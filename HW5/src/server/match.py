import select
import socket
from dataclasses import dataclass, field
from time import monotonic

from .output import LeagueLog
from .rules import CARDS, SIDES, card_hash, forfeit, prize_order, winner


@dataclass
class Peer:
    sock: socket.socket
    player: int = 0
    strategy: str = ""
    buffer: bytearray = field(default_factory=bytearray)

    @property
    def name(self) -> str:
        return f"P{self.player}"

    def send(self, line: str) -> None:
        self.sock.sendall(f"{line}\n".encode("ascii"))

    def read_available(self) -> None:
        data = self.sock.recv(4096)
        if not data:
            raise ConnectionError(f"{self.name} closed its TCP connection")
        self.buffer.extend(data)

    def pop_line(self) -> str | None:
        end = self.buffer.find(b"\n")
        if end < 0:
            return None
        line = self.buffer[:end].decode("ascii", errors="replace")
        del self.buffer[:end + 1]
        return line


@dataclass
class MatchResult:
    mid: int
    table: int
    started: float
    ended: float
    outcome: str
    scores: tuple[int, int]
    confirmations: tuple[str, str]
    dead: set[int]
    lines: list[str]
    commit_times: list[float]
    stale: int
    forfeit_round: int | None
    reason: str


class Match:
    def __init__(
        self,
        mid: int,
        table: int,
        peers: tuple[Peer, Peer],
        dead: set[int],
        seed: int,
        timeout: float,
        league_start: float,
        log: LeagueLog,
    ):
        self.mid = mid
        self.game = f"G{mid:02d}"
        self.table = table
        self.peers = peers
        self.dead = dead
        self.prizes = prize_order(seed, mid)
        self.timeout = timeout
        self.league_start = league_start
        self.log = log
        self.lines: list[str] = []
        self.commit_times: list[float] = []
        self.stale = 0

    def _broadcast(self, message: str) -> None:
        for peer in self.peers:
            if peer.player not in self.dead:
                peer.send(message)

    def _ask(
        self, message: str, kind: str, round_no: int | None = None,
    ) -> tuple[dict[int, list[str]], dict[int, str], float]:
        sent_at = monotonic()
        self._broadcast(message)
        deadline = monotonic() + self.timeout
        waiting = {side: peer for side, peer in enumerate(self.peers) if peer.player not in self.dead}
        expected = [kind, str(self.mid)]
        if round_no is not None:
            expected.append(str(round_no))
        waiting_for = " ".join(expected)
        replies: dict[int, list[str]] = {}
        faults: dict[int, str] = {}

        while waiting:
            # Each Table reads both of its players against the same deadline.
            for side, peer in list(waiting.items()):
                while (line := peer.pop_line()) is not None:
                    fields = line.split()
                    if fields == ["REJOIN", peer.name]:
                        self.log("REJOIN", "INFO", f"{peer.name} rejoined (waiting {waiting_for})")
                        continue
                    if fields == ["QUIT", str(self.mid)]:
                        self.dead.add(peer.player)
                        faults[side] = "DISCONNECT"
                        self.log(
                            "DISCONN", "WARN",
                            f"{peer.name} QUIT (virtual disconnect) in {self.game} -> DEAD",
                        )
                    elif fields[:len(expected)] == expected:
                        replies[side] = fields
                    else:
                        self.stale += 1
                        self.log("STALE", "WARN", f"{peer.name} dropped {ascii(line)} (waiting {waiting_for})")
                        continue
                    del waiting[side]
                    break
            if not waiting:
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([peer.sock for peer in waiting.values()], [], [], remaining)
            if not ready or monotonic() > deadline:
                break
            for peer in waiting.values():
                if peer.sock in ready:
                    peer.read_available()

        for side in waiting:
            faults[side] = "TIMEOUT"
        return replies, faults, monotonic() - sent_at

    def _play_rounds(self) -> tuple[tuple[int, int], dict[int, str], int]:
        hands = [set(CARDS), set(CARDS)]
        scores = [0, 0]
        for round_no, prize in enumerate(self.prizes, 1):
            commits, faults, latency = self._ask(
                f"ROUND {self.mid} {round_no} {prize}", "COMMIT", round_no,
            )
            if len(commits) == 2:
                self.commit_times.append(latency)
            for side, fields in commits.items():
                if len(fields) != 4 or not fields[3].isascii():
                    faults[side] = "BAD_MSG"
            if faults:
                return (scores[0], scores[1]), faults, round_no

            hashes = [commits[side][3] for side in (0, 1)]
            reveals, faults, _ = self._ask(
                f"COMMITS {self.mid} {round_no} {hashes[0]} {hashes[1]}", "REVEAL", round_no,
            )
            cards: dict[int, tuple[int, str]] = {}
            for side, fields in reveals.items():
                try:
                    if len(fields) != 5 or not fields[4].isascii():
                        raise ValueError
                    card, nonce = int(fields[3]), fields[4]
                except ValueError:
                    faults[side] = "BAD_MSG"
                    continue
                if card_hash(card, nonce) != hashes[side]:
                    faults[side] = "BAD_HASH"
                elif card not in hands[side]:
                    faults[side] = "BAD_CARD"
                else:
                    cards[side] = card, nonce
            if faults:
                return (scores[0], scores[1]), faults, round_no

            (card_a, nonce_a), (card_b, nonce_b) = cards[0], cards[1]
            hands[0].remove(card_a)
            hands[1].remove(card_b)
            side = winner(card_a, card_b)
            if side != "-":
                scores[SIDES.index(side)] += prize
            score_a, score_b = scores
            self._broadcast(
                f"REVEALS {self.mid} {round_no} {card_a} {nonce_a} {card_b} {nonce_b} "
                f"{side} {score_a} {score_b}"
            )
            self.lines.append(
                f"R {self.mid:02d} {round_no} {prize} {card_a} {nonce_a} {hashes[0]} "
                f"{card_b} {nonce_b} {hashes[1]} {side} {score_a} {score_b}"
            )
        return (scores[0], scores[1]), {}, len(CARDS)

    def play(self) -> MatchResult:
        a, b = self.peers
        started = monotonic()
        self.log("MATCH", "INFO", f"{self.game} {a.name}({a.strategy}) vs {b.name}({b.strategy}) table={self.table}")
        self.lines.append(
            f"MATCH {self.mid:02d} {a.name} {b.name} table={self.table} t={started - self.league_start:.6f}"
        )
        for side, peer in enumerate(self.peers):
            if peer.player not in self.dead:
                peer.send(f"MATCH {self.mid} {SIDES[side]} {self.peers[1 - side].name}")

        faults = {side: "DISCONNECT" for side, peer in enumerate(self.peers) if peer.player in self.dead}
        round_no = 0
        scores = (0, 0)
        if len(faults) == 1:
            _, attendance_faults, _ = self._ask(f"ROUND {self.mid} 1 {self.prizes[0]}", "COMMIT", 1)
            faults.update(attendance_faults)
        elif not faults:
            scores, faults, round_no = self._play_rounds()

        forfeit_round = None
        reason = ""
        if faults:
            who, reason, scores = forfeit(faults)
            outcome = f"FORFEIT_{who}"
            forfeit_round = round_no
            self.log(
                "FORFEIT", "WARN",
                f"{self.game} {a.name} vs {b.name} round={round_no} forfeit={who} reason={reason}",
            )
            self.lines.append(f"F {self.mid:02d} {round_no} {who} {reason}")
            self._broadcast(f"FORFEIT {self.mid} {who} {reason}")
        else:
            side = winner(*scores)
            outcome = "DRAW" if side == "-" else f"WIN_{side}"

        score_a, score_b = scores
        replies, _, _ = self._ask(
            f"MATCH_END {self.mid} {outcome} {score_a} {score_b}", "CONFIRM",
        )
        confirmations = []
        for side, peer in enumerate(self.peers):
            if peer.player in self.dead:
                status = "-"
            elif side not in replies:
                status = "NO"
            elif replies[side] == ["CONFIRM", str(self.mid), f"{score_a}:{score_b}"]:
                status = "OK"
            else:
                status = "DISPUTE"
            confirmations.append(status)

        ended = monotonic()
        self.lines.append(f"END {self.mid:02d} {outcome} {score_a}:{score_b} t={ended - self.league_start:.6f}")
        self.log(
            "RESULT", "SUCCESS",
            f"{self.game} {a.name} {score_a}:{score_b} {b.name} {outcome} "
            f"confirm={'/'.join(confirmations)} {(ended - started) * 1000:.0f}ms",
        )
        return MatchResult(
            self.mid, self.table, started, ended, outcome, scores,
            (confirmations[0], confirmations[1]), self.dead, self.lines, self.commit_times,
            self.stale, forfeit_round, reason,
        )
