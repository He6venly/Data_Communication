package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces.Result;
import cwnu.dchw2.common.Interfaces.SeatMetrics;
import cwnu.dchw2.common.Interfaces.SeatView;
import cwnu.dchw2.common.Interfaces.Seats;
import cwnu.dchw2.common.Interfaces.WaitNotice;
import cwnu.dchw2.common.Protocol;
import cwnu.dchw2.common.Protocol.Request;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.StringJoiner;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

/** 상태 판정만 수행한다. detail도 Lock 안에서 캡처하고 I/O는 호출자에게 맡긴다. */
public final class SeatManager implements Seats {
    private static final class Seat {
        final ReentrantLock lock = new ReentrantLock();
        final ArrayDeque<WaitEntry> waiting = new ArrayDeque<>();
        int owner;
        long sequence;
    }

    private static final class WaitEntry {
        final int clientId;
        final int requestId;
        final long registeredNanos;

        WaitEntry(Request request) {
            clientId = request.clientId;
            requestId = request.requestId;
            registeredNanos = System.nanoTime();
        }
    }

    private final Seat[] seats = new Seat[Protocol.SEAT_COUNT];
    private final AtomicLong assignments = new AtomicLong();
    private final AtomicLong releases = new AtomicLong();
    private final AtomicLong contention = new AtomicLong();
    private final AtomicLong doubleBookings = new AtomicLong();
    private final AtomicLong waitlisted = new AtomicLong();

    public SeatManager() {
        for (int i = 0; i < seats.length; i++) {
            seats[i] = new Seat();
        }
    }

    @Override
    public Result handle(Request request) {
        if (request.clientId < 1 || request.clientId > Protocol.CLIENT_COUNT
                || request.requestId < 1) {
            throw new IllegalArgumentException("Client 번호 또는 요청 번호가 잘못되었습니다.");
        }
        switch (request.command) {
            case Protocol.RESERVE_MULTI:
                if (request.seats.size() < Protocol.MIN_MULTI_SEATS
                        || request.seats.size() > Protocol.MAX_MULTI_SEATS
                        || new HashSet<>(request.seats).size() != request.seats.size()) {
                    return result(request, Protocol.FAIL, Protocol.BAD_MULTI, null, "locks=none");
                }
                break;
            case Protocol.RESERVE:
            case Protocol.CANCEL:
                if (request.seats.size() != 1) {
                    throw new IllegalArgumentException("단일 명령은 좌석 1개가 필요합니다.");
                }
                break;
            default:
                throw new IllegalArgumentException("예약·취소 명령이 아닙니다.");
        }
        for (int number : request.seats) {
            if (number < 1 || number > Protocol.SEAT_COUNT) {
                return result(request, Protocol.FAIL, Protocol.BAD_SEAT, null, "locks=none");
            }
        }
        if (request.command == Protocol.RESERVE_MULTI) {
            return reserveMulti(request);
        }
        int number = request.seats.get(0);
        Seat seat = seats[number - 1];
        acquire(seat);
        try {
            int before = seat.owner;
            int waitingBefore = seat.waiting.size();
            int status;
            String reason;
            WaitNotice notice = null;
            if (request.command == Protocol.RESERVE) {
                if (seat.owner == 0) {
                    assign(seat, request.clientId);
                    status = Protocol.SUCCESS;
                    reason = Protocol.OK;
                } else if (seat.owner == request.clientId) {
                    status = Protocol.FAIL;
                    reason = Protocol.ALREADY_OWNER;
                } else if (isWaiting(seat, request.clientId)) {
                    status = Protocol.FAIL;
                    reason = Protocol.ALREADY_WAITING;
                } else {
                    seat.waiting.addLast(new WaitEntry(request));
                    waitlisted.incrementAndGet();
                    status = Protocol.WAITLISTED;
                    reason = Protocol.TAKEN;
                }
            } else if (seat.owner != request.clientId) {
                status = Protocol.FAIL;
                reason = Protocol.NOT_OWNER;
            } else {
                seat.owner = 0;
                releases.incrementAndGet();
                WaitEntry head = seat.waiting.pollFirst();
                if (head != null) {
                    assign(seat, head.clientId);
                    notice = new WaitNotice(head.clientId, head.requestId,
                            number, head.registeredNanos);
                }
                status = Protocol.SUCCESS;
                reason = Protocol.OK;
            }
            String detail = transition(number, seat, before, waitingBefore);
            if (notice != null) {
                detail += " handoffClientId=" + notice.clientId
                        + " handoffRequestId=" + notice.requestId;
            }
            return result(request, status, reason, notice, detail);
        } finally {
            seat.lock.unlock();
        }
    }

    private Result reserveMulti(Request request) {
        List<Integer> order = new ArrayList<>(request.seats);
        Collections.sort(order);
        int acquired = 0;
        try {
            for (int number : order) {
                acquire(seats[number - 1]);
                acquired++;
            }
            boolean empty = true;
            for (int number : order) {
                if (seats[number - 1].owner != 0) {
                    empty = false;
                }
            }
            StringJoiner changes = new StringJoiner(";");
            for (int number : order) {
                Seat seat = seats[number - 1];
                int before = seat.owner;
                int waitingBefore = seat.waiting.size();
                if (empty) {
                    assign(seat, request.clientId);
                }
                changes.add(transition(number, seat, before, waitingBefore));
            }
            StringJoiner locks = new StringJoiner(",");
            for (int number : order) {
                locks.add(Integer.toString(number));
            }
            return result(request, empty ? Protocol.SUCCESS : Protocol.FAIL,
                    empty ? Protocol.OK : Protocol.TAKEN, null,
                    "transaction=" + request.clientId + ":" + request.requestId
                    + " lockOrder=" + locks + " transitions=" + changes);
        } finally {
            for (int i = acquired - 1; i >= 0; i--) {
                seats[order.get(i) - 1].lock.unlock();
            }
        }
    }

    private void acquire(Seat seat) {
        if (!seat.lock.tryLock()) {
            contention.incrementAndGet();
            seat.lock.lock();
        }
    }

    private void assign(Seat seat, int clientId) {
        if (seat.owner != 0) {
            doubleBookings.incrementAndGet();
            throw new IllegalStateException("이미 점유된 좌석을 배정하려 했습니다.");
        }
        seat.owner = clientId;
        assignments.incrementAndGet();
    }

    private static boolean isWaiting(Seat seat, int clientId) {
        for (WaitEntry entry : seat.waiting) {
            if (entry.clientId == clientId) {
                return true;
            }
        }
        return false;
    }

    private static String transition(int number, Seat seat, int before, int waitingBefore) {
        return "seat=" + number + ",sequence=" + (++seat.sequence)
                + ",ownerBefore=" + before + ",ownerAfter=" + seat.owner
                + ",waitingBefore=" + waitingBefore + ",waitingAfter=" + seat.waiting.size();
    }

    private static Result result(Request request, int status,
            String reason, WaitNotice notice, String detail) {
        return new Result(Protocol.response(request, status, reason), notice, detail);
    }

    @Override
    public List<SeatView> snapshot() {
        List<SeatView> copy = new ArrayList<>(seats.length);
        for (int i = 0; i < seats.length; i++) {
            Seat seat = seats[i];
            if (seat.lock.tryLock()) {
                try {
                    copy.add(new SeatView(i + 1, seat.owner, seat.waiting.size(), true));
                } finally {
                    seat.lock.unlock();
                }
            } else {
                copy.add(new SeatView(i + 1, -1, -1, false));
            }
        }
        return List.copyOf(copy);
    }

    @Override
    public SeatMetrics metrics() {
        return new SeatMetrics(assignments.get(), releases.get(), contention.get(),
                doubleBookings.get(), waitlisted.get());
    }
}
