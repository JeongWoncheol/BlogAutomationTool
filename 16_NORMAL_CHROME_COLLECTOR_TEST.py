# -*- coding: utf-8 -*-
import sys,time,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules.chrome_collector import collect,ensure_bridge,bridge_health

print("=== NORMAL CHROME COLLECTOR TEST v7.35 FIXED ===")
print("쿠팡·네이버 확장프로그램 경로만 검사합니다. 토스는 80번 Selenium 실전 테스트를 사용하세요.\n")
ensure_bridge()
if not (bridge_health() or {}).get("extension_online"):
    rc=subprocess.call(["cmd","/c","15_INSTALL_NORMAL_CHROME_EXTENSION.cmd"],cwd=str(ROOT))
    if rc!=0:raise SystemExit(2)
    for _ in range(15):
        time.sleep(1)
        if (bridge_health() or {}).get("extension_online"):break
if not (bridge_health() or {}).get("extension_online"):raise SystemExit(3)
tasks=[
 {"id":"normal-naver","site":"네이버쇼핑","query":"생수","target_name":"생수","mode":"price","limit":5,"delay_ms":3000},
 {"id":"normal-coupang","site":"쿠팡","query":"생수","target_name":"생수","mode":"price","limit":5,"delay_ms":3000},
]
res=collect(tasks,lambda d,t,m:print(f"[{d}/{t}] {m}"),timeout_sec=300)
ok=True
for r in res:
    found=bool(r.get("selected") or r.get("cards")) and r.get("status")=="ok"
    ok &= found
    print(("[PASS]" if found else "[FAIL]"),r.get("_site"),r.get("error",""))
raise SystemExit(0 if ok else 4)

