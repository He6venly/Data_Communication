import hashlib
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from src.server.match import Match, Peer
from src.server.rules import card_hash

HW5 = Path(__file__).resolve().parents[2]
KIT = Path(os.environ.get("HW5_KIT_DIR", HW5.parents[1] / "HW5_student_kit")).resolve()


@contextmanager
def connected_pair():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)
        with socket.create_connection(listener.getsockname(), timeout=2) as client:
            server, _ = listener.accept()
            with server:
                server.settimeout(2)
                yield server, client


def play_as_bot(port, player, strategy, fault=""):
    with socket.create_connection(("127.0.0.1", port), timeout=15) as sock:
        with sock.makefile("rb") as stream:
            def send(line):
                sock.sendall((line + "\n").encode("ascii"))

            if player == 1:
                sock.sendall(b"HEL")
                time.sleep(0.005)
                send(f"LO P{player} {strategy}")
            else:
                send(f"HELLO P{player} {strategy}")

            retired = False
            for raw in stream:
                kind, *args = raw.decode("ascii").split()
                if kind == "WELCOME":
                    _, seed, timeout_ms = args
                elif kind == "MATCH":
                    mid, _, _ = args
                    hand = list(range(1, 11))
                    prizes_left = set(range(1, 11))
                    scores = [0, 0]
                    rng = int(hashlib.sha256(f"{seed}:{mid}:{player}".encode()).hexdigest()[:8], 16) % (2**31)
                elif kind == "ROUND":
                    mid, round_no, prize = args
                    prize = int(prize)
                    active_fault = fault.split("@")[0] if fault.endswith(f"@{mid},{round_no}") else ""
                    if active_fault == "quit":
                        send(f"QUIT {mid}")
                        retired = True
                        continue
                    if active_fault == "slow":
                        time.sleep(int(timeout_ms) / 1000 + 1)
                    if active_fault == "badcard":
                        card = 11
                    elif strategy == "MATCH":
                        card = prize
                    elif strategy == "PLUS1":
                        card = next((value for value in hand if value > prize), hand[0])
                    elif strategy == "BIGSMALL":
                        card = hand[-1] if prize >= 6 else hand[0]
                    elif strategy == "TEAM":
                        card = hand[-1] if prize == max(prizes_left) else next(
                            (value for value in hand[:-1] if value >= prize + 2), hand[0],
                        )
                    else:
                        rng = (1103515245 * rng + 12345) % (2**31)
                        card = hand[(rng >> 16) % len(hand)]
                    nonce = f"{player:02x}{int(mid):02x}{int(round_no):012x}"
                    hashed = hashlib.sha256(f"{card}:{nonce}".encode()).hexdigest()
                    send(f"COMMIT {mid} {round_no} {hashed}")
                elif kind == "COMMITS":
                    card_to_send = card % 10 + 1 if active_fault == "badhash" else card
                    send(f"REVEAL {mid} {round_no} {card_to_send} {nonce}")
                elif kind == "REVEALS":
                    _, _, a, _, b, _, winner, score_a, score_b = args
                    a, b = int(a), int(b)
                    expected_winner = "A" if a > b else "B" if b > a else "-"
                    if expected_winner == "A":
                        scores[0] += prize
                    elif expected_winner == "B":
                        scores[1] += prize
                    if (expected_winner, *scores) != (winner, int(score_a), int(score_b)):
                        raise AssertionError(f"P{player}: incorrect REVEALS {args}")
                    hand.remove(card)
                    prizes_left.remove(prize)
                elif kind == "FORFEIT":
                    scores = {"A": [0, 55], "B": [55, 0], "BOTH": [0, 0]}[args[1]]
                elif kind == "MATCH_END":
                    match_mid, _, score_a, score_b = args
                    if retired or scores != [int(score_a), int(score_b)]:
                        raise AssertionError(f"P{player}: unexpected MATCH_END {args}")
                    send(f"CONFIRM {match_mid} {scores[0]}:{scores[1]}")
                elif kind == "LEAGUE_END":
                    if retired:
                        raise AssertionError(f"P{player}: LEAGUE_END after QUIT")
                elif kind == "BYE":
                    return
                elif kind != "START":
                    raise AssertionError(f"P{player}: unexpected {kind}")
            raise AssertionError(f"P{player}: server closed before BYE")


class ServerTests(unittest.TestCase):
    def run_league(self, run, tables, config):
        self.assertTrue(KIT.is_dir(), f"Set HW5_KIT_DIR to the kit directory: {KIT}")
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / f"run_{run}"
            log = out / f"Run{run}_League.txt"
            server = subprocess.Popen(
                [
                    sys.executable, "-B", "-m", "src.server",
                    "--host", "127.0.0.1", "--port", "0", "--tables", str(tables),
                    "--seed", "2026", "--timeout", "3000", "--run", run, "--out", str(out),
                ],
                cwd=HW5, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                until = time.monotonic() + 8
                port = None
                while server.poll() is None and time.monotonic() < until:
                    if log.is_file():
                        match = re.search(r"listen 127\.0\.0\.1:(\d+)", log.read_text(encoding="ascii"))
                        if match:
                            port = int(match[1])
                            break
                    time.sleep(0.01)
                self.assertIsNotNone(port, "Server did not listen")

                configs = (KIT / "4_config" / config).read_text(encoding="ascii").splitlines()
                with ThreadPoolExecutor(max_workers=10) as executor:
                    tasks = []
                    for line in configs:
                        player, strategy, *fault = line.split()
                        tasks.append(executor.submit(play_as_bot, port, int(player), strategy, *fault))
                    for task in tasks:
                        task.result(timeout=30)

                _, errors = server.communicate(timeout=5)
                self.assertEqual(server.returncode, 0, errors.decode(errors="replace"))
                files = {path.name: path.read_bytes() for path in out.iterdir()}
                for data in files.values():
                    self.assertTrue(data.isascii() and data.endswith(b"\n") and b"\r" not in data)
                self.assertEqual(len(files), 4)
                self.assertIn(b"45 matches in", files[log.name])

                # verify_league checks presence of the Player logs before replay.
                # These files stand in for the teammates' log writers in this Server-only test.
                for player in range(1, 11):
                    (out / f"Run{run}_P{player}.txt").touch()
                verify = subprocess.run(
                    [sys.executable, "-X", "utf8", str(KIT / "2_tools/python/verify_league.py"), str(out)],
                    capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
                )
                self.assertIn("matches 45/45  round-errors 0  overlap 0", verify.stdout)
                self.assertIn("-> PASS", verify.stdout)
                return files
            finally:
                if server.poll() is None:
                    server.kill()
                server.communicate()

    def test_a_and_b_match_reference_hashes(self):
        for config, expected in (
            ("players_sample.txt", ("cfde2bce", "c8a0c732")),
            ("players_std.txt", ("5255a2bf", "6a4147b7")),
        ):
            with self.subTest(config=config):
                a = self.run_league("A", 1, config)
                b = self.run_league("B", 4, config)
                for name, hash8 in zip(("results", "standings"), expected):
                    result = a[f"RunA_{name}.txt"]
                    self.assertEqual(result, b[f"RunB_{name}.txt"])
                    self.assertEqual(hashlib.sha256(result).hexdigest()[:8], hash8)
                for log in (a["RunA_League.txt"], b["RunB_League.txt"]):
                    self.assertEqual(log.count(b"confirm=OK/OK"), 45)
                    self.assertIn(b"commit_samples=450", log)

    def test_run_c_fouls_walkovers_and_stale(self):
        files = self.run_league("C", 4, "players_fault.txt")
        faults = [line for line in files["RunC_match_log.txt"].splitlines() if line.startswith(b"F ")]
        self.assertEqual(
            {line for line in faults if line.split()[2] != b"0"},
            {b"F 11 4 A TIMEOUT", b"F 21 6 B DISCONNECT", b"F 30 7 A BAD_CARD", b"F 40 3 A BAD_HASH"},
        )
        for line in faults:
            _, mid, round_no, side, reason = line.split()
            if round_no == b"0":
                row = files["RunC_results.txt"].splitlines()[int(mid)].split()
                self.assertEqual(row[1 if side == b"A" else 2], b"P8")
                self.assertEqual(reason, b"DISCONNECT")
        self.assertIn(b"P2 dropped 'COMMIT 11 4", files["RunC_League.txt"])
        self.assertIn(b"P8 QUIT (virtual disconnect) in G21 -> DEAD", files["RunC_League.txt"])

    def test_commit_deadline_does_not_penalize_other_player(self):
        logs = []
        with connected_pair() as (sa, _), connected_pair() as (sb, b):
            match = Match(
                0, 1, (Peer(sa, 1), Peer(sb, 2)), set(), 2026, 0.5, time.monotonic(),
                lambda *parts: logs.append(parts),
            )
            b.sendall(b"COMMIT 9 1 old\nREJOIN P2\nCOM")
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(match._ask, "ROUND 0 1 8", "COMMIT", 1)
                b.settimeout(2)
                with b.makefile("rb") as stream:
                    self.assertEqual(stream.readline(), b"ROUND 0 1 8\n")
                hashed = card_hash(2, "0000000000000000")
                b.sendall(f"MIT 0 1 {hashed}\n".encode("ascii"))
                answers, faults, _ = future.result(timeout=2)
            self.assertEqual(faults, {0: "TIMEOUT"})
            self.assertEqual(answers, {1: ["COMMIT", "0", "1", hashed]})
            self.assertEqual([event for event, _, _ in logs], ["STALE", "REJOIN"])

    def test_walkover_and_quit_during_confirm(self):
        with (
            connected_pair() as (sa, _), connected_pair() as (sb, b),
            ThreadPoolExecutor(max_workers=1) as executor, b.makefile("rb") as stream,
        ):
            peers = (Peer(sa, 1), Peer(sb, 2))
            started = time.monotonic()
            logs = []

            def log(*parts):
                logs.append(parts)

            match = Match(0, 1, peers, {1}, 2026, 1, started, log)
            future = executor.submit(match.play)
            self.assertEqual(stream.readline(), b"MATCH 0 B P1\n")
            self.assertTrue(stream.readline().startswith(b"ROUND 0 1 "))
            b.sendall(b"COMMIT 0 1\n")
            self.assertEqual(stream.readline(), b"FORFEIT 0 A DISCONNECT\n")
            self.assertEqual(stream.readline(), b"MATCH_END 0 FORFEIT_A 0 55\n")
            b.sendall(b"QUIT 0\n")
            result = future.result(timeout=2)
            self.assertEqual((result.outcome, result.scores), ("FORFEIT_A", (0, 55)))
            self.assertEqual(result.confirmations, ("-", "-"))
            self.assertEqual(result.dead, {1, 2})
            self.assertIn("F 00 0 A DISCONNECT", result.lines)
            self.assertIn(("DISCONN", "WARN", "P2 QUIT (virtual disconnect) in G00 -> DEAD"), logs)

            both = Match(0, 1, peers, result.dead, 2026, 1, started, log).play()
            self.assertEqual((both.outcome, both.scores), ("FORFEIT_BOTH", (0, 0)))
            self.assertIn("F 00 0 BOTH DISCONNECT", both.lines)


if __name__ == "__main__":
    unittest.main()
