import argparse
import socket
import threading
import time
import unittest
from unittest.mock import patch

from src.player.client import Player, card_hash
from src.player.bots import Bot, prize_order
from src.player.control import Lines, State


def args(**extra):
    values = dict(id=1, strategy="MATCH", host="127.0.0.1", port=9500, think=(18, 22),
                  run="B", fault=None, crasher=None)
    return argparse.Namespace(**(values | extra))


def read(sock, lines):
    while (line := lines.pop()) is None:
        lines.receive()
    return line


class Harness:
    def __init__(self, config=None):
        self.server, self.sock = socket.socketpair()
        self.server.settimeout(3)
        self.sock.settimeout(3)
        self.records = []
        self.client = Player(config or args(), self.sock, lambda *entry: self.records.append(entry))
        self.reader = Lines(self.server)
        self.result = None
        self.thread = threading.Thread(target=self.run)

    def run(self):
        try:
            self.result = self.client.run()
        finally:
            self.sock.close()

    def start(self):
        self.thread.start()
        assert read(self.server, self.reader).startswith("HELLO ")
        self.send(f"WELCOME P{self.client.args.id} 2026 80", "START 45")

    def send(self, *lines):
        self.server.sendall(("\n".join(lines)+"\n").encode())

    def line(self):
        return read(self.server, self.reader)

    def close(self):
        self.server.close()
        self.thread.join(5)
        if self.thread.is_alive():
            self.sock.shutdown(socket.SHUT_RDWR)
            self.thread.join(5)
        if self.thread.is_alive():
            raise AssertionError("Player thread did not stop")


class PlayerTests(unittest.TestCase):
    def make(self, config=None):
        h = Harness(config)
        self.addCleanup(h.close)
        h.start()
        return h

    def match(self, h, mid=0, side="A", opponent=2, tamper=None):
        # 서버 점수를 복사하지 않고 직접 계산한 점수로 CONFIRM하는지 확인함
        h.send(f"MATCH {mid} {side} P{opponent}")
        other = Bot("PLUS1", 2026, mid, opponent)
        scores = [0, 0]
        for r, prize in enumerate(prize_order(2026, mid), 1):
            h.send(f"ROUND {mid} {r} {prize}")
            commit = h.line().split()
            self.assertEqual(commit[:3], ["COMMIT", str(mid), str(r)])
            opp_card, opp_nonce = other.choose(prize, r), f"{r:016x}"
            hashes = [commit[3], card_hash(opp_card, opp_nonce)]
            if side == "B":
                hashes.reverse()
            h.send(f"COMMITS {mid} {r} {' '.join(hashes)}")
            reveal = h.line().split()
            self.assertEqual(reveal[:3], ["REVEAL", str(mid), str(r)])
            card, nonce = int(reveal[3]), reveal[4]
            self.assertEqual(card_hash(card, nonce), commit[3])
            self.assertEqual(len(nonce), 16)
            other.play(prize, r, opp_card, card)
            cards, nonces = [card, opp_card], [nonce, opp_nonce]
            if side == "B":
                cards.reverse()
                nonces.reverse()
            winner = "A" if cards[0] > cards[1] else "B" if cards[1] > cards[0] else "-"
            if winner != "-":
                scores[0 if winner == "A" else 1] += prize
            shown = scores[:] if tamper != "score" else [55, 55]
            shown_winner = winner if tamper != "winner" else "X"
            shown_nonces = nonces[:] if tamper != "hash" else ["0"*16]*2
            h.send(f"REVEALS {mid} {r} {cards[0]} {shown_nonces[0]} {cards[1]} {shown_nonces[1]} {shown_winner} {shown[0]} {shown[1]}")
        outcome = "WIN_A" if scores[0] > scores[1] else "WIN_B" if scores[1] > scores[0] else "DRAW"
        final = scores[:] if tamper != "final" else [55, 55]
        h.send(f"MATCH_END {mid} {outcome} {final[0]} {final[1]}")
        self.assertEqual(h.line(), f"CONFIRM {mid} {scores[0]}:{scores[1]}")
        return scores

    def finish(self, h, pts=0):
        h.send(f"LEAGUE_END 5 {pts}", "BYE")
        h.thread.join(5)
        self.assertFalse(h.thread.is_alive())

    def test_normal_match_both_sides(self):
        for player, side, opponent in ((1, "A", 2), (2, "B", 1)):
            h = self.make(args(id=player))
            self.match(h, side=side, opponent=opponent)
            self.finish(h)
            self.assertEqual(h.result, 0, h.records)
            self.assertEqual(h.records[-1][0:2], ("TERMINATE", "SUCCESS"))

    def test_score_winner_and_final_tamper_still_use_own_score(self):
        for tamper in ("score", "winner", "final"):
            h = self.make()
            self.match(h, tamper=tamper)
            self.finish(h)
            self.assertEqual(h.result, 1)
            self.assertTrue(any(event == "VERIFY" and status == "FAIL" for event, status, _ in h.records))

    def test_opponent_hash_tamper_is_detected(self):
        h = self.make()
        h.send("MATCH 0 A P2", f"ROUND 0 1 {prize_order(2026,0)[0]}")
        digest = h.line().split()[3]
        h.send(f"COMMITS 0 1 {digest} {'a'*64}")
        reveal = h.line().split()
        card, nonce = int(reveal[3]), reveal[4]
        h.send(f"REVEALS 0 1 {card} {nonce} 1 {'0'*16} A 8 0", "BYE")
        h.thread.join(3)
        self.assertEqual(h.result, 1)
        self.assertTrue(any("public hash mismatch" in r[2] for r in h.records))

    def test_forfeit_confirm_and_both_is_loss(self):
        for who, scores in (("A", "0:55"), ("B", "55:0"), ("BOTH", "0:0")):
            h = self.make()
            h.send("MATCH 0 A P2", f"FORFEIT 0 {who} TIMEOUT", f"MATCH_END 0 FORFEIT_{who} {scores.replace(':', ' ')}")
            self.assertEqual(h.line(), f"CONFIRM 0 {scores}")
            self.finish(h, 3 if who == "B" else 0)
            self.assertEqual(h.result, 0)
            self.assertEqual(h.client.stats, [1, 0, 0] if who == "B" else [0, 0, 1])

    def test_badcard_and_badhash_faults(self):
        for fault in ("badcard", "badhash"):
            h = self.make(args(run="C", fault=(fault, 0, 1)))
            prize = prize_order(2026, 0)[0]
            h.send("MATCH 0 A P2", f"ROUND 0 1 {prize}")
            commit = h.line().split()[3]
            h.send(f"COMMITS 0 1 {commit} {'a'*64}")
            reveal = h.line().split()
            if fault == "badcard":
                self.assertEqual(int(reveal[3]), 11)
                self.assertEqual(card_hash(11, reveal[4]), commit)
            else:
                self.assertNotEqual(card_hash(int(reveal[3]), reveal[4]), commit)
            h.send(f"FORFEIT 0 A {'BAD_CARD' if fault == 'badcard' else 'BAD_HASH'}", "MATCH_END 0 FORFEIT_A 0 55")
            self.assertEqual(h.line(), "CONFIRM 0 0:55")
            self.finish(h)
            self.assertEqual(h.result, 0)

    def test_slow_fault_sends_late_commit_then_confirms(self):
        h = self.make(args(run="C", fault=("slow", 0, 1)))
        start = time.monotonic()
        h.send("MATCH 0 A P2", f"ROUND 0 1 {prize_order(2026,0)[0]}")
        h.send("FORFEIT 0 A TIMEOUT", "MATCH_END 0 FORFEIT_A 0 55")
        self.assertTrue(h.line().startswith("COMMIT 0 1 "))
        self.assertGreaterEqual(time.monotonic()-start, 1.08)
        self.assertEqual(h.line(), "CONFIRM 0 0:55")
        self.finish(h)

    def test_virtual_quit_keeps_connection_until_bye(self):
        h = self.make(args(run="C", fault=("quit", 0, 1)))
        h.send("MATCH 0 A P2", f"ROUND 0 1 {prize_order(2026,0)[0]}")
        self.assertEqual(h.line(), "QUIT 0")
        h.send("FORFEIT 0 A DISCONNECT", "MATCH_END 0 FORFEIT_A 0 55")
        h.server.settimeout(0.1)
        with self.assertRaises(socket.timeout):
            h.server.recv(1)
        h.server.settimeout(3)
        h.send("BYE")
        h.thread.join(3)
        self.assertEqual(h.result, 0)
        self.assertIn("left at G00", h.records[-1][2])

    def test_eof_is_failure(self):
        h = self.make()
        h.server.shutdown(socket.SHUT_WR)
        h.thread.join(3)
        self.assertEqual(h.result, 1)

    def test_discarded_run_d_results_are_not_invented(self):
        # 승점으로 놓친 결과를 짐작할 수 있어도 관측한 전적만 그대로 적어줌
        for missing, points in ((1, 3), (1, 0), (3, 3)):
            h = self.make(args(run="D"))
            h.client.seen = set(range(9-missing))
            h.client.stats = [0, 0, 9-missing]
            h.send(f"LEAGUE_END 5 {points}", "BYE")
            h.thread.join(3)
            self.assertEqual(h.result, 0)
            self.assertIn(f"W0 D0 L{9-missing} observed_only=yes missing={missing}", h.records[-1][2])
            self.assertEqual(h.records[-1][1], "WARN")


class ConfirmBoundaryTests(unittest.TestCase):
    def prepare(self):
        game, peer = socket.socketpair()
        peer.settimeout(0.1)
        self.addCleanup(game.close)
        self.addCleanup(peer.close)
        player = Player(args(run="D"), game, lambda *record: None)
        self.addCleanup(player.state.close)
        player.handle("WELCOME P1 2026 3000")
        player.handle("START 45")
        player.handle("MATCH 0 A P2")
        player.handle("FORFEIT 0 B TIMEOUT")
        return player, peer

    def test_command_after_confirm_waits_for_idle_and_next_match(self):
        # CONFIRM 직후 장애가 들어와도 IDLE 보고를 마치고 다음 경기로 미뤄줌
        for command in ("CRASH", "QUIT"):
            with self.subTest(command=command):
                player, peer = self.prepare()
                attempted, released = threading.Event(), threading.Event()
                reports = []
                original = player.state.send
                def inject():
                    attempted.set()
                    player.state.command(command)
                    released.set()
                worker = threading.Thread(target=inject)
                def send(line, generation):
                    result = original(line, generation)
                    worker.start()
                    self.assertTrue(attempted.wait(1))
                    # 잘못된 이전 구현은 여기서 장애가 적용되고 새 구현은 Lock에서 대기함
                    released.wait(0.05)
                    return result
                player.state.report = lambda mode=None: reports.append(mode or player.state.mode)
                try:
                    with patch.object(player.state, "send", side_effect=send):
                        player.handle("MATCH_END 0 FORFEIT_B 55 0")
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(peer.recv(1024), b"CONFIRM 0 55:0\n")
                    self.assertEqual((player.state.mode, player.state.pending), ("IDLE", command))
                    self.assertEqual(reports, ["IDLE"])
                    player.handle("MATCH 1 A P3")
                    self.assertEqual(reports, ["IDLE", "PLAYING", "CRASHED" if command == "CRASH" else "QUIT"])
                    if command == "QUIT":
                        self.assertEqual(peer.recv(1024), b"QUIT 1\n")
                finally:
                    worker.join(2)

    def test_command_before_confirm_blocks_it(self):
        for command in ("CRASH", "QUIT"):
            with self.subTest(command=command):
                player, peer = self.prepare()
                player.state.command(command)
                if command == "QUIT":
                    self.assertEqual(peer.recv(1024), b"QUIT 0\n")
                player.handle("MATCH_END 0 FORFEIT_B 55 0")
                with self.assertRaises(socket.timeout):
                    peer.recv(1024)
                self.assertEqual(player.seen, set())

    def test_buffered_bye_before_restart_never_sends_rejoin(self):
        player, peer = self.prepare()
        player.state.command("CRASH")
        player.lines.buffer[:] = b"LEAGUE_END 5 3\nBYE\n"
        player.state.command("RESTART")
        self.assertEqual(player.read(), "BYE")
        with self.assertRaises(socket.timeout):
            peer.recv(1024)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.game, self.peer = socket.socketpair()
        self.peer.settimeout(0.05)
        self.records = []
        self.state = State(1, self.game, lambda *record: self.records.append(record))
        self.addCleanup(self.game.close)
        self.addCleanup(self.peer.close)
        self.addCleanup(self.state.close)

    def test_pending_crash_and_restart_generation(self):
        self.state.command("CRASH")
        self.assertEqual(self.state.mode, "IDLE")
        self.state.match(0)
        self.assertEqual(self.state.mode, "CRASHED")
        self.assertEqual([r[1] for r in self.records], ["INFO", "WARN"])
        self.assertFalse(self.state.send("COMMIT 0 1 hidden", 0))
        with self.assertRaises(socket.timeout):
            self.peer.recv(1)
        self.state.command("RESTART")
        self.assertEqual(self.state.mode, "RECOVERING")

    def test_crash_during_think_blocks_send(self):
        generation = self.state.match(0)
        self.state.round = 1
        self.state.command("CRASH")
        self.assertFalse(self.state.send("COMMIT 0 1 hidden", generation))
        self.assertFalse(self.state.send("REVEAL 0 1 1 nonce", generation))
        self.assertEqual(self.records[-1][2], "G00 r=1 last=- (now)")

    def test_pending_quit_and_permanent_quit(self):
        self.state.command("QUIT")
        self.state.match(8)
        self.assertEqual(self.peer.recv(100), b"QUIT 8\n")
        self.state.command("RESTART")
        self.assertEqual(self.state.mode, "QUIT")


class LineTests(unittest.TestCase):
    def test_split_coalesced_and_invalid_lines(self):
        a, b = socket.socketpair()
        try:
            lines = Lines(b)
            a.sendall(b"BY")
            lines.receive()
            self.assertIsNone(lines.pop())
            a.sendall(b"E\nNEXT\n")
            lines.receive()
            self.assertEqual(lines.pop(), "BYE")
            self.assertEqual(lines.pop(), "NEXT")
            for invalid in (b"\xff\n", b"X\r\n", b"\t\n", b"x"*4097):
                lines.buffer[:] = invalid
                with self.assertRaises(ValueError):
                    lines.pop()
        finally:
            a.close()
            b.close()


class ControlTests(unittest.TestCase):
    def make(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        h = Harness(args(run="D", crasher=listener.getsockname()))
        self.addCleanup(h.close)
        h.start()
        control, _ = listener.accept()
        control.settimeout(3)
        self.addCleanup(control.close)
        lines = Lines(control)
        self.assertEqual(read(control, lines), "CTRL P1")
        self.assertEqual(read(control, lines), "STATE P1 IDLE")
        return h, control, lines

    def command(self, control, line):
        control.sendall((line+"\n").encode())

    def quiet(self, h):
        h.server.settimeout(0.06)
        try:
            with self.assertRaises(socket.timeout):
                h.server.recv(1)
        finally:
            h.server.settimeout(3)

    def test_idle_pending_crash_restart_ignores_old_match_then_plays_new(self):
        h, control, lines = self.make()
        self.command(control, "CRASH")
        deadline = time.monotonic()+2
        while h.client.state.pending is None and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertEqual(h.client.state.pending, "CRASH")
        h.send("MATCH 0 A P2")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 0")
        self.assertEqual(read(control, lines), "STATE P1 CRASHED 0")
        h.send(f"ROUND 0 1 {prize_order(2026,0)[0]}", "FORFEIT 0 A TIMEOUT", "MATCH_END 0 FORFEIT_A 0 55")
        self.quiet(h)
        self.command(control, "RESTART")
        self.assertEqual(h.line(), "REJOIN P1")
        self.assertEqual(read(control, lines), "STATE P1 IDLE")
        h.send("COMMITS 0 1 ignored ignored", "MATCH_END 0 FORFEIT_A 0 55")
        self.quiet(h)
        h.send("MATCH 1 A P3", "FORFEIT 1 B TIMEOUT", "MATCH_END 1 FORFEIT_B 55 0")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 1")
        self.assertEqual(h.line(), "CONFIRM 1 55:0")
        self.assertEqual(read(control, lines), "STATE P1 IDLE")
        h.send("LEAGUE_END 1 3", "BYE")
        self.assertEqual(read(control, lines), "STATE P1 END")
        h.thread.join(3)
        self.assertEqual(h.result, 0, h.records)
        self.assertEqual(sum(r[:2] == ("CRASH", "WARN") for r in h.records), 1)
        self.assertFalse(h.client.state.thread.is_alive())

    def test_crash_during_real_think_has_no_commit(self):
        h, control, lines = self.make()
        entered, resume = threading.Event(), threading.Event()
        def pause(seconds):
            entered.set()
            self.assertTrue(resume.wait(3))
        with patch("src.player.client.time.sleep", side_effect=pause):
            h.send("MATCH 0 A P2", f"ROUND 0 1 {prize_order(2026,0)[0]}")
            self.assertEqual(read(control, lines), "STATE P1 PLAYING 0")
            self.assertTrue(entered.wait(2))
            self.command(control, "CRASH")
            self.assertEqual(read(control, lines), "STATE P1 CRASHED 0")
            resume.set()
            self.quiet(h)
        h.send("BYE")
        self.assertEqual(read(control, lines), "STATE P1 END")
        h.thread.join(3)
        self.assertFalse(h.client.state.thread.is_alive())
        self.assertEqual(h.result, 1)

    def test_quit_midmatch_and_bye_end(self):
        h, control, lines = self.make()
        h.send("MATCH 0 A P2")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 0")
        self.command(control, "QUIT")
        self.assertEqual(h.line(), "QUIT 0")
        self.assertEqual(read(control, lines), "STATE P1 QUIT")
        self.command(control, "RESTART")
        h.send("ROUND 0 1 8", "MATCH_END 0 FORFEIT_A 0 55")
        self.quiet(h)
        h.send("BYE")
        self.assertEqual(read(control, lines), "STATE P1 END")
        h.thread.join(3)
        self.assertEqual(h.records[-1][:2], ("TERMINATE", "WARN"))
        self.assertIn("left at G00", h.records[-1][2])

    def test_control_eof_wakes_game_and_joins(self):
        h, control, lines = self.make()
        control.shutdown(socket.SHUT_RDWR)
        h.thread.join(3)
        self.assertFalse(h.thread.is_alive())
        self.assertEqual(h.result, 1)
        self.assertFalse(h.client.state.thread.is_alive())

    def test_restart_drains_buffer_and_partial_old_line(self):
        h, control, lines = self.make()
        h.send("MATCH 0 A P2")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 0")
        self.command(control, "CRASH")
        self.assertEqual(read(control, lines), "STATE P1 CRASHED 0")
        h.server.sendall(b"ROUND 0 1 ")
        self.command(control, "RESTART")
        self.assertEqual(h.line(), "REJOIN P1")
        self.assertEqual(read(control, lines), "STATE P1 IDLE")
        h.server.sendall(b"8\nMATCH 1 A P3\nFORFEIT 1 B TIMEOUT\nMATCH_END 1 FORFEIT_B 55 0\n")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 1")
        self.assertEqual(h.line(), "CONFIRM 1 55:0")
        self.assertEqual(read(control, lines), "STATE P1 IDLE")
        h.send("LEAGUE_END 5 3", "BYE")
        self.assertEqual(read(control, lines), "STATE P1 END")
        h.thread.join(3)
        self.assertEqual(h.result, 0)

    def test_crash_after_commit_blocks_reveal(self):
        h, control, lines = self.make()
        h.send("MATCH 0 A P2", f"ROUND 0 1 {prize_order(2026,0)[0]}")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 0")
        digest = h.line().split()[3]
        self.command(control, "CRASH")
        self.assertEqual(read(control, lines), "STATE P1 CRASHED 0")
        h.send(f"COMMITS 0 1 {digest} {'a'*64}")
        self.quiet(h)
        self.assertIn("last=COMMIT", [r[2] for r in h.records if r[0:2] == ("CRASH", "WARN")][0])
        h.send("BYE")
        self.assertEqual(read(control, lines), "STATE P1 END")
        h.thread.join(3)
        self.assertFalse(h.thread.is_alive())

    def test_last_match_restart_and_bye_together(self):
        h, control, lines = self.make()
        h.send("MATCH 8 A P10")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 8")
        self.command(control, "CRASH")
        self.assertEqual(read(control, lines), "STATE P1 CRASHED 8")
        self.command(control, "RESTART")
        h.send("FORFEIT 8 A TIMEOUT", "MATCH_END 8 FORFEIT_A 0 55", "LEAGUE_END 10 0", "BYE")
        self.assertIn(read(control, lines), ("STATE P1 END", "STATE P1 IDLE"))
        h.thread.join(3)
        self.assertFalse(h.thread.is_alive())
        self.assertEqual(h.result, 1, h.records)
        self.assertFalse(h.client.state.thread.is_alive())

    def test_idle_quit_reports_playing_before_quit(self):
        h, control, lines = self.make()
        self.command(control, "QUIT")
        deadline = time.monotonic()+2
        while h.client.state.pending is None and time.monotonic() < deadline:
            time.sleep(0.001)
        h.send("MATCH 0 A P2")
        self.assertEqual(read(control, lines), "STATE P1 PLAYING 0")
        self.assertEqual(read(control, lines), "STATE P1 QUIT")
        self.assertEqual(h.line(), "QUIT 0")
        h.send("BYE")
        self.assertEqual(read(control, lines), "STATE P1 END")
        h.thread.join(3)
        self.assertEqual(sum(r[:2] == ("QUIT", "WARN") for r in h.records), 1)
