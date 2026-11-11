from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations

PLAYERS = tuple(range(1, 11))
CARDS = tuple(range(1, 11))
PAIRS = tuple(combinations(PLAYERS, 2))
STRATEGIES = ("RANDOM", "MATCH", "PLUS1", "BIGSMALL", "TEAM")
SIDES = ("A", "B")
MAX_SCORE = sum(CARDS)
MODULUS = 2**31


def seed_of(label: str) -> int:
    return int(sha256(label.encode("utf-8")).hexdigest()[:8], 16) % MODULUS


def prize_order(seed: int, mid: int) -> list[int]:
    state = seed_of(f"{seed}:{mid}")
    prizes = list(CARDS)
    for index in range(len(prizes) - 1, 0, -1):
        state = (1103515245 * state + 12345) % MODULUS
        other = (state >> 16) % (index + 1)
        prizes[index], prizes[other] = prizes[other], prizes[index]
    return prizes


def card_hash(card: int, nonce: str) -> str:
    return sha256(f"{card}:{nonce}".encode("ascii")).hexdigest()


def winner(score_a: int, score_b: int) -> str:
    if score_a > score_b:
        return "A"
    if score_b > score_a:
        return "B"
    return "-"


def forfeit(faults: dict[int, str]) -> tuple[str, str, tuple[int, int]]:
    if len(faults) == 2:
        return "BOTH", "+".join(dict.fromkeys((faults[0], faults[1]))), (0, 0)
    side = next(iter(faults))
    scores = (0, MAX_SCORE) if side == 0 else (MAX_SCORE, 0)
    return SIDES[side], faults[side], scores


@dataclass
class Standing:
    player: int
    wins: int = 0
    draws: int = 0
    losses: int = 0
    scored: int = 0
    conceded: int = 0

    @property
    def points(self) -> int:
        return 3 * self.wins + self.draws


def standings(games: list[tuple[int, str, tuple[int, int]]]) -> list[Standing]:
    totals = {player: Standing(player) for player in PLAYERS}
    for mid, outcome, scores in games:
        a, b = (totals[player] for player in PAIRS[mid])
        score_a, score_b = scores
        a.scored += score_a
        a.conceded += score_b
        b.scored += score_b
        b.conceded += score_a

        if outcome == "DRAW":
            a.draws += 1
            b.draws += 1
        elif outcome == "FORFEIT_BOTH":
            a.losses += 1
            b.losses += 1
        else:
            won, lost = (a, b) if outcome in ("WIN_A", "FORFEIT_B") else (b, a)
            won.wins += 1
            lost.losses += 1

    return sorted(
        totals.values(),
        key=lambda row: (-row.points, row.conceded - row.scored, -row.scored, row.player),
    )
