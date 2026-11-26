"""Tracker 명령·생존·지시·관찰 상태를 한 Lock으로 관리함."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import math
import threading
import time
from typing import Callable

from src.common.contracts import Env, EventSink, LifecycleError
from .config import validate_env
from .observer import PeerReport, observe_locked
from .report import build_locked
from .scheduler import Command, check_completion, exit_code_locked, tick_locked


@dataclass(frozen=True, slots=True)
class Reply:
    """송신할 줄·연결의 피어 id·송신 확인용 지시 번호를 전달함."""

    lines: tuple[str, ...]
    peer_id: str | None
    delivery_token: int | None = None


class TrackerState:
    """네트워크와 분리한 Tracker의 명령 처리·상태 전이를 담당함."""

    def __init__(self, *, env: Env, emit: EventSink,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """원본 설정을 복사하고 상태·이벤트 큐·단조 시계를 준비함."""
        self.env = validate_env(deepcopy(dict(env)))
        self.peers = {p["id"]: p for p in self.env["peers"]}
        self.files = {f["name"]: f for f in self.env["files"]}
        chunk = self.env["chunk_size"]
        self.nchunks = {n: (f["size"] + chunk - 1) // chunk for n, f in self.files.items()}
        self.lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._emit = emit
        self._clock = clock
        self._events: deque[tuple[str, dict]] = deque()
        self.joined: set[str] = set()
        self.last_seen: dict[str, float | None] = {p: None for p in self.peers}
        self.have = {p: 0 for p in self.peers}
        self.holders: dict[str, set[str]] = {}
        self.byes: set[str] = set()
        self.dead: set[str] = set()
        self.done: dict[str, tuple[str, str]] = {}
        self.done_times: dict[str, float] = {}
        self.started_at: float | None = None
        self.progress_changed_at: float = 0
        self.alldone_at: float | None = None
        self.abort_reason: str | None = None
        self.aborted_at: float | None = None
        self.pending: dict[str, deque[Command]] = {p: deque() for p in self.peers}
        self._inflight: dict[int, Command] = {}
        self._serial = 0
        self.scheduled: set[int] = set()
        self.crashes_sent: list[dict] = []
        self.destroy_at: float | None = None
        self.destroy_progress: float | None = None
        self.destroy_delivered: str | None = None
        self.dead_times: dict[str, float] = {}
        self.reports: dict[tuple[str, str], PeerReport] = {}
        self.rep_times: dict[str, float | None] = {n: None for n in self.files}
        self.rep_stats: dict[str, tuple[int, int] | None] = {n: None for n in self.files}
        self.rep_progress: float | None = None
        self.frozen_report: dict | None = None

    @property
    def terminal(self) -> bool:
        """ALLDONE 또는 ABORT가 확정된 상태인지 확인함."""
        return self.alldone_at is not None or self.abort_reason is not None

    def elapsed(self, now: float) -> float:
        """경계 조건 판정에는 반올림 전 START 경과 시간을 사용함."""
        return 0.0 if self.started_at is None else max(0.0, now - self.started_at)

    def progress(self) -> float:
        """원본을 제외한 수신 청크 합으로 전체 진행률을 계산함."""
        return sum(self.have.values()) / self.env["progress_total_chunks"]

    def is_live(self, pid: str, now: float) -> bool:
        """참가했고 BYE 없이 dead_sec 이내에 응답한 피어를 구분함."""
        last = self.last_seen[pid]
        return last is not None and pid not in self.byes and now - last <= self.env["timing"]["dead_sec"]

    def queue_event(self, event: str, **fields) -> None:
        """상태 Lock 안에서는 이벤트만 적재하고 I/O는 미룸."""
        if "t_start" in fields:
            fields["t_start"] = round(fields["t_start"], 2)
        self._events.append((event, fields))

    def _flush(self) -> None:
        """상태 Lock을 놓고 생성 순서대로 이벤트를 출력함."""
        with self._output_lock:
            while True:
                with self.lock:
                    if not self._events:
                        return
                    event, fields = self._events.popleft()
                self._emit(event, **fields)

    def _now(self) -> float:
        """주입한 시계가 유한한 경과 시각을 반환하는지 확인함."""
        now = self._clock()
        if not math.isfinite(now):
            raise ValueError("clock must return finite monotonic time")
        return now

    def _touch(self, pid: str, now: float) -> None:
        """메시지 수신 시각을 갱신하고 DEAD 피어의 복귀를 기록함."""
        if pid in self.dead:
            self.dead.remove(pid)
            self.queue_event("BACK", id=pid)
        self.last_seen[pid] = now

    def new_command(self, target: str, kind: str, seconds: float | None = None) -> Command:
        """지시별 고유 번호를 발급해 중복 송신 확인을 구분함."""
        self._serial += 1
        return Command(self._serial, target, kind, seconds)

    def drop_unclaimed(self, target: str | None = None) -> None:
        """아직 송신 중이 아닌 지시를 버리고 사유 추적용 이벤트를 남김."""
        for pid, commands in self.pending.items():
            if target is not None and target != pid:
                continue
            keep = deque()
            for command in commands:
                if command.serial in self._inflight:
                    keep.append(command)
                else:
                    self.queue_event("CMD_DROPPED", id=pid, cmd=command.wire)
            self.pending[pid] = keep

    def set_abort(self, reason: str, now: float) -> None:
        """첫 ABORT 사유와 시작 시각을 고정하고 미송신 지시를 정리함."""
        if not self.terminal:
            self.abort_reason, self.aborted_at = reason, now
            self.queue_event("ABORT", reason=reason, progress=self.progress())
            self.drop_unclaimed()

    def handle(self, line: str, *, peer_id: str | None = None, src_ip: str = "") -> Reply:
        """한 명령을 처리하고 Lock 밖에서 보낼 응답 복사본을 반환함."""
        if not isinstance(line, str):
            raise TypeError("line must be str")
        with self.lock:
            if self.frozen_report is not None:
                raise LifecycleError("tracker report already frozen", operation="handle")
            now = self._now()
            context = peer_id if peer_id in self.joined else None
            if context is not None:
                self._touch(context, now)
            tokens = line.split()
            if not tokens or any(c in line for c in "\r\n\x00"):
                result = Reply(("ERR BADCMD",), context)
            else:
                try:
                    result = self._dispatch(tokens, context, src_ip, now)
                except (ValueError, IndexError):
                    result = Reply(("ERR BADCMD",), context)
        self._flush()
        return result

    def _dispatch(self, words: list[str], context: str | None, src_ip: str, now: float) -> Reply:
        """명령 종류·인자 수·참가 id를 확인하고 해당 상태 전이로 분기함."""
        op, size = words[0], len(words)
        arity = {"HELLO": 2, "REGISTER": 6, "HAVE": 4, "LIST": 1, "PEERS": 2,
                 "HEARTBEAT": 3, "REPORT": 6, "UNDONE": 2, "STATE": 1, "BYE": 2}
        if op not in arity and op != "DONE":
            raise ValueError("unknown command")
        if (op == "DONE" and size < 3) or (op != "DONE" and size != arity[op]):
            raise ValueError("wrong argument count")
        if op == "HELLO":
            pid = words[1]
            if pid not in self.peers:
                raise ValueError("unknown peer")
            if pid in self.joined:
                self.queue_event("REJOIN", id=pid)
            else:
                self.joined.add(pid)
                self.queue_event("JOIN", id=pid, n=len(self.joined), src_ip=src_ip)
            self.byes.discard(pid)
            self._touch(pid, now)
            if self.started_at is None and len(self.joined) == len(self.peers):
                self.started_at = self.progress_changed_at = now
                self.queue_event("START", peers=len(self.peers))
            return Reply(("OK",), pid)
        if op in ("LIST", "PEERS", "STATE"):
            return Reply(self._query(words, now), context)
        pid = words[1]
        if pid not in self.joined:
            raise ValueError("HELLO required")
        # 접속을 매번 여는 구현도 명령 안의 id로 생존 시각을 갱신함.
        self._touch(pid, now)
        if op in ("REGISTER", "HAVE"):
            return Reply((self._register(words),), pid)
        if op == "HEARTBEAT":
            have = self._uint(words[2])
            maximum = sum(n for name, n in self.nchunks.items() if self.files[name]["origin"] != pid)
            if have > maximum:
                raise ValueError("invalid have")
            if self.have[pid] != have:
                self.have[pid] = have
                self.progress_changed_at = now
            if not self.terminal and self.pending[pid] and not any(c.target == pid for c in self._inflight.values()):
                command = self.pending[pid][0]
                self._inflight[command.serial] = command
                return Reply((command.wire,), pid, command.serial)
            return Reply(("OK",), pid)
        if op == "REPORT":
            self._report(words, now)
        elif op == "DONE":
            kind, detail = self._done(words)
            if not self.terminal and self.done.get(pid) != (kind, detail):
                self.done[pid] = (kind, detail)
                self.done_times[pid] = self.elapsed(now)
                self.queue_event("DONE", id=pid, kind=kind, detail=detail)
                check_completion(self, now)
        elif op == "UNDONE":
            if not self.terminal and pid in self.done:
                self.done.pop(pid)
                self.done_times.pop(pid, None)
                self.queue_event("UNDONE", id=pid)
        elif op == "BYE":
            if pid not in self.byes:
                self.byes.add(pid)
                self.queue_event("BYE", id=pid)
        return Reply(("OK",), pid)

    @staticmethod
    def _uint(text: str) -> int:
        """명령의 개수·포트·인덱스 항목을 음수가 아닌 정수로 읽음."""
        if not text.isascii() or not text.isdigit():
            raise ValueError("nonnegative integer required")
        return int(text)

    def _query(self, words: list[str], now: float) -> tuple[str, ...]:
        """등록 파일·live 보유자·종료 상태를 다중 행 응답으로 구성함."""
        op = words[0]
        if op == "LIST":
            rows = []
            for name, file in self.files.items():
                if name in self.holders:
                    rows.append(f"{name} {file['size']} {self.env['chunk_size']} {self.nchunks[name]} {len(self.holders[name])}")
            return (f"FILES {len(rows)}", *rows)
        if op == "PEERS":
            name = words[1]
            if name not in self.holders:
                return ("ERR NOFILE",)
            rows = [f"{pid} {peer['host']} {peer['port']}" for pid, peer in self.peers.items()
                    if pid in self.holders[name] and self.is_live(pid, now)]
            return (f"PEERS {len(rows)}", *rows)
        check_completion(self, now)
        live = [p for p in self.peers if self.is_live(p, now)]
        done = sum(p in self.done for p in live)
        head = f"STATE {done} {len(live)}"
        if self.abort_reason is not None:
            return (f"{head} ABORT {self.abort_reason}",)
        return (head + (" ALLDONE" if self.alldone_at is not None else " WAIT"),)

    def _register(self, words: list[str]) -> str:
        """완성·부분 보유 등록을 env와 대조하고 보유자 집합에 반영함."""
        op, pid, port_text, name = words[:4]
        port = self._uint(port_text)
        if port != self.peers[pid]["port"]:
            return "ERR MISMATCH"
        if op == "HAVE":
            if name not in self.holders:
                return "ERR NOFILE"
        else:
            size, chunk = self._uint(words[4]), self._uint(words[5])
            if name not in self.files or (size, chunk) != (self.files[name]["size"], self.env["chunk_size"]):
                return "ERR MISMATCH"
            self.holders.setdefault(name, set())
            self.queue_event("REGISTER", id=pid, file=name)
        self.holders[name].add(pid)
        return "OK"

    def _report(self, words: list[str], now: float) -> None:
        """REPORT 길이·비트·송출 통계를 확인한 뒤 관찰 자료를 교체함."""
        _, pid, name, sent_text, distinct_text, bitmap = words
        if name not in self.files:
            raise ValueError("unknown report file")
        sent, distinct = self._uint(sent_text), self._uint(distinct_text)
        if len(bitmap) != self.nchunks[name] or set(bitmap) - {"0", "1"}:
            raise ValueError("invalid bitmap")
        if distinct > min(sent, self.nchunks[name]):
            raise ValueError("invalid upload statistics")
        self.reports[pid, name] = PeerReport(bitmap, sent, distinct, now)

    def _done(self, words: list[str]) -> tuple[str, str]:
        """FULL과 PARTIAL의 파일별 유실 수·FAILED 표기를 검증함."""
        kind = words[2]
        if kind == "FULL" and len(words) == 3:
            return "FULL", ""
        if kind != "PARTIAL" or len(words) < 4:
            raise ValueError("invalid DONE")
        lost = {}
        for token in words[3:]:
            name, count = token.rsplit(":", 1)
            if name not in self.files or name in lost:
                raise ValueError("invalid DONE file")
            if count != "FAILED" and not 1 <= self._uint(count) <= self.nchunks[name]:
                raise ValueError("invalid loss count")
            lost[name] = count
        detail = " ".join(f"{name}:{lost[name]}" for name in self.files if name in lost)
        return "PARTIAL", detail

    def delivery_valid(self, token: int) -> bool:
        """송신 직전 지시가 아직 유효하고 종료가 확정되지 않았는지 확인함."""
        with self.lock:
            return token in self._inflight and not self.terminal and self.frozen_report is None

    def delivery_succeeded(self, token: int) -> bool:
        """실제 송신 성공 뒤 한 번만 지시 전달과 crash 기록을 확정함."""
        with self.lock:
            command = self._inflight.pop(token, None) if self.frozen_report is None else None
            if command is None:
                return False
            self.pending[command.target].remove(command)
            self.queue_event("CMD_DELIVERED", id=command.target, cmd=command.wire)
            if command.kind == "DISCONNECT":
                self.crashes_sent.append({"t": round(self.elapsed(self._now()), 2), "peer": command.target,
                                          "cmd": "DISCONNECT", "sec": command.seconds})
            else:
                self.destroy_delivered = command.target
                self.drop_unclaimed(command.target)
        self._flush()
        return True

    def delivery_failed(self, token: int) -> None:
        """송신 실패 지시를 재시도 가능하게 풀고 종료 뒤에는 버림."""
        with self.lock:
            self._inflight.pop(token, None)
            if self.terminal:
                self.drop_unclaimed()
        self._flush()

    def tick(self) -> None:
        """scheduler 한 주기의 상태 전이를 수행하고 이벤트를 출력함."""
        with self.lock:
            tick_locked(self, self._now())
        self._flush()

    def observe(self) -> None:
        """observer 한 주기의 복제 관찰을 수행하고 이벤트를 출력함."""
        with self.lock:
            observe_locked(self, self._now())
        self._flush()

    def exit_code(self) -> int | None:
        """상태 변경 없이 main이 종료 가능한지 확인함."""
        with self.lock:
            return exit_code_locked(self, self._now())

    def abort(self, reason: str) -> None:
        """시그널·실행 오류를 첫 중단 사유로 기록하고 대기 지시를 정리함."""
        if not isinstance(reason, str) or not reason:
            raise ValueError("abort reason required")
        with self.lock:
            if self.frozen_report is None:
                self.set_abort(reason, self._now())
        self._flush()

    def snapshot(self) -> dict:
        """검사·상태 표시용 자료를 외부 변경이 불가능한 복사본으로 반환함."""
        with self.lock:
            return deepcopy({
                "started_at": self.started_at, "joined": tuple(p for p in self.peers if p in self.joined),
                "last_seen": self.last_seen, "have": self.have, "done": self.done,
                "byes": tuple(p for p in self.peers if p in self.byes),
                "dead": tuple(p for p in self.peers if p in self.dead),
                "pending": {p: tuple(c.wire for c in q) for p, q in self.pending.items()},
                "abort": self.abort_reason, "alldone": self.alldone_at is not None,
                "progress": self.progress(), "T_rep": self.rep_times, "p_rep": self.rep_progress,
                "T_destroy": self.destroy_at, "p_destroy": self.destroy_progress,
                "T_dead": self.dead_times, "T_done": self.done_times,
                "upstat_at_rep": self.rep_stats, "crashes_sent": self.crashes_sent,
            })

    def prepare_report(self, *, force: bool = False) -> dict:
        """정상 종료 또는 강제 중단의 최종 report를 고정하고 변경을 차단함."""
        with self.lock:
            if self.frozen_report is None:
                now = self._now()
                forced = force and self.terminal
                if (not forced and exit_code_locked(self, now) is None) or self._inflight:
                    raise LifecycleError("tracker is not ready to finish", operation="prepare_report")
                self.frozen_report = deepcopy(build_locked(self, now))
            result = deepcopy(self.frozen_report)
        self._flush()
        return result
