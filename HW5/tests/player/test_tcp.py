import hashlib
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import tempfile
import time
import threading
import unittest

from test_bots import kit_root
from src.player.control import Lines, send_line

ROOT = Path(__file__).resolve().parents[2]


class ControlDouble:
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(10)
        self.address = self.listener.getsockname()
        self.states, self.peers, self.lines = {}, {}, {}
        self.crashed = self.quit = None
        self.restart_at = None
        self.restarted = self.rejoined = False
        self.errors = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self):
        # 실제 Crasher 대신 crash 하나랑 quit 하나만 주입해서 Player 통합을 확인함
        sockets = [self.listener]
        accepted = []
        try:
            while not self.stop.is_set():
                for sock in select.select(sockets, [], [], 0.03)[0]:
                    if sock is self.listener:
                        peer, _ = sock.accept()
                        peer.settimeout(2)
                        sockets.append(peer)
                        accepted.append(peer)
                        self.lines[peer] = Lines(peer)
                        continue
                    reader = self.lines[sock]
                    try:
                        reader.receive()
                    except EOFError:
                        sockets.remove(sock)
                        continue
                    while (line := reader.pop()) is not None:
                        fields = line.split()
                        k = int(fields[1][1:])
                        if fields[0] == "CTRL":
                            self.peers[k] = sock
                        else:
                            self.states[k] = fields[2:]
                            if fields[2] == "CRASHED" and k == self.crashed:
                                self.restart_at = time.monotonic()+4.1
                            if fields[2] == "IDLE" and k == self.crashed and self.restarted:
                                self.rejoined = True
                if len(self.peers) != 10:
                    continue
                if self.crashed is None:
                    candidates = [k for k, state in self.states.items() if state[0] == "PLAYING"]
                    if candidates:
                        self.crashed = min(candidates)
                        send_line(self.peers[self.crashed], "CRASH")
                if self.crashed is not None and self.quit is None:
                    crashed_state = self.states.get(self.crashed, [])
                    if crashed_state and crashed_state[0] == "CRASHED":
                        candidates = [k for k, state in self.states.items() if state[0] == "PLAYING"
                                      and k != self.crashed and state[1] != crashed_state[1]]
                        if candidates:
                            self.quit = min(candidates)
                            send_line(self.peers[self.quit], "QUIT")
                if self.restart_at and not self.restarted and time.monotonic() >= self.restart_at:
                    send_line(self.peers[self.crashed], "RESTART")
                    self.restarted = True
                if len(self.states) == 10 and all(state[0] == "END" for state in self.states.values()):
                    return
        except Exception as exc:
            self.errors.append(exc)
        finally:
            for sock in accepted:
                sock.close()

    def close(self):
        self.stop.set()
        self.thread.join(5)
        self.listener.close()
        if self.thread.is_alive():
            raise AssertionError("control double did not stop")


class TCPTests(unittest.TestCase):
    def run_league(self, tables, config, run, hashes=None):
        # 실제 서버랑 Player 10개를 별도 프로세스로 띄워 결과 파일까지 대조함
        kit = kit_root()
        external = os.environ.get("HW5_PLAYER_RESULTS_DIR")
        with tempfile.TemporaryDirectory(prefix="hw5 player ") as temporary:
            parent = Path(external) if external else Path(temporary)
            output = parent / f"{config}_M{tables}_{time.time_ns()}" / f"run_{run}"
            children = []
            controller = ControlDouble() if run == "D" else None
            try:
                server = subprocess.Popen([sys.executable, "-m", "src.server", "--host", "127.0.0.1",
                    "--port", "0", "--seed", "2026", "--tables", str(tables), "--timeout", "3000",
                    "--run", run, "--out", str(output)], cwd=ROOT, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE)
                children.append(server)
                league_log = output / f"Run{run}_League.txt"
                deadline = time.monotonic()+10
                while time.monotonic() < deadline:
                    if league_log.exists():
                        match = re.search(r"listen 127\.0\.0\.1:(\d+)", league_log.read_text())
                        if match:
                            port = match[1]
                            break
                    self.assertIsNone(server.poll(), "server failed before listen")
                    time.sleep(0.01)
                else:
                    self.fail("server did not become ready")
                for row in (kit / "4_config" / f"players_{config}.txt").read_text().splitlines():
                    fields = row.split()
                    if not fields or fields[0].startswith("#"):
                        continue
                    command = [sys.executable, "-m", "src.player", "--host", "127.0.0.1", "--port", port,
                        "--id", fields[0], "--strategy", fields[1], "--think", "18,22", "--run", run,
                        "--out", str(output)]
                    if len(fields) == 3:
                        command += ["--fault", fields[2]]
                    if controller:
                        command += ["--crasher", f"{controller.address[0]}:{controller.address[1]}"]
                    children.append(subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
                deadline = time.monotonic()+90
                for process in children:
                    _, stderr = process.communicate(timeout=max(1, deadline-time.monotonic()))
                    self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
                self.assertEqual(len(list(output.iterdir())), 14)
                results = (output / f"Run{run}_results.txt").read_bytes()
                standings = (output / f"Run{run}_standings.txt").read_bytes()
                self.assertEqual(len(results.splitlines()), 45)
                self.assertEqual(len(standings.splitlines()), 10)
                if hashes:
                    self.assertEqual(tuple(hashlib.sha256(data).hexdigest()[:8] for data in (results, standings)), hashes)
                log = league_log.read_text()
                if run not in ("C", "D"):
                    result_lines = [line for line in log.splitlines() if re.search(r"\| RESULT\s*\|", line)]
                    self.assertEqual(len(result_lines), 45)
                    self.assertTrue(all("confirm=OK/OK" in line for line in result_lines))
                for row in standings.decode().splitlines():
                    rank, name, w, d, l, pts, gf, ga = row.split()
                    player_log = (output / f"Run{run}_{name}.txt").read_text()
                    self.assertNotIn("| VERIFY | FAIL", player_log)
                    if controller and name == f"P{controller.quit}":
                        self.assertIn("left at", player_log.splitlines()[-1])
                    elif controller and "observed_only=yes" in player_log.splitlines()[-1]:
                        tail = player_log.splitlines()[-1]
                        self.assertIn(f"rank={rank} pts={pts}", tail)
                        observed = [0, 0, 0]
                        mid_seen = set()
                        for entry in player_log.splitlines():
                            match = re.search(r"\| RESULT \| SUCCESS \| G(\d+) (\d+):(\d+) (\S+)", entry)
                            if match:
                                mid, sa, sb, outcome = match.groups()
                                self.assertNotIn(mid, mid_seen)
                                mid_seen.add(mid)
                                if outcome == "DRAW":
                                    observed[1] += 1
                                else:
                                    side = 0 if name in (output / f"Run{run}_results.txt").read_text().splitlines()[int(mid)].split()[1:2] else 1
                                    scores = (int(sa), int(sb))
                                    observed[0 if scores[side] > scores[1-side] else 2] += 1
                        ow, od, ol = observed
                        self.assertIn(f"W{ow} D{od} L{ol} observed_only=yes missing={9-len(mid_seen)}", tail)
                    elif run != "C" or name != "P8":
                        self.assertIn(f"rank={rank} pts={pts} W{w} D{d} L{l}", player_log.splitlines()[-1])
                    else:
                        self.assertIn("left at G21", player_log.splitlines()[-1])
                for path in output.iterdir():
                    data = path.read_bytes()
                    data.decode("ascii")
                    self.assertNotIn(b"\r", data)
                    self.assertTrue(data.endswith(b"\n"))
                if run == "C":
                    match_log = (output / "RunC_match_log.txt").read_text()
                    for line in ("F 11 4 A TIMEOUT", "F 30 7 A BAD_CARD", "F 40 3 A BAD_HASH", "F 21 6 B DISCONNECT"):
                        self.assertIn(line, match_log)
                    self.assertIn("STALE", log)
                if controller:
                    controller.thread.join(5)
                    self.assertFalse(controller.thread.is_alive())
                    self.assertFalse(controller.errors, controller.errors)
                    self.assertIsNotNone(controller.crashed)
                    self.assertIsNotNone(controller.quit)
                    self.assertTrue(controller.restarted and controller.rejoined)
                    self.assertTrue(all(state == ["END"] for state in controller.states.values()))
                env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
                check = subprocess.run([sys.executable, str(kit / "2_tools/python/verify_league.py"), str(output)],
                    cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertIn("PASS", check.stdout)
                self.assertNotIn("FAIL", check.stdout)
                if external:
                    print(f"\nTCP {config} M={tables} Run {run}: {output}", flush=True)
            finally:
                for process in children:
                    if process.poll() is None:
                        process.kill()
                for process in children:
                    process.communicate(timeout=10)
                if controller:
                    controller.close()

    def test_sample_tables_1(self):
        self.run_league(1, "sample", "A", ("cfde2bce", "c8a0c732"))

    def test_sample_tables_2(self):
        self.run_league(2, "sample", "B", ("cfde2bce", "c8a0c732"))

    def test_sample_tables_4(self):
        self.run_league(4, "sample", "B", ("cfde2bce", "c8a0c732"))

    def test_team_run_a(self):
        self.run_league(1, "std", "A", ("5255a2bf", "6a4147b7"))

    def test_team_run_b(self):
        self.run_league(4, "std", "B", ("5255a2bf", "6a4147b7"))

    def test_fault_run_c(self):
        self.run_league(4, "fault", "C")

    def test_run_d_with_control_double(self):
        self.run_league(4, "std", "D")


class CLITests(unittest.TestCase):
    def test_invalid_cli_and_existing_log(self):
        with tempfile.TemporaryDirectory(prefix="hw5 cli ") as directory:
            root = Path(directory)
            base = [sys.executable, "-m", "src.player", "--host", "127.0.0.1", "--port", "9500",
                    "--id", "1", "--strategy", "MATCH", "--run", "B", "--out", str(root / "logs")]
            for options in (["--id", "11"], ["--port", "0"], ["--think", "nan,22"], ["--think", "0,0"],
                            ["--strategy", "UNKNOWN"], ["--fault", "slow@0,1"], ["--run", "D"],
                            ["--crasher", "bad"], ["--run", "C", "--fault", "slow@45,1"]):
                result = subprocess.run(base+options, cwd=ROOT, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2, options)
                self.assertFalse((root / "logs").exists())
            (root / "logs").mkdir()
            path = root / "logs/RunB_P1.txt"
            path.write_bytes(b"previous run\n")
            result = subprocess.run(base, cwd=ROOT, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(path.read_bytes(), b"previous run\n")
