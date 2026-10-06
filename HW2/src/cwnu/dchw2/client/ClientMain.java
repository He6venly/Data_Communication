package cwnu.dchw2.client;

import cwnu.dchw2.common.Log;
import cwnu.dchw2.common.Protocol;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;

public final class ClientMain {
    private ClientMain() {}

    public static void main(String[] args) {
        List<Log> logs = new ArrayList<>();
        List<Client> clients = new ArrayList<>();
        List<Thread> threads = new ArrayList<>();
        BlockingQueue<Client> ended = new LinkedBlockingQueue<>();
        Throwable failure = null;
        boolean interrupted = false;
        int requests = 0;
        try {
            if (args.length != 3 || args[0].isBlank()) {
                throw new IllegalArgumentException("사용법: ClientMain <serverHost> <port> <Client당 요청 수>");
            }
            int port = Integer.parseInt(args[1]);
            requests = Integer.parseInt(args[2]);
            if (port < 1 || port > 65535 || requests < 1
                    || requests > Integer.MAX_VALUE / Protocol.CLIENT_COUNT) {
                throw new IllegalArgumentException("포트 또는 요청 수가 유효 범위를 벗어났습니다.");
            }
            for (int id = 1; id <= Protocol.CLIENT_COUNT; id++) {
                Log log = new Log("CLIENT" + id, Path.of("logs", "Client" + id + ".txt"));
                logs.add(log);
                log.write("INIT", "INFO", "clientId=" + id + " requests=" + requests);
                Client client = new Client(id, args[0], port, requests, log);
                clients.add(client);
                threads.add(new Thread(() -> {
                    try {
                        client.run();
                    } finally {
                        ended.add(client);
                    }
                }, "Client-" + id + "-receive"));
            }
            for (Thread thread : threads) {
                thread.start();
            }
            for (int count = 0; count < clients.size(); count++) {
                Client client = ended.take();
                if (client.failure() != null) {
                    throw new IOException("Client 실행이 실패했습니다.", client.failure());
                }
            }
        } catch (InterruptedException e) {
            interrupted = true;
            failure = e;
        } catch (IOException | RuntimeException e) {
            failure = e;
        } finally {
            if (failure != null) {
                for (Client client : clients) {
                    client.abort(failure);
                }
            }
            for (Thread thread : threads) {
                while (thread.isAlive()) {
                    try {
                        thread.join();
                    } catch (InterruptedException e) {
                        interrupted = true;
                        if (failure == null) {
                            failure = e;
                        }
                        for (Client client : clients) {
                            client.abort(failure);
                        }
                    }
                }
            }
            for (Log log : logs) {
                try {
                    log.close();
                } catch (IOException | RuntimeException e) {
                    if (failure == null) {
                        failure = e;
                    } else {
                        failure.addSuppressed(e);
                    }
                }
            }
            if (interrupted) {
                Thread.currentThread().interrupt();
            }
        }
        if (failure != null) {
            System.err.println("ClientMain 실패: " + failure);
            if (failure.getCause() != null) {
                System.err.println("원인: " + failure.getCause());
            }
            System.exit(1);
        }
        int sent = 0;
        int responses = 0;
        int notifications = 0;
        long selected = 0;
        long popular = 0;
        for (Client client : clients) {
            Client.Snapshot state = client.snapshot();
            sent += state.sent;
            responses += state.firstResponses;
            notifications += state.notifications;
            selected += state.selectedSeats;
            popular += state.popularSeats;
        }
        double ratio = selected == 0 ? 0 : (double) popular / selected;
        String condition = popularCondition(requests, clients.size(), sent, responses, selected, popular);
        System.out.println("Client " + clients.size() + "개 종료: sent=" + sent
                + " firstResponses=" + responses + " notifyReceived=" + notifications
                + " requestsPerClient=" + requests
                + " selectedSeats=" + selected + " popularSeats=" + popular
                + " popularSeatRatio=" + ratio
                + " popularCondition=" + condition);
        if (condition.equals("BELOW_HALF")) {
            System.err.println("과제 조건 미달: 정식 실행의 인기 좌석 선택 비율이 절반 미만입니다."
                    + " selectedSeats=" + selected + " popularSeats=" + popular
                    + " popularSeatRatio=" + ratio);
            System.exit(1);
        }
    }

    /** Client 30명의 정식 요청 완료 후 전체 선택 수로 판정한다. 축소 실행은 실측만 한다. */
    static String popularCondition(int requestsPerClient, int clientCount, int sent,
            int firstResponses, long selectedSeats, long popularSeats) {
        int expected = Protocol.CLIENT_COUNT * Protocol.REQUESTS_PER_CLIENT;
        if (requestsPerClient != Protocol.REQUESTS_PER_CLIENT
                || clientCount != Protocol.CLIENT_COUNT || sent != expected || firstResponses != expected) {
            return "NOT_EVALUATED";
        }
        // CANCEL과 MULTI의 모든 좌석을 포함하며, 정확히 절반인 경우도 통과한다.
        return selectedSeats > 0 && popularSeats >= selectedSeats / 2 + selectedSeats % 2
                ? "PASS" : "BELOW_HALF";
    }
}
