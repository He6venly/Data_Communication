import socket
from threading import Lock
from time import monotonic

from src.common.transport import Conn


class ProtocolError(ValueError):
    """서버 응답이 약속된 형식과 다를 때 사용함."""


class TrackerLink:
    """요청 한 개가 후속 줄까지 다 읽도록 연결을 직렬화함."""

    def __init__(self, address, peer_id, file_count, peer_count):
        self.address, self.peer_id = address, peer_id
        self.limits = {"FILES": file_count, "PEERS": peer_count}
        self.conn = None
        self.max_timeout = 5.0
        self.lock = Lock()

    def close(self):
        """대기 중인 수신을 깨울 수 있도록 요청 Lock 없이 연결을 닫음."""
        conn = self.conn
        self.conn = None
        if conn is not None:
            conn.close()

    def request(self, command, timeout=5.0):
        """연결이 없으면 HELLO부터 하고 응답이 끊기면 연결을 폐기함."""
        with self.lock:
            timeout = min(timeout, self.max_timeout)
            deadline = monotonic()+timeout

            def line(conn):
                """후속 줄도 같은 응답 마감 안에서 읽음."""
                remaining = deadline-monotonic()
                if remaining <= 0:
                    raise TimeoutError("Tracker response deadline")
                conn.sock.settimeout(remaining)
                return conn.read_line()

            try:
                conn = self.conn
                if conn is None:
                    conn = Conn(socket.create_connection(self.address, timeout=timeout))
                    self.conn = conn
                    conn.send_line(f"HELLO {self.peer_id}")
                    if line(conn) != "OK":
                        raise ProtocolError("HELLO rejected")
                remaining = deadline-monotonic()
                if remaining <= 0:
                    raise TimeoutError("Tracker request deadline")
                conn.sock.settimeout(remaining)
                conn.send_line(command)
                head = line(conn)
                parts = head.split()
                if parts and parts[0] in self.limits:
                    if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
                        raise ProtocolError("invalid row count")
                    count = int(parts[1])
                    if count > self.limits[parts[0]]:
                        raise ProtocolError("response has too many rows")
                    return head, tuple(line(conn) for _ in range(count))
                return head, ()
            except (OSError, ValueError):
                self.close()
                self.conn = None
                raise
