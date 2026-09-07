"""Batch identity and local artifact gates for celebrity dashboard jobs."""

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from . import blog_adapter, common, celebrity_style_adapter as style
from .blog_link_policy import affiliate_requirement_reason


class BatchSelection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    product_ids: tuple[int, ...] = ()
    ready_product_ids: tuple[int, ...] = ()
    reasons: tuple[str, ...] = ()


class ReferenceImage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    file: str
    source_url: str


class VisualItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, str_strip_whitespace=True)
    category: str = ''
    description: str = ''


class VisualResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    items: tuple[VisualItem, ...] = ()


class VisionEvidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    attempted: bool = False
    images: tuple[ReferenceImage, ...] = ()
    result: VisualResult = VisualResult()
    errors: tuple[str, ...] = ()


class ExactEvidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    text_source_indices: tuple[int, ...] = ()
    source_page_texts: tuple[dict[str, JsonValue], ...] = ()


def visual_reason(candidate_id: int) -> str:
    """Require an acquired reference photo and successful AI garment analysis."""
    with closing(common.db_connect(row_factory=True)) as con:
        row = con.execute('SELECT vision_json FROM celebrity_style_candidates WHERE id=?', (candidate_id,)).fetchone()
    if row is None:
        return '착장 후보 없음'
    try:
        vision = VisionEvidence.model_validate_json(str(row['vision_json'] or '{}'))
    except ValidationError:
        return '착장 참고 이미지 AI 분석 기록 확인 필요'
    if not vision.attempted or vision.errors or not any(item.category and item.description for item in vision.result.items):
        return '착장 참고 이미지 AI 분석 미완료 · 기존 Vision 모델 상태 확인'
    if not vision.images or not all(image.source_url and Path(image.file).is_file() for image in vision.images):
        return 'AI가 분석한 착장 참고 이미지 파일 없음'
    return ''


def exact_rows(product_ids: Sequence[int]) -> list[sqlite3.Row]:
    """Require unchanged promoted identity and explicit exact item evidence."""
    if not product_ids:
        return []
    marks = ','.join('?' for _ in product_ids)
    with closing(common.db_connect(row_factory=True)) as con:
        rows = con.execute(
            f"""SELECT DISTINCT p.* FROM products p
            JOIN celebrity_style_candidates c ON c.id=p.celebrity_style_id
            JOIN celebrity_style_items i ON i.candidate_id=c.id AND i.matched_product_id=p.id
            WHERE p.id IN ({marks}) AND p.content_type='celebrity_style'
            AND (c.fingerprint LIKE 'search:google:%' OR c.fingerprint LIKE 'search:naver:%')
            AND c.promoted_product_id=p.id AND COALESCE(p.already_posted,0)=0
            AND COALESCE(p.status,'') NOT LIKE '추천제외:%'
            AND i.exact_claim_allowed=1 AND i.match_type IN ('정확상품','정확상품(네이버검증)')
            AND i.matched_name=p.name AND i.matched_url=p.source_url
            ORDER BY p.product_no,p.id""", tuple(product_ids),
        ).fetchall()
        accepted: list[sqlite3.Row] = []
        for row in rows:
            if visual_reason(int(row['celebrity_style_id'])):
                continue
            item = con.execute("SELECT * FROM celebrity_style_items WHERE candidate_id=? AND matched_product_id=? AND exact_claim_allowed=1 AND matched_name=? AND matched_url=? ORDER BY confidence_score DESC LIMIT 1", (row['celebrity_style_id'], row['id'], row['name'], row['source_url'])).fetchone()
            candidate = con.execute('SELECT * FROM celebrity_style_candidates WHERE id=?', (row['celebrity_style_id'],)).fetchone()
            try:
                evidence = ExactEvidence.model_validate_json(str(item['evidence_json'] or '{}'))
                claim = {**dict(item), 'exact_claim_allowed': True, 'exact_text_evidence': list(evidence.text_source_indices)}
                confirmed = style._item_confidence(claim, style._candidate_sources(candidate), evidence.source_page_texts)[1]
            except ValidationError:
                confirmed = False
            if confirmed:
                accepted.append(row)
        return accepted


def prepare_artifacts(product_ids: Sequence[int]) -> BatchSelection:
    """Recover only this batch's DB draft without generic AI regeneration."""
    valid: list[int] = []
    reasons: list[str] = []
    rows = exact_rows(product_ids)
    with closing(common.db_connect(row_factory=True)) as con:
        for row in rows:
            post, reason = blog_adapter._ensure_post_artifact(con, row)
            if post is None:
                reasons.append(f"상품 {row['id']}: {reason}")
            else:
                post['title'] = str(row['title'])
                post['blocks'] = blog_adapter._blocks_from_db_body(row['body'])
                post['tags'] = [tag.strip().lstrip('#') for tag in str(row['tags']).split(',') if tag.strip()]
                path = blog_adapter._safe_post_dir(row) / 'post.json'
                written, detail = blog_adapter._write_post_artifact(path, post)
                if written:
                    valid.append(int(row['id']))
                else:
                    reasons.append(f"상품 {row['id']}: 원고 파일 저장 실패 {detail}")
    absent = set(product_ids) - {int(row['id']) for row in rows}
    reasons.extend(f"상품 {pid}: 현재 확정 착장 상품 근거 없음 또는 저장 완료" for pid in sorted(absent))
    return BatchSelection(product_ids=tuple(valid), reasons=tuple(reasons))


def inspect_batch(product_ids: Sequence[int]) -> BatchSelection:
    """Recheck physical image digests and affiliate identity immediately before save."""
    rows = exact_rows(product_ids)
    ready: list[int] = []
    reasons: list[str] = []
    for row in rows:
        image_ok, detail = common.verified_blog_image_set(row, 3)
        reason = str(detail.get('reason') or '') if not image_ok else affiliate_requirement_reason({key: str(row[key] or '') for key in ('sharelink', 'name', 'source_url', 'source_platform', 'content_type', 'post_dir')}, 'required')
        if not row['title'] or not row['body'] or not row['tags']:
            reason = '제목·본문·태그 미완료'
        if reason:
            reasons.append(f"상품 {row['id']}: {reason}")
        else:
            ready.append(int(row['id']))
    absent = set(product_ids) - {int(row['id']) for row in rows}
    reasons.extend(f"상품 {pid}: 현재 확정 착장 상품 근거 없음 또는 저장 완료" for pid in sorted(absent))
    return BatchSelection(product_ids=tuple(int(row['id']) for row in rows), ready_product_ids=tuple(ready), reasons=tuple(reasons))
