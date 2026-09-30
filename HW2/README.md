# HW2 — Thread Pool 기반 실시간 좌석 예매 시스템

Java로 좌석 100개를 관리하는 원격 서버와 로컬 Client 30개를 구현합니다.
현재는 구현 전 설계입니다. 아래 파일과 공통 규약을 기준으로 각 파트를 병행 개발합니다.

## 파일 구성

기본 패키지는 `cwnu.dchw2`이며, 하위 파트는 `server`, `client`, `common`입니다.

```text
HW2/
├─ README.md
└─ src/cwnu/dchw2/
   ├─ server/
   │  ├─ Server.java
   │  ├─ SeatManager.java
   │  ├─ RequestQueue.java
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
      └─ Log.java
```

12개 파일로 시작합니다. Seat·WaitEntry·Result는 SeatManager 내부 작은 클래스,
Request·Response는 Protocol 내부 작은 클래스로 둡니다.
설정·통계·종료·요청 생성은 관련 클래스의 메서드로 작성합니다.

## 파트 1 — 서버 핵심·통합 / 본인

담당 패키지: `cwnu.dchw2.server`

- **Server.java**: 실행 인자로 주소·포트·개발용 요청 건수를 받고 서버 구성요소를 연결합니다. Worker 10개를 시작하고 누적 통계와 정상 종료를 관리합니다.
- **SeatManager.java**: 좌석 100개를 EMPTY로 초기화하고 좌석별 Lock·owner·FIFO waitlist를 관리합니다. 단일 예약, 취소, 다중 예약, 대기자 인계를 구현합니다.
- **RequestQueue.java**: 요청 FIFO Queue를 구현합니다. 빈 Queue와 가득 찬 Queue는 Condition Variable로 대기하고, 종료 시 대기자를 깨웁니다. 현재·최대 길이를 기록합니다.
- **Worker.java**: 10개 Worker가 요청을 꺼내 SeatManager에 전달합니다. 좌석 Lock 해제 후 응답·통지 적재·로그 기록을 수행합니다.
- **Notifier.java**: 통지 Queue와 CV를 관리합니다. 대기자에게 NOTIFY를 보내고 등록부터 통지 송신까지의 대기시간을 기록합니다.

통신 없이 요청 객체를 넣어 단일 예약·MULTI·FIFO부터 검사할 수 있습니다.
통합할 때 조원 3과 Queue 입력·송신 완료 기준을, 조원 2와 예약 결과·종료 신호를 확인합니다.

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
- 인기 좌석 1~10번에 예약 선택 확률 80%로 시작합니다. CANCEL과 MULTI 개수까지 포함한 실제 좌석 선택 비율을 집계해 절반 이상 조건을 확인합니다.

Client 상태:

- 보유 좌석 Set, 진행 중 요청 Map, 대기 요청 Map으로 시작하고 공유 상태는 짧은 synchronized 구간으로 보호합니다.
- 전송 전 pending에 등록하고 같은 좌석의 첫 응답이 오기 전에는 겹치는 요청을 만들지 않습니다.
- 취소 pending 좌석은 재예약·중복 취소 후보에서 제외합니다. 취소 SUCCESS면 보유 제거, FAIL이면 유지합니다.
- NOTIFY가 WAITLISTED보다 먼저 오면 배정 완료를 먼저 기록합니다. 뒤늦은 WAITLISTED로 상태를 되돌리지 않고 첫 응답 집계는 별도로 합니다.
- 선도착 NOTIFY의 첫 응답을 받기 전에는 그 좌석을 취소하지 않습니다.
- 이미 보유·대기 중인 좌석의 단일 재예약 FAIL은 정상 결과입니다. FAIL 때문에 기존 보유나 원 대기 등록을 지우지 않습니다.
- 모든 좌석에 대기 등록되었다는 이유로 송신을 멈추지 않습니다. 대기 등록은 원 요청 ID로 유지합니다.

합의한 RESP·NOTIFY 예제로 상태 갱신을 먼저 검사하고 공통 Log를 독립적으로 작성할 수 있습니다.
로그 호출 형식·파일 닫기 책임은 전원에게 공유합니다.

완료 확인:

- Client별 5,000건 송신·첫 응답 집계, NOTIFY 별도 집계.
- 응답·통지 순서가 바뀌어도 보유 상태 유지.
- BYE까지 연결을 유지하고 최종 보유 좌석 기록.
- Server/Client 로그가 공통 형식을 따르고 여러 스레드 기록이 섞이지 않음.

## 파트 3 — TCP 통신·Protocol·Monitor / 조원 3

담당 패키지: `cwnu.dchw2.server`, 메시지 규약은 `cwnu.dchw2.common`

- **Protocol.java**: 공통 요청·응답 데이터와 한 줄 인코딩·파싱을 작성합니다. 각 메시지의 사용 예제를 본인과 조원 2에게 공유합니다.
- **Listener.java**: NIO Selector 하나로 accept·다중 연결 수신·줄 분리·요청 Queue 적재를 수행합니다. 좌석 예약을 직접 판정하지 않습니다.
- **ClientConnection.java**: 연결·Client ID·수신 버퍼·송신 Lock을 관리합니다. 메시지 전체가 전송된 후 반환하고 부분 쓰기와 write=0을 처리합니다.
- **Monitor.java**: 5초마다 전체 좌석 현황·Queue 길이·누적 처리 수를 출력합니다. Queue에 요청이 있는데 30초간 처리 진전이 없으면 Deadlock 의심을 기록합니다.

좌석 기능 없는 echo로 접속·메시지 분할/병합·부분 쓰기를 먼저 검사할 수 있습니다.
본인과 RequestQueue.put·SeatManager.snapshot·통계 조회를 연결하고 원격 접속 확인을 지원합니다.

완료 확인:

- 서버 연결별 수신 스레드를 만들지 않고 Listener 1개로 30개 연결 처리.
- 메시지가 나뉘거나 붙어 와도 정확하게 파싱.
- Worker와 Notifier의 동시 송신이 섞이지 않음.
- 같은 처리 정지 구간은 1건으로 집계하고 정상 진행 후 다시 멈추면 새 구간으로 기록.
- 감시는 네트워크 지연도 감지할 수 있으며 실제 Deadlock 확정이나 강제 해제 기능은 아님.

## 공통 작업 규약

### 메시지와 연결 메서드

- UTF-8, 한 줄에 한 메시지, 줄바꿈으로 구분합니다.
- HELLO로 Client ID를 등록하고 요청 ID는 Client별 1부터 증가합니다.
- 응답 순서는 요청 순서라고 가정하지 않습니다.
- 요청당 첫 응답 1개, NOTIFY는 원 대기 요청 ID를 사용하는 별도 이벤트입니다.

| 방향 | 형식 | 의미 |
| --- | --- | --- |
| Client → Server | `HELLO clientId` | Client 등록 |
| Client → Server | `RESERVE reqId seat` | 단일 예약 |
| Client → Server | `RESERVE_MULTI reqId seat1,seat2,...` | 2~4석 예약 |
| Client → Server | `CANCEL reqId seat` | 본인 좌석 취소 |
| Server → Client | `RESP reqId status seats reason` | 첫 응답 |
| Server → Client | `NOTIFY reqId seat` | 원 대기 요청의 좌석 배정 |
| Server → Client | `BYE` | 정상 종료 |

- status: SUCCESS, FAIL, WAITLISTED.
- seats: 요청 좌석을 쉼표로 구분.
- reason: OK, TAKEN, ALREADY_OWNER, ALREADY_WAITING, NOT_OWNER, BAD_SEAT, BAD_MULTI.
- 숫자·명령 자체를 파싱할 수 없는 입력은 기록 후 연결 종료. 범위·MULTI 개수·중복 오류는 FAIL.
- Request는 Client ID·요청 ID·명령·좌석 목록을 담습니다.
- Result는 첫 응답과 선택적 통지 대상·원 요청 ID·좌석·등록 시각을 담습니다.

파트 간 메서드:

| 연결 | 메서드 | 계약 |
| --- | --- | --- |
| Listener → RequestQueue | `put(Task)` | Request와 ClientConnection을 묶어 적재 |
| RequestQueue → Worker | `take()` | 빈 Queue는 CV 대기, 종료 후 잔여 요청도 없으면 null |
| Worker → SeatManager | `handle(Request)` | Socket·파일 I/O 없이 Result 반환 |
| Worker/Notifier → ClientConnection | `send(String line)` | 줄바꿈까지 전체 송신 완료 후 반환, 실패는 IOException |
| Monitor → SeatManager | `snapshot()` | 좌석별 Lock으로 읽은 복사본 반환 |
| 모든 파트 → Log | `write(event, status, message)` | 공통 형식으로 한 줄 기록. 생성 시 노드 이름·파일 지정 |

메서드와 데이터 형태를 먼저 공유하되, 공통 필드를 바꿀 때는 관련 담당과 확인합니다.

### Lock과 스레드

- Server의 main을 Listener로 사용하고 Worker 10개·Notifier 1개·Monitor 1개를 둡니다.
- 요청·연결별 서버 스레드나 로그·송신 전용 스레드를 추가하지 않습니다. Client 송수신 스레드는 별개입니다.
- owner와 waitlist는 해당 좌석 Lock 안에서만 접근합니다. Monitor도 snapshot을 사용합니다.
- MULTI는 입력 검사 후 오름차순 Lock 획득, 모두 비어 있을 때 일괄 배정, finally에서 역순 해제합니다.
- Request Queue 용량은 1,024. 포화 시 notFull, 비어 있으면 notEmpty Condition에서 while 조건 검사로 대기합니다.
- Queue Lock을 놓고 좌석 Lock을 획득합니다. Socket·파일 I/O는 좌석 Lock 밖에서 수행합니다.
- ClientConnection은 송신 Lock으로 메시지 전체를 직렬화합니다. NIO write=0을 바쁜 무한 반복으로 처리하지 않습니다.

### 로그·통계·종료

```text
[HH:MM:SS.mmm] NODE | EVENT | STATUS | message
```

- UTC 로그, 경과시간은 같은 노드의 monotonic clock으로 측정합니다.
- Server.txt, Client1.txt~Client30.txt에 Client ID·요청 ID·좌석·결과를 기록합니다.
- STATUS는 SUCCESS/FAIL/INFO/WARN. WAITLISTED는 WAITLIST 이벤트의 WARN으로 기록합니다.
- INIT, CONNECT, RESERVE, RESERVE_MULTI, CANCEL, LOCK, WAITLIST, NOTIFY, POOL, DOUBLE_BOOKING_CHECK, TERMINATE와 추가 감시·오류 이벤트를 명세에 정리합니다.
- 대기자 인계는 해제 1 + 배정 1, MULTI 성공은 좌석 수만큼 배정합니다.
- 최대 Queue 길이는 변경 시 갱신하고 Lock 경합은 최초 tryLock 실패 시 1회 집계합니다.
- 처리량은 첫 Client 연결~마지막 첫 응답 송신, 응답시간은 Client 송신~첫 응답 수신, 대기시간은 Server 등록~NOTIFY 송신으로 측정합니다.
- 정상 종료는 Client별 첫 응답 5,000건·합계 150,000건 확인 후 남은 요청·통지까지 처리합니다.
- Worker join → Notifier 잔여 통지 전송·join → BYE → 최종 기록·Monitor 종료·Socket/Log 정리 순서를 지킵니다. Queue 비움만 보고 종료하지 않습니다.
- CV 대기자를 깨우고 Listener의 select를 해제할 수 있어야 합니다.
- 종료 시 미해결 Waitlist를 별도 기록합니다. 연결 단절·송신 실패는 실패 실행으로 남기고 원인 수정 후 새 실행합니다.

### 공동 검증과 협업

- Protocol 예제와 Result 형태를 확인한 뒤 각 파트의 작은 테스트를 병행합니다.
- Client 1개의 단일 예약이 실제 TCP로 왕복할 때 첫 통합하고 MULTI·Waitlist·종료를 붙입니다.
- 같은 좌석 경쟁, [5,3] vs [3,5], 일부 점유된 MULTI, FIFO 인계, NOTIFY 선도착, 마지막 통지 후 종료를 확인합니다.
- 배정 검사와 카운트를 실제 처리 경로에 두고 이중예약·Deadlock 0건을 확인합니다.
- 배정 수 - 해제 수 = 최종 예약 좌석 수.
- Server 최종 owner = Client 30명의 최종 보유 목록, Client 간 중복 소유 없음.
- WAITLISTED 수 = NOTIFY 수신 수 + 종료 시 미해결 대기 수.
- 로컬 축소 실행 후 원격 서버 + 로컬 Client 30개로 정식 실행합니다.
- 필수 지표는 처리량·평균 첫 응답 시간·Queue 최대 길이·이중예약 수·정지 감시 수·Waitlist 평균 대기시간·Lock 경합 수·최종 정합성입니다.
- 각자 담당 기능의 테스트·설명을 작성하고 실제 겪은 시행착오만 선택 → 문제 → 변경 → 재확인 결과로 기록합니다.

### 실행 환경과 제출

- Java 표준 라이브러리 중심으로 작성하고 JDK 버전·컴파일 방법을 통일합니다.
- 주소·포트와 개발용 요청 건수는 실행 인자로 지정합니다. 실제 명령은 구현 후 추가합니다.
- GitHub에는 코드와 README만 관리하며 개인 세션·PDF·실행 로그·영상은 로컬 보관합니다.
- 다른 담당 파일 수정이나 공통 계약 변경은 먼저 공유합니다.
- 제출 ZIP은 전체 소스, AllDefinedLogs.txt, 같은 원격 정식 실행의 Server.txt·Client1.txt~Client30.txt, Readme.txt, 영상 링크의 download.txt를 포함합니다.
- 시연 영상은 5분 이내이며, 실행 방법과 실측 결과는 검증 후 README에 추가합니다.
