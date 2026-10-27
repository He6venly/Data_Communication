# HW4 - ASCII Evolution

2026학년도 2학기 데이터통신 2조 · **Python 확정**

우리 조의 ASCII 입력 그림 세 장을 원격 Work Assigner와 로컬 Worker N개가 TCP로 나누어 3,000 Round 진화시키는 과제임. N=1과 서로 다른 무작위 N(4~8)의 원격 실행 두 회에서 동일한 해시를 얻어야 함.

현재 구현 전 설계 상태임. 아래 패키지·명령은 구현 기준이며 실행 가능한 코드·실측 결과를 의미하지 않음. Python 지정은 사용자 요구, Python 3.12 이상·단일 스레드 Worker·독립 패키지·JSON 로그는 설계 선택임.

업무 비중은 **안선효 4 : 황대겸 3 : 황왕석 3**. 기존 담당 경험과 통합 책임을 반영한 예상 비중이며 코드 줄 수나 실측 시간의 비율이 아님.

## 1. 업무 분담

| 담당 | 비중 | 주 담당 | 전용 코드 경로 | 완료 산출물 |
| --- | ---: | --- | --- | --- |
| 안선효 | 40% | Assigner, Barrier, 실측·분석, 원격 배포, 통합·제출 취합 | `src/assigner/`, `tests/assigner/`, `tests/integration/` | 서버 코드·대역 Worker·통합 검사 코드, 실측표·최종 문서 |
| 황대겸 | 30% | Worker, 규칙 3종, 덧칠·변환, 기준 계산 | `src/worker/`, `tests/worker/` | Worker 코드·규칙 검사·대역 Assigner·통신 없는 기준 계산 도구 |
| 황왕석 | 30% | canvas 생성, Worker 실행 보조, 결과 검증, GIF·시연 자료 제작 | `tools/`, `tests/tools/` | 생성·기동·검사·GIF 코드, G2 입력 3장·검사 기록·영상 초안 |

계획·설명·검증 기록은 `G2HW4/문서/`, 입력은 `G2HW4/canvas/`, 실행 산출물은 `G2HW4/실행결과/` 등 로컬에서 관리함. Git에는 코드와 README만 보관함. 각 담당은 담당 코드 설명을 README에 기록하고 최종 제출용 Readme.txt·AllDefinedLogs.txt는 안선효가 로컬에서 취합함.

### 안선효: Assigner·통합 40%

- 초기 설정·canvas 읽기·형식 검사, N 무작위 결정, 균등 띠 분할, 접속 순서별 k 배정 구현
- Main 1개 + Handler N개, 공유 Mutex 1개 + done_cv/go_cv 2개 구현
- Halo 중계, RESULT 번호·길이 검사, 전체 띠 조립, 독립 snapshot으로 Lock 밖 저장 구현
- round 31개·frame 301개·RoundHash 출력, Assigner 로그·Round/Barrier/전송량 실측 구현
- 오류 발생 시 모든 CV 대기 해제, 소켓 shutdown/close, Handler join을 포함한 종료 처리
- 실제 Worker 없이 시험할 대역 Worker 작성: 정상·지연·잘못된 r/k·중도 종료를 재현
- 실제 구성 통합, N=1 및 원격 무작위 두 실행, 지표 분석·최종 제출 취합 담당
- 코드 README·최종 Readme·AllDefinedLogs 검토 및 제출 ZIP 무결성 확인 담당

예상 비중 내역: Assigner·동기화 25 + 실측·통합·배포·제출 15.

### 황대겸: Worker·계산 30%

- ASSIGN 수신, h+2줄 작업판·cur/next 이중 버퍼, ROUND 수신→계산→RESULT 송신 구현
- rule1_cell, rule2_cell, rule3_cell, repaint, to_brian, to_cyclic 구현
- 덧칠·변환을 Halo 포함 전체 작업판에 적용, 전역 y·좌우 Torus 처리
- 배정 k에 따른 Worker 로그, 처리 Round 수·계산시간 요약, BYE·EOF·오류 처리 구현
- 교수님 규칙 10개, 덧칠 3단계, cyclic, 띠 3개, G11 기준 해시 검증 담당
- 실제 Assigner 없이 시험할 대역 Assigner 작성: ASSIGN·ROUND·BYE·잘린 수신·비정상 메시지 재현
- 통신 없는 전체 판 기준 계산 도구 작성. 제출용 N=1은 실제 Assigner+Worker 실행이라는 점을 구분

예상 비중 내역: 규칙·기준 검증 16 + Worker 통신·로그·대역 검사 14.

### 황왕석: 입력·실행·검증 도구 30%

- G2 canvas 3장 생성기 작성: 문구·글꼴·좌표·seed를 재현 가능하게 관리
- 수치 검사와 문구·높이·서로 다른 배치 육안 확인, 입력 파일은 Git 밖으로 출력
- Worker N개를 별도 프로세스로 실행하는 보조 도구 작성. Worker 내부 모듈을 import하지 않고 전달받은 명령만 실행
- 제공 도구를 기반으로 형식·ASCII/LF·해시·N 조건·누락·행 순서를 엄격히 검사하는 도구 작성
- frame 파일 301개 확인, GIF 제작·프레임 수·처음/마지막 상태 검사
- 실행별 로그·메타정보 정합성 검사, 오류 시 0이 아닌 종료 코드 반환
- canvas 설명·GIF·시연 녹화 구성과 영상 초안 제작, 실제 원격 시연은 안선효와 함께 진행
- 도구 설명·canvas 제작법·검사 결과·영상 링크 정보를 안선효에게 전달

예상 비중 내역: canvas 7 + 실행 보조 5 + 검증·GIF 13 + 시연 준비 5.

## 2. 독립 개발을 위한 경계

**다른 담당자의 Python 모듈을 import하지 않는 구조로 구성함. 공통 구현 담당자를 기다리는 단계도 두지 않음.** 공유하는 것은 TCP 메시지·CLI·파일·로그의 규격뿐임.

| 파트 | 개발 중 필요한 입력 | 상대 구현 없이 진행하는 방법 | 통합 시 연결 |
| --- | --- | --- | --- |
| Assigner | 교수님 G11 canvas | 안선효 소유 대역 Worker로 기동·Barrier·저장 검사 | 실제 Worker와 TCP 연결 |
| Worker | 교수님 키트·G11 canvas | 순수 규칙 검사 + 황대겸 소유 대역 Assigner | 실제 Assigner와 TCP 연결 |
| 도구 | 교수님 샘플 round·RoundHash·GIF, 직접 만든 검사 데이터 | 정상/오류 fixture를 코드로 만들고 임시 폴더에 저장; 기동은 대역 명령 사용 | 실제 결과 파일·프로세스 명령 입력 |

송수신·로그 같은 작은 기능은 Assigner/Worker 각 패키지 안에서 구현함. 소규모 중복보다 공통 모듈 대기와 변경 전파를 줄이는 선택임. `src/common/`은 사용하지 않음. 검증 도구는 계산 코드를 가져오지 않고 산출물을 읽으며, 실행 보조는 Worker 내부 객체를 참조하지 않음.

실제 실행에서는 Worker 결과와 Assigner Barrier가 서로 의존하는 것이 과제의 필수 동작임. 개발 독립성은 대역·고정 규약으로 확보하며, 대역 통과만으로 전체 기능 완료로 판정하지 않음.

## 3. 개발 기준 규약

아래는 독립 개발을 위해 이번 계획에서 정한 **설계 선택**임. 공식 명세의 메시지·Round·크기 조건은 그대로 유지함. 변경 필요 시 안선효가 영향 범위를 취합하고 규약·양쪽 검사 코드를 함께 갱신함.

### 환경·패키지

- Python 3.12 이상, Assigner/Worker/검사 핵심은 표준 라이브러리 사용
- GIF에만 Pillow 사용. canvas는 직접 정의한 글꼴 사용을 기본안으로 두어 pyfiglet 의존 제거
- Worker는 단일 스레드, N개 독립 프로세스로 실행
- 실행 작업 디렉터리는 `개발저장소/HW4`
- `src`는 별도 초기화 로직 없는 namespace package로 사용, 각 담당이 자기 하위 패키지·`__main__.py` 소유
- `tools`와 `tests`의 내부 구현은 황왕석 및 해당 테스트 담당이 자기 경로에서 관리
- 교수님 원본 경로와 산출물 경로는 인자로 전달. 절대 경로와 공백 포함 경로 지원

### 패키지 구성

아래는 구현할 파일 구성임. 현재 코드가 생성되었다는 의미는 아님. 파일 분리는 담당 내부 설계이며 같은 담당 범위 안에서 합칠 수 있음. 실행 진입점과 파트 간 규약은 유지함.

```text
HW4/
├─ README.md
├─ src/                            namespace package, 공통 초기화 없음
│  ├─ assigner/                    안선효
│  │  ├─ __init__.py               부작용 없는 패키지 선언
│  │  ├─ __main__.py               CLI·기동·접속·종료
│  │  ├─ server.py                 HELLO·ASSIGN·Handler 생성
│  │  ├─ handler.py                Worker별 ROUND/RESULT 송수신
│  │  ├─ barrier.py                공유 상태·Mutex·CV·Halo 중계
│  │  ├─ storage.py                canvas 읽기·snapshot·round/frame·해시
│  │  ├─ metrics.py                Round·Barrier·전송량 측정 및 분석
│  │  ├─ transport.py              Assigner 전용 TCP 줄 버퍼·검사
│  │  └─ log.py                    Assigner 로그 직렬화
│  └─ worker/                      황대겸
│     ├─ __init__.py               부작용 없는 패키지 선언
│     ├─ __main__.py               CLI·접속·수신/계산/송신·종료
│     ├─ board.py                  작업판·이중 버퍼·전역 좌표
│     ├─ rules.py                  규칙 3종·덧칠·brian/cyclic 변환
│     ├─ reference.py              통신 없는 전체 판 기준 계산 CLI
│     ├─ transport.py              Worker 전용 TCP 줄 버퍼·검사
│     └─ log.py                    Worker 로그·계산시간 요약
├─ tools/                          황왕석
│  ├─ __init__.py                   부작용 없는 패키지 선언
│  ├─ launch_workers.py            전달된 명령으로 N개 프로세스 실행
│  ├─ make_canvas.py               글꼴·문구·좌표·seed 기반 생성
│  ├─ check_canvas.py              입력 형식·점·획 검사
│  ├─ verify_run.py                실행 파일·메타정보·로그 검사
│  ├─ make_hash_result.py          N=1/a/b 조건·31개 해시 비교
│  ├─ make_gif.py                  frame 검사·GIF 생성·확인
│  └─ formats.py                   도구 내부 파일·로그 형식 처리
└─ tests/
   ├─ assigner/                    안선효: 대역 Worker·Barrier·저장 검사
   ├─ worker/                      황대겸: 대역 Assigner·규칙·전환 검사
   ├─ tools/                       황왕석: 임시 fixture·대역 프로세스
   └─ integration/                 안선효: 실제 프로그램 연결·해시 검사
```

`src.assigner`와 `src.worker`는 자기 패키지 내부와 표준 라이브러리만 참조함. `tools`는 자기 내부 코드·표준 라이브러리·GIF용 Pillow만 참조함. tools의 formats는 도구 담당 내부 모듈이며 Assigner/Worker가 의존하는 공통 모듈이 아님.

`reference.py`는 Worker 규칙만 재사용하는 황대겸 소유 개발 도구임. 통신 없는 결과를 제출용 N=1 실행 결과로 대체하지 않음. 통합 테스트와 실행 보조는 subprocess와 TCP·파일로만 실제 프로그램에 접근함.

그림·로그·JSON·GIF·문서는 위 코드 트리에 저장하지 않고 명령 인자로 지정한 로컬 경로에 출력함. 테스트 fixture도 임시 폴더에서 생성함. Git 추적용 빈 파일이나 미구현 코드 파일은 만들지 않음.

### 실행 인터페이스

아래 명령은 **구현 목표이며 현재 실행 가능한 코드가 아님**. IP·PORT·N·RUN은 실행 시 치환할 값임. 포트 숫자는 아직 고정하지 않음.

```text
python -m src.assigner --host IP --port PORT --team 2 --canvas-dir PATH --out-dir PATH --run-id RUN
python -m src.assigner --host IP --port PORT --team 2 --canvas-dir PATH --out-dir PATH --run-id RUN --n 1
python -m src.worker --host IP --port PORT --log-dir PATH --run-id RUN
python -m tools.launch_workers --count N -- python -m src.worker --host IP --port PORT --log-dir PATH --run-id RUN
python -m tools.make_canvas --team 2 --seed 200 --out-dir PATH
python -m tools.check_canvas --canvas-dir PATH
python -m tools.verify_run --run-dir PATH
python -m tools.make_hash_result --team 2 --baseline PATH --run-a PATH --run-b PATH --output PATH
python -m tools.make_gif --run-dir PATH --output PATH
```

Assigner의 `--n` 생략 시 4~8 무작위. `--n`은 개발·기준값용이며 정식 분산 실행에서는 생략함. 기동 도구의 N은 Assigner가 출력한 값을 사람이 전달함. 기동 도구가 Assigner의 N을 재선정하거나 별도 제어 메시지를 추가하지 않음.

실행 보조는 `--` 뒤 인자 목록을 shell 없이 N회 실행하고 자기 자식 프로세스만 관리함. 중도 실패 시 나머지 자기 자식을 정리하고 실패 반환. stdout/stderr는 프로세스별 임시 진단 파일로 분리하되 공식 Worker 로그는 ASSIGN의 k로 결정함.

### TCP 메시지

| 메시지 | 후속 줄 수 | 검사 |
| --- | ---: | --- |
| HELLO | 0 | 접속 후 한 번 |
| ASSIGN k N y0 y1 team | 3h+4 | canvas0 h줄, canvas1/2 각각 h+2줄 |
| ROUND r | 2 | top·bottom, r=0~2999 순서 |
| RESULT r k | 2 또는 h+2 | `(r+1)%10==0`일 때만 h줄 추가 |
| BYE | 0 | 3,000회 종료 뒤 |

ASCII·LF 사용. 명령 필드는 공백으로 분리, 그림 줄은 160바이트 그대로 보존함. `strip/trim` 금지, CR·비ASCII·잘못된 길이는 오류 처리. recv 한 번과 메시지 한 개를 동일시하지 않음. 송신은 메시지 전체를 구성해 sendall하며 상태 Lock 밖에서 수행함. 규약 버전이나 run_id를 명세의 TCP 메시지에 추가하지 않음.

### 결과 파일과 메타정보

각 실행 폴더는 아래 구조로 통일함. Assigner 출력 폴더와 로컬 Worker 로그 폴더는 별도 호스트에 있으며, 실행 종료 후 같은 run_id 폴더로 취합함.

```text
RUN/
  run_info.json           Assigner가 기록
  RoundHash.txt           roundXXXX.txt hash8, 31줄
  round0000.txt ... round3000.txt
  frames/frame0000.txt ... frame3000.txt
  logs/Assigner.txt
  logs/Worker0.txt ... Worker(N-1).txt
```

`run_info.json`의 필수 필드: `schema_version=1`, `run_id` 문자열, `team` 정수, `n` 정수, `n_mode` (`random`/`fixed`), `rounds=3000`, `width=160`, `height=80`, `timezone="KST"`, `canvas_sha256` 객체(canvas0/1/2.txt 각각 전체 SHA-256 소문자 64자리). run_id는 모든 명령에 같은 값을 전달함. 메타정보는 실행 재현·입력 혼합 방지용이며 원격 배포 사실 자체의 증명은 아님.

`verify_run`은 파일·로그·메타정보를 읽어 검사함. 서버 환경·실측 분석·원격 실행 증빙은 안선효 담당. 개발용 fixture의 `n_mode` 값으로 실제 원격 실행을 대신 주장하지 않음.

### 로그 계약

공식 외형 `[HH:MM:SS.mmm] NODE | EVENT | STATUS | message` 유지. 시간대 KST, message는 JSON 객체로 정함. 모든 기록에 `run_id`를 포함함. 추가 로그 필드는 허용하되 아래 필수 필드의 뜻·자료형은 변경하지 않음.

| 노드·EVENT | 최소 JSON 필드 |
| --- | --- |
| Assigner INIT | n, team, bands(경계 정수 배열), n_mode |
| CONNECT / ASSIGN | k, n / k, y0, y1, h, team |
| Assigner BARRIER | r_start, r_end(양 끝 포함), count, round_avg_ms, round_max_ms, wait_avg_ms, wait_max_ms, slowest_counts(k 문자열→횟수), normal_rounds, full_rounds, normal_bytes, full_bytes |
| SAVE | state_round, path(실행 폴더 상대 경로), bytes, hash8 |
| REPAINT | round, canvas(canvas1.txt/canvas2.txt), conversion(brian/cyclic) |
| Worker ROUND | k, r_start, r_end, count, compute_avg_ms, compute_max_ms |
| Assigner TERMINATE | rounds_completed, elapsed_ms, throughput_round_s, handlers_joined |
| Worker TERMINATE | k, rounds_completed, compute_avg_ms |
| 오류(STATUS=FAIL) | reason, 가능한 경우 round와 k |

ROUND/RESULT 요약을 추가하면 r_start/r_end/count로 범위를 명시함. 정상 요약 구간은 0~99, …, 2900~2999, 총 30개임. 전송량은 명령·그림·LF를 포함한 Round 메시지의 송수신 합계이며 초기 ASSIGN과 BYE는 제외함. normal_bytes/full_bytes는 해당 100회 구간 합계로 기록하고 평균은 합계/해당 회수로 계산함.

Worker 계산시간은 ROUND 명령과 Halo 수신 완료 직후부터 RESULT sendall 완료까지로 정의함. Assigner 시간은 공식 측정 위치의 단조 시계 기준, 도착 시각은 Handler가 결과 전체 수신 뒤 공유 Lock 안에서 기록함. JSON 수치 단위는 ms, 바이트는 정수임.

서버 로그는 자기 Handler들이 하나의 파일에 쓰므로 로그 직렬화만 담당하는 Lock 사용 가능. Round 공유 Mutex와 분리하며 추가 로그 스레드를 만들지 않음. 상태 Lock 안에서 로그 파일 I/O하지 않음.

## 4. 각 파트의 독립 완료 기준

| 담당 | 독립 완료 기준 | 통합에서 추가 확인할 항목 |
| --- | --- | --- |
| 안선효 | N=1/4~8 분할·Halo, 늦은 대역 Worker를 기다리는 Barrier, 중복/잘못된 RESULT·EOF 실패 종료, 저장 파일 수·LF, 추가 스레드 없음 | 실제 계산 해시·실제 원격 처리량·전체 정상 종료 |
| 황대겸 | 공식 10개 규칙 + repaint/brian/cyclic/band 통과, G11 31개 해시 일치, 대역과 모든 메시지 길이·순서·전환 검사 | 실제 Assigner와 3,000회·N별 결과 동일 |
| 황왕석 | 샘플 round 검사와 고의 손상 입력 실패, N 중복/범위·해시 누락 거부, frame 누락 거부, 대역 프로세스 N개 기동·실패 정리, G2 canvas 조건 통과 | 실제 실행 폴더 전체 검사·실제 GIF·영상 일치 |

샘플에는 frame 301개와 노드 로그·run_info가 없으므로, 도구 검사는 샘플의 검사 가능한 부분과 임시 fixture로 나누어 수행함. 합성 데이터 통과와 실제 실행 검증을 기록에서 분리함. 테스트 데이터는 코드에서 임시 디렉터리에 생성하거나 외부 키트 경로로 읽으며 Git에 txt/json/GIF fixture를 넣지 않음.

각 담당 인계 항목: 코드, 재현 명령, 실행한 검사·결과, 알려진 제한·미완료 항목, 자기 로그 정의, README 실행 설명. 검증 기록은 로컬에 보관함.

## 5. 통합 및 변경 관리

통합 실패는 메시지/상태/파일/도구 중 원인 경계부터 확인하며 상대 코드를 임의로 수정하지 않음. 각 담당이 자기 파일을 고치고 안선효가 전체 결과를 확인함. Assigner와 Worker의 대역끼리만 통과하는 상황을 막기 위해 실제 프로그램 연결 결과를 별도로 확인함.

## 6. 핵심 과제 조건

- canvas 3장 각각 80줄×160글자, 출력 가능한 ASCII·LF·12,880바이트
- 각 그림에 G2 + 높이 5줄 이상 문구 2개 이상, 그림마다 다른 문구·배치
- 점/(점+공백) 비율 4~6%, 공백·점을 제외한 글자 획 384칸 이상
- Assigner Main 1 + Handler N, 공유 Mutex 1 + Condition 2. 상태 Lock 안에서 네트워크·파일 I/O 금지
- Worker 간 직접 통신 금지, 모든 Halo는 Assigner가 중계
- 균등 띠 `[80*k//N, 80*(k+1)//N)`, Torus·이중 버퍼 적용
- Rule1 0~999, Rule2 1000~1999, Rule3 2000~2999
- Round 1000/2000 직전 Halo 포함 전체 작업판 덧칠·변환. round1000/2000은 덧칠 전 상태 저장
- 최초 상태 포함 round 31개·frame 301개, 전체 파일 SHA-256 앞 8자리 소문자 비교
- 정식 분산 두 실행은 원격 Assigner·로컬 Worker, N 무작위 4~8이며 서로 다른 N 사용
- N=1도 실제 Assigner+Worker로 실행. 세 실행 31개 해시 일치 및 같은 원격 실행의 round·로그·GIF 확인
- 최종 제출: 전체 소스·canvas·round 31개·노드 로그·hash_result·GIF·Readme·AllDefinedLogs·영상 링크

## 7. 저장소 관리

Git에는 코드와 README만 보관함. 상세 계획·자료점검·제출 체크리스트는 로컬 `G2HW4/문서/`에서 관리함. README에는 조원 개발에 필요한 패키지·역할·공통 규약을 함께 유지함.

입력은 `G2HW4/canvas/`, 결과·로그는 `G2HW4/실행결과/`, 검증 기록·시연·제출물은 각각 별도 로컬 폴더에서 관리함. 교수님 원본은 기존 위치에 보존함. 빈 코드 폴더는 로컬에서만 유지하고 코드 작성 시 Git에 추가함.
