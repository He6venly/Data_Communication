"""TCP 소켓에서 JSON 메시지를 줄바꿈 단위로 송수신하는 모듈."""

import json
import socket
import threading
from collections import deque


class ConnectionClosed(Exception):
    """상대가 연결을 정상적으로 종료한 경우."""


class InvalidMessage(Exception):
    """수신한 메시지의 형식이 잘못된 경우."""


class JsonLineConnection:
    """소켓 하나의 JSON 송수신을 관리한다."""

    def __init__(self, sock: socket.socket):
        if not isinstance(sock, socket.socket):
            raise TypeError("sock은 socket.socket 객체여야 합니다")

        self.sock = sock
        self.recv_buffer = bytearray()
        self.message_queue = deque()
        self.send_lock = threading.Lock()
        self.closed = False

    def send(self, message: dict):
        """dict를 UTF-8 JSON으로 바꾸고 줄바꿈을 붙여 전송한다."""
        if not isinstance(message, dict):
            raise TypeError("message는 dict 객체여야 합니다")

        data = json.dumps(
            message,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8") + b"\n"

        # 여러 스레드가 동시에 보내도 메시지가 섞이지 않게 한다.
        with self.send_lock:
            self.sock.sendall(data)

    def recv(self) -> dict:
        """다음 JSON 메시지 한 개를 받아 dict로 반환한다."""
        while not self.message_queue:
            if self.closed:
                raise ConnectionClosed("상대가 연결을 종료했습니다")

            data = self.sock.recv(4096)

            if not data:
                self.closed = True

                # 줄바꿈 없이 연결이 끝나면 미완성 메시지로 처리한다.
                if self.recv_buffer:
                    self.recv_buffer.clear()
                    raise InvalidMessage(
                        "줄바꿈을 받기 전에 연결이 종료되었습니다"
                    )

                raise ConnectionClosed("상대가 연결을 종료했습니다")

            self.recv_buffer.extend(data)
            self._split_messages()

        line = self.message_queue.popleft()
        return self._parse_message(line)

    def _split_messages(self):
        """수신 버퍼에서 줄바꿈까지 완성된 메시지를 분리한다."""
        while b"\n" in self.recv_buffer:
            index = self.recv_buffer.index(b"\n")
            line = bytes(self.recv_buffer[:index])
            del self.recv_buffer[: index + 1]
            self.message_queue.append(line)

    @staticmethod
    def _parse_message(line: bytes) -> dict:
        """한 줄을 UTF-8 JSON 객체로 변환한다."""
        if not line:
            raise InvalidMessage("빈 메시지는 허용되지 않습니다")

        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidMessage(
                f"잘못된 UTF-8 JSON 메시지입니다: {error}"
            ) from error

        if not isinstance(message, dict):
            raise InvalidMessage("JSON 메시지는 객체여야 합니다")

        return message


# 사용 예제
#
# Master에서 전송:
#   connection = JsonLineConnection(worker_socket)
#   connection.send({"type": "TASK", "key": "0A1F", "value": 42})
#
# Worker에서 수신:
#   connection = JsonLineConnection(master_socket)
#   try:
#       message = connection.recv()
#       print(message)
#   except ConnectionClosed:
#       print("Master와 연결이 종료되었습니다")
#   except InvalidMessage as error:
#       print(f"잘못된 메시지: {error}")
#
# 출력값:
#   {'type': 'TASK', 'key': '0A1F', 'value': 42}
#
# 주의: send()는 여러 스레드에서 호출할 수 있지만 recv()는 소켓마다
# 하나의 수신 스레드에서만 호출해야 한다.
