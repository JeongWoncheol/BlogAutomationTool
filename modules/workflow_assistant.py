# -*- coding: utf-8 -*-
"""Small read-only workflow helper for the Studio dashboard."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .common import DB, ROOT, init_db, settings


GUIDE_PATH = ROOT / "기능_한눈에보기.txt"


def health():
    return {"ready": True, "name": "작업 도우미", "message": "기능 안내·다음 단계·실패 재시도 준비됨"}


def guide_text():
    try:
        return GUIDE_PATH.read_text(encoding="utf-8")
    except Exception:
        return "기능 설명 파일을 읽지 못했습니다. README_KR.txt를 확인하세요."


def _where(batch_id=""):
    where = ["COALESCE(status,'') NOT LIKE '추천제외:%'", "COALESCE(already_posted,0)=0"]
    params = []
    if str(batch_id or "").strip():
        where.append("COALESCE(import_batch_id,'')=?")
        params.append(str(batch_id).strip())
    return " AND ".join(where), params


def snapshot(batch_id=""):
    init_db()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    where, params = _where(batch_id)
    rows = con.execute("SELECT * FROM products WHERE " + where + " ORDER BY product_no,id", params).fetchall()
    posted_where = "COALESCE(status,'') NOT LIKE '추천제외:%'"
    posted_params = []
    if str(batch_id or "").strip():
        posted_where += " AND COALESCE(import_batch_id,'')=?"
        posted_params.append(str(batch_id).strip())
    posted, review = con.execute(
        "SELECT SUM(CASE WHEN COALESCE(already_posted,0)=1 THEN 1 ELSE 0 END),"
        "SUM(CASE WHEN COALESCE(already_posted_review,0)=1 AND COALESCE(already_posted,0)=0 THEN 1 ELSE 0 END) "
        "FROM products WHERE " + posted_where,
        posted_params,
    ).fetchone()
    con.close()
    min_tags = max(20, int(settings().get("seo_min_related_tags", 20)))
    result = {
        "total": len(rows), "posted": int(posted or 0), "review": int(review or 0),
        "content_missing": 0, "image_complete": 0, "image_incomplete": 0,
        "sharelink_missing": 0, "draft_ready_images": 0, "draft_ready_text": 0,
        "draft_saved": 0, "draft_failed": 0,
    }
    for row in rows:
        tag_count = len([value for value in re.split(r"[,\n]+", str(row["tags"] or "")) if value.strip()])
        content_ok = bool(row["title"] and row["body"] and row["tags"] and tag_count >= min_tags)
        images_ok = int(row["image_verified_count"] or 0) >= 3 and all(
            str(row[key] or "").strip() and Path(str(row[key])).is_file() for key in ("image1", "image2", "image3")
        )
        saved = str(row["status"] or "").startswith("임시저장완료")
        failed = str(row["status"] or "") == "임시저장실패"
        if not content_ok: result["content_missing"] += 1
        if images_ok: result["image_complete"] += 1
        else: result["image_incomplete"] += 1
        if images_ok and not str(row["sharelink"] or "").strip(): result["sharelink_missing"] += 1
        if saved: result["draft_saved"] += 1
        elif content_ok and images_ok: result["draft_ready_images"] += 1
        elif content_ok: result["draft_ready_text"] += 1
        if failed: result["draft_failed"] += 1
    return result


def recommendation(batch_id="", selected_batch=False):
    state = snapshot(batch_id)
    if state["total"] == 0:
        action = "외부 원고 폴더를 가져오거나 인기상품 수집을 먼저 실행하세요."
    elif state["review"]:
        action = "‘게시완료/남은목록’에서 자동대조 확인필요 제품을 먼저 확인하세요."
    elif state["content_missing"]:
        action = "‘신규·실패 제목·본문·태그 만들기’를 실행하세요."
    elif state["draft_failed"]:
        action = "‘마지막 임시저장 실패 재시도’로 실패한 1건부터 다시 확인하세요."
    elif state["sharelink_missing"]:
        action = "‘제휴링크 무클릭 생성’을 실행해 사진 3장 완료 제품의 링크를 준비하세요."
    elif state["draft_ready_images"]:
        action = "‘사진3장 완료만 임시저장’을 실행하세요. 기존 게시글과 완료 글은 자동 제외됩니다."
    elif state["image_incomplete"]:
        action = "사진이 필요한 제품은 ‘사진 3장 가져오기/보강’을, 글만 저장할 제품은 ‘이미지 미완료만 텍스트 임시저장’을 사용하세요."
    elif state["draft_ready_text"]:
        action = "‘이미지 미완료만 텍스트 임시저장’을 실행하세요."
    else:
        action = "현재 선택 범위의 임시저장 작업이 모두 완료됐습니다. ‘게시완료/남은목록’으로 최종 확인하세요."
    scope = "선택한 외부 원고 묶음" if selected_batch else "현재 전체 상품"
    summary = (
        f"[{scope}] 남은 제품 {state['total']}개 · 기존 게시완료 {state['posted']}개 · 확인필요 {state['review']}개\n"
        f"원고 보완 {state['content_missing']}개 · 사진3장 완료 {state['image_complete']}개 · 이미지 미완료 {state['image_incomplete']}개\n"
        f"임시저장 완료 {state['draft_saved']}개 · 실패 {state['draft_failed']}개\n\n추천 작업\n{action}"
    )
    return {"action": action, "summary": summary, "state": state}


def last_failed_product(batch_id=""):
    init_db()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    where = ["COALESCE(status,'')='임시저장실패'", "COALESCE(already_posted,0)=0"]
    params = []
    if str(batch_id or "").strip():
        where.append("COALESCE(import_batch_id,'')=?")
        params.append(str(batch_id).strip())
    row = con.execute(
        "SELECT * FROM products WHERE " + " AND ".join(where) + " ORDER BY COALESCE(updated_at,'') DESC,id DESC LIMIT 1",
        params,
    ).fetchone()
    con.close()
    if row is None: return None
    image_paths = [str(row[key] or "") for key in ("image1", "image2", "image3")]
    images_ok = int(row["image_verified_count"] or 0) >= 3 and all(Path(path).is_file() for path in image_paths)
    return {
        "id": int(row["id"]), "product_no": int(row["product_no"] or row["id"]), "name": str(row["name"] or ""),
        "mode": "images_only" if images_ok else "text_only", "last_error": str(row["last_error"] or "원인 기록 없음"),
    }
