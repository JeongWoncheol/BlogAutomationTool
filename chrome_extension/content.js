(()=>{
const priceRe=/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/g;
function vis(e){if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>1&&r.height>1&&s.display!=="none"&&s.visibility!=="hidden";}
function txt(e){return (e?.innerText||e?.textContent||"").replace(/\s+/g," ").trim();}
function site(){const h=location.hostname;if(h==="itemscout.io"||h.endsWith(".itemscout.io"))return"아이템스카우트";if(h==="datalab.naver.com")return"네이버데이터랩";if(h.includes("coupang"))return"쿠팡";if(h.includes("naver"))return"네이버쇼핑";if(h==="toss.shopping"||h.endsWith(".toss.shopping")||h.includes("sharelink.toss")||h==="toss.im"||h.endsWith(".toss.im"))return"토스쇼핑";return"";}
function rect(e){const r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height};}
function setNativeValue(el,value){const p=Object.getPrototypeOf(el),d=Object.getOwnPropertyDescriptor(p,"value");if(d?.set)d.set.call(el,value);else el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));}
function perUnit(t){return /(1개당|개당|100g당|10g당|100ml당|10ml당|ml당|g당|kg당|회당|월\s*\d|당\s*\d)/i.test(t);}
function bestPrice(card){
  const nodes=[...card.querySelectorAll("strong,em,span,p,div")].filter(vis),cand=[];
  for(const n of nodes){let t=txt(n);if(!t||t.length>70||perUnit(t))continue;priceRe.lastIndex=0;const m=[...t.matchAll(priceRe)];if(!m.length)continue;
    const st=getComputedStyle(n);if((st.textDecorationLine||"").includes("line-through"))continue;
    const fs=parseFloat(st.fontSize)||0,bold=(parseInt(st.fontWeight)||0)>=600?3:0,cls=String(n.className||"").toLowerCase();
    for(const x of m){const v=parseInt(x[1].replaceAll(",",""));if(v<100||v>100000000)continue;
      let sc=fs+bold+(cls.includes("price")?5:0)+(t.trim()===x[0].trim()?4:0);cand.push({v,sc});}}
  if(cand.length){cand.sort((a,b)=>b.sc-a.sc||a.v-b.v);const top=cand[0].sc;return Math.min(...cand.filter(x=>x.sc>=top-1.5).map(x=>x.v));}
  const lines=txt(card).split(/\n|  +/).filter(x=>!perUnit(x));let vals=[];for(const l of lines){priceRe.lastIndex=0;for(const m of l.matchAll(priceRe)){const v=parseInt(m[1].replaceAll(",",""));if(v>=100)vals.push(v);}}
  return vals.length?Math.min(...vals):null;
}
function isNoiseLine(s){
  const t=(s||"").replace(/\s+/g," ").trim();
  if(!t) return true;
  if(/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/.test(t)) return true;
  if(/^(판매처|판매자)\s*\d*$/i.test(t)) return true;
  if(/^(쿠폰\s*할인가|쿠폰할인가|할인가|즉시할인|카드할인|회원할인|혜택|적립|광고)$/i.test(t)) return true;
  if(/^(오늘|내일|모레).*(배송|도착|휴무)/i.test(t)) return true;
  if(/^(무료\s*배송|무료배송|로켓배송|판매자로켓|배송비\s*무료|도착\s*예정)$/i.test(t)) return true;
  if(/^(리뷰|후기|평점)\s*[\d,.()개]*$/i.test(t)) return true;
  if(/^\d+\s*%\s*(특가|할인)?$/i.test(t)) return true;
  if(/^[★☆⭐]\s*[\d.(),]+$/.test(t)) return true;
  if(/^(\d+\s*원)?\s*(쿠폰|할인|적립|혜택)/i.test(t)) return true;
  if(/^(쿠팡|네이버|토스)\s*(추천|할인|혜택|쿠폰)?$/i.test(t)) return true;
  if(/^(30일\s*최저가|오늘만\s*특가|링크\s*생성|상품\s*보기|자세히\s*보기|수익\s*보기)$/i.test(t)) return true;
  if(t.length<4) return true;
  return false;
}
function cleanProductName(s){
  let t=(s||"").replace(/\s+/g," ").trim();
  t=t.replace(/^\[(?:쿠폰|농협쿠폰|할인|특가|이벤트|프로모션|즉시할인|카드할인)[^\]]*\]\s*/i,"");
  t=t.replace(/\s+(?:쿠폰할인가|즉시할인|카드할인|무료배송|로켓배송|오늘\s*도착|내일\s*도착|배송\s*휴무).*$/i,"").trim();
  return t;
}
function nameScore(e,t){
  let s=0;
  const tag=(e.tagName||"").toLowerCase();
  const cls=String(e.className||"").toLowerCase();
  const href=(e.getAttribute?.("href")||"").toLowerCase();
  if(tag==="a") s+=8;
  if(href) s+=4;
  if(cls.includes("name")||cls.includes("title")||cls.includes("product")) s+=8;
  if(e.closest("a[href]")) s+=4;
  if(e.querySelector?.("img")) s+=3;
  if(t.length>=12) s+=4;
  if(t.length>=20) s+=2;
  if(t.length>180) s-=10;
  return s;
}
function nameOf(card){
  const siteName=site();
  const selectors = siteName==="쿠팡"
    ? [".name","[class*='name']","[class*='title']","a[href*='/vp/products/']","a[href]"]
    : siteName==="네이버쇼핑"
    ? ["[class*='product_title']","[class*='title']","a[href]"]
    : ["[class*='product'] [class*='name']","[class*='title']","a[href]"];

  const cand=[];
  for(const sel of selectors){
    let els=[];
    try{els=[...card.querySelectorAll(sel)];}catch(e){}
    for(const e of els){
      if(!vis(e)) continue;
      const t=cleanProductName(txt(e));
      if(isNoiseLine(t)) continue;
      if(!/[A-Za-z가-힣]/.test(t)) continue;
      cand.push({t,score:nameScore(e,t)});
    }
  }

  const lines=(card.innerText||"").split("\n")
    .map(x=>cleanProductName(x))
    .filter(x=>!isNoiseLine(x))
    .filter(x=>/[A-Za-z가-힣]/.test(x))
    .filter(x=>!/^(오늘|내일|모레|배송|도착|판매처|쿠폰|할인|혜택|광고)/i.test(x));
  for(const t of lines) cand.push({t,score:(t.length>=12?6:2)+(t.length>=20?2:0)});

  if(!cand.length) return "";
  const map=new Map();
  for(const x of cand){
    const k=x.t.toLowerCase();
    if(!map.has(k) || map.get(k).score<x.score) map.set(k,x);
  }
  const arr=[...map.values()];
  arr.sort((a,b)=>b.score-a.score || b.t.length-a.t.length);
  return arr[0].t;
}
function imgOf(card){let best=null;for(const im of card.querySelectorAll("img")){if(!vis(im))continue;const r=im.getBoundingClientRect(),area=r.width*r.height;if(r.width<50||r.height<50)continue;if(!best||area>best.area)best={el:im,area,src:im.currentSrc||im.src||"",rect:rect(im)};}return best;}
function isCoupangProductHref(href){
 try{const u=new URL(href||"",location.href);return /(^|\.)coupang\.com$/i.test(u.hostname)&&/\/vp\/products\/\d+/i.test(u.pathname)}catch(_e){return false}
}
function hrefOf(card){
 const anchors=[];
 try{if(card.matches?.("a[href]"))anchors.push(card);anchors.push(...card.querySelectorAll("a[href]"));}catch(_e){}
 if(site()==="쿠팡"){
   const direct=anchors.find(a=>isCoupangProductHref(a.href||a.getAttribute?.("href")||""));
   if(direct)return new URL(direct.href||direct.getAttribute("href"),location.href).href;
 }
 return anchors[0]?.href||"";
}
function selectors(){
 if(site()==="쿠팡")return["li.search-product","li[class*='search-product']","article","div[class*='product']"];
 if(site()==="네이버쇼핑")return["div[class*='product_item']","li[class*='basicList_item']","div[class*='basicList_item']","div[class*='product']","article"];
 return["article","li","div[class*='product']","div[class*='item']","div[class*='card']","tr"];
}
function genericCards(limit=20){
 const out=[],seen=new Set();for(const sel of selectors()){for(const e of document.querySelectorAll(sel)){if(!vis(e))continue;const t=txt(e);if(t.length<8||t.length>1800)continue;const p=bestPrice(e);if(!p)continue;const n=nameOf(e);if(!n||isNoiseLine(n))continue;const h=hrefOf(e),im=imgOf(e),key=n+"|"+p;if(seen.has(key))continue;seen.add(key);const rr=rect(e);out.push({name:n,price:p,text:t,url:h,image_url:im?.src||"",rect:rr,imageRect:im?.rect||null,docY:rr.y+window.scrollY});if(out.length>=limit)return out;}}return out;
}
function productNameFromLines(card,rankNo=0){
 const bad=/^(?:전체|일간|주간|찜하기|무료배송|네이버배송|도착보장|설치비|배송비|원가|할인율|별점|리뷰|광고|판매자|판매처|쿠폰|적립|혜택)/i;
 const arr=(card?.innerText||"").split(/\n+/).map(x=>cleanProductName(x)).filter(Boolean).filter(x=>!isNoiseLine(x));
 const cand=[];
 for(let x of arr){
   x=x.replace(/^\d{1,3}\s*위\s*/,"").trim();
   if(!x||bad.test(x)||/^\d{1,3}\s*위$/.test(x)||!/[A-Za-z가-힣]/.test(x))continue;
   if(x.length>220)continue;
   let sc=Math.min(x.length,90);
   if(x.length>=12)sc+=25;if(x.length>=24)sc+=15;
   if(/\d+(?:ml|l|g|kg|mg|개|매|팩|세트|인치)/i.test(x))sc+=8;
   cand.push({x,sc});
 }
 cand.sort((a,b)=>b.sc-a.sc||b.x.length-a.x.length);
 return cand[0]?.x||nameOf(card)||"";
}
function productHrefFromCard(card,name=""){
 const as=[];
 try{if(card.matches?.("a[href]"))as.push(card);as.push(...card.querySelectorAll("a[href]"));}catch(_e){}
 const scoreA=(a)=>{
   const h=(a.href||"").toLowerCase(),t=txt(a);let sc=0;
   if(site()==="쿠팡"&&isCoupangProductHref(h))sc+=300;
   if(/\/products?\/|\/product\/|\/goods\//.test(h))sc+=30;
   if(/smartstore\.naver\.com|brand\.naver\.com|shopping\.naver\.com/.test(h))sc+=12;
   if(a.querySelector("img"))sc+=8;
   if(name&&t&&normalizeLabel(name).includes(normalizeLabel(t).slice(0,18)))sc+=5;
   return sc;
 };
 as.sort((a,b)=>scoreA(b)-scoreA(a));
 const best=as[0]?.href||hrefOf(card)||"";
 if(site()!=="쿠팡"||isCoupangProductHref(best))return best;
 let parent=card;
 for(let depth=0;parent&&depth<4;depth++,parent=parent.parentElement){
   let links=[];try{links=[...parent.querySelectorAll("a[href*='/vp/products/']")]}catch(_e){}
   const exact=links.find(a=>isCoupangProductHref(a.href));if(exact)return exact.href;
 }
 return "";
}
function rankSeedNodes(){
 const nodes=[...document.querySelectorAll("span,strong,b,em,p,div")].filter(vis),out=[];
 for(const e of nodes){const t=txt(e).trim();const m=t.match(/^(\d{1,3})\s*위$/);if(m)out.push({e,rank:Number(m[1])});}
 return out;
}
function ancestorRankCard(seed){
 let e=seed?.parentElement||null,best=null;
 for(let i=0;e&&i<9;i++,e=e.parentElement){
   const t=txt(e);if(!t||t.length>2400)continue;
   const p=bestPrice(e);if(!p)continue;
   const hasVisual=!!e.querySelector("img")||!!e.querySelector("a[href]");
   if(!hasVisual)continue;
   best=e;break;
 }
 return best;
}
function naverRankCards(limit=50){
 const out=[],seen=new Set();
 for(const {e,rank} of rankSeedNodes().sort((a,b)=>a.rank-b.rank)){
   if(rank<1||rank>200)continue;
   const card=ancestorRankCard(e);if(!card)continue;
   const p=bestPrice(card),n=productNameFromLines(card,rank);if(!p||!n||isNoiseLine(n))continue;
   const im=imgOf(card),rr=rect(card),h=productHrefFromCard(card,n),key=rank+"|"+n+"|"+p;
   if(seen.has(key))continue;seen.add(key);
   out.push({name:n,price:p,text:txt(card),url:h,image_url:im?.src||"",rect:rr,imageRect:im?.rect||null,docY:rr.y+window.scrollY,rank_hint:rank});
   if(out.length>=limit)break;
 }
 return out;
}

function naverRankBoundaryCards(limit=50){
 // Current Naver BEST changes CSS class hashes often. Build cards from rank labels
 // and the next rank boundary so extraction is independent of those class names.
 const seeds=rankSeedNodes().filter(x=>x.rank>=1&&x.rank<=200).sort((a,b)=>a.rank-b.rank);
 const out=[],seen=new Set();
 for(const {e,rank} of seeds){
   let root=e;
   // climb until there is a price + image/link, but avoid giant page containers.
   for(let i=0;i<12&&root;i++,root=root.parentElement){
     const t=txt(root); if(!t||t.length>3200)continue;
     if(!bestPrice(root))continue;
     const imgs=[...root.querySelectorAll('img')].filter(vis);
     const links=[...root.querySelectorAll('a[href]')].filter(vis);
     if(!imgs.length&&!links.length)continue;
     // Reject an ancestor containing multiple distinct rank labels; that is a list wrapper.
     const ranks=[...root.querySelectorAll('span,strong,b,em,p,div')].filter(vis)
       .map(x=>txt(x).trim()).filter(x=>/^\d{1,3}\s*위$/.test(x));
     if(new Set(ranks).size>1)continue;
     const p=bestPrice(root), n=productNameFromLines(root,rank);
     if(!p||!n||isNoiseLine(n))continue;
     const im=imgOf(root),rr=rect(root),h=productHrefFromCard(root,n),key=rank+'|'+n+'|'+p;
     if(seen.has(key))break; seen.add(key);
     out.push({name:n,price:p,text:txt(root),url:h,image_url:im?.src||'',rect:rr,imageRect:im?.rect||null,docY:rr.y+window.scrollY,rank_hint:rank});
     break;
   }
   if(out.length>=limit)break;
 }
 return out;
}

function naverLooseCards(limit=50){
 const out=[],seen=new Set();
 const anchors=[...document.querySelectorAll("a[href]")].filter(a=>vis(a)&&/(smartstore\.naver\.com|brand\.naver\.com|shopping\.naver\.com)/i.test(a.href||""));
 for(const a of anchors){
   let e=a;let card=null;
   for(let i=0;i<8&&e;i++,e=e.parentElement){const t=txt(e);if(t.length<20||t.length>1800)continue;if(bestPrice(e)&&e.querySelector("img")){card=e;break;}}
   if(!card)continue;const p=bestPrice(card),n=productNameFromLines(card);if(!p||!n)continue;
   const key=n.toLowerCase()+"|"+p;if(seen.has(key))continue;seen.add(key);
   const im=imgOf(card),rr=rect(card);out.push({name:n,price:p,text:txt(card),url:productHrefFromCard(card,n),image_url:im?.src||"",rect:rr,imageRect:im?.rect||null,docY:rr.y+window.scrollY});
   if(out.length>=limit)break;
 }
 return out;
}
function directText(e){
  if(!e)return'';let out='';
  try{for(const n of e.childNodes||[])if(n.nodeType===Node.TEXT_NODE)out+=' '+(n.nodeValue||'');}catch(_e){}
  return cleanProductName(out.replace(/\s+/g,' ').trim());
}
function tossProductNameFromDom(card){
  if(!card)return'';const cand=[];
  const nodes=[card,...card.querySelectorAll('a,span,p,div,strong,b,h3,h4')];
  for(const e of nodes){
    if(!vis(e))continue;
    let t=directText(e);if(!t&&e.children.length===0)t=cleanProductName(txt(e));
    if(!t||t.length<4||t.length>220||isNoiseLine(t)||!/[A-Za-z가-힣]/.test(t))continue;
    if(/\d{1,3}(?:,\d{3})+\s*원/.test(t)||/^(카테고리|상품 조회|검색|링크 생성|수익)/.test(t))continue;
    let sc=Math.min(t.length,100);if(t.length>=10)sc+=30;if(t.length>=20)sc+=15;
    if(/\d+(?:ml|l|g|kg|mg|개|매|팩|세트|인치)/i.test(t))sc+=8;
    if(e.tagName==='A')sc+=10;
    const r=e.getBoundingClientRect();if(r.width>100&&r.height<120)sc+=5;
    cand.push({t,sc});
  }
  cand.sort((a,b)=>b.sc-a.sc||b.t.length-a.t.length);return cand[0]?.t||productNameFromLines(card)||nameOf(card)||'';
}
function tossCardFromSeed(seed){
  if(!seed)return null;
  let e=seed,best=null,bestScore=-1;
  for(let i=0;e&&i<11;i++,e=e.parentElement){
    if(!vis(e))continue;
    const all=txt(e);if(!all||all.length<10||all.length>2600)continue;
    const r=e.getBoundingClientRect();
    if(r.width<80||r.height<14||r.height>1200)continue;
    const p=bestPrice(e);if(!p)continue;
    const imgs=[...e.querySelectorAll('img')].filter(vis).filter(im=>{const rr=im.getBoundingClientRect();return rr.width>=45&&rr.height>=45;});
    const links=[...e.querySelectorAll('a[href]')].filter(vis);
    const buttons=[...e.querySelectorAll('button,[role="button"]')].filter(vis);
    const priceNodes=[...e.querySelectorAll('strong,em,span,p,div')].filter(vis).filter(n=>{const t=txt(n);return t&&t.length<=80&&!perUnit(t)&&/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/.test(t);});
    // A product row may use completely hashed React classes.  Geometry and
    // content are much more stable than class names: one/few prices, a visual
    // or link, and a bounded text block are enough to form a candidate card.
    // Real Sharelink Product Lookup can render a row as plain div/text with no
    // anchor/button and with the image loaded in a sibling wrapper. Do not reject
    // a candidate only because it has no obvious interactive/visual descendant.
    if(priceNodes.length>8||imgs.length>8)continue;
    const n=tossProductNameFromDom(e);if(!n||isNoiseLine(n))continue;
    let sc=0;
    if(imgs.length)sc+=35;
    if(links.length)sc+=25;
    if(buttons.length)sc+=8;
    if(priceNodes.length>=1&&priceNodes.length<=3)sc+=32;
    if(!imgs.length&&!links.length&&priceNodes.length>=1&&all.length<=650)sc+=28;
    if(r.height>=16&&r.height<=520)sc+=18;
    if(all.length<=900)sc+=14;
    if(i<=5)sc+=10;
    // Prefer the smallest good ancestor around the seed, not a whole list wrapper.
    sc-=Math.max(0,i-4)*3;
    if(sc>bestScore){bestScore=sc;best=e;}
    if(sc>=112)break;
  }
  return best;
}
function tossCardRecord(card){
  if(!card)return null;
  const p=bestPrice(card),name=tossProductNameFromDom(card);if(!p||!name||isNoiseLine(name))return null;
  const im=imgOf(card),rr=rect(card);
  return{name,price:p,text:txt(card),url:productHrefFromCard(card,name),image_url:im?.src||'',rect:rr,imageRect:im?.rect||null,docY:rr.y+window.scrollY};
}
function tossPriceBoundaryCards(limit=80){
 const out=[],seen=new Set();
 const nodes=[...document.querySelectorAll('strong,em,span,p,div')].filter(vis);
 for(const n of nodes){
   const t=txt(n); if(!t||t.length>100||!/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/.test(t)||perUnit(t))continue;
   const card=tossCardFromSeed(n);if(!card)continue;
   const rec=tossCardRecord(card);if(!rec)continue;
   const key=normalizeLabel(rec.name)+'|'+rec.price;if(seen.has(key))continue;seen.add(key);out.push(rec);
   if(out.length>=limit)break;
 }
 return out;
}
function tossImageBoundaryCards(limit=80){
 const out=[],seen=new Set();
 const imgs=[...document.querySelectorAll('img')].filter(vis).filter(im=>{const r=im.getBoundingClientRect();return r.width>=55&&r.height>=55;});
 for(const im of imgs){
   const card=tossCardFromSeed(im);if(!card)continue;
   const rec=tossCardRecord(card);if(!rec)continue;
   const key=normalizeLabel(rec.name)+'|'+rec.price;if(seen.has(key))continue;seen.add(key);out.push(rec);
   if(out.length>=limit)break;
 }
 return out;
}
function tossAnchorBoundaryCards(limit=80){
 const out=[],seen=new Set();
 const anchors=[...document.querySelectorAll('a[href]')].filter(vis);
 for(const a of anchors){
   const card=tossCardFromSeed(a);if(!card)continue;
   const rec=tossCardRecord(card);if(!rec)continue;
   const key=normalizeLabel(rec.name)+'|'+rec.price;if(seen.has(key))continue;seen.add(key);out.push(rec);
   if(out.length>=limit)break;
 }
 return out;
}
function tossTextBoundaryCards(limit=80){
 const out=[],seen=new Set();
 // Price nodes are the most stable visible signal on the live Product Lookup
 // screen. Build the smallest bounded row that contains the price plus a real
 // product-like text line, even when the React classes are fully hashed.
 const nodes=[...document.querySelectorAll('strong,em,span,p,div,td')].filter(vis);
 for(const n of nodes){
   const own=txt(n);if(!own||own.length>140||!/\d{1,3}(?:,\d{3})+\s*원/.test(own)||perUnit(own))continue;
   let e=n,card=null;
   for(let i=0;e&&i<10;i++,e=e.parentElement){
     if(!vis(e))continue;const all=txt(e);if(!all||all.length<10||all.length>1800)continue;
     const r=e.getBoundingClientRect();if(r.width<80||r.height<14||r.height>900)continue;
     const matches=(all.match(/\d{1,3}(?:,\d{3})+\s*원/g)||[]);if(matches.length>5)continue;
     const nm=tossProductNameFromDom(e);const pr=bestPrice(e);if(!nm||!pr||isNoiseLine(nm))continue;
     card=e;break;
   }
   if(!card)continue;const rec=tossCardRecord(card);if(!rec)continue;
   const key=normalizeLabel(rec.name)+'|'+rec.price;if(seen.has(key))continue;seen.add(key);out.push(rec);
   if(out.length>=limit)break;
 }
 return out;
}
function tossButtonRowCards(limit=80){
 const out=[],seen=new Set();
 const seeds=[...document.querySelectorAll('button,[role="button"],tr,li')].filter(vis).filter(e=>/\d{1,3}(?:,\d{3})+\s*원/.test(txt(e)));
 for(const seed of seeds){
   const card=tossCardFromSeed(seed)||seed;const rec=tossCardRecord(card);if(!rec)continue;
   const key=normalizeLabel(rec.name)+'|'+rec.price;if(seen.has(key))continue;seen.add(key);out.push(rec);if(out.length>=limit)break;
 }
 return out;
}

// v7.25: Toss Product Lookup can render inside open Shadow DOM and compact
// virtual-list wrappers whose class names are fully hashed.  Query all open
// roots, then form records from visible price/name boundaries.  This is the
// first in-page fallback before background.js tries every frame in MAIN world.
function tossOpenRoots(){
 const out=[document],seen=new Set([document]);
 for(let i=0;i<out.length;i++){
   const r=out[i];let nodes=[];try{nodes=[...r.querySelectorAll('*')];}catch(_e){}
   for(const e of nodes){try{if(e.shadowRoot&&!seen.has(e.shadowRoot)){seen.add(e.shadowRoot);out.push(e.shadowRoot);}}catch(_e){}}
 }
 return out;
}
function tossRootElements(selector){
 const out=[];for(const r of tossOpenRoots()){try{for(const e of r.querySelectorAll(selector))out.push(e);}catch(_e){}}
 return out;
}
function tossNameFromCompactText(raw){
 const lines=String(raw||'').split(/\n+/).map(x=>cleanProductName(x)).filter(Boolean);
 const cand=[];
 for(let line of lines){
   line=line.replace(/\d{1,3}(?:,\d{3})+\s*원/g,' ').replace(/\s+/g,' ').trim();
   if(!line||line.length<4||line.length>240||isNoiseLine(line)||!/[A-Za-z가-힣]/.test(line))continue;
   if(/^(상품\s*조회|카테고리|검색|전체|링크|홈|성과|설정|가이드|의견\s*남기기)$/i.test(line))continue;
   let sc=Math.min(line.length,100);if(line.length>=10)sc+=25;if(line.length>=20)sc+=12;
   if(/\d+(?:ml|l|g|kg|mg|개|매|팩|세트|인치)/i.test(line))sc+=8;
   cand.push({line,sc});
 }
 cand.sort((a,b)=>b.sc-a.sc||b.line.length-a.line.length);return cand[0]?.line||'';
}
function tossDeepRootCards(limit=120){
 const out=[],seen=new Set();
 const roots=tossOpenRoots();
 for(const root of roots){
   let nodes=[];try{nodes=[...root.querySelectorAll('strong,em,span,p,div,td,tr,li,a,button')].filter(vis);}catch(_e){}
   for(const n of nodes){
     const own=txt(n);if(!own||own.length>220||!/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/.test(own)||perUnit(own))continue;
     let e=n,card=null;
     for(let i=0;e&&i<11;i++,e=e.parentElement){
       if(!vis(e))continue;const all=txt(e);if(!all||all.length<8||all.length>2200)continue;
       const matches=(all.match(/\d{1,3}(?:,\d{3})+\s*원/g)||[]);if(matches.length>7)continue;
       const p=bestPrice(e);if(!p)continue;
       const name=tossProductNameFromDom(e)||tossNameFromCompactText(all);if(!name||isNoiseLine(name))continue;
       card=e;break;
     }
     if(!card)continue;
     let rec=tossCardRecord(card);
     if(!rec){const p=bestPrice(card),name=tossNameFromCompactText(txt(card));if(p&&name){const rr=rect(card);rec={name,price:p,text:txt(card),url:productHrefFromCard(card,name),image_url:imgOf(card)?.src||'',rect:rr,imageRect:null,docY:rr.y+window.scrollY};}}
     if(!rec)continue;
     const key=normalizeLabel(rec.name)+'|'+rec.price;if(seen.has(key))continue;seen.add(key);out.push(rec);if(out.length>=limit)return out;
   }
 }
 return out;
}
function tossSameOriginFrameCards(limit=120){
 const out=[],seen=new Set();
 for(const f of document.querySelectorAll('iframe')){
   let d=null;try{d=f.contentDocument;}catch(_e){d=null;}if(!d?.body)continue;
   let nodes=[];try{nodes=[...d.querySelectorAll('strong,em,span,p,div,td,tr,li,a,button')];}catch(_e){}
   for(const n of nodes){let r=null;try{r=n.getBoundingClientRect();}catch(_e){continue;}if(!r||r.width<1||r.height<1)continue;
     const t=(n.innerText||n.textContent||'').replace(/\s+/g,' ').trim();if(!t||t.length>240||!/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/.test(t))continue;
     let e=n,all='',price=null,name='';
     for(let i=0;e&&i<9;i++,e=e.parentElement){all=(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim();if(!all||all.length>1800)continue;const m=[...all.matchAll(/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/g)];if(!m.length||m.length>6)continue;price=parseInt(m[0][1].replaceAll(',',''));name=tossNameFromCompactText(e.innerText||e.textContent||'');if(price&&name)break;}
     if(!price||!name)continue;const key=normalizeLabel(name)+'|'+price;if(seen.has(key))continue;seen.add(key);out.push({name,price,text:all,url:'',image_url:'',rect:null,imageRect:null,docY:0});if(out.length>=limit)return out;
   }
 }
 return out;
}
function tossCollectorDiagnostics(){
  const priceVisible=[...document.querySelectorAll('strong,em,span,p,div')].filter(vis).filter(n=>{const t=txt(n);return t&&t.length<=100&&!perUnit(t)&&/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/.test(t);}).length;
  const imageVisible=[...document.querySelectorAll('img')].filter(vis).filter(im=>{const r=im.getBoundingClientRect();return r.width>=55&&r.height>=55;}).length;
  const anchorsVisible=[...document.querySelectorAll('a[href]')].filter(vis).length;
  const iframes=[...document.querySelectorAll('iframe')].filter(vis).map(f=>({src:f.src||'',title:f.title||'',w:Math.round(f.getBoundingClientRect().width),h:Math.round(f.getBoundingClientRect().height)})).slice(0,8);
  const samples=[...document.querySelectorAll('strong,em,span,p,div,td')].filter(vis).map(txt).filter(t=>t&&t.length<140&&/\d{1,3}(?:,\d{3})+\s*원/.test(t)).slice(0,12);
  return{price_visible:priceVisible,image_visible:imageVisible,anchor_visible:anchorsVisible,
    deep_root_cards:tossDeepRootCards(120).length,same_origin_frame_cards:tossSameOriginFrameCards(120).length,open_roots:tossOpenRoots().length,
    price_cards:tossPriceBoundaryCards(120).length,text_cards:tossTextBoundaryCards(120).length,button_rows:tossButtonRowCards(120).length,image_cards:tossImageBoundaryCards(120).length,anchor_cards:tossAnchorBoundaryCards(120).length,generic_cards:genericCards(120).length,iframes,price_samples:samples,txn:tossTxnGet()};
}
function cards(limit=20){
 if(site()==="토스쇼핑"){
   const want=Math.max(limit,120);
   const sources=[tossDeepRootCards(want),tossSameOriginFrameCards(want),tossPriceBoundaryCards(want),tossTextBoundaryCards(want),tossButtonRowCards(want),tossImageBoundaryCards(want),tossAnchorBoundaryCards(want),genericCards(want)],map=new Map();
   for(const arr of sources)for(const c of arr){const k=(normalizeLabel(c.name||'')+'|'+c.price);if(!map.has(k))map.set(k,c);}
   const out=[...map.values()];if(out.length)return out.slice(0,limit);
 }
 if(site()==="네이버쇼핑"){
   const sources=[naverRankBoundaryCards(Math.max(limit,60)),naverRankCards(Math.max(limit,60)),naverLooseCards(Math.max(limit,60)),genericCards(Math.max(limit,60))];
   const map=new Map();
   for(const arr of sources)for(const c of arr){
     const rank=Number(c.rank_hint||0), key=rank?`r${rank}`:((c.name||'').toLowerCase()+'|'+c.price);
     if(!map.has(key))map.set(key,c);
   }
   const out=[...map.values()];out.sort((a,b)=>(Number(a.rank_hint||9999)-Number(b.rank_hint||9999)));
   if(out.length)return out.slice(0,limit);
 }
 return genericCards(limit);
}
// v8.03: visible popularity signals for trend-keyword -> Coupang selection.
// This intentionally uses only information rendered on the normal search page:
// review count, recent purchase/sales count, rating, relevance and search position.
function coupangCountValue(raw){
 const s=String(raw||'').replace(/,/g,'').trim(),m=s.match(/([0-9]+(?:\.[0-9]+)?)\s*(만|천)?\s*\+?/);if(!m)return 0;
 let v=Number(m[1]||0);if(m[2]==='만')v*=10000;else if(m[2]==='천')v*=1000;return Math.round(v||0);
}
function coupangPopularityFromCard(card,query,index){
 const text=String(card?.text||''),reviews=[],purchases=[],ratings=[];
 for(const rx of [/(?:리뷰|상품평)\s*[:：]?\s*[\(\[]?\s*([0-9][0-9,.]*(?:\s*(?:만|천))?\+?)/gi,/(?:후기)\s*[:：]?\s*[\(\[]?\s*([0-9][0-9,.]*(?:\s*(?:만|천))?\+?)/gi,/\(([0-9][0-9,]{1,8})\)/g]){
   for(const m of text.matchAll(rx))reviews.push(coupangCountValue(m[1]));
 }
 for(const m of text.matchAll(/(?:최근\s*한\s*달\s*)?(?:구매|판매)\s*([0-9][0-9,.]*(?:\s*(?:만|천))?\+?)/gi))purchases.push(coupangCountValue(m[1]));
 for(const rx of [/(?<!\d)([0-5]\.\d)(?!\d)/g,/(?<!\d)([0-5](?:\.\d)?)\s*(?:점|\/\s*5)(?!\d)/g]){for(const m of text.matchAll(rx)){const v=Number(m[1]);if(v>=0&&v<=5)ratings.push(v);}}
 const qs=tokens(String(query||'')),low=(String(card?.name||'')+' '+text).toLowerCase();
 const relevance=qs.length?qs.filter(x=>low.includes(x)).length/qs.length:0;
 const review_count=Math.max(0,...reviews),purchase_count=Math.max(0,...purchases),rating=Math.max(0,...ratings);
 const search_position=Math.max(1,Number(index||0)+1),is_ad=/(^|\s)광고($|\s)/.test(text);
 let score=Math.log1p(review_count)*18+Math.log1p(purchase_count)*22+rating*5+relevance*38+18/Math.sqrt(search_position);
 if(is_ad)score-=30;if(!isCoupangProductHref(card?.url||''))score-=25;
 return{review_count,purchase_count,rating,relevance:Number(relevance.toFixed(4)),search_position,is_ad,score:Number(score.toFixed(4)),method:'visible_review_purchase_rating_position_v8_03'};
}
function chooseCoupangTrendProduct(cs,query){
 const arr=(cs||[]).map((c,i)=>({...c,popularity:coupangPopularityFromCard(c,query,i)})).filter(c=>c.name&&c.popularity.relevance>0);
 if(!arr.length)return{cards:[],selected:null};
 const nonAds=arr.filter(c=>!c.popularity.is_ad),pool=nonAds.length?nonAds:arr;
 pool.sort((a,b)=>b.popularity.score-a.popularity.score||b.popularity.review_count-a.popularity.review_count||b.popularity.purchase_count-a.popularity.purchase_count||a.popularity.search_position-b.popularity.search_position);
 return{cards:arr,selected:pool[0]||null};
}

function crit(s){let a=[];for(const m of s.matchAll(/\d+(?:\.\d+)?\s?(?:ml|l|g|kg|mg|cm|mm|oz|개입|개|매|팩|세트|인치)/gi))a.push(m[0].replace(/\s/g,"").toLowerCase());
 for(const x of (s.toUpperCase().match(/\b[A-Z0-9_-]{5,}\b/g)||[]))if(/[A-Z]/.test(x)&&/\d/.test(x))a.push(x.toLowerCase());return[...new Set(a)];
}
function tokens(s){return[...new Set((s.toLowerCase().match(/[0-9a-z가-힣]+/g)||[]).filter(x=>x.length>=2))];}
function score(text,target){const compact=text.toLowerCase().replace(/\s/g,"");for(const c of crit(target))if(!compact.includes(c))return 0;const ts=tokens(target);if(!ts.length)return 0;let hit=0;for(const x of ts)if(text.toLowerCase().includes(x))hit++;return hit/ts.length;}
function blocked(){
 const b=(document.body?.innerText||"").toLowerCase(),u=location.href.toLowerCase();
 if(site()==="쿠팡")return u.includes("errors.edgesuite.net")||b.includes("access denied")||b.includes("you don't have permission to access")
   ||b.includes("요청하신 페이지의 사용권한이 없습니다")||b.includes("사용권한이 제한된 페이지")||b.includes("접근이 제한된 페이지")||b.includes("입력하신 페이지주소는 사용권한이 제한된 페이지입니다");
 if(site()==="네이버쇼핑")return b.includes("비정상적인 접근")||b.includes("자동입력 방지")||b.includes("서비스 이용이 제한");
 return false;
}
function tossLogin(){
 const b=(document.body?.innerText||"").replace(/\s+/g," ");
 const path=(location.pathname||"").toLowerCase();
 if(/(^|\/)(login|signin|sign-in)(\/|$)/.test(path))return true;
 // Sharelink의 로그인된 대시보드에도 '로그인' 문자열이 남을 수 있다.
 // 실제 앱 메뉴가 하나라도 보이면 로그인 완료 상태로 취급한다.
 if(/베스트\s*랭킹|상품\s*조회|링크\s*관리|실적\s*대시보드|API\s*키\s*발급|정산\s*내역/.test(b))return false;
 const pwd=[...document.querySelectorAll("input[type='password']")].some(vis);
 const authInput=[...document.querySelectorAll("input")].some(e=>vis(e)&&/(휴대폰|전화번호|이메일|비밀번호|인증번호)/.test((e.placeholder||"")+" "+(e.getAttribute('aria-label')||"")));
 const loginButton=[...document.querySelectorAll("button,a,[role='button']")].some(e=>vis(e)&&/^로그인$/.test(txt(e).trim()));
 return pwd || (loginButton&&authInput);
}
function findInput(s){for(const x of s){for(const e of document.querySelectorAll(x))if(vis(e)&&!e.disabled)return e;}return null;}
function clickText(labels){for(const l of labels){for(const e of document.querySelectorAll("button,a,div,span")){if(vis(e)&&txt(e).trim()===l){e.click();return true;}}}return false;}
async function sleep(ms){return new Promise(r=>setTimeout(r,ms));}

function clickableFromText(label){
  const nodes=[...document.querySelectorAll("a,button,[role='button'],li,div,span")];
  for(const e of nodes){
    if(!vis(e)) continue;
    const t=txt(e).replace(/\s+/g," ").trim();
    if(t===label || t.startsWith(label+" ")){
      return e.closest("a,button,[role='button']") || e;
    }
  }
  return null;
}
async function waitInput(selectors,timeout=10000){
  const end=Date.now()+timeout;
  while(Date.now()<end){
    const x=findInput(selectors);
    if(x) return x;
    await sleep(250);
  }
  return null;
}
function tossProductSearchInput(){
  const nodes=[...document.querySelectorAll("input[type='search'],input[type='text'],input:not([type])")].filter(e=>vis(e)&&!e.disabled);
  let best=null,bestScore=-999;
  for(const e of nodes){
    const hint=((e.placeholder||"")+" "+(e.getAttribute('aria-label')||"")+" "+(e.name||"")).replace(/\s+/g," ").toLowerCase();
    const r=e.getBoundingClientRect();let sc=0;
    if(/상품명|상품\s*검색|제품명|검색/.test(hint))sc+=100;
    if(/상품/.test(hint))sc+=45;
    if(e.type==='search')sc+=20;
    if(r.width>=220)sc+=15;if(r.width>=360)sc+=10;
    if(/카테고리|api|url|링크|금액|수수료|날짜|기간|이메일|전화/.test(hint))sc-=180;
    const near=(e.closest('form,section,main,div')?.innerText||'').slice(0,250);
    if(/상품\s*조회|상품\s*검색/.test(near))sc+=25;
    if(sc>bestScore){bestScore=sc;best=e;}
  }
  return bestScore>=20?best:null;
}
async function tossGoProductLookup(){
  if(tossLogin()) return {status:"login_required"};
  // 1) Already on product lookup page?
  let inp=tossProductSearchInput();
  if(!inp) inp=await waitInput([
    "input[placeholder*='상품명']",
    "input[placeholder*='상품']",
    "input[placeholder*='검색']",
    "input[type='search']"
  ],1200);
  if(inp) return {status:"ok",input:inp};

  // 2) Click the actual left sidebar "상품 조회" menu visible in Sharelink PC.
  let menu=clickableFromText("상품 조회") || clickableFromText("상품조회");
  if(menu){
    try{ menu.click(); }catch(e){}
    await sleep(900);
  }

  inp=tossProductSearchInput();
  if(!inp) inp=await waitInput([
    "input[placeholder*='상품명']",
    "input[placeholder*='상품']",
    "input[placeholder*='검색']",
    "input[aria-label*='검색']",
    "input[type='search']",
    "input[type='text']"
  ],9000);
  if(inp) return {status:"ok",input:inp};

  // 3) v7.18: never fall back to Best Ranking. Product lookup must stay on 상품 조회.
  return {status:"no_search_ui"};
}

const TOSS_CATEGORY_ALIASES={
  "생활용품":["생활용품","생활","생활/건강","생활·건강","리빙","생활건강"],
  "주방용품":["주방용품","주방","주방/생활","주방·생활","키친"],
  "패션잡화":["패션의류잡화","패션의류/잡화","패션의류·잡화","패션잡화","패션","패션/잡화","패션·잡화","의류/잡화","의류·잡화"],
  "식품":["식품","푸드","식품/건강","식품·건강","먹거리"],
  "디지털/가전":["가전/디지털","가전·디지털","디지털/가전","디지털·가전","가전디지털","디지털","가전"],
  "화장품/미용":["뷰티","화장품/미용","화장품·미용","뷰티/미용","뷰티·미용","화장품","미용"]
};
const TOSS_CATEGORY_KEYWORDS={
  "생활용품":["세제","세탁","섬유유연제","휴지","화장지","물티슈","청소","욕실","수건","탈취","방향","생활"],
  "주방용품":["주방","밀폐","용기","프라이팬","후라이팬","냄비","텀블러","컵","도마","칼","식기","수저","보관"],
  "패션잡화":["운동화","스니커즈","신발","가방","백팩","원피스","티셔츠","셔츠","바지","패딩","자켓","재킷","모자","샌들","의류","패션"],
  "식품":["쌀","잡곡","음료","생수","커피","차","과자","간식","고기","소고기","돼지","김치","과일","건강식품","비타민","식품"],
  "디지털/가전":["이어폰","헤드폰","충전","마우스","키보드","선풍기","가습기","청소기","냉장고","에어프라이어","전자","가전","디지털","스피커"],
  "화장품/미용":["화장품","뷰티","스킨","로션","크림","세럼","에센스","쿠션","파운데이션","립","틴트","샴푸","트리트먼트","선크림"]
};

// v7.18 Toss popularity collection: 링크 > 상품 조회 > exactly ONE category checkbox.
// The visible Sharelink labels are intentionally kept exactly as the user specified.
const TOSS_PRODUCT_LOOKUP_CATEGORIES=[
  {blog:"디지털/가전",site:"가전/디지털",aliases:["가전/디지털","가전·디지털","디지털/가전","디지털·가전","가전디지털"]},
  {blog:"화장품/미용",site:"뷰티",aliases:["뷰티","화장품/미용","화장품·미용","화장품","미용"]},
  {blog:"생활용품",site:"생활용품",aliases:["생활용품","생활"]},
  {blog:"식품",site:"식품",aliases:["식품"]},
  {blog:"주방용품",site:"주방용품",aliases:["주방용품","주방"]},
  {blog:"패션잡화",site:"패션의류잡화",aliases:["패션의류잡화","패션의류/잡화","패션의류·잡화","패션잡화","패션/잡화","패션·잡화","의류/잡화","의류·잡화"]}
];
function tossCategoryDefByLabel(label,aliases=[]){
  const wants=[label,...(aliases||[])].filter(Boolean).map(normalizeLabel);
  let best=TOSS_PRODUCT_LOOKUP_CATEGORIES[0],score=-1;
  for(const d of TOSS_PRODUCT_LOOKUP_CATEGORIES){
    const ds=[d.site,d.blog,...d.aliases].map(normalizeLabel);
    let sc=0;
    for(const a of wants)for(const b of ds){if(a===b)sc=Math.max(sc,100);else if(a&&b&&(a.includes(b)||b.includes(a)))sc=Math.max(sc,60);}
    if(sc>score){score=sc;best=d;}
  }
  return score>=60?best:null;
}
function tossLabelTextForControl(e){
  if(!e)return"";
  const bits=[];
  const push=x=>{x=(x||"").replace(/\s+/g," ").trim();if(x&&x.length<=110&&!bits.includes(x))bits.push(x);};
  push(e.getAttribute?.("aria-label"));push(e.getAttribute?.("title"));push(txt(e));
  if(e.labels)for(const l of e.labels)push(txt(l));
  const id=e.id;if(id){try{const lab=document.querySelector(`label[for="${CSS.escape(id)}"]`);if(lab)push(txt(lab));}catch(_e){}}
  let n=e.parentElement;
  for(let i=0;n&&i<4;i++,n=n.parentElement){const t=txt(n);if(t&&t.length<=110)push(t);}
  return bits.join(" | ");
}
function tossAliasScore(raw,aliases){
  const n=normalizeLabel(raw);let sc=-1;
  for(const a0 of aliases||[]){const a=normalizeLabel(a0);if(!a)continue;
    if(n===a)sc=Math.max(sc,220);
    else if(n.startsWith(a+"|")||n.endsWith("|"+a))sc=Math.max(sc,205);
    else if(a.length>=2&&n.includes(a))sc=Math.max(sc,150);
  }
  return sc;
}
function tossNearestCheckboxForLabel(e){
  if(!e)return null;
  if(e.matches?.('input[type="checkbox"],[role="checkbox"],[aria-checked]'))return e;
  const inside=e.querySelector?.('input[type="checkbox"],[role="checkbox"],[aria-checked]');if(inside)return inside;
  let n=e;
  for(let i=0;n&&i<6;i++,n=n.parentElement){
    const own=n.matches?.('input[type="checkbox"],[role="checkbox"],[aria-checked]')?n:null;if(own)return own;
    const x=n.querySelector?.('input[type="checkbox"],[role="checkbox"],[aria-checked]');if(x)return x;
    const role=(n.getAttribute?.('role')||'').toLowerCase();
    const cls=String(n.className||'').toLowerCase();
    if(role==='button'||role==='option'||/(checkbox|check-box|filter|chip|pill|toggle)/.test(cls))return n;
  }
  return interactiveTarget(e);
}
function tossExactCategoryLabelNode(labels){
  const aliases=(labels||[]).filter(Boolean).map(normalizeLabel);if(!aliases.length)return null;
  const nodes=[...document.querySelectorAll('label,span,p,div,button,[role="option"],[role="checkbox"],[role="button"]')].filter(vis).filter(tossMainAreaElement);
  let best=null,bestScore=-1;
  for(const e of nodes){
    const raw=txt(e).replace(/\s+/g,' ').trim();if(!raw||raw.length>55)continue;
    const n=normalizeLabel(raw);let sc=-1;
    for(const a of aliases){
      if(n===a)sc=Math.max(sc,300);
      else if(a.length>=3&&n===normalizeLabel(a.replace(/\//g,'')))sc=Math.max(sc,260);
    }
    if(sc<0)continue;
    const r=e.getBoundingClientRect();
    if(r.width<4||r.height<4||r.left<180)continue;
    if(e.children.length===0)sc+=70;
    if(e.tagName==='LABEL')sc+=65;
    if(e.tagName==='BUTTON')sc+=45;
    if((e.getAttribute?.('role')||'').toLowerCase()==='checkbox')sc+=60;
    if(r.height>=14&&r.height<=80)sc+=20;
    if(r.width>=20&&r.width<=420)sc+=15;
    if(sc>bestScore){bestScore=sc;best=e;}
  }
  return bestScore>=300?best:null;
}
function tossControlCandidatesForLabel(labelNode){
  if(!labelNode)return[];const out=[];const push=x=>{if(x&&!out.includes(x))out.push(x);};
  if(labelNode.matches?.('input[type="checkbox"],[role="checkbox"]'))push(labelNode);
  const lab=labelNode.closest?.('label');if(lab){push(lab.querySelector?.('input[type="checkbox"]'));push(lab);}
  let n=labelNode;
  for(let i=0;n&&i<5;i++,n=n.parentElement){
    push(n.querySelector?.(':scope > input[type="checkbox"]'));
    push(n.querySelector?.('input[type="checkbox"]'));
    push(n.querySelector?.('[role="checkbox"]'));
    const prev=n.previousElementSibling,next=n.nextElementSibling;
    for(const x of [prev,next]){if(!x)continue;push(x.matches?.('input[type="checkbox"],[role="checkbox"]')?x:null);push(x.querySelector?.('input[type="checkbox"],[role="checkbox"]'));}
    const role=(n.getAttribute?.('role')||'').toLowerCase(),cls=String(n.className||'').toLowerCase(),r=n.getBoundingClientRect();
    if((n.tagName==='BUTTON'||role==='checkbox'||role==='option'||role==='button'||/(checkbox|check-box|filter|chip|pill|toggle)/.test(cls))&&r.height<=120)push(n);
  }
  // The exact text node itself is a valuable React target: a bubbling click on
  // the visible label reaches delegated handlers without accidentally clicking a
  // large parent container that can represent the whole filter section.
  push(labelNode);
  try{
    const r=labelNode.getBoundingClientRect(),y=Math.max(1,Math.min(innerHeight-2,r.top+r.height/2));
    for(const dx of [-34,-24,-14,14,24,34]){
      const x=Math.max(1,Math.min(innerWidth-2,r.left+(dx<0?dx:r.width+dx)));
      const hit=document.elementFromPoint(x,y);if(hit){
        push(hit.matches?.('input[type="checkbox"],[role="checkbox"]')?hit:null);
        push(hit.closest?.('label,button,[role="checkbox"],[role="button"]'));
        try{const hr=hit.getBoundingClientRect(),hc=(getComputedStyle(hit).cursor||'').toLowerCase();if(hr.width>=8&&hr.width<=72&&hr.height>=8&&hr.height<=72&&(hc==='pointer'||hit.querySelector?.('svg')))push(hit);}catch(_e){}
      }
    }
  }catch(_e){}
  return out.filter(Boolean);
}
function tossCategoryControlByAliases(labels){
  const aliases=(labels||[]).filter(Boolean);if(!aliases.length)return null;
  const label=tossExactCategoryLabelNode(aliases);
  if(label){
    const cand=tossControlCandidatesForLabel(label);
    // Prefer real checkbox semantics, then label/button, then the exact leaf.
    for(const e of cand)if(e.matches?.('input[type="checkbox"]'))return e;
    for(const e of cand)if((e.getAttribute?.('role')||'').toLowerCase()==='checkbox')return e;
    for(const e of cand)if(e.tagName==='LABEL'||e.tagName==='BUTTON')return e;
    if(cand.length)return cand[0];
  }
  // Strict fallback: semantic controls in the main Product Lookup content only.
  let best=null,bestScore=-1;
  const controls=[...document.querySelectorAll('input[type="checkbox"],[role="checkbox"],[aria-checked]')].filter(tossMainAreaElement);
  for(const e of controls){
    const raw=tossLabelTextForControl(e);let sc=tossAliasScore(raw,aliases);if(sc<0)continue;
    if(e.matches?.('input[type="checkbox"]'))sc+=90;
    if((e.getAttribute?.('role')||'').toLowerCase()==='checkbox')sc+=75;
    if(sc>bestScore){bestScore=sc;best=e;}
  }
  return bestScore>=150?best:null;
}
function tossControlState(e){
  if(!e)return{known:false,checked:false,source:'missing'};
  if(e.matches?.('input[type="checkbox"]'))return{known:true,checked:!!e.checked,source:'input.checked'};
  const inp=e.querySelector?.('input[type="checkbox"]');if(inp)return{known:true,checked:!!inp.checked,source:'descendant.checked'};
  const attrs=['aria-checked','aria-selected','aria-pressed'];
  for(const a of attrs){const v=(e.getAttribute?.(a)||'').toLowerCase();if(v==='true')return{known:true,checked:true,source:a};if(v==='false')return{known:true,checked:false,source:a};}
  const states=['data-state','data-checked','data-selected'];
  for(const a of states){const v=(e.getAttribute?.(a)||'').toLowerCase();if(['checked','true','on','selected','active'].includes(v))return{known:true,checked:true,source:a};if(['unchecked','false','off','inactive'].includes(v))return{known:true,checked:false,source:a};}
  let n=e;
  for(let i=0;n&&i<4;i++,n=n.parentElement){
    const cls=String(n.className||'').toLowerCase();
    if(/(^|[ _-])(checked|selected|active|on)([ _-]|$)/.test(cls))return{known:true,checked:true,source:'class'};
    if(/(^|[ _-])(unchecked|inactive|off)([ _-]|$)/.test(cls))return{known:true,checked:false,source:'class'};
  }
  return{known:false,checked:false,source:'unknown'};
}
function tossControlChecked(e){return tossControlState(e).checked;}
function tossControlFingerprint(e){
  if(!e)return'';
  const parts=[];let n=e;
  for(let i=0;n&&i<4;i++,n=n.parentElement){
    const st=getComputedStyle(n),r=n.getBoundingClientRect();
    const attrs=['class','role','aria-checked','aria-selected','aria-pressed','data-state','data-checked','data-selected'];
    parts.push(attrs.map(a=>`${a}=${n.getAttribute?.(a)||''}`).join(';'));
    parts.push(`bg=${st.backgroundColor};bc=${st.borderColor};c=${st.color};fw=${st.fontWeight};o=${st.opacity};w=${Math.round(r.width)};h=${Math.round(r.height)}`);
    const svg=n.querySelector?.('svg');if(svg)parts.push('svg='+String(svg.outerHTML||'').slice(0,500));
  }
  return parts.join('||');
}
function tossTxnGet(){try{return JSON.parse(sessionStorage.getItem('nvb_toss_filter_txn')||'null');}catch(_e){return null;}}
function tossTxnSet(x){try{sessionStorage.setItem('nvb_toss_filter_txn',JSON.stringify(x||null));}catch(_e){}return x;}
function tossTxnClear(){try{sessionStorage.removeItem('nvb_toss_filter_txn');}catch(_e){}}
function tossMainClickReceiptGet(){try{return JSON.parse(sessionStorage.getItem('nvb_toss_main_category_click_receipt')||'null');}catch(_e){return null;}}
function tossMainClickReceiptClear(){try{sessionStorage.removeItem('nvb_toss_main_category_click_receipt');}catch(_e){}}
function tossRawProductSignature(){
  const main=[...document.querySelectorAll('main,[role="main"],section,div')].filter(tossMainAreaElement);
  let root=main.sort((a,b)=>{const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();return(br.width*br.height)-(ar.width*ar.height);})[0]||document.body;
  const text=(root?.innerText||'').replace(/\s+/g,' ').slice(0,18000);
  const prices=(text.match(/\d{1,3}(?:,\d{3})+\s*원/g)||[]).slice(0,80);
  return `${text.length}|${prices.join('|')}|${text.slice(-1200)}`;
}
function tossTxnMatches(siteCategory){const t=tossTxnGet();return !!t&&normalizeLabel(t.site||'')===normalizeLabel(siteCategory||'');}
function tossCategoryState(){
  const out=[];
  for(const d of TOSS_PRODUCT_LOOKUP_CATEGORIES){
    const c=tossCategoryControlByAliases([d.site,...d.aliases]);
    out.push({blog:d.blog,site:d.site,found:!!c,checked:!!c&&tossControlChecked(c),text:c?tossLabelTextForControl(c).slice(0,140):""});
  }
  return out;
}
function tossExactMenuControl(label){
  const want=normalizeLabel(label),nodes=[...document.querySelectorAll('a,button,[role="button"],[role="menuitem"],li,span,div')].filter(vis);
  let best=null,bestScore=-1;
  for(const e of nodes){
    const raw=txt(e).replace(/\s+/g,' ').trim();if(!raw||normalizeLabel(raw)!==want)continue;
    const it=interactiveTarget(e);let sc=100;
    if(it.tagName==='A'||it.tagName==='BUTTON')sc+=30;
    const role=(it.getAttribute?.('role')||'').toLowerCase();if(role==='button'||role==='menuitem')sc+=25;
    if(e.children.length===0)sc+=12;
    if(sc>bestScore){bestScore=sc;best=it;}
  }
  return best;
}
function tossFindProductLookupMenu(){return tossExactMenuControl('상품 조회')||tossExactMenuControl('상품조회');}
function tossFindLinkGroup(){return tossExactMenuControl('링크');}
function tossMenuHref(e){
  if(!e)return"";
  try{
    const a=e.closest?.('a[href]')||e.querySelector?.('a[href]');
    const h=a?.getAttribute?.('href')||"";
    if(h&&!h.startsWith('#')&&!h.startsWith('javascript:'))return new URL(h,location.href).href;
  }catch(_e){}
  let n=e?.parentElement;
  for(let i=0;n&&i<6;i++,n=n.parentElement){
    try{if(n.matches?.('a[href]')){const h=n.getAttribute('href')||"";if(h&&!h.startsWith('#'))return new URL(h,location.href).href;}}catch(_e){}
  }
  return"";
}
function tossMainAreaElement(e){
  if(!e||!vis(e))return false;
  try{if(e.closest('aside,nav,[role="navigation"]'))return false;}catch(_e){}
  const r=e.getBoundingClientRect();
  const sideCut=Math.min(260,Math.max(170,innerWidth*0.17));
  return r.right>sideCut+30 && (r.left>sideCut-30 || r.width>innerWidth*0.45);
}
function tossMainHeadingConfirmed(){
  const nodes=[...document.querySelectorAll('h1,h2,h3,h4,[role="heading"]')].filter(tossMainAreaElement);
  return nodes.some(e=>/^상품\s*조회$/.test(txt(e).trim())||txt(e).trim().startsWith('상품 조회 '));
}
function tossMainSearchInput(){
  const sels=["input[placeholder*='상품명']","input[placeholder*='상품']","input[placeholder*='검색']","input[aria-label*='검색']","input[type='search']"];
  for(const sel of sels){
    for(const e of document.querySelectorAll(sel)){if(tossMainAreaElement(e)&&!e.disabled)return e;}
  }
  return null;
}
function tossCategoryHeadingInMain(){
  return [...document.querySelectorAll('h1,h2,h3,h4,strong,legend,button,[role="button"],span,div')].filter(tossMainAreaElement).some(e=>{const t=txt(e).replace(/\s+/g,' ').trim();return t==='카테고리'||/^카테고리\s*(전체|선택|필터)?$/.test(t);});
}
async function tossDispatchClickChain(e){
  if(!e)return{ok:false,error:'menu missing'};
  // v7.28: exactly ONE activation.  Older builds dispatched a synthetic
  // 'click' event and then called element.click() again, so React/SPA menu
  // handlers could receive two clicks and return to the original state.
  const before=location.href;
  let target=interactiveTarget(e)||e;
  try{target.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}
  await sleep(120);
  try{try{target.focus?.({preventScroll:true});}catch(_e){};target.click();}
  catch(_e){try{target.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window,button:0}));}catch(__e){return{ok:false,error:String(__e),url:location.href};}}
  // Give the SPA enough time to mount the new main content before any retry.
  const end=Date.now()+1500;
  while(Date.now()<end){
    await sleep(150);
    if(location.href!==before||tossProductLookupPageConfirmed())break;
  }
  return{ok:true,navigated:location.href!==before,target:txt(target).trim(),url:location.href,product_lookup_confirmed:tossProductLookupPageConfirmed()};
}
async function tossEnterProductLookup(){
  if(tossLogin())return{ok:false,login_required:true};
  if(tossProductLookupPageConfirmed())return{ok:true,already:true};
  // User's real Sharelink screen already exposes 상품 조회 under 링크. Never
  // click the parent accordion when the child is visible because that can close it.
  let menu=tossFindProductLookupMenu();
  if(!menu){
    const link=tossFindLinkGroup();
    if(link){
      const expanded=(link.getAttribute?.('aria-expanded')||'').toLowerCase();
      if(expanded!=='true'){await tossDispatchClickChain(link);await sleep(500);}
    }
    menu=tossFindProductLookupMenu();
  }
  if(!menu)return{ok:false,wait:true,error:"토스 왼쪽 '링크' 영역에서 '상품 조회' 버튼을 찾지 못했습니다."};
  const href=tossMenuHref(menu);
  sessionStorage.removeItem('nvb_toss_category_panel_clicked');
  const beforeUrl=location.href;
  const click=await tossDispatchClickChain(menu);
  const end=Date.now()+3200;
  while(Date.now()<end){
    await sleep(220);
    if(tossProductLookupPageConfirmed())return{ok:true,clicked:true,click,href};
    if(location.href!==beforeUrl)return{ok:false,wait:true,navigated:true,error:'상품 조회 경로 이동 후 본문 렌더링 대기',click,href};
  }
  // React event delegation can occasionally ignore synthetic clicks. If the menu
  // is an anchor (or is inside one), let background.js navigate to its exact href.
  if(href&&normalizeLabel(href)!==normalizeLabel(location.href))return{ok:false,wait:true,navigate_url:href,error:'상품 조회 메뉴 href 직접 이동',click,href};
  return{ok:false,wait:true,error:'상품 조회 클릭 후에도 홈 화면입니다. 메뉴 클릭 이벤트를 재시도합니다.',click,href,home_path:(location.pathname||'')};
}
function tossFindSearchInput(){return tossMainSearchInput();}
function tossProductLookupPageConfirmed(){
  if(tossLogin())return false;
  // v7.19 false-positive fix: the /home dashboard always contains the sidebar
  // text '상품 조회'. Never treat that sidebar text or unrelated product words
  // as proof that the Product Lookup page opened.
  const menu=tossFindProductLookupMenu();
  const selected=!!menu&&selectedControl(menu);
  const heading=tossMainHeadingConfirmed();
  const input=!!tossMainSearchInput();
  const category=tossCategoryHeadingInMain();
  const path=(location.pathname||'/').replace(/\/+$/,'')||'/';
  const notHome=path!=='/'&&path!=='/home';
  return (selected&&(heading||input||category||notHome)) || (heading&&(input||category||notHome)) || (input&&category) || (notHome&&input);
}
function tossProductLookupVisible(){return tossProductLookupPageConfirmed();}
function tossFindCategorySection(){
  const nodes=[...document.querySelectorAll('button,[role="button"],summary,legend,h2,h3,h4,strong,span,div')].filter(vis);
  let best=null,bestScore=-1;
  for(const e of nodes){
    const t=txt(e).replace(/\s+/g,' ').trim();if(!t||t.length>50)continue;
    let sc=-1;if(t==='카테고리')sc=160;else if(/^카테고리\s*(전체|선택|필터)?$/.test(t))sc=145;else continue;
    const it=interactiveTarget(e);if(it!==e)sc+=20;
    const role=(it.getAttribute?.('role')||'').toLowerCase();if(role==='button')sc+=20;if(it.tagName==='BUTTON'||it.tagName==='SUMMARY')sc+=20;
    if(sc>bestScore){bestScore=sc;best=it;}
  }
  return best;
}
async function tossEnsureCategoryPanel(targetAliases=[]){
  let c=tossCategoryControlByAliases(targetAliases);
  if(c){try{c.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}return{ok:true,opened:false,target_found:true};}
  const section=tossFindCategorySection();
  if(section){
    try{section.scrollIntoView?.({block:'center',behavior:'instant'});}catch(e){}
    await sleep(180);
    const aria=(section.getAttribute?.('aria-expanded')||'').toLowerCase();
    const state=(section.getAttribute?.('data-state')||'').toLowerCase();
    const explicitlyOpen=aria==='true'||['open','opened','expanded'].includes(state);
    const explicitlyClosed=aria==='false'||['closed','collapsed'].includes(state);
    // Do not toggle an already-open accordion on every retry. On components
    // without aria-expanded, click at most once per document.
    const once=sessionStorage.getItem('nvb_toss_category_panel_clicked')==='1';
    if(explicitlyClosed||(!explicitlyOpen&&!once)){
      await tossDispatchClickChain(section);
      sessionStorage.setItem('nvb_toss_category_panel_clicked','1');
      await sleep(650);
    }
  }
  c=tossCategoryControlByAliases(targetAliases);
  if(c){try{c.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}return{ok:true,opened:!!section,target_found:true};}
  // Search progressively down the main content. Toss sometimes mounts filter
  // chips only after they approach the viewport.
  const startY=window.scrollY;
  for(let i=0;i<5&&!c;i++){
    window.scrollBy({top:Math.max(320,innerHeight*0.55),behavior:'instant'});
    await sleep(420);
    c=tossCategoryControlByAliases(targetAliases);
  }
  if(c){try{c.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}return{ok:true,opened:!!section,target_found:true,scrolled:true};}
  try{window.scrollTo({top:startY,behavior:'instant'});}catch(_e){}
  return{ok:false,opened:!!section,target_found:false,error:'상품 조회는 열렸지만 대상 카테고리 컨트롤을 찾지 못했습니다.'};
}
async function tossClickCheckbox(control,desired,timeout=5000){
  if(!control)return{ok:false,error:"checkbox control missing"};
  if(tossControlChecked(control)===desired)return{ok:true,changed:false};
  const direct=control.matches?.('input[type="checkbox"]')?control:(control.querySelector?.('input[type="checkbox"]')||null);
  const before=tossControlChecked(control);
  try{
    const clickable=(direct&&vis(direct))?direct:(control.closest?.('label')||interactiveTarget(control)||control);
    clickable.scrollIntoView?.({block:'center',behavior:'instant'});await sleep(120);
    try{clickable.click();}catch(_e){clickable.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));}
  }catch(e){return{ok:false,error:String(e)};}
  const end=Date.now()+timeout;
  while(Date.now()<end){
    await sleep(220);
    if(tossControlChecked(control)===desired)return{ok:true,changed:before!==desired};
    const label=tossLabelTextForControl(control);const ref=tossCategoryControlByAliases([label]);
    if(ref&&tossControlChecked(ref)===desired)return{ok:true,changed:before!==desired};
  }
  return{ok:false,error:`체크 상태가 ${desired?'선택':'해제'}로 바뀌지 않았습니다.`};
}
async function tossClearAllCategoryChecks(){
  const before=tossCategoryState();
  for(const d of TOSS_PRODUCT_LOOKUP_CATEGORIES){
    let c=tossCategoryControlByAliases([d.site,...d.aliases]);
    if(c&&tossControlChecked(c)){
      const r=await tossClickCheckbox(c,false,4500);if(!r.ok)return{ok:false,error:`${d.site} 체크 해제 실패: ${r.error}`,before,after:tossCategoryState()};
      await sleep(250);
    }
  }
  const after=tossCategoryState(),checked=after.filter(x=>x.checked);
  // Do not demand that all 6 controls are mounted. The only invariant required
  // between tasks is that no known category remains checked.
  return{ok:checked.length===0,before,after,checked:checked.map(x=>x.site),found_count:after.filter(x=>x.found).length};
}
function tossProductSignature(){
  return cards(16).map(c=>(c.name||'').slice(0,70)+'|'+(c.price||'')).join('||');
}
async function tossSelectOnlyCategory(siteCategory,aliases=[]){
  const d=tossCategoryDefByLabel(siteCategory,aliases);if(!d)return{ok:false,error:'토스 카테고리 매핑 실패: '+siteCategory};
  if(!tossProductLookupPageConfirmed())return{ok:false,wait:true,error:'토스 상품 조회 화면 확인 대기'};
  const panel=await tossEnsureCategoryPanel([d.site,...d.aliases,...aliases]);
  if(!panel.ok)return{ok:false,wait:true,error:`${d.site} 체크박스 렌더링 대기`,panel,state:tossCategoryState()};
  let target=tossCategoryControlByAliases([d.site,...d.aliases,...aliases]);
  if(!target)return{ok:false,wait:true,error:'토스 카테고리 체크박스를 찾지 못했습니다: '+d.site,state:tossCategoryState()};

  let txn=tossTxnGet();
  if(txn && normalizeLabel(txn.site||'')!==normalizeLabel(d.site)){
    return{ok:false,error:`이전 토스 필터 트랜잭션이 종료되지 않았습니다: ${txn.site||'?'} -> ${d.site}`,transaction:txn};
  }
  // If a transaction has already been confirmed for this category, do not click
  // again. Re-check the selected state against the exact target before collect.
  if(txn&&txn.phase==='selected'){
    const st=tossControlState(target),fp=tossControlFingerprint(target);
    const explicit=st.known&&st.checked;
    const stableVisual=!!txn.selected_fp&&fp===txn.selected_fp&&fp!==txn.before_fp;
    if(explicit||stableVisual)return{ok:true,target:d.site,state:tossCategoryState(),checked_labels:[d.site],panel,checkbox_stable:true,transaction:txn,evidence:{state:st,stable_visual:stableVisual,reused:true},collector_diag:tossCollectorDiagnostics()};
    return{ok:false,error:`${d.site} 선택 트랜잭션은 있으나 실제 체크 상태가 유지되지 않습니다.`,transaction:txn,state:tossCategoryState(),diag:tossCollectorDiagnostics()};
  }

  // v7.24 HARD CHECK GATE: the content script no longer performs the ON click.
  // Ask background.js to click the exact category control in the page MAIN world.
  // This prevents a broad parent DIV from being clicked and prevents the route
  // from advancing merely because the product list changed for another reason.
  const receipt=tossMainClickReceiptGet();
  const receiptMatches=!!receipt&&normalizeLabel(receipt.site||'')===normalizeLabel(d.site)&&Date.now()-Number(receipt.ts||0)<12000;
  if(!receiptMatches){
    return{ok:false,needs_main_world_click:true,error:`${d.site} 실제 체크 클릭 필요`,panel,state:tossCategoryState(),target_aliases:[d.site,...d.aliases,...aliases]};
  }

  // Confirm the MAIN-world click with only strong target-state evidence.
  // Product-list signature changes are intentionally NOT accepted as proof; they
  // caused the real user's page to advance with no category visibly checked.
  target=tossCategoryControlByAliases([d.site,...d.aliases,...aliases])||target;
  const st1=tossControlState(target),fp1=tossControlFingerprint(target);
  try{target.blur?.();document.body?.focus?.();}catch(_e){}
  await sleep(700);
  target=tossCategoryControlByAliases([d.site,...d.aliases,...aliases])||target;
  const st2=tossControlState(target),fp2=tossControlFingerprint(target);
  const explicit=(st1.known&&st1.checked)||(st2.known&&st2.checked)||!!receipt.after_checked;
  const visualChanged=!!receipt.before_fp&&fp2!==receipt.before_fp;
  const visualStable=visualChanged&&fp1===fp2;
  const receiptVisual=!!receipt.before_fp&&!!receipt.after_fp&&receipt.after_fp!==receipt.before_fp&&fp2===receipt.after_fp;
  const selected=explicit||visualStable||receiptVisual;
  if(selected){
    txn=tossTxnSet({site:d.site,blog:d.blog,phase:'selected',on_clicks:1,off_clicks:0,on_ts:Number(receipt.ts||Date.now()),selected_ts:Date.now(),before_fp:receipt.before_fp||'',selected_fp:fp2,main_world_receipt:receipt,selection_evidence:{state1:st1,state2:st2,explicit,visual_changed:visualChanged,visual_stable:visualStable,receipt_visual:receiptVisual}});
    tossMainClickReceiptClear();
    tossResetProductScrollTop();await sleep(850);
    return{ok:true,target:d.site,state:tossCategoryState(),checked_labels:[d.site],panel,checkbox_stable:true,transaction:txn,evidence:txn.selection_evidence,collector_diag:tossCollectorDiagnostics()};
  }
  const age=Date.now()-Number(receipt.ts||0);
  if(age<6500)return{ok:false,wait:true,error:`${d.site} 클릭 후 실제 체크 표시 확인 대기`,panel,receipt,state:tossCategoryState(),diag:tossCollectorDiagnostics()};
  tossMainClickReceiptClear();
  return{ok:false,error:`${d.site} 카테고리 클릭은 실행됐지만 실제 체크 표시가 확인되지 않아 수집을 차단했습니다.`,panel,receipt,state:tossCategoryState(),diag:tossCollectorDiagnostics()};
}

async function tossUncheckTransaction(siteCategory){
  const d=tossCategoryDefByLabel(siteCategory,[]);const txn=tossTxnGet();
  if(!d||!txn||normalizeLabel(txn.site||'')!==normalizeLabel(d.site))return{ok:false,error:'토스 OFF 트랜잭션을 찾지 못했습니다.',transaction:txn};
  if(Number(txn.off_clicks||0)>0)return{ok:false,error:'토스 OFF 클릭이 이미 실행됐습니다. 중복 해제를 차단합니다.',transaction:txn};
  // v7.28: product collection scrolls the virtual list far below the filters.
  // The category finder intentionally accepts only visible main-area controls,
  // so return to the filter area BEFORE re-finding the control.  Earlier builds
  // could collect products successfully and then fail only at OFF confirmation.
  tossResetProductScrollTop();
  try{window.scrollTo({top:0,behavior:'instant'});}catch(_e){}
  await sleep(750);
  let target=tossCategoryControlByAliases([d.site,...d.aliases]);
  if(!target)return{ok:false,error:`${d.site} 수집 후 체크박스 재탐색 실패`,transaction:txn};
  const beforeFp=tossControlFingerprint(target),beforeState=tossControlState(target),beforeSig=tossRawProductSignature();
  const clickTarget=target.matches?.('input[type="checkbox"]')?target:(target.closest?.('label')||interactiveTarget(target)||target);
  try{clickTarget.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}
  await sleep(140);
  try{clickTarget.click();}catch(_e){try{clickTarget.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));}catch(__e){return{ok:false,error:`${d.site} OFF 클릭 실패`,transaction:txn};}}
  let next=Object.assign({},txn,{phase:'off_clicked',off_clicks:1,off_ts:Date.now(),pre_off_fp:beforeFp,pre_off_sig:beforeSig,pre_off_state:beforeState});tossTxnSet(next);
  const end=Date.now()+7000;let final={};
  while(Date.now()<end){
    await sleep(350);
    target=tossCategoryControlByAliases([d.site,...d.aliases])||target;
    const st=tossControlState(target),fp=tossControlFingerprint(target),sig=tossRawProductSignature();
    const explicitOff=st.known&&!st.checked;
    const returnedToBaseline=!!txn.before_fp&&fp===txn.before_fp;
    const changedFromSelected=!!txn.selected_fp&&fp!==txn.selected_fp;
    const listChanged=!!beforeSig&&sig!==beforeSig;
    final={state:st,returned_to_baseline:returnedToBaseline,changed_from_selected:changedFromSelected,list_changed:listChanged};
    if(explicitOff||returnedToBaseline||changedFromSelected||(Date.now()-next.off_ts>=1000&&listChanged)){
      next=Object.assign({},next,{phase:'off_confirmed',off_confirmed_ts:Date.now(),off_evidence:final});tossTxnSet(next);
      // leave a compact receipt, then clear the active transaction so next category can start.
      try{sessionStorage.setItem('nvb_toss_last_txn',JSON.stringify(next));}catch(_e){}
      tossTxnClear();
      tossResetProductScrollTop();
      await sleep(650);
      return{ok:true,before:[{site:d.site,checked:true}],after:[],transaction:next,evidence:final,post_uncheck_settled:true};
    }
  }
  return{ok:false,error:`${d.site} OFF 클릭 1회 후 해제 증거를 확인하지 못했습니다.`,before:[{site:d.site,checked:true}],after:[{site:d.site,checked:true}],transaction:tossTxnGet(),evidence:final};
}

function normalizeLabel(x){return (x||"").replace(/\s+/g,"").replace(/[·ㆍ]/g,"/").toLowerCase();}
function categoryTextMatch(text,category){
  const t=(text||"").toLowerCase();
  return (TOSS_CATEGORY_KEYWORDS[category]||[]).some(k=>t.includes(k.toLowerCase()));
}
function findCategoryControl(category){
  const aliases=(TOSS_CATEGORY_ALIASES[category]||[category]).map(normalizeLabel);
  const nodes=[...document.querySelectorAll("button,a,[role='tab'],[role='button'],li,span,div")].filter(vis);
  let best=null,bestScore=-1;
  for(const e of nodes){
    const t=txt(e).trim();
    if(!t || t.length>40) continue;
    const n=normalizeLabel(t);
    let sc=-1;
    for(const a of aliases){
      if(n===a) sc=Math.max(sc,100);
      else if(n.includes(a)||a.includes(n)) sc=Math.max(sc,70);
    }
    const role=(e.getAttribute("role")||"").toLowerCase();
    if(role==="tab") sc+=15;
    if(e.tagName==="BUTTON"||e.tagName==="A") sc+=8;
    if(sc>bestScore){bestScore=sc;best=e;}
  }
  return bestScore>=70?best:null;
}
async function waitForProductCards(minCount=3,timeout=9000){
  const end=Date.now()+timeout;
  while(Date.now()<end){
    const c=cards(Math.max(minCount,10));
    if(c.length>=minCount)return c;
    await sleep(300);
  }
  return cards(Math.max(minCount,10));
}
function bestScrollable(){
  let best=null,bestArea=0;
  for(const e of document.querySelectorAll("main,section,div,ul")){
    if(!vis(e))continue;
    const st=getComputedStyle(e);if(!/(auto|scroll)/.test(st.overflowY||""))continue;
    if(e.scrollHeight<=e.clientHeight+180)continue;
    const r=e.getBoundingClientRect(),area=r.width*r.height;
    if(area>bestArea){bestArea=area;best=e;}
  }
  return best;
}
async function scrollProductArea(){
  const sc=bestScrollable();
  if(sc && sc!==document.body && sc!==document.documentElement){
    const before=sc.scrollTop;sc.scrollTop=Math.min(sc.scrollHeight,sc.scrollTop+Math.max(500,sc.clientHeight*0.82));
    sc.dispatchEvent(new Event("scroll",{bubbles:true}));
    await sleep(250);
    if(sc.scrollTop>before+2)return;
  }
  window.scrollBy({top:Math.max(550,innerHeight*0.82),behavior:"instant"});
}
function findTextAnchor(label){
  if(!label)return null;
  const target=normalizeLabel(label),nodes=[...document.querySelectorAll("h1,h2,h3,h4,strong,b,p,span,div,button,a")].filter(vis);
  let best=null,bestScore=-1;
  for(const e of nodes){
    const raw=txt(e).trim();if(!raw||raw.length>100)continue;
    const n=normalizeLabel(raw);let sc=-1;
    if(n===target)sc=120;else if(n.includes(target))sc=90;else continue;
    const r=e.getBoundingClientRect();
    if(raw.length<=25)sc+=10;if(r.width<900)sc+=3;
    if(sc>bestScore){bestScore=sc;best=e;}
  }
  return best;
}
async function ensureCoupangRankingAnchor(label="쿠팡 랭킹순",timeout=18000){
  const end=Date.now()+timeout;let lastY=-1,stuck=0;
  while(Date.now()<end){
    const a=findTextAnchor(label);
    if(a){
      try{a.scrollIntoView({block:"start",behavior:"instant"});}catch(e){}
      await sleep(650);
      const r=a.getBoundingClientRect();
      return{ok:true,label:txt(a).trim(),docY:r.top+window.scrollY};
    }
    const y=window.scrollY;if(y===lastY)stuck++;else stuck=0;lastY=y;
    await scrollProductArea();await sleep(500);
    if(stuck>=5)break;
  }
  return{ok:false,error:"쿠팡 카테고리에서 '"+label+"' 문구를 찾지 못했습니다."};
}
function tossMainScrollContainer(){
  const roots=[...document.querySelectorAll('main,[role="main"]')].filter(vis);
  const cand=[];
  for(const root of roots){
    if(root.scrollHeight>root.clientHeight+120)cand.push(root);
    for(const e of root.querySelectorAll('section,div,ul')){
      if(!vis(e))continue;const st=getComputedStyle(e);if(!/(auto|scroll)/.test(st.overflowY||''))continue;
      if(e.scrollHeight<=e.clientHeight+120)continue;cand.push(e);
    }
  }
  cand.sort((a,b)=>{const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();return (br.width*br.height)-(ar.width*ar.height);});
  return cand[0]||null;
}
async function scrollTossProductArea(round=0){
  const sc=tossMainScrollContainer();
  if(sc){
    const before=sc.scrollTop;sc.scrollTop=Math.min(sc.scrollHeight,sc.scrollTop+Math.max(450,sc.clientHeight*0.75));
    sc.dispatchEvent(new Event('scroll',{bubbles:true}));await sleep(300);
    if(sc.scrollTop>before+2)return true;
  }
  const before=window.scrollY;window.scrollBy({top:Math.max(500,innerHeight*0.72),behavior:'instant'});await sleep(300);
  return window.scrollY>before+2;
}
function tossResetProductScrollTop(){
  try{const sc=tossMainScrollContainer();if(sc){sc.scrollTop=0;sc.dispatchEvent(new Event('scroll',{bubbles:true}));}}catch(_e){}
  try{window.scrollTo({top:0,behavior:'instant'});}catch(_e){}
}
async function tossTryLoadMoreOrNext(){
  const nodes=[...document.querySelectorAll('button,a,[role="button"]')].filter(e=>vis(e)&&tossMainAreaElement(e));
  let best=null,bestScore=-1;
  for(const e of nodes){
    if(e.disabled||e.getAttribute?.('aria-disabled')==='true')continue;
    const t=txt(e).replace(/\s+/g,' ').trim();
    const aria=(e.getAttribute?.('aria-label')||'').replace(/\s+/g,' ').trim();
    let sc=-1;
    if(/^(더보기|상품 더보기|결과 더보기)$/.test(t))sc=150;
    else if(/^(다음|다음 페이지|다음페이지)$/.test(t))sc=140;
    else if(/다음\s*페이지/.test(aria))sc=135;
    if(sc<0)continue;
    const r=e.getBoundingClientRect();if(r.top<innerHeight*0.35)sc-=25;
    if(sc>bestScore){bestScore=sc;best=e;}
  }
  if(!best)return{clicked:false};
  try{best.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}
  await sleep(180);
  try{best.click();}catch(_e){try{best.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));}catch(__e){return{clicked:false};}}
  await sleep(1200);
  return{clicked:true,label:txt(best).trim()||best.getAttribute?.('aria-label')||''};
}
async function collectTossCardsWhileChecked(limit=30,siteCategory=''){
  const wanted=tossCategoryDefByLabel(siteCategory,[]);
  const txn=tossTxnGet();
  if(!wanted||!txn||normalizeLabel(txn.site||'')!==normalizeLabel(wanted.site)||!['selected','on_clicked'].includes(txn.phase)){
    return{ok:false,cards:[],error:`${wanted?.site||siteCategory}: ON 트랜잭션이 확인되지 않아 수집을 시작하지 않습니다.`,rounds:0,transaction:txn,diag:tossCollectorDiagnostics()};
  }
  const map=new Map();let lastSize=-1,noGrowth=0,rounds=0;
  const started=Date.now(),deadline=started+90000;
  // The user's required behavior is strict: once ON was clicked, keep it ON
  // throughout the entire collect phase. Never click the category here.
  await sleep(2200);
  while(Date.now()<deadline&&rounds<70){
    rounds++;
    const nowTxn=tossTxnGet();
    if(!nowTxn||normalizeLabel(nowTxn.site||'')!==normalizeLabel(wanted.site)||Number(nowTxn.off_clicks||0)>0){
      return{ok:false,cards:[...map.values()].slice(0,limit),error:`수집 중 ${wanted.site} 트랜잭션이 종료/변경되었습니다.`,rounds,transaction:nowTxn,diag:tossCollectorDiagnostics()};
    }
    const batch=cards(Math.max(limit*6,220));
    for(const c of batch){
      // v7.28: a popularity slot is a unique PRODUCT, not a product/price pair.
      // Sharelink can show commission, promo, original and selling prices around
      // the same product.  Counting those as separate cards can create a false
      // 30/30 that later collapses below 30 in Python name de-duplication.
      const key=normalizeLabel(c.name||'');
      if(!c.name||!c.price||!key)continue;
      if(!map.has(key))map.set(key,c);
      else{
        const old=map.get(key)||{};
        const oldScore=(old.url?3:0)+(old.image_url?2:0)+(old.text?.length?1:0);
        const newScore=(c.url?3:0)+(c.image_url?2:0)+(c.text?.length?1:0);
        if(newScore>oldScore)map.set(key,c);
      }
    }
    if(map.size>=limit){
      const doneTxn=Object.assign({},nowTxn,{phase:'collected',collected_count:map.size,collected_ts:Date.now(),collect_rounds:rounds});tossTxnSet(doneTxn);
      return{ok:true,cards:[...map.values()].slice(0,limit),rounds,transaction:doneTxn,diag:tossCollectorDiagnostics(),elapsed_ms:Date.now()-started};
    }
    if(map.size===lastSize)noGrowth++;else noGrowth=0;
    lastSize=map.size;
    const moved=await scrollTossProductArea(rounds);
    await sleep(rounds<10?1200:900);
    if(noGrowth>=5){const more=await tossTryLoadMoreOrNext();if(more.clicked){noGrowth=0;await sleep(1100);continue;}}
    if(!moved&&noGrowth>=12){tossResetProductScrollTop();await sleep(1000);noGrowth=0;}
  }
  const finalTxn=Object.assign({},tossTxnGet()||txn,{phase:'collect_failed',collected_count:map.size,collect_failed_ts:Date.now(),collect_rounds:rounds});tossTxnSet(finalTxn);
  return{ok:false,cards:[...map.values()].slice(0,limit),error:`${wanted.site}: 필터 ON을 유지한 채 ${Math.round((Date.now()-started)/1000)}초 수집했지만 ${map.size}/${limit}개만 인식했습니다.`,rounds,transaction:finalTxn,diag:tossCollectorDiagnostics(),elapsed_ms:Date.now()-started};
}

async function collectCardsWithScroll(limit=30,category=null,strictCategory=false,minDocY=0){
  const map=new Map();let noGrowth=0,last=0;
  for(let i=0;i<30;i++){
    const batch=cards(Math.max(limit*3,100));
    for(const c of batch){
      if(minDocY && Number(c.docY||0)<minDocY-20)continue;
      if(strictCategory && category && !categoryTextMatch(c.name+" "+c.text,category))continue;
      const key=(c.name||"").toLowerCase()+"|"+c.price;
      if(!map.has(key))map.set(key,c);
    }
    if(map.size>=limit)break;
    if(map.size===last)noGrowth++;else noGrowth=0;
    last=map.size;
    if(noGrowth>=6)break;
    await scrollProductArea();await sleep(800);
  }
  return [...map.values()].slice(0,limit);
}

async function tossGoBestRankingCategory(category){
  if(tossLogin())return{status:"login_required"};
  sessionStorage.setItem("nvb_toss_best_category",category||"");
  sessionStorage.setItem("nvb_toss_category_selected","0");

  // Ensure left-menu Best Ranking page.
  let best=clickableFromText("베스트 랭킹");
  if(!best){
    // Sometimes the "링크" accordion is collapsed.
    const linkMenu=clickableFromText("링크");
    if(linkMenu){try{linkMenu.click();}catch(e){} await sleep(350);}
    best=clickableFromText("베스트 랭킹");
  }
  if(!best)return{status:"error",error:"토스 왼쪽 메뉴의 '베스트 랭킹'을 찾지 못했습니다."};

  try{best.click();}catch(e){}
  await sleep(900);
  await waitForProductCards(2,5000);

  if(category){
    const control=findCategoryControl(category);
    if(control){
      try{control.click();}catch(e){}
      sessionStorage.setItem("nvb_toss_category_selected","1");
      await sleep(800);
      await waitForProductCards(2,5000);
      return{status:"ok",category_selected:true,category};
    }
    // v7.13: a missing category button is an error. Never substitute the
    // overall Best Ranking page or infer the category from product-name keywords.
    return{status:"error",error:"토스 베스트 랭킹 카테고리 버튼을 찾지 못했습니다: "+category,category_selected:false,category};
  }
  return{status:"ok",category_selected:false,category:null};
}

async function tossGoBestRanking(){
  return await tossGoBestRankingCategory(null);
}


const CATEGORY_NOISE=[
 "로그인","회원가입","장바구니","마이","고객센터","주문","배송조회","검색","홈","최근본상품",
 "이벤트","쿠폰","혜택","광고","브랜드","판매자","더보기","전체보기","설정","가이드","의견 남기기",
 "링크 관리","상품 조회","API 키 발급","내 정보","정산 내역","실적 대시보드"
];
function categoryLabelOK(t){
  t=(t||"").replace(/\s+/g," ").trim();
  if(t.length<2||t.length>28)return false;
  if(CATEGORY_NOISE.some(x=>t===x||t.startsWith(x+" ")))return false;
  if(/^\d+$/.test(t)||/원$/.test(t)||/%/.test(t))return false;
  if(/로그인|회원|장바구니|배송|주문|검색창|고객센터/.test(t))return false;
  return /[A-Za-z가-힣]/.test(t);
}
function absoluteHref(e){
  try{
    const a=e.closest("a[href]")||e.querySelector?.("a[href]")||e;
    const h=a?.getAttribute?.("href")||"";
    if(!h||h.startsWith("javascript:")||h==="#")return "";
    return new URL(h,location.href).href;
  }catch(e){return "";}
}
function categoryScore(e,label,url){
  let s=0;
  const role=(e.getAttribute?.("role")||"").toLowerCase();
  const cls=String(e.className||"").toLowerCase();
  const u=(url||"").toLowerCase();
  if(e.tagName==="A")s+=8;
  if(role==="tab"||role==="menuitem")s+=12;
  if(/category|cate|department|menu|gnb|lnb|best/.test(cls))s+=10;
  if(/categor|department|best|display|section|menu/.test(u))s+=12;
  if(label.length>=3&&label.length<=12)s+=4;
  if(e.closest("nav,aside,[role='navigation']"))s+=8;
  return s;
}
async function revealCategoryUI(siteName){
  if(siteName==="토스쇼핑"){
    // v7.18: Toss categories are the checkboxes under 링크 > 상품 조회.
    const linkMenu=clickableFromText("링크");
    if(linkMenu){try{linkMenu.click();}catch(e){} await sleep(250);}
    const lookup=clickableFromText("상품 조회")||clickableFromText("상품조회");
    if(lookup){try{lookup.click();}catch(e){} await sleep(1000);}
    return;
  }
  // Naver/Coupang: try common visible category/menu controls without using a search box.
  const labels=["카테고리","전체 카테고리","전체카테고리","쇼핑 카테고리","상품 카테고리"];
  for(const l of labels){
    const x=clickableFromText(l);
    if(x){try{x.click();}catch(e){} await sleep(600);break;}
  }
}
async function discoverNativeCategories(limit=30){
  const siteName=site();
  await revealCategoryUI(siteName);
  // Scroll a little so lazy navigation sections/tabs are mounted.
  window.scrollTo({top:0,behavior:"instant"});
  await sleep(300);
  const cand=[];
  const nodes=[...document.querySelectorAll("a[href],button,[role='tab'],[role='menuitem'],[role='button'],nav li,aside li")];
  for(const e of nodes){
    if(!vis(e))continue;
    const label=txt(e).replace(/\s+/g," ").trim();
    if(!categoryLabelOK(label))continue;
    const url=absoluteHref(e);
    const score=categoryScore(e,label,url);
    if(score<8)continue;
    cand.push({label,url,score});
  }
  const map=new Map();
  for(const c of cand){
    const k=c.label.toLowerCase();
    const old=map.get(k);
    if(!old||old.score<c.score)map.set(k,c);
  }
  let arr=[...map.values()];
  arr.sort((a,b)=>b.score-a.score||a.label.localeCompare(b.label));
  // Prefer entries having actual URLs; tabs without URL are still allowed for Toss.
  const withUrl=arr.filter(x=>x.url);
  const noUrl=arr.filter(x=>!x.url);
  arr=[...withUrl,...noUrl];
  return arr.slice(0,limit);
}
async function collectCategoryProducts(limit=6){
  // Category pages should be ranked/browse pages; collect visible cards only.
  const arr=await collectCardsWithScroll(Math.max(limit,12),null,false);
  return arr.slice(0,limit);
}
function detailImageRecord(im,tier=0){
  if(!im)return null;
  const r=im.getBoundingClientRect();
  const nw=Number(im.naturalWidth||0),nh=Number(im.naturalHeight||0);
  let ancestor="",node=im;
  for(let i=0;i<9&&node;i++,node=node.parentElement){ancestor+=" "+String(node.className||"")+" "+String(node.id||"")+" "+(node.getAttribute?.("aria-label")||"");}
  const detailZone=/(productdetail|product-detail|product_detail|productdescription|product-description|detail-content|detail_content|description|상품상세|상품설명)/i.test(ancestor);
  const srcset=(im.getAttribute("srcset")||im.getAttribute("data-srcset")||"").split(',').map(x=>x.trim().split(/\s+/)[0]).filter(Boolean);
  let u=im.currentSrc||im.getAttribute("data-src")||im.getAttribute("data-original")||im.getAttribute("data-lazy-src")||im.getAttribute("data-zoom-image")||im.getAttribute("data-image")||im.src||srcset[srcset.length-1]||"";
  if(!u)return null;
  const w=Math.max(r.width,nw,Number(im.getAttribute("width")||0)),h=Math.max(r.height,nh,Number(im.getAttribute("height")||0));
  // Detail-description URLs often exist in data-src before the image is rendered.
  // Keep them as download candidates even when lazy-load dimensions are still 0.
  if(!detailZone && (Math.max(w,nw)<160||Math.max(h,nh)<160))return null;
  const meta=((im.alt||"")+" "+(im.title||"")+" "+String(im.className||"")+" "+u+ancestor).toLowerCase();
  if(/(logo|icon|sprite|badge|banner|advert|tracking|pixel|avatar|profile|coupon|delivery|pay|qr)/i.test(meta))return null;
  if(/(recommend|related|similar|recent|also[-_ ]?buy|together|ranking|best[-_ ]?item|other[-_ ]?product|연관|추천상품|함께본|최근본)/i.test(ancestor.toLowerCase()))return null;
  const a=im.closest?.("a[href]");
  if(a){
    try{
      const hu=new URL(a.href,location.href),cu=new URL(location.href);
      const productPath=/(\/vp\/products\/|\/products?\/|\/goods\/|\/items?\/|\/t\/)/i;
      if(productPath.test(hu.pathname)&&productPath.test(cu.pathname)&&hu.pathname!==cu.pathname)return null;
    }catch(e){}
  }
  const ew=Math.max(w,detailZone?800:1),eh=Math.max(h,detailZone?800:1);
  const ratio=ew/Math.max(1,eh);if(!detailZone&&ratio>5.5)return null;
  const renderOnly=/^(data:|blob:)/i.test(u);
  const role=detailZone?'detail_description_dom':'product_gallery_or_main';
  return {url:u,width:Math.round(w),height:Math.round(h),alt:im.alt||"",render_only:renderOnly,long_detail:detailZone&&ratio<0.20,role,detail_zone:detailZone,score:Math.round(Math.min(ew,2200)*Math.min(eh,12000))+(detailZone?12:0)*1000000000+tier*1000000000};
}
function scanDetailImages(limit=24){
  const arr=[],seen=new Set();
  const selectors=[
    ["[class*='gallery'] img",8],["[class*='product-image'] img",8],["[class*='productImage'] img",8],
    ["[class*='detail'] img",6],["[class*='product'] img",5],["main img",3],["article img",2],["[class*='image'] img",1],["img",0]
  ];
  for(const [sel,tier] of selectors){
    let ims=[];try{ims=[...document.querySelectorAll(sel)];}catch(e){}
    for(const im of ims){
      const rec=detailImageRecord(im,tier);if(!rec||seen.has(rec.url))continue;
      seen.add(rec.url);arr.push(rec);
    }
  }
  arr.sort((a,b)=>b.score-a.score);
  return arr.slice(0,limit);
}
async function collectDetailImagesWithScroll(limit=12,rounds=7,waitMs=850){
  const map=new Map();
  const add=()=>{for(const x of scanDetailImages(Math.max(limit*4,40))){const k=x.url||(`render:${x.width}x${x.height}:${x.alt||''}`);const old=map.get(k);if(!old||old.score<x.score)map.set(k,x);}};
  const startY=window.scrollY;
  // Expand the description before checking naturalWidth/naturalHeight. Coupang
  // lazy-loads many images only after the detail section approaches viewport.
  for(const b of [...document.querySelectorAll('button,a,[role="button"]')]){
    const t=(b.innerText||'').replace(/\s+/g,' ');
    if(/상품\s*(상세|정보).*더보기|상세.*더보기|펼쳐보기/.test(t)){try{b.click();await sleep(450)}catch(e){}}
  }
  const detail=[...document.querySelectorAll('#productDetail,#productDescription,.product-detail-content-inside,.product-detail-content,[class*="product-detail"],[class*="detail-content"],[class*="description"]')]
    .filter(e=>{try{const r=e.getBoundingClientRect();return r.width>300&&r.height>300}catch(_){return false}})
    .sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
  if(detail){try{detail.scrollIntoView({block:'start',behavior:'instant'});await sleep(Math.max(700,Number(waitMs||850)))}catch(e){}}
  add();
  let stagnant=0,lastY=-1;
  for(let i=0;i<Math.max(4,rounds);i++){
    const step=Math.max(600,innerHeight*0.78);
    const before=window.scrollY;
    window.scrollBy({top:step,behavior:"instant"});
    await sleep(Math.max(700,Number(waitMs||850)));
    add();
    const after=window.scrollY;
    stagnant=(after<=before+2||after===lastY)?stagnant+1:0;lastY=after;
    if(stagnant>=2)break;
  }
  // One final scan after lazy resources settle.
  await sleep(Math.max(500,Number(waitMs||850)));add();
  try{window.scrollTo({top:startY,behavior:"instant"});}catch(e){}
  const arr=[...map.values()];arr.sort((a,b)=>b.score-a.score);
  return arr.slice(0,limit);
}


function interactiveTarget(e){
 let n=e;
 for(let i=0;n&&i<7;i++,n=n.parentElement){
   const role=(n.getAttribute?.("role")||"").toLowerCase();
   const cur=(getComputedStyle(n).cursor||"").toLowerCase();
   if(n.tagName==="A"||n.tagName==="BUTTON"||["button","tab","menuitem","option"].includes(role)||typeof n.onclick==="function"||cur==="pointer")return n;
 }
 return e;
}
async function robustClick(e,waitMs=700){
 if(!e)return{ok:false};const target=interactiveTarget(e),before=location.href;
 try{target.scrollIntoView?.({block:"center",behavior:"instant"});}catch(_e){}
 await sleep(120);
 try{target.click();}catch(err){
   try{target.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,view:window}));}catch(e2){return{ok:false,error:String(err)}}
 }
 await sleep(waitMs);
 return{ok:true,navigated:location.href!==before,url:location.href,target:txt(target).trim()};
}
function routeDebug(extra={}){
 const body=(document.body?.innerText||"").replace(/\s+/g," ");
 return Object.assign({url:location.href,title:document.title||"",site:site(),body_head:body.slice(0,800),card_count:genericCards(40).length,naver_rank_count:site()==="네이버쇼핑"?cards(80).length:null},extra||{});
}
function selectedControl(e){
  if(!e)return false;
  const aria=(e.getAttribute?.("aria-selected")||e.getAttribute?.("aria-current")||e.getAttribute?.("data-selected")||"").toLowerCase();
  if(["true","page","selected","active"].includes(aria))return true;
  const cls=(String(e.className||"")+" "+String(e.parentElement?.className||"")).toLowerCase();
  return /(^|[ _-])(active|selected|checked|current|on)([ _-]|$)/.test(cls);
}
function controlByAliases(labels){
  const aliases=(labels||[]).filter(Boolean).map(normalizeLabel);
  if(!aliases.length)return null;
  const nodes=[...document.querySelectorAll("button,a,[role='tab'],[role='button'],[role='menuitem'],[role='option'],li,span,div")].filter(vis);
  let best=null,bestScore=-1;
  for(const e of nodes){
    const raw=txt(e).trim();if(!raw||raw.length>55)continue;
    const n=normalizeLabel(raw);let sc=-1;
    for(const a of aliases){
      if(n===a)sc=Math.max(sc,140);
      else if(a.length>=3 && n.startsWith(a) && n.length<=a.length+10)sc=Math.max(sc,92);
      else if(n.length>=3 && a.startsWith(n) && a.length<=n.length+6)sc=Math.max(sc,78);
    }
    if(sc<0)continue;
    const it=interactiveTarget(e),role=(it.getAttribute?.("role")||"").toLowerCase();
    if(role==="tab"||role==="menuitem"||role==="option")sc+=25;
    if(it.tagName==="BUTTON"||it.tagName==="A")sc+=18;
    if(it!==e)sc+=8;
    if(e.children.length===0)sc+=6;
    if(selectedControl(it)||selectedControl(e))sc+=10;
    const rr=it.getBoundingClientRect();if(rr.width>20&&rr.height>12&&rr.width<600)sc+=4;
    if(sc>bestScore){bestScore=sc;best=it;}
  }
  return bestScore>=78?best:null;
}
async function clickControlAliases(labels,waitMs=700){
  const e=controlByAliases(labels);if(!e)return{found:false};
  const label=txt(e).replace(/\s+/g," ").trim();
  if(selectedControl(e))return{found:true,selected:true,label};
  // Coupang category anchors can occasionally expose a legacy http:// href.
  // Upgrade the clicked anchor before navigation so Akamai never sees the
  // avoidable HTTP -> HTTPS redirect in an automated category sequence.
  if(site()==="쿠팡"){
    try{
      const a=e.matches?.("a[href]")?e:(e.closest?.("a[href]")||e.querySelector?.("a[href]"));
      if(a&&/^http:\/\//i.test(a.href||a.getAttribute("href")||""))a.href=String(a.href||a.getAttribute("href")).replace(/^http:\/\//i,"https://");
    }catch(_e){}
  }
  const rc=await robustClick(e,waitMs);if(!rc.ok)return{found:true,error:rc.error||"click failed",label};
  return{found:true,selected:selectedControl(controlByAliases(labels)),label,navigated:rc.navigated,url:rc.url};
}
function pageLooksLikeCategory(label){
  const n=normalizeLabel(label);if(!n)return false;
  const heads=[...document.querySelectorAll("h1,h2,h3,[aria-current='page'],[aria-selected='true'],[class*='selected'],[class*='active']")].filter(vis);
  return heads.some(e=>normalizeLabel(txt(e))===n || normalizeLabel(txt(e)).startsWith(n));
}
function sameRouteUrl(a,b){
  try{
    const x=new URL(a,location.href),y=new URL(b,location.href);
    const xp=(x.pathname.replace(/\/+$/g,"")||"/");
    const yp=(y.pathname.replace(/\/+$/g,"")||"/");
    return x.origin===y.origin && xp===yp && x.search===y.search;
  }catch(e){return String(a||"").replace(/#.*$/,"")===String(b||"").replace(/#.*$/,"");}
}
function pageRenderState(){
  const body=(document.body?.innerText||"").replace(/\s+/g," ").trim();
  return {ready:document.readyState,body_len:body.length,body_head:body.slice(0,300)};
}
async function openFixedCategory(siteName,siteCategory,parentCategory,aliases,fallbackUrl,rankingAnchor="",parentFallbackUrl=""){
  if(blocked())return{status:"blocked"};
  if(siteName==="토스쇼핑"&&tossLogin())return{status:"login_required"};
  const targetAliases=[siteCategory,...(aliases||[])].filter(Boolean);

  // Preserve progress for user-defined multi-click paths across SPA/full-page navigation.
  const routeId=[siteName,parentCategory||"",siteCategory||""].join("|");
  try{
    if(sessionStorage.getItem("nvb_fixed_route_id")!==routeId){
      sessionStorage.setItem("nvb_fixed_route_id",routeId);
      sessionStorage.removeItem("nvb_fixed_naver_parent");
      sessionStorage.removeItem("nvb_fixed_toss_best");
      // v7.23 every Toss category starts from a freshly reloaded /home. Clear
      // content-script bookkeeping as well; otherwise the old accordion flag or
      // transaction can make category #2..#6 behave differently from category #1.
      if(siteName==="토스쇼핑"){
        tossTxnClear();
        sessionStorage.removeItem('nvb_toss_category_panel_clicked');
        sessionStorage.removeItem('nvb_toss_last_txn');
        sessionStorage.setItem('nvb_toss_fresh_route_started',String(Date.now()));
      }
    }
  }catch(e){}

  if(siteName==="쿠팡"){
    fallbackUrl=String(fallbackUrl||"").replace(/^http:\/\//i,"https://");
    parentFallbackUrl=String(parentFallbackUrl||"").replace(/^http:\/\//i,"https://");
    // v7.17: if we already reached the configured direct category URL, never
    // navigate to that same URL again.  Wait for Coupang's delayed DOM to mount,
    // then let the collect stage locate "쿠팡 랭킹순".
    if(fallbackUrl && sameRouteUrl(location.href,fallbackUrl)){
      const rs=pageRenderState();
      if(rs.body_len<120){
        return{status:"route_progress",clicked_label:siteCategory,detail:"쿠팡 카테고리 페이지 렌더링 대기(동일 URL 재로드 금지)",debug:routeDebug({direct_category_url:true,render_state:rs})};
      }
      return{status:"ok",category_confirmed:true,clicked_label:siteCategory,direct_category_url:true,debug:routeDebug({direct_category_url:true,render_state:rs})};
    }
    if(pageLooksLikeCategory(siteCategory) && cards(2).length)return{status:"ok",category_confirmed:true,clicked_label:siteCategory};
    const menu=controlByAliases(["카테고리","전체 카테고리","전체카테고리"]);
    if(menu&&!selectedControl(menu)){await robustClick(menu,450);}
    const r=await clickControlAliases(targetAliases,650);
    if(r.found){
      if(pageLooksLikeCategory(siteCategory)||selectedControl(controlByAliases(targetAliases)))return{status:"ok",category_confirmed:true,clicked_label:r.label};
      return{status:"route_progress",clicked_label:r.label};
    }
    if(fallbackUrl && !sameRouteUrl(location.href,fallbackUrl))return{status:"navigate",url:fallbackUrl};
    return{status:"route_progress",clicked_label:siteCategory,detail:"쿠팡 카테고리 화면 렌더링 대기",debug:routeDebug({fallback_url:fallbackUrl||""})};
  }

  if(siteName==="네이버쇼핑"){
    // User-defined source: 쇼핑 BEST > 베스트상품 > 많이 본 상품.
    // entry_url already opens 많이 본 BEST, then select the requested category only.
    const body=document.body?.innerText||"";
    if(!/많이\s*본\s*BEST|많이\s*본\s*상품/.test(body)){
      const best=controlByAliases(["베스트"]);if(best){try{best.click();}catch(e){} return{status:"route_progress"};}
    }
    if(parentCategory){
      let parentDone=false;
      try{parentDone=sessionStorage.getItem("nvb_fixed_naver_parent")===parentCategory;}catch(e){}
      const parent=controlByAliases([parentCategory]);
      if(!parentDone){
        if(parent && (selectedControl(parent)||pageLooksLikeCategory(parentCategory))){
          try{sessionStorage.setItem("nvb_fixed_naver_parent",parentCategory);}catch(e){}
          parentDone=true;
        }else if(parent){
          // Store the completed step BEFORE the click; navigation can close the message port.
          try{sessionStorage.setItem("nvb_fixed_naver_parent",parentCategory);}catch(e){}
          const pc=await robustClick(parent,1100);
          return{status:"route_progress",clicked_label:parentCategory,debug:routeDebug({parent_click:pc})};
        }else{
          if(parentFallbackUrl){
            try{sessionStorage.removeItem("nvb_fixed_naver_parent");}catch(e){}
            return{status:"navigate",url:parentFallbackUrl,detail:`네이버 상위 카테고리 '${parentCategory}' 직접 진입 후 하위 카테고리 재확인`,debug:routeDebug({parent_fallback:true})};
          }
          return{status:"route_progress",detail:`네이버 상위 카테고리 '${parentCategory}' 버튼 렌더링 대기`,debug:routeDebug()};
        }
      }
      const beforeUrl=location.href,beforeSig=(document.body?.innerText||"").slice(0,3000);
      const child=await clickControlAliases(targetAliases,1200);
      if(child.found){
        const now=controlByAliases(targetAliases),urlChanged=location.href!==beforeUrl;
        const enoughCards=naverRankCards(40).length>=10 || naverLooseCards(40).length>=10;
        const bodyChanged=(document.body?.innerText||"").slice(0,3000)!==beforeSig;
        if(selectedControl(now)||pageLooksLikeCategory(siteCategory)||(enoughCards&&(urlChanged||child.selected||bodyChanged))){
          try{sessionStorage.removeItem("nvb_fixed_naver_parent");}catch(e){}
          return{status:"ok",category_confirmed:true,clicked_label:child.label,debug:routeDebug({urlChanged,bodyChanged})};
        }
        return{status:"route_progress",clicked_label:child.label,debug:routeDebug({urlChanged,bodyChanged})};
      }
      return{status:"route_progress",clicked_label:parentCategory,detail:`네이버 '${parentCategory} > ${siteCategory}' 하위 카테고리 렌더링 대기`,debug:routeDebug()};
    }
    const beforeUrl=location.href,beforeSig=(document.body?.innerText||"").slice(0,3000);
    const r=await clickControlAliases(targetAliases,1200);
    if(r.found){
      const now=controlByAliases(targetAliases),urlChanged=location.href!==beforeUrl;
      const enoughCards=naverRankCards(40).length>=10 || naverLooseCards(40).length>=10;
      const bodyChanged=(document.body?.innerText||"").slice(0,3000)!==beforeSig;
      if(selectedControl(now)||pageLooksLikeCategory(siteCategory)||(enoughCards&&(urlChanged||r.selected||bodyChanged)))return{status:"ok",category_confirmed:true,clicked_label:r.label,debug:routeDebug({urlChanged,bodyChanged})};
      return{status:"route_progress",clicked_label:r.label,debug:routeDebug({urlChanged,bodyChanged})};
    }
    if(fallbackUrl)return{status:"navigate",url:fallbackUrl,debug:routeDebug({fallback:true})};
    return{status:"route_progress",detail:"네이버 카테고리 컨트롤 렌더링 대기: "+siteCategory,debug:routeDebug()};
  }

  if(siteName==="토스쇼핑"){
    // v7.19 HARD GATE: 링크 > 상품 조회 > (카테고리 영역 펼침) > 대상 1개 체크.
    // Product Lookup confirmation and checkbox discovery are separate because
    // Toss lazily renders/collapses the category filter UI.
    if(tossLogin())return{status:"login_required"};

    const enter=await tossEnterProductLookup();
    if(!enter.ok){
      if(enter.login_required)return{status:"login_required"};
      if(enter.navigate_url)return{status:"navigate",url:enter.navigate_url,clicked_label:'상품 조회',detail:'토스 상품 조회 메뉴 href 직접 이동',debug:routeDebug({enter,toss_category_state:tossCategoryState()})};
      return{status:"route_progress",clicked_label:enter.error?.includes('상품 조회')?'상품 조회':'링크',detail:enter.error||'토스 상품 조회 진입 대기',debug:routeDebug({enter,toss_category_state:tossCategoryState()})};
    }

    const d=tossCategoryDefByLabel(siteCategory,targetAliases);
    const panel=await tossEnsureCategoryPanel(d?[d.site,...d.aliases,...targetAliases]:targetAliases);
    if(!panel.ok)return{status:"route_progress",clicked_label:"카테고리",detail:`토스 카테고리 필터 렌더링 대기: ${siteCategory}`,toss_product_lookup_confirmed:true,debug:routeDebug({panel,toss_category_state:tossCategoryState()})};

    const sel=await tossSelectOnlyCategory(siteCategory,targetAliases);
    if(!sel.ok){
      if(sel.needs_main_world_click)return{status:"toss_category_click_required",clicked_label:siteCategory,detail:sel.error,toss_product_lookup_confirmed:true,site_category_label:siteCategory,category_aliases:sel.target_aliases||targetAliases,debug:routeDebug({toss_category_state:tossCategoryState(),selection:sel})};
      if(sel.wait)return{status:"route_progress",clicked_label:"카테고리",detail:sel.error,toss_product_lookup_confirmed:true,debug:routeDebug({toss_category_state:tossCategoryState(),selection:sel})};
      return{status:"error",error:sel.error,toss_product_lookup_confirmed:true,debug:routeDebug({toss_category_state:tossCategoryState(),selection:sel})};
    }
    return{
      status:"ok",category_confirmed:true,toss_product_lookup_confirmed:true,
      toss_single_checkbox_confirmed:true,clicked_label:sel.target||siteCategory,
      toss_checked_categories:sel.checked_labels||[],
      debug:routeDebug({toss_route_stage:"ready_to_collect",toss_category_state:tossCategoryState(),selection:sel,panel})
    };
  }
  return{status:"error",error:"지원하지 않는 사이트"};
}

async function performSearch(s,q,action=null,categoryLabel="",opts={}){
 if(action==="open_fixed_category"){
   return await openFixedCategory(
     s,opts.site_category_label||categoryLabel||q,
     opts.parent_category_label||"",opts.category_aliases||[],opts.fallback_url||"",opts.ranking_anchor||"",opts.parent_fallback_url||""
   );
 }
 if(action==="click_category"){
   await revealCategoryUI(s);
   const target=clickableFromText(categoryLabel);
   if(!target)return{status:"error",error:"카테고리 버튼을 찾지 못함: "+categoryLabel};
   try{target.click();}catch(e){return{status:"error",error:String(e)}}
   await sleep(1000);
   return{status:"ok"};
 }
 if(blocked())return{status:"blocked"};
 if(s==="토스쇼핑"){
   if(tossLogin())return{status:"login_required"};
   // v7.18 popularity discovery never uses Best Ranking. Fixed 540 tasks are
   // routed through 링크 > 상품 조회 > single category checkbox.
   if(q==="__BEST_RANKING__"||q.startsWith("__TOSS_BEST__::")){
     return{status:"error",error:"v7.18 인기상품 수집은 베스트 랭킹을 사용하지 않습니다. 링크 > 상품 조회 단독 체크 방식만 사용합니다."};
   }

   const nav=await tossGoProductLookup();
   if(nav.status==="login_required")return nav;
   if(nav.status==="ranking_only"){
     return{status:"ranking_only"};
   }
   if(nav.status!=="ok" || !nav.input){
     return{status:"error",error:"토스 '상품 조회' 화면에서 검색 입력창을 찾지 못했습니다."};
   }
   const inp=nav.input;
   setNativeValue(inp,q);inp.focus();
   inp.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",code:"Enter",keyCode:13,bubbles:true}));
   inp.dispatchEvent(new KeyboardEvent("keyup",{key:"Enter",code:"Enter",keyCode:13,bubbles:true}));
   const form=inp.form;if(form){try{form.requestSubmit();}catch(e){}}
   // Some SPA screens need a visible search button click.
   const sb=clickableFromText("검색");
   if(sb){try{sb.click();}catch(e){}}
   return{status:"ok"};
 }
 if(s==="쿠팡"){
   const inp=findInput(["input#headerSearchKeyword","input[name='q']","input[placeholder*='상품']","input[placeholder*='검색']","input[type='search']"]);
   if(!inp)return{status:"error",error:"쿠팡 홈 검색창을 찾지 못했습니다."};
   try{inp.scrollIntoView({block:"center",behavior:"instant"});}catch(_e){}
   inp.focus();
   setNativeValue(inp,"");
   inp.dispatchEvent(new Event("input",{bubbles:true}));
   await sleep(120);
   setNativeValue(inp,q);
   inp.dispatchEvent(new Event("input",{bubbles:true}));
   inp.dispatchEvent(new Event("change",{bubbles:true}));
   await sleep(180);
   const form=inp.form;
   if(form){try{form.requestSubmit();return{status:"ok",method:"homepage_search_form"};}catch(_e){}}
   inp.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",code:"Enter",keyCode:13,bubbles:true}));
   inp.dispatchEvent(new KeyboardEvent("keyup",{key:"Enter",code:"Enter",keyCode:13,bubbles:true}));
   if(clickText(["검색"]))return{status:"ok",method:"homepage_search_button"};
   return{status:"ok",method:"homepage_search_enter"};
 }
 return{status:"ok"};
}

// v8.00 supplemental trend collectors -------------------------------------------------
function trendNorm(s){return String(s||"").replace(/\s+/g," ").trim();}
function trendLabelText(el){
  if(!el)return"";
  let t=trendNorm(el.innerText||el.textContent||"");
  if(!t&&el.id){try{const l=document.querySelector(`label[for="${CSS.escape(el.id)}"]`);if(l)t=trendNorm(l.innerText||l.textContent||"");}catch(_e){}}
  if(!t){try{const l=el.closest("label");if(l)t=trendNorm(l.innerText||l.textContent||"");}catch(_e){}}
  return t;
}
async function trendWait(ms=700){return new Promise(r=>setTimeout(r,ms));}
function trendJoinPromptState(){
  if(site()!=="아이템스카우트")return{blocking:false,scope:null,text:"",target_text:""};
  const dialogs=[...document.querySelectorAll("[role='dialog'],[aria-modal='true'],dialog,[class*='modal'],[class*='Modal'],[class*='dialog'],[class*='Dialog'],[class*='popup'],[class*='Popup']")].filter(vis);
  let best=null,bestScore=-1,bestText="",bestTarget="";
  const scoreScope=(e)=>{
    const t=trendNorm(e.innerText||e.textContent||"");if(!t)return null;
    let score=0,target="";
    // v8.00: promotional overlay shown in the user's screenshot.  Prefer the
    // one-day suppression so it does not reappear during the 12-bucket run.
    if(t.includes("하루간 보지 않기")){score+=180;target="하루간 보지 않기";}
    if(t.includes("다음에 할래요")){score+=120;if(!target)target="다음에 할래요";}
    if(/로켓그로스|프로모션|혜택받고 시작하기/.test(t))score+=45;
    if(t.includes("카카오 로그인"))score+=35;
    if(t.includes("이메일 로그인"))score+=35;
    if(t.includes("회원가입"))score+=20;
    if(t.includes("더 많은 기능과 데이터"))score+=20;
    return{score,target,text:t};
  };
  for(const e of dialogs){const x=scoreScope(e);if(x&&x.score>bestScore){best=e;bestScore=x.score;bestText=x.text;bestTarget=x.target;}}
  if(bestScore>=100)return{blocking:true,scope:best,text:bestText,target_text:bestTarget};
  const body=trendNorm(document.body?.innerText||"");
  let bodyTarget=body.includes("하루간 보지 않기")?"하루간 보지 않기":body.includes("다음에 할래요")?"다음에 할래요":"";
  const bodyBlocking=!!bodyTarget&&(/카카오 로그인|이메일 로그인|회원가입|더 많은 기능과 데이터|로켓그로스|프로모션|혜택받고 시작하기/.test(body));
  return{blocking:bodyBlocking,scope:bodyBlocking?document.body:null,text:bodyBlocking?body.slice(0,1800):"",target_text:bodyTarget};
}
function trendClickPromptTarget(scope,targetText=""){
  if(!scope)return false;
  const wants=targetText?[targetText] : ["하루간 보지 않기","다음에 할래요"];
  const nodes=[...scope.querySelectorAll("button,a,[role='button'],[tabindex],span,div,p,u")].filter(vis);
  let target=null;
  for(const want of wants){
    target=nodes.find(e=>{const t=trendNorm(e.innerText||e.textContent||"");return t===want||t.replace(/\s/g,"")===want.replace(/\s/g,"");});
    if(target)break;
  }
  if(!target)return false;
  target=target.closest?.("button,a,[role='button'],[tabindex]")||target;
  try{target.scrollIntoView({block:"center",behavior:"instant"});}catch(_e){}
  try{
    for(const type of ["pointerdown","mousedown","pointerup","mouseup"]){
      try{target.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window}));}catch(_e){}
    }
    try{target.click();}catch(_e){}
    return true;
  }catch(_e){return false;}
}
async function trendDismissItemScoutJoinPrompt(maxWait=5200){
  if(site()!=="아이템스카우트")return{ok:true,dismissed:false,attempts:0,remaining:false,reason:"not_itemscout"};
  const started=Date.now();let attempts=0,dismissed=false,clicks=0,lastText="",lastTarget="";
  do{
    attempts++;
    const st=trendJoinPromptState();lastText=st.text||lastText;lastTarget=st.target_text||lastTarget;
    if(!st.blocking)return{ok:true,dismissed,attempts,clicks,remaining:false,reason:dismissed?"itemscout_overlay_dismissed":"no_itemscout_overlay",target:lastTarget};
    if(trendClickPromptTarget(st.scope,st.target_text)){dismissed=true;clicks++;await trendWait(420);}else{await trendWait(240);}
  }while(Date.now()-started<Math.max(0,Number(maxWait||0)));
  const final=trendJoinPromptState();
  return{ok:!final.blocking,dismissed,attempts,clicks,remaining:!!final.blocking,reason:final.blocking?"itemscout_overlay_still_blocking":"itemscout_overlay_dismissed",target:final.target_text||lastTarget,text:trendNorm(final.text||lastText).slice(0,500)};
}
function trendClickExact(labels){
  const wants=(Array.isArray(labels)?labels:[labels]).map(trendNorm).filter(Boolean);
  const candidates=[...document.querySelectorAll("button,label,a,[role='button'],[role='option'],li,span,div")].filter(vis);
  let best=null,bestScore=-1;
  for(const e of candidates){
    const t=trendNorm(e.innerText||e.textContent||"");if(!t||t.length>90)continue;
    for(const w of wants){
      let sc=-1;if(t===w)sc=100;else if(t.replace(/\s/g,"")===w.replace(/\s/g,""))sc=95;else if(t.startsWith(w)&&t.length<=w.length+10)sc=70;
      if(sc<0)continue;if(e.matches("button,label,a,[role='button'],[role='option']"))sc+=15;
      const r=e.getBoundingClientRect();if(r.width>20&&r.height>12)sc+=3;
      if(sc>bestScore){best=e;bestScore=sc;}
    }
  }
  if(!best)return false;
  try{best.scrollIntoView({block:"center"});best.click();return true;}catch(_e){return false;}
}
function trendSetSelect(text){
  const want=trendNorm(text);if(!want)return false;
  for(const sel of [...document.querySelectorAll("select")].filter(vis)){
    const opts=[...sel.options];const op=opts.find(o=>trendNorm(o.textContent)===want)||opts.find(o=>trendNorm(o.textContent).replace(/\s/g,"")===want.replace(/\s/g,""));
    if(!op)continue;setNativeValue(sel,op.value);return true;
  }
  return false;
}
function trendControlByText(text){
  const want=trendNorm(text).replace(/\s/g,"");
  const controls=[...document.querySelectorAll("input[type='checkbox'],input[type='radio']")];
  for(const el of controls){
    const t=trendLabelText(el).replace(/\s/g,"");
    if(t===want||t.includes(want)||want.includes(t))return el;
    if(el.id){try{const l=document.querySelector(`label[for="${CSS.escape(el.id)}"]`);const lt=trendNorm(l?.innerText||l?.textContent||"").replace(/\s/g,"");if(lt===want||lt.includes(want))return el;}catch(_e){}}
  }
  return null;
}
function trendSetChecked(text,desired=true){
  const el=trendControlByText(text);if(!el)return false;
  if(Boolean(el.checked)!==Boolean(desired)){try{el.click();}catch(_e){return false;}}
  return Boolean(el.checked)===Boolean(desired);
}
function trendSectionByLabel(label,maxLen=1800){
  const all=[...document.querySelectorAll("tr,section,fieldset,div")].filter(vis);let best=null,bestLen=1e9;
  for(const e of all){const t=trendNorm(e.innerText||"");if(!t.includes(label)||t.length>maxLen)continue;if(t.length<bestLen){best=e;bestLen=t.length;}}
  return best;
}
function trendRangeSection(){return trendSectionByLabel("연령대",1600)||document.body;}
function trendHasSelectedChip(text){
  const want=trendNorm(text).replace(/\s/g,"");
  const els=[...document.querySelectorAll("button,[role='button'],span,div")].filter(vis);
  for(const e of els){const t=trendNorm(e.innerText||e.textContent||"").replace(/\s/g,"");if(!t.includes(want)||t.length>want.length+12)continue;
    const aria=String(e.getAttribute('aria-pressed')||e.getAttribute('aria-selected')||'').toLowerCase();
    const cls=String(e.className||'');const style=getComputedStyle(e);const bg=String(style.backgroundColor||'');
    const rgb=(bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i)||[]).slice(1).map(Number);const blue=rgb.length===3&&rgb[2]>150&&rgb[2]>rgb[0]+25;
    if(aria==='true'||/active|selected|checked|on/i.test(cls)||/×|✕|✖|x$/i.test(t)||blue)return true;
  }
  return false;
}
function trendSetScopedRadio(rowLabel,option){
  const row=trendSectionByLabel(rowLabel,700);if(!row)return false;
  const want=trendNorm(option).replace(/\s/g,"");
  const radios=[...row.querySelectorAll("input[type='radio']")];
  for(const r of radios){const t=trendLabelText(r).replace(/\s/g,"");if(t===want||t.endsWith(want)){if(!r.checked)try{r.click();}catch(_e){};return !!r.checked;}}
  const els=[...row.querySelectorAll("label,button,[role='radio'],[role='button'],span")].filter(vis);
  const e=els.find(x=>trendNorm(x.innerText||x.textContent||"").replace(/\s/g,"")===want);
  if(!e)return false;const pressed=String(e.getAttribute('aria-checked')||e.getAttribute('aria-pressed')||'').toLowerCase()==='true';if(!pressed)try{e.click();}catch(_e){};return true;
}
function trendEnsureMajorBrandExcluded(){
  // When selected ItemScout renders an X chip both in the row and in the active
  // filter list. Never click that chip again: doing so would REMOVE the filter.
  if(trendHasSelectedChip("주요 브랜드 제외"))return{ok:true,method:"selected_chip"};
  const input=trendControlByText("주요 브랜드 제외");
  if(input){if(!input.checked)try{input.click();}catch(_e){};return{ok:!!input.checked,method:"checkbox"};}
  const row=trendSectionByLabel("브랜드 키워드",650);
  if(row){const els=[...row.querySelectorAll("label,button,[role='button'],span,div")].filter(vis);const e=els.find(x=>trendNorm(x.innerText||x.textContent||"").replace(/\s/g,"")==="주요브랜드제외");if(e){try{(e.closest?.("button,label,[role='button']")||e).click();}catch(_e){};return{ok:false,pending:true,method:"brand_row_click_pending_verify"};}}
  return{ok:false,method:"not_found"};
}

function trendActiveAgeChipPair(){
  const els=[...document.querySelectorAll("button,[role='button'],span,div")].filter(vis);
  for(const e of els){
    const raw=trendNorm(e.innerText||e.textContent||'').replace(/\s/g,'');
    const m=raw.match(/^(10|20|30|40|50|60)대~(10|20|30|40|50|60)대(?:[×✕✖x])?$/);
    if(!m)continue;
    const aria=String(e.getAttribute('aria-pressed')||e.getAttribute('aria-selected')||'').toLowerCase();
    const cls=String(e.className||'');const bg=String(getComputedStyle(e).backgroundColor||'');
    const rgb=(bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i)||[]).slice(1).map(Number);
    const blue=rgb.length===3&&rgb[2]>145&&rgb[2]>rgb[0]+20;
    const active=aria==='true'||/active|selected|checked|on/i.test(cls)||/[×✕✖x]$/.test(raw)||blue;
    if(active)return[Number(m[1]),Number(m[2])];
  }
  return[];
}
function trendAgeGeometry(sec=trendRangeSection()){
  const nums=[10,20,30,40,50,60],by=new Map();
  // Collect all visible numeric tick candidates, then choose the most horizontal
  // six-value cluster. This avoids unrelated 20/30 text elsewhere in the filter.
  const cand=[];
  for(const e of [...sec.querySelectorAll('span,div,label,p,b,strong')].filter(vis)){
    const t=trendNorm(e.innerText||e.textContent||'');if(!nums.includes(Number(t)))continue;
    const r=e.getBoundingClientRect();if(r.width>85||r.height>48)continue;
    cand.push({n:Number(t),e,r,cx:r.left+r.width/2,cy:r.top+r.height/2});
  }
  let best=[];
  for(const base of cand){
    const row=cand.filter(x=>Math.abs(x.cy-base.cy)<=9);
    const uniq=[];for(const n of nums){const xs=row.filter(x=>x.n===n).sort((a,b)=>a.cx-b.cx);if(xs.length)uniq.push(xs[xs.length-1]);}
    if(uniq.length>best.length||(uniq.length===best.length&&uniq.length>=2&&(uniq.at(-1).cx-uniq[0].cx)>(best.at(-1)?.cx-best[0]?.cx||0)))best=uniq;
  }
  if(best.length<4)return{ok:false,method:'age_tick_cluster_missing',count:best.length};
  for(const x of best)by.set(x.n,x);
  if(!nums.every(n=>by.has(n)))return{ok:false,method:'age_tick_incomplete',ticks:[...by.keys()]};
  const tracks=[...sec.querySelectorAll("input[type='range'],[role='slider']")].filter(vis)
    .map(e=>({e,r:e.getBoundingClientRect()})).filter(x=>x.r.width>120).sort((a,b)=>b.r.width-a.r.width);
  let y=tracks.length?(tracks[0].r.top+tracks[0].r.height/2):Math.min(...best.map(x=>x.r.top))-25;
  const xmap={};for(const n of nums)xmap[n]=by.get(n).cx;
  return{ok:true,method:'tick_track_geometry',xmap,y,track:tracks.length?{left:tracks[0].r.left,top:tracks[0].r.top,width:tracks[0].r.width,height:tracks[0].r.height}:null,
    ticks:best.map(x=>({n:x.n,x:Math.round(x.cx),y:Math.round(x.cy)}))};
}
function trendRuntimeMessage(msg,timeout=2600){
  return new Promise(resolve=>{
    let done=false;const finish=v=>{if(done)return;done=true;clearTimeout(timer);resolve(v||{ok:false,error:'empty_response'});};
    const timer=setTimeout(()=>finish({ok:false,error:'runtime_message_timeout'}),timeout);
    try{chrome.runtime.sendMessage(msg,r=>{const e=chrome.runtime.lastError;if(e)finish({ok:false,error:e.message});else finish(r);});}
    catch(e){finish({ok:false,error:String(e)});}
  });
}
async function trendWaitCommittedAgePair(lo,hi,timeout=1800){
  const started=Date.now();let stable=0,last=[];
  while(Date.now()-started<timeout){
    const chip=trendActiveAgeChipPair();last=chip;
    if(chip.length===2&&chip[0]===lo&&chip[1]===hi){stable++;if(stable>=2)return{ok:true,pair:chip,method:'committed_age_chip',elapsed_ms:Date.now()-started};}
    else stable=0;
    // Some builds do not render a chip until filter registration. Keep the exact
    // slider values as a secondary signal, never as the preferred source.
    if(!chip.length){const snap=trendSliderSnapshot(trendRangeSection());let vals=[];
      if(snap.roles.length>=2)vals=snap.roles.map(x=>x.now).filter(Number.isFinite).sort((a,b)=>a-b);
      if(vals.length<2&&snap.ranges.length>=2)vals=snap.ranges.map(x=>x.value).filter(Number.isFinite).sort((a,b)=>a-b);
      if(vals.length>=2&&vals[0]===lo&&vals[1]===hi){stable++;if(stable>=3)return{ok:true,pair:vals.slice(0,2),method:'fallback_exact_slider_values',elapsed_ms:Date.now()-started};}
    }
    await trendWait(75);
  }
  return{ok:false,pair:last,method:'committed_age_pair_timeout',elapsed_ms:Date.now()-started};
}
function trendPointStack(x,y){
  try{return document.elementsFromPoint(Number(x),Number(y)).slice(0,8).map(e=>({tag:String(e.tagName||'').toLowerCase(),role:e.getAttribute?.('role')||'',type:e.getAttribute?.('type')||'',value:'value' in e?String(e.value||''):'',cls:String(e.className||'').slice(0,180)}));}
  catch(_e){return[];}
}
function trendCommittedOrRawAgePair(sec=trendRangeSection()){
  const chip=trendActiveAgeChipPair();if(chip.length>=2)return{pair:chip.slice(0,2),source:'committed_age_chip'};
  const raw=trendSliderSnapshot(sec);let vals=[];
  if(raw.roles.length>=2)vals=raw.roles.map(x=>x.now).filter(Number.isFinite).sort((a,b)=>a-b);
  if(vals.length<2&&raw.ranges.length>=2)vals=raw.ranges.map(x=>x.value).filter(Number.isFinite).sort((a,b)=>a-b);
  return{pair:vals.length>=2?vals.slice(0,2):[10,60],source:vals.length>=2?'raw_slider_fallback':'default_10_60'};
}
async function trendSetAgeRangeTrusted(lo,hi,sec=trendRangeSection()){
  const attempts=[];
  try{sec.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});}catch(_e){}
  await trendWait(180);
  // Re-plan after every physical operation instead of building one static order.
  // If a wrong thumb ever reacts, the next iteration sees the newly committed
  // pair and can still converge to the requested age range, including one decade.
  for(let stepNo=1;stepNo<=8;stepNo++){
    const state=trendCommittedOrRawAgePair(sec),pair=state.pair;
    if(pair.length>=2&&pair[0]===lo&&pair[1]===hi){
      const final=await trendWaitCommittedAgePair(lo,hi,1200);
      if(final.ok)return{ok:true,method:'cdp_trusted_dual_slider_verified',lo,hi,actual:pair,attempts,final};
    }
    let side,target;
    // Expand outer bounds first to avoid dual-slider crossing/clamping; after
    // that, shrink the edge that differs. This also handles recovery from an
    // accidental wrong-thumb move because the plan is recomputed each step.
    if(pair[1]<hi){side='right';target=hi;}
    else if(pair[0]>lo){side='left';target=lo;}
    else if(pair[1]!==hi){side='right';target=hi;}
    else if(pair[0]!==lo){side='left';target=lo;}
    else break;
    let opOk=false;
    for(let tryNo=1;tryNo<=5&&!opOk;tryNo++){
      const liveState=trendCommittedOrRawAgePair(sec),live=liveState.pair;
      const liveStart=side==='left'?live[0]:live[1],liveOpp=side==='left'?live[1]:live[0];
      if(liveStart===target){opOk=true;break;}
      const g=trendAgeGeometry(sec);if(!g.ok){attempts.push({stepNo,side,target,tryNo,state:liveState,geometry:g});break;}
      const dy=[0,-4,4,-8,8][tryNo-1]||0,y=g.y+dy;
      const from={x:g.xmap[liveStart],y},to={x:g.xmap[target],y};
      if(!Number.isFinite(from.x)||!Number.isFinite(to.x)){attempts.push({stepNo,side,target,tryNo,state:liveState,geometry:g,error:'tick_x_missing'});break;}
      const hit_before=trendPointStack(from.x,from.y);
      const response=await trendRuntimeMessage({type:'itemscoutTrustedDrag',from,to,steps:24},5000);
      const expect=side==='left'?[target,liveOpp]:[liveOpp,target];expect.sort((a,b)=>a-b);
      const verify=await trendWaitCommittedAgePair(expect[0],expect[1],1900);
      const afterState=trendCommittedOrRawAgePair(sec);
      attempts.push({stepNo,side,target,tryNo,state_before:liveState,from,to,hit_before,response,expect,verify,state_after:afterState,geometry:g});
      if(verify.ok){opOk=true;break;}
      // Even when the requested edge did not commit, a physical drag may have
      // changed the other edge. Return to the outer convergence loop immediately
      // once any committed chip changed instead of repeating stale coordinates.
      if(afterState.source==='committed_age_chip'&&(afterState.pair[0]!==live[0]||afterState.pair[1]!==live[1])){opOk=true;break;}
      await trendWait(150);
    }
    if(!opOk)return{ok:false,method:'cdp_trusted_drag_side_failed',lo,hi,side,target,current:trendCommittedOrRawAgePair(sec),attempts};
    await trendWait(120);
  }
  const final=await trendWaitCommittedAgePair(lo,hi,2000);
  return{ok:final.ok,method:final.ok?'cdp_trusted_dual_slider_verified':'cdp_trusted_final_unverified',lo,hi,actual:final.pair||trendCommittedOrRawAgePair(sec).pair,attempts,final};
}

function trendSliderSnapshot(sec=trendRangeSection()){
  const sortLR=els=>els.slice().sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left);
  const roles=sortLR([...sec.querySelectorAll("[role='slider']")].filter(vis)).map((e,i)=>({
    i,left:Math.round(e.getBoundingClientRect().left),now:Number(e.getAttribute('aria-valuenow')),
    min:Number(e.getAttribute('aria-valuemin')),max:Number(e.getAttribute('aria-valuemax')),
    step:Number(e.getAttribute('aria-valuestep')||10),label:trendNorm(e.getAttribute('aria-label')||e.getAttribute('aria-valuetext')||'')
  }));
  const ranges=sortLR([...sec.querySelectorAll("input[type='range']")].filter(vis)).map((e,i)=>({
    i,left:Math.round(e.getBoundingClientRect().left),value:Number(e.value),min:Number(e.min||10),max:Number(e.max||60),step:Number(e.step||10),
    aria:Number(e.getAttribute('aria-valuenow'))
  }));
  const chips=[...document.querySelectorAll("button,[role='button'],span,div")].filter(vis).map(e=>trendNorm(e.innerText||e.textContent||''))
    .filter(t=>/^\d{1,2}대\s*~\s*\d{1,2}대(?:\s*[×✕✖x])?$/.test(t)).slice(0,8);
  return{roles,ranges,chips};
}
function trendSliderValues(sec=trendRangeSection()){
  const snap=trendSliderSnapshot(sec);
  let vals=trendActiveAgeChipPair();
  if(vals.length>=2)return{values:vals.slice(0,2).sort((a,b)=>a-b),snapshot:snap,source:"committed_age_chip"};
  vals=[];
  if(snap.roles.length>=2){vals=snap.roles.map(x=>x.now).filter(Number.isFinite);}
  if(vals.length<2&&snap.ranges.length>=2){vals=snap.ranges.map(x=>x.value).filter(Number.isFinite);}
  vals=vals.slice(0,2).sort((a,b)=>a-b);
  return{values:vals,snapshot:snap};
}
function trendAgeChipLabel(lo,hi){return `${lo}대~${hi}대`;}
function trendVerifyAgeRange(lo,hi,sec=trendRangeSection()){
  // The selected filter chip is ItemScout's committed React state, so it is the
  // strongest final signal. Slider values are used as a second independent check.
  if(trendHasSelectedChip(trendAgeChipLabel(lo,hi)))return{ok:true,method:"age_chip",lo,hi,snapshot:trendSliderSnapshot(sec)};
  const m=trendSliderValues(sec),vals=m.values;
  if(vals.length>=2&&vals[0]===lo&&vals[1]===hi)return{ok:true,method:"slider_values",lo,hi,values:vals,snapshot:m.snapshot};
  return{ok:false,method:"unverified",lo,hi,values:vals,snapshot:m.snapshot};
}
async function trendWaitAgeRange(lo,hi,sec=trendRangeSection(),timeout=1400){
  const started=Date.now();let last=trendVerifyAgeRange(lo,hi,sec),stable=0,lastSig='';
  // Do not accept the value written synchronously by setNativeValue. React can
  // re-render with the previous pair on the next tick. Require a persisted
  // target state across multiple polls.
  await trendWait(80);
  while(Date.now()-started<timeout){
    last=trendVerifyAgeRange(lo,hi,sec);
    const sig=JSON.stringify(last.values||[])+"|"+(last.ok?"1":"0");
    if(last.ok&&sig===lastSig)stable++;else stable=last.ok?1:0;
    lastSig=sig;
    if(last.ok&&stable>=2)return Object.assign({},last,{persisted:true,elapsed_ms:Date.now()-started});
    await trendWait(70);
  }
  return Object.assign({},last,{persisted:false,elapsed_ms:Date.now()-started});
}
function trendSliderNodeValue(el,kind){
  const v=kind==='role'?Number(el.getAttribute('aria-valuenow')):Number(el.value);
  return Number.isFinite(v)?v:NaN;
}
function trendSortSliderNodesByValue(els,kind){
  // ItemScout overlays the two native range inputs on one full-width track.
  // Their boundingClientRect().left can therefore be identical and DOM order is
  // NOT a reliable min/max identity.  Numeric current value is the stable identity.
  return els.slice().sort((a,b)=>{
    const av=trendSliderNodeValue(a,kind),bv=trendSliderNodeValue(b,kind);
    if(Number.isFinite(av)&&Number.isFinite(bv)&&av!==bv)return av-bv;
    const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();
    const ac=ar.left+ar.width/2,bc=br.left+br.width/2;
    return ac-bc;
  });
}
function trendOrderedRoleSliders(sec){return trendSortSliderNodesByValue([...sec.querySelectorAll("[role='slider']")].filter(vis),'role');}
function trendOrderedRangeInputs(sec){return trendSortSliderNodesByValue([...sec.querySelectorAll("input[type='range']")].filter(vis),'range');}
function trendSliderPair(sec=trendRangeSection()){
  const m=trendSliderValues(sec);
  return Array.isArray(m.values)?m.values.slice(0,2):[];
}
async function trendWaitSideCommit(side,target,oppositeBefore,sec,timeout=950){
  const started=Date.now();let stable=0,lastPair=[],wrongSide=false;
  await trendWait(70);
  while(Date.now()-started<timeout){
    const pair=trendSliderPair(sec);lastPair=pair;
    if(pair.length>=2){
      const sideVal=side==='left'?pair[0]:pair[1],oppVal=side==='left'?pair[1]:pair[0];
      const oppositeOk=!Number.isFinite(oppositeBefore)||oppVal===oppositeBefore;
      if(sideVal===target&&oppositeOk){stable++;if(stable>=2)return{ok:true,pair,now:sideVal,opposite:oppVal,elapsed_ms:Date.now()-started};}
      else stable=0;
      // Explicitly detect the historical failure: request right 60->30 but the
      // left thumb changes (20->30) while the high value stays 60.
      if(Number.isFinite(oppositeBefore)&&oppVal!==oppositeBefore&&sideVal!==target)wrongSide=true;
    }
    await trendWait(65);
  }
  return{ok:false,pair:lastPair,now:side==='left'?lastPair[0]:lastPair[1],wrong_side_moved:wrongSide,elapsed_ms:Date.now()-started};
}
async function trendWaitOneHandle(side,target,sec,timeout=700){
  const pair=trendSliderPair(sec),oppositeBefore=pair.length>=2?(side==='left'?pair[1]:pair[0]):NaN;
  return await trendWaitSideCommit(side,target,oppositeBefore,sec,timeout);
}
async function trendSetRangeInputStable(side,target,sec){
  const pairBefore=trendSliderPair(sec),oppositeBefore=pairBefore.length>=2?(side==='left'?pairBefore[1]:pairBefore[0]):NaN;
  const ranges=trendOrderedRangeInputs(sec);if(ranges.length<2)return{ok:false,method:"range_missing",pair_before:pairBefore};
  const e=side==='left'?ranges[0]:ranges[ranges.length-1],before=Number(e.value);
  const diag=ranges.map((x,i)=>({i,value:Number(x.value),left:Math.round(x.getBoundingClientRect().left),width:Math.round(x.getBoundingClientRect().width),aria:Number(x.getAttribute('aria-valuenow'))}));
  if(before===target){const w=await trendWaitSideCommit(side,target,oppositeBefore,sec,320);return{ok:w.ok,method:"range_already",before,after:w.now,pair_before:pairBefore,pair_after:w.pair||[],inputs:diag,wrong_side_moved:!!w.wrong_side_moved};}
  setNativeValue(e,String(target));
  const w=await trendWaitSideCommit(side,target,oppositeBefore,sec,1000);
  return{ok:w.ok,method:w.wrong_side_moved?"range_wrong_thumb_detected":"range_value_identity",before,after:w.now,pair_before:pairBefore,pair_after:w.pair||[],inputs:diag,wrong_side_moved:!!w.wrong_side_moved,wait_ms:w.elapsed_ms};
}
async function trendSetRoleSliderStable(side,target,sec){
  let history=[];
  for(let guard=0;guard<12;guard++){
    const roles=trendOrderedRoleSliders(sec);if(roles.length<2)return{ok:false,method:"aria_missing",history};
    const el=side==='left'?roles[0]:roles[roles.length-1];
    const min=Number(el.getAttribute("aria-valuemin")),max=Number(el.getAttribute("aria-valuemax"));
    const now=Number(el.getAttribute("aria-valuenow"));history.push(now);
    if(!Number.isFinite(now)||!Number.isFinite(min)||!Number.isFinite(max))return{ok:false,method:"aria_invalid",history};
    if(now===target)return{ok:true,method:"aria_sequential",history};
    const key=target<=min?"Home":target>=max?"End":now<target?"ArrowRight":"ArrowLeft";
    const pairBefore=trendSliderPair(sec),oppositeBefore=pairBefore.length>=2?(side==='left'?pairBefore[1]:pairBefore[0]):NaN;
    try{el.focus({preventScroll:true});}catch(_e){try{el.focus();}catch(__e){}}
    try{el.dispatchEvent(new KeyboardEvent("keydown",{key,bubbles:true,cancelable:true}));el.dispatchEvent(new KeyboardEvent("keyup",{key,bubbles:true,cancelable:true}));}catch(_e){}
    // React/rc-slider/Ant style controls commit asynchronously. Waiting for the
    // actual DOM handle value before the next key prevents stale-state races.
    const expected=key==="Home"?min:key==="End"?max:(now<target?Math.min(target,now+10):Math.max(target,now-10));
    const changed=await trendWaitSideCommit(side,expected,oppositeBefore,sec,700);
    if(!changed.ok){
      await trendWait(120);
      const again=trendOrderedRoleSliders(sec);const cur=again.length>=2?Number((side==='left'?again[0]:again[again.length-1]).getAttribute('aria-valuenow')):NaN;
      if(cur===now)return{ok:false,method:"aria_no_commit",history:[...history,cur]};
    }
  }
  const roles=trendOrderedRoleSliders(sec);const cur=roles.length>=2?Number((side==='left'?roles[0]:roles[roles.length-1]).getAttribute('aria-valuenow')):NaN;
  return{ok:cur===target,method:"aria_guard",history:[...history,cur]};
}
function trendPointerMove(el,targetX,targetY){
  try{
    const r=el.getBoundingClientRect(),sx=r.left+r.width/2,sy=r.top+r.height/2,pid=1;
    const p=(target,type,x,y,buttons)=>{try{target.dispatchEvent(new PointerEvent(type,{pointerId:pid,pointerType:'mouse',isPrimary:true,bubbles:true,cancelable:true,clientX:x,clientY:y,buttons,button:0}));}catch(_e){}};
    const m=(target,type,x,y,buttons)=>{try{target.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,buttons,button:0}));}catch(_e){}};
    // Modern sliders may consume PointerEvents while older rc-slider style
    // controls consume MouseEvents. Chrome supports PointerEvent construction even
    // when the widget listens only for mouse events, so the old fallback never ran.
    // Dispatch both families deliberately to the same target coordinates.
    p(el,'pointerdown',sx,sy,1);
    for(let i=1;i<=10;i++){const x=sx+(targetX-sx)*i/10,y=sy+(targetY-sy)*i/10;p(document,'pointermove',x,y,1);}
    p(document,'pointerup',targetX,targetY,0);
    m(el,'mousedown',sx,sy,1);
    for(let i=1;i<=10;i++){const x=sx+(targetX-sx)*i/10,y=sy+(targetY-sy)*i/10;m(document,'mousemove',x,y,1);}
    m(document,'mouseup',targetX,targetY,0);
    return true;
  }catch(_e){return false;}
}
async function trendSetAgeRangeByGeometry(lo,hi,sec){
  const ticks=[];for(const n of [10,20,30,40,50,60]){let best=null;for(const e of [...sec.querySelectorAll("span,div,label,p")].filter(vis)){if(trendNorm(e.innerText||e.textContent||"")!==String(n))continue;const r=e.getBoundingClientRect();if(r.width<80&&r.height<45){best={n,e,r};break;}}if(best)ticks.push(best);}
  if(ticks.length<4)return{ok:false,method:"geometry_ticks_missing",lo,hi,tick_count:ticks.length,snapshot:trendSliderSnapshot(sec)};
  ticks.sort((a,b)=>a.r.left-b.r.left);const by=new Map(ticks.map(x=>[x.n,x]));if(!by.has(lo)||!by.has(hi))return{ok:false,method:"geometry_target_tick_missing",lo,hi,snapshot:trendSliderSnapshot(sec)};
  const tickTop=Math.min(...ticks.map(x=>x.r.top)),minX=Math.min(...ticks.map(x=>x.r.left)),maxX=Math.max(...ticks.map(x=>x.r.right));
  const findHandles=()=>{let handles=[];for(const e of [...sec.querySelectorAll("button,span,div,[role='slider']")].filter(vis)){const r=e.getBoundingClientRect();if(r.width<10||r.width>42||r.height<10||r.height>42)continue;const cx=r.left+r.width/2,cy=r.top+r.height/2;if(cx<minX-25||cx>maxX+25||cy<tickTop-70||cy>tickTop-2)continue;const st=getComputedStyle(e);if(e.getAttribute('role')==='slider'||parseFloat(st.borderRadius||'0')>=6||/slider|handle|thumb/i.test(String(e.className||'')))handles.push({e,r,cx,cy});}handles.sort((a,b)=>a.cx-b.cx);return handles;};
  let handles=findHandles();if(handles.length<2)return{ok:false,method:"geometry_handles_missing",lo,hi,handle_count:handles.length,snapshot:trendSliderSnapshot(sec)};
  const targetX=n=>by.get(n).r.left+by.get(n).r.width/2;
  // Move only one handle at a time and let React commit before touching the
  // second handle. This is essential for ItemScout's controlled dual slider.
  let vals=trendSliderValues(sec).values,ops=[];
  const currentLo=vals[0],currentHi=vals[1];
  const order=[];
  if(Number.isFinite(currentHi)&&hi>currentHi)order.push(['right',hi]);
  if(Number.isFinite(currentLo)&&lo<currentLo)order.push(['left',lo]);
  if(!order.some(x=>x[0]==='left')&&currentLo!==lo)order.push(['left',lo]);
  if(!order.some(x=>x[0]==='right')&&currentHi!==hi)order.push(['right',hi]);
  for(const [side,target] of order){
    handles=findHandles();if(handles.length<2)break;
    const pairBefore=trendSliderPair(sec),oppBefore=pairBefore.length>=2?(side==='left'?pairBefore[1]:pairBefore[0]):NaN;
    const h=side==='left'?handles[0]:handles[handles.length-1],ty=h.cy;
    trendPointerMove(h.e,targetX(target),ty);
    const committed=await trendWaitSideCommit(side,target,oppBefore,sec,1100);
    ops.push({side,target,pair_before:pairBefore,committed,after:trendSliderSnapshot(sec)});
  }
  const v=await trendWaitAgeRange(lo,hi,sec,1100);return Object.assign({},v,{method:v.ok?"geometry_pointer_verified":"geometry_pointer_unverified",lo,hi,ops});
}
function trendAgeCodes(ageCodes){
  if(!Array.isArray(ageCodes)||!ageCodes.length)return[];
  const nums=ageCodes.map(Number);
  if(nums.some(n=>![10,20,30,40,50,60].includes(n)))return[];
  return [...new Set(nums)].sort((a,b)=>a-b);
}
function trendAgeCheckboxes(){
  const controls=[...document.querySelectorAll("input[type='checkbox'],input[type='radio']")];
  return [10,20,30,40,50,60].map(n=>({n,control:controls.find(c=>{
    const label=trendLabelText(c).replace(/\s/g,'');
    return label===`${n}대`||(n===60&&label==='60대이상');
  })}));
}
function trendVerifyAgeChecks(nums){
  const checks=trendAgeCheckboxes();
  const actual=checks.filter(x=>x.control?.checked).map(x=>x.n);
  return{ok:checks.every(x=>x.control&&Boolean(x.control.checked)===nums.includes(x.n)),method:"age_checks",actual,requested:nums};
}
async function trendSetAgeRange(ageCodes){
  const nums=trendAgeCodes(ageCodes);if(!nums.length)return{ok:false,method:"invalid_age_codes"};
  if(site()!=="아이템스카우트"){
    for(const {n,control} of trendAgeCheckboxes()){
      if(control&&Boolean(control.checked)!==nums.includes(n))try{control.click();}catch(_e){}
    }
    await trendWait(100);
    return trendVerifyAgeChecks(nums);
  }
  if(nums.some((n,i)=>i>0&&n!==nums[i-1]+10))return{ok:false,method:"noncontiguous_age_range",requested:nums};
  const lo=Math.min(...nums),hi=Math.max(...nums),sec=trendRangeSection(),attempts=[];
  let pre=await trendWaitAgeRange(lo,hi,sec,260);if(pre.ok)return Object.assign(pre,{already:true,attempts});

  // v8.02: ItemScout's visible thumbs are not reliably controlled by writing
  // input.value/ARIA. Use Chrome's trusted low-level mouse input first, starting
  // at the currently committed thumb position and physically dragging to the
  // exact tick. This is equivalent to the user's successful manual operation.
  if(site()==="아이템스카우트"){
    const trusted=await trendSetAgeRangeTrusted(lo,hi,sec);attempts.push({phase:'trusted_cdp',trusted});
    if(trusted.ok)return Object.assign({},trusted,{attempts});
  }

  // Repeat with fresh DOM references. ItemScout re-renders the two controlled
  // range inputs after each handle change, so never write both handles back to
  // back using stale references (the v7.99 root cause).
  for(let round=1;round<=3;round++){
    let model=trendSliderValues(sec),vals=model.values;attempts.push({round,phase:'start',values:vals,snapshot:model.snapshot});
    const curLo=vals[0],curHi=vals[1];
    const order=[];
    // Expand the interval first if needed; then move the inner edge. This avoids
    // dual-slider crossing/clamping and also skips a handle already at target.
    if(Number.isFinite(curHi)&&hi>curHi)order.push(['right',hi]);
    if(Number.isFinite(curLo)&&lo<curLo)order.push(['left',lo]);
    if(curLo!==lo&&!order.some(x=>x[0]==='left'))order.push(['left',lo]);
    if(curHi!==hi&&!order.some(x=>x[0]==='right'))order.push(['right',hi]);

    for(const [side,target] of order){
      const ranges=trendOrderedRangeInputs(sec);let op=null;
      if(ranges.length>=2)op=await trendSetRangeInputStable(side,target,sec);
      if(!op?.ok){const roles=trendOrderedRoleSliders(sec);if(roles.length>=2)op=await trendSetRoleSliderStable(side,target,sec);}
      attempts.push({round,side,target,op,snapshot:trendSliderSnapshot(sec)});
      await trendWait(100);
    }
    let v=await trendWaitAgeRange(lo,hi,sec,900);attempts.push({round,phase:'verify',verify:v});
    if(v.ok)return Object.assign({},v,{method:"sequential_dual_slider",attempts});
  }

  const geo=await trendSetAgeRangeByGeometry(lo,hi,sec);attempts.push({phase:'geometry',geo});
  if(geo.ok)return Object.assign({},geo,{attempts});
  const final=trendVerifyAgeRange(lo,hi,sec);
  return{ok:false,method:"itemscout_dual_slider_not_verified",lo,hi,actual:final.values||[],snapshot:final.snapshot,attempts};
}
async function trendWaitForKeywordChange(before,timeout=3200){
  const started=Date.now();let last=[];while(Date.now()-started<timeout){last=extractTrendKeywords(30);const sig=last.slice(0,8).map(x=>x.keyword).join('|');if(last.length&&sig&&sig!==before)return{changed:true,cards:last,elapsed:Date.now()-started};await trendWait(120);}return{changed:false,cards:last,elapsed:Date.now()-started};
}
async function trendSetCategory(category){
  if(trendSetSelect(category)){await trendWait(650);return{ok:true,method:"select"};}
  // Click a category selector first when the page keeps options in a popup.
  trendClickExact(["카테고리","분야"]);await trendWait(250);
  const ok=trendClickExact(category);if(ok)await trendWait(900);
  return{ok,method:"text_click"};
}
function trendKeywordNoise(t){
  t=trendNorm(t);if(!t||t.length<2||t.length>100)return true;
  if(/^(순위|키워드|검색어|검색량|조회수|클릭량|상품수|경쟁률|총검색수|기기별|성별|연령대|기간|카테고리|전체|남성|여성|쇼핑성|정보성|적용|조회|검색)$/i.test(t))return true;
  if(/^\d+(?:[,.]\d+)*(?:%|회|건|개)?$/.test(t))return true;
  if(/^\d{4}[.\-/]\d{1,2}/.test(t))return true;
  return !/[A-Za-z가-힣]/.test(t);
}
function trendKeywordFromRow(row){
  const cells=[...row.querySelectorAll("th,td")].filter(vis);
  const texts=(cells.length?cells:[row]).map(e=>trendNorm(e.innerText||e.textContent||"")).filter(Boolean);
  for(let t of texts){
    const pieces=t.split(/\n+/).map(trendNorm).filter(Boolean);
    for(let p of pieces){p=p.replace(/^\s*\d{1,3}\s*(?:위|\.)?\s*/,"").trim();if(!trendKeywordNoise(p))return p;}
  }
  return"";
}
function trendRankFromRow(row,index){
  const first=trendNorm(row.querySelector("th,td")?.innerText||"");let m=first.match(/^\s*(\d{1,3})(?:\s*위)?\s*$/);if(m)return Number(m[1]);
  m=trendNorm(row.innerText||"").match(/^\s*(\d{1,3})(?:\s*위|\.|\s)/);return m?Number(m[1]):index;
}
function extractTrendKeywords(limit=30){
  const lim=Math.max(1,Number(limit||30)),out=[],seen=new Set();
  const add=(keyword,rank,text="")=>{keyword=trendNorm(keyword);const key=keyword.toLowerCase().replace(/[^0-9a-z가-힣]/g,"");if(!key||seen.has(key)||trendKeywordNoise(keyword))return;seen.add(key);out.push({keyword,name:keyword,rank_hint:Number(rank||out.length+1),text:trendNorm(text).slice(0,600),url:location.href});};
  let rows=[...document.querySelectorAll("tbody tr")].filter(vis);
  if(rows.length<lim)rows.push(...[...document.querySelectorAll("[role='row'],li,[class*='rank'],[class*='keyword']")].filter(vis));
  let idx=0;for(const row of rows){idx++;const kw=trendKeywordFromRow(row);if(kw)add(kw,trendRankFromRow(row,idx),row.innerText||"");if(out.length>=lim)break;}
  // Fallback for visually ranked lists where rank and keyword are sibling nodes.
  if(out.length<lim){
    const rankNodes=[...document.querySelectorAll("span,strong,b,em,div")].filter(vis).filter(e=>/^\s*\d{1,3}\s*(?:위)?\s*$/.test(trendNorm(e.innerText||e.textContent||"")));
    for(const rn of rankNodes){const rank=Number(trendNorm(rn.innerText||rn.textContent||"").match(/\d+/)?.[0]||0);let p=rn.parentElement;for(let d=0;p&&d<4;d++,p=p.parentElement){const kw=trendKeywordFromRow(p);if(kw){add(kw,rank,p.innerText||"");break;}}if(out.length>=lim)break;}
  }
  out.sort((a,b)=>Number(a.rank_hint||999)-Number(b.rank_hint||999));return out.slice(0,lim);
}
async function collectItemScoutTrend(msg){
  const filter={};
  try{window.scrollTo({top:0,left:0,behavior:"instant"});}catch(_e){window.scrollTo(0,0);}
  filter.overlay_preflight=await trendDismissItemScoutJoinPrompt(6000);
  if(filter.overlay_preflight.remaining){
    return{status:"error",site:site(),url:location.href,cards:[],filter_state:filter,
      error:"아이템스카우트 안내창의 '하루간 보지 않기/다음에 할래요' 자동 처리에 실패했습니다.",
      debug:{collector:"itemscout_trusted_physical_dual_slider_v8_02",modal_blocked:true,body_head:trendNorm(document.body?.innerText||"").slice(0,1200)}};
  }
  await trendWait(160);
  if(Number(msg.period_days||30)<=31){filter.period30=trendClickExact(["최근 30일","30일"]);await trendWait(180);}
  // Direct /category/N navigation already selects the category. Only attempt a
  // UI category click if the page title/body does not contain the requested one.
  const wantedCat=msg.category_label||msg.blog_category||msg.query||"";
  const wantedPath=msg.category_id?`/category/${msg.category_id}`:"";
  filter.category=(wantedPath&&location.pathname.replace(/\/+$/,'')===wantedPath)?{ok:true,method:"category_url",path:location.pathname}:await trendSetCategory(wantedCat);
  await trendDismissItemScoutJoinPrompt(800);
  // Screenshot contract: keyword type 전체, gender 전체, major brands excluded.
  filter.keyword_type=trendSetScopedRadio("키워드 유형",msg.keyword_type||"전체");await trendWait(100);
  filter.gender=trendSetScopedRadio("성별","전체");await trendWait(100);
  filter.exclude_major_brands=trendEnsureMajorBrandExcluded();await trendWait(180);
  filter.exclude_major_brands_verify=trendEnsureMajorBrandExcluded();
  if(!filter.exclude_major_brands_verify?.ok){return{status:"error",site:site(),url:location.href,cards:[],filter_state:filter,
    error:"아이템스카우트 '주요 브랜드 제외'가 실제 활성화됐는지 확인되지 않아 잘못된 데이터 수집을 중단했습니다.",debug:{collector:"itemscout_trusted_physical_dual_slider_v8_02",brand_filter_not_verified:true}};}
  filter.age=await trendSetAgeRange(msg.age_codes||[]);await trendWait(180);
  if(!filter.age?.ok){await trendWait(220);filter.age_retry=await trendSetAgeRange(msg.age_codes||[]);if(filter.age_retry?.ok)filter.age=filter.age_retry;}
  if(!filter.age?.ok){return{status:"error",site:site(),url:location.href,cards:[],filter_state:filter,
    error:`아이템스카우트 연령 양쪽 핸들 설정 실패: 목표 ${filter.age?.lo||''}~${filter.age?.hi||''}대 / 실제 ${(filter.age?.actual||filter.age?.values||[]).join('~')||'확인불가'}대. 실제 화면 핸들을 Chrome trusted drag로 이동한 뒤에도 목표 범위가 유지되지 않아 잘못된 데이터 수집을 중단했습니다. 상세 핸들/ARIA/입력값은 실패 진단 파일에 저장됩니다.`,
    debug:{collector:"itemscout_trusted_physical_dual_slider_v8_02",age_not_verified:true,slider_snapshot:filter.age?.snapshot||{},attempts:filter.age?.attempts||[]}};}
  filter.overlay_before_apply=await trendDismissItemScoutJoinPrompt(900);
  const before=extractTrendKeywords(30).slice(0,8).map(x=>x.keyword).join('|');
  filter.apply=trendClickExact(["적용","조회","검색"]);
  // ItemScout often updates automatically. Wait for actual ranking mutation
  // instead of sleeping a fixed 2.2 seconds on every bucket.
  const changed=await trendWaitForKeywordChange(before,3000);filter.result_wait={changed:changed.changed,elapsed_ms:changed.elapsed};
  await trendDismissItemScoutJoinPrompt(600);
  let cards=changed.cards?.length?changed.cards:extractTrendKeywords(msg.limit||30);
  if(cards.length<Number(msg.limit||30)){await trendWait(300);cards=extractTrendKeywords(msg.limit||30);}
  const requestedAges=trendAgeCodes(msg.age_codes);
  filter.age_after_apply=await trendWaitAgeRange(requestedAges[0],requestedAges.at(-1),trendRangeSection(),500);
  if(!filter.age_after_apply.ok)return{status:"error",site:site(),url:location.href,cards:[],filter_state:filter,
    error:"아이템스카우트 조회 후 연령대 선택이 달라져 수집 결과를 제외했습니다."};
  return{status:cards.length?"ok":"error",site:site(),url:location.href,cards:cards.slice(0,Number(msg.limit||30)),filter_state:filter,
    error:cards.length?"":"아이템스카우트 필터 적용 후 순위 키워드를 찾지 못했습니다.",
    debug:{collector:"itemscout_trusted_physical_dual_slider_v8_02",modal_blocked:false,fast_wait:true,body_head:trendNorm(document.body?.innerText||"").slice(0,1200)}};
}
const TREND_DATALAB_CIDS={"패션의류":"50000000","패션잡화":"50000001","화장품/미용":"50000002","디지털/가전":"50000003","가구/인테리어":"50000004","식품":"50000006"};
function trendDateISO(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
async function naverDataLabDirectRanks(msg){
  if(location.hostname!=="datalab.naver.com")return{ok:false,error:"wrong_host"};
  const cid=String(msg.category_id||TREND_DATALAB_CIDS[msg.category_label||msg.query]||"");if(!cid)return{ok:false,error:"category_id_missing"};
  const ages=trendAgeCodes(msg.age_codes);if(!ages.length)return{ok:false,error:"invalid_age_codes"};
  const end=new Date();end.setHours(12,0,0,0);end.setDate(end.getDate()-2);const start=new Date(end);start.setDate(start.getDate()-Math.max(1,Number(msg.period_days||30))+1);
  const age=ages.join(',');const gender=msg.gender&&msg.gender!=="전체"?(msg.gender==="여성"?'f':msg.gender==="남성"?'m':''):'';
  const cards=[],seen=new Set(),limit=Math.max(1,Number(msg.limit||30));
  try{
    for(let page=1;page<=Math.ceil(limit/20);page++){
      const body=new URLSearchParams({cid,timeUnit:'date',startDate:trendDateISO(start),endDate:trendDateISO(end),age,gender,device:'',page:String(page),count:'20'});
      const r=await fetch('/shoppingInsight/getCategoryKeywordRank.naver',{method:'POST',credentials:'include',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body:body.toString(),cache:'no-store'});
      if(!r.ok)return{ok:false,error:`HTTP ${r.status}`,cid,age};
      const obj=await r.json();const ranks=Array.isArray(obj?.ranks)?obj.ranks:[];if(!ranks.length)return{ok:false,error:'empty_ranks',cid,age,response_status:obj?.statusCode,returnCode:obj?.returnCode};
      for(const x of ranks){const kw=trendNorm(x?.keyword||'');const k=kw.toLowerCase().replace(/[^0-9a-z가-힣]/g,'');if(!k||seen.has(k))continue;seen.add(k);cards.push({keyword:kw,name:kw,rank_hint:Number(x?.rank||cards.length+1),text:kw,url:location.href,source:'datalab_same_origin_internal'});if(cards.length>=limit)break;}
      if(cards.length>=limit)break;await trendWait(180);
    }
    return{ok:cards.length>0,cards:cards.slice(0,limit),cid,age,startDate:trendDateISO(start),endDate:trendDateISO(end),method:'same_origin_internal_post'};
  }catch(e){return{ok:false,error:String(e),cid,age};}
}
async function collectNaverDataLabTrend(msg){
  // v8.00 API-key-free fast path: use the exact same-origin JSON request the
  // DataLab page itself uses. This is not the authenticated NAVER Open API.
  const direct=await naverDataLabDirectRanks(msg);
  if(direct.ok)return{status:"ok",site:site(),url:location.href,cards:direct.cards,filter_state:{direct},aggregation_mode:"same_origin_internal_request",
    error:"",debug:{collector:"naver_datalab_no_api_fast_v8_00",browser_clicks:0}};
  // If Naver changes the internal request contract, fall back to the visible UI.
  const filter={direct_fallback:direct};
  filter.category=await trendSetCategory(msg.category_label||msg.blog_category||msg.query||"");
  if(Number(msg.period_days||30)<=31){filter.period=trendClickExact(["1개월","최근 1개월","최근 30일"]);await trendWait(220);}
  if(msg.gender&&msg.gender!=="전체"){filter.gender=trendSetChecked(msg.gender,true)||trendClickExact(msg.gender);await trendWait(150);}else{filter.gender="전체";}
  filter.age=await trendSetAgeRange(msg.age_codes||[]);await trendWait(220);
  if(!filter.age?.ok)return{status:"error",site:site(),url:location.href,cards:[],filter_state:filter,
    error:"네이버 데이터랩에서 선택한 연령대만 적용됐는지 확인되지 않아 수집을 중단했습니다."};
  const before=extractTrendKeywords(30).slice(0,8).map(x=>x.keyword).join('|');filter.apply=trendClickExact(["조회하기","조회","적용"]);
  const changed=await trendWaitForKeywordChange(before,3200);let cards=changed.cards?.length?changed.cards:extractTrendKeywords(msg.limit||30);
  if(cards.length<Number(msg.limit||30)){window.scrollBy({top:Math.max(600,innerHeight*.75),behavior:"instant"});await trendWait(450);cards=extractTrendKeywords(msg.limit||30);}
  filter.age_after_apply=trendVerifyAgeChecks(trendAgeCodes(msg.age_codes));
  if(!filter.age_after_apply.ok)return{status:"error",site:site(),url:location.href,cards:[],filter_state:filter,
    error:"네이버 데이터랩 조회 후 연령대 선택이 달라져 수집 결과를 제외했습니다."};
  return{status:cards.length?"ok":"error",site:site(),url:location.href,cards:cards.slice(0,Number(msg.limit||30)),filter_state:filter,aggregation_mode:"visible_ui_fallback",
    error:cards.length?"":"네이버 데이터랩 조건 적용 후 인기검색어 순위를 찾지 못했습니다.",
    debug:{collector:"naver_datalab_ui_fallback_v8_00",direct_error:direct.error||"",body_head:trendNorm(document.body?.innerText||"").slice(0,1200)}};
}


async function collect(msg){
 if(blocked())return{status:"blocked",site:site(),cards:[]};
 if(site()==="토스쇼핑"&&tossLogin())return{status:"login_required",cards:[]};

 if(msg.mode==="trend_keyword_collect"){
   if(site()==="아이템스카우트")return await collectItemScoutTrend(msg);
   if(site()==="네이버데이터랩")return await collectNaverDataLabTrend(msg);
   return{status:"error",site:site(),cards:[],error:"트렌드 수집 페이지가 아닙니다: "+location.href};
 }

 if(msg.mode==="category_discovery"){
   const categories=await discoverNativeCategories(msg.limit||30);
   return{
     status:"ok",site:site(),url:location.href,categories,
     devicePixelRatio:window.devicePixelRatio||1,
     viewportWidth:innerWidth,viewportHeight:innerHeight
   };
 }

 if(msg.mode==="fixed_category_collect"){
   let minDocY=0,anchorOk=true,anchorLabel="";
   if(site()==="쿠팡"){
     const ar=await ensureCoupangRankingAnchor(msg.ranking_anchor||"쿠팡 랭킹순",18000);
     if(!ar.ok)return{status:"error",error:ar.error,ranking_anchor_confirmed:false};
     minDocY=ar.docY;anchorLabel=ar.label;anchorOk=true;
   }
   const tossBefore=site()==="토스쇼핑"?tossCategoryState():null;
   let tossTxnBefore=null,tossWanted=null;
   if(site()==="토스쇼핑"){
     tossWanted=tossCategoryDefByLabel(msg.site_category_label||msg.category_label||"",[]);
     tossTxnBefore=tossTxnGet();
     // v7.22 do not reject the real Sharelink filter merely because its custom
     // checkbox exposes no aria/data checked state. The route transaction is the
     // authoritative proof that exactly one ON click was issued for this category.
     if(!tossWanted||!tossTxnBefore||normalizeLabel(tossTxnBefore.site||'')!==normalizeLabel(tossWanted.site)||Number(tossTxnBefore.on_clicks||0)!==1||Number(tossTxnBefore.off_clicks||0)!==0){
       return{status:"error",site:site(),url:location.href,cards:[],category_confirmed:false,
         error:`토스 수집 직전 필터 트랜잭션 검증 실패: ${tossTxnBefore?.site||'없음'}`,
         toss_checked_before_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],toss_uncheck_after_collect:false,
         debug:routeDebug({toss_category_state:tossCategoryState(),toss_transaction:tossTxnBefore})};
     }
   }
   let cs=[],tossCollect=null;
   if(site()==="토스쇼핑"){
     // v7.30 PRIMARY: product names come from whole rendered text + MAIN-world data feed
     // (fetch/XHR/Response + rendered-history) and an independently detected
     // internal virtual-list scroller.  Do not parse/uncheck in the isolated
     // content world; background.js owns the full 30-product transaction.
     const dbg=routeDebug({collector:"toss_price_anchor_v7_32",wanted:msg.limit||30,collected:0,
       toss_before:tossBefore,toss_txn_before:tossTxnBefore,price_anchor_required:true});
     return{status:"toss_price_anchor_collect_required",site:site(),url:location.href,cards:[],category_confirmed:true,
       toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,toss_uncheck_after_collect:false,
       toss_checked_before_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],toss_checked_after_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],debug:dbg};
   }else{
     cs=await collectCardsWithScroll(msg.limit||30,null,false,minDocY);
   }
   const e=controlByAliases([msg.site_category_label||msg.category_label||""]);
   let tossCleanup=null;
   // v7.28 strict ordering: NEVER uncheck a Toss category when fewer than
   // the requested products were parsed.  Keep the filter ON so background.js
   // can run a deep all-frame/shadow-DOM fallback first.  This fixes the real
   // user-visible bug where ON -> parser 0 -> immediate OFF happened.
   if(site()==="토스쇼핑" && cs.length<(msg.limit||30)){
     const dbg=routeDebug({collector:"fixed_category_collect",wanted:msg.limit||30,collected:cs.length,
       toss_before:tossBefore,toss_after:null,toss_collect:tossCollect,toss_txn_before:tossTxnBefore,toss_cleanup:null,deep_fallback_required:true});
     return{status:"toss_deep_fallback_required",site:site(),url:location.href,cards:cs,category_confirmed:true,
       error:tossCollect?.error||`${msg.site_category_label||msg.category_label||"카테고리"}: ${(msg.limit||30)}개 목표 중 ${cs.length}개 수집`,
       toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,toss_uncheck_after_collect:false,
       toss_checked_before_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],toss_checked_after_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],debug:dbg};
   }
   if(site()==="토스쇼핑"){
     // OFF is issued exactly once only after the requested count is actually full.
     tossCleanup=await tossUncheckTransaction(msg.site_category_label||msg.category_label||"");
   }
   const dbg=routeDebug({collector:"fixed_category_collect",wanted:msg.limit||30,collected:cs.length,
     toss_before:tossBefore,toss_after:tossCleanup?.after||null,toss_collect:tossCollect,toss_txn_before:tossTxnBefore,toss_cleanup:tossCleanup});
   if(site()==="토스쇼핑"&&(!tossCleanup||!tossCleanup.ok))return{
     status:"error",site:site(),url:location.href,cards:cs,
     error:`토스 ${msg.site_category_label||msg.category_label||"카테고리"} 수집 후 체크 해제 검증 실패`,
     category_confirmed:true,toss_single_checkbox_confirmed:true,toss_uncheck_after_collect:false,
     toss_checked_before_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],
     toss_checked_after_collect:(tossCleanup?.after||[]).filter(x=>x.checked).map(x=>x.site),debug:dbg
   };
   if(cs.length<(msg.limit||30))return{
     status:"error",site:site(),url:location.href,cards:cs,
     error:site()==="토스쇼핑"?(tossCollect?.error||`${msg.site_category_label||msg.category_label||"카테고리"}: ${(msg.limit||30)}개 목표 중 ${cs.length}개 수집`):`${msg.site_category_label||msg.category_label||"카테고리"}: ${(msg.limit||30)}개 목표 중 ${cs.length}개 수집`,
     category_confirmed:true,ranking_anchor_confirmed:site()!=="쿠팡"||anchorOk,ranking_anchor_label:anchorLabel,
     toss_single_checkbox_confirmed:site()!=="토스쇼핑"||true,toss_uncheck_after_collect:site()!=="토스쇼핑"||!!tossCleanup?.ok,
     toss_checked_before_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],
     toss_checked_after_collect:(tossCleanup?.after||[]).filter(x=>x.checked).map(x=>x.site),debug:dbg
   };
   return{
     status:"ok",site:site(),url:location.href,cards:cs,category_confirmed:true,
     ranking_anchor_confirmed:site()!=="쿠팡"||anchorOk,ranking_anchor_label:anchorLabel,
     toss_product_lookup_confirmed:site()!=="토스쇼핑"||true,
     toss_single_checkbox_confirmed:site()!=="토스쇼핑"||true,
     toss_uncheck_after_collect:site()!=="토스쇼핑"||!!tossCleanup?.ok,
     toss_checked_before_collect:tossTxnBefore?.site?[tossTxnBefore.site]:[],
     toss_checked_after_collect:(tossCleanup?.after||[]).filter(x=>x.checked).map(x=>x.site),
     category_label:msg.site_category_label||msg.category_label||"",
     clicked_label:e?txt(e).trim():(msg.site_category_label||msg.category_label||""),
     devicePixelRatio:window.devicePixelRatio||1,
     viewportWidth:innerWidth,viewportHeight:innerHeight,debug:dbg
   };
 }

 if(msg.mode==="category_collect"){
   const cs=await collectCategoryProducts(msg.limit||6);
   return{
     status:"ok",site:site(),url:location.href,cards:cs,
     category_label:msg.category_label||"",
     devicePixelRatio:window.devicePixelRatio||1,
     viewportWidth:innerWidth,viewportHeight:innerHeight
   };
 }

 if(msg.mode==="detail"){
   // Fast path: first expose lazy/data-src URLs without repeatedly scrolling the
   // page. The background worker only performs rendered crops if direct detail
   // image saving is still needed.
   const images=msg.fast_capture_only ? scanDetailImages(Math.max(msg.limit||12,24)) : await collectDetailImagesWithScroll(msg.limit||12,msg.detail_scroll_rounds||7,msg.detail_scroll_wait_ms||850);
   const body=(document.body?.innerText||"").replace(/\s+/g," ").slice(0,18000);
   const title=(document.title||"").replace(/\s+/g," ").trim();
   return{
     status:"ok",site:site(),url:location.href,
     detail_images:images,
     page_text:body,page_title:title,
     devicePixelRatio:window.devicePixelRatio||1,
     viewportWidth:innerWidth,viewportHeight:innerHeight
   };
 }

 let cs=cards(msg.limit||10),selected=null;
 if(msg.mode==="trend_coupang_pick"&&site()==="쿠팡"){
   // Scroll just enough to build a bounded candidate pool, then choose one
   // concrete product for this trend keyword from visible popularity signals.
   cs=await collectCardsWithScroll(msg.limit||24,null,false,0);
   const pick=chooseCoupangTrendProduct(cs,msg.query||"");
   cs=pick.cards;selected=pick.selected;
 }
 if(msg.mode==="price"&&msg.target){
   const compactToken=x=>String(x||"").toLowerCase().replace(/\s/g,"");
   const critical=(msg.critical_tokens&&msg.critical_tokens.length?msg.critical_tokens:crit(msg.target)).map(compactToken);
   const identity=(msg.identity_tokens&&msg.identity_tokens.length?msg.identity_tokens:tokens(msg.target)).map(x=>String(x).toLowerCase()).filter(Boolean);
   const signature=(msg.signature_tokens||[]).map(x=>String(x).toLowerCase()).filter(Boolean);
   const threshold=Number(msg.match_threshold||0.62),softThreshold=Math.min(threshold,0.48);
   const aliases=t=>{const x=compactToken(t),a=[x];let m=x.match(/^(\d+(?:\.\d+)?)(개입)$/);if(m)a.push(m[1]+"개");return[...new Set(a)]};
   const tokenScore=(text,target)=>{const low=String(text||"").toLowerCase(),ts=tokens(String(target||""));if(!ts.length)return 0;return ts.filter(x=>low.includes(x)).length/ts.length;};
   let best=-1;
   for(const c of cs){
     const compact=compactToken(c.text||"");
     const missing=critical.filter(x=>!aliases(x).some(a=>compact.includes(a)));
     if(missing.length)continue; // capacity/model/count remain hard guards
     const low=(c.text||"").toLowerCase();
     const core=identity.slice(0,3),coreHits=core.filter(x=>low.includes(x));
     if(core.length&&!coreHits.length)continue;
     const signatureMissing=signature.filter(x=>!low.includes(x));
     const identityPool=identity.slice(0,8),identityHits=identityPool.filter(x=>low.includes(x));
     const needHits=Math.max(2,Math.min(4,Math.ceil(identityPool.length/2)));
     const sc=tokenScore(c.text,msg.target);
     const strictOk=!signatureMissing.length && sc>=Math.max(0.58,threshold);
     const balancedOk=identityHits.length>=needHits && sc>=softThreshold;
     if(!(strictOk||balancedOk))continue;
     if(sc>best || (Math.abs(sc-best)<0.0001 && selected && c.price<selected.price)){
       best=sc;selected={...c,score:sc,match_detail:{critical,missing:[],core,core_hits:coreHits,core_hit:true,signature,signature_missing:signatureMissing,identity_hits:identityHits,identity_required:needHits,threshold,match_mode:strictOk?"browser_strict":"browser_balanced"}};
     }
   }
   if(selected){
     const els=[...document.querySelectorAll(selectors().join(","))].filter(vis);
     let chosen=null;
     for(const e of els){if(txt(e)===selected.text){chosen=e;break;}}
     if(chosen){
       chosen.scrollIntoView({block:"center",behavior:"instant"});
       await sleep(350);selected.rect=rect(chosen);
       const im=imgOf(chosen);selected.imageRect=im?.rect||null;
     }
   }
 }
 return{status:"ok",site:site(),url:location.href,cards:cs,selected,
   devicePixelRatio:window.devicePixelRatio||1,viewportWidth:innerWidth,viewportHeight:innerHeight};
}
chrome.runtime.onMessage.addListener((m,sender,sendResponse)=>{
 if(m?.type==="performSearch"){performSearch(m.site,m.query,m.action,m.category_label,m).then(sendResponse);return true;}
 if(m?.type==="collect"){collect(m).then(sendResponse);return true;}
 if(m?.type==="tossFinalizeCategory"){
   tossUncheckTransaction(m.site_category_label||m.category_label||"").then(r=>sendResponse({status:r?.ok?"ok":"error",cleanup:r,toss_uncheck_after_collect:!!r?.ok,toss_checked_after_collect:(r?.after||[]).filter(x=>x.checked).map(x=>x.site)}));return true;
 }
});
if(location.hostname==="127.0.0.1"){
  try{chrome.runtime.sendMessage({type:"collectorPageAlive"});}catch(e){}
}

async function bridgeHeartbeatDirect(){
  try{
    await fetch("http://127.0.0.1:8765/api/heartbeat",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        ts:Date.now(),
        extension_version:chrome.runtime.getManifest().version,
        source:"collector_content"
      })
    });
  }catch(e){}
}
if(location.hostname==="127.0.0.1"){
  bridgeHeartbeatDirect();
  try{chrome.runtime.sendMessage({type:"collectorPageAlive"});}catch(e){}
  const params=new URLSearchParams(location.search);
  const rid=params.get("run_id");
  if(params.get("autostart")==="1" && rid){
    let tries=0;
    const kick=()=>{
      tries++;
      chrome.runtime.sendMessage({type:"collectorAutostart",runId:rid},resp=>{
        if(resp?.ok){
          console.log("collector autostart ok",resp);
        }else if(tries<5){
          setTimeout(kick,800);
        }
      });
    };
    kick();
  }
}
})();
