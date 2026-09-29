# HW2 — Thread Pool 기반 실시간 좌석 예매 시스템

> Java로 구현할 예정이며, 현재는 요구사항 정리와 설계 단계입니다. 실행 방법과 실측 결과는 구현·검증 후 추가합니다.

## 과제 개요

원격 서버의 좌석 100개를 로컬 Client 30개가 동시에 예약·취소하는 TCP 프로그램입니다.
고정 Thread Pool과 좌석별 Lock을 사용해 이중예약을 막고, 다중 예약의 원자성과 대기열의 FIFO를 보장합니다.

- 마감: **2026년 10월 12일(월) 23:59**
- 언어: **Java**
- 기준 자료: 교수님 배포 HW2description.pdf, HW2explanation.pdf
- 저장소에는 코드와 README를 관리하며, 과제 PDF·개인 세션·실행 로그·영상은 로컬에서 관리합니다.

## 필수 요구사항

| 항목 | 기준 |
| --- | --- |
| 배포 | 서버는 별도 원격 호스트, Client 30개는 로컬 PC |
| 통신 | Client별 TCP 연결 1개, 주소·포트는 실행 인자 또는 설정으로 지정 |
| 좌석 | 1~100번, 초기 EMPTY, 좌석마다 owner·FIFO waitlist·Lock |
| 서버 | Listener 1개 + 시작 시 미리 생성한 Worker 정확히 10개 |
| 추가 스레드 | Notifier 1개 권장, Monitor 최대 1개 선택. 요청·연결별 스레드 생성 금지 |
| 대기 | 빈 Request Queue는 Condition Variable로 대기. Worker는 Waitlist 때문에 멈추지 않음 |
| 부하 | Client당 5,000건, 총 150,000건, 0.2~1.0초 무작위 간격 |
| 경합 | 요청 좌석의 절반 이상을 일부 인기 좌석에 집중 |
| 로그 | 모든 요청·응답·통지 기록, 5초마다 좌석 현황·Queue 길이·누적 처리량 |
| 성공 기준 | 이중예약 0건, Deadlock 0건, 최종 좌석 정합성 확인 |

최종 제출 로그는 원격 서버 구성에서 얻어야 합니다. 평균 간격 0.6초 기준 정식 부하 실행은 약 50분이므로 리허설과 재실행 시간을 확보합니다.

## 요청 처리 규칙

| 요청 | 처리 |
| --- | --- |
| RESERVE | 빈 좌석이면 SUCCESS. 본인 소유 또는 이미 대기 중이면 FAIL. 다른 Client 소유이면 FIFO 등록 후 WAITLISTED |
| RESERVE_MULTI | 중복 없는 2~4석. 좌석 번호 오름차순으로 Lock 획득. 모두 비어 있을 때만 전부 배정하며, 하나라도 점유 중이면 변경 없이 전체 FAIL |
| CANCEL | 소유자만 취소 가능. 대기자가 있으면 같은 좌석 Lock 안에서 맨 앞 Client에게 즉시 인계하고 NOTIFY. 없으면 EMPTY |

- 좌석 범위 오류와 MULTI의 개수·중복 오류는 좌석 Lock 전에 FAIL 처리합니다.
- MULTI는 Waitlist에 등록하지 않습니다.
- CANCEL 대상은 Client가 응답·NOTIFY로 보유를 확인한 좌석에서 선택합니다. 보유가 없으면 예약 요청을 보냅니다.
- WAITLISTED도 첫 응답으로 처리 완료입니다. 이후 NOTIFY는 별도 이벤트입니다.
- Client는 이전 응답을 기다리지 않고 다음 요청을 보내며 응답·통지를 별도로 수신합니다.

## 3인 역할 분담안

| 담당 | 주요 범위 |
| --- | --- |
| 메인 담당 | Worker Pool·CV Queue, 좌석별 Lock, 다중 예약, FIFO 인계, 종료 제어, 전체 통합 |
| Client 담당 | Client 30개 실행, 무작위 요청, 응답·통지 수신, 보유 좌석 관리, 응답시간·Client 로그 |
| 통신·검증 담당 | Listener·TCP 연결, 메시지 파싱·송신, 공통 로그, 서버 통계·검증 도구, 원격 실행 지원 |
| 공동 | 메시지 계약, 담당 기능 테스트·설명 작성, 최종 실행·영상·제출 점검 |

## 패키지 구성안

아래는 예정 구조이며 아직 Java 파일을 생성한 상태는 아닙니다.

```text
src/main/java/g2hw2/
├─ common/             Message, MessageCodec, LineFramer, EventLogger
├─ server/
│  ├─ ServerMain, ServerConfig, ServerLifecycle
│  ├─ net/             Listener, ClientSession
│  ├─ concurrency/     ConditionQueue, WorkerPool, Worker, Notifier
│  ├─ booking/         Seat, WaitEntry, BookingService, BookingResult
│  └─ monitor/         ServerMetrics, PoolMonitor
├─ client/             ClientMain, ClientConfig, BookingClient,
│                      RequestGenerator, ClientState, ClientMetrics
└─ verification/       LogVerifier
```

BookingService는 좌석 잠금과 상태 변경을 담당하며 소켓·파일 I/O는 하지 않습니다.
Worker는 상태 변경 결과를 받아 Lock 해제 후 응답·통지 적재·로그 기록을 수행합니다.
Listener는 요청 수신과 Queue 적재를 담당하고 좌석 상태를 직접 변경하지 않습니다.

## 구현 전에 정할 사항

다음은 과제 필수 수치가 아닌 팀 설계 항목입니다.

- Request Queue 용량과 가득 찼을 때의 처리.
- 메시지 경계·필드·실패 사유와 Client ID + 요청 ID 규칙.
- 요청 종류 비율, 인기 좌석 범위·비율, 난수 seed.
- 응답 미수신·취소 진행 중 좌석의 Client 상태 관리.
- 연결 장애 정책, 통계 집계 방식, 시간대와 종료 절차.
- JDK 버전·빌드 방식·서버 및 Client 실행 명령.

기본 방향은 UTF-8 줄 단위 메시지, 소켓별 송신 Lock, CV 기반 Queue와 Notifier입니다.
좌석 Lock 안에서는 네트워크 전송이나 파일 기록을 하지 않습니다.

## 주의할 동시성 문제

- TCP 메시지가 나뉘거나 합쳐져 도착해도 처리해야 합니다.
- NOTIFY가 WAITLISTED보다 먼저 도착할 수 있으므로 요청 ID로 매칭합니다.
- 오래된 CANCEL 응답이 재배정 상태를 지우지 않도록 좌석 version 등으로 상태 갱신 순서를 관리합니다.
- FIFO는 통지 도착 순서가 아닌 서버의 대기 등록·배정 순서로 확인합니다.
- Queue가 비어 있어도 Worker·Notifier가 처리 중일 수 있으므로 진행 중 작업까지 끝낸 후 BYE를 보냅니다.
- Monitor의 좌석 조회도 좌석별 Lock을 사용합니다.

## 검증 및 지표

필수 검증:

1. 동일 좌석 경쟁에서 이중예약 0건.
2. 겹치는 MULTI 요청에서 교착과 부분 배정 없음.
3. 취소 후 대기자 FIFO 인계와 끼어들기 방지.
4. 배정 수 - 해제 수 = 종료 시 예약 좌석 수.
5. Server 최종 owner와 Client 30명의 최종 보유 목록 일치.
6. WAITLISTED 수 = NOTIFY 수신 수 + 종료 시 미해결 대기 수.
7. Client별 첫 응답 5,000건, 총 150,000건. 남은 통지 전송 후 정상 종료.

처리량, 평균 첫 응답 시간, Queue 최대 길이, 이중예약·Deadlock 수, Waitlist 평균 대기시간, Lock 경합 수, 최종 정합성을 기록합니다.
응답시간은 Client 내부 시계, Waitlist 대기시간은 Server 내부 시계로 측정합니다.
종료 시 미해결 Waitlist는 오류가 아니며 별도로 집계합니다.

## 진행 순서

1. 메시지·상태·로그·종료 계약 합의.
2. Listener → Queue → Worker → 단일 예약·취소 연결.
3. MULTI → Waitlist·Notifier 구현.
4. 응답 순서 역전·경쟁·종료 테스트.
5. 로컬 축소 실행 → 원격 리허설 → 정식 150,000건 실행.
6. 실측 결과·실행법 정리 및 제출물 점검.

## 제출 준비

제출 ZIP에는 전체 소스, AllDefinedLogs.txt, 같은 정식 실행의 Server.txt·Client1.txt~Client30.txt,
Readme.txt, 5분 이내 시연 영상의 다운로드 링크를 담은 download.txt가 필요합니다.
저장소 관리 범위와 제출물 범위는 구분하며, 로그·영상 등은 로컬에서 준비합니다.

Readme에는 조원 역할, 배포 환경, 실행 방법, 설계 선택과 이유, 동시성 제어 전략, 실측 결과와 검증 근거를 작성합니다.
