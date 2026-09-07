# -*- coding: utf-8 -*-
from pathlib import Path
import json, getpass
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data';DATA.mkdir(exist_ok=True)
cred_path=DATA/'openai_api_credentials.json'
settings_path=DATA/'settings.json'
old={}
try:
    old=json.loads(cred_path.read_text(encoding='utf-8'))
except Exception:pass
print('=== OpenAI API 설정 ===')
print('API 키는 이 PC의 data/openai_api_credentials.json에만 저장됩니다.')
print('OpenAI Platform에서 발급한 API key를 입력하세요. 기존 키를 유지하려면 Enter만 누르세요.')
key=getpass.getpass('OpenAI API key: ').strip()
if not key:key=str(old.get('api_key') or '').strip()
if not key:
    raise SystemExit('API key가 없어 설정을 취소했습니다.')
model_default='gpt-5.6-sol'
try:
    cfg=json.loads(settings_path.read_text(encoding='utf-8'))
    model_default=str(old.get('model') or cfg.get('openai_model') or model_default)
except Exception:
    cfg={}
model=input(f'Model [{model_default}]: ').strip() or model_default
cred={'api_key':key,'model':model}
cred_path.write_text(json.dumps(cred,ensure_ascii=False,indent=2),encoding='utf-8')
if settings_path.exists():
    cfg=json.loads(settings_path.read_text(encoding='utf-8'))
    cfg['llm_provider']='openai'
    cfg['llm_provider_priority']=['openai','ollama','safe_fallback']
    cfg['openai_model']=model
    settings_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
print('\n저장 완료:',cred_path)
print('OpenAI는 선택형 유료 fallback입니다. 기본 자동사용은 OFF이며 Ollama가 1순위입니다.')
