"""FileStore의 청크·해시·결과 저장 동작을 확인한다."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from src.common.contracts import FileState, InvalidChunkError, NoChunkError
from src.storage.store import FileStore


def make_env(data: bytes) -> dict:
    """마지막 청크가 짧은 테스트용 env를 만든다."""
    return {
        "chunk_size": 8,
        "peers": [
            {"id": "P1", "dir": "p1", "host": "127.0.0.1", "port": 7101, "up_kbps": 100, "down_kbps": 100},
            {"id": "P2", "dir": "p2", "host": "127.0.0.1", "port": 7102, "up_kbps": 100, "down_kbps": 100},
        ],
        "files": [{"name": "sample.bin", "size": len(data), "origin": "P1", "sha256": hashlib.sha256(data).hexdigest()}],
    }


class FileStoreTests(unittest.TestCase):
    """예약부터 최종 결과 파일까지 저장소 경계를 검사한다."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hw6-store-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b"abcdefghijk"
        self.events: list[tuple[str, dict]] = []
        self.store = FileStore(
            env=make_env(self.data),
            peer_id="P2",
            root=self.root,
            emit=lambda ev, **fields: self.events.append((ev, fields)),
        )
        self.store.initialize()
        self.addCleanup(self.store.finalize)
        self.store.prepare_download("sample.bin")

    def test_duplicate_reservation_partial_chunk_and_finalize(self) -> None:
        """중복 예약을 막고 8바이트와 3바이트를 정확히 받아 완성한다."""
        first = self.store.reserve("sample.bin", 0)
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.reserve("sample.bin", 0))
        with self.assertRaises(InvalidChunkError):
            self.store.commit(first, b"short", "P1")

        result = self.store.commit(first, b"abcdefgh", "P1")
        self.store.release(first)
        self.assertTrue(result.accepted)
        self.assertFalse(result.complete_now)
        self.assertEqual(self.store.read_chunk("sample.bin", 0), b"abcdefgh")
        with self.assertRaises(NoChunkError):
            self.store.read_chunk("sample.bin", 1)

        last = self.store.reserve("sample.bin", 1)
        result = self.store.commit(last, b"ijk", "P1")
        self.store.release(last)
        self.assertTrue(result.complete_now)
        self.assertEqual(result.state, FileState.SEED)
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot.files[0].bitmap, "11")
        self.assertEqual(snapshot.received_bytes, 11)
        self.assertEqual(self.store.read_chunk("sample.bin", 1), b"ijk")
        self.assertEqual([ev for ev, _ in self.events[-2:]], ["RECV", "HASH"])

        final = self.store.finalize()
        self.assertEqual(final.files[0].bitmap, "11")
        self.assertEqual((self.root / "p2" / "sample.bin").read_bytes(), self.data)
        self.assertEqual((self.root / "p2" / "sample.bin.bitmap").read_text(), "11")
        self.assertFalse((self.root / "p2" / "sample.bin.lost").exists())
        self.assertEqual(self.store.finalize(), final)

    def test_pause_invalidates_old_reservation(self) -> None:
        """pause가 예약 세대를 바꾸면 이전 토큰의 디스크 기록을 공개하지 않는다."""
        old = self.store.reserve("sample.bin", 0)
        self.store.pause()
        stale = self.store.commit(old, b"abcdefgh", "P1")
        self.assertEqual(stale.reason, "STALE")
        self.assertEqual(self.store.snapshot().files[0].bitmap, "00")
        self.store.resume()
        new = self.store.reserve("sample.bin", 0)
        self.assertNotEqual(old.serial, new.serial)
        self.store.release(new)

    def test_hash_failure_retries_then_marks_corrupt(self) -> None:
        """해시 불일치 뒤 한 번 재수신하고 두 번째 실패를 corrupt로 보존한다."""
        for idx, data in enumerate((b"XXXXXXXX", b"YYY")):
            token = self.store.reserve("sample.bin", idx)
            self.store.commit(token, data, "P1")
            self.store.release(token)
        snap = self.store.snapshot().files[0]
        self.assertEqual(snap.state, FileState.DOWN)
        self.assertEqual(snap.bitmap, "00")
        self.assertEqual(snap.hash_failures, 1)

        for idx, data in enumerate((b"MMMMMMMM", b"NNN")):
            token = self.store.reserve("sample.bin", idx)
            self.store.commit(token, data, "P1")
            self.store.release(token)
        snap = self.store.snapshot().files[0]
        self.assertEqual(snap.state, FileState.FAILED)
        self.assertEqual(snap.bitmap, "00")
        self.assertEqual((self.root / "p2" / "sample.bin.corrupt").read_bytes(), b"MMMMMMMMNNN")
        self.assertEqual([fields["action"] for ev, fields in self.events if ev == "CORRUPT"], ["redownload", "give_up"])

        self.store.finalize()
        self.assertEqual((self.root / "p2" / "sample.bin.lost").read_text(), "0-1")


if __name__ == "__main__":
    unittest.main()
