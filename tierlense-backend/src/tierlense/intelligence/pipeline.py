"""Evidence-first investigation workflow used by the background worker."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tierlense.core.config import Settings, get_settings
from tierlense.intelligence.errors import ProviderResponseError, SourceFetchError
from tierlense.intelligence.fetcher import canonicalize_url
from tierlense.intelligence.interfaces import IntelligenceProvider, SourceDiscoveryProvider, SourceFetcher
from tierlense.intelligence.metrics import JobMetricsRecorder, metrics_context
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
    EvidenceChange,
    InvestigationFinding,
    InvestigationJob,
    InvestigationSource,
    Organization,
    WatchProfile,
)
from tierlense.services.job_queue import complete_job, update_job_progress

SessionFactory = Callable[[], Session]
WHITESPACE_RE = re.compile(r"\s+")
SOURCE_TYPES = {"official", "news", "documentation", "regulatory", "financial", "research", "other"}
GENERIC_IDENTITY_TOKENS = {
    "the", "and", "for", "from", "with", "company", "corporation", "corporate", "corp",
    "inc", "incorporated", "llc", "ltd", "limited", "plc", "group", "global", "official",
    "software", "creative", "creatives", "service", "services", "solution", "solutions",
    "system", "systems", "technology", "technologies", "international", "holdings",
}
RELATIONSHIP_TERMS = re.compile(
    r"\b(suppl(?:y|ies|ied|ying)|supplier|vendor|customer|client|contract(?:ed)?|"
    r"procure(?:d|s|ment)?|purchas(?:e|es|ed)|depend(?:s|ed|ing)? on|rel(?:y|ies|ied) on|"
    r"use(?:s|d)? by|provid(?:e|es|ed) to|owned by|ownership|subsidiary|parent company|"
    r"acquir(?:e|es|ed)|manufactur(?:e|es|ed|ing) for|component for|distribut(?:e|es|ed) to|"
    r"partner(?:ed|ship)? with|operat(?:e|es|ed) for|customer of|service provider for)\b",
    flags=re.IGNORECASE,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_passage(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip().casefold()


def validate_finding_passage(finding: ExtractedFinding, content_text: str) -> str:
    """Validate whether the model's quoted support passage exists in the fetched text.

    This establishes provenance of the quote, not the independent truth of the claim.
    """
    if not finding.source_passage or not finding.source_passage.strip():
        return "needs_review"
    passage = normalize_passage(finding.source_passage)
    document = normalize_passage(content_text)
    if len(passage) < 12 or passage not in document:
        return "unsupported"
    return "passage_verified"


def _fingerprint(job_id: UUID, document_id: UUID, finding: ExtractedFinding) -> str:
    material = "|".join(
        [
            str(job_id),
            str(document_id),
            finding.finding_type.casefold().strip(),
            finding.subject_name.casefold().strip(),
            finding.predicate.casefold().strip(),
            (finding.object_value or "").casefold().strip(),
            finding.event_status.casefold().strip(),
            (finding.event_date or "").casefold().strip(),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _finding_semantic_key(finding: ExtractedFinding) -> tuple[str, ...]:
    """Stable claim key that does not depend on LLM paraphrasing of its summary."""
    return (
        finding.finding_type.casefold().strip(),
        _normalized_phrase(finding.subject_name),
        _normalized_phrase(finding.predicate),
        _normalized_phrase(finding.object_value or ""),
        finding.event_status.casefold().strip(),
        _normalized_phrase(finding.event_date or ""),
        _normalized_phrase(finding.related_entity_name or ""),
        _normalized_phrase(finding.relationship_type or ""),
    )


def _finding_from_record(record: InvestigationFinding) -> ExtractedFinding:
    return ExtractedFinding(
        finding_type=record.finding_type,
        subject_name=record.subject_name,
        predicate=record.predicate,
        object_value=record.object_value,
        summary=record.summary,
        event_status=record.event_status,
        event_date=record.event_date,
        source_passage=record.source_passage,
        confidence=record.model_confidence,
        **(record.structured_details or {}),
    )


def _source_type_for(candidate: SourceCandidate) -> str:
    return candidate.source_type


def _source_domain(url: str) -> str:
    return (urlsplit(url).hostname or "unknown").lower()[:255]


def _normalized_words(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").casefold())


def _normalized_phrase(value: str | None) -> str:
    return " ".join(_normalized_words(value))


def _identity_labels(organization: OrganizationContext) -> list[str]:
    return [label.strip() for label in [organization.name, *organization.identity_clues] if label and label.strip()]


def _has_identity_text(organization: OrganizationContext, texts: list[str | None]) -> bool:
    """Return true only when candidate/document text contains a name or distinctive alias anchor.

    Generic words such as "software", "creative" and "solutions" are deliberately not
    sufficient to associate a source with an organization.
    """
    words = set(word for value in texts for word in _normalized_words(value))
    combined = " " + " ".join(_normalized_words(" ".join(v or "" for v in texts))) + " "
    for label in _identity_labels(organization):
        label_words = _normalized_words(label)
        if not label_words:
            continue
        phrase = " " + " ".join(label_words) + " "
        if phrase in combined:
            return True
        distinctive = [
            word for word in label_words
            if len(word) >= 4 and word not in GENERIC_IDENTITY_TOKENS
        ]
        if any(word in words for word in distinctive):
            return True
    return False


def _hostname(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").casefold().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _is_official_domain(organization: OrganizationContext, url: str | None) -> bool:
    expected = _hostname(organization.website)
    actual = _hostname(url)
    return bool(expected and actual and (actual == expected or actual.endswith("." + expected)))


def candidate_has_identity_anchor(organization: OrganizationContext, candidate: SourceCandidate) -> bool:
    """Pre-filter candidates whose title/snippet/URL contain no identity anchor."""
    return _is_official_domain(organization, str(candidate.url)) or _has_identity_text(
        organization, [candidate.title, candidate.snippet, str(candidate.url)]
    )


def document_has_identity_anchor(organization: OrganizationContext, document: FetchedDocument) -> bool:
    """Confirm the fetched content is about the target, not merely a similar-named search hit."""
    return _is_official_domain(organization, document.url) or _has_identity_text(
        organization, [document.title, document.content_text]
    )


def finding_is_linked_to_organization(
    finding: ExtractedFinding,
    organization: OrganizationContext,
    document: FetchedDocument,
) -> bool:
    """Require a defensible link between a claim and the monitored organization.

    A quoted passage about an unrelated company is not accepted just because that
    company operates in the same industry. Supplier/ownership/dependency claims
    must quote the target, the claimed counterparty, and relationship language.
    """
    subject = _normalized_phrase(finding.subject_name)
    target_subject = any(subject == _normalized_phrase(label) for label in _identity_labels(organization))
    quoted_text = finding.source_passage or ""
    passage_has_target = _has_identity_text(organization, [quoted_text])
    normalized_passage = " " + _normalized_phrase(quoted_text) + " "
    subject_in_passage = bool(subject and " " + subject + " " in normalized_passage)
    relationship_types = {"supplier_relationship", "ownership_relationship", "technical_dependency"}
    impact_types = {"disruption_event", "financial_signal", "policy_change"}

    if finding.finding_type in relationship_types:
        if not passage_has_target or not RELATIONSHIP_TERMS.search(quoted_text):
            return False
        if target_subject:
            # If the target is the relationship subject, the other endpoint must be
            # present in the quoted passage too; a model-written object alone is not proof.
            other_endpoint = _normalized_phrase(finding.related_entity_name or finding.object_value or "")
            return bool(other_endpoint and " " + other_endpoint + " " in normalized_passage)
        return subject_in_passage

    if target_subject and (_is_official_domain(organization, document.url) or passage_has_target):
        return True

    if finding.finding_type in impact_types:
        return bool(passage_has_target and subject_in_passage and RELATIONSHIP_TERMS.search(quoted_text))

    # A matching company name in an AI-written summary is not enough; only the
    # source subject or quoted passage can establish relevance to the target.
    return False


def _context_from_records(organization: Organization, profile: WatchProfile | None) -> OrganizationContext:
    return OrganizationContext(
        id=str(organization.id),
        name=organization.name,
        website=organization.website,
        country_code=organization.country_code,
        description=organization.description,
        dependency_role=profile.dependency_role if profile else "supplier",
        products_services=list(profile.products_services or []) if profile else [],
        dependency_context=profile.dependency_context if profile else None,
        criticality=profile.criticality if profile else "medium",
        identity_clues=list(profile.identity_clues or []) if profile else [],
    )


class InvestigationPipeline:
    """Coordinates provider interfaces while persisting every evidence-bearing step."""

    def __init__(
        self,
        session_factory: SessionFactory,
        discovery: SourceDiscoveryProvider,
        fetcher: SourceFetcher,
        analyzer: IntelligenceProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.discovery = discovery
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.settings = settings or get_settings()

    def process(self, job_id: UUID) -> dict[str, int | str]:
        # Provider callbacks persist call/token metrics for successful and failed
        # requests, making provider use visible across retries.
        with metrics_context(JobMetricsRecorder(self.session_factory, job_id)):
            return self._process_job(job_id)

    def _process_job(self, job_id: UUID) -> dict[str, int | str]:
        organization_context = self._load_context(job_id)
        self._reconcile_persisted_organization_findings(organization_context)

        # Discovery is a durable checkpoint. Retries reuse source associations and
        # do not redo search or reset completed relevance/fetch work.
        associations = self._existing_association_ids(job_id)
        if associations:
            update_job_progress(
                self.session_factory,
                job_id,
                percent=3,
                message=f"Resuming {len(associations)} persisted source(s) for {organization_context.name}.",
                lease_seconds=self.settings.worker_lease_seconds,
            )
        else:
            update_job_progress(
                self.session_factory,
                job_id,
                percent=3,
                message=f"Searching public sources for {organization_context.name}.",
                lease_seconds=self.settings.worker_lease_seconds,
            )
            candidates = self.discovery.discover(
                organization_context, max_results=self.settings.max_sources_per_investigation
            )
            candidates = self._deduplicate_candidates(candidates)[: self.settings.max_sources_per_investigation]
            associations = self._persist_candidates(job_id, candidates)

        if not associations:
            summary = self._build_summary(job_id, message="The discovery provider returned no source URLs.")
            complete_job(self.session_factory, job_id, result_summary=summary)
            return summary

        # Deterministic identity pre-filter first; then one model request classifies
        # the complete bounded candidate set rather than one request per source.
        self._classify_pending_sources(organization_context, associations)

        ready_for_extraction: list[tuple[UUID, SourceCandidate, FetchedDocument, UUID]] = []
        total_sources = len(associations)
        for index, association_id in enumerate(associations, start=1):
            percent = 5 + int(((index - 1) / max(total_sources, 1)) * 70)
            update_job_progress(
                self.session_factory,
                job_id,
                percent=percent,
                message=f"Fetching relevant source {index} of {total_sources}.",
                lease_seconds=self.settings.worker_lease_seconds,
            )
            candidate = self._load_association(association_id)
            state = self._load_association_state(association_id)
            status = state["fetch_status"]
            if status == "processed":
                continue
            if status in {"skipped_irrelevant", "skipped_identity_unverified", "identity_unverified"}:
                continue

            if status != "fetched" and not candidate_has_identity_anchor(organization_context, candidate):
                self._save_relevance(
                    association_id,
                    RelevanceAssessment(
                        relevant=False,
                        score=0.0,
                        reason=(
                            "No reliable identity anchor matched the monitored organization in the search result, "
                            "known website, or configured identity clues."
                        ),
                        categories=["unrelated"],
                    ),
                )
                self._set_fetch_status(
                    association_id,
                    "skipped_identity_unverified",
                    "Automatic processing skipped because organization identity could not be established.",
                )
                continue

            was_reused = False
            if status == "fetched" and state["evidence_document_id"] is not None:
                fetched = self._load_fetched_document(state["evidence_document_id"])
                document_id = state["evidence_document_id"]
            else:
                if state["relevant"] is not None and state["relevance_score"] is not None:
                    relevance = RelevanceAssessment(
                        relevant=state["relevant"],
                        score=state["relevance_score"],
                        reason=state["relevance_reason"] or "Reused validated relevance assessment.",
                        categories=state["relevance_categories"] or [],
                    )
                else:
                    # Compatibility path for older analyzers not implementing batches.
                    relevance = self.analyzer.classify_relevance(organization_context, candidate)
                    self._save_relevance(association_id, relevance)
                if not relevance.relevant or relevance.score < self.settings.min_relevance_score:
                    self._set_fetch_status(association_id, "skipped_irrelevant", relevance.reason)
                    continue
                try:
                    fetched = self.fetcher.fetch(str(candidate.url))
                except SourceFetchError as exc:
                    self._set_fetch_status(association_id, "failed", str(exc))
                    continue
                document_id, was_reused = self._persist_document(association_id, fetched)

            # Fetched-page identity checks remain independent of model classification.
            if not document_has_identity_anchor(organization_context, fetched):
                self._set_fetch_status(
                    association_id,
                    "identity_unverified",
                    "Fetched content did not independently identify the monitored organization; extraction skipped.",
                )
                continue
            if status != "fetched":
                reused_count = self._reuse_unchanged_findings(
                    job_id=job_id,
                    association_id=association_id,
                    document_id=document_id,
                    content_text=fetched.content_text,
                    organization=organization_context,
                    candidate=candidate,
                    document=fetched,
                ) if 'was_reused' in locals() and was_reused else 0
                if reused_count:
                    continue
            ready_for_extraction.append((association_id, candidate, fetched, document_id))

        # Each model request handles a bounded group. The full source text is still
        # persisted and used locally for exact quote validation after extraction.
        for batch_index, document_batch in enumerate(self._group_extraction_batches(ready_for_extraction), start=1):
            update_job_progress(
                self.session_factory,
                job_id,
                percent=min(96, 78 + batch_index * 3),
                message=f"Extracting evidence from document batch {batch_index}.",
                lease_seconds=self.settings.worker_lease_seconds,
            )
            batch_inputs = [
                (str(association_id), candidate, fetched)
                for association_id, candidate, fetched, _document_id in document_batch
            ]
            method = getattr(self.analyzer, "extract_findings_batch", None)
            if callable(method):
                findings_by_source = method(organization_context, batch_inputs)
            else:
                findings_by_source = {
                    source_id: self.analyzer.extract_findings(organization_context, candidate, fetched)
                    for source_id, candidate, fetched in batch_inputs
                }
            expected_ids = {source_id for source_id, _candidate, _fetched in batch_inputs}
            if set(findings_by_source) != expected_ids:
                raise ProviderResponseError(
                    "Batch extraction did not return findings for each requested document exactly once."
                )

            for association_id, candidate, fetched, document_id in document_batch:
                saved_counts = self._persist_findings(
                    job_id=job_id,
                    organization_id=UUID(organization_context.id),
                    association_id=association_id,
                    document_id=document_id,
                    findings=findings_by_source[str(association_id)],
                    content_text=fetched.content_text,
                    organization=organization_context,
                    candidate=candidate,
                    document=fetched,
                )
                note = None
                if saved_counts["identity_rejected"]:
                    note = (
                        f"Extraction completed; {saved_counts['identity_rejected']} candidate claim(s) were not saved "
                        "because their quoted evidence did not establish a direct link to the monitored organization."
                    )
                self._set_fetch_status(association_id, "processed", note)

        # Only findings whose source passage is verified are promoted to graph facts/events.
        # Materialization is idempotent and leaves ambiguous relationship metadata for review.
        from tierlense.services.supply_chain import materialize_verified_findings

        with self.session_factory() as graph_db:
            graph_metrics = materialize_verified_findings(graph_db, job_id)
            from tierlense.services.operations import reassess_pending_evidence_changes
            reassessed_ids = reassess_pending_evidence_changes(graph_db, job_id)
            graph_db.commit()

        summary = self._build_summary(
            job_id,
            message=(
                "Evidence discovery and extraction completed. Claims are source-grounded and identity-checked; "
                "they are not independent proof of truth."
            ),
        )
        summary.update({
            "graph_entities_created": graph_metrics["entities_created"],
            "graph_relationships_created": graph_metrics["relationships_created"],
            "disruption_events_created": graph_metrics["events_created"],
            "evidence_changes_detected": self._count_evidence_changes(job_id),
            "risk_assessments_created_after_change": len(reassessed_ids),
        })
        complete_job(self.session_factory, job_id, result_summary=summary)
        return summary

    def _classify_pending_sources(self, organization: OrganizationContext, association_ids: list[UUID]) -> None:
        pending: list[tuple[str, SourceCandidate]] = []
        for association_id in association_ids:
            state = self._load_association_state(association_id)
            status = state["fetch_status"]
            if status in {"processed", "fetched", "skipped_irrelevant", "skipped_identity_unverified", "identity_unverified"}:
                continue
            if state["relevant"] is not None and state["relevance_score"] is not None:
                continue
            candidate = self._load_association(association_id)
            if not candidate_has_identity_anchor(organization, candidate):
                self._save_relevance(
                    association_id,
                    RelevanceAssessment(
                        relevant=False,
                        score=0.0,
                        reason=(
                            "No reliable identity anchor matched the monitored organization in the search result, "
                            "known website, or configured identity clues."
                        ),
                        categories=["unrelated"],
                    ),
                )
                self._set_fetch_status(
                    association_id,
                    "skipped_identity_unverified",
                    "Automatic processing skipped because organization identity could not be established.",
                )
                continue
            pending.append((str(association_id), candidate))

        batch_limit = max(1, int(self.settings.max_relevance_batch_size))
        for start in range(0, len(pending), batch_limit):
            batch = pending[start : start + batch_limit]
            method = getattr(self.analyzer, "classify_relevance_batch", None)
            if callable(method):
                assessments = method(organization, batch)
            else:
                assessments = {
                    source_id: self.analyzer.classify_relevance(organization, candidate)
                    for source_id, candidate in batch
                }
            expected = {source_id for source_id, _candidate in batch}
            if set(assessments) != expected:
                raise ProviderResponseError(
                    "Batch relevance classification did not return each requested source ID exactly once."
                )
            for source_id, _candidate in batch:
                self._save_relevance(UUID(source_id), assessments[source_id])

    def _group_extraction_batches(
        self, ready: list[tuple[UUID, SourceCandidate, FetchedDocument, UUID]]
    ) -> list[list[tuple[UUID, SourceCandidate, FetchedDocument, UUID]]]:
        if not ready:
            return []
        per_document_limit = min(
            self.settings.source_document_max_chars, self.settings.groq_extraction_max_input_chars
        )
        aggregate_limit = max(per_document_limit, int(self.settings.max_extraction_batch_input_chars))
        source_limit = max(1, int(self.settings.max_extraction_sources_per_batch))
        groups: list[list[tuple[UUID, SourceCandidate, FetchedDocument, UUID]]] = []
        current: list[tuple[UUID, SourceCandidate, FetchedDocument, UUID]] = []
        current_chars = 0
        for item in ready:
            size = min(len(item[2].content_text[: self.settings.source_document_max_chars]), per_document_limit)
            if current and (len(current) >= source_limit or current_chars + size > aggregate_limit):
                groups.append(current)
                current = []
                current_chars = 0
            current.append(item)
            current_chars += size
        if current:
            groups.append(current)
        return groups

    def _count_evidence_changes(self, job_id: UUID) -> int:
        from tierlense.models import EvidenceChange
        with self.session_factory() as db:
            return int(db.scalar(select(func.count(EvidenceChange.id)).where(EvidenceChange.job_id == job_id)) or 0)

    def _build_summary(self, job_id: UUID, *, message: str) -> dict[str, int | str]:
        """Build a cumulative summary from persisted state so retries stay idempotent."""
        with self.session_factory() as db:
            associations = list(
                db.scalars(select(InvestigationSource).where(InvestigationSource.job_id == job_id)).all()
            )
            findings = list(
                db.scalars(select(InvestigationFinding).where(InvestigationFinding.job_id == job_id)).all()
            )
            source_count = len(associations)
            relevant_count = sum(1 for item in associations if item.relevant is True)
            document_count = sum(1 for item in associations if item.evidence_document_id is not None)
            fetch_failed_count = sum(1 for item in associations if item.fetch_status == "failed")
            skipped_count = sum(
                1 for item in associations
                if item.fetch_status in {"skipped_irrelevant", "skipped_identity_unverified", "identity_unverified"}
            )
            return {
                "sources_discovered": source_count,
                "sources_relevant": relevant_count,
                "documents_fetched": document_count,
                "documents_reused": sum(1 for item in associations if item.evidence_document_id is not None and item.fetch_status == "processed" and bool(item.error_summary and "Unchanged content hash" in item.error_summary)),
                "evidence_changes_detected": int(db.scalar(select(func.count(EvidenceChange.id)).where(EvidenceChange.job_id == job_id)) or 0),
                "findings_extracted": len(findings),
                "passages_verified": sum(1 for item in findings if item.validation_status == "passage_verified"),
                "unsupported_findings": sum(1 for item in findings if item.validation_status == "unsupported"),
                "needs_review_findings": sum(1 for item in findings if item.validation_status == "needs_review"),
                "identity_rejected_sources": sum(
                    1 for item in associations
                    if item.fetch_status in {"skipped_identity_unverified", "identity_unverified"}
                ),
                "fetch_failures": fetch_failed_count,
                "sources_skipped": skipped_count,
                "message": message,
            }

    def _existing_association_ids(self, job_id: UUID) -> list[UUID]:
        with self.session_factory() as db:
            return list(
                db.scalars(
                    select(InvestigationSource.id)
                    .where(InvestigationSource.job_id == job_id)
                    .order_by(InvestigationSource.discovered_at.asc())
                ).all()
            )

    def _load_context(self, job_id: UUID) -> OrganizationContext:
        with self.session_factory() as db:
            job = db.get(InvestigationJob, job_id)
            if job is None:
                raise ValueError(f"Investigation job {job_id} does not exist")
            organization = db.get(Organization, job.organization_id)
            if organization is None:
                raise ValueError("Investigation organization no longer exists")
            profile = db.get(WatchProfile, organization.id)
            return _context_from_records(organization, profile)

    @staticmethod
    def _deduplicate_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        seen: set[str] = set()
        output: list[SourceCandidate] = []
        for candidate in candidates:
            try:
                url = canonicalize_url(str(candidate.url))
            except SourceFetchError:
                continue
            if url in seen:
                continue
            seen.add(url)
            output.append(candidate)
        return output

    def _persist_candidates(self, job_id: UUID, candidates: list[SourceCandidate]) -> list[UUID]:
        with self.session_factory() as db:
            job = db.get(InvestigationJob, job_id)
            if job is None:
                raise ValueError(f"Investigation job {job_id} does not exist")
            for candidate in candidates:
                try:
                    canonical_url = canonicalize_url(str(candidate.url))
                except SourceFetchError:
                    continue
                source = db.scalar(select(DiscoveredSource).where(DiscoveredSource.canonical_url == canonical_url))
                if source is None:
                    source = DiscoveredSource(
                        canonical_url=canonical_url,
                        source_domain=_source_domain(canonical_url),
                        title=candidate.title[:1000],
                        source_type=_source_type_for(candidate),
                    )
                    db.add(source)
                    db.flush()
                else:
                    source.last_seen_at = utc_now()
                    if candidate.title and candidate.title != "Untitled source":
                        source.title = candidate.title[:1000]
                    if candidate.source_type != "other":
                        source.source_type = candidate.source_type
                association = db.scalar(
                    select(InvestigationSource).where(
                        InvestigationSource.job_id == job_id,
                        InvestigationSource.source_id == source.id,
                    )
                )
                if association is None:
                    association = InvestigationSource(
                        job_id=job_id,
                        source_id=source.id,
                        search_query=candidate.search_query or None,
                        discovery_snippet=candidate.snippet or None,
                    )
                    db.add(association)
                    db.flush()
                    # Incremental scans may reuse a previous relevance result when the
                    # same canonical source and exact discovery snippet recur. The page
                    # is still fetched so its content hash can be compared.
                    previous = db.scalar(
                        select(InvestigationSource)
                        .join(InvestigationJob, InvestigationJob.id == InvestigationSource.job_id)
                        .where(
                            InvestigationSource.source_id == source.id,
                            InvestigationSource.job_id != job_id,
                            InvestigationSource.relevant.is_not(None),
                            InvestigationSource.relevance_score.is_not(None),
                            InvestigationSource.discovery_snippet == (candidate.snippet or None),
                            InvestigationJob.organization_id == job.organization_id,
                        )
                        .order_by(InvestigationSource.discovered_at.desc())
                        .limit(1)
                    )
                    if previous is not None:
                        association.relevant = previous.relevant
                        association.relevance_score = previous.relevance_score
                        association.relevance_reason = "Reused prior relevance assessment for the same canonical source and unchanged discovery snippet; document is re-fetched to detect content changes."
                        association.relevance_categories = list(previous.relevance_categories or [])
                else:
                    # Refresh useful search metadata without erasing completed work.
                    # A queued retry can therefore resume from fetched/processed state.
                    association.search_query = candidate.search_query or association.search_query
                    if candidate.snippet:
                        association.discovery_snippet = candidate.snippet
            db.commit()
            return list(
                db.scalars(
                    select(InvestigationSource.id)
                    .where(InvestigationSource.job_id == job_id)
                    .order_by(InvestigationSource.discovered_at.asc())
                ).all()
            )

    def _load_association(self, association_id: UUID) -> SourceCandidate:
        with self.session_factory() as db:
            association = db.get(InvestigationSource, association_id)
            if association is None:
                raise ValueError(f"Investigation source {association_id} does not exist")
            source = db.get(DiscoveredSource, association.source_id)
            if source is None:
                raise ValueError("Discovered source record no longer exists")
            candidate = SourceCandidate(
                url=source.canonical_url,
                title=source.title or source.source_domain,
                snippet=association.discovery_snippet or "",
                source_type=source.source_type if source.source_type in SOURCE_TYPES else "other",
                search_query=association.search_query or "",
            )
            return candidate

    def _load_association_state(self, association_id: UUID) -> dict:
        with self.session_factory() as db:
            association = db.get(InvestigationSource, association_id)
            if association is None:
                raise ValueError(f"Investigation source {association_id} does not exist")
            return {
                "fetch_status": association.fetch_status,
                "relevant": association.relevant,
                "relevance_score": association.relevance_score,
                "relevance_reason": association.relevance_reason,
                "relevance_categories": list(association.relevance_categories or []),
                "evidence_document_id": association.evidence_document_id,
            }

    def _load_fetched_document(self, document_id: UUID) -> FetchedDocument:
        with self.session_factory() as db:
            document = db.get(EvidenceDocument, document_id)
            if document is None:
                raise ValueError(f"Evidence document {document_id} does not exist")
            source = db.get(DiscoveredSource, document.source_id)
            if source is None:
                raise ValueError("Evidence document source no longer exists")
            return FetchedDocument(
                url=source.canonical_url,
                title=document.title,
                content_type=document.content_type,
                content_text=document.content_text,
                content_hash=document.content_hash,
                fetched_at=document.fetched_at,
                published_at=document.published_at,
                http_status=document.http_status,
                is_truncated=document.is_truncated,
                metadata=dict(document.metadata_json or {}),
            )

    def _reconcile_persisted_organization_findings(
        self, organization: OrganizationContext
    ) -> None:
        """Revalidate this organization's full finding history before new work starts."""
        organization_id = UUID(organization.id)
        with self.session_factory() as db:
            rows = list(
                db.execute(
                    select(InvestigationSource.id, InvestigationSource.evidence_document_id)
                    .join(InvestigationJob, InvestigationJob.id == InvestigationSource.job_id)
                    .where(InvestigationJob.organization_id == organization_id)
                    .order_by(InvestigationSource.discovered_at.asc())
                ).all()
            )

        for association_id, document_id in rows:
            # A finding without a stored source document cannot satisfy the evidence-first
            # contract. Keep other source records intact, but remove unsupported claims.
            if document_id is None:
                with self.session_factory() as db:
                    db.execute(
                        delete(InvestigationFinding).where(
                            InvestigationFinding.investigation_source_id == association_id
                        )
                    )
                    db.commit()
                continue

            document = self._load_fetched_document(document_id)
            if not document_has_identity_anchor(organization, document):
                self._set_fetch_status(
                    association_id,
                    "identity_unverified",
                    "Stored source does not establish the monitored organization identity; attached findings were removed.",
                )
                continue

            candidate = self._load_association(association_id)
            self._revalidate_existing_findings(association_id, organization, candidate, document)

    def _revalidate_existing_findings(
        self,
        association_id: UUID,
        organization: OrganizationContext,
        candidate: SourceCandidate,
        document: FetchedDocument,
    ) -> int:
        """Remove legacy claims that fail current identity checks; recheck quote status."""
        removed = 0
        with self.session_factory() as db:
            records = list(
                db.scalars(
                    select(InvestigationFinding).where(
                        InvestigationFinding.investigation_source_id == association_id
                    )
                ).all()
            )
            for record in records:
                try:
                    finding = _finding_from_record(record)
                except Exception:
                    db.delete(record)
                    removed += 1
                    continue
                if not finding_is_linked_to_organization(finding, organization, document):
                    db.delete(record)
                    removed += 1
                    continue
                record.validation_status = validate_finding_passage(finding, document.content_text)
            if removed:
                association = db.get(InvestigationSource, association_id)
                if association is not None:
                    association.error_summary = (
                        f"Removed {removed} previously stored finding(s) that did not meet current organization-identity checks."
                    )[:4000]
                    association.updated_at = utc_now()
            db.commit()
        return removed

    def _save_relevance(self, association_id: UUID, relevance) -> None:
        with self.session_factory() as db:
            association = db.get(InvestigationSource, association_id)
            if association is None:
                return
            association.relevant = relevance.relevant
            association.relevance_score = relevance.score
            association.relevance_reason = relevance.reason
            association.relevance_categories = relevance.categories
            association.fetch_status = "classified"
            association.error_summary = None
            association.updated_at = utc_now()
            db.commit()

    def _set_fetch_status(self, association_id: UUID, status: str, error: str | None) -> None:
        with self.session_factory() as db:
            association = db.get(InvestigationSource, association_id)
            if association is None:
                return
            if status in {"skipped_irrelevant", "skipped_identity_unverified", "identity_unverified"}:
                # Keep the source/document as audit evidence, but do not leave claims
                # attached to this organization after the source fails identity triage.
                db.execute(
                    delete(InvestigationFinding).where(
                        InvestigationFinding.investigation_source_id == association_id
                    )
                )
            association.fetch_status = status
            association.error_summary = error[:4000] if error else None
            association.updated_at = utc_now()
            db.commit()

    def _persist_document(self, association_id: UUID, fetched: FetchedDocument) -> tuple[UUID, bool]:
        """Persist a content version and detect transitions from the last observed hash."""
        with self.session_factory() as db:
            association = db.get(InvestigationSource, association_id)
            if association is None:
                raise ValueError("Investigation-source association no longer exists")
            job = db.get(InvestigationJob, association.job_id)
            if job is None:
                raise ValueError("Investigation job no longer exists")
            source = db.get(DiscoveredSource, association.source_id)
            if source is None:
                raise ValueError("Discovered source record no longer exists")

            now = utc_now()
            source.last_seen_at = now
            if fetched.title:
                source.title = fetched.title[:1000]

            previous_hash = source.latest_content_hash
            previous_document_id = source.latest_document_id
            if not previous_hash:
                previous_document = db.scalar(
                    select(EvidenceDocument)
                    .where(EvidenceDocument.source_id == source.id)
                    .order_by(EvidenceDocument.fetched_at.desc())
                    .limit(1)
                )
                if previous_document is not None:
                    previous_hash = previous_document.content_hash
                    previous_document_id = previous_document.id

            document = db.scalar(
                select(EvidenceDocument).where(
                    EvidenceDocument.source_id == source.id,
                    EvidenceDocument.content_hash == fetched.content_hash,
                )
            )
            reused = document is not None
            if document is None:
                document = EvidenceDocument(
                    source_id=source.id,
                    content_hash=fetched.content_hash,
                    title=fetched.title,
                    content_type=fetched.content_type,
                    content_text=fetched.content_text,
                    content_length=len(fetched.content_text),
                    http_status=fetched.http_status,
                    published_at=fetched.published_at,
                    fetched_at=fetched.fetched_at,
                    is_truncated=fetched.is_truncated,
                    metadata_json=fetched.metadata,
                )
                db.add(document)
                db.flush()
            else:
                # EvidenceDocument represents a content version; do not rewrite the
                # original version timestamp when unchanged content is observed again.
                document.http_status = fetched.http_status

            changed = bool(previous_hash and previous_hash != fetched.content_hash)
            if changed:
                db.add(EvidenceChange(
                    organization_id=job.organization_id,
                    job_id=job.id,
                    source_id=source.id,
                    previous_document_id=previous_document_id,
                    current_document_id=document.id,
                    previous_content_hash=previous_hash,
                    current_content_hash=fetched.content_hash,
                    change_type="content_changed",
                    reassessment_status="pending",
                    reassessment_details={
                        "trigger": "incremental_scan",
                        "reused_historical_content_version": reused,
                        "note": "Source hash changed relative to the last observed version; reassessment is queued after graph materialization.",
                    },
                    detected_at=now,
                ))
                source.last_content_changed_at = now

            source.latest_content_hash = fetched.content_hash
            source.latest_document_id = document.id
            association.evidence_document_id = document.id
            association.fetch_status = "fetched"
            association.error_summary = None
            association.updated_at = now
            db.commit()
            return document.id, reused

    def _reuse_unchanged_findings(
        self,
        *,
        job_id: UUID,
        association_id: UUID,
        document_id: UUID,
        content_text: str,
        organization: OrganizationContext,
        candidate: SourceCandidate,
        document: FetchedDocument,
    ) -> int:
        """Copy previously verified claims for an unchanged content version into this scan snapshot."""
        with self.session_factory() as db:
            current_job = db.get(InvestigationJob, job_id)
            if current_job is None:
                return 0
            prior_rows = list(db.scalars(
                select(InvestigationFinding)
                .join(InvestigationJob, InvestigationJob.id == InvestigationFinding.job_id)
                .where(
                    InvestigationFinding.organization_id == current_job.organization_id,
                    InvestigationFinding.job_id != job_id,
                    InvestigationFinding.evidence_document_id == document_id,
                    InvestigationFinding.validation_status == "passage_verified",
                    InvestigationJob.status == "completed",
                )
                .order_by(InvestigationFinding.created_at.desc())
            ).all())
            copied = 0
            seen_keys: set[tuple[str, ...]] = set()
            for prior in prior_rows:
                finding = _finding_from_record(prior)
                if validate_finding_passage(finding, content_text) != "passage_verified":
                    continue
                if not finding_is_linked_to_organization(finding, organization, document):
                    continue
                key = _finding_semantic_key(finding)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                db.add(InvestigationFinding(
                    job_id=job_id,
                    organization_id=current_job.organization_id,
                    investigation_source_id=association_id,
                    evidence_document_id=document_id,
                    fingerprint=_fingerprint(job_id, document_id, finding),
                    finding_type=prior.finding_type,
                    subject_name=prior.subject_name,
                    predicate=prior.predicate,
                    object_value=prior.object_value,
                    summary=prior.summary,
                    event_status=prior.event_status,
                    event_date=prior.event_date,
                    source_passage=prior.source_passage,
                    model_confidence=prior.model_confidence,
                    validation_status="passage_verified",
                    structured_details=dict(prior.structured_details or {}),
                ))
                copied += 1
            if copied:
                association = db.get(InvestigationSource, association_id)
                if association is not None:
                    association.fetch_status = "processed"
                    association.error_summary = "Unchanged content hash; reused previously passage-verified findings without another model call."
            db.commit()
            return copied

    def _persist_findings(
        self,
        *,
        job_id: UUID,
        organization_id: UUID,
        association_id: UUID,
        document_id: UUID,
        findings: list[ExtractedFinding],
        content_text: str,
        organization: OrganizationContext,
        candidate: SourceCandidate,
        document: FetchedDocument,
    ) -> dict[str, int]:
        counts = {
            "created": 0, "passage_verified": 0, "unsupported": 0,
            "needs_review": 0, "identity_rejected": 0,
        }
        # Clean up records created by an earlier attempt/version before comparing keys.
        self._revalidate_existing_findings(association_id, organization, candidate, document)
        with self.session_factory() as db:
            existing_rows = list(
                db.scalars(
                    select(InvestigationFinding).where(
                        InvestigationFinding.job_id == job_id,
                        InvestigationFinding.investigation_source_id == association_id,
                        InvestigationFinding.evidence_document_id == document_id,
                    )
                ).all()
            )
            existing_keys = {_finding_semantic_key(_finding_from_record(row)) for row in existing_rows}
            for finding in findings:
                validation_status = validate_finding_passage(finding, content_text)
                if not finding_is_linked_to_organization(finding, organization, document):
                    counts["identity_rejected"] += 1
                    continue
                semantic_key = _finding_semantic_key(finding)
                if semantic_key in existing_keys:
                    # Idempotency survives LLM paraphrasing and the previous fingerprint version.
                    continue
                fingerprint = _fingerprint(job_id, document_id, finding)
                if validation_status in counts:
                    counts[validation_status] += 1
                db.add(
                    InvestigationFinding(
                        job_id=job_id,
                        organization_id=organization_id,
                        investigation_source_id=association_id,
                        evidence_document_id=document_id,
                        fingerprint=fingerprint,
                        finding_type=finding.finding_type,
                        subject_name=finding.subject_name,
                        predicate=finding.predicate,
                        object_value=finding.object_value,
                        summary=finding.summary,
                        event_status=finding.event_status,
                        event_date=finding.event_date,
                        source_passage=finding.source_passage,
                        model_confidence=finding.confidence,
                        validation_status=validation_status,
                        structured_details={
                            key: value
                            for key, value in finding.model_dump(mode="json").items()
                            if key in {
                                "related_entity_name", "related_entity_type", "relationship_type",
                                "component_or_service", "ownership_percentage", "is_state_owned",
                                "country_code", "disruption_type", "severity",
                            } and value is not None
                        },
                    )
                )
                counts["created"] += 1
                existing_keys.add(semantic_key)
            db.commit()
        return counts

