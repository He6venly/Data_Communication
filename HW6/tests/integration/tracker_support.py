"""별도 Tracker 프로세스와 네 TCP 대역 피어를 구성함."""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

from src.common.transport import Conn


PROJECT = Path(__file__).resolve().parents[2]
KIT = Path(os.environ.get("HW6_KIT_DIR", PROJECT.parent / "제공 파일 및 명세 설명/hw6_student_kit/Python"))


def env_for_tcp():
    """배포 env의 별도 복사본에 작은 비정형 파일과 여유 있는 제한을 적용함."""
    env = json.loads((KIT / "envs/DEV.json").read_text(encoding="utf-8"))
    env.update(name="TCP_UNIT3", chunk_size=8, progress_total_chunks=12, crashes=[], destroy=None)
    env["files"] = [dict(name=name, size=len(data), origin=pid, sha256=hashlib.sha256(data).hexdigest())
                    for name, data, pid in [("a.bin", b"abcdefghijk", "P1"),
                                            ("b.bin", b"12345678", "P2"), ("c.bin", b"x", "P3")]]
    env["timing"].update(dead_sec=4, hang_sec=30, deadline_sec=30)
    return env


def free_port():
    """CLI에 전달할 로컬 임시 포트를 구함."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def until(predicate, timeout=5):
    """대기 조건을 짧게 확인하고 실패 시 무한 대기를 막음."""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError("condition timed out")
        time.sleep(.02)


def exchange(conn, line):
    """명령 하나를 보내고 FILES·PEERS의 후속 행까지 모두 읽음."""
    conn.send_line(line)
    header = conn.read_line()
    words = header.split()
    count = int(words[1]) if words and words[0] in ("FILES", "PEERS") else 0
    return (header, *(conn.read_line() for _ in range(count)))


class TrackerProcess:
    """한글·공백 경로에서 실행한 독립 Tracker의 출력·수명을 관리함."""

    def __init__(self, root, env, *, wrapper=None, extra_args=None):
        """원본 env와 별도의 JSON을 쓰고 실제 모듈 진입점을 실행함."""
        self.root = Path(root)
        self.env = env
        self.env_path = self.root / "작은 설정.json"
        self.env_path.write_text(json.dumps(env), encoding="utf-8")
        self.original_env = self.env_path.read_bytes()
        self.port = env["tracker"]["port"]
        self.out = (self.root / "stdout.txt").open("wb")
        self.err = (self.root / "stderr.txt").open("wb")
        command = [sys.executable, "-B"] + (["-c", wrapper] if wrapper else ["-m", "src.tracker"])
        command += ["--env", str(self.env_path), *(extra_args or [])]
        child_env = dict(os.environ, PYTHONPATH=str(PROJECT), PYTHONIOENCODING="utf-8")
        self.process = subprocess.Popen(command, cwd=self.root, env=child_env, stdout=self.out, stderr=self.err)
        self.connections = []

    def ready(self):
        """listen 완료 출력을 제한 시간 안에 확인함."""
        def check():
            if "Tracker listening" in (self.root / "stdout.txt").read_text(encoding="utf-8"):
                return True
            if self.process.poll() is not None:
                raise AssertionError(self.stderr())
            return False
        until(check)

    def connect(self):
        """실제 로컬 TCP 연결을 열고 테스트 종료 시 회수하도록 등록함."""
        conn = Conn(socket.create_connection(("127.0.0.1", self.port), timeout=3))
        self.connections.append(conn)
        return conn

    def join(self):
        """서로 다른 연결 네 개에서 HELLO와 원본 REGISTER를 수행함."""
        peers = {}
        for peer in self.env["peers"]:
            pid = peer["id"]
            conn = self.connect()
            assert exchange(conn, f"HELLO {pid}") == ("OK",)
            peers[pid] = conn
        for file in self.env["files"]:
            pid = file["origin"]
            peer = next(p for p in self.env["peers"] if p["id"] == pid)
            assert exchange(peers[pid], f"REGISTER {pid} {peer['port']} {file['name']} {file['size']} 8") == ("OK",)
        return peers

    def events(self):
        """이미 flush된 JSONL 행을 읽고 쓰는 중인 마지막 행은 다음 확인으로 미룸."""
        path = self.root / "logs/tracker.jsonl"
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                break
        return events

    def stderr(self):
        """실패 원인을 확인할 표준 오류 출력을 반환함."""
        return (self.root / "stderr.txt").read_text(encoding="utf-8")

    def wait(self, timeout=8):
        """자식 종료와 원본 env 보존을 확인하고 실행 결과를 반환함."""
        code = self.process.wait(timeout=timeout)
        assert self.env_path.read_bytes() == self.original_env
        return code

    def close(self):
        """검사 실패 때도 연결·자식·출력 핸들을 회수함."""
        try:
            for conn in self.connections:
                conn.close()
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
        finally:
            self.out.close()
            self.err.close()


class TCPCase(unittest.TestCase):
    """검사마다 독립 작업 폴더·env·프로세스를 준비함."""

    def setUp(self):
        """결과와 로그가 다른 실행과 섞이지 않게 임시 폴더를 사용함."""
        import tempfile
        self.directory = tempfile.TemporaryDirectory(prefix="hw6 TCP 한글 ")
        self.addCleanup(self.directory.cleanup)
        self.env = env_for_tcp()
        self.env["tracker"]["port"] = free_port()

    def start(self, **kwargs):
        """실제 모듈을 실행하고 성공·실패와 관계없이 회수를 등록함."""
        child = TrackerProcess(self.directory.name, self.env, **kwargs)
        self.addCleanup(child.close)
        child.ready()
        return child

    def check_result(self, child, code):
        """종료 코드·필수 로그·EXIT 마지막 행·report를 함께 확인함."""
        self.assertEqual(child.wait(), code, child.stderr())
        records = child.events()
        self.assertEqual(records[0]["ev"], "START_PROGRAM")
        self.assertEqual(records[0]["env"], self.env["name"])
        self.assertEqual(records[-1]["ev"], "EXIT")
        self.assertEqual(records[-1]["code"], code)
        self.assertEqual(sum(e["ev"] == "EXIT" for e in records), 1)
        self.assertTrue(all(e["peer"] == "tracker" for e in records))
        self.assertEqual([e["t"] for e in records], sorted(e["t"] for e in records))
        data = (child.root / "report.json").read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertFalse(list(child.root.glob(".report-*.tmp")))
        return json.loads(data), records

