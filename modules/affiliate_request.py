"""Finite affiliate request budgets with cooperative UI cancellation."""

import socket
import time
import io
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from typing import Final

import anyio
import httpx2
from pydantic import TypeAdapter

from .common import log

_LIMITS: Final = httpx2.Limits(
    max_connections=200, max_keepalive_connections=40, keepalive_expiry=30
)
_REQUEST_BODY: Final = TypeAdapter(bytes | None)


class AffiliateStopped(RuntimeError):
    """The user stopped the current operation."""

    def __init__(self) -> None:
        super().__init__("사용자가 쉐어링크 작업을 중지했습니다.")


class AffiliateTimeout(RuntimeError):
    """The per-product request budget was exhausted."""

    def __init__(self) -> None:
        super().__init__("쉐어링크 상품별 처리 제한시간을 초과했습니다.")


@dataclass(frozen=True, slots=True)
class Operation:
    """One product shares its deadline across search queries and link creation."""

    deadline: float
    stop_check: Callable[[], bool] | None = None

    def remaining(self) -> float:
        if self.stop_check and self.stop_check():
            raise AffiliateStopped
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AffiliateTimeout
        return remaining

    def pause(self, seconds: float) -> None:
        until = time.monotonic() + max(0, seconds)
        while time.monotonic() < until:
            time.sleep(max(0, min(0.1, self.remaining(), until - time.monotonic())))


async def _response_log(response: httpx2.Response) -> None:
    log(
        f"쿠팡 API 응답: {response.request.method} {response.request.url.path} HTTP {response.status_code}"
    )


async def _request(request: urllib.request.Request, operation: Operation) -> bytes:
    payload = _REQUEST_BODY.validate_python(request.data, strict=True)
    async def watch_stop(scope: anyio.CancelScope) -> None:
        while True:
            if operation.stop_check and operation.stop_check():
                scope.cancel()
                return
            await anyio.sleep(0.1)

    transport = httpx2.AsyncHTTPTransport(
        http2=True,
        retries=3,
        limits=_LIMITS,
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    response: httpx2.Response | None = None
    try:
        with anyio.fail_after(operation.remaining()):
            async with httpx2.AsyncClient(
                transport=transport,
                timeout=httpx2.Timeout(connect=5, read=15, write=10, pool=10),
                follow_redirects=False,
                event_hooks={"response": [_response_log]},
            ) as client:
                async with anyio.create_task_group() as group:
                    group.start_soon(watch_stop, group.cancel_scope)
                    response = await client.request(
                        request.get_method(),
                        request.full_url,
                        headers=dict(request.header_items()),
                        content=payload,
                    )
                    group.cancel_scope.cancel()
    except TimeoutError as error:
        raise AffiliateTimeout from error
    if response is None:
        raise AffiliateStopped
    if response.status_code >= 300:
        raise urllib.error.HTTPError(
            request.full_url,
            response.status_code,
            response.text[:500],
            Message(),
            io.BytesIO(response.content),
        )
    return response.content


def fetch(request: urllib.request.Request, operation: Operation) -> bytes:
    """Execute signed requests without ever opening returned tracking links."""
    return anyio.run(_request, request, operation)
