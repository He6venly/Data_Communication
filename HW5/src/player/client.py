from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import random
import secrets
import select
import socket
import threading
import time

from .bots import Bot, prize_order
from .control import Lines, State, send_line

PAIRS = [(a, b) for a in range(1, 11) for b in range(a + 1, 11)]


def card_hash(card, nonce):
    return hashlib.sha256(f"{card}:{nonce}".encode("ascii")).hexdigest()


class PlayerLog:
    def __init__(self, out, run, player):
        Path(out).mkdir(parents=True, exist_ok=True)
        self.file = (Path(out) / f"Run{run}_P{player}.txt").open("x", encoding="ascii", newline="\n")
        self.player, self.lock = player, threading.Lock()

    def __call__(self, event, status, message):
        # 게임이랑 제어 로그가 섞이지 않게 한 줄씩 KST 시각으로 적어줌
        stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M:%S.%f")[:-3]
        with self.lock:
            self.file.write(f"[{stamp}] P{self.player} | {event} | {status} | {message}\n")
            self.file.flush()

    def close(self):
        self.file.close()


class Player:
    def __init__(self, args, sock, log):
        self.args, self.sock, self.log = args, sock, log
        self.lines = Lines(sock)
        self.state = State(args.id, sock, log)
        self.seed = None
        self.timeout_ms = None
        self.started = False
        self.bot = None
        self.mid = None
        self.side = None
        self.r = 0
        self.phase = None
        self.scores = [0, 0]
        self.opp_hand = set(range(1, 11))
        self.stats = [0, 0, 0]
        self.rank, self.pts = None, None
        self.failed = False
        self.match_failed = False
        self.fault_used = False
        self.seen = set()
        self.generation = 0

    def verify(self, condition, reason):
        # 공개된 해시랑 점수가 내 계산과 다르면 검산 실패를 남겨줌
        if not condition:
            self.failed = True
            self.match_failed = True
            game = f"G{self.mid:02d}" if self.mid is not None else "LEAGUE"
            self.log("VERIFY", "FAIL", f"{game} r={self.r} {reason}")
        return condition

    def _recover(self):
        # 버퍼랑 소켓에 쌓인 줄을 버린 다음 새 MATCH부터 다시 참여함
        with self.state.lock:
            bye = False
            while (line := self.lines.pop()) is not None:
                bye |= line == "BYE"
            if bye:
                return "BYE"
            while select.select([self.sock], [], [], 0)[0]:
                self.lines.receive()
                while (line := self.lines.pop()) is not None:
                    bye |= line == "BYE"
                if bye:
                    return "BYE"
            self.discard_partial = bool(self.lines.buffer)
            self.bot, self.mid, self.phase = None, None, None
            if hasattr(self, "forfeit"):
                del self.forfeit
            if bye:
                return "BYE"
            send_line(self.sock, f"REJOIN P{self.args.id}")
            self.log("REJOIN", "INFO", "REJOIN sent (waiting for new MATCH)")
            self.state.mode = "IDLE"
            self.state.report()
        return None

    def read(self):
        while True:
            with self.state.lock:
                if self.state.error is not None:
                    raise ConnectionError(f"control failed: {self.state.error}")
                recovering = self.state.mode == "RECOVERING"
            if recovering:
                bye = self._recover()
                if bye:
                    return bye
            line = self.lines.pop()
            if line is not None:
                if getattr(self, "discard_partial", False):
                    self.discard_partial = False
                    continue
                return line
            ready, _, _ = select.select([self.sock, self.state.wake_read], [], [])
            if self.state.wake_read in ready:
                self.state.wake_read.recv(4096)
                continue
            self.lines.receive()

    def fault(self):
        # 설정에 적힌 경기랑 판에서만 고장을 한 번 적용해줌
        target = self.args.fault
        if target and not self.fault_used and (self.mid, self.r) == target[1:]:
            self.fault_used = True
            kind = target[0]
            if kind == "quit":
                with self.state.lock:
                    self.state._apply("QUIT", fault=True)
            else:
                self.log("FAULT", "WARN", f"G{self.mid:02d} r={self.r} {kind}")
            return kind
        return None

    def handle(self, line):
        # 메시지 순서대로 카드 선택이랑 검산을 하고 다음 단계로 넘어감
        if line == "BYE":
            return False
        with self.state.lock:
            if self.state.mode in ("CRASHED", "QUIT", "RECOVERING"):
                return True
        fields = line.split(" ")
        kind = fields[0]
        if kind == "WELCOME" and len(fields) == 4 and self.seed is None:
            if fields[1] != f"P{self.args.id}":
                raise ValueError("WELCOME player mismatch")
            self.seed, self.timeout_ms = map(int, fields[2:])
            if self.timeout_ms <= 0:
                raise ValueError("invalid timeout")
            if self.args.crasher:
                self.state.start_control(self.args.crasher)
            return True
        if kind == "START" and fields == ["START", "45"] and self.seed is not None:
            self.started = True
            self.log("START", "INFO", "45 matches")
            return True
        if kind == "MATCH" and len(fields) == 4 and self.started:
            mid = int(fields[1])
            if not 0 <= mid < 45 or fields[2] not in ("A", "B"):
                raise ValueError("invalid MATCH")
            side = 0 if fields[2] == "A" else 1
            pair = PAIRS[mid]
            if pair[side] != self.args.id or fields[3] != f"P{pair[1-side]}" or mid in self.seen:
                raise ValueError("MATCH pairing mismatch")
            self.mid, self.side, self.r = mid, side, 0
            self.match_failed = False
            self.scores, self.opp_hand = [0, 0], set(range(1, 11))
            self.bot = Bot(self.args.strategy, self.seed, mid, self.args.id)
            self.phase = "ROUND"
            self.generation = self.state.match(mid)
            self.log("MATCH", "INFO", f"G{mid:02d} side={fields[2]} opp={fields[3]}")
            return True
        if kind == "LEAGUE_END" and len(fields) == 3:
            self.rank, self.pts = map(int, fields[1:])
            self.verify(1 <= self.rank <= 10 and 0 <= self.pts <= 27, "invalid league ranking")
            if self.args.run != "D":
                self.verify(self.pts == 3*self.stats[0]+self.stats[1], "league points mismatch")
            return True
        if kind not in ("ROUND", "COMMITS", "REVEALS", "FORFEIT", "MATCH_END"):
            raise ValueError(f"unexpected message: {kind}")
        if self.bot is None or len(fields) < 2 or fields[1] != str(self.mid):
            self.log("STALE", "INFO", f"dropped {kind}")
            return True
        if kind == "ROUND" and len(fields) == 4:
            if self.phase != "ROUND" or int(fields[2]) != self.r+1 or self.r >= 10:
                raise ValueError("ROUND order mismatch")
            self.r, self.prize = map(int, fields[2:])
            if self.prize != prize_order(self.seed, self.mid)[self.r-1]:
                raise ValueError("prize order mismatch")
            with self.state.lock:
                self.state.round = self.r
            fault = self.fault()
            time.sleep(random.uniform(*self.args.think)/1000)
            if fault == "slow":
                time.sleep(self.timeout_ms/1000 + 1)
            self.card = 11 if fault == "badcard" else self.bot.choose(self.prize, self.r)
            self.nonce = secrets.token_hex(8)
            self.hash = card_hash(self.card, self.nonce)
            self.bad_hash = fault == "badhash"
            self.state.send(f"COMMIT {self.mid} {self.r} {self.hash}", self.generation)
            self.phase = "COMMITS"
        elif kind == "COMMITS" and len(fields) == 5:
            if self.phase != "COMMITS" or fields[2] != str(self.r):
                raise ValueError("COMMITS order mismatch")
            self.hashes = fields[3:]
            self.verify(self.hashes[self.side] == self.hash, "own COMMIT mismatch")
            card = self.card % 10 + 1 if self.bad_hash else self.card
            self.state.send(f"REVEAL {self.mid} {self.r} {card} {self.nonce}", self.generation)
            self.phase = "REVEALS"
        elif kind == "REVEALS" and len(fields) == 10:
            if self.phase != "REVEALS" or fields[2] != str(self.r):
                raise ValueError("REVEALS order mismatch")
            cards, nonces = [int(fields[3]), int(fields[5])], [fields[4], fields[6]]
            for side in (0, 1):
                self.verify(card_hash(cards[side], nonces[side]) == self.hashes[side], "public hash mismatch")
            own, opp = cards[self.side], cards[1-self.side]
            self.verify(own == self.card and nonces[self.side] == self.nonce, "own reveal mismatch")
            if own not in self.bot.hand or opp not in self.opp_hand:
                raise ValueError("revealed card not in hand")
            winner = "A" if cards[0] > cards[1] else "B" if cards[1] > cards[0] else "-"
            if winner != "-":
                self.scores[0 if winner == "A" else 1] += self.prize
            self.verify(fields[7] == winner, "winner mismatch")
            self.verify(list(map(int, fields[8:])) == self.scores, "round score mismatch")
            self.bot.play(self.prize, self.r, own, opp)
            self.opp_hand.remove(opp)
            self.phase = "END" if self.r == 10 else "ROUND"
        elif kind == "FORFEIT" and len(fields) == 4:
            who = fields[2]
            if who not in ("A", "B", "BOTH"):
                raise ValueError("invalid FORFEIT side")
            self.scores = [0, 55] if who == "A" else [55, 0] if who == "B" else [0, 0]
            self.phase, self.forfeit = "END", f"FORFEIT_{who}"
            self.log("FORFEIT", "WARN", f"G{self.mid:02d} who={who} reason={fields[3]}")
        elif kind == "MATCH_END" and len(fields) == 5:
            expected = getattr(self, "forfeit", None)
            if expected is None:
                expected = "WIN_A" if self.scores[0] > self.scores[1] else "WIN_B" if self.scores[1] > self.scores[0] else "DRAW"
            self.verify(self.phase == "END" and fields[2] == expected, "match outcome mismatch")
            self.verify(list(map(int, fields[3:])) == self.scores, "match score mismatch")
            if expected == "DRAW":
                self.stats[1] += 1
            elif expected == "FORFEIT_BOTH" or expected in ("FORFEIT_A", "FORFEIT_B") and expected[-1] == "AB"[self.side]:
                self.stats[2] += 1
            else:
                won = self.scores[self.side] > self.scores[1-self.side]
                self.stats[0 if won else 2] += 1
            self.state.send(f"CONFIRM {self.mid} {self.scores[0]}:{self.scores[1]}", self.generation)
            self.log("RESULT", "WARN" if self.match_failed else "SUCCESS", f"G{self.mid:02d} {self.scores[0]}:{self.scores[1]} {expected}")
            self.seen.add(self.mid)
            self.bot = None
            if hasattr(self, "forfeit"):
                del self.forfeit
            with self.state.lock:
                if self.state.mode == "PLAYING" and self.generation == self.state.generation:
                    self.state.mode = "IDLE"
                    self.state.report()
        else:
            raise ValueError(f"invalid {kind} fields")
        return True

    def run(self):
        # BYE까지 소켓을 유지하고 마지막 로그에 실제 종료 상태를 남겨줌
        try:
            send_line(self.sock, f"HELLO P{self.args.id} {self.args.strategy}")
            self.log("CONNECT", "SUCCESS", f"server={self.args.host}:{self.args.port} strategy={self.args.strategy}")
            while self.handle(self.read()):
                pass
            with self.state.lock:
                self.state.mode = "END"
                self.state.report()
            self.state.close()
            if self.state.quit_mid is not None:
                self.log("TERMINATE", "WARN", f"left at G{self.state.quit_mid:02d} BYE received")
            elif self.rank is not None:
                w, d, l = self.stats
                missing = 9 - len(self.seen)
                residual = self.pts - (3*w+d)
                # 버린 경기의 전적은 승점으로 하나로 정해질 때만 채우고 애매하면 따로 표시함
                possibilities = [(a, b, missing-a-b) for a in range(missing+1)
                                 for b in range(missing-a+1) if 3*a+b == residual]
                extra = ""
                status = "SUCCESS"
                if self.args.run == "D" and len(possibilities) == 1:
                    a, b, c = possibilities[0]
                    w, d, l = w+a, d+b, l+c
                elif self.args.run == "D" and missing:
                    status = "WARN"
                    extra = f" observed_only=yes missing={missing} (results discarded during crash)"
                self.log("TERMINATE", "FAIL" if self.failed else status, f"rank={self.rank} pts={self.pts} W{w} D{d} L{l}{extra}")
            else:
                self.log("TERMINATE", "WARN", "BYE received before league ranking")
            return 1 if self.failed else 0
        except (OSError, EOFError, ValueError, KeyboardInterrupt) as exc:
            with self.state.lock:
                self.state.mode = "END"
            self.state.close()
            self.log("TERMINATE", "FAIL", f"reason={ascii(str(exc))}")
            return 130 if isinstance(exc, KeyboardInterrupt) else 1
