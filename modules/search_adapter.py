# -*- coding: utf-8 -*-
from pathlib import Path
from collections.abc import Callable
from urllib.parse import quote
import time,re,json,sqlite3,os,tempfile,shutil,csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from .common import *
from .performance_adapter import get_weights
from . import coupang_safe
from . import market_safe
from . import toss_sharelink_pc
from . import chrome_collector
from . import toss_multi_frame_collector
from . import toss_sharelink_api
from .published_product_registry import filter_published_candidates, registry_summary
from .collection_preferences import CollectionPreferences, load_preferences, apply_preferences
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except Exception:
    webdriver=None

SITES={
 "쿠팡":lambda q:f"https://www.coupang.com/np/search?q={quote(q)}",
 "네이버쇼핑":lambda q:f"https://search.shopping.naver.com/search/all?query={quote(q)}"
}
# 토스쇼핑은 공식 소비자 쇼핑 경험이 토스 앱 중심이므로 PC URL을 임의 추정하지 않습니다.
MOBILE_ONLY_PLATFORMS={"토스쇼핑"}
PRICE=re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원")

def health():
    cfg=settings()
    if cfg.get("collection_mode","chrome_extension")=="chrome_extension":
        h=chrome_collector.health()
        toss_api=bool(cfg.get("toss_discovery_api_enabled",True) and toss_sharelink_api.ready())
        toss_ok=toss_api or webdriver is not None
        mode="토스 Sharelink API(홈페이지 미사용)" if toss_api else "토스 Selenium 보완"
        return {"ready":toss_ok,"name":"상품 검색",
                "message":(f"쿠팡/네이버 일반 Chrome + {mode} · API 0건은 Selenium 자동복구 · 부분수집도 확보분으로 Top100 생성 / "+h.get("message","") if toss_ok else "토스 API 키 또는 Selenium이 필요합니다.")}
    return {"ready":webdriver is not None,"name":"상품 검색","message":"Selenium 준비됨" if webdriver else "selenium 미설치"}

def driver_start(fast_discovery=False, isolated=False, profile_key=None):
    perf=performance_settings()
    opt=webdriver.ChromeOptions()
    if profile_key:
        profile=ROOT/"data"/"browser_profiles"/re.sub(r"[^0-9A-Za-z가-힣_-]","_",profile_key)
        profile.mkdir(parents=True,exist_ok=True)
    elif isolated:
        profile=ROOT/"data"/"browser_workers"/("discovery_"+str(threading.get_ident()))
        profile.mkdir(parents=True,exist_ok=True)
    else:
        profile=Path(os.environ.get("LOCALAPPDATA",str(ROOT)))/settings().get("chrome_profile","NaverBlogAutomationProfile")
    opt.add_argument(f"--user-data-dir={profile}")
    opt.add_argument("--no-first-run");opt.add_argument("--no-default-browser-check")
    opt.add_argument("--disable-notifications");opt.add_argument("--disable-popup-blocking")
    opt.page_load_strategy=perf.get("browser_page_load_strategy","eager")
    # In safe_market_mode images remain enabled because missing images/odd loading can increase false failures.
    if fast_discovery and perf.get("disable_images_for_discovery_only",False):
        opt.add_experimental_option("prefs",{"profile.managed_default_content_settings.images":2})
    d=webdriver.Chrome(options=opt)
    d.set_page_load_timeout(int(perf.get("search_page_timeout_sec",12)))
    return d

def wait_results(driver, timeout=None):
    timeout=timeout or performance_settings().get("dom_ready_timeout_sec",6)
    try:
        WebDriverWait(driver,timeout,poll_frequency=performance_settings().get("poll_interval_sec",0.15)).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR,"li, article, div[class*='product'], div[class*='item'], div[class*='basicList']"))>0
        )
    except Exception:
        pass

def extract_cards(driver,limit=10,platform=None):
    result=[];seen=set()
    if platform=="쿠팡":
        selectors=["li.search-product","li[class*='search-product']","article","div[class*='product']"]
    elif platform=="네이버쇼핑":
        selectors=["div[class*='product_item']","li[class*='basicList_item']","div[class*='basicList_item']",
                   "div[class*='product']","article","li"]
    else:
        selectors=["article","li","div[class*='product']","div[class*='item']","div[class*='basicList']"]
    for sel in selectors:
        try:els=driver.find_elements(By.CSS_SELECTOR,sel)
        except:continue
        for e in els:
            try:
                if not e.is_displayed():continue
                txt=norm(e.text)
                if len(txt)<10 or len(txt)>1600:continue
                pm=PRICE.search(txt)
                if not pm:continue
                price=int(pm.group(1).replace(",",""))
                if not 100<=price<=100000000:continue
                url="";img=""
                try:
                    a=e.find_element(By.CSS_SELECTOR,"a[href]");url=a.get_attribute("href") or ""
                except:pass
                try:
                    im=e.find_element(By.CSS_SELECTOR,"img");img=im.get_attribute("src") or im.get_attribute("data-src") or ""
                except:pass
                lines=[x.strip() for x in (e.text or "").splitlines() if x.strip()]
                candidates=[x for x in lines[:10] if not PRICE.fullmatch(x) and len(x)>=3]
                name=max(candidates,key=len) if candidates else txt[:140]
                key=(name,price)
                if key in seen:continue
                seen.add(key)
                result.append({"name":name,"price":price,"url":url,"image_url":img,"text":txt,"element":e})
                if len(result)>=limit:return result
            except:pass
    return result

def _platform_driver(platform):
    return driver_start(fast_discovery=False,isolated=False,profile_key=platform)

def _search_one(driver,platform,query,limit):
    if platform=="토스쇼핑":
        cards=toss_sharelink_pc.search_cards(driver,query,limit)
        return [{"name":c["name"],"price":c["price"],"url":c.get("url",""),"image_url":"",
                 "text":c["text"]} for c in cards]
    market_safe.search(driver,platform,query)
    return [{k:v for k,v in c.items() if k!="element"} for c in extract_cards(driver,limit,platform)]

def _discover_selenium(progress=None):
    """
    v6.8: Query-by-query sequential discovery.
    The old v6.7 UI appeared frozen because progress only updated after an entire
    marketplace finished all 15 searches. Now every query updates the GUI.
    """
    cfg=settings();init_db_fast()
    platforms=[p for p in ["네이버쇼핑","토스쇼핑","쿠팡"] if p in cfg.get("platforms",[])]
    tasks=[(p,cat,cat) for p in platforms for cat in cfg["categories"]]
    total=len(tasks);done=0;rows=[];errors=[]
    prog=ProgressThrottle(progress,min_interval=0)

    drivers={}
    try:
        with StageTimer("3사 상품 통합검색",f"queries={total}"):
            for platform in platforms:
                try:
                    drivers[platform]=_platform_driver(platform)
                except Exception as e:
                    errors.append(f"{platform} Chrome 시작 실패: {e}")
                    # count all platform tasks as skipped while showing progress
                    count=sum(1 for p,_,_ in tasks if p==platform)
                    for _ in range(count):
                        done+=1;prog(done,total,f"{platform} Chrome 시작 실패",force=True)
                    continue

                for cat in cfg["categories"]:
                    q=cat
                    prog(done,total,f"{platform} · {cat} 카테고리 수집 중",force=True)
                    ck=cache_key("discover-v79-category-only",platform,cat)
                    cards=cache_get(ck)
                    if cards is None:
                        try:
                            cards=_search_one(
                                drivers[platform],platform,q,
                                cfg.get("top_per_platform_category",30)
                            )
                            cache_set(ck,cards)
                            if platform in ("쿠팡","네이버쇼핑") and cards:
                                market_safe.reset(platform)
                        except Exception as e:
                            cards=[]
                            errors.append(f"{platform}/{cat}: {e}")
                            log(f"[DISCOVERY] {platform}/{cat} 실패: {e}")

                    accepted=0
                    for c in cards:
                        name=clean_product_name(c.get("name",""))
                        if not is_valid_product_name(name):
                            continue
                        if not _category_compatible(name,cat):
                            continue
                        accepted+=1
                        item=dict(c)
                        item["name"]=name
                        item.update(
                            platform=platform,
                            category=cat,
                            query=cat,
                            rank_no=accepted
                        )
                        rows.append(item)
                        if accepted>=cfg.get("top_per_platform_category",30):
                            break

                    done+=1
                    prog(
                        done,total,
                        f"{platform} · {cat} 카테고리 {accepted}개",
                        force=True
                    )

            # Deduplicate raw candidates before DB write.
            dedup=[];seen=set()
            for c in rows:
                key=(c["platform"],re.sub(r"[^가-힣A-Za-z0-9]","",c["name"]).lower()[:80],c["price"])
                if key in seen:continue
                seen.add(key);dedup.append(c)
            rows=dedup

            con=db_connect()
            try:
                con.execute("DELETE FROM candidates")
                con.executemany("""INSERT INTO candidates(platform,category,query,name,price,url,image_url,rank_no,captured_at)
                                  VALUES(?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                    [(c["platform"],c["category"],c["query"],c["name"],c["price"],c.get("url",""),c.get("image_url",""),c["rank_no"]) for c in rows])
                con.commit()

                allr=con.execute("SELECT platform,category,name,price,url,rank_no FROM candidates").fetchall()
                groups={}
                for platform,cat,name,price,url,rank in allr:
                    key=" ".join(identity_terms(name)[:5]).lower() or name.lower()[:50]
                    g=groups.setdefault(key,{"names":[],"platforms":set(),"category":cat,"score":0,"url":url})
                    g["names"].append(name);g["platforms"].add(platform);g["score"]+=max(1,11-(rank or 10))
                weights=get_weights(cfg["categories"])
                for g in groups.values():
                    g["weighted_score"]=(len(g["platforms"])*30+g["score"])*weights.get(g["category"],1.0)
                ranked=sorted(groups.values(),key=lambda g:g["weighted_score"],reverse=True)[:cfg.get("final_top_products",30)]

                if not ranked:
                    errfile=ROOT/"logs"/"search_failures_v68.txt"
                    errfile.write_text("\n".join(errors[-100:]) or "검색 결과 0개",encoding="utf-8")
                    raise RuntimeError("3사 상품검색 결과가 0개입니다. logs/search_failures_v68.txt와 실행 로그를 확인하세요.")

                con.execute("DELETE FROM products WHERE status='검색선정'")
                payload=[]
                for i,g in enumerate(ranked,1):
                    name=max(g["names"],key=len)
                    payload.append((i,name,g["category"],json.dumps(identity_terms(name),ensure_ascii=False),
                                    ",".join(sorted(g["platforms"])),g["url"],g["weighted_score"]))
                con.executemany("""INSERT INTO products(product_no,name,category,product_identity,source_platform,source_url,score,status,updated_at)
                                   VALUES(?,?,?,?,?,?,?,'검색선정',datetime('now','localtime'))""",payload)
                con.commit()
            finally:
                con.close()

        prog(total,total,f"검색 후보 {len(rows)}개 / 최종 {len(ranked)}개",force=True)
        return {"candidates":len(rows),"selected":len(ranked),"errors":errors[-20:]}
    finally:
        for d in drivers.values():
            try:d.quit()
            except:pass




_PROMO_ONLY_RE = re.compile(
    r"^(?:쿠폰\s*할인가|쿠폰할인가|할인가|즉시할인|카드할인|회원할인|혜택|적립|"
    r"무료\s*배송|무료배송|로켓배송|판매자로켓|광고|판매처\s*\d*|"
    r"오늘.*(?:배송|도착|휴무)|내일.*(?:배송|도착)|모레.*(?:배송|도착))$",
    re.I
)

def clean_product_name(name):
    s=clean_listing_title_noise(name)
    s=re.sub(r"^\[(?:쿠폰|농협쿠폰|할인|특가|이벤트|프로모션|즉시할인|카드할인)[^\]]*\]\s*","",s,flags=re.I)
    s=re.sub(r"\s+(?:쿠폰할인가|즉시할인|카드할인|무료배송|로켓배송|오늘\s*도착|내일\s*도착|배송\s*휴무).*$","",s,flags=re.I)
    return s.strip()

def is_valid_product_name(name):
    s=clean_product_name(name)
    if len(s)<4:return False
    if _PROMO_ONLY_RE.match(s):return False
    if re.fullmatch(r"\d+\s*%\s*(?:특가|할인)?",s,re.I):return False
    if re.fullmatch(r"(?:리뷰|후기|평점)\s*[\d,.()개]*",s,re.I):return False
    if not re.search(r"[A-Za-z가-힣]",s):return False
    return True

def _site_category_map(cfg):
    return cfg.get("site_category_map") or {}


_TOSS_CATEGORY_WORDS={
 "생활용품":("생활","리빙","홈리빙","홈데코","화장지","휴지","물티슈","세제","세탁","청소","욕실","수납","마스크","생리대","치약","칫솔","탈취","방향제"),
 "주방용품":("주방","냄비","프라이팬","팬","도마","식기","그릇","수저","텀블러","보관용기","밀폐용기","랩","호일","키친타월","칼","컵"),
 "패션잡화":("패션","의류","티셔츠","셔츠","원피스","바지","팬츠","가방","신발","운동화","샌들","양말","모자","지갑","벨트","주얼리"),
 "식품":("식품","음료","생수","과자","라면","쌀","고기","과일","커피","차","우유","주스","간식","영양제","비타민","건강식"),
 "디지털/가전":("디지털","가전","전자","이어폰","헤드폰","충전","케이블","스마트폰","노트북","키보드","마우스","모니터","청소기","선풍기","에어컨","배터리"),
 "화장품/미용":("뷰티","화장품","미용","크림","세럼","에센스","로션","스킨","클렌징","선크림","쿠션","립","마스크팩","샴푸","트리트먼트","헤어","향수")
}

def _toss_category_words(cat,cfg=None):
    words=list(_TOSS_CATEGORY_WORDS.get(cat,()))+[cat]
    mapping=((cfg or {}).get("site_category_map") or {}).get("토스쇼핑",{}).get(cat,{})
    words.extend([mapping.get("site_category") or "",*(mapping.get("aliases") or [])])
    out=[]
    for word in words:
        word=norm(word).lower().replace("·","/")
        if word and word not in out:out.append(word)
    return tuple(out)

def _toss_category_score(text,cat,cfg=None):
    low=norm(text).lower().replace("·","/");words=_toss_category_words(cat,cfg)
    return sum(3 if low.startswith(w.lower()) else 1 for w in words if w.lower() in low)

def _toss_category_from_text(text,categories,cfg=None):
    scored=[(_toss_category_score(text,c,cfg),c) for c in categories]
    scored.sort(reverse=True)
    return scored[0][1] if scored and scored[0][0]>0 else ""

def _collect_toss_api_results(toss_tasks,cfg,progress=None):
    """Collect Toss discovery rows without opening Sharelink web UI.

    Official best-selling is used once, then best-categories feeds are called
    only for buckets that still need products. Category IDs come from the API
    category tree when available and from categoryIds carried by global rows.
    """
    if not toss_tasks:return []
    limit=int(toss_tasks[0].get("limit") or cfg.get("top_per_platform_category",30))
    categories=[t.get("blog_category") for t in toss_tasks]
    buckets={c:[] for c in categories};seen={c:set() for c in categories};errors=[]
    cat_ids={c:[] for c in categories};id_labels={};api_ok=False;global_ok=False
    category_api_ok={c:False for c in categories}
    tried_ids={c:[] for c in categories};category_errors={c:[] for c in categories}
    def add(cat,row,source):
        if cat not in buckets or len(buckets[cat])>=limit:return
        name=clean_product_name(row.get("name") or "")
        if not is_valid_product_name(name):return
        key=str(row.get("product_id") or re.sub(r"[^가-힣A-Za-z0-9]","",name).lower()[:160])
        if not key or key in seen[cat]:return
        seen[cat].add(key);buckets[cat].append({"name":name,"price":row.get("price"),"url":row.get("url") or "",
          "image_url":row.get("image_url") or "","text":name,"source":source,"product_id":row.get("product_id") or ""})
    try:
        try:
            nodes=toss_sharelink_api.get_categories(False);api_ok=True
            ranked_ids={c:[] for c in categories}
            for node in nodes:
                cid=str(node.get("category_id") or "");label=(node.get("path") or "")+" "+(node.get("name") or "")
                cat=_toss_category_from_text(label,categories,cfg)
                if cid and cat:
                    id_labels[cid]=cat
                    try:level=int(node.get("level") or max(1,str(node.get("path") or "").count("/")+1))
                    except Exception:level=9
                    score=_toss_category_score(label,cat,cfg)
                    ranked_ids[cat].append((level,-score,len(label),cid))
            # v7.54: category-tree IDs are the authoritative input for the
            # official best-categories endpoint.  v7.53 accidentally waited
            # for an ID to reappear in the global feed, which left buckets
            # empty and surfaced status=partial despite a healthy API.
            for cat in categories:
                for _,_,_,cid in sorted(ranked_ids[cat]):
                    if cid not in cat_ids[cat]:cat_ids[cat].append(cid)
        except Exception as e:errors.append("category tree: "+str(e))
        try:
            global_rows=toss_sharelink_api.best_selling(int(cfg.get("toss_discovery_api_global_size",500)))
            api_ok=True;global_ok=True
        except Exception as e:
            # Global best and category best are independent official feeds.
            # A global-feed failure must not prevent category-tree collection.
            global_rows=[];errors.append("global best-selling: "+str(e))
        for row in global_rows:
            assigned=""
            for cid in reversed(row.get("category_ids") or []):
                if str(cid) in id_labels:assigned=id_labels[str(cid)];break
            if not assigned:assigned=_toss_category_from_text(row.get("name") or "",categories,cfg)
            if assigned:
                add(assigned,row,"toss_sharelink_best_selling_api")
                for cid in reversed(row.get("category_ids") or []):
                    cid=str(cid)
                    if cid and cid not in cat_ids[assigned]:cat_ids[assigned].insert(0,cid)
        # Explicit IDs are optional. They are classified by category-tree label
        # or by the returned product titles, never by list position.
        for cid in toss_sharelink_api.credentials().get("category_ids") or []:
            cid=str(cid);cat=id_labels.get(cid)
            if cat and cid not in cat_ids[cat]:cat_ids[cat].append(cid)
        probe=max(1,int(cfg.get("toss_discovery_api_category_probe_per_blog_category",12)))
        feed_size=max(limit,min(100,int(cfg.get("toss_discovery_api_category_feed_size",100))))
        for ci,cat in enumerate(categories,1):
            for cid in cat_ids[cat][:probe]:
                if len(buckets[cat])>=limit:break
                tried_ids[cat].append(cid)
                try:
                    feed=toss_sharelink_api.best_categories(cid,feed_size);api_ok=True;category_api_ok[cat]=True
                    for row in feed:add(cat,row,"toss_sharelink_best_categories_api")
                except Exception as e:
                    msg=f"{cat}/{cid}: {e}";errors.append(msg);category_errors[cat].append(msg)
            if progress:progress(ci,len(categories),f"토스 API · {cat} {len(buckets[cat])}/{limit}")
    except Exception as e:
        errors.append(str(e))
    results=[]
    for task in toss_tasks:
        cat=task.get("blog_category") or "";cards=buckets.get(cat,[])[:limit];complete=len(cards)>=limit
        cat_ok=bool(category_api_ok.get(cat) or cards)
        # A short category feed is a valid API response, not a transport/error
        # status. Keep shortage as coverage metadata so the collected products
        # remain usable for Top100 instead of showing a misleading partial error.
        results.append({"_task_id":task.get("id"),"_site":"토스쇼핑","status":"ok" if cat_ok else "error",
          "cards":cards,"url":"api://sharelink/products","clicked_label":"API:"+cat,
          "category_confirmed":bool(cat_ids.get(cat) or cards),"ranking_anchor_confirmed":True,"toss_collection_mode":"api",
          "toss_api_confirmed":cat_ok,"toss_product_lookup_confirmed":True,"toss_single_checkbox_confirmed":True,
          "toss_uncheck_after_collect":True,"toss_filter_cleanup_confirmed":True,
          "toss_checked_before_collect":[],"toss_checked_after_collect":[],
          "collection_complete":complete,"detail":f"Sharelink API {len(cards)}/{limit}",
          "error":"" if complete else f"API 정상응답 · 확보 {len(cards)}/{limit}",
          "debug":{"engine":"toss_sharelink_api_category_tree_v7_54","global_count":sum(len(v) for v in buckets.values()),
                   "global_api_ok":global_ok,"category_api_ok":bool(category_api_ok.get(cat)),
                   "category_ids_found":len(cat_ids.get(cat) or []),"category_ids_tried":tried_ids.get(cat) or [],
                   "category_errors":category_errors.get(cat) or [],"errors":errors[-20:]}})
    return results


def _build_extension_discovery_rows(cfg,progress=None):
    """
    v7.14 STRICT 540 MODE

    3 marketplaces x 6 user categories x 30 ranked products = 540 raw slots.
    Every task must confirm the marketplace-specific category before collection.
    Coupang additionally requires the visible "쿠팡 랭킹순" anchor and only
    cards below that anchor are accepted by the extension. Toss uses the user-
    specified 링크 > 상품 조회 flow and exactly one checked category at a time;
    the extension must uncheck it after collecting 30 before the next task.
    """
    platforms=[p for p in ["쿠팡","네이버쇼핑","토스쇼핑"] if p in cfg.get("platforms",[])]
    categories=list(load_preferences(cfg).market_categories)
    limit=int(cfg.get("top_per_platform_category",30))
    delay_ms=int(float(cfg.get("chrome_task_delay_sec",5.0))*1000)
    mapping=_site_category_map(cfg)
    def safe_task_url(platform,value):
        value=str(value or "").strip()
        if platform=="쿠팡" and value.lower().startswith("http://"):
            value="https://"+value[7:]
        return value
    tasks=[];meta={};plan=[]
    for p in platforms:
        platform_categories=(cfg.get("toss_category_order") or categories) if p=="토스쇼핑" else categories
        # Keep the user-specified Toss checkbox order while preserving the same
        # six canonical blog categories for coverage/scoring.
        platform_categories=[c for c in platform_categories if c in categories]
        for ci,cat in enumerate(platform_categories,1):
            m=(mapping.get(p) or {}).get(cat) or {}
            site_cat=m.get("site_category") or cat
            tid=f"fixed-{p}-{ci:02d}"
            task={
                "id":tid,"site":p,"query":cat,"mode":"fixed_category_collect",
                "blog_category":cat,"site_category_label":site_cat,
                "parent_category_label":m.get("parent_category","") or "",
                "category_aliases":m.get("aliases") or [site_cat],
                "entry_url":safe_task_url(p,m.get("entry_url","") or ""),
                "fallback_url":safe_task_url(p,m.get("fallback_url","") or ""),
                "parent_fallback_url":safe_task_url(p,m.get("parent_fallback_url","") or ""),
                "click_path":m.get("click_path") or [],
                "ranking_anchor":m.get("ranking_anchor","") or "",
                "capture":True,
                "evdir":str(ROOT/"evidence"/"collection_540"/p/re.sub(r"[^0-9A-Za-z가-힣_-]","_",cat)),
                "limit":limit,"delay_ms":delay_ms
            }
            tasks.append(task);meta[tid]=(p,cat,site_cat,m)
            plan.append({
                "site":p,"blog_category":cat,"site_category":site_cat,
                "parent_category":m.get("parent_category","") or "",
                "click_path":m.get("click_path") or [],"entry_url":safe_task_url(p,m.get("entry_url","") or ""),
                "fallback_url":safe_task_url(p,m.get("fallback_url","") or ""),
                "parent_fallback_url":safe_task_url(p,m.get("parent_fallback_url","") or ""),
                "ranking_anchor":m.get("ranking_anchor","") or ""
            })

    outdir=ROOT/"outputs";outdir.mkdir(parents=True,exist_ok=True)
    (outdir/"site_category_click_plan.json").write_text(json.dumps({
        "mode":"PARTIAL_TOP100_TOSS_API_FIRST_V7_53","tasks":plan,
        "target_per_site_category":limit,"raw_target":len(tasks)*limit
    },ensure_ascii=False,indent=2),encoding="utf-8")

    # v7.54: Toss Sharelink API is the default discovery engine. It does not
    # open the Sharelink homepage. Selenium is retained only as an explicit
    # fallback for categories the API could not fill.
    extension_tasks=[t for t in tasks if t.get("site")!="토스쇼핑"]
    toss_tasks=[t for t in tasks if t.get("site")=="토스쇼핑"]
    results=[]
    if extension_tasks:
        def _ext_progress(done,total,msg):
            if progress:progress(done,len(tasks),msg)
        results.extend(chrome_collector.collect(
            extension_tasks,progress=_ext_progress,
            timeout_sec=max(1800,len(extension_tasks)*120)
        ))
    toss_api_mode=bool(cfg.get("toss_discovery_api_enabled",True) and toss_sharelink_api.ready())
    toss_api_health=toss_sharelink_api.health()
    if toss_tasks and toss_api_mode:
        base=len(extension_tasks)
        def _toss_progress(done,total,msg):
            if progress:progress(base+done,len(tasks),msg)
        api_results=_collect_toss_api_results(toss_tasks,cfg,progress=_toss_progress)
        results.extend(api_results)
        # v7.56 recovery: a configured key can still be expired, unauthorized,
        # IP-restricted or pointed at a temporarily failing endpoint.  v7.55
        # treated ready()==True as success and, with web fallback disabled,
        # returned six empty Toss buckets.  Automatically recover only tasks
        # whose API path produced no usable card; the optional setting can still
        # request web supplementation for short-but-valid feeds.
        api_failed_ids={x.get("_task_id") for x in api_results if x.get("status")!="ok" or not (x.get("cards") or [])}
        supplement_ids={x.get("_task_id") for x in api_results if len(x.get("cards") or [])<limit}
        incomplete_ids=(supplement_ids if cfg.get("toss_discovery_web_fallback_enabled",False) else
                        (api_failed_ids if cfg.get("toss_discovery_auto_recover_on_api_failure",True) else set()))
        if incomplete_ids:
            web_tasks=[t for t in toss_tasks if t.get("id") in incomplete_ids]
            if web_tasks:
                web=toss_multi_frame_collector.collect_tasks(web_tasks,progress=_toss_progress)
                byid={x.get("_task_id"):x for x in results}
                for wr in web:
                    old=byid.get(wr.get("_task_id")) or {};merged=[];seen_names=set()
                    for card in [*(old.get("cards") or []),*(wr.get("cards") or [])]:
                        k=re.sub(r"[^가-힣A-Za-z0-9]","",str(card.get("name") or "")).lower()[:160]
                        if k and k not in seen_names:seen_names.add(k);merged.append(card)
                        if len(merged)>=limit:break
                    combined=dict(wr if (wr.get("status")=="ok" or wr.get("cards")) else old)
                    combined["cards"]=merged
                    combined["toss_collection_mode"]="api_then_web_fallback" if merged else "api_then_web_failed"
                    combined["api_error_before_fallback"]=old.get("error") or ""
                    combined["web_fallback_error"]="" if merged else (wr.get("error") or wr.get("status") or "응답 없음")
                    combined["debug"]={"api":old.get("debug") or {},"web":wr.get("debug") or {},"auto_recovery":True}
                    combined["status"]="ok" if merged else "error"
                    byid[wr.get("_task_id")]=combined
                results=[byid.get(x.get("_task_id"),x) for x in results]
    elif toss_tasks:
        base=len(extension_tasks)
        def _toss_progress(done,total,msg):
            if progress:progress(base+done,len(tasks),msg)
        results.extend(toss_multi_frame_collector.collect_tasks(toss_tasks,progress=_toss_progress))
    (outdir/"live_collection_results.json").write_text(
        json.dumps({"mode":"v7.56_toss_api_with_failure_recovery" if toss_api_mode else "toss_selenium_fallback",
                    "toss_api_health":toss_api_health,"tasks":plan,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
    rows=[];errors=[];coverage={}
    for r in results:
        tid=r.get("_task_id")
        p,cat,site_cat,m=meta.get(tid,(r.get("_site"),"","",{}))
        key=f"{p}|{cat}"
        status=r.get("status") or "error"
        if status!="ok":
            errors.append(f"{p}/{cat}({site_cat}): {status} {r.get('error','')}")
        # Even a failed/partial browser task may have valid cards. Preserve them
        # so the per-site 180 tabs show exactly what was actually found.
        picked=[];seen=set()
        for c in r.get("cards") or []:
            name=clean_product_name(c.get("name",""))
            if not is_valid_product_name(name):continue
            k=re.sub(r"[^가-힣A-Za-z0-9]","",name).lower()[:140]
            if not k or k in seen:continue
            seen.add(k)
            picked.append({
                "platform":p,"category":cat,"site_category":site_cat,
                "query":"","name":name,"price":c.get("price"),
                "url":c.get("url","") or "","image_url":c.get("image_url","") or "",
                "rank_no":len(picked)+1,"text":c.get("text","") or "",
                "clicked_label":r.get("clicked_label","") or "",
                "page_url":r.get("url","") or "",
                "ranking_anchor_confirmed":bool(r.get("ranking_anchor_confirmed",p!="쿠팡"))
            })
            if len(picked)>=limit:break
        rows.extend(picked)
        coverage[key]={
            "count":len(picked),"target":limit,"site_category":site_cat,
            "clicked_label":r.get("clicked_label","") or "",
            "page_url":r.get("url","") or "",
            "category_confirmed":bool(r.get("category_confirmed",True)),
            "ranking_anchor_confirmed":bool(r.get("ranking_anchor_confirmed",p!="쿠팡")),
            "toss_product_lookup_confirmed":bool(r.get("toss_product_lookup_confirmed",p!="토스쇼핑")),
            "toss_single_checkbox_confirmed":bool(r.get("toss_single_checkbox_confirmed",p!="토스쇼핑")),
            "toss_uncheck_after_collect":bool(r.get("toss_uncheck_after_collect",p!="토스쇼핑")),
            "toss_filter_cleanup_confirmed":bool(r.get("toss_filter_cleanup_confirmed",r.get("toss_uncheck_after_collect",p!="토스쇼핑"))),
            "toss_cleanup_method":r.get("toss_cleanup_method","") or "",
            "toss_collection_mode":r.get("toss_collection_mode","") or "web",
            "toss_api_confirmed":bool(r.get("toss_api_confirmed",False)),
            "toss_checked_before_collect":r.get("toss_checked_before_collect") or [],
            "toss_checked_after_collect":r.get("toss_checked_after_collect") or [],
            "status":status,
            "reason_code":r.get("reason_code","") or "",
            "resume_required":bool(r.get("resume_required",False) or r.get("resume_required_categories")),
            "resume_required_categories":r.get("resume_required_categories") or [],
            "full_screenshot":r.get("full_screenshot","") or "",
            "debug":r.get("debug") or {},
            "route_attempts":r.get("route_attempts"),
            "route_detail":r.get("detail","") or "",
            "error":r.get("error","") or ("" if len(picked)>=limit else f"{limit}개 중 {len(picked)}개만 수집")
        }
        if len(picked)<limit:
            errors.append(f"{p}/{cat}: {limit}개 목표 중 {len(picked)}개")

    coverage_payload={
        "raw_target":len(tasks)*limit,"raw_actual":len(rows),
        "per_site_target":len(categories)*limit,"per_site_category_target":limit,
        "coverage":coverage,"errors":errors
    }
    (outdir/"strict540_category_coverage.json").write_text(
        json.dumps(coverage_payload,ensure_ascii=False,indent=2),encoding="utf-8")
    toss_diag=[]
    for cat in categories:
        row=coverage.get(f"토스쇼핑|{cat}") or {}
        toss_diag.append({"category":cat,"count":row.get("count",0),"target":limit,"status":row.get("status") or "error",
                          "mode":row.get("toss_collection_mode") or ("api" if toss_api_mode else "selenium"),
                          "reason":row.get("error") or row.get("route_detail") or "","debug":row.get("debug") or {}})
    (outdir/"toss_collection_diagnostic.json").write_text(json.dumps({
        "version":"7.56","api_ready":bool(toss_api_health.get("ready")),"api_message":toss_api_health.get("message") or "",
        "auto_recover_on_api_failure":bool(cfg.get("toss_discovery_auto_recover_on_api_failure",True)),
        "categories":toss_diag},ensure_ascii=False,indent=2),encoding="utf-8")

    # Save exactly what each source supplied so the GUI and manual audit can show it.
    for p,fn in [("쿠팡","coupang_collected_180.json"),("토스쇼핑","toss_collected_180.json"),("네이버쇼핑","naver_collected_180.json")]:
        arr=[x for x in rows if x["platform"]==p]
        (outdir/fn).write_text(json.dumps({"site":p,"target":len(categories)*limit,"actual":len(arr),"products":arr},
                                             ensure_ascii=False,indent=2),encoding="utf-8")
    coupang_rows=[x for x in rows if x.get("platform")=="쿠팡"]
    blocked_categories=[];resume_categories=[]
    for cat in categories:
        item=coverage.get(f"쿠팡|{cat}") or {}
        if item.get("status") in ("blocked","skipped_blocked") or str(item.get("reason_code") or "").startswith("COUPANG_ACCESS_DENIED"):
            blocked_categories.append(cat)
        if item.get("resume_required") or item.get("status")=="skipped_blocked":resume_categories.append(cat)
    (outdir/"coupang_collection_diagnostic.json").write_text(json.dumps({
        "policy":"COUPANG_HTTPS_BATCH_STOP_V7_68","https_only":True,
        "access_denied_detected":bool(blocked_categories),"blocked_categories":blocked_categories,
        "resume_required_categories":resume_categories,"preserved_coupang_products":len(coupang_rows),
        "naver_products_continued":sum(1 for x in rows if x.get("platform")=="네이버쇼핑"),
        "toss_products_continued":sum(1 for x in rows if x.get("platform")=="토스쇼핑"),
        "message":"첫 Access Denied 이후 남은 쿠팡 웹 작업만 중단하며, 기존 쿠팡 결과와 네이버·토스 결과는 보존합니다."
    },ensure_ascii=False,indent=2),encoding="utf-8")
    return rows,errors,coverage


def _group_key(name):
    ident=identity_terms(name)
    return " ".join(ident[:7]).lower() or re.sub(r"[^가-힣A-Za-z0-9]","",name).lower()[:100]


def discover(progress=None,preferences: CollectionPreferences | None = None,stop_check: Callable[[], bool] | None = None):
    cfg=settings()
    cfg.update(apply_preferences(cfg,load_preferences(cfg) if preferences is None else preferences))
    if stop_check and stop_check():return {"stage_ok":False,"stopped":True,"message":"상품 수집 중지"}
    if cfg.get("collection_mode","chrome_extension")!="chrome_extension":
        raise RuntimeError("인기상품 수집은 쿠팡/네이버 일반 Chrome + 토스 Sharelink API 모드를 사용합니다.")
    init_db_fast()
    rows,errors,coverage=_build_extension_discovery_rows(cfg,progress)
    if stop_check and stop_check():return {"stage_ok":False,"stopped":True,"message":"상품 수집 중지: 기존 결과 보존"}

    # Dedup only inside the same marketplace/category. We intentionally keep the
    # same product if it appears on another marketplace because that is a strong
    # popularity-consensus signal for Top100 scoring.
    dedup=[];seen=set()
    for c in rows:
        key=(c["platform"],c["category"],re.sub(r"[^가-힣A-Za-z0-9]","",c["name"]).lower()[:140])
        if key in seen:continue
        seen.add(key);dedup.append(c)
    rows=dedup
    fresh_collected_rows=list(rows);preserved_previous=[]
    # v8.04: merge a short/failed category with its last stored snapshot. Fresh
    # cards always win; only missing, non-duplicate ranks are filled from the DB.
    prior_con=db_connect(row_factory=True)
    try:prior_rows=[dict(x) for x in prior_con.execute("SELECT * FROM candidates ORDER BY platform,category,rank_no,id").fetchall()]
    finally:prior_con.close()
    categories=list(cfg.get("categories") or [])
    platforms=[p for p in ["쿠팡","네이버쇼핑","토스쇼핑"] if p in cfg.get("platforms",[])]
    limit=int(cfg.get("top_per_platform_category",30))
    effective=[]
    for platform in platforms:
        for category in categories:
            current=[dict(x) for x in fresh_collected_rows if x["platform"]==platform and x["category"]==category]
            current.sort(key=lambda x:int(x.get("rank_no") or 999))
            old=[dict(x) for x in prior_rows if x.get("platform")==platform and x.get("category")==category]
            merged=[];scope_seen=set()
            for item in current:
                key=re.sub(r"[^가-힣A-Za-z0-9]","",str(item.get("name") or "")).lower()[:160]
                if not key or key in scope_seen:continue
                scope_seen.add(key);merged.append(item)
            if len(merged)<limit:
                for item in old:
                    if len(merged)>=limit:break
                    key=re.sub(r"[^가-힣A-Za-z0-9]","",str(item.get("name") or "")).lower()[:160]
                    if not key or key in scope_seen:continue
                    scope_seen.add(key)
                    restored={"platform":platform,"category":category,"site_category":category,"query":"",
                              "name":item.get("name") or "","price":item.get("price"),"url":item.get("url") or "",
                              "image_url":item.get("image_url") or "","rank_no":len(merged)+1,
                              "text":"","preserved_previous":True}
                    merged.append(restored);preserved_previous.append(restored)
            for index,item in enumerate(merged[:limit],1):item["rank_no"]=index
            effective.extend(merged[:limit])
    rows=effective
    # v7.96: a successful Naver draft is a product-level exclusion, not merely
    # an article fingerprint.  Keep raw collection coverage intact, but remove
    # already-drafted products before candidates/Top100 are built.
    collected_rows=list(rows)
    rows,published_excluded=filter_published_candidates(collected_rows)
    outdir=ROOT/"outputs";outdir.mkdir(parents=True,exist_ok=True)
    try:
        diag=outdir/"published_product_collection_exclusions.csv"
        with diag.open("w",encoding="utf-8-sig",newline="") as f:
            fields=["platform","category","name","url","matched_name","saved_at","match_reason","match_score","registry_key"]
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(published_excluded)
    except Exception as exc:log("게시완료 상품 수집 제외 진단 저장 실패: "+str(exc))
    if published_excluded:
        log(f"[DISCOVERY] 네이버 임시저장 완료 상품 {len(published_excluded)}개 수집 후보에서 제외 · 신규 후보 {len(rows)}개")

    con=db_connect(row_factory=True)
    try:
        con.execute("DELETE FROM candidates")
        con.executemany("""INSERT INTO candidates(platform,category,query,name,price,url,image_url,rank_no,captured_at)
                          VALUES(?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            [(c["platform"],c["category"],"",c["name"],c.get("price"),c.get("url","") or "",
              c.get("image_url","") or "",c["rank_no"]) for c in rows])
        con.commit()

        expected=len(categories)*len(platforms)*limit
        missing=[]
        gate_failures=[];soft_warnings=[]
        for p in platforms:
            for cat in categories:
                # Coverage describes what the marketplace actually supplied.
                # Published-product exclusions are intentional, not failures.
                n=sum(1 for r in fresh_collected_rows if r["platform"]==p and r["category"]==cat)
                if n!=limit:missing.append(f"{p}/{cat} {n}/{limit}")
                cov=coverage.get(f"{p}|{cat}") or {}
                status=cov.get("status") or "error"
                if status!="ok":soft_warnings.append(f"{p}/{cat} status={status} · 확보 {n}/{limit}")
                if not cov.get("category_confirmed",False):soft_warnings.append(f"{p}/{cat} 카테고리 확인 실패 · 확보분만 반영")
                if p=="쿠팡" and not cov.get("ranking_anchor_confirmed",False):
                    soft_warnings.append(f"쿠팡/{cat} 쿠팡 랭킹순 미확인 · 확보분만 반영")
                if p=="토스쇼핑":
                    if cov.get("toss_collection_mode")=="api":
                        if not cov.get("toss_api_confirmed",False):soft_warnings.append(f"토스쇼핑/{cat} API 확인 실패 · 다른 확보분으로 계속")
                    else:
                        if not cov.get("toss_product_lookup_confirmed",False):soft_warnings.append(f"토스쇼핑/{cat} 상품 조회 미확인")
                        if not cov.get("toss_single_checkbox_confirmed",False):soft_warnings.append(f"토스쇼핑/{cat} 단독 체크 미확인")
                        if not cov.get("toss_filter_cleanup_confirmed",False):soft_warnings.append(f"토스쇼핑/{cat} 필터 초기화 미확인")
                        if len(cov.get("toss_checked_before_collect") or [])!=1:soft_warnings.append(f"토스쇼핑/{cat} 수집 직전 체크 수 비정상")
                        if cov.get("toss_checked_after_collect") or []:soft_warnings.append(f"토스쇼핑/{cat} 수집 후 체크/필터 잔존")
        # v7.54: there is no arbitrary raw-count threshold. Any valid rows are
        # ranked; if fewer than 100 distinct products remain, all of them are
        # shown as Top N instead of discarding the completed collection.
        if not collected_rows:
            raise RuntimeError("유효한 수집 상품이 0개라 순위를 만들 수 없습니다. 수집 진단을 확인하세요.")
        groups={}
        for c in rows:
            gkey=_group_key(c["name"])
            g=groups.setdefault(gkey,{
                "key":gkey,"names":[],"platforms":set(),"category_hits":{},"rank_score":0,
                "appearances":0,"url":"","image_url":"","best_rank":999,"rows":[]
            })
            g["names"].append(c["name"]);g["platforms"].add(c["platform"]);g["appearances"]+=1
            g["category_hits"][c["category"]]=g["category_hits"].get(c["category"],0)+1
            # rank 1=30 points ... rank 30=1 point
            g["rank_score"]+=max(1,31-int(c.get("rank_no") or 30))
            g["best_rank"]=min(g["best_rank"],int(c.get("rank_no") or 30));g["rows"].append(c)
            if not g["url"] and c.get("url"):g["url"]=c["url"]
            if not g["image_url"] and c.get("image_url"):g["image_url"]=c["image_url"]

        weights=get_weights(categories)
        for g in groups.values():
            g["category"]=max(categories,key=lambda x:(g["category_hits"].get(x,0),
                sum(max(1,31-int(r.get("rank_no") or 30)) for r in g["rows"] if r["category"]==x)))
            consensus=len(g["platforms"])
            # Cross-site appearance dominates, then actual within-category rank.
            g["weighted_score"]=(consensus*300 + g["rank_score"]*5 + min(g["appearances"],6)*10)*weights.get(g["category"],1.0)

        final_total=int(cfg.get("final_top_products",100))
        ranked=sorted(groups.values(),key=lambda g:(g["weighted_score"],len(g["platforms"]),-g["best_rank"]),reverse=True)[:final_total]

        old_products=[dict(x) for x in con.execute("SELECT * FROM products WHERE COALESCE(content_type,'')<>'celebrity_style' AND COALESCE(source_platform,'') NOT LIKE '%왈라랜드%' ORDER BY id").fetchall()]
        old_by_url={str(x.get("source_url") or ""):x for x in old_products if str(x.get("source_url") or "")}
        old_by_key={}
        for old in old_products:
            old_by_key.setdefault(_group_key(old.get("name") or ""),[]).append(old)
        used_old_ids=set();new_product_ids=[]
        for i,g in enumerate(ranked,1):
            name=max(g["names"],key=len)
            candidate_urls=[str(x.get("url") or "") for x in g.get("rows") or [] if str(x.get("url") or "")]
            old=next((old_by_url[u] for u in candidate_urls if u in old_by_url and int(old_by_url[u]["id"]) not in used_old_ids),None)
            if old is None:
                old=next((x for x in old_by_key.get(_group_key(name),[]) if int(x["id"]) not in used_old_ids),None)
            source_platform=",".join(sorted(g["platforms"]));source_url=g["url"]
            if old is not None:
                oid=int(old["id"]);used_old_ids.add(oid);new_product_ids.append(oid)
                has_content=bool(str(old.get("title") or "").strip() and str(old.get("body") or "").strip() and str(old.get("tags") or "").strip())
                next_status=str(old.get("status") or "원고완료") if has_content else "검색선정"
                if next_status.startswith("추천제외:이전작성보존"):next_status="원고완료" if has_content else "검색선정"
                con.execute("""UPDATE products SET product_no=?,name=?,category=?,product_identity=?,source_platform=?,source_url=?,score=?,status=?,updated_at=datetime('now','localtime') WHERE id=?""",
                            (i,name,g["category"],json.dumps(identity_terms(name),ensure_ascii=False),source_platform,source_url,g["weighted_score"],next_status,oid))
            else:
                cur=con.execute("""INSERT INTO products(product_no,name,category,product_identity,source_platform,source_url,score,status,updated_at)
                                   VALUES(?,?,?,?,?,?,?,'검색선정',datetime('now','localtime'))""",
                                (i,name,g["category"],json.dumps(identity_terms(name),ensure_ascii=False),source_platform,source_url,g["weighted_score"]))
                new_product_ids.append(int(cur.lastrowid))
        # Remove only untouched empty leftovers. Generated content/images/links
        # remain recoverable but are excluded from the active Top list.
        for old in old_products:
            oid=int(old["id"])
            if oid in used_old_ids:continue
            material=any(str(old.get(k) or "").strip() for k in ("title","body","tags","image1","image2","image3","sharelink","post_dir"))
            if material:
                con.execute("UPDATE products SET product_no=NULL,status='추천제외:이전작성보존',updated_at=datetime('now','localtime') WHERE id=?",(oid,))
            else:
                con.execute("DELETE FROM products WHERE id=?",(oid,))
        con.commit()

        dist={cat:sum(1 for g in ranked if g["category"]==cat) for cat in categories}
        (outdir/"final_top100_from_540.json").write_text(json.dumps({
            "raw_target":expected,"raw_actual":len(fresh_collected_rows),"effective_with_preserved":len(collected_rows),
            "preserved_previous_count":len(preserved_previous),"collection_complete":len(fresh_collected_rows)==expected and not missing,
            "partial_accepted":len(fresh_collected_rows)!=expected or bool(missing),"shortages":missing,"soft_warnings":soft_warnings,
            "published_product_duplicates_excluded":len(published_excluded),"fresh_candidate_actual":len(rows),
            "published_registry":registry_summary(),
            "published_exclusion_diagnostic":str(outdir/"published_product_collection_exclusions.csv"),
            "final_target":final_total,"final_actual":len(ranked),"ranking_mode":"AVAILABLE_ROWS_TOP_N_V7_54",
            "page_size":int(cfg.get("top100_page_size",50)),"category_distribution":dist,
            "products":[{"rank":i+1,"name":max(g["names"],key=len),"category":g["category"],
                         "platforms":sorted(g["platforms"]),"score":g["weighted_score"],"best_rank":g["best_rank"]}
                        for i,g in enumerate(ranked)],"errors":errors
        },ensure_ascii=False,indent=2),encoding="utf-8")
    finally:
        con.close()

    partial=len(fresh_collected_rows)!=expected or bool(missing)
    if progress:
        base=(f"부분수집 신규 {len(fresh_collected_rows)}/{expected} · 이전정상 {len(preserved_previous)}건 보존" if partial else f"완전수집 {expected}/{expected}")
        progress(1,1,base+f" · 게시완료 중복 {len(published_excluded)}개 제외 · 신규 Top {len(ranked)}")
    return {"candidates":len(rows),"collected_candidates":len(collected_rows),"selected":len(ranked),
            "fresh_collected_candidates":len(fresh_collected_rows),"preserved_previous":len(preserved_previous),
            "published_duplicates_excluded":len(published_excluded),"partial_accepted":partial,"shortages":missing,
            "stage_ok":True,"soft_pending":partial,"errors":errors[-20:],
            "message":f"신규 수집 {len(fresh_collected_rows)}개 · 이전 정상 {len(preserved_previous)}건 보존 · 임시저장 완료 중복 {len(published_excluded)}개 제외 · 신규 Top {len(ranked)}"}

def run(context=None,progress=None):
    return discover(progress)
