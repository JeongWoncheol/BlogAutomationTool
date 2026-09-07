# -*- coding: utf-8 -*-
from pathlib import Path
import json, sys, urllib.request
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from modules.common import settings
from modules import ollama_local
cfg=settings();st=ollama_local.status(cfg)
print("=== Ollama 무료 AI 테스트 ===")
print("상태:",st.get("reason"));print("프로필:",cfg.get("ollama_generation_profile","balanced"));print("권장:",st.get("recommended"));print("사용 모델:",st.get("model"));print("하드웨어:",st.get("hardware"))
if not st.get("ready"):
    print("88_OLLAMA_FREE_AUTO_SETUP.cmd를 먼저 실행하세요.");raise SystemExit(2)
model=st["model"]
payload={"model":model,"messages":[{"role":"user","content":"한국어로 JSON만 답하세요. {\\\"status\\\":\\\"ok\\\",\\\"message\\\":\\\"로컬 AI 연결 성공\\\"}"}],"stream":False,"format":"json","think":False,"options":{"temperature":0.2,"num_ctx":4096}}
req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=180) as r:obj=json.loads(r.read().decode("utf-8","ignore"))
print("응답:",(obj.get("message") or {}).get("content") or "")
eval_count=int(obj.get("eval_count") or 0);eval_ns=int(obj.get("eval_duration") or 0)
if eval_count and eval_ns:print("생성 속도:",round(eval_count/(eval_ns/1_000_000_000),2),"tok/s")
print("PASS")
