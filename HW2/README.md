# HW2 — Thread Pool 기반 실시간 좌석 예매 시스템

Java 콘솔 프로그램으로 원격 서버의 좌석 100개를 로컬 Client 30개가 예약·취소합니다.
현재는 구현 전 설계이며, 아래 파일 이름과 공통 규약을 기준으로 분업합니다.
각 담당이 자기 코드를 설명하고 테스트할 수 있는 규모로 작성합니다.

## 필수 기능

- 원격 서버 1개, 로컬 Client 30개, Client별 TCP 연결 1개.
- 시작 시 Worker 정확히 10개 생성. Listener 1개, Notifier 1개, Monitor 1개 사용.
- 좌석별 Lock과 owner·FIFO waitlist. 전체 좌석을 하나의 Lock으로 처리하지 않음.
- RESERVE, CANCEL, 2~4석 RESERVE_MULTI. MULTI는 오름차순 Lock과 전부 성공/실패.
- Request Queue와 Notify Queue는 Condition Variable로 대기·깨우기.
- Worker는 좌석이 날 때까지 대기하지 않음.
- Client당 5,000건, 총 150,000건, 무작위 0.2~1.0초 간격. 응답을 기다리지 않고 다음 요청 전송.
- 요청 좌석의 절반 이상을 일부 인기 좌석에 집중. 최종 로그는 원격 구성에서 수집.
- 요청·응답·통지 로그, 5초 POOL 출력, 간단한 처리 정지 감시, 최종 정합성 검사.

## 파일 구성

```text
HW2/
├─ README.md
└─ src/g2hw2/
   ├─ common/
   │  ├─ Protocol.java
   │  └─ Log.java
   ├─ server/
   │  ├─ Server.java
   │  ├─ SeatManager.java
   │  ├─ RequestQueue.java
   │  ├─ Worker.java
   │  ├─ Notifier.java
   │  ├─ Listener.java
   │  ├─ ClientConnection.java
   │  └─ Monitor.java
   └─ client/
      ├─ ClientMain.java
      └─ Client.java
```

12개 파일로 시작합니다. 작은 Seat·WaitEntry·Result는 SeatManager 내부 클래스,
Request·Response는 Protocol 내부 클래스로 둡니다.
설정·통계·종료·요청 생성은 관련 클래스의 메서드로 작성합니다.

## 담당 파트와 파일

| 담당 | 파일 | 책임 |
| --- | --- | --- |
| 본인: 서버 핵심·통합 | Server.java | 구성 조립, Worker 10개 시작, 통계 집계, 종료 조정 |
| 본인 | SeatManager.java | 좌석 100개, 좌석별 Lock, 단일·다중 예약, 취소, FIFO 인계 |
| 본인 | RequestQueue.java | 요청 FIFO Queue, CV 대기·깨우기, 용량·최대 길이·종료 |
| 본인 | Worker.java | 요청 꺼내기 → 좌석 처리 → Lock 해제 후 통지 적재·응답·로그 |
| 본인 | Notifier.java | 통지 Queue와 CV, NOTIFY 송신, 대기시간 기록 |
| 조원 2: Client | ClientMain.java | 로컬 Client 30개 시작과 전체 종료 대기 |
| 조원 2 | Client.java | 요청 생성, 송신·수신, 보유·대기·pending 관리, 응답시간·최종 로그 |
| 조원 3: 통신·로그·관측 | Protocol.java | 메시지 데이터, 한 줄 인코딩·파싱 |
| 조원 3 | Log.java | 공통 로그 형식, 스레드 간 기록 직렬화 |
| 조원 3 | Listener.java | 단일 NIO Selector로 accept·수신·줄 분리·Queue 적재 |
| 조원 3 | ClientConnection.java | 연결·Client ID·입력 버퍼, 송신 Lock, 메시지 전체 전송 |
| 조원 3 | Monitor.java | 5초 좌석·Queue·처리량 출력, 처리 정지 감시 |
| 공동 | README·담당 기능 테스트 | 메시지 합의, 실제 TCP 통합, 최종 검증·원격 실행·제출 점검 |

본인이 서버 동시성을 소유하고 조원 3은 좌석 상태를 직접 변경하지 않습니다.
조원 2는 Server 구현에 의존하지 않고 합의한 응답 예제로 Client를 개발합니다.
각자 자신의 테스트 결과와 실제 시행착오를 설명에 반영합니다.

## 공통 규약

### 1. 실행과 파일 관리

- Java 표준 라이브러리 중심으로 작성. 외부 서버 프레임워크·DB·GUI는 사용하지 않음.
- 패키지는 g2hw2.common, g2hw2.server, g2hw2.client.
- JDK 버전과 컴파일 방법은 각자 환경을 확인해 하나로 통일하고 README에 기록.
- 주소·포트, 개발용 요청 건수는 실행 인자로 받음. 세부 실행 명령은 구현 후 추가.
- GitHub에는 코드와 README를 관리. 개인 세션·PDF·실행 로그·영상은 로컬 보관.
- 다른 담당 파일을 변경할 필요가 있으면 먼저 변경 내용을 공유. Protocol 필드와 공통 메서드는 함께 확인한 뒤 변경.

### 2. 메시지

UTF-8, 한 줄에 한 메시지, 줄바꿈으로 구분합니다. 접속 시 Client ID를 알리고,
이후 요청 ID는 Client별 1부터 증가합니다. 동일 연결의 응답 순서를 요청 순서라고 가정하지 않습니다.

| 방향 | 형식 | 의미 |
| --- | --- | --- |
| Client → Server | HELLO clientId | Client 등록 |
| Client → Server | RESERVE reqId seat | 단일 예약 |
| Client → Server | RESERVE_MULTI reqId seat1,seat2,... | 2~4석 예약 |
| Client → Server | CANCEL reqId seat | 본인 좌석 취소 |
| Server → Client | RESP reqId status seats reason | 첫 응답 |
| Server → Client | NOTIFY reqId seat | 원 대기 요청의 좌석 배정 |
| Server → Client | BYE | 정상 종료 |

예:

```text
HELLO 9
RESERVE 1 42
RESERVE_MULTI 2 5,3
CANCEL 3 42

RESP 1 WAITLISTED 42 TAKEN
RESP 2 SUCCESS 5,3 OK
RESP 3 FAIL 42 NOT_OWNER
NOTIFY 1 42
BYE
```

- status는 SUCCESS/FAIL/WAITLISTED. seats는 요청 좌석을 쉼표로 표시하고 reason은 공백 없는 한 단어.
- 첫 reason 목록은 OK, TAKEN, ALREADY_OWNER, ALREADY_WAITING, NOT_OWNER, BAD_SEAT, BAD_MULTI. 추가 사유는 공유 후 반영.
- 요청당 첫 응답 1개. NOTIFY는 그 응답과 별개이며 대기 등록 당시 요청 ID 사용.
- 응답 지연은 요청 전송~첫 응답 수신까지만 측정.
- 수신 버퍼에 데이터를 누적해 완성된 줄만 파싱. 나뉜 메시지와 여러 줄 동시 수신 처리.
- 숫자·명령을 파싱할 수 없는 입력은 기록 후 연결 종료. 잘못된 좌석 범위와 MULTI 개수·중복은 FAIL.
- HELLO 외 요청은 Worker 경로로 전달. Listener가 예약 판정을 대신하지 않음.

### 3. 파트 연결

아래는 구현할 메서드의 계약이며 현재 구현 완료를 뜻하지 않습니다.
각 반환 객체는 결과를 복사해서 담고, 내부 Seat나 waitlist를 다른 파트에 넘기지 않습니다.

| 연결 | 계약 |
| --- | --- |
| Listener → RequestQueue | put(Task): 파싱한 Request와 ClientConnection을 묶어 적재 |
| RequestQueue → Worker | take(): 요청이 없으면 CV 대기, 종료 후 잔여 요청도 없으면 null |
| Worker → SeatManager | handle(Request): 첫 응답과 선택적 통지 정보를 담은 Result 반환 |
| Worker/Notifier → ClientConnection | send(String line): 줄바꿈까지 전체 송신 완료 후 반환, 실패는 IOException |
| Monitor → SeatManager | snapshot(): 각 좌석 Lock으로 읽은 복사본 반환 |
| 모든 파트 → Log | write(event, status, message): 정해진 형식으로 한 줄 기록 |

Request에는 연결에서 확인한 Client ID, 요청 ID, 명령, 좌석 목록을 담습니다.
Result에는 응답 데이터와 인계가 발생한 경우 통지 대상 Client ID·원 요청 ID·좌석·등록 시각을 담습니다.
SeatManager는 Socket이나 파일을 사용하지 않습니다.
Notifier는 Server가 관리하는 연결 목록에서 통지 대상 연결을 찾습니다.
Monitor가 사용할 누적 처리 수 등 통계는 Server의 짧은 메서드로 읽습니다.

### 4. Lock·Queue·송신

- owner와 waitlist는 해당 좌석 Lock 안에서만 읽고 변경. Monitor 조회도 동일.
- MULTI 입력 검사 후 좌석 번호 오름차순 Lock 획득, 전부 확인 후 반영, finally에서 역순 해제.
- Request Queue Lock을 해제한 뒤 좌석 Lock 획득.
- Request Queue 용량 1,024. 포화 시 Listener가 notFull Condition에서 대기, 빈 Queue는 Worker가 notEmpty에서 대기.
- Condition은 while 조건 검사와 함께 사용. sleep으로 Queue를 반복 확인하지 않음.
- Worker는 Result를 받은 뒤 통지 enqueue·응답 송신·파일 기록. 좌석 Lock을 쥔 채 I/O하지 않음.
- 같은 연결의 Worker/Notifier 송신은 ClientConnection의 송신 Lock으로 메시지 전체 직렬화.
- NIO 부분 쓰기와 write=0의 쓰기 가능 대기는 조원 3이 작은 echo 예제로 먼저 검증. 추가 송신 스레드나 바쁜 무한 반복은 사용하지 않음.

### 5. Client 상태

보유 좌석 Set, 진행 중 요청 Map, 대기 요청 Map으로 시작합니다.
송신·수신 스레드가 공유하는 상태는 짧은 synchronized 구간으로 보호합니다.

- 요청을 보내기 전에 pending에 등록. MULTI는 관련 좌석 모두 표시.
- 같은 좌석에 상태 변경 요청을 겹치지 않도록 첫 응답 미수신 좌석은 새 요청 후보에서 제외.
- 취소 보낸 좌석은 첫 응답까지 재예약·중복 취소 후보에서 제외.
- CANCEL SUCCESS는 보유 제거, FAIL은 보유 상태 유지.
- NOTIFY 선도착은 원 요청에 배정 완료 표시. 뒤늦은 WAITLISTED로 보유 상태를 되돌리지 않음.
- 선도착 NOTIFY의 첫 응답을 받기 전에는 그 좌석을 취소하지 않음.
- 이미 보유·대기 중인 좌석의 단일 재예약은 허용. Server의 FAIL을 정상 결과로 기록하고 기존 보유·대기 상태를 유지.
- 중복 예약 FAIL로 원래 대기 등록을 지우지 않음. 대기 등록은 WAITLISTED를 받은 원 요청 ID로 유지.
- Waitlist 등록 자체는 다음 요청을 막지 않음. 모든 좌석에 대기 등록되었다는 이유로 Client가 멈추면 안 됨.
- 특정 요청의 응답 대기를 위해 전체 송신을 멈추지 않음. 정상 실행의 응답 처리와 별개로 정해진 간격에 다른 후보 요청을 생성.

### 6. 요청 생성

- 미보유 시 RESERVE 60% / MULTI 40%, 보유 시 RESERVE 30% / MULTI 20% / CANCEL 50%로 시작.
- CANCEL 후보는 응답·통지로 보유를 확인했고 pending이 아닌 좌석. 없으면 예약 요청.
- MULTI 좌석 수 2~4, 중복 없이 선택.
- 인기 좌석 1~10번에 예약 선택 확률 80%로 시작하고 나머지는 일반 좌석.
- 후보 제외·CANCEL·MULTI 개수까지 포함해 실제 인기 좌석 선택 비율을 집계. 절반 이상 조건은 축소 실행에서 확인하고 정식 실행 설정을 고정.
- 선택 비율과 후보 부족 처리는 작은 실행에서 함께 확인. 예시 확률만으로 필수 비율을 충족했다고 주장하지 않음.

### 7. 로그·집계·Deadlock 감시

```text
[HH:MM:SS.mmm] NODE | EVENT | STATUS | message
```

- 시간대 UTC. 경과시간은 같은 노드의 monotonic clock으로 측정.
- Server.txt, Client1.txt~Client30.txt. 요청/응답 기록에 Client ID·요청 ID·좌석·결과를 포함.
- STATUS는 SUCCESS/FAIL/INFO/WARN. WAITLISTED 응답은 WAITLIST 이벤트의 WARN으로 기록.
- INIT, CONNECT, RESERVE, RESERVE_MULTI, CANCEL, LOCK, WAITLIST, NOTIFY, POOL, DOUBLE_BOOKING_CHECK, TERMINATE와 추가 감시·오류 이벤트를 명세에 정리.
- Log는 동기식 파일 기록. 로그 전용 서버 스레드를 추가하지 않음.
- 대기자 인계는 해제 1 + 배정 1. MULTI 성공은 좌석 수만큼 배정.
- Queue 최대 길이는 enqueue/dequeue 시 갱신. Lock 경합은 최초 tryLock 실패 시 1회.
- Monitor는 5초마다 전체 좌석 현황·Queue 길이·누적 처리 수 출력.
- Queue에 요청이 있는데 30초간 첫 응답 송신 수가 증가하지 않으면 Deadlock 의심 기록. 같은 정지 구간은 1건, 정상 진행 후 다시 멈추면 새 구간.
- 이 감시는 네트워크 지연도 감지할 수 있음. 실제 Deadlock 확정·강제 해제 기능은 아님.
- Deadlock 예방은 MULTI의 오름차순 Lock Ordering으로 수행.

### 8. 종료·장애

- Server가 Client별 요청 수와 첫 응답 총수 확인. 정상 실행은 각 5,000건·총 150,000건.
- 입력 종료 → 남은 요청 처리 및 Worker join → 남은 통지 송신 및 Notifier join → BYE → 최종 기록·Monitor 종료·연결/로그 정리.
- Queue가 비었다는 이유만으로 진행 중 작업이나 통지를 생략하지 않음.
- CV 대기자를 깨우고 Listener의 select도 해제해 종료 가능하게 함.
- Client는 전송 완료 후에도 모든 첫 응답과 BYE까지 연결 유지. NOTIFY 수신을 계속하고 BYE 후 최종 보유 목록 기록.
- 종료 시 남은 Waitlist는 미해결 수로 기록.
- 연결 단절·송신 실패는 실패 실행으로 남기고 원인 수정 후 새 실행. 자동 재접속·재전송은 하지 않음.
- Socket 송신 완료와 Client 수신 완료는 구분하고 최종 로그에서 대조.

## 동시 작업과 협업 지점

공통 메시지 예제와 Result 형태를 전원이 확인하면 다음 작업을 병행합니다.

| 담당 | 상대 코드 없이 할 작업 | 통합할 때 확인할 부분 |
| --- | --- | --- |
| 본인 | 요청 객체를 직접 넣어 단일 예약·MULTI·FIFO 검사, Queue·Worker 구현 | Listener 요청 객체, send 완료 의미, Notifier 대상 연결 |
| 조원 2 | 예시 RESP/NOTIFY로 상태 갱신 검사, 요청 생성과 송신/수신 분리 | 요청 ID·응답 필드, NOTIFY 선도착, BYE |
| 조원 3 | echo로 접속·분할/병합·부분 쓰기 검사, 공통 Log 작성 | RequestQueue.put, ClientConnection.send, Monitor 조회 |

실제 TCP로 Client 1개의 단일 예약이 왕복하는 단계에서 첫 통합합니다.
이후 MULTI·Waitlist·종료를 붙이고 30개 축소 실행과 원격 정식 실행으로 검증합니다.
파트가 모두 완성될 때까지 통합을 미루지 않습니다.

## 최소 검증과 결과 설명

- 같은 좌석 동시 예약: 이중예약 0건.
- [5,3] vs [3,5]: 오름차순 Lock, 교착 없음. 일부 점유된 MULTI는 부분 배정 없음.
- 취소 후 B 다음 C로 FIFO 인계, 끼어들기 없음.
- 분할/병합 메시지, NOTIFY 선도착, 마지막 통지까지 전달한 정상 종료.
- 코드 내 배정 검사와 배정/해제 카운트를 실제 처리 경로에 기록.
- 배정 수 - 해제 수 = 최종 예약 좌석 수.
- Server 최종 owner = Client 30명의 최종 보유 목록, Client 간 중복 소유 없음.
- WAITLISTED 수 = NOTIFY 수신 수 + 종료 시 미해결 대기 수.
- Client별 첫 응답 5,000건, 합계 150,000건.

처리량, 평균 첫 응답 시간, Queue 최대 길이, 이중예약 수, 정지 감시 수,
Waitlist 평균 대기시간, Lock 경합 수, 최종 정합성을 기록합니다.
별도 검증 시스템은 만들지 않고 간단한 검사·로그 대조부터 사용합니다.

실제로 겪은 시행착오만 처음 선택 → 관찰한 문제 → 변경 → 재확인 결과 순으로 작성합니다.
정상 동작과 필수 검증을 확인한 뒤에는 기능 확장보다 설명과 제출물 점검에 집중합니다.

## 제출물

전체 소스, AllDefinedLogs.txt, 같은 원격 정식 실행의 Server.txt·Client1.txt~Client30.txt,
Readme.txt, 5분 이내 시연 영상의 다운로드 링크를 담은 download.txt를 ZIP으로 준비합니다.
GitHub에는 코드와 README를 올리고 나머지 제출 자료는 로컬에서 준비합니다.
컴파일·실행 명령과 실제 결과는 구현·검증 후 이 README에 추가합니다.
