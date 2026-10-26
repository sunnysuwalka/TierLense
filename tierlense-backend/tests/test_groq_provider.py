"""Groq provider contract tests use fake SDK responses; no API key/network is needed."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tierlense.core.config import Settings
from tierlense.intelligence.errors import ProviderConfigurationError, ProviderRateLimitError, ProviderRequestError
from tierlense.intelligence.groq_provider import (
    GroqBrowserSearchProvider,
    GroqIntelligenceProvider,
    parse_search_candidates,
    retry_after_seconds_from_error,
)
from tierlense.intelligence.schemas import FetchedDocument, OrganizationContext, SourceCandidate


class FakeCompletions:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.contents.pop(0)
        if isinstance(item, BaseException):
            raise item
        if hasattr(item, "choices"):
            return item
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=item))])


class FakeClient:
    def __init__(self, contents):
        self.chat = SimpleNamespace(completions=FakeCompletions(contents))


def _organization():
    return OrganizationContext(
        id="org-1",
        name="Arisun Creatives",
        products_services=["software solutions"],
        criticality="high",
    )


def test_retry_after_parser_reads_provider_message_and_header():
    class RateLimited(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "5"})

    assert retry_after_seconds_from_error(RateLimited("rate limited")) == 5.0
    assert retry_after_seconds_from_error(Exception("Try again in 3.39s")) == 3.39
    assert retry_after_seconds_from_error(Exception("Please try again in 6m33.552s")) == pytest.approx(393.552)


def test_search_provider_translates_429_to_queue_aware_error():
    class RateLimited(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "7"})

    class RateLimitedCompletions:
        def create(self, **kwargs):
            raise RateLimited("tokens per minute exceeded")

    client = SimpleNamespace(chat=SimpleNamespace(completions=RateLimitedCompletions()))
    provider = GroqBrowserSearchProvider(Settings(), client=client)
    with pytest.raises(ProviderRateLimitError) as raised:
        provider.discover(_organization(), max_results=3)
    assert raised.value.retry_after_seconds == 7.0
    assert "rate limit" in str(raised.value).casefold()


def test_relevance_falls_back_once_without_json_mode_and_validates_schema():
    relevance = json.dumps({
        "relevant": True,
        "score": 0.8,
        "reason": "The source describes an NVIDIA AI initiative.",
        "categories": ["company_update"],
    })
    client = FakeClient([_json_validation_error(), relevance])
    provider = GroqIntelligenceProvider(Settings(), client=client)

    assessment = provider.classify_relevance(
        _organization(),
        SourceCandidate(url="https://example.com", title="Example", snippet="A public page"),
    )

    calls = client.chat.completions.calls
    assert assessment.relevant is True
    assert assessment.score == 0.8
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert calls[0]["max_completion_tokens"] <= 350
    assert calls[1]["max_completion_tokens"] <= 350
    assert calls[0]["reasoning_effort"] == "low"
    assert calls[1]["reasoning_effort"] == "low"
    assert "short string" in calls[1]["messages"][0]["content"]


@pytest.mark.parametrize(
    "bad_output",
    [
        "This is not JSON",
        json.dumps({"relevant": True, "score": 1.5, "reason": "bad score", "categories": []}),
    ],
)
def test_relevance_rejects_invalid_fallback_without_classifying_source(bad_output):
    client = FakeClient([_json_validation_error(), bad_output])
    provider = GroqIntelligenceProvider(Settings(), client=client)

    with pytest.raises(ProviderRequestError, match="relevance fallback returned invalid JSON") as raised:
        provider.classify_relevance(
            _organization(),
            SourceCandidate(url="https://example.com", title="Example", snippet="A public page"),
        )

    assert raised.value.provider_code == "fallback_invalid_output"
    assert len(client.chat.completions.calls) == 2
    assert "response_format" not in client.chat.completions.calls[1]
    assert "JSON object" in str(raised.value) or "schema fields" in str(raised.value)


def test_relevance_falls_back_when_initial_response_fails_local_schema_validation():
    initial_invalid = json.dumps({"relevant": "yes", "score": 1.7, "reason": "invalid", "categories": []})
    fallback_valid = json.dumps({
        "relevant": True,
        "score": 0.82,
        "reason": "The page is about a company-specific initiative.",
        "categories": ["company_update"],
    })
    client = FakeClient([initial_invalid, fallback_valid])
    provider = GroqIntelligenceProvider(Settings(groq_analysis_model="some-compatible-model"), client=client)

    assessment = provider.classify_relevance(
        _organization(),
        SourceCandidate(url="https://example.com", title="Example", snippet="A public page"),
    )

    calls = client.chat.completions.calls
    assert assessment.relevant is True
    assert assessment.score == pytest.approx(0.82)
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert calls[0]["max_completion_tokens"] <= 350
    assert calls[1]["max_completion_tokens"] <= 350


def test_reasoning_effort_is_only_sent_to_gpt_oss_models():
    client = FakeClient([json.dumps({
        "relevant": False,
        "score": 0.1,
        "reason": "The source is not about the organization.",
        "categories": ["unrelated"],
    })])
    settings = Settings(groq_analysis_model="llama-3.3-70b-versatile")
    provider = GroqIntelligenceProvider(settings, client=client)
    provider.classify_relevance(
        _organization(),
        SourceCandidate(url="https://example.com", title="Example", snippet="A public page"),
    )
    assert "reasoning_effort" not in client.chat.completions.calls[0]


def _sample_document(text="A source reports a production outage at Example Supplier."):
    return FetchedDocument(
        url="https://example.com/news",
        title="Supplier event",
        content_type="text/html",
        content_text=text,
        content_hash="a" * 64,
        fetched_at=datetime.now(timezone.utc),
    )


def _sample_findings_payload():
    return json.dumps({"findings": [{
        "finding_type": "disruption_event",
        "subject_name": "Example Supplier",
        "predicate": "reported_outage",
        "object_value": "production outage",
        "summary": "A source reports a production outage.",
        "event_status": "reported",
        "event_date": None,
        "source_passage": "A source reports a production outage at Example Supplier.",
        "confidence": 0.8,
    }]})


def _json_validation_error():
    class BadRequestError(Exception):
        status_code = 400
        response = SimpleNamespace(status_code=400, headers={})
        body = {
            "error": {
                "message": "Failed to validate JSON. Please adjust your prompt. See failed_generation for details.",
                "code": "json_validate_failed",
            }
        }

    return BadRequestError("Groq rejected JSON; code=json_validate_failed")


def test_extraction_falls_back_once_without_json_mode_and_still_validates_schema():
    client = FakeClient([_json_validation_error(), _sample_findings_payload()])
    provider = GroqIntelligenceProvider(Settings(), client=client)
    candidate = SourceCandidate(url="https://example.com/news", title="Supplier event", snippet="outage")

    findings = provider.extract_findings(_organization(), candidate, _sample_document())

    assert len(findings) == 1
    assert findings[0].source_passage == "A source reports a production outage at Example Supplier."
    assert len(client.chat.completions.calls) == 2
    assert client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in client.chat.completions.calls[1]
    assert client.chat.completions.calls[1]["max_completion_tokens"] <= 1400
    assert client.chat.completions.calls[0]["reasoning_effort"] == "low"
    assert client.chat.completions.calls[1]["reasoning_effort"] == "low"
    fallback_system = client.chat.completions.calls[1]["messages"][0]["content"]
    assert "exact quote" in fallback_system
    assert "outside knowledge" in fallback_system


@pytest.mark.parametrize(
    "bad_output",
    [
        "This is not JSON",
        json.dumps({"findings": [{"not_a_valid_finding": True}]}),
    ],
)
def test_extraction_rejects_invalid_fallback_output_without_returning_findings(bad_output):
    client = FakeClient([_json_validation_error(), bad_output])
    provider = GroqIntelligenceProvider(Settings(), client=client)
    candidate = SourceCandidate(url="https://example.com/news", title="Supplier event", snippet="outage")

    with pytest.raises(ProviderRequestError, match="fallback returned invalid JSON") as raised:
        provider.extract_findings(_organization(), candidate, _sample_document())

    assert raised.value.provider_code == "fallback_invalid_output"
    assert len(client.chat.completions.calls) == 2
    assert "response_format" not in client.chat.completions.calls[1]


def test_extraction_bounds_model_input_and_completion_budget():
    text = "HEAD-OF-DOCUMENT. " + ("repeated content " * 1000) + " TAIL-OF-DOCUMENT."
    settings = Settings(
        groq_extraction_max_input_chars=1000,
        groq_extraction_max_completion_tokens=500,
    )
    client = FakeClient([json.dumps({"findings": []})])
    provider = GroqIntelligenceProvider(settings, client=client)
    candidate = SourceCandidate(url="https://example.com/news", title="Supplier event", snippet="context")

    findings = provider.extract_findings(_organization(), candidate, _sample_document(text))

    sent_payload = json.loads(client.chat.completions.calls[0]["messages"][1]["content"])
    sent_text = sent_payload["document_text"]
    assert findings == []
    assert len(sent_text) <= 1000
    assert "HEAD-OF-DOCUMENT" in sent_text
    assert "TAIL-OF-DOCUMENT" in sent_text
    assert "Middle of document omitted" in sent_text
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 500


def test_search_provider_uses_browser_search_and_parses_candidates():
    payload = {"sources": [{"url": "https://example.com/news", "title": "Service update", "snippet": "A service update", "source_type": "news", "published_at": None, "search_query": "service update"}]}
    client = FakeClient([json.dumps(payload)])
    provider = GroqBrowserSearchProvider(Settings(), client=client)
    results = provider.discover(_organization(), max_results=3)
    assert len(results) == 1
    assert results[0].title == "Service update"
    call = client.chat.completions.calls[0]
    assert call["tools"] == [{"type": "browser_search"}]
    assert call["tool_choice"] == "required"


def test_search_candidate_parser_falls_back_to_direct_urls():
    results = parse_search_candidates("Found source https://example.com/a and https://example.org/b.", query="test", limit=5)
    assert [str(item.url) for item in results] == ["https://example.com/a", "https://example.org/b"]


def test_analysis_provider_validates_relevance_and_extracts_findings():
    relevance = {"relevant": True, "score": 0.8, "reason": "Supplier event", "categories": ["disruption_event"]}
    findings = {"findings": [{
        "finding_type": "disruption_event",
        "subject_name": "Example Supplier",
        "predicate": "reported_outage",
        "object_value": "production outage",
        "summary": "A source reports a production outage.",
        "event_status": "reported",
        "event_date": None,
        "source_passage": "A source reports a production outage at Example Supplier.",
        "confidence": 0.8,
    }]}
    client = FakeClient([json.dumps(relevance), json.dumps(findings)])
    provider = GroqIntelligenceProvider(Settings(), client=client)
    org = _organization()
    candidate = SourceCandidate(url="https://example.com/news", title="Supplier event", snippet="outage", source_type="news")
    assessment = provider.classify_relevance(org, candidate)
    document = FetchedDocument(
        url="https://example.com/news",
        title="Supplier event",
        content_type="text/html",
        content_text="A source reports a production outage at Example Supplier.",
        content_hash="a" * 64,
        fetched_at=datetime.now(timezone.utc),
    )
    extracted = provider.extract_findings(org, candidate, document)
    assert assessment.relevant is True
    assert len(extracted) == 1
    assert client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert client.chat.completions.calls[1]["response_format"] == {"type": "json_object"}


def test_missing_key_fails_with_actionable_configuration_error():
    provider = GroqBrowserSearchProvider(Settings(groq_api_key=None))
    with pytest.raises(ProviderConfigurationError, match="GROQ_API_KEY"):
        provider.discover(_organization(), max_results=3)


def test_search_provider_extracts_urls_from_groq_browser_tool_metadata():
    browser_result = SimpleNamespace(
        title="Official service status",
        url="https://status.example.com/incidents/123",
        content="The provider reports a service interruption affecting customers.",
    )
    executed_tool = SimpleNamespace(
        type="browser_search",
        browser_results=[browser_result],
        search_results=None,
        output=None,
    )
    # Browser-search final text may show citation markers rather than literal URLs.
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="The company published a status update. 〖1†L1-L3〗",
                    executed_tools=[executed_tool],
                    annotations=[],
                )
            )
        ]
    )
    provider = GroqBrowserSearchProvider(Settings(), client=FakeClient([response]))

    results = provider.discover(_organization(), max_results=3)

    assert len(results) == 1
    assert str(results[0].url) == "https://status.example.com/incidents/123"
    assert results[0].title == "Official service status"
    assert "service interruption" in results[0].snippet


def test_search_provider_extracts_urls_from_search_results_metadata():
    search_result = SimpleNamespace(
        title="Regulatory filing",
        url="https://registry.example.gov/company/123",
        content="Public filing about the monitored entity.",
        score=0.91,
    )
    executed_tool = SimpleNamespace(
        type="browser_search",
        browser_results=[],
        search_results=SimpleNamespace(results=[search_result]),
        output=None,
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="I found a public filing, see citation 〖1†L1-L2〗.",
                    executed_tools=[executed_tool],
                    annotations=[],
                )
            )
        ]
    )
    provider = GroqBrowserSearchProvider(Settings(), client=FakeClient([response]))

    results = provider.discover(_organization(), max_results=3)

    assert len(results) == 1
    assert str(results[0].url) == "https://registry.example.gov/company/123"
    assert results[0].title == "Regulatory filing"
