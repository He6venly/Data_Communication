from time import monotonic


class DeadlineSocket:
    """공통 Conn의 각 송수신에 같은 요청 마감을 적용함."""

    def __init__(self, sock):
        self.sock = sock
        self.deadline = None

    def _apply(self):
        """데이터가 조금씩 들어와도 요청 시간이 늘어나지 않게 함."""
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline expired")
        self.sock.settimeout(remaining)

    def recv(self, size):
        self._apply()
        return self.sock.recv(size)

    def sendall(self, data):
        self._apply()
        self.sock.sendall(data)

    def shutdown(self, how):
        self.sock.shutdown(how)

    def close(self):
        self.sock.close()
