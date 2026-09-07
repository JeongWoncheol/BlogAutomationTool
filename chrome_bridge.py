# -*- coding: utf-8 -*-
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json, threading, time, base64, io, uuid, traceback, sys
from PIL import Image, ImageChops
from modules.toss_visual_ocr import windows_ocr, parse_visual_products, crop_evidence
from modules.common import settings

ROOT=(Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent)

def adaptive_detail_crop(im,role=""):
    """Trim uniform outer margins from detail captures without over-cropping."""
    if not str(role or "").startswith("detail_") or im.width<240 or im.height<240:
        return im,False
    rgb=im.convert("RGB")
    corners=[rgb.getpixel((0,0)),rgb.getpixel((rgb.width-1,0)),
             rgb.getpixel((0,rgb.height-1)),rgb.getpixel((rgb.width-1,rgb.height-1))]
    bg=tuple(sorted(x[i] for x in corners)[len(corners)//2] for i in range(3))
    diff=ImageChops.difference(rgb,Image.new("RGB",rgb.size,bg)).convert("L")
    mask=diff.point(lambda value:255 if value>14 else 0)
    box=mask.getbbox()
    if not box:return im,False
    pad=max(6,min(24,int(min(im.size)*0.018)))
    left=max(0,box[0]-pad);top=max(0,box[1]-pad)
    right=min(im.width,box[2]+pad);bottom=min(im.height,box[3]+pad)
    if right-left<im.width*0.62 or bottom-top<im.height*0.62:return im,False
    if left<4 and top<4 and right>im.width-4 and bottom>im.height-4:return im,False
    return im.crop((left,top,right,bottom)),True
HOST="127.0.0.1"; PORT=8765
LOCK=threading.RLock()
RUNS={}
LAST_HEARTBEAT=0.0
LAST_EXTENSION_META={}
NAVER_GUARD=ROOT/"data"/"naver_access_guard.json"
COUPANG_GUARD=ROOT/"data"/"coupang_circuit.json"
def _load_naver_guard():
    try:
        obj=json.loads(NAVER_GUARD.read_text(encoding="utf-8"));return float(obj.get("blocked_until") or 0)
    except Exception:return 0.0
NAVER_BLOCKED_UNTIL=_load_naver_guard()
def _load_coupang_guard():
    try:
        obj=json.loads(COUPANG_GUARD.read_text(encoding="utf-8"));return float(obj.get("blocked_until") or 0)
    except Exception:return 0.0
COUPANG_BLOCKED_UNTIL=_load_coupang_guard()
LOG=ROOT/"logs"/"chrome_bridge.log"
LOG.parent.mkdir(exist_ok=True)

def log(msg):
    line=f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line,flush=True)
    with LOG.open("a",encoding="utf-8") as f:f.write(line+"\n")

def send_json(h,obj,status=200):
    raw=json.dumps(obj,ensure_ascii=False).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type","application/json; charset=utf-8")
    h.send_header("Content-Length",str(len(raw)))
    h.send_header("Access-Control-Allow-Origin","*")
    h.send_header("Access-Control-Allow-Headers","Content-Type")
    h.end_headers();h.wfile.write(raw)

def read_json(h):
    n=int(h.headers.get("Content-Length","0") or 0)
    raw=h.rfile.read(n) if n else b"{}"
    return json.loads(raw.decode("utf-8"))

def run_status(run):
    tasks=run["tasks"]
    return {
      "run_id":run["run_id"],
      "total":len(tasks),
      "done":sum(1 for x in tasks if x["state"]=="done"),
      "pending":sum(1 for x in tasks if x["state"]=="pending"),
      "active":sum(1 for x in tasks if x["state"]=="active"),
      "paused":run.get("paused",False),
      "pause_reason":run.get("pause_reason",""),
      "cancelled":run.get("cancelled",False),
      "extension_online":time.time()-LAST_HEARTBEAT<12,
      "last_heartbeat_age":round(time.time()-LAST_HEARTBEAT,1) if LAST_HEARTBEAT else None,
    }

def task_stale_timeout(task):
    """Task lease must outlive lazy-load scrolling and rendered crop upload."""
    try:
        requested=float(task.get("task_timeout_sec") or 0)
        if requested>0:return max(90.0,requested+30.0)
    except Exception:pass
    if task.get("mode")=="detail":return 330.0
    if task.get("mode")=="fixed_category_collect" and task.get("site")=="토스쇼핑":return 210.0
    return 120.0

def save_capture(task,result,screenshot):
    if not screenshot or not screenshot.startswith("data:image/"):return result
    try:
        b64=screenshot.split(",",1)[1]
        im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        evdir=Path(task.get("evdir") or ROOT/"evidence"/"_chrome_collector")
        if not evdir.is_absolute():evdir=ROOT/evdir
        evdir.mkdir(parents=True,exist_ok=True)
        safe=re_sub(r"[^0-9A-Za-z가-힣_-]","_",task.get("site","site"))
        stamp=time.strftime("%Y%m%d_%H%M%S")
        full=evdir/f"{safe}_Chrome화면_{stamp}.jpg"
        im.save(full,"JPEG",quality=94)
        result["full_screenshot"]=str(full)

        selected=result.get("selected") or {}
        dpr=float(result.get("devicePixelRatio") or 1)
        vw=float(result.get("viewportWidth") or im.width/dpr)
        vh=float(result.get("viewportHeight") or im.height/dpr)
        # captureVisibleTab maps viewport CSS pixels to screenshot pixels.
        sx=im.width/max(1,vw); sy=im.height/max(1,vh)
        def crop_rect(rect,name):
            if not rect:return None
            x=max(0,int(rect.get("x",0)*sx));y=max(0,int(rect.get("y",0)*sy))
            w=max(1,int(rect.get("width",0)*sx));h=max(1,int(rect.get("height",0)*sy))
            box=(x,y,min(im.width,x+w),min(im.height,y+h))
            if box[2]<=box[0] or box[3]<=box[1]:return None
            c=im.crop(box)
            p=evdir/f"{safe}_{name}_{stamp}.jpg";c.save(p,"JPEG",quality=96)
            return str(p)
        cp=crop_rect(selected.get("rect"),"동일상품카드")
        ip=crop_rect(selected.get("imageRect"),"제품사진")
        if cp:result["evidence"]=cp
        if ip:result["image_path"]=ip
    except Exception as e:
        result["capture_error"]=str(e)
    return result

def re_sub(pattern,repl,text):
    import re
    return re.sub(pattern,repl,text or "")

class H(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        global LAST_HEARTBEAT
        u=urlparse(self.path);q=parse_qs(u.query)
        if u.path=="/health":
            return send_json(self,{
                "ok":True,
                "extension_online":time.time()-LAST_HEARTBEAT<20,
                "last_heartbeat_age":round(time.time()-LAST_HEARTBEAT,1) if LAST_HEARTBEAT else None,
                "extension_meta":LAST_EXTENSION_META,
                "naver_access_cooldown_remaining":max(0,int(NAVER_BLOCKED_UNTIL-time.time())),
                "coupang_access_cooldown_remaining":max(0,int(COUPANG_BLOCKED_UNTIL-time.time()))
            })
        if u.path=="/collector":
            html="""<!doctype html><html><head><meta charset='utf-8'><title>Normal Chrome Collector</title>
            <style>body{font-family:Arial,'Malgun Gothic';max-width:760px;margin:60px auto;padding:24px}
            .box{border:1px solid #ddd;border-radius:14px;padding:24px} .ok{color:#087f23}</style></head>
            <body><div class='box'><h2>블로그 자동화 · 일반 Chrome 수집 모드</h2>
            <p>이 탭은 Chrome 확장프로그램을 깨우기 위한 로컬 페이지입니다.</p>
            <p class='ok'>확장프로그램이 설치되어 있으면 네이버 전체 → 쿠팡 전체 → 토스 전체 순서로 한 개의 작업 탭을 재사용합니다.</p>
            <p>토스 최초 사용 시 로그인 화면이 나오면 직접 로그인한 뒤 프로그램에서 검색을 다시 실행하세요.</p>
            <p>이 페이지는 안전하게 닫아도 됩니다.</p></div></body></html>"""
            raw=html.encode("utf-8");self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if u.path=="/api/active_run":
            with LOCK:
                active_runs=[]
                for rid,run in RUNS.items():
                    st=run_status(run)
                    if not st["cancelled"] and st["done"] < st["total"]:
                        active_runs.append((run.get("created_at",0),rid,st))
                if not active_runs:
                    return send_json(self,{"active":False})
                active_runs.sort(reverse=True)
                _,rid,st=active_runs[0]
                return send_json(self,{"active":True,"run_id":rid,"status":st})
        if u.path=="/api/next":
            rid=(q.get("run_id") or [""])[0]
            with LOCK:
                run=RUNS.get(rid)
                if not run:return send_json(self,{"error":"run_not_found"},404)
                if run.get("cancelled"):return send_json(self,{"done":True,"cancelled":True})
                if run.get("paused"):return send_json(self,{"paused":True,"reason":run.get("pause_reason","")})
                active=next((x for x in run["tasks"] if x["state"]=="active"),None)
                if active:
                    # Reset only when the task lease has received no progress
                    # heartbeat for the full mode-specific timeout.
                    lease_at=max(float(active.get("started_at") or 0),float(active.get("last_activity") or 0))
                    if time.time()-lease_at > task_stale_timeout(active):
                        log(f"STALE TASK RESET {active['id']}")
                        active["state"]="pending"
                        active["error"]="stale task automatically reset"
                    else:
                        return send_json(self,{"task":active})
                task=next((x for x in run["tasks"] if x["state"]=="pending"),None)
                if not task:return send_json(self,{"done":True})
                task["state"]="active";task["started_at"]=time.time();task["last_activity"]=task["started_at"]
                return send_json(self,{"task":task})
        if u.path=="/api/status":
            rid=(q.get("run_id") or [""])[0]
            with LOCK:
                run=RUNS.get(rid)
                if not run:return send_json(self,{"error":"run_not_found"},404)
                st=run_status(run)
                st["results"]=[x.get("result") for x in run["tasks"] if x.get("result") is not None]
                st["tasks"]=[{"id":x["id"],"site":x["site"],"query":x["query"],"state":x["state"],
                              "error":x.get("error",""),"last_stage":x.get("last_stage","")} for x in run["tasks"]]
                return send_json(self,st)
        return send_json(self,{"error":"not_found"},404)

    def do_POST(self):
        global LAST_HEARTBEAT, LAST_EXTENSION_META, NAVER_BLOCKED_UNTIL, COUPANG_BLOCKED_UNTIL
        u=urlparse(self.path)
        try:data=read_json(self)
        except Exception as e:return send_json(self,{"error":str(e)},400)
        if u.path=="/api/heartbeat":
            LAST_HEARTBEAT=time.time()
            if isinstance(data,dict):
                LAST_EXTENSION_META={
                    "extension_version":data.get("extension_version",""),
                    "source":data.get("source",""),
                    "ts":data.get("ts")
                }
                rid=str(data.get("run_id") or "");tid=str(data.get("task_id") or "")
                if rid and tid:
                    with LOCK:
                        run=RUNS.get(rid)
                        task=next((x for x in (run or {}).get("tasks",[]) if x.get("id")==tid and x.get("state")=="active"),None)
                        if task:
                            task["last_activity"]=time.time();task["last_stage"]=str(data.get("stage") or "")
            return send_json(self,{"ok":True})
        if u.path=="/api/start":
            rid=data.get("run_id") or uuid.uuid4().hex
            tasks=[]
            naver_cooling=time.time()<NAVER_BLOCKED_UNTIL
            coupang_cooling=time.time()<COUPANG_BLOCKED_UNTIL
            for i,x in enumerate(data.get("tasks") or []):
                t=dict(x);t.setdefault("id",f"{rid}-{i+1:04d}");t["state"]="pending";t["result"]=None;t["error"]=""
                if naver_cooling and t.get("site")=="네이버쇼핑":
                    t["state"]="done";t["finished_at"]=time.time();t["result"]={"status":"skipped_blocked","error":"네이버 접근 제한 쿨다운 중 — 추가 요청을 보내지 않았습니다.",
                        "_task_id":t.get("id"),"_site":"네이버쇼핑","_query":t.get("query")}
                elif coupang_cooling and t.get("site")=="쿠팡":
                    t["state"]="done";t["finished_at"]=time.time();t["result"]={"status":"skipped_blocked","reason_code":"COUPANG_ACCESS_DENIED_COOLDOWN",
                        "error":"쿠팡 접근 제한 쿨다운 중 — 추가 쿠팡 요청을 보내지 않았습니다.",
                        "_task_id":t.get("id"),"_site":"쿠팡","_query":t.get("query")}
                tasks.append(t)
            with LOCK:
                RUNS[rid]={"run_id":rid,"tasks":tasks,"paused":False,"pause_reason":"","cancelled":False,
                           "created_at":time.time()}
            log(f"RUN START {rid} tasks={len(tasks)}")
            return send_json(self,{"ok":True,"run_id":rid,"total":len(tasks)})
        if u.path=="/api/toss_visual_state_diff":
            before=data.get("before") or ""; after=data.get("after") or ""; region=data.get("region") or {}; viewport=data.get("viewport") or {}
            if not (isinstance(before,str) and before.startswith("data:image/") and isinstance(after,str) and after.startswith("data:image/")):
                return send_json(self,{"ok":False,"error":"screenshots_missing"},400)
            try:
                from PIL import ImageChops,ImageStat
                def dec(x): return Image.open(io.BytesIO(base64.b64decode(x.split(",",1)[1]))).convert("RGB")
                a,b=dec(before),dec(after)
                vw=float(viewport.get("width") or a.width); vh=float(viewport.get("height") or a.height)
                sx=a.width/max(1.0,vw); sy=a.height/max(1.0,vh)
                x=float(region.get("x") or 0); y=float(region.get("y") or 0); w=float(region.get("width") or 1); h=float(region.get("height") or 1)
                pad=12.0
                box=(max(0,int((x-pad)*sx)),max(0,int((y-pad)*sy)),min(a.width,int((x+w+pad)*sx)),min(a.height,int((y+h+pad)*sy)))
                ca=a.crop(box); cb=b.crop(box)
                if ca.size!=cb.size: cb=cb.resize(ca.size)
                diff=ImageChops.difference(ca,cb).convert("L")
                stat=ImageStat.Stat(diff); mean=float(stat.mean[0] if stat.mean else 0.0)
                hist=diff.histogram(); total=max(1,sum(hist)); changed=sum(hist[8:])/total
                return send_json(self,{"ok":True,"mean_abs":mean,"changed_ratio":changed,"changed":bool(mean>=0.65 or changed>=0.0025),"box":box,"size":ca.size})
            except Exception as e:
                return send_json(self,{"ok":False,"error":str(e)},500)
        if u.path=="/api/detail_capture_viewport":
            shot=data.get("screenshot") or ""
            rect=data.get("rect") or {}
            viewport=data.get("viewport") or {}
            if not (isinstance(shot,str) and shot.startswith("data:image/")):
                return send_json(self,{"ok":False,"error":"screenshot_missing"},400)
            try:
                tid_raw=str(data.get("task_id") or "")
                if tid_raw:
                    with LOCK:
                        for run in RUNS.values():
                            task=next((x for x in run.get("tasks",[]) if x.get("id")==tid_raw and x.get("state")=="active"),None)
                            if task:task["last_activity"]=time.time();task["last_stage"]="detail_capture_viewport_upload"
                b64=shot.split(",",1)[1]
                im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
                vw=float(viewport.get("width") or im.width);vh=float(viewport.get("height") or im.height)
                sx=im.width/max(1.0,vw);sy=im.height/max(1.0,vh)
                x=max(0.0,float(rect.get("x") or 0));y=max(0.0,float(rect.get("y") or 0))
                w=max(1.0,float(rect.get("width") or 1));h=max(1.0,float(rect.get("height") or 1))
                # Rect is viewport CSS pixels. Clamp hard so browser chrome / DPR
                # differences can never produce an empty crop.
                left=max(0,min(im.width-1,int(round(x*sx))))
                top=max(0,min(im.height-1,int(round(y*sy))))
                right=max(left+1,min(im.width,int(round((x+w)*sx))))
                bottom=max(top+1,min(im.height,int(round((y+h)*sy))))
                crop=im.crop((left,top,right,bottom))
                if crop.width<120 or crop.height<120:
                    return send_json(self,{"ok":False,"error":f"crop_too_small:{crop.width}x{crop.height}","box":[left,top,right,bottom]},400)
                meta=data.get("meta") if isinstance(data.get("meta"),dict) else {}
                crop,adaptive_cropped=adaptive_detail_crop(crop,meta.get("role") or "")
                max_side=2200
                if max(crop.size)>max_side:
                    scale=max_side/float(max(crop.size))
                    crop=crop.resize((max(1,int(crop.width*scale)),max(1,int(crop.height*scale))),Image.Resampling.LANCZOS)
                tid=re_sub(r"[^0-9A-Za-z가-힣_-]","_",str(data.get("task_id") or "detail"))
                label=re_sub(r"[^0-9A-Za-z가-힣_-]","_",str(data.get("label") or "제품이미지"))
                outdir=ROOT/"evidence"/"detail_screen_capture"/tid
                outdir.mkdir(parents=True,exist_ok=True)
                idx=max(1,int(data.get("index") or 1))
                path=outdir/f"{idx:02d}_{label}.jpg"
                crop.save(path,"JPEG",quality=95,optimize=True)
                log(f"detail viewport crop saved: {path} {crop.width}x{crop.height}")
                return send_json(self,{"ok":True,"path":str(path),"width":crop.width,"height":crop.height,"label":label,"meta":meta,"fallback":"captureVisibleTab","adaptive_cropped":adaptive_cropped})
            except Exception as e:
                return send_json(self,{"ok":False,"error":str(e)},500)
        if u.path=="/api/detail_capture":
            shot=data.get("screenshot") or ""
            if not (isinstance(shot,str) and shot.startswith("data:image/")):
                return send_json(self,{"ok":False,"error":"screenshot_missing"},400)
            try:
                tid_raw=str(data.get("task_id") or "")
                if tid_raw:
                    with LOCK:
                        for run in RUNS.values():
                            task=next((x for x in run.get("tasks",[]) if x.get("id")==tid_raw and x.get("state")=="active"),None)
                            if task:task["last_activity"]=time.time();task["last_stage"]="detail_capture_upload"
                b64=shot.split(",",1)[1]
                im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
                if im.width<120 or im.height<120:
                    return send_json(self,{"ok":False,"error":f"crop_too_small:{im.width}x{im.height}"},400)
                meta=data.get("meta") if isinstance(data.get("meta"),dict) else {}
                im,adaptive_cropped=adaptive_detail_crop(im,meta.get("role") or "")
                # Avoid pathological full-page/long-detail captures while retaining a
                # high quality product image. The source screenshot is already clipped
                # by CDP to the image element, so this is only a safety resize.
                max_side=2200
                if max(im.size)>max_side:
                    scale=max_side/float(max(im.size))
                    im=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.LANCZOS)
                tid=re_sub(r"[^0-9A-Za-z가-힣_-]","_",str(data.get("task_id") or "detail"))
                label=re_sub(r"[^0-9A-Za-z가-힣_-]","_",str(data.get("label") or "제품이미지"))
                outdir=ROOT/"evidence"/"detail_screen_capture"/tid
                outdir.mkdir(parents=True,exist_ok=True)
                idx=max(1,int(data.get("index") or 1))
                path=outdir/f"{idx:02d}_{label}.jpg"
                im.save(path,"JPEG",quality=95,optimize=True)
                log(f"detail CDP crop saved: {path} {im.width}x{im.height}")
                return send_json(self,{"ok":True,"path":str(path),"width":im.width,"height":im.height,"label":label,"meta":meta,"adaptive_cropped":adaptive_cropped})
            except Exception as e:
                return send_json(self,{"ok":False,"error":str(e),"trace":traceback.format_exc()[-2000:]},500)
        if u.path=="/api/toss_visual_ocr":
            shot=data.get("screenshot") or ""
            if not (isinstance(shot,str) and shot.startswith("data:image/")):
                return send_json(self,{"ok":False,"error":"screenshot_missing","cards":[]},400)
            try:
                b64=shot.split(",",1)[1]
                im=Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
                original_size=im.size
                # Windows.Media.Ocr has an implementation-dependent maximum
                # image dimension.  Keep high-DPI/4K Chrome captures safely
                # below that range while preserving enough text resolution.
                if max(im.size)>2200:
                    scale=2200.0/max(im.size)
                    im=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.LANCZOS)
                rid=re_sub(r"[^0-9A-Za-z_-]","_",str(data.get("run_id") or "visual"))
                tid=re_sub(r"[^0-9A-Za-z가-힣_-]","_",str(data.get("task_id") or "task"))
                cat=re_sub(r"[^0-9A-Za-z가-힣_-]","_",str(data.get("category") or "category"))
                rnd=max(0,int(data.get("round") or 0))
                outdir=ROOT/"evidence"/"toss_visual_ocr"/rid/tid/cat
                outdir.mkdir(parents=True,exist_ok=True)
                imgpath=outdir/f"screen_{rnd:02d}.png"
                im.save(imgpath,"PNG")
                ocr=windows_ocr(imgpath,language=str(data.get("language") or "ko-KR"),timeout=40)
                cards,diag=parse_visual_products(ocr,im.size,limit=max(30,int(data.get("limit") or 30)*2))
                cards=crop_evidence(imgpath,cards,outdir/f"cards_{rnd:02d}",prefix=f"r{rnd:02d}")
                diag.update({"screenshot":str(imgpath),"category":str(data.get("category") or ""),"round":rnd,"image_width":im.width,"image_height":im.height,"original_width":original_size[0],"original_height":original_size[1]})
                (outdir/f"ocr_{rnd:02d}.json").write_text(json.dumps({"diag":diag,"cards":cards,"ocr":ocr},ensure_ascii=False,indent=2),encoding="utf-8")
                return send_json(self,{"ok":bool(ocr.get("ok")),"cards":cards,"diag":diag,"error":ocr.get("error","")})
            except Exception as e:
                return send_json(self,{"ok":False,"error":str(e),"cards":[],"trace":traceback.format_exc()[-4000:]},500)
        if u.path=="/api/result":
            rid=data.get("run_id");tid=data.get("task_id")
            with LOCK:
                run=RUNS.get(rid)
                if not run:return send_json(self,{"error":"run_not_found"},404)
                task=next((x for x in run["tasks"] if x["id"]==tid),None)
                if not task:return send_json(self,{"error":"task_not_found"},404)
                result=data.get("result") or {}
                if result.get("status")=="login_required":
                    # keep task pending, pause queue for normal user login
                    task["state"]="pending";run["paused"]=True
                    run["pause_reason"]="토스 쉐어링크 로그인 필요"
                    log(f"RUN PAUSE {rid}: Toss login required")
                    return send_json(self,{"ok":True,"paused":True})
                result=save_capture(task,result,data.get("screenshot"))
                result["_task_id"]=tid;result["_site"]=task.get("site");result["_query"]=task.get("query")
                task["result"]=result;task["state"]="done";task["finished_at"]=time.time()
                # Naver anti-abuse/access restriction: do not keep hammering the
                # same search site with the rest of a batch. Mark remaining Naver
                # tasks as safely skipped so other marketplaces can continue.
                if task.get("site")=="네이버쇼핑" and result.get("status")=="blocked":
                    try:cooldown=max(900,int(settings().get("naver_access_cooldown_sec",3600)))
                    except Exception:cooldown=3600
                    NAVER_BLOCKED_UNTIL=max(NAVER_BLOCKED_UNTIL,time.time()+cooldown)
                    try:
                        NAVER_GUARD.parent.mkdir(parents=True,exist_ok=True)
                        NAVER_GUARD.write_text(json.dumps({"blocked_until":NAVER_BLOCKED_UNTIL,"detected_at":time.time(),"reason":"naver_access_restriction"},ensure_ascii=False,indent=2),encoding="utf-8")
                    except Exception:pass
                    skipped=0
                    for pending in run["tasks"]:
                        if pending.get("site")=="네이버쇼핑" and pending.get("state")=="pending":
                            rr={"status":"skipped_blocked","error":"네이버 접근 제한 감지 — 같은 실행의 추가 네이버 요청을 자동 중단했습니다.",
                                "_task_id":pending.get("id"),"_site":"네이버쇼핑","_query":pending.get("query")}
                            pending["result"]=rr;pending["state"]="done";pending["finished_at"]=time.time();skipped+=1
                    run["naver_blocked"]=True;run["naver_blocked_at"]=time.time()
                    log(f"NAVER ACCESS RESTRICTION {rid}: skipped {skipped} pending Naver tasks; cooldown={cooldown}s")
                # Coupang Akamai blocks are IP/session-wide, not one-category
                # failures. Stop every remaining Coupang browser task at the
                # first denial, preserve completed/partial rows, and let Naver
                # and Toss tasks continue in the same run.
                if task.get("site")=="쿠팡" and result.get("status")=="blocked":
                    try:cooldown=max(1800,int(settings().get("coupang_access_cooldown_sec",3600)))
                    except Exception:cooldown=3600
                    COUPANG_BLOCKED_UNTIL=max(COUPANG_BLOCKED_UNTIL,time.time()+cooldown)
                    skipped=0;resume=[]
                    for pending in run["tasks"]:
                        if pending.get("site")=="쿠팡" and pending.get("state")=="pending":
                            label=pending.get("blog_category") or pending.get("query") or pending.get("id")
                            rr={"status":"skipped_blocked","reason_code":"COUPANG_ACCESS_DENIED_BATCH_STOP",
                                "error":"첫 Access Denied 감지 — 같은 실행의 남은 쿠팡 요청을 자동 중단했습니다.",
                                "resume_required":True,"_task_id":pending.get("id"),"_site":"쿠팡","_query":pending.get("query")}
                            pending["result"]=rr;pending["state"]="done";pending["finished_at"]=time.time();skipped+=1;resume.append(label)
                    result["reason_code"]="COUPANG_ACCESS_DENIED"
                    result["batch_stop_applied"]=True;result["skipped_coupang_tasks"]=skipped;result["resume_required_categories"]=resume
                    run["coupang_blocked"]=True;run["coupang_blocked_at"]=time.time();run["coupang_resume_required"]=resume
                    try:
                        COUPANG_GUARD.parent.mkdir(parents=True,exist_ok=True)
                        COUPANG_GUARD.write_text(json.dumps({"blocked_until":COUPANG_BLOCKED_UNTIL,"last_reason":"COUPANG_ACCESS_DENIED",
                            "last_blocked_at":time.time(),"run_id":rid,"skipped_tasks":skipped,"resume_required_categories":resume},ensure_ascii=False,indent=2),encoding="utf-8")
                    except Exception:pass
                    log(f"COUPANG ACCESS DENIED {rid}: skipped {skipped} pending Coupang tasks; other sites continue; cooldown={cooldown}s")
                log(f"TASK DONE {task['site']} / {task['query']} / status={result.get('status','ok')}")
            return send_json(self,{"ok":True})
        if u.path=="/api/resume":
            rid=data.get("run_id")
            with LOCK:
                run=RUNS.get(rid)
                if not run:return send_json(self,{"error":"run_not_found"},404)
                run["paused"]=False;run["pause_reason"]=""
            return send_json(self,{"ok":True})
        if u.path=="/api/cancel":
            rid=data.get("run_id")
            with LOCK:
                if rid in RUNS:RUNS[rid]["cancelled"]=True
            return send_json(self,{"ok":True})
        return send_json(self,{"error":"not_found"},404)

def run_server():
    log(f"Chrome bridge listening http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()

if __name__=="__main__":
    run_server()
