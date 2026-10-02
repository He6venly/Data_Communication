package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces;
import cwnu.dchw2.common.Protocol;
import java.io.IOException;
import java.util.StringJoiner;

public final class Worker implements Runnable {
    private final Interfaces.RequestQueue queue;
    private final Interfaces.Seats seats;
    private final Interfaces.Notifications notifier;
    private final Interfaces.ServerContext server;
    private final Interfaces.Logger log;
    private volatile boolean abortRequested;

    public Worker(Interfaces.RequestQueue queue, Interfaces.Seats seats,
            Interfaces.Notifications notifier, Interfaces.ServerContext server,
            Interfaces.Logger log) {
        this.queue = queue;
        this.seats = seats;
        this.notifier = notifier;
        this.server = server;
        this.log = log;
    }

    /** 실패 종료 전용. 정상 종료는 RequestQueue.close 후 잔여 처리로 끝낸다. */
    public void abort() {
        abortRequested = true;
    }

    @Override
    public void run() {
        try {
            while (!abortRequested) {
                Interfaces.Task task = queue.take();
                if (task == null || abortRequested) {
                    return;
                }
                Protocol.Request request = task.request;
                String event = Protocol.commandName(request.command);
                String fields = fields(request);
                log.write(event, "INFO", fields + " result=REQUEST");
                Interfaces.Result result = seats.handle(request);
                // handle는 모든 좌석 Lock을 풀고 반환한다. 통지가 RESP보다 먼저 갈 수 있다.
                if (result.notice != null) {
                    notifier.submit(result.notice);
                }
                task.connection.send(Protocol.encodeResponse(result.response));
                server.recordFirstResponse(request.clientId);
                String status = Protocol.statusName(result.response.status);
                if (request.command == Protocol.RESERVE_MULTI
                        && result.detail.contains("lockOrder=")) {
                    log.write("LOCK", "INFO", fields + " result=" + status + " " + result.detail);
                }
                log.write(result.response.status == Protocol.WAITLISTED ? "WAITLIST" : event,
                        result.response.status == Protocol.WAITLISTED ? "WARN" : status,
                        fields + " result=" + status + " reason=" + result.response.reason
                        + " " + result.detail);
            }
        } catch (InterruptedException e) {
            if (!abortRequested) {
                server.reportFailure(e);
            }
            Thread.currentThread().interrupt();
        } catch (IOException | RuntimeException e) {
            server.reportFailure(e);
        }
    }

    static String fields(Protocol.Request request) {
        StringJoiner seatText = new StringJoiner(",");
        for (int seat : request.seats) {
            seatText.add(Integer.toString(seat));
        }
        return "clientId=" + request.clientId + " requestId=" + request.requestId
                + " seats=" + (request.seats.isEmpty() ? "-" : seatText.toString());
    }
}
