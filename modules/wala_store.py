import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from .common import DB
from .wala_models import WalaArticle


class ArchiveCounts(TypedDict):
    total: int
    cached: int
    pending: int
    unavailable: int
    errors: int


def init_schema() -> None:
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS wala_archive (
            content_id INTEGER PRIMARY KEY, payload TEXT,
            fetched_at TEXT, last_error TEXT, unavailable INTEGER DEFAULT 0,
            in_sitemap INTEGER DEFAULT 1)""")


def index_archive(content_ids: list[int]) -> None:
    """Replace sitemap membership without deleting previously collected data."""
    init_schema()
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute("UPDATE wala_archive SET in_sitemap=0")
        con.executemany("""INSERT INTO wala_archive(content_id) VALUES(?)
            ON CONFLICT(content_id) DO UPDATE SET in_sitemap=1""",
            ((article_id,) for article_id in content_ids))


def pending_ids(limit: int) -> list[int]:
    """Fetch unseen pages first; retry failed pages on subsequent runs."""
    with closing(sqlite3.connect(DB)) as con:
        rows = con.execute("""SELECT content_id FROM wala_archive
            WHERE in_sitemap=1 AND payload IS NULL AND unavailable=0
            ORDER BY (last_error IS NOT NULL), content_id DESC LIMIT ?""", (limit,))
        return [int(row[0]) for row in rows]


def save_article(article: WalaArticle) -> None:
    """Commit each complete page so stopping never loses an entire batch."""
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute("""UPDATE wala_archive SET payload=?,fetched_at=?,
            last_error=NULL,unavailable=0 WHERE content_id=?""",
            (article.model_dump_json(), datetime.now(timezone.utc).isoformat(), article.id))


def record_error(article_id: int, message: str, unavailable: bool = False) -> None:
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute("UPDATE wala_archive SET last_error=?,unavailable=? WHERE content_id=?",
                    (message, int(unavailable), article_id))


def archive_counts() -> ArchiveCounts:
    init_schema()
    with closing(sqlite3.connect(DB)) as con:
        row = con.execute("""SELECT COUNT(*),
            COALESCE(SUM(payload IS NOT NULL),0),
            COALESCE(SUM(payload IS NULL AND unavailable=0),0),
            COALESCE(SUM(unavailable=1),0),
            COALESCE(SUM(last_error IS NOT NULL AND unavailable=0),0)
            FROM wala_archive WHERE in_sitemap=1""").fetchone()
        return ArchiveCounts(total=row[0], cached=row[1], pending=row[2],
                             unavailable=row[3], errors=row[4])


def cached_articles() -> list[WalaArticle]:
    with closing(sqlite3.connect(DB)) as con:
        return [WalaArticle.model_validate_json(row[0]) for row in con.execute(
            "SELECT payload FROM wala_archive WHERE payload IS NOT NULL ORDER BY content_id DESC")]


def export_archive(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for article in cached_articles():
            output.write(article.model_dump_json() + "\n")
    return path


def article_for_candidate(candidate_id: int) -> WalaArticle:
    with closing(sqlite3.connect(DB)) as con:
        row = con.execute("""SELECT a.payload FROM wala_archive a
            JOIN celebrity_style_candidates c ON c.fingerprint='wala:' || a.content_id
            WHERE c.id=?""", (candidate_id,)).fetchone()
        if row is None:
            message = f"왈라랜드 원문 캐시가 없습니다: 후보 {candidate_id}"
            raise LookupError(message)
        return WalaArticle.model_validate_json(row[0])


def selected_rows(candidate_ids: list[int] | None,
                  statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
    """None selects the Wala archive; an empty selection selects nothing."""
    if candidate_ids == []:
        return []
    with closing(sqlite3.connect(DB)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""SELECT * FROM celebrity_style_candidates
            WHERE fingerprint LIKE 'wala:%' ORDER BY event_date DESC,id DESC""").fetchall()
    selected = set(candidate_ids) if candidate_ids is not None else None
    return [row for row in rows if (selected is None or row["id"] in selected)
            and (statuses is None or row["status"] in statuses)]


def save_candidate(article: WalaArticle) -> int:
    """Retain publisher facts and leave finished analysis/drafts intact on rescan."""
    title_key = re.sub(r"\s+", "", article.title).casefold()
    name = next((tag for tag in article.tags if re.sub(r"\s+", "", tag).casefold()
                 in title_key), article.title[:60])
    now = datetime.now(timezone.utc).isoformat()
    source = {"source_type": "wala", "title": article.title,
              "description": article.description, "url": article.url,
              "pub_date": article.published_at.isoformat(), "content_id": article.id,
              "original_source_name": article.source_name,
              "original_source_url": article.source_link,
              "original_source_name2": article.source_name2,
              "original_source_url2": article.source_link2,
              "image_urls": article.images, "tags": article.tags,
              "products": [product.model_dump(mode="json") for product in article.products]}
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute("""INSERT INTO celebrity_style_candidates
            (fingerprint,celebrity_name,event_name,event_date,look_type,query_text,
             discovered_at,updated_at,source_count,independent_source_count,
             freshness_score,evidence_score,confidence_score,confidence_label,
             status,summary,source_json)
            VALUES(?,?,?,?,?,?,?,?,1,1,0,50,50,'단일 출처 소개','수집완료',?,?)
            ON CONFLICT(fingerprint) DO UPDATE SET source_json=excluded.source_json,
            event_name=excluded.event_name,event_date=excluded.event_date,
            updated_at=excluded.updated_at""",
            (f"wala:{article.id}", name, article.title,
             article.published_at.date().isoformat(), "왈라랜드 착장", "왈라랜드 공개 아카이브",
             now, now, article.title, json.dumps([source], ensure_ascii=False)))
        return int(con.execute("SELECT id FROM celebrity_style_candidates WHERE fingerprint=?",
                               (f"wala:{article.id}",)).fetchone()[0])
