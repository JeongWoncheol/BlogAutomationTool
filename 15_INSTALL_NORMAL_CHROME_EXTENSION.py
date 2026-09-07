# -*- coding: utf-8 -*-
from pathlib import Path
import json, os, subprocess, sys, time, urllib.request

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from chrome_profile import choose_profile, open_chrome_url
from stable_extension import sync_extension, stable_extension_dir

MANIFEST=ROOT/"chrome_extension"/"manifest.json"
BRIDGE=ROOT/"chrome_bridge.py"

def bridge_health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health",timeout=1) as r:
            return json.loads(r.read().decode("utf-8"))
    except:return None

def start_bridge():
    if bridge_health():return
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
    subprocess.Popen([sys.executable,str(BRIDGE)],cwd=str(ROOT),
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     creationflags=flags)
    for _ in range(20):
        time.sleep(.2)
        if bridge_health():return

def main():
    print("=== Normal Chrome Collector Guided Setup v7.58 ===\n")
    if not MANIFEST.exists():
        print("[FAIL] chrome_extension\\manifest.json not found.")
        return 2
    m=json.loads(MANIFEST.read_text(encoding="utf-8"))
    print("[PASS] Extension:",m.get("name"))
    print("[PASS] Program extension version:",m.get("version"))

    profile=choose_profile(interactive=True)
    print("[PASS] Chrome profile:",profile["label"])

    stable=sync_extension()
    print("[PASS] Updated stable extension folder:")
    print(" ",stable)

    try:
        subprocess.Popen(["explorer.exe",str(stable)])
    except:pass

    try:
        open_chrome_url("chrome://extensions/",profile)
    except Exception as e:
        print("[WARN] Could not open chrome://extensions/:",e)

    print()
    print("IMPORTANT - ONE TIME / UPDATE STEP")
    print("1. In chrome://extensions/, find 'NaverBlog Normal Chrome Collector'.")
    print("2. If an OLD extension is loaded from another v7.x folder, REMOVE it.")
    print("3. Turn ON Developer mode.")
    print("4. Click 'Load unpacked'.")
    print("5. Select THIS stable folder:")
    print(" ",stable)
    expected=m.get("version") or "unknown"
    print(f"6. Extension version must show {expected}.")
    print()
    input(f"After the extension card shows version {expected} and is ENABLED, press ENTER... ")

    start_bridge()
    try:
        open_chrome_url("http://127.0.0.1:8765/collector?setup_check=1",profile)
    except:pass

    print("[CHECK] Waiting for extension heartbeat...")
    for i in range(60):
        h=bridge_health() or {}
        meta=h.get("extension_meta") or {}
        if h.get("extension_online"):
            ver=meta.get("extension_version","")
            print("[PASS] Extension heartbeat connected. version=",ver or "unknown")
            if ver and ver!=expected:
                print(f"[CHECK] Connected extension is not v{expected}.")
                print("[ACTION] Remove the old unpacked extension and load the stable folder above.")
                return 6
            print("[READY] Run 16_NORMAL_CHROME_COLLECTOR_TEST.cmd")
            return 0
        if i in (9,29,49):
            print(f"[WAIT] {i+1}s - extension not connected yet.")
        time.sleep(1)

    print("[FAIL] Extension heartbeat not received.")
    print("[ACTION] Open chrome://extensions/ and confirm:")
    print(" - NaverBlog Normal Chrome Collector exists")
    print(f" - Version is {expected}")
    print(" - Toggle is ON")
    print(" - Loaded folder is the stable folder shown above")
    return 5

if __name__=="__main__":
    raise SystemExit(main())
