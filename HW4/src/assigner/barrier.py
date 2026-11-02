"""작업자 결과를 동기화하고 다음 라운드의 이웃 행을 준비한다."""

from dataclasses import dataclass
import math
import socket
import threading
import time
from collections.abc import Callable

from .partition import bands, initial_halos
from .storage import Canvas
from .transport import LineConnection, PhaseTimeout, ProtocolError


@dataclass(frozen=True)
class RoundMeasurement:
    round: int
    round_ms: float
    wait_ms: float
    slowest: int
    bytes_sent_received: int
    full: bool


def run_rounds(connections: list[LineConnection], canvas: Canvas, io_timeout: float,
               save_snapshot: Callable[[int, tuple[str, ...]], None],
               record_round: Callable[[RoundMeasurement], None],
               rounds: int = 3000) -> tuple[float, int]:
    if io_timeout <= 0 or not math.isfinite(io_timeout) or rounds <= 0:
        raise ValueError("제한시간과 라운드 수는 양수여야 합니다")
    ranges = bands(len(connections))
    lock = threading.Lock()
    done_cv = threading.Condition(lock)
    go_cv = threading.Condition(lock)
    state = {"round": 0, "arrived": 0, "error": None, "start": 0.0}
    seen = [-1] * len(connections)
    edges = [None] * len(connections)
    halos = [initial_halos(canvas, y0, y1) for y0, y1 in ranges]
    arrivals = [0.0] * len(connections)
    byte_counts = [0] * len(connections)
    frame = list(canvas.rows)

    def fail(exc: BaseException) -> None:
        # 최초 오류를 보존하고 대기 중인 모든 작업을 깨운다.
        with lock:
            if state["error"] is None:
                state["error"] = exc
            done_cv.notify_all()
            go_cv.notify_all()
        for connection in connections:
            try:
                connection.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def handle(k: int) -> None:
        connection = connections[k]
        y0, y1 = ranges[k]
        phase = "send"
        r = 0
        try:
            for r in range(rounds):
                with lock:
                    if state["error"] is not None:
                        return
                    if state["round"] != r:
                        raise ProtocolError("라운드 순서가 잘못됐습니다")
                    top, bottom = halos[k]
                request = f"ROUND {r}\n{top}\n{bottom}\n".encode("ascii")
                phase = "send"
                connection.send(request, time.monotonic() + io_timeout)
                phase = "recv"
                deadline = time.monotonic() + io_timeout
                header = connection.read_line(deadline, 80)
                if header != f"RESULT {r} {k}".encode("ascii"):
                    raise ProtocolError("결과 라운드 또는 작업자 번호가 잘못됐습니다")
                count = 2 + (y1 - y0 if (r + 1) % 10 == 0 else 0)
                lines = [connection.read_line(deadline, 160) for _ in range(count)]
                if any(len(line) != 160 for line in lines):
                    raise ProtocolError("결과 행의 길이가 잘못됐습니다")
                if count > 2 and (lines[0] != lines[2] or lines[1] != lines[-1]):
                    raise ProtocolError("결과의 가장자리 행이 일치하지 않습니다")
                with lock:
                    if state["error"] is not None:
                        return
                    if state["round"] != r or seen[k] == r:
                        raise ProtocolError("중복되거나 순서가 잘못된 결과입니다")
                    edges[k] = (lines[0].decode("ascii"), lines[1].decode("ascii"))
                    if count > 2:
                        frame[y0:y1] = [line.decode("ascii") for line in lines[2:]]
                    arrivals[k] = time.monotonic()
                    byte_counts[k] = len(request) + len(header) + 1 + sum(len(line) + 1 for line in lines)
                    seen[k] = r
                    state["arrived"] += 1
                    if state["arrived"] == len(connections):
                        done_cv.notify()
                    while state["error"] is None and state["round"] == r:
                        go_cv.wait()
                    if state["error"] is not None:
                        return
            phase = "send"
            connection.send(b"BYE\n", time.monotonic() + io_timeout)
        except BaseException as exc:
            if isinstance(exc, TimeoutError):
                exc = PhaseTimeout(phase, io_timeout)
            exc.k = k
            exc.round = r
            fail(exc)
        finally:
            connection.close()

    try:
        save_snapshot(0, tuple(frame))
    except BaseException as exc:
        fail(exc)
        exc.handlers_joined = 0
        exc.rounds_completed = 0
        raise
    threads = [threading.Thread(target=handle, args=(k,)) for k in range(len(connections))]
    started = []
    try:
        state["start"] = time.monotonic()
        first_start = state["start"]
        for thread in threads:
            thread.start()
            started.append(thread)
        for r in range(rounds):
            with lock:
                # 모든 결과를 받은 뒤에만 다음 라운드를 시작한다.
                while state["error"] is None and state["arrived"] < len(connections):
                    left = state["start"] + io_timeout - time.monotonic()
                    if left <= 0:
                        exc = PhaseTimeout("barrier", io_timeout)
                        exc.round = r
                        raise exc
                    done_cv.wait(left)
                if state["error"] is not None:
                    break
                end = time.monotonic()
                elapsed_ms = (end - first_start) * 1000
                slowest = max(range(len(connections)), key=lambda k: (arrivals[k], -k))
                measurement = RoundMeasurement(r, (end - state["start"]) * 1000,
                                               (max(arrivals) - min(arrivals)) * 1000,
                                               slowest, sum(byte_counts), (r + 1) % 10 == 0)
                halos[:] = [(edges[(k - 1) % len(edges)][1], edges[(k + 1) % len(edges)][0])
                            for k in range(len(edges))]
                snapshot = tuple(frame) if (r + 1) % 10 == 0 else None
                state["arrived"] = 0
                state["round"] = r + 1
                if r + 1 < rounds:
                    state["start"] = time.monotonic()
                go_cv.notify_all()
            if snapshot is not None:
                save_snapshot(r + 1, snapshot)
            record_round(measurement)
    except BaseException as exc:
        fail(exc)
    finally:
        for thread in started:
            try:
                thread.join()
            except KeyboardInterrupt as exc:
                fail(exc)
                thread.join()
    if state["error"] is not None:
        state["error"].handlers_joined = len(started)
        state["error"].rounds_completed = state["round"]
        raise state["error"]
    return elapsed_ms, len(started)
