import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import ClassVar, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from .affiliate_identity import bound_evidence
from .common import verified_blog_image_set
from .coupang_partners_api import _valid_affiliate_url
from .wala_policy import SOURCE_REASON, ProductRow, is_wala_product

AffiliatePolicy = Literal["existing", "omit", "required"]
_AFFILIATE_URL: Final = re.compile(
    r"https?://(?:link\.coupang\.com|coupa\.ng)(?::443)?/[^\s<>\"\[\]]+", re.IGNORECASE
)


class AffiliateContext(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    affiliate_policy: AffiliatePolicy = "existing"


class AffiliatePost(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    sharelink: str = ""
    coupang_sharelink_evidence: dict[str, JsonValue] = {}


class AffiliatePolicyError(RuntimeError):
    pass


def affiliate_policy(context: Mapping[str, JsonValue] | None) -> AffiliatePolicy:
    return AffiliateContext.model_validate(context or {}).affiliate_policy


def _required_reason(row: ProductRow, post: AffiliatePost) -> str:
    if is_wala_product(row):
        return SOURCE_REASON
    link = str(row["sharelink"] or "").strip()
    if not _valid_affiliate_url(link):
        return "검증된 쿠팡 제휴링크 없음: 사진 3장 상품 제휴링크 만들기를 먼저 실행하세요."
    if post.sharelink != link or not bound_evidence(
        post.coupang_sharelink_evidence, link, str(row["name"] or ""),
        str(row["source_url"] or "") if "쿠팡" in str(row["source_platform"] or "") else "",
    ):
        return "쿠팡 제휴링크의 상품 연결 근거 불일치: 제휴링크를 다시 만들어 주세요."
    return ""


def affiliate_requirement_reason(row: ProductRow, policy: AffiliatePolicy) -> str:
    if policy != "required":
        return ""
    try:
        path = Path(str(row["post_dir"] or "")) / "post.json"
        post = AffiliatePost.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError):
        return "쿠팡 제휴링크의 원고 검증 기록을 읽을 수 없습니다."
    return _required_reason(row, post)


def _without_affiliate(value: JsonValue) -> JsonValue:
    match value:
        case str():
            return _AFFILIATE_URL.sub("", value).strip()
        case list():
            return [_without_affiliate(item) for item in value]
        case dict():
            return {key: _without_affiliate(item) for key, item in value.items()}
        case None | bool() | int() | float():
            return value
        case unreachable:
            assert_never(unreachable)


def prepare_affiliate_post(
    row: ProductRow, post: dict[str, JsonValue], policy: AffiliatePolicy,
) -> dict[str, JsonValue]:
    if policy != "existing":
        image_ok, detail = verified_blog_image_set(row, 3)
        if not image_ok:
            raise AffiliatePolicyError(str(detail.get("reason") or "동일 상품 사진 3장 검증 미완료"))
    match policy:
        case "existing":
            return post
        case "required":
            try:
                parsed = AffiliatePost.model_validate(post)
            except ValidationError as exc:
                raise AffiliatePolicyError("쿠팡 제휴링크 원고 검증 기록 형식 오류") from exc
            reason = _required_reason(row, parsed)
            if reason:
                raise AffiliatePolicyError(reason)
            return post
        case "omit":
            clean = deepcopy(post)
            blocks = clean.get("blocks")
            if isinstance(blocks, list):
                clean["blocks"] = [
                    _without_affiliate(block) for block in blocks
                    if not isinstance(block, dict)
                    or (block.get("type") != "sharelink" and block.get("role") != "sharelink")
                ]
            clean["sharelink"] = ""
            return clean
        case unreachable:
            assert_never(unreachable)
