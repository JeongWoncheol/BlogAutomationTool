from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationInfo, field_validator

from .common import DATA, settings

MARKET_CATEGORIES = ("생활용품", "주방용품", "패션잡화", "식품", "디지털/가전", "화장품/미용")
TREND_CATEGORIES = ("패션의류", "패션잡화", "화장품/미용", "디지털/가전", "가구/인테리어", "식품")
AGE_GROUPS = {"20~30대": ("20", "30"), "40~60대": ("40", "50", "60")}
type SettingsSnapshot = dict[str, JsonValue]
_SAVE_LOCK = RLock()


class CollectionPreferences(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    market_categories: tuple[str, ...] = MARKET_CATEGORIES
    trend_categories: tuple[str, ...] = TREND_CATEGORIES
    age_groups: tuple[str, ...] = tuple(AGE_GROUPS)

    @field_validator("market_categories", "trend_categories", "age_groups")
    @classmethod
    def known_nonempty(cls, values: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        choices = {"market_categories": MARKET_CATEGORIES, "trend_categories": TREND_CATEGORIES,
                   "age_groups": tuple(AGE_GROUPS)}[info.field_name or ""]
        if not values or any(value not in choices for value in values):
            message = f"수집 조건은 지원되는 항목을 하나 이상 선택해야 합니다: {', '.join(choices)}"
            raise ValueError(message)
        return tuple(dict.fromkeys(values))


def load_preferences(cfg: Mapping[str, JsonValue] | None = None) -> CollectionPreferences:
    source = settings() if cfg is None else cfg
    ages = source.get("trend_age_groups", AGE_GROUPS)
    if not isinstance(ages, dict):
        message = "trend_age_groups는 연령그룹과 연령코드의 매핑이어야 합니다."
        raise ValueError(message)
    for label, codes in ages.items():
        if label not in AGE_GROUPS or not isinstance(codes,(list,tuple)) or tuple(codes) != AGE_GROUPS[label]:
            message = f"지원하지 않는 연령그룹 또는 연령코드입니다: {label}"
            raise ValueError(message)
    return CollectionPreferences.model_validate({
        "market_categories": source.get("categories", MARKET_CATEGORIES),
        "trend_categories": source.get("trend_categories", TREND_CATEGORIES),
        "age_groups": tuple(ages),
    })


def apply_preferences(cfg: Mapping[str, JsonValue], preferences: CollectionPreferences) -> SettingsSnapshot:
    return {**cfg, "categories": list(preferences.market_categories),
            "trend_categories": list(preferences.trend_categories),
            "trend_age_groups": {label: list(AGE_GROUPS[label]) for label in preferences.age_groups}}


def save_preferences(preferences: CollectionPreferences, path: Path | None = None) -> None:
    target = DATA / "settings.json" if path is None else path
    with _SAVE_LOCK:
        cfg = json.loads(target.read_text(encoding="utf-8"))
        updated = apply_preferences(cfg, preferences)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".collection-", suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
