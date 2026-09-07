# -*- coding: utf-8 -*-
from pathlib import Path
import json,time,re
from urllib.parse import quote
from .common import ROOT,log,performance_settings

STATE_DIR=ROOT/"data"/"market_circuit"
STATE_DIR.mkdir(parents=True,exist_ok=True)

MARKETS={
 "쿠팡":{
   "home":"https://www.coupang.com/",
   "direct_search":None,
   "search_selectors":[
      "input#headerSearchKeyword","input[name='q']",
      "input[placeholder*='상품']","input[placeholder*='검색']","input[type='search']"
   ],
   "strong":["access denied","you don't have permission to access","errors.edgesuite.net","reference #18."],
 },
 "네이버쇼핑":{
   "home":"https://shopping.naver.com/home",
   "direct_search":lambda q:"https://search.shopping.naver.com/search/all?query="+quote(q),
   "search_selectors":[
      "input[placeholder*='검색']","input[type='search']","input[name='query']","input[name='q']"
   ],
   "strong":["비정상적인 접근","자동입력 방지","서비스 이용이 제한","접근이 제한되었습니다"],
 }
}
_LAST={}

def _path(site):return STATE_DIR/(re.sub(r"[^0-9A-Za-z가-힣_-]","_",site)+".json")
def _load(site):
    try:return json.loads(_path(site).read_text(encoding="utf-8"))
    except:return {"blocked_until":0,"reason":""}
def _save(site,obj):_path(site).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
def remaining(site):return max(0,int(_load(site).get("blocked_until",0)-time.time()))
def blocked(site):return remaining(site)>0
def reset(site=None):
    for s in ([site] if site else list(MARKETS)):_save(s,{"blocked_until":0,"reason":""})

def trip(site,reason):
    sec=int(performance_settings().get("market_block_cooldown_sec",600))
    _save(site,{"blocked_until":time.time()+sec,"reason":str(reason),"at":time.strftime("%Y-%m-%d %H:%M:%S")})
    log(f"[MARKET][{site}][CIRCUIT OPEN] {sec}s: {reason}")

def _visible_text(driver):
    try:
        body=driver.find_element("tag name","body")
        return (body.text or "")[:30000].lower()
    except:
        try:return (driver.title or "").lower()
        except:return ""

def detect_block(driver,site):
    """
    Strong visible-page signatures only.
    Do NOT inspect arbitrary JS source for generic words like captcha/403/429,
    because that caused false circuit trips in v6.7.
    """
    cfg=MARKETS[site]
    try:url=(driver.current_url or "").lower()
    except:url=""
    text=_visible_text(driver)
    if site=="쿠팡" and "errors.edgesuite.net" in url:return True
    return any(sig.lower() in text for sig in cfg["strong"])

def save_evidence(driver,site,label):
    ev=ROOT/"evidence"/"_market_diagnostic"/site;ev.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime("%Y%m%d_%H%M%S")
    shot=ev/f"{label}_{stamp}.png";html=ev/f"{label}_{stamp}.html"
    try:driver.save_screenshot(str(shot))
    except:pass
    try:html.write_text(driver.page_source,encoding="utf-8",errors="replace")
    except:pass
    return str(shot),str(html)

def throttle(site):
    sec=float(performance_settings().get("market_min_interval_sec",2.0))
    left=sec-(time.monotonic()-_LAST.get(site,0))
    if left>0:time.sleep(left)
    _LAST[site]=time.monotonic()

def _find_search(driver,site,timeout=7):
    from selenium.webdriver.common.by import By
    end=time.time()+timeout
    while time.time()<end:
        for sel in MARKETS[site]["search_selectors"]:
            try:
                for e in driver.find_elements(By.CSS_SELECTOR,sel):
                    if e.is_displayed() and e.is_enabled():return e
            except:pass
        time.sleep(.2)
    return None

def search(driver,site,query):
    from selenium.webdriver.common.keys import Keys
    if site not in MARKETS:raise RuntimeError("지원하지 않는 쇼핑몰: "+site)
    if blocked(site):
        raise RuntimeError(f"{site} 안전대기 {remaining(site)}초")
    throttle(site);cfg=MARKETS[site]

    # Naver: direct public search URL is a normal shopping search and is more stable
    # than relying on a changing home-page input selector.
    if site=="네이버쇼핑" and cfg.get("direct_search"):
        try:driver.get(cfg["direct_search"](query))
        except Exception:pass
        time.sleep(.4)
        if detect_block(driver,site):
            save_evidence(driver,site,"search_blocked");trip(site,"검색 접근 제한")
            raise RuntimeError("네이버쇼핑 접근 제한 감지")
        return True

    # Coupang: home -> visible search field; direct /np/search was previously denied.
    try:
        if "coupang.com" not in (driver.current_url or "").lower():
            driver.get(cfg["home"]);time.sleep(.5)
    except Exception:pass
    if detect_block(driver,site):
        save_evidence(driver,site,"home_blocked");trip(site,"홈 접근 제한")
        raise RuntimeError("쿠팡 홈 Access Denied")
    field=_find_search(driver,site)
    if not field:
        try:driver.get(cfg["home"]);time.sleep(.6)
        except:pass
        field=_find_search(driver,site)
    if not field:
        save_evidence(driver,site,"search_field_missing")
        raise RuntimeError("쿠팡 검색창을 찾지 못함")
    try:
        field.click();field.send_keys(Keys.CONTROL,"a");field.send_keys(Keys.BACKSPACE)
        field.send_keys(query);field.send_keys(Keys.ENTER)
    except Exception as e:raise RuntimeError("쿠팡 검색 입력 실패: "+str(e))
    end=time.time()+int(performance_settings().get("search_page_timeout_sec",12))
    while time.time()<end:
        if detect_block(driver,site):
            save_evidence(driver,site,"search_blocked");trip(site,f"검색 '{query}' Access Denied")
            raise RuntimeError("쿠팡 자동 검색 Access Denied")
        try:
            if len(driver.find_elements("css selector",
                "li.search-product,li[class*='search-product'],article,div[class*='product'],div[class*='item']"))>0:
                reset(site);return True
        except:pass
        time.sleep(.2)
    if detect_block(driver,site):
        save_evidence(driver,site,"search_blocked");trip(site,"검색 결과 접근 제한")
        raise RuntimeError("쿠팡 검색 결과 Access Denied")
    return True

def health():
    vals=[]
    waiting=False
    for s in MARKETS:
        r=remaining(s)
        if r:waiting=True;vals.append(f"{s}:대기 {r}초")
        else:vals.append(f"{s}:READY")
    return {"ready":True,"state":"WAIT" if waiting else "PASS",
            "name":"쿠팡/네이버 PC 검색","message":" / ".join(vals)}
