# Data_Communication

# HW1 팀 공지 · 역할 분담 · 개발 규약

> **마감: 2026년 9월 23일(수) 23:59 / 언어: Python / 조원: 3명 / Worker: 4개**
>
> 이 문서는 조원들이 함께 구현하기 위한 작업 안내다. **아래 함수와 실행 명령은 구현 목표이며, 현재 구현 완료를 의미하지 않는다.**
> 과제 필수 조건과 팀에서 선택한 설계를 구분했다. 이름·학번은 제출용 Readme.txt 작성 시 채운다.

## 먼저 읽을 내용

1. **A(팀장)는 Master·AWS, B는 Worker, C는 공통 통신·로그·P2P를 담당한다.**
2. **C가 공통 메시지 형식과 송수신 함수를 먼저 제공한다.** A와 B는 이를 함께 사용한다.
3. **B만 Worker 큐를 수정한다.** C의 P2P 코드는 B가 제공한 함수로 작업을 예약·추가·제거한다.
4. **가상 시간 규칙은 A가 초안을 작성하고 세 사람이 합의한 뒤 구현한다.** 각자 시간을 증가시키면 안 된다.
5. 코드를 합칠 때는 메시지 왕복 → 작업 처리 → 재시도 → P2P → 전체 검증 순서로 확인한다.
6. 함수·메시지·통계 기준을 바꿀 때는 상대 담당자에게 먼저 공유하고 이 문서도 수정한다.

### 목차

- [1. 무엇을 만드는가](#1-무엇을-만드는가)
- [2. 반드시 지켜야 할 과제 조건](#2-반드시-지켜야-할-과제-조건)
- [3. 담당과 개발 우선순위](#3-담당과-개발-우선순위)
- [4. A 담당 — Master·AWS](#4-a-담당--masteraws)
- [5. B 담당 — Worker](#5-b-담당--worker)
- [6. C 담당 — 통신·로그·P2P](#6-c-담당--통신로그p2p)
- [7. 공통 메시지와 작업 상태](#7-공통-메시지와-작업-상태)
- [8. 가상 시간 — 구현 전 공동 확정](#8-가상-시간--구현-전-공동-확정)
- [9. 큐·P2P·재시도 규칙](#9-큐p2p재시도-규칙)
- [10. 로그와 통계](#10-로그와-통계)
- [11. 실행·협업 규칙](#11-실행협업-규칙)
- [12. 최종 검증과 제출](#12-최종-검증과-제출)

## 1. 무엇을 만드는가

**Master가 데이터 5,000개를 나누어 주고, Worker들이 저장하며, 실패한 작업은 성공할 때까지 다시 처리하는 시스템이다.**

- **Master:** AWS에서 실행하는 관리자. 작업 생성·분배·실패 재할당·시간·결과 집계를 맡는다.
- **Worker:** 조원 로컬 PC에서 실행하는 처리자. 자신의 큐에서 작업을 꺼내 저장한다.
- **P2P:** 일이 몰린 Worker가 다른 Worker에게 대기 작업을 직접 넘기는 통신이다.
- **ACK:** 상대가 요청을 받았다는 확인 응답이다.
- **가상 시간:** 실제로 기다린 시간이 아니라 프로그램이 계산해 기록하는 시각이다.

```text
                   AWS Master
           배정 / 결과 / 시간 / 통계
                TCP 소켓 통신
        ┌────────┬────────┬────────┐
      Worker1  Worker2  Worker3  Worker4
        └──── Worker 간 직접 TCP ────┘
                    P2P 이전
```

Worker 코드는 하나를 공통으로 사용하고, ID가 다른 **독립 스레드 4개**로 실행한다. Worker마다 큐·저장소·소켓·통계를 따로 가진다.

## 2. 반드시 지켜야 할 과제 조건

| 항목 | 원문 요구사항 |
|---|---|
| 배치 | Master는 AWS/GCP 등 외부 클라우드, Worker는 조원 로컬 PC |
| 통신 | Master↔Worker, Worker↔Worker 모두 TCP 소켓 |
| Worker | 4개이며 각각 독립 스레드로 동작 |
| 데이터 | 중복 없는 4자리 16진수 Key 5,000개, Value는 1~100 정수 |
| 시작 | Worker 4개 연결·초기화가 끝난 후 작업 분배 |
| 분배 | 큐 여유가 가장 큰 Worker 우선, 대기 큐 10개면 해당 Worker 분배 중단 |
| 대기 큐 | 최대 10개, 가득 찬 큐에 들어오는 추가 요청은 즉시 FAIL |
| WARN | 큐가 70%를 초과한 상태에서 작업이 들고날 때마다 기록 |
| 처리 | 매 시도 가상 1~3초, 성공 80% / 실패 20% |
| 재시도 | Master가 실패 작업을 우선 큐에 넣어 다른 Worker에 재할당, 성공까지 반복 |
| P2P 점검 | 가상 1~3초 랜덤 주기, 예상 대기시간 = 대기 작업 수 × 2초 |
| P2P 조건 | 예상 대기시간이 15초를 초과하면 이웃 상태 조회·이전 요청 |
| 통신 지연 | 노드 간 가상 지연 1초. 실제 sleep으로 구현하지 않음 |
| 종료 | 고유 Key 5,000개 성공 완료, 전체 KV·통계 출력 후 정상 종료 |
| 설정 | Master IP·포트를 실행 인자 또는 설정파일로 지정 |

**외부 서버·소켓·독립 스레드 필수 조건 미충족, 압축 오류, 컴파일·실행 불가는 원문상 전체 0점 조건이다.**

### 원문 예시에서 주의할 점

- 완료 기준은 **고유 Key 5,000개의 성공**이다. 예시의 성공 3,987건으로 종료하면 안 된다.
- 강의자료에는 “5가지 지표”라고 쓰였지만 원문과 목록 기준으로 **필수 통계는 6개**다.
- 예시 수행시간 195.40초는 목표값이 아니다.
- 예시 Key `h2k7`은 16진수가 아니다. 실제 Key에는 `0-9, a-f`만 사용한다.
- Google Drive 사용 자체는 원문 필수가 아니다. 다운로드 가능한 영상 링크가 필요하다.

## 3. 담당과 개발 우선순위

| 담당 | 책임 | 담당 파일 |
|---|---|---|
| A — 팀장 | AWS, Master, 전체 통합, 가상 시간 관리 | master.py |
| B | Worker 실행, 큐, 저장·확률 처리, Worker 통계 | worker.py, run_workers.py |
| C | 공통 TCP 송수신, 로그, P2P | protocol.py, logger.py, p2p.py |
| 공동 | 메시지·시간 규칙, 통합 검증, Readme·영상 | README.md 및 제출 문서 |

### 우선순위의 의미

| 단계 | 먼저 완성할 것 | 다른 담당자에게 전달할 결과 |
|---|---|---|
| P0 | 공통 규약·통신·시간 설계 | C: 송수신 사용 예제 / A: 시간 규칙 초안 / B: 큐 함수 계약 |
| P1 | 접속·배정·큐·저장·결과·로그 | AWS Master와 Worker 4개가 작업을 주고받는 실행 |
| P2 | 실패 재할당·P2P·시간 통합 | 재실패 후 성공, Worker 간 안전한 작업 이전 |
| P3 | 통계·종료·전체 검증·제출 | 5,000개 완료 로그, 재현 가능한 실행법, 제출 파일 |

P0 동안 B는 큐·저장소를, A는 작업 생성·접속 관리 구조를 작성할 수 있다. **시간에 의존하는 처리·P2P 점검은 시간 규칙 확정 후 연결한다.**

## 4. A 담당 — Master·AWS

### 구현할 함수

| 우선순위 | 함수 | 역할 |
|---|---|---|
| P0 | `generate_tasks(count)` | 중복 없는 Key와 Value 생성. 원본 데이터는 따로 보관 |
| P0 | `register_worker(connection, hello)` | Worker ID·P2P 주소 등록, 중복 ID 거절 |
| P1 | `wait_until_ready()` | Worker 4개의 초기화 완료 확인 |
| P1 | `broadcast_peers()` | Worker들에게 다른 Worker 접속 주소 전달 |
| P1 | `select_worker(task)` | 최소 큐 우선, 동률이면 순환 선택 |
| P1 | `dispatch_task(task, worker)` | 작업 전송 및 아직 ACK가 안 온 배정 관리 |
| P1 | `handle_task_ack(message)` | 수신·거절 반영. 거절된 작업을 잃지 않고 다시 대기시킴 |
| P1 | `handle_result(message)` | 결과 검증, 중복 결과 제외, 성공·실패 집계 |
| P2 | `requeue_failed_task(task, worker_id)` | 실패 작업을 우선 큐에 넣고 직전 실패 Worker 기록 |
| P2 | `handle_transfer_result(message)` | P2P 이전 상태·작업 위치 반영 |
| P2 | `advance_clock()` | 합의한 방식으로 다음 가상 이벤트 처리 |
| P3 | `is_complete()` | 고유 성공 5,000개·원본 값 일치·미정리 작업 여부 확인 |
| P3 | `shutdown_all()` | 종료 신호, Worker 통계 수집, 전체 KV·STAT 기록, 연결 정리 |

### A 완료 조건

- 실패 재시도는 신규 작업보다 먼저 배정하며 **직전에 실패한 Worker는 제외**한다.
- 다른 Worker가 모두 가득 찼다면 재시도 작업을 보관하고 공간이 생길 때까지 기다린다.
- 생성한 원본 5,000개와 성공 완료 목록을 구분한다.
- 오래된 결과·중복 ACK·늦게 도착한 P2P 보고가 최신 상태를 덮어쓰지 않도록 검증한다.
- 배정 중인 작업과 큐 상태 보고를 중복 계산하지 않도록 ACK·상태 버전을 연계한다.
- SSH 연결과 별도로, 실행 중인 Master의 TCP 포트에 외부 Worker가 접속되는지 확인한다.

## 5. B 담당 — Worker

**B가 큐를 소유하고 수정한다. C는 아래 함수만 사용한다.** 함수 이름과 반환값을 바꿀 때 A·C에게 먼저 공유한다.

### 실행·큐·처리 함수

| 우선순위 | 함수 | 역할·반환값 |
|---|---|---|
| P0 | `Worker(worker_id, config)` | Worker별 큐·저장소·소켓·잠금·통계 생성 |
| P0 | `connect_master()` | Master에 접속하고 HELLO 전송 |
| P0 | `run()` | 독립 Worker 실행 루프. 네트워크 수신과 가상 이벤트 처리 연결 |
| P0 | `start_workers(config)` | run_workers.py에서 Worker 스레드 4개 시작 |
| P1 | `handle_master_message(message)` | TASK·시간 제어·STOP 등을 해당 동작으로 전달 |
| P1 | `enqueue_task(task, clock)` | 큐 수신. `accepted`, `reason`, `queue_size` 반환 |
| P1 | `get_queue_status()` | 대기 수, 이전 예약 수, 수신 공간, 상태 버전 반환 |
| P1 | `take_next_task(clock)` | 처리 가능한 작업 하나 또는 None. 이전 예약 작업 제외 |
| P1 | `start_task(task, clock)` | 처리시간·성공 여부 추첨, 가상 완료 이벤트 등록 |
| P1 | `complete_task(task, success, clock)` | 성공 저장 또는 실패 기록, 통계 갱신·결과 전송 |
| P1 | `report_result(task, success, clock)` | Master에 처리 결과 보고 |
| P1 | `report_queue_status(clock)` | Master에 큐 상태 보고 |
| P1 | `log_queue_change(before, after, clock)` | 큐 변화와 반복 WARN 기록 |
| P3 | `get_stats(clock)` | Worker 최종 통계 반환 |
| P3 | `shutdown(clock)` | 진행 상태 확인, 통계 저장·종료 응답, 소켓·스레드 정리 |

### C에게 제공할 P2P용 함수 — P2

| 함수 | 역할·반환값 |
|---|---|
| `reserve_transfer(count, transfer_id, clock)` | 큐 뒤쪽의 이전 가능한 작업 예약. 예약한 작업 목록 반환 |
| `accept_transfer(tasks, transfer_id, clock)` | 용량·중복 확인 후 묶음 전체 수신 또는 전체 거절. ACK용 결과 반환 |
| `get_transfer_status(transfer_id)` | 해당 이전이 수신 완료·거절·진행 중인지 조회 |
| `commit_transfer(transfer_id, clock)` | ACK 확인 후 송신 큐에서 예약 작업 제거 |
| `cancel_transfer(transfer_id, clock)` | 수신이 확실히 거절·취소된 경우에만 예약 해제 |

### B가 반드시 지킬 것

- 현재 처리 중 작업은 대기 큐 10개에 포함하지 않는다.
- **송신 이전 예약 작업은 ACK 전까지 대기 큐 용량에 포함**하고 처리 대상으로 꺼내지 않는다.
- 큐 상태 확인과 수정은 같은 잠금 안에서 수행한다.
- 네트워크 응답을 기다리면서 큐 잠금을 계속 잡지 않는다.
- 같은 Worker에서는 작업을 하나씩 처리하되, 처리 중에도 메시지 수신이 막히지 않게 한다.
- 재시도 작업도 매번 성공 80%·실패 20%를 적용한다.
- 저장소에는 성공한 작업만 반영한다.
- 팀 설계상 재시도 작업을 대기 큐에서 우선 선택하고, 같은 우선순위 안에서는 먼저 들어온 작업을 먼저 처리한다.

## 6. C 담당 — 통신·로그·P2P

### P0: 공통 통신부터 전달

| 함수 | 역할 |
|---|---|
| `JsonConnection(sock)` | 소켓별 수신 버퍼와 송신 잠금 보관 |
| `send(message)` | JSON + 줄바꿈을 UTF-8로 전송. sendall 사용 |
| `receive()` | 줄바꿈까지 누적하고 메시지 한 개 반환. 남은 데이터는 보존 |
| `close()` | 연결 종료, 수신 대기 해제 |
| `validate_message(message)` | 메시지 종류별 필수 필드·자료형 검사 |

**A와 B에게 사용 예제와 오류 규칙을 먼저 공유한다.**

- 정상 수신은 dict, 정상 연결 종료는 None.
- 잘못된 메시지와 소켓 오류는 서로 구분 가능한 예외로 전달한다.
- 한 메시지가 여러 번에 나뉘어 와도 처리한다.
- 여러 메시지가 한꺼번에 와도 각각 처리한다.
- 소켓 하나당 수신 담당은 하나로 제한한다.
- 여러 스레드의 송신은 잠금으로 메시지가 섞이지 않게 한다.
- 수신 직후 가상 이벤트를 실행할지 여부는 시간 관리자와 연동한다. 통신 함수가 스스로 시간을 증가시키지 않는다.

### P1: 공통 로그

| 함수 | 역할 |
|---|---|
| `create_logger(node_id, path)` | 노드별 로그 파일 준비 |
| `log_event(clock, event, status, message)` | 공통 형식으로 스레드 안전하게 기록 |
| `close_logger()` | 버퍼 저장 후 파일 닫기 |

EVENT·메시지·발생 조건은 AllDefinedLogs.txt에 함께 기록한다. log_event는 생성한 logger 객체의 메서드로 구현해 노드·파일을 구분한다.

### P2: P2P 구현

| 함수 | 역할 |
|---|---|
| `start_listener(host, port)` | Worker의 직접 TCP 접속 수신 |
| `set_peers(peer_list)` | 다른 Worker 주소 등록 |
| `handle_peer_message(message)` | 큐 조회·작업 이전·이전 상태 확인 요청 처리 |
| `schedule_next_check(clock)` | 다음 점검 시각을 현재 가상 시각 + 랜덤 1~3초로 예약 |
| `check_load(clock)` | 대기 작업 수 × 2 > 15일 때 이웃 조회·이전 시도 |
| `query_peer_status(peer)` | 소켓으로 상대 큐 상태 조회 |
| `select_target(statuses)` | 자기보다 큐가 작고 수신 공간이 있는 Worker 선택 |
| `calculate_transfer_count(local, remote)` | 큐 차이의 절반을 기본으로 이전 개수 계산 |
| `transfer_tasks(target, count, clock)` | B의 예약 → 직접 전송 → ACK 확인 → B의 제거 함수 호출 |
| `query_transfer_status(peer, transfer_id)` | ACK가 불명확할 때 상대의 수신 상태 확인 |
| `report_transfer_result(transfer_id, clock)` | Master에 이전 결과·작업 위치 보고 |
| `stop()` | 진행 중 이전 정리 후 P2P 연결·수신 루프 종료 |

### C가 반드시 지킬 것

- 큐를 직접 변경하지 않고 B의 함수만 사용한다.
- 묶음 이전은 수신 공간이 충분할 때 전체 수락하고, 부족하면 전체 거절하는 방식으로 시작한다.
- Worker당 송신 이전은 한 번에 한 건씩 진행한다.
- 같은 transfer_id를 다시 받아도 큐에 중복 추가하지 않는다.
- **ACK 시간 초과는 수신 실패 확정이 아니다.** 상태가 불명확하면 예약을 유지하고 확인한다.
- 상태 조회에서 “모름”이 나왔다고 바로 취소하지 않는다. 원래 요청이 아직 도착 중일 수 있다.
- 실패·재시도·시간 제어를 위한 통신 비용도 합의한 시간 모델에서 처리한다.

## 7. 공통 메시지와 작업 상태

### 공통 봉투 — 팀 규약

```json
{
  "type": "TASK",
  "message_id": "master-000123",
  "sender": "MASTER",
  "receiver": "WORKER1",
  "clock": 12.0,
  "payload": {
    "key": "a3f7",
    "value": 42,
    "attempt": 1,
    "is_retry": false
  }
}
```

- sender/receiver는 MASTER, WORKER1~WORKER4를 사용한다.
- message_id는 송신 노드별 카운터 등으로 실행 중 중복되지 않게 만든다.
- 응답에는 payload.reply_to로 요청 message_id를 연결한다.
- payload는 메시지 종류별 내용이다. 공통 봉투와 payload를 혼용하지 않는다.
- attempt는 **Master의 새 배정 시도마다 증가**하는 번호다. 큐 거절 후 재배정도 새 번호를 사용한다.
- 실제 확률 실패 횟수는 attempt 값으로 계산하지 않고, 실제 처리 FAIL 이벤트로 집계한다.
- P2P 이전은 배정 재시도가 아니므로 key·value·attempt를 유지한다.
- is_retry는 처리 실패 또는 수신 거절로 재배정된 작업의 우선순위 표시에 사용한다. 실패 사유는 별도로 보존한다.

### 메시지 목록

| 종류 | 방향 | payload의 주요 내용 |
|---|---|---|
| HELLO | Worker → Master | worker_id, 다른 Worker가 접속할 수 있는 peer_host·peer_port |
| PEERS | Master → Worker | Worker별 P2P 주소 목록 |
| READY | Worker → Master | 큐·P2P 수신 준비 완료 |
| TASK | Master → Worker | key, value, attempt, is_retry |
| TASK_ACK | Worker → Master | reply_to, key, attempt, accepted, reason, queue_size, queue_version |
| RESULT | Worker → Master | key, value, attempt, status, reason |
| QUEUE_STATUS | Worker → Master | queue_size, reserved_out, free_slots, queue_version |
| P2P_QUERY / P2P_STATUS | Worker ↔ Worker | 요청 ID / 큐 상태 |
| P2P_TRANSFER | Worker → Worker | transfer_id, 작업 목록, 이전할 대기시간 정보 |
| P2P_ACK | Worker → Worker | transfer_id, accepted, reason |
| P2P_STATUS_QUERY / P2P_TRANSFER_STATUS | Worker ↔ Worker | transfer_id / 수신·거절·미확정 상태 |
| TRANSFER_RESULT | Worker → Master | transfer_id, from_worker, to_worker, 작업 목록, 결과 |
| STOP | Master → Worker | 완료 사유, 최종 시각 |
| STOP_ACK | Worker → Master | 최종 통계 |
| 시간 제어 메시지 | Master ↔ Worker | **8절 공동 확정 후 C가 종류·필드를 추가** |

RESULT의 status는 SUCCESS 또는 FAIL이다. 수신 거절은 TASK_ACK의 accepted=false와 reason=QUEUE_FULL로 표현하고, 로그에는 FAIL로 기록한다.

### 작업 상태

```text
미할당 → 배정 응답 대기 → 큐 대기 → 처리 중 → 성공 완료
                ↓                    ↓
             수신 거절             처리 실패
                └──── 재배정 대기 ────┘

큐 대기 → P2P 이전 예약 → ACK 확인 → 수신 Worker에서 처리
```

성공 여부는 Key별로 한 번만 반영한다. 중복 RESULT와 이전 보고의 도착 순서가 뒤바뀌어도 완료 상태를 되돌리지 않는다. 메시지는 실제 송신자·작업 ID·시도 번호·이전 이력을 함께 확인한다.

## 8. 가상 시간 — 구현 전 공동 확정

**필수 조건은 실제 sleep 없이 처리 1~3초·통신 1초를 반영하는 것이다. 원문은 병렬 시간 계산 알고리즘까지 고정하지 않는다.**

팀의 설계 방향은 **A가 관리하는 가상 이벤트 방식**이다. “현재 10초에 시작해 2초 걸리는 작업”은 실제 2초를 기다리지 않고 12초의 완료 이벤트로 등록한다.

- B는 처리 완료 시각, C는 P2P 점검 시각을 시간 관리자에 연결한다.
- 전송 시각과 도착 시각을 구분한다. 데이터 메시지 편도 지연은 1초를 적용하는 방향이다.
- 실제 TCP 수신과 가상 메시지 도착 처리를 구분한다.
- A가 시간 진행을 관리하더라도 P2P 작업 데이터는 Worker끼리 직접 전송한다.
- 실제 네트워크 timeout은 연결 오류 탐지용이다. 과제의 처리·통신 지연을 대신하지 않는다.

### A가 초안 작성 → B·C와 합의 → 이 절 갱신

- [ ] 동시 처리 시간을 합산할지, 병렬 완료 시각으로 계산할지 확정.
- [ ] 같은 가상 시각의 이벤트 처리 순서 확정.
- [ ] 실제로 늦게 도착한 메시지가 과거 이벤트가 되지 않도록 진행 허가·동기화 방법 확정.
- [ ] TASK·ACK·결과·큐 조회·P2P의 통신 지연 계산 단위 확정.
- [ ] 시간 제어 메시지 자체의 비용 처리 확정. 시간 제어가 추가 시간 제어를 무한 생성하지 않게 설계.
- [ ] 초기화·종료 시각과 전체 수행시간의 측정 구간 확정.
- [ ] 작은 예제로 병렬 처리·메시지 도착·점검이 일관되게 기록되는지 확인.

**이 항목은 아직 완성된 프로토콜이 아니다. 시간 관련 코드를 각자 임의로 완성하지 말고, 공통 규칙부터 닫는다.**

## 9. 큐·P2P·재시도 규칙

### 큐 크기

- queue_size: 처리 중 작업을 제외한 대기 작업 수. 송신 이전 예약 작업 포함.
- reserved_out: queue_size 중 이전 예약된 작업 수.
- free_slots: 10 - queue_size.
- 이미 큐에 포함된 예약 작업을 더해서 이중 계산하지 않는다.
- 팀 WARN 기준은 입출력 전 또는 후가 8개 이상이면 기록하는 것으로 한다. 따라서 7→8, 9→8, 8→7도 기록한다.
- 큐 10개에서 새 요청은 거절하고 FAIL 로그를 남긴다.

### 팀이 선택한 분배·P2P 기본안

| 기능 | 기본안 | 장점 / 한계 |
|---|---|---|
| Master 분배 | 최소 큐 우선 + 동률 순환 | 단순하고 공평함 / 상태 보고 지연에 주의 |
| 재할당 | 재시도 우선 + 직전 실패 Worker 제외 | 실패 작업을 끝까지 처리 / 과도한 재시도 시 신규 작업 지연 가능 |
| P2P 이웃 | 다른 Worker 3개 모두 | 후보 비교가 쉬움 / 조회 메시지 발생 |
| P2P 이전 개수 | floor((내 큐 - 상대 큐) / 2)를 기본으로, 예약 가능한 작업 수·상대 공간 이내 | 균형 회복 / 조회 후 상대 큐가 바뀔 수 있음 |

이전 개수가 0이거나 수신 가능한 상대가 없으면 이전하지 않고 다음 점검으로 넘어간다. 수신 시점의 용량 검사는 반드시 다시 한다.

### ACK 처리

1. 송신 Worker가 이전 작업을 예약한다.
2. 수신 Worker가 용량·중복을 확인하고 큐에 추가한다.
3. 수신 Worker가 ACK를 보낸다.
4. 송신 Worker는 ACK 확인 후 예약 작업을 제거한다.
5. Master에 이전 완료를 보고한다.

예약 중인 송신 작업은 처리하지 않는다. 수신 기록은 ACK 재전송에 사용할 수 있도록 보관한다. 통신이 끊겨 수신 여부를 확인할 수 없으면 작업을 임의 복제하거나 완료로 처리하지 말고, 오류·미완료 상태로 남긴다. 자동 재연결·프로세스 장애 복구는 원문의 20% 처리 실패 시나리오와 별도 확장이다.

## 10. 로그와 통계

```text
[12.00] WORKER1 | PROC | SUCCESS | key=a3f7 attempt=1 stored
```

파일은 Master.txt와 Worker1.txt~Worker4.txt로 나눈다. EVENT 이름은 자유롭게 정하되 AllDefinedLogs.txt에 모두 설명한다.

### 필수 통계 6개

| 지표 | 집계 기준 |
|---|---|
| Worker별 처리량 | 해당 Worker에서 성공한 KV 수 |
| 성공·실패 횟수 | 실제 처리 성공·20% 확률 실패 횟수. 큐 초과 거절은 별도 |
| 평균 대기시간 | 큐 진입부터 처리 시작까지의 가상 대기시간 |
| P2P 이벤트 횟수 | 성공한 이전 묶음 수. transfer_id 기준 중복 제거 |
| 장애 재할당 횟수 | 처리 실패 때문에 다른 Worker가 실제 수락한 재배정 건수 |
| 전체 수행시간 | 합의한 시작·종료 구간의 System Clock 차이 |

### 팀 집계 규칙

- 전체 성공 합계 = 고유 완료 Key 수 = 5,000이어야 한다.
- 80%는 매 시도의 확률이므로 실행 결과가 정확히 80:20일 필요는 없다.
- 큐 거절·ACK 재전송을 확률 실패에 더하지 않는다.
- P2P로 작업 3개를 한 번에 옮기면 이벤트 1회, 이전 작업 3건이다.
- 각 Worker는 P2P 송신·수신 횟수를 구분하고, Master는 transfer_id로 전체 이벤트를 한 번만 센다.
- Worker의 장애 재할당 지표는 처리 실패 유래 재배정을 수락한 건수로 정의한다. 일반 큐 거절 후 재배정은 따로 센다.
- 평균 대기는 **한 처리 시도 동안 각 큐에서 실제 대기한 구간을 합산**한다. P2P 이동 전에 쌓인 대기는 보존하고, 노드 간 이동 시간은 큐 대기에 포함하지 않는다. 처리 실패 후 새 시도는 새로 측정한다.
- 처리 시작된 시도 수와 대기시간 합을 함께 보관한다. 전체 평균은 Worker 평균의 단순 평균이 아니라 합계/전체 시도 수로 계산한다.
- 각 노드 STAT에 관련 지표를 기록하고, 값이 없으면 0과 측정 범위를 명시한다. Master는 전체와 Worker별 통계를 함께 기록한다.

## 11. 실행·협업 규칙

### 예정 파일 구조

```text
Data_Communication/
├── README.md
├── master.py
├── worker.py
├── run_workers.py
├── protocol.py
├── logger.py
├── p2p.py
├── AllDefinedLogs.txt
└── Readme.txt
```

실행 코드·제출 파일은 구현하면서 추가한다. 이 목록 자체가 파일 생성 완료를 의미하지 않는다.

### 실행 인자 목표 — 코드 구현 후 사용

```bash
# AWS: Master
python3 master.py --host 0.0.0.0 --port 5000

# 로컬 PC: Worker 4개
python run_workers.py --master-host <MASTER_PUBLIC_IP> --master-port 5000 --count 4
```

- Windows에서는 환경에 따라 python 대신 py를 사용한다.
- Master는 0.0.0.0에 바인딩하고, Worker는 Master 공인 IP에 접속한다.
- 같은 PC의 Worker끼리는 127.0.0.1과 서로 다른 P2P 포트를 사용할 수 있다.
- 서로 다른 PC이면 다른 Worker가 실제 접속할 수 있는 주소를 등록한다. 127.0.0.1이나 0.0.0.0을 원격 접속 주소로 배포하지 않는다.
- AWS Master 연결 성공과 Worker 간 직접 연결 성공은 별도로 확인한다.
- 조원은 Worker 실행에 PEM이 필요 없다. 서버 관리는 A가 맡는다.
- PEM·AWS 키·비밀번호·개인 설정은 GitHub와 제출 ZIP에 넣지 않는다. git add . 전에 파일 목록을 확인한다.
- 공통 Python 버전을 정하고 Readme.txt에 실제 시험한 버전을 기록한다.

### GitHub 작업 방식

1. 작업 전 최신 main을 받는다.
2. 담당 기능별 브랜치에서 작업한다. 예: feature/master, feature/worker, feature/protocol-p2p.
3. 담당 파일 중심으로 변경하고, 공통 함수 변경은 관련 담당자 A/B/C에게 공유한다.
4. PR에 “무엇을 구현했는지 / 실행 명령 / 확인한 결과 / 남은 문제”를 적는다.
5. A가 통합 확인 후 main에 반영한다.
6. 각 담당자는 자신의 기능 설명·알고리즘 장단점을 작성한다. 문서 전담으로 한 사람을 빼지 않는다.

## 12. 최종 검증과 제출

### 합치는 순서

1. C 송수신 함수로 메시지 분할·합쳐짐·연결 종료 검증.
2. Master↔Worker 1개 작업 배정·ACK·결과 확인.
3. AWS Master↔로컬 Worker 4개 연결.
4. 소량 작업으로 큐·확률 실패·재실패·재할당 확인.
5. P2P 이전·수신 거절·중복 전송·ACK 확인.
6. 가상 시간·통계·정상 종료 확인.
7. 기본 80%/20% 조건으로 5,000개 전체 실행.

소량·강제 실패·불균형 큐 구성은 검증용이다. 제출 전체 실행은 원문 조건을 사용한다. 정상 분배에서 P2P가 잘 발생하지 않으면 별도 검증에서 큐 9개·3개처럼 구성해 실제 이전을 확인한다.

### 완료 체크리스트

- [ ] 외부 Master, TCP 통신, 독립 Worker 스레드 4개.
- [ ] 초기화 완료 전 작업 분배 없음.
- [ ] 고유 Key 5,000개 성공, 원본 Value 일치.
- [ ] 재실패 시에도 다른 Worker로 우선 재할당.
- [ ] 큐 최대 10개, 초과 거절, 반복 WARN.
- [ ] P2P 이전 전후 유실·중복 처리 없음.
- [ ] 오래된 결과·중복 보고로 통계나 완료 상태가 변하지 않음.
- [ ] 필수 통계 6개와 전체 KV 출력.
- [ ] 작업·이전이 정리된 후 종료하며 수신 대기 스레드까지 정상 종료.
- [ ] 다른 폴더에 압축을 풀어 Readme.txt대로 실행 가능.

### 제출물

| 파일 | 내용 |
|---|---|
| 전체 소스·설정 | 실행에 필요한 파일 전체. 비밀 키 제외 |
| Master.txt, Worker1.txt~Worker4.txt | 전체 실행의 노드별 로그 |
| AllDefinedLogs.txt | 정의한 모든 EVENT·로그 메시지 명세 |
| Readme.txt | 조원 이름·학번·역할, 구성요소, 환경·실행법, 분배/P2P 알고리즘과 장단점, 장애 처리, 추가 사항 |
| download.txt | 5분 이내 G조이름HW1.mp4의 다운로드 가능한 링크 |

**GitHub README.md와 제출용 Readme.txt는 별개다.** 제출 전 실제 구현에 맞춘 Readme.txt를 반드시 준비한다.

영상은 초기화·동적 분배·실패 재할당·P2P·로그 출력을 보여준다. 5,000개 완료까지 전부 녹화할 필요는 없다. 링크 권한과 다운로드·재생을 다른 계정 또는 로그아웃 상태에서 확인한다.

최종 파일명은 **G조이름HW1.zip**이며 조별 한 명이 제출한다.

---

### 문서 검증 근거

2026-09-17 기준으로 로컬 제공 자료와 대조했다.

- HW1description_plain-20260910.pdf: 1~6쪽 요구사항, 7쪽 로그, 11~12쪽 제출 조건.
- HW1강의자료-20260910.pdf: 전체 흐름·필수 조건 보조 확인.
- 데이터 통신 과제 분석.pdf: 요약 참고.

함수명·메시지 구조·동률 처리·P2P 이전 개수·협업 방식은 **팀 구현 규약**이다. 가상 시간의 상세 동기화는 8절 체크리스트를 확정한 뒤 반영한다. 본 문서는 구현·테스트 완료 보고가 아니다.
