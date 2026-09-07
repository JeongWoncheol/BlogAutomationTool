(()=>{
  if(window.__NVB_TOSS_PRICE_ANCHOR?.version==='2.0.0') return;

  // v7.33: Sharelink product cards are read exactly as they are drawn:
  //   commission/profit -> product name -> selling price -> badges/review -> link button.
  // The selling price is the anchor.  We first resolve the *local card* that owns
  // the price, then take the contiguous product-name line(s) immediately above it.
  // Spatial matching is only a fallback.  Open shadow roots are scanned too.
  const SELL_RE=/(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원/;
  const BAD_EXACT=/^(?:상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|더보기|다음|이전|무료배송|배송|쿠폰|할인|혜택|적립|광고|리뷰|평점|30일\s*최저가|오늘만\s*특가|판매가|정가|할인가|내일도착|내일출발|베스트판매자|링크\s*발급)$/i;
  const BAD_CONTAINS=/(?:개당\s*)?\d[\d,]*\s*원\s*수익|예상\s*수익|확정\s*수익|수수료|정산|실적|소득세|지방\s*소득세|API\s*키|하나은행|가이드|의견\s*남기기/i;
  const PROMO=/(무료배송|배송비|쿠폰|적립|리뷰|평점|별점|특가|할인율|판매가|정가|할인가|오늘만|30일\s*최저가|내일도착|내일출발|베스트판매자|링크\s*발급|수익)/i;
  const state={version:'2.0.0',scans:0,scrolls:0,last:[],lastScroller:null};

  const norm=s=>String(s??'').replace(/\s+/g,' ').trim();
  const key=s=>norm(s).toLowerCase().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');
  const rectObj=r=>({x:r.x,y:r.y,left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height});
  const priceNum=s=>{if(BAD_CONTAINS.test(norm(s)))return 0;const m=norm(s).match(SELL_RE);if(!m)return 0;const v=parseInt(m[1].replaceAll(',',''));return Number.isFinite(v)&&v>=100&&v<=100000000?v:0;};
  const visibleRect=r=>r&&r.width>1&&r.height>1&&r.bottom>-30&&r.top<innerHeight+30&&r.right>0&&r.left<innerWidth;
  const inProductMain=el=>{try{if(el.closest('aside,nav,[role="navigation"],header'))return false;const r=el.getBoundingClientRect();return r.right>Math.max(220,innerWidth*0.15);}catch(_){return true}};
  const overlap=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left));
  const overlapRatio=(a,b)=>overlap(a,b)/Math.max(1,Math.min(a.width,b.width));

  function cleanNameLine(s){
    s=norm(s)
      .replace(/(?:개당\s*)?\d{1,3}(?:,\d{3})+\s*원(?:\s*수익)?/g,' ')
      .replace(/\d{1,3}\s*%\s*(?:특가|할인)?/g,' ')
      .replace(/\b(?:무료배송|오늘만\s*특가|30일\s*최저가|내일도착|내일출발|베스트판매자|링크\s*발급)\b/g,' ')
      .replace(/\s+/g,' ').trim();
    if(!s||s.length<2||s.length>260||!/[A-Za-z가-힣]/.test(s))return'';
    if(BAD_EXACT.test(s)||BAD_CONTAINS.test(s)||PROMO.test(s))return'';
    if(/^\d+(?:\.\d+)?$/.test(s)||/^\d+\s*위$/.test(s)||/^\d[\d,]*\s*원$/.test(s))return'';
    if(/^★?\s*\d(?:\.\d)?\s*\(?[\d,]*\)?$/.test(s))return'';
    return s;
  }

  function roots(){
    const out=[document],seen=new Set(out);
    for(let i=0;i<out.length;i++){
      let els=[];try{els=[...out[i].querySelectorAll('*')]}catch(_){continue}
      for(const e of els){try{if(e.shadowRoot&&!seen.has(e.shadowRoot)){seen.add(e.shadowRoot);out.push(e.shadowRoot)}}catch(_){}}
    }
    return out;
  }

  function textFragments(){
    const out=[],seen=new Set();
    for(const root of roots()){
      let walker;try{walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT)}catch(_){continue}
      let n,count=0;
      while((n=walker.nextNode())&&count++<25000){
        const text=norm(n.nodeValue);if(!text||text.length>700)continue;
        const el=n.parentElement;if(!el||!inProductMain(el))continue;
        let cs,r;try{cs=getComputedStyle(el);if(cs.display==='none'||cs.visibility==='hidden'||Number(cs.opacity||1)<0.03)continue;const range=document.createRange();range.selectNodeContents(n);r=range.getBoundingClientRect()}catch(_){continue}
        if(!visibleRect(r))continue;
        const sig=`${text}|${Math.round(r.left)}|${Math.round(r.top)}|${Math.round(r.width)}|${Math.round(r.height)}`;
        if(seen.has(sig))continue;seen.add(sig);out.push({text,el,rect:rectObj(r)});
      }
    }
    return out;
  }

  function sellingPriceFragment(f){
    const t=norm(f.text);if(!t||BAD_CONTAINS.test(t))return 0;
    const p=priceNum(t);if(!p)return 0;
    // A real selling price is normally a compact line such as
    // "8,900원" or "8,900원 30일 최저가".  Reject huge card text blocks.
    if(t.length>90)return 0;
    return p;
  }

  function cardLines(card){
    let txt='';try{txt=String(card?.innerText||card?.textContent||'')}catch(_){}
    return txt.split(/\n+/).map(norm).filter(Boolean);
  }

  function lineHasSellingPrice(line,price){
    if(BAD_CONTAINS.test(line))return false;
    const p=priceNum(line);return p===price;
  }

  function cardNameFromLines(card,price){
    const lines=cardLines(card);if(!lines.length)return'';
    let idx=-1;
    for(let i=0;i<lines.length;i++){if(lineHasSellingPrice(lines[i],price)){idx=i;break}}
    if(idx<0)return'';
    const picked=[];
    for(let i=idx-1;i>=0&&picked.length<4;i--){
      const raw=lines[i];
      if(BAD_CONTAINS.test(raw)||/(?:^|\s)\d{1,3}\s*%\s*(?:특가|할인)?(?:$|\s)/i.test(raw)){
        if(picked.length)break; else continue;
      }
      const n=cleanNameLine(raw);
      if(!n){if(picked.length)break;continue;}
      // Stop before unrelated card metadata.  Product names often contain
      // commas, model numbers and option quantities, so those are retained.
      picked.unshift(n);
    }
    let name=norm(picked.join(' '));
    // Keep a wrapped 2-line title, but avoid accidentally gluing a badge to it.
    if(name.length>240)name=norm(picked.slice(-2).join(' '));
    return cleanNameLine(name);
  }

  function findLocalCard(p){
    let best=null,bestScore=-1e9,el=p.el;
    for(let depth=0;el&&depth<14;depth++,el=el.parentElement){
      if(!inProductMain(el))continue;
      let r,t;try{r=el.getBoundingClientRect();t=norm(el.innerText||el.textContent||'')}catch(_){continue}
      if(!visibleRect(r)||r.width<100||r.height<45||r.width>Math.min(620,innerWidth*0.58)||r.height>1100||t.length>3000)continue;
      const lines=cardLines(el),saleLines=lines.filter(x=>priceNum(x)>0&&!BAD_CONTAINS.test(x));
      if(!saleLines.some(x=>lineHasSellingPrice(x,p.price)))continue;
      if(saleLines.length>5)continue;
      const name=cardNameFromLines(el,p.price);if(!name)continue;
      let hasImg=false,hasIssue=false;try{hasImg=!!el.querySelector('img');hasIssue=/링크\s*발급/.test(t)}catch(_){}
      let score=500-depth*7-Math.max(0,r.width-360)*0.3-Math.max(0,r.height-650)*0.15;
      if(hasImg)score+=90;if(hasIssue)score+=110;if(saleLines.length===1)score+=70;
      if(r.width>=140&&r.width<=360)score+=70;
      if(score>bestScore){best={el,rect:rectObj(r),name,score};bestScore=score;}
    }
    return best;
  }

  function spatialNameForPrice(p,all){
    const candidates=[];
    for(const f of all){
      if(f===p||sellingPriceFragment(f)||BAD_CONTAINS.test(f.text))continue;
      const n=cleanNameLine(f.text);if(!n)continue;
      const cr=f.rect,pr=p.rect;if(cr.top>pr.top+12)continue;
      const gap=Math.max(0,pr.top-cr.bottom);if(gap>190)continue;
      const ov=overlapRatio(cr,pr),dx=Math.abs((cr.left+cr.right-pr.left-pr.right)/2);
      if(ov<0.08&&dx>150)continue;
      let score=450-gap*2.8-dx*0.28+Math.min(100,n.length*1.7)+ov*100;
      if(cr.width>=pr.width*1.05)score+=30;if(cr.left<=pr.left+35)score+=20;
      candidates.push({name:n,score,frag:f});
    }
    candidates.sort((a,b)=>b.score-a.score);
    if(!candidates.length)return null;
    const first=candidates[0];
    // Join one directly adjacent line when a product title is split into spans.
    const close=candidates.find((x,i)=>i>0&&Math.abs(x.frag.rect.left-first.frag.rect.left)<45&&Math.abs(first.frag.rect.top-x.frag.rect.bottom)<38);
    const name=close&&close.frag.rect.top<first.frag.rect.top?norm(`${close.name} ${first.name}`):first.name;
    return{name:cleanNameLine(name)||first.name,score:first.score,rect:first.frag.rect};
  }

  function scan(limit=100){
    state.scans++;
    const all=textFragments(),prices=[];
    for(const f of all){const p=sellingPriceFragment(f);if(p)prices.push(Object.assign({},f,{price:p}));}
    const map=new Map(),evidence=[];
    for(const p of prices){
      const local=findLocalCard(p);const spatial=local?null:spatialNameForPrice(p,all);
      const name=local?.name||spatial?.name||'';if(!name)continue;
      const k=key(name);if(!k)continue;
      let url='',image_url='';
      const owner=local?.el||p.el;
      try{const a=owner?.matches?.('a[href]')?owner:owner?.querySelector?.('a[href]');url=a?.href||''}catch(_){}
      try{const im=owner?.querySelector?.('img[src],img[data-src],img[data-original]');image_url=im?.currentSrc||im?.src||im?.getAttribute?.('data-src')||im?.getAttribute?.('data-original')||''}catch(_){}
      const score=Math.round(local?.score||spatial?.score||0);
      const rec={name,price:p.price,text:`${name} ${p.price.toLocaleString()}원`,url,image_url,source:'toss_card_local_v7_33',anchor:{priceText:p.text,priceRect:p.rect,cardRect:local?.rect||null,method:local?'card_local_lines':'spatial_above',score}};
      const old=map.get(k);if(!old||score>Number(old.anchor?.score||0))map.set(k,rec);evidence.push(rec.anchor);
    }
    const cards=[...map.values()].slice(0,Math.max(1,Number(limit||100)));state.last=cards;
    return{cards,diag:{engine:'toss_card_local_multiframe_v7_33',url:location.href,title:document.title||'',fragments:all.length,priceAnchors:prices.length,matched:cards.length,scans:state.scans,scrolls:state.scrolls,evidence:evidence.slice(0,50)}};
  }

  function scrollable(el){
    if(!el||el===document.body||el===document.documentElement)return false;
    try{const cs=getComputedStyle(el);return /(auto|scroll|overlay)/.test((cs.overflowY||'')+' '+(cs.overflow||''))&&el.scrollHeight>el.clientHeight+80&&el.clientHeight>80}catch(_){return false}
  }
  function findScroller(){
    const pf=textFragments().filter(f=>sellingPriceFragment(f));const scores=new Map();
    for(const p of pf){
      let el=p.el;
      for(let d=0;el&&d<14;d++,el=el.parentElement){
        if(!scrollable(el))continue;let r;try{r=el.getBoundingClientRect()}catch(_){break}
        let s=(scores.get(el)||0)+500+Math.min(1200,(el.scrollHeight-el.clientHeight)/3)+Math.min(600,r.width*r.height/1800)+(r.left>180?150:0);
        scores.set(el,s);break;
      }
    }
    if(scores.size)return[...scores.entries()].sort((a,b)=>b[1]-a[1])[0][0];
    let best=null,bestScore=-1;
    for(const root of roots()){
      let els=[];try{els=[...root.querySelectorAll('main,section,div,ul,ol,[role="main"],[role="list"],[role="grid"]')]}catch(_){continue}
      for(const el of els){if(!scrollable(el))continue;let r;try{r=el.getBoundingClientRect()}catch(_){continue};if(!visibleRect(r)||r.right<230)continue;const s=Math.min(1400,(el.scrollHeight-el.clientHeight)/2)+Math.min(800,r.width*r.height/1800)+(r.left>180?120:0);if(s>bestScore){best=el;bestScore=s}}
    }
    return best;
  }

  function advance(round=0){
    const sc=findScroller();
    if(sc){
      const before=Number(sc.scrollTop||0),max=Math.max(0,sc.scrollHeight-sc.clientHeight),delta=Math.max(300,Math.floor(sc.clientHeight*0.78));
      const target=Math.min(max,before+delta);try{sc.scrollTop=target;sc.dispatchEvent(new Event('scroll',{bubbles:true}))}catch(_){}
      const after=Number(sc.scrollTop||0);state.scrolls++;state.lastScroller={type:'element',before,after,max,clientHeight:sc.clientHeight,scrollHeight:sc.scrollHeight,round,url:location.href};return state.lastScroller;
    }
    const se=document.scrollingElement||document.documentElement||document.body;const before=Number(se.scrollTop||window.scrollY||0),max=Math.max(0,se.scrollHeight-se.clientHeight),target=Math.min(max,before+Math.max(420,Math.floor(innerHeight*0.76)));
    try{se.scrollTop=target;window.scrollTo(0,target);se.dispatchEvent(new Event('scroll',{bubbles:true}))}catch(_){}
    const after=Number(se.scrollTop||window.scrollY||0);state.scrolls++;state.lastScroller={type:'window',before,after,max,round,url:location.href};return state.lastScroller;
  }

  function reset(){state.scans=0;state.scrolls=0;state.last=[];state.lastScroller=null;return true}
  window.__NVB_TOSS_PRICE_ANCHOR={version:'2.0.0',scan,advance,reset,diag:()=>({version:state.version,scans:state.scans,scrolls:state.scrolls,lastCount:state.last.length,lastScroller:state.lastScroller})};
})();
