"""Run an explicitly scoped celebrity search through verified affiliate drafts."""

from collections.abc import Callable, Sequence
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import blog_adapter, celebrity_style_adapter as style, common, content_adapter, coupang_sharelink_adapter
from .blog_target import require_target_blog_id
from .celebrity_dashboard_batch import inspect_batch, prepare_artifacts, visual_reason
from .celebrity_source import use_source

Progress = Callable[[int, int, str], None]
StopCheck = Callable[[], bool]
SearchSource = Literal['google', 'naver']


class DashboardRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, str_strip_whitespace=True)
    celebrity: str = Field(min_length=1, max_length=80)
    source: SearchSource
    days: int = Field(default=30, ge=0, le=365)
    max_articles: int = Field(default=3, ge=1, le=20)
    save_draft: bool = False


class StageResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    stage: str
    processed: int = 0
    stage_ok: bool = True
    stopped: bool = False
    message: str = ''


class AdapterResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    candidate_ids: tuple[int, ...] = ()
    product_id: int = 0
    processed: int = 0
    count: int = 0
    stage_ok: bool = True
    stopped: bool = False
    message: str = ''


class PipelineResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    candidate_ids: tuple[int, ...] = ()
    product_ids: tuple[int, ...] = ()
    ready_product_ids: tuple[int, ...] = ()
    counts: dict[str, int] = Field(default_factory=dict)
    stages: tuple[StageResult, ...] = ()
    stage_ok: bool = False
    stopped: bool = False
    message: str


def _stopped(stop_check: StopCheck | None) -> bool:
    return bool(stop_check and stop_check())


def save_prepared(product_ids: Sequence[int], progress: Progress | None = None, stop_check: StopCheck | None = None) -> PipelineResult:
    """Save only retained batch IDs after repeating all local identity gates."""
    ids = tuple(dict.fromkeys(pid for pid in product_ids if pid > 0))
    if _stopped(stop_check):
        return PipelineResult(product_ids=ids, stopped=True, message='사용자 중지 · 준비된 원고 보존')
    batch = inspect_batch(ids)
    if not batch.ready_product_ids:
        return PipelineResult(product_ids=ids, message='임시저장 가능한 확정 상품 없음 · ' + ' / '.join(batch.reasons[:3]))
    require_target_blog_id()
    if _stopped(stop_check):
        return PipelineResult(product_ids=ids, ready_product_ids=batch.ready_product_ids, stopped=True, message='사용자 중지 · 임시저장 실행 전 중단')
    try:
        raw = blog_adapter.run(context={'mode': 'images_only', 'affiliate_policy': 'required', 'product_ids': list(batch.ready_product_ids), 'stop_check': stop_check}, progress=progress)
    except (RuntimeError, OSError) as exc:
        common.log('착장 대시보드 임시저장 실패: ' + str(exc))
        return PipelineResult(product_ids=ids, ready_product_ids=inspect_batch(ids).ready_product_ids, stages=(StageResult(stage='draft_save', stage_ok=False, message=str(exc)),), message='임시저장 실패 · 준비된 원고 보존: ' + str(exc))
    result = AdapterResult.model_validate(raw)
    complete = result.stage_ok and not result.stopped and result.processed == len(ids)
    remaining = inspect_batch(ids).ready_product_ids
    return PipelineResult(product_ids=ids, ready_product_ids=remaining, counts={'saved': result.processed}, stages=(StageResult(stage='draft_save', processed=result.processed, stage_ok=complete, stopped=result.stopped, message=result.message),), stage_ok=complete, stopped=result.stopped, message=result.message + ((' · 제외 ' + ' / '.join(batch.reasons[:3])) if batch.reasons else ''))


def run(celebrity: str, source: SearchSource, days: int = 30, max_articles: int = 3, save_draft: bool = False, progress: Progress | None = None, stop_check: StopCheck | None = None) -> PipelineResult:
    """Search, analyze, draft and affiliate only the candidates found by this job."""
    request = DashboardRequest(celebrity=celebrity, source=source, days=days, max_articles=max_articles, save_draft=save_draft)
    if request.save_draft:
        require_target_blog_id()
    candidate_ids: tuple[int, ...] = ()
    product_ids: list[int] = []
    stages: list[StageResult] = []
    reasons: list[str] = []

    def finish(message: str, *, stopped: bool = False, saved: PipelineResult | None = None) -> PipelineResult:
        batch = inspect_batch(product_ids)
        pending_reasons = list(batch.reasons) if saved is None else []
        all_stages = tuple(stages) + (saved.stages if saved else ())
        ready = batch.ready_product_ids if saved is None else saved.ready_product_ids
        products_complete = saved.stage_ok if saved is not None else len(ready) == len(product_ids)
        complete = bool(product_ids) and products_complete and not reasons and all(stage.stage_ok for stage in all_stages) and not stopped
        if request.save_draft:
            complete = complete and saved is not None and saved.stage_ok
        return PipelineResult(candidate_ids=candidate_ids, product_ids=tuple(product_ids), ready_product_ids=ready, counts={'candidates': len(candidate_ids), 'promoted': len(product_ids), 'ready': len(ready), 'review': len(reasons), 'saved': saved.counts.get('saved', 0) if saved else 0}, stages=all_stages, stage_ok=complete, stopped=stopped, message=message + ((' · 확인 필요: ' + ' / '.join((reasons + pending_reasons)[:3])) if reasons or pending_reasons else ''))

    def record(name: str, result: AdapterResult) -> AdapterResult:
        stages.append(StageResult(stage=name, processed=result.processed or result.count, stage_ok=result.stage_ok and not result.stopped, stopped=result.stopped, message=result.message))
        return result

    with use_source(request.source):
        if _stopped(stop_check):
            return finish('사용자 중지 · 검색 실행 전 중단', stopped=True)
        result = record('search', AdapterResult.model_validate(style.collect_latest(days=request.days, celebrity=request.celebrity, max_articles=request.max_articles, progress=progress, stop_check=stop_check)))
        candidate_ids = tuple(dict.fromkeys(result.candidate_ids))
        if result.stopped or _stopped(stop_check):
            return finish('사용자 중지 · 수집된 후보 보존', stopped=True)
        if not candidate_ids:
            return finish(result.message or '조건에 맞는 착장 검색 결과 없음')
        for name, action in (('reference_images', style.collect_reference_images), ('analysis', style.analyze_unfinished), ('matching', style.match_products), ('draft_content', style.generate_drafts)):
            if _stopped(stop_check):
                return finish('사용자 중지 · 수집·분석 결과 보존', stopped=True)
            result = record(name, AdapterResult.model_validate(action(candidate_ids=list(candidate_ids), progress=progress, stop_check=stop_check)))
            if result.stopped:
                return finish(result.message, stopped=True)
        for candidate_id in candidate_ids:
            if _stopped(stop_check):
                return finish('사용자 중지 · 확정 상품 원고 보존', stopped=True)
            reason = visual_reason(candidate_id)
            if reason:
                reasons.append(f'후보 {candidate_id}: {reason}')
                continue
            try:
                result = AdapterResult.model_validate(style.promote_candidate(candidate_id, exact_only=True))
            except RuntimeError as exc:
                reasons.append(f'후보 {candidate_id}: {exc}')
                continue
            if result.product_id > 0:
                product_ids.append(result.product_id)
        product_ids = list(dict.fromkeys(product_ids))
        if not product_ids:
            return finish('자동 처리 가능한 확정 상품 없음 · 착장 후보에서 근거 확인')
        artifacts = prepare_artifacts(product_ids)
        reasons.extend(artifacts.reasons)
        if not artifacts.product_ids:
            return finish('원고 파일 준비 미완료')
        if _stopped(stop_check):
            return finish('사용자 중지 · 원고 파일 보존', stopped=True)
        result = record('product_images', AdapterResult.model_validate(content_adapter.run_images(context={'product_ids': list(artifacts.product_ids), 'stop_check': stop_check}, progress=progress)))
        if result.stopped or _stopped(stop_check):
            return finish('사용자 중지 · 수집한 상품 사진 보존', stopped=True)
        result = record('affiliate', AdapterResult.model_validate(coupang_sharelink_adapter.run(context={'product_ids': list(artifacts.product_ids)}, progress=progress, stop_check=stop_check)))
        if result.stopped or _stopped(stop_check):
            return finish('사용자 중지 · 생성한 제휴링크 보존', stopped=True)
        if request.save_draft:
            saved = save_prepared(product_ids, progress, stop_check)
            return finish(saved.message, stopped=saved.stopped, saved=saved)
        batch = inspect_batch(product_ids)
        return finish(f'착장 후보 {len(candidate_ids)}건 · 대표 확정 상품 {len(product_ids)}건 · 제휴 원고 준비 {len(batch.ready_product_ids)}건')
