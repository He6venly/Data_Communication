# HW6 Mini-Torrent

데이터통신 2조 개발 기준임. **안선효 40% · 황대겸 30% · 황왕석 30%**의 분업을 기준으로 패키지·인터페이스·독립 검증 범위를 정함. Tracker·Peer는 구현 전이며 아래 파일 구성과 명령은 구현 계약임. 실제 통합·원격 실행 결과와 성능 수치는 아직 없음.

공식 기준은 `HW6description.pdf`와 `HW6studentSpec.pdf`임. `HW6explanation.pdf`·`HW6QnA.pdf`는 세부 해설, `hw6_student_kit/Python/`은 원본 env·검증 도구·허용 lib의 기준으로 사용함. 위치 지정 파일 I/O는 `pwriteExplanation/`의 가이드와 예제를 참고함. 배포 원본은 로컬에 보존함.

외부 VM·TCP·동시 업로드/다운로드·env·장애·필수 7회·제출 형식은 과제 요구사항임. 아래 4:3:3 분업, Python 선택, 패키지·함수·브랜치 이름, 내부 호출 경계는 팀 설계임. 비율은 구현·검증·통합 부담을 나누는 기준이며 코드 줄 수나 과제 채점 비율이 아님.

## 담당별 작업과 완료 기준

| 담당·비율 | 소유 경로 | 작업 브랜치 기준 | 구현·검증 범위 |
| --- | --- | --- | --- |
| 안선효 40% | `src/common/`, `src/tracker/`, `tests/common/`, `tests/fixtures/transport.json`, `tests/tracker/`, `tests/integration/`, 개발·제출 문서 | `hw6/tracker` | 공유 자료형·예외·인터페이스, 공통 Conn·공유 수신 사례, Tracker 전체, 명단·생존·지시·관찰·report, 실제 통합·VM 배포·7회 정합성·실측 분석·최종 취합 |
| 황대겸 30% | `src/peer/`, `tests/peer/` | `hw6/peer` | Peer 진입점·Tracker 연결·control, worker pool·청크/소스 선택·제한·재시도, crash/rejoin·STALLED·DONE·종료 조율 |
| 황왕석 30% | `src/storage/`, `src/upload/`, `tools/`, `tests/storage/`, `tests/upload/`, `tests/tools/` | `hw6/storage-upload` | 파일·bitmap·해시·결과 저장, 업로드 서버·공유 UP 제한기, 화면, 실행·결과 보관·추가 검사 도구·시연 자료 |

소유 경로는 저장소 `HW6/` 기준임. 브랜치 이름은 작업 기준이며 현재 브랜치를 만들었다는 뜻은 아님. 기존 체크아웃과 사용자 변경을 보존하며 새 워크트리를 만들지 않음. 상대 담당의 내부 파일을 직접 수정하지 않고 아래 공개 인터페이스와 대역으로 독립 구현함. 각 담당이 자기 코드의 테스트와 로그 정의를 작성하고 안선효가 최종 문서·결과를 합침.

### 안선효: Tracker·통합 40%

1. 공통 Conn·공유 수신 사례 → env 검증·TCP 명령 → 참가·명단·생존 → scheduler·지시 → observer·report → ALLDONE·ABORT·종료 순서로 구현함. Conn은 세 소비자가 함께 사용하고 Tracker 설정·로그는 자기 패키지에서 관리함.
2. 대역 Peer 4개로 REGISTER/HAVE·LIST/PEERS·heartbeat·재참가·DONE/UNDONE·BYE를 확인함. 분할/합친 수신, 낡은 REPORT, 세 파괴 조건, replica_safe, DEAD·hang·deadline도 검사함.
3. origin을 뺀 fresh live bitmap OR와 T_rep·p_rep·dup_ratio, 지시 등록/전달 시각, report 키·시각 기준·종료 코드가 맞으면 독립 구현 완료임.
4. 실제 Peer 통합, 로컬 DEV와 VM Tracker DEV, 제출 7회, 데이터·속도·로그·report 정합성과 C3 분석, 제출 Readme·로그 사전 취합을 맡음. 원격 자원 종류·리전·주소는 실제 배포 시 기록함.

### 황대겸: Peer 제어·다운로드 30%

1. CLI·TrackerLink → 원본 등록·LIST 대기·HAVE 재시도 → 가짜 FileStore/UploadServer 연결 → worker·random/rarest·소스 선택 → 주기 갱신·REPORT → 장애·DONE·종료 순서로 구현함. 수신은 공통 Conn을 사용함.
2. 대역 Tracker·업로드 서버로 TCP 분할, 짧은 마지막 청크, idx/len 오류, 중복 예약 방지, 상대당 inflight, 공유 DOWN 제한기, 실패·BAN·캐시 제거를 검사함.
3. crash 동안 송신 0·복귀 즉시 재등록/갱신, tracker_lost, STALLED/UNSTALLED·DONE/UNDONE, ALLDONE 전 업로드 유지와 모든 스레드 종료까지 확인하면 독립 구현 완료임.
4. 파일 쓰기·해시·rename·bitmap 갱신은 FileStore에 맡김. 검증된 완성 상태를 받은 뒤 REGISTER하며, 저장소 내부 Lock·fd·mmap을 직접 조작하지 않음.

### 황왕석: 저장소·업로드·도구 30%

1. FileStore의 위치 지정 읽기/쓰기·원본 검사 → 예약·commit·완성 검증 → 결과 저장 → BITMAP/GET 서버·UP 제한기 → 화면·도구 순서로 구현함.
2. 네트워크 없는 테스트와 대역 다운로드 클라이언트로 다중 worker 쓰기, 부분 읽기/쓰기, 짧은 마지막 청크, 디스크 기록 전 bitmap 비공개, 완성 처리 1회, 해시 실패 재수신을 검사함.
3. Windows 매핑·파일 핸들 종료 후 rename, crash 시 연결 차단, 재기동, 종료 시 모든 Peer·파일의 bitmap과 필요한 lost/incomplete, 연결 재사용·스레드 종료를 확인하면 독립 구현 완료임.
4. Peer 4개 실행·종료 코드 수집, 공식 verify 실행·출력 저장, Run별 기록 보관·추가 정합성 검사 도구를 제공함. 대역 명령으로 기동 도구도 검증함. 실제 Run·시연 결과는 통합 이후 별도 확인함.

## 필수 요구사항

| 항목 | 필수 조건 |
| --- | --- |
| 프로그램·배포 | 외부 VM의 Tracker 1개, 로컬 PC 한 대의 Peer 4개를 각각 독립 프로세스로 실행함. 개발 중 로컬 Tracker 사용 가능하나 제출 7회는 VM Tracker 구성임 |
| 통신 | TCP Socket. Peer가 Tracker에 연결하며, DATA는 Peer 사이에서만 전송함. 외부 P2P·RPC·JSON 라이브러리 금지, 언어 표준 라이브러리와 해당 언어의 키트 lib만 허용함 |
| 동시성 | Peer의 업로드 서버는 연결당 handler 스레드, 다운로드는 env의 worker pool을 사용함. 기본 worker 8개, 상대당 진행 중 GET 최대 4개임 |
| 데이터 | 본 시나리오는 10·20·30 MiB, DEV는 3·5·7 MiB임. 청크 65,536 B, 마지막 청크는 실제 남은 길이만 처리함. 공개 크기의 배수 조건을 가정하지 않음 |
| 초기 보유 | 공개 설정에서 P1·P2·P3가 각 파일의 원본, P4는 빈 상태임. 구현은 `files[].origin`과 `peers[]`를 읽음 |
| 진행률 | 원본을 제외한 수신 청크 합 ÷ `progress_total_chunks`. 공개 본 시나리오 2,880, DEV 720임 |
| 설정 | Tracker와 Peer가 같은 원본 env를 읽음. 포트·속도·정책·시간·일정·피어 이름을 하드코딩하거나 Run 이름으로 동작을 분기하지 않음 |
| 속도 | Peer 전체에 UP·DOWN 제한기 각 1개. KB/s × 1,024로 계산하며 두 방향의 한도는 독립임. 실행 전체 평균이 각 한도 이하여야 함 |
| 장애 | Tracker의 HEARTBEAT 응답으로만 가상 crash·destroy를 지시함. crash 중 모든 네트워크 송신을 멈추며, destroy는 결과 저장 후 BYE 없이 exit 3임 |
| 완료 | DONE 후에도 ALLDONE까지 업로드함. 유실이 있더라도 받을 수 있는 청크를 모두 받고 생존자 bitmap이 같아야 함 |
| 종료 | 0: ALLDONE 정상(FULL·PARTIAL), 1: 인자·설정·원본 해시 오류, 2: ABORT·tracker_lost, 3: 파괴된 희생자임. 모든 대기에 timeout을 둠 |
| 필수 증거 | 제출 7회 모두 공식 verify PASS, JSONL 5개, report, verify 출력, 희생자를 포함한 모든 Peer의 bitmap·필요한 lost를 보관함 |

### env·CLI 읽기와 오류

| 설정 | 읽는 쪽과 사용 규칙 |
| --- | --- |
| `version`, `name`, `run`, `seed`, `description` | version=1만 허용함. name·run·seed·description은 실행 식별·설명에 보존하며 seed는 생성 기록임. Run 이름으로 동작을 분기하지 않음 |
| `tracker.port`, `peers[].id/host/port/dir` | Tracker는 `0.0.0.0`에 bind하며 CLI PORT가 기본 포트보다 우선함. Peer는 자기 env host·port에만 bind하고 env dir에 저장함. Tracker IP는 Peer 마지막 두 인자로만 받음 |
| `chunk_size`, `files[].name/size/origin/sha256` | 청크 수는 올림, idx는 0부터, 길이는 `min(chunk_size, size - idx*chunk_size)`임. 원본 보유·REGISTER 값·파일 전체 해시·bitmap 크기의 기준임 |
| `peers[].up_kbps/down_kbps`, `progress_total_chunks` | 각 한도를 B/s로 변환하며 원본을 제외한 청크 진행률의 분모를 읽음 |
| `download.workers/per_peer_max/policy/policy_seed` | worker·상대당 한도·정책·청크 선택 seed를 읽음. CLI policy 우선, env policy=null이고 CLI도 없으면 exit 1임 |
| `timing.*`, `crashes[]`, `destroy` | 아래 주기·생존·제외·손실·응답 제한과 모든 장애 조건을 그대로 읽음. 비공개 env의 파일·피어·속도·포트·시각 변경도 지원함 |

Peer IP/PORT 누락·숫자가 아닌 PORT·version≠1·env에 없는 id·정책 누락/오류·원본 SHA-256 불일치는 사용법/원인을 출력하고 exit 1임. 시작부터 Tracker에 닿지 않는 경우는 설정 오류로 즉시 끝내지 않고 `tracker_lost_sec` 뒤 결과를 정리해 exit 2임. 정상 실행을 시작하기 전의 인자 오류에는 로그 파일 생성이 필수가 아니나, 로거가 열린 뒤의 오류는 마지막 EXIT code=1도 남김.

### 공개 설정과 실행 7회

| 실행·결과 폴더 | env | 정책 | crash 수 | 파괴 조건 | 기대 결과 |
| --- | --- | --- | ---: | --- | --- |
| `DEV` | `DEV.json` | random | 2 | 없음 | 전원 FULL·exit 0 |
| `A` | `A.json` | random | 8 | 없음 | 전원 FULL·DEAD 오판 0 |
| `B` | `B.json` | random | 3 | P3, START+34초부터 replica_safe를 만족하면 파괴 | 생존자 FULL, P3 exit 3·DEAD |
| `C1` | `C1.json` | rarest | 0 | P4, 진행률 ≥ 0.475 | 생존자 FULL, 유실·STALLED 0 |
| `C2` | `C2.json` | rarest | 0 | P3, 진행률 ≥ 0.308, 안전 확인 없음 | 생존자 PARTIAL·bitmap 수렴, P3 exit 3 |
| `C3_random` | `C3.json` | CLI random | 0 | P1, 진행률 ≥ `p_rep + 0.369 × (1 − p_rep)` | 생존자 FULL, 비교용 report |
| `C3_rarest` | 동일 `C3.json` | CLI rarest | 0 | 동일 공식, 정책별 관측 p_rep 사용 | 생존자 FULL, 비교용 report |

위 값은 공개 설정 설명이며 구현 상수가 아님. C3는 Peer 4개 모두 같은 정책을 명시하며 두 실행 사이에 초기화함. B의 34초는 파괴를 검토하기 시작하는 시각임. 실제 파괴 시각·C2 손실 수·정책별 성능은 실행 후 측정함.

공개 timing은 heartbeat 2초, bitmap 갱신 1초, PEERS 갱신 3초, DEAD 20초, STALLED 30초, hang 60초, deadline 900초, 화면 상태 주기 5초, 연속 실패 3회, BAN 5초, REPORT 유효기간 3초, tracker_lost 30초임. 구현은 각 값을 env에서 읽음. 명세상 구현 상수인 scheduler 0.5초, GET·연결 timeout 5초, ABORT 뒤 대기 15초, 종료 업로드 유예 최대 3초는 별도로 둠.

## 패키지와 공통 인터페이스

Python 3.12 이상과 표준 라이브러리를 사용함. 기존 Python 과제 경험을 활용하고 배포 도구와 실행 환경을 맞추기 위한 선택임. Tracker는 Linux VM, 로컬 Peer는 Windows를 기준으로 설계함. VM 종류·리전·주소는 실제 배포 때 정하며 HW5의 주소를 가져오지 않음.

위치 지정 파일 I/O는 Linux의 `os.pread/pwrite`, Windows의 표준 `mmap`을 감싸는 동일 인터페이스로 설계함. 제공 mmap 예제가 근거임. Windows에서는 파일 크기를 먼저 확보하고, 매핑·파일 핸들을 닫은 뒤 rename함. 공유 파일 오프셋을 바꾸는 `seek + write`는 사용하지 않음. Windows 지원과 동시 종료·rename 동작은 구현 후 검증할 항목임.

### 구현할 파일 구성

현재 제공된 코드는 `src/common/contracts.py`의 자료형·예외·Protocol뿐임. 아래 Conn·Tracker·Peer·저장소·업로드·도구는 구현 전임. 실행 디렉터리는 `HW6/`, `src/`와 그 하위 폴더는 초기화 로직 없는 Python 네임스페이스 패키지로 구성함. 담당 내부의 파일 분리는 조정할 수 있으나 소유 경로와 공개 계약은 유지함.

```text
HW6/
├── README.md
├── .gitignore
├── src/
│   ├── common/                  안선효 40%, 세 소비자가 공유
│   │   ├── contracts.py         고정 자료형·예외·Protocol (제공됨)
│   │   └── transport.py         Conn·줄/정확한 바이트 수신 (구현 대상)
│   ├── tracker/                 안선효 40%
│   │   ├── __main__.py          CLI·기동·종료
│   │   ├── server.py            요청 처리·명단·공유 상태
│   │   ├── scheduler.py         생존·가상 장애·완료·ABORT
│   │   ├── observer.py          REPORT·복제·replica_safe
│   │   ├── report.py            지표 고정·report 저장
│   │   ├── config.py            Tracker env 검증
│   │   └── log.py               Tracker JSONL
│   ├── peer/                    황대겸 30%
│   │   ├── __main__.py          CLI·구성요소 조립
│   │   ├── client.py            시작·가상 장애·종료 조율
│   │   ├── tracker_link.py      요청·응답 직렬화·재연결
│   │   ├── control.py           주기 갱신·REPORT·STALLED·DONE
│   │   ├── download.py          worker·GET·재시도·DOWN 제한
│   │   ├── selection.py         원격 캐시·rarity·선택·BAN
│   │   ├── config.py            Peer env·CLI 검증
│   │   └── log.py               Peer JSONL·공유 이벤트 발행
│   ├── storage/                 황왕석 30%
│   │   ├── store.py             FileStore·예약·bitmap·commit
│   │   ├── positional.py        pread/pwrite·Windows mmap
│   │   └── results.py           HASH·완성·bitmap/lost 저장
│   └── upload/                  황왕석 30%
│       ├── server.py            listener·연결당 handler
│       ├── limiter.py           공유 UP 제한기
│       └── screen.py            상태판·최근 이벤트
├── tools/                       황왕석 30%
│   ├── launch_peers.py          Peer 4개 기동·종료 코드 수집
│   ├── collect_run.py           verify 후 기록만 Run별 보관
│   └── check_run.py             속도·report·bitmap/lost 추가 검사
└── tests/
    ├── common/                  안선효, 공통 Conn 검사
    ├── fixtures/transport.json  안선효, 세 담당의 공유 수신 사례
    ├── tracker/                 안선효
    ├── integration/             안선효
    ├── peer/                    황대겸
    ├── storage/                 황왕석
    ├── upload/                  황왕석
    └── tools/                   황왕석
```

Tracker와 Peer는 `python -m src.tracker`, `python -m src.peer`로 실행함. 업로드·저장소는 Peer 프로세스 안에서 동작하며 별도 프로세스를 추가하지 않음. **Tracker·Peer·Upload 모두 `src.common.transport.Conn` 하나를 import함.** 자료형·예외·Protocol은 모두 `src.common.contracts`를 import하고 각자 다시 정의하지 않음. 공통 모듈에 env 읽기·로그·Tracker/Peer 실행 로직을 넣지 않음. 배포 lib를 활용할 때는 해당 담당 패키지 안에 필요한 파일과 출처·라이선스를 보존함. 실행에 필요한 원본 env·도구는 별도 키트 경로로 받음.

### 생성자·import·의존 방향

아래 인자 이름·타입·기본값을 그대로 사용함. `*` 뒤 인자는 모두 keyword-only임. env는 JSON 원본 필드 이름을 유지한 Mapping이며, 각 담당이 만든 Config 객체나 필드명이 바뀐 dict를 넘기지 않음. root는 `Path.cwd().resolve()`인 절대 Path임. env dir가 상대 경로이면 root 기준, 절대 경로이면 그대로 사용하며 env 파일의 부모 폴더 기준으로 해석하지 않음. 구성요소는 받은 env를 변경하지 않음.

| 실제 구현 경로·클래스 | 고정 생성자 | 생성 시 동작 |
| --- | --- | --- |
| `src.storage.store.FileStore` | `FileStore(*, env: Env, peer_id: str, root: Path, emit: EventSink)` | 설정을 보관함. 파일 I/O는 initialize에서 수행함 |
| `src.upload.server.UploadServer` | `UploadServer(*, env: Env, peer_id: str, store: StorePort, stopping: Event, emit: EventSink)` | 저장소·신호·콜백을 보관함. bind·스레드 시작은 start에서 수행함 |
| `src.upload.screen.StatusScreen` | `StatusScreen(*, stopping: Event, period_sec: float, stream: TextIO \| None = None)` | stream=None이면 sys.stdout. 스레드 시작은 start에서 수행함 |
| `src.peer.log.EventLog` / `src.tracker.log.EventLog` | `EventLog(*, peer_id: str, root: Path, started_at: float)` | root/logs/id.jsonl을 열되 START/EXIT를 자동 생성하지 않음. tracker의 id는 소문자 tracker임 |
| `src.common.transport.Conn` | `Conn(sock: socket.socket)` | 전달받은 연결의 버퍼만 생성함. connect·timeout 설정은 호출자가 수행함 |

황대겸의 peer main이 FileStore·UploadServer·StatusScreen을 조립함. storage/upload는 peer나 tracker 구현을 역으로 import하지 않음. UploadServer는 생성자로 받은 StorePort만 호출함. 화면은 callback으로 받은 PeerView만 읽음. 자료형·Protocol을 제공한 것과 실제 클래스의 구현 완료를 구분함.

```python
# Peer 구성 예시. 실제 구성요소는 각 담당이 구현할 대상임.
from pathlib import Path
from threading import Event
from src.storage.store import FileStore
from src.upload.server import UploadServer
from src.upload.screen import StatusScreen

root = Path.cwd().resolve()
stopping = Event()  # peer main만 set함. 하위 구성요소는 읽기만 함.
store = FileStore(env=env, peer_id=peer_id, root=root, emit=log.event)
store.initialize()  # log의 START 뒤, upload.start와 HELLO 앞
upload = UploadServer(env=env, peer_id=peer_id, store=store,
                      stopping=stopping, emit=log.event)
screen = StatusScreen(stopping=stopping,
                      period_sec=float(env["timing"]["status_every_sec"]))
upload.start()
screen.start(snapshot=build_peer_view, recent=log.recent)
```

### 반환 자료형·단위·스냅샷 구조

정의는 제공된 `src/common/contracts.py`로 고정함. 아래 snapshot/result/token은 `frozen=True, slots=True, kw_only=True` dataclass임. dict·임의 객체·서로 다른 자체 dataclass로 바꾸지 않음. 중첩 목록도 tuple이므로 외부에서 저장소 상태를 변경할 수 없음. 모든 필드는 필수이고 생략 기본값이 없음.

| 자료형 | 필드와 정확한 타입 |
| --- | --- |
| `Reservation` | `file:str`, `idx:int`, `generation:int`, `serial:int` |
| `FileSnapshot` | `name:str`, `size:int`, `chunk_size:int`, `nchunks:int`, `origin:str`, `sha256:str`, `state:FileState`, `prepared:bool`, `bitmap:str`, `in_progress:tuple[int,...]`, `sent:int`, `distinct:int`, `sources:tuple[tuple[str,int],...]`, `received_bytes:int`, `sent_bytes:int`, `hash_failures:int` |
| `StoreSnapshot` | `peer_id:str`, `generation:int`, `paused:bool`, `downloaded_have:int`, `received_bytes:int`, `sent_bytes:int`, `files:tuple[FileSnapshot,...]` |
| `CommitResult` | `accepted:bool`, `state:FileState`, `complete_now:bool`, `reason:Literal["STALE","RELEASED","CONSUMED"] \| None` |
| `PeerView` | `peer_id:str`, `elapsed_sec:float`, `online:bool`, `policy:Literal["random","rarest"]`, `up_kbps:int`, `down_kbps:int`, `actual_up_kbps:float`, `actual_down_kbps:float`, `files:tuple[FileSnapshot,...]` |

`FileState`는 DOWN·VERIFYING·SEED·STALLED·FAILED 문자열 Enum임. VERIFYING은 해시 검사·rename 중의 내부 상태이며 화면에서는 DOWN으로 표시하고 DONE 대상에서 제외함. 로그·JSON에는 `.value`를 사용함. bitmap은 nchunks 길이의 0/1 문자열, in_progress는 정렬된 예약 idx tuple, sources는 피어 id 순으로 정렬한 `(src, 청크 수)` tuple임. FILES 순서는 env.files 순서를 유지함. 호출자는 `{f.name: f for f in snap.files}`로 이름별 조회함.

`downloaded_have`는 snapshot.files에서 origin≠내 id인 파일의 bitmap 1 개수 합임. 원본은 제외하며 hash 재시도 시 줄어들 수 있음. received_bytes/sent_bytes는 실제 수신 commit/전체 송신 성공의 누적 바이트이며 원본 크기를 더하지 않음. hash 재시도·crash 때 누적 바이트를 0으로 되돌리지 않음. sources는 현재 파일 수신 시도의 출처 수이며 CORRUPT 재수신 때 초기화함. sent는 전체 송신한 청크 횟수, distinct는 보낸 서로 다른 idx 수임. 크기·바이트·청크 수는 int, 경과 시간은 초 float, 속도는 KB/s이며 1 KB=1,024 B임. EXIT up_mb/down_mb는 누적 바이트÷2^20임.

snapshot의 파일별 복사본과 downloaded_have·바이트 합은 같은 세대·같은 복사본에서 계산함. 스냅샷 생성 중 I/O를 하지 않으며 호출자가 내부 Lock을 잡지 않음. 상태판의 실제 속도는 황대겸이 누적 바이트 차이/경과 시간/1,024로 계산해 PeerView에 넣음. 화면 담당이 별도 전송 통계나 단위 변환을 추측하지 않음.

### FileStore·업로드·로그 메서드 계약

| 공개 메서드 | 반환값·동작 |
| --- | --- |
| `initialize() -> None` | 원본 검증·메타정보를 준비함. 원본은 SEED·전부 1·prepared=True, 그 외는 DOWN·전부 0·prepared=False임. generation=0·paused=False로 시작함. 실패 시 열었던 핸들을 자체 정리하고 초기화 성공으로 표시하지 않음 |
| `snapshot() -> StoreSnapshot` | 초기화 후 사용함. finalize 뒤에도 마지막 스냅샷 조회 가능함 |
| `prepare_download(file:str) -> FileSnapshot` | 전체 크기 .part를 최초 한 번 준비함. 동일 파일 재호출·원본·완성 파일은 기존 상태를 반환하고 초기화하지 않음 |
| `reserve(file:str, idx:int) -> Reservation \| None` | prepared·DOWN·미보유·미예약·online일 때만 토큰 반환. 후보 불가·paused는 None이며 실패/BAN이 아님. serial은 이 FileStore에서 재사용하지 않는 정수임 |
| `commit(token:Reservation, data:bytes, src:str) -> CommitResult` | 크기·토큰을 확인해 위치 쓰기→bitmap→RECV를 수행함. 성공은 accepted=True·reason=None이며 해시 재시도로 DOWN/FAILED가 되어도 해당 commit 자체는 성공임. 마지막 성공 해시를 처리한 호출 하나만 complete_now=True임 |
| `release(token:Reservation) -> None` | finally에서 호출함. 성공·실패·이전 세대·이미 release·finalize 뒤 모두 안전한 반복 호출임. 다른 토큰의 예약을 지우지 않음 |
| `read_chunk(file:str, idx:int) -> bytes` | 정확히 clen(idx) 바이트. 모르는 파일은 NoFileError, 정상 idx의 미보유/미준비는 NoChunkError, paused는 OfflineError임. 에러 문자열·빈 bytes로 대신하지 않음 |
| `record_sent(file:str, idx:int, size:int) -> None` | DATA 전체 송신 성공 후 호출. size=clen(idx) 확인 뒤 누적 통계를 반영함. 실제 송신이 끝났다면 pause 직후라도 집계함 |
| `set_stalled(file:str, stalled:bool) -> bool` | DOWN↔STALLED가 실제 전환된 경우 True, 변화 없음/SEED/VERIFYING/FAILED면 False. control은 True일 때만 STALLED/UNSTALLED를 기록함 |
| `pause() -> None`, `resume() -> None` | 첫 pause가 세대를 1 증가시키고 예약을 무효화함. 새 commit을 차단·진행 중 I/O를 정리함. 반복 pause는 세대를 추가 증가시키지 않음. resume은 그 새 세대를 online으로 열며 데이터·bitmap·누적 통계를 유지함 |
| `finalize() -> StoreSnapshot` | 모든 생산 스레드 종료 뒤 결과를 저장하고 핸들을 닫음. paused=True의 마지막 스냅샷을 반환함. LIST 대기 등으로 아직 prepare하지 않은 파일도 bitmap·필요한 lost/0으로 채운 incomplete를 남김. 성공 뒤 반복 호출은 같은 스냅샷이며 I/O를 반복하지 않음. snapshot/finalize/release 외 호출은 이후 LifecycleError임 |
| `UploadServer.start() -> None` | bind·listen 성공 후 반환함. 실행 중 재호출은 no-op. initialize 완료된 FileStore를 요구함 |
| `offline() -> None`, `online() -> None` | offline은 listener·기존 연결을 닫고 세대를 무효화함. online은 start 이후의 재바인드임. 반복 호출은 no-op이며 이전 handler가 새 세대에서 DATA를 보내지 못함. 최종 stop 뒤 online은 LifecycleError임 |
| `stop(grace_sec:float=3.0) -> None` | 신규 연결을 막고 진행 업로드를 0~3초 유예 후 강제로 연결을 닫음. 그 뒤 최장 5초의 join 예산으로 listener/handler 종료를 확인하며 남으면 ShutdownError임. stopping Event를 임의로 set하지 않음 |
| `StatusScreen.start(snapshot:Callable[[],PeerView], recent:Callable[[int],tuple[str,...]]) -> None` | 데이터 자체가 아닌 두 공급 함수를 받음. period_sec마다 호출하여 표시하며, recent(n)으로 최근 n줄을 얻음. repeat start는 no-op임 |
| `StatusScreen.stop() -> None` | 반복 가능함. 화면 스레드를 최대 5초 내 join하고 남으면 ShutdownError임. 공급 함수는 메모리 복사만 하고 네트워크/파일 I/O를 하지 않음 |
| `EventLog.event(ev:str, **fields:JSONValue) -> None`, `recent(n:int=5) -> tuple[str,...]`, `close() -> None` | event가 파일·flush·최근 버퍼를 함께 처리함. recent는 시간순 복사본, close는 반복 가능함. close/EXIT 이후 event는 LifecycleError임. kwargs에 t·peer·ev를 덮어쓰지 않음 |

같은 인자로 initialize/start를 반복 성공 호출해도 중복 파일 초기화·스레드 생성을 하지 않음. initialize 전의 데이터 메서드와 finalize/최종 stop 이후 재초기화는 LifecycleError임. 원본 검증으로 initialize가 실패한 경우 main은 finalize를 호출하지 않고 EXIT 1로 정리함. 인자의 잘못된 타입은 TypeError, idx/본문 크기 등 청크 계약 위반은 InvalidChunkError임. `commit`의 거절 판정 우선순위는 STALE→RELEASED→CONSUMED이며 accepted=False·complete_now=False·현재 파일 state를 반환하고 RECV·have·출처·바이트를 늘리지 않음. 이 세 결과는 상대 FAIL/BAN이 아님. 발급되지 않은 토큰은 InvalidChunkError임. worker는 반환값과 관계없이 finally로 release함.

FileStore는 emit을 상태 Lock 밖에서 호출하고 마지막 청크의 RECV→HASH 순서를 보장함. 자료형 객체를 이벤트 값으로 직접 넘기지 않고 bool/int/float/str/list/dict/null의 JSON 값으로 바꿔 넘김. COMPLETE sources는 `dict(file_snapshot.sources)`임. registered_files는 Peer가 관리하여 SEED지만 REGISTER OK를 받지 못한 파일이 있으면 DONE을 보류하고 등록만 재시도함.

### 예외·프로토콜 응답·프로세스 종료 대응

아래 예외는 모두 공유 파일에서 import함. HW6Error 계열은 `Error(message:str, *, operation:str="", file:str|None=None)` 형식이며 operation/file 속성을 보존함. 문자열 메시지를 비교하여 분기하지 않음. ConnClosed는 ConnectionError의 하위 클래스이며 transport 모듈에서도 같은 클래스를 재노출함.

| 예외·상황 | 처리 담당·고정 대응 |
| --- | --- |
| `ConfigurationError` | 각 main. env·CLI·초기 원본 검증 오류로 exit 1 |
| `NoFileError` | Upload handler는 ERR NOFILE로 응답하고 같은 연결을 계속 처리함 |
| `NoChunkError` | Upload handler는 ERR NOCHUNK로 응답하고 같은 연결을 계속 처리함 |
| `InvalidChunkError` | Upload의 GET idx 형식·범위 오류는 ERR BADCMD. Peer가 받은 DATA의 idx/len 오류는 commit 전 FAIL·연결 폐기·예약 해제. FileStore에 잘못된 인자를 넘긴 로컬 오류는 ERROR kind=contract로 실패 종료함 |
| `OfflineError` | Upload는 응답을 보내지 않고 연결을 닫음. crash 중 ERR를 송신하지 않음 |
| `ConnClosed`, `TimeoutError`, 네트워크 `OSError` | worker의 실제 원격 요청 실패이면 FAIL·해당 연결 폐기·예약 해제·BAN 집계. 자체 crash/stopping 취소는 집계에서 제외함. TrackerLink는 연결을 새로 열고 tracker_lost를 별도로 판정함 |
| `StoreIOError` | 로컬 I/O 오류를 상대 FAIL/BAN으로 돌리지 않음. main에 전달하고 ERROR kind=local_io·정리·EXIT 2로 끝냄. `.corrupt`는 I/O 실패가 아닌 해시 2회 불일치 때만 사용함 |
| `LifecycleError`, `ShutdownError`, 잘못된 로컬 타입 | 숨기거나 PASS로 처리하지 않음. ERROR kind=contract 또는 shutdown·EXIT 2로 인계함. destroy 자체가 성공한 EXIT 3과 정리 실패 EXIT 2를 구분함 |

로컬 실패용 ERROR는 추가 이벤트이며 `kind,operation,file,message`를 기록함(file이 없으면 null). Tracker로 보내는 ABORT reason이나 과제 필수 메시지 형식은 바꾸지 않음. 내부 예외는 emit·실패 큐/공유 상태로 peer main에 전달하고 worker/handler 안에서 조용히 소멸시키지 않음. 실제 클래스는 위 Protocol과 서명을 맞춤. FileStore/UploadServer/StatusScreen은 생성 시 I/O·네트워크·스레드를 시작하지 않으며, EventLog의 명시적인 로그 파일 열기만 생성자 I/O 예외임.

### 도구의 CLI·결과 인계 계약

tools는 `HW6/`에서 `python -m tools.이름`으로 실행하고 구현 패키지의 내부 객체를 import하지 않음. 아래 대문자 자리표시자는 실제 경로·주소로 바꿈. 경로는 공백을 포함할 수 있으므로 subprocess는 shell 문자열 대신 argv 목록을 사용함.

| 도구·고정 CLI | 동작·성공/실패 기준 |
| --- | --- |
| `python -m tools.launch_peers --env ENV [--python EXE] [--policy random\|rarest] TRACKER_IP PORT` | EXE 기본값은 sys.executable. env의 각 id로 `EXE -m src.peer --env ENV --id ID [--policy POLICY] IP PORT`를 실행함. VM Tracker는 별도로 먼저 기동함. 희생자 3·생존자 0이면 도구 0, 다른 종료 코드는 도구 1임. CLI 오류는 1이고 C3 정책 누락을 자식 기동 전에 거부함 |
| `python -m tools.collect_run --env ENV --kit KIT --run-name RUN [--runs-dir runs]` | KIT는 Python 키트 경로. 현재 폴더의 VM 로그·report 존재를 확인하고 `sys.executable KIT/tools/verify.py --env ENV`를 실행하여 출력 전체를 verify.txt에 저장함. 공식 verify와 추가 정합성이 통과하면 logs·report·verify·p1~p4의 bitmap/lost만 runs/RUN에 복사함. 원래 데이터는 삭제하지 않음 |
| `python -m tools.check_run --env ENV --run-dir RUN_DIR [--policy random\|rarest]` | 기록 파일만 읽어 5개 로그·필수 이벤트/필드·EXIT·시각·희생자 포함 bitmap/lost·속도·정책·report를 검사함. C3는 policy 명시 필수. 통과 0, 미달/누락/형식 오류 1임. 큰 데이터가 없는 보관 폴더의 검사를 공식 verify 재실행으로 표현하지 않음 |

RUN은 DEV·A·B·C1·C2·C3_random·C3_rarest 중 하나이며 env.name·C3 정책과 대조함. 이미 있는 runs/RUN을 덮어쓰지 않고 exit 1로 끝냄. 실패 출력은 verify.txt에 보존하되 정상 제출 Run으로 보관하지 않음. launch_peers 자동 검사에서는 자식 stdout을 버려 상태판을 끄고 stderr는 사용자가 확인할 수 있게 유지함. 시연은 별도 터미널 4개에서 Peer를 직접 실행하여 ASCII 화면을 확인함.

각 담당은 자기 브랜치에 자기 소유 경로만 인계함. `src/common/contracts.py`는 세 브랜치가 같은 정의를 사용하고, 전달물에 같은 이름의 복제 contracts/transport나 다른 버전의 공통 타입을 포함하지 않음. 안선효는 공통 코드 기준을 먼저 맞춘 뒤 storage/upload와 peer를 조립하며, 기존 문서나 다른 조원의 파일을 덮어쓰는 폴더 전체 교체를 하지 않음.

FileStore는 commit의 디스크 기록·bitmap 갱신 직후 RECV를 기록하고, 마지막 청크라면 그 뒤 HASH·필요한 CORRUPT를 기록함. worker는 src를 전달하고 RECV를 중복 기록하지 않음. COMPLETE·제어 이벤트는 Peer가 기록함. 업로드는 전체 송신 성공 통계만 집계하며 **SEND 로그를 남기지 않음**. 출처는 수신자의 RECV.src로 분석함(PPT p.182). 복사본을 얻은 뒤 reserve가 실패하면 다른 후보를 다시 고름. 파일 bitmap·fd·mmap·내부 Lock을 다른 패키지에서 직접 읽거나 변경하지 않음.

### 공통 TCP 수신 버퍼와 공유 검사

안선효가 `src/common/transport.py`와 `tests/fixtures/transport.json`을 단독 소유함. Tracker·Peer·Upload에 별도 transport.py나 Conn 사본을 만들지 않음. 공통 모듈은 다른 구현 패키지를 import하지 않으며 각 담당의 명령 처리·응답 검증은 자기 패키지에서 검사함. 공통 Conn·공유 사례를 먼저 제공하고 상대 구현을 기다리는 동안은 같은 공개 API의 대역을 사용함.

서명은 `read_line() -> str`, `read_exact(n:int) -> bytes`, `send_line(text:str) -> None`, `send_all(data:bytes) -> None`, `close() -> None`임. Conn(sock)은 소켓당 하나의 rbuf를 소유함. read_line은 LF까지 소비하고 LF를 뺀 UTF-8 문자열, read_exact는 버퍼의 남은 바이트부터 정확히 n바이트를 반환함. send_line은 UTF-8+LF, send_all은 헤더·바이너리의 전부 송신, close는 대기 중 I/O를 깨우는 종료를 담당하며 반복 가능함. 불완전한 줄·본문의 EOF는 공통 contracts의 ConnClosed, 시간 초과는 TimeoutError로 전달하며 짧은 본문을 성공으로 돌려주지 않음. n=0은 빈 bytes임. timeout·연결 재수립·DATA idx/len·LIST/PEERS 후속 줄 수 검증은 호출자의 책임임. 중간 응답에서 timeout/EOF가 나면 그 연결을 폐기하고 새 연결에서 요청 전체를 다시 시작함.

공유 JSON은 사례 id, 수신 조각의 16진수 배열, 호출 순서, 기대 반환값·예외로 구성하는 계약임. 아래 입력을 세 담당이 동일하게 사용하며, 표는 구현 전 검사 기준이고 실행 PASS가 아님.

| 공유 사례 | 입력·조건 | 확인할 결과 |
| --- | --- | --- |
| 분할 줄·UTF-8 | `OK\n` 및 한글 헤더를 바이트 하나씩 수신 | LF 전까지 기다림, UTF-8 디코딩은 줄이 모인 뒤 수행함 |
| 붙은 줄 | 한 recv에 `OK\nSTATE 0 4 WAIT\n` | 두 read_line이 각각 한 줄을 반환함 |
| 헤더·본문·다음 응답 | 한 recv에 `DATA 1 3\nA\nBOK\n` | read_line → DATA 헤더, read_exact(3) → `A\nB`, 다음 read_line → OK. 본문의 LF를 헤더로 해석하지 않음 |
| 분할 본문·바이너리 | 본문 조각에 NUL·LF·UTF-8이 아닌 바이트 포함 | 선언 길이만큼 원래 bytes를 복원하고 남은 바이트를 보존함 |
| 짧은 마지막 청크 | 파일 11 B·chunk 8 B·idx 1 | DATA len=3, 제한·읽기·쓰기 모두 3 B, 8 B를 기다리지 않음 |
| 다중 행 응답 | FILES/PEERS 헤더·n줄·다음 OK가 한꺼번에 수신 | TrackerLink가 n줄 전체를 소비하고 다음 응답을 보존함 |
| EOF·timeout·0바이트 | 줄/본문 중간 EOF, 무응답, read_exact(0) | ConnClosed·TimeoutError·빈 bytes를 구분함 |
| 잘못된 DATA | 요청과 다른 idx·음수/초과/짧은 len | Peer가 commit 전에 거부하고 해당 소스 연결·예약을 정리함 |

공통 Conn 검사는 안선효, Tracker의 다중 행·명령 검사는 안선효, Peer의 DATA 검사는 황대겸, Upload의 응답·FileStore 마지막 청크 검사는 황왕석이 맡음. 세 담당은 같은 사례를 자기 경로의 의미 검사에 재사용함.

### TCP 계약

헤더는 UTF-8 한 줄, 공백 구분, LF 종료임. 소켓마다 수신 버퍼 하나로 `read_line`과 `read_exact`를 함께 처리하고, LIST·PEERS의 후속 n줄까지 같은 응답으로 읽음. DATA의 idx·본문 길이를 요청과 대조함. 알 수 없는 명령·잘못된 인자 개수는 `ERR BADCMD`로 응답하며 연결을 유지함.

| 방향 | 요청 | 응답 |
| --- | --- | --- |
| P→T | `HELLO id` | `OK` |
| P→T | `REGISTER id port file size chunk` | `OK` / `ERR MISMATCH` |
| P→T | `HAVE id port file` | `OK` / `ERR NOFILE` |
| P→T | `LIST` | `FILES n` + n줄 `file size chunk nchunks nholders` |
| P→T | `PEERS file` | `PEERS n` + n줄 `id host port` |
| P→T | `HEARTBEAT id have` | `OK` / `CMD DISCONNECT sec` / `CMD DESTROY` |
| P→T | `REPORT id file sent distinct bitmap` | `OK` |
| P→T | `DONE id FULL` / `DONE id PARTIAL file:lost …` | `OK` |
| P→T | `UNDONE id` / `BYE id` | `OK` |
| P→T | `STATE` | `STATE done alive WAIT` / `… ALLDONE` / `… ABORT reason` |
| P→P | `BITMAP file` | `BITMAP n bits` / `ERR NOFILE` |
| P→P | `GET file idx` | `DATA idx len\n` + len 바이트 / `ERR NOCHUNK` / `ERR NOFILE` |

PEERS는 연결에서 본 공인 IP가 아닌 env의 host를 반환함. 자기 id가 포함될 수 있으므로 Peer가 제외함. 부분 보유는 HAVE, 완성은 SHA-256 확인 후 REGISTER함. 프로토콜에 별도 push·정책 전달 명령을 추가하지 않음.

### Peer 시작 절차와 등록 재시도

1. 황대겸이 CLI·env·정책을 검증하고 Peer 로거를 열어 START를 첫 줄로 기록함. 황왕석의 FileStore가 원본의 존재·크기·전체 SHA-256을 검사함. 실패하면 exit 1이며 원본을 임의로 생성하거나 덮어쓰지 않음.
2. UploadServer를 자기 env host·port에 listen시킨 뒤 Tracker에 연결하여 HELLO·원본 REGISTER를 보냄. Tracker는 env 피어 모두의 첫 HELLO를 받은 순간 START를 한 번만 고정함.
3. LIST의 FILES 헤더와 n줄을 모두 읽고 **env의 모든 파일 이름이 보일 때까지 LIST를 반복**함. 개수만 같다고 통과하지 않고 size·chunk·nchunks도 env와 대조함. 먼저 참가한 Peer가 FILES 0이나 일부 파일만 보는 상황을 허용함.
4. 받을 파일마다 원본 크기의 0으로 초기화된 `.part`를 만들고 GET 이벤트를 기록한 뒤 HAVE를 보냄. **HAVE가 ERR NOFILE이면 등록 성공으로 처리하지 않고 LIST를 다시 확인한 뒤 HAVE를 재시도**함. 대기 중에는 stopping·ABORT·tracker_lost를 확인하고 busy loop를 피함. 일반 STATE·heartbeat 처리를 굶기지 않음.
5. HAVE 성공 뒤 PEERS→자기 id 제외→BITMAP을 수집하고 worker를 시작함. 원격 bitmap은 길이·0/1 형식을 검증함. 전체 원본 보유자만 기다리지 않고 부분 보유자도 소스로 사용함.
6. crash 복귀 시 기존 디스크·bitmap·통계를 유지한 채 listen→HELLO→모든 검증된 완성 파일 REGISTER·나머지 HAVE→PEERS/BITMAP 즉시 갱신을 수행함. LIST/HAVE 대기 규칙도 재사용하고 zero_since를 초기화함. 새 START를 기록하지 않고 REJOIN을 기록함.

상대가 늦게 등록하는 상황의 재시도는 명세상 참가 순서에 대응하는 처리이며, 고정 실행 순서나 임의의 긴 시작 sleep으로 대신하지 않음. 파일 완성 후 REGISTER 응답을 놓친 경우에도 등록 재시도를 수행함.

### 필수 로그 이벤트별 담당

기준은 과제명세 §9-3과 PPT p.182–185임. 모든 줄의 공통 필드는 `t`(프로그램 시작 후 초, 숫자), `peer`(P1–P4 또는 tracker), `ev`임. 아래 표의 명세 필수 필드는 반드시 기록하며 팀 추가 필드는 분석·대조를 위해 함께 고정함. 조건부 사건은 실제 발생할 때 기록함.

| 주체·이벤트 | 명세 필수 필드 | 팀 추가 필드 | 담당·기록 위치와 시점 |
| --- | --- | --- | --- |
| Tracker START_PROGRAM | `env` | `run`, `seed`, `description`, `port` | 안선효·tracker main. listen 성공 직후 로그 첫 줄 |
| Tracker START | `peers` | 없음 | 안선효·참가 처리. env 피어 모두 첫 HELLO, START 기준 고정 |
| Tracker CMD | `target`, `cmd` | DISCONNECT의 `sec`, DESTROY의 `progress` | 안선효·scheduler. 지시를 pending에 넣은 순간 |
| Tracker DEAD | `id` | `silent_sec` | 안선효·scheduler. last_seen이 dead_sec를 넘은 첫 판정 |
| Tracker ALLDONE | 없음 | `live`, `done` | 안선효·완료 판정. 참가 완료 후 live 전원 DONE일 때 한 번 |
| Tracker EXIT | `code` | `alldone`, `t_exit` | 안선효·tracker main. report 저장·handler/보조 스레드 정리 뒤 마지막 줄. 정상 0, ABORT 2 |
| Peer START | `env`, `policy`, `up_kbps`, `down_kbps` | `run`, `seed`, `description`, `rng_seed`, `tracker` | 황대겸·peer main. 유효 env·정책을 읽고 로거를 연 직후 첫 줄. C3도 실제 CLI 정책을 기록함 |
| Peer RECV | `file`, `idx`, `src` | 없음 | 황왕석·FileStore.commit(worker 호출). 디스크 쓰기와 bitmap=1 뒤, HASH 전에 한 번. 황대겸이 src를 전달함 |
| Peer CRASH | `sec` | 없음 | 황대겸·client. DISCONNECT를 받아 네트워크에서 사라지는 순간 |
| Peer REJOIN | 없음 | 없음 | 황대겸·client. HELLO·재등록·강제 갱신 후 복귀 |
| Peer DESTROY | 없음 | 없음 | 황대겸·client. DESTROY를 받고 결과를 저장하기 전 |
| Peer STALLED | `file`, `lost` | 없음 | 황대겸·control. 남은 청크 전부 rarity=0이 stall_sec 지속된 첫 전환 |
| Peer DONE | `kind` | `detail` | 황대겸·control. DONE의 OK를 받은 뒤. FULL은 빈 detail, PARTIAL은 file:유실수 또는 file:FAILED |
| Peer EXIT | `code` | `up_mb`, `down_mb` | 황대겸·peer main의 단일 종료 경로. 황왕석이 결과 저장·통계 반환을 맡음. 정상/비정상/희생 0/2/3, 로거 기동 후 설정 오류 1 |

### 추가 로그와 단일 종료 책임

| 주체·담당 | 이벤트와 고정 필드 |
| --- | --- |
| Tracker·안선효 | JOIN(`id,n,src_ip`), REGISTER(`id,file`), REJOIN/BACK/BYE(`id`), CMD_DELIVERED/CMD_DROPPED(`id,cmd`), REPLICATED(`file,t_start,upstat,progress`), ALL_REPLICATED(`t_start,p_rep`), DONE(`id,kind,detail`), UNDONE(`id`), ABORT(`reason,progress`) |
| Peer·황대겸 | GET(`file,chunks`), FAIL(`file,idx,src,err`), BAN(`target,sec`), COMPLETE(`file,sec,sources`), UNSTALLED(`file`), UNDONE(추가 필드 없음), ALLDONE(`done,alive`), ABORT(`reason,silent_sec`) |
| FileStore·황왕석 | HASH(`file,ok,sec`), CORRUPT(`file,action,tries`). action은 redownload 또는 give_up임. COMPLETE용 파일별 출처 통계도 제공함 |
| 각 main·실패 구성요소 | ERROR(`kind,operation,file,message`). local_io·contract·shutdown 실패를 기존 ABORT 사유와 구분하는 팀 추가 이벤트임 |

황대겸이 생성한 Peer emit 하나를 FileStore·UploadServer에 주입하고, 저장소·업로드가 별도 로그나 EXIT를 쓰지 않음. 업로드 청크별 SEND 이벤트는 만들지 않음. 한 줄 UTF-8 JSON 객체·즉시 flush·숫자/불리언 타입을 지키며 ASCII 막대·색 코드·사람용 문장은 파일에 넣지 않음. 대상 피어에 예약 필드 t·peer·ev를 재사용하지 않음. 사용하는 이벤트는 위 표와 AllDefinedLogs.txt를 함께 맞춤.

Peer 종료 담당은 황대겸 한 명임. 황왕석의 stop/finalize가 끝난 뒤 로그 생산 스레드·화면을 모두 정리하고, 필요한 BYE와 결과 통계를 확정한 다음 EXIT 한 줄을 flush·close함. destroy도 DESTROY→저장→EXIT code=3을 남기고 BYE를 보내지 않음. Tracker는 ALLDONE 뒤 모든 env 피어가 BYE 또는 DEAD가 된 경우 report→EXIT 0, ABORT 뒤에는 최대 15초간 퇴장을 기다리고 report→EXIT 2임. EXIT 뒤 이벤트·콜백을 허용하지 않음.

### 스레드·Lock 설계

| 프로그램 | 스레드 | 역할 |
| --- | --- | --- |
| Tracker | main 1, 연결당 handler, scheduler 1, observer 1 | 접속·요청 처리, 생존·지시·종료 판정, 복제 관측 |
| Peer | main 1, listener 1, 연결당 upload handler, env만큼 worker, control 1, screen 1 | 기동·종료, 업로드·다운로드, 주기 제어, 화면 출력 |

| 공유 자료 | 보호 방식 |
| --- | --- |
| Tracker 명단·last_seen·have·DONE·BYE·pending·REPORT·관측 시각 | Tracker 상태 Lock 1개. 스냅샷 후 송신·로그·report 저장 |
| 파일별 bitmap·have·in_progress·상태·완성 처리권 | 파일별 Lock. 마지막 청크 검증은 한 worker만 수행함 |
| 보유자·원격 bitmap 캐시·rarity | remote_lock |
| 상대별 inflight·연속 실패·BAN·선택 난수 | sel_lock |
| UP·DOWN 예약 시각 | 제한기별 Lock. 예약만 보호하며 대기는 밖에서 수행함 |
| Tracker 연결과 요청·응답 전체 | 연결 전용 직렬화 Lock. LIST·PEERS의 후속 줄까지 한 요청으로 보호함 |
| JSONL·최근 이벤트 / 화면 출력 | 로거·화면 전용 Lock. 상태 Lock을 놓은 뒤 호출함 |

일반 상태 Lock을 잡은 채 네트워크·파일 I/O·sleep을 하지 않음. 연결 전용 직렬화 Lock과 로그 전용 Lock은 명세의 요청·응답 혼선 방지 및 한 줄 기록 규칙에 따른 별도 용도임. 상태 Lock과 중첩하지 않음. 여러 상태 Lock이 필요하면 파일 → remote → sel 순서를 지키고, 가능하면 각각 스냅샷을 얻어 중첩을 피함. Condition 대기는 Lock을 놓는 wait를 사용함.

control이 다른 Peer의 느린 BITMAP 요청을 순서대로 기다리다 heartbeat·STATE·REPORT를 밀리지 않게 해야 함. 갱신 요청에는 전체 시간 예산을 두고, 불응 상대는 즉시 캐시에서 제외하는 설계임. worker는 자기 상대별 연결을 재사용함.

### 주기 제어와 화면

| 담당 | 작업·기준 주기 | 필수 처리 |
| --- | --- | --- |
| 안선효 | scheduler 0.5초·observer 1초 | START 이후 장애·생존·완료·watchdog를 검사함. observer는 네트워크 I/O 없이 REPORT 스냅샷으로 관찰함 |
| 황대겸 | HEARTBEAT=`heartbeat_sec` | 원본을 제외한 총 have 보고·CMD 수신. Peer끼리 heartbeat를 만들지 않음 |
| 황대겸 | REPORT·STATE·STALLED 검사 1초 | 모든 파일의 bitmap·sent·distinct 보고, 종료 상태 확인. **REPORT·BITMAP 등 제어 메시지는 UP/DOWN 데이터 제한기에 넣지 않음** |
| 황대겸 | PEERS=`peers_refresh_sec`, BITMAP=`bitmap_refresh_sec` | 받는 파일의 캐시만 갱신함. 실패·NOCHUNK·목록 제외 시 제거하고 BAN 상대와 자기는 rarity에서 제외함. 완성 파일은 원격 캐시 갱신을 중단함 |
| 황왕석 | 화면=`status_every_sec` | ONLINE/CRASHED·정책·경과 시간·업/다운 실측/한도, 파일별 진행률·보유/전체 청크·DOWN/SEED/STALLED/FAILED 표시 |

화면은 파일마다 **40칸 ASCII 막대**를 사용함. `#`는 해당 구간 전부 보유, `+`는 일부 보유, `.`은 미보유, `x`는 STALLED 파일의 유실 구간임. 위쪽 상태판은 제자리 갱신, 아래쪽 최근 이벤트는 흐르도록 하고 stdout이 터미널이 아니면 상태판을 끔. 출력은 screen 또는 전용 Lock 하나로 직렬화함. 화면 규격은 과제명세 p.14·구현명세 p.10을 따름.

### 파일·선택·장애 처리

- 선택과 `in_progress` 예약은 같은 임계 구역에서 수행함. 수신·길이 확인·위치 지정 쓰기가 끝난 뒤 bitmap=1로 바꾸며, 실패 시 finally에서 예약·inflight를 해제함. 마지막 청크의 부분 쓰기·읽기도 반복 처리함.
- random은 시작 때 전체 `(file, idx)` 순서를 한 번 섞음. rarest는 받을 수 있는 전체 후보 중 rarity 최소, 동점 무작위임. 난수 seed는 `policy_seed + 피어 번호`, CLI 정책이 env보다 우선함.
- 소스는 보유 bitmap=1, BAN 아님, inflight가 `per_peer_max` 미만인 상대 중 가장 한가한 곳을 고르며 동점은 무작위임. 연속 실패는 env 기준으로 BAN하고 성공 시 초기화함. NOCHUNK·BITMAP 실패·PEERS 제외 시 낡은 캐시를 버림.
- 원본은 시작 시 전체 SHA-256, 수신 파일은 완성 시 전체 SHA-256을 1 MiB 단위로 계산함. 일치하면 HASH→rename→REGISTER OK→COMPLETE, 불일치하면 CORRUPT 후 재수신, 2회 연속 실패 시 `.corrupt`·FAILED임.
- crash는 listener·연결을 닫고 네트워크 송신을 멈추며 디스크·bitmap을 보존함. 복귀 시 HELLO·REGISTER/HAVE와 PEERS·BITMAP 갱신을 다시 수행하고 STALLED 계시를 초기화함. 자체 crash로 버린 DATA를 상대의 실패로 세지 않음.
- 파일의 미보유 청크 **전부**가 rarity=0인 상태로 `stall_sec` 지속될 때만 STALLED임. 다시 소스가 생기면 UNSTALLED·UNDONE으로 복귀함. 모든 파일이 SEED·STALLED·FAILED이면 DONE을 보내되 업로드는 계속함.
- 일반 종료는 ALLDONE 확인 → 새 연결 중단·업로드 유예 → worker·control 정리 → bitmap·lost·incomplete 저장 → BYE → EXIT 0임. ABORT·tracker_lost는 동일 정리 후 EXIT 2, destroy는 BYE 없이 DESTROY→저장→EXIT 3임.
- 종료·crash와 수신 완료의 경쟁을 검사함. 이전 연결의 DATA가 복귀 후 새 작업으로 반영되거나, 열린 파일을 닫는 중 handler가 읽는 상황을 막음. 모든 네트워크·Condition·join 대기는 종료 신호를 확인할 수 있어야 함.

DOWN.take는 응답을 받은 뒤가 아니라 **GET 전에**, UP.take는 **DATA 헤더·본문 송신 전에** 실제 청크 길이로 예약함. REPORT의 sent는 전체 DATA 송신을 마친 청크 횟수, distinct는 서로 다른 idx 수이며 파일별로 유지함. crash 자체로 취소한 요청·per_peer_max 때문에 아직 선택하지 못한 요청·제한기 대기를 상대 FAIL로 세지 않음.

마지막 청크는 RECV→HASH→검증 성공·rename→REGISTER OK→COMPLETE 순서로 기록함. 해시 불일치 시 bitmap·have·예약·출처를 해당 파일 세대에 맞게 초기화하여 처음부터 다시 받고, FAILED 파일의 DONE detail은 `file:FAILED`임. 남은 청크가 없더라도 해시 검증 중인 파일을 SEED·DONE으로 먼저 보고하지 않음. 정상 완성 파일의 등록 재시도가 남아 있으면 DONE을 보류함. Windows rename 시 잠깐 읽기를 막고 진행 중 I/O를 마친 뒤 매핑·핸들을 닫아 이름을 바꾸고 필요 핸들을 다시 엶.

가상 crash 시간은 tracker_lost 무응답 계시에서 제외하며, 시작부터 Tracker에 닿지 않는 경우와 실행 중 Tracker가 먼저 사라진 경우를 모두 검사함. crash 중 화면·로컬 로그는 유지하되 네트워크 송신은 없음. 정상 종료·ABORT·destroy·개발용 Ctrl+C/SIGTERM은 main의 단일 정리 경로로 모으며, 개발용 시그널 종료 코드만 과제 고정값 적용 대상에서 제외함.

### Tracker 관찰과 결과

네 피어가 모두 HELLO한 순간 START를 고정함. 이후 어떤 유효 메시지든 last_seen을 갱신하며, 침묵이 dead_sec를 넘으면 DEAD, 다시 참가하면 BACK으로 처리함. 종료한 BYE 피어는 PEERS에서 제외함. ALLDONE은 참가 완료 후 live가 비어 있지 않고 live 전원 DONE일 때 선언하며 이후 늦은 지시는 버림.

observer는 live이며 `report_stale_sec` 이내 REPORT만 사용함. 파일의 origin을 제외한 bitmap OR가 처음 모두 1이면 T_rep를 저장하고 당시 원본의 sent·distinct를 고정함. 모든 파일 복제가 끝나면 p_rep를 저장함. `dup_ratio=(sent−distinct)/sent`이며 관측하지 못한 값은 null로 남김. sent=0의 나눗셈을 피함.

replica_safe는 희생자가 가진 **모든 파일의 모든 1 청크**가 다른 fresh live Peer의 OR에 있는지 검사함. 희생자의 REPORT가 없거나 오래되면 파괴를 미룸. `T_destroy`는 pending에 파괴 지시를 넣은 시각이며 실제 전달은 CMD_DELIVERED로 구분함. report에는 `env, run, seed, policy, destroy_plan, crashes_sent, T_rep, p_rep, upstat_at_rep, dup_ratio, T_destroy, p_destroy, T_dead, T_done, T_last_done, T_alldone, T_exit, done_kind, peers, abort`를 배포 예시 순서로 기록함.

report 시각은 START 기준, JSONL `t`는 각 프로세스 시작 기준임. 두 시계를 그대로 비교하지 않음. C3의 env 정책은 null이며 배포 report 예시도 이를 허용함. 실제 실행 정책은 각 Peer START와 결과 폴더명으로 확인하고, 4개 Peer가 같은 정책인지 대조함.

report는 UTF-8 객체 하나·들여쓰기 2칸·시각 소수 둘째자리로 저장함. 발생하지 않은 시각·값은 null, 대상이 없는 목록·객체는 빈 값으로 둠. 파괴한 피어의 마지막 have도 진행률의 누적 합에 보존함. 모두 DONE인 정상 마무리를 hang으로 오판하지 않으며, START 이전에는 START 기준 장애·hang·deadline을 진행하지 않음. FILES의 nholders는 REGISTER/HAVE 보유자 수이고 PEERS는 그중 live·BYE 아님만 반환함.

## 독립 개발과 통합 순서

### 조원별 작업 시작

조원은 이 README에서 자기 이름의 소유 경로·공개 계약·통과 기준을 읽고 기존 작업 폴더에서 해당 브랜치 작업을 시작함. 공통 contracts를 먼저 import하며 이름·필드·반환형·예외 클래스를 다시 만들지 않음. Protocol 상속은 필수가 아니지만 메서드 서명과 실제 반환 객체는 반드시 같아야 함. import 단계에서 소켓·파일·스레드를 시작하지 않고 main 또는 명시적 initialize/start에서만 시작함.

각 담당의 첫 검사는 다음과 같음. 아래 명령은 해당 테스트를 구현한 뒤 실행하며 현재 테스트가 존재한다는 뜻은 아님. 대역 테스트는 실제 클래스를 같은 API로 교체할 수 있도록 구성함.

| 담당 | 첫 구현·검사 | 독립 검사 명령 |
| --- | --- | --- |
| 안선효 | common Conn·공유 입력 → Tracker, contracts와 서명 일치 | `python -m unittest discover -s tests/common -v`, `python -m unittest discover -s tests/tracker -v` |
| 황대겸 | EventLog·CLI → 대역 StorePort/UploadPort → control·worker | `python -m unittest discover -s tests/peer -v` |
| 황왕석 | FileStore와 공개 반환형 → UploadServer → StatusScreen·도구 | `python -m unittest discover -s tests/storage -v`, `python -m unittest discover -s tests/upload -v`, `python -m unittest discover -s tests/tools -v` |

최종 인계는 자기 소유 소스·필요한 lib·테스트·실제 사용한 이벤트 정의·실행한 검사 명령과 결과로 구성함. 테스트 0건·필수 skip·대역 검사만으로 실제 통합 통과를 보고하지 않음. 새 의존성·포트·공통 객체의 필드를 임의로 추가하지 않음. 공개 계약을 바꿔야 하면 contracts·README·호출부·대역·검사를 같은 변경으로 맞춤.

### 통합자의 결합 순서

1. 세 담당이 TCP·CLI·FileStore/UploadServer 계약을 기준으로 자기 대역과 소규모 데이터를 준비함. Tracker는 대역 Peer, Peer는 대역 Tracker·FileStore·UploadServer, storage/upload는 대역 다운로드 클라이언트를 사용하여 상대 코드 없이 검증함.
2. 황대겸·황왕석이 실제 FileStore/UploadServer를 Peer 진입점에 조립하고 단일 소스→다중 소스→8 worker를 확인함. 안선효는 동시에 Tracker의 관찰·지시·종료를 독립 검사함.
3. 안선효가 실제 Tracker 1개와 Peer 4개를 독립 프로세스로 연결함. 로컬 DEV에서 해시·부분 재공유·속도·crash·종료·공식 verify를 확인한 뒤 A·B·C1·C2·C3의 조건을 검사함.
4. VM Tracker DEV를 통과한 뒤 제출 7회를 하나씩 실행함. 황왕석의 도구로 로그·report를 취합하고 원래 데이터가 있는 실행 폴더에서 공식 verify를 수행한 다음 결과 기록을 보관함. 각 담당이 자기 로그·오류를 대조하고 안선효가 통합 정합성과 실측 분석을 확정함.

시나리오는 동시에 돌리지 않음. 대역 테스트 통과와 실제 통합·원격 실행 통과를 구분함. C3 추가 2–3회는 권장 분석이며 필수 7회와 구분함.

### crash·복귀·최종 종료 호출 순서

| 상황·조율 담당 | 고정 순서와 하위 구성요소 책임 |
| --- | --- |
| 최초 기동·황대겸 | EventLog → START → FileStore.initialize → UploadServer.start → HELLO·REGISTER/LIST/HAVE → 화면·control·worker. StorePort/UploadPort를 main에서 한 번씩 생성함 |
| crash 진입·황대겸 | Peer의 online을 false로 바꿔 신규 요청 차단 → FileStore.pause로 예약/commit 무효화 → UploadServer.offline과 다운로드/Tracker 연결 닫기 → CRASH. stopping Event는 set하지 않음. 닫힌 연결의 송신 오류는 자체 취소로 분류함 |
| crash 복귀·황대겸 | 지시된 침묵 시간 경과 → FileStore.resume → UploadServer.online → HELLO·완성 파일 REGISTER·HAVE 재등록 → 즉시 캐시 갱신 → zero_since 초기화 → online·REJOIN. 복귀 절차 자체의 등록 통신은 허용하되 worker·평상시 control은 준비 완료 전 요청을 보내지 않음 |
| 정상·ABORT·황대겸 | 새 다운로드 예약 차단·stopping.set → UploadServer.stop(3.0)로 진행 업로드 마무리/강제 종료 → worker·control join → FileStore.finalize → 필요한 BYE → StatusScreen.stop → EXIT → EventLog.close. 업로드 유예가 끝나기 전 FileStore.pause/finalize로 읽기 핸들을 닫지 않음 |
| destroy·황대겸 | online=false → DESTROY → stopping.set → UploadServer.stop(0.0)·다운로드/Tracker 연결 닫기 → worker·control join → FileStore.finalize → 화면 stop → EXIT 3·close. BYE·재참가 없음 |

control이나 handler가 자신을 join하거나 finalize를 직접 호출하지 않음. 상태 전환 요청만 main에 전달하고 main이 단일 정리 절차를 수행함. 정상 종료를 위해 이미 진행 중인 업로드가 stopping만 보고 즉시 버려지지 않게 하되 새 GET은 받지 않음. uploader stop은 파일 읽기 사용자가 모두 끝났음을 보장해야 함. 종료 대기 실패·저장 실패가 있으면 정상 PASS로 마감하지 않으며 ERROR와 비정상 종료를 남김.

### 통합 인수 검사

안선효가 `tests/integration/test_interfaces.py`에 아래 실제 클래스 검사를 구현하고 `python -m unittest discover -s tests/integration -v`로 실행함. 생성자/메서드 서명 검사에서 그치지 않고 반환 객체·로그·파일·상태 전이를 함께 확인함. 개인 구현의 내부 fd/Lock/자료구조에 의존하지 않음.

| 검사 | 공통 입력·기대 결과 |
| --- | --- |
| 생성·import·의존 | 세 실제 클래스가 고정 keyword 인자로 생성됨. import/생성자에서 불필요한 bind·스레드·파일 초기화 없음. 공통 dataclass·예외 객체를 그대로 사용함 |
| snapshot·부분 재공유 | 원본 없는 P4, 파일 내용 `b"abcdefghijk"`, size=11·chunk=8·원본 P1·SHA-256은 이 바이트에서 계산한 env 사용. prepare 뒤 idx0의 8 B commit → bitmap="10", downloaded_have=1, received_bytes=8. read_chunk(0)는 같은 8 B, idx1은 NoChunkError임 |
| 예약·정확한 마지막 청크 | idx0 이중 reserve의 두 번째는 None. idx1의 `b"ijk"` 3 B commit → bitmap="11"·SEED·downloaded_have=2·received_bytes=11, complete_now는 한 번. read_chunk(1)는 정확히 3 B임 |
| 반복·기동/종료 | initialize·prepare 재호출이 기존 내용을 지우지 않음. release 두 번·close/stop 두 번이 안전함. finalize 뒤 bitmap 파일은 11이며 LF 없음, lost 없음. 같은 마지막 StoreSnapshot 재조회 가능함 |
| 세대·가상 오프라인 | 첫 청크 보유 후 남은 청크 예약 → pause → 이전 토큰 commit은 STALE·RECV 없음·bitmap 불변. 반복 pause는 세대 유지, read는 OfflineError. resume 뒤 새 토큰으로 이어받음 |
| 해시 재시도·예외 | 크기는 같고 해시가 다른 11 B를 한 번 받으면 HASH false·CORRUPT redownload·bitmap 초기화, 두 번째 연속 실패는 FAILED·.corrupt임. 잘못된 idx는 InvalidChunkError, 알 수 없는 파일은 NoFileError임 |
| 업로드·프로토콜 | 실제 UploadServer를 ephemeral 시험 포트와 공통 Conn으로 연결하여 BITMAP/GET·NOFILE/NOCHUNK/BADCMD·3 B DATA를 확인함. 누적 sent/distinct는 전체 송신 성공 뒤만 증가하고 SEND 로그는 없음. offline 중 응답 없음·online 재접속 가능함 |
| 저장소·화면·종료 경계 | finalize 전에 읽기/쓰기 사용자가 모두 종료됨. snapshot만 받는 StatusScreen이 VERIFYING을 DOWN으로 표시함. 파일 미보유 영역·lost 범위·예외 전달·EXIT 마지막 줄과 종료 후 남은 스레드 0을 확인함 |

위 11 B 입력은 대역/계약 검사 전용 임시 env임. 공개 env를 수정하지 않음. 실제 DEV·원격 7회 결과를 대신하지 않음. 서로 다른 패키지의 타입 변환용 임시 어댑터를 통합자가 추가하는 대신, 계약을 어긴 제공자 구현을 해당 담당 경로에서 수정해 재검사함.

### 실행 방법 — 구현 후 적용할 계약

아래는 **예정 명령**이며 현재 구현이 없어 실행할 수 없음. `HW6/`에서 실행하며 `KIT`는 각 실행 환경의 `hw6_student_kit/Python` 실제 경로, `TRACKER_IP`는 실제 주소로 바꿈. 양쪽은 같은 원본 env를 사용함. Windows는 `python`, Linux·WSL은 `python3`를 사용함.

```text
python "KIT/lib/env_example.py" --env "KIT/envs/B.json" --id P3
python "KIT/lib/env_example.py" --env "KIT/envs/C3.json" --id P1 --policy rarest
python "KIT/tools/reset_dirs.py" --env "KIT/envs/DEV.json"

# Tracker: 외부 VM에서 먼저 실행. 로컬 개발일 때만 PC에서 실행
python -m src.tracker --env "KIT/envs/DEV.json"
# 다른 Tracker 포트가 필요하면 env를 고치지 않고 마지막에 지정
python -m src.tracker --env "KIT/envs/DEV.json" 6100

# Peer: 각각 별도 터미널·프로세스, TRACKER_IP를 실제 주소로 변경
python -m src.peer --env "KIT/envs/DEV.json" --id P1 TRACKER_IP 6000
python -m src.peer --env "KIT/envs/DEV.json" --id P2 TRACKER_IP 6000
python -m src.peer --env "KIT/envs/DEV.json" --id P3 TRACKER_IP 6000
python -m src.peer --env "KIT/envs/DEV.json" --id P4 TRACKER_IP 6000

# C3: 네 Peer 모두 동일 정책. 다음 정책 전에는 결과 보관 후 초기화
python -m src.peer --env "KIT/envs/C3.json" --id P1 --policy random TRACKER_IP 6000
python -m src.peer --env "KIT/envs/C3.json" --id P1 --policy rarest TRACKER_IP 6000

# 종료 후 VM의 logs/tracker.jsonl과 report.json을 로컬로 복사한 다음 검사
python "KIT/tools/verify.py" --env "KIT/envs/DEV.json"
```

Peer는 기본 포트여도 IP·PORT를 모두 받음. Tracker를 6100으로 띄웠다면 네 Peer와 VM 방화벽도 같은 포트로 맞춤. VM 방화벽은 로컬 공인 IP에서 오는 Tracker 포트만 허용함. 과제의 실행 조건이며 현재 VM 설정을 변경한 것은 아님.

### 키트 사용 시 주의점

- `reset_dirs.py`는 현재 작업 폴더 기준 p1–p4·logs·report를 삭제함. 이전 결과를 `runs/<Run>/`에 보관한 뒤 실행함. 제출 기록만 보관한 폴더에서는 큰 데이터가 없어 공식 verify를 다시 돌릴 수 없음. verify는 원래 데이터가 남은 실행 폴더에서 먼저 수행함.
- 초기화 도구는 data의 파일 크기가 같으면 원본을 재생성하지 않음. 잘못된 동일 크기 데이터는 Peer 시작 시 env 해시 검사로 거부해야 함.
- 배포 `run_dev.sh`는 루트 tracker.py·peer.py를 가정하는 로컬 DEV 예시이며 6000번 포트를 사용함. 팀 패키지 진입점과 다르고 정책 인자도 전달하지 않으므로 그대로 사용하지 않음. 실행 도구는 `python -m src.peer`를 사용함.
- `argparse` 기본 사용법 오류는 exit 2이지만 과제의 인자 오류는 exit 1임. 진입점에서 맞춰야 함.
- 키트 로거는 append 방식이므로 실행 전 초기화가 필요함. 경과 시간·timeout·속도 예약은 단조 시계를 사용하는 안이며, 사용한 로거의 시계 기준도 실제 코드·로그 사전에 맞춤.
- 공식 verify는 종료 코드·데이터·수렴·손실·JSON 파싱을 검사함. 속도·화면·report 스키마·희생자의 모든 bitmap·lost 범위·마지막 줄 EXIT·C3 정책 일치까지 PASS로 보장하지 않으므로 별도 대조함.

## 분석과 최종 제출

실측표에는 Run별 T_alldone·T_done, Peer별 평균 송수신 속도와 한도 대비 비율, 출처 분포와 P4 재공유량, CRASH·FAIL·BAN 수, T_rep·p_rep·dup_ratio, 파괴·DEAD·마지막 DONE, C2 커버리지·손실 수를 기록함. 현재는 측정값이 없으므로 참고 구현의 숫자를 결과로 넣지 않음.

속도는 명세의 첫 RECV부터 마지막 RECV 구간 평균과 실행 전체 평균의 측정 구간을 구분함. 실제 청크 길이로 바이트를 합산하고, 상대 Peer 로그를 합쳐 업로드를 추정할 때는 프로세스별 시계 차이를 명시함. C3에서는 로그를 Tracker START 기준으로 정렬한 뒤 실제 파괴 시점까지 출처를 셈. rarest가 복제를 앞당겨도 전체 완료가 늦을 수 있는 원인을 원본 쏠림·재공유·서로 다른 실제 파괴 시각으로 분석함. 동점 무작위 외의 정책 개선은 필수 random·rarest 실행과 구분함.

report 시각 순서, 실제 전달된 crash 수, 파괴 대상의 DEAD, RECV 수와 최종 bitmap의 관계, 속도 준수를 대조함. 정상·무손실 본 실행의 전체 수신 청크 수는 2,880이며 DEV는 720임. C2 유실 수를 예제의 99개로 고정하지 않음.

```text
G2HW6.zip                    ZIP 생성은 요청 시 수행
├── src/                     실제 Tracker·Peer·필요 lib·실행 스크립트
├── runs/
│   ├── DEV/                 아래와 동일한 구성
│   ├── A/
│   ├── B/
│   ├── C1/
│   ├── C2/
│   │   ├── logs/            P1.jsonl–P4.jsonl, tracker.jsonl
│   │   ├── report.json
│   │   ├── verify.txt       실제 RESULT: PASS 출력
│   │   └── p1/–p4/          모든 파일의 .bitmap, 미완성 파일의 .lost
│   ├── C3_random/
│   └── C3_rarest/
├── AllDefinedLogs.txt
├── Readme.txt
└── download.txt
```

bitmap은 희생자·원본·완성 파일도 필수이며 청크 수만큼의 0/1 문자열, 줄바꿈 없음임. lost는 미보유 번호를 오름차순·쉼표·연속 구간 a-b로 기록하며 공백 없이 한 줄임. 완성 파일에는 lost를 만들지 않음. 미완성 `.part`는 종료 시 원본 크기의 `.incomplete`로 바꾸고 bitmap=0 구간은 0바이트로 정리하여 verify 전까지 보존함. 생존자 결과는 파일별로 bitmap=OR와 같아야 함. 완성 데이터·incomplete·data·키·임시 파일은 제출 기록에 넣지 않음.

Readme.txt는 조원 이름·학번·역할, 실제 언어·설치·실행, VM 종류·리전·포트, Thread·Lock 대응, 속도·선택·장애·STALLED 설계, 실측표·분석·정합성·한계·느낀 점을 포함함. AllDefinedLogs.txt에는 실제 사용한 모든 이벤트·필드·단위·기록 시점을 정의함. JSONL은 각 이벤트마다 flush하고 마지막 줄을 EXIT로 유지함. 시연은 공지 기준에 따라 DEV 또는 A의 ASCII·crash/rejoin, C2의 STALLED→ALLDONE, verify PASS를 포함하며 링크의 비로그인 접근·재생을 확인함. 별도 분석 보고서는 만들지 않음.

공식 분석 질문의 답에는 각 Peer의 한도 대비 평균·미달 원인, P4 재공유량과 부분 재공유가 없다면 걸릴 시간의 추정 근거, C2 원본 송출량·파괴 시각과 손실 수의 관계, C3 복제/중복 이득과 전체 완료의 관계, 같은 청크 쏠림을 줄이는 선택 개선을 포함함. 추정과 실측을 구분함. 제출 src에는 `src/common/transport.py`까지 필요한 모든 패키지·사용한 키트 lib·실행 보조를 포함하며, 제출물의 바깥 src를 작업 디렉터리로 하여 같은 `python -m src.tracker/peer` 구조가 유지되도록 구성함. 요청 시 만드는 최종 ZIP은 새 폴더에 풀어 실행 방법·파일 구성을 확인함.

## 구현 전 명세 재검증

아래는 배포 명세와 이 README의 **문서 대조 범위**임. 설계에 반영한 사실을 나타내며 구현·테스트 PASS나 제출 실행 완료를 뜻하지 않음.

| 대조 항목 | 원문 기준 | README 반영 위치·검증 담당 |
| --- | --- | --- |
| TCP·배포·프로세스·허용 코드 | 과제명세 §1·§4·§9-1, 구현명세 §1 | 필수 요구사항·패키지, 안선효 |
| env 전 필드·CLI 우선순위·exit 1 | 과제명세 §3, 구현명세 §3–6 | env·CLI 읽기와 오류·공개 설정, 안선효/황대겸 |
| 참가 경쟁·LIST 대기·HAVE 재시도·재참가 | 과제명세 §4-5·§5, PPT p.82–83 | Peer 시작 절차와 등록 재시도, 황대겸 |
| 줄/본문 경계·n줄 응답·짧은 청크·에러 | 과제명세 §5③, 구현명세 §7 | 공통 TCP 수신 버퍼·TCP 계약, 안선효 및 각 소비 담당 |
| 스레드·Lock·부분 재공유·파일 검증 | 과제명세 §2·§4·§5, 구현명세 §8–9 | 내부 패키지·스레드·파일 계약, 황대겸/황왕석 |
| 데이터 제한기·선택·BAN·주기 갱신 | 과제명세 §5④–⑥·§6-2, Q&A Q9–Q14 | 주기 제어·파일/선택/장애, 황대겸/황왕석 |
| crash·destroy·DEAD·STALLED·UNDONE·종료 | 과제명세 §6, 구현명세 §9–10·§12 | 단일 종료 책임·장애·Tracker 결과, 세 담당 |
| T_rep·fresh REPORT·safe·report·두 시계 | 과제명세 §7·§9-4, 구현명세 §10, PPT p.205 | Tracker 관찰과 결과, 안선효 |
| 필수 이벤트·필드·소유자·EXIT 마지막 | 과제명세 §9-3, 구현명세 §11, PPT p.182–185·194 | 필수/추가 로그 표·단일 종료 책임, 세 담당 |
| 40칸 막대·상태·터미널 출력 | 과제명세 §5⑦, 구현명세 §11 | 주기 제어와 화면, 황왕석 |
| 제출 7회·bitmap/lost·검사·분석·시연 | 과제명세 §8·§9-2·§9-4–6, 구현명세 §13, PPT p.234–235 | 독립/통합 순서·분석과 최종 제출, 세 담당 |

대조한 원문 범위에서 추가 미반영 필수 항목은 발견하지 못함. 공유 자료형·예외·Protocol 파일은 제공됨. 공통 Conn·공유 검사 입력·Tracker·Peer·저장소·업로드·검사 코드는 아직 구현 전이며, 구현 후 담당별 실제 검사와 VM Tracker 7회 검증이 남아 있음.
