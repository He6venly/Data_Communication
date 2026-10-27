# HW4 - ASCII Evolution

2026학년도 2학기 데이터통신 2조 · **분석 및 개발 준비** · 마감 **2026-11-09 23:59**.

우리 조가 만든 ASCII 입력 그림 세 장을 원격 Work Assigner와 로컬 Worker N개가 TCP로 나누어 3,000 Round 진화시키는 과제다. N=1과 서로 다른 무작위 N(4~8)의 원격 실행 두 회가 같은 해시를 내야 한다.

**언어는 Python 추천 단계**다. Java 장단점·필수 요구·구현 순서·검증·제출 목록은 [계획서](docs/계획서.md)를 따른다.

| 경로 | 용도 |
| --- | --- |
| [docs/계획서.md](docs/계획서.md) | 과제 해석, 언어 비교, 설계 제안, 일정 |
| [docs/자료점검.md](docs/자료점검.md) | 제공 자료 전체 목록과 실제 검사 결과 |
| [docs/제출체크리스트.md](docs/제출체크리스트.md) | 구현·실행·제출 완료 조건 |
| src/assigner, src/worker, src/common | 프로그램 코드 예정 |
| canvas | 우리 조 입력 그림 예정 |
| tools | 생성·검사·GIF·실행 보조 예정 |
| tests | 규칙·프로토콜·통합 검사 예정 |

현재는 문서와 폴더만 준비했다. 실행 가능한 과제 코드·G2 canvas·실측 결과·제출 ZIP은 아직 없다. 교수님 원본은 로컬 G2HW4/HW4_student_pack에 보존하고 실행결과·로그·시연·제출 staging은 Git 밖에서 실행별로 관리한다.

canvas는 각 80줄×160글자·LF·12,880바이트, G2와 큰 문구 2개 이상, 점 비율 4~6%, 획 384칸 이상이어야 한다. 세 장의 문구와 배치를 다르게 한다. ‘조 소개’는 선택 주제다.

Assigner는 Main 1 + Handler N, 공유 Mutex 1 + Condition 2로 구현한다. HW3의 Ring·장애 복구·Dispatcher Pool을 가져오지 않는다. 키 파일은 저장소에 포함하지 않는다.
