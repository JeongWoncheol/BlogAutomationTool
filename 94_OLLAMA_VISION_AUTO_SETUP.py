# -*- coding: utf-8 -*-
import re, shutil, subprocess, sys
from modules import ollama_local

print("[NBlog v8.08.44] 연예인 착장용 Qwen3-VL 설치 점검")
exe=shutil.which("ollama")
if not exe:
    print("Ollama 실행파일을 찾지 못했습니다. 먼저 88_OLLAMA_FREE_AUTO_SETUP.cmd를 실행하세요.")
    input("Enter를 누르면 종료합니다...");raise SystemExit(2)
try:
    ver=subprocess.run([exe,"--version"],capture_output=True,text=True,timeout=10)
    text=(ver.stdout or ver.stderr or "").strip();print("Ollama:",text)
    m=re.search(r"(\d+)\.(\d+)\.(\d+)",text)
    if m and tuple(map(int,m.groups())) < (0,12,7):
        print("경고: Qwen3-VL은 Ollama 0.12.7 이상이 권장/필요합니다. Ollama를 최신 버전으로 업데이트하세요.")
except Exception as e:print("버전 확인 경고:",e)
info=ollama_local.hardware_info();vram=float(info.get("vram_gb") or 0);ram=float(info.get("ram_gb") or 0)
if vram>=7:model="qwen3-vl:8b"
elif vram>=3.5 or ram>=16:model="qwen3-vl:4b"
else:model="qwen3-vl:2b"
print(f"하드웨어: RAM {ram:.1f}GB / VRAM {vram:.1f}GB -> 권장 Vision 모델 {model}")
try:
    names=ollama_local.server_models(timeout=3)
    if any(ollama_local._same_model(model,x) for x in names):
        print(model,"이미 설치되어 있습니다.")
    else:
        print(model,"다운로드를 시작합니다.")
        r=subprocess.run([exe,"pull",model])
        if r.returncode!=0:raise RuntimeError("ollama pull 실패")
    print("설치 완료. 프로그램의 '연예인 착장 트렌드' 화면에서 Vision 상태를 확인하세요.")
except Exception as e:
    print("설치 실패:",e);input("Enter를 누르면 종료합니다...");raise SystemExit(1)
input("Enter를 누르면 종료합니다...")
