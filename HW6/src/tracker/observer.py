"""최근 REPORT로 복제 완료와 안전한 파괴 조건을 계산함."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import TrackerState


@dataclass(frozen=True, slots=True)
class PeerReport:
    """파일별 bitmap·송출 통계·수신 시각을 함께 보관함."""

    bitmap: str
    sent: int
    distinct: int
    received_at: float


def fresh_report(state: TrackerState, pid: str, name: str, now: float) -> PeerReport | None:
    """살아 있고 유효기간 안에 보고한 파일 상태만 반환함."""
    report = state.reports.get((pid, name))
    if not state.is_live(pid, now) or report is None:
        return None
    if now - report.received_at > state.env["timing"]["report_stale_sec"]:
        return None
    return report


def coverage(state: TrackerState, name: str, exclude: str, now: float) -> int:
    """제외한 피어 외의 최근 live bitmap을 비트 OR로 합침."""
    union = 0
    for pid in state.peers:
        report = fresh_report(state, pid, name, now)
        if pid != exclude and report is not None:
            union |= int(report.bitmap, 2)
    return union


def replica_safe(state: TrackerState, victim: str, now: float) -> bool:
    """희생자가 가진 모든 청크에 다른 live 사본이 있는지 확인함."""
    for name in state.files:
        own = fresh_report(state, victim, name, now)
        if own is None:
            return False
        bits = int(own.bitmap, 2)
        if bits & ~coverage(state, name, victim, now):
            return False
    return True


def observe_locked(state: TrackerState, now: float) -> None:
    """파일별 최초 복제 시각과 당시 원본 송출 통계를 고정함."""
    if state.started_at is None or state.terminal or state.frozen_report is not None:
        return
    for name, file in state.files.items():
        if state.rep_times[name] is not None:
            continue
        full = (1 << state.nchunks[name]) - 1
        if coverage(state, name, file["origin"], now) != full:
            continue
        state.rep_times[name] = state.elapsed(now)
        # 원본 REPORT가 오래됐더라도 관측 시점의 마지막 송출 통계는 보존함.
        origin = state.reports.get((file["origin"], name))
        stats = (origin.sent, origin.distinct) if origin else None
        state.rep_stats[name] = stats
        state.queue_event("REPLICATED", file=name, t_start=state.rep_times[name],
                          upstat=list(stats) if stats else None, progress=state.progress())
    if state.rep_progress is None and all(t is not None for t in state.rep_times.values()):
        state.rep_progress = state.progress()
        state.queue_event("ALL_REPLICATED", t_start=state.elapsed(now), p_rep=state.rep_progress)
