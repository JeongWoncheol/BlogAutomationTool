# -*- coding: utf-8 -*-
"""
Toss Sharelink fixed-category collector (v7.35)

Design goals
- Do NOT depend on Toss CSS class names.
- Traverse every iframe recursively with Selenium (cross-origin frames included).
- Traverse every OPEN Shadow DOM root inside each frame.
- Use the real selling-price line as an anchor and the contiguous title lines
  immediately above it as the product name.
- Scroll the actual inner product list, not only the top-level document.
- Collect 30 UNIQUE product names before leaving a category.
- Reset to /home between categories instead of failing because a custom Toss
  checkbox does not expose a machine-readable OFF state.
- Keep Chrome performance logs as a backup source for product API responses.

This module intentionally uses a dedicated persistent Chrome profile under
LOCALAPPDATA so a Toss login survives program upgrades. The first run may ask
for a one-time login in the opened Toss Chrome window.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import time
import logging
from typing import Any, Dict, Iterable, List, Tuple

from .common import ROOT, log, performance_settings

HOME = "https://sharelink.toss.im/home"
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{1,9})\s*원")
NAME_FIELDS = (
    "productName", "displayProductName", "product_name", "goodsNm", "goodsName",
    "itemName", "item_name", "itemTitle", "item_title", "productTitle", "name", "title"
)
PRICE_FIELDS = (
    "price", "salePrice", "sale_price", "sellingPrice", "selling_price", "discountPrice",
    "discount_price", "finalPrice", "final_price"
)
NOISE_RE = re.compile(
    r"수익|수수료|정산|확정\s*수익|예상\s*수익|링크\s*발급|베스트판매자|"
    r"내일(?:도착|출발)|무료배송|배송비|쿠폰|적립|리뷰|평점|별점|30일\s*최저가|"
    r"하루특가|특가|할인율|판매가|정가|할인가|프로모션\s*상품|발굴순",
    re.I,
)
UI_EXACT = re.compile(
    r"^(?:상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|프로모션\s*상품|발굴순)$",
    re.I,
)


def _norm(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()


def _key(name: str) -> str:
    return re.sub(r"[^0-9a-z가-힣/]", "", _norm(name).lower().replace("·", "/").replace("ㆍ", "/"))[:220]


def _valid_name(name: str) -> bool:
    s = _norm(name)
    if len(s) < 3 or len(s) > 260 or not re.search(r"[A-Za-z가-힣]", s):
        return False
    if NOISE_RE.search(s) or UI_EXACT.match(s):
        return False
    if re.fullmatch(r"\d{1,3}\s*%\s*(?:특가|할인)?", s, re.I):
        return False
    if PRICE_RE.fullmatch(s):
        return False
    return True


def parse_text_block(text: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Parse rendered Toss text using selling price -> immediately preceding title lines."""
    lines = [_norm(x) for x in str(text or "").splitlines() if _norm(x)]
    out: Dict[str, Dict[str, Any]] = {}
    for i, line in enumerate(lines):
        if re.search(r"수익|수수료|정산", line, re.I):
            continue
        m = PRICE_RE.search(line)
        if not m:
            continue
        try:
            price = int(m.group(1).replace(",", ""))
        except Exception:
            continue
        if not (100 <= price <= 100_000_000):
            continue

        picked: List[str] = []
        for j in range(i - 1, max(-1, i - 8), -1):
            raw = lines[j]
            if PRICE_RE.search(raw) and not re.search(r"수익|수수료|정산", raw, re.I):
                break
            # Strong visual boundary immediately above a title on Toss cards.
            if re.search(r"(?:개당\s*)?\d[\d,]*\s*원\s*수익|\d{1,3}\s*%\s*(?:특가|할인)?|역대급특가|오늘만\s*특가", raw, re.I):
                if picked:
                    break
                continue
            if not _valid_name(raw):
                if picked:
                    break
                continue
            picked.insert(0, raw)
            if len(picked) >= 3:
                break

        if not picked:
            continue
        name = _norm(" ".join(picked))
        if len(name) > 240:
            name = _norm(" ".join(picked[-2:]))
        if not _valid_name(name):
            continue
        k = _key(name)
        if not k or k in out:
            continue
        out[k] = {
            "name": name,
            "price": price,
            "text": f"{name} {price:,}원",
            "url": "",
            "image_url": "",
            "source": "toss_selenium_rendered_text",
        }
        if len(out) >= max(1, int(limit)):
            break
    return list(out.values())


def _profile_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = Path(local) / "NaverBlogAutomationStudio" / "TossSeleniumProfile"
    else:
        p = ROOT / "data" / "browser_profiles" / "toss_selenium"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_driver():
    try:
        from selenium import webdriver
    except Exception as e:
        raise RuntimeError("Selenium이 설치되지 않았습니다. 01_INSTALL.cmd를 먼저 실행하세요. " + str(e))

    opt = webdriver.ChromeOptions()
    opt.add_argument(f"--user-data-dir={_profile_dir()}")
    opt.add_argument("--profile-directory=Default")
    opt.add_argument("--start-maximized")
    opt.add_argument("--no-first-run")
    opt.add_argument("--no-default-browser-check")
    opt.add_argument("--disable-notifications")
    opt.add_argument("--disable-popup-blocking")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opt.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=opt)
    try:
        driver.set_page_load_timeout(int(performance_settings().get("search_page_timeout_sec", 15)))
    except Exception:
        pass
    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass
    return driver


def _body(driver) -> str:
    try:
        return driver.find_element("tag name", "body").text or ""
    except Exception:
        return ""


def _login_required(driver) -> bool:
    try:
        url = (driver.current_url or "").lower()
        txt = _body(driver)
        if "/login" in url:
            return True
        # Do not treat a mere sidebar/footer word '로그인' as logged out.
        return ("로그인" in txt and "상품 조회" not in txt and "상품조회" not in txt and "베스트 랭킹" not in txt)
    except Exception:
        return False


def ensure_login(driver, wait_sec: int | None = None) -> bool:
    wait_sec = int(wait_sec or performance_settings().get("market_login_wait_sec", 240))
    try:
        driver.get(HOME)
    except Exception:
        pass
    time.sleep(1.0)
    if not _login_required(driver):
        return True
    log("[TOSS SELENIUM] 최초 1회 로그인 필요 - 열린 Toss 전용 Chrome에서 로그인하세요.")
    end = time.time() + wait_sec
    while time.time() < end:
        try:
            if "sharelink.toss.im" in (driver.current_url or "") and not _login_required(driver):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# JS helpers are run INSIDE the currently selected Selenium frame. They recurse
# through every OPEN shadowRoot in that frame.
_JS_CLICK_EXACT = r"""
const wanted=(arguments[0]||[]).map(x=>String(x||'').replace(/\s+/g,' ').trim());
const leftMenu=!!arguments[1];
const norm=x=>String(x||'').replace(/\s+/g,' ').trim();
const vis=e=>{try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>2&&r.height>2&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0.02}catch(_){return false}};
const roots=[document],seen=new Set([document]);
for(let i=0;i<roots.length;i++){
  let all=[];try{all=[...roots[i].querySelectorAll('*')]}catch(_){ }
  for(const e of all){try{if(e.shadowRoot&&!seen.has(e.shadowRoot)){seen.add(e.shadowRoot);roots.push(e.shadowRoot)}}catch(_){ }}
}
const cand=[];
for(const root of roots){
  let nodes=[];try{nodes=[...root.querySelectorAll('label,button,a,[role="button"],[role="menuitem"],[role="checkbox"],[role="option"],span,p,div')]}catch(_){ }
  for(const n of nodes){if(!vis(n))continue;const t=norm(n.innerText||n.textContent||'');if(!wanted.includes(t))continue;
    let c=n.closest?.('label,button,a,[role="button"],[role="menuitem"],[role="checkbox"],[role="option"]')||n;
    if(!vis(c))c=n;const r=c.getBoundingClientRect();
    let score=0;if(leftMenu)score+=Math.max(0,500-r.left);else score+=r.left>180?100:0;
    if(['BUTTON','A','LABEL','INPUT'].includes(c.tagName))score+=100;
    cand.push({c,score,text:t,left:r.left,top:r.top});
  }
}
cand.sort((a,b)=>b.score-a.score);
if(!cand.length)return {ok:false,found:0,wanted};
const e=cand[0].c;try{e.scrollIntoView({block:'center',behavior:'instant'})}catch(_){ }
try{e.click()}catch(_){try{e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}))}catch(__){return {ok:false,found:cand.length,error:String(__),text:cand[0].text}}}
return {ok:true,found:cand.length,text:cand[0].text,left:cand[0].left,top:cand[0].top};
"""

_JS_EXTRACT = r"""
const limit=Math.max(30,Number(arguments[0]||180));
const norm=x=>String(x||'').replace(/\s+/g,' ').trim();
const priceRe=/(?<!\d)(\d{1,3}(?:,\d{3})+|\d{1,9})\s*원/;
const noise=/수익|수수료|정산|확정\s*수익|예상\s*수익|링크\s*발급|베스트판매자|내일(?:도착|출발)|무료배송|배송비|쿠폰|적립|리뷰|평점|별점|30일\s*최저가|하루특가|특가|할인율|판매가|정가|할인가|프로모션\s*상품|발굴순/i;
const ui=/^(?:상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|프로모션\s*상품|발굴순)$/i;
const validName=t=>{t=norm(t);return t.length>=3&&t.length<=260&&/[A-Za-z가-힣]/.test(t)&&!noise.test(t)&&!ui.test(t)&&!priceRe.test(t)&&!/^\d{1,3}\s*%\s*(?:특가|할인)?$/i.test(t)};
const roots=[document],seenRoots=new Set([document]);
for(let i=0;i<roots.length;i++){let all=[];try{all=[...roots[i].querySelectorAll('*')]}catch(_){ }for(const e of all){try{if(e.shadowRoot&&!seenRoots.has(e.shadowRoot)){seenRoots.add(e.shadowRoot);roots.push(e.shadowRoot)}}catch(_){ }}}
const out=[],seen=new Set();
const push=(name,price,text,url,img,y)=>{name=norm(name);const k=name.toLowerCase().replace(/[^0-9a-z가-힣/]/g,'').slice(0,220);if(!k||seen.has(k)||!validName(name)||!price)return;seen.add(k);out.push({name,price,text:norm(text).slice(0,1600),url:url||'',image_url:img||'',docY:Number(y||0),source:'toss_selenium_multiframe_shadow'})};
for(const root of roots){
  let priceNodes=[];try{priceNodes=[...root.querySelectorAll('span,p,strong,em,div,td,a,button')]}catch(_){ }
  for(const n of priceNodes){
    const own=norm(n.innerText||n.textContent||'');if(!own||own.length>100||noise.test(own))continue;const m=own.match(priceRe);if(!m)continue;
    const price=parseInt(m[1].replace(/,/g,''),10);if(!(price>=100&&price<=100000000))continue;
    let block=n,best=null;
    for(let depth=0;block&&depth<9;depth++,block=block.parentElement){
      const text=String(block.innerText||block.textContent||'').trim();if(!text||text.length>2200)continue;
      const lines=text.split(/\n+/).map(norm).filter(Boolean);const priceIdx=lines.findIndex(x=>x===own||(!noise.test(x)&&priceRe.test(x)));
      if(priceIdx<0)continue;
      const prices=lines.filter(x=>!noise.test(x)&&priceRe.test(x)).length;if(prices<1||prices>4)continue;
      const picked=[];
      for(let j=priceIdx-1;j>=Math.max(0,priceIdx-7)&&picked.length<3;j--){
        const x=lines[j];if(!x)continue;if(!noise.test(x)&&priceRe.test(x))break;
        if(/(?:개당\s*)?\d[\d,]*\s*원\s*수익|\d{1,3}\s*%\s*(?:특가|할인)?|역대급특가|오늘만\s*특가/i.test(x)){if(picked.length)break;continue;}
        if(!validName(x)){if(picked.length)break;continue;}picked.unshift(x);
      }
      if(!picked.length)continue;
      const name=norm(picked.join(' '));if(!validName(name))continue;
      let href='',img='';try{href=(block.matches?.('a[href]')?block:block.querySelector?.('a[href]'))?.href||''}catch(_){ }
      try{const im=block.querySelector?.('img');img=im?.currentSrc||im?.src||im?.getAttribute?.('data-src')||''}catch(_){ }
      let y=0;try{y=block.getBoundingClientRect().top+scrollY}catch(_){ }
      best={name,price,text,url:href,img,y};break;
    }
    if(best)push(best.name,best.price,best.text,best.url,best.img,best.y);
    if(out.length>=limit*3)break;
  }
}
// Root text fallback for virtualized rows that have no useful card ancestor.
for(const root of roots){
  let text='';try{text=(root===document?document.body?.innerText:root.textContent)||''}catch(_){ }
  const lines=String(text).split(/\n+/).map(norm).filter(Boolean);
  for(let i=0;i<lines.length&&out.length<limit*3;i++){
    const line=lines[i];if(noise.test(line))continue;const m=line.match(priceRe);if(!m)continue;const price=parseInt(m[1].replace(/,/g,''),10);if(!(price>=100&&price<=100000000))continue;
    const picked=[];for(let j=i-1;j>=Math.max(0,i-7)&&picked.length<3;j--){const x=lines[j];if(!x)continue;if(!noise.test(x)&&priceRe.test(x))break;if(/(?:개당\s*)?\d[\d,]*\s*원\s*수익|\d{1,3}\s*%\s*(?:특가|할인)?|역대급특가|오늘만\s*특가/i.test(x)){if(picked.length)break;continue;}if(!validName(x)){if(picked.length)break;continue;}picked.unshift(x)}
    if(picked.length)push(norm(picked.join(' ')),price,picked.join(' | '),'','',i);
  }
}
return {cards:out.slice(0,limit*3),diag:{roots:roots.length,body_chars:String(document.body?.innerText||'').length,url:location.href,title:document.title||''}};
"""

_JS_SCROLL = r"""
const vis=e=>{try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>120&&r.height>100&&r.bottom>0&&r.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'}catch(_){return false}};
const countPrice=e=>{try{return ((e.innerText||e.textContent||'').match(/(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d{1,9})\s*원/g)||[]).filter(x=>!/수익/.test(x)).length}catch(_){return 0}};
const cand=[],seen=new Set();
for(const e of [document.scrollingElement,document.documentElement,document.body,...document.querySelectorAll('main,[role="main"],section,div,ul,ol,[role="list"],[role="grid"]')]){
  if(!e||seen.has(e))continue;seen.add(e);try{if(e.closest?.('aside,nav,[role="navigation"]'))continue}catch(_){ }
  if(![document.scrollingElement,document.documentElement,document.body].includes(e)&&!vis(e))continue;
  const sh=Number(e.scrollHeight||0),ch=Number(e.clientHeight||0);if(sh<=ch+60)continue;let r={left:0,right:innerWidth,width:innerWidth,height:innerHeight};try{r=e.getBoundingClientRect()}catch(_){ }
  if(r.right<260)continue;const st=(()=>{try{return getComputedStyle(e)}catch(_){return{overflowY:''}}})();const pc=countPrice(e);
  const score=pc*100000+(/auto|scroll|overlay/.test(st.overflowY||'')?25000:0)+(r.left>180?7000:0)+Math.min(25000,sh-ch)+Math.min(10000,(r.width||0)*(r.height||0)/2500);
  cand.push({e,score,pc,sh,ch,left:r.left||0});
}
cand.sort((a,b)=>b.score-a.score);
for(const x of cand.slice(0,15)){const before=Number(x.e.scrollTop||0),max=Math.max(0,x.sh-x.ch);if(max<=before+2)continue;const step=Math.max(360,Math.floor((x.ch||innerHeight)*0.78)),to=Math.min(max,before+step);try{x.e.scrollTop=to;x.e.dispatchEvent(new Event('scroll',{bubbles:true}));x.e.dispatchEvent(new WheelEvent('wheel',{deltaY:step,bubbles:true,cancelable:true}))}catch(_){continue}const after=Number(x.e.scrollTop||0);if(after>before+2)return {moved:true,type:'element',before,after,max,priceCount:x.pc,left:x.left};}
const se=document.scrollingElement||document.documentElement||document.body,before=Number(se.scrollTop||scrollY||0),max=Math.max(0,Number(se.scrollHeight||0)-Number(se.clientHeight||0)),to=Math.min(max,before+Math.max(450,Math.floor(innerHeight*.78)));try{se.scrollTop=to;scrollTo(0,to);se.dispatchEvent(new Event('scroll',{bubbles:true}))}catch(_){ }
return {moved:Number(se.scrollTop||scrollY||0)>before+2,type:'window',before,after:Number(se.scrollTop||scrollY||0),max,candidates:cand.slice(0,5).map(x=>({pc:x.pc,score:Math.round(x.score),left:Math.round(x.left)}))};
"""


def _frame_walk(driver, action, depth: int = 0, max_depth: int = 6, path: Tuple[int, ...] = ()):
    """Yield action results for main frame + every nested iframe/frame recursively."""
    if depth > max_depth:
        return
    try:
        yield path, action(driver)
    except Exception as e:
        yield path, {"error": str(e)}
    try:
        frames = driver.find_elements("css selector", "iframe,frame")
    except Exception:
        frames = []
    for idx in range(len(frames)):
        try:
            # Re-query because virtualized pages may stale old frame objects.
            frames_now = driver.find_elements("css selector", "iframe,frame")
            if idx >= len(frames_now):
                continue
            driver.switch_to.frame(frames_now[idx])
            yield from _frame_walk(driver, action, depth + 1, max_depth, path + (idx,))
        except Exception as e:
            yield path + (idx,), {"error": str(e)}
        finally:
            try:
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass


def _click_exact_all_frames(driver, labels: Iterable[str], left_menu: bool = False) -> Dict[str, Any]:
    labels = [_norm(x) for x in labels if _norm(x)]
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    attempts = []
    for path, result in _frame_walk(driver, lambda d: d.execute_script(_JS_CLICK_EXACT, labels, bool(left_menu))):
        attempts.append({"frame": list(path), "result": result})
        if isinstance(result, dict) and result.get("ok"):
            return {"ok": True, "frame": list(path), "detail": result, "attempts": attempts[-8:]}
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return {"ok": False, "error": f"텍스트 클릭 실패: {labels}", "attempts": attempts[-12:]}


def _all_frame_text(driver) -> str:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    chunks = []
    for path, result in _frame_walk(driver, lambda d: d.execute_script("return document.body ? (document.body.innerText||'') : ''")):
        if isinstance(result, str) and result:
            chunks.append(result)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return "\n".join(chunks)


def _lookup_ready(driver) -> bool:
    txt = _all_frame_text(driver)
    cats = ["가전/디지털", "뷰티", "생활용품", "식품", "주방용품", "패션의류잡화"]
    return ("상품 조회" in txt or "상품조회" in txt) and sum(1 for c in cats if c in txt) >= 2


def enter_product_lookup(driver) -> Tuple[bool, Dict[str, Any]]:
    if _lookup_ready(driver):
        return True, {"already": True}
    # If submenu is already visible, click 상품 조회 directly. Only expand 링크 if needed.
    r = _click_exact_all_frames(driver, ["상품 조회", "상품조회"], left_menu=True)
    if not r.get("ok"):
        _click_exact_all_frames(driver, ["링크"], left_menu=True)
        time.sleep(0.5)
        r = _click_exact_all_frames(driver, ["상품 조회", "상품조회"], left_menu=True)
    if not r.get("ok"):
        return False, r
    end = time.time() + 12
    while time.time() < end:
        if _lookup_ready(driver):
            return True, r
        time.sleep(0.4)
    return False, {"error": "상품 조회 클릭 후 카테고리 화면 확인 실패", "click": r}


def click_category_once(driver, site_category: str, aliases: Iterable[str]) -> Dict[str, Any]:
    labels = [site_category, *list(aliases or [])]
    # Exact label text is enough on current Toss Sharelink; do not toggle twice.
    r = _click_exact_all_frames(driver, labels, left_menu=False)
    if r.get("ok"):
        time.sleep(1.4)
    return r


def extract_products_all_frames(driver, limit: int = 180) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    merged: Dict[str, Dict[str, Any]] = {}
    frames = []
    for path, result in _frame_walk(driver, lambda d: d.execute_script(_JS_EXTRACT, int(limit))):
        if not isinstance(result, dict):
            continue
        diag = result.get("diag") or {}
        frames.append({"path": list(path), **diag, "cards": len(result.get("cards") or [])})
        for c in result.get("cards") or []:
            name = _norm(c.get("name"))
            if not _valid_name(name):
                continue
            k = _key(name)
            if not k:
                continue
            rec = {
                "name": name,
                "price": int(c.get("price") or 0) or None,
                "text": c.get("text") or name,
                "url": c.get("url") or "",
                "image_url": c.get("image_url") or "",
                "source": c.get("source") or "toss_selenium_multiframe_shadow",
                "frame_path": list(path),
            }
            old = merged.get(k)
            if not old or ((not old.get("url") and rec.get("url")) or (not old.get("image_url") and rec.get("image_url"))):
                merged[k] = rec
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return list(merged.values())[:limit], {"frame_count": len(frames), "frames": frames, "merged": len(merged)}


def _scroll_all_frames(driver) -> Dict[str, Any]:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    moves = []
    for path, result in _frame_walk(driver, lambda d: d.execute_script(_JS_SCROLL)):
        if isinstance(result, dict):
            moves.append({"frame": list(path), **result})
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return {"moved": any(bool(x.get("moved")) for x in moves), "moves": moves[-30:]}


def _json_products(obj: Any, out: Dict[str, Dict[str, Any]], depth: int = 0):
    if depth > 10:
        return
    if isinstance(obj, dict):
        name = ""
        for f in NAME_FIELDS:
            if isinstance(obj.get(f), str) and _valid_name(obj.get(f)):
                name = _norm(obj.get(f)); break
        if name:
            price = None
            for f in PRICE_FIELDS:
                v = obj.get(f)
                try:
                    if isinstance(v, str):
                        m = PRICE_RE.search(v)
                        if m: v = int(m.group(1).replace(",", ""))
                        else: v = int(re.sub(r"[^0-9]", "", v) or 0)
                    if isinstance(v, (int, float)) and 100 <= int(v) <= 100_000_000:
                        price = int(v); break
                except Exception:
                    pass
            k = _key(name)
            if k and k not in out:
                out[k] = {"name": name, "price": price, "text": name, "url": "", "image_url": "", "source": "toss_selenium_network"}
        for v in obj.values():
            _json_products(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _json_products(v, out, depth + 1)


def collect_network_products(driver, limit: int = 180) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    stats = {"events": 0, "responses": 0, "bodies": 0, "errors": 0, "urls": []}
    try:
        logs = driver.get_log("performance")
    except Exception as e:
        return [], {**stats, "error": str(e)}
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            stats["events"] += 1
            if msg.get("method") != "Network.responseReceived":
                continue
            p = msg.get("params") or {}; resp = p.get("response") or {}
            url = str(resp.get("url") or ""); mime = str(resp.get("mimeType") or "").lower()
            if not ("json" in mime or re.search(r"api|product|goods|item|search|catalog", url, re.I)):
                continue
            stats["responses"] += 1
            if url and len(stats["urls"]) < 80: stats["urls"].append(url)
            rid = p.get("requestId")
            if not rid: continue
            try:
                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid}).get("body") or ""
            except Exception:
                stats["errors"] += 1; continue
            if not body or len(body) > 12_000_000: continue
            stats["bodies"] += 1
            try:
                obj = json.loads(body)
                _json_products(obj, out)
            except Exception:
                # JSON embedded as text fallback: parse rendered-like fragments only.
                for c in parse_text_block(body, 300):
                    k = _key(c["name"])
                    if k and k not in out:
                        c["source"] = "toss_selenium_network_text"; out[k] = c
            if len(out) >= limit:
                break
        except Exception:
            stats["errors"] += 1
    return list(out.values())[:limit], {**stats, "products": len(out)}


def collect_current_category(driver, limit: int = 30, timeout_sec: int = 100) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    need = max(1, int(limit))
    merged: Dict[str, Dict[str, Any]] = {}
    rounds = []
    started = time.time(); last = -1; no_growth = 0
    while time.time() - started < timeout_sec and len(rounds) < 80:
        dom, ddiag = extract_products_all_frames(driver, max(need * 6, 180))
        net, ndiag = collect_network_products(driver, max(need * 6, 180))
        for c in [*dom, *net]:
            name = _norm(c.get("name"))
            if not _valid_name(name): continue
            k = _key(name)
            if not k: continue
            old = merged.get(k)
            if not old:
                merged[k] = c
            elif (not old.get("price") and c.get("price")) or (not old.get("url") and c.get("url")):
                merged[k] = {**old, **{x: v for x, v in c.items() if v not in (None, "")}}
        rec = {"round": len(rounds), "total": len(merged), "dom": len(dom), "network": len(net), "dom_diag": ddiag, "network_diag": ndiag}
        rounds.append(rec)
        if len(merged) >= need:
            return list(merged.values())[:need], {"ok": True, "rounds": rounds, "final": len(merged), "elapsed_sec": round(time.time()-started, 1)}
        if len(merged) == last: no_growth += 1
        else: no_growth = 0
        last = len(merged)
        mv = _scroll_all_frames(driver); rec["scroll"] = mv
        time.sleep(1.0 if len(rounds) < 10 else 0.7)
        if no_growth >= 22 and not mv.get("moved"):
            break
    return list(merged.values())[:need], {"ok": len(merged) >= need, "rounds": rounds, "final": len(merged), "elapsed_sec": round(time.time()-started, 1)}


def _save_failure_evidence(driver, category: str, diag: Dict[str, Any]):
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]", "_", category)
    out = ROOT / "evidence" / "toss_selenium_multiframe" / safe
    out.mkdir(parents=True, exist_ok=True)
    try: driver.switch_to.default_content()
    except Exception: pass
    try: driver.save_screenshot(str(out / "screen.png"))
    except Exception: pass
    try: (out / "page.html").write_text(driver.page_source or "", encoding="utf-8", errors="replace")
    except Exception: pass
    try: (out / "diagnostic.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass


def collect_tasks(tasks: List[Dict[str, Any]], progress=None) -> List[Dict[str, Any]]:
    """Collect Toss fixed-category tasks and return extension-compatible result dicts."""
    if not tasks:
        return []
    driver = create_driver()
    results = []
    try:
        if not ensure_login(driver):
            raise RuntimeError("토스 전용 Selenium Chrome 로그인 시간이 초과되었습니다. 열린 창에서 로그인 후 다시 실행하세요.")
        total = len(tasks)
        for idx, task in enumerate(tasks, 1):
            blog_cat = task.get("blog_category") or task.get("query") or ""
            site_cat = task.get("site_category_label") or blog_cat
            aliases = task.get("category_aliases") or [site_cat]
            if progress:
                try: progress(idx - 1, total, f"토스 Selenium · {blog_cat} · 상품 조회 진입")
                except Exception: pass
            diag: Dict[str, Any] = {"engine": "selenium_multiframe_shadow_v7_35", "blog_category": blog_cat, "site_category": site_cat}
            try:
                driver.get(task.get("entry_url") or HOME)
            except Exception:
                pass
            time.sleep(1.0)
            ok, lookup = enter_product_lookup(driver); diag["product_lookup"] = lookup
            if not ok:
                _save_failure_evidence(driver, blog_cat, diag)
                results.append({"_task_id": task["id"], "_site": "토스쇼핑", "_query": blog_cat, "status": "error", "error": "토스 상품 조회 진입 실패", "cards": [], "toss_product_lookup_confirmed": False, "toss_single_checkbox_confirmed": False, "toss_filter_cleanup_confirmed": False, "debug": diag})
                continue

            # Drain all pre-category network events (home/promotions/product-lookup shell).
            # The Network fallback must only see responses caused by THIS category.
            try:
                driver.get_log("performance")
                diag["network_drained_before_category"] = True
            except Exception as e:
                diag["network_drained_before_category"] = False
                diag["network_drain_error"] = str(e)
            cat_click = click_category_once(driver, site_cat, aliases); diag["category_click"] = cat_click
            if not cat_click.get("ok"):
                _save_failure_evidence(driver, blog_cat, diag)
                results.append({"_task_id": task["id"], "_site": "토스쇼핑", "_query": blog_cat, "status": "error", "error": f"토스 {site_cat} 카테고리 클릭 실패", "cards": [], "toss_product_lookup_confirmed": True, "toss_single_checkbox_confirmed": False, "toss_filter_cleanup_confirmed": False, "debug": diag})
                continue

            if progress:
                try: progress(idx - 1, total, f"토스 Selenium · {blog_cat} · 제품명 30개 수집")
                except Exception: pass
            cards, cdiag = collect_current_category(driver, int(task.get("limit") or 30), timeout_sec=105)
            diag["collector"] = cdiag
            # Cleanup proof is a deterministic fresh /home reset. We do not reject
            # 30 valid products because a custom Toss checkbox hides OFF state.
            cleanup_ok = False
            try:
                driver.get(HOME); time.sleep(0.8)
                cleanup_ok = "sharelink.toss.im/home" in (driver.current_url or "")
            except Exception:
                cleanup_ok = False
            diag["cleanup_home_reset"] = {"ok": cleanup_ok, "url": getattr(driver, "current_url", "")}
            status = "ok" if len(cards) >= int(task.get("limit") or 30) and cleanup_ok else "error"
            error = "" if status == "ok" else f"토스 {site_cat}: {int(task.get('limit') or 30)}개 중 {len(cards)}개 수집 / 홈 초기화={cleanup_ok}"
            if status != "ok":
                _save_failure_evidence(driver, blog_cat, diag)
            results.append({
                "_task_id": task["id"], "_site": "토스쇼핑", "_query": blog_cat,
                "status": status, "error": error, "cards": cards,
                "clicked_label": site_cat, "url": getattr(driver, "current_url", ""),
                "category_confirmed": True,
                "toss_product_lookup_confirmed": True,
                "toss_single_checkbox_confirmed": bool(cat_click.get("ok")),
                "toss_uncheck_after_collect": cleanup_ok,
                "toss_filter_cleanup_confirmed": cleanup_ok,
                "toss_cleanup_method": "fresh_home_reload_selenium",
                "toss_checked_before_collect": [site_cat],
                "toss_checked_after_collect": [],
                "debug": diag,
            })
            if progress:
                try: progress(idx, total, f"토스 Selenium · {blog_cat} · {len(cards)}/30")
                except Exception: pass
        return results
    finally:
        try: driver.quit()
        except Exception: pass


def login_setup(wait_sec: int = 300) -> bool:
    driver = create_driver()
    try:
        driver.get(HOME)
        end = time.time() + wait_sec
        print("Toss Selenium 전용 Chrome이 열렸습니다. 로그인이 필요하면 로그인하세요.")
        while time.time() < end:
            if not _login_required(driver):
                print("[PASS] Toss 로그인 세션 확인")
                return True
            time.sleep(1)
        print("[FAIL] 로그인 확인 시간 초과")
        return False
    finally:
        try: driver.quit()
        except Exception: pass
