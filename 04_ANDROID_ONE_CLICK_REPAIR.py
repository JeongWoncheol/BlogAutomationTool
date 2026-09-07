from pathlib import Path
import os, sys, shutil, subprocess, time, urllib.request, zipfile, json, socket

ROOT=Path(__file__).resolve().parent
TOOLS=ROOT/"tools"; LOGS=ROOT/"logs"
TOOLS.mkdir(exist_ok=True); LOGS.mkdir(exist_ok=True)
logfile=LOGS/"android_repair.log"

def log(s):
    print(s, flush=True)
    with logfile.open("a",encoding="utf-8") as f: f.write(s+"\n")

def run(args, timeout=180, env=None):
    log("$ "+" ".join(map(str,args)))
    p=subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     timeout=timeout, env=env or os.environ.copy(), shell=False)
    raw=p.stdout or b""
    for enc in ("utf-8","cp949","euc-kr"):
        try: out=raw.decode(enc); break
        except UnicodeDecodeError: pass
    else: out=raw.decode("utf-8","replace")
    if out.strip(): log(out.rstrip())
    return p.returncode,out

def which_any(names):
    for n in names:
        x=shutil.which(n)
        if x:return x
    return None

def adb_path():
    candidates=[]
    for k in ("ANDROID_SDK_ROOT","ANDROID_HOME"):
        if os.environ.get(k): candidates.append(Path(os.environ[k])/"platform-tools"/"adb.exe")
    candidates += [
        Path.home()/"AppData/Local/Android/Sdk/platform-tools/adb.exe",
        Path("C:/Android/platform-tools/adb.exe"),
        Path("C:/platform-tools/adb.exe"),
        TOOLS/"platform-tools"/"adb.exe",
    ]
    w=shutil.which("adb")
    if w:candidates.insert(0,Path(w))
    for p in candidates:
        if p.exists():return p
    return None

def install_adb():
    p=adb_path()
    if p:return p
    log("[AUTO] ADB 없음 -> Google Platform-Tools 설치")
    url="https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    z=TOOLS/"platform-tools.zip"
    urllib.request.urlretrieve(url,z)
    dest=TOOLS/"platform-tools"
    if dest.exists():shutil.rmtree(dest)
    with zipfile.ZipFile(z) as f:f.extractall(TOOLS)
    p=dest/"adb.exe"
    if not p.exists():raise RuntimeError("ADB 설치 후 adb.exe를 찾지 못했습니다.")
    return p

def appium_cmd():
    candidates=[
        shutil.which("appium"),
        str(Path(os.environ.get("APPDATA",""))/"npm"/"appium.cmd"),
        r"C:\Users\%s\AppData\Roaming\npm\appium.cmd"%os.environ.get("USERNAME","")
    ]
    for x in candidates:
        if x and Path(x).exists():return x
    return None

def npm_cmd():
    for x in (shutil.which("npm"),r"C:\Program Files\nodejs\npm.cmd"):
        if x and Path(x).exists():return x
    return None

def server_up():
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:4723/status",timeout=1) as r:
            return r.status==200
    except Exception:return False

def main():
    logfile.write_text("",encoding="utf-8")
    log("=== Android / Toss Repair v6.2 ===")

    # ADB
    adb=install_adb()
    log(f"[PASS] ADB: {adb}")
    sdk=adb.parent.parent
    os.environ["ANDROID_HOME"]=str(sdk)
    os.environ["ANDROID_SDK_ROOT"]=str(sdk)
    os.environ["PATH"]=str(adb.parent)+os.pathsep+os.environ.get("PATH","")

    # Node/npm/Appium
    node=which_any(["node.exe","node"])
    npm=npm_cmd()
    if not node or not npm:
        raise RuntimeError("Node.js/npm이 없습니다. Node.js LTS 설치 후 다시 실행하세요.")
    log(f"[PASS] Node: {node}")
    log(f"[PASS] npm: {npm}")
    appium=appium_cmd()
    if not appium:
        rc,_=run([npm,"install","-g","appium"],timeout=300)
        if rc:raise RuntimeError("Appium 설치 실패")
        appium=appium_cmd()
    if not appium:raise RuntimeError("Appium CLI 경로 확인 실패")
    log(f"[PASS] Appium: {appium}")

    # Driver: query once, no batch pipe/parentheses.
    rc,out=run([appium,"driver","list","--installed"],timeout=60)
    installed=("uiautomator2" in out.lower())
    if installed:
        log("[PASS] UiAutomator2 이미 설치됨 - 재설치하지 않음")
    else:
        log("[AUTO] UiAutomator2 설치")
        rc,out=run([appium,"driver","install","uiautomator2"],timeout=300)
        if rc:raise RuntimeError("UiAutomator2 설치 실패")
        rc,out=run([appium,"driver","list","--installed"],timeout=60)
        if "uiautomator2" not in out.lower():raise RuntimeError("UiAutomator2 설치 검증 실패")
        log("[PASS] UiAutomator2 설치/검증 완료")

    # ADB server/device state
    run([str(adb),"start-server"],timeout=30)
    rc,out=run([str(adb),"devices"],timeout=30)
    states=[]
    for line in out.splitlines():
        if "\t" in line:
            serial,state=line.split("\t",1); states.append((serial.strip(),state.strip()))
    if not states:
        log("[WAIT] Android 기기가 아직 연결되지 않았습니다.")
        log("       휴대폰: 개발자 옵션 > USB 디버깅 ON > USB 데이터 케이블 연결")
        log("       RSA 팝업이 나오면 '이 컴퓨터에서 항상 허용' 후 허용")
    elif any(s=="unauthorized" for _,s in states):
        log("[WAIT] 기기가 unauthorized 상태입니다. 휴대폰 화면에서 RSA USB 디버깅을 허용하세요.")
    elif any(s=="device" for _,s in states):
        log("[PASS] Android 기기 연결 완료")
    else:
        log("[WARN] ADB 상태: "+repr(states))

    # Appium server: start even if phone absent, so diagnostic no longer gets 10061.
    if server_up():
        log("[PASS] Appium 서버 이미 실행 중")
    else:
        log("[AUTO] Appium 서버 시작: 127.0.0.1:4723")
        env=os.environ.copy()
        out_file=(LOGS/"appium_server.log").open("ab")
        flags=0
        if os.name=="nt":
            flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"CREATE_NO_WINDOW",0)
        subprocess.Popen([appium,"--address","127.0.0.1","--port","4723","--base-path","/"],
                         stdout=out_file,stderr=subprocess.STDOUT,env=env,
                         creationflags=flags)
        for _ in range(30):
            if server_up():break
            time.sleep(.5)
        if not server_up():
            raise RuntimeError("Appium 서버 시작 실패. logs/appium_server.log 확인")
        log("[PASS] Appium 서버 4723 정상")

    log("")
    log("=== 설치 단계 완료 ===")
    if not any(s=="device" for _,s in states):
        log("[NEXT] 이제 휴대폰만 연결/승인한 뒤 05_ANDROID_TOSS_DIAGNOSTIC.cmd 실행")
    else:
        log("[NEXT] 05_ANDROID_TOSS_DIAGNOSTIC.cmd 실행")
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except Exception as e:
        log("[FAIL] "+str(e))
        log("상세 로그: "+str(logfile))
        sys.exit(1)
