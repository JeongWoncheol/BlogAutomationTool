"""Keep promoted Wala content within its publisher-only source policy."""

import json
from collections.abc import Collection
from pathlib import Path
from typing import Final, Protocol, TypedDict

from PIL import Image, UnidentifiedImageError

from .common import EVIDENCE, verified_blog_image_set

REVIEW_REASON: Final = "왈라랜드 전용 콘텐츠: 착장 페이지에서 참고자료와 상품 사진을 확인해 주세요."
SOURCE_REASON: Final = "왈라랜드 전용 콘텐츠는 외부 가격·상품·제휴링크 검색에서 제외합니다."


class ProductRow(Protocol):
    def keys(self) -> Collection[str]: ...

    def __getitem__(self, key: str) -> str | int | float | bytes | None: ...


class SkippedPrice(TypedDict):
    product_id: int
    skipped: bool
    reason: str
    verified_sites: int
    price_image_verified_sites: int
    compare_image: str
    evidence: str
    records: list[str]
    lookup_completed: bool
    comparison_ready: bool
    stage_ok: bool
    soft_pending: bool


def is_wala_product(row: ProductRow) -> bool:
    return ("content_type" in row.keys() and "source_platform" in row.keys()
            and row["content_type"] == "celebrity_style" and row["source_platform"] == "왈라랜드")


def skipped_price(product_id: int) -> SkippedPrice:
    return {"product_id": product_id, "skipped": True, "reason": SOURCE_REASON,
            "verified_sites": 0, "price_image_verified_sites": 0,
            "compare_image": "", "evidence": "", "records": [],
            "lookup_completed": False, "comparison_ready": False,
            "stage_ok": True, "soft_pending": False}


def preserve_product_images(row: ProductRow, post_dir: Path, required: int) -> tuple[list[str], str]:
    """Reuse verified product slots without promoting article reference photos."""
    images: list[str] = []
    reference_root = (EVIDENCE / "celebrity_style").resolve()
    verified = int(str(row["image_verified_count"] or 0))
    for key in ("image1", "image2", "image3")[:min(verified, required)]:
        value = str(row[key] or "").strip()
        if not value:
            continue
        path = Path(value).resolve()
        if not path.is_file() or path.is_relative_to(reference_root) or str(path) in images:
            continue
        try:
            with Image.open(path) as photo:
                photo.verify()
        except (OSError, UnidentifiedImageError, SyntaxError):
            continue
        images.append(str(path))
    complete, _ = verified_blog_image_set(row, required)
    if complete and len(images) >= required:
        return images, str(row["image_evidence_json"] or "")
    post_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = post_dir / "wala_image_review.json"
    evidence = {
        "target": str(row["name"] or ""), "required": required,
        "source_policy": "WALA_ONLY_EXISTING_PRODUCT_IMAGES",
        "verified_count": len(images), "verified": False,
        "exact_product_found": False, "composition": {"verified": False},
        "failure_summary": {"code": "WALA_REFERENCE_REVIEW_REQUIRED", "short": REVIEW_REASON},
        "images": [{"path": path, "kind": "existing_product_slot"} for path in images],
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return images, str(evidence_path)
