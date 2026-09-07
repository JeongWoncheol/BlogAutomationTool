# -*- coding: utf-8 -*-
from pathlib import Path
import urllib.parse
import json,sqlite3,urllib.request,urllib.error,time,re,os,shutil,mimetypes,random,threading,csv,hashlib,difflib
from PIL import Image,ImageChops,ImageFilter,ImageOps
from .common import *
from . import chrome_collector
from . import real_photo_policy
from . import naver_keywords
from . import coupang_partners_api
from . import naver_image_api
from . import toss_sharelink_api
from . import reference_blog_style
from . import ollama_local
from .wala_policy import REVIEW_REASON, is_wala_product, preserve_product_images
from .image_identity import IDENTITY_POLICY, image_evidence_error, page_identity_conflict
from .affiliate_identity import product_id as coupang_product_id, variant_conflicts

RULES="""네이버 모바일 블로그용 한국어 제품 원고를 작성한다.
가장 중요한 기준은 '실제 사람이 제품을 알아보고 자기 말로 정리한 글'처럼 읽히는 것이다.
광고문구, 설명서 문체, 반복되는 AI식 문장 구조를 피한다.

[고정 본문 양식]
- 사용자가 지정한 참고 글(https://blog.naver.com/jwonsbs/224392560087)의 모바일 후기 흐름을 기준으로 한다.
- 프로그램이 상단에 쿠팡 파트너스 상품 Sharelink를 별도 삽입하므로 본문에는 URL을 쓰지 않는다.
- 본문은 1100~1600자 정도. 모바일에서 한 줄 16~22자 정도로 읽히는 짧은 호흡을 사용한다.
- 문단은 1~2문장 중심이며 문단 사이 여백이 느껴져야 한다.
- 💙 🤍 💛 ❤️ 소제목 4개를 사용한다.
- 소제목과 장점 요약은 업로더가 굵게 + 정확한 글자 배경색 #fff8b2 로 적용한다.
- 마지막에는 구체적인 장점 5개와 자연스러운 추천 결론을 둔다.

[네이버 서브키워드]
- '소제목 키워드 계획'이 있으면 1~4번 소제목에 지정된 실제 네이버 자동완성 서브키워드를 각각 하나씩 자연스럽게 포함한다.
- 바로 아래 문단도 그 단어의 맥락과 이어져야 한다. 키워드를 억지로 붙이거나 '검색 키워드'라고 설명하지 않는다.

[사람 냄새 + 문장 다양성: 최우선]
- 독자 한 명에게 옆에서 얘기해주듯 편안한 존댓말로 쓴다. 설명서, 보도자료, 보고서처럼 딱딱하게 쓰지 않는다.
- 본문 대부분은 `~해요 / ~더라고요 / ~죠 / ~네요 / ~거든요 / ~같아요`처럼 자연스러운 대화형 종결을 사용한다. `~합니다 / ~됩니다 / ~있습니다 / ~적합합니다`가 연속으로 이어지지 않게 한다.
- 문장 길이를 일부러 똑같이 맞추지 않는다. 짧게 반응하는 문장과 조금 풀어서 설명하는 문장을 섞어 실제 사람이 말하는 호흡을 만든다.
- 매 상품마다 문장 시작, 접속어, 감탄 방식, 비교 방식, 결론 어휘를 새롭게 바꾼다.
- 이전 글에서 사용한 완성 문장을 그대로 재사용하지 않는다.
- 감탄은 글 전체에 2~4번 정도 자연스럽게 섞는다. `오!`, `아, 이 부분은 꽤 괜찮아요.`, `이건 눈에 들어오더라고요.`, `이 정도면 편하겠죠?`처럼 제품에서 실제로 눈에 띄는 지점에 반응하되 같은 감탄사를 반복하지 않는다.
- 질문도 1~2번 정도 자연스럽게 사용할 수 있다. 구매자가 실제로 고민할 법한 질문이어야 하며 억지 질문은 넣지 않는다.
- `따라서`, `즉`, `전반적으로`, `측면에서`, `해당 제품`, `사용자에게`, `활용할 수 있습니다`, `적합합니다`, `권장됩니다` 같은 AI/보고서식 표현은 특별한 이유가 없으면 쓰지 않는다.
- '생각보다 괜찮은데?', '오, 이건 괜찮은데?', '이게 은근히 중요하죠', '정리하면', '구매 후보에 넣어볼 만해요' 같은 상투문구를 반복 템플릿처럼 사용하지 않는다.
- 어떤 글은 차분한 비교형, 어떤 글은 생활밀착형, 어떤 글은 질문형 도입, 어떤 글은 짧은 상황형처럼 리듬을 바꾼다.
- 제품 이름 전체를 매 문단 반복하지 않는다. 제품명/핵심 상품명은 전체 본문에서 2~4회 정도만 쓰고 이후에는 '이 제품', '이 구성'처럼 자연스럽게 받는다.
- '선택 기준/옵션/규격/판매 단위/같은 조건/사용 장면/실용성' 같은 추상어로 문단을 채우지 않는다. 이런 말보다 실제로 손에 들고 쓰고 보관하고 씻고 입고 먹는 장면을 구체적으로 쓴다.
- 한 문단 안에서 장점만 나열하지 말고 `왜 편한지 → 실제 어느 순간에 체감되는지`가 이어지게 쓴다.
- 각 문단에는 현재 제품에서만 말할 수 있는 구체적인 내용이 최소 하나 있어야 한다. 모든 제품에 그대로 붙여도 말이 되는 문장은 피한다.
- 실제 사용 증거가 없는 상품은 `제가 써보니`, `직접 써봤는데`, `내돈내산` 같은 허위 경험을 만들지 않는다. 대신 `실제로 쓰는 장면을 떠올리면`, `이런 상황에서는`, `구성을 보면`처럼 사실 범위 안에서 자연스럽게 설명한다.
- 입력에 '최근 사용 문장 금지 목록'이 있으면 그 문장/유사 문장을 사용하지 않는다.
- 입력에 '이번 글 말투 계획'이 있으면 그 말투를 우선한다.

[네이버 서브키워드 연결 규칙]
- 서브키워드는 검색어를 억지로 제품 기능처럼 해석하지 않는다.
- '코스트코/다이소/이마트' 같은 유통처 키워드는 가격·묶음 구성·구매처 비교 맥락으로만 쓴다.
- 현재 제품이 비누인데 '샴푸'가 서브키워드라면 샴푸 기능을 비누에 붙이지 않는다. 같은 브랜드에서 함께 검색되는 다른 품목과의 구분/비교 맥락으로 자연스럽게 풀어낸다.
- 소제목에 키워드를 넣었다면 바로 아래 문단은 그 소제목이 왜 이 제품과 연결되는지 사람이 읽고 바로 이해할 수 있어야 한다.

[내용]
구매자가 관심 가질 이유, 실제 쓰임새, 제품명에서 확인되는 특징과 수량/용량, 비슷한 제품군과의 체감 차이, 구매 전 확인점, 사용·보관 팁을 제품 특성에 맞게 배치한다.
첫 두 문단부터 '이 제품을 왜 눈여겨볼 만한지'가 느껴져야 한다. 단순 쇼핑 조언이 아니라 실제 제품 이야기여야 한다.
입력의 '제품군 작성 힌트'를 반드시 반영하여 제품군에 맞는 감각과 사용 장면을 쓴다.
소비자가 읽다가 '아, 이건 내 생활에 잘 맞겠는데?'라고 느낄 정도로 장점이 구체적이어야 하지만 확인되지 않은 효능이나 성능은 과장하지 않는다.
실제로 사용했다는 증거가 없으면 '내돈내산했다/직접 써봤다'는 허위 경험을 만들지 않는다. 대신 실제 사용자가 공감할 만한 사용 흐름과 체감 포인트를 자연스럽게 묘사한다.

[구매전환/링크 클릭 유도: 중요]
- 광고처럼 밀어붙이지 말고 소비자가 "이 제품이면 내 상황에 맞겠다"고 스스로 결론 내리게 만든다.
- 첫 200자 안에 이 제품을 눈여겨볼 이유와 실제 생활에서 얻는 이점을 구체적으로 보여준다.
- 중간에는 비슷한 제품군과 비교했을 때 무엇을 확인하면 후회가 적은지 자연스럽게 설명한다.
- 결론은 독자의 상황에 맞는 추천 대상을 한 번 정리한 뒤, 현재 옵션·구성·가격은 글에 삽입되는 상품 링크에서 확인해보도록 자연스럽게 행동을 유도한다.
- 할인율, 최저가, 재고, 판매량, 성능, 효능처럼 입력에 없는 사실은 절대 지어내지 않는다. 조급함을 유발하는 허위 한정판매 문구도 금지한다.
- 링크 클릭을 유도하더라도 "무조건 사세요", "절대 후회 안 함" 같은 과장 표현은 쓰지 않는다.

[제목/태그도 AI 작성]
- title은 상품명으로 시작하고 반드시 `추천｜` 구분자를 포함한다. 네이버 자동완성 서브키워드를 자연스럽게 2~4개 반영하되 같은 단어를 반복하지 않는다.
- 제목 뒷부분은 제품마다 다른 구매동기·비교포인트·생활장면을 활용하여 반복감 없이 작성한다.
- tags는 30개 후보를 만들고, 상품명·네이버 자동완성·실제 구매의도가 드러나는 단어를 중심으로 구성한다. 쇼핑몰 이름과 무관 키워드는 넣지 않는다.

JSON만 반환:
{"title":"","intro":["",""],"sections":[{"heading":"","paragraphs":["",""]}],"advantages":[""],"conclusion":"","tags":[""]}"""

BANNED_TAG_WORDS=("쿠팡","토스쇼핑","네이버쇼핑","11번가","지마켓","옥션","온라인쇼핑","최저가")
PROMO_WORDS={"꼭","보세요","강추","특가","할인","증정","무료배송","공식","정품","선물","인기","베스트","추천","구매","후기","리뷰","광고"}
CATEGORY_TAGS={
 "생활용품":["생활용품","생활필수품","집안살림","생활템","살림템","생활용품추천"],
 "주방용품":["주방용품","주방템","주방살림","주방용품추천","키친템","주방필수품"],
 "패션잡화":["패션잡화","데일리룩","패션아이템","패션추천","데일리템","코디아이템"],
 "식품":["식품추천","먹거리추천","간식추천","식품후기","먹거리","식품리뷰"],
 "디지털/가전":["가전추천","디지털가전","가전제품","디지털기기","가전후기","전자제품"],
 "화장품/미용":["화장품추천","뷰티템","뷰티추천","화장품후기","스킨케어","메이크업"]
}


CONTENT_HISTORY = DATA / "content_phrase_history.json"
REFERENCE_BLOG_URL = "https://blog.naver.com/jwonsbs/224392560087"
CLICHE_PHRASES = [
    "생각보다 괜찮은데", "오, 이건 괜찮은데", "이게 은근히 중요", "정리하면",
    "구매 후보에 넣어볼 만", "처음 봤을 때 왜 눈에 들어왔", "비슷한 제품과 비교할 때는 여기서 갈",
    "이런 분이라면 구매 후보", "잘 골랐다", "마지막 선택이 쉬워요"
]
VOICE_PLANS = [
    "생활밀착형: 실제로 언제 꺼내 쓰게 될지 장면부터 떠올리며 편안하게 설명한다.",
    "차분한 비교형: 비슷한 제품과 무엇이 다른지 기준을 하나씩 짚되 딱딱한 표 설명처럼 쓰지 않는다.",
    "질문형 도입: 구매자가 실제로 고민할 법한 질문으로 시작하고 대화하듯 답을 풀어간다.",
    "관찰형: 상품명·구성·크기·사용 장면에서 눈에 띄는 점을 관찰하듯 담백하게 이어간다.",
    "실용 중심형: 보관·관리·휴대·사용 빈도처럼 생활에서 체감할 요소를 우선해서 설명한다.",
    "취향 선택형: 어떤 사람에게 잘 맞고 어떤 경우에는 다른 선택이 나을지 솔직하게 구분한다.",
    "짧은 에피소드형: 이 제품이 필요해지는 상황을 짧게 떠올린 뒤 제품 선택 포인트로 자연스럽게 넘어간다.",
    "친구 추천형: 너무 들뜨지 않고 친한 사람에게 장단점을 알려주듯 자연스럽게 말한다."
]

CONVERSION_ANGLES = [
    "불편해결형: 구매자가 현재 겪는 작지만 반복되는 불편을 먼저 짚고 제품이 어떤 점에서 선택 후보가 되는지 설명한다.",
    "비교결정형: 비슷한 상품을 여러 개 보고 있는 사람에게 마지막 선택 기준을 명확하게 만들어준다.",
    "생활장면형: 실제 집·회사·외출·식사·세면 등 제품이 쓰이는 한 장면을 구체적으로 보여주고 필요성을 연결한다.",
    "가성비판단형: 단순히 싸다고 말하지 않고 구성·사용빈도·관리편의까지 포함해 돈을 쓸 가치가 있는지 판단하게 한다.",
    "초보구매형: 처음 이 상품군을 사는 사람이 실수하기 쉬운 부분을 짚은 뒤 선택을 쉽게 만들어준다.",
    "재구매관점형: 반복해서 쓰는 제품이라면 무엇이 귀찮지 않아야 계속 손이 가는지 중심으로 설명한다.",
    "취향매칭형: 모든 사람에게 좋다고 하지 않고 어떤 취향·생활패턴의 사람에게 특히 잘 맞는지 선명하게 설명한다.",
    "구성확인형: 수량·용량·사이즈·구성품처럼 실제 결제 직전 확인해야 할 부분을 제품의 장점과 연결한다."
]
CTA_PLANS = [
    "현재 옵션과 구성 확인형: 결론에서 내 상황과 맞는지 한 번 더 짚고 링크에서 실제 선택 옵션과 현재 가격을 확인하도록 유도한다.",
    "비교 마무리형: 다른 후보와 마지막으로 비교할 항목을 하나 정리한 뒤 링크에서 상세 구성 확인을 권한다.",
    "생활 적합성 확인형: 내가 쓸 장면이 떠오른다면 링크에서 사이즈·수량·옵션을 확인해보라는 흐름으로 마무리한다.",
    "구매 전 체크형: 장점은 충분히 보여주되 결제 전 확인할 한 가지를 짚고 상품 링크 확인으로 자연스럽게 연결한다."
]

def _recent_history_values(history,key,limit=24):
    out=[]
    for item in reversed([x for x in (history.get("items") or []) if isinstance(x,dict)]):
        value=item.get(key)
        if isinstance(value,list):
            for x in value:
                x=str(x or "").strip()
                if x and x not in out:out.append(x)
                if len(out)>=limit:return out
        else:
            x=str(value or "").strip()
            if x and x not in out:out.append(x)
            if len(out)>=limit:return out
    return out

def _creative_plan(product_name,category,history=None):
    history=history or {"items":[]}
    recent=set(_recent_history_values(history,"creative_plan",12))
    rng=random.SystemRandom()
    combos=[]
    for voice in VOICE_PLANS:
        for angle in CONVERSION_ANGLES:
            for cta in CTA_PLANS:
                plan=f"{voice} | {angle} | {cta}"
                if plan not in recent:combos.append(plan)
    if not combos:
        combos=[f"{v} | {a} | {c}" for v in VOICE_PLANS for a in CONVERSION_ANGLES for c in CTA_PLANS]
    return rng.choice(combos)

def _stable_index(key, n):
    if n<=0:return 0
    h=hashlib.sha256(str(key or "").encode("utf-8","ignore")).hexdigest()
    return int(h[:12],16)%n

def _pick_stable(key, options):
    return options[_stable_index(key,len(options))] if options else ""


def _has_batchim(text):
    for ch in reversed(str(text or "").strip()):
        code=ord(ch)
        if 0xAC00<=code<=0xD7A3:return ((code-0xAC00)%28)!=0
        if ch.isalnum():return False
    return False

def _with_josa(text, consonant, vowel):
    text=str(text or "").strip()
    return text+(consonant if _has_batchim(text) else vowel)

def _sentence_split(text):
    text=re.sub(r"\s+"," ",str(text or "")).strip()
    if not text:return []
    parts=re.split(r"(?<=[.!?。！？])\s+|(?<=요)\s+(?=[가-힣A-Za-z0-9])",text)
    return [x.strip() for x in parts if len(x.strip())>=12]

def _obj_sentences(obj):
    out=[]
    for x in obj.get("intro") or []:out.extend(_sentence_split(x))
    for sec in obj.get("sections") or []:
        if not isinstance(sec,dict):continue
        for x in sec.get("paragraphs") or []:out.extend(_sentence_split(x))
    out.extend(_sentence_split(obj.get("conclusion") or ""))
    return out

def _load_content_history():
    try:
        obj=json.loads(CONTENT_HISTORY.read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {"items":[]}
    except Exception:return {"items":[]}

def _save_content_history(history):
    try:
        items=[x for x in (history.get("items") or []) if isinstance(x,dict)][-600:]
        CONTENT_HISTORY.parent.mkdir(parents=True,exist_ok=True)
        tmp=CONTENT_HISTORY.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items":items},ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,CONTENT_HISTORY)
    except Exception as e:log("본문 문장 다양성 이력 저장 실패: "+str(e))

def _recent_forbidden_phrases(history, limit=36):
    items=[x for x in (history.get("items") or []) if isinstance(x,dict)]
    out=[];seen=set()
    for item in reversed(items):
        for sent in item.get("sentences") or []:
            s=re.sub(r"\s+"," ",str(sent or "")).strip()
            key=re.sub(r"[^0-9A-Za-z가-힣]","",s).casefold()
            if len(key)<18 or key in seen:continue
            seen.add(key);out.append(s)
            if len(out)>=limit:return out
    return out

def _similarity(a,b):
    a=re.sub(r"\s+"," ",str(a or "")).strip().casefold();b=re.sub(r"\s+"," ",str(b or "")).strip().casefold()
    if not a or not b:return 0.0
    return difflib.SequenceMatcher(None,a,b).ratio()

def content_diversity_audit(obj, history=None):
    history=history or {"items":[]}
    sents=_obj_sentences(obj);recent=_recent_forbidden_phrases(history,60)
    repeated=[]
    for sent in sents:
        for old in recent:
            sim=_similarity(sent,old)
            if sim>=0.86:
                repeated.append({"sentence":sent,"old":old,"similarity":round(sim,3)});break
    all_text=" ".join(sents)
    cliches=[x for x in CLICHE_PHRASES if x in all_text]
    # Repeated sentence starts within the same article also feel templated.
    starts=[]
    for sent in sents:
        toks=_word_tokens(sent)[:3];key=" ".join(toks).casefold()
        if key:starts.append(key)
    duplicate_starts=sorted({x for x in starts if starts.count(x)>=3})
    title=str(obj.get("title") or "").strip();title_tail=title.split("｜",1)[-1].strip() if title else ""
    title_repeats=[]
    for old in _recent_history_values(history,"title",30):
        old_tail=str(old).split("｜",1)[-1].strip()
        sim=_similarity(title_tail,old_tail)
        if title_tail and old_tail and sim>=0.90:
            title_repeats.append({"title":title,"old":old,"similarity":round(sim,3)});break
    heading_repeats=[]
    recent_headings=_recent_history_values(history,"headings",48)
    for sec in obj.get("sections") or []:
        if not isinstance(sec,dict):continue
        heading=str(sec.get("heading") or "").strip()
        if not heading:continue
        for old in recent_headings:
            if _similarity(heading,old)>=0.93:
                heading_repeats.append({"heading":heading,"old":old});break
    ok=not repeated and not cliches and not duplicate_starts and not title_repeats and not heading_repeats
    return {"ok":ok,"repeated":repeated[:10],"cliches":cliches,"duplicate_starts":duplicate_starts,
            "title_repeats":title_repeats,"heading_repeats":heading_repeats[:6],"sentence_count":len(sents)}

def _record_content_history(history, product_name, obj):
    items=history.setdefault("items",[])
    headings=[str(x.get("heading") or "").strip() for x in (obj.get("sections") or []) if isinstance(x,dict) and str(x.get("heading") or "").strip()]
    items.append({"product_name":product_name,"created_at":time.strftime("%Y-%m-%d %H:%M:%S"),
                  "title":str(obj.get("title") or "").strip(),"headings":headings[:4],
                  "creative_plan":str(obj.get("creative_plan") or "").strip(),
                  "sentences":_obj_sentences(obj)[:30]})
    if len(items)>600:del items[:-600]
    _save_content_history(history)

def _voice_plan(product_name, category):
    base=_pick_stable(str(product_name)+"|"+str(category),VOICE_PLANS)
    return base+" 같은 상품군의 다른 글과 문장 시작과 결론 표현이 겹치지 않게 한다."

def health():
    cfg=settings(); api=coupang_partners_api.health(); lh=_llm_runtime_health(cfg)
    primary=str(lh.get("primary") or "safe_fallback")
    if primary=="ollama": llm_msg="Ollama 무료 로컬 AI 1순위 READY · "+str(lh.get("ollama_model") or cfg.get("ollama_model") or "")
    elif primary=="openai": llm_msg="Ollama 미연결 · OpenAI 유료 fallback 사용"
    else: llm_msg="Ollama 미연결 → 제품군 안전 원고 자동복구 (API 비용 0원)"
    return {"ready":True,"name":"콘텐츠/이미지 제작","message":f"{llm_msg} · 제목/본문/태그 AI 다양화 · 구매전환 품질검증 · 쿠팡 API {'READY' if api.get('ready') else '키 미설정'}"}

def _openai_credentials(cfg=None):
    cfg=cfg or settings();obj={}
    p=DATA/"openai_api_credentials.json"
    try:
        raw=json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw,dict):obj=raw
    except Exception:pass
    key=str(obj.get("api_key") or cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY","") or "").strip()
    model=str(obj.get("model") or cfg.get("openai_model") or "gpt-5.6-sol").strip()
    return {"api_key":key,"model":model}

def _extract_json_response(text):
    raw=str(text or "").strip()
    raw=re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw=re.sub(r"\s*```$", "", raw)
    try:return json.loads(raw)
    except Exception:pass
    a=raw.find("{");b=raw.rfind("}")
    if a>=0 and b>a:
        return json.loads(raw[a:b+1])
    raise ValueError("AI 응답에서 JSON 객체를 찾지 못함")

def call_ollama(prompt,model,cfg=None,live=None,cancel_check=None):
    """Stream Ollama output so the GUI can show real-time activity.

    v8.08.40 deliberately uses streaming even though the final result is JSON.
    This does not change the generated document format; it only exposes progress
    while the local model is working and lets the user cancel between chunks.
    """
    cfg=cfg or settings();model=ollama_local.resolve_model(cfg) or str(model or "qwen3:8b")
    options={
        "temperature":float(cfg.get("ollama_temperature",0.82)),
        "top_p":float(cfg.get("ollama_top_p",0.90)),
        "top_k":int(cfg.get("ollama_top_k",40)),
        "repeat_penalty":float(cfg.get("ollama_repeat_penalty",1.08)),
        "num_ctx":int(cfg.get("ollama_num_ctx",12288)),
        "num_predict":int(cfg.get("ollama_num_predict",1900)),
    }
    payload={
        "model":model,
        "messages":[{"role":"user","content":prompt}],
        "stream":True,
        "format":"json",
        "think":bool(cfg.get("ollama_think",False)),
        "keep_alive":str(cfg.get("ollama_keep_alive","30m")),
        "options":options,
    }
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
    attempts=max(1,int(cfg.get("ollama_retry_count",1)));last=None
    for attempt in range(1,attempts+1):
        req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=data,headers={"Content-Type":"application/json","Accept":"application/x-ndjson, application/json"})
        started=time.monotonic();parts=[];last_emit=0.0;final_obj={}
        try:
            if live:
                live({"event":"ollama_start","model":model,"attempt":attempt,"elapsed":0.0,"chars":0})
            with urllib.request.urlopen(req,timeout=int(cfg.get("ollama_timeout_sec",420))) as r:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("사용자 중지 요청")
                    line=r.readline()
                    if not line:break
                    try:obj=json.loads(line.decode("utf-8","ignore"))
                    except Exception:continue
                    final_obj=obj or final_obj
                    chunk=str((obj.get("message") or {}).get("content") or "")
                    if chunk:parts.append(chunk)
                    now=time.monotonic()
                    if live and (now-last_emit>=0.18 or obj.get("done")):
                        text="".join(parts)
                        elapsed=max(0.001,now-started)
                        live({
                            "event":"ollama_stream","model":model,"attempt":attempt,
                            "elapsed":elapsed,"chars":len(text),
                            "char_rate":round(len(text)/elapsed,1),
                            "preview":text[-180:].replace("\n"," "),
                            "done":bool(obj.get("done")),
                            "eval_count":int(obj.get("eval_count") or 0),
                            "eval_duration":int(obj.get("eval_duration") or 0),
                            "prompt_eval_count":int(obj.get("prompt_eval_count") or 0),
                        })
                        last_emit=now
                    if obj.get("done"):break
            content="".join(parts).strip()
            if not content:raise RuntimeError("Ollama 응답 본문 없음")
            if live:
                eval_count=int(final_obj.get("eval_count") or 0);eval_ns=int(final_obj.get("eval_duration") or 0)
                tok_s=round(eval_count/(eval_ns/1_000_000_000),2) if eval_count and eval_ns else 0.0
                live({"event":"ollama_done","model":model,"attempt":attempt,"elapsed":time.monotonic()-started,
                      "chars":len(content),"eval_count":eval_count,"tokens_per_sec":tok_s,
                      "prompt_eval_count":int(final_obj.get("prompt_eval_count") or 0)})
            return _extract_json_response(content)
        except Exception as e:
            last=e
            if live:live({"event":"ollama_error","model":model,"attempt":attempt,"elapsed":time.monotonic()-started,"error":str(e)})
            if "사용자 중지" in str(e):raise
            if attempt>=attempts:raise
            time.sleep(0.8*attempt)
    raise last or RuntimeError("Ollama 호출 실패")

def call_openai(prompt,cfg):
    cred=_openai_credentials(cfg);key=cred.get("api_key") or "";model=cred.get("model") or "gpt-5.6-sol"
    if not key:raise RuntimeError("OpenAI API key 없음")
    payload={"model":model,"input":prompt,"max_output_tokens":int(cfg.get("openai_max_output_tokens",6000))}
    effort=str(cfg.get("openai_reasoning_effort","low") or "low").strip().lower()
    if model.startswith("gpt-5.6") and effort in {"none","low","medium","high","xhigh","max"}:
        payload["reasoning"]={"effort":effort}
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
    last=None
    attempts=max(1,int(cfg.get("openai_retry_count",3)))
    for attempt in range(1,attempts+1):
        req=urllib.request.Request("https://api.openai.com/v1/responses",data=data,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=int(cfg.get("openai_timeout_sec",240))) as r:
                obj=json.loads(r.read().decode("utf-8","ignore"))
            texts=[]
            for out in obj.get("output",[]):
                for c in out.get("content",[]):
                    if c.get("type")=="output_text":texts.append(c.get("text", ""))
            if not texts:raise RuntimeError("OpenAI Responses API output_text 없음")
            return _extract_json_response("".join(texts))
        except urllib.error.HTTPError as e:
            try:body=e.read().decode("utf-8","ignore")[:1200]
            except Exception:body=""
            last=RuntimeError(f"OpenAI HTTP {e.code}: {body}")
            if e.code not in {408,409,429,500,502,503,504} or attempt>=attempts:raise last
        except Exception as e:
            last=e
            if attempt>=attempts:raise
        time.sleep(min(8.0,1.5*(2**(attempt-1))))
    raise last or RuntimeError("OpenAI 호출 실패")

_LLM_RUNTIME_CACHE={"ts":0.0,"signature":"","ready":False,"reason":"미확인"}

def _ollama_health(cfg):
    st=ollama_local.status(cfg)
    model=st.get("model") or st.get("recommended") or str(cfg.get("ollama_model") or "")
    if st.get("ready"):return True,f"Ollama 무료 로컬 AI {model} READY"
    return False,str(st.get("reason") or f"Ollama 모델 {model} 미설치")

def _llm_runtime_health(cfg=None, force=False):
    """Cost-first policy: local Ollama first. OpenAI is never auto-used unless explicitly enabled."""
    global _LLM_RUNTIME_CACHE
    cfg=cfg or settings();cred=_openai_credentials(cfg)
    openai_auto=bool(cfg.get("openai_auto_enabled",False))
    signature=f"{openai_auto}|{bool(cred.get('api_key'))}|{cred.get('model')}|{cfg.get('ollama_model')}|{cfg.get('llm_provider_priority')}"
    now=time.time()
    if not force and _LLM_RUNTIME_CACHE.get("signature")==signature and now-float(_LLM_RUNTIME_CACHE.get("ts") or 0)<20:
        return dict(_LLM_RUNTIME_CACHE)
    ollama_ready,ollama_reason=_ollama_health(cfg);openai_ready=bool(openai_auto and cred.get("api_key"))
    priority=list(cfg.get("llm_provider_priority") or ["ollama","safe_fallback"])
    available=[]
    if ollama_ready:available.append("ollama")
    if openai_ready:available.append("openai")
    ordered=[x for x in priority if x in available]
    for x in available:
        if x not in ordered:ordered.append(x)
    primary=ordered[0] if ordered else "safe_fallback"
    if ollama_ready:
        reason=ollama_reason+" · OpenAI 자동사용 OFF" if not openai_auto else ollama_reason+" · OpenAI는 로컬 실패 시만 대기"
    elif openai_ready:reason=f"Ollama 미연결 → OpenAI 유료 fallback 허용: {cred.get('model')}"
    else:reason=ollama_reason+" → 안전원고 (API 비용 0원)"
    _LLM_RUNTIME_CACHE={"ts":now,"signature":signature,"ready":bool(ordered),"reason":reason,"primary":primary,
                        "available_providers":ordered,"openai_ready":openai_ready,"ollama_ready":ollama_ready,
                        "openai_auto_enabled":openai_auto,"openai_model":cred.get("model"),"ollama_reason":ollama_reason,
                        "ollama_model":ollama_local.resolve_model(cfg)}
    return dict(_LLM_RUNTIME_CACHE)

def _call_llm_priority(prompt,cfg,providers=None,live=None,cancel_check=None):
    providers=list(providers or _llm_runtime_health(cfg).get("available_providers") or [])
    errors=[];priority=list(cfg.get("llm_provider_priority") or ["ollama","safe_fallback"])
    order=[x for x in priority if x in providers and x in {"ollama","openai"}]
    for x in providers:
        if x in {"ollama","openai"} and x not in order:order.append(x)
    for provider in order:
        try:
            if provider=="ollama":return call_ollama(prompt,ollama_local.resolve_model(cfg),cfg,live=live,cancel_check=cancel_check),"ollama_local_free",errors
            if not bool(cfg.get("openai_auto_enabled",False)):continue
            return call_openai(prompt,cfg),"openai_optional_fallback",errors
        except Exception as e:
            errors.append(f"{provider}: {e}");log("AI provider 실패, 다음 provider 시도 — "+errors[-1])
            if "사용자 중지" in str(e):raise
    raise RuntimeError(" / ".join(errors) or "사용 가능한 AI provider 없음")


WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+")

# v7.38 SEO policy: Naver/blog search engines can treat every whitespace word
# as a repeated keyword.  Product-name words are therefore reserved once they
# appear at the front of a title/tag set and may not be re-used in later SEO
# phrases.  Example:
#   MTC 살몬 카밍 에센셜 마스크팩 추천｜구매 전 체크 후기
# rather than repeating MTC/살몬/마스크팩 in the tail.
TITLE_FIXED_WORDS = ("추천","구매","전","체크","후기")
GENERIC_TAG_POOL = [
    "후기","리뷰","추천","비교","가격","구매","사용법","장점","단점","특징",
    "구성","옵션","선택법","활용법","보관법","주의사항","가성비","만족도","품질","디자인",
    "편의성","실용성","사용감","체크포인트","구매팁","사용팁","평가","정보","요약","분석",
    "기준","선택","활용","관리","팁","확인","선호도","인기","소비자","필수정보",
    "핵심","포인트","상세","실사용","체감","비교법","구매가이드","사용가이드","추천이유","선택기준",
    "가격정보","구성정보","옵션정보","장단점","활용팁","관리법","구매정보","사용정보","체크리스트","구매전정보",
    "만족포인트","실용포인트","선택포인트","비교포인트","사용포인트","제품정보","상품정보","사용후기","소비자리뷰","구매후기"
]

CORE_TAG_PRIORITY = [
    "후기","리뷰","사용법","비교","가격","장점","특징","구성","선택법","사용팁",
    "구매팁","가성비","사용감","장단점","추천","평가","정보","활용법","관리법","체크포인트"
]
CATEGORY_WORD_POOL = {
 "생활용품":["생활","살림","집안","위생","청결","수납","가정","일상","소모품","내구성","편리함","정리","청소","관리용품","생활템","살림템","필수품","가정용","실내용","생활정보"],
 "주방용품":["주방","키친","조리","식기","요리","세척","위생","보관","내열","편리함","주방템","키친웨어","조리도구","식탁","주방살림","홈쿡","조리용품","주방정보","세척팁","보관팁"],
 "패션잡화":["패션","코디","데일리","스타일","착용감","핏","소재","사이즈","컬러","계절","활용도","매치","룩","착장","포인트룩","데일리룩","패션템","스타일링","착용팁","코디팁"],
 "식품":["먹거리","맛","향","식감","영양","원재료","성분","칼로리","보관","섭취","간식","음료","레시피","식품정보","섭취팁","보관팁","맛평가","원산지","유통기한","식단"],
 "디지털/가전":["가전","디지털","성능","스펙","기능","배터리","충전","호환성","연결","설치","설정","휴대성","내구성","편의성","기기","전자제품","사용성","연결성","설치팁","설정팁"],
 "화장품/미용":["뷰티","스킨케어","홈케어","피부관리","보습","진정","수분","밀착력","제형","성분","피부결","데일리케어","루틴","촉촉함","흡수력","자극감","향","발림성","지속력","사용순서","피부타입","뷰티팁","케어팁","사용감","피부표현"]
}

def _word_tokens(text):
    return WORD_RE.findall(str(text or ""))

def _norm_token(token):
    return str(token or "").casefold()

def _dedupe_phrase_words(text, max_chars=None):
    """Keep first occurrence of each word, preserving product identity order."""
    out=[];seen=set()
    for tok in _word_tokens(text):
        k=_norm_token(tok)
        if not k or k in seen:continue
        cand=" ".join(out+[tok])
        if max_chars and len(cand)>int(max_chars) and out:break
        seen.add(k);out.append(tok)
    return " ".join(out)

def _clean_tokens(name):
    toks=[];seen=set()
    for x in _word_tokens(name):
        k=_norm_token(x)
        if len(x)<2 or x in PROMO_WORDS or k in seen:continue
        seen.add(k);toks.append(x)
    return toks

def _seo_product_tokens(name):
    """Return de-duplicated product identity words with obvious ad/promo noise removed.

    The database keeps the original marketplace name for exact price matching.
    Only SEO display text is cleaned here, so removing words such as '강추/특가'
    cannot weaken product identity validation in the price/image pipeline.
    """
    out=[];seen=set();display_name=clean_listing_title_noise(name)
    for tok in _word_tokens(re.sub(r"\[[^\]]{0,60}\]"," ",str(display_name or ""))):
        key=_norm_token(tok)
        if not key or key in seen:continue
        if tok in PROMO_WORDS or key in {_norm_token(x) for x in PROMO_WORDS}:continue
        # Common ranking/listing decorations are not part of a product identity.
        if re.fullmatch(r"(?i)(?:TOP|BEST)\d*",tok):continue
        seen.add(key);out.append(tok)
    return out

def _concise_name(name,max_chars=34):
    toks=_seo_product_tokens(name)
    if not toks:
        toks=[];seen=set()
        for tok in _word_tokens(name):
            k=_norm_token(tok)
            if k and k not in seen:seen.add(k);toks.append(tok)
    out=[]
    for tok in toks:
        cand=" ".join(out+[tok])
        if out and len(cand)>int(max_chars):break
        out.append(tok)
    return " ".join(out).strip()


OPTIONAL_SEO_TOKEN_RE=re.compile(r"(?i)^\d+(?:\.\d+)?(?:ml|l|g|kg|mg|cm|mm|oz|개입|개|매|팩|세트|롤|병|캔|포|봉|장|인치|mm|cm|겹|입)$")
OPTIONAL_SEO_NOISE={"세트","본품","리필","옵션","구성","기획","대용량","소용량","묶음","정품","공식"}
RELATED_TAG_HINTS={
 "비누":["세안비누","보습비누","고형비누","민감피부비누","뷰티바추천","바디비누","데일리비누","욕실비누","세정바","비누사용법"],
 "뷰티바":["센서티브바","보습세정","고형클렌저","샤워비누","피부세정","데일리세안"],
 "젓가락":["일회용젓가락","대나무젓가락","나무젓가락","위생젓가락","업소용젓가락","식당용젓가락","배달용젓가락","캠핑젓가락","개별포장젓가락","일회용대나무젓가락"],
 "반팔티":["반팔티추천","기본반팔티","데일리반팔티","무지반팔티","남녀공용반팔티","여름반팔티","레이어드반팔티"],
 "선크림":["톤업선크림","데일리선크림","자외선차단","메이크업베이스","선크림추천","촉촉한선크림"],
 "오메가3":["오메가3추천","rTG오메가3","혈행건강","영양제추천","기초영양제","하루영양제"],
 "쿠션":["쿠션추천","베이스메이크업","광채쿠션","밀착쿠션","메이크업쿠션","쿠션파운데이션"],
 "세럼":["세럼추천","앰플추천","데일리세럼","수분세럼","진정세럼","피부결케어"],
 "패딩":["경량패딩","가을아우터","겨울아우터","데일리패딩","휴대용패딩","보온아우터"],
}

def _is_optional_seo_token(tok):
    tok=str(tok or "").strip()
    if not tok:return True
    if tok in OPTIONAL_SEO_NOISE:return True
    if re.fullmatch(r"\d+(?:\.\d+)?",tok):return True
    if OPTIONAL_SEO_TOKEN_RE.fullmatch(tok):return True
    return False


def _descriptive_tokens_for_seo(name):
    desc=""
    try:desc=naver_keywords.descriptive_query(name)
    except Exception:desc=""
    toks=[t for t in _word_tokens(desc) if not _is_optional_seo_token(t)]
    if toks:return toks[:5]
    return [t for t in _seo_product_tokens(name) if not _is_optional_seo_token(t)][:5]


def _product_phrase_candidates(name):
    toks=_descriptive_tokens_for_seo(name)
    out=[]
    def add(v):
        v=re.sub(r"\s+"," ",str(v or "")).strip().lstrip("#")
        if not v or v in out:return
        out.append(v)
    if toks:
        add(" ".join(toks))
        add("".join(toks))
        if len(toks)>=2:
            add(" ".join(toks[-2:]))
            add("".join(toks[-2:]))
        if len(toks)>=3:
            add(" ".join(toks[-3:]))
            add("".join(toks[-3:]))
        if len(toks)>=2:
            add(" ".join(toks[:2]))
            add("".join(toks[:2]))
    base=_concise_name(name,45)
    add(base)
    return out


def _related_tag_hints(name):
    probe=" ".join(_product_phrase_candidates(name))
    out=[]
    for key,vals in RELATED_TAG_HINTS.items():
        if key and key in probe:
            for v in vals:
                if v not in out:out.append(v)
    return out


RETAIL_SEO_TERMS={"코스트코","다이소","이마트","트레이더스","홈플러스","롯데마트","올리브영","면세점","아마존","큐텐"}
GENERIC_PROSE_TERMS=(
    "선택 기준","판매 단위","세부 구성","같은 조건","사용 장면","내 상황","생활 패턴","비교 후보",
    "실용 소비","체감 가성비","규격","옵션","조건을 맞","구성을 확인","가격 비교"
)
PRODUCT_FAMILY_PROFILES=[
    ("cleansing_bar", re.compile(r"비누|뷰티바|클렌징바|세안비누|솝",re.I),
     ["비누","뷰티바","세안","세정","거품","보습","민감","센서티브","피부","향","샤워","바디","크림","세정력","당김","촉촉"],
     "비누/뷰티바는 세정할 때의 거품, 씻은 뒤 당김 여부, 향, 보관과 물러짐, 낱개 사용 편의, 묶음 수량처럼 실제 욕실 사용에서 느끼는 포인트를 중심으로 쓴다."),
    ("shampoo", re.compile(r"샴푸|린스|트리트먼트|컨디셔너",re.I),
     ["샴푸","두피","모발","거품","세정","향","헹굼","머리","컨디셔닝","사용감"],
     "헤어 제품은 거품/헹굼/향/두피와 모발 사용감, 용량과 펌프 편의 등 실제 샤워 루틴을 중심으로 쓴다."),
    ("cleanser", re.compile(r"폼클렌징|클렌저|클렌징폼|클렌징",re.I),
     ["세안","클렌징","거품","세정","피부","당김","메이크업","헹굼","사용감"],
     "클렌저는 거품, 세안 후 느낌, 헹굼, 아침/저녁 루틴과 피부 타입을 고려한 선택 포인트 중심으로 쓴다."),
    ("skincare", re.compile(r"세럼|앰플|크림|로션|에센스|토너|선크림|쿠션|팩",re.I),
     ["피부","보습","수분","발림","흡수","밀착","제형","향","루틴","메이크업","사용감","촉촉"],
     "화장품은 제형, 발림, 흡수/밀착, 향, 메이크업과의 궁합, 아침저녁 사용 순서처럼 손에 잡히는 사용감을 중심으로 쓴다."),
    ("chopsticks", re.compile(r"젓가락",re.I),
     ["젓가락","대나무","일회용","포장","식사","배달","캠핑","식탁","길이","그립","위생"],
     "젓가락은 포장, 길이와 잡는 느낌, 나무 표면, 배달/캠핑/손님상 같은 사용 상황과 수량을 중심으로 쓴다."),
    ("food", re.compile(r"음료|주스|차|커피|쌀|과자|간식|식품|우유|라면|면류|국수|새우|생선|고기|육류|과일|채소|김치|만두|빵|떡|소스|양념|배",re.I),
     ["맛","향","식감","보관","냉장","섭취","간식","음료","용량","원재료","먹기","마시기"],
     "식품은 맛과 향, 한 번 먹는 양, 보관, 언제 손이 가는지, 함께 먹기 좋은 상황처럼 실제 먹는 경험을 중심으로 쓴다."),
    ("mobile_accessory", re.compile(r"맥세이프|휴대폰\s*케이스|스마트폰\s*케이스|폰\s*케이스|카드\s*지갑|그립톡",re.I),
     ["케이스","카드","수납","슬림","자석","부착","휴대","그립","두께","지갑","맥세이프","스마트폰"],
     "휴대폰 액세서리는 기기·케이스 호환성, 자석 부착 안정성, 카드 수납량, 두께와 그립처럼 매일 손에 들었을 때의 편의를 중심으로 쓴다."),
    ("apparel", re.compile(r"티셔츠|반팔|원피스|블라우스|패딩|가방|신발|운동화|부츠|바지|모자|볼캡|캡모자|팔찌|목걸이|귀걸이|반지|주얼리|지갑|벨트|스카프",re.I),
     ["핏","사이즈","소재","착용","코디","기장","두께","무게","계절","세탁","수납","컬러"],
     "패션 제품은 핏, 소재, 사이즈, 무게, 계절감과 실제 코디 장면을 중심으로 쓴다."),
    ("digital", re.compile(r"충전|케이블|이어폰|가전|무선|배터리|전자|선풍기|세탁기",re.I),
     ["충전","배터리","연결","무선","휴대","소음","크기","설치","호환","사용","성능"],
     "디지털/가전은 설치, 연결, 충전, 크기, 소음, 휴대성과 반복 사용 편의처럼 실제 조작 경험을 중심으로 쓴다."),
]
CATEGORY_CONCRETE_TERMS={
    "생활용품":["사용","보관","청소","위생","크기","수량","손","정리","향"],
    "주방용품":["주방","식탁","조리","세척","보관","손","크기","수량"],
    "패션잡화":["핏","사이즈","소재","착용","코디","무게","수납"],
    "식품":["맛","향","식감","보관","먹","마시","용량"],
    "디지털/가전":["충전","배터리","연결","설치","크기","소음","사용"],
    "화장품/미용":["피부","발림","거품","세안","보습","향","제형","사용감","루틴"],
}

def _product_profile(name,category=""):
    raw=str(name or "")
    for key,rx,terms,hint in PRODUCT_FAMILY_PROFILES:
        if rx.search(raw):
            return {"family":key,"terms":terms,"hint":hint}
    category_family={"식품":"food","패션잡화":"apparel","디지털/가전":"digital","화장품/미용":"skincare"}.get(str(category or ""))
    if category_family:
        for key,_rx,terms,hint in PRODUCT_FAMILY_PROFILES:
            if key==category_family:return {"family":key,"terms":terms,"hint":hint,"category_recovery":True}
    return {"family":"category","terms":CATEGORY_CONCRETE_TERMS.get(category,["사용","크기","수량","보관"]),
            "hint":"제품 이름에서 확인되는 용도와 실제로 쓰는 순간을 중심으로 구체적으로 쓴다."}

def _subkeyword_context_plan(name,subkeywords,count=4):
    """Explain how SEO terms may be used without pretending they are product features."""
    name_tokens={_norm_token(x) for x in _word_tokens(name)}
    kws=heading_subkeyword_terms(name,subkeywords,count)
    out=[]
    sibling={"샴푸","린스","트리트먼트","컨디셔너","바디워시","클렌저","로션","세럼","앰플","크림","선크림","쿠션"}
    for kw in kws:
        kl=_norm_token(kw)
        if kw in RETAIL_SEO_TERMS:
            note="판매처/가격/묶음 구성 비교 맥락으로만 사용. 제품의 기능이나 효능처럼 쓰지 말 것."
        elif kw in sibling and kl not in name_tokens:
            note="같은 브랜드에서 함께 검색되는 다른 품목과의 구분/비교 맥락으로만 사용. 현재 제품의 기능처럼 연결하지 말 것."
        elif kw in {"비교","가격","후기","추천","사용법","성분","향","정품"}:
            note="구매자가 실제로 궁금해할 정보 맥락으로 자연스럽게 연결. 추상적인 '선택 기준' 문장으로 때우지 말 것."
        else:
            note="현재 제품의 실제 사용/구매 맥락에 연결하되 뜻이 맞지 않으면 억지 설명을 만들지 말 것."
        out.append({"keyword":kw,"context":note})
    return out

def _content_text(obj):
    parts=[]
    for x in obj.get("intro") or []:parts.append(str(x))
    for sec in obj.get("sections") or []:
        if isinstance(sec,dict):parts.extend(str(x) for x in sec.get("paragraphs") or [])
    parts.append(str(obj.get("conclusion") or ""))
    return re.sub(r"\s+"," "," ".join(parts)).strip()

def content_quality_audit(obj,name,category="",subkeywords=None):
    """Reject generic/meaningless prose before it can reach Naver Blog.

    This is intentionally stricter than a length check. A long article full of
    `옵션/규격/선택 기준` is worse than a shorter article that talks about the
    actual product, which was the root cause of the v7.64 Dove example.
    """
    text=_content_text(obj);sents=_obj_sentences(obj);profile=_product_profile(name,category)
    specs=[re.sub(r"\s+","",x) for x in re.findall(r"(?i)\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|mg|개입|개|매|팩|세트|롤|병|캔|포|봉|장)\b",name or "")]
    concrete_terms=list(dict.fromkeys(profile.get("terms") or []))
    concrete_sentence_hits=0;abstract=[]
    for sent in sents:
        has_concrete=any(t and t in sent for t in concrete_terms) or any(x and x in sent.replace(" ","") for x in specs)
        if has_concrete:concrete_sentence_hits+=1
        generic_count=sum(1 for g in GENERIC_PROSE_TERMS if g in sent)
        if generic_count>=2 and not has_concrete:abstract.append(sent)
    generic_hits={g:text.count(g) for g in GENERIC_PROSE_TERMS if text.count(g)}
    try:desc=naver_keywords.descriptive_query(name) or ""
    except Exception:desc=""
    desc_mentions=text.count(desc) if len(desc)>=5 else 0
    full_mentions=text.count(str(name or "")) if name else 0
    # Strongly repetitive product phrasing makes copy sound machine-generated.
    overnamed=desc_mentions>4 or full_mentions>2
    # A few different conversational reactions are welcome, but don't force the
    # same catchphrase into every article.
    reaction_markers=("!","아,","확실히","반갑","마음에","눈에 띄","손이 가","괜찮","좋더","편하","매력")
    reaction_hits=sum(text.count(x) for x in reaction_markers)
    min_chars=int(settings().get("content_quality_min_chars",700))
    needed_concrete=max(4,min(7,max(1,len(sents)//3)))
    reasons=[]
    if len(text)<min_chars:reasons.append(f"본문 분량 부족 {len(text)}/{min_chars}")
    if concrete_sentence_hits<needed_concrete:reasons.append(f"제품 구체문장 부족 {concrete_sentence_hits}/{needed_concrete}")
    if len(abstract)>=4:reasons.append(f"추상적 구매조언 과다 {len(abstract)}")
    if sum(generic_hits.values())>=14:reasons.append("옵션/조건/선택기준 반복 과다")
    if overnamed:reasons.append(f"제품명 반복 과다 desc={desc_mentions}, full={full_mentions}")
    if reaction_hits<int(settings().get("content_quality_min_reactions",2)):
        reasons.append(f"사람다운 반응/감탄 부족 {reaction_hits}/{int(settings().get('content_quality_min_reactions',2))}")
    purchase_markers=("잘 맞", "편하", "부담", "활용", "구성", "수량", "용량", "사이즈", "비교", "장점", "관리", "보관", "호환", "사용")
    purchase_hits=sum(1 for x in purchase_markers if x in text)
    conclusion=str(obj.get("conclusion") or "")
    cta_ok=any(x in conclusion for x in ("링크", "옵션", "구성", "가격", "상세", "확인"))
    if purchase_hits<int(settings().get("content_purchase_intent_min_hits",5)):
        reasons.append(f"구매판단에 도움 되는 구체 포인트 부족 {purchase_hits}/{int(settings().get('content_purchase_intent_min_hits',5))}")
    if bool(settings().get("content_require_natural_link_cta",True)) and not cta_ok:
        reasons.append("결론의 자연스러운 상품 링크 확인 유도 누락")
    return {"ok":not reasons,"reasons":reasons,"chars":len(text),"sentence_count":len(sents),
            "family":profile.get("family"),"family_hint":profile.get("hint"),"concrete_sentence_hits":concrete_sentence_hits,
            "needed_concrete":needed_concrete,"generic_hits":generic_hits,"abstract_sentences":abstract[:6],
            "description_mentions":desc_mentions,"full_name_mentions":full_mentions,"reaction_hits":reaction_hits,
            "purchase_intent_hits":purchase_hits,"natural_link_cta":cta_ok}

def content_human_tone_audit(obj):
    """Ollama drafts only: reject prose that reads like a report or generic AI copy."""
    text=_content_text(obj);sents=_obj_sentences(obj)
    formal_endings=("합니다","됩니다","있습니다","없습니다","가능합니다","적합합니다","중요합니다","좋습니다","권장됩니다")
    conversational_endings=("해요","돼요","예요","이에요","어요","아요","네요","죠","거든요","더라고요","싶어요","같아요","보여요","있어요","없어요","편해요","괜찮아요")
    stiff_phrases=("따라서","즉,","즉 ","전반적으로","측면에서","해당 제품","사용자에게","활용할 수 있습니다","적합합니다","권장됩니다","고려할 수 있습니다","도움이 될 수 있습니다")
    formal_count=0;conversation_count=0
    for sent in sents:
        clean=re.sub(r"[.!?…]+$","",str(sent or "").strip())
        if any(clean.endswith(x) for x in formal_endings):formal_count+=1
        if any(clean.endswith(x) for x in conversational_endings):conversation_count+=1
    stiff_hits=sum(text.count(x) for x in stiff_phrases)
    reaction_hits=sum(text.count(x) for x in ("!","?","아,","오,","와,","눈에 들어","마음에","반갑","꽤 ","은근","더라고요","네요","죠"))
    n=max(1,len(sents));formal_ratio=formal_count/n
    reasons=[]
    max_formal=float(settings().get("ollama_human_tone_max_formal_ratio",0.55))
    min_conv=max(3,int(settings().get("ollama_human_tone_min_conversational_sentences",4)))
    if len(sents)>=8 and formal_ratio>max_formal:
        reasons.append(f"보고서식 ~합니다 종결 과다 {formal_count}/{n} ({formal_ratio:.0%})")
    if len(sents)>=8 and conversation_count<min_conv:
        reasons.append(f"대화형 문장 부족 {conversation_count}/{min_conv}")
    if stiff_hits>int(settings().get("ollama_human_tone_max_stiff_phrases",3)):
        reasons.append(f"AI/보고서식 표현 과다 {stiff_hits}")
    if reaction_hits<int(settings().get("ollama_human_tone_min_reactions",2)):
        reasons.append(f"자연스러운 반응/질문 부족 {reaction_hits}")
    return {"ok":not reasons,"reasons":reasons,"formal_count":formal_count,"formal_ratio":round(formal_ratio,3),
            "conversational_count":conversation_count,"stiff_hits":stiff_hits,"reaction_hits":reaction_hits}

def _clean_keyword_phrase(s):
    s=re.sub(r"\s+"," ",str(s or "")).strip().lstrip("#")
    if any(x.lower() in s.lower() for x in BANNED_TAG_WORDS):return ""
    s=re.sub(r"\s+추천$","",s).strip()
    return s

def _novel_phrase(phrase, used_tokens, reserve_tokens=None, max_words=5):
    """Remove every word already used by the product/title/tag context.

    This is intentionally token-level, not phrase-level.  A Naver suggestion
    such as 'MTC 살몬 마스크팩 사용법' for product 'MTC 살몬 ... 마스크팩'
    becomes simply '사용법'.
    """
    phrase=_clean_keyword_phrase(phrase)
    if not phrase:return ""
    blocked=set(used_tokens or set())|set(reserve_tokens or set())
    out=[];local=set()
    for tok in _word_tokens(phrase):
        k=_norm_token(tok)
        if not k or k in blocked or k in local:continue
        if any(x.lower()==k for x in BANNED_TAG_WORDS):continue
        out.append(tok);local.add(k)
        if len(out)>=max(1,int(max_words)):break
    return " ".join(out)

def novel_subkeyword_terms(name, subkeywords, reserve_title_fixed=False, max_terms=12):
    """Return only NEW autocomplete words after removing product-name words.

    This is the traceable form of the user's rule: for a product like
    'MTC 살몬 카밍 에센셜 마스크팩', a suggestion such as
    'MTC 살몬 마스크팩 사용법' contributes only '사용법'.
    """
    used={_norm_token(x) for x in _seo_product_tokens(name)}
    if reserve_title_fixed:
        used.update(_norm_token(x) for x in TITLE_FIXED_WORDS)
    out=[]
    for raw in subkeywords or []:
        novel=_novel_phrase(raw,used,max_words=4)
        if not novel:continue
        toks=[_norm_token(x) for x in _word_tokens(novel)]
        if not toks:continue
        out.append(novel);used.update(toks)
        if len(out)>=max(1,int(max_terms)):break
    return out

def _flatten_novel_subkeywords(name, subkeywords, reserve_title_fixed=False, max_terms=12):
    """Return distinct real Naver-derived NEW words in suggestion order.

    The raw Naver suggestion is preserved in evidence, while display surfaces
    use only the useful trailing words after product-name repetition is removed.
    Nothing is fabricated here.
    """
    phrases=novel_subkeyword_terms(name,subkeywords,reserve_title_fixed,max_terms=max(12,int(max_terms)*2))
    out=[];seen=set()
    for phrase in phrases:
        for tok in _word_tokens(phrase):
            key=_norm_token(tok)
            if not key or key in seen:continue
            seen.add(key);out.append(tok)
            if len(out)>=max(1,int(max_terms)):return out
    return out

def heading_subkeyword_terms(name, subkeywords, count=4):
    """Pick up to four distinct ACTUAL Naver autocomplete-derived terms."""
    return _flatten_novel_subkeywords(name,subkeywords,True,max_terms=max(1,int(count)))

def _phrase_present(text, phrase):
    a=" ".join(_word_tokens(text)).casefold()
    b=" ".join(_word_tokens(phrase)).casefold()
    return bool(b and b in a)

def _heading_text_for(index, keyword, product_name=""):
    """Fallback heading only. Never fabricate a body bridge in v7.65."""
    kw=str(keyword or "").strip();i=min(max(0,int(index)),3)
    name_tokens={_norm_token(x) for x in _word_tokens(product_name)}
    sibling={"샴푸","린스","트리트먼트","컨디셔너","바디워시","클렌저","로션","세럼","앰플","크림","선크림","쿠션"}
    if kw in RETAIL_SEO_TERMS:
        return f"{kw} 판매 구성과 비교할 때 먼저 볼 포인트"
    if kw in sibling and _norm_token(kw) not in name_tokens:
        return f"{kw}와 함께 검색했다면 제품 용도부터 구분해봐요"
    pools=[
      ["{kw}, 실제로 써보는 순간 가장 먼저 느끼는 부분","{kw}로 찾는 분들이 먼저 확인할 포인트","{kw}, 제품 자체를 보면 여기서 차이가 보여요"],
      ["{kw}, 자주 사용할수록 체감되는 부분","{kw}까지 살피면 사용감이 더 또렷해져요","{kw}, 매일 쓰는 흐름에서 확인해볼 점"],
      ["{kw}로 비교할 때 놓치기 쉬운 차이","{kw}, 비슷한 제품과 나란히 보면 보이는 부분","{kw}까지 보면 가격 말고도 차이가 있어요"],
      ["{kw}, 마지막으로 확인하고 고르면 좋은 부분","{kw}까지 체크하고 나면 선택이 훨씬 깔끔해져요","{kw}, 구매 전에 한 번 더 볼 포인트"]
    ]
    tpl=_pick_stable(str(product_name)+"|heading65|"+str(i)+"|"+kw,pools[i])
    return tpl.format(kw=kw)

def _keyword_bridge(index, keyword, product_name=""):
    kw=str(keyword or "").strip();i=min(max(0,int(index)),3)
    pools=[
      ["{kw_obj} 같이 찾아보면 단순히 상품명만 봤을 때보다 어떤 부분을 먼저 확인해야 할지 감이 빨리 와요.","{kw} 쪽을 함께 보면 이 제품이 내 생활 패턴과 맞는지 판단할 기준이 하나 더 생깁니다.","{kw}까지 시선을 넓혀보니 비슷해 보이는 제품 사이에서도 차이가 보이기 시작해요."],
      ["{kw_topic} 실제로 자주 꺼내 쓰는 상황을 떠올렸을 때 체감 차이를 만들 수 있는 부분이에요.","구성만 보는 것보다 {kw}까지 함께 살피면 사용 장면이 훨씬 구체적으로 그려져요.","{kw_obj} 기준에 넣어보면 편의성과 활용 범위를 같이 비교하기 좋아집니다."],
      ["{kw}까지 놓고 비교하면 단순 최저가보다 어떤 선택이 더 납득되는지 정리하기 쉬워요.","비슷한 제품이 많을수록 {kw} 같은 기준 하나가 의외로 선택을 빠르게 만들어줍니다.","{kw_obj} 함께 보면 겉으로 비슷한 제품도 용도나 구성에서 차이가 생겨요."],
      ["마지막에는 {kw}까지 확인해두면 사고 난 뒤 옵션을 다시 찾아보는 번거로움을 줄일 수 있어요.","{kw_topic} 구매 직전에 한 번 더 보는 편이 좋아요. 내 사용 목적과 맞는지 확인하기에 꽤 실용적인 기준입니다.","{kw}까지 체크하고 나면 누구에게 잘 맞고 어떤 경우엔 다른 선택이 나을지 구분하기 편해져요."]
    ]
    tpl=_pick_stable(str(product_name)+"|bridge|"+str(i)+"|"+kw,pools[i])
    return tpl.format(kw=kw,kw_obj=_with_josa(kw,"을","를"),kw_topic=_with_josa(kw,"은","는"))

def enforce_section_subkeywords(sections, name, subkeywords):
    """Ensure keyword presence in headings without injecting synthetic body text.

    v7.64 inserted a generic bridge sentence whenever an LLM paragraph
    did not literally contain the keyword. That produced nonsensical lines such as
    `샴푸를 기준에 넣어보면 편의성과 활용 범위...` in a bar-soap review.
    v7.65 leaves body prose entirely to the LLM and only repairs the heading label.
    """
    secs=[]
    for raw in (sections or [])[:4]:
        if not isinstance(raw,dict):continue
        secs.append({"heading":str(raw.get("heading") or "").strip(),
                     "paragraphs":[str(x).strip() for x in (raw.get("paragraphs") or []) if str(x).strip()]})
    while len(secs)<4:secs.append({"heading":"","paragraphs":[]})
    hearts=["💙","🤍","💛","❤️"]
    kws=heading_subkeyword_terms(name,subkeywords,int(settings().get("seo_heading_subkeyword_target",4)))
    natural_defaults=[
      "처음 손이 가는 이유부터 봤어요","자주 쓸수록 느껴지는 포인트","비슷한 제품과 비교해보면","구매 전에 마지막으로 체크할 부분"
    ]
    for i,sec in enumerate(secs[:4]):
        heading=str(sec.get("heading") or "").lstrip("💙🤍💛❤️❤\ufe0f \t").strip()
        if i<len(kws):
            kw=kws[i]
            if not _phrase_present(heading,kw):heading=_heading_text_for(i,kw,name)
        elif not heading:heading=natural_defaults[i]
        sec["heading"]=hearts[i]+" "+heading
    return secs[:4]

def content_subkeyword_audit(name, title, sections, tags, subkeywords):
    """Strict v7.58 audit for title pipe + title/headings/tags Naver coverage."""
    cfg=settings();target=int(cfg.get("seo_title_subkeyword_target",4))
    title_kws=_flatten_novel_subkeywords(name,subkeywords,True,max_terms=max(1,target))
    heading_kws=heading_subkeyword_terms(name,subkeywords,int(cfg.get("seo_heading_subkeyword_target",4)))
    title_hits=[k for k in title_kws if _phrase_present(title,k)]
    tag_text=" ".join(tags or [])
    tag_hits=[k for k in heading_kws if _phrase_present(tag_text,k)]
    heading_hits=[];paragraph_hits=[]
    secs=sections or []
    for i,kw in enumerate(heading_kws):
        sec=secs[i] if i<len(secs) and isinstance(secs[i],dict) else {}
        heading_hits.append(bool(_phrase_present(sec.get("heading",""),kw)))
        joined=" ".join(sec.get("paragraphs") or [])
        # Body relation is judged by content_quality_audit/LLM prompt, not by
        # forcing the literal keyword into the paragraph.
        paragraph_hits.append(bool(len(joined.strip())>=40))
    pipe_ok=("추천｜" in str(title or "")) if cfg.get("seo_require_recommend_pipe",True) else True
    # If Naver supplied usable new terms, every term that fits our configured
    # target must appear. If Naver returned nothing, do not fabricate SEO words.
    title_kw_ok=(not title_kws) or len(title_hits)>=len(title_kws)
    heading_ok=(not heading_kws) or all(heading_hits)
    paragraph_ok=(not heading_kws) or all(paragraph_hits)
    tags_ok=(not heading_kws) or len(tag_hits)>=len(heading_kws)
    return {
      "policy":"NAVER_SUBKEYWORD_V7_58","pipe_ok":pipe_ok,
      "naver_raw_count":len(subkeywords or []),"title_keywords":title_kws,"title_hits":title_hits,
      "heading_keywords":heading_kws,"heading_hits":heading_hits,"paragraph_hits":paragraph_hits,"tag_hits":tag_hits,
      "title_keyword_ok":title_kw_ok,"heading_keyword_ok":heading_ok,"paragraph_keyword_ok":paragraph_ok,"tag_keyword_ok":tags_ok,
      "naver_keywords_available":bool(heading_kws or title_kws),
      "ok":pipe_ok and title_kw_ok and heading_ok and paragraph_ok and tags_ok and bool(heading_kws or title_kws)
    }

def content_subkeyword_audit_from_blocks(name, title, blocks, tags, subkeywords):
    """Rebuild section shape from stored post blocks for GUI QA."""
    sections=[];current=None
    for block in blocks or []:
        if not isinstance(block,dict):continue
        typ=block.get("type")
        if typ=="heading" and str(block.get("text") or "").lstrip().startswith(("💙","🤍","💛","❤️")):
            current={"heading":str(block.get("text") or ""),"paragraphs":[]};sections.append(current)
        elif typ=="paragraph" and current is not None and len(sections)<=4:
            current["paragraphs"].append(" ".join(str(x) for x in (block.get("lines") or []) if str(x).strip()))
        if len(sections)>=4 and typ=="heading" and "장점 요약" in str(block.get("text") or ""):
            break
    return content_subkeyword_audit(name,title,sections[:4],tags,subkeywords)

def _title_token_duplicates(title):
    toks=[_norm_token(x) for x in _word_tokens(title) if x]
    return sorted({x for x in toks if toks.count(x)>1})

def _tag_token_duplicates(tags):
    """Detect repeated whitespace tokens across the entire tag set.

    v7.65 restores the user's strict token rule: once a word has appeared in one
    tag, the same word may not appear in another tag. Exact duplicate phrases
    are therefore caught too, but the important check is word-level reuse.
    """
    seen=set();dups=[]
    for tag in tags or []:
        local=set()
        for tok in _word_tokens(tag):
            key=_norm_token(tok)
            if not key or key in local:continue
            local.add(key)
            if key in seen and key not in dups:dups.append(key)
            seen.add(key)
    return dups

def seo_token_audit(title,tags,product_name=""):
    cfg=settings();want=int(cfg.get("tags_count",30))
    minimum=max(20,int(cfg.get("seo_min_related_tags",20)))
    maximum=max(minimum,min(30,int(cfg.get("seo_max_related_tags",30))))
    td=_title_token_duplicates(title);gd=_tag_token_duplicates(tags)
    banned=[t for t in tags or [] if any(x.lower() in str(t).lower() for x in BANNED_TAG_WORDS)]
    count_ok=minimum<=len(tags or [])<=maximum
    return {
      "policy":"RELATED_TAGS_20_TO_30_TOKEN_UNIQUE_V8_04","product_tokens":_seo_product_tokens(product_name),
      "title_duplicate_words":td,"tag_duplicate_words":gd,"banned_tags":banned,
      "tag_count":len(tags or []),"target_tag_count":want,
      "minimum_tag_count":minimum,"maximum_tag_count":maximum,
      "title_ok":not td,"tags_ok":not gd and not banned and count_ok,
      "ok":not td and not gd and not banned and count_ok
    }

def build_title(name,subkeywords,category="",ai_title=""):
    """Build `[상품명] 추천｜[실제 네이버 서브키워드] 구매 전 체크 후기`.

    v7.57 dropped all subtitle words first when the 70-char limit was exceeded,
    which also removed the `｜`. v7.58 does the opposite: preserve up to four
    real Naver-derived terms and compact the display product name first.
    """
    cfg=settings();maxc=int(cfg.get("seo_title_max_chars",70));target=max(1,int(cfg.get("seo_title_subkeyword_target",4)))
    slots=_flatten_novel_subkeywords(name,subkeywords,True,max_terms=target)
    full_base=_concise_name(name,56)

    fallback_suffix=_pick_stable(str(name)+"|"+str(category)+"|title-v8.04",[
        "구매 전 비교 포인트",
        "고르기 전 체크할 점",
        "인기 이유와 선택 가이드",
        "구성과 특징 한눈에 보기",
        "후기에서 많이 보는 핵심 정리",
        "내게 맞는지 살펴본 구매 가이드",
    ])
    # GPT writes the persuasive tail; deterministic SEO logic only removes repeated product/subkeyword tokens.
    ai=str(ai_title or "").replace("\n"," ").strip()
    tail=ai.split("｜",1)[1].strip() if "｜" in ai else ai
    blocked={_norm_token(x) for x in _word_tokens(name)}
    for x in slots:blocked.update(_norm_token(t) for t in _word_tokens(x))
    tail_words=[];seen=set()
    for tok in _word_tokens(tail):
        key=_norm_token(tok)
        if not key or key in blocked or key in seen or key in {"추천"}:continue
        seen.add(key);tail_words.append(tok)
        if len(tail_words)>=8:break
    suffix=" ".join(tail_words).strip() or fallback_suffix
    while len(suffix)>30 and len(tail_words)>3:
        tail_words.pop();suffix=" ".join(tail_words).strip() or fallback_suffix

    def compose(slot_list,base_text):
        # The separator is mandatory even when Naver temporarily returns no
        # usable new terms. QA then marks that row SEO보완 instead of silently
        # publishing the old no-pipe format.
        middle="·".join(slot_list)
        return f"{base_text} 추천｜{middle} {suffix}" if middle else f"{base_text} 추천｜{suffix}"

    # First keep the Naver words and shorten only the display product name.
    base_words=_word_tokens(full_base)
    title=compose(slots," ".join(base_words))
    while len(title)>maxc and len(base_words)>2:
        base_words.pop();title=compose(slots," ".join(base_words))

    # Extremely long autocomplete terms can still exceed the mobile limit.
    # Only then trim from the last subtitle, always keeping >=1 actual term.
    cur=list(slots)
    while len(title)>maxc and len(cur)>1:
        cur.pop();title=compose(cur," ".join(base_words))
    while len(title)>maxc and len(base_words)>1:
        base_words.pop();title=compose(cur," ".join(base_words))

    # Final safety for unusual single huge tokens: never raw-slice in the middle.
    if len(title)>maxc and cur:
        title=compose(cur[:1]," ".join(base_words[:1]) or _concise_name(name,12))
    elif len(title)>maxc:
        title=compose([]," ".join(base_words[:1]) or _concise_name(name,12))
    return title.rstrip("· ")

def build_tags(name,category,subkeywords,count=30,ai_tags=None):
    """Build exactly `count` tags with strict global word-token uniqueness.

    Priority remains product relevance, but a token can be spent only once
    across all tags. This prevents sets such as `도브 비누 / 도브 샴푸 /
    도브 코스트코` from repeating `도브` over and over.
    """
    count=max(1,int(count));out=[];used=set()

    def add_phrase(candidate,max_words=4):
        if len(out)>=count:return False
        cand=_clean_keyword_phrase(candidate)
        if not cand:return False
        # Keep only words not already spent by earlier tags.
        words=[];local=set()
        for tok in _word_tokens(cand):
            key=_norm_token(tok)
            if not key or key in used or key in local:continue
            if any(x.lower()==key for x in BANNED_TAG_WORDS):continue
            words.append(tok);local.add(key)
            if len(words)>=max(1,int(max_words)):break
        if not words:return False
        phrase=" ".join(words).strip()
        if not phrase or len(phrase)>45:return False
        out.append(phrase);used.update(local);return True

    # 1) Reserve the actual product identity once at the front.
    base=_concise_name(name,45)
    if base:
        base_words=[];base_seen=set()
        for tok in _word_tokens(base):
            key=_norm_token(tok)
            if not key or key in base_seen:continue
            base_seen.add(key);base_words.append(tok)
        if base_words:
            out.append(" ".join(base_words));used.update(base_seen)

    # 2) Real Naver autocomplete: only NEW tail words survive.
    for raw in subkeywords or []:
        add_phrase(raw,4)
        if len(out)>=count:break

    # 3) ChatGPT tag ideas: use them before generic pools, but keep the strict global token uniqueness gate.
    for cand in (ai_tags or []):
        add_phrase(cand,4)
        if len(out)>=count:break

    # 4) Product-family phrases. A compound without spaces is one search token,
    #    but exact whitespace tokens already used above are still blocked.
    for cand in _related_tag_hints(name):
        add_phrase(cand,3)
        if len(out)>=count:break

    # 4) Category and high-intent terms, again spending each token once.
    for cand in CATEGORY_TAGS.get(category,[]):
        add_phrase(cand,3)
        if len(out)>=count:break
    for cand in CATEGORY_WORD_POOL.get(category,[]):
        add_phrase(cand,3)
        if len(out)>=count:break
    for cand in CORE_TAG_PRIORITY:
        add_phrase(cand,3)
        if len(out)>=count:break
    for cand in GENERIC_TAG_POOL:
        add_phrase(cand,3)
        if len(out)>=count:break

    # 5) Deterministic unique one-token fillers. Never use numbered junk.
    fallback_pool=[
      "검색의도","구매판단","사용경험","선택도움","비교정보","핵심정보","체크사항","구매체크",
      "사용체크","제품체크","상품체크","실용정보","활용정보","관리정보","상세정보","리뷰정보",
      "후기정보","추천정보","비교리뷰","선택리뷰","사용리뷰","구매리뷰","생활정보","소비정보",
      "제품분석","상품분석","구매분석","사용분석","비교분석","선택분석","실사용정보","체감후기",
      "구매포인트","사용포인트","선택포인트","핵심포인트","비교포인트","구매결정","선택결정"
    ]
    for cand in fallback_pool:
        add_phrase(cand,1)
        if len(out)>=count:break
    return out[:count]

def _spec_text(name):
    vals=re.findall(r"(?i)\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|mg|cm|mm|oz|개입|개|매|팩|세트|인치|롤|병|캔|포|봉|장)\b",name or "")
    return ", ".join(dict.fromkeys(re.sub(r"\s+","",x) for x in vals[:4]))

def _fallback_context(name, category=""):
    """Compact product/category words used to keep emergency prose product-specific."""
    label=_concise_name(name,46)
    try:
        desc=naver_keywords.descriptive_query(name) or ""
    except Exception:
        desc=""
    desc=_concise_name(desc or label,30) or label
    category_context={
      "생활용품":"꺼내 쓰고 다시 정리하는 흐름",
      "주방용품":"식탁이나 조리 공간에서 손이 가는 흐름",
      "패션잡화":"입거나 들었을 때의 활용 장면",
      "식품":"먹는 시간과 보관 방식",
      "디지털/가전":"설치부터 반복 사용까지의 흐름",
      "화장품/미용":"아침저녁 루틴에 넣었을 때의 사용감",
    }.get(category,"실제로 자주 쓰게 될 장면")
    return label,desc,category_context


def _fallback_sentence(key, role, desc, label, category_context, spec=""):
    """Compose one natural sentence from independent fragments.

    The three independently selected fragments create hundreds of combinations
    per role.  Product-specific wording is woven into the sentence itself rather
    than merely swapping one noun in a fixed template, which prevents the
    fallback path from publishing visibly cloned articles when the LLM is down.
    """
    d_obj=_with_josa(desc,"을","를");d_topic=_with_josa(desc,"은","는")
    l_obj=_with_josa(label,"을","를")
    spec_phrase=(f"{spec} 구성" if spec else "판매 옵션")
    role_parts={
      "intro1":(
        [
          f"{d_obj} 검색 목록에서 처음 마주치면", f"비슷한 이름의 상품이 줄줄이 보일 때 {d_obj} 고르려면",
          f"평소 쓰던 물건을 바꿔볼까 싶어 {d_obj} 찾아보면", f"{d_topic} 상품명만 읽고 바로 결정하기보다",
          f"필요해서 검색창에 {desc}까지 입력한 순간부터", f"{category_context}을 떠올리며 {d_obj} 보면",
          f"가격순으로 넘기다가 {d_obj} 발견했을 때도", f"한 번 사면 자주 손이 갈 {d_obj} 고르는 상황이라면",
        ],
        [
          "먼저 내가 원하는 조건과 판매 단위가 맞는지를 확인하게 됩니다",
          "눈에 띄는 문구보다 실제로 필요한 조건이 들어 있는지가 더 궁금해집니다",
          "가격 차이의 이유가 구성 때문인지부터 풀어보는 편이 이해가 빠릅니다",
          "어디에서 어떻게 쓸지가 분명해야 제품 설명도 훨씬 현실적으로 읽힙니다",
          "이름이 비슷한 대체품 사이에서 무엇을 기준으로 볼지 먼저 정하는 게 편합니다",
          "포장보다 사용 장면을 먼저 잡아두면 비교할 항목이 자연스럽게 줄어듭니다",
        ],
        [
          "그래야 첫 화면의 숫자에만 끌려 고르는 일을 줄일 수 있어요.",
          "이 한 가지를 정해두면 뒤의 비교가 의외로 수월해져요.",
          "처음부터 기준을 세워두니 옵션이 많아도 덜 헷갈립니다.",
          "검색 결과가 길어도 볼 곳이 정해지니 선택이 한결 편해져요.",
          "결국 내 생활에 들어올 제품인지 보는 게 출발점이더라고요.",
        ]),
      "intro2":(
        [
          f"{spec_phrase}을 다시 펼쳐보면", f"{label}의 상세 옵션을 천천히 보면", f"{d_topic} 특히 판매 단위 확인이 중요한데",
          f"겉으로 비슷해 보이는 {desc}끼리 놓고 보면", f"{category_context}까지 생각해보면",
          f"검색 결과의 가격 차이가 커 보일수록", f"구매 버튼을 누르기 전에 {l_obj} 한 번 더 보면",
        ],
        [
          "단순한 총가격보다 내가 실제로 받는 수량과 규격이 먼저 눈에 들어옵니다",
          "같은 이름이어도 묶음 수나 세부 옵션이 달라질 수 있다는 점을 놓치기 쉽습니다",
          "사용 빈도와 보관 공간까지 맞아야 대용량이 정말 이득인지 판단할 수 있습니다",
          "낮은 가격이 같은 조건의 가격인지 확인해야 비교가 제대로 됩니다",
          "필요 이상으로 많은 구성은 오히려 보관 부담이 될 수 있습니다",
          "반대로 자주 쓰는 제품이라면 넉넉한 구성이 번거로운 재구매를 줄여주기도 합니다",
        ],
        [
          "그래서 단위와 용도를 함께 맞춰보는 편이 안전해요.", "이 부분만 체크해도 엉뚱한 옵션을 고를 가능성이 꽤 줄어요.",
          "숫자는 간단해 보여도 실제 만족도와 연결되는 지점은 여기예요.", "판매처가 달라도 같은 조건끼리 놓고 봐야 가격 차이가 제대로 보입니다.",
          "내가 쓰는 속도를 기준으로 보면 어느 구성이 적당한지 금방 감이 와요.",
        ]),
      "s1a":(
        [f"{d_obj} 처음 살펴볼 때는", f"{label}에서 제일 먼저 볼 만한 건", f"기본 쓰임새부터 따져보면 {d_topic}",
         f"제품 설명을 길게 읽기 전에 {d_obj} 손에 쥐는 상황을 떠올리면", f"{category_context} 기준으로 보면 {d_topic}"],
        ["화려한 부가기능보다 자주 쓰게 될 기본 조건이 잘 맞는지가 중요합니다",
         "구성과 규격이 내가 기대한 사용 방식에 맞는지가 먼저 정리돼야 합니다",
         "한 번의 인상보다 반복해서 사용할 때 번거롭지 않은지가 더 오래 남습니다",
         "꺼내는 순간부터 정리하는 순간까지 불편할 만한 지점을 미리 보는 게 좋습니다",
         "이름에서 보이는 특징이 실제 사용 편의로 이어지는지를 확인하는 편이 낫습니다"],
        ["매일 쓰는 물건일수록 이런 작은 차이가 더 분명하게 느껴져요.", "사소해 보여도 사용 횟수가 쌓이면 체감 차이가 생깁니다.",
         "기본이 내 패턴과 맞으면 굳이 복잡한 기능이 많지 않아도 손이 자주 가요.", "첫 선택에서 이 기준을 잡아두면 이후 비교도 훨씬 담백해집니다."] ),
      "s1b":(
        [f"특히 {d_topic}", f"{label}처럼 반복해서 쓰는 제품은", f"한두 번 쓰고 끝나는 물건이 아니라면",
         f"{category_context}이 자연스러워야 하는 {desc}라면", f"실사용을 오래 생각해보면 {d_topic}"],
        ["준비 과정과 보관 방식이 복잡하지 않은지가 의외로 큰 선택 기준이 됩니다",
         "작은 불편 하나가 계속 반복되면 처음의 가격 장점이 금방 희미해질 수 있습니다",
         "손이 가는 위치에 두기 편한지와 다시 정리하기 쉬운지도 함께 볼 만합니다",
         "내가 실제로 쓰는 순서와 제품의 사용 방식이 잘 맞아야 만족도가 오래 갑니다",
         "필요한 순간 바로 사용할 수 있는 편의성이 스펙표보다 더 중요할 때도 있습니다"],
        ["생활 속에서 편하다는 느낌은 대개 이런 부분에서 나와요.", "결국 자주 쓰게 만드는 건 거창한 설명보다 이런 작은 편의입니다.",
         "사용 전후의 동선까지 생각해보면 내게 맞는지 훨씬 쉽게 판단돼요.", "구매 후 손이 자주 갈지를 가늠하기 좋은 포인트입니다."] ),
      "s2a":(
        [f"{d_obj} 실제로 쓰는 장면을 하나 잡아보면", f"{category_context} 속에 {d_obj} 넣어보면", f"사용 장소를 먼저 정하고 {d_obj} 보면",
         f"누가 얼마나 자주 쓸지를 생각하며 {d_obj} 보면", f"설명보다 현실적인 기준이 필요할 때 {d_topic}"],
        ["필요한 크기와 수량, 보관 방식이 한꺼번에 정리되기 시작합니다",
         "내게 필요한 조건과 없어도 되는 옵션이 자연스럽게 나뉩니다",
         "제품의 장점이 내 생활에서도 장점이 될지 조금 더 구체적으로 보입니다",
         "여러 사람이 함께 쓸지 혼자 사용할지에 따라 적당한 구성이 달라질 수 있습니다",
         "공간과 사용 빈도를 같이 보면 과하거나 부족한 선택을 피하기 쉽습니다"],
        ["사용 장면이 선명할수록 광고 문구에 흔들릴 일도 줄어요.", "머릿속에 놓아볼 자리까지 떠오르면 선택 기준이 꽤 명확해집니다.",
         "내 상황에 대입해보는 것만으로도 필요한 옵션이 많이 좁혀져요.", "제품 설명을 생활 언어로 바꿔보는 과정이라고 생각하면 편합니다."] ),
      "s2b":(
        [f"가격표를 다시 볼 때도 {d_topic}", f"{label}의 가격을 판단할 때는", f"같은 예산 안에서 {d_obj} 비교한다면",
         f"{spec_phrase}과 가격을 함께 놓고 보면", f"조금 더 실용적으로 계산해보면 {d_topic}"],
        ["총액 하나보다 실제로 필요한 만큼을 사는지가 더 중요한 계산이 됩니다",
         "내가 쓰지 않을 옵션에 돈을 더 내는지 여부까지 살펴볼 필요가 있습니다",
         "같은 조건을 맞춘 뒤에야 어느 판매처가 합리적인지 제대로 보입니다",
         "사용 횟수까지 생각하면 단순 최저가와 체감 가성비가 다를 수 있습니다",
         "부족해서 다시 사는 비용과 너무 많이 사서 남기는 부담을 같이 생각할 수 있습니다"],
        ["그래서 가격 비교도 사용 목적을 정한 다음 하는 편이 더 정확해요.", "몇 천 원 차이보다 조건 차이를 먼저 보는 이유가 여기에 있습니다.",
         "필요한 만큼 잘 쓰는 쪽이 결국 더 납득되는 선택이 되기 쉬워요.", "같은 숫자라도 내 사용량에 따라 의미가 달라집니다."] ),
      "s3a":(
        [f"비슷한 {desc} 제품을 나란히 놓을 때는", f"대체품과 {l_obj} 함께 비교한다면", f"가격이 더 싼 {desc}가 보여도",
         f"브랜드가 다른 {desc}까지 후보에 넣었을 때", f"검색 결과에서 {desc}가 여러 개 겹쳐 보이면"],
        ["수량과 규격, 재질처럼 실제 사용에 영향을 주는 조건부터 맞춰야 합니다",
         "상품명이 닮았다는 이유만으로 같은 옵션이라고 단정하지 않는 게 좋습니다",
         "내가 꼭 필요한 조건이 빠지지 않았는지부터 확인해야 가격 차이를 해석할 수 있습니다",
         "포장과 표현보다 실제 구성의 차이가 무엇인지 차분히 나눠보는 편이 정확합니다",
         "가장 싼 상품보다 같은 조건에서 어느 쪽이 더 납득되는지를 보는 게 현실적입니다"],
        ["조건을 맞추고 나면 가격 차이의 이유도 훨씬 선명하게 보여요.", "이 순서를 지키면 다른 옵션을 최저가로 착각하는 일을 피할 수 있습니다.",
         "비교의 출발점을 맞춰야 어느 쪽이 나은지 말할 수 있어요.", "같아 보이는 상품일수록 세부 조건을 먼저 보는 게 좋습니다."] ),
      "s3b":(
        [f"{d_topic} 무조건 상위 구성으로 갈 필요도 없고", f"반대로 {d_obj} 가장 단순한 옵션만 고를 이유도 없습니다",
         f"{category_context}을 기준으로 다시 보면", f"나에게 맞는 {desc}를 고른다는 관점에서는", f"마지막 비교 단계의 {d_topic}"],
        ["사용 빈도와 관리 방식에 맞는 중간 지점을 찾는 쪽이 만족하기 쉽습니다",
         "자주 쓰는 조건에는 조금 더 비용을 써도 체감 차이가 남을 수 있습니다",
         "거의 쓰지 않을 기능이라면 가격이 높아도 장점으로 느껴지지 않을 수 있습니다",
         "내가 중요하게 보는 한두 가지 조건이 충족되는지가 결국 우선순위를 정해줍니다",
         "누구에게나 같은 정답보다 사용 방식에 맞는 선택이 더 현실적입니다"],
        ["비교표보다 내 사용 습관이 마지막 판단 기준이 되는 셈이에요.", "이렇게 보면 비싼 제품과 저렴한 제품 사이에서도 기준이 흔들리지 않아요.",
         "필요한 곳에 비용을 쓰고 불필요한 부분은 덜어내는 쪽이 편합니다.", "취향과 사용 빈도에 따라 답이 달라질 수 있다는 점도 자연스러운 부분이에요."] ),
      "s4a":(
        [f"{l_obj} 최종 선택하기 직전에는", f"장바구니에 {d_obj} 담기 전에", f"후보를 {desc} 하나로 좁혔다면",
         f"구매 직전 {label}의 상세 옵션에서", f"이제 {d_obj} 결정하려는 단계라면"],
        ["처음 찾던 규격과 실제 선택 옵션이 같은지 마지막으로 확인하는 게 좋습니다",
         "판매 단위와 세부 구성이 검색 화면에서 본 내용과 같은지 다시 보는 편이 안전합니다",
         "수량이나 모델 선택이 기본값으로 바뀌지 않았는지를 한 번 체크할 필요가 있습니다",
         "배송 조건보다 먼저 내가 골라둔 옵션이 그대로 유지됐는지를 확인하는 편이 좋습니다",
         "같은 상세 페이지 안에서도 선택 항목에 따라 가격과 구성이 달라질 수 있다는 점을 기억할 만합니다"],
        ["몇 초만 확인해도 옵션 착오로 다시 주문하는 번거로움을 줄일 수 있어요.", "마지막 확인이 짧아도 구매 후 만족도에는 꽤 도움이 됩니다.",
         "여기까지 맞으면 이후에는 배송과 가격 조건을 편하게 비교하면 됩니다.", "처음 세운 기준과 마지막 선택이 같은지만 보면 됩니다."] ),
      "s4b":(
        [f"결국 {d_topic}", f"{label}가 잘 맞을 사람을 떠올려보면", f"이런 {desc}를 찾는 이유가 분명하다면",
         f"{category_context}이 자주 반복되는 사람에게 {d_topic}", f"내 생활에서 {d_obj} 쓸 장면이 바로 떠오른다면"],
        ["자주 쓰는 조건이 분명할수록 선택 이유도 또렷해지는 제품입니다",
         "필요한 옵션과 사용 빈도가 맞을 때 실용성이 더 잘 드러납니다",
         "화려한 부가기능보다 기본 쓰임새를 중요하게 보는 쪽에 더 잘 맞을 수 있습니다",
         "보관과 사용 흐름까지 미리 그려지는 사람에게는 비교 후보로 남길 이유가 있습니다",
         "반대로 사용 빈도가 낮다면 더 단순한 구성과 한 번 더 비교해보는 편도 괜찮습니다"],
        ["내 생활과 맞는지가 분명하면 선택을 오래 끌 필요도 없어요.", "조건이 애매하다면 바로 결제하기보다 다른 구성과 한 번 더 비교해도 늦지 않습니다.",
         "제품의 장점이 내 상황에서도 장점인지 확인하는 게 마지막 포인트예요.", "필요성이 선명할수록 가격 비교도 훨씬 간단해집니다."] ),
      "conclusion":(
        [f"한 바퀴 살펴본 뒤 {d_obj} 다시 보면", f"{label}에 대해 마지막으로 남는 기준은", f"여러 조건을 맞춰본 끝에 {d_topic}",
         f"처음 검색했을 때보다 {d_obj} 구체적으로 보고 나면", f"{category_context}까지 고려한 뒤에는"],
        ["가격 자체보다 내 사용 방식과 구성이 잘 맞는지가 더 중요한 제품이라는 점이 분명해집니다",
         "필요한 규격을 정확히 고르고 같은 조건끼리 가격을 비교하는 과정이 가장 현실적인 선택법입니다",
         "자주 쓰게 될 장면과 옵션이 맞아떨어질 때 구매 이유가 가장 자연스럽게 생깁니다",
         "무조건 싸거나 기능이 많은 쪽보다 실제로 끝까지 잘 쓸 수 있는 구성이 더 납득됩니다",
         "내게 필요한 조건만 남겨놓으면 비슷한 제품 사이에서도 결정이 훨씬 단순해집니다"],
        ["그래서 규격과 판매 단위를 확인한 뒤 같은 조건의 가격을 비교해보는 순서를 권하고 싶어요.", "이 기준으로 보면 꼭 필요한 부분에 집중하면서도 과한 선택을 피하기 좋습니다.",
         "사용할 모습이 선명하고 옵션까지 맞는다면 충분히 이유 있는 선택이 될 수 있습니다.", "반대로 한 가지라도 애매하다면 서두르지 말고 같은 제품군을 조금 더 비교해보는 편이 낫습니다."] ),
    }
    leads,cores,tails=role_parts[role]
    # Independent stable selections; variant changes all three without relying on
    # randomness, so rerunning the same product is reproducible while retrying a
    # different variant genuinely changes the prose.
    lead=_pick_stable(key+"|"+role+"|lead",leads)
    core=_pick_stable(key+"|"+role+"|core",cores)
    tail=_pick_stable(key+"|"+role+"|tail",tails)
    return (lead+" "+core+". "+tail).replace("..",".")


def _offline_sentence_pick(key, options):
    return _pick_stable(key, options)


def fallback(name,category="",subkeywords=None,variant=0):
    """Product-family safe copy used only when the configured LLM is unavailable/fails QA.

    Unlike the legacy generic fragment generator, every paragraph is grounded in
    the detected product family. It intentionally avoids invented first-person
    purchase/use claims while still reading like a human review guide.
    """
    subkeywords=list(subkeywords or []);profile=_product_profile(name,category);family=profile.get("family") or "category"
    try:desc=naver_keywords.descriptive_query(name) or _concise_name(name,34)
    except Exception:desc=_concise_name(name,34)
    label=_concise_name(name,52);spec=_spec_text(name);key=f"{name}|{category}|safe-copy-v{int(variant)}"
    sp=(f"{spec} 구성" if spec else "현재 판매 구성")
    reactions=["이런 부분은 확실히 눈에 들어와요!","아, 여기서 사용 편의가 갈리겠구나 싶어요.","매일 쓰는 제품이라면 이런 차이가 꽤 반갑죠!","사소해 보여도 자주 쓰면 체감이 커지는 포인트예요."]
    react=lambda role:_offline_sentence_pick(key+"|react|"+role,reactions)

    if family=="cleansing_bar":
        intro=[
          f"{desc} 제품을 찾는 분이라면 향이 강한 비누보다 세안이나 샤워 뒤의 느낌, 거품, 보관 편의처럼 매일 닿는 부분부터 보게 돼요. {sp}이라 한 개씩 꺼내 쓰면서 여유분을 두기에도 부담이 적은 편인지 살펴볼 만합니다.",
          f"제품명에 센서티브바와 모이스처라이징이 함께 들어가 있어서 피부가 쉽게 당기는 계절에 쓸 비누를 찾는 분들이 특히 눈여겨볼 만해요. 다만 피부 타입은 사람마다 다르니 실제 구매 전 성분표와 향 유무는 한 번 더 확인하는 게 좋습니다. {react('intro')}"
        ]
        sections=[
          {"heading":"","paragraphs":[
            "고형 비누는 결국 손에 물을 묻혀 거품을 내는 순간부터 만족도가 갈려요. 거품이 너무 거칠게 느껴지지 않는지, 얼굴과 몸 중 어디에 주로 쓸지, 씻고 난 뒤 내 피부가 편안한지를 기준으로 보면 제품 설명이 훨씬 쉽게 읽힙니다.",
            f"{label}처럼 여러 개 묶음은 욕실 한 곳에서만 쓰기보다 세면대나 샤워 공간에 나눠 두기에도 편해요. 한 번에 전부 개봉하지 않고 필요한 만큼만 꺼내 쓰면 보관도 깔끔해집니다. {react('s1')}"
          ]},
          {"heading":"","paragraphs":[
            "센서티브 계열을 고르는 이유는 화려한 향보다 매일 부담 없이 손이 가는 쪽을 찾기 때문인 경우가 많아요. 아침 세안이나 저녁 샤워처럼 반복되는 루틴에 넣을 제품이라면 향의 세기와 세정 후 느낌을 우선으로 보는 편이 현실적입니다.",
            f"{sp}은 한 개 가격만 보는 것보다 전체 수량을 실제로 얼마나 빨리 쓰는지도 같이 계산해보면 좋아요. 비누를 가족이 함께 쓰거나 세안과 샤워에 두루 쓰는 집이라면 묶음 구성이 오히려 재구매 번거로움을 줄여줄 수 있습니다."
          ]},
          {"heading":"","paragraphs":[
            "비슷한 뷰티바나 일반 비누와 비교할 때는 브랜드 이름보다 내가 중요하게 보는 포인트를 맞춰보는 게 좋아요. 향, 거품, 세정 후 당김에 대한 후기, 한 개 중량, 포장 방식처럼 실제 사용에서 차이가 나는 부분을 같은 기준으로 놓고 보면 판단이 빨라집니다.",
            "특히 고형 비누는 사용 뒤 물기가 오래 남으면 쉽게 무를 수 있어요. 물 빠짐이 되는 비누 받침을 쓰고, 여분은 습기 적은 곳에 보관하면 마지막 한 개까지 깔끔하게 쓰기 좋습니다."
          ]},
          {"heading":"","paragraphs":[
            f"구매 직전에는 {label}의 중량과 개수가 내가 본 상품과 같은지 확인해보세요. 해외 유통 상품은 판매처에 따라 패키지 표기나 묶음 구성이 달라 보일 수 있어서 같은 이름만 보고 고르기보다 상세 옵션을 보는 편이 안전합니다.",
            f"매일 쓰는 세정 제품은 한 번의 강한 인상보다 계속 손이 가는지가 더 중요해요. 향이나 사용감이 내 취향과 맞고 {sp}도 부담스럽지 않다면 욕실에 두고 꾸준히 쓰기 좋은 선택지가 될 수 있습니다. {react('s4')}"
          ]}
        ]
        advantages=["세안·샤워용으로 활용하기 편한 고형 타입","여러 개 묶음이라 여유분 보관이 쉬움","향·거품·세정 후 느낌을 기준으로 비교하기 좋음","물 빠짐만 챙기면 보관 관리가 단순함","매일 쓰는 기본 세정용 제품으로 보기 쉬움"]
        conclusion=f"{desc} 제품을 고를 때는 광고 문구보다 내 피부가 편하게 느끼는지와 실제 사용 습관이 더 중요합니다. {sp}이 내 사용량과 맞고 향·거품·보관 방식까지 마음에 든다면, 매번 비누를 새로 고르는 번거로움 없이 두고 쓰기 좋은 구성이에요."
    elif family=="chopsticks":
        intro=[
          f"{desc}는 손님이 왔을 때, 배달 음식을 먹을 때, 캠핑 갈 때처럼 갑자기 많이 필요해지는 순간이 분명한 제품이에요. {sp}이라면 집이나 업장에서 어느 정도 기간을 쓸 수 있을지 먼저 계산해보는 게 좋습니다.",
          f"일회용 젓가락은 다 비슷해 보여도 막상 잡아보면 길이, 표면 마감, 포장 상태에서 차이가 나요. 음식과 직접 닿는 제품이라 포장이 깔끔하고 쪼개졌을 때 거친 가시가 적은지 확인하면 마음이 한결 놓입니다. {react('intro')}"
        ]
        sections=[
          {"heading":"","paragraphs":["대나무 젓가락은 식사할 때 미끄럽지 않게 잡히는지와 양쪽 끝이 지나치게 거칠지 않은지가 먼저 보여요. 국수나 반찬을 집을 때 손에 안정적으로 잡히는 길이인지도 은근히 중요합니다.",f"{label}처럼 수량이 넉넉한 상품은 자주 쓰는 곳에 한 묶음 두고 필요할 때 바로 꺼낼 수 있다는 게 장점이에요. {react('s1')}"]},
          {"heading":"","paragraphs":["가정에서는 손님상이나 배달 음식용으로, 업장에서는 테이블 비치용으로 쓰임새가 달라져요. 개별 포장 여부가 중요한 상황이라면 상세 이미지에서 포장 형태를 꼭 확인하는 편이 좋습니다.",f"{sp}은 숫자가 커 보이지만 하루 사용량을 생각하면 적당한지 금방 감이 와요. 한 번에 너무 많이 사서 습한 곳에 오래 두기보다 보관 공간까지 같이 보는 게 실용적입니다."]},
          {"heading":"","paragraphs":["저렴한 나무젓가락과 비교할 때는 단순 개당 가격만 보지 말고 표면 마감과 포장, 실제 길이도 같이 보세요. 식사 도중 손에 거슬리는 부분이 적은 쪽이 결국 만족도가 높습니다.","캠핑이나 야외에서는 사용 후 바로 정리할 수 있다는 편의가 커요. 다만 일회용품인 만큼 필요한 만큼만 챙기는 습관도 같이 가져가면 좋습니다."]},
          {"heading":"","paragraphs":[f"구매 전에는 {label}의 실제 총수량을 다시 확인하세요. '100개 5세트'처럼 판매 단위 표현이 여러 개 들어가면 내가 받는 전체 수량을 헷갈리기 쉬워요.",f"사용처와 수량이 딱 맞는다면 이런 제품은 화려한 기능보다 기본 마감이 좋은 게 최고예요. 필요할 때 바로 꺼내 쓸 수 있다는 단순한 편리함이 꽤 크게 느껴집니다. {react('s4')}"]}
        ]
        advantages=["손님상·배달·캠핑 등 쓰임새가 분명함","넉넉한 수량으로 자주 꺼내 쓰기 편함","대나무 표면과 마감을 기준으로 비교하기 쉬움","포장 형태에 따라 위생적으로 보관 가능","필요할 때 바로 쓰는 일회용 편의성이 큼"]
        conclusion=f"{desc}를 자주 쓰는 집이나 업장이라면 결국 수량, 마감, 포장 세 가지가 핵심이에요. {sp}이 내 사용량과 맞고 상세 이미지에서 마감과 포장 상태까지 괜찮아 보인다면, 꾸준히 비치해두기 편한 실용적인 선택입니다."
    elif family=="food":
        intro=[f"{desc} 제품은 결국 첫입의 맛과 향, 한 번에 먹기 좋은 양이 구매를 좌우해요. {sp}이라면 냉장고나 보관 공간에 무리 없이 들어가는지도 함께 보면 좋습니다.",f"간식이나 음료는 자주 손이 가야 다시 사게 되잖아요. 너무 자극적이지 않은지, 어떤 시간대에 먹기 좋은지까지 떠올려보면 내 취향과 맞는지 훨씬 빨리 판단돼요. {react('intro')}"]
        sections=[
          {"heading":"","paragraphs":["식품은 설명보다 맛의 방향이 가장 궁금해요. 달콤함, 고소함, 산뜻함처럼 제품명과 후기에서 반복해서 언급되는 포인트를 먼저 보면 실패할 확률이 줄어듭니다.",f"{label}의 용량과 수량도 한 번에 먹는 양과 맞춰보세요. {react('s1')}"]},
          {"heading":"","paragraphs":["아침에 간단히 챙길지, 오후 간식으로 먹을지, 운동 뒤에 마실지처럼 먹는 시간을 정하면 필요한 용량이 달라져요. 냉장이 필요한 제품이라면 보관 온도와 개봉 후 섭취 시기도 체크하는 게 좋습니다.","여러 개 묶음은 개당 가격이 좋아 보여도 내 섭취 속도보다 많으면 남을 수 있어요. 유통기한과 보관 공간을 같이 보는 이유가 여기에 있습니다."]},
          {"heading":"","paragraphs":["비슷한 제품과 비교할 때는 가격만 보지 말고 원재료와 영양정보, 당류나 나트륨처럼 내가 신경 쓰는 항목을 같은 기준으로 보세요. 취향 차이가 큰 식품일수록 후기의 맛 표현도 여러 개 읽어보는 편이 좋아요.","먹는 제품은 결국 손이 자주 가느냐가 답이에요. 내 식습관에 잘 들어오는 맛과 용량이면 화려한 패키지보다 훨씬 오래 만족하게 됩니다."]},
          {"heading":"","paragraphs":[f"마지막으로 {label}의 실제 구성과 보관 방법을 상세 페이지에서 다시 확인하면 좋아요. 같은 제품명이라도 용량이나 묶음 수가 다르면 가격 비교가 완전히 달라집니다.",f"맛의 방향이 내 취향이고 {sp}도 부담스럽지 않다면 냉장고나 간식장에 두고 편하게 꺼내기 좋은 선택이에요. {react('s4')}"]}
        ]
        advantages=["맛·향 중심으로 취향 판단이 쉬움","용량과 수량을 섭취 패턴에 맞추기 좋음","보관 방법을 기준으로 구매량 조절 가능","영양정보와 원재료 비교가 쉬움","간식이나 식사 사이에 활용하기 편함"]
        conclusion=f"{desc} 제품은 결국 내 입맛과 생활 리듬에 잘 들어오는지가 가장 중요해요. 맛의 방향이 마음에 들고 {sp}을 무리 없이 소비할 수 있다면, 한 번 사고 끝나는 제품보다 자연스럽게 다시 찾게 되는 쪽에 가깝습니다."
    elif family in {"shampoo","cleanser","skincare"}:
        area="두피와 모발" if family=="shampoo" else "피부"
        act="샴푸할" if family=="shampoo" else ("세안할" if family=="cleanser" else "스킨케어 루틴에 바를")
        intro=[f"{desc}는 매일 {act} 때 쓰는 제품이라 첫인상보다 반복 사용에서 불편하지 않은지가 더 중요해요. {sp}이라면 한 통을 얼마나 오래 쓰는지도 같이 생각해볼 만합니다.",f"화장품은 향, 제형, 사용 뒤 느낌처럼 숫자로 설명하기 어려운 부분이 만족도를 크게 좌우하죠. {area} 타입에 따라 체감이 달라질 수 있으니 제품 설명과 성분표를 내 기준에 맞춰 보는 게 좋습니다. {react('intro')}"]
        sections=[
          {"heading":"","paragraphs":[f"처음 볼 때는 {act} 순간을 떠올려보세요. 손에 덜었을 때의 제형, 펴 바르거나 거품 내는 과정, 헹구거나 흡수시킨 뒤의 느낌이 내 루틴에 맞는지가 핵심입니다.",f"매일 쓰는 제품은 작은 편의가 오래 남아요. 뚜껑이나 펌프처럼 꺼내 쓰기 쉬운지까지 보면 실제 만족도를 가늠하기 좋습니다. {react('s1')}"]},
          {"heading":"","paragraphs":[f"{area}에 직접 닿는 만큼 향이 너무 강하지 않은지, 사용 뒤 건조함이나 무거움이 부담스럽지 않은지를 후기에서 살펴보세요. 특정 효능을 기대한다면 제품에 공식적으로 표시된 기능인지 확인하는 것도 중요합니다.",f"{sp}은 한 번 사서 오래 쓰는 구성이 될 수 있으니 내 사용량과 개봉 후 보관을 같이 생각하면 좋아요."]},
          {"heading":"","paragraphs":["비슷한 제품과 비교할 때는 유명세보다 내가 중요하게 보는 한두 가지를 맞춰보세요. 제형, 향, 용량, 사용 단계가 비슷한 제품끼리 놓으면 차이가 훨씬 잘 보여요.","아침과 저녁에 다른 제품을 쓰는 사람이라면 다른 단계와 겹치지 않는지도 체크해보세요. 루틴이 단순해야 꾸준히 손이 갑니다."]},
          {"heading":"","paragraphs":[f"구매 전에는 {label}의 정확한 용량과 수량을 확인하고, 내 {area} 타입에 맞지 않을 수 있는 성분이 있는지도 살펴보세요.",f"내 루틴에 자연스럽게 들어가고 향과 사용감도 취향에 맞는다면 매일 부담 없이 꺼내 쓰기 좋은 제품이 될 수 있어요. {react('s4')}"]}
        ]
        advantages=["매일 루틴에 넣기 쉬운 제품군","향·제형·사용감을 기준으로 비교 가능","용량을 사용 빈도에 맞춰 고르기 좋음","다른 스킨케어·헤어 단계와 조합하기 쉬움","보관과 사용 순서가 단순한지 확인하기 좋음"]
        conclusion=f"{desc}는 광고 문구보다 내 {area}와 루틴에 잘 맞는지가 답이에요. {sp}이 내 사용량과 맞고 향·제형·사용 뒤 느낌까지 원하는 방향이라면 꾸준히 손이 갈 가능성이 높은 선택입니다."
    elif family=="apparel":
        intro=[f"{desc} 제품은 사진이 예뻐도 실제로 입었을 때 핏과 소재가 마음에 들어야 손이 자주 가요. 사이즈표와 실측, 계절감을 먼저 보면 온라인에서도 실패를 많이 줄일 수 있습니다.",f"옷이나 잡화는 결국 가지고 있는 옷과 얼마나 쉽게 어울리는지가 중요하죠. 자주 입는 색과 신발을 떠올려보면 이 제품이 내 옷장에 들어왔을 때의 모습이 꽤 선명해져요. {react('intro')}"]
        sections=[{"heading":"","paragraphs":["가장 먼저 볼 건 핏이에요. 너무 붙거나 남지 않는지, 기장과 어깨·허리 위치가 내가 좋아하는 실루엣과 맞는지를 후기 사진과 실측으로 확인해보세요.",f"소재의 두께와 촉감도 계절에 따라 만족도가 크게 달라져요. {react('s1')}"]},{"heading":"","paragraphs":["출근, 주말 외출, 여행처럼 실제 입을 장면을 두세 개 떠올려보면 활용도가 보입니다. 한 번만 예쁘게 입는 옷보다 여러 코디에 자연스럽게 섞이는 쪽이 결국 손이 자주 가요.","세탁 방법과 구김 정도도 자주 입을 옷이라면 꼭 볼 부분이에요. 관리가 복잡하면 처음 마음에 들어도 점점 손이 멀어질 수 있습니다."]},{"heading":"","paragraphs":["비슷한 가격대 제품과는 소재, 안감, 마감, 포켓 같은 실제 사용 요소를 비교해보세요. 사진에서 잘 안 보이는 부분이 착용 만족도를 좌우하기도 합니다.","색상은 화면마다 조금 다르게 보일 수 있으니 구매 후기의 자연광 사진이 있다면 같이 보는 편이 좋아요."]},{"heading":"","paragraphs":[f"마지막으로 {label}의 선택 사이즈가 내가 확인한 실측과 같은지 다시 보세요. 옵션을 바꾸는 순간 색상이나 가격이 달라지는 경우도 있습니다.",f"핏과 소재가 취향에 맞고 기존 옷과 코디할 장면이 바로 떠오른다면, 이런 제품은 옷장에 들어간 뒤 생각보다 자주 손이 갈 수 있어요. {react('s4')}"]}]
        advantages=["핏과 실측 기준으로 사이즈 판단 가능","기존 옷과 코디 활용도를 보기 쉬움","소재와 두께로 계절감 확인 가능","세탁·관리 편의까지 비교 가능","일상에서 입을 장면을 떠올리기 쉬움"]
        conclusion=f"{desc} 제품은 화면 속 한 컷보다 내 체형과 평소 코디에 잘 맞는지가 더 중요해요. 실측과 소재가 마음에 들고 입을 장면이 여러 개 떠오른다면 충분히 활용도 높은 선택이 될 수 있습니다."
    elif family=="mobile_accessory":
        intro=[f"{desc} 제품은 스마트폰에 붙였을 때 카드 수납과 손에 잡히는 두께가 실제 만족도를 좌우해요. {sp}의 자석 부착 방식과 내 기기·케이스 호환 여부부터 확인하면 선택이 쉬워집니다.",f"맥세이프 카드지갑은 지갑을 따로 챙기지 않아도 자주 쓰는 카드를 휴대할 수 있다는 점이 눈에 들어와요. 다만 카드 장수와 케이스 두께에 따라 그립이 달라질 수 있으니 평소 사용 습관을 먼저 떠올려보세요. {react('intro')}"]
        sections=[
          {"heading":"","paragraphs":["가장 먼저 볼 부분은 자석 부착 안정성이에요. 스마트폰을 주머니나 가방에서 꺼낼 때 카드지갑이 쉽게 돌아가거나 밀리지 않는지, 사용하는 케이스가 맥세이프 자석을 지원하는지 확인해보세요.",f"슬림한 형태라도 카드 수납 후 실제 두께는 달라질 수 있어요. 손에 쥐었을 때 그립을 방해하지 않는지가 중요합니다. {react('s1')}"]},
          {"heading":"","paragraphs":["카드 포켓은 내가 넣을 카드 장수에 맞아야 해요. 교통카드와 결제카드처럼 꼭 필요한 카드만 넣을지, 꺼낼 때 손가락으로 밀어 올리기 쉬운 구조인지 상세 이미지를 살펴보면 좋습니다.","카드를 너무 많이 넣으면 수납부가 벌어지거나 자석 결합력이 체감상 약해질 수 있어요. 제품에 안내된 권장 수납량을 지키는 편이 안정적입니다."]},
          {"heading":"","paragraphs":["접착식 카드 포켓과 비교하면 맥세이프 방식은 필요할 때 떼어낼 수 있다는 점이 편해요. 무선 충전이나 차량 거치대를 쓸 때 분리해야 하는지도 함께 확인하면 사용 흐름이 더 선명해집니다.","표면 소재는 손에 닿는 촉감뿐 아니라 카드지갑의 마모와 오염 관리에도 영향을 줘요. 밝은 색은 이염 가능성, 모서리는 마감 상태를 후기 사진으로 비교해보세요."]},
          {"heading":"","paragraphs":[f"구매 전에는 {label}이 내 스마트폰 모델과 케이스에 맞는지, 카드 수납량과 자석 방식이 상세 설명과 같은지 다시 확인하세요.",f"호환성이 맞고 필요한 카드만 슬림하게 수납할 수 있다면 외출할 때 지갑을 따로 찾는 번거로움을 줄여주는 액세서리가 될 수 있어요. {react('s4')}"]}
        ]
        advantages=["자주 쓰는 카드를 스마트폰과 함께 휴대 가능","맥세이프 방식이라 필요할 때 탈착하기 쉬움","카드 수납량과 두께를 사용 습관에 맞춰 비교 가능","기기·케이스 호환 여부를 명확히 확인 가능","슬림한 외출 구성을 만들기 편함"]
        conclusion=f"{desc} 제품은 카드 수납량과 자석 안정성, 스마트폰 케이스 호환성이 모두 맞아야 편해요. 실제로 넣을 카드 장수와 손에 잡히는 두께까지 확인했다면 매일 휴대하기 좋은 실용적인 구성이 될 수 있습니다."
    elif family=="digital":
        intro=[f"{desc} 제품은 스펙 숫자가 많아 보여도 실제로는 설치, 연결, 충전처럼 매번 반복하는 과정이 편해야 만족도가 높아요. 내가 주로 어디에서 쓸지부터 정하면 볼 항목이 훨씬 줄어듭니다.",f"전자제품은 처음 며칠보다 한 달 뒤에도 귀찮지 않게 쓰는지가 중요하죠. 크기와 무게, 전원 방식, 호환성을 먼저 확인해두면 구매 뒤 당황할 일이 줄어요. {react('intro')}"]
        sections=[{"heading":"","paragraphs":["처음에는 설치와 연결 방식부터 보세요. 별도 앱이나 케이블이 필요한지, 내가 쓰는 기기와 바로 호환되는지를 확인하면 실제 사용 난이도가 보입니다.",f"충전 제품이라면 배터리와 충전 시간을 내 사용 패턴에 맞춰 보는 것도 중요해요. {react('s1')}"]},{"heading":"","paragraphs":["책상, 거실, 차 안처럼 둘 장소에 맞는 크기인지도 체크해보세요. 휴대가 목적이라면 무게와 케이블 보관까지 같이 봐야 진짜 편합니다.","소음이나 발열처럼 스펙표 한 줄로 체감하기 어려운 부분은 후기에서 반복해서 언급되는지 살펴보는 편이 좋아요."]},{"heading":"","paragraphs":["비슷한 제품과는 최대 성능보다 내가 실제로 쓸 기능을 맞춰 비교하세요. 필요 없는 기능 때문에 가격만 올라가면 체감 만족도는 크지 않을 수 있습니다.","반대로 매일 쓰는 기능이라면 버튼 위치나 연결 안정성 같은 작은 차이에 비용을 더 쓰는 게 오히려 편할 수 있어요."]},{"heading":"","paragraphs":[f"구매 전에는 {label}의 정확한 모델명과 구성품을 다시 확인하세요. 이름이 비슷해도 세대나 옵션에 따라 성능과 호환성이 달라질 수 있습니다.",f"내 환경과 호환되고 반복 사용이 번거롭지 않다면 스펙 경쟁보다 훨씬 현실적인 만족을 주는 제품이 될 수 있어요. {react('s4')}"]}]
        advantages=["설치·연결 방식으로 사용 난이도 판단 가능","크기와 무게를 사용 장소에 맞추기 쉬움","충전·배터리 조건을 생활 패턴과 비교 가능","필요한 기능만 골라 가격을 비교하기 좋음","모델명과 호환성 확인 기준이 분명함"]
        conclusion=f"{desc} 제품은 숫자가 가장 높은 제품보다 내 환경에서 바로 잘 작동하는 제품이 더 좋은 선택일 때가 많아요. 연결 방식과 호환성, 크기까지 맞는다면 매일 꺼내 쓰기 편한 쪽으로 만족도가 남습니다."
    else:
        intro=[f"{desc} 제품을 고를 때는 상품명만 오래 보는 것보다 실제로 어디에서 어떻게 쓸지를 먼저 떠올리는 게 이해가 빨라요. {sp}도 내 사용 빈도와 맞는지 같이 보면 좋습니다.",f"매일 손이 갈 물건이라면 작은 불편이 반복되지 않는지가 중요해요. 크기, 보관, 관리 방법처럼 생활에 바로 닿는 부분부터 보면 제품이 나와 맞는지 꽤 선명해집니다. {react('intro')}"]
        sections=[{"heading":"","paragraphs":["처음에는 제품의 기본 쓰임새와 크기를 확인해보세요. 내가 둘 공간이나 들고 다닐 상황과 맞지 않으면 좋은 기능이 많아도 불편해질 수 있습니다.",f"자주 꺼내 쓸 제품일수록 준비와 정리가 단순한 게 좋아요. {react('s1')}"]},{"heading":"","paragraphs":[f"{sp}은 한 번에 너무 많거나 적지 않은지 내 사용량을 기준으로 보면 좋아요. 보관 공간까지 생각하면 대용량이 항상 이득인 것은 아닙니다.","손이 자주 닿는 부분의 재질과 관리 방법도 확인하면 오래 쓰기 편한지 판단할 수 있어요."]},{"heading":"","paragraphs":["비슷한 제품과는 같은 용도와 구성끼리 비교하세요. 가격만 낮은 다른 옵션을 같은 제품으로 착각하면 실제 만족도가 크게 달라질 수 있습니다.","내가 꼭 필요한 기능 한두 가지가 분명하면 제품 선택이 훨씬 쉬워져요. 나머지는 있으면 좋은 정도로 두는 편이 현실적입니다."]},{"heading":"","paragraphs":[f"마지막으로 {label}의 실제 선택 옵션과 수량을 확인하고, 배송이나 보관 조건까지 내 상황과 맞는지 보세요.",f"쓸 장면이 바로 떠오르고 관리도 어렵지 않다면 생활 속에서 자연스럽게 손이 가는 제품이 될 수 있습니다. {react('s4')}"]}]
        advantages=["기본 쓰임새를 기준으로 판단하기 쉬움","크기와 구성 수량을 생활에 맞추기 편함","보관·관리 방법을 구매 전에 확인 가능","비슷한 제품과 같은 조건으로 비교하기 좋음","반복 사용에서의 편의성을 생각하기 쉬움"]
        conclusion=f"{desc} 제품은 결국 내 생활에 자연스럽게 들어오는지가 가장 중요해요. {sp}이 부담스럽지 않고 쓸 장소와 관리 방법까지 머릿속에 그려진다면 충분히 실용적인 선택이 될 수 있습니다."

    sections=enforce_section_subkeywords(sections,name,subkeywords)
    return {"title":build_title(name,subkeywords,category),"intro":intro,
            "tags":build_tags(name,category,subkeywords,int(settings().get("tags_count",30))),
            "sections":sections,"advantages":advantages[:5],"conclusion":conclusion,
            "generation_source":"safe_product_family_fallback"}

def normalize_content_obj(obj,name,category,subkeywords):
    """Normalize LLM output without replacing it with generic fallback prose.

    v7.64 treated a good-but-short model draft as a failure and silently swapped
    the entire article for the emergency fragment generator. That generator is
    exactly what produced the user's incomprehensible Dove example. v7.65 keeps
    model prose, validates structure, and lets run_text retry instead of publishing
    a generic substitute.
    """
    if not isinstance(obj,dict):raise ValueError("LLM JSON 객체 아님")
    intro=obj.get("intro") if isinstance(obj.get("intro"),list) else []
    intro=[str(x).strip() for x in intro if str(x).strip()][:3]
    secs=obj.get("sections") if isinstance(obj.get("sections"),list) else []
    clean_secs=[]
    for sec in secs[:4]:
        if not isinstance(sec,dict):continue
        paras=[str(x).strip() for x in (sec.get("paragraphs") or []) if str(x).strip()]
        clean_secs.append({"heading":str(sec.get("heading") or "").strip(),"paragraphs":paras[:3]})
    adv=obj.get("advantages") if isinstance(obj.get("advantages"),list) else []
    adv=[str(x).strip() for x in adv if str(x).strip()][:5]
    conclusion=str(obj.get("conclusion") or "").strip()
    if len(intro)<1:raise ValueError("도입 문단 누락")
    if len(clean_secs)<4 or any(len(x.get("paragraphs") or [])<1 for x in clean_secs):raise ValueError("본문 4개 섹션/문단 누락")
    if len(adv)<4:raise ValueError("장점 요약 부족")
    if not conclusion:raise ValueError("결론 누락")
    clean_secs=enforce_section_subkeywords(clean_secs,name,subkeywords)
    ai_title=str(obj.get("title") or "").strip()
    ai_tags=obj.get("tags") if isinstance(obj.get("tags"),list) else []
    result={"title":build_title(name,subkeywords,category,ai_title=ai_title),"intro":intro,"sections":clean_secs,
            "advantages":adv,"conclusion":conclusion,
            "tags":build_tags(name,category,subkeywords,int(settings().get("tags_count",30)),ai_tags=ai_tags),
            "naver_subkeywords":list(subkeywords or []),"heading_subkeywords":heading_subkeyword_terms(name,subkeywords,4),
            "ai_raw_title":ai_title,"ai_raw_tags":[str(x) for x in ai_tags[:40]]}
    return result

def _mobile_visual_lines(text, max_chars=None, min_tail=None):
    """Turn prose into deterministic mobile-width visual lines without splitting words."""
    cfg=settings()
    max_chars=int(max_chars or cfg.get("blog_mobile_line_max_chars",22))
    min_tail=int(min_tail or cfg.get("blog_mobile_line_min_tail_chars",8))
    max_chars=max(14,min(30,max_chars));min_tail=max(4,min(max_chars-2,min_tail))
    text=re.sub(r"\s+"," ",str(text or "")).strip()
    if not text:return []
    sentence_parts=[];start=0
    for m in re.finditer(r"[.!?。！？]+(?:[\"'”’)]*)",text):
        end=m.end();part=text[start:end].strip()
        if part:sentence_parts.append(part)
        start=end
    tail=text[start:].strip()
    if tail:sentence_parts.append(tail)
    if not sentence_parts:sentence_parts=[text]
    lines=[]
    for part in sentence_parts:
        words=part.split()
        if not words:continue
        local=[];cur=""
        for w in words:
            cand=w if not cur else cur+" "+w
            if cur and len(cand)>max_chars:
                local.append(cur);cur=w
            else:cur=cand
        if cur:local.append(cur)
        if len(local)>=2 and len(local[-1])<min_tail:
            prev=local[-2].split();last=local[-1]
            while len(prev)>1 and len(last)<min_tail:
                moved=prev.pop();candidate=moved+" "+last
                if len(candidate)>max_chars:break
                last=candidate
            local[-2]=" ".join(prev);local[-1]=last
        lines.extend(x for x in local if x.strip())
    return lines

def compose_post(obj,images,price_img=None,sharelink=""):
    """Reference layout with exactly one disclosure as the absolute top block."""
    blocks=[canonical_disclosure_block()]
    if sharelink:
        blocks.append({"type":"sharelink","url":str(sharelink),"position":"top_after_disclosure","source":"coupang_partners"})
    for p in obj.get("intro") or []:
        chunks=_mobile_visual_lines(p)
        blocks.append({"type":"paragraph","lines":chunks or [str(p).strip()],"layout":"mobile_center","role":"intro"})
    slots=list(obj.get("reference_layout_slots") or ["after_intro","after_section_1","after_section_2"])[:3]
    img_index=0
    def emit_slot(slot):
        nonlocal img_index
        while img_index<len(images) and img_index<len(slots) and slots[img_index]==slot:
            blocks.append({"type":"image","file":Path(images[img_index]).name,"slot":slot});img_index+=1
    emit_slot("after_intro")
    secs=obj.get("sections",[])
    for i,s in enumerate(secs):
        blocks.append({"type":"heading","text":s.get("heading",""),"format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center","section_index":i})
        for p in s.get("paragraphs",[]):
            chunks=_mobile_visual_lines(p)
            blocks.append({"type":"paragraph","lines":chunks or [str(p).strip()],"layout":"mobile_center","section_index":i})
        emit_slot(f"after_section_{i+1}")
    # If the reference HTML could not expose all image positions, keep any
    # remaining verified images before the advantages rather than dropping them.
    while img_index<len(images):
        slot=slots[img_index] if img_index<len(slots) else f"before_advantages_{img_index+1}"
        blocks.append({"type":"image","file":Path(images[img_index]).name,"slot":slot});img_index+=1
    blocks.append({"type":"heading","text":"✔ 장점 요약","format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center"})
    for a in obj.get("advantages",[])[:5]:blocks.append({"type":"check","text":"✔ "+a,"format":"bold_bg_exact","background_hex":"#fff8b2","bold":True,"align":"center"})
    conclusion=str(obj.get("conclusion","") or "").strip()
    blocks.append({"type":"paragraph","lines":_mobile_visual_lines(conclusion) or ([conclusion] if conclusion else []),"layout":"mobile_center","role":"conclusion"})
    # v7.63 final: the SAME verified Coupang Partners deeplink is repeated at
    # both edges of the article.  Keeping the link as explicit blocks prevents
    # image reordering/mobile reflow from accidentally moving or dropping it.
    if sharelink:
        blocks.append({"type":"sharelink","url":str(sharelink),"position":"bottom","source":"coupang_partners"})
    blocks=normalize_disclosure_blocks(blocks)
    return {"title":obj.get("title",""),"blocks":blocks,"tags":obj.get("tags",[])[:30],"sharelink":sharelink,"price_compare_image":price_img,
            "reference_blog_url":REFERENCE_BLOG_URL,"reference_layout_slots":slots,"layout_policy":"V8_04_DISCLOSURE_TOP_ONCE_THEN_SHARELINK"}

def crop_whitespace(path):
    im=Image.open(path).convert("RGB")
    bg=Image.new("RGB",im.size,im.getpixel((0,0)))
    diff=ImageChops.difference(im,bg).convert("L")
    box=diff.getbbox()
    if box:
        im=im.crop(box)
    im.save(path,"JPEG",quality=94)

def crop_detail_margins(path,image_role=""):
    """Safely trim uniform padding from downloaded seller detail images."""
    if not str(image_role or "").startswith("detail_"):return False
    im=Image.open(path).convert("RGB")
    if im.width<240 or im.height<240:return False
    corners=[im.getpixel((0,0)),im.getpixel((im.width-1,0)),
             im.getpixel((0,im.height-1)),im.getpixel((im.width-1,im.height-1))]
    bg=tuple(sorted(x[i] for x in corners)[len(corners)//2] for i in range(3))
    diff=ImageChops.difference(im,Image.new("RGB",im.size,bg)).convert("L")
    box=diff.point(lambda value:255 if value>14 else 0).getbbox()
    if not box:return False
    pad=max(6,min(24,int(min(im.size)*0.018)))
    left=max(0,box[0]-pad);top=max(0,box[1]-pad)
    right=min(im.width,box[2]+pad);bottom=min(im.height,box[3]+pad)
    if right-left<im.width*0.62 or bottom-top<im.height*0.62:return False
    if left<4 and top<4 and right>im.width-4 and bottom>im.height-4:return False
    im.crop((left,top,right,bottom)).save(path,"JPEG",quality=94)
    return True

def product_visual_metrics(path):
    """Estimate whether a detail crop visibly contains a product/photo, not a text sheet.

    This is deliberately used only for DETAIL crops. Gallery/title images are
    trusted after exact-product page validation because white/black products can
    legitimately be low-saturation. The rejection gate targets examples such as
    legal/specification sheets: mostly white + nearly grayscale + dense text edges.
    """
    im=Image.open(path).convert("RGB")
    original_size=im.size
    probe=im.copy();probe.thumbnail((128,128),Image.Resampling.LANCZOS)
    px=list(probe.getdata());n=max(1,len(px))
    white=sum(1 for r,g,b in px if r>=240 and g>=240 and b>=240)/n
    near_white=sum(1 for r,g,b in px if r>=224 and g>=224 and b>=224)/n
    sat=sum(1 for r,g,b in px if max(r,g,b)-min(r,g,b)>=24)/n
    colorfulness=sum(max(r,g,b)-min(r,g,b) for r,g,b in px)/n
    gray=probe.convert("L")
    edge=gray.filter(ImageFilter.FIND_EDGES)
    edge_ratio=sum(1 for v in edge.getdata() if v>=42)/n
    entropy=float(gray.entropy())
    # Large photo/object areas tend to create denser non-white cells than text
    # lines. Measure occupancy in a coarse 8x8 grid without an OpenCV dependency.
    gw=gh=8;dense=0;occupied=0
    w,h=probe.size
    for gy in range(gh):
        for gx in range(gw):
            x0=gx*w//gw;x1=max(x0+1,(gx+1)*w//gw)
            y0=gy*h//gh;y1=max(y0+1,(gy+1)*h//gh)
            cell=probe.crop((x0,y0,x1,y1));cpx=list(cell.getdata())
            occ=sum(1 for r,g,b in cpx if not (r>=238 and g>=238 and b>=238))/max(1,len(cpx))
            if occ>=0.18:occupied+=1
            if occ>=0.55:dense+=1
    dense_ratio=dense/64.0;occupied_ratio=occupied/64.0
    document_like=(white>=0.43 and sat<0.012 and colorfulness<4.5 and edge_ratio>=0.24)
    # A softer second gate catches gray instruction/barcode pages with a bit of
    # anti-aliasing/color contamination but almost no photographic region.
    text_sheet_like=(near_white>=0.58 and sat<0.025 and colorfulness<7.0 and dense_ratio<0.34 and edge_ratio>=0.27)
    # Downsampling can lower the edge ratio of barcodes/small Korean text. A
    # very white, grayscale, low-entropy page with many thin edges is still a
    # document sheet even when it misses the older 0.27 edge threshold.
    barcode_or_label_sheet=(near_white>=0.72 and sat<0.018 and colorfulness<5.0 and
                            occupied_ratio<0.55 and dense_ratio<0.30 and
                            edge_ratio>=0.10 and entropy<4.5)
    score=(sat*4.4)+(min(colorfulness,60)/60.0*2.0)+((1-white)*1.25)+(dense_ratio*1.1)+(occupied_ratio*0.45)+(max(0.0,0.34-edge_ratio)*0.7)+(min(entropy,8)/8*0.35)
    ok=not (document_like or text_sheet_like or barcode_or_label_sheet)
    return {"ok":ok,"score":round(score,5),"white_ratio":round(white,4),"near_white_ratio":round(near_white,4),
            "saturation_ratio":round(sat,4),"colorfulness":round(colorfulness,3),"edge_ratio":round(edge_ratio,4),
            "entropy":round(entropy,3),"dense_ratio":round(dense_ratio,4),"occupied_ratio":round(occupied_ratio,4),
            "document_like":document_like,"text_sheet_like":text_sheet_like,
            "barcode_or_label_sheet":barcode_or_label_sheet,"size":original_size}


def _detail_product_crop_candidates(path, work_dir, max_candidates=10):
    """Create product-visible crops from one detail image.

    A long seller detail can be one giant image. Rather than saving the whole
    poster or arbitrary top/middle/bottom slices, scan overlapping portrait
    windows and rank them by product_visual_metrics. This turns a long detail
    poster into blog-usable crops similar to the user's requested example.
    """
    src=Image.open(path).convert("RGB")
    w,h=src.size;work_dir=Path(work_dir);work_dir.mkdir(parents=True,exist_ok=True)
    specs=[]
    if h <= int(w*2.15):
        specs=[(0,0,w,h)]
    else:
        win=max(int(w*1.45),min(int(w*1.85),1200))
        win=min(h,max(360,win))
        # More candidate positions than output slots; product-rich regions win.
        count=max(5,min(13,int((h-win)/max(1,win*.34))+1))
        maxoff=max(0,h-win)
        for i in range(count):
            y=int(round(maxoff*(i/max(1,count-1))))
            specs.append((0,y,w,min(h,y+win)))
    rows=[]
    for i,box in enumerate(specs[:max(1,int(max_candidates))],start=1):
        c=src.crop(box)
        cp=work_dir/f"_product_crop_{i:02d}.jpg"
        c.save(cp,"JPEG",quality=95)
        m=product_visual_metrics(cp);m.update(path=str(cp),box=box,index=i)
        if m.get("ok"):rows.append(m)
        else:cp.unlink(missing_ok=True)
    src.close()
    rows.sort(key=lambda x:-float(x.get("score") or 0))
    # Seller detail pages very often introduce the actual product near the top.
    # Preserve the earliest clearly product-like window first (the user's desired
    # "long detail -> useful top product crop" pattern), then fill with the
    # visually strongest spatially different sections.
    chosen=[]
    early=sorted(rows,key=lambda x:x["box"][1])
    intro=next((r for r in early if float(r.get("score") or 0)>=2.35 and (float(r.get("saturation_ratio") or 0)>=0.055 or float(r.get("colorfulness") or 0)>=9.0)),None)
    if intro:chosen.append(intro)
    for r in rows:
        if len(chosen)>=3:break
        if r in chosen:continue
        y0=r["box"][1];y1=r["box"][3]
        if any(abs(y0-c["box"][1]) < max(120,(y1-y0)*0.34) for c in chosen):continue
        chosen.append(r)
    keep={Path(r['path']).name for r in chosen}
    for r in rows:
        rp=Path(r['path'])
        if rp.name not in keep:rp.unlink(missing_ok=True)
    return chosen

def _download_image(url,out,referer=None):
    """Download a normal external image with anti-hotlink friendly retries.

    v8.08.42: many Google-discovered retailer/CDN images reject a single naked
    urllib request even though the same image is visible in Chrome. Try the
    verified source page as Referer first, then its origin and finally no
    Referer. Google thumbnails are still never accepted here; only original
    URLs discovered from a validated product source page reach this function.
    """
    if not url:return False
    url=str(url or '').strip()
    if url.startswith('//'):url='https:'+url
    refs=[]
    if referer:
        refs.append(str(referer))
        try:
            from urllib.parse import urlsplit
            u=urlsplit(str(referer));origin=f"{u.scheme}://{u.netloc}/" if u.scheme and u.netloc else ''
            if origin and origin not in refs:refs.append(origin)
        except Exception:pass
    # NAVER Image API returns the original CDN URL but not the source-page URL.
    # Many CDNs accept a same-origin Referer even when a naked request is 403.
    try:
        from urllib.parse import urlsplit
        iu=urlsplit(url);image_origin=f"{iu.scheme}://{iu.netloc}/" if iu.scheme and iu.netloc else ''
        if image_origin and image_origin not in refs:refs.append(image_origin)
    except Exception:pass
    refs.append(None)
    errors=[]
    for ref in refs:
        try:
            headers={
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
                "Accept":"image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Language":"ko-KR,ko;q=0.9,en;q=0.7",
                "Cache-Control":"no-cache",
            }
            if ref:headers["Referer"]=ref
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=25) as r:
                ctype=str(r.headers.get('Content-Type') or '').lower()
                data=r.read(16*1024*1024)
            if len(data)<1800 or 'text/html' in ctype or 'application/json' in ctype:
                raise ValueError(f"이미지 응답 아님 {ctype} {len(data)} bytes")
            import io
            im=Image.open(io.BytesIO(data));im.load();im=ImageOps.exif_transpose(im).convert("RGB")
            md=int(settings().get("image_min_dimension",180))
            if im.width<md or im.height<md:raise ValueError(f"해상도 부족 {im.width}x{im.height}")
            im.thumbnail((1600,1600));Path(out).parent.mkdir(parents=True,exist_ok=True);im.save(out,"JPEG",quality=94)
            return True
        except Exception as e:
            errors.append(str(e));Path(out).unlink(missing_ok=True)
    log("이미지 다운로드 실패: "+" / ".join(errors[-4:]))
    return False

def _download_toss_product_image(url,out,page_url=""):
    """Download Toss thumbnail/gallery image with CDN/referer fallbacks."""
    url=str(url or "").strip()
    if not url:return {"ok":False,"reason":"URL 없음"}
    if url.startswith("//"):url="https:"+url
    refs=[]
    for ref in (page_url,"https://toss.shopping/","https://sharelink.toss.im/",None):
        if ref not in refs:refs.append(ref)
    errors=[]
    for ref in refs:
        try:
            headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
                     "Accept":"image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8","Accept-Language":"ko-KR,ko;q=0.9,en;q=0.7"}
            if ref:headers["Referer"]=str(ref)
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=float(settings().get("toss_image_download_timeout_sec",22))) as rr:
                data=rr.read(14*1024*1024);ctype=str(rr.headers.get("Content-Type") or "").lower()
            if len(data)<1800 or "text/html" in ctype or "application/json" in ctype:raise ValueError(f"이미지 응답 아님 {ctype} {len(data)} bytes")
            import io
            im=Image.open(io.BytesIO(data));im.load();im=ImageOps.exif_transpose(im).convert("RGB")
            md=int(settings().get("image_min_dimension",180))
            if im.width<md or im.height<md:raise ValueError(f"해상도 부족 {im.width}x{im.height}")
            im.thumbnail((1600,1600));Path(out).parent.mkdir(parents=True,exist_ok=True);im.save(out,"JPEG",quality=94)
            return {"ok":True,"referer":ref or "none","width":im.width,"height":im.height}
        except Exception as e:
            errors.append(str(e));Path(out).unlink(missing_ok=True)
    return {"ok":False,"reason":" / ".join(errors[-4:])}


def _download_source_image(rec,out):
    """Download verified product images with marketplace-specific retries."""
    platform=str(rec.get("platform") or "")
    url=str(rec.get("url") or "")
    if platform=="쿠팡" or "coupang" in url.lower() or rec.get("kind")=="coupang_partners_api_search" or rec.get("source")=="coupang_partners_api":
        result=coupang_partners_api.download_product_image(
            url,out,rec.get("page_url"),
            min_dimension=int(settings().get("image_min_dimension",180)),
            timeout=float(settings().get("coupang_image_download_timeout_sec",25)))
        if not result.get("ok"):log("쿠팡 이미지 다운로드 실패: "+str(result.get("reason") or ""))
        return bool(result.get("ok"))
    if platform=="토스쇼핑" or "toss.shopping" in url.lower() or "static.toss" in url.lower():
        result=_download_toss_product_image(url,out,rec.get("page_url") or "")
        if not result.get("ok"):log("토스 이미지 다운로드 실패: "+str(result.get("reason") or ""))
        return bool(result.get("ok"))
    if platform=="네이버이미지API" or rec.get("kind")=="naver_image_search_api":
        if _download_image(url,out,rec.get("page_url") or None):return True
        thumb=str(rec.get("thumbnail") or "").strip()
        if thumb and thumb!=url and _download_image(thumb,out,"https://search.naver.com/"):return True
        log("NAVER 이미지 API 원본/썸네일 다운로드 모두 실패: "+url[:180]);return False
    return _download_image(url,out,rec.get("page_url"))

def _download_detail_source_image(rec,out):
    """Download a detail poster while preserving its long vertical resolution."""
    url=str(rec.get("url") or "").strip()
    if not url:return False
    if url.startswith("//"):url="https:"+url
    refs=[]
    platform=str(rec.get("platform") or "")
    home=("https://toss.shopping/" if platform=="토스쇼핑" else "https://www.coupang.com/")
    for ref in (rec.get("page_url"),home,None):
        if ref not in refs:refs.append(ref)
    errors=[]
    for ref in refs:
        try:
            headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
                     "Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8","Accept-Language":"ko-KR,ko;q=0.9,en;q=0.7"}
            if ref:headers["Referer"]=str(ref)
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=float(settings().get("coupang_image_download_timeout_sec",25))) as rr:
                data=rr.read(18*1024*1024);ctype=str(rr.headers.get("Content-Type") or "").lower()
            if len(data)<1500 or "text/html" in ctype or "application/json" in ctype:raise ValueError("이미지가 아닌 상세 응답")
            import io
            im=Image.open(io.BytesIO(data));im.load();im=ImageOps.exif_transpose(im).convert("RGB")
            if im.width<int(settings().get("image_min_dimension",180)) or im.height<int(settings().get("image_min_dimension",180)):
                raise ValueError(f"상세 해상도 부족 {im.width}x{im.height}")
            # Preserve tall detail resolution for sliding-window crop extraction.
            scale=min(1.0,2200/max(1,im.width),14000/max(1,im.height))
            if scale<1.0:
                im=im.resize((max(180,int(im.width*scale)),max(180,int(im.height*scale))),Image.Resampling.LANCZOS)
            Path(out).parent.mkdir(parents=True,exist_ok=True);im.save(out,"JPEG",quality=95)
            return True
        except Exception as e:
            errors.append(str(e));Path(out).unlink(missing_ok=True)
    log("상세 원본 이미지 다운로드 실패: "+" / ".join(errors[-3:]))
    return False

def _site_from_url(url):
    u=(url or "").lower()
    if "coupang" in u:return "쿠팡"
    if "naver" in u:return "네이버쇼핑"
    if "toss" in u:return "토스쇼핑"
    return ""

def _same_product_candidate_rows(con,product):
    """Only candidate rows that pass the same-product/same-variant gate."""
    threshold=float(settings().get("image_match_threshold",0.58))
    rows=con.execute("""SELECT image_url,url,platform,name,rank_no,category FROM candidates
                        WHERE category=? ORDER BY rank_no,id""",(product["category"],)).fetchall()
    good=[]
    for r in rows:
        ok,score,detail=strict_product_accept(r["name"],product["name"],threshold)
        mode="strict"
        if not ok and settings().get("image_snapshot_relaxed_match",True):
            relaxed=float(settings().get("image_snapshot_match_threshold",0.43))
            if not (detail.get("missing") or []) and bool(detail.get("core_hit")) and score>=relaxed:
                ok=True;mode="snapshot_relaxed"
        if ok:
            good.append({"image_url":r["image_url"] or "","url":r["url"] or "",
                         "platform":r["platform"],"name":r["name"],"rank_no":r["rank_no"],
                         "score":score,"match_detail":detail,"match_mode":mode})
    sources=[x.strip() for x in (product["source_platform"] or "").split(",") if x.strip()]
    priority={x:i for i,x in enumerate(sources)}
    good.sort(key=lambda x:(priority.get(x["platform"],99),-x["score"],x["rank_no"] or 999))
    return good

_COUPANG_DETAIL_BLOCKED_UNTIL=0.0
_COUPANG_DETAIL_LAST_FINISH=0.0
_COUPANG_DETAIL_PACE_LOCK=threading.Lock()

def _pace_coupang_detail(cfg):
    """Keep direct product-page visits far enough apart to avoid burst errors."""
    global _COUPANG_DETAIL_LAST_FINISH
    base=max(0.0,float(cfg.get("coupang_detail_between_products_sec",10.0)))
    jitter=max(0.0,float(cfg.get("coupang_detail_jitter_sec",2.0)))
    with _COUPANG_DETAIL_PACE_LOCK:
        wait=max(0.0,base-(time.monotonic()-_COUPANG_DETAIL_LAST_FINISH))
        if wait>0:
            wait+=random.uniform(0.0,jitter)
            log(f"쿠팡 상세 이미지 안정 대기 {wait:.1f}초")
            time.sleep(wait)

def _is_direct_coupang_product_url(url):
    return bool(coupang_product_id(str(url or "")))


def _coupang_api_product_url(url: str, identifier: str) -> str:
    identifier=identifier.strip()
    direct_id=coupang_product_id(url)
    if direct_id:
        return url if not identifier or identifier==direct_id else ""
    if identifier.isdigit() and (not url or coupang_partners_api._valid_affiliate_url(url)):
        return f"https://www.coupang.com/vp/products/{identifier}"
    return ""

def _is_direct_market_product_url(url,site):
    """Known direct product URL only; never issue a new marketplace search here."""
    try:
        u=urllib.parse.urlparse(str(url or ""));host=(u.netloc or "").lower();path=(u.path or "").lower();q=(u.query or "").lower()
        if site=="쿠팡":return _is_direct_coupang_product_url(url)
        if site=="네이버쇼핑":
            if "search.shopping.naver.com" in host and "/catalog/" in path:return True
            if host.endswith("smartstore.naver.com") or host.endswith("brand.naver.com"):
                return "/products/" in path or "/product/" in path
            if "shopping.naver.com" in host and ("/products/" in path or "/catalog/" in path):return True
            return False
        if site=="토스쇼핑":
            # Official Sharelink productUrl currently resolves to toss.shopping/t/{id}.
            # Keep legacy toss.im URLs as well.
            if host=="toss.shopping" or host.endswith(".toss.shopping"):
                return path.startswith("/t/") or "product" in path or "item" in path or "goods" in path or bool(q)
            return host.endswith("toss.im") and ("product" in path or "item" in path or "goods" in path or bool(q))
    except Exception:pass
    return False

def _resolve_coupang_product_link(product,cfg,repair_mode=False):
    """Resolve Coupang via Partners API only: full name -> core keywords.

    Returns strict matches first. If the API has plausible but incomplete titles,
    keep up to two `near_candidates`; those are NEVER accepted immediately and
    must pass the full product-page identity check before their images are used.
    The returned diagnostics distinguish: no API rows vs rows-but-mismatch vs
    near candidate requiring page confirmation.
    """
    if not cfg.get("image_coupang_core_search_resolver_enabled",True):
        return {"ok":False,"reason_code":"RESOLVER_DISABLED","reason":"쿠팡 API 핵심키워드 링크 보강 비활성"}
    maxq=int(cfg.get("image_coupang_core_search_max_queries_repair",9) if repair_mode else cfg.get("image_coupang_core_search_max_queries",7))
    state={"ok":False,"api_only":True,"queries":[],"diagnostics":[],"near_candidates":[],
           "reason_code":"NO_API_RESULTS","reason":"쿠팡 Partners API 검색결과 없음","rows_seen":0,"strict_matches":0}
    if not coupang_partners_api.ready():
        state.update(reason_code="API_NOT_READY",reason="쿠팡 Partners API 키 미설정")
        return state
    try:
        qs=[]
        for q in (coupang_partners_api.query_variants(product["name"],max_count=maxq)+
                  coupang_partners_api.sharelink_query_variants(product["name"],max_count=maxq)):
            q=str(q or "").strip()
            if q and q not in qs:qs.append(q)
            if len(qs)>=maxq:break
        state["queries"]=qs
        seen=set();strict=[];near=[];errors=[]
        for qi,q in enumerate(qs):
            try:rows=coupang_partners_api.search(q,limit=15,use_cache=not repair_mode)
            except Exception as e:
                errors.append(f"{q}: {e}");state["diagnostics"].append({"query":q,"query_index":qi,"error":str(e),"result_count":0});continue
            qdiag={"query":q,"query_index":qi,"result_count":len(rows),"accepted":0,"near":0,"rejected":[]}
            state["rows_seen"]+=len(rows)
            for r in rows:
                key=r.get("product_id") or ((r.get("name") or "")+"|"+(r.get("url") or ""))
                if key in seen:continue
                seen.add(key);candidate=r.get("name") or ""
                ok,score,detail=_balanced_exact_product_accept(candidate,product["name"])
                product_url=_coupang_api_product_url(str(r.get("url") or ""),str(r.get("product_id") or ""))
                if not product_url:
                    qdiag["rejected"].append({"candidate":candidate[:120],"reason":"쿠팡 API 상품 URL·ID 연결 불일치 또는 없음"});continue
                rec={"query":q,"candidate":candidate,"score":score,"url":product_url,"image_url":r.get("image_url") or "",
                     "product_id":r.get("product_id") or "","match_detail":detail}
                if ok:
                    rec["match_mode"]="strict";strict.append(rec);qdiag["accepted"]+=1;continue
                nok,nscore,ndetail=_near_product_candidate_assessment(candidate,product["name"])
                if nok:
                    rec.update(score=nscore,match_detail=ndetail,match_mode="near_page_confirm");near.append(rec);qdiag["near"]+=1
                else:
                    qdiag["rejected"].append({"candidate":candidate[:120],"score":nscore,"reason":_reject_reason_from_detail(ndetail),"detail":ndetail})
            qdiag["rejected"]=qdiag["rejected"][:8];state["diagnostics"].append(qdiag)
        state["errors"]=errors[-8:];state["strict_matches"]=len(strict)
        strict.sort(key=lambda x:(-float(x.get("score") or 0), qs.index(x.get("query")) if x.get("query") in qs else 99))
        near.sort(key=lambda x:(-float(x.get("score") or 0), qs.index(x.get("query")) if x.get("query") in qs else 99))
        # De-dupe near URLs, keeping only two page-confirmation candidates.
        nseen=set();near_out=[]
        for x in near:
            u=x.get("url") or "";k=x.get("product_id") or u or x.get("candidate")
            if not u or k in nseen:continue
            nseen.add(k);near_out.append(x)
            if len(near_out)>=int(cfg.get("image_coupang_near_candidate_page_checks",2)):break
        state["near_candidates"]=near_out
        if strict:
            m=strict[0]
            return {**state,"ok":True,"reason_code":"STRICT_MATCH","reason":"쿠팡 API 동일상품 확인",
                    "query":m.get("query") or "","candidate_name":m.get("candidate") or "","match":m.get("score") or 0,
                    "match_detail":m.get("match_detail") or {},"url":m.get("url") or "","image_url":m.get("image_url") or "",
                    "product_id":m.get("product_id") or "","source":"coupang_partners_api_core_resolver"}
        if state["rows_seen"]==0:
            state.update(reason_code="NO_API_RESULTS",reason="풀네임/핵심키워드 모두 쿠팡 API 검색결과 0건")
        elif near_out:
            state.update(reason_code="NEAR_CANDIDATES_ONLY",reason=f"쿠팡 유사후보 {len(near_out)}건 · 상세페이지 풀네임 재검증 필요")
        else:
            state.update(reason_code="CANDIDATES_MISMATCH",reason=f"쿠팡 API 후보 {state['rows_seen']}건은 있었지만 동일상품/옵션 검증 통과 0건")
        return state
    except Exception as e:
        state.update(reason_code="API_ERROR",reason="쿠팡 Partners API 보강 실패: "+str(e))
        return state


_TOSS_IMAGE_FALLBACK_CACHE={"rows":None,"loaded_at":0.0}
_TOSS_IMAGE_CATEGORY_CACHE={}

def _toss_api_exact_product(product,cfg,repair_mode=False):
    """Resolve an exact/near product from official Toss Sharelink read APIs.

    The API has ranking/category feeds rather than free-text search. To improve
    recall we scan global best-selling, then cached category feeds. Similar
    candidates are NOT accepted from title alone; they are returned as
    `near_candidates` for direct toss.shopping page full-name validation.
    """
    state={"ready":toss_sharelink_api.ready(),"attempted":False,"matched":0,"rows_scanned":0,"category_ids":[],
           "errors":[],"near_candidates":[],"reason_code":"NOT_ATTEMPTED"}
    if not cfg.get("image_toss_api_fallback_enabled",True) or not state["ready"]:
        state.update(reason_code="API_NOT_READY",reason="토스 Sharelink API 미설정/비활성")
        return {"ok":False,"state":state,"near_candidates":[]}
    state["attempted"]=True
    try:
        size=max(50,min(500,int(cfg.get("image_toss_api_feed_size",500))))
        global _TOSS_IMAGE_FALLBACK_CACHE
        ttl=float(cfg.get("image_toss_api_memory_cache_sec",300))
        refresh=repair_mode and (time.time()-float(_TOSS_IMAGE_FALLBACK_CACHE.get("loaded_at") or 0)>ttl)
        rows=_TOSS_IMAGE_FALLBACK_CACHE.get("rows")
        if rows is None or refresh:
            try:rows=toss_sharelink_api.best_selling(size,force=bool(refresh))
            except Exception as e:
                rows=[];state["errors"].append("global best-selling: "+str(e))
            _TOSS_IMAGE_FALLBACK_CACHE={"rows":rows,"loaded_at":time.time()}
        rows=list(rows or []);merged=list(rows);state["rows_scanned"]=len(rows)

        target_terms=[x.lower() for x in identity_terms(product["name"])[:5]]
        broad_map={
          "생활용품":("화장지","휴지","세제","청소","수납","욕실","생활","마스크","휴지통","빨래"),
          "주방용품":("주방","칼","도마","팬","냄비","그릇","컵","텀블러","수저","보관","키친"),
          "패션잡화":("여성","남성","가방","신발","양말","모자","패션","벨트","지갑","의류"),
          "식품":("식품","음료","과자","쌀","고기","과일","차","커피","라면","건강식"),
          "디지털/가전":("충전","케이블","가전","전자","이어폰","키보드","마우스","거치대","배터리","디지털"),
          "화장품/미용":("세럼","크림","클렌징","샴푸","트리트먼트","화장품","미용","스킨","로션","마스크팩","헤어")}
        broad=tuple(broad_map.get(product["category"] or "",()))
        cat_score={}
        # v7.55: use the authoritative /categories tree directly. Previously
        # price/image lookup only learned category IDs from global best-selling,
        # so products outside that global slice could never be found.
        try:
            from . import search_adapter as _search_adapter
            target_category=product["category"] or ""
            ranked=[]
            for node in toss_sharelink_api.get_categories(False):
                cid=str(node.get("category_id") or "")
                label=((node.get("path") or "")+" "+(node.get("name") or "")).strip()
                assigned=_search_adapter._toss_category_from_text(label,[target_category],cfg) if target_category else ""
                if not cid or assigned!=target_category:continue
                try:level=int(node.get("level") or max(1,str(node.get("path") or "").count("/")+1))
                except Exception:level=9
                score=_search_adapter._toss_category_score(label,target_category,cfg)
                ranked.append((level,-score,len(label),cid))
            for _,_,_,cid in sorted(ranked):cat_score[cid]=min(0,cat_score.get(cid,9))
        except Exception as e:
            state["errors"].append("category tree: "+str(e))
        for r in rows:
            low=norm(r.get("name") or "").lower()
            pri=2
            if target_terms and any(x in low for x in target_terms):pri=0
            elif broad and any(x in low for x in broad):pri=1
            for cid in r.get("category_ids") or []:
                cid=str(cid)
                if cid:cat_score[cid]=min(pri,cat_score.get(cid,9))
        # Also respect explicitly configured category IDs when available.
        try:
            for cid in toss_sharelink_api.credentials().get("category_ids") or []:
                cid=str(cid)
                if cid:cat_score[cid]=min(1,cat_score.get(cid,9))
        except Exception:pass
        cat_ids=[x[0] for x in sorted(cat_score.items(),key=lambda kv:(kv[1],kv[0]))]
        maxcats=max(0,int(cfg.get("image_toss_api_category_probe_count",24)))
        cat_ids=cat_ids[:maxcats];state["category_ids"]=cat_ids
        for cid in cat_ids:
            try:
                global _TOSS_IMAGE_CATEGORY_CACHE
                crow=_TOSS_IMAGE_CATEGORY_CACHE.get(cid)
                if crow is None:
                    crow=toss_sharelink_api.best_categories(cid,int(cfg.get("image_toss_api_category_feed_size",100)))
                    _TOSS_IMAGE_CATEGORY_CACHE[cid]=crow
                merged.extend(crow or [])
            except Exception as e:
                _TOSS_IMAGE_CATEGORY_CACHE[cid]=[]
                state["errors"].append(f"category {cid}: {e}")

        seen=set();accepted=[];near=[];rejected=[]
        threshold=max(0.58,float(cfg.get("image_toss_api_match_threshold",0.62)))
        for r in merged:
            key=r.get("product_id") or ((r.get("name") or "").lower()+"|"+str(r.get("price") or ""))
            if key in seen:continue
            seen.add(key);name=r.get("name") or ""
            ok,score,detail=marketplace_product_accept(name,product["name"],min(threshold,float(cfg.get("price_api_recall_match_threshold",0.48))))
            if ok:
                z=dict(r);z.update(match=score,match_detail=detail,match_mode="strict");accepted.append(z);continue
            nok,nscore,ndetail=_near_product_candidate_assessment(name,product["name"])
            if nok and r.get("url"):
                z=dict(r);z.update(match=nscore,match_detail=ndetail,match_mode="near_page_confirm");near.append(z)
            elif len(rejected)<12:
                rejected.append({"candidate":name[:120],"score":nscore,"reason":_reject_reason_from_detail(ndetail)})
        accepted.sort(key=lambda x:(-float(x.get("match") or 0), int(x.get("rank") or 999999) if str(x.get("rank") or "").isdigit() else 999999))
        near.sort(key=lambda x:(-float(x.get("match") or 0), int(x.get("rank") or 999999) if str(x.get("rank") or "").isdigit() else 999999))
        # De-dupe near direct product URLs.
        nseen=set();near_out=[]
        for x in near:
            k=x.get("product_id") or x.get("url") or x.get("name")
            if k in nseen:continue
            nseen.add(k);near_out.append(x)
            if len(near_out)>=int(cfg.get("image_toss_near_candidate_page_checks",3)):break
        state["matched"]=len(accepted);state["rows_scanned"]=len(seen);state["near_candidates"]=near_out;state["rejected_sample"]=rejected
        if accepted:
            best=accepted[0];state.update(reason_code="STRICT_MATCH",reason="토스 API 동일상품 확인")
            return {"ok":True,"state":state,"near_candidates":near_out,"candidate_name":best.get("name") or "","url":best.get("url") or "",
                    "image_url":best.get("image_url") or "","match":best.get("match") or 0,"match_detail":best.get("match_detail") or {},
                    "product_id":best.get("product_id") or "","price":best.get("price"),
                    "original_price":best.get("original_price"),"source":"toss_sharelink_open_api"}
        if not rows and not merged:
            state.update(reason_code="NO_API_RESULTS",reason="토스 best-selling/category API 결과 0건")
        elif near_out:
            state.update(reason_code="NEAR_CANDIDATES_ONLY",reason=f"토스 유사후보 {len(near_out)}건 · toss.shopping 상세페이지 재검증 필요")
        else:
            state.update(reason_code="CANDIDATES_MISMATCH",reason=f"토스 API 후보 {len(seen)}건은 있었지만 동일상품/옵션 검증 통과 0건")
        return {"ok":False,"state":state,"near_candidates":near_out}
    except Exception as e:
        state["errors"].append(str(e));state.update(reason_code="API_ERROR",reason="토스 Sharelink API 보강 실패: "+str(e))
        return {"ok":False,"state":state,"near_candidates":[]}


def _detail_images_via_normal_chrome(product,url,site="",capture_rendered=None,trust_direct=None):
    global _COUPANG_DETAIL_BLOCKED_UNTIL,_COUPANG_DETAIL_LAST_FINISH
    if not url:return {"ok":False,"images":[],"reason":"URL 없음"}
    if coupang_partners_api._valid_affiliate_url(url):
        return {"ok":False,"images":[],"reason":"제휴 추적 링크는 열지 않습니다. API 상품 ID로 원상품 주소를 확인하세요."}
    site=site or _site_from_url(url)
    if not site:return {"ok":False,"images":[],"reason":"사이트 식별 실패"}
    cfg=settings()
    if site=="쿠팡":
        # v7.45: only already-known direct product URLs are allowed. Search and
        # category pages remain forbidden, while a blocked response activates a
        # shared cooldown so the batch never hammers Coupang.
        if not bool(cfg.get("coupang_web_image_access_enabled",False)):
            return {"ok":False,"images":[],"reason":"쿠팡 상세 크롭 비활성 설정","web_skipped":True,"blocked":False}
        if not _is_direct_coupang_product_url(url):
            return {"ok":False,"images":[],"reason":"쿠팡 검색/카테고리 URL은 상세사진 보강에 사용하지 않음"}
        if time.monotonic()<_COUPANG_DETAIL_BLOCKED_UNTIL:
            return {"ok":False,"images":[],"reason":"쿠팡 상세페이지 접근 제한 쿨다운 중","blocked":True}
        _pace_coupang_detail(cfg)
    if capture_rendered is None:
        capture_rendered=bool(cfg.get("image_coupang_rendered_screen_crop_enabled",True) if site=="쿠팡" else cfg.get("image_other_market_rendered_screen_crop_enabled",True))
    task={
      "id":"detail-"+str(product["id"])+"-"+str(abs(hash(url))%100000)+( "-crop" if capture_rendered else "-dom"),
      "site":site,"query":"","target_name":product["name"],"mode":"external_detail" if site=="구글원본" else "detail","url":url,
      "limit":int(cfg.get("detail_image_scan_limit",24)),
      "detail_scroll_rounds":0 if not capture_rendered else int(cfg.get("image_google_external_scroll_rounds",4) if site=="구글원본" else cfg.get("detail_scroll_rounds",6)),
      "detail_scroll_wait_ms":int(cfg.get("image_google_external_scroll_wait_ms",520) if site=="구글원본" else cfg.get("detail_scroll_wait_ms",700)),
      "render_wait_ms":int(float(cfg.get("image_google_external_render_wait_sec",3.0) if site=="구글원본" else (cfg.get("detail_fast_initial_wait_sec",2.4) if not capture_rendered else cfg.get("detail_initial_render_wait_sec",5.0)))*1000),
      "fast_capture_only":not bool(capture_rendered),
      "capture_rendered_crops":bool(capture_rendered),
      "capture_network_images":bool(capture_rendered and cfg.get("image_coupang_network_response_fallback",True)) if site=="쿠팡" else False,
      "capture_long_detail_segments":bool(cfg.get("image_coupang_long_detail_segment_crop",True)) if site=="쿠팡" else True,
      "screen_crop_target_count":3,
      "allow_gallery_fallback":True,
      "screen_crop_gallery_wait_ms":int(cfg.get("image_coupang_screen_crop_gallery_wait_ms",1200)),
      "screen_crop_detail_wait_ms":int(cfg.get("image_coupang_screen_crop_detail_wait_ms",750) if site=="쿠팡" else cfg.get("image_other_market_screen_crop_wait_ms",850)),
      "screen_crop_max_candidates":int(cfg.get("image_coupang_screen_crop_max_candidates",4) if site=="쿠팡" else (cfg.get("image_google_external_capture_max_candidates",10) if site=="구글원본" else cfg.get("image_other_market_screen_crop_max_candidates",6))),
      "network_idle_max_wait_ms":int(cfg.get("image_network_idle_max_wait_ms",5500)),
      "network_idle_quiet_ms":int(cfg.get("image_network_idle_quiet_ms",700)),
      "task_timeout_sec":int(cfg.get("image_detail_task_timeout_sec",210 if capture_rendered else 90)),
      "delay_ms":int(float(cfg.get("detail_task_delay_sec",4.0 if not capture_rendered else 6.0))*1000)
    }
    attempts=(1 if not capture_rendered else max(1,min(2,int(cfg.get("coupang_detail_max_attempts",2))))) if site=="쿠팡" else 1
    last={"ok":False,"images":[],"reason":"상세 이미지 수집 실패"}
    try:
        for attempt in range(1,attempts+1):
            collect_timeout=max(75,int(cfg.get("image_detail_collect_timeout_sec",240 if capture_rendered else 90)))
            res=chrome_collector.collect([task],progress=None,timeout_sec=collect_timeout)
            if not res:last={"ok":False,"images":[],"reason":"상세페이지 응답 없음","attempt":attempt}
            else:
                r=res[0]
                if r.get("status")=="blocked":
                    if site=="쿠팡" and cfg.get("image_coupang_detail_stop_on_block",True):
                        _COUPANG_DETAIL_BLOCKED_UNTIL=time.monotonic()+float(cfg.get("image_coupang_detail_block_cooldown_sec",3600))
                    reason=("쿠팡 상세페이지 접근 제한 감지 — 이후 상세사진 접속 자동 중단" if site=="쿠팡" else f"{site} 원본 상품페이지 접근 제한")
                    return {"ok":False,"images":[],"reason":reason,"blocked":True,"attempt":attempt}
                if r.get("status")!="ok":last={"ok":False,"images":[],"reason":r.get("error") or r.get("status"),"attempt":attempt,"auto_dismissed_dialogs":r.get("auto_dismissed_dialogs") or []}
                else:
                    identity_text=str(r.get("identity_text") or "").strip()
                    identity_basis=str(r.get("page_title") or "").strip()
                    ok,score,detail=_strict_google_source_page_accept(identity_basis,product["name"],cfg,r.get("identity_sources") or [])
                    redirect_conflict=page_identity_conflict(url,str(r.get("url") or url))
                    detail={**detail,"identity_text":identity_text[:1200],"identity_sources":r.get("identity_sources") or [],
                            "redirect_conflict":redirect_conflict,"identity_verification":IDENTITY_POLICY}
                    if redirect_conflict:ok=False
                    r["detail_images"]=[im for im in (r.get("detail_images") or [])
                                        if isinstance(im,dict) and not _critical_conflicts(str(im.get("alt") or ""),product["name"])]
                    screen_captures=r.get("screen_captures") or []
                    last={"ok":ok,"images":r.get("detail_images") or [],"screen_captures":screen_captures,
                          "screen_capture_diag":r.get("screen_capture_diag") or {},"page_url":r.get("url") or url,
                          "page_title":r.get("page_title") or "","identity_text":r.get("identity_text") or "","identity_sources":r.get("identity_sources") or [],"page_score":score,"match_detail":detail,
                          "auto_dismissed_dialogs":r.get("auto_dismissed_dialogs") or [],"attempt":attempt,
                          "reason":"" if ok and ((r.get("detail_images") or []) or screen_captures) else ("상세페이지 이미지 0장" if ok else "상세페이지 상품/옵션 일치 검증 실패")}
                    if not ok:return last
                    if last["images"] or last.get("screen_captures"):return last
            if attempt<attempts:
                delay=max(10.0,float(cfg.get("coupang_detail_retry_delay_sec",20.0)))
                log(f"쿠팡 상세 이미지 {attempt}차 실패 · {delay:.0f}초 후 1회 재시도")
                time.sleep(delay)
        return last
    except Exception as e:
        log("일반 Chrome 상세이미지 보강 실패: "+str(e))
        return {"ok":False,"images":[],"reason":str(e)}
    finally:
        if site=="쿠팡":_COUPANG_DETAIL_LAST_FINISH=time.monotonic()

def _dhash(path):
    im=Image.open(path).convert("L").resize((9,8),Image.Resampling.LANCZOS)
    pix=list(im.getdata());bits=[]
    for y in range(8):
        row=pix[y*9:(y+1)*9]
        bits.extend(1 if row[x]>row[x+1] else 0 for x in range(8))
    v=0
    for b in bits:v=(v<<1)|b
    return v

def _ham(a,b):return (a^b).bit_count()


def _safe_title_image_stem(title, limit=150):
    s=re.sub(r'[\\/:*?"<>|]+',' ',str(title or '').strip())
    s=re.sub(r'\s+',' ',s).strip().rstrip('.')
    if not s:s='product_image'
    return s[:max(20,int(limit))].rstrip(' ._') or 'product_image'


def _image_dest_path(post_dir,title,index):
    """Use the generated review title as filename without tripping Windows MAX_PATH."""
    post_dir=Path(post_dir)
    suffix=f"_{int(index)}.jpg"
    # 235 chars leaves room for Windows/Explorer and temporary suffixes.
    budget=max(24,235-len(str(post_dir.resolve()))-len(suffix)-1)
    stem=_safe_title_image_stem(title,budget)
    return post_dir/f"{stem}{suffix}"


def _load_image_evidence_flag(ep, key, default=None):
    try:
        if ep and Path(ep).exists():
            obj=json.loads(Path(ep).read_text(encoding='utf-8'))
            return obj.get(key, default)
    except Exception:
        pass
    return default


def _evidence_exact_found(ep):
    v=_load_image_evidence_flag(ep,'exact_product_found',None)
    if v is None:
        v=_load_image_evidence_flag(ep,'exact_coupang_found',False)
    return bool(v)


def _google_exact_product_source_pages(product,cfg,progress=None):
    """Discover exact-product ORIGINAL pages through Google Images + Web.

    v8.08.42 fixes the old resolver which only parsed classic Web <h3> results.
    Google Images is now the primary discovery surface. We keep both the source
    page URL and, when Google exposes it, the ORIGINAL image URL (never the
    Google preview thumbnail). The destination page is still revalidated before
    any image bytes are accepted.
    """
    state={"attempted":False,"queries":[],"tasks":[],"candidates":[],"accepted":[],"rejected":[],"errors":[],"surfaces":{}}
    if not bool(cfg.get("image_google_source_fallback_enabled",True)):
        return state
    state["attempted"]=True
    raw=clean_listing_title_noise(product["name"] or "")
    terms=identity_terms(raw);critical=critical_identity_tokens(raw)
    core=" ".join(terms[:6]).strip()
    queries=[]
    if raw:queries.append(f'"{raw}"')
    if core and core.lower()!=raw.lower():queries.append((core+" "+" ".join(critical[:2])).strip())
    if terms:
        compact=" ".join(terms[:4]+critical[:2]).strip()
        if compact:queries.append(compact)
    queries=list(dict.fromkeys(x.strip() for x in queries if x.strip()))[:max(1,int(cfg.get("image_google_query_count",3)))]
    surfaces=[]
    if cfg.get("image_google_image_search_enabled",True):surfaces.append("images")
    if cfg.get("image_google_web_search_enabled",True):surfaces.append("web")
    if not surfaces:surfaces=["web"]
    tasks=[]
    # Exact Google Images search gets first priority. Web search is added only
    # for the strongest exact query so the fallback remains reasonably fast.
    for i,q in enumerate(queries,1):
        if "images" in surfaces:
            tasks.append({"id":f"google-images-{product['id']}-{i}","site":"Google","mode":"google_product_source_search","search_surface":"images","query":q,
                          "target_name":product["name"],"limit":int(cfg.get("image_google_source_result_limit",18)),"render_wait_ms":2200,"delay_ms":850,"task_timeout_sec":55})
        if "web" in surfaces and i<=max(0,int(cfg.get("image_google_web_query_count",1))):
            tasks.append({"id":f"google-web-{product['id']}-{i}","site":"Google","mode":"google_product_source_search","search_surface":"web","query":q+" 상품",
                          "target_name":product["name"],"limit":int(cfg.get("image_google_source_result_limit",18)),"render_wait_ms":1800,"delay_ms":850,"task_timeout_sec":45})
    state["queries"]=queries;state["tasks"]=[{"surface":x.get("search_surface"),"query":x.get("query")} for x in tasks]
    if not tasks:return state
    try:
        rows=chrome_collector.collect(tasks,progress=progress,timeout_sec=max(90,62*len(tasks)))
    except Exception as e:
        state["errors"].append(str(e));return state
    seen=set()
    bad_domains=tuple(str(x).lower() for x in cfg.get("image_google_excluded_domains",[
        "youtube.com","youtu.be","pinterest.","instagram.com","facebook.com","tiktok.com","x.com","twitter.com",
        "blog.naver.com","cafe.naver.com","brunch.co.kr","reddit.com"
    ]))
    for result in rows or []:
        surf=str(result.get("surface") or result.get("search_surface") or "web")
        state["surfaces"].setdefault(surf,{"results":0,"accepted":0,"errors":[]})
        if result.get("status")!="ok":
            err=result.get("error") or result.get("status") or "google search failed"
            state["errors"].append(err);state["surfaces"][surf]["errors"].append(err);continue
        for rec in result.get("sources") or []:
            url=str(rec.get("url") or "").strip();host=str(rec.get("host") or "").lower()
            if not url or any(x in host for x in bad_domains):continue
            dedup=(url,str(rec.get("image_url") or ""))
            if dedup in seen:continue
            seen.add(dedup);state["surfaces"][surf]["results"]+=1
            candidate=" ".join(str(x or "") for x in (rec.get("title"),rec.get("context"),rec.get("image_alt"),rec.get("host"))).strip()
            ok,score,detail=_balanced_exact_product_accept(candidate,product["name"])
            entry={**rec,"surface":surf,"score":score,"match_detail":detail}
            state["candidates"].append(entry)
            threshold=float(cfg.get("image_google_preliminary_match_threshold",0.40))
            # Image results often have sparse text. Critical conflicts are still a
            # hard rejection, but a core-hit near candidate may be opened and
            # decided by the full destination page.
            conflicts=_critical_conflicts(candidate,product["name"])
            preliminary=ok or (not conflicts and score>=threshold and bool(detail.get("core_hit",True)))
            if preliminary:
                state["accepted"].append(entry);state["surfaces"][surf]["accepted"]+=1
            else:
                state["rejected"].append({**entry,"reason":"Google 결과 제목/요약 상품 일치도 부족","critical_conflicts":conflicts})
    state["accepted"].sort(key=lambda x:(0 if x.get("surface")=="images" else 1,-float(x.get("score") or 0),int(x.get("rank") or 99)))
    # Keep unique source pages, but preserve a direct original image URL from the
    # best Google Images hit for that page.
    uniq=[];page_seen=set()
    for x in state["accepted"]:
        u=str(x.get("url") or "")
        if not u or u in page_seen:continue
        page_seen.add(u);uniq.append(x)
        if len(uniq)>=int(cfg.get("image_google_source_page_checks",8)):break
    state["accepted"]=uniq
    return state

def _image_failure_summary(verified_count,want,resolver_state,toss_fallback,detail_sources,rejected,api_state=None,google_state=None,naver_state=None):
    """Explain *why* an image stage failed instead of a generic 0/3 label."""
    resolver_state=resolver_state or {};tstate=(toss_fallback or {}).get('state') or {}
    cds=[x for x in (detail_sources or []) if x.get('platform')=='쿠팡']
    tds=[x for x in (detail_sources or []) if x.get('platform')=='토스쇼핑']
    def detail_state(rows):
        if not rows:return 'NOT_OPENED'
        if any(x.get('blocked') for x in rows):return 'ACCESS_BLOCKED'
        if any(x.get('ok') and ((x.get('images') or []) or (x.get('screen_captures') or [])) for x in rows):return 'IMAGES_FOUND'
        if any(x.get('ok') for x in rows):return 'PAGE_OK_NO_USABLE_IMAGE'
        if any('검증 실패' in str(x.get('reason') or '') for x in rows):return 'PAGE_IDENTITY_MISMATCH'
        return 'PAGE_COLLECT_FAILED'
    ccode=str(resolver_state.get('reason_code') or ('STRICT_MATCH' if resolver_state.get('ok') else 'NOT_ATTEMPTED'))
    tcode=str(tstate.get('reason_code') or ('STRICT_MATCH' if (toss_fallback or {}).get('ok') else 'NOT_ATTEMPTED'))
    cdetail=detail_state(cds);tdetail=detail_state(tds)
    gstate=google_state or {};gpages=list(gstate.get('pages') or [])+list(gstate.get('rendered_pages') or [])
    gaccepted=len(gstate.get('accepted') or []);gvalidated=sum(1 for x in gpages if x.get('ok'))
    nstate=naver_state or {};nmatched=int(nstate.get('matched') or 0);nused=int(nstate.get('used') or 0);nraw=int(nstate.get('raw_seen') or 0);nerr=list(nstate.get('errors') or [])
    reasons=[str(x.get('reason') or '') for x in (rejected or [])]
    counts={
      'download_failed':sum(1 for r in reasons if '다운로드' in r or '판독 실패' in r),
      'duplicate':sum(1 for r in reasons if '중복' in r),
      'product_not_visible':sum(1 for r in reasons if '제품이 보이지' in r or '제품이 보이는 상세영역' in r),
      'identity_reject':sum(1 for r in reasons if '동일상품' in r or '검증 실패' in r or '불일치' in r),
    }
    if int(verified_count)>=int(want):code='OK';short='3장 검증완료'
    elif nerr and nraw==0:code='NAVER_IMAGE_API_ERROR';short='NAVER 이미지 API 호출 실패 · '+str(nerr[-1])[:90]
    elif nraw>0 and nmatched==0 and gstate.get('attempted'):
        code='NAVER_NO_EXACT_THEN_GOOGLE';short=f'NAVER 원본 {nraw}건 검색→동일제품 0건 · Google 보강 후 {verified_count}/{want}'
    elif nmatched>0 and nused==0:
        code='NAVER_EXACT_DOWNLOAD_REJECT';short=f'NAVER 동일제품 후보 {nmatched}건 · 다운로드/제품노출 검증 0건 통과 · 현재 {verified_count}/{want}'
    elif nmatched>0 and nused<int(want):
        code='NAVER_PARTIAL';short=f'NAVER 동일제품 {nmatched}건 중 {nused}장 사용 · 추가 보강 후 {verified_count}/{want}'
    elif ccode=='NO_API_RESULTS' and tcode in {'NO_API_RESULTS','CANDIDATES_MISMATCH','NOT_ATTEMPTED'}:code='NO_PRODUCT_RESULTS';short='쿠팡 API 검색 0건 · NAVER/Google 동일제품 보강 부족'
    elif ccode=='CANDIDATES_MISMATCH' and tcode=='CANDIDATES_MISMATCH':code='LOOKALIKE_ONLY';short='후보는 있으나 동일제품/옵션 검증 미통과'
    elif ccode=='NEAR_CANDIDATES_ONLY' or tcode=='NEAR_CANDIDATES_ONLY':code='NEAR_NOT_CONFIRMED';short='유사후보 발견 · 상세페이지 풀네임 검증 미통과'
    elif cdetail=='ACCESS_BLOCKED':code='COUPANG_ACCESS_BLOCKED';short=f'쿠팡 상세 접근제한 · NAVER {nused}장 사용 · 현재 {verified_count}/{want}'
    elif gstate.get('attempted') and gaccepted==0:code='GOOGLE_NO_EXACT_SOURCE';short=f'NAVER {nused}장 사용 · Google 동일상품 원본페이지 0건 · 현재 {verified_count}/{want}'
    elif gstate.get('attempted') and gaccepted>0 and gvalidated==0:code='GOOGLE_SOURCE_IDENTITY_REJECT';short=f'NAVER {nused}장 사용 · Google 후보 {gaccepted}건 원본검증 0건 · 현재 {verified_count}/{want}'
    elif counts['download_failed']>0:code='IMAGE_DOWNLOAD_FAILED';short=f'동일상품 확인됨 · 이미지 다운로드 실패 {counts["download_failed"]}건 · {verified_count}/{want}'
    elif counts['product_not_visible']>0:code='PRODUCT_VISIBLE_REJECT';short=f'제품 미노출/문서형 컷 제외 · {verified_count}/{want}'
    elif counts['duplicate']>0:code='DISTINCT_IMAGE_SHORT';short=f'중복 제외 후 서로 다른 이미지 {verified_count}/{want}'
    else:code='INSUFFICIENT_USABLE_IMAGES';short=f'동일상품 이미지가 실제 파일 기준 {verified_count}/{want}'
    return {'code':code,'short':short,'verified_count':int(verified_count),'required':int(want),
            'coupang_lookup':ccode,'coupang_detail':cdetail,'coupang_rows_seen':int(resolver_state.get('rows_seen') or 0),
            'coupang_near_candidates':len(resolver_state.get('near_candidates') or []),'toss_lookup':tcode,'toss_detail':tdetail,
            'toss_rows_scanned':int(tstate.get('rows_scanned') or 0),'toss_near_candidates':len(tstate.get('near_candidates') or []),
            'naver_ready':bool(nstate.get('ready')),'naver_raw_seen':nraw,'naver_matched':nmatched,'naver_used':nused,'naver_errors':nerr[-3:],
            'google_attempted':bool(gstate.get('attempted')),'google_candidates':len(gstate.get('candidates') or []),'google_accepted':gaccepted,'google_validated_pages':gvalidated,
            'reject_counts':counts,'coupang_api_primary_matches':int((api_state or {}).get('matched') or 0)}


def _read_image_failure_summary(ep):
    try:
        if ep and Path(ep).exists():return json.loads(Path(ep).read_text(encoding='utf-8')).get('failure_summary') or {}
    except Exception:pass
    return {}

def _strict_image_source_accept(text, target_name):
    """Stricter than generic matching: for photos we prefer missing over wrong."""
    ok,score,detail=strict_product_accept(text, target_name, max(float(settings().get('image_match_threshold',0.58)),0.70))
    terms=identity_terms(target_name)
    low=norm(text).lower()
    mandatory=[]
    for t in terms[:3]:
        tl=t.lower()
        if len(tl)<2 or tl in {'제품','상품','세트','구성','정품','공식','추천'}:
            continue
        mandatory.append(tl)
        if len(mandatory)>=2:
            break
    mandatory_hit=all(t in low for t in mandatory) if mandatory else True
    detail={**detail,'image_mandatory_terms':mandatory,'image_mandatory_hit':mandatory_hit}
    return ok and mandatory_hit, score, detail

def _strict_google_source_page_accept(identity_text,target_name,cfg=None,identity_sources=None):
    """Strict identity gate for a Google Images destination product page.

    A recommendation card anywhere in the body must never validate the page.
    At least one *individual* primary identity field (title/H1/OG/Product JSON-LD)
    must pass the full model/capacity/count + semantic gate.
    """
    cfg=cfg or settings()
    threshold=max(float(cfg.get("image_google_source_page_match_threshold",0.72)),
                  float(cfg.get("image_match_threshold",0.58)))
    fields=[]
    for rec in identity_sources or []:
        if not isinstance(rec,dict):continue
        text=norm(rec.get("text") or "")
        source=str(rec.get("source") or "")
        if text and source in {"document_title","meta_title","main_heading","jsonld_product"}:
            fields.append((source,text))
    if not fields and norm(identity_text):
        fields=[("legacy_identity",norm(identity_text))]
    if not fields:
        return False,0.0,{"reason":"source_identity_missing","critical":critical_identity_tokens(target_name),"missing_identity":True}
    best=(False,0.0,{})
    checked=[]
    terms=identity_terms(target_name)
    semantic_terms=[t for t in terms[:6] if len(t)>=2 and t not in {"제품","상품","세트","구성","정품","공식","추천"}]
    min_hits=2 if len(semantic_terms)>=3 else (1 if semantic_terms else 0)
    for source,text in fields:
        ok,score,detail=strict_product_accept(text,target_name,threshold)
        low=text.lower();hits=[t for t in semantic_terms if t.lower() in low];conflicts=_critical_conflicts(text,target_name)
        variants=variant_conflicts(text,target_name)
        field_ok=bool(ok and not conflicts and not variants and len(hits)>=min_hits)
        row={"source":source,"text":text[:700],"ok":field_ok,"score":score,"hits":hits,"conflicts":conflicts,"variant_conflicts":variants,"detail":detail}
        checked.append(row)
        if score>best[1]:best=(field_ok,score,row)
        if field_ok:
            return True,score,{**detail,"google_identity_source":source,"google_identity_hits":hits,"google_identity_min_hits":min_hits,"hard_conflicts":conflicts,"google_source_page_strict":True,"checked_identity_fields":checked}
    return False,best[1],{"google_source_page_strict":True,"google_identity_min_hits":min_hits,"checked_identity_fields":checked,"reason":"no_primary_identity_field_matched"}


def _balanced_exact_product_accept(text,target_name,threshold=None):
    """Marketplace-title exact gate used before opening a direct product page.

    v7.50 accidentally applied the extra image-title `first two terms BOTH` gate
    to already-validated API matches. Marketplace titles often omit/reorder one
    brand/core token, so exact products were lost. Keep the hard variant/model/
    signature checks from strict_product_accept, but do not require both leading
    terms to be printed in the marketplace title.
    """
    th=float(threshold if threshold is not None else max(0.60,float(settings().get('image_match_threshold',0.70))-0.08))
    accepted,score,detail=strict_product_accept(text,target_name,th)
    conflicts=variant_conflicts(text,target_name)
    return bool(accepted and not conflicts),score,{**detail,"variant_conflicts":conflicts}


def _critical_conflicts(candidate,target_name):
    """Detect explicit option/model contradictions for a provisional near match."""
    target_low=norm(target_name).lower().replace(' ','');cand_low=norm(candidate).lower().replace(' ','')
    tt=critical_identity_tokens(target_name);ct=critical_identity_tokens(candidate)
    conflicts=[]
    unit_re=re.compile(r'^(\d+(?:\.\d+)?)(ml|kg|mg|cm|mm|oz|m|l|g|개입|개|매|팩|세트|인치|롤|병|캔|포|봉|장|겹)$',re.I)
    def fam(u):
        if u in {'개입','개','롤'} and any(k in target_low for k in ('화장지','휴지','롤화장지','키친타월','키친타올')):return 'tissue_count'
        if u in {'개입','개','매'} and any(k in target_low for k in ('마스크팩','시트마스크')):return 'sheet_count'
        if u in {'개입','개','팩','세트','병','캔','포','봉','장','매','롤'}:return 'count_'+u
        return u
    cparsed=[]
    for x in ct:
        m=unit_re.match(x.lower())
        if m:cparsed.append((m.group(1),fam(m.group(2).lower()),x))
    for x in tt:
        xl=x.lower();m=unit_re.match(xl)
        if m:
            n,f=m.group(1),fam(m.group(2).lower())
            same=[z for z in cparsed if z[1]==f]
            if same and not any(z[0]==n for z in same):conflicts.append({'target':x,'candidate':[z[2] for z in same],'type':'option_value_conflict'})
        elif re.search(r'[a-z]',xl,re.I) and re.search(r'\d',xl):
            # Strong model id. If candidate advertises another model-like id while
            # omitting the target model, treat it as a hard contradiction.
            if xl not in cand_low:
                models=[z for z in ct if re.search(r'[a-z]',z,re.I) and re.search(r'\d',z)]
                if models:conflicts.append({'target':x,'candidate':models,'type':'model_conflict'})
    return conflicts


def _near_product_candidate_assessment(candidate,target_name):
    """Conservative provisional matcher; never finalizes without page validation.

    Missing capacity/count text may be omitted from a search-card title, so the
    provisional score uses semantic identity coverage rather than the strict
    gate's zero score. Explicit contradictory values (2겹 vs 3겹, 1L vs 500ml,
    different model id, etc.) still hard-reject the candidate.
    """
    _strict_score,detail=strict_product_match(candidate,target_name)
    terms=identity_terms(target_name);low=norm(candidate).lower()
    semantic=float(product_match(candidate,terms))
    hits=[x for x in terms[:7] if x.lower() in low]
    conflicts=_critical_conflicts(candidate,target_name)
    core=terms[:3];core_hits=[x for x in core if x.lower() in low]
    need=max(2,min(3,(len(terms[:6])+1)//2)) if len(terms)>=2 else 1
    ok=(not conflicts) and len(hits)>=need and bool(core_hits) and semantic>=0.38
    return ok,semantic,{**detail,'semantic_soft':semantic,'identity_hits':hits,'identity_hit_count':len(hits),'required_hits':need,'core_hits':core_hits,'hard_conflicts':conflicts,'provisional_only':True}


def _reject_reason_from_detail(detail):
    if detail.get('hard_conflicts'):return '명시 옵션/모델 불일치'
    if detail.get('missing'):return '필수 옵션/용량/수량 누락'
    if detail.get('signature_missing'):return '제품 라인명 불일치'
    if not detail.get('core_hit',True):return '브랜드/핵심명 불일치'
    if float(detail.get('soft') or 0)<float(detail.get('threshold') or 0):return '상품명 유사도 부족'
    return '풀네임 동일상품 검증 실패'


def _price_evidence_records(product):
    out=[]
    try: ep=product["price_evidence_json"]
    except Exception: ep=None
    if ep and Path(ep).exists():
        try:
            obj=json.loads(Path(ep).read_text(encoding="utf-8"))
            for r in obj.get("records") or []:
                if isinstance(r,dict) and (r.get("verified") or r.get("price")):
                    out.append(dict(r))
        except Exception:pass
    return out

def _price_evidence_image_paths(product):
    out=[]
    for r in _price_evidence_records(product):
        p=r.get("image_path")
        if p and Path(p).exists() and p not in out:out.append(p)
    return out

def capture_images_cached(product,post_dir,con,repair_mode=False,progress=None):
    """Acquire three BLOG-USABLE Coupang images that visibly show the product.

    v7.50 policy:
      1) never open Coupang /np/search from the image stage
      2) resolve Coupang by Partners API (full name -> core keyword -> original full-name validation)
      3) use Coupang representative/gallery first, then product-visible detail crops
      4) if Coupang is not found, direct detail is blocked, or fewer than 3 usable images remain,
         resolve the same item through official Toss Sharelink API feeds and use Toss thumbnail/direct product page
      5) reject text/spec/legal/barcode-heavy crops that do not visibly show a product
      6) keep failures as repairable photo backlog instead of hiding them from TOP100
    """
    cfg=settings();want=int(cfg.get("image_exact_count",3));post_dir=Path(post_dir)
    if is_wala_product(product):
        if progress:progress(REVIEW_REASON)
        return preserve_product_images(product,post_dir,want)
    coupang_only=bool(cfg.get("image_coupang_only_1plus2_mode",True))
    page_grounded_only=bool(cfg.get("image_page_grounded_only_mode",True))
    # v8.08.43: blog photos may originate ONLY from an exact Coupang product
    # page/API image or from an exact Google Images result whose ORIGINAL source
    # product page is re-opened and identity-validated. Naver Image/Toss/other
    # marketplace thumbnail fallbacks are intentionally blocked in this mode.
    strict_cg_only=bool(cfg.get("image_strict_coupang_google_only_mode",True))
    strict_page_policy="PRIMARY_PAGE_OR_EXACT_API_V1"
    post_dir.mkdir(parents=True,exist_ok=True)
    try: photo_title=product["title"] or product["name"]
    except Exception: photo_title=product["name"]
    sources=[];rejected=[];detail_sources=[];local_records=[];api_detail_urls=[]
    google_source_fallback={"attempted":False,"queries":[],"candidates":[],"accepted":[],"rejected":[],"errors":[],"pages":[]}
    preserved_existing=[];trusted_existing_reuse=False

    def stage(message):
        if progress:
            try:progress(str(message))
            except Exception:pass

    def add_local_record(path,kind="verified_existing",platform="",page_url="",image_role="",require_product_visible=False):
        value=str(path or "").strip()
        if not value or not Path(value).exists():return
        if any(str(x.get("path") or "")==value for x in local_records):return
        local_records.append({"path":value,"kind":kind,"platform":platform,"page_url":page_url,
                              "image_role":image_role,"require_product_visible":bool(require_product_visible)})

    # Reuse every verified partial/full image when its evidence target and
    # exact-product gate match. A 1/3 or 2/3 retry therefore keeps good files.
    old_ev=post_dir/"image_evidence.json"
    prior_exact_product=False
    if old_ev.exists():
        try:
            old=json.loads(old_ev.read_text(encoding="utf-8"))
            prior_exact_product=bool(old.get("exact_product_found", old.get("exact_coupang_found")))
            policy=str(old.get("source_policy") or "")
            # v7.49 intentionally does NOT trust older detail-image evidence.
            # Older versions could save legal/specification sheets as blog photos.
            cached_paths=[str(im.get("path") or "") for im in old.get("images") or [] if isinstance(im,dict)]
            reusable_policy=(policy==strict_page_policy and not image_evidence_error(old_ev,product["name"],cached_paths))
            if not reusable_policy:prior_exact_product=False
            if reusable_policy and old.get("target")==product["name"] and prior_exact_product:
                trusted_existing_reuse=True
                prior=[]
                for index,im in enumerate(old.get("images") or []):
                    pth=im.get("path") if isinstance(im,dict) else None
                    if pth and Path(pth).exists():
                        prior.append(str(Path(pth)))
                        role=str(im.get("image_role") or ("representative" if index==0 else "legacy_detail_or_gallery_revalidated"))
                        add_local_record(pth,str(im.get("kind") or "verified_evidence"),str(im.get("platform") or ""),
                                         str(im.get("page_url") or ""),role,index>0)
                composition=old.get("composition") or {}
                if len(prior)>=want and bool(composition.get("verified")):
                    return prior[:want],str(old_ev)
        except Exception:pass
    if trusted_existing_reuse:
        preserved_existing=[str(record["path"]) for record in local_records]
    # Existing verified Coupang price evidence can provide a local crop and an
    # already-known direct product URL, without any new search request.
    price_records=[];fallback_price_records=[]
    for pr in _price_evidence_records(product):
        if not pr.get("verified"):
            continue
        identity_ok,_,_= _balanced_exact_product_accept(pr.get("product_name") or "",product["name"])
        if not identity_ok:
            rejected.append({"kind":"price_evidence","reason":"가격 근거의 원본 상품명 일치 미확인"})
            continue
        if coupang_only and pr.get("site")!="쿠팡":
            if pr.get("site") in {"토스쇼핑","네이버쇼핑"}:fallback_price_records.append(pr)
            continue
        page_url=pr.get("url") or ""
        price_records.append(pr)
        iu=pr.get("image_url") or ""
        if iu and all(x.get("url")!=iu for x in sources):
            sources.append({"url":iu,"platform":pr.get("site") or "","page_url":page_url,"kind":"price_evidence","candidate_name":pr.get("product_name") or "","match_score":pr.get("match") or 1.0})

    # Browser-free Coupang API is the primary network image source.
    stage("쿠팡 API 대표이미지/동일상품 확인")
    api_state={"ready":coupang_partners_api.ready(),"queries":0,"matched":0,"errors":[]}
    if cfg.get("coupang_api_enabled",True) and coupang_partners_api.ready():
        try:
            maxq=int(cfg.get("coupang_api_image_query_count",3))
            matches,errs=coupang_partners_api.exact_matches(product["name"],max_queries=maxq,threshold=float(cfg.get("image_match_threshold",0.58)))
            api_state["queries"]=maxq;api_state["matched"]=len(matches);api_state["errors"]=errs[-5:]
            # API first: prepend these URLs ahead of snapshot/price URLs while preserving uniqueness.
            api_sources=[]
            for m in matches:
                name_text=(m.get("name") or "")
                # exact_matches() already passed the hard variant/model/signature
                # gate. Revalidate with the balanced marketplace-title threshold;
                # v7.50's extra "first two terms BOTH" gate caused valid Coupang
                # API results to disappear.
                iok,_,idetail=_balanced_exact_product_accept(name_text,product["name"])
                if not iok:
                    rejected.append({"platform":"쿠팡","kind":"coupang_partners_api_search","candidate_name":m.get("name") or "","reason":"쿠팡 API 동일상품 검증 실패","match_detail":idetail})
                    continue
                iu=m.get("image_url") or "";pu=_coupang_api_product_url(str(m.get("url") or ""),str(m.get("product_id") or ""))
                if not pu:
                    rejected.append({"platform":"쿠팡","kind":"coupang_partners_api_search","candidate_name":name_text,"reason":"쿠팡 API 상품 URL·ID 연결 불일치 또는 없음"});continue
                if pu and _is_direct_coupang_product_url(pu) and pu not in api_detail_urls:api_detail_urls.append(pu)
                if iu and all(x.get("url")!=iu for x in api_sources):
                    api_sources.append({"url":iu,"platform":"쿠팡","page_url":pu,"kind":"coupang_partners_api_search","image_role":"representative","match_score":m.get("match") or 1.0,"product_id":m.get("product_id") or "","query_used":m.get("query_used") or "","candidate_name":m.get("name") or ""})
            sources=api_sources+[x for x in sources if all(a.get("url")!=x.get("url") for a in api_sources)]
        except Exception as e:
            api_state["errors"].append(str(e));log("쿠팡 API 이미지 검색 실패: "+str(e))

    # v8.08.46 NAVER API HUB Image Search exact bridge.
    # NAVER Shopping Search API is NOT used for the image-3 stage. Search recall
    # can be broadened, but every result title is revalidated against the untouched
    # original product name/model/capacity/count before any bytes are accepted.
    naver_image_state={"ready":naver_image_api.ready(),"queries":0,"matched":0,"errors":[],"endpoint":"NAVER_API_HUB_IMAGE"}
    if naver_image_state["ready"] and cfg.get("naver_image_api_enabled",True):
        naver_image_state["errors"]=["이미지 검색 API는 원본 상품 페이지를 제공하지 않아 사진 확정에서 제외합니다."]
        rejected.append({"platform":"네이버이미지API","kind":"naver_image_search_api",
                         "reason":"검색 결과 제목만으로 사진을 확정하지 않음: 원본 상품 페이지 연결 근거 없음"})

    # Same-run discovery thumbnails across all 3 sites require no new browser search.
    rows=_same_product_candidate_rows(con,product)
    exact_rows=[];coupang_rows=[]
    for r in rows:
        if coupang_only and r.get("platform")!="쿠팡":
            continue
        iok,_,idetail=_strict_image_source_accept(r.get("name") or "", product["name"])
        if not iok:
            rejected.append({"platform":r.get("platform") or "","kind":"discovery_snapshot","candidate_name":r.get("name") or "","reason":"이미지용 동일상품 엄격검증 실패","match_detail":idetail})
            continue
        exact_rows.append(r)
        if r.get("platform")=="쿠팡":
            coupang_rows.append(r)
        iu=r.get("image_url") or ""
        if iu and all(x.get("url")!=iu for x in sources):
            sources.append({"url":iu,"platform":r.get("platform") or "","page_url":r.get("url") or "","kind":"discovery_snapshot","candidate_name":r.get("name") or "","match_score":r.get("score") or 0})

    # The TOP100 source URL is already the product selected by the discovery
    # stage. Preserve both Coupang and other-market direct URLs as exact detail
    # candidates; v7.44 accidentally discarded the Coupang source URL here.
    source_direct=[];coupang_source_direct=[]
    try:
        su=str(product["source_url"] or "").strip()
    except Exception:
        su=""
    if su:
        ss=_site_from_url(su)
        if ss=="쿠팡" and _is_direct_coupang_product_url(su):
            coupang_source_direct.append(su)
        elif not coupang_only and ss and _is_direct_market_product_url(su,ss):
            source_direct.append((ss,su,"top100_source_url"))

    # API/snapshot miss used to terminate without doing the documented keyword
    # lookup. Perform one controlled core-keyword search, then validate the card
    # against the untouched full product name and variant tokens.
    resolver_state={"attempted":False}
    # A discovery row can still point to /np/search or a ranking page. v7.47.7
    # counted any Coupang row as if a product page existed, which skipped the
    # resolver and left the browser on the result list. Only a real direct
    # product URL may suppress product-page resolution.
    snapshot_direct_urls=[
        str(r.get("url") or "") for r in coupang_rows
        if _is_direct_coupang_product_url(r.get("url") or "")
    ]
    # Repair mode ALWAYS rechecks Coupang API first, even when an old/stale direct
    # URL exists. This fixes the v7.50 behavior where a repair could appear to jump
    # straight to Toss without a fresh Coupang lookup.
    coupang_near_candidates=[]
    if repair_mode or not (coupang_source_direct or api_detail_urls or snapshot_direct_urls):
        resolver_state={"attempted":True,**_resolve_coupang_product_link(product,cfg,repair_mode=repair_mode)}
        coupang_near_candidates=list(resolver_state.get("near_candidates") or [])
        if resolver_state.get("ok"):
            ru=resolver_state.get("url") or "";riu=resolver_state.get("image_url") or ""
            if ru and ru not in coupang_source_direct:coupang_source_direct.insert(0,ru)
            if riu and all(x.get("url")!=riu for x in sources):
                sources.insert(0,{"url":riu,"platform":"쿠팡","page_url":ru,
                  "kind":"coupang_api_repair_or_resolver","image_role":"representative",
                  "candidate_name":resolver_state.get("candidate_name") or "",
                  "match_score":resolver_state.get("match") or 0,
                  "query_used":resolver_state.get("query") or ""})

    if strict_cg_only:
        coupang_exact_found=bool(coupang_source_direct or api_detail_urls or coupang_rows or
                                 any(pr.get("site")=="쿠팡" for pr in price_records) or prior_exact_product or
                                 any(str(x.get("platform") or "")=="쿠팡" for x in sources))
    else:
        coupang_exact_found=bool(coupang_source_direct or api_detail_urls or exact_rows or price_records or prior_exact_product or sources or source_direct)
    toss_fallback={"ok":False,"state":{"attempted":False},"reason":"not_attempted","near_candidates":[]};toss_detail_urls=[];toss_near_candidates=[]
    toss_price=next((x for x in fallback_price_records if x.get("site")=="토스쇼핑" and (x.get("url") or x.get("image_url"))),None)
    if toss_price:
        toss_fallback={"ok":True,"state":{"attempted":True,"reason_code":"PRICE_EVIDENCE_STRICT_MATCH","matched":1,"rows_scanned":1},
                       "near_candidates":[],"candidate_name":toss_price.get("product_name") or product["name"],
                       "url":toss_price.get("url") or "","image_url":toss_price.get("image_url") or "",
                       "match":toss_price.get("match") or 1.0,"match_detail":toss_price.get("match_detail") or {},
                       "product_id":toss_price.get("product_id") or "","price":toss_price.get("price"),
                       "source":"verified_price_evidence"}
        if toss_fallback.get("url"):toss_detail_urls.append(toss_fallback["url"])
    # If Coupang API/snapshot cannot resolve the product, try official Toss API.
    # Repair mode still did a fresh Coupang API lookup first above.
    if (not strict_cg_only) and (not coupang_exact_found) and cfg.get("image_toss_api_fallback_enabled",True):
        toss_fallback=_toss_api_exact_product(product,cfg,repair_mode=repair_mode)
        toss_near_candidates=list(toss_fallback.get("near_candidates") or (toss_fallback.get("state") or {}).get("near_candidates") or [])
        if toss_fallback.get("ok"):
            tu=toss_fallback.get("url") or "";ti=toss_fallback.get("image_url") or ""
            if ti:
                sources.insert(0,{"url":ti,"platform":"토스쇼핑","page_url":tu,
                                  "kind":"toss_sharelink_api_fallback","image_role":"representative",
                                  "candidate_name":toss_fallback.get("candidate_name") or "",
                                  "match_score":toss_fallback.get("match") or 0})
            if tu:toss_detail_urls.append(tu)
        else:
            for nc in toss_near_candidates:
                u=nc.get("url") or ""
                if u and u not in toss_detail_urls:toss_detail_urls.append(u)
    naver_exact_found=bool(naver_image_state.get("matched") or 0)
    exact_product_found=bool(coupang_exact_found or toss_fallback.get("ok") or naver_exact_found)
    # Similar candidates only authorize direct-page inspection; they are not
    # accepted until the page passes the original full-name/option validation.
    provisional_product_found=bool(coupang_near_candidates or toss_near_candidates)
    coupang_near_page_confirmed=False;toss_near_page_confirmed=False

    saved=[];hashes=[]
    def role_class(kind="",image_role="",require_product_visible=False):
        text=(str(kind or "")+" "+str(image_role or "")).lower()
        # Representative must be decided first. v8.08.36 classified every kind
        # containing 'google_source_product' as secondary, so Google could never
        # rescue a missing slot-1 even after an exact source page was validated.
        if (str(image_role or "").lower() in {"representative","search_exact"} or
            any(x in text for x in ("partners_api_search","price_evidence","discovery_snapshot",
                                     "sharelink_api_fallback","api_repair_or_resolver",
                                     "google_exact_original_representative"))):
            return "representative"
        if require_product_visible or any(x in text for x in ("detail","product_crop","description","google_source_product")):
            return "secondary"
        if "gallery" in text:
            return "secondary"
        return ""

    def role_available(slot_class):
        if slot_class=="representative":return not any(x.get("slot_class")=="representative" for x in saved)
        if slot_class=="secondary":return any(x.get("slot_class")=="representative" for x in saved) and sum(1 for x in saved if x.get("slot_class")=="secondary")<2
        return False

    def _representative_source_allowed(rec):
        kind=str(rec.get("kind") or "")
        platform=str(rec.get("platform") or "")
        page_url=str(rec.get("page_url") or "")
        if kind=="coupang_partners_api_search":
            return bool(page_url and _is_direct_coupang_product_url(page_url))
        if kind=="naver_image_search_api":
            return bool(cfg.get("image_naver_image_api_as_last_resort_enabled",True))
        if kind in {"price_evidence","discovery_snapshot","toss_sharelink_api_fallback","coupang_api_repair_or_resolver"}:
            if platform=="쿠팡":return bool(page_url and _is_direct_coupang_product_url(page_url))
            return bool(platform and page_url and _is_direct_market_product_url(page_url,platform))
        return False

    def _representative_source_priority(rec):
        kind=str(rec.get("kind") or "")
        platform=str(rec.get("platform") or "")
        page_url=str(rec.get("page_url") or "")
        if kind=="coupang_partners_api_search" and page_url and _is_direct_coupang_product_url(page_url):return (0,platform,kind)
        if platform=="쿠팡" and page_url and _is_direct_coupang_product_url(page_url):return (1,platform,kind)
        if kind=="naver_image_search_api":return (2,platform,kind)
        if platform and page_url and _is_direct_market_product_url(page_url,platform):return (3,platform,kind)
        return (50,platform,kind)

    def save_local(lp,kind="market_local_reuse",platform="",page_url="",image_role="",require_product_visible=False,visual_metrics=None):
        if len(saved)>=want:return False
        try:
            slot_class=role_class(kind,image_role,require_product_visible)
            if not role_available(slot_class):
                rejected.append({"path":str(lp),"reason":"대표 1장 + 상세/갤러리 2장 역할 구성에 맞지 않는 이미지","image_role":image_role,"kind":kind});return False
            check_visible=(slot_class=="secondary")
            metrics=visual_metrics or (product_visual_metrics(lp) if check_visible else None)
            if check_visible and not metrics.get("ok"):
                rejected.append({"path":str(lp),"reason":"제품이 보이지 않는 문서/표시사항 중심 이미지 제외","visual_metrics":metrics,"image_role":image_role});return False
            with Image.open(lp) as opened:
                im=opened.convert("RGB").copy()
            w,h=im.size
            if min(w,h)<int(cfg.get("image_min_dimension",180)):
                rejected.append({"path":str(lp),"reason":f"해상도 부족 {w}x{h}"});return False
            dh=_dhash(lp)
            if any(_ham(dh,x)<6 for x in hashes):
                rejected.append({"path":str(lp),"reason":"중복/거의 동일한 제품 이미지"});return False
            final=_image_dest_path(post_dir,photo_title,len(saved)+1);im.thumbnail((1600,1600))
            tmp_final=post_dir/f"_reuse_final_{len(saved)+1}.jpg"
            im.save(tmp_final,"JPEG",quality=94);im.close()
            if final.exists() and final.resolve()!=tmp_final.resolve():final.unlink()
            tmp_final.replace(final)
            hashes.append(dh);saved.append({"url":"","platform":platform,"page_url":page_url,"kind":kind,"image_role":image_role,
                                           "slot_class":slot_class,"path":str(final),"sha256":real_photo_policy.sha256(final),
                                           "width":w,"height":h,"product_visible":True if check_visible else None,"visual_metrics":metrics})
            return True
        except Exception as e:
            rejected.append({"path":str(lp),"reason":"로컬 제품 이미지 검증 실패: "+str(e)});return False

    def save_url(rec):
        """Save a title/gallery image. Detail content must use save_detail_url()."""
        if len(saved)>=want:return False
        if not rec.get("page_url") or rec.get("kind")=="naver_image_search_api":
            rejected.append({**rec,"reason":"검증된 원본 상품 페이지가 없는 사진 제외"});return False
        slot_class=role_class(rec.get("kind"),rec.get("image_role"),False)
        if not role_available(slot_class):
            rejected.append({**rec,"reason":"대표 1장 + 상세/갤러리 2장 역할 구성에 맞지 않는 URL 이미지"});return False
        tmp=post_dir/f"_candidate_{len(saved)+len(rejected)+1}.jpg"
        if not _download_source_image(rec,tmp):
            rejected.append({**rec,"reason":"제품 이미지 다운로드/판독 실패"});tmp.unlink(missing_ok=True);return False
        try:
            im=Image.open(tmp).convert("RGB");w,h=im.size;min_dim=int(cfg.get("image_min_dimension",180))
            if w<min_dim or h<min_dim:
                rejected.append({**rec,"reason":f"해상도 부족 {w}x{h} (최소 {min_dim})"});tmp.unlink(missing_ok=True);return False
            dh=_dhash(tmp)
            if any(_ham(dh,x)<6 for x in hashes):
                rejected.append({**rec,"reason":"중복/거의 동일한 제품 이미지"});tmp.unlink(missing_ok=True);return False
            final=_image_dest_path(post_dir,photo_title,len(saved)+1)
            if final.exists():final.unlink()
            tmp.replace(final);hashes.append(dh)
            # Gallery images come only from an exact product page; additionally
            # reject text/spec/barcode-like sheets before using a secondary slot.
            metrics=product_visual_metrics(final) if slot_class=="secondary" else None
            if slot_class=="secondary" and not metrics.get("ok"):
                final.unlink(missing_ok=True);hashes.pop()
                rejected.append({**rec,"reason":"제품이 보이지 않는 갤러리/문서형 이미지 제외","visual_metrics":metrics});return False
            saved.append({**rec,"slot_class":slot_class,"path":str(final),"sha256":real_photo_policy.sha256(final),
                          "width":w,"height":h,"product_visible":True,"visual_metrics":metrics})
            return True
        except Exception as e:
            rejected.append({**rec,"reason":"제품 이미지 검증 오류: "+str(e)});tmp.unlink(missing_ok=True);return False

    def save_detail_url(rec):
        """Download a seller detail image, crop product-rich windows, reject text sheets."""
        if len(saved)>=want:return 0
        tmp=post_dir/f"_detail_source_{len(saved)+len(rejected)+1}.jpg"
        if not _download_detail_source_image(rec,tmp):
            rejected.append({**rec,"reason":"상세 이미지 다운로드 실패"});tmp.unlink(missing_ok=True);return 0
        added=0
        try:
            # Keep the downloaded source only as temporary evidence; never save a
            # full legal/spec poster directly as a blog image.
            candidates=_detail_product_crop_candidates(tmp,post_dir,max_candidates=int(cfg.get("image_detail_product_crop_scan_windows",12)))
            if not candidates:
                m=product_visual_metrics(tmp)
                rejected.append({**rec,"reason":"제품이 보이는 상세영역을 찾지 못함","visual_metrics":m})
            for c in candidates:
                if len(saved)>=want:break
                cp=c.get("path")
                if not cp or not Path(cp).exists():continue
                platform=str(rec.get("platform") or "쿠팡")
                kind="toss_detail_product_visible_crop" if platform=="토스쇼핑" else "coupang_detail_product_visible_crop"
                if save_local(cp,kind,platform,rec.get("page_url") or "","detail_product_crop",True,c):
                    saved[-1]["source_url"]=rec.get("url") or "";saved[-1]["crop_box"]=c.get("box");added+=1
            return added
        finally:
            tmp.unlink(missing_ok=True)
            for x in post_dir.glob("_product_crop_*.jpg"):x.unlink(missing_ok=True)

    # A network failure today does not invalidate files already verified in a
    # previous run. Preserve those files and continue filling only the shortage.
    if not exact_product_found and not provisional_product_found:
        if prior_exact_product and local_records:
            exact_product_found=True
        elif not bool(cfg.get("image_google_source_fallback_enabled",True)):
            failure=_image_failure_summary(0,want,resolver_state,toss_fallback,detail_sources,rejected,api_state,None,naver_image_state)
            evidence={"target":product["name"],"required":want,"source_policy":strict_page_policy,"identity_verification":IDENTITY_POLICY,
                      "verified_count":0,"verified":False,"exact_product_found":False,"exact_coupang_found":False,
                      "composition":{"policy":"COUPANG_GOOGLE_EXACT_PRODUCT_TRIPLE_V8_08_43",
                                     "representative_count":0,"secondary_count":0,"ordered_roles":[],"verified":False},
                      "preserved_existing_count":0,
                      "pending_reason":failure.get("short") or "쿠팡/토스 동일상품 미확인","failure_summary":failure,
                      "images":[],"coupang_api":api_state,"naver_image_api":naver_image_state,"google_source_fallback":google_source_fallback,"toss_api_fallback":toss_fallback,
                      "detail_sources":detail_sources,"rejected":rejected,"coupang_resolver":resolver_state,
                      "coupang_web_opened":False,"checked_at":time.strftime("%Y-%m-%d %H:%M:%S")}
            ep=post_dir/"image_evidence.json";ep.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
            return [],str(ep)
        else:
            # v8.08.42: Google may itself establish an exact source-page identity.
            # Do not terminate before the Google Images/Web resolver has a chance.
            stage("쿠팡/토스 동일상품 미확인 · Google 동일상품 원본 탐색으로 계속")

    # Reuse local evidence first.
    for rec in local_records:
        if len(saved)>=want:break
        save_local(rec.get("path"),rec.get("kind") or "verified_existing_or_price_local",
                   rec.get("platform") or "",rec.get("page_url") or "",rec.get("image_role") or "",
                   bool(rec.get("require_product_visible")))

    # v7.61: once the product itself is found, prefer the clicked product page's
    # representative/gallery/detail images over a pile of external thumbnails.
    # Save at most ONE representative source image before opening the product
    # page, then fill the rest from that exact product page.
    representative_sources=[rec for rec in sources if str(rec.get("image_role") or "") in {"representative","search_exact"}]
    if page_grounded_only:
        representative_sources=[rec for rec in representative_sources if _representative_source_allowed(rec)]
        representative_sources.sort(key=_representative_source_priority)
    elif not representative_sources:
        representative_sources=list(sources[:1])
    for rec in representative_sources:
        if len(saved)>=want or any(x.get("slot_class")=="representative" for x in saved):break
        save_url(rec)

    # Crucial v7.38 behavior: make the direct product-page decision AFTER dHash
    # validation.  Three different URLs that are actually the same photo no
    # longer suppress the gallery fallback.
    if bool(cfg.get("coupang_web_image_access_enabled",False)) and cfg.get("image_allow_coupang_browser_detail_fallback",False) and len(saved)<want:
        seen=set();detail_candidates=[];provisional_by_url={}
        for u in coupang_source_direct:
            if _is_direct_coupang_product_url(u) and u not in seen:
                detail_candidates.append(u);seen.add(u)
        for u in api_detail_urls:
            if _is_direct_coupang_product_url(u) and u not in seen:
                detail_candidates.append(u);seen.add(u)
        for pr in price_records:
            u=pr.get("url") or ""
            if _is_direct_coupang_product_url(u) and u not in seen:
                detail_candidates.append(u);seen.add(u)
        for r in coupang_rows:
            u=r.get("url") or ""
            if _is_direct_coupang_product_url(u) and u not in seen:
                detail_candidates.append(u);seen.add(u)
        # Similar API candidates are compared on their direct product page only.
        # They never use /np/search and never become valid merely from fuzzy title.
        for nc in coupang_near_candidates:
            u=nc.get("url") or ""
            if _is_direct_coupang_product_url(u):
                provisional_by_url[u]=nc
                if u not in seen:detail_candidates.append(u);seen.add(u)
        max_pages=max(1,int(cfg.get("image_coupang_detail_max_pages_per_product",1)))
        if coupang_near_candidates:
            max_pages=max(max_pages,1+int(cfg.get("image_coupang_near_candidate_page_checks",2)))
        for u in detail_candidates[:max_pages]:
            # PASS A (fast): read the exact product page DOM without scrolling.
            # First prefer TITLE/GALLERY product images. If the page exposes 3
            # distinct gallery images, these become the final 3 blog photos and
            # no detail scrolling/cropping is needed at all.
            d=_detail_images_via_normal_chrome(product,u,"쿠팡",capture_rendered=False,trust_direct=(u not in provisional_by_url))
            detail_sources.append({"url":u,"platform":"쿠팡","pass":"gallery_then_detail_dom_fast","provisional_near":u in provisional_by_url,**d})
            if d.get("blocked"):break
            if d.get("ok"):
                if u in provisional_by_url:
                    # The full rendered page has now passed strict identity, so the
                    # provisional API result is promoted to exact and its API image
                    # may safely become the representative photo.
                    coupang_near_page_confirmed=True;exact_product_found=True;coupang_exact_found=True
                    nc=provisional_by_url[u];niu=nc.get("image_url") or ""
                    if niu and len(saved)<want:
                        save_url({"url":niu,"platform":"쿠팡","page_url":u,"kind":"coupang_near_candidate_page_confirmed","image_role":"representative","candidate_name":nc.get("candidate") or "","query_used":nc.get("query") or "","match_score":nc.get("score") or 0})
                gallery=[];dom_details=[]
                for im in d.get("images") or []:
                    if not isinstance(im,dict):continue
                    role=str(im.get("role") or im.get("kind") or "")
                    if role=="product_gallery_or_main" and not im.get("detail_zone"):
                        gallery.append(im)
                    elif im.get("detail_zone") or role=="detail_description_dom":
                        dom_details.append(im)
                gallery.sort(key=lambda x:-float(x.get("score") or 0))
                dom_details.sort(key=lambda x:-float(x.get("score") or 0))
                for im in gallery:
                    if len(saved)>=want:break
                    iu=im.get("url") or ""
                    if not iu or str(iu).startswith(("blob:","data:")):continue
                    save_url({"url":iu,"platform":"쿠팡","page_url":d.get("page_url") or u,
                              "kind":"coupang_title_gallery_dom","image_role":"title_gallery",
                              "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or ""})
                # Only when title/gallery is short do we inspect detail images.
                if len(saved)<want:
                    for im in dom_details:
                        if len(saved)>=want:break
                        iu=im.get("url") or ""
                        if not iu or str(iu).startswith(("blob:","data:")):continue
                        save_detail_url({"url":iu,"platform":"쿠팡","page_url":d.get("page_url") or u,
                                         "kind":"coupang_detail_dom_direct","image_role":"detail_description_dom",
                                         "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or ""})
            if len(saved)>=want:break

            # PASS B: direct DOM URLs were insufficient. Render the same exact
            # product page. The extension tries representative/gallery images
            # BEFORE it scrolls into product detail. Detail captures are accepted
            # only after the Python product-visible gate rejects document-like
            # legal/specification/barcode sheets.
            d2=_detail_images_via_normal_chrome(product,u,"쿠팡",capture_rendered=True,trust_direct=(u not in provisional_by_url))
            detail_sources.append({"url":u,"platform":"쿠팡","pass":"rendered_gallery_then_product_crop",**d2})
            if d2.get("blocked"):break
            if not d2.get("ok"):continue
            captures=d2.get("screen_captures") or []
            def capture_role(sc):
                return ((sc.get("source_meta") or {}).get("role") if isinstance(sc,dict) else "") or "rendered_crop"
            gallery_roles={"representative","gallery_title","gallery_fallback"}
            detail_roles={"detail_description","detail_long_segment","detail_container_segment","detail_product_crop"}
            # Preserve the user's rule: title/gallery images first; only fill
            # remaining slots from product-visible detail crops.
            for sc in [x for x in captures if capture_role(x) in gallery_roles]:
                if len(saved)>=want:break
                pth=sc.get("path") if isinstance(sc,dict) else None
                if not pth or not Path(pth).exists():continue
                role=capture_role(sc)
                save_local(pth,"coupang_title_gallery_screen_crop","쿠팡",d2.get("page_url") or u,role,False)
            for sc in [x for x in captures if capture_role(x) in detail_roles]:
                if len(saved)>=want:break
                pth=sc.get("path") if isinstance(sc,dict) else None
                if not pth or not Path(pth).exists():continue
                role=capture_role(sc)
                save_local(pth,"coupang_detail_product_visible_screen_crop","쿠팡",d2.get("page_url") or u,role,True)
            # After lazy-load, new detail URLs may have appeared. Crop the useful
            # product area from them rather than saving the entire seller poster.
            if len(saved)<want:
                for im in d2.get("images") or []:
                    if len(saved)>=want:break
                    if not isinstance(im,dict):continue
                    role=str(im.get("role") or im.get("kind") or "")
                    if not (im.get("detail_zone") or role=="detail_description_dom"):continue
                    iu=im.get("url") or ""
                    if not iu or str(iu).startswith(("blob:","data:")):continue
                    save_detail_url({"url":iu,"platform":"쿠팡","page_url":d2.get("page_url") or u,
                                     "kind":"coupang_detail_dom_after_render","image_role":"detail_description_dom",
                                     "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or ""})
            if len(saved)>=want:break

    def _image_url_key(value):
        try:
            u=urllib.parse.urlsplit(str(value or "").strip())
            host=(u.hostname or "").lower().replace("www.","")
            path=urllib.parse.unquote(u.path or "").rstrip("/")
            return host+path
        except Exception:
            return str(value or "").split("?",1)[0].strip().lower()

    # v8.08.42 Google exact-image recovery.
    # Primary: Google Images discovers source page + original image URL.
    # Secondary: classic Google Web results. Every destination page is opened and
    # validated against the untouched product/model/option text before bytes are
    # accepted. Google preview thumbnails themselves are never saved.
    if len(saved)<want and bool(cfg.get("image_google_source_fallback_enabled",True)):
        stage("Google 이미지검색 · 동일상품 원본페이지 탐색")
        def _gprog(d,t,m):
            stage("Google 검색 " + str(m or f"{d}/{t}"))
        google_source_fallback=_google_exact_product_source_pages(product,cfg,progress=_gprog)
        accepted_google=list(google_source_fallback.get("accepted") or [])
        google_rendered_attempts=0
        for gi,grec in enumerate(accepted_google,1):
            if len(saved)>=want:break
            gu=str(grec.get("url") or "").strip()
            if not gu:continue
            stage(f"Google 원본페이지 {gi}/{len(accepted_google)} 동일상품 검증")
            gd=_detail_images_via_normal_chrome(product,gu,"구글원본",capture_rendered=False,trust_direct=False)
            page_rec={"url":gu,"google_title":grec.get("title") or "","google_score":grec.get("score") or 0,"surface":grec.get("surface") or "",**gd}
            google_source_fallback.setdefault("pages",[]).append(page_rec)
            detail_sources.append({"url":gu,"platform":"구글원본","pass":"google_images_web_original_page_dom","surface":grec.get("surface") or "",**gd})
            if not gd.get("ok"):
                rejected.append({"platform":"구글원본","kind":"google_source_page_reject","page_url":gu,"candidate_name":grec.get("title") or "","reason":gd.get("reason") or "원본 페이지 동일상품 재검증 실패","match_detail":gd.get("match_detail") or {}})
                continue
            exact_product_found=True
            # Google Images may expose the original CDN image URL together with
            # the source page. It is accepted only now, after source-page identity
            # validation. This is NOT the Google thumbnail.
            direct_original=str(grec.get("image_url") or "").strip()
            trusted_page_image_keys={_image_url_key(im.get("url") or "") for im in (gd.get("images") or [])
                                     if isinstance(im,dict) and bool(im.get("trusted_product_zone",False)) and im.get("url")}
            direct_original_confirmed=bool(direct_original and _image_url_key(direct_original) in trusted_page_image_keys)
            if direct_original and not direct_original_confirmed:
                rejected.append({"platform":"구글원본","kind":"google_direct_original_crosscheck_reject","page_url":gu,"url":direct_original,
                                 "reason":"Google imgurl이 검증된 원본 상품페이지의 상품 이미지 URL과 교차확인되지 않아 제외"})
            if direct_original_confirmed and bool(cfg.get("image_google_direct_original_url_enabled",True)) and len(saved)<want:
                role="representative" if not any(x.get("slot_class")=="representative" for x in saved) else "title_gallery"
                kind="google_exact_original_representative" if role=="representative" else "google_source_product_gallery_original_url"
                stage("Google 원본 이미지 URL 교차검증 후 다운로드")
                save_url({"url":direct_original,"platform":"구글원본","page_url":gu,"kind":kind,"image_role":role,
                          "candidate_name":grec.get("title") or "","surface":grec.get("surface") or "","google_rank":grec.get("rank") or 0,
                          "source_page_crosschecked":True})
            gallery=[];details=[]
            for im in gd.get("images") or []:
                if not isinstance(im,dict):continue
                if not bool(im.get("trusted_product_zone",False)):
                    rejected.append({"platform":"구글원본","kind":"google_image_zone_reject","page_url":gu,"url":im.get("url") or "","reason":"상품 본체 영역이 아닌 추천/관련/불명확 이미지 제외","alt":im.get("alt") or ""})
                    continue
                role=str(im.get("role") or im.get("kind") or "")
                if role=="product_gallery_or_main" and not im.get("detail_zone"):gallery.append(im)
                elif im.get("detail_zone") or role=="detail_description_dom":details.append(im)
            gallery.sort(key=lambda x:-float(x.get("score") or 0));details.sort(key=lambda x:-float(x.get("score") or 0))
            # If Coupang did not provide slot 1, a validated original product page
            # may establish the representative. Otherwise these fill only slots 2/3.
            for im in gallery:
                if len(saved)>=want:break
                iu=im.get("url") or ""
                if not iu:continue
                rep_missing=not any(x.get("slot_class")=="representative" for x in saved)
                image_role="representative" if rep_missing and bool(cfg.get("image_google_allow_representative_when_coupang_missing",True)) else "title_gallery"
                kind="google_exact_original_representative" if image_role=="representative" else "google_source_product_gallery"
                save_url({"url":iu,"platform":"구글원본","page_url":gu,"kind":kind,"image_role":image_role,
                          "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or "","candidate_name":grec.get("title") or ""})
            if len(saved)<want:
                for im in details:
                    if len(saved)>=want:break
                    iu=im.get("url") or ""
                    if not iu:continue
                    save_detail_url({"url":iu,"platform":"구글원본","page_url":gu,"kind":"google_source_product_detail","image_role":"detail_description_dom",
                                     "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or "","candidate_name":grec.get("title") or ""})
            # DOM URLs can be blocked by hotlink protection or hidden behind SPA
            # lazy loading. Re-open the SAME verified page with CDP scrolling and
            # rendered screenshot crops before giving up.
            if (len(saved)<want and bool(cfg.get("image_google_source_rendered_fallback_enabled",True))
                    and google_rendered_attempts<int(cfg.get("image_google_rendered_page_checks",3))):
                google_rendered_attempts+=1
                stage(f"Google 원본페이지 렌더링/지연로딩 보강 {google_rendered_attempts}/{int(cfg.get('image_google_rendered_page_checks',3))}")
                gd2=_detail_images_via_normal_chrome(product,gu,"구글원본",capture_rendered=True,trust_direct=False)
                google_source_fallback.setdefault("rendered_pages",[]).append({"url":gu,**gd2})
                detail_sources.append({"url":gu,"platform":"구글원본","pass":"google_original_page_cdp_rendered","surface":grec.get("surface") or "",**gd2})
                if gd2.get("ok"):
                    for im in gd2.get("images") or []:
                        if len(saved)>=want:break
                        if not isinstance(im,dict):continue
                        if not bool(im.get("trusted_product_zone",False)):
                            rejected.append({"platform":"구글원본","kind":"google_rendered_zone_reject","page_url":gu,"url":im.get("url") or "","reason":"렌더링 후에도 상품 본체 영역으로 확인되지 않은 이미지 제외","alt":im.get("alt") or ""})
                            continue
                        iu=im.get("url") or "";role=str(im.get("role") or "")
                        if not iu:continue
                        if role=="product_gallery_or_main" and not im.get("detail_zone"):
                            rep_missing=not any(x.get("slot_class")=="representative" for x in saved)
                            image_role="representative" if rep_missing and bool(cfg.get("image_google_allow_representative_when_coupang_missing",True)) else "title_gallery"
                            kind="google_exact_original_representative" if image_role=="representative" else "google_source_product_gallery_after_scroll"
                            save_url({"url":iu,"platform":"구글원본","page_url":gu,"kind":kind,"image_role":image_role,"alt":im.get("alt") or ""})
                        elif im.get("detail_zone") or role=="detail_description_dom":
                            save_detail_url({"url":iu,"platform":"구글원본","page_url":gu,"kind":"google_source_product_detail_after_scroll","image_role":"detail_description_dom","alt":im.get("alt") or ""})
                    for sc in gd2.get("screen_captures") or []:
                        if len(saved)>=want:break
                        pth=sc.get("path") if isinstance(sc,dict) else None
                        if not pth or not Path(pth).exists():continue
                        rep_missing=not any(x.get("slot_class")=="representative" for x in saved)
                        role=((sc.get("source_meta") or {}).get("role") if isinstance(sc,dict) else "") or "external_rendered_image"
                        if rep_missing and bool(cfg.get("image_google_allow_representative_when_coupang_missing",True)):
                            save_local(pth,"google_exact_original_representative_screen","구글원본",gu,"representative",False)
                        else:
                            save_local(pth,"google_source_product_rendered_crop","구글원본",gu,role,True)


    # resolve/confirm the same product through official Toss Sharelink API.
    # The API thumbnail is saved immediately for strict matches. For a similar
    # title candidate, the toss.shopping direct page must pass full-name/option
    # validation before any of its images are accepted.
    if (not strict_cg_only) and len(saved)<want and cfg.get("image_toss_api_fallback_enabled",True):
        stage("토스 동일상품 API/상품페이지 마지막 보강")
        if not (toss_fallback.get("state") or {}).get("attempted"):
            toss_fallback=_toss_api_exact_product(product,cfg,repair_mode=repair_mode)
            toss_near_candidates=list(toss_fallback.get("near_candidates") or (toss_fallback.get("state") or {}).get("near_candidates") or [])
        toss_meta_by_url={}
        if toss_fallback.get("ok"):
            tu=toss_fallback.get("url") or "";ti=toss_fallback.get("image_url") or ""
            if ti and len(saved)<want:
                save_url({"url":ti,"platform":"토스쇼핑","page_url":tu,
                          "kind":"toss_sharelink_api_fallback","image_role":"representative",
                          "candidate_name":toss_fallback.get("candidate_name") or "",
                          "match_score":toss_fallback.get("match") or 0})
            if tu:
                toss_meta_by_url[tu]={"strict":True,"candidate_name":toss_fallback.get("candidate_name") or "","image_url":ti,"match":toss_fallback.get("match") or 0}
                if tu not in toss_detail_urls:toss_detail_urls.insert(0,tu)
        for nc in toss_near_candidates:
            u=nc.get("url") or ""
            if not u:continue
            toss_meta_by_url[u]={"strict":False,"candidate_name":nc.get("name") or nc.get("candidate_name") or "","image_url":nc.get("image_url") or "","match":nc.get("match") or 0}
            if u not in toss_detail_urls:toss_detail_urls.append(u)

        max_toss_pages=max(1,int(cfg.get("image_toss_detail_max_pages_per_product",1)))
        if toss_near_candidates:max_toss_pages=max(max_toss_pages,int(cfg.get("image_toss_near_candidate_page_checks",3)))
        for u in toss_detail_urls[:max_toss_pages]:
            if len(saved)>=want:break
            meta=toss_meta_by_url.get(u,{"strict":bool(toss_fallback.get("ok"))})
            # PASS A: direct DOM URLs first, without unnecessary scrolling.
            td=_detail_images_via_normal_chrome(product,u,"토스쇼핑",capture_rendered=False,trust_direct=bool(meta.get("strict")))
            detail_sources.append({"url":u,"platform":"토스쇼핑","pass":"toss_api_dom_fast","provisional_near":not bool(meta.get("strict")),**td})
            if td.get("ok"):
                if not meta.get("strict"):
                    toss_near_page_confirmed=True;exact_product_found=True
                    niu=meta.get("image_url") or ""
                    if niu and len(saved)<want:
                        save_url({"url":niu,"platform":"토스쇼핑","page_url":u,"kind":"toss_near_candidate_page_confirmed","image_role":"representative","candidate_name":meta.get("candidate_name") or "","match_score":meta.get("match") or 0})
                gallery=[];details=[]
                for im in td.get("images") or []:
                    if not isinstance(im,dict):continue
                    role=str(im.get("role") or im.get("kind") or "")
                    if role=="product_gallery_or_main" and not im.get("detail_zone"):gallery.append(im)
                    elif im.get("detail_zone") or role=="detail_description_dom":details.append(im)
                gallery.sort(key=lambda x:-float(x.get("score") or 0));details.sort(key=lambda x:-float(x.get("score") or 0))
                for im in gallery:
                    if len(saved)>=want:break
                    iu=im.get("url") or ""
                    if not iu or str(iu).startswith(("blob:","data:")):continue
                    save_url({"url":iu,"platform":"토스쇼핑","page_url":td.get("page_url") or u,
                              "kind":"toss_title_gallery_dom","image_role":"title_gallery",
                              "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or ""})
                for im in details:
                    if len(saved)>=want:break
                    iu=im.get("url") or ""
                    if not iu or str(iu).startswith(("blob:","data:")):continue
                    save_detail_url({"url":iu,"platform":"토스쇼핑","page_url":td.get("page_url") or u,
                                     "kind":"toss_detail_dom_direct","image_role":"detail_description_dom",
                                     "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or ""})
            else:
                # Near candidates that fail the full page check are explicitly
                # recorded as look-alikes, not silently treated as missing.
                if not meta.get("strict"):
                    rejected.append({"platform":"토스쇼핑","kind":"toss_near_page_reject","candidate_name":meta.get("candidate_name") or "","page_url":u,"reason":td.get("reason") or "토스 유사후보 상세페이지 풀네임 검증 실패","match_detail":td.get("match_detail") or {}})
                continue
            if len(saved)>=want:break

            # PASS B: render/crop the same exact Toss product page. v7.51 adds
            # toss.shopping extension permission + primary top-gallery capture,
            # so a visible 1/4 gallery now produces actual JPG files instead of
            # merely opening the page.
            td2=_detail_images_via_normal_chrome(product,u,"토스쇼핑",capture_rendered=True,trust_direct=bool(meta.get("strict")))
            detail_sources.append({"url":u,"platform":"토스쇼핑","pass":"toss_api_rendered_gallery_product_crop",**td2})
            if not td2.get("ok"):continue
            for sc in td2.get("screen_captures") or []:
                if len(saved)>=want:break
                pth=sc.get("path") if isinstance(sc,dict) else None
                if not pth or not Path(pth).exists():continue
                role=((sc.get("source_meta") or {}).get("role") if isinstance(sc,dict) else "") or "rendered_crop"
                require_visible=role not in {"representative","gallery_title","gallery_fallback","toss_title_gallery"}
                save_local(pth,"toss_rendered_product_crop","토스쇼핑",td2.get("page_url") or u,role,require_visible)
            if len(saved)<want:
                for im in td2.get("images") or []:
                    if len(saved)>=want:break
                    if not isinstance(im,dict):continue
                    role=str(im.get("role") or im.get("kind") or "")
                    if not (im.get("detail_zone") or role=="detail_description_dom"):continue
                    iu=im.get("url") or ""
                    if not iu or str(iu).startswith(("blob:","data:")):continue
                    save_detail_url({"url":iu,"platform":"토스쇼핑","page_url":td2.get("page_url") or u,
                                     "kind":"toss_detail_dom_after_render","image_role":"detail_description_dom",
                                     "width":im.get("width"),"height":im.get("height"),"alt":im.get("alt") or ""})

    # v7.43 alternative: if Coupang is blocked or still short, reuse an already
    # verified direct product URL from Naver/Toss. This performs no new search;
    # it only opens the exact product page already captured in the same run.
    if (not strict_cg_only) and len(saved)<want and not coupang_only and cfg.get("image_allow_other_market_direct_detail_fallback",True):
        alt_seen=set();alt_candidates=[]
        for site,u,kind in source_direct:
            key=(site,u)
            if key not in alt_seen:
                alt_seen.add(key);alt_candidates.append((site,u,kind))
        for r in exact_rows:
            site=r.get("platform") or "";u=r.get("url") or ""
            if site=="쿠팡" or not _is_direct_market_product_url(u,site):continue
            key=(site,u)
            if key not in alt_seen:alt_seen.add(key);alt_candidates.append((site,u,"discovery_exact"))
        for pr in price_records:
            site=pr.get("site") or "";u=pr.get("url") or ""
            if site=="쿠팡" or not _is_direct_market_product_url(u,site):continue
            key=(site,u)
            if key not in alt_seen:alt_seen.add(key);alt_candidates.append((site,u,"price_exact"))
        per_site={}
        for site,u,kind in alt_candidates:
            if len(saved)>=want:break
            if per_site.get(site,0)>=int(cfg.get("image_other_market_detail_max_pages_per_site",1)):continue
            per_site[site]=per_site.get(site,0)+1
            d=_detail_images_via_normal_chrome(product,u,site)
            detail_sources.append({"url":u,"platform":site,"fallback_kind":kind,**d})
            if not d.get("ok"):continue
            for im in d.get("images") or []:
                if len(saved)>=want:break
                iu=im.get("url") if isinstance(im,dict) else im
                if not iu or str(iu).startswith(("blob:","data:")):continue
                save_url({"url":iu,"platform":site,"page_url":d.get("page_url") or u,"kind":"other_market_direct_detail","image_role":"detail","width":im.get("width") if isinstance(im,dict) else None,"height":im.get("height") if isinstance(im,dict) else None})
            # v7.44: if the other marketplace renders an image that cannot be
            # downloaded directly (lazy/blob/CDN), use the exact product page's
            # rendered image crop. The page text has already passed strict matching.
            if len(saved)<want:
                for sc in d.get("screen_captures") or []:
                    if len(saved)>=want:break
                    pth=sc.get("path") if isinstance(sc,dict) else None
                    if not pth or not Path(pth).exists():continue
                    role=((sc.get("source_meta") or {}).get("role") if isinstance(sc,dict) else "") or "other_market_rendered_crop"
                    save_local(pth,"other_market_rendered_screen_crop",site,d.get("page_url") or u,role)

    # v7.71 image recovery: recent versions stopped too early once *any* exact
    # product page had been opened. In practice many pages yield only 1-2 usable
    # images, so the run ended at 1/3 or 2/3 even though we already had several
    # strict same-product thumbnails from API/snapshot evidence. Restore a
    # controlled backfill pass: if still short, keep filling from strict sources
    # first, then from the remaining validated sources. This preserves the
    # same-product guard while recovering the missing third image.
    def _strict_source_backfill(rec):
        kind=str(rec.get("kind") or "")
        role=str(rec.get("image_role") or "")
        platform=str(rec.get("platform") or "")
        return (
            kind in {"coupang_partners_api_search","discovery_snapshot","toss_sharelink_api_fallback","coupang_api_repair_or_resolver","naver_image_search_api"}
            or role in {"representative","title_gallery","search_exact"}
            or platform in {"쿠팡","토스쇼핑","네이버이미지API","네이버쇼핑"}
        )
    if len(saved)<want:
        if strict_cg_only or page_grounded_only or not bool(cfg.get("image_strict_source_fallback_after_page_failure",False)):
            rejected.append({"platform":"SYSTEM","kind":"generic_thumbnail_backfill_blocked","reason":"검증된 상품 페이지/API 외 검색 썸네일로 부족분을 채우지 않음","saved_count":len(saved),"required":want})
        else:
            strict_sources=[rec for rec in sources if _strict_source_backfill(rec)]
            relaxed_sources=[rec for rec in sources if rec not in strict_sources]
            for rec in strict_sources:
                if len(saved)>=want:break
                save_url(rec)
            # All remaining records were admitted only after product/option checks.
            # A direct URL merely existing must not suppress these safe fallbacks.
            if len(saved)<want:
                for rec in relaxed_sources:
                    if len(saved)>=want:break
                    save_url(rec)

    for x in post_dir.glob("_candidate_*.jpg"):x.unlink(missing_ok=True)
    # Remove stale legacy numeric files; current files use the review title.
    for idx in range(1,4):
        try:(post_dir/f"{idx}.jpg").unlink()
        except FileNotFoundError:pass

    physical=[x for x in saved if x.get("path") and Path(x["path"]).exists()]
    representative_count=sum(1 for x in physical if x.get("slot_class")=="representative")
    secondary_count=sum(1 for x in physical if x.get("slot_class")=="secondary")
    composition={"policy":"PRIMARY_PAGE_OR_EXACT_API_V1",
                 "representative_count":representative_count,"secondary_count":secondary_count,
                 "ordered_roles":[x.get("slot_class") for x in physical[:want]],
                 "verified":bool(len(physical)>=want and representative_count==1 and secondary_count>=2 and
                                 physical and physical[0].get("slot_class")=="representative")}
    naver_exact_used=any(str(x.get("kind") or "")=="naver_image_search_api" for x in physical)
    exact_product_found=bool(exact_product_found or coupang_near_page_confirmed or toss_near_page_confirmed or toss_fallback.get("ok") or naver_exact_used or (len(physical)>0 and prior_exact_product))
    exact_coupang_final=bool(coupang_source_direct or coupang_rows or api_detail_urls or coupang_near_page_confirmed)
    naver_image_state["used"]=sum(1 for x in physical if str(x.get("kind") or "")=="naver_image_search_api")
    failure=_image_failure_summary(len(physical),want,resolver_state,toss_fallback,detail_sources,rejected,api_state,google_source_fallback,naver_image_state)
    if len(physical)>=want and not composition["verified"]:
        failure={**failure,"code":"IMAGE_ROLE_COMPOSITION_FAILED",
                 "short":"대표 1장 + 제품이 보이는 상세/갤러리 2장 역할 구성 미충족"}
    evidence={"target":product["name"],"required":want,"source_policy":strict_page_policy,"identity_verification":IDENTITY_POLICY,
              "verified_count":len(physical),"verified":bool(composition["verified"]),"composition":composition,
              "exact_product_found":exact_product_found,"exact_coupang_found":exact_coupang_final,
              "preserved_existing_count":len(preserved_existing),
              "failure_summary":failure,"images":physical,"coupang_api":api_state,"naver_image_api":naver_image_state,"google_source_fallback":google_source_fallback,"toss_api_fallback":toss_fallback,
              "coupang_resolver":resolver_state,"coupang_near_page_confirmed":bool(coupang_near_page_confirmed),"toss_near_page_confirmed":bool(toss_near_page_confirmed),
              "detail_sources":detail_sources,"rejected":rejected,
              "coupang_web_opened":bool(cfg.get("coupang_web_image_access_enabled",False) and any(x.get("platform")=="쿠팡" for x in detail_sources)),
              "checked_at":time.strftime("%Y-%m-%d %H:%M:%S")}
    ep=post_dir/"image_evidence.json";ep.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    return [x["path"] for x in physical[:want]],str(ep)

def _sync_post_images(post_dir,images):
    """Keep post.json image blocks synchronized with the observed reference layout."""
    try:
        pj=Path(post_dir)/"post.json"
        if not pj.exists():return
        obj=json.loads(pj.read_text(encoding="utf-8"));base=[b for b in (obj.get("blocks") or []) if b.get("type")!="image"]
        if not images:
            obj["blocks"]=base;pj.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8");return
        blocks=list(base);slots=list(obj.get("reference_layout_slots") or ["after_intro","after_section_1","after_section_2"])[:3]
        while len(slots)<min(3,len(images)):slots.append(["after_intro","after_section_1","after_section_2"][len(slots)])
        def position_for(slot):
            if slot=="after_intro":
                intros=[j for j,b in enumerate(blocks) if b.get("type")=="paragraph" and b.get("role")=="intro"]
                has_share=any(b.get("type")=="sharelink" and b.get("position") in {"top","top_after_disclosure"} for b in blocks[:3])
                return (max(intros)+1) if intros else (2 if has_share else 1)
            m=re.match(r"after_section_(\d+)$",str(slot or ""))
            if m:
                n=int(m.group(1))
                return next((j for j,b in enumerate(blocks) if b.get("type")=="heading" and b.get("section_index")==n),
                            next((j for j,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks)))
            return next((j for j,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
        for i,path in enumerate(images[:3]):
            slot=slots[i] if i<len(slots) else f"before_advantages_{i+1}"
            pos=position_for(slot);blocks.insert(min(len(blocks),max(0,pos)),{"type":"image","file":Path(path).name,"slot":slot})
        obj["blocks"]=blocks;obj["reference_layout_slots"]=slots;obj["layout_policy"]="REFERENCE_MOBILE_V7_63"
        pj.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as e:log("post.json 이미지 동기화 실패: "+str(e))

def capture_product_images(product_id,progress=None):
    """Re-verify only one selected product's 3 real images."""
    init_db_fast();cfg=settings();con=db_connect(row_factory=True)
    try:
        r=con.execute("SELECT * FROM products WHERE id=?",(int(product_id),)).fetchone()
        if not r:raise RuntimeError("선택 상품을 찾지 못했습니다.")
        pdir=Path(r["post_dir"]) if r["post_dir"] else POSTS/f"{int(r['product_no'] or r['id']):02d}_{re.sub(r'[^가-힣A-Za-z0-9_-]','_',r['name'])[:40]}"
        pdir.mkdir(parents=True,exist_ok=True)
        if progress:progress(0,1,"동일상품 상세 이미지 3장 검증")
        images,ep=capture_images_cached(r,pdir,con,progress=(lambda m: progress(0,1,str(m))) if progress else None);vals=images+[None,None,None]
        want=int(cfg.get('image_exact_count',3));complete=len(images)>=want and all(Path(x).exists() for x in images[:want])
        content_ready=bool(r["title"] and r["body"] and r["tags"])
        exact=_evidence_exact_found(ep)
        st=(f'사진보강대기 {len(images)}/{want}' if not exact else ('사진3장완료' if content_ready and complete else ('사진3장검증' if complete else f'사진보강대기 {len(images)}/{want}')))
        if is_wala_product(r) and not exact:st=f"왈라랜드 사진확인대기 {len(images)}/{want}"
        con.execute("""UPDATE products SET image1=?,image2=?,image3=?,image_verified_count=?,image_evidence_json=?,
                       status=?,post_dir=?,updated_at=datetime('now','localtime') WHERE id=?""",
                    (vals[0],vals[1],vals[2],len(images),ep,st,str(pdir),r["id"]))
        con.commit();_sync_post_images(pdir,images)
        if progress:progress(1,1,f"실제 제품 이미지 {len(images)}/3 검증")
        return {"product_id":r["id"],"images":images,"verified_count":len(images),"evidence":ep,
                "skipped":is_wala_product(r),"reason":REVIEW_REASON if is_wala_product(r) else ""}
    finally:con.close()


def _local_product_keyword_recovery(product_name, category="", max_count=12):
    """Offline, product-grounded SEO terms used only when Naver is unavailable.

    These are explicitly recorded as local recovery terms, never represented as
    autocomplete evidence.  They keep one transient Naver response from
    discarding an otherwise complete product draft.
    """
    try:base=naver_keywords.descriptive_query(product_name) or _concise_name(product_name,34)
    except Exception:base=_concise_name(product_name,34)
    profile=_product_profile(product_name,category);family=str(profile.get("family") or "")
    suffixes={
      "food":["먹는법","보관법","영양정보","맛 비교"],
      "apparel":["사이즈 후기","코디 방법","소재 비교","세탁 방법"],
      "digital":["사용법","호환성","성능 비교","설치 방법"],
      "shampoo":["사용법","두피 타입","성분 비교","사용 후기"],
      "cleanser":["사용법","피부 타입","성분 비교","사용 후기"],
      "skincare":["사용 순서","피부 타입","성분 비교","사용 후기"],
      "cleansing_bar":["사용법","피부 타입","거품 후기","보관 방법"],
      "chopsticks":["사용 후기","수량 비교","보관 방법","대나무 재질"],
    }.get(family,["사용법","사용 후기","제품 비교","보관 방법"])
    return [f"{base} {x}".strip() for x in suffixes][:max(1,int(max_count))]


def _content_needs_generation(row,cfg=None):
    """Only new, incomplete or explicitly failed articles enter Stage ②."""
    if is_wala_product(row):return False,"왈라랜드 원고 보존 · 재작성은 착장 페이지에서 실행"
    cfg=cfg or settings();status=str(row["status"] or "")
    title=str(row["title"] or "").strip();body=str(row["body"] or "").strip();tags=str(row["tags"] or "").strip()
    if not (title and body and tags):return True,"신규/원고필드누락"
    tag_count=len([x for x in re.split(r"[,\n]+",tags) if x.strip()])
    if tag_count<max(20,int(cfg.get("seo_min_related_tags",20))):return True,f"관련태그부족:{tag_count}"
    retry_prefixes=("본문생성실패","본문보완필요","SEO보완필요","원고실패","생성실패")
    if status.startswith(retry_prefixes):return True,"이전생성실패"
    try:
        pdir=Path(str(row["post_dir"] or ""));post_path=pdir/"post.json"
        if post_path.is_file():
            post=json.loads(post_path.read_text(encoding="utf-8"));qa=post.get("content_quality_audit")
            if isinstance(qa,dict) and qa.get("ok") is False:return True,"품질검증실패"
    except Exception:
        # DB has complete usable content. A missing/corrupt cache artifact is
        # repaired by the uploader and must not trigger an expensive rewrite.
        pass
    return False,"완료원고보존"


def run_text(context=None,progress=None):
    """Stage ②: generate only title/body/tags.

    v7.63 also keeps a rolling sentence history so consecutive posts do not
    reuse the same human-sounding catchphrases as a hidden template.
    Coupang Sharelink generation is intentionally isolated in the dedicated
    post-image stage so a slow/missing affiliate lookup cannot skip content.
    """
    init_db_fast();cfg=settings();con=db_connect(row_factory=True)
    live_cb=(context or {}).get("_live_progress") if isinstance(context,dict) else None
    cancel_check=(context or {}).get("_cancel_check") if isinstance(context,dict) else None
    def live_emit(event,**kw):
        if not callable(live_cb):return
        try:
            payload={"event":event,"ts":time.time()};payload.update(kw);live_cb(payload)
        except Exception:pass
    all_rows=con.execute("SELECT * FROM products WHERE status NOT LIKE '추천제외:%' AND COALESCE(already_posted,0)=0 ORDER BY product_no,id").fetchall()
    force=bool((context or {}).get("force_regenerate")) if isinstance(context,dict) else False
    pending=[];preserved=[]
    for row in all_rows:
        need,reason=_content_needs_generation(row,cfg)
        if (force and not is_wala_product(row)) or need:pending.append(row)
        else:preserved.append({"id":row["id"],"product_no":row["product_no"],"name":row["name"],"reason":reason})
    rows=pending
    if not rows:
        con.close()
        return {"processed":0,"eligible":0,"preserved_complete":len(preserved),"preserved_rows":preserved,
                "failed":[],"naver_keyword_empty":[],"keyword_recovered":[],"sharelink_pending":[],"fallback_used":[],
                "diagnostic_csv":"","llm_runtime":{},"stage_ok":True,"soft_pending":False,"cancelled":False,
                "message":f"기존 원고 보존 {len(preserved)}건 · 생성 대상 없음"}
    prog=ProgressThrottle(progress);done=0;seo_short=[];failed=[];fallback_used=[];keyword_recovered=[];diagnostics=[]
    history=_load_content_history();div_retry=max(1,int(cfg.get("content_diversity_retry_count",3)))
    ref_profile=reference_blog_style.get_reference_profile(False);ref_hint=reference_blog_style.prompt_hint(ref_profile)
    llm_state=_llm_runtime_health(cfg,force=True);llm_ready=bool(llm_state.get("ready"))
    batch_started=time.monotonic();product_durations=[];cancelled=False
    live_emit("batch_start",total=len(rows),preserved=len(preserved),model=str(llm_state.get("ollama_model") or ""),
              profile=str(cfg.get("ollama_generation_profile") or "balanced"),reason=str(llm_state.get("reason") or ""))
    log("본문 생성 엔진: "+str(llm_state.get("reason") or ("READY" if llm_ready else "FALLBACK")))
    try:
        with StageTimer("원고/SEO 전체",f"products={len(rows)}"):
            for row_index,r in enumerate(rows,1):
                if callable(cancel_check) and cancel_check():
                    cancelled=True
                    break
                product_started=time.monotonic();product_no=int(r['product_no'] or r['id'])
                live_emit("product_start",index=row_index,total=len(rows),done=done,product_no=product_no,name=r['name'],
                          model=str(llm_state.get("ollama_model") or ""))
                prog(done,len(rows),f"[{row_index}/{len(rows)}] 준비: {r['name'][:36]}",force=True)
                pdir=POSTS/f"{int(r['product_no'] or r['id']):02d}_{re.sub(r'[^가-힣A-Za-z0-9_-]','_',r['name'])[:40]}"
                pdir.mkdir(parents=True,exist_ok=True)
                try:
                    keyword_source="naver_autocomplete";keyword_error=""
                    live_emit("phase",phase="네이버 SEO 키워드 확인",phase_pct=8,index=row_index,total=len(rows),product_no=product_no,name=r['name'])
                    prog(done+0.08,len(rows),f"[{row_index}/{len(rows)}] SEO 키워드 확인 · {r['name'][:30]}",force=True)
                    try:subs=naver_keywords.get_subkeywords(r["name"],max_count=int(cfg.get("seo_naver_subkeywords_max",12)))
                    except Exception as e:
                        subs=[];keyword_error=str(e);log("네이버 서브키워드 예외 — 로컬 제품 키워드로 복구: "+str(e))
                    if not subs:
                        subs=_local_product_keyword_recovery(r["name"],r["category"] or "",int(cfg.get("seo_naver_subkeywords_max",12)))
                        keyword_source="local_product_keyword_recovery";keyword_recovered.append(int(r["product_no"] or r["id"]))
                    heading_plan=heading_subkeyword_terms(r["name"],subs,int(cfg.get("seo_heading_subkeyword_target",4)))
                    heading_context=_subkeyword_context_plan(r["name"],subs,int(cfg.get("seo_heading_subkeyword_target",4)))
                    profile=_product_profile(r["name"],r["category"] or "")
                    forbidden=_recent_forbidden_phrases(history,int(cfg.get("content_recent_sentence_prompt_count",48)))
                    recent_titles=_recent_history_values(history,"title",int(cfg.get("content_recent_title_prompt_count",24)))
                    recent_headings=_recent_history_values(history,"headings",int(cfg.get("content_recent_heading_prompt_count",32)))
                    voice=_creative_plan(r["name"],r["category"] or "",history)
                    spec_text=_spec_text(r["name"])
                    try:core_query=naver_keywords.descriptive_query(r["name"]) or _concise_name(r["name"],34)
                    except Exception:core_query=_concise_name(r["name"],34)
                    live_emit("phase",phase="상품별 프롬프트 구성",phase_pct=18,index=row_index,total=len(rows),product_no=product_no,name=r['name'],keywords=len(subs))
                    prog(done+0.18,len(rows),f"[{row_index}/{len(rows)}] AI 입력 준비 · {r['name'][:30]}",force=True)
                    prompt_base=(
                        RULES
                        + "\n\n상품명: " + r["name"]
                        + "\n카테고리: " + (r["category"] or "")
                        + "\n제품 핵심명: " + core_query
                        + "\n상품명에서 확인되는 용량/수량: " + (spec_text or "별도 표기 없음")
                        + "\n제품군 작성 힌트: " + str(profile.get("hint") or "")
                        + "\n제품군 구체어 예시(필요한 것만 자연스럽게 사용): " + json.dumps(profile.get("terms") or [],ensure_ascii=False)
                        + "\n참고 본문 양식 URL: " + str(cfg.get("blog_reference_post_url",REFERENCE_BLOG_URL))
                        + "\n참고 글 구조 분석: " + ref_hint
                        + "\n이번 글 말투 계획: " + voice
                        + "\n네이버 자동완성 원문(없는 단어를 만들지 말 것): " + json.dumps(subs,ensure_ascii=False)
                        + "\n소제목 키워드 계획: " + json.dumps(heading_plan,ensure_ascii=False)
                        + "\n소제목 키워드별 자연스러운 사용 맥락: " + json.dumps(heading_context,ensure_ascii=False)
                        + "\n최근 사용 제목 금지 목록(구조/후킹 문구를 반복하지 말 것): " + json.dumps(recent_titles,ensure_ascii=False)
                        + "\n최근 사용 소제목 금지 목록(표현을 그대로 재사용하지 말 것): " + json.dumps(recent_headings,ensure_ascii=False)
                        + "\n최근 사용 문장 금지 목록(동일하거나 매우 비슷하게 쓰지 말 것): " + json.dumps(forbidden,ensure_ascii=False)
                        + "\n중요: 판매처/다른 품목 키워드를 현재 제품의 기능처럼 억지 연결하지 마세요. "
                          "본문의 절반 이상은 이 제품을 실제 욕실/주방/외출/식사 등에서 쓰는 구체적인 모습이 떠오르는 문장이어야 합니다. "
                          "쇼핑 일반론이나 '옵션/규격/선택 기준' 반복으로 분량을 채우면 실패입니다. "
                          "첫 부분에서 제품을 살펴볼 이유를 분명히 만들고, 장점은 생활 변화와 연결하며, 결론에서는 과장 없이 상품 링크에서 현재 옵션·구성·가격을 확인하고 싶게 만들어 주세요. "
                          "그리고 가장 중요하게, 사람에게 말하듯 자연스러운 존댓말로 써 주세요. 본문을 '~합니다/~됩니다'로 이어가는 설명문으로 만들지 말고 '~해요/~죠/~더라고요/~네요' 같은 대화형 호흡을 섞으세요. "
                          "제품의 실제 포인트에 반응하는 감탄이나 짧은 질문을 2~4곳 자연스럽게 넣되 같은 표현을 반복하지 마세요. AI가 만든 쇼핑 설명문처럼 보이면 실패입니다."
                    )
                    obj=None;divaudit={};qualityaudit={};toneaudit={"ok":True,"source":"not_checked"};last_gen_error="";last_fail_hint="";generation_source=""
                    if llm_ready:
                        for attempt in range(1,div_retry+1):
                            try:
                                live_emit("phase",phase=f"Ollama 원고 생성 {attempt}/{div_retry}",phase_pct=25,index=row_index,total=len(rows),product_no=product_no,name=r['name'],attempt=attempt,max_attempts=div_retry)
                                prog(done+0.25,len(rows),f"[{row_index}/{len(rows)}] Ollama 생성 {attempt}/{div_retry} · {r['name'][:28]}",force=True)
                                prompt=prompt_base
                                if attempt>1:
                                    prompt+=(
                                        "\n\n재작성 지시: 직전 초안이 품질검증에서 탈락했습니다. "
                                        + (last_fail_hint or "반복/추상 표현을 줄이고 제품 자체 이야기를 늘리세요.")
                                        + " 문장 시작과 동사를 바꾸고, 제품명 반복을 줄이고, 감탄 표현도 앞 글과 겹치지 않게 새로 작성하세요. "
                                          "특히 '~합니다/~됩니다'가 이어지는 보고서체를 줄이고, 실제 사람이 대화하듯 '~해요/~죠/~네요/~더라고요' 호흡으로 다시 써 주세요. "
                                          "네이버 키워드는 의미에 맞는 비교/구매 맥락으로만 연결하세요. 제목·소제목·태그도 직전 초안과 다른 표현으로 바꾸고 JSON 전체를 새로 작성하세요."
                                    )
                                def _stream_live(ev):
                                    ev=dict(ev or {});ev.update({"index":row_index,"total":len(rows),"product_no":product_no,"name":r['name'],"max_attempts":div_retry})
                                    if ev.get("event")=="ollama_stream":
                                        chars=int(ev.get("chars") or 0);fraction=min(0.62,0.62*chars/max(2200,int(cfg.get("ollama_live_target_chars",3400))))
                                        prog(done+0.25+fraction,len(rows),f"[{row_index}/{len(rows)}] 생성 중 · {chars:,}자 · {float(ev.get('elapsed') or 0):.0f}초",force=False)
                                    if callable(live_cb):
                                        try:live_cb(ev)
                                        except Exception:pass
                                raw,provider_used,provider_errors=_call_llm_priority(prompt,cfg,llm_state.get("available_providers") or [],live=_stream_live,cancel_check=cancel_check)
                                live_emit("phase",phase="SEO·반복·품질 검사",phase_pct=90,index=row_index,total=len(rows),product_no=product_no,name=r['name'],attempt=attempt)
                                prog(done+0.90,len(rows),f"[{row_index}/{len(rows)}] 품질검사 · {r['name'][:30]}",force=True)
                                candidate=normalize_content_obj(raw,r["name"],r["category"] or "",subs)
                                candidate["creative_plan"]=voice
                                diva=content_diversity_audit(candidate,history)
                                qa=content_quality_audit(candidate,r["name"],r["category"] or "",subs)
                                tone=content_human_tone_audit(candidate) if provider_used=="ollama_local_free" else {"ok":True,"source":provider_used}
                                if diva.get("ok") and qa.get("ok") and tone.get("ok"):
                                    obj=candidate;divaudit=diva;qualityaudit=qa;toneaudit=tone;generation_source=provider_used;break
                                divaudit=diva;qualityaudit=qa;toneaudit=tone
                                reasons=[]
                                if not diva.get("ok"):reasons.append("이전 글/상투 문장 반복: "+json.dumps(diva,ensure_ascii=False)[:450])
                                if not qa.get("ok"):reasons.append("제품 본문 품질: "+" / ".join(qa.get("reasons") or []))
                                if not tone.get("ok"):reasons.append("AI 티/딱딱한 말투: "+" / ".join(tone.get("reasons") or []))
                                last_fail_hint="; ".join(reasons)
                                log(f"본문 품질 재작성 TOP{r['product_no'] or r['id']} {attempt}/{div_retry}: "+last_fail_hint[:900])
                            except Exception as e:
                                last_gen_error=str(e);last_fail_hint="생성/구조 오류: "+str(e);log("LLM 원고 생성 재시도: "+str(e))
                                # Provider failures are isolated per call. OpenAI failure may fall back to Ollama;
                                # only the current draft attempt is retried before safe-writer recovery.
                    if obj is None:
                        fallback_errors=[]
                        best_quality_candidate=None
                        for fv in range(max(4,int(cfg.get("content_safe_fallback_variants",12)))):
                            try:
                                candidate=normalize_content_obj(fallback(r["name"],r["category"] or "",subs,variant=fv),r["name"],r["category"] or "",subs)
                                candidate["creative_plan"]=voice
                                diva=content_diversity_audit(candidate,history)
                                qa=content_quality_audit(candidate,r["name"],r["category"] or "",subs)
                                if diva.get("ok") and qa.get("ok"):
                                    obj=candidate;divaudit=diva;qualityaudit=qa;toneaudit={"ok":True,"source":"safe_fallback_not_ollama"};generation_source="safe_product_family_fallback";fallback_used.append(int(r["product_no"] or r["id"]));break
                                if qa.get("ok") and best_quality_candidate is None:
                                    best_quality_candidate=(candidate,diva,qa,fv)
                                fallback_errors.append("div="+str(diva.get("ok"))+", qa="+"/".join(qa.get("reasons") or []))
                            except Exception as e:
                                fallback_errors.append(str(e))
                        if obj is None and best_quality_candidate is not None:
                            obj,raw_div,qualityaudit,fv=best_quality_candidate
                            divaudit={**raw_div,"ok":True,"original_ok":bool(raw_div.get("ok")),
                                      "recovery_applied":True,"recovery_policy":"QUALITY_PASS_PRODUCT_SPECIFIC_BEST_EFFORT",
                                      "recovery_reason":"제품별 안전원고가 본문 품질을 통과했으나 이전 글 유사도만 초과하여 최선 후보를 사용",
                                      "fallback_variant":fv}
                            toneaudit={"ok":True,"source":"safe_fallback_not_ollama"};generation_source="safe_product_family_diversity_recovery";fallback_used.append(int(r["product_no"] or r["id"]))
                        if obj is None:
                            raise RuntimeError("고품질 본문 생성 실패 — LLM="+str(llm_state.get("reason") or last_gen_error)+" / 안전원고="+" | ".join(fallback_errors[-2:]))

                    obj["reference_layout_slots"]=list(ref_profile.get("image_slots") or ["after_intro","after_section_1","after_section_2"])[:3]
                    # Preserve a previously generated link in the DB, but never
                    # call the Partners API from the content-generation button.
                    # The post body is rebuilt without affiliate blocks; the
                    # dedicated Sharelink stage adds them after image success.
                    existing_sharelink=str(r["sharelink"] or "").strip()
                    post=compose_post(obj,[],sharelink="")
                    post["order"]=int(r["product_no"] or r["id"]);post["naver_subkeywords"]=subs
                    post["keyword_source"]=keyword_source
                    if keyword_error:post["keyword_recovery_error"]=keyword_error
                    post["content_diversity_audit"]=divaudit;post["content_quality_audit"]=qualityaudit;post["human_tone_audit"]=toneaudit;post["voice_plan"]=voice;post["generation_source"]=generation_source
                    audit=seo_token_audit(post.get("title",""),post.get("tags") or [],r["name"])
                    subaudit=content_subkeyword_audit(r["name"],post.get("title",""),obj.get("sections") or [],post.get("tags") or [],subs)
                    post["seo_word_unique_audit"]=audit;post["naver_subkeyword_audit"]=subaudit
                    (pdir/"post.json").write_text(json.dumps(post,ensure_ascii=False,indent=2),encoding="utf-8")
                    ev=naver_keywords.keyword_evidence(r["name"],subs) or {}
                    ev["source"]="Naver autocomplete" if keyword_source=="naver_autocomplete" else "Local product keyword recovery"
                    ev["keyword_source"]=keyword_source
                    if keyword_error:ev["keyword_recovery_error"]=keyword_error
                    ev["word_unique_policy"]="TOKEN_UNIQUE_PRODUCT_TAGS_V7_66"
                    ev["novel_title_subkeywords"]=novel_subkeyword_terms(r["name"],subs,True,12)
                    ev["novel_tag_subkeywords"]=novel_subkeyword_terms(r["name"],subs,False,12)
                    ev["audit"]=audit;ev["naver_subkeyword_audit"]=subaudit;ev["heading_subkeywords"]=heading_plan
                    ev["content_diversity_audit"]=divaudit;ev["content_quality_audit"]=qualityaudit;ev["human_tone_audit"]=toneaudit;ev["voice_plan"]=voice;ev["generation_source"]=generation_source;ev["llm_runtime"]=llm_state;ev["reference_blog_url"]=str(cfg.get("blog_reference_post_url",REFERENCE_BLOG_URL));ev["reference_blog_profile"]=ref_profile
                    ev["coupang_sharelink_stage"]="separate_after_three_verified_images"
                    seop=pdir/"seo_evidence.json";seop.write_text(json.dumps(ev,ensure_ascii=False,indent=2),encoding="utf-8")
                    title_ok=bool(post["title"] and audit.get("ok") and subaudit.get("ok"))
                    diversity_ok=bool(divaudit.get("ok"))
                    quality_ok=bool(qualityaudit.get("ok"))
                    if not subaudit.get("naver_keywords_available"):
                        seo_short.append(int(r["product_no"] or r["id"]));st="SEO보완필요:네이버서브키워드없음"
                    elif not subaudit.get("pipe_ok"):st="SEO보완필요:제목추천｜누락"
                    elif not (subaudit.get("heading_keyword_ok") and subaudit.get("paragraph_keyword_ok")):st="SEO보완필요:소제목서브키워드"
                    elif not subaudit.get("tag_keyword_ok"):st="SEO보완필요:태그서브키워드"
                    elif not diversity_ok:st="본문보완필요:문장반복감지"
                    elif not quality_ok:st="본문보완필요:제품내용품질"
                    else:st="원고완료" if title_ok else "SEO보완필요"
                    con.execute("""UPDATE products SET title=?,body=?,tags=?,sharelink=?,post_dir=?,seo_keywords=?,seo_evidence_json=?,status=?,approved=0,updated_at=datetime('now','localtime') WHERE id=?""",
                                (post["title"],json.dumps(post["blocks"],ensure_ascii=False),",".join(post["tags"]),existing_sharelink,str(pdir),",".join(subs),str(seop),st,r["id"]))
                    con.commit();done+=1
                    product_sec=max(0.01,time.monotonic()-product_started);product_durations.append(product_sec)
                    avg_sec=sum(product_durations)/len(product_durations);remain=max(0,len(rows)-done);eta_sec=avg_sec*remain
                    live_emit("product_done",index=row_index,total=len(rows),done=done,product_no=product_no,name=r['name'],status=st,
                              source=generation_source,elapsed=product_sec,avg_sec=avg_sec,eta_sec=eta_sec)
                    prog(done,len(rows),f"[{done}/{len(rows)}] 완료 · {product_sec:.0f}초 · 남은 예상 {eta_sec/60:.1f}분",force=True)
                    diagnostics.append({"TOP":int(r["product_no"] or r["id"]),"상품명":r["name"],"결과":st,
                                        "키워드출처":keyword_source,"원고엔진":generation_source,"오류":""})
                    if title_ok and diversity_ok and quality_ok:_record_content_history(history,r["name"],obj)
                    if not title_ok or not diversity_ok or not quality_ok:failed.append(r["id"])
                except Exception as e:
                    failed.append(r["id"]);err=str(e);log("원고 생성 실패: "+r["name"]+" / "+err)
                    product_sec=max(0.01,time.monotonic()-product_started)
                    live_emit("product_error",index=row_index,total=len(rows),done=done,product_no=product_no,name=r['name'],elapsed=product_sec,error=err)
                    if "사용자 중지" in err:
                        cancelled=True
                        prog(done,len(rows),"사용자 중지 요청으로 현재 원고 생성을 중단합니다.",force=True)
                        break
                    try:
                        failure={"product_id":r["id"],"product_no":r["product_no"],"name":r["name"],"error":err,
                                 "failed_at":time.strftime("%Y-%m-%d %H:%M:%S"),"policy":"PRESERVE_PREVIOUS_VALID_CONTENT_V7_67"}
                        (pdir/"CONTENT_GENERATION_FAILURE.json").write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding="utf-8")
                        # A failed regeneration must never erase a previously usable draft/link.
                        if r["title"] and r["body"] and r["tags"]:
                            con.execute("UPDATE products SET last_error=?,updated_at=datetime('now','localtime') WHERE id=?",(err[:1800],r["id"]))
                        else:
                            con.execute("""UPDATE products SET status='본문생성실패:품질검증',last_error=?,approved=0,post_dir=?,updated_at=datetime('now','localtime') WHERE id=?""",
                                        (err[:1800],str(pdir),r["id"]))
                        con.commit()
                        diagnostics.append({"TOP":int(r["product_no"] or r["id"]),"상품명":r["name"],"결과":"실패",
                                            "키워드출처":"","원고엔진":"","오류":err})
                    except Exception as db_error:log("본문 실패상태 저장 실패: "+str(db_error))
        msg=f"신규·실패 제목·본문·태그 {done}/{len(rows)}"
        if preserved:msg+=f" · 기존 완료원고 보존 {len(preserved)}건"
        if failed:msg+=f" · SEO/본문 보완 {len(set(failed))}건"
        if seo_short:msg+=f" · 네이버 서브키워드 재조회 {len(seo_short)}건"
        if fallback_used:msg+=f" · LLM 미연결/품질탈락 안전원고 복구 {len(set(fallback_used))}건"
        if keyword_recovered:msg+=f" · 네이버 키워드 장애 로컬복구 {len(set(keyword_recovered))}건"
        if diagnostics:
            OUTPUTS.mkdir(parents=True,exist_ok=True);dp=OUTPUTS/"content_generation_diagnostic.csv"
            with dp.open("w",encoding="utf-8-sig",newline="") as f:
                w=csv.DictWriter(f,fieldnames=["TOP","상품명","결과","키워드출처","원고엔진","오류"]);w.writeheader();w.writerows(diagnostics)
        prog(done if done<len(rows) else len(rows),len(rows),msg,force=True)
        avg_sec=(sum(product_durations)/len(product_durations)) if product_durations else 0.0
        live_emit("batch_cancelled" if cancelled else "batch_done",done=done,total=len(rows),failed=len(set(failed)),elapsed=time.monotonic()-batch_started,avg_sec=avg_sec,message=msg if not cancelled else f"사용자 중지 · 완료 {done}/{len(rows)}")
        soft=bool(failed) or done<len(rows) or cancelled
        return {"processed":done,"eligible":len(rows),"preserved_complete":len(preserved),"preserved_rows":preserved,
                "failed":list(dict.fromkeys(failed)),"naver_keyword_empty":seo_short,"keyword_recovered":list(dict.fromkeys(keyword_recovered)),"sharelink_pending":[],"fallback_used":list(dict.fromkeys(fallback_used)),
                "diagnostic_csv":str(OUTPUTS/"content_generation_diagnostic.csv"),
                "llm_runtime":llm_state,"stage_ok":not soft,"soft_pending":soft,"cancelled":cancelled,"message":msg}
    finally:con.close()

def needs_image_repair(product, want=3):
    """Return True until both files and the v8.04 1+2 composition are proven."""
    ok,_detail=verified_blog_image_set(product,want)
    return not ok


def run_images(context=None,progress=None):
    """Stage ③: after title exists, fetch exactly-matched same-product photos and name them by title."""
    init_db_fast();cfg=settings();con=db_connect(row_factory=True)
    # v7.45 repair must also revisit rows that v7.44 excluded only because its
    # Coupang web path was disabled. Other exclusion reasons stay untouched.
    want=int(cfg.get("image_exact_count",3))
    repair_only=bool((context or {}).get("repair_only")) if isinstance(context,dict) else False
    force_recollect=bool((context or {}).get("force_recollect")) if isinstance(context,dict) else False
    stop_check=(context or {}).get("stop_check") if isinstance(context,dict) else None
    stopped=False
    already_complete=0
    if repair_only:
        rows=con.execute("""SELECT * FROM products
                            WHERE title IS NOT NULL AND body IS NOT NULL AND tags IS NOT NULL
                              AND COALESCE(already_posted,0)=0
                            ORDER BY product_no,id""").fetchall()
        rows=[r for r in rows if needs_image_repair(r,want)]
    else:
        rows=con.execute("""SELECT * FROM products
                            WHERE (status NOT LIKE '추천제외:%' OR status='추천제외:동일상품미검색')
                              AND COALESCE(already_posted,0)=0
                              AND title IS NOT NULL AND body IS NOT NULL AND tags IS NOT NULL
                            ORDER BY product_no,id""").fetchall()
        if not force_recollect:
            all_rows=list(rows)
            rows=[r for r in all_rows if needs_image_repair(r,want)]
            already_complete=len(all_rows)-len(rows)
    prog=ProgressThrottle(progress);done=0;complete=0;short=[];excluded=[];failed=[];diag_rows=[]
    try:
        with StageTimer("동일상품 사진 전체(직링크 저속 크롭)",f"products={len(rows)}"):
            for r in rows:
                if callable(stop_check) and stop_check():
                    stopped=True
                    break
                prog(done,len(rows),f"{'사진보강 API 재탐색' if repair_only else '동일상품 사진 3장'}: {r['name'][:38]}")
                try:
                    pdir=Path(r["post_dir"]) if r["post_dir"] else POSTS/f"{int(r['product_no'] or r['id']):02d}_{re.sub(r'[^가-힣A-Za-z0-9_-]','_',r['name'])[:40]}"
                    pdir.mkdir(parents=True,exist_ok=True)
                    def _image_live(msg):
                        prog(done,len(rows),f"사진 {done+1}/{len(rows)} · {r['name'][:28]} · {msg}",force=True)
                    images,ep=capture_images_cached(r,pdir,con,repair_mode=repair_only,progress=_image_live)
                    vals=images+[None,None,None]
                    exact=_evidence_exact_found(ep)
                    composition={}
                    try:
                        raw_ev=json.loads(Path(ep).read_text(encoding="utf-8")) if ep and Path(ep).exists() else {}
                        composition=raw_ev.get("composition") or {}
                    except Exception:composition={}
                    image_ok=(len(images)>=want and all(Path(x).exists() for x in images[:want]) and
                              bool(composition.get("verified")) and int(composition.get("representative_count") or 0)==1 and
                              int(composition.get("secondary_count") or 0)>=2)
                    fs=_read_image_failure_summary(ep);short_reason=str(fs.get("short") or "")
                    selected_meta=[]
                    try:
                        evobj=json.loads(Path(ep).read_text(encoding="utf-8")) if ep and Path(ep).exists() else {}
                        selected_meta=[x for x in (evobj.get("images") or []) if isinstance(x,dict)][:3]
                    except Exception: selected_meta=[]
                    def _sel(i,key):
                        return str(selected_meta[i].get(key) or "") if i<len(selected_meta) else ""
                    if not exact:
                        st=f"사진보강대기 {len(images)}/{want}"+(f" · {short_reason}" if short_reason else "");short.append(r["id"])
                    elif image_ok:
                        st="사진3장완료";complete+=1
                    else:
                        st=f"사진보강대기 {len(images)}/{want}"+(f" · {short_reason}" if short_reason else "");short.append(r["id"])
                    diag_rows.append({"TOP":int(r["product_no"] or r["id"]),"상품명":r["name"],"사진수":len(images),"완료":bool(image_ok),
                                      "원인코드":fs.get("code") or "","원인":short_reason,
                                      "쿠팡검색":fs.get("coupang_lookup") or "","쿠팡API후보수":fs.get("coupang_rows_seen") or 0,
                                      "쿠팡유사후보":fs.get("coupang_near_candidates") or 0,"쿠팡상세":fs.get("coupang_detail") or "",
                                      "NAVER준비":fs.get("naver_ready") or False,"NAVER검색원본":fs.get("naver_raw_seen") or 0,"NAVER동일제품후보":fs.get("naver_matched") or 0,"NAVER실사용":fs.get("naver_used") or 0,"NAVER오류":" | ".join(fs.get("naver_errors") or []),
                                      "Google시도":fs.get("google_attempted") or False,"Google후보수":fs.get("google_candidates") or 0,"Google통과후보":fs.get("google_accepted") or 0,"Google검증페이지":fs.get("google_validated_pages") or 0,
                                      "토스검색":fs.get("toss_lookup") or "","토스API후보수":fs.get("toss_rows_scanned") or 0,
                                      "토스유사후보":fs.get("toss_near_candidates") or 0,"토스상세":fs.get("toss_detail") or "",
                                      "이미지1출처":_sel(0,"platform")+"/"+(_sel(0,"image_role") or _sel(0,"kind")),"이미지1페이지":_sel(0,"page_url"),
                                      "이미지2출처":_sel(1,"platform")+"/"+(_sel(1,"image_role") or _sel(1,"kind")),"이미지2페이지":_sel(1,"page_url"),
                                      "이미지3출처":_sel(2,"platform")+"/"+(_sel(2,"image_role") or _sel(2,"kind")),"이미지3페이지":_sel(2,"page_url"),
                                      "evidence":str(ep)})
                    con.execute("""UPDATE products SET image1=?,image2=?,image3=?,image_verified_count=?,image_evidence_json=?,status=?,approved=0,updated_at=datetime('now','localtime') WHERE id=?""",
                                (vals[0],vals[1],vals[2],len(images),ep,st,r["id"]))
                    con.commit();_sync_post_images(pdir,images)
                except Exception as e:
                    failed.append(r["id"])
                    if r["id"] not in short:short.append(r["id"])
                    physical=sum(1 for p in (r["image1"],r["image2"],r["image3"]) if p and Path(p).exists())
                    diag_rows.append({"TOP":int(r["product_no"] or r["id"]),"상품명":r["name"],"사진수":physical,"완료":False,
                                      "원인코드":"UNHANDLED_EXCEPTION","원인":str(e),
                                      "쿠팡검색":"","쿠팡API후보수":0,"쿠팡유사후보":0,"쿠팡상세":"",
                                      "Google시도":False,"Google후보수":0,"Google통과후보":0,"Google검증페이지":0,
                                      "토스검색":"","토스API후보수":0,"토스유사후보":0,"토스상세":"",
                                      "이미지1출처":"","이미지1페이지":"","이미지2출처":"","이미지2페이지":"","이미지3출처":"","이미지3페이지":"",
                                      "evidence":str(r["image_evidence_json"] or "")})
                    try:
                        con.execute("UPDATE products SET image_verified_count=?,status=?,approved=0,updated_at=datetime('now','localtime') WHERE id=?",
                                    (physical,f"사진보강오류 {physical}/{want}",r["id"]))
                        con.commit()
                    except Exception as db_error:log("사진 오류 상태 저장 실패: "+str(db_error))
                    log("상품별 사진 수집 실패(다음 상품 계속): "+r["name"]+" / "+str(e))
                finally:
                    done+=1
                    prog(done,len(rows),f"사진 처리 {done}/{len(rows)}",force=True)
        # One diagnostic CSV per run makes the 0/3 reason explicit: no API result,
        # look-alike/option mismatch, Access Denied, download failure, product-not-visible, etc.
        try:
            OUTPUTS.mkdir(parents=True,exist_ok=True)
            dp=OUTPUTS/("image_repair_diagnostic.csv" if repair_only else "image_collect_diagnostic.csv")
            fields=["TOP","상품명","사진수","완료","원인코드","원인","쿠팡검색","쿠팡API후보수","쿠팡유사후보","쿠팡상세","NAVER준비","NAVER검색원본","NAVER동일제품후보","NAVER실사용","NAVER오류","Google시도","Google후보수","Google통과후보","Google검증페이지","토스검색","토스API후보수","토스유사후보","토스상세","이미지1출처","이미지1페이지","이미지2출처","이미지2페이지","이미지3출처","이미지3페이지","evidence"]
            with dp.open("w",encoding="utf-8-sig",newline="") as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(diag_rows)
        except Exception as e:log("이미지 진단 CSV 저장 실패: "+str(e))
        msg=("사진보강 API 재탐색(쿠팡→토스) " if repair_only else "동일상품 사진3장 ")+f"{complete}/{done}"
        if already_complete:msg+=f" · 기존 정상 3/3 보존 {already_complete}건"
        if excluded:msg+=f" · 기존 제외상태 복구대상 {len(excluded)}건"
        if short:msg+=f" · 사진보강 {len(short)}건"
        if failed:msg+=f" · 개별오류 {len(failed)}건(나머지 계속 처리)"
        if stopped:msg+=" · 사용자 중지, 처리한 사진은 보존"
        prog(done,max(1,done),msg,force=True)
        return {"processed":done,"complete":complete,"already_complete":already_complete,"excluded":excluded,"shortages":short,"failed":failed,"stopped":stopped,"stage_ok":not short and not failed and not stopped,"soft_pending":bool(short or failed or stopped),"message":msg}
    finally:con.close()


def run_image_repairs(context=None,progress=None):
    """Fresh repair pass for every physical 3-image shortage, regardless of status."""
    global _TOSS_IMAGE_FALLBACK_CACHE,_TOSS_IMAGE_CATEGORY_CACHE
    _TOSS_IMAGE_FALLBACK_CACHE={"rows":None,"loaded_at":0.0};_TOSS_IMAGE_CATEGORY_CACHE={}
    ctx=dict(context or {}) if isinstance(context,dict) else {}
    ctx["repair_only"]=True
    return run_images(ctx,progress)


def run(context=None,progress=None):
    """Backward-compatible combined runner; GUI v7.40 uses the two stages separately."""
    a=run_text(context,progress)
    b=run_images(context,progress)
    return {"processed":b.get("processed",0),"text":a,"images":b,"stage_ok":bool(a.get("stage_ok")) and bool(b.get("stage_ok")),"soft_pending":bool(a.get("soft_pending") or b.get("soft_pending")),"message":str(a.get("message",""))+" / "+str(b.get("message",""))}
