# -*- coding: utf-8 -*-
"""Convert ItemScout/NAVER DataLab trend keywords into concrete Coupang products.

No external API key is required.  The collector opens Coupang search-result pages in
normal Chrome, evaluates a bounded set of visible product cards, and keeps one
popularity-weighted product per trend keyword.  The resulting physical products are
inserted into the existing ``products`` table so Stage ② (title/body/tags) can run
without a separate content pipeline.
"""
from pathlib import Path
from urllib.parse import urlparse
import csv, json, math, re, sqlite3, time
from .common import (ROOT, DB, settings, clean_listing_title_noise, identity_terms,
                     strict_product_match, critical_identity_tokens, log)
from . import chrome_collector, coupang_partners_api
from .published_product_registry import filter_published_candidates, product_profile
from . import trend_collection_adapter

SOURCE_ITEMSCOUT=trend_collection_adapter.SOURCE_ITEMSCOUT
SOURCE_DATALAB=trend_collection_adapter.SOURCE_DATALAB
PICK_SOURCE="쿠팡"

_KCOUNT_RE=re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(만|천)?\s*\+?")

def _norm_key(text):
    return re.sub(r"[^0-9A-Za-z가-힣]+","",str(text or "")).lower()

def _parse_count_token(text):
    s=str(text or "").replace(",","").strip()
    m=_KCOUNT_RE.search(s)
    if not m:return 0
    try:v=float(m.group(1))
    except Exception:return 0
    unit=m.group(2) or ""
    if unit=="만":v*=10000
    elif unit=="천":v*=1000
    return int(v)

def _metric_from_text(text):
    """Defensive parser for Coupang card text when the extension omitted metrics."""
    s=re.sub(r"\s+"," ",str(text or ""))
    reviews=[]
    for pat in [
        r"(?:리뷰|상품평)\s*[:：]?\s*[\(\[]?\s*([0-9][0-9,.]*(?:\s*(?:만|천))?\+?)",
        r"(?:후기)\s*[:：]?\s*[\(\[]?\s*([0-9][0-9,.]*(?:\s*(?:만|천))?\+?)",
        r"\(([0-9][0-9,]{1,8})\)"
    ]:
        for x in re.findall(pat,s,re.I):reviews.append(_parse_count_token(x))
    purchases=[]
    for x in re.findall(r"(?:최근\s*한\s*달\s*)?(?:구매|판매)\s*([0-9][0-9,.]*(?:\s*(?:만|천))?\+?)",s,re.I):
        purchases.append(_parse_count_token(x))
    ratings=[]
    # A bare 4.5/2.0 is rating-like only when it is not a capacity/weight/size
    # token. This prevents `4.5kg`, `2.0L`, `3.5mm` from becoming ratings.
    unit_tail=r"(?:ml|kg|mg|cm|mm|oz|m|l|g|개입|개|매|팩|세트|인치|롤|병|캔|포|봉|장|겹)\b"
    rating_hits=re.findall(rf"(?<![\dA-Za-z가-힣])([0-5]\.\d)(?!\d)(?!\s*{unit_tail})",s,re.I)
    rating_hits+=re.findall(r"(?<!\d)([0-5](?:\.\d)?)\s*(?:점|/\s*5)(?!\d)",s)
    for x in rating_hits:
        try:
            v=float(x)
            if 0<=v<=5:ratings.append(v)
        except Exception:pass
    return {
        "review_count":max(reviews or [0]),"purchase_count":max(purchases or [0]),
        "rating":max(ratings or [0.0]),"is_ad":bool(re.search(r"(^|\s)광고($|\s)",s)),
    }

def _relevance(keyword,name,text=""):
    q=[x.lower() for x in re.findall(r"[0-9A-Za-z가-힣]+",str(keyword or "")) if len(x)>=2]
    if not q:return 0.0
    low=(str(name or "")+" "+str(text or "")).lower()
    return sum(1 for x in q if x in low)/len(q)

def _card_popularity(card,keyword,index=0):
    pop=dict(card.get("popularity") or {}) if isinstance(card,dict) else {}
    fallback=_metric_from_text((card or {}).get("text") or "")
    review=int(pop.get("review_count") or fallback["review_count"] or 0)
    purchase=int(pop.get("purchase_count") or fallback["purchase_count"] or 0)
    try:rating=float(pop.get("rating") or fallback["rating"] or 0.0)
    except Exception:rating=0.0
    is_ad=bool(pop.get("is_ad",fallback["is_ad"]))
    rel=float(pop.get("relevance") or _relevance(keyword,(card or {}).get("name"),(card or {}).get("text")))
    pos=max(1,int(pop.get("search_position") or index+1))
    # Reviews and recent purchases are the strongest visible popularity signals.
    # Position/relevance are tie-breakers, not substitutes for popularity evidence.
    score=(math.log1p(review)*18.0)+(math.log1p(purchase)*22.0)+(rating*5.0)+(rel*38.0)+(18.0/math.sqrt(pos))
    if is_ad:score-=30.0
    if not (card or {}).get("url"):score-=25.0
    return {"review_count":review,"purchase_count":purchase,"rating":rating,"is_ad":is_ad,
            "relevance":round(rel,4),"search_position":pos,"score":round(score,4)}

def _is_coupang_product_url(url):
    try:
        u=urlparse(str(url or ""))
        return "coupang.com" in (u.hostname or "").lower() and bool(re.search(r"/vp/products/\d+",u.path or "",re.I))
    except Exception:return False

def _pick_best(cards,keyword):
    candidates=[]
    for i,c in enumerate(cards or []):
        if not isinstance(c,dict):continue
        name=clean_listing_title_noise(c.get("name") or "")
        if len(name)<3:continue
        rel=_relevance(keyword,name,c.get("text") or "")
        # Validate the returned product title itself. Never append the search
        # keyword to candidate text, because that would make an unrelated item
        # appear to contain every requested term.
        score,detail=strict_product_match(name,keyword)
        terms=identity_terms(keyword);low=name.lower()
        hits=[x for x in terms if x.lower() in low]
        required=1 if len(terms)<=1 else max(2,(len(terms)+1)//2)
        match_ok=(not detail.get("missing")) and len(hits)>=required and rel>=0.50
        if not match_ok:continue
        m=_card_popularity(c,keyword,i)
        c=dict(c);c["name"]=name;c["popularity"]=m
        c["product_match"]={"ok":True,"score":score,"relevance":rel,"identity_hits":hits,
                            "required_hits":required,"critical":critical_identity_tokens(keyword)}
        candidates.append(c)
    if not candidates:return None
    # Prefer non-ad results whenever at least one relevant non-ad product exists.
    non_ads=[x for x in candidates if not x["popularity"]["is_ad"]]
    pool=non_ads or candidates
    pool.sort(key=lambda x:(float(x["popularity"]["score"]),int(x["popularity"]["review_count"]),
                            int(x["popularity"]["purchase_count"]),-int(x["popularity"]["search_position"])),reverse=True)
    return pool[0]


def _canonical_api_product_url(row):
    """Return a stable Coupang product URL without opening Coupang web search."""
    url=str((row or {}).get("url") or "").strip()
    if _is_coupang_product_url(url):return url
    pid=re.sub(r"\D+","",str((row or {}).get("product_id") or ""))
    if pid:return f"https://www.coupang.com/vp/products/{pid}"
    return ""

def _api_card_popularity(row,keyword,index=0):
    """Score an official Partners API result without inventing web-only metrics.

    The Partners search response provides result order/rank but not live review or
    purchase counters.  We therefore use API search position + query relevance as
    the popularity evidence and keep unavailable review/purchase/rating fields at 0.
    """
    try:rank=max(1,int((row or {}).get("rank") or index+1))
    except Exception:rank=index+1
    name=str((row or {}).get("name") or "")
    rel=_relevance(keyword,name,name)
    score=(rel*70.0)+(42.0/math.sqrt(rank))
    if bool((row or {}).get("is_rocket")):score+=3.0
    if bool((row or {}).get("is_free_shipping")):score+=1.0
    return {"review_count":0,"purchase_count":0,"rating":0.0,"is_ad":False,
            "relevance":round(rel,4),"search_position":rank,"score":round(score,4),
            "metric_source":"coupang_partners_api_rank"}

def _cards_from_partners_api(keyword,limit=10):
    """Official, browser-free trend product lookup.

    This path deliberately never calls coupang.com/np/search.  It is the default
    for trend -> Coupang extraction because Coupang may reject automated web search
    even when the query was submitted from its homepage.
    """
    rows=coupang_partners_api.search(keyword,max(1,min(10,int(limit))))
    cards=[]
    for i,row in enumerate(rows or []):
        if not isinstance(row,dict):continue
        name=clean_listing_title_noise(row.get("name") or "")
        url=_canonical_api_product_url(row)
        if len(name)<3 or not url:continue
        pop=_api_card_popularity(row,keyword,i)
        cards.append({"name":name,"price":row.get("price"),"url":url,
                      "image_url":row.get("image_url") or "","text":name,
                      "popularity":pop,"api_product_id":row.get("product_id") or "",
                      "collector_source":"coupang_partners_api"})
    return cards

def _cards_from_local_coupang_snapshots(keyword,limit=30):
    """Offline fallback using already-collected Coupang rows only; no web request."""
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    try:
        rows=[dict(r) for r in con.execute("""SELECT name,price,url,image_url,rank_no,captured_at
            FROM candidates WHERE platform='쿠팡' AND COALESCE(name,'')<>''
            ORDER BY datetime(COALESCE(captured_at,'')) DESC, COALESCE(rank_no,9999) ASC LIMIT 1200""").fetchall()]
    except Exception:
        rows=[]
    finally:con.close()
    out=[];seen=set()
    for r in rows:
        name=clean_listing_title_noise(r.get("name") or "");url=str(r.get("url") or "")
        if not name or not _is_coupang_product_url(url):continue
        if _relevance(keyword,name,name)<0.50:continue
        key=(name.lower(),url)
        if key in seen:continue
        seen.add(key)
        try:pos=max(1,int(r.get("rank_no") or len(out)+1))
        except Exception:pos=len(out)+1
        rel=_relevance(keyword,name,name)
        out.append({"name":name,"price":r.get("price"),"url":url,"image_url":r.get("image_url") or "","text":name,
                    "popularity":{"review_count":0,"purchase_count":0,"rating":0.0,"is_ad":False,
                                  "relevance":round(rel,4),"search_position":pos,
                                  "score":round(rel*65.0+35.0/math.sqrt(pos),4),
                                  "metric_source":"local_coupang_snapshot_rank"},
                    "collector_source":"local_coupang_snapshot"})
        if len(out)>=max(1,int(limit)):break
    return out

def _age_bonus(age_group):
    return 8 if "/" in str(age_group or "") else 0

def build_keyword_plan(per_category=None):
    """Merge both trend sources and return at most N unique keywords/category."""
    cfg=settings();limit=max(1,min(100,int(per_category or cfg.get("trend_coupang_keywords_per_category",30) or 30)))
    cats=cfg.get("trend_categories") or trend_collection_adapter.DEFAULT_CATEGORIES
    groups={}
    for source in (SOURCE_ITEMSCOUT,SOURCE_DATALAB):
        for r in trend_collection_adapter.merged_rows(source):
            cat=str(r.get("category") or "");kw=str(r.get("keyword") or "").strip();key=(cat,_norm_key(kw))
            if cat not in cats or not key[1]:continue
            try:rank=max(1,int(r.get("rank_no") or 999))
            except Exception:rank=999
            g=groups.setdefault(key,{"category":cat,"keyword":kw,"sources":set(),"age_groups":set(),"source_ranks":{},"trend_score":0.0})
            g["sources"].add(source);g["age_groups"].update(x.strip() for x in str(r.get("age_group") or "").split("/") if x.strip())
            g["source_ranks"][source]=min(rank,int(g["source_ranks"].get(source,999)))
            g["trend_score"]+=max(0,31-rank)+_age_bonus(r.get("age_group"))
    bycat={c:[] for c in cats}
    for g in groups.values():
        if len(g["sources"])>1:g["trend_score"]+=20
        g["source_count"]=len(g["sources"]);g["best_rank"]=min(g["source_ranks"].values() or [999])
        g["sources"]=sorted(g["sources"]);g["age_groups"]=sorted(g["age_groups"])
        bycat.setdefault(g["category"],[]).append(g)
    out=[]
    for cat in cats:
        arr=bycat.get(cat,[])
        arr.sort(key=lambda g:(g["source_count"],g["trend_score"],-g["best_rank"]),reverse=True)
        out.extend(arr[:limit])
    for i,r in enumerate(out,1):r["plan_no"]=i
    return out

def _ensure_pick_table(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS trend_product_picks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      category TEXT, keyword TEXT, trend_sources TEXT, age_groups TEXT,
      trend_score REAL DEFAULT 0, coupang_name TEXT, coupang_url TEXT,
      coupang_price INTEGER, coupang_image_url TEXT, review_count INTEGER DEFAULT 0,
      purchase_count INTEGER DEFAULT 0, rating REAL DEFAULT 0, popularity_score REAL DEFAULT 0,
      search_position INTEGER DEFAULT 0, status TEXT, evidence_json TEXT,
      captured_at TEXT, product_id INTEGER
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_trend_product_pick_scope ON trend_product_picks(category,keyword);
    """)

def _candidate_identity(row):
    url=str(row.get("url") or "")
    m=re.search(r"/vp/products/(\d+)",url,re.I)
    if m:return "coupang:"+m.group(1)
    p=product_profile(row.get("name") or "",url)
    return "base:"+(p.get("base_canonical") or p.get("canonical") or _norm_key(row.get("name")))

def _write_exports(rows,plan):
    out=ROOT/"outputs";out.mkdir(parents=True,exist_ok=True)
    csv_path=out/"trend_to_coupang_popular_products.csv"
    with csv_path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["카테고리","트렌드키워드","트렌드출처","연령","트렌드점수","쿠팡선정상품","가격","리뷰","최근구매/판매","평점","인기점수","검색위치","URL","상태"])
        for r in rows:
            p=r.get("popularity") or {}
            w.writerow([r.get("category"),r.get("keyword")," / ".join(r.get("sources") or [])," / ".join(r.get("age_groups") or []),r.get("trend_score"),r.get("name"),r.get("price"),p.get("review_count"),p.get("purchase_count"),p.get("rating"),p.get("score"),p.get("search_position"),r.get("url"),r.get("status")])
    (out/"trend_to_coupang_popular_products.json").write_text(json.dumps({"plan":plan,"selected":rows},ensure_ascii=False,indent=2),encoding="utf-8")
    return str(csv_path)

def selected_rows():
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    try:
        _ensure_pick_table(con);con.commit()
        return [dict(r) for r in con.execute("SELECT * FROM trend_product_picks ORDER BY category,trend_score DESC,popularity_score DESC,id").fetchall()]
    finally:con.close()

def extract_popular_products(progress=None):
    cfg=settings();plan=build_keyword_plan()
    if not plan:
        return {"stage_ok":False,"message":"아이템스카우트/네이버 데이터랩 수집 결과가 없습니다. 두 트렌드 수집 버튼 중 하나 이상을 먼저 실행하세요.","selected":0}

    # v8.08.34: Coupang web search is intentionally NOT used here.  Even a search
    # submitted from Coupang's homepage ultimately lands on /np/search and can be
    # rejected by Coupang's access-control layer.  Use the official Partners API;
    # if unavailable, reuse only previously collected local Coupang snapshots.
    api_ready=bool(coupang_partners_api.ready())
    api_limit=max(3,min(10,int(cfg.get("trend_coupang_api_results_per_keyword",10) or 10)))
    snapshot_fallback=bool(cfg.get("trend_coupang_snapshot_fallback_enabled",True))
    browser_fallback=bool(cfg.get("trend_coupang_browser_fallback_enabled",False))
    # Default/release policy is false.  Retain the setting only for explicit
    # diagnostics; normal trend extraction never opens Coupang search pages.
    if browser_fallback:
        log("[TREND→COUPANG] browser fallback setting ignored by v8.08.34 safe mode")

    picked=[];failed=[]
    log(f"[TREND→COUPANG] v8.08.34 브라우저 검색 0회 시작: 키워드 {len(plan)}개 / Partners API={'READY' if api_ready else 'NOT READY'}")
    for i,tr in enumerate(plan,1):
        kw=tr["keyword"]
        if progress:
            try:progress(i-1,len(plan),f"쿠팡 인기상품(API) {i}/{len(plan)}: {kw[:30]}")
            except Exception:pass
        cards=[];source="";errors=[]
        if api_ready:
            try:
                cards=_cards_from_partners_api(kw,api_limit);source="coupang_partners_api"
            except Exception as e:
                errors.append("Partners API: "+str(e))
        if not cards and snapshot_fallback:
            try:
                cards=_cards_from_local_coupang_snapshots(kw,max(api_limit,24));source="local_coupang_snapshot" if cards else source
            except Exception as e:
                errors.append("local snapshot: "+str(e))
        selected=_pick_best(cards,kw) if cards else None
        if not selected:
            reason=" / ".join(errors[-3:]) or ("쿠팡 Partners API 키 미설정 및 로컬 쿠팡 스냅샷 후보 없음" if not api_ready else "공식 API/로컬 스냅샷에서 관련 상품 후보 없음")
            failed.append({**tr,"error":reason,"collector_mode":"API_FIRST_NO_WEB"})
            continue
        url=str(selected.get("url") or "")
        if not _is_coupang_product_url(url):
            failed.append({**tr,"error":"쿠팡 상품 상세 URL을 확정하지 못함","candidate":selected,"collector_mode":"API_FIRST_NO_WEB"});continue
        picked.append({**tr,"name":clean_listing_title_noise(selected.get("name") or ""),"price":selected.get("price"),"url":url,
                       "image_url":selected.get("image_url") or "","popularity":selected.get("popularity") or {},"status":"쿠팡인기상품선정",
                       "collector_status":"ok","collector_debug":{"mode":"API_FIRST_NO_WEB","source":source,"web_search_count":0,"errors":errors}})
        if progress:
            try:progress(i,len(plan),f"쿠팡 인기상품(API) {i}/{len(plan)} 완료")
            except Exception:pass

    # One physical Coupang product can win multiple trend keywords. Keep the strongest
    # row but preserve every contributing keyword in evidence.
    dedup={}
    for r in picked:
        k=_candidate_identity(r)
        old=dedup.get(k)
        if old is None:
            r["matched_keywords"]=[r["keyword"]];dedup[k]=r;continue
        old["matched_keywords"].append(r["keyword"])
        old_strength=(float(old.get("trend_score") or 0)+float((old.get("popularity") or {}).get("score") or 0))
        new_strength=(float(r.get("trend_score") or 0)+float((r.get("popularity") or {}).get("score") or 0))
        if new_strength>old_strength:
            r["matched_keywords"]=old["matched_keywords"];dedup[k]=r
    unique=list(dedup.values())
    # Reuse the durable already-drafted-product policy (spec/count/colour differences
    # are still the same product) before exposing rows to Stage ②.
    as_candidates=[{"platform":"쿠팡","category":r["category"],"name":r["name"],"url":r["url"],"price":r.get("price"),"_pick":r} for r in unique]
    fresh,excluded=filter_published_candidates(as_candidates)
    fresh_rows=[x["_pick"] for x in fresh]
    fresh_object_ids={id(x) for x in fresh_rows}
    now=time.strftime("%Y-%m-%d %H:%M:%S")
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    preserved_pick_count=0
    try:
        _ensure_pick_table(con)
        previous_pick_keys={(str(x["category"]),str(x["keyword"])) for x in con.execute("SELECT category,keyword FROM trend_product_picks").fetchall()}
        # Remove only unprocessed leftovers from an older trend extraction. Never
        # delete rows that already have generated content/images or a saved draft.
        con.execute("""DELETE FROM products WHERE source_platform=? AND COALESCE(status,'')='트렌드쿠팡선정' AND COALESCE(title,'')='' AND COALESCE(body,'')='' AND COALESCE(tags,'')=''
                       AND COALESCE(image1,'')='' AND COALESCE(image2,'')='' AND COALESCE(image3,'')=''""",(PICK_SOURCE,))
        max_no=int(con.execute("SELECT COALESCE(MAX(product_no),0) FROM products").fetchone()[0] or 0)
        existing_urls={str(r["source_url"] or ""):int(r["id"]) for r in con.execute("SELECT id,source_url FROM products WHERE COALESCE(source_url,'')<>''").fetchall()}
        product_ids={}
        for r in fresh_rows:
            pid=existing_urls.get(r["url"])
            if pid is None:
                max_no+=1
                cur=con.execute("""INSERT INTO products(product_no,name,category,product_identity,source_platform,source_url,score,status,updated_at)
                    VALUES(?,?,?,?,?,?,?,'트렌드쿠팡선정',datetime('now','localtime'))""",
                    (max_no,r["name"],r["category"],json.dumps(identity_terms(r["name"]),ensure_ascii=False),PICK_SOURCE,r["url"],float((r.get("popularity") or {}).get("score") or 0)+float(r.get("trend_score") or 0)))
                pid=int(cur.lastrowid);existing_urls[r["url"]]=pid
            product_ids[_candidate_identity(r)]=pid
        for r in unique:
            p=r.get("popularity") or {};pid=product_ids.get(_candidate_identity(r))
            status="상품목록연동완료" if pid else ("기존작성상품제외" if id(r) not in fresh_object_ids else "미연동")
            ev={"trend_sources":r.get("sources"),"source_ranks":r.get("source_ranks"),"age_groups":r.get("age_groups"),
                "matched_keywords":r.get("matched_keywords"),"collector_status":r.get("collector_status"),"collector_debug":r.get("collector_debug"),"popularity":p}
            con.execute("""INSERT OR REPLACE INTO trend_product_picks(category,keyword,trend_sources,age_groups,trend_score,coupang_name,coupang_url,coupang_price,coupang_image_url,
                         review_count,purchase_count,rating,popularity_score,search_position,status,evidence_json,captured_at,product_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["category"],r["keyword"]," / ".join(r.get("sources") or [])," / ".join(r.get("age_groups") or []),float(r.get("trend_score") or 0),r["name"],r["url"],r.get("price"),r.get("image_url"),
                 int(p.get("review_count") or 0),int(p.get("purchase_count") or 0),float(p.get("rating") or 0),float(p.get("score") or 0),int(p.get("search_position") or 0),status,json.dumps(ev,ensure_ascii=False),now,pid))
        current_pick_keys={(str(r.get("category") or ""),str(r.get("keyword") or "")) for r in unique}
        preserved_pick_count=len(previous_pick_keys-current_pick_keys)
        con.commit()
    finally:con.close()
    export=_write_exports(unique,plan)
    fail_path=ROOT/"outputs"/"trend_to_coupang_failures.json";fail_path.parent.mkdir(parents=True,exist_ok=True)
    fail_path.write_text(json.dumps(failed,ensure_ascii=False,indent=2),encoding="utf-8")
    log(f"[TREND→COUPANG] 완료: 검색 {len(plan)} / 쿠팡선정 {len(unique)} / 상품목록연동 {len(fresh_rows)} / 작성이력제외 {len(excluded)} / 실패 {len(failed)}")
    return {"stage_ok":bool(fresh_rows) or bool(preserved_pick_count),"soft_pending":bool(failed),"planned":len(plan),"selected":len(unique),"linked":len(fresh_rows),
            "preserved_previous_picks":preserved_pick_count,
            "published_excluded":len(excluded),"failed":len(failed),"csv":export,
            "message":f"트렌드 키워드 {len(plan)}개 → 쿠팡 인기상품 {len(unique)}개 선정 · 이전 정상선정 {preserved_pick_count}건 보존 · 기존 상품목록 {len(fresh_rows)}개 연동 · 작성이력 제외 {len(excluded)}개"}

def health():
    api=coupang_partners_api.health()
    return {"ready":True,"name":"트렌드→쿠팡 인기상품 추출",
            "message":"v8.08.34 안전모드: 쿠팡 웹 검색(/np/search)을 열지 않습니다. 공식 Coupang Partners API 검색순위로 인기 후보를 선택하고, API가 없거나 일시 실패하면 이미 수집된 로컬 쿠팡 스냅샷만 사용합니다. 웹 접근제한 화면을 유발하는 자동 검색 fallback은 기본적으로 비활성화되어 있습니다. "+str(api.get("message") or ""),
            "state":"PASS" if api.get("ready") else "PARTIAL"}
