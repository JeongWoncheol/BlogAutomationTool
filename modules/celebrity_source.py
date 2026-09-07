"""Keep celebrity discovery providers isolated for each dashboard run."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final, Literal, assert_never

from pydantic import JsonValue, TypeAdapter

from .common import settings

type Source = Literal["wala", "naver", "google"]

_SOURCE: Final[ContextVar[Source | None]] = ContextVar("celebrity_source", default=None)
_PARSER: Final[TypeAdapter[Source]] = TypeAdapter(Source)
_SETTINGS: Final[TypeAdapter[dict[str, JsonValue]]] = TypeAdapter(dict[str, JsonValue])


def current_source() -> Source:
    """An explicit run overrides the persisted default without changing it."""
    selected = _SOURCE.get()
    if selected is not None:
        return selected
    config = _SETTINGS.validate_python(settings())
    return _PARSER.validate_python(config.get("celebrity_style_source", "wala"))


@contextmanager
def use_source(source: Source) -> Generator[None]:
    token = _SOURCE.set(_PARSER.validate_python(source))
    try:
        yield
    finally:
        _SOURCE.reset(token)


def source_sql(column: Literal["fingerprint", "c.fingerprint"] = "fingerprint") -> str:
    """Legacy mixed search records stay archived, outside explicit provider runs."""
    source = current_source()
    match source:
        case "wala":
            return f"{column} LIKE 'wala:%'"
        case "naver" | "google":
            return f"{column} LIKE 'search:{source}:%'"
        case unreachable:
            assert_never(unreachable)
