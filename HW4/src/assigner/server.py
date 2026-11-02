"""작업자의 접속을 확인하고 담당 띠를 전달한다."""

import math
import socket
import time
from collections.abc import Callable

from .partition import assignment_rows, bands
from .storage import Canvas
from .transport import LineConnection, PhaseTimeout, ProtocolError, remaining


def accept_workers(host: str, port: int, n: int, team: int,
                   canvases: tuple[Canvas, Canvas, Canvas], startup_timeout: float,
                   on_ready: Callable[[tuple], None],
                   on_connect: Callable[[int], None] = lambda k: None,
                   on_assign: Callable[[int, int, int], None] = lambda k, y0, y1: None) -> list[LineConnection]:
    ranges = bands(n)
    if team <= 0 or not math.isfinite(startup_timeout) or startup_timeout <= 0:
        raise ValueError("팀 번호와 제한시간은 양수여야 합니다")
    connections: list[LineConnection] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((host, port))
            listener.listen(n)
            deadline = time.monotonic() + startup_timeout
            on_ready(listener.getsockname())
            # 접속 순서대로 번호를 부여하고 전원의 인사를 확인한 뒤 할당한다.
            for k, _ in enumerate(ranges):
                listener.settimeout(remaining(deadline))
                try:
                    sock, _ = listener.accept()
                except socket.timeout as exc:
                    raise TimeoutError("접속 제한시간을 초과했습니다") from exc
                connection = LineConnection(sock)
                connections.append(connection)
                if connection.read_line(deadline, 5) != b"HELLO":
                    raise ProtocolError("잘못된 HELLO 메시지입니다")
                on_connect(k)
            for k, ((y0, y1), connection) in enumerate(zip(ranges, connections)):
                header = f"ASSIGN {k} {n} {y0} {y1} {team}"
                rows = assignment_rows(canvases, y0, y1)
                message = ("\n".join((header, *rows)) + "\n").encode("ascii")
                connection.send(message, deadline)
                on_assign(k, y0, y1)
        return connections
    except BaseException as exc:
        for connection in connections:
            connection.close()
        if isinstance(exc, TimeoutError):
            raise PhaseTimeout("startup", startup_timeout) from exc
        raise
