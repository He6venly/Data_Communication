"""The single failure detector starts only after START has been sent."""

from hw3.common.settings import FAILURE_DETECTOR_INTERVAL_SECONDS


def detector_loop(app):
    app.started.wait()
    while not app.detector_stop.wait(FAILURE_DETECTOR_INTERVAL_SECONDS):
        events, actions = app.tables.detect()
        app.publish(events)
        for worker_id, kind, fields in actions:
            app.send(app.tables.workers[worker_id].channel, kind, fields)
