# -*- coding: utf-8 -*-
from pathlib import Path
import hashlib, json
from PIL import Image

ALLOWED_SOURCE_TYPES={"real_product","real_listing","user_photo"}

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def validate_photo_records(records):
    seen=set(); valid=[]; rejected=[]
    for r in records:
        p=Path(r.get("path",""))
        why=[]
        if r.get("source_type") not in ALLOWED_SOURCE_TYPES: why.append("실제 사진 출처가 아님")
        if not p.exists(): why.append("파일 없음")
        if p.exists():
            try:
                im=Image.open(p); w,h=im.size
                if w<300 or h<300: why.append("해상도 부족")
                digest=sha256(p)
                if digest in seen: why.append("중복 이미지")
                seen.add(digest)
            except Exception: why.append("이미지 판독 실패")
        if why: rejected.append({**r,"reason":", ".join(why)})
        else: valid.append(r)
    return valid,rejected
