# -*- coding: utf-8 -*-
from getpass import getpass
from modules import toss_sharelink_api as api

print("=== 토스 Sharelink Creator Open API 설정 v7.47.6 ===")
print("공식 문서 흐름을 그대로 사용합니다.")
print("1) POST", api.DEFAULT_TOKEN_PATH)
print("   grant_type=client_credentials")
print("   scope=sharelink:read  (상품 조회 전용)")
print("2) GET", api.DEFAULT_BASE + api.DEFAULT_HEALTH_PATH)
print("3) GET", api.DEFAULT_BASE + api.DEFAULT_BEST_SELLING_PATH + "?size=5")
print("※ 링크 발급 기능을 추가할 때만 scope에 sharelink:write를 함께 사용합니다.")
print()

pip=api.public_ip(4)
if pip:
    print("현재 이 PC의 외부 공인 IP:",pip)
    print("-> Sharelink Creator 어드민의 출발지 IP에는 이 공인 IP를 등록하세요.")
else:
    print("현재 공인 IP 자동조회 실패. 브라우저에서 '내 공인 IP'를 확인해 주세요.")
print("※ 192.168.x.x / 10.x.x.x / 172.16~31.x.x는 공인 IP가 아닙니다.\n")

access=getpass("Sharelink Access Key (입력 문자는 화면에 보이지 않음): ").strip()
secret=getpass("Sharelink Secret Key (입력 문자는 화면에 보이지 않음): ").strip()
publisher=input("Publisher UUID/ID (없으면 Enter): ").strip()
categories=input("Category ID들 (알면 쉼표 구분, 모르면 Enter): ").strip()

p=api.save_credentials(access,secret,publisher,"",api.DEFAULT_BASE,api.DEFAULT_TOKEN_PATH,
                       api.DEFAULT_FEED_PATH,api.DEFAULT_SCOPE,categories,
                       api.DEFAULT_CATEGORIES_PATH,api.DEFAULT_BEST_SELLING_PATH)
print("\n저장 완료:",p)
print("저장 scope:",api.DEFAULT_SCOPE)

print("\n[1/3] OAuth 액세스 토큰 발급 테스트 중...")
try:
    t=api.token_test()
    print("PASS: OAuth 토큰 발급 정상")
    print("OAuth mode:",t.get("oauth_mode"))
    print("발급/요청 scope:",t.get("scope"))
except Exception as e:
    print("FAIL: OAuth 토큰 발급 실패")
    print(str(e))
    raise SystemExit(3)

print("\n[2/3] Sharelink /openapi/health 확인 중...")
h=api.sharelink_health_test(auto_scope=False)
if not h.get("ok"):
    print("FAIL: /health 연결 실패")
    print("HTTP:",h.get("http_status") or "-")
    if h.get("event_id"):print("x-toss-event-id:",h.get("event_id"))
    print("서버 응답:",str(h.get("body") or h.get("reason") or "")[:1200])
    print("\n확인사항: 토큰 요청에 scope=sharelink:read가 포함됩니다. 403/ACCESS_DENIED라면 등록 공인 IP를 확인하세요.")
    print("진단 파일:",api.write_connection_diagnostic({"health":h}))
    raise SystemExit(4)
print("PASS: Sharelink /health 정상")
print("사용 scope:",h.get("scope") or api.DEFAULT_SCOPE)
print("서버 응답:",h.get("response"))

print("\n[3/3] 베스트 상품 5개 조회 중...")
try:
    rows=api.best_selling(5,True)
    if not rows:raise RuntimeError("상품 items가 0건입니다.")
    print("PASS: /openapi/products/best-selling?size=5 정상 ·",len(rows),"건")
    category_ids=[]
    for x in rows:
        for cid in x.get("category_ids") or []:
            if cid not in category_ids:category_ids.append(cid)
        print(" -",x.get("rank"),x.get("name"),x.get("price"),x.get("category_ids"))
    if category_ids:
        print("응답에서 확인된 categoryIds:",", ".join(category_ids[:20]))
except Exception as e:
    print("FAIL: 베스트 상품 API 연결 실패")
    print(str(e))
    print("진단 파일:",api.write_connection_diagnostic({"product_error":str(e)}))
    raise SystemExit(5)

print("\n설정 완료. 공식 문서의 토큰 -> health -> best-selling 3단계가 모두 PASS했습니다.")
