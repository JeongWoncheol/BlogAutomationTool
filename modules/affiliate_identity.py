"""Local product identity checks for affiliate links; tracking URLs stay unopened."""

import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

_COLORS: Final = (
    ("화이트", "white", "흰색"),
    ("블랙", "black", "검정"),
    ("실버", "silver", "은색"),
    ("핑크", "pink", "분홍"),
    ("블루", "blue", "파랑"),
    ("레드", "red", "빨강"),
    ("그린", "green", "초록"),
    ("베이지", "beige"),
    ("그레이", "gray", "grey", "회색"),
    ("네이비", "navy"),
)
_ACCESSORIES: Final = ("케이스", "보호필름", "액정보호", "스트랩", "충전기", "파우치")


def product_id(url: str) -> str:
    """Accept actual Coupang product pages, never hostname lookalikes."""
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").lower()
        valid = (
            parsed.scheme in {"http", "https"}
            and (host == "coupang.com" or host.endswith(".coupang.com"))
            and parsed.username is None
            and parsed.port in {None, 80, 443}
        )
        found = re.fullmatch(r"/(?:vp/)?products/(\d+)/?", parsed.path)
        return found.group(1) if valid and found else ""
    except ValueError:
        return ""


def same_product_url(expected: str, actual: str) -> bool:
    """Bind product ID and each selected item/vendor option in the source URL."""
    identifier = product_id(expected)
    if not identifier or identifier != product_id(actual):
        return False
    left = parse_qs(urlsplit(expected).query)
    right = parse_qs(urlsplit(actual).query)
    return all(
        left.get(key) == right.get(key)
        for key in ("itemId", "vendorItemId")
        if left.get(key) or right.get(key)
    )


def variant_conflicts(candidate: str, target: str) -> list[str]:
    """Require stated model numbers, colors and editions; reject accessory swaps."""
    low = candidate.lower()
    wanted = target.lower()
    missing = [
        value
        for value in re.findall(r"\d+(?:\.\d+)?", wanted)
        if not re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d.])", low)
    ]
    for aliases in _COLORS:
        if any(alias in wanted for alias in aliases) and not any(
            alias in low for alias in aliases
        ):
            missing.append(aliases[0])
    for aliases in (
        ("프로", "pro"),
        ("울트라", "ultra"),
        ("플러스", "plus"),
        ("미니", "mini"),
    ):
        if any(alias in wanted for alias in aliases) != any(
            alias in low for alias in aliases
        ):
            missing.append(aliases[0])
    for term in _ACCESSORIES:
        if (term in low) != (term in wanted):
            missing.append("액세서리:" + term)
    return sorted(set(missing))


class LinkEvidence(BaseModel):
    """Fields that bind a stored tracking link to its original product selection."""

    model_config = ConfigDict(frozen=True)
    ok: bool = False
    sharelink: str = ""
    product_id: str = ""
    original_url: str = ""
    product_url: str = ""
    target_name_original: str = ""
    match_product_name: str = ""
    source: str = ""


def bound_evidence(
    raw: Mapping[str, JsonValue], link: str, target: str, source_url: str = ""
) -> bool:
    """Reuse stored evidence only when link, product and target still agree."""
    try:
        evidence = LinkEvidence.model_validate(raw)
    except ValidationError:
        return False
    if not evidence.ok or evidence.sharelink != link:
        return False
    if evidence.target_name_original.strip() != target.strip():
        return False
    if source_url and product_id(source_url):
        if not same_product_url(
            source_url, evidence.product_url or evidence.original_url
        ):
            return False
    return bool(
        evidence.product_id
        and evidence.source
        not in {"existing_verified_db_link", "verified_coupang_affiliate_url", ""}
    )
