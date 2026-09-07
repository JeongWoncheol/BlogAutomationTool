# -*- coding: utf-8 -*-
"""Read a user-supplied public Naver Blog post only to infer layout characteristics.

The fetched text is NOT reused as article copy. We keep structural signals such as
paragraph count, line-length tendency, heart headings, and image positions so the
automation can follow the user's reference layout without cloning its wording.
"""
from pathlib import Path
import urllib.request, urllib.parse, re, json, time, html
from .common import DATA, settings, log

CACHE=DATA/"reference_blog_style_cache.json"
DEFAULT_URL="https://blog.naver.com/jwonsbs/224392560087"


def _fetch(url,timeout=15):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"ko-KR,ko;q=0.9,en;q=0.6",
        "Referer":"https://blog.naver.com/"
    })
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read(4*1024*1024).decode("utf-8","ignore")


def _postview_url(url):
    m=re.search(r"blog\.naver\.com/([^/?#]+)/([0-9]{6,})",str(url or ""))
    if not m:return str(url or "")
    blog_id,log_no=m.group(1),m.group(2)
    return "https://blog.naver.com/PostView.naver?"+urllib.parse.urlencode({
        "blogId":blog_id,"logNo":log_no,"redirect":"Dlog","widgetTypeCall":"true","directAccess":"false"
    })


def _strip_tags(fragment):
    fragment=re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>"," ",fragment)
    fragment=re.sub(r"(?i)<br\s*/?>","\n",fragment)
    fragment=re.sub(r"(?i)</p\s*>","\n",fragment)
    fragment=re.sub(r"(?s)<[^>]+>"," ",fragment)
    return re.sub(r"[ \t\r\f\v]+"," ",html.unescape(fragment))


def analyze_html(raw,url=""):
    # SmartEditor ONE posts commonly expose these classes in published HTML.
    para_matches=list(re.finditer(r'(?is)<p[^>]*class=["\'][^"\']*se-text-paragraph[^"\']*["\'][^>]*>(.*?)</p>',raw))
    paras=[];events=[]
    for m in para_matches:
        t=re.sub(r"\s+"," ",_strip_tags(m.group(1))).strip()
        if not t:continue
        paras.append(t);events.append((m.start(),"heading" if t.lstrip().startswith(("💙","🤍","💛","❤️")) else "paragraph",t))
    # Prefer SmartEditor content images for ordering; generic img count is only a fallback statistic.
    image_matches=list(re.finditer(r'(?is)<img[^>]*(?:class=["\'][^"\']*se-image-resource|data-lazy-src=|data-src=)[^>]*>',raw))
    for m in image_matches:events.append((m.start(),"image",""))
    if not paras:
        seen=set()
        for m in re.finditer(r'(?is)<(?:p|div|span)[^>]*>(.*?)</(?:p|div|span)>',raw):
            t=re.sub(r"\s+"," ",_strip_tags(m.group(1))).strip()
            if len(t)<8 or len(t)>220:continue
            k=re.sub(r"\s+","",t)
            if k in seen:continue
            seen.add(k);paras.append(t)
            if len(paras)>=80:break
    headings=[p for p in paras if p.lstrip().startswith(("💙","🤍","💛","❤️"))]
    img_count=len(re.findall(r'(?is)<img\b',raw))
    lengths=[len(p) for p in paras if 5<=len(p)<=250]
    avg=round(sum(lengths)/len(lengths),1) if lengths else 0
    events.sort(key=lambda x:x[0]);heading_no=0;slots=[]
    for _,typ,_text in events:
        if typ=="heading":heading_no+=1
        elif typ=="image":
            slot="after_intro" if heading_no<=0 else f"after_section_{min(heading_no,4)}"
            if slot not in slots:slots.append(slot)
            if len(slots)>=3:break
    if len(slots)<3:slots=["after_intro","after_section_1","after_section_2"]
    return {
        "source_url":url,
        "paragraph_count":len(paras),
        "heart_heading_count":len(headings),
        "heart_headings_present":bool(headings),
        "image_tag_count":img_count,
        "image_slots":slots[:3],
        "avg_paragraph_chars":avg,
        "short_paragraph_ratio":round(sum(1 for x in lengths if x<=55)/max(1,len(lengths)),3),
        "observed_at":time.strftime("%Y-%m-%d %H:%M:%S"),
        "policy":"STRUCTURE_ONLY_NO_COPY"
    }


def _load_cache():
    try:
        obj=json.loads(CACHE.read_text(encoding="utf-8"));return obj if isinstance(obj,dict) else {}
    except Exception:return {}


def get_reference_profile(force=False):
    cfg=settings();url=str(cfg.get("blog_reference_post_url") or DEFAULT_URL).strip()
    ttl=float(cfg.get("blog_reference_style_cache_hours",24))*3600
    cache=_load_cache();rec=cache.get(url) if isinstance(cache.get(url),dict) else None
    if rec and not force and time.time()-float(rec.get("ts",0))<=ttl:
        return dict(rec.get("profile") or {})
    try:
        raw=_fetch(_postview_url(url),timeout=float(cfg.get("blog_reference_fetch_timeout_sec",15)))
        profile=analyze_html(raw,url)
        cache[url]={"ts":time.time(),"profile":profile}
        CACHE.parent.mkdir(parents=True,exist_ok=True)
        CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")
        return profile
    except Exception as e:
        log("참고 블로그 양식 자동분석 실패(기본 양식 사용): "+str(e))
        return {
            "source_url":url,"paragraph_count":0,"heart_heading_count":4,"heart_headings_present":True,
            "image_tag_count":3,"image_slots":["after_intro","after_section_1","after_section_2"],"avg_paragraph_chars":0,"short_paragraph_ratio":1.0,
            "policy":"REFERENCE_FALLBACK_MOBILE_V7_63","fetch_error":str(e)[:300]
        }


def prompt_hint(profile=None):
    p=profile or get_reference_profile(False)
    return (
        "참고 글의 문장을 복사하지 말고 구조만 따른다. "
        f"하트 소제목={int(p.get('heart_heading_count') or 4)}개, "
        f"이미지 흐름≈{max(3,int(p.get('image_tag_count') or 3))}장, "
        f"이미지 배치={p.get('image_slots') or ['after_intro','after_section_1','after_section_2']}, "
        f"짧은 문단 비율={p.get('short_paragraph_ratio',1.0)}. "
        "상단 Sharelink 뒤에 짧은 도입, 본문 중간에 제품 이미지가 분산되는 모바일 후기 흐름을 유지한다."
    )
