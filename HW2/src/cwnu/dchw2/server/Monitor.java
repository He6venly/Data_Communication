package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces.Logger;
import cwnu.dchw2.common.Interfaces.QueueView;
import cwnu.dchw2.common.Interfaces.RequestQueue;
import cwnu.dchw2.common.Interfaces.SeatView;
import cwnu.dchw2.common.Interfaces.Seats;
import cwnu.dchw2.common.Interfaces.ServerContext;
import cwnu.dchw2.common.Interfaces.Stoppable;
import cwnu.dchw2.common.Protocol;
import java.io.IOException;
import java.util.List;
import java.util.Objects;
import java.util.StringJoiner;

/** 좌석과 Queue 상태를 주기적으로 기록하고 단순 처리 정지를 감시한다. */
public final class Monitor implements Stoppable {
    private final ServerContext server;
    private final RequestQueue queue;
    private final Seats seats;
    private final Logger log;
    private volatile boolean stopRequested;
    private volatile Thread runningThread;
    private boolean started;

    public Monitor(ServerContext server, RequestQueue queue,
            Seats seats, Logger log) {
        this.server = Objects.requireNonNull(server, "server");
        this.queue = Objects.requireNonNull(queue, "queue");
        this.seats = Objects.requireNonNull(seats, "seats");
        this.log = Objects.requireNonNull(log, "log");
    }

    @Override
    public void run() {
        synchronized (this) {
            if (started) {
                throw new IllegalStateException("Monitor는 한 번만 실행할 수 있습니다.");
            }
            started = true;
            runningThread = Thread.currentThread();
        }
        long observedProgress = server.lastProgressNanos();
        boolean suspicionRecorded = false;
        try {
            while (!stopRequested) {
                Thread.sleep(Protocol.MONITOR_INTERVAL_MS);
                if (stopRequested) {
                    return;
                }

                QueueView queueView = queue.snapshot();
                List<SeatView> seatViews = seats.snapshot();
                int completed = server.completedCount();
                long progress = server.lastProgressNanos();
                long now = System.nanoTime();
                if (progress != observedProgress) {
                    observedProgress = progress;
                    suspicionRecorded = false;
                }

                log.write("POOL", "INFO", seatText(seatViews)
                        + " queueCurrent=" + queueView.currentSize
                        + " queueMax=" + queueView.maxSize
                        + " completed=" + completed);
                printSummary(seatViews, queueView, completed);

                long stalledNanos = progress == 0 ? 0 : now - progress;
                if (queueView.currentSize > 0 && progress != 0
                        && stalledNanos >= Protocol.STALL_THRESHOLD_MS * 1_000_000L
                        && !suspicionRecorded) {
                    server.recordDeadlockSuspicion();
                    suspicionRecorded = true;
                    log.write("DEADLOCK_SUSPECT", "WARN",
                            "queueCurrent=" + queueView.currentSize
                            + " completed=" + completed
                            + " stalledMillis=" + (stalledNanos / 1_000_000L));
                }
            }
        } catch (InterruptedException e) {
            if (!stopRequested) {
                server.reportFailure(e);
                Thread.currentThread().interrupt();
            }
        } catch (IOException | RuntimeException e) {
            server.reportFailure(e);
        } finally {
            runningThread = null;
        }
    }

    private static String seatText(List<SeatView> seatViews) {
        StringJoiner text = new StringJoiner(",", "seats=", "");
        for (SeatView seat : seatViews) {
            if (!seat.readable) {
                text.add(seat.seat + ":UNREADABLE");
            } else {
                text.add(seat.seat + ":owner=" + seat.ownerId
                        + ":waiting=" + seat.waitingCount);
            }
        }
        return text.toString();
    }

    private static void printSummary(List<SeatView> seatViews,
            QueueView queueView, int completed) {
        int reserved = 0;
        int waiting = 0;
        int unreadable = 0;
        for (SeatView seat : seatViews) {
            if (!seat.readable) {
                unreadable++;
            } else {
                reserved += seat.ownerId > 0 ? 1 : 0;
                waiting += seat.waitingCount;
            }
        }

        System.out.println("처리 요청: " + completed + "건");
        if (unreadable == 0) {
            System.out.println("예약 좌석: " + reserved + " / " + Protocol.SEAT_COUNT);
            System.out.println("대기 등록: " + waiting + "건");
        } else {
            System.out.println("예약 좌석: 확인된 " + reserved + " / " + Protocol.SEAT_COUNT
                    + " (일부 집계, 미조회 " + unreadable + "석)");
            System.out.println("대기 등록: 확인된 " + waiting + "건 (일부 집계)");
        }
        System.out.println("요청 Queue: 현재 " + queueView.currentSize
                + " / 최대 " + queueView.maxSize);
    }

    @Override
    public void stop() {
        stopRequested = true;
        Thread thread = runningThread;
        if (thread != null) {
            thread.interrupt();
        }
    }
}
