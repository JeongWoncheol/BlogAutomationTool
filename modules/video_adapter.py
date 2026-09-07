# -*- coding: utf-8 -*-
from pathlib import Path
import json, sqlite3, time, os, shutil, urllib.request, urllib.parse, uuid, subprocess, copy, re, math, mimetypes
from .common import ROOT, DB, log, settings
from . import ollama_local, content_adapter

VIDEO_ROOT = ROOT/"video"
CFG_PATH = VIDEO_ROOT/"video_engine.json"

def cfg():
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))

def ensure_columns():
    con=sqlite3.connect(DB)
    cols={r[1] for r in con.execute("PRAGMA table_info(products)").fetchall()}
    for name,typ in [
        ("video_storyboard","TEXT"),
        ("video_output","TEXT"),
        ("video_status","TEXT DEFAULT '미생성'"),
        ("video_last_error","TEXT"),
        ("video_quality_mode","TEXT"),
        ("video_plan_source","TEXT"),
        ("video_plan_summary","TEXT")
    ]:
        if name not in cols:
            con.execute(f"ALTER TABLE products ADD COLUMN {name} {typ}")
    con.commit();con.close()


def _auto_node_map(wf):
    m={}
    for nid,n in wf.items():
        if not isinstance(n,dict): continue
        cls=str(n.get("class_type","")).lower()
        title=(str(n.get("_meta",{}).get("title",""))+" "+cls).lower()
        inp=n.get("inputs",{}) if isinstance(n.get("inputs"),dict) else {}
        if not m.get("load_image_node") and "loadimage" in cls:m["load_image_node"]=str(nid)
        if "cliptextencode" in cls:
            txt=str(inp.get("text","")).lower()
            neg=any(x in title for x in ["negative","neg"]) or any(x in txt for x in ["bad quality","worst quality","deformed"])
            if neg and not m.get("negative_prompt_node"):m["negative_prompt_node"]=str(nid)
            elif not neg and not m.get("positive_prompt_node"):m["positive_prompt_node"]=str(nid)
        if not m.get("save_video_node") and any(x in cls for x in ["savevideo","vhs_videocombine","saveanimatedwebp"]):m["save_video_node"]=str(nid)
        if not m.get("steps_node") and "steps" in inp:m["steps_node"]=str(nid)
        if not m.get("cfg_node") and any(k in inp for k in ["cfg","guidance"]):m["cfg_node"]=str(nid)
        if not m.get("seed_node") and "seed" in inp:m["seed_node"]=str(nid)
        if not m.get("frame_count_node") and any(k in inp for k in ["length","frames","frame_count","num_frames"]):
            if "video" in cls or "wan" in cls:m["frame_count_node"]=str(nid)
    return m

def _ensure_node_map():
    c=cfg(); wf=ROOT/c["workflow_api_json"]
    if not wf.exists(): return c
    try:
        data=json.loads(wf.read_text(encoding="utf-8"))
        auto=_auto_node_map(data)
        nm=c.setdefault("node_map",{})
        changed=False
        for k,v in auto.items():
            if not nm.get(k):
                nm[k]=v;changed=True
        if changed:
            CFG_PATH.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception: pass
    return c

def health():
    c=_ensure_node_map()
    wf=ROOT/c["workflow_api_json"]
    ff=shutil.which("ffmpeg")
    comfy=False
    try:
        with urllib.request.urlopen(c["comfy_url"]+"/system_stats",timeout=2) as r:
            comfy=(r.status==200)
    except: pass
    nm=c.get("node_map",{})
    ready=bool(ff and wf.exists() and comfy and nm.get("positive_prompt_node") and nm.get("load_image_node"))
    misses=[]
    if not ff: misses.append("ffmpeg 미설치")
    if not wf.exists(): misses.append("ComfyUI API workflow JSON 없음")
    if not comfy: misses.append("ComfyUI 서버 미연결")
    if not nm.get("positive_prompt_node"): misses.append("positive_prompt_node 미설정")
    if not nm.get("load_image_node"): misses.append("load_image_node 미설정")
    if not ready: misses.append("09_AI_VIDEO_AUTO_SETUP.cmd 실행 권장")
    return {"ready":ready,"name":"AI 자연동작 제품영상","message":"정상" if ready else " / ".join(misses)}


def planning_health():
    st=ollama_local.status(settings())
    model=st.get("model") or st.get("recommended") or settings().get("ollama_model") or "Qwen3"
    if st.get("ready"):
        return {"ready":True,"name":"Ollama 영상기획","message":f"Ollama {model} 무료 로컬 영상기획 READY","model":model}
    return {"ready":False,"name":"Ollama 영상기획","message":str(st.get("reason") or "Ollama 연결 필요"),"model":model}

def _safe(s):
    return re.sub(r"[^0-9A-Za-z가-힣_-]+","_",s)[:55].strip("_") or "product"

def _category_mode(category,name):
    t=((category or "")+" "+(name or "")).lower()
    if any(x in t for x in ["식품","푸드","음료","과일","건강식품","간식"]): return "food"
    if any(x in t for x in ["패션","운동화","신발","가방","의류","원피스","블라우스","티셔츠"]): return "fashion"
    if any(x in t for x in ["뷰티","스킨","메이크업","화장","세럼","에센스","크림","쿠션","선크림"]): return "beauty"
    if any(x in t for x in ["가전","디지털","선풍기","이어폰","세탁기","청소기","캡처카드"]): return "device"
    return "living"

def _common(name):
    return f"""
Photorealistic premium Korean lifestyle product-review video, vertical 9:16.
The REAL PRODUCT REFERENCE IMAGE is the exact product: {name}.
Preserve the exact real product shape, color, proportions, logo placement and recognizable design.
The product must remain the SAME product through all scenes.
Use natural Korean adult actors, subtle genuine expressions, realistic hands, realistic gravity, realistic object physics,
realistic fabric/water/food behavior where relevant, smooth cinematic tracking and handheld motion.
This must look like a real commercial filmed in a real home, NOT a slideshow and NOT a static image animation.
The person must physically interact with the product: pick it up, open it, use it, react to the result, and continue the routine.
No floating objects, no teleporting products, no impossible physics, no deformed hands, no extra fingers.
No fake prices, discounts, medical/scientific claims, or invented product functions.
Do not render Korean text inside the generated clip; leave clean caption-safe space for post editing.
"""

def _scene_library(mode):
    if mode=="food":
        return [
          ("Hook","A real person notices the product in a kitchen and naturally picks it up, immediately showing the exact product clearly."),
          ("Open","Hands physically open the exact package and reveal the real contents with realistic package movement."),
          ("Prepare","The same person prepares the product for eating or drinking using realistic cup, plate, or cooking tools."),
          ("Use","Show the central eating/drinking/preparation action continuously, with natural hand and body movement."),
          ("Detail","Macro moving shot of real texture, steam, liquid, crunch, or serving amount without exaggeration."),
          ("Reaction","The same person tastes it and shows a small authentic satisfied reaction, never overacting."),
          ("Lifestyle","Show the product fitting naturally into breakfast, snack, office, or home routine."),
          ("Practicality","Show real pack size, amount, storage, or portion convenience through physical handling."),
          ("Repeat","The same person reaches for the product again later, showing repeat-use desirability."),
          ("WhyBuy","Demonstrate the main real purchase reason through action: convenience, portion, taste use-case, or storage."),
          ("Montage","Fast match-cut montage: open, prepare, consume, smile, clean up, store."),
          ("Hero","Final hero composition: exact real product on a natural kitchen/table setting, slow push-in, clean lower caption space.")
        ]
    if mode=="fashion":
        return [
          ("Hook","A real person holds the exact product and immediately transitions into wearing or carrying it."),
          ("Detail","Hands touch real material, stitching, sole, zipper, strap, or hardware while camera moves around the exact item."),
          ("Wear","The same person physically puts on the clothing/shoes or adjusts the bag, showing the full action."),
          ("Fit","Full-body moving shot while walking or turning so real fit and proportions are visible."),
          ("Motion","Natural walking, stairs, sitting, or everyday motion to show how the product moves with the body."),
          ("Feature","Physically demonstrate an actual pocket, handle, strap, cushioning, closure, or other visible feature."),
          ("Style","The same product is used in one believable daily outfit without changing the product design."),
          ("CloseFit","Close moving shot of the worn item while the person moves naturally."),
          ("Lifestyle","Use the item in commute, walk, cafe, office, or casual outing context."),
          ("WhyBuy","Show the clearest real purchase reason through movement: comfort, versatility, capacity, easy styling."),
          ("Montage","Fast match-cut montage: wear, walk, detail, lifestyle, confident natural movement."),
          ("Hero","Final hero: exact product worn or placed naturally, slow push-in, clean lower caption space.")
        ]
    if mode=="beauty":
        return [
          ("Hook","At a real vanity or sink, the same Korean adult reaches for the exact product as part of a normal routine."),
          ("Detail","Hands physically handle the exact bottle, compact, tube or package and show pump/cap/applicator detail."),
          ("Dose","The same person dispenses or takes a realistic amount onto hand, puff, cotton pad, or fingertip."),
          ("Apply","Continuous real application to the appropriate area with natural hand motion."),
          ("Texture","Macro moving shot showing real texture, spreadability, finish or absorption without unsupported claims."),
          ("Reaction","The same person checks the result in a mirror with a subtle satisfied expression."),
          ("Routine","Show how the exact product fits easily into morning or evening routine."),
          ("Carry","Physically place it into pouch/shelf/bag to show realistic storage or portability if applicable."),
          ("Repeat","The same person later reaches for the same product again in another routine moment."),
          ("WhyBuy","Show the main real purchase reason through routine behavior: ease, texture, finish, portability, or format."),
          ("Montage","Fast match-cut montage: open, dispense, apply, mirror, store."),
          ("Hero","Final hero: exact real product on the vanity, same environment, slow push-in, clean lower caption space.")
        ]
    if mode=="device":
        return [
          ("Hook","A real person encounters a practical need and immediately reaches for the exact product."),
          ("Detail","Hands physically show real buttons, ports, handle, controls, vents, or structure with moving close-ups."),
          ("Setup","The same person performs the actual setup or connection sequence with realistic movement."),
          ("Use","Continuous central use action showing the device being operated by the person."),
          ("Operation","Moving close-up of the device physically operating with realistic motion and physics."),
          ("Reaction","The same person checks the result and gives a subtle authentic satisfied reaction."),
          ("Lifestyle","Show the device solving the everyday use-case in a real home/desk/travel environment."),
          ("StoreCarry","The person physically stores, carries, folds, packs, or places the device naturally."),
          ("Repeat","The same person uses the same exact device again in another realistic scenario."),
          ("WhyBuy","Show the most obvious real purchase reason through action: convenience, portability, control, or practical use."),
          ("Montage","Fast match-cut montage: pick up, setup, operate, result, store."),
          ("Hero","Final hero: exact real device in its natural usage space, slow push-in, clean lower caption space.")
        ]
    return [
      ("Hook","Show a real everyday inconvenience or need, then the same person naturally reaches for the exact product."),
      ("Detail","Hands physically handle and rotate the exact product, showing package and material details."),
      ("Prepare","The same person opens, removes, unfolds, dispenses, or prepares the product for real use."),
      ("Use","Show the main product use continuously from hand movement to physical result."),
      ("DetailUse","Macro moving shot of the product actually being used, with realistic physics."),
      ("Reaction","The same person checks the result and gives a small genuine satisfied reaction."),
      ("Lifestyle","Show how the product fits naturally into a repeated everyday routine."),
      ("Practicality","Physically show real quantity, size, storage, portability, or organization."),
      ("Repeat","The same person later reaches for and uses the same product again."),
      ("WhyBuy","Demonstrate the main real purchase reason through action, not a feature list."),
      ("Montage","Fast match-cut montage: take out, use, result, lifestyle, store."),
      ("Hero","Final hero: exact real product in the same natural environment, slow push-in, clean lower caption space.")
    ]

def _body_text(row):
    raw=str(row["body"] or "") if "body" in row.keys() else ""
    try:
        obj=json.loads(raw)
        if isinstance(obj,list):
            parts=[]
            for b in obj:
                if not isinstance(b,dict):continue
                if b.get("text"):parts.append(str(b.get("text")))
                if isinstance(b.get("lines"),list):parts.extend(str(x) for x in b.get("lines") if str(x).strip())
            return " ".join(parts)[:3500]
    except Exception:pass
    return re.sub(r"\s+"," ",raw)[:3500]


def _fallback_plan(row, reason=""):
    mode=_category_mode(row["category"],row["name"])
    library=_scene_library(mode); common=_common(row["name"])
    scenes=[]
    for i,(purpose,action) in enumerate(library,1):
        s=(i-1)*5;e=i*5
        transition="End with a stable natural frame that can become the starting frame of the next scene."
        if i==12:transition="End with the exact product clearly visible and hold a stable hero composition for the final CTA."
        scenes.append({"scene":i,"start":s,"end":e,"purpose":purpose,"action":action,"caption":"","prompt":f"{common}\nSCENE {i}/12, duration about 5 seconds, timeline {s:02d}-{e:02d}.\nScene purpose: {purpose}.\nAction: {action}\nCONTINUITY:\nUse the SAME main adult, same face, same hair, same clothing family, same home/environment, and the SAME exact product.\nContinue naturally from the previous-scene frame when provided. The actor and camera must actually move. Use real hand-object contact and realistic object motion.\n{transition}".strip()})
    return {"concept":"실제 제품사진 기반 생활밀착형 사용 영상","target_customer":"제품 구매를 비교 중인 소비자","video_goal":"제품의 실제 사용 장면과 구매 판단 포인트를 자연스럽게 전달","hook_text":"이 제품, 실제 생활에서는 이렇게 쓰입니다","cta_text":"구성·옵션·현재 가격은 제품 링크에서 확인해보세요","style":"photorealistic Korean lifestyle product review","planning_source":"template_fallback","fallback_reason":reason,"scenes":scenes}


def _normalize_ai_plan(row,obj):
    if not isinstance(obj,dict):raise ValueError("Ollama 영상기획 JSON 형식 오류")
    raw=obj.get("scenes") or []
    fallback=_scene_library(_category_mode(row["category"],row["name"]))
    common=_common(row["name"]); scenes=[]
    for i in range(1,13):
        ai=raw[i-1] if i-1<len(raw) and isinstance(raw[i-1],dict) else {}
        fp,fa=fallback[i-1]
        purpose=str(ai.get("purpose") or fp).strip()[:120]
        action=str(ai.get("action") or fa).strip()[:700]
        caption=str(ai.get("caption") or "").strip()[:90]
        creative=str(ai.get("prompt") or "").strip()
        start=(i-1)*5;end=i*5
        transition="End with a stable natural frame that can become the starting frame of the next scene."
        if i==12:transition="End with the exact product clearly visible and hold a stable hero composition for the final CTA."
        prompt=f"{common}\nSCENE {i}/12, duration about 5 seconds, timeline {start:02d}-{end:02d}.\nScene purpose: {purpose}.\nAction: {action}\nCreative direction: {creative}\nCONTINUITY: Same main adult, same face/hair/clothing family/environment and SAME exact product. Real physical interaction and camera movement only. No invented functions or claims. {transition}".strip()
        scenes.append({"scene":i,"start":start,"end":end,"purpose":purpose,"action":action,"caption":caption,"prompt":prompt})
    return {"concept":str(obj.get("concept") or "생활밀착형 제품 사용 영상").strip()[:300],
            "target_customer":str(obj.get("target_customer") or "구매를 비교 중인 소비자").strip()[:220],
            "video_goal":str(obj.get("video_goal") or "제품 사용 장면과 구매 판단 포인트 전달").strip()[:300],
            "hook_text":str(obj.get("hook_text") or "").strip()[:120],
            "cta_text":str(obj.get("cta_text") or "구성·옵션·현재 가격은 제품 링크에서 확인해보세요").strip()[:120],
            "style":str(obj.get("style") or "photorealistic Korean lifestyle product review").strip()[:240],
            "planning_source":"ollama_local_free","scenes":scenes}


def _ollama_plan(row):
    cfgobj=settings(); st=ollama_local.status(cfgobj)
    if not st.get("ready"):raise RuntimeError(str(st.get("reason") or "Ollama 로컬 AI가 준비되지 않았습니다."))
    model=ollama_local.resolve_model(cfgobj)
    title=str(row["title"] or "") if "title" in row.keys() else ""
    tags=str(row["tags"] or "") if "tags" in row.keys() else ""
    prompt=f"""당신은 한국 숏폼 커머스 영상 기획자입니다. 아래 실제 상품 데이터만 사용해서 9:16 세로형 60초 제품 영상을 기획하세요.

상품명: {row["name"]}
카테고리: {row["category"]}
블로그 제목: {title}
본문 참고: {_body_text(row)}
태그 참고: {tags[:1200]}

규칙:
- 총 12컷, 컷당 약 5초. 실제 제품사진을 Image-to-Video reference로 사용할 예정입니다.
- 제품 형태·색상·로고·패키지·모델을 절대 임의 변경하지 마세요.
- 확인되지 않은 기능, 효능, 성능, 할인, 최저가, 재고, 의학적 표현을 만들지 마세요.
- 한국 성인 1명을 중심으로 같은 인물/의상/공간이 자연스럽게 이어지게 기획하세요.
- 정지 슬라이드가 아니라 손으로 집고, 열고, 착용/사용하고, 결과를 확인하는 실제 행동 중심으로 작성하세요.
- 1~2컷은 훅, 중간은 사용/디테일/구매 판단 포인트, 12컷은 제품 hero + CTA 여백입니다.
- caption은 짧은 한국어 자막 문구이고, 영상 생성 prompt는 영어로 써주세요.
- 과장된 구매 강요 대신 '구성·옵션·현재 가격을 링크에서 확인'하는 자연스러운 CTA를 사용하세요.

반드시 아래 JSON 한 개만 반환하세요.
{{
 "concept":"영상 한 줄 콘셉트",
 "target_customer":"핵심 타깃",
 "video_goal":"영상 목표",
 "hook_text":"첫 화면 자막",
 "cta_text":"마지막 CTA",
 "style":"촬영/무드 방향",
 "scenes":[
   {{"scene":1,"purpose":"장면 목적(한국어)","action":"실제 행동(한국어)","caption":"짧은 자막(한국어)","prompt":"English image-to-video direction"}}
 ]
}}"""
    obj=content_adapter.call_ollama(prompt,model,cfgobj)
    plan=_normalize_ai_plan(row,obj);plan["ollama_model"]=model
    return plan


def storyboard_for(row, use_ollama=True):
    if use_ollama:
        try:return _ollama_plan(row)
        except Exception as e:
            log("Ollama 영상기획 실패 → 안전 기본기획: "+str(e))
            return _fallback_plan(row,str(e))
    return _fallback_plan(row)


def read_storyboard(path):
    try:
        obj=json.loads(Path(path).read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except Exception:return {}


def save_storyboard(product_id, force_ai=True):
    ensure_columns()
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    row=con.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
    if not row: con.close(); raise RuntimeError("상품 없음")
    existing=str(row["video_storyboard"] or "") if "video_storyboard" in row.keys() else ""
    if not force_ai and existing and Path(existing).is_file():
        old=read_storyboard(existing);sc=old.get("scenes") or []
        if len(sc)==12:
            con.close();return Path(existing),sc
    plan=storyboard_for(row, use_ollama=True)
    scenes=plan.get("scenes") or []
    d=VIDEO_ROOT/"storyboards"/f"{int(row['product_no'] or row['id']):02d}_{_safe(row['name'])}"
    d.mkdir(parents=True,exist_ok=True)
    p=d/"storyboard.json"
    payload={"product_id":product_id,"product_name":row["name"],"created_at":time.strftime("%Y-%m-%d %H:%M:%S"),**plan}
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    source=str(plan.get("planning_source") or "template_fallback")
    summary=f"{plan.get('concept','')} | 타깃: {plan.get('target_customer','')} | CTA: {plan.get('cta_text','')}"
    status="Ollama영상기획완료" if source=="ollama_local_free" else "기본영상기획완료"
    con.execute("UPDATE products SET video_storyboard=?,video_status=?,video_plan_source=?,video_plan_summary=?,updated_at=datetime('now','localtime') WHERE id=?",(str(p),status,source,summary[:1800],product_id))
    con.commit();con.close()
    return p,scenes

def _multipart_upload_image(url,path,name):
    boundary="----NVB"+uuid.uuid4().hex
    src=Path(path)
    mime=mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    data=src.read_bytes()
    body=[]
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()+data+b"\r\n")
    for k,v in [("type","input"),("overwrite","true")]:
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    body.append(f"--{boundary}--\r\n".encode())
    req=urllib.request.Request(
        url.rstrip("/")+"/upload/image",
        data=b"".join(body),
        headers={"Content-Type":f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(req,timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))

def _copy_to_comfy(path,tag="ref"):
    c=cfg();src=Path(path)
    name=f"blog_{tag}_{uuid.uuid4().hex[:8]}_{src.name}"
    root=Path(c.get("comfy_root") or "")
    if c.get("comfy_root") and root.exists():
        inp=root/"input";inp.mkdir(parents=True,exist_ok=True)
        dst=inp/name;shutil.copy2(src,dst);return name
    try:
        resp=_multipart_upload_image(c["comfy_url"],src,name)
        return resp.get("name") or name
    except Exception as e:
        raise RuntimeError("ComfyUI 이미지 업로드 실패: "+str(e))

def _set(wf,node,key,val):
    n=wf.get(str(node))
    if not n: raise RuntimeError(f"ComfyUI node {node} 없음")
    n.setdefault("inputs",{})[key]=val

def _apply(prompt, primary_ref, product_ref=None, prefix="scene"):
    c=cfg();wf=json.loads((ROOT/c["workflow_api_json"]).read_text(encoding="utf-8"));nm=c["node_map"]
    _set(wf,nm["positive_prompt_node"],"text",prompt)
    if nm.get("negative_prompt_node"):
        neg=("slideshow, still photo, static image, generic product, changed logo, changed package, wrong colors, "
             "deformed hand, extra fingers, floating object, teleportation, impossible physics, cartoon, CGI, fake text")
        _set(wf,nm["negative_prompt_node"],"text",neg)
    _set(wf,nm["load_image_node"],"image",primary_ref)
    # Optional second reference: exact product image while primary is previous scene frame.
    if product_ref and nm.get("secondary_product_reference_node"):
        _set(wf,nm["secondary_product_reference_node"],"image",product_ref)
    if nm.get("save_video_node"):
        n=wf.get(str(nm["save_video_node"]))
        if n:
            for k in ["filename_prefix","filename"]:
                if k in n.get("inputs",{}): n["inputs"][k]=prefix;break
    # quality knobs when workflow exposes them
    q=c.get("quality_mode","balanced")
    steps={"fast":18,"balanced":28,"quality":40}.get(q,28)
    cfgv={"fast":4.5,"balanced":5.5,"quality":6.0}.get(q,5.5)
    if nm.get("steps_node"):
        n=wf.get(str(nm["steps_node"]))
        if n:
            for k in ["steps","value"]:
                if k in n.get("inputs",{}):n["inputs"][k]=steps;break
    if nm.get("cfg_node"):
        n=wf.get(str(nm["cfg_node"]))
        if n:
            for k in ["cfg","guidance","value"]:
                if k in n.get("inputs",{}):n["inputs"][k]=cfgv;break
    return wf

def _post(url,obj,timeout=60):
    data=json.dumps(obj).encode()
    req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())

def _get(url,timeout=60):
    with urllib.request.urlopen(url,timeout=timeout) as r:return json.loads(r.read().decode())

def _wait(wf,timeout=2400):
    c=cfg();pid=_post(c["comfy_url"]+"/prompt",{"prompt":wf,"client_id":str(uuid.uuid4())})["prompt_id"]
    end=time.time()+timeout
    while time.time()<end:
        h=_get(c["comfy_url"]+"/history/"+pid)
        if pid in h:return h[pid]
        time.sleep(2)
    raise TimeoutError("ComfyUI 생성 시간 초과")

def _find_output(hist):
    c=cfg();cand=[]
    for nodeout in hist.get("outputs",{}).values():
        for val in nodeout.values():
            if isinstance(val,list):
                for item in val:
                    if isinstance(item,dict) and item.get("filename"):cand.append(item)
    vids=[x for x in cand if Path(x["filename"]).suffix.lower() in [".mp4",".mov",".webm",".gif"]]
    item=(vids or cand)[0] if (vids or cand) else None
    if not item:raise RuntimeError("영상 출력 파일을 찾지 못했습니다.")

    root=Path(c.get("comfy_root") or "")
    if c.get("comfy_root") and root.exists():
        folder=root/("output" if item.get("type","output")=="output" else item.get("type"))/item.get("subfolder","")
        p=folder/item["filename"]
        if p.exists():
            return p

    outdir=VIDEO_ROOT/"downloaded_outputs";outdir.mkdir(parents=True,exist_ok=True)
    p=outdir/f"{uuid.uuid4().hex[:8]}_{Path(item['filename']).name}"
    query=urllib.parse.urlencode({
        "filename":item["filename"],
        "subfolder":item.get("subfolder",""),
        "type":item.get("type","output")
    })
    try:
        with urllib.request.urlopen(c["comfy_url"].rstrip("/")+"/view?"+query,timeout=300) as r:
            p.write_bytes(r.read())
    except Exception as e:
        raise RuntimeError("ComfyUI 출력 다운로드 실패: "+str(e))
    if not p.exists() or p.stat().st_size==0:
        raise RuntimeError("ComfyUI 출력 다운로드 파일이 비어 있습니다.")
    return p

def _last_frame(video,out):
    cmd=["ffmpeg","-y","-sseof","-0.08","-i",str(video),"-frames:v","1","-q:v","2",str(out)]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if not out.exists():raise RuntimeError("마지막 프레임 추출 실패")
    return out

def _concat_xfade(clips,out,transition=0.15):
    # Re-encode clips to a common format, then use tiny xfade transitions for smooth continuity.
    tmp=out.parent/"norm";tmp.mkdir(parents=True,exist_ok=True)
    norm=[]
    for i,c in enumerate(clips):
        n=tmp/f"n_{i:02d}.mp4"
        subprocess.run(["ffmpeg","-y","-i",str(c),"-vf",f"scale={cfg()['width']}:{cfg()['height']},fps={cfg()['fps']}",
                        "-an","-c:v","libx264","-pix_fmt","yuv420p","-crf","20",str(n)],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        norm.append(n)
    # More robust than complex xfade for arbitrary clips: concatenate because chained last-frame gives continuity.
    lst=out.parent/"concat.txt";lst.write_text("\n".join(f"file '{x.as_posix()}'" for x in norm),encoding="utf-8")
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),"-c:v","libx264","-pix_fmt","yuv420p",
                    "-movflags","+faststart",str(out)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def generate_product(product_id,progress=None):
    ensure_columns();c=cfg()
    sb,scenes=save_storyboard(product_id,force_ai=False)
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    row=con.execute("SELECT * FROM products WHERE id=?",(product_id,)).fetchone()
    ref=row["image1"] or row["image2"] or row["image3"]
    if not ref or not Path(ref).exists():
        con.close();raise RuntimeError("실제 제품사진이 없습니다. 먼저 실제 사진 수집 단계를 실행하세요.")
    h=health()
    if not h["ready"]:
        con.close();raise RuntimeError(h["message"])
    product_ref=_copy_to_comfy(ref,"product")
    outdir=VIDEO_ROOT/"clips"/f"{int(row['product_no'] or row['id']):02d}_{_safe(row['name'])}"
    outdir.mkdir(parents=True,exist_ok=True)
    clips=[];previous_frame=None
    retries=int(c.get("scene_retry_count",2))
    try:
        for i,scene in enumerate(scenes,1):
            if progress:progress(i-1,len(scenes),f"{i}/12 {scene['purpose']} — 자연동작 생성")
            primary=product_ref if previous_frame is None else _copy_to_comfy(previous_frame,f"chain{i:02d}")
            dual_product=product_ref if previous_frame is not None and c.get("dual_reference_supported") else None
            last_err=None
            for attempt in range(retries+1):
                try:
                    wf=_apply(scene["prompt"],primary,dual_product,f"blog_{int(row['product_no'] or row['id']):02d}_s{i:02d}_a{attempt}")
                    hist=_wait(wf);src=_find_output(hist)
                    dst=outdir/f"scene_{i:02d}{src.suffix.lower()}";shutil.copy2(src,dst)
                    # validate decodable and create continuity frame
                    frame=outdir/f"scene_{i:02d}_last.jpg";_last_frame(dst,frame)
                    clips.append(dst);previous_frame=frame;break
                except Exception as e:
                    last_err=e;log(f"video scene {i} retry {attempt}: {e}")
                    if attempt>=retries:raise
            if progress:progress(i,len(scenes),f"{i}/12 완료")
        finaldir=VIDEO_ROOT/"outputs";finaldir.mkdir(parents=True,exist_ok=True)
        final=finaldir/f"{int(row['product_no'] or row['id']):02d}_{_safe(row['name'])}_natural_60s.mp4"
        _concat_xfade(clips,final,float(c.get("transition_seconds",0.15)))
        con.execute("UPDATE products SET video_output=?,video_status='자연동작영상완료',video_last_error=NULL,video_quality_mode=?,updated_at=datetime('now','localtime') WHERE id=?",
                    (str(final),c.get("quality_mode","balanced"),product_id))
        con.commit()
        if progress:progress(12,12,"60초 자연동작 영상 완성")
        return final
    except Exception as e:
        con.execute("UPDATE products SET video_status='영상실패',video_last_error=?,updated_at=datetime('now','localtime') WHERE id=?",(str(e),product_id))
        con.commit();raise
    finally:
        con.close()

def generate_all(progress=None):
    ensure_columns()
    con=sqlite3.connect(DB);rows=con.execute("SELECT id,name FROM products ORDER BY product_no,id").fetchall();con.close()
    outs=[]
    for i,(pid,name) in enumerate(rows,1):
        if progress:progress(i-1,len(rows),f"{name[:35]} 영상 시작")
        outs.append(str(generate_product(pid)))
    if progress:progress(len(rows),len(rows),"전체 제품 영상 완료")
    return outs
