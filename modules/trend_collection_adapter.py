# -*- coding: utf-8 -*-
"""Supplemental age/category trend collection for ItemScout and NAVER DataLab.

This module is deliberately isolated from the legacy 3-market 540-product table.
ItemScout/DataLab expose search-keyword/ranking trends rather than marketplace
product cards, so results are stored in ``trend_candidates`` and can be reviewed
or exported without changing the existing Top100 product pipeline.
"""
from pathlib import Path
from collections.abc import Callable
import csv, json, re, sqlite3, time
from .common import ROOT, DB, settings, log
from . import chrome_collector
from .collection_preferences import CollectionPreferences, load_preferences, apply_preferences, AGE_GROUPS

DEFAULT_CATEGORIES=["패션의류","패션잡화","화장품/미용","디지털/가전","가구/인테리어","식품"]
DEFAULT_AGE_GROUPS={label:list(codes) for label,codes in AGE_GROUPS.items()}
SOURCE_ITEMSCOUT="아이템스카우트"
SOURCE_DATALAB="네이버데이터랩"

ITEMSCOUT_CATEGORY_IDS={"패션의류":1,"패션잡화":2,"화장품/미용":3,"디지털/가전":4,"가구/인테리어":5,"식품":7}
DATALAB_CATEGORY_IDS={"패션의류":"50000000","패션잡화":"50000001","화장품/미용":"50000002","디지털/가전":"50000003","가구/인테리어":"50000004","식품":"50000006"}


def _slug(text):
    return re.sub(r"[^0-9A-Za-z가-힣_-]+","_",str(text or "")).strip("_") or "trend"


def _cfg_categories(cfg):
    return list(load_preferences(cfg).trend_categories)


def _cfg_age_groups(cfg):
    return [(label,list(AGE_GROUPS[label])) for label in load_preferences(cfg).age_groups]


def _tasks(source,cfg):
    limit=max(1,min(100,int(cfg.get("trend_top_per_category",30) or 30)))
    period=max(1,int(cfg.get("trend_period_days",30) or 30))
    gender=str(cfg.get("trend_gender","전체") or "전체")
    categories=_cfg_categories(cfg)
    age_groups=_cfg_age_groups(cfg)
    if source==SOURCE_ITEMSCOUT:
        # v8.00: the reference screenshots use keyword type "전체" with
        # "주요 브랜드 제외" enabled.  Category URLs are deterministic, so use
        # them directly and collect each selected decade before moving categories.
        keyword_type=str(cfg.get("itemscout_keyword_type") or "전체")
        exclude_major=bool(cfg.get("itemscout_exclude_major_brands",True))
    elif source==SOURCE_DATALAB:
        keyword_type="";exclude_major=False
    else:
        raise ValueError("지원하지 않는 트렌드 수집처: "+str(source))
    tasks=[];meta={}
    # Category outer-loop lets all selected decades reuse the category page.
    for ci,category in enumerate(categories,1):
        for gi,(age_label,age_codes) in enumerate(age_groups,1):
            tid=f"trend-{('itemscout' if source==SOURCE_ITEMSCOUT else 'datalab')}-{ci:02d}-{gi:02d}"
            if source==SOURCE_ITEMSCOUT:
                cat_id=int(ITEMSCOUT_CATEGORY_IDS.get(category,1))
                entry=str(cfg.get(f"itemscout_trend_url_{cat_id}") or f"https://itemscout.io/category/{cat_id}")
                category_id=str(cat_id)
            else:
                entry=str(cfg.get("naver_datalab_trend_url") or "https://datalab.naver.com/shoppingInsight/sCategory.naver")
                category_id=str(DATALAB_CATEGORY_IDS.get(category,""))
            task={
                "id":tid,"site":source,"mode":"trend_keyword_collect","query":category,
                "category_label":category,"category_id":category_id,"blog_category":category,"entry_url":entry,
                "age_group":age_label,"age_codes":age_codes,"limit":limit,
                "period_days":period,"gender":gender,"keyword_type":keyword_type,
                "exclude_major_brands":exclude_major,"capture":True,
                "delay_ms":int(cfg.get("trend_task_delay_ms",500) or 500),
                "task_timeout_sec":int(cfg.get("trend_task_timeout_sec",90) or 90),
                "evdir":str(ROOT/"evidence"/"trend_collection"/_slug(source)/_slug(age_label)/_slug(category)),
            }
            tasks.append(task);meta[tid]=(age_label,age_codes,category)
    return tasks,meta,limit


def _keyword_from_card(card):
    if not isinstance(card,dict):return ""
    for key in ("keyword","name","title","text"):
        value=re.sub(r"\s+"," ",str(card.get(key) or "")).strip()
        if value:return value[:250]
    return ""


def _rank_from_card(card,default):
    for key in ("rank","rank_no","rank_hint","position"):
        try:
            v=int(card.get(key))
            if v>0:return v
        except Exception:pass
    return int(default)


def _trend_key(text):
    # Same-category cross-age merge: punctuation/case/spacing differences are
    # considered the same displayed item, while model numbers remain intact.
    return re.sub(r"[^0-9A-Za-z가-힣]+","",str(text or "")).lower()


def merged_rows(source, preferences: CollectionPreferences | None = None):
    """Return display/export rows with duplicate keywords merged per category.

    Raw age-bucket rows remain in trend_candidates as evidence.  The GUI/CSV
    shows one row when the same item appears in multiple decades and preserves
    the per-age ranks inside the merged status/evidence summary.
    """
    selection=load_preferences() if preferences is None else preferences
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    try:
        rows=con.execute("""SELECT source,age_group,age_codes,category,rank_no,keyword,captured_at,page_url,status,evidence_json
                            FROM trend_candidates WHERE source=? ORDER BY category,rank_no,id""",(source,)).fetchall()
    finally:con.close()
    groups={}
    age_order={label:i for i,(label,_codes) in enumerate(DEFAULT_AGE_GROUPS.items())}
    for r in rows:
        if r["category"] not in selection.trend_categories or r["age_group"] not in selection.age_groups:continue
        d=dict(r);key=(d["category"],_trend_key(d["keyword"]))
        if not key[1]:continue
        g=groups.setdefault(key,{"source":d["source"],"category":d["category"],"keyword":d["keyword"],
            "age_groups":[],"age_codes":[],"ranks":{},"captured_at":d["captured_at"],"page_url":d["page_url"],
            "statuses":[],"evidence":[]})
        if d["age_group"] not in g["age_groups"]:g["age_groups"].append(d["age_group"])
        for code in str(d.get("age_codes") or "").split(","):
            if code and code not in g["age_codes"]:g["age_codes"].append(code)
        g["ranks"][d["age_group"]]=min(int(d["rank_no"] or 999),int(g["ranks"].get(d["age_group"],999)))
        g["captured_at"]=max(str(g["captured_at"] or ""),str(d["captured_at"] or ""))
        if d["status"] not in g["statuses"]:g["statuses"].append(d["status"])
        if d.get("evidence_json"):g["evidence"].append(d["evidence_json"])
    out=[]
    for g in groups.values():
        g["age_groups"].sort(key=lambda x:age_order.get(x,99))
        g["age_codes"]=[code for label,codes in AGE_GROUPS.items() if label in g["age_groups"] for code in codes]
        rank=min(g["ranks"].values()) if g["ranks"] else 999
        both=len(g["age_groups"])>1
        out.append({"source":g["source"],"age_group":" / ".join(g["age_groups"]),"age_codes":",".join(g["age_codes"]),
            "category":g["category"],"rank_no":rank,"keyword":g["keyword"],"captured_at":g["captured_at"],
            "page_url":g["page_url"],"status":"중복통합" if both else (g["statuses"][0] if g["statuses"] else "수집완료"),
            "age_rank":" / ".join(f"{a}:{g['ranks'][a]}위" for a in g["age_groups"] if a in g["ranks"]),
            "evidence_json":json.dumps({"merged_same_category":both,"age_ranks":g["ranks"],"raw_evidence":g["evidence"]},ensure_ascii=False)})
    out.sort(key=lambda r:(r["category"],int(r["rank_no"] or 999),r["keyword"]))
    return out


def _write_exports(source, preferences: CollectionPreferences):
    outdir=ROOT/"outputs";outdir.mkdir(parents=True,exist_ok=True)
    stem="itemscout_age_trends" if source==SOURCE_ITEMSCOUT else "naver_datalab_age_trends"
    merged=merged_rows(source,preferences)
    (outdir/f"{stem}.json").write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding="utf-8")
    with (outdir/f"{stem}.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["수집처","연령그룹","연령코드","카테고리","통합순위","키워드","연령별순위","수집시각","페이지URL","상태"])
        for r in merged:w.writerow([r["source"],r["age_group"],r["age_codes"],r["category"],r["rank_no"],r["keyword"],r["age_rank"],r["captured_at"],r["page_url"],r["status"]])
    # Export selected raw decade evidence; legacy combined rows stay in the DB.
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    try:raw=con.execute("""SELECT source,age_group,age_codes,category,rank_no,keyword,captured_at,page_url,status,evidence_json
                            FROM trend_candidates WHERE source=? ORDER BY category,age_group,rank_no,id""",(source,)).fetchall()
    finally:con.close()
    with (outdir/f"{stem}_RAW.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["수집처","연령그룹","연령코드","카테고리","순위","키워드","수집시각","페이지URL","상태","증거"])
        for r in raw:
            if r["category"] in preferences.trend_categories and r["age_group"] in preferences.age_groups:
                w.writerow([r[x] for x in r.keys()])
    return str(outdir/f"{stem}.csv")


def collect_source(source,progress=None,preferences: CollectionPreferences | None = None,stop_check: Callable[[], bool] | None = None):
    cfg=settings();selection=load_preferences(cfg) if preferences is None else preferences
    cfg.update(apply_preferences(cfg,selection));tasks,meta,limit=_tasks(source,cfg)
    if stop_check and stop_check():return {"stage_ok":False,"stopped":True,"count":0,"message":"트렌드 수집 중지"}
    if not tasks:return {"stage_ok":False,"message":"트렌드 수집 조건이 비어 있습니다.","count":0}
    log(f"[TREND] {source} 시작: {len(tasks)}개 조합 × TOP{limit}")
    results=chrome_collector.collect(
        tasks,progress=progress,
        timeout_sec=max(1200,len(tasks)*int(cfg.get("trend_task_timeout_sec",150) or 150))
    )
    if stop_check and stop_check():return {"stage_ok":False,"stopped":True,"count":0,"message":"트렌드 수집 중지: 기존 결과 보존"}
    now=time.strftime("%Y-%m-%d %H:%M:%S")
    byid={str(r.get("_task_id") or ""):r for r in results if isinstance(r,dict)}
    rows=[];errors=[];coverage={}
    for task in tasks:
        tid=task["id"];age_label,age_codes,category=meta[tid];res=byid.get(tid) or {}
        cards=res.get("cards") or []
        seen=set();accepted=[]
        for idx,card in enumerate(cards,1):
            kw=_keyword_from_card(card)
            key=re.sub(r"[^0-9A-Za-z가-힣]","",kw).lower()
            if not key or key in seen:continue
            seen.add(key);accepted.append((_rank_from_card(card,idx),kw,card))
        accepted.sort(key=lambda x:x[0]);accepted=accepted[:limit]
        page_url=str(res.get("url") or task.get("entry_url") or "")
        status=str(res.get("status") or ("ok" if accepted else "error"))
        evidence={
            "task_id":tid,"collector_status":status,"error":res.get("error") or "",
            "debug":res.get("debug") or {},"filter_state":res.get("filter_state") or {},
            "aggregation_mode":res.get("aggregation_mode") or "",
        }
        for pos,(site_rank,kw,card) in enumerate(accepted,1):
            # Persist a stable 1..30 rank per filtered bucket. The original site's
            # rank_hint stays inside evidence_json; this also protects against a
            # fallback page that repeats 1..10 for multiple dates.
            rank=pos
            rows.append((source,age_label,",".join(age_codes),category,rank,kw,now,page_url,
                         "수집완료" if status=="ok" else "부분수집",
                         json.dumps({**evidence,"card":card},ensure_ascii=False)))
        failure_detail={
            "count":len(accepted),"target":limit,"status":status,"error":res.get("error") or "",
            "page_url":page_url,"filter_state":res.get("filter_state") or {},"debug":res.get("debug") or {}
        }
        coverage[f"{age_label}|{category}"]=failure_detail
        if len(accepted)<limit:
            age_state=(res.get("filter_state") or {}).get("age_retry") or (res.get("filter_state") or {}).get("age") or {}
            actual=age_state.get("actual") or age_state.get("values") or (age_state.get("snapshot") or {}).get("chips") or []
            log(f"[TREND][FAIL] {source} {age_label}/{category} {len(accepted)}/{limit} method={age_state.get('method','')} actual={actual} error={res.get('error') or status}")
            errors.append(f"{age_label} · {category}: {len(accepted)}/{limit} ({res.get('error') or status})")
    fresh_rows=list(rows);preserved_count=0;effective_rows=[]
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    try:
        # Replace only one age/category bucket at a time. A short/failed bucket
        # keeps non-duplicate rows from its previous successful snapshot, while
        # fresh rows always take priority and retain ranks 1..N.
        for task in tasks:
            age_label,age_codes,category=meta[task["id"]]
            current=[x for x in fresh_rows if x[1]==age_label and x[3]==category]
            current.sort(key=lambda x:int(x[4] or 999))
            old=con.execute("""SELECT * FROM trend_candidates
                               WHERE source=? AND age_group=? AND category=?
                               ORDER BY rank_no,id""",(source,age_label,category)).fetchall()
            merged=[];seen=set()
            for x in current:
                key=_trend_key(x[5])
                if not key or key in seen:continue
                seen.add(key);merged.append(tuple(x))
            if len(merged)<limit:
                for old_row in old:
                    if len(merged)>=limit:break
                    key=_trend_key(old_row["keyword"])
                    if not key or key in seen:continue
                    seen.add(key);preserved_count+=1
                    try:old_evidence=json.loads(old_row["evidence_json"] or "{}")
                    except Exception:old_evidence={"legacy_evidence":old_row["evidence_json"] or ""}
                    old_evidence["v8_04_partial_preserved"]=True
                    old_evidence["preserved_at"]=now
                    merged.append((source,age_label,old_row["age_codes"] or ",".join(age_codes),category,
                                   len(merged)+1,old_row["keyword"],old_row["captured_at"] or now,
                                   old_row["page_url"] or task.get("entry_url") or "","이전정상보존",
                                   json.dumps(old_evidence,ensure_ascii=False)))
            # Re-number current rows too so the unique scope remains contiguous.
            merged=[(x[0],x[1],x[2],x[3],i,x[5],x[6],x[7],x[8],x[9]) for i,x in enumerate(merged,1)]
            con.execute("DELETE FROM trend_candidates WHERE source=? AND age_group=? AND category=?",
                        (source,age_label,category))
            con.executemany("""INSERT INTO trend_candidates
              (source,age_group,age_codes,category,rank_no,keyword,captured_at,page_url,status,evidence_json)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",merged)
            effective_rows.extend(merged)
        con.commit()
    finally:con.close()
    csv_path=_write_exports(source,selection)
    outdir=ROOT/"outputs";outdir.mkdir(parents=True,exist_ok=True)
    merged_count=len(merged_rows(source,selection))
    failures={k:v for k,v in coverage.items() if int(v.get("count") or 0)<int(v.get("target") or limit)}
    audit={"source":source,"captured_at":now,"target":len(tasks)*limit,"fresh_collected":len(fresh_rows),
           "effective_rows":len(effective_rows),"preserved_previous_rows":preserved_count,
           "merged_count":merged_count,"coverage":coverage,"failures":failures,"errors":errors,"csv":csv_path}
    base=('itemscout' if source==SOURCE_ITEMSCOUT else 'naver_datalab')
    (outdir/f"{base}_trend_coverage.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    (outdir/f"{base}_trend_failures.json").write_text(json.dumps({"source":source,"captured_at":now,"failures":failures},ensure_ascii=False,indent=2),encoding="utf-8")
    log(f"[TREND] {source} 완료: 신규 {len(fresh_rows)}/{len(tasks)*limit} · 이전정상보존 {preserved_count}")
    return {"stage_ok":bool(effective_rows),"soft_pending":len(fresh_rows)<len(tasks)*limit,
            "count":len(fresh_rows),"effective_count":len(effective_rows),"preserved_previous":preserved_count,
            "merged_count":merged_count,"target":len(tasks)*limit,
            "message":f"{source} 신규 {len(fresh_rows)}/{len(tasks)*limit} · 이전 정상 {preserved_count}건 보존 · 카테고리 중복통합 {merged_count}개", "errors":errors,"csv":csv_path}


def health():
    h=chrome_collector.health()
    selection=load_preferences()
    return {"ready":bool(h.get("ready",True)),"name":"아이템스카우트/데이터랩 트렌드 수집",
            "message":f"일반 Chrome 확장프로그램으로 선택한 {len(selection.trend_categories)}개 카테고리 × {len(selection.age_groups)}개 연령그룹을 수집합니다. "+str(h.get("message") or ""),
            "state":h.get("state","PASS")}
