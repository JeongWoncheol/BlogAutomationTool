# -*- coding: utf-8 -*-
from pathlib import Path
import json, re, time, urllib.parse
from .common import ROOT, strict_product_match, log
from .search_adapter import driver_start, wait_results, extract_cards

CFG_PATH=ROOT/"data"/"toss_web.json"

DEFAULT_CFG={
    "enabled": True,
    "mode_order": ["share_url","web_url","manual_url","android_fallback"],
    "known_domains": ["toss.im","shopping.toss.im","toss-shopping.com"],
    "search_timeout_sec": 12,
    "minimum_identity_score": 0.55,
    "allow_android_fallback": False,
    "manual_url_file": "data/toss_manual_urls.json",
    "notes": "Android is optional. Web/share URL methods are attempted first. Unsupported or blocked flows remain unverified rather than guessed."
}

def ensure_config():
    if not CFG_PATH.exists():
        CFG_PATH.write_text(json.dumps(DEFAULT_CFG,ensure_ascii=False,indent=2),encoding="utf-8")
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))

def _manual_map():
    c=ensure_config()
    p=ROOT/c.get("manual_url_file","data/toss_manual_urls.json")
    if not p.exists():
        p.write_text("{}",encoding="utf-8")
    try:return json.loads(p.read_text(encoding="utf-8"))
    except:return {}

def _price_from_text(text):
    vals=[]
    for x in re.findall(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원',text or ""):
        try: vals.append(int(x.replace(",","")))
        except: pass
    return min(vals) if vals else None

def _pick_image(driver):
    els=driver.find_elements("css selector","img")
    best=None
    for e in els:
        try:
            if not e.is_displayed(): continue
            s=e.size
            if s.get("width",0)<180 or s.get("height",0)<180: continue
            src=e.get_attribute("src") or e.get_attribute("data-src") or ""
            if not src: continue
            area=s["width"]*s["height"]
            if not best or area>best[0]: best=(area,e,src)
        except: pass
    return best

def _page_record(driver,target_name,evdir,source,url):
    wait_results(driver,ensure_config().get("search_timeout_sec",12))
    text=driver.page_source
    # visible body text is better if available
    try:
        body=driver.find_element("tag name","body").text
        if body: text=body
    except: pass
    score,detail=strict_product_match(text,target_name)
    price=_price_from_text(text)
    evdir=Path(evdir);evdir.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime("%Y%m%d_%H%M%S")
    shot=evdir/f"토스_{source}_{stamp}.png"
    try: driver.save_screenshot(str(shot))
    except: pass
    image_path=None
    try:
        best=_pick_image(driver)
        if best:
            image_path=evdir/f"토스_{source}_제품사진_{stamp}.png"
            best[1].screenshot(str(image_path))
    except: pass
    if score < float(ensure_config().get("minimum_identity_score",0.55)):
        return {"site":"토스쇼핑","price":None,"product_name":text[:220],"image_path":str(image_path) if image_path else None,
                "match":score,"evidence":str(shot),"url":url,"source":source,
                "reason":"동일상품 검증 점수 미달"}
    if not price:
        return {"site":"토스쇼핑","price":None,"product_name":text[:220],"image_path":str(image_path) if image_path else None,
                "match":score,"evidence":str(shot),"url":url,"source":source,
                "reason":"화면 표시가격 추출 실패"}
    return {"site":"토스쇼핑","price":price,"product_name":text[:220],"image_path":str(image_path) if image_path else None,
            "match":score,"evidence":str(shot),"url":url,"source":source}

def _candidate_urls(product_name,explicit_url=None):
    c=ensure_config()
    urls=[]
    if explicit_url: urls.append(("manual_url",explicit_url))
    mmap=_manual_map()
    if product_name in mmap and mmap[product_name]:
        urls.append(("manual_url",mmap[product_name]))
    # If the product name/body already contains a Toss share URL, accept it.
    for u in re.findall(r'https?://[^\s<>"\']+',product_name or ""):
        if any(d in u for d in c.get("known_domains",[])):
            urls.append(("share_url",u))
    seen=set();out=[]
    for source,u in urls:
        if not u or u in seen: continue
        seen.add(u);out.append((source,u))
    return out

def fetch(product_name,evdir,explicit_url=None,driver=None):
    """
    Web/share URL first. Android is NOT required.
    If no verified Toss URL is available or the page cannot be read, return unverified safely.
    """
    own=driver is None
    d=driver or driver_start(fast_discovery=False,isolated=True)
    try:
        candidates=_candidate_urls(product_name,explicit_url)
        if not candidates:
            return {"site":"토스쇼핑","price":None,"product_name":"","image_path":None,"match":0,
                    "reason":"토스 상품/쉐어 URL 없음 - Android 없이도 계속 진행 가능",
                    "source":"web_first"}
        errors=[]
        for source,url in candidates:
            try:
                d.get(url)
                rec=_page_record(d,product_name,evdir,source,url)
                if rec.get("price"): return rec
                errors.append(rec.get("reason","검증 실패"))
            except Exception as e:
                errors.append(str(e))
        return {"site":"토스쇼핑","price":None,"product_name":"","image_path":None,"match":0,
                "reason":" / ".join(errors)[:500] or "토스 웹 검증 실패","source":"web_first"}
    finally:
        if own:
            try:d.quit()
            except:pass

def health():
    c=ensure_config()
    return {"ready":True,"state":"PASS","name":"토스쇼핑 Web/URL 가격·사진 검증",
            "message":"Android 선택사항 / Share·상품 URL 우선 / 실패 시 미검증 처리"}
