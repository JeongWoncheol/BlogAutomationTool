# -*- coding: utf-8 -*-
from modules import naver_image_api as api
print('=== NAVER API HUB 이미지 검색 테스트 ===')
h=api.health();print(h.get('message'));print('Endpoint:',h.get('endpoint'))
if not api.ready():raise SystemExit('92_NAVER_IMAGE_API_SETUP.cmd를 먼저 실행하세요.')
query=input('테스트 검색어 (Enter=로지텍 MX Master 3S): ').strip() or '로지텍 MX Master 3S'
try:rows=api.search(query,10,sort='sim',filter_value='large')
except Exception as exc:raise SystemExit('FAIL: '+str(exc))
print('응답 이미지:',len(rows),'건')
for row in rows[:5]:print('-',row.get('name'),f"/ {row.get('width')}x{row.get('height')}",'/ URL:','YES' if row.get('image_url') else 'NO')
if not rows:raise SystemExit('FAIL: 이미지 검색 결과가 0건입니다.')
print('PASS: NAVER API HUB 이미지 검색 응답 정상')
