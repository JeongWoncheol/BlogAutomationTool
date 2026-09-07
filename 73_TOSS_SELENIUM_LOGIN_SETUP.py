# -*- coding: utf-8 -*-
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from modules.toss_multi_frame_collector import login_setup

print('=== v7.35 Toss Selenium 전용 로그인 설정 ===')
print('Toss 전용 persistent Chrome profile을 사용합니다.')
print('최초 1회만 로그인하면 다음 버전에서도 LOCALAPPDATA 프로필을 재사용합니다.\n')
raise SystemExit(0 if login_setup(300) else 2)

