// v7.41: Coupang sometimes raises a native alert while the product page is
// otherwise usable. A native modal blocks extension messages until a person
// clicks 확인, so suppress only the known transient server-error alert here.
(()=>{
  if(window.__NBAS_COUPANG_DIALOG_GUARD__)return;
  window.__NBAS_COUPANG_DIALOG_GUARD__=true;
  const originalAlert=window.alert.bind(window);
  const isTransient=message=>/(서버에서\s*오류|오류가\s*발생|server\s*error|temporar(?:y|ily)\s*(?:error|unavailable))/i.test(String(message||''));
  window.alert=function(message){
    if(!isTransient(message))return originalAlert(message);
    try{
      const events=JSON.parse(sessionStorage.getItem('__nbas_coupang_dialogs__')||'[]');
      events.push({message:String(message||''),ts:Date.now(),handled:'main_world_alert_guard'});
      sessionStorage.setItem('__nbas_coupang_dialogs__',JSON.stringify(events.slice(-10)));
    }catch(_e){}
    console.warn('[NBAS] transient Coupang server alert suppressed:',message);
  };
})();
