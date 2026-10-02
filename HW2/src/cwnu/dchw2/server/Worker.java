package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces.Logger;
import cwnu.dchw2.common.Interfaces.Notifications;
import cwnu.dchw2.common.Interfaces.RequestQueue;
import cwnu.dchw2.common.Interfaces.Result;
import cwnu.dchw2.common.Interfaces.Seats;
import cwnu.dchw2.common.Interfaces.ServerContext;
import cwnu.dchw2.common.Interfaces.Task;
import cwnu.dchw2.common.Protocol;
import cwnu.dchw2.common.Protocol.Request;
import java.io.IOException;
import java.util.StringJoiner;

public final class Worker implements Runnable {
    private final RequestQueue queue;
    private final Seats seats;
    private final Notifications notifier;
    private final ServerContext server;
    private final Logger log;
    private volatile boolean abortRequested;

    public Worker(RequestQueue queue, Seats seats,
            Notifications notifier, ServerContext server,
            Logger log) {
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
                Task task = queue.take();
                if (task == null || abortRequested) {
                    return;
                }
                Request request = task.request;
                String event = Protocol.commandName(request.command);
                String fields = fields(request);
                log.write(event, "INFO", fields + " result=REQUEST");
                Result result = seats.handle(request);
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

    static String fields(Request request) {
        StringJoiner seatText = new StringJoiner(",");
        for (int seat : request.seats) {
            seatText.add(Integer.toString(seat));
        }
        return "clientId=" + request.clientId + " requestId=" + request.requestId
                + " seats=" + (request.seats.isEmpty() ? "-" : seatText.toString());
    }
}
