# -*- coding: utf-8 -*-
from pathlib import Path
import json,getpass
ROOT=Path(__file__).resolve().parent;out=ROOT/'data'/'naver_image_api_credentials.json'
print('=== NAVER API HUB 이미지 검색 API 설정 ===')
print('이미 설정했다면 다시 입력할 필요가 없습니다. 키를 변경할 때만 실행하세요.')
print('Client Secret은 입력 중 화면에 표시되지 않습니다.')
cid=input('NAVER API HUB Client ID: ').strip();sec=getpass.getpass('NAVER API HUB Client Secret: ').strip()
if not cid or not sec:raise SystemExit('Client ID/Secret이 비어 있어 저장하지 않았습니다.')
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'client_id':cid,'client_secret':sec,'api_mode':'naver_api_hub'},ensure_ascii=False,indent=2),encoding='utf-8')
print('저장 완료:',out)
print('사용 API: /search/v1/image · filter=large · sort=sim')
