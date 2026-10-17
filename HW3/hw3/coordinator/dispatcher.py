# Dispatcher 6개가 대기 요청을 처리한다.

STOP = object()


def dispatcher_loop(app):
    while True:
        item = app.requests.get()
        if item is STOP:
            return
        if app.finishing.is_set():
            continue
        channel, message = item
        kind, fields = message.kind, message.fields
        if kind == "HELLO":
            app.publish(app.tables.hello(channel, int(fields[0]), fields[1], int(fields[2])))
            continue
        worker_id = app.sender(channel, message)
        if worker_id is None:
            continue
        with channel.send_lock:
            reply = None
            if kind == "RING_OK":
                events = app.tables.ring_ok(worker_id)
            elif kind == "REQ":
                reply, events = app.tables.request(worker_id)
            elif kind == "RESULT":
                reply, events = app.tables.result(worker_id, *map(int, fields))
            elif kind == "REJOIN":
                reply, events = app.tables.rejoin(worker_id)
            else:
                events = [app.tables.event("PROTOCOL", "WARN", worker=worker_id,
                                           message=f"unexpected {kind}")]
            app.publish(events)
            if reply is not None:
                app.send(channel, *reply)
