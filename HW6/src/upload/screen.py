"""주기적으로 Peer 상태와 최근 이벤트를 그리는 터미널 화면."""

from __future__ import annotations

import sys
import threading
from typing import Callable, TextIO

from src.common.contracts import FileState, PeerView


class StatusScreen:
    def __init__(
        self, *, stopping: threading.Event, period_sec: float, stream: TextIO | None = None
    ) -> None:
        """화면 주기와 외부 상태 공급자만 보관하고 출력 스레드는 아직 시작하지 않는다."""
        self.stopping = stopping
        self.period_sec = max(0.1, float(period_sec))
        self.stream = stream if stream is not None else sys.stdout
        self._thread: threading.Thread | None = None
        self._snapshot: Callable[[], PeerView] | None = None
        self._recent: Callable[[int], tuple[str, ...]] | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()

    def start(
        self,
        snapshot: Callable[[], PeerView],
        recent: Callable[[int], tuple[str, ...]],
    ) -> None:
        """같은 화면 스레드가 중복 생성되지 않도록 공급 함수를 한 번 등록한다."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._done.clear()
            self._snapshot = snapshot
            self._recent = recent
            self._thread = threading.Thread(target=self._run, name="peer-status", daemon=True)
            self._thread.start()

    @staticmethod
    def _bar(bitmap: str, count: int = 40, *, stalled: bool = False) -> str:
        """bitmap을 40칸으로 줄여 완성·부분·빈·유실 구간을 문자로 그린다."""
        if not bitmap:
            return "." * count
        symbols: list[str] = []
        for col in range(count):
            lo = col * len(bitmap) // count
            hi = max(lo + 1, (col + 1) * len(bitmap) // count)
            segment = bitmap[lo:hi]
            if segment and all(bit == "1" for bit in segment):
                symbols.append("#")
            elif "1" in segment:
                symbols.append("+")
            else:
                symbols.append("x" if stalled else ".")
        return "".join(symbols)

    def _render(self) -> str:
        """PeerView 복사본과 최근 로그를 사람이 읽는 상태판 문자열로 만든다."""
        assert self._snapshot is not None and self._recent is not None
        view = self._snapshot()
        state = "ONLINE" if view.online else "OFFLINE"
        lines = [
            f"Mini-Torrent {view.peer_id}  t={view.elapsed_sec:6.1f}s  {state}  policy={view.policy}",
            f"UP {view.actual_up_kbps:7.1f}/{view.up_kbps} KB/s   DOWN {view.actual_down_kbps:7.1f}/{view.down_kbps} KB/s",
        ]
        for file in view.files:
            shown = "DOWN" if file.state == FileState.VERIFYING else file.state.value
            count = file.bitmap.count("1")
            pct = count * 100 / file.nchunks if file.nchunks else 0.0
            lines.append(
                f"{file.name:<16} [{self._bar(file.bitmap, stalled=file.state == FileState.STALLED)}] "
                f"{pct:5.1f}% {shown}"
            )
        lines.append("Recent events:")
        lines.extend(self._recent(5))
        return "\n".join(lines)

    def _run(self) -> None:
        """화면 스레드 하나가 주기적으로 상태판을 갱신한다."""
        while not self.stopping.is_set() and not self._done.is_set():
            try:
                rendered = self._render()
            except Exception as exc:
                rendered = f"상태 화면 오류: {exc}"
            with self._lock:
                self.stream.write("\x1b[H\x1b[2J" + rendered + "\n")
                self.stream.flush()
            self._done.wait(self.period_sec)

    def stop(self) -> None:
        """화면 갱신을 끝내고 남은 스레드가 없는지 확인한다."""
        thread = self._thread
        if thread is None:
            return
        self._done.set()
        if thread is not threading.current_thread():
            thread.join(5.0)
        if thread.is_alive():
            from src.common.contracts import ShutdownError
            raise ShutdownError("상태 화면 스레드가 종료되지 않음")
        self._thread = None\n