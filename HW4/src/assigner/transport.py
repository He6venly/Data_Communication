"""줄 단위 TCP 수신과 메시지별 제한시간을 처리한다."""

import socket
import time


class ProtocolError(ValueError):
    pass


class PhaseTimeout(TimeoutError):
    def __init__(self, phase: str, timeout_s: float):
        super().__init__(f"{phase} 제한시간을 초과했습니다")
        self.phase = phase
        self.timeout_s = timeout_s


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("통신 제한시간을 초과했습니다")
    return seconds


class LineConnection:
    def __init__(self, sock: socket.socket):
        self.socket = sock
        self.buffer = bytearray()

    def read_line(self, deadline: float, max_length: int) -> bytes:
        # 한 번의 수신에 여러 줄이 들어와도 다음 메시지를 보존한다.
        while True:
            end = self.buffer.find(b"\n")
            if end >= 0:
                if end > max_length:
                    raise ProtocolError("줄이 너무 깁니다")
                line = bytes(self.buffer[:end])
                del self.buffer[:end + 1]
                if any(c < 32 or c > 126 for c in line):
                    raise ProtocolError("출력할 수 없는 문자가 포함됐습니다")
                return line
            if len(self.buffer) > max_length:
                raise ProtocolError("줄이 너무 깁니다")
            self.socket.settimeout(remaining(deadline))
            try:
                data = self.socket.recv(4096)
            except socket.timeout as exc:
                raise TimeoutError("수신 제한시간을 초과했습니다") from exc
            if not data:
                raise EOFError("메시지 수신 중 연결이 종료됐습니다")
            self.buffer.extend(data)

    def send(self, data: bytes, deadline: float) -> None:
        self.socket.settimeout(remaining(deadline))
        try:
            self.socket.sendall(data)
        except socket.timeout as exc:
            raise TimeoutError("송신 제한시간을 초과했습니다") from exc

    def close(self) -> None:
        self.socket.close()
