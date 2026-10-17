# Task의 step을 계산하고 CKPT·RESULT를 전송한다.

from .primes import count_step


def compute_loop(worker):
    state = worker.state
    while not state.stop_event.is_set():
        worker.request_if_idle()
        work = state.take_work()
        if work is None:
            return
        assignment = work.assignment
        if assignment.from_worker is not None:
            worker.emit("TAKEOVER", "INFO", task=assignment.task, epoch=assignment.epoch,
                        from_worker=assignment.from_worker, ckpt_epoch=work.ckpt_epoch,
                        resume_step=work.resume_step, partial=work.partial)
        partial = work.partial
        for step in range(work.resume_step, 11):
            if not state.valid(work):
                break
            count = count_step(assignment.task, step)
            if not state.delay(work, worker.config.step_delay_ms / 1000):
                break
            partial += count
            if step < 10:
                worker.send_checkpoint(work, step, partial)
            elif worker.send_normal("RESULT", (assignment.task, assignment.epoch, partial),
                                    work.generation, assignment=assignment):
                worker.emit("RESULT", "SUCCESS", task=assignment.task, epoch=assignment.epoch,
                            result=partial)
        state.finish(work)
