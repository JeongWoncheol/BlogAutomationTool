[v8.08.52 Ollama 원고 자연어 개선]
- 제품 원고: 사람과 대화하듯 편안한 존댓말, 자연스러운 감탄/질문, 문장 호흡 다양화
- Ollama 초안이 ~합니다/~됩니다 보고서체 또는 AI 상투표현이 과하면 자동 재작성
- 실제 사용 근거가 없을 때 내돈내산/직접 사용 경험을 지어내지 않는 원칙 유지
- 연예인 착장 원고도 기사 요약체 대신 자연스러운 패션 대화체로 개선

Naver Blog Automation Studio v8.08.52 - CLEAN RUNTIME / OLLAMA HUMAN TONE
=====================================================

이 배포본은 v8.08.50 실행/운영에 필요하지 않은 과거 버전 변경내역,
회귀 테스트, 개발용 감사(audit) 파일, 중복 진단 파일을 제거한 경량본입니다.

[기본 실행]
1) 최초 1회: 01_INSTALL.cmd
2) Chrome 확장 설치/갱신: 15_INSTALL_NORMAL_CHROME_EXTENSION.cmd
3) 프로그램 실행: START_STUDIO.cmd

[현재 주요 설정]
- 쿠팡 Partners API: 83_COUPANG_PARTNERS_API_SETUP.cmd
- NAVER 이미지 API HUB: 92_NAVER_IMAGE_API_SETUP.cmd
- 무료 로컬 AI(Ollama): 88_OLLAMA_FREE_AUTO_SETUP.cmd
- 착장 Vision AI: 94_OLLAMA_VISION_AUTO_SETUP.cmd
- Toss Sharelink API: 97_TOSS_SHARELINK_API_SETUP.cmd
- OpenAI API(선택): 90_OPENAI_API_SETUP.cmd
- AI 영상(선택): 09_AI_VIDEO_AUTO_SETUP.cmd

[설정 확인용으로 남긴 최소 진단]
- Android Toss: 05_ANDROID_TOSS_DIAGNOSTIC.cmd
- Chrome Collector: 16_NORMAL_CHROME_COLLECTOR_TEST.cmd
- ComfyUI: 24_COMFYUI_DEEP_DIAGNOSTIC.cmd
- 쿠팡 API: 84_COUPANG_PARTNERS_API_TEST.cmd
- Ollama: 89_OLLAMA_FREE_AI_TEST.cmd
- OpenAI: 91_OPENAI_API_TEST.cmd
- NAVER 이미지 API: 93_NAVER_IMAGE_API_TEST.cmd
- 이미지 3장 수집 체인: 95_IMAGE_SOURCE_CHAIN_DIAGNOSTIC.cmd
- Toss API: 98_TOSS_SHARELINK_API_TEST.cmd

[중요 폴더]
- modules/          프로그램 기능 모듈
- chrome_extension/ Chrome 자동화 확장
- data/             DB 및 설정/이력
- config/           SEO 정책
- templates/        블로그 템플릿
- tools/            OCR 등 실제 런타임 도구
- video/            AI 영상 설정

실행 중 logs/, outputs/, evidence/, posts/, backups/ 등은 자동 생성됩니다.
기존 버전의 API 키/Chrome 프로필은 프로그램의 이전 버전 설정 승계 로직으로 가져옵니다.

※ 기능_한눈에보기.txt는 프로그램 내부 Workflow Assistant가 직접 읽으므로 삭제하지 마세요.
