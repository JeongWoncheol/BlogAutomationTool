importScripts('toss_network_parser.js');
const BRIDGE="http://127.0.0.1:8765";
const EXT_VERSION=chrome.runtime.getManifest().version;
let running=false, runId=null, workTabId=null, currentTask=null, stage=null, timer=null, watchdog=null;
let runGeneration=0;
let pageDialogGuard={attached:false,tabId:null,events:[],lastError:''};

// v7.43: while the logged-in Coupang detail page renders, keep a lightweight
// record of real image responses. This is a fallback for lazy/blob/CDN cases
// where re-downloading the URL outside Chrome fails although the browser has
// already received the bytes.
let coupangImageNet={entries:new Map(),stats:{responses:0,finished:0,bodySaved:0,bodyErrors:0},active:false,lastEventAt:0};
function resetCoupangImageNet(){coupangImageNet={entries:new Map(),stats:{responses:0,finished:0,bodySaved:0,bodyErrors:0},active:true,lastEventAt:Date.now()};}
function imageUrlKey(u){try{const x=new URL(String(u||''));return (x.origin+x.pathname).toLowerCase()}catch(_){return String(u||'').split('?')[0].toLowerCase()}}
function imageNetBadUrl(u){return /(logo|sprite|avatar|icon|badge|tracking|pixel|favicon|banner|advert|coupon|review|recommend|related|recent|ranking|loading|placeholder)/i.test(String(u||''));}
// v7.17: route retries must survive full-page navigation.  v7.16 passed a local
// attempt counter that reset to zero every time onUpdated fired, which could
// reload the same Coupang fallback URL forever.
let fixedRouteAttempts=0, fixedSameUrlStalls=0, fixedLastUrl="", fixedRouteProgress={}, fixedProgressKey="", fixedProgressStalls=0, tossMainWorldRescues=0, tossCategoryMainClicks=0;
const FIXED_ROUTE_MAX_ATTEMPTS=24;
const TOSS_SAME_PROGRESS_LIMIT=8;


// v7.32 Toss price-anchor screen collector; Network is fallback only.
// Routing/clicking remains on the proven DOM/MAIN-world path.  This debugger is
// attached only to observe the browser's actual Network responses, so Service
// Worker/cache/GraphQL responses that bypass page-level fetch/XHR wrappers can
// still provide the real product names.
let tossNet={attached:false,tabId:null,generation:0,store:NVBTossNetParser.createStore(),requests:new Map(),stats:{responses:0,bodies:0,bodyErrors:0,websocketFrames:0,attachErrors:0},lastError:''};
function tossNetReset(){
  tossNet.generation=Number(tossNet.generation||0)+1;
  tossNet.store=NVBTossNetParser.createStore();tossNet.requests=new Map();
  tossNet.stats={responses:0,bodies:0,bodyErrors:0,websocketFrames:0,attachErrors:tossNet.stats?.attachErrors||0};
  tossNet.lastError='';
}
function dbgSend(method,params={}){
  return new Promise((resolve,reject)=>{
    if(!tossNet.attached||!tossNet.tabId)return reject(new Error('Toss Network debugger not attached'));
    try{chrome.debugger.sendCommand({tabId:tossNet.tabId},method,params,(r)=>{const e=chrome.runtime.lastError;if(e)reject(new Error(e.message));else resolve(r||{});});}
    catch(e){reject(e)}
  });
}
async function tossNetAttach(reset=false){
  if(!workTabId)return{ok:false,error:'work tab missing'};
  try{
    if(tossNet.attached&&tossNet.tabId!==workTabId){try{await new Promise(r=>chrome.debugger.detach({tabId:tossNet.tabId},()=>r()))}catch(_e){}tossNet.attached=false;tossNet.tabId=null;}
    if(!tossNet.attached){
      await new Promise((resolve,reject)=>{chrome.debugger.attach({tabId:workTabId},'1.3',()=>{const e=chrome.runtime.lastError;if(e)reject(new Error(e.message));else resolve();});});
      tossNet.attached=true;tossNet.tabId=workTabId;
      await dbgSend('Network.enable',{maxTotalBufferSize:100000000,maxResourceBufferSize:10000000,maxPostDataSize:3000000});
      try{await dbgSend('Network.setCacheDisabled',{cacheDisabled:false});}catch(_e){}
    }
    if(reset)tossNetReset();
    return{ok:true,attached:true};
  }catch(e){tossNet.stats.attachErrors=(tossNet.stats.attachErrors||0)+1;tossNet.lastError=String(e);return{ok:false,error:String(e)}}
}
async function tossNetDetach(){
  if(!tossNet.attached||!tossNet.tabId)return;
  const id=tossNet.tabId;tossNet.attached=false;tossNet.tabId=null;
  try{await new Promise(r=>chrome.debugger.detach({tabId:id},()=>r()))}catch(_e){}
}
function tossNetSnapshot(limit=200){
  const snap=NVBTossNetParser.snapshot(tossNet.store,limit);
  snap.capture_stats=Object.assign({},tossNet.stats);snap.attached=!!tossNet.attached;snap.last_error=tossNet.lastError||'';return snap;
}
function tossNetResponseInteresting(p){
  const r=p?.response||{},u=String(r.url||'').toLowerCase(),m=String(r.mimeType||'').toLowerCase(),type=String(p?.type||'');
  if(!u)return false;
  if(['Image','Media','Font'].includes(type)||/^(image|video|audio|font)\//.test(m))return false;
  if(['XHR','Fetch'].includes(type))return true;
  if(/json|graphql|javascript|text/.test(m))return true;
  if(/api|product|goods|item|search|query|graphql|link|share/.test(u))return true;
  return false;
}
chrome.debugger.onEvent.addListener((source,method,params)=>{
  if(!tossNet.attached||source.tabId!==tossNet.tabId||!running||currentTask?.site!=='토스쇼핑')return;
  if(method==='Network.responseReceived'&&tossNetResponseInteresting(params)){
    tossNet.stats.responses++;tossNet.requests.set(params.requestId,{url:params.response?.url||'',mime:params.response?.mimeType||'',type:params.type||'',status:params.response?.status||0,generation:tossNet.generation});
    return;
  }
  if(method==='Network.loadingFinished'){
    const meta=tossNet.requests.get(params.requestId);if(!meta)return;
    tossNet.requests.delete(params.requestId);
    const gen=meta.generation;
    dbgSend('Network.getResponseBody',{requestId:params.requestId}).then(b=>{
      if(gen!==tossNet.generation)return;
      let body=b?.body||'';if(b?.base64Encoded){try{const bin=atob(body),bytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);body=new TextDecoder('utf-8',{fatal:false}).decode(bytes)}catch(_e){}}
      if(body){tossNet.stats.bodies++;NVBTossNetParser.ingestText(tossNet.store,body,meta.url,'chrome_network');}
    }).catch(e=>{tossNet.stats.bodyErrors++;tossNet.lastError=String(e)});
    return;
  }
  if(method==='Network.webSocketFrameReceived'){
    const payload=params?.response?.payloadData||'';if(payload){tossNet.stats.websocketFrames++;NVBTossNetParser.ingestText(tossNet.store,payload,'','websocket');}
  }
});
chrome.debugger.onDetach.addListener((source,reason)=>{if(source.tabId===tossNet.tabId){tossNet.attached=false;tossNet.tabId=null;tossNet.lastError='debugger detached: '+String(reason||'')}});
function normalizeRouteUrl(u){
  try{
    const x=new URL(u||"");
    x.hash="";
    x.pathname=(x.pathname.replace(/\/+$/g,"")||"/");
    return x.origin+x.pathname+(x.search||"");
  }catch(e){return String(u||"").replace(/#.*$/,"").replace(/\/+$/,"");}
}
function safeMarketplaceUrl(siteName,u){
  let value=String(u||"").trim();
  if(siteName==="쿠팡")value=value.replace(/^http:\/\//i,"https://");
  return value;
}

const bridgeSleep=ms=>new Promise(r=>setTimeout(r,ms));
async function post(path,obj){
  // Local bridge failures are transport failures, not marketplace failures.
  // Retry only 127.0.0.1 with bounded exponential backoff; no extra web visit.
  const attempts=path==='/api/heartbeat'?2:5;let last=null;
  for(let n=0;n<attempts;n++){
    try{
      const ctl=new AbortController(),to=setTimeout(()=>ctl.abort(),(path==='/api/detail_capture'||path==='/api/detail_capture_viewport')?20000:8000);
      const r=await fetch(BRIDGE+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj||{}),signal:ctl.signal});
      clearTimeout(to);if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();
    }catch(e){last=e;if(n+1<attempts)await bridgeSleep(Math.min(4000,250*(2**n)));}
  }
  throw last||new Error('local bridge post failed');
}
async function get(path){
  let last=null;
  for(let n=0;n<5;n++){
    try{
      const ctl=new AbortController(),to=setTimeout(()=>ctl.abort(),8000);
      const r=await fetch(BRIDGE+path,{signal:ctl.signal});clearTimeout(to);
      if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();
    }catch(e){last=e;if(n<4)await bridgeSleep(Math.min(4000,250*(2**n)));}
  }
  throw last||new Error('local bridge get failed');
}
async function heartbeat(source="background"){
  try{
    await post("/api/heartbeat",{ts:Date.now(),extension_version:EXT_VERSION,source,run_id:runId||'',task_id:currentTask?.id||'',stage:stage||''});
    return true;
  }catch(e){ return false; }
}

async function taskProgressBeat(source){if(currentTask)armWatchdog();return await heartbeat('task:'+String(source||stage||'active'));}

async function attachPageDialogGuard(){
  if(!workTabId)return{ok:false,error:'work tab missing'};
  if(pageDialogGuard.attached&&pageDialogGuard.tabId===workTabId)return{ok:true,attached:true};
  try{
    if(pageDialogGuard.attached)await detachPageDialogGuard();
    await new Promise((resolve,reject)=>chrome.debugger.attach({tabId:workTabId},'1.3',()=>{const e=chrome.runtime.lastError;e?reject(new Error(e.message)):resolve();}));
    pageDialogGuard={attached:true,tabId:workTabId,events:[],lastError:''};
    resetCoupangImageNet();
    await new Promise((resolve,reject)=>chrome.debugger.sendCommand({tabId:workTabId},'Page.enable',{},()=>{const e=chrome.runtime.lastError;e?reject(new Error(e.message)):resolve();}));
    try{await new Promise((resolve,reject)=>chrome.debugger.sendCommand({tabId:workTabId},'Network.enable',{maxTotalBufferSize:120000000,maxResourceBufferSize:16000000},()=>{const e=chrome.runtime.lastError;e?reject(new Error(e.message)):resolve();}));}catch(_e){}
    chrome.debugger.sendCommand({tabId:workTabId},'Page.handleJavaScriptDialog',{accept:true},()=>void chrome.runtime.lastError);
    return{ok:true,attached:true};
  }catch(e){pageDialogGuard={attached:false,tabId:null,events:[],lastError:String(e)};return{ok:false,error:String(e)};}
}
async function detachPageDialogGuard(){
  if(!pageDialogGuard.attached||!pageDialogGuard.tabId)return;
  const id=pageDialogGuard.tabId;pageDialogGuard.attached=false;pageDialogGuard.tabId=null;coupangImageNet.active=false;
  try{await new Promise(r=>chrome.debugger.detach({tabId:id},()=>r()));}catch(_e){}
}
chrome.debugger.onEvent.addListener((source,method,params)=>{
  if(!pageDialogGuard.attached||source.tabId!==pageDialogGuard.tabId)return;
  if(method==='Page.javascriptDialogOpening'){
    pageDialogGuard.events.push({message:String(params?.message||''),type:String(params?.type||''),ts:Date.now(),handled:'debugger_auto_accept'});
    pageDialogGuard.events=pageDialogGuard.events.slice(-10);
    chrome.debugger.sendCommand({tabId:pageDialogGuard.tabId},'Page.handleJavaScriptDialog',{accept:true},()=>void chrome.runtime.lastError);
    return;
  }
  if(!coupangImageNet.active||currentTask?.site!=='쿠팡'||currentTask?.mode!=='detail')return;
  if(method==='Network.responseReceived'){
    const r=params?.response||{},mime=String(r.mimeType||'').toLowerCase(),type=String(params?.type||''),url=String(r.url||'');
    if((type==='Image'||mime.startsWith('image/'))&&url&&!imageNetBadUrl(url)&&Number(r.status||0)>=200&&Number(r.status||0)<400){
      coupangImageNet.stats.responses++;coupangImageNet.lastEventAt=Date.now();
      coupangImageNet.entries.set(params.requestId,{requestId:params.requestId,url,mime:mime||'image/jpeg',type,status:Number(r.status||0),ts:Date.now(),encodedDataLength:0});
    }
    return;
  }
  if(method==='Network.loadingFinished'){
    const e=coupangImageNet.entries.get(params.requestId);if(!e)return;
    e.encodedDataLength=Number(params?.encodedDataLength||0);e.finished=true;coupangImageNet.stats.finished++;coupangImageNet.lastEventAt=Date.now();
  }
});
chrome.debugger.onDetach.addListener(source=>{if(source.tabId===pageDialogGuard.tabId){pageDialogGuard.attached=false;pageDialogGuard.tabId=null;coupangImageNet.active=false;}});

chrome.runtime.onInstalled.addListener(()=>{
  try{chrome.alarms.create("bridgeHeartbeat",{periodInMinutes:0.5});}catch(e){}
  heartbeat("installed");
});
chrome.runtime.onStartup.addListener(()=>{
  try{chrome.alarms.create("bridgeHeartbeat",{periodInMinutes:0.5});}catch(e){}
  heartbeat("startup");
});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==="bridgeHeartbeat") heartbeat("alarm");});
heartbeat("service_worker_start");


async function itemscoutTrustedDrag(tabId,from,to,steps=18){
  if(!tabId||!from||!to)return{ok:false,error:'trusted_drag_missing_args'};
  const target={tabId:Number(tabId)};let attachedHere=false;
  const wait=ms=>new Promise(r=>setTimeout(r,ms));
  const send=async(method,params)=>await chrome.debugger.sendCommand(target,method,params||{});
  try{
    let ready=false;
    // If this extension already owns a debugger session on the tab, reuse it.
    try{await send('Runtime.evaluate',{expression:'1',returnByValue:true});ready=true;}catch(_e){}
    if(!ready){
      try{await chrome.debugger.attach(target,'1.3');attachedHere=true;ready=true;}
      catch(e){
        // A same-extension session can race with attach. One last command tells us
        // whether the session is actually usable; DevTools/other debuggers remain a
        // clean failure so the content script can fall back without corrupting UI.
        try{await send('Runtime.evaluate',{expression:'1',returnByValue:true});ready=true;}
        catch(_e){return{ok:false,error:'trusted_drag_attach_failed: '+String(e)}}
      }
    }
    const fx=Number(from.x),fy=Number(from.y),tx=Number(to.x),ty=Number(to.y);
    if(![fx,fy,tx,ty].every(Number.isFinite))return{ok:false,error:'trusted_drag_invalid_coordinates'};
    const count=Math.max(8,Math.min(36,Number(steps||18)));
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:fx,y:fy,button:'none',buttons:0});
    await wait(35);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x:fx,y:fy,button:'left',buttons:1,clickCount:1});
    await wait(30);
    for(let i=1;i<=count;i++){
      const q=i/count,x=fx+(tx-fx)*q,y=fy+(ty-fy)*q;
      await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'left',buttons:1});
      await wait(18);
    }
    await wait(35);
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:tx,y:ty,button:'left',buttons:0,clickCount:1});
    await wait(80);
    return{ok:true,method:'cdp_trusted_mouse_drag',from:{x:fx,y:fy},to:{x:tx,y:ty},steps:count};
  }catch(e){return{ok:false,error:'trusted_drag_command_failed: '+String(e)};}
  finally{
    // Detach only the session we attached ourselves. Never tear down an existing
    // collector/debugger session owned elsewhere in this extension.
    if(attachedHere){try{await chrome.debugger.detach(target);}catch(_e){}}
  }
}

chrome.runtime.onMessage.addListener((msg,sender,sendResponse)=>{
  if(msg?.type==="itemscoutTrustedDrag"){
    itemscoutTrustedDrag(sender.tab?.id,msg.from,msg.to,msg.steps)
      .then(x=>sendResponse(x||{ok:false,error:"trusted_drag_empty_result"}))
      .catch(e=>sendResponse({ok:false,error:String(e)}));
    return true;
  }
  if(msg?.type==="collectorPageAlive"){
    heartbeat("collector_page");
    sendResponse({ok:true,version:EXT_VERSION});
    return true;
  }
  if(msg?.type==="collectorAutostart"){
    startCollector(msg.runId||null,sender.tab?.id)
      .then(x=>sendResponse({ok:true,run_id:runId,detail:x||""}))
      .catch(e=>sendResponse({ok:false,error:String(e)}));
    return true;
  }
  if(msg?.type==="manualStart"){
    startCollector(msg.runId||null,null)
      .then(x=>sendResponse({ok:true,run_id:runId,detail:x||""}))
      .catch(e=>sendResponse({ok:false,error:String(e)}));
    return true;
  }
  if(msg?.type==="manualStop"){
    running=false;currentTask=null;stage=null;
    tossNetDetach();
    detachPageDialogGuard();
    clearTimeout(timer);clearTimeout(watchdog);
    sendResponse({ok:true});
    return true;
  }
  if(msg?.type==="getStatus"){
    sendResponse({running,runId,stage,currentTask:currentTask?.id||null,version:EXT_VERSION});
    return true;
  }
});

async function resolveRunId(explicit){
  if(explicit) return explicit;
  try{
    const a=await get("/api/active_run");
    if(a?.active && a.run_id) return a.run_id;
  }catch(e){}
  return null;
}

async function startCollector(rid,tabId){
  await heartbeat("start_collector");
  const resolvedRunId=await resolveRunId(rid);
  if(!resolvedRunId) throw new Error("활성 Run이 없습니다. 프로그램에서 상품검색/가격검증 버튼을 먼저 누르세요.");
  if(running&&runId===resolvedRunId&&currentTask)return "collector already running";
  runGeneration+=1;
  const generation=runGeneration;
  clearTimeout(timer);clearTimeout(watchdog);
  runId=resolvedRunId;
  running=true;
  // v7.35: the /collector tab is only a launcher. Never turn every launcher into
  // another marketplace work tab. Keep ONE reusable work tab across Naver ->
  // Coupang -> Toss and across full-name/core-keyword batches.
  const launcherTabId=tabId||null;
  let validWork=false;
  if(workTabId){try{await chrome.tabs.get(workTabId);validWork=true;}catch(e){workTabId=null;}}
  if(!validWork){
    const tab=await chrome.tabs.create({url:"about:blank",active:true});
    workTabId=tab.id;
  }
  await nextTask(generation);
  if(launcherTabId && launcherTabId!==workTabId){
    setTimeout(()=>chrome.tabs.remove(launcherTabId).catch(()=>{}),700);
  }
  return "collector started / single reusable work tab";
}

function armWatchdog(){
  clearTimeout(watchdog);
  const requested=Number(currentTask?.task_timeout_sec||0),configured=requested>0?Math.max(60,requested)*1000:0;
  const fallback=currentTask?.mode==="detail"?300000:(currentTask?.mode==="fixed_category_collect"&&currentTask?.site==="토스쇼핑")?180000:90000;
  const timeout=configured||fallback;
  watchdog=setTimeout(async()=>{
    if(!running||!currentTask)return;
    try{
      await finish(Object.assign({},fixedRouteProgress,{status:"error",error:`task watchdog timeout at stage=${stage}`}));
    }catch(e){}
  },timeout);
}

function fixedRoutePayload(){
  return {
    type:"performSearch",
    site:currentTask.site,
    query:currentTask.query,
    action:"open_fixed_category",
    category_label:currentTask.category_label||"",
    blog_category:currentTask.blog_category||currentTask.query||"",
    site_category_label:currentTask.site_category_label||"",
    parent_category_label:currentTask.parent_category_label||"",
    category_aliases:currentTask.category_aliases||[],
    fallback_url:safeMarketplaceUrl(currentTask.site,currentTask.fallback_url||""),
    parent_fallback_url:safeMarketplaceUrl(currentTask.site,currentTask.parent_fallback_url||""),
    click_path:currentTask.click_path||[],
    ranking_anchor:currentTask.ranking_anchor||""
  };
}


async function mainWorldTossProductLookupRescue(){
  if(!workTabId)return null;
  try{
    const rows=await chrome.scripting.executeScript({
      target:{tabId:workTabId},world:"MAIN",
      func:()=>{
        const norm=x=>(x||"").replace(/\s+/g," ").trim();
        const visible=e=>{try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>2&&r.height>2&&s.display!=="none"&&s.visibility!=="hidden";}catch(_e){return false;}};
        const nodes=[...document.querySelectorAll('a,button,[role="button"],[role="menuitem"],li,span,div')].filter(visible);
        const candidates=[];
        for(const e of nodes){
          const t=norm(e.innerText||e.textContent||"");if(t!=="상품 조회"&&t!=="상품조회")continue;
          const r=e.getBoundingClientRect();if(r.left>420)continue;
          let target=e.closest?.('a,button,[role="button"],[role="menuitem"]')||e;
          let href="";try{const a=target.closest?.('a[href]')||target.querySelector?.('a[href]');href=a?.href||"";}catch(_e){}
          let score=100-(Math.max(0,r.left)/10);if(target.tagName==='A'||target.tagName==='BUTTON')score+=30;if(href)score+=25;
          candidates.push({e,target,href,score,rect:{x:r.x,y:r.y,w:r.width,h:r.height}});
        }
        candidates.sort((a,b)=>b.score-a.score);const c=candidates[0];
        if(!c)return{ok:false,error:"main-world 상품 조회 메뉴 없음",url:location.href};
        try{c.target.scrollIntoView({block:'center',behavior:'instant'});}catch(_e){}
        try{c.target.click();}catch(_e){try{c.e.click();}catch(__e){}}
        return{ok:true,href:c.href||"",text:norm(c.target.innerText||c.target.textContent||""),rect:c.rect,url:location.href};
      }
    });
    return rows?.[0]?.result||null;
  }catch(e){return{ok:false,error:String(e)};}
}


async function mainWorldTossCategoryClick(siteCategory,aliases=[]){
  if(!workTabId)return{ok:false,error:'work tab missing'};
  try{
    const rows=await chrome.scripting.executeScript({
      target:{tabId:workTabId},world:'MAIN',
      args:[siteCategory,aliases||[]],
      func:async(siteCategory,aliases)=>{
        const norm=x=>(x||'').replace(/\s+/g,'').replace(/[·ㆍ]/g,'/').toLowerCase();
        const wanted=[siteCategory,...(aliases||[])].filter(Boolean).map(norm);
        const visible=e=>{try{const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>3&&r.height>3&&st.display!=='none'&&st.visibility!=='hidden'&&Number(st.opacity||1)>0.05;}catch(_e){return false;}};
        const inMain=e=>{if(!e||!visible(e))return false;try{if(e.closest('aside,nav,[role="navigation"]'))return false;}catch(_e){}const r=e.getBoundingClientRect();const cut=Math.min(270,Math.max(170,innerWidth*0.17));return r.right>cut+30&&(r.left>cut-25||r.width>innerWidth*0.45);};
        const text=e=>(e?.innerText||e?.textContent||'').replace(/\s+/g,' ').trim();
        const state=e=>{if(!e)return{known:false,checked:false};const inp=e.matches?.('input[type="checkbox"]')?e:e.querySelector?.('input[type="checkbox"]');if(inp)return{known:true,checked:!!inp.checked,source:'input'};for(const a of ['aria-checked','aria-selected','aria-pressed']){const v=(e.getAttribute?.(a)||'').toLowerCase();if(v==='true')return{known:true,checked:true,source:a};if(v==='false')return{known:true,checked:false,source:a};}for(const a of ['data-state','data-checked','data-selected']){const v=(e.getAttribute?.(a)||'').toLowerCase();if(['checked','true','on','selected','active'].includes(v))return{known:true,checked:true,source:a};if(['unchecked','false','off','inactive'].includes(v))return{known:true,checked:false,source:a};}return{known:false,checked:false,source:'unknown'};};
        const fingerprint=e=>{if(!e)return'';const parts=[];let n=e;for(let i=0;n&&i<4;i++,n=n.parentElement){const st=getComputedStyle(n),r=n.getBoundingClientRect();parts.push(`tag=${n.tagName};class=${n.getAttribute?.('class')||''};role=${n.getAttribute?.('role')||''};ac=${n.getAttribute?.('aria-checked')||''};as=${n.getAttribute?.('aria-selected')||''};ap=${n.getAttribute?.('aria-pressed')||''};ds=${n.getAttribute?.('data-state')||''};bg=${st.backgroundColor};bc=${st.borderColor};c=${st.color};fw=${st.fontWeight};o=${st.opacity};w=${Math.round(r.width)};h=${Math.round(r.height)}`);const svg=n.querySelector?.('svg');if(svg)parts.push('svg='+String(svg.outerHTML||'').slice(0,400));}return parts.join('||');};
        const labels=[...document.querySelectorAll('label,span,p,div,button,[role="option"],[role="checkbox"],[role="button"]')].filter(inMain);
        let label=null,score=-1;
        for(const e of labels){const raw=text(e);if(!raw||raw.length>55)continue;const n=norm(raw);if(!wanted.includes(n))continue;const r=e.getBoundingClientRect();let sc=300;if(e.children.length===0)sc+=80;if(e.tagName==='LABEL')sc+=70;if(e.tagName==='BUTTON')sc+=45;if((e.getAttribute?.('role')||'').toLowerCase()==='checkbox')sc+=65;if(r.height>=14&&r.height<=80)sc+=20;if(r.width<=420)sc+=15;if(sc>score){score=sc;label=e;}}
        if(!label)return{ok:false,error:`본문에서 '${siteCategory}' 정확한 카테고리 라벨을 찾지 못했습니다.`,url:location.href};
        const candidates=[];const push=e=>{if(e&&!candidates.includes(e))candidates.push(e);};
        if(label.matches?.('input[type="checkbox"],[role="checkbox"]'))push(label);
        const lab=label.closest?.('label');if(lab){push(lab.querySelector?.('input[type="checkbox"]'));push(lab);}
        let n=label;for(let i=0;n&&i<5;i++,n=n.parentElement){push(n.querySelector?.(':scope > input[type="checkbox"]'));push(n.querySelector?.('input[type="checkbox"]'));push(n.querySelector?.('[role="checkbox"]'));const prev=n.previousElementSibling,next=n.nextElementSibling;for(const x of [prev,next]){if(!x)continue;if(x.matches?.('input[type="checkbox"],[role="checkbox"]'))push(x);push(x.querySelector?.('input[type="checkbox"],[role="checkbox"]'));}const role=(n.getAttribute?.('role')||'').toLowerCase(),cls=String(n.className||'').toLowerCase(),r=n.getBoundingClientRect();if((n.tagName==='BUTTON'||role==='checkbox'||role==='option'||role==='button'||/(checkbox|check-box|filter|chip|pill|toggle)/.test(cls))&&r.height<=120)push(n);}
        try{
          const lr=label.getBoundingClientRect(),y=Math.max(1,Math.min(innerHeight-2,lr.top+lr.height/2));
          for(const dx of [-42,-32,-22,-12,12,22]){const x=Math.max(1,Math.min(innerWidth-2,lr.left+(dx<0?dx:lr.width+dx)));const hit=document.elementFromPoint(x,y);if(!hit)continue;push(hit.matches?.('input[type="checkbox"],[role="checkbox"]')?hit:null);push(hit.closest?.('label,button,[role="checkbox"],[role="button"]'));try{const hr=hit.getBoundingClientRect(),hc=(getComputedStyle(hit).cursor||'').toLowerCase();if(hr.width>=8&&hr.width<=72&&hr.height>=8&&hr.height<=72&&(hc==='pointer'||hit.querySelector?.('svg')))push(hit);}catch(_e){}}
        }catch(_e){}
        // Exact visible text is the final fallback for React delegated click handlers.
        push(label);
        const target=candidates.find(e=>e?.matches?.('input[type="checkbox"]'))||candidates.find(e=>(e?.getAttribute?.('role')||'').toLowerCase()==='checkbox')||candidates.find(e=>e?.tagName==='LABEL')||candidates.find(e=>e?.tagName==='BUTTON')||candidates.find(e=>{try{const r=e.getBoundingClientRect();return r.width<=72&&r.height<=72&&(getComputedStyle(e).cursor||'').toLowerCase()==='pointer';}catch(_e){return false;}})||label;
        const beforeState=state(target),beforeFp=fingerprint(target),beforeLabelFp=fingerprint(label),r=label.getBoundingClientRect();
        try{target.scrollIntoView?.({block:'center',behavior:'instant'});}catch(_e){}
        await new Promise(r=>setTimeout(r,120));
        try{
          // Exactly one activation. HTMLElement.click() bubbles to React delegated
          // handlers and also preserves native label/checkbox activation behavior.
          target.click();
        }catch(e){return{ok:false,error:'카테고리 클릭 예외: '+String(e),site:siteCategory};}
        await new Promise(r=>setTimeout(r,700));
        // Re-find the exact label/control after React re-render.
        const labels2=[...document.querySelectorAll('label,span,p,div,button,[role="option"],[role="checkbox"],[role="button"]')].filter(inMain);
        let label2=labels2.find(e=>wanted.includes(norm(text(e)))&&e.children.length===0)||labels2.find(e=>wanted.includes(norm(text(e))))||label;
        const label2Lab=label2.closest?.('label');
        let target2=null;
        if(target.tagName==='INPUT'&&String(target.getAttribute?.('type')||'').toLowerCase()==='checkbox')target2=label2Lab?.querySelector?.('input[type="checkbox"]')||label2.parentElement?.querySelector?.('input[type="checkbox"]');
        else if((target.getAttribute?.('role')||'').toLowerCase()==='checkbox')target2=label2.closest?.('[role="checkbox"]')||label2.parentElement?.querySelector?.('[role="checkbox"]');
        else if(target.tagName==='LABEL')target2=label2Lab;
        else if(target.tagName==='BUTTON')target2=label2.closest?.('button');
        target2=target2||label2;
        const semantic=[target2,label2].map(state);const afterChecked=semantic.some(x=>x.known&&x.checked);const afterFp=fingerprint(target2),afterLabelFp=fingerprint(label2);
        const receipt={site:siteCategory,ts:Date.now(),before_fp:beforeFp,before_label_fp:beforeLabelFp,after_fp:afterFp,after_label_fp:afterLabelFp,before_known:beforeState.known,before_checked:beforeState.checked,after_checked:afterChecked,label_text:text(label2),target_tag:target.tagName,target_role:target.getAttribute?.('role')||'',target_type:target.getAttribute?.('type')||'',rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},url:location.href};
        try{sessionStorage.setItem('nvb_toss_main_category_click_receipt',JSON.stringify(receipt));}catch(_e){}
        return{ok:true,receipt,visual_changed:(afterFp!==beforeFp)||(afterLabelFp!==beforeLabelFp),after_checked:afterChecked};
      }
    });
    return rows?.[0]?.result||null;
  }catch(e){return{ok:false,error:String(e)};}
}

async function finishWithDiagnostic(result){
  let shot=null;
  try{
    const tab=await chrome.tabs.get(workTabId);
    shot=await chrome.tabs.captureVisibleTab(tab.windowId,{format:"png"});
  }catch(e){ if(result&&typeof result==="object")result.capture_error=String(e); }
  await finish(result,shot);
}
async function attemptFixedRoute(){
  if(!running||stage!=="search"||!currentTask||currentTask.mode!=="fixed_category_collect")return;
  fixedRouteAttempts++;
  if(fixedRouteAttempts>FIXED_ROUTE_MAX_ATTEMPTS){
    await finishWithDiagnostic(Object.assign({},fixedRouteProgress,{
      status:"error",
      error:`지정 카테고리 화면이 ${FIXED_ROUTE_MAX_ATTEMPTS}회 안에 준비되지 않았습니다: ${currentTask.site} / ${currentTask.blog_category||currentTask.query}`+(fixedRouteProgress?.detail?` · 마지막 단계: ${fixedRouteProgress.detail}`:""),
      route_attempts:fixedRouteAttempts-1,
      same_url_stalls:fixedSameUrlStalls,
      last_url:fixedLastUrl
    }));
    return;
  }
  let resp=null;
  try{
    // v7.30: ALWAYS install the Toss MAIN-world tap before content.js is allowed
    // to inspect/click the category UI. This closes every timing path: whether
    // the category ON is performed by content.js or by the MAIN-world fallback,
    // the product request/render can no longer happen before the collector exists.
    if(currentTask?.site==="토스쇼핑"){
      const preArm=await installTossDataFeedTap(false);
      const netArm=await tossNetAttach(false);
      fixedRouteProgress=Object.assign({},fixedRouteProgress,{toss_network_prearm:netArm});
      if(!preArm?.ok){
        clearTimeout(timer);timer=setTimeout(()=>attemptFixedRoute(),1200);return;
      }
    }
    resp=await chrome.tabs.sendMessage(workTabId,fixedRoutePayload());
    if(resp&&typeof resp==="object"){
      fixedRouteProgress=Object.assign({},fixedRouteProgress,{
        toss_product_lookup_confirmed:resp.toss_product_lookup_confirmed??fixedRouteProgress.toss_product_lookup_confirmed,
        toss_single_checkbox_confirmed:resp.toss_single_checkbox_confirmed??fixedRouteProgress.toss_single_checkbox_confirmed,
        clicked_label:resp.clicked_label||fixedRouteProgress.clicked_label||"",
        detail:resp.detail||fixedRouteProgress.detail||"",
        debug:resp.debug||fixedRouteProgress.debug||{}
      });
      const key=normalizeRouteUrl((await chrome.tabs.get(workTabId).catch(()=>({url:""})))?.url||"")+"|"+(resp.status||"")+"|"+(resp.detail||resp.error||"");
      if(key===fixedProgressKey)fixedProgressStalls++;else{fixedProgressKey=key;fixedProgressStalls=0;}
      if(currentTask?.site==="토스쇼핑"&&fixedProgressStalls>=TOSS_SAME_PROGRESS_LIMIT){
        await finishWithDiagnostic(Object.assign({},fixedRouteProgress,{status:"error",
          error:`토스 화면이 같은 단계에서 ${TOSS_SAME_PROGRESS_LIMIT}회 멈췄습니다: ${resp.detail||resp.error||"상태 변화 없음"}`,
          route_attempts:fixedRouteAttempts,progress_stalls:fixedProgressStalls,last_url:fixedLastUrl||""}));
        return;
      }
    }
  }catch(e){
    // document_idle/content script can lag behind tab complete, especially on
    // Coupang category pages.  v7.16 returned here and could leave the task in
    // a bad state.  Retry without reloading the page.
    console.debug("fixed route message interrupted:",String(e));
    clearTimeout(timer);
    timer=setTimeout(()=>attemptFixedRoute(),1500);
    return;
  }
  if(!running||!currentTask)return;
  if(resp?.status==="login_required"||resp?.status==="blocked"||resp?.status==="error"){
    await finishWithDiagnostic(Object.assign({},resp,{route_attempts:fixedRouteAttempts,same_url_stalls:fixedSameUrlStalls}));return;
  }
  if(resp?.status==="toss_category_click_required"&&currentTask?.site==="토스쇼핑"){
    if(tossCategoryMainClicks>=1){
      await finishWithDiagnostic(Object.assign({},fixedRouteProgress,{status:"error",error:`토스 ${currentTask.site_category_label||currentTask.blog_category||currentTask.query} 카테고리 실제 체크가 확인되지 않았습니다. 같은 카테고리를 반복 클릭하지 않고 중단합니다.`,route_attempts:fixedRouteAttempts,main_world_category_clicks:tossCategoryMainClicks}));
      return;
    }
    tossCategoryMainClicks++;
    // v7.30: arm/reset the MAIN-world rendered-text/network feed BEFORE the category
    // ON click so the filtered product request can never race ahead of capture.
    const feedArm=await installTossDataFeedTap(true);
    const netArm=await tossNetAttach(true);
    fixedRouteProgress=Object.assign({},fixedRouteProgress,{toss_network_arm:netArm});
    if(!feedArm?.ok){await finishWithDiagnostic(Object.assign({},fixedRouteProgress,{status:"error",error:"토스 상품 데이터 감시 시작 실패: "+(feedArm?.error||"unknown")}));return;}
    const clickRes=await mainWorldTossCategoryClick(resp.site_category_label||currentTask.site_category_label||currentTask.blog_category||currentTask.query,resp.category_aliases||currentTask.category_aliases||[]);
    fixedRouteProgress=Object.assign({},fixedRouteProgress,{main_world_category_click:clickRes,main_world_category_clicks:tossCategoryMainClicks,detail:clickRes?.ok?`토스 ${currentTask.site_category_label||currentTask.blog_category||currentTask.query} 정확한 카테고리 1회 클릭 완료 -> 상품 직접 수집 시작`:(clickRes?.error||'토스 카테고리 클릭 실패')});
    if(!clickRes?.ok){await finishWithDiagnostic(Object.assign({},fixedRouteProgress,{status:"error",error:clickRes?.error||'토스 카테고리 MAIN-world 클릭 실패'}));return;}
    // v7.34: the exact target control was already activated ONCE in MAIN world.
    // Do not ask the isolated content script to prove the custom React checkbox
    // a second time. That extra proof was a false-negative gate on the real
    // Sharelink page: the category visibly changed but collection was blocked at
    // 0/30 as "single checkbox unconfirmed". Start direct product reading now.
    fixedRouteProgress=Object.assign({},fixedRouteProgress,{toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,clicked_label:currentTask.site_category_label||currentTask.blog_category||currentTask.query||'',main_world_single_click_accepted:true});
    stage="collect";clearTimeout(timer);timer=setTimeout(()=>collectNow(),1500);return;
  }
  if(resp?.status==="ok"&&resp?.category_confirmed){
    stage="collect";
    clearTimeout(timer);
    timer=setTimeout(()=>collectNow(),1100);
    return;
  }
  if(resp?.status==="navigate"&&resp?.url){
    stage="search";
    clearTimeout(timer);
    let tab=null;
    try{tab=await chrome.tabs.get(workTabId);}catch(e){}
    const current=normalizeRouteUrl(tab?.url||"");
    const target=normalizeRouteUrl(resp.url);
    fixedLastUrl=current||target;
    if(current && target && current===target){
      // Critical v7.17 guard: NEVER update a tab to the URL it is already on.
      // Allow the existing category page to finish rendering instead.
      fixedSameUrlStalls++;
      timer=setTimeout(()=>attemptFixedRoute(),1800);
      return;
    }
    fixedSameUrlStalls=0;
    fixedLastUrl=target;
    await chrome.tabs.update(workTabId,{url:resp.url,active:true});
    return;
  }
  // On the real Toss /home screen the submenu is visibly present but some React
  // builds ignore isolated-world synthetic clicks. After the normal content-script
  // attempt, retry the exact left-menu control once from the page MAIN world.
  if(currentTask?.site==="토스쇼핑" && (resp?.detail||resp?.error||"").includes("상품 조회") && tossMainWorldRescues<3){
    let tab=null;try{tab=await chrome.tabs.get(workTabId);}catch(e){}
    const path=(()=>{try{return new URL(tab?.url||"").pathname;}catch(e){return"";}})();
    if(path==="/home"||path==="/"||!path){
      tossMainWorldRescues++;
      const rescue=await mainWorldTossProductLookupRescue();
      fixedRouteProgress=Object.assign({},fixedRouteProgress,{main_world_rescue:rescue,main_world_rescue_count:tossMainWorldRescues});
      clearTimeout(timer);
      timer=setTimeout(()=>attemptFixedRoute(),1400);
      return;
    }
  }
  // SPA/menu transitions may not emit a full page-load event. Retry on the current
  // DOM, but the per-task no-progress guard prevents 14/18 from hanging forever.
  stage="search";
  clearTimeout(timer);
  timer=setTimeout(()=>attemptFixedRoute(),1600);
}
async function nextTask(expectedGeneration=runGeneration){
  if(!running||expectedGeneration!==runGeneration)return;
  clearTimeout(watchdog);
  try{
    const n=await get("/api/next?run_id="+encodeURIComponent(runId));
    if(!running||expectedGeneration!==runGeneration)return;
    if(n.paused||n.done){
      running=false;currentTask=null;stage=null;
      await detachPageDialogGuard();
      await closeCollectorLauncherTabs();
      return;
    }
    currentTask=n.task;
    if(!currentTask){running=false;return;}
    fixedRouteAttempts=0;
    fixedSameUrlStalls=0;
    fixedLastUrl="";
    fixedRouteProgress={};
    fixedProgressKey="";
    fixedProgressStalls=0;
    tossMainWorldRescues=0;
    tossCategoryMainClicks=0;
    stage="navigate";
    armWatchdog();
    await launchTask(currentTask);
  }catch(e){
    console.error("nextTask",e);
    running=false;
  }
}

async function launchTask(t){
  if(!workTabId){
    const tab=await chrome.tabs.create({url:"about:blank",active:true});
    workTabId=tab.id;
  }

  // v8.08.42 Google Images + Web are source-page resolvers. Google preview
  // thumbnails are never saved; Images search is used to discover imgrefurl +
  // original imgurl, followed by destination-page identity validation.
  if(t.mode==="google_product_source_search"){
    stage="collect";
    const q=String(t.query||"").trim(),surface=String(t.search_surface||"web");
    const base=surface==="images"
      ? "https://www.google.com/search?hl=ko&safe=active&tbm=isch&udm=2&q="
      : "https://www.google.com/search?hl=ko&num=20&q=";
    await chrome.tabs.update(workTabId,{url:base+encodeURIComponent(q),active:true});
    return;
  }

  // v8.08.36 arbitrary Google-discovered product pages are scanned through CDP,
  // so the extension does not require <all_urls> read/change permission.
  if(t.mode==="external_detail"&&t.url){
    stage="collect";
    const ar=await attachPageDialogGuard();if(!ar?.ok)pageDialogGuard.lastError=ar?.error||'external debugger attach failed';
    await chrome.tabs.update(workTabId,{url:String(t.url),active:true});
    return;
  }

  // Supplemental age/category trend pages are self-contained filter UIs.
  // Navigate directly, then content.js applies category/age filters and reads TOP30.
  if(t.mode==="trend_keyword_collect"){
    stage="collect";
    const u=t.entry_url || (t.site==="아이템스카우트" ? "https://itemscout.io/category/1" : "https://datalab.naver.com/shoppingInsight/sCategory.naver");
    // v8.00: both age buckets reuse one direct category page; only category changes navigate
    // page. This limits ItemScout to six category navigations, while the second age
    // bucket stays on the already-loaded category page.
    try{
      const tab=await chrome.tabs.get(workTabId),cur=String(tab?.url||"");
      const cu=new URL(cur),tu=new URL(u);
      const sameHost=cu.hostname===tu.hostname||cu.hostname.endsWith("."+tu.hostname)||tu.hostname.endsWith("."+cu.hostname);
      const sameSurface=t.site==="아이템스카우트"
        ? (/^\/category(?:\/|$)/.test(cu.pathname) && cu.pathname.replace(/\/+$/,'')===tu.pathname.replace(/\/+$/,''))
        : /shoppingInsight/.test(cu.pathname);
      if(sameHost&&sameSurface){
        clearTimeout(timer);
        timer=setTimeout(()=>collectNow(),900);
        return;
      }
    }catch(_e){}
    await chrome.tabs.update(workTabId,{url:u,active:true});
    return;
  }

  // v8.08.33: NEVER jump directly to /np/search for trend keywords.
  // The live Coupang site can reject repeated direct search-result URLs with
  // the "요청하신 페이지의 사용권한이 없습니다" page.  Reuse one Chrome tab,
  // return to the normal homepage, then let content.js use the visible search box.
  if(t.mode==="trend_coupang_pick" && t.site==="쿠팡"){
    stage="search";
    await chrome.tabs.update(workTabId,{url:"https://www.coupang.com/",active:true});
    return;
  }

  // Discovery is click/browse based, never keyword-search based.
  if(t.mode==="category_discovery"){
    stage="collect";
    const u=t.site==="네이버쇼핑" ? "https://shopping.naver.com/home"
      : t.site==="토스쇼핑" ? "https://sharelink.toss.im/home"
      : "https://www.coupang.com/";
    await chrome.tabs.update(workTabId,{url:u,active:true});
    return;
  }

  if(t.mode==="fixed_category_collect"){
    stage="search";
    // v7.23 Toss live fix: the first Toss category succeeds on a fresh Product
    // Lookup session, while later categories can inherit stale React filter,
    // scroll, virtual-list and accordion state.  Do NOT reuse that SPA state.
    // Every Toss category starts from a freshly loaded /home, then content.js
    // executes exactly: 상품 조회 -> one category ON -> collect 30 -> OFF.
    if(t.site==="토스쇼핑"){
      const home=t.entry_url || "https://sharelink.toss.im/home";
      try{
        const tab=await chrome.tabs.get(workTabId);
        const cur=normalizeRouteUrl(tab?.url||"");
        const target=normalizeRouteUrl(home);
        if(cur && target && cur===target){
          await chrome.tabs.reload(workTabId,{bypassCache:false});
        }else{
          await chrome.tabs.update(workTabId,{url:home,active:true});
        }
      }catch(e){
        await chrome.tabs.update(workTabId,{url:home,active:true});
      }
      return;
    }
    const u=safeMarketplaceUrl(t.site,t.entry_url || (t.site==="네이버쇼핑" ? "https://snxbest.naver.com/product/best/click" : "https://www.coupang.com/"));
    await chrome.tabs.update(workTabId,{url:u,active:true});
    return;
  }

  if(t.mode==="category_collect"){
    stage="collect";
    if(t.category_url){
      await chrome.tabs.update(workTabId,{url:safeMarketplaceUrl(t.site,t.category_url),active:true});
      return;
    }
    stage="search";
    const u=t.site==="토스쇼핑" ? "https://sharelink.toss.im/home"
      : t.site==="네이버쇼핑" ? "https://shopping.naver.com/home"
      : "https://www.coupang.com/";
    await chrome.tabs.update(workTabId,{url:u,active:true});
    return;
  }

  if(t.mode==="detail" && t.url){
    stage="collect";
    // v7.45: Python sends only a previously verified direct product URL.
    // Attach before navigation to collect dialogs and rendered image evidence.
    if(t.capture_rendered_crops!==false){const ar=await attachPageDialogGuard();if(!ar?.ok)pageDialogGuard.lastError=ar?.error||'debugger attach failed';}
    await chrome.tabs.update(workTabId,{url:safeMarketplaceUrl(t.site,t.url),active:true});
    return;
  }

  // Legacy price lookup kept for explicit price verification only.
  if(t.site==="네이버쇼핑"){
    stage="collect";
    const u="https://search.shopping.naver.com/search/all?query="+encodeURIComponent(t.query);
    await chrome.tabs.update(workTabId,{url:u,active:true});
  }else if(t.site==="쿠팡"){
    stage="search";
    await chrome.tabs.update(workTabId,{url:"https://www.coupang.com/",active:true});
  }else if(t.site==="토스쇼핑"){
    stage="search";
    await chrome.tabs.update(workTabId,{url:"https://sharelink.toss.im/home",active:true});
  }else{
    await finish({status:"error",error:"unknown site"});
  }
}

async function recoverTrendCoupangBlock(reason="blocked"){
  if(!running||!currentTask||currentTask.mode!=="trend_coupang_pick"||currentTask.site!=="쿠팡")return false;
  currentTask._coupang_block_retry=Number(currentTask._coupang_block_retry||0)+1;
  const maxRetry=Math.max(0,Number(currentTask.block_retry_max??1));
  if(currentTask._coupang_block_retry>maxRetry)return false;
  const cooldown=Math.max(30000,Number(currentTask.block_cooldown_ms||45000));
  stage="recover_coupang_block";
  clearTimeout(timer);
  try{await heartbeat("coupang_block_cooldown");}catch(_e){}
  timer=setTimeout(async()=>{
    if(!running||!currentTask||currentTask.mode!=="trend_coupang_pick")return;
    try{
      stage="search";
      await chrome.tabs.update(workTabId,{url:"https://www.coupang.com/",active:true});
    }catch(e){
      await finish({status:"error",error:"쿠팡 접근제한 후 홈 복귀 실패: "+String(e),block_reason:reason});
    }
  },cooldown);
  return true;
}

chrome.tabs.onUpdated.addListener(async(tabId,change,tab)=>{
  if(!running||tabId!==workTabId||change.status!=="complete"||!currentTask)return;
  await heartbeat("tab_complete");

  if(stage==="search"){
    const fixed=currentTask.mode==="fixed_category_collect";
    clearTimeout(timer);
    if(fixed){
      // v7.28 regression fix: do NOT replace the proven Toss menu/category route
      // with CDP.  The real user's /home screen reliably exposes "상품 조회"
      // to content.js/MAIN-world click recovery.  Route all three sites through
      // the same fixed-route state machine; Toss product reading is handled only
      // after the category ON transaction is confirmed.
      await attemptFixedRoute();
      return;
    }
    stage="collect";
    try{
      const resp=await chrome.tabs.sendMessage(tabId,{
        type:"performSearch",
        site:currentTask.site,
        query:currentTask.query,
        action:currentTask.mode==="category_collect" ? "click_category" : "search",
        category_label:currentTask.category_label||"",
        blog_category:currentTask.blog_category||currentTask.query||"",
        site_category_label:currentTask.site_category_label||"",
        parent_category_label:currentTask.parent_category_label||"",
        category_aliases:currentTask.category_aliases||[],
        fallback_url:currentTask.fallback_url||"",
        parent_fallback_url:currentTask.parent_fallback_url||"",
        click_path:currentTask.click_path||[]
      });
      if(resp?.status==="blocked"&&currentTask?.mode==="trend_coupang_pick"&&currentTask?.site==="쿠팡"){
        if(await recoverTrendCoupangBlock(resp?.error||"blocked_before_search"))return;
      }
      if(resp?.status==="login_required"||resp?.status==="blocked"||resp?.status==="error"){
        await finish(resp);return;
      }
      if(resp?.status==="ranking_only") stage="collect";
    }catch(e){
      console.debug("search navigation closed port:",String(e));
    }
    clearTimeout(timer);
    // Toss Sharelink is an SPA and often renders product cards well after the
    // Enter/search event. Give price lookups enough time for the result list.
    const searchWait=(currentTask?.mode==="price"&&currentTask?.site==="토스쇼핑")?5600
      :(currentTask?.mode==="trend_coupang_pick"&&currentTask?.site==="쿠팡"?4200
      :(currentTask?.mode==="price"?3800:3200));
    timer=setTimeout(()=>collectNow(),searchWait);
    return;
  }

  if(stage==="collect"){
    clearTimeout(timer);
    const renderWait=currentTask?.mode==="detail"?Math.max(5000,Number(currentTask?.render_wait_ms||6500))
      :(currentTask?.mode==="external_detail"?Math.max(2600,Number(currentTask?.render_wait_ms||3200))
      :(currentTask?.mode==="google_product_source_search"?Math.max(1800,Number(currentTask?.render_wait_ms||2200))
      :(currentTask?.mode==="trend_keyword_collect"?2600
      :(currentTask?.mode==="trend_coupang_pick"?2800
      :(currentTask?.mode==="price"&&currentTask?.site==="네이버쇼핑"?4200
      :(currentTask?.mode==="price"?3000:1000))))));
    timer=setTimeout(()=>collectNow(),renderWait);
  }
});


// v7.25: Deep Toss extraction in the page MAIN world across every accessible
// frame.  This bypasses hashed CSS classes, open Shadow DOM boundaries and the
// common case where the Product Lookup virtual list is mounted in a child frame.
async function mainWorldTossDeepExtract(limit=30){
  if(!workTabId)return{cards:[],diag:{error:'work tab missing'}};
  try{
    const rows=await chrome.scripting.executeScript({
      target:{tabId:workTabId,allFrames:true},world:'MAIN',args:[Math.max(30,Number(limit||30))],
      func:(limit)=>{
        const priceRx=/(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/g;
        const norm=x=>(x||'').replace(/\s+/g,' ').trim();
        const visible=e=>{try{const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>1&&r.height>1&&st.display!=='none'&&st.visibility!=='hidden'&&Number(st.opacity||1)>0.03;}catch(_e){return false;}};
        const mainArea=e=>{if(!e||!visible(e))return false;try{if(e.closest('aside,nav,[role="navigation"]'))return false;}catch(_e){}const r=e.getBoundingClientRect();if(innerWidth>700){const cut=Math.min(280,Math.max(150,innerWidth*0.16));if(r.right<cut+20)return false;}return true;};
        const noise=x=>{const t=norm(x);if(!t||t.length<4)return true;if(/^(상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|상품\s*조회)$/i.test(t))return true;if(/^(무료배송|배송|쿠폰|할인|혜택|적립|광고|리뷰|평점|30일\s*최저가|오늘만\s*특가)/i.test(t))return true;return false;};
        const cleanName=raw=>{
          const lines=String(raw||'').split(/\n+/).map(norm).filter(Boolean),cand=[];
          for(let line of lines){
            line=line.replace(/\d{1,3}(?:,\d{3})+\s*원/g,' ').replace(/\s+/g,' ').trim();
            line=line.replace(/\b\d+\s*%\s*(?:특가|할인)?\b/g,' ').replace(/\s+/g,' ').trim();
            if(noise(line)||line.length>240||!/[A-Za-z가-힣]/.test(line))continue;
            let sc=Math.min(line.length,100);if(line.length>=10)sc+=25;if(line.length>=20)sc+=12;if(/\d+(?:ml|l|g|kg|mg|개|매|팩|세트|인치)/i.test(line))sc+=8;
            cand.push({line,sc});
          }
          cand.sort((a,b)=>b.sc-a.sc||b.line.length-a.line.length);return cand[0]?.line||'';
        };
        const roots=[document],seenRoots=new Set([document]);
        for(let i=0;i<roots.length;i++){let els=[];try{els=[...roots[i].querySelectorAll('*')];}catch(_e){}for(const e of els){try{if(e.shadowRoot&&!seenRoots.has(e.shadowRoot)){seenRoots.add(e.shadowRoot);roots.push(e.shadowRoot);}}catch(_e){}}}
        const out=[],seen=new Set();
        const push=(name,price,text,url='')=>{name=norm(name);if(!name||noise(name)||!price)return;const key=name.toLowerCase().replace(/[^0-9a-z가-힣]/g,'').slice(0,150)+'|'+price;if(!key||seen.has(key))return;seen.add(key);out.push({name,price,text:norm(text).slice(0,1800),url:url||'',image_url:''});};
        for(const root of roots){
          let nodes=[];try{nodes=[...root.querySelectorAll('strong,em,span,p,div,td,tr,li,a,button')].filter(mainArea);}catch(_e){}
          for(const n of nodes){
            const own=norm(n.innerText||n.textContent||'');if(!own||own.length>240||!priceRx.test(own)){priceRx.lastIndex=0;continue;}priceRx.lastIndex=0;
            let e=n,block=null,price=0,name='',text='';
            for(let i=0;e&&i<10;i++,e=e.parentElement){
              if(!mainArea(e))continue;text=(e.innerText||e.textContent||'').trim();const flat=norm(text);if(flat.length<8||flat.length>2400)continue;
              const vals=[...flat.matchAll(priceRx)].map(m=>parseInt(m[1].replaceAll(',',''))).filter(v=>v>=100&&v<=100000000);priceRx.lastIndex=0;if(!vals.length||vals.length>8)continue;
              name=cleanName(text);if(!name)continue;price=Math.min(...vals);block=e;break;
            }
            if(!block||!name||!price)continue;let href='';try{const a=block.matches?.('a[href]')?block:block.querySelector?.('a[href]');href=a?.href||'';}catch(_e){}
            push(name,price,text,href);if(out.length>=limit*3)break;
          }
          if(out.length>=limit*3)break;
        }
        // Pure rendered-text fallback.  Useful for virtualized rows where the
        // price and name are sibling text nodes with no useful card ancestor.
        let bodyText='';try{bodyText=document.body?.innerText||'';}catch(_e){}
        const lines=bodyText.split(/\n+/).map(norm).filter(Boolean);
        for(let i=0;i<lines.length&&out.length<limit*3;i++){
          const line=lines[i];const ms=[...line.matchAll(priceRx)];priceRx.lastIndex=0;if(!ms.length)continue;
          const price=parseInt(ms[0][1].replaceAll(',',''));if(price<100)continue;
          let name=cleanName(line);
          if(!name||name===line.replace(priceRx,'').trim()){
            for(let j=i-1;j>=Math.max(0,i-6);j--){const x=cleanName(lines[j]);if(x&&!noise(x)){name=x;break;}}
          }
          if(name)push(name,price,(lines.slice(Math.max(0,i-4),Math.min(lines.length,i+4))).join(' | '),'');
        }
        return{cards:out.slice(0,limit*3),diag:{url:location.href,roots:roots.length,price_texts:lines.filter(x=>/\d{1,3}(?:,\d{3})+\s*원/.test(x)).length,body_len:bodyText.length,frame_title:document.title||''}};
      }
    });
    const map=new Map(),frames=[];
    for(const row of rows||[]){const r=row?.result||{};frames.push(r.diag||{});for(const c of r.cards||[]){const k=String(c.name||'').toLowerCase().replace(/[^0-9a-z가-힣]/g,'').slice(0,150)+'|'+String(c.price||'');if(k&&!map.has(k))map.set(k,c);}}
    return{cards:[...map.values()].slice(0,Math.max(limit,120)),diag:{frames,frame_count:(rows||[]).length,merged_count:map.size}};
  }catch(e){return{cards:[],diag:{error:String(e)}};}
}
function mergeTossCards(a,b,limit){
  // A popularity slot is a product, not a (product, price) pair.  Toss can show
  // commission/promotional and actual prices for the same card; counting both
  // used to make the browser think it had 30 while Python later de-duplicated
  // the rows back below 30.  Deduplicate by normalized product name here.
  const map=new Map();
  for(const c of [...(a||[]),...(b||[])]){
    const name=String(c?.name||'').trim(),price=Number(c?.price||0);if(!name)continue;
    const k=name.toLowerCase().replace(/[^0-9a-z가-힣]/g,'').slice(0,180);if(!k)continue;
    if(!map.has(k)){map.set(k,c);continue;}
    const old=map.get(k)||{};
    // Prefer a record with URL/image and a non-commission visual price.
    const oldScore=(old.url?4:0)+(old.image_url?2:0)+(!old.commission_price_anchor?1:0);
    const newScore=(c.url?4:0)+(c.image_url?2:0)+(!c.commission_price_anchor?1:0);
    if(newScore>oldScore)map.set(k,c);
  }
  return[...map.values()].slice(0,limit);
}

// v7.26 Toss visual OCR fallback.  DOM parsing has repeatedly failed on the
// real Sharelink Product Lookup screen even while products are visibly drawn.
// Keep the selected category ON, capture the actual viewport, OCR product
// names/prices locally through Windows.Media.Ocr, scroll, and accumulate 30.
async function tossVisualScrollStep(round=0){
  try{
    const rows=await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',args:[round],func:(round)=>{
      const vis=e=>{try{const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>10&&r.height>10&&st.display!=='none'&&st.visibility!=='hidden';}catch(_e){return false;}};
      const all=[document.scrollingElement,document.documentElement,document.body,...document.querySelectorAll('main,[role="main"],section,div')].filter(Boolean);
      let best=null,bestScore=-1;
      for(const e of all){try{if(!vis(e)&&e!==document.scrollingElement&&e!==document.documentElement&&e!==document.body)continue;if(e.closest?.('aside,nav,[role="navigation"]'))continue;const sh=Number(e.scrollHeight||0),ch=Number(e.clientHeight||0);if(sh<=ch+120)continue;const r=e.getBoundingClientRect?.()||{width:innerWidth,height:innerHeight,left:0};const mainBonus=(r.left||0)>Math.min(280,innerWidth*.18)?500:0;const score=(sh-ch)+Math.max(0,r.width||0)+mainBonus;if(score>bestScore){bestScore=score;best=e;}}catch(_e){}}
      if(!best)best=document.scrollingElement||document.documentElement||document.body;
      const before=Number(best.scrollTop||scrollY||0),step=Math.max(420,Math.floor((best.clientHeight||innerHeight)*0.72));
      try{best.scrollTop=Math.min(Math.max(0,best.scrollHeight-(best.clientHeight||innerHeight)),before+step);best.dispatchEvent(new Event('scroll',{bubbles:true}));}catch(_e){scrollBy(0,step);}
      const after=Number(best.scrollTop||scrollY||0);
      if(after<=before+3){
        const btn=[...document.querySelectorAll('button,a,[role="button"]')].find(e=>vis(e)&&/^(더보기|더 보기|다음|다음 페이지|more)$/i.test((e.innerText||e.textContent||'').trim()));
        if(btn){try{btn.click();return{moved:true,more:true,before,after};}catch(_e){}}
      }
      return{moved:after>before+3,before,after,scrollHeight:Number(best.scrollHeight||0),clientHeight:Number(best.clientHeight||0)};
    }});
    return rows?.[0]?.result||{moved:false};
  }catch(e){return{moved:false,error:String(e)};}
}
async function mainWorldTossVisualOCRCollect(limit=30,seedCards=[]){
  const map=new Map();
  const add=arr=>{for(const c of arr||[]){const name=String(c?.name||'').trim(),price=Number(c?.price||0);if(!name||!price)continue;const k=name.toLowerCase().replace(/[^0-9a-z가-힣]/g,'').slice(0,180);if(k&&!map.has(k))map.set(k,c);}};
  add(seedCards);
  const rounds=[];
  for(let round=0;round<14&&map.size<limit;round++){
    let shot=null;
    try{const tab=await chrome.tabs.get(workTabId);shot=await chrome.tabs.captureVisibleTab(tab.windowId,{format:'png'});}catch(e){rounds.push({round,capture_error:String(e)});break;}
    let vr=null;
    try{vr=await post('/api/toss_visual_ocr',{run_id:runId,task_id:currentTask?.id||'',category:currentTask?.site_category_label||currentTask?.blog_category||currentTask?.query||'',round,limit,screenshot:shot,language:'ko-KR'});}catch(e){vr={ok:false,error:String(e),cards:[]};}
    add(vr?.cards||[]);rounds.push({round,found:(vr?.cards||[]).length,total:map.size,diag:vr?.diag||{},error:vr?.error||''});
    if(map.size>=limit)break;
    const mv=await tossVisualScrollStep(round);rounds[round].scroll=mv;
    await new Promise(r=>setTimeout(r,mv?.more?1500:950));
    if(!mv?.moved&&!mv?.more&&round>=4){
      // One return-to-top pass can reveal virtualized products that were dropped.
      try{await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',func:()=>{const e=document.scrollingElement||document.documentElement||document.body;e.scrollTop=0;scrollTo(0,0);}});}catch(_e){}
      await new Promise(r=>setTimeout(r,700));
    }
  }
  return{cards:[...map.values()].slice(0,limit),diag:{rounds,merged_count:map.size,method:'windows_visual_ocr'}};
}
async function finalizeTossAfterDeep(siteCategory){
  try{return await chrome.tabs.sendMessage(workTabId,{type:'tossFinalizeCategory',site_category_label:siteCategory,category_label:siteCategory});}
  catch(e){return{status:'error',error:String(e),toss_uncheck_after_collect:false};}
}

// v7.27 legacy Toss CDP Accessibility collector (v7.28: route disabled; kept only as diagnostic reference).
// This is the primary Toss engine. It does not depend on React CSS classes,
// content-script checkbox state, or Windows OCR. Chrome's accessibility tree is
// used both to click the actual visible category control and to read rendered
// product names/prices. Screenshot OCR remains a final fallback only.
let TOSS_CDP_ATTACHED=false;
function tossNorm(x){return String(x||'').replace(/\s+/g,' ').trim();}
function tossKey(x){return tossNorm(x).toLowerCase().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');}
function axValue(v){return v&&typeof v==='object'&&'value' in v?v.value:v;}
function axRole(n){return String(axValue(n?.role)||'').toLowerCase();}
function axName(n){return tossNorm(axValue(n?.name)||'');}
function axProp(n,name){for(const p of n?.properties||[])if(p?.name===name)return axValue(p.value);return undefined;}
function axChecked(n){
  for(const k of ['checked','selected','pressed']){const v=axProp(n,k);if(v===true||v==='true'||v==='checked'||v==='mixed')return true;if(v===false||v==='false'||v==='unchecked')return false;}
  return null;
}
async function cdpAttach(){
  if(TOSS_CDP_ATTACHED)return true;
  try{await chrome.debugger.attach({tabId:workTabId},'1.3');TOSS_CDP_ATTACHED=true;return true;}
  catch(e){if(String(e).toLowerCase().includes('already attached')){TOSS_CDP_ATTACHED=true;return true;}throw e;}
}
async function cdpDetach(){if(!TOSS_CDP_ATTACHED)return;try{await chrome.debugger.detach({tabId:workTabId});}catch(_e){}TOSS_CDP_ATTACHED=false;}
async function cdp(method,params={}){return await chrome.debugger.sendCommand({tabId:workTabId},method,params);}
async function cdpAX(){await cdp('Accessibility.enable',{});return (await cdp('Accessibility.getFullAXTree',{}))?.nodes||[];}
function axMaps(nodes){const by=new Map(),children=new Map();for(const n of nodes){by.set(String(n.nodeId),n);if(n.parentId){const k=String(n.parentId),a=children.get(k)||[];a.push(String(n.nodeId));children.set(k,a);}}return{by,children};}
function axNoise(s){const t=tossNorm(s);if(!t||t.length<3||t.length>190)return true;if(!/[A-Za-z가-힣]/.test(t))return true;return /^(상품\s*조회|카테고리|검색|전체|홈|링크|링크\s*관리|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|무료배송|배송|쿠폰|할인|혜택|적립|광고|리뷰|평점|30일\s*최저가|오늘만\s*특가|더보기|다음)$/i.test(t);}
function axCleanName(raw){let s=tossNorm(raw).replace(/\d{1,3}(?:,\d{3})+\s*원/g,' ').replace(/\b\d{1,3}\s*%\s*(?:특가|할인)?\b/g,' ').replace(/\s+/g,' ').trim();return s;}
function axPrice(text){const arr=[...String(text||'').matchAll(/(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원/g)].map(m=>Number(m[1].replaceAll(',',''))).filter(v=>v>=100&&v<=100000000);return arr.length?arr[0]:0;}
function axSubtreeText(id,maps,max=100){const out=[],q=[String(id)],seen=new Set();while(q.length&&out.length<max){const x=q.shift();if(seen.has(x))continue;seen.add(x);const n=maps.by.get(x);if(n){const name=axName(n);if(name)out.push({name,role:axRole(n),id:x,node:n});for(const c of maps.children.get(x)||[])q.push(c);}}return out;}
function parseTossAXProducts(nodes,limit=90){
  const maps=axMaps(nodes),out=[],seen=new Set();
  const priceNodes=nodes.filter(n=>axPrice(axName(n))>0 && !/(개당|수익)/.test(axName(n)));
  for(const pn of priceNodes){
    const price=axPrice(axName(pn));if(!price)continue;
    let anc=pn,best=null;
    for(let depth=0;depth<8&&anc;depth++){
      const items=axSubtreeText(anc.nodeId,maps,80);const prices=items.filter(x=>axPrice(x.name)>0&&!/(개당|수익)/.test(x.name));
      const cand=[];
      for(const x of items){let nm=axCleanName(x.name);if(axPrice(x.name)>0||axNoise(nm)||/^(개당|수익|30일\s*최저가)/.test(nm))continue;let score=Math.min(nm.length,110);if(x.role==='link')score+=90;if(x.role==='heading')score+=40;if(nm.length>=10)score+=25;if(nm.length>=20)score+=15;if(/\d+(?:ml|l|g|kg|mg|개|매|팩|세트|인치)/i.test(nm))score+=8;cand.push({name:nm,score,role:x.role});}
      cand.sort((a,b)=>b.score-a.score||b.name.length-a.name.length);
      if(cand.length && prices.length>=1 && prices.length<=3){best={name:cand[0].name,price,score:cand[0].score};break;}
      anc=anc.parentId?maps.by.get(String(anc.parentId)):null;
    }
    if(!best)continue;const key=tossKey(best.name);if(!key||seen.has(key))continue;seen.add(key);out.push({name:best.name,price:best.price,text:`${best.name} ${best.price.toLocaleString()}원`,url:'',image_url:'',cdp_ax:true});if(out.length>=limit)break;
  }
  return out;
}
async function axNodeBox(n){
  const id=Number(n?.backendDOMNodeId||0);if(!id)return null;
  try{const r=await cdp('DOM.getBoxModel',{backendNodeId:id});const q=r?.model?.border||r?.model?.content;if(!q||q.length<8)return null;const xs=[q[0],q[2],q[4],q[6]],ys=[q[1],q[3],q[5],q[7]];const x=Math.min(...xs),y=Math.min(...ys),right=Math.max(...xs),bottom=Math.max(...ys);return{x,y,width:right-x,height:bottom-y,cx:(x+right)/2,cy:(y+bottom)/2};}catch(_e){return null;}
}
async function cdpViewport(){try{return (await cdp('Runtime.evaluate',{expression:'({width:innerWidth,height:innerHeight,dpr:devicePixelRatio||1,path:location.pathname,url:location.href})',returnByValue:true}))?.result?.value||{};}catch(_e){return{};}}
async function cdpShot(){try{return 'data:image/png;base64,'+(await cdp('Page.captureScreenshot',{format:'png',fromSurface:true}))?.data;}catch(_e){return null;}}
async function detailMainWorld(func,args=[]){
  try{
    const rows=await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',func,args});
    return rows?.[0]?.result||null;
  }catch(e){return{error:String(e)}}
}

async function resolveCoupangProductHrefFromPage(selected){
  if(!workTabId||currentTask?.site!=="쿠팡"||!selected)return{ok:false,error:"selection missing"};
  try{
    const rows=await chrome.scripting.executeScript({
      target:{tabId:workTabId,allFrames:true},world:"MAIN",
      args:[selected.name||"",selected.text||"",selected.url||""],
      func:(selectedName,selectedText,existingUrl)=>{
        const direct=u=>{try{const x=new URL(u||"",location.href);return /(^|\.)coupang\.com$/i.test(x.hostname)&&/\/vp\/products\/\d+/i.test(x.pathname)}catch(_e){return false}};
        if(direct(existingUrl))return{ok:true,url:new URL(existingUrl,location.href).href,method:"selected_direct",score:1};
        const norm=s=>String(s||"").toLowerCase().replace(/\s+/g,"").replace(/[^0-9a-z가-힣]/g,"");
        const token=s=>[...new Set((String(s||"").toLowerCase().match(/[0-9a-z가-힣]+/g)||[]).filter(x=>x.length>=2))];
        const target=String(selectedName||selectedText||"");const targetTokens=token(target);const compact=norm(target);
        const candidates=[];
        for(const a of document.querySelectorAll("a[href*='/vp/products/']")){
          if(!direct(a.href))continue;
          let card=a;for(let i=0;card&&i<5;i++,card=card.parentElement){
            const text=String(card.innerText||card.textContent||"").replace(/\s+/g," ").trim();
            if(!text||text.length>2200)continue;
            const low=text.toLowerCase(),hits=targetTokens.filter(x=>low.includes(x)).length;
            let score=targetTokens.length?hits/targetTokens.length:0;
            if(compact&&norm(text).includes(compact.slice(0,Math.min(24,compact.length))))score+=0.35;
            if(a.querySelector("img"))score+=0.05;
            candidates.push({url:a.href,score,text:text.slice(0,500)});break;
          }
        }
        candidates.sort((a,b)=>b.score-a.score);
        const best=candidates[0];
        return best&&best.score>=0.45?{ok:true,url:best.url,method:"page_anchor_rescan",score:best.score,candidate_text:best.text}:{ok:false,error:"direct_product_anchor_not_found",candidate_count:candidates.length,best_score:best?.score||0};
      }
    });
    const found=(rows||[]).map(x=>x?.result).filter(x=>x?.ok&&x?.url).sort((a,b)=>Number(b.score||0)-Number(a.score||0))[0];
    return found||{ok:false,error:"direct_product_anchor_not_found_in_frames",frames:(rows||[]).length};
  }catch(e){return{ok:false,error:String(e)}}
}
async function detailVisibleTabClipCapture(rect,label,index,meta={}){
  if(!rect||!workTabId)return null;
  try{
    const pos=await detailMainWorld(async(rect)=>{
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const rw=Math.max(1,Number(rect.width||0)),rh=Math.max(1,Number(rect.height||0));
      const targetY=Math.max(0,Number(rect.y||0)-Math.max(35,Math.min(150,innerHeight*0.12)));
      window.scrollTo({top:targetY,left:0,behavior:'instant'});await sleep(320);
      const x=Math.max(0,Number(rect.x||0)-scrollX),y=Math.max(0,Number(rect.y||0)-scrollY);
      const maxW=Math.max(1,innerWidth-x-8),maxH=Math.max(1,innerHeight-y-8);
      const width=Math.min(rw,maxW),height=Math.min(rh,maxH,Math.max(180,innerHeight*0.82));
      return{ok:width>=120&&height>=120,rect:{x,y,width,height},viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio||1},scrollY};
    },[rect]);
    if(!pos?.ok)return null;
    const tab=await chrome.tabs.get(workTabId);
    const shot=await chrome.tabs.captureVisibleTab(tab.windowId,{format:'png'});
    if(!shot)return null;
    const saved=await post('/api/detail_capture_viewport',{task_id:currentTask?.id||'detail',label,index,meta:Object.assign({capture_engine:'captureVisibleTab'},meta),rect:pos.rect,viewport:pos.viewport,screenshot:shot});
    return saved?.ok?Object.assign({kind:'rendered_screen_crop',fallback:'captureVisibleTab'},saved,{capture_label:label,source_meta:Object.assign({capture_engine:'captureVisibleTab'},meta)}):null;
  }catch(e){return null}
}
async function detailClipCapture(rect,label,index,meta={}){
  if(!rect||!Number.isFinite(Number(rect.x))||!Number.isFinite(Number(rect.y)))return null;
  const x=Math.max(0,Number(rect.x)),y=Math.max(0,Number(rect.y));
  const width=Math.max(1,Math.min(2200,Number(rect.width||0))),height=Math.max(1,Math.min(1900,Number(rect.height||0)));
  if(width<120||height<120)return null;
  // Primary: precise CDP clip. Fallback: visible-tab screenshot + local crop.
  // The fallback keeps image saving working even when another DevTools/debugger
  // session prevents chrome.debugger from attaching.
  if(pageDialogGuard.attached){
    try{
      const r=await cdp('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:true,clip:{x,y,width,height,scale:1}});
      if(r?.data){
        const saved=await post('/api/detail_capture',{task_id:currentTask?.id||'detail',label,index,meta:Object.assign({capture_engine:'cdp'},meta),screenshot:'data:image/png;base64,'+r.data});
        if(saved?.ok)return Object.assign({kind:'rendered_screen_crop'},saved,{capture_label:label,source_meta:Object.assign({capture_engine:'cdp'},meta)});
      }
    }catch(e){}
  }
  return await detailVisibleTabClipCapture({x,y,width,height},label,index,meta);
}
async function coupangMainImageInfo(){
  return await detailMainWorld(()=>{
    const visible=e=>{try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>=220&&r.height>=220&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0.05}catch(_){return false}};
    const bad=e=>{let s='',n=e;for(let i=0;i<7&&n;i++,n=n.parentElement)s+=' '+String(n.className||'')+' '+String(n.id||'')+' '+String(n.getAttribute?.('aria-label')||'');return /(recommend|related|similar|recent|ranking|best[-_ ]?item|other[-_ ]?product|banner|advert|coupon|delivery|review|연관|추천상품|함께본|최근본|광고|배너)/i.test(s)};
    const selectors=['#repImageContainer img','.prod-image__detail img','.prod-image img','[class*="prod-image"] img','[class*="product-image"] img','[class*="gallery"] img','main img'];
    const seen=new Set(),arr=[];
    for(let tier=selectors.length;tier>0;tier--){let ims=[];try{ims=[...document.querySelectorAll(selectors[selectors.length-tier])]}catch(_){}for(const im of ims){if(seen.has(im)||!visible(im)||bad(im))continue;seen.add(im);const r=im.getBoundingClientRect();const py=r.top+scrollY;if(py>1500)continue;const ratio=r.width/Math.max(1,r.height);if(ratio>4.5||ratio<0.2)continue;const area=r.width*r.height;arr.push({im,score:area+tier*1e8,rect:{x:r.left+scrollX,y:py,width:r.width,height:r.height},src:im.currentSrc||im.src||'',alt:im.alt||''})}}
    arr.sort((a,b)=>b.score-a.score);const z=arr[0];return z?{rect:z.rect,src:z.src,alt:z.alt,score:z.score}:null;
  });
}
async function coupangClickGalleryThumb(index,waitMs=1800){
  return await detailMainWorld(async(index,waitMs)=>{
    const vis=e=>{try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>20&&r.height>20&&r.width<220&&r.height<220&&r.top<1200&&r.bottom>0&&s.display!=='none'&&s.visibility!=='hidden'}catch(_){return false}};
    const sels=['.prod-image__item','.prod-image__items li','.prod-image__item img','[class*="prod-image"] [class*="thumb"]','[class*="gallery"] [class*="thumb"]','[class*="thumbnail"] img'];
    const arr=[],seen=new Set();for(const sel of sels){let es=[];try{es=[...document.querySelectorAll(sel)]}catch(_){}for(const e0 of es){const e=e0.matches?.('img')?(e0.closest('li,button,a,div')||e0):e0;if(seen.has(e)||!vis(e))continue;seen.add(e);const t=(e.innerText||'')+' '+String(e.className||'');if(/recommend|related|recent|ranking|추천|연관|최근/i.test(t))continue;arr.push(e)}}
    if(arr.length<=index)return{ok:false,count:arr.length};const e=arr[index];try{
      e.scrollIntoView({block:'center',behavior:'instant'});e.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));e.click();
      await new Promise(r=>setTimeout(r,Math.max(900,Number(waitMs||1800))));
      const main=document.querySelector('#repImageContainer img,.prod-image__detail img,.prod-image img,[class*="product-image"] img');
      if(main?.decode){try{await Promise.race([main.decode(),new Promise(r=>setTimeout(r,2400))])}catch(_){}}
      return{ok:true,count:arr.length,loaded:!!main?.complete,natural_width:Number(main?.naturalWidth||0),natural_height:Number(main?.naturalHeight||0)}
    }catch(err){return{ok:false,count:arr.length,error:String(err)}}
  },[index,waitMs]);
}
async function coupangDetailImageInfo(index,waitMs=1100){
  return await detailMainWorld(async(index,waitMs)=>{
    const sleep=ms=>new Promise(r=>setTimeout(r,ms));
    const waitReady=async(im,maxMs=2800)=>{let stable=0,last='';const start=Date.now();while(Date.now()-start<maxMs){const key=`${im.complete}:${im.naturalWidth||0}x${im.naturalHeight||0}:${im.currentSrc||im.src||''}`;if(im.complete&&im.naturalWidth>=220&&im.naturalHeight>=220&&key===last)stable++;else stable=0;last=key;if(stable>=2)return true;try{if(im.decode)await Promise.race([im.decode(),sleep(350)])}catch(_){}await sleep(180)}return !!(im.complete&&im.naturalWidth>=220&&im.naturalHeight>=220)};
    const buttons=[...document.querySelectorAll('button,a,[role="button"]')].filter(e=>/상품\s*(상세|정보).*더보기|상세.*더보기|펼쳐보기/.test((e.innerText||'').replace(/\s+/g,' ')));
    for(const b of buttons.slice(0,3)){try{b.click();await sleep(450)}catch(_){} }
    const bad=e=>{let s='',n=e;for(let i=0;i<8&&n;i++,n=n.parentElement)s+=' '+String(n.className||'')+' '+String(n.id||'')+' '+String(n.getAttribute?.('aria-label')||'');return /(recommend|related|similar|recent|ranking|best[-_ ]?item|other[-_ ]?product|carousel|banner|advert|coupon|review|연관|추천상품|함께본|최근본|광고|배너|리뷰)/i.test(s)};
    const detailSels=['#productDetail','#productDescription','.product-detail-content-inside','.product-detail-content','[class*="product-detail"]','[class*="detail-content"]','[class*="description"]'];
    let containers=[];for(const sel of detailSels){try{containers.push(...document.querySelectorAll(sel))}catch(_){}}
    containers=[...new Set(containers)].filter(e=>!bad(e)).sort((a,b)=>(b.scrollHeight||0)-(a.scrollHeight||0));
    const container=containers[0]||null;
    // v7.46: activate lazy image URLs and finish a bounded decode pass before
    // dimensions are used as a rejection gate. Otherwise naturalWidth=0 races
    // can discard perfectly valid detail images before they enter the viewport.
    if(container){
      const lazy=[...container.querySelectorAll('img')].slice(0,80);
      for(const im of lazy){
        try{
          const src=im.currentSrc||im.src||im.getAttribute('data-src')||im.getAttribute('data-original')||im.getAttribute('data-lazy-src')||im.getAttribute('data-url')||'';
          if(src&&!im.src)im.src=src;
          im.loading='eager';
        }catch(_){}
      }
      try{container.scrollIntoView({block:'start',behavior:'instant'});await sleep(Math.max(800,Number(waitMs||1100)))}catch(_){}
      const cr=container.getBoundingClientRect();const top=cr.top+scrollY;const bottom=top+Math.max(cr.height,container.scrollHeight||0);
      for(let y=top;y<Math.min(bottom,top+16000);y+=Math.max(650,innerHeight*.78)){
        try{scrollTo({top:y,behavior:'instant'});await sleep(Math.max(500,Number(waitMs||1100)*.55))}catch(_){}
      }
      try{
        await Promise.race([
          Promise.allSettled(lazy.slice(0,40).map(im=>im.decode?im.decode():Promise.resolve())),
          sleep(2200)
        ]);
      }catch(_){}
    }
    const sels=['#productDetail img','#productDescription img','.product-detail-content-inside img','.product-detail-content img','[class*="product-detail"] img','[class*="detail-content"] img','[class*="description"] img','article img'];
    const seen=new Set(),arr=[];
    for(let tier=sels.length;tier>0;tier--){let ims=[];try{ims=[...document.querySelectorAll(sels[sels.length-tier])]}catch(_){}for(const im of ims){
      if(seen.has(im)||bad(im))continue;seen.add(im);
      try{im.scrollIntoView({block:'center',behavior:'instant'});await sleep(80)}catch(_){}
      const r=im.getBoundingClientRect(),nw=Number(im.naturalWidth||0),nh=Number(im.naturalHeight||0),w=Math.max(Number(r.width||0),nw),h=Math.max(Number(r.height||0),nh);
      if(w<240||h<240)continue;
      const ratio=w/Math.max(1,h);if(ratio>5.5)continue; // no lower ratio rejection: long detail is valid
      const py=r.top+scrollY;if(py<650)continue;
      const src=im.currentSrc||im.src||im.getAttribute('data-src')||im.getAttribute('data-original')||im.getAttribute('data-lazy-src')||'';
      arr.push({im,score:Math.min(w,2200)*Math.min(h,14000)+tier*1e9,src,alt:im.alt||'',long_detail:ratio<.20});
    }}
    arr.sort((a,b)=>b.score-a.score);const z=arr[index];if(!z)return{ok:false,count:arr.length,container_found:!!container};
    try{z.im.scrollIntoView({block:'center',behavior:'instant'});await sleep(Math.max(700,Number(waitMs||1100)));await waitReady(z.im)}catch(_){}
    const r=z.im.getBoundingClientRect();if(r.width<220||r.height<220)return{ok:false,count:arr.length,reason:'rendered_too_small',container_found:!!container};
    return{ok:true,count:arr.length,rect:{x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height},src:z.im.currentSrc||z.im.src||z.src,alt:z.im.alt||z.alt,long_detail:!!z.long_detail,container_found:!!container};
  },[index,waitMs]);
}

async function coupangDetailContainerSegments(maxSegments=4,waitMs=850){
  return await detailMainWorld(async(maxSegments,waitMs)=>{
    const sleep=ms=>new Promise(r=>setTimeout(r,ms));
    const bad=e=>{let s='',n=e;for(let i=0;i<8&&n;i++,n=n.parentElement)s+=' '+String(n.className||'')+' '+String(n.id||'');return /(recommend|related|recent|ranking|review|banner|advert|coupon|연관|추천상품|최근본|리뷰|광고|배너)/i.test(s)};
    for(const b of [...document.querySelectorAll('button,a,[role="button"]')]){const t=(b.innerText||'').replace(/\s+/g,' ');if(/상품\s*(상세|정보).*더보기|상세.*더보기|펼쳐보기/.test(t)){try{b.click();await sleep(420)}catch(_){}}}
    const sels=['#productDetail','#productDescription','.product-detail-content-inside','.product-detail-content','[class*="product-detail"]','[class*="detail-content"]','[class*="description"]','article'];
    const all=[];for(let tier=sels.length;tier>0;tier--){let es=[];try{es=[...document.querySelectorAll(sels[sels.length-tier])]}catch(_){}for(const e of es){if(bad(e))continue;const r=e.getBoundingClientRect();const h=Math.max(r.height,e.scrollHeight||0),w=Math.max(r.width,e.scrollWidth||0);if(w<420||h<500)continue;all.push({e,w,h,tier,score:Math.min(w,1400)*Math.min(h,30000)+tier*1e9})}}
    all.sort((a,b)=>b.score-a.score);const z=all[0];if(!z)return{ok:false,segments:[],reason:'detail_container_missing'};
    const e=z.e;try{e.scrollIntoView({block:'start',behavior:'instant'});await sleep(Math.max(700,Number(waitMs||850)))}catch(_){}
    // Force lazy resources to render through the first 18k px of detail content.
    let r=e.getBoundingClientRect();let top=r.top+scrollY,totalH=Math.max(r.height,e.scrollHeight||0);
    for(let off=0;off<Math.min(totalH,18000);off+=Math.max(700,innerHeight*.8)){try{scrollTo({top:top+off,behavior:'instant'});await sleep(Math.max(420,Number(waitMs||850)*.55))}catch(_){}}
    r=e.getBoundingClientRect();top=r.top+scrollY;totalH=Math.max(r.height,e.scrollHeight||0);const width=Math.min(1600,Math.max(420,r.width));const x=Math.max(0,r.left+scrollX);
    const segH=Math.min(1500,Math.max(800,innerHeight*1.25));const n=Math.max(1,Math.min(Number(maxSegments||4),Math.ceil(totalH/segH)));
    const offsets=[];if(n===1)offsets.push(0);else for(let i=0;i<n;i++)offsets.push(Math.max(0,(totalH-segH)*(i/(n-1))));
    const segments=offsets.map((off,i)=>({x,y:top+off,width,height:Math.min(segH,totalH-off),segment_index:i,total_height:totalH})).filter(x=>x.width>=300&&x.height>=300);
    return{ok:segments.length>0,segments,total_height:totalH,width,container_class:String(e.className||'').slice(0,160)};
  },[maxSegments,waitMs]);
}

async function coupangDomResourceUrls(){
  return await detailMainWorld(()=>{
    const bad=s=>/(logo|sprite|avatar|icon|badge|tracking|pixel|favicon|banner|advert|coupon|review|recommend|related|recent|ranking|loading|placeholder)/i.test(String(s||''));
    const urls=new Set();const add=u=>{if(!u)return;for(const v of String(u).split(',')){const raw=v.trim().split(/\s+/)[0];if(!raw||bad(raw))continue;try{const z=new URL(raw,location.href).href;if(/^https?:/i.test(z))urls.add(z)}catch(_){}}};
    let roots=[...document.querySelectorAll('#repImageContainer,#productDetail,#productDescription,.prod-image,.product-detail-content-inside,.product-detail-content,[class*="gallery"],[class*="product-detail"],[class*="detail-content"]')];
    roots=[...new Set(roots)];if(!roots.length)roots=[document];
    for(const root of roots){let els=[];try{els=[...root.querySelectorAll('img,source,[style]')]}catch(_){}for(const e of els){for(const a of ['src','srcset','data-src','data-original','data-lazy-src','data-zoom-image','data-image','data-srcset'])add(e.getAttribute?.(a)||'');try{const bg=getComputedStyle(e).backgroundImage||'';for(const m of bg.matchAll(/url\(["']?([^"')]+)["']?\)/g))add(m[1])}catch(_){}}}
    // Structured product metadata is a useful browser-visible fallback.
    for(const sc of document.querySelectorAll('script[type="application/ld+json"]')){try{const obj=JSON.parse(sc.textContent||'{}');const walk=o=>{if(!o)return;if(Array.isArray(o)){for(const x of o)walk(x);return}if(typeof o==='object'){if(o.image){if(Array.isArray(o.image))o.image.forEach(add);else if(typeof o.image==='string')add(o.image);else walk(o.image)}for(const [k,v] of Object.entries(o)){if(k!=='image')walk(v)}}};walk(obj)}catch(_){}}
    for(const m of document.querySelectorAll('meta[property="og:image"],meta[name="twitter:image"]'))add(m.content||'');
    return{urls:[...urls].slice(0,180)};
  });
}

async function waitForCoupangImageNetworkIdle(maxWaitMs=8000,quietMs=1000){
  const started=Date.now();let lastPending=0;
  while(Date.now()-started<Math.max(1000,Number(maxWaitMs||8000))){
    const pending=[...coupangImageNet.entries.values()].filter(x=>!x.finished).length;lastPending=pending;
    const quietFor=Date.now()-Number(coupangImageNet.lastEventAt||started);
    if(pending===0&&quietFor>=Math.max(400,Number(quietMs||1000)))return{ok:true,pending,quiet_for_ms:quietFor,waited_ms:Date.now()-started};
    await taskProgressBeat('coupang_network_wait');
    await bridgeSleep(300);
  }
  return{ok:false,pending:lastPending,waited_ms:Date.now()-started,reason:'network_idle_timeout'};
}

async function captureCoupangNetworkImages(allowedUrls,maxCount=4,startIndex=1){
  const captures=[],diag={candidates:0,allowed:(allowedUrls||[]).length,errors:[]};
  if(!pageDialogGuard.attached||!coupangImageNet.active)return{captures,diag:Object.assign(diag,{error:'network_debugger_inactive'})};
  const allow=new Set((allowedUrls||[]).map(imageUrlKey));
  let rows=[...coupangImageNet.entries.values()].filter(e=>e.finished&&!imageNetBadUrl(e.url)&&Number(e.encodedDataLength||0)>=12000);
  if(allow.size)rows=rows.filter(e=>allow.has(imageUrlKey(e.url)));
  rows.sort((a,b)=>Number(b.encodedDataLength||0)-Number(a.encodedDataLength||0));diag.candidates=rows.length;
  for(const e of rows){
    if(captures.length>=Math.max(1,Number(maxCount||4)))break;
    try{
      const body=await cdp('Network.getResponseBody',{requestId:e.requestId});if(!body?.body)continue;
      let data;if(body.base64Encoded)data=`data:${e.mime||'image/jpeg'};base64,${body.body}`;else{const u=unescape(encodeURIComponent(body.body));data=`data:${e.mime||'image/jpeg'};base64,${btoa(u)}`}
      const saved=await post('/api/detail_capture',{task_id:currentTask?.id||'detail',label:'브라우저수신이미지',index:startIndex+captures.length,meta:{role:'network_rendered_resource',url:e.url,bytes:e.encodedDataLength||0},screenshot:data});
      if(saved?.ok){captures.push(Object.assign({kind:'network_response_image'},saved,{source_meta:{role:'network_rendered_resource',url:e.url}}));coupangImageNet.stats.bodySaved++}
    }catch(err){coupangImageNet.stats.bodyErrors++;diag.errors.push(String(err).slice(0,180))}
  }
  diag.stats=Object.assign({},coupangImageNet.stats);return{captures,diag};
}

async function captureCoupangRenderedProductImages(){
  const captures=[],diag={main:false,thumb_attempts:[],detail_attempts:[],container_segments:null,network:null,gallery_first:true};
  if(currentTask?.site!=='쿠팡'||currentTask?.mode!=='detail')return{captures,diag};
  if(!pageDialogGuard.attached)diag.debugger_fallback='captureVisibleTab';
  await taskProgressBeat('coupang_crop_start');
  const targetCount=Math.max(3,Math.min(5,Number(currentTask?.screen_crop_target_count||3)));
  let main=await coupangMainImageInfo();
  if(main?.rect){const c=await detailClipCapture(main.rect,'대표이미지_화면크롭',captures.length+1,{role:'representative',src:main.src||''});if(c){captures.push(c);diag.main=true}}
  let priorSrc=main?.src||'';

  // v7.49: TITLE/GALLERY FIRST. If the product page contains multiple title
  // images, use them before any product-detail scrolling. This is faster and
  // guarantees that the selected photos visibly show the product.
  if(currentTask?.allow_gallery_fallback!==false)for(const idx of [1,2,3,4,5,6]){
    if(captures.length>=targetCount)break;
    await taskProgressBeat('coupang_gallery_title_'+idx);
    const click=await coupangClickGalleryThumb(idx,Number(currentTask?.screen_crop_gallery_wait_ms||1200));diag.thumb_attempts.push({index:idx,click});if(!click?.ok)continue;
    const changed=await coupangMainImageInfo();if(!changed?.rect)continue;
    if(priorSrc&&changed.src&&changed.src===priorSrc)continue;
    const c=await detailClipCapture(changed.rect,'타이틀갤러리_화면크롭',captures.length+1,{role:'gallery_title',thumb_index:idx,src:changed.src||'',changed_src:!!changed.src&&changed.src!==priorSrc});
    if(c){captures.push(c);priorSrc=changed.src||priorSrc}
  }
  if(captures.length>=targetCount){await taskProgressBeat('coupang_crop_done_gallery_only');return{captures,diag}}

  // Only if gallery/title images are insufficient do we activate lazy-loaded
  // product detail. We generate several candidate regions; Python later rejects
  // text/legal/barcode sheets and keeps only product-visible crops.
  for(let i=0;i<Math.max(3,Number(currentTask?.screen_crop_max_candidates||7))&&captures.length<targetCount+5;i++){
    await taskProgressBeat('coupang_detail_'+i);
    const d=await coupangDetailImageInfo(i,Number(currentTask?.screen_crop_detail_wait_ms||750));diag.detail_attempts.push({index:i,ok:!!d?.ok,count:d?.count||0,reason:d?.reason||'',long_detail:!!d?.long_detail,container_found:!!d?.container_found});if(!d?.ok||!d.rect)continue;
    if(currentTask?.capture_long_detail_segments!==false&&d.long_detail&&d.rect.height>1400){
      const segH=Math.min(1500,Math.max(720,d.rect.width*1.65));
      for(const frac of [0,.18,.36,.54,.72,.88]){if(captures.length>=targetCount+5)break;const off=Math.max(0,(d.rect.height-segH)*frac);const rect={x:d.rect.x,y:d.rect.y+off,width:d.rect.width,height:Math.min(segH,d.rect.height-off)};const c=await detailClipCapture(rect,'긴상세_제품후보크롭',captures.length+1,{role:'detail_long_segment',detail_index:i,segment_fraction:frac,src:d.src||''});if(c)captures.push(c)}
    }else{
      const c=await detailClipCapture(d.rect,'상세설명_제품후보크롭',captures.length+1,{role:'detail_description',detail_index:i,src:d.src||''});if(c)captures.push(c);
    }
  }
  // One giant description container may not expose its internal images. Capture
  // more overlapping candidate slices and let Python select product-rich ones.
  if(currentTask?.capture_long_detail_segments!==false&&captures.length<targetCount+5){
    await taskProgressBeat('coupang_detail_segments');
    const seg=await coupangDetailContainerSegments(Math.max(6,Number(currentTask?.screen_crop_max_candidates||7)),Number(currentTask?.screen_crop_detail_wait_ms||750));diag.container_segments={ok:!!seg?.ok,count:(seg?.segments||[]).length,total_height:seg?.total_height||0,width:seg?.width||0,reason:seg?.reason||''};
    for(const r of seg?.segments||[]){if(captures.length>=targetCount+6)break;const c=await detailClipCapture(r,'상세영역_제품후보크롭',captures.length+1,{role:'detail_container_segment',segment_index:r.segment_index,total_height:r.total_height});if(c)captures.push(c)}
  }
  // Network-body fallback is restricted to exact-page DOM-referenced images.
  if(currentTask?.capture_network_images!==false&&captures.length<targetCount+5){
    const idle=await waitForCoupangImageNetworkIdle(Number(currentTask?.network_idle_max_wait_ms||5500),Number(currentTask?.network_idle_quiet_ms||700));
    const dom=await coupangDomResourceUrls();const net=await captureCoupangNetworkImages(dom?.urls||[],Math.max(1,targetCount+5-captures.length),captures.length+1);diag.network=Object.assign({idle},net?.diag||{});for(const c of net?.captures||[])captures.push(c)
  }
  await taskProgressBeat('coupang_crop_done');
  return{captures,diag};
}

// v7.51: Toss productUrl returned by Sharelink API points to toss.shopping/t/....
// Capture the primary product gallery near the top BEFORE generic detail scrolling.
// This avoids losing the visible 1/4, 2/4 ... product images and avoids QR/review areas.
async function captureTossTopGalleryImages(){
  const captures=[],diag={site:currentTask?.site||'',candidates:0,errors:[]};
  if(!currentTask||currentTask.mode!=='detail'||currentTask.site!=='토스쇼핑')return{captures,diag};
  try{
    const rows=await detailMainWorld(async()=>{
      const badMeta=s=>/(logo|icon|badge|banner|advert|coupon|delivery|pay|qr|qrcode|review|rating|seller|profile|avatar|추천|리뷰|판매자|qr코드)/i.test(String(s||''));
      const out=[],seen=new Set();
      for(const im of [...document.querySelectorAll('img')]){
        try{
          const r=im.getBoundingClientRect(),nw=Number(im.naturalWidth||0),nh=Number(im.naturalHeight||0);
          const w=Math.max(r.width,nw),h=Math.max(r.height,nh),x=r.left+scrollX,y=r.top+scrollY;
          // Do not assume a 900px-wide window. On the user's maximized Chrome
          // the real Toss gallery can sit to the right of x=900.
          if(w<260||h<260||y<20||y>Math.max(1600,innerHeight*1.8)||x<0||x>scrollX+innerWidth-40)continue;
          const src=im.currentSrc||im.getAttribute('data-src')||im.getAttribute('data-original')||im.src||'';
          const meta=(im.alt||'')+' '+(im.title||'')+' '+String(im.className||'')+' '+src;
          if(!src||badMeta(meta))continue;
          const ratio=w/Math.max(1,h);if(ratio>3.5||ratio<0.22)continue;
          const key=src||`${Math.round(x)}:${Math.round(y)}:${Math.round(w)}:${Math.round(h)}`;if(seen.has(key))continue;seen.add(key);
          out.push({x,y,width:r.width||Math.min(w,1800),height:r.height||Math.min(h,1800),src,alt:im.alt||'',score:Math.min(w,1800)*Math.min(h,1800)-y*1000});
        }catch(_){}
      }
      out.sort((a,b)=>b.score-a.score);return out.slice(0,8);
    });
    const arr=Array.isArray(rows)?rows:[];diag.candidates=arr.length;
    for(const r of arr){
      if(captures.length>=4)break;
      const c=await detailClipCapture(r,'토스_타이틀갤러리_제품이미지',captures.length+1,{role:'toss_title_gallery',src:r.src||'',alt:r.alt||''});
      if(c)captures.push(c);
    }
  }catch(e){diag.errors.push(String(e))}
  return{captures,diag};
}

// v7.44: generic rendered-image fallback for an already-known exact Naver/Toss
// product page. Python verifies the product/page identity before these crops are
// accepted. This avoids depending on direct CDN downloads while never opening
// Coupang in the image stage.
async function captureGenericRenderedProductImages(){
  const captures=[],diag={site:currentTask?.site||'',candidates:0,segments:0,errors:[]};
  if(!currentTask||currentTask.mode!=='detail'||currentTask.site==='쿠팡')return{captures,diag};
  if(!pageDialogGuard.attached)return{captures,diag:Object.assign(diag,{error:'debugger_not_attached'})};
  try{
    const info=await detailMainWorld(async(maxCount,waitMs)=>{
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const bad=e=>{let s='',n=e;for(let i=0;i<8&&n;i++,n=n.parentElement)s+=' '+String(n.className||'')+' '+String(n.id||'')+' '+String(n.getAttribute?.('aria-label')||'')+' '+String(n.innerText||'').slice(0,120);return /(recommend|related|similar|recent|ranking|best[-_ ]?item|other[-_ ]?product|banner|advert|coupon|review|footer|header|nav|연관|추천상품|함께본|최근본|광고|배너|리뷰|푸터|헤더)/i.test(s)};
      for(const b of [...document.querySelectorAll('button,a,[role="button"]')]){const t=(b.innerText||'').replace(/\s+/g,' ');if(/상품\s*(상세|정보).*더보기|상세.*더보기|펼쳐보기/.test(t)){try{b.click();await sleep(350)}catch(_){}}}
      const docH=Math.max(document.documentElement.scrollHeight||0,document.body?.scrollHeight||0);
      for(let y=0;y<Math.min(docH,14000);y+=Math.max(650,innerHeight*.75)){try{scrollTo({top:y,behavior:'instant'});await sleep(Math.max(300,Number(waitMs||900)*.45))}catch(_){}}
      const arr=[],seen=new Set();
      for(const im of [...document.querySelectorAll('main img,article img,[class*="product"] img,[class*="detail"] img,[class*="description"] img,img')]){
        if(seen.has(im)||bad(im))continue;seen.add(im);
        try{const r=im.getBoundingClientRect(),w=Math.max(r.width,Number(im.naturalWidth||0)),h=Math.max(r.height,Number(im.naturalHeight||0));if(w<260||h<260)continue;const py=r.top+scrollY,px=r.left+scrollX;if(py<0||px<0)continue;const ratio=w/Math.max(1,h);if(ratio>6.5)continue;const area=Math.min(w,1800)*Math.min(h,12000);const alt=(im.alt||'')+' '+String(im.getAttribute('title')||'');arr.push({x:px,y:py,width:r.width||Math.min(w,1600),height:r.height||Math.min(h,12000),src:im.currentSrc||im.src||'',alt,score:area+(alt?1e7:0)});}catch(_){}}
      arr.sort((a,b)=>b.score-a.score);return arr.slice(0,Math.max(4,Number(maxCount||8)*2));
    },[Number(currentTask?.screen_crop_max_candidates||8),Number(currentTask?.screen_crop_detail_wait_ms||950)]);
    const rows=Array.isArray(info)?info:[];diag.candidates=rows.length;
    for(const r of rows){
      if(captures.length>=Math.max(3,Number(currentTask?.screen_crop_max_candidates||8)))break;
      if(Number(r.height||0)>1900){
        const segH=1400,fullH=Number(r.height||0);
        for(const frac of [0,.5,.88]){if(captures.length>=Math.max(3,Number(currentTask?.screen_crop_max_candidates||8)))break;const off=Math.max(0,(fullH-segH)*frac);const c=await detailClipCapture({x:r.x,y:Number(r.y||0)+off,width:r.width,height:Math.min(segH,fullH-off)},'타마켓_긴상세_화면크롭',captures.length+1,{role:'other_market_long_detail_segment',segment_fraction:frac,src:r.src||''});if(c){captures.push(c);diag.segments++;}}
      }else{const c=await detailClipCapture(r,'타마켓_상품이미지_화면크롭',captures.length+1,{role:'other_market_rendered_image',src:r.src||'',alt:r.alt||''});if(c)captures.push(c)}
    }
  }catch(e){diag.errors.push(String(e))}
  return{captures,diag};
}

async function cdpVisualDiff(before,after,box,viewport){if(!before||!after||!box)return{ok:false};try{return await post('/api/toss_visual_state_diff',{before,after,region:{x:box.x,y:box.y,width:box.width,height:box.height},viewport});}catch(e){return{ok:false,error:String(e)};}}
async function cdpClickBox(box){if(!box)return false;for(const type of ['mouseMoved','mousePressed','mouseReleased'])await cdp('Input.dispatchMouseEvent',{type,x:box.cx,y:box.cy,button:'left',clickCount:1});return true;}
async function cdpFindAXExact(aliases,{leftMenu=false,preferCheckbox=false}={}){
  const wanted=new Set((aliases||[]).filter(Boolean).map(tossKey)),nodes=await cdpAX(),cand=[];
  for(const n of nodes){const name=axName(n),k=tossKey(name);if(!wanted.has(k)||!n.backendDOMNodeId)continue;const role=axRole(n);let target=n;
    if(['statictext','inlinetextbox','generic'].includes(role)&&n.parentId){const maps=axMaps(nodes);let p=n;for(let i=0;i<4&&p?.parentId;i++){p=maps.by.get(String(p.parentId));if(!p)break;if(['checkbox','button','link','menuitem','option','switch'].includes(axRole(p))){target=p;break;}}}
    const box=await axNodeBox(target)||await axNodeBox(n);if(!box)continue;let score=0;const tr=axRole(target);if(preferCheckbox&&['checkbox','switch'].includes(tr))score+=200;if(['button','link','menuitem'].includes(tr))score+=80;if(leftMenu){score+=Math.max(0,450-box.x);}else{score+=box.x>220?80:0;}score+=Math.max(0,80-Math.min(80,box.height));cand.push({node:target,labelNode:n,box,score,role:tr,name});
  }
  cand.sort((a,b)=>b.score-a.score);return{nodes,candidate:cand[0]||null,candidates:cand.slice(0,8)};
}
async function cdpTossProductLookupReady(){const nodes=await cdpAX();const names=nodes.map(axName);const cats=['가전/디지털','뷰티','생활용품','식품','주방용품','패션의류잡화'];const catCount=cats.filter(c=>names.some(n=>tossKey(n)===tossKey(c))).length;const heading=nodes.some(n=>/^상품\s*조회$/.test(axName(n))&&['heading','main','generic'].includes(axRole(n)));const textbox=nodes.some(n=>axRole(n)==='textbox'&&/상품|검색/.test(axName(n)));return{ready:catCount>=2||heading||textbox,catCount,heading,textbox,nodes};}
async function cdpTossOpenProductLookup(){
  let categoryToggleClicked=false;
  for(let attempt=0;attempt<5;attempt++){
    const ready=await cdpTossProductLookupReady();
    if(ready.ready&&ready.catCount>=1)return{ok:true,already:attempt===0,catCount:ready.catCount,category_toggle_clicked:categoryToggleClicked};
    // On some Sharelink builds the Product Lookup page is already open but the
    // category filter is collapsed. Expand that panel instead of clicking the
    // left menu again.
    if(ready.ready&&ready.catCount===0&&!categoryToggleClicked){
      const cg=await cdpFindAXExact(['카테고리','카테고리 필터','카테고리 선택'],{});
      if(cg.candidate&&['button','link','menuitem','generic','statictext'].includes(cg.candidate.role)){await cdpClickBox(cg.candidate.box);categoryToggleClicked=true;await new Promise(r=>setTimeout(r,800));continue;}
    }
    const f=await cdpFindAXExact(['상품 조회','상품조회'],{leftMenu:true});if(!f.candidate)return{ok:false,error:'CDP 접근성 트리에서 상품 조회 메뉴를 찾지 못했습니다.',diag:{catCount:ready.catCount,ready:ready.ready}};
    await cdpClickBox(f.candidate.box);await new Promise(r=>setTimeout(r,1000));
  }
  const r=await cdpTossProductLookupReady();return (r.ready&&r.catCount>=1)?{ok:true,catCount:r.catCount,category_toggle_clicked:categoryToggleClicked}:{ok:false,error:'상품 조회 클릭 후 카테고리 컨트롤이 확인되지 않았습니다.',diag:r};
}
async function cdpCategoryState(aliases){const f=await cdpFindAXExact(aliases,{preferCheckbox:true});if(!f.candidate)return{found:false,checked:null,candidate:null,candidates:f.candidates};return{found:true,checked:axChecked(f.candidate.node),candidate:f.candidate,candidates:f.candidates};}
async function cdpSetCategory(aliases,desired){
  let st=await cdpCategoryState(aliases);if(!st.found)return{ok:false,error:'CDP 접근성 트리에서 카테고리 컨트롤을 찾지 못했습니다.',state:st};
  if(st.checked===desired)return{ok:true,changed:false,proof:'ax_checked',state:st};
  const viewport=await cdpViewport(),before=await cdpShot(),box=st.candidate.box;
  await cdpClickBox(box);await new Promise(r=>setTimeout(r,850));
  const after=await cdpShot();st=await cdpCategoryState(aliases);const diff=await cdpVisualDiff(before,after,box,viewport);
  const semantic=st.found&&st.checked===desired;const visual=!!diff?.changed;
  if(semantic||visual)return{ok:true,changed:true,proof:semantic?'ax_checked':'visual_region_changed',state:st,diff,box};
  return{ok:false,error:`카테고리 ${desired?'체크':'해제'} 클릭 후 실제 상태 변화가 확인되지 않았습니다.`,state:st,diff,box};
}
function cdpDedupCards(arr,limit=60){const map=new Map();for(const c of arr||[]){let name=axCleanName(c?.name||'');if(axNoise(name))continue;const k=tossKey(name);if(!k)continue;if(!map.has(k))map.set(k,Object.assign({},c,{name}));}return[...map.values()].slice(0,limit);}
async function cdpTossScrollProductArea(){
  try{
    const r=await cdp('Runtime.evaluate',{expression:`(()=>{const vis=e=>{try{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>80&&r.height>80&&s.display!=='none'&&s.visibility!=='hidden'}catch(e){return false}};const a=[document.scrollingElement,document.documentElement,document.body,...document.querySelectorAll('main,section,div,[role=main]')].filter(Boolean);let best=null,score=-1;for(const e of a){try{if(!vis(e)&&![document.scrollingElement,document.documentElement,document.body].includes(e))continue;const sh=Number(e.scrollHeight||0),ch=Number(e.clientHeight||0);if(sh<=ch+80)continue;const b=e.getBoundingClientRect?e.getBoundingClientRect():{left:0,width:innerWidth,height:innerHeight};if(b.right<250)continue;const sc=(sh-ch)+(b.left>200?600:0)+Math.min(800,b.width||0);if(sc>score){score=sc;best=e}}catch(_){}}if(!best)return{moved:false,error:'scroll container not found'};const before=Number(best.scrollTop||0),step=Math.max(420,Math.floor((best.clientHeight||innerHeight)*0.78)),max=Math.max(0,Number(best.scrollHeight||0)-Number(best.clientHeight||0));best.scrollTop=Math.min(max,before+step);best.dispatchEvent(new Event('scroll',{bubbles:true}));return{moved:Number(best.scrollTop||0)>before+2,before,after:Number(best.scrollTop||0),max,tag:best.tagName||'',className:String(best.className||'').slice(0,120)}})()`,returnByValue:true});
    return r?.result?.value||{moved:false};
  }catch(e){return{moved:false,error:String(e)}}
}
async function cdpTossCollectProducts(limit=30){
  const all=[],rounds=[];let stale=0,last=0;
  for(let round=0;round<18&&cdpDedupCards(all,limit*2).length<limit;round++){
    const nodes=await cdpAX(),cards=parseTossAXProducts(nodes,limit*3);all.push(...cards);const unique=cdpDedupCards(all,limit*2);rounds.push({round,ax_nodes:nodes.length,found:cards.length,total:unique.length});
    if(unique.length>=limit)break;
    if(unique.length===last)stale++;else stale=0;last=unique.length;
    const mv=await cdpTossScrollProductArea();rounds[round].scroll=mv;
    await new Promise(r=>setTimeout(r,850));
    if(stale>=3){
      const more=await cdpFindAXExact(['더보기','더 보기','다음','다음 페이지'],{});if(more.candidate){await cdpClickBox(more.candidate.box);await new Promise(r=>setTimeout(r,900));stale=0;}
    }
  }
  return{cards:cdpDedupCards(all,limit).slice(0,limit),diag:{rounds,method:'chrome_cdp_accessibility',total_unique:cdpDedupCards(all,999).length}};
}
async function runTossCdpFixedTask(){
  if(!running||!currentTask||currentTask.site!=='토스쇼핑'||currentTask.mode!=='fixed_category_collect')return;
  stage='collect';const need=Number(currentTask.limit||30),siteCat=currentTask.site_category_label||currentTask.blog_category||currentTask.query||'',aliases=[siteCat,...(currentTask.category_aliases||[])];
  let result={status:'error',site:'토스쇼핑',cards:[],category_confirmed:false,toss_product_lookup_confirmed:false,toss_single_checkbox_confirmed:false,toss_uncheck_after_collect:false,toss_checked_before_collect:[],toss_checked_after_collect:[siteCat],debug:{engine:'cdp_accessibility_v7_27'}};
  try{
    await cdpAttach();await cdp('Page.enable',{});await cdp('DOM.enable',{});await cdp('Runtime.enable',{});await cdp('Accessibility.enable',{});
    const open=await cdpTossOpenProductLookup();result.debug.open=open;if(!open.ok)throw new Error(open.error||'상품 조회 진입 실패');result.toss_product_lookup_confirmed=true;
    // Prefer the site's own reset control when present. This removes stale
    // server/React filter state before the exact target is selected.
    let reset=null;try{reset=await cdpFindAXExact(['초기화','필터 초기화','전체 해제','선택 초기화'],{});if(reset.candidate){await cdpClickBox(reset.candidate.box);await new Promise(r=>setTimeout(r,650));result.debug.filter_reset={clicked:true,name:reset.candidate.name,role:reset.candidate.role};}}catch(_e){}
    // Clear any other explicitly checked known Toss category before target selection.
    const allDefs=[['가전/디지털'],['뷰티'],['생활용품'],['식품'],['주방용품'],['패션의류잡화']];
    const clears=[];for(const a of allDefs){if(tossKey(a[0])===tossKey(siteCat))continue;const st=await cdpCategoryState(a);if(st.found&&st.checked===true){const rr=await cdpSetCategory(a,false);clears.push({category:a[0],result:rr});if(!rr.ok)throw new Error(`${a[0]} 기존 체크 해제 실패`);}}
    result.debug.preclear=clears;
    const sel=await cdpSetCategory(aliases,true);result.debug.select=sel;if(!sel.ok)throw new Error(sel.error||`${siteCat} 체크 실패`);result.category_confirmed=true;result.toss_single_checkbox_confirmed=true;result.toss_checked_before_collect=[siteCat];
    await new Promise(r=>setTimeout(r,900));
    let col=await cdpTossCollectProducts(need);result.debug.cdp_collect=col.diag;let cards=col.cards||[];
    // Final fallback only: legacy visual OCR can supplement AX results, but never
    // controls checkbox state and never decides category success.
    if(cards.length<need){const visual=await mainWorldTossVisualOCRCollect(need,cards);result.debug.ocr_fallback=visual.diag||{};cards=mergeTossCards(cards,visual.cards||[],need);}
    // One last deep DOM supplement if accessibility + OCR are still short.
    if(cards.length<need){const deep=await mainWorldTossDeepExtract(need);result.debug.deep_fallback=deep.diag||{};cards=mergeTossCards(cards,deep.cards||[],need);}
    cards=cdpDedupCards(cards,need);result.cards=cards;
    if(cards.length<need)throw new Error(`토스 ${siteCat} 실제 상품 ${need}개 중 ${cards.length}개만 확보했습니다. 카테고리 체크는 수집 실패 시 임의로 반복 토글하지 않습니다.`);
    const off=await cdpSetCategory(aliases,false);result.debug.uncheck=off;if(!off.ok)throw new Error(off.error||`${siteCat} 체크 해제 실패`);
    result.status='ok';result.error='';result.toss_uncheck_after_collect=true;result.toss_checked_after_collect=[];result.clicked_label=siteCat;result.url=(await cdpViewport()).url||'';
  }catch(e){result.error=String(e?.message||e);try{const vp=await cdpViewport();result.url=vp.url||'';}catch(_e){} }
  finally{await cdpDetach();}
  await finishWithDiagnostic(result);
}



// v7.32 Toss price-anchor primary collector.
// The category-entry/check route stays unchanged.  After the filter is ON,
// the visible selling-price text is the anchor and the nearest readable text
// directly above it is treated as the product name.  This mirrors what the
// user sees on Sharelink and avoids CSS/React/API schema dependencies.
async function installTossPriceAnchor(reset=false){
  // v7.33: inject into every accessible Toss frame.  The real Sharelink product
  // grid can be mounted by a micro-frontend/iframe even though the category UI
  // lives in the top document.  v7.32 only scanned the top frame.
  try{
    let rows=[];
    try{rows=await chrome.scripting.executeScript({target:{tabId:workTabId,allFrames:true},world:'MAIN',files:['toss_price_anchor.js']});}
    catch(e){rows=await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',files:['toss_price_anchor.js']});}
    if(reset){
      try{await chrome.scripting.executeScript({target:{tabId:workTabId,allFrames:true},world:'MAIN',func:()=>{try{return window.__NVB_TOSS_PRICE_ANCHOR?.reset?.()||false}catch(e){return false}}});}
      catch(e){await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',func:()=>{try{return window.__NVB_TOSS_PRICE_ANCHOR?.reset?.()||false}catch(e){return false}}});}
    }
    return{ok:true,frames:(rows||[]).map(x=>x.frameId)};
  }catch(e){return{ok:false,error:String(e)}}
}
async function tossPriceAnchorSnapshot(limit=120){
  try{
    let rows=[];
    try{rows=await chrome.scripting.executeScript({target:{tabId:workTabId,allFrames:true},world:'MAIN',args:[limit],func:(lim)=>{try{return window.__NVB_TOSS_PRICE_ANCHOR?.scan?.(lim)||{cards:[],diag:{missing:true}}}catch(e){return{cards:[],diag:{error:String(e)}}}}});}
    catch(e){rows=await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',args:[limit],func:(lim)=>{try{return window.__NVB_TOSS_PRICE_ANCHOR?.scan?.(lim)||{cards:[],diag:{missing:true}}}catch(e){return{cards:[],diag:{error:String(e)}}}}});}
    const map=new Map(),frames=[];let bestFrameId=null,bestScore=-1;
    for(const row of rows||[]){
      const r=row?.result||{cards:[],diag:{missing:true}},diag=Object.assign({frameId:row?.frameId,documentId:row?.documentId||''},r.diag||{});
      frames.push(diag);
      const score=Number(diag.matched||0)*100+Number(diag.priceAnchors||0)*10+Number(diag.fragments||0)/1000;
      if(score>bestScore){bestScore=score;bestFrameId=row?.frameId;}
      for(const c of r.cards||[]){const name=String(c?.name||'').replace(/\s+/g,' ').trim(),k=tossNameKey(name);if(!k)continue;const rec=Object.assign({},c,{name,frameId:row?.frameId});const old=map.get(k);const ns=Number(rec.anchor?.score||0)+(rec.price?100:0)+(rec.url?20:0),os=Number(old?.anchor?.score||0)+(old?.price?100:0)+(old?.url?20:0);if(!old||ns>os)map.set(k,rec);}
    }
    return{cards:[...map.values()].slice(0,Math.max(1,Number(limit||120))),bestFrameId,diag:{engine:'toss_card_local_multiframe_v7_33',frame_count:(rows||[]).length,bestFrameId,merged_count:map.size,frames}};
  }catch(e){return{cards:[],bestFrameId:null,diag:{error:String(e)}}}
}
async function tossPriceAnchorAdvance(round=0,frameId=null){
  const run=async(target)=>{
    const rows=await chrome.scripting.executeScript({target,world:'MAIN',args:[round],func:(r)=>{try{return window.__NVB_TOSS_PRICE_ANCHOR?.advance?.(r)||{type:'none',round:r}}catch(e){return{type:'error',error:String(e),round:r}}}});
    let best=null,bestDelta=-1;
    for(const row of rows||[]){const x=Object.assign({frameId:row?.frameId},row?.result||{}),delta=Math.max(0,Number(x.after||0)-Number(x.before||0));if(delta>bestDelta){best=x;bestDelta=delta;}}
    return best||{type:'none',round};
  };
  try{
    if(frameId!==null&&frameId!==undefined){try{return await run({tabId:workTabId,frameIds:[frameId]});}catch(e){}}
    try{return await run({tabId:workTabId,allFrames:true});}catch(e){return await run({tabId:workTabId});}
  }catch(e){return{type:'error',error:String(e),round}}
}
function tossNameKey(name){return String(name||'').toLowerCase().replace(/\s+/g,' ').trim().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');}
function tossMergeByName(map,cards,source='toss_card_local'){
  for(const c of cards||[]){
    const name=String(c?.name||'').replace(/\s+/g,' ').trim();
    if(!name||name.length<3||name.length>260||!/[A-Za-z가-힣]/.test(name))continue;
    if(/^(상품\s*조회|카테고리|검색|전체|홈|링크|베스트\s*랭킹|성과|설정|더보기)$/i.test(name))continue;
    if(/수익|수수료|정산|무료배송|배송비|쿠폰|리뷰|평점|30일\s*최저가|링크\s*발급|베스트판매자/i.test(name))continue;
    const k=tossNameKey(name);if(!k)continue;
    const rec={name,price:Number(c.price||0)||null,text:c.text||name,url:c.url||'',image_url:c.image_url||'',source:c.source||source,anchor:c.anchor||null,frameId:c.frameId};
    const old=map.get(k),oldScore=(old?.price?100:0)+(old?.anchor?.score||0)+(old?.url?20:0),newScore=(rec.price?100:0)+(rec.anchor?.score||0)+(rec.url?20:0);
    if(!old||newScore>oldScore)map.set(k,rec);
  }
}
async function collectTossPriceAnchorPrimary(limit=30){
  const need=Math.max(1,Number(limit||30)),map=new Map(),rounds=[];
  const arm=await installTossPriceAnchor(true);
  if(!arm.ok)return{ok:false,cards:[],diag:{engine:'toss_card_local_multiframe_v7_33',arm,error:'card-local multi-frame injection failed'}};
  await new Promise(r=>setTimeout(r,1300));
  let noGrowth=0,last=0,bestFrameId=null;
  for(let round=0;round<60;round++){
    const snap=await tossPriceAnchorSnapshot(Math.max(need*5,150));bestFrameId=snap.bestFrameId??bestFrameId;
    tossMergeByName(map,snap.cards||[],'toss_card_local');
    const rec={round,total:map.size,visible_cards:(snap.cards||[]).length,bestFrameId:snap.bestFrameId,diag:snap.diag||{}};rounds.push(rec);
    if(map.size>=need)return{ok:true,cards:[...map.values()].slice(0,need),diag:{engine:'toss_card_local_multiframe_v7_33',arm,rounds,final_count:map.size,bestFrameId}};
    if(map.size===last)noGrowth++;else noGrowth=0;last=map.size;
    const mv=await tossPriceAnchorAdvance(round,bestFrameId);rec.scroll=mv;
    await new Promise(r=>setTimeout(r,round<10?900:700));
    if(noGrowth>=16&&round>=22&&((mv?.max??1)<=((mv?.after??0)+3)))break;
  }
  const snap=await tossPriceAnchorSnapshot(Math.max(need*6,180));tossMergeByName(map,snap.cards||[],'toss_card_local');
  return{ok:map.size>=need,cards:[...map.values()].slice(0,need),diag:{engine:'toss_card_local_multiframe_v7_33',arm,rounds,final_count:map.size,bestFrameId:snap.bestFrameId??bestFrameId,final_diag:snap.diag||{}}};
}

// v7.30 Toss rendered-text + data-feed primary collector.
async function installTossDataFeedTap(reset=false){
  try{
    await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',files:['toss_main_tap.js']});
    if(reset){await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',func:()=>{try{return window.__NVB_TOSS_FEED?.reset?.()||false}catch(e){return false}}});}
    return{ok:true};
  }catch(e){return{ok:false,error:String(e)}}
}
async function tossDataFeedSnapshot(limit=150){
  try{
    const rows=await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',args:[limit],func:(lim)=>{try{return window.__NVB_TOSS_FEED?.snapshot?.(lim)||{cards:[],stats:{},urls:[],missing:true}}catch(e){return{cards:[],stats:{},urls:[],error:String(e)}}}});
    return rows?.[0]?.result||{cards:[],stats:{},urls:[],missing:true};
  }catch(e){return{cards:[],stats:{},urls:[],error:String(e)}}
}
async function tossDataFeedScroll(round=0){
  try{
    const rows=await chrome.scripting.executeScript({target:{tabId:workTabId},world:'MAIN',args:[round],func:(round)=>{
      const visible=e=>{try{const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>120&&r.height>100&&st.display!=='none'&&st.visibility!=='hidden'&&Number(st.opacity||1)>0.02}catch(_){return false}};
      const priceCount=e=>{try{return ((e.innerText||e.textContent||'').match(/\d[\d,]*\s*원/g)||[]).length}catch(_){return 0}};
      const cand=[];
      const nodes=[...document.querySelectorAll('main,section,div,ul,ol,table,tbody,[role="main"],[role="list"],[role="grid"]')];
      for(const e of nodes){
        if(!visible(e))continue;
        try{if(e.closest('aside,nav,[role="navigation"]'))continue}catch(_){ }
        const delta=(e.scrollHeight||0)-(e.clientHeight||0);if(delta<60)continue;
        const r=e.getBoundingClientRect();if(r.right<260||r.bottom<80)continue;
        const st=getComputedStyle(e),pc=Math.min(80,priceCount(e));
        const overflowBonus=/(auto|scroll)/.test((st.overflowY||'')+' '+(st.overflow||''))?25000:0;
        const locationBonus=r.left>180?5000:0;
        // Product-list candidates dominate because they visibly contain prices.
        const score=pc*100000+overflowBonus+locationBonus+Math.min(20000,delta)+Math.min(10000,r.width*r.height/3000);
        cand.push({e,score,pc,delta,tag:e.tagName});
      }
      cand.sort((a,b)=>b.score-a.score);
      for(const x of cand.slice(0,12)){
        const before=Number(x.e.scrollTop||0),max=Math.max(0,x.e.scrollHeight-x.e.clientHeight);
        if(max<=before+2)continue;
        const step=Math.max(320,Math.floor(x.e.clientHeight*0.78));
        const target=Math.min(max,before+step);
        try{x.e.scrollTop=target;x.e.dispatchEvent(new Event('scroll',{bubbles:true}));}catch(_){continue}
        const after=Number(x.e.scrollTop||0);
        if(after>before+1)return{type:'element',before,after,max,price_count:x.pc,tag:x.tag,round,candidates:cand.length};
      }
      // Some list components load another page only through a visible More button.
      if(round>=2){
        const more=[...document.querySelectorAll('button,a,[role="button"]')].find(e=>{try{const t=(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim();const r=e.getBoundingClientRect(),st=getComputedStyle(e);return /^(더보기|더\s*보기|다음|다음\s*페이지)$/i.test(t)&&r.width>10&&r.height>10&&st.display!=='none'&&st.visibility!=='hidden'&&!e.disabled}catch(_){return false}});
        if(more){try{more.click();return{type:'more_button',text:(more.innerText||more.textContent||'').trim(),round,candidates:cand.length}}catch(_){ }}
      }
      const se=document.scrollingElement||document.documentElement||document.body;
      const before=Number(se.scrollTop||window.scrollY||0),max=Math.max(0,se.scrollHeight-se.clientHeight);
      const target=Math.min(max,before+Math.max(450,Math.floor(innerHeight*0.78)));
      try{se.scrollTop=target;window.scrollTo(0,target);se.dispatchEvent(new Event('scroll',{bubbles:true}))}catch(_){ }
      const after=Number(se.scrollTop||window.scrollY||0);
      return{type:'window',before,after,max,round,candidates:cand.length};
    }});
    return rows?.[0]?.result||{type:'none',round};
  }catch(e){return{type:'error',error:String(e),round}}
}
function tossFeedMerge(map,cards){
  for(const c of cards||[]){const name=String(c?.name||'').replace(/\s+/g,' ').trim();if(!name||name.length<3||name.length>220)continue;if(!/[A-Za-z가-힣]/.test(name))continue;if(/^(상품\s*조회|카테고리|검색|전체|홈|링크|베스트\s*랭킹|성과|설정|더보기)$/i.test(name))continue;const k=name.toLowerCase().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');if(!k)continue;const old=map.get(k);if(!old||(!old.price&&c.price))map.set(k,{name,price:Number(c.price||0)||null,text:c.text||name,url:c.url||'',image_url:c.image_url||'',source:c.source||'toss_data_feed'});}
}
async function collectTossDataFeedPrimary(limit=30){
  const need=Math.max(1,Number(limit||30)),map=new Map(),rounds=[];let noGrowth=0,last=0;
  const arm=await installTossDataFeedTap(false);
  const netArm=await tossNetAttach(false);
  if(!arm.ok&&!netArm.ok)return{ok:false,cards:[],diag:{arm,netArm,error:'page tap and Chrome Network capture both unavailable'}};
  for(let round=0;round<70;round++){
    const snap=await tossDataFeedSnapshot(need*6);tossFeedMerge(map,snap.cards||[]);
    const net=tossNetSnapshot(need*8);tossFeedMerge(map,net.cards||[]);
    const rec={round,total:map.size,feed_cards:(snap.cards||[]).length,network_cards:(net.cards||[]).length,stats:snap.stats||{},network_stats:net.capture_stats||{},network_parser_stats:net.stats||{},source_counts:snap.sourceCounts||{},network_sources:net.sourceCounts||{},urls:[...(snap.urls||[]).slice(-15),...(net.urls||[]).slice(-15)],samples:(snap.samples||[]).slice(0,30)};rounds.push(rec);
    if(map.size>=need)return{ok:true,cards:[...map.values()].slice(0,need),diag:{engine:'toss_chrome_network_plus_rendered_v7_31',rounds,final_stats:snap.stats||{},network:net,last_urls:rec.urls}};
    if(map.size===last)noGrowth++;else noGrowth=0;last=map.size;
    const mv=await tossDataFeedScroll(round);rec.scroll=mv;
    await new Promise(r=>setTimeout(r,round<10?1100:850));
    // Do not abort early while the real list is still moving or Network bodies are arriving.
    if(noGrowth>=30&&round>=32)break;
  }
  const snap=await tossDataFeedSnapshot(need*8);tossFeedMerge(map,snap.cards||[]);
  const net=tossNetSnapshot(need*10);tossFeedMerge(map,net.cards||[]);
  return{ok:map.size>=need,cards:[...map.values()].slice(0,need),diag:{engine:'toss_chrome_network_plus_rendered_v7_31',rounds,final_stats:snap.stats||{},network:net,source_counts:snap.sourceCounts||{},last_urls:[...(snap.urls||[]).slice(-30),...(net.urls||[]).slice(-30)],samples:(snap.samples||[]).slice(0,100),final_count:map.size}};
}


// v7.34 Toss DIRECT TEXT primary collector.
// The real Sharelink screen has a very stable visual/text order inside each
// product item: profit/discount -> product title line(s) -> selling price.
// Instead of guessing React card DOM, read document.body.innerText from EVERY
// accessible frame and use the selling-price line as the anchor. This survives
// hashed CSS classes, micro-frontends and virtualized rows.
function tossDirectNorm(x){return String(x||'').replace(/\s+/g,' ').trim();}
function tossDirectKey(x){return tossDirectNorm(x).toLowerCase().replace(/[·ㆍ]/g,'/').replace(/[^0-9a-z가-힣/]/g,'');}
function tossDirectSellPrice(line){
  const t=tossDirectNorm(line);if(!t||/수익|수수료|정산|예상\s*수익|확정\s*수익/i.test(t))return 0;
  const m=t.match(/(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원/);if(!m)return 0;
  const v=parseInt(m[1].replace(/,/g,''),10);return Number.isFinite(v)&&v>=100&&v<=100000000?v:0;
}
function tossDirectTitleLine(line){
  let t=tossDirectNorm(line);if(!t)return'';
  if(/수익|수수료|정산|확정\s*수익|예상\s*수익|링크\s*발급|베스트판매자|내일(?:도착|출발)|무료배송|배송비|쿠폰|적립|리뷰|평점|별점|30일\s*최저가|하루특가|특가|할인율|판매가|정가|할인가/i.test(t))return'';
  if(/^(?:상품\s*조회|카테고리|검색|전체|홈|링크|베스트\s*랭킹|성과|설정|가이드|의견\s*남기기|프로모션\s*상품|발굴순)$/i.test(t))return'';
  if(/^\d{1,3}\s*%\s*(?:특가|할인)?$/i.test(t)||/^★?\s*\d(?:\.\d)?\s*\(?[\d,]*\)?$/.test(t)||/^\d+[\d,]*\s*원$/.test(t))return'';
  if(t.length<2||t.length>260||!/[A-Za-z가-힣]/.test(t))return'';
  return t;
}
function parseTossDirectText(text,limit=200){
  const lines=String(text||'').split(/\r?\n+/).map(tossDirectNorm).filter(Boolean),map=new Map();
  for(let i=0;i<lines.length;i++){
    const price=tossDirectSellPrice(lines[i]);if(!price)continue;
    const picked=[];
    for(let j=i-1;j>=Math.max(0,i-7)&&picked.length<3;j--){
      const raw=lines[j];
      if(tossDirectSellPrice(raw))break;
      // These are reliable card boundaries immediately above the title.
      if(/(?:개당\s*)?\d[\d,]*\s*원\s*수익|\d{1,3}\s*%\s*(?:특가|할인)?|역대급특가|오늘만\s*특가/i.test(raw)){if(picked.length)break;continue;}
      const title=tossDirectTitleLine(raw);
      if(!title){if(picked.length)break;continue;}
      picked.unshift(title);
      // Most Sharelink titles wrap to one or two lines. Three is retained only
      // for unusually long titles/options.
    }
    if(!picked.length)continue;
    let name=tossDirectNorm(picked.join(' '));
    if(name.length>240)name=tossDirectNorm(picked.slice(-2).join(' '));
    const k=tossDirectKey(name);if(!k)continue;
    const rec={name,price,text:`${name} ${price.toLocaleString()}원`,url:'',image_url:'',source:'toss_direct_text_v7_34'};
    if(!map.has(k))map.set(k,rec);
    if(map.size>=Math.max(1,Number(limit||200)))break;
  }
  return [...map.values()];
}
async function tossDirectTextSnapshot(limit=180){
  try{
    let rows=[];
    try{rows=await chrome.scripting.executeScript({target:{tabId:workTabId,allFrames:true},func:()=>({text:String(document.body?.innerText||'').slice(0,700000),url:location.href,title:document.title||''})});}
    catch(e){rows=await chrome.scripting.executeScript({target:{tabId:workTabId},func:()=>({text:String(document.body?.innerText||'').slice(0,700000),url:location.href,title:document.title||''})});}
    const merged=new Map(),frames=[];let bestFrameId=null,bestCount=-1;
    for(const row of rows||[]){
      const val=row?.result||{},cards=parseTossDirectText(val.text||'',Math.max(Number(limit||180)*3,180));
      frames.push({frameId:row?.frameId,url:val.url||'',title:val.title||'',body_chars:String(val.text||'').length,parsed:cards.length,samples:cards.slice(0,5).map(x=>x.name)});
      if(cards.length>bestCount){bestCount=cards.length;bestFrameId=row?.frameId;}
      for(const c of cards){const k=tossDirectKey(c.name);if(k&&!merged.has(k))merged.set(k,Object.assign({},c,{frameId:row?.frameId}));}
    }
    return{cards:[...merged.values()].slice(0,Math.max(1,Number(limit||180))),bestFrameId,diag:{engine:'toss_direct_body_text_allframes_v7_34',frame_count:(rows||[]).length,bestFrameId,merged_count:merged.size,frames}};
  }catch(e){return{cards:[],bestFrameId:null,diag:{engine:'toss_direct_body_text_allframes_v7_34',error:String(e)}};}
}
async function tossDirectTextAdvance(round=0,frameId=null){
  const run=async(target)=>{
    const rows=await chrome.scripting.executeScript({target,args:[round],func:(r)=>{
      const norm=s=>String(s||'').replace(/\s+/g,' ').trim();
      const countPrices=text=>String(text||'').split(/\n+/).reduce((n,line)=>{line=norm(line);if(!line||/수익|수수료|정산/.test(line))return n;return /(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d{4,9})\s*원/.test(line)?n+1:n},0);
      const vis=e=>{try{const b=e.getBoundingClientRect(),s=getComputedStyle(e);return b.width>120&&b.height>100&&b.bottom>0&&b.top<innerHeight&&s.display!=='none'&&s.visibility!=='hidden'}catch(_){return false}};
      const cand=[];const seen=new Set();
      for(const e of [document.scrollingElement,document.documentElement,document.body,...document.querySelectorAll('main,[role="main"],section,div,ul,ol,[role="grid"],[role="list"]')]){
        if(!e||seen.has(e))continue;seen.add(e);try{if(e.closest?.('aside,nav,[role="navigation"]'))continue;}catch(_){ }
        if(![document.scrollingElement,document.documentElement,document.body].includes(e)&&!vis(e))continue;
        const sh=Number(e.scrollHeight||0),ch=Number(e.clientHeight||0);if(sh<=ch+60)continue;
        let b={left:0,right:innerWidth,width:innerWidth,height:innerHeight};try{b=e.getBoundingClientRect()}catch(_){ }
        if(b.right<260)continue;let pc=0;try{pc=countPrices(e.innerText||e.textContent||'')}catch(_){ }
        const style=(()=>{try{return getComputedStyle(e)}catch(_){return{overflowY:''}}})();
        const score=pc*100000+(/auto|scroll|overlay/.test(style.overflowY||'')?20000:0)+(b.left>180?7000:0)+Math.min(30000,sh-ch)+Math.min(10000,(b.width||0)*(b.height||0)/2500);
        cand.push({e,score,pc,sh,ch,left:b.left||0});
      }
      cand.sort((a,b)=>b.score-a.score);
      for(const x of cand.slice(0,15)){
        const before=Number(x.e.scrollTop||0),max=Math.max(0,x.sh-x.ch);if(max<=before+2)continue;
        const step=Math.max(320,Math.floor((x.ch||innerHeight)*0.78)),to=Math.min(max,before+step);
        try{x.e.scrollTop=to;x.e.dispatchEvent(new Event('scroll',{bubbles:true}));x.e.dispatchEvent(new WheelEvent('wheel',{deltaY:step,bubbles:true,cancelable:true}));}catch(_){continue}
        const after=Number(x.e.scrollTop||0);if(after>before+2)return{type:'element',before,after,max,priceCount:x.pc,round:r,left:x.left};
      }
      const se=document.scrollingElement||document.documentElement||document.body,before=Number(se.scrollTop||scrollY||0),max=Math.max(0,Number(se.scrollHeight||0)-Number(se.clientHeight||0)),to=Math.min(max,before+Math.max(420,Math.floor(innerHeight*.78)));
      try{se.scrollTop=to;scrollTo(0,to);se.dispatchEvent(new Event('scroll',{bubbles:true}));}catch(_){ }
      return{type:'window',before,after:Number(se.scrollTop||scrollY||0),max,round:r,candidates:cand.slice(0,5).map(x=>({pc:x.pc,score:Math.round(x.score),left:Math.round(x.left)}))};
    }});
    return rows?.[0]?.result||{type:'none',round};
  };
  try{if(frameId!==null&&frameId!==undefined){try{return await run({tabId:workTabId,frameIds:[frameId]});}catch(_){ }}return await run({tabId:workTabId,allFrames:true});}
  catch(e){return{type:'error',error:String(e),round};}
}
async function collectTossDirectTextPrimary(limit=30){
  const need=Math.max(1,Number(limit||30)),map=new Map(),rounds=[];let bestFrameId=null,last=0,noGrowth=0;
  for(let round=0;round<70;round++){
    const snap=await tossDirectTextSnapshot(Math.max(need*6,180));bestFrameId=snap.bestFrameId??bestFrameId;
    tossMergeByName(map,snap.cards||[],'toss_direct_text');
    const rec={round,total:map.size,visible:(snap.cards||[]).length,bestFrameId:snap.bestFrameId,diag:snap.diag};rounds.push(rec);
    if(map.size>=need)return{ok:true,cards:[...map.values()].slice(0,need),diag:{engine:'toss_direct_body_text_allframes_v7_34',rounds,final_count:map.size,bestFrameId}};
    if(map.size===last)noGrowth++;else noGrowth=0;last=map.size;
    const mv=await tossDirectTextAdvance(round,bestFrameId);rec.scroll=mv;
    await new Promise(r=>setTimeout(r,round<10?900:700));
    if(noGrowth>=20&&round>=28&&((mv?.max??1)<=((mv?.after??0)+3)))break;
  }
  const snap=await tossDirectTextSnapshot(Math.max(need*8,240));tossMergeByName(map,snap.cards||[],'toss_direct_text');
  return{ok:map.size>=need,cards:[...map.values()].slice(0,need),diag:{engine:'toss_direct_body_text_allframes_v7_34',rounds,final_count:map.size,bestFrameId:snap.bestFrameId??bestFrameId,final_diag:snap.diag}};
}


// v7.35 detail-image collector: scan every accessible frame and every open Shadow DOM.
// This mirrors the user's Selenium multi-frame/Shadow-DOM collector, but runs inside
// the installed Chrome extension so the current logged-in browser session is reused.
async function mainWorldDetailImagesMultiFrame(limit=24,fast=false){
  const lim=Math.max(6,Number(limit||24));
  const func=async(lim,fast)=>{
    const out=[],seen=new Set(),roots=[];
    const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
    const reject=(u)=>/logo|sprite|avatar|icon|badge|tracking|pixel|favicon|banner|advert|loading|placeholder/i.test(String(u||''));
    const add=(url,w,h,score,kind,rect)=>{
      try{url=new URL(url,location.href).href;}catch(e){return;}
      if(!/^https?:/i.test(url)||reject(url)||seen.has(url))return;
      w=Number(w||0);h=Number(h||0);
      if((w&&w<120)||(h&&h<120))return;
      seen.add(url);out.push({url,width:w||null,height:h||null,score:Number(score||0),kind:kind||'img',rect:rect||null,frame_url:location.href});
    };
    const walk=(root,depth=0)=>{
      if(!root||depth>10)return;
      roots.push(root);
      let imgs=[];try{imgs=[...root.querySelectorAll('img')];}catch(e){}
      for(const img of imgs){
        const r=img.getBoundingClientRect?.()||{};
        const nw=Number(img.naturalWidth||0),nh=Number(img.naturalHeight||0),rw=Number(r.width||0),rh=Number(r.height||0);
        const url=img.currentSrc||img.src||'';if(!url)continue;
        let score=Math.max(nw*nh,rw*rh);
        let anc=img;let meta='';for(let i=0;anc&&i<5;i++,anc=anc.parentElement){meta+=' '+String(anc.className||'')+' '+String(anc.id||'');}
        if(/product|detail|gallery|thumb|viewer|photo|image/i.test(meta))score+=500000;
        if(/recommend|related|recent|banner|ad[s_-]?|logo/i.test(meta))score-=600000;
        add(url,nw||rw,nh||rh,score,'img',{x:r.x||0,y:r.y||0,width:rw,height:rh});
        const ss=String(img.getAttribute?.('srcset')||'').split(',').map(x=>x.trim().split(/\s+/)[0]).filter(Boolean);
        for(const su of ss)add(su,nw||rw,nh||rh,score-100,'srcset',null);
      }
      let els=[];try{els=[...root.querySelectorAll('*')];}catch(e){}
      for(const el of els){
        if(el.shadowRoot)walk(el.shadowRoot,depth+1);
        // Some commerce galleries render the product shot as a CSS background.
        try{
          const bg=getComputedStyle(el).backgroundImage||'';const m=bg.match(/url\(["']?([^"')]+)["']?\)/i);
          if(m){const r=el.getBoundingClientRect();if(r.width>=160&&r.height>=160)add(m[1],r.width,r.height,r.width*r.height+100000,'background',{x:r.x,y:r.y,width:r.width,height:r.height});}
        }catch(e){}
      }
    };
    const startY=window.scrollY;
    const scrollers=[];
    try{for(const el of document.querySelectorAll('div,section,main,article')){const st=getComputedStyle(el);if(/auto|scroll/.test(st.overflowY||'')&&el.scrollHeight>el.clientHeight+300&&el.clientHeight>220)scrollers.push(el);}}catch(e){}
    for(let round=0;round<(fast?1:5);round++){
      walk(document);
      if(fast||out.length>=lim*2)break;
      try{window.scrollBy(0,Math.max(500,innerHeight*.68));}catch(e){}
      for(const el of scrollers.slice(0,3)){try{el.scrollTop=Math.min(el.scrollHeight,el.scrollTop+Math.max(420,el.clientHeight*.65));}catch(e){}}
      const visible=[...document.querySelectorAll('img')].filter(im=>{try{const r=im.getBoundingClientRect();return r.width>=180&&r.height>=180&&r.bottom>-200&&r.top<innerHeight+200}catch(_){return false}}).slice(0,20);
      for(const im of visible){try{if(!im.src){const lazy=im.getAttribute('data-src')||im.getAttribute('data-original')||im.getAttribute('data-lazy-src');if(lazy)im.src=lazy}im.loading='eager'}catch(_){}}
      try{await Promise.race([Promise.allSettled(visible.map(im=>im.decode?im.decode():Promise.resolve())),sleep(1500)])}catch(_){}
      await sleep(520);
    }
    try{window.scrollTo(0,startY);}catch(e){}
    const body=(document.body?.innerText||'').replace(/\s+/g,' ').slice(0,10000);
    out.sort((a,b)=>b.score-a.score);
    return {images:out.slice(0,lim),page_text:body,page_title:document.title||'',frame_url:location.href,roots:roots.length};
  };
  try{
    const rs=await chrome.scripting.executeScript({target:{tabId:workTabId,allFrames:true},world:'MAIN',func,args:[Math.max(lim*3,36),!!fast]});
    const map=new Map(),texts=[],frames=[];
    for(const x of rs||[]){
      const r=x?.result||{};frames.push({frameId:x.frameId,url:r.frame_url||'',count:(r.images||[]).length,roots:r.roots||0});
      if(r.page_text)texts.push(r.page_text);
      for(const im of r.images||[]){const old=map.get(im.url);if(!old||Number(old.score||0)<Number(im.score||0))map.set(im.url,im);}
    }
    const images=[...map.values()].sort((a,b)=>Number(b.score||0)-Number(a.score||0)).slice(0,lim);
    return {ok:true,images,page_text:texts.join(' ').slice(0,18000),frames};
  }catch(e){return {ok:false,images:[],page_text:'',frames:[],error:String(e)};}
}


// v8.08.36: Google is used only as a SOURCE-PAGE DISCOVERY fallback.
// We do not save Google preview thumbnails. The original result page is opened
// separately and its Product/OG/gallery image URLs are collected through CDP.
async function collectGoogleProductSourcePages(limit=12){
  if(!workTabId)return{status:'error',sources:[],error:'work tab missing'};
  try{
    const surface=String(currentTask?.search_surface||'web');
    const rows=await chrome.scripting.executeScript({
      target:{tabId:workTabId},world:'MAIN',args:[Math.max(6,Number(limit||12)),surface],
      func:(limit,surface)=>{
        const norm=s=>String(s||'').replace(/\s+/g,' ').trim();
        const decode=s=>{try{return decodeURIComponent(String(s||'').replace(/\+/g,' '))}catch(_){return String(s||'')}};
        const jsun=s=>String(s||'').replace(/\\u003d/gi,'=').replace(/\\u0026/gi,'&').replace(/\\u002f/gi,'/').replace(/\\\//g,'/').replace(/&amp;/gi,'&');
        const badHost=h=>/(^|\.)(google\.|youtube\.com$|youtu\.be$|pinterest\.|instagram\.|facebook\.|tiktok\.|x\.com$|twitter\.|blog\.naver\.com$|cafe\.naver\.com$|brunch\.co\.kr$|reddit\.)/i.test(h||'');
        const badText=t=>/(블로그|카페|후기\s*모음|이미지\s*검색|유튜브|인스타|핀터레스트|검색결과)/i.test(t||'');
        const badImage=u=>/(gstatic\.com|googleusercontent\.com\/proxy|encrypted-tbn|favicon|logo|sprite|icon|avatar|badge|tracking|pixel)/i.test(u||'');
        const out=[],seen=new Set();
        const normalizeUrl=(raw,base=location.href)=>{try{const u=new URL(jsun(raw),base);return /^https?:$/i.test(u.protocol)?u.href:''}catch(_){return''}};
        const parseGoogleHref=(href)=>{
          try{
            const u=new URL(String(href||''),location.href);let source='',image='';
            const isGoogle=/(^|\.)google\./i.test(u.hostname);
            if(isGoogle){
              const ref=u.searchParams.get('imgrefurl')||u.searchParams.get('url')||u.searchParams.get('q')||'';
              const img=u.searchParams.get('imgurl')||'';
              if(/^https?:/i.test(ref))source=ref;if(/^https?:/i.test(img))image=img;
              if(!source&&u.pathname==='/url'){const q=u.searchParams.get('q')||u.searchParams.get('url');if(/^https?:/i.test(q||''))source=q;}
            }else source=u.href;
            return{source:normalizeUrl(source),image:normalizeUrl(image)};
          }catch(_){return{source:'',image:''}}
        };
        const add=(url,title,context,imageUrl,source,imageAlt='')=>{
          url=normalizeUrl(url);imageUrl=normalizeUrl(imageUrl);
          if(!url)return;let u=null;try{u=new URL(url)}catch(_){return}
          if(badHost(u.hostname))return;
          if(imageUrl&&badImage(imageUrl))imageUrl='';
          const t=norm(title),c=norm(context).slice(0,900),ia=norm(imageAlt).slice(0,320);
          if(badText(t+' '+c))return;
          const key=url+'|'+imageUrl;if(seen.has(key))return;seen.add(key);
          out.push({url,title:t||ia||u.hostname,context:c,host:u.hostname,rank:out.length+1,image_url:imageUrl,image_alt:ia,source,search_surface:surface});
        };

        // Layer 1: visible Web and Images result anchors. Unlike v8.08.36 this
        // does not require an <h3>; image cards often expose only an <img alt>.
        for(const a of [...document.querySelectorAll('a[href]')]){
          const parsed=parseGoogleHref(a.getAttribute('href')||a.href);if(!parsed.source)continue;
          const h=a.querySelector('h3,[role="heading"]');const im=a.querySelector('img');
          const alt=norm(im?.alt||im?.getAttribute?.('aria-label')||'');
          let title=norm(h?.innerText||h?.textContent||a.getAttribute('aria-label')||alt||a.innerText);
          let box=a.closest('div[data-snhf],div[data-ved],div[jscontroller],div.MjjYud,div')||a.parentElement;
          let context=norm(box?.innerText||a.innerText||alt).slice(0,900);
          if(surface==='web'&&!h&&title.length<3)continue;
          if(surface==='images'&&!im&&!parsed.image)continue;
          add(parsed.source,title,context,parsed.image,surface==='images'?'google_images_anchor':'google_web_anchor',alt);
          if(out.length>=limit*2)break;
        }

        // Layer 2: classic /imgres links can be HTML-escaped and therefore not
        // represented as a normal external href after Google rewrites the card.
        const html=String(document.documentElement?.innerHTML||'').slice(0,8_000_000);
        for(const m of html.matchAll(/(?:href=["']|\\?"url\\?":\\?")([^"']*\/imgres\?[^"']+)/gi)){
          if(out.length>=limit*3)break;
          const raw=jsun(m[1]).replace(/^\\?"|\\?"$/g,'');const parsed=parseGoogleHref(raw);
          if(parsed.source)add(parsed.source,'',raw,parsed.image,'google_images_imgres','');
        }

        // Layer 3: Google Images legacy/current payloads frequently keep the
        // original image (ou) and source page (ru) in script JSON. Read only URL
        // pairs; no preview bytes are used.
        if(surface==='images'&&out.length<limit){
          const payload=[...document.scripts].map(x=>String(x.textContent||'')).filter(Boolean).join('\n').slice(0,10_000_000);
          const patterns=[
            /["']ou["']\s*:\s*["']([^"']+)["'][\s\S]{0,900}?["']ru["']\s*:\s*["']([^"']+)["']/gi,
            /["']ru["']\s*:\s*["']([^"']+)["'][\s\S]{0,900}?["']ou["']\s*:\s*["']([^"']+)["']/gi
          ];
          for(let pi=0;pi<patterns.length;pi++)for(const m of payload.matchAll(patterns[pi])){
            if(out.length>=limit*3)break;
            const image=pi===0?jsun(m[1]):jsun(m[2]),source=pi===0?jsun(m[2]):jsun(m[1]);
            add(source,'',source,image,'google_images_payload','');
          }
        }
        return{status:out.length?'ok':'error',sources:out.slice(0,limit),surface,search_surface:surface,page_title:document.title||'',page_text:norm(document.body?.innerText||'').slice(0,4000),error:out.length?'':'Google '+surface+' 원본 상품페이지 후보를 찾지 못함'};
      }
    });
    return rows?.[0]?.result||{status:'error',sources:[],surface,error:'google main world result missing'};
  }catch(e){return{status:'error',sources:[],surface:String(currentTask?.search_surface||'web'),error:String(e)}}
}

async function scanExternalProductPageViaDebugger(limit=24){
  if(!workTabId)return{status:'error',detail_images:[],error:'work tab missing'};
  try{
    if(!pageDialogGuard.attached||pageDialogGuard.tabId!==workTabId){const a=await attachPageDialogGuard();if(!a?.ok)return{status:'error',detail_images:[],error:'external debugger attach failed: '+String(a?.error||'')}}
    await new Promise((resolve,reject)=>chrome.debugger.sendCommand({tabId:workTabId},'Runtime.enable',{},()=>{const e=chrome.runtime.lastError;e?reject(new Error(e.message)):resolve()}));
    const lim=Math.max(12,Number(limit||24)),rounds=Math.max(0,Number(currentTask?.detail_scroll_rounds||0)),waitMs=Math.max(180,Number(currentTask?.detail_scroll_wait_ms||520));
    const target=JSON.stringify(String(currentTask?.target_name||''));
    const expression=`(async()=>{\n
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));\n
      const target=${target};\n
      const norm=s=>String(s||'').replace(/\\s+/g,' ').trim();\n
      const tokens=[...new Set((target.toLowerCase().match(/[0-9a-z가-힣]+/g)||[]).filter(x=>x.length>=2))].slice(0,10);\n
      const bad=/logo|sprite|avatar|icon|badge|tracking|pixel|favicon|banner|advert|coupon|review|recommend|related|recent|ranking|loading|placeholder|payment|delivery|shipping|footer|header|nav|회원|로그인|광고|추천|리뷰/i;\n
      const badNode=e=>{let s='',n=e;for(let i=0;i<7&&n;i++,n=n.parentElement)s+=' '+String(n.className||'')+' '+String(n.id||'')+' '+String(n.getAttribute?.('aria-label')||'')+' '+String(n.getAttribute?.('data-testid')||'')+' '+String(n.innerText||'').slice(0,140);return /(recommend|related|similar|recent|ranking|banner|advert|coupon|review|footer|header|nav|cross.?sell|upsell|연관|추천상품|함께본|최근본|광고|배너|리뷰|다른\s*상품|비슷한\s*상품)/i.test(s)};\n
      const identity=[];const idSeen=new Set();const addId=(value,source)=>{value=norm(value);if(!value||idSeen.has(value))return;idSeen.add(value);identity.push({text:value.slice(0,600),source})};\n
      addId(document.title,'document_title');\n
      for(const sel of ['meta[property="og:title"]','meta[name="twitter:title"]','meta[itemprop="name"]'])for(const e of document.querySelectorAll(sel))addId(e.content||'','meta_title');\n
      for(const e of [...document.querySelectorAll('h1,[itemprop="name"],[data-testid*="product"][data-testid*="name"],[class*="product"][class*="name"],[class*="product"][class*="title"]')].slice(0,12))if(!badNode(e))addId(e.innerText||e.textContent||'','main_heading');\n
      for(const sc of document.querySelectorAll('script[type="application/ld+json"]')){try{const j=JSON.parse(sc.textContent||'null');const walk=o=>{if(!o)return;if(Array.isArray(o)){o.forEach(walk);return}if(typeof o!=='object')return;const typ=String(o['@type']||'').toLowerCase();if(typ.includes('product'))addId(o.name||o.headline||'','jsonld_product');for(const v of Object.values(o))walk(v)};walk(j)}catch(_){}}\n
      const map=new Map();\n
      const add=(url,role,score,alt,w,h,source,pos=0)=>{try{url=new URL(String(url||''),location.href).href}catch(_){return};if(!/^https?:/i.test(url)||bad.test(url))return;const key=url;const text=norm(alt);const hit=tokens.filter(x=>text.toLowerCase().includes(x)).length;const topLimit=Math.max(1800,innerHeight*2.2),nearTop=Number(pos||0)<=topLimit;const trusted=(source==='jsonld'||source==='meta'||(nearTop&&role==='product_gallery_or_main')||hit>0);score=Number(score||0)+hit*28+(trusted?26:-60);if(w&&h){const ratio=w/Math.max(1,h);if(ratio>6.5||ratio<0.12)score-=35;}const rec={url,role,score,alt:text.slice(0,360),width:Number(w||0),height:Number(h||0),detail_zone:role==='detail_description_dom',source,pos:Number(pos||0),target_hits:hit,near_top:nearTop,trusted_product_zone:trusted};const old=map.get(key);if(!old||Number(old.score||0)<score)map.set(key,rec);};\n
      const parseSrcset=(v)=>String(v||'').split(',').map(x=>x.trim().split(/\\s+/)[0]).filter(Boolean);\n
      const scan=()=>{\n
        for(const sel of ['meta[property="og:image"]','meta[property="og:image:url"]','meta[name="twitter:image"]','link[rel="image_src"]'])for(const e of document.querySelectorAll(sel))add(e.content||e.href,'product_gallery_or_main',175,identity[0]?.text||document.title,0,0,'meta',0);\n
        for(const sc of document.querySelectorAll('script[type="application/ld+json"]')){try{const j=JSON.parse(sc.textContent||'null');const walk=o=>{if(!o)return;if(Array.isArray(o)){o.forEach(walk);return}if(typeof o!=='object')return;const typ=String(o['@type']||'').toLowerCase();if(typ.includes('product')){const ims=o.image||o.images;for(const im of (Array.isArray(ims)?ims:[ims])){if(typeof im==='string')add(im,'product_gallery_or_main',210,o.name||document.title,0,0,'jsonld',0);else if(im&&typeof im==='object')add(im.url||im.contentUrl,'product_gallery_or_main',210,o.name||document.title,im.width,im.height,'jsonld',0)}};for(const v of Object.values(o))walk(v)};walk(j)}catch(_){}}\n
        for(const im of [...document.images]){if(badNode(im))continue;try{const r=im.getBoundingClientRect();const w=im.naturalWidth||im.width||r.width,h=im.naturalHeight||im.height||r.height;if(w<160||h<160)continue;const host=im.closest('figure,li,section,article,[class*="product"],[class*="gallery"],[class*="detail"],div');const alt=norm((im.alt||'')+' '+(im.title||'')+' '+(host?.innerText||'').slice(0,320));const pos=Math.max(0,r.top+(window.scrollY||0));const hit=tokens.some(x=>alt.toLowerCase().includes(x));const role=pos<Math.max(1800,innerHeight*2.2)||hit?'product_gallery_or_main':'detail_description_dom';let score=60+Math.min(80,Math.sqrt(Math.max(1,w*h))/8)+(role==='product_gallery_or_main'?30:0);if(/product|상품|대표|main|gallery|thumb|zoom|detail|상세/i.test((im.className||'')+' '+alt))score+=24;const vals=[im.currentSrc,im.src,im.getAttribute('data-src'),im.getAttribute('data-original'),im.getAttribute('data-lazy-src'),im.getAttribute('data-zoom-image'),im.getAttribute('data-large-image'),im.getAttribute('data-image'),im.getAttribute('data-origin-src')];for(const v of vals)if(v)add(v,role,score,alt,w,h,'img_attr',pos);for(const v of parseSrcset(im.getAttribute('srcset')||im.getAttribute('data-srcset')))add(v,role,score+8,alt,w,h,'img_srcset',pos);}catch(_){}}\n
        for(const src of document.querySelectorAll('picture source[srcset],source[data-srcset]')){const p=src.parentElement?.querySelector('img');if(p&&badNode(p))continue;const r=p?.getBoundingClientRect?.()||{top:0};const alt=norm(p?.alt||identity[0]?.text||document.title);const pos=Math.max(0,Number(r.top||0)+(window.scrollY||0));const role=pos<Math.max(1800,innerHeight*2.2)?'product_gallery_or_main':'detail_description_dom';for(const v of parseSrcset(src.getAttribute('srcset')||src.getAttribute('data-srcset')))add(v,role,90,alt,p?.naturalWidth||0,p?.naturalHeight||0,'picture_source',pos);}\n
        const styled=[...document.querySelectorAll('[style*="background"],[class*="product"],[class*="gallery"],[class*="detail"]')].slice(0,1200);for(const e of styled){if(badNode(e))continue;try{const r=e.getBoundingClientRect(),st=getComputedStyle(e),bg=String(st.backgroundImage||'');if(!bg||bg==='none'||r.width<180||r.height<180)continue;const near=norm((e.getAttribute('aria-label')||'')+' '+(e.innerText||'')).slice(0,260),pos=Math.max(0,r.top+(window.scrollY||0)),role=pos<Math.max(1800,innerHeight*2.2)?'product_gallery_or_main':'detail_description_dom';for(const m of bg.matchAll(/url\\(["']?([^"')]+)["']?\\)/g))add(m[1],role,70,near,r.width,r.height,'css_background',pos);}catch(_){}}\n
      };\n
      const eager=()=>{for(const im of [...document.images].slice(0,500)){try{im.loading='eager';for(const a of ['data-src','data-original','data-lazy-src']){const v=im.getAttribute(a);if(v&&!im.src)im.src=v}}catch(_){}}};\n
      const startY=window.scrollY||0;scan();eager();\n
      const maxY=Math.max(0,Math.max(document.documentElement.scrollHeight||0,document.body?.scrollHeight||0)-innerHeight);\n
      for(let i=0;i<${rounds};i++){const frac=${rounds}>1?i/Math.max(1,${rounds}-1):1;try{window.scrollTo({top:Math.floor(maxY*frac),behavior:'instant'})}catch(_){window.scrollTo(0,Math.floor(maxY*frac))}eager();await sleep(${waitMs});scan();}\n
      try{window.scrollTo({top:startY,behavior:'instant'})}catch(_){window.scrollTo(0,startY)}await sleep(120);scan();\n
      const out=[...map.values()].filter(x=>x.trusted_product_zone).sort((a,b)=>Number(b.score||0)-Number(a.score||0));const body=norm(document.body?.innerText||'').slice(0,22000);const identityText=identity.map(x=>x.text).join(' | ').slice(0,4200);\n
      return{status:out.length?'ok':'error',url:location.href,page_title:document.title||'',identity_text:identityText,identity_sources:identity,page_text:body,detail_images:out.slice(0,${lim}),scan_diag:{rounds:${rounds},candidates:out.length,maxY,identity_count:identity.length},error:out.length?'':'원본 상품페이지의 신뢰 가능한 상품 이미지 0장'};\n
    })()`;
    const r=await new Promise((resolve,reject)=>chrome.debugger.sendCommand({tabId:workTabId},'Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},res=>{const e=chrome.runtime.lastError;e?reject(new Error(e.message)):resolve(res)}));
    return r?.result?.value||{status:'error',detail_images:[],error:r?.exceptionDetails?.text||'external Runtime.evaluate no value'};
  }catch(e){return{status:'error',detail_images:[],error:String(e)}}
}

async function captureExternalRenderedProductImagesViaDebugger(){
  const captures=[],diag={site:currentTask?.site||'',candidates:0,errors:[]};
  if(!workTabId||currentTask?.mode!=='external_detail')return{captures,diag};
  try{
    if(!pageDialogGuard.attached||pageDialogGuard.tabId!==workTabId){const a=await attachPageDialogGuard();if(!a?.ok)return{captures,diag:Object.assign(diag,{error:a?.error||'debugger_not_attached'})}}
    const target=JSON.stringify(String(currentTask?.target_name||'')),maxCount=Math.max(4,Number(currentTask?.screen_crop_max_candidates||8));
    const expression=`(()=>{const target=${target},tokens=[...new Set((target.toLowerCase().match(/[0-9a-z가-힣]+/g)||[]).filter(x=>x.length>=2))].slice(0,10);const bad=e=>{let s='',n=e;for(let i=0;i<7&&n;i++,n=n.parentElement)s+=' '+String(n.className||'')+' '+String(n.id||'')+' '+String(n.getAttribute?.('aria-label')||'')+' '+String(n.innerText||'').slice(0,100);return /(recommend|related|similar|recent|ranking|banner|advert|coupon|review|footer|header|nav|연관|추천상품|함께본|최근본|광고|배너|리뷰)/i.test(s)};const arr=[];for(const im of [...document.images]){if(bad(im))continue;try{const r=im.getBoundingClientRect(),w=Math.max(r.width,Number(im.naturalWidth||0)),h=Math.max(r.height,Number(im.naturalHeight||0));if(w<240||h<240)continue;const ratio=w/Math.max(1,h);if(ratio>5.5||ratio<0.16)continue;const y=r.top+scrollY,x=r.left+scrollX,alt=String((im.alt||'')+' '+(im.title||'')+' '+(im.closest('figure,section,article,[class*=product],[class*=gallery],[class*=detail],div')?.innerText||'')).replace(/\\s+/g,' ').slice(0,360),low=alt.toLowerCase(),hits=tokens.filter(t=>low.includes(t)).length;let score=Math.min(w,1800)*Math.min(h,2200)+hits*25000000+(y<innerHeight*2.2?12000000:0);if(y>=innerHeight*2.2&&hits===0)continue;arr.push({x,y,width:Math.min(w,1800),height:Math.min(h,1800),src:im.currentSrc||im.src||'',alt,score,role:y<innerHeight*2.2?'external_gallery_rendered':'external_detail_rendered',trusted_product_zone:true,target_hits:hits});}catch(_){}}arr.sort((a,b)=>b.score-a.score);return arr.slice(0,${maxCount});})()`;
    const r=await new Promise((resolve,reject)=>chrome.debugger.sendCommand({tabId:workTabId},'Runtime.evaluate',{expression,returnByValue:true},res=>{const e=chrome.runtime.lastError;e?reject(new Error(e.message)):resolve(res)}));
    const rows=Array.isArray(r?.result?.value)?r.result.value:[];diag.candidates=rows.length;
    for(const row of rows){if(captures.length>=maxCount)break;const c=await detailClipCapture(row,'구글원본_상품이미지_화면크롭',captures.length+1,{role:row.role||'external_rendered_image',src:row.src||'',alt:row.alt||'',engine:'external_cdp'});if(c)captures.push(c)}
  }catch(e){diag.errors.push(String(e))}
  return{captures,diag};
}

async function closeCollectorLauncherTabs(){
  try{
    const tabs=await chrome.tabs.query({});
    const ids=(tabs||[]).filter(t=>t.id!==workTabId&&/^http:\/\/127\.0\.0\.1:8765\/collector(?:\?|$)/.test(t.url||'')).map(t=>t.id);
    if(ids.length)await chrome.tabs.remove(ids);
  }catch(e){}
}

async function dismissItemScoutJoinPromptMainWorld(){
  if(!workTabId||currentTask?.site!=="아이템스카우트"||currentTask?.mode!=="trend_keyword_collect")return{ok:true,dismissed:false,reason:"not_applicable"};
  try{
    const rows=await chrome.scripting.executeScript({
      target:{tabId:workTabId},world:"MAIN",
      func:()=>{
        const norm=x=>String(x||"").replace(/\s+/g," ").trim();
        const visible=e=>{try{const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>2&&r.height>2&&st.display!=="none"&&st.visibility!=="hidden"&&Number(st.opacity||1)>0.02;}catch(_e){return false;}};
        const dialogs=[...document.querySelectorAll("[role='dialog'],[aria-modal='true'],dialog,[class*='modal'],[class*='Modal'],[class*='dialog'],[class*='Dialog'],[class*='popup'],[class*='Popup']")].filter(visible);
        const choose=(scope)=>{const text=norm(scope?.innerText||scope?.textContent||"");let label="";if(text.includes("하루간 보지 않기"))label="하루간 보지 않기";else if(text.includes("다음에 할래요"))label="다음에 할래요";if(!label)return null;const nodes=[...scope.querySelectorAll("button,a,[role='button'],[tabindex],span,div,p,u")].filter(visible);let el=nodes.find(e=>{const t=norm(e.innerText||e.textContent||"");return t===label||t.replace(/\s/g,"")===label.replace(/\s/g,"");});if(!el)return null;return{el:el.closest?.("button,a,[role='button'],[tabindex]")||el,label};};
        let hit=null;for(const d of dialogs){const t=norm(d.innerText||d.textContent||"");if(!/하루간 보지 않기|다음에 할래요/.test(t))continue;hit=choose(d);if(hit)break;}
        if(!hit){const body=norm(document.body?.innerText||"");if(/하루간 보지 않기|다음에 할래요/.test(body))hit=choose(document.body);}
        if(!hit)return{ok:true,dismissed:false,reason:"no_prompt"};
        try{hit.el.scrollIntoView({block:"center",behavior:"instant"});}catch(_e){}
        try{hit.el.click();return{ok:true,dismissed:true,reason:hit.label==="하루간 보지 않기"?"clicked_hide_one_day":"clicked_next_time",target:hit.label};}catch(e){return{ok:false,dismissed:false,reason:String(e),target:hit.label};}
      }
    });
    return rows?.[0]?.result||{ok:false,dismissed:false,reason:"no_main_world_result"};
  }catch(e){return{ok:false,dismissed:false,reason:String(e)};}
}


async function collectNow(){
  if(!running||stage!=="collect"||!currentTask)return;
  try{
    await taskProgressBeat('collect_start');
    let res=null,trendJoinPrompt=null;
    if(currentTask?.site==="아이템스카우트"&&currentTask?.mode==="trend_keyword_collect"){
      trendJoinPrompt=await dismissItemScoutJoinPromptMainWorld();
      if(trendJoinPrompt?.dismissed)await new Promise(r=>setTimeout(r,420));
    }
    if(currentTask?.mode==="google_product_source_search"){
      res=await collectGoogleProductSourcePages(currentTask.limit||12);
    }else if(currentTask?.mode==="external_detail"){
      res=await scanExternalProductPageViaDebugger(currentTask.limit||24);
      if(res?.status==="ok"&&currentTask?.capture_rendered_crops!==false){
        try{const sc=await captureExternalRenderedProductImagesViaDebugger();res.screen_captures=sc?.captures||[];res.screen_capture_diag=sc?.diag||{};}catch(e){res.screen_captures=[];res.screen_capture_diag={error:String(e)}}
      }
      if(pageDialogGuard.events.length)res.auto_dismissed_dialogs=[...pageDialogGuard.events];
    }else if(currentTask?.site==="토스쇼핑"&&currentTask?.mode==="fixed_category_collect"){
      const siteCat=currentTask.site_category_label||currentTask.blog_category||currentTask.query||'';
      // v7.34: Toss fixed-category product reading is owned completely by the
      // background worker. The category click has already happened; bypass the
      // old content-script transaction gate that could incorrectly return 0/30.
      res={status:"toss_price_anchor_collect_required",site:"토스쇼핑",url:(await chrome.tabs.get(workTabId).catch(()=>({url:""})))?.url||"",cards:[],category_confirmed:true,toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,toss_uncheck_after_collect:false,toss_filter_cleanup_confirmed:false,toss_checked_before_collect:[siteCat],toss_checked_after_collect:[siteCat],clicked_label:siteCat,debug:Object.assign({},fixedRouteProgress||{},{collector:"toss_direct_text_background_v7_34",bypassed_content_transaction_gate:true})};
    }else{
      res=await chrome.tabs.sendMessage(workTabId,{
        type:"collect",
        site:currentTask.site,
        query:currentTask.query,
        mode:currentTask.mode,
        target:currentTask.target_name||"",
        category_label:currentTask.category_label||currentTask.site_category_label||"",
        category_id:currentTask.category_id||"",
        blog_category:currentTask.blog_category||currentTask.query||"",
        site_category_label:currentTask.site_category_label||"",
        ranking_anchor:currentTask.ranking_anchor||"",
        limit:currentTask.limit||10,
        age_group:currentTask.age_group||"",
        age_codes:currentTask.age_codes||[],
        period_days:currentTask.period_days||30,
        gender:currentTask.gender||"전체",
        keyword_type:currentTask.keyword_type||"",
        exclude_major_brands:!!currentTask.exclude_major_brands,
        detail_scroll_rounds:currentTask.detail_scroll_rounds||7,
        detail_scroll_wait_ms:currentTask.detail_scroll_wait_ms||850,
        fast_capture_only:currentTask.fast_capture_only!==false,
        critical_tokens:currentTask.critical_tokens||[],
        identity_tokens:currentTask.identity_tokens||[],
        signature_tokens:currentTask.signature_tokens||[],
        match_threshold:currentTask.match_threshold||0.62
      });
    }
    if(trendJoinPrompt&&res){res.debug=Object.assign({},res.debug||{},{background_join_prompt:trendJoinPrompt,page_reuse_v799:true});}
    if(currentTask?.site==="아이템스카우트"&&currentTask?.mode==="trend_keyword_collect"&&res?.status!=="ok"&&(res?.filter_state?.overlay_preflight?.remaining||res?.filter_state?.join_prompt_preflight?.remaining)){
      currentTask._itemscout_prompt_retry=Number(currentTask._itemscout_prompt_retry||0)+1;
      if(currentTask._itemscout_prompt_retry<=2){
        await dismissItemScoutJoinPromptMainWorld();
        clearTimeout(timer);
        timer=setTimeout(()=>collectNow(),900);
        return;
      }
    }
    if(currentTask?.mode==="detail" && res?.status==="ok"){
      const mf=await mainWorldDetailImagesMultiFrame(currentTask.limit||18,currentTask.fast_capture_only!==false);
      await taskProgressBeat('detail_dom_scan_done');
      const map=new Map();
      for(const im of [...(res.detail_images||[]),...(mf.images||[])]){
        if(!im?.url)continue;const old=map.get(im.url);
        if(!old){map.set(im.url,im);continue;}
        // Preserve the explicit product-description classification discovered by
        // content.js even when the multi-frame scanner gives the same URL a
        // larger generic score.
        if(old.detail_zone||old.role==='detail_description_dom'){
          if(Number(old.score||0)<Number(im.score||0))map.set(im.url,Object.assign({},im,{role:old.role||im.role,detail_zone:true,long_detail:old.long_detail||im.long_detail}));
          continue;
        }
        if(Number(old.score||0)<Number(im.score||0))map.set(im.url,im);
      }
      res.detail_images=[...map.values()].sort((a,b)=>Number(b.score||0)-Number(a.score||0)).slice(0,Number(currentTask.limit||18));
      if(mf.page_text && String(res.page_text||'').length<5000)res.page_text=((res.page_text||'')+' '+mf.page_text).slice(0,18000);
      res.detail_multiframe={ok:mf.ok,frames:mf.frames||[],count:res.detail_images.length,error:mf.error||''};
      if(currentTask?.capture_rendered_crops!==false){
        try{
          if(currentTask?.site==='쿠팡'){
            const sc=await captureCoupangRenderedProductImages();
            res.screen_captures=sc?.captures||[];res.screen_capture_diag=sc?.diag||{};
          }else if(currentTask?.site==='토스쇼핑'){
            const top=await captureTossTopGalleryImages();
            const sc=await captureGenericRenderedProductImages();
            res.screen_captures=[...(top?.captures||[]),...(sc?.captures||[])];
            res.screen_capture_diag={toss_top_gallery:top?.diag||{},generic:sc?.diag||{}};
          }else{
            const sc=await captureGenericRenderedProductImages();
            res.screen_captures=sc?.captures||[];res.screen_capture_diag=sc?.diag||{};
          }
        }catch(e){res.screen_captures=[];res.screen_capture_diag={error:String(e)}}
      }
      if(pageDialogGuard.events.length)res.auto_dismissed_dialogs=[...pageDialogGuard.events];
    }
    if(res?.status==="blocked"&&currentTask?.mode==="trend_coupang_pick"&&currentTask?.site==="쿠팡"){
      if(await recoverTrendCoupangBlock(res?.error||"blocked_search_result"))return;
    }
    if(res?.status==="login_required"||res?.status==="blocked"){
      await finish(res);return;
    }
    if(currentTask?.site==="토스쇼핑"&&currentTask?.mode==="fixed_category_collect"&&res?.status==="toss_price_anchor_collect_required"){
      const need=Number(currentTask.limit||30),siteCat=currentTask.site_category_label||currentTask.blog_category||currentTask.query||'';
      // v7.34 PRIMARY: read ALL Toss frames as plain rendered text.  A real
      // selling-price line is the anchor; the one-to-three contiguous title
      // lines immediately above it are the product name.  This exactly matches
      // the user's live Sharelink screen and does not depend on CSS/card DOM.
      const direct=await collectTossDirectTextPrimary(need);
      const mergedMap=new Map();tossMergeByName(mergedMap,direct.cards||[],'toss_direct_text');
      let anchor={ok:true,cards:[],diag:{skipped:true}},fallback={ok:true,cards:[],diag:{skipped:true}};
      if(mergedMap.size<need){anchor=await collectTossPriceAnchorPrimary(need);tossMergeByName(mergedMap,anchor.cards||[],'toss_price_anchor_fallback');}
      if(mergedMap.size<need){fallback=await collectTossDataFeedPrimary(need);tossMergeByName(mergedMap,fallback.cards||[],'toss_network_fallback');}
      const cards=[...mergedMap.values()].slice(0,need);
      let cleanup=null;
      if(cards.length>=need){cleanup=await finalizeTossAfterDeep(siteCat);}
      const cleanupOk=!!cleanup?.toss_uncheck_after_collect;
      const debug=Object.assign({},res.debug||{},{direct_text_primary:direct.diag||{},direct_text_count:(direct.cards||[]).length,card_local_fallback:anchor.diag||{},card_local_fallback_count:(anchor.cards||[]).length,data_feed_fallback:fallback.diag||{},data_feed_fallback_count:(fallback.cards||[]).length,final_count:cards.length,final_cleanup:cleanup});
      if(cards.length>=need){
        // IMPORTANT: do not throw away 30 valid products only because Toss's
        // custom checkbox does not expose a reliable OFF state. Every Toss task
        // starts from a fresh /home anyway. If one-click OFF cannot be confirmed,
        // finish() performs an explicit /home reload and records that reset as
        // the cleanup proof before the result is posted.
        res=Object.assign({},res,{status:'ok',error:'',cards,category_confirmed:true,toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,toss_checked_before_collect:[siteCat],toss_uncheck_after_collect:cleanupOk,toss_filter_cleanup_confirmed:cleanupOk,toss_cleanup_method:cleanupOk?'checkbox_off':'pending_home_reload',toss_cleanup_pending_home_reset:!cleanupOk,toss_checked_after_collect:cleanupOk?[]:[siteCat],debug});
      }else{
        res=Object.assign({},res,{status:'error',cards,error:`토스 직접 텍스트 수집 결과 ${need}개 중 ${cards.length}개입니다. 카테고리 체크는 유지했습니다.`,category_confirmed:true,toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,toss_checked_before_collect:[siteCat],toss_uncheck_after_collect:false,toss_filter_cleanup_confirmed:false,toss_checked_after_collect:[siteCat],debug});
      }
    }
    if(currentTask?.site==="토스쇼핑"&&currentTask?.mode==="fixed_category_collect"&&res?.status==="toss_visual_collect_required"){
      const need=Number(currentTask.limit||30);
      const visual=await mainWorldTossVisualOCRCollect(need,res.cards||[]);
      let merged=mergeTossCards(res.cards||[],visual.cards||[],need);
      let deep={cards:[],diag:{skipped:true}};
      // DOM/Shadow/iframe parsing is now only a supplement if the visual OCR
      // did not reach 30 unique product names.
      if(merged.length<need){deep=await mainWorldTossDeepExtract(need);merged=mergeTossCards(merged,deep.cards||[],need);}
      let cleanup=null;if(merged.length>=need){cleanup=await finalizeTossAfterDeep(currentTask.site_category_label||currentTask.blog_category||currentTask.query||'');}
      const baseDebug=Object.assign({},res.debug||{},{visual_primary:true,visual_ocr:visual.diag||{},visual_ocr_cards:(visual.cards||[]).length,background_deep_extract:deep.diag||{},background_deep_cards:(deep.cards||[]).length,merged_cards:merged.length,final_cleanup:cleanup});
      if(merged.length>=need&&cleanup?.toss_uncheck_after_collect){
        res=Object.assign({},res,{status:'ok',error:'',cards:merged,toss_uncheck_after_collect:true,toss_checked_after_collect:cleanup.toss_checked_after_collect||[],debug:baseDebug});
      }else{
        res=Object.assign({},res,{status:'error',cards:merged,error:merged.length<need?`토스 화면 OCR/DOM 보조 수집 결과 ${need}개 중 ${merged.length}개입니다. 체크는 유지했습니다.`:(cleanup?.error||'토스 30개 수집 후 체크 해제 실패'),toss_uncheck_after_collect:false,toss_checked_after_collect:[currentTask.site_category_label||currentTask.blog_category||currentTask.query||''],debug:baseDebug});
      }
    }
    if(currentTask?.site==="토스쇼핑"&&currentTask?.mode==="fixed_category_collect"&&res?.status==="toss_deep_fallback_required"){
      const need=Number(currentTask.limit||30),deep=await mainWorldTossDeepExtract(need);
      let merged=mergeTossCards(res.cards||[],deep.cards||[],need);
      // IMPORTANT: v7.25 still called finalizeTossAfterDeep() before checking
      // whether 30 products were actually secured.  That reproduced the exact
      // user-visible ON -> read few/zero -> OFF failure.  v7.26 keeps the
      // category checked and switches to screenshot/OCR collection first.
      let visual={cards:[],diag:{skipped:true}};
      if(merged.length<need){
        visual=await mainWorldTossVisualOCRCollect(need,merged);
        merged=mergeTossCards(merged,visual.cards||[],need);
      }
      let cleanup=null;
      if(merged.length>=need){cleanup=await finalizeTossAfterDeep(currentTask.site_category_label||currentTask.blog_category||currentTask.query||'');}
      const baseDebug=Object.assign({},res.debug||{}, {background_deep_extract:deep.diag||{},background_deep_cards:(deep.cards||[]).length,visual_ocr:visual.diag||{},visual_ocr_cards:(visual.cards||[]).length,merged_cards:merged.length,final_cleanup:cleanup});
      if(merged.length>=need&&cleanup?.toss_uncheck_after_collect){
        res=Object.assign({},res,{status:'ok',error:'',cards:merged,category_confirmed:true,toss_product_lookup_confirmed:true,toss_single_checkbox_confirmed:true,toss_uncheck_after_collect:true,toss_checked_after_collect:cleanup.toss_checked_after_collect||[],debug:baseDebug});
      }else{
        res=Object.assign({},res,{status:'error',cards:merged,error:merged.length<need?`토스 화면 OCR까지 수행했지만 ${need}개 중 ${merged.length}개만 확보했습니다. 카테고리 체크는 해제하지 않았습니다.`:(cleanup?.error||'토스 수집 후 체크 해제 실패'),toss_uncheck_after_collect:false,toss_checked_after_collect:[currentTask.site_category_label||currentTask.blog_category||currentTask.query||''],debug:baseDebug});
      }
    }
    // A search-results page is never accepted as image evidence. Resolve the
    // strictly matched card to a real Coupang /vp/products page before Python
    // starts the representative + detail-image collection task.
    if(currentTask?.site==="쿠팡"&&currentTask?.resolve_product_page&&res?.selected){
      const page=await resolveCoupangProductHrefFromPage(res.selected);
      res.product_page_resolution=page;
      if(page?.ok&&page?.url)res.selected.url=page.url;
      if(!page?.ok){res.status="error";res.error="동일상품 카드는 찾았지만 쿠팡 상세페이지 직링크를 확정하지 못했습니다.";}
    }
    let shot=null;
    const trendSuccess=currentTask.mode==="trend_keyword_collect"&&res?.status==="ok";
    if(!trendSuccess&&((currentTask.capture && res?.selected) || res?.status!=="ok" || currentTask.mode==="fixed_category_collect")){
      try{
        const tab=await chrome.tabs.get(workTabId);
        shot=await chrome.tabs.captureVisibleTab(tab.windowId,{format:"png"});
      }catch(e){res.capture_error=String(e);}
    }
    await finish(res||{status:"error",error:"no response"},shot);
  }catch(e){
    // One retry after a short wait handles late SPA rendering.
    try{
      await new Promise(r=>setTimeout(r,currentTask?.mode==="detail"?4500:1600));
      const res=await chrome.tabs.sendMessage(workTabId,{
        type:"collect",site:currentTask.site,query:currentTask.query,
        mode:currentTask.mode,target:currentTask.target_name||"",
        category_label:currentTask.category_label||currentTask.site_category_label||"",
        category_id:currentTask.category_id||"",
        blog_category:currentTask.blog_category||currentTask.query||"",
        site_category_label:currentTask.site_category_label||"",
        ranking_anchor:currentTask.ranking_anchor||"",
        limit:currentTask.limit||10,
        age_group:currentTask.age_group||"",
        age_codes:currentTask.age_codes||[],
        period_days:currentTask.period_days||30,
        gender:currentTask.gender||"전체",
        keyword_type:currentTask.keyword_type||"",
        exclude_major_brands:!!currentTask.exclude_major_brands,
        detail_scroll_rounds:currentTask.detail_scroll_rounds||7,
        detail_scroll_wait_ms:currentTask.detail_scroll_wait_ms||850,
        fast_capture_only:currentTask.fast_capture_only!==false,
        critical_tokens:currentTask.critical_tokens||[],
        identity_tokens:currentTask.identity_tokens||[],
        signature_tokens:currentTask.signature_tokens||[],
        match_threshold:currentTask.match_threshold||0.62
      });
      await finish(res||{status:"error",error:"no response after retry"});
    }catch(e2){
      await finish({status:"error",error:String(e2)});
    }
  }
}

async function finish(result,screenshot=null){
  clearTimeout(watchdog);
  if(["detail","external_detail"].includes(currentTask?.mode)&&pageDialogGuard.events.length&&result)result.auto_dismissed_dialogs=[...pageDialogGuard.events];
  if(["detail","external_detail"].includes(currentTask?.mode))await detachPageDialogGuard();
  // v7.34: Toss filter cleanup is best-effort checkbox OFF, then guaranteed
  // fresh-home reset.  A valid 30-product result must never be discarded solely
  // because a custom checkbox has no machine-readable OFF state.
  if(currentTask?.site==="토스쇼핑"&&result&&result.toss_cleanup_pending_home_reset&&Array.isArray(result.cards)&&result.cards.length>=Number(currentTask?.limit||30)){
    try{
      await chrome.tabs.update(workTabId,{url:"https://sharelink.toss.im/home",active:true});
      await new Promise(r=>setTimeout(r,900));
      const tab=await chrome.tabs.get(workTabId),u=String(tab?.url||"");
      const ok=/^https:\/\/sharelink\.toss\.im\/home(?:[?#]|$)/.test(u);
      result.toss_filter_cleanup_confirmed=ok;
      result.toss_cleanup_method=ok?'fresh_home_reload':'fresh_home_reload_unconfirmed';
      if(ok){result.toss_checked_after_collect=[];result.error='';result.status='ok';}
      if(result.debug)result.debug.home_reload_cleanup={ok,url:u};
    }catch(e){
      result.toss_filter_cleanup_confirmed=false;result.toss_cleanup_method='fresh_home_reload_failed';
      if(result.debug)result.debug.home_reload_cleanup={ok:false,error:String(e)};
    }
    delete result.toss_cleanup_pending_home_reset;
  }
  if(currentTask?.site==="토스쇼핑"&&result&&result.toss_uncheck_after_collect){
    result.toss_filter_cleanup_confirmed=true;result.toss_cleanup_method=result.toss_cleanup_method||'checkbox_off';
  }
  try{
    await post("/api/result",{
      run_id:runId,task_id:currentTask.id,result,screenshot
    });
  }catch(e){console.error("finish post",e);}
  if(currentTask?.site==="토스쇼핑")await tossNetDetach();
  const delay=currentTask?.mode==="google_product_source_search" ? Math.max(900,Number(currentTask?.delay_ms||1200))
    : currentTask?.mode==="external_detail" ? Math.max(1200,Number(currentTask?.delay_ms||1800))
    : currentTask?.mode==="trend_keyword_collect" ? Math.max(300,Number(currentTask?.delay_ms||500))
    : currentTask?.mode==="trend_coupang_pick" ? Math.max(6000,Number(currentTask?.delay_ms||7000))+Math.floor(Math.random()*2500)
    : Math.max(1500,Number(currentTask?.delay_ms||4000));
  const expectedGeneration=runGeneration;
  currentTask=null;stage=null;
  clearTimeout(timer);
  timer=setTimeout(()=>nextTask(expectedGeneration),delay);
}
