"""Recoverable Wala collection errors with explicit stop/skip semantics."""

from dataclasses import dataclass
from typing import override


class WalaError(Exception):
    """Base for expected public-source collection failures."""


@dataclass(frozen=True, slots=True)
class WalaParseError(WalaError):
    article_id: int
    reason: str

    @override
    def __str__(self) -> str:
        return f"Wala {self.article_id}: {self.reason}"


@dataclass(frozen=True, slots=True)
class WalaUnavailableError(WalaError):
    article_id: int
    status: str

    @override
    def __str__(self) -> str:
        return f"Wala {self.article_id}: unavailable ({self.status})"


@dataclass(frozen=True, slots=True)
class WalaHTTPError(WalaError):
    url: str
    status_code: int

    @override
    def __str__(self) -> str:
        return f"Wala HTTP {self.status_code}: {self.url}"


class WalaAccessError(WalaHTTPError):
    """Access denied or rate limited: stop this collection run."""


@dataclass(frozen=True, slots=True)
class WalaTransportError(WalaError):
    url: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"Wala request failed: {self.url}: {self.reason}"
