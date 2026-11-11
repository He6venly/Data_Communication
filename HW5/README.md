# HW5 Card Duel League

데이터통신 2조 개발 기준임. 담당, 공통 인터페이스, TEAM 전략을 확정함. `hw5/server`에서는 Server를 구현하고 대역 Player로 A·B·C를 검증함. 실제 Player·Crasher 통합과 원격 Run은 검증 전임.

공식 기준은 `HW5description.pdf`임. `HW5explanation.pdf`는 세부 구현과 로그를, `HW5QnA.pdf`는 해석과 제출 구성을 확인할 때 사용함. 원본 설정과 정답은 `HW5_student_kit/`를 사용함.

## 확정 담당

| 담당 | 브랜치와 소유 경로 | 구현 범위 | 단독 검증 |
| --- | --- | --- | --- |
| 안선효 | `hw5/server` · `src/server/` · `tests/server/` · `tests/integration/` | Server, Lobby·Table, 판정·점수, 결과 파일·실측 지표, 통합·원격 실행·최종 제출 취합 | 대역 Player 10개로 매칭, 정상·지연·위반·부전패, 파일 검사 |
| 황대겸 | `hw5/player` · `src/player/` · `tests/player/` | Player, 표준 bot·TEAM, 검산·CONFIRM, Run C 고장, Run D 상태·제어 | kit bot 41건과 TEAM 기준 hash, 대역 Server·Crasher로 송신·침묵·복귀·종료 검사 |
| 황왕석 | `hw5/crasher-tools` · `src/crasher/` · `tools/launch_players.py` · `tests/crasher/` · `tests/tools/` | Crasher C1–C8, 원본 설정으로 Player 10개를 띄우는 스크립트, 로그 취합과 kit 검증 지원 | 대역 Player 10개로 대상 선택·ACK·복귀 검사. launcher는 대역 실행 명령과 kit 설정으로 검사 |

각 담당이 자기 브랜치에서 자기 경로와 필요한 대역을 관리함. Server·Player·Crasher는 자기 패키지와 Python 표준 라이브러리만 import함. 접점은 아래 TCP 메시지·CLI·파일·로그와 공식 설정임. 인터페이스 변경이 필요하면 명세 근거를 대조하고 관련 담당과 README를 먼저 맞춤. 통합 단계에서 실제 프로그램을 별도 프로세스로 실행함.

## 구현 범위

Python 3.12 이상과 표준 라이브러리를 사용함. 구현 대상은 Server, Player, Crasher와 Player 실행 스크립트 1개임. 검증은 제공 kit와 담당별 대역을 사용함.

| 항목 | 과제 필수 조건 |
| --- | --- |
| 배포·연결 | 원격 Server 1개, 로컬 PC 한 대의 Player 10개 독립 프로세스, Run D에서 같은 PC의 Crasher 1개. 게임은 Server–Player TCP Star, 제어는 Crasher–Player TCP |
| 스레드·동기화 | Server Main 1 + START 직후 생성하는 Table M개. 공유 상태 Mutex 1개, 같은 Mutex에 연결한 `lobby_cv`·`done_cv` 두 개. 로그 Lock은 별도 |
| 경기·점수 | P1–P10의 모든 쌍 45경기, 각 10판. 작은 번호가 A. 각 경기에서 카드와 상금은 각각 1–10. 큰 카드가 상금 획득, 동률이면 상금 소멸. 승 3·무 1·패 0. 순위는 PTS·득실차·득점 내림차순, 선수 번호 오름차순 |
| 실행값 | 리그 seed 2026, COMMIT·REVEAL·CONFIRM 단계별 3,000ms, ROUND 수신 후 카드 선택 전에 18–22ms 균등 무작위 대기. M은 1–5 지원 |
| 전략 배치 | P1/P2 RANDOM, P3/P4 MATCH, P5/P6 PLUS1, P7/P8 BIGSMALL, P9/P10 TEAM. 샘플 설정의 P9/P10은 RANDOM |
| 판정 | SHA-256 Commit–Reveal. Player가 공개 hash·판정·누적 점수를 직접 계산해 CONFIRM 전송 |
| 장애 | 명세의 가상 crash·quit. 프로세스와 TCP 연결은 BYE까지 유지 |
| 제출 Run | A는 M=1, B/C/D는 M=4. A/B/D는 `players_std.txt`, C는 `players_fault.txt`. 샘플 검증은 `players_sample.txt` |

팀 설계는 Server의 Main·Table만, Player의 게임 스레드와 Run D 제어 스레드 1개, Crasher의 제어 수신·사건 대기·복귀 예약으로 구성함. Crasher 공유 상태는 Mutex·Condition으로 처리함. 로그 시각은 KST, 경과 시간은 단조 시계로 측정함. 설정값은 실행 인자와 kit 설정으로 받음.

### 패키지와 파일 구성

아래는 구현할 파일과 역할임. 실행은 저장소 `HW5/`에서 하며 `src/`, `tools/`와 그 하위 실행 패키지는 Python 네임스페이스 패키지로 둠.

```text
HW5/
├── README.md
├── .gitignore
├── src/
│   ├── server/                 안선효
│   │   ├── __main__.py          CLI 인자와 Server 실행
│   │   ├── league.py            접속, Lobby, Table 스레드, 리그 종료
│   │   ├── match.py             게임 메시지, 단계별 마감, 몰수·부전패
│   │   ├── rules.py             대진, seed·LCG·상금, 점수·순위 계산
│   │   └── output.py            결과 파일, Server 로그, 지표 저장
│   ├── player/                 황대겸
│   │   ├── __main__.py          CLI 인자와 Player 실행
│   │   ├── client.py            게임 TCP, 검산·CONFIRM, Run C 고장, Player 로그
│   │   ├── bots.py              kit 호환 bot API, seed·LCG·상금, 표준·TEAM 전략
│   │   └── control.py           Run D 제어 TCP, 대기 명령·침묵·복귀 상태
│   └── crasher/                황왕석
│       ├── __main__.py          CLI 인자와 Crasher 실행
│       ├── controller.py       제어 TCP, Player 상태·ACK, Crasher 로그
│       └── scheduler.py        C1–C8 사건 계획, 대상 선택, 복귀 예약
├── tools/
│   └── launch_players.py       kit 설정을 읽어 Player 10개 실행
└── tests/
    ├── server/
    │   └── test_server.py      대역 Player, 매칭·판정·타임아웃·파일
    ├── player/
    │   ├── test_bots.py        공식 kit와 TEAM 기준 hash 대조
    │   └── test_player.py      대역 Server·Crasher, 게임·장애·종료
    ├── crasher/
    │   └── test_crasher.py     대역 Player, 주입·ACK·복귀·종료
    ├── tools/
    │   └── test_launch_players.py  kit 설정과 대역 실행 명령
    └── integration/
        └── test_league.py      실제 프로세스와 TCP, Run 결과 대조
```

대역과 소규모 검사 데이터는 담당 테스트 파일에 둠. kit 검증 스크립트는 배포본에서 실행함.

## 공통 계산과 bot

```text
pairs = [(a,b) for a in 1..10 for b in a+1..10]
seed_of(text) = int(SHA256(UTF8(text)).hexdigest()[:8], 16) mod 2^31
LCG: x = seed mod 2^31
next(): x = (1103515245*x + 12345) mod 2^31; return x >> 16
prize_order(S,mid): [1..10], LCG(seed_of("S:mid")), i=9..1,
                   j=next() mod (i+1), swap(a[i],a[j])
RANDOM: LCG(seed_of("S:mid:k")), 매 판 hand[next() % len(hand)]
TEAM 난수를 쓸 경우: LCG(seed_of("S:mid:k:TEAM")) 하나만 사용
```

이름표의 숫자는 0을 붙이지 않은 10진수이며 공백 없음. 생성기는 경기마다 새로 만들고 테이블 번호·A/B 자리를 넣지 않음. Player의 S는 WELCOME에서 받음. RANDOM은 마지막 한 장일 때도 판마다 정확히 한 번 next() 호출함.

### 고정 seed의 정답과 적용 범위

| 샘플 설정(P9/P10=RANDOM)의 seed | results hash | standings hash | 독립 계산 대조 |
| --- | --- | --- | --- |
| 2026 | `cfde2bce` | `c8a0c732` | 정답·제공 A/B 파일과 일치 |
| 7 | `f11a9a2e` | `ceb40a34` | bot_tests의 정답과 일치 |

상금·RANDOM의 시드는 경기 순서나 테이블 배정과 독립적임. A/B에서 같은 두 파일은 results·standings임. C/D의 장애 결과는 적용 순서에 따라 달라질 수 있음.

Player bot의 kit 연결 규격은 kit와 같은 `seed_of(text)`, `LCG(seed).next()`, `prize_order(S, mid)`, `Bot(strategy, S, mid, k)` 및 `choose(prize,r)`, `play(prize,r,my_card,opp_card)`로 정함. `choose()`는 손패를 바꾸지 않고 REVEALS 뒤 `play()`에서 제거함. 손패는 항상 오름차순임.

| 전략 | 선택 규칙 |
| --- | --- |
| MATCH | 이번 상금과 같은 카드 |
| PLUS1 | 상금보다 큰 남은 카드 중 최소, 없으면 손패 최소 |
| BIGSMALL | 상금≥6이면 손패 최대, 그 외 최소 |
| TEAM | 남은 최고 상금에 손패의 최고 카드를 사용하고, 그 전에는 다른 카드로 승부 |

TEAM 함수는 `team_choose(p,r,hand,history,prizes_left,rng)`로 제한함. history는 `(r,p,내 카드,공개된 상대 카드)`이며 상대 번호·전략·자리·mid·k·S를 전달하지 않음. TEAM 선택 입력은 이번 경기 상태로 한정함. S/mid/k는 난수를 사용하는 전략의 이름표 구성에만 사용함.

### TEAM 최고 카드 보존

미처리 상금 중 최댓값이 나올 때까지 손패의 최고 카드를 남겨 둠. 미처리 상금은 1–10에서 처리한 판의 상금만 제외한 집합이며 현재 상금도 포함함.

1. 현재 상금이 미처리 상금의 최댓값이면 손패의 최고 카드를 냄.
2. 그 외에는 최고 카드를 제외하고, 상금보다 2 이상 큰 카드 중 최솟값을 냄.
3. 조건에 맞는 카드가 없으면 손패의 최솟값을 냄.

예를 들어 손패가 2·6·9이고 미처리 상금이 4·7·10이면, 상금 4에는 6을 내고 9는 남겨 둠. 상금 10이 나오면 그때의 최고 카드를 냄. 카드와 상금은 REVEALS를 확인한 뒤에만 제거함. 선택에 필요한 값은 현재 상금, 미처리 상금의 최댓값, 내 손패임. 난수 호출은 0회임.

kit 방식대로 `mid=seed%45`를 사용했으며, 범위별로 상대마다 A/B 자리에서 각 1,000경기씩 치름.

| 상대 | seed 1–1000 승/무/패 | 승률 | seed 1001–2000 승/무/패 | 승률 |
| --- | --- | ---: | --- | ---: |
| RANDOM | 1458 / 75 / 467 | 72.9% | 1459 / 51 / 490 | 72.95% |
| MATCH | 1636 / 36 / 328 | 81.8% | 1656 / 28 / 316 | 82.8% |
| PLUS1 | 1662 / 10 / 328 | 83.1% | 1684 / 10 / 306 | 84.2% |
| BIGSMALL | 1722 / 42 / 236 | 86.1% | 1702 / 34 / 264 | 85.1% |

seed 2026의 정식 전략 구성에서 통신 없이 45경기를 정순·역순으로 실행해 경기별 결과가 일치함. 자체 기준 hash는 results `5255a2bf`, standings `6a4147b7`임. G44의 TEAM 대 TEAM은 `0:0 DRAW`였음.

## TCP·단계별 처리 계약

한 줄 ASCII, 공백 1칸, 끝 LF. TCP 분할·합쳐진 수신에 대응하는 소켓별 바이트 버퍼를 사용함. 게임 메시지의 mid/r은 정수, 결과·match_log의 mid는 두 자리, 사람이 읽는 로그는 `Gxx`임.

| 방향 | 메시지 |
| --- | --- |
| P→S | `HELLO Pk STRATEGY` |
| S→P | `WELCOME Pk seed timeout_ms`, `START 45` |
| S→P | `MATCH mid side opp`, `ROUND mid r prize` |
| P→S | `COMMIT mid r hash` |
| S→P | `COMMITS mid r hA hB` |
| P→S | `REVEAL mid r card nonce` |
| S→P | `REVEALS mid r cA nA cB nB winner sA sB` |
| P→S | `QUIT mid`, `REJOIN Pk` |
| S→P | `FORFEIT mid who reason`, `MATCH_END mid outcome sA sB` |
| P→S | `CONFIRM mid sA:sB` |
| S→P | `LEAGUE_END rank pts`, `BYE` |

`opp`는 `P번호`, side/winner는 A/B이며 판 비김 winner는 `-`. nonce는 매 판 `secrets.token_hex(8)`, hash는 `sha256(f"{card}:{nonce}".encode("ascii")).hexdigest()`임. nonce는 REVEAL 전 송신하지 않음.

Server는 두 COMMIT 수신 후 COMMITS, 두 REVEAL 검사 후 REVEALS를 보냄. REVEAL 검사 순서는 **칸 수·카드 정수 → hash 일치 → 손패 포함**임. 첫 사유 하나만 적용하며 hash 길이·nonce 길이를 별도 BAD_MSG 사유로 추가하지 않음. COMMIT은 칸 수 4개, REVEAL은 5개임. 종류·mid·r이 다른 줄은 STALE로 버리고 같은 deadline으로 계속 기다림. REJOIN은 로그만 남김.

ROUND·COMMITS·MATCH_END를 두 선수에게 각각 송신한 뒤 단계마다 같은 절대 deadline을 적용함. 먼저 받은 정상 응답은 상대가 침묵해도 인정함. 마감 시 양쪽 수신 버퍼의 완성 줄을 확인하고 늦은 줄은 STALE로 처리함. CONFIRM은 일치 `OK`, 지연 `NO`, 불일치 `DISPUTE`, DEAD 또는 QUIT `-`로 기록함. QUIT은 이후 DEAD로 처리하고 해당 경기 점수는 유지함.

Player는 상대 COMMIT hash와 공개 카드·nonce를 비교하고 판 winner·누적 점수를 직접 계산함. MATCH_END 점수를 복사하지 않음. 몰수는 FORFEIT의 who로 자체 기록 점수를 결정함.

## Lobby·장애·종료 계약

### Server

1. Main이 HELLO의 번호 1–10·중복을 검사하고 WELCOME 전송. 10명이 모이면 START, Table M개 생성
2. Lock 안에서 두 선수 모두 PLAYING이 아닌 PENDING 경기 전체 중 무작위 하나 선택. DEAD가 낀 경기에도 같은 예약 규칙 적용
3. 두 소켓을 Table 하나에 예약하고 assigned 증가, Lock 밖에서 경기 수행. 수신 잔여 버퍼는 Table 지역 변수가 아닌 Player 레코드에 보존
4. 영구 이탈 여부는 테이블 예약과 구분해 보존함. DEAD를 예약 중 PLAYING으로 표시하더라도 기존 DEAD 정보가 사라지지 않게 별도 dead 값 또는 예약 전 스냅샷을 유지함
5. Lock 안에서 결과·match_log·지표와 DEAD/IDLE 복귀·finished 갱신. 매 종료마다 `lobby_cv.notify_all()`, finished=45이면 `done_cv.notify()`
6. 후보가 없으면 while 조건으로 lobby_cv 대기, assigned=45이면 Table 종료. Main은 finished=45 대기 후 Table 모두 join
7. Lock 밖에서 파일 저장·hash 계산, 순위 순서로 LEAGUE_END·BYE 전송. DEAD에는 BYE만 전송. 실제 지표와 TERMINATE 후 종료

공유 상태 Lock 안에서 send/recv·sleep·파일 저장·로그 I/O를 수행하지 않음. 로그 Lock은 공유 상태 Lock과 중첩하지 않음. 매칭 난수는 상금·bot LCG와 분리함.

### 몰수·Run C

| 상황 | 결과 |
| --- | --- |
| COMMIT/REVEAL TIMEOUT·BAD_MSG·BAD_HASH·BAD_CARD·QUIT | 해당 선수 몰수, QUIT 사유는 DISCONNECT이며 영구 DEAD |
| A만 위반 / B만 위반 | FORFEIT_A 0:55 / FORFEIT_B 55:0. 이전 판 점수 폐기 |
| 양쪽 위반·양쪽 DEAD | FORFEIT_BOTH 0:0, 양쪽 모두 L·승점 0. DRAW와 구분 |
| 이전 QUIT 선수와의 경기 | 살아 있는 상대에게 MATCH·ROUND 1 후 COMMIT으로 출석만 확인. 종류·mid·r만 확인하고 hash·칸 수 검사 생략 |
| 출석 성공 / 상대도 침묵·QUIT | DEAD 쪽 부전패 / FORFEIT_BOTH. F 줄의 r=0 |

FORFEIT는 위반한 선수도 포함해 DEAD가 아닌 두 선수에게 전송한 뒤 MATCH_END·CONFIRM을 처리함. BOTH 사유는 A사유+B사유, 같으면 하나만 기록함.

| Player | 고정 고장 | 필수 결과 |
| --- | --- | --- |
| P2 | `slow@11,4`: ROUND 후 timeout+1초 대기 뒤 정상 COMMIT | `F 11 4 A TIMEOUT`, 늦은 COMMIT은 STALE |
| P5 | `badcard@30,7`: 카드 11로 올바른 COMMIT·REVEAL | `F 30 7 A BAD_CARD` |
| P7 | `badhash@40,3`: 정상 COMMIT 후 다른 카드 `c%10+1` 공개 | `F 40 3 A BAD_HASH` |
| P8 | `quit@21,6`: COMMIT 대신 QUIT, BYE까지 유지 | `F 21 6 B DISCONNECT`, 이후 배정 경기 r=0 부전패 |

Run C hash·P8 부전패 개수·최종 전적은 매칭 순서에 따라 달라짐. 예제의 P8 0승9패·부전패 8개를 고정 기대값으로 쓰지 않음. QUIT 전에 끝난 경기 결과는 유지함.

### Crasher·Player Run D

제어 메시지는 `CTRL Pk`, `STATE Pk PLAYING mid`, `STATE Pk IDLE`, `STATE Pk CRASHED mid`, `STATE Pk QUIT`, `STATE Pk END`와 반대 방향 `CRASH`·`RESTART`·`QUIT`임. Player는 WELCOME 뒤 Crasher에 접속함. Crasher를 Player보다 먼저 기동함.

- C1. Player 10개의 CTRL 접속 대기. seed 생략 시 무작위이며 사용한 seed와 계획을 로그 첫 PLAN에 기록
- C2. 장애 4–7건·quit 1–2건·나머지 crash, 종류 순서 무작위
- C3. 발생 기준은 종료 경기 수 근사값 2–30에서 무작위로 정함. PLAYING→IDLE 횟수÷2로 추적하고 전원이 END 또는 QUIT이면 사건 주입 대기를 끝냄
- C4. 현재 PLAYING이며 본인·상대가 장애 중이 아닌 선수 중 무작위 선택. crash·영구 quit·아직 적용되지 않은 명령 대기까지 장애 집합에 포함
- C5. 대상 선택 후 0–0.3초 대기, 송신 직전 Lock 안에서 같은 경기·자격 재검사. 바뀌면 다시 선택
- C6. `STATE Pk CRASHED mid` ACK 수신부터 무작위 4–5초 뒤 RESTART. 여러 crash의 복귀를 독립 예약하며 IDLE 확인 후 장애 집합에서 제거
- C7. quit은 영구 장애로 유지하고 재선택하지 않음
- C8. 모든 Player의 END 확인 후 요약·TERMINATE. 종료 판정용 END/QUIT과 실제 프로세스 종료용 END를 구분함

Player는 MATCH에서 PLAYING 보고 후 대기 명령을 적용함. IDLE 중 받은 CRASH/QUIT은 INFO 기록 후 다음 MATCH에서 실행하며, 실제 적용에만 WARN을 한 번 기록함. 게임 송신 직전 mode 검사와 송신을 같은 Player 상태 Lock 안에서 수행하여 think 중 crash 뒤 COMMIT이 새지 않게 함. 이 Lock은 Server의 공유 상태 Lock과 다른 로컬 Lock임.

CRASHED·QUIT 상태에서도 게임 소켓을 읽어 BYE 외 줄은 버림. RESTART 시 이미 쌓인 사용자·소켓 수신 데이터를 비우고 REJOIN·STATE IDLE을 보낸 뒤 **새 MATCH부터** Bot을 생성함. crash 중 버린 MATCH의 경기는 복귀 시점이 마감 전이어도 새 MATCH가 올 때까지 무시함. Server는 REJOIN을 기록하고 기존 단계의 마감까지 대기함.

QUIT은 게임 소켓으로 `QUIT mid`를 보내고 BYE까지 유지함. BYE 시 QUIT 선수도 `STATE END`와 TERMINATE를 남김. 마지막 경기 crash·리그 종료 중 restart·제어 EOF를 검사해 제어 스레드/타이머가 종료를 막지 않게 함. 일정상 두 장애 선수가 만나는 경기는 FORFEIT_BOTH 규칙으로 처리함.

## 파일·필수 로그

`run_X/`의 `X`는 A, B, C, D 중 하나임. 실행 주체별 파일명은 아래와 같음.

| 주체 | 파일명 |
| --- | --- |
| Server | `RunX_results.txt`, `RunX_standings.txt`, `RunX_match_log.txt`, `RunX_League.txt` |
| Player | `RunX_P1.txt`부터 `RunX_P10.txt`까지 |
| Crasher | `RunD_Crasher.txt` (Run D) |

Run 폴더의 모든 출력은 ASCII·LF로 저장하고 마지막 줄도 LF로 끝냄. hash8은 **실제 파일 전체 바이트 SHA-256의 앞 8자리 소문자**임. Windows의 CRLF 자동 변환을 피하도록 `newline="\n"` 또는 바이너리 저장 사용함.

```text
RunX_results.txt      45줄, mid 오름차순: 18 P3 P5 10:45 WIN_B
RunX_standings.txt    10줄, 순위순: 1 P6 8 1 0 25 261 132
RunX_match_log.txt:
LEAGUE seed=2026 tables=4
MATCH 18 P3 P5 table=4 t=6.856
R 18 r prize cA nA hA cB nB hB winner sA sB
F 18 r who reason
END 18 outcome sA:sB t=7.539
```

match_log는 경기 mid순, R은 판순, F는 몰수 시에만 기록함. t는 START 이후 같은 Server 단조 시계의 초임. nonce 16자리와 hash 64자리를 그대로 기록함.

공통 로그 외형은 `[HH:MM:SS.mmm] NODE | EVENT | STATUS | message`임. NODE는 SERVER/Pk/CRASHER, STATUS는 SUCCESS/FAIL/INFO/WARN. 고정 앞부분 뒤에 필요한 값만 붙임.

| 노드·EVENT·STATUS | message 고정 앞부분 |
| --- | --- |
| SERVER MATCH INFO | `Gxx Pa(전략) vs Pb(전략) table=t` |
| SERVER RESULT SUCCESS | `Gxx Pa sA:sB Pb OUTCOME confirm=X/Y` |
| SERVER FORFEIT WARN | `Gxx Pa vs Pb round=r forfeit=WHO reason=R` |
| SERVER DISCONN WARN | `Pk QUIT ... in Gxx ...` |
| SERVER REJOIN INFO | `Pk rejoined (waiting KIND mid ...)` |
| SERVER SAVE SUCCESS | `RunX_results.txt hash=h8 RunX_standings.txt hash=h8` |
| Pk CRASH/QUIT WARN | `Gxx r=n last=L ...` |
| Pk REJOIN INFO | `REJOIN sent ...` |
| Pk TERMINATE SUCCESS | `rank=r pts=p Ww Dd Ll` |
| Pk TERMINATE WARN | `left at Gxx ...` |
| CRASHER PLAN INFO | `seed=S events=F (crash C, quit Q)` |
| CRASHER CRASH/QUIT WARN | `#n Pk (PLAYING Gxx)` |
| CRASHER CRASH_ACK INFO | `#n Pk crashed in Gxx` |
| CRASHER RESTART INFO | `#n Pk after d.dds` |
| CRASHER REJOINED/QUIT_ACK INFO | `#n Pk back to IDLE` / `#n Pk reported QUIT` |
| CRASHER SUMMARY INFO | `fired F/F events: crash C, quit Q` |
| CRASHER TERMINATE SUCCESS | `all players ended` |

SERVER의 INIT·CONNECT·START·TABLE·METRICS·TERMINATE, Player의 CONNECT·MATCH·RESULT·FORFEIT·FAULT·VERIFY 등 실제 사용하는 모든 EVENT도 기록·정의함. Server의 `METRICS INFO`에는 실행시간·동시 경기 수, 테이블별 가동률·대기, 두 COMMIT을 수신한 판의 지연, 몰수·부전패·STALE·CONFIRM 수, 전략별 전적·평균 득점을 기록함. Run C quit은 Player `FAULT WARN`, Run D quit은 `QUIT WARN`임. 장애 전 마지막 ROUND 번호가 없으면 r=0, 마지막 송신 종류가 없으면 last=-임. 종료한 Player의 TERMINATE는 마지막 줄로 유지함.

## 실행과 검증

개발 실행은 저장소 `HW5/`에서 함. `SERVER_IP`·`KIT`·`RESULTS`·`LOCAL_LOGS`는 실제 값으로 바꿈. Server 단독 검증은 `python -m unittest discover -s tests/server -v`로 실행함. kit가 개발저장소 옆의 `HW5_student_kit/`에 없으면 `HW5_KIT_DIR`에 kit 경로를 지정함.

```text
python -m src.server --host 0.0.0.0 --port 9500 --seed 2026 --tables 1 --timeout 3000 --run A --out "RESULTS/run_A"
python -m tools.launch_players --host SERVER_IP --port 9500 --config "KIT/4_config/players_std.txt" --think 18,22 --run A --out "LOCAL_LOGS/run_A"

python -m src.player --host SERVER_IP --port 9500 --id 3 --strategy MATCH --think 18,22 --run B --out "LOCAL_LOGS/run_B"
python -m src.crasher --host 127.0.0.1 --port 9700 --run D --out "LOCAL_LOGS/run_D" --seed 11
python -m tools.launch_players --host SERVER_IP --port 9500 --config "KIT/4_config/players_std.txt" --think 18,22 --run D --out "LOCAL_LOGS/run_D" --crasher 127.0.0.1:9700
```

B/C/D는 Server의 `--tables 4`와 해당 Run·경로를 지정함. launcher는 kit의 `번호 전략 [고장]`을 읽어 Player 10개를 독립 프로세스로 실행하고, C의 고장 열을 `--fault 종류@mid,r`로 전달함. D는 Server·Crasher·Player 순으로 기동함. Run마다 새 폴더를 사용하고 Server·Player·Crasher 출력을 같은 Run 폴더에 모음.

1. 각 담당이 대역 검사와 kit로 자신의 프로그램을 확인함. bot 테스트는 kit 임시 사본의 mybots 어댑터로 `src.player.bots`를 연결함. 표준 41건 ALL PASS와 샘플·TEAM 기준 hash를 확인함.
2. 실제 TCP를 로컬에서 샘플 설정으로 M=1·2·4에서 확인함. results `cfde2bce`·standings `c8a0c732`, overlap 0이 기준임. 정식 설정 A/B는 파일 바이트와 자체 기준 `5255a2bf`·`6a4147b7`을 대조함.
3. 로컬 C에서 고장 4건의 판·사유·점수와 QUIT 이후 부전패를 확인함. D는 seed를 바꿔 실행하고 Crasher 사건과 영향을 대조함.
4. 제출용 A–D는 원격 Server와 로컬 Player·Crasher에서 실행함. 각 Run은 45경기·판 오류 0·overlap 0·verify PASS, A/B는 results·standings 동일·정상 CONFIRM `OK/OK`·VERIFY FAIL 0건, D는 chaos PASS가 기준임. 끝까지 참여한 Player의 TERMINATE 순위·승점·W/D/L을 standings와 대조함.

제공 `2_tools/python/`의 세 파일을 같은 작업 폴더에 두고 실행함. 아래 RESULTS는 Run 폴더가 모인 실제 경로임.

```text
python verify_league.py "RESULTS/run_A"
python verify_league.py "RESULTS/run_B"
python verify_league.py "RESULTS/run_C"
python verify_league.py "RESULTS/run_D"
python check_chaos.py "RESULTS/run_A" "RESULTS/run_D"
python make_compare.py 2 "RESULTS/run_A" "RESULTS/run_B" "RESULTS/run_C" "RESULTS/run_D"
```

A/B/C는 파일 14개, D는 Crasher 로그까지 15개임. verify는 D에서도 기본 14개를 검사하므로 chaos의 15개 검사까지 확인함. 출력의 PASS와 실제 파일의 LF·hash를 함께 대조함. 이전 확인 범위는 제공 A/B/D의 verify·A/D의 chaos, 독립 기준 계산의 bot 41건과 샘플 hash, TEAM 오프라인 실측임.

## 실측·분석과 최종 제출

Server 최종 로그와 제출 Readme에 다음을 실제 측정값으로 기록함.

- START 전송부터 마지막 경기 CONFIRM 처리 종료까지 총 실행시간, MATCH 전송부터 CONFIRM 처리 종료까지의 경기 평균·최소·최대
- 테이블별 경기 수·가동률(경기시간 합/총시간)·lobby_cv 대기시간, 평균 동시 경기 수(전체 경기시간 합/총시간)
- ROUND 송신부터 두 COMMIT 도착까지의 응답 지연 평균·최대. timeout 판은 누락·성공 표본과 구분해 집계 방법 명시
- 사유별 몰수·부전패·STALE·CONFIRM OK/NO/DISPUTE/- 수, 전략별 W/D/L·평균 득점
- A/B 시간 비·하한·tail·유휴 테이블, 로컬/원격 지연과 think를 뺀 나머지 지연, TEAM 상성·강약 분석
- D의 사건 목록·crash/quit 수·복귀 간격·영향 경기. `(D 총시간-B 총시간)/crash 수`는 quit·매칭 변화가 섞인 비교 평균으로 표시하고 순수 crash 인과 효과로 단정하지 않음

제출 구성은 Q&A Q5·Q8을 따름. 실행 시 kit의 원본 설정을 경로로 지정함. 설정 파일은 ZIP 밖의 kit에 둠.

```text
G2HW5.zip
├─ src/                 전체 프로그램과 실행 보조, 실제 실행 방법
├─ run_A/               RunA_results, standings, match_log, League, P1–P10 (14개)
├─ run_B/               같은 구성, RunB_ (14개)
├─ run_C/               같은 구성, RunC_ (14개)
├─ run_D/               같은 구성, RunD_ + RunD_Crasher.txt (15개)
├─ compare_result.txt
├─ AllDefinedLogs.txt
├─ download.txt
└─ Readme.txt
```

제출 `src/` 아래에 저장소의 `src/`와 `tools/launch_players.py`를 같은 상대 경로로 넣음. 압축을 푼 뒤 제출 `src/`에서 위 실행 명령을 사용함. 제출 문서는 실제 코드·명령·실측값을 기준으로 작성함.

제출 Readme.txt에는 이름·학번·역할, 서비스·인스턴스·OS·시간대, 설치·실행·kit 준비, 구조·메시지·Thread/Lock/CV, timeout·stale·부전패, TEAM 규칙·의도·상성표, 지표·정합성·Run D 분석, 한계·느낀 점을 포함함. AllDefinedLogs.txt는 실제 사용하는 모든 EVENT·STATUS·필드·단위를 정의함.

약 5분 `G2HW5.mp4`에는 원격 시작·10명 접속·4테이블 동시 진행·Run C 몰수/부전패·Run D crash/복귀/quit과 Crasher/Server 로그·verify/chaos/compare 확인을 포함함. download.txt의 링크를 비로그인 다운로드·재생으로 확인함. 최종 ZIP은 새 폴더에 풀어 Readme의 실행 명령과 파일 구성을 확인함.

Git에는 소스·개발 README·필요 설정을 관리함. kit 원본·실행 산출물·키·영상은 각 실행 환경에 보관함.
