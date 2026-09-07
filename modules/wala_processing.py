"""Turn cached Wala editorial links into attributed outfit items."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import Final, TypedDict

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from .common import DB, settings
from .wala_models import WalaArticle, WalaProduct
from .wala_store import article_for_candidate, selected_rows

type Progress = Callable[[int, int, str], None]
type StopCheck = Callable[[], bool]


class ProcessingResult(TypedDict):
    processed: int
    matched: int
    images: int
    stopped: bool
    errors: list[str]
    message: str


class ProductEvidence(BaseModel):
    """Persist the exact publisher record independently of matching services."""

    model_config = ConfigDict(frozen=True)
    wala_product: WalaProduct
    source_url: str
    original_source_urls: tuple[str, ...]
    published_at: datetime
    rule: str = "WALA_PUBLISHER_LINK_NOT_INDEPENDENT_WEAR_CONFIRMATION"


_COMPLETED: Final = frozenset({"원고완료", "작성물연동"})
_CATEGORY_HINTS: Final = (
    ("아우터", ("재킷", "자켓", "코트", "패딩", "jacket", "coat")),
    ("원피스", ("원피스", "dress")),
    ("상의", ("티셔츠", "후드", "셔츠", "니트", "shirt", "hood", "knit")),
    ("하의", ("팬츠", "바지", "스커트", "데님", "pants", "skirt", "jean")),
    ("가방", ("가방", "백", "bag")),
    ("신발", ("신발", "슈즈", "부츠", "스니커즈", "shoes", "boot", "sneaker")),
    ("모자", ("모자", "hat", "cap")),
    ("주얼리", ("주얼리", "목걸이", "귀걸이", "necklace", "earring")),
)


def _category(product: WalaProduct) -> str:
    title = product.title.casefold()
    return next((name for name, hints in _CATEGORY_HINTS if any(h in title for h in hints)), "기타")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _evidence(article: WalaArticle, product: WalaProduct) -> ProductEvidence:
    return ProductEvidence(
        wala_product=product, source_url=article.url, published_at=article.published_at,
        original_source_urls=tuple(link for link in (article.source_link, article.source_link2) if link),
    )


def analyze_unfinished(
    candidate_ids: list[int] | None = None, progress: Progress | None = None,
    stop_check: StopCheck | None = None,
) -> ProcessingResult:
    """Extract only Wala's direct product links; visual output remains advisory."""
    from . import celebrity_style_adapter as legacy

    rows = [row for row in selected_rows(candidate_ids) if row["status"] not in _COMPLETED]
    processed = 0
    stopped = False
    cfg = settings()
    vision_ready = bool(rows and cfg.get("celebrity_style_vision_enabled", True)
                        and not (stop_check and stop_check()) and legacy._vision_model(cfg))
    with closing(sqlite3.connect(DB)) as con:
        for index, row in enumerate(rows):
            if stop_check and stop_check():
                stopped = True
                break
            if progress:
                progress(index, len(rows), f"왈라랜드 착장 정리 · {row['celebrity_name']}")
            article = article_for_candidate(int(row["id"]))
            vision = TypeAdapter(dict[str, JsonValue]).validate_json(row["vision_json"] or "{}")
            if vision_ready:
                vision = legacy._vision_analyze(dict(row), legacy._candidate_sources(row))
            else:
                vision.setdefault("attempted", False)
                vision.setdefault("model", "")
                vision.setdefault("images", [])
                vision.setdefault("result", {})
                vision.setdefault("errors", [])
                vision.setdefault("reference_search", {})
                vision.setdefault("cluster_result", {})
            for product in article.products:
                evidence = _evidence(article, product)
                con.execute(
                    """INSERT INTO celebrity_style_items
                    (candidate_id,item_category,item_description,brand,model_name,color,
                     evidence_level,confidence_score,exact_claim_allowed,evidence_json,updated_at)
                    VALUES(?,?,?,?,?,'','왈라랜드 소개',60,0,?,?)
                    ON CONFLICT(candidate_id,item_category,item_description,brand,model_name)
                    DO UPDATE SET evidence_json=excluded.evidence_json,
                    evidence_level=excluded.evidence_level,exact_claim_allowed=0,
                    confidence_score=excluded.confidence_score,updated_at=excluded.updated_at""",
                    (row["id"], _category(product), product.title, product.brand, product.title,
                     evidence.model_dump_json(), _now()),
                )
            status = "착장분석완료" if article.products else "착장근거부족"
            if row["status"] == "상품매칭완료":
                status = str(row["status"])
            summary = f"왈라랜드 소개 상품 {len(article.products)}개. 단일 매체의 연결 정보이며 실제 착용 확정과 구분합니다."
            con.execute(
                """UPDATE celebrity_style_candidates SET summary=?,vision_json=?,
                confidence_score=?,confidence_label='왈라랜드 소개',status=?,updated_at=?,last_error=NULL
                WHERE id=?""",
                (summary, json.dumps(vision, ensure_ascii=False), 60 if article.products else 30,
                 status, _now(), row["id"]),
            )
            con.commit()
            processed += 1
    legacy._write_candidates_csv()
    legacy._write_items_csv()
    message = f"왈라랜드 착장 정리 {processed}건" + (" · 중지됨" if stopped else " 완료")
    if progress:
        progress(processed, len(rows) or 1, message)
    return {"processed": processed, "matched": 0, "images": 0, "stopped": stopped, "errors": [], "message": message}


def match_products(
    candidate_ids: list[int] | None = None, progress: Progress | None = None,
    stop_check: StopCheck | None = None,
) -> ProcessingResult:
    """Copy publisher-linked product metadata without external shopping searches."""
    from . import celebrity_style_adapter as legacy

    rows = selected_rows(candidate_ids)
    processed = matched = 0
    visited = 0
    stopped = False
    with closing(sqlite3.connect(DB)) as con:
        con.row_factory = sqlite3.Row
        for index, row in enumerate(rows):
            if stop_check and stop_check():
                stopped = True
                break
            if progress:
                progress(index, len(rows), f"왈라랜드 상품 연결 · {row['celebrity_name']}")
            items = con.execute(
                "SELECT id,evidence_json FROM celebrity_style_items WHERE candidate_id=?",
                (row["id"],),
            ).fetchall()
            linked = 0
            for item in items:
                evidence = ProductEvidence.model_validate_json(item["evidence_json"])
                product = evidence.wala_product
                con.execute(
                    """UPDATE celebrity_style_items SET matched_name=?,matched_url=?,
                    matched_price=?,matched_image_url=?,match_type=?,exact_claim_allowed=0,
                    naver_product_json='{}',coupang_product_json='{}',updated_at=? WHERE id=?""",
                    (product.title, product.url, product.price, product.image_url,
                     "왈라랜드 연결상품" if product.url else "상품링크없음", _now(), item["id"]),
                )
                linked += bool(product.title and product.url)
                processed += 1
            matched += linked
            if row["status"] not in _COMPLETED:
                status = "상품매칭완료" if linked else ("상품매칭부분" if items else "착장근거부족")
                con.execute(
                    "UPDATE celebrity_style_candidates SET status=?,updated_at=? WHERE id=?",
                    (status, _now(), row["id"]),
                )
            con.commit()
            visited += 1
    legacy._write_items_csv()
    legacy._write_candidates_csv()
    message = f"왈라랜드 상품 {processed}개 확인 · {matched}개 연결" + (" · 중지됨" if stopped else "")
    if progress:
        progress(visited, len(rows) or 1, message)
    return {"processed": processed, "matched": matched, "images": 0, "stopped": stopped, "errors": [], "message": message}


def collect_reference_images(
    candidate_ids: list[int] | None = None, progress: Progress | None = None,
    stop_check: StopCheck | None = None,
) -> ProcessingResult:
    """Cache Wala article photos only as local analysis evidence."""
    from . import celebrity_style_adapter as legacy
    from .wala_images import reference_images

    rows = selected_rows(candidate_ids)
    processed = images = 0
    stopped = False
    errors: list[str] = []
    with closing(sqlite3.connect(DB)) as con:
        for index, row in enumerate(rows):
            if stop_check and stop_check():
                stopped = True
                break
            if progress:
                progress(index, len(rows), f"왈라랜드 참고 이미지 · {row['celebrity_name']}")
            reference = reference_images(row, [], stop_check)
            errors.extend(reference["errors"])
            old = TypeAdapter(dict[str, JsonValue]).validate_json(row["vision_json"] or "{}")
            old["reference_search"] = json.loads(json.dumps(reference))
            old["reference_only_collected_at"] = _now()
            con.execute(
                "UPDATE celebrity_style_candidates SET vision_json=?,updated_at=? WHERE id=?",
                (json.dumps(old, ensure_ascii=False), _now(), row["id"]),
            )
            con.commit()
            images += len(reference["downloaded"])
            processed += 1
            if reference["stopped"] or (stop_check and stop_check()):
                stopped = True
                break
    legacy._write_candidates_csv()
    message = f"왈라랜드 참고 이미지 {images}장 · 후보 {processed}건"
    message += " · 중지됨" if stopped else (f" · 일부 실패 {len(errors)}건" if errors else " 완료")
    if progress:
        progress(processed, len(rows) or 1, message)
    return {"processed": processed, "matched": 0, "images": images, "stopped": stopped, "errors": errors, "message": message}
