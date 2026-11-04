"""도구에서 공통으로 쓰는 파일 형식 검사 함수."""

from hashlib import sha256
import json
import math
from pathlib import Path
import re


WIDTH = 160
HEIGHT = 80
SNAPSHOT_ROUNDS = tuple(range(0, 3001, 100))
FRAME_ROUNDS = tuple(range(0, 3001, 10))
VALID_N = (1, 4, 5, 6, 7, 8)

HASH8_RE = re.compile(r"[0-9a-f]{8}", re.ASCII)
HASH_RE = re.compile(r"[0-9a-f]{64}", re.ASCII)
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", re.ASCII)
LOG_RE = re.compile(
    r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\] (ASSIGNER|WORKER\d+) \| "
    r"([A-Z]+) \| (SUCCESS|FAIL|INFO|WARN) \| (\{.*\})$"
)


# 파일이나 로그 형식이 과제 규약과 다를 때 사용하는 예외다.
class FormatError(ValueError):
    """입력이나 산출물의 형식이 계약과 다를 때 사용한다."""


# bool을 제외한 실제 정수인지 확인한다.
def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# 무한대와 NaN이 아닌 유한한 수인지 확인한다.
def is_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


# 바이트 데이터의 전체 SHA-256 값을 계산한다.
def sha256_hex(data):
    return sha256(data).hexdigest()


# ASCII와 LF로 저장된 80x160 그림 파일을 검사하고 읽는다.
def read_grid(path):
    """80x160, 출력 가능한 ASCII, LF 형식의 그림을 읽는다."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FormatError(f"{path}: 파일을 읽을 수 없습니다 ({exc})") from exc

    if len(data) != 12880:
        raise FormatError(f"{path}: 파일 크기는 12880바이트여야 합니다")
    if b"\r" in data:
        raise FormatError(f"{path}: CRLF가 아닌 LF 줄바꿈이 필요합니다")
    rows = data.split(b"\n")
    if len(rows) != HEIGHT + 1 or rows[-1] != b"":
        raise FormatError(f"{path}: 80줄과 마지막 LF가 필요합니다")
    for number, row in enumerate(rows[:-1], start=1):
        if len(row) != WIDTH:
            raise FormatError(f"{path}: {number}번째 줄은 160자여야 합니다")
        if any(byte < 32 or byte > 126 for byte in row):
            raise FormatError(f"{path}: 출력 가능한 ASCII만 사용할 수 있습니다")
    return data, tuple(row.decode("ascii") for row in rows[:-1])


# 80x160 그림을 마지막 LF까지 포함한 바이트 형식으로 저장한다.
def write_grid(path, rows):
    if len(rows) != HEIGHT or any(len(row) != WIDTH for row in rows):
        raise ValueError("저장할 그림은 80x160이어야 합니다")
    data = ("\n".join(rows) + "\n").encode("ascii")
    Path(path).write_bytes(data)
    return data


# NaN과 무한대를 허용하지 않고 JSON 객체를 읽는다.
def load_json(path):
    path = Path(path)

    def invalid_constant(value):
        raise FormatError(f"{path}: {value}는 유효한 JSON 수가 아닙니다")

    try:
        with path.open(encoding="utf-8") as file:
            result = json.load(file, parse_constant=invalid_constant)
    except (OSError, ValueError) as exc:
        raise FormatError(f"{path}: JSON을 읽을 수 없습니다 ({exc})") from exc
    if not isinstance(result, dict):
        raise FormatError(f"{path}: JSON 최상위 값은 객체여야 합니다")
    return result


# RoundHash.txt의 31개 해시와 순서를 검사한다.
def read_round_hash(path):
    path = Path(path)
    try:
        data = path.read_bytes()
        if b"\r" in data or not data.endswith(b"\n"):
            raise FormatError(f"{path}: RoundHash는 LF 줄바꿈과 마지막 LF가 필요합니다")
        lines = data.decode("ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FormatError(f"{path}: RoundHash를 읽을 수 없습니다 ({exc})") from exc
    expected = [f"round{r:04d}.txt" for r in SNAPSHOT_ROUNDS]
    if len(lines) != len(expected):
        raise FormatError(f"{path}: RoundHash는 정확히 31줄이어야 합니다")
    result = {}
    for index, (line, name) in enumerate(zip(lines, expected), start=1):
        fields = line.split()
        if len(fields) != 2 or fields[0] != name or not HASH8_RE.fullmatch(fields[1]):
            raise FormatError(f"{path}: {index}번째 해시의 이름, 순서 또는 형식이 잘못됐습니다")
        result[name] = fields[1]
    return result


# 한 줄 단위 노드 로그를 JSON 필드로 분리해 읽는다.
def read_log(path, expected_node=None):
    path = Path(path)
    try:
        data = path.read_bytes()
        if b"\r" in data or not data.endswith(b"\n"):
            raise FormatError(f"{path}: 로그는 LF 줄바꿈과 마지막 LF가 필요합니다")
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FormatError(f"{path}: 로그를 읽을 수 없습니다 ({exc})") from exc
    if not lines:
        raise FormatError(f"{path}: 로그가 비어 있습니다")
    records = []
    for number, line in enumerate(lines, start=1):
        match = LOG_RE.fullmatch(line)
        if match is None:
            raise FormatError(f"{path}: {number}번째 로그 형식이 잘못됐습니다")
        _, node, event, status, body = match.groups()
        if expected_node is not None and node != expected_node:
            raise FormatError(f"{path}: 노드 이름은 {expected_node}여야 합니다")
        try:
            fields = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(
                FormatError(f"유효하지 않은 JSON 수: {value}")))
        except ValueError as exc:
            raise FormatError(f"{path}: {number}번째 JSON이 잘못됐습니다 ({exc})") from exc
        if not isinstance(fields, dict):
            raise FormatError(f"{path}: 로그 JSON은 객체여야 합니다")
        records.append({"node": node, "event": event, "status": status,
                        "fields": fields, "line": number})
    return records


# 읽은 로그에서 원하는 이벤트와 상태만 골라낸다.
def event_records(records, event, status=None):
    return [record for record in records
            if record["event"] == event and (status is None or record["status"] == status)]

