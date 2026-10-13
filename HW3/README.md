# HW3 - Fault-Tolerant 협업 Worker Ring

2026학년도 2학기 데이터통신 2조 HW3. 현재 설계 단계이며 구현 언어는 미정이다.
제출 기한: **2026-10-26(월) 23:59**.

## 과제 개요

원격 Coordinator와 로컬 Worker 10개가 1~100,000,000의 소수 개수를 Task 1,000개로 나누어 계산한다. 반복되는 가상 crash·restart·rejoin에서도 모든 Task를 정확히 한 번 확정해야 한다.

| 구성요소 | 실행 위치와 역할 |
| --- | --- |
| Coordinator | 별도 원격 호스트. 고정 Dispatcher 6개, Request Queue, HB 장애 감지, Task 배정·인계·결과 확정 |
| Worker | 로컬 PC 한 대에서 독립 프로세스 10개. step 계산, 고정 Buddy에 CKPT 전송, HB·재합류 |
| Chaos Launcher | Worker와 같은 로컬 PC. 각 Worker에 개별 TCP 연결, 무작위 CRASH·RESTART 주입 |

## 핵심 규칙

- 모든 통신은 TCP. RING_OK 10개 후 START, Task마다 별도 Mutex, 대기는 Condition Variable.
- Worker는 RUNNING일 때 1초마다 HB. Coordinator만 HB 부재로 3초 SUSPECT·5초 DEAD를 판정한다. Launcher와 Coordinator는 통신하지 않는다.
- CKPT는 항상 고정 Buddy로 보낸다. Worker끼리는 상대의 생사를 판정하지 않는다.
- crash 중 TCP 연결을 유지하고 Queue·진행 Task·CKPT Store를 지운 뒤 침묵한다.
- 임의의 순간에 CRASHED·REJOINING인 Worker의 합은 최대 2개다.
- DEAD Worker의 모든 ASSIGNED Task를 링의 다음 ALIVE에게 인계한다. 이전에 인계받은 Task도 포함한다.
- **연속 Buddy 2개 장애:** 백업이 소실되면 처음부터 재계산하고, 인계받은 Worker까지 죽으면 그 Worker 소유 Task 전체를 다시 인계한다.
- Coordinator가 Task별 epoch·owner를 관리하고, 현재 값과 일치하는 RESULT만 Task Lock 안에서 한 번 Commit한다.
- 재합류한 Worker는 옛 Task를 돌려받지 않고 새 Task를 요청한다.
- 정식 실행은 원격 구성과 `--step-delay 100`. 성공 기준은 DONE=1,000, 모든 commit_count=1, 합계=5,761,455다.

## Java와 Python 비교

아래 난이도와 추천은 설계 판단이며 두 언어의 구현·성능을 실측한 결과가 아니다. 언어가 달라도 crash·송신 경쟁, Lock 순서, 재인계 검증은 동일하게 필요하다.

| 기준 | Python | Java |
| --- | --- | --- |
| 처음 구현하는 난이도 | 상대적으로 쉬움. 짧은 코드, deque·dict·Lock·Condition으로 구성 | 상대적으로 높음. 클래스·타입·NIO 버퍼·부분 쓰기 처리가 더 많음 |
| 고정 Listener·Thread Pool | selectors와 직접 만든 Thread 6개·Queue·CV | Selector와 직접 만든 Thread 6개·Queue·Condition |
| Worker 프로세스 실행 | subprocess.Popen | ProcessBuilder |
| 오류 확인 | 빠른 수정·실행, 자료형·메시지 오류는 실행 검증 필요 | 컴파일 시 자료형·메서드 계약 오류를 일부 확인 |
| 기존 HW 코드 활용 | HW1은 Python이지만 시간·장애 모델이 달라 그대로 이식하기 어려움 | HW2의 Queue·Condition, Selector, 송신 Lock·로그 코드를 수정해 활용 가능 |
| 계산 성능 | 기본 CPython의 CPU 스레드 병렬성에는 GIL 제약. 독립 Worker 10개 프로세스로 계산 분산 | 같은 GIL 제약은 없음. 실제 구간 체 처리시간은 별도 측정 필요 |
| 배포 | Python 실행 환경 필요, 별도 컴파일 단계 없음 | JDK와 컴파일 단계 필요. HW2에 Java 배포 설명이 있음 |

**구현 난이도와 신규 코드 양을 우선하면 Python을 권장한다.** Coordinator는 주로 I/O·상태 처리이며 계산은 Worker별 독립 프로세스이므로, 이 과제에서 GIL만을 이유로 Python을 제외할 필요는 없다. 실제 계산·HB 지연은 측정해야 한다.

조원들이 Java에 더 익숙하고 HW2 공통 코드를 적극 재사용한다면 Java도 합리적이다. 재사용하더라도 고정 스레드 수, 신규 프로토콜, Worker 독립 프로세스, 가상 crash·epoch 모델에 맞게 수정·재검증해야 한다.

근거: [Python threading](https://docs.python.org/3/library/threading.html), [selectors](https://docs.python.org/3/library/selectors.html), [subprocess](https://docs.python.org/3/library/subprocess.html), [Java Condition](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/locks/Condition.html), [Selector](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/nio/channels/Selector.html), [ProcessBuilder](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/lang/ProcessBuilder.html). 기존 코드 참조: `HW2/src/cwnu/dchw2/server/`의 BoundedRequestQueue·Listener·ClientConnection 및 `common/Log.java`.

## 구현 순서

1. 소수 함수·메시지 경계·공통 로그 검증.
2. 기동·Ring 구성·장애 없는 1,000 Task 계산·종료.
3. HB·FD·단일 crash·CKPT 기반 인계.
4. Rejoin·반복 crash·연속 Buddy 장애·stale 결과 검증.
5. 무작위 Launcher·원격 정식 실행·로그와 지표 정리.

소스·실행 명령·실측 결과는 구현 후 추가한다.
