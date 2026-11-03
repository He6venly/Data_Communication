from dataclasses import dataclass
import socket
import time

from .board import HEIGHT, WIDTH


class ProtocolError(ValueError):
    pass


class PhaseTimeout(TimeoutError):
    def __init__(self, phase, timeout_s):
        super().__init__(f"{phase} 제한시간을 초과했습니다")
        self.phase, self.timeout_s = phase, timeout_s


def connect(host, port, timeout_s):
    # 다른 주소로 다시 접속해도 제한시간은 처음 접속을 시도한 때부터 계산함
    deadline = time.monotonic() + timeout_s
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    error = OSError("접속할 주소가 없습니다")
    for family, kind, protocol, _, address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PhaseTimeout("connect", timeout_s)
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(remaining)
            sock.connect(address)
            if time.monotonic() >= deadline:
                raise PhaseTimeout("connect", timeout_s)
            return sock
        except BaseException as exc:
            sock.close()
            if isinstance(exc, TimeoutError):
                raise PhaseTimeout("connect", timeout_s) from exc
            if not isinstance(exc, OSError):
                raise
            error = exc
    raise error


@dataclass(frozen=True)
class Assignment:
    k: int
    n: int
    y0: int
    y1: int
    team: int
    rows: list
    canvas1: list
    canvas2: list


class Connection:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()

    def _remaining(self, deadline, phase, timeout_s):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PhaseTimeout(phase, timeout_s)
        return remaining

    def line(self, deadline, phase, timeout_s, limit=WIDTH):
        # 데이터가 나뉘거나 한꺼번에 와도 줄 단위로 읽고 메시지 전체의 제한시간을 확인함
        while True:
            remaining = self._remaining(deadline, phase, timeout_s)
            end = self.buffer.find(b"\n")
            if end >= 0:
                if end > limit:
                    raise ProtocolError("줄이 너무 깁니다")
                line = bytes(self.buffer[:end])
                del self.buffer[:end + 1]
                if any(c < 32 or c > 126 for c in line):
                    raise ProtocolError("출력 가능한 ASCII와 LF만 허용합니다")
                return line.decode("ascii")
            if len(self.buffer) > limit:
                raise ProtocolError("줄이 너무 깁니다")
            self.sock.settimeout(remaining)
            try:
                data = self.sock.recv(4096)
            except socket.timeout as exc:
                raise PhaseTimeout(phase, timeout_s) from exc
            if not data:
                raise EOFError("메시지 수신 중 연결이 종료됐습니다")
            self.buffer.extend(data)

    def picture(self, deadline, phase, timeout_s):
        row = self.line(deadline, phase, timeout_s)
        if len(row) != WIDTH:
            raise ProtocolError("그림 줄은 160문자여야 합니다")
        return row

    def send(self, data, deadline, phase, timeout_s):
        # 명령이랑 그림은 한 번에 보내고 보낼 때도 제한시간을 걸어둠
        self.sock.settimeout(self._remaining(deadline, phase, timeout_s))
        try:
            self.sock.sendall(data)
        except socket.timeout as exc:
            raise PhaseTimeout(phase, timeout_s) from exc

    def assignment(self, deadline, timeout_s):
        # Worker 번호랑 띠 범위가 맞는지 확인하고 정해진 3h+4줄만 읽어줌
        fields = self.line(deadline, "startup", timeout_s).split()
        if len(fields) != 6 or fields[0] != "ASSIGN":
            raise ProtocolError("ASSIGN 명령이 필요합니다")
        try:
            k, n, y0, y1, team = map(int, fields[1:])
        except ValueError as exc:
            raise ProtocolError("ASSIGN 필드는 정수여야 합니다") from exc
        if (n not in (1, 4, 5, 6, 7, 8) or not 0 <= k < n or team <= 0
                or (y0, y1) != (HEIGHT * k // n, HEIGHT * (k + 1) // n)):
            raise ProtocolError("ASSIGN 번호 또는 띠 경계가 잘못됐습니다")
        h = y1 - y0
        rows = [self.picture(deadline, "startup", timeout_s) for _ in range(3 * h + 4)]
        return Assignment(k, n, y0, y1, team, rows[:h], rows[h:2*h+2], rows[2*h+2:])

    def round(self, r, deadline, phase, timeout_s):
        # 받아야 하는 Round 번호인지 확인하고 Halo 두 줄까지 같은 제한시간 안에 읽음
        fields = self.line(deadline, phase, timeout_s).split()
        if fields != ["ROUND", str(r)]:
            raise ProtocolError(f"ROUND {r} 명령이 필요합니다")
        return (self.picture(deadline, phase, timeout_s),
                self.picture(deadline, phase, timeout_s))
