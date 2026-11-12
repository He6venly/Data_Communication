import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


STRATEGIES = {"RANDOM", "MATCH", "PLUS1", "BIGSMALL", "TEAM"}


@dataclass(frozen=True)
class PlayerConfig:
    player: int
    strategy: str
    fault: str | None = None


# kit 설정 파일의 열 수, 번호, 전략, 중복 여부를 확인한다.
def read_config(path: Path) -> list[PlayerConfig]:
    configs = []
    for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        fields = raw.split()
        if not fields:
            continue
        if len(fields) not in (2, 3):
            raise ValueError(f"line {line_number}: expected 2 or 3 fields")
        try:
            player = int(fields[0])
        except ValueError as error:
            raise ValueError(f"line {line_number}: invalid player number") from error
        strategy = fields[1]
        if player not in range(1, 11):
            raise ValueError(f"line {line_number}: player number must be 1..10")
        if strategy not in STRATEGIES:
            raise ValueError(f"line {line_number}: unknown strategy {strategy}")
        fault = fields[2] if len(fields) == 3 else None
        configs.append(PlayerConfig(player, strategy, fault))

    players = [config.player for config in configs]
    if sorted(players) != list(range(1, 11)):
        raise ValueError("config must contain P1..P10 exactly once")
    return configs


# 각 Player를 독립 프로세스로 실행할 명령 목록을 만든다.
def build_commands(
    configs: list[PlayerConfig], host: str, port: int, think: str,
    run_name: str, out: Path, crasher: str | None,
) -> list[list[str]]:
    commands = []
    for config in configs:
        command = [
            sys.executable, "-B", "-m", "src.player",
            "--host", host,
            "--port", str(port),
            "--id", str(config.player),
            "--strategy", config.strategy,
            "--think", think,
            "--run", run_name,
            "--out", str(out),
        ]
        if config.fault:
            command.extend(("--fault", config.fault))
        if crasher:
            command.extend(("--crasher", crasher))
        commands.append(command)
    return commands


# 열 개 프로세스를 시작하고 하나라도 실패하면 나머지도 종료한다.
def launch(commands: list[list[str]], cwd: Path) -> int:
    processes = [subprocess.Popen(command, cwd=cwd) for command in commands]
    try:
        while processes:
            for process in list(processes):
                result = process.poll()
                if result is None:
                    continue
                processes.remove(process)
                if result != 0:
                    for running in processes:
                        running.terminate()
                    for running in processes:
                        running.wait()
                    return result
            if processes:
                time.sleep(0.05)
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait()
        return 130
    return 0


# launcher 실행 인자를 읽고 원본 설정으로 Player 열 명을 실행한다.
def main() -> int:
    parser = argparse.ArgumentParser(description="Launch ten HW5 Player processes")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--think", default="18,22")
    parser.add_argument("--run", choices=("A", "B", "C", "D"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--crasher")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.run == "D" and not args.crasher:
        parser.error("Run D requires --crasher HOST:PORT")
    if args.run != "D" and args.crasher:
        parser.error("--crasher is only used for Run D")

    try:
        configs = read_config(args.config)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    commands = build_commands(
        configs, args.host, args.port, args.think, args.run, args.out, args.crasher,
    )
    return launch(commands, Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    sys.exit(main())
