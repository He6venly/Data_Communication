# HW4 - ASCII Evolution

2026학년도 2학기 데이터통신 2조 · **분석 및 개발 준비** · 마감 **2026-11-09 23:59**

우리 조의 ASCII 입력 그림 세 장을 원격 Work Assigner와 로컬 Worker N개가 TCP로 나누어 3,000 Round 진화시키는 과제임. N=1과 서로 다른 무작위 N(4~8)의 원격 실행 두 회에서 동일한 해시를 얻어야 함.

언어는 **Python 추천 단계이며 미확정**. 프로그램·G2 canvas·실측 결과는 아직 없음.

## 저장소 관리

- 개발저장소에는 코드와 README만 관리
- 계획서·자료점검·제출 체크리스트는 로컬 G2HW4/문서/에서 관리
- canvas는 로컬 G2HW4/canvas/에서 관리
- 실행결과·로그·검증기록·시연자료·제출물은 G2HW4의 별도 로컬 폴더에서 관리
- 빈 코드 폴더는 로컬에만 유지하며 코드 작성 시 Git에 추가

예정 코드 구성: src/assigner/, src/worker/, src/common/, tools/, tests/.

## 핵심 요구사항

- canvas: 각 80줄×160글자, ASCII·LF·12,880바이트
- 각 그림에 G2 + 높이 5줄 이상 문구 2개 이상, 그림마다 다른 문구·배치
- 점 비율 4~6%, 글자 획 384칸 이상
- Assigner: Main 1 + Handler N, 공유 Mutex 1 + Condition 2
- Worker 간 직접 통신 금지, 모든 Halo는 Assigner가 중계
- 최종 검증: 세 실행의 31개 해시 일치, 같은 원격 실행의 round·로그·GIF 제출
