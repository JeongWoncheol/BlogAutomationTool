# -*- coding: utf-8 -*-
from pathlib import Path
import json,time,re
from .common import ROOT,log,performance_settings

def _selenium():
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        return By,Keys
    except Exception as e:
        raise RuntimeError("Selenium이 설치되어 있지 않습니다. 01_INSTALL.cmd를 먼저 실행하세요.") from e

STATE=ROOT/"data"/"coupang_circuit.json"
HOME="https://www.coupang.com/"

def _state():
    if not STATE.exists():
        return {"blocked_until":0,"last_reason":"","last_blocked_at":0}
    try:return json.loads(STATE.read_text(encoding="utf-8"))
    except:return {"blocked_until":0,"last_reason":"","last_blocked_at":0}

def remaining_seconds():
    return max(0,int(_state().get("blocked_until",0)-time.time()))

def circuit_open():
    return remaining_seconds()>0

def trip(reason,cooldown_sec=600):
    now=time.time()
    obj={"blocked_until":now+cooldown_sec,"last_reason":str(reason),"last_blocked_at":now}
    STATE.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    log(f"[COUPANG][CIRCUIT OPEN] {cooldown_sec}s: {reason}")

def reset():
    STATE.write_text(json.dumps({"blocked_until":0,"last_reason":"","last_blocked_at":0},
                                ensure_ascii=False,indent=2),encoding="utf-8")

def access_denied(driver):
    try:
        txt=(driver.title+" "+driver.page_source[:25000]).lower()
        signatures=[
            "access denied",
            "you don't have permission to access",
            "errors.edgesuite.net",
            "reference #18.",
            "sorry! access denied",
            "forbidden"
        ]
        return any(x in txt for x in signatures)
    except:return False

def _find_search_input(driver,timeout=7):
    By,_=_selenium()
    selectors=[
        "input#headerSearchKeyword",
        "input[name='q']",
        "input[placeholder*='찾고 싶은 상품']",
        "input[placeholder*='검색']",
        "input[type='search']"
    ]
    end=time.time()+timeout
    while time.time()<end:
        for sel in selectors:
            for e in driver.find_elements(By.CSS_SELECTOR,sel):
                try:
                    if e.is_displayed() and e.is_enabled(): return e
                except:pass
        time.sleep(.15)
    return None

def search_via_home(driver,query):
    """
    Do not hammer /np/search directly.
    Navigate to Coupang home once, then use the site's visible search box.
    If Akamai returns Access Denied, open a 10-minute circuit breaker.
    """
    remain=remaining_seconds()
    if remain:
        raise RuntimeError(f"쿠팡 접근 제한 대기 중입니다. 약 {remain//60+1}분 후 재시도하세요.")

    try:
        driver.get(HOME)
    except Exception as e:
        if access_denied(driver):
            trip("쿠팡 홈 접근 시 Access Denied")
            raise RuntimeError("쿠팡 Access Denied가 감지되어 10분간 자동 요청을 중지했습니다.")
        raise

    if access_denied(driver):
        trip("쿠팡 홈에서 Access Denied")
        raise RuntimeError("쿠팡 Access Denied가 감지되었습니다. IP 보호를 위해 10분간 쿠팡 요청을 중지합니다.")

    field=_find_search_input(driver)
    if not field:
        raise RuntimeError("쿠팡 홈 검색창을 찾지 못했습니다. 페이지 구조가 변경되었을 수 있습니다.")

    _,Keys=_selenium()
    try:
        field.click()
        field.send_keys(Keys.CONTROL,"a")
        field.send_keys(Keys.BACKSPACE)
        field.send_keys(query)
        field.send_keys(Keys.ENTER)
    except Exception as e:
        raise RuntimeError("쿠팡 검색창 입력 실패: "+str(e))

    # Wait for navigation/results without fixed 3-second sleep.
    end=time.time()+int(performance_settings().get("search_page_timeout_sec",12))
    while time.time()<end:
        if access_denied(driver):
            try: save_block_evidence(driver,"search_blocked")
            except Exception: pass
            trip(f"검색 '{query}' 중 Access Denied")
            raise RuntimeError("쿠팡 검색 중 Access Denied가 감지되어 10분간 요청을 중지했습니다.")
        try:
            if len(driver.find_elements(_selenium()[0].CSS_SELECTOR,
               "li, article, div[class*='product'], div[class*='item'], div[class*='search-product']"))>0:
                return True
        except:pass
        time.sleep(.2)
    if access_denied(driver):
        trip(f"검색 '{query}' 결과 Access Denied")
        raise RuntimeError("쿠팡 Access Denied가 감지되어 10분간 요청을 중지했습니다.")
    return True

def status_text():
    s=_state()
    rem=remaining_seconds()
    if rem:
        return f"COUPANG CIRCUIT OPEN: {rem}s / {s.get('last_reason','')}"
    return "COUPANG CIRCUIT READY"


def save_block_evidence(driver, label="coupang_block"):
    ev=ROOT/"evidence"/"_coupang_diagnostic"
    ev.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime("%Y%m%d_%H%M%S")
    shot=ev/f"{label}_{stamp}.png"
    html=ev/f"{label}_{stamp}.html"
    try: driver.save_screenshot(str(shot))
    except Exception: pass
    try: html.write_text(driver.page_source,encoding="utf-8",errors="replace")
    except Exception: pass
    return str(shot),str(html)

def probe_search(driver, query="생수"):
    """
    Diagnostic wrapper that never dumps a traceback to the user.
    Returns a structured state:
      PASS: automation search works
      HOME_OK_SEARCH_BLOCKED: home works but automated search is denied
      HOME_BLOCKED: home itself is denied
      ERROR: selector/other failure
    """
    result={"status":"ERROR","message":"","evidence":[]}
    try:
        driver.get(HOME)
        time.sleep(.7)
        if access_denied(driver):
            ev=save_block_evidence(driver,"home_blocked")
            trip("쿠팡 홈 Access Denied")
            return {"status":"HOME_BLOCKED","message":"쿠팡 홈 자체가 Access Denied입니다.","evidence":list(ev)}
        try:
            search_via_home(driver,query)
        except RuntimeError as e:
            if access_denied(driver) or "Access Denied" in str(e):
                ev=save_block_evidence(driver,"search_blocked")
                return {
                    "status":"HOME_OK_SEARCH_BLOCKED",
                    "message":"쿠팡 홈은 열리지만 자동 검색 순간 Access Denied가 발생합니다. 자동 검색을 더 반복하지 않습니다.",
                    "evidence":list(ev)
                }
            return {"status":"ERROR","message":str(e),"evidence":[]}
        if access_denied(driver):
            ev=save_block_evidence(driver,"search_blocked")
            trip(f"검색 '{query}' 자동화 차단")
            return {"status":"HOME_OK_SEARCH_BLOCKED","message":"자동 검색 결과에서 Access Denied가 감지되었습니다.","evidence":list(ev)}
        reset()
        return {"status":"PASS","message":"쿠팡 홈/자동 검색 모두 정상입니다.","evidence":[]}
    except Exception as e:
        try: ev=save_block_evidence(driver,"probe_error")
        except Exception: ev=()
        return {"status":"ERROR","message":str(e),"evidence":list(ev)}

def automation_allowed():
    s=_state()
    # When the last reason is search automation blocking, do not keep hammering Coupang.
    return not circuit_open()
