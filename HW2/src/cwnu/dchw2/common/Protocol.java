package cwnu.dchw2.common;

import java.util.List;
import java.util.StringJoiner;

/** 팀장 제공 공통 규약. UTF-8로 전송하고, 송신 담당이 반환 문자열에 LF를 붙인다. */
public final class Protocol {
    private Protocol() {}

    public static final int HELLO = 1000;
    public static final int RESERVE = 1001;
    public static final int RESERVE_MULTI = 1002;
    public static final int CANCEL = 1003;
    public static final int RESP = 2000;
    public static final int NOTIFY = 2001;
    public static final int BYE = 2002;
    public static final int SUCCESS = 3000;
    public static final int FAIL = 3001;
    public static final int WAITLISTED = 3002;

    public static final String OK = "OK";
    public static final String TAKEN = "TAKEN";
    public static final String ALREADY_OWNER = "ALREADY_OWNER";
    public static final String ALREADY_WAITING = "ALREADY_WAITING";
    public static final String NOT_OWNER = "NOT_OWNER";
    public static final String BAD_SEAT = "BAD_SEAT";
    public static final String BAD_MULTI = "BAD_MULTI";

    public static final int SEAT_COUNT = 100;
    public static final int CLIENT_COUNT = 30;
    public static final int WORKER_COUNT = 10;
    public static final int REQUESTS_PER_CLIENT = 5_000;
    public static final int REQUEST_QUEUE_CAPACITY = 1_024;
    public static final int MIN_MULTI_SEATS = 2;
    public static final int MAX_MULTI_SEATS = 4;
    public static final int MIN_REQUEST_INTERVAL_MS = 200;
    public static final int MAX_REQUEST_INTERVAL_MS = 1_000;
    public static final long MONITOR_INTERVAL_MS = 5_000;
    public static final long STALL_THRESHOLD_MS = 30_000;

    /** clientId는 연결에서 붙인다. 좌석의 의미 검사는 SeatManager가 담당한다. */
    public static final class Request {
        public final int clientId;
        public final int requestId;
        public final int command;
        public final List<Integer> seats;

        public Request(int clientId, int requestId, int command, List<Integer> seats) {
            this.clientId = clientId;
            this.requestId = requestId;
            this.command = command;
            this.seats = List.copyOf(seats);
        }
    }

    /** NOTIFY/BYE의 미사용 status는 0, reason은 "-"로 둔다. */
    public static final class Response {
        public final int type;
        public final int requestId;
        public final int status;
        public final List<Integer> seats;
        public final String reason;

        public Response(int type, int requestId, int status,
                        List<Integer> seats, String reason) {
            this.type = type;
            this.requestId = requestId;
            this.status = status;
            this.seats = List.copyOf(seats);
            this.reason = reason;
        }
    }

    public static String encodeHello(int clientId) {
        checkClientId(clientId);
        return HELLO + " " + clientId;
    }

    public static int parseHello(String line) {
        String[] fields = fields(line);
        expectFields(fields, 2);
        if (number(fields[0]) != HELLO) {
            throw new IllegalArgumentException("첫 메시지는 HELLO여야 합니다.");
        }
        int clientId = number(fields[1]);
        checkClientId(clientId);
        return clientId;
    }

    public static String encodeRequest(Request request) {
        checkClientId(request.clientId);
        checkRequestId(request.requestId);
        checkOperation(request.command);
        checkSingleSeatField(request.command, request.seats);
        return request.command + " " + request.requestId + " " + seatText(request.seats);
    }

    /** 형식 오류는 예외, 범위·MULTI 개수·중복 오류는 그대로 반환해 FAIL 판정에 맡긴다. */
    public static Request decodeRequest(String line, int clientId) {
        checkClientId(clientId);
        String[] fields = fields(line);
        expectFields(fields, 3);
        int command = number(fields[0]);
        checkOperation(command);
        int requestId = number(fields[1]);
        checkRequestId(requestId);
        List<Integer> seats = parseSeats(fields[2]);
        checkSingleSeatField(command, seats);
        return new Request(clientId, requestId, command, seats);
    }

    public static Response response(Request request, int status, String reason) {
        checkStatus(status);
        checkReason(reason);
        return new Response(RESP, request.requestId, status, request.seats, reason);
    }

    public static Response notification(int requestId, int seat) {
        checkRequestId(requestId);
        checkSeat(seat);
        return new Response(NOTIFY, requestId, 0, List.of(seat), "-");
    }

    public static Response bye() {
        return new Response(BYE, 0, 0, List.of(), "-");
    }

    public static String encodeResponse(Response response) {
        switch (response.type) {
            case RESP:
                checkRequestId(response.requestId);
                checkStatus(response.status);
                checkReason(response.reason);
                return RESP + " " + response.requestId + " " + response.status
                        + " " + seatText(response.seats) + " " + response.reason;
            case NOTIFY:
                checkRequestId(response.requestId);
                if (response.seats.size() != 1) {
                    throw new IllegalArgumentException("NOTIFY는 좌석 1개여야 합니다.");
                }
                checkSeat(response.seats.get(0));
                return NOTIFY + " " + response.requestId + " " + response.seats.get(0);
            case BYE:
                return Integer.toString(BYE);
            default:
                throw new IllegalArgumentException("알 수 없는 서버 메시지입니다.");
        }
    }

    public static Response decodeResponse(String line) {
        String[] fields = fields(line);
        int type = number(fields[0]);
        switch (type) {
            case RESP:
                expectFields(fields, 5);
                int requestId = number(fields[1]);
                checkRequestId(requestId);
                int status = number(fields[2]);
                checkStatus(status);
                checkReason(fields[4]);
                return new Response(RESP, requestId, status, parseSeats(fields[3]), fields[4]);
            case NOTIFY:
                expectFields(fields, 3);
                return notification(number(fields[1]), number(fields[2]));
            case BYE:
                expectFields(fields, 1);
                return bye();
            default:
                throw new IllegalArgumentException("알 수 없는 서버 메시지입니다.");
        }
    }

    /** 로그 EVENT 등에 사용할 이름이다. 전송에는 숫자 코드를 사용한다. */
    public static String commandName(int command) {
        switch (command) {
            case HELLO: return "HELLO";
            case RESERVE: return "RESERVE";
            case RESERVE_MULTI: return "RESERVE_MULTI";
            case CANCEL: return "CANCEL";
            case RESP: return "RESP";
            case NOTIFY: return "NOTIFY";
            case BYE: return "BYE";
            default: throw new IllegalArgumentException("알 수 없는 명령입니다.");
        }
    }

    public static String statusName(int status) {
        switch (status) {
            case SUCCESS: return "SUCCESS";
            case FAIL: return "FAIL";
            case WAITLISTED: return "WAITLISTED";
            default: throw new IllegalArgumentException("알 수 없는 결과입니다.");
        }
    }

    private static String[] fields(String line) {
        if (line == null || line.isBlank() || line.indexOf('\n') >= 0 || line.indexOf('\r') >= 0) {
            throw new IllegalArgumentException("완성된 메시지 한 줄이 필요합니다.");
        }
        return line.strip().split("\\s+");
    }

    private static void expectFields(String[] fields, int count) {
        if (fields.length != count) {
            throw new IllegalArgumentException("메시지 필드 수가 잘못되었습니다.");
        }
    }

    private static int number(String text) {
        try {
            return Integer.parseInt(text);
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("정수가 아닌 필드입니다: " + text, e);
        }
    }

    private static List<Integer> parseSeats(String text) {
        if (text.equals("-")) {
            return List.of();
        }
        String[] values = text.split(",", -1);
        java.util.ArrayList<Integer> seats = new java.util.ArrayList<>(values.length);
        for (String value : values) {
            seats.add(number(value));
        }
        return List.copyOf(seats);
    }

    private static String seatText(List<Integer> seats) {
        if (seats.isEmpty()) {
            return "-";
        }
        StringJoiner text = new StringJoiner(",");
        for (int seat : seats) {
            text.add(Integer.toString(seat));
        }
        return text.toString();
    }

    private static void checkClientId(int clientId) {
        if (clientId < 1 || clientId > CLIENT_COUNT) {
            throw new IllegalArgumentException("Client 번호는 1~30이어야 합니다.");
        }
    }

    private static void checkRequestId(int requestId) {
        if (requestId < 1) {
            throw new IllegalArgumentException("요청 번호는 1 이상이어야 합니다.");
        }
    }

    private static void checkOperation(int command) {
        if (command != RESERVE && command != RESERVE_MULTI && command != CANCEL) {
            throw new IllegalArgumentException("예약·취소 명령이 아닙니다.");
        }
    }

    private static void checkSingleSeatField(int command, List<Integer> seats) {
        if (command != RESERVE_MULTI && seats.size() != 1) {
            throw new IllegalArgumentException("단일 예약·취소는 좌석 필드 1개가 필요합니다.");
        }
    }

    private static void checkSeat(int seat) {
        if (seat < 1 || seat > SEAT_COUNT) {
            throw new IllegalArgumentException("통지 좌석 번호는 1~100이어야 합니다.");
        }
    }

    private static void checkStatus(int status) {
        if (status != SUCCESS && status != FAIL && status != WAITLISTED) {
            throw new IllegalArgumentException("알 수 없는 결과입니다.");
        }
    }

    private static void checkReason(String reason) {
        if (!List.of(OK, TAKEN, ALREADY_OWNER, ALREADY_WAITING,
                NOT_OWNER, BAD_SEAT, BAD_MULTI).contains(reason)) {
            throw new IllegalArgumentException("알 수 없는 응답 사유입니다.");
        }
    }
}
