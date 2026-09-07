# -*- coding: utf-8 -*-
from getpass import getpass
from modules import coupang_partners_api as api
print('=== 쿠팡 Partners API 설정 (브라우저 없는 가격/이미지 조회) ===')
print('쿠팡 Partners API에서 발급받은 Access Key / Secret Key가 필요합니다.')
print('키가 없으면 그냥 Enter를 눌러 종료하세요. 프로그램은 540 수집 스냅샷 모드로 계속 동작합니다.\n')
a=input('Access Key: ').strip()
if not a:
    print('취소했습니다.');raise SystemExit(0)
s=getpass('Secret Key: ').strip()
if not s:
    print('Secret Key가 비어 있어 저장하지 않았습니다.');raise SystemExit(1)
p=api.save_credentials(a,s)
print('\n저장 완료:',p)
print('주의: 이 파일은 개인 인증정보입니다. 다른 사람에게 전달하거나 ZIP에 포함하지 마세요.')
print('다음으로 84_COUPANG_PARTNERS_API_TEST.cmd 를 실행해 확인하세요.')
