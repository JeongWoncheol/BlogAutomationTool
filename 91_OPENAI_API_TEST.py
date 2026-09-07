# -*- coding: utf-8 -*-
from pathlib import Path
import json, urllib.request, urllib.error
ROOT=Path(__file__).resolve().parent
cred_path=ROOT/'data'/'openai_api_credentials.json'
settings_path=ROOT/'data'/'settings.json'
obj={}
try:obj=json.loads(cred_path.read_text(encoding='utf-8'))
except Exception:pass
try:cfg=json.loads(settings_path.read_text(encoding='utf-8'))
except Exception:cfg={}
key=str(obj.get('api_key') or cfg.get('openai_api_key') or '').strip()
model=str(obj.get('model') or cfg.get('openai_model') or 'gpt-5.6-sol').strip()
if not key:raise SystemExit('OpenAI API key가 없습니다. 90_OPENAI_API_SETUP.cmd를 먼저 실행하세요.')
url='https://api.openai.com/v1/models/'+model
req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
try:
    with urllib.request.urlopen(req,timeout=20) as r:
        data=json.loads(r.read().decode('utf-8','ignore'))
    print('OPENAI API READY')
    print('model:',data.get('id') or model)
    print('기본 자동작성은 Ollama가 1순위입니다. OpenAI는 settings.json의 openai_auto_enabled=true일 때만 자동사용됩니다.')
except urllib.error.HTTPError as e:
    try:body=e.read().decode('utf-8','ignore')
    except Exception:body=''
    raise SystemExit(f'OpenAI API 테스트 실패 HTTP {e.code}: {body[:800]}')
