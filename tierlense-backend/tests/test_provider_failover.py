"""Failover order, cooldown, and OpenAI-compatible request contract tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from tierlense.core.config import Settings
from tierlense.intelligence.compatible_client import OpenAICompatibleHTTPClient
from tierlense.intelligence.errors import ProviderRateLimitError, ProviderRequestError, ProviderResponseError
from tierlense.intelligence.provider_adapters import (
    MistralIntelligenceProvider,
    OpenRouterBrowserSearchProvider,
    OpenRouterIntelligenceProvider,
)
from tierlense.intelligence.provider_failover import (
    FailoverIntelligenceProvider,
    FailoverSourceDiscoveryProvider,
    ProviderCooldownRegistry,
)
from tierlense.intelligence.schemas import (
    FetchedDocument,
    OrganizationContext,
    RelevanceAssessment,
    SourceCandidate,
)


def _organization():
    return OrganizationContext(
        id="org-1",
        name="Example Components Ltd",
        products_services=["industrial components"],
        criticality="high",
    )


def _candidate():
    return SourceCandidate(
        url="https://example.com/news",
        title="Example supplier update",
        snippet="A manufacturing update",
        source_type="news",
    )


def _relevance():
    return RelevanceAssessment(
        relevant=True,
        score=0.91,
        reason="The page is an organization-specific update.",
        categories=["company_update"],
    )


class FakeIntelligence:
    def __init__(self, provider_name, classification=None, classification_error=None):
        self.provider_name = provider_name
        self.classification = classification or _relevance()
        self.classification_error = classification_error
        self.classification_calls = 0
        self.extraction_calls = 0

    def classify_relevance(self, organization, candidate):
        self.classification_calls += 1
        if self.classification_error:
            error, self.classification_error = self.classification_error, None
            raise error
        return self.classification

    def extract_findings(self, organization, candidate, document):
        self.extraction_calls += 1
        return []


class FakeDiscovery:
    def __init__(self, provider_name, results=None, error=None):
        self.provider_name = provider_name
        self.results = results or []
        self.error = error
        self.calls = 0

    def discover(self, organization, max_results):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results[:max_results]


def test_intelligence_falls_back_in_order_and_cools_down_rate_limited_provider():
    groq = FakeIntelligence(
        "Groq",
        classification_error=ProviderRateLimitError("daily quota", retry_after_seconds=30),
    )
    openrouter = FakeIntelligence("OpenRouter")
    mistral = FakeIntelligence("Mistral")
    cooldowns = ProviderCooldownRegistry()
    chain = FailoverIntelligenceProvider(
        [groq, openrouter, mistral], cooldowns=cooldowns, failure_cooldown_seconds=60
    )

    result = chain.classify_relevance(_organization(), _candidate())

    assert result.score == pytest.approx(0.91)
    assert groq.classification_calls == 1
    assert openrouter.classification_calls == 1
    assert mistral.classification_calls == 0

    # Shared cooldown means the next source is sent directly to OpenRouter.
    result2 = chain.classify_relevance(_organization(), _candidate())
    assert result2.relevant is True
    assert groq.classification_calls == 1
    assert openrouter.classification_calls == 2


def test_intelligence_falls_back_after_groq_json_validation_request_error():
    # Groq's malformed/failed JSON response is a non-retryable request error at
    # the provider layer, but should still trigger a different provider in-chain.
    groq = FakeIntelligence(
        "Groq",
        classification_error=ProviderRequestError(
            "Groq rejected JSON generation", status_code=400, provider_code="json_validate_failed"
        ),
    )
    openrouter = FakeIntelligence("OpenRouter")
    chain = FailoverIntelligenceProvider([groq, openrouter])

    result = chain.classify_relevance(_organization(), _candidate())

    assert result.relevant is True
    assert groq.classification_calls == 1
    assert openrouter.classification_calls == 1


def test_source_discovery_falls_back_to_openrouter_after_groq_rate_limit():
    source = _candidate()
    groq = FakeDiscovery("Groq", error=ProviderRateLimitError("TPD quota", retry_after_seconds=45))
    openrouter = FakeDiscovery("OpenRouter", results=[source])
    mistral = FakeDiscovery("Mistral", results=[_candidate()])
    chain = FailoverSourceDiscoveryProvider([groq, openrouter, mistral])

    found = chain.discover(_organization(), max_results=4)

    assert found == [source]
    assert groq.calls == 1
    assert openrouter.calls == 1
    assert mistral.calls == 0


def test_all_rate_limited_providers_return_retry_delay_for_queue():
    groq = FakeIntelligence("Groq", classification_error=ProviderRateLimitError("quota", 10))
    openrouter = FakeIntelligence("OpenRouter", classification_error=ProviderRateLimitError("quota", 50))
    chain = FailoverIntelligenceProvider([groq, openrouter])

    with pytest.raises(ProviderRateLimitError) as raised:
        chain.classify_relevance(_organization(), _candidate())

    assert raised.value.retry_after_seconds == 50


def test_mixed_rate_limit_and_other_failure_waits_for_longest_existing_cooldown():
    cooldowns = ProviderCooldownRegistry()
    cooldowns.put("Groq", 120)
    groq = FakeIntelligence("Groq")
    openrouter = FakeIntelligence(
        "OpenRouter",
        classification_error=ProviderRequestError(
            "fallback output was invalid", provider_code="fallback_invalid_output"
        ),
    )
    mistral = FakeIntelligence(
        "Mistral",
        classification_error=ProviderRateLimitError("provider quota", retry_after_seconds=35),
    )
    chain = FailoverIntelligenceProvider(
        [groq, openrouter, mistral], cooldowns=cooldowns, failure_cooldown_seconds=60
    )

    with pytest.raises(ProviderRateLimitError) as raised:
        chain.classify_relevance(_organization(), _candidate())

    assert raised.value.retry_after_seconds >= 119
    assert groq.classification_calls == 0
    assert openrouter.classification_calls == 1
    assert mistral.classification_calls == 1


def test_openrouter_retries_once_when_first_relevance_response_fails_schema_validation():
    class FakeCompletions:
        def __init__(self):
            self.calls = []
            self.contents = [
                json.dumps({"relevant": "yes", "score": 1.7, "reason": "bad", "categories": []}),
                json.dumps({
                    "relevant": True,
                    "score": 0.83,
                    "reason": "The source is about an organization-specific update.",
                    "categories": ["company_update"],
                }),
            ]

        def create(self, **kwargs):
            self.calls.append(kwargs)
            content = self.contents.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    completions = FakeCompletions()
    provider = OpenRouterIntelligenceProvider(
        Settings(openrouter_analysis_model="openrouter/free"),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    result = provider.classify_relevance(_organization(), _candidate())

    assert result.relevant is True
    assert result.score == pytest.approx(0.83)
    assert len(completions.calls) == 2
    assert completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in completions.calls[1]


def test_openrouter_adapter_uses_configured_model_and_server_search_tool():
    class FakeCompletions:
        def __init__(self, content):
            self.content = content
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
            )

    content = json.dumps({"sources": [{
        "url": "https://example.com/news",
        "title": "Supplier update",
        "snippet": "A supplier update",
        "source_type": "news",
    }]})
    completions = FakeCompletions(content)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = Settings(openrouter_api_key="unused-in-fake", openrouter_search_model="qwen/test-model")
    provider = OpenRouterBrowserSearchProvider(settings, client=client)

    results = provider.discover(_organization(), max_results=2)

    assert len(results) == 1
    call = completions.calls[0]
    assert call["model"] == "qwen/test-model"
    assert call["tools"] == [{
        "type": "openrouter:web_search",
        "parameters": {
            "engine": "exa",
            "max_results": 5,
            "max_uses": 2,
            "max_total_results": 10,
            "search_context_size": "low",
        },
    }]
    assert "tool_choice" not in call



def test_openrouter_search_falls_back_to_dynamic_free_router_on_unavailable_model():
    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise ProviderRequestError("model unavailable", status_code=404, provider_code="model_not_found")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "sources": [{"url": "https://example.com/supplier", "title": "Supplier", "source_type": "news"}]
            })))])

    completions = FakeCompletions()
    provider = OpenRouterBrowserSearchProvider(
        Settings(openrouter_api_key="fake", openrouter_search_model="qwen/example:free"),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    result = provider.discover(_organization(), max_results=2)

    assert len(result) == 1
    assert [call["model"] for call in completions.calls] == ["qwen/example:free", "openrouter/free"]


def test_openrouter_analysis_falls_back_to_dynamic_free_router_on_unavailable_model():
    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise ProviderRequestError("model unavailable", status_code=404, provider_code="model_not_found")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "relevant": True, "score": 0.8, "reason": "Company-specific", "categories": ["company_update"]
            })))])

    completions = FakeCompletions()
    provider = OpenRouterIntelligenceProvider(
        Settings(openrouter_analysis_model="qwen/example:free"),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    result = provider.classify_relevance(_organization(), _candidate())

    assert result.relevant
    assert [call["model"] for call in completions.calls] == ["qwen/example:free", "openrouter/free"]

def test_openrouter_and_mistral_use_their_configured_analysis_models():
    class FakeCompletions:
        def __init__(self, content):
            self.content = content
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
            )

    content = json.dumps({
        "relevant": True,
        "score": 0.8,
        "reason": "Organization-specific content",
        "categories": ["company_update"],
    })
    for provider_cls, settings, expected_model in (
        (OpenRouterIntelligenceProvider, Settings(openrouter_analysis_model="qwen/custom"), "qwen/custom"),
        (MistralIntelligenceProvider, Settings(mistral_analysis_model="mistral-custom"), "mistral-custom"),
    ):
        completions = FakeCompletions(content)
        provider = provider_cls(settings, client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
        result = provider.classify_relevance(_organization(), _candidate())
        assert result.relevant
        assert completions.calls[0]["model"] == expected_model


def test_openai_compatible_client_maps_completion_budget_and_bearer_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
        })

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleHTTPClient(
        provider_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-secret",
        timeout_seconds=5,
        http_client=http_client,
    )
    try:
        client.chat.completions.create(
            model="qwen/test",
            messages=[{"role": "user", "content": "hello"}],
            max_completion_tokens=350,
        )
    finally:
        http_client.close()

    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer test-secret"
    assert seen["body"]["max_tokens"] == 350
    assert "max_completion_tokens" not in seen["body"]


def test_mistral_discovery_uses_conversations_web_search_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "outputs": [{
                "type": "message.output",
                "content": json.dumps({"sources": [{
                    "url": "https://example.org/supplier-update",
                    "title": "Supplier update",
                    "snippet": "A manufacturer update.",
                    "source_type": "news",
                    "published_at": None,
                    "search_query": "supplier update",
                }]}),
            }],
        })

    from tierlense.intelligence.provider_adapters import MistralBrowserSearchProvider

    settings = Settings(mistral_api_key="mistral-test", mistral_search_model="mistral-test-model")
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MistralBrowserSearchProvider(settings, http_client=http_client)
    try:
        candidates = provider.discover(_organization(), max_results=3)
    finally:
        http_client.close()

    assert len(candidates) == 1
    assert str(candidates[0].url) == "https://example.org/supplier-update"
    assert seen["url"] == "https://api.mistral.ai/v1/conversations"
    assert seen["auth"] == "Bearer mistral-test"
    assert seen["body"]["model"] == "mistral-test-model"
    assert seen["body"]["tools"] == [{"type": "web_search"}]
    assert [item["role"] for item in seen["body"]["inputs"]] == ["user"]
    assert "You are TierLense's public-source discovery component" in seen["body"]["inputs"][0]["content"]
    assert "Research request:" in seen["body"]["inputs"][0]["content"]



def test_openrouter_defaults_use_dynamic_free_router():
    settings = Settings()
    assert settings.openrouter_search_model == "openrouter/free"
    assert settings.openrouter_analysis_model == "openrouter/free"

def test_provider_factory_keeps_groq_openrouter_mistral_priority():
    from tierlense.intelligence.provider_factory import build_provider_chains

    settings = Settings(
        groq_api_key="groq-test",
        openrouter_api_key="openrouter-test",
        mistral_api_key="mistral-test",
    )
    discovery, intelligence = build_provider_chains(settings)

    assert [provider.provider_name for provider in discovery.providers] == ["Groq", "OpenRouter", "Mistral"]
    assert [provider.provider_name for provider in intelligence.providers] == ["Groq", "OpenRouter", "Mistral"]
    assert discovery.cooldowns is intelligence.cooldowns


def test_openrouter_batch_relevance_uses_one_strict_schema_request_for_multiple_sources():
    candidates = [
        ("source-1", _candidate()),
        ("source-2", SourceCandidate(
            url="https://example.com/regulatory", title="Example Components regulatory filing",
            snippet="A current filing about Example Components", source_type="regulatory",
        )),
    ]
    payload = {"assessments": [
        {"source_id": "source-1", "relevant": True, "score": 0.9, "reason": "Company-specific supplier update", "categories": ["supplier_relationship"]},
        {"source_id": "source-2", "relevant": True, "score": 0.8, "reason": "Organization-specific filing", "categories": ["financial_signal"]},
    ]}

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return {"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 300, "completion_tokens": 100, "total_tokens": 400}}

    completions = FakeCompletions()
    provider = OpenRouterIntelligenceProvider(
        Settings(openrouter_analysis_model="openrouter/free"),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    result = provider.classify_relevance_batch(_organization(), candidates)

    assert set(result) == {"source-1", "source-2"}
    assert result["source-1"].relevant is True
    assert result["source-2"].categories == ["financial_signal"]
    assert len(completions.calls) == 1
    assert completions.calls[0]["response_format"]["type"] == "json_schema"
    assert completions.calls[0]["max_completion_tokens"] == provider.settings.groq_relevance_max_completion_tokens


def test_openrouter_batch_extraction_binds_findings_to_each_source_in_one_call():
    from tierlense.intelligence.schemas import FetchedDocument

    now = datetime.now(timezone.utc)
    documents = [
        ("source-1", _candidate(), FetchedDocument(
            url="https://example.com/news", title="Arisun update", content_type="text/html",
            content_text="Arisun Creatives reported that Example Supplier expanded factory capacity.",
            content_hash="hash-one", fetched_at=now,
        )),
        ("source-2", SourceCandidate(
            url="https://example.com/news-2", title="Arisun service update", snippet="Arisun service news",
            source_type="news",
        ), FetchedDocument(
            url="https://example.com/news-2", title="Arisun service update", content_type="text/html",
            content_text="Arisun Creatives announced a software service update.",
            content_hash="hash-two", fetched_at=now,
        )),
    ]
    payload = {"documents": [
        {"source_id": "source-1", "findings": [{
            "finding_type": "supplier_relationship", "subject_name": "Arisun Creatives",
            "predicate": "uses", "object_value": "Example Supplier", "summary": "Arisun Creatives uses Example Supplier.",
            "event_status": "reported", "event_date": None,
            "source_passage": "Arisun Creatives reported that Example Supplier expanded factory capacity.", "confidence": 0.8,
        }]},
        {"source_id": "source-2", "findings": []},
    ]}

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    completions = FakeCompletions()
    provider = OpenRouterIntelligenceProvider(
        Settings(openrouter_analysis_model="openrouter/free"),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    result = provider.extract_findings_batch(_organization(), documents)

    assert set(result) == {"source-1", "source-2"}
    assert len(result["source-1"]) == 1
    assert result["source-2"] == []
    assert len(completions.calls) == 1
    assert completions.calls[0]["response_format"]["type"] == "json_schema"
