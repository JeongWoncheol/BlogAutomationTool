# -*- coding: utf-8 -*-
from pathlib import Path
import json, re, time, os, shutil, subprocess, locale
from PIL import Image
from .common import ROOT, strict_product_match, log, identity_terms, critical_identity_tokens, signature_identity_tokens

CFG=ROOT/"data"/"toss_mobile.json"

def _run_text(args, timeout=12):
    """Windows-safe subprocess capture. Avoid cp949 reader-thread crashes."""
    p=subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     timeout=timeout, check=False)
    raw=p.stdout or b""
    for enc in ("utf-8","cp949","euc-kr",locale.getpreferredencoding(False)):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError,LookupError):
            pass
    return raw.decode("utf-8","replace")

def _candidate_adb_paths():
    home=Path.home()
    vals=[]
    for env in ("ANDROID_SDK_ROOT","ANDROID_HOME"):
        if os.environ.get(env):
            vals.append(Path(os.environ[env])/"platform-tools"/"adb.exe")
    vals += [
        home/"AppData"/"Local"/"Android"/"Sdk"/"platform-tools"/"adb.exe",
        Path("C:/Android/platform-tools/adb.exe"),
        Path("C:/platform-tools/adb.exe"),
        ROOT/"tools"/"platform-tools"/"adb.exe",
    ]
    w=shutil.which("adb")
    if w: vals.insert(0,Path(w))
    seen=set()
    for x in vals:
        s=str(x)
        if s.lower() not in seen:
            seen.add(s.lower()); yield x


def config():
    return json.loads(CFG.read_text(encoding="utf-8"))

def _adb_path():
    if os.name!="nt":
        ah=os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if ah:
            p=Path(ah)/"platform-tools"/"adb"
            if p.exists(): return str(p)
        return shutil.which("adb")
    for p in _candidate_adb_paths():
        if p.exists(): return str(p)
    return None

def _connected_device():
    adb=_adb_path()
    if not adb:return False,"adb 없음"
    try:
        out=_run_text([adb,"devices"],timeout=8)
        rows=[x for x in out.splitlines()[1:] if "\tdevice" in x]
        return bool(rows), (rows[0].split("\t")[0] if rows else "연결된 Android 없음")
    except Exception as e:return False,str(e)

def health():
    try:
        import appium
        from appium import webdriver
    except Exception:
        return {"ready":False,"state":"FAIL","name":"토스쇼핑 Android 가격·사진 검증","message":"Appium-Python-Client 미설치"}
    appium_cmd=shutil.which("appium") or str(Path(os.environ.get("APPDATA",""))/"npm"/"appium.cmd")
    if appium_cmd and not Path(appium_cmd).exists():
        appium_cmd=None
    ok,dev=_connected_device()
    if not appium_cmd:
        return {"ready":False,"state":"FAIL","name":"토스쇼핑 Android 가격·사진 검증","message":"Appium 서버 CLI 미설치"}
    if not ok:
        return {"ready":False,"state":"WAIT_DEVICE","name":"토스쇼핑 Android 가격·사진 검증",
                "message":"소프트웨어 준비됨 / Android 기기 연결 대기: "+dev}
    return {"ready":True,"state":"PASS","name":"토스쇼핑 Android 가격·사진 검증","message":"Android/Appium 준비됨"}

def _session():
    from appium import webdriver
    from appium.options.android import UiAutomator2Options
    c=config()
    opts=UiAutomator2Options()
    opts.platform_name="Android"
    opts.automation_name=c["automation_name"]
    opts.device_name=c["device_name"]
    opts.app_package=c["app_package"]
    opts.no_reset=bool(c["no_reset"])
    opts.new_command_timeout=int(c["new_command_timeout"])
    # Do not force an activity: use the already installed/logged-in app.
    return webdriver.Remote(c["appium_url"],options=opts)

def _click_by_text(driver,texts,timeout=12):
    from appium.webdriver.common.appiumby import AppiumBy
    end=time.time()+timeout
    while time.time()<end:
        for t in texts:
            xpaths=[
              f'//*[@text="{t}"]',
              f'//*[contains(@text,"{t}")]',
              f'//*[@content-desc="{t}"]',
              f'//*[contains(@content-desc,"{t}")]'
            ]
            for xp in xpaths:
                els=driver.find_elements(AppiumBy.XPATH,xp)
                for e in els:
                    try:
                        if e.is_displayed() and e.is_enabled():
                            e.click();time.sleep(1);return True
                    except:pass
        time.sleep(.5)
    return False

def _find_search_field(driver,timeout=15):
    from appium.webdriver.common.appiumby import AppiumBy
    end=time.time()+timeout
    while time.time()<end:
        # Native EditText first
        for by,val in [
          (AppiumBy.CLASS_NAME,"android.widget.EditText"),
          (AppiumBy.XPATH,'//*[contains(@text,"검색")]'),
          (AppiumBy.XPATH,'//*[contains(@content-desc,"검색")]')
        ]:
            for e in driver.find_elements(by,val):
                try:
                    if e.is_displayed() and e.is_enabled():
                        return e
                except:pass
        time.sleep(.5)
    return None

def _navigate_to_search(driver):
    c=config()
    # If already on a search-capable screen, use it.
    field=_find_search_field(driver,2)
    if field:return field
    # Try Shopping entry.
    _click_by_text(driver,c["navigation_texts"]["shopping"],10)
    field=_find_search_field(driver,3)
    if field:return field
    # Try search icon / accessibility label.
    _click_by_text(driver,c["navigation_texts"]["search"],10)
    field=_find_search_field(driver,8)
    if not field:
        raise RuntimeError("토스 앱에서 쇼핑 검색 입력창을 찾지 못했습니다. Toss UI 변경 가능성")
    return field

def _node_text(el):
    parts=[]
    for attr in ["text","content-desc"]:
        try:
            v=el.get_attribute(attr)
            if v:parts.append(v)
        except:pass
    return " ".join(parts)

def _candidate_containers(driver,product_name):
    from appium.webdriver.common.appiumby import AppiumBy
    # Search result names may be split across native descendants. Start from all text nodes
    # containing an important target token, then climb parents.
    terms=[x for x in re.findall(r"[0-9A-Za-z가-힣]+",product_name) if len(x)>=2]
    anchors=[]
    for t in terms[:5]:
        for xp in [f'//*[contains(@text,"{t}")]',f'//*[contains(@content-desc,"{t}")]']:
            try:anchors.extend(driver.find_elements(AppiumBy.XPATH,xp))
            except:pass
    containers=[]
    seen=set()
    for a in anchors:
        cur=a
        for _ in range(5):
            try:
                txt=_node_text(cur)
                # Native element text does not always include children: read descendant text via XPath.
                desc=cur.find_elements(AppiumBy.XPATH,'.//*')
                full=" ".join([txt]+[_node_text(x) for x in desc])
                key=(cur.id,full[:120])
                if key not in seen:
                    seen.add(key)
                    score,_=strict_product_match(full,product_name)
                    if score>0 and re.search(config()["price_regex"],full):
                        containers.append((score,cur,full))
                cur=cur.find_element(AppiumBy.XPATH,"..")
            except:break
    containers.sort(key=lambda x:x[0],reverse=True)
    return containers

def _fallback_product_crop(cardshot,out):
    """Crop the visual product-photo area from an Android result-card screenshot.

    UiAutomator sometimes exposes a composed card but no child ImageView. In that
    case the card screenshot is still trustworthy same-card evidence, so create a
    product-photo crop from the most likely square image region.
    """
    try:
        im=Image.open(cardshot).convert("RGB");w,h=im.size
        if w<160 or h<160:return None
        if w>=h*1.35:
            side=min(h,int(w*0.46));box=(0,0,side,side)
        else:
            side=min(w,int(h*0.62));box=((w-side)//2,0,(w-side)//2+side,side)
        c=im.crop(box)
        if c.width<140 or c.height<140:return None
        c.save(out,"JPEG",quality=95)
        return str(out)
    except Exception:
        return None

def fetch_product(driver,product_name,evdir,search_query=None):
    from appium.webdriver.common.appiumby import AppiumBy
    field=_navigate_to_search(driver)
    try:field.click();field.clear()
    except:pass
    field.send_keys(search_query or product_name)
    try:driver.press_keycode(66)  # ENTER / search
    except:pass
    time.sleep(4)

    candidates=_candidate_containers(driver,product_name)
    if not candidates:
        # Save failure evidence.
        fail=Path(evdir)/"토스쇼핑_검색결과_검증실패.png"
        driver.save_screenshot(str(fail))
        return {"site":"토스쇼핑","price":None,"product_name":"","image_path":None,"match":0,
                "evidence":str(fail),"reason":"동일상품+가격 카드 탐색 실패"}

    score,card,full=candidates[0]
    if score < float(config()["minimum_identity_score"]):
        fail=Path(evdir)/"토스쇼핑_동일상품점수미달.png"
        try:card.screenshot(str(fail))
        except:driver.save_screenshot(str(fail))
        return {"site":"토스쇼핑","price":None,"product_name":full[:160],"image_path":None,"match":score,
                "evidence":str(fail),"reason":"Product Identity Lock 점수 미달"}

    pm=re.search(config()["price_regex"],full)
    price=int(pm.group(1).replace(",","")) if pm else None

    evdir=Path(evdir);evdir.mkdir(parents=True,exist_ok=True)
    cardshot=evdir/"토스쇼핑_Android_동일카드_상품명_사진_가격.png"
    try:card.screenshot(str(cardshot))
    except:driver.save_screenshot(str(cardshot))

    # Try to capture the visible product image from within the SAME result card.
    image_path=None
    try:
        imgs=card.find_elements(AppiumBy.CLASS_NAME,"android.widget.ImageView")
        imgs=[x for x in imgs if x.is_displayed() and x.rect.get("width",0)>=100 and x.rect.get("height",0)>=100]
        if imgs:
            image_path=evdir/"토스쇼핑_Android_제품사진.png"
            imgs[0].screenshot(str(image_path))
    except:pass
    if not image_path:
        fallback=evdir/"토스쇼핑_Android_제품사진_카드크롭.jpg"
        fp=_fallback_product_crop(cardshot,fallback)
        if fp:image_path=Path(fp)

    return {"site":"토스쇼핑","price":price,"product_name":full[:220],"image_path":str(image_path) if image_path else None,
            "match":score,"evidence":str(cardshot),"source":"Android/Appium",
            "android_card_image_fallback":bool(image_path and Path(image_path).name.endswith("카드크롭.jpg"))}

def fetch(product_name,evdir,driver=None):
    own=driver is None
    d=driver or _session()
    try:return fetch_product(d,product_name,evdir)
    finally:
        if own:
            try:d.quit()
            except:pass



def core_search_query(product_name):
    """Short fallback query: brand/core line + strong signature/model tokens.

    Search can be broad, but final acceptance still uses the FULL target name.
    """
    terms=identity_terms(product_name)
    sig=signature_identity_tokens(product_name)
    crit=critical_identity_tokens(product_name)
    out=[]
    for x in (terms[:2]+sig+crit[:2]):
        x=str(x).strip()
        if x and x.lower() not in {y.lower() for y in out}: out.append(x)
    if len(out)<2:
        for x in terms[2:5]:
            if x and x.lower() not in {y.lower() for y in out}: out.append(x)
            if len(out)>=4: break
    return " ".join(out[:5]).strip() or str(product_name)

def open_session():
    """Public one-session entry used by batch price verification."""
    return _session()

def close_session(driver):
    try: driver.quit()
    except Exception: pass

def fetch_product_with_fallback(driver,product_name,evdir):
    """Full-name search first, then core-keyword search; exact target validation remains unchanged."""
    first=fetch_product(driver,product_name,evdir)
    first['query_used']=product_name
    if first.get('price') and float(first.get('match') or 0)>=float(config().get('minimum_identity_score',0.55)):
        return first
    core=core_search_query(product_name)
    if core and core.strip().lower()!=str(product_name).strip().lower():
        second=fetch_product(driver,product_name,evdir,search_query=core)
        second['query_used']=core
        second['fallback_from_fullname']=True
        # keep the more useful evidence if fallback also fails
        if second.get('price') or float(second.get('match') or 0)>float(first.get('match') or 0):
            return second
    return first

def diagnostic_report(save_file=True):
    """
    Deep Android/Appium/Toss diagnostics.
    Never guesses readiness. Every stage is logged with PASS/WARN/FAIL.
    """
    import socket, urllib.request, json as _json
    from datetime import datetime
    rows=[]
    def add(stage,status,detail):
        rows.append({"stage":stage,"status":status,"detail":str(detail),"time":datetime.now().isoformat(timespec="seconds")})
        log(f"[ANDROID DIAG][{status}] {stage}: {detail}")

    c=config()

    # 1) ADB
    adb=_adb_path()
    add("ADB 경로","PASS" if adb else "FAIL",adb or "adb 실행파일을 찾지 못함")
    ok,dev=_connected_device()
    add("Android 디바이스 연결","PASS" if ok else "WAIT",dev if ok else dev+" / 04B_CONNECT_ANDROID_DEVICE.cmd 실행")

    # 2) Node/npm/Appium CLI
    node_cmd=shutil.which("node")
    npm_cmd=shutil.which("npm")
    add("Node.js","PASS" if node_cmd else "FAIL",node_cmd or "Node.js 없음 - 04_SETUP_TOSS_ANDROID.cmd 실행")
    add("npm","PASS" if npm_cmd else "FAIL",npm_cmd or "npm 없음 - Node.js LTS 설치 필요")
    appium_cmd=shutil.which("appium")
    add("Appium CLI","PASS" if appium_cmd else "FAIL",appium_cmd or "Appium 없음 - 자동 셋업이 npm install -g appium 수행")
    if appium_cmd:
        try:
            out=_run_text([appium_cmd,"driver","list","--installed"],timeout=12)
            has_driver="uiautomator2" in out.lower()
            add("UiAutomator2 드라이버","PASS" if has_driver else "FAIL",out.strip()[:500] if has_driver else "uiautomator2 미설치 - 자동 셋업 실행 필요")
        except Exception as e:
            add("UiAutomator2 드라이버","WARN",e)

    # 3) Appium server
    server_ok=False
    try:
        with urllib.request.urlopen(c["appium_url"]+"/status",timeout=3) as r:
            body=r.read().decode("utf-8","ignore")
            server_ok=(r.status==200)
            add("Appium 서버","PASS" if server_ok else "FAIL",f"HTTP {r.status} {body[:180]}")
    except Exception as e:
        add("Appium 서버","FAIL",e)

    # 4) Device details
    if ok and adb:
        try:
            model=_run_text([adb,"shell","getprop","ro.product.model"],timeout=6).strip()
            api=_run_text([adb,"shell","getprop","ro.build.version.sdk"],timeout=6).strip()
            boot=_run_text([adb,"shell","getprop","sys.boot_completed"],timeout=6).strip()
            add("디바이스 모델","PASS",model)
            add("Android API","PASS",api)
            add("부팅 상태","PASS" if boot=="1" else "WARN",boot)
        except Exception as e:add("디바이스 정보","WARN",e)

        # 5) Toss package installed?
        try:
            out=_run_text([adb,"shell","pm","list","packages",c["app_package"]],timeout=8)
            installed=c["app_package"] in out
            add("Toss 앱 설치","PASS" if installed else "FAIL",out.strip() or "패키지 없음")
        except Exception as e:add("Toss 앱 설치","FAIL",e)

        # 6) Toss process/activity accessibility
        try:
            act=_run_text([adb,"shell","dumpsys","window","windows"],timeout=8)
            foreground=(c["app_package"] in act)
            add("Toss 전면 실행 여부","PASS" if foreground else "WARN","현재 전면앱에 Toss 패키지 감지" if foreground else "Toss 앱을 직접 열어 로그인 상태를 확인하세요.")
        except Exception as e:add("전면앱 확인","WARN",e)

    # 7) Appium session creation
    session_ok=False
    if server_ok and ok:
        try:
            d=_session()
            session_ok=True
            add("Appium UiAutomator2 세션","PASS","세션 생성 성공")
            # 8) App state
            try:
                src=d.page_source
                add("UI XML 접근","PASS" if len(src)>100 else "WARN",f"XML length={len(src)}")
                # Common auth/login hints. This is only heuristic, not definitive.
                login_terms=["로그인","휴대폰 번호","인증","가입"]
                found=[x for x in login_terms if x in src]
                if found:
                    add("Toss 로그인 상태","WARN","로그인/인증 관련 UI 감지: "+",".join(found))
                else:
                    add("Toss 로그인 상태","PASS","현재 UI에서 로그인 요구 문구 미감지")
            except Exception as e:add("UI XML 접근","FAIL",e)

            # 9) Shopping/search navigation
            try:
                field=_navigate_to_search(d)
                add("토스쇼핑 검색화면 접근","PASS","검색 입력창 탐색 성공")
            except Exception as e:
                add("토스쇼핑 검색화면 접근","FAIL",e)

            # Save screenshot/XML evidence
            try:
                ev=ROOT/"evidence"/"_android_diagnostic"
                ev.mkdir(parents=True,exist_ok=True)
                shot=ev/"android_diag_screen.png"
                xml=ev/"android_diag_page.xml"
                d.save_screenshot(str(shot))
                xml.write_text(d.page_source,encoding="utf-8")
                add("진단 증거 저장","PASS",f"{shot} / {xml}")
            except Exception as e:add("진단 증거 저장","WARN",e)

            try:d.quit()
            except:pass
        except Exception as e:
            add("Appium UiAutomator2 세션","FAIL",e)

    overall="PASS"
    if any(x["status"]=="FAIL" for x in rows): overall="FAIL"
    elif any(x["status"]=="WAIT" for x in rows): overall="WAIT_DEVICE"
    elif any(x["status"]=="WARN" for x in rows): overall="WARN"

    result={"overall":overall,"rows":rows}
    if save_file:
        out=ROOT/"logs"/"android_diagnostic.json"
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(_json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        text=ROOT/"logs"/"android_diagnostic.log"
        text.write_text("\n".join(f"[{r['status']}] {r['stage']}: {r['detail']}" for r in rows),encoding="utf-8")
    return result


# v5.5 reusable session helpers
def open_session():
    return _session()

def close_session(driver):
    try:driver.quit()
    except:pass
