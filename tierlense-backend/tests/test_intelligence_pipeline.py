"""Integration tests for discovery-to-evidence persistence without external services."""

import hashlib
import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tierlense.core.config import Settings
from tierlense.db.base import Base
from tierlense.intelligence.pipeline import InvestigationPipeline
from tierlense.intelligence.schemas import (
    ExtractedFinding,
    FetchedDocument,
    OrganizationContext,
    RelevanceAssessment,
    SourceCandidate,
)
from tierlense.models import (
    DiscoveredSource,
    EvidenceDocument,
    InvestigationFinding,
    InvestigationJob,
    InvestigationSource,
    Organization,
    WatchProfile,
)
from tierlense import models  # noqa: F401


class FakeDiscovery:
    def __init__(self):
        self.calls = 0

    def discover(self, organization: OrganizationContext, max_results: int):
        self.calls += 1
        return [
            SourceCandidate(
                url="https://example.com/incident?utm_source=test",
                title="Arisun Creatives factory update",
                snippet="Arisun Creatives relies on Example Supplier, which reported a temporary factory interruption.",
                source_type="news",
                search_query="supplier factory interruption",
            )
        ][:max_results]


class FakeFetcher:
    def __init__(self):
        self.calls = 0

    def fetch(self, url: str):
        self.calls += 1
        text = (
            "Arisun Creatives relies on Example Supplier, which reported a factory fire "
            "that halted production for two days."
        )
        return FetchedDocument(
            url="https://example.com/incident",
            title="Arisun Creatives factory update",
            content_type="text/html",
            content_text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
        )


class FakeAnalyzer:
    def __init__(self):
        self.classify_calls = 0
        self.extract_calls = 0

    def classify_relevance(self, organization: OrganizationContext, candidate: SourceCandidate):
        self.classify_calls += 1
        assert organization.name == "Arisun Creatives"
        return RelevanceAssessment(
            relevant=True,
            score=0.92,
            reason="The source describes an operational disruption relevant to a supplier.",
            categories=["disruption_event"],
        )

    def extract_findings(self, organization: OrganizationContext, candidate: SourceCandidate, document: FetchedDocument):
        self.extract_calls += 1
        return [
            ExtractedFinding(
                finding_type="disruption_event",
                subject_name="Example Supplier",
                predicate="reported_factory_disruption",
                object_value="production halted for two days",
                summary="The source reports a factory fire that halted production for two days.",
                event_status="reported",
                event_date=None,
                source_passage=(
                    "Arisun Creatives relies on Example Supplier, which reported a factory fire "
                    "that halted production for two days."
                ),
                confidence=0.91,
            )
        ]


def _test_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_investigation_discovers_fetches_extracts_and_persists_evidence():
    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(
                organization=organization,
                dependency_role="software_service_provider",
                products_services=["software solutions"],
                dependency_context="Important software services",
                criticality="high",
                identity_clues=[],
            )
            job = InvestigationJob(organization=organization, job_type="initial_scan", status="running", scheduled_at=datetime.now(timezone.utc), attempt_count=1)
            db.add_all([organization, profile, job])
            db.commit()
            job_id = job.id
            organization_id = organization.id

        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            max_sources_per_investigation=8,
            min_relevance_score=0.45,
            source_document_max_chars=120000,
        )
        analyzer = FakeAnalyzer()
        pipeline = InvestigationPipeline(factory, FakeDiscovery(), FakeFetcher(), analyzer, settings)
        summary = pipeline.process(job_id)

        with factory() as db:
            job = db.get(InvestigationJob, job_id)
            assert job.status == "completed"
            assert job.progress_percent == 100
            assert job.result_summary["sources_discovered"] == 1
            assert job.result_summary["sources_relevant"] == 1
            assert job.result_summary["findings_extracted"] == 1
            assert db.scalar(select(func.count(DiscoveredSource.id))) == 1
            assert db.scalar(select(func.count(EvidenceDocument.id))) == 1
            assert db.scalar(select(func.count(InvestigationSource.id))) == 1
            assert db.scalar(select(func.count(InvestigationFinding.id))) == 1
            finding = db.scalar(select(InvestigationFinding).where(InvestigationFinding.organization_id == organization_id))
            assert finding is not None
            assert finding.validation_status == "passage_verified"
            assert "factory fire" in finding.source_passage
        assert summary["passages_verified"] == 1
    finally:
        engine.dispose()


def test_retry_does_not_repeat_processed_sources_or_duplicate_findings():
    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(
                organization=organization,
                dependency_role="software_service_provider",
                products_services=["software solutions"],
                dependency_context="Important software services",
                criticality="high",
                identity_clues=[],
            )
            job = InvestigationJob(
                organization=organization, job_type="initial_scan", status="running",
                scheduled_at=datetime.now(timezone.utc), attempt_count=1,
            )
            db.add_all([organization, profile, job])
            db.commit()
            job_id = job.id

        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            max_sources_per_investigation=8,
            min_relevance_score=0.45,
            source_document_max_chars=120000,
        )
        analyzer = FakeAnalyzer()
        pipeline = InvestigationPipeline(factory, FakeDiscovery(), FakeFetcher(), analyzer, settings)
        first = pipeline.process(job_id)
        second = pipeline.process(job_id)

        with factory() as db:
            assert db.scalar(select(func.count(DiscoveredSource.id))) == 1
            assert db.scalar(select(func.count(EvidenceDocument.id))) == 1
            assert db.scalar(select(func.count(InvestigationSource.id))) == 1
            assert db.scalar(select(func.count(InvestigationFinding.id))) == 1
        assert first["findings_extracted"] == second["findings_extracted"] == 1
        assert analyzer.classify_calls == 1
        assert analyzer.extract_calls == 1
    finally:
        engine.dispose()


def test_retry_after_extraction_rate_limit_reuses_fetched_document():
    from tierlense.intelligence.errors import ProviderRateLimitError

    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(
                organization=organization,
                dependency_role="software_service_provider",
                products_services=["software solutions"],
                dependency_context="Important software services",
                criticality="high",
                identity_clues=[],
            )
            job = InvestigationJob(
                organization=organization, job_type="initial_scan", status="running",
                scheduled_at=datetime.now(timezone.utc), attempt_count=1,
            )
            db.add_all([organization, profile, job])
            db.commit()
            job_id = job.id

        class RateLimitOnceAnalyzer(FakeAnalyzer):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def extract_findings(self, organization, candidate, document):
                self.attempts += 1
                if self.attempts == 1:
                    raise ProviderRateLimitError("provider rate limited", retry_after_seconds=4)
                return super().extract_findings(organization, candidate, document)

        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            max_sources_per_investigation=8,
            min_relevance_score=0.45,
            source_document_max_chars=120000,
        )
        analyzer = RateLimitOnceAnalyzer()
        fetcher = FakeFetcher()
        discovery = FakeDiscovery()
        pipeline = InvestigationPipeline(factory, discovery, fetcher, analyzer, settings)

        try:
            pipeline.process(job_id)
            raise AssertionError("First extraction should simulate a transient rate limit")
        except ProviderRateLimitError:
            pass
        # A worker retry invokes the same pipeline/job after the queue delay.
        result = pipeline.process(job_id)

        with factory() as db:
            assert db.scalar(select(func.count(EvidenceDocument.id))) == 1
            assert db.scalar(select(func.count(InvestigationFinding.id))) == 1
            association = db.scalar(select(InvestigationSource).where(InvestigationSource.job_id == job_id))
            assert association.fetch_status == "processed"
        assert discovery.calls == 1
        assert fetcher.calls == 1
        assert analyzer.classify_calls == 1
        assert analyzer.attempts == 2
        assert analyzer.extract_calls == 1
        assert result["findings_extracted"] == 1
    finally:
        engine.dispose()


def test_similar_name_source_is_rejected_before_ai_or_fetch():
    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(
                organization=organization,
                dependency_role="software_service_provider",
                products_services=["software solutions"],
                dependency_context="Important software services",
                criticality="high",
                identity_clues=[],
            )
            job = InvestigationJob(
                organization=organization, job_type="initial_scan", status="running",
                scheduled_at=datetime.now(timezone.utc), attempt_count=1,
            )
            db.add_all([organization, profile, job])
            db.commit()
            job_id = job.id

        class SimilarNameDiscovery:
            def discover(self, organization, max_results):
                return [SourceCandidate(
                    url="https://linkedin.com/company/serious-group",
                    title="SERIOUSTEC: Software for Creatives",
                    snippet="Software for creatives; the result describes SERIOUSTEC.",
                    source_type="other",
                    search_query="Arisun Creatives software solutions",
                )]

        class NeverFetcher:
            def fetch(self, url):
                raise AssertionError("Unverified similar-name source must not be fetched")

        class NeverAnalyzer:
            def classify_relevance(self, organization, candidate):
                raise AssertionError("Unverified similar-name source must not consume an LLM call")

            def extract_findings(self, organization, candidate, document):
                raise AssertionError("No findings should be extracted")

        settings = Settings(database_url="sqlite+pysqlite:///:memory:")
        pipeline = InvestigationPipeline(factory, SimilarNameDiscovery(), NeverFetcher(), NeverAnalyzer(), settings)
        summary = pipeline.process(job_id)

        with factory() as db:
            association = db.scalar(select(InvestigationSource).where(InvestigationSource.job_id == job_id))
            assert association.fetch_status == "skipped_identity_unverified"
            assert association.relevant is False
            assert db.scalar(select(func.count(InvestigationFinding.id))) == 0
        assert summary["identity_rejected_sources"] == 1
        assert summary["findings_extracted"] == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "source_url, source_title, source_text, finding_subject, finding_object, quoted_passage",
    [
        (
            "https://linkedin.com/company/serious-group",
            "SERIOUSTEC: Software for Creatives",
            "Founded 2004. Company size 11-50 employees.",
            "SERIOUSTEC",
            "2004",
            "Founded 2004.",
        ),
        (
            "https://linkedin.com/company/artisun-id-creative",
            "artisun",
            "Founded in 2022 as an independent production house.",
            "Artisun Creative",
            "2022",
            "Founded in 2022 as an independent production house.",
        ),
    ],
)
def test_legacy_unrelated_findings_are_removed_when_fetched_source_fails_identity(
    source_url, source_title, source_text, finding_subject, finding_object, quoted_passage
):
    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(
                organization=organization,
                dependency_role="software_service_provider",
                products_services=["software solutions"],
                dependency_context="Important software services",
                criticality="high",
                identity_clues=[],
            )
            job = InvestigationJob(
                organization=organization, job_type="manual_scan", status="running",
                scheduled_at=datetime.now(timezone.utc), attempt_count=2,
            )
            source = DiscoveredSource(
                canonical_url=source_url,
                source_domain="linkedin.com",
                title=source_title,
                source_type="other",
            )
            db.add_all([organization, profile, job, source])
            db.flush()
            text = source_text
            document = EvidenceDocument(
                source_id=source.id,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                title=source_title,
                content_type="text/html",
                content_text=text,
                content_length=len(text),
                http_status=200,
                fetched_at=datetime.now(timezone.utc),
                metadata_json={},
            )
            db.add(document)
            db.flush()
            association = InvestigationSource(
                job_id=job.id,
                source_id=source.id,
                evidence_document_id=document.id,
                search_query="Arisun Creatives software solutions",
                discovery_snippet="Software for creatives; the result describes SERIOUSTEC.",
                relevant=True,
                relevance_score=0.9,
                relevance_reason="Legacy overly broad relevance decision",
                relevance_categories=["company_update"],
                fetch_status="fetched",
            )
            db.add(association)
            db.flush()
            db.add(InvestigationFinding(
                job_id=job.id,
                organization_id=organization.id,
                investigation_source_id=association.id,
                evidence_document_id=document.id,
                fingerprint="f" * 64,
                finding_type="company_update",
                subject_name=finding_subject,
                predicate="founded",
                object_value=finding_object,
                summary=f"{finding_subject} was founded in {finding_object}.",
                event_status="reported",
                event_date=None,
                source_passage=quoted_passage,
                model_confidence=1.0,
                validation_status="passage_verified",
            ))
            db.commit()
            job_id = job.id

        class SameCandidateDiscovery:
            def discover(self, organization, max_results):
                return [SourceCandidate(
                    url="https://linkedin.com/company/serious-group",
                    title="SERIOUSTEC: Software for Creatives",
                    snippet="Software for creatives; the result describes SERIOUSTEC.",
                    source_type="other",
                    search_query="Arisun Creatives software solutions",
                )]

        class NeverCalledFetcher:
            def fetch(self, url):
                raise AssertionError("A stored document should be rechecked without refetching")

        class NeverCalledAnalyzer:
            def classify_relevance(self, organization, candidate):
                raise AssertionError("A fetched source without identity must not be reclassified")

            def extract_findings(self, organization, candidate, document):
                raise AssertionError("A source without identity must not generate findings")

        settings = Settings(database_url="sqlite+pysqlite:///:memory:")
        pipeline = InvestigationPipeline(factory, SameCandidateDiscovery(), NeverCalledFetcher(), NeverCalledAnalyzer(), settings)
        summary = pipeline.process(job_id)

        with factory() as db:
            association = db.scalar(select(InvestigationSource).where(InvestigationSource.job_id == job_id))
            assert association.fetch_status == "identity_unverified"
            assert db.scalar(select(func.count(InvestigationFinding.id))) == 0
            assert db.scalar(select(func.count(EvidenceDocument.id))) == 1
        assert summary["findings_extracted"] == 0
        assert summary["identity_rejected_sources"] == 1
    finally:
        engine.dispose()


def test_new_investigation_reconciles_findings_from_prior_failed_jobs():
    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(
                organization=organization,
                dependency_role="software_service_provider",
                products_services=["software solutions"],
                dependency_context="Important software services",
                criticality="high",
                identity_clues=[],
            )
            old_job = InvestigationJob(
                organization=organization, job_type="manual_scan", status="failed",
                scheduled_at=datetime.now(timezone.utc), attempt_count=3,
            )
            new_job = InvestigationJob(
                organization=organization, job_type="manual_scan", status="running",
                scheduled_at=datetime.now(timezone.utc), attempt_count=1,
            )
            source = DiscoveredSource(
                canonical_url="https://linkedin.com/company/serious-group",
                source_domain="linkedin.com",
                title="SERIOUSTEC: Software for Creatives",
                source_type="other",
            )
            db.add_all([organization, profile, old_job, new_job, source])
            db.flush()
            text = "Founded 2004. Company size 11-50 employees."
            document = EvidenceDocument(
                source_id=source.id,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                title="SERIOUSTEC: Software for Creatives",
                content_type="text/html",
                content_text=text,
                content_length=len(text),
                http_status=200,
                fetched_at=datetime.now(timezone.utc),
                metadata_json={},
            )
            db.add(document)
            db.flush()
            association = InvestigationSource(
                job_id=old_job.id,
                source_id=source.id,
                evidence_document_id=document.id,
                search_query="Arisun Creatives software solutions",
                discovery_snippet="Search result about SERIOUSTEC.",
                relevant=True,
                relevance_score=0.9,
                relevance_reason="Legacy broad match",
                relevance_categories=["company_update"],
                fetch_status="fetched",
            )
            db.add(association)
            db.flush()
            db.add(InvestigationFinding(
                job_id=old_job.id,
                organization_id=organization.id,
                investigation_source_id=association.id,
                evidence_document_id=document.id,
                fingerprint="e" * 64,
                finding_type="company_update",
                subject_name="SERIOUSTEC",
                predicate="founded",
                object_value="2004",
                summary="SERIOUSTEC was founded in 2004.",
                event_status="reported",
                event_date=None,
                source_passage="Founded 2004. Company size 11-50 employees.",
                model_confidence=1.0,
                validation_status="passage_verified",
            ))
            db.commit()
            new_job_id = new_job.id
            old_job_id = old_job.id

        class EmptyDiscovery:
            def discover(self, organization, max_results):
                return []

        class NeverCalledFetcher:
            def fetch(self, url):
                raise AssertionError("Historical reconciliation must use saved documents")

        class NeverCalledAnalyzer:
            def classify_relevance(self, organization, candidate):
                raise AssertionError("No discovery candidates expected")

            def extract_findings(self, organization, candidate, document):
                raise AssertionError("No discovery candidates expected")

        settings = Settings(database_url="sqlite+pysqlite:///:memory:")
        pipeline = InvestigationPipeline(factory, EmptyDiscovery(), NeverCalledFetcher(), NeverCalledAnalyzer(), settings)
        pipeline.process(new_job_id)

        with factory() as db:
            assert db.scalar(select(func.count(InvestigationFinding.id)).where(InvestigationFinding.job_id == old_job_id)) == 0
            old_association = db.scalar(select(InvestigationSource).where(InvestigationSource.job_id == old_job_id))
            assert old_association.fetch_status == "identity_unverified"
            assert db.scalar(select(func.count(EvidenceDocument.id))) == 1
    finally:
        engine.dispose()


def test_finding_about_unrelated_company_is_not_linked_to_target():
    from tierlense.intelligence.pipeline import finding_is_linked_to_organization

    organization = OrganizationContext(id="org-1", name="Arisun Creatives", products_services=["software solutions"])
    candidate = SourceCandidate(
        url="https://linkedin.com/company/serious-group",
        title="SERIOUSTEC: Software for Creatives",
        snippet="",
    )
    document = FetchedDocument(
        url=str(candidate.url), title=candidate.title, content_type="text/html",
        content_text="Founded 2004. Company size 11-50 employees.", content_hash="b" * 64,
        fetched_at=datetime.now(timezone.utc),
    )
    finding = ExtractedFinding(
        finding_type="company_update", subject_name="SERIOUSTEC", predicate="founded",
        object_value="2004", summary="SERIOUSTEC was founded in 2004.",
        event_status="reported", source_passage="Founded 2004", confidence=1.0,
    )
    assert not finding_is_linked_to_organization(finding, organization, document)

    weak_relationship = ExtractedFinding(
        finding_type="supplier_relationship", subject_name="SERIOUSTEC", predicate="supplies",
        object_value="software", summary="SERIOUSTEC supplies software to Arisun Creatives.",
        event_status="reported", source_passage="Arisun Creatives reported a supplier issue.", confidence=0.8,
    )
    assert not finding_is_linked_to_organization(weak_relationship, organization, document)


def test_finding_quote_must_exist_in_source_text():
    from tierlense.intelligence.pipeline import validate_finding_passage

    grounded = ExtractedFinding(
        finding_type="company_update",
        subject_name="Example Inc",
        predicate="announced",
        object_value="a service change",
        summary="Example Inc announced a service change.",
        event_status="reported",
        source_passage="Example Inc announced a service change in March.",
        confidence=0.8,
    )
    assert validate_finding_passage(grounded, "Example Inc announced a service change in March.") == "passage_verified"
    assert validate_finding_passage(grounded, "A completely unrelated document.") == "unsupported"


def test_pipeline_batches_relevance_and_extraction_for_multiple_sources():
    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Arisun Creatives", identity_status="unverified")
            profile = WatchProfile(organization=organization, dependency_role="service_provider", products_services=["software"])
            job = InvestigationJob(organization=organization, job_type="initial_scan", status="running", scheduled_at=datetime.now(timezone.utc), attempt_count=1)
            db.add_all([organization, profile, job])
            db.commit()
            job_id = job.id

        class MultiDiscovery:
            def discover(self, organization, max_results):
                return [SourceCandidate(
                    url=f"https://example.com/updates/{i}",
                    title=f"Arisun Creatives supplier update {i}",
                    snippet=f"Arisun Creatives update {i} about Example Supplier.",
                    source_type="news",
                ) for i in range(1, 4)][:max_results]

        class MultiFetcher:
            def fetch(self, url):
                text = "Arisun Creatives relies on Example Supplier, which reported a factory fire that halted production for two days."
                return FetchedDocument(
                    url=url, title="Arisun Creatives supplier update", content_type="text/html",
                    content_text=text, content_hash=hashlib.sha256((url + text).encode()).hexdigest(),
                    fetched_at=datetime.now(timezone.utc), http_status=200,
                )

        class BatchAnalyzer(FakeAnalyzer):
            def __init__(self):
                super().__init__()
                self.relevance_batches = 0
                self.extraction_batches = 0

            def classify_relevance_batch(self, organization, candidates):
                self.relevance_batches += 1
                return {source_id: self.classify_relevance(organization, candidate)
                        for source_id, candidate in candidates}

            def extract_findings_batch(self, organization, documents):
                self.extraction_batches += 1
                return {source_id: self.extract_findings(organization, candidate, document)
                        for source_id, candidate, document in documents}

        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            max_sources_per_investigation=8,
            max_relevance_batch_size=8,
            max_extraction_batch_input_chars=18000,
            max_extraction_sources_per_batch=3,
        )
        analyzer = BatchAnalyzer()
        pipeline = InvestigationPipeline(factory, MultiDiscovery(), MultiFetcher(), analyzer, settings)
        summary = pipeline.process(job_id)

        assert summary["sources_discovered"] == 3
        assert analyzer.relevance_batches == 1
        assert analyzer.extraction_batches == 1
        with factory() as db:
            rows = list(db.scalars(select(InvestigationSource).where(InvestigationSource.job_id == job_id)).all())
            assert len(rows) == 3
            assert all(row.fetch_status == "processed" for row in rows)
    finally:
        engine.dispose()


def test_provider_request_metrics_are_persisted_by_stage_and_provider():
    from tierlense.intelligence.metrics import JobMetricsRecorder, metrics_context, provider_attempt, provider_stage, record_provider_request

    engine, factory = _test_db()
    try:
        with factory() as db:
            organization = Organization(name="Metrics Test")
            job = InvestigationJob(organization=organization, job_type="initial_scan", status="running", scheduled_at=datetime.now(timezone.utc))
            db.add(job)
            db.commit()
            job_id = job.id

        with metrics_context(JobMetricsRecorder(factory, job_id)):
            with provider_stage("batch relevance classification"):
                record_provider_request(
                    "Groq", success=True,
                    response={"usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}},
                    model="openai/gpt-oss-120b",
                )
                with provider_attempt("fallback"):
                    record_provider_request(
                        "OpenRouter", success=False, status_code=429, error_code="rate_limit_exceeded",
                        model="openrouter/free",
                    )

        with factory() as db:
            job = db.get(InvestigationJob, job_id)
            metrics = job.execution_metrics
            assert metrics["totals"]["requests"] == 2
            assert metrics["totals"]["fallback_requests"] == 1
            assert metrics["totals"]["total_tokens"] == 150
            assert metrics["queue_attempt_count"] == 0
            groq = metrics["providers"]["Groq"]["stages"]["batch relevance classification"]
            assert groq["successes"] == 1 and groq["total_tokens"] == 150
            assert groq["models"] == ["openai/gpt-oss-120b"]
            openrouter = metrics["providers"]["OpenRouter"]["stages"]["batch relevance classification"]
            assert openrouter["failures"] == 1 and openrouter["last_status_code"] == 429
            assert openrouter["fallback_requests"] == 1
    finally:
        engine.dispose()
