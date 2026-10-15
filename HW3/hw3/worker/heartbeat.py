"""Heartbeat and REJOIN timers; neither timer advances while CRASHED."""

import time


def heartbeat_loop(worker):
    state = worker.state
    next_hb = 0.0
    hb_generation = None
    while True:
        with state.cv:
            while True:
                with state.state_lock, state.store_lock:
                    if state.mode == "STOPPED":
                        return
                    now = time.monotonic()
                    generation = state.crash_gen
                    hb_due = (state.mode == "RUNNING"
                              and (generation != hb_generation or now >= next_hb))
                    request_due = state.needs_request()
                    rejoin_due = (state.mode == "REJOINING" and state.rejoin_due is not None
                                  and now >= state.rejoin_due)
                    if hb_due or request_due or rejoin_due:
                        break
                    deadline = next_hb if state.mode == "RUNNING" else state.rejoin_due
                    # BOOTING/CRASHED and REJOINING awaiting a reply have no timer.
                    timeout = max(0.0, deadline - now) if deadline is not None else None
                # Check the predicate and enter wait under the same Queue/CV lock,
                # so START/RESTART/WELCOME/finish/BYE notifications cannot be lost.
                state.cv.wait(timeout)
        if hb_due:
            if worker.send_normal("HB", (worker.config.worker_id,), generation):
                worker.emit("HB", "INFO")
            hb_generation = generation
            next_hb = time.monotonic() + 1.0
        if rejoin_due:
            worker.send_rejoin_if_due()
        if request_due:
            worker.request_if_idle()
