"""Bounded source fetching and URL policy tests; all HTTP responses are mocked."""

import httpx
import pytest

from tierlense.core.config import Settings
from tierlense.intelligence.errors import SourceFetchError
from tierlense.intelligence.fetcher import HttpSourceFetcher, canonicalize_url


def test_canonicalize_url_removes_tracking_parameters_and_fragment():
    assert canonicalize_url("https://example.com/story?utm_source=mail&id=5#section") == "https://example.com/story?id=5"


def test_fetcher_extracts_html_metadata_and_deduplicable_content(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="""
            <html><head><title>Supplier notice</title>
            <meta property='article:published_time' content='2026-01-04T12:00:00Z'>
            <script>ignore this</script></head>
            <body><nav>navigation junk</nav><main><p>Supplier announced a temporary service interruption.</p></main></body></html>
            """,
            request=request,
        )

    monkeypatch.setattr("tierlense.intelligence.fetcher._assert_public_destination", lambda url: None)
    fetcher = HttpSourceFetcher(
        Settings(source_document_max_chars=1000),
        client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs),
    )
    document = fetcher.fetch("https://example.com/notice?utm_campaign=test")
    assert document.title == "Supplier notice"
    assert "temporary service interruption" in document.content_text
    assert "navigation junk" not in document.content_text
    assert "ignore this" not in document.content_text
    assert document.published_at is not None
    assert len(document.content_hash) == 64


def test_fetcher_blocks_loopback_destination():
    fetcher = HttpSourceFetcher(Settings())
    with pytest.raises(SourceFetchError, match="non-public"):
        fetcher.fetch("http://127.0.0.1/admin")


def test_fetcher_blocks_unexpected_ports():
    fetcher = HttpSourceFetcher(Settings())
    with pytest.raises(SourceFetchError, match="Non-standard ports"):
        fetcher.fetch("https://example.com:8443/article")
