# -*- coding: utf-8 -*-
"""Naver autocomplete keyword helper.

Uses the same public autocomplete responses shown by Naver search UI, with a
small local cache and conservative throttling.  If Naver returns no suggestions
we return an empty list rather than inventing 'Naver keywords'.
"""
from pathlib import Path
import json, time, re, urllib.request, urllib.parse
from .common import DATA, log, identity_terms, settings

CACHE = DATA / "naver_keyword_cache.json"
GUARD = DATA / "naver_access_guard.json"
_LAST_REQUEST = 0.0
CACHE_SCHEMA = 2  # v7.58 invalidates legacy empty-cache entries immediately

def _naver_cooling_down():
    try:
        obj=json.loads(GUARD.read_text(encoding="utf-8"));return time.time()<float(obj.get("blocked_until") or 0)
    except Exception:return False

PROMO_STOP = {
    "꼭","보세요","강추","특가","할인","선물","증정","무료배송","공식","정품","추천",
    "제품","상품","세트","구성","신제품","인기","베스트","기획","단독","한정"
}
BANNED = ("쿠팡","토스쇼핑","네이버쇼핑","11번가","지마켓","옥션","알리익스프레스","테무")
# v7.58: autocomplete seeds should describe the product, not origin/listing noise.
# A title such as "미국 도브 센서티브바 ... 미국산 ..." produced a weak
# first seed in v7.57 because only one autocomplete request was enabled.
SEED_NOISE = {
    "미국","미국산","국내","국내산","수입","수입산","해외","해외직구","병행수입",
    "무료","배송","당일","로켓","특가","행사","대용량","소용량"
}

COUNT_UNIT_RE = re.compile(r"(?i)^\d+(?:\.\d+)?(?:ml|l|g|kg|mg|cm|mm|oz|개입|개|매|팩|세트|롤|병|캔|포|봉|장|입)$")
PURE_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
OPTION_NOISE = {
    "본품","리필","세트","단품","구성","기획","옵션","대용량","소용량","묶음",
    "대형","중형","소형","1입","2입","3입","4입","5입","6입"
}


def _load_cache():
    try:
        obj=json.loads(CACHE.read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except Exception:
        return {}


def _save_cache(obj):
    try:
        CACHE.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as e:
        log("네이버 자동완성 캐시 저장 실패: "+str(e))


def _walk_strings(obj):
    """Yield likely suggestion strings from changing nested JSON layouts."""
    if isinstance(obj,str):
        s=re.sub(r"<[^>]+>","",obj).strip()
        if s: yield s
    elif isinstance(obj,list):
        # Naver items are commonly [suggestion, ...metadata]. Prefer first text.
        if obj and isinstance(obj[0],str):
            s=re.sub(r"<[^>]+>","",obj[0]).strip()
            if s: yield s
        for x in obj:
            if isinstance(x,(list,dict)):
                yield from _walk_strings(x)
    elif isinstance(obj,dict):
        for k in ("items","suggestions","query","keyword"):
            if k in obj: yield from _walk_strings(obj[k])


def _request(seed, timeout=8):
    global _LAST_REQUEST
    if _naver_cooling_down():
        log("네이버 접근 제한 쿨다운 중: 자동완성 요청도 보내지 않습니다.");return None
    cfg=settings();gap=float(cfg.get("seo_naver_autocomplete_delay_sec",0.55))
    now=time.time();wait=gap-(now-_LAST_REQUEST)
    if wait>0:time.sleep(wait)
    params={
        "q":seed,"con":"1","frm":"nx","ans":"2","r_format":"json","r_enc":"UTF-8",
        "r_unicode":"0","t_koreng":"1","run":"2","rev":"4","q_enc":"UTF-8","st":"100",
        "r_lt":"100","client":"mobile"
    }
    url="https://ac.search.naver.com/nx/ac?"+urllib.parse.urlencode(params)
    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
             "Accept":"application/json,text/plain,*/*","Referer":"https://search.naver.com/"}
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            raw=r.read(1024*1024).decode("utf-8","ignore")
        _LAST_REQUEST=time.time()
        # Some variants wrap JSON in a callback. Extract the first JSON object.
        raw=raw.strip()
        if raw and raw[0] not in "[{":
            a=raw.find("{");b=raw.rfind("}")
            if a>=0 and b>a:raw=raw[a:b+1]
        return json.loads(raw)
    except Exception as e:
        _LAST_REQUEST=time.time();log(f"네이버 자동완성 요청 실패 [{seed}]: {e}")
        return None


def _token_is_count_or_option(tok):
    tok=str(tok or "").strip()
    if not tok:return True
    if tok in OPTION_NOISE:return True
    if tok in PROMO_STOP or tok in SEED_NOISE:return True
    if PURE_NUMBER_RE.fullmatch(tok):return True
    if COUNT_UNIT_RE.fullmatch(tok):return True
    return False


def _seed_tokens(name):
    toks=[]
    for t in identity_terms(name):
        tt=t.strip()
        if not tt or len(tt)<2 or _token_is_count_or_option(tt):continue
        if tt not in toks:toks.append(tt)
    if not toks:
        toks=[x for x in re.findall(r"[A-Za-z가-힣0-9]+",name or "") if len(x)>=2 and not _token_is_count_or_option(x)]
    return toks[:8]


def descriptive_query_tokens(name):
    """Return a Naver-searchable descriptive phrase without count/set suffixes.

    User rule: for names like `키볼리 일회용 대나무 젓가락 100개 5세트`,
    search `일회용 대나무 젓가락` first instead of the raw listing title.
    Brand words are therefore optional, while count/set option tokens are removed.
    """
    toks=_seed_tokens(name)
    if not toks:return []
    # Drop a likely brand/vendor token when enough descriptive nouns remain.
    if len(toks)>=4:
        body=toks[1:]
    elif len(toks)>=3 and len(toks[0])<=6:
        body=toks[1:]
    else:
        body=list(toks)
    # Remove trailing option/count noise once more, then keep a compact phrase.
    body=[x for x in body if not _token_is_count_or_option(x)]
    if len(body)>=2:return body[:4]
    return toks[:4]


def descriptive_query(name):
    return " ".join(descriptive_query_tokens(name)).strip()


def _seeds(name,max_requests=4):
    """Build several product-centered autocomplete seeds.

    v7.57 shipped with one request in settings, so a weak first seed could leave
    the title with no real Naver subtitle and therefore no `추천｜...` segment.
    v7.58 intentionally tries compact brand/product combinations while keeping
    request count bounded and throttled.
    """
    toks=_seed_tokens(name);desc=descriptive_query_tokens(name);out=[]
    def add(parts):
        q=" ".join(x for x in parts if x).strip()
        if q and q not in out:out.append(q)
    if len(desc)>=3:add(desc[:3])
    if len(desc)>=2:add(desc[:2])
    if len(toks)>=3:add(toks[:3])
    if len(toks)>=2:add(toks[:2])
    if len(toks)>=1:add(toks[:1])
    if len(desc)>=4:add(desc[:4])
    if len(toks)>=4:add(toks[:4])
    # Alternate brand + later product-line word helps cases where the second
    # token is generic but a later term is what Naver autocomplete recognizes.
    if len(toks)>=4:add([toks[0],toks[3]])
    return out[:max(1,int(max_requests))]


def _valid_suggestion(s,seeds):
    s=re.sub(r"\s+"," ",s or "").strip()
    if len(s)<2 or len(s)>80:return False
    if any(x.lower() in s.lower() for x in BANNED):return False
    low=s.lower();seed_tokens=[]
    for z in seeds:seed_tokens.extend(re.findall(r"[0-9A-Za-z가-힣]+",z.lower()))
    strong=[x for x in seed_tokens if len(x)>=2]
    return not strong or any(x in low for x in strong)


def get_subkeywords(product_name, max_count=12):
    cfg=settings()
    if not cfg.get("seo_use_naver_autocomplete",True):return []
    max_req=int(cfg.get("seo_naver_autocomplete_max_requests",4));ttl_h=float(cfg.get("seo_naver_keyword_cache_hours",168))
    # Do not pin an empty/temporarily blocked autocomplete response for 7 days.
    # Positive suggestions may stay cached long, but empty results are refreshed
    # quickly so the next title build can recover automatically.
    empty_ttl_h=float(cfg.get("seo_naver_empty_cache_hours",0.5))
    seeds=_seeds(product_name,max_req);cache=_load_cache();out=[];changed=False
    for seed in seeds:
        key=seed.lower();item=cache.get(key) if isinstance(cache.get(key),dict) else None
        vals=None
        if item:
            cached_vals=item.get("values") or []
            age=time.time()-float(item.get("ts",0))
            limit=(ttl_h if cached_vals else min(ttl_h,empty_ttl_h))*3600
            # v7.57 could cache an empty response for seven days. Ignore those
            # legacy empty entries on the first v7.58 run so `추천｜` can recover
            # immediately instead of waiting for the old cache to expire.
            legacy_empty=(not cached_vals and int(item.get("schema") or 0)<CACHE_SCHEMA)
            if age<=limit and not legacy_empty:vals=cached_vals
        if vals is None:
            obj=_request(seed)
            vals=[]
            if obj is not None:
                seen=set()
                for s in _walk_strings(obj):
                    s=re.sub(r"\s+"," ",s).strip()
                    if s.lower()==seed.lower() or not _valid_suggestion(s,seeds):continue
                    if s.lower() not in seen:seen.add(s.lower());vals.append(s)
                cache[key]={"ts":time.time(),"values":vals,"schema":CACHE_SCHEMA};changed=True
        for s in vals or []:
            if s not in out and _valid_suggestion(s,seeds):out.append(s)
            if len(out)>=max_count:break
        if len(out)>=max_count:break
    if changed:_save_cache(cache)
    return out[:max_count]


def keyword_evidence(product_name, subkeywords):
    return {
        "source":"Naver autocomplete",
        "product_name":product_name,
        "descriptive_query":descriptive_query(product_name),
        "seeds":_seeds(product_name,int(settings().get("seo_naver_autocomplete_max_requests",2))),
        "subkeywords":list(subkeywords or []),
        "fetched_at":time.strftime("%Y-%m-%d %H:%M:%S")
    }
