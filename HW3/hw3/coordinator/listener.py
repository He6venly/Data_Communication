# Worker 연결과 메시지 수신을 처리한다.

from dataclasses import dataclass, field
import selectors
import socket
import threading
import time

from hw3.common.protocol import parse, ProtocolError
from hw3.common.transport import LineBuffer
from hw3.common.settings import POOL_LOG_INTERVAL_SECONDS


@dataclass(eq=False)
class Channel:
    sock: object
    worker_id: int | None = None
    send_lock: object = field(default_factory=threading.RLock)
    buffer: object = field(default_factory=LineBuffer)


def listener_loop(app):
    next_pool = time.monotonic() + POOL_LOG_INTERVAL_SECONDS
    with selectors.DefaultSelector() as selector:
        selector.register(app.server, selectors.EVENT_READ, None)
        try:
            while not app.stop_event.is_set():
                for key, _ in selector.select(0.1):
                    if key.data is None:
                        try:
                            sock, address = app.server.accept()
                        except BlockingIOError:
                            continue
                        sock.settimeout(1.0)
                        channel = Channel(sock)
                        selector.register(sock, selectors.EVENT_READ, channel)
                        app.emit("CONNECT", role="worker", address=list(address))
                        continue
                    channel = key.data
                    try:
                        data = channel.sock.recv(65536)
                        if not data:
                            selector.unregister(channel.sock)
                            if channel.worker_id is not None and not app.finishing.is_set():
                                app.fail(ConnectionError(f"Worker {channel.worker_id} EOF; not a virtual crash"))
                            channel.sock.close()
                            continue
                        for line in channel.buffer.feed(data):
                            try:
                                message = parse(line)
                            except ProtocolError as error:
                                app.emit("PROTOCOL", "WARN", error=str(error))
                                continue
                            if app.finishing.is_set():
                                continue
                            if message.kind == "HB":
                                worker_id = app.sender(channel, message)
                                if worker_id is not None:
                                    app.publish(app.tables.heartbeat(worker_id))
                            else:
                                app.requests.put((channel, message))
                    except socket.timeout:
                        continue
                    except (OSError, ValueError) as error:
                        if not app.finishing.is_set():
                            app.fail(error)
                now = time.monotonic()
                if now >= next_pool and app.tables.started_at is not None and not app.finishing.is_set():
                    app.emit("POOL", queue=app.requests.qsize(), **app.tables.snapshot())
                    next_pool = now + POOL_LOG_INTERVAL_SECONDS
        finally:
            for key in list(selector.get_map().values()):
                if key.data is not None:
                    key.fileobj.close()
