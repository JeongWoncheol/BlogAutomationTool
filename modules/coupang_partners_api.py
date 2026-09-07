# -*- coding: utf-8 -*-
"""Coupang Partners product search adapter.

Browser-free product/price/image lookup using the authenticated Coupang Partners
API.  This module deliberately does not attempt to bypass Coupang web access
controls.  If credentials are unavailable, callers must fall back to already
collected discovery snapshots or a user-triggered browser refresh.
"""
from pathlib import Path
import os, json, time, hmac, hashlib, urllib.parse, urllib.request, urllib.error, threading, html, io
from datetime import datetime, timezone
from collections.abc import Callable

from .affiliate_identity import product_id as _identity_product_id, same_product_url, variant_conflicts
from .affiliate_request import AffiliateStopped, AffiliateTimeout, Operation, fetch

from .common import (ROOT, DATA, log, db_connect, init_db_fast,
                     marketplace_product_accept, critical_identity_tokens,
                     identity_terms, signature_identity_tokens,
                     clean_listing_title_noise)

# Avoid circular import of search_adapter.clean_product_name.  A small local
# normalization is enough for API records; identity validation is done by common.
def _clean_name(s):
    import re
    s=re.sub(r"<[^>]+>"," ",str(s or ""))
    s=re.sub(r"\s+"," ",s).strip()
    return s[:300]

CREDENTIALS = DATA / "coupang_partners_credentials.json"
CACHE = DATA / "coupang_partners_cache.json"
DEEPLINK_CACHE = DATA / "coupang_deeplink_cache.json"
BASE_URL = "https://api-gateway.coupang.com"
SEARCH_PATHS = [
    "/v2/providers/affiliate_open_api/apis/openapi/products/search",
    "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search",
]
SEARCH_PATH = SEARCH_PATHS[0]
DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
_LOCK=threading.Lock()
_LAST_CALL=0.0


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _settings():
    try:
        return json.loads((DATA/"settings.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def credentials():
    cfg=_settings()
    file_obj=_read_json(CREDENTIALS,{})
    access=(os.environ.get("COUPANG_PARTNERS_ACCESS_KEY") or
            cfg.get("coupang_partners_access_key") or file_obj.get("access_key") or "").strip()
    secret=(os.environ.get("COUPANG_PARTNERS_SECRET_KEY") or
            cfg.get("coupang_partners_secret_key") or file_obj.get("secret_key") or "").strip()
    return access,secret


def save_credentials(access_key, secret_key):
    access_key=str(access_key or "").strip();secret_key=str(secret_key or "").strip()
    if not access_key or not secret_key:
        raise ValueError("Access Key와 Secret Key를 모두 입력해야 합니다.")
    CREDENTIALS.parent.mkdir(parents=True,exist_ok=True)
    CREDENTIALS.write_text(json.dumps({"access_key":access_key,"secret_key":secret_key},ensure_ascii=False,indent=2),encoding="utf-8")
    return str(CREDENTIALS)


def clear_credentials():
    try:CREDENTIALS.unlink()
    except FileNotFoundError:pass


def ready():
    a,s=credentials();return bool(a and s)


def health():
    a,s=credentials()
    if not (a and s):
        return {"ready":False,"name":"쿠팡 Partners API","message":"API 키 미설정 · 같은 실행의 쿠팡 수집 스냅샷만 사용합니다."}
    return {"ready":True,"name":"쿠팡 Partners API","message":f"브라우저 없이 상품명·가격·대표이미지·제휴링크 생성 · 상품 ID별 영구 DB 캐시 · Access Key {a[:4]}…{a[-3:]}"}


def normalize_image_url(url):
    """Normalize escaped or protocol-relative image URLs returned by the API."""
    value=html.unescape(str(url or "").strip()).replace("\\/","/")
    if value.startswith("//"):value="https:"+value
    elif value and "://" not in value:value="https://"+value.lstrip("/")
    try:
        p=urllib.parse.urlsplit(value)
        if p.scheme not in ("http","https") or not p.netloc:return ""
        path=urllib.parse.quote(urllib.parse.unquote(p.path),safe="/%:@!$&'()*+,;=-._~")
        return urllib.parse.urlunsplit(("https" if p.scheme=="http" else p.scheme,p.netloc,path,p.query,""))
    except Exception:return ""


def download_product_image(url, out, referer=None, min_dimension=180, timeout=25):
    """Download/decode a Coupang API image with CDN-compatible Referer retries."""
    from PIL import Image, ImageOps
    url=normalize_image_url(url);out=Path(out)
    if not url:return {"ok":False,"reason":"빈/잘못된 쿠팡 이미지 URL","url":""}
    refs=[]
    for value in (referer,"https://www.coupang.com/",None):
        if value not in refs:refs.append(value)
    errors=[]
    for ref in refs:
        headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
                 "Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8","Accept-Language":"ko-KR,ko;q=0.9,en;q=0.7","Cache-Control":"no-cache"}
        if ref:headers["Referer"]=ref
        try:
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=float(timeout)) as response:
                data=response.read(15*1024*1024);ctype=str(response.headers.get("Content-Type") or "").lower()
            if len(data)<1024:raise ValueError(f"응답이 너무 작음({len(data)} bytes)")
            if "text/html" in ctype or "application/json" in ctype:raise ValueError("이미지가 아닌 응답: "+ctype)
            im=Image.open(io.BytesIO(data));im.load();im=ImageOps.exif_transpose(im)
            if im.width<int(min_dimension) or im.height<int(min_dimension):raise ValueError(f"해상도 부족 {im.width}x{im.height}")
            if im.mode in ("RGBA","LA"):
                bg=Image.new("RGB",im.size,"white");bg.paste(im,mask=im.getchannel("A"));im=bg
            else:im=im.convert("RGB")
            im.thumbnail((1600,1600),Image.Resampling.LANCZOS);out.parent.mkdir(parents=True,exist_ok=True)
            im.save(out,"JPEG",quality=94,optimize=True)
            return {"ok":True,"path":str(out),"url":url,"width":im.width,"height":im.height,"content_type":ctype}
        except Exception as e:
            errors.append(str(e))
            try:out.unlink(missing_ok=True)
            except Exception:pass
            time.sleep(0.15)
    return {"ok":False,"reason":" / ".join(errors[-3:]) or "쿠팡 이미지 다운로드 실패","url":url}


def _authorization(method, uri, access_key, secret_key):
    parts=uri.split("?",1);path=parts[0];query=parts[1] if len(parts)==2 else ""
    dt=datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message=dt+method.upper()+path+query
    signature=hmac.new(secret_key.encode("utf-8"),message.encode("utf-8"),hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256,access-key={access_key},signed-date={dt},signature={signature}"


def _cache_key(keyword,limit,image_size=""):
    return f"{keyword.strip().lower()}|{int(limit)}|{image_size}"


def _cache_get(key, ttl):
    obj=_read_json(CACHE,{})
    rec=obj.get(key)
    if not rec:return None
    if time.time()-float(rec.get("ts",0))>float(ttl):return None
    return rec.get("value")


def _cache_put(key,value):
    with _LOCK:
        obj=_read_json(CACHE,{})
        obj[key]={"ts":time.time(),"value":value}
        # Keep the cache bounded.
        if len(obj)>500:
            items=sorted(obj.items(),key=lambda kv:float((kv[1] or {}).get("ts",0)),reverse=True)[:350]
            obj=dict(items)
        CACHE.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")


def _throttle(operation: Operation | None = None):
    global _LAST_CALL
    sec=float(_settings().get("coupang_api_min_interval_sec",0.45))
    operation=operation or Operation(time.monotonic()+30)
    while not _LOCK.acquire(timeout=0.1):
        operation.remaining()
    try:
        wait=max(0.0,sec-(time.monotonic()-_LAST_CALL))
        if wait:operation.pause(wait)
        _LAST_CALL=time.monotonic()
    finally:
        _LOCK.release()


def search(keyword, limit=10, use_cache=True, operation: Operation | None = None):
    """Return normalized Coupang Partners product search rows.

    Search itself is browser-free.  The API account/rate policy still applies,
    so this adapter caches short-lived responses and serializes calls.
    """
    keyword=" ".join(str(keyword or "").split()).strip()
    if not keyword:return []
    limit=max(1,min(10,int(limit)))
    cfg=_settings();ttl=int(cfg.get("coupang_api_cache_ttl_sec",300))
    operation=operation or Operation(time.monotonic()+max(1,min(30,float(cfg.get("coupang_api_timeout_sec",15)))))
    operation.remaining()
    ck=_cache_key(keyword,limit)
    if use_cache:
        hit=_cache_get(ck,ttl)
        if isinstance(hit,list):return hit
    access,secret=credentials()
    if not (access and secret):
        raise RuntimeError("쿠팡 Partners API 키가 설정되지 않았습니다. 83_COUPANG_PARTNERS_API_SETUP.cmd를 실행하세요.")
    params=urllib.parse.urlencode({"keyword":keyword,"limit":limit},quote_via=urllib.parse.quote)
    body=None;last_error=None;used_path=None
    # Coupang Partners deployments seen in the field use both the legacy path and
    # the /v1/ path.  Try only these authenticated API paths; never fall back to
    # coupang.com web scraping here.
    for path in SEARCH_PATHS:
        uri=path+"?"+params
        auth=_authorization("GET",uri,access,secret)
        req=urllib.request.Request(BASE_URL+uri,headers={"Authorization":auth,"Content-Type":"application/json;charset=UTF-8","Accept":"application/json"})
        _throttle(operation)
        try:
            body=fetch(req,operation).decode("utf-8","replace");used_path=path
            break
        except (AffiliateStopped, AffiliateTimeout):
            raise
        except urllib.error.HTTPError as e:
            detail=e.read(8000).decode("utf-8","replace") if hasattr(e,"read") else str(e)
            last_error=RuntimeError(f"쿠팡 Partners API HTTP {e.code}: {detail[:500]}")
            # Authentication/policy errors will not be fixed by changing paths.
            if int(getattr(e,"code",0) or 0) not in (400,404,405):
                raise last_error
        except Exception as e:
            last_error=RuntimeError("쿠팡 Partners API 호출 실패: "+str(e));break
    if body is None:
        raise last_error or RuntimeError("쿠팡 Partners API 호출 실패")
    try:obj=json.loads(body)
    except Exception:raise RuntimeError("쿠팡 Partners API 응답이 JSON이 아닙니다.")
    if str(obj.get("rCode",obj.get("code","0"))) not in ("0","SUCCESS","200",""):
        raise RuntimeError("쿠팡 Partners API 오류: "+str(obj.get("rMessage") or obj.get("message") or obj)[:600])
    data=obj.get("data") or {};products=data.get("productData") if isinstance(data,dict) else data
    if not isinstance(products,list):products=[]
    out=[]
    for p in products:
        if not isinstance(p,dict):continue
        try:price=int(float(p.get("productPrice") or 0))
        except Exception:price=0
        out.append({
            "product_id":str(p.get("productId") or ""),
            "name":_clean_name(p.get("productName") or ""),
            "price":price if price>0 else None,
            "image_url":normalize_image_url(p.get("productImage") or p.get("imageUrl") or p.get("productImageUrl") or ""),
            "url":str(p.get("productUrl") or ""),
            "rank":p.get("rank"),
            "is_rocket":bool(p.get("isRocket",False)),
            "is_free_shipping":bool(p.get("isFreeShipping",False)),
            "keyword":str(p.get("keyword") or keyword),
            "source":"coupang_partners_api",
            "api_path":used_path,
            "captured_at":time.strftime("%Y-%m-%d %H:%M:%S")
        })
    _cache_put(ck,out)
    return out


def query_variants(target_name, max_count=4):
    """Full name first, then core/variant fallback queries.

    Search recall and final identity are separate: every returned API row is
    still validated against the untouched full product name.
    """
    import re
    raw=" ".join(str(target_name or "").split())
    toks=re.findall(r"[0-9A-Za-z가-힣.+_-]+",raw)
    variants=[]
    def add(q):
        q=" ".join(str(q or "").split()).strip()
        if q and q.lower() not in {x.lower() for x in variants}:variants.append(q)
    add(raw[:80])
    strong=[]
    for tok in toks:
        if len(tok)<2:continue
        if tok in {"추천","후기","정품","공식","무료배송","특가","증정"}:continue
        strong.append(tok)
    critical=critical_identity_tokens(raw);core=identity_terms(raw);sig=signature_identity_tokens(raw)
    add(" ".join((core[:2]+sig+critical[:2])[:6])[:50])
    add(" ".join(strong[:5]+[x for x in critical if x not in strong[:5]])[:50])
    add(" ".join(strong[:3]+[x for x in critical if x not in strong[:3]])[:50])
    return variants[:max(1,int(max_count))]


def sharelink_query_variants(target_name, max_count=7):
    """High-recall Sharelink searches; final acceptance still uses the full title.

    A long collected listing title often contains origin, promotion and seller
    phrases that Coupang's API title omits.  Search those titles first, then use
    compact product terms without weakening capacity/count/model verification.
    """
    import re
    raw=" ".join(clean_listing_title_noise(target_name).split());terms=identity_terms(raw)
    critical=critical_identity_tokens(raw);signature=signature_identity_tokens(raw)
    noise={"추천","후기","정품","공식","무료배송","특가","증정","국내산","수입산","미국산","해외직구"}
    words=[x for x in re.findall(r"[0-9A-Za-z가-힣.+_-]+",raw) if len(x)>=2 and x not in noise]
    out=[]
    def add(parts):
        values=parts if isinstance(parts,(list,tuple)) else [str(parts)]
        unique=[];seen=set()
        for value in values:
            key=str(value or "").strip().lower()
            if key and key not in seen:seen.add(key);unique.append(str(value).strip())
        q=" ".join(unique)
        q=" ".join(q.split()).strip()[:80]
        if q and q.lower() not in {x.lower() for x in out}:out.append(q)
    add(raw)
    add((terms[:4]+[x for x in critical if x not in terms[:4]])[:7])
    add((terms[:3]+signature+[x for x in critical if x not in terms[:3]])[:7])
    if len(terms)>=3:add((terms[1:5]+critical)[:7])
    add((words[:4]+[x for x in critical if x not in words[:4]])[:7])
    add((terms[:2]+signature+critical)[:6])
    if signature:add((terms[:1]+signature+critical)[:5])
    add((terms[:2]+critical)[:5])
    return out[:max(1,int(max_count))]


def _sharelink_candidate_accept(candidate_name, target_name):
    """Match a shortened API title to the untouched collected title.

    Model/capacity/count stay mandatory.  Seller-tail words may be absent only
    when at least two product identity words (and a leading core word) agree.
    """
    threshold=float(_settings().get("coupang_sharelink_match_threshold",0.36))
    ok,score,detail=marketplace_product_accept(candidate_name,target_name,threshold)
    conflicts=variant_conflicts(str(candidate_name or ""),str(target_name or ""))
    if conflicts:return False,score,{**detail,"variant_conflicts":conflicts,"sharelink_match_mode":"variant_rejected"}
    if ok:return ok,score,{**detail,"sharelink_match_mode":detail.get("match_mode") or "balanced"}
    low=" ".join(str(candidate_name or "").lower().split())
    terms=identity_terms(target_name)[:8];hits=[x for x in terms if x.lower() in low]
    core=terms[:3];core_hits=[x for x in core if x.lower() in low]
    missing=list(detail.get("missing") or [])
    required=1 if len(terms)<=1 else 2
    relaxed=(not missing) and bool(core_hits) and len(hits)>=required and float(score)>=threshold
    return relaxed,score,{**detail,"identity_hits":hits,"core_hits":core_hits,
                          "required_hits":required,"sharelink_match_mode":"core_keyword_full_title_verified" if relaxed else "rejected"}


def sharelink_exact_matches(target_name, max_queries=7, operation: Operation | None = None):
    """Search broad, validate strict, and retain per-query failure evidence."""
    matched=[];seen=set();errors=[];attempts=[]
    operation=operation or Operation(time.monotonic()+45)
    for q in sharelink_query_variants(target_name,max_queries):
        operation.remaining()
        try:rows=search(q,10,operation=operation)
        except (AffiliateStopped, AffiliateTimeout):
            raise
        except Exception as e:
            errors.append(str(e));attempts.append({"query":q,"error":str(e),"result_count":0});break
        accepted=0;rejected=[]
        for row in rows:
            key=row.get("product_id") or (row.get("name"),row.get("price"),row.get("url"))
            if key in seen:continue
            seen.add(key)
            ok,score,detail=_sharelink_candidate_accept(row.get("name") or "",target_name)
            if not ok:
                if len(rejected)<4:rejected.append({"name":row.get("name") or "","score":score,"detail":detail})
                continue
            item=dict(row);item.update(match=score,match_detail=detail,verified=True,query_used=q)
            matched.append(item);accepted+=1
        attempts.append({"query":q,"result_count":len(rows),"accepted":accepted,"rejected_samples":rejected})
        if matched:break
    matched.sort(key=lambda r:(-float(r.get("match") or 0),int(r.get("rank") or 9999),int(r.get("price") or 10**12)))
    return matched,errors,attempts


def exact_matches(target_name, max_queries=2, threshold=None):
    cfg=_settings();threshold=float(cfg.get("price_api_recall_match_threshold",0.48))
    matched=[];seen=set();errors=[]
    for q in query_variants(target_name,max_queries):
        try:rows=search(q,10)
        except Exception as e:
            errors.append(str(e));continue
        for r in rows:
            key=r.get("product_id") or (r.get("name"),r.get("price"),r.get("image_url"))
            if key in seen:continue
            seen.add(key)
            # IMPORTANT: validate the returned product name only.  Never append
            # the search query to the candidate text; doing so can make unrelated
            # results look like exact matches because the query itself contains
            # every target keyword.
            ok,score,detail=marketplace_product_accept(r.get("name") or "",target_name,threshold)
            if not ok:continue
            z=dict(r);z.update(match=score,match_detail=detail,verified=True,query_used=q)
            matched.append(z)
    matched.sort(key=lambda r:(-float(r.get("match") or 0), int(r.get("rank") or 9999), int(r.get("price") or 10**12)))
    return matched,errors


def best_exact_match(target_name, max_queries=2, threshold=None):
    rows,errors=exact_matches(target_name,max_queries,threshold)
    return (rows[0] if rows else None),errors


def _product_id_from_url(url):
    return _identity_product_id(str(url or ""))


def _valid_affiliate_url(url):
    """Validate syntax locally. Never open a tracking URL to 'test' it."""
    try:
        parsed=urllib.parse.urlsplit(str(url or "").strip())
        host=(parsed.hostname or "").lower()
        return parsed.scheme.lower()=="https" and host in {"link.coupang.com","coupa.ng"} and parsed.username is None and parsed.port in (None,443) and bool(parsed.path.strip("/"))
    except Exception:return False


def _cached_deeplink(product_id,sub_id="",source_url="",product_name=""):
    if not str(product_id or "").strip():return None
    init_db_fast();con=db_connect(row_factory=True)
    try:
        row=con.execute("""SELECT * FROM affiliate_link_cache
                           WHERE coupang_product_id=? AND sub_id=?""",
                        (str(product_id).strip(),str(sub_id or "").strip())).fetchone()
        if not row:return None
        link=str(row["sharelink"] or "").strip()
        if not _valid_affiliate_url(link):return None
        if source_url and not same_product_url(source_url,str(row["source_url"] or "")):return None
        if product_name:
            accepted,_,_=_sharelink_candidate_accept(str(row["product_name"] or ""),str(product_name))
            if not accepted:return None
        meta={}
        try:meta=json.loads(row["metadata_json"] or "{}")
        except (ValueError,TypeError):return None
        if meta.get("source") not in {"coupang_partners_deeplink","coupang_partners_search_affiliate_url"}:return None
        if str(meta.get("product_id") or "")!=str(product_id):return None
        if _product_id_from_url(row["source_url"] or "") and not same_product_url(row["source_url"],str(meta.get("original_url") or "")):return None
        con.execute("""UPDATE affiliate_link_cache SET last_used_at=datetime('now','localtime')
                       WHERE coupang_product_id=? AND sub_id=?""",
                    (str(product_id).strip(),str(sub_id or "").strip()));con.commit()
        return {"ok":True,"sharelink":link,"shorten_url":link,
                "landing_url":"","original_url":row["source_url"] or "",
                "product_id":str(product_id),"source":"affiliate_link_db_cache",
                "cache_hit":True,"response_code":row["response_code"] or "CACHE",
                "cache_metadata":meta}
    finally:con.close()


def _store_deeplink(product_id,sub_id,product_name,source_url,result,response_code="0"):
    link=str((result or {}).get("sharelink") or "").strip()
    if not str(product_id or "").strip() or not _valid_affiliate_url(link):return False
    init_db_fast();con=db_connect()
    try:
        con.execute("""INSERT INTO affiliate_link_cache
          (coupang_product_id,sub_id,product_name,source_url,sharelink,response_code,metadata_json,created_at,last_used_at)
          VALUES(?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))
          ON CONFLICT(coupang_product_id,sub_id) DO UPDATE SET
            product_name=excluded.product_name,source_url=excluded.source_url,
            sharelink=excluded.sharelink,response_code=excluded.response_code,
            metadata_json=excluded.metadata_json,last_used_at=excluded.last_used_at""",
          (str(product_id).strip(),str(sub_id or "").strip(),str(product_name or "")[:300],
           str(source_url or "")[:1200],link,str(response_code or "")[:80],
           json.dumps(result,ensure_ascii=False)[:12000]))
        con.commit();return True
    finally:con.close()


def remember_existing_deeplink(product_id,sharelink,source_url="",product_name="",sub_id=""):
    """Recognize an existing link only through matching API cache evidence."""
    cached=_cached_deeplink(product_id,sub_id,source_url,product_name)
    return bool(cached and cached.get("sharelink")==str(sharelink or "").strip())


def create_deeplink(coupang_url, sub_id="", use_cache=True, product_id="", product_name="", operation: Operation | None = None):
    """Create one affiliate link through the API, then reuse it forever by product ID.

    The returned tracking URL is never opened by urllib, Selenium, Chrome or any
    other verifier. Only HTTPS/host/path syntax and the API response code are
    checked locally.
    """
    url=str(coupang_url or "").strip()
    url_product_id=_product_id_from_url(url)
    if not url_product_id:
        return {"ok":False,"reason":"쿠팡 상품 URL 없음","original_url":url}
    cfg=_settings();product_id=str(product_id or _product_id_from_url(url)).strip()
    if product_id!=url_product_id:
        return {"ok":False,"reason":"쿠팡 상품 URL과 상품 ID 불일치","original_url":url}
    operation=operation or Operation(time.monotonic()+max(1,min(30,float(cfg.get("coupang_api_timeout_sec",15)))))
    operation.remaining()
    if use_cache:
        cached=_cached_deeplink(product_id,sub_id,url,product_name)
        if cached:return cached
    access,secret=credentials()
    if not (access and secret):
        return {"ok":False,"reason":"쿠팡 Partners API 키 미설정","original_url":url}
    body={"coupangUrls":[url]}
    if str(sub_id or "").strip():body["subId"]=str(sub_id).strip()
    raw=json.dumps(body,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    auth=_authorization("POST",DEEPLINK_PATH,access,secret)
    req=urllib.request.Request(BASE_URL+DEEPLINK_PATH,data=raw,method="POST",headers={
        "Authorization":auth,"Content-Type":"application/json;charset=UTF-8","Accept":"application/json"})
    _throttle(operation)
    try:
        obj=json.loads(fetch(req,operation).decode("utf-8","replace"))
    except (AffiliateStopped, AffiliateTimeout):
        raise
    except urllib.error.HTTPError as e:
        detail=e.read(8000).decode("utf-8","replace") if hasattr(e,"read") else str(e)
        return {"ok":False,"reason":f"쿠팡 딥링크 HTTP {e.code}: {detail[:400]}","original_url":url}
    except Exception as e:
        return {"ok":False,"reason":"쿠팡 딥링크 생성 실패: "+str(e),"original_url":url}
    response_code=str(obj.get("rCode",obj.get("code","0")))
    if response_code not in ("0","SUCCESS","200",""):
        return {"ok":False,"reason":"쿠팡 딥링크 API 오류: "+str(obj.get("rMessage") or obj.get("message") or obj)[:400],"original_url":url}
    rows=obj.get("data") or []
    item=next((row for row in rows if isinstance(row,dict) and
               same_product_url(url,str(row.get("originalUrl") or ""))),{}) if isinstance(rows,list) else {}
    if not item:
        return {"ok":False,"reason":"딥링크 응답 원상품 URL 불일치 또는 누락","original_url":url}
    short=str(item.get("shortenUrl") or item.get("shortUrl") or "").strip()
    landing=str(item.get("landingUrl") or "").strip()
    # A plain landing URL is not accepted as the canonical affiliate link. The
    # API must return a Coupang short tracking host; validation remains local.
    link=short if _valid_affiliate_url(short) else ""
    result={"ok":bool(link),"sharelink":link,"shorten_url":link,"landing_url":landing,
            "original_url":str(item.get("originalUrl") or url),"product_id":product_id,
            "response_code":response_code,"source":"coupang_partners_deeplink",
            "cache_hit":False,"link_validation":"LOCAL_FORMAT_ONLY_NO_CLICK"}
    if not result["ok"]:result["reason"]="쿠팡 딥링크 응답에 유효한 HTTPS 단축 제휴링크가 없음"
    else:
        operation.remaining()
        _store_deeplink(product_id,sub_id,product_name,url,result,response_code)
    return result


def exact_product_sharelink(target_name, sub_id="", max_queries=3, verified_product_url="", stop_check: Callable[[], bool] | None = None):
    """Reuse an already verified Coupang product URL, otherwise search the API.

    A TOP100 row discovered on Coupang already has stronger identity evidence
    than another shortened keyword search.  Converting that exact URL first
    avoids dropping Sharelinks for long marketplace titles; a failed conversion
    still falls through to the cleaned core-keyword API search.
    """
    clean_target=clean_listing_title_noise(target_name) or str(target_name or "").strip()
    operation=Operation(time.monotonic()+45,stop_check)
    operation.remaining()
    direct_error=""
    verified=str(verified_product_url or "").strip()
    if verified:
        try:
            parsed=urllib.parse.urlsplit(verified);host=(parsed.netloc or "").lower();path=(parsed.path or "").lower()
            if parsed.scheme.lower()=="http" and (host.endswith("coupang.com") or "link.coupang.com" in host):
                verified=urllib.parse.urlunsplit(("https",parsed.netloc,parsed.path,parsed.query,parsed.fragment))
                parsed=urllib.parse.urlsplit(verified);host=(parsed.netloc or "").lower();path=(parsed.path or "").lower()
            is_product=bool(_product_id_from_url(verified))
            if is_product:
                direct=create_deeplink(verified,sub_id=sub_id,
                                       product_id=_product_id_from_url(verified),product_name=clean_target,operation=operation)
                if direct.get("ok"):
                    return {**direct,"source":"verified_coupang_product_url_deeplink",
                            "target_name_original":str(target_name or ""),"target_name_cleaned":clean_target,
                            "query_attempts":[]}
                direct_error=str(direct.get("reason") or "검증된 쿠팡 URL 딥링크 변환 실패")
        except (AffiliateStopped, AffiliateTimeout):
            raise
        except Exception as exc:
            direct_error="검증된 쿠팡 URL 처리 실패: "+str(exc)
    rows,errors,attempts=sharelink_exact_matches(clean_target,max_queries=max_queries,operation=operation)
    if direct_error:errors.insert(0,direct_error)
    match=rows[0] if rows else None
    if not match:
        reason="쿠팡 Partners 동일상품 미검색"+(" · "+errors[-1] if errors else "")
        return {"ok":False,"reason":reason,"errors":errors[-4:],"query_attempts":attempts}
    product_url=str(match.get("url") or "").strip()
    if not product_url:
        return {"ok":False,"reason":"쿠팡 Partners 동일상품 URL 없음","match":match,"errors":errors[-4:],"query_attempts":attempts}
    dl=create_deeplink(product_url,sub_id=sub_id,product_id=match.get("product_id") or "",product_name=match.get("name") or clean_target,operation=operation)
    # Product-search responses can themselves contain an affiliate tracking URL.
    # If the deeplink endpoint temporarily fails, keep that verified Partners URL
    # rather than dropping the top Sharelink altogether.
    if not dl.get("ok") and _valid_affiliate_url(product_url):
        dl={"ok":True,"sharelink":product_url,"shorten_url":product_url,"landing_url":"","original_url":product_url,
            "source":"coupang_partners_search_affiliate_url","deeplink_fallback_reason":dl.get("reason") or "",
            "product_id":str(match.get("product_id") or ""),"link_validation":"LOCAL_FORMAT_ONLY_NO_CLICK"}
        operation.remaining()
        _store_deeplink(match.get("product_id") or "",sub_id,match.get("name") or clean_target,
                        match.get("url") or "",dl,"SEARCH_RESPONSE")
    out={**dl,"match_product_name":match.get("name") or "","product_id":match.get("product_id") or "",
         "product_url":product_url,"match_score":match.get("match") or 0,"query_used":match.get("query_used") or "",
         "target_name_original":str(target_name or ""),"target_name_cleaned":clean_target,
         "errors":errors[-4:],"query_attempts":attempts}
    return out
