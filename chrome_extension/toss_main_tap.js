(()=>{
  if(window.__NVB_TOSS_FEED?.version==='1.2.0') return;
  const prev=window.__NVB_TOSS_FEED;
  const store={
    version:'1.2.0',items:new Map(),
    stats:{fetchHits:0,xhrHits:0,responseJsonHits:0,responseTextHits:0,jsonParsed:0,textParsed:0,mutationHits:0,bodyScans:0,bodyCandidates:0,scriptScans:0,renderScans:0,ingestErrors:0},
    urls:[],startedAt:Date.now(),lastBodyLines:0
  };
  const norm=s=>String(s??'').replace(/\s+/g,' ').trim();
  const key=s=>norm(s).toLowerCase().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');
  const PRICE_RX=/(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원/g;
  const BAD_EXACT=/^(?:상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|더보기|다음|이전|오늘만\s*이\s*가격에\s*살\s*수\s*있는\s*하루특가|30일\s*최저가|무료배송|배송|쿠폰|할인|혜택|적립|광고|리뷰|평점)$/i;
  const BAD_CONTAINS=/(?:개당\s*)?\d[\d,]*\s*원\s*수익|수수료|정산|실적|API\s*키|하나은행|확정\s*수익금|소득세|지방\s*소득세|가이드|의견\s*남기기/i;
  const noise=s=>{s=norm(s);return !s||s.length<3||s.length>240||!/[A-Za-z가-힣]/.test(s)||BAD_EXACT.test(s)||BAD_CONTAINS.test(s)};
  const cleanName=s=>norm(s)
    .replace(/(?:개당\s*)?\d{1,3}(?:,\d{3})+\s*원(?:\s*수익)?/g,' ')
    .replace(/\b\d{1,3}\s*%\s*(?:특가|할인)?\b/g,' ')
    .replace(/\b30일\s*최저가\b/g,' ')
    .replace(/\b(?:무료배송|오늘만\s*특가|특가)\b/g,' ')
    .replace(/\s+/g,' ').trim();
  const priceNum=v=>{
    if(typeof v==='number'&&Number.isFinite(v)&&v>0)return Math.round(v);
    const m=norm(v).match(/(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원?/);return m?parseInt(m[1].replaceAll(',','')):null;
  };
  function add(name,price=0,url='',source=''){
    name=cleanName(name); if(noise(name))return false;
    // Reject lines that are effectively only a price/promotion after cleanup.
    if(!/[A-Za-z가-힣]/.test(name))return false;
    const k=key(name); if(!k||k.length<3)return false;
    price=priceNum(price)||0; const old=store.items.get(k);
    const rec={name,price,text:(name+(price?' '+price.toLocaleString()+'원':'')),url:norm(url),image_url:'',source};
    if(!old || ((price&&!old.price)||(rec.url&&!old.url))) store.items.set(k,Object.assign({},old||{},rec));
    return true;
  }
  const NAME_KEYS=['productName','product_name','name','title','itemName','item_name','displayName','productTitle','goodsName','goods_name','product_title','itemTitle','productNm','goodsNm'];
  const PRICE_KEYS=['salePrice','sale_price','finalPrice','final_price','discountPrice','discount_price','sellingPrice','selling_price','price','amount','lowestPrice','saleAmount','discountedPrice'];
  const URL_KEYS=['productUrl','product_url','url','link','landingUrl','landing_url','shareUrl','webUrl'];
  function walk(obj,source='',depth=0,seen=new WeakSet()){
    if(depth>14||obj==null)return;
    if(typeof obj==='string'){
      const t=obj.trim();
      if(t.length<1000000&&/^[\[{]/.test(t)){try{walk(JSON.parse(t),source,depth+1,seen);store.stats.jsonParsed++;}catch(_){}}
      return;
    }
    if(typeof obj!=='object')return; if(seen.has(obj))return; seen.add(obj);
    if(Array.isArray(obj)){for(const x of obj)walk(x,source,depth+1,seen);return;}
    let name=''; for(const k of NAME_KEYS){if(typeof obj[k]==='string'&&obj[k].trim()){name=obj[k];break}}
    let price=0; for(const k of PRICE_KEYS){const n=priceNum(obj[k]);if(n){price=n;break}}
    let url=''; for(const k of URL_KEYS){if(typeof obj[k]==='string'&&obj[k].trim()){url=obj[k];break}}
    if(name) add(name,price,url,source||'json');
    for(const v of Object.values(obj)){if(v&&typeof v==='object')walk(v,source,depth+1,seen)}
  }
  function ingestText(text,url='',source='text'){
    text=String(text??''); if(!text)return; store.stats.textParsed++;
    if(text.length<3000000&&/^[\s]*[\[{]/.test(text)){try{walk(JSON.parse(text),source);store.stats.jsonParsed++;}catch(_){}}
    const pats=[/"(?:productName|product_name|itemName|displayName|productTitle|goodsName|productNm|goodsNm|title)"\s*:\s*"([^"\\]{3,240})"/g,/"name"\s*:\s*"([^"\\]{3,240})"/g];
    for(const re of pats){let m,c=0;while((m=re.exec(text))&&c++<500)add(m[1],0,url,source)}
  }
  function noteUrl(u){u=norm(u);if(!u)return;if(!store.urls.includes(u))store.urls.push(u);if(store.urls.length>50)store.urls.shift()}

  // ---- Network data tap. It is useful when category selection triggers API calls. ----
  const origFetch=window.fetch;
  if(typeof origFetch==='function'&&!origFetch.__nvbWrapped){
    const wf=async function(...args){
      const r=await origFetch.apply(this,args);
      try{store.stats.fetchHits++;noteUrl(r.url||args?.[0]?.url||args?.[0]);const c=r.clone();c.text().then(t=>ingestText(t,r.url,'fetch')).catch(()=>{});}catch(e){store.stats.ingestErrors++;}
      return r;
    }; wf.__nvbWrapped=true; window.fetch=wf;
  }
  const op=XMLHttpRequest.prototype.open, os=XMLHttpRequest.prototype.send;
  if(!op.__nvbWrapped){
    XMLHttpRequest.prototype.open=function(m,u,...rest){this.__nvbUrl=u;return op.call(this,m,u,...rest)};
    XMLHttpRequest.prototype.open.__nvbWrapped=true;
    XMLHttpRequest.prototype.send=function(...args){
      if(!this.__nvbHooked){this.__nvbHooked=true;this.addEventListener('loadend',()=>{try{store.stats.xhrHits++;noteUrl(this.responseURL||this.__nvbUrl);if(this.responseType==='json')walk(this.response,'xhr');else if(!this.responseType||this.responseType==='text')ingestText(this.responseText||'',this.responseURL,'xhr')}catch(e){store.stats.ingestErrors++;}})}
      return os.apply(this,args)
    };
  }
  const oj=Response.prototype.json, ot=Response.prototype.text;
  if(!oj.__nvbWrapped){Response.prototype.json=async function(...a){const v=await oj.apply(this,a);try{store.stats.responseJsonHits++;walk(v,'response.json')}catch(e){store.stats.ingestErrors++}return v};Response.prototype.json.__nvbWrapped=true;}
  if(!ot.__nvbWrapped){Response.prototype.text=async function(...a){const v=await ot.apply(this,a);try{store.stats.responseTextHits++;ingestText(v,this.url,'response.text')}catch(e){store.stats.ingestErrors++}return v};Response.prototype.text.__nvbWrapped=true;}

  // ---- DOM/visible-text collection independent of CSS card classes. ----
  function visible(e){try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>2&&r.height>2&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0.02;}catch(_){return false}}
  function goodNameLine(line){const c=cleanName(line);if(noise(c))return'';if(/^(?:원가|할인율|배송비|무료배송|별점|리뷰|찜하기|판매처|30일\s*최저가)/.test(c))return'';if(/^\d+\s*위$/.test(c))return'';return c;}
  function parseRenderedText(text,source='body_text'){
    const raw=String(text||'').split(/\n+/).map(x=>norm(x)).filter(Boolean);
    store.lastBodyLines=raw.length; let hits=0;
    // 1) Every visible price line acts as an anchor. Product name is normally the
    // nearest preceding non-promo line in the same virtual-list row/card.
    for(let i=0;i<raw.length;i++){
      const line=raw[i]; if(!/\d[\d,]*\s*원/.test(line))continue;
      if(/개당\s*\d[\d,]*\s*원\s*수익|수익/.test(line)&&!/(?:^|\s)\d[\d,]*\s*원(?:\s|$)/.test(line.replace(/개당\s*\d[\d,]*\s*원\s*수익/g,'')))continue;
      let price=priceNum(line)||0, name='';
      const same=goodNameLine(line.replace(PRICE_RX,' ').replace(/\b\d{1,3}\s*%\s*(?:특가|할인)?\b/g,' '));
      if(same&&same.length>=4)name=same;
      if(!name){
        for(let j=i-1;j>=Math.max(0,i-7);j--){
          const c=goodNameLine(raw[j]);
          if(!c)continue;
          if(/\d[\d,]*\s*원/.test(raw[j])||/수익|할인율|배송|별점|리뷰|쿠폰|특가/.test(c))continue;
          name=c;break;
        }
      }
      if(name&&add(name,price,'',source))hits++;
    }
    // 2) Some compact rows expose product and price on the same line without a
    // line break. Strip the price/promo tail and keep the readable product text.
    for(const line of raw){
      if(!/\d[\d,]*\s*원/.test(line))continue;
      const c=goodNameLine(line.replace(/(?:개당\s*)?\d[\d,]*\s*원(?:\s*수익)?/g,' ').replace(/\d{1,3}\s*%\s*(?:특가|할인)?/g,' '));
      if(c&&c.length>=4&&add(c,priceNum(line)||0,'',source+'_same_line'))hits++;
    }
    store.stats.bodyCandidates+=hits;return hits;
  }
  function scanBodyText(){
    try{store.stats.bodyScans++;const body=document.body;if(!body)return 0;return parseRenderedText(body.innerText||body.textContent||'','body_text');}
    catch(e){store.stats.ingestErrors++;return 0}
  }
  function scanRendered(root=document){
    try{
      store.stats.renderScans++;
      const sels='article,li,tr,[role="row"],[role="listitem"],a[href],button,div';
      const nodes=[...root.querySelectorAll(sels)]; let hits=0,seen=0;
      for(const e of nodes){if(seen++>7000||hits>400)break;if(!visible(e))continue;const t=norm(e.innerText||e.textContent||'');if(!t||t.length>1200)continue;if(!/\d[\d,]*\s*원/.test(t))continue;
        const before=store.items.size;parseRenderedText(String(e.innerText||e.textContent||''),'rendered');if(store.items.size>before)hits+=store.items.size-before;
      }
      return hits;
    }catch(e){store.stats.ingestErrors++;return 0}
  }
  function scanEmbeddedJson(){
    let hits=0;
    try{
      store.stats.scriptScans++;
      const candidates=[];
      for(const s of document.querySelectorAll('script[type="application/json"],script#__NEXT_DATA__,script[data-hypernova-key],script')){
        const t=s.textContent||'';if(t.length<20||t.length>2500000)continue;if(!/(product|goods|item|salePrice|price|상품)/i.test(t))continue;candidates.push(t);if(candidates.length>=30)break;
      }
      for(const t of candidates){const before=store.items.size;ingestText(t,'','embedded_script');hits+=Math.max(0,store.items.size-before)}
      for(const k of ['__NEXT_DATA__','__APOLLO_STATE__','__INITIAL_STATE__']){try{const v=window[k];if(v){const before=store.items.size;walk(v,'window.'+k);hits+=Math.max(0,store.items.size-before)}}catch(_){}}
    }catch(e){store.stats.ingestErrors++;}
    return hits;
  }
  let mutationTimer=null;
  const mo=new MutationObserver(ms=>{
    store.stats.mutationHits+=ms.length;
    clearTimeout(mutationTimer);
    mutationTimer=setTimeout(()=>{scanBodyText();scanRendered(document)},120);
  });
  try{mo.observe(document.documentElement,{childList:true,subtree:true,characterData:true})}catch(_){ }

  function productLineSamples(){
    try{const lines=String(document.body?.innerText||'').split(/\n+/).map(norm).filter(Boolean),out=[];for(let i=0;i<lines.length&&out.length<120;i++){if(/\d[\d,]*\s*원/.test(lines[i])){for(let j=Math.max(0,i-2);j<=Math.min(lines.length-1,i+1);j++){const x=lines[j];if(x&&!out.includes(x))out.push(x);if(out.length>=120)break;}}}return out}catch(_){return[]}
  }
  store.snapshot=(limit=180)=>{
    scanBodyText();scanRendered(document);scanEmbeddedJson();
    const cards=[...store.items.values()].slice(0,Math.max(30,Number(limit||180)));const sourceCounts={};for(const c of cards)sourceCounts[c.source||'unknown']=(sourceCounts[c.source||'unknown']||0)+1;
    return{version:store.version,cards,stats:Object.assign({},store.stats),urls:[...store.urls],startedAt:store.startedAt,now:Date.now(),bodyLines:store.lastBodyLines,sourceCounts,samples:productLineSamples()};
  };
  store.reset=()=>{
    store.items.clear();store.urls.length=0;
    store.stats={fetchHits:0,xhrHits:0,responseJsonHits:0,responseTextHits:0,jsonParsed:0,textParsed:0,mutationHits:0,bodyScans:0,bodyCandidates:0,scriptScans:0,renderScans:0,ingestErrors:0};
    store.startedAt=Date.now();store.lastBodyLines=0;return true;
  };
  // Cross-world reset hook: content.js can dispatch this before category ON if
  // the click path does not need the background MAIN-world fallback.
  document.addEventListener('__NVB_TOSS_FEED_RESET',()=>{try{store.reset()}catch(_){}});
  window.__NVB_TOSS_FEED=store;
  scanBodyText();scanRendered(document);scanEmbeddedJson();
})();
