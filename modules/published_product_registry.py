# -*- coding: utf-8 -*-
"""Durable product-level deduplication for successfully saved Naver drafts.

The older blog history prevents an identical *article* from being clicked twice,
but it is deliberately mode/title/body sensitive.  This ledger has a different
job: once Naver positively confirms a temporary save, the physical product is
excluded from later discovery runs even when another marketplace uses a longer
seller title or a different URL.

Only confirmed draft saves are recorded.  Failed and ambiguous saves never call
``record_published_product`` and therefore remain eligible for a later run.
"""
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from collections.abc import Sequence
from typing import TypedDict
import hashlib, json, os, re, sqlite3, threading, time

from .common import (
    DATA, DB, clean_listing_title_noise, critical_identity_tokens,
    identity_terms, log, settings,
)

REGISTRY_PATH=DATA/"published_product_registry.json"
REGISTRY_VERSION=2
_LOCK=threading.RLock()


class RegistryRecord(TypedDict, total=False):
    key: str
    name: str
    blog_id: str
    canonical: str
    base_canonical: str
    terms: list[str]
    critical: list[str]
    models: list[str]
    core_compact: str
    source_ids: list[str]
    sources: list[str]
    last_saved_at: str
    matched_post_titles: list[str]
    matched_post_urls: list[str]


class SourcePost(TypedDict, total=False):
    title: str
    url: str
    source: str
    blog_id: str
    published_at: str

_CORE_GENERIC={
    "제품","상품","정품","공식","추천","단품","세트","구성","선택","옵션",
    "무료배송","로켓배송","당일배송","색상","사이즈","화이트","블랙","그레이",
    "국내산","수입","신형","NEW","new",
}

def _value(row,key,default=""):
    try:return row[key]
    except Exception:
        try:return row.get(key,default)
        except Exception:return default

def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _canonical_name(name):
    cleaned=clean_listing_title_noise(str(name or "")).lower()
    return re.sub(r"[^가-힣a-z0-9]+","",cleaned)

def _base_product_canonical(name):
    """Canonical product identity with seller option/spec tokens removed.

    This is intentionally used only for the *already drafted product* registry.
    A 500 ml / 1 L, 1-pack / 2-pack, 256 GB / 512 GB, colour or clothing-size
    option is still the same product for the user's collection policy. Model
    identifiers remain in the string and are checked separately.
    """
    s=clean_listing_title_noise(str(name or "")).lower()
    # N+N promotions and multiplied pack/size forms.
    s=re.sub(r"(?i)\b\d+\s*\+\s*\d+\s*(?:개입|개|매|팩|세트|롤|병|캔|포|봉|장|정|캡슐)\b"," ",s)
    s=re.sub(r"(?i)(?:x|×|\*)\s*\d+\s*(?:개|팩|세트|병|캔|포|봉|장|정|캡슐)?\b"," ",s)
    # Capacity / count / physical dimension / digital-storage options.
    s=re.sub(r"(?i)\b\d+(?:\.\d+)?\s*(?:ml|kg|mg|cm|mm|oz|tb|gb|mb|l|g|개입|개|매|팩|세트|인치|롤|병|캔|포|봉|장|겹|정|캡슐|호)\b"," ",s)
    s=re.sub(r"(?i)\b\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?\s*(?:cm|mm|m)?\b"," ",s)
    # Common selectable colour / apparel-size option words.
    s=re.sub(r"(?i)(?<![a-z0-9])(?:xs|s|m|l|xl|xxl|xxxl)(?![a-z0-9])"," ",s)
    s=re.sub(r"(?:화이트|블랙|그레이|회색|실버|골드|베이지|브라운|네이비|블루|레드|핑크|그린|옐로우|퍼플|오렌지)"," ",s)
    s=re.sub(r"\b\d{2,4}\s*(?:사이즈|size|호)\b"," ",s,flags=re.I)
    s=re.sub(r"[^가-힣a-z0-9]+","",s)
    return s

def _normalize_critical(token):
    value=re.sub(r"\s+","",str(token or "")).lower().replace("_","-")
    value=re.sub(r"^(\d+)개입$",r"\1개",value)
    value=re.sub(r"^(\d+)매입$",r"\1매",value)
    return value

def _product_source_ids(url):
    """Return only product-specific IDs; category/search URLs are ignored."""
    raw=str(url or "").strip()
    if not raw:return []
    try:
        parsed=urlparse(raw);host=(parsed.hostname or "").lower();path=parsed.path or ""
    except Exception:return []
    out=[]
    patterns=[]
    coupang=host=="coupang.com" or host.endswith(".coupang.com")
    naver=host=="naver.com" or host.endswith(".naver.com")
    toss=host=="toss.im" or host.endswith(".toss.im")
    wala=host in {"wala-land.com","www.wala-land.com"}
    if parsed.scheme not in {"http","https"} or parsed.username:return []
    if coupang:
        patterns=[("coupang",r"^/(?:vp/)?products/(\d+)(?:/|$)")]
    elif naver:
        patterns=[("naver_catalog",r"/catalog/(\d+)(?:/|$)"),("naver_product",r"/products/(\d+)(?:/|$)")]
    elif toss:
        patterns=[("toss_product",r"/(?:products?|items?)/([A-Za-z0-9_-]{5,})(?:/|$)")]
    elif wala:
        patterns=[("wala_content",r"^/(?:ko/|en/)?content/(\d+)(?:/|$)"),("wala_product",r"^/(?:ko/|en/)?products/(\d+)(?:/|$)")]
    for prefix,pattern in patterns:
        m=re.search(pattern,path,re.I)
        if m:out.append(prefix+":"+m.group(1).lower())
    if coupang or naver or toss:
        try:query=parse_qs(parsed.query)
        except Exception:query={}
        for key in ("productId","product_id","catalogId","catalog_id","itemId","item_id","vendorItemId"):
            for value in query.get(key,[]):
                value=re.sub(r"[^A-Za-z0-9_-]","",str(value))
                if len(value)>=4:out.append(host+":"+key.lower()+":"+value.lower())
    return list(dict.fromkeys(out))

def product_profile(name,url=""):
    cleaned=clean_listing_title_noise(str(name or ""))
    critical=[_normalize_critical(x) for x in critical_identity_tokens(cleaned)]
    critical=list(dict.fromkeys(x for x in critical if x))
    terms=[]
    critical_flat={re.sub(r"[^가-힣a-z0-9]","",x) for x in critical}
    for token in identity_terms(cleaned):
        low=str(token).lower()
        flat=re.sub(r"[^가-힣a-z0-9]","",low)
        normalized_flat=re.sub(r"[^가-힣a-z0-9]","",_normalize_critical(low))
        if not flat or normalized_flat in critical_flat or token in _CORE_GENERIC or low in _CORE_GENERIC:continue
        if re.fullmatch(r"\d+",flat):continue
        if low not in terms:terms.append(low)
    unit_token=re.compile(r"(?i)^\d+(?:\.\d+)?(?:ml|kg|mg|cm|mm|oz|tb|gb|mb|m|l|g|개|매|팩|세트|인치|롤|병|캔|포|봉|장|겹|정|캡슐|호)$")
    model_tokens=[x for x in critical if re.search(r"[a-z]",x) and re.search(r"\d",x) and not unit_token.fullmatch(x)]
    return {
        "name":cleaned,"canonical":_canonical_name(cleaned),"base_canonical":_base_product_canonical(cleaned),"terms":terms[:12],
        "critical":critical,"models":model_tokens,"core_compact":"".join(terms[:12]),
        "source_ids":_product_source_ids(url),
    }

def _ngram_overlap(left,right,size=2):
    left=str(left or "");right=str(right or "")
    if len(left)<size or len(right)<size:return 0.0
    lg={left[i:i+size] for i in range(len(left)-size+1)};rg={right[i:i+size] for i in range(len(right)-size+1)}
    return len(lg.intersection(rg))/max(1,min(len(lg),len(rg)))

def _same_product_profiles(left,right,min_ratio=0.72):
    lids=set(left.get("source_ids") or []);rids=set(right.get("source_ids") or [])
    if lids and rids and lids.intersection(rids):return True,"source_product_id",1.0
    lc=str(left.get("canonical") or "");rc=str(right.get("canonical") or "")
    if len(lc)>=6 and lc==rc:return True,"exact_normalized_title",1.0

    # Model identifiers remain a hard distinction. Capacity/count/colour/size
    # tokens do NOT: the user's policy treats those as the same already-written
    # product and excludes them from future discovery.
    lm=set(left.get("models") or []);rm=set(right.get("models") or [])
    if lm and rm and lm!=rm:return False,"model_variant_mismatch",0.0

    lb=str(left.get("base_canonical") or "");rb=str(right.get("base_canonical") or "")
    if not lb:lb=_base_product_canonical(left.get("name") or "")
    if not rb:rb=_base_product_canonical(right.get("name") or "")
    if len(lb)>=4 and lb==rb:
        return True,"same_product_spec_ignored",1.0

    # Once option/spec tokens are removed, an extra lexical suffix/prefix usually
    # means a different product line (e.g. iPhone Pro vs Pro Max), not a size
    # option.  Prevent semantic overlap from collapsing those products.
    if len(lb)>=5 and len(rb)>=5 and (lb.startswith(rb) or rb.startswith(lb)):
        short,long=(lb,rb) if len(lb)<=len(rb) else (rb,lb)
        extra=long[len(short):]
        if len(extra)>=2 and re.search(r"[가-힣a-z]",extra):
            return False,"product_line_suffix_mismatch",0.0

    lt=set(left.get("terms") or []);rt=set(right.get("terms") or [])
    if not lt or not rt:return False,"identity_terms_missing",0.0
    common=lt.intersection(rt);ratio=len(common)/max(1,min(len(lt),len(rt)))
    lead=set((left.get("terms") or [])[:2]).intersection((right.get("terms") or [])[:2])
    char_score=_ngram_overlap(lb or left.get("core_compact"),rb or right.get("core_compact"))
    threshold=max(0.78,float(min_ratio))
    ok=len(common)>=3 and bool(lead) and ratio>=threshold
    # Short product lines such as "제주 삼다수 500ml" vs "제주 삼다수 2L"
    # legitimately have only 1-2 semantic tokens once specs are removed.
    if not ok and bool(lead) and len(common)>=2 and char_score>=0.78:
        return True,"semantic_same_product_spec_ignored",max(ratio,char_score)
    if not ok and len(common)>=1 and len(lb)>=5 and len(rb)>=5 and char_score>=0.90:
        return True,"semantic_same_product_compound_spec_ignored",char_score
    return ok,("semantic_same_product_spec_ignored" if ok else "identity_ratio_low"),max(ratio,char_score)

def _empty_payload():
    return {"version":REGISTRY_VERSION,"updated_at":"","items":{},"meta":{"import_tokens":[]}}

def _read_payload():
    try:obj=json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:return _empty_payload()
    if not isinstance(obj,dict):raise RuntimeError("상품 이력 형식이 잘못되었습니다. 원본을 보존한 상태로 복구가 필요합니다.")
    items=obj.get("items")
    if isinstance(items,list):
        items={str(x.get("key") or i):x for i,x in enumerate(items) if isinstance(x,dict)}
    if not isinstance(items,dict):items={}
    obj["items"]={str(k):v for k,v in items.items() if isinstance(v,dict)}
    obj["version"]=REGISTRY_VERSION
    if not isinstance(obj.get("meta"),dict):obj["meta"]={}
    if not isinstance(obj["meta"].get("import_tokens"),list):obj["meta"]["import_tokens"]=[]
    return obj

def _write_payload(payload):
    REGISTRY_PATH.parent.mkdir(parents=True,exist_ok=True)
    items=list((payload.get("items") or {}).items())
    items.sort(key=lambda kv:str((kv[1] or {}).get("last_saved_at") or ""),reverse=True)
    payload["items"]=dict(items);payload["updated_at"]=_now();payload["version"]=REGISTRY_VERSION
    tokens=list(dict.fromkeys(str(x) for x in (payload.get("meta") or {}).get("import_tokens",[]) if x))
    payload.setdefault("meta",{})["import_tokens"]=tokens
    tmp=REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,REGISTRY_PATH)

def _record_profile(record):
    profile=product_profile(record.get("name") or "")
    for key in ("canonical","base_canonical","terms","critical","models","core_compact","source_ids"):
        value=record.get(key)
        if isinstance(value,list) if key not in ("canonical","base_canonical","core_compact") else isinstance(value,str):
            profile[key]=value
    return profile

def _active_scope(blog_id: str | None = None) -> str:
    from .blog_target import get_target_blog_id
    return get_target_blog_id() if blog_id is None else blog_id


def _find_match(payload,profile,blog_id=None):
    scope=_active_scope(blog_id)
    threshold=float(settings().get("published_product_match_min_ratio",0.72))
    best=None
    for key,record in (payload.get("items") or {}).items():
        if str(record.get("blog_id") or "")!=scope:continue
        ok,reason,score=_same_product_profiles(profile,_record_profile(record),threshold)
        if ok and (best is None or score>best[3]):best=(key,record,reason,score)
        if best and best[2] in ("source_product_id","exact_normalized_title"):break
    return best

def _merge_record(payload,name,url="",mode="",saved_at="",evidence_token="",source="confirmed_save",blog_id=None):
    scope=_active_scope(blog_id)
    profile=product_profile(name,url);canonical=profile.get("canonical") or ""
    if len(canonical)<3:return False,None
    tokens=payload.setdefault("meta",{}).setdefault("import_tokens",[])
    scoped_token=scope+"|"+evidence_token if scope else evidence_token
    match=_find_match(payload,profile,scope)
    if evidence_token and scoped_token in tokens and match and source in (match[1].get("sources") or []):return False,match[0]
    if match:key,record=match[0],match[1]
    else:
        seed=scope+"|"+canonical+"|"+"|".join(profile.get("critical") or [])+"|"+str(len(payload.get("items") or {}))
        key=hashlib.sha256(seed.encode("utf-8","ignore")).hexdigest()[:24]
        record={"key":key,"blog_id":scope,"name":profile["name"],"canonical":profile["canonical"],"base_canonical":profile["base_canonical"],
                "terms":profile["terms"],"critical":profile["critical"],"models":profile["models"],"core_compact":profile["core_compact"],
                "source_ids":[],"source_urls":[],"modes":[],"first_saved_at":saved_at or _now(),
                "last_saved_at":saved_at or _now(),"save_count":0,"sources":[]}
        payload.setdefault("items",{})[key]=record
    record["source_ids"]=list(dict.fromkeys([*(record.get("source_ids") or []),*(profile.get("source_ids") or [])]))[:20]
    if url:record["source_urls"]=list(dict.fromkeys([*(record.get("source_urls") or []),str(url)]))[:20]
    if mode:record["modes"]=list(dict.fromkeys([*(record.get("modes") or []),str(mode)]))
    record["sources"]=list(dict.fromkeys([*(record.get("sources") or []),str(source)]))
    record["last_saved_at"]=max(str(record.get("last_saved_at") or ""),str(saved_at or _now()))
    record["save_count"]=int(record.get("save_count") or 0)+1
    if evidence_token:tokens.append(scoped_token)
    return True,key

def _import_existing_successes(payload):
    if not bool(settings().get("published_product_import_existing_history",True)):return False
    changed=False
    history_path=DATA/"blog_upload_history.json"
    try:history=json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:history={}
    if isinstance(history,dict):
        for fingerprint,item in history.items():
            if not isinstance(item,dict) or not item.get("name"):continue
            token="history:"+str(fingerprint)
            did,_=_merge_record(payload,item.get("name"),item.get("source_url") or "",
                                item.get("mode") or "",item.get("saved_at") or "",token,"blog_history_import",str(item.get("blog_id") or ""))
            changed=changed or did
    try:
        con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
        rows=con.execute("""SELECT id,name,source_url,status,updated_at FROM products
                            WHERE COALESCE(status,'') LIKE '임시저장완료%'""").fetchall()
        con.close()
    except Exception:rows=[]
    for row in rows:
        token=f"db:{row['id']}:{row['updated_at'] or ''}:{row['status'] or ''}"
        did,_=_merge_record(payload,row["name"],row["source_url"] or "",row["status"] or "",
                            row["updated_at"] or "",token,"studio_db_import","")
        changed=changed or did
    return changed

def load_registry(import_existing=True):
    with _LOCK:
        payload=_read_payload()
        changed=_import_existing_successes(payload) if import_existing else False
        if changed:_write_payload(payload)
        return payload

def record_published_product(row,mode,post_fingerprint="",saved_at="",blog_id=None):
    """Record one product only after Naver's draft-save verification succeeded."""
    with _LOCK:
        payload=_read_payload();import_changed=_import_existing_successes(payload)
        name=str(_value(row,"name","") or "");url=str(_value(row,"source_url","") or "")
        when=saved_at or _now();token="save:"+(str(post_fingerprint) or hashlib.sha256((name+"|"+when+"|"+str(mode)).encode("utf-8","ignore")).hexdigest())
        changed,key=_merge_record(payload,name,url,str(mode or ""),when,token,"confirmed_naver_draft",blog_id)
        if changed or import_changed:_write_payload(payload)
        return {"recorded":bool(changed),"key":key,"name":name,"saved_at":when}

def record_known_published_product(name,url="",post_title="",post_url="",source="manual_existing_post",saved_at="",blog_id=None):
    """Record a user-confirmed or safely matched existing Naver post.

    This is separate from confirmed draft-save recording.  It lets products
    published outside Studio participate in the same future-collection guard.
    """
    with _LOCK:
        payload=_read_payload();import_changed=_import_existing_successes(payload)
        scope=_active_scope(blog_id)
        ignored=payload.setdefault("meta",{}).setdefault("ignored_post_matches",{})
        ignored[scope]=[profile for profile in ignored.get(scope,[]) if not _same_product_profiles(product_profile(name,url),profile)[0]]
        when=saved_at or _now()
        evidence="known:"+hashlib.sha256(
            (str(source)+"|"+str(name)+"|"+str(post_title)+"|"+str(post_url)).encode("utf-8","ignore")
        ).hexdigest()
        changed,key=_merge_record(payload,str(name or ""),str(url or ""),"already_published",when,evidence,str(source or "manual_existing_post"),blog_id)
        if key and key in (payload.get("items") or {}):
            record=payload["items"][key]
            if post_title:record["matched_post_titles"]=list(dict.fromkeys([*(record.get("matched_post_titles") or []),str(post_title)]))[:20]
            if post_url:record["matched_post_urls"]=list(dict.fromkeys([*(record.get("matched_post_urls") or []),str(post_url)]))[:20]
        if changed or import_changed:_write_payload(payload)
        return {"recorded":bool(changed),"key":key,"name":str(name or ""),"saved_at":when}

def remove_known_published_product(name,url="",sources=None,blog_id=None):
    """Remove only manual/automatic-existing evidence, preserving real save history."""
    removable=set(sources or ("manual_existing_post","naver_rss_existing_post","title_file_existing_post"))
    with _LOCK:
        payload=_read_payload();profile=product_profile(name,url);scope=_active_scope(blog_id);match=_find_match(payload,profile,scope)
        ignored=payload.setdefault("meta",{}).setdefault("ignored_post_matches",{}).setdefault(scope,[])
        if not any(_same_product_profiles(profile,previous)[0] for previous in ignored):ignored.append(profile)
        if not match:
            _write_payload(payload)
            return {"removed":False,"kept":False}
        key,record=match[0],match[1]
        old_sources=list(record.get("sources") or [])
        record["sources"]=[value for value in old_sources if value not in removable]
        durable=[value for value in record["sources"] if value in ("confirmed_naver_draft","blog_history_import","studio_db_import")]
        if durable:
            record["matched_post_titles"]=[];record["matched_post_urls"]=[]
            _write_payload(payload)
            return {"removed":True,"kept":True,"key":key}
        payload.get("items",{}).pop(key,None);_write_payload(payload)
        return {"removed":True,"kept":False,"key":key}

def filter_published_candidates(rows,blog_id=None):
    """Split discovery rows into fresh candidates and already-drafted products."""
    if not bool(settings().get("collection_skip_published_products",True)):
        return list(rows),[]
    scope=_active_scope(blog_id)
    if not scope:return list(rows),[]
    payload=load_registry(import_existing=True)
    items={key:record for key,record in (payload.get("items") or {}).items() if str(record.get("blog_id") or "")==scope}
    kept=[];excluded=[];threshold=float(settings().get("published_product_match_min_ratio",0.72))
    exact_names={str(r.get("canonical") or ""): (k,r) for k,r in items.items() if r.get("canonical")}
    source_index={sid:(k,r) for k,r in items.items() for sid in (r.get("source_ids") or [])}
    profiles=[(k,r,_record_profile(r)) for k,r in items.items()]
    for row in rows:
        profile=product_profile(_value(row,"name",""),_value(row,"url","") or _value(row,"source_url",""))
        hit=None
        for sid in profile.get("source_ids") or []:
            if sid in source_index:
                k,r=source_index[sid];hit=(k,r,"source_product_id",1.0);break
        if hit is None and profile.get("canonical") in exact_names:
            k,r=exact_names[profile["canonical"]];hit=(k,r,"exact_normalized_title",1.0)
        if hit is None:
            for k,r,rprofile in profiles:
                ok,reason,score=_same_product_profiles(profile,rprofile,threshold)
                if ok and (hit is None or score>hit[3]):hit=(k,r,reason,score)
        if hit is None:hit=_find_post_title_match(payload,profile,scope)
        if hit is None:kept.append(row);continue
        record=hit[1]
        excluded.append({
            "platform":_value(row,"platform",""),"category":_value(row,"category",""),
            "name":_value(row,"name",""),"url":_value(row,"url",""),
            "matched_name":record.get("name") or "","saved_at":record.get("last_saved_at") or "",
            "match_reason":hit[2],"match_score":round(float(hit[3]),4),"registry_key":hit[0],
            "blog_id":scope,"evidence_sources":list(record.get("sources") or []),
        })
    return kept,excluded

def registry_summary():
    payload=load_registry(import_existing=True)
    scope=_active_scope()
    entries=[record for record in (payload.get("items") or {}).values() if scope and str(record.get("blog_id") or "")==scope]
    drafts=sum(bool(set(record.get("sources") or []).intersection({"confirmed_naver_draft","blog_history_import","studio_db_import"})) for record in entries)
    published=sum(bool(set(record.get("sources") or []).intersection({"manual_existing_post","naver_rss_existing_post","title_file_existing_post"})) for record in entries)
    return {"products":len(entries),"drafts":drafts,"published":published,"blog_id":scope,
            "source_posts":len((payload.get("meta",{}).get("source_posts") or {}).get(scope,[])),
            "legacy_products":sum(not record.get("blog_id") for record in (payload.get("items") or {}).values()),"updated_at":payload.get("updated_at") or "",
            "path":str(REGISTRY_PATH)}


def registry_entries(include_legacy: bool = False) -> list[RegistryRecord]:
    """List evidence without assigning historical unknown accounts to the current blog."""
    payload=load_registry(import_existing=True);scope=_active_scope()
    return [record for record in (payload.get("items") or {}).values()
            if (scope and str(record.get("blog_id") or "")==scope) or (include_legacy and not record.get("blog_id"))]


def find_published_match(name: str,url: str = "",blog_id: str | None = None) -> RegistryRecord | None:
    """Find active-blog evidence for a save guard regardless of collection preferences."""
    scope=_active_scope(blog_id)
    if not scope:return None
    payload=load_registry();profile=product_profile(name,url)
    match=_find_match(payload,profile,scope) or _find_post_title_match(payload,profile,scope)
    return match[1] if match else None


def store_source_posts(posts: Sequence[SourcePost],blog_id: str) -> None:
    with _LOCK:
        payload=_read_payload()
        source_posts=payload.setdefault("meta",{}).setdefault("source_posts",{})
        merged={(post.get("title"),post.get("url")):post for post in source_posts.get(blog_id,[])}
        for post in posts:merged[(post.get("title"),post.get("url"))]=post
        source_posts[blog_id]=list(merged.values())
        _write_payload(payload)


def _find_post_title_match(payload,profile,scope: str) -> tuple[str,RegistryRecord,str,float] | None:
    from .already_posted_adapter import AUTO_SCORE,_match_title
    meta=payload.get("meta") or {}
    ignored=(meta.get("ignored_post_matches") or {}).get(scope,[])
    if any(_same_product_profiles(profile,previous)[0] for previous in ignored):return None
    for post in (meta.get("source_posts") or {}).get(scope,[]):
        score,reason=_match_title({"name":profile["name"],"source_url":""},post.get("title") or "")
        if score<AUTO_SCORE:continue
        key="post:"+hashlib.sha256((scope+"|"+str(post.get("title"))+"|"+str(post.get("url"))).encode("utf-8")).hexdigest()[:24]
        source="naver_rss_existing_post" if post.get("source")=="NAVER_RSS" else "title_file_existing_post"
        record: RegistryRecord={"key":key,"name":profile["name"],"blog_id":scope,"sources":[source],
                "last_saved_at":post.get("published_at") or "","matched_post_titles":[post.get("title") or ""],"matched_post_urls":[post.get("url") or ""]}
        return key,record,reason,float(score)
    return None
