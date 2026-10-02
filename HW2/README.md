# HW2 — Thread Pool 기반 실시간 좌석 예매 시스템

Java로 좌석 100개를 관리하는 원격 서버와 로컬 Client 30개를 구현합니다.
Protocol.java와 Interfaces.java를 팀장이 제공하며, 팀장 담당 Server·SeatManager·BoundedRequestQueue·Worker·Notifier와 파트 2 담당 ClientMain·Client·Log의 구현·독립 검증을 완료했습니다. Listener·ClientConnection·Monitor는 파트 3 담당이 구현합니다. 각 담당은 담당 파트 전체를 독립적으로 구현·검증하고, 팀장이 결과를 받아 리팩토링·통합합니다.

## 개발 범위와 보고서 메모

- 학부 3인 프로젝트 규모로 시작하고, PDF에 명시된 주요 기능과 검증을 먼저 구현합니다.
- 정교한 Deadlock 탐지·자동 복구 같은 부수 기능은 초기 구현 범위에 넣지 않습니다. 필요성이 드러나면 팀장이 추가 시도 여부를 정합니다.
- 개선을 시도하다 복잡성이나 한계로 단순한 방법을 선택한 경우, 그 과정과 최종 선택의 이유를 보고서에 기록합니다.
- 기록은 **개선하려던 점 → 시도한 방법 → 발생한 문제 → 최종 선택과 이유 → 확인 결과** 순으로 작성합니다.
- 검토만 한 내용과 실제 구현·실험한 내용을 구분합니다. 아직 시도하지 않은 개선을 실패한 경험으로 미리 작성하지 않습니다.

## 파일 구성

기본 패키지는 `cwnu.dchw2`이며, 하위 파트는 `server`, `client`, `common`입니다.

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
      ├─ Protocol.java       # 팀장 제공
      ├─ Interfaces.java     # 팀장 제공
      └─ Log.java
```

공통 인터페이스 파일 하나를 추가해 총 13개 Java 파일로 구성합니다. 현재 소스는 공통 코드 2개·팀장 서버 핵심 5개·파트 2 Client/Log 3개이며, 나머지 통신/Monitor 3개는 파트 3 구현 예정입니다.
Request·Response는 Protocol 내부 일반 클래스, Task·Result·WaitNotice·조회용 데이터는 Interfaces 내부 일반 클래스입니다. Seat·WaitEntry는 SeatManager 내부에 둡니다. record·enum 없이 public final 필드와 숫자 상수·switch를 사용합니다.
설정·통계·종료·요청 생성은 관련 클래스의 메서드로 작성합니다.

## 파트 1 — 서버 핵심·통합 / 팀장

담당 패키지: `cwnu.dchw2.server`, 공통 계약은 `cwnu.dchw2.common`

- **Protocol.java — 제공 완료**: 숫자 상수, 요청·응답 데이터, 메시지 인코딩·해석을 제공합니다.
- **Interfaces.java — 제공 완료**: 파트 사이 메서드와 공유 데이터를 제공합니다. 변경은 팀장이 관리합니다.
- **Server.java**: 실행 인자로 주소·포트·개발용 요청 건수를 받고 서버 구성요소를 연결합니다. Worker 10개를 시작하고 누적 통계와 정상 종료를 관리합니다.
- **SeatManager.java**: 좌석 100개를 EMPTY로 초기화하고 좌석별 Lock·owner·FIFO waitlist를 관리합니다. 단일 예약, 취소, 다중 예약, 대기자 인계를 구현합니다.
- **BoundedRequestQueue.java**: 요청 FIFO Queue를 구현합니다. 빈 Queue와 가득 찬 Queue는 Condition Variable로 대기하고, 종료 시 대기자를 깨웁니다. 현재·최대 길이를 기록합니다.
- **Worker.java**: 10개 Worker가 요청을 꺼내 SeatManager에 전달합니다. 좌석 Lock 해제 후 응답·통지 적재·로그 기록을 수행합니다.
- **Notifier.java**: 통지 Queue와 CV를 관리합니다. 대기자에게 NOTIFY를 보내고 등록부터 통지 송신까지의 대기시간을 기록합니다.

통신 없이 요청 객체를 넣어 단일 예약·MULTI·FIFO부터 검사할 수 있습니다.
팀장이 메시지·데이터 타입·메서드 인자와 반환값·로그·종료 규약을 확정해 전달합니다. 각 파트의 결과를 받은 뒤 규약 준수 여부를 확인하고, 필요한 리팩토링·연결 수정과 전체 통합 검증을 수행합니다.

완료 확인:

- 같은 좌석의 이중예약 없음.
- MULTI는 2~4석, 오름차순 Lock, 전부 성공 또는 전부 실패.
- 취소 시 FIFO 맨 앞 Client에게 Lock 안에서 바로 인계.
- Worker가 Waitlist 때문에 멈추지 않고 마지막 요청·통지까지 처리 후 종료.

## 파트 2 — Client·공통 로그 / 조원 2

담당 패키지: `cwnu.dchw2.client`, 공통 로그는 `cwnu.dchw2.common`

- **ClientMain.java**: 로컬 Client 30개를 실행하고 전체 종료를 기다립니다.
- **Client.java**: 각 Client의 TCP 연결 1개를 유지합니다. 요청 생성·송신과 응답·NOTIFY 수신을 별도 흐름으로 처리하고 보유 좌석·대기·진행 중 요청을 관리합니다. 응답시간과 최종 보유 목록을 기록합니다.
- **Log.java**: Server와 Client가 함께 사용하는 파일 로거를 작성합니다. 공통 형식·시간대·스레드 간 기록 직렬화·파일 닫기를 구현하고 다른 담당에게 사용 예제를 제공합니다.

요청 생성:

- Client당 5,000건을 무작위 0.2~1.0초 간격으로 보내며 이전 응답을 기다리지 않습니다.
- 미보유 시 RESERVE 60% / MULTI 40%, 보유 시 RESERVE 30% / MULTI 20% / CANCEL 50%로 시작합니다.
- CANCEL은 응답·통지로 보유를 확인했고 pending이 아닌 좌석에서 선택합니다. 후보가 없으면 예약 요청을 보냅니다.
- MULTI는 2~4석을 중복 없이 선택합니다.
- 인기 좌석 1~10번에 예약 선택 확률 80%로 시작합니다. CANCEL과 MULTI 개수까지 포함한 실제 좌석 선택 비율을 집계해 절반 이상 조건을 확인하고, 조정이 필요하면 팀장에게 결과를 보고합니다.

Client 상태:

- 보유 좌석 Set, 진행 중 요청 Map, 대기 요청 Map으로 시작하고 공유 상태는 짧은 synchronized 구간으로 보호합니다.
- 전송 전 pending에 등록하고 같은 좌석의 첫 응답이 오기 전에는 겹치는 요청을 만들지 않습니다.
- 취소 pending 좌석은 재예약·중복 취소 후보에서 제외합니다. 취소 SUCCESS면 보유 제거, FAIL이면 유지합니다.
- NOTIFY가 WAITLISTED보다 먼저 오면 배정 완료를 먼저 기록합니다. 뒤늦은 WAITLISTED로 상태를 되돌리지 않고 첫 응답 집계는 별도로 합니다.
- 선도착 NOTIFY의 첫 응답을 받기 전에는 그 좌석을 취소하지 않습니다.
- 이미 보유·대기 중인 좌석의 단일 재예약 FAIL은 정상 결과입니다. FAIL 때문에 기존 보유나 원 대기 등록을 지우지 않습니다.
- 모든 좌석에 대기 등록되었다는 이유로 송신을 멈추지 않습니다. 대기 등록은 원 요청 ID로 유지합니다.

팀장이 전달한 RESP·NOTIFY 예제로 상태 갱신을 먼저 검사하고, 지정한 로그 형식에 따라 공통 Log를 작성합니다.
로거 사용 예제를 전원에게 공유합니다. 로그 호출 형식·파일 닫기 책임을 바꿀 필요가 있으면 팀장에게 제안합니다.

완료 확인:

- Client별 5,000건 송신·첫 응답 집계, NOTIFY 별도 집계.
- 응답·통지 순서가 바뀌어도 보유 상태 유지.
- BYE까지 연결을 유지하고 최종 보유 좌석 기록.
- Server/Client 로그가 공통 형식을 따르고 여러 스레드 기록이 섞이지 않음.

## 파트 3 — TCP 통신·Monitor / 조원 3

담당 패키지: `cwnu.dchw2.server`

팀장이 제공한 Protocol·Interfaces를 사용합니다. 공통 규약·데이터·인터페이스 작성은 조원 3의 담당에서 제외합니다.

- **Listener.java**: NIO Selector 하나로 accept·다중 연결 수신·줄 분리·요청 Queue 적재를 수행합니다. 좌석 예약을 직접 판정하지 않습니다.
- **ClientConnection.java**: 연결·Client ID·수신 버퍼·송신 Lock을 관리합니다. 메시지 전체가 전송된 후 반환하고 부분 쓰기와 write=0을 처리합니다.
- **Monitor.java**: 5초마다 전체 좌석 현황·Queue 길이·누적 처리 수를 출력합니다. Queue에 요청이 있는데 30초간 처리 진전이 없으면 Deadlock 의심을 기록합니다.

좌석 기능 없는 echo로 접속·메시지 분할/병합·부분 쓰기를 먼저 검사할 수 있습니다.
RequestQueue·Seats·ServerContext 계약에 맞춰 연결하고 원격 접속 확인을 지원합니다.

완료 확인:

- 서버 연결별 수신 스레드를 만들지 않고 Listener 1개로 30개 연결 처리.
- 메시지가 나뉘거나 붙어 와도 정확하게 파싱.
- Worker와 Notifier의 동시 송신이 섞이지 않음.
- 같은 처리 정지 구간은 1건으로 집계하고 정상 진행 후 다시 멈추면 새 구간으로 기록.
- 감시는 네트워크 지연도 감지할 수 있으며 실제 Deadlock 확정이나 강제 해제 기능은 아님.

## 공통 작업 규약

팀장이 다음 규약을 정해 전달합니다. 각 담당은 구현 중 문제나 변경 필요성을 팀장에게 보고하고, 공통 규약 변경은 팀장이 확정·전달한 뒤 반영합니다. 담당 파일 내부의 구현 방법은 규약을 지키는 범위에서 각 담당이 정합니다.

### 메시지와 연결 메서드

- UTF-8, 한 줄에 한 메시지, 줄바꿈으로 구분합니다.
- HELLO로 Client ID를 등록하고 요청 ID는 Client별 1부터 증가합니다.
- 응답 순서는 요청 순서라고 가정하지 않습니다.
- 요청당 첫 응답 1개, NOTIFY는 원 대기 요청 ID를 사용하는 별도 이벤트입니다.

| 방향 | 형식 | 의미 |
| --- | --- | --- |
| Client → Server | `1000 clientId` | Client 등록 |
| Client → Server | `1001 reqId seat` | 단일 예약 |
| Client → Server | `1002 reqId seat1,seat2,...` | 2~4석 예약 |
| Client → Server | `1003 reqId seat` | 요청자 소유 좌석 취소 |
| Server → Client | `2000 reqId status seats reason` | 첫 응답 |
| Server → Client | `2001 reqId seat` | 원 대기 요청의 좌석 배정 |
| Server → Client | `2002` | 정상 종료 |

- status: SUCCESS=3000, FAIL=3001, WAITLISTED=3002. 코드에서는 Protocol 상수 이름을 사용합니다.
- seats: 요청 좌석을 쉼표로 구분하고 원 순서를 유지합니다. 빈 목록은 `-`이며 0석 MULTI는 BAD_MULTI로 FAIL입니다.
- Protocol.encode 메서드는 줄바꿈을 붙이지 않습니다. 실제 송신 담당이 LF를 한 번 붙입니다.
- reason: OK, TAKEN, ALREADY_OWNER, ALREADY_WAITING, NOT_OWNER, BAD_SEAT, BAD_MULTI.
- 숫자·명령 자체를 파싱할 수 없는 입력은 기록 후 연결 종료. 범위·MULTI 개수·중복 오류는 FAIL.
- Request는 Client ID·요청 ID·명령·좌석 목록을 담습니다. 예약 메시지의 Client ID는 Listener가 등록된 연결에서 붙입니다.
- HELLO는 첫 메시지로 한 번 전송하며 별도 응답은 없습니다. Client ID는 1~30, 요청 ID는 각 연결에서 1부터 증가합니다. 재등록·중복 접속·증가하지 않는 요청 ID는 규약 오류입니다.
- Result는 첫 응답과 선택적 통지 대상·원 요청 ID·좌석·등록 시각을 담습니다.

파트 간 계약은 [Interfaces.java](src/cwnu/dchw2/common/Interfaces.java)에 실제 Java interface로 제공됩니다.

| 구현 클래스 | 구현할 interface | 주요 책임 |
| --- | --- | --- |
| Server | `ServerContext` | 연결 등록·조회, 첫 응답·통지·정지 감시 집계, 실패 전달 |
| BoundedRequestQueue | `RequestQueue` | put/take/close/snapshot |
| SeatManager | `Seats` | handle/snapshot/metrics |
| ClientConnection | `Connection` | clientId/bindClientId/send/close |
| Notifier | `Notifications` | submit/finish/run |
| Listener, Monitor | `Stoppable` | run/stop |
| Log | `Logger` | write/close |

메서드의 반환값·예외·종료 조건은 소스 주석을 따릅니다. 각 담당은 상대 구현 클래스 대신 위 interface를 생성자 인자로 받아 임시 대역으로도 확인할 수 있습니다.

```java
import cwnu.dchw2.common.Interfaces.Result;
import cwnu.dchw2.common.Interfaces.Task;
import cwnu.dchw2.common.Protocol;
import cwnu.dchw2.common.Protocol.Request;

// Listener의 수신 처리: 연결 등록과 완성된 줄 조립이 끝난 뒤
Request request = Protocol.decodeRequest(line, connection.clientId());
queue.put(new Task(request, connection));

// Worker의 처리: 여기의 queue/seats/notifier/server/log는 제공된 interface 타입
Task task = queue.take();
if (task != null) {
    Result result = seats.handle(task.request);
    if (result.notice != null) {
        notifier.submit(result.notice);
    }
    task.connection.send(Protocol.encodeResponse(result.response));
    server.recordFirstResponse(task.request.clientId);
    log.write(Protocol.commandName(task.request.command), "INFO", result.detail);
}
```

위 코드는 연결 흐름 예시입니다. 실제 run에서는 반복, 예외 처리, 요청·응답 로그를 추가합니다. IOException·InterruptedException 등 실패는 ServerContext.reportFailure로 전달합니다.

생성자 형태는 다음으로 맞춥니다.

```text
Listener(ServerContext server, RequestQueue queue,
         Logger log, String bindHost, int port)
ClientConnection(SocketChannel channel)
Monitor(ServerContext server, RequestQueue queue,
        Seats seats, Logger log)
Log(String node, Path file) throws IOException
```

Protocol만 사용하는 Client 예시:

```java
import cwnu.dchw2.common.Protocol;
import cwnu.dchw2.common.Protocol.Request;
import cwnu.dchw2.common.Protocol.Response;
import java.util.List;

Request request = new Request(
    7, 12, Protocol.RESERVE, List.of(42)
);
String line = Protocol.encodeRequest(request); // "1001 12 42"
// pending 등록·송신 시각 기록 후, Client 송신 담당이 LF를 붙여 전송

Response reply = Protocol.decodeResponse("2000 12 3002 42 TAKEN");
switch (reply.type) {
    case Protocol.RESP:
        // reply.requestId로 pending을 찾아 첫 응답과 상태 처리
        break;
    case Protocol.NOTIFY:
        // 원 예약 요청 번호로 배정 처리. 첫 응답 건수에는 포함하지 않음
        break;
    case Protocol.BYE:
        // 최종 목록 기록·정상 종료
        break;
}
```

Server의 판정에는 Protocol.response(request, status, reason), Notifier에는 Protocol.notification(requestId, seat), 종료에는 Protocol.bye()를 사용하면 됩니다.

메서드와 데이터 형태는 팀장이 확정해 전달합니다. 공통 필드나 메서드를 바꿀 필요가 있으면 팀장에게 제안하고, 확정된 변경을 관련 담당에게 전달한 뒤 반영합니다.

### Lock과 스레드

- Server의 main을 Listener로 사용하고 Worker 10개·Notifier 1개·Monitor 1개를 둡니다.
- 요청·연결별 서버 스레드나 로그·송신 전용 스레드를 추가하지 않습니다. Client 송수신 스레드는 별개입니다.
- owner와 waitlist는 해당 좌석 Lock 안에서만 접근합니다. Monitor의 snapshot은 좌석별 tryLock을 사용하며 못 읽은 좌석은 readable=false, ownerId/waitingCount=-1로 표시합니다. 최종 상태는 Worker 종료 후 조회합니다.
- MULTI는 입력 검사 후 오름차순 Lock 획득, 모두 비어 있을 때 일괄 배정, finally에서 역순 해제합니다.
- Request Queue 용량은 1,024. 포화 시 notFull, 비어 있으면 notEmpty Condition에서 while 조건 검사로 대기합니다.
- Queue Lock을 놓고 좌석 Lock을 획득합니다. Socket·파일 I/O는 좌석 Lock 밖에서 수행합니다.
- ClientConnection은 송신 Lock으로 메시지 전체를 직렬화합니다. NIO write=0을 바쁜 무한 반복으로 처리하지 않습니다. 쓰기 준비 대기는 Listener의 Queue 적재 완료에 의존하지 않습니다.

### 로그·통계·종료

```text
[HH:MM:SS.mmm] NODE | EVENT | STATUS | message
```

- UTC 로그, 경과시간은 같은 노드의 monotonic clock으로 측정합니다.
- Java 시간 형식은 `HH:mm:ss.SSS`로 지정합니다. 노드 이름은 `SERVER`, `CLIENT1`~`CLIENT30`, 저장 위치는 실행 폴더의 `logs/Server.txt`, `logs/Client1.txt`~`logs/Client30.txt`입니다. Log 생성자가 필요한 상위 폴더를 생성합니다.
- Server.txt, Client1.txt~Client30.txt에 Client ID·요청 ID·좌석·결과를 기록합니다.
- STATUS는 SUCCESS/FAIL/INFO/WARN. WAITLISTED는 WAITLIST 이벤트의 WARN으로 기록합니다.
- INIT, CONNECT, RESERVE, RESERVE_MULTI, CANCEL, LOCK, WAITLIST, NOTIFY, POOL, DOUBLE_BOOKING_CHECK, TERMINATE와 추가 감시·오류 이벤트를 명세에 정리합니다.
- 대기자 인계는 해제 1 + 배정 1, MULTI 성공은 좌석 수만큼 배정합니다.
- 최대 Queue 길이는 변경 시 갱신하고 Lock 경합은 최초 tryLock 실패 시 1회 집계합니다.
- 처리량은 첫 Client 연결~마지막 첫 응답 송신, 응답시간은 Client 송신~첫 응답 수신, 대기시간은 Server 등록~NOTIFY 송신으로 측정합니다.
- 정상 종료는 Client별 첫 응답 5,000건·합계 150,000건 확인 후 남은 요청·통지까지 처리합니다.
- 입력 중단·RequestQueue.close → Worker join → Notifier.finish·잔여 통지 전송·join → BYE → Monitor 중단·join·최종 기록 → Socket/Log 정리 순서를 지킵니다. Queue 비움만 보고 종료하지 않습니다.
- Listener.stop은 수신과 Selector 대기만 끝내며 등록된 연결은 BYE까지 유지합니다. Notifier.finish는 정상 실행에서 Worker join 후 호출합니다.
- CV 대기자를 깨우고 Listener의 select를 해제할 수 있어야 합니다.
- 종료 시 미해결 Waitlist를 별도 기록합니다. 연결 단절·송신 실패는 실패 실행으로 남기고 원인 수정 후 새 실행합니다.

요청·응답 로그의 message에는 `clientId`, `requestId`, `seats`, `result`를 공통 이름으로 기록합니다. 좌석은 공백 없는 쉼표 목록, 빈 목록은 `-`입니다. 요청 seats는 원 순서를 유지하고 최종 보유 목록만 오름차순으로 정렬합니다. 요청 전송·수신은 result=REQUEST, 첫 응답은 SUCCESS/FAIL/WAITLISTED, 통지는 NOTIFY로 기록합니다. 추가 필드는 뒤에 붙일 수 있습니다.

```text
[12:00:00.000] CLIENT7 | RESERVE | INFO | clientId=7 requestId=12 seats=42 result=REQUEST
[12:00:00.015] CLIENT7 | WAITLIST | WARN | clientId=7 requestId=12 seats=42 result=WAITLISTED reason=TAKEN
[12:00:01.000] CLIENT7 | NOTIFY | SUCCESS | clientId=7 requestId=12 seats=42 result=NOTIFY
[12:00:02.000] CLIENT7 | TERMINATE | INFO | clientId=7 heldSeats=3,5,42
```

Client 종료 시 최종 보유 목록과 미해결 대기 수를 각각 기록합니다. Server는 최종 owner를 `seat=42 ownerId=7` 형식으로 좌석 1~100번 순서로 남기며 EMPTY는 ownerId=0입니다. 위 시각과 좌석은 형식 예시이며 실측 결과가 아닙니다.

### 독립 구현과 팀장 통합

- 팀장이 메시지·데이터 필드·메서드 이름·인자·반환값·예외·종료 조건을 지정해 전달합니다.
- 각 담당은 자기 파트 전체를 구현합니다. 상대 파트가 필요한 부분은 지정된 인터페이스의 임시 대역이나 입력 예제로 검증할 수 있습니다.
- 팀장은 Protocol·Interfaces와 서버 핵심, 조원 2는 Client 전체와 Log, 조원 3은 Listener·ClientConnection·Monitor를 구현합니다. 조원에게 공통 규약·인터페이스 작성은 배정하지 않습니다.
- 조원은 담당 소스와 함께 실행·검증 방법, 확인한 결과, 남은 문제를 전달합니다.
- 조원 2는 예제 RESP·NOTIFY를 수신 처리에 넣어 정상 예약·취소, 취소 FAIL, WAITLISTED, NOTIFY 선도착을 확인합니다. 송신과 무관하게 수신 상태를 검사할 수 있도록 처리 메서드를 나눕니다. Protocol·Interfaces 외 서버 구현이 없어도 임시 서버로 TCP 송수신을 확인할 수 있습니다.
- 조원 3은 임시 RequestQueue·ServerContext·Seats·Logger로 완성된 줄의 Queue 적재, 분할/병합 수신, 같은 연결의 동시 송신을 확인합니다. Monitor는 정상 진행·정지 구간당 1회 집계·진행 재개 후 새 정지·stop 후 종료를 확인합니다.
- 임시 대역은 확인용이며 정상 종료 신호·첫 응답 집계 등 공통 계약을 지킵니다. 최종 프로그램 구성에서는 제외합니다.
- 팀장이 파트별 결과를 받아 공통 인터페이스에 맞게 리팩토링·통합하고 실제 TCP 전체 동작을 검증합니다.
- 담당 내부 구현은 자유롭게 정하되, 공통 규약 변경이 필요하면 팀장에게 보고합니다.
- 같은 좌석 경쟁, [5,3] vs [3,5], 일부 점유된 MULTI, FIFO 인계, NOTIFY 선도착, 마지막 통지 후 종료를 확인합니다.
- 배정 검사와 카운트를 실제 처리 경로에 두고 이중예약·Deadlock 0건을 확인합니다.
- 배정 수 - 해제 수 = 최종 예약 좌석 수.
- Server 최종 owner = Client 30명의 최종 보유 목록, Client 간 중복 소유 없음.
- WAITLISTED 수 = NOTIFY 수신 수 + 종료 시 미해결 대기 수.
- 로컬 축소 실행 후 원격 서버 + 로컬 Client 30개로 정식 실행합니다.
- 필수 지표는 처리량·평균 첫 응답 시간·Queue 최대 길이·이중예약 수·정지 감시 수·Waitlist 평균 대기시간·Lock 경합 수·최종 정합성입니다.
- 각자 담당 기능의 테스트·설명을 작성하고 실제 겪은 시행착오만 선택 → 문제 → 변경 → 재확인 결과로 기록합니다.

### 실행 환경과 제출

- JDK 17 기준, Java 표준 라이브러리를 사용합니다. 현재 제공된 공통 코드만 컴파일하는 명령은 HW2 폴더에서 다음과 같습니다.

```text
javac --release 17 -encoding UTF-8 -d out src/cwnu/dchw2/common/Protocol.java src/cwnu/dchw2/common/Interfaces.java
```

- 팀장 핵심 코드는 조원 클래스 없이도 컴파일됩니다. Server.main은 아래 지정된 생성자의 조원 클래스를 reflection으로 연결합니다. reflection은 진입점 구성에만 사용하며 요청 처리에는 사용하지 않습니다. 조원 클래스가 없으면 클래스 누락을 표시하고 종료 코드 1로 끝납니다. out의 class 파일과 실행 로그는 GitHub에 올리지 않습니다.

```text
javac --release 17 -encoding UTF-8 -Xlint:all -d out src/cwnu/dchw2/common/Protocol.java src/cwnu/dchw2/common/Interfaces.java src/cwnu/dchw2/server/Server.java src/cwnu/dchw2/server/SeatManager.java src/cwnu/dchw2/server/BoundedRequestQueue.java src/cwnu/dchw2/server/Worker.java src/cwnu/dchw2/server/Notifier.java
```
- Server와 ClientMain의 실행 인자 순서는 다음으로 고정합니다. 세 인자를 모두 받으며 주소·포트·개발용 요청 수를 소스에 고정하지 않습니다.

```text
Server <bindHost> <port> <client당 요청 수>
ClientMain <serverHost> <port> <client당 요청 수>
```

- Server의 bindHost는 수신할 로컬 인터페이스 주소, ClientMain의 serverHost는 접속할 서버 주소입니다. Client 수는 30개, Worker 수는 10개로 고정하고 요청 수만 축소할 수 있습니다. 포트는 1~65535, 요청 수는 양수로 검사합니다.
- 같은 실행의 Server와 ClientMain에는 동일한 포트와 Client당 요청 수를 지정합니다. 정식 실행의 요청 수는 5000이며 개발용은 10 등 작은 값으로 지정할 수 있습니다. 요청 수는 전체 합계가 int 범위를 넘지 않는 양수로 검사합니다.
- GitHub에는 코드와 README만 관리하며 개인 세션·PDF·실행 로그·영상은 로컬 보관합니다.
- 다른 담당 파일 수정은 해당 담당에게 공유합니다. 공통 계약 변경은 팀장에게 제안하고 팀장이 확정·전달한 내용만 반영합니다.
- 제출 ZIP은 전체 소스, AllDefinedLogs.txt, 같은 원격 정식 실행의 Server.txt·Client1.txt~Client30.txt, Readme.txt, 영상 링크의 download.txt를 포함합니다.
- 시연 영상은 5분 이내이며, 실행 방법과 실측 결과는 검증 후 README에 추가합니다.

## 팀장 핵심의 연결 방법

공통 인터페이스의 이름·메서드·메시지 형식은 유지했습니다. 구현 `RequestQueue.java`를 용량 제한을 드러내는 `BoundedRequestQueue.java`로 변경해 interface `RequestQueue`와의 이름 충돌을 없앴습니다. `Interfaces.java`는 Request·Response import만 정리했으며, 나머지 중첩 타입도 각 소스 상단에서 명시적으로 import해 본문에는 단순 이름을 사용합니다. 조원 코드는 공통 interface 생성자를 그대로 쓰며, 구현 객체를 직접 만들 때만 `new BoundedRequestQueue(...)`로 변경합니다.

| 클래스 | 생성자 또는 연결 메서드 | 책임 |
| --- | --- | --- |
| Server | `Server(int requestsPerClient, Logger log)` | 실제 SeatManager·BoundedRequestQueue·Worker 10개·Notifier 연결 |
| Server | `Server(int requestsPerClient, Logger log, Seats seats)` | 독립 검증에서 Seats 대역 주입 |
| Server | `queue()`, `seats()` | Listener·Monitor에 전달할 interface 반환 |
| Server | `run(Stoppable listener, Stoppable monitor)` | 호출 스레드에서 Listener 실행, 모든 정리 후 성공 여부 반환. Logger 닫기 책임도 Server가 소유 |
| Server | `failure()`, `statistics()` | 첫 실패 원인과 Client별 응답 수·통지 수·처리량·평균 대기시간·정지 감시 집계 조회 |
| SeatManager | `SeatManager()` | EMPTY 좌석 100개와 좌석별 ReentrantLock·FIFO ArrayDeque 초기화 |
| BoundedRequestQueue | `BoundedRequestQueue()` | 용량 1024, notEmpty/notFull Condition 대기, close 후 잔여 drain |
| BoundedRequestQueue | `BoundedRequestQueue(int capacity)` | 포화 검증용 작은 용량 지정 |
| Worker | `Worker(RequestQueue queue, Seats seats, Notifications notifier, ServerContext server, Logger log)` | 요청 처리·통지 적재·첫 응답 송신·로그 |
| Notifier | `Notifier(ServerContext server, Logger log)` | 통지 Queue와 Condition, 성공 송신 후 대기시간 집계 |

`Server.run`은 한 번만 호출합니다. 정상 종료는 `RequestQueue.close`로 Worker를 깨우고 잔여 요청을 처리합니다. Worker join 후 `Notifier.finish`를 호출하며 Notifier join은 진행 중 send와 마지막 로그 기록까지 기다립니다. 그 뒤 BYE를 보내고 Monitor를 stop·interrupt·join한 다음 최종 좌석을 검사하고 자원을 닫습니다. Queue가 비었거나 첫 응답 카운트에 도달했다는 이유만으로 join을 생략하지 않습니다.

Monitor가 stop 후 대기를 해제하기 위한 `InterruptedException`을 해당 Monitor 스레드에서 reportFailure로 전달하면 정상 종료로 구분합니다. 예상하지 않은 Worker·Notifier·호출 스레드 interrupt는 실패입니다. 실패 시 입력을 닫고 대기자를 깨우며 등록 연결을 닫아 막힌 송신을 해제하고 실행 스레드를 join합니다. Connection.close는 송신 완료를 기다리는 방법으로 구현하면 실패 종료가 막히므로 실제 소켓을 닫아 send가 반환하도록 해야 합니다. 실패한 실행은 자동 재접속·재전송하지 않습니다.

조원 클래스가 준비되면 HW2 폴더에서 전체 소스를 컴파일하고 실행합니다. 아래 명령은 연결 방법이며 실제 TCP 전체 실행은 아직 검증하지 않았습니다.

```powershell
$sources = Get-ChildItem -LiteralPath src -Recurse -Filter '*.java' | ForEach-Object { $_.FullName }
javac --release 17 -encoding UTF-8 -d out $sources
java -cp out cwnu.dchw2.server.Server 0.0.0.0 12345 10
```

`bindHost`·포트·요청 수는 예시 실행 인자이며 코드에 고정하지 않습니다. Server.main은 `Log(String, Path)`, `Listener(ServerContext, RequestQueue, Logger, String, int)`, `Monitor(ServerContext, RequestQueue, Seats, Logger)`를 기존 규약 그대로 찾습니다. 구성 초기화 실패와 Logger.close 실패도 종료 코드 1로 처리합니다.

## 파트 2 구현·실행·독립 검증 결과

`ClientMain.java`, `Client.java`, `Log.java`를 구현했습니다. Protocol·Interfaces·팀장 서버 핵심과 파트 3 담당 파일은 변경하지 않았습니다.

ClientMain은 인자 검사 후 Client 30개와 각 Client의 Logger를 준비합니다. Client의 `run`이 수신을 맡고 별도 스레드 하나가 요청을 보냅니다. 먼저 종료한 Client를 종료 Queue로 확인하므로 Client 번호와 관계없이 실패를 감지해 전체 연결·대기를 해제합니다. 정상 종료와 실패 모두 송수신 스레드 종료를 기다린 뒤 Log를 닫습니다. 실패 시 종료 코드는 1입니다.

Client는 첫 응답 전 pending에 등록하고 좌석을 다른 요청에서 제외합니다. 모든 좌석이 pending일 때만 상태 변경을 기다립니다. waitlist 등록은 송신을 막지 않으며 재예약 FAIL도 원 대기 요청을 지우지 않습니다. 선도착 NOTIFY는 보유에 반영하되 첫 WAITLISTED까지 해당 좌석의 pending을 유지해 취소를 막습니다. 응답시간은 요청 로그 기록 후 실제 송신을 시작하는 시점부터 첫 RESP 수신까지 `System.nanoTime()` 차이로 계산합니다. NOTIFY는 첫 응답 건수·평균 응답시간에 포함하지 않습니다.

BYE까지 연결을 유지하며 송신 완료만으로 연결을 닫지 않습니다. 종료 로그에 오름차순 보유 목록, 원 요청 ID별 미해결 대기, 송신·첫 응답·성공·실패·WAITLISTED·NOTIFY·pending 수, 평균 응답시간(ms), 명령별 요청 수, CANCEL과 MULTI 개수를 포함한 실제 인기 좌석 선택 비율을 남깁니다. 조기 BYE·BYE 없는 연결 단절·알 수 없거나 중복된 응답·소켓/로그 오류는 실패입니다. 인기 좌석 비율이 절반 미만이면 `popularCondition=BELOW_HALF`로 보고하며 확률을 임의 변경하지 않습니다.

파트 2만 컴파일하려면 HW2 폴더에서 다음을 실행합니다. 표준 라이브러리만 사용합니다.

```powershell
javac --release 17 -encoding UTF-8 -Xlint:all -d out src/cwnu/dchw2/common/Protocol.java src/cwnu/dchw2/common/Interfaces.java src/cwnu/dchw2/common/Log.java src/cwnu/dchw2/client/Client.java src/cwnu/dchw2/client/ClientMain.java
```

파트 3 통합 후 서버를 먼저 실행하고 별도 터미널에서 Client를 실행합니다. 같은 실행의 포트·요청 수를 맞춥니다.

```powershell
java -cp out cwnu.dchw2.client.ClientMain 127.0.0.1 12345 10
# 정식 원격 실행: 실제 서버 주소와 같은 포트 사용, Client당 요청 수는 5000
java -cp out cwnu.dchw2.client.ClientMain <serverHost> <port> 5000
```

마지막 줄의 `<serverHost>`·`<port>`는 설명용 자리표시자입니다. 실제 값으로 바꿔 실행합니다. 파일은 실행 폴더의 `logs/Client1.txt`~`logs/Client30.txt`이며 같은 파일로 새 실행하면 이전 내용을 초기화합니다. 이전 실행을 보관하려면 실행 폴더를 구분하거나 실행 전 logs 폴더를 복사합니다.

연결·확인용 메서드는 다음과 같습니다. 추가 데이터 파일 없이 Client 내부 일반 클래스로 조회 값을 제공합니다.

| 메서드 | 사용·책임 |
| --- | --- |
| `Client(int clientId, String host, int port, int requestsPerClient, Logger log)` | ClientMain이 생성. 번호 1~30, 주소·포트·요청 수 검사 |
| `run()` | 연결 1개, 수신 흐름, 송신 스레드 시작·종료. 한 번만 호출 |
| `failure()` | 실패 원인 조회. 정상 종료면 null |
| `abort(Throwable cause)` | 실패 설정·소켓 닫기·송신 interrupt·상태 대기 해제 |
| `snapshot()` | 상태 Lock 안에서 보유·대기·집계를 불변 목록과 Snapshot으로 복사 |
| `prepareRequest()`, `handleResponse(Response)` | 같은 client 패키지의 독립 검증에서 요청 생성과 예제 응답 처리를 확인하는 경로 |

공통 Log 사용 예제입니다. `Log(String node, Path file)`은 폴더를 생성하고 UTF-8 파일을 열며, 각 write를 직렬화해 UTC `HH:mm:ss.SSS` 시각으로 기록하고 flush합니다. message의 CR/LF는 공백으로 바꿉니다. close는 중복 호출 가능하며 close 후 write는 IOException입니다. I/O 오류를 숨기지 않으므로 호출자가 실행 실패를 처리해야 합니다.

```java
import cwnu.dchw2.common.Log;
import cwnu.dchw2.common.Interfaces.Logger;
import java.nio.file.Path;

// 독립 사용: 생성한 코드가 닫는다.
try (Logger log = new Log("CLIENT7", Path.of("logs", "Client7.txt"))) {
    log.write("RESERVE", "INFO", "clientId=7 requestId=12 seats=42 result=REQUEST");
}
// Server.run에 전달한 Logger는 Server가 닫는다.
// Client 생성자에 전달한 Logger는 ClientMain이 송수신 종료 후 닫는다.
```

Windows의 JDK 21.0.12.1에서 `--release 17 -encoding UTF-8 -Xlint:all` 컴파일 경고·오류 0건과 독립 검증 20개가 통과했습니다. 임시 검증 소스·대역·결과는 로컬 `Sol Session/verification`에만 보관합니다. 정상 소스 목록·GitHub 업로드에는 포함하지 않습니다.

| 구분 | 실제 확인 범위 | 결과 |
| --- | --- | --- |
| 예제 응답·실제 Client 처리 경로 | 단일 예약, MULTI 2~4석·중복 제외, 정상 취소·취소 FAIL | 성공 좌석 반영, MULTI FAIL·취소 FAIL 시 기존 보유 유지 |
| 예제 응답·실제 Client 처리 경로 | WAITLISTED→NOTIFY, NOTIFY→WAITLISTED, 재예약 FAIL | 원 요청 ID로 연결, 통지 별도 집계, 보유·원 대기 보존, 선도착 좌석 취소 차단 |
| 요청 생성·상태 대기 | 첫 응답 미수신 상태의 추가 요청·역순 응답·100석 pending·100석 waitlist | pending 좌석 겹침 없음, 전 pending 시 대기·첫 응답 후 해제, 전 waitlist라도 계속 송신 |
| 실제 Log | 8개 스레드가 500줄씩 기록, JVM 기본 시간대 Asia/Seoul | 4,000줄 유실·섞임·중복 0, UTC·UTF-8·CR/LF 치환·폴더 생성·닫기 확인 |
| 임시 TCP 서버 + 실제 Client | 첫 RESP를 두 번째 요청 뒤로 지연, 역순·분할·병합 응답 | 응답 대기 없이 요청 2건 송신, 정확한 수신·BYE 후 종료 |
| 실제 팀장 Server·Worker·Notifier·Seats·Queue + 임시 통신/Monitor + 실제 ClientMain | 30명×20건, HELLO·연속 요청 ID·송신 간격·분할 응답·BYE·로그 30개 | 송신 600·첫 응답 600·pending 0, 모든 Client 정상 종료 |
| 위 축소 TCP 실행의 실제 로그 대조 | CANCEL·MULTI 포함 좌석 선택, Server owner와 Client 보유, WAITLIST 수지 | 전체 선택 982석 중 인기 739석(75.25%), 통지 63·미해결 119·최종 보유 18석, Client 간 중복 0·Server owner 일치 |
| 별도 JVM 실패 검증 | 인자 오류 8종, 접속 거절, Client30 조기 BYE, 로그 생성 실패 | 종료 코드 1, 다른 Client의 read·sleep 해제·전체 종료, 남은 송신 스레드 0 |
| 미검증 | 파트 3 실제 Listener/ClientConnection/Monitor, 원격 30×5000, JDK 17 런타임·Linux | 팀장 통합 후 확인 필요 |

위 실측 수치는 한 번의 축소 실행 결과이며 무작위 요청이므로 새 실행에서 달라집니다. 임시 통신은 검증 목적으로 연결별 수신 스레드를 사용했습니다. 파트 3의 Selector 1개 처리·부분 쓰기·write=0 대기·Monitor 감시 구현을 검증한 결과가 아닙니다. 정식 150,000건 완료나 과제 전체 검증 완료로 해석하지 않습니다.

검증 중 Windows JVM의 기본 콘솔 인코딩으로 출력한 한글을 검증 코드가 UTF-8로 읽어 실패했습니다. 실제 Log 파일은 이미 명시적 UTF-8이었으며, 검증 JVM의 콘솔 인코딩을 UTF-8로 지정한 뒤 검증 20개를 통과했습니다. 자동 재접속·재전송이나 정교한 교착 탐지 실험은 수행하지 않았습니다.

## 팀장 핵심의 실제 구현·검증 결과와 한계

Windows의 JDK 21.0.6에서 `javac --release 17 -encoding UTF-8 -Xlint:all` 컴파일 경고·오류 0건, 핵심 독립 검증 22개와 별도 JVM 진입점 검증 8개가 통과했습니다. 이는 팀장 핵심 구현과 대역 연결 결과이며 원격 정식 부하의 실측 결과가 아닙니다. 검증 소스와 임시 대역은 로컬 `Sol Session/verification`에 보관하고 GitHub에는 팀장 소스 5개·Interfaces.java의 import 정리·이 README의 변경만 반영합니다.

| 구분 | 실제 확인 범위 | 결과 |
| --- | --- | --- |
| 팀장 실제 구현 | EMPTY·예약·본인 재예약·중복 대기·비소유자 취소·잘못된 입력 | 공통 판정표 일치 |
| 팀장 실제 구현 | 같은 좌석 Client 30명 동시 예약, 이어서 전체 FIFO 인계·해제 | SUCCESS 1·WAITLISTED 29, 배정 30·해제 30·남은 owner 0·이중예약 0 |
| 팀장 실제 구현 | [5,3] 대 [3,5] 동시 MULTI 200회 | 회당 SUCCESS 1·FAIL 1, Lock 순서 3,5·원 요청 순서 유지·교착에 의한 중단 없음 |
| 팀장 실제 구현 | 부분 점유된 [5,3,8] MULTI·4석 성공 | 실패 시 빈 좌석과 기존 owner 불변·대기 등록 없음, 성공 시 4석 배정 |
| 팀장 실제 구현 | Queue 1024개 FIFO, 포화 producer·빈 consumer 10개·close·interrupt | CV 대기와 해제, 잔여 drain, 추가 put 거부, 최대 길이 유지 |
| 팀장 실제 구현 | 좌석별 tryLock snapshot·잘못된 MULTI의 Lock 전 거절 | 읽지 못한 좌석은 -1/false, 잘못된 입력은 점유 Lock을 기다리지 않음 |
| 팀장 실제 구현 + 연결/Logger 대역 | Worker send·로그 시점, NOTIFY 선도착, Notifier finish 후 통지 20개 | 좌석 Lock 해제 후 I/O, 원 대기 requestId 유지, 첫 응답과 통지 별도 집계 |
| Server + Client/연결/Listener/Monitor/Logger 대역 | Client 30명×2건, 마지막 CANCEL의 통지·마지막 Worker 로그를 latch로 지연 | Worker 정확히 10개, 응답 60·통지 1, 모두 완료·join 후 각 Client에 마지막 BYE, 최종 검사 시 Worker 종료 확인 |
| 위 정상 대역 실행 | 서버 수지와 대역 보유 목록 대조 | 배정 30−해제 1=보유 29, WAITLISTED 1=통지 1+미해결 0, owner 일치 |
| 실패 주입 대역 실행 | RESP·NOTIFY·요청/INIT 로그 실패, Listener 조기 반환, 예상 밖 interrupt, 막힌 send | 실패 반환·대기 해제·등록 연결/로그 닫기·스레드 종료, BYE로 성공 표시하지 않음 |
| 별도 JVM + 조원 클래스명 대역 | main 연결, 인자 오류·합계 overflow·클래스 누락·Monitor 초기화/Logger.close 실패 | 정상 종료 코드 0, 실패 종료 코드 1, 초기화 실패 시 Logger 정리 |
| 미검증 | 실제 TCP·NIO 부분 쓰기·실제 Client 상태/로그·Monitor 5초 감시·원격 30×5000 실행·JDK 17 런타임/Linux 실행 | 조원 코드 통합과 실제 실행 환경에서 확인 필요 |

실제 처리 경로에서 이미 owner가 있는 좌석에 대한 재배정 시도를 검사하고 배정·해제·대기 등록을 집계합니다. MULTI는 입력을 검사한 뒤 오름차순으로 Lock을 획득하고 역순 finally 해제를 수행합니다. CANCEL 인계는 같은 좌석 Lock 안에서 해제 1·배정 1로 계산합니다. tryLock의 최초 실패만 경합 1회로 세며 snapshot 읽기 실패는 Worker 경합에 더하지 않습니다.

Result.detail에는 좌석별 sequence·owner 전후·대기 인원 전후를 담고 MULTI는 `clientId:requestId` transaction과 Lock 순서를 함께 담습니다. Worker는 Lock 밖에서 이를 기록합니다. 독립 검증은 로그 출력 순서에 기대지 않고 sequence로 전이를 재생하여 계측·최종 owner와 대조했습니다. 실행 중 snapshot과 여러 통계 카운트는 서로 다른 시점의 값일 수 있으며 원자적 전체 스냅샷으로 주장하지 않습니다.

서버 종료 로그는 내부 수지를 `serverBalance=PASS/FAIL`, 실제 Client 대조를 `clientCrossCheck=UNVERIFIED`로 따로 표시합니다. NOTIFY 성공 송신 수는 실제 Client 수신 수와 같은 검증이 아닙니다. 실제 Client 30명의 종료 목록·통지 수신 로그 대조 전에는 과제 전체의 최종 정합성 PASS를 선언하지 않습니다. Logger.close 실패는 이미 적힌 종료 로그와 별도로 stderr 및 실패 반환/종료 코드에 남습니다.

진입점 reflection은 조원 클래스가 없는 상태에서 독립 컴파일을 가능하게 하려는 선택입니다. 클래스명·생성자 오류가 실행 시 드러나는 한계가 있어 별도 JVM 대역으로 연결·실패 경로를 확인했습니다. 자동 복구나 정교한 교착 탐지 실험은 수행하지 않았습니다.
