import re

from .common import settings
from .wala_policy import ProductRow, is_wala_product


def tag_requirement_reason(row: ProductRow) -> str:
    tags = {tag.strip().lstrip("#").casefold() for tag in re.split(r"[,\n]+", str(row["tags"] or ""))}
    tags.discard("")
    minimum = 1 if is_wala_product(row) else max(20, int(settings().get("seo_min_related_tags", 20)))
    return f"관련 태그 {minimum}개 미만 (중복 제외 {len(tags)}개)" if len(tags) < minimum else ""
