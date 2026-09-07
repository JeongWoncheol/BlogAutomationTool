# -*- coding: utf-8 -*-
from pathlib import Path
import sys,json,os
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules.comfy_discovery import discover_installations,probe_running_server,legacy_base_path,workflow_search_dirs

cfg=json.loads((ROOT/"video"/"video_engine.json").read_text(encoding="utf-8"))
print("=== COMFYUI DEEP DIAGNOSTIC v7.10 ===")
print("[INFO] USERPROFILE:",os.environ.get("USERPROFILE"))
print("[INFO] APPDATA:",os.environ.get("APPDATA"))
print("[INFO] LOCALAPPDATA:",os.environ.get("LOCALAPPDATA"))
print("[INFO] configured root:",cfg.get("comfy_root") or "(empty)")
print("[INFO] legacy base path:",legacy_base_path() or "(none)")
srv=probe_running_server(cfg.get("comfy_url","http://127.0.0.1:8188"))
print("[PASS]" if srv else "[CHECK]","running API server:",srv or "not found")
infos=discover_installations(cfg.get("comfy_root"))
print("[INFO] installation candidates:",len(infos))
for i,x in enumerate(infos,1):
    print(f" {i}. root={x['root']}")
    print(f"    source={x['source']}")
    print(f"    python={x.get('python') or '(not found)'}")
    print(f"    port={x.get('port') or '(unknown)'}")
root=infos[0]["root"] if infos else None
print("[INFO] workflow search dirs:")
for d in workflow_search_dirs(root):print(" -",d)
program_wf=ROOT/"video"/"workflows"
print("[INFO] program workflow folder:",program_wf)
print("[INFO] API JSON files:",len(list(program_wf.glob("*.json"))))
if srv and infos:
    print("[PASS] ComfyUI installation + server both detected.")
elif srv:
    print("[PASS] Server detected. Server-only mode is supported.")
elif infos:
    print("[CHECK] Installation detected but server not running. Launch it in ComfyUI Desktop.")
else:
    print("[FAIL] No server/install detected.")
