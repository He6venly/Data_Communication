================================================================
                  데이터통신 HW3 프로그램 설명서
          Fault-Tolerant 협업 Worker Ring - 데이타통신 2조
================================================================


1. 조원 및 역할
----------------------------------------------------------------

  조 : 2조

  이름: 안선효                    학번: 20170210
  담당: Coordinator 및 전체 통합
  내용: 작업 배정·장애 감지·인계·결과 관리, AWS 서버 구성,
        로그 분석 및 문서·시연 영상 취합.

  이름: 황대겸                    학번: 20223149
  담당: Worker
  내용: 소수 계산, 로컬 Queue·Checkpoint Store, Heartbeat,
        가상 crash·재합류 및 Worker 통신.

  이름: 황왕석                    학번: 20222161
  담당: 공통 모듈 및 Chaos Launcher
  내용: 메시지 해석·TCP 송수신·공통 로그, Worker 프로세스 실행,
        무작위 CRASH·RESTART 및 장애 상태 관리.


2. 프로그램 개요 및 구성
----------------------------------------------------------------

  2.1 시스템 개요

  AWS의 Coordinator 1개와 로컬 Windows PC의 Worker 10개,
  Chaos Launcher 1개로 구성한 분산 작업 시스템.
  모든 프로그램 간 통신에는 TCP Socket을 사용함.

  1부터 100,000,000까지의 소수 개수를 Task 1,000개로 나누어 계산함.
  Task 하나는 수 100,000개를 담당하고, 다시 step 10개로 나누어 처리함.
  각 step의 크기는 수 10,000개임.

  Worker는 고정 Ring으로 연결되며 다음 Worker를 Buddy로 사용함.
  계산 중간값을 Buddy에게 Checkpoint로 보내고, Task 결과는
  Coordinator에게 RESULT로 보냄.

  Launcher는 무작위 Worker에게 CRASH와 RESTART를 전달함.
  Coordinator는 Heartbeat가 끊긴 Worker의 작업을 다른 Worker에게 인계함.
  모든 Task가 한 번씩 반영되고 결과 합계가 5,761,455이면 정상 완료임.


  2.2 소스 파일 구성

  hw3/common/
    settings.py       Worker·Task 수, 포트와 시간 설정.
    protocol.py       메시지 생성·해석과 입력값 검사.
    transport.py      UTF-8 줄 단위 수신 버퍼와 Socket 송신.
    log.py            KST 시각의 텍스트·JSON 로그 기록.

  hw3/coordinator/
    __main__.py       기동, Ring 구성, 최종 검증 및 종료.
    tables.py         Task·Worker 상태, 배정 Queue, Lock 및 지표 관리.
    listener.py       접속 수락, 메시지 수신과 직접 HB 처리.
    dispatcher.py     고정 Dispatcher 6개의 요청 처리.
    detector.py       SUSPECT·DEAD 판정과 Task 인계.

  hw3/worker/
    __main__.py       실행 인자 처리와 Worker 기동·종료.
    state.py          상태, Queue, Checkpoint Store와 crash 세대 관리.
    network.py        Coordinator·Buddy·Launcher 통신.
    heartbeat.py      Heartbeat 전송과 REJOIN 재시도.
    compute.py        Task의 step 순차 계산과 CKPT·RESULT 전송.
    primes.py         구간 에라토스테네스의 체를 이용한 소수 계산.

  hw3/launcher/
    __main__.py       Worker 제어 연결과 READY·REJOINED·EOF 처리.
    processes.py      Worker 10개를 독립 프로세스로 실행.
    chaos.py          난수 기반 장애 주입 시각과 Worker 상태 관리.

  hw3/tools/
    verify_logs.py    로그 12개의 정합성 검사와 장애별 지표 계산.

  common/__init__.py는 공통 메시지 API를 공개하며 폴더 구조를 유지함.


3. 컴파일 및 실행 방법
----------------------------------------------------------------

  3.1 실행 환경

  사용 언어           : Python 3.12 이상
  Coordinator 환경    : AWS 원격 호스트
  AWS 서비스          : AWS EC2
  인스턴스 유형       : t3.micro
  원격 OS             : Ubuntu 26.04 LTS
  Worker 환경         : 로컬 Windows PC 1대
  외부 패키지         : 없음. Python 표준 라이브러리만 사용.
  Coordinator 주소    : 공인 IP 또는 DNS (실행 시 입력)
  Coordinator 포트    : TCP 4575
  Worker Peer 주소    : 127.0.0.1, TCP 7001~7010
  로그 시간대         : KST
  정식 step delay     : 100ms

  [AWS]는 원격 서버의 Bash 터미널,
  [Windows]는 로컬 PC의 PowerShell에서 실행하는 명령임.
  아래 명령은 hw3 폴더가 있는 위치에서 실행함.


  3.2 실행 준비

  (1) AWS 서버와 로컬 PC에 hw3 폴더 전체를 배치함.

      [AWS]
      python3 --version

      [Windows]
      python --version

  (2) AWS의 TCP 4575 포트로 로컬 PC에서 접속할 수 있어야 함.
      로컬의 Peer 포트 7001~7010은 Worker끼리와 Launcher 연결에 사용함.

  (3) 양쪽 로그 시각을 맞추고 동일한 run_id를 사용함.
      로그 파일은 추가 기록 방식이므로 실행마다 새 run_id와 폴더를 지정함.
      아래 명령의 hw3-run01은 양쪽에서 같은 값으로 맞춤.


  3.3 소스 컴파일 및 문법 검사

  Python 소스로 실행하며 아래 명령으로 hw3 전체의 문법을 검사함.

  [AWS]
  python3 -m compileall -q hw3

  [Windows]
  python -m compileall -q hw3

  오류 없이 명령 입력줄이 돌아오면 문법 검사 완료임.


  3.4 Coordinator 실행 - AWS에서 먼저 실행

  [AWS]
  run_id=hw3-run01
  python3 -u -m hw3.coordinator --host 0.0.0.0 --port 4575 --run-id "$run_id" --log-dir "logs/$run_id"

  인자 설명
  - --host    : Worker 연결을 받을 주소.
  - --port    : TCP 수신 포트, 4575.
  - --run-id  : 양쪽에서 동일하게 사용할 실행 ID.
  - --log-dir : Coordinator 로그 저장 폴더.

  Coordinator 실행 창을 유지한 채 로컬 Launcher를 실행함.


  3.5 Launcher 실행 - 로컬 Windows에서 실행

  AWS_PUBLIC_IP는 실제 Coordinator의 공인 IP 또는 DNS로 바꾸어 입력함.
  0.0.0.0은 Coordinator의 수신 주소이며 로컬 접속 주소로 사용하지 않음.

  [Windows]
  $coord = 'AWS_PUBLIC_IP:4575'
  $runId = 'hw3-run01'
  python -u -m hw3.launcher --coord $coord --workers 10 --peer-ip 127.0.0.1 --peer-base 7000 --step-delay 100 --seed 42 --run-id $runId --log-dir "logs/$runId"

  인자 설명
  - --coord      : Coordinator의 주소와 포트.
  - --workers    : 실행할 Worker 수, 10개.
  - --peer-ip    : Worker끼리 연결할 주소, 127.0.0.1.
  - --peer-base  : Worker 번호를 더할 기준 포트, 7000.
  - --step-delay : step마다 기다리는 시간, 100ms.
  - --seed       : 장애 주입에 사용할 난수 기준값, 42.
  - --run-id     : Coordinator와 같은 실행 ID.
  - --log-dir    : Worker·Launcher 로그 저장 폴더.

  Launcher 한 번으로 Worker 10개가 각각 독립 프로세스로 실행됨.
  Worker 번호는 1~10, Peer 포트는 7001~7010임.


  3.6 진행 상황 및 정상 종료

  Coordinator 콘솔에서 시작, 작업 진행, 장애 감지, 인계와 재합류를 확인함.
  POOL에는 DONE·PENDING·ASSIGNED 수와 ALIVE·SUSPECT·DEAD 목록을 표시함.
  Worker의 TAKEOVER 로그에서 resume_step과 partial을 확인할 수 있음.
  시연에서는 Coordinator 출력과 해당 Worker의 TAKEOVER 로그를 함께 표시함.

  정상 종료 기준
  - Task 1,000개 모두 DONE, COMMIT 1,000개.
  - 모든 Task의 commit_count=1, 이중 Commit=0.
  - 결과 합계 5,761,455, VERIFY=PASS.
  - Coordinator와 Worker의 남은 스레드 수 0.
  - Launcher가 Worker 10개의 종료를 확인한 뒤 종료함.


  3.7 로그 취합 및 정합성 검사

  AWS의 Coordinator.txt와 같은 실행의 로컬 Worker1.txt~Worker10.txt,
  Launcher.txt를 하나의 폴더에 모음.

  [Windows]
  python -m hw3.tools.verify_logs --log-dir "logs/$runId" --run-id $runId --output "logs/$runId/analysis.json"

  분석 결과의 pass와 errors를 확인함.
  결과 파일은 지정한 폴더의 analysis.json에 저장됨.


4. TCP 통신 프로토콜
----------------------------------------------------------------

  UTF-8 문자열을 공백으로 구분하고 LF(\n)로 메시지 끝을 표시함.
  Socket마다 수신 버퍼를 두어 분할되거나 붙어서 도착한 메시지를 구분함.
  Coordinator는 HELLO로 등록한 Socket을 기준으로 송신 Worker를 판별함.

  Worker -> Coordinator
    HELLO i ip port          Worker 번호와 Peer 주소 등록.
    RING_OK i                Buddy 연결 완료.
    HB i                     Heartbeat.
    REQ i                    새 Task 요청.
    RESULT k e v             Task 결과 전달.
    REJOIN i                 재합류 요청.

  Coordinator -> Worker
    RING j ip port           고정 Buddy 주소 전달.
    START                    계산 시작.
    ASSIGN k 1               새 Task 배정.
    NO_TASK                  PENDING Task 없음.
    TAKEOVER k e from=d      죽은 Worker의 Task 인계.
    ACK k                    결과 반영 완료.
    REJECT_STALE k reason    DEAD·DONE·EPOCH 사유로 결과 거부.
    WELCOME                  재합류 승인.
    RETRY_LATER              2초 뒤 재합류 재요청.
    BYE                      종료.

  Worker -> Buddy
    PEER i                   연결한 Worker 번호 전달.
    CKPT k e s partial       step s까지의 누적 계산값 전달.

  Launcher -> Worker
    LAUNCHER                 제어 연결 등록.
    CRASH                    가상 crash.
    RESTART                  재합류 시작.

  Worker -> Launcher
    READY i                  START 수신과 제어 연결 완료.
    REJOINED i               재합류 완료.

  i·j·d는 Worker 번호 1~10, k는 Task 번호 0~999임.
  e는 Task별 epoch, s는 완료한 step, partial은 누적 소수 개수임.


5. Thread Pool 및 동기화
----------------------------------------------------------------

  5.1 Coordinator

  main, Listener 1개, Dispatcher 6개, Failure Detector 1개로 구성함.
  Listener는 Socket 수신과 파싱을 담당하고 HB는 직접 처리함.
  나머지 메시지는 Request Queue에 넣어 고정 Dispatcher가 처리함.

  Task마다 독립 Lock을 사용하고 Worker Table은 하나의 Lock으로 보호함.
  Lock 순서는 Worker Table -> Task 번호 오름차순임.
  Socket 송신 Lock으로 메시지 순서를 보호하며 상태 Lock을 해제한 뒤 전송함.

  REQ는 Worker Table Lock 안에서 DEAD 확인, PENDING 추출,
  Task 배정을 한 번에 처리함.
  RESULT는 Worker 상태를 먼저 확인하고 Task Lock 안에서
  DONE·epoch·owner 검사와 Commit을 함께 처리함.

  Queue가 비었을 때와 기동·종료 대기는 Condition Variable을 사용함.
  1,000번째 Commit이 main을 깨우면 검증과 BYE 전송을 처리함.
  Dispatcher에 STOP 6개를 넣고 모든 스레드를 join하여 종료함.


  5.2 Worker

  Control Recv, Peer Server, Compute, Heartbeat 스레드를 사용함.
  Compute 하나가 진행 중 Task를 먼저 끝내고 인계 Task를 FIFO로 처리함.
  현재 Task와 Queue가 모두 비었을 때 새 REQ를 보냄.

  Lock 순서는 Queue -> state -> Store임.
  Queue 대기와 CRASHED·REJOINING 상태의 계산·HB 대기는 CV를 사용함.
  BYE 수신 시 대기 중인 스레드를 깨워 종료함.

  송신과 CRASH 전환을 같은 송신 경계로 보호함.
  상태·세대를 확인한 뒤 상태 Lock을 풀고 전송하며,
  진행 중인 전송이 끝난 뒤 CRASH 상태로 전환함.


6. 소수 계산 및 Task 분배
----------------------------------------------------------------

  Task k의 범위 : [k*100000+1, (k+1)*100000]
  step s의 범위 : lo=k*100000+(s-1)*10000+1, hi=lo+9999

  10,000 이하의 작은 소수 목록을 구해 각 step의 구간 체에 사용함.
  작은 소수의 배수를 지운 뒤 남은 수를 세며, 1은 소수에서 제외함.

  Coordinator는 PENDING Queue에 Task 0~999를 오름차순으로 넣음.
  Worker의 REQ가 처리될 때 맨 앞 Task를 epoch=1로 배정함.
  빨리 끝낸 Worker가 다시 요청하여 다음 Task를 받는 방식임.

  Worker는 step 1~10을 순서대로 계산함.
  step 1~9 뒤에는 누적값을 CKPT로 보내고, step 10 뒤에는 RESULT를 보냄.
  Coordinator는 Commit된 result만 합산함.


7. 장애 처리 및 복구
----------------------------------------------------------------

  7.1 Heartbeat와 장애 감지

  Worker는 RUNNING 상태에서 1초마다 HB를 보냄.
  Coordinator는 START 시각으로 lastHB를 초기화하고 FD를 시작함.
  FD는 1초마다 검사하여 HB가 3초 이상 없으면 SUSPECT,
  5초 이상 없으면 DEAD로 판정함.
  SUSPECT에서 HB가 다시 오면 ALIVE로 복귀함.


  7.2 가상 crash

  CRASH를 받으면 Queue·진행 중 Task·Checkpoint Store와
  requested·no_task를 초기화하고 crash_gen을 증가시킴.
  TCP 연결은 유지하며 HB·REQ·CKPT·RESULT 송신을 중단함.
  받은 메시지는 읽고 버리되 RESTART와 BYE는 처리함.

  계산을 시작할 때 crash_gen을 저장하고 step·전송 전에 비교함.
  crash 전의 계산 결과가 재합류 후 전송되는 것을 막음.


  7.3 Checkpoint와 인계

  Buddy는 항상 i mod 10+1이며 Worker 10의 Buddy는 Worker 1임.
  Store는 Task별 최신 CKPT 하나를 (epoch, step) 순서로 비교해 보관함.
  Buddy가 crash 중이면 받은 CKPT를 버림.
  CKPT 송신 오류는 WARN으로 기록하고 계산을 계속함.

  DEAD Worker의 모든 ASSIGNED Task를 링 순서의 다음 ALIVE에 인계함.
  이전에 인계받아 Queue에서 기다리던 Task도 포함함.
  DEAD·SUSPECT는 건너뛰며 ALIVE가 없으면 첫 SUSPECT를 선택함.
  같은 검사에서 여러 Worker가 DEAD가 되면 모두 표시한 뒤 번호순으로 처리함.

  인계받은 Worker는 Store에서 새 epoch보다 낮은 최신 CKPT를 사용함.
  해당 CKPT가 있으면 다음 step부터 이어 계산함.
  CKPT가 없으면 step 1, partial=0에서 시작함.
  인계받은 Worker까지 crash하면 원래 Task와 인계 Task를 다시 넘김.


  7.4 Epoch와 Commit

  epoch는 Worker별이 아니라 Task별로 관리함.
  ASSIGN 때 1, TAKEOVER 때마다 Coordinator가 1 증가시킴.
  Worker는 받은 epoch를 CKPT·RESULT에 그대로 사용함.

  RESULT 판정 순서
  ① 송신 Worker가 DEAD이면 REJECT_STALE DEAD.
  ② Task가 이미 DONE이면 REJECT_STALE DONE.
  ③ epoch 또는 owner가 다르면 REJECT_STALE EPOCH.
  ④ 유효하면 DONE, result 저장, commit_count 증가 후 ACK.

  Task Lock 안에서 확인과 반영을 함께 수행하여 이중 Commit을 방지함.


  7.5 재합류

  RESTART -> REJOINING -> REJOIN -> WELCOME -> RUNNING 순서임.
  Coordinator는 DEAD Worker의 재합류를 승인하고 lastHB를 갱신함.
  아직 DEAD 전이면 RETRY_LATER를 보내며 Worker는 2초 뒤 다시 요청함.
  REJOINING 동안 받은 CKPT는 저장하고 계산·HB는 WELCOME 뒤 재개함.
  WELCOME보다 먼저 받은 TAKEOVER는 Queue에 보관한 뒤 처리함.

  재합류한 Worker는 REJOINED를 Launcher에 보내고 새 Task를 요청함.
  NO_TASK를 받으면 추가 REQ를 보내지 않고 인계 또는 종료를 기다림.


  7.6 Launcher의 장애 주입

  READY 10개를 받은 시각을 t0로 사용함.
  seed 기반 난수로 현재 RUNNING Worker 중 victim을 선택함.

  - 첫 CRASH : t0 후 10~20초.
  - 다음 CRASH : 직전 CRASH 후 5~15초.
  - RESTART : CRASH 후 10~15초.
  - 동시 장애 : CRASHED와 REJOINING 합계 최대 2개.
  - 2개 장애 중 : REJOINED 뒤 새 간격을 뽑아 다음 CRASH 예약.
  - t0 후 80초 : 새 CRASH 중단, 예약된 RESTART는 계속 처리.

  Worker 제어 연결의 EOF는 EXITED로 처리하고 예정 RESTART를 취소함.
  10개 모두 EXITED가 되면 각 프로세스의 정상 종료를 확인하고 Launcher가 종료함.
  Coordinator와 Launcher는 직접 통신하지 않음.
  Coordinator의 실제 연결 오류는 가상 crash와 구분하여 오류 종료함.


8. 로그 및 지표 계산
----------------------------------------------------------------

  로그 형식 : [HH:MM:SS.mmm] NODE | EVENT | STATUS | JSON
  시간대는 KST이며 모든 행에 run_id와 ts_unix_ms를 기록함.
  전체 이벤트 설명은 AllDefinedLogs.txt에 정리함.

  Coordinator.txt                  배정·HB 판정·인계·Commit·최종 검증.
  Worker1.txt ~ Worker10.txt        계산·CKPT·crash·재합류·종료.
  Launcher.txt                     장애 주입·재시작·Worker 종료.

  콘솔에는 주요 상태와 진행 수를 표시하고 상세 이벤트는 파일에 기록함.
  Worker TAKEOVER의 resume_step·partial은 실제 재개 시점의 값임.
  Coordinator의 seq로 판정 순서를 확인하고 노드 간 기록은
  실제 시각·run_id·Task·epoch로 대조함.

  지표 계산
  - 실행시간 : START부터 마지막 COMMIT까지.
  - 처리량 : 1,000 / 실행시간(초).
  - 감지 지연 : DEAD 시각 - 마지막 HB 수신 시각.
  - 복구 시간 : DEAD부터 인계 Task가 전부 Commit될 때까지.
  - 재합류 지연 : REJOIN 시각부터 재합류 후 첫 새 ASSIGN까지.
  - 재합류 후 처리 수 : 해당 재합류 회차에서 Commit한 Task 수.
  - CKPT 절약률 : 장애별 Σ(재개 step-1) / (인계 Task 수*10).
  - 이중 Commit : commit_count가 2 이상인 Task 수.

  재인계된 Task의 복구 시간은 최종 Commit까지 계산함.
  재개 로그가 없는 인계는 CKPT 절약률의 분자에 0으로 계산함.
  인계 Task가 없으면 해당 복구 시간과 절약률은 '-'로 표시함.


9. 실행 결과
----------------------------------------------------------------

  9.1 실행 정보

  실행 ID                    :
  실행 시작 시각             :
  실행 종료 시각             :
  사용한 seed                :
  제출 로그 위치             :


  9.2 정합성 확인

  Task DONE 수               :
  COMMIT 수                  :
  Task별 commit_count        :
  이중 Commit 수             :
  소수 개수 합계             :
  Launcher CRASH 수          :
  Coordinator DEAD 수        :
  승인 REJOIN 수             :
  최대 동시 장애 수          :
  재합류 후 새 Task 수행     :
  Worker RESULT 대조         :
  전체 정상 종료             :
  정합성 판정                :


  9.3 전체 실행 지표

  실행시간                   :
  처리량                     :


  9.4 장애별 지표

  회차  Worker  인계 Task/대상  감지(s)  복구(s)  재합류(s)  처리 Task  CKPT 절약률
  --------------------------------------------------------------------------





10. 시행착오
----------------------------------------------------------------

  10.1 메시지 검증 구조

  처음에는 메시지마다 검증 함수를 나누고 함수 목록으로 호출함.
  검사 규칙이 여러 함수에 나뉘어 구조를 파악하고 수정하기 어려웠음.
  구현 난이도를 낮추기 위해 필드 수 표와 if/elif로 직접 검사하는
  단순한 방식으로 변경함. 메시지 형식과 입력값 검사 기준은 유지함.


  10.2 소수 계산 방식

  처음에는 슬라이스 연산으로 여러 배수를 한 번에 제거하도록 구현함.
  배수의 위치와 처리 개수를 함께 계산하는 식을 이해하고 수정하기 어려웠음.
  구현 난이도를 낮추기 위해 리스트와 for문으로 배수를 하나씩 제거하는
  기본적인 방식으로 변경함. 구간 체와 Task·step의 계산 범위는 유지함.
