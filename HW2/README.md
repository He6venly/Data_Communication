# HW2 — Thread Pool 기반 실시간 좌석 예매 시스템

Java로 좌석 100개를 관리하는 원격 서버와 로컬 Client 30개를 구현합니다.
Protocol.java와 Interfaces.java는 팀장이 제공합니다. 각 담당은 담당 파트 전체를 독립적으로 구현·검증하고, 팀장이 결과를 받아 리팩토링·통합합니다.

## 개발 범위와 보고서 메모

- 학부 3인 프로젝트 규모로 시작하고, PDF에 명시된 주요 기능과 검증을 먼저 구현합니다.
- 정교한 Deadlock 탐지·자동 복구 같은 부수 기능은 초기 구현 범위에 넣지 않습니다. 필요성이 드러나면 팀장이 추가 시도 여부를 정합니다.
- 개선을 시도하다 복잡성이나 한계로 단순한 방법을 선택한 경우, 그 과정과 최종 선택의 이유를 보고서에 기록합니다.
- 기록은 **개선하려던 점 → 시도한 방법 → 발생한 문제 → 최종 선택과 이유 → 확인 결과** 순으로 작성합니다.
- 검토만 한 내용과 실제 구현·실험한 내용을 구분합니다. 아직 시도하지 않은 개선을 실패한 경험으로 미리 작성하지 않습니다.

### Client의 같은 좌석 중첩 요청 제한 — 보고서 메모

- **애로사항**: 같은 좌석에 예약·취소 요청을 겹쳐 보내면 RESP와 NOTIFY의 도착 순서에 따라 보유·대기 상태를 갱신하기 복잡해집니다. 모든 순서를 처리하는 상태 관리에는 구현·검증 부담이 있습니다.
- **선택한 방식**: 첫 응답을 기다리는 pending 좌석은 새 요청 후보에서 제외합니다. 100석 모두 pending일 때만 송신을 조건 대기하고, 응답 처리로 후보가 생기면 다시 보냅니다. 송신·수신은 별도 흐름으로 유지합니다.
- **대기 등록과 구분**: WAITLISTED 첫 응답을 받으면 pending 제한을 해제합니다. 좌석 배정을 기다리는 waitlist 때문에 송신을 멈추는 방식은 아닙니다.
- **선택 이유와 한계**: 학부 프로젝트 범위에서 상태 처리의 복잡성을 줄이는 선택입니다. 다만 모든 좌석이 pending이면 응답을 기다리므로, PDF의 이전 응답을 기다리지 않는 요청 생성 조건을 모든 상황에서 충족한다고 단정하지 않습니다.
- **보고서 작성**: 위 애로사항과 단순화 이유를 설명합니다. 중첩 요청 허용을 실제 구현하다 실패했다는 서술은 해당 시도·문제·변경 기록이 있을 때만 추가합니다. 전체 pending 대기의 발생 여부와 영향도 실측한 경우에만 결과로 적습니다.

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

총 13개 Java 파일로 구성합니다.
Request·Response는 Protocol 내부 일반 클래스, Task·Result·WaitNotice·조회용 데이터는 Interfaces 내부 일반 클래스입니다. Seat·WaitEntry는 SeatManager 내부에 둡니다. record·enum 없이 public final 필드와 숫자 상수·switch를 사용합니다.
설정·통계·종료·요청 생성은 관련 클래스의 메서드로 작성합니다.

## 파트 1 — 서버 핵심·통합 / 팀장

담당 패키지: `cwnu.dchw2.server`, 공통 계약은 `cwnu.dchw2.common`

- **Protocol.java**: 숫자 상수, 요청·응답 데이터, 메시지 인코딩·해석을 제공합니다.
- **Interfaces.java**: 파트 사이 메서드와 공유 데이터를 제공합니다. 변경은 팀장이 관리합니다.
- **Server.java**: 실행 인자로 주소·포트·개발용 요청 건수를 받고 서버 구성요소를 연결합니다. Worker 10개를 시작하고 누적 통계와 정상 종료를 관리합니다.
- **SeatManager.java**: 좌석 100개를 EMPTY로 초기화하고 좌석별 Lock·owner·FIFO waitlist를 관리합니다. 단일 예약, 취소, 다중 예약, 대기자 인계를 구현합니다.
- **BoundedRequestQueue.java**: 요청 FIFO Queue를 구현합니다. 빈 Queue와 가득 찬 Queue는 Condition Variable로 대기하고, 종료 시 대기자를 깨웁니다. 현재·최대 길이를 기록합니다.
- **Worker.java**: 10개 Worker가 요청을 꺼내 SeatManager에 전달합니다. 좌석 Lock 해제 후 응답·통지 적재·로그 기록을 수행합니다.
- **Notifier.java**: 통지 Queue와 CV를 관리합니다. 대기자에게 NOTIFY를 보내고 등록부터 통지 송신까지의 대기시간을 기록합니다.

통신 없이 요청 객체를 넣어 단일 예약·MULTI·FIFO부터 검사할 수 있습니다.
팀장이 메시지·데이터 타입·메서드 인자와 반환값·로그·종료 규약을 확정해 전달합니다. 각 파트의 결과를 받은 뒤 규약 준수 여부를 확인하고, 필요한 리팩토링·연결 수정과 전체 통합 검증을 수행합니다.

검증 기준:

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

- Client당 5,000건을 무작위 0.2~1.0초 간격으로 생성하며, 요청 후보가 있으면 이전 응답을 기다리지 않고 보냅니다. 100석 모두 pending일 때의 예외는 위 보고서 메모를 따릅니다.
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

검증 기준:

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

검증 기준:

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

- JDK 17 기준, Java 표준 라이브러리를 사용합니다. 공통 코드만 컴파일하는 명령은 HW2 폴더에서 다음과 같습니다.

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

HW2 폴더에서 전체 소스를 컴파일하고 실행하는 예시는 다음과 같습니다.

```powershell
$sources = Get-ChildItem -LiteralPath src -Recurse -Filter '*.java' | ForEach-Object { $_.FullName }
javac --release 17 -encoding UTF-8 -d out $sources
java -cp out cwnu.dchw2.server.Server 0.0.0.0 12345 10
```

`bindHost`·포트·요청 수는 예시 실행 인자이며 코드에 고정하지 않습니다. Server.main은 `Log(String, Path)`, `Listener(ServerContext, RequestQueue, Logger, String, int)`, `Monitor(ServerContext, RequestQueue, Seats, Logger)`를 기존 규약 그대로 찾습니다. 구성 초기화 실패와 Logger.close 실패도 종료 코드 1로 처리합니다.

## 계측과 결과 해석 기준

실제 처리 경로에서 이미 owner가 있는 좌석에 대한 재배정 시도를 검사하고 배정·해제·대기 등록을 집계합니다. MULTI는 입력을 검사한 뒤 오름차순으로 Lock을 획득하고 역순 finally 해제를 수행합니다. CANCEL 인계는 같은 좌석 Lock 안에서 해제 1·배정 1로 계산합니다. tryLock의 최초 실패만 경합 1회로 세며 snapshot 읽기 실패는 Worker 경합에 더하지 않습니다.

Result.detail에는 좌석별 sequence·owner 전후·대기 인원 전후를 담고 MULTI는 `clientId:requestId` transaction과 Lock 순서를 함께 담습니다. Worker는 Lock 밖에서 이를 기록합니다. 검증에서는 로그 출력 순서에 기대지 않고 sequence로 전이를 재생하여 계측·최종 owner와 대조합니다. 실행 중 snapshot과 여러 통계 카운트는 서로 다른 시점의 값일 수 있으며 원자적 전체 스냅샷으로 주장하지 않습니다.

서버 종료 로그는 내부 수지를 `serverBalance=PASS/FAIL`, 실제 Client 대조를 `clientCrossCheck=UNVERIFIED`로 따로 표시합니다. NOTIFY 성공 송신 수는 실제 Client 수신 수와 같은 검증이 아닙니다. 실제 Client 30명의 종료 목록·통지 수신 로그 대조 전에는 과제 전체의 최종 정합성 PASS를 선언하지 않습니다. Logger.close 실패는 이미 적힌 종료 로그와 별도로 stderr 및 실패 반환/종료 코드에 남습니다.

진입점 reflection은 조원 클래스가 없는 상태에서 독립 컴파일을 가능하게 하려는 선택입니다. 클래스명·생성자 오류가 실행 시 드러나는 한계가 있으므로 연결·실패 경로를 검증해야 합니다.
