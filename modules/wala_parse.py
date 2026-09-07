"""Parse only CONTENT_DETAIL, never related-article queries."""

import json
import re
from typing import Final, assert_never
from urllib.parse import urlsplit

from pydantic import ValidationError

from .wala_errors import WalaParseError, WalaUnavailableError
from .wala_models import (
    ArticleResponse,
    NextDocument,
    RawArticle,
    RawProduct,
    WalaArticle,
    WalaProduct,
)

BASE_URL: Final = "https://wala-land.com"
PUBLIC_HOSTS: Final = frozenset({"wala-land.com", "img.wala-land.com"})


def public_image_url(url: str) -> str:
    """Discard non-public or non-Wala image references without fetching them."""
    try:
        parsed = urlsplit(url)
        return (
            url
            if parsed.scheme == "https"
            and parsed.hostname in PUBLIC_HOSTS
            and not parsed.username
            and parsed.port in (None, 443)
            else ""
        )
    except ValueError:
        return ""


def _link(url: str) -> str:
    try:
        parsed = urlsplit(url)
        return (
            url
            if parsed.scheme in ("http", "https")
            and parsed.hostname
            and not parsed.username
            else ""
        )
    except ValueError:
        return ""


def extract_next_data(html: str, article_id: int = 0) -> str:
    """Extract the serialized Next document without executing page scripts."""
    found = re.search(
        r"<script\b[^>]*\bid=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>",
        html,
        re.DOTALL,
    )
    if not found:
        raise WalaParseError(article_id, "missing __NEXT_DATA__")
    return found.group(1)


def _product(raw: RawProduct) -> WalaProduct:
    match raw.type:
        case "STORE":
            url = f"{BASE_URL}/ko/products/{raw.id}"
        case "CONTENT":
            url = _link(raw.link)
        case _:
            assert_never(raw.type)
    return WalaProduct(
        id=raw.id,
        type=raw.type,
        title=raw.title or raw.title_eng,
        brand=raw.brand or raw.brand_eng,
        price=raw.price or raw.basic_price or 0,
        basic_info=raw.basic_info,
        image_url=public_image_url(raw.image_url),
        url=url,
        alternatives=tuple(_product(item) for item in raw.alternatives or ()),
    )


def parse_article(html: str, article_id: int) -> WalaArticle:
    """Validate article identity/status and preserve direct product provenance."""
    try:
        document = NextDocument.model_validate_json(extract_next_data(html, article_id))
        selected = [
            q for q in document.queries if q.key and q.key[0] == "CONTENT_DETAIL"
        ]
        if len(selected) != 1:
            raise WalaParseError(article_id, "expected one CONTENT_DETAIL query")
        response = ArticleResponse.model_validate(selected[0].state.data)
        if response.code != 200 or response.value is None:
            raise WalaUnavailableError(article_id, str(response.code))
        raw = RawArticle.model_validate(response.value)
    except ValidationError as error:
        raise WalaParseError(article_id, str(error)) from error
    if raw.id != article_id:
        raise WalaParseError(article_id, f"returned article {raw.id}")
    if raw.status != "PUBLIC":
        raise WalaUnavailableError(article_id, raw.status)
    return WalaArticle(
        id=raw.id,
        title=raw.title or raw.title_eng,
        title_eng=raw.title_eng,
        description=raw.description,
        published_at=raw.published_at,
        tags=tuple(
            dict.fromkeys(
                t.title_kor or t.title_eng
                for t in raw.tags or ()
                if t.title_kor or t.title_eng
            )
        ),
        images=tuple(
            dict.fromkeys(
                url for value in raw.images or () if (url := public_image_url(value))
            )
        ),
        source_name=raw.source_name,
        source_link=_link(raw.source_link),
        source_name2=raw.source_name2,
        source_link2=_link(raw.source_link2),
        products=tuple(_product(item) for item in raw.products or ()),
        url=f"{BASE_URL}/ko/content/{raw.id}",
        status=raw.status,
        raw_json=json.dumps(response.value, ensure_ascii=False),
    )
