# HW4 - ASCII Evolution 개발 기준

2026학년도 2학기 데이터통신 2조. **이 README를 HW4의 최종 개발 기준으로 사용함.** 담당 작업·설계·계산 규칙·통신·CLI·로그·검증·제출 조건을 모두 포함하며, 저장소 밖의 계획서나 대화 내용을 개발 전제에 두지 않음.

현재는 설계 확정 단계이며 Assigner·Worker·도구 소스와 G2 입력은 아직 구현·생성되지 않은 상태임. 아래 트리와 명령은 구현 계약이며 실행 완료 결과가 아님. 공식 원본은 `HW4description.pdf`, 테스트 자료는 별도 제공되는 `HW4_student_pack/`임. 공식 명세가 최우선이며 실제 충돌을 발견한 경우에만 안선효에게 확인함.

원격 배포·TCP·분할식·Barrier·계산·canvas·검증·제출 조건은 과제 필수 사항임. Python·패키지 경계·단일 스레드 Worker·JSON 로그·CLI·타임아웃·브랜치는 팀에서 확정한 설계 선택임.

- [작업 시작](#작업-시작)
- [담당별 작업과 완료 기준](#담당별-작업과-완료-기준)
- [설계 방향과 패키지](#설계-방향과-패키지)
- [필수 계산 규칙](#필수-계산-규칙)
- [입력과 실행](#입력과-실행)
- [통신과 Barrier](#통신과-barrier)
- [산출물과 로그](#산출물과-로그)
- [자료와 검증](#자료와-검증)
- [통합 실행과 제출](#통합-실행과-제출)
- [협업과 변경 관리](#협업과-변경-관리)

## 작업 시작

Codex에 이 README와 본인 이름을 전달하고 다음 순서로 작업함.

```text
나는 [본인 이름]임. HW4/README.md를 읽고 내 담당 구현과 독립 검증을 진행해.
README의 공통 계약과 기존 변경을 보존하고, 실제 검사 결과와 인계 항목을 보고해.
```

1. 저장소의 적용 가능한 AGENTS.md와 이 README를 읽고 기존 변경·현재 브랜치를 확인함.
2. 사용자 지정 이름으로 담당을 결정하고 아래 소유 경로에서 작업함. 이름이 없고 요청에서도 담당을 알 수 없을 때만 담당을 확인함.
3. 담당별 작업 브랜치를 사용하되 기존 브랜치·미커밋 변경은 보존함. 실행 작업 디렉터리는 저장소의 `HW4/`임.
4. 상대 구현을 기다리지 않고 자기 대역 프로그램과 임시 검사 데이터로 구현·검증함.
5. TCP·CLI·파일·로그 계약을 그대로 지키고, 실행한 검사와 미완료 항목을 구분해 인계함.

담당 내부의 함수명·자료구조·파일 분리·최적화·오류 수정은 직접 결정하고 중요한 이유만 기록함. 기존 승인 사항은 반복 확인하지 않음. 공통 계약 변경·담당 범위 변경·추가 의존성이나 스레드 구조 변경·비용 발생·명세 충돌은 변경 전에 안선효에게 확인함.

다른 담당 패키지를 import하거나 상대 코드를 임의로 수정하지 않음. 빈 파일·미구현 골격만 만들어 완료로 보고하지 않음. 테스트 0건·필수 skip·예시 출력·제공 샘플을 자기 구현의 PASS로 기록하지 않음. 실제 통합·원격 실행을 수행하지 않았다면 각각 미실행으로 기록함.

## 담당별 작업과 완료 기준

| 담당 | 소유 경로 | 작업 브랜치 | 인계 대상 |
| --- | --- | --- | --- |
| 안선효 | `src/assigner/`, `tests/assigner/`, `tests/integration/` | `hw4/assigner` | Assigner·통합·배포·실측·최종 제출 |
| 황대겸 | `src/worker/`, `tests/worker/` | `hw4/worker` | Worker·규칙·통신 없는 기준 계산 |
| 황왕석 | `tools/`, `tests/tools/` | `hw4/tools` | canvas·실행 보조·검사·GIF·시연 자료 |

### 안선효: Assigner·통합

1. canvas 읽기·검사 → N 결정·분할 → HELLO·ASSIGN → Handler·Barrier → 저장·로그·실측 → 정상/실패 종료 순서로 구현함.
2. 자기 대역 Worker로 N=1/4~8 분할·Halo·Barrier를 검사함. 지연·잘못된 r/k·중복 결과·EOF·무응답·부분 수신·저장 실패도 검사함.
3. 처음 상태와 마지막 상태 저장, round 31개·frame 301개, Lock 밖 I/O, Handler 전부 종료, 추가 스레드 없음까지 확인하면 독립 개발 완료임.
4. 실제 Worker 통합, G2 N=1 기준 실행, 서로 다른 무작위 N의 원격 실행 두 회, 성능 분석·Readme·AllDefinedLogs·제출 ZIP 취합을 담당함.

### 황대겸: Worker·계산

1. 순수 규칙 6개 → 띠·Halo·이중 버퍼 → reference → Worker TCP·로그·종료 순서로 구현함.
2. 공식 10개 규칙 테스트와 repaint/brian/cyclic/band 검사를 모두 통과하고 G11의 31개 해시를 맞춤.
3. 자기 대역 Assigner로 ASSIGN 길이·분할/합친 수신·Round 순서·전환·전역 y·RESULT 줄 수·BYE·EOF·타임아웃을 검사하면 독립 개발 완료임.
4. `src.worker.reference`는 자기 규칙만 재사용하는 개발 도구임. 전체 판 3,000회 계산 결과는 실제 TCP N=1 제출 기준을 대신하지 않음.

### 황왕석: 입력·실행·검사 도구

1. canvas 생성·검사 → Worker 기동 보조 → 실행·해시 검사 → GIF 제작·검사 순서로 구현함.
2. 정상 샘플과 고의 손상 fixture로 ASCII/LF·파일 수·순서·해시·N·로그·메타정보를 검사함. 오류는 실패 코드로 반환함.
3. 기동 도구는 대역 명령으로 N개 프로세스 실행·자식 실패 시 전체 정리를 검사함. Worker 내부 객체를 참조하지 않음.
4. G2 canvas 3장과 전체 SHA-256, 검사 기록, 도구·재현 명령을 인계하면 독립 개발 완료임. 실제 결과의 GIF·시연 자료는 통합 이후 별도로 확인함.

## 설계 방향과 패키지

원격 Assigner 1개와 로컬 PC 한 대의 Worker N개 프로세스를 TCP Star로 연결함. Worker 간 연결은 없으며 모든 Halo는 Assigner가 중계함. N은 정식 실행마다 4~8 중 무작위이고 비교할 두 원격 실행의 N은 서로 달라야 함.

Assigner는 통신·동기화·저장, Worker는 계산, tools는 생성·기동·산출물 검증을 담당함. 분리된 프로세스 계산과 제공 Python 키트 활용을 위해 Python을 선택함. Worker는 단일 스레드로 시작하고 HW3의 Ring·Heartbeat·장애 복구는 가져오지 않음.

파트 간 공통 런타임 패키지는 두지 않음. 작은 송수신·로그 코드는 Assigner/Worker 내부에 각각 구현하고 공통 모듈 대기를 줄임. `src/common/`은 만들지 않음. 공유하는 것은 TCP·CLI·파일·로그 계약뿐임.

### 환경·패키지

- Python 3.12 이상, Assigner/Worker/검사 핵심은 표준 라이브러리 사용
- GIF에만 Pillow 사용. canvas는 직접 정의한 글꼴 사용을 기본안으로 두어 pyfiglet 의존 제거
- Worker는 단일 스레드, N개 독립 프로세스로 실행
- 실행 작업 디렉터리는 저장소의 `HW4/`
- `src`는 별도 초기화 로직 없는 namespace package로 사용, 각 담당이 자기 하위 패키지·`__main__.py` 소유
- `tools`와 `tests`의 내부 구현은 황왕석 및 해당 테스트 담당이 자기 경로에서 관리
- 교수님 원본 경로와 산출물 경로는 인자로 전달. 절대 경로와 공백 포함 경로 지원

환경 확인은 `python --version`으로 수행함. GIF 제작 환경에서는 `python -m pip install Pillow`로 의존성을 준비함. 서버의 Assigner와 규칙·해시 검사에는 Pillow가 필요하지 않도록 GIF 코드에서만 import함.

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

## 필수 계산 규칙

### 판·띠·상태 시점

- 전체 크기는 H=80, W=160, G2 정식 실행은 team=2임. G11 샘플 검사에서는 인자로 team=11을 사용함. k는 접속 순서 0~N-1임.
- 담당 행은 `[y0,y1) = [80*k//N, 80*(k+1)//N)`, 높이는 h=y1-y0임. N=1도 같은 식을 사용함.
- S(r)은 Round r 계산 직전 상태이며 Round r은 S(r+1)을 만듦. 실행 r은 0~2999, 총 3,000회임.
- 작업판은 `top + 담당 띠 h줄 + bottom`의 h+2줄임. 상태 cur/next와 canvas1·2 조각만 가지며 전체 80행을 Worker마다 복제하지 않음.
- 작업판 i의 전역 행은 `y=(y0-1+i)%80`임. 열은 `(x±1)%160`으로 감싸고 세로 Torus는 Halo로 처리함. 작업판 h+2행 자체를 세로로 감싸지 않음.
- 모든 다음 상태는 이전 cur만 읽어 next에 쓰고 한 회 끝나면 교체함. 계산 중 제자리 갱신 금지임.

| 규칙 | Round | 다음 상태 |
| --- | --- | --- |
| Rule1 Text Life | 0~999 | 8이웃. 공백 이외는 점도 살아 있는 칸임. 생존 이웃 2/3이면 자기 문자 유지, 나머지는 공백. 공백은 살아 있는 이웃이 3개일 때 탄생하며 부모 3개의 최빈 문자, 동률이면 ASCII 최소 문자 사용 |
| Rule2 Brian | 1000~1999 | 8이웃. `@ → + → 공백`. 공백은 이웃 @가 정확히 2개이면 @, 그 외 공백 |
| Rule3 Cyclic | 2000~2999 | 4이웃(상하좌우). `RAMP=" .:-=+*#%@"`에서 현재 단계 k의 다음 `(k+1)%10` 단계가 이웃 중 하나라도 있으면 그 단계로 전진, 아니면 유지 |

### 덧칠·변환·저장

매 ROUND에서 Halo를 먼저 받은 뒤 아래 전환을 해당 Round에 한 번만 적용하고 계산함. **전환 범위는 Halo를 포함한 작업판 전체 h+2줄임.**

| 계산 직전 | 처리 순서 |
| --- | --- |
| r=1000 | canvas1 조각에서 공백·점을 제외한 문자만 cur에 덧칠 → cur의 공백 아닌 칸 전부 @로 변환 → Rule2 계산 |
| r=2000 | canvas2 조각을 같은 조건으로 덧칠 → RAMP의 공백 아닌 문자는 유지, 나머지(공백 포함)는 `RAMP[(7*x+3*y+(x*y)%11+team)%10]`으로 변환 → Rule3 계산 |

최초 S(0)을 round0000·frame0000으로 저장함. `(r+1)%10==0`일 때 RESULT에 전체 띠를 붙이고 frame을 저장함. `(r+1)%100==0`이면 같은 snapshot을 round 파일로도 저장함. round1000·round2000 및 같은 번호 frame은 **덧칠 전** S(1000)·S(2000)임. 마지막은 S(3000)임.

### 규칙 함수와 기준 계산

Worker 내부의 `rules.py`에서 `rule1_cell(w,i,x)`, `rule2_cell(w,i,x)`, `rule3_cell(w,i,x)`, `repaint(w,c)`, `to_brian(w)`, `to_cyclic(w,ytop,team)`을 구현함. 칸 함수는 다음 문자만 반환하고, 전환 함수 3개는 작업판 전체를 제자리 변환함. `ytop=(y0-1)%80`, `y=(ytop+i)%80`임.

공식 10×10 키트에도 연결되도록 칸 함수의 열 너비는 입력에서 구함. 칸 함수는 `i-1/i+1` 행을 그대로 읽고, 전체 판 검사에서는 마지막/첫 행을 Halo로 붙임. 프로그램 실행의 80×160 조건과 작은 규칙 검사를 혼동하지 않음.

reference의 CLI는 `python -m src.worker.reference --team 11 --canvas-dir "G11_DIR" --out-dir "REFERENCE_DIR"`로 정함. 3,000회와 동일 저장 시점을 사용해 round 31개와 `ReferenceHash.txt`를 출력함. 출력은 없거나 빈 폴더를 사용함. 제출 실행용 run_info·공식 노드 로그를 만들지 않고, verify_run과 make_hash_result의 TCP 실행 입력으로 사용하지 않음.

## 입력과 실행

### canvas 제작

세 파일 모두 다음 필수 조건을 만족해야 함.

1. 80줄×160문자, 출력 가능한 ASCII 32~126만 사용함. 탭·한글·CR·BOM 금지임.
2. 각 줄과 마지막 줄 뒤에도 LF를 써서 파일당 정확히 12,880바이트임. 줄 앞뒤 공백은 그림이므로 제거하지 않음.
3. G2와 조 이름 외 문구 2개 이상을 높이 5줄 이상의 큰 ASCII 글자로 넣음. 세 장의 문구·배치를 서로 다르게 함.
4. 글자 배치 후 남은 빈칸마다 5% 확률로 점을 뿌림. `점/(점+공백)`은 4~6%, 공백·점 이외 획은 384칸 이상임.
5. 문구·글자 높이·잘림·배치 차이는 사람이 확인함. 수치 검사 PASS만으로 전체 canvas 조건을 통과했다고 하지 않음.

제작 기본안은 직접 만든 높이 7줄 글꼴이며 문구는 아래를 사용함. 황왕석이 조건 충족을 위해 획·좌표를 조정할 수 있고 실제 배치를 인계 기록에 남김. 글꼴·배경 난수는 표준 라이브러리만으로 구현함.

| 파일 | 큰 글자 문구 | 시작 좌표 제안(x,y) |
| --- | --- | --- |
| canvas0.txt | G2 / CONNECT / BUILD TOGETHER | (8,6) / (28,25) / (8,51) |
| canvas1.txt | G2 / SHARE IDEAS / GROW AS ONE | (112,8) / (12,32) / (40,60) |
| canvas2.txt | G2 / IN SYNC / BEYOND LIMITS | (65,5) / (10,22) / (30,46) |

동일 seed로 동일 파일을 재생성해야 함. `make_canvas --seed 200`을 기본으로 삼고 실제 글꼴·좌표·seed·세 입력 SHA-256을 함께 인계함. 샘플 G11에 조 번호만 바꾼 그림은 사용하지 않음.

### 실행 인터페이스

아래 명령은 **구현 목표이며 현재 실행 가능한 코드가 아님**. IP·PORT·N·RUN 및 경로는 실행 시 치환할 값임. 공통 사용 포트는 9000으로 정하되 CLI에는 `--port`를 명시함. 실제 서버 포트 사용 가능 여부는 배포 전 확인함. 공백 포함 경로는 따옴표로 감쌈.

```text
python -m src.assigner --host IP --port PORT --team 2 --canvas-dir "CANVAS_DIR" --out-dir "RUN_DIR" --run-id RUN
python -m src.assigner --host IP --port PORT --team 2 --canvas-dir "CANVAS_DIR" --out-dir "RUN_DIR" --run-id RUN --n 1
python -m src.worker --host IP --port PORT --log-dir "LOG_DIR" --run-id RUN
python -m src.worker.reference --team 11 --canvas-dir "G11_DIR" --out-dir "REFERENCE_DIR"
python -m tools.launch_workers --count N -- python -m src.worker --host IP --port PORT --log-dir "LOG_DIR" --run-id RUN
python -m tools.make_canvas --team 2 --seed 200 --out-dir "CANVAS_DIR"
python -m tools.check_canvas --canvas-dir "CANVAS_DIR"
python -m tools.verify_run --run-dir "RUN_DIR"
python -m tools.make_hash_result --team 2 --baseline "N1_DIR" --run-a "RUN_A_DIR" --run-b "RUN_B_DIR" --output "HASH_FILE"
python -m tools.make_gif --run-dir "RUN_DIR" --output "GIF_FILE"
```

Assigner의 `--n` 생략 시 4~8 무작위. `--n`은 개발·기준값용이며 정식 분산 실행에서는 생략함. 기동 도구의 N은 Assigner가 출력한 값을 사람이 전달함. 기동 도구가 Assigner의 N을 재선정하거나 별도 제어 메시지를 추가하지 않음.

`--n` 고정값은 1 또는 4~8만 허용하고 메타정보에 fixed로 기록함. team은 양의 정수, 실제 실행 port는 1~65535, launcher count는 1 또는 4~8만 허용함. 검사 대역이 빈 포트를 확보할 때만 포트 0을 사용할 수 있음. `--team`·실행 경로·run_id는 예시 기본값을 코드에 박지 않고 인자에서 읽음.

실행 보조는 `--` 뒤 인자 목록을 shell 없이 N회 실행하고 자기 자식 프로세스만 관리함. 중도 실패 시 나머지 자기 자식을 정리하고 실패 반환. stdout/stderr는 프로세스별 임시 진단 파일로 분리하되 공식 Worker 로그는 ASSIGN의 k로 결정함.

Assigner의 `--host`는 수신 바인드 주소(원격 기본 `0.0.0.0`), Worker의 `--host`는 실제 접속 대상 주소임. 로컬 검사는 `127.0.0.1`을 사용함. 실행마다 안선효가 N·접속 주소·포트·run_id·원격 RUN_DIR·로컬 LOG_DIR·입력 3장 해시를 전달하고 Worker 담당이 같은 값으로 기동함. bind 주소 `0.0.0.0`을 Worker 접속 주소로 전달하지 않음.

Assigner는 listen 준비가 끝나면 N·bands·host·port·run_id를 포함한 INIT SUCCESS 로그 한 줄을 stdout과 자기 로그 파일에 출력하고 flush함. 사람이 이 N을 확인한 뒤 launcher를 기동할 수 있어야 함. 접속 전 오류는 stderr에 원인을 출력함.

run_id는 영문·숫자로 시작하는 영문·숫자·밑줄·하이픈 1~64자로 정함. 예시는 `g2-n1-001`, `g2-run1-001`, `g2-run2-001`이며 재실행 시 새 번호를 사용함. 이 문자열은 TCP 메시지에 추가하지 않음.

### 타임아웃과 종료 코드

무한 대기와 담당별 실패 판단 차이를 줄이기 위한 **설계 선택**임. 다음 선택 인자는 기본값을 생략해도 같은 동작을 해야 함. 양의 유한한 초 단위 수만 허용함.

| 적용 대상 | 선택 인자·기본값 | 범위 |
| --- | --- | --- |
| Worker | `--connect-timeout 10` | 최초 TCP connect 전체 |
| Assigner·Worker | `--startup-timeout 300` | Assigner는 listen 준비부터 N개 HELLO 확인·ASSIGN 전송 완료까지, Worker는 HELLO 송신 시작부터 ASSIGN 전체 수신·최초 ROUND 전체 수신까지 |
| Assigner·Worker | `--io-timeout 120` | 준비 완료 후 논리 메시지 하나의 송신 또는 수신 전체. Worker는 RESULT 송신 뒤 다음 ROUND 또는 BYE를 받는 대기도 포함 |

단조 시계로 전체 제한시간을 계산하고, 부분 수신마다 남은 시간을 적용함. 바이트가 조금씩 도착해도 논리 메시지의 제한시간을 다시 시작하지 않음. 최초 ROUND는 Worker의 startup 제한시간을 적용하며 이후 ROUND/BYE부터 io 제한시간을 적용함. 초기 접속 대기를 120초 응답 제한으로 잘못 중단하지 않도록 구분한 선택임.

Assigner Main의 done_cv 대기도 해당 Round의 `t_start[r] + io_timeout`을 기한으로 사용함. 기한 도달 시 arrived·failed를 Lock 안에서 다시 확인하고 미완료이면 전체 실패 처리함. CV 기한 대기는 추가 감시 스레드 없이 구현함. Handler의 다음 Round go_cv 대기도 failed를 확인하며 같은 실패 통지를 받음. 타임아웃·EOF·프로토콜 오류 발생 후 자동 재접속·재시작·부분 재개는 하지 않음.

실제 실행에서는 양쪽 startup/io 값을 동일하게 지정하고 기본값을 변경했다면 명령과 값을 검증 기록에 남김. 짧은 타임아웃 오류 검사는 개발용 인자 변경으로 수행 가능함. 위 수치는 성능 실측값이 아니므로 원격 실행으로 적절성을 확인함.

종료 코드는 정상 완료·검사 PASS는 0, CLI 값 오류는 2, 통신·파일·검증 실패는 1로 통일함. Ctrl+C는 130으로 구분함. 검사에서 0건 수집·필수 자료 없음은 PASS로 처리하지 않음. 파일 로그가 준비되기 전 실패는 stderr에 원인을 남기고 같은 실패 코드로 종료함.

### 출력 경로와 재실행

아래는 실행 결과 혼합과 담당별 경로 해석 차이를 막기 위한 **설계 선택**임. 모든 상대 경로는 명령 실행 디렉터리 기준으로 해석함.

| 인자 | 의미와 최종 경로 |
| --- | --- |
| Assigner `--out-dir RUN_DIR` | 한 실행의 최종 폴더 자체. `RUN_DIR/run_info.json`, `RUN_DIR/roundXXXX.txt`, `RUN_DIR/frames/`, `RUN_DIR/logs/Assigner.txt` 생성 |
| Worker `--log-dir LOG_DIR` | 공식 로그를 직접 넣을 폴더. `LOG_DIR/Worker{k}.txt` 생성 |
| `--run-id RUN` | 메타정보·로그에 기록하는 동일 실행 식별자. 경로에 자동으로 덧붙이지 않음 |
| 검사 도구 `--run-dir`, 해시 도구의 세 실행 경로 | 위 RUN_DIR 자체를 입력으로 받음 |
| canvas 생성기 `--out-dir CANVAS_DIR` | `CANVAS_DIR/canvas0.txt` 등 입력 3장을 직접 생성 |
| 도구 `--output FILE` | 결과 파일의 최종 경로 자체 |

예를 들어 원격 Assigner에 `--out-dir "/srv/hw4/run1/g2-a" --run-id g2-a`, 로컬 Worker에 `--log-dir "../../실행결과/run1/g2-a/logs" --run-id g2-a`를 지정함. 원격 결과를 로컬 `../../실행결과/run1/g2-a`로 취합하면 `logs/Assigner.txt`와 `logs/Worker{k}.txt`가 같은 폴더에 모임. N=1 로컬 실행도 Assigner의 RUN_DIR 아래 `logs`를 Worker의 LOG_DIR로 직접 지정함.

- Assigner와 canvas 생성기의 출력 폴더는 없거나 비어 있어야 함. 비어 있지 않으면 기존 파일을 바꾸기 전에 실패 종료함. Assigner는 `run_info.json`을 배타적 생성으로 선점한 뒤 접속을 받음.
- Worker 여러 개가 같은 LOG_DIR를 사용하는 것은 허용함. ASSIGN으로 k를 받은 뒤 `Worker{k}.txt`를 배타적으로 생성하고, 기존 파일이 있으면 덮어쓰지 않고 실패 종료함. ASSIGN 전 로그는 메모리에 보관했다가 해당 파일 앞부분에 기록함.
- `--output` 대상도 기존 파일이 있으면 실패함. 실패·중단 결과는 보존하며, 재실행에는 새 RUN_DIR·LOG_DIR·run_id를 사용함. 이어하기·자동 삭제·덮어쓰기 옵션은 두지 않음.
- 원격 결과 취합 시 기존 파일을 덮어쓰지 않음. 서로 다른 이름의 로그만 병합하고, run_info와 각 로그의 run_id가 같은지 검사함. 충돌하면 취합을 중단하고 원본을 보존함.

## 통신과 Barrier

### TCP 메시지

| 메시지 | 후속 줄 수 | 검사 |
| --- | ---: | --- |
| HELLO | 0 | 접속 후 한 번 |
| ASSIGN k N y0 y1 team | 3h+4 | canvas0 h줄, canvas1/2 각각 h+2줄 |
| ROUND r | 2 | top·bottom, r=0~2999 순서 |
| RESULT r k | 2 또는 h+2 | `(r+1)%10==0`일 때만 h줄 추가 |
| BYE | 0 | 3,000회 종료 뒤 |

ASCII·LF 사용. 명령 필드는 공백으로 분리, 그림 줄은 160바이트 그대로 보존함. `strip/trim` 금지, CR·비ASCII·잘못된 길이는 오류 처리. recv 한 번과 메시지 한 개를 동일시하지 않음. 송신은 메시지 전체를 구성해 sendall하며 상태 Lock 밖에서 수행함. 규약 버전이나 run_id를 명세의 TCP 메시지에 추가하지 않음.

접속 단계는 Main이 N개 HELLO 확인 → 각 Worker에 ASSIGN 전체 전송 → Handler N개 생성·시작 순서임. Worker는 자신이 k·N·team을 정하지 않고 ASSIGN 값을 검사해 사용함. h=y1-y0, k/N 범위와 분할식도 검사함.

ASSIGN의 canvas0은 `[y0,y1)` h줄, canvas1·2는 `[y0-1,y1+1)`을 mod 80으로 읽은 h+2줄씩임. Worker는 canvas0 띠를 cur 가운데에 넣고 매 ROUND top/bottom을 새로 채움. RESULT의 첫·끝 줄은 계산 후 담당 띠의 첫·끝 줄임. 전체 띠를 보낸 회에는 중복 첫·끝 줄도 생략하지 않고, Assigner가 전체 띠 양 끝과 일치하는지 확인함.

초기 halo는 canvas0에서 구함. 이후 `top[k]=edge[(k-1+N)%N].last`, `bottom[k]=edge[(k+1)%N].first`임. N=1이면 자기 마지막/첫 줄을 Halo로 사용함. RESULT r의 모든 N개가 모이기 전에 ROUND r+1을 보내지 않음. BYE는 RESULT 2999 전부 수신 뒤에만 전송함.

### Barrier 상태 전이

공식 구조는 Main 1 + Handler N, 공유 Mutex `m` 1개와 같은 `m`을 사용하는 `done_cv`·`go_cv` 2개임. 아래는 이를 구현하기 위한 상태·순서 계약이며 실행 코드가 아닌 의사코드임.

Main이 N개 HELLO를 확인하고 모든 ASSIGN을 전송한 뒤 Handler를 생성함. Handler 시작 전에 canvas0으로 frame0000·round0000과 초기 halo를 준비하고, `round=0`, `arrived=0`, `failed=False`, `seen[k]=-1`로 초기화함. `round`, `arrived`, `failed`, 최초 오류 원인, `seen`, `edge`, `halo`, `frame`, 도착 시각은 모두 `m`으로 보호함.

```text
Handler k: r = 0..2999
  m 안: failed이면 종료, round == r 확인, halo[k] 복사
  m 밖: ROUND r + halo 전송, RESULT 전체 수신, r/k/길이 검사
  m 안:
    failed이면 종료
    round != r 또는 seen[k] == r이면 오류
    edge[k] 갱신, 전체 띠가 있으면 frame의 자기 구간 갱신
    도착 시각 기록, seen[k] = r, arrived += 1
    arrived == N이면 done_cv.notify()
    while not failed and round == r: go_cv.wait()
    failed이면 종료
  위 반복 3000회 완료 뒤 m 밖에서 BYE 전송, 소켓 닫기

Main: t_start[0] 기록 직후 Handler N개 시작
  r = 0..2999 반복
    m 안:
      while not failed and arrived < N:
        remaining = t_start[r] + io_timeout - now()
        remaining <= 0이면 timeout 오류
        done_cv.wait(remaining)
      failed이면 반복 중단
      t_end[r] 기록, 도착 시각으로 Barrier 대기 계산
      edge로 다음 halo 준비
      (r+1)%10 == 0이면 frame의 독립 snapshot 복사
      arrived = 0, round = r+1
      r < 2999이면 t_start[r+1] 기록
      go_cv.notify_all()
    m 밖: 해당 Round의 snapshot이 있을 때만 저장·해시, 100회마다 요약 로그
  최종 저장 완료 및 모든 Handler join 뒤 성공 여부 확인·종료 요약
```

파일 저장과 다음 Round 계산은 겹칠 수 있으므로 snapshot은 변경 가능한 frame과 분리함. 마지막에도 `round=3000`으로 갱신하고 go_cv를 깨워 Handler가 BYE로 진행하게 함. Main은 파일 저장 성공과 모든 Handler의 정상 종료까지 확인한 뒤에만 SUCCESS를 기록함.

수신·검사·전송·저장 중 오류가 나면 m을 해제한 예외 처리 구간에서 공통 실패 처리를 호출함. **m 안에서는** `failed=True`와 최초 원인을 기록하고 두 CV 모두 `notify_all()`함. **m을 놓은 뒤** FAIL 로그와 모든 연결 소켓의 shutdown/close로 recv/send 대기도 해제함. 종료된 소켓의 중복 정리는 허용하며, 각 스레드의 예외 경로에서도 이 절차를 수행함. Handler는 다른 Handler를 join하지 않고, Main만 자기 Handler 전부를 join한 뒤 실패 상태와 0이 아닌 종료 코드로 끝냄. failed 이후 도착 결과는 집계하지 않음.

## 산출물과 로그

### 결과 파일과 메타정보

각 실행 폴더는 아래 구조로 통일함. 아래 RUN_DIR는 `--out-dir`로 지정한 최종 폴더임. 원격 Assigner 결과와 로컬 Worker 로그는 위 출력 경로 계약에 따라 같은 실행 폴더로 취합함.

```text
RUN_DIR/
  run_info.json           Assigner가 기록
  RoundHash.txt           roundXXXX.txt hash8, 31줄
  round0000.txt ... round3000.txt
  frames/frame0000.txt ... frame3000.txt
  logs/Assigner.txt
  logs/Worker0.txt ... Worker(N-1).txt
```

`run_info.json`의 필수 필드: `schema_version=1`, `run_id` 문자열, `team` 정수, `n` 정수, `n_mode` (`random`/`fixed`), `rounds=3000`, `width=160`, `height=80`, `timezone="KST"`, `canvas_sha256` 객체(canvas0/1/2.txt 각각 전체 SHA-256 소문자 64자리), `timeouts` 객체(startup_s·io_s: 양의 유한한 초 단위 수). run_id는 모든 명령에 같은 값을 전달함. 메타정보는 실행 재현·입력 혼합 방지용이며 원격 배포 사실 자체의 증명은 아님.

`verify_run`은 파일·로그·메타정보를 읽어 검사함. 서버 환경·실측 분석·원격 실행 증빙은 안선효 담당. 개발용 fixture의 `n_mode` 값으로 실제 원격 실행을 대신 주장하지 않음.

### 로그 계약

공식 외형 `[HH:MM:SS.mmm] NODE | EVENT | STATUS | message` 유지. 시간대 KST, message는 JSON 객체로 정함. 모든 기록에 `run_id`를 포함함. 추가 로그 필드는 허용하되 아래 필수 필드의 뜻·자료형은 변경하지 않음.

NODE는 ASSIGNER 또는 WORKER0~WORKER(N-1), STATUS는 SUCCESS/FAIL/INFO/WARN임. 로그 파일은 UTF-8·LF, 시각은 시스템 기본 시간대와 무관하게 KST로 기록함. k/N/team/행/횟수/바이트는 JSON 정수, 시간·처리량은 유한한 JSON 수, slowest_counts는 k 문자열을 키로 하는 정수 객체임. 숫자를 문자열로 기록하지 않음. INIT·ASSIGN·SAVE·정상 TERMINATE는 SUCCESS, 진행 요약·REPAINT는 INFO, 실패는 FAIL로 정함.

| 노드·EVENT | 최소 JSON 필드 |
| --- | --- |
| Assigner INIT | n, team, bands(경계 정수 배열), n_mode, host, port, startup_timeout_s, io_timeout_s |
| Worker INIT | connect_timeout_s, startup_timeout_s, io_timeout_s |
| Assigner CONNECT | k, n |
| ASSIGN(양쪽) | k, n, y0, y1, h, team |
| Assigner RESULT(Worker별 100회 요약) | k, r_start, r_end, count |
| Assigner BARRIER | r_start, r_end(양 끝 포함), count, round_avg_ms, round_max_ms, wait_avg_ms, wait_max_ms, slowest_counts(k 문자열→횟수), normal_rounds, full_rounds, normal_bytes, full_bytes |
| SAVE | state_round, path(실행 폴더 상대 경로), bytes, hash8 |
| REPAINT | round, canvas(canvas1.txt/canvas2.txt), conversion(brian/cyclic) |
| Worker ROUND | k, r_start, r_end, count, compute_avg_ms, compute_max_ms |
| Assigner TERMINATE | rounds_completed, elapsed_ms, throughput_round_s, handlers_joined, round_avg_ms, round_max_ms, wait_avg_ms, wait_max_ms, slowest_counts, slowest_workers, normal_rounds, full_rounds, normal_bytes, full_bytes, normal_avg_bytes, full_avg_bytes |
| Worker TERMINATE | k, rounds_completed, compute_avg_ms |
| 오류(STATUS=FAIL) | reason, 가능한 경우 round와 k |

타임아웃 FAIL에는 reason="timeout", phase(connect/startup/send/recv/barrier), timeout_s와 가능한 round·k를 기록함. 최초 오류 원인을 보존하고 뒤따른 소켓 종료 오류로 덮어쓰지 않음.

Worker ROUND·Assigner RESULT는 각 Worker별 100회마다 요약하고 r_start/r_end/count로 범위를 명시함. Assigner BARRIER는 Main에서 100회마다 기록함. 정상 요약 구간은 0~99, …, 2900~2999, 총 30개임. 전송량은 명령·그림·LF를 포함한 Round 메시지의 송수신 합계이며 초기 ASSIGN과 BYE는 제외함. normal_bytes/full_bytes는 해당 100회 구간 합계로 기록하고 평균은 합계/해당 회수로 계산함.

Assigner의 정상 TERMINATE에는 **3,000회 전체의 지표를 최종 요약**함. round/wait 평균은 전체 Round 값의 합계/3000, 최대는 전체 최댓값임. slowest_counts는 k별 최지연 횟수 객체이고, slowest_workers는 그 횟수가 최대인 k를 모두 담은 오름차순 정수 배열임. 한 Round의 도착 시각이 동률이면 k가 가장 작은 Worker를 집계하는 설계로 정해 재현성을 확보함. normal_rounds=2700, full_rounds=300이며 normal_bytes/full_bytes는 각 유형의 전체 전송량, normal_avg_bytes/full_avg_bytes는 각 합계를 해당 Round 수로 나눈 값임. handlers_joined는 실제 join 완료 수로 정상 종료 시 N임.

실패 종료는 STATUS=FAIL로 구분하고 reason·rounds_completed·handlers_joined 및 확보한 지표만 기록함. 완료하지 않은 3,000회를 정상 요약으로 채우지 않음. Worker 계산시간은 각 Worker 로그에서 수집해 최종 Readme의 띠 높이별 실측표에 함께 정리하며, 서버가 측정한 값으로 대신 기록하지 않음.

시간 측정은 `time.perf_counter()` 같은 단조 시계로 수행함. Main은 Handler 시작 직전에 t_start[0], 이후 go_cv 통지 직전에 t_start[r+1], 각 Round에서 전체 결과 도착 대기를 통과한 직후·halo 준비 전에 t_end[r]을 기록함. Handler는 RESULT 전체 수신 후 공유 Lock 안에서 arr_t[k]를 기록함. Round 시간은 `(t_end[r]-t_start[r])*1000` ms, Barrier 대기는 `(max(arr_t)-min(arr_t))*1000` ms임. elapsed_ms는 `(t_end[2999]-t_start[0])*1000`, throughput_round_s는 `3000/(elapsed_ms/1000)`임. 마지막 파일 저장·join 시간을 이 총시간에 더하지 않음.

Worker 계산시간은 ROUND 명령과 Halo 수신 완료 직후부터 RESULT sendall 완료까지로 정의함. 따라서 전환·계산·송신을 포함하며 순수 칸 계산시간과 구분함. JSON 시간 단위는 ms, 바이트는 정수임.

서버 로그는 자기 Handler들이 하나의 파일에 쓰므로 로그 직렬화만 담당하는 Lock 사용 가능. Round 공유 Mutex와 분리하며 추가 로그 스레드를 만들지 않음. 상태 Lock 안에서 로그 파일 I/O하지 않음.

필수 EVENT는 INIT, CONNECT, ASSIGN, ROUND, RESULT, BARRIER, SAVE, REPAINT, TERMINATE임. Worker INIT/접속 로그는 k를 받은 뒤 WORKERk 이름으로 기존 순서를 보존해 파일 앞부분에 기록함. Worker는 r=1000/2000의 실제 전환을 REPAINT로 기록하고, Assigner는 해당 전환 Round의 진행을 기록함. SAVE는 저장한 round/frame의 상대 경로와 실제 바이트·해시를 기록함. 날짜가 바뀌어도 측정은 단조 시계로 수행함.

### hash_result 형식

RoundHash.txt는 `roundXXXX.txt hash8` 형식 31줄이며 `hash8=sha256(파일 전체 바이트).hexdigest()[:8]`임. LF를 포함해 해시를 계산하고 소문자 16진수 8자리만 사용함.

make_hash_result는 세 실행의 team·입력 전체 SHA-256·정상 종료·형식·기록 해시를 확인한 뒤 다음 순서의 파일을 출력함. a,b는 실제 run-a/run-b의 서로 다른 4~8 정수이며 baseline의 N은 1이어야 함. 분산 두 실행은 n_mode=random이어야 함. 단순히 세 파일이 같다는 이유로 유효하지 않은 실행을 승인하지 않음.

| 행 | 형식 |
| --- | --- |
| 조번호 | `TEAM 2` |
| 머리줄 | `ROUND N=1 N={a} N={b} RESULT` |
| 31개 데이터 | `0000 hash1 hasha hashb SAME`부터 `3000 ...`까지 100 간격·오름차순. 불일치는 DIFF |
| 최종 | `FINAL hash1 hasha hashb SAME` 또는 DIFF. 세 값은 각각 round3000 해시와 같아야 함 |
| 합계 | `TOTAL 31/31 SAME -> PASS`. 불일치는 실제 SAME 개수와 FAIL |

위 표의 `{a}`, `{b}`, hash 표기는 설명용 자리표시자임. 실제 파일은 ASCII·LF·공백 구분이며 TEAM·머리줄·31줄·FINAL·TOTAL을 빠짐없이 작성함. N/메타정보/형식 오류는 실패 종료하며 TOTAL PASS 파일을 만들지 않음. 계산 해시가 서로 다른 경우에는 DIFF·TOTAL FAIL 결과와 실패 코드를 반환함.

### GIF 계약

동일 원격 실행 run1의 frame0000~frame3000(10 간격) **301개**로 제작함. 고정폭 글꼴, 일반 프레임 80ms, 상태 번호 0/1000/2000/3000은 1000ms로 정함. 30MB 이하는 권장 목표임. 처음 그림은 canvas0, 마지막 그림은 round3000과 같아야 함.

Pillow가 같은 그림을 합치거나 최적화할 수 있으므로 저장 후 GIF를 다시 열어 실제 프레임 수·전체 디코딩·처음/마지막 상태를 검사함. 상태 번호를 프레임에 표시해 동일한 판 상태도 각 저장 시점으로 구분함. 원본 round/frame의 문자 파일에는 표시 문구를 넣지 않음. 누락·순서 오류·GIF 301프레임 미달은 실패로 처리함.

## 자료와 검증

### 자료 공유와 검사 실행

안선효가 공식 명세·강의자료·HW4_student_pack 원본과 원본 SHA-256 목록을 팀원에게 전달함. 전달 채널 자체는 개발 인터페이스에 포함하지 않으며, 수신자는 아래 자료가 실제로 열리는지와 해시 일치를 확인해 회신함. 원본과 산출물은 Git 밖에 보관하는 기존 원칙을 유지함.

- 각 담당은 자기 PC의 배포팩 루트를 환경변수 `HW4_PACK_DIR`로 지정함. 테스트는 이 값을 읽고, 개인 PC의 절대 경로를 코드에 넣지 않음.
- 필수 상대 경로는 `1_rule_test_kit/`, `2_tools/`, `3_G11_sample/`임. 자료가 필요한 검사는 환경변수·자료가 없으면 실패로 보고함. 자료 없이 통과 처리하거나 샘플 해시를 구현 결과로 기록하지 않음. 자료가 없는 검사는 미검증으로 남기고 자료가 필요 없는 구현·fixture 검사는 계속함.
- G2 canvas는 황왕석이 검사 완료한 최종 3장과 전체 SHA-256을 안선효에게 인계함. 안선효가 동일 파일을 기준·분산 실행에 배포함. 각 담당이 별도로 만든 그림을 정식 실행 입력으로 혼용하지 않음.
- canvas 교체 시 N=1·분산 두 실행을 모두 새 입력으로 다시 생성함. 이전 결과와의 혼합은 run_info의 canvas_sha256 검사에서 거부함.

아래는 표준 라이브러리 unittest를 사용하는 **구현 후의 검사 진입점 계약**임. 현재 테스트 코드의 존재·통과를 의미하지 않음. 작업 디렉터리는 HW4, 테스트 파일명은 `test_*.py`로 정하고 각 담당 디렉터리에서 발견되게 구성함.

```text
python -m unittest discover -s tests/assigner -p "test_*.py" -v
python -m unittest discover -s tests/worker -p "test_*.py" -v
python -m unittest discover -s tests/tools -p "test_*.py" -v
python -m unittest discover -s tests/integration -p "test_*.py" -v
```

각 담당의 완료 보고에는 명령·Python 버전·실행 건수·PASS/FAIL·누락/skip 이유를 포함함. 테스트가 0건이거나 필수 검사가 skip되면 담당 완료로 인정하지 않음. 통합은 대역이 아닌 실제 Assigner·Worker를 subprocess로 실행하고, 자식 Python은 `sys.executable`을 사용해 인터프리터를 일치시킴. 검사용 서버 포트는 OS가 배정한 빈 포트를 사용 가능하며 정식 실행 포트 변경과 구분함.

환경변수 설정 예시는 아래와 같음. 실제 PC의 배포팩 루트로 치환하며 G11 경로는 그 아래 `3_G11_sample/`임.

```powershell
$env:HW4_PACK_DIR = "C:\실제경로\HW4_student_pack"
```

```bash
export HW4_PACK_DIR="/actual/path/HW4_student_pack"
```

### 담당별 검사

1. **Worker 규칙:** tests.txt의 Rule1 4개·Rule2 3개·Rule3 3개 총 10개를 통과함. 이 결과만으로 전환·띠 검증까지 완료 처리하지 않음.
2. **전환·띠:** repaint_S1000 + repaint_canvas1 → repaint_step1_painted → repaint_step2_brian → repaint_step3_R1000을 바이트 비교함. cyclic_convert_input은 ytop=25, team=11의 정답과 비교함. N=3의 W0/W1/W2 작업판 결과를 각각 비교하고 연결 결과가 rule1_output_R1과 같은지 확인함.
3. **G11 전체:** reference를 team=11과 G11 canvas로 실행해 RoundHash_N1.txt의 31개 해시와 비교함. round0000은 74aebc0f, round1000은 cc1b26db, round2000은 e5971646, round3000은 414b775c임. 이는 제공 샘플 기준값이며 G2 정답값이 아님.
4. **Assigner 대역:** 분할·Torus·지연·순서·바이트 분할/합침·오류·무응답·첫/마지막 저장·실패 시 CV/소켓 해제·모든 Handler 종료를 검사함.
5. **도구:** 정상 fixture와 N 중복/범위 오류·해시 누락/중복/순서 오류·CRLF·비ASCII·frame 누락·로그 불일치·입력 혼합 fixture를 검사함. 제공 도구가 종료 코드 0으로 FAIL을 출력하는 경우가 있으므로 자기 검사에서 출력과 실제 결과도 판단함.
6. **실제 통합:** Assigner/Worker를 실제 subprocess와 TCP로 연결해 N=1과 N=4~8의 31개 해시를 비교함. 특히 N=6/7의 다른 띠 높이와 r=999/1000/1999/2000 경계를 확인함.

제공 규칙 키트의 myrules.py는 미구현 틀임. 원본은 수정하지 않고 자기 테스트의 임시 복제본/어댑터에서 Worker 규칙과 연결함. G11에는 round 31개는 있지만 frame 301개·공식 노드 로그·run_info는 없으므로, 도구 검사는 샘플로 가능한 부분과 임시 fixture를 구분함.

verify_run의 정상 기준은 정확한 round 31개·frame 301개, ASCII/LF·크기, RoundHash 31개와 재계산 해시, round와 같은 번호 frame의 바이트 일치, 메타정보의 team/N/run_id/입력 해시/타임아웃과 INIT·ASSIGN의 분할 경계 일치, Worker k=0~N-1 로그 전부와 각 3,000회·정상 종료임. frame0000·round0000의 전체 SHA-256은 메타정보의 canvas0 해시와도 비교함. canvas1·2 원본 해시는 안선효가 실제 배포 파일과 대조하고, make_hash_result는 세 실행에 기록된 입력 해시가 같은지 확인함. 추가·누락·중복 snapshot, FAIL 로그가 섞인 실행, 일치하지 않는 run_id는 거부함. 원격 호스트 사용 사실은 이 파일 검사만으로 증명되지 않으므로 안선효가 배포 정보·로그·영상으로 별도 확인함.

## 통합 실행과 제출

### 실행 순서

1. 황대겸의 G11 규칙·reference 검증과 각 담당의 대역 검사를 완료함.
2. 로컬 실제 TCP로 G2 N=1을 실행해 n1 폴더를 만듦. 아래는 구현 후 사용할 명령 형식이며 값은 실제 경로로 치환함.

```text
python -m src.assigner --host 127.0.0.1 --port 9000 --team 2 --canvas-dir "CANVAS_DIR" --out-dir "N1_DIR" --run-id g2-n1-001 --n 1
python -m src.worker --host 127.0.0.1 --port 9000 --log-dir "N1_DIR/logs" --run-id g2-n1-001
```

3. 원격 Assigner를 **--n 없이** 시작함. 출력한 N을 사람이 확인해 로컬 launcher의 --count에 전달함. 원격 bind 주소와 실제 Worker 접속 주소를 구분함.

```text
python -m src.assigner --host 0.0.0.0 --port 9000 --team 2 --canvas-dir "CANVAS_DIR" --out-dir "REMOTE_RUN1_DIR" --run-id g2-run1-001
python -m tools.launch_workers --count N -- python -m src.worker --host SERVER_IP --port 9000 --log-dir "LOCAL_RUN1_DIR/logs" --run-id g2-run1-001
```

4. 새 run_id·폴더로 원격 run2를 실행함. N이 run1과 같으면 새로운 실행으로 다시 시작해 다르게 얻음. 입력은 세 실행 모두 동일한 최종 G2 canvas임.
5. 원격 결과를 로컬 같은 실행 폴더로 취합함. 각 실행의 Worker 로그와 run_id·입력 해시를 대조하고 기존 파일을 덮어쓰지 않음.
6. verify_run을 n1/run1/run2 각각 수행하고 make_hash_result로 세 실행을 비교함. 동일 run1의 frame으로 GIF를 제작함.

```text
python -m tools.verify_run --run-dir "N1_DIR"
python -m tools.verify_run --run-dir "LOCAL_RUN1_DIR"
python -m tools.verify_run --run-dir "LOCAL_RUN2_DIR"
python -m tools.make_hash_result --team 2 --baseline "N1_DIR" --run-a "LOCAL_RUN1_DIR" --run-b "LOCAL_RUN2_DIR" --output "HASH_FILE"
python -m tools.make_gif --run-dir "LOCAL_RUN1_DIR" --output "GIF_FILE"
```

7. round·로그·GIF가 같은 원격 run1에서 나온 것인지 확인하고 실측표·분석·시연을 정리함.

### 제출 체크리스트

- [ ] 각 canvas의 수치 조건과 문구·글꼴 높이·서로 다른 배치를 확인함.
- [ ] N=1 실제 TCP와 서로 다른 무작위 N(4~8)의 원격 실행 두 회를 완료함.
- [ ] 세 실행의 형식·기록 해시·재계산 해시가 일치하고 hash_result 31줄·FINAL이 SAME, TOTAL이 PASS임.
- [ ] Assigner와 모든 Worker가 3,000회를 처리했고 BYE·join·정상 종료를 확인함.
- [ ] 원격 run1 round 31개·로그·GIF가 같은 실행이며 GIF가 실제 301프레임임.
- [ ] 총시간·처리량·Round/Barrier 평균·최대·최지연 Worker·유형별 전송량·띠 높이별 Worker 시간을 실측·분석함.
- [ ] Readme.txt에 조원 이름·학번·역할, 서버 서비스·인스턴스·OS·시간대, 실제 설치/실행 명령, 구성·메시지, Thread/Lock/CV, canvas 제작·검사, 실측·정합성 결과, 한계·배운 점을 작성함.
- [ ] AllDefinedLogs.txt에 모든 실제 EVENT·STATUS·JSON 필드·단위를 정의함.
- [ ] 약 5분 영상에 canvas 설명·검사, 다른 N 두 원격 실행의 시작/접속/진행/종료, GIF 재생, RoundHash와 hash_result 대조를 포함함. 영상의 두 실행은 해시 표 제작 실행과 달라도 되지만 N은 서로 달라야 하고 결과 해시는 같아야 함.
- [ ] download.txt 링크의 다운로드·권한·재생을 확인함.
- [ ] 새 폴더에 ZIP을 풀고 Readme.txt 명령대로 실행 가능한지와 압축 무결성을 확인함.

제출 ZIP은 아래 구성으로 취합함. code에는 실행에 필요한 전체 소스·도구를 포함함. 원본 frames·세 실행 RoundHash·다른 실행 로그는 로컬 증빙으로 보관하며 필요 시 추가함.

```text
G2HW4.zip
├─ code/
├─ canvas/canvas0.txt, canvas1.txt, canvas2.txt
├─ rounds/round0000.txt ... round3000.txt
├─ logs/Assigner.txt, Worker0.txt ... Worker(N-1).txt
├─ hash_result.txt
├─ G2HW4.gif
├─ Readme.txt
├─ AllDefinedLogs.txt
└─ download.txt
```

## 협업과 변경 관리

### Git 작업과 공통 문서 변경

통합 기준은 main임. 담당 브랜치에서 자기 코드·테스트만 수정하고 실행 명령·검사 건수·결과·미완료 항목을 인계함. 안선효가 실제 통합 검사를 확인하고 main 반영을 취합함. 기존 변경을 초기화하거나 상대 변경을 통째로 삭제하지 않음.

공통 규약 수정은 안선효가 이 README와 영향받는 검사 코드를 함께 갱신함. 각 담당은 자기 구현 설명의 변경안을 인계하고, 서로 다른 계약을 먼저 구현하지 않음. 저장소 밖의 예전 계획서는 참고 기록이며 이 README의 개발 규약을 추가하거나 덮어쓰지 않음.

Git에는 코드와 README만 보관함. 입력·샘플·로그·JSON·GIF·영상·제출물·검증 기록은 각 PC에서 지정한 외부 경로에 보관함. fixture는 코드로 임시 디렉터리에 생성함. 기존 HW1~HW3·교수님 원본·키 파일을 수정하거나 산출물을 코드 경로에 저장하지 않음.

### 사용자 확인 범위와 인계

서버 IP·계정·OS·실제 포트 가용성·비용·자료 전달 채널은 환경값임. 없는 값을 추정해 넣지 않으며 원격 실행 전에 안선효가 확인해 전달함. 이 값이 없어도 로컬 규칙·대역·도구 개발은 진행함. 유료 자원 생성·사양 변경은 비용 확인 후 수행함.

시작 보고는 `이름 / 담당 경로 / 브랜치 / Python 버전 / 자료 접근 여부 / 진행 불가 항목`으로 남김. 기존 정보로 담당·경로·규약을 알 수 있다면 재질문하지 않음. 실제 자료 전달·열람 확인을 받지 않았다면 확인 완료로 기록하지 않음.

완료 보고는 `구현 항목 / 변경 경로 / 재현 명령 / 실제 검사 건수·결과 / 미실행·실패·한계 / 상대 담당 인계 내용`으로 정리함. 외부 자료가 없으면 그 자료를 요구하는 검사만 미검증으로 남기고 가능한 구현·검사를 계속함. 독립 검사 통과, 실제 TCP 통합 통과, 원격 실행 통과, 제출 검증 완료를 구분함.
