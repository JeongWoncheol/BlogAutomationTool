# -*- coding: utf-8 -*-
from pathlib import Path
import os,json,time,re,ctypes,sqlite3,traceback,hashlib
from .common import *
try:
 from selenium import webdriver
 from selenium.webdriver.common.by import By
 from selenium.webdriver.common.keys import Keys
 from selenium.webdriver.common.action_chains import ActionChains
 from selenium.webdriver.support.ui import WebDriverWait
 from selenium.webdriver.support import expected_conditions as EC
except Exception: webdriver=None

WRITE_URL="https://blog.naver.com/GoBlogWrite.naver"

class DraftSaveAmbiguousError(RuntimeError):
 """A save click may have been accepted but completion could not be proven. Never auto-retry this post."""
 pass

def health():
 return {"ready":webdriver is not None,"name":"네이버 자동등록","message":"Selenium SmartEditor 자동입력 준비됨" if webdriver else "selenium 미설치"}

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

def start_driver():
 opt=webdriver.ChromeOptions()
 profile=Path(os.environ.get("LOCALAPPDATA",str(ROOT)))/settings().get("chrome_profile","NaverBlogAutomationProfile")
 opt.add_argument(f"--user-data-dir={profile}");opt.add_argument("--start-maximized");opt.add_argument("--no-first-run");opt.add_argument("--no-default-browser-check")
 # Keep Chrome visible when a post fails so a SmartEditor DOM change does not
 # look like the program silently killed the browser. Successful batches still
 # call quit() explicitly.
 opt.add_experimental_option("detach",False)
 return webdriver.Chrome(options=opt)

def wait_frame(d):
 d.switch_to.default_content();WebDriverWait(d,30).until(EC.presence_of_element_located((By.ID,"mainFrame")));d.switch_to.frame(d.find_element(By.ID,"mainFrame"))

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
 e=toolbar(d,["취소선","strike"]); 
 if active(e):e.click()
 e=toolbar(d,["굵게","bold"]);
 if active(e):e.click()
 e=toolbar(d,["가운데 정렬","중앙 정렬","가운데","center"]);
 if e:
  try:e.click()
  except:pass

def _editor_text(d):
 try:
  return str(d.execute_script("""const r=document.querySelector('.se-main-container')||document.querySelector('.se-content');return r?(r.innerText||''):'';""") or '')
 except Exception:return ''

def _compact_text(text):
 return re.sub(r"\s+","",str(text or ''))

def title(d,text):
 e=WebDriverWait(d,15).until(EC.presence_of_element_located((By.CSS_SELECTOR,".se-title-text,.se-section-documentTitle")))
 ActionChains(d).click(e).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).send_keys(text).perform()
 time.sleep(.15)

def clear(d):
 """Clear body and VERIFY it is empty before writing; prevents carry-over/duplicate bodies."""
 e=WebDriverWait(d,15).until(EC.presence_of_element_located((By.CSS_SELECTOR,".se-main-container,.se-content")))
 for attempt in range(2):
  ActionChains(d).click(e).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform();time.sleep(.25)
  basefmt(d)
  if not _compact_text(_editor_text(d)):return
  # SmartEditor may keep one component selected on the first Ctrl+A/Delete.
  ActionChains(d).click(e).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform();time.sleep(.25)
 raise RuntimeError("본문 초기화 실패: 이전 글이 남아 있어 중복 작성 위험이 있으므로 중단")

def _focus_body_end_after_toolbar(d):
 """v7.64: toolbar may steal focus, so always restore article caret before typing."""
 root=WebDriverWait(d,12).until(EC.presence_of_element_located((By.CSS_SELECTOR,'.se-main-container,.se-content')))
 try:
  target=d.execute_script(r"""
   const root=arguments[0],vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
   const xs=[...root.querySelectorAll('[contenteditable=true],.se-text-paragraph')].filter(e=>vis(e)&&!e.closest('.se-documentTitle,.se-section-documentTitle,[class*=documentTitle]'));
   return xs.length?xs[xs.length-1]:root;
  """,root)
 except Exception:target=root
 try:ActionChains(d).move_to_element(target).click().perform()
 except Exception:
  try:target.click()
  except Exception:pass
 try:d.execute_script("const e=arguments[0],s=getSelection(),r=document.createRange();try{e.focus();}catch(x){}r.selectNodeContents(e);r.collapse(false);s.removeAllRanges();s.addRange(r);",target)
 except Exception:pass
 return target

def line(d,t):
 text=str(t or '');needle=_compact_text(text);before=_compact_text(_editor_text(d));cnt=before.count(needle) if needle else 0
 basefmt(d)
 target=_focus_body_end_after_toolbar(d)
 try:
  if (target.get_attribute('contenteditable') or '').lower()=='true':target.send_keys(text);target.send_keys(Keys.ENTER)
  else:ActionChains(d).send_keys(text).send_keys(Keys.ENTER).perform()
 except Exception:ActionChains(d).send_keys(text).send_keys(Keys.ENTER).perform()
 end=time.time()+3.5
 while time.time()<end:
  if not needle or _compact_text(_editor_text(d)).count(needle)>cnt:return
  time.sleep(.08)
 now=_compact_text(_editor_text(d))
 if now!=before:raise RuntimeError('본문 문장 부분 입력 감지: 저장 금지 · '+text[:70])
 basefmt(d);_focus_body_end_after_toolbar(d);ActionChains(d).send_keys(text).send_keys(Keys.ENTER).perform()
 end=time.time()+3.5
 while time.time()<end:
  if _compact_text(_editor_text(d)).count(needle)>cnt:return
  time.sleep(.08)
 raise RuntimeError('v7.64 본문 재포커스 직접입력 실패: '+text[:70])
def find_exact(d,t):
 lit=json.dumps(t)
 for xp in [f"//*[contains(@class,'se-text-paragraph') and normalize-space(.)={lit}]",f"//*[self::p or self::span or self::div][normalize-space(.)={lit}]"]:
  for e in d.find_elements(By.XPATH,xp):
   if e.is_displayed():return e
def selectline(d,e):ActionChains(d).click(e).send_keys(Keys.HOME).key_down(Keys.SHIFT).send_keys(Keys.END).key_up(Keys.SHIFT).perform()
def bold(d,t):
 e=find_exact(d,t)
 if not e:return
 selectline(d,e);s=toolbar(d,["취소선","strike"]);
 if active(s):s.click()
 b=toolbar(d,["굵게","bold"]);
 if b:b.click()
 # Explicitly collapse the selection. A highlighted heading must never survive
 # until the photo button because SmartEditor can replace selected text with an image.
 try:
  d.execute_script("""const s=window.getSelection();if(s&&s.rangeCount){s.collapseToEnd();}""")
 except Exception:ActionChains(d).send_keys(Keys.RIGHT).perform()

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
 n=0
 for b in post["blocks"]:
  typ=b.get("type")
  if typ=="disclosure":
   for x in b.get("lines") or COUPANG_DISCLOSURE_LINES:line(d,str(x))
   ActionChains(d).send_keys(Keys.ENTER).perform()
  elif typ=="sharelink":
   url=str(b.get("url") or "").strip()
   if url:
    # v7.82 compatibility extension: keep v7.59 typing mechanics while
    # preserving v7.81 top/bottom Coupang Partners link blocks.
    line(d,url);ActionChains(d).send_keys(Keys.ENTER).perform();time.sleep(.35)
  elif typ in ("image","price_compare_image"):n+=1;line(d,f"[[IMG{n}]]");ActionChains(d).send_keys(Keys.ENTER).perform()
  elif typ=="heading":line(d,b["text"]);ActionChains(d).send_keys(Keys.ENTER).perform()
  elif typ=="check":line(d,b["text"])
  elif typ=="paragraph":
   for x in b.get("lines",[]):line(d,x)
   ActionChains(d).send_keys(Keys.ENTER).perform()

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
 bad=d.execute_script("""const r=document.querySelector('.se-main-container')||document.querySelector('.se-content');if(!r)return [];let o=[];r.querySelectorAll('*').forEach(e=>{let t=(e.innerText||'').trim();if(t&&(getComputedStyle(e).textDecorationLine||'').includes('line-through'))o.push(t.slice(0,40));});return [...new Set(o)].slice(0,10);""") or []
 if bad:raise RuntimeError("취소선 감지 "+repr(bad[:3]))
 src=d.page_source
 for i in range(1,expected_images+1):
  if f"[[IMG{i}]]" in src:raise RuntimeError(f"이미지 마커 IMG{i} 잔존")
 count=_editor_image_count(d)
 if count!=int(expected_images):raise RuntimeError(f"최종 이미지 개수 불일치: 기대 {expected_images}장 / 실제 {count}장")

def _required_body_chunks(post):
 out=[]
 for b in post.get('blocks',[]):
  typ=b.get('type')
  if typ in ('heading','check') and b.get('text'):out.append(str(b['text']))
  elif typ in ('paragraph','disclosure'):out.extend(str(x) for x in b.get('lines',[]) if str(x).strip())
  elif typ=='sharelink' and b.get('url'):out.append(str(b['url']))
 return out

def _validate_built_once(d,post):
 """1st hard gate: full body + exact image markers before image upload."""
 text=_compact_text(_editor_text(d))
 markers=[f"[[IMG{i}]]" for i,b in enumerate([x for x in post.get('blocks',[]) if x.get('type') in ('image','price_compare_image')],1)]
 for m in markers:
  if text.count(_compact_text(m))!=1:raise RuntimeError(f"본문 작성 검증 실패: {m} 개수 {text.count(_compact_text(m))}")
 chunks=_required_body_chunks(post);counts={};samples={}
 for x in chunks:
  c=_compact_text(x)
  if c:counts[c]=counts.get(c,0)+1;samples.setdefault(c,x[:50])
 missing=[]
 for c,need in counts.items():
  got=text.count(c)
  if got<need:missing.append(f"{samples[c]} (필요 {need}/실제 {got})")
 if missing:raise RuntimeError('본문 작성 불완전: 저장 금지 · '+repr(missing[:5]))
 expected=sum(len(_compact_text(x)) for x in chunks)
 body=text
 for m in markers:body=body.replace(_compact_text(m),'',1)
 if expected>=80 and len(body)<int(expected*.90):raise RuntimeError(f'본문 작성량 부족: 기대 {expected} / 실제 {len(body)} · 저장 금지')
 sig=_compact_text(''.join(chunks))[:120]
 if len(sig)>=40 and text.count(sig)>1:raise RuntimeError("동일 본문이 편집기에 두 번 작성된 것을 감지하여 저장 중단")

def _validate_final_body_before_draft(d,post,expected_images):
 """2nd hard gate immediately before locating/clicking the draft button."""
 text=_compact_text(_editor_text(d));chunks=_required_body_chunks(post);counts={};samples={}
 for x in chunks:
  c=_compact_text(x)
  if c:counts[c]=counts.get(c,0)+1;samples.setdefault(c,x[:50])
 missing=[]
 for c,need in counts.items():
  got=text.count(c)
  if got<need:missing.append(f"{samples[c]} (필요 {need}/실제 {got})")
 if missing:raise RuntimeError('임시저장 직전 본문 누락/중복부족: 저장 차단 · '+repr(missing[:5]))
 expected=sum(len(_compact_text(x)) for x in chunks)
 if expected>=80 and len(text)<int(expected*.90):raise RuntimeError(f'임시저장 직전 본문 길이 부족: 기대 {expected} / 실제 {len(text)}')
 if _editor_image_count(d)!=int(expected_images):raise RuntimeError(f'임시저장 직전 이미지 개수 불일치: {_editor_image_count(d)}/{expected_images}')
 return True

def tags(d,tags):
 for css in ["input[placeholder*='태그']","input[aria-label*='태그']",".tag_input input"]:
  for e in d.find_elements(By.CSS_SELECTOR,css):
   if e.is_displayed():
    for t in tags:e.clear();e.send_keys(t);e.send_keys(Keys.ENTER)
    return True
 return False

def _find_save_button(d):
 selectors=[(By.CSS_SELECTOR,"button[class*='save_btn']"),(By.XPATH,"//button[normalize-space(.)='저장']"),(By.XPATH,"//*[@role='button' and normalize-space(.)='저장']"),(By.XPATH,"//button[contains(normalize-space(.),'임시저장')]"),(By.XPATH,"//*[@role='button' and contains(normalize-space(.),'임시저장')]")]
 for by,sel in selectors:
  try:
   for e in d.find_elements(by,sel):
    if e.is_displayed() and e.is_enabled():return e
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
    log(f"네이버 임시저장 확인: 저장 개수 {before}->{after}");return True
   if success_text:
    log("네이버 임시저장 확인 문구: "+success_text);return True
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

def _post_fingerprint(row,mode):
 payload={"mode":mode,"title":str(row["title"] or ""),"body":str(row["body"] or ""),"tags":str(row["tags"] or "")}
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
 if not bool(settings().get("blog_skip_duplicate_drafts",True)):return list(rows),skipped,history
 done_status="임시저장완료(사진3장)" if mode=="images_only" else "임시저장완료(3사가격)"
 for row in rows:
  fp=_post_fingerprint(row,mode)
  if fp in seen:
   skipped.append({"id":row["id"],"name":row["name"],"reasons":["동일 원고 중복 방지(현재 실행)"]});continue
  seen.add(fp)
  if str(row["status"] or "")==done_status or fp in history:
   skipped.append({"id":row["id"],"name":row["name"],"reasons":["이미 임시저장 완료된 동일 원고"]});continue
  out.append(row)
 return out,skipped,history

def _eligible_rows(con,mode):
 rows=con.execute("SELECT * FROM products WHERE post_dir IS NOT NULL AND status NOT LIKE '추천제외:%' ORDER BY product_no,id").fetchall()
 eligible=[];skipped=[]
 for row in rows:
  reasons=[];images=_physical_images(row)
  if not row["title"] or not row["body"] or not row["tags"]:reasons.append("원고 미완료")
  elif len([x for x in re.split(r"[,\n]+",str(row["tags"] or "")) if x.strip()])<max(20,int(settings().get("seo_min_related_tags",20))):reasons.append("관련 태그 20개 미만")
  if len(images)<3:reasons.append(f"제품 이미지 {len(images)}/3")
  if mode=="price_complete":
   if int(row["price_verified_sites"] or 0)<3:reasons.append(f"3사 가격 {int(row['price_verified_sites'] or 0)}/3")
   if int(row["price_image_verified_sites"] or 0)<3:reasons.append(f"3사 대표이미지 {int(row['price_image_verified_sites'] or 0)}/3")
   cmp=row["price_compare_image"]
   if not cmp or not Path(cmp).exists():reasons.append("3사 가격비교 이미지 없음")
  if reasons:skipped.append({"id":row["id"],"name":row["name"],"reasons":reasons})
  else:eligible.append(row)
 return eligible,skipped

def _post_for_mode(row,mode):
 pdir=Path(row["post_dir"]);post=json.loads((pdir/"post.json").read_text(encoding="utf-8"))
 blocks=[b for b in (post.get("blocks") or []) if b.get("type") not in ("image","price_compare_image")]
 blocks=normalize_disclosure_blocks(blocks)
 images=_physical_images(row)[:3]
 first_para=next((i for i,b in enumerate(blocks) if b.get("type")=="paragraph"),0)
 advantages=next((i for i,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
 positions=[0,min(len(blocks),first_para+2),min(len(blocks),advantages)];offset=0
 for i,path in enumerate(images):
  pos=min(len(blocks),positions[min(i,2)]+offset);blocks.insert(pos,{"type":"image","file":path});offset+=1
 if mode=="price_complete":
  insert_at=next((i for i,b in enumerate(blocks) if b.get("type")=="heading" and "장점 요약" in str(b.get("text") or "")),len(blocks))
  blocks.insert(insert_at,{"type":"price_compare_image","file":str(row["price_compare_image"] or "")})
 post["blocks"]=normalize_disclosure_blocks(blocks);post["blog_upload_mode"]=mode
 return post

def _save_blog_failure_diagnostic(d,row,attempt,error):
 out=OUTPUTS/"blog_upload_diagnostics";out.mkdir(parents=True,exist_ok=True)
 base=f"TOP{int(row['product_no'] or row['id']):03d}_attempt{attempt}"
 shot=out/(base+".png");html=out/(base+".html")
 try:d.save_screenshot(str(shot))
 except Exception:shot=None
 try:html.write_text(d.page_source,encoding="utf-8")
 except Exception:html=None
 return str(shot) if shot else "",str(html) if html else ""

def _write_one_post(d,r,mode):
 pdir=Path(r["post_dir"]);post=_post_for_mode(r,mode)
 d.get(WRITE_URL);time.sleep(4)
 if "nid.naver.com" in d.current_url:
  raise RuntimeError("네이버 로그인이 필요합니다. 자동화 전 전용 Chrome 프로필에 로그인하세요.")
 wait_frame(d);cancel_existing(d);wait_frame(d)
 title(d,post["title"]);clear(d);build(d,post)
 _validate_built_once(d,post)
 for b in post["blocks"]:
  if b["type"] in ("heading","check"):bold(d,b["text"])
 imgs=[b["file"] for b in post["blocks"] if b["type"] in ("image","price_compare_image")]
 for i,f in enumerate(imgs,1):
  fp=Path(f);fp=fp if fp.is_absolute() else pdir/fp
  image(d,f"[[IMG{i}]]",fp.resolve())
 validate(d,len(imgs));tags(d,post.get("tags",[]));close_file_dialogs()
 _validate_final_body_before_draft(d,post,len(imgs))
 # Saving while the red '업로드 중에는...' toast is present is forbidden.
 if not draft(d,expected_images=len(imgs)):raise RuntimeError("임시저장 확인 실패")
 return len(imgs)

def run(context=None,progress=None):
 mode=str((context or {}).get("mode") or settings().get("blog_default_mode","images_only"))
 if mode not in {"images_only","price_complete"}:mode="images_only"
 con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;rows,skipped=_eligible_rows(con,mode)
 rows,dedupe_skipped,history=_dedupe_upload_rows(rows,mode);skipped.extend(dedupe_skipped)
 if not rows:
  con.close();label="사진 3장" if mode=="images_only" else "3사 가격+대표이미지"
  return {"processed":0,"stage_ok":True,"soft_pending":False,"mode":mode,"skipped":skipped,"message":f"{label} 신규 임시저장 대상 0건 · 이미 저장된 동일 원고/조건 미달 {len(skipped)}건 건너뜀"}

 cfg=settings();retry_count=max(1,int(cfg.get("blog_upload_retry_count",2)));keep_on_failure=bool(cfg.get("blog_keep_browser_open_on_failure",True))
 diagnostics=[];successes=0;failed=[];d=None
 try:
  d=start_driver()
  for idx,r in enumerate(rows):
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
     if attempt<retry_count:
      time.sleep(1.2)
   if ok:
    saved_status="임시저장완료(사진3장)" if mode=="images_only" else "임시저장완료(3사가격)"
    con.execute("UPDATE products SET status=?,last_error=NULL,updated_at=datetime('now','localtime') WHERE id=?",(saved_status,r["id"]));con.commit();successes+=1
    fp=_post_fingerprint(r,mode);history[fp]={"product_id":r["id"],"product_no":r["product_no"],"name":r["name"],"mode":mode,"saved_at":time.strftime("%Y-%m-%d %H:%M:%S")}
    _save_blog_history(history)
    if progress:progress(idx+1,len(rows),f"임시저장 확인완료: {r['name'][:30]}")
   else:
    failed.append({"id":r["id"],"name":r["name"],"error":last_error})
    con.execute("UPDATE products SET status='임시저장실패',last_error=?,updated_at=datetime('now','localtime') WHERE id=?",(last_error,r["id"]));con.commit()
    if progress:progress(idx+1,len(rows),f"임시저장 실패 · 현재 상품에서 배치 중단: {r['name'][:25]}")
    log("작성/검증 실패이므로 다음 상품으로 이동하지 않습니다. 현재 동일 탭을 보존합니다.")
    break

   # v8.08.11: successful products also stay in the same Chrome window and
   # the exact same tab. The next iteration navigates that tab to WRITE_URL.
   if idx+1<len(rows):
    log("동일 Chrome/동일 탭 유지 → 다음 상품 글쓰기 URL로 이동")
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

 label="사진 3장 기준" if mode=="images_only" else "3사 가격 비교 기준"
 if failed:
  return {"processed":successes,"failed":failed,"stage_ok":False,"soft_pending":True,"mode":mode,"skipped":skipped,
          "diagnostic_csv":str(OUTPUTS/"blog_upload_diagnostic.csv"),
          "message":f"{label} 임시저장 성공 {successes}/{len(rows)} · 실패 {len(failed)}건은 재시도 후 진단 저장 · 실패 시 Chrome 창 유지"}
 return {"processed":successes,"failed":[],"stage_ok":True,"mode":mode,"skipped":skipped,
         "message":f"{label} {successes}건 임시저장 완료 · 조건 미달 {len(skipped)}건 제외"}
