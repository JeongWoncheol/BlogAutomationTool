# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess,os
from .common import *
def health():
    test=ROOT/"sharelink"/"Toss_Sharelink_Android_Emulator_06_Test"
    return {"ready":test.exists(),"name":"토스 쉐어링크","message":"Android/Appium 도구 폴더 존재" if test.exists() else "선택 기능: Android/Appium 도구 미설치"}
def run(context=None,progress=None):
    raise RuntimeError("토스 쉐어링크는 Android/Appium 선택 기능입니다. GUI의 선택기능 탭에서 실행하세요.")
