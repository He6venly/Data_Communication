package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces.Logger;
import cwnu.dchw2.common.Interfaces.RequestQueue;
import cwnu.dchw2.common.Interfaces.ServerContext;
import cwnu.dchw2.common.Interfaces.Stoppable;
import cwnu.dchw2.common.Interfaces.Task;
import cwnu.dchw2.common.Protocol;
import cwnu.dchw2.common.Protocol.Request;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.channels.SelectionKey;
import java.nio.channels.Selector;
import java.nio.channels.ServerSocketChannel;
import java.nio.channels.SocketChannel;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.StringJoiner;

/** 하나의 Selector에서 접속 수락과 모든 Client 수신을 처리한다. */
public final class Listener implements Stoppable {
    private final ServerContext server;
    private final RequestQueue queue;
    private final Logger log;
    private final Selector selector;
    private final ServerSocketChannel serverChannel;
    private final Set<ClientConnection> connections = new HashSet<>();
    private volatile boolean stopRequested;
    private boolean started;

    public Listener(ServerContext server, RequestQueue queue,
            Logger log, String bindHost, int port) throws IOException {
        this.server = Objects.requireNonNull(server, "server");
        this.queue = Objects.requireNonNull(queue, "queue");
        this.log = Objects.requireNonNull(log, "log");
        if (bindHost == null || bindHost.isBlank()) {
            throw new IllegalArgumentException("bindHost가 비어 있습니다.");
        }
        if (port < 1 || port > 65535) {
            throw new IllegalArgumentException("포트는 1~65535여야 합니다.");
        }

        Selector openedSelector = Selector.open();
        ServerSocketChannel openedServer = null;
        try {
            openedServer = ServerSocketChannel.open();
            openedServer.configureBlocking(false);
            openedServer.bind(new InetSocketAddress(bindHost, port));
            openedServer.register(openedSelector, SelectionKey.OP_ACCEPT);
        } catch (IOException | RuntimeException e) {
            if (openedServer != null) {
                try {
                    openedServer.close();
                } catch (IOException closeError) {
                    e.addSuppressed(closeError);
                }
            }
            try {
                openedSelector.close();
            } catch (IOException closeError) {
                e.addSuppressed(closeError);
            }
            throw e;
        }
        selector = openedSelector;
        serverChannel = openedServer;
    }

    @Override
    public void run() {
        synchronized (this) {
            if (started) {
                throw new IllegalStateException("Listener는 한 번만 실행할 수 있습니다.");
            }
            started = true;
        }
        try {
            while (!stopRequested) {
                checkInterrupted();
                selector.select();
                if (stopRequested) {
                    break;
                }
                checkInterrupted();
                Iterator<SelectionKey> keys = selector.selectedKeys().iterator();
                while (keys.hasNext() && !stopRequested) {
                    SelectionKey key = keys.next();
                    keys.remove();
                    if (!key.isValid()) {
                        continue;
                    }
                    if (key.isAcceptable()) {
                        acceptConnections();
                    } else if (key.isReadable()) {
                        readConnection(key);
                    }
                }
            }
        } catch (InterruptedException e) {
            if (!stopRequested) {
                fail(e, null);
            }
            Thread.currentThread().interrupt();
        } catch (IOException | RuntimeException e) {
            fail(e, null);
        } finally {
            closeListenerResources();
        }
    }

    private static void checkInterrupted() throws InterruptedException {
        if (Thread.currentThread().isInterrupted()) {
            throw new InterruptedException("Listener 스레드가 중단되었습니다.");
        }
    }

    private void acceptConnections() throws IOException {
        for (SocketChannel channel; (channel = serverChannel.accept()) != null;) {
            ClientConnection connection = null;
            try {
                channel.configureBlocking(false);
                connection = new ClientConnection(channel);
                channel.register(selector, SelectionKey.OP_READ, connection);
                connections.add(connection);
            } catch (IOException | RuntimeException e) {
                if (connection != null) {
                    connection.close();
                } else {
                    channel.close();
                }
                throw e;
            }
        }
    }

    private void readConnection(SelectionKey key) throws IOException, InterruptedException {
        ClientConnection connection = (ClientConnection) key.attachment();
        List<String> lines = new ArrayList<>();
        int read = connection.readLines(lines);
        if (read < 0) {
            throw new IOException("Client 연결이 예기치 않게 종료되었습니다: clientId="
                    + connection.clientId());
        }
        for (String line : lines) {
            if (stopRequested) {
                return;
            }
            try {
                handleLine(connection, line);
            } catch (IllegalArgumentException | IllegalStateException e) {
                logProtocolFailure(connection, e);
                key.cancel();
                connections.remove(connection);
                connection.close();
                throw e;
            }
        }
    }

    private void handleLine(ClientConnection connection, String line)
            throws IOException, InterruptedException {
        if (connection.clientId() == 0) {
            int clientId = Protocol.parseHello(line);
            server.registerClient(clientId, connection);
            return;
        }
        Request request = Protocol.decodeRequest(line, connection.clientId());
        connection.acceptRequestId(request.requestId);
        queue.put(new Task(request, connection));
        log.write(Protocol.commandName(request.command), "INFO",
                requestFields(request) + " result=REQUEST");
    }

    private void logProtocolFailure(ClientConnection connection, RuntimeException cause)
            throws IOException {
        log.write("PROTOCOL", "FAIL", "clientId=" + connection.clientId()
                + " reason=" + cause.getMessage());
    }

    private static String requestFields(Request request) {
        StringJoiner seats = new StringJoiner(",");
        for (int seat : request.seats) {
            seats.add(Integer.toString(seat));
        }
        return "clientId=" + request.clientId + " requestId=" + request.requestId
                + " seats=" + (request.seats.isEmpty() ? "-" : seats.toString());
    }

    private void fail(Throwable cause, ClientConnection connection) {
        if (connection != null) {
            try {
                connection.close();
            } catch (IOException closeError) {
                cause.addSuppressed(closeError);
            }
        }
        server.reportFailure(cause);
    }

    @Override
    public void stop() {
        stopRequested = true;
        selector.wakeup();
    }

    private void closeListenerResources() {
        IOException problem = null;
        try {
            serverChannel.close();
        } catch (IOException e) {
            problem = e;
        }
        for (ClientConnection connection : new ArrayList<>(connections)) {
            if (connection.clientId() == 0) {
                try {
                    connection.close();
                } catch (IOException e) {
                    if (problem == null) {
                        problem = e;
                    } else {
                        problem.addSuppressed(e);
                    }
                }
            }
        }
        try {
            selector.close();
        } catch (IOException e) {
            if (problem == null) {
                problem = e;
            } else {
                problem.addSuppressed(e);
            }
        }
        // stop의 wakeup과 달리 close가 던진 IOException은 실제 자원 정리 실패다.
        if (problem != null) {
            server.reportFailure(problem);
        }
    }
}
