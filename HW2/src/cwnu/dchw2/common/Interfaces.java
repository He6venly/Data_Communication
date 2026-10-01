package cwnu.dchw2.common;

import java.io.IOException;
import java.util.List;

/** 팀장 제공 파트 간 계약. 각 담당은 자기 클래스로 interface를 구현한다. */
public final class Interfaces {
    private Interfaces() {}

    public interface Connection extends AutoCloseable {
        /** 등록 전에는 0이다. */
        int clientId();

        /** Server의 등록 과정에서 한 번만 호출한다. */
        void bindClientId(int clientId);

        /** 줄바꿈 없는 line을 받고 LF를 붙인다. 송신 Lock 안에서 전체 전송 후 반환한다. */
        void send(String line) throws IOException;

        @Override
        void close() throws IOException;
    }

    public interface RequestQueue {
        /** 가득 차면 CV 대기. close 후 적재는 IllegalStateException이다. */
        void put(Task task) throws InterruptedException;

        /** 빈 Queue는 CV 대기. close되고 잔여 작업도 없으면 null이다. */
        Task take() throws InterruptedException;

        /** 잔여 작업은 유지하고 추가 적재를 중단한다. 모든 CV 대기자를 깨운다. */
        void close();

        QueueView snapshot();
    }

    public interface Seats {
        /** 소켓·파일 I/O 없이 판정한다. 모든 좌석 Lock을 해제하고 반환한다. */
        Result handle(Protocol.Request request);

        /** 좌석별 tryLock으로 복사한다. 읽지 못한 좌석은 readable=false로 반환한다. */
        List<SeatView> snapshot();

        SeatMetrics metrics();
    }

    public interface Notifications extends Runnable {
        /** Worker가 좌석 Lock 해제 후 호출한다. finish 후 추가는 IllegalStateException이다. */
        void submit(WaitNotice notice);

        /** 정상 실행에서는 Worker join 후 호출한다. 잔여 통지를 보내고 run이 종료한다. */
        void finish();
    }

    public interface ServerContext {
        /** 번호·중복 검사, bindClientId, 연결 등록. 규약 오류는 IllegalArgumentException이다. */
        void registerClient(int clientId, Connection connection);

        /** 미등록 번호는 null이다. */
        Connection findClient(int clientId);

        /** RESP 전체 송신 성공 후 한 번 호출한다. NOTIFY는 제외한다. */
        void recordFirstResponse(int clientId);

        /** NOTIFY 송신 성공 후 호출한다. 대기시간은 Server의 nanoTime 차이다. */
        void recordNotify(long waitNanos);

        /** Monitor가 정지 구간당 한 번 호출한다. 과제용 단순 정지 감시 횟수를 누적한다. */
        void recordDeadlockSuspicion();

        int completedCount();

        /** 첫 연결 시 초기화하고 첫 응답 송신 성공 때 갱신하는 nanoTime 값이다. */
        long lastProgressNanos();

        /** 실패 설정·대기 해제만 한다. 호출한 스레드 안에서 전체 join을 하지 않는다. */
        void reportFailure(Throwable cause);
    }

    public interface Logger extends AutoCloseable {
        /** UTC, 노드 이름, 한 줄 기록 직렬화. message 내부 줄바꿈은 공백으로 바꾼다. */
        void write(String event, String status, String message) throws IOException;

        @Override
        void close() throws IOException;
    }

    /** Listener·Monitor 공통 종료 계약. Listener는 등록된 연결을 닫지 않는다. */
    public interface Stoppable extends Runnable {
        void stop();
    }

    public static final class Task {
        public final Protocol.Request request;
        public final Connection connection;

        public Task(Protocol.Request request, Connection connection) {
            this.request = request;
            this.connection = connection;
        }
    }

    public static final class QueueView {
        public final int currentSize;
        public final int maxSize;

        public QueueView(int currentSize, int maxSize) {
            this.currentSize = currentSize;
            this.maxSize = maxSize;
        }
    }

    public static final class WaitNotice {
        public final int clientId;
        public final int requestId;
        public final int seat;
        public final long registeredNanos;

        public WaitNotice(int clientId, int requestId, int seat, long registeredNanos) {
            this.clientId = clientId;
            this.requestId = requestId;
            this.seat = seat;
            this.registeredNanos = registeredNanos;
        }
    }

    public static final class Result {
        public final Protocol.Response response;
        public final WaitNotice notice;
        public final String detail;

        /** notice는 대기자 인계 때만 존재하고 나머지는 null이다. detail은 로그 설명이다. */
        public Result(Protocol.Response response, WaitNotice notice, String detail) {
            this.response = response;
            this.notice = notice;
            this.detail = detail;
        }
    }

    public static final class SeatView {
        public final int seat;
        public final int ownerId;
        public final int waitingCount;
        public final boolean readable;

        /** EMPTY owner=0. 못 읽었으면 readable=false, ownerId/waitingCount=-1이다. */
        public SeatView(int seat, int ownerId, int waitingCount, boolean readable) {
            this.seat = seat;
            this.ownerId = ownerId;
            this.waitingCount = waitingCount;
            this.readable = readable;
        }
    }

    public static final class SeatMetrics {
        public final long assignments;
        public final long releases;
        public final long contention;
        public final long doubleBookings;
        public final long waitlisted;

        public SeatMetrics(long assignments, long releases, long contention,
                           long doubleBookings, long waitlisted) {
            this.assignments = assignments;
            this.releases = releases;
            this.contention = contention;
            this.doubleBookings = doubleBookings;
            this.waitlisted = waitlisted;
        }
    }
}
