# -*- coding: utf-8 -*-
"""Distinguish products already posted outside Studio.

Manual decisions are authoritative.  Automatic matching reads only public
Naver RSS titles or a user-selected title file.  Strong matches are excluded;
ambiguous matches are flagged for review but stay eligible.
"""
from __future__ import annotations

import csv
import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .common import DATA, DB, OUTPUTS, init_db, log
from .published_product_registry import (
    _same_product_profiles,
    product_profile,
    record_known_published_product,
    remove_known_published_product,
)


CONFIG_PATH=DATA/"already_posted_config.json"
REPORT_ROOT=OUTPUTS/"already_posted"
AUTO_SCORE=0.82
REVIEW_SCORE=0.55
POSTED_COLUMNS=(
    ("already_posted","INTEGER DEFAULT 0"),
    ("already_posted_review","INTEGER DEFAULT 0"),
    ("already_posted_auto_ignored","INTEGER DEFAULT 0"),
    ("already_posted_method","TEXT"),
    ("already_posted_title","TEXT"),
    ("already_posted_url","TEXT"),
    ("already_posted_at","TEXT"),
    ("already_posted_match_score","REAL"),
)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def health():
    return {"ready":True,"name":"기존 게시글 제외","message":"수동 표시·RSS/제목파일 안전 대조 준비됨"}


def ensure_schema(con=None):
    init_db()
    own=con is None
    if own:con=sqlite3.connect(DB)
    columns={row[1] for row in con.execute("PRAGMA table_info(products)").fetchall()}
    for name,kind in POSTED_COLUMNS:
        if name not in columns:con.execute(f"ALTER TABLE products ADD COLUMN {name} {kind}")
    con.execute("CREATE INDEX IF NOT EXISTS ix_products_already_posted ON products(already_posted,already_posted_review,import_batch_id)")
    con.commit()
    if own:con.close()


def _atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temp,path)


def normalize_blog_id(value):
    raw=str(value or "").strip()
    looks_like_url="://" in raw or raw.casefold().startswith(("blog.naver.com/","m.blog.naver.com/"))
    if looks_like_url:
        parsed=urllib.parse.urlparse(raw if "://" in raw else "https://"+raw)
        query=urllib.parse.parse_qs(parsed.query)
        raw=str((query.get("blogId") or query.get("blogid") or [""])[0]).strip()
        if not raw:
            parts=[part for part in parsed.path.split("/") if part]
            raw=parts[0] if parts else ""
    raw=raw.strip().strip("/@")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}",raw):
        raise RuntimeError("네이버 블로그 ID 또는 blog.naver.com 주소를 정확히 입력하세요.")
    return raw


def load_config():
    try:
        value=json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except Exception:return {}


def save_blog_id(value):
    blog_id=normalize_blog_id(value)
    cfg=load_config();cfg.update({"blog_id":blog_id,"updated_at":_now()})
    _atomic_json(CONFIG_PATH,cfg)
    return blog_id


def _clean_title(value):
    value=html.unescape(re.sub(r"<[^>]+>"," ",str(value or "")))
    value=re.sub(r"\s+"," ",value).strip()
    return value


def fetch_naver_rss(blog_id,timeout=25):
    blog_id=normalize_blog_id(blog_id)
    url=f"https://rss.blog.naver.com/{urllib.parse.quote(blog_id)}.xml"
    request=urllib.request.Request(
        url,
        headers={"User-Agent":"NaverBlogAutomationStudio/8.06 (HTTP/1.1; public RSS duplicate check)","Accept":"application/rss+xml, application/xml;q=0.9, text/xml;q=0.8"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            status=int(getattr(response,"status",200) or 200)
            payload=response.read(8*1024*1024)
    except Exception as exc:
        raise RuntimeError(f"네이버 RSS를 읽지 못했습니다: {type(exc).__name__}: {exc}") from exc
    if status!=200:raise RuntimeError(f"네이버 RSS 응답 코드 {status}")
    try:root=ET.fromstring(payload)
    except Exception as exc:raise RuntimeError(f"네이버 RSS XML 형식 오류: {exc}") from exc
    posts=[];seen=set()
    for item in root.findall(".//item"):
        title=_clean_title(item.findtext("title") or "")
        link=str(item.findtext("link") or "").strip()
        published=str(item.findtext("pubDate") or "").strip()
        key=(title.casefold(),link)
        if not title or key in seen:continue
        seen.add(key);posts.append({"title":title,"url":link,"published_at":published,"source":"NAVER_RSS"})
    if not posts:raise RuntimeError("RSS에서 공개 게시글 제목을 찾지 못했습니다. 블로그 ID·공개 설정을 확인하세요.")
    return posts,{"blog_id":blog_id,"rss_url":url,"count":len(posts),"checked_at":_now()}


def read_title_file(path):
    selected=Path(path)
    if not selected.is_file():raise RuntimeError("선택한 제목 파일이 없습니다.")
    suffix=selected.suffix.lower();posts=[]
    if suffix==".txt":
        for line in selected.read_text(encoding="utf-8-sig").splitlines():
            title=_clean_title(line)
            if title:posts.append({"title":title,"url":"","published_at":"","source":"TITLE_FILE"})
    elif suffix==".csv":
        with selected.open("r",encoding="utf-8-sig",newline="") as stream:
            rows=list(csv.reader(stream))
        if rows:
            header=[str(value).strip().casefold() for value in rows[0]]
            title_names={"제목","글제목","게시글제목","title","post title"}
            url_names={"url","링크","주소","게시글url"}
            title_index=next((i for i,value in enumerate(header) if value in title_names),0)
            url_index=next((i for i,value in enumerate(header) if value in url_names),None)
            start=1 if any(value in title_names for value in header) else 0
            for row in rows[start:]:
                if title_index>=len(row):continue
                title=_clean_title(row[title_index]);url=str(row[url_index]).strip() if url_index is not None and url_index<len(row) else ""
                if title:posts.append({"title":title,"url":url,"published_at":"","source":"TITLE_FILE"})
    elif suffix==".json":
        value=json.loads(selected.read_text(encoding="utf-8-sig"))
        if not isinstance(value,list):raise RuntimeError("JSON 제목 파일은 목록 형식이어야 합니다.")
        for item in value:
            if isinstance(item,str):title=item;url=""
            elif isinstance(item,dict):title=item.get("title") or item.get("제목") or "";url=item.get("url") or item.get("링크") or ""
            else:continue
            title=_clean_title(title)
            if title:posts.append({"title":title,"url":str(url or ""),"published_at":"","source":"TITLE_FILE"})
    else:raise RuntimeError("TXT, CSV, JSON 제목 파일만 지원합니다.")
    unique=[];seen=set()
    for post in posts:
        key=(post["title"].casefold(),post.get("url") or "")
        if key in seen:continue
        seen.add(key);unique.append(post)
    if not unique:raise RuntimeError("제목 파일에서 게시글 제목을 찾지 못했습니다.")
    return unique,{"file":str(selected.resolve()),"count":len(unique),"checked_at":_now()}


def _flat(value):
    return re.sub(r"[^가-힣a-z0-9]+","",str(value or "").lower())


def _line_signature(value):
    text=re.sub(r"[^가-힣a-z0-9]+"," ",str(value or "").lower()).strip()
    compact=text.replace(" ","")
    markers=set()
    pairs=(("promax",("promax","프로맥스")),("ultra",("ultra","울트라")),("plus",("plus","플러스")),
           ("mini",("mini","미니")),("air",("air","에어")),("fold",("fold","폴드")),
           ("flip",("flip","플립")),("lite",("lite","라이트")),("fe",(" fe ","에프이")))
    for key,aliases in pairs:
        if any(alias.strip() in compact if " " not in alias else alias in " "+text+" " for alias in aliases):markers.add(key)
    if "promax" not in markers:
        words=set(text.split())
        if "pro" in words or "프로" in words:markers.add("pro")
        if "max" in words or "맥스" in words:markers.add("max")
    numbers=set(re.findall(r"(?<![가-힣a-z0-9])\d{1,4}(?![가-힣a-z0-9])",text))
    return markers,numbers


def _match_title(product,post_title):
    title=_clean_title(post_title);title_flat=_flat(title)
    profile=product_profile(product["name"],product["source_url"] or "")
    candidate=re.split(r"[｜|]",title,1)[0].strip()
    candidate=re.sub(r"\s+(?:추천|후기|리뷰|사용기|구매기)\b.*$","",candidate,flags=re.I).strip() or title
    product_markers,product_numbers=_line_signature(product["name"])
    candidate_markers,candidate_numbers=_line_signature(candidate)
    if product_markers!=candidate_markers:return 0.0,"product_line_variant_mismatch"
    if product_numbers!=candidate_numbers:return 0.0,"model_generation_mismatch"
    candidate_profile=product_profile(candidate,"")
    same,profile_reason,profile_score=_same_product_profiles(profile,candidate_profile,0.78)
    if same:
        if profile_reason in ("source_product_id","exact_normalized_title","same_product_spec_ignored"):
            return max(0.94,float(profile_score)),profile_reason
        if float(profile_score)>=0.90:return float(profile_score),profile_reason
        return max(REVIEW_SCORE,min(0.79,float(profile_score))),profile_reason+"_review"
    if profile_reason=="model_variant_mismatch":
        return 0.0,profile_reason
    canonical=str(profile.get("canonical") or "");base=str(profile.get("base_canonical") or "")
    models=[_flat(value) for value in profile.get("models") or [] if _flat(value)]
    if models and any(model not in title_flat for model in models):return 0.0,"model_mismatch"
    if len(canonical)>=5 and canonical in title_flat:return 1.0,"exact_product_name_in_title"
    if len(base)>=6 and base in title_flat:return 0.94,"base_product_name_in_title"
    terms=[_flat(value) for value in profile.get("terms") or [] if len(_flat(value))>=2]
    if not terms:return 0.0,"identity_terms_missing"
    hits=[term for term in terms if term in title_flat];ratio=len(hits)/max(1,len(terms))
    lead=terms[0] in title_flat if terms else False
    if len(hits)>=3 and lead and ratio>=0.75:return max(REVIEW_SCORE,min(0.79,ratio)),"identity_terms_review"
    if len(hits)>=2 and lead and ratio>=0.55:return max(REVIEW_SCORE,min(0.79,ratio)),"identity_terms_review"
    return 0.0,"no_safe_match"


def _rows_for_batch(con,batch_id=""):
    where=["COALESCE(status,'') NOT LIKE '추천제외:%'"];params=[]
    if batch_id:where.append("COALESCE(import_batch_id,'')=?");params.append(batch_id)
    return con.execute("SELECT * FROM products WHERE "+" AND ".join(where)+" ORDER BY product_no,id",params).fetchall()


def match_posts(posts,batch_id="",method="NAVER_RSS_AUTO",progress=None):
    ensure_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    rows=_rows_for_batch(con,batch_id);auto=0;review=0;unchanged=0;matches=[]
    try:
        for index,row in enumerate(rows,1):
            if int(row["already_posted"] or 0):unchanged+=1;continue
            if int(row["already_posted_auto_ignored"] or 0):unchanged+=1;continue
            best=(0.0,"",None)
            for post in posts:
                score,reason=_match_title(row,post.get("title") or "")
                if score>best[0]:best=(score,reason,post)
                if score>=1.0:break
            score,reason,post=best
            if post is not None and score>=AUTO_SCORE:
                con.execute(
                    "UPDATE products SET already_posted=1,already_posted_review=0,already_posted_method=?,already_posted_title=?,already_posted_url=?,already_posted_at=?,already_posted_match_score=?,updated_at=datetime('now','localtime') WHERE id=?",
                    (method,post.get("title") or "",post.get("url") or "",_now(),float(score),row["id"]),
                );auto+=1
                source="naver_rss_existing_post" if method=="NAVER_RSS_AUTO" else "title_file_existing_post"
                try:record_known_published_product(row["name"],row["source_url"] or "",post.get("title") or "",post.get("url") or "",source)
                except Exception as exc:log("기존 게시글 레지스트리 기록 경고: "+str(exc))
                matches.append({"product_id":row["id"],"product_no":row["product_no"],"name":row["name"],"decision":"POSTED","score":round(score,4),"reason":reason,"post_title":post.get("title") or "","post_url":post.get("url") or ""})
            elif post is not None and score>=REVIEW_SCORE:
                con.execute(
                    "UPDATE products SET already_posted_review=1,already_posted_method='AUTO_REVIEW',already_posted_title=?,already_posted_url=?,already_posted_match_score=?,updated_at=datetime('now','localtime') WHERE id=?",
                    (post.get("title") or "",post.get("url") or "",float(score),row["id"]),
                );review+=1
                matches.append({"product_id":row["id"],"product_no":row["product_no"],"name":row["name"],"decision":"REVIEW","score":round(score,4),"reason":reason,"post_title":post.get("title") or "","post_url":post.get("url") or ""})
            else:unchanged+=1
            if progress:progress(index,len(rows),f"기존 게시글 대조 {index}/{len(rows)}: {row['name'][:30]}")
        con.commit()
    finally:con.close()
    report=export_status_report(batch_id,matches)
    return {"processed":len(rows),"posted":auto,"review":review,"unchanged":unchanged,"report_csv":report,"message":f"기존 게시글 자동대조 완료 · 게시완료 {auto}개 · 확인 필요 {review}개 · 남은 제품 {batch_summary(batch_id)['remaining']}개"}


def mark_manual(product_ids,posted=True):
    ids=[int(value) for value in product_ids if str(value).isdigit()]
    if not ids:return {"changed":0,"message":"선택한 제품이 없습니다."}
    ensure_schema();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    rows=con.execute("SELECT * FROM products WHERE id IN ("+",".join("?" for _ in ids)+")",ids).fetchall();changed=0
    try:
        for row in rows:
            if posted:
                con.execute(
                    "UPDATE products SET already_posted=1,already_posted_review=0,already_posted_auto_ignored=0,already_posted_method='MANUAL',already_posted_title=COALESCE(NULLIF(title,''),name),already_posted_url='',already_posted_at=?,already_posted_match_score=1.0,updated_at=datetime('now','localtime') WHERE id=?",
                    (_now(),row["id"]),
                )
                try:record_known_published_product(row["name"],row["source_url"] or "",row["title"] or row["name"],"","manual_existing_post")
                except Exception as exc:log("수동 게시완료 레지스트리 기록 경고: "+str(exc))
            else:
                con.execute(
                    "UPDATE products SET already_posted=0,already_posted_review=0,already_posted_auto_ignored=1,already_posted_method='MANUAL_NOT_POSTED',already_posted_title=NULL,already_posted_url=NULL,already_posted_at=?,already_posted_match_score=NULL,updated_at=datetime('now','localtime') WHERE id=?",
                    (_now(),row["id"]),
                )
                try:remove_known_published_product(row["name"],row["source_url"] or "")
                except Exception as exc:log("게시표시 해제 레지스트리 정리 경고: "+str(exc))
            changed+=1
        con.commit()
    finally:con.close()
    return {"changed":changed,"message":f"선택 제품 {changed}개를 {'기존 게시완료' if posted else '미게시(수동 확인)'}로 표시했습니다."}


def batch_summary(batch_id=""):
    ensure_schema();con=sqlite3.connect(DB)
    try:
        where="COALESCE(status,'') NOT LIKE '추천제외:%'";params=[]
        if batch_id:where+=" AND COALESCE(import_batch_id,'')=?";params.append(batch_id)
        total,posted,review,manual_not=con.execute(
            f"SELECT COUNT(*),SUM(CASE WHEN COALESCE(already_posted,0)=1 THEN 1 ELSE 0 END),SUM(CASE WHEN COALESCE(already_posted_review,0)=1 AND COALESCE(already_posted,0)=0 THEN 1 ELSE 0 END),SUM(CASE WHEN COALESCE(already_posted_auto_ignored,0)=1 THEN 1 ELSE 0 END) FROM products WHERE {where}",params
        ).fetchone()
    finally:con.close()
    total=int(total or 0);posted=int(posted or 0);review=int(review or 0);manual_not=int(manual_not or 0)
    return {"total":total,"posted":posted,"review":review,"manual_not_posted":manual_not,"remaining":max(0,total-posted)}


def pending_product_ids(batch_id="",image_state=""):
    ensure_schema();con=sqlite3.connect(DB)
    try:
        where=["COALESCE(status,'') NOT LIKE '추천제외:%'","COALESCE(already_posted,0)=0"];params=[]
        if batch_id:where.append("COALESCE(import_batch_id,'')=?");params.append(batch_id)
        if image_state:where.append("COALESCE(import_image_state,'')=?");params.append(image_state)
        return [int(row[0]) for row in con.execute("SELECT id FROM products WHERE "+" AND ".join(where)+" ORDER BY product_no,id",params).fetchall()]
    finally:con.close()


def export_status_report(batch_id="",matches=None):
    ensure_schema();REPORT_ROOT.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    rows=_rows_for_batch(con,batch_id);con.close()
    suffix=re.sub(r"[^0-9A-Za-z_-]+","_",batch_id or "ALL")[:40]
    path=REPORT_ROOT/f"already_posted_{suffix}.csv"
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(["상품번호","상품명","게시구분","판정방식","대조 게시글 제목","게시글 URL","일치점수","이미지상태","현재처리상태"])
        for row in rows:
            if int(row["already_posted"] or 0):state="기존 게시완료"
            elif int(row["already_posted_review"] or 0):state="자동대조 확인필요"
            elif int(row["already_posted_auto_ignored"] or 0):state="미게시 수동확인"
            else:state="남은 제품"
            writer.writerow([row["product_no"],row["name"],state,row["already_posted_method"] or "",row["already_posted_title"] or "",row["already_posted_url"] or "",row["already_posted_match_score"] if row["already_posted_match_score"] is not None else "",row["import_image_state"] or "",row["status"] or ""])
    return str(path.resolve())
