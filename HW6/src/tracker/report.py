"""Tracker 상태 복사본을 공식 report 형식으로 만들고 원자적으로 저장함."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import TrackerState


def build_locked(state: TrackerState, now: float) -> dict:
    """공식 키 순서와 START 기준 시각으로 결과 객체를 구성함."""
    e = state.env
    def times(values: dict) -> dict:
        """시각만 소수 둘째자리로 반올림하고 미발생 값은 null로 유지함."""
        return {key: round(value, 2) if value is not None else None for key, value in values.items()}
    ratios = {name: ((v[0] - v[1]) / v[0] if v and v[0] else None)
              for name, v in state.rep_stats.items()}
    return {
        "env": e["name"], "run": e["run"], "seed": e["seed"],
        "policy": e["download"]["policy"], "destroy_plan": e["destroy"],
        "crashes_sent": state.crashes_sent,
        "T_rep": times(state.rep_times), "p_rep": state.rep_progress,
        "upstat_at_rep": {n: list(v) if v is not None else None for n, v in state.rep_stats.items()},
        "dup_ratio": ratios,
        "T_destroy": round(state.destroy_at, 2) if state.destroy_at is not None else None,
        "p_destroy": state.destroy_progress,
        "T_dead": times(state.dead_times), "T_done": times(state.done_times),
        "T_last_done": round(max(state.done_times.values()), 2) if state.done_times else None,
        "T_alldone": round(state.alldone_at, 2) if state.alldone_at is not None else None,
        "T_exit": round(state.elapsed(now), 2),
        "done_kind": {p: d[0] for p, d in state.done.items()},
        "peers": {p: ("BYE" if p in state.byes else "DEAD" if p in state.dead else "LIVE")
                  for p in state.peers},
        "abort": state.abort_reason,
    }


def write_report(path: Path, report: dict) -> None:
    """완성된 JSON을 같은 폴더의 임시 파일에 쓴 뒤 결과 파일로 교체함."""
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".report-", suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
