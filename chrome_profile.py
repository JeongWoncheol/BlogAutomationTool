# -*- coding: utf-8 -*-
from pathlib import Path
import json, os, subprocess, sys

ROOT=(Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent)
CFG=ROOT/"data"/"normal_chrome_profile.json"
CFG.parent.mkdir(parents=True,exist_ok=True)

def user_data_dir():
    local=os.environ.get("LOCALAPPDATA")
    if not local:return None
    p=Path(local)/"Google"/"Chrome"/"User Data"
    return p if p.exists() else None

def chrome_path():
    candidates=[]
    for env,tail in [
        ("PROGRAMFILES",Path("Google/Chrome/Application/chrome.exe")),
        ("PROGRAMFILES(X86)",Path("Google/Chrome/Application/chrome.exe")),
        ("LOCALAPPDATA",Path("Google/Chrome/Application/chrome.exe")),
    ]:
        base=os.environ.get(env)
        if base:candidates.append(Path(base)/tail)
    candidates += [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if p.exists():return p
    return None

def detect_profiles():
    ud=user_data_dir()
    out=[]
    if not ud:return out
    local_state=ud/"Local State"
    cache={}
    if local_state.exists():
        try:
            j=json.loads(local_state.read_text(encoding="utf-8"))
            cache=j.get("profile",{}).get("info_cache",{}) or {}
        except Exception:
            cache={}
    # Local State profile cache gives the display names seen on the chooser screen.
    for directory,info in cache.items():
        p=ud/directory
        if not p.exists():continue
        name=info.get("name") or directory
        gaia=info.get("gaia_name") or ""
        user=info.get("user_name") or ""
        label=name
        extras=[x for x in [gaia,user] if x and x!=name]
        if extras: label += " ("+", ".join(extras)+")"
        out.append({"directory":directory,"name":name,"label":label})
    # Fallback if info_cache is empty.
    if not out:
        for p in [ud/"Default",*sorted(ud.glob("Profile *"))]:
            if p.exists():out.append({"directory":p.name,"name":p.name,"label":p.name})
    return out

def load_saved():
    try:return json.loads(CFG.read_text(encoding="utf-8"))
    except:return {}

def save_profile(directory,name):
    obj={"profile_directory":directory,"profile_name":name}
    CFG.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    return obj

def choose_profile(interactive=True):
    profiles=detect_profiles()
    saved=load_saved()
    if saved.get("profile_directory"):
        for p in profiles:
            if p["directory"]==saved["profile_directory"]:
                print(f"[INFO] Saved Chrome profile: {p['label']} [{p['directory']}]")
                if not interactive:return p
                ans=input("Use this profile? [Y/n]: ").strip().lower()
                if ans in ("","y","yes"):return p
                break
    if not profiles:
        raise RuntimeError("Chrome profiles were not detected.")
    print()
    print("CHROME PROFILE SELECTION")
    print("Choose the profile you normally use for Naver / Coupang / Toss.")
    for i,p in enumerate(profiles,1):
        print(f" {i}. {p['label']}  [{p['directory']}]")
    while True:
        raw=input(f"Select 1-{len(profiles)}: ").strip()
        try:
            n=int(raw)
            if 1<=n<=len(profiles):
                p=profiles[n-1];save_profile(p["directory"],p["name"]);return p
        except:pass
        print("Invalid selection.")

def open_chrome_url(url, profile=None):
    ch=chrome_path()
    if not ch:raise RuntimeError("Chrome executable not found.")
    if profile is None:
        profile=choose_profile(interactive=False)
    args=[str(ch),f"--profile-directory={profile['directory']}",url]
    subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return args

if __name__=="__main__":
    p=choose_profile(interactive=True)
    print(f"[PASS] Saved: {p['label']} [{p['directory']}]")
