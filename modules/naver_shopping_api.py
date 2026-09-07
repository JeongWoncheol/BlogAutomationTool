# -*- coding: utf-8 -*-
"""NAVER Search API shopping adapter.

The same NAVER Developers Search API credentials used by image search can call
the official shopping endpoint.  A result is accepted only after the complete
target name (including model/capacity/count tokens) is validated.
"""
from pathlib import Path
import html, json, re, threading, time, urllib.parse, urllib.request

from .common import DATA, settings, marketplace_product_accept, identity_terms, critical_identity_tokens

CREDENTIALS = DATA / "naver_image_api_credentials.json"
ENDPOINT = "https://openapi.naver.com/v1/search/shop.json"
_CACHE = {}
_LOCK = threading.Lock()
_LAST_CALL = 0.0


def _creds():
    cfg=settings();obj={}
    try:obj=json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except Exception:pass
    return (str(cfg.get("naver_search_client_id") or cfg.get("naver_image_client_id") or obj.get("client_id") or "").strip(),
            str(cfg.get("naver_search_client_secret") or cfg.get("naver_image_client_secret") or obj.get("client_secret") or "").strip())


def ready():
    a,b=_creds();return bool(a and b)


def health():
    return {"ready":ready(),"name":"NAVER 쇼핑 검색 API",
            "message":"가격(lprice)+대표이미지(image) 조회 가능" if ready() else "Client ID/Secret 미설정 · 92_NAVER_IMAGE_API_SETUP.cmd 실행"}


def _clean(value):
    value=html.unescape(re.sub(r"<[^>]+>"," ",str(value or "")))
    return re.sub(r"\s+"," ",value).strip()


def query_variants(target,max_count=5):
    raw=" ".join(str(target or "").split());out=[]
    def add(q):
        q=" ".join(str(q or "").split()).strip()
        if q and q.casefold() not in {x.casefold() for x in out}:out.append(q)
    # Recall first, identity validation later.  Core queries avoid long seller
    # suffixes while the untouched full name remains the final hard gate.
    add(raw[:100])
    terms=identity_terms(raw);critical=critical_identity_tokens(raw)
    add(" ".join(terms[:4]+critical[:3]))
    add(" ".join(terms[:3]+critical[:2]))
    add(" ".join(terms[:2]+critical[:3]))
    add(" ".join(terms[:2]))
    return out[:max(1,int(max_count))]


def _throttle():
    global _LAST_CALL
    wait_sec=float(settings().get("naver_shopping_api_min_interval_sec",0.08))
    with _LOCK:
        delay=max(0.0,wait_sec-(time.monotonic()-_LAST_CALL))
        if delay:time.sleep(delay)
        _LAST_CALL=time.monotonic()


def search(query,display=100,start=1,sort="sim",use_cache=True):
    query=" ".join(str(query or "").split()).strip()
    if not query:return []
    display=max(1,min(100,int(display)));start=max(1,min(1000,int(start)));sort=sort if sort in {"sim","date","asc","dsc"} else "sim";key=(query.casefold(),display,start,sort)
    ttl=float(settings().get("naver_shopping_api_cache_ttl_sec",900))
    if use_cache:
        hit=_CACHE.get(key)
        if hit and time.time()-hit[0]<ttl:return [dict(x) for x in hit[1]]
    cid,secret=_creds()
    if not cid or not secret:raise RuntimeError("NAVER Search API Client ID/Secret이 설정되지 않았습니다.")
    params=urllib.parse.urlencode({"query":query,"display":display,"start":start,"sort":sort,"exclude":"used:rental:cbshop"})
    req=urllib.request.Request(ENDPOINT+"?"+params,headers={
        "X-Naver-Client-Id":cid,"X-Naver-Client-Secret":secret,
        "User-Agent":"NaverBlogAutomationStudio/7.56","Accept":"application/json"})
    _throttle()
    with urllib.request.urlopen(req,timeout=float(settings().get("naver_shopping_api_timeout_sec",15))) as response:
        obj=json.loads(response.read(4*1024*1024).decode("utf-8","replace"))
    rows=[]
    for item in obj.get("items") or []:
        try:price=int(float(item.get("lprice") or 0))
        except Exception:price=0
        if price<=0:continue
        image=str(item.get("image") or "").strip()
        if image.startswith("//"):image="https:"+image
        rows.append({"name":_clean(item.get("title")),"price":price,"image_url":image,
                     "url":str(item.get("link") or ""),"product_id":str(item.get("productId") or ""),
                     "mall_name":_clean(item.get("mallName")),"brand":_clean(item.get("brand")),
                     "maker":_clean(item.get("maker")),"product_type":item.get("productType"),
                     "category1":_clean(item.get("category1")),"category2":_clean(item.get("category2")),
                     "category3":_clean(item.get("category3")),"category4":_clean(item.get("category4")),
                     "source":"naver_shopping_search_api","captured_at":time.strftime("%Y-%m-%d %H:%M:%S")})
    _CACHE[key]=(time.time(),[dict(x) for x in rows])
    return rows


def best_exact_match(target,max_queries=3,threshold=0.62):
    seen=set();accepted=[];errors=[];rows_seen=0;rejected=[]
    display=int(settings().get("naver_shopping_api_display",100))
    pages=max(1,min(3,int(settings().get("naver_shopping_api_pages_per_query",2))))
    relaxed=float(settings().get("price_api_recall_match_threshold",0.48))
    for query in query_variants(target,max_queries):
        for page in range(pages):
            start=1+page*display
            try:rows=search(query,display,start=start,sort="sim")
            except Exception as exc:errors.append(f"{query} start={start}: {exc}");break
            rows_seen+=len(rows)
            for row in rows:
                key=row.get("product_id") or (row.get("name","").casefold()+"|"+str(row.get("price")))
                if key in seen:continue
                seen.add(key)
                identity_text=" ".join(x for x in (row.get("name"),row.get("brand"),row.get("maker")) if x)
                ok,score,detail=marketplace_product_accept(identity_text,target,min(float(threshold),relaxed))
                if not ok:
                    if len(rejected)<10:rejected.append({"name":row.get("name") or "","score":score,"detail":detail})
                    continue
                rec=dict(row);rec.update(verified=True,match=score,match_detail=detail,query_used=query,
                                         query_start=start,identity_text=identity_text)
                accepted.append(rec)
            if len(rows)<display or accepted:break
        if accepted and max(float(x.get("match") or 0) for x in accepted)>=0.88:break
    accepted.sort(key=lambda x:(-float(x.get("match") or 0),int(x.get("price") or 10**15)))
    diag={"rows_seen":rows_seen,"unique_candidates":len(seen),"accepted":len(accepted),"rejected_sample":rejected}
    if accepted:accepted[0]["api_diagnostic"]=diag
    elif rows_seen:errors.append(f"NAVER_API_CANDIDATES_MISMATCH rows={rows_seen}")
    else:errors.append("NAVER_API_NO_RESULTS")
    return (accepted[0] if accepted else None),errors
