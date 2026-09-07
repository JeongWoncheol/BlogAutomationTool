AI 자연동작 제품영상 v5.1

이 버전의 핵심:
- 제품 선택 → 버튼 1번 → 12장면 × 약 5초 → 약 60초 MP4
- 실제 제품사진을 첫 Reference로 사용
- 1번 장면의 마지막 프레임을 2번 장면의 시작 Reference로 자동 사용
- 2번 장면 마지막 프레임 → 3번 장면 시작 Reference ... 방식으로 연속 연결
- 그래서 12개의 독립 영상보다 동일 인물/환경/동작 연결성이 좋아집니다.
- workflow가 두 번째 reference image를 지원하면 product reference도 매 장면 함께 넣을 수 있습니다.
  video_engine.json:
  dual_reference_supported=true
  secondary_product_reference_node=<노드ID>

GUI:
AI 제품영상 탭
1) 상품/진행현황에서 제품 선택
2) '선택 제품 12컷 스토리보드 생성'
3) 장면을 확인
4) '선택 제품 AI영상 생성'
5) 완료 파일은 video/outputs

ComfyUI 1회 설정:
1) Image-to-Video workflow가 실제로 영상 생성되는지 ComfyUI에서 확인
2) Workflow를 API Format JSON으로 저장
3) video/workflows/wan22_i2v_api.json에 저장
4) video/video_engine.json의 comfy_root와 node_map 설정
5) ffmpeg 설치

권장:
- NVIDIA GPU
- Wan2.2 Image-to-Video 또는 현재 PC에서 안정적으로 도는 I2V workflow
- 첫 테스트는 제품 1개로 진행
- quality_mode: fast / balanced / quality

중요:
AI 모델이 실제 제품의 작은 글자/로고를 완벽히 유지하지 못할 수 있으므로 영상 검수는 필요합니다.
블로그 본문 이미지는 계속 '실제 사진만' 사용합니다.
