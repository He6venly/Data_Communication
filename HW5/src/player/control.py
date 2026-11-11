import select
import socket
import threading


class Lines:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()

    def pop(self):
        # 나뉘거나 합쳐서 온 데이터도 공백을 보존하면서 한 줄씩 꺼내줌
        end = self.buffer.find(b"\n")
        if end < 0:
            if len(self.buffer) > 4096:
                raise ValueError("line too long")
            return None
        if end > 4096:
            raise ValueError("line too long")
        line = bytes(self.buffer[:end])
        del self.buffer[:end + 1]
        if any(c < 32 or c > 126 for c in line):
            raise ValueError("ASCII lines with LF required")
        return line.decode("ascii")

    def receive(self):
        data = self.sock.recv(4096)
        if not data:
            raise EOFError("TCP connection closed before BYE")
        self.buffer.extend(data)


def send_line(sock, line):
    sock.sendall((line + "\n").encode("ascii"))


class State:
    def __init__(self, player, game, log):
        self.player, self.game, self.log = player, game, log
        self.lock = threading.RLock()
        self.mode = "IDLE"
        self.mid = None
        self.round = 0
        self.last = "-"
        self.pending = None
        self.generation = 0
        self.quit_mid = None
        self.error = None
        self.control = None
        self.thread = None
        self.closed = False
        self.wake_read, self.wake_write = socket.socketpair()
        self.stop_read, self.stop_write = socket.socketpair()

    def report(self, mode=None):
        if self.control is not None:
            mode = mode or self.mode
            suffix = f" {self.mid}" if mode in ("PLAYING", "CRASHED") else ""
            send_line(self.control, f"STATE P{self.player} {mode}{suffix}")

    def send(self, line, generation):
        # 장애 상태 확인이랑 실제 송신을 묶어서 crash 뒤 응답이 새지 않게 해줌
        with self.lock:
            if self.mode != "PLAYING" or generation != self.generation:
                return False
            send_line(self.game, line)
            self.last = line.split()[0]
            return True

    def _apply(self, command, fault=False):
        # 실제 장애를 적용할 때만 상태를 바꾸고 WARN이랑 ACK를 한 번 남겨줌
        self.generation += 1
        self.mode = "CRASHED" if command == "CRASH" else "QUIT"
        event = "FAULT" if fault else command
        self.log(event, "WARN", f"G{self.mid:02d} r={self.round} last={self.last} (now)")
        if command == "QUIT":
            self.quit_mid = self.mid
            send_line(self.game, f"QUIT {self.mid}")
        self.report()

    def match(self, mid):
        # 쉬는 중 받은 명령은 새 경기의 PLAYING을 보고한 다음 적용해줌
        with self.lock:
            self.mid, self.round, self.last = mid, 0, "-"
            self.mode = "PLAYING"
            self.report()
            if self.pending:
                command, self.pending = self.pending, None
                self._apply(command)
            return self.generation

    def command(self, command):
        # 복귀는 게임 수신 쪽을 깨워서 밀린 메시지부터 비우게 해줌
        with self.lock:
            if command not in ("CRASH", "QUIT", "RESTART"):
                raise ValueError("unknown control command")
            if self.mode in ("QUIT", "END"):
                return
            if command == "RESTART":
                if self.mode == "CRASHED":
                    self.mode = "RECOVERING"
                    self.wake_write.sendall(b"R")
                return
            if self.mode == "IDLE":
                if self.pending is None:
                    self.pending = command
                    self.log(command, "INFO", "received while IDLE -> apply at next MATCH")
            elif self.mode == "PLAYING":
                self._apply(command)

    def start_control(self, address):
        # WELCOME을 받은 뒤 제어 서버에 접속하고 수신 스레드 하나만 띄워줌
        self.control = socket.create_connection(address, timeout=10)
        self.control.settimeout(10)
        self.control.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        send_line(self.control, f"CTRL P{self.player}")
        with self.lock:
            self.report()
        self.thread = threading.Thread(target=self._control_loop, name=f"P{self.player}-control")
        self.thread.start()

    def _control_loop(self):
        # 제어 연결 하나만 읽고 종료 신호가 오면 대기 중이어도 바로 끝내줌
        lines = Lines(self.control)
        try:
            while True:
                ready, _, _ = select.select([self.control, self.stop_read], [], [])
                if self.stop_read in ready:
                    return
                lines.receive()
                while (line := lines.pop()) is not None:
                    self.command(line)
        except (OSError, EOFError, ValueError) as exc:
            with self.lock:
                if self.mode != "END":
                    self.error = exc
                    self.wake_write.sendall(b"E")

    def close(self):
        # 내가 만든 제어 스레드랑 소켓은 성공이나 실패에 상관없이 정리함
        if self.closed:
            return
        self.closed = True
        if self.thread is not None:
            self.stop_write.sendall(b"S")
            self.thread.join(timeout=12)
        if self.control is not None:
            self.control.close()
        for sock in (self.wake_read, self.wake_write, self.stop_read, self.stop_write):
            sock.close()
