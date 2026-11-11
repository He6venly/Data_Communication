import select
import socket
from dataclasses import dataclass
from pathlib import Path
from random import choice
from threading import Condition, Lock, Thread
from time import monotonic

from .match import Match, MatchResult, Peer
from .output import LeagueLog, log_metrics, save_results
from .rules import PAIRS, PLAYERS, STRATEGIES, standings


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    seed: int
    tables: int
    timeout_ms: int
    run: str
    out: Path


class League:
    def __init__(self, config: ServerConfig, log: LeagueLog):
        self.config = config
        self.log = log
        self.timeout = config.timeout_ms / 1000
        self.players: dict[int, Peer] = {}
        self.pending = list(range(len(PAIRS)))
        self.busy: set[int] = set()
        self.dead: set[int] = set()
        self.results: dict[int, MatchResult] = {}
        self.lobby_wait = [0.0] * config.tables
        self.error: BaseException | None = None
        self.lock = Lock()
        self.lobby_cv = Condition(self.lock)
        self.done_cv = Condition(self.lock)
        self.started = 0.0

    def _hello(self, peer: Peer) -> tuple[int, str]:
        deadline = monotonic() + self.timeout
        while (line := peer.pop_line()) is None:
            remaining = deadline - monotonic()
            if remaining <= 0 or not select.select([peer.sock], [], [], remaining)[0]:
                raise TimeoutError("HELLO timed out")
            peer.read_available()

        fields = line.split()
        if (
            len(fields) != 3 or fields[0] != "HELLO"
            or fields[1] not in {f"P{k}" for k in PLAYERS} or fields[2] not in STRATEGIES
        ):
            raise ValueError("invalid HELLO")
        player = int(fields[1][1:])
        if player in self.players:
            raise ValueError(f"duplicate P{player}")
        return player, fields[2]

    def _accept_players(self, listener: socket.socket) -> None:
        while len(self.players) < len(PLAYERS):
            sock, address = listener.accept()
            try:
                sock.settimeout(self.timeout)
                peer = Peer(sock)
                peer.player, peer.strategy = self._hello(peer)
                peer.send(f"WELCOME {peer.name} {self.config.seed} {self.config.timeout_ms}")
                self.players[peer.player] = peer
            except (OSError, ValueError) as error:
                sock.close()
                self.log("CONNECT", "WARN", f"{address[0]}:{address[1]} {ascii(str(error))}")
                continue
            except BaseException:
                sock.close()
                raise

            self.log(
                "CONNECT", "SUCCESS",
                f"{peer.name} strategy={peer.strategy} from {address[0]}:{address[1]} "
                f"({len(self.players)}/{len(PLAYERS)})",
            )

    def _table(self, table: int) -> None:
        waited = 0.0
        played = 0
        busy_time = 0.0
        try:
            while True:
                with self.lobby_cv:
                    while self.pending and self.error is None:
                        available = [mid for mid in self.pending if self.busy.isdisjoint(PAIRS[mid])]
                        if available:
                            break
                        before = monotonic()
                        self.lobby_cv.wait()
                        waited += monotonic() - before
                    if not self.pending or self.error is not None:
                        break

                    mid = choice(available)
                    self.pending.remove(mid)
                    a, b = PAIRS[mid]
                    self.busy.update((a, b))
                    dead = self.dead.intersection((a, b))

                result = Match(
                    mid, table, (self.players[a], self.players[b]), dead,
                    self.config.seed, self.timeout, self.started, self.log,
                ).play()
                played += 1
                busy_time += result.ended - result.started

                with self.lobby_cv:
                    self.results[mid] = result
                    self.dead.update(result.dead)
                    self.busy.difference_update((a, b))
                    self.lobby_cv.notify_all()
                    if len(self.results) == len(PAIRS):
                        self.done_cv.notify()

            with self.lock:
                self.lobby_wait[table - 1] = waited
            self.log(
                "TABLE", "INFO",
                f"table {table} exit: matches={played} busy={busy_time:.6f}s lobby_wait={waited:.6f}s",
            )
        except Exception as error:
            with self.lobby_cv:
                if self.error is None:
                    self.error = error
                self.lobby_cv.notify_all()
                self.done_cv.notify()

    def _run_tables(self) -> None:
        threads = []
        try:
            for table in range(1, self.config.tables + 1):
                worker = Thread(target=self._table, args=(table,), name=f"Table-{table}")
                worker.start()
                threads.append(worker)
            with self.done_cv:
                self.done_cv.wait_for(lambda: len(self.results) == len(PAIRS) or self.error is not None)
                if self.error is not None:
                    raise self.error
            for worker in threads:
                worker.join()
            if self.error is not None:
                raise self.error
        except BaseException as error:
            with self.lobby_cv:
                if self.error is None:
                    self.error = error
                self.lobby_cv.notify_all()
            for peer in self.players.values():
                try:
                    peer.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            for worker in threads:
                worker.join()
            raise

    def run(self, listener: socket.socket) -> None:
        try:
            self._accept_players(listener)
            self.started = monotonic()
            for peer in self.players.values():
                peer.send(f"START {len(PAIRS)}")
            self.log("START", "INFO", f"{len(PAIRS)} matches, {self.config.tables} tables")
            self._run_tables()

            matches = [self.results[mid] for mid in range(len(PAIRS))]
            ranking = standings([(match.mid, match.outcome, match.scores) for match in matches])
            save_results(
                self.config.out, self.config.run, self.config.seed, self.config.tables,
                matches, ranking, self.log,
            )
            for rank, row in enumerate(ranking, 1):
                peer = self.players[row.player]
                if row.player not in self.dead:
                    peer.send(f"LEAGUE_END {rank} {row.points}")
                peer.send("BYE")
            elapsed = log_metrics(
                matches, self.started, self.lobby_wait, ranking,
                {player: peer.strategy for player, peer in self.players.items()}, self.log,
            )
            self.log("TERMINATE", "SUCCESS", f"{len(matches)} matches in {elapsed:.3f}s, tables joined")
        finally:
            for peer in self.players.values():
                peer.sock.close()


def serve(config: ServerConfig) -> None:
    config.out.mkdir(parents=True, exist_ok=True)
    for suffix in ("results", "standings", "match_log", "League"):
        path = config.out / f"Run{config.run}_{suffix}.txt"
        if path.exists():
            raise FileExistsError(f"output already exists: {path}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((config.host, config.port))
        listener.listen(len(PLAYERS))
        host, port = listener.getsockname()
        log_path = config.out / f"Run{config.run}_League.txt"
        with log_path.open("x", encoding="ascii", newline="\n") as stream:
            log = LeagueLog(stream)
            log(
                "INIT", "SUCCESS",
                f"seed={config.seed} tables={config.tables} timeout={config.timeout_ms}ms listen {host}:{port}",
            )
            try:
                League(config, log).run(listener)
            except (Exception, KeyboardInterrupt) as error:
                log("TERMINATE", "FAIL", ascii(str(error) or type(error).__name__))
                raise
