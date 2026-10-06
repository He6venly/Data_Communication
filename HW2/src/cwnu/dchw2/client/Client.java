package cwnu.dchw2.client;

import cwnu.dchw2.common.Interfaces.Logger;
import cwnu.dchw2.common.Protocol;
import cwnu.dchw2.common.Protocol.Request;
import cwnu.dchw2.common.Protocol.Response;
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Random;
import java.util.Set;
import java.util.StringJoiner;

/** run은 수신을 담당하고 별도 스레드 하나가 송신한다. Logger는 호출자가 닫는다. */
public final class Client implements Runnable {
    private static final class Pending {
        final Request request;
        long sentNanos;
        boolean notified;

        Pending(Request request, long sentNanos) {
            this.request = request;
            this.sentNanos = sentNanos;
        }
    }

    private final Object stateLock = new Object();
    private final int clientId;
    private final String host;
    private final int port;
    private final int requestsPerClient;
    private final Logger log;
    private final Random random = new Random();
    private final Set<Integer> held = new HashSet<>();
    private final Set<Integer> busySeats = new HashSet<>();
    private final Map<Integer, Pending> pending = new LinkedHashMap<>();
    private final Map<Integer, Request> waiting = new LinkedHashMap<>();
    private volatile Socket socket;
    private volatile Thread sender;
    private volatile boolean stopping;
    private volatile boolean byeReceived;
    private volatile Throwable failure;
    private boolean started;
    private int nextRequestId = 1;
    private int sent;
    private int firstResponses;
    private int successes;
    private int failures;
    private int waitlisted;
    private int notifications;
    private long totalResponseNanos;
    private long selectedSeats;
    private long popularSeats;
    private int reserveRequests;
    private int multiRequests;
    private int cancelRequests;

    public Client(int clientId, String host, int port, int requestsPerClient, Logger log) {
        if (clientId < 1 || clientId > Protocol.CLIENT_COUNT
                || host == null || host.isBlank() || port < 1 || port > 65535
                || requestsPerClient < 1
                || requestsPerClient > Integer.MAX_VALUE / Protocol.CLIENT_COUNT) {
            throw new IllegalArgumentException("Client ID·주소·포트·요청 수가 잘못되었습니다.");
        }
        this.clientId = clientId;
        this.host = host;
        this.port = port;
        this.requestsPerClient = requestsPerClient;
        this.log = Objects.requireNonNull(log, "log");
    }

    @Override
    public void run() {
        synchronized (stateLock) {
            if (started) {
                throw new IllegalStateException("Client는 한 번만 실행할 수 있습니다.");
            }
            started = true;
        }
        try {
            socket = new Socket();
            if (!stopping) {
                socket.connect(new InetSocketAddress(host, port), 10_000);
                socket.setTcpNoDelay(true);
                BufferedWriter output = new BufferedWriter(new OutputStreamWriter(
                        socket.getOutputStream(), StandardCharsets.UTF_8));
                BufferedReader input = new BufferedReader(new InputStreamReader(
                        socket.getInputStream(), StandardCharsets.UTF_8));
                log.write("CONNECT", "SUCCESS", "clientId=" + clientId
                        + " serverHost=" + host + " port=" + port);
                // HELLO를 보낸 뒤 송신 담당을 시작하므로 첫 메시지는 항상 HELLO다.
                sendLine(output, Protocol.encodeHello(clientId));
                sender = new Thread(() -> sendRequests(output), "Client-" + clientId + "-send");
                sender.start();
                while (!stopping) {
                    String line = input.readLine();
                    if (line == null) {
                        throw new IOException("BYE 전에 연결이 종료되었습니다.");
                    }
                    handleResponse(Protocol.decodeResponse(line));
                }
            }
        } catch (IOException | RuntimeException e) {
            fail(e);
        } finally {
            stopTransport();
            joinSender();
            try {
                writeFinalState();
            } catch (IOException | RuntimeException e) {
                fail(e);
                System.err.println("CLIENT" + clientId + " 최종 로그 실패: " + e);
            }
        }
    }

    private void sendRequests(BufferedWriter output) {
        try {
            for (int i = 0; i < requestsPerClient && !stopping; i++) {
                if (i > 0) {
                    Thread.sleep(Protocol.MIN_REQUEST_INTERVAL_MS + random.nextInt(
                            Protocol.MAX_REQUEST_INTERVAL_MS - Protocol.MIN_REQUEST_INTERVAL_MS + 1));
                }
                Request request = prepareRequest();
                if (request == null) {
                    return;
                }
                log.write(Protocol.commandName(request.command), "INFO", fields(request)
                        + " result=REQUEST");
                synchronized (stateLock) {
                    pending.get(request.requestId).sentNanos = System.nanoTime();
                }
                sendLine(output, Protocol.encodeRequest(request));
                synchronized (stateLock) {
                    sent++;
                    selectedSeats += request.seats.size();
                    for (int seat : request.seats) {
                        if (seat <= 10) {
                            popularSeats++;
                        }
                    }
                    switch (request.command) {
                        case Protocol.RESERVE: reserveRequests++; break;
                        case Protocol.RESERVE_MULTI: multiRequests++; break;
                        case Protocol.CANCEL: cancelRequests++; break;
                        default: throw new IllegalStateException("알 수 없는 요청입니다.");
                    }
                }
            }
            // 송신 완료 후에도 소켓을 유지한다. 마지막 RESP·NOTIFY·BYE는 수신 담당이 읽는다.
        } catch (InterruptedException e) {
            if (!stopping) {
                fail(e);
            }
            Thread.currentThread().interrupt();
        } catch (IOException | RuntimeException e) {
            fail(e);
        }
    }

    /** 짧은 상태 Lock 안에서 선택과 pending 등록을 함께 한다. I/O는 여기서 수행하지 않는다. */
    Request prepareRequest() throws InterruptedException {
        synchronized (stateLock) {
            // 전 좌석이 첫 응답 대기 중일 때만 대기한다. waitlist 자체는 송신을 막지 않는다.
            while (busySeats.size() == Protocol.SEAT_COUNT && !stopping) {
                stateLock.wait();
            }
            if (stopping) {
                return null;
            }
            List<Integer> available = new ArrayList<>();
            List<Integer> cancellable = new ArrayList<>();
            for (int seat = 1; seat <= Protocol.SEAT_COUNT; seat++) {
                if (!busySeats.contains(seat)) {
                    available.add(seat);
                    if (held.contains(seat)) {
                        cancellable.add(seat);
                    }
                }
            }
            int draw = random.nextInt(100);
            int command = held.isEmpty()
                    ? (draw < 60 ? Protocol.RESERVE : Protocol.RESERVE_MULTI)
                    : (draw < 30 ? Protocol.RESERVE
                            : draw < 50 ? Protocol.RESERVE_MULTI : Protocol.CANCEL);
            if (command == Protocol.CANCEL && cancellable.isEmpty()) {
                command = random.nextInt(100) < 60 ? Protocol.RESERVE : Protocol.RESERVE_MULTI;
            }
            List<Integer> seats = new ArrayList<>();
            if (command == Protocol.CANCEL) {
                seats.add(cancellable.get(random.nextInt(cancellable.size())));
            } else {
                if (command == Protocol.RESERVE_MULTI && available.size() < Protocol.MIN_MULTI_SEATS) {
                    command = Protocol.RESERVE;
                }
                int count = command == Protocol.RESERVE ? 1 : Math.min(available.size(),
                        Protocol.MIN_MULTI_SEATS + random.nextInt(
                                Protocol.MAX_MULTI_SEATS - Protocol.MIN_MULTI_SEATS + 1));
                for (int i = 0; i < count; i++) {
                    int seat = chooseSeat(available);
                    seats.add(seat);
                    available.remove(Integer.valueOf(seat));
                }
            }
            Request request = new Request(clientId, nextRequestId++, command, seats);
            pending.put(request.requestId, new Pending(request, System.nanoTime()));
            busySeats.addAll(request.seats);
            return request;
        }
    }

    private int chooseSeat(List<Integer> available) {
        List<Integer> popular = new ArrayList<>();
        List<Integer> other = new ArrayList<>();
        for (int seat : available) {
            (seat <= 10 ? popular : other).add(seat);
        }
        List<Integer> candidates = random.nextInt(100) < 80 ? popular : other;
        if (candidates.isEmpty()) {
            candidates = available;
        }
        return candidates.get(random.nextInt(candidates.size()));
    }

    /** 예제 RESP·NOTIFY를 실제 수신과 같은 경로로 검증할 수 있게 분리했다. */
    void handleResponse(Response response) throws IOException {
        long receivedNanos = System.nanoTime();
        Request request;
        long elapsed = 0;
        synchronized (stateLock) {
            switch (response.type) {
                case Protocol.RESP:
                    Pending entry = pending.get(response.requestId);
                    if (entry == null || !entry.request.seats.equals(response.seats)
                            || (entry.notified && response.status != Protocol.WAITLISTED)
                            || (response.status == Protocol.WAITLISTED
                                    && entry.request.command != Protocol.RESERVE)) {
                        throw new IOException("요청과 맞지 않거나 중복된 첫 응답입니다: " + response.requestId);
                    }
                    request = entry.request;
                    switch (response.status) {
                        case Protocol.SUCCESS:
                            if (request.command == Protocol.CANCEL) {
                                held.removeAll(request.seats);
                            } else {
                                held.addAll(request.seats);
                            }
                            successes++;
                            break;
                        case Protocol.FAIL:
                            failures++; // 기존 보유·원 대기 요청은 그대로 둔다.
                            break;
                        case Protocol.WAITLISTED:
                            waitlisted++;
                            if (!entry.notified) {
                                waiting.put(request.requestId, request);
                            }
                            break;
                        default: throw new IOException("알 수 없는 응답 결과입니다.");
                    }
                    pending.remove(response.requestId);
                    busySeats.removeAll(request.seats);
                    firstResponses++;
                    elapsed = receivedNanos - entry.sentNanos;
                    totalResponseNanos += elapsed;
                    stateLock.notifyAll();
                    break;
                case Protocol.NOTIFY:
                    request = waiting.get(response.requestId);
                    Pending early = pending.get(response.requestId);
                    if (request == null && early != null && !early.notified
                            && early.request.command == Protocol.RESERVE) {
                        request = early.request;
                    }
                    if (request == null || !request.seats.equals(response.seats)) {
                        throw new IOException("원 대기 요청과 맞지 않거나 중복된 NOTIFY입니다: "
                                + response.requestId);
                    }
                    waiting.remove(response.requestId);
                    if (early != null) {
                        early.notified = true; // busy는 WAITLISTED가 올 때까지 유지한다.
                    }
                    held.addAll(response.seats);
                    notifications++;
                    break;
                case Protocol.BYE:
                    byeReceived = true;
                    stopping = true;
                    stateLock.notifyAll();
                    return;
                default: throw new IOException("알 수 없는 서버 메시지입니다.");
            }
        }
        if (response.type == Protocol.NOTIFY) {
            log.write("NOTIFY", "SUCCESS", fields(request) + " result=NOTIFY");
        } else {
            String result = Protocol.statusName(response.status);
            log.write(response.status == Protocol.WAITLISTED
                            ? "WAITLIST" : Protocol.commandName(request.command),
                    response.status == Protocol.WAITLISTED ? "WARN" : result,
                    fields(request) + " result=" + result + " reason=" + response.reason
                            + " responseNanos=" + elapsed);
        }
    }

    public Throwable failure() {
        return failure;
    }

    /** 다른 Client의 실패나 main interrupt 때 소켓 read/write와 상태 대기를 함께 해제한다. */
    public void abort(Throwable cause) {
        fail(Objects.requireNonNull(cause, "cause"));
    }

    private void fail(Throwable cause) {
        synchronized (stateLock) {
            if (failure == null) {
                failure = cause;
            }
        }
        stopTransport();
    }

    private void stopTransport() {
        synchronized (stateLock) {
            stopping = true;
            stateLock.notifyAll();
        }
        Socket current = socket;
        if (current != null) {
            try {
                current.close(); // 송신 완료를 기다리지 않고 막힌 read/write를 해제한다.
            } catch (IOException e) {
                synchronized (stateLock) {
                    if (failure == null) {
                        failure = e;
                    } else {
                        failure.addSuppressed(e);
                    }
                }
            }
        }
        Thread currentSender = sender;
        if (currentSender != null && currentSender != Thread.currentThread()) {
            currentSender.interrupt();
        }
    }

    private void joinSender() {
        boolean interrupted = false;
        Thread current = sender;
        if (current != null) {
            while (current.isAlive()) {
                try {
                    current.join();
                } catch (InterruptedException e) {
                    interrupted = true;
                    fail(e);
                }
            }
        }
        if (interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    private void writeFinalState() throws IOException {
        Snapshot state = snapshot();
        if (failure == null && (!byeReceived || state.sent != requestsPerClient
                || state.firstResponses != requestsPerClient || state.pendingCount != 0
                || state.waitlisted != state.notifications + state.waitingRequests.size())) {
            fail(new IOException("BYE 또는 최종 요청·대기 집계가 일치하지 않습니다."));
        }
        for (Request request : state.waitingRequests) {
            log.write("WAITLIST", "WARN", fields(request) + " result=UNRESOLVED");
        }
        log.write("TERMINATE", "INFO", "clientId=" + clientId
                + " heldSeats=" + seatText(state.heldSeats));
        log.write("TERMINATE", failure == null ? "SUCCESS" : "FAIL",
                "clientId=" + clientId + " byeReceived=" + byeReceived
                        + " sent=" + state.sent + " firstResponses=" + state.firstResponses
                        + " successes=" + state.successes + " failures=" + state.failures
                        + " waitlisted=" + state.waitlisted + " notifyReceived=" + state.notifications
                        + " unresolvedWaits=" + state.waitingRequests.size()
                        + " pending=" + state.pendingCount
                        + " averageResponseMillis=" + state.averageResponseMillis
                        + " reserveRequests=" + state.reserveRequests
                        + " multiRequests=" + state.multiRequests + " cancelRequests=" + state.cancelRequests
                        + " selectedSeats=" + state.selectedSeats + " popularSeats=" + state.popularSeats
                        + " popularSeatRatio=" + state.popularSeatRatio
                        + (failure == null ? "" : " cause=" + failure));
    }

    public Snapshot snapshot() {
        synchronized (stateLock) {
            List<Integer> sortedHeld = new ArrayList<>(held);
            sortedHeld.sort(Integer::compareTo);
            return new Snapshot(sent, firstResponses, successes, failures, waitlisted, notifications,
                    pending.size(), List.copyOf(sortedHeld), List.copyOf(waiting.values()),
                    firstResponses == 0 ? 0 : totalResponseNanos / (firstResponses * 1_000_000.0),
                    reserveRequests, multiRequests, cancelRequests, selectedSeats, popularSeats);
        }
    }

    public static final class Snapshot {
        public final int sent, firstResponses, successes, failures, waitlisted, notifications, pendingCount;
        public final List<Integer> heldSeats;
        public final List<Request> waitingRequests;
        public final double averageResponseMillis;
        public final int reserveRequests, multiRequests, cancelRequests;
        public final long selectedSeats, popularSeats;
        public final double popularSeatRatio;

        private Snapshot(int sent, int firstResponses, int successes, int failures, int waitlisted,
                int notifications, int pendingCount, List<Integer> heldSeats, List<Request> waitingRequests,
                double averageResponseMillis, int reserveRequests, int multiRequests, int cancelRequests,
                long selectedSeats, long popularSeats) {
            this.sent = sent;
            this.firstResponses = firstResponses;
            this.successes = successes;
            this.failures = failures;
            this.waitlisted = waitlisted;
            this.notifications = notifications;
            this.pendingCount = pendingCount;
            this.heldSeats = heldSeats;
            this.waitingRequests = waitingRequests;
            this.averageResponseMillis = averageResponseMillis;
            this.reserveRequests = reserveRequests;
            this.multiRequests = multiRequests;
            this.cancelRequests = cancelRequests;
            this.selectedSeats = selectedSeats;
            this.popularSeats = popularSeats;
            popularSeatRatio = selectedSeats == 0 ? 0 : (double) popularSeats / selectedSeats;
        }
    }

    private static void sendLine(BufferedWriter output, String line) throws IOException {
        output.write(line);
        output.write('\n');
        output.flush();
    }

    private static String fields(Request request) {
        return "clientId=" + request.clientId + " requestId=" + request.requestId
                + " seats=" + seatText(request.seats);
    }

    private static String seatText(List<Integer> seats) {
        StringJoiner text = new StringJoiner(",");
        for (int seat : seats) {
            text.add(Integer.toString(seat));
        }
        return seats.isEmpty() ? "-" : text.toString();
    }
}
