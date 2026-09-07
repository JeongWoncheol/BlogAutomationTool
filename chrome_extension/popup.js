const s=document.getElementById("s");
const start=document.getElementById("start");
const stop=document.getElementById("stop");
const refresh=document.getElementById("refresh");
const BRIDGE="http://127.0.0.1:8765";

async function bridge(path,opts){
  const r=await fetch(BRIDGE+path,opts);
  return await r.json();
}
async function update(){
  try{
    await bridge("/api/heartbeat",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ts:Date.now(),extension_version:chrome.runtime.getManifest().version,source:"popup"})
    });
    const h=await bridge("/health");
    const a=await bridge("/api/active_run");
    const ext=await chrome.runtime.sendMessage({type:"getStatus"}).catch(()=>({}));
    let text=`확장 버전: ${chrome.runtime.getManifest().version}\nBridge: 정상\n`;
    text+=`Heartbeat: ${h.extension_online?"연결됨":"대기"}\n`;
    text+=`활성 Run: ${a.active ? a.run_id : "없음"}\n`;
    if(a.active) text+=`진행: ${a.status.done}/${a.status.total}\n`;
    text+=`Collector: ${ext.running?"실행 중":"대기"} ${ext.stage||""}`;
    s.textContent=text;
  }catch(e){
    s.textContent="Bridge가 실행되지 않았습니다.\n프로그램에서 상품검색/가격검증을 먼저 실행하세요.\n"+String(e);
  }
}
start.onclick=async()=>{
  try{
    const a=await bridge("/api/active_run");
    if(!a.active){
      s.textContent="활성 Run이 없습니다.\n프로그램에서 ① 인기상품 통합검색 또는 가격검증 버튼을 먼저 누르세요.";
      return;
    }
    const resp=await chrome.runtime.sendMessage({type:"manualStart",runId:a.run_id});
    s.textContent=resp?.ok ? `Run 연결 성공\n${a.run_id}` : `Run 연결 실패\n${resp?.error||""}`;
    setTimeout(update,800);
  }catch(e){s.textContent="연결 실패\n"+String(e);}
};
stop.onclick=async()=>{
  await chrome.runtime.sendMessage({type:"manualStop"}).catch(()=>{});
  s.textContent="수집 중지 요청";
};
refresh.onclick=update;
update();
