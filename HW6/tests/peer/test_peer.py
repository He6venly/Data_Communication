import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
from socketserver import StreamRequestHandler, ThreadingTCPServer
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from time import monotonic
import unittest

from src.common.contracts import CommitResult, FileSnapshot, FileState, Reservation, StoreSnapshot
from src.common.transport import Conn
from src.peer.client import Peer
from src.peer.config import ConfigurationError, parse_args
from src.peer.control import Control
from src.peer.download import read_chunk
from src.peer.log import EventLog
from src.peer.selection import Selection
from src.peer.tracker_link import ProtocolError, TrackerLink


def config():
    return {
        "chunk_size": 8, "run": "sandbox", "seed": 1, "description": "loopback fixture",
        "files": [{"name": "data", "size": 11, "origin": "P1"}],
        "peers": [{"id": f"P{i}", "host": "127.0.0.1", "port": 7000+i, "up_kbps": 8192, "down_kbps": 8192}
                  for i in range(1, 5)],
        "download": {"workers": 4, "per_peer_max": 1, "policy_seed": 13},
        "timing": {"tracker_lost_sec": .4, "heartbeat_sec": .09, "peers_refresh_sec": .1,
                   "bitmap_refresh_sec": .1, "stall_sec": .12, "ban_sec": 1, "fail_limit": 2},
    }


class Store:
    """메모리에서 공개 예약·bitmap·세대 동작을 재현함."""

    def __init__(self):
        self.lock = Lock()
        self.data = FileSnapshot(name="data", size=11, chunk_size=8, nchunks=2, origin="P1", sha256="",
                                 state=FileState.DOWN, prepared=False, bitmap="00", in_progress=(),
                                 sent=0, distinct=0, sources=(), received_bytes=0, sent_bytes=0, hash_failures=0)
        self.generation = self.serial = 0
        self.paused = False
        self.tokens = {}
        self.received = {}
        self.finalized = False

    def initialize(self):
        pass

    def snapshot(self):
        with self.lock:
            return StoreSnapshot(peer_id="P4", generation=self.generation, paused=self.paused,
                                 downloaded_have=self.data.bitmap.count("1"), received_bytes=self.data.received_bytes,
                                 sent_bytes=0, files=(replace(self.data, in_progress=tuple(self.tokens)),))

    def prepare_download(self, file):
        with self.lock:
            self.data = replace(self.data, prepared=True)
            return self.data

    def reserve(self, file, idx):
        with self.lock:
            if self.paused or self.data.state != FileState.DOWN or self.data.bitmap[idx] == "1" or idx in self.tokens:
                return None
            self.serial += 1
            token = Reservation(file=file, idx=idx, serial=self.serial, generation=self.generation)
            self.tokens[idx] = token
            return token

    def release(self, token):
        with self.lock:
            if self.tokens.get(token.idx) == token:
                del self.tokens[token.idx]

    def commit(self, token, data, src):
        with self.lock:
            if self.tokens.get(token.idx) != token:
                return CommitResult(accepted=False, state=self.data.state, complete_now=False, reason="STALE")
            self.received[token.idx] = data
            bits = list(self.data.bitmap)
            bits[token.idx] = "1"
            complete = all(b == "1" for b in bits)
            state = FileState.SEED if complete else FileState.DOWN
            self.data = replace(self.data, bitmap="".join(bits), state=state,
                                received_bytes=sum(map(len, self.received.values())),
                                sources=((src, len(self.received)),))
            return CommitResult(accepted=True, state=state, complete_now=complete, reason=None)

    def set_stalled(self, file, stalled):
        with self.lock:
            before, after = (FileState.DOWN, FileState.STALLED) if stalled else (FileState.STALLED, FileState.DOWN)
            if self.data.state != before:
                return False
            self.data = replace(self.data, state=after)
            return True

    def pause(self):
        with self.lock:
            self.paused = True
            self.generation += 1
            self.tokens.clear()

    def resume(self):
        with self.lock:
            self.paused = False

    def finalize(self):
        self.finalized = True
        return self.snapshot()


class Upload:
    def __init__(self):
        self.calls = []

    def start(self): self.calls.append("start")
    def offline(self): self.calls.append("offline")
    def online(self): self.calls.append("online")
    def stop(self, seconds): self.calls.append(seconds)


class Screen:
    def start(self, snapshot, recent): self.view = snapshot()
    def stop(self): pass


class Server(ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, handler):
        self.respond = handler
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(StreamRequestHandler):
    def handle(self):
        try:
            while row := self.rfile.readline():
                response = self.server.respond(row.decode().strip())
                if response is None:
                    return
                for piece in response if isinstance(response, tuple) else (response,):
                    self.wfile.write(piece)
        except OSError:
            pass


class PeerTests(unittest.TestCase):
    def serve(self, handler):
        server = Server(handler)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(cleanup)
        return server.server_address

    def test_tracker_multiline_and_reconnect_after_partial_eof(self):
        commands = []
        def handler(row):
            commands.append(row)
            if row == "LIST":
                if commands.count(row) == 1:
                    return b"FILES 1\nda", b"ta 11 8 2 1\n"
                return b"FILES 1\n" if commands.count(row) == 2 else b"FILES 0\n"
            return b"OK\n"
        address = self.serve(handler)
        link = TrackerLink(address, "P4", 1, 4)
        self.addCleanup(link.close)
        self.assertEqual(link.request("LIST"), ("FILES 1", ("data 11 8 2 1",)))
        self.assertEqual(link.request("HEARTBEAT P4 0"), ("OK", ()))
        with self.assertRaises(OSError):
            link.request("LIST", timeout=.15)
        self.assertEqual(link.request("LIST"), ("FILES 0", ()))
        self.assertEqual(commands.count("HELLO P4"), 2)

    def test_data_boundary_and_bad_index_length(self):
        for wire in (b"DATA 1 3\nA\nBOK\n", b"DATA 0 3\n", b"DATA 1 -1\n", b"DATA 1 8\n"):
            with self.subTest(wire=wire):
                a, b = socket.socketpair()
                with a, b:
                    a.sendall(wire)
                    conn = Conn(b)
                    if b"A\nB" in wire:
                        self.assertEqual(read_chunk(conn, 1, 3), b"A\nB")
                        self.assertEqual(conn.read_line(), "OK")
                    else:
                        with self.assertRaises(ProtocolError):
                            read_chunk(conn, 1, 3)

    def test_rarest_limit_and_ban(self):
        selection = Selection(config(), "rarest", 10)
        store = Store()
        store.prepare_download("data")
        selection.update("data", "P1", ("127.0.0.1", 7001), "11")
        selection.update("data", "P2", ("127.0.0.1", 7002), "10")
        token, peer, _, size = selection.choose(store)
        self.assertEqual((token.idx, peer, size), (1, "P1", 3))
        other, other_pid, _, _ = selection.choose(store)
        self.assertEqual((other.idx, other_pid), (0, "P2"))
        self.assertIsNone(selection.choose(store))
        store.release(token)
        self.assertFalse(selection.finish("data", peer, "fail"))
        selection.update("data", "P1", ("127.0.0.1", 7001), "11")
        token, peer, _, _ = selection.choose(store)
        store.release(token)
        self.assertTrue(selection.finish("data", peer, "fail"))
        selection.update("data", "P1", ("127.0.0.1", 7001), "11")
        self.assertIsNone(selection.choose(store))

    def run_peer(self, env, address):
        store, upload = Store(), Upload()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            started = monotonic()
            log = EventLog(peer_id="P4", root=root, started_at=started)
            args = argparse.Namespace(env=Path("fixture.json"), policy="rarest", host=address[0], port=address[1])
            stopping = Event()
            client = Peer(args, env, env["peers"][-1], store, upload, Screen(), log, stopping, started)
            result = []
            thread = Thread(target=lambda: result.append(client.run()), daemon=True)
            thread.start()
            thread.join(5)
            if thread.is_alive():
                client.interrupted.set()
                client.link.close()
                thread.join(7)
            self.assertFalse(thread.is_alive())
            self.assertTrue(all(not t.is_alive() for t in client.pool.threads))
            self.assertFalse(client.control_thread.is_alive())
            log.close()
            records = [json.loads(row) for row in (root/"logs/P4.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["ev"], "START")
            self.assertEqual(records[-1]["ev"], "EXIT")
            self.assertEqual(records[-1]["code"], result[0])
        return result[0], store, upload, records

    def test_tcp_crash_rejoin_have_retry_and_full_shutdown(self):
        commands = []
        visits = []
        first_get = Event()
        sent_crash = Event()
        def data_server(row):
            if row.startswith("BITMAP"):
                return b"BITMAP 2 11\n"
            idx = int(row.split()[-1])
            visits.append(idx)
            if len(visits) == 1:
                first_get.set()
                sent_crash.wait(2)
                # 오프라인 전환 때 읽고 있던 연결이 먼저 닫히도록 응답을 늦춤.
                Event().wait(.24)
            payload = (b"abcd\n\x00gh", b"ijk")[idx]
            return f"DATA {idx} {len(payload)}\n".encode()+payload
        origin_addr = self.serve(data_server)

        def tracker(row):
            commands.append((monotonic(), row))
            lines = [s for _, s in commands]
            if row.startswith("HEARTBEAT") and first_get.is_set() and not sent_crash.is_set():
                sent_crash.set()
                return b"CMD DISCONNECT 0.12\n"
            if row == "LIST":
                return b"FILES 0\n" if lines.count(row) == 1 else b"FILES 1\ndata 11 8 2 1\n"
            if row.startswith("HAVE") and lines.count(row) == 1:
                return b"ERR NOFILE\n"
            if row.startswith("PEERS"):
                return f"PEERS 1\nP1 {origin_addr[0]} {origin_addr[1]}\n".encode()
            if row == "STATE":
                return b"STATE 1 1 ALLDONE\n" if "DONE P4 FULL" in lines else b"STATE 0 1 WAIT\n"
            return b"OK\n"
        env = config()
        env["peers"][0].update(host=origin_addr[0], port=origin_addr[1])
        code, store, upload, logs = self.run_peer(env, self.serve(tracker))
        self.assertEqual(code, 0, logs)
        self.assertEqual(store.received, {0: b"abcd\n\x00gh", 1: b"ijk"})
        self.assertEqual(len(visits), 3)
        self.assertEqual(set(visits), {0, 1})
        self.assertEqual(upload.calls, ["start", "offline", "online", 3.0])
        events = [row["ev"] for row in logs]
        self.assertLess(events.index("CRASH"), events.index("REJOIN"))
        self.assertNotIn("FAIL", events)
        self.assertLess(events.index("COMPLETE"), events.index("DONE"))
        hellos = [t for t, line in commands if line == "HELLO P4"]
        self.assertGreaterEqual(hellos[1]-hellos[0], .12)
        self.assertIn("BYE P4", [line for _, line in commands])

    def test_destroy_saves_without_bye(self):
        commands = []
        def handler(row):
            commands.append(row)
            return b"CMD DESTROY\n" if row.startswith("HEARTBEAT") else b"OK\n"
        code, store, upload, logs = self.run_peer(config(), self.serve(handler))
        self.assertEqual(code, 3)
        self.assertTrue(store.finalized)
        self.assertNotIn("BYE P4", commands)
        self.assertEqual(upload.calls[-1], 0.0)
        self.assertEqual(logs[-2]["ev"], "DESTROY")

    def test_tracker_lost_from_start(self):
        code, store, _, logs = self.run_peer(config(), self.serve(lambda row: None))
        self.assertEqual(code, 2)
        self.assertTrue(store.finalized)
        self.assertEqual(logs[-2]["reason"], "tracker_lost")

    def test_stalled_then_undone_when_source_returns(self):
        env, store = config(), Store()
        store.prepare_download("data")
        selection = Selection(env, "rarest", 13)
        events = []
        class Link:
            def request(self, command, timeout):
                return "OK", ()
        control = Control(env, env["peers"][-1], Link(), store, selection, None,
                          lambda ev, **fields: events.append((ev, fields)))
        control.update_done(store.snapshot().files, 1)
        control.update_done(store.snapshot().files, 1.2)
        self.assertEqual(events[-1], ("DONE", {"kind": "PARTIAL", "detail": "data:2"}))
        selection.update("data", "P1", ("127.0.0.1", 7001), "01")
        control.update_done(store.snapshot().files, 1.3)
        self.assertEqual([ev for ev, _ in events], ["STALLED", "DONE", "UNSTALLED", "UNDONE"])

    def test_public_envs_and_policy_override(self):
        kit = Path(os.environ.get("HW6_KIT_DIR", "../제공 파일 및 명세 설명/hw6_student_kit/Python"))
        for run in ("DEV", "A", "B", "C1", "C2", "C3"):
            base = ["--env", str(kit/"envs"/f"{run}.json"), "--id", "P4", "127.0.0.1", "6000"]
            args, _, _ = parse_args(["--policy", "rarest", *base])
            self.assertEqual(args.policy, "rarest")
            if run == "C3":
                with self.assertRaises(ConfigurationError):
                    parse_args(base)
            else:
                args, env, _ = parse_args(base)
                self.assertEqual(args.policy, env["download"]["policy"])
