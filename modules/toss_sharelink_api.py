# -*- coding: utf-8 -*-
"""Toss Sharelink Creator Open API adapter (v7.47.6 official flow).

Official read-only flow reflected from the user's Sharelink documentation:
1) POST https://oauth2.cert.toss.im/token as application/x-www-form-urlencoded
   with grant_type=client_credentials, client_id=Access Key,
   client_secret=Secret Key, scope=sharelink:read.
2) GET https://sharelink.toss.im/openapi/health with Bearer token.
3) GET https://sharelink.toss.im/openapi/products/best-selling?size=N.
The token is cached until expires_in. Link issuance would additionally require
sharelink:write, but this Studio currently only needs read access for product data.
"""
from pathlib import Path
import os, json, time, threading, urllib.parse, urllib.request, urllib.error, re, base64, ipaddress, hashlib

from .common import DATA, log

CREDENTIALS = DATA / "toss_sharelink_api_credentials.json"
CACHE = DATA / "toss_sharelink_api_cache.json"
CATEGORY_CACHE = DATA / "toss_sharelink_category_cache.json"

# Sharelink Creator Open API values shown in the official guide screenshots.
# Read-only product/ranking access requires sharelink:read. Link issuance would
# additionally require sharelink:write, separated by a space.
DEFAULT_BASE = "https://sharelink.toss.im/openapi"
DEFAULT_TOKEN_PATH = "https://oauth2.cert.toss.im/token"
DEFAULT_SCOPE = "sharelink:read"
DEFAULT_FEED_PATH = "/products/best-selling"
DEFAULT_BEST_CATEGORIES_PATH = "/products/best-categories/{categoryId}"
DEFAULT_CATEGORIES_PATH = "/categories"  # optional/legacy helper only; never required for connection
DEFAULT_BEST_SELLING_PATH = "/products/best-selling"
SHARELINK_ALT_BASE = "https://sharelink.toss.im/openapi"
DEFAULT_HEALTH_PATH = "/health"
OAUTH_METADATA_URLS = ("https://oauth2.cert.toss.im/.well-known/oauth-authorization-server", "https://oauth2.cert.toss.im/.well-known/openid-configuration")
LEGACY_SHOPPING_BASE = "https://shopping-fep.toss.im"
ENDPOINT_CACHE = DATA / "toss_sharelink_endpoint_cache.json"
LEGACY_SHOPPING_SCOPE = "toss-shopping-fep:write"

_LOCK = threading.Lock()
_TOKEN = {"value":"", "expires_at":0.0}


def _read_json(path, default):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:return default


def _settings():
    return _read_json(DATA/"settings.json",{})


def _normalize_path(value, default=""):
    """Accept a URL, /path, or copied docs string such as `GET /path`."""
    s=" ".join(str(value or default or "").strip().split())
    s=re.sub(r"^(GET|POST|PUT|PATCH|DELETE|HEAD)\s+", "", s, flags=re.I).strip()
    # Strip accidental surrounding quotes/backticks copied from docs.
    s=s.strip("`'\"")
    if not s:return str(default or "")
    if s.startswith(("http://","https://")):return s
    return "/"+s.lstrip("/")

def _normalize_sharelink_api_path(value, default=""):
    """Normalize a Sharelink path relative to a base that already ends in /openapi."""
    s=_normalize_path(value,default)
    if s.startswith(("http://","https://")):
        return s
    if s=="/openapi":return "/"
    if s.startswith("/openapi/"):
        s=s[len("/openapi"):]
    return s or "/"


def _migrate_legacy_base(base):
    b=str(base or "").strip().rstrip("/")
    if not b or b==LEGACY_SHOPPING_BASE:
        return DEFAULT_BASE
    # Old builds sometimes saved the Sharelink host without its /openapi prefix.
    if b=="https://sharelink.toss.im":
        return DEFAULT_BASE
    return b


def _parse_category_ids(value):
    if isinstance(value,(list,tuple,set)):
        parts=value
    else:
        parts=re.split(r"[,;\s]+",str(value or "").strip())
    out=[]
    for x in parts:
        s=str(x).strip()
        if not s:continue
        # Category IDs are documented as path identifiers; preserve non-numeric
        # values defensively in case Toss changes the schema.
        if s not in out:out.append(s)
    return out


def credentials():
    cfg=_settings();obj=_read_json(CREDENTIALS,{})
    def pick(env,key,default=""):
        return str(os.environ.get(env) or cfg.get("toss_sharelink_"+key) or obj.get(key) or default).strip()
    cats=os.environ.get("TOSS_SHARELINK_CATEGORY_IDS") or cfg.get("toss_sharelink_category_ids") or obj.get("category_ids") or []
    base=_migrate_legacy_base(pick("TOSS_SHARELINK_BASE_URL","base_url",DEFAULT_BASE))
    scope=pick("TOSS_SHARELINK_SCOPE","scope",DEFAULT_SCOPE)
    feed=_normalize_sharelink_api_path(pick("TOSS_SHARELINK_FEED_PATH","feed_path",DEFAULT_FEED_PATH),DEFAULT_FEED_PATH)
    cats_path=_normalize_sharelink_api_path(pick("TOSS_SHARELINK_CATEGORIES_PATH","categories_path",DEFAULT_CATEGORIES_PATH),DEFAULT_CATEGORIES_PATH)
    best_path=_normalize_sharelink_api_path(pick("TOSS_SHARELINK_BEST_SELLING_PATH","best_selling_path",DEFAULT_BEST_SELLING_PATH),DEFAULT_BEST_SELLING_PATH)
    # Migrate old builds to the official Creator read scope and global best-selling feed.
    if not scope.strip() or scope.strip()==LEGACY_SHOPPING_SCOPE:
        scope=DEFAULT_SCOPE
    if "best-categories" in feed or "{categoryId}" in feed or "{category_id}" in feed:
        feed=DEFAULT_FEED_PATH
    return {
        "access_key":pick("TOSS_SHARELINK_ACCESS_KEY","access_key"),
        "secret_key":pick("TOSS_SHARELINK_SECRET_KEY","secret_key"),
        "access_token":pick("TOSS_SHARELINK_ACCESS_TOKEN","access_token"),
        "publisher_id":pick("TOSS_SHARELINK_PUBLISHER_ID","publisher_id"),
        "base_url":base,
        "token_path":_normalize_path(pick("TOSS_SHARELINK_TOKEN_PATH","token_path",DEFAULT_TOKEN_PATH),DEFAULT_TOKEN_PATH),
        "scope":scope,
        "feed_path":feed,
        "categories_path":cats_path,
        "best_selling_path":best_path,
        "category_ids":_parse_category_ids(cats),
    }


def save_credentials(access_key="",secret_key="",publisher_id="",access_token="",base_url=DEFAULT_BASE,
                     token_path=DEFAULT_TOKEN_PATH,feed_path=DEFAULT_FEED_PATH,scope=DEFAULT_SCOPE,
                     category_ids=None,categories_path=DEFAULT_CATEGORIES_PATH,best_selling_path=DEFAULT_BEST_SELLING_PATH):
    base=_migrate_legacy_base(base_url or DEFAULT_BASE)
    sc=str(scope or "").strip()
    if not sc or sc==LEGACY_SHOPPING_SCOPE:sc=DEFAULT_SCOPE
    fp=_normalize_sharelink_api_path(feed_path,DEFAULT_FEED_PATH)
    if "best-categories" in fp or "{categoryId}" in fp or "{category_id}" in fp:
        fp=DEFAULT_FEED_PATH
    cp=_normalize_sharelink_api_path(categories_path,DEFAULT_CATEGORIES_PATH)
    bp=_normalize_sharelink_api_path(best_selling_path,DEFAULT_BEST_SELLING_PATH)
    obj={"access_key":str(access_key).strip(),"secret_key":str(secret_key).strip(),
         "publisher_id":str(publisher_id).strip(),"access_token":str(access_token).strip(),
         "base_url":base,"token_path":_normalize_path(token_path,DEFAULT_TOKEN_PATH),
         "scope":sc,"feed_path":fp,"categories_path":cp,"best_selling_path":bp,
         "category_ids":_parse_category_ids(category_ids or [])}
    if not obj["access_token"] and not (obj["access_key"] and obj["secret_key"]):
        raise ValueError("Access Token 또는 Access Key + Secret Key가 필요합니다.")
    CREDENTIALS.parent.mkdir(parents=True,exist_ok=True)
    CREDENTIALS.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    _TOKEN.update(value="",expires_at=0.0)
    return str(CREDENTIALS)


def ready():
    c=credentials();return bool(c["access_token"] or (c["access_key"] and c["secret_key"]))


def health():
    c=credentials()
    if not ready():
        return {"ready":False,"name":"토스 Sharelink Open API","message":"API 키 미설정 · 97_TOSS_SHARELINK_API_SETUP.cmd에서 등록하세요."}
    mode="고정 Access Token" if c["access_token"] else "OAuth2 client_credentials"
    key=c["access_key"] or c["access_token"]
    cat=(",".join(c.get("category_ids",[])[:3]) if c.get("category_ids") else "자동탐색")
    scope_label=c['scope'] or DEFAULT_SCOPE
    return {"ready":True,"name":"토스 Sharelink Open API",
            "message":f"{mode} 저장됨 · {key[:4]}…{key[-3:]} · Sharelink scope={scope_label} · category={cat}"}


def _join(base,path):
    path=_normalize_path(path)
    if str(path).startswith(("http://","https://")):return str(path)
    return base.rstrip("/")+"/"+str(path).lstrip("/")


def _endpoint_candidates(c, kind):
    """Sharelink-only endpoint candidates. Never mix ordinary Shopping FEP URLs."""
    base=_migrate_legacy_base(c.get("base_url") or DEFAULT_BASE).rstrip("/")
    alts=[]
    def add_path(path):
        path=_normalize_sharelink_api_path(path)
        url=_join(base,path)
        if url and url not in alts:alts.append(url)
    if kind=="health":
        add_path(DEFAULT_HEALTH_PATH)
    elif kind=="best":
        add_path(c.get("best_selling_path") or DEFAULT_BEST_SELLING_PATH)
        add_path(DEFAULT_BEST_SELLING_PATH)
    elif kind=="categories":
        # The API is in pilot; keep only Sharelink-host candidates and never use
        # the unrelated shopping-fep category tree.
        for path in (c.get("categories_path") or DEFAULT_CATEGORIES_PATH,
                     DEFAULT_CATEGORIES_PATH,"/products/categories","/product-categories"):
            add_path(path)
    return alts


def _headers_for_api(c,token):
    headers={"Accept":"application/json","Authorization":"Bearer "+token}
    if c.get("publisher_id"):
        headers["X-Publisher-Id"]=c["publisher_id"];headers["Publisher-Id"]=c["publisher_id"]
    return headers


def _record_endpoint(kind,url):
    obj=_read_json(ENDPOINT_CACHE,{})
    obj[kind]={"url":url,"saved_at":time.time()}
    try:ENDPOINT_CACHE.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:pass


def _cached_endpoint(kind,ttl=86400):
    obj=_read_json(ENDPOINT_CACHE,{})
    row=obj.get(kind) or {};url=str(row.get("url") or "")
    # Never resurrect stale shopping-fep endpoints saved by v7.47.2/3.
    if url and "sharelink.toss.im/openapi" in url and time.time()-float(row.get("saved_at") or 0)<ttl:
        return url
    return ""


def _probe_best_endpoint(size=3):
    """Find a working Sharelink product-list endpoint and return rows + URL."""
    c=credentials();token=_access_token();headers=_headers_for_api(c,token)
    cached=_cached_endpoint("best")
    urls=([cached] if cached else [])+_endpoint_candidates(c,"best")
    seen=set();errors=[]
    for u in urls:
        if not u or u in seen:continue
        seen.add(u)
        try:
            rows=_feed_rows_from_url(u,max(1,min(int(size),10)),headers)
            if rows:
                _record_endpoint("best",u);return rows,u,errors
            errors.append(u+": 상품 0건")
        except Exception as e:
            errors.append(u+": "+str(e))
    raise RuntimeError("Sharelink 베스트 상품 endpoint 자동탐색 실패: "+" / ".join(errors[-5:]))


def _api_error_from_obj(obj):
    if not isinstance(obj,dict):return ""
    err=obj.get("error")
    if isinstance(err,dict):
        return str(err.get("errorCode") or err.get("code") or err.get("reason") or err.get("message") or "")
    if err:return str(err)
    return str(obj.get("errorCode") or obj.get("code") or "")


class TossAPIHTTPError(RuntimeError):
    def __init__(self,status,body="",headers=None,url=""):
        self.status=int(status or 0);self.body=str(body or "");self.headers=dict(headers or {});self.url=str(url or "")
        super().__init__(f"토스 API HTTP {self.status}: {self.body[:1200]}")


def _request_json(url,method="GET",headers=None,data=None,timeout=20):
    raw=None
    if data is not None:
        raw=data if isinstance(data,(bytes,bytearray)) else urllib.parse.urlencode(data).encode("utf-8")
    req=urllib.request.Request(url,data=raw,method=method,headers=headers or {})
    try:
        with urllib.request.urlopen(req,timeout=float(timeout)) as r:
            body=r.read(5*1024*1024).decode("utf-8","replace")
            try:obj=json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:obj={"raw":body}
            return obj,dict(r.headers)
    except urllib.error.HTTPError as e:
        detail=e.read(12000).decode("utf-8","replace") if hasattr(e,"read") else str(e)
        raise TossAPIHTTPError(e.code,detail,dict(e.headers or {}),url)
    except Exception as e:
        if isinstance(e,TossAPIHTTPError):raise
        raise RuntimeError("토스 API 호출 실패: "+str(e))


def _header(headers,name):
    for k,v in (headers or {}).items():
        if str(k).lower()==str(name).lower():return str(v)
    return ""


def _required_scope_from_error(exc):
    """Extract an OAuth scope only when the resource server explicitly advertises it."""
    headers=getattr(exc,"headers",{}) or {}
    challenge=_header(headers,"WWW-Authenticate")
    patterns=[r'(?i)scope\s*=\s*"([^"]+)"',r"(?i)scope\s*=\s*'([^']+)'",r'(?i)required[_ -]?scope[s]?\s*[:=]\s*([A-Za-z0-9:._/-]+)']
    texts=[challenge,getattr(exc,"body","") or ""]
    for text in texts:
        for pat in patterns:
            m=re.search(pat,str(text or ""))
            if m and m.group(1).strip():return m.group(1).strip()
    return ""


def _event_id_from_error(exc):
    return _header(getattr(exc,"headers",{}) or {},"x-toss-event-id") or _header(getattr(exc,"headers",{}) or {},"x-request-id")


def _jwt_claims(token):
    """Decode JWT payload without verifying signature; diagnostic metadata only."""
    try:
        parts=str(token or "").split(".")
        if len(parts)<2:return {}
        raw=parts[1]+"="*((4-len(parts[1])%4)%4)
        return json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8","replace"))
    except Exception:return {}


def discover_scope_candidates():
    """Read OAuth server metadata and return only server-advertised Sharelink scopes."""
    found=[]
    for url in OAUTH_METADATA_URLS:
        try:
            obj,_=_request_json(url,"GET",{"Accept":"application/json"},None,8)
            vals=obj.get("scopes_supported") or obj.get("scopesSupported") or []
            if isinstance(vals,str):vals=re.split(r"[ ,]+",vals)
            for x in vals or []:
                x=str(x or "").strip()
                if x and "sharelink" in x.lower() and x not in found:found.append(x)
        except Exception:
            pass
    return found

def discover_oauth_scopes_all():
    """Return all scopes explicitly advertised by Toss OAuth metadata.

    This is diagnostic/negotiation only.  We never invent arbitrary permission
    names and never treat the ordinary Shopping-FEP scope as Sharelink scope.
    """
    found=[];sources=[]
    for url in OAUTH_METADATA_URLS:
        try:
            obj,_=_request_json(url,"GET",{"Accept":"application/json"},None,8)
            vals=obj.get("scopes_supported") or obj.get("scopesSupported") or []
            if isinstance(vals,str):vals=re.split(r"[ ,]+",vals)
            vals=[str(x or "").strip() for x in (vals or []) if str(x or "").strip()]
            if vals:sources.append({"url":url,"scopes":vals})
            for x in vals:
                if x not in found:found.append(x)
        except Exception:
            pass
    return found,sources


def _likely_sharelink_scopes(scopes):
    """Prioritize only server-advertised scopes that look relevant to Sharelink."""
    ranked=[]
    for s in scopes or []:
        low=str(s).lower()
        if s==LEGACY_SHOPPING_SCOPE:continue
        score=0
        if "sharelink" in low:score+=100
        if "product" in low:score+=40
        if "shopping" in low:score+=20
        if "openapi" in low or "open-api" in low:score+=20
        if "read" in low:score+=15
        if "write" in low:score+=3
        if score:ranked.append((-score,str(s)))
    ranked.sort()
    return [s for _,s in ranked]


def _health_with_scope(scope):
    """Request a token with one explicit server-advertised scope and test health."""
    c=credentials();url=_join(DEFAULT_BASE,DEFAULT_HEALTH_PATH)
    try:
        obj,_=_oauth_try(_join(c["base_url"],c["token_path"]),c,scope,False)
        token=str(obj.get("access_token") or obj.get("accessToken") or (obj.get("data") or {}).get("accessToken") or "").strip()
        if not token:return {"ok":False,"scope":scope,"stage":"token","error":"access_token 없음"}
        granted=obj.get("scope") or ""
        claims=_jwt_claims(token)
        if not granted:
            granted=claims.get("scope") or claims.get("scp") or ""
        if isinstance(granted,(list,tuple)):granted=" ".join(str(x) for x in granted)
        headers=_headers_for_api(c,token)
        robj,rhdr=_request_json(url,"GET",headers,None,float(_settings().get("toss_sharelink_api_timeout_sec",20)))
        _validate_api_obj(robj)
        return {"ok":True,"scope":scope,"granted_scope":str(granted or ""),"response":robj,"headers":rhdr,"endpoint":url}
    except Exception as e:
        return {"ok":False,"scope":scope,"stage":"health" if not isinstance(e,urllib.error.HTTPError) else "http",
                "http_status":getattr(e,"status",0),"error":str(e),"event_id":_event_id_from_error(e),
                "body":getattr(e,"body","")[:1200] if getattr(e,"body","") else ""}


def auto_negotiate_sharelink_scope(max_candidates=12):
    """Compatibility wrapper: enforce the documented read scope and test /health."""
    c=credentials()
    if (c.get("scope") or "").strip()!=DEFAULT_SCOPE:
        _persist_scope(DEFAULT_SCOPE)
    h=sharelink_health_test(auto_scope=False)
    return {"ok":bool(h.get("ok")),"scope":DEFAULT_SCOPE if h.get("ok") else "","health":h,
            "attempts":[{"scope":DEFAULT_SCOPE,"ok":bool(h.get("ok")),"http_status":h.get("http_status",0)}],
            "metadata_scopes":[],"metadata_sources":[],"auto_fixed":True if h.get("ok") else False,
            "server_permission_missing":bool(h.get("permission_missing")),"reason":h.get("reason") or ""}


def write_connection_diagnostic(result=None):
    """Write a support-safe diagnostic report without Access/Secret/token values."""
    c=credentials();result=result or {}
    report={
      "generated_at":time.strftime("%Y-%m-%d %H:%M:%S"),
      "public_ip":public_ip(),
      "api_base":DEFAULT_BASE,"token_url":DEFAULT_TOKEN_PATH,"health_url":_join(DEFAULT_BASE,DEFAULT_HEALTH_PATH),
      "publisher_id":c.get("publisher_id") or "",
      "access_key_masked":((c.get("access_key") or "")[:4]+"…"+(c.get("access_key") or "")[-3:]) if c.get("access_key") else "",
      "configured_scope":c.get("scope") or "",
      "result":result,
    }
    # scrub anything that could accidentally be secret/token-like
    raw=json.dumps(report,ensure_ascii=False,indent=2)
    for secret in (c.get("secret_key") or "", c.get("access_token") or "", _TOKEN.get("value") or ""):
        if secret:raw=raw.replace(secret,"***REDACTED***")
    path=DATA/"toss_sharelink_connection_diagnostic.json"
    path.write_text(raw,encoding="utf-8")
    return str(path)


def _persist_scope(scope):
    scope=str(scope or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
    obj=_read_json(CREDENTIALS,{})
    obj["scope"]=scope
    obj["base_url"]=DEFAULT_BASE
    CREDENTIALS.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    _TOKEN.update(value="",expires_at=0.0)


def _is_private_ip(value):
    try:return ipaddress.ip_address(str(value).strip()).is_private
    except Exception:return False


def public_ip(timeout=5):
    """Best-effort public egress IPv4 lookup used only for diagnostics."""
    urls=("https://api.ipify.org","https://checkip.amazonaws.com")
    for u in urls:
        try:
            req=urllib.request.Request(u,headers={"User-Agent":"NaverBlogAutomationStudio/7.47.5"})
            with urllib.request.urlopen(req,timeout=float(timeout)) as r:
                val=r.read(128).decode("utf-8","replace").strip()
            ip=ipaddress.ip_address(val)
            if not ip.is_private and not ip.is_loopback:return str(ip)
        except Exception:pass
    return ""


def _diagnostic_message(exc):
    s=str(exc);low=s.lower()
    if "invalid_scope" in low:
        return "Sharelink Creator 문서 기준 조회 scope는 sharelink:read 입니다. 저장 scope와 발급 키 종류를 확인하세요."
    if "client granted oauth scope: []" in low or "granted oauth scope: []" in low:
        return "토큰이 scope 없이 발급되었습니다. v7.47.6은 공식 문서대로 scope=sharelink:read를 토큰 요청 본문에 반드시 전송합니다."
    if "SHARELINK_OPENAPI_ACCESS_DENIED" in s:
        pip=public_ip();suffix=(f" 현재 이 PC의 외부 공인 IP는 {pip} 입니다." if pip else "")
        return "Sharelink API 출발지 IP 허용목록 오류입니다."+suffix
    if "404" in s:
        return "Sharelink API host/path가 맞지 않습니다. v7.47.4는 production base를 https://sharelink.toss.im/openapi 로 고정하고 shopping-fep host를 사용하지 않습니다."
    if "401" in s or "invalid_client" in low or "unauthorized" in low:
        return "Sharelink 인증/권한 오류입니다. Access Key/Secret Key와 Creator 어드민의 Open API 권한 상태를 확인하세요."
    if "403" in s:
        pip=public_ip();suffix=(f" 현재 공인 IP={pip}." if pip else "")
        return "403이면 등록 출발지 공인 IP 또는 해당 Sharelink 키 권한을 확인하세요."+suffix
    return "Sharelink Creator 어드민의 Open API 권한, 등록 공인 IP, Access/Secret Key 상태를 확인하세요."


def _oauth_try(url,c,scope=None,basic=False):
    headers={"Accept":"application/json; charset=UTF-8","Content-Type":"application/x-www-form-urlencoded"}
    form={"grant_type":"client_credentials"}
    if basic:
        raw=(c["access_key"]+":"+c["secret_key"]).encode("utf-8")
        headers["Authorization"]="Basic "+base64.b64encode(raw).decode("ascii")
    else:
        form.update(client_id=c["access_key"],client_secret=c["secret_key"])
    if scope:
        form["scope"]=scope
    return _request_json(url,"POST",headers,form)


def _access_token(force=False):
    c=credentials()
    if c["access_token"]:return c["access_token"]
    now=time.time()
    with _LOCK:
        if not force and _TOKEN["value"] and _TOKEN["expires_at"]>now+60:return _TOKEN["value"]
        if not (c["access_key"] and c["secret_key"]):raise RuntimeError("토스 Sharelink API 키가 설정되지 않았습니다.")
        url=_join(c["base_url"],c["token_path"])
        configured_scope=(c.get("scope") or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
        # Official Sharelink Creator flow: application/x-www-form-urlencoded body
        # with grant_type, client_id, client_secret and scope=sharelink:read.
        attempts=[("body+official_scope",configured_scope,False)]
        errors=[];obj=None;mode=""
        for label,scope,basic in attempts:
            try:
                obj,_=_oauth_try(url,c,scope,basic);mode=label;break
            except Exception as e:
                errors.append(label+": "+str(e))
        if obj is None:
            joined=" / ".join(errors[-3:])
            raise RuntimeError("토스 Sharelink OAuth 토큰 발급 실패: "+joined+" | "+_diagnostic_message(joined))
        token=str(obj.get("access_token") or obj.get("accessToken") or (obj.get("data") or {}).get("accessToken") or "").strip()
        if not token:
            raise RuntimeError("토스 Sharelink 토큰 응답에 access_token이 없습니다: "+str(obj)[:700])
        exp=int(obj.get("expires_in") or obj.get("expiresIn") or (obj.get("data") or {}).get("expiresIn") or 3600)
        claims=_jwt_claims(token)
        claim_scope=claims.get("scope") or claims.get("scp") or ""
        if isinstance(claim_scope,(list,tuple)):claim_scope=" ".join(str(x) for x in claim_scope)
        granted_scope=str(obj.get("scope") or claim_scope or configured_scope or "").strip()
        _TOKEN.update(value=token,expires_at=now+max(60,exp),mode=mode,scope=granted_scope,claims=claims)
        return token


def token_test():
    token=_access_token(True)
    return {"ok":bool(token),"token_prefix":token[:6]+"…" if token else "",
            "scope":str(_TOKEN.get("scope") or credentials().get("scope") or DEFAULT_SCOPE),
            "oauth_mode":str(_TOKEN.get("mode") or "fixed_access_token"),
            "public_ip":public_ip()}

def sharelink_health_test(auto_scope=True):
    """Official step 2: GET /openapi/health with Bearer token."""
    c=credentials();url=_join(DEFAULT_BASE,DEFAULT_HEALTH_PATH)
    try:
        token=_access_token(False)
        headers=_headers_for_api(c,token)
        obj,hdr=_request_json(url,"GET",headers,None,float(_settings().get("toss_sharelink_api_timeout_sec",20)))
        _validate_api_obj(obj)
        return {"ok":True,"endpoint":url,"scope":str(_TOKEN.get("scope") or c.get("scope") or DEFAULT_SCOPE),
                "response":obj,"headers":hdr,"auto_scope":False}
    except TossAPIHTTPError as e:
        return {"ok":False,"endpoint":url,"http_status":e.status,"body":(e.body or str(e))[:1800],
                "required_scope":_required_scope_from_error(e),"scope_candidates":[],"event_id":_event_id_from_error(e),
                "permission_missing":("granted oauth scope: []" in (e.body or '').lower()),"reason":_diagnostic_message(e)}
    except Exception as e:
        return {"ok":False,"endpoint":url,"http_status":getattr(e,"status",0),"body":getattr(e,"body",str(e))[:1800],
                "required_scope":"","scope_candidates":[],"event_id":_event_id_from_error(e),"reason":_diagnostic_message(e)}


def _find_lists(value):
    found=[]
    if isinstance(value,list):
        if value and all(isinstance(x,dict) for x in value):found.append(value)
        for x in value:found.extend(_find_lists(x))
    elif isinstance(value,dict):
        for x in value.values():found.extend(_find_lists(x))
    return found


def _value(obj,*keys):
    for k in keys:
        v=obj.get(k)
        if v not in (None,""):return v
    return ""


def _price(value):
    if isinstance(value,(int,float)) and value>0:return int(value)
    m=re.search(r"\d[\d,]*",str(value or ""))
    return int(m.group(0).replace(",","")) if m else None


def normalize_product(p):
    nested=p.get("product") if isinstance(p.get("product"),dict) else {}
    x=dict(nested);x.update(p)
    name=str(_value(x,"displayName","productName","itemName","name","title")).strip()
    price=_price(_value(x,"displayPrice","salePrice","discountPrice","productPrice","price","finalPrice"))
    image=str(_value(x,"imageUrl","displayImageUrl","productImage","thumbnailUrl","mainImageUrl","image")).strip()
    url=str(_value(x,"productUrl","shareUrl","shortUrl","landingUrl","url")).strip()
    item_id=str(_value(x,"tacaItemId","itemId","productId","id")).strip()
    if image.startswith("//"):image="https:"+image
    if url.startswith("//"):url="https:"+url
    cats=_value(x,"categoryIds","category_ids")
    if not isinstance(cats,list):cats=[]
    return {"name":name,"price":price,"image_url":image,"url":url,"product_id":item_id,
            "rank":_value(x,"rank"),"original_price":_price(_value(x,"originalPrice","original_price")),
            "discount_rate":_value(x,"discountRate","discount_rate"),"is_sold_out":bool(_value(x,"isSoldOut","soldOut")),
            "review_score":_value(x,"reviewScore","review_score"),"review_count":_value(x,"reviewCount","review_count"),
            "category_ids":[str(v) for v in cats],"source":"toss_sharelink_open_api","raw":p}


def _next_cursor(value):
    if isinstance(value,dict):
        for key in ("nextCursor","next_cursor","nextPageCursor"):
            if value.get(key) not in (None,""):return str(value[key])
        page=value.get("pageInfo") or value.get("pagination")
        if isinstance(page,dict):
            for key in ("nextCursor","next_cursor","cursor"):
                if page.get(key) not in (None,""):return str(page[key])
        for child in value.values():
            found=_next_cursor(child)
            if found:return found
    return ""


def _validate_api_obj(obj):
    if not isinstance(obj,dict):return
    err=obj.get("error")
    result_type=str(obj.get("resultType") or obj.get("result_type") or "").upper()
    if err or result_type in {"FAIL","FAILED","ERROR"}:
        code=_api_error_from_obj(obj)
        raise RuntimeError("토스 API 오류: "+(code+" · " if code else "")+str(err or obj)[:900])


def _extract_category_nodes(obj):
    """Flatten unknown Toss category response shapes defensively."""
    out=[];seen=set()
    def walk(v,path=""):
        if isinstance(v,dict):
            cid=_value(v,"categoryId","category_id","id")
            name=str(_value(v,"displayName","categoryName","name","title")).strip()
            if cid not in (None,"") and name:
                key=str(cid)
                if key not in seen:
                    level=_value(v,"level","depth")
                    try:level=int(level)
                    except Exception:level=max(1,path.count("/")+1)
                    seen.add(key);out.append({"category_id":key,"name":name,"path":path,"level":level,"raw":v})
            for k,x in v.items():
                if isinstance(x,(dict,list)):walk(x,(path+"/"+name).strip("/"))
        elif isinstance(v,list):
            for x in v:walk(x,path)
    walk(obj)
    return out


def get_categories(force=False):
    """Discover category IDs without failing the whole Sharelink connection on 404.

    v7.47.2 guessed two category URLs and treated their 404 as a hard failure.
    v7.47.3 probes several documented/compatible category sources. If category
    discovery still fails, callers may fall back to global best-selling.
    """
    cfg=_settings();ttl=max(60,int(cfg.get("toss_sharelink_api_category_cache_ttl_sec",21600)))
    cached=_read_json(CATEGORY_CACHE,{})
    if not force and time.time()-float(cached.get("saved_at") or 0)<ttl and cached.get("rows"):
        return cached["rows"]
    c=credentials();token=_access_token();headers=_headers_for_api(c,token)
    urls=[];cached_url=_cached_endpoint("categories")
    if cached_url:urls.append(cached_url)
    urls.extend(_endpoint_candidates(c,"categories"))
    errors=[];seen=set()
    for u in urls:
        if not u or u in seen:continue
        seen.add(u)
        try:
            obj,_=_request_json(u,"GET",headers,None,float(cfg.get("toss_sharelink_api_timeout_sec",20)))
            _validate_api_obj(obj);rows=_extract_category_nodes(obj)
            if rows:
                _record_endpoint("categories",u)
                CATEGORY_CACHE.write_text(json.dumps({"saved_at":time.time(),"rows":rows,"source_url":u},ensure_ascii=False,indent=2),encoding="utf-8")
                return rows
            errors.append(u+": category list empty")
        except Exception as e:errors.append(u+": "+str(e))
    raise RuntimeError("토스 카테고리 자동조회 불가(상품 API 인증 실패와는 별개): "+" / ".join(errors[-6:]))

def _feed_rows_from_url(base_url,size,headers):
    cfg=_settings();requested=max(1,min(int(size),500));page_size=min(100,requested);cursor="";rows=[];seen=set()
    # The official API accepts up to 100 items per request. Keep following the
    # cursor even when invalid/duplicate cards were filtered, rather than
    # precomputing a fixed page count from the requested size.
    for _page in range(20):
        params={"size":min(page_size,requested-len(rows))}
        if cursor:params["cursor"]=cursor
        sep="&" if "?" in base_url else "?";url=base_url+sep+urllib.parse.urlencode(params)
        obj,_=_request_json(url,"GET",headers,None,float(cfg.get("toss_sharelink_api_timeout_sec",20)))
        _validate_api_obj(obj)
        lists=_find_lists(obj);candidate=max(lists,key=len) if lists else []
        for raw in candidate:
            x=normalize_product(raw)
            if not x["name"] or not x["price"]:continue
            key=x["product_id"] or (x["name"].lower()+"|"+str(x["price"]))
            if key in seen:continue
            seen.add(key);rows.append(x)
            if len(rows)>=requested:break
        nxt=_next_cursor(obj)
        if len(rows)>=requested or not nxt or nxt==cursor:break
        cursor=nxt
    return rows[:requested]


def best_categories(category_id,size=30):
    c=credentials();token=_access_token();headers={"Accept":"application/json","Authorization":"Bearer "+token}
    if c["publisher_id"]:
        headers["X-Publisher-Id"]=c["publisher_id"];headers["Publisher-Id"]=c["publisher_id"]
    path=DEFAULT_BEST_CATEGORIES_PATH
    path=path.replace("{categoryId}",urllib.parse.quote(str(category_id),safe="")).replace("{category_id}",urllib.parse.quote(str(category_id),safe=""))
    return _feed_rows_from_url(_join(c["base_url"],path),size,headers)


def _auto_category_ids(limit=6):
    c=credentials()
    if c.get("category_ids"):return c.get("category_ids",[])[:limit]
    rows=get_categories(False)
    # Prefer broad top-level/common shopping category names used by the Studio.
    aliases=("생활","주방","패션","식품","가전","디지털","화장품","뷰티")
    ranked=[]
    for x in rows:
        n=x["name"]
        hit=0 if any(a in n for a in aliases) else 1
        depth=str(x.get("path") or "").count("/")
        ranked.append((hit,depth,n,x["category_id"]))
    ranked.sort()
    out=[]
    for _,_,_,cid in ranked:
        if cid not in out:out.append(cid)
        if len(out)>=limit:break
    return out


def best_selling(size=100,force=False):
    """Official step 3: GET /openapi/products/best-selling?size=N.

    Category-best is a separate explicit call via best_categories(category_id).
    Global product-list connection never depends on guessed category endpoints.
    """
    cfg=_settings();ttl=max(30,int(cfg.get("toss_sharelink_api_cache_ttl_sec",900)))
    c=credentials()
    # Cache rows belong to the configured Sharelink account.  v7.55 packaged
    # an audit-created cache without an account marker, which could be mistaken
    # for a real live feed immediately after extraction.  Unmarked/other-key
    # caches are ignored.
    fp=hashlib.sha256((str(c.get("access_key") or c.get("access_token") or "")+"|"+str(c.get("publisher_id") or "")+"|"+str(c.get("base_url") or "")).encode("utf-8")).hexdigest()[:20]
    cached=_read_json(CACHE,{})
    if not force and cached.get("credential_fingerprint")==fp and time.time()-float(cached.get("saved_at") or 0)<ttl and isinstance(cached.get("rows"),list):
        return cached["rows"][:int(size)]
    token=_access_token();headers=_headers_for_api(c,token)
    requested=max(1,min(int(size),500))
    feed=c.get("best_selling_path") or DEFAULT_BEST_SELLING_PATH
    rows=_feed_rows_from_url(_join(c["base_url"],feed),requested,headers)
    CACHE.write_text(json.dumps({"saved_at":time.time(),"credential_fingerprint":fp,"rows":rows,"endpoint":_join(c["base_url"],feed)},ensure_ascii=False,indent=2),encoding="utf-8")
    return rows[:requested]


def connection_test():
    """Official 3-step verification: token -> /health -> best-selling?size=5."""
    if not ready():raise RuntimeError(health()["message"])
    token_info=token_test()
    h=sharelink_health_test(auto_scope=False)
    if not h.get("ok"):
        extra=(f" · x-toss-event-id={h.get('event_id')}" if h.get("event_id") else "")
        raise RuntimeError("Sharelink /health 연결 실패: "+str(h.get("reason") or h.get("body") or "")+extra)
    rows=best_selling(5,True)
    if not rows:raise RuntimeError("Sharelink best-selling 응답은 성공했지만 상품 items가 0건입니다.")
    c=credentials();cat_ids=[]
    for row in rows:
        for cid in row.get("category_ids") or []:
            if cid not in cat_ids:cat_ids.append(cid)
    return {"ok":True,"token_ok":token_info["ok"],"scope":token_info.get("scope") or DEFAULT_SCOPE,
            "health_endpoint":h.get("endpoint"),"health_ok":True,
            "endpoint":_join(c["base_url"],c.get("best_selling_path") or DEFAULT_BEST_SELLING_PATH)+"?size=5",
            "count":len(rows),"category_ok":bool(cat_ids),"category_ids":cat_ids[:20],
            "sample":[{k:x.get(k) for k in ("rank","name","price","original_price","image_url","url","category_ids")} for x in rows[:5]]}
