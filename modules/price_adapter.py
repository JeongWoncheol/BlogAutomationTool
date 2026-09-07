# -*- coding: utf-8 -*-
from pathlib import Path
import json,sqlite3,time,re,hashlib,urllib.request,urllib.error
from PIL import Image,ImageDraw,ImageFont,ImageOps,ImageFilter
from .common import *
from .search_adapter import is_valid_product_name, clean_product_name, driver_start, SITES, extract_cards, wait_results
from . import coupang_safe
from . import toss_mobile_adapter
from . import toss_web_adapter
from . import toss_sharelink_pc
from . import market_safe
from . import chrome_collector
from . import coupang_partners_api
from . import toss_sharelink_api
from . import naver_shopping_api
from .wala_policy import SOURCE_REASON, is_wala_product, skipped_price

def _image_dhash(path):
    im=Image.open(path).convert("L").resize((9,8),Image.Resampling.LANCZOS)
    pix=list(im.getdata());value=0
    for y in range(8):
        row=pix[y*9:(y+1)*9]
        for x in range(8):value=(value<<1)|(1 if row[x]>row[x+1] else 0)
    return value

def _hash_distance(a,b):
    return (a^b).bit_count()

def health():
    cfg=settings()
    if cfg.get("collection_mode","chrome_extension")=="chrome_extension":
        api=coupang_partners_api.health();tossapi=toss_sharelink_api.health();navapi=naver_shopping_api.health()
        return {"ready":True,"name":"3사 가격 안전검증",
                "message":"쿠팡/NAVER/Toss 공식 API 우선 · 쿠팡 Partners API "+("READY" if api.get("ready") else "키 미설정")+
                          " · 토스 Sharelink API "+("READY" if tossapi.get("ready") else "키 미설정")+
                          " · NAVER 쇼핑 API "+("READY" if navapi.get("ready") else "키 미설정")+
                          " · 누락만 핵심키워드→풀네임 재검증 · 가격+상품이미지 증거 검증"}
    try:
        from selenium import webdriver
    except Exception:
        return {"ready":False,"name":"3사 실제가격 엄격검증","message":"Selenium 모드인데 PC Selenium이 설치되지 않았습니다."}
    return {"ready":True,"name":"3사 실제가격 엄격검증",
            "message":"Selenium 보조 모드 · 쿠팡/네이버/토스 동일상품 가격 확인"}

def font(size,bold=False):
    paths=["C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
           "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for p in paths:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def fit_image(path,size=(360,270)):
    im=Image.open(path).convert("RGB")
    im.thumbnail(size,Image.Resampling.LANCZOS)
    bg=Image.new("RGB",size,"white")
    bg.paste(im,((size[0]-im.width)//2,(size[1]-im.height)//2))
    return bg

def _wrap(draw,text,font_obj,max_width,max_lines=3):
    words=re.findall(r"\S+",text or "")
    lines=[];cur=""
    for word in words:
        test=(cur+" "+word).strip()
        if draw.textbbox((0,0),test,font=font_obj)[2] <= max_width:
            cur=test
        else:
            if cur: lines.append(cur)
            cur=word
            if len(lines)>=max_lines-1: break
    if cur and len(lines)<max_lines: lines.append(cur)
    if len(lines)==max_lines and len(" ".join(words))>len(" ".join(lines)):
        while lines[-1] and draw.textbbox((0,0),lines[-1]+"…",font=font_obj)[2]>max_width:
            lines[-1]=lines[-1][:-1]
        lines[-1]+="…"
    return "\n".join(lines)

def _fit_cover(path,size):
    im=Image.open(path).convert("RGB")
    return ImageOps.fit(im,size,method=Image.Resampling.LANCZOS,centering=(0.5,0.5))

def _draw_crown(draw,cx,top,scale=1.0):
    # Large vector crown: no emoji/font dependency.
    w=int(126*scale);h=int(72*scale);x=cx-w//2;y=top
    pts=[(x,y+h),(x+8,y+22),(x+34,y+43),(x+w//2,y),(x+w-34,y+43),(x+w-8,y+22),(x+w,y+h)]
    draw.polygon(pts,fill=(238,181,24),outline=(155,105,0))
    draw.rounded_rectangle((x,y+h-14,x+w,y+h+8),radius=6,fill=(255,207,52),outline=(155,105,0),width=3)

def create_compare(name,records,out):
    """Always render all three marketplaces without fabricating missing values.

    Even if only one or zero marketplaces verify the exact option, the card keeps
    all three columns visible so a product never disappears from the comparison.
    """
    site_order=["쿠팡","네이버쇼핑","토스쇼핑"]
    by={r.get("site"):dict(r) for r in records if r.get("site")}
    allrec=[by.get(x,{"site":x,"price":None,"verified":False,"reason":"검색 결과 없음"}) for x in site_order]
    valid=[r for r in allrec if r.get("verified") and isinstance(r.get("price"),(int,float)) and r.get("price")>0]
    winner=min(valid,key=lambda r:r["price"]) if valid else None
    if winner:
        others=[r for r in allrec if r.get("site")!=winner.get("site")]
        ordered=[others[0],winner,others[1]]
    else:
        ordered=allrec

    W,H=1800,1100
    canvas=Image.new("RGB",(W,H),(247,248,250));d=ImageDraw.Draw(canvas)
    d.text((70,45),"3사 동일옵션 가격 확인",font=font(32,True),fill=(30,33,38))
    title=_wrap(d,name,font(48,True),1120,2)
    d.multiline_text((70,96),title,font=font(48,True),fill=(15,17,20),spacing=7)
    checked=time.strftime("%Y.%m.%d %H:%M 기준")
    tw=d.textbbox((0,0),checked,font=font(24,True))[2]
    d.text((W-70-tw,55),checked,font=font(24,True),fill=(95,97,102))
    coupled_count=sum(1 for r in allrec if r.get("verified") and r.get("price") and r.get("image_path") and Path(r.get("image_path")).exists())
    badge=f"가격 {len(valid)}/3 · 가격+이미지 {coupled_count}/3"
    d.rounded_rectangle((70,225,560,270),radius=20,fill=(232,235,239))
    d.text((315,248),badge,font=font(21,True),fill=(55,58,63),anchor="mm")
    boxes=[(65,310,520,950),(590,235,1210,1030),(1280,310,1735,950)]

    for r,box in zip(ordered,boxes):
        x0,y0,x1,y1=box;win=bool(winner and r.get("site")==winner.get("site"));verified=bool(r.get("verified") and r.get("price"))
        if win:
            glow=Image.new("RGBA",(W,H),(0,0,0,0));gd=ImageDraw.Draw(glow)
            gd.rounded_rectangle((x0-22,y0-22,x1+22,y1+22),radius=48,fill=(255,213,74,58))
            glow=glow.filter(ImageFilter.GaussianBlur(18))
            canvas=Image.alpha_composite(canvas.convert("RGBA"),glow).convert("RGB");d=ImageDraw.Draw(canvas)
            d.rounded_rectangle((x0-12,y0-12,x1+12,y1+12),radius=46,fill=(255,247,215))
            d.rounded_rectangle(box,radius=42,fill=(255,255,252),outline=(209,153,14),width=16)
            _draw_crown(d,(x0+x1)//2,y0-125,1.15)
            badge="확인 판매처" if len(valid)==1 else "최저가 1등"
            bw=d.textbbox((0,0),badge,font=font(38,True))[2]+70;bx=(x0+x1-bw)//2
            d.rounded_rectangle((bx,y0-40,bx+bw,y0+28),radius=34,fill=(206,148,12))
            d.text(((x0+x1)//2,y0-6),badge,font=font(38,True),fill="white",anchor="mm")
        else:d.rounded_rectangle(box,radius=34,fill="white",outline=(214,217,221),width=4)

        d.text(((x0+x1)//2,y0+62),r.get("site",""),font=font(38 if win else 31,True),fill=(20,22,25),anchor="mm")
        cardw=x1-x0;iw=cardw-70;ih=335 if win else 275;img_top=y0+115
        coupled=bool(r.get("image_path") and Path(r["image_path"]).exists())
        if coupled:
            canvas.paste(_fit_cover(r["image_path"],(iw,ih)),(x0+35,img_top));d=ImageDraw.Draw(canvas)
        else:
            d.rounded_rectangle((x0+35,img_top,x1-35,img_top+ih),20,fill=(242,243,245))
            d.text(((x0+x1)//2,img_top+ih//2),"동일상품 이미지 미수집",font=font(21,True),fill=(130,130,130),anchor="mm")

        pnfont=font(25 if win else 21,True)
        pname=_wrap(d,r.get("product_name") or name,pnfont,cardw-70,2)
        d.multiline_text((x0+35,img_top+ih+24),pname,font=pnfont,fill=(55,58,63),spacing=6)
        py=y0+585 if win else y0+530
        if verified:
            d.text(((x0+x1)//2,py),f'{int(r["price"]):,}원',font=font(76 if win else 50,True),fill=(12,14,17),anchor="mm")
            if win and len(valid)>=2:
                others_price=[int(q["price"]) for q in valid if q.get("site")!=winner.get("site")]
                saving=max(others_price)-int(winner["price"]) if others_price else 0
                if saving>0:d.text(((x0+x1)//2,py+88),f"다른 확인 판매처보다 최대 {saving:,}원 저렴",font=font(26,True),fill=(144,99,0),anchor="mm")
            elif winner and r.get("site")!=winner.get("site"):
                diff=int(r["price"])-int(winner["price"])
                if diff>0:d.text(((x0+x1)//2,py+65),f"+{diff:,}원",font=font(22,True),fill=(110,112,116),anchor="mm")
            if not coupled:d.text(((x0+x1)//2,py+110),"가격은 확인됐지만 이미지 증거는 보강 필요",font=font(17,False),fill=(120,122,126),anchor="mm")
        else:
            d.text(((x0+x1)//2,py),"동일옵션 가격 미확인",font=font(34,True),fill=(120,122,126),anchor="mm")
            reason=_wrap(d,r.get("reason") or "동일상품/동일옵션을 확인하지 못했습니다.",font(18,False),cardw-80,2)
            d.multiline_text((x0+40,py+55),reason,font=font(18,False),fill=(130,132,136),spacing=4)

    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);canvas.save(out,"JPEG",quality=96,subsampling=0)
    return str(out)



def core_search_query(name):
    """First fallback query. Exact target validation never changes."""
    qs=core_search_queries(name,1)
    return qs[0] if qs else str(name)

def core_search_queries(name,max_count=3):
    terms=identity_terms(name);sig=signature_identity_tokens(name);crit=critical_identity_tokens(name)
    variants=[]
    def add(parts):
        out=[]
        for x in parts:
            x=str(x or "").strip()
            if x and x.lower() not in {y.lower() for y in out}:out.append(x)
        q=" ".join(out[:6]).strip()
        if q and q.lower()!=str(name).strip().lower() and q.lower() not in {x.lower() for x in variants}:variants.append(q)
    add(terms[:3]+crit[:2])
    add(terms[:2]+sig+crit[:2])
    add(terms[:1]+sig+crit[:3])
    add(terms[:4])
    return variants[:max(0,int(max_count))]

def _download_record_image(rec,evdir):
    """Persist the image URL tied to the selected exact product record.

    CDN rules differ by marketplace. Try direct/no-referer and site referers rather
    than treating the first 403 as permanent image failure.
    """
    if rec.get("image_path") and Path(rec["image_path"]).exists():
        rec["price_image_verified"]=True;return rec
    u=str(rec.get("image_url") or "").strip()
    if not u:
        rec["price_image_verified"]=False;return rec
    if u.startswith("//"):u="https:"+u
    attempts=[];urls=[u]
    if u.startswith("http://"):urls.insert(0,"https://"+u[len("http://"):])
    page=rec.get("url") or ""
    if page:attempts.append(page)
    site=rec.get("site") or ""
    attempts += (["https://www.coupang.com/",""] if site=="쿠팡" else
                 ["https://search.shopping.naver.com/",""] if site=="네이버쇼핑" else
                 ["https://sharelink.toss.im/",""])
    seen=set();last=""
    for image_url in urls:
      for referer in attempts:
        key=(image_url,referer)
        if key in seen:continue
        seen.add(key)
        try:
            headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
                     "Accept":"image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"}
            if referer:headers["Referer"]=referer
            req=urllib.request.Request(image_url,headers=headers)
            with urllib.request.urlopen(req,timeout=18) as rr:data=rr.read(12*1024*1024)
            if len(data)<4000:raise RuntimeError("image too small")
            sitefn=re.sub(r"[^0-9A-Za-z가-힣_-]","_",site or "site")
            p=Path(evdir)/f"{sitefn}_동일상품_직접이미지.jpg"
            with Image.open(__import__('io').BytesIO(data)) as opened:im=opened.convert("RGB").copy()
            if im.width<120 or im.height<120:raise RuntimeError(f"image dimension {im.width}x{im.height}")
            im.thumbnail((1400,1400));im.save(p,"JPEG",quality=95)
            rec["image_path"]=str(p);rec["price_image_verified"]=True;rec["image_download_referer"]=referer or "none"
            return rec
            im.close()
        except Exception as e:last=str(e)
    rec["price_image_verified"]=False;rec["image_error"]=last or "image download failed"
    return rec


def _candidate_image_enrich(con,product,rec,cfg):
    """Fill a verified price record's missing image URL from the same-run exact candidate.

    Marketplace taxonomies do not line up 1:1.  v7.56 restricted the lookup to the
    blog category and therefore threw away an otherwise exact candidate whenever a
    marketplace classified it differently.  Identity validation is the safety gate;
    category is now only a tie-break preference.
    """
    if not con or not rec.get("verified") or rec.get("image_path") or rec.get("image_url"):
        return rec
    rows=con.execute("""SELECT name,image_url,url,rank_no,category FROM candidates
                         WHERE platform=? AND image_url IS NOT NULL AND image_url<>''
                         ORDER BY rank_no,id""",(rec.get("site"),)).fetchall()
    best=None
    for c in rows:
        ok,score,detail=marketplace_product_accept(c["name"] or "",product["name"],float(cfg.get("price_api_recall_match_threshold",0.48)))
        if not ok:continue
        same_category=bool(product["category"] and c["category"] and c["category"]==product["category"])
        z={"score":score,"image_url":c["image_url"] or "","url":c["url"] or "","name":c["name"] or "","rank":c["rank_no"],"detail":detail,"same_category":same_category}
        if (best is None or score>best["score"] or
            (abs(score-best["score"])<1e-9 and same_category and not best.get("same_category")) or
            (abs(score-best["score"])<1e-9 and same_category==best.get("same_category") and int(z["rank"] or 999)<int(best["rank"] or 999))):
            best=z
    if best:
        rec["image_url"]=best["image_url"]
        rec["image_enriched_from"]="same_run_exact_candidate_cross_category_safe"
        rec["image_candidate_name"]=best["name"]
        rec["image_match_detail"]=best["detail"]
        if not rec.get("url"):rec["url"]=best["url"]
    return rec

def _candidate_prefill(con,rows,site,cfg):
    """Reuse the same-run 540 discovery snapshot before issuing new searches.

    Category mismatch is no longer a hard rejection. Coupang/NAVER/Toss use
    different category trees, so exact identity + option tokens decide safety and
    same category is used only as a tie breaker.
    """
    if not con or not cfg.get("price_reuse_same_run_candidates",True):return {}
    allc=con.execute("SELECT * FROM candidates WHERE platform=? AND price IS NOT NULL AND price>0 ORDER BY rank_no,id",(site,)).fetchall()
    out={}
    for r in rows:
        best=None
        for c in allc:
            ok,score,detail=marketplace_product_accept(c["name"] or "",r["name"],float(cfg.get("price_api_recall_match_threshold",0.48)))
            match_mode="strict"
            if not ok and cfg.get("price_snapshot_relaxed_match",True):
                critical_missing=detail.get("missing") or []
                core_hit=bool(detail.get("core_hit"))
                signature_missing=detail.get("signature_missing") or []
                relaxed=float(cfg.get("price_snapshot_match_threshold",0.52))
                if not critical_missing and core_hit and not signature_missing and score>=relaxed:
                    ok=True;match_mode="snapshot_relaxed_strict_variant"
            if not ok:continue
            same_category=bool(r["category"] and c["category"] and c["category"]==r["category"])
            row={"site":site,"price":int(c["price"]),"product_name":clean_product_name(c["name"] or ""),"image_path":None,
                 "image_url":c["image_url"] or "","evidence":None,"url":c["url"] or "","match":score,"verified":True,
                 "match_detail":detail,"match_mode":match_mode,"source":"same_run_discovery_snapshot","captured_at":c["captured_at"] or "","query_used":c["query"] or "","browser_free":True,
                 "rank_no":c["rank_no"],"same_category":same_category}
            if (best is None or score>best["match"] or
                (abs(score-best["match"])<1e-9 and same_category and not best.get("same_category")) or
                (abs(score-best["match"])<1e-9 and same_category==best.get("same_category") and int(c["rank_no"] or 999)<int(best.get("rank_no") or 999))):
                best=row
        if best:out[r["id"]]=best
    return out

def _coupang_api_prefill(rows,cfg,existing=None,progress=None):
    """Browser-free Coupang price/image enrichment for snapshot misses only."""
    out=dict(existing or {})
    if not cfg.get("coupang_api_enabled",True) or not coupang_partners_api.ready():
        code="API_DISABLED" if not cfg.get("coupang_api_enabled",True) else "API_CREDENTIALS_MISSING"
        return out,{"ready":False,"attempted":0,"verified":0,"errors":[],"reason_codes":{str(r["id"]):code for r in rows}}
    missing=[r for r in rows if not (out.get(r["id"]) or {}).get("verified") or not (out.get(r["id"]) or {}).get("image_url")]
    max_queries=max(1,int(cfg.get("coupang_api_price_query_count",4)))
    state={"ready":True,"attempted":0,"verified":0,"errors":[],"reason_codes":{}}
    for i,r in enumerate(missing,1):
        state["attempted"]+=1
        try:
            best,errs=coupang_partners_api.best_exact_match(r["name"],max_queries=max_queries,threshold=float(cfg.get("price_match_threshold",0.62)))
            if errs:state["errors"].extend(errs[-1:])
            if best and best.get("price"):
                out[r["id"]]={"site":"쿠팡","price":int(best["price"]),"product_name":best.get("name") or "",
                              "image_path":None,"image_url":best.get("image_url") or "","evidence":None,
                              "url":best.get("url") or "","match":float(best.get("match") or 0),"verified":True,
                              "match_detail":best.get("match_detail") or {},"source":"coupang_partners_api",
                              "captured_at":best.get("captured_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
                              "query_used":best.get("query_used") or "","browser_free":True,"product_id":best.get("product_id") or ""}
                state["verified"]+=1
                state["reason_codes"][str(r["id"])]=best.get("match_detail",{}).get("match_mode") or "MATCH"
            else:state["reason_codes"][str(r["id"])]=("API_ERROR" if errs else "NO_EXACT_PRODUCT")
        except Exception as e:
            state["errors"].append(str(e));state["reason_codes"][str(r["id"])]="API_ERROR";log("쿠팡 Partners API 가격조회 실패: "+str(e))
        if progress and (i==1 or i==len(missing) or i%5==0):
            try:progress(i,max(1,len(missing)),f"쿠팡 API 가격/이미지 {i}/{len(missing)}")
            except Exception:pass
    return out,state


def _toss_api_prefill(rows,cfg,existing=None,progress=None):
    """Fill Toss misses from the authenticated Sharelink product feed.

    A feed hit is accepted only after comparison with the untouched full target
    name.  Therefore a popular but similarly named option cannot silently supply
    the wrong price, capacity or quantity.
    """
    out=dict(existing or {});state={"ready":toss_sharelink_api.ready(),"attempted":0,"verified":0,"errors":[],"reason_codes":{}}
    if not cfg.get("toss_sharelink_api_enabled",True) or not state["ready"]:
        code="API_DISABLED" if not cfg.get("toss_sharelink_api_enabled",True) else "API_CREDENTIALS_MISSING"
        state["reason_codes"]={str(r["id"]):code for r in rows};return out,state
    missing=[r for r in rows if not (out.get(r["id"]) or {}).get("verified") or not (out.get(r["id"]) or {}).get("image_url")]
    if not missing:return out,state
    # Reuse the stronger image-stage resolver: global best-selling plus relevant
    # category feeds.  v7.51 price comparison scanned only the global feed, so a
    # valid API connection still returned no price for most non-best products.
    from . import content_adapter
    for i,r in enumerate(missing,1):
        state["attempted"]+=1
        try:
            hit=content_adapter._toss_api_exact_product(r,cfg,repair_mode=False)
            hs=hit.get("state") or {};state.setdefault("rows_scanned",0);state["rows_scanned"]=max(state["rows_scanned"],int(hs.get("rows_scanned") or 0))
            state["reason_codes"][str(r["id"])]=hs.get("reason_code") or ""
            price=hit.get("price")
            if hit.get("ok") and isinstance(price,(int,float)) and int(price)>0:
                out[r["id"]]={"site":"토스쇼핑","price":int(price),"product_name":hit.get("candidate_name") or "",
                   "image_path":None,"image_url":hit.get("image_url") or "","evidence":None,
                   "url":hit.get("url") or "","match":float(hit.get("match") or 0),"verified":True,
                   "match_detail":hit.get("match_detail") or {},"match_mode":"api_global_plus_category_strict",
                   "source":"toss_sharelink_open_api","browser_free":True,
                   "product_id":hit.get("product_id") or "","captured_at":time.strftime("%Y-%m-%d %H:%M:%S")}
                state["verified"]+=1
            elif hit.get("ok"):
                state["errors"].append(f"{r['name']}: 동일상품은 확인됐지만 API 가격 필드가 비어 있음")
        except Exception as e:
            state["errors"].append(str(e));state["reason_codes"][str(r["id"])]="API_ERROR";log("토스 Sharelink API 가격조회 실패: "+str(e))
        if progress and (i==1 or i==len(missing) or i%10==0):
            try:progress(i,max(1,len(missing)),f"토스 API 동일상품 검증 {i}/{len(missing)}")
            except Exception:pass
    return out,state


def _naver_api_prefill(rows,cfg,existing=None,progress=None):
    """Browser-free NAVER shopping price + representative image."""
    out=dict(existing or {});state={"ready":naver_shopping_api.ready(),"attempted":0,"verified":0,"errors":[],"reason_codes":{}}
    if not cfg.get("naver_shopping_api_enabled",True) or not state["ready"]:
        code="API_DISABLED" if not cfg.get("naver_shopping_api_enabled",True) else "API_CREDENTIALS_MISSING"
        state["reason_codes"]={str(r["id"]):code for r in rows};return out,state
    missing=[r for r in rows if not (out.get(r["id"]) or {}).get("verified") or not (out.get(r["id"]) or {}).get("image_url")]
    for i,r in enumerate(missing,1):
        state["attempted"]+=1
        try:
            best,errs=naver_shopping_api.best_exact_match(r["name"],max_queries=int(cfg.get("naver_shopping_api_query_count",5)),threshold=float(cfg.get("price_match_threshold",0.62)))
            if errs:state["errors"].extend(errs[-1:])
            if best and best.get("price"):
                out[r["id"]]={"site":"네이버쇼핑","price":int(best["price"]),"product_name":best.get("name") or "",
                    "image_path":None,"image_url":best.get("image_url") or "","evidence":None,
                    "url":best.get("url") or "","match":float(best.get("match") or 0),"verified":True,
                    "match_detail":best.get("match_detail") or {},"source":"naver_shopping_search_api",
                    "query_used":best.get("query_used") or "","browser_free":True,
                    "product_id":best.get("product_id") or "","captured_at":best.get("captured_at") or time.strftime("%Y-%m-%d %H:%M:%S")}
                state["verified"]+=1
                state["reason_codes"][str(r["id"])]=best.get("match_detail",{}).get("match_mode") or "MATCH"
            else:state["reason_codes"][str(r["id"])]=("API_ERROR" if any("HTTP" in str(x) or "timed" in str(x).lower() for x in errs) else "NO_EXACT_PRODUCT")
        except Exception as e:
            state["errors"].append(str(e));state["reason_codes"][str(r["id"])]="API_ERROR";log("NAVER 쇼핑 API 가격조회 실패: "+str(e))
        if progress and (i==1 or i==len(missing) or i%10==0):
            try:progress(i,max(1,len(missing)),f"네이버 API 가격/대표이미지 {i}/{len(missing)}")
            except Exception:pass
    return out,state

def create_single_sale(name,records,out,fallback_image=None):
    """When only one marketplace can be verified, render a truthful single-sale card instead of fake comparison."""
    valid=[r for r in records if r.get("verified") and isinstance(r.get("price"),(int,float)) and r.get("price")>0]
    if not valid:return None
    r=min(valid,key=lambda x:x["price"])
    W,H=1400,1000
    canvas=Image.new("RGB",(W,H),(248,249,251));d=ImageDraw.Draw(canvas)
    d.text((70,50),"단독 판매 확인",font=font(34,True),fill=(35,38,43))
    d.multiline_text((70,105),_wrap(d,name,font(46,True),1260,2),font=font(46,True),fill=(15,17,20),spacing=8)
    image_path=r.get("image_path") or fallback_image
    if image_path and Path(image_path).exists():
        canvas.paste(_fit_cover(image_path,(640,520)),(70,275));d=ImageDraw.Draw(canvas)
    else:
        d.rounded_rectangle((70,275,710,795),32,fill=(238,240,243));d.text((390,535),"제품 이미지 확인 필요",font=font(26,True),fill=(125,128,132),anchor="mm")
    d.text((780,310),r.get("site","판매처"),font=font(38,True),fill=(45,48,53))
    d.text((780,390),f'{int(r["price"]):,}원',font=font(72,True),fill=(15,17,20))
    d.multiline_text((780,495),_wrap(d,r.get("product_name") or name,font(25,True),520,4),font=font(25,True),fill=(65,68,73),spacing=7)
    d.text((780,720),"다른 판매처에서 동일 옵션을 확인하지 못해\n가격 비교가 아닌 단독 판매 정보로 표시합니다.",font=font(22,False),fill=(100,103,108),spacing=7)
    checked=time.strftime("%Y.%m.%d %H:%M 기준")
    d.text((70,900),checked,font=font(21,False),fill=(120,123,128))
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);canvas.save(out,"JPEG",quality=96,subsampling=0)
    return str(out)

def _task_for_price(r,site,query,tid,delay,cfg,phase="full"):
    return {"id":tid,"site":site,"query":query,"target_name":r["name"],"mode":"price","limit":30,
            "capture":True,"evdir":str(EVIDENCE/f"{int(r['product_no'] or r['id']):02d}"),"delay_ms":delay,
            "critical_tokens":critical_identity_tokens(r["name"]),"identity_tokens":identity_terms(r["name"]),
            "signature_tokens":signature_identity_tokens(r["name"]),"match_threshold":float(cfg.get("price_match_threshold",0.62)),
            "search_phase":phase}

def _record_from_extension(rr,target,site,cfg,query_used=""):
    rec={"site":site,"price":None,"product_name":"","image_path":rr.get("image_path"),"evidence":rr.get("evidence"),
         "url":"","match":0,"verified":False,"source":"normal_chrome_extension","query_used":query_used}
    sel=rr.get("selected")
    if rr.get("status")=="ok" and sel:
        pname=clean_product_name(sel.get("name",""));candidate_text=sel.get("text") or sel.get("name") or ""
        ok,score,detail=marketplace_product_accept(candidate_text,target,float(cfg.get("price_api_recall_match_threshold",0.48)))
        if ok and is_valid_product_name(pname) and isinstance(sel.get("price"),(int,float)) and sel.get("price")>0:
            rec.update(price=int(sel.get("price")),product_name=pname,url=sel.get("url","") or "",match=score,verified=True,match_detail=detail,
                       image_url=sel.get("image_url","") or "")
        else:rec.update(reason="동일상품/옵션 재검증 실패",match_detail=detail)
    else:rec["reason"]=rr.get("error") or rr.get("status") or "상품 카드 없음"
    return rec

def _collect_site_with_fallback(rows,site,cfg,delay=None,progress=None,prefix="batch",con=None):
    """Collect one marketplace with API/snapshot first and resilient browser recovery.

    v7.57 fixes two live failure modes from v7.56:
    * one Chrome/bridge exception no longer aborts the whole marketplace stage;
    * unresolved products get several progressively reduced queries, while every
      candidate is still validated against the untouched full product name.
    """
    rows=list(rows);out={};fallback_count=0
    api_state=None
    if site=="쿠팡" and rows:
        out,api_state=_coupang_api_prefill(rows,cfg,out,progress)
    elif site=="토스쇼핑" and rows:
        out,api_state=_toss_api_prefill(rows,cfg,out,progress)
    elif site=="네이버쇼핑" and rows:
        out,api_state=_naver_api_prefill(rows,cfg,out,progress)

    snap=_candidate_prefill(con,rows,site,cfg)
    for pid,rec in snap.items():
        if not (out.get(pid) or {}).get("verified"):out[pid]=rec
        elif not (out.get(pid) or {}).get("image_url") and rec.get("image_url"):
            out[pid]["image_url"]=rec.get("image_url");out[pid]["image_enriched_from"]="same_run_snapshot_fallback"
    missing=[r for r in rows if not (out.get(r["id"]) or {}).get("verified")]

    if not cfg.get("price_allow_automatic_browser_refresh",False):
        for r in missing:
            old=out.get(r["id"]) or {"site":site,"price":None,"verified":False}
            old.setdefault("source","same_run_snapshot_only");old["browser_free"]=True
            if api_state:
                old["api_diagnostic"]={"ready":api_state.get("ready"),"reason_code":(api_state.get("reason_codes") or {}).get(str(r["id"]),""),
                                       "errors":(api_state.get("errors") or [])[-3:]}
            old["reason"]=("쿠팡 API/동일 실행 수집 스냅샷에서 동일 옵션을 찾지 못함" if site=="쿠팡" else
                           "토스 API/동일 실행 수집 스냅샷에서 동일 옵션을 찾지 못함 · 자동 재검색 비활성" if site=="토스쇼핑" else
                           "네이버 쇼핑 API/동일 실행 수집 스냅샷에서 동일 옵션을 찾지 못함 · 자동 재검색 비활성")
            out[r["id"]]=old
        return out,0

    if delay is None:
        sec=float(cfg.get("naver_price_delay_sec",8.0) if site=="네이버쇼핑" else cfg.get("chrome_task_delay_sec",4.0))
        delay=int(sec*1000)

    blocked=False;browser_attempted=set();browser_returned=set();browser_errors=[]
    def api_diag(r):
        return {"ready":bool((api_state or {}).get("ready")),
                "reason_code":((api_state or {}).get("reason_codes") or {}).get(str(r["id"]),""),
                "errors":((api_state or {}).get("errors") or [])[-3:]}
    def consume(tasks,meta,is_fallback=False):
        nonlocal blocked,out
        if not tasks:return
        browser_attempted.update(r["id"] for r,_ in meta.values())
        try:
            results=chrome_collector.collect(tasks,progress=progress,timeout_sec=max(480,len(tasks)*24))
        except Exception as e:
            err=f"{site} Chrome 보완 수집 예외: {e}"
            browser_errors.append(err);log(err)
            for r,q in meta.values():
                old=out.get(r["id"]) or {"site":site,"price":None,"verified":False,"source":"api_then_browser_fallback"}
                old["browser_attempted"]=True;old["browser_status"]="collector_exception";old["browser_error"]=str(e);old["api_diagnostic"]=api_diag(r)
                old["reason"]="Chrome 확장/브리지 수집 예외 · 다음 축약 검색으로 자동 복구 시도"
                out[r["id"]]=old
            return
        for rr in results or []:
            tid=rr.get("_task_id");pair=meta.get(tid)
            if not pair:continue
            r,q=pair;browser_returned.add(r["id"])
            if rr.get("status") in ("blocked","skipped_blocked") and site=="네이버쇼핑":blocked=True
            new=_record_from_extension(rr,r["name"],site,cfg,q);old=out.get(r["id"]) or {}
            new["browser_status"]=rr.get("status") or "unknown";new["api_diagnostic"]=api_diag(r)
            if rr.get("diagnostic"):new["browser_diagnostic"]=rr.get("diagnostic")
            if is_fallback:new["fallback_from_fullname"]=True
            if new.get("verified") or float(new.get("match") or 0)>float(old.get("match") or 0) or not old:
                out[r["id"]]=new

    # Site-specific recall depth. Toss Sharelink has no free-text official API,
    # so it gets one extra reduced-query pass. Every pass retains full-name
    # validation through target_name/critical tokens.
    key={"토스쇼핑":"toss_price_browser_core_query_count","네이버쇼핑":"naver_price_browser_core_query_count","쿠팡":"coupang_price_browser_core_query_count"}.get(site,"price_browser_core_query_count")
    default_count={"토스쇼핑":3,"네이버쇼핑":2,"쿠팡":2}.get(site,2)
    qcount=max(1,int(cfg.get(key,default_count)))
    for qi in range(qcount):
        if blocked:break
        current=[r for r in rows if not (out.get(r["id"]) or {}).get("verified")]
        if not current:break
        tasks=[];meta={}
        for r in current:
            qs=core_search_queries(r["name"],qcount)
            if qi>=len(qs):continue
            q=qs[qi];tid=f"{prefix}-core{qi+1}-{site}-{r['id']}"
            phase="core_keyword_primary_fullname_validation" if qi==0 else f"core_keyword_fallback_{qi+1}_fullname_validation"
            tasks.append(_task_for_price(r,site,q,tid,delay,cfg,phase));meta[tid]=(r,q)
            if qi>0:fallback_count+=1
        consume(tasks,meta,qi>0)

    if not blocked and cfg.get("price_fullname_fallback_enabled",True):
        current=[r for r in rows if not (out.get(r["id"]) or {}).get("verified")]
        fb=[];fbmeta={}
        for r in current:
            tid=f"{prefix}-full-{site}-{r['id']}"
            fb.append(_task_for_price(r,site,r["name"],tid,delay,cfg,"full_name_fallback"));fbmeta[tid]=(r,r["name"]);fallback_count+=1
        consume(fb,fbmeta,True)

    if blocked:
        for r in rows:
            if not (out.get(r["id"]) or {}).get("verified"):
                old=out.get(r["id"]) or {"site":site,"price":None,"verified":False}
                old["reason"]="네이버 접근 제한 감지 — 추가 검색을 자동 중단했습니다. 같은 실행에서 재시도하지 않습니다."
                old["access_restriction"]=True;out[r["id"]]=old
    for r in rows:
        if (out.get(r["id"]) or {}).get("verified"):continue
        old=out.get(r["id"]) or {"site":site,"price":None,"verified":False,"source":"api_then_browser_fallback"}
        old.setdefault("api_diagnostic",api_diag(r));old["browser_attempted"]=r["id"] in browser_attempted
        if browser_errors:old.setdefault("browser_errors",browser_errors[-3:])
        if r["id"] in browser_attempted and r["id"] not in browser_returned and not old.get("browser_error"):
            old["reason"]="공식 API 미확인 후 Chrome 보완을 요청했지만 수집 응답이 없습니다. Chrome 확장/브리지 연결을 확인하세요."
            old["browser_status"]="no_response"
        elif not old.get("reason") or old.get("reason","").endswith("자동 복구 시도"):
            code=(old.get("api_diagnostic") or {}).get("reason_code") or ""
            label={"API_CREDENTIALS_MISSING":"공식 API 키 미설정","API_DISABLED":"공식 API 비활성",
                   "API_ERROR":"공식 API 오류","NO_EXACT_PRODUCT":"API 후보 중 동일상품/옵션 없음"}.get(code,"공식 API 동일상품 미확인")
            old["reason"]=label+" · Chrome 다중 핵심키워드/풀네임 보완에서도 동일상품 가격을 확인하지 못함"
        out[r["id"]]=old
    return out,fallback_count

def _read_existing_image(r):
    for k in ("image1","image2","image3"):
        try:
            p=r[k]
            if p and Path(p).exists():return p
        except Exception:pass
    return None

def _backfill_product_images(con,r,records):
    """Use verified marketplace card crops / Android product crop to repair missing blog photos."""
    want=int(settings().get("image_exact_count",3));existing=[]
    for k in ("image1","image2","image3"):
        try:
            x=r[k]
            if x and Path(x).exists():existing.append(str(x))
        except Exception:pass
    seen=set(existing);sources=[]
    for rec in records:
        # Blog product photos are Coupang-only in v7.38. Naver/Toss images may
        # still be retained as price evidence, but are never copied into 1/2/3.jpg.
        if rec.get("site")!="쿠팡":continue
        p=rec.get("image_path")
        if p and Path(p).exists() and p not in seen:
            seen.add(p);sources.append(p)
    if len(existing)>=want or not sources:return
    pdir=Path(r["post_dir"]) if r["post_dir"] else POSTS/f"{int(r['product_no'] or r['id']):02d}_{re.sub(r'[^가-힣A-Za-z0-9_-]','_',r['name'])[:40]}"
    pdir.mkdir(parents=True,exist_ok=True)
    hashes=[]
    for x in existing:
        try:hashes.append(_image_dhash(x))
        except Exception:pass
    for src in sources:
        if len(existing)>=want:break
        try:
            probe=Image.open(src)
            min_dim=int(settings().get("image_min_dimension",180))
            if probe.width<min_dim or probe.height<min_dim:continue
            dh=_image_dhash(src)
            if any(_hash_distance(dh,h)<6 for h in hashes):continue
            dst=pdir/f"{len(existing)+1}.jpg"
            im=probe.convert("RGB");im.thumbnail((1600,1600));im.save(dst,"JPEG",quality=94)
            hashes.append(dh);existing.append(str(dst))
        except Exception:pass
    vals=existing+[None,None,None]
    # Preserve content status but repair the visible photo count after the price stage.
    new_status=("콘텐츠완료" if len(existing)>=want else f"사진부족 {len(existing)}/{want}") if (r["title"] or r["body"]) else ("사진3장검증" if len(existing)>=want else f"사진부족 {len(existing)}/{want}")
    img_ev=None
    try:
        old_ev=r["image_evidence_json"]
        obj=json.loads(Path(old_ev).read_text(encoding="utf-8")) if old_ev and Path(old_ev).exists() else {"target":r["name"]}
        obj["verified_count"]=len(existing);obj["verified"]=len(existing)>=want;obj["price_stage_backfill"]=sources;obj["checked_at"]=time.strftime("%Y-%m-%d %H:%M:%S")
        evp=pdir/"image_evidence.json";evp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8");img_ev=str(evp)
    except Exception:img_ev=r["image_evidence_json"] if "image_evidence_json" in r.keys() else None
    con.execute("UPDATE products SET image1=?,image2=?,image3=?,image_verified_count=?,image_evidence_json=?,status=?,post_dir=?,updated_at=datetime('now','localtime') WHERE id=?",
                (vals[0],vals[1],vals[2],len(existing),img_ev,new_status,str(pdir),r["id"]))
    # Keep post.json image blocks in sync if content was already composed.
    try:
        pj=pdir/"post.json"
        if pj.exists():
            obj=json.loads(pj.read_text(encoding="utf-8"));blocks=obj.get("blocks") or []
            old=[b for b in blocks if b.get("type")=="image"]
            for i,b in enumerate(old[:len(existing)]):b["file"]=Path(existing[i]).name
            if not old:
                obj["blocks"]=[{"type":"image","file":Path(x).name} for x in existing]+blocks
            elif len(old)<len(existing):
                # Price-stage backfill may add image2/image3 after content was
                # composed with only one photo. Keep post.json and the DB in
                # sync so blog upload really uses all verified images.
                missing=[{"type":"image","file":Path(x).name} for x in existing[len(old):]]
                insert_at=next((i for i,b in enumerate(blocks)
                                if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
                obj["blocks"]=blocks[:insert_at]+missing+blocks[insert_at:]
            pj.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:pass

def capture_same_card(driver, card, evdir, site):
    """One evidence transaction: the SAME DOM card supplies name, price, image and screenshot."""
    card_shot=evdir/f"{site}_동일카드_상품명_사진_가격.png"
    try: card["element"].screenshot(str(card_shot))
    except: driver.save_screenshot(str(card_shot))
    image_path=None
    try:
        img=card["element"].find_element("css selector","img")
        if img.is_displayed() and img.size["width"]>=80 and img.size["height"]>=80:
            image_path=evdir/f"{site}_제품사진.png"
            img.screenshot(str(image_path))
    except: pass
    return str(card_shot), str(image_path) if image_path else None

def _run_selenium(context=None,progress=None):
    init_db_fast()
    con=db_connect(row_factory=True)
    rows=con.execute("SELECT * FROM products WHERE status NOT LIKE '추천제외:%' AND COALESCE(already_posted,0)=0 ORDER BY product_no,id").fetchall()
    skipped=[skipped_price(int(r["id"])) for r in rows if is_wala_product(r)]
    rows=[r for r in rows if not is_wala_product(r)]
    if not rows:
        con.close()
        return {"processed":0,"skipped":skipped,"stage_ok":True,"soft_pending":False,"message":SOURCE_REASON}
    drivers={}
    prog=ProgressThrottle(progress)
    try:
        # Dedicated persistent profiles reduce repeated fresh-session churn.
        drivers["쿠팡"]=driver_start(False,False,profile_key="coupang")
        drivers["네이버쇼핑"]=driver_start(False,False,profile_key="naver_shopping")
        drivers["토스쇼핑"]=driver_start(False,False,profile_key="toss_sharelink")
        with StageTimer("3사 가격·제품사진 전체",f"products={len(rows)}"):
            for idx,r in enumerate(rows):
                with StageTimer("가격 제품",r["name"][:35]):
                    records=[]
                    evdir=EVIDENCE/f"{int(r['product_no'] or r['id']):02d}"
                    evdir.mkdir(parents=True,exist_ok=True)

                    # Coupang + Naver: normal visible search via home/search field.
                    for site in ["쿠팡","네이버쇼핑"]:
                        drv=drivers[site]
                        try:
                            market_safe.search(drv,site,r["name"])
                        except RuntimeError as e:
                            records.append({"site":site,"price":None,"product_name":"","image_path":None,
                                            "match":0,"reason":str(e),"source":"safe_pc"})
                            continue
                        cards=extract_cards(drv,25,site)
                        scored=[(strict_product_match(c["text"],r["name"])[0],c) for c in cards]
                        scored=[x for x in scored if x[0]>=0.55]
                        scored.sort(key=lambda x:(-x[0],x[1]["price"]))
                        if not scored:
                            try:drv.save_screenshot(str(evdir/f"{site}_동일상품없음.png"))
                            except:pass
                            records.append({"site":site,"price":None,"product_name":"","image_path":None,
                                            "match":0,"reason":"동일상품 카드 검증 실패","source":"safe_pc"})
                            continue
                        match,c=scored[0]
                        evidence,image_path=capture_same_card(drv,c,evdir,site)
                        records.append({"site":site,"price":c["price"],"product_name":c["name"],
                                        "image_path":image_path,"evidence":evidence,
                                        "url":c.get("url",""),"match":match,"source":"safe_pc"})

                    # Toss Sharelink PC: login once, search products, price/photo/share URL from same session.
                    toss_rec=toss_sharelink_pc.fetch(drivers["토스쇼핑"],r["name"],evdir)
                    records.append(toss_rec)

                    prices={x["site"]:x.get("price") for x in records}
                    out=evdir/"가격비교_제품사진포함.jpg"
                    cmp=create_compare(r["name"],records,out)
                    (evdir/"evidence.json").write_text(json.dumps({
                        "target":r["name"],"identity_terms":identity_terms(r["name"]),
                        "checked_at":time.strftime("%Y-%m-%d %H:%M:%S"),
                        "records":records
                    },ensure_ascii=False,indent=2),encoding="utf-8")
                    con.execute("""UPDATE products SET price_coupang=?,price_naver=?,price_toss=?,
                      price_checked_at=datetime('now','localtime'),price_compare_image=?,updated_at=datetime('now','localtime') WHERE id=?""",
                      (prices.get("쿠팡"),prices.get("네이버쇼핑"),prices.get("토스쇼핑"),cmp,r["id"]))
                    con.commit()
                    prog(idx+1,len(rows),f"3사 가격+사진 검증: {r['name'][:30]}")
        prog(len(rows),len(rows),"3사 가격 검증 완료",force=True)
    finally:
        for d in drivers.values():
            try:d.quit()
            except:pass
        con.close()
    return {"processed":len(rows),"skipped":skipped,"stage_ok":True,"soft_pending":False,
            "message":f"3사 가격 처리 {len(rows)}건 · 왈라랜드 제외 {len(skipped)}건"}


def _export_price_summary(con):
    import csv
    out=OUTPUTS/"price_comparison_summary.csv";out.parent.mkdir(parents=True,exist_ok=True)
    rows=con.execute("""SELECT product_no,name,price_coupang,price_naver,price_toss,price_verified_sites,
                        price_image_verified_sites,price_checked_at,price_compare_image,price_evidence_json
                        FROM products ORDER BY product_no,id""").fetchall()
    with out.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["TOP","상품명","쿠팡","네이버","토스","가격검증사이트수","가격+이미지동시검증수","검증시각","3사비교이미지","증거JSON"])
        for r in rows:w.writerow(list(r))
    return str(out)


def _finalize_records(r,records,cfg):
    """Make price and image evidence belong to the same exact-market record."""
    evdir=EVIDENCE/f"{int(r['product_no'] or r['id']):02d}";evdir.mkdir(parents=True,exist_ok=True)
    out=[]
    for rec in records:
        rec=dict(rec)
        if rec.get("verified") and rec.get("price"):
            _download_record_image(rec,evdir)
        else:
            rec["price_image_verified"]=False
        # Never borrow a generic blog image and pretend it is marketplace evidence.
        rec.pop("presentation_image_fallback",None)
        out.append(rec)
    verified=sum(1 for x in out if x.get("verified") and x.get("price"))
    coupled=sum(1 for x in out if x.get("verified") and x.get("price") and x.get("image_path") and Path(x["image_path"]).exists())
    return out,verified,coupled,evdir


def _save_product_price(con,r,records,cfg,site_order,extra=None):
    records=[_candidate_image_enrich(con,r,dict(x),cfg) for x in records]
    records,verified,coupled,evdir=_finalize_records(r,records,cfg)
    prices={x["site"]:x.get("price") for x in records if x.get("verified") and x.get("price")}
    cmp=create_compare(r["name"],records,evdir/"가격비교_제품사진포함.jpg")
    # v7.40: price verification never mutates blog photos. Image stage is separate.
    obj={"target":r["name"],"identity_terms":identity_terms(r["name"]),"critical_tokens":critical_identity_tokens(r["name"]),
         "signature_tokens":signature_identity_tokens(r["name"]),"match_threshold":float(cfg.get("price_match_threshold",0.62)),
         "search_strategy":"three_official_apis_then_missing_only_browser_v7_56",
         "site_order":site_order,"image_mode":"three_site_truthful_compare","verified_sites":verified,
         "price_image_verified_sites":coupled,"checked_at":time.strftime("%Y-%m-%d %H:%M:%S"),"records":records}
    if extra:obj.update(extra)
    ep=evdir/"evidence.json";ep.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    con.execute("""UPDATE products SET price_coupang=?,price_naver=?,price_toss=?,price_checked_at=datetime('now','localtime'),
      price_compare_image=?,price_verified_sites=?,price_image_verified_sites=?,price_evidence_json=?,updated_at=datetime('now','localtime') WHERE id=?""",
      (prices.get("쿠팡"),prices.get("네이버쇼핑"),prices.get("토스쇼핑"),cmp,verified,coupled,str(ep),r["id"]))
    return {"verified_sites":verified,"price_image_verified_sites":coupled,"compare_image":cmp,"evidence":str(ep),"records":records}


def _repair_content_images_after_price(product_ids,progress=None):
    """Price evidence contains exact product URLs/images; retry content galleries afterwards."""
    if not settings().get("price_post_image_repair",True):return {"attempted":0,"repaired":0,"remaining":[]}
    from . import content_adapter
    init_db_fast();con=db_connect(row_factory=True)
    try:
        want=int(settings().get("image_exact_count",3))
        rows=con.execute("SELECT id,name,image_verified_count FROM products WHERE id IN (%s) ORDER BY product_no,id" % ",".join("?"*len(product_ids)),tuple(product_ids)).fetchall() if product_ids else []
    finally:con.close()
    need=[r for r in rows if int(r["image_verified_count"] or 0)<want]
    repaired=0;remaining=[]
    for i,r in enumerate(need):
        try:
            if progress:progress(i,max(1,len(need)),f"가격 증거 기반 이미지 3장 재수집: {r['name'][:32]}")
            z=content_adapter.capture_product_images(r["id"])
            if int(z.get("verified_count") or 0)>=want:repaired+=1
            else:remaining.append({"id":r["id"],"name":r["name"],"verified_count":z.get("verified_count",0)})
        except Exception as e:
            remaining.append({"id":r["id"],"name":r["name"],"verified_count":0,"error":str(e)})
    return {"attempted":len(need),"repaired":repaired,"remaining":remaining}


def verify_product(product_id,progress=None):
    """Verify one product: no fake image substitution, exact price+image evidence."""
    init_db_fast();cfg=settings();con=db_connect(row_factory=True)
    try:
        r=con.execute("SELECT * FROM products WHERE id=?",(int(product_id),)).fetchone()
        if not r:raise RuntimeError("선택 상품을 찾지 못했습니다.")
        if is_wala_product(r):return skipped_price(int(r["id"]))
        records_by={}
        for site in ["네이버쇼핑","쿠팡","토스쇼핑"]:
            got,_=_collect_site_with_fallback([r],site,cfg,None,progress,prefix="one",con=con)
            records_by[site]=got.get(r["id"],{"site":site,"price":None,"verified":False,"reason":"검색 결과 없음"})
        toss=records_by.get("토스쇼핑") or {}
        if cfg.get("price_allow_automatic_toss_app_refresh",False) and (not toss.get("verified") or not toss.get("image_path")):
            h=toss_mobile_adapter.health()
            if h.get("ready"):
                d=None
                try:
                    d=toss_mobile_adapter.open_session();evdir=EVIDENCE/f"{int(r['product_no'] or r['id']):02d}";evdir.mkdir(parents=True,exist_ok=True)
                    ar=toss_mobile_adapter.fetch_product_with_fallback(d,r["name"],evdir)
                    if ar.get("price"):
                        ok,score,detail=strict_product_accept(ar.get("product_name") or "",r["name"],float(cfg.get("price_match_threshold",0.62)))
                        ar.update(site="토스쇼핑",verified=bool(ok),match=score,match_detail=detail,source="Android/Appium")
                    if ar.get("verified"):records_by["토스쇼핑"]=ar
                    elif toss.get("verified") and ar.get("image_path"):
                        toss["image_path"]=ar.get("image_path");toss["android_image_fallback"]=True;records_by["토스쇼핑"]=toss
                finally:
                    if d:toss_mobile_adapter.close_session(d)
        records=[records_by.get(s,{"site":s,"price":None,"verified":False}) for s in ["쿠팡","네이버쇼핑","토스쇼핑"]]
        saved=_save_product_price(con,r,records,cfg,["네이버쇼핑","쿠팡","토스쇼핑"])
        con.commit();_export_price_summary(con)
        repair=_repair_content_images_after_price([r["id"]],progress)
        comparison_ready=saved["verified_sites"]>=int(cfg.get("price_require_verified_sites",3)) and saved["price_image_verified_sites"]>=int(cfg.get("price_require_image_with_price_sites",3))
        saved.update({"product_id":r["id"],"image_repair":repair,"lookup_completed":True,
                      "comparison_ready":comparison_ready,"stage_ok":True,"soft_pending":not comparison_ready})
        return saved
    finally:con.close()


def verify_product_live_browser(product_id,progress=None):
    """Explicit, user-triggered live refresh for one product only.

    This is NOT used by batch automation. It may open Naver/Toss search pages once
    for the selected product and therefore can still be rate-limited by the sites.
    No attempt is made to bypass access controls.
    """
    init_db_fast();cfg=dict(settings())
    cfg["price_allow_automatic_browser_refresh"]=True
    cfg["price_fallback_query_count"]=0;cfg["naver_price_fallback_query_count"]=0
    cfg["price_allow_automatic_toss_app_refresh"]=False
    con=db_connect(row_factory=True)
    try:
        r=con.execute("SELECT * FROM products WHERE id=?",(int(product_id),)).fetchone()
        if not r:raise RuntimeError("선택 상품을 찾지 못했습니다.")
        if is_wala_product(r):return skipped_price(int(r["id"]))
        records_by={}
        # Coupang will still use API first if configured; only a miss can reach browser.
        for site in ["쿠팡","네이버쇼핑","토스쇼핑"]:
            got,_=_collect_site_with_fallback([r],site,cfg,None,progress,prefix="manual-live",con=con)
            records_by[site]=got.get(r["id"],{"site":site,"price":None,"verified":False,"reason":"검색 결과 없음"})
        records=[records_by[s] for s in ["쿠팡","네이버쇼핑","토스쇼핑"]]
        saved=_save_product_price(con,r,records,cfg,["쿠팡","네이버쇼핑","토스쇼핑"],{"manual_live_browser":True})
        con.commit();_export_price_summary(con)
        saved["product_id"]=r["id"]
        return saved
    finally:con.close()


def run(context=None,progress=None):
    cfg=settings()
    # v7.38 default price policy is always snapshot/API-first.  The old Selenium
    # whole-batch price collector is retained only behind an explicit opt-in so
    # changing collection_mode cannot accidentally re-open hundreds of pages.
    if cfg.get("collection_mode","chrome_extension")!="chrome_extension" and cfg.get("price_allow_legacy_selenium_mode",False):
        return _run_selenium(context,progress)
    init_db_fast();con=db_connect(row_factory=True)
    rows=con.execute("SELECT * FROM products WHERE COALESCE(already_posted,0)=0 ORDER BY product_no,id").fetchall()
    skipped=[skipped_price(int(r["id"])) for r in rows if is_wala_product(r)]
    rows=[r for r in rows if not is_wala_product(r)]
    if not rows:
        con.close()
        return {"processed":0,"skipped":skipped,"price_complete":0,"price_incomplete":[],
                "search_order":[],"fallback_queries":0,"stage_ok":True,"soft_pending":False,"message":SOURCE_REASON}
    site_order=["네이버쇼핑","쿠팡","토스쇼핑"]
    grouped={r["id"]:{} for r in rows};fallback_total=0

    # Site-major, but skip already-collected same-run evidence. Naver is first so
    # any access restriction can be detected and stopped before repeated retries.
    for site in site_order:
        try:
            site_records,fb=_collect_site_with_fallback(rows,site,cfg,None,progress,prefix="batch",con=con)
        except Exception as e:
            log(f"{site} 가격 단계 전체 예외 격리: {e}")
            site_records={r["id"]:{"site":site,"price":None,"verified":False,"source":"site_exception_isolated",
                                      "reason":"판매처 가격 단계 예외가 발생했지만 다른 2개 판매처는 계속 조회함",
                                      "browser_error":str(e)} for r in rows};fb=0
        fallback_total+=fb
        for pid,rec in site_records.items():grouped.setdefault(pid,{})[site]=rec

    # Android Toss fallback: one Appium session for the whole batch.
    android_driver=None;android_state={"attempted":False,"ready":False,"used":0,"error":""}
    try:
        need_android=[r for r in rows if not (grouped.get(r["id"],{}).get("토스쇼핑") or {}).get("verified") or not (grouped.get(r["id"],{}).get("토스쇼핑") or {}).get("image_path")]
        if need_android and cfg.get("price_allow_automatic_toss_app_refresh",False):
            android_state["attempted"]=True;h=toss_mobile_adapter.health();android_state["health"]=h
            if h.get("ready"):
                android_driver=toss_mobile_adapter.open_session();android_state["ready"]=True
                for r in need_android:
                    evdir=EVIDENCE/f"{int(r['product_no'] or r['id']):02d}";evdir.mkdir(parents=True,exist_ok=True)
                    try:
                        ar=toss_mobile_adapter.fetch_product_with_fallback(android_driver,r["name"],evdir)
                        if ar.get("price"):
                            ok,score,detail=strict_product_accept(ar.get("product_name") or "",r["name"],float(cfg.get("price_match_threshold",0.62)))
                            ar.update(site="토스쇼핑",verified=bool(ok),match=score,match_detail=detail,source="Android/Appium")
                        else:ar.update(site="토스쇼핑",verified=False,source="Android/Appium")
                        old=grouped.setdefault(r["id"],{}).get("토스쇼핑") or {}
                        if ar.get("verified"):
                            if not ar.get("image_path") and old.get("image_path"):ar["image_path"]=old.get("image_path")
                            grouped[r["id"]]["토스쇼핑"]=ar;android_state["used"]+=1
                        elif old.get("verified") and ar.get("image_path"):
                            old["image_path"]=ar.get("image_path");old["android_image_fallback"]=True;grouped[r["id"]]["토스쇼핑"]=old;android_state["used"]+=1
                    except Exception as e:log("Android Toss fallback 실패: "+str(e))
            else:android_state["error"]=h.get("message","")
    except Exception as e:
        android_state["error"]=str(e);log("Android Toss batch fallback 초기화 실패: "+str(e))
    finally:
        if android_driver:toss_mobile_adapter.close_session(android_driver)

    outcomes=[]
    try:
        for r in rows:
            by=grouped.get(r["id"],{})
            records=[by.get(s,{"site":s,"price":None,"verified":False,"reason":"검색 결과 없음"}) for s in ["쿠팡","네이버쇼핑","토스쇼핑"]]
            saved=_save_product_price(con,r,records,cfg,site_order,{"android_toss":android_state})
            outcomes.append({"id":r["id"],"name":r["name"],**{k:saved[k] for k in ("verified_sites","price_image_verified_sites")}})
        con.commit();_export_price_summary(con)
    finally:con.close()

    repair={"attempted":0,"repaired":0,"remaining":[],"disabled":"v7.40 별도 이미지 단계 사용"}
    req_price=int(cfg.get("price_require_verified_sites",3));req_coupled=int(cfg.get("price_require_image_with_price_sites",3))
    incomplete=[x for x in outcomes if x["verified_sites"]<req_price or x["price_image_verified_sites"]<req_coupled]
    # A marketplace can legitimately have no matching listing. The batch has
    # still completed all three lookups; do not block later image/QC stages.
    stage_ok=True
    # Human-readable per-site diagnostics for products that did not reach 3/3.
    try:
        import csv
        dp=OUTPUTS/"price_lookup_diagnostic.csv";dp.parent.mkdir(parents=True,exist_ok=True)
        with dp.open("w",encoding="utf-8-sig",newline="") as f:
            fields=["TOP","상품명","판매처","가격","검증","대표이미지","원인","소스","검색어","브라우저상태","브라우저오류","API진단","매칭상세"]
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for r in rows:
                by=grouped.get(r["id"],{})
                for site in ("쿠팡","네이버쇼핑","토스쇼핑"):
                    rec=by.get(site) or {}
                    w.writerow({"TOP":r["product_no"] or r["id"],"상품명":r["name"],"판매처":site,"가격":rec.get("price") or "",
                                "검증":bool(rec.get("verified")),"대표이미지":rec.get("image_url") or rec.get("image_path") or "",
                                "원인":rec.get("reason") or "","소스":rec.get("source") or "","검색어":rec.get("query_used") or "",
                                "브라우저상태":rec.get("browser_status") or "","브라우저오류":rec.get("browser_error") or "",
                                "API진단":json.dumps(rec.get("api_diagnostic") or {},ensure_ascii=False),
                                "매칭상세":json.dumps(rec.get("match_detail") or {},ensure_ascii=False)})
    except Exception as e:log("가격 진단 CSV 저장 실패: "+str(e))
    return {"processed":len(rows),"skipped":skipped,"android_toss":android_state,"search_order":site_order,"fallback_queries":fallback_total,
            "price_complete":len(rows)-len(incomplete),"price_incomplete":incomplete,"image_repair":repair,
            "stage_ok":stage_ok,"soft_pending":True if incomplete else False,
            "message":("가격+동일상품 이미지 3사 검증 완료" if not incomplete else f"3사 조회 완료 · 3사 모두 동일상품 확인 {len(rows)-len(incomplete)}/{len(rows)} · 미판매/미확인 {len(incomplete)}건은 비교표에 그대로 표시")}
