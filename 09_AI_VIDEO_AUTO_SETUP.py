# -*- coding: utf-8 -*-
from pathlib import Path
import json, os, sys, shutil, subprocess, time, urllib.request

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules.comfy_discovery import discover_installations, probe_running_server, workflow_search_dirs

CFG=ROOT/"video"/"video_engine.json"
WF_DIR=ROOT/"video"/"workflows"
WF_DIR.mkdir(parents=True,exist_ok=True)

def say(x): print(x,flush=True)
def load_cfg(): return json.loads(CFG.read_text(encoding="utf-8"))
def save_cfg(c): CFG.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding="utf-8")

def server_ok(url):
    try:
        with urllib.request.urlopen(url.rstrip("/")+"/system_stats",timeout=2) as r:
            return r.status==200
    except Exception:
        return False

def start_comfy(info,url):
    if server_ok(url):
        return True
    root=Path(info["root"])
    py=info.get("python")
    if not py or not Path(py).exists():
        say("[CHECK] 설치는 찾았지만 ComfyUI 전용 Python을 찾지 못했습니다.")
        say("[NEXT] ComfyUI Desktop에서 사용할 설치의 Launch를 눌러 서버를 먼저 실행하세요.")
        return False
    main=root/"main.py"
    log=ROOT/"logs"/"comfyui_server.log"
    log.parent.mkdir(exist_ok=True)
    f=open(log,"ab")
    flags=0x00000008 if os.name=="nt" else 0
    subprocess.Popen(
        [str(py),str(main),"--listen","127.0.0.1","--port","8188"],
        cwd=str(root),stdout=f,stderr=subprocess.STDOUT,creationflags=flags
    )
    for _ in range(90):
        if server_ok(url):
            return True
        time.sleep(1)
    return False

def node_title(n):
    return str(n.get("_meta",{}).get("title",""))+" "+str(n.get("class_type",""))

def automap(wf):
    m={}
    for nid,n in wf.items():
        if not isinstance(n,dict):
            continue
        cls=str(n.get("class_type","")).lower()
        title=node_title(n).lower()
        inp=n.get("inputs",{}) if isinstance(n.get("inputs"),dict) else {}
        if not m.get("load_image_node") and "loadimage" in cls:
            m["load_image_node"]=str(nid)
        if "cliptextencode" in cls:
            txt=str(inp.get("text","")).lower()
            neg=any(x in title for x in ["negative","neg"]) or any(x in txt for x in ["bad quality","worst quality","deformed"])
            if neg and not m.get("negative_prompt_node"):
                m["negative_prompt_node"]=str(nid)
            elif not neg and not m.get("positive_prompt_node"):
                m["positive_prompt_node"]=str(nid)
        if not m.get("save_video_node") and any(x in cls for x in ["savevideo","vhs_videocombine","saveanimatedwebp","saveanimatedpng"]):
            m["save_video_node"]=str(nid)
        if not m.get("frame_count_node") and any(k in inp for k in ["length","frames","frame_count","num_frames"]):
            if any(x in cls for x in ["video","wan","latent"]):
                m["frame_count_node"]=str(nid)
        if not m.get("seed_node") and "seed" in inp:
            m["seed_node"]=str(nid)
        if not m.get("steps_node") and "steps" in inp:
            m["steps_node"]=str(nid)
        if not m.get("cfg_node") and any(k in inp for k in ["cfg","guidance"]):
            m["cfg_node"]=str(nid)
    return m

def valid_api(p):
    try:
        j=json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(j,dict):
            return None,None
        if isinstance(j.get("nodes"),list):
            return None,None
        m=automap(j)
        if m.get("positive_prompt_node") and m.get("load_image_node"):
            return j,m
    except Exception:
        pass
    return None,None

def find_api_workflows(root):
    out=list(WF_DIR.glob("*.json"))
    for d in workflow_search_dirs(root):
        try:
            out+=list(d.rglob("*.json"))
        except Exception:
            pass
    seen=set();ret=[]
    for p in out:
        try:
            k=str(p.resolve()).lower()
        except Exception:
            k=str(p).lower()
        if k not in seen:
            seen.add(k);ret.append(p)
    return ret

def main():
    say("=== AI PRODUCT VIDEO AUTO SETUP v7.10 ===")
    c=load_cfg()

    running=probe_running_server(c.get("comfy_url","http://127.0.0.1:8188"))
    if running:
        c["comfy_url"]=running
        say(f"[PASS] 실행 중 ComfyUI API 서버: {running}")
    else:
        say("[INFO] 실행 중인 ComfyUI API 서버는 아직 없습니다.")

    infos=discover_installations(c.get("comfy_root"))
    info=infos[0] if infos else None

    if info:
        root=Path(info["root"])
        c["comfy_root"]=str(root)
        c["comfy_python"]=str(info.get("python") or "")
        c["comfy_detect_source"]=info.get("source","")
        c["server_only_mode"]=False
        say(f"[PASS] ComfyUI 설치 폴더: {root}")
        say(f"[INFO] 탐지 방식: {info.get('source','')}")
        if info.get("python"):
            say(f"[PASS] ComfyUI Python: {info['python']}")
        if info.get("port") and not running:
            c["comfy_url"]=f"http://127.0.0.1:{info['port']}"
    elif running:
        c["comfy_root"]=""
        c["comfy_python"]=""
        c["comfy_detect_source"]="running_server_only"
        c["server_only_mode"]=True
        say("[PASS] 설치 폴더 없이 실행 서버를 사용합니다 (server-only mode).")
        say("[INFO] 제품 이미지는 ComfyUI /upload/image API로 전송합니다.")
    else:
        save_cfg(c)
        say("[NEED] ComfyUI 설치와 실행 서버를 찾지 못했습니다.")
        say("[NEXT] 24_COMFYUI_DEEP_DIAGNOSTIC.cmd를 실행하세요.")
        say("[NEXT] ComfyUI Desktop에서 설치 항목의 Launch를 누른 뒤 다시 09번을 실행해도 됩니다.")
        return 2

    save_cfg(c)

    if not server_ok(c["comfy_url"]):
        if not info or not start_comfy(info,c["comfy_url"]):
            say("[NEED] ComfyUI 설치는 확인했지만 API 서버가 실행되지 않았습니다.")
            say("[NEXT] ComfyUI Desktop에서 Launch를 눌러 UI가 열린 상태로 만든 뒤 다시 실행하세요.")
            return 3
        say("[PASS] ComfyUI API 서버 자동 시작")
    else:
        say("[PASS] ComfyUI API 서버 연결 정상")

    candidates=find_api_workflows(Path(c["comfy_root"]) if c.get("comfy_root") else None)
    best=None
    for p in candidates:
        j,m=valid_api(p)
        if not j:
            continue
        text=json.dumps(j).lower();name=p.name.lower();score=0
        if "wan" in text or "wan" in name: score+=4
        if "2.2" in text or "wan22" in text or "wan2.2" in text: score+=3
        if "loadimage" in text: score+=2
        if m.get("save_video_node"): score+=2
        if best is None or score>best[0]:
            best=(score,p,j,m)

    if not best:
        c["enabled"]=False
        save_cfg(c)
        say("[NEED] ComfyUI 연결은 정상입니다. Image-to-Video API workflow JSON이 필요합니다.")
        say("[STEP 1] ComfyUI Settings > Comfy > Dev Mode에서 API save 옵션을 켜세요.")
        say("[STEP 2] 실제 동작하는 Wan/Image-to-Video workflow를 여세요.")
        say("[STEP 3] Save (API Format)으로 JSON을 저장하세요.")
        say(f"[STEP 4] JSON을 여기에 넣으세요: {WF_DIR}")
        say("[STEP 5] 09_AI_VIDEO_AUTO_SETUP.cmd를 다시 실행하세요.")
        return 4

    _,p,j,m=best
    dst=WF_DIR/"auto_i2v_api.json"
    if p.resolve()!=dst.resolve():
        shutil.copy2(p,dst)
    c["workflow_api_json"]="video/workflows/auto_i2v_api.json"
    c.setdefault("node_map",{}).update(m)
    c["engine"]="ComfyUI-I2V"
    c["enabled"]=True
    save_cfg(c)

    say(f"[PASS] API workflow: {p}")
    say("[PASS] node_map 자동 설정")
    for k,v in m.items():
        say(f"       {k} = {v}")
    say("[READY] AI 제품영상 생성 준비 완료")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
