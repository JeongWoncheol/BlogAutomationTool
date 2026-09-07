# -*- coding: utf-8 -*-
from pathlib import Path
import re,time
from .common import ROOT,log,strict_product_match,performance_settings

HOME="https://sharelink.toss.im/home"
PRICE_RE=re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원")

def health():
    return {"ready":True,"state":"PASS","name":"토스 쉐어링크 PC 상품조회",
            "message":"sharelink.toss.im/home 전용 Chrome 로그인 세션 사용 (Android 불필요)"}

def _body(driver):
    try:return driver.find_element("tag name","body").text or ""
    except:return ""

def _login_required(driver):
    try:
        url=(driver.current_url or "").lower()
        txt=_body(driver)
        return "/login" in url or ("로그인" in txt and "상품 조회" not in txt and "상품조회" not in txt)
    except:return False

def ensure_login(driver,wait_sec=None):
    wait_sec=int(wait_sec or performance_settings().get("market_login_wait_sec",180))
    try:driver.get(HOME)
    except:pass
    time.sleep(.7)
    if not _login_required(driver):return True
    log("[TOSS SHARELINK] 최초 로그인 필요 - 열린 Chrome에서 정상 로그인하세요.")
    end=time.time()+wait_sec
    while time.time()<end:
        try:
            if "sharelink.toss.im" in (driver.current_url or "") and not _login_required(driver):
                return True
        except:pass
        time.sleep(1)
    return False

def _click_product_lookup(driver):
    from selenium.webdriver.common.by import By
    labels=["상품 조회","상품조회","상품 검색","상품검색"]
    for label in labels:
        try:
            els=driver.find_elements(By.XPATH,f'//*[normalize-space(text())="{label}" or contains(normalize-space(.),"{label}")]')
        except:els=[]
        for e in els[:12]:
            try:
                if e.is_displayed() and e.is_enabled():
                    e.click();time.sleep(.5);return True
            except:pass
    return False

def _find_search(driver,timeout=12):
    from selenium.webdriver.common.by import By
    end=time.time()+timeout
    while time.time()<end:
        selectors=[
          "input[placeholder*='상품명']","input[placeholder*='상품']","input[placeholder*='검색']",
          "input[type='search']","input[aria-label*='검색']","input[type='text']"
        ]
        for sel in selectors:
            try:
                for e in driver.find_elements(By.CSS_SELECTOR,sel):
                    if not (e.is_displayed() and e.is_enabled()):continue
                    ph=(e.get_attribute("placeholder") or "")+(e.get_attribute("aria-label") or "")
                    if sel!="input[type='text']" or any(x in ph for x in ["상품","검색"]):
                        return e
            except:pass
        time.sleep(.2)
    return None

def navigate_lookup(driver):
    if not ensure_login(driver):return False,"로그인 시간 초과"
    f=_find_search(driver,2)
    if f:return True,"검색창 확인"
    _click_product_lookup(driver)
    f=_find_search(driver,10)
    if f:return True,"상품 조회 화면 확인"
    ev=ROOT/"evidence"/"_toss_sharelink";ev.mkdir(parents=True,exist_ok=True)
    try:driver.save_screenshot(str(ev/"상품조회_검색창없음.png"))
    except:pass
    try:(ev/"상품조회_화면.html").write_text(driver.page_source,encoding="utf-8",errors="replace")
    except:pass
    return False,"상품 조회 검색창 탐색 실패"

def _price_cards(driver,limit=50):
    from selenium.webdriver.common.by import By
    # Generic card extraction that keys off visible price text.
    selectors=["article","li","div[class*='product']","div[class*='item']","div[class*='card']","tr"]
    out=[];seen=set()
    for sel in selectors:
        try:els=driver.find_elements(By.CSS_SELECTOR,sel)
        except:continue
        for e in els:
            try:
                if not e.is_displayed():continue
                txt=" ".join((e.text or "").split())
                if len(txt)<8 or len(txt)>1800:continue
                pm=PRICE_RE.search(txt)
                if not pm:continue
                price=int(pm.group(1).replace(",",""))
                if not 100<=price<=100000000:continue
                lines=[x.strip() for x in (e.text or "").splitlines() if x.strip()]
                # remove obvious price-only lines before choosing product name
                candidates=[x for x in lines[:10] if not PRICE_RE.fullmatch(x) and len(x)>=3]
                name=max(candidates,key=len) if candidates else txt[:150]
                href=""
                try:
                    a=e.find_element(By.CSS_SELECTOR,"a[href]");href=a.get_attribute("href") or ""
                except:pass
                key=(name,price,href)
                if key in seen:continue
                seen.add(key);out.append({"element":e,"text":txt,"name":name,"price":price,"url":href})
                if len(out)>=limit:return out
            except:pass
    return out

def search_cards(driver,query,limit=20):
    from selenium.webdriver.common.keys import Keys
    ok,msg=navigate_lookup(driver)
    if not ok:raise RuntimeError(msg)
    field=_find_search(driver,4)
    if not field:raise RuntimeError("토스 상품검색 입력창 없음")
    try:
        field.click();field.send_keys(Keys.CONTROL,"a");field.send_keys(Keys.BACKSPACE)
        field.send_keys(query);field.send_keys(Keys.ENTER)
    except Exception as e:raise RuntimeError("토스 상품 조회 입력 실패: "+str(e))
    end=time.time()+12
    cards=[]
    while time.time()<end:
        cards=_price_cards(driver,limit)
        if cards:return cards
        time.sleep(.25)
    return cards

def _capture(card,driver,evdir):
    evdir=Path(evdir);evdir.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime("%Y%m%d_%H%M%S")
    evidence=evdir/f"토스쉐어링크_동일카드_{stamp}.png"
    try:card["element"].screenshot(str(evidence))
    except:driver.save_screenshot(str(evidence))
    image=None
    try:
        imgs=card["element"].find_elements("css selector","img")
        imgs=[x for x in imgs if x.is_displayed() and x.size.get("width",0)>=80 and x.size.get("height",0)>=80]
        if imgs:
            image=evdir/f"토스쉐어링크_제품사진_{stamp}.png";imgs[0].screenshot(str(image))
    except:pass
    return str(evidence),str(image) if image else None

def _share_url(driver):
    from selenium.webdriver.common.by import By
    for sel in ["input[value^='http']","textarea","a[href*='toss.im']"]:
        try:
            for e in driver.find_elements(By.CSS_SELECTOR,sel):
                if not e.is_displayed():continue
                v=e.get_attribute("value") or e.get_attribute("href") or (e.text or "")
                if v.startswith("http") and "toss.im" in v:return v
        except:pass
    for label in ["쉐어링크","링크 만들기","링크 생성","링크 복사","공유하기","공유"]:
        try:els=driver.find_elements(By.XPATH,f'//*[contains(normalize-space(.),"{label}")]')
        except:els=[]
        for e in els[:8]:
            try:
                if e.is_displayed() and e.is_enabled():
                    e.click();time.sleep(.5)
                    for sel in ["input[value^='http']","textarea","a[href*='toss.im']"]:
                        for x in driver.find_elements(By.CSS_SELECTOR,sel):
                            v=x.get_attribute("value") or x.get_attribute("href") or (x.text or "")
                            if v.startswith("http") and "toss.im" in v:return v
            except:pass
    return None

def fetch(driver,target_name,evdir):
    try:cards=search_cards(driver,target_name,40)
    except Exception as e:
        return {"site":"토스쇼핑","price":None,"product_name":"","image_path":None,"match":0,
                "reason":str(e),"source":"sharelink_pc"}
    scored=[]
    for c in cards:
        score,_=strict_product_match(c["text"],target_name)
        if score>0:scored.append((score,c))
    scored.sort(key=lambda x:(-x[0],x[1]["price"]))
    if not scored or scored[0][0]<0.55:
        return {"site":"토스쇼핑","price":None,"product_name":"","image_path":None,"match":0,
                "reason":"토스 쉐어링크 동일상품 검증 실패","source":"sharelink_pc"}
    score,card=scored[0]
    evidence,image=_capture(card,driver,evdir)
    share=None
    try:
        card["element"].click();time.sleep(.6);share=_share_url(driver)
    except:pass
    try:driver.get(HOME);time.sleep(.3)
    except:pass
    return {"site":"토스쇼핑","price":card["price"],"product_name":card["name"],
            "image_path":image,"match":score,"evidence":evidence,
            "url":share or card.get("url",""),"share_url":share,"source":"sharelink_pc"}
