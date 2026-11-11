from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, TextIO

from .rules import PAIRS, Standing

if TYPE_CHECKING:
    from .match import MatchResult

KST = timezone(timedelta(hours=9))


class LeagueLog:
    def __init__(self, stream: TextIO):
        self.stream = stream
        self.lock = Lock()

    def __call__(self, event: str, status: str, message: str) -> None:
        with self.lock:
            now = datetime.now(KST).isoformat(sep=" ", timespec="milliseconds")[11:23]
            self.stream.write(f"[{now}] SERVER | {event:<9} | {status:<7} | {message}\n")
            self.stream.flush()


def save_results(
    directory: Path, run: str, seed: int, tables: int,
    matches: list["MatchResult"], ranking: list[Standing], log: LeagueLog,
) -> None:
    result_lines = []
    match_lines = [f"LEAGUE seed={seed} tables={tables}"]
    for match in matches:
        a, b = PAIRS[match.mid]
        score_a, score_b = match.scores
        result_lines.append(f"{match.mid:02d} P{a} P{b} {score_a}:{score_b} {match.outcome}")
        match_lines.extend(match.lines)

    standing_lines = [
        f"{rank} P{row.player} {row.wins} {row.draws} {row.losses} "
        f"{row.points} {row.scored} {row.conceded}"
        for rank, row in enumerate(ranking, 1)
    ]
    hashes = []
    for suffix, lines in (
        ("results", result_lines), ("standings", standing_lines), ("match_log", match_lines),
    ):
        name = f"Run{run}_{suffix}.txt"
        data = ("\n".join(lines) + "\n").encode("ascii")
        with (directory / name).open("xb") as stream:
            stream.write(data)
        if suffix != "match_log":
            hashes.append(f"{name} hash={sha256(data).hexdigest()[:8]}")
    log("SAVE", "SUCCESS", " ".join(hashes))


def log_metrics(
    matches: list["MatchResult"], started: float, lobby_wait: list[float],
    ranking: list[Standing], strategies: dict[int, str], log: LeagueLog,
) -> float:
    elapsed = max(match.ended for match in matches) - started
    durations = [match.ended - match.started for match in matches]
    log(
        "METRICS", "INFO",
        f"total_s={elapsed:.6f} match_avg_ms={sum(durations) * 1000 / len(matches):.3f} "
        f"match_min_ms={min(durations) * 1000:.3f} match_max_ms={max(durations) * 1000:.3f} "
        f"avg_concurrency={sum(durations) / elapsed:.6f}",
    )
    for table, wait in enumerate(lobby_wait, 1):
        busy = [duration for match, duration in zip(matches, durations) if match.table == table]
        log(
            "METRICS", "INFO",
            f"table={table} matches={len(busy)} utilization={sum(busy) / elapsed:.6f} lobby_wait_s={wait:.6f}",
        )
    commits = [latency for match in matches for latency in match.commit_times]
    if commits:
        log(
            "METRICS", "INFO",
            f"commit_samples={len(commits)} commit_avg_ms={sum(commits) * 1000 / len(commits):.3f} "
            f"commit_max_ms={max(commits) * 1000:.3f}",
        )
    confirms = Counter(status for match in matches for status in match.confirmations)
    reasons = Counter(match.reason for match in matches if match.reason)
    walkovers = sum(match.forfeit_round == 0 for match in matches)
    log(
        "METRICS", "INFO",
        f"forfeits={sum(reasons.values()) - walkovers} walkovers={walkovers} "
        f"stale={sum(match.stale for match in matches)} confirm_OK={confirms['OK']} "
        f"confirm_NO={confirms['NO']} confirm_DISPUTE={confirms['DISPUTE']} confirm_-={confirms['-']}",
    )
    for reason, count in sorted(reasons.items()):
        log("METRICS", "INFO", f"forfeit_reason={reason} matches={count}")

    by_strategy: dict[str, list[Standing]] = defaultdict(list)
    for row in ranking:
        by_strategy[strategies[row.player]].append(row)
    for strategy, rows in sorted(by_strategy.items()):
        wins = sum(row.wins for row in rows)
        draws = sum(row.draws for row in rows)
        losses = sum(row.losses for row in rows)
        scored = sum(row.scored for row in rows)
        log(
            "METRICS", "INFO",
            f"strategy={strategy} W={wins} D={draws} L={losses} avg_GF={scored / (wins + draws + losses):.3f}",
        )
    return elapsed
