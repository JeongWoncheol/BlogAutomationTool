# -*- coding: utf-8 -*-
"""Celebrity outfit trend discovery / verification / article drafting.

v8.08.44 design goals
--------------------
1) Fresh public evidence first (NAVER News/Blog Search API; Google browser fallback).
2) Never treat a visual guess as an exact brand/model identification.
3) Bind celebrity + event + publication date before merging evidence.
4) Exact outfit claims require explicit text evidence and independent corroboration.
5) Vision (Qwen3-VL) is advisory for garment type/color/silhouette/logo clues only.
6) Source photos are analysis evidence only and are never promoted to blog images.
7) A verified/clearly-labelled product can be promoted into the existing product pipeline.
"""
from pathlib import Path
import base64, csv, email.utils, hashlib, html, json, math, os, re, sqlite3, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from .common import ROOT, DATA, DB, OUTPUTS, EVIDENCE, settings, log, clean_listing_title_noise, marketplace_product_accept
from . import content_adapter, ollama_local, naver_shopping_api, coupang_partners_api, chrome_collector

CREDENTIALS=DATA/"naver_image_api_credentials.json"

EVENT_RULES=[
    ("공항패션", re.compile(r"공항\s*패션|공항룩|출국|입국|인천공항|김포공항",re.I)),
    ("브랜드행사", re.compile(r"브랜드\s*행사|팝업|포토월|스토어\s*오픈|플래그십|앰버서더",re.I)),
    ("시사회", re.compile(r"시사회|VIP\s*시사회|프리미어",re.I)),
    ("제작발표회", re.compile(r"제작\s*발표회|발표회|쇼케이스|간담회",re.I)),
    ("패션위크", re.compile(r"패션\s*위크|fashion\s*week|컬렉션|런웨이",re.I)),
    ("출근길", re.compile(r"출근길|퇴근길|뮤직뱅크|음악중심|인기가요",re.I)),
    ("사복", re.compile(r"사복|데일리룩|일상룩|인스타(?:그램)?\s*패션|SNS\s*패션",re.I)),
    ("공식석상", re.compile(r"레드카펫|포토콜|공식\s*석상|기자간담회|어워즈|시상식",re.I)),
]

OUTFIT_TERMS=re.compile(r"착장|패션|룩|코디|재킷|자켓|코트|가디건|니트|셔츠|블라우스|티셔츠|원피스|드레스|스커트|팬츠|데님|청바지|가방|백|숄더백|토트백|크로스백|신발|슈즈|운동화|스니커즈|로퍼|부츠|모자|선글라스|목걸이|귀걸이|주얼리|액세서리",re.I)
NEGATIVE_DISCOVERY=re.compile(r"닮은꼴|과거\s*사진|어린시절|AI\s*(?:사진|이미지)|합성|논란|다이어트|메이크업만|헤어만|이상형|열애|결혼|집|부동산",re.I)
ROLE_WORDS={"배우","가수","아이돌","모델","방송인","아나운서","개그맨","개그우먼","셀럽","스타","연예인","멤버","그룹","기자","사진","뉴스","패션","공항","출국","입국","브랜드","행사","시사회","공식","착장","코디","룩"}
ITEM_CATEGORIES=["아우터","상의","하의","원피스/드레스","가방","신발","모자","주얼리/액세서리","기타"]
OUTFIT_EVENT_QUERY_HINTS={
    "공항패션":["공항패션","공항룩","출국","입국"],"브랜드행사":["브랜드 행사","포토월","팝업","행사"],
    "시사회":["시사회","VIP 시사회","프리미어"],"제작발표회":["제작발표회","쇼케이스","간담회"],
    "패션위크":["패션위크","컬렉션","런웨이"],"출근길":["출근길","뮤직뱅크","음악중심","인기가요"],
    "사복":["사복","데일리룩","일상룩","인스타 패션"],"공식석상":["레드카펫","포토콜","시상식","공식석상"],
    "패션화제":["착장","패션","룩","코디"],
}
OUTFIT_IMAGE_BAD_HOSTS=("coupang.com","shopping.naver.com","smartstore.naver.com","brand.naver.com","toss.shopping","pinterest.","instagram.com","youtube.com","youtu.be","x.com","twitter.com","facebook.com","tiktok.com")

KST=timezone(timedelta(hours=9))

def _today_kst():
    return datetime.now(KST).date()

def _now():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

def _clean(s):
    s=html.unescape(re.sub(r"<[^>]+>"," ",str(s or "")))
    return re.sub(r"\s+"," ",s).strip()

def _safe_json(v,default):
    try:
        o=json.loads(v or "")
        return o if isinstance(o,type(default)) else default
    except Exception:return default

def _date_from_pub(v):
    if not v:return None
    raw=str(v).strip()
    if re.fullmatch(r"\d{8}",raw):
        try:return datetime.strptime(raw,"%Y%m%d").date()
        except Exception:pass
    try:
        d=email.utils.parsedate_to_datetime(raw)
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(KST).date()
    except Exception:
        try:return datetime.fromisoformat(str(v)[:19]).date()
        except Exception:return None

def _event_type(text):
    for label,rx in EVENT_RULES:
        if rx.search(text or ""):return label
    return "패션화제"

def _source_weight(url,source_type=""):
    host=""
    try:host=urllib.parse.urlparse(url or "").hostname or ""
    except Exception:pass
    h=host.lower()
    # A single source may authorize an exact-claim only when it is a known
    # high-authority entertainment/newsroom or a clearly official brand/company
    # domain.  A generic news result is useful evidence, but not enough by itself.
    if any(x in h for x in ("dispatch.co.kr","osen.co.kr","newsen.com","starnews.co.kr","sportschosun.com","mk.co.kr","yna.co.kr","news1.kr","edaily.co.kr","xportsnews.com","tenasia.com","isplus.com")):return 1.0
    if any(x in h for x in ("official","brand","company")):return .96
    if source_type=="news":return .82
    if source_type=="blog":return .58
    if source_type=="google":return .62
    return .65

def _independent_host(url):
    try:
        h=(urllib.parse.urlparse(url or "").hostname or "").lower()
        return re.sub(r"^www\.","",h)
    except Exception:return ""


def _naver_creds():
    cfg=settings();obj={}
    try:obj=json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except Exception:pass
    return (str(cfg.get("naver_api_hub_client_id") or cfg.get("naver_search_client_id") or cfg.get("naver_image_client_id") or obj.get("client_id") or "").strip(),
            str(cfg.get("naver_api_hub_client_secret") or cfg.get("naver_search_client_secret") or cfg.get("naver_image_client_secret") or obj.get("client_secret") or "").strip())

def _naver_search(kind,query,display=50,sort="date"):
    cid,sec=_naver_creds()
    if not cid or not sec:raise RuntimeError("NAVER API HUB 키가 없습니다. 92_NAVER_IMAGE_API_SETUP.cmd에서 Client ID/Secret을 설정하세요.")
    if kind not in {"news","blog","image"}:raise ValueError(kind)
    endpoint=f"https://naverapihub.apigw.ntruss.com/search/v1/{kind}"
    params={"query":query,"display":max(1,min(100,int(display))),"start":1,"sort":sort,"format":"json"}
    if kind=="image":params["filter"]="large"
    req=urllib.request.Request(endpoint+"?"+urllib.parse.urlencode(params),headers={
        "X-NCP-APIGW-API-KEY-ID":cid,"X-NCP-APIGW-API-KEY":sec,
        "User-Agent":"NBlogStudio/8.08.46 CelebrityStyle","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=float(settings().get("celebrity_style_api_timeout_sec",15))) as r:
        obj=json.loads(r.read(4*1024*1024).decode("utf-8","replace"))
    rows=[]
    for item in obj.get("items") or []:
        if kind=="image":
            try:w=int(item.get("sizewidth") or 0);h=int(item.get("sizeheight") or 0)
            except Exception:w=h=0
            rows.append({"title":_clean(item.get("title")),"image_url":str(item.get("link") or ""),"thumbnail":str(item.get("thumbnail") or ""),
                         "width":w,"height":h,"source_page":"","source_type":"image","pub_date":""})
        else:
            link=str(item.get("originallink") or item.get("link") or "")
            rows.append({"title":_clean(item.get("title")),"description":_clean(item.get("description")),"url":link,
                         "naver_url":str(item.get("link") or ""),"source_type":kind,
                         "pub_date":str(item.get("pubDate") or item.get("postdate") or "")})
    return rows


def _google_sources(query,limit=12):
    tasks=[]
    for surface in ("web","images"):
        tasks.append({"id":"celeb-google-"+hashlib.sha1((surface+query).encode("utf-8")).hexdigest()[:12],"site":"Google",
                      "mode":"google_product_source_search","search_surface":surface,"query":query,"target_name":query,
                      "limit":int(limit),"render_wait_ms":1800 if surface=="web" else 2200,"delay_ms":700,"task_timeout_sec":50})
    try:results=chrome_collector.collect(tasks,timeout_sec=max(100,60*len(tasks)))
    except Exception as exc:return [],[str(exc)]
    rows=[];seen=set();errors=[]
    for res in results or []:
        if res.get("status")!="ok":errors.append(str(res.get("error") or "Google search failed"));continue
        for x in res.get("sources") or []:
            u=str(x.get("url") or "").strip()
            if not u or u in seen:continue
            seen.add(u)
            rows.append({"title":_clean(x.get("title")),"description":_clean(x.get("context")),"url":u,"naver_url":"",
                         "source_type":"google","pub_date":"","image_url":str(x.get("image_url") or ""),"search_surface":x.get("search_surface") or res.get("surface")})
    return rows,errors


def init_schema():
    con=sqlite3.connect(DB);c=con.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS celebrity_style_candidates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      fingerprint TEXT UNIQUE,
      celebrity_name TEXT, event_name TEXT, event_date TEXT, look_type TEXT,
      query_text TEXT, discovered_at TEXT, updated_at TEXT,
      source_count INTEGER DEFAULT 0, independent_source_count INTEGER DEFAULT 0,
      freshness_score REAL DEFAULT 0, evidence_score REAL DEFAULT 0, confidence_score REAL DEFAULT 0,
      confidence_label TEXT DEFAULT '후보', status TEXT DEFAULT '수집완료',
      summary TEXT, source_json TEXT, vision_json TEXT,
      draft_title TEXT, draft_body TEXT, draft_tags TEXT,
      promoted_product_id INTEGER DEFAULT 0, last_error TEXT
    );
    CREATE TABLE IF NOT EXISTS celebrity_style_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      candidate_id INTEGER NOT NULL,
      item_category TEXT, item_description TEXT, brand TEXT, model_name TEXT, color TEXT,
      evidence_level TEXT DEFAULT '추정', confidence_score REAL DEFAULT 0,
      exact_claim_allowed INTEGER DEFAULT 0,
      evidence_json TEXT, naver_product_json TEXT, coupang_product_json TEXT,
      matched_name TEXT, matched_url TEXT, matched_price INTEGER DEFAULT 0, matched_image_url TEXT,
      match_type TEXT DEFAULT '미확인', matched_product_id INTEGER DEFAULT 0, updated_at TEXT,
      UNIQUE(candidate_id,item_category,item_description,brand,model_name)
    );
    CREATE INDEX IF NOT EXISTS ix_celeb_style_date ON celebrity_style_candidates(event_date,confidence_score);
    CREATE INDEX IF NOT EXISTS ix_celeb_item_candidate ON celebrity_style_items(candidate_id,confidence_score);
    """)
    con.commit();con.close()


def health():
    init_schema();cid,sec=_naver_creds();cfg=settings()
    text=ollama_local.status(cfg)
    return {"ready":bool(cid and sec) or bool(cfg.get("celebrity_style_google_fallback",True)),
            "name":"연예인 착장 트렌드",
            "message":("NAVER API HUB 뉴스/블로그/이미지 READY" if cid and sec else "NAVER API 미설정 · Google 일반 Chrome fallback 사용")+
                      (" · Ollama READY" if text.get("ready") else " · Ollama 미준비(휴리스틱 fallback)")}


def _freshness_score(pub_dates,days):
    ds=[_date_from_pub(x) for x in pub_dates if x]
    ds=[x for x in ds if x]
    if not ds:return 4.0
    age=max(0,(_today_kst()-max(ds)).days)
    return max(0,10*(1-age/max(1,days+1)))


def _heuristic_celeb_name(title,description=""):
    t=_clean(title)
    patterns=[
        r"^([가-힣]{2,4})(?=,|\s|\(|\[)",
        r"([가-힣]{2,4})\s*(?=공항\s*패션|공항룩|출국|입국|시사회|제작발표회|브랜드\s*행사|포토월|패션위크|사복|착장|드레스|가방)",
        r"(?:배우|가수|모델|방송인|아이돌)\s*([가-힣]{2,4})",
    ]
    for p in patterns:
        m=re.search(p,t)
        if m:
            name=m.group(1).strip()
            if name not in ROLE_WORDS and len(name)>=2:return name
    # do not aggressively guess from description; false celebrity identities are worse than missing candidates.
    return ""


def _ai_extract_candidates(rows,manual_name=""):
    cfg=settings();compact=[]
    for i,r in enumerate(rows[:120]):
        compact.append({"i":i,"title":r.get("title") or "","description":(r.get("description") or "")[:260],"date":r.get("pub_date") or "","type":r.get("source_type")})
    prompt="""너는 한국 연예매체/패션 데이터 검증 담당자다. 아래 검색 결과에서 실제 '연예인 본인의 최근 착장/공항패션/행사패션/사복'에 해당하는 항목만 추출한다.
엄격 규칙:
- 검색결과에 명시되지 않은 연예인 이름, 브랜드, 행사, 날짜를 추측하지 않는다.
- 작품 속 캐릭터 의상, 과거 회상 기사, 닮은꼴, AI 합성, 단순 광고모델 뉴스는 제외한다.
- 같은 인물+같은 행사/날짜로 보이는 결과는 source_indices로 묶는다.
- event_type은 공항패션/브랜드행사/시사회/제작발표회/패션위크/출근길/사복/공식석상/패션화제 중 하나.
- celebrity는 본문에 분명히 나타난 이름만 쓴다.
- manual_celebrity가 있으면 그 사람만 반환한다.
JSON 객체만 반환: {"candidates":[{"celebrity":"","event_type":"","event_name":"","source_indices":[0],"reason":""}]}
manual_celebrity="""+json.dumps(manual_name,ensure_ascii=False)+"\n검색결과="+json.dumps(compact,ensure_ascii=False)
    try:
        model=ollama_local.resolve_model(cfg)
        obj=content_adapter.call_ollama(prompt,model,cfg)
        out=obj.get("candidates") if isinstance(obj,dict) else None
        return [x for x in (out or []) if isinstance(x,dict)]
    except Exception as exc:
        log("연예인 착장 후보 AI 추출 fallback: "+str(exc));return []


def _group_candidates(rows,manual_name=""):
    ai=_ai_extract_candidates(rows,manual_name) if bool(settings().get("celebrity_style_ai_extract",True)) else []
    groups=[];used=set()
    for cand in ai:
        name=_clean(cand.get("celebrity"));idxs=[]
        for x in cand.get("source_indices") or []:
            try:i=int(x)
            except Exception:continue
            if 0<=i<len(rows):idxs.append(i);used.add(i)
        if manual_name and manual_name.casefold() not in name.casefold():continue
        if not name or not idxs:continue
        sources=[rows[i] for i in idxs]
        text=" ".join((s.get("title") or "")+" "+(s.get("description") or "") for s in sources)
        if not OUTFIT_TERMS.search(text) or NEGATIVE_DISCOVERY.search(text):continue
        ev=_clean(cand.get("event_type")) or _event_type(text)
        groups.append({"celebrity":name,"event_type":ev,"event_name":_clean(cand.get("event_name")) or ev,"sources":sources})
    # Conservative heuristic fallback for search results AI did not claim.
    for i,r in enumerate(rows):
        if i in used:continue
        text=(r.get("title") or "")+" "+(r.get("description") or "")
        if not OUTFIT_TERMS.search(text) or NEGATIVE_DISCOVERY.search(text):continue
        name=manual_name.strip() if manual_name.strip() and manual_name.strip() in text else _heuristic_celeb_name(r.get("title"),r.get("description"))
        if not name:continue
        ev=_event_type(text)
        # merge only same person + same event type + same publication day. Avoid mixing multiple airport/brand events.
        d=_date_from_pub(r.get("pub_date"));dstr=str(d or "")
        hit=None
        for g in groups:
            gd=_date_from_pub((g.get("sources") or [{}])[0].get("pub_date"))
            if g["celebrity"]==name and g["event_type"]==ev and str(gd or "")==dstr:hit=g;break
        if hit:hit["sources"].append(r)
        else:groups.append({"celebrity":name,"event_type":ev,"event_name":ev,"sources":[r]})
    return groups


def _candidate_score(name,event,sources,days):
    hosts={_independent_host(s.get("url")) for s in sources if _independent_host(s.get("url"))}
    explicit=sum(1 for s in sources if name and name in ((s.get("title") or "")+" "+(s.get("description") or "")))
    event_hits=sum(1 for s in sources if _event_type((s.get("title") or "")+" "+(s.get("description") or ""))==event)
    source_component=min(25.0,8+6*len(hosts)) if hosts else min(18.0,6*len(sources))
    celeb_component=min(20.0,8+5*explicit)
    event_component=min(15.0,5+4*event_hits)
    freshness=_freshness_score([s.get("pub_date") for s in sources],days)
    quality=min(20.0,sum(_source_weight(s.get("url"),s.get("source_type"))*6 for s in sources))
    score=min(90.0,source_component+celeb_component+event_component+freshness+quality)
    return round(score,1),len(hosts),round(freshness,1)


def collect_latest(days=None,celebrity="",progress=None):
    init_schema();cfg=settings();days=max(1,min(30,int(days or cfg.get("celebrity_style_period_days",3))))
    manual=_clean(celebrity);queries=[]
    if manual:
        suffixes=cfg.get("celebrity_style_manual_query_suffixes") or ["공항패션","착장 패션","브랜드 행사 패션","시사회 패션","사복 데일리룩"]
        queries=[f'"{manual}" {x}' for x in suffixes]
    else:
        queries=list(cfg.get("celebrity_style_queries") or ["연예인 공항패션","아이돌 공항패션","연예인 브랜드 행사 패션","연예인 시사회 패션","연예인 제작발표회 패션","연예인 사복 데일리룩","연예인 출근길 패션"])
    maxq=max(1,int(cfg.get("celebrity_style_query_count",8)));queries=queries[:maxq]
    rows=[];seen=set();errors=[];total=max(1,len(queries)*2);done=0
    cutoff=_today_kst()-timedelta(days=days)
    for q in queries:
        for kind in ("news","blog"):
            done+=1
            if progress:progress(done,total,f"착장 검색 · {kind} · {q}")
            if not bool(cfg.get("celebrity_style_use_naver_"+kind,True)):continue
            try:found=_naver_search(kind,q,int(cfg.get("celebrity_style_results_per_query",35)),"date")
            except Exception as exc:errors.append(f"NAVER {kind} {q}: {exc}");continue
            for r in found:
                d=_date_from_pub(r.get("pub_date"))
                if d and d<cutoff:continue
                key=(r.get("url") or r.get("naver_url") or "")+"|"+(r.get("title") or "")
                if key in seen:continue
                seen.add(key);r["query_used"]=q;rows.append(r)
    # If NAVER is unavailable/too sparse, use existing logged-in normal Chrome Google resolver.
    min_rows=int(cfg.get("celebrity_style_google_fallback_min_rows",12))
    if bool(cfg.get("celebrity_style_google_fallback",True)) and len(rows)<min_rows:
        fallback_queries=queries[:max(1,int(cfg.get("celebrity_style_google_query_count",2)))]
        for q in fallback_queries:
            if progress:progress(done,total,f"Google 보강 · {q}")
            gres,gerr=_google_sources(q,int(cfg.get("celebrity_style_google_result_limit",12)));errors.extend(gerr)
            for r in gres:
                key=(r.get("url") or "")+"|"+(r.get("title") or "")
                if key in seen:continue
                seen.add(key);r["query_used"]=q;rows.append(r)
    groups=_group_candidates(rows,manual)
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;now=_now();saved=0;saved_ids=[]
    for g in groups:
        sources=[];source_seen=set()
        for s in g["sources"]:
            k=s.get("url") or s.get("naver_url") or s.get("title")
            if k in source_seen:continue
            source_seen.add(k);sources.append(s)
        dates=[_date_from_pub(s.get("pub_date")) for s in sources];dates=[d for d in dates if d]
        # Do not turn an undated Google result into "today's outfit".  Unknown
        # publication/event dates remain unknown and receive the low undated
        # freshness score.  A stable source hash prevents unrelated undated
        # events from the same celebrity/type being merged forever.
        event_date=str(max(dates)) if dates else ""
        score,indep,fresh=_candidate_score(g["celebrity"],g["event_type"],sources,days)
        undated_key=hashlib.sha1("|".join(str(s.get("url") or s.get("title") or "") for s in sources[:3]).encode("utf-8")).hexdigest()[:12]
        fp_date=event_date or ("undated-"+undated_key)
        fp=hashlib.sha1((g["celebrity"]+"|"+g["event_type"]+"|"+fp_date).encode("utf-8")).hexdigest()
        summary=" / ".join(_clean(s.get("title")) for s in sources[:3])[:1200]
        con.execute("""INSERT INTO celebrity_style_candidates
          (fingerprint,celebrity_name,event_name,event_date,look_type,query_text,discovered_at,updated_at,source_count,independent_source_count,freshness_score,evidence_score,confidence_score,confidence_label,status,summary,source_json,last_error)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
          ON CONFLICT(fingerprint) DO UPDATE SET
           event_name=excluded.event_name,updated_at=excluded.updated_at,source_count=excluded.source_count,independent_source_count=excluded.independent_source_count,
           freshness_score=excluded.freshness_score,evidence_score=excluded.evidence_score,confidence_score=MAX(celebrity_style_candidates.confidence_score,excluded.confidence_score),
           summary=excluded.summary,source_json=excluded.source_json,status=CASE WHEN celebrity_style_candidates.status IN ('원고완료','작성물연동') THEN celebrity_style_candidates.status ELSE '수집완료' END,last_error=NULL""",
          (fp,g["celebrity"],g.get("event_name") or g["event_type"],event_date,g["event_type"],manual or "자동 최신검색",now,now,len(sources),indep,fresh,score,score,
           "다중근거" if indep>=2 else "단일근거","수집완료",summary,json.dumps(sources,ensure_ascii=False)))
        rid=con.execute("SELECT id FROM celebrity_style_candidates WHERE fingerprint=?",(fp,)).fetchone()
        if rid:saved_ids.append(int(rid[0]))
        saved+=1
    con.commit();con.close();_write_candidates_csv()
    return {"count":saved,"candidate_ids":list(dict.fromkeys(saved_ids)),"raw_sources":len(rows),"errors":errors,"message":f"최근 {days}일 착장 후보 {saved}건 · 원천 {len(rows)}건 수집"}


def _candidate_sources(row):return _safe_json(row["source_json"] if isinstance(row,sqlite3.Row) else row.get("source_json"),[])


def _fetch_source_page_text(url,target_name=""):
    if not url:return ""
    task={"id":"celeb-page-"+hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],"site":"외부원문","mode":"external_detail","url":url,
          "target_name":target_name or "fashion","limit":12,"detail_scroll_rounds":1,"detail_scroll_wait_ms":250,"capture_rendered_crops":False,"task_timeout_sec":45}
    try:
        results=chrome_collector.collect([task],timeout_sec=60)
        if results:return _clean((results[0] or {}).get("page_text") or "")[:18000]
    except Exception as exc:log("착장 원문 텍스트 보강 실패: "+str(exc))
    return ""


def _vision_model(cfg=None):
    cfg=cfg or settings();preferred=str(cfg.get("celebrity_style_vision_model") or "qwen3-vl:4b").strip()
    try:
        names=ollama_local.server_models(timeout=2.5)
        if any(ollama_local._same_model(preferred,x) for x in names):return preferred
        for m in ("qwen3-vl:8b","qwen3-vl:4b","qwen3-vl:2b"):
            if any(ollama_local._same_model(m,x) for x in names):return m
    except Exception:pass
    return ""


def vision_status():
    model=_vision_model(settings())
    return {"ready":bool(model),"model":model,"message":("Vision READY · "+model) if model else "Qwen3-VL 미설치 · 94_OLLAMA_VISION_AUTO_SETUP.cmd 실행"}


def _download_temp_image(url,out,referer="",min_dim=300,max_bytes=8*1024*1024,max_ratio=2.8):
    try:
        from PIL import Image,ImageOps
        import io
        headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
                 "Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8","Accept-Language":"ko-KR,ko;q=0.9,en;q=0.7"}
        if referer:headers["Referer"]=str(referer)
        req=urllib.request.Request(url,headers=headers)
        with urllib.request.urlopen(req,timeout=18) as r:data=r.read(max_bytes)
        if len(data)<8000:return False
        im=Image.open(io.BytesIO(data));im.load();im=ImageOps.exif_transpose(im).convert("RGB")
        if min(im.width,im.height)<int(min_dim):return False
        ratio=max(im.width,im.height)/max(1,min(im.width,im.height))
        if ratio>float(max_ratio):return False
        out.parent.mkdir(parents=True,exist_ok=True);im.save(out,"JPEG",quality=93);return True
    except Exception:return False


def _outfit_reference_score(title,desc,row,source_host="",evidence_hosts=None):
    text=((title or "")+" "+(desc or "")).strip();low=text.lower();score=0
    celeb=str(row.get("celebrity_name") or "")
    if celeb and celeb in text:score+=7
    hints=OUTFIT_EVENT_QUERY_HINTS.get(str(row.get("look_type") or "패션화제"),[str(row.get("look_type") or "")])
    if any(q and q.lower() in low for q in hints):score+=4
    ed=str(row.get("event_date") or "")
    if ed and (ed in text or ed.replace("-","") in low or ed[:7] in text):score+=2
    if source_host and evidence_hosts and source_host in evidence_hosts:score+=3
    if any(bad in low for bad in ("쇼핑","구매","판매","최저가","가격비교","협찬상품","광고상품")):score-=5
    return score


def _google_image_sources(query,limit=12):
    task={"id":"celeb-google-image-"+hashlib.sha1(query.encode("utf-8")).hexdigest()[:12],"site":"Google","mode":"google_product_source_search",
          "search_surface":"images","query":query,"target_name":query,"limit":int(limit),"render_wait_ms":2200,"delay_ms":700,"task_timeout_sec":50}
    try:results=chrome_collector.collect([task],timeout_sec=70)
    except Exception as exc:return [],[str(exc)]
    rows=[];seen=set();errors=[]
    for res in results or []:
        if res.get("status")!="ok":errors.append(str(res.get("error") or "Google image search failed"));continue
        for x in res.get("sources") or []:
            iu=str(x.get("image_url") or "").strip();page=str(x.get("url") or "").strip()
            if not iu or iu in seen:continue
            seen.add(iu)
            rows.append({"title":_clean(x.get("title")),"description":_clean(x.get("context") or x.get("image_alt")),"image_url":iu,
                         "page_url":page,"host":str(x.get("host") or _independent_host(page)),"source_type":"google_image"})
    return rows,errors


def _collect_outfit_reference_images(row,sources):
    cfg=settings();state={"queries":[],"candidates":[],"downloaded":[],"errors":[]}
    celeb=str(row.get("celebrity_name") or "").strip();look=str(row.get("look_type") or "패션화제").strip();eday=str(row.get("event_date") or "").strip()
    if not celeb:return state
    hints=OUTFIT_EVENT_QUERY_HINTS.get(look,[look or "착장"])
    queries=[]
    if eday:queries.append(f'"{celeb}" {look} {eday}')
    for h in hints[:3]:queries.append(f'"{celeb}" {h}')
    queries.append(f'"{celeb}" 착장')
    queries=list(dict.fromkeys(q for q in queries if q.strip()))[:max(1,int(cfg.get("celebrity_style_reference_query_count",4)))]
    state["queries"]=queries
    evidence_hosts={_independent_host(s.get("url")) for s in sources if _independent_host(s.get("url"))}
    candidates=[];seen=set()
    for q in queries:
        try:nrows=_naver_search("image",q,int(cfg.get("celebrity_style_reference_search_images",18)),"sim")
        except Exception as exc:state["errors"].append(f"NAVER image {q}: {exc}");nrows=[]
        for r in nrows:
            title=_clean(r.get("title"));score=_outfit_reference_score(title,"",row,"",evidence_hosts)
            if score<int(cfg.get("celebrity_style_reference_min_text_score",7)):continue
            iu=str(r.get("image_url") or "").strip()
            if not iu or iu in seen:continue
            seen.add(iu);candidates.append({"title":title,"description":"","image_url":iu,"page_url":"","host":"","source_type":"naver_image","score":score})
        if bool(cfg.get("celebrity_style_google_fallback",True)) and len(candidates)<int(cfg.get("celebrity_style_reference_min_candidates",6)):
            grows,gerrs=_google_image_sources(q,int(cfg.get("celebrity_style_google_image_result_limit",12)));state["errors"].extend(gerrs)
            for r in grows:
                host=str(r.get("host") or "").lower()
                if any(bad in host for bad in OUTFIT_IMAGE_BAD_HOSTS):continue
                title=_clean(r.get("title"));desc=_clean(r.get("description"));score=_outfit_reference_score(title,desc,row,host,evidence_hosts)
                if score<int(cfg.get("celebrity_style_reference_min_text_score",7)):continue
                iu=str(r.get("image_url") or "").strip()
                if not iu or iu in seen:continue
                seen.add(iu);candidates.append({**r,"score":score})
    candidates.sort(key=lambda x:(-float(x.get("score") or 0),x.get("source_type")!="naver_image"));state["candidates"]=candidates[:24]
    work=EVIDENCE/"celebrity_style"/str(row["id"])/"references";hashes=set();max_img=max(2,int(cfg.get("celebrity_style_reference_max_images",5)))
    min_dim=max(240,int(cfg.get("celebrity_style_reference_image_min_dimension",300)))
    for idx,c in enumerate(candidates[:24],1):
        p=work/f"ref_{idx}.jpg"
        if not _download_temp_image(c.get("image_url") or "",p,referer=c.get("page_url") or "",min_dim=min_dim,
                                    max_ratio=float(cfg.get("celebrity_style_reference_max_aspect_ratio",2.8))):continue
        try:digest=hashlib.sha1(p.read_bytes()).hexdigest()
        except Exception:digest=""
        if digest and digest in hashes:p.unlink(missing_ok=True);continue
        if digest:hashes.add(digest)
        state["downloaded"].append({**c,"file":str(p)})
        if len(state["downloaded"])>=max_img:break
    return state


def _ollama_vision_json(image_paths,prompt,model):
    images=[]
    for p in image_paths:
        try:images.append(base64.b64encode(Path(p).read_bytes()).decode("ascii"))
        except Exception:pass
    if not images:raise RuntimeError("Vision 분석 이미지 없음")
    cfg=settings();payload={"model":model,"messages":[{"role":"user","content":prompt,"images":images}],"stream":False,"format":"json","think":False,
                            "keep_alive":str(cfg.get("ollama_keep_alive","30m")),"options":{"temperature":0.1,"top_p":0.7,"num_ctx":8192,"num_predict":1000}}
    req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=int(cfg.get("celebrity_style_vision_timeout_sec",180))) as r:obj=json.loads(r.read().decode("utf-8","replace"))
    return content_adapter._extract_json_response((obj.get("message") or {}).get("content") or "")


def _vision_analyze(row,sources):
    cfg=settings();state={"attempted":False,"model":"","images":[],"result":{},"errors":[],"reference_search":{},"cluster_result":{}}
    if not bool(cfg.get("celebrity_style_vision_enabled",True)):return state
    model=_vision_model(cfg)
    if not model:return state
    state["attempted"]=True;state["model"]=model
    ref=_collect_outfit_reference_images(row,sources);state["reference_search"]=ref
    downloaded=list(ref.get("downloaded") or []);paths=[Path(x["file"]) for x in downloaded if x.get("file")]
    if not paths:state["errors"].append("착장 전용 참고 이미지를 확보하지 못했습니다.");return state

    # Expert gate: compare the candidate pictures to each other first.  Search
    # relevance alone is not enough; keep the largest visually consistent outfit
    # cluster before extracting garment attributes.
    selected_idx=list(range(len(paths)))
    if len(paths)>=2:
        cluster_prompt=f"""아래 {len(paths)}장의 사진은 {row['celebrity_name']}의 {row['look_type']} 착장 검색 후보이다.
인물 신원을 새로 추정하지 말고 옷의 색, 실루엣, 아우터/상의/하의, 가방, 신발 조합만 비교한다.
서로 같은 날/같은 착장으로 보이는 가장 큰 그룹의 0부터 시작하는 이미지 번호를 same_outfit_indices에 반환한다.
확신이 없으면 억지로 묶지 않는다. JSON: {{"same_outfit_indices":[0,1],"confidence":0,"reason":""}}"""
        try:
            cl=_ollama_vision_json(paths,cluster_prompt,model);state["cluster_result"]=cl if isinstance(cl,dict) else {}
            raw=(cl or {}).get("same_outfit_indices") or []
            idx=[]
            for x in raw:
                try:i=int(x)
                except Exception:continue
                if 0<=i<len(paths) and i not in idx:idx.append(i)
            if len(idx)>=2:selected_idx=idx
            elif len(paths)>2:selected_idx=[0]  # safest high-text-score candidate only
        except Exception as exc:state["errors"].append("착장 이미지 클러스터링 실패: "+str(exc))
    sel_paths=[paths[i] for i in selected_idx]
    sel_meta=[downloaded[i] for i in selected_idx]
    state["images"]=[{"file":x.get("file"),"source_url":x.get("image_url"),"title":x.get("title"),"source_type":x.get("source_type"),"score":x.get("score")} for x in sel_meta]
    prompt=f"""선별된 사진들은 {row['celebrity_name']}의 {row['look_type']} 착장 참고 컷이다.
사진만으로 브랜드/정확 모델명을 확정하지 마라. 로고/문자가 명확히 읽히면 logo_clue에 보이는 문자열만 기록한다.
여러 사진에 공통으로 확인되는 의상 특성을 우선하고, 불확실한 품목은 낮은 visual_confidence를 준다.
JSON 객체: {{"items":[{{"category":"아우터/상의/하의/원피스/가방/신발/모자/주얼리/기타","description":"","color":"","silhouette":"","logo_clue":"","visual_confidence":0}}],"overall_notes":""}}"""
    try:state["result"]=_ollama_vision_json(sel_paths,prompt,model)
    except Exception as exc:state["errors"].append(str(exc))
    return state


def collect_reference_images(candidate_ids=None,progress=None):
    """Explicitly collect only outfit-related reference images for selected candidates.

    Files are evidence/analysis references; they are not automatically promoted
    to blog image slots.  This prevents news/photo copyright material from being
    silently republished while still letting the outfit verifier use the images.
    """
    init_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    where="WHERE 1=1";params=[]
    ids=[int(x) for x in (candidate_ids or []) if str(x).isdigit()]
    if ids:where+=" AND id IN ("+",".join("?" for _ in ids)+")";params.extend(ids)
    rows=con.execute("SELECT * FROM celebrity_style_candidates "+where+" ORDER BY event_date DESC,confidence_score DESC LIMIT 80",params).fetchall();count=0;images=0
    for idx,row in enumerate(rows):
        if progress:progress(idx,len(rows),f"착장 관련 이미지 · {row['celebrity_name']} · {row['look_type']}")
        ref=_collect_outfit_reference_images(row,_candidate_sources(row));images+=len(ref.get("downloaded") or [])
        old=_safe_json(row["vision_json"],{});old["reference_search"]=ref;old["reference_only_collected_at"]=_now()
        con.execute("UPDATE celebrity_style_candidates SET vision_json=?,updated_at=? WHERE id=?",(json.dumps(old,ensure_ascii=False),_now(),row["id"]));con.commit();count+=1
    con.close();_write_candidates_csv()
    if progress:progress(len(rows),len(rows) or 1,"착장 관련 이미지 수집 완료")
    return {"processed":count,"images":images,"message":f"착장 관련 참고이미지 {images}장 · 후보 {count}건 수집 완료"}

def _ai_extract_items(row,sources,page_texts,vision):
    cfg=settings();evidence=[]
    for i,s in enumerate(sources[:12]):
        evidence.append({"i":i,"type":s.get("source_type"),"title":s.get("title"),"description":s.get("description"),"url":s.get("url"),"pub_date":s.get("pub_date")})
    prompt=f"""너는 20년 경력의 패션 리서처이자 팩트체커다. 연예인 착장 상품을 식별하되 오정보가 생기지 않도록 매우 보수적으로 판단한다.
대상: {row['celebrity_name']} / {row['look_type']} / 날짜 {row['event_date'] or '미확인'}
규칙:
1. brand/model_name은 아래 텍스트 근거에 실제로 명시된 경우만 쓴다. 사진/Vision만으로 브랜드나 모델을 만들어내지 않는다.
2. exact_text_evidence에는 어떤 source index가 브랜드/제품을 명시하는지 번호만 쓴다.
3. 같은 아이템을 여러 줄로 중복 만들지 않는다.
4. 품목은 최대 6개. 카테고리, 색상, 특징은 텍스트와 Vision을 조합할 수 있다.
5. evidence_level은 '텍스트확정','텍스트강함','시각추정','스타일유사' 중 하나.
6. exact_claim_allowed=true는 최소한 브랜드+구체 제품/모델 식별 정보가 텍스트에 존재할 때만 가능하다. 단순 브랜드명만 있으면 false.
JSON 객체: {{"items":[{{"category":"","description":"","brand":"","model_name":"","color":"","evidence_level":"","exact_text_evidence":[0],"exact_claim_allowed":false,"notes":""}}],"summary":""}}
텍스트근거={json.dumps(evidence,ensure_ascii=False)}
원문보강={json.dumps(page_texts,ensure_ascii=False)}
Vision보조={json.dumps((vision or {}).get('result') or {},ensure_ascii=False)}"""
    try:
        obj=content_adapter.call_ollama(prompt,ollama_local.resolve_model(cfg),cfg)
        return obj if isinstance(obj,dict) else {"items":[],"summary":""}
    except Exception as exc:
        log("착장 아이템 AI 분석 실패: "+str(exc));return {"items":[],"summary":""}


def _item_confidence(item,sources):
    idxs=[]
    for x in item.get("exact_text_evidence") or []:
        try:i=int(x)
        except Exception:continue
        if 0<=i<len(sources):idxs.append(i)
    hosts={_independent_host(sources[i].get("url")) for i in idxs if _independent_host(sources[i].get("url"))}
    brand=bool(_clean(item.get("brand")));model=bool(_clean(item.get("model_name")));level=str(item.get("evidence_level") or "")
    score=18
    if idxs:score+=22
    if len(hosts)>=2:score+=22
    elif len(hosts)==1:score+=10
    if brand:score+=12
    if model:score+=18
    if level=="텍스트확정":score+=8
    elif level=="텍스트강함":score+=4
    exact=bool(item.get("exact_claim_allowed")) and brand and model
    # One source is enough only when it is a deliberately high-authority
    # newsroom/official domain. Generic portal news, blogs, and Google results
    # require corroboration from a second independent host.
    if exact and len(hosts)<2:
        auth=max((_source_weight(sources[i].get("url"),sources[i].get("source_type")) for i in idxs),default=0)
        if auth<.95: exact=False;score=min(score,82)
    return min(100,score),exact,len(hosts)


def analyze_unfinished(candidate_ids=None,progress=None):
    init_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    where="WHERE status NOT IN ('원고완료','작성물연동')";params=[]
    ids=[int(x) for x in (candidate_ids or []) if str(x).isdigit()]
    if ids:where+=" AND id IN ("+",".join("?" for _ in ids)+")";params.extend(ids)
    rows=con.execute("SELECT * FROM celebrity_style_candidates "+where+" ORDER BY event_date DESC,confidence_score DESC LIMIT 80",params).fetchall()
    processed=0
    for idx,row in enumerate(rows):
        if progress:progress(idx,len(rows),f"착장 검증 · {row['celebrity_name']} · {row['look_type']}")
        sources=_candidate_sources(row);page_texts=[]
        if bool(settings().get("celebrity_style_fetch_source_pages",True)):
            checks=max(0,int(settings().get("celebrity_style_source_page_checks",2)))
            ranked=sorted(sources,key=lambda s:_source_weight(s.get("url"),s.get("source_type")),reverse=True)
            for s in ranked[:checks]:
                txt=_fetch_source_page_text(s.get("url") or "",row["celebrity_name"])
                if txt:page_texts.append({"url":s.get("url"),"text":txt[:8000]})
        vision=_vision_analyze(row,sources)
        ai=_ai_extract_items(row,sources,page_texts,vision)
        con.execute("DELETE FROM celebrity_style_items WHERE candidate_id=?",(row["id"],))
        item_scores=[]
        for it in ai.get("items") or []:
            if not isinstance(it,dict):continue
            desc=_clean(it.get("description"));brand=_clean(it.get("brand"));model=_clean(it.get("model_name"));cat=_clean(it.get("category")) or "기타"
            if not desc and not brand and not model:continue
            score,exact,indep=_item_confidence(it,sources);item_scores.append(score)
            ev={"text_source_indices":it.get("exact_text_evidence") or [],"independent_sources":indep,"notes":it.get("notes") or "","rule":"VISUAL_NEVER_CONFIRMS_BRAND_MODEL"}
            con.execute("""INSERT OR REPLACE INTO celebrity_style_items
              (candidate_id,item_category,item_description,brand,model_name,color,evidence_level,confidence_score,exact_claim_allowed,evidence_json,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (row["id"],cat,desc,brand,model,_clean(it.get("color")),_clean(it.get("evidence_level")) or "추정",score,1 if exact else 0,json.dumps(ev,ensure_ascii=False),_now()))
        candidate_score=float(row["confidence_score"] or 0)
        if item_scores:candidate_score=min(100,round(candidate_score*.55+max(item_scores)*.45,1))
        label="확정가능" if any(x>=85 for x in item_scores) else ("근거강함" if candidate_score>=70 else "추정")
        status="착장분석완료" if item_scores else "착장근거부족"
        con.execute("UPDATE celebrity_style_candidates SET summary=?,vision_json=?,confidence_score=?,confidence_label=?,status=?,updated_at=?,last_error=NULL WHERE id=?",
                    (_clean(ai.get("summary")) or row["summary"],json.dumps(vision,ensure_ascii=False),candidate_score,label,status,_now(),row["id"]))
        con.commit();processed+=1
    con.close();_write_candidates_csv();_write_items_csv()
    if progress:progress(len(rows),len(rows) or 1,"착장 분석 완료")
    return {"processed":processed,"message":f"착장 근거 분석 {processed}건 완료"}


def _product_target(item):
    parts=[_clean(item["brand"]),_clean(item["model_name"])]
    if not parts[1]:parts.append(_clean(item["item_description"]))
    return " ".join(x for x in parts if x).strip()


def _similar_query(item):
    desc=_clean(item["item_description"]);color=_clean(item["color"]);cat=_clean(item["item_category"])
    brand=_clean(item["brand"])
    # For a similar style fallback, do not force a guessed brand into the query.
    return " ".join(x for x in (color,desc,cat) if x)[:100]


def _best_similar_coupang(query):
    if not query:return None
    try:rows=coupang_partners_api.search(query,10)
    except Exception:return None
    toks=set(re.findall(r"[0-9A-Za-z가-힣]+",query.casefold()))
    best=None;bestscore=-1
    for pos,r in enumerate(rows):
        name=_clean(r.get("name"));nt=set(re.findall(r"[0-9A-Za-z가-힣]+",name.casefold()))
        overlap=len(toks&nt)/max(1,len(toks));score=overlap*100-max(0,pos)*1.5
        if score>bestscore:bestscore=score;best=dict(r);best["similarity_score"]=round(score,1)
    return best


def match_products(candidate_ids=None,progress=None):
    init_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    where="WHERE c.status IN ('착장분석완료','상품매칭부분','착장근거부족')";params=[]
    ids=[int(x) for x in (candidate_ids or []) if str(x).isdigit()]
    if ids:where+=" AND c.id IN ("+",".join("?" for _ in ids)+")";params.extend(ids)
    items=con.execute("SELECT i.*,c.celebrity_name,c.look_type FROM celebrity_style_items i JOIN celebrity_style_candidates c ON c.id=i.candidate_id "+where+" ORDER BY c.confidence_score DESC,i.confidence_score DESC",params).fetchall()
    matched=0
    for idx,it in enumerate(items):
        if progress:progress(idx,len(items),f"상품 검증 · {it['celebrity_name']} · {it['item_category']}")
        target=_product_target(it);nav=None;cp=None;match_type="미확인";exact_allowed=bool(it["exact_claim_allowed"]);chosen=None
        if target and exact_allowed:
            try:nav,_errs=naver_shopping_api.best_exact_match(target,max_queries=3,threshold=.58)
            except Exception:nav=None
            try:cp=coupang_partners_api.best_exact_match(target,max_queries=3,threshold=.58)
            except Exception:cp=None
            # Exact identity always beats affiliate availability. Never replace a NAVER-exact item
            # with a merely similar Coupang item while keeping an exact label.
            if cp:match_type="정확상품";chosen=cp
            elif nav:match_type="정확상품(네이버검증)";chosen=nav
        if chosen is None:
            sq=_similar_query(it)
            sim=_best_similar_coupang(sq)
            if sim:
                cp=sim;chosen=sim;match_type="유사스타일"
        if chosen:
            matched+=1
            con.execute("""UPDATE celebrity_style_items SET naver_product_json=?,coupang_product_json=?,matched_name=?,matched_url=?,matched_price=?,matched_image_url=?,match_type=?,updated_at=? WHERE id=?""",
             (json.dumps(nav or {},ensure_ascii=False),json.dumps(cp or {},ensure_ascii=False),_clean(chosen.get("name")),str(chosen.get("url") or ""),int(chosen.get("price") or 0),str(chosen.get("image_url") or ""),match_type,_now(),it["id"]))
        else:
            con.execute("UPDATE celebrity_style_items SET match_type='미확인',updated_at=? WHERE id=?",(_now(),it["id"]))
        con.commit()
    cand_ids={int(x["candidate_id"]) for x in items}
    for cid in cand_ids:
        cnt=con.execute("SELECT COUNT(*) FROM celebrity_style_items WHERE candidate_id=? AND matched_name<>''",(cid,)).fetchone()[0]
        con.execute("UPDATE celebrity_style_candidates SET status=?,updated_at=? WHERE id=?",("상품매칭완료" if cnt else "상품매칭부분",_now(),cid))
    con.commit();con.close();_write_items_csv();_write_candidates_csv()
    if progress:progress(len(items),len(items) or 1,"상품 검증 완료")
    return {"processed":len(items),"matched":matched,"message":f"착장 아이템 {len(items)}개 검증 · 상품 연결 {matched}개"}


def _draft_prompt(row,items,sources):
    safe_items=[]
    for it in items:
        safe_items.append({"category":it["item_category"],"description":it["item_description"],"brand":it["brand"],"model_name":it["model_name"],"color":it["color"],
                           "evidence_level":it["evidence_level"],"confidence":it["confidence_score"],"exact_claim_allowed":bool(it["exact_claim_allowed"]),
                           "matched_name":it["matched_name"],"match_type":it["match_type"],"matched_price":it["matched_price"]})
    src=[{"title":s.get("title"),"url":s.get("url"),"type":s.get("source_type"),"date":s.get("pub_date")} for s in sources[:8]]
    return f"""너는 네이버 블로그 패션 에디터다. 검색 유입과 신뢰도를 둘 다 중시한다. 아래 검증 데이터만 사용해 연예인 착장 분석 글을 작성한다.
대상: {row['celebrity_name']} / {row['look_type']} / {row['event_date'] or '날짜 미확인'}
절대 규칙:
- exact_claim_allowed=false인 아이템을 '{row['celebrity_name']}가 착용한 정확한 제품'이라고 쓰지 않는다. 반드시 '비슷한 분위기/유사 스타일/추정'으로 표현한다.
- 기사에서 확인되지 않은 가격, 소재, 제품명, 브랜드를 만들지 않는다.
- 직접 구매/직접 착용/내돈내산 표현 금지. 연예인과 제품의 협찬 여부도 근거 없으면 언급하지 않는다.
- 출처 원문 문장을 길게 복사하지 말고 사실만 재서술한다.
- 제목은 70자 이내, '{row['celebrity_name']} 착장' 핵심어와 {row['look_type']}을 자연스럽게 포함한다.
- 본문은 모바일 가독성, 4~5개 소제목, 900~1400자 정도. 각 문단은 1~3문장.
- 패션 기사를 요약한 보고서처럼 쓰지 말고, 친구와 오늘 착장 얘기를 나누듯 자연스러운 존댓말로 쓴다.
- `~합니다/~됩니다/~있습니다`가 연속되지 않게 하고 `~해요/~죠/~네요/~더라고요/~같아요` 같은 대화형 호흡을 섞는다.
- 사진이나 검증 정보에서 실제로 눈에 띄는 포인트에 `오, 이 조합은 눈에 들어오네요!`, `이런 부분이 궁금해지죠?` 같은 자연스러운 반응/질문을 2~3번 섞되 표현을 반복하지 않는다.
- `따라서/즉/전반적으로/측면에서/해당 제품/활용할 수 있습니다` 같은 AI·보고서식 표현은 피한다.
- 직접 착용했다고 꾸미지 말고 관찰자 시점의 자연스러운 대화체를 유지한다.
- 정확상품/유사스타일을 명확히 구분하고, 마지막에 '현재 판매 옵션과 가격은 링크에서 다시 확인' 취지 문장을 넣는다.
- 태그 30개를 중복 단어 과다 없이 반환한다.
JSON 객체만: {{"title":"","intro":[""],"sections":[{{"heading":"❤️ ...","paragraphs":[""]}}],"advantages":[""],"conclusion":"","tags":[""]}}
검증아이템={json.dumps(safe_items,ensure_ascii=False)}
출처메타={json.dumps(src,ensure_ascii=False)}"""


def _fallback_draft(row,items):
    celeb=row["celebrity_name"];look=row["look_type"];date=row["event_date"]
    title=f"{celeb} {look} 착장｜가방·신발·아우터 어디 제품인지 근거별로 확인"
    sections=[]
    for it in items[:4]:
        exact=bool(it["exact_claim_allowed"]);match=it["match_type"] or "미확인"
        item=" ".join(x for x in (it["brand"],it["model_name"],it["item_description"]) if x).strip() or it["item_category"]
        wording=(f"확인 가능한 텍스트 근거에서 {item} 정보가 잡혔습니다." if exact else f"{it['item_category']}은 {it['color']} {it['item_description']} 계열로 보이며, 정확 제품 확정 근거는 부족합니다.")
        if match=="유사스타일":wording+=" 연결된 쇼핑 상품은 실제 착용품 확정이 아니라 비슷한 스타일 참고용입니다."
        sections.append({"heading":f"❤️ {it['item_category']} 체크", "paragraphs":[wording]})
    if not sections:sections=[{"heading":"❤️ 착장 포인트","paragraphs":["공개된 기사와 검색 자료를 기준으로 확인했지만 정확 제품을 단정할 수준의 근거는 아직 부족합니다."]}]
    tags=[celeb,f"{celeb}착장",f"{celeb}패션",look,"연예인착장","연예인패션","공항패션","셀럽패션","데일리룩","패션정보","착장정보","가방정보","신발정보","아우터정보","여자패션","남자패션","코디추천","패션코디","스타일링","패션아이템","브랜드정보","제품정보","유사상품","스타일분석","패션트렌드","오늘패션","연예인코디","셀럽코디","패션검색","착장분석"][:30]
    intro=(f"{date} 전후 공개된 자료를 기준으로 {celeb}의 {look} 착장을 정리해봤습니다." if date
           else f"최근 검색에서 확인된 공개 자료를 기준으로 {celeb}의 {look} 착장을 정리해봤습니다. 자료의 게시 날짜가 확인되지 않은 항목은 최신 착장으로 단정하지 않습니다.")
    return {"title":title[:70],"intro":[intro+" 정확 제품과 유사 스타일은 구분해서 봐주세요."],"sections":sections,"advantages":["확정 근거와 추정을 분리해 표시","행사·날짜가 맞는 자료를 우선 확인","유사 상품은 실제 착용품처럼 표현하지 않음"],"conclusion":"착장 정보와 판매 상품은 수시로 바뀔 수 있으니 현재 옵션과 가격은 연결된 상품 페이지에서 다시 확인하는 편이 좋습니다.","tags":tags}


def _draft_to_blocks(obj,sources):
    blocks=[]
    for p in obj.get("intro") or []:blocks.append({"type":"paragraph","lines":[_clean(p)],"layout":"mobile_center","role":"intro"})
    for i,s in enumerate(obj.get("sections") or []):
        blocks.append({"type":"heading","text":_clean(s.get("heading")),"format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center","section_index":i})
        for p in s.get("paragraphs") or []:blocks.append({"type":"paragraph","lines":[_clean(p)],"layout":"mobile_center","section_index":i})
    blocks.append({"type":"heading","text":"✔ 착장 정보 확인 기준","format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center"})
    for a in (obj.get("advantages") or [])[:5]:blocks.append({"type":"check","text":"✔ "+_clean(a),"format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center"})
    c=_clean(obj.get("conclusion"));
    if c:blocks.append({"type":"paragraph","lines":[c],"layout":"mobile_center","role":"conclusion"})
    if sources:
        blocks.append({"type":"heading","text":"📌 확인한 공개 자료","format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center"})
        for s in sources[:5]:
            title=_clean(s.get("title"));host=_independent_host(s.get("url"))
            if title:blocks.append({"type":"paragraph","lines":[f"{host or s.get('source_type','출처')} · {title[:90]}"],"layout":"mobile_center","role":"source_meta"})
    return blocks


def generate_drafts(candidate_ids=None,progress=None):
    init_schema();cfg=settings();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    where="WHERE status IN ('착장분석완료','상품매칭완료','상품매칭부분','착장근거부족')";params=[]
    ids=[int(x) for x in (candidate_ids or []) if str(x).isdigit()]
    if ids:where+=" AND id IN ("+",".join("?" for _ in ids)+")";params.extend(ids)
    rows=con.execute("SELECT * FROM celebrity_style_candidates "+where+" ORDER BY event_date DESC,confidence_score DESC LIMIT 80",params).fetchall();made=0
    for idx,row in enumerate(rows):
        if progress:progress(idx,len(rows),f"착장 원고 생성 · {row['celebrity_name']} · {row['look_type']}")
        items=con.execute("SELECT * FROM celebrity_style_items WHERE candidate_id=? ORDER BY confidence_score DESC,id",(row["id"],)).fetchall();sources=_candidate_sources(row)
        try:
            obj=content_adapter.call_ollama(_draft_prompt(row,items,sources),ollama_local.resolve_model(cfg),cfg) if ollama_local.status(cfg).get("ready") else _fallback_draft(row,items)
        except Exception as exc:
            log("착장 원고 Ollama fallback: "+str(exc));obj=_fallback_draft(row,items)
        if not isinstance(obj,dict):obj=_fallback_draft(row,items)
        title=_clean(obj.get("title"))[:70] or _fallback_draft(row,items)["title"]
        tags=[];seen=set()
        for t in obj.get("tags") or []:
            t=_clean(t).lstrip("#")
            if not t or t.casefold() in seen:continue
            seen.add(t.casefold());tags.append(t)
        for t in _fallback_draft(row,items)["tags"]:
            if len(tags)>=30:break
            if t.casefold() not in seen:seen.add(t.casefold());tags.append(t)
        blocks=_draft_to_blocks(obj,sources)
        body=json.dumps(blocks,ensure_ascii=False)
        con.execute("UPDATE celebrity_style_candidates SET draft_title=?,draft_body=?,draft_tags=?,status='원고완료',updated_at=?,last_error=NULL WHERE id=?",
                    (title,body,",".join(tags[:30]),_now(),row["id"]));con.commit();made+=1
    con.close();_write_candidates_csv()
    if progress:progress(len(rows),len(rows) or 1,"착장 원고 생성 완료")
    return {"processed":made,"message":f"연예인 착장 원고 {made}건 생성 완료"}


def _next_product_no(con):
    try:return int(con.execute("SELECT COALESCE(MAX(product_no),0)+1 FROM products").fetchone()[0])
    except Exception:return 1


def promote_candidate(candidate_id):
    """Promote one drafted outfit article into the existing product/blog pipeline.

    The product identity is the best verified marketplace item, so the existing
    strict 3-image engine searches the selected physical product. The article itself
    remains a celebrity-style article and labels similar items as similar.
    """
    init_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    row=con.execute("SELECT * FROM celebrity_style_candidates WHERE id=?",(int(candidate_id),)).fetchone()
    if not row:con.close();raise RuntimeError("착장 후보를 찾지 못했습니다.")
    if not row["draft_title"] or not row["draft_body"] or not row["draft_tags"]:con.close();raise RuntimeError("먼저 착장 블로그 원고를 생성하세요.")
    item=con.execute("SELECT * FROM celebrity_style_items WHERE candidate_id=? AND COALESCE(matched_name,'')<>'' AND COALESCE(matched_url,'')<>'' ORDER BY CASE WHEN match_type='정확상품' THEN 0 WHEN match_type LIKE '정확상품%' THEN 1 ELSE 2 END, confidence_score DESC LIMIT 1",(row["id"],)).fetchone()
    if not item:con.close();raise RuntimeError("연결 가능한 상품이 없습니다. 먼저 상품 검증/매칭을 실행하세요.")
    existing=con.execute("SELECT id FROM products WHERE content_type='celebrity_style' AND celebrity_style_id=? LIMIT 1",(row["id"],)).fetchone()
    if existing:
        pid=int(existing[0]);con.execute("UPDATE products SET name=?,category=?,source_platform='연예인착장',source_url=?,title=?,body=?,tags=?,status='연예인착장원고완료',updated_at=datetime('now','localtime') WHERE id=?",
          (item["matched_name"],"패션잡화" if item["item_category"] in {"가방","신발","모자","주얼리/액세서리"} else "패션의류",item["matched_url"],row["draft_title"],row["draft_body"],row["draft_tags"],pid))
    else:
        pno=_next_product_no(con)
        cur=con.execute("""INSERT INTO products(product_no,name,category,product_identity,source_platform,source_url,score,status,title,body,tags,content_type,celebrity_style_id,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                        (pno,item["matched_name"],"패션잡화" if item["item_category"] in {"가방","신발","모자","주얼리/액세서리"} else "패션의류",clean_listing_title_noise(item["matched_name"]),"연예인착장",item["matched_url"],float(row["confidence_score"] or 0),"연예인착장원고완료",row["draft_title"],row["draft_body"],row["draft_tags"],"celebrity_style",row["id"]))
        pid=int(cur.lastrowid)
    # Prefer a verified/selected Coupang result for affiliate conversion. Similar-style matches remain clearly labelled in article text.
    try:
        cp=_safe_json(item["coupang_product_json"],{})
        if cp and str(cp.get("url") or "").strip():
            dl=coupang_partners_api.create_deeplink(str(cp.get("url") or ""),product_id=str(cp.get("product_id") or ""),product_name=str(cp.get("name") or item["matched_name"]))
            if dl.get("ok"):
                con.execute("UPDATE products SET sharelink=? WHERE id=?",(str(dl.get("sharelink") or dl.get("shorten_url") or ""),pid))
    except Exception as exc:log("연예인 착장 Sharelink 생성 보류: "+str(exc))
    con.execute("UPDATE celebrity_style_candidates SET promoted_product_id=?,status='작성물연동',updated_at=? WHERE id=?",(pid,_now(),row["id"]))
    con.execute("UPDATE celebrity_style_items SET matched_product_id=? WHERE id=?",(pid,item["id"]));con.commit();con.close()
    return {"product_id":pid,"candidate_id":row["id"],"matched_name":item["matched_name"],"match_type":item["match_type"],"message":f"기존 작성 파이프라인에 연동 완료 · 상품ID {pid}"}


def candidate_rows(limit=300):
    init_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    rows=con.execute("SELECT * FROM celebrity_style_candidates ORDER BY event_date DESC,confidence_score DESC,updated_at DESC LIMIT ?",(int(limit),)).fetchall();out=[]
    for r in rows:
        d=dict(r);items=con.execute("SELECT * FROM celebrity_style_items WHERE candidate_id=? ORDER BY confidence_score DESC,id",(r["id"],)).fetchall()
        d["items"]=[dict(x) for x in items];d["item_count"]=len(items);d["matched_count"]=sum(1 for x in items if x["matched_name"])
        out.append(d)
    con.close();return out


def candidate_detail(candidate_id):
    init_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    r=con.execute("SELECT * FROM celebrity_style_candidates WHERE id=?",(int(candidate_id),)).fetchone()
    if not r:con.close();return None
    d=dict(r);d["sources"]=_candidate_sources(r);d["vision"]=_safe_json(r["vision_json"],{});d["items"]=[dict(x) for x in con.execute("SELECT * FROM celebrity_style_items WHERE candidate_id=? ORDER BY confidence_score DESC,id",(r["id"],)).fetchall()]
    con.close();return d


def _write_candidates_csv():
    OUTPUTS.mkdir(parents=True,exist_ok=True);p=OUTPUTS/"celebrity_style_candidates.csv";rows=candidate_rows(500)
    fields=["id","celebrity_name","event_date","look_type","source_count","independent_source_count","confidence_score","confidence_label","item_count","matched_count","status","draft_title","promoted_product_id"]
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})
    return p


def _write_items_csv():
    OUTPUTS.mkdir(parents=True,exist_ok=True);p=OUTPUTS/"celebrity_style_items.csv";con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    rows=con.execute("SELECT c.celebrity_name,c.event_date,c.look_type,i.* FROM celebrity_style_items i JOIN celebrity_style_candidates c ON c.id=i.candidate_id ORDER BY c.event_date DESC,c.id,i.confidence_score DESC").fetchall();con.close()
    fields=["candidate_id","celebrity_name","event_date","look_type","item_category","item_description","brand","model_name","color","evidence_level","confidence_score","exact_claim_allowed","matched_name","matched_price","match_type","matched_url"]
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:w.writerow({k:r[k] if k in r.keys() else "" for k in fields})
    return p


def export_paths():
    return {"candidates":str(_write_candidates_csv()),"items":str(_write_items_csv())}


def run_full(days=None,celebrity="",progress=None):
    phases=[("최신 착장 수집",collect_latest),("착장 근거 분석",analyze_unfinished),("상품 검증/매칭",match_products),("블로그 원고 생성",generate_drafts)]
    results={};batch_ids=[]
    for pi,(name,fn) in enumerate(phases):
        def cb(d,t,m,pi=pi,name=name):
            if progress:progress(pi*100+(d/max(1,t))*100,len(phases)*100,f"{name} · {m}")
        if fn is collect_latest:
            r=fn(days=days,celebrity=celebrity,progress=cb);batch_ids=list(r.get("candidate_ids") or [])
        else:r=fn(candidate_ids=batch_ids or None,progress=cb)
        results[name]=r
    if progress:progress(100,100,"연예인 착장 전체 파이프라인 완료")
    return {"stage_ok":True,"results":results,"message":"연예인 착장 수집 → 검증 → 상품매칭 → 원고생성 완료"}

init_schema()
