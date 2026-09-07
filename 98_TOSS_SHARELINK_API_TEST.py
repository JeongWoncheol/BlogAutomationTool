# -*- coding: utf-8 -*-
from modules import toss_sharelink_api as api

print("=== Toss Sharelink 공식 3단계 연결 테스트 ===")
try:
    t=api.token_test();print("[1/3] OAuth PASS · scope:",t.get("scope"))
except Exception as e:
    print("[1/3] OAuth FAIL:",e);raise SystemExit(2)
h=api.sharelink_health_test(auto_scope=False)
if not h.get("ok"):
    print("[2/3] /health FAIL:",h);raise SystemExit(3)
print("[2/3] /health PASS:",h.get("response"))
try:
    rows=api.best_selling(5,True)
except Exception as e:
    print("[3/3] best-selling FAIL:",e);raise SystemExit(4)
print("[3/3] best-selling PASS ·",len(rows),"건")
for x in rows:print(" -",x.get("rank"),x.get("name"),x.get("price"),x.get("category_ids"))
