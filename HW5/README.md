# HW5 - Card Duel League

2026학년도 2학기 데이터통신 2조.

현재는 자료 검토·개발 계획 수립 단계임. Server·Player·Crasher와 자체 테스트는 아직 구현하지 않았으며, 아래 소스 구조·명령·완료 기준은 개발 계약임. 제공 샘플의 PASS를 자체 구현의 PASS로 사용하지 않음.

## 기준 자료와 확인 결과

| 구분 | 자료·확인 내용 |
| --- | --- |
| 공식 요구사항 | `HW5description.pdf` 32쪽. 규칙·필수 구현·Run·검증·제출 기준 |
| 상세 설명 | `HW5explanation.pdf` 179쪽. 난수·프로토콜·Lobby·장애·의사코드·필수 로그 |
| 해석 보충 | `HW5QnA.pdf` 19쪽. 설정 원본 사용, 제출 구성, TEAM 제한, crash 복귀 범위 등 |
| 제공 kit | `HW5_student_kit/` 76개 파일. README, bot 테스트, Python/C/Java 도구, 샘플 A/B/D, 설정 3종 |
| 정리 지침 | 로컬 `제출물정리_AGENTS.md`와 작업 지침. 원본·사용자 변경 보존, 실제 실행 근거로만 완료 판정 |
| 저장소 설정 | 기존 `.gitignore`의 Python 캐시·키 제외 규칙 유지. HW5 산출물 제외 규칙은 이 폴더에 한정 |

명세가 우선이며, 강의자료와 Q&A는 같은 규칙의 설명으로 사용함. 코드 편의 때문에 필수 조건을 바꾸지 않음. 충돌이 실제 동작·평가에 영향을 주는 경우 해당 절과 재현 예를 먼저 제시함.

제공 자료 검사 결과:

- kit Python 소스 7개의 문법 검사 통과. 설정 3개는 각각 10줄, LF, BOM 없음 확인
- 제공 `3_sample/run_A`, `run_B`, `run_D`에 Python `verify_league.py` 실행: 모두 45/45, 판 오류 0, overlap 0, results·standings MATCH, PASS
- 샘플 A/B의 results hash `cfde2bce`, standings hash `c8a0c732` 일치. 샘플 D는 `c28d4996`, `2bccc0ee`
- 제공 A/D에 `check_chaos.py` 실행: files 15/15, crash 5 + quit 2, `CHAOS D -> PASS`
- 원본 Python `bot_test.py`: **0 PASS / 41 FAIL, SOME FAIL**. `mybots.py`가 TODO 템플릿이므로 예상된 미구현 결과임. 종료 코드 0도 통과를 의미하지 않음
- 별도의 임시 독립 기준 계산을 메모리에서 공식 `bot_test.py`에 연결해 정답 41건 대조: **41 PASS / 0 FAIL, ALL PASS**. SEED 6·LCG 4·PRIZE 10·BOT 12·MATCH 7·LEAGUE 2건 모두 일치. kit 템플릿과 프로젝트 구현은 수정하지 않았으며 자체 프로그램의 구현 완료를 의미하지 않음
- 독립 계산의 seed 2026 리그 결과·순위를 제공 샘플 A/B와 바이트 단위로 비교해 일치 확인. seed 7의 두 리그 hash도 정답과 일치
- C/Java는 구성·함수 계약·빌드 및 도구 호출 경로 확인. C 컴파일·실행은 미검증이며, Java 런타임 확인은 응답을 얻지 못해 중단함. 언어 간 출력 일치는 배포 자료의 설명이며 이번 환경에서 실측 검증한 사실은 아님
- TEAM의 최고 카드 보존 전략을 통신 없이 검증함. 표준 상대 4종에 대해 seed 1~1000과 별도 seed 1001~2000에서 양쪽 자리로 총 16,000경기를 비교함. 결과는 TEAM 절 참조
- 프로젝트 Player에 연결한 bot·실제 TCP·원격 Run A~D·제출 비교표는 미검증

## 필수 요구사항

| 항목 | 고정 조건 |
| --- | --- |
| 프로그램·배포 | 외부 호스트의 League Server 1개, 로컬 PC 한 대의 Player 10개 독립 프로세스, Run D에서 같은 PC의 Crasher 1개 |
| 연결 | 게임 TCP Star. Player 간 연결 없음. Crasher는 Player 제어 TCP에만 연결하며 Server와 통신하지 않음 |
| Server 스레드 | Main 1 + START 직후 한 번 생성한 Table M개. 경기별·Player별 스레드 생성 금지 |
| 동기화 | 공유 상태용 Mutex 1개 + 같은 Mutex를 사용하는 `lobby_cv`, `done_cv` 2개. 로그 전용 Lock은 별도로 허용 |
| 경기 | P1~P10 모든 쌍 45경기, `mid=0..44`, 각 10판. A는 작은 번호, B는 큰 번호 |
| 카드·점수 | 각자 카드 1~10 한 번씩. 더 큰 카드가 상금 획득, 동률이면 상금 소멸. 승 3·무 1·패 0 |
| 순위 | PTS 내림차순 → GF-GA 내림차순 → GF 내림차순 → 번호 오름차순 |
| 테이블·seed | `--tables` 1~5 지원. 제출은 A=1, B/C/D=4. 리그 seed=2026 |
| 시간 | COMMIT·REVEAL·CONFIRM 단계별 공통 deadline 3,000ms. ROUND 수신 후 카드 선택 전 think 18~22ms 균등 무작위 |
| 표준 전략 | P1/P2 RANDOM, P3/P4 MATCH, P5/P6 PLUS1, P7/P8 BIGSMALL, P9/P10 동일한 자체 TEAM |
| 공개·검증 | SHA-256 Commit–Reveal. Player가 상대 hash·판정·점수를 검산하고 자기 점수로 CONFIRM |
| 장애 | TCP 연결·프로세스를 유지하는 가상 crash·quit. 물리적 종료·재접속으로 대체하지 않음 |
| 출력 | `run_X/RunX_*`, A/B/C 14개·D 15개. 결과 데이터는 ASCII·LF, 로그는 UTF-8·LF |
| 정합성 | A~D 모두 verify PASS, A/B results·standings hash 각각 동일, D chaos PASS |

정상 A/B에서 모든 Server RESULT가 `confirm=OK/OK`이고 Player의 VERIFY FAIL이 0건이어야 함. M=5 실행은 제출 요구가 아니지만 입력 범위는 지원함.

## 설계 선택과 미확정 사항

다음은 명세가 강제한 언어·경로가 아니라 이번 개발의 기본안임.

- Python 3.12 이상·표준 라이브러리 사용. 제공 Python kit와 직접 연결 가능하고 TCP 대기가 주인 Server에 적합하므로 선택함
- 각 프로그램은 자기 패키지 내부만 import함. 담당 간 런타임 의존을 줄이기 위해 공통 실행 패키지를 만들지 않고 TCP·CLI·파일·로그 계약을 공유함. 난수 공식은 Server·Player에서 각각 검사함
- Server는 선택 Monitor 없이 Main+Table M만 사용함. Player는 게임 Main, Run D에서만 제어 수신 스레드 1개 추가함
- Crasher는 제어 연결을 `selectors`로 읽는 수신 스레드 1개와 Main 사건 스케줄러를 기본안으로 사용함. Main은 CV의 기한 대기로 사건과 여러 restart 시점을 함께 관리하며 busy-wait하지 않음
- 로그는 실제 KST 시각, 구간 측정은 `time.perf_counter()` 사용. 필수 message 앞부분을 그대로 유지하고 추가 정보는 뒤에 붙임
- 기본 게임 포트 9500, 로컬 제어 포트 9700을 예시로 사용함. 호스트·포트·seed·테이블·timeout·Run·출력·전략·고장은 CLI/설정으로 받음
- 원본 PDF·kit·키·실행 결과·영상·제출물은 Git 밖에 보관함. kit를 수정하지 않고 bot 테스트용 임시 사본·어댑터에서 자기 구현을 연결함

TEAM 기본안은 최고 카드 보존 전략임. 통신 없는 프로토타입으로 규칙과 상성을 확인함.

**미확정:** 아래 담당 배분은 HW4 역할을 참고한 제안임. 학번, 원격 서비스·인스턴스·OS·주소·접속 계정·실제 포트 가용성은 아직 확정·확인하지 않았음. 원격 환경값이 없어도 로컬 개발은 진행 가능함. 유료 자원 생성·변경은 이번 작업 범위에 포함하지 않음.

## 담당별 작업 계획

| 담당 제안 | 소유 경로·브랜치 | 작업·독립 완료 기준 |
| --- | --- | --- |
| 안선효 | `src/server/`, `tests/server/`, `tests/integration/` / `hw5/server` | Main·Table Pool·Lobby·판정·deadline·stale·QUIT·부전패·파일·지표. 대역 Player로 정상/위반/지연 검증 후 실제 통합·원격 배포·최종 취합 |
| 황대겸 | `src/player/`, `tests/player/` / `hw5/player` | 결정적 난수·표준 bot·TEAM·독립 검산·Run C 고장·Run D 제어 상태. bot 41건 ALL PASS, 상성 측정, 대역 Server/Crasher로 송신 차단·복귀·BYE 검증 |
| 황왕석 | `src/crasher/`, `tools/`, `tests/crasher/`, `tests/tools/` / `hw5/crasher-tools` | C1~C8·제어 TCP·로그, 설정 기반 Player launcher, kit 실행 어댑터·검증·비교 취합. 대역 Player로 지연 ACK·명령 대기·복수 restart·종료 검증 |

실제 구현 전에 담당 배분을 팀 내에서 확정함. 각자 상대 구현을 기다리지 않고 대역과 임시 데이터로 검사하며, 상대 소유 경로는 임의로 수정하지 않음. 통합은 실제 프로그램을 별도 프로세스로 실행해 TCP로 수행함. 기존 HW1~HW4와 다른 사람의 변경을 보존함.

예정 구조이며 빈 코드·빈 테스트 파일을 선생성하지 않음:

```text
HW5/
├─ README.md
├─ .gitignore
├─ src/
│  ├─ server/          __main__, lobby, match, transport, storage, metrics, log
│  ├─ player/          __main__, bots, team, transport, control, verify, log
│  └─ crasher/         __main__, control, scheduler, log
├─ tools/             launch_players, check_bots, verify_runs
└─ tests/             server, player, crasher, tools, integration
```

패키지 내부 파일 분리는 담당자가 결정함. 작업 디렉터리는 저장소의 `HW5/`, 실행 진입점은 `python -m src.server`, `python -m src.player`, `python -m src.crasher`, `python -m tools.launch_players`로 정함. `src`는 초기화 부작용 없는 namespace package로 사용함.

## 공통 계산·Bot 계약

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

고정 seed는 상금 순서·RANDOM 카드·동일한 TEAM 알고리즘의 결과를 고정함. 상금·bot 선택에는 현재 시각이나 언어 기본 난수를 섞지 않으며, 호출 순서·호출 횟수·손패 정렬도 정의와 같아야 함.

샘플 hash는 P9/P10이 RANDOM일 때의 정답임. 정식 설정은 자체 TEAM을 사용하므로 TEAM을 고정한 뒤 Run A/B의 results·standings가 각각 같아야 하며 샘플 hash와 같을 필요는 없음. C의 QUIT 전 경기 배치와 D의 실제 장애 대상·적용 시점은 실행 순서에 영향을 받아 리그 seed가 같아도 결과가 달라질 수 있음. Crasher seed는 장애 계획을 재현하며 OS 스케줄링·상태 보고 도착 순서까지 고정하지 않음. nonce·시각·테이블 배정이 포함된 match_log와 운영 로그는 A/B에서도 동일 hash를 요구하지 않음.

Player bot 공개 계약은 kit와 같은 `seed_of(text)`, `LCG(seed).next()`, `prize_order(S, mid)`, `Bot(strategy, S, mid, k)` 및 `choose(prize,r)`, `play(prize,r,my_card,opp_card)`로 정함. `choose()`는 손패를 바꾸지 않고 REVEALS 뒤 `play()`에서 제거함. 손패는 항상 오름차순임.

| 전략 | 선택 규칙 |
| --- | --- |
| MATCH | 이번 상금과 같은 카드 |
| PLUS1 | 상금보다 큰 남은 카드 중 최소, 없으면 손패 최소 |
| BIGSMALL | 상금≥6이면 손패 최대, 그 외 최소 |
| TEAM | 남은 최고 상금에 손패의 최고 카드를 사용하고, 그 전에는 다른 카드로 승부 |

TEAM 함수는 `team_choose(p,r,hand,history,prizes_left,rng)`로 제한함. history는 `(r,p,내 카드,공개된 상대 카드)`이며 상대 번호·전략·자리·mid·k·S를 전달하지 않음. S/mid/k는 난수 생성기 이름표 구성에만 사용함. 다른 경기·순위·현재 시각·파일·네트워크 정보도 선택 근거로 사용하지 않음.

### TEAM 최고 카드 보존

미처리 상금 중 최댓값이 나올 때까지 손패의 최고 카드를 남겨 둠. 미처리 상금은 1~10에서 처리한 판의 상금만 제외한 집합이며 현재 상금도 포함함.

1. 현재 상금이 미처리 상금의 최댓값이면 손패의 최고 카드를 냄.
2. 그 외에는 최고 카드를 제외하고, 상금보다 2 이상 큰 카드 중 최솟값을 냄.
3. 조건에 맞는 카드가 없으면 손패의 최솟값을 냄.

예를 들어 손패가 2·6·9이고 미처리 상금이 4·7·10이면, 상금 4에는 6을 내고 9는 남겨 둠. 상금 10이 나오면 그때의 최고 카드를 냄. 카드와 상금은 REVEALS를 확인한 뒤에만 제거함. 선택에 필요한 값은 현재 상금, 미처리 상금의 최댓값, 내 손패임. 난수 호출은 0회임.

kit 방식대로 `mid=seed%45`를 사용했으며, 범위별로 상대마다 A/B 자리에서 각 1,000경기씩 치름.

| 상대 | seed 1~1000 승/무/패 | 승률 | seed 1001~2000 승/무/패 | 승률 |
| --- | --- | ---: | --- | ---: |
| RANDOM | 1458 / 75 / 467 | 72.9% | 1459 / 51 / 490 | 72.95% |
| MATCH | 1636 / 36 / 328 | 81.8% | 1656 / 28 / 316 | 82.8% |
| PLUS1 | 1662 / 10 / 328 | 83.1% | 1684 / 10 / 306 | 84.2% |
| BIGSMALL | 1722 / 42 / 236 | 86.1% | 1702 / 34 / 264 | 85.1% |

남은 상금의 순위로 카드 순위를 정하는 방식과 최근 3판의 공개 카드로 다음 카드를 추정하는 방식도 비교함. 최고 카드 보존은 선택 규칙 세 줄로 설명할 수 있고, 두 seed 범위에서 표준 상대별 승률이 72.9~86.1%로 고르게 나와 기본안으로 채택함.

공식 표준 bot 41건 ALL PASS. seed 2026의 정식 전략 구성에서 통신 없이 45경기를 정순·역순으로 실행해 경기별 결과가 일치함. 자체 기준 hash는 results `5255a2bf`, standings `6a4147b7`임. G44의 TEAM 대 TEAM은 `0:0 DRAW`였음. 프로젝트 Player 연결과 실제 TCP 실행은 미검증.

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

두 선수는 단계마다 같은 절대 deadline을 사용함. A 대기 때문에 B의 마감을 새로 3초 늘리지 않음. A 대기 후 시간이 끝나도 B 소켓에 이미 수신된 완성 줄을 확인함. 이 경계는 B가 먼저 보낸 뒤 A가 침묵하는 대역 검사로 확인함. CONFIRM 지연·불일치는 `NO`·`DISPUTE` 기록만 남기며 점수는 변경하지 않음. DEAD 또는 CONFIRM 대신 QUIT은 `-`임.

Player는 상대 COMMIT hash와 공개 카드·nonce를 비교하고 판 winner·누적 점수를 직접 계산함. MATCH_END 점수를 복사하지 않음. 몰수는 FORFEIT의 who로 자체 기록 점수를 결정함.

## Lobby·장애·종료 계약

### Server

1. Main이 HELLO의 번호 1~10·중복을 검사하고 WELCOME 전송. 10명이 모이면 START, Table M개 생성
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

- C1: Player 10개의 CTRL 접속 대기. seed 생략 시 무작위이며 사용한 seed와 계획을 첫 PLAN에 기록
- C2: 장애 4~7건·quit 1~2건·나머지 crash, 종류 순서 무작위
- C3: 발생 기준은 종료 경기 수 근사값 2~30에서 무작위 계획. PLAYING→IDLE 횟수÷2로 추적하고 리그 종료 시 대기 중단. 계획한 사건이 리그 전에 모두 발생했는지도 확인
- C4: 현재 PLAYING이며 본인·상대가 장애 중이 아닌 선수 중 무작위 선택. crash·영구 quit·아직 적용되지 않은 명령 대기까지 장애 집합에 포함
- C5: 대상 선택 후 0~0.3초 대기, 송신 직전 Lock 안에서 같은 경기·자격 재검사. 바뀌면 다시 선택
- C6: `STATE CRASHED` ACK 수신부터 4~5초 뒤 RESTART. 여러 crash의 복귀를 독립 예약하며 IDLE 확인 후 장애 집합에서 제거
- C7: quit은 영구 장애로 유지하고 재선택하지 않음
- C8: 모든 Player의 END 확인 후 요약·TERMINATE. 종료 판정용 END/QUIT과 실제 프로세스 종료용 END를 구분함

Player는 MATCH에서 PLAYING 보고 후 대기 명령을 적용함. IDLE 중 받은 CRASH/QUIT은 INFO 기록 후 다음 MATCH에서 실행하며, 실제 적용에만 WARN을 한 번 기록함. 게임 송신 직전 mode 검사와 송신을 같은 Player 상태 Lock 안에서 수행하여 think 중 crash 뒤 COMMIT이 새지 않게 함. 이 Lock은 Server의 공유 상태 Lock과 다른 로컬 Lock임.

CRASHED·QUIT 상태에서도 게임 소켓을 읽어 BYE 외 줄은 버림. RESTART 시 이미 쌓인 사용자·소켓 수신 데이터를 비우고 REJOIN·STATE IDLE을 보낸 뒤 **새 MATCH부터** Bot을 생성함. crash 중 버린 MATCH의 경기는 복귀 시점이 마감 전이어도 이어서 참여하지 않음. Server는 REJOIN으로 마감·Bot·점수를 초기화하지 않음.

QUIT은 게임 소켓으로 `QUIT mid`를 보내고 BYE까지 유지함. BYE 시 QUIT 선수도 `STATE END`와 TERMINATE를 남김. 마지막 경기 crash·리그 종료 중 restart·제어 EOF를 검사해 제어 스레드/타이머가 종료를 막지 않게 함. 일정상 두 장애 선수가 만나는 경기는 FORFEIT_BOTH 규칙으로 처리함.

## 파일·필수 로그

결과 파일 3개는 ASCII·LF·마지막 LF, hash8은 **실제 파일 전체 바이트 SHA-256의 앞 8자리 소문자**임. Windows의 CRLF 자동 변환을 피하도록 `newline="\n"` 또는 바이너리 저장 사용함.

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

위 숫자는 형식 예이며 실측 결과가 아님. match_log는 경기 mid순, R은 판순, F는 몰수 시에만 기록함. 시각 t는 START 이후 같은 Server 단조 시계의 초임. 동시 경기 경계를 소수 3자리로 반올림해 overlap이 생기지 않도록 충분한 정밀도로 저장하고 실제 구간으로 검사함. nonce·hash는 축약하지 않음.

공통 로그 외형은 `[HH:MM:SS.mmm] NODE | EVENT | STATUS | message`임. NODE는 SERVER/Pk/CRASHER, STATUS는 SUCCESS/FAIL/INFO/WARN. 필수 앞부분을 JSON으로 대체하지 않음.

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

SERVER의 INIT·CONNECT·START·TABLE·TERMINATE, Player의 CONNECT·MATCH·RESULT·FORFEIT·FAULT·VERIFY 등 실제 사용하는 모든 EVENT도 기록·정의함. Run C quit은 Player `FAULT WARN`, Run D quit은 `QUIT WARN`임. 장애 전 마지막 ROUND 번호가 없으면 r=0, 마지막 송신 종류가 없으면 last=-임. 종료한 Player의 TERMINATE는 마지막 줄로 유지함.

## 실행·검증 계획

### 환경과 원본 경로

`HW5_KIT_DIR`은 각 PC의 배포 원본 루트로 지정함. 필수 자료가 없으면 해당 검사는 실패·미검증으로 보고하고 skip을 PASS로 계산하지 않음. 아래는 현재 로컬 배치에서 저장소 `HW5/`를 작업 디렉터리로 쓰는 PowerShell 예임.

```powershell
$env:PYTHONUTF8 = "1"
$env:HW5_KIT_DIR = (Resolve-Path "../../HW5_student_kit").Path
$env:HW5_RESULTS_DIR = [IO.Path]::GetFullPath("../../실행결과")
python --version
```

Linux/macOS에서는 같은 환경변수를 `export`로 지정하고 `python3`를 사용함. 개인 절대 경로·접속 키·주소를 소스에 넣지 않음. `python` 명령은 실제 설치된 Python 3.12 이상으로 연결해야 함. 이번 자료 검사에는 번들 Python을 사용했으며 현재 PC의 기본 `python` 명령은 사용 가능 여부를 별도 확인해야 함.

### 구현 후 CLI 계약

다음 명령은 **현재 실행 가능한 코드가 아니라 구현할 진입점과 인자**임. `SERVER_IP`, `RESULTS`, `KIT`, `LOCAL_LOGS`는 실제 경로·환경값으로 치환함.

```text
python -m src.server --host 0.0.0.0 --port 9500 --seed 2026 --tables 1 --timeout 3000 --run A --out "RESULTS/run_A"
python -m tools.launch_players --host SERVER_IP --port 9500 --config "KIT/4_config/players_std.txt" --think 18,22 --run A --out "LOCAL_LOGS/run_A"

python -m src.player --host SERVER_IP --port 9500 --id 3 --strategy MATCH --think 18,22 --run B --out "LOCAL_LOGS/run_B"
python -m src.crasher --host 127.0.0.1 --port 9700 --run D --out "LOCAL_LOGS/run_D" --seed 11
python -m tools.launch_players --host SERVER_IP --port 9500 --config "KIT/4_config/players_std.txt" --think 18,22 --run D --out "LOCAL_LOGS/run_D" --crasher 127.0.0.1:9700
```

Server는 B/C/D에서 `--tables 4`·해당 Run·출력 경로로 변경함. C launcher는 `players_fault.txt`의 고장 열을 각 Player의 `--fault 종류@mid,r`에 전달함. D는 Server·Crasher·Player 순으로 기동함. launcher는 설정의 P1~P10 중복·누락·전략·고장 형식을 검사하고 `sys.executable`로 독립 프로세스 10개를 실행함. 자식 실패·사용자 중단 시 자식들을 정리하고 실패를 반환함. 정상 실행 도중 Player를 종료하는 동작을 장애 주입으로 사용하지 않음.

Run별로 새 출력 폴더를 사용하고 이전 결과를 조용히 덮어쓰지 않음. Server의 4개 파일과 로컬 Player 10개 로그, D의 Crasher 로그를 같은 Run끼리 모음. 경로는 공백·한글을 지원함.

### 검사 순서와 완료 기준

1. 임시 kit 사본의 mybots 어댑터에 `src.player.bots` 연결 → 공식 41건 ALL PASS → 통신 없는 샘플 45경기 hash 일치. seed 7의 league hash `f11a9a2e`·`ceb40a34`도 확인
2. 대역 Server/Player로 부분 수신·여러 줄 수신·중복 id·단계 순서·확정 전 REVEAL 금지·자체 CONFIRM 검산 확인
3. 로컬 실제 TCP를 sample 설정 M=1, M=2, M=4로 실행 → results `cfde2bce`·standings `c8a0c732`, verify overlap 0 확인. M=5는 지원 범위 검사
4. TEAM 고정 후 정식 A/B의 두 결과 파일을 바이트·hash로 비교, 정상 CONFIRM 전부 OK/OK, VERIFY FAIL 0건 확인
5. Run C 고장 4건의 선수·판·사유·점수, 늦은 COMMIT 폐기, QUIT 이후 경기·마지막 BYE 확인. 두 위반·CONFIRM QUIT·DEAD+침묵·잘못된 카드/hash 검사 우선순위도 대역으로 확인
6. Crasher 대역으로 C1~C8·ACK 기준 4~5초·명령 대기·상대 장애 제외·여러 crash 복귀·모든 END 종료 확인. 실제 D를 여러 seed로 반복해 매번 chaos PASS 확인
7. 외부 Server+로컬 Player 구성으로 정식 A/B/C/D 새 실행 → 로그 취합 → 공식 검사·실측·영상·제출 문서 작성

예정 자체 검사 명령은 `python -m unittest discover -s tests/담당경로 -p "test_*.py" -v`임. 현재 테스트 파일은 없음. 테스트 0건·필수 skip·대역만의 PASS를 실제 통합 PASS로 보고하지 않음. 도구의 정상 fixture뿐 아니라 파일 누락·CRLF·hash 손상·잘못된 로그·비정상 자식 종료가 실패로 잡히는지도 검사함.

아래는 **제공 kit의 현재 사용 가능한 명령**임. kit의 `2_tools/python/`에서 실행하며 경로는 실제 절대 경로로 치환함. 마지막 명령은 작업 디렉터리에 파일을 생성하므로 원본 보존을 위해 세 도구를 임시 작업 폴더에 함께 복사하고 그 폴더에서 실행함.

```text
python verify_league.py "RESULTS/run_A"
python verify_league.py "RESULTS/run_B"
python verify_league.py "RESULTS/run_C"
python verify_league.py "RESULTS/run_D"
python check_chaos.py "RESULTS/run_A" "RESULTS/run_D"
python make_compare.py 2 "RESULTS/run_A" "RESULTS/run_B" "RESULTS/run_C" "RESULTS/run_D"
```

`make_compare`는 같은 디렉터리의 verify·chaos를 호출하며 `TEAM 2`를 사용함. kit에는 Run C 샘플이 없어 제공 자료만으로 정식 4-Run 비교표를 만들 수 없음. A/B/D 샘플을 C로 바꾸거나 예제 PASS를 채워 제출하지 않음.

verify는 Run D에서도 기본 14개 파일을 검사하므로 D의 15번째 Crasher 파일은 chaos로 별도 확인함. 검사 종료 코드만 보지 않고 `-> PASS`, `CHAOS D -> PASS`, 오류 출력·필수 파일을 함께 판정함. verify의 텍스트 읽기는 CRLF를 정규화할 수 있으므로 별도 바이트 검사로 LF·ASCII·마지막 LF·실제 파일 hash를 확인함. 제공 도구의 PASS는 원격 배포 사실·필수 Thread 구조·전체 로그·Run C 고장 처리까지 증명하지 않으므로 코드·로그·영상 검사도 수행함.

## 실측·분석과 최종 제출

Server 최종 로그와 제출 Readme에 다음을 실제 측정값으로 기록함.

- START 전송~마지막 경기 CONFIRM 처리 종료까지 총 실행시간, MATCH 전송~CONFIRM 처리 종료의 경기 평균·최소·최대
- 테이블별 경기 수·가동률(경기시간 합/총시간)·lobby_cv 대기시간, 평균 동시 경기 수(전체 경기시간 합/총시간)
- ROUND 송신~두 COMMIT 도착의 응답 지연 평균·최대. timeout 판은 누락·성공 표본과 구분해 집계 방법 명시
- 사유별 몰수·부전패·STALE·CONFIRM OK/NO/DISPUTE/- 수, 전략별 W/D/L·평균 득점
- A/B 시간 비·하한·tail·유휴 테이블, 로컬/원격 지연과 think를 뺀 나머지 지연, TEAM 상성·강약 분석
- D의 사건 목록·crash/quit 수·복귀 간격·영향 경기. `(D 총시간-B 총시간)/crash 수`는 quit·매칭 변화가 섞인 비교 평균으로 표시하고 순수 crash 인과 효과로 단정하지 않음

제출 목표 구성은 Q&A Q5·Q8의 예를 따름. 원본 설정 3종은 kit를 그대로 참조하고 ZIP에 별도로 넣지 않음. 따라서 실행 방법에 kit 준비·경로 지정이 반드시 포함되어야 함.

```text
G2HW5.zip
├─ src/                 전체 프로그램과 실행 보조, 실제 실행 방법
├─ run_A/               RunA_results, standings, match_log, League, P1~P10 (14개)
├─ run_B/               같은 구성, RunB_ (14개)
├─ run_C/               같은 구성, RunC_ (14개)
├─ run_D/               같은 구성, RunD_ + RunD_Crasher.txt (15개)
├─ compare_result.txt
├─ AllDefinedLogs.txt
├─ download.txt
└─ Readme.txt
```

저장소의 `src/`, `tools/`를 제출 `src/` 아래에 함께 두어 패키지 경로를 보존하고 실행 작업 디렉터리를 명시함. 개발 README는 제출 Readme.txt와 구분하며, 최종 문서는 실제 코드·명령·결과 기준으로 작성함. 계획·대화 흔적·내부 절대 경로·미검증 성공 문구를 제출 문서에 넣지 않음.

제출 Readme.txt에는 이름·학번·역할, 서비스·인스턴스·OS·시간대, 설치·실행·kit 준비, 구조·메시지·Thread/Lock/CV, timeout·stale·부전패, TEAM 규칙·의도·상성표, 지표·정합성·Run D 분석, 한계·느낀 점을 포함함. AllDefinedLogs.txt는 실제 사용하는 모든 EVENT·STATUS·필드·단위를 정의함.

약 5분 `G2HW5.mp4`에는 원격 시작·10명 접속·4테이블 동시 진행·Run C 몰수/부전패·Run D crash/복귀/quit과 Crasher/Server 로그·verify/chaos/compare 확인을 포함함. download.txt의 링크를 비로그인 다운로드·재생으로 확인함. ZIP을 요청받아 생성할 경우 새 폴더에 풀어 실제 Readme 명령·파일 구성·압축 무결성을 확인함.

Git에는 코드·개발 README·필요 설정만 관리함. 실행 결과·원본·검증 임시물·제출 파일·키는 올리지 않음. 작업 브랜치에서 자기 범위를 구현하고 독립 검사·실제 통합·원격 실행·제출 확인을 구분해 인계함.
