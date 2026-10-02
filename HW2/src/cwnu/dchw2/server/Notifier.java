package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces.Connection;
import cwnu.dchw2.common.Interfaces.Logger;
import cwnu.dchw2.common.Interfaces.Notifications;
import cwnu.dchw2.common.Interfaces.ServerContext;
import cwnu.dchw2.common.Interfaces.WaitNotice;
import cwnu.dchw2.common.Protocol;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.Objects;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

public final class Notifier implements Notifications {
    private final ArrayDeque<WaitNotice> notices = new ArrayDeque<>();
    private final ReentrantLock lock = new ReentrantLock();
    private final Condition available = lock.newCondition();
    private final ServerContext server;
    private final Logger log;
    private boolean finished;
    private volatile boolean aborted;

    public Notifier(ServerContext server, Logger log) {
        this.server = server;
        this.log = log;
    }

    @Override
    public void submit(WaitNotice notice) {
        Objects.requireNonNull(notice, "notice");
        lock.lock();
        try {
            if (finished) {
                throw new IllegalStateException("Notify Queue 입력이 종료되었습니다.");
            }
            notices.addLast(notice);
            available.signal();
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void finish() {
        lock.lock();
        try {
            finished = true;
            available.signalAll();
        } finally {
            lock.unlock();
        }
    }

    /** 실패 실행에서는 전송을 중단한다. 정상 finish는 잔여 통지를 유지한다. */
    public void abort() {
        lock.lock();
        try {
            aborted = true;
            finished = true;
            available.signalAll();
        } finally {
            lock.unlock();
        }
    }

    private WaitNotice take() throws InterruptedException {
        lock.lockInterruptibly();
        try {
            while (notices.isEmpty() && !finished) {
                available.await();
            }
            return aborted || notices.isEmpty() ? null : notices.removeFirst();
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void run() {
        try {
            for (WaitNotice notice; (notice = take()) != null;) {
                Connection connection = server.findClient(notice.clientId);
                if (connection == null) {
                    throw new IOException("통지 대상 Client가 미등록 상태입니다: " + notice.clientId);
                }
                connection.send(Protocol.encodeResponse(
                        Protocol.notification(notice.requestId, notice.seat)));
                long waitNanos = System.nanoTime() - notice.registeredNanos;
                server.recordNotify(waitNanos);
                log.write("NOTIFY", "SUCCESS", "clientId=" + notice.clientId
                        + " requestId=" + notice.requestId + " seats=" + notice.seat
                        + " result=NOTIFY waitNanos=" + waitNanos);
            }
        } catch (InterruptedException e) {
            if (!aborted) {
                server.reportFailure(e);
            }
            Thread.currentThread().interrupt();
        } catch (IOException | RuntimeException e) {
            server.reportFailure(e);
        }
    }
}
