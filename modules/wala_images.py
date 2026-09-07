"""Keep source photographs in analysis evidence with their original attribution."""

import hashlib
import io
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import TypedDict
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import JsonValue

from .common import EVIDENCE, settings
from .wala_client import WalaClient
from .wala_errors import WalaAccessError, WalaError
from .wala_store import article_for_candidate


class ReferenceImage(TypedDict):
    title: str
    description: str
    image_url: str
    page_url: str
    host: str
    source_type: str
    score: int
    file: str


class ReferenceState(TypedDict):
    queries: list[str]
    candidates: list[ReferenceImage]
    downloaded: list[ReferenceImage]
    errors: list[str]
    stopped: bool


def reference_images(
    row: sqlite3.Row | Mapping[str, JsonValue],
    sources: Sequence[Mapping[str, JsonValue]],
    stop_check: Callable[[], bool] | None = None,
) -> ReferenceState:
    """Download only Wala article photographs; never put them in blog image slots."""
    del sources
    article = article_for_candidate(int(str(row["id"])))
    state = ReferenceState(queries=[article.url], candidates=[], downloaded=[], errors=[], stopped=False)
    for url in dict.fromkeys(article.images):
        state["candidates"].append(ReferenceImage(
            title=article.title, description="왈라랜드 원문 참고 사진 · 분석 전용",
            image_url=url, page_url=article.url, host=urlsplit(url).hostname or "",
            source_type="wala", score=0, file="",
        ))
    max_images = max(1, int(settings().get("celebrity_style_reference_max_images", 5)))
    directory = EVIDENCE / "celebrity_style" / str(row["id"]) / "references"
    with WalaClient() as client:
        for candidate in state["candidates"]:
            if stop_check and stop_check():
                state["errors"].append("이미지 수집을 중지했습니다.")
                state["stopped"] = True
                break
            url = candidate["image_url"]
            output = directory / ("wala_" + hashlib.sha256(url.encode()).hexdigest()[:20] + ".jpg")
            try:
                if not output.is_file():
                    data = client.image_bytes(url)
                    with Image.open(io.BytesIO(data)) as original:
                        original.load()
                        with ImageOps.exif_transpose(original).convert("RGB") as normalized:
                            directory.mkdir(parents=True, exist_ok=True)
                            normalized.save(output, "JPEG", quality=93)
                else:
                    with Image.open(output) as cached:
                        cached.verify()
                downloaded = candidate.copy()
                downloaded["file"] = str(output)
                state["downloaded"].append(downloaded)
            except WalaAccessError as exc:
                state["errors"].append(str(exc))
                state["stopped"] = True
                break
            except (WalaError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                state["errors"].append(f"{url}: {exc}")
            if len(state["downloaded"]) >= max_images:
                break
    return state
