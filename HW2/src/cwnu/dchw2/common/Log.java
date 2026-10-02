package cwnu.dchw2.common;

import cwnu.dchw2.common.Interfaces.Logger;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Objects;

/** 실행당 파일 하나를 새로 작성한다. 생성한 Server/ClientMain이 close 책임을 갖는다. */
public final class Log implements Logger {
    private static final DateTimeFormatter CLOCK =
            DateTimeFormatter.ofPattern("HH:mm:ss.SSS").withZone(ZoneOffset.UTC);
    private final String node;
    private final BufferedWriter writer;
    private boolean closed;

    public Log(String node, Path file) throws IOException {
        this.node = field(node, "node");
        Path absolute = Objects.requireNonNull(file, "file").toAbsolutePath();
        Files.createDirectories(absolute.getParent());
        writer = Files.newBufferedWriter(absolute, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE);
    }

    @Override
    public synchronized void write(String event, String status, String message) throws IOException {
        if (closed) {
            throw new IOException("이미 닫힌 로그입니다: " + node);
        }
        String eventField = field(event, "event");
        if (!Objects.equals(status, "INFO") && !Objects.equals(status, "SUCCESS")
                && !Objects.equals(status, "FAIL") && !Objects.equals(status, "WARN")) {
            throw new IllegalArgumentException("로그 STATUS가 잘못되었습니다.");
        }
        String singleLine = Objects.requireNonNull(message, "message")
                .replace('\r', ' ').replace('\n', ' ');
        writer.write("[" + CLOCK.format(Instant.now()) + "] " + node + " | "
                + eventField + " | " + status + " | " + singleLine + "\n");
        writer.flush();
    }

    @Override
    public synchronized void close() throws IOException {
        if (!closed) {
            closed = true;
            writer.close();
        }
    }

    private static String field(String value, String name) {
        Objects.requireNonNull(value, name);
        if (value.isBlank() || value.indexOf('|') >= 0
                || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0) {
            throw new IllegalArgumentException(name + "은 비어 있지 않은 한 줄 필드여야 합니다.");
        }
        return value;
    }
}
