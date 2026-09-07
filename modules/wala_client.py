"""Polite, Wala-only public HTTP collection with explicit failure semantics."""

import logging
import socket
import time
from types import TracebackType
from typing import Final, Self
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx2

from .wala_errors import (
    WalaAccessError,
    WalaError,
    WalaHTTPError,
    WalaParseError,
    WalaTransportError,
    WalaUnavailableError,
)
from .wala_models import WalaArticle
from .wala_parse import (
    BASE_URL,
    PUBLIC_HOSTS,
    extract_next_data,
    parse_article,
    public_image_url,
)

__all__ = [
    "WalaAccessError",
    "WalaClient",
    "WalaError",
    "WalaHTTPError",
    "WalaParseError",
    "WalaTransportError",
    "WalaUnavailableError",
    "extract_next_data",
    "parse_article",
]

_LOGGER: Final = logging.getLogger(__name__)
_LIMITS: Final = httpx2.Limits(
    max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0
)
_TIMEOUT: Final = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)


def _guard_request(request: httpx2.Request) -> None:
    """Apply the host boundary to every redirect before it is sent."""
    if (
        request.url.scheme != "https"
        or request.url.host not in PUBLIC_HOSTS
        or request.url.port not in (None, 443)
    ):
        raise WalaTransportError(str(request.url), "redirect outside public Wala hosts")
    _LOGGER.debug("Wala request %s %s", request.method, request.url)


def _log_response(response: httpx2.Response) -> None:
    _LOGGER.info(
        "Wala HTTP %s %s %d",
        response.http_version,
        response.request.url,
        response.status_code,
    )


class WalaClient:
    """A sequential session; mutable state tracks the minimum request interval."""

    def __init__(self, min_interval: float = 0.5) -> None:
        self._interval: float = max(0.5, min_interval)
        self._last_request: float = 0.0
        transport = httpx2.HTTPTransport(
            http2=True,
            retries=3,
            limits=_LIMITS,
            socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
        )
        self._client: httpx2.Client = httpx2.Client(
            transport=transport,
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": "BlogAutomationTool-Wala/1.0",
                "Accept-Language": "ko-KR,ko;q=0.9",
            },
            event_hooks={"request": [_guard_request], "response": [_log_response]},
        )

    def __enter__(self) -> Self:
        _ = self._client.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._client.__exit__(exc_type, exc_value, traceback)

    def _get(self, url: str) -> httpx2.Response:
        remaining = self._interval - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()
        try:
            response = self._client.get(url)
        except httpx2.RequestError as error:
            raise WalaTransportError(url, str(error)) from error
        if response.status_code in (403, 429):
            raise WalaAccessError(url, response.status_code)
        if response.status_code >= 400:
            raise WalaHTTPError(url, response.status_code)
        return response

    def article_ids(self) -> list[int]:
        """Enumerate the full public content sitemap, ignoring generated lastmod."""
        content = self._get(f"{BASE_URL}/content/sitemap.xml").content
        if (
            len(content) > 10_000_000
            or b"<!DOCTYPE" in content.upper()
            or b"<!ENTITY" in content.upper()
        ):
            raise WalaParseError(0, "unsafe or oversized content sitemap")
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as error:
            raise WalaParseError(0, "invalid content sitemap XML") from error
        ids: set[int] = set()
        for location in root.findall("{*}url/{*}loc"):
            parsed = urlsplit(location.text or "")
            parts = parsed.path.strip("/").split("/")
            if (
                parsed.hostname == "wala-land.com"
                and len(parts) >= 2
                and parts[-2] == "content"
                and parts[-1].isdigit()
            ):
                ids.add(int(parts[-1]))
        if not ids:
            raise WalaParseError(0, "content sitemap contains no article IDs")
        return sorted(ids, reverse=True)

    def article_html(self, article_id: int) -> str:
        if article_id < 1:
            raise WalaParseError(article_id, "article ID must be positive")
        try:
            return self._get(f"{BASE_URL}/ko/content/{article_id}").text
        except WalaHTTPError as error:
            if error.status_code in (404, 410):
                raise WalaUnavailableError(
                    article_id, str(error.status_code)
                ) from error
            raise

    def article(self, article_id: int) -> WalaArticle:
        return parse_article(self.article_html(article_id), article_id)

    def image_bytes(self, url: str) -> bytes:
        """Download a publisher-hosted image without following external hosts."""
        if not public_image_url(url):
            raise WalaTransportError(url, "image must use a public Wala HTTPS host")
        response = self._get(url)
        if not response.headers.get("content-type", "").lower().startswith("image/"):
            raise WalaTransportError(url, "response is not an image")
        return response.content
