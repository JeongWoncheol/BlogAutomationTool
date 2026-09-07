# -*- coding: utf-8 -*-
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules.toss_mobile_adapter import diagnostic_report

r=diagnostic_report(True)
print("\n=== Android / Toss Deep Diagnostic ===")
for x in r["rows"]:
    print(f"[{x['status']}] {x['stage']}: {x['detail']}")
print("\nOVERALL:",r["overall"])
if r["overall"]=="WAIT_DEVICE":
    print("\n[NEXT] 프로그램/Appium 설치는 준비되어 있습니다.")
    print("[NEXT] 현재 필요한 것은 Android 기기 연결입니다.")
    print("[NEXT] 04B_CONNECT_ANDROID_DEVICE.cmd를 실행하고 휴대폰 USB 디버깅을 승인하세요.")
elif r["overall"]=="PASS":
    print("\n[PASS] 토스 Android 자동검증 준비 완료")
else:
    print("\n[CHECK] FAIL/WARN 항목을 확인하세요.")
print("Detailed logs: logs/android_diagnostic.log")
print("Evidence: evidence/_android_diagnostic/")
