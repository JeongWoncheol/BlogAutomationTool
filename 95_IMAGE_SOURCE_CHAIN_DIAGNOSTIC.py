# -*- coding: utf-8 -*-
from pathlib import Path
import csv, sqlite3, json
from modules.common import DB, OUTPUTS
from modules import naver_image_api, coupang_partners_api

print('=== v8.08.48 이미지 소스 체인 진단 ===')
print('NAVER:', naver_image_api.health().get('message'))
print('Coupang:', coupang_partners_api.health().get('message'))
if not naver_image_api.ready():
    raise SystemExit('NAVER API HUB 이미지 키가 현재 폴더에 없습니다. 92 설정 또는 이전 버전 설정 승계를 확인하세요.')
con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
rows=con.execute("""SELECT id,product_no,name,status,COALESCE(image_verified_count,0) AS image_verified_count
                    FROM products WHERE COALESCE(already_posted,0)=0
                    ORDER BY CASE WHEN COALESCE(image_verified_count,0)<3 THEN 0 ELSE 1 END, COALESCE(updated_at,'') DESC, id DESC LIMIT 12""").fetchall();con.close()
out=[]
for i,r in enumerate(rows,1):
    print(f'[{i}/{len(rows)}] TOP {r["product_no"]} {r["name"][:60]}')
    try:
        matches,errs,diag=naver_image_api.exact_matches_with_diagnostic(r['name'],max_queries=5,threshold=.72)
        print('  raw=',diag.get('raw_seen'),'exact=',len(matches),'identity_reject=',diag.get('identity_reject'),'model_reject=',diag.get('model_reject'),'errors=',len(errs))
        print('  top=', ' / '.join(x.get('name','')[:50] for x in matches[:3]) or '-')
        out.append({'TOP':r['product_no'],'상품명':r['name'],'현재사진':r['image_verified_count'],'NAVER_raw':diag.get('raw_seen',0),'NAVER_exact':len(matches),
                    'identity_reject':diag.get('identity_reject',0),'model_reject':diag.get('model_reject',0),'size_reject':diag.get('size_reject',0),
                    '오류':' | '.join(errs[-3:]),'상위후보':' | '.join(x.get('name','') for x in matches[:3])})
    except Exception as e:
        print('  ERROR:',e);out.append({'TOP':r['product_no'],'상품명':r['name'],'현재사진':r['image_verified_count'],'오류':str(e)})
OUTPUTS.mkdir(parents=True,exist_ok=True);p=OUTPUTS/'image_source_chain_diagnostic.csv'
fields=['TOP','상품명','현재사진','NAVER_raw','NAVER_exact','identity_reject','model_reject','size_reject','오류','상위후보']
with p.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    for r in out:w.writerow({k:r.get(k,'') for k in fields})
print('\n완료:',p)
