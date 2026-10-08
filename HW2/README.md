# HW2 - Thread Pool 기반 실시간 좌석 예매 시스템

## 1. 프로그램 개요

좌석 100개를 관리하는 원격 Server와 로컬 Client 30개가 TCP Socket으로 통신하는 Java 프로그램이다. 단일 예약, 다중 예약, 취소, FIFO 대기 등록과 비동기 배정 통지를 처리한다. Server는 고정 Worker 10개와 Request Queue를 사용하며 요청이나 연결마다 새 서버 스레드를 만들지 않는다.

이 문서의 구현 기준은 `2314024b3b5f03890129967dca1720e3a11c241b`의 제품 소스다. 로그 명세, 로그 분석 방법과 실측 결과는 별도 작성 영역으로 비워 두었다. 문서의 설정값과 판정 기준은 실행 결과가 아니다.

| 항목 | 설정 및 조건 |
| --- | --- |
| 좌석 | 1~100번, 초기 owner=0(EMPTY) |
| Client | 30개, Client별 TCP 연결 1개 |
| Server 스레드 | main Listener 1개, Worker 10개, Notifier 1개, Monitor 1개 |
| 정식 요청 | Client당 5,000건, 전체 150,000건 |
| 전송 간격 | 첫 요청 이후 무작위 200~1,000ms sleep |
| 인기 좌석 | 1~10번. 모든 요청의 실제 선택 좌석 중 절반 이상이어야 함 |
| 다중 예약 | 서로 다른 2~4석, All-or-Nothing, 오름차순 Lock Ordering |
| Request Queue | FIFO, 최대 1,024건 |
| 상태 출력 및 감시 | 5초마다 상태 출력, Queue가 비어 있지 않고 30초간 첫 응답 진전이 없으면 정지 의심 집계 |

## 2. 조원과 역할

데이타통신 2조.

| 이름 | 학번 | 역할 | 담당 |
| --- | --- | --- | --- |
| 안선효 | 20170210 | 팀장 | 공통 규약·Protocol·Interfaces, Server·SeatManager·BoundedRequestQueue·Worker·Notifier, 통합 |
| 황대겸 | 20223149 | 조원 2 | ClientMain·Client·공통 Log |
| 황왕석 | 20222161 | 조원 3 | Listener·ClientConnection·Monitor |

공통 메시지, 인터페이스와 실행 기준은 팀장이 지정했다. 담당별 독립 검증에서는 인터페이스 대역을 사용할 수 있지만 제품 구성에는 실제 구현만 연결한다. 공통 계약 변경은 팀장이 확정하고 관련 담당에게 전달한다.

## 3. 파일 구성과 책임

기본 패키지는 `cwnu.dchw2`이며 `server`, `client`, `common`으로 나뉜다. Java 소스는 총 13개다.

```text
HW2/
├─ README.md
└─ src/cwnu/dchw2/
   ├─ server/
   │  ├─ Server.java
   │  ├─ SeatManager.java
   │  ├─ BoundedRequestQueue.java
   │  ├─ Worker.java
   │  ├─ Notifier.java
   │  ├─ Listener.java
   │  ├─ ClientConnection.java
   │  └─ Monitor.java
   ├─ client/
   │  ├─ ClientMain.java
   │  └─ Client.java
   └─ common/
      ├─ Protocol.java
      ├─ Interfaces.java
      └─ Log.java
```

| 클래스 | 실제 역할 |
| --- | --- |
| Server | 구성 연결, Client 등록, 첫 응답·통지 집계, 정상/실패 종료, 최종 상태 검사 |
| SeatManager | 좌석별 owner·Lock·FIFO waitlist, 예약·취소·MULTI 원자적 판정 |
| BoundedRequestQueue | 용량 제한 FIFO와 notEmpty/notFull Condition, close 후 잔여 요청 유지 |
| Worker | 요청 추출, 좌석 판정, 통지 적재, 첫 응답 송신. 좌석 Lock 밖에서 I/O 수행 |
| Notifier | Notify Queue와 Condition 대기, 인계받은 Client에 NOTIFY 송신 |
| Listener | main 스레드의 NIO Selector로 accept·수신·메시지 분리·HELLO 등록·Queue 적재 |
| ClientConnection | 수신 조립, 요청 번호 검사, 메시지 단위 송신 직렬화, 부분 쓰기·write=0·연결 종료 처리 |
| Monitor | 좌석·Queue·누적 처리 수의 주기 관측과 단순 처리 정지 감시 |
| ClientMain | Client 30개 시작, 실패 전파, 전체 종료 대기, 정식 인기 좌석 비율 판정 |
| Client | 요청 생성·송신, 별도 수신 흐름, 보유·진행 중·대기 상태 관리 |
| Protocol | 숫자 상수·Request/Response, 메시지 인코딩·해석 |
| Interfaces | 파트 간 계약과 Task·Result·WaitNotice·조회 데이터 |
| Log | |

Request·Response는 Protocol의 중첩 일반 클래스, 공유 데이터는 Interfaces의 중첩 일반 클래스다. 구현의 Seat·WaitEntry는 SeatManager 내부에 둔다. 숫자 `public static final int`와 `switch`를 사용하고, 중첩 타입은 각 소스 상단에서 import하여 본문에서는 단순 이름으로 사용한다. 구현 Queue의 이름은 interface RequestQueue와 충돌하지 않도록 BoundedRequestQueue로 구분했다.

## 4. 배포 환경과 실행 조건

| 항목 | 환경 |
| --- | --- |
| 원격 Server | AWS EC2 t3.micro, Ubuntu 26.04 LTS, x86_64 |
| 로컬 Client | Windows PC 1대에서 ClientMain으로 Client 30개 실행 |
| Java | 양쪽 Temurin JDK 17.0.20.1+1, Java 표준 라이브러리만 사용 |
| 연결 | 로컬 PC에서 AWS 공인 주소로 직접 TCP 접속. SSH 터널이나 임시 대역을 사용하지 않음 |
| 주소 및 포트 | Server와 ClientMain의 실행 인자로 지정. 아래 명령의 5000은 포트 예시이며 변경 가능 |
| 시간대 | UTC |

JDK의 `bin`이 현재 터미널의 PATH에 있어야 한다. 격리 JDK를 사용할 경우 `java`와 `javac`를 해당 JDK의 실행 파일 경로로 호출해도 된다. `java -version`과 `javac -version`으로 양쪽 버전을 확인한다.

AWS에 같은 제품 소스를 배치하고 해당 TCP 포트의 수신이 허용된 상태에서 Server를 먼저 실행한다. `<AWS_PUBLIC_IP>`에는 실제 AWS 공인 IP 또는 DNS 이름을 넣는다. `0.0.0.0`은 Server의 bind 주소이며 Client의 접속 주소가 아니다. IP가 바뀌면 Client 실행 인자를 바꾼다. 인증용 PEM은 실행 소스나 제출물에 포함하지 않는다.

Server의 NIO Selector는 원격 Linux에서 실행한다. 로컬 Windows Client는 blocking Socket을 사용한다. Windows에서 Server까지 실행하는 개발 구성은 Selector 초기화 환경의 영향을 받을 수 있으며 원격 배포 구성과 구분한다.

## 5. 컴파일과 실행

모든 명령은 해당 컴퓨터의 `HW2` 폴더에서 실행한다. 두 컴퓨터 모두 공통 파일만이 아니라 전체 Java 소스를 컴파일한다. 실행마다 Server와 ClientMain의 포트 및 Client당 요청 수가 같아야 한다.

### 5.1 원격 Linux Server

```bash
java -version
javac -version
mapfile -t sources < <(find src -type f -name '*.java' | sort)
mkdir -p out
javac --release 17 -encoding UTF-8 -Xlint:all -d out "${sources[@]}"
java -cp out cwnu.dchw2.server.Server 0.0.0.0 5000 5000
```

마지막 명령의 첫 `5000`은 포트, 두 번째 `5000`은 Client당 요청 수다. 프로그램이 정상 종료할 때까지 Server 터미널과 원격 연결을 유지한다.

### 5.2 로컬 Windows Client

```powershell
java -version
javac -version
$sources = @(Get-ChildItem -LiteralPath src -Recurse -Filter '*.java' |
    ForEach-Object { $_.FullName })
javac --release 17 -encoding UTF-8 -Xlint:all -d out $sources
$serverHost = 'AWS_PUBLIC_IP' # 실제 AWS 공인 IP 또는 DNS로 교체
java -cp out cwnu.dchw2.client.ClientMain $serverHost 5000 5000
```

`AWS_PUBLIC_IP`는 설명용 자리표시자이며, 실행 전에 `$serverHost`에 실제 주소를 지정한다. ClientMain은 별도 창 30개가 아니라 한 JVM 안에서 Client 30개를 실행한다. 각 Client에는 송신 스레드와 수신 스레드가 있으며 Client별 Socket은 1개다.

### 5.3 실행 인자와 축소 실행

| 진입점 | 인자 순서 | 의미 |
| --- | --- | --- |
| Server | `<bindHost> <port> <requestsPerClient>` | 수신 인터페이스, 수신 포트, 각 Client의 첫 응답 목표 |
| ClientMain | `<serverHost> <port> <requestsPerClient>` | AWS 접속 주소, 접속 포트, 각 Client의 송신 목표 |

포트는 1~65535, 요청 수는 1~`Integer.MAX_VALUE / 30` 범위다. Client 수 30개와 Worker 수 10개는 고정이며 요청 수만 축소할 수 있다. 요청 간격은 실행 인자로 바꾸지 않는다.

개발용 30×20 실행은 Server의 마지막 인자와 ClientMain의 마지막 인자를 모두 `20`으로 바꾼다. 정식 실행은 두 인자를 모두 `5000`으로 설정한다. 축소 실행을 정식 부하 결과로 제출하지 않는다. 인자 오류·실행 실패는 종료 코드 1이며 정상 실행은 0이다. 정식 실행 완료 후 인기 좌석 비율이 절반 미만이면 조건 미달을 별도로 표시하고 ClientMain이 코드 1로 종료한다. 축소 실행의 인기 조건은 `NOT_EVALUATED`다.

## 6. TCP 메시지와 공통 계약

### 6.1 메시지 경계와 요청 번호

메시지는 UTF-8이며 LF(`\n`)로 구분한다. 인코딩 함수는 LF 없는 문자열을 반환하고 실제 송신 담당이 LF를 한 번 붙인다. Listener는 불완전한 줄을 다음 수신까지 보관하며 한 번에 여러 줄이 들어오면 각각 처리한다. 잘못된 UTF-8이나 해석할 수 없는 메시지는 실행 실패로 처리한다.

각 Client의 첫 메시지는 HELLO다. Client ID는 1~30으로 중복 등록할 수 없으며, 요청 ID는 연결마다 1부터 하나씩 증가한다. HELLO에는 별도 응답을 보내지 않는다. Worker가 동시에 처리하므로 첫 응답의 도착 순서는 요청 순서와 다를 수 있다. Client는 요청 ID로 응답을 연결한다.

| 방향 | 메시지 | 의미 |
| --- | --- | --- |
| Client → Server | `1000 clientId` | HELLO 등록 |
| Client → Server | `1001 reqId seat` | RESERVE, 단일 예약 |
| Client → Server | `1002 reqId seat1,seat2,...` | RESERVE_MULTI, 2~4석 예약 |
| Client → Server | `1003 reqId seat` | CANCEL, 자신의 보유 좌석 취소 |
| Server → Client | `2000 reqId status seats reason` | RESP, 요청의 첫 응답 |
| Server → Client | `2001 reqId seat` | NOTIFY, 원 단일 예약 요청의 대기자 배정 |
| Server → Client | `2002` | BYE, 정상 종료 신호 |

| 항목 | 값 또는 규칙 |
| --- | --- |
| RESP status | SUCCESS=3000, FAIL=3001, WAITLISTED=3002 |
| reason | OK, TAKEN, ALREADY_OWNER, ALREADY_WAITING, NOT_OWNER, BAD_SEAT, BAD_MULTI |
| seats | 공백 없는 쉼표 목록, 빈 목록은 `-`. 요청 좌석의 입력 순서 유지 |
| Client ID 부착 | 예약 메시지에 따로 넣지 않고 HELLO로 등록된 연결에서 Listener가 부착 |
| 첫 응답 | 유효한 요청당 RESP 1개. WAITLISTED도 첫 응답 완료에 포함 |
| NOTIFY | 원 대기 요청의 reqId 사용. 첫 응답 수와 별도 집계 |
| 입력 오류 | 잘못된 범위·MULTI 개수·중복 좌석은 FAIL. 명령·숫자·HELLO·요청 번호 규약 오류는 연결 정리 후 실행 실패 |

### 6.2 파트 간 인터페이스

실제 계약은 [Interfaces.java](src/cwnu/dchw2/common/Interfaces.java)에 정의돼 있다. 구현 클래스가 아니라 이 interface를 인자로 받아 상태 판정·통신·종료 책임을 분리한다.

| 구현 | interface | 주요 메서드 |
| --- | --- | --- |
| Server | ServerContext | registerClient, findClient, recordFirstResponse, recordNotify, recordDeadlockSuspicion, completedCount, lastProgressNanos, reportFailure |
| BoundedRequestQueue | RequestQueue | put, take, close, snapshot |
| SeatManager | Seats | handle, snapshot, metrics |
| ClientConnection | Connection | clientId, bindClientId, send, close |
| Notifier | Notifications | submit, finish, run |
| Listener·Monitor | Stoppable | run, stop |
| Log | Logger | |

| 공유 데이터 | 용도 |
| --- | --- |
| Task | Request와 해당 Connection을 Queue에 전달 |
| Result | 첫 응답과 선택적 WaitNotice를 Worker에 전달 |
| WaitNotice | 통지 대상 Client ID, 원 요청 ID, 좌석과 등록 시각 |
| QueueView·SeatView·SeatMetrics | Lock을 보호한 조회 결과를 Monitor·Server에 전달 |

Server.main은 Log·Listener·Monitor를 기존 생성자 계약에 따라 reflection으로 연결한다. 조원 클래스 없이 팀장 핵심만 독립 컴파일하기 위한 선택이며 요청 처리에는 reflection을 사용하지 않는다. 모든 제품 소스를 함께 컴파일하면 실제 구현이 연결된다. 클래스명이나 생성자 오류가 실행 시 드러나는 한계가 있다.

## 7. Thread Pool과 Request Queue

```text
Client 송신 → main Listener → BoundedRequestQueue → Worker 10개 → SeatManager
                                             Worker → 해당 Client에 RESP
                                  대기자 인계 시 Worker → Notify Queue → Notifier → NOTIFY
```

Request Queue는 ArrayDeque와 ReentrantLock으로 직접 구현했다. Listener는 addLast, Worker는 removeFirst로 요청을 전달한다. Queue에 넣는 순서대로 꺼내지만 서로 다른 Worker의 처리 완료나 응답 송신 순서까지 보장하지는 않는다.

| 조건 | 동작 |
| --- | --- |
| Queue가 비어 있음 | Worker가 notEmpty.await로 대기 |
| Queue가 1,024건으로 가득 참 | Listener가 notFull.await로 대기하고 Worker가 공간을 만들면 재개 |
| 정상 close | 추가 적재를 막고 notEmpty/notFull의 모든 대기자를 깨움. 기존 Task는 유지 |
| close 후 잔여 작업 없음 | take가 null을 반환하여 Worker 종료 |
| 조건 재검사 | 깨어난 뒤 while로 재검사하여 여러 대기자와 허위 깨움을 처리 |

Queue Lock은 deque와 종료 플래그를 변경·조회하는 구간에만 사용한다. Worker는 Queue Lock을 해제한 뒤 좌석 Lock을 얻는다. Waitlist 등록 뒤 Client 배정을 기다리지 않고 WAITLISTED를 보내며 다음 Task를 처리한다.

고정 스레드와 제한 Queue는 생성 비용과 적재량을 제한하고, Condition은 sleep 반복 확인을 없앤다. 반면 Queue가 포화되면 단일 Listener의 다른 수신도 지연된다. 또한 느린 Client의 실제 소켓 송신 중에는 Worker가 대기할 수 있다. 이를 해결한다는 이유로 별도 송신 스레드나 자동 복구를 추가하지 않았다.

## 8. 동시성 제어와 다중 예약

### 8.1 임계구역

| 보호 대상 | 동기화 | 임계구역과 근거 |
| --- | --- | --- |
| 각 좌석 owner·waitlist | 좌석별 ReentrantLock | 상태 검사와 배정·해제·FIFO 등록·인계를 같은 Lock 안에서 수행하여 check-then-act 경쟁 방지 |
| MULTI 대상 좌석 | 대상 Lock 전체, 오름차순 획득 | 모든 EMPTY 확인부터 일괄 배정까지 다른 요청의 개입 방지 |
| Request Queue | Queue ReentrantLock + notEmpty/notFull | deque·종료 상태·현재/최대 크기 보호 |
| Notify Queue | Notifier ReentrantLock + available | 통지 전달·종료 상태와 빈 Queue 대기 보호 |
| 동일 연결 송신 | ClientConnection sendLock | Worker의 RESP와 Notifier의 NOTIFY 바이트가 서로 섞이는 것 방지 |
| Server 연결·응답 집계 | stateLock | 등록 중복 검사와 Client별 목표·합계 갱신을 함께 보호 |
| Server 실패·관측 값 | AtomicReference·volatile·stateLock | 첫 실패 원인 보존과 스레드 간 종료/진행 상태 가시성 확보 |
| Client held·pending·waiting | Client stateLock | 송신 후보 선택·pending 등록과 수신 상태 변경의 경쟁 방지 |

좌석별 Lock을 선택해 서로 다른 좌석 요청은 독립적으로 처리할 수 있다. Socket I/O는 좌석 Lock과 Queue Lock 밖에서 수행한다. MULTI 때문에 여러 좌석을 동시에 잠가야 하는 복잡성은 있지만 좌석 상태 전체를 단일 전역 Lock으로 직렬화하지 않는다.

Monitor는 각 좌석의 tryLock으로 상태를 복사하고 Lock을 얻지 못한 좌석은 미조회 상태로 표시한다. EMPTY로 간주하거나 무기한 대기하지 않는다. 실행 중 전체 조회와 통계는 원자적 단일 시점 snapshot이 아니며, 최종 상태는 Worker와 Monitor 종료 후 조회한다.

### 8.2 요청 판정

| 요청 | 조건 | 결과 및 상태 변경 |
| --- | --- | --- |
| RESERVE | EMPTY | SUCCESS, 요청자를 owner로 설정 |
| RESERVE | 이미 자신이 owner | FAIL / ALREADY_OWNER, 변경 없음 |
| RESERVE | 같은 좌석에 이미 자신이 대기 등록 | FAIL / ALREADY_WAITING, 원 대기 유지 |
| RESERVE | 타인이 owner, 자신은 미등록 | WAITLISTED / TAKEN, FIFO 끝에 등록 |
| RESERVE_MULTI | 유효한 서로 다른 2~4석 모두 EMPTY | SUCCESS, 모든 좌석 배정 |
| RESERVE_MULTI | 하나라도 점유 중 | FAIL / TAKEN, 배정·대기 등록 변경 없음 |
| RESERVE_MULTI | 개수 또는 중복 오류 | FAIL / BAD_MULTI, Lock 획득 전 거부 |
| 예약·취소 | 범위를 벗어난 좌석 | FAIL / BAD_SEAT, 변경 없음 |
| CANCEL | 자신이 owner | SUCCESS, 해제 후 대기자가 있으면 맨 앞 Client에 즉시 인계 |
| CANCEL | 자신이 owner가 아님 | FAIL / NOT_OWNER, 변경 없음 |

MULTI는 입력 좌석을 복사해 오름차순으로 정렬한 뒤 순서대로 Lock을 획득한다. 모든 대상의 owner가 0인지 검사하고, 하나라도 점유 중이면 어떤 좌석도 배정하지 않는다. 모두 비어 있을 때만 일괄 배정하며 finally에서 획득한 Lock을 역순으로 해제한다. MULTI는 Waitlist에 등록하지 않는다.

예를 들어 `[5,3]`과 `[3,5]`가 동시에 와도 두 요청 모두 3번 다음 5번을 잠근다. 모든 MULTI가 같은 순서를 사용하므로 좌석 Lock 사이의 순환 대기를 방지한다. 타임아웃이나 강제 해제로 교착을 숨기지 않는다. 다만 인기 좌석의 경합 자체를 없애거나 요청 처리의 공정성을 보장하는 방법은 아니다.

## 9. Waitlist·Condition Variable·Notifier

좌석마다 ArrayDeque로 대기자를 관리한다. owner가 다른 Client인 단일 예약은 해당 좌석 Lock 안에서 addLast로 등록하며 Client ID·원 요청 ID·등록 시각을 보관한다. 동일 Client의 중복 대기를 거부한다. FIFO의 기준은 실제 좌석 Lock 안에서 등록된 순서다.

CANCEL 성공 시 같은 좌석 Lock 안에서 기존 owner를 비우고 pollFirst로 대기자를 꺼내 즉시 새 owner로 지정한다. Worker는 Lock을 해제한 뒤 WaitNotice를 Notifier에 전달한다. 배정을 Notifier 송신 시점까지 미루지 않으므로 다른 예약이 인계 중인 좌석을 가져가지 않는다.

Notifier는 Notify Queue가 비어 있으면 available Condition에서 대기하고, 통지가 들어오면 깨어나 원 요청 ID의 NOTIFY를 보낸다. finish는 추가 통지를 막지만 잔여 통지는 유지한다. 정상 종료에서 Worker join 뒤 finish를 호출하여 마지막 Worker가 생성한 통지를 빠뜨리지 않는다. 실패 종료의 abort는 정상 finish와 달리 전송을 중단한다.

연결별 송신 Lock은 RESP·NOTIFY 한 메시지 전체를 직렬화한다. 부분 쓰기는 남은 바이트를 이어 보내고 write=0이면 연결별 write Selector에서 쓰기 준비를 기다린다. 이 Selector는 추가 스레드가 아니며, Listener의 Queue 적재나 OP_WRITE 처리에 의존하지 않는다. 따라서 Listener가 Queue 포화로 대기할 때 필요한 송신 재개를 Listener에게 맡기는 순환 의존을 피한다.

대기자에게는 RESP(WAITLISTED)보다 NOTIFY가 먼저 도착할 수도 있다. Client가 원 요청 상태로 이를 구분하며 첫 응답과 배정 통지를 별도로 처리한다. 종료 시 미해결 Waitlist는 강제로 배정하거나 오류로 바꾸지 않는다. 연결 단절에 대한 재접속·재전송은 제공하지 않는다.

## 10. Client 요청 생성과 상태 관리

### 10.1 요청 선택 정책

| 상황 | 선택 정책 |
| --- | --- |
| 보유 좌석 없음 | RESERVE 60%, RESERVE_MULTI 40% |
| 보유 좌석 있음 | RESERVE 30%, RESERVE_MULTI 20%, CANCEL 50% |
| CANCEL을 선택했으나 취소 후보 없음 | RESERVE 60% / RESERVE_MULTI 40%로 대체 |
| MULTI 후보 부족 | 가능한 2~4석으로 제한, 2석 미만이면 RESERVE로 대체 |
| 예약 좌석 선택 | 후보를 인기1~10 / 나머지로 나눠 인기 그룹을 80% 확률로 선택 |
| 선택한 그룹에 후보 없음 | 전체 가능한 후보에서 선택 |
| 인기 조건 판정 | CANCEL 1석·RESERVE 1석·MULTI의 모든 좌석을 포함한 실제 선택 수로 계산 |

예약 선택 확률 80%는 전체 인기 비율 80%를 보장하지 않는다. 취소는 실제 보유 좌석에서 선택하며 pending 제외나 후보 대체의 영향이 있다. 정식 실행의 목표 요청·첫 응답 완료 뒤 ClientMain이 전체 선택 수의 절반 이상인지 판정한다. 고정 seed나 실행 중 비율을 자동 조정하는 기능은 사용하지 않는다.

### 10.2 공유 상태와 응답 순서

| 상태 | 의미 및 처리 |
| --- | --- |
| held | SUCCESS 예약 또는 NOTIFY로 확인한 보유 좌석 |
| pending·busySeats | 첫 응답 미수신 요청과 좌석. 송신 전에 등록하고 새 요청 후보에서 제외 |
| waiting | WAITLISTED를 받은 원 요청. 이후 NOTIFY로 제거 |
| 취소 pending | 첫 응답 전에는 해당 좌석을 재예약하거나 다시 취소하지 않음 |
| 취소 SUCCESS / FAIL | SUCCESS면 보유 제거, FAIL이면 기존 보유 유지 |
| 중복 예약 FAIL | 기존 보유나 다른 원 요청의 대기 등록을 지우지 않음 |
| NOTIFY 선도착 | 보유를 먼저 반영하되 첫 WAITLISTED까지 busy 상태 유지. 뒤늦은 첫 응답으로 배정을 되돌리지 않음 |
| 첫 응답 후 WAITLISTED | pending 제한 해제. 배정을 기다리는 것 자체는 다음 송신을 막지 않음 |

같은 좌석의 첫 응답이 오기 전에 새 요청을 겹치지 않도록 하여 상태 전이의 복잡성을 줄였다. 수신은 송신과 별도로 계속 진행한다. 후보가 있는 동안에는 직전 응답을 기다리지 않고 다음 요청을 생성하지만, 100석 모두 pending이면 Client가 stateLock.wait로 조건 대기한다. 이 극단적인 경우까지 이전 응답을 기다리지 않는 조건을 무조건 충족한다고 주장하지 않는다. 모든 pending 대기의 실제 발생 여부와 영향은 실측 영역에서 별도로 판단한다.

이 선택은 단순한 상태 관리와 응답 순서 대응을 위한 것이다. 일반적인 좌석 version 체계나 모든 중첩 요청 순서의 처리를 추가하지 않았다. 그러한 대안을 실제 구현하다 실패했다는 이력은 확인된 자료 없이 작성하지 않는다.

## 11. 정상 종료·실패 종료·Monitor

Server는 RESP 전체 송신 성공 뒤 Client별 첫 응답 수를 한 번씩 증가시킨다. NOTIFY는 첫 응답 목표에 더하지 않는다. Client별 상한을 검사하므로 합계가 목표에 도달했다는 것은 모든 Client가 목표를 채웠다는 의미다.

정상 종료는 다음 순서로 진행한다.

```text
각 Client 첫 응답 목표 도달
→ Listener 입력 중단·select 깨움 / RequestQueue.close
→ 잔여 Task 처리·Worker 10개 join
→ Notifier.finish·잔여 통지 송신·Notifier join
→ 등록 Client에 BYE
→ Monitor stop·interrupt·join
→ 최종 좌석 조회·검사
→ 연결과 자원 정리
```

Listener.stop은 수신을 중단하고 등록된 연결은 BYE까지 유지한다. Queue가 비었다는 이유만으로 종료하거나 join을 생략하지 않는다. Client도 5,000건 송신을 마쳤다는 이유로 연결을 닫지 않고 모든 첫 응답과 Server의 BYE까지 수신한다. ClientMain은 Client의 송수신 종료를 기다린 뒤 전체 판정을 수행한다.

Monitor는 5초마다 좌석·Queue·누적 처리 수를 조회한다. Queue가 비어 있지 않고 마지막 첫 응답 송신 이후 30초 이상 진전이 없으면 같은 정지 구간에 한 번만 의심을 집계하며, 진행이 재개되면 다음 정지 구간을 새로 감시한다. 현재 화면은 누적 처리 건수이며 `완료 / 목표` 표시는 구현하지 않았다.

이것은 단순 처리 정지 감시로서 실제 교착을 확정하는 탐지기가 아니다. 네트워크 지연을 의심으로 볼 수 있고 Queue가 비어 있는 경우의 정지는 감지하지 못할 수 있다. 정교한 Lock 그래프·자동 복구·타임아웃 강제 해제는 추가하지 않았다.

실패 시 첫 원인을 보존하고 입력을 중단한다. Queue·Notifier의 조건 대기를 깨우고 Worker·Notifier를 중단하며 연결을 닫아 막힌 소켓 I/O를 해제한 뒤 스레드를 join한다. Connection.close는 sendLock 완료를 기다리지 않는다. 정상 Monitor.stop 뒤 대기를 해제하는 interrupt는 실패와 구분한다. 예상하지 않은 Worker·Notifier·Server 호출 스레드의 interrupt는 실패다.

## 12. 로그 명세와 기록 방식

### 12.1 Log 구현과 공통 형식

### 12.2 이벤트·상태·필드 명세

### 12.3 저장 위치·분석 방법·원본 보존

## 13. 검증과 실측 결과

### 13.1 기능·경쟁·종료 검사

| 검사 항목 | 방법 | 결과 |
| --- | --- | --- |
| 동일 좌석 경쟁 | | |
| 역순 MULTI | | |
| 일부 점유 MULTI 전체 실패 | | |
| FIFO 대기자 인계 | | |
| NOTIFY 선도착 | | |
| Queue 종료와 대기 해제 | | |
| 마지막 통지와 정상 종료 | | |
| 입력·연결·송신 실패 종료 | | |

### 13.2 로그 대조와 최종 정합성

| 확인 항목 | 근거 및 결과 |
| --- | --- |
| 이미 점유된 좌석의 중복 배정 없음 | |
| 배정 수 - 해제 수 = 최종 보유 좌석 수 | |
| Server 최종 owner = Client30개 최종 보유 목록 | |
| Client 간 보유 좌석 중복 없음 | |
| WAITLISTED = NOTIFY 수신 + 미해결 대기 | |
| 최종 정합성 판정 | |

### 13.3 정식 원격 실행 실측표

| Server 지표 | 측정값 |
| --- | --- |
| 전체 처리량(req/s) | |
| Request Queue 최대 길이(건) | |
| 이중예약(건) | |
| 처리 정지 의심(건) | |
| Waitlist 평균 대기시간(sec) | |
| Lock 경합(건) | |
| 최종 좌석 정합성 | |

| Client30개 합계 | 측정값 |
| --- | --- |
| 총 요청/첫 응답(건) | |
| SUCCESS(건/%) | |
| FAIL(건/%) | |
| WAITLISTED(건/%) | |
| NOTIFY 수신/미해결 대기(건) | |
| 평균 첫 응답 시간(ms) | |
| 인기 좌석 선택 수/전체 선택 수/비율 | |
| 실제 전송 간격·전체 pending 대기 관측 | |

### 13.4 실제 시행착오와 재확인 결과

## 14. 시연과 제출 구성

이번 제출에서는 정식 원격 실행을 촬영하고 그 실행의 소스·자료·결과를 함께 사용한다. 전체 실행 녹화를 5분 이내로 편집해 원격 Server, 로컬 Client30개의 접속·요청, MULTI·대기자 인계와 종료 결과를 설명한다. 기존 검증 자료나 축소 실행을 새 촬영 실행의 정식 결과로 섞지 않는다.

| 제출 파일 | 용도 |
| --- | --- |
| 전체 Java 소스 | Server·Client·common13개 파일, 촬영 실행과 동일한 구현 |
| Readme.txt | 본 문서의 설명과 별도 작성 영역을 완성한 최종 제출 설명서 |
| AllDefinedLogs.txt | |
| Server.txt·Client1.txt~Client30.txt | |
| download.txt | G2HW2.mp4의 다운로드 가능한 링크 |
| G2HW2.zip | 위 제출 파일을 묶은 최종 압축 파일 |

영상 링크의 다운로드·공유 권한·재생과 ZIP의 압축 해제를 확인한다. 검증용 증빙 ZIP은 최종 제출 ZIP과 다르다. PEM, JDK 바이너리, out의 class, 개발용 대역과 개인 세션은 제출물에서 제외한다. GitHub에는 코드와 README만 작업 브랜치·한글 PR로 반영하며 결과 자료·영상은 제출물로 별도 관리한다. 기본 브랜치 직접 반영과 자동 병합은 하지 않는다.

### 촬영용 콘솔 출력

서버 실행 시 `-Ddchw2.console=true`를 추가하면 INIT·CONNECT·MULTI의 LOCK 결과·최종 검사·종료 통계만 콘솔에도 표시합니다. Worker 이름, 요청 좌석, 결과와 실제 Lock 순서를 보여주며 긴 좌석 전이 상세는 파일에만 유지합니다. 기존 Monitor 요약은 그대로 출력됩니다. 옵션을 생략하면 추가 출력은 없습니다.

```text
java -Ddchw2.console=true -cp out cwnu.dchw2.server.Server 0.0.0.0 5000 20
```

위 명령은 촬영용 축소 실행입니다. `serverBalance=PASS`는 서버 내부 검사이며 Client 최종 목록 대조 결과와 구분합니다. 기존 정식 실행 로그를 보존하기 위해 별도 실행 폴더를 사용합니다.
