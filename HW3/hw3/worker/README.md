# HW3 Worker — 황대겸 담당 구현

기준: `main`의 `fc357c6` 및 `HW3/README.md`에 확정된 규약. 변경 범위는
`hw3/worker/`와 `tests/worker/`다. Coordinator·Launcher·공통 모듈은 다른 담당의 구현을 사용한다.
루트 `hw3/__init__.py`도 공통 담당 소유이므로 여기서 생성하지 않았다.
현재 Python의 namespace package로 Worker를 찾을 수 있고, 공통 담당이 초기화 파일을 추가해도 동작한다.

## 구성과 동작

- `__main__.py`: 확정된 CLI, 초기화, 종료 및 모든 스레드 join.
- `state.py`: Queue → state → Store 순서의 Lock, CV, crash_gen 및 상태 전이.
- `network.py`: Coordinator Control Recv, select 기반 Peer Server, 연결별 줄 버퍼와 송신 Lock.
- `compute.py`: Compute 스레드 하나. 진행 Task 완료 후 인계 Task FIFO, step 1–9 CKPT, step 10 RESULT.
- `heartbeat.py`: RUNNING의 1초 HB, REJOINING의 RETRY_LATER 이후 2초 재시도.
- `primes.py`: 작은 소수 1,229개를 이용한 구간 체. 명세의 양 끝 포함 범위를 계산한다.

Main 외에 Control Recv·Peer Server·Compute·Heartbeat 네 스레드만 생성한다.
Coordinator/Launcher 모듈을 import하지 않으며 프로그램 간 연결은 TCP다.
Buddy는 `i mod 10 + 1`로 고정하고 수신 Peer는 앞 Worker의 `PEER i`만 허용한다.
Buddy 송신 오류는 WARN 후 계산을 계속한다. Coordinator/Launcher 연결 종료는 치명적 오류로 종료한다.
접속 거절은 0.5초 후 재시도하며, 모든 개별 소켓 I/O에는 유한 타임아웃을 둔다.

상태는 `BOOTING → RUNNING → CRASHED → REJOINING → RUNNING`, 종료 시 `STOPPED`다.
READY는 START와 Launcher 연결이 모두 갖춰졌을 때 한 번만 전송한다.
재합류 후에는 WELCOME 이전에 HB·Compute·REQ를 보내지 않고 CKPT 수신만 허용한다.
REJOINED와 새 REQ는 WELCOME 이후 전송한다. Worker가 epoch를 증가시키지 않는다.

Task별 CKPT는 `(epoch, step)`이 가장 큰 것 하나만 저장한다. TAKEOVER를 실제 계산할 때
새 epoch보다 낮은 최신 CKPT의 다음 step과 partial로 재개한다. 없으면 step 1·partial 0이다.
진행 중 Task를 먼저 끝내며, ACK를 기다리지 않고 Queue까지 빈 경우에만 다음 REQ를 보낸다.
ACK·REJECT_STALE는 로그만 남기므로 지연된 응답이 새 Task를 지우지 않는다.
NO_TASK 이후에도 TAKEOVER는 계산하지만 새 REQ는 보내지 않는다.

## Crash 초기화와 송신 보장

CRASH는 소켓별 송신 Lock과 별개의 **Worker 송신 경계**를 먼저 잡는다.
진행 중 송신이 유한 타임아웃 내에 끝난 뒤 Queue → state → Store Lock을 잡아
CRASHED로 전환하고 아래 메모리를 초기화한다.

- 대기 Queue, 진행 Task, CKPT Store
- Task별 수신 epoch 중복 방지 자료와 RESULT 로그용 epoch 자료
- requested, no_task, 예약된 REJOIN 재시도 시각

crash_gen과 장애 회차는 증가한다. START/READY 여부와 Coordinator·Buddy·Launcher TCP는 유지한다.
CRASHED에서는 메시지를 계속 읽되 RESTART·Coordinator BYE 외에는 처리하지 않는다.
BYE는 CRASHED 상태의 CV 대기도 깨우고 모든 소켓과 스레드를 정리한다.

Compute는 Task를 꺼낸 세대를 기억한다. 정상 송신은 송신 경계 안에서 RUNNING과
동일 세대·Task epoch를 확인한다. 확인 후 업무 Lock을 풀고 실제 송신하므로
네트워크 I/O 동안 Queue·state·Store Lock을 보유하지 않는다.
송신 경계를 기다리던 이전 세대의 송신은 CRASH 이후 취소된다.
수신의 상태 확인과 Queue/Store 변경도 같은 업무 Lock 안에서 수행한다.

## 실행

Python 3.12 이상, 표준 라이브러리만 사용한다. `HW3`에서 실행한다.

```bash
python -m hw3.worker --id 1 --coord <REMOTE_IP>:4575 --peer-ip 127.0.0.1 --peer-port 7001 --step-delay 100 --run-id hw3-run01 --log-dir logs/hw3-run01
```

실제 실행에는 황왕석 담당의 다음 공통 API가 필요하다.

- `common.protocol`: Message, ProtocolError, encode, parse
- `common.transport`: LineBuffer, send_line
- `common.log`: NodeLogger
- `common.settings`: CONTRACT_VERSION

공통 모듈이 없으면 설명을 출력하고 종료 코드 2로 끝낸다. 제품에는 공통 대역을 연결하지 않는다.
공통 settings의 개별 수치 상수 이름은 원문 README에 지정되지 않았으므로 새로운 API 이름을 만들지 않았다.
현재 수식과 타이머에는 확정된 정식 수치를 그대로 적용했다. 공통 구현 통합 때 해당 상수의 실제 이름에 맞춰
참조를 연결하고 같은 기준 커밋에서 재검증해야 한다. CLI 인자 이름과 ms 단위는 기존 계약 그대로다.

## 독립 검증 결과

2026-10-14 로컬 Windows, Python 3.12.14에서 **23개 테스트 통과** (26.296초). 테스트 명령:

```bash
python -m unittest discover -s tests/worker -v
```

`tests/worker/contract_double.py`는 확정된 API와 문법의 **테스트 전용 대역**이다.
테스트가 명시적으로 설치하며 제품 코드에서는 사용하지 않는다.
프로세스 테스트의 `run_with_contract_double.py`도 제출 실행 명령으로 사용하면 안 된다.

검증 범위:

- 독립적인 일반 체와 Task 0의 모든 step 누적값 비교, Task 152/160/271 명세값 비교.
- 모든 1,000 Task 직접 계산 합계 `5,761,455`.
- 실제 Worker 10개 독립 프로세스의 TCP Ring, 1,000 RESULT·중복 없음·동일 합계.
- 실제 Worker 사이 CKPT 송수신, `W4 → W5 → W6` 및 `W10 → W1 → W2` 연속 crash.
  원래 Task와 대기 중 인계 Task를 모두 재인계하며, CKPT 소실 Task는 step 1부터 계산.
- 반복 crash, RESTART/REJOIN/RETRY_LATER/WELCOME, REJOINING CKPT 수신과 HB·계산 중단.
- READY의 양쪽 지연 순서, 메시지 분할/병합, 지연 ACK·stale 응답, NO_TASK 이후 TAKEOVER.
- CRASH 직전 송신 경쟁: 진행 송신 완료 후 전환, 기다리던 이전 세대 송신 취소,
  송신 중 세 업무 Lock 획득 가능.
- CRASHED 중 BYE, 잘못된 문법, Coordinator EOF, 모든 Worker 스레드 종료.

10개 프로세스의 전체 계산 검사는 개발용 `step-delay=0`이다. 다른 TCP 검사는 10–300ms 지연을 사용한다.
테스트는 임시 디렉터리와 독점적인 로컬 포트, 직접 생성한 프로세스 핸들만 사용하고 모두 정리한다.
연구실 서버나 GPU는 사용하지 않았다.

**실제 공통 모듈·Coordinator·Launcher와의 통합은 미완료**다. 기준 main에는 이 소스들이 없었다.
대역 검증은 원격 AWS 실행, 실제 FD 인계 판정, 정식 100ms 무작위 장애 실행,
최종 로그 12개 분석과 제출 영상의 증거가 아니다. 관련 소스 통합 후 단계별 실제 연결 검사를 수행해야 한다.

## 로그 취합 안내

Worker 이벤트 정의는 같은 폴더의 `AllDefinedLogs.txt`에 기록했다.
최종 공통 `AllDefinedLogs.txt`에 안선효 담당이 취합할 수 있는 Worker 부분이다.
TAKEOVER 로그는 실제 계산 재개 시점에 기록하며 ckpt_epoch·resume_step·초기 partial을 포함한다.
NodeLogger가 KST 형식, run_id, ts_unix_ms 및 한 줄의 직렬화를 담당한다.

`REJECT_STALE k reason`과 `ACK k`에는 epoch가 없다. REJECT_STALE 로그는 첫 세대에서
해당 Task의 송신 RESULT epoch가 하나로 확정될 때만 그 값을 기록한다.
crash 이후의 늦은 응답 또는 여러 epoch의 응답은 `epoch=null`로 기록해 추측하지 않는다.
이에 대한 확정 epoch의 최종 근거는 Coordinator의 거부 로그다. 응답이 어떤 경우든
Worker의 진행 Task·Queue·requested에는 영향을 주지 않는다.
