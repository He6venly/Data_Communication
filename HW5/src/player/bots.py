import hashlib

STRATEGIES = ("RANDOM", "MATCH", "PLUS1", "BIGSMALL", "TEAM")


def seed_of(text):
    # 이름표를 해시로 바꿔서 경기마다 같은 난수로 시작하게 해줌
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % (2**31)


class LCG:
    def __init__(self, seed):
        self.x = seed % (2**31)

    def next(self):
        self.x = (1103515245 * self.x + 12345) % (2**31)
        return self.x >> 16


def prize_order(S, mid):
    # 상금은 테이블이나 경기 진행 순서랑 관계없이 같은 순서로 섞어줌
    prizes = list(range(1, 11))
    rng = LCG(seed_of(f"{S}:{mid}"))
    for i in range(9, 0, -1):
        j = rng.next() % (i + 1)
        prizes[i], prizes[j] = prizes[j], prizes[i]
    return prizes


def team_choose(p, r, hand, history, prizes_left, rng):
    # 최고 상금에는 최고 카드를 쓰고 그전에는 최고 카드를 남겨둠
    if p == max(prizes_left):
        return hand[-1]
    return next((card for card in hand[:-1] if card >= p + 2), hand[0])


class Bot:
    def __init__(self, strategy, S, mid, k):
        if strategy not in STRATEGIES:
            raise ValueError("unknown strategy")
        self.strategy = strategy
        self.hand = list(range(1, 11))
        self.history = []
        self.prizes_left = set(range(1, 11))
        label = f"{S}:{mid}:{k}" + (":TEAM" if strategy == "TEAM" else "")
        self.rng = LCG(seed_of(label))

    def choose(self, prize, r):
        # 고를 때는 손패를 그대로 두고 공개가 끝난 뒤에만 카드를 빼줌
        if self.strategy == "RANDOM":
            return self.hand[self.rng.next() % len(self.hand)]
        if self.strategy == "MATCH":
            return prize
        if self.strategy == "PLUS1":
            return next((c for c in self.hand if c > prize), self.hand[0])
        if self.strategy == "BIGSMALL":
            return self.hand[-1] if prize >= 6 else self.hand[0]
        return team_choose(prize, r, self.hand, self.history, self.prizes_left, self.rng)

    def play(self, prize, r, my_card, opp_card):
        self.hand.remove(my_card)
        self.prizes_left.remove(prize)
        self.history.append((r, prize, my_card, opp_card))
