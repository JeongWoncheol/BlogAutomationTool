# -*- coding: utf-8 -*-
from pathlib import Path
import json, os, shutil, subprocess, sys, time, urllib.request
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules import ollama_local


def wait_server(sec=35):
    end=time.time()+sec
    while time.time()<end:
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=2).read();return True
        except Exception:time.sleep(1)
    return False

print("=== Ollama 무료 로컬 AI 자동설정 ===")
settings_path=ROOT/"data"/"settings.json"
try:cfg=json.loads(settings_path.read_text(encoding="utf-8"))
except Exception:cfg={}
profile=str(cfg.get("ollama_generation_profile") or "balanced")
info=ollama_local.hardware_info();model=ollama_local.recommend_model(info,profile)
print(f"RAM {info['ram_gb']}GB / NVIDIA VRAM {info['vram_gb']}GB")
print("실행 프로필:",profile)
print("추천 모델:",model,"(GPU 우선 판단 · 로컬 실행 · OpenAI API 비용 없음)")
exe=shutil.which("ollama")
if not exe:
    print("Ollama가 설치되어 있지 않습니다. Windows winget 설치를 시도합니다.")
    winget=shutil.which("winget")
    if not winget:
        print("winget을 찾지 못했습니다. https://ollama.com/download 에서 Ollama를 설치한 뒤 이 파일을 다시 실행하세요.")
        raise SystemExit(2)
    rc=subprocess.call([winget,"install","-e","--id","Ollama.Ollama","--accept-source-agreements","--accept-package-agreements"])
    if rc!=0:
        print("Ollama 자동 설치에 실패했습니다. 공식 설치 프로그램으로 설치 후 다시 실행하세요.");raise SystemExit(rc)
    exe=shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA",''))/"Programs"/"Ollama"/"ollama.exe")

if not wait_server(8):
    try:subprocess.Popen([exe,"serve"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except Exception:pass
if not wait_server(35):
    print("Ollama 서버가 시작되지 않았습니다. Windows를 한 번 재로그인하거나 Ollama 앱을 실행한 뒤 다시 시도하세요.");raise SystemExit(3)

try:
    installed_names=ollama_local.server_models()
except Exception:
    installed_names=[]
exact_installed=any(str(x).casefold()==model.casefold() for x in installed_names)
if exact_installed:
    print("이미 설치된 추천 모델 사용:",model)
else:
    print("모델 다운로드 시작:",model)
    print("최초 1회만 다운로드하며 모델 크기에 따라 시간이 걸릴 수 있습니다.")
    rc=subprocess.call([exe,"pull",model])
    if rc!=0:print("모델 다운로드 실패");raise SystemExit(rc)

ollama_local.write_selected_model(model)
print("\n완료:",model)
print("이제 프로그램에서 'Ollama 제목·본문·태그 생성'을 사용하면 됩니다.")
print("v8.08.40은 실시간 토큰/경과시간 표시와 GPU 기준 모델 선택으로 속도를 개선했습니다.")
print("OpenAI 자동사용은 기본 OFF라 API 비용이 발생하지 않습니다.")
