# -*- coding: utf-8 -*-
from pathlib import Path
import os, sys, subprocess, shutil, time, json

ROOT=Path(__file__).resolve().parent
LOG=ROOT/"logs"/"android_device_connect.log"
LOG.parent.mkdir(exist_ok=True)

def write(msg):
    print(msg,flush=True)
    with LOG.open("a",encoding="utf-8") as f:
        f.write(msg+"\n")

def safe_text(raw):
    for enc in ("utf-8","cp949","euc-kr"):
        try:return raw.decode(enc)
        except UnicodeDecodeError:pass
    return raw.decode("utf-8","replace")

def adb_path():
    cands=[
        ROOT/"tools"/"platform-tools"/"adb.exe",
        Path.home()/"AppData/Local/Android/Sdk/platform-tools/adb.exe",
        Path("C:/Android/platform-tools/adb.exe"),
        Path("C:/platform-tools/adb.exe"),
    ]
    for env in ("ANDROID_SDK_ROOT","ANDROID_HOME"):
        if os.environ.get(env):
            cands.insert(0,Path(os.environ[env])/"platform-tools"/"adb.exe")
    w=shutil.which("adb")
    if w:cands.insert(0,Path(w))
    for p in cands:
        if p.exists():return p
    return None

def run(adb,*args,timeout=15):
    p=subprocess.run([str(adb),*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
    return p.returncode,safe_text(p.stdout or b"")

def states(adb):
    _,out=run(adb,"devices")
    found=[]
    for line in out.splitlines()[1:]:
        if "\t" in line:
            serial,state=line.split("\t",1)
            found.append((serial.strip(),state.strip()))
    return found,out

def main():
    LOG.write_text("",encoding="utf-8")
    write("=== Android Device Connection Assistant v6.4 ===")
    adb=adb_path()
    if not adb:
        write("[FAIL] ADB를 찾지 못했습니다. 04_ANDROID_ONE_CLICK_REPAIR.cmd를 먼저 실행하세요.")
        return 2
    write(f"[PASS] ADB: {adb}")

    run(adb,"kill-server")
    run(adb,"start-server")
    write("[PASS] ADB server restarted")

    deadline=time.time()+120
    last=None
    while time.time()<deadline:
        st,out=states(adb)
        normalized=tuple(st)
        if normalized!=last:
            write("[ADB DEVICES]")
            write(out.rstrip())
            last=normalized

        if any(s=="device" for _,s in st):
            serial=next(x for x,s in st if s=="device")
            write(f"[PASS] Android 연결 완료: {serial}")
            _,model=run(adb,"-s",serial,"shell","getprop","ro.product.model")
            _,api=run(adb,"-s",serial,"shell","getprop","ro.build.version.sdk")
            write(f"[PASS] Model: {model.strip()} / API: {api.strip()}")
            return 0

        if any(s=="unauthorized" for _,s in st):
            write("[WAIT] 휴대폰이 unauthorized 상태입니다.")
            write("       휴대폰 화면에서 'USB 디버깅을 허용하시겠습니까?' → '항상 허용' → 허용을 누르세요.")
        elif any(s=="offline" for _,s in st):
            write("[WAIT] 기기가 offline 상태입니다. USB 케이블을 다시 연결하고 USB 디버깅을 껐다 켜보세요.")
        else:
            write("[WAIT] Android 기기를 기다리는 중...")
            write("       1) 휴대폰 개발자 옵션 활성화")
            write("       2) USB 디버깅 ON")
            write("       3) 충전 전용이 아닌 데이터 USB 케이블 연결")
            write("       4) USB 용도에서 '파일 전송/Android Auto' 선택")
            write("       5) RSA 디버깅 팝업 허용")
        time.sleep(5)

    write("[WAIT_DEVICE] 120초 동안 연결된 Android를 찾지 못했습니다.")
    write("소프트웨어 설치 문제는 아닙니다. PC가 휴대폰/에뮬레이터를 ADB 장치로 아직 인식하지 못한 상태입니다.")
    return 3

if __name__=="__main__":
    sys.exit(main())
