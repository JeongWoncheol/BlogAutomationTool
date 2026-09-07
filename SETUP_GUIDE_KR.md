# 실행 준비 분석 및 설정 가이드

분석일: 2026-09-07. 대상: 이 폴더의 Naver Blog Automation Studio v8.08.52 소스.

이 프로그램은 Windows에서 실행하는 Python/Tkinter 데스크톱 앱이다. 상품 수집 → AI 원고 → 실제 상품 사진 3장 → 가격 비교 → 품질검수 → 네이버 블로그 임시저장을 수행한다. 공개 발행은 사용자가 네이버에서 직접 완료해야 한다.

아래는 최초 코드·설정·설치 스크립트 분석 결과다. 이후 Python 의존성 설치와 전용 Chrome 프로필 설정을 완료했고, 착장 기능을 왈라랜드 기반으로 변경했다. 현재 설정 순서는 [IMPROVEMENTS_KR.md](IMPROVEMENTS_KR.md), 착장 사용법은 [WALA_SETUP_KR.md](WALA_SETUP_KR.md)를 우선 참고한다. Selenium·Appium·httpx2·Pydantic은 설치되었고 DB와 착장 원고도 생성되어 있다. 아래 표의 미설치·DB 없음은 최초 조사 시점의 기록이다. API 인증, 네이버 로그인, 실제 임시저장은 수행하지 않았다.

## 1. 현재 PC에서 확인한 상태

| 항목 | 확인 결과 | 필요한 조치 |
|---|---|---|
| Windows | Windows 10 Enterprise LTSC, Build 19044 | 앱은 Windows 지향. 최신 Ollama의 공식 Windows 요구사항과 차이 확인 |
| Python | 3.13.5, `python`과 `py -3`가 같은 설치를 가리킴 | 기존 Python으로 의존성 설치 가능 여부 확인 |
| Tkinter | Tcl/Tk 8.6.15 확인 | 별도 웹 프런트엔드 설치 불필요 |
| Pillow | 11.3.0 설치됨 | 현재 requirements 하한 충족 |
| Selenium | 현재 Python에 없음 | 필수 설치 |
| Appium Python Client | 현재 Python에 없음 | requirements에 포함. Android 기능에서 사용 |
| Chrome | `C:\Program Files\Google\Chrome\Application\chrome.exe` 존재 | 수집 확장 설치 및 프로필 선택 |
| RAM / GPU | 약 15.7GB / Intel Iris Xe | 프로젝트 자동 선택 로직상 Qwen3 4B 대상 |
| Ollama | PATH·기본 설치 위치에서 실행 파일 미확인, 11434 리스너 없음 | 로컬 AI 사용 시 설치·기동·모델 다운로드 |
| FFmpeg / Appium / ADB / Java | PATH에서 미확인 | 해당 선택 기능을 쓸 때 설치/경로 설정 |
| Node / npm | PATH에 존재 | Android 설치 도구가 사용. 기본 앱 실행에는 불필요 |
| 로컬 서비스 | 8765 / 11434 / 8188 / 4723 리스너 없음 | 사용하는 서비스를 설치 도구나 앱으로 시작 |
| API 인증 | 저장소에 인증 JSON 없음. 관련 Coupang/Toss/OpenAI 환경변수도 미설정 | 사용하는 연동의 키 발급·입력 |
| DB / 원고 | `data/studio.db`, 기존 `posts/` 없음 | DB는 앱 초기화 시 생성. 상품 수집 또는 외부 원고 가져오기 필요 |

Python 소스 65개 AST 구문 검사, Chrome 확장 JavaScript 7개 `node --check`, 배포 JSON 7개 파싱은 통과했다. 이는 로그인·수집·원고 생성·임시저장 성공을 의미하지 않는다.

## 2. 기능별 필요한 설정

| 원하는 동작 | 필요한 것 | 처음에는 생략 가능한 것 |
|---|---|---|
| 앱 창 실행 | Python + Tkinter + requirements 패키지 | API 키, Android, 영상 도구 |
| 상품/트렌드 웹 수집 | Chrome + 수집 확장 + 8765 브리지 + 올바른 일반 Chrome 프로필 | ComfyUI, FFmpeg, Android |
| 로컬 AI 원고 | Ollama 서버 + Qwen3 모델 | OpenAI API |
| 상품 이미지 검색 | 쿠팡/네이버 API, 일반 Chrome을 쓰는 수집 경로 | AI 이미지 생성 도구. 본문 사진은 실제 상품 사진 정책 |
| 쿠팡 상품 조회·제휴 링크 | Coupang Partners API Access Key / Secret Key | Toss Android |
| 네이버 이미지 | NAVER API HUB 이미지 API 권한·Client ID/Secret | 네이버 블로그 로그인은 이 API와 별개 |
| 네이버 쇼핑 가격 API | 기존 NAVER Developers 검색 API Client ID/Secret | API HUB 키로 대체된다고 가정하면 안 됨 |
| Toss 상품 조회 | Sharelink Creator API 키·읽기 권한·등록 IP 또는 PC 로그인 수집 경로 | Android는 필수 아님 |
| 블로그 임시저장 | Selenium + 전용 Chrome 프로필 + 그 브라우저의 네이버 로그인 + 준비된 원고 | OpenAI, 영상 도구 |
| 외부 원고 임시저장 | 지원 형식의 폴더/ZIP + 블로그 연결 | 원고가 완성되어 있으면 상품 수집·AI 생성 생략 가능 |
| 연예인 착장 분석 | 왈라랜드 공개 원문, 선택적으로 기존 Ollama/Qwen3-VL | NAVER 검색 키·영상 생성 도구. [현재 가이드](WALA_SETUP_KR.md) |
| AI 상품 영상 | FFmpeg + ComfyUI + I2V 모델/노드 + API 형식 workflow + 실제 상품 이미지 | 기본 상품 원고·임시저장에는 불필요 |

근거: [앱 파이프라인](app.py), [설정](data/settings.json), [실제 사진 정책](config/seo_policy.json), [작업 도우미](modules/workflow_assistant.py).

## 3. 기본 실행 준비 순서

### 3-1. 의존성 설치

프로젝트 폴더에서 `01_INSTALL.cmd`를 실행한다. 이 파일의 실제 내용은 `python -m pip install -r requirements.txt`다.

의존성은 다음 세 가지다.

```text
selenium>=4.28.0
Pillow>=10.0.0
Appium-Python-Client>=4.4.0
```

`01_INSTALL.cmd`는 Python·Chrome·Ollama를 설치하지 않는다. `START_STUDIO.cmd`는 `py -3`를 우선 사용하지만 대부분의 설정 도구는 `python`을 사용한다. 현재 PC에서는 두 명령이 같은 Python을 가리킨다. 다른 PC나 가상환경에서는 설치한 Python과 실행하는 Python을 반드시 맞춰야 한다. 가상환경을 선택한다면 그 환경의 `python`으로 requirements 설치와 `app.py` 실행을 모두 수행한다.

Selenium은 `webdriver.Chrome()`을 사용하며 저장소에 ChromeDriver 바이너리를 넣어두는 방식이 아니다. 최초 드라이버 준비가 실패하면 인터넷 연결과 Selenium의 드라이버 관리 오류를 확인한다.

### 3-2. 비어 있는 블로그 Chrome 프로필 수정

[data/settings.json](data/settings.json)의 현재 값은 `"chrome_profile": ""`다. 다음처럼 바꿔야 한다.

```json
"chrome_profile": "NaverBlogAutomationProfile"
```

현재 코드가 `Path(LOCALAPPDATA) / settings().get("chrome_profile", "NaverBlogAutomationProfile")`로 경로를 계산하므로, 빈 문자열이면 기본 폴더명이 적용되지 않고 `%LOCALAPPDATA%` 자체가 Chrome 데이터 디렉터리가 된다. 실제 계산 결과도 `C:\Users\Administrator\AppData\Local`이었다.

전용 이름을 지정하면 `%LOCALAPPDATA%\NaverBlogAutomationProfile`을 사용한다. 일반 수집용 Chrome 프로필과는 다른 설정이다. 근거: [blog_adapter.py 79행](modules/blog_adapter.py), [실제 exact 엔진 51행](modules/blog_adapter_v759_exact.py).

### 3-3. Chrome 수집 확장 설치

1. `15_INSTALL_NORMAL_CHROME_EXTENSION.cmd` 실행.
2. 수집에 사용할 일반 Chrome 프로필 선택. 재선택은 `15B_SELECT_CHROME_PROFILE.cmd`.
3. 열린 `chrome://extensions/`에서 개발자 모드를 켠다.
4. 압축해제된 확장 프로그램 로드 대상으로 다음 폴더를 선택한다.

```text
%LOCALAPPDATA%\NaverBlogAutomationStudio\chrome_extension
```

설치 도구는 소스 확장을 이 고정 경로에 복사한다. 확장을 Chrome에 등록하는 마지막 과정은 사용자가 해야 한다. 동일 수집 확장이 여러 개 등록되어 있으면 기존 중복 확장을 정리하고 현재 복사본을 사용한다.

확장 이름은 `NaverBlog Normal Chrome Collector`, 저장소 manifest 버전은 `4.6.8`이다. 버전과 heartbeat를 프로그램이 검사한다. `16_NORMAL_CHROME_COLLECTOR_TEST.cmd`로 네이버쇼핑·쿠팡 수집을 검사한다. 이 테스트는 블로그 글쓰기 테스트가 아니다.

브리지는 `http://127.0.0.1:8765`에서 자동 기동된다. 8765는 Python과 확장 양쪽에 연결되어 있으므로 `settings.json`만 바꿔 다른 포트로 쓰면 연결이 어긋날 수 있다.

근거: [설치 도구](15_INSTALL_NORMAL_CHROME_EXTENSION.py), [확장 복사](stable_extension.py), [일반 Chrome 프로필](chrome_profile.py), [수집 클라이언트](modules/chrome_collector.py).

### 3-4. AI 원고 설정

기본 경로는 Ollama다. `88_OLLAMA_FREE_AUTO_SETUP.cmd` → `89_OLLAMA_FREE_AI_TEST.cmd` 순서로 실행한다. 88번은 Ollama가 없으면 winget 설치를 시도하고, 로컬 서버를 시작하고, 선택한 Qwen3 모델을 내려받는다. winget이 없으면 [공식 Ollama 설치](https://ollama.com/download/windows)가 필요하다.

서버 주소는 `http://127.0.0.1:11434`다. 현재 PC는 NVIDIA VRAM이 감지되지 않고 RAM이 24GB 미만이므로, 프로젝트의 `recommend_model()`은 `qwen3:4b`를 선택한다. 앱의 AI 설정에서 `초고속 · 4B 중심` 프로필을 선택하면 `ollama_num_ctx=8192` 등도 함께 조정된다. 기본 배포값 `qwen3:8b`를 그대로 유지하는 것과 다르다. 생성 속도는 실제로 측정하지 않았다.

다만 최신 Ollama 공식 문서는 Windows 10 22H2 이상을 요구한다. 현재 PC의 LTSC Build 19044는 이 요구사항보다 이전이므로 설치·실행 호환성을 보장할 수 없다. 지원 OS에서 실행하거나, 아래 OpenAI 선택 경로를 검토해야 한다. [Ollama Windows 요구사항](https://docs.ollama.com/windows).

Ollama가 없어도 앱은 안전 원고 fallback으로 진행할 수 있다. 따라서 화면에 콘텐츠 기능이 정상으로 표시되는 것만으로 AI가 연결됐다고 판단하면 안 된다. AI 모델이 연결되어 있어도 원고 품질검수 통과는 별도다. 근거: [Ollama 선택 로직](modules/ollama_local.py), [콘텐츠 health 및 fallback](modules/content_adapter.py).

### 3-5. 앱 실행과 네이버 로그인

`START_STUDIO.cmd`로 실행한다. 일반 Chrome에서 이미 네이버에 로그인했더라도, 블로그 작성용 Selenium Chrome에서는 다시 로그인해야 할 수 있다. 작성 대상이 준비된 뒤 임시저장을 실행하면 열린 전용 Chrome에서 수동 로그인한다. 로그인 대기 설정은 현재 180초다.

현재 글쓰기 경로는 `blog_adapter.run()` → `blog_adapter_v759_exact.run()`이다. 모든 공개 임시저장 버튼이 이 엔진을 사용한다. Windows 키보드 입력을 사용하는 경로가 있으므로 자동 작성 중에는 해당 PC의 키보드·마우스 사용과 창 전환을 피하고 화면을 유지한다.

대상 원고가 없거나 조건에 맞는 상품이 0개이면 Chrome을 열지 않고 끝나는 동작이 있다. 이때는 로그인 문제가 아니라 원고/이미지/중복 판정부터 확인한다.

## 4. 외부 API별 설정

### 4-1. Coupang Partners

쿠팡 파트너스 계정에서 사용할 수 있는 Partners API Access Key와 Secret Key를 준비한다. 이 코드는 affiliate API를 사용하므로 판매자 WING API 안내와 혼동하면 안 된다. 계정의 실제 API 접근 권한은 로컬에서 확인하지 못했다.

`83_COUPANG_PARTNERS_API_SETUP.cmd` → `84_COUPANG_PARTNERS_API_TEST.cmd`.

저장 파일은 `data/coupang_partners_credentials.json`, 필드는 `access_key`, `secret_key`다. 환경변수 `COUPANG_PARTNERS_ACCESS_KEY`, `COUPANG_PARTNERS_SECRET_KEY`도 지원하며 파일보다 우선한다.

상품 검색과 이미지/가격 조회, 제휴 deeplink 생성에 사용한다. 키가 없어도 모든 기능이 동일하게 작동하는 것은 아니다. 특히 신규 환경에는 재사용할 쿠팡 snapshot이 없어 API 중심 기능이 결과를 만들지 못할 수 있다. 근거: [쿠팡 API](modules/coupang_partners_api.py), [트렌드 상품 연결](modules/trend_coupang_adapter.py).

### 4-2. NAVER 이미지 API HUB와 기존 쇼핑 API를 구분

이 저장소의 가장 중요한 설정 불일치다.

| 기능 | 실제 호출 주소 | 인증 종류 |
|---|---|---|
| 상품 이미지 | `naverapihub.apigw.ntruss.com/search/v1/image` | API HUB Client ID/Secret, `X-NCP-APIGW-*` 헤더 |
| 연예인 뉴스·블로그·이미지 | 동일 HUB의 `/search/v1/news`, `/blog`, `/image` | API HUB 키 |
| 쇼핑 가격 | `openapi.naver.com/v1/search/shop.json` | Developers 검색 API 키, `X-Naver-*` 헤더 |

공식 문서상 기존 Developers 키를 API HUB에 그대로 사용할 수 없다. [공식 이관 가이드](https://guide.ncloud-docs.com/docs/apihub-migration).

이미지는 네이버 클라우드 콘솔 → NAVER API HUB → 서비스 이용 신청 → Application 등록 → 이미지 API 선택 → Client ID/Secret 확인 → `92_NAVER_IMAGE_API_SETUP.cmd` 입력 → `93_NAVER_IMAGE_API_TEST.cmd` 순서다. 착장 분석까지 사용할 때는 뉴스·블로그 API 권한도 준비한다. [Application 등록 안내](https://guide.ncloud-docs.com/docs/apihub-application).

92번은 HUB 키를 `data/naver_image_api_credentials.json`의 `client_id`, `client_secret`, `api_mode`에 저장한다. 그런데 쇼핑 API도 이 파일을 fallback으로 읽는다. 92번을 한 번 실행했다고 네이버 이미지와 쇼핑 가격이 모두 인증되는 것은 아니다.

현재 코드 변경 없이 양쪽 키를 명확히 지정하려면 `data/settings.json`에 다음 필드를 각각 설정한다. 아래는 기존 JSON에 추가/병합할 항목이며 전체 파일을 대체하는 내용이 아니다.

```json
{
  "naver_api_hub_client_id": "API_HUB에서_발급받은_ID",
  "naver_api_hub_client_secret": "API_HUB에서_발급받은_SECRET",
  "naver_search_client_id": "Developers_검색_API_ID",
  "naver_search_client_secret": "Developers_검색_API_SECRET"
}
```

HUB 필드를 명시하는 이유는 착장 모듈이 `naver_search_client_id`도 fallback으로 읽기 때문이다. 쇼핑 키만 추가하면 착장 모듈이 HUB 파일의 키보다 쇼핑 키를 먼저 선택한다. 네 필드로 두 종류를 분리하면 이미지·착장·쇼핑 호출의 키 선택이 명확해진다.

쇼핑 API 키에는 검색 API 사용 권한이 필요하다. 기존 Developers API의 본인 계정 사용 가능 여부와 실제 호출 성공을 확인해야 한다. HUB 키만 발급 가능한 환경이라면 현재 쇼핑 어댑터는 추가 수정이나 다른 수집 경로 검토가 필요하다. [쇼핑 검색 공식 문서](https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md).

`data/settings.json`은 Git 추적 파일이다. 위처럼 실제 키를 입력한 파일을 커밋하거나 공유하면 안 된다. `.env`를 자동 로드하는 구현은 없으므로 임의의 `.env` 파일을 만드는 것만으로는 적용되지 않는다.

근거: [이미지 인증 17행](modules/naver_image_api.py), [쇼핑 인증 20행](modules/naver_shopping_api.py), [착장 인증 106행](modules/celebrity_style_adapter.py).

### 4-3. Toss Sharelink

Toss Sharelink Creator에 접근 가능한 계정과 API Access Key/Secret Key를 준비한다. 코드의 기본 인증 흐름은 `https://oauth2.cert.toss.im/token`에서 `client_credentials` 토큰 발급 → `https://sharelink.toss.im/openapi/health` → `/products/best-selling` 조회다. 기본 scope는 `sharelink:read`다.

`97_TOSS_SHARELINK_API_SETUP.cmd` → `98_TOSS_SHARELINK_API_TEST.cmd`.

97번은 키를 저장하면서 실제 인증·상품 조회도 수행한다. 안내에 따라 Creator 관리자에 호출 PC의 출발지 공인 IP를 등록한다. Publisher ID와 Category ID는 도구에서 선택 입력이다. 권한 발급·IP 제한의 최신 계정별 조건은 Creator 관리자에서 확인해야 하며, 이번 분석에서는 유효한 키로 검증하지 않았다.

저장 파일은 `data/toss_sharelink_api_credentials.json`이다. 핵심 항목은 `access_key`, `secret_key`, `scope`; 직접 설정하는 경우 `access_token`도 지원한다. 환경변수 `TOSS_SHARELINK_ACCESS_KEY`, `TOSS_SHARELINK_SECRET_KEY`, `TOSS_SHARELINK_ACCESS_TOKEN`을 읽는다.

PC 웹 경로를 사용할 때는 `73_TOSS_SELENIUM_LOGIN_SETUP.cmd`에서 열린 Toss 전용 Chrome에 로그인한다. 기본 상품 수집은 API를 먼저 시도하며 API 실패 작업을 Selenium으로 보완하는 코드가 있다. 하지만 이 보완도 해당 웹 계정의 접근과 로그인이 필요하다. `toss_sharelink_enabled=false`와 `toss_sharelink_api_enabled=true`는 서로 다른 설정이므로 앞의 값만 보고 Toss API가 꺼졌다고 판단하면 안 된다.

근거: [Toss API](modules/toss_sharelink_api.py), [설정 도구](97_TOSS_SHARELINK_API_SETUP.py), [수집 분기](modules/search_adapter.py), [PC 로그인](modules/toss_multi_frame_collector.py).

### 4-4. OpenAI 선택 경로

로컬 AI 대신 또는 실패 시 유료 API를 사용하려면 `90_OPENAI_API_SETUP.cmd` → `91_OPENAI_API_TEST.cmd`를 실행한다. `data/openai_api_credentials.json`에 `api_key`, `model`을 저장한다. 코드의 기본 모델 `gpt-5.6-sol`은 [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-sol)에 존재한다. 실제 계정 접근·사용 한도는 별도다.

중요: 90번만 실행하면 자동 호출은 활성화되지 않는다. `openai_auto_enabled=true`가 추가로 필요하다. 또한 90번은 `llm_provider_priority`를 OpenAI 우선으로 바꾼다. Ollama를 먼저 쓰고 싶다면 다음처럼 지정한다.

```json
{
  "openai_auto_enabled": true,
  "llm_provider_priority": ["ollama", "openai", "safe_fallback"]
}
```

OpenAI를 우선할 의도라면 순서를 `["openai", "ollama", "safe_fallback"]`로 둔다. 비용 없는 기본 경로를 유지할 때는 `openai_auto_enabled=false`를 유지한다. `llm_provider` 하나만 바꾸는 것으로 호출 순서를 제어할 수 없다.

91번은 모델 정보 조회 테스트다. 실제 Responses API로 원고를 생성하는 테스트가 아니므로, 통과 후에도 원고 1건의 생성·품질 검증이 필요하다. 근거: [90번 설정](90_OPENAI_API_SETUP.py), [91번 테스트](91_OPENAI_API_TEST.py), [실제 제공자 선택과 호출](modules/content_adapter.py).

## 5. 첫 작업은 단계별로 확인

1. 의존성·Chrome 프로필·확장 연결을 먼저 준비한다.
2. 완성된 외부 원고 1건을 지원 형식으로 가져오거나, 상품을 수집해 작업 대상을 만든다.
3. 원고가 없다면 AI로 제목·본문·태그를 생성하고 결과를 확인한다.
4. 테스트 작성에서 텍스트만 임시저장을 실행해 전용 네이버 로그인·글 입력·저장을 확인한다.
5. 사진 3장을 수집·검증한 뒤 이미지 3장 임시저장을 확인한다.
6. 제휴 링크와 3사 가격 검증을 추가하고 최종 결과를 확인한다.

일부 작성 버튼은 선택한 한 행이 아니라 미완료 대상 전체에 적용된다. 첫 확인은 실제 데이터 범위를 1건으로 준비해야 한다.

| 임시저장 모드 | 역할 |
|---|---|
| `text_only` | 이미지·가격 비교표를 제외한 원고 저장. 준비된 제목·본문·태그와 해당 원고 검증 조건은 필요 |
| `images_only` | 현재 기본값. 동일상품 사진 3장을 포함한 원고 저장 |
| `price_complete` | 3사 가격 및 대표이미지 검증·비교 이미지까지 준비된 대상 저장 |

전체 실행의 QA는 사진 3장, 태그 수, SEO 서브키워드, 본문 품질, 기본 3개 판매처의 가격·이미지 증거 등을 검사한다. API 연결이 모두 성공해도 동일 모델·용량·구성의 상품이 3개 사이트에 없으면 `QA보완`이 정상적으로 남을 수 있다. 확장 설치 실패와 상품 검증 조건 미충족은 구분해야 한다. 근거: [app.py의 qa()](app.py), [exact 엔진의 대상 선정과 run()](modules/blog_adapter_v759_exact.py).

외부 원고 가져오기는 폴더/ZIP과 `전체_포스트.json`, `전체_포스트_175.json`, `posts.json`, `manifest.json`, 상품별 `post.json` 또는 `제목.txt`/`본문.txt`/`태그.txt` 등의 구조를 인식한다. 아무 문서나 그대로 가져오는 기능은 아니다. 기존 게시글 중복 대조는 별도의 블로그 ID와 RSS/파일 가져오기를 사용한다. 이 ID는 블로그 로그인 자격증명을 대신하지 않는다. 근거: [외부 원고](modules/external_batch_import.py), [기존 게시글 대조](modules/already_posted_adapter.py).

## 6. Android와 영상은 별도 선택 기능

### Android Toss

필요할 때만 Node/npm, Java/JDK와 `JAVA_HOME`, Android SDK/ADB와 `ANDROID_HOME` 또는 `ANDROID_SDK_ROOT`, Appium 서버, UiAutomator2 드라이버, USB 디버깅을 허용한 Android 기기를 준비한다. 휴대폰에는 Toss 앱 설치와 로그인이 먼저 되어 있어야 한다. Appium/드라이버 버전별 요구사항은 [UiAutomator2 공식 저장소](https://github.com/appium/appium-uiautomator2-driver#readme)에서 확인한다.

실행 순서는 `04_ANDROID_ONE_CLICK_REPAIR.cmd` → USB 연결·RSA 허용 → `04B_CONNECT_ANDROID_DEVICE.cmd` → `05_ANDROID_TOSS_DIAGNOSTIC.cmd`다. 04번은 Node/npm이 없으면 설치하지 않고 중단하며, JDK 전체를 준비해주는 스크립트도 아니다.

현재 배포에는 필수 입력 파일 `data/toss_mobile.json`이 없다. Android 모듈은 이 파일을 바로 읽으며 04번은 생성하지 않는다. 따라서 도구 설치만 끝내도 Android 동작은 완성되지 않는다. 필요한 필드는 `automation_name`, `device_name`, `app_package`, `appium_url`, `no_reset`, `new_command_timeout`, `navigation_texts.shopping`, `navigation_texts.search`, `price_regex`, `minimum_identity_score`다. 기기·현재 앱 화면에 맞는 값을 준비하거나 동작하던 설정을 복원해야 한다. 현재 파일로 Android 실행 완료를 보장할 수 없다.

근거: [Android 세션 설정](modules/toss_mobile_adapter.py), [04번 설치 도구](04_ANDROID_ONE_CLICK_REPAIR.py).

### AI 영상

`03_SETUP_FFMPEG.cmd`로 FFmpeg를 준비한다. ComfyUI와 실제 사용할 Image-to-Video 모델·커스텀 노드를 설치하고, ComfyUI 자체에서 동작하는 workflow를 API Format JSON으로 저장해야 한다.

그다음 `09_AI_VIDEO_AUTO_SETUP.cmd`, 자동 탐색 실패 시 `25_SET_COMFYUI_ROOT.cmd`, 마지막으로 `24_COMFYUI_DEEP_DIAGNOSTIC.cmd`를 사용한다. 09번은 기존 ComfyUI와 workflow를 탐색·기동·연결하는 도구이며 모든 모델/노드를 설치해주는 도구가 아니다.

`video/video_engine.json`의 기본 `workflow_api_json`은 `video/workflows/wan22_i2v_api.json`이지만 해당 파일은 저장소에 없다. `comfy_root`, `comfy_url`, workflow 경로, 실제 노드 ID에 맞는 `node_map`을 준비해야 한다. prompt·image 입력 노드와 실제 영상 출력까지 맞아야 렌더링할 수 있다.

기본 URL은 `http://127.0.0.1:8188`, 기본 영상은 12장면 × 5초, 720×1280, 24fps다. 실제 상품 사진을 참조하여 장면 생성 후 FFmpeg로 합친다. 현재 PC에서 이 영상 workflow의 속도·메모리 적합성은 검증하지 않았으므로 기본 블로그 흐름 이후 별도 검증 대상으로 둔다. `local_video_enabled=false`가 현재 기본값이다.

근거: [영상 설정](video/video_engine.json), [영상 준비 검사](modules/video_adapter.py), [자동 탐색](09_AI_VIDEO_AUTO_SETUP.py).

## 7. 문서나 버튼만 믿으면 막히는 부분

| 발견 사항 | 실제 의미 / 대응 |
|---|---|
| `02_ONE_CLICK_ALL_SETUP.cmd` | FFmpeg와 Android 설치 도구만 호출. Python 패키지·Chrome 확장·AI·API 키를 모두 준비하지 않음 |
| `chrome_profile` 빈 문자열 | 블로그 자동화 시작 전에 전용 폴더명 지정 필요 |
| 네이버 키 파일 공유 | HUB와 Developers 키를 분리해야 이미지/착장/쇼핑 인증 혼선 방지 |
| OpenAI 설정 도구 | 키 저장·우선순위 변경은 하지만 자동 호출 활성화는 별도 |
| 연결 상태 READY | 여러 모듈은 키 존재만 확인. 실제 API 호출 테스트와 구분 |
| Android 설정 파일 없음 | `toss_mobile.json` 준비·복원 필요 |
| 기본 영상 workflow 없음 | 실제 ComfyUI API workflow 준비 필요 |
| 이전 버전 자동 승계 | 정해진 `NBlog_v7_*`, `NBlog_v8_*`, `NaverBlog_Automation_Studio_v*_*` 폴더 이름만 탐색. 임의 경로의 설정을 모두 찾아주는 기능 아님 |

아래 여섯 CMD는 코드에서 호출하지만 현재 저장소에 없다.

```text
11_TOSS_SHARELINK_PC_DIAGNOSTIC.cmd
13_3SITE_SEARCH_SMOKE_TEST.cmd
31_LIVE_SAMPLE_3PRODUCT_PRICE_TEST.cmd
77_ANDROID_TOSS_PRICE_IMAGE_TEST.cmd
78_TOSS_SELENIUM_MULTIFRAME_AUDIT.cmd
80_TOSS_SELENIUM_LIVE_SMOKE.cmd
```

따라서 UI의 `3사 검색 연결 테스트` 등 일부 진단 버튼은 파일 누락 때문에 실행되지 않는다. 이 문제는 사용자의 API 키 설정 실수가 아니다. 현재 존재하는 `16`, `73`, `84`, `89`, `93`, `95`, `98`, `05`, `24` 진단을 목적에 맞게 사용하고, 누락 버튼은 배포 파일 복원 또는 코드 보완 대상으로 남긴다. 이 진단들은 서로 완전히 동일한 테스트는 아니다. 근거: [앱의 진단 실행 함수](app.py).

## 8. 저장 위치와 문제 확인 위치

| 위치 | 용도 |
|---|---|
| `data/settings.json` | 실행·AI·이미지·가격·블로그 정책 |
| `data/*credentials*.json` | 연동 인증. Git 제외 대상 |
| `data/normal_chrome_profile.json` | 일반 수집용 Chrome 프로필 선택 |
| `data/studio.db` | 상품·후보·작업 상태 SQLite DB. 별도 DB 서버 불필요 |
| `posts/` | 상품별 원고·사진·관련 산출물 |
| `outputs/` | 진단 CSV·내보내기 결과 |
| `outputs/blog_upload_diagnostics/` | 임시저장 실패 화면·HTML·상태 |
| `logs/studio.log` | 앱 실행 로그 |
| `evidence/` | 상품·가격·이미지 검증 근거 |
| `data/blog_upload_history.json`, `data/published_product_registry.json` | 임시저장/기존 게시글 중복 방지 이력 |
| `video/outputs/` | 영상 산출물 |

기본 경로부터 시작할 때 필요한 작업은 패키지 설치, 비어 있는 Chrome 프로필 설정, 수집 확장 등록, 사용할 AI 연결, 네이버 로그인이다. 상품 API·3사 가격·착장·Android·영상은 해당 기능을 추가하는 순서로 준비한다. 설정과 배포 누락 때문에 현재 상태를 곧바로 전체 자동화 완료 상태로 볼 수는 없다.
