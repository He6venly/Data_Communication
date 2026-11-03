"""같은 Worker 명령을 N개의 독립 프로세스로 실행한다."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time


VALID_COUNT = (1, 4, 5, 6, 7, 8)


# 실행 중인 자식 Worker를 종료하고 남은 프로세스까지 정리한다.
def stop_processes(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
    for process in processes:
        if process.poll() is None:
            process.wait()


# 실패한 Worker의 임시 stdout과 stderr 내용을 출력한다.
def show_diagnostics(files):
    for kind, k, path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text:
            print(f"--- Worker{k} {kind} ---", file=sys.stderr)
            print(text, end="" if text.endswith("\n") else "\n", file=sys.stderr)


# 같은 명령으로 N개 Worker를 실행하고 하나가 실패하면 전체를 종료한다.
def launch(count, command):
    if count not in VALID_COUNT:
        raise ValueError("Worker 수는 1 또는 4~8이어야 합니다")
    if not command:
        raise ValueError("-- 뒤에 실행할 명령이 필요합니다")

    processes = []
    handles = []
    diagnostic_files = []
    with tempfile.TemporaryDirectory(prefix="hw4_workers_") as temp_name:
        temp = Path(temp_name)
        try:
            for k in range(count):
                stdout_path = temp / f"worker{k}_stdout.txt"
                stderr_path = temp / f"worker{k}_stderr.txt"
                stdout = stdout_path.open("w", encoding="utf-8", newline="\n")
                stderr = stderr_path.open("w", encoding="utf-8", newline="\n")
                handles.extend((stdout, stderr))
                diagnostic_files.extend((("stdout", k, stdout_path),
                                         ("stderr", k, stderr_path)))
                processes.append(subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                                  shell=False))

            while True:
                codes = [process.poll() for process in processes]
                failed = [code for code in codes if code not in (None, 0)]
                if failed:
                    stop_processes(processes)
                    for handle in handles:
                        handle.close()
                    show_diagnostics(diagnostic_files)
                    return failed[0]
                if all(code == 0 for code in codes):
                    return 0
                time.sleep(0.05)
        except (KeyboardInterrupt, OSError):
            stop_processes(processes)
            raise
        finally:
            for handle in handles:
                if not handle.closed:
                    handle.close()


# Worker 수와 -- 뒤의 실제 실행 명령을 입력받는다.
def parser():
    result = argparse.ArgumentParser(description="HW4 Worker 프로세스 실행 보조")
    result.add_argument("--count", type=int, choices=VALID_COUNT, required=True)
    result.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- 뒤에 실제 Worker 명령을 적습니다")
    return result


# 실행 보조 결과를 자식 프로세스 종료 코드로 반환한다.
def main(argv=None):
    args = parser().parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        return launch(args.count, command)
    except KeyboardInterrupt:
        print("Worker 실행이 중단됐습니다", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"Worker 실행 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

