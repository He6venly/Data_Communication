"""Heartbeat and REJOIN timers; neither timer advances while CRASHED."""

import time


def heartbeat_loop(worker):
    next_hb = time.monotonic()
    while not worker.state.stop_event.is_set():
        with worker.state.locked():
            mode = worker.state.mode
            generation = worker.state.crash_gen
        now = time.monotonic()
        if mode == "RUNNING" and now >= next_hb:
            if worker.send_normal("HB", (worker.config.worker_id,), generation):
                worker.emit("HB", "INFO")
            next_hb = time.monotonic() + 1.0
        elif mode != "RUNNING":
            next_hb = now
        worker.send_rejoin_if_due()
        worker.request_if_idle()
        worker.state.stop_event.wait(0.05)
