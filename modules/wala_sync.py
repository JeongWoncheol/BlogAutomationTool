from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from .wala_client import WalaClient, WalaError, WalaAccessError, WalaUnavailableError
from . import wala_store


class CollectResult(TypedDict):
    count: int
    candidate_ids: list[int]
    raw_sources: int
    errors: list[str]
    stopped: bool
    archive: wala_store.ArchiveCounts
    message: str


def collect_latest(days: int = 0, celebrity: str = "",
                   progress: Callable[[int, int, str], None] | None = None,
                   stop_check: Callable[[], bool] | None = None,
                   max_articles: int = 50) -> CollectResult:
    """Index the complete sitemap and fetch the next explicit batch only."""
    errors: list[str] = []
    fetched = 0
    stopped = False
    with WalaClient() as client:
        if progress:
            progress(0, 1, "왈라랜드 전체 공개 목록 확인 중")
        wala_store.index_archive(client.article_ids())
        pending = wala_store.pending_ids(max(1, min(500, max_articles)))
        for index, article_id in enumerate(pending):
            if stop_check and stop_check():
                stopped = True
                break
            if progress:
                progress(index, len(pending), f"왈라랜드 원문 {index + 1}/{len(pending)} · {article_id}")
            try:
                article = client.article(article_id)
                wala_store.save_article(article)
                fetched += 1
            except WalaUnavailableError as exc:
                wala_store.record_error(article_id, str(exc), unavailable=True)
            except WalaAccessError as exc:
                wala_store.record_error(article_id, str(exc))
                errors.append(str(exc))
                stopped = True
                break
            except WalaError as exc:
                wala_store.record_error(article_id, str(exc))
                errors.append(str(exc))
    cutoff = (datetime.now(timezone(timedelta(hours=9))).date()
              - timedelta(days=days)) if days > 0 else None
    needle = "".join(celebrity.split()).casefold()
    candidate_ids: list[int] = []
    for article in wala_store.cached_articles():
        if cutoff and article.published_at.date() < cutoff:
            continue
        haystack = "".join((article.title + article.title_eng + " ".join(article.tags)).split()).casefold()
        if needle and needle not in haystack:
            continue
        candidate_ids.append(wala_store.save_candidate(article))
    counts = wala_store.archive_counts()
    prefix = "수집 중지" if stopped else "이번 수집 완료"
    message = (f"{prefix} · 새 원문 {fetched}건 · 검색 일치 {len(candidate_ids)}건 · "
               f"전체 {counts['total']}건 중 저장 {counts['cached']}건 / "
               f"남음 {counts['pending']}건 / 비공개·삭제 {counts['unavailable']}건 / 오류 {counts['errors']}건")
    if needle or days > 0:
        message += " · 검색은 현재 저장된 원문 기준 (남은 원문은 다음 수집으로 계속)"
    return CollectResult(count=len(candidate_ids), candidate_ids=candidate_ids,
                         raw_sources=fetched, errors=errors, stopped=stopped,
                         archive=counts, message=message)
