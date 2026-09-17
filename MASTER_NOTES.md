# Master 구현 메모

## 구현 범위

- 고유 KV 생성, Worker 4개 등록·준비 확인.
- 최소 큐 우선 배정, 동률 순환, 수신 ACK 전 추가 배정 제한.
- 실패 작업 우선 재배정, 직전 실패 Worker 제외.
- 큐 거절·확률 실패 분리, 오래된 큐 보고·중복 결과 제외.
- P2P 완료 보고 반영, 작업 소유 Worker 변경, 이전 ID 중복 집계 방지.
- 전체 KV·통계 기록, 종료 응답·Worker 성공/실패 집계 비교, 소켓·스레드 정리.

`master.py`의 `Master`는 데이터·분배 로직, `MasterServer`는 TCP·로그 연결 담당.
기존 protocol.py와 logger.py는 변경 없음.

## 현재 제한

확인한 main README에는 가상 시간의 상세 계산·동기화 방식이 아직 미확정으로 표시.
**현재 실행은 연결 검증 전용. 시각은 0, 전체 수행시간은 null로 기록. 제출용 로그로 사용 금지.**
처리 지연·P2P 주기·통신 지연의 최종 시뮬레이션은 시간 규칙 확인 후 연결 필요.
Worker·P2P 실제 구현과의 통합 및 AWS 실행은 미검증.

## 실행

```bash
python master.py --connection-test --host 0.0.0.0 --port 5000 --count 20
python -m unittest -v test_master
```

- 기본 작업 수 5,000. `--seed`로 데이터 생성 재현 가능.
- 기본 로그 폴더 `logs/master`. 같은 실행의 Worker 로그 폴더와 분리.
- `--timeout`은 실제 연결·응답 오류 확인 시간이며 가상 시간이 아님.
- 검증 Worker는 test_master.py 내부에만 존재. 조원의 Worker 코드 대체용이 아님.

## 조원과 맞출 메시지 초안

공통 모듈은 JSON 송수신만 담당하므로, 아래 형식은 Master 쪽 연동 초안.
기존 Worker 형식이 있으면 파트 간 확인 후 맞춤.

```json
{
  "type": "TASK",
  "message_id": "master-1",
  "sender": "MASTER",
  "receiver": "WORKER1",
  "clock": 0,
  "payload": {"key": "a3f7", "value": 42, "attempt": 1, "is_retry": false}
}
```

| 메시지 | payload |
|---|---|
| HELLO: Worker → Master | worker_id: 1~4, peer_host: 접속 가능한 주소, peer_port: 포트 |
| PEERS: Master → Worker | peers: worker_id·host·port 목록 |
| READY: Worker → Master | 빈 객체. 큐 초기화·P2P 수신 준비 후 전송 |
| TASK: Master → Worker | key, value, attempt, is_retry |
| TASK_ACK: Worker → Master | key, attempt, accepted: bool, queue_size, queue_version, reply_to |
| RESULT: Worker → Master | key, value, attempt, status: SUCCESS/FAIL, waiting_time, queue_size, queue_version |
| QUEUE_STATUS: Worker → Master | queue_size, queue_version |
| TRANSFER_RESULT: 송신 Worker → Master | transfer_id, source, target, items: key·attempt 목록 |
| TRANSFER_RECORDED: Master → 수신 Worker | transfer_id |
| STOP: Master → Worker | completed: 고유 성공 수 |
| STOP_ACK: Worker → Master | stats: success·fail 포함 최종 통계 객체 |

- Worker의 sender는 WORKER1~WORKER4, receiver는 MASTER.
- message_id는 Worker별 고유 값. 재전송한 동일 메시지는 같은 ID 사용.
- queue_version은 큐 상태 변경 시 증가하는 정수. 같은 버전은 같은 상태, 과거 버전은 무시.
- 큐 수에는 처리 중 작업 제외, 송신 이전 예약 작업 포함.
- TASK_ACK를 먼저 전송하고 해당 작업의 RESULT 전송. 큐가 가득 차면 accepted=false.
- 큐 변화 시 최신 상태 보고 필요. 공간이 생겨도 보고가 없으면 배정 대기 가능.
- attempt는 새 배정마다 증가. 중복 ACK·RESULT는 통계에 중복 반영하지 않음.
- waiting_time은 한 처리 시도의 누적 가상 큐 대기. 재시도 시 새로 측정.

## P2P 보고 순서

1. Worker 간 직접 전송·수신 ACK.
2. 송신 Worker에서 예약 작업 제거 후 TRANSFER_RESULT 전송.
3. Master의 TRANSFER_RECORDED를 받은 수신 Worker에서 이전 작업 처리 허용.

Master 보고보다 RESULT가 먼저 도착하는 순서 문제 방지용 초안.
P2P 데이터 전송은 여전히 Worker 간 직접 TCP 사용.
완료 보고 후 양쪽 Worker의 최신 큐 상태 보고 필요.
P2P 실제 요청·ACK·중복 방지는 조원 코드에서 별도 구현 필요.

## 시간 규칙 수신 후 남은 작업

- 가상 시간 진행과 송신·도착·처리 완료 순서 연결.
- P2P 조회·이전·확인 메시지의 가상 지연 반영.
- 초기화부터 종료까지의 전체 수행시간 기록.
- 새 메시지·상세 메시지 항목의 공통 로그 명세 보완 협의.
- 실제 Worker의 통계·P2P·종료 동작과 통합 시험.
