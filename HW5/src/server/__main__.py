import argparse
import sys
from pathlib import Path

from .league import ServerConfig, serve


def main() -> int:
    parser = argparse.ArgumentParser(description="HW5 Card Duel League Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9500)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--tables", type=int, choices=range(1, 6), required=True)
    parser.add_argument("--timeout", type=int, default=3000, help="stage timeout in milliseconds")
    parser.add_argument("--run", choices=("A", "B", "C", "D"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        serve(ServerConfig(args.host, args.port, args.seed, args.tables, args.timeout, args.run, args.out))
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"Server: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
