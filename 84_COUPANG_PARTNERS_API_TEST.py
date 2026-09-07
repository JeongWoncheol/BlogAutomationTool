# -*- coding: utf-8 -*-
from modules import coupang_partners_api as api
print(api.health())
if not api.ready():
    print('SKIP: API 키 미설정');raise SystemExit(0)
q=input('테스트 상품명 [생수]: ').strip() or '생수'
rows=api.search(q,3,use_cache=False)
print('RESULT',len(rows))
for x in rows:
    print(x.get('name'),x.get('price'),x.get('image_url'))
if not rows:raise SystemExit(2)
print('PASS')
