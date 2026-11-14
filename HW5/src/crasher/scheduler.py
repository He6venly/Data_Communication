import random
import time
from dataclasses import dataclass
from threading import Thread

from .controller import PlayerController


PAIRS = [(a, b) for a in range(1, 11) for b in range(a + 1, 11)]


@dataclass(frozen=True)
class CrashEvent:
    kind: str
    trigger: int


class CrashScheduler:
    def __init__(self, controller: PlayerController, seed: int):
        self.controller = controller
        self.random = random.Random(seed)
        self.seed = seed
        self.events = self.make_plan()
        self.faulty: set[int] = set()
        self.pending: set[int] = set()
        self.blocked_mids: set[int] = set()
        self.restart_threads: list[Thread] = []
        self.fired = 0

    # seed를 이용해 장애 수, 종류, 발생 기준을 한 번만 만든다.
    def make_plan(self) -> list[CrashEvent]:
        count = self.random.randint(4, 7)
        quit_count = self.random.randint(1, min(2, count))
        kinds = ["QUIT"] * quit_count + ["CRASH"] * (count - quit_count)
        self.random.shuffle(kinds)
        triggers = sorted(self.random.sample(range(2, 31), count))
        return [CrashEvent(kind, trigger) for kind, trigger in zip(kinds, triggers)]

    # Crasher 로그 첫 줄에 사용할 전체 계획 문자열을 만든다.
    def plan_message(self) -> str:
        crash_count = sum(event.kind == "CRASH" for event in self.events)
        quit_count = len(self.events) - crash_count
        kinds = " ".join(event.kind for event in self.events)
        triggers = ", ".join(str(event.trigger) for event in self.events)
        return (
            f"seed={self.seed} events={len(self.events)} (crash {crash_count}, quit {quit_count}) "
            f"kinds={kinds} triggers(finished)=[{triggers}]"
        )

    # 모든 Player가 END 또는 QUIT이면 더 주입할 경기가 없다고 판단한다.
    def league_over(self) -> bool:
        return bool(self.controller.players) and all(
            state.mode in ("END", "QUIT") for state in self.controller.players.values()
        )

    # 현재 경기 중이며 본인과 상대가 장애 집합에 없는 Player를 찾는다.
    def eligible_players(self) -> list[int]:
        active_mids = {
            state.mid for state in self.controller.players.values()
            if state.mode in ("PLAYING", "CRASHED") and state.mid is not None
        }
        self.blocked_mids.intersection_update(active_mids)
        result = []
        for player, state in self.controller.players.items():
            if state.mode != "PLAYING" or player in self.faulty or player in self.pending:
                continue
            if state.mid in self.blocked_mids:
                continue
            a, b = PAIRS[state.mid]
            opponent = b if player == a else a
            opponent_state = self.controller.players[opponent]
            if (
                opponent_state.mode == "PLAYING"
                and opponent_state.mid == state.mid
                and opponent not in self.faulty
                and opponent not in self.pending
            ):
                result.append(player)
        return result

    # 선택 후 지연 동안 경기가 바뀌지 않았는지 다시 확인한다.
    def still_eligible(self, player: int, mid: int) -> bool:
        state = self.controller.players[player]
        a, b = PAIRS[mid]
        opponent = b if player == a else a
        opponent_state = self.controller.players[opponent]
        return (
            state.mode == "PLAYING"
            and state.mid == mid
            and player in self.pending
            and opponent_state.mode == "PLAYING"
            and opponent_state.mid == mid
            and opponent not in self.faulty
            and opponent not in self.pending
        )

    # CRASH ACK부터 4~5초 뒤에 RESTART를 보내고 IDLE 복귀를 확인한다.
    def restart_after_delay(self, number: int, player: int, mid: int, delay: float) -> None:
        try:
            time.sleep(delay)
            with self.controller.condition:
                state = self.controller.players[player]
                if state.mode == "END" or self.controller.error is not None:
                    self.pending.discard(player)
                    self.faulty.discard(player)
                    return
                idle_before = state.idle_reports
                self.controller.send_locked(player, "RESTART")
            self.controller.log("RESTART", "INFO", f"#{number} P{player} after {delay:.2f}s")
            self.controller.wait_for(
                lambda: self.controller.players[player].idle_reports > idle_before
                or self.controller.players[player].mode == "END"
            )
            with self.controller.condition:
                ended = self.controller.players[player].mode == "END"
                self.pending.discard(player)
                self.faulty.discard(player)
            if not ended:
                self.controller.log("REJOINED", "INFO", f"#{number} P{player} back to IDLE")
        except BaseException as error:
            self.controller.record_error(error)

    # 한 사건의 대상을 고르고 명령 직전에 자격을 다시 검사해 전송한다.
    def fire_event(self, number: int, event: CrashEvent) -> bool:
        while True:
            with self.controller.condition:
                if self.controller.error is not None:
                    raise self.controller.error
                candidates = self.eligible_players()
                if not candidates:
                    if self.league_over():
                        return False
                    self.controller.condition.wait()
                    continue
                player = self.random.choice(candidates)
                state = self.controller.players[player]
                mid = state.mid
                self.pending.add(player)

            time.sleep(self.random.uniform(0, 0.3))
            with self.controller.condition:
                if self.controller.error is not None:
                    raise self.controller.error
                if not self.still_eligible(player, mid):
                    self.pending.discard(player)
                    continue
                self.faulty.add(player)
                self.blocked_mids.add(mid)
                state.fault_ack = None
                self.controller.send_locked(player, event.kind)

            ack_mode = "QUIT" if event.kind == "QUIT" else "CRASHED"
            self.controller.wait_for(
                lambda: state.mode == "END" or (state.fault_ack is not None and state.fault_ack[0] == ack_mode)
            )
            with self.controller.condition:
                ack = state.fault_ack
                if ack is None or ack[0] != ack_mode:
                    self.pending.discard(player)
                    self.faulty.discard(player)
                    if self.league_over():
                        return False
                    continue
                ack_mid = ack[1]
                ended = state.mode == "END"
                if ack_mid is not None:
                    self.blocked_mids.add(ack_mid)
                if ended:
                    self.pending.discard(player)
                    self.faulty.discard(player)

            self.controller.log(event.kind, "WARN", f"#{number} P{player} (PLAYING G{mid:02d})")
            self.fired += 1
            if event.kind == "QUIT":
                self.controller.log("QUIT_ACK", "INFO", f"#{number} P{player} reported QUIT")
                return True

            self.controller.log("CRASH_ACK", "INFO", f"#{number} P{player} crashed in G{ack_mid:02d}")
            if ended:
                return True
            delay = self.random.uniform(4, 5)
            thread = Thread(
                target=self.restart_after_delay,
                args=(number, player, ack_mid, delay),
                name=f"Restart-P{player}-{number}",
            )
            thread.start()
            self.restart_threads.append(thread)
            return True

    # 계획한 finished 기준마다 사건을 하나씩 실행한다.
    def run(self) -> None:
        try:
            for number, event in enumerate(self.events, 1):
                self.controller.wait_for(
                    lambda: self.controller.finished_matches() >= event.trigger or self.league_over()
                )
                if self.league_over() or not self.fire_event(number, event):
                    break
        except BaseException as error:
            self.controller.record_error(error)
            raise
        finally:
            for thread in self.restart_threads:
                thread.join()

        self.controller.wait_for(
            lambda: all(state.mode == "END" for state in self.controller.players.values())
        )
        crash_count = sum(event.kind == "CRASH" for event in self.events[:self.fired])
        quit_count = self.fired - crash_count
        self.controller.log(
            "SUMMARY", "INFO",
            f"fired {self.fired}/{len(self.events)} events: crash {crash_count}, quit {quit_count}",
        )
        self.controller.log("TERMINATE", "SUCCESS", "all players ended")
