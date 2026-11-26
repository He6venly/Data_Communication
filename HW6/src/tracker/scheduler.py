"""START 기준 장애·생존·완료·중단 조건을 상태 Lock 안에서 판정함."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .observer import replica_safe

if TYPE_CHECKING:
    from .state import TrackerState


@dataclass(frozen=True, slots=True)
class Command:
    """지시의 고유 번호·대상·종류·대기 시간을 보관함."""

    serial: int
    target: str
    kind: str
    seconds: float | None = None

    @property
    def wire(self) -> str:
        """지시를 공통 TCP 응답 한 줄로 변환함."""
        return f"CMD DISCONNECT {self.seconds}" if self.kind == "DISCONNECT" else "CMD DESTROY"


def check_completion(state: TrackerState, now: float) -> None:
    """참가 완료 후 live 전원 DONE인 최초 시각을 고정함."""
    if state.started_at is None or state.terminal:
        return
    live = [pid for pid in state.peers if state.is_live(pid, now)]
    if live and all(pid in state.done for pid in live):
        state.alldone_at = state.elapsed(now)
        state.queue_event("ALLDONE", live=live, done={p: d[0] for p, d in state.done.items()})
        state.drop_unclaimed()


def destroy_due(state: TrackerState, now: float) -> bool:
    """time·progress·after_replication 파괴 시점을 원본 env로 판정함."""
    plan = state.env["destroy"]
    if plan is None or state.destroy_at is not None:
        return False
    if plan["trigger"] == "time":
        due = state.elapsed(now) >= plan["value"]
    elif plan["trigger"] == "progress":
        due = state.progress() >= plan["value"]
    else:
        due = state.rep_progress is not None and state.progress() >= (
            state.rep_progress + plan["value"] * (1 - state.rep_progress)
        )
    return due and (not plan["replica_safe"] or replica_safe(state, plan["peer"], now))


def tick_locked(state: TrackerState, now: float) -> None:
    """DEAD·watchdog·장애 지시를 순서대로 검사하고 종료 후 지시는 버림."""
    if state.started_at is None or state.frozen_report is not None:
        return
    for pid, last in state.last_seen.items():
        if pid not in state.byes and pid not in state.dead and last is not None:
            if now - last > state.env["timing"]["dead_sec"]:
                state.dead.add(pid)
                state.dead_times[pid] = state.elapsed(now)
                state.queue_event("DEAD", id=pid, silent_sec=round(now - last, 2))
    check_completion(state, now)
    if not state.terminal:
        if state.elapsed(now) > state.env["timing"]["deadline_sec"]:
            state.set_abort("deadline", now)
        elif now - state.progress_changed_at >= state.env["timing"]["hang_sec"]:
            state.set_abort("stalled", now)
    for idx, crash in sorted(enumerate(state.env["crashes"]), key=lambda x: x[1]["at_sec"]):
        if idx in state.scheduled or state.elapsed(now) < crash["at_sec"]:
            continue
        state.scheduled.add(idx)
        command = state.new_command(crash["peer"], "DISCONNECT", crash["duration_sec"])
        if state.terminal or state.destroy_delivered == crash["peer"]:
            state.queue_event("CMD_DROPPED", id=command.target, cmd=command.wire)
        else:
            state.pending[command.target].append(command)
            state.queue_event("CMD", target=command.target, cmd=command.kind, sec=command.seconds)
    if not state.terminal and destroy_due(state, now):
        plan = state.env["destroy"]
        command = state.new_command(plan["peer"], "DESTROY")
        state.pending[command.target].appendleft(command)
        state.destroy_at = state.elapsed(now)
        state.destroy_progress = state.progress()
        state.queue_event("CMD", target=command.target, cmd="DESTROY", progress=state.destroy_progress)


def exit_code_locked(state: TrackerState, now: float) -> int | None:
    """전원 퇴장/DEAD 또는 ABORT 유예 만료 뒤의 종료 코드를 반환함."""
    if state.started_at is None:
        return None
    inactive = all(pid in state.byes or pid in state.dead for pid in state.peers)
    if state.abort_reason is not None:
        return 2 if inactive or now - state.aborted_at >= 15 else None
    return 0 if state.alldone_at is not None and inactive else None
