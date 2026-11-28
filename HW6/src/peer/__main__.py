import signal
import sys
from pathlib import Path
from threading import Event
from time import monotonic

from src.common.contracts import ConfigurationError
from .client import Peer
from .config import parse_args
from .log import EventLog


def main(argv=None):
    """공개 인터페이스에 맞춰 저장소와 업로드 서버를 연결함."""
    try:
        args, env, peer = parse_args(argv)
        from src.storage.store import FileStore
        from src.upload.screen import StatusScreen
        from src.upload.server import UploadServer
    except (ConfigurationError, ImportError) as exc:
        print(exc, file=sys.stderr)
        return 1
    root, started_at, stopping = Path.cwd().resolve(), monotonic(), Event()
    try:
        log = EventLog(peer_id=args.id, root=root, started_at=started_at)
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        store = FileStore(env=env, peer_id=args.id, root=root, emit=log.event)
        upload = UploadServer(env=env, peer_id=args.id, store=store, stopping=stopping, emit=log.event)
        screen = StatusScreen(stopping=stopping, period_sec=float(env["timing"]["status_every_sec"]))
        client = Peer(args, env, peer, store, upload, screen, log, stopping, started_at)
        previous = {}
        try:
            for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
                if sig is not None:
                    previous[sig] = signal.signal(sig, lambda *_: client.interrupted.set())
            return client.run()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
