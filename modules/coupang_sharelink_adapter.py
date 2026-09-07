# -*- coding: utf-8 -*-
"""Dedicated Coupang Sharelink stage for products with three verified images."""
from pathlib import Path
import csv,json,os,time
from .common import *
from . import coupang_partners_api

def health():
    state=coupang_partners_api.health()
    return {"ready":bool(state.get("ready")),"name":"쿠팡 쉐어링크(사진3장 성공만)",
            "message":"대표 1장+상세/갤러리 2장 검증 상품만 처리 · 제휴링크 무클릭 생성/상품ID DB 캐시 · "+str(state.get("message") or "")}

def _physical_image_count(row):
    count=0
    for key in ("image1","image2","image3"):
        try:
            value=str(row[key] or "").strip()
            if value and Path(value).is_file():count+=1
        except Exception:pass
    return count

def _affiliate_blocks(blocks,link):
    clean=[dict(b) for b in (blocks or []) if isinstance(b,dict) and b.get("type")!="sharelink"]
    clean=normalize_disclosure_blocks(clean)
    if link:
        clean.insert(1,{"type":"sharelink","url":link,"position":"top_after_disclosure","source":"coupang_partners"})
        clean.append({"type":"sharelink","url":link,"position":"bottom","source":"coupang_partners"})
    return clean

def _update_post_file(row,link,evidence):
    pdir=Path(str(row["post_dir"] or ""));path=pdir/"post.json"
    if not path.is_file():raise RuntimeError("post.json 없음")
    post=json.loads(path.read_text(encoding="utf-8"))
    post["sharelink"]=link
    post["blocks"]=_affiliate_blocks(post.get("blocks") or [],link)
    post["coupang_sharelink_evidence"]=evidence
    post["sharelink_stage"]="separate_after_three_verified_images"
    tmp=path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(post,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,path)
    return post

def run(context=None,progress=None):
    init_db_fast();cfg=settings();con=db_connect(row_factory=True)
    all_rows=con.execute("SELECT * FROM products WHERE post_dir IS NOT NULL AND status NOT LIKE '추천제외:%' AND COALESCE(already_posted,0)=0 ORDER BY product_no,id").fetchall()
    rows=[];skipped=[]
    for row in all_rows:
        physical=_physical_image_count(row);verified=int(row["image_verified_count"] or 0)
        image_ok,image_detail=verified_blog_image_set(row,3)
        if not image_ok:
            skipped.append({"TOP":row["product_no"] or row["id"],"상품명":row["name"],"결과":"제외",
                            "원인":image_detail.get("reason") or f"검증 이미지 {min(physical,verified)}/3"})
        elif not row["title"] or not row["body"] or not row["tags"]:
            skipped.append({"TOP":row["product_no"] or row["id"],"상품명":row["name"],"결과":"제외","원인":"제목·본문·태그 미완료"})
        else:rows.append(row)
    success=0;failed=[];preserved=0;diagnostics=list(skipped)
    try:
        for index,row in enumerate(rows,1):
            if progress:progress(index-1,len(rows),f"사진3장 성공 쉐어링크: {row['name'][:32]}")
            current=str(row["sharelink"] or "").strip()
            if coupang_partners_api._valid_affiliate_url(current):
                try:
                    coupang_partners_api.remember_existing_deeplink(
                        coupang_partners_api._product_id_from_url(str(row["source_url"] or "")),
                        current,str(row["source_url"] or ""),str(row["name"] or ""),
                        str(cfg.get("coupang_partner_sub_id","") or ""))
                except Exception as exc:log("기존 제휴링크 DB 캐시 기록 경고: "+str(exc))
                preserved+=1;success+=1
                diagnostics.append({"TOP":row["product_no"] or row["id"],"상품명":row["name"],"결과":"기존링크 유지","원인":""})
                if progress:progress(index,len(rows),f"기존 쉐어링크 유지: {row['name'][:30]}")
                continue
            try:
                source_platform=str(row["source_platform"] or "")
                verified_url=str(row["source_url"] or "") if "쿠팡" in source_platform else ""
                evidence=coupang_partners_api.exact_product_sharelink(
                    row["name"],sub_id=str(cfg.get("coupang_partner_sub_id","") or ""),
                    max_queries=int(cfg.get("coupang_partner_sharelink_search_queries",7)),
                    verified_product_url=verified_url)
                link=str(evidence.get("sharelink") or "").strip() if evidence.get("ok") else ""
                if not link:raise RuntimeError(str(evidence.get("reason") or "쿠팡 동일상품 쉐어링크 없음"))
                post=_update_post_file(row,link,evidence)
                con.execute("UPDATE products SET sharelink=?,body=?,last_error=NULL,updated_at=datetime('now','localtime') WHERE id=?",
                            (link,json.dumps(post.get("blocks") or [],ensure_ascii=False),row["id"]))
                con.commit();success+=1
                diagnostics.append({"TOP":row["product_no"] or row["id"],"상품명":row["name"],"결과":"성공","원인":""})
            except Exception as exc:
                reason=f"쉐어링크 실패: {type(exc).__name__}: {exc}"
                failed.append({"id":row["id"],"TOP":row["product_no"] or row["id"],"name":row["name"],"reason":reason})
                con.execute("UPDATE products SET last_error=?,updated_at=datetime('now','localtime') WHERE id=?",(reason[:1800],row["id"]));con.commit()
                diagnostics.append({"TOP":row["product_no"] or row["id"],"상품명":row["name"],"결과":"실패","원인":reason})
            if progress:progress(index,len(rows),f"쉐어링크 처리 {index}/{len(rows)}")
    finally:
        con.close()
    OUTPUTS.mkdir(parents=True,exist_ok=True);diag=OUTPUTS/"coupang_sharelink_image3_diagnostic.csv"
    with diag.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["TOP","상품명","결과","원인"]);w.writeheader();w.writerows(diagnostics)
    message=f"사진3장 성공 상품 쉐어링크 {success}/{len(rows)} · 기존링크 {preserved}건 · 실패 {len(failed)}건 · 이미지 미달 제외 {len(skipped)}건"
    return {"processed":success,"failed":failed,"eligible":len(rows),"skipped":skipped,
            "stage_ok":not failed,"soft_pending":bool(failed),"diagnostic_csv":str(diag),"message":message}
