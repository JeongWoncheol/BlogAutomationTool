from collections.abc import Callable
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import ClassVar, Final, Literal

from PIL import Image, ImageTk, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from . import celebrity_style_adapter
from .celebrity_dashboard_pipeline import DashboardRequest, PipelineResult
from .celebrity_source import use_source

SearchSource = Literal["google", "naver"]
SOURCES: Final[dict[str, SearchSource]] = {"Google": "google", "네이버": "naver"}
PERIODS: Final = {"최근 7일": 7, "최근 30일": 30, "최근 1년": 365, "전체 기간": 0}


class PreviewItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    item_category: str | None = None
    item_description: str | None = None
    brand: str | None = None
    model_name: str | None = None
    color: str | None = None
    exact_claim_allowed: bool = False
    match_type: str | None = None
    matched_name: str | None = None
    matched_url: str | None = None


class PreviewSource(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    title: str | None = None
    url: str | None = None


class ReferenceImage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    file: str | None = None


class PreviewVision(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    images: tuple[ReferenceImage, ...] = ()


class PreviewBlock(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    text: str | None = None
    lines: tuple[str, ...] = ()


class PreviewCandidate(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    id: int
    celebrity_name: str | None = None
    look_type: str | None = None
    status: str | None = None
    summary: str | None = None
    promoted_product_id: int = 0
    draft_title: str | None = None
    draft_body: str | None = None
    draft_tags: str | None = None
    items: tuple[PreviewItem, ...] = ()
    sources: tuple[PreviewSource, ...] = ()
    vision: PreviewVision = PreviewVision()


class CelebrityDashboardPanel:
    """Own mutable Tk controls and the completed batch currently shown to the user."""

    def __init__(self, card: tk.Frame, on_run: Callable[[bool], None], on_save: Callable[[], None]) -> None:
        self.card = card
        self.name = tk.StringVar(master=card)
        self.source = tk.StringVar(master=card, value="Google")
        self.period = tk.StringVar(master=card, value="최근 30일")
        self.limit = tk.StringVar(master=card, value="3")
        self.status = tk.StringVar(master=card, value="인물명을 입력하고 검색처를 선택하세요.")
        self.result: PipelineResult | None = None
        self.result_source: SearchSource = "google"
        self.candidates: dict[str, PreviewCandidate] = {}
        self.preview_images: dict[tk.Toplevel, ImageTk.PhotoImage] = {}
        form = ttk.Frame(card, style="Card.TFrame", padding=14)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for row, label in enumerate(("연예인 이름", "검색 조건")):
            ttk.Label(form, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(form, textvariable=self.name).grid(row=0, column=1, sticky="ew", pady=4)
        options = ttk.Frame(form, style="Card.TFrame")
        options.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Combobox(options, textvariable=self.source, values=tuple(SOURCES), state="readonly", width=9).pack(side="left", padx=(0, 8))
        ttk.Combobox(options, textvariable=self.period, values=tuple(PERIODS), state="readonly", width=12).pack(side="left", padx=(0, 8))
        ttk.Label(options, text="착장 후보", style="Card.TLabel").pack(side="left", padx=(0, 4))
        ttk.Spinbox(options, from_=1, to=20, textvariable=self.limit, width=4).pack(side="left")
        ttk.Label(options, text="개까지", style="Card.TLabel").pack(side="left", padx=(4, 0))
        actions = ttk.Frame(card, style="Card.TFrame", padding=(14, 0, 14, 8))
        actions.pack(fill="x")
        for col in range(2):
            actions.columnconfigure(col, weight=1)
        ttk.Button(actions, text="착장 원고·제휴 준비", style="Soft.TButton", command=lambda: on_run(False)).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(actions, text="검색부터 네이버 임시저장", style="Accent.TButton", command=lambda: on_run(True)).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=4)
        self.save_button = ttk.Button(actions, text="준비된 원고 임시저장", style="Accent.TButton", command=on_save, state="disabled")
        self.save_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(actions, text="선택 착장·원고 확인", style="Soft.TButton", command=self.open_preview).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=4)
        self.progress = ttk.Progressbar(card, maximum=100)
        self.progress.pack(fill="x", padx=14, pady=(0, 4))
        status = ttk.Label(card, textvariable=self.status, style="Card.TLabel", justify="left")
        status.pack(fill="x", padx=14, pady=(0, 8))
        card.bind("<Configure>", lambda event: status.configure(wraplength=max(220, event.width - 32)), add="+")
        table_frame = ttk.Frame(card, style="Card.TFrame", padding=(14, 0, 14, 14))
        table_frame.pack(fill="x")
        table_frame.columnconfigure(0, weight=1)
        self.table = ttk.Treeview(table_frame, columns=("name", "items", "state"), show="headings", height=4)
        for key, title, width in (("name", "인물 · 착장", 210), ("items", "확인 제품", 280), ("state", "진행 상태", 180)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=90)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.bind("<Double-1>", lambda _event: self.open_preview())

    def request(self, save_draft: bool) -> DashboardRequest:
        return DashboardRequest(celebrity=self.name.get().strip(), source=SOURCES[self.source.get()],
                                days=PERIODS[self.period.get()], max_articles=int(self.limit.get()), save_draft=save_draft)

    def clear_result(self) -> None:
        self.result = None
        self.candidates.clear()
        self.table.delete(*self.table.get_children())
        self.save_button.configure(state="disabled")

    def show_result(self, result: PipelineResult, source: SearchSource) -> None:
        self.clear_result()
        self.result = result
        self.result_source = source
        self.status.set(result.message)
        with use_source(source):
            for candidate_id in result.candidate_ids:
                raw = celebrity_style_adapter.candidate_detail(candidate_id)
                if not raw:
                    continue
                candidate = PreviewCandidate.model_validate(raw)
                key = str(candidate.id)
                self.candidates[key] = candidate
                products = [item.matched_name for item in candidate.items if item.exact_claim_allowed and item.match_type and item.match_type.startswith("정확상품") and item.matched_name]
                state = "제휴 원고 준비 완료" if candidate.promoted_product_id in result.ready_product_ids else candidate.status
                self.table.insert("", "end", iid=key, values=(f"{candidate.celebrity_name or ''} · {candidate.look_type or ''}", " / ".join(products) or "제품 확인 필요", state or "대기"))
        self.save_button.configure(state="normal" if result.ready_product_ids else "disabled")

    def open_preview(self) -> None:
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("착장 선택", "확인할 착장 후보를 선택하세요.", parent=self.card)
            return
        candidate = self.candidates[selected[0]]
        window = tk.Toplevel(self.card)
        window.title(f"{candidate.celebrity_name or ''} 착장 · 근거와 원고")
        window.geometry("900x640")
        window.minsize(640, 420)
        body = ttk.Frame(window, padding=14)
        body.pack(fill="both", expand=True)
        files = [Path(ref.file) for ref in candidate.vision.images if ref.file and Path(ref.file).is_file()]
        if files:
            try:
                with Image.open(files[0]) as picture:
                    picture.thumbnail((220, 240))
                    preview = ImageTk.PhotoImage(picture.copy(), master=window)
                label = ttk.Label(body, image=preview)
                label.pack(side="left", anchor="n", padx=(0, 14))
                self.preview_images[window] = preview
                window.bind("<Destroy>", lambda event: self.preview_images.pop(window, None) if event.widget == window else None, add="+")
            except (OSError, UnidentifiedImageError):
                ttk.Label(body, text="참고 이미지를 열 수 없습니다.").pack(anchor="w")
        lines = [candidate.draft_title or candidate.celebrity_name or "착장", candidate.summary or "", f"AI 분석 참고 사진: {len(files)}장", "", "착장 아이템"]
        for item in candidate.items:
            identity = "정확 제품 근거 확인" if item.exact_claim_allowed else "시각 추정 · 제품 미확정"
            lines.extend((f"• {item.item_category or ''} / {item.color or ''} / {item.item_description or ''}",
                          f"  {identity} · {item.brand or ''} {item.model_name or ''}",
                          f"  연결: {item.matched_name or '없음'} ({item.match_type or '미확인'})", item.matched_url or ""))
        lines.extend(("", "출처"))
        lines.extend(f"{source.title or ''}\n{source.url or ''}" for source in candidate.sources)
        lines.extend(("", "원고"))
        if candidate.draft_body:
            try:
                blocks = TypeAdapter(tuple[PreviewBlock, ...]).validate_json(candidate.draft_body)
                for block in blocks:
                    lines.extend((block.text,) if block.text else block.lines)
                    lines.append("")
            except ValidationError:
                lines.append("원고 형식을 확인해 주세요.")
        else:
            lines.append("원고 준비 전")
        lines.extend(("", "태그: " + (candidate.draft_tags or "")))
        text_frame = ttk.Frame(body)
        text_frame.pack(side="left", fill="both", expand=True)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text = tk.Text(text_frame, wrap="word", font=("Malgun Gothic", 9), relief="flat")
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_frame, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
