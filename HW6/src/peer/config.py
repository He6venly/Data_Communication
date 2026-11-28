import argparse
from pathlib import Path

from src.common.contracts import ConfigurationError
from src.tracker.config import load_env, port_number


class Parser(argparse.ArgumentParser):
    def error(self, message):
        """인자 오류를 과제의 종료 코드 1로 처리함."""
        raise ConfigurationError(f"{self.format_usage().strip()}\n{message}", operation="cli")


def parse_args(argv=None):
    """env를 읽고 내 피어와 실제 적용할 정책을 정함."""
    parser = Parser(description="HW6 Mini-Torrent Peer")
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--id", required=True)
    parser.add_argument("--policy", choices=("random", "rarest"))
    parser.add_argument("host")
    parser.add_argument("port", type=port_number)
    args = parser.parse_args(argv)
    env = load_env(args.env)
    peer = next((p for p in env["peers"] if p["id"] == args.id), None)
    if peer is None or not args.host.strip():
        parser.error("unknown peer id or empty Tracker host")
    args.policy = args.policy or env["download"]["policy"]
    if args.policy is None:
        parser.error("--policy is required for this env")
    return args, env, peer
