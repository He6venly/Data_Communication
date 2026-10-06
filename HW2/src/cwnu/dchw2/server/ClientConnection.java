package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces.Connection;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.nio.ByteBuffer;
import java.nio.channels.ClosedSelectorException;
import java.nio.channels.CancelledKeyException;
import java.nio.channels.SelectionKey;
import java.nio.channels.Selector;
import java.nio.channels.SocketChannel;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.locks.ReentrantLock;

/** 한 Client의 수신 조립 상태와 직렬화된 송신을 관리한다. */
public final class ClientConnection implements Connection {
    private final SocketChannel channel;
    private final Selector writeSelector;
    private final SelectionKey writeKey;
    private final ReentrantLock sendLock = new ReentrantLock();
    private final ByteBuffer receiveBuffer = ByteBuffer.allocate(8192);
    private final ByteArrayOutputStream unfinishedLine = new ByteArrayOutputStream();
    private volatile int clientId;
    private volatile boolean closed;
    private int nextRequestId = 1;

    public ClientConnection(SocketChannel channel) throws IOException {
        this.channel = Objects.requireNonNull(channel, "channel");
        channel.configureBlocking(false);
        writeSelector = Selector.open();
        try {
            writeKey = channel.register(writeSelector, 0);
        } catch (IOException | RuntimeException e) {
            try {
                writeSelector.close();
            } catch (IOException closeError) {
                e.addSuppressed(closeError);
            }
            throw e;
        }
    }

    @Override
    public int clientId() {
        return clientId;
    }

    @Override
    public void bindClientId(int clientId) {
        if (clientId < 1) {
            throw new IllegalArgumentException("Client 번호는 양수여야 합니다.");
        }
        synchronized (this) {
            if (this.clientId != 0) {
                throw new IllegalStateException("Client 번호는 한 번만 등록할 수 있습니다.");
            }
            this.clientId = clientId;
        }
    }

    /** Listener 스레드만 호출한다. 반환값 -1은 상대가 연결을 닫았다는 뜻이다. */
    int readLines(List<String> lines) throws IOException {
        int total = 0;
        while (true) {
            int read = channel.read(receiveBuffer);
            if (read < 0) {
                return -1;
            }
            if (read == 0) {
                return total;
            }
            total += read;
            receiveBuffer.flip();
            while (receiveBuffer.hasRemaining()) {
                byte value = receiveBuffer.get();
                if (value == '\n') {
                    lines.add(decodeLine());
                    unfinishedLine.reset();
                } else {
                    unfinishedLine.write(value);
                }
            }
            receiveBuffer.clear();
        }
    }

    private String decodeLine() throws IOException {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(unfinishedLine.toByteArray())).toString();
        } catch (CharacterCodingException e) {
            throw new IOException("UTF-8 메시지를 해석할 수 없습니다.", e);
        }
    }

    /** Listener 스레드에서 요청 번호를 검사하고 다음 번호로 옮긴다. */
    void acceptRequestId(int requestId) {
        if (requestId != nextRequestId) {
            throw new IllegalArgumentException("요청 번호가 순서와 다릅니다. expected="
                    + nextRequestId + " actual=" + requestId);
        }
        nextRequestId++;
    }

    @Override
    public void send(String line) throws IOException {
        Objects.requireNonNull(line, "line");
        if (line.indexOf('\n') >= 0 || line.indexOf('\r') >= 0) {
            throw new IllegalArgumentException("송신 문자열에는 줄바꿈을 넣을 수 없습니다.");
        }
        ByteBuffer message = StandardCharsets.UTF_8.encode(line + "\n");
        sendLock.lock();
        try {
            if (closed || !channel.isOpen()) {
                throw new IOException("이미 닫힌 연결입니다.");
            }
            while (message.hasRemaining()) {
                if (channel.write(message) != 0) {
                    continue;
                }
                waitUntilWritable();
            }
        } finally {
            try {
                if (writeKey.isValid() && writeSelector.isOpen()) {
                    writeKey.interestOps(0);
                    writeSelector.selectedKeys().clear();
                }
            } catch (CancelledKeyException | ClosedSelectorException ignored) {
                // close가 송신 대기를 해제한 경우에는 원래의 송신 실패를 그대로 전달한다.
            }
            sendLock.unlock();
        }
    }

    private void waitUntilWritable() throws IOException {
        try {
            checkWriteInterrupted();
            if (!writeKey.isValid()) {
                throw new IOException("송신 대기 중 연결이 닫혔습니다.");
            }
            writeKey.interestOps(SelectionKey.OP_WRITE);
            while (!closed) {
                checkWriteInterrupted();
                int ready = writeSelector.select();
                checkWriteInterrupted();
                if (ready > 0) {
                    break;
                }
            }
            writeSelector.selectedKeys().clear();
            writeKey.interestOps(0);
            if (closed || !channel.isOpen()) {
                throw new IOException("송신 대기 중 연결이 닫혔습니다.");
            }
        } catch (CancelledKeyException | ClosedSelectorException e) {
            throw new IOException("송신 대기 중 연결이 닫혔습니다.", e);
        }
    }

    private static void checkWriteInterrupted() throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) {
            // isInterrupted는 상태를 지우지 않으므로 호출자도 interrupt를 확인할 수 있다.
            throw new InterruptedIOException("송신 쓰기 준비 대기가 중단되었습니다.");
        }
    }

    @Override
    public void close() throws IOException {
        closed = true;
        IOException problem = null;
        // 송신 Lock을 기다리지 않고 채널을 먼저 닫아 write/select 대기를 해제한다.
        try {
            channel.close();
        } catch (IOException e) {
            problem = e;
        }
        writeSelector.wakeup();
        try {
            writeSelector.close();
        } catch (IOException e) {
            if (problem == null) {
                problem = e;
            } else {
                problem.addSuppressed(e);
            }
        }
        if (problem != null) {
            throw problem;
        }
    }

    SocketChannel channel() {
        return channel;
    }
}
