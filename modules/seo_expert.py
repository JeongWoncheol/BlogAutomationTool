# -*- coding: utf-8 -*-
"""
Naver Blog SEO / editorial policy for this project.
Principles:
- Search intent first, not keyword stuffing.
- Real-photo-only content. No generated/illustrated lifestyle images.
- Product identity lock before image/price use.
- Mobile-first paragraphs.
- Avoid unverifiable first-person claims. Draft as review-style only when actual user experience/evidence exists.
"""
from dataclasses import dataclass, asdict
import re, json, random

INTENTS = {
    "구매형": ["추천","가격","최저가","구매","가성비"],
    "비교형": ["비교","차이","vs","대체","쿠팡","네이버","토스"],
    "후기형": ["후기","사용","써보니","실사용"],
    "문제해결형": ["사용법","어떻게","불편","해결","방법"],
    "스펙형": ["용량","사이즈","색상","모델","구성","개입"],
}

def classify_intent(text):
    scores={k:sum(1 for x in v if x.lower() in text.lower()) for k,v in INTENTS.items()}
    return max(scores,key=scores.get) if max(scores.values()) else "후기형"

def unique_keywords(name, candidates, max_count=5):
    """Return only candidate words not already used by the product/earlier terms.

    v7.38 treats whitespace/alphanumeric Korean words as individually reserved
    SEO tokens. A suggestion like 'MTC 살몬 마스크팩 사용법' therefore
    contributes only '사용법' when those product words are already present.
    """
    used={x.casefold() for x in re.findall(r"[0-9A-Za-z가-힣]+",str(name or ""))}
    out=[]
    for raw in candidates or []:
        fresh=[]
        for tok in re.findall(r"[0-9A-Za-z가-힣]+",str(raw or "")):
            key=tok.casefold()
            if not key or key in used:continue
            used.add(key);fresh.append(tok)
        if fresh:out.append(" ".join(fresh))
        if len(out)>=max(1,int(max_count)):break
    return out

def title_score(title, product_name, keywords):
    score=100; reasons=[]
    if len(title)>55: score-=12; reasons.append("모바일 제목이 길어 잘릴 가능성")
    if len(title)<18: score-=8; reasons.append("검색 의도 정보가 부족")
    # Repetition guard
    toks=re.findall(r"[0-9A-Za-z가-힣]+",title.lower())
    for t in set(toks):
        if len(t)>=2 and toks.count(t)>=3:
            score-=12; reasons.append(f"'{t}' 과반복")
    if product_name.split()[0].lower() not in title.lower():
        score-=18; reasons.append("제품 식별 핵심어 누락")
    if not any(k.lower() in title.lower() for k in keywords):
        score-=10; reasons.append("서브 검색어 미반영")
    return max(score,0),reasons

def mobile_format(text):
    # Keep short 1–2 sentence chunks; preserve headings/checklist.
    paras=[p.strip() for p in re.split(r"\n\s*\n",text) if p.strip()]
    out=[]
    for p in paras:
        if p.startswith(("💙","🤍","💛","❤️","✅","✔","📌","🔍")):
            out.append(p); continue
        s=re.split(r"(?<=[.!?요다죠])\s+",p)
        buf=[]
        for x in s:
            if x.strip(): buf.append(x.strip())
            if len(buf)>=2:
                out.append(" ".join(buf));buf=[]
        if buf: out.append(" ".join(buf))
    return "\n\n".join(out)

def qa_content(title, body, tags, photo_records=None):
    issues=[]; score=100
    if len(body)<700: issues.append("본문이 너무 짧음"); score-=15
    if len(body)>2200: issues.append("모바일 기준 본문이 과도하게 김"); score-=8
    # exact duplicated paragraph check
    ps=[re.sub(r"\s+"," ",p.strip()) for p in body.split("\n\n") if len(p.strip())>25]
    if len(ps)!=len(set(ps)): issues.append("중복 문단 존재"); score-=20
    if body.count("추천")>8: issues.append("'추천' 반복 과다"); score-=10
    if body.count("내돈내산")>2: issues.append("'내돈내산' 반복 과다"); score-=10
    if "토스쇼핑 쉐어링크 활동" not in body:
        issues.append("제휴 고지문 확인 필요"); score-=8
    if photo_records is not None:
        bad=[p for p in photo_records if p.get("source_type") not in ("real_product","real_listing","user_photo")]
        if bad: issues.append("실제 사진 외 이미지 포함"); score-=30
    return {"score":max(score,0),"issues":issues}

PHOTO_POLICY = {
    "generated_images": False,
    "illustrations": False,
    "synthetic_lifestyle": False,
    "allowed": ["실제 상품 사진","실제 판매 페이지 상품 사진","사용자가 제공한 실사용 사진"],
    "preferred_roles": ["대표 제품컷","제품 상세컷","구성/옵션컷","실제 사용컷(존재할 때)","판매페이지 가격 증거컷"],
    "duplicate_hash_check": True,
    "product_identity_lock": True,
}
