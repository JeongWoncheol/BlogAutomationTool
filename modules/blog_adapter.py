# -*- coding: utf-8 -*-
from pathlib import Path
import os,json,time,re,ctypes,sqlite3,traceback,hashlib,threading,subprocess,urllib.parse,importlib
from .common import *
from .published_product_registry import record_published_product
try:
 from selenium import webdriver
 from selenium.webdriver.common.by import By
 from selenium.webdriver.common.keys import Keys
 from selenium.webdriver.common.action_chains import ActionChains
 from selenium.webdriver.support.ui import WebDriverWait
 from selenium.webdriver.support import expected_conditions as EC
except Exception: webdriver=None

WRITE_URL="https://blog.naver.com/GoBlogWrite.naver"
_BLOG_DRIVER=None
TITLE_SELECTORS=".se-title-text,.se-section-documentTitle,[contenteditable='true'][data-placeholder*='제목'],[contenteditable='true'][aria-label*='제목']"
BODY_SELECTORS=".se-main-container,.se-content"
BODY_EDITABLE_SELECTORS=(
 ".se-section-text .se-text-paragraph[contenteditable='true'],"
 ".se-section-text [contenteditable='true'],"
 ".se-component.se-text [contenteditable='true'],"
 ".se-module-text .se-text-paragraph[contenteditable='true'],"
 ".se-main-container [contenteditable='true'],.se-content [contenteditable='true'],"
 "[contenteditable='true'][data-placeholder*='본문'],[contenteditable='true'][aria-label*='본문'],"
 ".se-section-text .se-text-paragraph,.se-component.se-text .se-text-paragraph,"
 "[contenteditable='true'],[role='textbox'],textarea"
)

class DraftSaveAmbiguousError(RuntimeError):
 """A save click may have been accepted but completion could not be proven. Never auto-retry this post."""
 pass

def health():
 return {"ready":webdriver is not None,"name":"네이버 자동등록","message":"v8.08.51 · SmartEditor 실제 체크표시 문단까지 굵게 + #fff8b2 강제 검증" if webdriver else "selenium 미설치"}

def close_file_dialogs():
 if os.name!="nt":return
 user32=ctypes.windll.user32;WM_CLOSE=0x0010
 @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
 def cb(hwnd,l):
  try:
   if not user32.IsWindowVisible(hwnd):return True
   cls=ctypes.create_unicode_buffer(256);user32.GetClassNameW(hwnd,cls,256)
   n=user32.GetWindowTextLengthW(hwnd);t=ctypes.create_unicode_buffer(n+1);user32.GetWindowTextW(hwnd,t,n+1)
   if cls.value=="#32770" and ("열기" in t.value or "Open" in t.value):user32.PostMessageW(hwnd,WM_CLOSE,0,0)
  except:pass
  return True
 try:user32.EnumWindows(cb,0)
 except:pass

def _driver_alive(d):
 if d is None:return False
 try:
  handles=list(d.window_handles or [])
  if not handles:return False
  try:cur=d.current_window_handle
  except Exception:cur=None
  if cur not in handles:d.switch_to.window(handles[0])
  d.execute_script("return document.readyState || 'loading'")
  return True
 except Exception:return False

def _is_webview_dead_error(exc):
 text=(type(exc).__name__+": "+str(exc)).lower()
 needles=("web view not found","no such window","target window already closed","chrome not reachable",
          "disconnected: not connected to devtools","disconnected: unable to receive message from renderer",
          "session deleted because of page crash","invalid session id","tab crashed","page crash","devtoolsactiveport")
 return any(x in text for x in needles)

def _dispose_driver(d=None):
 global _BLOG_DRIVER
 target=d or _BLOG_DRIVER
 if target is not None:
  try:target.quit()
  except Exception:pass
 if target is _BLOG_DRIVER or d is None:_BLOG_DRIVER=None

def _automation_profile_path():
 return Path(os.environ.get("LOCALAPPDATA",str(ROOT)))/settings().get("chrome_profile","NaverBlogAutomationProfile")

def _profile_chrome_pids(profile):
 """Return only chrome.exe processes that own the dedicated automation profile."""
 if os.name!="nt":return []
 try:
  target=str(Path(profile).resolve()).replace("'","''")
  ps=("$t='"+target+"'; Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
      "Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($t,[System.StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
      "Select-Object -ExpandProperty ProcessId")
  result=subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],capture_output=True,text=True,timeout=8)
  return [int(value.strip()) for value in (result.stdout or "").splitlines() if value.strip().isdigit()]
 except Exception:return []

def _release_stale_profile(profile):
 """Recover only the program-owned Chrome profile after a verified start failure."""
 profile=Path(profile);pids=_profile_chrome_pids(profile)
 if pids:
  log("네이버 전용 Chrome 프로필 점유 감지 · 이전 자동화 Chrome 정리: "+",".join(map(str,pids)))
  for pid in pids:
   try:subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],capture_output=True,timeout=6)
   except Exception:pass
  time.sleep(1.4)
 if not _profile_chrome_pids(profile):
  for name in ("SingletonLock","SingletonSocket","SingletonCookie","DevToolsActivePort"):
   try:(profile/name).unlink(missing_ok=True)
   except Exception:pass

def _new_driver_with_profile(profile):
 opt=webdriver.ChromeOptions()
 opt.add_argument(f"--user-data-dir={profile}");opt.add_argument("--start-maximized");opt.add_argument("--no-first-run");opt.add_argument("--no-default-browser-check")
 opt.add_experimental_option("detach",False)
 return webdriver.Chrome(options=opt)

def start_driver(force_new=False):
 """Return one reusable automation Chrome. Never create an extra tab per product."""
 global _BLOG_DRIVER
 if not force_new and _driver_alive(_BLOG_DRIVER):return _BLOG_DRIVER
 if _BLOG_DRIVER is not None:_dispose_driver(_BLOG_DRIVER)
 if webdriver is None:raise RuntimeError("Selenium을 불러오지 못했습니다. requirements 설치 상태를 확인하세요.")
 profile=_automation_profile_path();profile.mkdir(parents=True,exist_ok=True)
 try:
  _BLOG_DRIVER=_new_driver_with_profile(profile);log("네이버 Chrome 시작 성공 · v8.07 전용 프로필");return _BLOG_DRIVER
 except Exception as first:
  log("네이버 Chrome 1차 시작 실패: "+(type(first).__name__+": "+str(first)).replace("\n"," ")[:900])
  _release_stale_profile(profile)
  try:
   _BLOG_DRIVER=_new_driver_with_profile(profile);log("네이버 Chrome 시작 성공 · 전용 프로필 잠금 자동복구");return _BLOG_DRIVER
  except Exception as second:
   _BLOG_DRIVER=None
   raise RuntimeError("네이버 전용 Chrome 시작 실패. 전용 프로필 잠금 복구 후에도 시작하지 못했습니다: "+str(second)[:500])

def _ensure_one_valid_window(d):
 if not _driver_alive(d):raise RuntimeError("Chrome 자동화 창을 찾지 못했습니다(web view/session lost)")
 handles=list(d.window_handles or [])
 # Old v7.63 created a new tab after every product. Clean only stale extra tabs
 # inside this dedicated automation profile so v7.64 always works in one tab.
 if len(handles)>1:
  keep=d.current_window_handle if d.current_window_handle in handles else handles[0]
  for h in list(handles):
   if h==keep:continue
   try:d.switch_to.window(h);d.close()
   except Exception:pass
  d.switch_to.window(keep)
 return d.current_window_handle

def _navigate_same_tab(d,url):
 _ensure_one_valid_window(d)
 try:d.switch_to.default_content()
 except Exception:pass
 d.get(url)
 WebDriverWait(d,30).until(lambda x: _driver_alive(x) and x.execute_script("return document.readyState") in ("interactive","complete"))
 return d.current_window_handle

def _wait_for_naver_login_if_needed(d):
 """Allow a one-time manual login in the same persistent automation profile."""
 if "nid.naver.com" not in str(getattr(d,"current_url","") or ""):return False
 timeout=max(30,float(settings().get("blog_login_wait_sec",180)));end=time.time()+timeout
 log(f"네이버 로그인 대기: 열린 자동화 Chrome에서 로그인하세요(최대 {int(timeout)}초)")
 while time.time()<end:
  try:
   if "nid.naver.com" not in str(d.current_url or ""):
    _navigate_same_tab(d,WRITE_URL);return True
  except Exception:pass
  time.sleep(.5)
 raise RuntimeError("네이버 로그인 대기 시간초과. 열린 자동화 Chrome에서 로그인한 뒤 임시저장을 다시 실행하세요.")

def _editor_context_here(d):
 """True only in the document that owns both visible title and body editors."""
 try:
  titles=d.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS)
  bodies=d.find_elements(By.CSS_SELECTOR,BODY_SELECTORS)
  return any(_visible(x) for x in titles) and any(_visible(x) for x in bodies)
 except Exception:return False

def _switch_to_editor_context(d,timeout=45,quiet=False):
 """Find SmartEditor in the top document or any nested iframe.

 Naver no longer guarantees that every account receives an iframe named
 `mainFrame`. The previous fixed-ID wait opened Naver successfully but timed
 out before the first title keystroke on alternate layouts.
 """
 _ensure_one_valid_window(d);end=time.time()+float(timeout);last={}
 def descend(depth,path):
  if _editor_context_here(d):return path or "top"
  if depth<=0:return None
  try:frames=d.find_elements(By.CSS_SELECTOR,"iframe,frame")
  except Exception:frames=[]
  for i,fr in enumerate(frames):
   try:
    if not _visible(fr):continue
    ident=fr.get_attribute("id") or fr.get_attribute("name") or str(i)
    d.switch_to.frame(fr)
    found=descend(depth-1,path+[ident])
    if found:return found
    d.switch_to.parent_frame()
   except Exception:
    try:d.switch_to.default_content()
    except Exception:pass
  return None
 while time.time()<end:
  try:
   d.switch_to.default_content()
   found=descend(3,[])
   if found:
    if not quiet:log("네이버 SmartEditor 입력 문서 확인: "+("/".join(found) if isinstance(found,list) else str(found)))
    return found
   d.switch_to.default_content()
   last={"url":str(getattr(d,"current_url","") or ""),"title":str(getattr(d,"title","") or ""),
         "frames":len(d.find_elements(By.CSS_SELECTOR,"iframe,frame")),"source":(d.page_source or "")[:5000]}
   url=last["url"].lower();src=last["source"]
   if "nid.naver.com" in url or "로그인" in src and "SmartEditor" not in src:
    raise RuntimeError("네이버 로그인이 필요합니다. 열린 자동화 Chrome에서 로그인한 뒤 다시 실행하세요.")
   if any(x in src for x in ("접근 권한이 없습니다","블로그를 개설","서비스 이용이 제한")):
    raise RuntimeError("네이버 블로그 글쓰기 권한 또는 계정 상태를 확인해야 합니다.")
  except RuntimeError:raise
  except Exception as e:last["error"]=str(e)
  time.sleep(.35)
 raise RuntimeError(f"SmartEditor 입력 영역을 찾지 못했습니다. URL={last.get('url','')} · iframe={last.get('frames',0)} · 페이지제목={last.get('title','')}")

def wait_frame(d):
 return _switch_to_editor_context(d,timeout=float(settings().get("blog_editor_ready_timeout_sec",45)))

def _switch_to_editor_host(d,timeout=8):
 """Return to the title/toolbar document without assuming a fixed frame id."""
 return _switch_to_editor_context(d,timeout=max(1.0,float(timeout)),quiet=True)

def _visible(el):
 try:
  return bool(el.is_displayed())
 except Exception:return False

def _page_has_visible_text(d,text):
 try:
  return bool(d.execute_script("""
   const needle=arguments[0];
   const els=[...document.querySelectorAll('body *')];
   return els.some(e=>{
    const t=(e.innerText||'').trim(); if(!t || !t.includes(needle))return false;
    const s=getComputedStyle(e),r=e.getBoundingClientRect();
    return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;
   });
  """,text))
 except Exception:return text in (getattr(d,'page_source','') or '')

def cancel_existing(d):
 """Start a NEW post. The '작성 중인 글' dialog is a resume prompt, not a save confirmation."""
 def here():
  src=d.page_source or ''
  if "작성 중인 글이 있습니다" not in src and "이어져 작성하시겠습니까" not in src:return False
  for xp in ["//button[normalize-space(.)='취소']","//*[@role='button' and normalize-space(.)='취소']"]:
   for e in d.find_elements(By.XPATH,xp):
    if e.is_displayed() and e.is_enabled():
     e.click();time.sleep(1.0)
     return True
  return False
 d.switch_to.default_content();clicked=here()
 try:
  wait_frame(d);clicked=here() or clicked
 except Exception:pass
 if clicked:
  # Never type while the resume dialog is still fading out.
  end=time.time()+5
  while time.time()<end:
   if "작성 중인 글이 있습니다" not in (d.page_source or ''):break
   time.sleep(.2)
 return clicked

def toolbar(d,labels):
 for lab in labels:
  xp=f"//*[self::button or @role='button'][contains(@aria-label,{json.dumps(lab)}) or contains(@title,{json.dumps(lab)}) or contains(normalize-space(.),{json.dumps(lab)})]"
  for e in d.find_elements(By.XPATH,xp):
   if e.is_displayed():return e
 return None
def active(e):
 if not e:return False
 return (e.get_attribute("aria-pressed") or "").lower()=="true" or "active" in (e.get_attribute("class") or "").lower()
def basefmt(d):
 # Nested-body layouts keep formatting controls in the title/toolbar host frame.
 try:_switch_to_editor_host(d,timeout=5)
 except Exception:pass
 e=toolbar(d,["취소선","strike"]); 
 if active(e):e.click()
 e=toolbar(d,["굵게","bold"]);
 if active(e):e.click()
 # v7.60: mobile-style centered short lines instead of PC-width layout.
 if bool(settings().get("blog_mobile_center_align",True)):
  e=toolbar(d,["가운데 정렬","중앙 정렬","가운데","center"])
 else:
  e=toolbar(d,["왼쪽 정렬","좌측 정렬","왼쪽","left"])
 if e:
  try:
   if not active(e):e.click()
  except Exception:
   try:e.click()
   except:pass

def _editor_text(d):
 try:
  root=_body_root(d,timeout=6)
  text=str(d.execute_script("""
   const titleSel='.se-title-text,.se-section-documentTitle,[data-placeholder*=\"제목\"],[aria-label*=\"제목\"]';
   const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
   const isTitle=e=>!!e.closest(titleSel)||/제목|title/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||''));
   const nodes=[...document.querySelectorAll(arguments[0])].filter(e=>visible(e)&&!isTitle(e));
   const leaves=nodes.filter(e=>!nodes.some(x=>x!==e&&e.contains(x)));
   if(leaves.length)return leaves.map(e=>e.innerText||e.textContent||'').join('\n');
   const root=arguments[1];return root?(root.innerText||root.textContent||''):'';
  """,BODY_EDITABLE_SELECTORS,root) or '')
  return re.sub(r"(?i)본문을?\s*입력(?:해\s*주세요|하세요)?|내용을?\s*입력(?:해\s*주세요|하세요)?","",text)
 except Exception:return ''

def _editor_title_text(d):
 def read_here():
  return str(d.execute_script("""
    const r=document.querySelector(arguments[0]);
    return r?(r.innerText||r.textContent||''):'';
   """,TITLE_SELECTORS) or '')
 try:
  text=read_here()
  if text:return text
 except Exception:pass
 try:
  _switch_to_editor_host(d,timeout=6)
  return read_here()
 except Exception:return ''

def _compact_text(text):
 return re.sub(r"\s+","",str(text or ''))

def _frame_is_editor_auxiliary(fr):
 """Reject SmartEditor helper iframes that are not the article body.

 Naver creates transient IME/input-buffer frames (for example
 ``input_buffer178807...``). v7.79 could mistake the contenteditable inside
 such a frame for the article body, so the first sentence never reached the
 actual post document.
 """
 try:
  hint=" ".join(str(fr.get_attribute(x) or "") for x in ("id","name","class","src","title","aria-label")).lower()
 except Exception:hint=""
 return bool(re.search(r"input[_-]?buffer|inputbuffer|clipboard|paste[_-]?(?:buffer|area|frame)?|dummy|hidden[_-]?frame|accessibility[_-]?frame|ime[_-]?(?:buffer|frame)",hint))



def _smarteditor3_native_body(d, activate=True):
 """Return SmartEditor 3/ONE body shell even before contenteditable is materialized.

 Current Naver builds can expose only the title as contenteditable while the body
 is a lazy ``se-component se-text`` shell. Clicking the real text component
 creates/activates Naver's internal IME input_buffer. Treat that as a valid body
 focus instead of waiting forever for a second contenteditable element.
 """
 try:
  return d.execute_script("""
   const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle';
   const vis=e=>{if(!e)return false;const st=getComputedStyle(e),r=e.getBoundingClientRect();return st.display!=='none'&&st.visibility!=='hidden'&&r.width>=80&&r.height>=12;};
   const isTitle=e=>!!e.closest(titleSel)||/제목|title/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||''));
   const sels=[
    '.se-section-text .se-module-text',
    '.se-component.se-text .se-module-text',
    '.se-component.se-text .se-module',
    '.se-section-text .se-text-paragraph',
    '.se-component.se-text .se-text-paragraph',
    '.se-component.se-text',
    '.se-section-text',
    '.se-main-container .se-placeholder',
    '.se-main-container [class*=se-module-text]',
    '.se-main-container [class*=text-paragraph]',
    '.se-content .se-component.se-text'
   ];
   let nodes=[];for(const sel of sels){for(const e of document.querySelectorAll(sel)){if(vis(e)&&!isTitle(e))nodes.push(e);}}
   nodes=[...new Set(nodes)];if(!nodes.length)return null;
   const title=document.querySelector(titleSel),tr=title?title.getBoundingClientRect():null;
   const score=e=>{const r=e.getBoundingClientRect(),hint=((typeof e.className==='string'?e.className:'')+' '+(e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||'')).toLowerCase();let s=r.width*r.height;
    if(tr&&r.top>=tr.bottom-6)s+=1e9;if(/se-module-text|se-text-paragraph/.test(hint))s+=4e8;if(/se-component.*se-text|se-section-text/.test(hint))s+=2e8;if(/placeholder/.test(hint))s+=1e8;return s;};
   nodes.sort((a,b)=>score(b)-score(a));let e=nodes[0];
   if(arguments[0]){try{e.scrollIntoView({block:'center',inline:'nearest'});}catch(x){}try{e.click();}catch(x){}try{e.focus();}catch(x){}}
   return e;
  """,bool(activate))
 except Exception:return None

def _native_body_focus_ok(d,root):
 try:
  return bool(d.execute_script("""
   const root=arguments[0],a=document.activeElement,s=window.getSelection();
   if(a){const h=((a.id||'')+' '+(a.name||'')+' '+(typeof a.className==='string'?a.className:'')).toLowerCase();if(a.tagName==='IFRAME'&&/input[_-]?buffer|inputbuffer|ime/.test(h))return true;}
   if(a&&(a===root||root.contains(a)))return true;
   if(s&&s.rangeCount&&s.anchorNode){const n=s.anchorNode.nodeType===1?s.anchorNode:s.anchorNode.parentElement;if(n&&(n===root||root.contains(n)))return true;}
   return false;
  """,root))
 except Exception:return False

def _nested_body_candidate_here(d):
 """Find a real article-body leaf in the current child-frame document."""
 return d.execute_script("""
  const fe=window.frameElement;
  const frameHint=fe?[(fe.id||''),(fe.name||''),(fe.className||''),(fe.getAttribute('src')||''),(fe.getAttribute('title')||''),(fe.getAttribute('aria-label')||'')].join(' ').toLowerCase():'';
  if(/input[_-]?buffer|inputbuffer|clipboard|paste[_-]?(buffer|area|frame)?|dummy|hidden[_-]?frame|accessibility[_-]?frame|ime[_-]?(buffer|frame)/i.test(frameHint))return null;
  const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle';
  const vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>=20&&r.height>=8;};
  const isTitle=e=>!!e.closest(titleSel)||/제목|title/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||''));
  const bad=e=>/태그|검색|댓글|링크|주소|input[_-]?buffer|clipboard|paste|tag|search|comment/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('name')||'')+' '+(typeof e.className==='string'?e.className:''));
  const deep=(root,out)=>{for(const e of root.querySelectorAll('*')){if(e.matches('[contenteditable=true],[role=textbox],textarea'))out.push(e);if(e.shadowRoot)deep(e.shadowRoot,out);}};
  let nodes=[];deep(document,nodes);nodes=[...new Set(nodes)].filter(e=>vis(e)&&!isTitle(e)&&!bad(e));
  if(!nodes.length){
   const shells=[...document.querySelectorAll('.se-section-text,.se-component.se-text,.se-content,.se-main-container,.se-writing-area,.se-editor,[class*=editor-body],[class*=writing-area]')].filter(e=>vis(e)&&!isTitle(e));
   if(shells.length){shells.sort((a,b)=>{const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();return br.width*br.height-ar.width*ar.height;});try{shells[0].focus();shells[0].click();}catch(x){}}
   return null;
  }
  const score=e=>{const r=e.getBoundingClientRect(),cls=typeof e.className==='string'?e.className:'',hint=((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||'')+' '+cls).toLowerCase();let s=r.width*r.height;if(e.getAttribute('contenteditable')==='true')s+=1e8;if(/se-text-paragraph|se-module-text|se-section-text|본문|내용/.test(hint))s+=5e7;return s;};
  nodes.sort((a,b)=>score(b)-score(a));
  return nodes[0];
 """)

def _find_body_in_child_frames(d,depth=3,path=None):
 """Descend only plausible editor frames and stay there on success."""
 if depth<=0:return None
 path=list(path or [])
 try:frames=d.find_elements(By.CSS_SELECTOR,"iframe,frame")
 except Exception:frames=[]
 for idx,fr in enumerate(frames):
  switched=False
  try:
   if not _visible(fr) or _frame_is_editor_auxiliary(fr):continue
   ident=fr.get_attribute("id") or fr.get_attribute("name") or str(idx)
   d.switch_to.frame(fr);switched=True
   candidate=_nested_body_candidate_here(d)
   if candidate is not None and _visible(candidate):
    log("네이버 SmartEditor 중첩 본문 프레임 확인: "+"/".join(path+[ident]))
    return candidate
   nested=_find_body_in_child_frames(d,depth-1,path+[ident])
   if nested is not None:return nested
   d.switch_to.parent_frame();switched=False
  except Exception:
   if switched:
    try:d.switch_to.parent_frame()
    except Exception:pass
 return None

def _body_root(d,timeout=20):
 """Find the actual body editor across current SmartEditor DOM variants.

 The body paragraph can be created only after its shell is clicked. Search is
 therefore retry-based and never lets one early miss abort WebDriverWait.
 """
 end=time.time()+max(1.0,float(timeout));last="";loops=0;tab_tried=False
 while time.time()<end:
  loops+=1
  try:
   e=d.execute_script("""
    const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle';
    const visible=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>=20&&r.height>=8;};
    const isTitle=e=>!!e.closest(titleSel)||/제목|title/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||''));
    const deep=(root,sel,out)=>{for(const e of root.querySelectorAll('*')){if(e.matches(sel))out.push(e);if(e.shadowRoot)deep(e.shadowRoot,sel,out);}};
    let all=[];deep(document,arguments[0],all);
    const bad=e=>/태그|검색|댓글|링크|주소|tag|search|comment/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('name')||''));
    const nodes=[...new Set(all)].filter(e=>visible(e)&&!isTitle(e)&&!bad(e));
    if(!nodes.length)return null;
    const title=document.querySelector(titleSel),tr=title?title.getBoundingClientRect():null;
    const score=e=>{
     const cls=typeof e.className==='string'?e.className:'';
     const hint=((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||'')+' '+cls).toLowerCase();
     let s=0;if(e.getAttribute('contenteditable')==='true')s+=50;
     if((e.getAttribute('role')||'').toLowerCase()==='textbox')s+=40;
     if(e.tagName==='TEXTAREA')s+=35;
     if(/본문|내용|text-paragraph|se-module-text/.test(hint))s+=20;
     if(e.closest('.se-section-text,.se-component.se-text,[class*=se-component][class*=text]'))s+=25;
     if(e.querySelector('[contenteditable=true]'))s-=15;
     const r=e.getBoundingClientRect();if(tr&&r.top>=tr.bottom-5)s+=30;else if(tr)s-=30;
     s+=Math.min(10,(r.width*r.height)/50000);
     s+=Math.min(8,(e.innerText||'').length/100);return s;
    };
    nodes.sort((a,b)=>score(b)-score(a));const best=nodes[0];
    if(best.getAttribute('contenteditable')==='true'||(best.getAttribute('role')||'').toLowerCase()==='textbox'||best.tagName==='TEXTAREA')return best;
    const inner=best.querySelector('[contenteditable=true],[role=textbox],textarea');if(inner&&visible(inner)&&!isTitle(inner)&&!bad(inner))return inner;
    try{best.click();}catch(e){} return null;
   """,BODY_EDITABLE_SELECTORS)
   if e is not None and _visible(e):return e
  except Exception as exc:last=str(exc)
  # A blank new SmartEditor can expose its real paragraph only after the host
  # body shell is clicked. v7.79 scanned child iframes first and therefore
  # selected Naver's transient `input_buffer...` IME frame. Activate the host
  # shell first, then rescan the host on the next loop.
  try:
   activated=bool(d.execute_script("""
    const sels='.se-section-text,.se-component.se-text,.se-content,.se-main-container,.se-writing-area,.se-editor,[class*=editor-body],[class*=writing-area]';
    const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle';
    const vis=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
    const nodes=[...document.querySelectorAll(sels)].filter(e=>vis(e)&&!e.closest(titleSel));
    if(!nodes.length)return false;const title=document.querySelector(titleSel),tr=title?title.getBoundingClientRect():null;
    nodes.sort((a,b)=>{const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();const as=(tr&&ar.top>=tr.bottom?1e9:0)+ar.width*ar.height;const bs=(tr&&br.top>=tr.bottom?1e9:0)+br.width*br.height;return bs-as;});
    const e=nodes[0];e.scrollIntoView({block:'center'});try{e.focus();e.click();}catch(x){}return true;
   """))
   if activated:
    time.sleep(.2)
    if loops<2:continue
  except Exception as exc:last=str(exc)
  # Only after host activation has had a chance to create the paragraph do we
  # inspect child frames. Known input/clipboard helper frames are filtered.
  try:
   nested=_find_body_in_child_frames(d,depth=3)
   if nested is not None and _visible(nested):return nested
  except Exception as exc:
   last=str(exc)
   try:_switch_to_editor_host(d,timeout=3)
   except Exception:pass
  # Account variants can expose the body only through sequential keyboard
  # focus. Start from the verified title and inspect active/selection elements.
  if loops>=3 and not tab_tried:
   tab_tried=True
   try:
    title_el=next((z for z in d.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(z)),None)
    if title_el:
     ActionChains(d).click(title_el).send_keys(Keys.END).perform()
     for _ in range(10):
      ActionChains(d).send_keys(Keys.TAB).perform();time.sleep(.12)
      active=d.execute_script("""
       const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle';
       const bad=e=>!e||!!e.closest(titleSel)||/제목|title|태그|검색|댓글|tag|search|comment/i.test((e.getAttribute('data-placeholder')||'')+' '+(e.getAttribute('aria-label')||''));
       let e=document.activeElement;const s=window.getSelection();
       if((!e||e===document.body)&&s&&s.anchorNode)e=s.anchorNode.nodeType===1?s.anchorNode:s.anchorNode.parentElement;
       if(e)e=e.closest('[contenteditable=true],[role=textbox],textarea')||e.querySelector&&e.querySelector('[contenteditable=true],[role=textbox],textarea');
       if(bad(e))return null;const r=e.getBoundingClientRect(),st=getComputedStyle(e);
       return st.display!=='none'&&st.visibility!=='hidden'&&r.width>0?e:null;
      """)
      if active is not None and _visible(active):return active
   except Exception as exc:last=str(exc)
  time.sleep(.15)
 # SmartEditor 3/ONE lazy-body fallback: a second contenteditable may never be
 # present until the actual text component is clicked. Accept the native body
 # shell when the click establishes a body selection or Naver IME input buffer.
 try:
  native=_smarteditor3_native_body(d,activate=True)
  if native is not None:
   time.sleep(.12)
   if _native_body_focus_ok(d,native) or _body_input_buffer_active(d):
    log("네이버 SmartEditor3 네이티브 본문 셸 활성화: contenteditable 생성 대기 없이 진행")
    return native
 except Exception as exc:last=str(exc)
 try:
  inventory=d.execute_script("""
   const vis=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0;};
   const els=[...document.querySelectorAll('[contenteditable],[role=textbox],textarea,iframe')].filter(vis);
   return {contenteditable:els.filter(e=>e.hasAttribute('contenteditable')).length,role_textbox:els.filter(e=>(e.getAttribute('role')||'')==='textbox').length,
    textarea:els.filter(e=>e.tagName==='TEXTAREA').length,iframe:els.filter(e=>e.tagName==='IFRAME').length,
    samples:els.slice(0,12).map(e=>({tag:e.tagName,cls:String(e.className||'').slice(0,100),ce:e.getAttribute('contenteditable'),role:e.getAttribute('role'),placeholder:e.getAttribute('data-placeholder')||e.getAttribute('placeholder')||''}))};
  """) or {}
 except Exception:inventory={}
 raise RuntimeError("SmartEditor 실제 본문 입력칸을 찾지 못했습니다(제목 영역은 보호됨) · DOM="+repr(inventory)[:700]+(" · "+last[:160] if last else ""))

def _focus_body_end(d):
 """Restore a collapsed caret in SmartEditor body, including lazy SE3 shells."""
 root=_body_root(d)
 try:
  editable=bool(d.execute_script("return arguments[0].getAttribute('contenteditable')==='true'||arguments[0].getAttribute('role')==='textbox'||arguments[0].tagName==='TEXTAREA'||!!arguments[0].querySelector('[contenteditable=true],[role=textbox],textarea');",root))
 except Exception:editable=False
 if editable:
  try:
   ok=d.execute_script("""
    const root=arguments[0];
    const cand=[...root.querySelectorAll('[contenteditable=true],[role=textbox],textarea')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;});
    const target=(root.matches&&root.matches('[contenteditable=true],[role=textbox],textarea'))?root:(cand.length?cand[cand.length-1]:root);
    try{target.focus();}catch(e){}
    const sel=window.getSelection();const range=document.createRange();
    range.selectNodeContents(target);range.collapse(false);sel.removeAllRanges();sel.addRange(range);
    return !!(document.activeElement===target || target.contains(document.activeElement) || sel.rangeCount);
   """,root)
   if ok:return root
  except Exception:pass
 # SmartEditor3 lazy shell: real click is the authoritative focus operation.
 try:
  ActionChains(d).move_to_element(root).click().perform();time.sleep(.08)
 except Exception:
  try:d.execute_script("arguments[0].scrollIntoView({block:'center'});arguments[0].click();",root);time.sleep(.08)
  except Exception:pass
 if _native_body_focus_ok(d,root) or _body_input_buffer_active(d):return root
 native=_smarteditor3_native_body(d,activate=True)
 if native is not None and (_native_body_focus_ok(d,native) or _body_input_buffer_active(d)):return native
 raise RuntimeError("SmartEditor3 본문 입력 포커스 복구 실패")

def _clear_title_field(d,e):
 """Clear SmartEditor title without WebElement.clear().

 SmartEditor title is a contenteditable shell, not a normal input. Selenium's
 clear() raises InvalidElementState on several current Naver editor builds,
 which previously made the clipboard fallback abort before any text was written.
 """
 try:
  ActionChains(d).move_to_element(e).click().key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform();time.sleep(.05)
  return True
 except Exception:
  try:
   e.click();ActionChains(d).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.BACKSPACE).perform();time.sleep(.05);return True
  except Exception:return False

def _insert_text_cdp(d,text):
 """Fast no-clipboard fallback for focused plain-text fields."""
 try:
  d.execute_cdp_cmd('Input.insertText',{'text':str(text or '')});return True
 except Exception:return False

def _paste_plain_text_resilient(d,text):
 """One-shot plain text input: clipboard -> CDP -> Selenium, never clear()."""
 if _set_windows_clipboard_text(text):
  try:
   ActionChains(d).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform();return 'clipboard'
  except Exception:pass
 if _insert_text_cdp(d,text):return 'cdp-insertText'
 try:
  ActionChains(d).send_keys(str(text or '')).perform();return 'selenium-send_keys'
 except Exception:return ''

def title(d,text):
 """Paste title independently with retry and no-clipboard recovery.

 The write is verified from the actual SmartEditor title DOM. If a method fails,
 the title is cleared again before the next method so retries cannot duplicate it.
 """
 e=WebDriverWait(d,20).until(lambda x:next((z for z in x.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(z)),False))
 want=_compact_text(text);methods=[]
 for attempt in range(3):
  if not _clear_title_field(d,e):
   try:e=WebDriverWait(d,4).until(lambda x:next((z for z in x.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(z)),False))
   except Exception:pass
  method=_paste_plain_text_resilient(d,text);methods.append(method or 'failed')
  end=time.time()+2.2
  while time.time()<end:
   got=_compact_text(_editor_title_text(d))
   if not want or got==want or want in got:
    log('SmartEditor3 제목 입력 확인: '+method+f' · {len(want)}자');return
   time.sleep(.08)
  # reacquire the title shell because Naver can remount it after the first click
  try:e=WebDriverWait(d,3).until(lambda x:next((z for z in x.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(z)),False))
  except Exception:pass
 raise RuntimeError('제목 입력 실패: clipboard/CDP/send_keys 3경로 검증 실패 · methods='+repr(methods))

def _enter_mainframe_after_title(d,timeout=12):
 """Hard-reset frame context after title input, then re-enter SmartEditor host.

 v7.81 intentionally follows the safest Selenium sequence for Naver:
 default_content() -> explicit mainFrame wait/switch when present -> generic
 editor-host fallback for accounts that no longer expose a fixed mainFrame.
 This prevents a title contenteditable, stale child iframe, or IME helper frame
 from retaining the keyboard focus when body writing begins.
 """
 _ensure_one_valid_window(d)
 try:d.switch_to.default_content()
 except Exception:pass
 deadline=time.time()+max(2.0,float(timeout));last=""
 # Prefer Naver's canonical mainFrame, but do not make it mandatory because
 # some current account/editor variants render SmartEditor in another frame.
 main_locs=[
  (By.CSS_SELECTOR,"iframe#mainFrame"),(By.CSS_SELECTOR,"frame#mainFrame"),
  (By.CSS_SELECTOR,"iframe[name='mainFrame']"),(By.CSS_SELECTOR,"frame[name='mainFrame']"),
 ]
 probe_deadline=min(deadline,time.time()+min(5.0,max(2.0,float(timeout)*.45)))
 while time.time()<probe_deadline:
  for by,sel in main_locs:
   try:
    d.switch_to.default_content()
    fr=next((z for z in d.find_elements(by,sel) if _visible(z)),None)
    if fr is None:continue
    # Explicitly wait until Selenium can switch into this exact frame.
    WebDriverWait(d,min(3.0,max(.5,probe_deadline-time.time()))).until(
     EC.frame_to_be_available_and_switch_to_it((by,sel)))
    WebDriverWait(d,5).until(lambda x:x.execute_script("return document.readyState") in ("interactive","complete"))
    log("네이버 제목 후 프레임 재진입: default_content → mainFrame")
    return "mainFrame"
   except Exception as exc:
    last=str(exc)
    try:d.switch_to.default_content()
    except Exception:pass
  time.sleep(.15)
 # Fallback still begins from top document and discovers the editor host.
 try:
  d.switch_to.default_content()
  found=_switch_to_editor_context(d,timeout=max(2.0,deadline-time.time()),quiet=True)
  log("네이버 제목 후 프레임 재진입: default_content → "+str(found))
  return found
 except Exception as exc:
  raise RuntimeError("제목 입력 후 SmartEditor 프레임 재진입 실패: "+(str(exc) or last))


def _body_shell_here(d):
 """Return a visible body shell below the title in the current host document."""
 try:
  shells=d.find_elements(By.CSS_SELECTOR,
   ".se-section-text,.se-component.se-text,.se-content,.se-main-container,.se-writing-area,.se-editor,[class*='editor-body'],[class*='writing-area']")
 except Exception:return None
 scored=[]
 try:
  title_el=next((z for z in d.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(z)),None)
  title_bottom=(title_el.rect.get('y',0)+title_el.rect.get('height',0)) if title_el else None
 except Exception:title_bottom=None
 for e in shells:
  try:
   if not _visible(e):continue
   r=e.rect or {};w=float(r.get('width') or 0);h=float(r.get('height') or 0);y=float(r.get('y') or 0)
   if w<120 or h<20:continue
   hint=((e.get_attribute('class') or '')+' '+(e.get_attribute('aria-label') or '')+' '+(e.get_attribute('data-placeholder') or '')).lower()
   if re.search(r"title|제목|tag|태그|search|검색|comment|댓글",hint):continue
   score=w*h
   if title_bottom is not None and y>=title_bottom-8:score+=1e9
   if re.search(r"se-section-text|se-component.*text|writing|content",hint):score+=2e8
   scored.append((score,e))
  except Exception:continue
 return max(scored,key=lambda x:x[0])[1] if scored else None


def _focus_is_inside(d,root):
 try:
  return bool(d.execute_script("""
   const root=arguments[0],a=document.activeElement,s=window.getSelection();
   const activeOk=!!a&&(a===root||root.contains(a));
   let selOk=false;try{if(s&&s.rangeCount){const n=s.anchorNode;selOk=!!n&&(n===root||root.contains(n.nodeType===1?n:n.parentElement));}}catch(e){}
   return activeOk||selOk;
  """,root))
 except Exception:return False

def _body_input_buffer_active(d):
 """Accept Naver's tiny IME input_buffer only after a real body shell was clicked."""
 try:
  return bool(d.execute_script("""
   const a=document.activeElement;if(!a)return false;
   const hint=((a.id||'')+' '+(a.name||'')+' '+(a.className||'')).toLowerCase();
   return a.tagName==='IFRAME' && /input[_-]?buffer|ime|clipboard|paste/.test(hint);
  """))
 except Exception:return False


def _reenter_and_focus_body_after_title(d,expected_title="",timeout=30):
 """Perform an explicit frame reset, body-shell click, render wait, and focus proof."""
 _enter_mainframe_after_title(d,timeout=min(12,float(timeout)))
 wanted=_compact_text(expected_title)
 if wanted:
  got=_compact_text(_editor_title_text(d))
  if wanted not in got:
   raise RuntimeError("제목 후 본문 전환 중 제목 검증 실패: 프레임 전환 이후 제목이 유지되지 않음")
 # _editor_title_text() may itself recover the host context; force a clean host
 # entry again before clicking the body shell so keyboard focus cannot stay on title.
 _enter_mainframe_after_title(d,timeout=min(10,float(timeout)))
 try:
  shell=WebDriverWait(d,max(3.0,float(timeout)*.45)).until(lambda x:_body_shell_here(x) or False)
 except Exception:
  shell=None
 if shell is not None:
  try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",shell)
  except Exception:pass
  clicked=False
  try:ActionChains(d).move_to_element(shell).click().perform();clicked=True
  except Exception:
   try:d.execute_script("arguments[0].focus();arguments[0].click();",shell);clicked=True
   except Exception:pass
  if clicked:log("네이버 제목 후 본문 셸 클릭: 실제 입력 영역 활성화")
 # SmartEditor3/ONE can intentionally keep only the title as contenteditable.
 # The body becomes writable through its native text shell + IME buffer, so do
 # not require a second contenteditable node before continuing.
 try:
  native=_smarteditor3_native_body(d,activate=True)
  if native is not None and (_native_body_focus_ok(d,native) or _body_input_buffer_active(d)):
   log("네이버 제목 후 본문 전환: SmartEditor3 네이티브 셸/IME 포커스 확인")
   return native
 except Exception:pass
 # Wait for lazy SmartEditor paragraph creation. _body_root may legitimately
 # enter one real nested body iframe, but v7.80's helper-frame filter remains.
 end=time.time()+max(5.0,float(timeout));root=None;last=""
 while time.time()<end:
  try:
   root=_body_root(d,timeout=min(2.0,max(.6,end-time.time())))
   if root is None or not _visible(root):raise RuntimeError("visible body root 없음")
   # A real mouse click is tried first; then place a collapsed caret at the end.
   try:ActionChains(d).move_to_element(root).click().perform()
   except Exception:
    try:d.execute_script("arguments[0].click();",root)
    except Exception:pass
   root=_focus_body_end(d)
   focus_inside=_focus_is_inside(d,root);input_buffer=_body_input_buffer_active(d)
   if focus_inside or input_buffer:
    try:frame_hint=str(d.execute_script("const f=window.frameElement;return f?((f.id||'')+'|'+(f.name||'')):'host';") or "host")
    except Exception:frame_hint="unknown"
    log("네이버 제목 후 본문 포커스 확인: "+frame_hint+(" · SmartEditor IME input_buffer 허용" if input_buffer else ""))
    return root
   last="본문 click 후 activeElement/selection 포커스 확인 실패"
  except Exception as exc:last=str(exc)
  time.sleep(.2)
 raise RuntimeError("제목 입력 후 본문 활성화 실패: Explicit Wait/클릭/포커스 확인 시간초과 · "+last[:220])


def clear(d,expected_title=""):
 """Clear only the body contenteditable and prove the title was untouched."""
 _body_root(d,timeout=20)
 wanted=_compact_text(expected_title)
 for attempt in range(2):
  root=_focus_body_end(d)
  # Scope the selection to the exact body contenteditable. Ctrl+A on the old
  # `.se-main-container` wrapper could include the document title.
  try:selected=bool(d.execute_script("""const r=arguments[0],s=window.getSelection(),g=document.createRange();g.selectNodeContents(r);s.removeAllRanges();s.addRange(g);r.focus();return true;""",root))
  except Exception:selected=False
  if not selected:raise RuntimeError("본문 한정 선택 실패: 제목 보호를 위해 전체선택을 실행하지 않음")
  ActionChains(d).send_keys(Keys.DELETE).perform()
  time.sleep(.25)
  basefmt(d);_focus_body_end(d)
  if wanted and wanted not in _compact_text(_editor_title_text(d)):
   raise RuntimeError("본문 초기화 중 제목 손상 감지: 자동 재작성과 다음 상품 이동을 중단")
  if not _compact_text(_editor_text(d)):return
  root=_focus_body_end(d)
  try:selected=bool(d.execute_script("""const r=arguments[0],s=window.getSelection(),g=document.createRange();g.selectNodeContents(r);s.removeAllRanges();s.addRange(g);r.focus();return true;""",root))
  except Exception:selected=False
  if not selected:raise RuntimeError("본문 재선택 실패: 제목 보호를 위해 전체선택을 실행하지 않음")
  ActionChains(d).send_keys(Keys.DELETE).perform()
  time.sleep(.25)
 raise RuntimeError("본문 초기화 실패: 이전 글이 남아 있어 중복 작성 위험이 있으므로 중단")

def _body_root_text(d,root=None):
 try:
  root=root or _body_root(d,timeout=20)
  text=str(d.execute_script("return arguments[0].innerText||arguments[0].textContent||'';",root) or "")
  # Empty-editor hints can be materialized as text in a few SmartEditor builds.
  text=re.sub(r"(?i)본문을?\s*입력(?:해\s*주세요|하세요)?|내용을?\s*입력(?:해\s*주세요|하세요)?","",text)
  return text
 except Exception:return ""

def _prepare_body_for_write(d,expected_title=""):
 """Activate the body and skip destructive work when a new editor is blank."""
 root=_body_root(d,timeout=float(settings().get("blog_editor_ready_timeout_sec",50)))
 existing=_compact_text(_body_root_text(d,root))
 cleared=False
 if existing:
  # Only a genuinely non-empty resumed body needs deletion. A normal new post
  # goes straight to writing, avoiding the empty-component DELETE regression.
  clear(d,expected_title);cleared=True;root=_body_root(d,timeout=20)
 _focus_body_end(d)
 wanted=_compact_text(expected_title)
 if wanted and wanted not in _compact_text(_editor_title_text(d)):
  raise RuntimeError("본문 준비 중 제목이 유지되지 않음")
 return {"body_was_nonempty":bool(existing),"cleared":cleared,"ready":True}

def _visible_body_targets_physical(d):
 """Visible SmartEditor text surfaces ordered from specific paragraph to canvas."""
 sels=[
  '.se-component.se-text .se-text-paragraph',
  '.se-section-text .se-text-paragraph',
  '.se-component.se-text .se-module-text',
  '.se-section-text .se-module-text',
  '.se-component.se-text',
  '.se-section-text',
  '.se-main-container',
  '.se-content'
 ]
 out=[];seen=set()
 for css in sels:
  try:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    try:
     if not _visible(e):continue
     key=getattr(e,'id',None) or (css,str(e.rect))
     if key in seen:continue
     seen.add(key);out.append(e)
    except Exception:pass
  except Exception:pass
 return out


def _native_line_count_modern(d,text):
 needle=_compact_text(text)
 if not needle:return 0
 try:
  return int(d.execute_script(r"""
   const want=arguments[0].replace(/\s+/g,'');
   const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle,[class*=documentTitle]';
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
   let n=0;
   for(const e of document.querySelectorAll('.se-text-paragraph,.se-module-text p,.se-component.se-text p,[contenteditable=true]')){
    if(!vis(e)||e.closest(titleSel))continue;
    const t=(e.innerText||e.textContent||'').replace(/\s+/g,'');if(t.includes(want))n++;
   }
   return n;
  """,needle) or 0)
 except Exception:return 0


def _activate_body_physical(d):
 """Click SmartEditor exactly like a user; Naver IME input_buffer focus is valid."""
 last={}
 for e in _visible_body_targets_physical(d):
  try:
   # Ignore giant editor wrappers until specific text surfaces were attempted.
   cls=str(e.get_attribute('class') or '')
   try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",e)
   except Exception:pass
   try:ActionChains(d).move_to_element(e).click().perform()
   except Exception:
    try:e.click()
    except Exception:continue
   time.sleep(.12)
   try:
    last=d.execute_script(r"""
     const a=document.activeElement,s=window.getSelection();let n=s&&s.anchorNode,el=n&&(n.nodeType===1?n:n.parentElement);
     const h=a?((a.id||'')+' '+(a.name||'')+' '+(typeof a.className==='string'?a.className:'')) .toLowerCase():'';
     return {active_tag:a&&a.tagName||'',active_id:a&&a.id||'',active_cls:a&&a.className||'',
       input_buffer:!!(a&&a.tagName==='IFRAME'&&/input[_-]?buffer|inputbuffer|ime/.test(h)),
       selection_in_body:!!(el&&el.closest&&el.closest('.se-component.se-text,.se-section-text,.se-text-paragraph,.se-module-text'))};
    """) or {}
   except Exception:last={}
   if last.get('input_buffer') or last.get('selection_in_body') or _focus_is_inside(d,e):return last
  except Exception:
   continue
 # Empty SmartEditor: click a safe canvas point below the title. This mirrors a
 # human click and is more reliable than waiting for a second contenteditable.
 try:
  root=next((x for x in d.find_elements(By.CSS_SELECTOR,'.se-main-container,.se-content') if _visible(x)),None)
  if root is not None:
   w=float((root.size or {}).get('width') or 400);h=float((root.size or {}).get('height') or 600)
   # Use the same positive in-canvas offset as the long-lived v7.59 exact engine.
   # This avoids title/toolbar hits while still behaving as a physical user click.
   xoff=max(8,min(80,int(w//4)));yoff=max(120,min(420,int(h//2)))
   ActionChains(d).move_to_element_with_offset(root,xoff,yoff).click().perform();time.sleep(.18)
   return {'fallback':'body_canvas','xoff':int(xoff),'yoff':int(yoff)}
 except Exception as exc:last={'fallback_error':str(exc)}
 raise RuntimeError('SmartEditor 본문 실제 클릭 실패: '+repr(last)[:700])


def _configure_win_clipboard_api():
 """Configure 64-bit-safe Win32 clipboard signatures once."""
 if os.name!='nt':return None,None
 from ctypes import wintypes
 user32=ctypes.windll.user32;kernel32=ctypes.windll.kernel32
 user32.OpenClipboard.argtypes=[wintypes.HWND];user32.OpenClipboard.restype=wintypes.BOOL
 user32.CloseClipboard.argtypes=[];user32.CloseClipboard.restype=wintypes.BOOL
 user32.EmptyClipboard.argtypes=[];user32.EmptyClipboard.restype=wintypes.BOOL
 user32.RegisterClipboardFormatW.argtypes=[wintypes.LPCWSTR];user32.RegisterClipboardFormatW.restype=wintypes.UINT
 user32.SetClipboardData.argtypes=[wintypes.UINT,ctypes.c_void_p];user32.SetClipboardData.restype=ctypes.c_void_p
 user32.IsClipboardFormatAvailable.argtypes=[wintypes.UINT];user32.IsClipboardFormatAvailable.restype=wintypes.BOOL
 user32.GetClipboardData.argtypes=[wintypes.UINT];user32.GetClipboardData.restype=ctypes.c_void_p
 kernel32.GlobalAlloc.argtypes=[wintypes.UINT,ctypes.c_size_t];kernel32.GlobalAlloc.restype=ctypes.c_void_p
 kernel32.GlobalLock.argtypes=[ctypes.c_void_p];kernel32.GlobalLock.restype=ctypes.c_void_p
 kernel32.GlobalUnlock.argtypes=[ctypes.c_void_p];kernel32.GlobalUnlock.restype=wintypes.BOOL
 kernel32.GlobalFree.argtypes=[ctypes.c_void_p];kernel32.GlobalFree.restype=ctypes.c_void_p
 kernel32.GlobalSize.argtypes=[ctypes.c_void_p];kernel32.GlobalSize.restype=ctypes.c_size_t
 return user32,kernel32


def _clipboard_open_retry(user32,timeout=3.5):
 """Open the Windows clipboard with bounded retries."""
 end=time.time()+max(.4,float(timeout));sleep=.025
 while time.time()<end:
  try:
   if user32.OpenClipboard(None):return True
  except Exception:pass
  time.sleep(sleep);sleep=min(.15,sleep*1.35)
 return False


def _clipboard_put_formats(formats,timeout=5.0):
 """Atomically publish clipboard formats with correct 64-bit HGLOBAL ownership."""
 if os.name!='nt':return False
 user32,kernel32=_configure_win_clipboard_api();end=time.time()+max(1.0,float(timeout));last=''
 while time.time()<end:
  if not _clipboard_open_retry(user32,timeout=min(1.2,max(.2,end-time.time()))):
   last='OpenClipboard timeout';continue
  handles=[];transferred=[]
  try:
   if not user32.EmptyClipboard():raise RuntimeError('EmptyClipboard failed')
   for fmt,data in formats:
    raw=bytes(data);h=kernel32.GlobalAlloc(0x0002,len(raw))
    if not h:raise RuntimeError('GlobalAlloc failed')
    handles.append(h);ptr=kernel32.GlobalLock(h)
    if not ptr:raise RuntimeError('GlobalLock failed')
    try:ctypes.memmove(ptr,raw,len(raw))
    finally:kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(int(fmt),h):raise RuntimeError(f'SetClipboardData failed fmt={fmt}')
    transferred.append(h)
   return True
  except Exception as exc:last=type(exc).__name__+': '+str(exc)
  finally:
   try:user32.CloseClipboard()
   except Exception:pass
   for h in handles:
    if h not in transferred:
     try:kernel32.GlobalFree(h)
     except Exception:pass
  time.sleep(.05)
 log('Windows clipboard publish 실패: '+last);return False


def _set_windows_clipboard_text(text):
 """Set Unicode text with 64-bit-safe clipboard handles and verify it exists."""
 if os.name!='nt':return False
 try:
  user32,_=_configure_win_clipboard_api();CF_UNICODETEXT=13
  ok=_clipboard_put_formats([(CF_UNICODETEXT,(str(text or '')+'\0').encode('utf-16-le'))],timeout=6.0)
  return bool(ok and user32.IsClipboardFormatAvailable(CF_UNICODETEXT))
 except Exception as exc:
  log('Unicode clipboard 설정 예외: '+type(exc).__name__+': '+str(exc));return False


def _set_windows_clipboard_rich(html_fragment, plain_text):
 """Put verified CF_HTML + Unicode text on the Windows clipboard."""
 if os.name!='nt':return False
 try:
  user32,_=_configure_win_clipboard_api();CF_UNICODETEXT=13
  cf_html=int(user32.RegisterClipboardFormatW('HTML Format') or 0)
  if not cf_html:raise RuntimeError('RegisterClipboardFormatW failed')
  frag=str(html_fragment or '');prefix='<html><body><!--StartFragment-->';suffix='<!--EndFragment--></body></html>'
  header=('Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n')
  dummy=header.format(0,0,0,0).encode('ascii');pb=prefix.encode('utf-8');fb=frag.encode('utf-8');sb=suffix.encode('utf-8')
  sh=len(dummy);sf=sh+len(pb);ef=sf+len(fb);eh=ef+len(sb)
  html_payload=header.format(sh,eh,sf,ef).encode('ascii')+pb+fb+sb+b'\0'
  text_payload=(str(plain_text or '')+'\0').encode('utf-16-le')
  ok=_clipboard_put_formats([(CF_UNICODETEXT,text_payload),(cf_html,html_payload)],timeout=7.0)
  return bool(ok and user32.IsClipboardFormatAvailable(CF_UNICODETEXT) and user32.IsClipboardFormatAvailable(cf_html))
 except Exception as exc:
  log('Rich clipboard 준비 예외: '+type(exc).__name__+': '+str(exc));return False


def clipboard_preflight():
 """Public UI preflight: prove TEXT and HTML clipboard can be published before opening Naver."""
 if os.name!='nt':return {'ok':False,'message':'Windows 전용 클립보드 점검입니다.'}
 token='NAVERBLOG_CLIPBOARD_TEST_'+str(int(time.time()*1000))
 try:
  text_ok=_set_windows_clipboard_text(token);rich_ok=_set_windows_clipboard_rich('<p><b>'+token+'</b></p>',token)
  return {'ok':bool(text_ok and rich_ok),'text':bool(text_ok),'rich':bool(rich_ok),'message':('클립보드 TEXT/HTML 준비 정상' if text_ok and rich_ok else f'클립보드 준비 실패 · TEXT={text_ok} HTML={rich_ok}')}
 except Exception as exc:return {'ok':False,'message':type(exc).__name__+': '+str(exc)}

def _html_escape(text):
 import html as _html
 return _html.escape(str(text or ''),quote=False)


def _block_lines_for_clipboard(post):
 """Create one SmartEditor3 paste transaction with stable image marker slots."""
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 normal_style='text-align:center; margin:0; white-space:pre-wrap;'
 emph_style=f'text-align:center; margin:0; white-space:pre-wrap; font-weight:700; background-color:{bg};'
 html_parts=[];plain=[];image_no=0
 def add_line(text,emphasis=False,blank_after=False):
  t=str(text or '')
  style=emph_style if emphasis else normal_style
  html_parts.append(f'<p style="{style}">{_html_escape(t) if t else "<br>"}</p>')
  plain.append(t)
  if blank_after:
   html_parts.append(f'<p style="{normal_style}"><br></p>');plain.append('')
 for b in post.get('blocks',[]):
  typ=b.get('type')
  if typ=='disclosure':
   for x in b.get('lines') or COUPANG_DISCLOSURE_LINES:add_line(x)
   add_line('')
  elif typ=='sharelink':
   url=str(b.get('url') or '').strip()
   if url:add_line(url,blank_after=True)
  elif typ in ('image','price_compare_image'):
   image_no+=1;add_line(f'[[IMG{image_no}]]',blank_after=True)
  elif typ=='heading':add_line(b.get('text',''),emphasis=True,blank_after=True)
  elif typ=='check':add_line(b.get('text',''),emphasis=True)
  elif typ=='paragraph':
   for x in b.get('lines') or []:add_line(x)
   add_line('')
 # remove only redundant trailing blank paragraphs, preserving content order
 while len(plain)>1 and plain[-1]=='':
  plain.pop()
  if html_parts:html_parts.pop()
 return ''.join(html_parts),'\r\n'.join(plain),image_no


def _smarteditor_focus_snapshot(d):
 """Small diagnostic proving where keyboard/paste input will land."""
 try:
  return d.execute_script(r"""
   const a=document.activeElement,s=window.getSelection();let n=s&&s.anchorNode;
   let e=n&&(n.nodeType===1?n:n.parentElement);
   const info=x=>x?{tag:x.tagName||'',id:x.id||'',cls:String(x.className||'').slice(0,160),ce:x.getAttribute&&x.getAttribute('contenteditable'),role:x.getAttribute&&x.getAttribute('role')}:{tag:'',id:'',cls:'',ce:null,role:null};
   let bodySel=false;try{bodySel=!!(e&&e.closest&&e.closest('.se-component.se-text,.se-section-text,.se-main-container,.se-content'));}catch(x){}
   return {active:info(a),selection:info(e),selection_in_body:bodySel,collapsed:!!(s&&s.rangeCount&&s.isCollapsed)};
  """) or {}
 except Exception:return {}


def _hard_focus_body_for_paste(d,timeout=12):
 """Physically focus the Naver body canvas before a single bulk paste.

 Unlike the old helper-frame heuristic, this routine never treats input_buffer
 as proof by itself. It clicks a visible body text component/paragraph first,
 then a calculated point BELOW the title inside .se-main-container, and finally
 rechecks the real body paragraph created by SmartEditor.
 """
 _enter_mainframe_after_title(d,timeout=min(10,float(timeout)))
 end=time.time()+max(4.0,float(timeout));last={}
 while time.time()<end:
  # 1) Existing real body text surface: best possible target.
  for css in ('.se-component.se-text .se-text-paragraph','.se-section-text .se-text-paragraph','.se-component.se-text .se-module-text','.se-section-text .se-module-text','.se-component.se-text','.se-section-text'):
   try:
    e=next((x for x in d.find_elements(By.CSS_SELECTOR,css) if _visible(x)),None)
    if e is None:continue
    try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",e)
    except Exception:pass
    try:ActionChains(d).move_to_element(e).click().perform()
    except Exception:
     try:e.click()
     except Exception:continue
    time.sleep(.18)
    # SmartEditor may materialize a contenteditable paragraph only AFTER click.
    real=next((x for x in d.find_elements(By.CSS_SELECTOR,'.se-component.se-text [contenteditable=true],.se-section-text [contenteditable=true],p.se-text-paragraph[contenteditable=true]') if _visible(x)),None)
    if real is not None:
     try:ActionChains(d).move_to_element(real).click().send_keys(Keys.END).perform()
     except Exception:
      try:d.execute_script("arguments[0].focus();",real)
      except Exception:pass
     time.sleep(.08)
     return real,_smarteditor_focus_snapshot(d)
    snap=_smarteditor_focus_snapshot(d);last=snap
    if snap.get('selection_in_body'):return e,snap
   except Exception as exc:last={'specific_error':str(exc)}

  # 2) Empty editor: click a physical point safely below title, inside canvas.
  try:
   root=next((x for x in d.find_elements(By.CSS_SELECTOR,'.se-main-container,.se-content') if _visible(x)),None)
   if root is not None:
    rr=root.rect or {};w=max(200.0,float(rr.get('width') or 600));h=max(240.0,float(rr.get('height') or 700))
    title_el=next((x for x in d.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(x)),None)
    # Selenium offsets are relative to the element center in W3C actions.
    target_y=min(h-70.0,max(100.0,((float((title_el.rect or {}).get('y') or 0)+float((title_el.rect or {}).get('height') or 0))-float(rr.get('y') or 0))+90.0 if title_el else 170.0))
    dy=target_y-h/2.0
    try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",root)
    except Exception:pass
    ActionChains(d).move_to_element(root).move_by_offset(0,int(dy)).click().perform();time.sleep(.25)
    real=next((x for x in d.find_elements(By.CSS_SELECTOR,'.se-component.se-text [contenteditable=true],.se-section-text [contenteditable=true],p.se-text-paragraph[contenteditable=true]') if _visible(x)),None)
    if real is not None:
     try:ActionChains(d).move_to_element(real).click().send_keys(Keys.END).perform()
     except Exception:pass
     return real,_smarteditor_focus_snapshot(d)
    snap=_smarteditor_focus_snapshot(d);last=snap
    if snap.get('selection_in_body'):return root,snap
  except Exception as exc:last={'canvas_error':str(exc)}
  time.sleep(.2)
 raise RuntimeError('SmartEditor3 본문 실제 포커스 확보 실패 · '+repr(last)[:700])


def _browser_native_copy_html(d,html_fragment,plain_text):
    """Deprecated in v8.08.11.

    Never opens a helper tab. The production writer uses the v7.64-style
    direct body transaction instead, so rich-copy is deliberately disabled.
    """
    log("Rich-copy helper disabled: single Chrome / single tab policy")
    return False

def _win_phys_click_and_paste_body(d):
 """Windows-level mouse click + Ctrl+V into SmartEditor body.

 Selenium can leave keyboard focus on Naver's transient input_buffer iframe even
 after a DOM click.  This path deliberately uses the OS input queue so Chrome
 receives exactly the same click/paste sequence as a human user.  It is only
 used on Windows and only after a rich clipboard payload has already been
 prepared.
 """
 if os.name!='nt':return False,{'reason':'not-windows'}
 try:
  _enter_mainframe_after_title(d,timeout=8)
  # Resolve a stable viewport point inside the editor, below the title.
  pos=d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>40&&r.height>40&&s.display!=='none'&&s.visibility!=='hidden';};
   const roots=[...document.querySelectorAll('.se-main-container,.se-content')].filter(vis);
   const root=roots[0]; if(!root)return null;
   const rr=root.getBoundingClientRect();
   let sel=window.getSelection(),anchor=sel&&sel.rangeCount?sel.anchorNode:null;
   let ae=anchor?(anchor.nodeType===1?anchor:anchor.parentElement):null;
   let target=(ae&&ae.closest&&ae.closest('.se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph'))||
              [...document.querySelectorAll('.se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].find(vis);
   const title=[...document.querySelectorAll(".se-title-text,.se-section-documentTitle,[contenteditable='true'][data-placeholder*='제목'],[contenteditable='true'][aria-label*='제목']")].find(vis);
   let x,y,tr=null;
   if(target&&vis(target)){
     tr=target.getBoundingClientRect();x=tr.left+Math.min(Math.max(18,tr.width*.35),Math.max(18,tr.width-18));y=tr.top+Math.min(Math.max(12,tr.height*.55),Math.max(12,tr.height-8));
   }else{
     y=rr.top+Math.min(Math.max(170,(title?title.getBoundingClientRect().bottom-rr.top+110:190)),Math.max(190,rr.height-90));
     x=rr.left+Math.min(Math.max(220,rr.width/2),Math.max(220,rr.width-120));
   }
   const chromeY=(window.outerHeight-window.innerHeight);
   return {x:Math.round(window.screenX+x),y:Math.round(window.screenY+chromeY+y),vx:Math.round(x),vy:Math.round(y),target:tr?{left:tr.left,top:tr.top,width:tr.width,height:tr.height}:null,root:{left:rr.left,top:rr.top,width:rr.width,height:rr.height},chromeY};
  """)
  if not pos:return False,{'reason':'no-body-root'}
  import ctypes
  user32=ctypes.windll.user32
  # Bring Chrome to foreground as best effort.
  try:
   hwnd=int(d.execute_script('return window.__selenium_hwnd||0') or 0)
   if hwnd:user32.SetForegroundWindow(hwnd)
  except Exception:pass
  user32.SetCursorPos(int(pos['x']),int(pos['y']))
  time.sleep(.12)
  MOUSEEVENTF_LEFTDOWN=0x0002;MOUSEEVENTF_LEFTUP=0x0004
  user32.mouse_event(MOUSEEVENTF_LEFTDOWN,0,0,0,0);time.sleep(.04);user32.mouse_event(MOUSEEVENTF_LEFTUP,0,0,0,0)
  time.sleep(.25)
  VK_CONTROL=0x11;VK_V=0x56;KEYEVENTF_KEYUP=0x0002
  user32.keybd_event(VK_CONTROL,0,0,0);time.sleep(.03);user32.keybd_event(VK_V,0,0,0);time.sleep(.03);user32.keybd_event(VK_V,0,KEYEVENTF_KEYUP,0);user32.keybd_event(VK_CONTROL,0,KEYEVENTF_KEYUP,0)
  time.sleep(.35)
  return True,{'point':pos,'focus':_smarteditor_focus_snapshot(d)}
 except Exception as exc:
  return False,{'reason':type(exc).__name__+': '+str(exc)[:400]}


def _execcommand_insert_html(d,html_fragment):
 """Last-resort insertion at the actual SmartEditor paragraph selection."""
 try:
  return bool(d.execute_script(r'''
   const html=arguments[0];
   const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle,[class*=documentTitle]';
   const bad=e=>!e||!!e.closest(titleSel)||/input[_-]?buffer|clipboard|paste|tag|search|comment/i.test(((e.id||'')+' '+(e.className||'')));
   let s=window.getSelection(),node=s&&s.rangeCount?s.anchorNode:null;
   let e=node?(node.nodeType===1?node:node.parentElement):null;
   if(bad(e)||!(e&&e.closest('.se-component.se-text,.se-section-text,.se-content'))){
     e=[...document.querySelectorAll('.se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].find(x=>!bad(x));
   }
   if(!e)return false;
   const host=e.closest('[contenteditable=true]')||e.closest('.se-module-text')||e;
   try{host.focus();}catch(x){}
   s=window.getSelection();const r=document.createRange();r.selectNodeContents(e);r.collapse(false);s.removeAllRanges();s.addRange(r);
   let ok=false;try{ok=document.execCommand('insertHTML',false,html);}catch(x){}
   const eventHost=e.closest('.se-component.se-text')||host;
   try{eventHost.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertFromPaste',data:null}));}catch(x){eventHost.dispatchEvent(new Event('input',{bubbles:true}));}
   return !!ok;
  ''',str(html_fragment or '')))
 except Exception:return False


def _active_input_buffer_frame(d):
 """Return Naver SmartEditor ONE's *currently active* IME/paste iframe.

 Recent diagnostics repeatedly proved that the visible paragraph selection is correct
 while document.activeElement is iframe#input_buffer....  Selenium ActionChains sent
 Ctrl+V to the iframe *element* in the parent document, not to the iframe document
 that actually owns keyboard input.  This helper makes that distinction explicit.
 """
 try:
  return d.execute_script(r"""
   const a=document.activeElement;if(!a||a.tagName!=='IFRAME')return null;
   const h=((a.id||'')+' '+(a.name||'')+' '+(typeof a.className==='string'?a.className:'')).toLowerCase();
   return /input[_-]?buffer|inputbuffer|ime|paste|clipboard/.test(h)?a:null;
  """)
 except Exception:return None


def _input_buffer_snapshot(d):
 """Best-effort diagnostic of the active SmartEditor input_buffer document."""
 frame=_active_input_buffer_frame(d)
 if frame is None:return {'present':False}
 info={'present':True}
 try:
  info.update(d.execute_script("return {id:arguments[0].id||'',name:arguments[0].name||'',cls:String(arguments[0].className||'')};",frame) or {})
 except Exception:pass
 switched=False
 try:
  d.switch_to.frame(frame);switched=True
  try:
   inner=d.execute_script(r"""
    const a=document.activeElement;
    const info=e=>e?{tag:e.tagName||'',id:e.id||'',cls:String(e.className||'').slice(0,120),ce:e.getAttribute&&e.getAttribute('contenteditable'),role:e.getAttribute&&e.getAttribute('role')}:{tag:'',id:'',cls:'',ce:null,role:null};
    const cand=[...document.querySelectorAll('textarea,input,[contenteditable=true],body')].slice(0,12).map(info);
    return {active:info(a),candidates:cand,body_html:(document.body&&document.body.innerHTML||'').slice(0,500)};
   """) or {}
   info.update(inner)
  except Exception as exc:info['inner_error']=type(exc).__name__+': '+str(exc)[:240]
 finally:
  if switched:
   try:d.switch_to.parent_frame()
   except Exception:
    try:_enter_mainframe_after_title(d,timeout=5)
    except Exception:pass
 return info


def _paste_via_active_input_buffer(d):
 """Send Ctrl+V *inside* the active Naver input_buffer iframe.

 The parent editor keeps the visual Selection in p.se-text-paragraph, but the real
 keyboard receiver is an iframe.  Switching into that frame before sending Ctrl+V
 mirrors where Chrome routes a user's keyboard event and fixes the repeated
 `selection_in_body=True + active=IFRAME input_buffer... + zero text growth` failure.
 """
 frame=_active_input_buffer_frame(d)
 if frame is None:return False,{'reason':'active-input-buffer-not-found'}
 diag={'frame':'input_buffer'};switched=False
 try:
  try:
   diag.update(d.execute_script("return {id:arguments[0].id||'',name:arguments[0].name||''};",frame) or {})
  except Exception:pass
  d.switch_to.frame(frame);switched=True
  target=None
  try:
   target=d.switch_to.active_element
  except Exception:target=None
  try:
   # Prefer a real editable/input node when the iframe body exposes one.
   candidates=d.find_elements(By.CSS_SELECTOR,"textarea,input,[contenteditable='true'],body")
   for e in candidates:
    try:
     if e.is_displayed():target=e;break
    except Exception:
     if target is None:target=e
  except Exception:pass
  if target is not None:
   try:target.click()
   except Exception:pass
   try:
    target.send_keys(Keys.CONTROL,'v');diag['sender']='element.send_keys';return True,diag
   except Exception:pass
  ActionChains(d).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform();diag['sender']='ActionChains-in-frame';return True,diag
 except Exception as exc:
  diag['reason']=type(exc).__name__+': '+str(exc)[:320];return False,diag
 finally:
  if switched:
   try:d.switch_to.parent_frame()
   except Exception:
    try:_enter_mainframe_after_title(d,timeout=5)
    except Exception:pass


def _send_text_via_active_input_buffer(d,text):
 """Trusted WebDriver keyboard fallback through Naver's active input_buffer iframe."""
 frame=_active_input_buffer_frame(d)
 if frame is None:return False,{'reason':'active-input-buffer-not-found'}
 diag={'frame':'input_buffer','chars':len(str(text or ''))};switched=False
 try:
  d.switch_to.frame(frame);switched=True
  target=None
  try:target=d.switch_to.active_element
  except Exception:pass
  try:
   for e in d.find_elements(By.CSS_SELECTOR,"textarea,input,[contenteditable='true'],body"):
    try:
     if e.is_displayed():target=e;break
    except Exception:
     if target is None:target=e
  except Exception:pass
  if target is None:return False,{**diag,'reason':'no-input-target'}
  try:target.click()
  except Exception:pass
  # One contiguous send_keys call: no per-line re-click, no caret relocation.
  target.send_keys(str(text or ''));diag['sender']='element.send_keys';return True,diag
 except Exception as exc:
  diag['reason']=type(exc).__name__+': '+str(exc)[:320];return False,diag
 finally:
  if switched:
   try:d.switch_to.parent_frame()
   except Exception:
    try:_enter_mainframe_after_title(d,timeout=5)
    except Exception:pass


def _wait_body_bulk_ack(d,before,want,anchors,timeout=18.0):
 """Verify a bulk body transaction without accepting partial/duplicate content."""
 end=time.time()+max(3.0,float(timeout));last=''
 while time.time()<end:
  now=_compact_text(_editor_text(d));last=now;grew=len(now)-len(before)
  if grew>=max(20,int(len(want)*0.70)) and (not anchors or (anchors[0] in now and anchors[-1] in now)):
   return True,now
  time.sleep(.12)
 return False,last


def _plain_bulk_keyboard_fallback(d,plain,before):
 """Final trusted-key fallback, allowed whenever all paste paths produced *zero* body text.

 First use the active SmartEditor input_buffer (the actual keyboard receiver). If
 Naver does not expose it, send the whole article once to the verified body target.
 Re-clicking between lines is intentionally forbidden to prevent the old mid-line
 caret corruption.
 """
 want=_compact_text(plain);anchors=[_compact_text(x) for x in str(plain or '').splitlines() if _compact_text(x)]
 try:
  target,snap=_hard_focus_body_for_paste(d,timeout=8)
  ok,ib=_send_text_via_active_input_buffer(d,plain)
  if ok:
   ack,now=_wait_body_bulk_ack(d,before,want,anchors,timeout=max(8.0,min(28.0,3.5+len(str(plain or ''))/280.0)))
   if ack:return True,{'focus':snap,'input_buffer':ib,'method':'input-buffer-send_keys'}
   if now!=before:return False,{'focus':snap,'input_buffer':ib,'partial':len(now)-len(before),'method':'input-buffer-send_keys'}
  # Only try the body element itself when the input_buffer route made zero change.
  try:target.click();time.sleep(.08)
  except Exception:pass
  target.send_keys(str(plain or ''))
  ack,now=_wait_body_bulk_ack(d,before,want,anchors,timeout=max(8.0,min(28.0,3.5+len(str(plain or ''))/280.0)))
  return bool(ack),{'focus':snap,'method':'body-element-send_keys','partial':0 if ack else len(now)-len(before)}
 except Exception as exc:return False,{'error':type(exc).__name__+': '+str(exc)}

def _paste_rich_body_once(d,post):
 """Paste the complete article with deterministic SmartEditor ONE recovery.

 v8.08.10 order:
 1) verified Windows CF_HTML -> OS physical click/Ctrl+V,
 2) **switch into active iframe#input_buffer and Ctrl+V there**,
 3) Selenium Ctrl+V on the verified body target,
 4) selection execCommand insertHTML,
 5) if and only if the body is still byte-for-byte unchanged, one trusted bulk
    send_keys transaction through input_buffer/body.

 Any partial body growth aborts immediately so a recovery path can never duplicate
 or interleave article text.
 """
 html_fragment,plain,slot_count=_block_lines_for_clipboard(post)
 before=_compact_text(_editor_text(d));want=_compact_text(plain)
 anchors=[_compact_text(x) for x in plain.splitlines() if _compact_text(x)]
 methods=[]
 rich_clip=_set_windows_clipboard_rich(html_fragment,plain)
 if rich_clip:copy_method='windows-cf-html'
 elif _set_windows_clipboard_text(plain):copy_method='unicode-text'
 else:copy_method='none'
 methods.append('clipboard='+copy_method)
 try:setattr(d,'_nb_clipboard_state',{'method':copy_method,'rich':bool(rich_clip),'preflight':'runtime','input_buffer':_input_buffer_snapshot(d)})
 except Exception:pass

 def verify(method,focus=None,timeout=None):
  ok,now=_wait_body_bulk_ack(d,before,want,anchors,timeout=timeout or max(7.0,min(28.0,3.5+len(plain)/420.0)))
  if ok:return {'plain_chars':len(want),'editor_chars':len(now),'image_slots':slot_count,'method':method,'focus':focus or _smarteditor_focus_snapshot(d)}
  if now!=before:
   raise RuntimeError(f'SmartEditor ONE 본문 부분 반영 감지로 재입력 차단: 기대≈{len(want)}자 실제증가={len(now)-len(before)}자 · method={method} · focus={focus or _smarteditor_focus_snapshot(d)}')
  return None

 # 1) Diagnostic-proven primary path: the real keyboard receiver is input_buffer iframe.
 # Focus the visible paragraph once, then switch *inside* the active iframe before Ctrl+V.
 if copy_method!='none':
  try:_hard_focus_body_for_paste(d,timeout=8)
  except Exception:pass
  ok,ibdiag=_paste_via_active_input_buffer(d)
  methods.append('input-buffer-frame+ctrl-v' if ok else 'input-buffer-failed:'+repr(ibdiag)[:220])
  if ok:
   result=verify('input-buffer-frame+ctrl-v',ibdiag,timeout=max(5.0,min(16.0,2.2+len(plain)/520.0)))
   if result:return result

 # 2) OS physical input is a fallback, not the first 20-second wait anymore.
 if copy_method!='none' and os.name=='nt':
  ok,diag=_win_phys_click_and_paste_body(d)
  methods.append('windows-physical-click+ctrl-v' if ok else 'windows-physical-failed:'+repr(diag)[:220])
  if ok:
   result=verify('windows-physical-click+ctrl-v',diag,timeout=max(5.0,min(16.0,2.2+len(plain)/520.0)))
   if result:return result

 # 3) Generic body-target Ctrl+V, at most one attempt now that input_buffer was handled explicitly.
 if copy_method!='none':
  target,snap=_hard_focus_body_for_paste(d,timeout=10)
  try:
   target.click();time.sleep(.10)
  except Exception:pass
  try:
   ActionChains(d).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform();method=copy_method+'+selenium-ctrl-v'
  except Exception as exc:method='selenium-ctrl-v-failed:'+type(exc).__name__
  methods.append(method)
  if 'failed' not in method:
   result=verify(method,snap,timeout=max(6.0,min(20.0,2.5+len(plain)/500.0)))
   if result:return result

 # 4) Browser editing-command fallback at the already-correct paragraph selection.
 if _execcommand_insert_html(d,html_fragment):
  methods.append('selection-execCommand-insertHTML')
  result=verify('selection-execCommand-insertHTML',_smarteditor_focus_snapshot(d),timeout=6.0)
  if result:return result

 # 5) Crucial v8.08.10 safety fallback: clipboard may be valid yet Naver can reject
 # paste.  When EVERY prior path produced zero body change, one trusted bulk
 # keyboard transaction is safer than stopping after title.  It never re-clicks per
 # line, so it cannot reproduce the old mid-sentence caret corruption.
 if _compact_text(_editor_text(d))==before:
  ok,snap=_plain_bulk_keyboard_fallback(d,plain,before)
  methods.append(('plain-bulk-keyboard:'+str((snap or {}).get('method',''))) if ok else 'plain-bulk-keyboard-failed:'+repr(snap)[:220])
  if ok:
   now=_compact_text(_editor_text(d))
   return {'plain_chars':len(want),'editor_chars':len(now),'image_slots':slot_count,'method':str((snap or {}).get('method') or 'plain-bulk-keyboard'),'focus':snap}
  now=_compact_text(_editor_text(d))
  if now!=before:
   raise RuntimeError(f'SmartEditor ONE 본문 키보드 fallback 부분 반영 감지: 기대≈{len(want)}자 실제증가={len(now)-len(before)}자 · '+repr(snap)[:400])

 raise RuntimeError('SmartEditor ONE 본문 전체 입력 미반영: '+repr(methods)+f' · 기대≈{len(want)}자 · focus='+repr(_smarteditor_focus_snapshot(d))[:500]+' · input_buffer='+repr(_input_buffer_snapshot(d))[:700])

def _verify_rich_heading_style(d,post):
 """Verify rich-paste styling; repair only the small emphasized set if stripped."""
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 targets=[str(b.get('text') or '') for b in post.get('blocks',[]) if b.get('type') in ('heading','check') and str(b.get('text') or '').strip()]
 repaired=0;ok_count=0
 for text in targets:
  e=find_exact(d,text)
  if e is not None and _bold_present(d,e) and _exact_bg_present(d,e,bg):ok_count+=1;continue
  # Native Rich Paste can be sanitized by Naver. Repair only this line, never the body text.
  if e is not None:
   try:
    format_yellow_bold(d,text);repaired+=1
    e=find_exact(d,text)
    if e is not None and _bold_present(d,e) and _exact_bg_present(d,e,bg):ok_count+=1
   except Exception as exc:log('Rich Paste 강조서식 보정 실패(본문 저장은 계속 검증): '+text[:40]+' · '+str(exc))
 return {'targets':len(targets),'verified':ok_count,'repaired':repaired,'background':bg}


def _wait_line_ack_modern(d,text,before_count,before_native,timeout=3.0):
 needle=_compact_text(text);end=time.time()+timeout
 if not needle:return True,'empty'
 while time.time()<end:
  try:
   now=_compact_text(_editor_text(d))
   if now.count(needle)>before_count:return True,'editor-text'
  except Exception:pass
  if _native_line_count_modern(d,text)>before_native:return True,'native-paragraph'
  time.sleep(.08)
 return False,''


def _body_runtime_diagnostic_modern(d):
 try:
  return d.execute_script(r"""
   const info=e=>{if(!e)return null;const r=e.getBoundingClientRect();return {tag:e.tagName,id:e.id||'',cls:String(e.className||'').slice(0,160),ce:e.getAttribute('contenteditable'),role:e.getAttribute('role'),text:(e.innerText||e.value||e.textContent||'').slice(0,160),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};};
   const a=document.activeElement,s=window.getSelection();let n=s&&s.anchorNode,anchor=n&&(n.nodeType===1?n:n.parentElement);
   return {active:info(a),anchor:info(anchor),editables:[...document.querySelectorAll('[contenteditable=true],[role=textbox],textarea')].slice(0,20).map(info),paragraphs:[...document.querySelectorAll('.se-text-paragraph,.se-module-text')].slice(0,20).map(info)};
  """) or {}
 except Exception as exc:return {'diagnostic_error':str(exc)}


def _last_article_paragraph(d):
 """Return the last visible BODY paragraph in document order, never the title."""
 try:
  return d.execute_script(r"""
   const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle,[class*=documentTitle],[data-placeholder*=\"제목\"],[aria-label*=\"제목\"]';
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
   const bad=e=>!!e.closest(titleSel)||/input[_-]?buffer|clipboard|paste|tag|search|comment/i.test(((e.id||'')+' '+(e.className||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('data-placeholder')||'')));
   let ps=[...document.querySelectorAll('.se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].filter(e=>vis(e)&&!bad(e));
   return ps.length?ps[ps.length-1]:null;
  """)
 except Exception:return None


def _place_caret_at_body_end(d):
 """Put a collapsed caret at the actual END of the article body.

 This is intentionally different from _activate_body_physical(): that helper is
 suitable only for an empty body. Re-clicking an arbitrary visible paragraph
 after every line can put the caret in the middle of already-written text.
 """
 try:_switch_to_editor_host(d,timeout=6)
 except Exception:pass
 e=_last_article_paragraph(d)
 if e is not None:
  try:
   d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",e)
  except Exception:pass
  try:ActionChains(d).move_to_element(e).click().send_keys(Keys.END).perform()
  except Exception:
   try:e.click();e.send_keys(Keys.END)
   except Exception:pass
  # Browser-level range collapse is used only to correct caret position; text
  # is still inserted through native keyboard/paste events so SmartEditor owns
  # the mutation and undo history.
  try:
   ok=bool(d.execute_script(r"""
    const e=arguments[0],s=getSelection();if(!e||!s)return false;
    const r=document.createRange();r.selectNodeContents(e);r.collapse(false);
    s.removeAllRanges();s.addRange(r);return s.isCollapsed;
   """,e))
   if ok:return e
  except Exception:return e
  return e
 _activate_body_physical(d)
 return _last_article_paragraph(d)


def _paste_text_native(d,text):
 """Fast native SmartEditor input: one clipboard paste instead of per-character typing."""
 text=str(text or '')
 if not text:return True
 if _set_windows_clipboard_text(text):
  try:
   ActionChains(d).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform();return True
  except Exception:pass
 try:ActionChains(d).send_keys(text).perform();return True
 except Exception:return False



def _se_dom_debug_snapshot(d):
 """Return a compact runtime map of the SmartEditor ONE/SE3-compatible body DOM.

 The user's diagnostics proved an important current-Naver invariant: the visible
 selection can already be inside ``p.se-text-paragraph`` while
 ``document.activeElement`` is the transient ``iframe#input_buffer...``.  A
 keyboard-only writer therefore cannot assume that activeElement is the article
 paragraph.  This snapshot is saved on every failure so future DOM changes are
 visible without guessing.
 """
 try:_switch_to_editor_host(d,timeout=6)
 except Exception:pass
 try:
  return d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';};
   const info=e=>{if(!e)return null;const r=e.getBoundingClientRect();return {tag:e.tagName||'',id:e.id||'',cls:String(e.className||'').slice(0,180),ce:e.getAttribute&&e.getAttribute('contenteditable'),role:e.getAttribute&&e.getAttribute('role'),ph:e.getAttribute&&((e.getAttribute('data-placeholder')||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'')),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};};
   const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle,[class*=documentTitle]';
   const ps=[...document.querySelectorAll('.se-main-container .se-component.se-text p.se-text-paragraph,.se-content .se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].filter(e=>vis(e)&&!e.closest(titleSel));
   const ce=[...document.querySelectorAll('.se-main-container [contenteditable=true],.se-content [contenteditable=true],[contenteditable=true]')].filter(e=>vis(e)&&!e.closest(titleSel)).slice(0,12);
   const a=document.activeElement,s=window.getSelection();let n=s&&s.rangeCount?s.anchorNode:null,sel=n?(n.nodeType===1?n:n.parentElement):null;
   return {active:info(a),selection:info(sel),selection_text:s&&s.rangeCount?String(s.toString()||'').slice(0,120):'',paragraph_count:ps.length,last_paragraph:info(ps.length?ps[ps.length-1]:null),contenteditables:ce.map(info),main_container:info(document.querySelector('.se-main-container')),content:info(document.querySelector('.se-content'))};
  """) or {}
 except Exception as exc:return {'snapshot_error':type(exc).__name__+': '+str(exc)[:300]}


def _se_last_body_paragraph(d,activate=True):
 """Locate the actual last article paragraph using the documented SE component tree.

 Exact preferred path:
 ``.se-main-container > .se-component.se-text ... .se-module-text > p.se-text-paragraph``.
 Title, tag, comment and input-buffer helpers are explicitly excluded.
 """
 try:_switch_to_editor_host(d,timeout=8)
 except Exception:pass
 try:
  e=d.execute_script(r"""
   const titleSel='.se-title-text,.se-section-documentTitle,.se-documentTitle,[class*=documentTitle]';
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),st=getComputedStyle(e);return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';};
   const bad=e=>!e||!!e.closest(titleSel)||/input[_-]?buffer|inputbuffer|clipboard|paste|tag|search|comment|제목|태그/i.test(((e.id||'')+' '+(typeof e.className==='string'?e.className:'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('data-placeholder')||'')));
   let ps=[...document.querySelectorAll('.se-main-container .se-component.se-text .se-module-text p.se-text-paragraph,.se-main-container .se-section-text p.se-text-paragraph,.se-content .se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].filter(e=>vis(e)&&!bad(e));
   if(!ps.length){
     const shell=[...document.querySelectorAll('.se-main-container .se-component.se-text,.se-content .se-component.se-text,.se-section-text,.se-main-container,.se-content')].find(e=>vis(e)&&!bad(e));
     if(shell&&arguments[0]){try{shell.scrollIntoView({block:'center'});shell.click();}catch(x){}}
     return null;
   }
   const p=ps[ps.length-1];if(arguments[0]){try{p.scrollIntoView({block:'center',inline:'nearest'});p.click();}catch(x){}}
   return p;
  """,bool(activate))
  if e is not None:return e
 except Exception:pass
 if activate:
  try:_activate_body_physical(d);time.sleep(.20)
  except Exception:pass
  try:
   return d.execute_script(r"""
    const ps=[...document.querySelectorAll('.se-main-container .se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')];return ps.length?ps[ps.length-1]:null;
   """)
  except Exception:return None
 return None


def _se_place_selection_at_paragraph_end(d,p=None):
 p=p or _se_last_body_paragraph(d,activate=True)
 if p is None:return False
 try:
  return bool(d.execute_script(r"""
   const p=arguments[0],s=window.getSelection();if(!p||!s)return false;
   const a=document.activeElement;if(a&&a.tagName==='IFRAME'&&/input[_-]?buffer|inputbuffer/i.test((a.id||'')+' '+(a.name||''))){try{a.blur();}catch(x){}}
   const host=p.closest('[contenteditable=true]')||p.closest('.se-module-text')||p.closest('.se-component.se-text')||p;
   try{host.focus({preventScroll:true});}catch(x){try{host.focus();}catch(y){}}
   const r=document.createRange();r.selectNodeContents(p);r.collapse(false);s.removeAllRanges();s.addRange(r);
   return !!(s.rangeCount&&s.isCollapsed&&p.contains(s.anchorNode));
  """,p))
 except Exception:return False


def _se_execcommand_insert(d,text,paragraph_break=True):
 """Use the browser's native editing command at the real SE paragraph selection.

 This avoids the current ``input_buffer`` trap: the visible selection belongs to
 ``p.se-text-paragraph`` even when the hidden IME iframe owns activeElement.
 ``execCommand`` mutates the selected editable document and emits the native
 input transaction instead of sending keystrokes to the helper iframe.
 """
 text=str(text or '')
 p=_se_last_body_paragraph(d,activate=True)
 if p is None:return False,{'reason':'no-paragraph'}
 _se_place_selection_at_paragraph_end(d,p)
 try:
  res=d.execute_script(r"""
   const p=arguments[0],txt=String(arguments[1]||''),wantBreak=!!arguments[2];
   const s=window.getSelection();if(!s||!s.rangeCount)return {ok:false,reason:'no-selection'};
   const before=(p.innerText||p.textContent||'');
   let okText=false,okBreak=true;
   try{okText=document.execCommand('insertText',false,txt);}catch(x){okText=false;}
   if(!okText&&txt){
     // Naver variants sometimes reject insertText but accept insertHTML at the
     // same paragraph selection. Escape to plain text so no arbitrary HTML is injected.
     const esc=txt.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
     try{okText=document.execCommand('insertHTML',false,esc);}catch(x){okText=false;}
   }
   if(wantBreak){try{okBreak=document.execCommand('insertParagraph',false,null);}catch(x){okBreak=false;}}
   const eventHost=p.closest('.se-component.se-text')||p.closest('.se-module-text')||p;
   try{eventHost.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:wantBreak?'insertParagraph':'insertText',data:txt||null}));}catch(x){try{eventHost.dispatchEvent(new Event('input',{bubbles:true}));}catch(y){}}
   return {ok:!!okText,break_ok:!!okBreak,before:before.slice(0,80),active:(document.activeElement&&document.activeElement.tagName||''),selection:(s.anchorNode&&(s.anchorNode.nodeType===1?s.anchorNode:s.anchorNode.parentElement).className||'')};
  """,p,text,bool(paragraph_break)) or {}
  return bool(res.get('ok')),res
 except Exception as exc:return False,{'reason':type(exc).__name__+': '+str(exc)[:240]}


def _se_charwise_action_insert(d,text,paragraph_break=True,delay=None):
 """Trusted fallback: refocus once, then type Korean one character at a time.

 Recent working SmartEditor automation examples use per-character events.  A
 single ``send_keys(long_korean_string)`` can be swallowed by Naver's IME
 input-buffer; per-character events preserve the composition bridge without
 re-clicking mid-sentence.
 """
 text=str(text or '')
 target=_v764_body_target_after_toolbar(d)
 delay=float(settings().get('blog_dom_char_delay_sec',0.012) if delay is None else delay)
 try:
  for ch in text:
   ActionChains(d).send_keys(ch).perform()
   if delay>0:time.sleep(delay)
  if paragraph_break:ActionChains(d).send_keys(Keys.ENTER).perform()
  return True,{'method':'action-charwise','chars':len(text),'delay':delay}
 except Exception as exc:return False,{'method':'action-charwise','error':type(exc).__name__+': '+str(exc)[:240]}


def _se_charwise_element_insert(d,text,paragraph_break=True,delay=None):
 text=str(text or '');target=_v764_body_target_after_toolbar(d)
 delay=float(settings().get('blog_dom_char_delay_sec',0.012) if delay is None else delay)
 try:
  ce=(target.get_attribute('contenteditable') or '').lower()=='true' or (target.get_attribute('role') or '').lower()=='textbox' or str(target.tag_name).lower()=='textarea'
 except Exception:ce=False
 if not ce:return False,{'method':'element-charwise','reason':'target-not-editable'}
 try:
  for ch in text:
   target.send_keys(ch)
   if delay>0:time.sleep(delay)
  if paragraph_break:target.send_keys(Keys.ENTER)
  return True,{'method':'element-charwise','chars':len(text),'delay':delay}
 except Exception as exc:return False,{'method':'element-charwise','error':type(exc).__name__+': '+str(exc)[:240]}



def _win_find_chrome_hwnd_for_driver(d):
 if os.name!='nt':return 0
 try:
  title=str(d.title or '').strip().lower()
 except Exception:title=''
 try:
  user32=ctypes.windll.user32;hits=[]
  @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
  def cb(hwnd,lparam):
   try:
    if not user32.IsWindowVisible(hwnd):return True
    cls=ctypes.create_unicode_buffer(128);user32.GetClassNameW(hwnd,cls,128)
    if cls.value!='Chrome_WidgetWin_1':return True
    n=user32.GetWindowTextLengthW(hwnd);buf=ctypes.create_unicode_buffer(n+1);user32.GetWindowTextW(hwnd,buf,n+1)
    wt=buf.value.strip();score=0
    if title and title in wt.lower():score+=100
    if '네이버' in wt or 'naver' in wt.lower():score+=50
    rect=ctypes.wintypes.RECT() if hasattr(ctypes,'wintypes') else None
    area=0
    if rect is not None and user32.GetWindowRect(hwnd,ctypes.byref(rect)):area=max(0,rect.right-rect.left)*max(0,rect.bottom-rect.top)
    hits.append((score,area,int(hwnd),wt))
   except Exception:pass
   return True
  user32.EnumWindows(cb,0)
  if not hits:return 0
  hits.sort(reverse=True);return hits[0][2]
 except Exception:return 0


def _win_body_screen_point(d):
 """Return a physical screen point inside the selected/last SE paragraph."""
 try:_switch_to_editor_host(d,timeout=6)
 except Exception:pass
 try:
  return d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>20&&r.height>8&&s.display!=='none'&&s.visibility!=='hidden';};
   const ps=[...document.querySelectorAll('.se-main-container .se-component.se-text .se-module-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].filter(vis);
   const p=ps.length?ps[ps.length-1]:null;if(!p)return null;
   p.scrollIntoView({block:'center',inline:'nearest'});const r=p.getBoundingClientRect();
   const chromeY=window.outerHeight-window.innerHeight;
   const vx=Math.round(r.left+Math.max(12,Math.min(r.width-12,r.width*.55)));
   const vy=Math.round(r.top+Math.max(8,Math.min(r.height-6,r.height*.55)));
   return {x:Math.round(window.screenX+vx),y:Math.round(window.screenY+chromeY+vy),vx,vy,rect:{x:r.x,y:r.y,w:r.width,h:r.height},chromeY};
  """)
 except Exception:return None


def _win_unicode_send_text(d,text,paragraph_break=True,delay=None):
 """Windows physical Unicode-key fallback that mirrors real user typing.

 It is used only after DOM-native and Selenium charwise probes fail.  The body
 paragraph is physically clicked once, then UTF-16 key events are injected via
 Win32 SendInput.  There is no per-character re-click, so the old mid-line caret
 corruption cannot recur.
 """
 if os.name!='nt':return False,{'method':'windows-unicode','reason':'not-windows'}
 text=str(text or '');delay=float(settings().get('blog_dom_char_delay_sec',0.012) if delay is None else delay)
 try:
  point=_win_body_screen_point(d)
  if not point:return False,{'method':'windows-unicode','reason':'no-body-point'}
  user32=ctypes.windll.user32;hwnd=_win_find_chrome_hwnd_for_driver(d)
  if hwnd:
   try:user32.ShowWindow(hwnd,9);user32.SetForegroundWindow(hwnd);time.sleep(.12)
   except Exception:pass
  user32.SetCursorPos(int(point['x']),int(point['y']));time.sleep(.08)
  user32.mouse_event(0x0002,0,0,0,0);time.sleep(.03);user32.mouse_event(0x0004,0,0,0,0);time.sleep(.14)
  ULONG_PTR=ctypes.c_size_t
  class KEYBDINPUT(ctypes.Structure):
   _fields_=[('wVk',ctypes.c_ushort),('wScan',ctypes.c_ushort),('dwFlags',ctypes.c_ulong),('time',ctypes.c_ulong),('dwExtraInfo',ULONG_PTR)]
  class INPUT_UNION(ctypes.Union):
   _fields_=[('ki',KEYBDINPUT)]
  class INPUT(ctypes.Structure):
   _anonymous_=('u',);_fields_=[('type',ctypes.c_ulong),('u',INPUT_UNION)]
  KEYEVENTF_KEYUP=0x0002;KEYEVENTF_UNICODE=0x0004;INPUT_KEYBOARD=1
  def send_unit(unit,up=False):
   flags=KEYEVENTF_UNICODE|(KEYEVENTF_KEYUP if up else 0)
   inp=INPUT(type=INPUT_KEYBOARD,ki=KEYBDINPUT(0,int(unit),flags,0,0))
   return int(user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(INPUT)))==1
  raw=text.encode('utf-16-le','surrogatepass')
  for i in range(0,len(raw),2):
   unit=raw[i]|(raw[i+1]<<8)
   if not send_unit(unit,False) or not send_unit(unit,True):return False,{'method':'windows-unicode','reason':'SendInput-failed','at':i//2}
   if delay>0:time.sleep(delay)
  if paragraph_break:
   VK_RETURN=0x0D
   user32.keybd_event(VK_RETURN,0,0,0);time.sleep(.03);user32.keybd_event(VK_RETURN,0,KEYEVENTF_KEYUP,0)
  return True,{'method':'windows-unicode','chars':len(text),'point':point,'hwnd':hwnd,'delay':delay}
 except Exception as exc:return False,{'method':'windows-unicode','error':type(exc).__name__+': '+str(exc)[:400]}

def _se_probe_cleanup(d,before,sentinel):
 """Undo a calibration marker and prove that the editor returned to its prior text."""
 # First ask the same editing document to undo its last native transaction.
 try:
  _switch_to_editor_host(d,timeout=5);_se_last_body_paragraph(d,activate=True)
  d.execute_script("try{return document.execCommand('undo',false,null);}catch(e){return false;}");time.sleep(.15)
 except Exception:pass
 now=_compact_text(_editor_text(d))
 if sentinel not in now and now==before:return True
 for _ in range(2):
  try:
   _switch_to_editor_host(d,timeout=5);_se_last_body_paragraph(d,activate=True)
   ActionChains(d).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform();time.sleep(.18)
  except Exception:pass
  now=_compact_text(_editor_text(d))
  if sentinel not in now and now==before:return True
 try:
  d.execute_script(r"""
   const needle=arguments[0],ps=[...document.querySelectorAll('.se-text-paragraph')];
   for(const p of ps){const w=document.createTreeWalker(p,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){const i=(n.nodeValue||'').indexOf(needle);if(i>=0){const r=document.createRange();r.setStart(n,i);r.setEnd(n,i+needle.length);const s=getSelection();s.removeAllRanges();s.addRange(r);try{document.execCommand('delete',false,null);}catch(x){r.deleteContents();}try{(p.closest('.se-component.se-text')||p).dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'}));}catch(x){}return true;}}}return false;
  """,sentinel);time.sleep(.15)
 except Exception:pass
 now=_compact_text(_editor_text(d))
 return sentinel not in now and now==before


def _se_dom_probe_input_strategy(d,force=False):
 """Calibrate the actual working body-input path on THIS Naver session.

 A short ASCII sentinel is inserted, verified in ``se-text-paragraph``, undone,
 and the successful method is cached on the WebDriver.  No full article is ever
 used as a probe.  This converts changing SmartEditor DOM/IME behavior from a
 guess into a runtime handshake.
 """
 if not force:
  cached=str(getattr(d,'_nb_dom_input_strategy','') or '')
  if cached:return cached
 try:_switch_to_editor_host(d,timeout=8)
 except Exception:pass
 before=_compact_text(_editor_text(d));sentinel='NBDOM'+format(int(time.time()*1000)%0xFFFFFF,'06X')
 tests=[('execcommand',lambda:_se_execcommand_insert(d,sentinel,False)),
        ('element-charwise',lambda:_se_charwise_element_insert(d,sentinel,False,delay=0.0)),
        ('action-charwise',lambda:_se_charwise_action_insert(d,sentinel,False,delay=0.0)),
        ('windows-unicode',lambda:_win_unicode_send_text(d,sentinel,False,delay=0.0))]
 report={'before_chars':len(before),'sentinel':sentinel,'dom':_se_dom_debug_snapshot(d),'attempts':[]}
 for name,fn in tests:
  try:ok,diag=fn()
  except Exception as exc:ok=False;diag={'error':type(exc).__name__+': '+str(exc)[:240]}
  time.sleep(.20);now=_compact_text(_editor_text(d));appeared=(sentinel in now)
  report['attempts'].append({'method':name,'call_ok':bool(ok),'appeared':appeared,'delta':len(now)-len(before),'diag':diag})
  if appeared:
   if not _se_probe_cleanup(d,before,sentinel):
    try:setattr(d,'_nb_dom_probe_report',report)
    except Exception:pass
    raise RuntimeError('SmartEditor DOM 입력 경로 학습 중 테스트 문자열 원복 실패: 저장 금지 · '+json.dumps(report,ensure_ascii=False)[:1800])
   setattr(d,'_nb_dom_input_strategy',name);setattr(d,'_nb_dom_probe_report',report)
   log('SmartEditor DOM 런타임 학습 성공: '+name+' · '+json.dumps(report['dom'],ensure_ascii=False)[:500])
   return name
  # Any mutation without the complete sentinel must be restored before testing another route.
  if now!=before:
   if not _se_probe_cleanup(d,before,sentinel):
    try:setattr(d,'_nb_dom_probe_report',report)
    except Exception:pass
    raise RuntimeError('SmartEditor DOM 입력 경로 학습 중 부분 입력 원복 실패: 저장 금지 · '+json.dumps(report,ensure_ascii=False)[:1800])
 try:setattr(d,'_nb_dom_probe_report',report)
 except Exception:pass
 raise RuntimeError('SmartEditor 본문 DOM 입력 경로 자동학습 실패: '+json.dumps(report,ensure_ascii=False)[:2200])


def _se_dom_write_line(d,text):
 """Write one verified paragraph using the calibrated session strategy."""
 text=str(text or '');needle=_compact_text(text)
 before=_compact_text(_editor_text(d));before_count=before.count(needle) if needle else 0
 before_native=_native_line_count_modern(d,text) if needle else 0
 strategy=_se_dom_probe_input_strategy(d)
 if strategy=='execcommand':ok,diag=_se_execcommand_insert(d,text,True)
 elif strategy=='element-charwise':ok,diag=_se_charwise_element_insert(d,text,True)
 elif strategy=='windows-unicode':ok,diag=_win_unicode_send_text(d,text,True)
 else:ok,diag=_se_charwise_action_insert(d,text,True)
 ack,via=_wait_line_ack_modern(d,text,before_count,before_native,timeout=max(3.8,min(8.0,2.2+len(text)/80.0)))
 if not needle or ack:
  log(f'SmartEditor DOM 문장 확인: {strategy}/{via or "ack"} · {text[:55]}');return
 after=_compact_text(_editor_text(d));native_after=_native_line_count_modern(d,text)
 if after!=before or native_after!=before_native:
  raise RuntimeError(f'SmartEditor DOM 문장 부분 입력 감지: 재입력 금지 · {text[:80]} · strategy={strategy} · before={len(before)} after={len(after)} · '+json.dumps(_se_dom_debug_snapshot(d),ensure_ascii=False)[:900])
 # Zero mutation only: recalibrate ONCE. This is safe because nothing was committed.
 try:delattr(d,'_nb_dom_input_strategy')
 except Exception:pass
 strategy2=_se_dom_probe_input_strategy(d,force=True)
 if strategy2=='execcommand':ok2,diag2=_se_execcommand_insert(d,text,True)
 elif strategy2=='element-charwise':ok2,diag2=_se_charwise_element_insert(d,text,True)
 elif strategy2=='windows-unicode':ok2,diag2=_win_unicode_send_text(d,text,True)
 else:ok2,diag2=_se_charwise_action_insert(d,text,True)
 ack,via=_wait_line_ack_modern(d,text,before_count,before_native,timeout=max(4.0,min(9.0,2.4+len(text)/70.0)))
 if ack:
  log(f'SmartEditor DOM 문장 경로 재학습 성공: {strategy}->{strategy2} · {text[:55]}');return
 after=_compact_text(_editor_text(d))
 if after!=before:raise RuntimeError('SmartEditor DOM 재학습 후 부분 입력 감지: 저장 금지 · '+text[:80])
 raise RuntimeError('SmartEditor 본문 문장 0반영: DOM 학습/재학습 모두 실패 · '+text[:80]+' · '+json.dumps(getattr(d,'_nb_dom_probe_report',{}),ensure_ascii=False)[:1800])


def _se_dom_blank_line(d):
 strategy=_se_dom_probe_input_strategy(d)
 if strategy=='execcommand':
  p=_se_last_body_paragraph(d,activate=True);_se_place_selection_at_paragraph_end(d,p)
  try:
   ok=bool(d.execute_script("try{return document.execCommand('insertParagraph',false,null);}catch(e){return false;}"))
   if ok:return
  except Exception:pass
 if strategy=='windows-unicode':
  ok,_=_win_unicode_send_text(d,'',True,delay=0.0)
  if ok:return
 # Keyboard strategies or execCommand fallback: no text re-click during a line, only
 # at the paragraph boundary where a fresh caret is safe.
 _v764_body_target_after_toolbar(d)
 ActionChains(d).send_keys(Keys.ENTER).perform()

def _v764_body_target_after_toolbar(d):
 """Re-acquire the REAL article body after any toolbar click.

 v7.64 rule: toolbar actions are allowed to steal focus, but text is NEVER sent
 until the editor host is restored and the caret is collapsed at the article end.
 Auxiliary IME/input_buffer frames are not treated as article containers.
 """
 try:_switch_to_editor_host(d,timeout=8)
 except Exception:pass
 try:
  root=_body_root(d,timeout=10)
 except Exception:
  _activate_body_physical(d);root=_body_root(d,timeout=10)
 # First prefer a genuine visible contenteditable inside the article body.
 try:
  target=d.execute_script(r"""
   const root=arguments[0];
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
   const bad=e=>!!e.closest('.se-title-text,.se-section-documentTitle,.se-documentTitle,[class*=documentTitle],[class*=tag],[class*=comment]')||/input[_-]?buffer|inputbuffer|clipboard|paste|tag|search|comment|title|제목|태그/i.test(((e.id||'')+' '+(e.className||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('data-placeholder')||'')));
   let xs=[];
   if(root.matches&&root.matches('[contenteditable=true],[role=textbox],textarea'))xs.push(root);
   xs.push(...root.querySelectorAll('[contenteditable=true],[role=textbox],textarea'));
   xs=xs.filter(e=>vis(e)&&!bad(e));
   if(xs.length)return xs[xs.length-1];
   const ps=[...root.querySelectorAll('.se-component.se-text .se-text-paragraph,.se-section-text .se-text-paragraph,.se-text-paragraph')].filter(e=>vis(e)&&!bad(e));
   return ps.length?ps[ps.length-1]:root;
  """,root)
 except Exception:target=None
 if target is None:target=root
 try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",target)
 except Exception:pass
 # Physical click/focus AFTER toolbar interaction, then collapse caret at END.
 try:ActionChains(d).move_to_element(target).click().perform()
 except Exception:
  try:target.click()
  except Exception:_activate_body_physical(d)
 try:
  d.execute_script(r"""
   const e=arguments[0],s=window.getSelection();
   try{e.focus();}catch(x){}
   const r=document.createRange();r.selectNodeContents(e);r.collapse(false);
   s.removeAllRanges();s.addRange(r);return !!(s.rangeCount&&s.isCollapsed);
  """,target)
 except Exception:
  try:target.send_keys(Keys.END)
  except Exception:pass
 return target


def _v764_direct_send_line(d,text):
 """Send one line without clipboard/CDP; element keyboard first, focused keyboard second."""
 target=_v764_body_target_after_toolbar(d)
 methods=[]
 try:
  ce=(target.get_attribute('contenteditable') or '').lower()=='true' or (target.get_attribute('role') or '').lower()=='textbox' or str(target.tag_name).lower()=='textarea'
 except Exception:ce=False
 if ce:
  try:
   target.send_keys(str(text or ''));target.send_keys(Keys.ENTER);return 'body-element-send_keys'
  except Exception as exc:methods.append('element:'+type(exc).__name__)
 # The click/range above established the article caret. Use the active browser
 # keyboard path only after that exact focus transaction.
 try:
  ActionChains(d).send_keys(str(text or '')).send_keys(Keys.ENTER).perform();return 'focused-action-send_keys'
 except Exception as exc:methods.append('action:'+type(exc).__name__)
 raise RuntimeError('SmartEditor 본문 직접키입력 실패: '+repr(methods))


def _v764_blank_line(d):
 """Insert a paragraph break only after restoring the body caret."""
 basefmt(d)
 target=_v764_body_target_after_toolbar(d)
 try:
  ce=(target.get_attribute('contenteditable') or '').lower()=='true' or (target.get_attribute('role') or '').lower()=='textbox' or str(target.tag_name).lower()=='textarea'
 except Exception:ce=False
 try:
  if ce:target.send_keys(Keys.ENTER)
  else:ActionChains(d).send_keys(Keys.ENTER).perform()
 except Exception:
  _activate_body_physical(d);ActionChains(d).send_keys(Keys.ENTER).perform()


def line(d,t):
 """SmartEditor ONE/SE3-compatible adaptive DOM line writer.

 v8.08.12 no longer assumes that ActionChains is delivered to the article when
 ``iframe#input_buffer`` owns activeElement.  The first body transaction learns
 a verified insertion route against ``p.se-text-paragraph`` and every line is
 acknowledged from the article DOM before the next line begins.
 """
 return _se_dom_write_line(d,t)

def find_exact(d,t):
 lit=json.dumps(t)
 for xp in [f"//*[contains(@class,'se-text-paragraph') and normalize-space(.)={lit}]",f"//*[self::p or self::span or self::div][normalize-space(.)={lit}]"]:
  for e in d.find_elements(By.XPATH,xp):
   if e.is_displayed():return e
def selectline(d,e):ActionChains(d).click(e).send_keys(Keys.HOME).key_down(Keys.SHIFT).send_keys(Keys.END).key_up(Keys.SHIFT).perform()

def _collapse_selection(d):
 try:d.execute_script("""const s=window.getSelection();if(s&&s.rangeCount){s.collapseToEnd();}""")
 except Exception:
  try:ActionChains(d).send_keys(Keys.RIGHT).perform()
  except Exception:pass

def _exact_bg_present(d,e,hex_color=None):
 try:
  target=str(hex_color or settings().get('blog_heading_advantage_background_hex','#fff8b2')).lstrip('#')
  if len(target)==3:target=''.join(c*2 for c in target)
  rgb=[int(target[i:i+2],16) for i in (0,2,4)]
  vals=d.execute_script("""
   const root=arguments[0],out=[];
   for(const n of [root,...root.querySelectorAll('*')]){const c=getComputedStyle(n).backgroundColor;if(c&&c!=='rgba(0, 0, 0, 0)'&&c!=='transparent')out.push(c);}
   return [...new Set(out)];
  """,e) or []
  for v in vals:
   nums=[int(x) for x in re.findall(r"\d+",str(v))[:3]]
   if nums==rgb:return True
  return False
 except Exception:return False

def _bold_present(d,e):
 try:
  vals=d.execute_script("""const r=arguments[0];return [r,...r.querySelectorAll('*')].map(n=>getComputedStyle(n).fontWeight);""",e) or []
  return any((str(v).isdigit() and int(v)>=600) or str(v).lower() in ('bold','bolder') for v in vals)
 except Exception:return False

def _click_exact_background(d,hex_color=None):
 target=str(hex_color or settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 h=target.lstrip('#');rgb=tuple(int(h[i:i+2],16) for i in (0,2,4)) if len(h)==6 else (136,143,178)
 btn=toolbar(d,["글자 배경색","배경색","텍스트 배경색","문자 배경색","형광펜","background"])
 if not btn:return False
 try:d.execute_script("arguments[0].click();",btn)
 except Exception:
  try:btn.click()
  except Exception:return False
 time.sleep(.22)
 try:
  ok=d.execute_script(r"""
   const target=arguments[0].toLowerCase(),rgb=arguments[1];
   const vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
   for(const e of document.querySelectorAll('input[type=color]')){if(!vis(e))continue;e.value=target;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true;}
   for(const e of document.querySelectorAll('button,[role=button],a,li,span,div')){if(!vis(e))continue;const label=((e.getAttribute('aria-label')||'')+' '+(e.getAttribute('title')||'')+' '+(e.getAttribute('data-color')||'')+' '+(e.getAttribute('style')||'')).toLowerCase();const bg=(getComputedStyle(e).backgroundColor||'').replace(/\s+/g,' ');if(label.includes(target)||bg===rgb){e.click();return true;}}
   for(const e of document.querySelectorAll('input[type=text],input:not([type]),textarea')){if(!vis(e))continue;const ph=((e.placeholder||'')+' '+(e.getAttribute('aria-label')||'')).toLowerCase();if(/색|color|hex/.test(ph)){e.focus();e.value=target;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));return true;}}
   return false;
  """,target,f'rgb({rgb[0]}, {rgb[1]}, {rgb[2]})')
  if ok:time.sleep(.18);return True
 except Exception:pass
 return False


def format_yellow_bold(d,t):
 """Compatibility name: apply configured bold + text background (default #fff8b2)."""
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 e=find_exact(d,t)
 if not e:raise RuntimeError(f'굵게 + 글자 배경색 {bg} 대상 문구를 찾지 못함: '+str(t)[:40])
 selectline(d,e)
 strike=toolbar(d,["취소선","strike"])
 if active(strike):strike.click()
 b=toolbar(d,["굵게","bold"])
 if b and not active(b):b.click()
 if not _exact_bg_present(d,e,bg):_click_exact_background(d,bg)
 if not (_exact_bg_present(d,e,bg) and _bold_present(d,e)):
  try:
   d.execute_script("""
    const root=arguments[0],bg=arguments[1];try{document.execCommand('bold',false,null);}catch(x){}try{document.execCommand('backColor',false,bg);}catch(x){}try{document.execCommand('hiliteColor',false,bg);}catch(x){}
    for(const n of [root,...root.querySelectorAll('*')]){n.style.fontWeight='700';n.style.backgroundColor=bg;}
    const host=root.closest('[contenteditable=true]')||root;try{host.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'formatBackColor'}));}catch(x){host.dispatchEvent(new Event('input',{bubbles:true}));}
   """,e,bg);time.sleep(.12)
  except Exception:pass
 ok=_exact_bg_present(d,e,bg) and _bold_present(d,e)
 if bool(settings().get('blog_require_exact_heading_style',False)) and not ok:raise RuntimeError(f'굵게 + 글자 배경색 {bg} 적용 검증 실패: '+str(t)[:40])
 _collapse_selection(d);return ok

def bold(d,t):
 e=find_exact(d,t)
 if not e:return
 selectline(d,e);s=toolbar(d,["취소선","strike"])
 if active(s):s.click()
 b=toolbar(d,["굵게","bold"])
 if b and not active(b):b.click()
 _collapse_selection(d)

def _delete_marker_safely(d,marker):
 """Select ONLY the marker text, delete it, and prove no surrounding article text vanished."""
 e=find_exact(d,marker)
 if not e:raise RuntimeError("이미지 마커 없음 "+marker)
 before=_compact_text(_editor_text(d));m=_compact_text(marker)
 selected=d.execute_script("""
  const root=arguments[0],needle=arguments[1];
  const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;
  while(n=w.nextNode()){const i=(n.nodeValue||'').indexOf(needle);if(i>=0){
   const r=document.createRange();r.setStart(n,i);r.setEnd(n,i+needle.length);
   const s=window.getSelection();s.removeAllRanges();s.addRange(r);return s.toString();
  }} return '';
 """,e,marker)
 if str(selected or '')!=marker:raise RuntimeError(f"이미지 마커 정밀 선택 실패 {marker}: {selected!r}")
 ActionChains(d).send_keys(Keys.BACKSPACE).perform();time.sleep(.12)
 after=_compact_text(_editor_text(d));expected=before.replace(m,"",1)
 if after!=expected:
  raise RuntimeError("이미지 위치 선택 중 본문 손상 감지: 사진 업로드를 중단하여 글 삭제를 방지")
 try:
  collapsed=bool(d.execute_script("""const s=window.getSelection();return !!s&&s.rangeCount>0&&s.isCollapsed;"""))
 except Exception:collapsed=False
 if not collapsed:
  ActionChains(d).send_keys(Keys.RIGHT).perform();time.sleep(.05)
  try:collapsed=bool(d.execute_script("""const s=window.getSelection();return !!s&&s.rangeCount>0&&s.isCollapsed;"""))
  except Exception:collapsed=True
 if not collapsed:raise RuntimeError("사진 삽입 전 텍스트 선택영역 해제 실패")
 return e

def build(d,post):
 """v8.08.12 SmartEditor DOM-handshake body writer.

 The previous v8.08.11 still had one structural hole: after a real
 ``p.se-text-paragraph`` was selected, Naver could keep
 ``iframe#input_buffer...`` as ``document.activeElement``.  A long
 ActionChains/send_keys call was therefore delivered to the helper IME frame,
 not necessarily to the article.

 v8.08.12 sets the base paragraph format ONCE, learns a working insertion route
 with a short reversible sentinel, then writes each paragraph through that
 verified route.  Toolbar clicks are not repeated between body sentences.
 """
 # One toolbar transaction only.  All later heading/check styling happens after
 # the complete body has been verified, so toolbar focus can no longer break the
 # next sentence.
 basefmt(d)
 strategy=_se_dom_probe_input_strategy(d,force=False)
 log('SmartEditor DOM 작성 경로 확정: '+strategy)
 n=0
 for b in post.get('blocks',[]):
  typ=b.get('type')
  if typ=='disclosure':
   for x in (b.get('lines') or COUPANG_DISCLOSURE_LINES):_se_dom_write_line(d,str(x))
   _se_dom_blank_line(d)
  elif typ=='sharelink':
   url=str(b.get('url') or '').strip()
   if url:_se_dom_write_line(d,url);_se_dom_blank_line(d)
  elif typ in ('image','price_compare_image'):
   n+=1;_se_dom_write_line(d,f'[[IMG{n}]]');_se_dom_blank_line(d)
  elif typ=='heading':
   _se_dom_write_line(d,str(b.get('text') or ''));_se_dom_blank_line(d)
  elif typ=='check':
   _se_dom_write_line(d,str(b.get('text') or ''))
  elif typ=='paragraph':
   for x in b.get('lines',[]):
    if str(x).strip():_se_dom_write_line(d,str(x))
   _se_dom_blank_line(d)
 log(f'SmartEditor DOM 본문 트랜잭션 완료: strategy={strategy} · 검증된 이미지 슬롯 {n}개')
 return {'image_slots':n,'method':'v80812-dom-handshake-'+strategy}

def _editor_image_count(d):
 try:
  _body_root(d,timeout=6)
  return int(d.execute_script("""
   const r=document.querySelector('.se-main-container')||document.querySelector('.se-content')||document.body;if(!r)return 0;
   const comps=r.querySelectorAll('.se-component.se-image,[class*=se-component][class*=se-image]').length;
   if(comps)return comps;
   return r.querySelectorAll('img.se-image-resource,[class*=se-image-container] img').length;
  """) or 0)
 except Exception:return 0

def _editor_images_ready(d,expected=None):
 try:
  _body_root(d,timeout=6)
  data=d.execute_script("""
   const r=document.querySelector('.se-main-container')||document.querySelector('.se-content')||document.body;if(!r)return {count:0,unready:0};
   const comps=[...r.querySelectorAll('.se-component.se-image,[class*=se-component][class*=se-image]')];
   const count=comps.length||r.querySelectorAll('img.se-image-resource,[class*=se-image-container] img').length;
   const imgs=[...r.querySelectorAll('img.se-image-resource,[class*=se-image-container] img')];
   const unready=imgs.filter(x=>!x.complete||!x.naturalWidth||!x.naturalHeight).length;
   return {count:count,unready:unready};
  """) or {}
  count=int(data.get('count') or 0);unready=int(data.get('unready') or 0)
  return count,unready,(expected is None or count==int(expected))
 except Exception:return _editor_image_count(d),0,False

def _upload_busy(d):
 """Detect SmartEditor upload state/toast instead of racing the next image/save click."""
 try:
  data=d.execute_script("""
   const vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
   const body=(document.body&&document.body.innerText)||'';
   const busyText=body.includes('업로드 중에는 일부 기능을 사용할 수 없습니다')||body.includes('업로드 중입니다');
   const sels=['[class*=upload][class*=loading]','[class*=upload][class*=progress]','[class*=image][class*=loading]','[class*=loading][class*=image]'];
   const busyNode=sels.some(q=>[...document.querySelectorAll(q)].some(vis));
   return {busy:busyText||busyNode,busyText:busyText,busyNode:busyNode};
  """) or {}
  return bool(data.get('busy')),data
 except Exception:return False,{}

def _wait_upload_idle(d,expected_images=None,timeout=None,stable_sec=None):
 cfg=settings();timeout=float(timeout if timeout is not None else cfg.get('blog_upload_idle_timeout_sec',35));stable_sec=float(stable_sec if stable_sec is not None else cfg.get('blog_image_settle_sec',1.5))
 end=time.time()+max(4.0,timeout);stable_from=None;last={}
 while time.time()<end:
  count,unready,count_ok=_editor_images_ready(d,expected_images);busy,bdetail=_upload_busy(d);last={'count':count,'unready':unready,'busy':busy,**bdetail}
  ready=(not busy and unready==0 and count_ok)
  if ready:
   if stable_from is None:stable_from=time.time()
   if time.time()-stable_from>=stable_sec:return True,last
  else:stable_from=None
  time.sleep(.25)
 return False,last

def _visible_file_inputs(d):
 try:
  found=[x for x in d.find_elements(By.CSS_SELECTOR,"input[type='file']") if _visible(x)]
  if found:return found
 except Exception:pass
 try:
  _switch_to_editor_host(d,timeout=6)
  return d.find_elements(By.CSS_SELECTOR,"input[type='file']")
 except Exception:return []

def _click_photo_toolbar(d):
 """Open SmartEditor ONE's photo insertion UI using stable semantics first."""
 try:_switch_to_editor_host(d,timeout=6)
 except Exception:pass
 selectors=[
  "button.se-image-toolbar-button",".se-toolbar-item-image button","[class*='toolbar-item-image'] button",
  "button[aria-label*='사진']","button[aria-label*='이미지']","button[title*='사진']","button[title*='이미지']",
  "[role='button'][aria-label*='사진']","[role='button'][aria-label*='이미지']"
 ]
 for css in selectors:
  try:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    if e.is_displayed() and e.is_enabled():
     try:d.execute_script("arguments[0].click();",e)
     except Exception:e.click()
     time.sleep(.7);return True
  except Exception:pass
 e=toolbar(d,["사진","이미지","Photo","Image"])
 if e:
  try:d.execute_script("arguments[0].click();",e)
  except Exception:
   try:e.click()
   except Exception:return False
  time.sleep(.7);return True
 return False

def _click_photo_submenu(d):
 # Some SmartEditor ONE revisions open a small source menu first.
 for lab in ["내 PC","PC에서 불러오기","파일 선택","사진 추가","내 컴퓨터","컴퓨터"]:
  lit=json.dumps(lab)
  for xp in [f"//*[self::button or @role='button' or self::a][normalize-space(.)={lit}]",
             f"//*[self::button or @role='button' or self::a][contains(normalize-space(.),{lit})]"]:
   try:
    for e in d.find_elements(By.XPATH,xp):
     if e.is_displayed() and e.is_enabled():
      try:d.execute_script("arguments[0].click();",e)
      except Exception:e.click()
      time.sleep(.6);return True
   except Exception:pass
 return False

def _find_open_dialog():
 if os.name!="nt":return None
 user32=ctypes.windll.user32;found=[]
 @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
 def cb(hwnd,l):
  try:
   if not user32.IsWindowVisible(hwnd):return True
   cls=ctypes.create_unicode_buffer(256);user32.GetClassNameW(hwnd,cls,256)
   n=user32.GetWindowTextLengthW(hwnd);t=ctypes.create_unicode_buffer(n+1);user32.GetWindowTextW(hwnd,t,n+1)
   if cls.value=="#32770" and ("열기" in t.value or "Open" in t.value):found.append(hwnd)
  except Exception:pass
  return True
 try:user32.EnumWindows(cb,0)
 except Exception:return None
 return found[-1] if found else None

def _native_dialog_upload(path,wait_sec=3.0):
 """Fallback for SmartEditor builds that expose only the Windows file chooser."""
 if os.name!="nt":return False
 user32=ctypes.windll.user32;WM_SETTEXT=0x000C;BM_CLICK=0x00F5
 end=time.time()+max(0.5,float(wait_sec));hwnd=None
 while time.time()<end and not hwnd:
  hwnd=_find_open_dialog()
  if not hwnd:time.sleep(.15)
 if not hwnd:return False
 edits=[]
 @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
 def child(ch,l):
  try:
   cls=ctypes.create_unicode_buffer(128);user32.GetClassNameW(ch,cls,128)
   if cls.value=="Edit" and user32.IsWindowVisible(ch):edits.append(ch)
  except Exception:pass
  return True
 try:user32.EnumChildWindows(hwnd,child,0)
 except Exception:return False
 if not edits:return False
 edit=edits[-1]
 try:
  user32.SetForegroundWindow(hwnd);user32.SendMessageW(edit,WM_SETTEXT,0,str(Path(path)))
  ok=user32.GetDlgItem(hwnd,1)
  if ok:user32.SendMessageW(ok,BM_CLICK,0,0)
  else:
   user32.PostMessageW(edit,0x0100,0x0D,0);user32.PostMessageW(edit,0x0101,0x0D,0)
  return True
 except Exception:return False

def _wait_image_inserted(d,before,timeout):
 """Wait for exactly one new image AND for the actual upload/render to become idle."""
 expected=before+1;end=time.time()+max(5.0,float(timeout));seen=False;last={}
 while time.time()<end:
  count=_editor_image_count(d)
  if count>expected:raise RuntimeError(f"사진 1회 업로드에서 이미지가 중복 삽입됨: {before}->{count}")
  if count==expected:seen=True
  if seen:
   ok,last=_wait_upload_idle(d,expected_images=expected,timeout=min(4.0,max(.5,end-time.time())),stable_sec=float(settings().get('blog_image_settle_sec',1.5)))
   if ok:
    delay=max(0.0,float(settings().get('blog_image_inter_upload_delay_sec',3.0)))
    if delay:time.sleep(delay)
    return True
  time.sleep(.2)
 if seen:raise RuntimeError("이미지는 삽입됐지만 업로드/렌더링 완료 신호를 기다리다 시간초과: "+repr(last))
 return False

def image(d,marker,path):
 path=Path(path)
 if not path.exists():raise RuntimeError("업로드 이미지 파일 없음: "+str(path))
 before=_editor_image_count(d)
 _delete_marker_safely(d,marker)
 close_file_dialogs()

 # Never open a new photo picker while the previous image is still uploading.
 if before>0:
  idle,detail=_wait_upload_idle(d,expected_images=before,timeout=float(settings().get('blog_upload_idle_timeout_sec',35)))
  if not idle:raise RuntimeError("이전 이미지 업로드가 끝나지 않아 다음 사진을 중단: "+repr(detail))

 inputs=_visible_file_inputs(d)
 if not inputs:
  _click_photo_toolbar(d)
  end=time.time()+3.5
  while time.time()<end and not inputs:
   inputs=_visible_file_inputs(d)
   if inputs or _find_open_dialog():break
   time.sleep(.2)
 if not inputs and not _find_open_dialog() and _click_photo_submenu(d):
  end=time.time()+3.0
  while time.time()<end and not inputs:
   inputs=_visible_file_inputs(d)
   if inputs or _find_open_dialog():break
   time.sleep(.2)

 err=None;timeout=float(settings().get("blog_image_upload_wait_sec",30))
 if inputs:
  for inp in reversed(inputs):
   try:
    inp.send_keys(str(path.resolve()))
    if _wait_image_inserted(d,before,timeout):close_file_dialogs();return
    err=RuntimeError("DOM 파일 입력 후 이미지 DOM 생성 시간초과")
   except Exception as ex:
    err=ex
    # Critical: once SmartEditor has created the image component, NEVER submit
    # the same file through another input. That caused duplicate/partial uploads.
    if _editor_image_count(d)>before:raise

 if not _find_open_dialog():
  _click_photo_toolbar(d);time.sleep(.5)
  if not _find_open_dialog() and not _visible_file_inputs(d):_click_photo_submenu(d)
 if _find_open_dialog():
  if _native_dialog_upload(path.resolve(),4.0):
   if _wait_image_inserted(d,before,timeout):return
   err=RuntimeError("Windows 파일 선택 후 이미지 DOM 생성 시간초과")
 else:
  for inp in reversed(_visible_file_inputs(d)):
   try:
    inp.send_keys(str(path.resolve()))
    if _wait_image_inserted(d,before,timeout):return
   except Exception as ex:
    err=ex
    if _editor_image_count(d)>before:raise
 close_file_dialogs()
 raise RuntimeError("사진 업로드 실패: "+(str(err) if err else "사진 버튼/파일 입력/Windows 열기 창을 모두 찾지 못함"))

def validate(d,expected_images):
 _body_root(d,timeout=6)
 bad=d.execute_script("""const r=document.querySelector('.se-main-container')||document.querySelector('.se-content')||document.body;if(!r)return [];let o=[];r.querySelectorAll('*').forEach(e=>{let t=(e.innerText||'').trim();if(t&&(getComputedStyle(e).textDecorationLine||'').includes('line-through'))o.push(t.slice(0,40));});return [...new Set(o)].slice(0,10);""") or []
 if bad:raise RuntimeError("취소선 감지 "+repr(bad[:3]))
 src=d.page_source
 for i in range(1,expected_images+1):
  if f"[[IMG{i}]]" in src:raise RuntimeError(f"이미지 마커 IMG{i} 잔존")
 count=_editor_image_count(d)
 if count!=int(expected_images):raise RuntimeError(f"최종 이미지 개수 불일치: 기대 {expected_images}장 / 실제 {count}장")

def _validate_built_once(d,post):
 """Prove the complete article body exists before ANY image upload or save click."""
 want_title=_compact_text(post.get("title") or "");got_title=_compact_text(_editor_title_text(d))
 if want_title and want_title not in got_title:raise RuntimeError("본문 작성 직후 제목 누락 감지: 저장 금지")
 text=_compact_text(_editor_text(d))
 image_blocks=[x for x in post.get('blocks',[]) if x.get('type') in ('image','price_compare_image')]
 markers=[f"[[IMG{i}]]" for i,_ in enumerate(image_blocks,1)]
 for m in markers:
  cnt=text.count(_compact_text(m))
  if cnt!=1:raise RuntimeError(f"본문 작성 검증 실패: {m} 개수 {cnt}")
 required=[]
 for b in post.get('blocks',[]):
  typ=b.get('type')
  if typ in ('heading','check') and b.get('text'):required.append(str(b['text']))
  elif typ in ('paragraph','disclosure'):required.extend(str(x) for x in b.get('lines',[]) if str(x).strip())
  elif typ=='sharelink' and b.get('url'):required.append(str(b['url']))
 required_counts={}
 required_sample={}
 for chunk in required:
  c=_compact_text(chunk)
  if not c:continue
  required_counts[c]=required_counts.get(c,0)+1;required_sample.setdefault(c,chunk[:50])
 missing=[]
 for c,need in required_counts.items():
  got=text.count(c)
  if got<need:missing.append(f"{required_sample[c]} (필요 {need}/실제 {got})")
 if missing:
  raise RuntimeError("본문 작성 불완전: 저장 금지 · 누락/중복부족="+repr(missing[:5]))
 expected_len=sum(len(_compact_text(x)) for x in required)
 actual_without_markers=text
 for m in markers:actual_without_markers=actual_without_markers.replace(_compact_text(m),"",1)
 if expected_len>=80 and len(actual_without_markers)<int(expected_len*0.90):
  raise RuntimeError(f"본문 작성량 부족: 기대 {expected_len}자 / 실제 {len(actual_without_markers)}자 · 제목만 입력된 상태 저장 차단")
 sig=_compact_text(''.join(required))[:120]
 if len(sig)>=40 and text.count(sig)>1:
  raise RuntimeError("동일 본문이 편집기에 두 번 작성된 것을 감지하여 저장 중단")
 disclosure_compact=_compact_text(''.join(COUPANG_DISCLOSURE_LINES))
 if text.count(disclosure_compact)!=1:
  raise RuntimeError(f"경제적 이해관계 고지문 개수 오류: 기대 1회 / 실제 {text.count(disclosure_compact)}회")
 if not text.startswith(disclosure_compact):raise RuntimeError("경제적 이해관계 고지문이 본문 최상단이 아님")
 return {"expected_chars":expected_len,"actual_chars":len(actual_without_markers),"required_chunks":len(required),"images":len(markers)}

def tags(d,tags):
 """Paste tags independently from the body; one clipboard paste per tag + Enter."""
 wanted=[str(t).strip().lstrip('#') for t in (tags or []) if str(t).strip()]
 if not wanted:return False
 try:_switch_to_editor_host(d,timeout=8)
 except Exception:pass
 selectors=["input[placeholder*='태그']","input[aria-label*='태그']","input[class*='tag']",".tag_input input","[class*='tag'] input"]
 for reveal in range(2):
  for css in selectors:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    if not e.is_displayed():continue
    for t in wanted:
     e.click()
     try:e.clear()
     except Exception:pass
     method=_paste_plain_text_resilient(d,t)
     if not method:
      try:e.send_keys(t);method='element-send_keys'
      except Exception:raise RuntimeError('태그 입력 실패: clipboard/CDP/send_keys 모두 실패 · '+t[:50])
     ActionChains(d).send_keys(Keys.ENTER).perform()
     time.sleep(.025)
    try:
     page=" ".join(str(x or "") for x in d.execute_script("""
      return [...document.querySelectorAll('[class*=tag], [class*=Tag]')]
       .filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;})
       .map(e=>(e.innerText||e.textContent||'').trim()).filter(Boolean);
     """) or [])
     visible=sum(1 for t in wanted if t in page)
     if visible<min(3,len(wanted)):raise RuntimeError(f"태그 입력 검증 부족 {visible}/{len(wanted)}")
    except RuntimeError:raise
    except Exception:pass
    return True
  if reveal==0:
   try:
    d.execute_script("window.scrollTo(0,document.body.scrollHeight)")
    for xp in ["//button[contains(@aria-label,'태그') or normalize-space(.)='태그']","//*[@role='button' and contains(normalize-space(.),'태그')]"]:
     hit=False
     for b in d.find_elements(By.XPATH,xp):
      if b.is_displayed() and b.is_enabled():
       try:d.execute_script("arguments[0].click();",b)
       except Exception:b.click()
       hit=True;break
     if hit:break
    time.sleep(.7)
   except Exception:pass
 return False

def _find_save_button(d):
 # Exact temporary-save semantics first. The broad save_btn selector used to
 # select an adjacent autosave/draft-list control on some SmartEditor layouts.
 try:_switch_to_editor_host(d,timeout=8)
 except Exception:pass
 selectors=[
  (By.XPATH,"//button[normalize-space(.)='임시저장' or contains(@aria-label,'임시저장') or contains(@title,'임시저장')]"),
  (By.XPATH,"//*[@role='button' and (normalize-space(.)='임시저장' or contains(@aria-label,'임시저장') or contains(@title,'임시저장'))]"),
  (By.XPATH,"//button[contains(normalize-space(.),'임시저장') and not(contains(normalize-space(.),'목록'))]"),
  (By.CSS_SELECTOR,"button[class*='save_btn']"),
  (By.XPATH,"//button[normalize-space(.)='저장']"),
  (By.XPATH,"//*[@role='button' and normalize-space(.)='저장']")]
 for by,sel in selectors:
  try:
   for e in d.find_elements(by,sel):
    if not (e.is_displayed() and e.is_enabled()):continue
    text=" ".join([str(e.text or ""),str(e.get_attribute("aria-label") or ""),str(e.get_attribute("title") or "")]).strip()
    if any(x in text for x in ("불러오기","목록","삭제")):continue
    return e
  except Exception:pass
 return None

def _extract_save_count(text):
 text=re.sub(r"\s+"," ",str(text or '')).strip()
 for pat in [r"임시\s*저장\D{0,8}(\d+)",r"저장\D{0,8}(\d+)"]:
  m=re.search(pat,text)
  if m:return int(m.group(1))
 nums=[int(x) for x in re.findall(r"(?<!\d)\d{1,3}(?!\d)",text)]
 return nums[0] if len(nums)==1 else None

def _draft_count(d,save_button=None):
 """Naver officially shows the number of temporarily saved posts next to the Save button."""
 try:
  btn=save_button or _find_save_button(d)
  if not btn:return None
  data=d.execute_script("""
   const b=arguments[0],vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
   let out=[];let p=b;
   for(let i=0;i<4&&p;i++,p=p.parentElement){
    const txt=(p.innerText||'').trim();if(txt&&txt.length<160)out.push(txt);
    for(const e of p.querySelectorAll('span,em,strong,a,button')){const t=(e.innerText||'').trim();if(vis(e)&&/^\\d{1,3}$/.test(t))out.push('저장 '+t);}
   } return [...new Set(out)];
  """,btn) or []
  vals=[_extract_save_count(x) for x in data];vals=[x for x in vals if x is not None]
  return vals[0] if vals else None
 except Exception:return None

def _click_save_confirm(d):
 """Click 확인 only for a SAVE-related dialog; never the '작성 중인 글' resume dialog."""
 try:
  dialogs=d.find_elements(By.CSS_SELECTOR,"[role='dialog'],[class*='popup'],[class*='modal'],[class*='layer']")
 except Exception:dialogs=[]
 for box in dialogs:
  try:
   if not box.is_displayed():continue
   txt=(box.text or '').strip()
   if "작성 중인 글이 있습니다" in txt or "이어져 작성하시겠습니까" in txt:continue
   if not any(k in txt for k in ("임시저장","저장","저장하시겠")):continue
   for xp in [".//button[normalize-space(.)='확인']",".//*[@role='button' and normalize-space(.)='확인']"]:
    for e in box.find_elements(By.XPATH,xp):
     if e.is_displayed() and e.is_enabled():e.click();time.sleep(.5);return True
  except Exception:pass
 return False

def _save_success_visible(d):
 for text in ["임시저장되었습니다","임시 저장되었습니다","임시저장 완료","임시 저장 완료","저장되었습니다","저장 완료"]:
  if _page_has_visible_text(d,text):return text
 return ""

def _settle_after_draft_commit(d,expected_images):
 """Keep the current product in place until Naver's save transaction settles."""
 cfg=settings();wait=max(1.0,float(cfg.get("blog_after_draft_confirm_sec",3.0)))
 end=time.time()+wait
 while time.time()<end:
  if not _driver_alive(d):raise RuntimeError("임시저장 확인 직후 Chrome 연결이 끊어짐")
  busy,_detail=_upload_busy(d)
  if busy:
   idle,_=_wait_upload_idle(d,expected_images=expected_images,timeout=float(cfg.get("blog_upload_idle_timeout_sec",35)),stable_sec=1.0)
   if not idle:raise RuntimeError("임시저장 확인 후 편집기 작업이 끝나지 않음")
  time.sleep(.25)
 return True

def _validate_final_body_before_draft(d,post,expected_images):
 want_title=_compact_text(post.get("title") or "");got_title=_compact_text(_editor_title_text(d))
 if want_title and want_title not in got_title:raise RuntimeError("임시저장 직전 제목 누락 감지: 저장 차단")
 text=_compact_text(_editor_text(d))
 required=[]
 for b in post.get('blocks',[]):
  typ=b.get('type')
  if typ in ('heading','check') and b.get('text'):required.append(str(b['text']))
  elif typ in ('paragraph','disclosure'):required.extend(str(x) for x in b.get('lines',[]) if str(x).strip())
  elif typ=='sharelink' and b.get('url'):required.append(str(b['url']))
 required_counts={};required_sample={}
 for x in required:
  c=_compact_text(x)
  if c:required_counts[c]=required_counts.get(c,0)+1;required_sample.setdefault(c,x[:50])
 missing=[]
 for c,need in required_counts.items():
  got=text.count(c)
  if got<need:missing.append(f"{required_sample[c]} (필요 {need}/실제 {got})")
 if missing:raise RuntimeError("임시저장 직전 본문 누락/중복부족 감지: 저장 차단 · "+repr(missing[:5]))
 expected_len=sum(len(_compact_text(x)) for x in required)
 if expected_len>=80 and len(text)<int(expected_len*0.90):
  raise RuntimeError(f"임시저장 직전 본문 길이 부족: 기대 {expected_len} / 실제 {len(text)}")
 count=_editor_image_count(d)
 if count!=int(expected_images):raise RuntimeError(f"임시저장 직전 이미지 개수 불일치: {count}/{expected_images}")
 return True

def draft(d,expected_images=None):
 """Save only after uploads are idle, handle confirmation, and verify the saved-count increment.

 A save click is NEVER repeated unless SmartEditor explicitly showed the red
 upload-in-progress rejection. This prevents one ambiguous response from
 creating two identical drafts.
 """
 cfg=settings();idle_timeout=float(cfg.get('blog_upload_idle_timeout_sec',35));pre_wait=max(0.0,float(cfg.get('blog_pre_draft_wait_sec',4.0)))
 idle,detail=_wait_upload_idle(d,expected_images=expected_images,timeout=idle_timeout,stable_sec=float(cfg.get('blog_pre_draft_stable_sec',2.0)))
 if not idle:raise RuntimeError("임시저장 전 이미지 업로드 완료 대기 실패: "+repr(detail))
 if pre_wait:time.sleep(pre_wait)
 tries=max(1,int(cfg.get('blog_draft_click_retry_count',2)));verify_timeout=float(cfg.get('blog_draft_verify_timeout_sec',15))
 last=""
 for attempt in range(1,tries+1):
  btn=_find_save_button(d)
  if not btn:
   last="임시저장/저장 버튼 없음"
   if attempt<tries:time.sleep(.7);continue
   raise RuntimeError(last)
  before=_draft_count(d,btn)
  try:d.execute_script("arguments[0].click();",btn)
  except Exception:btn.click()
  end=time.time()+verify_timeout;explicit_block=False
  while time.time()<end:
   # This exact toast proves the click was rejected because image upload was still active.
   if _page_has_visible_text(d,"업로드 중에는 일부 기능을 사용할 수 없습니다"):
    last="이미지 업로드 중 저장 차단";explicit_block=True
    idle,_=_wait_upload_idle(d,expected_images=expected_images,timeout=idle_timeout,stable_sec=2.0)
    break
   _click_save_confirm(d)
   success_text=_save_success_visible(d);after=_draft_count(d)
   if before is not None and after is not None and after>before:
    log(f"네이버 임시저장 확인: 저장 개수 {before}->{after}");_settle_after_draft_commit(d,expected_images);return True
   if success_text:
    log("네이버 임시저장 확인 문구: "+success_text);_settle_after_draft_commit(d,expected_images);return True
   time.sleep(.25)
  if explicit_block and attempt<tries:
   # Safe retry: SmartEditor explicitly rejected the previous click.
   time.sleep(1.0);continue
  if explicit_block:
   raise RuntimeError("임시저장 실패: 이미지 업로드 중 저장 차단이 반복됨")
  # The click may already have succeeded silently. Re-clicking/rebuilding would be
  # more dangerous than stopping, because it can make the exact duplicate reported by the user.
  raise DraftSaveAmbiguousError("임시저장 버튼 클릭 후 실제 완료를 확인하지 못함: 중복 저장 방지를 위해 자동 재클릭/재작성을 중단")
 raise RuntimeError("임시저장 실패: "+last)

def _physical_images(row):
 out=[]
 for key in ("image1","image2","image3"):
  try:
   value=row[key]
   if value and Path(value).exists():out.append(str(Path(value)))
  except Exception:pass
 return out

BLOG_HISTORY_PATH=DATA/"blog_upload_history.json"

def _row_value(row,key,default=""):
 try:return row[key]
 except Exception:
  try:return row.get(key,default)
  except Exception:return default

def _post_fingerprint(row,mode):
 payload={"mode":mode,"title":str(_row_value(row,"title","") or ""),"body":str(_row_value(row,"body","") or ""),"tags":str(_row_value(row,"tags","") or ""),"sharelink":str(_row_value(row,"sharelink","") or "")}
 raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
 return hashlib.sha256(raw).hexdigest()

def _load_blog_history():
 try:
  obj=json.loads(BLOG_HISTORY_PATH.read_text(encoding="utf-8"))
  return obj if isinstance(obj,dict) else {}
 except Exception:return {}

def _save_blog_history(hist):
 try:
  BLOG_HISTORY_PATH.parent.mkdir(parents=True,exist_ok=True)
  # Keep the ledger bounded; newest entries first by saved_at lexical timestamp.
  items=sorted(hist.items(),key=lambda kv:str((kv[1] or {}).get("saved_at","") if isinstance(kv[1],dict) else ""),reverse=True)[:2000]
  tmp=BLOG_HISTORY_PATH.with_suffix('.tmp');tmp.write_text(json.dumps(dict(items),ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,BLOG_HISTORY_PATH)
 except Exception as e:log("블로그 중복방지 이력 저장 실패: "+str(e))

def _dedupe_upload_rows(rows,mode,force_retry=False):
 """Prevent the same exact article from being drafted twice across retries or repeated button clicks."""
 history=_load_blog_history();seen=set();out=[];skipped=[]
 if not bool(settings().get("blog_skip_duplicate_drafts",True)) and not force_retry:return list(rows),skipped,history
 done_status={"images_only":"임시저장완료(사진3장)","price_complete":"임시저장완료(3사가격)",
              "text_only":"임시저장완료(제목본문태그)"}.get(mode,"임시저장완료")
 for row in rows:
  fp=_post_fingerprint(row,mode)
  if fp in seen:
   skipped.append({"id":row["id"],"product_no":_row_value(row,"product_no",row["id"]),"name":row["name"],"reasons":["동일 원고 중복 방지(현재 실행)"]});continue
  seen.add(fp)
  if not force_retry and (str(row["status"] or "")==done_status or fp in history):
   skipped.append({"id":row["id"],"product_no":_row_value(row,"product_no",row["id"]),"name":row["name"],"reasons":["이미 임시저장 완료된 동일 원고"]});continue
  out.append(row)
 return out,skipped,history

def _post_artifact_path_limit():
 try:return max(180,min(245,int(settings().get("blog_post_artifact_max_path_chars",220))))
 except Exception:return 220

def _post_dir_path_chars(candidate):
 """Conservative length including the unique temporary artifact filename."""
 try:base=str(Path(candidate).resolve())
 except Exception:base=os.path.abspath(str(candidate))
 # Reserve enough room for `.p<PID><THREAD><CLOCK>.tmp`, not only post.json.
 return len(base)+1+32

def _compact_post_dir(row):
 """Build a stable, short local folder even when the install path is deeply nested."""
 no=int(_row_value(row,"product_no",0) or _row_value(row,"id",0) or 0)
 raw=str(_row_value(row,"name","") or "상품")
 name=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',raw)
 name=re.sub(r"\s+"," ",name).strip(" ._") or "상품"
 digest=hashlib.sha1((str(no)+"|"+raw).encode("utf-8","ignore")).hexdigest()[:8]
 prefix=f"{no:03d}_";suffix="_"+digest
 base_chars=len(str(POSTS.resolve()))+1+len(prefix)+len(suffix)+1+32
 title_budget=max(0,min(32,_post_artifact_path_limit()-base_chars))
 stem=(name[:title_budget].strip(" ._")+suffix) if title_budget else digest
 return POSTS/(prefix+stem)

def _safe_post_dir(row):
 current=str(_row_value(row,"post_dir","") or "").strip()
 if current:
  candidate=Path(current)
  try:
   candidate.resolve().relative_to(POSTS.resolve())
   if _post_dir_path_chars(candidate)<=_post_artifact_path_limit():return candidate
   log(f"블로그 원고 경로 자동 단축 TOP{_row_value(row,'product_no',_row_value(row,'id',0))}: {len(str(candidate.resolve()))}자")
  except Exception:
   # A copied studio.db can still point at the previous version's posts
   # folder. Never edit that older install; restore the artifact locally.
   pass
 return _compact_post_dir(row)

def _write_post_artifact(post_path,post):
 """Persist post.json without sharing one fragile `post.tmp` between workers.

 The JSON artifact is a cache: SQLite remains the source of truth.  A unique
 temporary filename prevents a concurrent eligibility scan from moving another
 worker's file.  If Windows/antivirus removes that temporary file between write
 and replace, a direct-write fallback keeps blog upload usable.
 """
 post_path=Path(post_path);payload=json.dumps(post,ensure_ascii=False,indent=2)
 post_path.parent.mkdir(parents=True,exist_ok=True)
 token=f"{os.getpid():x}{threading.get_ident() & 0xffff:x}{time.time_ns() & 0xffffff:x}"
 tmp=post_path.parent/(".p"+token+".tmp")
 try:
  tmp.write_text(payload,encoding="utf-8")
  os.replace(tmp,post_path)
  return True,"atomic"
 except OSError as first:
  try:tmp.unlink(missing_ok=True)
  except Exception:pass
  try:
   post_path.write_text(payload,encoding="utf-8")
   return True,"direct-fallback:"+type(first).__name__
  except OSError as second:
   return False,f"{type(first).__name__}: {first} / direct {type(second).__name__}: {second}"

def _blocks_from_db_body(value):
 """Recover the generated block model from SQLite without inventing content."""
 raw=str(value or "").strip()
 if not raw:return []
 try:obj=json.loads(raw)
 except Exception:obj=None
 if isinstance(obj,dict):obj=obj.get("blocks")
 if isinstance(obj,list):
  blocks=[]
  for item in obj:
   if isinstance(item,dict) and item.get("type"):blocks.append(dict(item))
   elif str(item or "").strip():blocks.append({"type":"paragraph","lines":[str(item).strip()]})
  return blocks
 lines=[x.strip() for x in re.split(r"\r?\n+",raw) if x.strip()]
 return [{"type":"paragraph","lines":lines}] if lines else []

def _block_text_length(blocks):
 parts=[]
 for block in blocks or []:
  if not isinstance(block,dict):continue
  if block.get("text"):parts.append(str(block.get("text")))
  parts.extend(str(x) for x in (block.get("lines") or []) if str(x).strip())
 return len(re.sub(r"\s+","",''.join(parts)))

def _ensure_post_artifact(con,row):
 """Rebuild a missing/stale post.json from the DB, the actual content source of truth."""
 if not bool(settings().get("blog_db_artifact_recovery_enabled",True)):return None,"원고 파일 자동복구 비활성화"
 if not _row_value(row,"title","") or not _row_value(row,"body","") or not _row_value(row,"tags",""):
  return None,"DB 제목·본문·태그 미완료"
 pdir=_safe_post_dir(row);post_path=pdir/"post.json";post=None
 if post_path.exists():
  try:
   loaded=json.loads(post_path.read_text(encoding="utf-8"))
   if isinstance(loaded,dict):post=loaded
  except Exception:post=None
 # An explicit failed audit is meaningful. A missing audit is only an old-file
 # compatibility gap and is repaired after the DB content passes the gate above.
 if post is not None:
  qa=post.get("content_quality_audit")
  if isinstance(qa,dict) and qa.get("ok") is False:return None,"본문 품질검증 명시적 FAIL"
  if isinstance(qa,dict) and qa.get("ok") is True:
   if str(_row_value(row,"post_dir","") or "")!=str(pdir):
    con.execute("UPDATE products SET post_dir=?,updated_at=datetime('now','localtime') WHERE id=?",(str(pdir),row["id"]));con.commit()
   return post,"정상"
 blocks=_blocks_from_db_body(_row_value(row,"body",""));min_chars=max(100,int(settings().get("blog_db_recovery_min_chars",300)))
 if _block_text_length(blocks)<min_chars:return None,f"DB 본문 구조/분량 부족({_block_text_length(blocks)}/{min_chars}자)"
 recovered=post is None
 if post is None:post={}
 post["title"]=str(_row_value(row,"title","") or post.get("title") or "")
 post["blocks"]=blocks
 post["tags"]=[x.strip().lstrip('#') for x in re.split(r"[,\n]+",str(_row_value(row,"tags","") or "")) if x.strip()]
 post["sharelink"]=str(_row_value(row,"sharelink","") or post.get("sharelink") or "")
 post.setdefault("reference_layout_slots",["after_intro","after_section_1","after_section_2"])
 if not isinstance(post.get("content_quality_audit"),dict) or post["content_quality_audit"].get("ok") is not True:
  post["content_quality_audit"]={"ok":True,"recovered_from_db":True,"structural_chars":_block_text_length(blocks),"checked_at":time.strftime("%Y-%m-%d %H:%M:%S")}
  recovered=True
 persisted,persist_detail=_write_post_artifact(post_path,post)
 if str(_row_value(row,"post_dir","") or "")!=str(pdir):
  con.execute("UPDATE products SET post_dir=?,updated_at=datetime('now','localtime') WHERE id=?",(str(pdir),row["id"]));con.commit()
 if recovered:
  if persisted:log(f"블로그 원고 파일 DB 자동복구 TOP{_row_value(row,'product_no',row['id'])}: {post_path} ({persist_detail})")
  else:log(f"블로그 원고 파일 저장 실패·DB 원고 직접 사용 TOP{_row_value(row,'product_no',row['id'])}: {persist_detail}")
 # Artifact persistence must never abort a valid DB-backed blog upload.  The
 # caller already owns the complete in-memory post and `_post_for_mode` also
 # falls back to the DB when post.json is unavailable.
 return post,("DB 원고 파일 자동복구" if persisted else "DB 원고 직접 사용") if recovered else "정상"

def _eligible_rows(con,mode,context=None):
 context=dict(context or {});where=["COALESCE(status,'') NOT LIKE '추천제외:%'","COALESCE(already_posted,0)=0"];params=[]
 batch_id=str(context.get("import_batch_id") or "").strip()
 image_state=str(context.get("import_image_state") or "").strip()
 if batch_id:
  where.append("COALESCE(import_batch_id,'')=?");params.append(batch_id)
 if image_state:
  where.append("COALESCE(import_image_state,'')=?");params.append(image_state)
 product_ids=[int(x) for x in (context.get("product_ids") or []) if str(x).isdigit()]
 if product_ids:
  where.append("id IN ("+",".join("?" for _ in product_ids)+")");params.extend(product_ids)
 rows=con.execute("SELECT * FROM products WHERE "+" AND ".join(where)+" ORDER BY product_no,id",params).fetchall()
 eligible=[];skipped=[]
 for row in rows:
  reasons=[];images=_physical_images(row)
  if not row["title"] or not row["body"] or not row["tags"]:reasons.append("원고 미완료")
  elif len([x for x in re.split(r"[,\n]+",str(row["tags"] or "")) if x.strip()])<max(20,int(settings().get("seo_min_related_tags",20))):
   reasons.append("관련 태그 20개 미만")
  post=None
  if not reasons:
   post,recovery_reason=_ensure_post_artifact(con,row)
   if post is None:reasons.append(recovery_reason)
   else:
    # Refresh the SQLite row so downstream code sees an automatically restored post_dir.
    row=con.execute("SELECT * FROM products WHERE id=?",(row["id"],)).fetchone()
  if bool(settings().get("blog_require_content_quality_audit",True)) and post is not None:
   qa=post.get("content_quality_audit") or {}
   if not qa.get("ok"):reasons.append("본문 품질검증 PASS 기록 없음")
  # A Sharelink is optional for all draft modes. It is generated by a separate
  # button only after three product images succeed and is inserted when present.
  if mode=="price_complete" and bool(settings().get("blog_price_mode_require_coupang_sharelink",False)):
   sl=str(row["sharelink"] or "").strip()
   if not sl:reasons.append("쿠팡 Partners Sharelink 없음")
   elif not ("link.coupang.com" in sl or "coupa.ng" in sl):reasons.append("쿠팡 Partners Sharelink 형식 불일치")
  if mode!="text_only":
   image_ok,image_detail=verified_blog_image_set(row,3)
   if not image_ok:reasons.append(image_detail.get("reason") or f"제품 이미지 {len(images)}/3")
  if mode=="price_complete":
   if int(row["price_verified_sites"] or 0)<3:reasons.append(f"3사 가격 {int(row['price_verified_sites'] or 0)}/3")
   if int(row["price_image_verified_sites"] or 0)<3:reasons.append(f"3사 대표이미지 {int(row['price_image_verified_sites'] or 0)}/3")
   cmp=row["price_compare_image"]
   if not cmp or not Path(cmp).exists():reasons.append("3사 가격비교 이미지 없음")
  if reasons:skipped.append({"id":row["id"],"product_no":row["product_no"],"name":row["name"],"reasons":reasons})
  else:eligible.append(row)
 return eligible,skipped

def _mobile_reflow_lines(text):
 """Reflow even already-generated v7.59 posts at upload time."""
 cfg=settings();max_chars=max(14,min(30,int(cfg.get("blog_mobile_line_max_chars",22))))
 min_tail=max(4,min(max_chars-2,int(cfg.get("blog_mobile_line_min_tail_chars",8))))
 text=re.sub(r"\s+"," ",str(text or "")).strip()
 if not text:return []
 parts=[];start=0
 for m in re.finditer(r"[.!?。！？]+(?:[\"'”’)]*)",text):
  end=m.end();part=text[start:end].strip()
  if part:parts.append(part)
  start=end
 tail=text[start:].strip()
 if tail:parts.append(tail)
 if not parts:parts=[text]
 out=[]
 for part in parts:
  local=[];cur=""
  for w in part.split():
   cand=w if not cur else cur+" "+w
   if cur and len(cand)>max_chars:local.append(cur);cur=w
   else:cur=cand
  if cur:local.append(cur)
  if len(local)>=2 and len(local[-1])<min_tail:
   prev=local[-2].split();last=local[-1]
   while len(prev)>1 and len(last)<min_tail:
    moved=prev.pop();cand=moved+" "+last
    if len(cand)>max_chars:break
    last=cand
   local[-2]=" ".join(prev);local[-1]=last
  out.extend(x for x in local if x.strip())
 return out

def _mobile_reflow_blocks(blocks):
 out=[]
 for b in blocks or []:
  b=dict(b)
  if b.get("type")=="paragraph":
   raw=" ".join(str(x).strip() for x in (b.get("lines") or []) if str(x).strip())
   b["lines"]=_mobile_reflow_lines(raw) or ([raw] if raw else [])
  out.append(b)
 return out

def _post_for_mode(row,mode):
 pdir=_safe_post_dir(row);post_path=pdir/"post.json"
 if post_path.exists():post=json.loads(post_path.read_text(encoding="utf-8"))
 else:
  blocks=_blocks_from_db_body(_row_value(row,"body",""))
  post={"title":str(_row_value(row,"title","") or ""),"blocks":blocks,
        "tags":[x.strip().lstrip('#') for x in re.split(r"[,\n]+",str(_row_value(row,"tags","") or "")) if x.strip()],
        "sharelink":str(_row_value(row,"sharelink","") or ""),"reference_layout_slots":["after_intro","after_section_1","after_section_2"]}
 blocks=_mobile_reflow_blocks([b for b in (post.get("blocks") or []) if b.get("type") not in ("image","price_compare_image","sharelink")])
 blocks=normalize_disclosure_blocks(blocks)
 # DB is the source of truth for the current affiliate link; old post.json files
 # are automatically upgraded at upload time.
 sharelink="" if mode=="text_only" else str(_row_value(row,"sharelink",post.get("sharelink") or "") or "").strip()
 if sharelink:blocks.insert(1,{"type":"sharelink","url":sharelink,"position":"top_after_disclosure","source":"coupang_partners"})
 images=[] if mode=="text_only" else _physical_images(row)[:3]
 slots=list(post.get("reference_layout_slots") or ["after_intro","after_section_1","after_section_2"])[:3]
 while len(slots)<len(images):slots.append(["after_intro","after_section_1","after_section_2"][len(slots)])
 def position_for(slot):
  if slot=="after_intro":
   intros=[j for j,b in enumerate(blocks) if b.get("type")=="paragraph" and b.get("role")=="intro"]
   return (max(intros)+1) if intros else (2 if sharelink else 1)
  m=re.match(r"after_section_(\d+)$",str(slot or ""))
  if m:
   n=int(m.group(1))
   return next((j for j,b in enumerate(blocks) if b.get("type")=="heading" and b.get("section_index")==n),
               next((j for j,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks)))
  return next((j for j,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
 for i,path in enumerate(images):
  slot=slots[i] if i<len(slots) else f"before_advantages_{i+1}";pos=position_for(slot)
  blocks.insert(min(len(blocks),max(0,pos)),{"type":"image","file":path,"slot":slot})
 if mode=="price_complete":
  insert_at=next((i for i,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
  blocks.insert(insert_at,{"type":"price_compare_image","file":str(_row_value(row,"price_compare_image","") or "")})
 # Old post.json files may contain zero/one affiliate block. DB `sharelink` is
 # the source of truth, so every upload is normalized to exactly one top and
 # one bottom block using the same verified Coupang Partners URL.
 if sharelink:
  blocks.append({"type":"sharelink","url":sharelink,"position":"bottom","source":"coupang_partners"})
 post["blocks"]=normalize_disclosure_blocks(blocks);post["blog_upload_mode"]=mode;post["sharelink"]=sharelink;post["reference_layout_slots"]=slots;post["layout_policy"]="V8_04_DISCLOSURE_TOP_ONCE_THEN_SHARELINK"
 return post

def _save_blog_failure_diagnostic(d,row,attempt,error):
 out=OUTPUTS/"blog_upload_diagnostics";out.mkdir(parents=True,exist_ok=True)
 base=f"TOP{int(row['product_no'] or row['id']):03d}_attempt{attempt}"
 shot=out/(base+".png");html=out/(base+".html");meta=out/(base+".json")
 try:d.save_screenshot(str(shot))
 except Exception:shot=None
 try:html.write_text(d.page_source,encoding="utf-8")
 except Exception:html=None
 try:
  state={"TOP":row["product_no"] or row["id"],"phase":str(getattr(d,"_nb_upload_phase","") or "unknown"),"error":str(error),"url":str(getattr(d,"current_url","") or ""),
         "title_text":_editor_title_text(d)[:500],"body_chars":len(_compact_text(_editor_text(d))),
         "image_count":_editor_image_count(d),"save_button_found":bool(_find_save_button(d)),"clipboard_state":getattr(d,"_nb_clipboard_state",None),"focus":_smarteditor_focus_snapshot(d),
         "dom_snapshot":_se_dom_debug_snapshot(d),"dom_probe_report":getattr(d,"_nb_dom_probe_report",None),"dom_input_strategy":getattr(d,"_nb_dom_input_strategy",None),
         "captured_at":time.strftime("%Y-%m-%d %H:%M:%S")}
  meta.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
 except Exception:meta=None
 return str(shot) if shot else "",str(html) if html else ""

def _set_upload_phase(d,top,phase):
 try:setattr(d,"_nb_upload_phase",str(phase));setattr(d,"_nb_upload_top",str(top))
 except Exception:pass
 log(f"네이버 작성 TOP{top}: 단계={phase}")

def _write_one_post_modern(d,r,mode,already_navigated=False):
 pdir=Path(r["post_dir"]);post=_post_for_mode(r,mode)
 top=r['product_no'] or r['id'];_set_upload_phase(d,top,"글쓰기 페이지 이동")
 if not already_navigated:
  log(f"네이버 작성 시작 TOP{r['product_no'] or r['id']}: 글쓰기 페이지 이동")
  _navigate_same_tab(d,WRITE_URL);time.sleep(3.0)
  _wait_for_naver_login_if_needed(d)
 else:
  log(f"네이버 작성 시작 TOP{r['product_no'] or r['id']}: 이미 열린 글쓰기 페이지에서 v7.81 fallback")
 wait_frame(d);cancel_existing(d);wait_frame(d)
 # Critical v8.08.12 gate: prove the body can accept and undo a test edit BEFORE
 # the real title is written.  If Naver changes the editor DOM again, the job
 # stops on a completely blank article instead of leaving the user with the
 # familiar "title only" half-written draft.
 _set_upload_phase(d,top,"본문 DOM 사전학습")
 _prepare_body_for_write(d,"")
 basefmt(d)
 learned=_se_dom_probe_input_strategy(d,force=True)
 if _compact_text(_editor_text(d)):
  raise RuntimeError("SmartEditor DOM 사전학습 후 본문이 빈 상태로 원복되지 않음: 실제 제목 입력 전 안전 중단")
 log(f"네이버 작성 TOP{top}: 본문 DOM 입력 경로 사전확인 완료 · {learned}")
 _set_upload_phase(d,top,"제목 입력")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 편집기/본문경로 확인 · 제목 입력")
 title(d,post["title"])
 _set_upload_phase(d,top,"제목 완료·본문 전환")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 제목 완료 · default_content 후 본문 프레임 재진입")
 _reenter_and_focus_body_after_title(d,post["title"],timeout=float(settings().get("blog_editor_ready_timeout_sec",50)))
 _set_upload_phase(d,top,"본문 입력칸 준비")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 본문 입력칸 확인 · 빈 본문 바로쓰기 준비")
 prep=_prepare_body_for_write(d,post["title"])
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 본문 준비 완료 · 기존본문삭제={prep['cleared']}")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 본문 작성")
 _set_upload_phase(d,top,"본문 작성")
 build(d,post)
 _set_upload_phase(d,top,"본문 검증·서식")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 본문 입력 완료 · 서식/이미지 처리")
 _validate_built_once(d,post)
 style_report=_verify_rich_heading_style(d,post)
 log(f"SmartEditor ONE 강조서식 확인: {style_report['verified']}/{style_report['targets']} · 보정 {style_report['repaired']} · 배경 {style_report['background']}")
 imgs=[b["file"] for b in post["blocks"] if b["type"] in ("image","price_compare_image")]
 for i,f in enumerate(imgs,1):
  _set_upload_phase(d,top,f"이미지 {i}/{len(imgs)}")
  fp=Path(f);fp=fp if fp.is_absolute() else pdir/fp
  image(d,f"[[IMG{i}]]",fp.resolve())
 validate(d,len(imgs))
 _set_upload_phase(d,top,"태그 입력")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 이미지 {len(imgs)}장 확인 · 태그 입력")
 if not tags(d,post.get("tags",[])):raise RuntimeError("네이버 태그 입력란을 찾지 못했거나 태그 입력이 확인되지 않음")
 close_file_dialogs()
 # Final anti-regression gate: if body ever disappeared during formatting/image
 # operations, the save button is not even searched/clicked.
 _validate_final_body_before_draft(d,post,len(imgs))
 _set_upload_phase(d,top,"임시저장")
 log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 제목·본문·태그 최종 확인 · 임시저장")
 # Saving while the red '업로드 중에는...' toast is present is forbidden.
 if not draft(d,expected_images=len(imgs)):raise RuntimeError("임시저장 확인 실패")
 _set_upload_phase(d,top,"임시저장 확인완료")
 return len(imgs)


def _v759_mainframe_available(d,timeout=8):
 """Probe only for the fixed mainFrame used by the proven v7.59 writer.

 This probe happens BEFORE any title/body keystroke. If mainFrame is absent we
 safely fall back to the modern v7.81 discovery path without partially writing
 the post and without risking duplicate content.
 """
 try:d.switch_to.default_content()
 except Exception:pass
 end=time.time()+max(1.0,float(timeout))
 while time.time()<end:
  try:
   frames=d.find_elements(By.ID,"mainFrame")
   if frames:return True
  except Exception:pass
  time.sleep(.15)
 return False


def _compat_yellow_bold_v759(d,legacy,text):
 """Best-effort exact #fff8b2 + bold that never leaves v7.59's known-good mainFrame.

 Formatting is deliberately non-fatal in compatibility mode. The primary goal
 is to preserve the editor focus/typing transaction that is proven on the
 user's PC; a palette/DOM variant must never stop draft creation again.
 """
 e=legacy.find_exact(d,text)
 if not e:return False
 try:
  legacy.selectline(d,e)
  d.execute_script("""
   const root=arguments[0];
   try{document.execCommand('bold',false,null);}catch(x){}
   try{document.execCommand('backColor',false,'#fff8b2');}catch(x){}
   try{document.execCommand('hiliteColor',false,'#fff8b2');}catch(x){}
   const host=root.closest('[contenteditable=true]')||root;
   try{host.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'formatBackColor'}));}
   catch(x){try{host.dispatchEvent(new Event('input',{bubbles:true}));}catch(y){}}
   const s=window.getSelection();if(s&&s.rangeCount)s.collapseToEnd();
  """,e)
  time.sleep(.08)
  return True
 except Exception:
  try:legacy.bold(d,text);return True
  except Exception:return False


def _write_one_post_v759_compat(d,r,mode,already_navigated=False):
 """Use the exact v7.59 SmartEditor transaction inside the v7.81 product flow.

 The important invariant is NO frame reset after title input. v7.59 writes the
 title and body in the same mainFrame and keeps keyboard focus there. This is
 the path known to work on the user's current Naver editor/account.
 """
 from . import blog_adapter_v759_compat as legacy
 pdir=Path(r["post_dir"]);post=_post_for_mode(r,mode)
 top=r['product_no'] or r['id']
 if not already_navigated:
  log(f"네이버 작성 시작 TOP{top}: 글쓰기 페이지 이동 · v7.59 호환 트랜잭션")
  _navigate_same_tab(d,WRITE_URL);time.sleep(3.0)
  _wait_for_naver_login_if_needed(d)
 else:
  log(f"네이버 작성 시작 TOP{top}: 열린 글쓰기 페이지 · v7.59 호환 트랜잭션")
 # From this point through draft save, stay on the v7.59 interaction model.
 legacy.wait_frame(d);legacy.cancel_existing(d);legacy.wait_frame(d)
 log(f"네이버 작성 TOP{top}: v7.59 mainFrame 고정 · 제목 입력")
 legacy.title(d,post["title"])
 log(f"네이버 작성 TOP{top}: 제목 완료 · 프레임 재초기화 없이 동일 mainFrame 유지")
 legacy.clear(d)
 log(f"네이버 작성 TOP{top}: v7.59 본문 포커스/초기화 완료 · 본문 작성")
 legacy.build(d,post)
 legacy._validate_built_once(d,post)
 log(f"네이버 작성 TOP{top}: v7.59 본문 입력 완료 · 서식/이미지 처리")
 for b in post["blocks"]:
  if b.get("type") in ("heading","check"):
   _compat_yellow_bold_v759(d,legacy,b.get("text") or "")
 imgs=[b["file"] for b in post["blocks"] if b.get("type") in ("image","price_compare_image")]
 for i,f in enumerate(imgs,1):
  fp=Path(f);fp=fp if fp.is_absolute() else pdir/fp
  legacy.image(d,f"[[IMG{i}]]",fp.resolve())
 legacy.validate(d,len(imgs))
 log(f"네이버 작성 TOP{top}: 이미지 {len(imgs)}장 확인 · 태그 입력(v7.59)")
 if not legacy.tags(d,post.get("tags",[])):
  raise RuntimeError("네이버 태그 입력란을 찾지 못했거나 태그 입력이 확인되지 않음")
 close_file_dialogs()
 log(f"네이버 작성 TOP{top}: v7.59 저장 트랜잭션으로 임시저장")
 try:
  if not legacy.draft(d,expected_images=len(imgs)):raise RuntimeError("임시저장 확인 실패")
 except legacy.DraftSaveAmbiguousError as e:
  raise DraftSaveAmbiguousError(str(e))
 return len(imgs)


def _write_one_post(d,r,mode):
 """Prefer the proven v7.59 mainFrame writer; use v7.81 only when unavailable.

 The mainFrame probe MUST run after GoBlogWrite is loaded. Probing the previous
 page would always miss mainFrame and accidentally select the broken v7.81
 path, so navigation is intentionally centralized here for compatibility mode.
 """
 cfg=settings();preferred=str(cfg.get("blog_editor_transaction_mode","v759_preferred") or "v759_preferred").lower()
 if preferred in ("v759","v759_preferred","legacy","compat"):
  top=r['product_no'] or r['id']
  log(f"네이버 작성 시작 TOP{top}: 글쓰기 페이지 이동 · 작성기 선택 전")
  _navigate_same_tab(d,WRITE_URL);time.sleep(3.0)
  _wait_for_naver_login_if_needed(d)
  probe=float(cfg.get("blog_v759_mainframe_probe_sec",8))
  if _v759_mainframe_available(d,timeout=probe):
   log("네이버 작성기 선택: v7.59 mainFrame 임시저장 트랜잭션 복원 모드")
   return _write_one_post_v759_compat(d,r,mode,already_navigated=True)
  log("네이버 작성기 선택: mainFrame 미확인 → v7.81 동적 프레임 방식 fallback")
  return _write_one_post_modern(d,r,mode,already_navigated=True)
 return _write_one_post_modern(d,r,mode)

def _run_v782_modern(context=None,progress=None):
 ctx=dict(context or {});mode=str(ctx.get("mode") or settings().get("blog_default_mode","images_only"))
 force_retry=bool(ctx.get("force_retry",False))
 if mode not in {"images_only","price_complete","text_only"}:mode="images_only"
 con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;rows,skipped=_eligible_rows(con,mode,ctx)
 rows,dedupe_skipped,history=_dedupe_upload_rows(rows,mode,force_retry=force_retry);skipped.extend(dedupe_skipped)
 if not rows:
  con.close();label={"images_only":"사진 3장","price_complete":"3사 가격+대표이미지",
                     "text_only":"이미지 없는 제목·본문·태그"}[mode]
  try:
   import csv
   dp=OUTPUTS/"blog_upload_skip_diagnostic.csv";dp.parent.mkdir(parents=True,exist_ok=True)
   with dp.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["TOP","상품명","제외원인"]);w.writeheader()
    for x in skipped:
     top=x.get("product_no") or x.get("id")
     w.writerow({"TOP":top,"상품명":x.get("name"),"제외원인":" · ".join(x.get("reasons") or [])})
  except Exception:pass
  reason=(" · 첫 원인: "+" / ".join((skipped[0].get("reasons") or [])[:2])) if skipped else ""
  only_already_done=bool(skipped) and all(any("이미 임시저장 완료" in str(r) or "동일 원고 중복" in str(r) for r in (x.get("reasons") or [])) for x in skipped)
  return {"processed":0,"stage_ok":only_already_done,"soft_pending":not only_already_done,"mode":mode,"skipped":skipped,
          "diagnostic_csv":str(OUTPUTS/"blog_upload_skip_diagnostic.csv"),
          "message":f"{label} 신규 임시저장 대상 0건 · 조건 미달/저장완료 {len(skipped)}건{reason} · 제외 진단 저장"}

 cfg=settings()
 # Normal authoring errors are never auto-retried to prevent duplicate/partial
 # drafts.  A dead ChromeDriver web-view is different: the browser tab/session
 # itself is gone, so there is no surviving editor state to duplicate.  Allow
 # exactly one fresh-session recovery for that specific failure only.
 retry_count=2;keep_on_failure=bool(cfg.get("blog_keep_browser_open_on_failure",True));reuse=bool(cfg.get("blog_reuse_single_browser_session",True))
 diagnostics=[];successes=0;failed=[];d=None
 try:
  d=start_driver()
  _ensure_one_valid_window(d)
  for idx,r in enumerate(rows):
   ok=False;last_error=""
   for attempt in range(1,retry_count+1):
    try:
     if not _driver_alive(d):d=start_driver(force_new=True)
     _write_one_post(d,r,mode);ok=True;break
    except Exception as e:
     last_error=f"{type(e).__name__}: {e}";log(f"네이버 임시저장 실패 TOP{r['product_no'] or r['id']} 시도 {attempt}/{retry_count}: {last_error}")
     shot,html=_save_blog_failure_diagnostic(d,r,attempt,last_error)
     diagnostics.append({"TOP":r["product_no"] or r["id"],"상품명":r["name"],"시도":attempt,"오류":last_error,"스크린샷":shot,"HTML":html})
     close_file_dialogs()
     if isinstance(e,DraftSaveAmbiguousError):
      log("임시저장 결과가 모호하여 동일 글 중복 방지를 위해 이 상품 자동 재시도 중단");break
     if _is_webview_dead_error(e):
      log("Chrome web view/session 소실 감지: 편집기 상태 자체가 사라졌으므로 새 Chrome 세션으로 1회만 안전복구")
      try:d=start_driver(force_new=True)
      except Exception as restart_exc:
       last_error += " · Chrome 재시작 실패: "+str(restart_exc)[:300]
       break
      if attempt<retry_count:
       time.sleep(1.2)
       continue
     # All non-session authoring failures stop immediately.  Never duplicate a
     # partially written title/body by retrying the same product.
     break
   if ok:
    saved_status={"images_only":"임시저장완료(사진3장)","price_complete":"임시저장완료(3사가격)",
                  "text_only":"임시저장완료(제목본문태그)"}[mode]
    con.execute("UPDATE products SET status=?,last_error=NULL,updated_at=datetime('now','localtime') WHERE id=?",(saved_status,r["id"]));con.commit();successes+=1
    saved_at=time.strftime("%Y-%m-%d %H:%M:%S");fp=_post_fingerprint(r,mode)
    history[fp]={"product_id":r["id"],"product_no":r["product_no"],"name":r["name"],"source_url":r["source_url"] or "","mode":mode,"saved_at":saved_at}
    _save_blog_history(history)
    try:
     record_published_product(r,mode,fp,saved_at)
     log(f"게시완료 상품 중복 레지스트리 기록: {r['name']}")
    except Exception as exc:log("게시완료 상품 중복 레지스트리 기록 경고: "+str(exc))
    if progress:progress(idx+1,len(rows),f"임시저장 확인완료: {r['name'][:30]}")
   else:
    failed.append({"id":r["id"],"name":r["name"],"error":last_error})
    con.execute("UPDATE products SET status='임시저장실패',last_error=?,updated_at=datetime('now','localtime') WHERE id=?",(last_error,r["id"]));con.commit()
    if progress:progress(idx+1,len(rows),f"임시저장 실패 — 현재 상품에서 배치 중단: {r['name'][:25]}")
    log("현재 상품의 제목·본문·이미지를 보존하기 위해 다음 상품으로 이동하지 않고 배치를 중단")
    break
   # v7.64 intentionally does NOTHING to window handles here. The next product
   # is loaded into this exact same tab via `_navigate_same_tab`.
 finally:
  close_file_dialogs()
  try:
   if diagnostics:
    import csv
    dp=OUTPUTS/"blog_upload_diagnostic.csv";dp.parent.mkdir(parents=True,exist_ok=True)
    with dp.open("w",encoding="utf-8-sig",newline="") as f:
     w=csv.DictWriter(f,fieldnames=["TOP","상품명","시도","오류","스크린샷","HTML"]);w.writeheader();w.writerows(diagnostics)
  except Exception as e:log("블로그 진단 CSV 저장 실패: "+str(e))
  # Reuse one Chrome for later button presses as well. If reuse is disabled,
  # close it explicitly. A failed browser is also kept only when still alive.
  if d is not None and not reuse and not (failed and keep_on_failure):_dispose_driver(d)
  con.close()

 label={"images_only":"사진 3장 기준","price_complete":"3사 가격 비교 기준",
        "text_only":"이미지 없는 제목·본문·태그 기준"}[mode]
 if failed:
  first_error=str((failed[0] or {}).get("error") or "원인 미확인")
  return {"processed":successes,"failed":failed,"stage_ok":False,"soft_pending":True,"mode":mode,"skipped":skipped,
          "diagnostic_csv":str(OUTPUTS/"blog_upload_diagnostic.csv"),
          "message":f"{label} 임시저장 성공 {successes}/{len(rows)} · 현재 상품에서 안전 중단 · Chrome 창 유지 · 원인: {first_error[:220]} · 진단 저장"}
 return {"processed":successes,"failed":[],"stage_ok":True,"mode":mode,"skipped":skipped,
         "message":f"{label} {successes}건 임시저장 완료 · 단일 Chrome/단일 탭 재사용 · 조건 미달 {len(skipped)}건 제외"}


# v7.90: exact save-label protection + reference layout/sharelink/yellow styling + prior recovery stack.
# This is deliberately not a function-level compatibility shim.  The exact
# v7.59 module owns Chrome creation, GoBlogWrite navigation, mainFrame entry,
# title/body/image/tag typing, draft click/verification, retries and tab lifecycle.
def _prepare_exact_v759_artifacts():
 """Ensure current DB-backed posts have a local post.json before v7.59 scans them."""
 con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
 try:
  rows=con.execute("SELECT * FROM products WHERE COALESCE(status,'') NOT LIKE '추천제외:%' AND COALESCE(already_posted,0)=0 ORDER BY product_no,id").fetchall()
  for row in rows:
   if not _row_value(row,"title","") or not _row_value(row,"body","") or not _row_value(row,"tags",""):
    continue
   try:
    post,_detail=_ensure_post_artifact(con,row)
    # v7.90 placement is owned by the exact writer. Remove legacy paragraph-
    # converted sharelinks here so the same URL cannot be duplicated, then keep
    # only the canonical URL in post[sharelink]. The writer places it top+bottom
    # around the reference-post image slots.
    link=str(_row_value(row,"sharelink","") or "").strip()
    if isinstance(post,dict):
     blocks=[dict(b) for b in (post.get("blocks") or []) if isinstance(b,dict)]
     blocks=[b for b in blocks if b.get("type")!="sharelink" and b.get("role")!="sharelink"]
     post["blocks"]=normalize_disclosure_blocks(blocks);post["sharelink"]=link
     pdir=_safe_post_dir(row);_write_post_artifact(pdir/"post.json",post)
   except Exception as exc:log(f"v7.59 exact 원고 준비 경고 TOP{_row_value(row,'product_no',row['id'])}: {exc}")
 finally:
  con.close()


def run(context=None,progress=None):
 ctx=dict(context or {})
 mode=str(ctx.get("mode") or settings().get("blog_default_mode","images_only"))
 if mode not in {"images_only","price_complete","text_only"}:
  mode="images_only"
 if os.name=='nt' and bool(settings().get('blog_clipboard_preflight',False)):
  clip=clipboard_preflight()
  log('네이버 저장 사전점검: '+str(clip.get('message') or clip))
  if not clip.get('ok'):
   log('클립보드 사전점검 경고: 본문은 클립보드를 사용하지 않고 Windows 물리 키입력으로 작성합니다. 제목/태그 보조 경로만 클립보드를 사용할 수 있습니다.')
 # v8.08.20: ALL draft buttons use ONE SmartEditor physical-keyboard body engine.
 # The old modern/text_only branch performed a pre-title NBDOM handshake and is
 # the direct cause of the latest "write screen only / no title" regression.
 # Never call _run_v782_modern from a user-facing draft action.
 _prepare_exact_v759_artifacts()
 from . import blog_adapter_v759_exact as exact
 importlib.invalidate_caches()
 exact=importlib.reload(exact)
 expected_engine="v8.08.51"
 actual_engine=str(getattr(exact,"ENGINE_BUILD","") or "")
 if actual_engine!=expected_engine:
  raise RuntimeError(f"네이버 업로더 엔진 버전 불일치: 기대={expected_engine}, 실제={actual_engine or '미표기'} · 오래된 모듈/pyc 실행을 차단했습니다.")
 log("네이버 작성기 선택: v8.08.51 · 기본 15px 유지 · 화면의 모든 체크표시 문단까지 굵게 + #fff8b2 strict 검증")
 return exact.run(context={**ctx,"mode":mode},progress=progress)
