# -*- coding: utf-8 -*-
from pathlib import Path
import json, sqlite3, time, re, os, shutil, sys
ROOT=(Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[1])
DATA=ROOT/"data"; DB=DATA/"studio.db"
LOGS=ROOT/"logs"; EVIDENCE=ROOT/"evidence"; OUTPUTS=ROOT/"outputs"; POSTS=ROOT/"posts"
COUPANG_DISCLOSURE_LINES=(
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로,",
    "이에 따른 일정액의 수수료를 제공받습니다.",
)
def settings():
    return json.loads((DATA/"settings.json").read_text(encoding="utf-8"))
def log(msg):
    LOGS.mkdir(exist_ok=True)
    with (LOGS/"studio.log").open("a",encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ")+str(msg)+"\n")

# A released ZIP intentionally does not contain API secrets.  When a new
# version is extracted beside an older working install, carry only the user's
# local connection files forward.  This prevents a fresh version directory
# from silently losing Toss/Coupang/NAVER access while never overwriting keys
# that were already configured in the current version.
MIGRATABLE_RUNTIME_FILES={
    "toss_sharelink_api_credentials.json",
    "coupang_partners_credentials.json",
    "naver_image_api_credentials.json",
    "openai_api_credentials.json",
    "normal_chrome_profile.json",
    "content_phrase_history.json",
    "blog_upload_history.json",
    "published_product_registry.json",
    "already_posted_config.json",
}
_RUNTIME_MIGRATION={"checked":False,"copied":[],"source":"","errors":[]}

def _version_tuple(path):
    # Keep the patch/release component too.  v8.08.43 -> v8.08.44 is a
    # real upgrade and must be able to migrate the user's local API/profile
    # files even though the major/minor pair is identical.
    m=re.search(r"(?i)v(\d+)[_.-](\d+)(?:[_.-](\d+))?",str(path))
    return (int(m.group(1)),int(m.group(2)),int(m.group(3) or 0)) if m else (-1,-1,-1)

def _valid_runtime_file(name,path):
    try:obj=json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:return False
    if not isinstance(obj,dict):return False
    if name=="toss_sharelink_api_credentials.json":
        return bool(obj.get("access_token") or (obj.get("access_key") and obj.get("secret_key")))
    if name=="coupang_partners_credentials.json":
        return bool(obj.get("access_key") and obj.get("secret_key"))
    if name=="naver_image_api_credentials.json":
        return bool(obj.get("client_id") and obj.get("client_secret"))
    if name=="openai_api_credentials.json":
        return bool(str(obj.get("api_key") or "").strip())
    if name=="normal_chrome_profile.json":
        return bool(obj.get("user_data_dir") or obj.get("profile_directory") or obj.get("profile"))
    if name=="content_phrase_history.json":
        # Release ships an empty template. Treat it as NOT configured so a
        # previous install's phrase history can migrate and keep repetition
        # detection continuous across upgrades.
        return isinstance(obj.get("items"),list) and bool(obj.get("items"))
    if name=="blog_upload_history.json":
        # Same rule for draft fingerprints: an empty release template must not
        # block migration of the user's prior successful-save history.
        return isinstance(obj,dict) and bool(obj)
    if name=="published_product_registry.json":
        # Carry the durable "already drafted product" ledger to a new version.
        # An empty release template must not hide a populated older ledger.
        items=obj.get("items")
        return (isinstance(items,dict) and bool(items)) or (isinstance(items,list) and bool(items))
    if name=="already_posted_config.json":
        return bool(str(obj.get("blog_id") or "").strip())
    return False

def _previous_install_roots():
    current=ROOT.resolve();current_version=_version_tuple(ROOT)
    found=[];seen=set()
    for base in (ROOT.parent,ROOT.parent.parent):
        if not base.exists():continue
        try:
            outer=(list(base.glob("NaverBlog_Automation_Studio_v7_*"))+list(base.glob("NBlog_v7_*"))+
                   list(base.glob("NaverBlog_Automation_Studio_v8_*"))+list(base.glob("NBlog_v8_*")))
        except Exception:outer=[]
        for folder in outer:
            candidates=[folder]
            try:
                candidates.extend(x for x in folder.iterdir() if x.is_dir() and
                                  (x.name.startswith(("NaverBlog_Automation_Studio_v7_","NBlog_v7_",
                                                      "NaverBlog_Automation_Studio_v8_","NBlog_v8_"))))
            except Exception:pass
            for candidate in candidates:
                try:resolved=candidate.resolve()
                except Exception:continue
                if resolved==current or resolved in seen or not (resolved/"data").is_dir():continue
                ver=_version_tuple(resolved)
                if current_version!=(-1,-1,-1) and ver!=(-1,-1,-1) and ver>=current_version:continue
                seen.add(resolved)
                try:mtime=resolved.stat().st_mtime
                except Exception:mtime=0
                found.append((ver,mtime,resolved))
    found.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return [x[2] for x in found]

def migrate_previous_install_data(force=False):
    global _RUNTIME_MIGRATION
    if _RUNTIME_MIGRATION.get("checked") and not force:return dict(_RUNTIME_MIGRATION)
    result={"checked":True,"copied":[],"source":"","errors":[]}
    DATA.mkdir(parents=True,exist_ok=True)
    roots=_previous_install_roots()
    for name in sorted(MIGRATABLE_RUNTIME_FILES):
        dest=DATA/name
        if _valid_runtime_file(name,dest):continue
        for root in roots:
            source=root/"data"/name
            if not _valid_runtime_file(name,source):continue
            try:
                temp=dest.with_name(dest.name+".migrating")
                shutil.copy2(source,temp);os.replace(temp,dest)
                result["copied"].append(name)
                if not result["source"]:result["source"]=root.name
                break
            except Exception as exc:
                result["errors"].append(f"{name}: {exc}")
    _RUNTIME_MIGRATION=result
    if result["copied"]:
        log("이전 버전 연결 설정 자동 승계: "+", ".join(result["copied"])+" / source="+result["source"])
    if result["errors"]:log("이전 버전 연결 설정 승계 실패: "+" | ".join(result["errors"]))
    return dict(result)
def init_db():
    con=sqlite3.connect(DB); c=con.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_no INTEGER, name TEXT, category TEXT,
      product_identity TEXT, source_platform TEXT, source_url TEXT,
      score REAL DEFAULT 0, status TEXT DEFAULT '대기',
      title TEXT, body TEXT, tags TEXT,
      image1 TEXT,image2 TEXT,image3 TEXT,
      price_toss INTEGER,price_coupang INTEGER,price_naver INTEGER,
      price_checked_at TEXT, price_compare_image TEXT,
      sharelink TEXT, approved INTEGER DEFAULT 0,
      post_dir TEXT, last_error TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS candidates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      platform TEXT, category TEXT, query TEXT, name TEXT,
      price INTEGER, url TEXT, image_url TEXT, rank_no INTEGER,
      captured_at TEXT
    );
    CREATE TABLE IF NOT EXISTS jobs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER, step TEXT, status TEXT, message TEXT,
      retry_count INTEGER DEFAULT 0, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS trend_candidates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT, age_group TEXT, age_codes TEXT, category TEXT,
      rank_no INTEGER, keyword TEXT, captured_at TEXT,
      page_url TEXT, status TEXT DEFAULT '수집완료', evidence_json TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_trend_candidates_scope
      ON trend_candidates(source,age_group,category,rank_no);
    CREATE TABLE IF NOT EXISTS trend_product_picks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      category TEXT, keyword TEXT, trend_sources TEXT, age_groups TEXT,
      trend_score REAL DEFAULT 0, coupang_name TEXT, coupang_url TEXT,
      coupang_price INTEGER, coupang_image_url TEXT, review_count INTEGER DEFAULT 0,
      purchase_count INTEGER DEFAULT 0, rating REAL DEFAULT 0, popularity_score REAL DEFAULT 0,
      search_position INTEGER DEFAULT 0, status TEXT, evidence_json TEXT,
      captured_at TEXT, product_id INTEGER
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_trend_product_pick_scope
      ON trend_product_picks(category,keyword);
    CREATE TABLE IF NOT EXISTS affiliate_link_cache(
      coupang_product_id TEXT NOT NULL,
      sub_id TEXT NOT NULL DEFAULT '',
      product_name TEXT,
      source_url TEXT,
      sharelink TEXT NOT NULL,
      response_code TEXT,
      metadata_json TEXT,
      created_at TEXT NOT NULL,
      last_used_at TEXT NOT NULL,
      PRIMARY KEY(coupang_product_id,sub_id)
    );
    """)
    # Lightweight schema migrations for verification metadata.
    cols={r[1] for r in c.execute("PRAGMA table_info(products)").fetchall()}
    for name,typ in [
        ("image_verified_count","INTEGER DEFAULT 0"),
        ("image_evidence_json","TEXT"),
        ("price_verified_sites","INTEGER DEFAULT 0"),
        ("price_image_verified_sites","INTEGER DEFAULT 0"),
        ("price_evidence_json","TEXT"),
        ("seo_keywords","TEXT"),
        ("seo_evidence_json","TEXT"),
        ("import_batch_id","TEXT"),
        ("import_source_dir","TEXT"),
        ("import_item_no","INTEGER"),
        ("import_image_state","TEXT"),
        ("import_content_state","TEXT"),
        ("already_posted","INTEGER DEFAULT 0"),
        ("already_posted_review","INTEGER DEFAULT 0"),
        ("already_posted_auto_ignored","INTEGER DEFAULT 0"),
        ("already_posted_method","TEXT"),
        ("already_posted_title","TEXT"),
        ("already_posted_url","TEXT"),
        ("already_posted_at","TEXT"),
        ("already_posted_match_score","REAL"),
        ("content_type","TEXT DEFAULT 'product_review'"),
        ("celebrity_style_id","INTEGER DEFAULT 0")
    ]:
        if name not in cols:
            c.execute(f"ALTER TABLE products ADD COLUMN {name} {typ}")
    c.execute("CREATE INDEX IF NOT EXISTS ix_products_already_posted ON products(already_posted,already_posted_review,import_batch_id)")
    con.commit(); con.close()
def norm(s):
    return re.sub(r"\s+"," ",(s or "")).strip()

LISTING_TITLE_NOISE_PATTERNS=(
    r"(?:신세계|롯데|현대|갤러리아|AK|NC|국내)\s*백화점(?:\s*(?:상품|제품))?",
    r"선착순\s*쿠폰",r"슈퍼\s*적립",r"유\s*[/·-]?\s*무\s*라벨\s*랜덤\s*발송",
    r"유무라벨\s*랜덤\s*발송",r"라벨\s*랜덤\s*발송",r"랜덤\s*발송"
)

def clean_listing_title_noise(name):
    """Remove retailer/promotion decorations while preserving product brands.

    `광동 직영` becomes `광동`; only the seller marker is removed.  Retailer
    labels such as `신세계백화점` are removed as a phrase and never cause a
    broad deletion of ordinary brand words.
    """
    s=norm(str(name or ""))
    # Remove brackets only when their content is a known listing decoration.
    noise_union="|".join(LISTING_TITLE_NOISE_PATTERNS)+(r"|쿠폰|할인|특가|프로모션|이벤트|무료\s*배송|직영")
    s=re.sub(r"\[\s*(?:"+noise_union+r")[^\]]{0,40}\]\s*"," ",s,flags=re.I)
    for pattern in LISTING_TITLE_NOISE_PATTERNS:s=re.sub(pattern," ",s,flags=re.I)
    # Preserve the word immediately before 직영: 광동직영 -> 광동.
    s=re.sub(r"(?i)(?<![가-힣A-Za-z0-9])공식\s*직영(?![가-힣A-Za-z0-9])"," ",s)
    s=re.sub(r"(?i)([가-힣A-Za-z0-9]+)\s*직영(?![가-힣A-Za-z0-9])",r"\1",s)
    s=re.sub(r"(?i)(?<![가-힣A-Za-z0-9])직영(?![가-힣A-Za-z0-9])"," ",s)
    s=re.sub(r"\s+"," ",s).strip(" -_/·|,[]()")
    return s
def identity_terms(name):
    s=norm(clean_listing_title_noise(name))
    tokens=re.findall(r"[가-힣A-Za-z0-9]+",s)
    stop={"추천","후기","내돈내산","직접","써보니","제품","개입","개","1개"}
    return [t for t in tokens if t not in stop and len(t)>1][:10]
def product_match(text, terms):
    t=norm(text).lower()
    hits=sum(1 for x in terms if x.lower() in t)
    return hits/max(1,len(terms))


# ---- v5.2 strict product identity ----
CRITICAL_UNIT_RE = re.compile(
    r"(?i)(?:\b[A-Z]{1,8}[-_]?\d[A-Z0-9_-]*\b|\b\d+(?:\.\d+)?\s?(?:ml|kg|mg|cm|mm|oz|m|l|g|개입|개|매|팩|세트|인치|롤|병|캔|포|봉|장|겹)\b)"
)
PROMO_COUNT_RE = re.compile(r"(?i)\b\d+\s*\+\s*\d+\s*(?:개입|개|매|팩|세트|롤|병|캔|포|봉|장)\b")

def critical_identity_tokens(name):
    """Model numbers, capacities, counts and other variant-defining tokens."""
    raw=norm(name)
    promo=[re.sub(r"\s+","",x).lower() for x in PROMO_COUNT_RE.findall(raw)]
    found=list(dict.fromkeys(promo))
    unit_found=[]
    for x in CRITICAL_UNIT_RE.findall(raw):
        v=re.sub(r"\s+","",x).lower()
        if any(v in p for p in promo):
            continue
        if v not in unit_found:unit_found.append(v)
    # A trailing single-unit seller count such as "1개" is frequently omitted on
    # Naver/Toss even when the physical product/option is identical.  Treat it as
    # optional when a stronger capacity/count token (30개입, 120g, 30m, etc.) exists.
    weak_single={"1개","1팩","1세트","1롤","1병","1캔","1포","1봉","1장","1매"}
    has_strong=any(v not in weak_single for v in unit_found)
    for v in unit_found:
        if has_strong and v in weak_single:
            continue
        if v not in found:found.append(v)
    # Standalone long model-like tokens e.g. LE4W032ABK, S65M513
    for x in re.findall(r"\b(?=[A-Z0-9_-]{5,}\b)(?=.*[A-Z])(?=.*\d)[A-Z0-9_-]+\b", raw.upper()):
        v=x.lower()
        if v not in found: found.append(v)
    return found

SIGNATURE_GENERIC={
    "제품","상품","세트","구성","정품","공식","추천","용","타입","기본","베이직",
    "화이트","블랙","그레이","1개","2개","3개","4개","5개","10개"
}
def signature_identity_tokens(name):
    """One strong non-numeric product-line token used to reject same-size different variants.

    It is intentionally conservative: only the first few identity terms are considered,
    so long SEO tail words do not become mandatory.
    """
    terms=identity_terms(name)
    critical={x.lower() for x in critical_identity_tokens(name)}
    cands=[]
    for i,t in enumerate(terms[1:5],start=1):
        tl=t.lower()
        if tl in critical or t in SIGNATURE_GENERIC:continue
        if re.fullmatch(r"[0-9.]+",t):continue
        # Avoid pure count/capacity-like fragments already handled by critical tokens.
        if re.fullmatch(r"(?i)\d+(?:ml|kg|mg|cm|mm|oz|m|l|g|개입|개|매|팩|세트|인치|롤|병|캔|포|봉|장|겹)",t):continue
        cands.append((len(re.sub(r"[^가-힣A-Za-z0-9]","",t)), -i, t))
    if not cands:return []
    cands.sort(reverse=True)
    return [cands[0][2]]

def strict_product_match(text, target_name):
    """
    Hard gate critical variant tokens first, then normal semantic token ratio.
    If target says 200개입 but result says 100개입, it must fail.
    """
    t=norm(text).lower().replace(" ","")
    critical=critical_identity_tokens(target_name)
    target_low=norm(target_name).lower().replace(" ","")
    def critical_present(x):
        if x in t:return True
        m=re.fullmatch(r"(\d+)(개입|개|롤|매)",x)
        if not m:return False
        n,u=m.groups()
        # Marketplace titles often express the same package count differently.
        # Keep aliases narrow and product-type aware.
        if u in ("개입","개") and (n+"개입" in t or n+"개" in t):return True
        tissue=any(k in target_low for k in ("화장지","휴지","롤화장지","키친타월","키친타올"))
        sheet=any(k in target_low for k in ("마스크팩","시트마스크","팩"))
        if tissue and u in ("개입","개","롤") and any(n+z in t for z in ("개입","개","롤")):return True
        if sheet and u in ("개입","개","매") and any(n+z in t for z in ("개입","개","매")):return True
        return False
    missing=[x for x in critical if not critical_present(x)]
    if missing:
        return 0.0, {"critical":critical,"missing":missing,"soft":0.0}
    terms=identity_terms(target_name)
    soft=product_match(text,terms)
    return soft, {"critical":critical,"missing":[],"soft":soft}


def strict_product_accept(text, target_name, min_soft=0.62):
    """Return a hard yes/no for same-product + same-variant matching.

    Rules:
    - every model/capacity/count critical token in the target must exist
    - at least one of the first two identity terms must be present (brand/core name guard)
    - overall semantic token ratio must meet min_soft
    """
    score,detail=strict_product_match(text,target_name)
    terms=identity_terms(target_name)
    low=norm(text).lower()
    core=terms[:2]
    core_hit=(not core) or any(x.lower() in low for x in core)
    signature=signature_identity_tokens(target_name)
    signature_missing=[x for x in signature if x.lower() not in low]
    ok=(not detail.get("missing")) and core_hit and (not signature_missing) and score>=float(min_soft)
    return ok,score,{**detail,"core":core,"core_hit":core_hit,"signature":signature,
                    "signature_missing":signature_missing,"threshold":float(min_soft)}


def marketplace_product_accept(text,target_name,min_soft=0.48):
    """Balanced API-title matcher for current price lookup.

    Marketplace API titles often omit seller-tail words or one marketing line
    token. Model/capacity/count remain hard requirements, while a missing
    non-numeric signature word may be tolerated only when enough identity words
    and a leading brand/core word still agree.
    """
    strict_ok,strict_score,strict_detail=strict_product_accept(text,target_name,max(float(min_soft),0.58))
    if strict_ok:
        return True,strict_score,{**strict_detail,"match_mode":"strict"}
    score,base=strict_product_match(text,target_name)
    terms=identity_terms(target_name);low=norm(text).lower()
    hits=[x for x in terms[:8] if x.lower() in low]
    core=terms[:3];core_hits=[x for x in core if x.lower() in low]
    required=max(2,min(4,(len(terms[:8])+1)//2)) if len(terms)>=2 else 1
    ok=(not base.get("missing")) and bool(core_hits) and len(hits)>=required and score>=float(min_soft)
    detail={**strict_detail,**base,"identity_hits":hits,"identity_hit_count":len(hits),
            "required_hits":required,"core_hits":core_hits,"threshold":float(min_soft),
            "match_mode":"api_title_balanced" if ok else "rejected"}
    return ok,score,detail


def canonical_disclosure_block():
    """Return the one legally required disclosure block used by every writer."""
    return {"type":"disclosure","lines":list(COUPANG_DISCLOSURE_LINES),
            "position":"absolute_top","count_policy":"exactly_once"}


def normalize_disclosure_blocks(blocks):
    """Remove stale/duplicate disclosure text and insert one canonical top block."""
    clean=[]
    markers=("쿠팡파트너스활동의일환", "일정액의수수료를제공받습니다")
    for block in blocks or []:
        if not isinstance(block,dict):continue
        if block.get("type")=="disclosure":continue
        text=" ".join([str(block.get("text") or ""),*[str(x) for x in (block.get("lines") or [])]])
        compact=re.sub(r"\s+","",text)
        if any(marker in compact for marker in markers):continue
        clean.append(dict(block))
    return [canonical_disclosure_block(),*clean]


def disclosure_count(blocks):
    return sum(1 for b in (blocks or []) if isinstance(b,dict) and b.get("type")=="disclosure")


def verified_blog_image_set(row, required=3):
    """Validate both physical files and the v8.04 1+2 role composition."""
    from .image_identity import image_evidence_error
    physical=[]
    for key in ("image1","image2","image3")[:int(required)]:
        try:value=str(row[key] or "").strip()
        except Exception:value=""
        if value and Path(value).is_file():physical.append(value)
    try:count=int(row["image_verified_count"] or 0)
    except Exception:count=len(physical)
    try:evidence_path=str(row["image_evidence_json"] or "").strip()
    except Exception:evidence_path=""
    evidence={}
    if evidence_path and Path(evidence_path).is_file():
        try:evidence=json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        except Exception:evidence={}
    composition=evidence.get("composition") if isinstance(evidence,dict) else {}
    composition_ok=bool(isinstance(composition,dict) and composition.get("verified") and
                        int(composition.get("representative_count") or 0)==1 and
                        int(composition.get("secondary_count") or 0)>=2)
    wala=("content_type" in row.keys() and "source_platform" in row.keys() and
          row["content_type"]=="celebrity_style" and row["source_platform"]=="왈라랜드")
    identity_error="" if wala else image_evidence_error(Path(evidence_path),str(row["name"] or ""),physical)
    if len(set(str(Path(path).resolve()) for path in physical))!=len(physical):
        identity_error="같은 사진 파일이 여러 슬롯에 중복되어 있습니다."
    ok=(len(physical)>=int(required) and count>=int(required) and composition_ok and not identity_error)
    if len(physical)<int(required):reason=f"제품 이미지 실파일 {len(physical)}/{required}"
    elif count<int(required):reason=f"검증 이미지 메타데이터 {count}/{required}"
    elif not composition_ok:reason="대표 1장 + 제품 상세/갤러리 2장 구성 미검증"
    elif identity_error:reason=identity_error
    else:reason=""
    return ok,{"physical_count":len(physical),"verified_count":count,
               "composition":composition or {},"reason":reason,"evidence_path":evidence_path}


# ================= v5.5 PERFORMANCE CORE =================
import threading, hashlib
from contextlib import contextmanager

PERF_CONFIG_PATH = DATA/"performance.json"

def performance_settings():
    try:
        return json.loads(PERF_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def db_connect(row_factory=False):
    """Centralized SQLite connection optimized for concurrent read / short writes."""
    con=sqlite3.connect(DB, timeout=max(1,performance_settings().get("sqlite_busy_timeout_ms",5000)/1000))
    if row_factory:
        con.row_factory=sqlite3.Row
    try:
        if performance_settings().get("sqlite_wal",True):
            con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute(f"PRAGMA busy_timeout={int(performance_settings().get('sqlite_busy_timeout_ms',5000))}")
        con.execute("PRAGMA temp_store=MEMORY")
        con.execute("PRAGMA cache_size=-32000")
    except Exception:
        pass
    return con

class StageTimer:
    def __init__(self, name, extra=""):
        self.name=name; self.extra=extra; self.t0=None
    def __enter__(self):
        self.t0=time.perf_counter()
        log(f"[PERF][START] {self.name} {self.extra}".strip())
        return self
    def __exit__(self, exc_type, exc, tb):
        sec=time.perf_counter()-self.t0
        status="FAIL" if exc else "OK"
        log(f"[PERF][{status}] {self.name}: {sec:.2f}s {self.extra}".strip())
        return False

class ProgressThrottle:
    def __init__(self, callback, min_interval=None):
        self.callback=callback
        self.min_interval=min_interval if min_interval is not None else performance_settings().get("log_progress_min_interval_sec",0.35)
        self.last=0.0
        self.lock=threading.Lock()
    def __call__(self, done,total,msg,force=False):
        if not self.callback:return
        now=time.monotonic()
        with self.lock:
            if force or done>=total or now-self.last>=self.min_interval:
                self.last=now
                self.callback(done,total,msg)

_CACHE_LOCK=threading.Lock()
_RUNTIME_CACHE={}

def cache_get(key, ttl=None):
    ttl=ttl if ttl is not None else performance_settings().get("search_result_cache_ttl_sec",900)
    now=time.time()
    with _CACHE_LOCK:
        item=_RUNTIME_CACHE.get(key)
        if not item:return None
        ts,val=item
        if now-ts>ttl:
            _RUNTIME_CACHE.pop(key,None);return None
        return val

def cache_set(key,val):
    with _CACHE_LOCK:
        _RUNTIME_CACHE[key]=(time.time(),val)

def cache_key(*parts):
    raw="||".join(str(x) for x in parts)
    return hashlib.sha1(raw.encode("utf-8","ignore")).hexdigest()

def init_db_fast():
    init_db()
    con=db_connect()
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_products_no ON products(product_no)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_products_status ON products(status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_candidates_platform_cat ON candidates(platform,category)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_candidates_name ON candidates(name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_affiliate_cache_used ON affiliate_link_cache(last_used_at)")
        con.commit()
    finally:
        con.close()
