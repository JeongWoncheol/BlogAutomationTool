# -*- coding: utf-8 -*-
from . import content_adapter

def health():
    h=content_adapter.health()
    return {"ready":h.get("ready",True),"name":"제목·본문·태그","message":"Ollama(Qwen3) 무료 로컬 AI 1순위 · 사람과 대화하듯 자연스러운 후기체 + 감탄/질문 다양화 · AI/보고서체 자동 감지 후 재작성 · 제목/본문/태그를 상품마다 새로 생성 · 최근 제목/문장/소제목 중복 감지 후 자동 재작성 · 구매욕/링크확인 CTA 품질검증 · OpenAI 자동사용 OFF · 로컬 AI 실패 시 제품군 안전원고 자동복구 · "+str(h.get("message") or "")}

def run(context=None,progress=None):
    return content_adapter.run_text(context,progress)
