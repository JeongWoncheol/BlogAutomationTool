# -*- coding: utf-8 -*-
from pathlib import Path
import json,time,uuid,urllib.request,urllib.error,subprocess,sys,os
from .common import ROOT,log,settings,ProgressThrottle

BRIDGE_SCRIPT=ROOT/"chrome_bridge.py"
sys.path.insert(0,str(ROOT))
from chrome_profile import choose_profile, open_chrome_url

def _base():
    return settings().get("chrome_bridge_url","http://127.0.0.1:8765").rstrip("/")

def expected_extension_version():
    try:
        return str(json.loads((ROOT/"chrome_extension"/"manifest.json").read_text(encoding="utf-8")).get("version") or "")
    except Exception:return ""

def _json(method,path,obj=None,timeout=5,retries=3):
    url=_base()+path
    data=None if obj is None else json.dumps(obj,ensure_ascii=False).encode("utf-8")
    last=None
    for attempt in range(max(1,int(retries))):
        req=urllib.request.Request(url,data=data,method=method)
        if data is not None:req.add_header("Content-Type","application/json")
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last=e
            if 400<=int(e.code)<500 and int(e.code) not in (408,429):raise
        except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as e:
            last=e
        if attempt+1<max(1,int(retries)):
            time.sleep(min(3.0,0.25*(2**attempt)))
    raise last or RuntimeError("Chrome 로컬 브리지 통신 실패")

def bridge_health():
    try:return _json("GET","/health",timeout=1.5,retries=1)
    except:return None

def ensure_bridge():
    h=bridge_health()
    if h:return h
    flags=0
    if os.name=="nt":
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    if getattr(sys,"frozen",False):
        cmd=[sys.executable,"--chrome-bridge"]
    else:
        cmd=[sys.executable,str(BRIDGE_SCRIPT)]
    subprocess.Popen(cmd,cwd=str(ROOT),
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
    for _ in range(30):
        time.sleep(.2);h=bridge_health()
        if h:return h
    raise RuntimeError("Chrome 로컬 수집 Bridge를 시작하지 못했습니다.")

def open_collector(run_id):
    url=f"{_base()}/collector?run_id={run_id}&autostart=1"
    try:
        profile=choose_profile(interactive=False)
        open_chrome_url(url,profile)
    except Exception as e:
        raise RuntimeError("선택된 일반 Chrome 프로필을 열지 못했습니다. 15_INSTALL_NORMAL_CHROME_EXTENSION.cmd를 먼저 실행하세요. "+str(e))

def collect(tasks,progress=None,timeout_sec=1200):
    ensure_bridge()
    rid="chrome-"+uuid.uuid4().hex[:12]
    _json("POST","/api/start",{"run_id":rid,"tasks":tasks},timeout=5,retries=4)
    open_collector(rid)
    prog=ProgressThrottle(progress,min_interval=0)
    start=time.time();last_done=-1;extension_deadline=time.time()+15;version_checked=False
    while time.time()-start<timeout_sec:
        st=_json("GET",f"/api/status?run_id={rid}",timeout=4,retries=4)
        if st.get("extension_online"):
            extension_deadline=time.time()+15
            if not version_checked:
                h=bridge_health() or {};meta=h.get("extension_meta") or {};actual=str(meta.get("extension_version") or "");expected=expected_extension_version()
                if actual and expected and actual!=expected:
                    raise RuntimeError(f"Chrome 수집 확장프로그램 버전이 오래되었습니다. 현재 연결 v{actual}, 프로그램 필요 v{expected}. 15_INSTALL_NORMAL_CHROME_EXTENSION.cmd 실행 후 chrome://extensions 에서 확장프로그램을 다시 로드하세요.")
                if actual:version_checked=True
        elif time.time()>extension_deadline and st.get("done",0)==0:
            raise RuntimeError(
                "일반 Chrome 수집 확장프로그램이 연결되지 않았습니다. "
                "15_INSTALL_NORMAL_CHROME_EXTENSION.cmd로 확장프로그램을 먼저 설치하세요."
            )
        if st.get("paused"):
            raise RuntimeError(
                st.get("pause_reason","Chrome 수집 일시정지")+
                " — 열린 일반 Chrome에서 로그인한 뒤 검색 버튼을 다시 실행하세요."
            )
        done=st.get("done",0);total=st.get("total",len(tasks))
        if done!=last_done:
            active=next((x for x in st.get("tasks",[]) if x.get("state")=="active"),None)
            msg=f"일반 Chrome 수집 {done}/{total}"
            if active:
                msg+=f" · {active['site']} · {active['query']}"
                if active.get('last_stage'):msg+=f" · {active['last_stage']}"
            prog(done,total,msg,force=True);last_done=done
        if st.get("cancelled"):raise RuntimeError("Chrome 수집 작업이 취소되었습니다.")
        if done>=total:
            prog(total,total,"일반 Chrome 수집 완료",force=True)
            return st.get("results",[])
        time.sleep(.5)
    try:_json("POST","/api/cancel",{"run_id":rid})
    except:pass
    raise RuntimeError("일반 Chrome 수집 시간이 초과되었습니다.")

def health():
    h=bridge_health()
    if not h:return {"ready":True,"name":"일반 Chrome 수집","message":"Bridge는 필요 시 자동 시작 / 확장프로그램 설치 필요"}
    return {"ready":True,"name":"일반 Chrome 수집",
            "message":"Bridge 정상 / 확장프로그램 "+("연결됨" if h.get("extension_online") else "대기")}
