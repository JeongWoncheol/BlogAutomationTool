# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json, os, re, subprocess, tempfile, math
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
PS1=ROOT/'tools'/'windows_ocr.ps1'
PRICE_RE=re.compile(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원')
NOISE_WORDS=(
    '상품 조회','카테고리','검색','전체','홈','링크 관리','베스트 랭킹','실적 대시보드','정산 내역','api 키 발급',
    '내 정보','가이드','의견 남기기','무료배송','배송','쿠폰','할인','혜택','적립','광고','리뷰','평점','30일 최저가',
    '개당','수익','특가','오늘만','필터','초기화','정렬','상품명','판매가','수수료','링크 만들기'
)
CAT_NAMES=('가전/디지털','뷰티','생활용품','식품','주방용품','패션의류잡화','패션잡화','디지털/가전','화장품/미용')

def _norm(s): return re.sub(r'\s+',' ',str(s or '')).strip()
def _key(s): return re.sub(r'[^0-9a-z가-힣]','',_norm(s).lower())[:180]
def _is_noise(s):
    t=_norm(s)
    if len(t)<3 or len(t)>180: return True
    low=t.lower()
    if t in CAT_NAMES: return True
    if any(t==x or low==x.lower() for x in NOISE_WORDS): return True
    if re.fullmatch(r'[\d\W_]+',t): return True
    if not re.search(r'[A-Za-z가-힣]',t): return True
    return False

def windows_ocr(image_path:Path, language='ko-KR', timeout=35):
    if os.name!='nt':
        return {'ok':False,'error':'Windows OCR is only available on Windows','lines':[]}
    cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(PS1),'-ImagePath',str(image_path),'-LanguageTag',language]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        raw=(p.stdout or '').strip().splitlines()
        if not raw: return {'ok':False,'error':(p.stderr or f'PowerShell exit {p.returncode}').strip(),'lines':[]}
        data=json.loads(raw[-1])
        if p.returncode!=0 and data.get('ok') is not True: data.setdefault('error',(p.stderr or f'PowerShell exit {p.returncode}').strip())
        return data
    except Exception as e:
        return {'ok':False,'error':str(e),'lines':[]}

def _line_rect(x):
    return float(x.get('x',0)),float(x.get('y',0)),float(x.get('width',0)),float(x.get('height',0))
def _cx(x):
    a,_,w,_=_line_rect(x);return a+w/2

def parse_visual_products(ocr:dict, image_size:tuple[int,int], limit=50):
    """Pair visible product names with prices using OCR geometry.

    The Toss product lookup page can be a grid or compact list. Price text is
    used as a stable visual anchor. Candidate names are taken from nearby OCR
    lines above/left of the price, independent of DOM/CSS classes.
    """
    W,H=image_size
    lines=[]
    for raw in ocr.get('lines') or []:
        t=_norm(raw.get('text'))
        if not t: continue
        x,y,w,h=_line_rect(raw)
        # Left side navigation and browser-like top chrome are not product rows.
        if x+w < W*0.16 or y < max(70,H*0.055): continue
        lines.append({'text':t,'x':x,'y':y,'width':w,'height':h})
    prices=[]
    for ln in lines:
        m=PRICE_RE.search(ln['text'])
        if not m: continue
        try: price=int(m.group(1).replace(',',''))
        except: continue
        if not (100<=price<=100_000_000): continue
        # Avoid commission-only lines such as "개당 990원 수익" when a real
        # product price is nearby. They remain eligible only if no better anchor.
        commission=('수익' in ln['text'] or '개당' in ln['text'])
        prices.append((ln,price,commission))
    # Prefer real sale-price anchors over commission/profit labels.
    prices.sort(key=lambda z:(z[2], z[0]['y'], z[0]['x']))
    out=[];seen=set()
    for pl,price,commission in prices:
        px=_cx(pl); py=pl['y']
        same=_norm(PRICE_RE.sub(' ',pl['text']))
        cand=[]
        if same and not _is_noise(same): cand.append((same,0.0,pl))
        for ln in lines:
            if ln is pl: continue
            if PRICE_RE.search(ln['text']): continue
            if _is_noise(ln['text']): continue
            cy=ln['y']+ln['height']/2; cx=_cx(ln)
            dy=py-(ln['y']+ln['height'])
            # Name is usually directly above price in a grid, or slightly to the
            # left on a compact row. Keep the window intentionally generous.
            horiz=abs(cx-px)
            rowish=abs(cy-(pl['y']+pl['height']/2))<=55 and ln['x']<pl['x']
            above=(-12<=dy<=175 and horiz<=max(190,pl['width']*4.5))
            if not (above or rowish): continue
            dist=(max(dy,0)*1.0)+(horiz*0.22)+(0 if rowish else 8)
            # Promo labels should not beat a longer actual product name.
            if any(k in ln['text'] for k in ('최저가','특가','할인','수익')): dist+=120
            cand.append((ln['text'],dist,ln))
        if not cand: continue
        cand.sort(key=lambda z:(z[1],-len(z[0])))
        # Join at most two adjacent name lines (common two-line product title).
        name=cand[0][0]; anchor=cand[0][2]
        for t,dist,ln in cand[1:4]:
            if abs(ln['x']-anchor['x'])<120 and abs((ln['y']+ln['height'])-anchor['y'])<55 and len(name+' '+t)<=150:
                name=_norm(t+' '+name) if ln['y']<anchor['y'] else _norm(name+' '+t)
                break
        name=PRICE_RE.sub(' ',name)
        name=re.sub(r'\b\d{1,3}\s*%\s*(?:특가|할인)?\b',' ',name)
        name=_norm(name)
        if _is_noise(name): continue
        k=_key(name)
        if not k or k in seen: continue
        seen.add(k)
        # Approximate card crop. The actual screenshot is retained as evidence;
        # this crop is for human verification and later image matching.
        cx0=(_cx(anchor)+px)/2
        gridish=sum(1 for q,_,_ in prices if abs(q['y']-pl['y'])<45)>=2
        if gridish:
            cw=max(220,min(420,W*0.26)); x0=max(W*0.15,cx0-cw/2); x1=min(W,x0+cw)
            y0=max(0,min(anchor['y'],pl['y'])-220); y1=min(H,pl['y']+pl['height']+70)
        else:
            x0=max(W*0.15,min(anchor['x'],pl['x'])-70); x1=min(W,max(anchor['x']+anchor['width'],pl['x']+pl['width'])+120)
            y0=max(0,min(anchor['y'],pl['y'])-75); y1=min(H,max(anchor['y']+anchor['height'],pl['y']+pl['height'])+65)
        out.append({'name':name,'price':price,'text':f'{name} {price:,}원','url':'','image_url':'',
                    'visual_ocr':True,'commission_price_anchor':commission,
                    'ocr_rect':{'x':round(x0,1),'y':round(y0,1),'width':round(max(1,x1-x0),1),'height':round(max(1,y1-y0),1)}})
        if len(out)>=limit: break
    return out, {'line_count':len(lines),'price_anchor_count':len(prices),'product_count':len(out),'ocr_language':ocr.get('language',''),'ocr_ok':bool(ocr.get('ok')),'ocr_error':ocr.get('error','')}

def crop_evidence(image_path:Path, cards:list[dict], outdir:Path, prefix='card'):
    outdir.mkdir(parents=True,exist_ok=True)
    try: im=Image.open(image_path).convert('RGB')
    except Exception: return cards
    W,H=im.size
    for i,c in enumerate(cards,1):
        r=c.get('ocr_rect') or {};x=max(0,int(r.get('x',0)));y=max(0,int(r.get('y',0)));w=max(1,int(r.get('width',1)));h=max(1,int(r.get('height',1)))
        box=(x,y,min(W,x+w),min(H,y+h))
        if box[2]<=box[0] or box[3]<=box[1]: continue
        p=outdir/f'{prefix}_{i:02d}.jpg'; im.crop(box).save(p,'JPEG',quality=94); c['visual_card_path']=str(p)
    return cards
