# -*- coding: utf-8 -*-
"""NAVER API HUB Image Search adapter for strict same-product photos.

v8.08.46
- Current endpoint: https://naverapihub.apigw.ntruss.com/search/v1/image
- Current headers: X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY
- Existing credential filename is preserved so upgrades can migrate the user's key.
"""
from pathlib import Path
import html, json, re, time, urllib.parse, urllib.request, urllib.error
from .common import DATA, settings, strict_product_accept, marketplace_product_accept, identity_terms, critical_identity_tokens, clean_listing_title_noise

CREDENTIALS=DATA/"naver_image_api_credentials.json"
HUB_BASE="https://naverapihub.apigw.ntruss.com"
IMAGE_ENDPOINT=HUB_BASE+"/search/v1/image"

def _creds():
    cfg=settings();obj={}
    try:obj=json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except Exception:pass
    cid=str(cfg.get("naver_api_hub_client_id") or cfg.get("naver_image_client_id") or obj.get("client_id") or "").strip()
    sec=str(cfg.get("naver_api_hub_client_secret") or cfg.get("naver_image_client_secret") or obj.get("client_secret") or "").strip()
    return cid,sec

def ready():
    a,b=_creds();return bool(a and b)

def health():
    return {"ready":ready(),"name":"NAVER API HUB 이미지 검색","endpoint":IMAGE_ENDPOINT,
            "message":"READY · NAVER API HUB 이미지 검색" if ready() else "Client ID/Secret 미설정 · 92_NAVER_IMAGE_API_SETUP.cmd 실행"}

def _clean_title(s):
    s=html.unescape(re.sub(r"<[^>]+>"," ",str(s or "")))
    return re.sub(r"\s+"," ",s).strip()

def query_variants(target,max_count=5):
    """High-recall queries; exactness is enforced after retrieval.

    Long marketplace titles often contain seller/promotional tail words that NAVER
    Image documents omit.  Search the cleaned identity in several lengths, then
    validate every result against the untouched target + hard model/count tokens.
    """
    raw=" ".join(str(target or "").split());clean=" ".join(clean_listing_title_noise(raw).split());out=[]
    def add(x):
        x=" ".join(str(x or "").split()).strip()
        if x and x.casefold() not in {q.casefold() for q in out}:out.append(x)
    add(clean[:100] or raw[:100])
    terms=identity_terms(clean or raw);critical=critical_identity_tokens(raw);models=model_variant_tokens(raw)
    if terms:add(" ".join(terms[:7]+critical[:2]+models[:1]))
    if len(terms)>4:add(" ".join(terms[:5]+critical[:2]+models[:1]))
    if len(terms)>2:add(" ".join(terms[:3]+critical[:2]+models[:1]))
    if terms:add(" ".join(terms[:2]+models[:2]+critical[:2]))
    return out[:max(1,int(max_count))]


def model_variant_tokens(target):
    """Hard model tokens, including spaced forms such as `Y 09` -> `Y09`."""
    raw=str(target or "").upper();out=[]
    def add(tok):
        compact=re.sub(r"[^A-Z0-9]","",str(tok or "").upper())
        if len(compact)>=2 and re.search(r"[A-Z]",compact) and re.search(r"\d",compact) and compact not in out:out.append(compact)
    for a,b in re.findall(r"\b([A-Z]{1,6})[\s._-]+(\d{1,6}[A-Z]?)\b",raw):add(a+b)
    for a,b in re.findall(r"\b(\d{1,6})[\s._-]+([A-Z]{1,6})\b",raw):add(a+b)
    for tok in re.findall(r"[A-Z0-9][A-Z0-9._-]{1,24}",raw):add(tok)
    return out[:8]

def model_variant_match(candidate,target):
    required=model_variant_tokens(target)
    if not required:return True,[]
    compact=re.sub(r"[^A-Z0-9]","",str(candidate or "").upper())
    missing=[x for x in required if x not in compact]
    return not missing,missing

def search(query,display=50,start=1,sort="sim",filter_value="large"):
    cid,sec=_creds()
    if not cid or not sec:raise RuntimeError("NAVER API HUB Client ID/Secret이 설정되지 않았습니다.")
    params={"query":query,"display":max(1,min(100,int(display))),"start":max(1,min(1000,int(start))),"sort":sort,"filter":filter_value,"format":"json"}
    req=urllib.request.Request(IMAGE_ENDPOINT+"?"+urllib.parse.urlencode(params),headers={
        "X-NCP-APIGW-API-KEY-ID":cid,
        "X-NCP-APIGW-API-KEY":sec,
        "User-Agent":"NBlogStudio/8.08.46 NAVER-Image-Exact",
        "Accept":"application/json",
    })
    try:
        with urllib.request.urlopen(req,timeout=float(settings().get("naver_image_api_timeout_sec",18))) as r:
            obj=json.loads(r.read(5*1024*1024).decode("utf-8","replace"))
    except urllib.error.HTTPError as exc:
        try:body=exc.read(1200).decode("utf-8","replace")
        except Exception:body=""
        raise RuntimeError(f"NAVER API HUB HTTP {exc.code}: {body[:500] or exc.reason}") from exc
    out=[]
    for x in obj.get("items") or []:
        try:w=int(x.get("sizewidth") or 0);h=int(x.get("sizeheight") or 0)
        except Exception:w=h=0
        link=str(x.get("link") or "").strip();thumb=str(x.get("thumbnail") or "").strip()
        if link.startswith("//"):link="https:"+link
        if thumb.startswith("//"):thumb="https:"+thumb
        out.append({"name":_clean_title(x.get("title")),"image_url":link,"thumbnail":thumb,"width":w,"height":h,
                    "source":"naver_api_hub_image","captured_at":time.strftime("%Y-%m-%d %H:%M:%S")})
    return out

def _title_accept(candidate,target,threshold=0.72):
    """Image-title identity gate tuned for marketplace listing noise.

    Full strict match wins.  A balanced fallback is allowed only when all hard
    capacity/count/model tokens still match.  This recovers documents that omit
    seller-tail words without allowing sibling models/options.
    """
    strict_threshold=max(0.62,min(float(threshold),0.68))
    ok,score,detail=strict_product_accept(candidate,target,strict_threshold)
    mode="strict"
    if not ok:
        fallback=float(settings().get("naver_image_balanced_match_threshold",0.48))
        ok,score,detail=marketplace_product_accept(candidate,target,fallback);mode="balanced"
    mok,model_missing=model_variant_match(candidate,target)
    critical=critical_identity_tokens(target)
    terms=identity_terms(clean_listing_title_noise(target));low=str(candidate or "").lower()
    hits=[t for t in terms[:8] if t.lower() in low]
    anchor_stop={"당일발송","무료배송","국내배송","정품","공식","추천","특가","할인","모음전","선착순","슈퍼적립"}
    anchor=next((t for t in terms[:4] if t not in anchor_stop and len(t)>=2),"")
    anchor_hit=(not anchor) or anchor.lower() in low
    # For image evidence we prefer a miss to the wrong brand/product family.
    # Requiring the leading stable identity token blocks visually similar third-party items.
    if not anchor_hit:ok=False
    # With no hard model/count token, generic products require a stronger textual
    # consensus so a related product page cannot slip through on one descriptor.
    if not critical and not model_variant_tokens(target) and len(terms)>=4:
        if len(hits)<max(3,min(4,(len(terms[:8])+1)//2)):ok=False
    ok=bool(ok and mok)
    return ok,score,{**(detail or {}),"naver_image_mode":mode,"identity_hits":hits,"anchor":anchor,"anchor_hit":anchor_hit,
                     "model_tokens":model_variant_tokens(target),"model_missing":model_missing}


def exact_matches_with_diagnostic(target,max_queries=4,threshold=0.72):
    seen=set();out=[];errors=[]
    diag={"raw_seen":0,"unique_seen":0,"size_reject":0,"identity_reject":0,"model_reject":0,
          "accepted":0,"queries":[],"rejected_sample":[]}
    display=max(20,min(100,int(settings().get("naver_image_api_display",80))))
    pages=max(1,min(3,int(settings().get("naver_image_api_pages_per_query",2))))
    min_dim=max(180,int(settings().get("image_naver_image_min_dimension",260)))
    max_ratio=max(1.2,float(settings().get("image_naver_image_max_aspect_ratio",3.2)))
    for q in query_variants(target,max_queries):
        qdiag={"query":q,"raw":0,"accepted":0,"rejected":0}
        for page in range(pages):
            try:rows=search(q,display,start=1+page*display,sort="sim",filter_value="large")
            except Exception as e:errors.append(f"{q}: {e}");qdiag["error"]=str(e);break
            diag["raw_seen"]+=len(rows);qdiag["raw"]+=len(rows)
            for r in rows:
                u=r.get("image_url") or r.get("thumbnail") or ""
                if not u or u in seen:continue
                seen.add(u);diag["unique_seen"]+=1
                try:w=int(r.get("width") or 0);h=int(r.get("height") or 0)
                except Exception:w=h=0
                ratio=(max(w,h)/max(1,min(w,h))) if w and h else 1.0
                if w and h and (min(w,h)<min_dim or ratio>max_ratio):
                    diag["size_reject"]+=1;qdiag["rejected"]+=1;continue
                ok,score,detail=_title_accept(r.get("name") or "",target,float(threshold))
                if not ok:
                    if detail.get("model_missing"):diag["model_reject"]+=1
                    else:diag["identity_reject"]+=1
                    qdiag["rejected"]+=1
                    if len(diag["rejected_sample"])<12:
                        diag["rejected_sample"].append({"title":r.get("name") or "","score":score,"detail":detail})
                    continue
                z=dict(r);z.update(match=score,match_detail=detail,verified=True,query_used=q)
                out.append(z);qdiag["accepted"]+=1
            if len(rows)<display:break
        diag["queries"].append(qdiag)
        if len(out)>=int(settings().get("naver_image_api_stop_after_matches",12)):break
    out.sort(key=lambda x:(-float(x.get("match") or 0),-(int(x.get("width") or 0)*int(x.get("height") or 0))))
    diag["accepted"]=len(out)
    return out,errors,diag


def exact_matches(target,max_queries=3,threshold=0.72):
    rows,errors,_=exact_matches_with_diagnostic(target,max_queries,threshold)
    return rows,errors
