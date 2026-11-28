"""env의 Peer 네 개를 별도 프로세스로 실행한다."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """과제 도구의 CLI 입력 오류는 요구된 종료 코드 1로 보고한다."""
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv: list[str] | None = None) -> int:
    """env의 Peer 네 개를 별도 프로세스로 기동하고 종료 코드를 모은다."""
    parser = _Parser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--policy", choices=("random", "rarest"))
    parser.add_argument("tracker_ip")
    parser.add_argument("port", type=int)
    args = parser.parse_args(argv)
    try:
        env_path = Path(args.env).resolve()
        env = json.loads(env_path.read_text(encoding="utf-8"))
        policy = args.policy or env.get("download", {}).get("policy")
        if policy not in ("random", "rarest"):
            raise ValueError("policy가 env에 없으므로 --policy를 지정해야 함")
        if not 1 <= args.port <= 65535:
            raise ValueError("port는 1~65535여야 함")
        peers = env["peers"]
        if len(peers) != 4:
            raise ValueError("env에는 Peer 네 개가 필요함")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 1

    # 모든 자식에 같은 env·Tracker 주소·선택 정책을 넘긴다.
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for peer in peers:
            command = [args.python, "-m", "src.peer", "--env", str(env_path), "--id", str(peer["id"])]
            if args.policy is not None or env.get("download", {}).get("policy") is None:
                command.extend(("--policy", policy))
            command.extend((args.tracker_ip, str(args.port)))
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL)
            processes.append((str(peer["id"]), process))
        codes = {peer_id: process.wait() for peer_id, process in processes}
    except KeyboardInterrupt:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            process.wait()
        return 1
    except OSError as exc:
        print(f"Peer를 실행하지 못함: {exc}", file=sys.stderr)
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            process.wait()
        return 1

    # destroy 희생자는 3, 생존자는 0일 때만 묶음 실행을 성공으로 본다.
    victim = (env.get("destroy") or {}).get("peer")
    valid = all(code == (3 if peer_id == victim else 0) for peer_id, code in codes.items())
    for peer_id, code in codes.items():
        print(f"{peer_id}: exit {code}")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
