# HW6 Mini-Torrent

데이터통신 2조 개발 기준임. **안선효 40% · 황대겸 30% · 황왕석 30%**의 분업을 기준으로 패키지·인터페이스·독립 검증 범위를 정함. Tracker·Peer는 구현 전이며 아래 파일 구성과 명령은 구현 계약임. 실제 통합·원격 실행 결과와 성능 수치는 아직 없음.

공식 기준은 `HW6description.pdf`와 `HW6studentSpec.pdf`임. `HW6explanation.pdf`·`HW6QnA.pdf`는 세부 해설, `hw6_student_kit/Python/`은 원본 env·검증 도구·허용 lib의 기준으로 사용함. 위치 지정 파일 I/O는 `pwriteExplanation/`의 가이드와 예제를 참고함. 배포 원본은 로컬에 보존함.

외부 VM·TCP·동시 업로드/다운로드·env·장애·필수 7회·제출 형식은 과제 요구사항임. 아래 4:3:3 분업, Python 선택, 패키지·함수·브랜치 이름, 내부 호출 경계는 팀 설계임. 비율은 구현·검증·통합 부담을 나누는 기준이며 코드 줄 수나 과제 채점 비율이 아님.

## 담당별 작업과 완료 기준

| 담당·비율 | 소유 경로 | 작업 브랜치 기준 | 구현·검증 범위 |
| --- | --- | --- | --- |
| 안선효 40% | `src/tracker/`, `tests/tracker/`, `tests/integration/`, 개발·제출 문서 | `hw6/tracker` | Tracker 전체, 명단·생존·지시·관찰·report, 실제 통합·VM 배포·7회 정합성·실측 분석·최종 취합 |
| 황대겸 30% | `src/peer/`, `tests/peer/` | `hw6/peer` | Peer 진입점·Tracker 연결·control, worker pool·청크/소스 선택·제한·재시도, crash/rejoin·STALLED·DONE·종료 조율 |
| 황왕석 30% | `src/storage/`, `src/upload/`, `tools/`, `tests/storage/`, `tests/upload/`, `tests/tools/` | `hw6/storage-upload` | 파일·bitmap·해시·결과 저장, 업로드 서버·공유 UP 제한기, 화면, 실행·결과 보관·추가 검사 도구·시연 자료 |

소유 경로는 저장소 `HW6/` 기준임. 브랜치 이름은 작업 기준이며 현재 브랜치를 만들었다는 뜻은 아님. 기존 체크아웃과 사용자 변경을 보존하며 새 워크트리를 만들지 않음. 상대 담당의 내부 파일을 직접 수정하지 않고 아래 공개 인터페이스와 대역으로 독립 구현함. 각 담당이 자기 코드의 테스트와 로그 정의를 작성하고 안선효가 최종 문서·결과를 합침.

### 안선효: Tracker·통합 40%

1. env 검증 → TCP 명령 → 참가·명단·생존 → scheduler·지시 → observer·report → ALLDONE·ABORT·종료 순서로 구현함. Tracker 내부 송수신·설정·로그 코드는 자기 패키지에서 관리함.
2. 대역 Peer 4개로 REGISTER/HAVE·LIST/PEERS·heartbeat·재참가·DONE/UNDONE·BYE를 확인함. 분할/합친 수신, 낡은 REPORT, 세 파괴 조건, replica_safe, DEAD·hang·deadline도 검사함.
3. origin을 뺀 fresh live bitmap OR와 T_rep·p_rep·dup_ratio, 지시 등록/전달 시각, report 키·시각 기준·종료 코드가 맞으면 독립 구현 완료임.
4. 실제 Peer 통합, 로컬 DEV와 VM Tracker DEV, 제출 7회, 데이터·속도·로그·report 정합성과 C3 분석, 제출 Readme·로그 사전 취합을 맡음. 원격 자원 종류·리전·주소는 실제 배포 시 기록함.

### 황대겸: Peer 제어·다운로드 30%

1. CLI·TrackerLink → 가짜 FileStore/UploadServer 연결 → worker·random/rarest·소스 선택 → 주기 갱신·REPORT → 장애·DONE·종료 순서로 구현함.
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

현재는 README와 Git 제외 설정만 있으며 아래 소스는 구현 전임. 실행 디렉터리는 `HW6/`, `src/`와 그 하위 폴더는 초기화 로직 없는 Python 네임스페이스 패키지로 구성함. 담당 내부의 파일 분리는 조정할 수 있으나 소유 경로와 공개 계약은 유지함.

```text
HW6/
├── README.md
├── .gitignore
├── src/
│   ├── tracker/                 안선효 40%
│   │   ├── __main__.py          CLI·기동·종료
│   │   ├── server.py            요청 처리·명단·공유 상태
│   │   ├── scheduler.py         생존·가상 장애·완료·ABORT
│   │   ├── observer.py          REPORT·복제·replica_safe
│   │   ├── report.py            지표 고정·report 저장
│   │   ├── config.py            Tracker env 검증
│   │   ├── transport.py         Tracker TCP 버퍼
│   │   └── log.py               Tracker JSONL
│   ├── peer/                    황대겸 30%
│   │   ├── __main__.py          CLI·구성요소 조립
│   │   ├── client.py            시작·가상 장애·종료 조율
│   │   ├── tracker_link.py      요청·응답 직렬화·재연결
│   │   ├── control.py           주기 갱신·REPORT·STALLED·DONE
│   │   ├── download.py          worker·GET·재시도·DOWN 제한
│   │   ├── selection.py         원격 캐시·rarity·선택·BAN
│   │   ├── config.py            Peer env·CLI 검증
│   │   ├── transport.py         Peer TCP 버퍼
│   │   └── log.py               Peer JSONL·공유 이벤트 발행
│   ├── storage/                 황왕석 30%
│   │   ├── store.py             FileStore·예약·bitmap·commit
│   │   ├── positional.py        pread/pwrite·Windows mmap
│   │   └── results.py           HASH·완성·bitmap/lost 저장
│   └── upload/                  황왕석 30%
│       ├── server.py            listener·연결당 handler
│       ├── transport.py         BITMAP/GET TCP 버퍼
│       ├── limiter.py           공유 UP 제한기
│       └── screen.py            상태판·최근 이벤트
├── tools/                       황왕석 30%
│   ├── launch_peers.py          Peer 4개 기동·종료 코드 수집
│   ├── collect_run.py           verify 후 기록만 Run별 보관
│   └── check_run.py             속도·report·bitmap/lost 추가 검사
└── tests/
    ├── tracker/                 안선효
    ├── integration/             안선효
    ├── peer/                    황대겸
    ├── storage/                 황왕석
    ├── upload/                  황왕석
    └── tools/                   황왕석
```

Tracker와 Peer는 `python -m src.tracker`, `python -m src.peer`로 실행함. 업로드·저장소는 Peer 프로세스 안에서 동작하며 별도 프로세스를 추가하지 않음. 공통 런타임 패키지는 만들지 않고 Tracker·Peer·업로드의 짧은 송수신 코드는 각각 소유함. 배포 lib를 활용할 때는 해당 담당 패키지 안에 필요한 파일과 출처·라이선스를 보존함. 실행에 필요한 원본 env·도구는 별도 키트 경로로 받음.

### Peer 내부 패키지 계약

Peer 진입점이 FileStore·UploadServer·화면을 생성하고 worker·control과 연결함. `src.peer`는 아래 공개 기능만 import하며, storage·upload는 `src.peer`나 Tracker 구현을 import하지 않음. 로그 발행 함수·종료 신호·설정·FileStore 객체는 생성 인자로 전달함. 대역 객체도 같은 계약을 사용함.

| 제공자 | 공개 기능·입출력 | 책임 경계 |
| --- | --- | --- |
| `src.storage.store.FileStore` | `snapshot()` → 파일별 메타정보·bitmap·상태·비원본 have·업로드 통계의 복사본 | 통계 단위는 바이트와 청크 수로 구분하며 snapshot 변경이 원본에 반영되지 않음 |
| FileStore | `reserve(file, idx)` → 예약 토큰 또는 없음, `commit(token, data)` → 수신·검증 결과, `release(token)` | 중복 예약·크기·세대 검사, 위치 쓰기 후 bitmap 공개, 마지막 청크 검증 1회. worker는 finally로 release함 |
| FileStore | `read_chunk(file, idx)` → bytes 또는 NOFILE/NOCHUNK, `record_sent(file, idx, size)` | 보유 청크만 읽음. 전체 DATA 송신 성공 뒤에만 sent·distinct·바이트를 집계함 |
| FileStore | `set_stalled(file, stalled)` | control이 계산한 유실 판정을 DOWN↔STALLED 전환으로 반영함. SEED·검증 중·FAILED 파일을 덮어쓰지 않음 |
| FileStore | `pause()`·`resume()`·`finalize()` | pause는 새 예약·commit을 막고 진행 중 I/O를 정리함. resume은 새 세대를 시작함. finalize는 진행 작업이 끝난 뒤 결과 저장·핸들 해제를 수행함 |
| `src.upload.server.UploadServer` | `start()`·`offline()`·`online()`·`stop(grace_sec)` | env 주소 bind, 연결당 handler, BITMAP/GET·UP 제한. offline은 listener·기존 연결을 닫고 반환하며 중복 호출을 허용함 |
| `src.upload.screen.StatusScreen` | `start(snapshot, recent)`·`stop()` | 복사본·최근 이벤트만 읽고, 터미널일 때 고정 상태판과 흐르는 로그를 표시함 |
| Peer 로그 발행 함수 | `emit(ev, **fields)` | 한 Peer의 구성요소 모두 같은 JSONL에 기록함. storage/upload는 상태 Lock을 놓은 뒤 호출함 |
| `tools/` | CLI·파일·실제 자식 프로세스 | 구현 패키지를 import하지 않음. 기동 도구는 Python 실행 파일·env·Tracker IP/PORT·정책을 인자로 받음 |

예약 토큰은 파일·idx·세대를 식별함. commit은 읽기 전용 결과로 `accepted`, `state`, `complete_now`를 반환하며, SHA-256을 통과해 SEED로 전환된 commit 하나만 complete_now=true임. Peer는 이때만 REGISTER함. 자체 crash의 오래된 토큰은 accepted=false로 끝내고 상대 실패·BAN에 포함하지 않음. commit·finalize의 저장 오류는 정상 완료로 숨기지 않고 호출자에게 전달함.

FileStore의 HASH·CORRUPT·COMPLETE와 업로드의 SEND는 각 제공자가 emit으로 기록하고, Peer는 commit 성공의 RECV 및 제어 이벤트를 기록함. 같은 사건을 중복 기록하지 않음. 복사본을 얻은 뒤 reserve가 실패하면 다른 후보를 다시 고름. 파일 bitmap·fd·mmap·내부 Lock을 다른 패키지에서 직접 읽거나 변경하지 않음.

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

### 파일·선택·장애 처리

- 선택과 `in_progress` 예약은 같은 임계 구역에서 수행함. 수신·길이 확인·위치 지정 쓰기가 끝난 뒤 bitmap=1로 바꾸며, 실패 시 finally에서 예약·inflight를 해제함. 마지막 청크의 부분 쓰기·읽기도 반복 처리함.
- random은 시작 때 전체 `(file, idx)` 순서를 한 번 섞음. rarest는 받을 수 있는 전체 후보 중 rarity 최소, 동점 무작위임. 난수 seed는 `policy_seed + 피어 번호`, CLI 정책이 env보다 우선함.
- 소스는 보유 bitmap=1, BAN 아님, inflight가 `per_peer_max` 미만인 상대 중 가장 한가한 곳을 고르며 동점은 무작위임. 연속 실패는 env 기준으로 BAN하고 성공 시 초기화함. NOCHUNK·BITMAP 실패·PEERS 제외 시 낡은 캐시를 버림.
- 원본은 시작 시 전체 SHA-256, 수신 파일은 완성 시 전체 SHA-256을 1 MiB 단위로 계산함. 일치하면 HASH→COMPLETE→REGISTER, 불일치하면 CORRUPT 후 재수신, 2회 연속 실패 시 `.corrupt`·FAILED임.
- crash는 listener·연결을 닫고 네트워크 송신을 멈추며 디스크·bitmap을 보존함. 복귀 시 HELLO·REGISTER/HAVE와 PEERS·BITMAP 갱신을 다시 수행하고 STALLED 계시를 초기화함. 자체 crash로 버린 DATA를 상대의 실패로 세지 않음.
- 파일의 미보유 청크 **전부**가 rarity=0인 상태로 `stall_sec` 지속될 때만 STALLED임. 다시 소스가 생기면 UNSTALLED·UNDONE으로 복귀함. 모든 파일이 SEED·STALLED·FAILED이면 DONE을 보내되 업로드는 계속함.
- 일반 종료는 ALLDONE 확인 → 새 연결 중단·업로드 유예 → worker·control 정리 → bitmap·lost·incomplete 저장 → BYE → EXIT 0임. ABORT·tracker_lost는 동일 정리 후 EXIT 2, destroy는 BYE 없이 DESTROY→저장→EXIT 3임.
- 종료·crash와 수신 완료의 경쟁을 검사함. 이전 연결의 DATA가 복귀 후 새 작업으로 반영되거나, 열린 파일을 닫는 중 handler가 읽는 상황을 막음. 모든 네트워크·Condition·join 대기는 종료 신호를 확인할 수 있어야 함.

### Tracker 관찰과 결과

네 피어가 모두 HELLO한 순간 START를 고정함. 이후 어떤 유효 메시지든 last_seen을 갱신하며, 침묵이 dead_sec를 넘으면 DEAD, 다시 참가하면 BACK으로 처리함. 종료한 BYE 피어는 PEERS에서 제외함. ALLDONE은 참가 완료 후 live 전원 DONE일 때 선언하며 이후 늦은 지시는 버림.

observer는 live이며 `report_stale_sec` 이내 REPORT만 사용함. 파일의 origin을 제외한 bitmap OR가 처음 모두 1이면 T_rep를 저장하고 당시 원본의 sent·distinct를 고정함. 모든 파일 복제가 끝나면 p_rep를 저장함. `dup_ratio=(sent−distinct)/sent`이며 관측하지 못한 값은 null로 남김. sent=0의 나눗셈을 피함.

replica_safe는 희생자가 가진 **모든 파일의 모든 1 청크**가 다른 fresh live Peer의 OR에 있는지 검사함. 희생자의 REPORT가 없거나 오래되면 파괴를 미룸. `T_destroy`는 pending에 파괴 지시를 넣은 시각이며 실제 전달은 CMD_DELIVERED로 구분함. report에는 `env, run, seed, policy, destroy_plan, crashes_sent, T_rep, p_rep, upstat_at_rep, dup_ratio, T_destroy, p_destroy, T_dead, T_done, T_last_done, T_alldone, T_exit, done_kind, peers, abort`를 배포 예시 순서로 기록함.

report 시각은 START 기준, JSONL `t`는 각 프로세스 시작 기준임. 두 시계를 그대로 비교하지 않음. C3의 env 정책은 null이며 배포 report 예시도 이를 허용함. 실제 실행 정책은 각 Peer START와 결과 폴더명으로 확인하고, 4개 Peer가 같은 정책인지 대조함.

## 독립 개발과 통합 순서

1. 세 담당이 TCP·CLI·FileStore/UploadServer 계약을 기준으로 자기 대역과 소규모 데이터를 준비함. Tracker는 대역 Peer, Peer는 대역 Tracker·FileStore·UploadServer, storage/upload는 대역 다운로드 클라이언트를 사용하여 상대 코드 없이 검증함.
2. 황대겸·황왕석이 실제 FileStore/UploadServer를 Peer 진입점에 조립하고 단일 소스→다중 소스→8 worker를 확인함. 안선효는 동시에 Tracker의 관찰·지시·종료를 독립 검사함.
3. 안선효가 실제 Tracker 1개와 Peer 4개를 독립 프로세스로 연결함. 로컬 DEV에서 해시·부분 재공유·속도·crash·종료·공식 verify를 확인한 뒤 A·B·C1·C2·C3의 조건을 검사함.
4. VM Tracker DEV를 통과한 뒤 제출 7회를 하나씩 실행함. 황왕석의 도구로 로그·report를 취합하고 원래 데이터가 있는 실행 폴더에서 공식 verify를 수행한 다음 결과 기록을 보관함. 각 담당이 자기 로그·오류를 대조하고 안선효가 통합 정합성과 실측 분석을 확정함.

시나리오는 동시에 돌리지 않음. 대역 테스트 통과와 실제 통합·원격 실행 통과를 구분함. C3 추가 2–3회는 권장 분석이며 필수 7회와 구분함.

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

bitmap은 희생자·원본·완성 파일도 필수이며 청크 수만큼의 0/1 문자열, 줄바꿈 없음임. lost는 미보유 번호를 오름차순·쉼표·연속 구간 a-b로 기록함. 미완성 `.part`는 종료 시 원본 크기의 `.incomplete`로 바꿔 verify 전까지 보존함. 완성 데이터·incomplete·data·키·임시 파일은 제출 기록에 넣지 않음.

Readme.txt는 조원 이름·학번·역할, 실제 언어·설치·실행, VM 종류·리전·포트, Thread·Lock 대응, 속도·선택·장애·STALLED 설계, 실측표·분석·정합성·한계·느낀 점을 포함함. AllDefinedLogs.txt에는 실제 사용한 모든 이벤트·필드·단위·기록 시점을 정의함. JSONL은 각 이벤트마다 flush하고 마지막 줄을 EXIT로 유지함. 시연은 공지 기준에 따라 DEV 또는 A의 ASCII·crash/rejoin, C2의 STALLED→ALLDONE, verify PASS를 포함하며 링크의 비로그인 접근·재생을 확인함. 별도 분석 보고서는 만들지 않음.
