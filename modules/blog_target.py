import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, override
from urllib.parse import SplitResult, parse_qs, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver

from .common import DATA, settings

_HOSTS: Final = frozenset({"blog.naver.com", "m.blog.naver.com"})
_ID: Final = re.compile(r"[A-Za-z0-9_.-]{3,64}\Z")


@dataclass(frozen=True, slots=True)
class BlogTargetError(RuntimeError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


class EditorEvidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    url: str
    ids: tuple[str, ...] = ()
    has_title_editor: bool
    has_body_editor: bool


def _naver_url(value: str, *, editor: bool = False) -> SplitResult:
    try:
        parsed = urlsplit(value)
        allowed_scheme = (
            parsed.scheme == "https" if editor else parsed.scheme in {"http", "https"}
        )
        allowed_port = (
            parsed.port in (None, 443) if editor else parsed.port in (None, 80, 443)
        )
        valid = (
            allowed_scheme
            and allowed_port
            and parsed.hostname in _HOSTS
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError as exc:
        raise BlogTargetError("올바른 네이버 블로그 주소를 입력하세요.") from exc
    if not valid:
        raise BlogTargetError("네이버 블로그 주소 또는 블로그 ID를 입력하세요.")
    return parsed


def normalize_blog_id(value: str) -> str:
    raw = value.strip()
    if "://" in raw or raw.startswith(("blog.naver.com/", "m.blog.naver.com/")):
        parsed = _naver_url(raw if "://" in raw else "https://" + raw)
        query = parse_qs(parsed.query)
        identifiers = {
            value.casefold()
            for value in query.get("blogId", []) + query.get("blogid", [])
        }
        if len(identifiers) > 1:
            raise BlogTargetError(
                "주소에 서로 다른 블로그 ID가 있습니다. 대상 주소를 다시 확인하세요."
            )
        raw = (
            next(iter(identifiers))
            if identifiers
            else parsed.path.strip("/").split("/")[0]
        )
        if raw.lower().endswith(".naver"):
            raise BlogTargetError("주소에서 대상 블로그 ID를 찾지 못했습니다.")
    if not _ID.fullmatch(raw):
        raise BlogTargetError(
            "블로그 ID는 영문·숫자·밑줄·점·하이픈 3~64자로 입력하세요."
        )
    return raw.casefold()


def get_target_blog_id() -> str:
    value = str(settings().get("target_blog_id") or "").strip()
    return normalize_blog_id(value) if value else ""


def require_target_blog_id() -> str:
    target = get_target_blog_id()
    if not target:
        raise BlogTargetError(
            "먼저 계정·연결 화면에서 저장할 네이버 블로그 주소를 설정하세요."
        )
    return target


def save_target_blog(value: str) -> str:
    target = normalize_blog_id(value)
    current = settings()
    current["target_blog_id"] = target
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=DATA,
        prefix="settings-",
        suffix=".tmp",
        delete=False,
    ) as output:
        temporary = Path(output.name)
        json.dump(current, output, ensure_ascii=False, indent=2)
        output.write("\n")
    try:
        os.replace(temporary, DATA / "settings.json")
    finally:
        temporary.unlink(missing_ok=True)
    return target


def public_blog_url() -> str:
    target = get_target_blog_id()
    return "https://blog.naver.com/" + target if target else ""


def write_url() -> str:
    return "https://blog.naver.com/GoBlogWrite.naver?" + urlencode(
        {"blogId": require_target_blog_id()}
    )


def assert_editor_target(driver: WebDriver, expected: str) -> str:
    if require_target_blog_id() != expected:
        raise BlogTargetError("실행 도중 대상 블로그가 변경되어 작성을 중지했습니다.")
    try:
        evidence = EditorEvidence.model_validate(
            driver.execute_script("""
          const fields = 'input[name="blogId"],input[name="blogid"],input#blogId';
          const ids = [...document.querySelectorAll(fields)]
            .map(e => String(e.value || '').trim()).filter(Boolean);
          for (const key of ['blogId', 'g_blogId']) {
            if (typeof window[key] === 'string' && window[key].trim()) {
              ids.push(window[key].trim());
            }
          }
          const visible = e => {
            const style = getComputedStyle(e);
            return e.getClientRects().length > 0 && style.display !== 'none' &&
              style.visibility !== 'hidden' && style.visibility !== 'collapse';
          };
          const present = selector =>
            [...document.querySelectorAll(selector)].some(visible);
          const title = '.se-title-text,.se-section-documentTitle,.se-documentTitle,' +
            '[contenteditable="true"][data-placeholder*="제목"],' +
            '[contenteditable="true"][aria-label*="제목"]';
          const body = '.se-main-container,.se-content,.se-components-wrap';
          return {url: window.location.href, ids: [...new Set(ids)],
            has_title_editor: present(title),
            has_body_editor: present(body)};
        """)
        )
    except (ValidationError, WebDriverException) as exc:
        raise BlogTargetError(
            "편집기의 대상 블로그 정보를 읽지 못했습니다. 글 입력을 중지합니다."
        ) from exc
    parsed = _naver_url(evidence.url, editor=True)
    parts = parsed.path.strip("/").split("/")
    write_route = (
        parsed.path.casefold()
        in {"/goblogwrite.naver", "/postwrite.naver", "/postwriteform.naver"}
        or len(parts) >= 2
        and parts[1].casefold() in {"postwrite", "write"}
    )
    if not write_route or not evidence.has_title_editor or not evidence.has_body_editor:
        raise BlogTargetError(
            "네이버 글쓰기 편집기에서 대상 블로그를 확인하지 못했습니다."
        )
    ids = {normalize_blog_id(value) for value in evidence.ids}
    if parsed.path.lower() != "/goblogwrite.naver":
        query = parse_qs(parsed.query)
        ids.update(
            normalize_blog_id(value)
            for value in query.get("blogId", []) + query.get("blogid", [])
        )
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[1].casefold() in {"postwrite", "write"}:
            ids.add(normalize_blog_id(parts[0]))
    if ids != {expected}:
        actual = ", ".join(sorted(ids)) if ids else "확인 불가"
        raise BlogTargetError(
            f"저장 대상 불일치: 설정 {expected} / 편집기 {actual}. "
            "계정과 주소를 확인하세요."
        )
    return expected
