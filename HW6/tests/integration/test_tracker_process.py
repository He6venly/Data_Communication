"""독립 Tracker와 실제 TCP 네 연결로 명령·장애·종료를 검사함."""

import json
from pathlib import Path
import socket
import time

from tracker_support import TCPCase, TrackerProcess, exchange, free_port, until


SIGNAL_WRAPPER = '''
import signal, threading, time
from pathlib import Path
from src.tracker.__main__ import main
def interrupt():
    while not Path('interrupt').exists(): time.sleep(.02)
    signal.raise_signal(signal.SIGTERM)
threading.Thread(target=interrupt, daemon=True).start()
raise SystemExit(main())
'''


class TrackerProcessTests(TCPCase):
    """명령 응답과 실제 생성된 JSONL·report·프로세스 종료를 대조함."""

    def test_fragmented_batched_requests_and_normal_replication(self):
        """분할·합친 요청과 잘못된 UTF-8 이후에도 네 피어가 정상 종료함."""
        child = self.start()
        probe = child.connect()
        probe.sock.sendall(b"LI")
        time.sleep(.02)
        probe.sock.sendall(b"ST\nHELLO P1\nBOGUS\n\xff\nLIST\n")
        self.assertEqual([probe.read_line() for _ in range(5)],
                         ["FILES 0", "OK", "ERR BADCMD", "ERR BADCMD", "FILES 0"])
        probe.close()
        peers = child.join()
        catalog = exchange(peers["P4"], "LIST")
        self.assertEqual(catalog, ("FILES 3", "a.bin 11 8 2 1", "b.bin 8 8 1 1", "c.bin 1 8 1 1"))
        p4 = self.env["peers"][3]
        self.assertEqual(exchange(peers["P4"], f"HAVE P4 {p4['port']} a.bin"), ("OK",))
        rows = exchange(peers["P4"], "PEERS a.bin")
        self.assertEqual(rows, ("PEERS 2", f"P1 {self.env['peers'][0]['host']} {self.env['peers'][0]['port']}",
                               f"P4 {p4['host']} {p4['port']}"))
        for pid, conn in peers.items():
            for file in self.env["files"]:
                bits = "1" * ((file["size"] + 7) // 8)
                sent, distinct = (5, len(bits)) if pid == file["origin"] else (0, 0)
                self.assertEqual(exchange(conn, f"REPORT {pid} {file['name']} {sent} {distinct} {bits}"), ("OK",))
        until(lambda: any(e["ev"] == "ALL_REPLICATED" for e in child.events()), timeout=3)
        idle = child.connect()
        idle.sock.sendall(b"HEART")
        for pid, conn in peers.items():
            self.assertEqual(exchange(conn, f"DONE {pid} FULL"), ("OK",))
        self.assertEqual(exchange(peers["P4"], "STATE"), ("STATE 4 4 ALLDONE",))
        for pid, conn in peers.items():
            self.assertEqual(exchange(conn, f"BYE {pid}"), ("OK",))
        result, events = self.check_result(child, 0)
        self.assertEqual(set(result["peers"].values()), {"BYE"})
        self.assertEqual(set(result["done_kind"].values()), {"FULL"})
        self.assertEqual(result["upstat_at_rep"]["a.bin"], [5, 2])
        self.assertEqual(result["dup_ratio"]["a.bin"], .6)
        self.assertTrue(all(t is not None for t in result["T_rep"].values()))
        self.assertEqual(sum(e["ev"] == "START" for e in events), 1)
        self.assertEqual(next(e["peers"] for e in events if e["ev"] == "START"), 4)
        self.assertFalse(any(e["ev"] == "DEAD" for e in events))
        with self.assertRaises(OSError):
            idle.read_line()

    def test_crash_rejoin_and_undone(self):
        """heartbeat 지시를 받은 연결을 끊었다 다시 참가해 한 번만 송신 기록함."""
        self.env["crashes"] = [dict(peer="P2", at_sec=0, duration_sec=.15)]
        child = self.start()
        peers = child.join()
        command = until(lambda: (r if (r := exchange(peers["P2"], "HEARTBEAT P2 0"))[0].startswith("CMD") else None))
        self.assertEqual(command, ("CMD DISCONNECT 0.15",))
        peers["P2"].close()
        time.sleep(.15)
        peers["P2"] = child.connect()
        self.assertEqual(exchange(peers["P2"], "HELLO P2"), ("OK",))
        self.assertEqual(exchange(peers["P2"], "HEARTBEAT P2 0"), ("OK",))
        self.assertEqual(exchange(peers["P1"], "DONE P1 PARTIAL a.bin:1"), ("OK",))
        self.assertEqual(exchange(peers["P1"], "UNDONE P1"), ("OK",))
        self.assertEqual(exchange(peers["P1"], "STATE"), ("STATE 0 4 WAIT",))
        for pid, conn in peers.items():
            exchange(conn, f"DONE {pid} FULL")
        for pid, conn in peers.items():
            self.assertEqual(exchange(conn, f"BYE {pid}"), ("OK",))
        result, events = self.check_result(child, 0)
        self.assertEqual(len(result["crashes_sent"]), 1)
        self.assertEqual(result["crashes_sent"][0]["sec"], .15)
        self.assertTrue(any(e["ev"] == "REJOIN" and e["id"] == "P2" for e in events))

    def test_destroy_waits_for_dead_then_partial_survivors_exit(self):
        """희생자는 BYE 없이 침묵하고 DEAD 뒤 생존자 PARTIAL이 정상 종료함."""
        self.env["timing"]["dead_sec"] = .65
        self.env["destroy"] = dict(peer="P3", trigger="time", value=0, replica_safe=False)
        child = self.start()
        peers = child.join()
        def destroyed():
            for pid in ("P1", "P2", "P4"):
                exchange(peers[pid], f"HEARTBEAT {pid} 0")
            result = exchange(peers["P3"], "HEARTBEAT P3 0")
            return result if result == ("CMD DESTROY",) else None
        until(destroyed)
        peers["P3"].close()
        for pid in ("P1", "P2", "P4"):
            self.assertEqual(exchange(peers[pid], f"DONE {pid} PARTIAL c.bin:1"), ("OK",))
        self.assertEqual(exchange(peers["P1"], "STATE"), ("STATE 3 4 WAIT",))
        def alldone():
            for pid in ("P1", "P2", "P4"):
                exchange(peers[pid], f"HEARTBEAT {pid} 0")
            return exchange(peers["P1"], "STATE") == ("STATE 3 3 ALLDONE",)
        until(alldone)
        for pid in ("P1", "P2", "P4"):
            self.assertEqual(exchange(peers[pid], f"BYE {pid}"), ("OK",))
        result, events = self.check_result(child, 0)
        self.assertEqual(result["peers"]["P3"], "DEAD")
        self.assertEqual(result["done_kind"], dict.fromkeys(["P1", "P2", "P4"], "PARTIAL"))
        self.assertEqual([e["id"] for e in events if e["ev"] == "DEAD"], ["P3"])
        self.assertGreater(result["T_dead"]["P3"], result["T_destroy"])

    def test_abort_deadline_and_early_bye(self):
        """deadline의 ABORT를 실제 STATE로 전달하고 전원 BYE 시 일찍 종료함."""
        self.env["timing"]["deadline_sec"] = .1
        child = self.start()
        peers = child.join()
        until(lambda: "ABORT deadline" in exchange(peers["P1"], "STATE")[0])
        for pid, conn in peers.items():
            self.assertEqual(exchange(conn, f"BYE {pid}"), ("OK",))
        result, _ = self.check_result(child, 2)
        self.assertEqual(result["abort"], "deadline")
        self.assertLess(result["T_exit"], 5)

    def test_abort_without_bye_exits_after_real_grace(self):
        """응답 없는 피어가 있어도 실제 15초 유예 뒤 프로세스가 종료함."""
        self.env["timing"].update(dead_sec=20, deadline_sec=.1)
        child = self.start()
        child.join()
        self.assertEqual(child.wait(timeout=19), 2, child.stderr())
        result, events = self.check_result(child, 2)
        self.assertEqual(result["abort"], "deadline")
        start = next(e["t"] for e in events if e["ev"] == "ABORT")
        self.assertGreaterEqual(events[-1]["t"] - start, 14.98)
        self.assertLess(result["T_exit"], 18)

    def test_signal_before_and_after_start(self):
        """실제 자식에서 SIGTERM을 발생시켜 START 전후 연결과 스레드를 정리함."""
        for joined in (False, True):
            with self.subTest(joined=joined):
                root = Path(self.directory.name) / str(joined)
                root.mkdir()
                child = TrackerProcess(root, self.env, wrapper=SIGNAL_WRAPPER)
                self.addCleanup(child.close)
                child.ready()
                if joined:
                    child.join()
                idle = child.connect()
                idle.sock.sendall(b"LIST")
                (root / "interrupt").touch()
                result, _ = self.check_result(child, 2)
                self.assertEqual(result["abort"], "interrupted")
                self.assertEqual(result["T_exit"] is not None, joined)
                with self.assertRaises(OSError):
                    idle.read_line()

    def test_cli_port_override_and_bind_failure(self):
        """CLI 포트를 우선 사용하고 bind 실패는 report 없이 EXIT 1로 기록함."""
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            self.env["tracker"]["port"] = occupied.getsockname()[1]
            port = free_port()
            child = self.start(wrapper=SIGNAL_WRAPPER, extra_args=[str(port)])
            child.port = port
            exchange(child.connect(), "HELLO P1")
            (child.root / "interrupt").touch()
            self.check_result(child, 2)
            failed_root = child.root / "failed"
            failed_root.mkdir()
            failed = TrackerProcess(failed_root, self.env)
            self.addCleanup(failed.close)
            self.assertEqual(failed.wait(), 1)
            self.assertEqual(failed.events()[-1]["code"], 1)
            self.assertFalse((failed.root / "report.json").exists())

    def test_report_failure_returns_error_and_preserves_previous_file(self):
        """저장 실패를 성공으로 숨기지 않고 기존 report와 마지막 EXIT를 보존함."""
        wrapper = '''
import src.tracker.__main__ as entry
def fail(*args): raise OSError('report write failed')
entry.write_report = fail
raise SystemExit(entry.main())
'''
        child = self.start(wrapper=wrapper)
        path = child.root / "report.json"
        path.write_text('{"previous":true}', encoding="utf-8")
        peers = child.join()
        for pid, conn in peers.items():
            exchange(conn, f"DONE {pid} FULL")
        for pid, conn in peers.items():
            self.assertEqual(exchange(conn, f"BYE {pid}"), ("OK",))
        self.assertEqual(child.wait(), 2)
        self.assertEqual(json.loads(path.read_text()), {"previous": True})
        self.assertEqual(child.events()[-1]["code"], 2)
        self.assertTrue(any(e["ev"] == "ERROR" and e.get("operation") == "report" for e in child.events()))

    def test_log_io_failure_is_fatal_and_exit_is_last(self):
        """handler의 로그 I/O 오류를 단순 TCP 단절로 숨기지 않음."""
        wrapper = '''
from src.tracker.log import EventLog
from src.tracker.__main__ import main
original = EventLog.event
def fail_join(self, event, **fields):
    if event == 'JOIN': raise OSError('log write failed')
    return original(self, event, **fields)
EventLog.event = fail_join
raise SystemExit(main())
'''
        child = self.start(wrapper=wrapper)
        with self.assertRaises(OSError):
            exchange(child.connect(), "HELLO P1")
        result, events = self.check_result(child, 2)
        self.assertEqual(result["abort"], "server_error")
        self.assertTrue(any(e["ev"] == "ERROR" for e in events))

    def test_bad_cli_and_env_exit_one_before_log(self):
        """잘못된 포트·인자·env를 실제 진입점에서 exit 1로 처리함."""
        for name, arguments, version in [("port", ["bad"], 1), ("zero", ["0"], 1),
                                         ("option", ["--unknown"], 1), ("env", [], 2)]:
            with self.subTest(name=name):
                root = Path(self.directory.name) / name
                root.mkdir()
                self.env["version"] = version
                child = TrackerProcess(root, self.env, extra_args=arguments)
                self.addCleanup(child.close)
                self.assertEqual(child.wait(), 1)
                self.assertIn("사용법", child.stderr())
                self.assertFalse((root / "logs").exists())
                self.assertFalse((root / "report.json").exists())

