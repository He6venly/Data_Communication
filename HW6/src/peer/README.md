# HW6 Peer 인계

`HW6/`에서 실행함. Peer는 공통 Conn과 contracts를 사용하고, Tracker 설정 모듈의 env 검증을 재사용함. 실행 시 `FileStore`, `UploadServer`, `StatusScreen`의 실제 구현이 필요함.

```powershell
$env:HW6_KIT_DIR = '배포 키트의 hw6_student_kit/Python 경로'
python -B -m unittest discover -s tests/peer -v
python -m src.peer --env "$env:HW6_KIT_DIR/envs/DEV.json" --id P4 TRACKER_IP 6000
```

JSONL은 `logs/피어ID.jsonl`에 UTF-8/LF로 추가함. 공통 필드 `t`는 Peer 프로그램 시작 후 단조 시계 기준 초, `peer`는 피어 id, `ev`는 이벤트임. EXIT의 전송량은 MiB이며 화면의 전송률은 KiB/s임.

| Peer 이벤트 | 필드와 기록 시점 |
| --- | --- |
| START | `env,policy,up_kbps,down_kbps,run,seed,description,rng_seed,tracker`. 원본 검증 전 첫 이벤트, 속도 설정은 1024 B/s 단위 |
| GET | `file,chunks`. 다운로드 파일 준비 뒤 한 번 |
| FAIL | `file,idx,src,err`. 실제 GET 실패 시. 자체 취소는 제외 |
| BAN | `target,sec`. 연속 실패 기준 충족 시 |
| COMPLETE | `file,sec,sources`. 수신 파일을 REGISTER한 뒤. sec는 프로그램 시작부터의 초, sources는 피어별 청크 수 |
| CRASH / REJOIN / DESTROY | CRASH는 `sec` 및 연결 정리 뒤. REJOIN은 재등록·캐시 갱신 뒤. DESTROY는 종료 정리 전 |
| STALLED / UNSTALLED | `file`, STALLED에는 `lost`(청크 수) 추가. 파일 상태 전환 시 |
| DONE / UNDONE | DONE은 `kind,detail`, UNDONE은 추가 필드 없음. Tracker OK 뒤 |
| ALLDONE / ABORT | ALLDONE은 `done,alive`(피어 수), ABORT는 `reason,silent_sec` |
| ERROR | `kind,operation,file,message`. 설정·로컬 I/O·계약·정리 실패 |
| EXIT | `code,up_mb,down_mb`. 정리 뒤 마지막 줄 |

FileStore의 RECV·HASH·CORRUPT는 같은 EventLog를 사용함. 대역 테스트에서 쓰는 메모리 저장소는 실제 디스크 저장·해시·업로드 통합을 대신하지 않음.
