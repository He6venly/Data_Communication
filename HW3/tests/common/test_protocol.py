import unittest

from hw3.common.protocol import Message, ProtocolError, encode, parse


class ProtocolTests(unittest.TestCase):
    def test_every_message_round_trips(self) -> None:
        messages = [
            Message("HELLO", ("1", "127.0.0.1", "7001")),
            Message("RING_OK", ("1",)),
            Message("HB", ("10",)),
            Message("REQ", ("2",)),
            Message("RESULT", ("999", "3", "0")),
            Message("REJOIN", ("4",)),
            Message("RING", ("2", "localhost", "7002")),
            Message("START"),
            Message("ASSIGN", ("0", "1")),
            Message("NO_TASK"),
            Message("TAKEOVER", ("8", "2", "from=1")),
            Message("ACK", ("8",)),
            Message("REJECT_STALE", ("8", "DEAD")),
            Message("REJECT_STALE", ("8", "DONE")),
            Message("REJECT_STALE", ("8", "EPOCH")),
            Message("WELCOME"),
            Message("RETRY_LATER"),
            Message("BYE"),
            Message("PEER", ("5",)),
            Message("CKPT", ("8", "2", "9", "100")),
            Message("LAUNCHER"),
            Message("CRASH"),
            Message("RESTART"),
            Message("READY", ("6",)),
            Message("REJOINED", ("6",)),
        ]
        for message in messages:
            with self.subTest(message=message):
                wire = encode(message)
                self.assertNotIn("\n", wire)
                self.assertEqual(message, parse(wire))

    def test_field_count_and_range_errors(self) -> None:
        bad_lines = [
            "HELLO 1 127.0.0.1",
            "READY",
            "HB 0",
            "HB 11",
            "RESULT 1000 1 1",
            "RESULT 0 0 1",
            "RESULT 0 1 -1",
            "ASSIGN 0 2",
            "TAKEOVER 0 1 from=1",
            "CKPT 0 1 0 1",
            "CKPT 0 1 10 1",
            "RING 1 host 0",
            "RING 1 host 65536",
        ]
        for line in bad_lines:
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                parse(line)

    def test_rejects_invalid_reason_and_takeover_source(self) -> None:
        for line in [
            "REJECT_STALE 1 OWNER",
            "TAKEOVER 1 2 3",
            "TAKEOVER 1 2 from=0",
            "TAKEOVER 1 2 FROM=3",
        ]:
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                parse(line)

    def test_rejects_cr_lf_injection_and_odd_spacing(self) -> None:
        for line in ["HB 1\nREQ 1", "HB 1\r", " HB 1", "HB  1", "HB\t1"]:
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                parse(line)
        with self.assertRaises(ProtocolError):
            encode(Message("HELLO", ("1", "host\nCRASH", "7001")))

    def test_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ProtocolError):
            parse("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
