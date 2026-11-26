import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from src.common.contracts import ConfigurationError
from src.tracker.config import load_env, parse_args, validate_env


KIT = Path(os.environ.get("HW6_KIT_DIR", Path(__file__).resolve().parents[3] / "제공 파일 및 명세 설명/hw6_student_kit/Python"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = json.loads((KIT / "envs/DEV.json").read_text(encoding="utf-8"))

    def test_public_scenarios_unchanged(self):
        for name in ("DEV", "A", "B", "C1", "C2", "C3"):
            with self.subTest(name=name):
                path = KIT / "envs" / f"{name}.json"
                before = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(load_env(path), before)

    def test_variable_env_and_short_chunk(self):
        e = self.env
        e["chunk_size"] = 8
        e["files"] = [dict(name="unit.bin", size=11, origin="P4", sha256="a" * 64)]
        e["progress_total_chunks"] = 6
        e["tracker"]["port"] = 6201
        e["timing"]["dead_sec"] = 0.3
        e["seed"] = -101
        e["download"]["policy_seed"] = -999
        before = copy.deepcopy(e)
        self.assertIs(validate_env(e), e)
        self.assertEqual(e, before)

    def test_invalid_inputs(self):
        mutations = [
            lambda e: e.update(version=True),
            lambda e: e.update(version=2),
            lambda e: e.update(chunk_size=0),
            lambda e: e.update(progress_total_chunks=1),
            lambda e: e["peers"][1].update(id="P1"),
            lambda e: e["peers"][1].update(port=e["peers"][0]["port"]),
            lambda e: e["peers"][0].update(up_kbps=float("nan")),
            lambda e: e["timing"].update(fail_limit=1.5),
            lambda e: e["files"][0].update(sha256="Z" * 64),
            lambda e: e["files"][0].update(origin="P9"),
            lambda e: e["files"][0].update(origin=[]),
            lambda e: e["files"][0].update(name="../outside"),
            lambda e: e["download"].update(policy="fastest"),
            lambda e: e["crashes"][0].update(peer="P9"),
            lambda e: e["crashes"][0].update(peer={}),
            lambda e: e.update(destroy=dict(peer="P1", trigger="progress", value=2, replica_safe=True)),
            lambda e: e.update(destroy=dict(peer="P1", trigger="time", value=2, replica_safe=1)),
        ]
        for i, mutation in enumerate(mutations):
            with self.subTest(i=i):
                e = copy.deepcopy(self.env)
                mutation(e)
                with self.assertRaises(ConfigurationError):
                    validate_env(e)

    def test_cli_errors_and_port_override(self):
        args = parse_args(["--env", "path with space/env.json", "6100"])
        self.assertEqual(args.port, 6100)
        self.assertEqual(args.env, Path("path with space/env.json"))
        self.assertIsNone(parse_args(["--env", "x"]).port)
        for args in ([], ["--env", "x", "bad"], ["--env", "x", "0"], ["--env", "x", "65536"], ["--env", "x", "--unknown"]):
            with self.subTest(args=args), self.assertRaises(ConfigurationError):
                parse_args(args)

    def test_unreadable_or_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env.json"
            for content in (b"{broken", b"\xff", b"[]"):
                path.write_bytes(content)
                with self.assertRaises(ConfigurationError):
                    load_env(path)
            with self.assertRaises(ConfigurationError):
                load_env(path.with_name("missing.json"))
