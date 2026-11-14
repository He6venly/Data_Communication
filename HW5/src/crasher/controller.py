import select
import socket
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread
from typing import Callable, Iterator


@dataclass
class PlayerState:
    sock: socket.socket
    mode: str = "IDLE"
    mid: int | None = None
    idle_count: int = 0
    idle_reports: int = 0
    fault_ack: tuple[str, int | None] | None = None


class PlayerController:
    def __init__(self, log: Callable[[str, str, str], None]):
        self.log = log
        self.players: dict[int, PlayerState] = {}
        self.condition = Condition(Lock())
        self.error: BaseException | None = None
        self.threads: list[Thread] = []
        self.closing = Event()

    # 처음 받은 CTRL 줄에서 Player 번호를 확인한다.
    @staticmethod
    def read_ctrl(raw: bytes) -> int:
        if not raw:
            raise ConnectionError("CTRL before connection closed")
        fields = raw.decode("ascii").split()
        if len(fields) != 2 or fields[0] != "CTRL" or not fields[1].startswith("P"):
            raise ValueError("invalid CTRL")
        player = int(fields[1][1:])
        if player not in range(1, 11):
            raise ValueError("player number must be 1..10")
        return player

    # Player의 상태 보고를 공유 상태에 반영하고 대기 중인 스케줄러를 깨운다.
    def update_state(self, player: int, fields: list[str]) -> None:
        if len(fields) < 3 or fields[0] != "STATE" or fields[1] != f"P{player}":
            raise ValueError(f"invalid STATE from P{player}")
        mode = fields[2]
        if mode in ("PLAYING", "CRASHED"):
            if len(fields) != 4:
                raise ValueError(f"{mode} requires mid")
            mid = int(fields[3])
            if mid not in range(45):
                raise ValueError("mid must be 0..44")
        elif mode in ("IDLE", "QUIT", "END"):
            if len(fields) != 3:
                raise ValueError(f"{mode} does not take mid")
            mid = None
        else:
            raise ValueError(f"unknown state {mode}")

        with self.condition:
            state = self.players[player]
            if mode == "IDLE" and state.mode == "PLAYING":
                state.idle_count += 1
            if mode == "IDLE":
                state.idle_reports += 1
            if mode in ("CRASHED", "QUIT"):
                state.fault_ack = (mode, mid)
            state.mode = mode
            state.mid = mid
            self.condition.notify_all()

    # 보조 Thread에서 생긴 오류를 메인 대기 쪽으로 전달한다.
    def record_error(self, error: BaseException) -> None:
        with self.condition:
            if self.error is None:
                self.error = error
            self.condition.notify_all()

    # CTRL과 이후 STATE가 한 TCP 조각에 들어와도 같은 버퍼로 읽는다.
    def read_lines(self, sock: socket.socket) -> Iterator[bytes]:
        buffer = bytearray()
        waiting_for_ctrl = True
        while not self.closing.is_set():
            if waiting_for_ctrl:
                with self.condition:
                    if self.error is not None:
                        raise self.error
            if not select.select([sock], [], [], 0.25)[0]:
                continue
            data = sock.recv(4096)
            if not data:
                return
            buffer.extend(data)
            while (end := buffer.find(b"\n")) != -1:
                raw = bytes(buffer[:end])
                del buffer[:end + 1]
                waiting_for_ctrl = False
                yield raw

    # 한 Player의 제어 연결에서 STATE 줄을 계속 읽는다.
    def receive_states(self, player: int, lines: Iterator[bytes]) -> None:
        try:
            for raw in lines:
                self.update_state(player, raw.decode("ascii").split())
            with self.condition:
                if self.players[player].mode != "END" and not self.closing.is_set():
                    raise ConnectionError(f"P{player} control connection closed before END")
        except (OSError, UnicodeError, ValueError) as error:
            if not self.closing.is_set():
                self.record_error(error)

    # 열 명의 Player가 접속할 때까지 기다린 뒤 상태 수신 Thread를 시작한다.
    def accept_players(self, listener: socket.socket) -> None:
        listener.settimeout(0.25)
        while len(self.players) < 10:
            with self.condition:
                if self.error is not None:
                    raise self.error
            try:
                sock, address = listener.accept()
            except TimeoutError:
                continue
            try:
                lines = self.read_lines(sock)
                player = self.read_ctrl(next(lines, b""))
                with self.condition:
                    if player in self.players:
                        raise ValueError(f"duplicate P{player}")
                    self.players[player] = PlayerState(sock)
                self.log("CONNECT", "SUCCESS", f"P{player} from {address[0]}:{address[1]} ({len(self.players)}/10)")
                thread = Thread(target=self.receive_states, args=(player, lines), name=f"Control-P{player}")
                thread.start()
                self.threads.append(thread)
            except BaseException:
                sock.close()
                raise

    # 이미 상태 Lock을 잡은 곳에서 제어 명령을 보낸다.
    def send_locked(self, player: int, command: str) -> None:
        data = (command + "\n").encode("ascii")
        self.players[player].sock.sendall(data)

    # 선택한 Player에게 상태 Lock을 잡고 제어 명령을 보낸다.
    def send(self, player: int, command: str) -> None:
        with self.condition:
            self.send_locked(player, command)

    # 조건을 만족할 때까지 기다리되 수신 Thread 오류도 함께 확인한다.
    def wait_for(self, predicate) -> None:
        with self.condition:
            self.condition.wait_for(lambda: predicate() or self.error is not None)
            if self.error is not None:
                raise self.error

    # PLAYING에서 IDLE로 바뀐 횟수로 끝난 경기 수를 근사한다.
    def finished_matches(self) -> int:
        return sum(state.idle_count for state in self.players.values()) // 2

    # 모든 제어 연결과 수신 Thread를 정리한다.
    def close(self) -> None:
        self.closing.set()
        for state in self.players.values():
            try:
                state.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            state.sock.close()
        for thread in self.threads:
            thread.join(timeout=1)
