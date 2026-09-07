# -*- coding: utf-8 -*-
from pathlib import Path
import os, json, re, subprocess, urllib.request

def _server_ok(url, timeout=0.7):
    try:
        with urllib.request.urlopen(url.rstrip("/")+"/system_stats", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def probe_running_server(preferred="http://127.0.0.1:8188"):
    seen=[]
    urls=[preferred] + [f"http://127.0.0.1:{p}" for p in range(8188,8200)] + [
        "http://127.0.0.1:8000","http://127.0.0.1:8080"
    ]
    for u in urls:
        if u in seen:
            continue
        seen.append(u)
        if _server_ok(u):
            return u
    return None

def _recursive_strings(obj):
    if isinstance(obj,str):
        yield obj
    elif isinstance(obj,dict):
        for v in obj.values():
            yield from _recursive_strings(v)
    elif isinstance(obj,list):
        for v in obj:
            yield from _recursive_strings(v)

def _candidate_root(p):
    try:
        p=Path(os.path.expandvars(os.path.expanduser(str(p)))).resolve()
    except Exception:
        p=Path(str(p))
    for x in [
        p,
        p/"ComfyUI",
        p/"resources"/"ComfyUI",
        p/"resource"/"ComfyUI",
        p/"resources"/"app"/"ComfyUI",
    ]:
        if (x/"main.py").exists():
            return x
    return None

def legacy_base_path():
    home=Path.home()
    appdata=Path(os.environ.get("APPDATA",home/"AppData/Roaming"))
    for p in [
        appdata/"ComfyUI"/"config.json",
        appdata/"Comfy Desktop"/"config.json",
    ]:
        if not p.exists():
            continue
        try:
            j=json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(j,dict):
            for key in ("basePath","base_path"):
                if isinstance(j.get(key),str):
                    return Path(j[key])
        for s in _recursive_strings(j):
            try:
                q=Path(os.path.expandvars(os.path.expanduser(s)))
                if q.exists() and (q/".venv").exists():
                    return q
            except Exception:
                pass
    return None

def _python_for_root(root, legacy_base=None):
    root=Path(root)
    cands=[
        root/".venv"/"Scripts"/"python.exe",
        root.parent/".venv"/"Scripts"/"python.exe",
        root.parent/"python_embeded"/"python.exe",
        root.parent/"python_embedded"/"python.exe",
    ]
    if legacy_base:
        b=Path(legacy_base)
        cands += [
            b/".venv"/"Scripts"/"python.exe",
            b/"python_embeded"/"python.exe",
        ]
    for p in cands:
        if p.exists():
            return p
    return None

def running_process_candidates():
    out=[]
    if os.name!="nt":
        return out
    ps = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -match 'main\\.py' -and $_.CommandLine -match 'ComfyUI' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        r=subprocess.run(
            ["powershell.exe","-NoProfile","-Command",ps],
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=8
        )
        if not r.stdout.strip():
            return out
        data=json.loads(r.stdout)
        if isinstance(data,dict):
            data=[data]
        for item in data:
            cmd=item.get("CommandLine") or ""
            tokens=re.findall(r'"([^"]*main\\.py)"|(\\S*main\\.py)',cmd,re.I)
            for a,b in tokens:
                m=(a or b).strip('"')
                if "ComfyUI" not in m and "comfyui" not in m.lower():
                    continue
                root=_candidate_root(Path(m).parent)
                if root:
                    pm=re.search(r'--port(?:=|\\s+)(\\d+)',cmd)
                    out.append({
                        "root":root,
                        "python":_python_for_root(root,legacy_base_path()),
                        "source":"running_process",
                        "port":int(pm.group(1)) if pm else None,
                        "command_line":cmd,
                    })
    except Exception:
        pass
    return out

def discover_installations(configured_root=None):
    roots=[]
    seen=set()
    base=legacy_base_path()

    def add(path,source):
        if not path:
            return
        root=_candidate_root(path)
        if not root:
            return
        key=str(root).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append({
            "root":root,
            "python":_python_for_root(root,base),
            "source":source,
            "port":None,
        })

    for x in running_process_candidates():
        key=str(x["root"]).lower()
        if key not in seen:
            seen.add(key)
            roots.append(x)

    if configured_root:
        add(configured_root,"video_engine.json")
    if os.environ.get("COMFYUI_ROOT"):
        add(os.environ["COMFYUI_ROOT"],"COMFYUI_ROOT")

    home=Path.home()
    local=Path(os.environ.get("LOCALAPPDATA",home/"AppData/Local"))
    appdata=Path(os.environ.get("APPDATA",home/"AppData/Roaming"))

    for parent in [home/"ComfyUI-Installs",Path("C:/ComfyUI-Installs"),Path("D:/ComfyUI-Installs")]:
        if parent.exists():
            try:
                for p in parent.iterdir():
                    if p.is_dir():
                        add(p,"Comfy Desktop installs")
            except Exception:
                pass

    for rec in [
        appdata/"Comfy Desktop"/"installations.json",
        appdata/"comfyui-desktop-2"/"installations.json",
        appdata/"ComfyUI"/"installations.json",
    ]:
        if not rec.exists():
            continue
        try:
            j=json.loads(rec.read_text(encoding="utf-8"))
            for s in _recursive_strings(j):
                if len(s)<3:
                    continue
                if re.match(r'^[A-Za-z]:[\\\\/]',s) or s.startswith("%") or s.startswith("~"):
                    add(s,f"installations.json:{rec.parent.name}")
        except Exception:
            pass

    for p in [
        local/"Programs"/"ComfyUI",
        local/"Programs"/"@comfyorg"/"comfyui-electron",
        local/"Programs"/"@comfyorgcomfyui-electron",
        local/"Programs"/"comfyui-electron",
    ]:
        add(p,"ComfyUI Desktop resources")

    for p in [
        home/"ComfyUI",
        home/"Downloads"/"ComfyUI",
        home/"Desktop"/"ComfyUI",
        home/"Documents"/"ComfyUI",
        Path("C:/ComfyUI"),
        Path("D:/ComfyUI"),
    ]:
        add(p,"common_path")

    for parent in [home/"Downloads",home/"Desktop",Path("C:/"),Path("D:/")]:
        try:
            if not parent.exists():
                continue
            for p in parent.glob("ComfyUI*_windows_portable"):
                add(p,"portable")
        except Exception:
            pass

    def score(x):
        s=0
        if x["source"]=="running_process":
            s+=100
        if x["source"] in ("video_engine.json","COMFYUI_ROOT"):
            s+=80
        if x.get("python"):
            s+=30
        if "Desktop installs" in x["source"] or "installations.json" in x["source"]:
            s+=20
        return s

    roots.sort(key=score,reverse=True)
    return roots

def workflow_search_dirs(root=None):
    out=[]
    if root:
        r=Path(root)
        out += [r/"user"/"default"/"workflows", r/"user"/"default"/"workflows"/"video"]
    home=Path.home()
    appdata=Path(os.environ.get("APPDATA",home/"AppData/Roaming"))
    base=legacy_base_path()
    if base:
        out += [Path(base)/"user"/"default"/"workflows", Path(base)/"user"/"default"/"workflows"/"video"]
    out += [appdata/"ComfyUI"/"user"/"default"/"workflows", appdata/"Comfy Desktop"/"workflows"]
    ret=[];seen=set()
    for p in out:
        try:
            k=str(p.resolve()).lower()
        except Exception:
            k=str(p).lower()
        if k not in seen and p.exists():
            seen.add(k)
            ret.append(p)
    return ret
