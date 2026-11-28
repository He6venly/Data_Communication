================================================================
                  데이터통신 HW6 프로그램 설명서
                 Mini-Torrent - 데이타통신 2조
================================================================


1. 조원 및 역할
----------------------------------------------------------------

  조 : 2조

  이름: 안선효                    학번: 20170210
  담당: Tracker 및 전체 통합 (40%)
  내용: 공통 통신·자료형, 참가 명단·생존·장애 지시, 복제 관찰,
        report 저장, 구성요소 통합 및 정합성 검증.

  이름: 황대겸                    학번: 20223149
  담당: Peer 제어 및 다운로드 (30%)
  내용: Tracker 연결, 청크·소스 선택, Download Worker Pool,
        공유 DOWN 제한기, crash·복귀·DONE·종료 조율.

  이름: 황왕석                    학번: 20222161
  담당: 저장소·업로드·실행 도구 (30%)
  내용: 위치 지정 파일 I/O, bitmap·예약·해시·결과 저장,
        업로드 서버·공유 UP 제한기, 상태 화면 및 결과 수집 도구.


2. 프로그램 개요 및 구성
----------------------------------------------------------------

  2.1 시스템 개요

  외부 VM의 Tracker 1개와 로컬 PC 한 대의 Peer 4개로 구성함.
  Tracker와 Peer는 각각 독립 프로세스로 실행하며 TCP로 통신함.
  Tracker는 파일 보유 명단·생존·장애 지시·완료 상태를 관리함.
  파일 데이터는 Tracker를 거치지 않고 Peer끼리 직접 주고받음.

  공개 본 시나리오는 10·20·30 MiB 파일, DEV는 3·5·7 MiB 파일을
  사용함. 청크 크기는 65,536 B이며 마지막 청크는 남은 길이만 처리함.
  초기 원본은 env의 files[].origin을 따르고 P4는 빈 상태로 시작함.

  Peer는 파일을 받는 동시에 이미 받은 청크를 다른 Peer에 업로드함.
  완료한 Peer도 ALLDONE까지 업로드를 유지함. 원본 파괴로 유실이
  생겨도 받을 수 있는 청크를 모두 받은 뒤 생존자 bitmap을 맞추고
  DONE PARTIAL로 종료함.

  포트·속도·정책·worker 수·갱신 주기·장애 일정은 같은 env를 읽음.
  Run 이름으로 동작을 나누지 않으며 CLI 정책이 env보다 우선함.


  2.2 소스 파일 구성

  아래는 실행 작업 폴더를 기준으로 한 구성임.

  src/common/
    contracts.py     공유 자료형, 저장소·업로드 인터페이스와 예외.
    transport.py     소켓별 버퍼, 줄·정확한 바이트 수신과 종료.

  src/tracker/
    __main__.py      CLI, 시그널, 서버 기동, report·최종 종료.
    config.py        env·포트·자료형과 참조 관계 검사.
    server.py        TCP listener, 연결별 handler와 주기 스레드.
    state.py         참가·등록·명단·생존·REPORT·DONE 상태.
    scheduler.py     crash·destroy·DEAD·완료·watchdog 판정.
    observer.py      fresh bitmap OR, 복제 관찰과 replica_safe.
    report.py        최종 report 구성 및 원자적 파일 저장.
    log.py           Tracker JSONL과 최근 이벤트 버퍼.

  src/peer/
    __main__.py      CLI, 실제 구성요소 생성과 시그널 연결.
    config.py        Peer 인자, id·정책·Tracker 주소 검사.
    client.py        기동·화면·crash·복귀·최종 종료 조율.
    control.py       등록·갱신·REPORT·heartbeat·DONE 처리.
    tracker_link.py  HELLO·재연결과 여러 줄 응답 수신.
    deadline.py      하나의 요청에 공통 송수신 마감 적용.
    download.py      worker, DATA 검사, 공유 DOWN 제한기.
    selection.py     random·rarest, 소스 선택, inflight·BAN.
    log.py           Peer JSONL과 최근 이벤트 버퍼.

  src/storage/
    store.py         원본 검사, 청크 예약·commit·상태·완성 처리.
    positional.py    Windows mmap, Linux pread/pwrite 접근.
    results.py       bitmap과 유실 청크 범위 저장.

  src/upload/
    server.py        BITMAP·GET, 연결별 handler와 종료 유예.
    limiter.py       Peer 전체 업로드가 공유하는 속도 제한기.
    screen.py        40칸 상태판과 최근 이벤트 표시.

  tools/
    launch_peers.py  env의 Peer 4개를 독립 프로세스로 실행.
    collect_run.py   공식 verify·추가 검사 후 결과 기록 보관.
    check_run.py     로그·report·속도·bitmap·lost 추가 검사.


3. 컴파일 및 실행 방법
----------------------------------------------------------------

  3.1 실행 환경

  사용 언어           : Python 3.12 이상
  외부 패키지         : 없음. 실행 코드는 표준 라이브러리만 사용함.
  로컬 검증 환경      : Windows / Python 3.12.14
  Tracker 배포        : 외부 VM 1개. 실제 배포 정보는 9.1에 기록함.
  Tracker 기본 포트   : env의 tracker.port. 공개 env는 TCP 6000.
  Peer 수신 포트      : env의 peers[].port. 공개 env는 TCP 7001~7004.
  데이터 속도 단위    : 1 KB = 1,024 B, 1 MiB = 1,048,576 B.

  Windows는 python, Linux VM은 python3 명령을 사용함.
  아래 명령은 현재 폴더 아래에 src/common·src/tracker·src/peer와
  tools가 있는 실행 작업 폴더에서 수행함. 개발 폴더에서는 HW6/,
  제출 폴더에서는 바깥 src/가 이 작업 폴더에 해당함.


  3.2 실행 준비 및 문법 검사

  (1) 같은 소스를 로컬 PC와 VM에 배치하고 Python 버전을 확인함.
  (2) 배포 hw6_student_kit의 Python 폴더를 두 환경에 배치함.
      Tracker와 Peer는 수정하지 않은 같은 env 파일을 사용함.
  (3) VM 방화벽에서 로컬 PC의 공인 IP에 Tracker TCP 포트를 허용함.
      Peer 간 통신은 env의 로컬 host·port를 사용함.

  [원격 Bash]
  python3 --version
  python3 -m compileall -q src tools

  [로컬 PowerShell]
  python --version
  python -m compileall -q src tools
  $kit = 'hw6_student_kit/Python의 실제 경로'
  $trackerIp = '실제 VM의 공인 IP'
  $run = 'DEV'
  $envFile = Join-Path $kit "envs/$run.json"

  로컬 Tracker로 개발 검사할 때는 $trackerIp에 '127.0.0.1'을 지정함.
  기존 실행 결과를 보관한 뒤 아래 명령으로 로컬 초기 상태를 만듦.

  python "$kit/tools/reset_dirs.py" --env "$envFile"

  reset_dirs는 현재 폴더의 Peer 폴더·logs·report를 초기화함.
  원본이 없으면 make_dummy와 같은 방식으로 생성하고 origin에 복사함.
  같은 크기의 기존 원본을 재사용할 수 있으므로 원본 내용 검사는
  Peer 시작 시 env의 SHA-256과 다시 대조함.

  별도 실행 파일 빌드는 필요하지 않음. python -m으로 실행함.


  3.3 Tracker 실행 - 원격 호스트

  [원격 Bash] KIT에는 VM에 배치한 Python 키트 경로를 지정함.

  KIT='hw6_student_kit/Python의 실제 경로'
  RUN=DEV
  python3 -m src.tracker --env "$KIT/envs/$RUN.json"

  Tracker는 0.0.0.0에 listen함. 0.0.0.0은 Peer의 접속 주소가 아님.
  다른 포트가 필요하면 env를 수정하지 않고 마지막 인자로 지정함.

  python3 -m src.tracker --env "$KIT/envs/$RUN.json" 6100

  이 경우 네 Peer의 마지막 포트와 VM 방화벽도 6100으로 맞춤.
  Tracker는 env 피어 네 명의 첫 HELLO가 모이면 START를 고정함.


  3.4 Peer 실행 - 로컬 PC

  Tracker를 먼저 실행한 뒤 아래 네 명령을 각각 별도 터미널에서
  실행함. 각 창에서 3.2의 $kit·$trackerIp·$run·$envFile을 지정함.

  python -m src.peer --env "$envFile" --id P1 $trackerIp 6000
  python -m src.peer --env "$envFile" --id P2 $trackerIp 6000
  python -m src.peer --env "$envFile" --id P3 $trackerIp 6000
  python -m src.peer --env "$envFile" --id P4 $trackerIp 6000

  자동 실행·검사에서는 다음 명령으로 네 프로세스를 함께 실행함.
  이 도구는 상태 화면을 버리고 각 프로세스의 종료 코드를 수집함.

  python -m tools.launch_peers --env "$envFile" $trackerIp 6000

  실행 이름   env       정책     crash   파괴 조건
  ----------------------------------------------------------------
  DEV         DEV.json  random   2회     없음
  A           A.json    random   8회     없음
  B           B.json    random   3회     P3, 34초 이후 replica_safe
  C1          C1.json   rarest   없음    P4, 진행률 0.475 이상
  C2          C2.json   rarest   없음    P3, 진행률 0.308 이상
  C3_random   C3.json   random   없음    P1, p_rep 기준
  C3_rarest   C3.json   rarest   없음    P1, p_rep 기준

  표의 값은 공개 env의 설명임. 실제 프로그램은 해당 값을 env에서 읽음.
  B의 34초는 파괴 검토 시작 시각이며 실제 파괴 시각은 다를 수 있음.
  C3 조건은 진행률 >= p_rep + value * (1 - p_rep)임.

  C3는 env 정책이 null이므로 네 Peer 모두 같은 정책을 명시함.
  한 정책의 결과를 보관하고 초기화한 뒤 다른 정책을 실행함.

  $envFile = Join-Path $kit 'envs/C3.json'
  python -m tools.launch_peers --env "$envFile" --policy random $trackerIp 6000
  python -m tools.launch_peers --env "$envFile" --policy rarest $trackerIp 6000

  두 명령 사이에 반드시 결과 보관·초기화와 Tracker 재실행을 수행함.
  시나리오는 한 번에 하나씩 실행함.


  3.5 종료 확인 및 로그 취합

  희생자는 exit 3, 생존자와 Tracker는 ALLDONE 뒤 exit 0으로 끝남.
  로그 마지막 EXIT와 report의 done_kind·peers 상태를 대조함.
  원격 logs/tracker.jsonl과 report.json을 같은 실행의 로컬 폴더에
  복사한 뒤 원본 데이터가 남아 있는 상태에서 공식 검사를 실행함.

  python "$kit/tools/verify.py" --env "$envFile"
  python -m tools.check_run --env "$envFile" --run-dir .

  C3 추가 검사는 실행한 정책을 --policy random 또는 rarest로 지정함.
  결과 보관 도구는 공식 verify를 다시 실행하여 출력을 verify.txt에
  저장하고 추가 검사까지 통과한 기록만 새 폴더에 보관함.

  python -m tools.collect_run --env "$envFile" --kit "$kit" --run-name DEV

  --run-name은 DEV·A·B·C1·C2·C3_random·C3_rarest 중 하나임.
  이미 있는 결과 폴더는 덮어쓰지 않음. 보관 폴더에는 큰 데이터가
  없으므로 그 폴더의 추가 검사를 공식 verify 재실행으로 보지 않음.


4. TCP 통신 프로토콜
----------------------------------------------------------------

  헤더는 UTF-8 한 줄이며 공백으로 필드를 나누고 LF로 끝냄.
  DATA 본문만 바이너리임. 소켓마다 Conn 하나가 수신 버퍼를 가지며
  줄 수신과 정확한 바이트 수신이 같은 버퍼를 사용함.

  방향              요청                         응답
  ----------------------------------------------------------------
  Peer -> Tracker   HELLO id                     OK
                    REGISTER id port file size chunk
                                                 OK / ERR MISMATCH
                    HAVE id port file             OK / ERR NOFILE
                    LIST                          FILES n + n줄
                    PEERS file                    PEERS n + n줄
                    HEARTBEAT id have             OK / CMD 명령
                    REPORT id file sent distinct bitmap
                                                 OK
                    DONE id FULL                  OK
                    DONE id PARTIAL file:lost ... OK
                    UNDONE id / BYE id            OK
                    STATE                         STATE done alive 상태

  Peer -> Peer      BITMAP file                  BITMAP n bits
                    GET file idx                  DATA idx len + 본문

  FILES 후속 줄은 file size chunk nchunks nholders,
  PEERS 후속 줄은 id host port 형식임. 후속 n줄을 모두 읽은 뒤 다음
  요청으로 넘어감. STATE 상태는 WAIT·ALLDONE·ABORT reason임.
  장애 명령은 CMD DISCONNECT sec 또는 CMD DESTROY임.

  업로드 오류는 ERR NOFILE·ERR NOCHUNK·ERR BADCMD로 응답함.
  가상 오프라인 중에는 오류 응답도 보내지 않고 연결을 닫음.
  DATA의 idx·len을 요청과 비교하고 정확한 len 바이트만 commit함.
  timeout·EOF·잘린 본문은 성공으로 처리하지 않고 연결을 폐기함.


5. Thread Pool 및 동기화
----------------------------------------------------------------

  5.1 Tracker

  Main이 listener와 주기 스레드를 시작하고 연결마다 handler를 둠.
  scheduler는 0.5초마다 장애·DEAD·watchdog·완료를 검사함.
  observer는 1초마다 최근 REPORT로 복제를 관찰함.

  상태 Lock으로 참가자·보유 명단·생존 시각·DONE·pending 명령과
  REPORT를 보호함. 응답·이벤트를 Lock 안에서 만들고 실제 소켓
  송신·로그 기록·report 저장은 상태 Lock 밖에서 처리함.
  CMD는 송신 성공 콜백 뒤 실제 전달 기록을 확정함.

  ALLDONE을 고정하기 직전에도 fresh REPORT를 관측하여 주기 관측과
  마지막 DONE이 엇갈려 복제 지표가 빠지지 않도록 처리함.


  5.2 Peer와 저장소

  Main은 기동·crash·복귀·최종 정리를 담당함. control은 Tracker와
  주기 통신하고, 다운로드 worker는 env의 workers 수만큼 실행함.
  업로드는 listener와 연결별 handler, 화면은 전용 스레드를 사용함.

  Thread / 공유 자료               보호 수단
  ----------------------------------------------------------------
  control / Tracker 요청·응답       TrackerLink Lock과 소켓별 Conn
  worker / 원격 bitmap·inflight     Selection Lock
  worker / 전체 DOWN 예약 시각      공유 DOWN 제한기 Lock
  handler / 전체 UP 예약 시각       공유 UP 제한기 Lock
  worker·handler / 파일 상태        저장소 RLock과 파일별 RLock
  worker·Main / 진행 쓰기·pause      저장소 Condition과 예약 세대
  listener·handler / 연결·세대      UploadServer RLock
  로그 생산자 / JSONL·최근 버퍼     EventLog Lock
  화면 / 출력·속도 스냅샷           화면 Lock과 Peer view Lock

  청크는 reserve -> 위치 쓰기 -> bitmap 공개 순서로 처리함.
  위치 쓰기는 저장소 Lock 밖에서 수행하고 완료 후 상태를 반영함.
  같은 청크의 중복 예약을 막고 finally에서 예약·inflight를 반납함.
  Windows는 mmap, Linux는 pread/pwrite로 파일 위치를 지정함.
  해시 검사·파일 이름 변경 때는 해당 파일 접근을 직렬화하고
  Windows 매핑·파일 핸들을 닫은 뒤 rename함.


6. 청크 선택 및 속도 제한
----------------------------------------------------------------

  random은 시작할 때 전체 (file, idx) 순서를 한 번 섞어 사용함.
  rarest는 받을 수 있는 후보 중 원격 보유자가 가장 적은 청크를
  고르고 동률은 무작위로 선택함. 난수 seed는 policy_seed와 Peer
  번호로 정하며, 자기 자신과 BAN 상태의 소스는 제외함.

  청크를 가진 상대 중 inflight가 per_peer_max 미만인 소스를 고름.
  그중 가장 한가한 상대를 우선하고 동률은 무작위로 결정함.
  실패하면 해당 소스의 낡은 bitmap을 버리고 명단·bitmap을 다시
  조회함. 연속 실패가 fail_limit에 도달하면 ban_sec 동안 제외함.

  UP·DOWN은 서로 독립이며 Peer 전체가 방향마다 제한기 하나를
  공유함. KB/s를 1,024배 하여 B/s로 바꾸고 청크의 실제 길이로
  다음 전송 시각을 예약함. 대기는 제한기 Lock 밖에서 수행함.
  DOWN은 GET 전에, UP은 DATA 헤더·본문 송신 전에 적용함.
  BITMAP·REPORT·heartbeat 같은 제어 메시지는 데이터 제한에서 제외함.

  받은 청크는 디스크 반영 뒤 즉시 다른 Peer에 재공유함.
  전체 파일을 받으면 SHA-256을 검사하고 성공한 파일만 SEED로
  전환하여 REGISTER함. 해시가 다르면 bitmap·출처를 초기화하고
  한 번 더 수신함. 두 번째 불일치는 .corrupt와 FAILED로 처리함.


7. 장애 처리 및 복구
----------------------------------------------------------------

  7.1 crash와 복귀

  장애는 env 시각을 Peer가 직접 계산하지 않고 Tracker HEARTBEAT
  응답으로만 실행함. crash 때 신규 요청을 막고 저장소 세대를
  올린 뒤 진행 쓰기가 끝날 때까지 기다림. 이전 토큰의 commit은
  STALE로 거부하여 복귀 후의 청크를 덮어쓰지 않게 함.

  listener·업로드·다운로드·Tracker 연결을 닫고 지정 시간 동안
  모든 네트워크 송신을 멈춤. 디스크·bitmap·누적 전송량은 유지함.
  복귀 때 저장소와 listener를 열고 HELLO·완성 파일 REGISTER·HAVE,
  PEERS·BITMAP 강제 갱신을 마친 뒤 REJOIN과 다운로드를 재개함.
  가상 crash 시간은 tracker_lost 계시에서 제외함.


  7.2 destroy·STALLED·최종 종료

  destroy는 복귀하지 않음. 진행 통신을 닫고 모든 파일의 결과를
  저장한 뒤 BYE 없이 exit 3으로 끝남. Tracker는 dead_sec 이상
  침묵한 피어를 DEAD로 판정함.

  파일의 남은 청크 전부가 현재 받을 곳이 없고 진행 요청도 없는
  상태로 stall_sec 지속되면 STALLED로 전환함. 하나라도 소스가
  생기면 UNSTALLED·UNDONE 후 다시 받음. 모든 파일이 SEED·STALLED·
  FAILED가 되었을 때 DONE FULL 또는 DONE PARTIAL을 보냄.
  유실 하나를 발견했다고 바로 전체 다운로드를 끝내지 않음.

  정상·ABORT 종료는 신규 요청 차단 -> 진행 업로드 최대 3초 유예
  -> worker·control join -> 결과 저장 -> 필요한 BYE -> 화면 정리
  -> 마지막 EXIT 순서임. stopping 신호 뒤에도 이미 시작한 응답은
  유예하되 새 연결과 같은 연결의 후속 GET은 받지 않음.

  .bitmap은 모든 Peer·모든 파일에 청크 수만큼의 0/1을 LF 없이 씀.
  미완성은 없는 청크를 0으로 정리하고 .part를 .incomplete로 바꿈.
  .lost에는 없는 번호를 오름차순·쉼표·연속 구간 a-b로 저장함.
  완성 파일에는 .lost를 두지 않음.

  종료 코드   의미
  ----------------------------------------------------------------
  0           ALLDONE 뒤 정상 종료. FULL·PARTIAL 모두 포함함.
  1           CLI·env·원본 크기·원본 SHA-256 오류.
  2           ABORT·tracker_lost 또는 실행·정리 오류.
  3           DESTROY 지시를 받은 희생자.

  처음부터 Tracker에 닿지 않아도 tracker_lost_sec 동안 재시도하고
  결과를 정리하여 exit 2로 끝남. hang·deadline은 Tracker가 ABORT로
  알림. 개발용 Ctrl+C·SIGTERM도 Main의 정리 경로로 모음.


8. 로그 및 지표 계산
----------------------------------------------------------------

  logs/P1.jsonl~P4.jsonl과 logs/tracker.jsonl을 UTF-8·LF로 저장함.
  한 줄에 JSON 객체 하나를 쓰고 이벤트마다 flush함. 정상적으로
  정리를 마친 로그의 마지막 줄은 EXIT이며 그 뒤 기록을 막음.

  공통 필드 t는 각 프로그램 시작 후 단조 시계 기준 초, peer는
  P1~P4 또는 tracker, ev는 이벤트 이름임. Tracker report의 시각은
  네 Peer 참가가 모인 START 기준이므로 JSONL의 t와 바로 비교하지 않음.
  실제 사용 이벤트·필드는 AllDefinedLogs.txt에 별도로 정리함.

  Peer 이벤트        필드 / 기록 시점
  ----------------------------------------------------------------
  START              env, policy, up_kbps, down_kbps 및 실행 식별 정보.
  GET                file, chunks. 수신 파일 준비 뒤 한 번.
  RECV               file, idx, src. 디스크 쓰기와 bitmap 공개 뒤.
  HASH               file, ok, sec. 전체 파일 해시 검증 뒤.
  CORRUPT            file, action, tries. 재수신 또는 포기 전환.
  COMPLETE           file, sec, sources. 완성 REGISTER OK 뒤.
  FAIL / BAN         file, idx, src, err / target, sec.
  CRASH / REJOIN     sec / 추가 필드 없음. 연결 정리 / 재등록 뒤.
  DESTROY            추가 필드 없음. 희생자 결과 정리 전.
  STALLED            file, lost. 파일의 소스 부재가 지속된 첫 전환.
  UNSTALLED          file. 받을 소스가 다시 생긴 전환.
  DONE / UNDONE      kind, detail / 추가 필드 없음. Tracker OK 뒤.
  ALLDONE            done, alive. Tracker 전체 완료 확인 뒤.
  ABORT              reason, silent_sec. 중단 사유와 무응답 시간.
  ERROR              kind, operation, file, message. 로컬 실패 구분.
  EXIT               code, up_mb, down_mb. 정리 뒤 마지막 줄.

  Tracker는 START_PROGRAM·JOIN·START·REGISTER·REJOIN·BACK,
  CMD·CMD_DELIVERED·CMD_DROPPED·DEAD·REPLICATED·ALL_REPLICATED,
  DONE·UNDONE·BYE·ALLDONE·ABORT·ERROR·EXIT를 기록함.
  업로드의 청크별 SEND 로그는 두지 않고 수신자의 RECV.src로 출처를 셈.

  상태 화면은 파일마다 40칸 막대, 진행률·보유/전체 청크 수·상태와
  실측/한도 속도를 표시함. #는 전부 보유, +는 일부, .은 미보유,
  x는 STALLED의 빈 구간임. crash 동안 CRASHED로 표시하고,
  VERIFYING은 DOWN으로 표시함. 출력이 터미널이 아니면 화면을 끔.

  - 전체 진행률: 원본 제외 보유 청크 합 / progress_total_chunks.
  - 전체 평균 속도: EXIT의 누적 바이트 / 프로그램 실행 시간 / 1,024.
    up_mb·down_mb는 누적 바이트를 2^20으로 나눈 값임.
  - 수신 구간 평균: 실제 RECV 청크 길이 합 / (마지막 RECV - 첫 RECV).
    짧은 마지막 청크도 실제 길이로 계산하며 전체 평균과 구분함.
  - 출처 분포: COMPLETE.sources 또는 RECV.src를 파일·송수신자별로 셈.
    송신량 추정은 다른 Peer의 RECV.src를 합치며 시계 기준을 맞춤.
  - T_rep: 원본을 제외한 fresh live bitmap OR가 처음 모두 1인 관측 시각.
  - p_rep: 모든 파일의 복제가 관측되었을 때의 전체 진행률.
  - dup_ratio: 복제 시 원본의 (sent - distinct) / sent. sent=0은 null.
  - T_destroy·T_dead: Tracker report의 파괴 지시 등록·DEAD 판정 시각.
    실제 지시 전달 시각은 CMD_DELIVERED와 구분함.
  - 총 완료 시각·Peer별 완료 시각: report의 T_alldone·T_done.
  - C2 커버리지·유실: 생존자 bitmap의 1·0 개수를 파일별로 셈.
  - crash·실패·BAN: CRASH·FAIL·BAN 이벤트 수. 자체 취소는 FAIL 제외.

  공식 verify 외에 희생자를 포함한 모든 bitmap·lost, EXIT 마지막 줄,
  report 시각 순서, 실제 장애 수, 속도 한도와 C3 정책 일치를 대조함.
  C3 출처 분석은 Tracker START에 맞춘 실제 파괴 시점까지를 사용함.


9. 실행 결과
----------------------------------------------------------------

  9.1 실행 정보

  원격 실행 일시        :
  VM 종류·리전          :
  원격 OS / Python      :
  Tracker 공인 주소     :
  Tracker 사용 포트     :
  로컬 OS / Python      :
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


  9.4 C2 유실 및 C3 정책 비교



  9.5 실측 분석

  (1) Peer별 평균 수신 속도와 한도 대비 비율·미달 원인


  (2) P4 재공유량과 부분 재공유가 없을 때의 시간 추정


  (3) C2의 P3 원본 송출량·실제 파괴 시각·유실 청크 수 관계


  (4) C3의 복제 시각·중복률·전체 완료와 파괴 전 출처 분포


  (5) 같은 청크로 몰리는 현상을 줄이는 선택 규칙과 근거



10. 시행착오 및 한계
----------------------------------------------------------------

  10.1 수신 경계와 부분 재공유

  TCP의 recv 한 번을 메시지 하나로 보면 헤더와 본문이 붙거나
  나뉘어 도착할 때 다음 응답까지 섞임. 공통 Conn의 버퍼를 공유하고
  줄·본문·후속 줄을 순서대로 소비하도록 구성함.
  파일 완성 전에도 보유 청크를 내주므로 디스크 쓰기보다 bitmap이
  먼저 공개되지 않도록 commit의 상태 반영 순서를 고정함.


  10.2 장애와 종료의 경쟁

  세대가 다른 토큰을 거부하는 것만으로는 이전 쓰기가 새 청크를
  덮는 상황을 막을 수 없음. pause가 진행 쓰기 완료를 기다린 뒤
  복귀를 허용하도록 구성함. 종료 때는 새 요청 차단과 기존 응답
  허용을 나누어 stopping 신호가 업로드 유예를 없애지 않도록 함.


  10.3 구현 범위

  crash·destroy는 과제의 가상 장애이며 운영체제 프로세스 강제
  종료와 같은 장애 모델은 아님. 원본 해시가 잘못되면 오류로
  종료하고 원본을 임의로 고쳐 실행하지 않음. 스케줄링·네트워크
  도착 순서가 달라질 수 있으므로 같은 정책 seed가 전체 실행의
  청크 출처·완료 시간을 똑같이 보장하지는 않음.

  복제 지표는 최근 live REPORT를 관측한 값임. 보고하지 않았거나
  유효기간이 지난 데이터를 완성 추정치로 채우지 않음.
  로컬 검사와 외부 VM 구성의 실제 제출 실행은 구분함.


  10.4 추가 구현 및 배운 점

  Peer 일괄 실행, 결과 보관, 공식 verify가 보장하지 않는 기록의
  추가 검사를 도구로 구성함. 대역 검사와 실제 구성요소의 TCP
  검사를 나누어 개별 기능뿐 아니라 호출 순서도 확인하도록 함.

  정상 수신만 맞추는 것보다 쓰기 도중의 crash와 종료 직전 응답을
  다루는 일이 중요했음. 예약 세대·소켓 세대·종료 상태를 나누고
  마지막 결과를 누가 확정하는지 정해야 데이터와 로그가 맞았음.


11. 제출 파일 배치
----------------------------------------------------------------

  src/                 실행 작업 폴더. 아래 src/와 tools/를 포함함.
    src/common/        공유 자료형과 TCP 수신 버퍼
    src/tracker/       Tracker 전체 소스
    src/peer/          Peer 제어·다운로드 전체 소스
    src/storage/       청크 저장소·해시·결과 저장
    src/upload/        업로드 서버·속도 제한기·화면
    tools/             Peer 실행·결과 수집·추가 검사

  runs/DEV/            DEV의 결과 기록
  runs/A/ ~ C2/        A·B·C1·C2의 결과 기록
  runs/C3_random/      C3 random 결과 기록
  runs/C3_rarest/      C3 rarest 결과 기록

  각 Run 폴더의 구성
    logs/              P1.jsonl~P4.jsonl, tracker.jsonl
    report.json        Tracker의 복제·장애·완료 지표
    verify.txt         해당 실제 실행의 공식 verify 출력
    p1/ ~ p4/          모든 파일의 .bitmap과 필요한 .lost

  AllDefinedLogs.txt   사용한 모든 로그 이벤트·필드·단위·기록 시점
  download.txt         시연 영상 링크
  Readme.txt           프로그램 설명 및 실행 결과

  Peer별 결과 폴더는 희생자도 포함함. 완성 데이터·.incomplete·
  .corrupt·원본 data·키·임시 파일은 제출 기록에 넣지 않음.
  .incomplete는 공식 verify가 끝날 때까지 실행 폴더에 보존함.
