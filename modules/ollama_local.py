# -*- coding: utf-8 -*-
from pathlib import Path
import ctypes, json, os, shutil, subprocess, time, urllib.request
from .common import DATA, settings, log

QUALITY_ORDER=["qwen3:30b","qwen3:14b","qwen3:8b","qwen3:4b"]
MODEL_SIZE_GB={"qwen3:30b":19.0,"qwen3:14b":9.3,"qwen3:8b":5.2,"qwen3:4b":2.5}


def _ram_gb():
    try:
        if os.name=="nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_=[("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),("ullAvailExtendedVirtual",ctypes.c_ulonglong)]
            st=MEMORYSTATUSEX();st.dwLength=ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return round(st.ullTotalPhys/(1024**3),1)
        if hasattr(os,"sysconf"):
            return round(os.sysconf("SC_PAGE_SIZE")*os.sysconf("SC_PHYS_PAGES")/(1024**3),1)
    except Exception:pass
    return 0.0


def _vram_gb():
    try:
        p=subprocess.run(["nvidia-smi","--query-gpu=memory.total","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=4)
        if p.returncode==0:
            vals=[]
            for line in p.stdout.splitlines():
                try:vals.append(float(line.strip())/1024.0)
                except Exception:pass
            return round(max(vals),1) if vals else 0.0
    except Exception:pass
    return 0.0


def hardware_info():
    return {"ram_gb":_ram_gb(),"vram_gb":_vram_gb(),"nvidia":bool(_vram_gb())}


def recommend_model(info=None, mode="balanced"):
    """Choose a model by *actual accelerator capacity*, not RAM alone.

    v8.08.39 could select 14B/30B on a machine with lots of system RAM but no
    suitable GPU. That works, but it can be extremely slow because most layers
    run on CPU. v8.08.40 defaults to the 8B balanced profile and only selects
    larger models when GPU memory makes them practical.
    """
    info=info or hardware_info();ram=float(info.get("ram_gb") or 0);vram=float(info.get("vram_gb") or 0)
    mode=str(mode or "balanced").strip().lower()
    if mode in {"speed","fast","turbo"}:
        if vram>=6:return "qwen3:8b"
        return "qwen3:4b"
    if mode in {"quality","high","max"}:
        if vram>=20:return "qwen3:30b"
        if vram>=11:return "qwen3:14b"
        if vram>=6:return "qwen3:8b"
        return "qwen3:8b" if ram>=24 else "qwen3:4b"
    # balanced: keep quality high but avoid CPU-bound 14B/30B selection.
    if vram>=16:return "qwen3:14b"
    if vram>=7:return "qwen3:8b"
    if vram>=4:return "qwen3:4b"
    return "qwen3:8b" if ram>=24 else "qwen3:4b"


def server_models(timeout=3.0):
    req=urllib.request.Request("http://127.0.0.1:11434/api/tags",headers={"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:obj=json.loads(r.read().decode("utf-8","ignore"))
    return [str(m.get("name") or m.get("model") or "") for m in (obj.get("models") or []) if isinstance(m,dict)]


def _same_model(a,b):
    a=str(a or "").casefold();b=str(b or "").casefold()
    if a==b:return True
    if ":" not in a and b.startswith(a+":"):return True
    if ":" not in b and a.startswith(b+":"):return True
    return False


def best_installed(preferred=""):
    try:names=server_models()
    except Exception:return ""
    if preferred and any(_same_model(preferred,x) for x in names):return preferred
    for model in QUALITY_ORDER:
        if any(_same_model(model,x) for x in names):return model
    for x in names:
        if x.casefold().startswith("qwen3:") or x.casefold()=="qwen3":return x
    return ""


def best_installed_for_mode(preferred="", mode="balanced"):
    try:names=server_models()
    except Exception:return ""
    if preferred and any(_same_model(preferred,x) for x in names):return preferred
    mode=str(mode or "balanced").lower()
    order={
        "speed":["qwen3:4b","qwen3:8b","qwen3:14b","qwen3:30b"],
        "balanced":["qwen3:8b","qwen3:4b","qwen3:14b","qwen3:30b"],
        "quality":["qwen3:14b","qwen3:30b","qwen3:8b","qwen3:4b"],
    }.get(mode,["qwen3:8b","qwen3:4b","qwen3:14b","qwen3:30b"])
    for model in order:
        if any(_same_model(model,x) for x in names):return model
    for x in names:
        if x.casefold().startswith("qwen3:") or x.casefold()=="qwen3":return x
    return ""


def resolve_model(cfg=None):
    cfg=cfg or settings();preferred=str(cfg.get("ollama_model") or "").strip()
    mode=str(cfg.get("ollama_generation_profile") or "balanced")
    installed=best_installed_for_mode(preferred,mode)
    return installed or preferred or recommend_model(mode=mode)


def status(cfg=None):
    cfg=cfg or settings();info=hardware_info();recommended=recommend_model(info,str(cfg.get("ollama_generation_profile") or "balanced"))
    try:
        names=server_models();running=True
    except Exception as e:
        return {"ready":False,"running":False,"reason":"Ollama 서버 연결 불가: "+str(e),"recommended":recommended,"hardware":info,"model":""}
    chosen=best_installed_for_mode(str(cfg.get("ollama_model") or ""),str(cfg.get("ollama_generation_profile") or "balanced"))
    return {"ready":bool(chosen),"running":running,"reason":f"Ollama 로컬 AI {'READY' if chosen else '모델 설치 필요'}","recommended":recommended,"hardware":info,"model":chosen,"installed":names}


def write_selected_model(model):
    p=DATA/"settings.json";obj=json.loads(p.read_text(encoding="utf-8"));obj["ollama_model"]=model;obj["ollama_model_policy"]="gpu_aware_speed_balanced_qwen3";p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    log("Ollama 자동 선택 모델: "+model)
