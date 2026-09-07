# -*- coding: utf-8 -*-
import sys,os,json,sqlite3,time,threading,queue,traceback,importlib.util,shutil,csv,re,subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog
ROOT=(Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent);sys.path.insert(0,str(ROOT))
from modules.common import *
from modules import search_adapter,content_adapter,content_text_adapter,image_adapter,price_adapter,blog_adapter,video_adapter,toss_sharelink_pc,market_safe,coupang_safe,chrome_collector,coupang_partners_api,coupang_sharelink_adapter,toss_sharelink_api,naver_shopping_api,trend_collection_adapter,trend_coupang_adapter,celebrity_style_adapter,external_batch_import,already_posted_adapter,workflow_assistant,ollama_local
RUNTIME_MIGRATION=migrate_previous_install_data()
init_db()
STEPS=[
 ("search","① 인기상품 통합검색",search_adapter),
 ("content","② 제목·본문·태그",content_text_adapter),
 ("images","③ 동일상품 사진 3장",image_adapter),
 ("price","④ 3사 가격+이미지 검증",price_adapter),
 ("qa","⑤ 자동 품질검수",None),
 ("blog","⑥ 네이버 블로그 임시저장",blog_adapter)
]
class App(tk.Tk):
 def __init__(self):
  super().__init__();self.title("Naver Blog Automation Studio v8.08.52 OLLAMA HUMAN TONE")
  sw=max(1024,int(self.winfo_screenwidth() or 1600));sh=max(700,int(self.winfo_screenheight() or 900))
  ww=min(1680,max(1040,int(sw*0.92)));wh=min(1020,max(700,int(sh*0.90)))
  self.geometry(f"{ww}x{wh}+{max(0,(sw-ww)//2)}+{max(0,(sh-wh)//2)}");self.minsize(980,680)
  self.q=queue.Queue();self.worker=None;self.stop=False;self.vars={};self.pbs={}
  self.page_canvases={};self.page_canvas_windows={};self.page_scrollbars={};self._responsive_mode={}
  self.style();self.build();self.refresh();self.after(150,self.poll);self.after(600,self.health);self.after(1000,self._tick_content_live)
 def style(self):
  self.COLORS={
   "sidebar":"#17192d","sidebar2":"#24274a","accent":"#6c5ce7","accent2":"#8f63ff",
   "bg":"#f4f6fb","card":"#ffffff","text":"#20243a","muted":"#7b8194","line":"#e6e9f2",
   "success":"#19b87a","warn":"#f0a000","danger":"#ef5b64","blue":"#4c8bf5"
  }
  self.configure(bg=self.COLORS["bg"])
  s=ttk.Style(self)
  try:s.theme_use("clam")
  except:pass
  s.configure("TFrame",background=self.COLORS["bg"])
  s.configure("Card.TFrame",background=self.COLORS["card"])
  s.configure("TLabel",background=self.COLORS["bg"],foreground=self.COLORS["text"],font=("Malgun Gothic",9))
  s.configure("Card.TLabel",background=self.COLORS["card"],foreground=self.COLORS["text"],font=("Malgun Gothic",9))
  s.configure("PageTitle.TLabel",background=self.COLORS["bg"],foreground=self.COLORS["text"],font=("Malgun Gothic",17,"bold"))
  s.configure("PageSub.TLabel",background=self.COLORS["bg"],foreground=self.COLORS["muted"],font=("Malgun Gothic",9))
  s.configure("CardTitle.TLabel",background=self.COLORS["card"],foreground=self.COLORS["text"],font=("Malgun Gothic",11,"bold"))
  s.configure("Metric.TLabel",background=self.COLORS["card"],foreground=self.COLORS["accent"],font=("Malgun Gothic",20,"bold"))
  s.configure("Accent.TButton",font=("Malgun Gothic",9,"bold"),padding=(12,8),background=self.COLORS["accent"],foreground="white")
  s.map("Accent.TButton",background=[("active",self.COLORS["accent2"]),("pressed","#5748c8")])
  s.configure("Soft.TButton",font=("Malgun Gothic",9),padding=(10,7),background="#eef0f8",foreground=self.COLORS["text"])
  s.map("Soft.TButton",background=[("active","#e4e6f2")])
  s.configure("Danger.TButton",font=("Malgun Gothic",9,"bold"),padding=(10,7),background="#fff0f1",foreground=self.COLORS["danger"])
  s.configure("Treeview",rowheight=31,font=("Malgun Gothic",9),background="white",fieldbackground="white",foreground=self.COLORS["text"],borderwidth=0)
  s.configure("Treeview.Heading",font=("Malgun Gothic",9,"bold"),background="#f7f8fc",foreground="#555b70",relief="flat")
  s.map("Treeview",background=[("selected","#ebe8ff")],foreground=[("selected",self.COLORS["text"])])
  s.configure("Horizontal.TProgressbar",troughcolor="#eceef5",background=self.COLORS["accent"],bordercolor="#eceef5",lightcolor=self.COLORS["accent"],darkcolor=self.COLORS["accent"])
  s.configure("TLabelframe",background=self.COLORS["card"],bordercolor=self.COLORS["line"])
  s.configure("TLabelframe.Label",background=self.COLORS["card"],foreground=self.COLORS["text"],font=("Malgun Gothic",10,"bold"))

 def _sidebar_button(self,parent,text,key,indent=0,section=False):
  fg="#aeb3ca" if not section else "#737990"
  font=("Malgun Gothic",9,"bold") if not section else ("Malgun Gothic",8,"bold")
  if section:
   w=tk.Label(parent,text=text,anchor="w",bg=self.COLORS["sidebar"],fg=fg,font=font,padx=15+indent,pady=7)
   w.pack(fill="x");return w
  b=tk.Button(parent,text=text,anchor="w",relief="flat",bd=0,bg=self.COLORS["sidebar"],fg=fg,
              activebackground=self.COLORS["sidebar2"],activeforeground="white",font=font,
              padx=15+indent,pady=8,cursor="hand2",command=lambda:self.show_page(key))
  b.pack(fill="x");self.nav_buttons[key]=b;return b

 def _page(self,key,title,subtitle=""):
  """Create a page whose header stays visible and whose body always scrolls.

  V8.08.41 removes the old assumption that every card must fit in the current
  window height. The content width follows the viewport; overflow is vertical
  and reachable with mouse-wheel or the scrollbar on every modern/legacy page.
  """
  outer=tk.Frame(self.page_host,bg=self.COLORS["bg"])
  outer.grid(row=0,column=0,sticky="nsew")
  head=tk.Frame(outer,bg=self.COLORS["bg"]);head.pack(fill="x",padx=22,pady=(16,8))
  ttk.Label(head,text=title,style="PageTitle.TLabel").pack(anchor="w")
  if subtitle:
   sub=ttk.Label(head,text=subtitle,style="PageSub.TLabel",justify="left")
   sub.pack(anchor="w",fill="x",pady=(4,0))
   head.bind("<Configure>",lambda e,l=sub:l.configure(wraplength=max(300,e.width-6)),add="+")
  viewport=tk.Frame(outer,bg=self.COLORS["bg"]);viewport.pack(fill="both",expand=True)
  canvas=tk.Canvas(viewport,bg=self.COLORS["bg"],highlightthickness=0,bd=0)
  vbar=ttk.Scrollbar(viewport,orient="vertical",command=canvas.yview)
  canvas.configure(yscrollcommand=vbar.set)
  vbar.pack(side="right",fill="y");canvas.pack(side="left",fill="both",expand=True)
  body=tk.Frame(canvas,bg=self.COLORS["bg"])
  win=canvas.create_window((0,0),window=body,anchor="nw")
  body.pack_propagate(True)
  body.configure(padx=22,pady=0)
  def _body_cfg(_e,c=canvas):
   try:c.configure(scrollregion=c.bbox("all"))
   except:pass
  def _canvas_cfg(e,c=canvas,wid=win,b=body):
   try:
    c.itemconfigure(wid,width=max(1,e.width))
    c.configure(scrollregion=c.bbox("all"))
   except:pass
  body.bind("<Configure>",_body_cfg,add="+");canvas.bind("<Configure>",_canvas_cfg,add="+")
  self.modern_pages[key]=outer;self.page_bodies[key]=body;self.page_meta[key]=(title,subtitle)
  self.page_canvases[key]=canvas;self.page_canvas_windows[key]=win;self.page_scrollbars[key]=vbar
  return body

 def _card(self,parent,title="",subtitle="",pad=14):
  box=tk.Frame(parent,bg=self.COLORS["card"],highlightbackground=self.COLORS["line"],highlightthickness=1)
  if title:
   title_label=ttk.Label(box,text=title,style="CardTitle.TLabel",justify="left")
   title_label.pack(anchor="w",fill="x",padx=pad,pady=(pad,2))
   box.bind("<Configure>",lambda e,l=title_label,pd=pad:l.configure(wraplength=max(220,e.width-pd*2-4)),add="+")
  if subtitle:
   sub=ttk.Label(box,text=subtitle,style="Card.TLabel",foreground=self.COLORS["muted"],justify="left")
   sub.pack(anchor="w",fill="x",padx=pad,pady=(0,8))
   box.bind("<Configure>",lambda e,l=sub,pd=pad:l.configure(wraplength=max(220,e.width-pd*2-4)),add="+")
  return box

 def _is_descendant(self,widget,parent):
  try:
   w=widget
   while w is not None:
    if w==parent:return True
    name=w.winfo_parent()
    if not name:break
    w=w._nametowidget(name)
  except Exception:pass
  return False

 def _on_global_mousewheel(self,event):
  """Scroll the sidebar or current page without stealing wheel events from text/tables."""
  try:
   widget=event.widget
   # Keep native scrolling inside data/text controls.
   current_canvas=self.page_canvases.get(getattr(self,"current_page",""))
   if str(widget.winfo_class()) in {"Text","Treeview","Listbox","TCombobox","Spinbox"}:
    return None
   if str(widget.winfo_class())=="Canvas" and widget not in {current_canvas,getattr(self,"sidebar_canvas",None)}:
    return None
   if hasattr(self,"sidebar_nav_inner") and (widget==getattr(self,"sidebar_canvas",None) or self._is_descendant(widget,self.sidebar_nav_inner)):
    c=self.sidebar_canvas
   else:
    c=current_canvas
   if c is None:return None
   delta=getattr(event,"delta",0)
   if delta:
    c.yview_scroll(-1 if delta>0 else 1,"units")
   elif getattr(event,"num",None)==4:c.yview_scroll(-1,"units")
   elif getattr(event,"num",None)==5:c.yview_scroll(1,"units")
   return "break"
  except Exception:return None

 def _set_global_live(self,stage=None,detail=None,pct=None,eta=None):
  try:
   if stage is not None:self.global_stage_var.set(str(stage))
   if detail is not None:self.global_detail_var.set(str(detail))
   if pct is not None:self.global_live_pb["value"]=max(0,min(100,int(float(pct))))
   if eta is not None:self.global_eta_var.set(str(eta))
  except Exception:pass

 def _layout_collect_page(self,width):
  """Reflow the collection hub at narrow widths instead of clipping cards."""
  try:w=max(1,int(width or 0))
  except Exception:return
  if not hasattr(self,"collect_dual"):return
  mode="wide" if w>=1200 else ("medium" if w>=760 else "narrow")
  if self._responsive_mode.get("collect")==mode:return
  self._responsive_mode["collect"]=mode
  dual,left,right=self.collect_dual
  left.grid_forget();right.grid_forget()
  for c in range(2):dual.grid_columnconfigure(c,weight=0)
  if mode=="wide":
   dual.grid_columnconfigure(0,weight=1);dual.grid_columnconfigure(1,weight=1)
   left.grid(row=0,column=0,sticky="nsew",padx=(0,6),pady=0);right.grid(row=0,column=1,sticky="nsew",padx=(6,0),pady=0)
  else:
   dual.grid_columnconfigure(0,weight=1)
   left.grid(row=0,column=0,sticky="ew",pady=(0,8));right.grid(row=1,column=0,sticky="ew",pady=(0,0))
  # Real-time metrics: 8 across on wide, 4x2 on medium, 2x4 on narrow.
  cols=8 if mode=="wide" else (4 if mode=="medium" else 2)
  mg=self.collect_live_metrics_frame
  for c in range(8):mg.grid_columnconfigure(c,weight=0)
  for c in range(cols):mg.grid_columnconfigure(c,weight=1)
  for i,cell in enumerate(self.collect_live_metric_cells):
   cell.grid_forget();cell.grid(row=i//cols,column=i%cols,sticky="nsew",padx=2,pady=2)
  # Pipeline cards: 3, 2 or 1 columns.
  stepcols=3 if mode=="wide" else (2 if mode=="medium" else 1)
  sf=self.collect_steps_frame
  for c in range(3):sf.grid_columnconfigure(c,weight=0)
  for c in range(stepcols):sf.grid_columnconfigure(c,weight=1)
  for i,box in enumerate(self.collect_step_boxes):
   box.grid_forget();box.grid(row=i//stepcols,column=i%stepcols,sticky="nsew",padx=4,pady=4)
  # Trend action buttons are stacked only on narrow windows.
  if hasattr(self,"collect_trend_buttons"):
   for b in self.collect_trend_buttons:b.grid_forget()
   if mode=="narrow":
    for i,b in enumerate(self.collect_trend_buttons):b.grid(row=i,column=0,sticky="ew",pady=2)
    self.collect_trend_button_frame.grid_columnconfigure(0,weight=1)
   else:
    for i,b in enumerate(self.collect_trend_buttons):
     self.collect_trend_button_frame.grid_columnconfigure(i,weight=1);b.grid(row=0,column=i,sticky="ew",padx=3)
  try:
   self.collect_stage_flow_label.configure(wraplength=max(260,w-260))
   self.content_live_preview_label.configure(wraplength=max(260,w-72))
  except Exception:pass

 def show_page(self,key):
  if key not in self.modern_pages:return
  self.modern_pages[key].tkraise();self.current_page=key
  for k,b in self.nav_buttons.items():
   try:b.configure(bg=self.COLORS["sidebar2"] if k==key else self.COLORS["sidebar"],fg="white" if k==key else "#aeb3ca")
   except:pass
  try:self.refresh_modern_overview()
  except:pass

 def build(self):
  self.modern_pages={};self.page_bodies={};self.page_meta={};self.nav_buttons={};self.current_page="overview"
  shell=tk.Frame(self,bg=self.COLORS["bg"]);shell.pack(fill="both",expand=True)
  sidebar=tk.Frame(shell,bg=self.COLORS["sidebar"],width=220);sidebar.pack(side="left",fill="y");sidebar.pack_propagate(False)
  brand=tk.Frame(sidebar,bg=self.COLORS["sidebar"]);brand.pack(fill="x",pady=(16,8))
  tk.Label(brand,text="NBlog Studio",bg=self.COLORS["sidebar"],fg="white",font=("Malgun Gothic",12,"bold"),anchor="w").pack(fill="x",padx=15)
  tk.Label(brand,text="CONTENT AUTOMATION",bg=self.COLORS["sidebar"],fg="#6f7690",font=("Malgun Gothic",7),anchor="w").pack(fill="x",padx=15,pady=(1,0))
  nav_view=tk.Frame(sidebar,bg=self.COLORS["sidebar"]);nav_view.pack(fill="both",expand=True)
  self.sidebar_canvas=tk.Canvas(nav_view,bg=self.COLORS["sidebar"],highlightthickness=0,bd=0,width=204)
  side_scroll=ttk.Scrollbar(nav_view,orient="vertical",command=self.sidebar_canvas.yview);self.sidebar_canvas.configure(yscrollcommand=side_scroll.set)
  side_scroll.pack(side="right",fill="y");self.sidebar_canvas.pack(side="left",fill="both",expand=True)
  self.sidebar_nav_inner=tk.Frame(self.sidebar_canvas,bg=self.COLORS["sidebar"]);side_win=self.sidebar_canvas.create_window((0,0),window=self.sidebar_nav_inner,anchor="nw")
  self.sidebar_nav_inner.bind("<Configure>",lambda e:self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")),add="+")
  self.sidebar_canvas.bind("<Configure>",lambda e:self.sidebar_canvas.itemconfigure(side_win,width=max(1,e.width)),add="+")
  nav=self.sidebar_nav_inner
  self._sidebar_button(nav,"◈  대시보드","overview")
  self._sidebar_button(nav,"●  계정 · 연결","account")
  self._sidebar_button(nav,"✦  AI 설정","ai")
  self._sidebar_button(nav,"◇  카테고리 & 키워드","categories")
  self._sidebar_button(nav,"수집","",section=True)
  self._sidebar_button(nav,"◎  수집 센터","collect_run",indent=10)
  self._sidebar_button(nav,"▦  수집 결과 · 상품","collected",indent=10)
  self._sidebar_button(nav,"★  연예인 착장 트렌드","celebrity_style",indent=10)
  self._sidebar_button(nav,"작성","",section=True)
  self._sidebar_button(nav,"⚙  작성 설정","write_settings",indent=10)
  self._sidebar_button(nav,"▤  작성물 관리","drafts",indent=10)
  self._sidebar_button(nav,"◉  페르소나","persona",indent=10)
  self._sidebar_button(nav,"▧  템플릿","template",indent=10)
  self._sidebar_button(nav,"⚑  광고 고지","disclosure",indent=10)
  self._sidebar_button(nav,"✣  테스트 작성","test_write",indent=10)
  self._sidebar_button(nav,"영상","",section=True)
  self._sidebar_button(nav,"🎬  Ollama 영상 기획 · 생성","video",indent=10)
  self._sidebar_button(nav,"🚀  발행 · 임시저장","publish")
  self._sidebar_button(nav,"⌘  고급 도구 · 전체 설정","advanced")
  self._sidebar_button(nav,"⌁  라이선스 · 버전","license")
  tk.Label(sidebar,text="v8.08.52 · Ollama 자연대화체 · 체크문장 서식 안정화",bg=self.COLORS["sidebar"],fg="#5b617d",font=("Malgun Gothic",7),anchor="w").pack(side="bottom",fill="x",padx=15,pady=8)

  right=tk.Frame(shell,bg=self.COLORS["bg"]);right.pack(side="left",fill="both",expand=True)
  top=tk.Frame(right,bg="white",height=54,highlightbackground=self.COLORS["line"],highlightthickness=1);top.pack(fill="x");top.pack_propagate(False)
  tk.Label(top,text="네이버 블로그 자동화 운영 콘솔",bg="white",fg=self.COLORS["text"],font=("Malgun Gothic",10,"bold")).pack(side="left",padx=22)
  self.badge=tk.Label(top,text="시스템 점검 중",bg="#eef7ff",fg=self.COLORS["blue"],font=("Malgun Gothic",8,"bold"),padx=10,pady=5)
  self.badge.pack(side="right",padx=18,pady=12)
  # Always-visible compact run monitor. This remains on screen even when a long page is scrolled.
  livebar=tk.Frame(right,bg="#fbfbfe",highlightbackground=self.COLORS["line"],highlightthickness=1);livebar.pack(fill="x")
  self.global_stage_var=tk.StringVar(value="대기")
  self.global_detail_var=tk.StringVar(value="실행할 작업을 선택하세요.")
  self.global_eta_var=tk.StringVar(value="ETA -")
  tk.Label(livebar,textvariable=self.global_stage_var,bg="#fbfbfe",fg=self.COLORS["accent"],font=("Malgun Gothic",8,"bold"),width=18,anchor="w").pack(side="left",padx=(18,8),pady=5)
  self.global_live_pb=ttk.Progressbar(livebar,maximum=100,length=150);self.global_live_pb.pack(side="left",padx=(0,8),pady=8)
  tk.Label(livebar,textvariable=self.global_detail_var,bg="#fbfbfe",fg=self.COLORS["text"],font=("Malgun Gothic",8),anchor="w").pack(side="left",fill="x",expand=True,padx=(0,8),pady=5)
  tk.Label(livebar,textvariable=self.global_eta_var,bg="#fbfbfe",fg=self.COLORS["muted"],font=("Malgun Gothic",8,"bold"),anchor="e").pack(side="right",padx=(8,18),pady=5)
  self.page_host=tk.Frame(right,bg=self.COLORS["bg"]);self.page_host.pack(fill="both",expand=True);self.page_host.grid_rowconfigure(0,weight=1);self.page_host.grid_columnconfigure(0,weight=1)
  self.bind_all("<MouseWheel>",self._on_global_mousewheel,add="+");self.bind_all("<Button-4>",self._on_global_mousewheel,add="+");self.bind_all("<Button-5>",self._on_global_mousewheel,add="+")

  # Modern top-level pages
  self._build_overview_page(self._page("overview","대시보드","오늘의 수집·작성·이미지·임시저장 상태를 한눈에 확인합니다."))
  self._build_account_page(self._page("account","계정 · 연결","네이버 블로그, Chrome, 쿠팡/네이버/토스 API 연결 상태를 관리합니다."))
  self._build_ai_page(self._page("ai","AI 설정","Ollama Qwen3 무료 로컬 AI를 1순위로 사용해 제목·본문·태그를 다양하게 생성합니다."))
  self._build_categories_page(self._page("categories","카테고리 & 키워드","고정 카테고리, 트렌드 수집과 키워드 흐름을 확인합니다."))
  self._build_collect_settings_page(self._page("collect_settings","수집 · 설정","3사 상품 수집 및 동일상품 이미지 수집 정책을 한곳에서 확인합니다."))
  self._build_collect_run_page(self._page("collect_run","수집 센터","쿠팡·토스·네이버 3사 수집과 아이템스카우트·네이버 데이터랩 트렌드 수집을 한 화면에서 실행하고 진행률을 확인합니다."))
  self._build_celebrity_style_page(self._page("celebrity_style","연예인 착장 트렌드","최근 뉴스·블로그·Google 공개 자료를 교차검증해 연예인 착장 후보를 찾고, Ollama/Qwen3-VL 보조 분석 후 정확상품·추정·유사스타일을 구분해 원고를 만듭니다."))
  self._build_write_settings_page(self._page("write_settings","작성 · 설정","Ollama 무료 AI 원고 생성, 이미지 3장, SEO 품질검수 흐름을 관리합니다."))
  self._build_persona_page(self._page("persona","작성 · 페르소나","AI가 상품마다 다른 관점과 소비자 중심 표현을 사용하도록 작성 전략을 확인합니다."))
  self._build_disclosure_page(self._page("disclosure","작성 · 광고 고지","경제적 이해관계 고지문과 제휴링크 정책을 확인합니다."))
  self._build_test_write_page(self._page("test_write","작성 · 테스트","실제 배치 전에 원고·이미지·SmartEditor 저장환경을 빠르게 점검합니다."))
  self._build_publish_page(self._page("publish","발행 · 임시저장","이미지 3장/텍스트 전용 임시저장과 최근 상태를 한눈에 관리합니다."))
  self._build_license_page(self._page("license","라이선스 · 버전","현재 프로그램 버전과 핵심 기능 구성을 확인합니다."))

  # Existing functional pages, now mounted into the modern shell.
  self.tabs={}
  legacy_map=[
   ("상품/진행현황","collected","수집된 상품","TOP100·3사 원천상품·외부 원고·기존 게시 제외 상태를 관리합니다."),
   ("추가 트렌드 수집","trend","추가 트렌드 수집","아이템스카우트/네이버 데이터랩 트렌드를 수집합니다."),
   ("트렌드→쿠팡 추출","trend_products","트렌드 → 쿠팡 추출","트렌드 키워드에서 쿠팡 인기상품을 API 우선으로 추출합니다."),
   ("결과 미리보기","drafts","작성물 관리","선택 상품의 제목·본문·태그·이미지·가격 결과를 확인합니다."),
   ("이미지·가격 검증","verify","이미지 · 가격 검증","동일상품 이미지 3장과 3사 가격 증거를 검증합니다."),
   ("AI 제품영상","video","AI 제품영상","Ollama로 영상 콘셉트·훅·CTA·12컷을 기획하고 ComfyUI로 제품영상을 생성합니다."),
   ("성능/최적화","performance","성능 · 최적화","성능 설정과 PERF 로그를 확인합니다."),
   ("블로그 양식","template","작성 · 템플릿","모바일 블로그 기본 양식을 편집합니다."),
   ("문제 해결","diagnostics","문제 해결","수집·API·Chrome·SmartEditor 문제를 진단하고 복구합니다."),
   ("실행 로그","logs","실행 로그","최근 실행 로그를 확인합니다."),
   ("설정/선택기능","advanced","전체 설정","세부 JSON 설정과 선택 기능을 관리합니다.")]
  for old,key,title,sub in legacy_map:self.tabs[old]=self._page(key,title,sub)
  self.dashboard();self.trend_tab();self.trend_product_tab();self.preview();self.verify_tab();self.video_tab();self.performance_tab();self.template();self.trouble();self.logs();self.settings_tab()
  self.show_page("overview")

 def _build_overview_page(self,p):
  grid=tk.Frame(p,bg=self.COLORS["bg"]);grid.pack(fill="x")
  for i in range(5):grid.grid_columnconfigure(i,weight=1)
  metrics=[("전체 상품","overview_total","0"),("원고 준비","overview_content","0"),("사진 3장 완료","overview_images","0"),("임시저장 준비","overview_ready","0"),("기존 게시 제외","overview_posted","0")]
  self.overview_vars={};self.overview_metric_cards=[]
  for i,(label,key,default) in enumerate(metrics):
   c=self._card(grid);c.grid(row=0,column=i,sticky="nsew",padx=4,pady=4);self.overview_metric_cards.append(c)
   ttk.Label(c,text=label,style="Card.TLabel",foreground=self.COLORS["muted"]).pack(anchor="w",padx=14,pady=(14,3))
   v=tk.StringVar(value=default);self.overview_vars[key]=v;ttk.Label(c,textvariable=v,style="Metric.TLabel").pack(anchor="w",padx=14)
   ttk.Label(c,text="건",style="Card.TLabel",foreground=self.COLORS["muted"]).pack(anchor="w",padx=14,pady=(0,14))
  lower=tk.Frame(p,bg=self.COLORS["bg"]);lower.pack(fill="both",expand=True,pady=(12,0));lower.grid_columnconfigure(0,weight=2);lower.grid_columnconfigure(1,weight=1);lower.grid_rowconfigure(0,weight=1)
  recent=self._card(lower,"최근 상품 상태","수집→원고→이미지→검증→임시저장 진행 상태");recent.grid(row=0,column=0,sticky="nsew",padx=(0,6))
  self.overview_tree=ttk.Treeview(recent,columns=("no","name","status","img"),show="headings",height=9)
  for c,h,w in [("no","TOP",55),("name","상품명",390),("status","상태",150),("img","사진",70)]:self.overview_tree.heading(c,text=h);self.overview_tree.column(c,width=w,anchor="w")
  self.overview_tree.pack(fill="both",expand=True,padx=14,pady=(4,14))
  quick=self._card(lower,"빠른 실행","현재 상태에서 자주 쓰는 작업을 바로 실행합니다.");quick.grid(row=0,column=1,sticky="nsew",padx=(6,0))
  self.overview_layout=(grid,lower,recent,quick)
  ttk.Button(quick,text="▶ 검색부터 임시저장까지 전체 실행",style="Accent.TButton",command=self.runall).pack(fill="x",padx=14,pady=(8,5))
  ttk.Button(quick,text="Ollama 제목·본문·태그 생성",style="Soft.TButton",command=lambda:self.single("content")).pack(fill="x",padx=14,pady=4)
  ttk.Button(quick,text="동일상품 사진 3장",style="Soft.TButton",command=lambda:self.single("images")).pack(fill="x",padx=14,pady=4)
  ttk.Button(quick,text="네이버 저장환경 사전점검",style="Soft.TButton",command=self.blog_preflight).pack(fill="x",padx=14,pady=4)
  ttk.Button(quick,text="🩺 문제점 검토·자동복구",style="Soft.TButton",command=self.repair).pack(fill="x",padx=14,pady=4)
  ttk.Button(quick,text="■ 실행 중지",style="Danger.TButton",command=lambda:setattr(self,"stop",True)).pack(fill="x",padx=14,pady=(4,14))
  def _overview_reflow(e):
   w=max(1,int(e.width));cols=5 if w>=1150 else (3 if w>=760 else 2)
   mode=f"{cols}"
   if self._responsive_mode.get("overview")==mode:return
   self._responsive_mode["overview"]=mode
   for col in range(5):grid.grid_columnconfigure(col,weight=0)
   for col in range(cols):grid.grid_columnconfigure(col,weight=1)
   for i,card in enumerate(self.overview_metric_cards):card.grid_forget();card.grid(row=i//cols,column=i%cols,sticky="nsew",padx=4,pady=4)
   recent.grid_forget();quick.grid_forget()
   if w>=900:
    lower.grid_columnconfigure(0,weight=2);lower.grid_columnconfigure(1,weight=1)
    recent.grid(row=0,column=0,sticky="nsew",padx=(0,6));quick.grid(row=0,column=1,sticky="nsew",padx=(6,0))
   else:
    lower.grid_columnconfigure(0,weight=1);lower.grid_columnconfigure(1,weight=0)
    recent.grid(row=0,column=0,sticky="nsew",pady=(0,8));quick.grid(row=1,column=0,sticky="ew")
  p.bind("<Configure>",_overview_reflow,add="+")

 def _build_account_page(self,p):
  c=self._card(p,"연결 상태","새 버전은 이전 설치의 API/Chrome 연결 설정을 자동 승계합니다.");c.pack(fill="x")
  row=tk.Frame(c,bg="white");row.pack(fill="x",padx=14,pady=(6,14))
  for i in range(4):row.grid_columnconfigure(i,weight=1)
  ttk.Button(row,text="네이버 저장환경 점검",style="Accent.TButton",command=self.blog_preflight).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(row,text="Chrome 확장 설치/갱신",style="Soft.TButton",command=self.chrome_extension_setup).grid(row=0,column=1,sticky="ew",padx=4)
  ttk.Button(row,text="3사 검색 연결 테스트",style="Soft.TButton",command=self.market_smoke_test).grid(row=0,column=2,sticky="ew",padx=4)
  ttk.Button(row,text="문제 해결 열기",style="Soft.TButton",command=lambda:self.show_page("diagnostics")).grid(row=0,column=3,sticky="ew",padx=(4,0))
  api=self._card(p,"API 연결","쿠팡 Partners / 네이버 / 토스 연결을 설정하고 테스트합니다.");api.pack(fill="x",pady=(12,0))
  r=tk.Frame(api,bg="white");r.pack(fill="x",padx=14,pady=(6,14))
  buttons=[("쿠팡 API 설정",self.coupang_api_setup),("쿠팡 API 테스트",self.coupang_api_test),("네이버 API 설정",self.naver_api_setup),("네이버 API 테스트",self.naver_api_test),("토스 API 설정",self.toss_api_setup),("토스 API 테스트",self.toss_api_test)]
  for i,(t,cmd) in enumerate(buttons):ttk.Button(r,text=t,style="Soft.TButton",command=cmd).grid(row=i//3,column=i%3,sticky="ew",padx=4,pady=4);r.grid_columnconfigure(i%3,weight=1)

 def _build_ai_page(self,p):
  c=self._card(p,"Ollama 무료 로컬 AI 우선","Ollama Qwen3 → 안전원고 순서가 기본입니다. OpenAI 자동사용은 OFF라 API 비용이 발생하지 않습니다.");c.pack(fill="x")
  cfg=settings();profile=str(cfg.get("ollama_generation_profile") or "balanced")
  profile_labels={"speed":"초고속 · 4B 중심","balanced":"빠른 균형 · 8B 권장","quality":"고품질 · 14B/30B"}
  self.ollama_profile_var=tk.StringVar(value=profile_labels.get(profile,"빠른 균형 · 8B 권장"))
  profile_row=tk.Frame(c,bg="white");profile_row.pack(fill="x",padx=14,pady=(6,6));profile_row.grid_columnconfigure(1,weight=1)
  tk.Label(profile_row,text="원고 생성 속도",bg="white",fg=self.COLORS["text"],font=("Malgun Gothic",9,"bold")).grid(row=0,column=0,sticky="w",padx=(0,10))
  self.ollama_profile_combo=ttk.Combobox(profile_row,textvariable=self.ollama_profile_var,state="readonly",values=list(profile_labels.values()),width=28)
  self.ollama_profile_combo.grid(row=0,column=1,sticky="w")
  ttk.Button(profile_row,text="프로필 적용",style="Soft.TButton",command=self.apply_ollama_profile).grid(row=0,column=2,padx=(8,0))
  self.ollama_profile_status=tk.StringVar(value=f"현재 {cfg.get('ollama_model','qwen3:8b')} · ctx {cfg.get('ollama_num_ctx',12288):,} · 재작성 최대 {cfg.get('content_diversity_retry_count',2)}회")
  ttk.Label(c,textvariable=self.ollama_profile_status,style="Card.TLabel",foreground=self.COLORS["accent"]).pack(anchor="w",padx=14,pady=(0,6))
  r=tk.Frame(c,bg="white");r.pack(fill="x",padx=14,pady=(4,10));r.grid_columnconfigure(0,weight=1);r.grid_columnconfigure(1,weight=1)
  ttk.Button(r,text="Ollama 모델 확인·자동설치",style="Accent.TButton",command=self.ollama_auto_setup).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(r,text="Ollama 연결 테스트",style="Soft.TButton",command=self.ollama_ai_test).grid(row=0,column=1,sticky="ew",padx=(4,0))
  note=tk.Label(c,text="권장값은 Qwen3 8B + 12K context입니다. RAM만 많고 GPU가 부족한 PC에서 14B/30B가 자동 선택되어 느려지는 문제를 막도록 GPU VRAM 기준으로 모델을 고릅니다.",bg="white",fg=self.COLORS["muted"],font=("Malgun Gothic",9),anchor="w",justify="left")
  note.pack(fill="x",padx=14,pady=(0,12))
  gen=self._card(p,"AI 작성 실행","실시간으로 현재 상품·생성 문자수·경과시간·속도·남은 예상시간을 수집 센터에서 표시합니다.");gen.pack(fill="x",pady=(12,0))
  rr=tk.Frame(gen,bg="white");rr.pack(fill="x",padx=14,pady=(6,14));rr.grid_columnconfigure(0,weight=1);rr.grid_columnconfigure(1,weight=1)
  ttk.Button(rr,text="Ollama 신규/미완료 원고 생성",style="Accent.TButton",command=lambda:self.single("content")).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(rr,text="기존 원고 포함 전체 재생성",style="Soft.TButton",command=self.content_force_regenerate).grid(row=0,column=1,sticky="ew",padx=(4,0))

 def _build_categories_page(self,p):
  c=self._card(p,"기본 수집 카테고리","생활용품 · 주방용품 · 패션잡화 · 식품 · 디지털/가전 · 화장품/미용");c.pack(fill="x")
  r=tk.Frame(c,bg="white");r.pack(fill="x",padx=14,pady=(8,14))
  for i,name in enumerate(settings().get("categories",[])):
   tk.Label(r,text=name,bg="#f0edff",fg=self.COLORS["accent"],font=("Malgun Gothic",9,"bold"),padx=10,pady=6).grid(row=0,column=i,sticky="w",padx=(0,5))
  tr=self._card(p,"트렌드 키워드","트렌드와 3사 상품 수집을 분리하지 않고 ‘수집 센터’에서 함께 관리합니다.");tr.pack(fill="x",pady=(12,0))
  rr=tk.Frame(tr,bg="white");rr.pack(fill="x",padx=14,pady=(6,14));rr.grid_columnconfigure(0,weight=1)
  ttk.Button(rr,text="수집 센터 열기 · 3사 + 트렌드",style="Accent.TButton",command=lambda:self.show_page("collect_run")).grid(row=0,column=0,sticky="ew")

 def _build_collect_settings_page(self,p):
  c=self._card(p,"현재 수집 정책","3사 고정 카테고리 수집 + 쿠팡 트렌드 API 우선 + 동일상품 이미지 3장 정확도 우선 정책");c.pack(fill="x")
  r=tk.Frame(c,bg="white");r.pack(fill="x",padx=14,pady=(6,14))
  items=[("3사 상품 수집","쿠팡 · 토스 · 네이버, 카테고리별 30개"),("트렌드 추출","쿠팡 웹검색 대신 Partners API 우선"),("이미지 3장","쿠팡 API → NAVER 이미지 API exact 우선 → 부족 시 쿠팡 상세/Google 원본검증"),("안전 규칙","틀린 사진으로 억지 3장 채우기 금지")]
  for i,(a,b) in enumerate(items):
   tk.Label(r,text=a,bg="white",fg=self.COLORS["text"],font=("Malgun Gothic",9,"bold"),anchor="w").grid(row=i,column=0,sticky="w",pady=5)
   tk.Label(r,text=b,bg="white",fg=self.COLORS["muted"],font=("Malgun Gothic",9),anchor="w").grid(row=i,column=1,sticky="w",padx=(18,0),pady=5)
  ttk.Button(c,text="전체 설정(JSON) 열기",style="Soft.TButton",command=lambda:self.show_page("advanced")).pack(anchor="e",padx=14,pady=(0,14))

 def _build_collect_run_page(self,p):
  # Overall live status
  top=self._card(p,"통합 수집 진행 상황","3사 상품 수집과 트렌드 수집을 같은 화면에서 확인합니다. 후속 원고·이미지·검증 진행률도 아래에서 이어서 볼 수 있습니다.");top.pack(fill="x")
  row=tk.Frame(top,bg="white");row.pack(fill="x",padx=14,pady=(8,6));row.grid_columnconfigure(0,weight=1)
  ttk.Button(row,text="▶ 전체 파이프라인 실행",style="Accent.TButton",command=self.runall).grid(row=0,column=0,sticky="ew")
  ttk.Button(row,text="■ 중지",style="Danger.TButton",command=lambda:setattr(self,"stop",True)).grid(row=0,column=1,padx=(8,0))
  self.total=ttk.Progressbar(top,maximum=100);self.total.pack(fill="x",padx=14,pady=(2,5))
  self.totalmsg=ttk.Label(top,text="대기 중",style="Card.TLabel",foreground=self.COLORS["muted"]);self.totalmsg.pack(anchor="w",padx=14,pady=(0,12))

  dual=tk.Frame(p,bg=self.COLORS["bg"]);dual.pack(fill="x",pady=(12,0));dual.grid_columnconfigure(0,weight=1);dual.grid_columnconfigure(1,weight=1)
  # 3-site collection
  left=self._card(dual,"3사 사이트 인기상품 수집","쿠팡 · 토스쇼핑 · 네이버쇼핑을 고정 카테고리 기준으로 한 번에 수집합니다.");left.grid(row=0,column=0,sticky="nsew",padx=(0,6))
  self.collect_source_metric_vars={}
  metric=tk.Frame(left,bg="white");metric.pack(fill="x",padx=14,pady=(4,8))
  for i,(key,label) in enumerate([("쿠팡","쿠팡"),("토스쇼핑","토스"),("네이버쇼핑","네이버")]):
   metric.grid_columnconfigure(i,weight=1)
   box=tk.Frame(metric,bg="#f7f8fc",highlightbackground=self.COLORS["line"],highlightthickness=1);box.grid(row=0,column=i,sticky="ew",padx=(0 if i==0 else 4,0 if i==2 else 4))
   tk.Label(box,text=label,bg="#f7f8fc",fg=self.COLORS["muted"],font=("Malgun Gothic",8,"bold")).pack(anchor="w",padx=10,pady=(8,0))
   v=tk.StringVar(value="0/180");self.collect_source_metric_vars[key]=v
   tk.Label(box,textvariable=v,bg="#f7f8fc",fg=self.COLORS["accent"],font=("Malgun Gothic",15,"bold")).pack(anchor="w",padx=10,pady=(0,8))
  rr=tk.Frame(left,bg="white");rr.pack(fill="x",padx=14,pady=(0,12));rr.grid_columnconfigure(0,weight=1);rr.grid_columnconfigure(1,weight=1)
  ttk.Button(rr,text="▶ 3사 인기상품 수집 시작",style="Accent.TButton",command=lambda:self.single("search")).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(rr,text="수집 결과 보기",style="Soft.TButton",command=lambda:self.show_page("collected")).grid(row=0,column=1,sticky="ew",padx=(4,0))

  # Trend collection
  right=self._card(dual,"트렌드 수집 · 인기상품 연결","아이템스카우트와 네이버 데이터랩을 수집한 뒤 트렌드 키워드를 쿠팡 대표상품으로 연결합니다.");right.grid(row=0,column=1,sticky="nsew",padx=(6,0))
  self.collect_dual=(dual,left,right)
  self.collect_trend_summary=tk.StringVar(value="아이템스카우트 0 · 네이버 데이터랩 0 · 쿠팡 연결 0")
  ttk.Label(right,textvariable=self.collect_trend_summary,style="Card.TLabel",foreground=self.COLORS["accent"]).pack(anchor="w",padx=14,pady=(4,5))
  self.collect_trend_pb=ttk.Progressbar(right,maximum=100);self.collect_trend_pb.pack(fill="x",padx=14,pady=(0,4))
  self.collect_trend_info=tk.StringVar(value="트렌드 수집 대기")
  ttk.Label(right,textvariable=self.collect_trend_info,style="Card.TLabel",foreground=self.COLORS["muted"]).pack(anchor="w",padx=14,pady=(0,7))
  tr=tk.Frame(right,bg="white");tr.pack(fill="x",padx=14,pady=(0,12));self.collect_trend_button_frame=tr
  for i in range(3):tr.grid_columnconfigure(i,weight=1)
  b1=ttk.Button(tr,text="아이템스카우트 수집",style="Soft.TButton",command=lambda:self.trend_collect("아이템스카우트"));b1.grid(row=0,column=0,sticky="ew",padx=(0,3))
  b2=ttk.Button(tr,text="네이버 데이터랩 수집",style="Soft.TButton",command=lambda:self.trend_collect("네이버데이터랩"));b2.grid(row=0,column=1,sticky="ew",padx=3)
  b3=ttk.Button(tr,text="트렌드 → 쿠팡 상품 연결",style="Accent.TButton",command=self.trend_coupang_extract);b3.grid(row=0,column=2,sticky="ew",padx=(3,0))
  self.collect_trend_buttons=[b1,b2,b3]

  # v8.08.40: real-time Ollama monitor. The previous UI only updated before/after
  # each product, so a long local-model call looked frozen even when it was working.
  live=self._card(p,"Ollama 원고 실시간 모니터","현재 상품, 생성 단계, 경과시간, 생성량, 처리속도와 남은 예상시간을 실제 생성 중 계속 갱신합니다.");live.pack(fill="x",pady=(10,0))
  self.content_live_vars={
   "product":tk.StringVar(value="대기"),"phase":tk.StringVar(value="대기"),"model":tk.StringVar(value=str(settings().get("ollama_model") or "qwen3:8b")),
   "elapsed":tk.StringVar(value="0초"),"output":tk.StringVar(value="0자"),"speed":tk.StringVar(value="-"),"eta":tk.StringVar(value="-"),"attempt":tk.StringVar(value="-")
  }
  mg=tk.Frame(live,bg="white");mg.pack(fill="x",padx=14,pady=(2,5));self.collect_live_metrics_frame=mg;self.collect_live_metric_cells=[]
  metrics=[("현재 상품","product",3),("단계","phase",2),("모델","model",1),("경과","elapsed",1),("생성량","output",1),("속도","speed",1),("남은 예상","eta",1),("재작성","attempt",1)]
  for i,(label,key,weight) in enumerate(metrics):
   mg.grid_columnconfigure(i,weight=weight)
   cell=tk.Frame(mg,bg="#f7f8fc",highlightbackground=self.COLORS["line"],highlightthickness=1);cell.grid(row=0,column=i,sticky="nsew",padx=2,pady=2);self.collect_live_metric_cells.append(cell)
   tk.Label(cell,text=label,bg="#f7f8fc",fg=self.COLORS["muted"],font=("Malgun Gothic",7,"bold")).pack(anchor="w",padx=8,pady=(5,0))
   tk.Label(cell,textvariable=self.content_live_vars[key],bg="#f7f8fc",fg=self.COLORS["accent"] if key in {"product","phase"} else self.COLORS["text"],font=("Malgun Gothic",8,"bold"),anchor="w").pack(fill="x",padx=8,pady=(0,5))
  self.content_live_pb=ttk.Progressbar(live,maximum=100);self.content_live_pb.pack(fill="x",padx=14,pady=(0,4))
  self.content_live_preview=tk.StringVar(value="원고 생성 버튼을 누르면 여기에서 Ollama가 실제로 응답을 만들고 있는지 실시간으로 확인할 수 있습니다.")
  self.content_live_preview_label=ttk.Label(live,textvariable=self.content_live_preview,style="Card.TLabel",foreground=self.COLORS["muted"],justify="left")
  self.content_live_preview_label.pack(anchor="w",fill="x",padx=14,pady=(0,9))
  self.content_live_started_at=0.0;self.content_live_last_event={};self.content_live_avg_sec=0.0

  # Pipeline stages / live progress
  stages_title=tk.Frame(p,bg=self.COLORS["bg"]);stages_title.pack(fill="x",pady=(14,4))
  tk.Label(stages_title,text="후속 작업 진행 상황",bg=self.COLORS["bg"],fg=self.COLORS["text"],font=("Malgun Gothic",11,"bold")).pack(side="left")
  self.collect_stage_flow_label=tk.Label(stages_title,text="수집 → 원고 → 사진3장 → 가격검증 → 품질검수 → 임시저장",bg=self.COLORS["bg"],fg=self.COLORS["muted"],font=("Malgun Gothic",8),justify="left",anchor="w")
  self.collect_stage_flow_label.pack(side="left",fill="x",expand=True,padx=10)
  steps=tk.Frame(p,bg=self.COLORS["bg"]);steps.pack(fill="both",expand=True);self.collect_steps_frame=steps;self.collect_step_boxes=[]
  for c in range(3):steps.grid_columnconfigure(c,weight=1)
  for i,(k,l,m) in enumerate(STEPS):
   box=self._card(steps,l);box.grid(row=i//3,column=i%3,sticky="nsew",padx=5,pady=5);self.collect_step_boxes.append(box)
   v=tk.StringVar(value="대기");self.vars[k]=v;ttk.Label(box,textvariable=v,style="Card.TLabel",foreground=self.COLORS["muted"]).pack(anchor="w",padx=14,pady=(4,2))
   pb=ttk.Progressbar(box,maximum=100);pb.pack(fill="x",padx=14,pady=(0,8));self.pbs[k]=pb
   if k=="qa":cmd=lambda:self.single("qa");txt="SEO/중복/원고 품질검수"
   elif k=="blog":cmd=lambda:self.blog_single("images_only");txt="이미지 3장 임시저장"
   else:cmd=lambda kk=k:self.single(kk);txt={"search":"3사 인기상품 수집","content":"Ollama 원고 생성","images":"동일상품 사진 3장","price":"3사 가격+이미지 검증"}.get(k,"실행")
   ttk.Button(box,text=txt,style="Soft.TButton",command=cmd).pack(fill="x",padx=14,pady=(0,14))
  p.bind("<Configure>",lambda e:self._layout_collect_page(e.width),add="+")
  self.after_idle(lambda:self._layout_collect_page(p.winfo_width()))

 def _build_celebrity_style_page(self,p):
  top=self._card(p,"실시간 착장 후보 수집","자동 수집은 최근 공항패션·브랜드행사·시사회·제작발표회·출근길·사복 키워드를 검색합니다. 특정 연예인을 입력하면 그 인물만 좁혀서 확인합니다.")
  top.pack(fill="x")
  row=tk.Frame(top,bg="white");row.pack(fill="x",padx=14,pady=(6,8));row.grid_columnconfigure(1,weight=1)
  tk.Label(row,text="연예인 직접 검색",bg="white",fg=self.COLORS["text"],font=("Malgun Gothic",9,"bold")).grid(row=0,column=0,sticky="w",padx=(0,8))
  self.celeb_name_var=tk.StringVar(value="")
  ttk.Entry(row,textvariable=self.celeb_name_var).grid(row=0,column=1,sticky="ew",padx=(0,8))
  tk.Label(row,text="기간",bg="white",fg=self.COLORS["text"],font=("Malgun Gothic",9,"bold")).grid(row=0,column=2,sticky="e",padx=(0,6))
  self.celeb_period_var=tk.StringVar(value="3일")
  ttk.Combobox(row,textvariable=self.celeb_period_var,state="readonly",values=["1일","3일","7일","14일"],width=7).grid(row=0,column=3,sticky="e")
  br=tk.Frame(top,bg="white");br.pack(fill="x",padx=14,pady=(0,14))
  for i in range(4):br.grid_columnconfigure(i,weight=1)
  ttk.Button(br,text="🔥 최신 착장 자동 수집",style="Accent.TButton",command=lambda:self.celebrity_style_run("collect_auto")).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(br,text="🔎 입력 연예인 검색",style="Soft.TButton",command=lambda:self.celebrity_style_run("collect_manual")).grid(row=0,column=1,sticky="ew",padx=4)
  ttk.Button(br,text="▶ 전체 자동 파이프라인",style="Soft.TButton",command=lambda:self.celebrity_style_run("full")).grid(row=0,column=2,sticky="ew",padx=4)
  ttk.Button(br,text="CSV 열기",style="Soft.TButton",command=self.open_celebrity_style_csv).grid(row=0,column=3,sticky="ew",padx=(4,0))

  policy=self._card(p,"20년차 검증형 정확도 정책","사진만 보고 브랜드를 확정하지 않습니다. 인물·행사·날짜를 먼저 묶고, 독립 출처 교차확인과 상품명 검증을 거쳐 확정/추정/유사스타일을 분리합니다.")
  policy.pack(fill="x",pady=(10,0))
  self.celeb_policy_var=tk.StringVar(value="Qwen3-VL 상태 확인 중")
  tk.Label(policy,textvariable=self.celeb_policy_var,bg="white",fg=self.COLORS["accent"],font=("Malgun Gothic",9,"bold"),anchor="w").pack(fill="x",padx=14,pady=(5,2))
  txt=("• 확정: 텍스트에 브랜드+구체 제품/모델 근거가 있고, 독립 출처 2개 이상 또는 신뢰도 높은 원문 근거 + 쇼핑 상품명이 일치\n"
       "• 추정: 브랜드만 언급되거나 Vision이 로고/색상/실루엣만 포착한 경우 — 정확 제품이라고 쓰지 않음\n"
       "• 유사스타일: 정확 착용품을 검증하지 못했지만 비슷한 스타일의 판매상품을 찾은 경우 — 글에서도 명확히 유사상품으로 표시\n"
       "• 저작권 안전: 뉴스/블로그의 연예인 사진은 분석 근거로만 사용하고 블로그 이미지 3장으로 자동 재게시하지 않음")
  tk.Label(policy,text=txt,bg="white",fg=self.COLORS["text"],justify="left",anchor="w",font=("Malgun Gothic",9)).pack(fill="x",padx=14,pady=(2,8))
  pr=tk.Frame(policy,bg="white");pr.pack(fill="x",padx=14,pady=(0,14))
  for i in range(3):pr.grid_columnconfigure(i,weight=1)
  ttk.Button(pr,text="Qwen3-VL Vision 자동설치",style="Soft.TButton",command=self.ollama_vision_setup).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(pr,text="착장 관련 이미지 가져오기",style="Soft.TButton",command=lambda:self.celebrity_style_run("images_selected_or_all")).grid(row=0,column=1,sticky="ew",padx=4)
  ttk.Button(pr,text="착장 AI 근거분석",style="Soft.TButton",command=lambda:self.celebrity_style_run("analyze_selected_or_all")).grid(row=0,column=2,sticky="ew",padx=(4,0))

  act=self._card(p,"상품 검증 · 원고 · 기존 파이프라인 연결","정확상품과 유사스타일을 구분해서 매칭한 뒤 연예인 착장 글을 생성합니다. 선택 원고를 기존 작성물로 보내면 그 상품명을 기준으로 기존의 엄격 이미지 3장/Sharelink/SmartEditor 기능을 그대로 사용할 수 있습니다.")
  act.pack(fill="x",pady=(10,0))
  ar=tk.Frame(act,bg="white");ar.pack(fill="x",padx=14,pady=(6,14))
  for i in range(4):ar.grid_columnconfigure(i,weight=1)
  ttk.Button(ar,text="① 상품 검증/매칭",style="Soft.TButton",command=lambda:self.celebrity_style_run("match_selected_or_all")).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(ar,text="② 착장 블로그 원고 생성",style="Accent.TButton",command=lambda:self.celebrity_style_run("draft_selected_or_all")).grid(row=0,column=1,sticky="ew",padx=4)
  ttk.Button(ar,text="③ 선택 원고 → 작성물 연동",style="Soft.TButton",command=self.celebrity_style_promote_selected).grid(row=0,column=2,sticky="ew",padx=4)
  ttk.Button(ar,text="④ 연동 원고 텍스트 임시저장",style="Soft.TButton",command=self.celebrity_style_blog_selected).grid(row=0,column=3,sticky="ew",padx=(4,0))

  self.celeb_style_pb=ttk.Progressbar(p,maximum=100);self.celeb_style_pb.pack(fill="x",pady=(10,3))
  self.celeb_style_info=tk.StringVar(value="연예인 착장 수집 대기")
  ttk.Label(p,textvariable=self.celeb_style_info,style="PageSub.TLabel").pack(anchor="w",fill="x",pady=(0,6))
  self.celeb_style_summary=tk.StringVar(value="후보 0 · 분석 0 · 상품매칭 0 · 원고 0")
  ttk.Label(p,textvariable=self.celeb_style_summary,style="PageSub.TLabel",foreground=self.COLORS["accent"]).pack(anchor="w",fill="x",pady=(0,6))

  table=self._card(p,"착장 후보 · 근거 상태");table.pack(fill="both",expand=True,pady=(2,0))
  cols=("id","celeb","date","look","sources","confidence","items","matched","status")
  self.celeb_style_tree=ttk.Treeview(table,columns=cols,show="headings",height=11)
  for c,h,w in [("id","ID",45),("celeb","연예인",90),("date","기준일",92),("look","착장상황",105),("sources","독립출처",70),("confidence","신뢰점수",70),("items","아이템",60),("matched","상품",60),("status","상태",150)]:
   self.celeb_style_tree.heading(c,text=h);self.celeb_style_tree.column(c,width=w,anchor="w")
  sy=ttk.Scrollbar(table,orient="vertical",command=self.celeb_style_tree.yview);self.celeb_style_tree.configure(yscrollcommand=sy.set)
  self.celeb_style_tree.pack(side="left",fill="both",expand=True,padx=(14,0),pady=(4,14));sy.pack(side="right",fill="y",padx=(0,14),pady=(4,14))
  self.celeb_style_tree.bind("<<TreeviewSelect>>",lambda e:self.show_celebrity_style_detail())

  detail=self._card(p,"선택 착장 상세 · 출처/아이템/원고 미리보기");detail.pack(fill="both",expand=True,pady=(10,16))
  self.celeb_style_detail=tk.Text(detail,height=18,wrap="word",font=("Malgun Gothic",9),bg="#fbfbfe",fg=self.COLORS["text"],relief="flat",padx=10,pady=10)
  self.celeb_style_detail.pack(fill="both",expand=True,padx=14,pady=(4,14))
  try:
   vs=celebrity_style_adapter.vision_status();self.celeb_policy_var.set(vs.get("message") or "Vision 상태 미확인")
  except Exception as e:self.celeb_policy_var.set("Vision 상태 확인 실패: "+str(e))

 def _build_write_settings_page(self,p):
  c=self._card(p,"작성 파이프라인","Ollama 무료 AI 원고 → 동일상품 이미지 3장 → 가격검증 → SEO/중복 품질검수");c.pack(fill="x")
  r=tk.Frame(c,bg="white");r.pack(fill="x",padx=14,pady=(8,14));
  for i in range(4):r.grid_columnconfigure(i,weight=1)
  for i,(t,cmd) in enumerate([("Ollama 원고 생성",lambda:self.single("content")),("사진 3장",lambda:self.single("images")),("가격 검증",lambda:self.single("price")),("품질검수",lambda:self.single("qa"))]):
   ttk.Button(r,text=t,style="Accent.TButton" if i==0 else "Soft.TButton",command=cmd).grid(row=0,column=i,sticky="ew",padx=4)
  ttk.Button(p,text="작성물 관리 열기",style="Soft.TButton",command=lambda:self.show_page("drafts")).pack(anchor="e",pady=(12,0))

 def _build_persona_page(self,p):
  c=self._card(p,"현재 AI 페르소나","광고문구를 반복하기보다 실제 소비자가 비교·선택하는 흐름으로 쓰고, 상품마다 관점을 바꿉니다.");c.pack(fill="x")
  text=("• 생활밀착형 / 비교결정형 / 불편해결형 / 초보구매형 / 구성확인형 / 취향매칭형 관점 순환\n"
        "• 첫 문단에서 왜 볼 가치가 있는지 제시\n• 중간에는 사용장면·구성·비교 포인트\n• 마지막에는 과장 없이 링크에서 현재 옵션·가격 확인을 유도\n"
        "• 실제 사용 증거가 없는 경우 허위 내돈내산/직접사용 표현 금지")
  tk.Label(c,text=text,bg="white",fg=self.COLORS["text"],justify="left",anchor="w",font=("Malgun Gothic",9),pady=8).pack(fill="x",padx=14,pady=(0,14))

 def _build_disclosure_page(self,p):
  c=self._card(p,"경제적 이해관계 고지문","블로그 글 최상단에 사용하는 고정 고지문입니다.");c.pack(fill="x")
  msg="이 포스팅은 쿠팡 파트너스 활동의 일환으로,\n이에 따른 일정액의 수수료를 제공받습니다."
  tk.Label(c,text=msg,bg="#fff9df",fg="#5f5124",justify="left",font=("Malgun Gothic",10,"bold"),padx=14,pady=14).pack(fill="x",padx=14,pady=(8,14))
  ttk.Button(p,text="제휴링크 생성",style="Accent.TButton",command=self.sharelink_images_only).pack(anchor="e",pady=(12,0))

 def _build_test_write_page(self,p):
  c=self._card(p,"테스트 작성","대량 작업 전에 연결·원고·임시저장을 개별 점검합니다.");c.pack(fill="x")
  r=tk.Frame(c,bg="white");r.pack(fill="x",padx=14,pady=(8,14));
  for i in range(3):r.grid_columnconfigure(i,weight=1)
  ttk.Button(r,text="1. Ollama 원고 생성",style="Soft.TButton",command=lambda:self.single("content")).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(r,text="2. 네이버 저장환경 점검",style="Soft.TButton",command=self.blog_preflight).grid(row=0,column=1,sticky="ew",padx=4)
  ttk.Button(r,text="3. 텍스트만 임시저장",style="Accent.TButton",command=lambda:self.blog_single("text_only")).grid(row=0,column=2,sticky="ew",padx=(4,0))

 def _build_publish_page(self,p):
  c=self._card(p,"네이버 블로그 임시저장","텍스트/이미지3장 모드 모두 동일 원고를 사용하며, 같은 Chrome + 같은 탭을 재사용합니다.");c.pack(fill="x")
  r=tk.Frame(c,bg="white");r.pack(fill="x",padx=14,pady=(8,14));
  for i in range(3):r.grid_columnconfigure(i,weight=1)
  ttk.Button(r,text="① 저장환경 사전점검",style="Soft.TButton",command=self.blog_preflight).grid(row=0,column=0,sticky="ew",padx=(0,4))
  ttk.Button(r,text="② 이미지 3장 임시저장",style="Accent.TButton",command=lambda:self.blog_single("images_only")).grid(row=0,column=1,sticky="ew",padx=4)
  ttk.Button(r,text="② 텍스트만 임시저장",style="Soft.TButton",command=lambda:self.blog_single("text_only")).grid(row=0,column=2,sticky="ew",padx=(4,0))
  ttk.Button(c,text="마지막 실패 1건 안전 재시도",style="Danger.TButton",command=self.retry_last_blog_failure).pack(anchor="e",padx=14,pady=(0,14))
  hist=self._card(p,"최근 작업 상태","최근 상품의 처리상태를 표시합니다.");hist.pack(fill="both",expand=True,pady=(12,0))
  self.publish_tree=ttk.Treeview(hist,columns=("no","name","status","updated"),show="headings",height=10)
  for c1,h,w in [("no","TOP",55),("name","상품명",520),("status","상태",210),("updated","최근 갱신",150)]:self.publish_tree.heading(c1,text=h);self.publish_tree.column(c1,width=w,anchor="w")
  self.publish_tree.pack(fill="both",expand=True,padx=14,pady=(6,14))

 def _build_license_page(self,p):
  c=self._card(p,"NBlog Automation Studio","현재 배포본은 로컬 PC에서 실행되는 자동화 스튜디오입니다.");c.pack(fill="x")
  info="버전: v8.08.52 OLLAMA HUMAN TONE\n핵심: 연예인 착장 실시간 후보수집 · 다중출처 교차검증 · Qwen3-VL 보조분석 · 정확/추정/유사상품 분리 · 기존 상품/블로그 파이프라인 연동 · 동일상품 이미지 3장\n데이터: 로컬 SQLite / 로컬 설정 파일"
  tk.Label(c,text=info,bg="white",fg=self.COLORS["text"],justify="left",font=("Malgun Gothic",10),pady=12).pack(fill="x",padx=14,pady=(4,14))

 def refresh_modern_overview(self):
  if not hasattr(self,"overview_vars"):return
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
  total=con.execute("SELECT COUNT(*) c FROM products WHERE status NOT LIKE '추천제외:%'").fetchone()[0]
  content=con.execute("SELECT COUNT(*) FROM products WHERE title IS NOT NULL AND TRIM(title)<>'' AND body IS NOT NULL AND TRIM(body)<>'' AND tags IS NOT NULL AND TRIM(tags)<>'' AND status NOT LIKE '추천제외:%'").fetchone()[0]
  images=con.execute("SELECT COUNT(*) FROM products WHERE COALESCE(image_verified_count,0)>=3 AND status NOT LIKE '추천제외:%'").fetchone()[0]
  posted=con.execute("SELECT COUNT(*) FROM products WHERE COALESCE(already_posted,0)=1").fetchone()[0]
  ready=con.execute("SELECT COUNT(*) FROM products WHERE title IS NOT NULL AND TRIM(title)<>'' AND body IS NOT NULL AND TRIM(body)<>'' AND tags IS NOT NULL AND TRIM(tags)<>'' AND COALESCE(image_verified_count,0)>=3 AND COALESCE(already_posted,0)=0 AND status NOT LIKE '추천제외:%'").fetchone()[0]
  vals={"overview_total":total,"overview_content":content,"overview_images":images,"overview_ready":ready,"overview_posted":posted}
  for k,v in vals.items():self.overview_vars[k].set(str(v))
  if hasattr(self,"overview_tree"):
   self.overview_tree.delete(*self.overview_tree.get_children())
   rows=con.execute("SELECT product_no,name,status,image_verified_count FROM products WHERE status NOT LIKE '추천제외:%' ORDER BY COALESCE(updated_at,'') DESC,id DESC LIMIT 8").fetchall()
   for r in rows:self.overview_tree.insert("","end",values=(r["product_no"] or "-",r["name"] or "-",r["status"] or "대기",f"{int(r['image_verified_count'] or 0)}/3"))
  if hasattr(self,"publish_tree"):
   self.publish_tree.delete(*self.publish_tree.get_children())
   rows=con.execute("SELECT product_no,name,status,updated_at FROM products WHERE status NOT LIKE '추천제외:%' ORDER BY COALESCE(updated_at,'') DESC,id DESC LIMIT 12").fetchall()
   for r in rows:self.publish_tree.insert("","end",values=(r["product_no"] or "-",r["name"] or "-",r["status"] or "대기",r["updated_at"] or "-"))
  con.close()

 def dashboard(self):
  p=self.tabs["상품/진행현황"]
  bar=ttk.Frame(p,padding=8);bar.pack(fill="x")
  ttk.Button(bar,text="새로고침",command=self.refresh).pack(side="left")
  ttk.Button(bar,text="선택 승인",command=self.approve).pack(side="left",padx=4)
  ttk.Button(bar,text="TOP100 CSV",command=self.export).pack(side="left")
  ttk.Button(bar,text="원천 540 CSV",command=self.export_candidates).pack(side="left",padx=4)
  ttk.Button(bar,text="수집 진단 폴더",command=self.open_collection_diagnostics).pack(side="left",padx=4)
  ttk.Button(bar,text="이미지 실패 진단",command=self.open_image_diagnostics).pack(side="left",padx=4)
  self.collect_summary=tk.StringVar(value="수집 현황: 대기")
  ttk.Label(bar,textvariable=self.collect_summary,font=("Malgun Gothic",10,"bold")).pack(side="right")

  helper=ttk.LabelFrame(p,text="작업 도우미 · 기능 설명과 빠른 실행",padding=8);helper.pack(fill="x",padx=8,pady=(0,6))
  self.workflow_hint=tk.StringVar(value="‘다음 할 일 자동안내’를 누르면 현재 상태에 맞는 작업을 알려드립니다.")
  ttk.Label(helper,textvariable=self.workflow_hint,font=("Malgun Gothic",9,"bold"),wraplength=1370).pack(anchor="w",fill="x")
  helper_buttons=ttk.Frame(helper);helper_buttons.pack(fill="x",pady=(6,0))
  for column in range(4):helper_buttons.columnconfigure(column,weight=1)
  ttk.Button(helper_buttons,text="기능 한눈에 보기",command=self.show_function_guide).grid(row=0,column=0,sticky="ew",padx=(0,2))
  ttk.Button(helper_buttons,text="다음 할 일 자동안내",command=self.show_next_action).grid(row=0,column=1,sticky="ew",padx=2)
  ttk.Button(helper_buttons,text="마지막 임시저장 실패 재시도",command=self.retry_last_blog_failure).grid(row=0,column=2,sticky="ew",padx=2)
  ttk.Button(helper_buttons,text="실패 진단 폴더",command=self.open_blog_diagnostics).grid(row=0,column=3,sticky="ew",padx=(2,0))

  ext=ttk.LabelFrame(p,text="외부 원고 폴더 · 원고/이미지 가져오기",padding=8);ext.pack(fill="x",padx=8,pady=(0,6))
  self.external_batch_info=tk.StringVar(value="선택된 외부 배치 없음")
  ttk.Label(ext,textvariable=self.external_batch_info,font=("Malgun Gothic",9,"bold"),wraplength=1300).pack(anchor="w",fill="x")
  ext_buttons=ttk.Frame(ext);ext_buttons.pack(fill="x",pady=(7,0))
  for column in range(5):ext_buttons.columnconfigure(column,weight=1)
  ttk.Button(ext_buttons,text="폴더 선택·가져오기",command=self.external_batch_choose_folder).grid(row=0,column=0,sticky="ew",padx=(0,2))
  ttk.Button(ext_buttons,text="ZIP 선택·가져오기",command=self.external_batch_choose_zip).grid(row=0,column=1,sticky="ew",padx=2)
  ttk.Button(ext_buttons,text="완료/미완료 분류표",command=self.open_external_batch_report).grid(row=0,column=2,sticky="ew",padx=2)
  ttk.Button(ext_buttons,text="사진3장 완료만 임시저장",command=lambda:self.external_batch_blog("complete")).grid(row=0,column=3,sticky="ew",padx=2)
  ttk.Button(ext_buttons,text="이미지 미완료만 텍스트 임시저장",command=lambda:self.external_batch_blog("incomplete")).grid(row=0,column=4,sticky="ew",padx=(2,0))
  self.refresh_external_batch_state()

  posted=ttk.LabelFrame(p,text="이미 수동으로 올린 네이버 글 제외",padding=8);posted.pack(fill="x",padx=8,pady=(0,6))
  self.already_posted_info=tk.StringVar(value="기존 게시글 대조 전")
  ttk.Label(posted,textvariable=self.already_posted_info,font=("Malgun Gothic",9,"bold"),wraplength=1300).pack(anchor="w",fill="x")
  posted_buttons=ttk.Frame(posted);posted_buttons.pack(fill="x",pady=(7,0))
  for column in range(5):posted_buttons.columnconfigure(column,weight=1)
  ttk.Button(posted_buttons,text="선택 제품 수동 게시완료",command=lambda:self.existing_post_selected(True)).grid(row=0,column=0,sticky="ew",padx=(0,2))
  ttk.Button(posted_buttons,text="선택 게시표시 해제",command=lambda:self.existing_post_selected(False)).grid(row=0,column=1,sticky="ew",padx=2)
  ttk.Button(posted_buttons,text="네이버 기존글 자동대조",command=self.existing_post_auto).grid(row=0,column=2,sticky="ew",padx=2)
  ttk.Button(posted_buttons,text="제목 TXT·CSV 자동대조",command=self.existing_post_file).grid(row=0,column=3,sticky="ew",padx=2)
  ttk.Button(posted_buttons,text="게시완료/남은목록",command=self.open_existing_post_report).grid(row=0,column=4,sticky="ew",padx=(2,0))

  sub=ttk.Notebook(p);sub.pack(fill="both",expand=True,padx=8,pady=(0,8))
  top=ttk.Frame(sub);sub.add(top,text="TOP 100")
  self.source_trees={};self.source_count_labels={}
  for platform,label in [("쿠팡","쿠팡 수집 180"),("토스쇼핑","토스 수집 180"),("네이버쇼핑","네이버 수집 180")]:
   f=ttk.Frame(sub);sub.add(f,text=label);self._build_source_tree(f,platform)
  cov=ttk.Frame(sub);sub.add(cov,text="540 수집 검증")
  self.coverage_text=tk.Text(cov,font=("Consolas",10),wrap="none");self.coverage_text.pack(fill="both",expand=True,padx=8,pady=8)

  pager=ttk.Frame(top,padding=(4,6));pager.pack(fill="x")
  self.top_page=1;self.top_page_size=50;self.top_page_label=tk.StringVar(value="1 / 2 페이지 · 1~50")
  ttk.Button(pager,text="◀ 이전 50개",command=lambda:self.change_top_page(-1)).pack(side="left")
  ttk.Button(pager,text="다음 50개 ▶",command=lambda:self.change_top_page(1)).pack(side="left",padx=4)
  ttk.Label(pager,textvariable=self.top_page_label,font=("Malgun Gothic",10,"bold")).pack(side="left",padx=10)
  ttk.Label(pager,text="Top100은 인기점수 순이며, 출처 칸에 실제 발견 사이트를 표시합니다.",foreground="#666666").pack(side="right")

  cols=("no","name","cat","source","score","posted","status","verify","prices","approved")
  self.tree=ttk.Treeview(top,columns=cols,show="headings")
  heads={"no":"TOP","name":"상품명","cat":"카테고리","source":"발견 사이트","score":"인기점수","posted":"게시 구분","status":"처리상태","verify":"이미지/가격 검증","prices":"토스 / 쿠팡 / 네이버","approved":"승인"}
  widths={"no":55,"name":370,"cat":100,"source":145,"score":70,"posted":125,"status":115,"verify":140,"prices":190,"approved":55}
  for c in cols:self.tree.heading(c,text=heads[c]);self.tree.column(c,width=widths[c],anchor="w")
  self.tree.pack(fill="both",expand=True,padx=4,pady=4);self.tree.bind("<<TreeviewSelect>>",lambda e:self.show())
  self.live=tk.Text(top,height=6,font=("Consolas",9));self.live.pack(fill="x",padx=4,pady=(0,4))

 def tabs_nb_select(self,name):
  mapping={"상품/진행현황":"collected","추가 트렌드 수집":"trend","트렌드→쿠팡 추출":"trend_products","결과 미리보기":"drafts","이미지·가격 검증":"verify","AI 제품영상":"video","성능/최적화":"performance","블로그 양식":"template","문제 해결":"diagnostics","실행 로그":"logs","설정/선택기능":"advanced"}
  self.show_page(mapping.get(name,name))

 def blog_preflight(self):
  try:
   result=blog_adapter.clipboard_preflight()
   h=blog_adapter.health();cfg=settings()
   single_ok=bool(cfg.get("blog_reuse_single_browser_session",True) and cfg.get("blog_single_tab_only",True) and int(cfg.get("blog_browser_recycle_every_posts",0))==0)
   msg=(f"에디터: {h.get('message','')}\n\n"
        f"브라우저 정책: {'정상 · Chrome 1개/탭 1개 재사용' if single_ok else '설정 확인 필요'}\n"
        f"클립보드(보조 경로): {result.get('message','')}\n\n"
        "모든 임시저장 버튼은 같은 SmartEditor 엔진을 사용합니다. 제목을 먼저 검증한 뒤 본문 전체를 한 번의 실제 키보드 세션으로 입력하고, 이미지 모드는 슬롯만 실제 사진으로 교체합니다.\n"
        "제목: 실제 제목 클릭 → 직접 키입력(기존 성공 경로) → placeholder 제외 DOM 검증 → 0자 실패일 때만 Paste 복구\n"
        "본문: 텍스트만/이미지3장 모두 동일 원고 → Windows 물리 Unicode 전체 입력 → 이미지3장은 사진 삽입 완료 후 서식 적용 → 소제목/장점 굵게+#fff8b2 → 임시저장 직전 재검증\n"
        "이미지: 본문에 남긴 ㊀/㊁/㊂ 슬롯을 사진 1/2/3으로 차례로 교체합니다.\n"
        "제목 이전 DOM 테스트(NBDOM)는 사용하지 않습니다. helper tab/고정 mainFrame/문장별 본문 타이핑도 사용하지 않습니다.\n"
        "이미지 전 1차 검증 + 임시저장 직전 2차 검증을 모두 통과해야 저장 버튼을 찾습니다.")
   if h.get('ready') and single_ok:messagebox.showinfo("네이버 저장환경 정상",msg)
   else:messagebox.showerror("네이버 저장환경 점검 실패",msg)
  except Exception as e:messagebox.showerror("네이버 저장환경 점검 실패",str(e))

 def show_function_guide(self):
  popup=tk.Toplevel(self);popup.title("기능 한눈에 보기 · 권장 실행 순서");popup.geometry("900x720");popup.minsize(680,480)
  frame=ttk.Frame(popup,padding=10);frame.pack(fill="both",expand=True)
  text=tk.Text(frame,wrap="word",font=("Malgun Gothic",10),spacing1=2,spacing3=4)
  scroll=ttk.Scrollbar(frame,orient="vertical",command=text.yview);text.configure(yscrollcommand=scroll.set)
  text.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
  text.insert("1.0",workflow_assistant.guide_text());text.configure(state="disabled")
  popup.transient(self);popup.focus_set()

 def show_next_action(self):
  try:
   selected=external_batch_import.selected_state();batch_id=str(selected.get("batch_id") or "")
   result=workflow_assistant.recommendation(batch_id,selected_batch=bool(batch_id))
   self.workflow_hint.set("추천: "+result["action"])
   messagebox.showinfo("다음 할 일 자동안내",result["summary"])
  except Exception as e:messagebox.showerror("작업 상태 확인 실패",str(e))

 def retry_last_blog_failure(self):
  selected=external_batch_import.selected_state();batch_id=str(selected.get("batch_id") or "")
  try:item=workflow_assistant.last_failed_product(batch_id)
  except Exception as e:return messagebox.showerror("실패 제품 확인 오류",str(e))
  if not item:return messagebox.showinfo("재시도 대상 없음","현재 선택 범위에 임시저장 실패 제품이 없습니다.")
  mode_label="SmartEditor ONE(SE3 호환) + 이미지 슬롯 3장" if item["mode"]=="images_only" else "SmartEditor ONE(SE3 호환) · 이미지 없음"
  if not messagebox.askyesno("마지막 실패 1건 재시도",f"TOP {item['product_no']} · {item['name']}\n\n방식: {mode_label}\n최근 원인: {item['last_error'][:500]}\n\n이 제품 1건만 다시 실행할까요?"):
   return
  context={"product_ids":[item["id"]]}
  if batch_id:context["import_batch_id"]=batch_id
  self.blog_single(item["mode"],True,context)

 def open_blog_diagnostics(self):
  path=OUTPUTS/"blog_upload_diagnostics";path.mkdir(parents=True,exist_ok=True)
  try:
   if hasattr(os,"startfile"):os.startfile(str(path))
   else:subprocess.Popen(["xdg-open",str(path)])
  except Exception:messagebox.showinfo("실패 진단 폴더",str(path))

 def _build_source_tree(self,parent,platform):
  head=ttk.Frame(parent,padding=6);head.pack(fill="x")
  v=tk.StringVar(value=f"{platform}: 0/180");self.source_count_labels[platform]=v
  ttk.Label(head,textvariable=v,font=("Malgun Gothic",10,"bold")).pack(side="left")
  ttk.Label(head,text="6개 카테고리 × 각 30개 = 180개",foreground="#666666").pack(side="right")
  cols=("cat","rank","name","price","url")
  t=ttk.Treeview(parent,columns=cols,show="headings")
  for c,h,w in [("cat","카테고리",110),("rank","카테고리 순위",90),("name","상품명",580),("price","가격",100),("url","상품 URL",520)]:
   t.heading(c,text=h);t.column(c,width=w,anchor="w")
  y=ttk.Scrollbar(parent,orient="vertical",command=t.yview);x=ttk.Scrollbar(parent,orient="horizontal",command=t.xview)
  t.configure(yscrollcommand=y.set,xscrollcommand=x.set)
  t.pack(fill="both",expand=True,side="left",padx=(6,0),pady=(0,6));y.pack(fill="y",side="right",pady=(0,6));x.pack(fill="x",side="bottom",padx=6)
  self.source_trees[platform]=t

 def trend_tab(self):
  p=self.tabs["추가 트렌드 수집"]
  bar=ttk.Frame(p,padding=8);bar.pack(fill="x")
  ttk.Button(bar,text="아이템스카우트 20~30대 / 40~60대",command=lambda:self.trend_collect("아이템스카우트")).pack(side="left")
  ttk.Button(bar,text="네이버 데이터랩 20~30대 / 40~60대",command=lambda:self.trend_collect("네이버데이터랩")).pack(side="left",padx=4)
  ttk.Button(bar,text="트렌드 → 쿠팡 인기상품 추출",command=self.trend_coupang_extract).pack(side="left",padx=4)
  ttk.Button(bar,text="트렌드 CSV 저장",command=self.export_trends).pack(side="left",padx=4)
  ttk.Button(bar,text="새로고침",command=self.refresh_trends).pack(side="left")
  self.trend_summary=tk.StringVar(value="아이템스카우트 0/360 · 네이버 데이터랩 0/360")
  ttk.Label(bar,textvariable=self.trend_summary,font=("Malgun Gothic",10,"bold")).pack(side="right")
  note=("기존 쿠팡·토스·네이버 540개 상품 수집과 분리된 보조 트렌드입니다. "
        "패션의류·패션잡화·화장품/미용·디지털/가전·가구/인테리어·식품 × TOP30 × "
        "20~30대/40~60대를 각각 수집한 뒤, 같은 카테고리의 동일 키워드는 한 줄로 통합합니다. "
        "트렌드→쿠팡 버튼은 두 소스를 통합한 카테고리별 TOP30 키워드를 쿠팡에 검색해 대표 인기상품 1개씩 기존 상품목록에 연결합니다.")
  ttk.Label(p,text=note,foreground="#555555",wraplength=1380).pack(anchor="w",padx=10,pady=(0,6))
  self.trend_pb=ttk.Progressbar(p,maximum=100);self.trend_pb.pack(fill="x",padx=10,pady=(0,6))
  self.trend_info=tk.StringVar(value="대기 중");ttk.Label(p,textvariable=self.trend_info).pack(anchor="w",padx=10,pady=(0,6))
  cols=("source","age","cat","rank","keyword","agerank","captured","status")
  self.trend_tree=ttk.Treeview(p,columns=cols,show="headings")
  for c,h,w in [("source","수집처",120),("age","연령",150),("cat","카테고리",120),("rank","통합순위",70),("keyword","인기 키워드",430),("agerank","연령별 순위",210),("captured","수집시각",155),("status","상태",90)]:
   self.trend_tree.heading(c,text=h);self.trend_tree.column(c,width=w,anchor="w")
  y=ttk.Scrollbar(p,orient="vertical",command=self.trend_tree.yview);x=ttk.Scrollbar(p,orient="horizontal",command=self.trend_tree.xview)
  self.trend_tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
  self.trend_tree.pack(fill="both",expand=True,side="left",padx=(10,0),pady=(0,10));y.pack(fill="y",side="right",pady=(0,10));x.pack(fill="x",side="bottom",padx=10)

 def _selected_celebrity_style_ids(self):
  if not hasattr(self,"celeb_style_tree"):return []
  out=[]
  for x in self.celeb_style_tree.selection():
   try:out.append(int(x))
   except Exception:
    try:
     vals=self.celeb_style_tree.item(x,"values");out.append(int(vals[0]))
    except Exception:pass
  return out

 def celebrity_style_run(self,stage):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  days=int(re.sub(r"\D","",self.celeb_period_var.get() if hasattr(self,"celeb_period_var") else "3") or 3)
  name=(self.celeb_name_var.get().strip() if hasattr(self,"celeb_name_var") else "")
  if stage=="collect_manual" and not name:return messagebox.showwarning("연예인 이름 필요","직접 검색할 연예인 이름을 입력하세요.")
  ids=self._selected_celebrity_style_ids();self.stop=False
  def job():
   try:
    def cb(done,total,msg):
     pct=max(0,min(100,int(float(done)/max(1,float(total))*100)));self.q.put(("celeb",pct,msg))
    if stage=="collect_auto":
     self.q.put(("celeb",2,f"최근 {days}일 연예인 착장 자동 수집 준비"));res=celebrity_style_adapter.collect_latest(days=days,celebrity="",progress=cb)
    elif stage=="collect_manual":
     self.q.put(("celeb",2,f"{name} 최근 {days}일 착장 검색 준비"));res=celebrity_style_adapter.collect_latest(days=days,celebrity=name,progress=cb)
    elif stage=="images_selected_or_all":
     self.q.put(("celeb",2,"연예인명·행사·날짜 기반 착장 관련 이미지 수집 준비"));res=celebrity_style_adapter.collect_reference_images(candidate_ids=ids or None,progress=cb)
    elif stage=="analyze_selected_or_all":
     self.q.put(("celeb",2,"인물·행사·날짜·출처·이미지 클러스터 교차검증 준비"));res=celebrity_style_adapter.analyze_unfinished(candidate_ids=ids or None,progress=cb)
    elif stage=="match_selected_or_all":
     self.q.put(("celeb",2,"착장 아이템 정확상품/유사스타일 검증 준비"));res=celebrity_style_adapter.match_products(candidate_ids=ids or None,progress=cb)
    elif stage=="draft_selected_or_all":
     self.q.put(("celeb",2,"검증 근거 기반 착장 블로그 원고 생성 준비"));res=celebrity_style_adapter.generate_drafts(candidate_ids=ids or None,progress=cb)
    elif stage=="full":
     self.q.put(("celeb",2,"착장 전체 자동 파이프라인 준비"));res=celebrity_style_adapter.run_full(days=days,celebrity=name,progress=cb)
    else:raise RuntimeError("알 수 없는 연예인 착장 작업: "+str(stage))
    self.q.put(("celeb",100,res.get("message") or "연예인 착장 작업 완료"));self.q.put(("refresh",));self.emit("[연예인 착장] "+str(res.get("message") or res))
   except Exception as e:
    self.q.put(("celeb",0,"연예인 착장 작업 실패: "+str(e)));self.emit("[연예인 착장 오류] "+str(e));self.q.put(("refresh",))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def refresh_celebrity_styles(self):
  if not hasattr(self,"celeb_style_tree"):return
  rows=celebrity_style_adapter.candidate_rows(300)
  self.celeb_style_tree.delete(*self.celeb_style_tree.get_children())
  analyzed=matched=drafts=0
  for r in rows:
   status=str(r.get("status") or "")
   if status not in {"수집완료","착장근거부족"}:analyzed+=1
   if int(r.get("matched_count") or 0)>0:matched+=1
   if r.get("draft_title"):drafts+=1
   vals=(r.get("id"),r.get("celebrity_name") or "-",r.get("event_date") or "날짜미확인",r.get("look_type") or "-",r.get("independent_source_count") or 0,
         f"{float(r.get('confidence_score') or 0):.0f}",r.get("item_count") or 0,r.get("matched_count") or 0,status or "-")
   try:self.celeb_style_tree.insert("","end",iid=str(r.get("id")),values=vals)
   except Exception:self.celeb_style_tree.insert("","end",values=vals)
  if hasattr(self,"celeb_style_summary"):self.celeb_style_summary.set(f"후보 {len(rows)} · 분석 {analyzed} · 상품매칭 {matched} · 원고 {drafts}")
  try:
   vs=celebrity_style_adapter.vision_status();self.celeb_policy_var.set(vs.get("message") or "Vision 상태 미확인")
  except Exception:pass

 def show_celebrity_style_detail(self):
  ids=self._selected_celebrity_style_ids()
  if not ids or not hasattr(self,"celeb_style_detail"):return
  d=celebrity_style_adapter.candidate_detail(ids[0])
  if not d:return
  lines=[f"[{d.get('celebrity_name')}] {d.get('look_type')} · {d.get('event_date') or '날짜미확인'}",
         f"상태: {d.get('status')} / 신뢰점수: {float(d.get('confidence_score') or 0):.1f} / 독립출처: {d.get('independent_source_count')}",
         "", "■ 착장 아이템"]
  for it in d.get("items") or []:
   exact="정확 제품 주장 가능" if int(it.get("exact_claim_allowed") or 0) else "정확 제품 단정 금지"
   prod=(it.get("matched_name") or "미매칭")+((f" · {int(it.get('matched_price') or 0):,}원") if it.get("matched_price") else "")
   lines.append(f"- {it.get('item_category')}: {it.get('brand') or ''} {it.get('model_name') or ''} {it.get('item_description') or ''} / {it.get('color') or '-'}")
   lines.append(f"  근거={it.get('evidence_level')} {float(it.get('confidence_score') or 0):.0f}점 · {exact} · 상품={it.get('match_type')} · {prod}")
  lines.extend(["", "■ 확인 출처"])
  for s in (d.get("sources") or [])[:10]:lines.append(f"- [{s.get('source_type')}] {s.get('title') or '-'}\n  {s.get('url') or s.get('naver_url') or ''}")
  if d.get("vision"):
   v=d.get("vision") or {};lines.extend(["",f"■ Vision 보조: {v.get('model') or '-'} / 시도={v.get('attempted')} / 브랜드 확정용 아님"])
  if d.get("draft_title"):
   lines.extend(["", "■ 생성 원고", d.get("draft_title") or "", ""]);
   try:
    blocks=json.loads(d.get("draft_body") or "[]")
    for b in blocks:
     if b.get("type")=="heading":lines.append("\n"+str(b.get("text") or ""))
     elif b.get("text"):lines.append(str(b.get("text")))
     else:lines.extend(str(x) for x in (b.get("lines") or []))
   except Exception:lines.append(str(d.get("draft_body") or ""))
   lines.extend(["", "태그: "+str(d.get("draft_tags") or "")])
  self.celeb_style_detail.delete("1.0","end");self.celeb_style_detail.insert("1.0","\n".join(lines))

 def celebrity_style_promote_selected(self):
  ids=self._selected_celebrity_style_ids()
  if not ids:return messagebox.showwarning("선택 필요","작성물로 연동할 착장 후보를 선택하세요.")
  try:
   r=celebrity_style_adapter.promote_candidate(ids[0]);self.refresh();messagebox.showinfo("작성물 연동",r.get("message")+"\n\n이제 작성물 관리에서 해당 상품을 확인하고, 필요하면 동일상품 사진 3장 → 텍스트/이미지 임시저장을 실행할 수 있습니다.")
  except Exception as e:messagebox.showerror("작성물 연동 실패",str(e))

 def celebrity_style_blog_selected(self):
  ids=self._selected_celebrity_style_ids()
  if not ids:return messagebox.showwarning("선택 필요","임시저장할 착장 원고를 선택하세요.")
  try:
   d=celebrity_style_adapter.candidate_detail(ids[0]);pid=int((d or {}).get("promoted_product_id") or 0)
   if pid<=0:
    r=celebrity_style_adapter.promote_candidate(ids[0]);pid=int(r.get("product_id") or 0);self.refresh()
   if pid<=0:raise RuntimeError("작성물 연동 상품 ID를 만들지 못했습니다.")
   self.blog_single("text_only",blog_context={"product_ids":[pid]})
  except Exception as e:messagebox.showerror("착장 원고 임시저장 실패",str(e))

 def open_celebrity_style_csv(self):
  try:
   paths=celebrity_style_adapter.export_paths();p=Path(paths.get("candidates") or "")
   if p.exists():
    try:os.startfile(str(p))
    except Exception:messagebox.showinfo("연예인 착장 CSV",str(p))
  except Exception as e:messagebox.showerror("CSV 열기 실패",str(e))

 def ollama_vision_setup(self):
  try:subprocess.Popen(["cmd","/c","94_OLLAMA_VISION_AUTO_SETUP.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("Qwen3-VL 설치 실행 실패",str(e))

 def trend_product_tab(self):
  p=self.tabs["트렌드→쿠팡 추출"]
  bar=ttk.Frame(p,padding=8);bar.pack(fill="x")
  ttk.Button(bar,text="▶ 트렌드 → 쿠팡 인기상품 추출",command=self.trend_coupang_extract).pack(side="left")
  ttk.Button(bar,text="새로고침",command=self.refresh_trend_products).pack(side="left",padx=4)
  ttk.Button(bar,text="추출 CSV 열기",command=self.open_trend_coupang_csv).pack(side="left",padx=4)
  self.trend_product_summary=tk.StringVar(value="트렌드→쿠팡 추출 대기")
  ttk.Label(bar,textvariable=self.trend_product_summary,font=("Malgun Gothic",10,"bold")).pack(side="right")
  ttk.Label(p,text="아이템스카우트+네이버 데이터랩을 같은 카테고리/키워드로 통합한 뒤 카테고리별 최대 30개를 쿠팡에서 검색합니다. 리뷰·최근 구매/판매·평점·검색위치·검색어 일치도를 종합해 키워드당 대표상품 1개를 선정하고, 같은 쿠팡 상품은 하나로 합칩니다. 선정 상품은 기존 상품 DB에 들어가므로 ② 제목·본문·태그 버튼을 그대로 사용하면 됩니다.",foreground="#555555",wraplength=1380).pack(anchor="w",padx=10,pady=(0,6))
  cols=("cat","keyword","sources","product","price","reviews","purchases","rating","score","status")
  self.trend_product_tree=ttk.Treeview(p,columns=cols,show="headings")
  for c,h,w in [("cat","카테고리",110),("keyword","트렌드 키워드",180),("sources","트렌드 출처",180),("product","쿠팡 대표 인기상품",440),("price","가격",90),("reviews","리뷰",80),("purchases","구매/판매",90),("rating","평점",65),("score","인기점수",80),("status","연동상태",120)]:
   self.trend_product_tree.heading(c,text=h);self.trend_product_tree.column(c,width=w,anchor="w")
  y=ttk.Scrollbar(p,orient="vertical",command=self.trend_product_tree.yview);x=ttk.Scrollbar(p,orient="horizontal",command=self.trend_product_tree.xview)
  self.trend_product_tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
  self.trend_product_tree.pack(fill="both",expand=True,side="left",padx=(10,0),pady=(0,10));y.pack(fill="y",side="right",pady=(0,10));x.pack(fill="x",side="bottom",padx=10)

 def refresh_trend_products(self):
  if not hasattr(self,"trend_product_tree"):return
  for x in self.trend_product_tree.get_children():self.trend_product_tree.delete(x)
  rows=trend_coupang_adapter.selected_rows();linked=0
  for r in rows:
   if int(r.get("product_id") or 0)>0:linked+=1
   self.trend_product_tree.insert("","end",values=(r.get("category"),r.get("keyword"),r.get("trend_sources"),r.get("coupang_name"),
    f"{int(r.get('coupang_price') or 0):,}" if r.get("coupang_price") else "-",f"{int(r.get('review_count') or 0):,}",f"{int(r.get('purchase_count') or 0):,}",
    f"{float(r.get('rating') or 0):.1f}" if r.get("rating") else "-",f"{float(r.get('popularity_score') or 0):.1f}",r.get("status")))
  self.trend_product_summary.set(f"쿠팡 대표상품 {len(rows)}개 · 기존 제목/본문/태그 파이프라인 연동 {linked}개")

 def trend_coupang_extract(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.stop=False
  def job():
   try:
    self.q.put(("trend",2,"트렌드 통합 → 쿠팡 인기상품 추출 준비"))
    def cb(done,total,msg):self.q.put(("trend",int(done/max(1,total)*100),msg))
    result=trend_coupang_adapter.extract_popular_products(progress=cb)
    self.q.put(("trend",100,result.get("message") or "트렌드→쿠팡 추출 완료"));self.q.put(("refresh",))
    self.emit("[트렌드→쿠팡] "+str(result.get("message") or result))
   except Exception as e:
    self.q.put(("trend",0,"트렌드→쿠팡 추출 실패: "+str(e)));self.emit("[트렌드→쿠팡 오류] "+str(e))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def open_trend_coupang_csv(self):
  p=ROOT/"outputs"/"trend_to_coupang_popular_products.csv"
  if not p.exists():return messagebox.showinfo("추출 CSV","아직 추출 결과가 없습니다.")
  try:os.startfile(str(p))
  except Exception:messagebox.showinfo("추출 CSV",str(p))

 def refresh_trends(self):
  if not hasattr(self,"trend_tree"):return
  for x in self.trend_tree.get_children():self.trend_tree.delete(x)
  raw_counts={};merged_counts={}
  for source in ("아이템스카우트","네이버데이터랩"):
   con=sqlite3.connect(DB)
   try:raw_counts[source]=int(con.execute("SELECT COUNT(*) FROM trend_candidates WHERE source=?",(source,)).fetchone()[0])
   finally:con.close()
   rows=trend_collection_adapter.merged_rows(source);merged_counts[source]=len(rows)
   for r in rows:
    self.trend_tree.insert("","end",values=(r["source"],r["age_group"],r["category"],r["rank_no"],r["keyword"],r["age_rank"],r["captured_at"],r["status"]))
  linked=len(trend_coupang_adapter.selected_rows())
  if hasattr(self,"collect_trend_summary"):
   self.collect_trend_summary.set(f"아이템스카우트 {merged_counts.get('아이템스카우트',0)} · 네이버 데이터랩 {merged_counts.get('네이버데이터랩',0)} · 쿠팡 연결 {linked}")
  self.trend_summary.set(
   f"아이템스카우트 통합 {merged_counts.get('아이템스카우트',0)} (원본 {raw_counts.get('아이템스카우트',0)}/360) · "
   f"네이버 데이터랩 통합 {merged_counts.get('네이버데이터랩',0)} (원본 {raw_counts.get('네이버데이터랩',0)}/360)"
  )

 def trend_collect(self,source):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.stop=False
  def job():
   try:
    self.q.put(("trend",2,f"{source} 수집 준비 중"))
    def cb(done,total,msg):
     pct=int(done/max(1,total)*100);self.q.put(("trend",pct,msg))
    result=trend_collection_adapter.collect_source(source,progress=cb)
    self.q.put(("trend",100,result.get("message") or f"{source} 수집 완료"))
    self.q.put(("refresh",));self.emit(f"[추가 트렌드] {source}: {result.get('count',0)}/{result.get('target',360)}")
    if result.get("errors"):self.emit("[추가 트렌드 부분수집] "+" | ".join(result.get("errors")[:12]))
   except Exception as e:
    self.q.put(("trend",0,f"{source} 실패: {e}"));self.emit(f"[추가 트렌드 오류] {source}: {e}")
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def export_trends(self):
  p=filedialog.asksaveasfilename(defaultextension=".csv",initialfile="itemscout_naver_datalab_age_trends_MERGED.csv")
  if not p:return
  rows=[]
  for source in ("아이템스카우트","네이버데이터랩"):rows.extend(trend_collection_adapter.merged_rows(source))
  with open(p,"w",newline="",encoding="utf-8-sig") as f:
   w=csv.writer(f);w.writerow(["수집처","연령그룹","연령코드","카테고리","통합순위","키워드","연령별순위","수집시각","페이지URL","상태"])
   for r in rows:w.writerow([r["source"],r["age_group"],r["age_codes"],r["category"],r["rank_no"],r["keyword"],r["age_rank"],r["captured_at"],r["page_url"],r["status"]])

 def change_top_page(self,delta):
  total=self._top_product_count();pages=max(1,(total+self.top_page_size-1)//self.top_page_size)
  self.top_page=max(1,min(pages,self.top_page+delta));self.refresh_top100()

 def _top_product_count(self):
  con=sqlite3.connect(DB)
  try:return int(con.execute("SELECT COUNT(*) FROM products WHERE status NOT LIKE '추천제외:%'").fetchone()[0])
  finally:con.close()

 def refresh_top100(self):
  for x in self.tree.get_children():self.tree.delete(x)
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
  try:
   total=int(con.execute("SELECT COUNT(*) FROM products WHERE status NOT LIKE '추천제외:%'").fetchone()[0]);pages=max(1,(total+self.top_page_size-1)//self.top_page_size)
   self.top_page=max(1,min(self.top_page,pages));off=(self.top_page-1)*self.top_page_size
   rows=con.execute("SELECT * FROM products WHERE status NOT LIKE '추천제외:%' ORDER BY product_no,id LIMIT ? OFFSET ?",(self.top_page_size,off)).fetchall()
   for r in rows:
    pr=" / ".join("-" if not x else f"{x:,}" for x in [r["price_toss"],r["price_coupang"],r["price_naver"]])
    src=(r["source_platform"] or "-").replace("네이버쇼핑","네이버")
    iv=int(r["image_verified_count"] or 0) if "image_verified_count" in r.keys() else sum(1 for x in [r["image1"],r["image2"],r["image3"]] if x)
    pv=int(r["price_verified_sites"] or 0) if "price_verified_sites" in r.keys() else sum(1 for x in [r["price_toss"],r["price_coupang"],r["price_naver"]] if x)
    pc=int(r["price_image_verified_sites"] or 0) if "price_image_verified_sites" in r.keys() else 0
    if int(r["already_posted"] or 0):posted_state="기존게시·"+("수동" if str(r["already_posted_method"] or "")=="MANUAL" else "자동")
    elif int(r["already_posted_review"] or 0):posted_state="자동확인필요"
    elif int(r["already_posted_auto_ignored"] or 0):posted_state="미게시·수동확인"
    else:posted_state="남은 제품"
    self.tree.insert("", "end",iid=str(r["id"]),values=(r["product_no"],r["name"],r["category"],src,f"{r['score']:.0f}",posted_state,r["status"],f"사진 {iv}/3 · 가격 {pv}/3 · 결합 {pc}/3",pr,"✅" if r["approved"] else ""))
   a=off+1 if total else 0;b=min(total,off+self.top_page_size)
   self.top_page_label.set(f"{self.top_page} / {pages} 페이지 · {a}~{b} · 총 {total}")
  finally:con.close()

 def refresh_sources(self):
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
  try:
   counts={}
   for platform,t in self.source_trees.items():
    for x in t.get_children():t.delete(x)
    rows=con.execute("SELECT * FROM candidates WHERE platform=? ORDER BY category,rank_no,id",(platform,)).fetchall();counts[platform]=len(rows)
    for r in rows:
     price="-" if not r["price"] else f"{int(r['price']):,}원"
     t.insert("","end",values=(r["category"],r["rank_no"],r["name"],price,r["url"] or ""))
    self.source_count_labels[platform].set(f"{platform.replace('네이버쇼핑','네이버')}: {len(rows)}/180")
    if hasattr(self,"collect_source_metric_vars") and platform in self.collect_source_metric_vars:
     self.collect_source_metric_vars[platform].set(f"{len(rows)}/180")
  finally:con.close()
  return counts

 def refresh_coverage(self,counts=None):
  counts=counts or {};cfg=settings();cats=cfg.get("categories",[]);plats=["쿠팡","토스쇼핑","네이버쇼핑"]
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
  lines=["[수집 COVERAGE]","540개를 모두 채우지 못해도 실제 확보된 전체 데이터만으로 Top100(100개 미만이면 Top N)을 생성합니다.",""]
  allok=True;grand=0
  try:
   for p in plats:
    lines.append(f"[{p.replace('네이버쇼핑','네이버')}] target 180")
    stotal=0
    for cat in cats:
     n=int(con.execute("SELECT COUNT(*) FROM candidates WHERE platform=? AND category=?",(p,cat)).fetchone()[0]);stotal+=n
     ok=n==30;allok=allok and ok;lines.append(f"  {'PASS' if ok else 'FAIL'}  {cat}: {n}/30")
    grand+=stotal;lines.append(f"  TOTAL: {stotal}/180\n")
  finally:con.close()
  enough=grand>0
  state="COMPLETE" if allok and grand==540 else ("PARTIAL ACCEPTED" if enough else "INSUFFICIENT")
  lines.append(f"GRAND TOTAL: {grand}/540 · {state}")
  out=ROOT/"outputs"/"strict540_category_coverage.json"
  if out.exists():
   try:
    obj=json.loads(out.read_text(encoding="utf-8"));errs=obj.get("errors") or []
    if errs:lines.extend(["","최근 수집 오류:"]+["- "+str(x) for x in errs[-18:]])
    cov=obj.get("coverage") or {};bad=[]
    toss_order=(cfg.get("toss_category_order") or cats)
    toss_gate=[]
    for cat in toss_order:
     rec=cov.get(f"토스쇼핑|{cat}") or {}
     if not rec:continue
     before=rec.get("toss_checked_before_collect") or [];after=rec.get("toss_checked_after_collect") or []
     api_mode=rec.get("toss_collection_mode")=="api"
     gates=bool(rec.get("toss_api_confirmed")) if api_mode else (bool(rec.get("toss_product_lookup_confirmed")) and bool(rec.get("toss_single_checkbox_confirmed")) and bool(rec.get("toss_uncheck_after_collect")) and len(before)==1 and len(after)==0)
     detail=rec.get("route_detail") or rec.get("error") or ""
     route="Sharelink API · 홈페이지 미사용" if api_mode else f"수집직전 {before or '[]'} / 수집후 {after or '[]'}"
     toss_gate.append(f"  {'PASS' if gates else 'FAIL'} {cat} -> {rec.get('site_category') or '-'} : {route}"+(f" / 단계: {detail}" if detail else ""))
    if toss_gate:lines.extend(["","[토스 수집 경로 검증]"]+toss_gate)
    for key,rec in cov.items():
     if int(rec.get("count",0))>=int(rec.get("target",30)) and rec.get("status")=="ok":continue
     dbg=rec.get("debug") or {};shot=rec.get("full_screenshot") or ""
     detail=rec.get("route_detail") or rec.get("error") or ""
     bad.append(f"- {key}: status={rec.get('status')} count={rec.get('count')}/{rec.get('target')} URL={dbg.get('url') or rec.get('page_url') or '-'}"+(f" / 단계={detail}" if detail else ""))
     if shot:bad.append(f"    화면캡처: {shot}")
     if dbg.get("body_head"):bad.append("    화면텍스트: "+str(dbg.get("body_head"))[:260])
    if bad:lines.extend(["","실패 화면 진단:"]+bad[:54])
   except Exception:pass
  self.coverage_text.delete("1.0","end");self.coverage_text.insert("1.0","\n".join(lines))
  self.collect_summary.set(f"원천 {grand}/540 ({state}) · 쿠팡 {counts.get('쿠팡',0)}/180 · 토스 {counts.get('토스쇼핑',0)}/180 · 네이버 {counts.get('네이버쇼핑',0)}/180 · TOP {self._top_product_count()}/100")

 def open_collection_diagnostics(self):
  p=ROOT/"evidence"/"collection_540";p.mkdir(parents=True,exist_ok=True)
  try:os.startfile(str(p))
  except Exception:
   try:subprocess.Popen(["explorer.exe",str(p)])
   except Exception as e:messagebox.showerror("수집 진단 폴더",str(e))

 def open_image_diagnostics(self):
  out=ROOT/"outputs"
  repair=out/"image_repair_diagnostic.csv"
  collect=out/"image_collect_diagnostic.csv"
  p=repair if repair.exists() else collect
  if not p.exists():
   messagebox.showinfo("이미지 실패 진단","아직 이미지 진단 CSV가 없습니다.\n사진 3장 가져오기 또는 사진 보강만을 먼저 실행하세요.")
   return
  try:os.startfile(str(p))
  except Exception:
   try:subprocess.Popen(["explorer.exe","/select,",str(p)])
   except Exception as e:messagebox.showerror("이미지 실패 진단",str(e))

 def preview(self):
  p=self.tabs["결과 미리보기"];self.prev=tk.Text(p,font=("Malgun Gothic",10),wrap="word");self.prev.pack(fill="both",expand=True,padx=10,pady=10)

 def verify_tab(self):
  p=self.tabs["이미지·가격 검증"]
  top=ttk.Frame(p,padding=10);top.pack(fill="x")
  self.verify_product_label=tk.StringVar(value="TOP100에서 상품을 선택하세요.")
  ttk.Label(top,textvariable=self.verify_product_label,font=("Malgun Gothic",11,"bold")).pack(side="left")
  ttk.Button(top,text="새로고침",command=self.refresh_selected_verification).pack(side="right")
  ttk.Button(top,text="증거 폴더 열기",command=self.open_selected_evidence).pack(side="right",padx=4)
  ttk.Button(top,text="가격비교 이미지 열기",command=self.open_selected_compare_image).pack(side="right",padx=4)
  ttk.Button(top,text="선택 상품 안전 가격 재검증",command=self.verify_price_selected).pack(side="right",padx=4)
  ttk.Button(top,text="선택 상품만 라이브 갱신",command=self.verify_price_selected_live).pack(side="right",padx=4)
  ttk.Button(top,text="선택 상품 이미지 3장 재검증",command=self.verify_images_selected).pack(side="right",padx=4)
  ttk.Button(top,text="실전 예시 3상품 가격테스트",command=self.live_sample_price_test).pack(side="right",padx=4)

  imgf=ttk.LabelFrame(p,text="동일상품 실제 이미지 3장",padding=8);imgf.pack(fill="x",padx=10,pady=(0,8))
  self.image_verify_text=tk.Text(imgf,height=8,font=("Consolas",9),wrap="word");self.image_verify_text.pack(fill="x")
  pf=ttk.LabelFrame(p,text="쿠팡 · 네이버 · 토스 가격 비교표 (수집시각/API 기준)",padding=8);pf.pack(fill="both",expand=True,padx=10,pady=(0,10))
  cols=("site","state","price","source","captured","match","product","url")
  self.price_verify_tree=ttk.Treeview(pf,columns=cols,show="headings")
  for c,h,w in [("site","사이트",90),("state","검증상태",120),("price","확인 가격",110),("source","수집경로",190),("captured","확인시각",150),("match","일치도",70),("product","실제 확인 상품명",430),("url","상품 URL",430)]:
   self.price_verify_tree.heading(c,text=h);self.price_verify_tree.column(c,width=w,anchor="w")
  self.price_verify_tree.pack(fill="both",expand=True)
  self.price_verify_note=tk.StringVar(value="가격: 쿠팡 Partners API + NAVER 쇼핑 검색 API + Toss Sharelink 카테고리 API 우선. 판매처 미판매는 전체 단계를 중단하지 않고 미확인으로 표시합니다.")
  ttk.Label(pf,textvariable=self.price_verify_note,foreground="#666666").pack(anchor="w",pady=(6,0))

 def refresh_selected_verification(self):
  pid=self._selected_product_id()
  if not pid:return
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;r=con.execute("SELECT * FROM products WHERE id=?",(pid,)).fetchone();con.close()
  if not r:return
  self.verify_product_label.set(f"TOP {r['product_no']} · {r['name']}")
  self.image_verify_text.delete("1.0","end")
  iv=int(r["image_verified_count"] or 0) if "image_verified_count" in r.keys() else 0
  lines=[f"검증 이미지: {iv}/3",f"1: {r['image1'] or '-'}",f"2: {r['image2'] or '-'}",f"3: {r['image3'] or '-'}",f"증거: {r['image_evidence_json'] or '-'}"]
  self.image_verify_text.insert("1.0","\n".join(lines))
  for x in self.price_verify_tree.get_children():self.price_verify_tree.delete(x)
  records=[];ep=r["price_evidence_json"] if "price_evidence_json" in r.keys() else None
  if ep and Path(ep).exists():
   try:records=json.loads(Path(ep).read_text(encoding="utf-8")).get("records") or []
   except Exception:records=[]
  by={x.get("site"):x for x in records}
  for site in ["쿠팡","네이버쇼핑","토스쇼핑"]:
   x=by.get(site,{"site":site});ok=bool(x.get("verified") and x.get("price"));price=f"{int(x['price']):,}원" if ok else "-"
   imgok=bool(ok and x.get("image_path") and Path(x.get("image_path")).exists())
   state=("PASS+IMG" if imgok else ("PRICE PASS / IMG FAIL" if ok else "FAIL"))
   match=f"{float(x.get('match') or 0)*100:.0f}%" if x.get("match") else "-"
   source_map={"same_run_discovery_snapshot":"540 수집 스냅샷","coupang_partners_api":"쿠팡 Partners API","toss_sharelink_open_api":"토스 Sharelink Open API","normal_chrome_extension":"선택 라이브 Chrome","Android/Appium":"선택 라이브 Toss 앱","safe_pc":"선택 라이브 PC"}
   source=source_map.get(str(x.get("source") or ""),str(x.get("source") or "-"))
   captured=str(x.get("captured_at") or x.get("checked_at") or "-")
   self.price_verify_tree.insert("","end",values=(site.replace("네이버쇼핑","네이버"),state,price,source,captured,match,x.get("product_name") or x.get("reason") or "-",x.get("url") or ""))
  pv=int(r["price_verified_sites"] or 0) if "price_verified_sites" in r.keys() else 0
  pc=int(r["price_image_verified_sites"] or 0) if "price_image_verified_sites" in r.keys() else 0
  self.price_verify_note.set(f"가격 검증 {pv}/3 · 가격+이미지 증거 {pc}/3 · 비교 이미지: {r['price_compare_image'] or '-'} · 쿠팡 사진은 쿠팡 API/스냅샷/직접 상품페이지 갤러리만 사용")

 def open_selected_compare_image(self):
  pid=self._selected_product_id()
  if not pid:return messagebox.showwarning("가격비교 이미지","먼저 TOP100 상품을 선택하세요.")
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;r=con.execute("SELECT price_compare_image FROM products WHERE id=?",(pid,)).fetchone();con.close()
  path=Path(r["price_compare_image"] or "") if r else None
  if not path or not path.exists():return messagebox.showwarning("가격비교 이미지","아직 생성된 가격비교 이미지가 없습니다. ④ 가격+이미지 검증을 먼저 실행하세요.")
  try:os.startfile(str(path))
  except Exception:
   try:subprocess.Popen(["explorer.exe",str(path)])
   except Exception as e:messagebox.showerror("가격비교 이미지",str(e))

 def verify_images_selected(self):
  pid=self._selected_product_id()
  if not pid:return messagebox.showwarning("이미지 검증","먼저 TOP100 상품을 선택하세요.")
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    self.emit("선택 상품 실제 이미지 3장 재검증 시작")
    content_adapter.capture_product_images(pid,progress=self.progress("images"));self.q.put(("refresh",));self.emit("선택 상품 이미지 재검증 완료")
   except Exception as e:self.emit("선택 상품 이미지 검증 실패: "+str(e))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def image_repairs_only(self):
  """Run stage ③ only for rows with missing physical image files."""
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    self.q.put(("step","images","사진 보강 대상 확인 중",5));self.emit("사진 보강 대상만 재시도 시작")
    result=image_adapter.run_repairs(progress=self.progress("images"))
    ok=bool(result.get("stage_ok",True));msg=str(result.get("message") or "사진 보강 완료")
    self.q.put(("step","images","완료" if ok else msg,100));self.q.put(("refresh",));self.emit(msg)
   except Exception as e:
    self.q.put(("step","images","보강 실패",0));self.q.put(("refresh",));self.emit("사진 보강 실행 실패: "+str(e))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def sharelink_images_only(self):
  """Generate affiliate links only after all three product images are verified."""
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    h=coupang_sharelink_adapter.health()
    if not h.get("ready"):raise RuntimeError(h.get("message") or "쿠팡 Partners API 키가 필요합니다.")
    self.q.put(("step","content","사진3장 성공 상품 쉐어링크 확인 중",5));self.emit("사진3장 성공 상품만 쿠팡 쉐어링크 생성 시작")
    result=coupang_sharelink_adapter.run(progress=self.progress("content"))
    ok=bool(result.get("stage_ok",True));msg=str(result.get("message") or "쉐어링크 처리 완료")
    self.q.put(("step","content","쉐어링크 완료" if ok else msg,100));self.q.put(("refresh",));self.emit(msg)
   except Exception as e:
    self.q.put(("step","content","쉐어링크 실패",0));self.q.put(("refresh",));self.emit("쉐어링크 실행 실패: "+str(e))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def verify_price_selected(self):
  pid=self._selected_product_id()
  if not pid:return messagebox.showwarning("가격 검증","먼저 TOP100 상품을 선택하세요.")
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    self.emit("선택 상품 안전 가격 재검증 시작 · 추가 쇼핑검색 0회 기본")
    price_adapter.verify_product(pid,progress=self.progress("price"));self.q.put(("refresh",));self.emit("선택 상품 안전 가격 재검증 완료")
   except Exception as e:self.emit("선택 상품 가격 검증 실패: "+str(e))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def verify_price_selected_live(self):
  pid=self._selected_product_id()
  if not pid:return messagebox.showwarning("라이브 가격 갱신","먼저 TOP100 상품을 선택하세요.")
  if not messagebox.askyesno("선택 상품만 라이브 갱신","선택한 상품 1개에 한해 네이버/토스 검색 페이지를 실제로 열어 가격을 갱신할 수 있습니다. 사이트 접근 제한이 다시 발생할 수 있으며 우회하지 않습니다. 계속할까요?"):
   return
  def job():
   try:
    self.emit("선택 상품 1개 라이브 가격 갱신 시작")
    price_adapter.verify_product_live_browser(pid,progress=self.progress("price"));self.q.put(("refresh",));self.emit("선택 상품 라이브 가격 갱신 완료")
   except Exception as e:self.emit("라이브 가격 갱신 실패: "+str(e))
  threading.Thread(target=job,daemon=True).start()

 def live_sample_price_test(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  try:
   subprocess.Popen(["cmd","/c","31_LIVE_SAMPLE_3PRODUCT_PRICE_TEST.cmd"],cwd=ROOT)
   messagebox.showinfo("실전 가격테스트","일반 Chrome에서 3개 예시 상품을 쿠팡·네이버·토스 순으로 검증합니다.\n토스 로그인 화면이 나오면 현재 사용하는 계정으로 로그인한 뒤 다시 테스트를 실행하세요.\n결과는 outputs/live_sample_3product_price_table.csv 에 저장됩니다.")
  except Exception as e:messagebox.showerror("실전 가격테스트",str(e))

 def open_selected_evidence(self):
  pid=self._selected_product_id()
  if not pid:return
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;r=con.execute("SELECT product_no,id FROM products WHERE id=?",(pid,)).fetchone();con.close()
  if not r:return
  p=EVIDENCE/f"{int(r['product_no'] or r['id']):02d}";p.mkdir(parents=True,exist_ok=True)
  try:os.startfile(str(p))
  except Exception:pass

 def video_tab(self):
  p=self.tabs["AI 제품영상"]
  top=ttk.Frame(p,padding=10);top.pack(fill="x")
  ttk.Label(top,text="Ollama 무료 영상기획 + ComfyUI 제품영상",font=("Malgun Gothic",13,"bold")).pack(side="left")
  self.video_include=tk.BooleanVar(value=False)
  ttk.Checkbutton(top,text="전체 순차 실행에 AI영상 포함",variable=self.video_include).pack(side="right")

  select=ttk.LabelFrame(p,text="영상 기획할 제품 선택",padding=8);select.pack(fill="x",padx=10,pady=(0,8))
  self.video_product_var=tk.StringVar(value="")
  self.video_product_combo=ttk.Combobox(select,textvariable=self.video_product_var,state="readonly",width=100)
  self.video_product_combo.pack(side="left",fill="x",expand=True)
  ttk.Button(select,text="수집된 상품 보기",command=lambda:self.show_page("collected")).pack(side="right",padx=(8,0))

  bar=ttk.Frame(p,padding=(10,0,10,8));bar.pack(fill="x")
  ttk.Button(bar,text="① Ollama 영상기획 + 12컷 생성",style="Accent.TButton",command=self.video_storyboard).pack(side="left")
  ttk.Button(bar,text="② 선택 제품 60초 영상 만들기",command=self.video_generate_selected).pack(side="left",padx=4)
  ttk.Button(bar,text="전체 제품 영상 순차 생성",command=self.video_generate_all).pack(side="left")
  ttk.Button(bar,text="영상 출력 폴더",command=self.open_video_folder).pack(side="right")
  ttk.Button(bar,text="ComfyUI 영상엔진 자동설정",command=self.video_auto_setup).pack(side="right",padx=4)

  info=ttk.LabelFrame(p,text="기획 / 렌더링 진행 상태",padding=8);info.pack(fill="x",padx=10)
  self.video_info=tk.StringVar(value="제품을 선택하면 Ollama가 영상 콘셉트·타깃·훅·CTA·12컷을 무료로 기획합니다.")
  ttk.Label(info,textvariable=self.video_info,wraplength=1200).pack(anchor="w")
  self.video_pb=ttk.Progressbar(info,maximum=100);self.video_pb.pack(fill="x",pady=(6,0))
  self.video_plan_summary=tk.StringVar(value="영상기획 미생성")
  ttk.Label(info,textvariable=self.video_plan_summary,wraplength=1200,foreground="#555555").pack(anchor="w",pady=(6,0))

  cols=("scene","time","purpose","caption","prompt")
  self.video_tree=ttk.Treeview(p,columns=cols,show="headings")
  for c,h,w in [("scene","컷",45),("time","시간",75),("purpose","장면 목적",150),("caption","자막",260),("prompt","AI 영상 프롬프트 요약",650)]:
   self.video_tree.heading(c,text=h);self.video_tree.column(c,width=w,anchor="w")
  self.video_tree.pack(fill="both",expand=True,padx=10,pady=10)

  foot=ttk.Label(p,text="① 영상기획은 Ollama Qwen3 로컬 AI만 사용하므로 API 비용이 없습니다. ② 실제 영상 렌더링은 ComfyUI + Image-to-Video + FFmpeg를 사용합니다. 제품사진을 reference로 고정해 동일 상품 유지에 우선순위를 둡니다.",foreground="#666666",wraplength=1320)
  foot.pack(anchor="w",padx=10,pady=(0,8))

 def performance_tab(self):
  p=self.tabs["성능/최적화"]
  top=ttk.Frame(p,padding=10);top.pack(fill="x")
  ttk.Label(top,text="실행 성능 설정",font=("Malgun Gothic",13,"bold")).pack(side="left")
  ttk.Button(top,text="성능 로그 새로고침",command=self.load_perf_log).pack(side="right")
  split=ttk.Panedwindow(p,orient="horizontal");split.pack(fill="both",expand=True,padx=10,pady=(0,10))
  left=ttk.Frame(split);right=ttk.Frame(split);split.add(left,weight=1);split.add(right,weight=2)
  pcfg=ROOT/"data"/"performance.json"
  self.perf_text=tk.Text(left,font=("Consolas",10),undo=True);self.perf_text.pack(fill="both",expand=True)
  self.perf_text.insert("1.0",pcfg.read_text(encoding="utf-8"))
  ttk.Button(left,text="성능 설정 저장",command=self.save_perf_settings).pack(fill="x",pady=(6,0))
  self.perf_log=tk.Text(right,font=("Consolas",9));self.perf_log.pack(fill="both",expand=True)
  ttk.Label(right,text="최적화 원칙: 3사 공식 API 우선 / 같은 실행 스냅샷 재사용 / 실제 미확인 상품만 Chrome 핵심키워드→풀네임 재검증",
            foreground="#666666",wraplength=760).pack(anchor="w",pady=(6,0))

 def save_perf_settings(self):
  try:
   obj=json.loads(self.perf_text.get("1.0","end"))
   (ROOT/"data"/"performance.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
   messagebox.showinfo("성능 설정","저장했습니다. 다음 실행부터 반영됩니다.")
  except Exception as e:messagebox.showerror("성능 설정 오류",str(e))

 def load_perf_log(self):
  p=ROOT/"logs"/"studio.log";self.perf_log.delete("1.0","end")
  if not p.exists():return
  lines=[x for x in p.read_text(encoding="utf-8",errors="ignore").splitlines() if "[PERF]" in x]
  self.perf_log.insert("1.0","\n".join(lines[-500:]))
 def template(self):
  p=self.tabs["블로그 양식"];self.tpl=tk.Text(p,font=("Consolas",10));self.tpl.pack(fill="both",expand=True,padx=10,pady=10)
  path=ROOT/"templates"/"default_mobile.json";self.tpl.insert("1.0",path.read_text(encoding="utf-8"))
  ttk.Button(p,text="양식 저장",command=lambda:path.write_text(self.tpl.get("1.0","end"),encoding="utf-8")).pack(anchor="e",padx=10,pady=(0,8))
 def trouble(self):
  p=self.tabs["문제 해결"];row=ttk.Frame(p,padding=8);row.pack(fill="x")
  ttk.Button(row,text="전체 진단",command=self.health).pack(side="left");ttk.Button(row,text="네이버 저장환경 점검",command=self.blog_preflight).pack(side="left",padx=4);ttk.Button(row,text="일반 Chrome 확장 설치",command=self.chrome_extension_setup).pack(side="left",padx=4);ttk.Button(row,text="쿠팡·네이버 Chrome 테스트",command=self.chrome_collector_test).pack(side="left",padx=4);ttk.Button(row,text="토스 Multi-frame 감사",command=self.toss30_audit).pack(side="left",padx=4);ttk.Button(row,text="토스 Selenium 로그인",command=self.toss_ocr_diagnostic).pack(side="left",padx=4);ttk.Button(row,text="토스 체크→수집→해제 실전 테스트",command=self.toss_live_smoke).pack(side="left",padx=4);ttk.Button(row,text="Android 토스 가격/이미지 실전 테스트",command=self.android_diagnostic).pack(side="left",padx=4);ttk.Button(row,text="자동 복구",command=self.repair).pack(side="left",padx=4)
  self.diag=tk.Text(p,font=("Consolas",10));self.diag.pack(fill="both",expand=True,padx=8,pady=8)
 def logs(self):
  p=self.tabs["실행 로그"];self.logbox=tk.Text(p,font=("Consolas",9));self.logbox.pack(fill="both",expand=True,padx=8,pady=8)
  ttk.Button(p,text="로그 새로고침",command=self.loadlog).pack(anchor="e",padx=8,pady=(0,8))
 def settings_tab(self):
  p=self.tabs["설정/선택기능"];cfg=settings()
  quick=ttk.LabelFrame(p,text="고급 도구 바로가기",padding=8);quick.pack(fill="x",padx=8,pady=(8,4))
  for i in range(5):quick.columnconfigure(i,weight=1)
  for i,(label,key) in enumerate([("이미지·가격 검증","verify"),("AI 제품영상","video"),("성능/최적화","performance"),("문제 해결","diagnostics"),("실행 로그","logs")]):
   ttk.Button(quick,text=label,command=lambda k=key:self.show_page(k)).grid(row=0,column=i,sticky="ew",padx=2)
  self.settext=tk.Text(p,font=("Consolas",10));self.settext.pack(fill="both",expand=True,padx=8,pady=8);self.settext.insert("1.0",json.dumps(cfg,ensure_ascii=False,indent=2))
  row=ttk.Frame(p);row.pack(fill="x",padx=8,pady=(0,8))
  ttk.Button(row,text="설정 저장",command=self.savesettings).pack(side="left")
  ttk.Button(row,text="3사 검색 연결 테스트",command=self.market_smoke_test).pack(side="left",padx=4)
  ttk.Button(row,text="쿠팡 API 키 설정",command=self.coupang_api_setup).pack(side="left",padx=4)
  ttk.Button(row,text="쿠팡 API 테스트",command=self.coupang_api_test).pack(side="left",padx=4)
  ttk.Button(row,text="네이버 API 키 설정",command=self.naver_api_setup).pack(side="left",padx=4)
  ttk.Button(row,text="네이버 API 테스트",command=self.naver_api_test).pack(side="left",padx=4)
  ttk.Button(row,text="토스 API 키 설정",command=self.toss_api_setup).pack(side="left",padx=4)
  ttk.Button(row,text="토스 API 테스트",command=self.toss_api_test).pack(side="left",padx=4)
  airow=ttk.Frame(p);airow.pack(fill="x",padx=8,pady=(0,8))
  ttk.Label(airow,text="AI 원고: Ollama Qwen3 무료 로컬 AI 1순위 → 안전원고 (OpenAI 자동사용 OFF)",font=("Malgun Gothic",9,"bold")).pack(side="left")
  ttk.Button(airow,text="Ollama 무료 AI 자동설정",command=self.ollama_auto_setup).pack(side="left",padx=(12,4))
  ttk.Button(airow,text="Ollama 연결 테스트",command=self.ollama_ai_test).pack(side="left",padx=4)

 def emit(self,msg):
  log(msg);self.q.put(("log",msg))

 def refresh_external_batch_state(self):
  if not hasattr(self,"external_batch_info"):
   return
  state=external_batch_import.selected_state()
  if not state.get("batch_id"):
   self.external_batch_info.set("선택된 외부 원고 없음 · 원고가 들어있는 폴더 또는 ZIP을 선택하세요")
   return
  source=Path(str(state.get("source_path") or ""))
  self.external_batch_info.set(
   f"선택: {source.name or source} · 전체 {int(state.get('total') or 0)}개 · "
   f"사진3장 완료 {int(state.get('complete') or 0)}개 · "
   f"이미지 미완료 {int(state.get('incomplete') or 0)}개 · "
   f"원고 정상 {int(state.get('content_ready') or 0)}개"
  )
  if hasattr(self,"already_posted_info"):
   summary=already_posted_adapter.batch_summary(str(state.get("batch_id") or ""))
   self.already_posted_info.set(
    f"기존 게시완료 {summary['posted']}개 · 자동대조 확인필요 {summary['review']}개 · "
    f"미게시 수동확인 {summary['manual_not_posted']}개 · 실제 진행 대상 {summary['remaining']}개"
   )

 def external_batch_choose_folder(self):
  path=filedialog.askdirectory(title="외부 원고·이미지가 저장된 폴더 선택")
  if path:self._external_batch_start(path)

 def external_batch_choose_zip(self):
  path=filedialog.askopenfilename(title="외부 원고·이미지 ZIP 선택",filetypes=[("ZIP 압축파일","*.zip"),("모든 파일","*.*")])
  if path:self._external_batch_start(path)

 def _external_batch_start(self,path):
  if self.worker and self.worker.is_alive():
   return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.external_batch_info.set("선택한 위치를 검사하고 있습니다… 원본 파일은 변경하지 않습니다.")
  self.total["value"]=0;self.totalmsg.config(text="외부 원고 폴더 검사·가져오기")
  self.worker=threading.Thread(target=self._external_batch_work,args=(path,),daemon=True);self.worker.start()

 def _external_batch_work(self,path):
  try:
   def cb(done,total,msg):
    self.q.put(("total",int(done/max(1,total)*100),msg))
   result=external_batch_import.import_package(path,progress=cb)
   self.q.put(("external_done",result))
  except Exception as e:
   self.q.put(("external_error",str(e)))

 def external_batch_blog(self,image_state):
  state=external_batch_import.selected_state()
  if not state.get("batch_id"):
   return messagebox.showwarning("선택된 폴더 없음","먼저 ‘폴더 선택·가져오기’ 또는 ‘ZIP 선택·가져오기’를 실행하세요.")
  ids=already_posted_adapter.pending_product_ids(str(state.get("batch_id") or ""),image_state)
  posted_summary=already_posted_adapter.batch_summary(str(state.get("batch_id") or ""))
  content_ready=int(state.get("content_ready") or 0)
  if not ids:
   return messagebox.showinfo("처리 대상 없음","선택한 조건에 해당하는 제품이 없습니다.")
  if image_state=="complete":
   mode="images_only";label="사진 3장 완료";detail="대표 1장과 제품 상세/갤러리 2장을 넣어"
  else:
   mode="text_only";label="이미지 미완료";detail="이미지 없이 제목·본문·태그만"
  if content_ready<=0:
   return messagebox.showwarning("정상 원고 없음","본문 규칙 검사를 통과한 원고가 없어 임시저장을 시작하지 않습니다.")
  ok=messagebox.askyesno(
   "선택 배치 임시저장",
   f"{label} 제품 {len(ids)}개를 대상으로 {detail} 네이버 임시저장을 시작할까요?\n\n"
   f"수동·자동으로 확인된 기존 게시글 {posted_summary['posted']}개는 제외됩니다.\n"
   "이미 임시저장 완료된 제품은 건너뜁니다. 실패 시 현재 제품에서 멈추며 다음 제품으로 넘어가지 않습니다."
  )
  if not ok:return
  self.blog_single(mode,False,{"import_batch_id":state["batch_id"],"import_image_state":image_state,"product_ids":ids})

 def open_external_batch_report(self):
  state=external_batch_import.selected_state();path=Path(str(state.get("report_csv") or ""))
  if not path.is_file():
   return messagebox.showwarning("분류표 없음","먼저 외부 원고 폴더 또는 ZIP을 가져오세요.")
  try:
   if hasattr(os,"startfile"):os.startfile(str(path))
   else:subprocess.Popen(["xdg-open",str(path)])
  except Exception:
   messagebox.showinfo("완료/미완료 분류표",str(path))

 def existing_post_selected(self,posted):
  ids=[int(value) for value in self.tree.selection() if str(value).isdigit()]
  if not ids:return messagebox.showwarning("제품 선택 필요","상품/진행현황 목록에서 제품을 하나 이상 선택하세요. Ctrl 키로 여러 제품을 선택할 수 있습니다.")
  action="기존 게시완료로 표시" if posted else "게시완료 표시를 해제하고 자동대조 대상에서도 제외"
  if not messagebox.askyesno("수동 게시 구분",f"선택한 제품 {len(ids)}개를 {action}할까요?"):
   return
  try:
   result=already_posted_adapter.mark_manual(ids,posted=posted)
   state=external_batch_import.selected_state();already_posted_adapter.export_status_report(str(state.get("batch_id") or ""))
   self.refresh();messagebox.showinfo("수동 게시 구분",result.get("message") or "완료")
  except Exception as e:messagebox.showerror("수동 게시 구분 실패",str(e))

 def existing_post_auto(self):
  state=external_batch_import.selected_state()
  if not state.get("batch_id"):return messagebox.showwarning("선택된 폴더 없음","먼저 외부 원고 폴더 또는 ZIP을 가져오세요.")
  saved=str(already_posted_adapter.load_config().get("blog_id") or "")
  value=simpledialog.askstring("네이버 기존글 자동대조","본인 네이버 블로그 ID 또는 blog.naver.com 주소를 입력하세요.\n공개 RSS 제목만 읽으며 글을 열거나 수정하지 않습니다.",initialvalue=saved,parent=self)
  if value is None:return
  try:blog_id=already_posted_adapter.save_blog_id(value)
  except Exception as e:return messagebox.showerror("블로그 ID 오류",str(e))
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.already_posted_info.set("네이버 공개 RSS에서 기존 게시글 제목을 가져와 대조하고 있습니다…")
  self.worker=threading.Thread(target=self._existing_post_auto_work,args=(blog_id,state["batch_id"]),daemon=True);self.worker.start()

 def _existing_post_auto_work(self,blog_id,batch_id):
  try:
   posts,meta=already_posted_adapter.fetch_naver_rss(blog_id)
   def cb(done,total,msg):self.q.put(("total",int(done/max(1,total)*100),msg))
   result=already_posted_adapter.match_posts(posts,batch_id,"NAVER_RSS_AUTO",progress=cb)
   result["source_count"]=meta["count"];result["source_label"]="네이버 공개 RSS"
   self.q.put(("existing_post_done",result))
  except Exception as e:self.q.put(("existing_post_error",str(e)))

 def existing_post_file(self):
  state=external_batch_import.selected_state()
  if not state.get("batch_id"):return messagebox.showwarning("선택된 폴더 없음","먼저 외부 원고 폴더 또는 ZIP을 가져오세요.")
  path=filedialog.askopenfilename(title="이미 게시한 글 제목 파일 선택",filetypes=[("제목 파일","*.txt *.csv *.json"),("텍스트","*.txt"),("CSV","*.csv"),("JSON","*.json")])
  if not path:return
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.already_posted_info.set("선택한 제목 파일과 외부 원고 제품을 대조하고 있습니다…")
  self.worker=threading.Thread(target=self._existing_post_file_work,args=(path,state["batch_id"]),daemon=True);self.worker.start()

 def _existing_post_file_work(self,path,batch_id):
  try:
   posts,meta=already_posted_adapter.read_title_file(path)
   def cb(done,total,msg):self.q.put(("total",int(done/max(1,total)*100),msg))
   result=already_posted_adapter.match_posts(posts,batch_id,"TITLE_FILE_AUTO",progress=cb)
   result["source_count"]=meta["count"];result["source_label"]="제목 파일"
   self.q.put(("existing_post_done",result))
  except Exception as e:self.q.put(("existing_post_error",str(e)))

 def open_existing_post_report(self):
  try:
   state=external_batch_import.selected_state();path=Path(already_posted_adapter.export_status_report(str(state.get("batch_id") or "")))
   if hasattr(os,"startfile"):os.startfile(str(path))
   else:subprocess.Popen(["xdg-open",str(path)])
  except Exception as e:messagebox.showinfo("게시완료/남은목록",str(e))

 def content_live_progress(self,event):
  try:self.q.put(("content_live",dict(event or {})))
  except Exception:pass

 def _fmt_seconds(self,sec):
  try:sec=max(0,int(float(sec or 0)))
  except Exception:sec=0
  if sec<60:return f"{sec}초"
  m,s=divmod(sec,60)
  if m<60:return f"{m}분 {s:02d}초"
  h,m=divmod(m,60);return f"{h}시간 {m:02d}분"

 def _render_content_live(self,ev):
  if not hasattr(self,"content_live_vars"):return
  ev=dict(ev or {});self.content_live_last_event=ev
  event=str(ev.get("event") or "")
  name=str(ev.get("name") or "");idx=int(ev.get("index") or 0);total=int(ev.get("total") or 0)
  if event=="batch_start":
   self.content_live_started_at=time.monotonic();self.content_live_pb["value"]=0
   self.content_live_vars["product"].set(f"대상 {int(ev.get('total') or 0)}건")
   self.content_live_vars["phase"].set("배치 준비")
   self.content_live_vars["model"].set(str(ev.get("model") or settings().get("ollama_model") or "-"))
   self.content_live_vars["elapsed"].set("0초");self.content_live_vars["output"].set("0자");self.content_live_vars["speed"].set("-");self.content_live_vars["eta"].set("계산 중");self.content_live_vars["attempt"].set("-")
   self.content_live_preview.set(str(ev.get("reason") or "Ollama 원고 생성 준비 중"));return
  if event=="product_start":
   self.content_live_started_at=time.monotonic();self.content_live_pb["value"]=2
   self.content_live_vars["product"].set(f"{idx}/{total} · TOP{ev.get('product_no','-')} · {name[:42]}")
   self.content_live_vars["phase"].set("상품 준비")
   self.content_live_vars["model"].set(str(ev.get("model") or self.content_live_vars["model"].get()))
   self.content_live_vars["elapsed"].set("0초");self.content_live_vars["output"].set("0자");self.content_live_vars["speed"].set("-");self.content_live_vars["attempt"].set("-")
   self.content_live_preview.set("상품별 SEO 키워드와 AI 입력을 준비하고 있습니다.");return
  if event=="phase":
   self.content_live_vars["phase"].set(str(ev.get("phase") or "처리 중"));self.content_live_pb["value"]=int(ev.get("phase_pct") or self.content_live_pb["value"])
   if ev.get("attempt"):
    self.content_live_vars["attempt"].set(f"{int(ev.get('attempt'))}/{int(ev.get('max_attempts') or 1)}")
   self.content_live_preview.set(str(ev.get("phase") or "처리 중"));return
  if event in {"ollama_start","ollama_stream","ollama_done","ollama_error"}:
   if name:self.content_live_vars["product"].set(f"{idx}/{total} · TOP{ev.get('product_no','-')} · {name[:42]}")
   self.content_live_vars["model"].set(str(ev.get("model") or "-"));self.content_live_vars["elapsed"].set(self._fmt_seconds(ev.get("elapsed")))
   self.content_live_vars["attempt"].set(f"{int(ev.get('attempt') or 1)}/{int(ev.get('max_attempts') or 1)}")
   chars=int(ev.get("chars") or 0);self.content_live_vars["output"].set(f"{chars:,}자")
   if event=="ollama_start":
    self.content_live_vars["phase"].set("Ollama 모델 응답 대기");self.content_live_pb["value"]=25;self.content_live_preview.set("모델이 프롬프트를 읽고 첫 응답을 준비 중입니다. 모델 로딩이 필요한 첫 실행은 조금 더 걸릴 수 있습니다.")
   elif event=="ollama_stream":
    self.content_live_vars["phase"].set("Ollama 실시간 생성 중")
    target=max(2200,int(settings().get("ollama_live_target_chars",3400)));self.content_live_pb["value"]=min(88,25+int(63*chars/target))
    eval_count=int(ev.get("eval_count") or 0);eval_ns=int(ev.get("eval_duration") or 0)
    if eval_count and eval_ns:
     rate=eval_count/(eval_ns/1_000_000_000);self.content_live_vars["speed"].set(f"{rate:.1f} tok/s")
    else:self.content_live_vars["speed"].set(f"{float(ev.get('char_rate') or 0):.0f} 자/s")
    preview=str(ev.get("preview") or "").strip();self.content_live_preview.set(("생성 중 · "+preview[-140:]) if preview else "Ollama가 JSON 원고를 생성하고 있습니다.")
   elif event=="ollama_done":
    self.content_live_vars["phase"].set("AI 생성 완료 · 품질검사")
    self.content_live_vars["speed"].set(f"{float(ev.get('tokens_per_sec') or 0):.1f} tok/s" if ev.get("tokens_per_sec") else "완료")
    self.content_live_pb["value"]=90;self.content_live_preview.set(f"AI 응답 완료 · 출력 토큰 {int(ev.get('eval_count') or 0):,} · 품질검사 중")
   else:
    self.content_live_vars["phase"].set("AI 생성 오류");self.content_live_preview.set(str(ev.get("error") or "Ollama 오류"))
   return
  if event=="product_done":
   self.content_live_pb["value"]=100;self.content_live_vars["phase"].set("상품 원고 완료");self.content_live_vars["elapsed"].set(self._fmt_seconds(ev.get("elapsed")))
   self.content_live_vars["eta"].set(self._fmt_seconds(ev.get("eta_sec")));self.content_live_avg_sec=float(ev.get("avg_sec") or 0)
   self.content_live_preview.set(f"{idx}/{total} 완료 · {ev.get('status','원고완료')} · 평균 {self._fmt_seconds(ev.get('avg_sec'))}/건 · 다음 상품으로 이동")
   return
  if event=="product_error":
   self.content_live_vars["phase"].set("상품 처리 오류");self.content_live_vars["elapsed"].set(self._fmt_seconds(ev.get("elapsed")));self.content_live_preview.set(str(ev.get("error") or "원고 생성 오류"));return
  if event in {"batch_done","batch_cancelled"}:
   self.content_live_vars["phase"].set("전체 완료" if event=="batch_done" else "사용자 중지")
   self.content_live_vars["product"].set(f"완료 {int(ev.get('done') or 0)}/{int(ev.get('total') or 0)}")
   self.content_live_vars["elapsed"].set(self._fmt_seconds(ev.get("elapsed")));self.content_live_vars["eta"].set("0초" if event=="batch_done" else "중지")
   self.content_live_pb["value"]=100 if event=="batch_done" else self.content_live_pb["value"]
   self.content_live_preview.set(str(ev.get("message") or ("원고 생성이 완료되었습니다." if event=="batch_done" else "사용자 요청으로 중지했습니다.")))

 def _tick_content_live(self):
  try:
   if hasattr(self,"content_live_vars") and getattr(self,"content_live_started_at",0):
    ev=getattr(self,"content_live_last_event",{}) or {};event=str(ev.get("event") or "")
    if event not in {"batch_done","batch_cancelled","product_done","product_error"}:
     elapsed=max(0,time.monotonic()-self.content_live_started_at);self.content_live_vars["elapsed"].set(self._fmt_seconds(elapsed))
     if self.content_live_avg_sec and int(ev.get("total") or 0):
      remain=max(0,int(ev.get("total") or 0)-int(ev.get("index") or 1));self.content_live_vars["eta"].set(self._fmt_seconds(self.content_live_avg_sec*remain))
     try:self._set_global_live(eta="ETA "+self.content_live_vars["eta"].get())
     except Exception:pass
  except Exception:pass
  self.after(1000,self._tick_content_live)

 def poll(self):
  try:
   while 1:
    typ,*a=self.q.get_nowait()
    if typ=="log":self.live.insert("end",time.strftime("%H:%M:%S ")+a[0]+"\n");self.live.see("end")
    elif typ=="step":
     k,s1,p=a;self.vars[k].set(s1);self.pbs[k]["value"]=p
     label=next((x[1] for x in STEPS if x[0]==k),k);self._set_global_live(stage=label,detail=s1,pct=p)
    elif typ=="total":
     p,m=a;self.total["value"]=p;self.totalmsg.config(text=m);self._set_global_live(detail=m,pct=p)
    elif typ=="totalmsg":self.totalmsg.config(text=a[0] if a else "")
    elif typ=="refresh":self.refresh()
    elif typ=="content_live":
     ev=a[0] if a else {};self._render_content_live(ev)
     try:
      self._set_global_live(stage=self.content_live_vars["phase"].get(),detail=self.content_live_vars["product"].get(),pct=self.content_live_pb["value"],eta="ETA "+self.content_live_vars["eta"].get())
     except Exception:pass
    elif typ=="celeb":
     p,m=a;self._set_global_live(stage="연예인 착장",detail=m,pct=p)
     if hasattr(self,"celeb_style_pb"):self.celeb_style_pb["value"]=p
     if hasattr(self,"celeb_style_info"):self.celeb_style_info.set(m)
    elif typ=="video":
     p,m=a;self._set_global_live(stage="AI 제품영상",detail=m,pct=p)
     if hasattr(self,"video_pb"):self.video_pb["value"]=p
     if hasattr(self,"video_info"):self.video_info.set(m)
    elif typ=="video_plan_done":
     self._render_video_plan(*a)
    elif typ=="trend":
     p,m=a;self._set_global_live(stage="트렌드 수집",detail=m,pct=p)
     if hasattr(self,"trend_pb"):self.trend_pb["value"]=p
     if hasattr(self,"trend_info"):self.trend_info.set(m)
     if hasattr(self,"collect_trend_pb"):self.collect_trend_pb["value"]=p
     if hasattr(self,"collect_trend_info"):self.collect_trend_info.set(m)
    elif typ=="androiddiag":self._render_android_diag(a[0])
    elif typ=="external_done":
     result=a[0];self.refresh_external_batch_state();self.refresh()
     self.total["value"]=100;self.totalmsg.config(text=result.get("message","외부 폴더 가져오기 완료"))
     messagebox.showinfo("외부 원고 가져오기 완료",result.get("message","완료"))
    elif typ=="external_error":
     self.refresh_external_batch_state();self.totalmsg.config(text="외부 폴더 가져오기 실패")
     messagebox.showerror("외부 원고 가져오기 실패",a[0])
    elif typ=="existing_post_done":
     result=a[0];self.refresh();self.total["value"]=100;self.totalmsg.config(text=result.get("message","기존 게시글 대조 완료"))
     messagebox.showinfo("기존 게시글 대조 완료",f"{result.get('source_label','기존글')} {int(result.get('source_count') or 0)}개를 확인했습니다.\n\n{result.get('message','완료')}\n\n애매한 항목은 자동 제외하지 않고 ‘자동확인필요’로 표시했습니다.")
    elif typ=="existing_post_error":
     self.refresh();self.totalmsg.config(text="기존 게시글 대조 실패")
     messagebox.showerror("기존 게시글 대조 실패",a[0]+"\n\nRSS 범위 밖의 오래된 글은 제목 TXT·CSV 자동대조 또는 수동 게시완료 표시를 사용하세요.")
    elif typ=="blog_stage_error":
     msg,diagnostic=a
     extra=("\n\n진단표: "+diagnostic) if diagnostic else ""
     messagebox.showerror("임시저장 안전 중단",msg+"\n\n실패한 Chrome 창은 확인할 수 있도록 닫지 않았습니다. 현재 상품에서 멈췄으며 다음 상품으로 넘어가지 않았습니다."+extra)
  except queue.Empty:pass
  self.after(150,self.poll)
 def progress(self,k):
  def cb(done,total,msg):
   pct=max(0,min(100,int(float(done)/max(1,float(total))*100)))
   self.q.put(("step",k,msg,pct))
   pos=getattr(self,"active_progress_map",{}).get(k,(0,1));stage_idx,stage_total=pos
   overall=max(0,min(100,int((float(stage_idx)+pct/100.0)/max(1,float(stage_total))*100)))
   self.q.put(("total",overall,msg))
  return cb
 def single(self,k):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.stop=False
  self.worker=threading.Thread(target=self.work,args=([k],),daemon=True);self.worker.start()
 def content_force_regenerate(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  if not messagebox.askyesno("Ollama 전체 재생성","현재 완료 원고까지 포함해 제목·본문·태그를 Ollama 무료 로컬 AI 방식으로 다시 만들까요?\n\n기존 이미지와 제휴링크는 건드리지 않습니다."):
   return
  self.stop=False
  self.worker=threading.Thread(target=self.work,args=(["content"],None,False,None,{"force_regenerate":True}),daemon=True);self.worker.start()

 def blog_single(self,mode,force_retry=False,blog_context=None):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  self.stop=False
  self.worker=threading.Thread(target=self.work,args=(["blog"],mode,force_retry,blog_context),daemon=True);self.worker.start()
 def runall(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","이미 실행 중입니다.")
  self.stop=False;self.worker=threading.Thread(target=self.work,args=([x[0] for x in STEPS],),daemon=True);self.worker.start()
 def work(self,keys,blog_mode=None,blog_force_retry=False,blog_context=None,content_context=None):
  pending=False;self.active_progress_map={k:(idx,len(keys)) for idx,k in enumerate(keys)}
  for idx,k in enumerate(keys):
   if self.stop:break
   label=next(x[1] for x in STEPS if x[0]==k);self.q.put(("step",k,"실행 중",5));self.q.put(("total",int(idx/len(keys)*100),label))
   try:
    result=None
    if k=="qa":result=self.qa()
    else:
     mod=next(x[2] for x in STEPS if x[0]==k);h=mod.health()
     if not h.get("ready"):raise RuntimeError(h.get("message"))
     if k=="blog":
      context={"mode":blog_mode or settings().get("blog_default_mode","images_only"),"force_retry":bool(blog_force_retry)}
      context.update(blog_context or {})
      result=mod.run(context=context,progress=self.progress(k))
     elif k=="content":
      content_ctx=dict(content_context or {})
      content_ctx["_live_progress"]=self.content_live_progress
      content_ctx["_cancel_check"]=lambda:self.stop
      result=mod.run(context=content_ctx,progress=self.progress(k))
     else:result=mod.run(progress=self.progress(k))
    stage_ok=not isinstance(result,dict) or result.get("stage_ok",True)
    if stage_ok:
     self.q.put(("step",k,"완료",100));self.emit(label+" 완료")
    else:
     pending=True;msg=str(result.get("message") or "보강 필요")
     self.q.put(("step",k,msg,100));self.emit(label+" — "+msg)
     if k=="blog":
      failed_rows=list(result.get("failed") or []) if isinstance(result,dict) else []
      first_error=str((failed_rows[0] or {}).get("error") or "") if failed_rows else ""
      detail=msg+("\n\n실제 중단 원인: "+first_error if first_error else "")
      self.q.put(("blog_stage_error",detail,str(result.get("diagnostic_csv") or "")))
    # v7.40 has a dedicated image stage. Price verification never edits blog photos.
    if k=="price":
     con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
     rr=con.execute("SELECT image_verified_count,title,body,tags FROM products WHERE status NOT LIKE '추천제외:%' AND COALESCE(already_posted,0)=0").fetchall();con.close()
     img_bad=[x for x in rr if int(x["image_verified_count"] or 0)<3]
     text_bad=[x for x in rr if not x["title"] or not x["body"] or not x["tags"]]
     if img_bad:
      pending=True;self.q.put(("step","images",f"사진보강 필요 {len(img_bad)}건",100))
     elif rr:self.q.put(("step","images","완료 · 동일상품 3/3",100))
     if text_bad:
      pending=True;self.q.put(("step","content",f"원고보강 필요 {len(text_bad)}건",100))
    self.q.put(("refresh",))
   except Exception as e:
    self.q.put(("step",k,"실패",0));self.emit(label+" 실패: "+str(e));self.q.put(("refresh",));self.q.put(("total",int(idx/len(keys)*100),label+" 실패 — 실행 로그/진단 파일 확인"));return
  try:
   self._maybe_video_after_pipeline()
  except Exception as e:self.emit("AI영상 선택단계 실패: "+str(e))
  self.q.put(("total",100,"순차 실행 완료 · 보완 필요 항목 있음" if pending else "순차 실행 완료"));self.q.put(("refresh",))
 def qa(self):
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;rows=con.execute("SELECT * FROM products WHERE status NOT LIKE '추천제외:%' AND COALESCE(already_posted,0)=0").fetchall();failed=0
  for i,r in enumerate(rows):
   errs=[]
   if not r["title"]:errs.append("제목")
   if not r["body"]:errs.append("본문")
   iv=int(r["image_verified_count"] or 0) if "image_verified_count" in r.keys() else sum(1 for x in [r["image1"],r["image2"],r["image3"]] if x)
   physical=sum(1 for x in [r["image1"],r["image2"],r["image3"]] if x and Path(x).exists())
   if iv<3 or physical<3:errs.append(f"사진{min(iv,physical)}/3")
   taglist=[x.strip() for x in str(r["tags"] or "").split(",") if x.strip()]
   seo_audit=content_adapter.seo_token_audit(str(r["title"] or ""),taglist,str(r["name"] or ""))
   if len(taglist)!=int(settings().get("tags_count",30)):errs.append(f"태그{len(taglist)}/{int(settings().get('tags_count',30))}")
   if seo_audit.get("title_duplicate_words"):errs.append("제목단어중복:"+"/".join(seo_audit["title_duplicate_words"][:4]))
   if seo_audit.get("tag_duplicate_words"):errs.append("태그단어중복:"+"/".join(seo_audit["tag_duplicate_words"][:4]))
   if seo_audit.get("banned_tags"):errs.append("태그노이즈")
   # v7.58 strict Naver SEO audit: title must keep 추천｜, actual autocomplete
   # words must flow into title, four heart headings, their paragraphs, and tags.
   # If Naver supplied no usable new keyword we never invent one; the row stays
   # SEO보완 so the user can retry collection instead of publishing silently.
   seos=[x.strip() for x in str(r["seo_keywords"] or "").split(",") if x.strip()] if "seo_keywords" in r.keys() else []
   try:
    bobj=json.loads(r["body"] or "[]");bodytxt=" ".join(" ".join(map(str,b.get("lines") or [])) if b.get("type")=="paragraph" else str(b.get("text") or "") for b in bobj)
   except Exception:
    bobj=[];bodytxt=str(r["body"] or "")
   subaudit=content_adapter.content_subkeyword_audit_from_blocks(str(r["name"] or ""),str(r["title"] or ""),bobj,taglist,seos)
   if not subaudit.get("pipe_ok"):errs.append("제목추천｜누락")
   if not subaudit.get("naver_keywords_available"):errs.append("네이버서브키워드없음")
   else:
    if not subaudit.get("title_keyword_ok"):errs.append("제목서브키워드")
    if not subaudit.get("heading_keyword_ok"):errs.append("소제목서브키워드")
    if not subaudit.get("paragraph_keyword_ok"):errs.append("소제목본문연결")
    if not subaudit.get("tag_keyword_ok"):errs.append("태그서브키워드")
   if len(bodytxt)<850:errs.append("본문분량")
   try:
    sev=json.loads(Path(r["seo_evidence_json"]).read_text(encoding="utf-8")) if r["seo_evidence_json"] and Path(r["seo_evidence_json"]).exists() else {}
    da=sev.get("content_diversity_audit") or {}
    if da and not da.get("ok"):errs.append("본문문장반복")
    qa2=sev.get("content_quality_audit") or {}
    if bool(settings().get("blog_require_content_quality_audit",True)) and not qa2.get("ok"):
     errs.append("본문내용품질")
   except Exception:
    if bool(settings().get("blog_require_content_quality_audit",True)):errs.append("본문품질검증없음")
   # Sharelink is now a separate post-image stage. Missing affiliate links do
   # not block content/image QA or the title/body/tags-only draft mode.
   pv=int(r["price_verified_sites"] or 0) if "price_verified_sites" in r.keys() else sum(1 for x in [r["price_toss"],r["price_coupang"],r["price_naver"]] if x)
   pc=int(r["price_image_verified_sites"] or 0) if "price_image_verified_sites" in r.keys() else 0
   req=int(settings().get("price_require_verified_sites",3));req_img=int(settings().get("price_require_image_with_price_sites",3))
   if pv<req:errs.append(f"가격{pv}/{req}")
   if pc<req_img:errs.append(f"가격+이미지{pc}/{req_img}")
   status="QA통과" if not errs else "QA보완:"+",".join(errs)
   if errs:failed+=1
   con.execute("UPDATE products SET status=?,updated_at=datetime('now','localtime') WHERE id=?",(status,r["id"]))
   self.q.put(("step","qa",status,int((i+1)/max(1,len(rows))*100)))
  con.commit();con.close()
  return {"processed":len(rows),"failed":failed,"stage_ok":failed==0,"soft_pending":failed>0,
          "message":"QA 전상품 통과" if failed==0 else f"QA 보완 필요 {failed}건 — 미완료 상품은 블로그 임시저장 대상에서 제외됩니다."}

 def refresh(self):
  self.refresh_external_batch_state()
  self.refresh_top100()
  counts=self.refresh_sources()
  self.refresh_coverage(counts)
  try:self.refresh_trends()
  except Exception:pass
  try:self.refresh_celebrity_styles()
  except Exception:pass
  try:self.refresh_trend_products()
  except Exception:pass
  try:self.refresh_video_products()
  except Exception:pass
  try:self.refresh_selected_verification()
  except Exception:pass
  try:self.refresh_modern_overview()
  except Exception:pass
 def show(self):
  sel=self.tree.selection()
  if not sel:return
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row;r=con.execute("SELECT * FROM products WHERE id=?",(sel[0],)).fetchone();con.close()
  self.prev.delete("1.0","end")
  vstatus=r["video_status"] if "video_status" in r.keys() else "-"
  vout=r["video_output"] if "video_output" in r.keys() else "-"
  vplan=r["video_plan_summary"] if "video_plan_summary" in r.keys() else "-"
  iv=int(r["image_verified_count"] or 0) if "image_verified_count" in r.keys() else 0;pv=int(r["price_verified_sites"] or 0) if "price_verified_sites" in r.keys() else 0
  pc=int(r["price_image_verified_sites"] or 0) if "price_image_verified_sites" in r.keys() else 0
  posted_text=("기존 게시완료" if int(r["already_posted"] or 0) else "자동대조 확인필요" if int(r["already_posted_review"] or 0) else "미게시 수동확인" if int(r["already_posted_auto_ignored"] or 0) else "남은 제품")
  self.prev.insert("1.0",f"게시 구분\n{posted_text} · {r['already_posted_method'] or '-'}\n대조글: {r['already_posted_title'] or '-'}\n{r['already_posted_url'] or ''}\n\n제목\n{r['title'] or '-'}\n\n본문 블록\n{r['body'] or '-'}\n\n태그\n{r['tags'] or '-'}\n\n실제 이미지 검증 {iv}/3\n{r['image1']}\n{r['image2']}\n{r['image3']}\n\n3사 가격 검증 {pv}/3 · 가격+이미지 결합 {pc}/3\n쿠팡 {r['price_coupang'] or '-'} / 네이버 {r['price_naver'] or '-'} / 토스 {r['price_toss'] or '-'}\n가격비교 이미지\n{r['price_compare_image'] or '-'}\n\nAI 영상 기획\n{vplan or '-'}\n\nAI 영상 렌더링\n{vstatus}\n{vout}")
  self.refresh_selected_verification()
 def approve(self):
  sel=self.tree.selection();con=sqlite3.connect(DB)
  for i in sel:con.execute("UPDATE products SET approved=1 WHERE id=?",(i,))
  con.commit();con.close();self.refresh()
 def export(self):
  p=filedialog.asksaveasfilename(defaultextension=".csv")
  if not p:return
  con=sqlite3.connect(DB);rows=con.execute("SELECT * FROM products WHERE status NOT LIKE '추천제외:%' ORDER BY product_no,id").fetchall();cols=[x[1] for x in con.execute("PRAGMA table_info(products)")];con.close()
  with open(p,"w",newline="",encoding="utf-8-sig") as f:w=csv.writer(f);w.writerow(cols);w.writerows(rows)
 def export_candidates(self):
  p=filedialog.asksaveasfilename(defaultextension=".csv",initialfile="collected_540_products.csv")
  if not p:return
  con=sqlite3.connect(DB);rows=con.execute("SELECT platform,category,rank_no,name,price,url,image_url,captured_at FROM candidates ORDER BY platform,category,rank_no,id").fetchall();con.close()
  with open(p,"w",newline="",encoding="utf-8-sig") as f:
   w=csv.writer(f);w.writerow(["사이트","카테고리","카테고리순위","상품명","가격","URL","이미지URL","수집시각"]);w.writerows(rows)

 def health(self):
  checks=[]
  for m in [workflow_assistant,external_batch_import,already_posted_adapter,search_adapter,content_text_adapter,image_adapter,price_adapter,blog_adapter,chrome_collector,trend_collection_adapter,trend_coupang_adapter,coupang_partners_api,coupang_sharelink_adapter,naver_shopping_api,toss_sharelink_api]:
   try:
    h=m.health();checks.append((h.get("name"),h.get("ready"),h.get("message"),h.get("state","PASS")))
   except Exception as e:checks.append((m.__name__,False,str(e),"FAIL"))
  # AI video is optional and must not make product search look broken.
  try:
   vh=video_adapter.health()
   checks.append(("AI 자연동작 제품영상",True,"설정 완료" if vh.get("ready") else "선택 기능: "+vh.get("message",""),"PASS" if vh.get("ready") else "OPTION"))
  except Exception as e:checks.append(("AI 자연동작 제품영상",True,"선택 기능: "+str(e),"OPTION"))
  for path in [DB,ROOT/"templates"/"default_mobile.json"]:
   checks.append((path.name,path.exists(),str(path),"PASS" if path.exists() else "FAIL"))
  self.diag.delete("1.0","end")
  for n,ok,msg,state in checks:
   tag="OK" if ok and state=="PASS" else ("OPTION" if state=="OPTION" else ("WAIT" if state=="WAIT" else "FAIL"))
   self.diag.insert("end",f"[{tag}] {n}\n  {msg}\n\n")
  required=[x for x in checks if x[3]!="OPTION"]
  ready=sum(1 for x in required if x[1]);self.badge.config(text=f"● 필수 시스템 {ready}/{len(required)} 정상",bg="#e9fbf4" if ready==len(required) else "#fff6df",fg=self.COLORS["success"] if ready==len(required) else self.COLORS["warn"])


 def android_diagnostic(self):
  try:
   subprocess.Popen(["cmd","/c","77_ANDROID_TOSS_PRICE_IMAGE_TEST.cmd"],cwd=ROOT)
   messagebox.showinfo("Android 토스 가격/이미지 실전 테스트","현재 TOP1 상품을 연결된 Android Toss 앱에서 실제 검색해 가격과 동일상품 제품이미지를 함께 저장합니다.\n실패하면 04_ANDROID_ONE_CLICK_REPAIR.cmd와 05_ANDROID_TOSS_DIAGNOSTIC.cmd를 먼저 실행하세요.")
  except Exception as e:messagebox.showerror("Android 토스 실전 테스트",str(e))

 def coupang_api_setup(self):
  try:subprocess.Popen(["cmd","/c","83_COUPANG_PARTNERS_API_SETUP.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("쿠팡 API 설정",str(e))

 def coupang_api_test(self):
  try:subprocess.Popen(["cmd","/c","84_COUPANG_PARTNERS_API_TEST.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("쿠팡 API 테스트",str(e))

 def naver_api_setup(self):
  try:subprocess.Popen(["cmd","/c","92_NAVER_IMAGE_API_SETUP.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("네이버 API 설정",str(e))

 def naver_api_test(self):
  try:subprocess.Popen(["cmd","/c","93_NAVER_IMAGE_API_TEST.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("네이버 API 테스트",str(e))

 def toss_api_setup(self):
  try:subprocess.Popen(["cmd","/c","97_TOSS_SHARELINK_API_SETUP.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("토스 API 설정",str(e))

 def toss_api_test(self):
  try:subprocess.Popen(["cmd","/c","98_TOSS_SHARELINK_API_TEST.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("토스 API 테스트",str(e))

 def ollama_auto_setup(self):
  try:subprocess.Popen(["cmd","/c","88_OLLAMA_FREE_AUTO_SETUP.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("Ollama 무료 AI 자동설정",str(e))

 def ollama_ai_test(self):
  try:subprocess.Popen(["cmd","/c","89_OLLAMA_FREE_AI_TEST.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("Ollama 연결 테스트",str(e))

 def apply_ollama_profile(self):
  labels={"초고속 · 4B 중심":"speed","빠른 균형 · 8B 권장":"balanced","고품질 · 14B/30B":"quality"}
  profile=labels.get(str(getattr(self,"ollama_profile_var",tk.StringVar(value="빠른 균형 · 8B 권장")).get()),"balanced")
  presets={
   "speed":{"ollama_model":"qwen3:4b","ollama_num_ctx":8192,"ollama_num_predict":1700,"content_diversity_retry_count":1,"content_recent_sentence_prompt_count":10,"content_recent_title_prompt_count":8,"content_recent_heading_prompt_count":10,"seo_naver_autocomplete_max_requests":2},
   "balanced":{"ollama_model":"qwen3:8b","ollama_num_ctx":12288,"ollama_num_predict":2200,"content_diversity_retry_count":2,"content_recent_sentence_prompt_count":18,"content_recent_title_prompt_count":12,"content_recent_heading_prompt_count":16,"seo_naver_autocomplete_max_requests":3},
   "quality":{"ollama_model":"qwen3:14b","ollama_num_ctx":16384,"ollama_num_predict":2200,"content_diversity_retry_count":3,"content_recent_sentence_prompt_count":30,"content_recent_title_prompt_count":18,"content_recent_heading_prompt_count":24,"seo_naver_autocomplete_max_requests":4},
  }
  try:
   path=ROOT/"data"/"settings.json";cfg=json.loads(path.read_text(encoding="utf-8"));cfg["ollama_generation_profile"]=profile;cfg.update(presets[profile]);cfg["ollama_model_policy"]="gpu_aware_speed_balanced_qwen3";path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding="utf-8")
   if hasattr(self,"ollama_profile_status"):
    self.ollama_profile_status.set(f"현재 {cfg['ollama_model']} · ctx {int(cfg['ollama_num_ctx']):,} · 재작성 최대 {int(cfg['content_diversity_retry_count'])}회")
   model=cfg["ollama_model"]
   try:installed=ollama_local.server_models()
   except Exception:installed=[]
   present=any(str(x).casefold()==model.casefold() for x in installed)
   if present:
    messagebox.showinfo("Ollama 속도 프로필",f"프로필을 적용했습니다.\n\n{self.ollama_profile_var.get()}\n사용 모델: {model}\n\n다음 원고 생성부터 바로 적용됩니다.")
   else:
    if messagebox.askyesno("Ollama 모델 설치 필요",f"프로필을 적용했습니다.\n\n권장 모델 {model}이 현재 Ollama에 설치되지 않은 것 같습니다.\n지금 자동설정을 실행해 모델을 확인/설치할까요?"):
     self.ollama_auto_setup()
  except Exception as e:messagebox.showerror("Ollama 속도 프로필",str(e))

 def openai_api_setup(self):
  try:subprocess.Popen(["cmd","/c","90_OPENAI_API_SETUP.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("OpenAI API 설정",str(e))

 def openai_api_test(self):
  try:subprocess.Popen(["cmd","/c","91_OPENAI_API_TEST.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("OpenAI API 테스트",str(e))

 def market_smoke_test(self):
  try:
   subprocess.Popen(["cmd","/c","13_3SITE_SEARCH_SMOKE_TEST.cmd"],cwd=ROOT)
   messagebox.showinfo("3사 검색 테스트","네이버 → 쿠팡 → 토스 순으로 '생수' 1회 검색 테스트를 시작했습니다.\n토스 최초 사용이면 열린 Chrome에서 로그인하세요.")
  except Exception as e:messagebox.showerror("3사 검색 테스트",str(e))



 def chrome_extension_setup(self):
  try:subprocess.Popen(["cmd","/c","15_INSTALL_NORMAL_CHROME_EXTENSION.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("Chrome 확장 설치",str(e))

 def chrome_collector_test(self):
  try:subprocess.Popen(["cmd","/c","16_NORMAL_CHROME_COLLECTOR_TEST.cmd"],cwd=ROOT)
  except Exception as e:messagebox.showerror("일반 Chrome 테스트",str(e))

 def toss30_audit(self):
  try:
   subprocess.Popen(["cmd","/c","78_TOSS_SELENIUM_MULTIFRAME_AUDIT.cmd"],cwd=ROOT)
   messagebox.showinfo("토스 Multi-frame 감사","토스 Selenium 재귀 iframe + open Shadow DOM + 가격 바로 위 제품명 파서와 실제 수집 호출을 검사합니다.\n모든 항목 PASS가 정상입니다.")
  except Exception as e:messagebox.showerror("토스 30개 수집 엔진 감사",str(e))

 def toss_ocr_diagnostic(self):
  try:
   subprocess.Popen(["cmd","/c","73_TOSS_SELENIUM_LOGIN_SETUP.cmd"],cwd=ROOT)
   messagebox.showinfo("토스 Selenium 로그인","토스 전용 Chrome 창이 열립니다. 최초 한 번 로그인한 뒤 PASS가 표시될 때까지 창을 유지하세요.")
  except Exception as e:messagebox.showerror("토스 Selenium 로그인",str(e))

 def toss_live_smoke(self):
  try:
   subprocess.Popen(["cmd","/c","80_TOSS_SELENIUM_LIVE_SMOKE.cmd"],cwd=ROOT)
   messagebox.showinfo("토스 실전 테스트","토스 전용 Selenium Chrome에서 패션잡화 카테고리 실제 상품 5개를 수집합니다.\n최초 사용이면 먼저 '토스 Selenium 로그인'을 실행하세요.")
  except Exception as e:messagebox.showerror("토스 실전 테스트",str(e))

 def repair(self):
  migrated=migrate_previous_install_data(force=True)
  init_db()
  for p in [ROOT/"logs",ROOT/"evidence",ROOT/"outputs",ROOT/"posts",ROOT/"backups"]:p.mkdir(exist_ok=True)
  self.health();m=("\n이전 버전 연결 설정 승계: "+", ".join(migrated.get("copied") or [])) if migrated.get("copied") else ""
  messagebox.showinfo("자동 복구","DB/필수 폴더와 3사 연결 설정을 점검했습니다."+m+"\n\n토스 API가 실패하면 Selenium 보완 수집으로 자동 전환합니다.\n가격은 공식 API 실패 상품만 Chrome에서 핵심키워드→풀네임 순으로 재검증합니다.\n현재 접근제한이 감지된 사이트는 추가 요청을 자동 중단합니다.")
 def loadlog(self):
  p=ROOT/"logs"/"studio.log";self.logbox.delete("1.0","end");self.logbox.insert("1.0",p.read_text(encoding="utf-8") if p.exists() else "로그 없음")

 def _selected_product_id(self):
  sel=self.tree.selection()
  if not sel:return None
  return int(sel[0])

 def _video_selected_product_id(self):
  display=str(getattr(self,"video_product_var",tk.StringVar(value="")).get() or "") if hasattr(self,"video_product_var") else ""
  if display and hasattr(self,"video_product_map") and display in self.video_product_map:
   return int(self.video_product_map[display])
  return self._selected_product_id()

 def refresh_video_products(self):
  if not hasattr(self,"video_product_combo"):return
  con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
  try:rows=con.execute("SELECT id,product_no,name FROM products WHERE status NOT LIKE '추천제외:%' ORDER BY COALESCE(product_no,id),id LIMIT 500").fetchall()
  finally:con.close()
  current=self.video_product_var.get();self.video_product_map={}
  vals=[]
  for r in rows:
   text=f"TOP {r['product_no'] or '-'} · {r['name']}"
   if text in self.video_product_map:text=f"{text} · ID {r['id']}"
   self.video_product_map[text]=int(r["id"]);vals.append(text)
  self.video_product_combo["values"]=vals
  if current in self.video_product_map:self.video_product_var.set(current)
  elif vals:self.video_product_var.set(vals[0])

 def _render_video_plan(self,path,scenes,plan):
  if hasattr(self,"video_tree"):
   self.video_tree.delete(*self.video_tree.get_children())
   for scene in scenes:
    summary=re.sub(r"\s+"," ",str(scene.get("prompt") or ""))[:260]
    self.video_tree.insert("","end",values=(scene.get("scene"),f"{int(scene.get('start',0)):02d}-{int(scene.get('end',0)):02d}초",scene.get("purpose"),scene.get("caption"),summary))
  source="Ollama 무료 로컬 AI" if plan.get("planning_source")=="ollama_local_free" else "안전 기본기획"
  model=(" · "+str(plan.get("ollama_model"))) if plan.get("ollama_model") else ""
  summary=f"{source}{model} | 콘셉트: {plan.get('concept','-')} | 타깃: {plan.get('target_customer','-')} | 훅: {plan.get('hook_text','-')} | CTA: {plan.get('cta_text','-')}"
  if hasattr(self,"video_plan_summary"):self.video_plan_summary.set(summary)
  if hasattr(self,"video_info"):self.video_info.set(f"12컷 영상기획 완료: {path}")
  if hasattr(self,"video_pb"):self.video_pb["value"]=100

 def _video_progress(self,done,total,msg):
  pct=int(done/max(1,total)*100)
  self.q.put(("video",pct,msg))

 def video_auto_setup(self):
  def job():
   try:
    import subprocess
    p=subprocess.run(["cmd","/c","09_AI_VIDEO_AUTO_SETUP.cmd"],cwd=ROOT)
    h=video_adapter.health()
    self.q.put(("log","AI영상 자동설정: "+h["message"]))
    self.q.put(("refresh",None))
   except Exception as e:self.q.put(("error","AI영상 자동설정 실패: "+str(e)))
  threading.Thread(target=job,daemon=True).start()

 def video_storyboard(self):
  pid=self._video_selected_product_id()
  if not pid:return messagebox.showwarning("AI 영상","먼저 영상 기획할 제품을 선택하세요.")
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    ph=video_adapter.planning_health();self.q.put(("video",5,ph.get("message","Ollama 영상기획 준비")))
    self.q.put(("video",15,"상품 원고·카테고리 분석 → 영상 콘셉트 생성 중"))
    path,scenes=video_adapter.save_storyboard(pid,force_ai=True)
    plan=video_adapter.read_storyboard(path)
    self.q.put(("video",95,"12컷 프롬프트·자막·CTA 정리 중"))
    self.q.put(("video_plan_done",str(path),scenes,plan));self.q.put(("refresh",))
   except Exception as e:self.q.put(("video",0,"영상기획 실패: "+str(e)))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def video_generate_selected(self):
  pid=self._video_selected_product_id()
  if not pid:return messagebox.showwarning("AI 영상","먼저 영상 기획할 제품을 선택하세요.")
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    h=video_adapter.health()
    self.q.put(("video",0,"AI 영상 엔진 점검: "+h["message"]))
    if not h["ready"]:raise RuntimeError(h["message"])
    out=video_adapter.generate_product(pid,self._video_progress)
    self.q.put(("video",100,"완성: "+str(out)))
    self.q.put(("refresh",))
   except Exception as e:
    self.q.put(("video",0,"실패: "+str(e)))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def video_generate_all(self):
  if self.worker and self.worker.is_alive():return messagebox.showwarning("실행 중","다른 작업이 실행 중입니다.")
  def job():
   try:
    h=video_adapter.health()
    if not h["ready"]:raise RuntimeError(h["message"])
    outs=video_adapter.generate_all(self._video_progress)
    self.q.put(("video",100,f"전체 영상 완료: {len(outs)}개"))
    self.q.put(("refresh",))
   except Exception as e:self.q.put(("video",0,"전체 생성 실패: "+str(e)))
  self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

 def open_video_folder(self):
  p=ROOT/"video"/"outputs";p.mkdir(parents=True,exist_ok=True)
  try:os.startfile(str(p))
  except Exception as e:messagebox.showerror("폴더",str(e))

 def video_setup_help(self):
  p=ROOT/"video"/"README_SETUP_KR.txt"
  messagebox.showinfo("AI 영상 설정",
   "ComfyUI + Image-to-Video workflow를 연결하면 제품별 12컷×5초=60초 영상을 자동 생성합니다.\\n\\n"
   "자세한 설정: "+str(p))

 def _maybe_video_after_pipeline(self):
  if not getattr(self,"video_include",None) or not self.video_include.get():return
  h=video_adapter.health()
  if not h["ready"]:
   self.emit("AI영상 단계 건너뜀: "+h["message"]);return
  self.emit("AI영상 전체 생성 시작")
  video_adapter.generate_all(self._video_progress)
  self.emit("AI영상 전체 생성 완료")

 def toss_sharelink_diag(self):
  try:
   subprocess.Popen(["cmd","/c","11_TOSS_SHARELINK_PC_DIAGNOSTIC.cmd"],cwd=ROOT)
   messagebox.showinfo("토스 쉐어링크","Chrome 창이 열리면 처음 한 번만 정상 로그인하세요.\n로그인 쿠키는 전용 프로필에 유지됩니다.")
  except Exception as e:messagebox.showerror("토스 쉐어링크",str(e))

 def toss_url_manager(self):
  p=ROOT/"data"/"toss_manual_urls.json"
  if not p.exists():p.write_text("{}",encoding="utf-8")
  top=tk.Toplevel(self);top.title("토스 상품/쉐어 URL 관리");top.geometry("820x560")
  ttk.Label(top,text="상품명 → 토스 상품/쉐어 URL 매핑",font=("Malgun Gothic",12,"bold")).pack(anchor="w",padx=10,pady=(10,4))
  ttk.Label(top,text="Android 없이 토스 가격을 검증하려면, 확보한 토스 상품/쉐어 URL을 여기에 저장하세요. 없는 상품은 미검증으로 남기고 전체 작업은 계속됩니다.",
            wraplength=780,foreground="#666").pack(anchor="w",padx=10)
  txt=tk.Text(top,font=("Consolas",10));txt.pack(fill="both",expand=True,padx=10,pady=10)
  txt.insert("1.0",p.read_text(encoding="utf-8"))
  def save():
   try:
    obj=json.loads(txt.get("1.0","end"))
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    messagebox.showinfo("토스 URL","저장했습니다.")
   except Exception as e:messagebox.showerror("JSON 오류",str(e))
  ttk.Button(top,text="저장",command=save).pack(pady=(0,10))
 def savesettings(self):
  try:(ROOT/"data"/"settings.json").write_text(json.dumps(json.loads(self.settext.get("1.0","end")),ensure_ascii=False,indent=2),encoding="utf-8");messagebox.showinfo("설정","저장 완료")
  except Exception as e:messagebox.showerror("설정 오류",str(e))
if __name__=="__main__":
 if "--chrome-bridge" in sys.argv:
  from chrome_bridge import run_server
  run_server()
 else:
  App().mainloop()
