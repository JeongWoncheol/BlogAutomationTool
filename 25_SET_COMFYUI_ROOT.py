# -*- coding: utf-8 -*-
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules.comfy_discovery import discover_installations
cfgp=ROOT/"video"/"video_engine.json"
cfg=json.loads(cfgp.read_text(encoding="utf-8"))
print("=== SET COMFYUI ROOT v7.10 ===")
print("Enter a folder containing main.py, or its parent install folder.")
raw=input("ComfyUI path: ").strip().strip('"')
if not raw:raise SystemExit(1)
infos=discover_installations(raw)
chosen=None
for x in infos:
    try:
        rr=str(Path(raw).resolve()).lower()
        xr=str(Path(x["root"]).resolve()).lower()
        if xr.startswith(rr) or rr.startswith(xr):
            chosen=x;break
    except Exception:
        pass
if not chosen:
    print("[FAIL] main.py could not be found under that path.")
    raise SystemExit(2)
cfg["comfy_root"]=str(chosen["root"])
cfg["comfy_python"]=str(chosen.get("python") or "")
cfg["comfy_detect_source"]="manual"
cfgp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
print("[PASS] comfy_root =",cfg["comfy_root"])
print("[INFO] comfy_python =",cfg["comfy_python"] or "(not found)")
print("Run 09_AI_VIDEO_AUTO_SETUP.cmd again.")
