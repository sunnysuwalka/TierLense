"""Bounded, SSRF-conscious fetcher for publicly accessible HTTP(S) sources."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from tierlense.core.config import Settings, get_settings
from tierlense.intelligence.errors import SourceFetchError
from tierlense.intelligence.schemas import FetchedDocument

TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
USER_AGENT = "TierLenseResearchBot/0.1 (+public-source research; contact: operator-configured)"
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/pdf",
}


def canonicalize_url(url: str) -> str:
    """Normalize a URL for storage and de-duplication without guessing page identity."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise SourceFetchError("Only HTTP and HTTPS source URLs are allowed")
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise SourceFetchError("The source URL must have a hostname and no embedded credentials")
    try:
        port = parts.port
    except ValueError as exc:
        raise SourceFetchError("The source URL has an invalid port") from exc
    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        raise SourceFetchError("Non-standard ports are not allowed for public-source fetching")
    host = parts.hostname.lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise SourceFetchError("Local and internal hostnames are not allowed")
    netloc = f"[{host}]" if ":" in host else host
    path = parts.path or "/"
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit((scheme, netloc, path, urlencode(kept_query, doseq=True), ""))


def _assert_public_destination(url: str) -> None:
    """Reject non-public IP destinations before making a request to reduce SSRF risk."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise SourceFetchError("Source URL is missing a hostname")
    try:
        literal_ip = ipaddress.ip_address(host)
        addresses = [literal_ip]
    except ValueError:
        try:
            answers = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SourceFetchError(f"Could not resolve the source hostname: {host}") from exc
        addresses = []
        for answer in answers:
            try:
                addresses.append(ipaddress.ip_address(answer[4][0].split("%", 1)[0]))
            except ValueError:
                continue
    if not addresses:
        raise SourceFetchError("The source hostname did not resolve to an IP address")
    if any(not address.is_global for address in addresses):
        raise SourceFetchError("Source URL resolves to a non-public network address")


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_published_date(soup: BeautifulSoup, headers: httpx.Headers) -> datetime | None:
    meta_names = {
        "article:published_time",
        "date",
        "pubdate",
        "publish-date",
        "datepublished",
        "dc.date",
        "dc.date.issued",
    }
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        value = tag.get("content")
        if key in meta_names and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except ValueError:
                parsed_http = _parse_http_date(value)
                if parsed_http:
                    return parsed_http
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        value = str(time_tag.get("datetime"))
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return _parse_http_date(headers.get("Last-Modified"))


def _extract_pdf_text(content: bytes, max_chars: int) -> tuple[str, str | None, bool]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content), strict=False)
        chunks: list[str] = []
        char_count = 0
        truncated = False
        for page_index, page in enumerate(reader.pages):
            if page_index >= 40:
                truncated = True
                break
            text = page.extract_text() or ""
            if char_count + len(text) > max_chars:
                chunks.append(text[: max(0, max_chars - char_count)])
                truncated = True
                break
            chunks.append(text)
            char_count += len(text)
        metadata_title = None
        if reader.metadata and reader.metadata.title:
            metadata_title = str(reader.metadata.title)[:1000]
        return "\n\n".join(chunks).strip(), metadata_title, truncated
    except Exception as exc:
        raise SourceFetchError("The PDF could not be parsed into text") from exc


class HttpSourceFetcher:
    """Fetch HTML/text/PDF documents with size, redirect, and network-boundary controls."""

    def __init__(
        self,
        settings: Settings | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client_factory = client_factory or httpx.Client

    def fetch(self, url: str) -> FetchedDocument:
        current_url = canonicalize_url(url)
        response_headers: httpx.Headers | None = None
        response_status = 0
        content = b""
        final_url = current_url

        for redirect_count in range(self.settings.source_fetch_max_redirects + 1):
            _assert_public_destination(current_url)
            try:
                with self.client_factory(
                    timeout=httpx.Timeout(self.settings.source_fetch_timeout_seconds, connect=min(5.0, self.settings.source_fetch_timeout_seconds)),
                    follow_redirects=False,
                    trust_env=False,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9,*/*;q=0.2"},
                ) as client:
                    with client.stream("GET", current_url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise SourceFetchError("Source returned a redirect without a Location header")
                            if redirect_count >= self.settings.source_fetch_max_redirects:
                                raise SourceFetchError("Source exceeded the redirect limit")
                            current_url = canonicalize_url(urljoin(current_url, location))
                            continue
                        response_status = response.status_code
                        response.raise_for_status()
                        response_headers = response.headers
                        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
                        if content_type not in ALLOWED_CONTENT_TYPES:
                            raise SourceFetchError(f"Unsupported source content type: {content_type or 'unknown'}")
                        declared_length = response.headers.get("Content-Length")
                        if declared_length and declared_length.isdigit() and int(declared_length) > self.settings.source_fetch_max_bytes:
                            raise SourceFetchError("Source exceeds the configured download size limit")
                        parts: list[bytes] = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > self.settings.source_fetch_max_bytes:
                                raise SourceFetchError("Source exceeded the configured download size limit while downloading")
                            parts.append(chunk)
                        content = b"".join(parts)
                        final_url = current_url
                        break
            except SourceFetchError:
                raise
            except httpx.HTTPError as exc:
                raise SourceFetchError(f"HTTP request failed: {type(exc).__name__}") from exc
        else:
            raise SourceFetchError("Source could not be fetched after redirects")

        assert response_headers is not None
        content_type = response_headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
        title: str | None = None
        published_at: datetime | None = None
        truncated = False

        if content_type == "application/pdf":
            text, title, truncated = _extract_pdf_text(content, self.settings.source_document_max_chars)
        elif content_type in {"text/html", "application/xhtml+xml"}:
            encoding = response_headers.encoding or "utf-8"
            html = content.decode(encoding, errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(" ", strip=True)[:1000] or None
            published_at = _extract_published_date(soup, response_headers)
            for node in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "iframe", "svg", "canvas"]):
                node.decompose()
            body = soup.find("main") or soup.find("article") or soup.body or soup
            text = "\n".join(line.strip() for line in body.get_text("\n", strip=True).splitlines() if line.strip())
        else:
            text = content.decode("utf-8", errors="replace")

        normalized_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(normalized_text) > self.settings.source_document_max_chars:
            normalized_text = normalized_text[: self.settings.source_document_max_chars]
            truncated = True
        if not normalized_text:
            raise SourceFetchError("The source was accessible but no extractable text was found")

        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        return FetchedDocument(
            url=final_url,
            title=title,
            content_type=content_type,
            content_text=normalized_text,
            content_hash=digest,
            fetched_at=datetime.now(timezone.utc),
            published_at=published_at,
            http_status=response_status,
            is_truncated=truncated,
            metadata={"canonical_url": canonicalize_url(final_url), "download_bytes": len(content)},
        )
