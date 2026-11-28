================================================================
                  데이터통신 HW6 프로그램 설명서
                 Mini-Torrent - 데이타통신 2조
================================================================


1. 조원 및 역할
----------------------------------------------------------------

  조 : 2조

  이름: 안선효                    학번: 20170210
  담당: Tracker 및 전체 통합
  내용: 공통 통신, 파일 명단·생존 관리, 장애 지시, 복제 관찰,
        report 저장 및 전체 통합.

  이름: 황대겸                    학번: 20223149
  담당: Peer 제어 및 다운로드
  내용: Tracker 연결, 청크·소스 선택, Download Worker Pool,
        속도 제한, crash·복귀 및 종료 처리.

  이름: 황왕석                    학번: 20222161
  담당: 저장소·업로드 및 실행 도구
  내용: 청크 파일·bitmap·해시 관리, 업로드 서버, 상태 화면,
        Peer 실행 및 결과 수집 도구.


2. 프로그램 개요 및 구성
----------------------------------------------------------------

  2.1 시스템 개요

  외부 VM의 Tracker 1개와 로컬 PC의 Peer 4개로 구성함.
  각 프로그램은 독립 프로세스로 실행하며 TCP Socket으로 통신함.

  Tracker는 파일 보유 명단과 Peer의 생존·완료 상태를 관리함.
  파일 데이터는 Peer끼리 직접 주고받음. Peer는 다운로드와 업로드를
  동시에 수행하며, 받은 청크를 파일 완성 전에도 다른 Peer에 제공함.

  본 시나리오는 10·20·30 MiB, DEV는 3·5·7 MiB 파일을 사용함.
  청크 크기는 65,536 B이며 마지막 청크는 남은 길이로 처리함.
  초기 원본과 포트·속도·정책·장애 일정은 env에서 읽음.


  2.2 소스 파일 구성

  src/common/
    contracts.py     공유 자료형과 인터페이스, 예외 정의.
    transport.py     TCP 줄·본문 수신 버퍼와 연결 종료.

  src/tracker/
    __main__.py      실행 인자, Tracker 기동·종료와 결과 저장.
    config.py        env와 포트 검사.
    server.py        접속 수락, 연결별 handler와 주기 스레드.
    state.py         참가·등록·명단·생존·완료 상태 관리.
    scheduler.py     장애 지시, DEAD·ALLDONE·ABORT 판정.
    observer.py      복제 완료와 replica_safe 관찰.
    report.py        report.json 구성과 저장.
    log.py           Tracker 로그 기록.

  src/peer/
    __main__.py      실행 인자와 Peer 기동.
    config.py        Peer id·정책·Tracker 주소 검사.
    client.py        시작·crash·복귀·화면·종료 조율.
    control.py       등록, 주기 갱신, heartbeat·DONE 처리.
    tracker_link.py  Tracker 연결과 여러 줄 응답 수신.
    deadline.py      요청별 송수신 마감 적용.
    download.py      다운로드 worker와 공유 DOWN 제한기.
    selection.py     random·rarest, 소스 선택과 BAN.
    log.py           Peer 로그 기록.

  src/storage/
    store.py         청크 예약·저장·검증과 파일 상태 관리.
    positional.py    mmap 또는 pread/pwrite 파일 접근.
    results.py       bitmap과 lost 파일 저장.

  src/upload/
    server.py        BITMAP·GET 응답과 업로드 종료.
    limiter.py       공유 UP 제한기.
    screen.py        상태 화면과 최근 이벤트 출력.

  tools/
    launch_peers.py  Peer 4개 실행.
    collect_run.py   실행 결과 수집.
    check_run.py     결과 기록 검사.


3. 컴파일 및 실행 방법
----------------------------------------------------------------

  3.1 실행 환경

  사용 언어            : Python 3.12 이상
  외부 패키지          : 없음. Python 표준 라이브러리만 사용함.
  Tracker 환경         : 외부 VM
  원격 서비스·리전     :
  원격 인스턴스 유형   :
  원격 OS / Python     :
  로컬 OS / Python     : Windows / Python 3.12.14
  Tracker 포트         : TCP 6000
  Peer 포트            : TCP 7001~7004
  데이터 단위          : 1 KB=1,024 B, 1 MiB=1,048,576 B


  3.2 실행 준비 및 문법 검사

  (1) 원격 호스트와 로컬 PC에서 제출물의 바깥 src/ 폴더로 이동함.
      현재 폴더 아래에 src/common·tracker·peer·storage·upload와
      tools가 있어야 함.
  (2) 두 환경에 배포 키트의 Python 폴더를 배치하고 같은 env를 사용함.
  (3) 로컬 PC가 원격 Tracker의 TCP 6000에 접속할 수 있게 설정함.

  [원격 Bash]
  python3 --version
  python3 -m compileall -q src tools

  [로컬 PowerShell]
  python --version
  python -m compileall -q src tools

  별도 실행 파일 빌드는 필요하지 않음. python -m으로 실행함.


  3.3 Tracker 실행 - 원격 호스트

  [원격 Bash] 실행할 env 이름을 RUN에 지정함.

  KIT='hw6_student_kit/Python의 실제 경로'
  RUN=DEV
  python3 -m src.tracker --env "$KIT/envs/$RUN.json"

  Tracker는 env의 포트로 접속을 받으며 Peer 네 명이 HELLO하면
  START를 기록함.


  3.4 Peer 실행 - 로컬 PC

  [로컬 PowerShell] Tracker 기동 후 같은 env로 초기화함.

  $kit = 'hw6_student_kit/Python의 실제 경로'
  $trackerIp = 'Tracker의 공인 IP'
  $run = 'DEV'
  $envFile = Join-Path $kit "envs/$run.json"
  python "$kit/tools/reset_dirs.py" --env "$envFile"

  아래 명령을 각각 별도 터미널에서 실행함.

  python -m src.peer --env "$envFile" --id P1 $trackerIp 6000
  python -m src.peer --env "$envFile" --id P2 $trackerIp 6000
  python -m src.peer --env "$envFile" --id P3 $trackerIp 6000
  python -m src.peer --env "$envFile" --id P4 $trackerIp 6000

  자동 실행은 다음 명령을 사용함.

  python -m tools.launch_peers --env "$envFile" $trackerIp 6000

  Run         env       정책     crash   파괴
  ----------------------------------------------------------------
  DEV         DEV.json  random   2회     없음
  A           A.json    random   8회     없음
  B           B.json    random   3회     P3, 34초 이후 replica_safe
  C1          C1.json   rarest   없음    P4, 진행률 0.475
  C2          C2.json   rarest   없음    P3, 진행률 0.308
  C3_random   C3.json   random   없음    P1, p_rep 기준
  C3_rarest   C3.json   rarest   없음    P1, p_rep 기준

  C3는 같은 env로 정책을 지정하여 두 번 실행함.

  $envFile = Join-Path $kit 'envs/C3.json'
  python -m tools.launch_peers --env "$envFile" --policy random $trackerIp 6000

  첫 실행의 결과를 보관하고 초기화한 뒤 Tracker를 다시 기동함.

  python "$kit/tools/reset_dirs.py" --env "$envFile"
  python -m tools.launch_peers --env "$envFile" --policy rarest $trackerIp 6000


  3.5 종료 확인 및 로그 취합

  Tracker의 ALLDONE과 각 Peer의 마지막 EXIT를 확인함.
  원격의 logs/tracker.jsonl과 report.json을 같은 Run의 로컬
  Peer 로그·결과가 있는 폴더로 복사함.

  python "$kit/tools/verify.py" --env "$envFile"
  python -m tools.check_run --env "$envFile" --run-dir .

  C3 검사에는 --policy random 또는 --policy rarest를 지정함.
  결과 수집은 실행한 Run 이름을 지정함.

  python -m tools.collect_run --env "$envFile" --kit "$kit" --run-name DEV

  runs/의 해당 Run 폴더에 로그·report·verify·bitmap·lost를 보관함.


4. TCP 통신 프로토콜
----------------------------------------------------------------

  헤더는 UTF-8 한 줄이며 공백으로 필드를 구분하고 LF로 끝냄.
  DATA 본문은 바이너리임. 소켓별 버퍼에서 헤더와 본문을 나누어 읽음.

  방향               메시지
  ----------------------------------------------------------------
  Peer -> Tracker    HELLO id
                     REGISTER id port file size chunk
                     HAVE id port file
                     LIST / PEERS file
                     HEARTBEAT id have
                     REPORT id file sent distinct bitmap
                     DONE id FULL / DONE id PARTIAL file:lost ...
                     UNDONE id / BYE id / STATE

  Tracker -> Peer    OK / ERR MISMATCH / ERR NOFILE
                     FILES n + n줄
                     PEERS n + n줄
                     CMD DISCONNECT sec / CMD DESTROY
                     STATE done alive WAIT
                     STATE done alive ALLDONE
                     STATE done alive ABORT reason

  Peer -> Peer       BITMAP file / GET file idx
                     BITMAP n bits
                     DATA idx len + len바이트 본문
                     ERR NOFILE / ERR NOCHUNK / ERR BADCMD

  FILES의 후속 줄은 file size chunk nchunks nholders,
  PEERS의 후속 줄은 id host port 형식임.
  DATA의 idx와 len을 요청값과 비교한 뒤 본문을 저장함.


5. Thread Pool 및 동기화
----------------------------------------------------------------

  5.1 Tracker

  Main이 listener를 시작하고 연결마다 handler를 생성함.
  scheduler는 0.5초마다 장애·DEAD·완료·watchdog를 검사하며,
  observer는 1초마다 REPORT의 bitmap으로 복제 상태를 확인함.

  상태 Lock으로 참가자·명단·생존 시각·DONE·장애 지시를 보호함.
  응답과 이벤트를 상태 Lock 안에서 구성하고 소켓 송신·로그·결과
  파일 저장은 밖에서 수행함. 마지막 DONE을 처리할 때도 최신
  REPORT를 관측한 뒤 ALLDONE을 고정함.


  5.2 Peer와 저장소

  Main이 기동·crash·복귀·최종 종료를 조율함. control은 Tracker
  통신과 명단 갱신을 담당하고, 다운로드 worker는 env의 수만큼
  실행함. 업로드는 연결별 handler, 화면은 전용 스레드를 사용함.

  Thread / 공유 자료                보호 수단
  ----------------------------------------------------------------
  control / Tracker 요청·응답        TrackerLink Lock
  worker / 원격 bitmap·inflight      Selection Lock
  worker / DOWN 예약 시각            공유 DOWN 제한기 Lock
  handler / UP 예약 시각             공유 UP 제한기 Lock
  worker·handler / 파일 상태         저장소·파일별 RLock
  worker·Main / 쓰기 완료·pause       Condition과 예약 세대
  listener·handler / 연결·세대       UploadServer RLock
  로그 생산자 / JSONL·최근 이벤트    EventLog Lock
  화면 / 출력·속도 정보              화면·view Lock

  청크를 예약한 뒤 위치 지정 쓰기를 수행하고 bitmap을 공개함.
  Windows는 mmap, Linux는 pread/pwrite를 사용함. 파일 완성 시
  매핑과 핸들을 닫고 해시를 확인한 뒤 이름을 바꿈.


6. 청크 선택 및 속도 제한
----------------------------------------------------------------

  random은 시작할 때 전체 청크 순서를 한 번 섞어 사용함.
  rarest는 받을 수 있는 청크 중 보유자가 가장 적은 것을 고르고
  동률은 무작위로 선택함. 난수 seed는 policy_seed와 Peer 번호로 정함.

  청크를 가진 소스 중 진행 중인 요청이 per_peer_max 미만인 상대를
  고름. 요청 수가 가장 적은 상대를 우선하고 동률은 무작위로 정함.
  연속 실패가 fail_limit에 도달하면 ban_sec 동안 해당 소스를 제외함.

  UP·DOWN은 각각 Peer 전체가 공유하는 제한기 하나를 사용함.
  청크의 실제 길이로 다음 전송 시각을 예약하고 Lock 밖에서 대기함.
  DOWN은 GET 전에, UP은 DATA 송신 전에 적용함.
  BITMAP·REPORT·heartbeat는 데이터 속도 제한에서 제외함.

  파일 전체를 받으면 SHA-256을 확인하고 성공한 파일을 REGISTER함.
  첫 해시 불일치는 다시 받고, 두 번째 불일치는 .corrupt·FAILED로
  처리함. 디스크에 반영한 청크는 파일 완성 전에도 재공유함.


7. 장애 처리 및 복구
----------------------------------------------------------------

  7.1 crash와 복귀

  Tracker는 HEARTBEAT 응답으로 CMD DISCONNECT sec를 전달함.
  Peer는 신규 요청을 막고 저장소의 예약 세대를 올림. 진행 중 쓰기가
  끝나면 연결을 닫고 지정 시간 동안 네트워크 송신을 멈춤.

  복귀 때 저장소와 업로드 서버를 열고 HELLO·REGISTER·HAVE를
  다시 수행함. 명단과 bitmap 갱신 뒤 REJOIN을 기록하고 이어받음.
  디스크·bitmap·누적 전송량은 유지함.


  7.2 destroy와 최종 종료

  CMD DESTROY를 받은 Peer는 결과를 저장하고 BYE 없이 exit 3으로
  종료함. Tracker는 dead_sec 동안 응답이 없는 Peer를 DEAD로 판정함.

  남은 청크 전부를 받을 곳이 없는 상태로 stall_sec가 지나면
  STALLED로 전환함. 소스가 다시 생기면 UNSTALLED·UNDONE으로
  돌아가 받음. 모든 파일이 SEED·STALLED·FAILED가 되면 DONE을 보냄.

  정상 종료는 ALLDONE 확인, 신규 요청 차단, 업로드 최대 3초 유예,
  worker·control 종료, 결과 저장, BYE, 화면 정리, EXIT 순서임.
  ABORT와 tracker_lost도 같은 정리 경로를 사용함.

  모든 Peer는 모든 파일의 .bitmap을 저장함. 미완성 파일은 빈 청크를
  0으로 채워 .incomplete로 바꾸고, 유실 번호는 .lost에 기록함.

  종료 코드   의미
  ----------------------------------------------------------------
  0           ALLDONE 정상 종료. FULL·PARTIAL 포함.
  1           인자·env·원본 크기·원본 해시 오류.
  2           ABORT·tracker_lost·실행 오류.
  3           DESTROY 희생자.


8. 로그 및 지표 계산
----------------------------------------------------------------

  로그 형식 : {"t":초,"peer":"노드","ev":"이벤트",...}
  t는 각 프로그램 시작 후 경과 초, 노드는 tracker 또는 P1~P4임.
  UTF-8·LF로 한 줄에 이벤트 하나를 쓰고 마지막 줄에 EXIT를 기록함.
  이벤트별 필드와 기록 시점은 AllDefinedLogs.txt에 정리함.

  logs/tracker.jsonl  참가·명단·장애 지시·복제·완료·종료.
  logs/P1~P4.jsonl    수신·해시·출처·crash·복귀·상태·종료.
  report.json        복제·파괴·DEAD·DONE·ALLDONE 시각과 지표.
  p1~p4/*.bitmap     청크별 보유 상태.
  p1~p4/*.lost       유실 청크 번호와 연속 범위.
  verify.txt         공식 검사 출력.

  - 전체 진행률 : 원본 제외 보유 청크 합 / progress_total_chunks.
  - 전체 평균 속도 : 누적 송수신 바이트 / 실행 시간 / 1,024.
  - 수신 구간 평균 : RECV 청크 길이 합 / (마지막 RECV - 첫 RECV).
  - 출처 분포 : COMPLETE.sources 또는 RECV.src를 송수신자별로 집계함.
  - T_rep : 원본 제외 fresh live bitmap OR가 모두 1이 된 첫 관측 시각.
  - p_rep : 모든 파일의 복제가 관측되었을 때 전체 진행률.
  - dup_ratio : 복제 시 원본의 (sent - distinct) / sent.
  - T_destroy·T_dead : 파괴 지시 등록·DEAD 판정 시각.
  - T_done·T_alldone : Peer별 완료·전체 완료 시각.
  - crash·실패·BAN 수 : CRASH·FAIL·BAN 이벤트 수.
  - C2 커버리지·유실 : 생존자 bitmap의 1·0 개수.

  report 시각은 Tracker START 기준이며 JSONL은 프로그램 시작 기준임.
  속도는 실제 청크 길이를 사용하며 1 KB=1,024 B로 계산함.
  업로드 출처는 다른 Peer의 RECV.src로 집계함.


9. 실행 결과
----------------------------------------------------------------

  9.1 실행 정보

  원격 실행 일시        :
  Tracker 공인 주소     :
  시연 영상 파일        :
  시연 영상 링크        :


  9.2 정합성 확인

  Run         종료 코드   해시   bitmap 수렴   손실   verify
  ----------------------------------------------------------------
  DEV
  A
  B
  C1
  C2
  C3_random
  C3_rarest


  9.3 실행 지표

  Run         T_alldone(s)   T_last_done(s)   crash   FAIL   BAN
  ----------------------------------------------------------------
  DEV
  A
  B
  C1
  C2
  C3_random
  C3_rarest


  9.4 C2 유실 및 C3 정책 분석




10. 시행착오 및 한계
----------------------------------------------------------------

  10.1 TCP 수신과 부분 재공유

  헤더와 본문이 나뉘거나 붙어서 도착하므로 공통 수신 버퍼에서
  줄과 정확한 바이트 수를 순서대로 읽도록 구성함.
  부분 재공유는 디스크 쓰기 뒤 bitmap을 공개하는 순서로 처리함.


  10.2 장애 시 파일 일관성

  이전 예약을 거부해도 쓰기가 남아 있으면 복귀 뒤 청크를 덮을 수
  있었음. 예약 세대와 쓰기 완료 대기를 함께 사용하여 복귀 시점을
  맞춤. 종료 때도 신규 요청 차단과 진행 응답 완료를 나누어 처리함.


  10.3 종료와 결과 저장

  Main이 스레드 종료와 파일 저장을 한 곳에서 처리하도록 구성함.
  정상 동작뿐 아니라 장애 직전의 쓰기와 종료 직전 응답의 순서도
  맞춰야 파일 상태와 로그를 함께 설명할 수 있었음.


11. 제출 파일 배치
----------------------------------------------------------------

  src/               전체 소스와 실행 도구
  runs/DEV/          DEV 결과
  runs/A/            A 결과
  runs/B/            B 결과
  runs/C1/           C1 결과
  runs/C2/           C2 결과
  runs/C3_random/    C3 random 결과
  runs/C3_rarest/    C3 rarest 결과
  AllDefinedLogs.txt 로그 이벤트·필드 명세
  download.txt       시연 영상 링크
  Readme.txt         프로그램 설명 및 실행 결과

  각 Run은 logs/*.jsonl, report.json, verify.txt와
  p1~p4의 .bitmap·.lost로 구성함.
