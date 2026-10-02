package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces;
import cwnu.dchw2.common.Protocol;
import java.io.IOException;
import java.lang.reflect.InvocationTargetException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicReference;

/** Listener는 run을 호출한 스레드, 나머지는 고정 Worker 10 + Notifier 1 + Monitor 1이다. */
public final class Server implements Interfaces.ServerContext {
    private final Object stateLock = new Object();
    private final int requestsPerClient;
    private final int expectedResponses;
    private final Interfaces.Logger log;
    private final Interfaces.Seats seats;
    private final RequestQueue queue = new RequestQueue();
    private final Notifier notifier;
    private final Interfaces.Connection[] clients = new Interfaces.Connection[Protocol.CLIENT_COUNT];
    private final boolean[] connectionClosed = new boolean[Protocol.CLIENT_COUNT];
    private final int[] responses = new int[Protocol.CLIENT_COUNT];
    private final Worker[] workers = new Worker[Protocol.WORKER_COUNT];
    private final Thread[] workerThreads = new Thread[Protocol.WORKER_COUNT];
    private final AtomicReference<Throwable> failure = new AtomicReference<>();
    private volatile Interfaces.Stoppable listener;
    private volatile Interfaces.Stoppable monitor;
    private volatile Thread monitorThread;
    private volatile Thread notifierThread;
    private volatile boolean inputStopped;
    private volatile boolean monitorStopping;
    private boolean started;
    private volatile int completed;
    private volatile long lastProgress;
    private long firstConnection;
    private long lastResponse;
    private long notifyCount;
    private long totalWaitNanos;
    private long suspicions;

    public Server(int requestsPerClient, Interfaces.Logger log) {
        this(requestsPerClient, log, new SeatManager());
    }

    /** 조원 대역과 최종 검사 시점 검증을 위한 인터페이스 주입 경로다. */
    public Server(int requestsPerClient, Interfaces.Logger log, Interfaces.Seats seats) {
        if (requestsPerClient < 1 || requestsPerClient > Integer.MAX_VALUE / Protocol.CLIENT_COUNT) {
            throw new IllegalArgumentException("Client당 요청 수가 유효한 양수 범위를 벗어났습니다.");
        }
        this.requestsPerClient = requestsPerClient;
        expectedResponses = requestsPerClient * Protocol.CLIENT_COUNT;
        this.log = Objects.requireNonNull(log, "log");
        this.seats = Objects.requireNonNull(seats, "seats");
        notifier = new Notifier(this, log);
        for (int i = 0; i < workers.length; i++) {
            workers[i] = new Worker(queue, seats, notifier, this, log);
            workerThreads[i] = new Thread(workers[i], "Worker-" + (i + 1));
        }
        notifierThread = new Thread(notifier, "Notifier");
    }

    public Interfaces.RequestQueue queue() {
        return queue;
    }

    public Interfaces.Seats seats() {
        return seats;
    }

    public Throwable failure() {
        return failure.get();
    }

    /** 한 실행만 지원한다. 반환할 때 소켓·실행 스레드·Logger 정리를 완료한다. */
    public boolean run(Interfaces.Stoppable listener, Interfaces.Stoppable monitor) {
        Objects.requireNonNull(listener, "listener");
        Objects.requireNonNull(monitor, "monitor");
        synchronized (stateLock) {
            if (started) {
                throw new IllegalStateException("Server는 한 번만 실행할 수 있습니다.");
            }
            started = true;
            this.listener = listener;
            this.monitor = monitor;
            monitorThread = new Thread(() -> {
                try {
                    monitor.run();
                    if (!monitorStopping && failure.get() == null) {
                        reportFailure(new IllegalStateException("Monitor가 종료 요청 전에 반환했습니다."));
                    }
                } catch (RuntimeException e) {
                    reportFailure(e);
                }
            }, "Monitor");
        }
        try {
            log.write("INIT", "SUCCESS", "seats=" + Protocol.SEAT_COUNT
                    + " workers=" + Protocol.WORKER_COUNT + " expectedResponses=" + expectedResponses);
            if (failure.get() == null) {
                for (Thread thread : workerThreads) {
                    thread.start();
                }
                notifierThread.start();
                monitorThread.start();
                listener.run();
                if (failure.get() == null && completed != expectedResponses) {
                    reportFailure(new IOException("Listener가 모든 첫 응답 완료 전에 반환했습니다."));
                }
            }
        } catch (IOException | RuntimeException e) {
            reportFailure(e);
        } finally {
            shutdown();
        }
        return failure.get() == null;
    }

    @Override
    public void registerClient(int clientId, Interfaces.Connection connection) {
        checkClientId(clientId);
        Objects.requireNonNull(connection, "connection");
        synchronized (stateLock) {
            if (inputStopped || clients[clientId - 1] != null || connection.clientId() != 0) {
                throw new IllegalArgumentException("종료 중이거나 중복 등록된 연결입니다.");
            }
            for (Interfaces.Connection existing : clients) {
                if (existing == connection) {
                    throw new IllegalArgumentException("같은 연결을 다시 등록할 수 없습니다.");
                }
            }
            connection.bindClientId(clientId);
            clients[clientId - 1] = connection;
            if (firstConnection == 0) {
                firstConnection = System.nanoTime();
                lastProgress = firstConnection;
            }
        }
        try {
            log.write("CONNECT", "SUCCESS", "clientId=" + clientId);
        } catch (IOException | RuntimeException e) {
            reportFailure(e);
        }
    }

    @Override
    public Interfaces.Connection findClient(int clientId) {
        if (clientId < 1 || clientId > clients.length) {
            return null;
        }
        synchronized (stateLock) {
            return clients[clientId - 1];
        }
    }

    @Override
    public void recordFirstResponse(int clientId) {
        checkClientId(clientId);
        boolean allDone;
        synchronized (stateLock) {
            int index = clientId - 1;
            if (clients[index] == null || responses[index] >= requestsPerClient) {
                throw new IllegalStateException("미등록 Client 또는 첫 응답 목표 초과입니다: " + clientId);
            }
            responses[index]++;
            completed++;
            lastResponse = System.nanoTime();
            lastProgress = lastResponse;
            allDone = completed == expectedResponses;
        }
        // 등록된 Client마다 상한을 검사했으므로 합계 도달은 30명 모두의 도달을 뜻한다.
        if (allDone) {
            stopInput();
        }
    }

    @Override
    public void recordNotify(long waitNanos) {
        if (waitNanos < 0) {
            throw new IllegalArgumentException("대기시간은 음수가 될 수 없습니다.");
        }
        synchronized (stateLock) {
            notifyCount++;
            totalWaitNanos += waitNanos;
        }
    }

    @Override
    public void recordDeadlockSuspicion() {
        synchronized (stateLock) {
            suspicions++;
        }
    }

    @Override
    public int completedCount() {
        return completed;
    }

    @Override
    public long lastProgressNanos() {
        return lastProgress;
    }

    @Override
    public void reportFailure(Throwable cause) {
        Objects.requireNonNull(cause, "cause");
        if (monitorStopping && Thread.currentThread() == monitorThread
                && cause instanceof InterruptedException) {
            return; // stop 이후 정상 Monitor 대기 해제를 실패로 표시하지 않는다.
        }
        if (!failure.compareAndSet(null, cause)) {
            return;
        }
        stopInput();
        notifier.abort();
        for (int i = 0; i < workers.length; i++) {
            workers[i].abort();
            workerThreads[i].interrupt();
        }
        notifierThread.interrupt();
        closeConnections(); // 막힌 소켓 송신을 해제한다. join은 run 호출 스레드에서만 한다.
        stopMonitor();
    }

    private void stopInput() {
        inputStopped = true;
        queue.close();
        Interfaces.Stoppable current = listener;
        if (current != null) {
            try {
                current.stop();
            } catch (RuntimeException e) {
                reportFailure(e);
            }
        }
    }

    private void stopMonitor() {
        monitorStopping = true;
        Interfaces.Stoppable current = monitor;
        if (current != null) {
            try {
                current.stop();
            } catch (RuntimeException e) {
                reportFailure(e);
            }
        }
        Thread thread = monitorThread;
        if (thread != null) {
            thread.interrupt();
        }
    }

    private void shutdown() {
        boolean interrupted = Thread.interrupted();
        if (interrupted) {
            reportFailure(new InterruptedException("Server 호출 스레드가 중단되었습니다."));
        }
        stopInput();
        for (Thread thread : workerThreads) {
            interrupted |= join(thread);
        }
        notifier.finish(); // 마지막 Worker의 submit과 로그 기록까지 종료한 뒤에만 닫는다.
        interrupted |= join(notifierThread);
        if (failure.get() == null) {
            try {
                if (completed != expectedResponses) {
                    throw new IllegalStateException("첫 응답 수가 목표와 다릅니다.");
                }
                for (Interfaces.Connection connection : registeredConnections()) {
                    connection.send(Protocol.encodeResponse(Protocol.bye()));
                }
            } catch (IOException | RuntimeException e) {
                reportFailure(e);
            }
        }
        stopMonitor();
        interrupted |= join(monitorThread);
        try {
            writeFinalState(); // Worker와 Monitor 모두 종료한 뒤 좌석을 조회한다.
        } catch (IOException | RuntimeException e) {
            reportFailure(e);
        }
        closeConnections();
        try {
            Throwable problem = failure.get();
            log.write("TERMINATE", problem == null ? "SUCCESS" : "FAIL",
                    "completed=" + completed + " expected=" + expectedResponses
                    + " allThreadsJoined=true"
                    + (problem == null ? "" : " cause=" + problem));
        } catch (IOException | RuntimeException e) {
            reportFailure(e);
            System.err.println("TERMINATE 기록 실패: " + e);
        }
        try {
            log.close();
        } catch (IOException | RuntimeException e) {
            reportFailure(e);
            System.err.println("Logger 종료 실패: " + e);
        }
        if (interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    private boolean join(Thread thread) {
        boolean interrupted = false;
        if (thread != null) {
            while (thread.isAlive()) {
                try {
                    thread.join();
                } catch (InterruptedException e) {
                    interrupted = true;
                    reportFailure(e);
                }
            }
        }
        return interrupted;
    }

    private List<Interfaces.Connection> registeredConnections() {
        synchronized (stateLock) {
            List<Interfaces.Connection> copy = new ArrayList<>();
            for (Interfaces.Connection connection : clients) {
                if (connection != null) {
                    copy.add(connection);
                }
            }
            return copy;
        }
    }

    private void closeConnections() {
        List<Interfaces.Connection> toClose = new ArrayList<>();
        synchronized (stateLock) {
            for (int i = 0; i < clients.length; i++) {
                if (clients[i] != null && !connectionClosed[i]) {
                    connectionClosed[i] = true;
                    toClose.add(clients[i]);
                }
            }
        }
        for (Interfaces.Connection connection : toClose) {
            try {
                connection.close();
            } catch (IOException | RuntimeException e) {
                reportFailure(e);
            }
        }
    }

    private void writeFinalState() throws IOException {
        int reserved = 0;
        int unresolved = 0;
        for (Interfaces.SeatView seat : seats.snapshot()) {
            if (!seat.readable) {
                throw new IllegalStateException("Worker 종료 후 읽지 못한 좌석입니다: " + seat.seat);
            }
            reserved += seat.ownerId == 0 ? 0 : 1;
            unresolved += seat.waitingCount;
            log.write("POOL", "INFO", "final=true seat=" + seat.seat
                    + " ownerId=" + seat.ownerId + " waitingCount=" + seat.waitingCount);
        }
        Interfaces.SeatMetrics metrics = seats.metrics();
        Statistics stats = statistics();
        boolean valid = metrics.doubleBookings == 0
                && metrics.assignments - metrics.releases == reserved
                && metrics.waitlisted == stats.notifyCount + unresolved;
        log.write("DOUBLE_BOOKING_CHECK", valid ? "SUCCESS" : "FAIL",
                "serverBalance=" + (valid ? "PASS" : "FAIL")
                + " clientCrossCheck=UNVERIFIED doubleBookings=" + metrics.doubleBookings
                + " assignments=" + metrics.assignments + " releases=" + metrics.releases
                + " reserved=" + reserved + " waitlisted=" + metrics.waitlisted
                + " notifySent=" + stats.notifyCount + " unresolved=" + unresolved);
        log.write("TERMINATE", "INFO", "throughput=" + stats.throughput
                + " queueMax=" + queue.snapshot().maxSize + " contention=" + metrics.contention
                + " deadlockSuspicions=" + stats.deadlockSuspicions
                + " notifyAverageSeconds=" + stats.notifyAverageSeconds
                + " clientResponses=" + stats.clientResponses);
        if (!valid && failure.get() == null) {
            reportFailure(new IllegalStateException("서버 내부 최종 수지가 불일치합니다."));
        }
    }

    public Statistics statistics() {
        synchronized (stateLock) {
            List<Integer> counts = new ArrayList<>(responses.length);
            for (int count : responses) {
                counts.add(count);
            }
            long elapsed = firstConnection == 0 || lastResponse == 0 ? 0 : lastResponse - firstConnection;
            return new Statistics(completed, notifyCount, suspicions,
                    elapsed <= 0 ? 0 : completed * 1_000_000_000.0 / elapsed,
                    notifyCount == 0 ? 0 : totalWaitNanos / (notifyCount * 1_000_000_000.0),
                    List.copyOf(counts));
        }
    }

    public static final class Statistics {
        public final int completed;
        public final long notifyCount;
        public final long deadlockSuspicions;
        public final double throughput;
        public final double notifyAverageSeconds;
        public final List<Integer> clientResponses;

        private Statistics(int completed, long notifyCount, long deadlockSuspicions,
                double throughput, double notifyAverageSeconds, List<Integer> clientResponses) {
            this.completed = completed;
            this.notifyCount = notifyCount;
            this.deadlockSuspicions = deadlockSuspicions;
            this.throughput = throughput;
            this.notifyAverageSeconds = notifyAverageSeconds;
            this.clientResponses = clientResponses;
        }
    }

    private static void checkClientId(int clientId) {
        if (clientId < 1 || clientId > Protocol.CLIENT_COUNT) {
            throw new IllegalArgumentException("Client 번호는 1~30이어야 합니다.");
        }
    }

    /** 조원 클래스는 아직 없어도 핵심 소스가 컴파일되도록 진입점에서만 연결한다. */
    public static void main(String[] args) {
        Interfaces.Logger log = null;
        boolean runOwnsLog = false;
        try {
            if (args.length != 3 || args[0].isBlank()) {
                throw new IllegalArgumentException("사용법: Server <bindHost> <port> <Client당 요청 수>");
            }
            int port = Integer.parseInt(args[1]);
            int requests = Integer.parseInt(args[2]);
            if (port < 1 || port > 65535 || requests < 1
                    || requests > Integer.MAX_VALUE / Protocol.CLIENT_COUNT) {
                throw new IllegalArgumentException("포트 또는 요청 수가 유효 범위를 벗어났습니다.");
            }
            log = create(Interfaces.Logger.class, "cwnu.dchw2.common.Log",
                    new Class<?>[] {String.class, Path.class}, "SERVER", Path.of("logs", "Server.txt"));
            Server server = new Server(requests, log);
            Interfaces.Stoppable listener = create(Interfaces.Stoppable.class,
                    "cwnu.dchw2.server.Listener", new Class<?>[] {Interfaces.ServerContext.class,
                            Interfaces.RequestQueue.class, Interfaces.Logger.class, String.class, int.class},
                    server, server.queue(), log, args[0], port);
            Interfaces.Stoppable monitor = create(Interfaces.Stoppable.class,
                    "cwnu.dchw2.server.Monitor", new Class<?>[] {Interfaces.ServerContext.class,
                            Interfaces.RequestQueue.class, Interfaces.Seats.class, Interfaces.Logger.class},
                    server, server.queue(), server.seats(), log);
            runOwnsLog = true;
            if (!server.run(listener, monitor)) {
                throw new IllegalStateException("서버 실행 실패", server.failure());
            }
        } catch (Exception e) {
            if (!runOwnsLog && log != null) {
                try {
                    log.close();
                } catch (IOException closeError) {
                    e.addSuppressed(closeError);
                }
            }
            System.err.println("Server 실패: " + e);
            if (e.getCause() != null) {
                System.err.println("원인: " + e.getCause());
            }
            System.exit(1);
        }
    }

    private static <T> T create(Class<T> type, String name, Class<?>[] parameters,
            Object... arguments) throws ReflectiveOperationException {
        try {
            return type.cast(Class.forName(name).getConstructor(parameters).newInstance(arguments));
        } catch (InvocationTargetException e) {
            throw new ReflectiveOperationException(name + " 초기화 실패", e.getCause());
        }
    }
}
