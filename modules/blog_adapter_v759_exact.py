# -*- coding: utf-8 -*-
from pathlib import Path
import os,json,time,re,ctypes,sqlite3,traceback,hashlib,subprocess,html as _html
from .common import *
from .published_product_registry import record_published_product, find_published_match
from .already_posted_adapter import activate_blog_scope
from .blog_target import require_target_blog_id, write_url, assert_editor_target
from .blog_tag_policy import tag_requirement_reason
try:
 from selenium import webdriver
 from selenium.webdriver.common.by import By
 from selenium.webdriver.common.keys import Keys
 from selenium.webdriver.common.action_chains import ActionChains
 from selenium.webdriver.support.ui import WebDriverWait
 from selenium.webdriver.support import expected_conditions as EC
except Exception: webdriver=None

WRITE_URL="https://blog.naver.com/GoBlogWrite.naver"
ENGINE_BUILD="v8.08.51"

# Current Naver PC writing surface is SmartEditor ONE (SE3-compatible UX).
# Do not assume a fixed mainFrame: accounts/layouts can render the editor in top
# document or another frame.  The writer discovers the document that owns BOTH
# the title and the body canvas before any real content is touched.
TITLE_SELECTORS=(
 ".se-title-text,.se-section-documentTitle,.se-documentTitle,"
 "[contenteditable='true'][data-placeholder*='제목'],"
 "[contenteditable='true'][aria-label*='제목']"
)
BODY_HOST_SELECTORS=".se-main-container,.se-content,.se-components-wrap"

class DraftSaveAmbiguousError(RuntimeError):
 """A save click may have been accepted but completion could not be proven. Never auto-retry this post."""
 pass

def health():
 return {"ready":webdriver is not None,"name":"네이버 자동등록","message":"v8.08.31 본문 물리입력 + SmartEditor 가상선택(input_buffer) 검증형 native 서식 commit" if webdriver else "selenium 미설치"}

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

def _automation_profile_path():
 return Path(os.environ.get("LOCALAPPDATA",str(ROOT)))/settings().get("chrome_profile","NaverBlogAutomationProfile")

def _profile_chrome_pids(profile):
 """Return only chrome.exe processes using this automation profile (Windows)."""
 if os.name!="nt":return []
 try:
  target=str(Path(profile).resolve()).replace("'","''")
  ps=("$t='"+target+"'; "
      "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
      "Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($t,[System.StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
      "Select-Object -ExpandProperty ProcessId")
  r=subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],capture_output=True,text=True,timeout=8)
  return [int(x.strip()) for x in (r.stdout or "").splitlines() if x.strip().isdigit()]
 except Exception:return []

def _release_stale_profile(profile):
 """Close ONLY stale Chrome processes owned by the dedicated automation profile."""
 profile=Path(profile);pids=_profile_chrome_pids(profile)
 if pids:
  log("네이버 전용 Chrome 프로필 점유 감지 · 이전 자동화 Chrome 정리: "+",".join(map(str,pids)))
  for pid in pids:
   try:subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],capture_output=True,timeout=6)
   except Exception:pass
  time.sleep(1.4)
 # Lock files may remain after a crashed/forced-closed Chrome. Remove them only
 # when no process still owns this exact automation profile.
 if not _profile_chrome_pids(profile):
  for name in ("SingletonLock","SingletonSocket","SingletonCookie","DevToolsActivePort"):
   try:(profile/name).unlink(missing_ok=True)
   except Exception:pass

def _new_driver_with_profile(profile):
 opt=webdriver.ChromeOptions()
 opt.add_argument(f"--user-data-dir={profile}");opt.add_argument("--start-maximized");opt.add_argument("--no-first-run");opt.add_argument("--no-default-browser-check")
 # Keep a normal visible browser while the transaction is active. The caller now
 # closes failed sessions after diagnostics so the next version/run is never
 # blocked by a stale profile lock.
 opt.add_experimental_option("detach",False)
 return webdriver.Chrome(options=opt)

def start_driver():
 if webdriver is None:raise RuntimeError("Selenium을 불러오지 못했습니다. requirements 설치 상태를 확인하세요.")
 profile=_automation_profile_path();profile.mkdir(parents=True,exist_ok=True)
 log("네이버 Chrome 시작 준비: profile="+str(profile))
 try:
  d=_new_driver_with_profile(profile);log("네이버 Chrome 시작 성공 · 전용 프로필 1차");return d
 except Exception as first:
  text=(type(first).__name__+": "+str(first)).replace("\n"," ")
  log("네이버 Chrome 1차 시작 실패: "+text[:900])
  # The most common cause after a failed draft is a detached Chrome from the
  # previous version still holding NaverBlogAutomationProfile. Release only that
  # dedicated profile, never the user's ordinary Chrome windows.
  _release_stale_profile(profile)
  try:
   d=_new_driver_with_profile(profile);log("네이버 Chrome 시작 성공 · 전용 프로필 자동복구 재시도");return d
  except Exception as second:
   text2=(type(second).__name__+": "+str(second)).replace("\n"," ")
   log("네이버 Chrome 자동복구 재시도 실패: "+text2[:900])
   raise RuntimeError("네이버 전용 Chrome 시작 실패. 이전 자동화 프로필 잠금/ChromeDriver 상태를 자동복구했지만 재시도도 실패했습니다: "+text2[:500])

def _frame_is_auxiliary(fr):
 """Reject SmartEditor IME/clipboard helper frames during host discovery."""
 try:
  hint=" ".join(str(fr.get_attribute(x) or "") for x in ("id","name","class","src","title","aria-label")).lower()
 except Exception:hint=""
 return bool(re.search(r"input[_-]?buffer|inputbuffer|clipboard|paste[_-]?(?:buffer|area|frame)?|ime[_-]?(?:buffer|frame)|dummy|hidden[_-]?frame",hint))

def _editor_host_here(d):
 try:
  titles=[e for e in d.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(e)]
  bodies=[e for e in d.find_elements(By.CSS_SELECTOR,BODY_HOST_SELECTORS) if _visible(e)]
  return bool(titles and bodies)
 except Exception:return False

def _frame_path_here(d):
 try:
  return str(d.execute_script("const f=window.frameElement;return f?((f.id||f.name||f.className||'frame')):'top';") or 'top')
 except Exception:return 'unknown'

def wait_frame(d,timeout: float=35):
 """Discover the real SmartEditor host document dynamically.

 The old fixed ``#mainFrame`` wait is exactly why v8.08.13 could open the write
 screen and then do nothing on accounts where Naver no longer exposes that ID.
 We recurse visible non-IME frames and stop only in a document that owns BOTH a
 visible title and the SmartEditor body container.
 """
 end=time.time()+max(5.0,float(timeout));last={}
 def descend(depth,path):
  if _editor_host_here(d):return list(path)
  if depth<=0:return None
  try:frames=d.find_elements(By.CSS_SELECTOR,'iframe,frame')
  except Exception:frames=[]
  for i,fr in enumerate(frames):
   try:
    if not _visible(fr) or _frame_is_auxiliary(fr):continue
    ident=str(fr.get_attribute('id') or fr.get_attribute('name') or f'frame{i}')
    d.switch_to.frame(fr)
    found=descend(depth-1,path+[ident])
    if found is not None:return found
    d.switch_to.parent_frame()
   except Exception:
    try:d.switch_to.default_content()
    except Exception:pass
  return None
 while time.time()<end:
  try:
   d.switch_to.default_content()
   path=descend(4,[])
   if path is not None:
    setattr(d,'_nb_editor_frame_path',path or ['top'])
    log('네이버 SmartEditor 호스트 확인: '+('/'.join(path) if path else 'top document'))
    return path
   d.switch_to.default_content()
   last={'url':str(getattr(d,'current_url','') or ''),'frames':len(d.find_elements(By.CSS_SELECTOR,'iframe,frame'))}
   src=(d.page_source or '')[:8000]
   if 'nid.naver.com' in last['url']:
    raise RuntimeError('네이버 로그인이 필요합니다. 열린 자동화 Chrome에서 로그인 후 다시 실행하세요.')
   if any(x in src for x in ('접근 권한이 없습니다','서비스 이용이 제한','블로그를 개설')):
    raise RuntimeError('네이버 블로그 글쓰기 권한/계정 상태를 확인해야 합니다.')
  except RuntimeError:raise
  except Exception as exc:last['error']=type(exc).__name__+': '+str(exc)
  time.sleep(.18)
 raise RuntimeError('SmartEditor 제목+본문 호스트를 찾지 못했습니다: '+repr(last)[:700])

def _visible(el):
 try:
  return bool(el.is_displayed())
 except Exception:return False

def _is_title_node(d,e):
 try:
  return bool(d.execute_script("return !!(arguments[0]&&arguments[0].closest&&arguments[0].closest('.se-documentTitle,.se-section-documentTitle,.se-title-text,[class*=documentTitle]'));",e))
 except Exception:return False

def _visible_title_targets(d):
 """Return the real title typing surface before broad title wrappers.

 SmartEditor ONE often exposes a section/module wrapper plus a nested paragraph
 or contenteditable. Clicking the wrapper alone can leave keyboard input on the
 hidden IME buffer, so prefer the deepest visible title paragraph/editable.
 """
 sels=[
  ".se-documentTitle [contenteditable='true']",
  ".se-section-documentTitle [contenteditable='true']",
  ".se-title-text [contenteditable='true']",
  ".se-documentTitle p.se-text-paragraph",
  ".se-section-documentTitle p.se-text-paragraph",
  ".se-title-text p.se-text-paragraph",
  ".se-title-text",
  ".se-section-documentTitle",
  ".se-documentTitle",
  "[contenteditable='true'][data-placeholder*='제목']",
  "[contenteditable='true'][aria-label*='제목']",
 ]
 out=[];seen=set()
 for css in sels:
  try:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    try:
     if not e.is_displayed():continue
     key=e.id
     if key in seen:continue
     seen.add(key);out.append(e)
    except Exception:pass
  except Exception:pass
 return out

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
 # Reference post uses a centered mobile-reading layout. Keep the proven v7.59
 # keyboard transaction, but normalize each newly typed line to CENTER instead
 # of forcing the old left alignment.
 e=toolbar(d,["취소선","strike"]);
 if active(e):e.click()
 e=toolbar(d,["굵게","bold"]);
 if active(e):e.click()
 e=toolbar(d,["가운데 정렬","중앙 정렬","가운데","center"]);
 if e and not active(e):
  try:e.click()
  except:pass

def _article_text_snapshot(d):
 """Return only real article-body text, excluding title/editor chrome/placeholders.

 SmartEditor ONE keeps title, campaign guides and the body canvas under the same
 .se-content/.se-main-container. Reading outer.innerText therefore produces a
 false "old body remains" result even when the article body is empty.
 """
 try:
  return d.execute_script(r"""
   const root=document.querySelector('.se-main-container')||document.querySelector('.se-content');
   if(!root)return {text:'',paragraphs:0,components:0,chrome:''};
   const isTitle=e=>!!(e&&e.closest&&e.closest('.se-documentTitle,.se-section-documentTitle,.se-title-text,[class*=documentTitle]'));
   const isChrome=e=>!!(e&&e.closest&&e.closest('.se-toolbar,.se-guide,.se-placeholder,[class*=placeholder],[class*=toolbar],[class*=guide]'));
   const clean=t=>String(t||'')
     .replace(/추가할 컴포넌트를 선택하세요\.?/g,'')
     .replace(/나를 돌아보는 회고[^\n]*#모두의회고/g,'')
     .trim();
   const isBodyGuide=t=>{
     const c=String(t||'').replace(/[\s\u200b\ufeff]+/g,'');
     return /^(글감과함께)?나의일상을기록해보세요!?$/.test(c)
       || /^(본문|내용)을?(입력|작성)해?주세요!?$/.test(c)
       || /^(본문|내용)을입력하세요!?$/.test(c);
   };
   let ps=[...root.querySelectorAll('.se-text-paragraph')].filter(e=>!isTitle(e)&&!isChrome(e));
   let vals=ps.map(e=>clean(e.innerText||e.textContent||'')).filter(t=>t&&!isBodyGuide(t));
   if(vals.length)return {text:vals.join('\n'),paragraphs:ps.length,components:new Set(ps.map(e=>e.closest('.se-component.se-text,.se-section-text')||e)).size,chrome:clean(root.innerText||'').slice(0,300)};
   // Fallback for editor revisions where paragraph nodes are materialized only
   // after the first keystroke. Restrict the fallback to BODY text components.
   let cs=[...root.querySelectorAll('.se-component.se-text,.se-section-text')].filter(e=>!isTitle(e)&&!isChrome(e));
   vals=[];
   for(const e of cs){
    const t=clean(e.innerText||e.textContent||'');
    if(t&&!isBodyGuide(t))vals.push(t);
   }
   if(vals.length)return {text:vals.join('\n'),paragraphs:ps.length,components:cs.length,chrome:clean(root.innerText||'').slice(0,300)};
   // Final fallback: SmartEditor can temporarily remount text components under
   // a sibling container during media operations. Read body paragraphs from
   // the whole document, still excluding title/chrome/image captions.
   ps=[...document.querySelectorAll('p.se-text-paragraph')].filter(e=>!isTitle(e)&&!isChrome(e)&&!e.closest('.se-component.se-image,[class*=se-image]'));
   vals=ps.map(e=>clean(e.innerText||e.textContent||'')).filter(t=>t&&t!=='사진 설명을 입력하세요.'&&!isBodyGuide(t));
   return {text:vals.join('\n'),paragraphs:ps.length,components:cs.length,chrome:clean(root.innerText||'').slice(0,300)};
  """) or {"text":"","paragraphs":0,"components":0,"chrome":""}
 except Exception as e:
  return {"text":"","paragraphs":0,"components":0,"chrome":"","error":str(e)}

def _native_body_snapshot(d):
 """Read actual SmartEditor body paragraphs through WebDriver element APIs.

 This deliberately avoids execute_script/Runtime.callFunctionOn. Chrome 152 can
 intermittently fail to deserialize large JS snapshot results after dozens of
 sequential posts even though the real paragraph DOM is intact.
 """
 lines=[];paras=0
 try:
  els=d.find_elements(By.CSS_SELECTOR,'p.se-text-paragraph')
 except Exception:
  els=[]
 for e in els:
  try:
   # Exclude title and image-caption paragraphs without a document-wide JS call.
   if e.find_elements(By.XPATH,"./ancestor::*[contains(@class,'se-documentTitle') or contains(@class,'se-section-documentTitle') or contains(@class,'se-title-text')]"):
    continue
   if e.find_elements(By.XPATH,"./ancestor::*[contains(@class,'se-component') and contains(@class,'se-image')] | ./ancestor::*[contains(@class,'se-image-container')]"):
    continue
   paras+=1
   t=(e.text or '').strip()
   if not t:
    # get_attribute is a fallback only; WebElement.text is preferred because it
    # does not depend on our large Runtime.callFunctionOn snapshot.
    try:t=str(e.get_attribute('innerText') or e.get_attribute('textContent') or '').strip()
    except Exception:t=''
   if t and t!='사진 설명을 입력하세요.' and not _is_body_guide_text(t):lines.append(t)
  except Exception:
   continue
 return {'text':'\n'.join(lines),'lines':lines,'paragraphs':paras}

def _note_runtime_glitch(d,snap):
 err=str((snap or {}).get('error') or '')
 if err:
  try:
   setattr(d,'_nb_runtime_glitch',True)
   setattr(d,'_nb_runtime_glitch_error',err[:500])
  except Exception:pass

def _editor_text(d):
 """Resilient article read with SmartEditor empty-body guide filtering."""
 try:
  snap=_article_text_snapshot(d) or {}
  _note_runtime_glitch(d,snap)
  text=_strip_body_guide_lines(str(snap.get('text') or ''))
  if text:return text
 except Exception:
  snap={}
 try:
  native=_native_body_snapshot(d)
  text=_strip_body_guide_lines(str(native.get('text') or ''))
  if text:return text
 except Exception:pass
 return ''

def _compact_text(text):
 return re.sub(r"\s+","",str(text or ''))

_BODY_GUIDE_TEXTS={
 "글감과함께나의일상을기록해보세요!",
 "글감과함께나의일상을기록해보세요",
 "나의일상을기록해보세요!",
 "나의일상을기록해보세요",
 "본문을입력하세요",
 "내용을입력하세요",
 "내용을입력해주세요",
 "본문을작성해주세요",
}

def _is_body_guide_text(text):
 """True only for SmartEditor empty-body guide/placeholder text.

 Current SmartEditor ONE may materialize its empty-body guide inside an actual
 ``p.se-text-paragraph`` instead of a ``.se-placeholder`` node.  That guide is
 editor UI, not article content, and must never make a fresh post look non-empty.
 """
 raw=str(text or '').replace('\u200b','').replace('\ufeff','').strip()
 compact=re.sub(r"\s+","",raw)
 return (not compact) or compact in _BODY_GUIDE_TEXTS

def _strip_body_guide_lines(text):
 lines=[]
 for line in str(text or '').splitlines():
  if _is_body_guide_text(line):
   continue
  if line.strip():
   lines.append(line.strip())
 return "\n".join(lines)

def _native_line_count(d,text):
 needle=_compact_text(text)
 if not needle:return 0
 try:
  return sum(1 for x in (_native_body_snapshot(d).get('lines') or []) if _compact_text(x)==needle)
 except Exception:return 0

def _wait_line_ack(d,text,before_global_count,before_native_count,timeout=3.2):
 """Acknowledge a typed line from either native paragraph DOM or global snapshot.

 Native exact-paragraph acknowledgement is authoritative. This prevents a
 transient 0-length JS snapshot from turning a successfully typed line into a
 fatal error after long continuous runs.
 """
 needle=_compact_text(text)
 if not needle:return True,'empty'
 end=time.time()+timeout;last_global='';last_native=before_native_count
 while time.time()<end:
  nc=_native_line_count(d,text);last_native=nc
  if nc>before_native_count:return True,'native-paragraph'
  now=_compact_text(_editor_text(d));last_global=now
  if now.count(needle)>before_global_count:return True,'article-snapshot'
  time.sleep(.08)
 return False,{'native':last_native,'global_len':len(last_global)}


def _body_expected_lines(post):
 """Return only user-visible article text. Does not change editor focus/caret."""
 out=[]
 for b in post.get("blocks",[]):
  typ=b.get("type")
  if typ in ("heading","check") and b.get("text"):
   out.append(str(b.get("text")))
  elif typ in ("paragraph","disclosure"):
   out.extend(str(x) for x in (b.get("lines") or []) if str(x).strip())
  elif typ=="sharelink" and b.get("url"):
   out.append(str(b.get("url")))
 return out

def _validate_body_complete(d,post):
 """Read-only full-body gate usable both before and after image insertion."""
 got=_compact_text(_editor_text(d));lines=_body_expected_lines(post)
 expected=_compact_text(''.join(lines))
 if not expected:raise RuntimeError('본문 완료 검증 실패: 원고 본문이 비어 있음')
 counts={};samples={}
 for x in lines:
  c=_compact_text(x)
  if c:counts[c]=counts.get(c,0)+1;samples.setdefault(c,x[:50])
 missing=[]
 for c,need in counts.items():
  have=got.count(c)
  if have<need:missing.append(f"{samples[c]} (필요 {need}/실제 {have})")
 if missing:raise RuntimeError('본문 완료 검증 실패: 누락/중복부족 '+repr(missing[:5]))
 if len(got)<max(50,int(len(expected)*0.90)):
  raise RuntimeError(f'본문 완료 검증 실패: 기대 글자 {len(expected)} / 실제 본문 {len(got)}')
 return True

def _tag_dom_snapshot_here(d):
 try:
  return d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
   const sels=['[class*=tag]','[class*=Tag]','[aria-label*=태그]','[placeholder*=태그]'];
   let txt=[],chips=0;
   for(const q of sels){for(const e of document.querySelectorAll(q)){if(!vis(e))continue;const t=(e.innerText||e.value||e.textContent||'').trim();if(t)txt.push(t);if(e.matches('[class*=tag-item],[class*=tag_item],[class*=tag-chip],[class*=tag_chip],li,[role=option]'))chips++;}}
   return {text:txt.join('\n'),chips:chips};
  """) or {}
 except Exception:return {}

def _tag_dom_snapshot(d):
 """Read tag chips from current editor frame and, when necessary, outer document."""
 first=_tag_dom_snapshot_here(d);texts=[str(first.get('text') or '')];chips=int(first.get('chips') or 0)
 try:
  d.switch_to.default_content();outer=_tag_dom_snapshot_here(d)
  texts.append(str(outer.get('text') or ''));chips=max(chips,int(outer.get('chips') or 0))
 except Exception:pass
 finally:
  try:wait_frame(d)
  except Exception:pass
 return {'text':'\n'.join(x for x in texts if x),'chips':chips}

def _validate_tags_complete(d,wanted):
 """Read-only tag gate. Accept visible chips/text or per-Enter React acknowledgement."""
 wanted=[str(x).lstrip('#').strip() for x in (wanted or []) if str(x).strip()]
 if not wanted:return True
 end=time.time()+4.0;last={}
 while time.time()<end:
  last=_tag_dom_snapshot(d);text=_compact_text(str(last.get('text') or '').replace('#',''))
  seen=sum(1 for x in wanted if _compact_text(x) in text)
  chips=int(last.get('chips') or 0)
  confirmed=int(getattr(d,'_nb_tags_enter_confirmed',0) or 0)
  if seen==len(wanted):
   log(f"태그 완료 검증: DOM 텍스트 {seen}/{len(wanted)}");return True
  if chips>=len(wanted):
   log(f"태그 완료 검증: chip {chips}/{len(wanted)}");return True
  if confirmed>=len(wanted):
   log(f"태그 완료 검증: 입력란 Enter 반영 {confirmed}/{len(wanted)}");return True
  time.sleep(.15)
 raise RuntimeError(f"태그 완료 검증 실패: 입력 {len(wanted)}개 / DOM 확인 {sum(1 for x in wanted if _compact_text(x) in _compact_text(str(last.get('text') or '').replace('#','')))}개 / chip {int(last.get('chips') or 0)}개 / Enter반영 {int(getattr(d,'_nb_tags_enter_confirmed',0) or 0)}개")

def _body_runtime_diagnostic(d):
 """Collect body-vs-editor-chrome evidence without changing focus/caret."""
 try:
  data=d.execute_script(r"""
   const ae=document.activeElement;
   const info=e=>{if(!e)return null;const r=e.getBoundingClientRect();return {tag:e.tagName,cls:e.className||'',id:e.id||'',editable:e.getAttribute('contenteditable'),text:(e.innerText||e.value||e.textContent||'').slice(0,220),w:Math.round(r.width),h:Math.round(r.height)};};
   const root=document.querySelector('.se-main-container')||document.querySelector('.se-content');
   const ed=[...document.querySelectorAll('[contenteditable=true]')].map(info);
   const ps=[...document.querySelectorAll('.se-text-paragraph')].filter(e=>!e.closest('.se-documentTitle,.se-section-documentTitle,.se-title-text,[class*=documentTitle]')).map(info);
   const sel=window.getSelection();let anchor=null;
   try{let n=sel&&sel.anchorNode;let e=n&&(n.nodeType===1?n:n.parentElement);anchor=info(e);}catch(_e){}
   return {active:info(ae),root:info(root),contenteditables:ed.slice(0,30),body_paragraphs:ps.slice(0,30),selection_anchor:anchor,url:location.href};
  """) or {}
  data['article']=_article_text_snapshot(d)
  _note_runtime_glitch(d,data.get('article') or {})
  data['article_text_len']=len(str((data.get('article') or {}).get('text') or ''))
  data['native_article']=_native_body_snapshot(d)
  return data
 except Exception as e:return {'diagnostic_error':str(e)}

def _visible_body_targets(d):
 sels=[
  '.se-component.se-text .se-text-paragraph',
  '.se-section-text .se-text-paragraph',
  '.se-component.se-text .se-module-text',
  '.se-section-text .se-module-text',
  '.se-component.se-text',
  '.se-section-text'
 ]
 out=[];seen=set()
 for css in sels:
  try:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    try:
     if not e.is_displayed():continue
     key=e.id
     if key in seen:continue
     seen.add(key);out.append(e)
    except Exception:pass
  except Exception:pass
 return out

def _activate_body(d):
 """Native-click the real body canvas. input_buffer focus is ACCEPTED.

 New SmartEditor revisions intentionally focus a 1px input_buffer iframe for IME
 keyboard capture. Treating that iframe as a bogus body frame caused prior
 regressions; the reliable proof is whether typed text appears in body DOM.
 """
 last={}
 for e in _visible_body_targets(d):
  try:
   try:ActionChains(d).move_to_element(e).click().perform()
   except Exception:e.click()
   time.sleep(.12)
   last=d.execute_script(r"""
    const a=document.activeElement,s=window.getSelection();let n=s&&s.anchorNode,el=n&&(n.nodeType===1?n:n.parentElement);
    return {active_tag:a&&a.tagName||'',active_id:a&&a.id||'',active_cls:a&&a.className||'',
      input_buffer:!!(a&&a.tagName==='IFRAME'&&/^input_buffer/i.test(a.id||'')),
      selection_in_body:!!(el&&el.closest&&el.closest('.se-component.se-text,.se-section-text,.se-text-paragraph'))};
   """) or {}
   if last.get('input_buffer') or last.get('selection_in_body'):
    return last
  except Exception:continue
 # Empty documents sometimes expose only a narrow contenteditable input surface.
 try:
  for e in d.find_elements(By.CSS_SELECTOR,'[contenteditable="true"]'):
   if not e.is_displayed() or _is_title_node(d,e):continue
   try:ActionChains(d).move_to_element(e).click().perform()
   except Exception:e.click()
   time.sleep(.12)
   last={'fallback':'body-contenteditable'}
   return last
 except Exception:pass
 # Last safe fallback: click the body canvas, never the title.
 try:
  root=WebDriverWait(d,3).until(EC.presence_of_element_located((By.CSS_SELECTOR,'.se-main-container,.se-content')))
  ActionChains(d).move_to_element_with_offset(root, max(8,min(80,root.size.get('width',100)//4)), max(120,min(420,root.size.get('height',600)//2))).click().perform();time.sleep(.15)
  return {'fallback':'body_canvas'}
 except Exception as e:
  raise RuntimeError('본문 입력 위치 활성화 실패: '+str(e))

def _focus_body_end_after_toolbar(d):
 """v7.64 exact path: after toolbar interaction restore caret at LAST body paragraph."""
 root=WebDriverWait(d,8).until(EC.presence_of_element_located((By.CSS_SELECTOR,'.se-main-container,.se-content')))
 try:
  target=d.execute_script(r"""
   const root=arguments[0],vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
   let xs=[...root.querySelectorAll('.se-component.se-text .se-text-paragraph,.se-section-text .se-text-paragraph,[contenteditable=true]')]
      .filter(e=>vis(e)&&!e.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'));
   return xs.length?xs[xs.length-1]:root;
  """,root)
 except Exception:target=root
 try:ActionChains(d).move_to_element(target).click().perform()
 except Exception:
  try:target.click()
  except Exception:_activate_body(d)
 try:d.execute_script("const e=arguments[0],s=getSelection(),r=document.createRange();try{e.focus();}catch(x){}r.selectNodeContents(e);r.collapse(false);s.removeAllRanges();s.addRange(r);",target)
 except Exception:pass
 return target

def _wait_line_appeared(d,text,before_count,timeout=1.6):
 # Compatibility wrapper for older callers. New line() uses the dual/native ack.
 needle=_compact_text(text)
 if not needle:return True
 end=time.time()+timeout
 while time.time()<end:
  now=_compact_text(_editor_text(d))
  if now.count(needle)>before_count:return True
  time.sleep(.06)
 return False

def _browser_copy_stage(d,html_fragment,plain_text,kind='body'):
 """Use Chrome itself to create the clipboard payload in the SAME tab.

 We temporarily render the already-formatted article in a disposable
 contenteditable overlay, select it, and issue a real Ctrl+C.  Chrome therefore
 owns the HTML/text clipboard serialization; no hand-built CF_HTML offsets and
 no helper tab are involved.  The overlay is removed before Naver receives the
 paste.
 """
 stage_id='__nb_copy_stage__'
 _bypass_input_buffers(d,'copy-stage')
 try:
  stage=d.execute_script(r"""
   const id=arguments[0],html=arguments[1];
   let old=document.getElementById(id);if(old)old.remove();
   const e=document.createElement('div');e.id=id;e.contentEditable='true';e.tabIndex=0;
   e.setAttribute('data-nb-copy-stage','1');
   e.style.cssText='position:fixed;left:18px;top:18px;width:760px;max-height:360px;overflow:hidden;z-index:2147483647;background:#fff;color:#111;padding:12px;border:2px solid #777;opacity:.02;pointer-events:auto;';
   e.innerHTML=html;document.body.appendChild(e);e.focus();
   const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);
   return e;
  """,stage_id,str(html_fragment or ''))
  if stage is None:return False,{'reason':'stage-create-failed'}
  # Give Chrome a REAL focus/click gesture before copying. SmartEditor can
  # asynchronously move JS focus back to input_buffer; a physical WebDriver
  # click on the disposable stage prevents that race and matches manual copy.
  try:ActionChains(d).move_to_element(stage).click().perform()
  except Exception:
   try:stage.click()
   except Exception:pass
  d.execute_script("const e=document.getElementById(arguments[0]);if(e){e.focus();const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);}",stage_id)
  time.sleep(.05)
  # Ctrl+C is intentionally a real WebDriver keyboard transaction.  This makes
  # the clipboard format the same as a human Chrome copy, which is what Naver's
  # SmartEditor paste pipeline expects.
  ActionChains(d).key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
  time.sleep(.20)
  try:
   sel_len=int(d.execute_script("const s=getSelection();return s?String(s.toString()||'').length:0;") or 0)
  except Exception:sel_len=0
  try:d.execute_script("const e=document.getElementById(arguments[0]);if(e)e.remove();getSelection().removeAllRanges();",stage_id)
  except Exception:pass
  return sel_len>=min(4,max(1,len(str(plain_text or '').strip()))),{'selection_chars':sel_len,'kind':kind}
 except Exception as exc:
  try:d.execute_script("const e=document.getElementById(arguments[0]);if(e)e.remove();",stage_id)
  except Exception:pass
  return False,{'reason':type(exc).__name__+': '+str(exc)[:300],'kind':kind}

def _rich_body_payload(post):
 """Build one SE3-style rich-text clipboard document with image slot anchors.

 v8.08.50: preserve SmartEditor's default body font size (normally 15px).
 Headings and advantage rows carry only the two requested emphasis properties:
 native bold + exact text background #fff8b2.  No font-size declaration is
 injected into the clipboard payload, so font-size can no longer become a save
 failure point.
 """
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 normal="text-align:center;margin:0;white-space:pre-wrap;"
 html_parts=[];plain=[];image_no=0
 def add(text='',emphasis=False,blank=False):
  t=str(text or '')
  body=_html.escape(t,quote=False) if t else '<br>'
  if emphasis and t:
   body=f'<strong><span style="background-color:{bg};font-weight:700">{body}</span></strong>'
  pstyle=normal+('font-weight:700;background-color:'+bg+';' if emphasis else '')
  html_parts.append(f'<p style="{pstyle}">{body}</p>')
  plain.append(t)
  if blank:
   html_parts.append(f'<p style="{normal}"><br></p>');plain.append('')
 for b in (post.get('blocks') or []):
  typ=b.get('type')
  if typ=='disclosure':
   for x in (b.get('lines') or COUPANG_DISCLOSURE_LINES):add(x)
   add('')
  elif typ=='sharelink':
   u=str(b.get('url') or '').strip()
   if u:add(u,blank=True)
  elif typ in ('image','price_compare_image'):
   image_no+=1;add(_image_anchor_token(image_no),blank=True)
  elif typ=='heading':add(b.get('text',''),emphasis=True,blank=True)
  elif typ=='check':add(b.get('text',''),emphasis=True)
  elif typ=='paragraph':
   for x in (b.get('lines') or []):
    # v8.08.51: DB recovery/external-import posts can keep visible advantage
    # rows as ordinary paragraph lines.  The visible check marker is the user-
    # facing contract, so pre-style those rows even when block type is stale.
    sx=str(x or '').strip()
    add(x,emphasis=bool(re.match(r'^[✔✓☑✅]',sx)))
   add('')
 while len(plain)>1 and plain[-1]=='':
  plain.pop()
  if html_parts:html_parts.pop()
 return ''.join(html_parts),'\r\n'.join(plain),image_no

def _title_placeholder_text(text, placeholder=''):
 raw=str(text or '').replace('\u200b','').replace('\ufeff','').strip()
 compact=re.sub(r"\s+","",raw)
 known={"제목","제목을입력하세요","제목을입력해주세요","제목입력"}
 ph=re.sub(r"\s+","",str(placeholder or '').strip())
 return (not compact) or compact in known or (bool(ph) and compact==ph)


def _title_node_actual_text(d,e):
 """Read only the user-entered title text from a TITLE LEAF.

 Never trust wrapper innerText. SmartEditor title wrappers also contain editor
 chrome such as 위치이동/제목 배경 사진/삭제/취소/확인, which is not article
 content and caused v8.08.17 to abort before the first keystroke.
 """
 try:
  data=d.execute_script(r"""
   const e=arguments[0]; if(!e)return {values:[]};
   const titleRootSel='.se-documentTitle,.se-section-documentTitle,.se-title-text,[class*=documentTitle]';
   const leafSel='p.se-text-paragraph,[contenteditable="true"],input,textarea';
   const vis=n=>{if(!n)return false;const r=n.getBoundingClientRect(),st=getComputedStyle(n);return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';};
   let leaves=[];
   if(e.matches&&e.matches(leafSel)&&e.closest(titleRootSel))leaves.push(e);
   if(e.querySelectorAll){
    for(const n of e.querySelectorAll(leafSel)){
     if(n.closest(titleRootSel)&&vis(n))leaves.push(n);
    }
   }
   leaves=[...new Set(leaves)];
   // Wrappers are click surfaces only. They are NEVER title text sources.
   if(!leaves.length)return {values:[],leafCount:0};

   const clean=n=>{
    const tag=(n.tagName||'').toLowerCase();
    const ph=(n.getAttribute&&((n.getAttribute('data-placeholder')||n.getAttribute('aria-placeholder')||n.getAttribute('placeholder')||'')))||'';
    if(tag==='input'||tag==='textarea')return {text:String(n.value||''),placeholder:String(ph||'')};
    const c=n.cloneNode(true);
    const rm=[
      '.se-placeholder','.__se_placeholder','[class*=placeholder]',
      'button','[role=button]','[contenteditable="false"]',
      '[class*=toolbar]','[class*=control]','[class*=button]',
      '[class*=layer]','[class*=menu]','[class*=handle]'
    ];
    for(const q of rm){
      for(const x of [...c.querySelectorAll(q)]){try{x.remove();}catch(err){}}
    }
    return {text:String(c.innerText||c.textContent||''),placeholder:String(ph||'')};
   };
   return {values:leaves.map(clean),leafCount:leaves.length};
  """,e) or {}
  vals=data.get('values') or []
  texts=[]
  for item in vals:
   if not isinstance(item,dict):continue
   text=str(item.get('text') or '')
   ph=str(item.get('placeholder') or '')
   if not _title_placeholder_text(text,ph):
    t=text.strip()
    if t:texts.append(t)
  if not texts:return ''
  texts.sort(key=lambda x:len(_compact_text(x)))
  return texts[0]
 except Exception:
  return ''

def _title_text_here(d):
 """Return actual title content from leaf nodes only.

 Wrapper text is deliberately ignored because current SmartEditor ONE title
 modules include UI labels (위치이동/제목 배경 사진/삭제/취소/확인).
 """
 try:
  data=d.execute_script(r"""
   const rootSel='.se-documentTitle,.se-section-documentTitle,.se-title-text,[class*=documentTitle]';
   const vis=n=>{if(!n)return false;const r=n.getBoundingClientRect(),st=getComputedStyle(n);return r.width>0&&r.height>0&&st.display!=='none'&&st.visibility!=='hidden';};
   let leaves=[...document.querySelectorAll(
    '.se-documentTitle p.se-text-paragraph,.se-section-documentTitle p.se-text-paragraph,.se-title-text p.se-text-paragraph,'+
    '.se-documentTitle [contenteditable="true"],.se-section-documentTitle [contenteditable="true"],.se-title-text [contenteditable="true"],'+
    '[contenteditable="true"][data-placeholder*="제목"],[contenteditable="true"][aria-label*="제목"]'
   )].filter(n=>vis(n)&&!!n.closest(rootSel));
   leaves=[...new Set(leaves)];
   const clean=n=>{
    const tag=(n.tagName||'').toLowerCase();
    const ph=(n.getAttribute&&((n.getAttribute('data-placeholder')||n.getAttribute('aria-placeholder')||n.getAttribute('placeholder')||'')))||'';
    if(tag==='input'||tag==='textarea')return {text:String(n.value||''),placeholder:String(ph||'')};
    const c=n.cloneNode(true);
    for(const q of ['.se-placeholder','.__se_placeholder','[class*=placeholder]','button','[role=button]','[contenteditable="false"]','[class*=toolbar]','[class*=control]','[class*=button]','[class*=layer]','[class*=menu]','[class*=handle]']){
      for(const x of [...c.querySelectorAll(q)]){try{x.remove();}catch(err){}}
    }
    return {text:String(c.innerText||c.textContent||''),placeholder:String(ph||'')};
   };
   return leaves.map(clean);
  """) or []
  vals=[]
  for item in data:
   if not isinstance(item,dict):continue
   text=str(item.get('text') or '')
   ph=str(item.get('placeholder') or '')
   if _title_placeholder_text(text,ph):continue
   text=text.strip()
   if text:vals.append(text)
  if not vals:return ''
  vals.sort(key=lambda x:len(_compact_text(x)))
  return vals[0]
 except Exception:return ''

def _body_zero(d):
 return not _compact_text(_editor_text(d))

def _active_input_buffer_frame(d):
 try:
  a=d.switch_to.active_element
  if str(getattr(a,'tag_name','')).lower()!='iframe':return None
  hint=' '.join(str(a.get_attribute(x) or '') for x in ('id','name','class','title')).lower()
  return a if re.search(r'input[_-]?buffer|inputbuffer|ime',hint) else None
 except Exception:return None

def _input_buffer_inventory(d):
 """Read-only inventory of SmartEditor IME/input helper frames in the current editor document."""
 try:
  return d.execute_script(r"""
   const info=e=>{const r=e.getBoundingClientRect();return {id:e.id||'',name:e.name||'',cls:String(e.className||''),w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)};};
   return [...document.querySelectorAll('iframe,frame')].filter(e=>/input[_-]?buffer|inputbuffer|ime/i.test((e.id||'')+' '+(e.name||'')+' '+(e.className||'')+' '+(e.title||''))).map(info);
  """) or []
 except Exception:return []

def _bypass_input_buffers(d, reason='paste'):
 """Temporarily remove SmartEditor IME helper iframes before a trusted paste.

 The user's diagnostics repeatedly showed the visible SE paragraph selected while
 document.activeElement was iframe#input_buffer..., and every keyboard/paste path
 was consumed without changing article DOM.  For a *paste transaction* we do not
 need IME composition, so remove only those tiny helper frames in the current
 editor document, then return focus to the real visible editor surface.
 Naver may recreate the helper later; that is fine and is intentionally allowed.
 """
 try:
  data=d.execute_script(r"""
   const rx=/input[_-]?buffer|inputbuffer|ime/i, removed=[];
   const active=document.activeElement;
   if(active&&active.tagName==='IFRAME'&&rx.test((active.id||'')+' '+(active.name||'')+' '+(active.className||''))){try{active.blur();}catch(e){}}
   for(const f of [...document.querySelectorAll('iframe,frame')]){
    const h=(f.id||'')+' '+(f.name||'')+' '+(f.className||'')+' '+(f.title||'');
    if(rx.test(h)){removed.push(f.id||f.name||'input_buffer');try{f.remove();}catch(e){try{f.style.pointerEvents='none';f.style.display='none';}catch(x){}}}
   }
   return {removed:removed,active_before:active?{tag:active.tagName,id:active.id||'',cls:String(active.className||'')}:null};
  """) or {}
  if data.get('removed'): log('SmartEditor input_buffer 우회('+str(reason)+'): '+','.join(map(str,data.get('removed') or [])))
  return data
 except Exception as exc:return {'error':type(exc).__name__+': '+str(exc)[:240]}

def _focus_real_title(d,e=None,select_all=False):
 """Focus the visible title paragraph itself and keep input_buffer out of the transaction."""
 if e is None:e=next(iter(_visible_title_targets(d)),None)
 if e is None:return None
 try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",e)
 except Exception:pass
 try:ActionChains(d).move_to_element(e).click().perform()
 except Exception:
  try:e.click()
  except Exception:pass
 _bypass_input_buffers(d,'title-focus')
 try:
  d.execute_script(r"""
   const e=arguments[0],all=!!arguments[1];
   try{e.setAttribute('tabindex','-1');e.focus({preventScroll:true});}catch(x){try{e.focus();}catch(y){}}
   const s=getSelection(),r=document.createRange();r.selectNodeContents(e);if(!all)r.collapse(false);s.removeAllRanges();s.addRange(r);
  """,e,bool(select_all))
 except Exception:pass
 return e

def _real_body_paragraph(d):
 try:
  return d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>5&&r.height>5&&s.display!=='none'&&s.visibility!=='hidden';};
   const bad=e=>!!e.closest('.se-documentTitle,.se-section-documentTitle,.se-title-text,[class*=documentTitle]')||/input[_-]?buffer|inputbuffer|ime|tag|comment|search/i.test((e.id||'')+' '+String(e.className||''));
   let ps=[...document.querySelectorAll('.se-main-container .se-component.se-text .se-module-text p.se-text-paragraph,.se-content .se-component.se-text p.se-text-paragraph,.se-section-text p.se-text-paragraph,p.se-text-paragraph')].filter(e=>vis(e)&&!bad(e));
   return ps.length?ps[ps.length-1]:null;
  """)
 except Exception:return None

def _focus_real_body(d,physical_click=False):
 """Click body once like a user, remove recreated input_buffer, then collapse selection into the real paragraph."""
 p=_real_body_paragraph(d)
 if p is None:
  # Create/activate the empty paragraph using the normal editor click first.
  try:_activate_body(d)
  except Exception:pass
  p=_real_body_paragraph(d)
 if p is None:return None
 try:d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",p)
 except Exception:pass
 if physical_click:
  try:_win_physical_click_element(d,p)
  except Exception:pass
 else:
  try:ActionChains(d).move_to_element(p).click().perform()
  except Exception:
   try:p.click()
   except Exception:pass
 # Clicking the paragraph is exactly what makes Naver recreate input_buffer.
 # Remove it *after* the click and before Ctrl+V.
 _bypass_input_buffers(d,'body-after-click')
 try:
  d.execute_script(r"""
   const p=arguments[0],host=p.closest('.se-content')||document.querySelector('.se-content')||p;
   try{host.setAttribute('tabindex','-1');host.focus({preventScroll:true});}catch(x){}
   try{p.setAttribute('tabindex','-1');p.focus({preventScroll:true});}catch(x){try{p.focus();}catch(y){}}
   const s=getSelection(),r=document.createRange();r.selectNodeContents(p);r.collapse(false);s.removeAllRanges();s.addRange(r);
  """,p)
 except Exception:pass
 # A microtask/timer can recreate the helper after our first removal. Do one
 # bounded second pass; never loop forever.
 time.sleep(.05);_bypass_input_buffers(d,'body-final')
 try:
  d.execute_script("const p=arguments[0],s=getSelection(),r=document.createRange();r.selectNodeContents(p);r.collapse(false);s.removeAllRanges();s.addRange(r);",p)
 except Exception:pass
 return p

def _win_find_chrome_hwnd(d):
 if os.name!='nt':return 0
 try:title=str(d.title or '').strip().lower()
 except Exception:title=''
 try:
  user32=ctypes.windll.user32;hits=[]
  @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
  def cb(hwnd,lparam):
   try:
    if not user32.IsWindowVisible(hwnd):return True
    cls=ctypes.create_unicode_buffer(128);user32.GetClassNameW(hwnd,cls,128)
    if cls.value!='Chrome_WidgetWin_1':return True
    n=user32.GetWindowTextLengthW(hwnd);buf=ctypes.create_unicode_buffer(n+1);user32.GetWindowTextW(hwnd,buf,n+1);wt=buf.value
    score=(100 if title and title in wt.lower() else 0)+(40 if ('네이버' in wt or 'naver' in wt.lower()) else 0)
    hits.append((score,int(hwnd),wt))
   except Exception:pass
   return True
  user32.EnumWindows(cb,0)
  if not hits:return 0
  hits.sort(reverse=True);return hits[0][1]
 except Exception:return 0

def _win_foreground_chrome(d):
 """Maximize and foreground the browser before physical mouse/keyboard fallback."""
 if os.name!='nt':return 0
 try:d.maximize_window()
 except Exception:pass
 hwnd=_win_find_chrome_hwnd(d)
 if hwnd:
  try:
   user32=ctypes.windll.user32;user32.ShowWindow(hwnd,3);user32.SetForegroundWindow(hwnd);time.sleep(.15)
  except Exception:pass
 return hwnd

def _screen_point_for_element(d,e):
 try:
  data=d.execute_script(r"""
   const e=arguments[0];e.scrollIntoView({block:'center',inline:'nearest'});const r=e.getBoundingClientRect();
   let ox=0,oy=0,w=window,guard=0;
   try{while(w!==w.top&&guard++<8){const f=w.frameElement;if(!f)break;const q=f.getBoundingClientRect();ox+=q.left;oy+=q.top;w=w.parent;}}catch(x){}
   let topw;try{topw=w.top;}catch(x){topw=window;}
   const chromeY=Math.max(0,(topw.outerHeight||window.outerHeight)-(topw.innerHeight||window.innerHeight));
   return {x:(topw.screenX||window.screenX)+ox+r.left+Math.max(8,Math.min(r.width-8,r.width*.5)),y:(topw.screenY||window.screenY)+chromeY+oy+r.top+Math.max(6,Math.min(r.height-4,r.height*.55)),screenX:(topw.screenX||window.screenX),screenY:(topw.screenY||window.screenY),outerW:topw.outerWidth||window.outerWidth,outerH:topw.outerHeight||window.outerHeight,innerW:topw.innerWidth||window.innerWidth};
  """,e)
  return data if isinstance(data,dict) else None
 except Exception:return None

def _win_physical_click_element(d,e):
 if os.name!='nt':return False
 point=_screen_point_for_element(d,e)
 if not point:return False
 hwnd=_win_foreground_chrome(d)
 try:
  user32=ctypes.windll.user32
  # Map CSS screen coordinates to the physical Chrome window scale when possible.
  x=float(point['x']);y=float(point['y'])
  if hwnd and float(point.get('outerW') or 0)>0:
   class RECT(ctypes.Structure):_fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
   rc=RECT()
   if user32.GetWindowRect(hwnd,ctypes.byref(rc)):
    pw=max(1,rc.right-rc.left);ph=max(1,rc.bottom-rc.top)
    sx=max(.75,min(3.0,pw/float(point.get('outerW') or pw)));sy=max(.75,min(3.0,ph/float(point.get('outerH') or ph)))
    # Anchor scaling at the native Chrome window origin. This remains correct
    # on secondary monitors and Windows DPI scaling where screenX can be nonzero/negative.
    x=rc.left+(x-float(point.get('screenX') or 0))*sx
    y=rc.top +(y-float(point.get('screenY') or 0))*sy
  x=int(round(x));y=int(round(y))
  user32.SetCursorPos(x,y);time.sleep(.06);user32.mouse_event(0x0002,0,0,0,0);time.sleep(.025);user32.mouse_event(0x0004,0,0,0,0);time.sleep(.10)
  return True
 except Exception:return False

def _win_ctrl_v(d):
 """Real Windows Ctrl+V. keybd_event is deliberately used instead of the failing SendInput Unicode path."""
 if os.name!='nt':return False
 _win_foreground_chrome(d)
 try:
  user32=ctypes.windll.user32;VK_CONTROL=0x11;VK_V=0x56;KEYEVENTF_KEYUP=0x0002
  try:
   user32.keybd_event(VK_CONTROL,0,0,0);time.sleep(.025);user32.keybd_event(VK_V,0,0,0);time.sleep(.035);return True
  finally:
   try:user32.keybd_event(VK_V,0,KEYEVENTF_KEYUP,0);user32.keybd_event(VK_CONTROL,0,KEYEVENTF_KEYUP,0)
   except Exception:pass
 except Exception:return False

def _is_webview_dead_error(exc):
 text=(type(exc).__name__+': '+str(exc)).lower()
 return any(x in text for x in ('web view not found','no such window','target window already closed','chrome not reachable','disconnected: not connected to devtools','invalid session id','session deleted because of page crash','tab crashed','page crash'))

def _ctrl_v_action(d):
 try:
  ActionChains(d).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform();return True
 except Exception:return False

def _ctrl_v_cdp(d):
 """Chrome DevTools trusted key dispatch fallback for the focused SmartEditor."""
 try:
  common={'key':'v','code':'KeyV','windowsVirtualKeyCode':86,'nativeVirtualKeyCode':86,'modifiers':2}
  d.execute_cdp_cmd('Input.dispatchKeyEvent',{'type':'rawKeyDown',**common})
  d.execute_cdp_cmd('Input.dispatchKeyEvent',{'type':'keyUp',**common})
  return True
 except Exception:return False

def _wait_bulk_body(d,expected_plain,before='',timeout=12.0):
 expected=_compact_text(expected_plain);before=_compact_text(before)
 anchors=[_compact_text(x) for x in str(expected_plain or '').splitlines() if _compact_text(x)]
 end=time.time()+max(3.0,float(timeout));last=before
 while time.time()<end:
  last=_compact_text(_editor_text(d))
  if expected and (expected in last or (len(last)>=int(len(expected)*.92) and all(a in last for a in anchors[:2]+anchors[-2:]))):
   return True,last
  if last!=before and len(last)>max(8,len(before)+8):
   # Give SmartEditor a short settling window before declaring a partial paste.
   time.sleep(.25);new=_compact_text(_editor_text(d))
   if expected and (expected in new or (len(new)>=int(len(expected)*.92) and all(a in new for a in anchors[:2]+anchors[-2:]))):return True,new
   return False,new
  time.sleep(.10)
 return False,last

def _paste_rich_template(d,post):
 """One browser-native SmartEditor template paste with input_buffer bypass.

 Transaction: render completed HTML in Chrome -> Ctrl+C -> physical click body ->
 remove/neutralize input_buffer -> focus real SE paragraph -> physical Ctrl+V.
 Only zero-change failures may try another route. Any partial article mutation is
 terminal to prevent duplication/interleaving.
 """
 html_fragment,plain,slot_count=_rich_body_payload(post)
 before=_compact_text(_editor_text(d))
 if before:raise RuntimeError(f'Rich Paste 시작 전 본문이 비어 있지 않음: {len(before)}자')
 _bypass_input_buffers(d,'before-copy')
 copied,cdiag=_browser_copy_stage(d,html_fragment,plain,'body')
 if not copied:raise RuntimeError('Chrome 동일탭 Rich Copy 준비 실패: '+repr(cdiag))
 methods=[]
 timeout=max(7.0,min(20.0,5.0+len(plain)/450.0))
 def verify(label,sent):
  methods.append(label+('=sent' if sent else '=send-failed'))
  if not sent:return None
  full,now=_wait_bulk_body(d,plain,before,timeout=timeout)
  if full:return {'method':label,'chars':len(now),'slots':slot_count,'copy':cdiag,'input_buffer_bypass':True}
  if now!=before:raise RuntimeError(f'본문 Rich Paste 부분 반영 감지 — 재시도 금지 · method={label} · 실제증가={len(now)-len(before)}')
  return None
 # Primary: manual-like physical click, then delete input_buffer, then real Windows Ctrl+V.
 target=_focus_real_body(d,physical_click=True)
 if target is not None:
  # physical click may recreate input_buffer; bypass again without another click
  _bypass_input_buffers(d,'physical-paste')
  try:d.execute_script("const p=arguments[0],s=getSelection(),r=document.createRange();try{p.focus();}catch(x){}r.selectNodeContents(p);r.collapse(false);s.removeAllRanges();s.addRange(r);",target)
  except Exception:pass
  res=verify('windows-physical-ctrl-v',_win_ctrl_v(d))
  if res:return res
 # Route 2: same real selection with Selenium Ctrl+V, still with input_buffer removed.
 target=_focus_real_body(d,physical_click=False);_bypass_input_buffers(d,'selenium-paste')
 res=verify('selenium-ctrl-v',_ctrl_v_action(d))
 if res:return res
 # Route 3: CDP trusted Ctrl+V after one final real body focus. No input_buffer frame switch.
 target=_focus_real_body(d,physical_click=False);_bypass_input_buffers(d,'cdp-paste')
 res=verify('cdp-ctrl-v',_ctrl_v_cdp(d))
 if res:return res
 raise RuntimeError('SmartEditor 전체 Rich Paste 미반영(input_buffer 우회 포함): '+repr(methods)+' · copy='+repr(cdiag)+' · buffers='+repr(_input_buffer_inventory(d))+' · frame='+repr(getattr(d,'_nb_editor_frame_path',None)))

def _clear_title_if_body_failed(d):
 """Never leave another title-only draft when the body could not be committed."""
 try:
  if not _body_zero(d):return
  e=next((x for x in d.find_elements(By.CSS_SELECTOR,TITLE_SELECTORS) if _visible(x)),None)
  if e is None:return
  ActionChains(d).move_to_element(e).click().key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
  time.sleep(.10)
 except Exception:pass


def title(d,text):
 """Write title without any pre-read gate from wrapper UI.

 v8.08.17 still aborted before typing because SmartEditor title wrappers expose
 editor chrome text such as ``위치이동 제목 배경 사진 삭제 취소 확인``.  This
 transaction never treats wrapper innerText as article content.  It simply
 performs the historically stable human-like title action first, then verifies
 ONLY title leaf nodes (p.se-text-paragraph/contenteditable descendants).
 """
 want=str(text or '').strip();cw=_compact_text(want)
 if not cw:raise RuntimeError('제목 원고가 비어 있음')

 targets=_visible_title_targets(d)
 if not targets:
  raise RuntimeError('SmartEditor 실제 제목 입력 영역을 찾지 못했습니다')
 methods=[]

 def current():
  return _compact_text(_title_text_here(d))

 def wait_ok(timeout=3.2):
  end=time.time()+max(.5,float(timeout))
  while time.time()<end:
   got=current()
   if got==cw or (cw and cw in got):return True
   time.sleep(.07)
  return False

 # Route 1: the original v7.x action that was already proven on this project.
 # There is deliberately NO "is there existing title text?" pre-check here.
 # cancel_existing() already gives us a new-post transaction, and Ctrl+A/Delete
 # is the safe way to clear a resumed title if one exists.
 for idx,e in enumerate(targets[:5]):
  if current():
   break
  try:
   ActionChains(d).move_to_element(e).click().key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).send_keys(want).perform()
   methods.append(f'direct-title-sendkeys#{idx+1}')
  except Exception as exc:
   methods.append(f'direct-title-sendkeys#{idx+1}-error={type(exc).__name__}')
   continue
  if wait_ok():
   log(f'제목 직접입력 검증 완료 · target#{idx+1} · {len(cw)}자')
   return
  got=current()
  if got and got!=cw:
   raise RuntimeError('제목 직접입력 부분 반영 감지: 중복 방지를 위해 중단 · actual='+repr(_title_text_here(d)[:120]))

 # Route 2: only after ZERO verified title characters, use a browser-native
 # clipboard and a real Windows click/Ctrl+V, exactly like a manual paste.
 if not current():
  copied,cdiag=_browser_copy_stage(d,'<span>'+_html.escape(want,quote=False)+'</span>',want,'title')
  methods.append('browser-copy='+('ok' if copied else 'failed'))
  if copied:
   for idx,e in enumerate(targets[:5]):
    if current():break
    try:_win_physical_click_element(d,e)
    except Exception:pass
    # Do NOT remove input_buffer for title: it is Naver's legitimate IME bridge.
    try:
     d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",e)
    except Exception:pass
    sent=_win_ctrl_v(d);methods.append(f'windows-ctrl-v#{idx+1}' if sent else f'windows-ctrl-v#{idx+1}-failed')
    if sent and wait_ok():
     log(f'제목 Windows Paste 검증 완료 · target#{idx+1} · {len(cw)}자')
     return
    got=current()
    if got and got!=cw:
     raise RuntimeError('제목 Paste 부분 반영 감지: 재입력 금지 · actual='+repr(_title_text_here(d)[:120]))

 # Route 3: zero-change only Selenium Ctrl+V after clicking the deepest title
 # leaf again. Never loop once real title characters have appeared.
 if not current() and 'copied' in locals() and copied:
  for idx,e in enumerate(targets[:3]):
   if current():break
   try:ActionChains(d).move_to_element(e).click().perform()
   except Exception:
    try:e.click()
    except Exception:pass
   sent=_ctrl_v_action(d);methods.append(f'selenium-ctrl-v#{idx+1}' if sent else f'selenium-ctrl-v#{idx+1}-failed')
   if sent and wait_ok():
    log(f'제목 Selenium Paste 검증 완료 · target#{idx+1} · {len(cw)}자')
    return
   got=current()
   if got and got!=cw:
    raise RuntimeError('제목 최종 부분 반영 감지: 재입력 금지 · actual='+repr(_title_text_here(d)[:120]))

 raise RuntimeError(
  '제목 입력 검증 실패 · wrapper UI는 제목값으로 사용하지 않음 · methods='+
  repr(methods)+' · actual='+repr(_title_text_here(d)[:120])+
  ' · copy='+repr(cdiag if 'cdiag' in locals() else None)
 )

def clear(d):
 """Clear REAL article text only; ignore SmartEditor empty-body guide text."""
 # `_article_text_snapshot()` can expose the editor guide as a real paragraph
 # (`글감과 함께 나의 일상을 기록해보세요!`).  `_editor_text()` is the
 # authoritative, placeholder-filtered article read.
 actual=_compact_text(_editor_text(d))
 if not actual:
  # Critical v7.86 fix: a new empty post must NOT receive Ctrl+A/Delete.
  # Outer .se-content still contains title, campaign text and editor guides.
  st=_activate_body(d)
  log(f"본문 초기화 확인: 실제 본문 0자 · 제목/안내 UI 제외 · input_buffer 포커스 허용 · state={st}")
  return
 title_before=''
 try:
  te=d.find_element(By.CSS_SELECTOR,'.se-title-text,.se-section-documentTitle');title_before=(te.text or te.get_attribute('innerText') or '').strip()
 except Exception:pass
 # There really is article text (e.g. a resumed draft). Clear only body text nodes.
 for attempt in range(3):
  targets=_visible_body_targets(d)
  if targets:
   try:
    e=targets[-1];ActionChains(d).move_to_element(e).click().key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform();time.sleep(.30)
   except Exception:pass
  if not _compact_text(_editor_text(d)):
   if title_before:
    try:
     now=(d.find_element(By.CSS_SELECTOR,'.se-title-text,.se-section-documentTitle').text or '').strip()
     if not now:title(d,title_before)
    except Exception:pass
   _activate_body(d);return
  # Targeted DOM range fallback: select BODY components only, then dispatch Backspace.
  try:
   selected=d.execute_script(r"""
    const root=document.querySelector('.se-main-container')||document.querySelector('.se-content');if(!root)return 0;
    const xs=[...root.querySelectorAll('.se-component.se-text,.se-section-text')].filter(e=>!e.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'));
    if(!xs.length)return 0;const r=document.createRange();r.setStartBefore(xs[0]);r.setEndAfter(xs[xs.length-1]);const s=window.getSelection();s.removeAllRanges();s.addRange(r);return (s.toString()||'').length;
   """) or 0
   if selected:
    ActionChains(d).send_keys(Keys.BACKSPACE).perform();time.sleep(.35)
  except Exception:pass
  if not _compact_text(_editor_text(d)):
   _activate_body(d);return
 remain=_editor_text(d)
 raise RuntimeError('본문 초기화 실패: 실제 본문 텍스트가 남음 · UI/제목 제외 후 '+repr(remain[:160]))

def line(d,t):
 """Type one line; trust exact paragraph DOM before any global JS snapshot.

 After long runs ChromeDriver 152 can return an empty/deserialize-failed result
 from Runtime.callFunctionOn while SmartEditor has already committed the line.
 Retyping in that state would duplicate content, so native paragraph evidence is
 the first and authoritative acknowledgement.
 """
 t=str(t or '')
 needle=_compact_text(t)
 before=_compact_text(_editor_text(d));before_count=before.count(needle) if needle else 0
 before_native=_native_line_count(d,t) if needle else 0
 basefmt(d)
 _focus_body_end_after_toolbar(d)
 ActionChains(d).send_keys(t).send_keys(Keys.ENTER).perform()
 ok,via=_wait_line_ack(d,t,before_count,before_native,timeout=3.2)
 if not needle or ok:
  if via=='native-paragraph' and bool(getattr(d,'_nb_runtime_glitch',False)):
   log(f'본문 DOM 동기화 복구: JS 스냅샷 불안정에도 실제 문단 입력 확인 · {t[:55]}')
  return
 after=_compact_text(_editor_text(d));native_after=_native_line_count(d,t)
 # A native exact paragraph can appear a little later than the global snapshot.
 # One final native-only grace window prevents a false failure after 30~60 posts.
 end=time.time()+2.2
 while time.time()<end:
  if _native_line_count(d,t)>before_native:
   log(f'본문 DOM 지연복구 성공: 실제 문단 기준 · {t[:55]}')
   return
  time.sleep(.10)
 # If any body evidence changed but the exact line is not present, do NOT type
 # again; it may be a partial composition. Stop rather than duplicate text.
 native_text=_compact_text((_native_body_snapshot(d) or {}).get('text') or '')
 if (after and after!=before) or (native_text and native_text!=before):
  raise RuntimeError(f'본문 문장 부분 입력/DOM 동기화 실패: {t[:80]} · before={len(before)} after={len(after)} native={len(native_text)}')
 # No article-body change at all: focus was genuinely lost. Re-activate once.
 st=_activate_body(d);basefmt(d);_focus_body_end_after_toolbar(d)
 ActionChains(d).send_keys(t).send_keys(Keys.ENTER).perform()
 ok,via=_wait_line_ack(d,t,before_count,before_native,timeout=3.2)
 if ok:
  log(f'본문 포커스 자동복구 성공: {via} · {t[:50]} · state={st}')
  return
 # Last non-JS fallback: send directly to a visible body contenteditable.
 try:
  for e in d.find_elements(By.CSS_SELECTOR,'[contenteditable="true"]'):
   if not e.is_displayed():continue
   e.click();e.send_keys(t);e.send_keys(Keys.ENTER)
   ok,via=_wait_line_ack(d,t,before_count,before_native,timeout=2.5)
   if ok:
    log(f'본문 포커스 자동복구 성공: visible contenteditable/{via}')
    return
 except Exception:pass
 raise RuntimeError(f'본문 문장 입력 실패(3경로 모두 미반영): {t[:100]} · '+json.dumps(_body_runtime_diagnostic(d),ensure_ascii=False)[:1800])

def find_exact(d,t):
 lit=json.dumps(t)
 for xp in [f"//*[contains(@class,'se-text-paragraph') and normalize-space(.)={lit}]",f"//*[self::p or self::span or self::div][normalize-space(.)={lit}]"]:
  for e in d.find_elements(By.XPATH,xp):
   if e.is_displayed():return e
def _select_paragraph_contents(d,e):
 """Select an entire SmartEditor paragraph with a DOM Range and real edit focus.

 v8.08.23: the background palette may preserve the visual selection while the
 actual editing focus remains on SmartEditor ONE's hidden ``input_buffer``.  In
 that state a toolbar/shortcut can appear to run but the bold command is not
 committed to the text span.  Focus the nearest contenteditable host first, then
 recreate the exact paragraph range.  This keeps the selection inside the real
 article model instead of the IME bridge.
 """
 try:
  info=d.execute_script(r"""
   const p=arguments[0];
   if(!p)return {ok:false,reason:'no-element'};
   try{p.scrollIntoView({block:'center',inline:'nearest'});}catch(e){}
   const host=p.closest('[contenteditable=true]') ||
              p.parentElement?.closest?.('[contenteditable=true]') ||
              document.querySelector('.se-content [contenteditable=true]');
   try{if(host)host.focus({preventScroll:true});}catch(e){try{if(host)host.focus();}catch(x){}}
   const r=document.createRange();r.selectNodeContents(p);
   const s=window.getSelection();s.removeAllRanges();s.addRange(r);
   try{document.dispatchEvent(new Event('selectionchange',{bubbles:true}));}catch(e){}
   const text=String(s.toString()||'');
   return {ok:text.length>0,text:text,len:text.length,host:host?{tag:host.tagName,cls:String(host.className||'').slice(0,120)}:null};
  """,e) or {}
  return bool(info.get('ok')),info
 except Exception as ex:return False,{'ok':False,'reason':type(ex).__name__+': '+str(ex)}

def selectline(d,e):
 ok,_=_select_paragraph_contents(d,e)
 if not ok:
  ActionChains(d).click(e).send_keys(Keys.HOME).key_down(Keys.SHIFT).send_keys(Keys.END).key_up(Keys.SHIFT).perform()

def bold(d,t):
 e=_find_exact_body_paragraph(d,t) or find_exact(d,t)
 if not e:return False
 ok,_=_select_paragraph_contents(d,e)
 if not ok:return False
 s=toolbar(d,["취소선","strike"])
 if active(s):
  try:d.execute_script("arguments[0].click();",s)
  except Exception:s.click()
 e=_find_exact_body_paragraph(d,t) or e;_select_paragraph_contents(d,e)
 b=toolbar(d,["굵게","bold"])
 if b and not active(b):
  try:d.execute_script("arguments[0].click();",b)
  except Exception:b.click()
 time.sleep(.12)
 e=_find_exact_body_paragraph(d,t) or e
 ok=_bold_present(d,e)
 _collapse_selection(d)
 return ok


def _collapse_selection(d):
 try:d.execute_script("""const s=window.getSelection();if(s&&s.rangeCount)s.collapseToEnd();""")
 except Exception:
  try:ActionChains(d).send_keys(Keys.RIGHT).perform()
  except Exception:pass

def _hex_rgb(hex_color):
 h=str(hex_color or '').strip().lstrip('#')
 if len(h)==3:h=''.join(c*2 for c in h)
 if len(h)!=6:return [255,248,178]
 try:return [int(h[i:i+2],16) for i in (0,2,4)]
 except Exception:return [255,248,178]

def _exact_bg_present(d,e,hex_color=None):
 """Require the requested background behind EVERY visible text leaf.

 v8.08.46 accepted a paragraph when *any* descendant happened to carry the
 target color.  A wrapped advantage could therefore have only a transient or
 partial span colored while the visible letters stayed unhighlighted, yet the
 save gate still passed.  Walk each non-empty text node and accept it only when
 that text node itself or one of its ancestors up to the paragraph paints the
 exact target background.
 """
 try:
  target=str(hex_color or settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
  rgb=_hex_rgb(target)
  rep=d.execute_script(r"""
   const root=arguments[0],want=arguments[1],rows=[];
   const same=c=>{const m=String(c||'').match(/\d+/g)||[];return m.length>=3&&Number(m[0])===want[0]&&Number(m[1])===want[1]&&Number(m[2])===want[2];};
   const visible=e=>{try{const s=getComputedStyle(e);return s.display!=='none'&&s.visibility!=='hidden';}catch(x){return false;}};
   const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;
   while(n=w.nextNode()){
    const txt=String(n.nodeValue||'').replace(/[\u200B-\u200D\u2060\uFE0E\uFE0F]/g,'').trim();
    if(!txt)continue;
    let el=n.parentElement||root;if(!visible(el))continue;
    let hit=false,trail=[];
    while(el){
     let c='';try{c=getComputedStyle(el).backgroundColor||'';}catch(x){}
     if(c&&c!=='transparent'&&c!=='rgba(0, 0, 0, 0)')trail.push(c);
     if(same(c)){hit=true;break;}
     if(el===root)break;el=el.parentElement;
    }
    rows.push({text:txt.slice(0,80),hit:hit,backgrounds:trail.slice(0,6)});
   }
   return {ok:rows.length>0&&rows.every(x=>x.hit),rows:rows};
  """,e,rgb) or {}
  return bool(rep.get('ok'))
 except Exception:return False

def _bold_present(d,e):
 """Strictly verify that the ACTUAL visible text leaves are bold.

 v8.08.21/22 used ``any(fontWeight>=600)`` across the paragraph tree.  After the
 background-color command SmartEditor can rebuild an inner span at weight 400
 while the outer paragraph remains 700.  The old verifier therefore returned a
 false positive even though the letters looked normal on screen.  We now inspect
 every non-empty text node's parent and require the visible text leaves to be
 bold, which matches what the user actually sees.
 """
 try:
  rep=d.execute_script(r"""
   const root=arguments[0], rows=[];
   const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;
   const isBold=v=>{v=String(v||'').toLowerCase();const k=parseInt(v,10);return (!Number.isNaN(k)&&k>=600)||v==='bold'||v==='bolder';};
   while(n=w.nextNode()){
    const txt=String(n.nodeValue||'').replace(/[\u200B-\u200D\u2060\uFE0E\uFE0F]/g,'').trim();
    if(!txt)continue;
    const el=n.parentElement||root, cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden')continue;
    rows.push({text:txt.slice(0,80),weight:String(cs.fontWeight||''),bold:isBold(cs.fontWeight)});
   }
   if(!rows.length){const v=getComputedStyle(root).fontWeight;rows.push({text:'<root>',weight:String(v||''),bold:isBold(v)});}
   return {ok:rows.length>0 && rows.every(x=>x.bold),rows};
  """,e) or {}
  return bool(rep.get('ok'))
 except Exception:return False

def _click_exact_background(d,hex_color=None):
 """Use SmartEditor ONE's real background palette, preferring the exact hex chip."""
 target=str(hex_color or settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2').lower()
 rgb=_hex_rgb(target);rgb_css=f'rgb({rgb[0]}, {rgb[1]}, {rgb[2]})'
 btn=toolbar(d,["글자 배경색","배경색","텍스트 배경색","문자 배경색","형광펜","background"])
 if not btn:return False
 try:d.execute_script("arguments[0].click();",btn)
 except Exception:
  try:btn.click()
  except Exception:return False
 time.sleep(.28)
 try:
  result=d.execute_script(r"""
   const target=arguments[0].toLowerCase(),rgb=arguments[1];
   const norm=s=>String(s||'').toLowerCase().replace(/\s+/g,' ');
   const vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
   const all=[...document.querySelectorAll('button,[role=button],a,li,label,span,div,input')];
   // 1. Exact declared color/data-color/title/aria label.
   for(const e of all){if(!vis(e))continue;
    const meta=norm((e.getAttribute('data-color')||'')+' '+(e.getAttribute('data-value')||'')+' '+(e.getAttribute('value')||'')+' '+(e.getAttribute('title')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('style')||''));
    if(meta.includes(target)){e.click();return {ok:true,route:'exact-meta'};}
   }
   // 2. Exact computed chip color (#fff8b2 => rgb(255,248,178)).
   for(const e of all){if(!vis(e))continue;const cs=getComputedStyle(e);const bg=norm(cs.backgroundColor);const c=norm(cs.color);if(bg===norm(rgb)||c===norm(rgb)){e.click();return {ok:true,route:'exact-rgb'};}}
   // 3. Native color input / exact hex input when exposed by this editor build.
   for(const e of document.querySelectorAll('input[type=color]')){if(!vis(e))continue;e.value=target;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return {ok:true,route:'color-input'};}
   for(const e of document.querySelectorAll('input[type=text],input:not([type]),textarea')){if(!vis(e))continue;const ph=norm((e.placeholder||'')+' '+(e.getAttribute('aria-label')||''));if(/색|color|hex/.test(ph)){e.focus();e.value=target;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));return {ok:true,route:'hex-input'};}}
   return {ok:false,route:'no-exact-chip'};
  """,target,rgb_css) or {}
  if result.get('ok'):
   time.sleep(.22);return True
 except Exception:pass
 return False

def _direct_range_style_fallback(d,e,bg):
 """Last fallback after REAL toolbar selection failed.

 Apply formatting to the selected paragraph and emit formatting/input events so
 the editor has a chance to observe the mutation.  This is never the primary
 route; the subsequent computed-style gate decides whether saving may continue.
 """
 try:
  return bool(d.execute_script(r"""
   const root=arguments[0],bg=arguments[1];
   const r=document.createRange();r.selectNodeContents(root);const s=window.getSelection();s.removeAllRanges();s.addRange(r);
   let bold=false,back=false;
   try{bold=document.execCommand('bold',false,null);}catch(e){}
   try{back=document.execCommand('hiliteColor',false,bg)||document.execCommand('backColor',false,bg);}catch(e){}
   if(!back){for(const n of [root,...root.querySelectorAll('*')])n.style.backgroundColor=bg;}
   if(!bold){for(const n of [root,...root.querySelectorAll('*')])n.style.fontWeight='700';}
   const host=root.closest('[contenteditable=true]')||root;
   try{host.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'formatBackColor'}));}catch(e){host.dispatchEvent(new Event('input',{bubbles:true}));}
   return true;
  """,e,bg))
 except Exception:return False

def _win_ctrl_b(d):
 """Send a real Windows Ctrl+B to the currently selected SmartEditor paragraph."""
 if os.name!='nt':return False
 _win_foreground_chrome(d)
 try:
  user32=ctypes.windll.user32;VK_CONTROL=0x11;VK_B=0x42;KEYEVENTF_KEYUP=0x0002
  try:
   user32.keybd_event(VK_CONTROL,0,0,0);time.sleep(.025)
   user32.keybd_event(VK_B,0,0,0);time.sleep(.045)
   return True
  finally:
   try:user32.keybd_event(VK_B,0,KEYEVENTF_KEYUP,0);user32.keybd_event(VK_CONTROL,0,KEYEVENTF_KEYUP,0)
   except Exception:pass
 except Exception:return False


def _action_ctrl_b(d):
 try:
  ActionChains(d).key_down(Keys.CONTROL).send_keys('b').key_up(Keys.CONTROL).perform();return True
 except Exception:return False


def _ensure_bold_selected_paragraph(d,e,text=''):
 """Commit bold using native editor routes, then strictly verify visible text.

 Order is intentional: a real keyboard shortcut is closest to a human action and
 works with SmartEditor ONE's selection model.  The physical toolbar click is a
 second route, JavaScript click a third.  Direct style mutation remains the final
 fallback in ``format_yellow_bold`` only.
 """
 if _bold_present(d,e):return True
 routes=[]
 # 1) Real Windows Ctrl+B after focusing and reselecting the exact paragraph.
 ok,_=_select_paragraph_contents(d,e)
 if ok and _win_ctrl_b(d):
  routes.append('win-ctrl-b');time.sleep(.18)
  e2=_find_exact_body_paragraph(d,text) or e
  if _bold_present(d,e2):return True
 # 2) Selenium keyboard shortcut against the same live selection.
 e2=_find_exact_body_paragraph(d,text) or e;_select_paragraph_contents(d,e2)
 if _action_ctrl_b(d):
  routes.append('selenium-ctrl-b');time.sleep(.16)
  e2=_find_exact_body_paragraph(d,text) or e2
  if _bold_present(d,e2):return True
 # 3) Real physical click on SmartEditor bold toolbar button.
 e2=_find_exact_body_paragraph(d,text) or e;_select_paragraph_contents(d,e2)
 b=toolbar(d,['굵게','bold'])
 if b:
  try:
   if _win_physical_click_element(d,b):routes.append('physical-toolbar-bold')
   else:
    try:b.click();routes.append('selenium-toolbar-bold')
    except Exception:pass
  except Exception:pass
  time.sleep(.18)
  e2=_find_exact_body_paragraph(d,text) or e2
  if _bold_present(d,e2):return True
 # 4) JS toolbar click only as the last native-toolbar attempt.
 e2=_find_exact_body_paragraph(d,text) or e;_select_paragraph_contents(d,e2)
 b=toolbar(d,['굵게','bold'])
 if b:
  try:d.execute_script('arguments[0].click();',b);routes.append('js-toolbar-bold')
  except Exception:pass
  time.sleep(.16)
  e2=_find_exact_body_paragraph(d,text) or e2
  if _bold_present(d,e2):return True
 log('SmartEditor 굵게 native 경로 미반영: '+str(text)[:50]+' · '+repr(routes))
 return False


def format_yellow_bold(d,t):
 """Post-format one completed body paragraph: strict bold + exact #fff8b2.

 v8.08.23 fixes the visual-bold regression seen after background coloring.
 SmartEditor ONE can rebuild the inner text span when applying a background chip;
 therefore bold is committed BOTH before and after the background transaction and
 is verified on the actual text-bearing leaves rather than an outer wrapper.
 """
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 e=_find_exact_body_paragraph(d,t) or find_exact(d,t)
 if not e:
  try:
   nearby=d.execute_script(r"""
    const clean=s=>String(s||'').normalize('NFC').replace(/[\uFE0E\uFE0F\u200B-\u200D\u2060]/g,'').replace(/\s+/g,'');
    return [...document.querySelectorAll('p.se-text-paragraph')].filter(p=>!p.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]')).map(p=>({raw:String(p.innerText||p.textContent||''),key:clean(p.innerText||p.textContent||'')})).filter(x=>x.raw.trim()).slice(-18);
   """) or []
  except Exception:nearby=[]
  raise RuntimeError(f'서식 대상 본문 문단을 찾지 못함: {str(t)[:60]} · 최근문단='+json.dumps(nearby,ensure_ascii=False)[:1200])
 try:
  # Remove accidental strike-through first, then commit bold on the actual text.
  ok,sel=_select_paragraph_contents(d,e)
  if not ok:raise RuntimeError('굵게 적용 전 본문 Range 선택 실패: '+str(sel))
  strike=toolbar(d,['취소선','strike'])
  if active(strike):
   try:_win_physical_click_element(d,strike)
   except Exception:
    try:strike.click()
    except Exception:pass
  e=_find_exact_body_paragraph(d,t) or e
  if not _ensure_bold_selected_paragraph(d,e,t):
   # Do not fail yet: the final DOM formatting fallback runs after background.
   log('굵게 1차 native 적용 미확인 — 배경 적용 후 최종 보정 예정: '+str(t)[:60])

  # Background can recreate inner spans, so it is a separate transaction.
  e=_find_exact_body_paragraph(d,t) or e
  ok,sel=_select_paragraph_contents(d,e)
  if not ok:raise RuntimeError('배경색 적용 전 본문 Range 선택 실패: '+str(sel))
  if not _exact_bg_present(d,e,bg):_click_exact_background(d,bg)
  time.sleep(.18)

  # CRITICAL v8.08.23: re-apply/re-verify bold AFTER background span rebuild.
  e=_find_exact_body_paragraph(d,t) or e
  if not _bold_present(d,e):
   _ensure_bold_selected_paragraph(d,e,t)
  time.sleep(.18)

  # Final fallback writes both styles to all text descendants AFTER the palette
  # operation, then emits input events.  Because this runs last, a newly-created
  # background span cannot overwrite font-weight back to 400 afterward.
  e=_find_exact_body_paragraph(d,t) or e
  if not (_bold_present(d,e) and _exact_bg_present(d,e,bg)):
   _select_paragraph_contents(d,e);_direct_range_style_fallback(d,e,bg);time.sleep(.22)

  # Re-find after SmartEditor reconciliation and verify what is actually visible.
  e=_find_exact_body_paragraph(d,t) or e;time.sleep(.08)
  bold_ok=_bold_present(d,e);bg_ok=_exact_bg_present(d,e,bg)
  if not bold_ok:
   # One final native Ctrl+B on the reconciled span; never toggle if already bold.
   _ensure_bold_selected_paragraph(d,e,t);time.sleep(.18)
   e=_find_exact_body_paragraph(d,t) or e;bold_ok=_bold_present(d,e)
  _collapse_selection(d)
  if not (bold_ok and bg_ok):
   raise RuntimeError(f'SmartEditor 서식 적용 검증 실패: bold={bold_ok}, bg={bg_ok}, color={bg}, text={str(t)[:60]}')
  log(f'굵게 + 글자 배경색 {bg} 실제 텍스트 검증 완료: {str(t)[:60]}')
  return True
 except Exception:
  _collapse_selection(d);raise


# ---------------------------------------------------------------------------
# v8.08.27 - PERSISTENT NATIVE FORMAT TRANSACTION (Ctrl+B primary + resilient toolbar fallback)
# ---------------------------------------------------------------------------
# Important: formatting MUST be committed through SmartEditor ONE's own UI.
# Direct DOM style mutations / execCommand can look correct on screen but are
# not guaranteed to enter Naver's serialized editor model, so they disappear
# after draft-save + reopen. JavaScript is read-only here: geometry/diagnostics.
# Selection and toolbar/palette actions are performed with the real Windows mouse.

def _v825_text_key(text):
 txt=str(text or '')
 for ch in ('\ufe0e','\ufe0f','\u200b','\u200c','\u200d','\u2060'):
  txt=txt.replace(ch,'')
 return re.sub(r'\s+','',txt)

def _v825_map_css_screen_point(d,data,xkey,ykey):
 if not isinstance(data,dict):return None
 try:x=float(data[xkey]);y=float(data[ykey])
 except Exception:return None
 hwnd=_win_foreground_chrome(d)
 try:
  if hwnd and float(data.get('outerW') or 0)>0:
   user32=ctypes.windll.user32
   class RECT(ctypes.Structure):_fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
   rc=RECT()
   if user32.GetWindowRect(hwnd,ctypes.byref(rc)):
    pw=max(1,rc.right-rc.left);ph=max(1,rc.bottom-rc.top)
    sx=max(.75,min(3.0,pw/float(data.get('outerW') or pw)))
    sy=max(.75,min(3.0,ph/float(data.get('outerH') or ph)))
    x=rc.left+(x-float(data.get('screenX') or 0))*sx
    y=rc.top +(y-float(data.get('screenY') or 0))*sy
  return int(round(x)),int(round(y))
 except Exception:return None

def _v825_paragraph_drag_points(d,e):
 """Read only: return physical-screen start/end points for paragraph text."""
 try:
  data=d.execute_script(r'''
   const e=arguments[0];
   try{e.scrollIntoView({block:'center',inline:'nearest'});}catch(x){}
   const rg=document.createRange();rg.selectNodeContents(e);
   let rs=[...rg.getClientRects()].filter(r=>r.width>1&&r.height>1);
   if(!rs.length){const q=e.getBoundingClientRect();rs=[q];}
   const a=rs[0],b=rs[rs.length-1],er=e.getBoundingClientRect();
   let ox=0,oy=0,w=window,guard=0;
   try{while(w!==w.top&&guard++<8){const f=w.frameElement;if(!f)break;const q=f.getBoundingClientRect();ox+=q.left;oy+=q.top;w=w.parent;}}catch(x){}
   let topw;try{topw=w.top;}catch(x){topw=window;}
   const chromeY=Math.max(0,(topw.outerHeight||window.outerHeight)-(topw.innerHeight||window.innerHeight));
   const baseX=(topw.screenX||window.screenX)+ox,baseY=(topw.screenY||window.screenY)+chromeY+oy;
   return {
    sx:baseX+Math.max(er.left+1,a.left-4), sy:baseY+a.top+a.height*.55,
    ex:baseX+Math.min(er.right-1,b.right+4), ey:baseY+b.top+b.height*.55,
    screenX:(topw.screenX||window.screenX),screenY:(topw.screenY||window.screenY),
    outerW:topw.outerWidth||window.outerWidth,outerH:topw.outerHeight||window.outerHeight,
    lines:rs.length,text:String(e.innerText||e.textContent||'')
   };
  ''',e) or {}
  a=_v825_map_css_screen_point(d,data,'sx','sy');b=_v825_map_css_screen_point(d,data,'ex','ey')
  return a,b,data
 except Exception as ex:return None,None,{'error':type(ex).__name__+': '+str(ex)}

def _v825_drag(d,a,b):
 if os.name!='nt' or not a or not b:return False
 _win_foreground_chrome(d)
 try:
  user32=ctypes.windll.user32;x1,y1=a;x2,y2=b
  user32.SetCursorPos(int(x1),int(y1));time.sleep(.08)
  user32.mouse_event(0x0002,0,0,0,0)
  steps=max(10,min(24,int(abs(y2-y1)/10)+10))
  for i in range(1,steps+1):
   f=i/steps;user32.SetCursorPos(int(round(x1+(x2-x1)*f)),int(round(y1+(y2-y1)*f)));time.sleep(.012)
  time.sleep(.035);user32.mouse_event(0x0004,0,0,0,0);time.sleep(.16)
  return True
 except Exception:
  try:ctypes.windll.user32.mouse_event(0x0004,0,0,0,0)
  except Exception:pass
  return False

def _v825_selected_text(d):
 try:return str(d.execute_script("return String(window.getSelection?window.getSelection().toString():'');") or '')
 except Exception:return ''

def _v826_select_paragraph_range(d,e,expected_text=''):
 """Select the exact paragraph with browser Selection/Range, without mutating content.

 v8.08.25 depended on a Windows mouse drag across rendered text. After image
 insertion SmartEditor can reflow/scroll the body, so DPI/zoom/screen-coordinate
 drift could leave the drag outside the paragraph and return selected=''.
 Selection itself does not need to be physical for persistence. The format
 command still goes through SmartEditor ONE's real toolbar/palette UI.
 """
 if e is None:return False,{'reason':'no-element'}
 try:
  rep=d.execute_script(r"""
   const e=arguments[0],raw=String(arguments[1]||'');
   const key=s=>String(s||'').normalize('NFC')
     .replace(/[\uFE0E\uFE0F\u200B-\u200D\u2060]/g,'').replace(/\s+/g,'');
   try{e.scrollIntoView({block:'center',inline:'nearest'});}catch(x){}
   const host=e.closest('[contenteditable=true]')||e;
   try{host.focus({preventScroll:true});}catch(x){try{host.focus();}catch(y){}}
   const rg=document.createRange();rg.selectNodeContents(e);
   const sel=window.getSelection();sel.removeAllRanges();sel.addRange(rg);
   const selected=String(sel.toString()||'');
   return {ok:key(selected)===key(raw||e.innerText||e.textContent||''),selected,chars:selected.length,
     anchorNode:sel.anchorNode&&sel.anchorNode.nodeName,focusNode:sel.focusNode&&sel.focusNode.nodeName,
     paragraph:String(e.innerText||e.textContent||'')};
  """,e,str(expected_text or '')) or {}
  if rep.get('ok'):
   rep['route']='verified-browser-range';return True,rep
  return False,{'reason':'browser-range-mismatch','want':str(expected_text)[:120],'range':rep}
 except Exception as ex:
  return False,{'reason':'browser-range-error','error':type(ex).__name__+': '+str(ex),'want':str(expected_text)[:120]}

def _v825_select_paragraph_native(d,e,expected_text=''):
 """v8.08.26: verified exact Range first; physical drag only as emergency fallback.

 Formatting is still committed ONLY by physical SmartEditor toolbar/palette
 clicks. No DOM style mutation or execCommand is used in this path.
 """
 if expected_text:
  try:e=_find_exact_body_paragraph(d,expected_text) or e
  except Exception:pass
 if e is None:return False,{'reason':'no-element'}
 ok,rep=_v826_select_paragraph_range(d,e,expected_text)
 if ok:return True,rep
 attempts=[{'route':'verified-browser-range','result':rep}]
 # SmartEditor may remount a paragraph immediately after an image component is
 # inserted. Re-find and retry once before any coordinate-based fallback.
 if expected_text:
  try:
   fresh=_find_exact_body_paragraph(d,expected_text)
   if fresh is not None:
    e=fresh;ok2,rep2=_v826_select_paragraph_range(d,e,expected_text)
    attempts.append({'route':'verified-browser-range-refind','result':rep2})
    if ok2:return True,rep2
  except Exception as ex:
   attempts.append({'route':'verified-browser-range-refind','error':type(ex).__name__+': '+str(ex)})
 # Emergency physical fallback. Recompute coordinates AFTER the focus click so
 # SmartEditor scroll/reflow cannot invalidate coordinates captured beforehand.
 for label in ('forward','reverse'):
  try:_win_physical_click_element(d,e);time.sleep(.10)
  except Exception:pass
  a,b,diag=_v825_paragraph_drag_points(d,e)
  start,end=(a,b) if label=='forward' else (b,a)
  if not start or not end:
   attempts.append({'route':'physical-'+label,'sent':False,'geom':diag});continue
  sent=_v825_drag(d,start,end);sel=_v825_selected_text(d);key=_v825_text_key(sel);want=_v825_text_key(expected_text or diag.get('text',''))
  attempts.append({'route':'physical-'+label,'sent':sent,'selected':sel[:120],'chars':len(sel),'geom':diag})
  if sent and want and key==want:return True,{'route':'physical-drag-'+label,'selected':sel,'lines':diag.get('lines',0)}
 return False,{'reason':'selection-all-routes-failed','want':str(expected_text)[:120],'attempts':attempts}
def _v825_find_exact_bg_chip(d,bg):
 """Read only: locate the exact existing SmartEditor color swatch element."""
 rgb=_hex_rgb(bg);rgb_css=f'rgb({rgb[0]}, {rgb[1]}, {rgb[2]})'
 try:
  return d.execute_script(r'''
   const target=String(arguments[0]||'').toLowerCase(),rgb=String(arguments[1]||'').toLowerCase().replace(/\s+/g,'');
   const norm=s=>String(s||'').toLowerCase().replace(/\s+/g,'');
   const vis=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>3&&r.height>3;};
   const all=[...document.querySelectorAll('button,[role=button],a,li,label,span,[data-color],[class*=color]')];
   for(const e of all){if(!vis(e))continue;const meta=((e.getAttribute('data-color')||'')+' '+(e.getAttribute('data-value')||'')+' '+(e.getAttribute('title')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('style')||'')).toLowerCase();if(meta.includes(target))return e;}
   for(const e of all){if(!vis(e))continue;const cs=getComputedStyle(e);if(norm(cs.backgroundColor)===rgb||norm(cs.color)===rgb)return e;}
   return null;
  ''',str(bg).lower(),rgb_css)
 except Exception:return None

def _v827_toolbar_inventory(d,limit=40):
 """Diagnostic-only inventory of visible editor controls.

 This is deliberately read-only.  It gives a useful snapshot when Naver changes
 toolbar markup instead of failing with the unhelpful "button not found" error.
 """
 try:
  return d.execute_script(r"""
   const lim=arguments[0],vis=e=>{try{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>2&&r.height>2;}catch(x){return false;}};
   const rows=[];for(const e of document.querySelectorAll('button,[role=button],a,label,[data-command],[data-action],[class*=toolbar]')){
    if(!vis(e))continue;const meta=[e.tagName,e.getAttribute('aria-label')||'',e.getAttribute('title')||'',e.getAttribute('data-command')||'',e.getAttribute('data-action')||'',String(e.className||''),String(e.innerText||e.textContent||'').trim().slice(0,60)].join(' | ');
    rows.push(meta);if(rows.length>=lim)break;
   }return rows;
  """,int(limit)) or []
 except Exception:return []

def _v827_find_toolbar_control(d,kind):
 """Find current SmartEditor toolbar control across markup variants.

 v8.08.26 searched only button/role=button aria/title/text.  The live editor can
 expose the same command through data-command/data-action or a class token while
 keeping the visible label in a nested child.  Prefer the old exact lookup, then
 use a scored read-only DOM lookup.
 """
 kind=str(kind or '').lower()
 labels=(['굵게','bold'] if kind=='bold' else
         (['글자 크기','폰트 크기','font size','fontsize','font-size'] if kind=='fontsize' else
          ['글자 배경색','배경색','텍스트 배경색','문자 배경색','형광펜','background','highlight','backcolor']))
 hit=toolbar(d,labels)
 if hit:return hit
 try:
  return d.execute_script(r"""
   const kind=arguments[0];
   const vis=e=>{try{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>4&&r.height>4;}catch(x){return false;}};
   const norm=s=>String(s||'').toLowerCase().replace(/\s+/g,' ');
   let best=null,bestScore=0;
   const all=[...document.querySelectorAll('button,[role=button],a,label,div,span,[data-command],[data-action]')];
   for(const e of all){if(!vis(e))continue;if(e.closest('.se-text-paragraph,.se-documentTitle,.se-section-documentTitle'))continue;
    const meta=norm([e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('data-command'),e.getAttribute('data-action'),e.getAttribute('data-name'),e.getAttribute('data-testid'),e.className,e.innerText].join(' '));
    let sc=0;
    if(kind==='bold'){
      if(meta.includes('굵게'))sc+=120;
      if(/(^|[ _\-])bold([ _\-]|$)/.test(meta))sc+=100;
      if(meta.includes('toolbar')&&meta.includes('bold'))sc+=40;
    }else if(kind==='fontsize'){
      if(meta.includes('글자 크기')||meta.includes('폰트 크기'))sc+=145;
      if(/font.?size|fontsize/.test(meta))sc+=120;
      if(meta.includes('toolbar')&&/size|font/.test(meta))sc+=35;
    }else{
      if(meta.includes('글자 배경색')||meta.includes('텍스트 배경색')||meta.includes('문자 배경색'))sc+=130;
      if(meta.includes('배경색')||meta.includes('형광펜'))sc+=100;
      if(/background|highlight|backcolor|hilite/.test(meta))sc+=80;
      if(meta.includes('toolbar')&&/color|background/.test(meta))sc+=25;
    }
    if((e.tagName==='BUTTON'||e.getAttribute('role')==='button')&&sc)sc+=12;
    if(sc>bestScore){best=e;bestScore=sc;}
   }
   return bestScore>=80?best:null;
  """,kind)
 except Exception:return None


def _v828_restore_editor_context(d,timeout=8):
 """Return WebDriver to the real SmartEditor host after probing toolbar/palette frames."""
 try:
  wait_frame(d,timeout=timeout)
  return True
 except Exception:
  try:d.switch_to.default_content()
  except Exception:pass
  return False

def _v828_control_here(d,kind):
 """Read-only current-document toolbar lookup that returns the clickable ancestor."""
 kind=str(kind or '').lower()
 hit=_v827_find_toolbar_control(d,kind)
 if hit is not None:
  try:
   return d.execute_script(r"""
    let e=arguments[0];
    return e.closest('button,[role=button],a,label,[data-command],[data-action]')||e;
   """,hit) or hit
  except Exception:return hit
 try:
  return d.execute_script(r"""
   const kind=arguments[0];
   const vis=e=>{try{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>4&&r.height>4;}catch(x){return false;}};
   const norm=s=>String(s||'').toLowerCase().replace(/\s+/g,' ');
   let best=null,bestScore=0;
   const all=[...document.querySelectorAll('button,[role=button],a,label,div,span,svg,[data-command],[data-action],[data-name],[data-testid]')];
   for(const raw of all){
    if(!vis(raw))continue;
    if(raw.closest('.se-text-paragraph,.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'))continue;
    let e=raw.closest('button,[role=button],a,label,[data-command],[data-action]')||raw;
    if(!vis(e))continue;
    const meta=norm([
      e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('data-command'),e.getAttribute('data-action'),
      e.getAttribute('data-name'),e.getAttribute('data-testid'),e.className,e.innerText,e.textContent,
      raw.getAttribute&&raw.getAttribute('aria-label'),raw.getAttribute&&raw.getAttribute('title'),
      raw.className&&raw.className.baseVal||raw.className
    ].join(' '));
    let sc=0;
    if(kind==='bold'){
      if(meta.includes('굵게'))sc+=160;
      if(/(^|[ _\-])bold([ _\-]|$)/.test(meta))sc+=135;
      if(/font.?weight|strong/.test(meta))sc+=90;
      if(meta.includes('toolbar')&&(/bold|굵게/.test(meta)))sc+=50;
    }else if(kind==='fontsize'){
      if(meta.includes('글자 크기')||meta.includes('폰트 크기'))sc+=180;
      if(/font.?size|fontsize/.test(meta))sc+=150;
      if(meta.includes('toolbar')&&/size|font/.test(meta))sc+=45;
    }else{
      if(meta.includes('글자 배경색')||meta.includes('텍스트 배경색')||meta.includes('문자 배경색'))sc+=170;
      if(meta.includes('배경색')||meta.includes('형광펜'))sc+=135;
      if(/background.?color|text.?background|highlight|backcolor|hilite/.test(meta))sc+=105;
      if(meta.includes('toolbar')&&/color|background|highlight/.test(meta))sc+=35;
    }
    if((e.tagName==='BUTTON'||e.getAttribute('role')==='button')&&sc)sc+=15;
    if(sc>bestScore){best=e;bestScore=sc;}
   }
   return bestScore>=85?best:null;
  """,kind)
 except Exception:return None

def _v828_switch_index_path(d,path):
 """Switch from top to an iframe index path, freshly resolving each level."""
 try:d.switch_to.default_content()
 except Exception:return False
 try:
  for idx in path:
   frames=d.find_elements(By.CSS_SELECTOR,'iframe,frame')
   if idx<0 or idx>=len(frames):return False
   d.switch_to.frame(frames[idx])
  return True
 except Exception:
  try:d.switch_to.default_content()
  except Exception:pass
  return False

def _v828_context_paths(d,max_depth=5,max_contexts=80):
 """Enumerate non-IME frame paths without keeping stale WebElement references."""
 out=[];queue=[()]
 while queue and len(out)<max_contexts:
  path=queue.pop(0)
  if not _v828_switch_index_path(d,path):continue
  out.append(path)
  if len(path)>=int(max_depth):continue
  try:frames=d.find_elements(By.CSS_SELECTOR,'iframe,frame')
  except Exception:frames=[]
  for i,fr in enumerate(frames):
   try:
    if _frame_is_auxiliary(fr) or not _visible(fr):continue
   except Exception:continue
   queue.append(path+(i,))
 return out

def _v828_find_control_any_context(d,kind,max_depth=5):
 """Find a toolbar control in top or any visible non-IME frame.

 Every context is entered from top by an index path, so a transient/stale frame
 cannot strand the driver in the wrong parent document.
 """
 kind=str(kind or '').lower();seen=[]
 paths=_v828_context_paths(d,max_depth=max_depth)
 for path in paths:
  if not _v828_switch_index_path(d,path):continue
  try:
   hit=_v828_control_here(d,kind)
   seen.append({'path':list(path) or ['top'],'hit':bool(hit)})
   if hit is not None:
    try:setattr(d,'_nb_last_toolbar_context',{'kind':kind,'path':list(path),'seen':seen[-30:]})
    except Exception:pass
    return hit,list(path)
  except Exception as ex:seen.append({'path':list(path) or ['top'],'error':type(ex).__name__})
 _v828_restore_editor_context(d,timeout=6)
 try:setattr(d,'_nb_last_toolbar_context',{'kind':kind,'path':None,'seen':seen[-40:]})
 except Exception:pass
 return None,None

def _v828_inventory_all_contexts(d,limit=100,max_depth=5):
 """Collect visible controls from every reachable document context."""
 rows=[]
 for path in _v828_context_paths(d,max_depth=max_depth):
  if not _v828_switch_index_path(d,path):continue
  try:
   vals=d.execute_script(r"""
    const vis=e=>{try{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>2&&r.height>2;}catch(x){return false;}};
    const out=[];for(const e of document.querySelectorAll('button,[role=button],a,label,[data-command],[data-action],[data-name],[data-testid],[class*=toolbar]')){
     if(!vis(e))continue;
     out.push([e.tagName,e.getAttribute('aria-label')||'',e.getAttribute('title')||'',e.getAttribute('data-command')||'',e.getAttribute('data-action')||'',e.getAttribute('data-name')||'',e.getAttribute('data-testid')||'',String(e.className||'').slice(0,120),String(e.innerText||e.textContent||'').trim().slice(0,60)].join(' | '));
     if(out.length>=35)break;
    }return out;
   """) or []
   for v in vals:
    rows.append((('frame-index='+('/'.join(map(str,path)) if path else 'top'))+' :: '+str(v))[:420])
    if len(rows)>=int(limit):break
  except Exception:pass
  if len(rows)>=int(limit):break
 _v828_restore_editor_context(d,timeout=6)
 return rows[:int(limit)]

def _v828_focus_and_select(d,text):
 """Restore editor host, focus the real contenteditable, then select exactly one paragraph."""
 if not _v828_restore_editor_context(d,timeout=8):
  return False,{'reason':'editor-context-not-found'}
 e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
 if e is None:return False,{'reason':'paragraph-not-found','text':str(text)[:100]}
 try:
  rep=d.execute_script(r"""
   const e=arguments[0],raw=String(arguments[1]||'');
   const key=s=>String(s||'').normalize('NFC').replace(/[\uFE0E\uFE0F\u200B-\u200D\u2060]/g,'').replace(/\s+/g,'');
   try{e.scrollIntoView({block:'center',inline:'nearest'});}catch(x){}
   const host=e.closest('[contenteditable=true]')||document.querySelector('.se-content [contenteditable=true]')||e;
   try{host.focus({preventScroll:true});}catch(x){try{host.focus();}catch(y){}}
   const r=document.createRange();r.selectNodeContents(e);
   const s=window.getSelection();s.removeAllRanges();s.addRange(r);
   const selected=String(s.toString()||'');
   const a=document.activeElement;
   return {ok:key(selected)===key(raw||e.innerText||e.textContent||''),selected,chars:selected.length,
     active:{tag:a&&a.tagName,id:a&&a.id,cls:a&&String(a.className||'').slice(0,120),ce:a&&a.getAttribute&&a.getAttribute('contenteditable')},
     host:{tag:host&&host.tagName,id:host&&host.id,cls:host&&String(host.className||'').slice(0,120),ce:host&&host.getAttribute&&host.getAttribute('contenteditable')}};
  """,e,str(text)) or {}
  if rep.get('ok'):return True,rep
  return False,{'reason':'focus-selection-mismatch','detail':rep}
 except Exception as ex:return False,{'reason':'focus-selection-error','error':type(ex).__name__+': '+str(ex)}

def _v828_keyboard_bold(d,text):
 """Try Ctrl+B only while WebDriver is definitely in the editor host."""
 ok,rep=_v828_focus_and_select(d,text)
 if not ok:return False,rep
 if _action_ctrl_b(d):
  done,_=_v827_wait_bold(d,text,1.4)
  if done:return True,{'route':'editor-context-webdriver-ctrl-b','selection':rep}
 ok2,rep2=_v828_focus_and_select(d,text)
 if ok2 and _win_ctrl_b(d):
  done,_=_v827_wait_bold(d,text,1.5)
  if done:return True,{'route':'editor-context-windows-ctrl-b','selection':rep2}
 return False,{'route':'ctrl-b-no-commit','first':rep,'second':rep2}

def _v828_click_toolbar_for_text(d,kind,text):
 """Reselect body text, find toolbar across all contexts, and invoke real SmartEditor UI.

 WebDriver's native element click is primary because it does not depend on
 Windows DPI/screen coordinates. Physical click is retained only as fallback.
 Neither route mutates DOM styles directly.
 """
 ok,sel=_v828_focus_and_select(d,text)
 if not ok:return False,{'reason':'pre-toolbar-selection-failed','selection':sel}
 btn,path=_v828_find_control_any_context(d,kind)
 if btn is None:
  inv=_v828_inventory_all_contexts(d,limit=80)
  return False,{'reason':'toolbar-control-not-found','kind':kind,'selection':sel,'inventory':inv}
 clicked=False;route=''
 try:
  btn.click();clicked=True;route='webdriver-native-click'
 except Exception:
  try:
   clicked=_win_physical_click_element(d,btn);route='windows-physical-click' if clicked else ''
  except Exception:clicked=False
 time.sleep(.38)
 _v828_restore_editor_context(d,timeout=8)
 return bool(clicked),{'route':route or 'click-failed','kind':kind,'path':path,'selection':sel}

def _v828_find_bg_chip_any_context(d,bg,max_depth=5):
 """Find the exact background swatch in top or any visible non-IME frame."""
 for path in _v828_context_paths(d,max_depth=max_depth):
  if not _v828_switch_index_path(d,path):continue
  try:
   e=_v825_find_exact_bg_chip(d,bg)
   if e is not None:return e,list(path)
  except Exception:pass
 _v828_restore_editor_context(d,timeout=6)
 return None,None


# ---------------------------------------------------------------------------
# v8.08.29 - TRUSTED POINTER SELECTION / SMARTEDITOR MODEL COMMIT
# ---------------------------------------------------------------------------
# A JavaScript Range can visually select text while SmartEditor ONE still keeps
# its internal selection/caret model elsewhere (the live diagnostics showed
# document.activeElement=BODY and no contenteditable host).  In that state
# Ctrl+B and toolbar clicks are syntactically "sent" but never serialize into
# the editor model.  v8.08.29 therefore creates the selection with Chrome's
# trusted Input.dispatchMouseEvent path.  JavaScript is used ONLY to read glyph
# geometry and verify selection text; it does not create or style the selection.

def _v829_editor_index_path(d,max_depth=5):
 """Return the index path to the live editor host and leave driver in it."""
 try:d.switch_to.default_content()
 except Exception:return None
 queue=[()]
 while queue:
  path=queue.pop(0)
  if not _v828_switch_index_path(d,path):continue
  try:
   if _editor_host_here(d):
    try:setattr(d,'_nb_editor_index_path',list(path))
    except Exception:pass
    return list(path)
  except Exception:pass
  if len(path)>=int(max_depth):continue
  try:frames=d.find_elements(By.CSS_SELECTOR,'iframe,frame')
  except Exception:frames=[]
  for i,fr in enumerate(frames):
   try:
    if _frame_is_auxiliary(fr) or not _visible(fr):continue
   except Exception:continue
   queue.append(tuple(path)+(i,))
 try:d.switch_to.default_content()
 except Exception:pass
 return None

def _v829_frame_viewport_offset(d,path):
 """Return target-frame viewport origin in top-document CSS pixels.

 The routine walks the same frame-index path from top and sums each iframe's
 getBoundingClientRect().  It intentionally uses CSS viewport coordinates,
 which are the coordinate system expected by CDP Input.dispatchMouseEvent and
 are independent of Windows DPI / browser chrome / monitor scaling.
 """
 ox=0.0;oy=0.0
 try:d.switch_to.default_content()
 except Exception:return None
 try:
  for idx in list(path or []):
   frames=d.find_elements(By.CSS_SELECTOR,'iframe,frame')
   if int(idx)<0 or int(idx)>=len(frames):return None
   fr=frames[int(idx)]
   q=d.execute_script("const r=arguments[0].getBoundingClientRect();return {x:r.left,y:r.top,w:r.width,h:r.height};",fr) or {}
   ox+=float(q.get('x') or 0);oy+=float(q.get('y') or 0)
   d.switch_to.frame(fr)
  return {'x':ox,'y':oy,'path':list(path or [])}
 except Exception:
  try:d.switch_to.default_content()
  except Exception:pass
  return None

def _v829_paragraph_glyph_points_here(d,e):
 """Read first/last visible glyph points in the CURRENT editor frame."""
 try:
  return d.execute_script(r"""
   const e=arguments[0];
   try{e.scrollIntoView({block:'center',inline:'nearest'});}catch(x){}
   const visRect=r=>r&&r.width>.3&&r.height>2;
   const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
   const chars=[];let n;
   while(n=walker.nextNode()){
    const v=String(n.nodeValue||'');
    for(let i=0;i<v.length;i++){
     if(/\s/.test(v[i]))continue;
     const rg=document.createRange();
     try{rg.setStart(n,i);rg.setEnd(n,i+1);}catch(x){continue;}
     const rs=[...rg.getClientRects()].filter(visRect);if(!rs.length)continue;
     const r=rs[0];chars.push({l:r.left,r:r.right,t:r.top,b:r.bottom,w:r.width,h:r.height});
    }
   }
   if(!chars.length)return null;
   const a=chars[0],b=chars[chars.length-1],pr=e.getBoundingClientRect();
   // Quarter-glyph -> three-quarter-glyph reliably includes first/last char.
   return {sx:a.l+Math.max(.7,a.w*.22),sy:a.t+a.h*.55,
           ex:b.l+Math.max(.8,b.w*.82),ey:b.t+b.h*.55,
           px:pr.left,py:pr.top,pw:pr.width,ph:pr.height,
           text:String(e.innerText||e.textContent||''),glyphs:chars.length,
           vw:window.innerWidth,vh:window.innerHeight};
  """,e)
 except Exception:return None

def _v829_cdp_triple_click(d,point):
 """Trusted Chromium triple-click; browsers normally select the whole paragraph."""
 if not point:return False
 try:
  x,y=float(point[0]),float(point[1])
  d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y,'button':'none','buttons':0})
  for c in (1,2,3):
   d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','buttons':1,'clickCount':c})
   d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','buttons':0,'clickCount':c})
   time.sleep(.055)
  time.sleep(.14);return True
 except Exception:return False

def _v829_cdp_drag(d,start,end):
 """Trusted Chrome pointer drag in top-viewport CSS coordinates."""
 if not start or not end:return False
 try:
  x1,y1=float(start[0]),float(start[1]);x2,y2=float(end[0]),float(end[1])
  d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x1,'y':y1,'button':'none','buttons':0})
  d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mousePressed','x':x1,'y':y1,'button':'left','buttons':1,'clickCount':1})
  steps=max(12,min(36,int(abs(y2-y1)/8)+14))
  for i in range(1,steps+1):
   f=i/steps;x=x1+(x2-x1)*f;y=y1+(y2-y1)*f
   d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y,'button':'left','buttons':1})
   time.sleep(.009)
  d.execute_cdp_cmd('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x2,'y':y2,'button':'left','buttons':0,'clickCount':1})
  time.sleep(.14);return True
 except Exception:return False

def _v829_selection_state(d):
 try:
  return d.execute_script(r"""
   const s=window.getSelection(),a=document.activeElement;
   const info=x=>x?{tag:x.tagName||x.nodeName,id:x.id||'',cls:String(x.className||'').slice(0,140),ce:x.getAttribute&&x.getAttribute('contenteditable')}:null;
   return {selected:String(s&&s.toString()||''),chars:String(s&&s.toString()||'').length,active:info(a),
           input_buffer:!!(a&&a.tagName==='IFRAME'&&/input[_-]?buffer|inputbuffer|ime/i.test((a.id||'')+' '+(a.name||'')+' '+String(a.className||'')))};
  """) or {}
 except Exception:return {}

def _v829_native_select_text(d,text):
 """Select a paragraph through trusted browser pointer input, not JS Range."""
 want=str(text or '')
 # Maximize/foreground BEFORE geometry measurement.  v8.08.25 did this after
 # measurement, which could invalidate every physical coordinate on first use.
 try:_win_foreground_chrome(d)
 except Exception:pass
 path=_v829_editor_index_path(d,max_depth=5)
 if path is None:return False,{'reason':'editor-index-path-not-found'}
 e=_find_exact_body_paragraph(d,want) or find_exact(d,want)
 if e is None:return False,{'reason':'paragraph-not-found','text':want[:120],'path':path}
 # JS only reads rendered glyph geometry; it does NOT alter Selection.
 geom=_v829_paragraph_glyph_points_here(d,e)
 if not geom:return False,{'reason':'glyph-geometry-missing','text':want[:120],'path':path}
 # Scrolling may have happened in geometry read. Re-resolve frame positions now.
 off=_v829_frame_viewport_offset(d,path)
 if not off:return False,{'reason':'frame-offset-failed','path':path,'geom':geom}
 sx=off['x']+float(geom['sx']);sy=off['y']+float(geom['sy'])
 ex=off['x']+float(geom['ex']);ey=off['y']+float(geom['ey'])
 attempts=[]
 # Route 0: a trusted triple-click is the most user-like whole-paragraph
 # selection and avoids line-wrap/DPI geometry entirely.
 try:d.switch_to.default_content()
 except Exception:pass
 mid=((sx+ex)/2.0, sy if abs(ey-sy)>3 else (sy+ey)/2.0)
 sent=_v829_cdp_triple_click(d,mid)
 _v828_switch_index_path(d,path)
 st=_v829_selection_state(d);sel=str(st.get('selected') or '')
 attempts.append({'route':'cdp-trusted-triple-click','sent':sent,'selected':sel[:160],'chars':len(sel),'active':st.get('active'),'input_buffer':st.get('input_buffer'),'point':[round(mid[0],1),round(mid[1],1)]})
 if sent and _v825_text_key(sel)==_v825_text_key(want):
  rep=attempts[-1].copy();rep.update({'ok':True,'path':path,'glyphs':geom.get('glyphs')})
  try:setattr(d,'_nb_last_native_selection',rep)
  except Exception:pass
  return True,rep
 # Route 1/2: exact first-glyph to last-glyph trusted drags.
 for label,a,b in [('forward',(sx,sy),(ex,ey)),('reverse',(ex,ey),(sx,sy))]:
  try:d.switch_to.default_content()
  except Exception:pass
  sent=_v829_cdp_drag(d,a,b)
  _v828_switch_index_path(d,path)
  st=_v829_selection_state(d);sel=str(st.get('selected') or '')
  ok=bool(sent and _v825_text_key(sel)==_v825_text_key(want))
  attempts.append({'route':'cdp-trusted-drag-'+label,'sent':sent,'selected':sel[:160],'chars':len(sel),'active':st.get('active'),'input_buffer':st.get('input_buffer'),'start':[round(a[0],1),round(a[1],1)],'end':[round(b[0],1),round(b[1],1)]})
  if ok:
   rep=attempts[-1].copy();rep.update({'ok':True,'path':path,'glyphs':geom.get('glyphs')})
   try:setattr(d,'_nb_last_native_selection',rep)
   except Exception:pass
   return True,rep
  # Recompute geometry after failed selection because SmartEditor may scroll on mouseup.
  e=_find_exact_body_paragraph(d,want) or e;geom=_v829_paragraph_glyph_points_here(d,e) or geom
  off=_v829_frame_viewport_offset(d,path) or off
  sx=off['x']+float(geom['sx']);sy=off['y']+float(geom['sy']);ex=off['x']+float(geom['ex']);ey=off['y']+float(geom['ey'])
 return False,{'reason':'trusted-selection-failed','path':path,'attempts':attempts,'geom':geom}

def _v829_focus_input_buffer_bridge(d):
 """Focus Naver's legitimate IME/input_buffer without changing body text.

 SmartEditor ONE uses a tiny iframe as the actual keyboard receiver even though
 the selected paragraph itself is not contenteditable.  The v8.08.28 live log
 proved the opposite state (selected body text + active BODY + ce=None), which is
 why Ctrl+B had nowhere editable to commit.  Focusing the existing bridge after
 a trusted drag keeps the DOM selection visible while routing the shortcut to
 SmartEditor's own keyboard receiver.  No iframe is removed or edited here.
 """
 try:
  return d.execute_script(r"""
   const s=window.getSelection(),before=String(s&&s.toString()||'');
   const rx=/input[_-]?buffer|inputbuffer|ime/i;
   const fs=[...document.querySelectorAll('iframe,frame')];
   const f=fs.find(x=>rx.test((x.id||'')+' '+(x.name||'')+' '+String(x.className||'')+' '+(x.title||'')));
   if(!f)return {ok:false,reason:'no-input-buffer',selected:before};
   try{f.focus({preventScroll:true});}catch(e){try{f.focus();}catch(x){}}
   try{if(f.contentWindow)f.contentWindow.focus();}catch(e){}
   const a=document.activeElement,after=String(window.getSelection&&window.getSelection().toString()||'');
   return {ok:!!(a===f||/input[_-]?buffer|inputbuffer|ime/i.test((a&&a.id||'')+' '+(a&&a.name||'')+' '+String(a&&a.className||''))),
     frame:{id:f.id||'',name:f.name||'',cls:String(f.className||'')},active:a?{tag:a.tagName,id:a.id||'',cls:String(a.className||'')}:null,
     selected_before:before,selected_after:after};
  """) or {}
 except Exception as ex:return {'ok':False,'reason':type(ex).__name__+': '+str(ex)[:260]}

def _v829_cdp_ctrl_b(d):
 """Trusted Chromium Ctrl+B dispatched to the browser's actual focused target."""
 try:
  d.execute_cdp_cmd('Input.dispatchKeyEvent',{'type':'rawKeyDown','key':'Control','code':'ControlLeft','windowsVirtualKeyCode':17,'nativeVirtualKeyCode':17,'modifiers':2})
  d.execute_cdp_cmd('Input.dispatchKeyEvent',{'type':'rawKeyDown','key':'b','code':'KeyB','windowsVirtualKeyCode':66,'nativeVirtualKeyCode':66,'modifiers':2})
  d.execute_cdp_cmd('Input.dispatchKeyEvent',{'type':'keyUp','key':'b','code':'KeyB','windowsVirtualKeyCode':66,'nativeVirtualKeyCode':66,'modifiers':2})
  d.execute_cdp_cmd('Input.dispatchKeyEvent',{'type':'keyUp','key':'Control','code':'ControlLeft','windowsVirtualKeyCode':17,'nativeVirtualKeyCode':17,'modifiers':0})
  return True
 except Exception:return False


# ---------------------------------------------------------------------------
# v8.08.30 - INPUT_BUFFER KEYBOARD SELECTION / MODEL COMMIT
# ---------------------------------------------------------------------------
# Live v8.08.29 diagnostics proved that pointer selection itself is the wrong
# primitive on this SmartEditor build: every CDP click/drag is intercepted by
# iframe#input_buffer, leaving selected="" even though the paragraph text is
# visible. That iframe is Naver's legitimate keyboard/IME receiver. v8.08.30
# therefore uses it instead of fighting it:
#
#   physical click paragraph -> input_buffer active -> END
#   -> Shift+Home / Shift+Left keyboard selection -> Ctrl+B / toolbar command.
#
# No JS Range, DOM style mutation, execCommand, or CDP mouse drag is used by
# the save-path formatter.

def _v830_win_key(vk, *, shift=False, ctrl=False):
    if os.name != 'nt':
        return False
    try:
        u=ctypes.windll.user32
        KEYUP=0x0002; VK_SHIFT=0x10; VK_CONTROL=0x11
        if ctrl:u.keybd_event(VK_CONTROL,0,0,0)
        if shift:u.keybd_event(VK_SHIFT,0,0,0)
        u.keybd_event(int(vk),0,0,0)
        u.keybd_event(int(vk),0,KEYUP,0)
        if shift:u.keybd_event(VK_SHIFT,0,KEYUP,0)
        if ctrl:u.keybd_event(VK_CONTROL,0,KEYUP,0)
        return True
    except Exception:
        return False

def _v830_selection_snapshot(d):
    """Read-only parent-document selection and active/input_buffer state."""
    try:
        return d.execute_script(r"""
          const s=window.getSelection(),a=document.activeElement;
          const info=x=>x?{tag:x.tagName||x.nodeName,id:x.id||'',cls:String(x.className||'').slice(0,140),
                            ce:x.getAttribute&&x.getAttribute('contenteditable')}:null;
          const rx=/input[_-]?buffer|inputbuffer|ime/i;
          return {selected:String(s&&s.toString()||''), chars:String(s&&s.toString()||'').length,
                  active:info(a), input_buffer:!!(a&&a.tagName==='IFRAME'&&rx.test((a.id||'')+' '+(a.name||'')+' '+String(a.className||'')))};
        """) or {}
    except Exception:
        return {}

def _v830_focus_paragraph_keyboard(d,text):
    """Focus the exact paragraph with a real click and return its fresh element."""
    _v828_restore_editor_context(d,timeout=8)
    e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
    if e is None:
        return None,{'reason':'paragraph-not-found','text':str(text)[:120]}
    try:
        d.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",e)
        time.sleep(.12)
    except Exception:
        pass
    clicked=False
    try:
        clicked=_win_physical_click_element(d,e)
    except Exception:
        clicked=False
    if not clicked:
        try:
            ActionChains(d).move_to_element(e).click().perform();clicked=True
        except Exception:
            clicked=False
    time.sleep(.18)
    st=_v830_selection_snapshot(d)
    return (e if clicked else None),{'clicked':clicked,'state':st}

def _v830_keyboard_select_text(d,text):
    """Select one SmartEditor paragraph through Naver's active keyboard bridge."""
    want=str(text or '')
    want_key=_v825_text_key(want)
    if not want_key:
        return False,{'reason':'empty-target'}

    e,focus=_v830_focus_paragraph_keyboard(d,want)
    if e is None:
        return False,{'reason':'focus-failed','focus':focus}
    routes=[]

    # Route A: END + Shift+HOME, matching a human keyboard selection.
    _v830_win_key(0x23)  # VK_END
    time.sleep(.05)
    _v830_win_key(0x24,shift=True)  # VK_HOME + Shift
    time.sleep(.15)
    st=_v830_selection_snapshot(d);sel=str(st.get('selected') or '')
    routes.append({'route':'input-buffer-end-shift-home','selected':sel[:180],'chars':len(sel),
                   'active':st.get('active'),'input_buffer':st.get('input_buffer')})
    if _v825_text_key(sel)==want_key:
        rep=routes[-1].copy();rep.update({'ok':True})
        try:setattr(d,'_nb_last_native_selection',rep)
        except Exception:pass
        return True,rep

    # Route B: expand from paragraph end one Shift+LEFT at a time and stop on
    # the ACTUAL selected string. This is safe for emoji/VS16/grapheme movement.
    e,focus2=_v830_focus_paragraph_keyboard(d,want)
    if e is None:
        return False,{'reason':'refocus-failed','routes':routes,'focus':focus2}
    _v830_win_key(0x23)
    time.sleep(.04)
    max_steps=max(8,min(220,len(want)+24))
    hit=None
    for i in range(max_steps):
        _v830_win_key(0x25,shift=True)  # VK_LEFT + Shift
        if i<6 or i%2==1 or i>=max_steps-4:
            time.sleep(.012)
            st=_v830_selection_snapshot(d);sel=str(st.get('selected') or '')
            key=_v825_text_key(sel)
            if key==want_key:
                hit={'route':'input-buffer-shift-left','steps':i+1,'selected':sel[:180],'chars':len(sel),
                     'active':st.get('active'),'input_buffer':st.get('input_buffer'),'ok':True}
                break
            if key and len(key)>len(want_key)+8 and not key.endswith(want_key):
                break
    if hit:
        routes.append(hit)
        try:setattr(d,'_nb_last_native_selection',hit)
        except Exception:pass
        return True,hit

    st=_v830_selection_snapshot(d);sel=str(st.get('selected') or '')
    routes.append({'route':'input-buffer-shift-left-failed','selected':sel[:180],'chars':len(sel),
                   'active':st.get('active'),'input_buffer':st.get('input_buffer'),'max_steps':max_steps})
    # SmartEditor ONE may keep the model selection internal while the parent
    # window.getSelection() stays empty. If input_buffer is the active keyboard
    # receiver after our exact-paragraph click + keyboard selection sequence,
    # allow the native formatting command to prove success by changing ONLY the
    # target paragraph. This avoids false aborts while remaining fail-safe.
    if bool(st.get('input_buffer')) or bool((focus2.get('state') or {}).get('input_buffer')):
        rep={'route':'input-buffer-keyboard-selection-unverified','ok':True,'verified':False,
             'selected':sel[:180],'chars':len(sel),'active':st.get('active'),
             'input_buffer':True,'routes':routes}
        try:setattr(d,'_nb_last_native_selection',rep)
        except Exception:pass
        return True,rep
    return False,{'reason':'keyboard-selection-failed','routes':routes,'focus':focus,'focus2':focus2}

def _v830_keyboard_bold(d,text):
    """Commit bold only after a real keyboard selection exists."""
    ok,sel=_v830_keyboard_select_text(d,text)
    if not ok:
        return False,{'route':'keyboard-selection-failed','selection':sel}
    attempts=[]
    if _win_ctrl_b(d):
        attempts.append({'route':'input-buffer-selection+windows-ctrl-b','selection':sel})
        _v828_restore_editor_context(d,timeout=8)
        done,_=_v827_wait_bold(d,text,1.8)
        if done:return True,attempts[-1]

    ok2,sel2=_v830_keyboard_select_text(d,text)
    if ok2 and _v829_cdp_ctrl_b(d):
        attempts.append({'route':'input-buffer-selection+cdp-ctrl-b','selection':sel2})
        _v828_restore_editor_context(d,timeout=8)
        done,_=_v827_wait_bold(d,text,1.8)
        if done:return True,attempts[-1]

    ok3,sel3=_v830_keyboard_select_text(d,text)
    if ok3:
        time.sleep(.28)
        btn,path=_v828_find_control_any_context(d,'bold')
        if btn is not None:
            clicked=False
            try:btn.click();clicked=True
            except Exception:
                try:clicked=_win_physical_click_element(d,btn)
                except Exception:clicked=False
            attempts.append({'route':'input-buffer-selection+toolbar-bold','selection':sel3,'path':path,'clicked':clicked})
            time.sleep(.45);_v828_restore_editor_context(d,timeout=8)
            done,_=_v827_wait_bold(d,text,2.0)
            if done:return True,attempts[-1]
    return False,{'route':'keyboard-bold-no-commit','attempts':attempts,
                 'selection1':sel,'selection2':sel2 if 'sel2' in locals() else None,
                 'selection3':sel3 if 'sel3' in locals() else None,
                 'input_buffers':_input_buffer_inventory(d)}

def _v830_native_background(d,e,text,bg):
    """Commit background color from an input_buffer keyboard selection."""
    failures=[]
    for attempt in (1,2):
        ok,sel=_v830_keyboard_select_text(d,text)
        if not ok:
            failures.append({'attempt':attempt,'stage':'selection','diag':sel})
            continue
        time.sleep(.30)
        btn,path=_v828_find_control_any_context(d,'background')
        if btn is None:
            failures.append({'attempt':attempt,'stage':'toolbar-not-found','selection':sel})
            time.sleep(.20)
            continue
        clicked=False
        try:btn.click();clicked=True
        except Exception:
            try:clicked=_win_physical_click_element(d,btn)
            except Exception:clicked=False
        if not clicked:
            failures.append({'attempt':attempt,'stage':'toolbar-click-failed','path':path,'selection':sel})
            _v828_restore_editor_context(d,timeout=6)
            continue
        time.sleep(.50)
        chip,cpath=_v828_find_bg_chip_any_context(d,bg)
        if chip is None:
            failures.append({'attempt':attempt,'stage':'chip-not-found','path':path,'selection':sel})
            _v828_restore_editor_context(d,timeout=6)
            continue
        chip_clicked=False
        try:chip.click();chip_clicked=True
        except Exception:
            try:chip_clicked=_win_physical_click_element(d,chip)
            except Exception:chip_clicked=False
        if not chip_clicked:
            failures.append({'attempt':attempt,'stage':'chip-click-failed','path':path,'palette_path':cpath,'selection':sel})
            _v828_restore_editor_context(d,timeout=6)
            continue
        time.sleep(.75);_v828_restore_editor_context(d,timeout=8)
        fresh=_find_exact_body_paragraph(d,text) or e
        if _exact_bg_present(d,fresh,bg):
            return True
        failures.append({'attempt':attempt,'stage':'commit-not-visible','path':path,'palette_path':cpath,'selection':sel})
        time.sleep(.25)
    inv=_v828_inventory_all_contexts(d,limit=120)
    raise RuntimeError(f'SmartEditor 배경색 {bg} input_buffer-keyboard commit 실패 · engine={ENGINE_BUILD} · attempts='+
                       json.dumps(failures,ensure_ascii=False)[:1900]+' · controls='+json.dumps(inv,ensure_ascii=False)[:1600])


# ---------------------------------------------------------------------------
# v8.08.50 - font-size mutation removed. SmartEditor default size is preserved.

# v8.08.31 - SMARTEDITOR VIRTUAL SELECTION / ATTEMPT-AND-VERIFY FORMAT COMMIT
# ---------------------------------------------------------------------------
# Live v8.08.29 diagnostics showed the real SmartEditor behavior clearly:
# CDP trusted pointer gestures caused iframe#input_buffer to become active while
# window.getSelection().toString() remained empty.  SmartEditor ONE historically
# uses a virtual cursor / input buffer, so parent DOM selection text is NOT a
# reliable proof that the editor has no internal selection.
#
# v8.08.30 then made the opposite mistake: it abandoned pointer selection and
# tried END/Shift+Home, but the live v8.08.30 diagnostic showed active=BODY and
# input_buffer=false, so the keyboard selection never entered SmartEditor's
# internal model.
#
# v8.08.31 therefore uses a fail-safe attempt-and-verify transaction:
#   1) create a trusted pointer selection on the EXACT paragraph,
#   2) accept it as a *candidate* only if SmartEditor's input_buffer is active
#      (or native DOM selection exactly matches),
#   3) immediately issue the real SmartEditor formatting command,
#   4) judge success ONLY by the target paragraph's rendered style.
# No DOM style injection / execCommand is used.

def _v831_make_virtual_selection(d,text,route_index=0):
    """Create ONE trusted SmartEditor virtual-selection candidate.

    route_index: 0=triple click, 1=forward drag, 2=reverse drag.
    The command is sent only if the exact DOM selection is visible OR
    SmartEditor's own input_buffer becomes the active receiver.
    """
    want=str(text or '');want_key=_v825_text_key(want)
    if not want_key:return False,{'reason':'empty-target'}
    try:_win_foreground_chrome(d)
    except Exception:pass
    path=_v829_editor_index_path(d,max_depth=5)
    if path is None:return False,{'reason':'editor-index-path-not-found'}
    _v828_switch_index_path(d,path)
    e=_find_exact_body_paragraph(d,want) or find_exact(d,want)
    if e is None:return False,{'reason':'paragraph-not-found','text':want[:120],'path':path}
    geom=_v829_paragraph_glyph_points_here(d,e)
    if not geom:return False,{'reason':'glyph-geometry-missing','text':want[:120],'path':path}
    off=_v829_frame_viewport_offset(d,path)
    if not off:return False,{'reason':'frame-offset-failed','path':path,'geom':geom}
    sx=off['x']+float(geom['sx']);sy=off['y']+float(geom['sy'])
    ex=off['x']+float(geom['ex']);ey=off['y']+float(geom['ey'])
    mid=((sx+ex)/2.0, sy if abs(ey-sy)>3 else (sy+ey)/2.0)
    specs=[('cdp-trusted-triple-click',mid,None),
           ('cdp-trusted-drag-forward',(sx,sy),(ex,ey)),
           ('cdp-trusted-drag-reverse',(ex,ey),(sx,sy))]
    ri=max(0,min(2,int(route_index or 0)));label,a,b=specs[ri]
    try:d.switch_to.default_content()
    except Exception:pass
    sent=_v829_cdp_triple_click(d,a) if b is None else _v829_cdp_drag(d,a,b)
    _v828_switch_index_path(d,path)
    st=_v829_selection_state(d);sel=str(st.get('selected') or '')
    exact=bool(_v825_text_key(sel)==want_key);internal=bool(st.get('input_buffer'))
    rep={'route':label,'route_index':ri,'sent':bool(sent),'selected':sel[:180],'chars':len(sel),
         'active':st.get('active'),'input_buffer':internal,'exact_dom_selection':exact,
         'path':list(path),'glyphs':geom.get('glyphs'),'candidate':bool(sent and (exact or internal))}
    if b is None:rep['point']=[round(a[0],1),round(a[1],1)]
    else:
        rep['start']=[round(a[0],1),round(a[1],1)];rep['end']=[round(b[0],1),round(b[1],1)]
    if rep['candidate']:
        try:setattr(d,'_nb_last_native_selection',rep)
        except Exception:pass
        return True,rep
    rep['reason']='no-smarteditor-virtual-selection'
    return False,rep

def _v831_virtual_bold(d,text):
    """Bold via SmartEditor virtual selection with route rotation + target verification."""
    attempts=[]
    commands=('windows-ctrl-b','cdp-ctrl-b','toolbar-bold')
    for command in commands:
        for ri in (0,1,2):
            ok,sel=_v831_make_virtual_selection(d,text,ri)
            if not ok:
                attempts.append({'command':command,'route_index':ri,'selection':sel})
                continue
            applied=False;extra={}
            if command=='windows-ctrl-b':
                applied=bool(_win_ctrl_b(d))
            elif command=='cdp-ctrl-b':
                applied=bool(_v829_cdp_ctrl_b(d))
            else:
                time.sleep(.20)
                btn,path=_v828_find_control_any_context(d,'bold');extra={'toolbar_path':path}
                if btn is not None:
                    try:btn.click();applied=True
                    except Exception:
                        try:applied=bool(_win_physical_click_element(d,btn))
                        except Exception:applied=False
            attempts.append({'command':command,'route_index':ri,'selection':sel,'sent':bool(applied),**extra})
            if not applied:continue
            time.sleep(.42);_v828_restore_editor_context(d,timeout=8)
            done,_=_v827_wait_bold(d,text,2.1)
            if done:return True,attempts[-1]
            # Do not repeat the same command on the same virtual selection. The
            # next route creates a fresh selection, preventing accidental toggle.
    return False,{'route':'virtual-bold-no-commit','attempts':attempts,
                  'input_buffers':_input_buffer_inventory(d)}

def _v831_virtual_background(d,e,text,bg):
    """Apply exact background color through SmartEditor UI after virtual selection."""
    attempts=[]
    for i,ri in enumerate((1,2,0)):
        ok,sel=_v831_make_virtual_selection(d,text,ri)
        if not ok:
            attempts.append({'attempt':i+1,'stage':'selection','diag':sel});continue
        time.sleep(.22)
        btn,path=_v828_find_control_any_context(d,'background')
        if btn is None:
            attempts.append({'attempt':i+1,'stage':'background-control-not-found','selection':sel});continue
        clicked=False
        try:btn.click();clicked=True
        except Exception:
            try:clicked=bool(_win_physical_click_element(d,btn))
            except Exception:clicked=False
        if not clicked:
            attempts.append({'attempt':i+1,'stage':'background-control-click-failed','path':path,'selection':sel});continue
        time.sleep(.45)
        chip,cpath=_v828_find_bg_chip_any_context(d,bg)
        if chip is None:
            attempts.append({'attempt':i+1,'stage':'bg-chip-not-found','path':path,'selection':sel});continue
        cc=False
        try:chip.click();cc=True
        except Exception:
            try:cc=bool(_win_physical_click_element(d,chip))
            except Exception:cc=False
        if not cc:
            attempts.append({'attempt':i+1,'stage':'bg-chip-click-failed','path':path,'palette_path':cpath,'selection':sel});continue
        time.sleep(.75)
        _v828_restore_editor_context(d,timeout=8)
        fresh=_find_exact_body_paragraph(d,text) or e
        if fresh is not None and _exact_bg_present(d,fresh,bg):
            return True
        attempts.append({'attempt':i+1,'stage':'background-not-committed','path':path,'palette_path':cpath,'selection':sel})
    inv=_v828_inventory_all_contexts(d,limit=140)
    raise RuntimeError('SmartEditor 배경색 virtual-selection commit 실패 · engine='+ENGINE_BUILD+
                       ' · attempts='+json.dumps(attempts,ensure_ascii=False)[:2400]+
                       ' · controls='+json.dumps(inv,ensure_ascii=False)[:1800])

def _v829_keyboard_bold(d,text):
 """Bold through trusted selection, SmartEditor IME bridge, and native keys."""
 ok,sel=_v829_native_select_text(d,text)
 if not ok:return False,{'route':'trusted-selection-failed','selection':sel}
 routes=[]
 # Route 1: native selection itself may already move SmartEditor's keyboard
 # receiver to input_buffer.  Send the real Windows shortcut first.
 if _win_ctrl_b(d):
  routes.append({'route':'trusted-drag+windows-ctrl-b','selection':sel})
  _v828_restore_editor_context(d,timeout=8)
  done,_=_v827_wait_bold(d,text,1.5)
  if done:return True,routes[-1]
 # Route 2: the live v8.08.28 diagnostic had active=BODY / ce=None. Explicitly
 # focus Naver's OWN input_buffer keyboard bridge while preserving native text
 # selection, then send Ctrl+B again. This is not the old paste/bypass logic.
 ok2,sel2=_v829_native_select_text(d,text)
 bridge={}
 if ok2:
  bridge=_v829_focus_input_buffer_bridge(d)
  if bridge.get('ok') and _v825_text_key(bridge.get('selected_after') or bridge.get('selected_before') or '')==_v825_text_key(text):
   if _win_ctrl_b(d):
    routes.append({'route':'trusted-drag+input-buffer+windows-ctrl-b','selection':sel2,'bridge':bridge})
    _v828_restore_editor_context(d,timeout=8)
    done,_=_v827_wait_bold(d,text,1.7)
    if done:return True,routes[-1]
 # Route 3: Chromium trusted keyboard event against a freshly native-selected
 # paragraph. This stays outside Selenium ActionChains/JS execCommand.
 ok3,sel3=_v829_native_select_text(d,text)
 if ok3 and _v829_cdp_ctrl_b(d):
  routes.append({'route':'trusted-drag+cdp-ctrl-b','selection':sel3})
  _v828_restore_editor_context(d,timeout=8)
  done,_=_v827_wait_bold(d,text,1.7)
  if done:return True,routes[-1]
 return False,{'route':'trusted-keyboard-no-commit','routes':routes,'first':sel,'bridge':bridge,'second':sel2 if 'sel2' in locals() else None,'third':sel3 if 'sel3' in locals() else None,'input_buffers':_input_buffer_inventory(d)}

def _v829_click_toolbar_for_text(d,kind,text):
 """Open/commit SmartEditor formatting only after a trusted text selection."""
 ok,sel=_v829_native_select_text(d,text)
 if not ok:return False,{'reason':'trusted-toolbar-selection-failed','selection':sel}
 # The contextual text toolbar may be mounted only AFTER native selection.
 time.sleep(.22)
 btn,path=_v828_find_control_any_context(d,kind)
 if btn is None:
  inv=_v828_inventory_all_contexts(d,limit=130)
  return False,{'reason':'toolbar-control-not-found-after-trusted-selection','kind':kind,'selection':sel,'inventory':inv}
 # Record the exact matched control before clicking; useful if Naver changes UI.
 try:
  meta=d.execute_script("return [arguments[0].tagName,arguments[0].getAttribute('aria-label')||'',arguments[0].getAttribute('title')||'',arguments[0].getAttribute('data-command')||'',arguments[0].getAttribute('data-action')||'',String(arguments[0].className||''),String(arguments[0].innerText||arguments[0].textContent||'').trim()].join(' | ');",btn)
 except Exception:meta=''
 clicked=False;route=''
 try:
  btn.click();clicked=True;route='webdriver-native-click'
 except Exception:
  try:
   clicked=_win_physical_click_element(d,btn);route='windows-physical-click' if clicked else ''
  except Exception:clicked=False
 time.sleep(.42);_v828_restore_editor_context(d,timeout=8)
 return bool(clicked),{'route':route or 'click-failed','kind':kind,'path':path,'selection':sel,'control':str(meta)[:700]}

def _v827_wait_bold(d,text,timeout=1.25):
 end=time.time()+max(.3,float(timeout))
 last=None
 while time.time()<end:
  try:last=_find_exact_body_paragraph(d,text) or last
  except Exception:pass
  if last is not None and _bold_present(d,last):return True,last
  time.sleep(.10)
 return False,last

def _v825_native_background(d,e,text,bg):
 """v8.08.31 native background commit using SmartEditor virtual selection."""
 return _v831_virtual_background(d,e,text,bg)

def _v825_native_bold(d,e,text):
 """v8.08.31 persist bold using SmartEditor virtual selection + native command verification."""
 if e is not None and _bold_present(d,e):return True
 kb,kdiag=_v831_virtual_bold(d,text)
 if kb:return True
 inv=_v828_inventory_all_contexts(d,limit=120)
 raise RuntimeError('SmartEditor 굵게 virtual/native commit 실패 · engine='+ENGINE_BUILD+
                    ' · keyboard='+json.dumps(kdiag,ensure_ascii=False)[:1450]+
                    ' · all_frame_controls='+json.dumps(inv,ensure_ascii=False)[:1900])

def _v825_neutral_commit_click(d,target_text=''):
 """Collapse selection with a real click and allow SmartEditor model serialization."""
 target=_v825_text_key(target_text)
 try:
  for p in d.find_elements(By.CSS_SELECTOR,'p.se-text-paragraph'):
   try:
    if not p.is_displayed():continue
    if p.find_elements(By.XPATH,"./ancestor::*[contains(@class,'documentTitle') or contains(@class,'se-toolbar') or contains(@class,'se-guide')]"):continue
    txt=str(p.get_attribute('innerText') or p.text or '')
    if txt.strip() and _v825_text_key(txt)!=target:
     _win_physical_click_element(d,p);time.sleep(float(settings().get('blog_native_format_commit_wait_sec',0.8)));return True
   except Exception:continue
 except Exception:pass
 try:ActionChains(d).send_keys(Keys.RIGHT).perform()
 except Exception:pass
 time.sleep(float(settings().get('blog_native_format_commit_wait_sec',0.8)));return False

def _v825_native_style_probe(d,text,bg=None,release=True):
 """Read-only verification after native SmartEditor commands.

 v8.08.31 does not create a second selection just to verify style. Selection was
 the unstable operation in v8.08.25-29; after a native command, inspect the
 actual rendered text leaves only.
 """
 bg=str(bg or settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 _v828_restore_editor_context(d,timeout=8)
 e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
 if not e:return {'found':False,'bold':False,'bg':False,'text':str(text),'probe':'computed-readonly'}
 return {'found':True,'bold':bool(_bold_present(d,e)),'bg':bool(_exact_bg_present(d,e,bg)),
         'text':str(text),'probe':'computed-readonly'}

def format_yellow_bold(d,t):
 """v8.08.31: SmartEditor virtual-selection + native bold + exact #fff8b2 palette commit."""
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 e=_find_exact_body_paragraph(d,t) or find_exact(d,t)
 if e is None:raise RuntimeError('SmartEditor 실제 서식 대상 문단을 찾지 못함: '+str(t)[:80])
 _v825_native_bold(d,e,t);_v825_neutral_commit_click(d,t)
 e=_find_exact_body_paragraph(d,t) or e
 _v825_native_background(d,e,t,bg);_v825_neutral_commit_click(d,t)
 st=_v825_native_style_probe(d,t,bg,release=True)
 if not st.get('bold'):
  e=_find_exact_body_paragraph(d,t) or e;_v825_native_bold(d,e,t);_v825_neutral_commit_click(d,t)
 time.sleep(float(settings().get('blog_native_format_final_wait_sec',1.2)))
 st=_v825_native_style_probe(d,t,bg,release=True)
 if not (st.get('found') and st.get('bold') and st.get('bg')):
  raise RuntimeError('SmartEditor native 서식 commit 검증 실패: '+json.dumps(st,ensure_ascii=False)[:1200])
 log(f'SmartEditor native UI 서식 commit 완료: 굵게 + {bg} · {str(t)[:60]}')
 return True

def _image_anchor_token(index):
 """One-codepoint transient image anchor.

 Multi-character [[IMGn]] markers are unsafe in SmartEditor input_buffer because
 repeated Backspace/Delete events can be coalesced or the first event can be
 consumed while IME focus is activated.  Enclosed ideographic numerals are BMP
 codepoints (not Selenium's private-use key codes), so each anchor needs exactly
 ONE delete key after the image is already inserted.
 """
 i=int(index)
 if not 1 <= i <= 10: raise RuntimeError(f"이미지 앵커 인덱스 범위 초과: {i}")
 return chr(0x327F+i)  # ㊀ ... ㊉

def _image_anchor_tokens(post):
 n=sum(1 for b in (post.get('blocks') or []) if b.get('type') in ('image','price_compare_image'))
 return [_image_anchor_token(i) for i in range(1,n+1)]

def _find_exact_body_paragraph(d,text):
 """Return the intended BODY paragraph with SmartEditor/emoji normalization.

 v8.08.22: SmartEditor may normalize emoji variation selectors while the text
 was entered through the Windows Unicode keyboard bridge.  Example: source
 ``❤️`` (U+2764 U+FE0F) can be stored/read back as ``❤`` (U+2764).  A literal
 comparison then fails even though the visible paragraph is correct.

 Matching order:
  1) exact normalized text (whitespace + VS/zero-width ignored)
  2) unique semantic text after removing a leading emoji/symbol marker
 Never returns title/toolbar/guide paragraphs.
 """
 try:
  return d.execute_script(r"""
   const raw=String(arguments[0]||'');
   const key=s=>String(s||'').normalize('NFC')
     .replace(/[\uFE0E\uFE0F\u200B-\u200D\u2060]/g,'')
     .replace(/\s+/g,'');
   const core=s=>{
     const k=key(s);
     try{return k.replace(/^[^\p{L}\p{N}]+/u,'');}
     catch(e){return k.replace(/^[^0-9A-Za-z가-힣]+/,'');}
   };
   const needle=key(raw),needleCore=core(raw);
   const roots=[document.querySelector('.se-main-container'),document.querySelector('.se-content')].filter(Boolean);
   let ps=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('p.se-text-paragraph')]))];
   if(!ps.length)ps=[...document.querySelectorAll('p.se-text-paragraph')];
   ps=ps.filter(p=>{
     if(p.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'))return false;
     if(p.closest('.se-toolbar,.se-guide,[class*=toolbar],[class*=guide]'))return false;
     return true;
   });
   for(const p of ps){
    const t=String(p.innerText||p.textContent||'');
    if(key(t)===needle)return p;
   }
   if(needleCore){
    const hits=ps.filter(p=>core(p.innerText||p.textContent||'')===needleCore);
    if(hits.length===1)return hits[0];
   }
   return null;
  """,str(text))
 except Exception:return None

def _paragraph_snapshot(d):
 """Stable local body snapshot used for image-anchor transactions.

 This deliberately does NOT call _editor_text(): immediately after SmartEditor
 media operations the high-level text component tree can be temporarily
 unmounted even while p.se-text-paragraph nodes still exist.
 """
 try:
  return d.execute_script(r"""
   const roots=[document.querySelector('.se-main-container'),document.querySelector('.se-content')].filter(Boolean);
   let ps=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('p.se-text-paragraph')]))];
   if(!ps.length)ps=[...document.querySelectorAll('p.se-text-paragraph')];
   const clean=s=>String(s||'').replace(/\s+/g,'');
   const rows=[];
   for(const p of ps){
    if(p.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'))continue;
    if(p.closest('.se-toolbar,.se-guide,[class*=toolbar],[class*=guide]'))continue;
    let t=clean(p.innerText||p.textContent||'');
    if(t==='사진설명을입력하세요.')continue;
    rows.push({id:p.id||'',text:t});
   }
   return {ok:true,rows:rows,joined:rows.map(x=>x.text).join(''),count:rows.length};
  """) or {'ok':False,'rows':[],'joined':'','count':0}
 except Exception as ex:return {'ok':False,'rows':[],'joined':'','count':0,'error':str(ex)}

def _snapshot_without_token(snap,token):
 rows=list((snap or {}).get('rows') or []);tok=_compact_text(token)
 return ''.join(str(x.get('text') or '') for x in rows).replace(tok,'',1)

def _anchor_local_state(d,token,baseline=None):
 snap=_paragraph_snapshot(d);tok=_compact_text(token)
 joined=str(snap.get('joined') or '')
 return {'snap':snap,'token_count':joined.count(tok),'without':joined.replace(tok,'',1),'joined':joined,
         'body_same':(baseline is None or joined.replace(tok,'',1)==_snapshot_without_token(baseline,token))}

def _wait_anchor_local(d,token,baseline,want_gone,timeout=3.5):
 """Wait for a LOCAL paragraph state; tolerate temporary SmartEditor unmounts."""
 end=time.time()+max(1.0,float(timeout));good=0;samples=[]
 base_without=_snapshot_without_token(baseline,token)
 while time.time()<end:
  st=_anchor_local_state(d,token,baseline);snap=st['snap']
  if len(samples)<16:samples.append((snap.get('count',0),st['token_count'],len(st['joined'])))
  available=bool(snap.get('count'))
  ok=available and st['without']==base_without and (st['token_count']==0 if want_gone else st['token_count']==1)
  if ok:
   good+=1
   if good>=2:return {'ok':True,'samples':samples,'state':st}
  else:good=0
  time.sleep(.10)
 return {'ok':False,'samples':samples,'state':_anchor_local_state(d,token,baseline)}

def _focus_image_anchor(d,token):
 """Place caret at an intact one-character anchor WITHOUT changing article text."""
 e=_find_exact_body_paragraph(d,token)
 if not e:raise RuntimeError(f"이미지 한글자 앵커 문단을 찾지 못함: {token!r}")
 try:
  proof=d.execute_script(r"""
   const p=arguments[0],t=String(arguments[1]||'').replace(/\s+/g,'');
   const txt=String(p.innerText||p.textContent||'').replace(/\s+/g,'');
   const r=p.getBoundingClientRect();return {ok:txt===t&&r.width>0&&r.height>0,text:txt,id:p.id||'',w:r.width,h:r.height};
  """,e,token) or {}
 except Exception as ex:proof={'ok':False,'error':str(ex)}
 if not proof.get('ok'):raise RuntimeError(f"이미지 앵커 안전성 검증 실패: {token!r} · {proof}")
 # Click + HOME is read/focus-only. The marker remains intact until upload success.
 ActionChains(d).move_to_element(e).click().send_keys(Keys.HOME).perform();time.sleep(.08)
 chk=_find_exact_body_paragraph(d,token)
 if not chk:raise RuntimeError(f"이미지 앵커 포커스 중 앵커가 변형됨: {token!r}")
 return chk

def _undo_to_paragraph_snapshot(d,baseline,token,timeout=3.0):
 try:ActionChains(d).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform()
 except Exception:return False
 return bool(_wait_anchor_local(d,token,baseline,False,timeout).get('ok'))

def _cleanup_image_anchor_after_upload(d,token,baseline,expected_images):
 """Remove a ONE-character anchor only after the image has already landed.

 Each attempt performs exactly one destructive key.  No execCommand(delete),
 no Range.deleteContents, and no repeated Backspace sequence is used.
 """
 if _editor_image_count(d)!=int(expected_images):
  raise RuntimeError(f"이미지 앵커 정리 전 이미지 개수 불일치: 기대 {expected_images} / 실제 {_editor_image_count(d)}")
 # Image insertion itself may consume/replace the anchor. That's already ideal.
 pre=_wait_anchor_local(d,token,baseline,False,timeout=1.0)
 if not pre.get('ok'):
  gone=_wait_anchor_local(d,token,baseline,True,timeout=1.2)
  if gone.get('ok'):
   log(f"이미지 앵커 자동 소모 확인: {token!r} · 이미지 {expected_images}장");return True
 # baseline after image insertion should still have same article text + token.
 e=_find_exact_body_paragraph(d,token)
 if not e:
  gone=_wait_anchor_local(d,token,baseline,True,timeout=1.5)
  if gone.get('ok'):return True
  raise RuntimeError(f"이미지 삽입 후 앵커 상태를 확인하지 못함: {token!r} · {gone.get('samples')}")
 attempts=('backspace-one','delete-one','caret-backspace-one','select-one-backspace')
 traces=[]
 for mode in attempts:
  # every destructive attempt starts from the exact baseline article + one token
  if not _wait_anchor_local(d,token,baseline,False,timeout=1.2).get('ok'):
   if not _undo_to_paragraph_snapshot(d,baseline,token,2.5):
    raise RuntimeError(f"이미지 앵커 정리 시도 전 원문 복구 실패: {token!r} · mode={mode}")
  e=_find_exact_body_paragraph(d,token)
  if not e:continue
  try:
   if mode=='backspace-one':
    ActionChains(d).move_to_element(e).click().send_keys(Keys.END).send_keys(Keys.BACKSPACE).perform()
   elif mode=='delete-one':
    ActionChains(d).move_to_element(e).click().send_keys(Keys.HOME).send_keys(Keys.DELETE).perform()
   elif mode=='caret-backspace-one':
    ok=d.execute_script(r"""
     const p=arguments[0],t=String(arguments[1]||'').replace(/\s+/g,'');
     if(String(p.innerText||p.textContent||'').replace(/\s+/g,'')!==t)return false;
     const w=document.createTreeWalker(p,NodeFilter.SHOW_TEXT);let n,last=null;while(n=w.nextNode())if((n.nodeValue||'').length)last=n;
     if(!last)return false;const r=document.createRange();r.setStart(last,last.nodeValue.length);r.collapse(true);
     const s=window.getSelection();s.removeAllRanges();s.addRange(r);return s.rangeCount===1&&s.isCollapsed;
    """,e,token)
    if not ok:raise RuntimeError('collapsed caret 실패')
    ActionChains(d).send_keys(Keys.BACKSPACE).perform()
   else:
    ActionChains(d).move_to_element(e).click().send_keys(Keys.END).key_down(Keys.SHIFT).send_keys(Keys.HOME).key_up(Keys.SHIFT).send_keys(Keys.BACKSPACE).perform()
  except Exception as ex:
   traces.append((mode,'key-error',str(ex)[:120]));continue
  res=_wait_anchor_local(d,token,baseline,True,timeout=float(settings().get('blog_marker_settle_timeout_sec',3.2)))
  traces.append((mode,'gone' if res.get('ok') else 'not-gone',res.get('samples')))
  if res.get('ok'):
   if _editor_image_count(d)!=int(expected_images):raise RuntimeError('앵커 정리 중 이미지 개수 변경 감지')
   log(f"이미지 한글자 앵커 정리 성공: {token!r} · method={mode} · settle={res.get('samples')}");return True
  # unchanged means the key was consumed by input_buffer; try next route. Any
  # other local article change must be undone before another attempt.
  cur=_anchor_local_state(d,token,baseline)
  if cur['token_count']==1 and cur['body_same']:continue
  if not _undo_to_paragraph_snapshot(d,baseline,token,2.8):
   raise RuntimeError(f"이미지 앵커 주변 본문 변경 후 자동원복 실패: {token!r} · mode={mode} · traces={traces}")
 raise RuntimeError(f"이미지 한글자 앵커를 안전하게 정리하지 못함(이미지는 보존): {token!r} · traces={traces}")



def _win_send_full_body_unicode(d, plain_text):
    """Type the COMPLETE body through real Windows Unicode keyboard events.

    v8.08.20 deliberately stops using Rich Paste for article text.  The repeated
    diagnostics proved that Chrome successfully copied the whole document and
    Ctrl+V was dispatched, but SmartEditor ONE did not commit the paste into its
    document model.  Human typing, however, goes through Naver's legitimate
    ``iframe#input_buffer`` IME bridge.  This routine keeps that bridge alive,
    physically clicks the real body once, and injects UTF-16 keyboard events
    without any per-line re-click or toolbar focus churn.
    """
    if os.name != 'nt':
        return False, {'method':'windows-unicode-full-body','reason':'not-windows'}
    plain=str(plain_text or '')
    before=_compact_text(_editor_text(d))
    if before:
        raise RuntimeError(f'물리 키보드 본문 입력 시작 전 실제 본문이 비어 있지 않음: {len(before)}자')
    # Center alignment is the only global format we need before typing.  Toolbar
    # focus is immediately restored to the body and is never touched again while
    # the article is being entered.
    basefmt(d)
    try:
        target=_focus_body_end_after_toolbar(d)
    except Exception:
        _activate_body(d);target=_focus_body_end_after_toolbar(d)
    if target is None:
        return False, {'method':'windows-unicode-full-body','reason':'no-body-target'}
    try:
        clicked=_win_physical_click_element(d,target)
    except Exception:
        clicked=False
    if not clicked:
        try:
            ActionChains(d).move_to_element(target).click().perform();clicked=True
        except Exception:
            clicked=False
    if not clicked:
        return False, {'method':'windows-unicode-full-body','reason':'physical-click-failed'}
    time.sleep(.18)
    # IMPORTANT: do NOT remove/switch away from input_buffer here.  It is the
    # keyboard receiver created by SmartEditor for IME composition.
    try:
        user32=ctypes.windll.user32
        _win_foreground_chrome(d)
        ULONG_PTR=ctypes.c_size_t
        class KEYBDINPUT(ctypes.Structure):
            _fields_=[('wVk',ctypes.c_ushort),('wScan',ctypes.c_ushort),('dwFlags',ctypes.c_ulong),('time',ctypes.c_ulong),('dwExtraInfo',ULONG_PTR)]
        class INPUT_UNION(ctypes.Union):
            _fields_=[('ki',KEYBDINPUT)]
        class INPUT(ctypes.Structure):
            _anonymous_=('u',);_fields_=[('type',ctypes.c_ulong),('u',INPUT_UNION)]
        KEYEVENTF_KEYUP=0x0002;KEYEVENTF_UNICODE=0x0004;INPUT_KEYBOARD=1;VK_RETURN=0x0D
        def send_unit(unit,up=False):
            flags=KEYEVENTF_UNICODE|(KEYEVENTF_KEYUP if up else 0)
            inp=INPUT(type=INPUT_KEYBOARD,ki=KEYBDINPUT(0,int(unit),flags,0,0))
            return int(user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(INPUT)))==1
        def send_enter():
            user32.keybd_event(VK_RETURN,0,0,0);time.sleep(.018);user32.keybd_event(VK_RETURN,0,KEYEVENTF_KEYUP,0)
            return True
        delay=float(settings().get('blog_physical_unicode_char_delay_sec',0.0045))
        chunk_pause=float(settings().get('blog_physical_unicode_chunk_pause_sec',0.035))
        sent_chars=0
        # Normalize clipboard-style CRLF into logical lines; Enter is sent as a
        # real virtual key so SmartEditor creates actual paragraphs/components.
        lines=plain.replace('\r\n','\n').replace('\r','\n').split('\n')
        for li,line_text in enumerate(lines):
            raw=line_text.encode('utf-16-le','surrogatepass')
            for i in range(0,len(raw),2):
                unit=raw[i]|(raw[i+1]<<8)
                if not send_unit(unit,False) or not send_unit(unit,True):
                    return False, {'method':'windows-unicode-full-body','reason':'SendInput-failed','line':li,'char':sent_chars}
                sent_chars+=1
                if delay>0:time.sleep(delay)
                if sent_chars and sent_chars%96==0 and chunk_pause>0:time.sleep(chunk_pause)
            if li < len(lines)-1:
                send_enter();time.sleep(max(.012,delay*2))
        time.sleep(.55)
        full,now=_wait_bulk_body(d,plain,before,timeout=max(7.0,min(28.0,5.5+len(plain)/240.0)))
        if full:
            return True, {'method':'windows-unicode-full-body','chars':len(now),'sent_units':sent_chars,'target':'body','input_buffer':'kept'}
        if now!=before:
            raise RuntimeError(f'물리 키보드 본문 부분 반영 감지 — 재입력 금지 · 실제 {len(now)}자 / 기대≈{len(_compact_text(plain))}자')
        return False, {'method':'windows-unicode-full-body','reason':'zero-body-change','sent_units':sent_chars}
    except RuntimeError:
        raise
    except Exception as exc:
        return False, {'method':'windows-unicode-full-body','reason':type(exc).__name__+': '+str(exc)[:400]}


def _selenium_full_body_zero_change_fallback(d, plain_text):
    """Zero-change-only fallback: type the whole body without re-clicking per line."""
    plain=str(plain_text or '');before=_compact_text(_editor_text(d))
    if before:return False,{'method':'selenium-full-body','reason':'body-not-empty'}
    try:
        basefmt(d);_focus_body_end_after_toolbar(d)
        lines=plain.replace('\r\n','\n').replace('\r','\n').split('\n')
        for i,line_text in enumerate(lines):
            if line_text:ActionChains(d).send_keys(line_text).perform()
            if i < len(lines)-1:ActionChains(d).send_keys(Keys.ENTER).perform()
            if i and i%8==0:time.sleep(.05)
        full,now=_wait_bulk_body(d,plain,before,timeout=max(6.0,min(20.0,4.0+len(plain)/300.0)))
        if full:return True,{'method':'selenium-full-body','chars':len(now)}
        if now!=before:raise RuntimeError(f'Selenium 본문 부분 반영 감지 — 재입력 금지 · 실제 {len(now)}자')
        return False,{'method':'selenium-full-body','reason':'zero-body-change'}
    except RuntimeError:raise
    except Exception as exc:return False,{'method':'selenium-full-body','reason':type(exc).__name__+': '+str(exc)[:300]}


def _type_body_without_rich_paste(d, post):
    """v8.08.20 body transaction: real typing first, no clipboard paste loop."""
    _html_fragment,plain,slot_count=_rich_body_payload(post)
    if _compact_text(_editor_text(d)):
        raise RuntimeError('본문 물리입력 시작 전 실제 본문이 비어 있지 않습니다')
    methods=[]
    ok,diag=_win_send_full_body_unicode(d,plain)
    methods.append(diag)
    if ok:return {'method':diag.get('method'),'chars':len(_compact_text(_editor_text(d))),'slots':slot_count,'details':methods}
    # Only a proven ZERO-change may try one software-keyboard fallback.  We do
    # not fall back to Rich Paste because that exact layer has repeatedly been
    # proven to dispatch Ctrl+V without mutating SmartEditor.
    if _compact_text(_editor_text(d)):
        raise RuntimeError('물리 키보드 입력이 일부 반영되어 추가 입력을 차단했습니다')
    ok,diag2=_selenium_full_body_zero_change_fallback(d,plain)
    methods.append(diag2)
    if ok:return {'method':diag2.get('method'),'chars':len(_compact_text(_editor_text(d))),'slots':slot_count,'details':methods}
    raise RuntimeError('SmartEditor 본문 실제 키입력 2경로 모두 0자 미반영: '+repr(methods)+' · frame='+repr(getattr(d,'_nb_editor_frame_path',None)))

def build(d,post):
 """Write the entire SmartEditor body through a real keyboard transaction.

 v8.08.20 intentionally does NOT use Rich Paste.  Runtime evidence from the
 user's machine repeatedly showed a complete 1,300+ character Chrome copy and
 three successful Ctrl+V dispatches with zero article mutation.  Continuing to
 retry the same paste layer only moves the failure around.  We now keep Naver's
 legitimate input_buffer alive and type the whole prepared template in one
 continuous keyboard session; formatting and image-slot replacement happen only
 after the body text is proven present.
 """
 report=_type_body_without_rich_paste(d,post)
 setattr(d,'_nb_rich_paste_report',report)
 log('SmartEditor 본문 실제 키입력 완료 · '+repr(report))
 return report

def _editor_image_count(d):
 try:
  return int(d.execute_script("""
   const r=document.querySelector('.se-main-container')||document.querySelector('.se-content');if(!r)return 0;
   const comps=r.querySelectorAll('.se-component.se-image,[class*=se-component][class*=se-image]').length;
   if(comps)return comps;
   return r.querySelectorAll('img.se-image-resource,[class*=se-image-container] img').length;
  """) or 0)
 except Exception:return 0

def _editor_images_ready(d,expected=None):
 try:
  data=d.execute_script("""
   const r=document.querySelector('.se-main-container')||document.querySelector('.se-content');if(!r)return {count:0,unready:0};
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
 try:return d.find_elements(By.CSS_SELECTOR,"input[type='file']")
 except Exception:return []

def _click_photo_toolbar(d):
 """Open SmartEditor ONE's photo insertion UI using stable semantics first."""
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
 baseline=_paragraph_snapshot(d)
 if not baseline.get('count'):raise RuntimeError("이미지 삽입 전 본문 문단 스냅샷을 얻지 못함")
 if str(baseline.get('joined') or '').count(_compact_text(marker))!=1:
  raise RuntimeError(f"이미지 삽입 전 한글자 앵커 개수 이상: {marker!r}")
 log(f"이미지 업로드 준비: anchor={marker!r} · 기존 이미지 {before}장 · file={path.name}")
 _focus_image_anchor(d,marker)  # no text mutation before upload
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

 err=None;timeout=float(settings().get("blog_image_upload_wait_sec",30));inserted=False
 if inputs:
  for inp in reversed(inputs):
   try:
    inp.send_keys(str(path.resolve()))
    if _wait_image_inserted(d,before,timeout):inserted=True;break
    err=RuntimeError("DOM 파일 입력 후 이미지 DOM 생성 시간초과")
   except Exception as ex:
    err=ex
    if _editor_image_count(d)>before:inserted=True;break
 if not inserted:
  if not _find_open_dialog():
   _focus_image_anchor(d,marker)  # restore anchor caret before any second picker
   _click_photo_toolbar(d);time.sleep(.5)
   if not _find_open_dialog() and not _visible_file_inputs(d):_click_photo_submenu(d)
  if _find_open_dialog():
   if _native_dialog_upload(path.resolve(),4.0):
    if _wait_image_inserted(d,before,timeout):inserted=True
    else:err=RuntimeError("Windows 파일 선택 후 이미지 DOM 생성 시간초과")
  else:
   for inp in reversed(_visible_file_inputs(d)):
    try:
     inp.send_keys(str(path.resolve()))
     if _wait_image_inserted(d,before,timeout):inserted=True;break
    except Exception as ex:
     err=ex
     if _editor_image_count(d)>before:inserted=True;break
 if not inserted:
  close_file_dialogs();raise RuntimeError("사진 업로드 실패: "+(str(err) if err else "사진 버튼/파일 입력/Windows 열기 창을 모두 찾지 못함"))
 # Only now mutate the temporary anchor, using exactly one destructive key.
 expected=before+1
 _cleanup_image_anchor_after_upload(d,marker,baseline,expected)
 close_file_dialogs()
 log(f"이미지 업로드+앵커정리 완료: anchor={marker!r} · {_editor_image_count(d)}장")
 return

def validate(d,expected_images):
 bad=d.execute_script("""const r=document.querySelector('.se-main-container')||document.querySelector('.se-content');if(!r)return [];let o=[];r.querySelectorAll('*').forEach(e=>{let t=(e.innerText||'').trim();if(t&&(getComputedStyle(e).textDecorationLine||'').includes('line-through'))o.push(t.slice(0,40));});return [...new Set(o)].slice(0,10);""") or []
 if bad:raise RuntimeError("취소선 감지 "+repr(bad[:3]))
 # Do not scan page_source: React can retain removed editor text in hidden state.
 # Only visible/body paragraph state is authoritative for transient anchors.
 joined=str((_paragraph_snapshot(d) or {}).get('joined') or '')
 for i in range(1,expected_images+1):
  tok=_compact_text(_image_anchor_token(i))
  if joined.count(tok):raise RuntimeError(f"이미지 한글자 앵커 IMG{i} 잔존")
  if _compact_text(f"[[IMG{i}]]") in joined:raise RuntimeError(f"구형 이미지 마커 IMG{i} 잔존")
 count=_editor_image_count(d)
 if count!=int(expected_images):raise RuntimeError(f"최종 이미지 개수 불일치: 기대 {expected_images}장 / 실제 {count}장")

def _validate_built_once(d,post):
 """Catch exact body duplication before any photo upload can make it harder to recover."""
 text=_compact_text(_editor_text(d))
 markers=_image_anchor_tokens(post)
 for m in markers:
  if text.count(_compact_text(m))!=1:raise RuntimeError(f"본문 작성 검증 실패: {m} 개수 {text.count(_compact_text(m))}")
 chunks=[]
 for b in post.get('blocks',[]):
  if b.get('type') in ('heading','check') and b.get('text'):chunks.append(str(b['text']))
  elif b.get('type') in ('paragraph','disclosure'):chunks.extend(str(x) for x in b.get('lines',[]) if x)
 sig=_compact_text(''.join(chunks))[:120]
 if len(sig)>=40 and text.count(sig)>1:raise RuntimeError("동일 본문이 편집기에 두 번 작성된 것을 감지하여 저장 중단")
 # When a Coupang Partners sharelink exists, both edge blocks are mandatory.
 links=[str(b.get("url") or "").strip() for b in post.get("blocks",[]) if b.get("type")=="sharelink" and str(b.get("url") or "").strip()]
 for url in sorted(set(links)):
  need=links.count(url);got=text.count(_compact_text(url))
  if got<need:raise RuntimeError(f"쉐어링크 배치 검증 실패: 기대 {need}회 / 실제 {got}회")
 disclosure=_compact_text(''.join(COUPANG_DISCLOSURE_LINES))
 if text.count(disclosure)!=1:raise RuntimeError(f"경제적 이해관계 고지문 개수 오류: 기대 1회 / 실제 {text.count(disclosure)}회")
 if not text.startswith(disclosure):raise RuntimeError("경제적 이해관계 고지문이 본문 최상단이 아님")

def _scroll_tag_surface_here(d):
 """Bring bottom/publish UI into the DOM without disturbing editor text."""
 try:
  d.execute_script(r"""
   try{const sc=document.scrollingElement||document.documentElement;if(sc)sc.scrollTop=sc.scrollHeight;}catch(e){}
   const all=[...document.querySelectorAll('*')];
   for(const e of all){try{const st=getComputedStyle(e);if((st.overflowY==='auto'||st.overflowY==='scroll')&&e.scrollHeight>e.clientHeight+80)e.scrollTop=e.scrollHeight;}catch(_e){}}
  """)
 except Exception:pass
 time.sleep(.25)

def _tag_candidate_score(d,e):
 try:
  return int(d.execute_script(r"""
   const e=arguments[0];if(!e)return -999;
   const r=e.getBoundingClientRect(),s=getComputedStyle(e);
   if(s.display==='none'||s.visibility==='hidden'||r.width<2||r.height<2)return -999;
   const attrs=[e.getAttribute('placeholder'),e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('name'),e.id,e.className,e.getAttribute('data-placeholder')].filter(Boolean).join(' ');
   let score=0;if(/태그|tag/i.test(attrs))score+=18;
   if(e.tagName==='INPUT'||e.tagName==='TEXTAREA')score+=4;
   if(e.getAttribute('contenteditable')==='true')score+=2;
   if(/title|documentTitle|search|comment|댓글|검색|category|카테고리|reserve|예약|input_buffer/i.test(attrs))score-=40;
   let p=e.parentElement;
   for(let i=0;i<5&&p;i++,p=p.parentElement){const t=(p.innerText||'').trim();if(t&&/태그/.test(t)){if(i<=2&&t.length<420)score+=12;else if(t.length<900)score+=3;break;}}
   return score;
  """,e) or -999)
 except Exception:return -999

def _tag_inputs_here(d):
 """Find the tag editor across old inline UI and the 2026 publish-panel UI."""
 selectors=[
  "input[placeholder*='태그']","textarea[placeholder*='태그']","[contenteditable='true'][data-placeholder*='태그']",
  "input[aria-label*='태그']","textarea[aria-label*='태그']","[contenteditable='true'][aria-label*='태그']",
  "input[class*='tag']","textarea[class*='tag']","[class*='tag'] input","[class*='tag'] textarea","[class*='tag'][contenteditable='true']",
  ".tag_input input",".tag_input textarea"
 ]
 out=[];seen=set()
 for css in selectors:
  try:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    try:
     key=e.id
     if key in seen:continue
     if e.is_displayed() and e.is_enabled():out.append((_tag_candidate_score(d,e),e));seen.add(key)
    except Exception:pass
  except Exception:pass
 # Selector-independent fallback: current Naver builds can hash every class name.
 try:
  for e in d.find_elements(By.CSS_SELECTOR,"input,textarea,[contenteditable='true']"):
   try:
    key=e.id
    if key in seen or not (e.is_displayed() and e.is_enabled()):continue
    score=_tag_candidate_score(d,e)
    if score>=8:out.append((score,e));seen.add(key)
   except Exception:pass
 except Exception:pass
 out.sort(key=lambda x:x[0],reverse=True)
 return [e for score,e in out if score>=8]

def _tag_surface_inventory_here(d):
 try:
  return d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>1&&r.height>1&&s.display!=='none'&&s.visibility!=='hidden';};
   const info=e=>({tag:e.tagName,id:e.id||'',cls:String(e.className||'').slice(0,160),ph:e.getAttribute('placeholder')||'',aria:e.getAttribute('aria-label')||'',title:e.getAttribute('title')||'',text:(e.innerText||e.value||e.textContent||'').trim().slice(0,180)});
   return {fields:[...document.querySelectorAll('input,textarea,[contenteditable=true]')].filter(vis).map(info).slice(0,80),buttons:[...document.querySelectorAll('button,[role=button]')].filter(vis).map(info).filter(x=>/태그|발행|저장|닫기/.test(x.text+' '+x.aria+' '+x.title+' '+x.cls)).slice(0,50)};
  """) or {}
 except Exception:return {}

def _reveal_tag_input_here(d):
 _scroll_tag_surface_here(d)
 hit=False
 for xp in ["//button[contains(@aria-label,'태그') or contains(@title,'태그') or normalize-space(.)='태그']","//*[@role='button' and (contains(@aria-label,'태그') or contains(@title,'태그') or normalize-space(.)='태그')]","//button[contains(normalize-space(.),'태그')]"]:
  try:
   for b in d.find_elements(By.XPATH,xp):
    if b.is_displayed() and b.is_enabled():
     try:d.execute_script("arguments[0].click();",b)
     except Exception:b.click()
     time.sleep(.5);hit=True
     if _tag_inputs_here(d):return True
  except Exception:pass
 return hit

def _top_publish_button_here(d):
 """Return only the TOP publish button. Never return the confirm-publish button in the panel."""
 candidates=[]
 for css in ["button[class*='publish_btn']","[role='button'][class*='publish_btn']"]:
  try:
   for e in d.find_elements(By.CSS_SELECTOR,css):
    try:
     if e.is_displayed() and e.is_enabled():candidates.append(e)
    except Exception:pass
  except Exception:pass
 if not candidates:
  try:
   for e in d.find_elements(By.XPATH,"//button[normalize-space(.)='발행'] | //*[@role='button' and normalize-space(.)='발행']"):
    try:
     if e.is_displayed() and e.is_enabled():candidates.append(e)
    except Exception:pass
  except Exception:pass
 if not candidates:return None
 def top(e):
  try:return float(e.rect.get('y',999999))
  except Exception:return 999999
 candidates.sort(key=top)
 return candidates[0]

def _open_publish_tag_panel(d):
 """Naver PC 2026: publish-area tags are mounted only after the first '발행' click.

 The first click opens settings; it does NOT publish. Actual publication requires
 a second confirm action, which this draft engine never performs.
 """
 try:wait_frame(d)
 except Exception:pass
 if _tag_inputs_here(d):return True
 btn=_top_publish_button_here(d)
 if not btn:return False
 before_url=str(getattr(d,'current_url','') or '')
 try:d.execute_script("arguments[0].click();",btn)
 except Exception:btn.click()
 log("태그 복구: 상단 발행 버튼 1차 클릭 · 발행 설정 패널 열기(실제 발행 아님)")
 end=time.time()+5.0
 while time.time()<end:
  if str(getattr(d,'current_url','') or '')!=before_url and 'PostWrite' not in str(getattr(d,'current_url','')) and 'GoBlogWrite' not in str(getattr(d,'current_url','')):
   raise RuntimeError("태그 패널을 열던 중 글쓰기 URL을 이탈함 · 실제 발행 방지를 위해 즉시 중단")
  _scroll_tag_surface_here(d)
  if _tag_inputs_here(d):
   try:setattr(d,'_nb_publish_tag_panel_open',True)
   except Exception:pass
   log("태그 입력칸 확인: 발행 설정 패널")
   return True
  time.sleep(.2)
 return False

def _enter_tags_current_surface(d,wanted):
 confirmed=0
 for idx,t in enumerate(wanted,1):
  inputs=_tag_inputs_here(d)
  if not inputs:return False,confirmed
  e=inputs[0]
  try:
   e.click()
  except Exception:
   try:d.execute_script("arguments[0].focus();",e)
   except Exception:pass
  # Clear only the current text box, never existing chips.
  try:
   e.send_keys(Keys.CONTROL,'a');e.send_keys(Keys.DELETE)
  except Exception:
   try:e.clear()
   except Exception:pass
  try:e.send_keys(t);e.send_keys(Keys.ENTER)
  except Exception:
   try:ActionChains(d).click(e).send_keys(t).send_keys(Keys.ENTER).perform()
   except Exception:return False,confirmed
  time.sleep(.10)
  # React often replaces the input after Enter; reacquire on the next loop.
  try:
   inputs2=_tag_inputs_here(d);val=(inputs2[0].get_attribute('value') if inputs2 else '') or ''
  except Exception:val=''
  if not str(val).strip():confirmed+=1
  elif str(val).strip()==t:
   try:inputs2[0].send_keys(Keys.ENTER);time.sleep(.12)
   except Exception:pass
   try:val=( _tag_inputs_here(d)[0].get_attribute('value') or '' ) if _tag_inputs_here(d) else ''
   except Exception:val=''
   if not str(val).strip():confirmed+=1
  log(f"태그 입력 진행: {idx}/{len(wanted)} · {t[:35]}")
 try:setattr(d,'_nb_tags_enter_confirmed',confirmed);setattr(d,'_nb_tags_wanted',list(wanted))
 except Exception:pass
 return confirmed==len(wanted),confirmed

def tags(d,tags):
 """Enter tags through old inline UI or Naver's current publish-area tag editor."""
 wanted=[str(t).strip().lstrip('#') for t in (tags or []) if str(t).strip()]
 if not wanted:return False
 # 1) Old/compatible inline tag field in mainFrame.
 try:wait_frame(d)
 except Exception:pass
 _scroll_tag_surface_here(d)
 if not _tag_inputs_here(d):_reveal_tag_input_here(d)
 if _tag_inputs_here(d):
  ok,n=_enter_tags_current_surface(d,wanted)
  if ok:log(f"태그 입력 전송 완료: {n}개 · inline/mainFrame");return True
 # 2) Current official PC flow: first Publish click opens the settings/tag panel.
 try:
  if _open_publish_tag_panel(d):
   ok,n=_enter_tags_current_surface(d,wanted)
   if ok:log(f"태그 입력 전송 완료: {n}개 · publish-panel/mainFrame");return True
 except Exception:
  raise
 # 3) Defensive outer-document fallback for account/layout experiments.
 try:
  d.switch_to.default_content();_scroll_tag_surface_here(d)
  if not _tag_inputs_here(d):_reveal_tag_input_here(d)
  if _tag_inputs_here(d):
   ok,n=_enter_tags_current_surface(d,wanted)
   if ok:
    log(f"태그 입력 전송 완료: {n}개 · outer document")
    try:wait_frame(d)
    except Exception:pass
    return True
 except Exception:pass
 finally:
  try:wait_frame(d)
  except Exception:pass
 # Last diagnostic is intentionally compact and read-only.
 try:
  inv=_tag_surface_inventory_here(d);log("태그 입력칸 미발견 진단(mainFrame): "+json.dumps(inv,ensure_ascii=False)[:4000])
 except Exception:pass
 return False

def _close_publish_tag_panel(d):
 """Close the settings panel without clicking the confirm-publish action."""
 if not bool(getattr(d,'_nb_publish_tag_panel_open',False)):return True
 try:wait_frame(d)
 except Exception:pass
 # Explicit close/cancel controls first.
 for xp in ["//button[contains(@aria-label,'닫기') or contains(@title,'닫기')]","//*[@role='button' and (contains(@aria-label,'닫기') or contains(@title,'닫기'))]","//button[normalize-space(.)='취소']"]:
  try:
   for b in d.find_elements(By.XPATH,xp):
    if not (b.is_displayed() and b.is_enabled()):continue
    # Do not click editor-global close buttons high on the left unless they are
    # semantically tied to a visible settings layer.
    try:
     txt=' '.join([str(b.text or ''),str(b.get_attribute('aria-label') or ''),str(b.get_attribute('title') or ''),str(b.get_attribute('class') or '')])
     if '발행' in txt and '취소' not in txt:continue
    except Exception:pass
    try:d.execute_script("arguments[0].click();",b)
    except Exception:b.click()
    time.sleep(.4)
    if not _tag_inputs_here(d):
     setattr(d,'_nb_publish_tag_panel_open',False);log("태그 발행 설정 패널 닫기 완료");return True
  except Exception:pass
 # Escape is safe here: it closes a panel/suggestion, never confirms publish.
 try:
  ActionChains(d).send_keys(Keys.ESCAPE).pause(.2).send_keys(Keys.ESCAPE).perform();time.sleep(.4)
  if not _tag_inputs_here(d):
   setattr(d,'_nb_publish_tag_panel_open',False);log("태그 발행 설정 패널 ESC 닫기 완료");return True
 except Exception:pass
 # Keep it open if Naver changed close semantics. Save is still attempted by
 # direct DOM click, and there is deliberately NO second publish click.
 log("태그 발행 설정 패널 닫기 미확인 · 실제 발행 버튼 재클릭 없이 임시저장 버튼 직접 탐색")
 return False

def _save_button_meta(d,e):
 try:
  return d.execute_script(r"""
   const e=arguments[0],norm=t=>String(t||'').replace(/\s+/g,' ').trim();
   const txt=norm(e.innerText||e.textContent||''),aria=norm(e.getAttribute('aria-label')),title=norm(e.getAttribute('title')),cls=norm(e.className);
   const r=e.getBoundingClientRect();
   const labels=[...e.querySelectorAll('span,strong,em')].map(x=>norm(x.innerText||x.textContent||'')).filter(Boolean);
   const exact=[txt,aria,title,...labels].filter(x=>x==='저장'||x==='임시저장');
   const pureNum=/^\d+$/.test(txt);const countish=/count|badge|num|number|list|history/i.test(cls+' '+aria+' '+title);
   let score=-999;
   if(!pureNum){score=0;if(aria==='임시저장'||title==='임시저장')score+=130;else if(aria==='저장'||title==='저장')score+=120;
    if(txt==='임시저장')score+=120;else if(txt==='저장')score+=110;
    if(exact.length)score+=100;if(/임시\s*저장/.test(txt)&&!/^\d+$/.test(txt))score+=25;
    if(/불러오기|목록|삭제|임시저장목록|저장목록/.test(txt+' '+aria+' '+title))score-=180;
    if(countish&&!exact.length)score-=140;if(/\d/.test(txt)&&txt!=='저장'&&txt!=='임시저장')score-=20;
    if(r.top<350)score+=8;
   }
   return {text:txt,aria:aria,title:title,cls:cls.slice(0,180),score:score,x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),exact:exact.length,pureNum:pureNum,countish:countish};
  """,e) or {}
 except Exception:return {}

def _find_save_button_here(d,strict=False):
 """Return only the LABEL save control; never the numeric saved-draft list control."""
 cand=[]
 try:els=d.find_elements(By.CSS_SELECTOR,"button,[role='button'],a")
 except Exception:els=[]
 for e in els:
  try:
   if not (e.is_displayed() and e.is_enabled()):continue
   m=_save_button_meta(d,e);score=int(m.get('score',-999))
   if strict and not int(m.get('exact',0)):continue
   if score>=100:cand.append((score,e,m))
  except Exception:pass
 if not cand:return None
 cand.sort(key=lambda x:(x[0],-float(x[2].get('y',9999))),reverse=True)
 score,e,m=cand[0]
 try:setattr(d,'_nb_save_button_meta',m)
 except Exception:pass
 return e

def _find_save_button(d,strict=False):
 """Find exact temporary-save LABEL in mainFrame/outer document, excluding the number beside it."""
 # Current frame first (normal SmartEditor location).
 btn=_find_save_button_here(d,strict)
 if btn:return btn
 try:
  d.switch_to.default_content();btn=_find_save_button_here(d,strict)
  if btn:
   log('임시저장 라벨 버튼 위치: outer document');return btn
 except Exception:pass
 try:
  wait_frame(d);return _find_save_button_here(d,strict)
 except Exception:return None

def _save_button_inventory_here(d):
 try:
  out=[]
  for e in d.find_elements(By.CSS_SELECTOR,"button,[role='button'],a"):
   try:
    if e.is_displayed():
     m=_save_button_meta(d,e)
     if ('저장' in str(m.get('text','')) or '저장' in str(m.get('aria','')) or '저장' in str(m.get('title','')) or m.get('pureNum')):out.append(m)
   except Exception:pass
  return sorted(out,key=lambda x:int(x.get('score',-999)),reverse=True)[:20]
 except Exception:return []

def _draft_list_panel_open_here(d):
 try:
  return bool(d.execute_script(r"""
   const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>40&&r.height>40&&s.display!=='none'&&s.visibility!=='hidden';};
   for(const e of document.querySelectorAll('[class*=article],[class*=draft],[class*=save],[role=dialog],[class*=layer],[class*=popup]')){
    if(!vis(e))continue;const t=(e.innerText||'').trim();
    if(t.length>30&&t.includes('삭제')&&(/\d{4}\.\d{2}\.\d{2}/.test(t)||((t.match(/삭제/g)||[]).length>=1)))return true;
   } return false;
  """))
 except Exception:return False

def _draft_list_panel_open(d):
 if _draft_list_panel_open_here(d):return True
 try:
  d.switch_to.default_content();v=_draft_list_panel_open_here(d)
  try:wait_frame(d)
  except Exception:pass
  return v
 except Exception:
  try:wait_frame(d)
  except Exception:pass
  return False

def _close_draft_list_panel(d):
 """A numeric-count click only opens the list; closing it is safe and never saves/publishes."""
 # First try the current SmartEditor document, then the outer document because
 # Naver can mount the saved-draft list outside mainFrame.
 try:ActionChains(d).send_keys(Keys.ESCAPE).pause(.15).send_keys(Keys.ESCAPE).perform();time.sleep(.25)
 except Exception:pass
 if _draft_list_panel_open(d):
  try:
   d.switch_to.default_content();ActionChains(d).send_keys(Keys.ESCAPE).pause(.15).send_keys(Keys.ESCAPE).perform();time.sleep(.3)
  except Exception:pass
  try:wait_frame(d)
  except Exception:pass
 if not _draft_list_panel_open(d):
  log('저장 우측 숫자/목록 오픈 감지 · 목록만 닫고 정확한 저장 라벨 재탐색');return True
 return False

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

def draft(d,expected_images=None):
 """Exact label save + wrong-count recovery + positive completion verification.

 The numeric control immediately to the right of Naver's Save label opens the
 saved-draft list. It is NEVER a save candidate. If that list nevertheless opens,
 close only the list and re-locate a strict label control; that retry is safe
 because the first action demonstrably did not save anything.
 """
 _close_publish_tag_panel(d)
 cfg=settings();idle_timeout=float(cfg.get('blog_upload_idle_timeout_sec',35));pre_wait=max(0.0,float(cfg.get('blog_pre_draft_wait_sec',4.0)))
 idle,detail=_wait_upload_idle(d,expected_images=expected_images,timeout=idle_timeout,stable_sec=float(cfg.get('blog_pre_draft_stable_sec',2.0)))
 if not idle:raise RuntimeError("임시저장 전 이미지 업로드 완료 대기 실패: "+repr(detail))
 if pre_wait:time.sleep(pre_wait)
 verify_timeout=float(cfg.get('blog_draft_verify_timeout_sec',18));last="";wrong_list_recovered=False
 # Only explicit upload rejection may trigger a second genuine save click.
 for attempt in range(1,3):
  btn=_find_save_button(d,strict=True)
  if not btn:
   try:log("임시저장 버튼 후보 진단: "+json.dumps(_save_button_inventory_here(d),ensure_ascii=False)[:3000])
   except Exception:pass
   raise RuntimeError("정확한 임시저장/저장 라벨 버튼을 찾지 못함")
  meta=getattr(d,'_nb_save_button_meta',{}) or {}
  log("임시저장 클릭 대상 확정: "+json.dumps(meta,ensure_ascii=False))
  if meta.get('pureNum') or (meta.get('countish') and not meta.get('exact')):
   raise RuntimeError("저장 우측 숫자/목록 버튼을 저장 대상으로 탐지하여 안전 중단")
  before=_draft_count(d,btn)
  try:d.execute_script("arguments[0].scrollIntoView({block:'center'});",btn)
  except Exception:pass
  try:ActionChains(d).move_to_element(btn).pause(.12).click().perform()
  except Exception:
   try:d.execute_script("arguments[0].click();",btn)
   except Exception:btn.click()
  # Wrong target has a unique, observable result: the saved-draft ARTICLE list opens.
  time.sleep(.45)
  if _draft_list_panel_open(d):
   if wrong_list_recovered:
    raise RuntimeError("저장 라벨 클릭 후에도 임시저장 목록이 반복해서 열림 · 숫자/목록 오클릭 방지 중단")
   if not _close_draft_list_panel(d):
    raise RuntimeError("저장 우측 숫자/목록 오클릭 후 목록을 닫지 못함")
   wrong_list_recovered=True
   # This retry is not a duplicate-save risk: the first click opened the list.
   continue
  end=time.time()+verify_timeout;explicit_block=False
  while time.time()<end:
   if _page_has_visible_text(d,"업로드 중에는 일부 기능을 사용할 수 없습니다"):
    last="이미지 업로드 중 저장 차단";explicit_block=True
    idle,_=_wait_upload_idle(d,expected_images=expected_images,timeout=idle_timeout,stable_sec=2.0);break
   _click_save_confirm(d)
   success_text=_save_success_visible(d);after=_draft_count(d)
   if before is not None and after is not None and after>before:
    log(f"네이버 임시저장 확인: 저장 개수 {before}->{after}");return True
   if success_text:
    log("네이버 임시저장 확인 문구: "+success_text);return True
   # A draft-list opening during verification is also proof of wrong target.
   if _draft_list_panel_open(d):
    if not wrong_list_recovered and _close_draft_list_panel(d):
     wrong_list_recovered=True;break
    raise RuntimeError("임시저장 확인 중 저장 목록이 열림 · 저장 숫자 오클릭 감지")
   time.sleep(.25)
  if wrong_list_recovered and not explicit_block and time.time()<end:
   continue
  if explicit_block and attempt<2:
   time.sleep(1.0);continue
  if explicit_block:raise RuntimeError("임시저장 실패: 이미지 업로드 중 저장 차단이 반복됨")
  raise DraftSaveAmbiguousError("정확한 저장 라벨 클릭 후 실제 완료를 확인하지 못함: 중복 저장 방지를 위해 재클릭하지 않음")
 raise RuntimeError("임시저장 실패: "+last)

def _windows_basename(value):
 try:
  from pathlib import PureWindowsPath
  return PureWindowsPath(str(value or '')).name
 except Exception:return str(value or '').replace('\\','/').rsplit('/',1)[-1]

def _windows_parent_name(value):
 try:
  from pathlib import PureWindowsPath
  return PureWindowsPath(str(value or '')).parent.name
 except Exception:
  parts=str(value or '').replace('\\','/').split('/')
  return parts[-2] if len(parts)>1 else ''

def _local_post_candidates(product_no):
 n=int(product_no or 0);out=[]
 if n<=0:return out
 # Prefer compact/current DB artifacts, then the image-rich legacy-named folder
 # shipped inside the SAME release. Both are local and version-independent.
 for pat in (f"{n:03d}_*",f"{n:02d}_*"):
  for d in POSTS.glob(pat):
   if d.is_dir() and d not in out:out.append(d)
 return out

def _resolve_local_file(value,product_no=None,slot=None):
 """Rebase an old absolute artifact path into this extracted release."""
 if value:
  try:
   p=Path(str(value))
   if p.exists():return p.resolve()
  except Exception:pass
 base=_windows_basename(value)
 parent=_windows_parent_name(value)
 if parent and base:
  p=POSTS/parent/base
  if p.exists():return p.resolve()
 candidates=_local_post_candidates(product_no)
 if base:
  for d in candidates:
   p=d/base
   if p.exists():return p.resolve()
 # Last deterministic recovery: match the expected image slot only inside this
 # product's own local folders. Never borrow an image from another product.
 if slot:
  rx=re.compile(rf"[_-]{int(slot)}\\.(?:jpe?g|png|webp)$",re.I)
  matches=[]
  for d in candidates:
   try:matches.extend(p for p in d.iterdir() if p.is_file() and rx.search(p.name))
   except Exception:pass
  if len(matches)==1:return matches[0].resolve()
 return None

def _rebase_local_artifacts(con):
 """Repair copied DB absolute paths to the current release before eligibility.

 Earlier releases persisted C:\\...\\v7_76/v7_81 paths even though every new ZIP
 already contains the same 255 images and post.json files under ROOT/posts.
 If an older folder is moved/deleted, eligibility becomes 0 and Chrome never
 starts. Rebinding here makes each release self-contained.
 """
 rows=con.execute("SELECT * FROM products WHERE COALESCE(status,'') NOT LIKE '추천제외:%' ORDER BY product_no,id").fetchall()
 repaired=0;unresolved=[]
 for row in rows:
  updates={};n=row['product_no'] or row['id']
  # Rebind post_dir to the compact local artifact first when old absolute path is gone.
  cur=str(row['post_dir'] or '').strip()
  cur_ok=False
  if cur:
   try:cur_ok=(Path(cur)/'post.json').exists()
   except Exception:cur_ok=False
  if not cur_ok:
   local=None
   for d in _local_post_candidates(n):
    if (d/'post.json').exists() and d.name.startswith(f"{int(n):03d}_"):
     local=d.resolve();break
   if local is None:
    for d in _local_post_candidates(n):
     if (d/'post.json').exists():local=d.resolve();break
   if local is not None:updates['post_dir']=str(local)
  for slot,key in enumerate(('image1','image2','image3'),1):
   val=row[key]
   resolved=_resolve_local_file(val,n,slot)
   if resolved is not None and str(resolved)!=str(val or ''):updates[key]=str(resolved)
  cmp=row['price_compare_image'] if 'price_compare_image' in row.keys() else None
  if cmp:
   resolved=_resolve_local_file(cmp,n,None)
   if resolved is not None and str(resolved)!=str(cmp):updates['price_compare_image']=str(resolved)
  if updates:
   sets=','.join(f"{k}=?" for k in updates)
   con.execute(f"UPDATE products SET {sets} WHERE id=?",[*updates.values(),row['id']]);repaired+=1
 con.commit()
 # Read back and report only products that claim 3 photos but still cannot resolve them.
 rows=con.execute("SELECT * FROM products WHERE COALESCE(status,'') NOT LIKE '추천제외:%' ORDER BY product_no,id").fetchall()
 for row in rows:
  claimed=int(row['image_verified_count'] or 0) if 'image_verified_count' in row.keys() else 0
  if claimed>=3:
   missing=[k for k in ('image1','image2','image3') if not (row[k] and Path(row[k]).exists())]
   if missing:unresolved.append((row['product_no'] or row['id'],missing))
 log(f"블로그 로컬 경로 자동복구: DB 재연결 {repaired}건 · 3장완료 경로 미해결 {len(unresolved)}건")
 if unresolved:log("블로그 로컬 경로 미해결 TOP: "+", ".join(str(x[0]) for x in unresolved[:20]))
 return {'repaired':repaired,'unresolved':unresolved}

def _physical_images(row):
 out=[]
 for key in ("image1","image2","image3"):
  try:
   value=row[key]
   if value and Path(value).exists():out.append(str(Path(value)))
  except Exception:pass
 return out

BLOG_HISTORY_PATH=DATA/"blog_upload_history.json"

def _post_fingerprint(row,mode,blog_id=None):
 payload={"blog_id":require_target_blog_id() if blog_id is None else blog_id,"mode":mode,"title":str(row["title"] or ""),"body":str(row["body"] or ""),"tags":str(row["tags"] or "")}
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

def _dedupe_upload_rows(rows,mode):
 """Prevent the same exact article from being drafted twice across retries or repeated button clicks."""
 history=_load_blog_history();seen=set();out=[];skipped=[]
 done_status={"images_only":"임시저장완료(사진3장)","price_complete":"임시저장완료(3사가격)","text_only":"임시저장완료(텍스트)"}.get(mode,"임시저장완료(사진3장)")
 for row in rows:
  fp=_post_fingerprint(row,mode)
  if fp in seen:
   skipped.append({"id":row["id"],"name":row["name"],"reasons":["동일 원고 중복 방지(현재 실행)"]});continue
  seen.add(fp)
  if fp in history or find_published_match(row["name"],row["source_url"] or ""):
   skipped.append({"id":row["id"],"name":row["name"],"reasons":["이미 임시저장 완료된 동일 원고"]});continue
  out.append(row)
 return out,skipped,history

def _eligible_rows(con,mode,context=None):
 context=dict(context or {});where=["post_dir IS NOT NULL","status NOT LIKE '추천제외:%'","COALESCE(already_posted,0)=0"];params=[]
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
  elif tag_requirement_reason(row):reasons.append(tag_requirement_reason(row))
  if mode!="text_only":
   image_ok,image_detail=verified_blog_image_set(row,3)
   if not image_ok:reasons.append(image_detail.get("reason") or f"제품 이미지 {len(images)}/3")
  if mode=="price_complete":
   if int(row["price_verified_sites"] or 0)<3:reasons.append(f"3사 가격 {int(row['price_verified_sites'] or 0)}/3")
   if int(row["price_image_verified_sites"] or 0)<3:reasons.append(f"3사 대표이미지 {int(row['price_image_verified_sites'] or 0)}/3")
   cmp=row["price_compare_image"]
   if not cmp or not Path(cmp).exists():reasons.append("3사 가격비교 이미지 없음")
  if reasons:skipped.append({"id":row["id"],"name":row["name"],"reasons":reasons})
  else:eligible.append(row)
 return eligible,skipped

def _post_for_mode(row,mode):
 """Build the upload layout from the user's reference post structure.

 Order: disclosure exactly once -> TOP sharelink -> intro -> image1 -> section1 -> image2 -> section2 ->
 image3 -> remaining sections -> yellow advantage summary -> conclusion ->
 BOTTOM sharelink. Image slots come from reference_layout_slots when present.
 """
 pdir=Path(row["post_dir"]);post=json.loads((pdir/"post.json").read_text(encoding="utf-8"))
 # Rebuild only placement-sensitive blocks. Never trust stale image/sharelink positions.
 blocks=[dict(b) for b in (post.get("blocks") or []) if b.get("type") not in ("image","price_compare_image","sharelink")]
 blocks=normalize_disclosure_blocks(blocks)
 share=str((row["sharelink"] if "sharelink" in row.keys() else "") or post.get("sharelink") or "").strip()
 if share:blocks.insert(1,{"type":"sharelink","url":share,"position":"top_after_disclosure","source":"coupang_partners"})
 images=[] if mode=="text_only" else _physical_images(row)[:3]
 slots=list(post.get("reference_layout_slots") or ["after_intro","after_section_1","after_section_2"])[:3]
 while len(slots)<len(images):slots.append(["after_intro","after_section_1","after_section_2"][len(slots)])

 def pos_for(slot):
  if slot=="after_intro":
   idx=[i for i,b in enumerate(blocks) if b.get("type")=="paragraph" and b.get("role")=="intro"]
   return (max(idx)+1) if idx else (2 if share else 1)
  m=re.match(r"after_section_(\d+)$",str(slot or ""))
  if m:
   sec=int(m.group(1))-1
   idx=[i for i,b in enumerate(blocks) if int(b.get("section_index",-999))==sec]
   if idx:return max(idx)+1
  # fallback: directly before the advantage summary
  return next((i for i,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))

 # Insert one by one; recompute position each time so previous insertions are accounted for.
 for i,path in enumerate(images):
  slot=slots[i] if i<len(slots) else f"before_advantages_{i+1}"
  pos=min(len(blocks),max(0,pos_for(slot)))
  blocks.insert(pos,{"type":"image","file":path,"slot":slot})
 if mode=="price_complete":
  insert_at=next((i for i,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
  blocks.insert(insert_at,{"type":"price_compare_image","file":str(row["price_compare_image"] or "")})
 if share:blocks.append({"type":"sharelink","url":share,"position":"bottom","source":"coupang_partners"})
 post["blocks"]=normalize_disclosure_blocks(blocks);post["sharelink"]=share;post["reference_layout_slots"]=slots;post["blog_upload_mode"]=mode
 post["layout_policy"]="V8_04_DISCLOSURE_TOP_ONCE_REPRESENTATIVE_PLUS_TWO"
 return post

def _save_blog_failure_diagnostic(d,row,attempt,error):
 out=OUTPUTS/"blog_upload_diagnostics";out.mkdir(parents=True,exist_ok=True)
 base=f"TOP{int(row['product_no'] or row['id']):03d}_attempt{attempt}"
 shot=out/(base+".png");html=out/(base+".html")
 try:d.save_screenshot(str(shot))
 except Exception:shot=None
 try:html.write_text(d.page_source,encoding="utf-8")
 except Exception:html=None
 try:
  meta=out/(base+".json")
  state={"error":str(error),"engine_build":ENGINE_BUILD,"phase":str(getattr(d,"_nb_upload_phase","") or ""),"editor_frame_path":getattr(d,"_nb_editor_frame_path",None),
         "title":_title_text_here(d)[:500],"body_chars":len(_compact_text(_editor_text(d))),"body":_body_runtime_diagnostic(d),
         "last_toolbar_context":getattr(d,"_nb_last_toolbar_context",None),
         "last_native_selection":getattr(d,"_nb_last_native_selection",None),"editor_index_path":getattr(d,"_nb_editor_index_path",None),
         "rich_paste":getattr(d,"_nb_rich_paste_report",None),"input_buffers":_input_buffer_inventory(d),"url":str(getattr(d,"current_url","") or ""),"captured_at":time.strftime("%Y-%m-%d %H:%M:%S")}
  meta.write_text(json.dumps(state,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
 except Exception:pass
 return str(shot) if shot else "",str(html) if html else ""

def _set_exact_phase(d,top,phase):
 try:setattr(d,'_nb_upload_phase',str(phase));setattr(d,'_nb_upload_top',str(top))
 except Exception:pass
 log(f"네이버 작성 TOP{top}: 단계={phase}")

def _check_prefixed_text(text):
 """Visible check-marker rows are always advantage-style targets.

 This intentionally does not depend on the serialized block type.  Older DB
 recovery/external-import paths may preserve a row as ``paragraph`` even though
 the user sees a leading check mark in SmartEditor.
 """
 return bool(re.match(r'^[\s\u200b\ufeff]*[✔✓☑✅]',str(text or '')))


def _style_targets(post):
 """Serialized targets plus check-prefixed paragraph lines.

 v8.08.51 closes the gap where a visible ``✔ ...`` row was stored as a normal
 paragraph and therefore escaped the heading/check-only formatter.
 """
 out=[];seen=set()
 def add_target(txt,typ):
  txt=str(txt or '').strip()
  key=_v825_text_key(txt) if txt else ''
  if not txt or not key or key in seen:return
  seen.add(key);out.append({'text':txt,'type':typ})
 for b in (post.get('blocks') or []):
  typ=str(b.get('type') or '')
  if typ in ('heading','check'):
   add_target(b.get('text'),typ)
  elif typ=='paragraph':
   for line in (b.get('lines') or []):
    if _check_prefixed_text(line):add_target(line,'check-visible')
 return out


def _dom_check_style_targets(d):
 """Read ACTUAL SmartEditor body and return every visible check-mark paragraph.

 This is the final source of truth.  It catches rows that were flattened or
 rebuilt by SmartEditor and no longer map 1:1 to the serialized post block type.
 Wrapped screen lines remain one paragraph because ``innerText`` is read from the
 paragraph node itself.
 """
 try:
  rows=d.execute_script(r"""
   const roots=[document.querySelector('.se-main-container'),document.querySelector('.se-content')].filter(Boolean);
   let ps=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('p.se-text-paragraph')]))];
   if(!ps.length)ps=[...document.querySelectorAll('p.se-text-paragraph')];
   const clean=s=>String(s||'').replace(/[\u200B-\u200D\u2060\uFE0E\uFE0F]/g,'').trim();
   const out=[];
   for(const p of ps){
    if(p.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'))continue;
    if(p.closest('.se-toolbar,.se-guide,[class*=toolbar],[class*=guide]'))continue;
    let visible=true;try{const cs=getComputedStyle(p),r=p.getBoundingClientRect();visible=cs.display!=='none'&&cs.visibility!=='hidden'&&r.width>0&&r.height>0;}catch(e){}
    if(!visible)continue;
    const txt=clean(p.innerText||p.textContent||'');
    if(/^[✔✓☑✅]/u.test(txt))out.push(txt);
   }
   return out;
  """) or []
 except Exception:rows=[]
 out=[];seen=set()
 for txt in rows:
  txt=str(txt or '').strip();key=_v825_text_key(txt) if txt else ''
  if txt and key and key not in seen:
   seen.add(key);out.append({'text':txt,'type':'dom-check'})
 return out

def _style_state(d,text,bg=None):
 bg=str(bg or settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 _v828_restore_editor_context(d,timeout=8)
 e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
 if not e:return {'found':False,'bold':False,'bg':False,'text':str(text),'probe':'computed-readonly'}
 return {'found':True,'bold':bool(_bold_present(d,e)),'bg':bool(_exact_bg_present(d,e,bg)),
         'text':str(text),'probe':'computed-readonly'}

def _ensure_post_styles(d,post,phase='post-image'):
 """Apply and strictly verify bold + exact #fff8b2 on every heading/check.

 v8.08.50 deliberately does NOT alter font size.  SmartEditor keeps its normal
 default size (typically 15px).  This removes the v8.08.47~49 font-size toolbar
 commit path that caused safe-stop failures even when the article text itself
 was correctly selected.
 """
 bg=str(settings().get('blog_heading_advantage_background_hex','#fff8b2') or '#fff8b2')
 targets=_style_targets(post)
 # v8.08.51: serialized blocks are not trusted as the sole source of truth.
 # Merge every ACTUAL visible check-mark paragraph from SmartEditor itself.
 seen={_v825_text_key(x.get('text')) for x in targets if x.get('text')}
 for spec in _dom_check_style_targets(d):
  key=_v825_text_key(spec.get('text'))
  if key and key not in seen:
   targets.append(spec);seen.add(key)
 fail=[]
 for spec in targets:
  text=spec['text']
  st=_style_state(d,text,bg)
  if not st.get('bold'):
   e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
   _v825_native_bold(d,e,text);_v825_neutral_commit_click(d,text)
  st=_style_state(d,text,bg)
  if not st.get('bg'):
   e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
   _v825_native_background(d,e,text,bg);_v825_neutral_commit_click(d,text)
  # Applying background can rebuild text spans, so bold is checked one more time.
  st=_style_state(d,text,bg)
  if not st.get('bold'):
   e=_find_exact_body_paragraph(d,text) or find_exact(d,text)
   _v825_native_bold(d,e,text);_v825_neutral_commit_click(d,text)
  st=_style_state(d,text,bg)
  if not (st.get('found') and st.get('bold') and st.get('bg')):fail.append(st)
 if fail:
  raise RuntimeError(f'SmartEditor 필수 서식 최종검증 실패({phase}): '+json.dumps(fail[:4],ensure_ascii=False))
 log(f'네이버 SmartEditor 필수서식 검증 완료({phase}) · 기본 글자크기 유지 · 굵게 + {bg} · 실제 체크표시 포함 {len(targets)}개')
 return True

def _text_body_signature(post):
 """Mode-independent visible article text; image components are intentionally ignored."""
 return _compact_text(''.join(_body_expected_lines(post)))

def _write_one_post(d,r,mode):
 pdir=Path(r["post_dir"]);post=_post_for_mode(r,mode);top=r['product_no'] or r['id']
 # v8.08.26: image/text-only modes MUST use the exact same textual article.
 # Only image components may differ.  This guard prevents a future branch from
 # silently shortening/rewording the image-3 article.
 canonical_text_post=_post_for_mode(r,"text_only")
 if _text_body_signature(post)!=_text_body_signature(canonical_text_post):
  raise RuntimeError(f'모드별 본문 불일치 감지: {mode} 원고와 텍스트만 원고의 글 내용/길이가 다릅니다')
 sig=_text_body_signature(post)
 log(f"네이버 작성 TOP{top}: 동일 원고 검증 완료 · mode={mode} · visible_chars={len(sig)} · digest={hashlib.sha256(sig.encode('utf-8')).hexdigest()[:12]}")
 _set_exact_phase(d,top,'글쓰기 페이지 이동')
 try:d.maximize_window()
 except Exception:pass
 target=require_target_blog_id()
 d.get(write_url());time.sleep(2.2)
 _win_foreground_chrome(d)
 if "nid.naver.com" in d.current_url:
  raise RuntimeError("네이버 로그인이 필요합니다. 자동화 전 전용 Chrome 프로필에 로그인하세요.")
 wait_frame(d,timeout=float(settings().get('blog_editor_ready_timeout_sec',50)))
 assert_editor_target(d,target)
 cancel_existing(d);wait_frame(d,timeout=20)
 _set_exact_phase(d,top,'제목 입력')
 title(d,post["title"]);log(f"네이버 작성 TOP{top}: 제목 입력/검증 완료 · 동일 편집기 문서 유지")
 _set_exact_phase(d,top,'본문 초기화·포커스')
 clear(d);log(f"네이버 작성 TOP{top}: 실제 본문 0자 확인 · 본문 작성 시작")
 _set_exact_phase(d,top,'본문 실제 키보드 전체입력')
 try:
  build(d,post)
 except Exception:
  _clear_title_if_body_failed(d)
  raise
 _set_exact_phase(d,top,'본문 1차 검증')
 _validate_built_once(d,post);_validate_body_complete(d,post)
 log(f"네이버 작성 TOP{top}: 본문 실제 키보드 전체입력/검증 통과")

 # IMPORTANT v8.08.26: insert ALL images before native-UI styling. Image insertion is a
 # structural SmartEditor mutation and can reconstruct neighbouring text spans.
 # Formatting before this point was the reason image-3 drafts lost bold/bg while
 # text-only drafts retained them.
 imgs=[b["file"] for b in post["blocks"] if b["type"] in ("image","price_compare_image")]
 for i,f in enumerate(imgs,1):
  fp=Path(f);fp=fp if fp.is_absolute() else pdir/fp
  _set_exact_phase(d,top,f'이미지 {i}/{len(imgs)} 삽입')
  log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 이미지 {i}/{len(imgs)} 삽입 시작")
  image(d,_image_anchor_token(i),fp.resolve())
  log(f"네이버 작성 TOP{r['product_no'] or r['id']}: 이미지 {i}/{len(imgs)} 삽입 확인")
 _set_exact_phase(d,top,'이미지·본문 2차 검증')
 validate(d,len(imgs));_validate_body_complete(d,post)
 log(f"네이버 작성 TOP{top}: 이미지 {len(imgs)}장/본문 검증 통과")

 # Format only AFTER the last image component has been inserted/reconciled.
 _set_exact_phase(d,top,'이미지 삽입 후 소제목·장점 굵게+#fff8b2')
 _ensure_post_styles(d,post,'after-images')
 _validate_body_complete(d,post)

 _set_exact_phase(d,top,'태그 입력')
 log(f"네이버 작성 TOP{top}: 서식 전체검증 통과 · 태그 입력 시작")
 if not tags(d,post.get("tags",[])):raise RuntimeError("태그 입력칸을 찾지 못함")
 _validate_tags_complete(d,post.get("tags",[]));close_file_dialogs()

 _set_exact_phase(d,top,'임시저장 직전 최종검증')
 # One last idempotent style pass is intentional. SmartEditor can reconcile the
 # body once more when focus leaves the editor for the tag UI. Saving is allowed
 # only when the ACTUAL text leaves are still bold and exact #fff8b2.
 _ensure_post_styles(d,post,'pre-draft')
 _validate_body_complete(d,post);validate(d,len(imgs));_validate_tags_complete(d,post.get("tags",[]))
 log(f"네이버 작성 TOP{top}: 본문/이미지/서식/태그 최종검증 통과 · 임시저장 진행")
 _set_exact_phase(d,top,'임시저장')
 wait_frame(d,timeout=20)
 assert_editor_target(d,target)
 if not draft(d,expected_images=len(imgs)):raise RuntimeError("임시저장 확인 실패")
 _set_exact_phase(d,top,'임시저장 확인완료')
 return {"images":len(imgs),"body":True,"styles":True,"tags":True,"draft":True}

def _browser_recycle_reason(d,successes):
 """v8.08.11: normal batches never recycle Chrome between saved posts."""
 return ''

def _recycle_driver_between_posts(d,reason):
 log('네이버 Chrome 세션 안전 교체: '+reason+' · 저장 완료 후 다음 상품 전에 실행')
 try:d.quit()
 except Exception:pass
 time.sleep(.8)
 nd=start_driver()
 log('네이버 Chrome 세션 안전 교체 완료 · 단일 창/단일 탭 유지')
 return nd

def run(context=None,progress=None):
 ctx=dict(context or {});mode=str(ctx.get("mode") or settings().get("blog_default_mode","images_only"))
 target=require_target_blog_id();activate_blog_scope()
 stop_check=ctx.get("stop_check")
 if callable(stop_check) and stop_check():return {"processed":0,"stage_ok":False,"stopped":True,"message":"블로그 저장 중지"}
 if mode not in {"images_only","price_complete","text_only"}:mode="images_only"
 con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
 repair=_rebase_local_artifacts(con)
 rows,skipped=_eligible_rows(con,mode,ctx)
 rows,dedupe_skipped,history=_dedupe_upload_rows(rows,mode);skipped.extend(dedupe_skipped)
 if not rows:
  con.close();label={"images_only":"사진 3장","price_complete":"3사 가격+대표이미지","text_only":"텍스트만"}.get(mode,"사진 3장")
  unresolved=len(repair.get('unresolved') or [])
  msg=f"{label} 신규 임시저장 대상 0건 · 동일 원고/조건 미달 {len(skipped)}건"
  if unresolved:msg+=f" · 로컬 이미지 경로 미해결 {unresolved}건"
  log("네이버 Chrome 미실행: "+msg)
  pending=bool(unresolved) or any(any("이미 임시저장 완료" not in reason and "동일 원고 중복" not in reason for reason in item["reasons"]) for item in skipped)
  return {"processed":0,"stage_ok":not pending,"soft_pending":pending,"mode":mode,"skipped":skipped,"message":msg}

 cfg=settings();retry_count=max(1,int(cfg.get("blog_upload_retry_count",2)));keep_on_failure=bool(cfg.get("blog_keep_browser_open_on_failure",True))
 diagnostics=[];successes=0;failed=[];d=None;stopped=False
 try:
  d=start_driver()
  for idx,r in enumerate(rows):
   if find_published_match(r["name"],r["source_url"] or "",blog_id=target):
    skipped.append({"id":r["id"],"name":r["name"],"reasons":["이미 임시저장 완료된 동일 상품"]});continue
   if callable(stop_check) and stop_check():stopped=True;break
   if require_target_blog_id()!=target:raise RuntimeError("실행 중 대상 블로그 변경 감지")
   ok=False;last_error=""
   for attempt in range(1,retry_count+1):
    try:
     _write_one_post(d,r,mode);ok=True;break
    except Exception as e:
     last_error=f"{type(e).__name__}: {e}";log(f"네이버 임시저장 실패 TOP{r['product_no'] or r['id']} 시도 {attempt}/{retry_count}: {last_error}")
     shot,html=_save_blog_failure_diagnostic(d,r,attempt,last_error)
     diagnostics.append({"TOP":r["product_no"] or r["id"],"상품명":r["name"],"시도":attempt,"오류":last_error,"스크린샷":shot,"HTML":html})
     close_file_dialogs()
     if isinstance(e,DraftSaveAmbiguousError):
      log("임시저장 결과가 모호하여 동일 글 중복 방지를 위해 이 상품 자동 재시도 중단")
      break
     if _is_webview_dead_error(e) and attempt<retry_count:
      log("Chrome web view/session 소실 감지: 기존 세션을 종료하고 Chrome 하나만 새로 시작해 현재 상품 1회 복구")
      try:d.quit()
      except Exception:pass
      time.sleep(.8);d=start_driver();time.sleep(.5);continue
     # 일반 제목/본문/이미지 오류는 부분 작성 가능성이 있으므로 자동 재시도 금지.
     break
   if ok:
    saved_status={"images_only":"임시저장완료(사진3장)","price_complete":"임시저장완료(3사가격)","text_only":"임시저장완료(텍스트)"}.get(mode,"임시저장완료(사진3장)")
    con.execute("UPDATE products SET status=?,last_error=NULL,updated_at=datetime('now','localtime') WHERE id=?",(saved_status,r["id"]));con.commit();successes+=1
    saved_at=time.strftime("%Y-%m-%d %H:%M:%S");fp=_post_fingerprint(r,mode,blog_id=target)
    history[fp]={"blog_id":target,"product_id":r["id"],"product_no":r["product_no"],"name":r["name"],"source_url":r["source_url"] or "","mode":mode,"saved_at":saved_at}
    _save_blog_history(history)
    try:
     record_published_product(r,mode,fp,saved_at,blog_id=target)
     log(f"게시완료 상품 중복 레지스트리 기록: {r['name']}")
    except Exception as exc:log("게시완료 상품 중복 레지스트리 기록 경고: "+str(exc))
    if progress:progress(idx+1,len(rows),f"임시저장 확인완료: {r['name'][:30]}")
   else:
    failed.append({"id":r["id"],"name":r["name"],"error":last_error})
    con.execute("UPDATE products SET status='임시저장실패',last_error=?,updated_at=datetime('now','localtime') WHERE id=?",(last_error,r["id"]));con.commit()
    if progress:progress(idx+1,len(rows),f"현재 상품 미완료 · 다음 상품 이동 중단: {r['name'][:25]}")
    log("현재 상품의 본문·이미지·태그·임시저장이 모두 완료되지 않아 다음 상품으로 이동하지 않음")
    try:log("본문 실패 진단: "+json.dumps(_body_runtime_diagnostic(d),ensure_ascii=False)[:5000])
    except Exception:pass
    break

   if idx+1<len(rows):
    reason=_browser_recycle_reason(d,successes)
    if reason:
     d=_recycle_driver_between_posts(d,reason)
    else:
     log("현재 상품 완전 저장 확인 · 새 탭 생성 없이 동일 탭에서 다음 상품 진행")
 finally:
  close_file_dialogs()
  try:
   if diagnostics:
    import csv
    dp=OUTPUTS/"blog_upload_diagnostic.csv";dp.parent.mkdir(parents=True,exist_ok=True)
    with dp.open("w",encoding="utf-8-sig",newline="") as f:
     w=csv.DictWriter(f,fieldnames=["TOP","상품명","시도","오류","스크린샷","HTML"]);w.writeheader();w.writerows(diagnostics)
  except Exception as e:log("블로그 진단 CSV 저장 실패: "+str(e))
  if d is not None and not (failed and keep_on_failure):
   try:d.quit()
   except Exception:pass
  con.close()

 label={"images_only":"사진 3장 기준","price_complete":"3사 가격 비교 기준","text_only":"텍스트만 기준"}.get(mode,"사진 3장 기준")
 if stopped:return {"processed":successes,"stage_ok":False,"stopped":True,"mode":mode,"message":f"블로그 저장 중지 · {successes}건 저장 완료"}
 if failed:
  return {"processed":successes,"failed":failed,"stage_ok":False,"soft_pending":True,"mode":mode,"skipped":skipped,
          "diagnostic_csv":str(OUTPUTS/"blog_upload_diagnostic.csv"),
          "message":f"{label} 임시저장 성공 {successes}/{len(rows)} · 현재 상품 미완료 시 배치 중단 · 단일 탭 유지 · 실패 {len(failed)}건"}
 return {"processed":successes,"failed":[],"stage_ok":True,"mode":mode,"skipped":skipped,
         "message":f"{label} {successes}건 임시저장 완료 · v8.08.18 제목 wrapper UI 오판 제거 + leaf-only 제목 검증 + 전체 양식 Paste + 이미지 슬롯 교체 + 단일 탭 · 조건 미달 {len(skipped)}건 제외"}


# v7.86: body text is isolated from title/editor chrome; empty-body clear is non-destructive; input is verified with safe focus recovery.
