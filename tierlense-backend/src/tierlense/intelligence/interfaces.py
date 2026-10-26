"""Provider interfaces; concrete providers can be replaced without changing the pipeline."""

from typing import Protocol

from tierlense.intelligence.schemas import (
    ExtractedFinding,
    FetchedDocument,
    OrganizationContext,
    RelevanceAssessment,
    SourceCandidate,
)


class SourceDiscoveryProvider(Protocol):
    def discover(self, organization: OrganizationContext, max_results: int) -> list[SourceCandidate]:
        """Discover candidate URLs for an organization."""


class SourceFetcher(Protocol):
    def fetch(self, url: str) -> FetchedDocument:
        """Fetch and extract text from one permitted public HTTP(S) source."""


class IntelligenceProvider(Protocol):
    def classify_relevance(
        self, organization: OrganizationContext, candidate: SourceCandidate
    ) -> RelevanceAssessment:
        """Assess whether a search result is relevant to the monitored organization."""

    def extract_findings(
        self,
        organization: OrganizationContext,
        candidate: SourceCandidate,
        document: FetchedDocument,
    ) -> list[ExtractedFinding]:
        """Extract claims supported by the supplied document text."""

    def classify_relevance_batch(
        self, organization: OrganizationContext, candidates: list[tuple[str, SourceCandidate]]
    ) -> dict[str, RelevanceAssessment]:
        """Classify a group of candidate sources in one validated model call."""

    def extract_findings_batch(
        self,
        organization: OrganizationContext,
        documents: list[tuple[str, SourceCandidate, FetchedDocument]],
    ) -> dict[str, list[ExtractedFinding]]:
        """Extract claims from bounded document groups, keyed by source identifier."""
