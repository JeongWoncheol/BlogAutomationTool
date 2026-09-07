# -*- coding: utf-8 -*-
from . import content_adapter, coupang_partners_api, toss_sharelink_api

def health():
    cp=coupang_partners_api.health(); ts=toss_sharelink_api.health()
    return {"ready":True,"name":"동일상품 사진 3장","message":"v8.08.48 · 쿠팡 API 대표이미지 → NAVER API HUB 이미지 exact 후보를 즉시 1~3장 채움 → 부족할 때만 쿠팡 상세 → 마지막 Google 원본상품페이지 재검증 · NAVER 쇼핑 API는 이미지 수집에 사용하지 않음 · 모델/용량/수량 hard gate + 판매자 꼬리문구 허용 balanced matcher + dHash/제품노출 검사 · 쿠팡 상세 장기대기/2회 재시도 제거 · 쿠팡 API "+("READY" if cp.get("ready") else "키 미설정")}

def run(context=None,progress=None):
    return content_adapter.run_images(context,progress)

def run_repairs(context=None,progress=None):
    return content_adapter.run_image_repairs(context,progress)
