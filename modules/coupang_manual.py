# -*- coding: utf-8 -*-
"""
Manual-safe Coupang evidence importer.
Use when Coupang blocks Selenium search but the user can browse normally.
It never bypasses access controls. User manually supplies a screenshot and price.
"""
from pathlib import Path
import json, shutil, time
from .common import EVIDENCE, strict_product_match

def import_manual(product_no, target_name, screenshot_path, product_name, price):
    score,detail=strict_product_match(product_name,target_name)
    if score < 0.55:
        raise RuntimeError(f"동일상품 검증 실패: score={score:.2f}, {detail}")
    src=Path(screenshot_path)
    if not src.exists(): raise RuntimeError("스크린샷 파일이 없습니다.")
    evdir=EVIDENCE/f"{int(product_no):02d}"
    evdir.mkdir(parents=True,exist_ok=True)
    dst=evdir/"쿠팡_수동검증_상품명_가격_증거.png"
    shutil.copy2(src,dst)
    return {
        "site":"쿠팡","price":int(price),"product_name":product_name,
        "image_path":None,"match":score,"evidence":str(dst),
        "source":"manual_user_verified","checked_at":time.strftime("%Y-%m-%d %H:%M:%S")
    }
