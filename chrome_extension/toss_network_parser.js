(function(global){
  'use strict';
  const NAME_KEYS=[
    'productName','product_name','productNm','product_nm','productTitle','product_title',
    'itemName','item_name','itemTitle','item_title','goodsName','goods_name','goodsNm','goods_nm',
    'displayName','display_name','displayTitle','title','name'
  ];
  const PRICE_KEYS=[
    'salePrice','sale_price','finalPrice','final_price','discountPrice','discount_price',
    'sellingPrice','selling_price','lowestPrice','lowest_price','productPrice','product_price',
    'saleAmount','discountedPrice','amount','price'
  ];
  const URL_KEYS=['productUrl','product_url','landingUrl','landing_url','shareUrl','share_url','webUrl','web_url','url','link'];
  const IMAGE_KEYS=['imageUrl','image_url','thumbnailUrl','thumbnail_url','productImage','product_image','image','thumbnail'];
  const ID_RX=/(?:^|_)(?:product|goods|item)(?:id|no|number|code|key)(?:$|_)/i;
  const NAME_KEY_RX=/(?:product|goods|item).*(?:name|title)|(?:name|title).*(?:product|goods|item)|^(?:displayName|displayTitle|name|title|label)$/i;
  const PRICE_KEY_RX=/(?:sale|selling|final|discount|lowest|product)?(?:price|amount|cost)/i;
  const BAD_PRICE_KEY_RX=/(commission|profit|income|reward|earning|fee|settle|payout|수익|수수료|정산)/i;
  const BAD_EXACT=/^(?:상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|더보기|다음|이전|가전\/디지털|뷰티|생활용품|식품|주방용품|패션의류잡화)$/i;
  const BAD_CONTAINS=/(?:개당\s*)?\d[\d,]*\s*원\s*수익|수수료|정산|실적|API\s*키|확정\s*수익금|소득세|지방\s*소득세|가이드|의견\s*남기기/i;
  const norm=s=>String(s??'').replace(/\\u([0-9a-fA-F]{4})/g,(_,h)=>{try{return String.fromCharCode(parseInt(h,16))}catch(_e){return _}}).replace(/\\\//g,'/').replace(/\s+/g,' ').trim();
  const key=s=>norm(s).toLowerCase().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');
  function cleanName(s){
    return norm(s)
      .replace(/(?:개당\s*)?\d{1,3}(?:,\d{3})+\s*원(?:\s*수익)?/g,' ')
      .replace(/\b\d{1,3}\s*%\s*(?:특가|할인)?\b/g,' ')
      .replace(/\b30일\s*최저가\b/g,' ')
      .replace(/\b(?:무료배송|오늘만\s*특가|특가)\b/g,' ')
      .replace(/\s+/g,' ').trim();
  }
  function noise(s){s=cleanName(s);return !s||s.length<2||s.length>260||!/[A-Za-z가-힣]/.test(s)||BAD_EXACT.test(s)||BAD_CONTAINS.test(s)}
  function priceNum(v){
    if(typeof v==='number'&&Number.isFinite(v)&&v>=100&&v<=1000000000)return Math.round(v);
    const m=norm(v).match(/(\d{1,3}(?:,\d{3})+|\d{3,10})\s*원?/);if(!m)return 0;
    const n=parseInt(m[1].replaceAll(',',''));return Number.isFinite(n)&&n>=100&&n<=1000000000?n:0;
  }
  function createStore(){return{items:new Map(),stats:{bodies:0,jsonParsed:0,objects:0,objectCandidates:0,regexCandidates:0,errors:0},urls:[]}}
  function add(store,name,price=0,url='',image='',source=''){
    name=cleanName(name);if(noise(name))return false;const k=key(name);if(!k||k.length<2)return false;
    price=priceNum(price);const old=store.items.get(k);const rec={name,price:price||0,url:norm(url),image_url:norm(image),text:name+(price?` ${price.toLocaleString()}원`:''),source:source||'chrome_network'};
    const oldScore=old?((old.price?3:0)+(old.url?2:0)+(old.image_url?1:0)): -1;
    const newScore=(rec.price?3:0)+(rec.url?2:0)+(rec.image_url?1:0);
    if(!old||newScore>oldScore)store.items.set(k,Object.assign({},old||{},rec));
    return true;
  }
  function bestField(obj,keys,rx,kind){
    const cand=[];
    for(const [k,v] of Object.entries(obj||{})){
      if(kind==='name'&&typeof v==='string'){
        let score=0;if(keys.includes(k))score=120;else if(rx.test(k))score=90;else continue;
        const vv=cleanName(v);if(noise(vv))continue;if(/product|goods|item/i.test(k))score+=30;if(/title|name/i.test(k))score+=10;
        cand.push({v:vv,score,k});
      }else if(kind==='price'){
        if(BAD_PRICE_KEY_RX.test(k))continue;let score=0;if(keys.includes(k))score=120;else if(rx.test(k))score=75;else continue;
        const n=priceNum(v);if(!n)continue;if(/sale|selling|final|discount|lowest|product/i.test(k))score+=20;cand.push({v:n,score,k});
      }else if(kind==='url'&&typeof v==='string'){
        if(keys.includes(k)||/(product|landing|share|web)?url|link/i.test(k))cand.push({v,score:keys.includes(k)?100:60,k});
      }else if(kind==='image'&&typeof v==='string'){
        if(keys.includes(k)||/(image|thumbnail|thumb)/i.test(k))cand.push({v,score:keys.includes(k)?100:60,k});
      }
    }
    cand.sort((a,b)=>b.score-a.score);return cand[0]?.v|| (kind==='price'?0:'');
  }
  function walk(store,obj,source='json',url='',depth=0,seen=new WeakSet()){
    if(depth>18||obj==null)return;
    if(typeof obj==='string'){
      const t=obj.trim();if(t.length<2500000&&/^[\[{]/.test(t)){try{const j=JSON.parse(t);store.stats.jsonParsed++;walk(store,j,source,url,depth+1,seen)}catch(_e){}}
      return;
    }
    if(typeof obj!=='object')return;if(seen.has(obj))return;seen.add(obj);
    if(Array.isArray(obj)){for(const x of obj)walk(store,x,source,url,depth+1,seen);return;}
    store.stats.objects++;
    const name=bestField(obj,NAME_KEYS,NAME_KEY_RX,'name');
    const price=bestField(obj,PRICE_KEYS,PRICE_KEY_RX,'price');
    const href=bestField(obj,URL_KEYS,/(product|landing|share|web)?url|link/i,'url');
    const image=bestField(obj,IMAGE_KEYS,/(image|thumbnail|thumb)/i,'image');
    const productSignal=Object.keys(obj).some(k=>ID_RX.test(k)||/(product|goods|item)/i.test(k));
    if(name&&(productSignal||price||href)){if(add(store,name,price,href||url,image,source))store.stats.objectCandidates++;}
    for(const v of Object.values(obj))if(v&&typeof v==='object')walk(store,v,source,url,depth+1,seen);
  }
  function ingestText(store,text,url='',source='network'){
    try{
      text=String(text??'');if(!text)return;store.stats.bodies++;
      if(url&&!store.urls.includes(url)){store.urls.push(url);if(store.urls.length>80)store.urls.shift()}
      const trimmed=text.trim();
      if(trimmed.length<8000000&&/^[\[{]/.test(trimmed)){try{const j=JSON.parse(trimmed);store.stats.jsonParsed++;walk(store,j,source,url)}catch(_e){}}
      // Generic JSON-string fallback for GraphQL/custom API fields whose exact names are unknown.
      const rx=/"([^"\\]{1,100})"\s*:\s*"([^"\\]{2,260})"/g;let m,c=0;
      while((m=rx.exec(text))&&c++<5000){
        const k=m[1],v=m[2];if(!NAME_KEY_RX.test(k)&&!NAME_KEYS.includes(k))continue;
        if(add(store,v,0,url,'',source+'_regex'))store.stats.regexCandidates++;
      }
    }catch(_e){store.stats.errors++;}
  }
  function snapshot(store,limit=200){
    const cards=[...store.items.values()].slice(0,Math.max(30,Number(limit||200)));
    const sourceCounts={};for(const c of cards)sourceCounts[c.source||'unknown']=(sourceCounts[c.source||'unknown']||0)+1;
    return{cards,stats:Object.assign({},store.stats),urls:[...store.urls],sourceCounts,total:store.items.size};
  }
  global.NVBTossNetParser={createStore,add,walk,ingestText,snapshot,cleanName,noise,priceNum,key};
})(typeof self!=='undefined'?self:globalThis);
