"""Bind collected photos to product identity and unchanged file evidence."""

import hashlib
import re
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

IDENTITY_POLICY: Final = "PRIMARY_PAGE_OR_EXACT_API_V1"


def market_product_key(url: str) -> tuple[str, str]:
    """Extract stable marketplace product identity, excluding tracking queries."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    patterns = (
        ("coupang.com", r"/(?:vp/)?products/(\d+)", "coupang"),
        ("toss.shopping", r"/t/([^/]+)", "toss"),
        ("smartstore.naver.com", r"/(.+/products/\d+)", "naver-store"),
        ("brand.naver.com", r"/(.+/products/\d+)", "naver-brand"),
        ("shopping.naver.com", r"/catalog/(\d+)", "naver-catalog"),
    )
    for domain, pattern, market in patterns:
        if host == domain or host.endswith("." + domain):
            matched = re.fullmatch(pattern, path)
            if matched:
                return market, matched[1]
    return "", ""


def page_identity_conflict(requested_url: str, final_url: str) -> str:
    """Reject changed marketplace product/option IDs before trusting page photos."""
    requested_key = market_product_key(requested_url)
    final_key = market_product_key(final_url)
    if requested_key[0] and requested_key != final_key:
        return "상품 페이지 이동 후 상품 ID가 달라졌습니다."
    requested = parse_qs(urlsplit(requested_url).query)
    final = parse_qs(urlsplit(final_url).query)
    for key in ("itemId", "vendorItemId", "optionId"):
        if requested.get(key) and requested[key] != final.get(key):
            return "상품 페이지 이동 후 선택 옵션 ID가 달라졌습니다."
    return ""


class PhotoEvidence(BaseModel):
    """Persisted association between one accepted source and its file bytes."""

    model_config = ConfigDict(frozen=True)
    path: str
    sha256: str
    page_url: str
    kind: str


class ImageEvidence(BaseModel):
    """Boundary parser for image evidence created after primary identity checks."""

    model_config = ConfigDict(frozen=True)
    target: str
    identity_verification: str
    images: tuple[PhotoEvidence, ...]


def image_evidence_error(evidence_path: Path, target: str, paths: list[str]) -> str:
    """Require current identity policy, target, per-file provenance and digest."""
    try:
        evidence = ImageEvidence.model_validate_json(
            evidence_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError):
        return (
            "이전 사진 근거의 상품·출처 재검증이 필요합니다. 사진 보강을 실행해 주세요."
        )
    if evidence.identity_verification != IDENTITY_POLICY or evidence.target != target:
        return (
            "사진 근거의 상품명 또는 검증 정책이 다릅니다. 사진 보강을 실행해 주세요."
        )
    by_path = {str(Path(photo.path).resolve()): photo for photo in evidence.images}
    if len(by_path) != len(evidence.images):
        return "사진 근거에 같은 파일이 중복되어 있습니다."
    for path in paths:
        photo = by_path.get(str(Path(path).resolve()))
        if photo is None or not photo.page_url or not photo.kind:
            return "사진 파일과 검증된 원본 상품 출처가 연결되지 않았습니다."
        try:
            with Path(path).open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError:
            return "검증된 사진 파일을 읽을 수 없습니다."
        if digest != photo.sha256:
            return "사진 파일이 검증 후 변경되었습니다. 사진 보강을 실행해 주세요."
    return ""
