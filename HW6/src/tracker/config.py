"""배포 env를 변경하지 않고 Tracker 실행 입력을 검증함."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
from pathlib import Path
import re
from typing import Any

from src.common.contracts import ConfigurationError


TIMING_KEYS = (
    "heartbeat_sec", "bitmap_refresh_sec", "peers_refresh_sec", "dead_sec",
    "stall_sec", "hang_sec", "deadline_sec", "status_every_sec", "fail_limit",
    "ban_sec", "report_stale_sec", "tracker_lost_sec",
)


def _bad(message: str) -> None:
    raise ConfigurationError(message, operation="config")


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        _bad(f"{name}: object required")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        _bad(f"{name}: nonempty string required")
    return value


def _integer(value: Any, name: str, minimum: int | None = 1) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        bound = "" if minimum is None else f" >= {minimum}"
        _bad(f"{name}: integer{bound} required")
    return value


def _number(value: Any, name: str, minimum: float = 0, *, positive=False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        _bad(f"{name}: finite number required")
    if value < minimum or (positive and value <= 0):
        _bad(f"{name}: invalid value {value}")
    return value


def port_number(text: str) -> int:
    try:
        port = int(text)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError("PORT must be an integer", operation="cli") from exc
    if not 1 <= port <= 65535:
        _bad("PORT must be 1..65535")
    return port


def _validate_env(env: Any) -> dict:
    e = _object(env, "env")
    if type(e.get("version")) is not int or e["version"] != 1:
        _bad("unsupported env version")
    for key in ("name", "run", "description"):
        _text(e.get(key), key)
    _integer(e.get("seed"), "seed", None)
    tracker = _object(e.get("tracker"), "tracker")
    port = _integer(tracker.get("port"), "tracker.port")
    if port > 65535:
        _bad("tracker.port must be 1..65535")
    chunk = _integer(e.get("chunk_size"), "chunk_size")
    peers = e.get("peers")
    if not isinstance(peers, list) or len(peers) != 4:
        _bad("peers must contain four peers")
    ids, endpoints, dirs = set(), set(), set()
    for peer in peers:
        p = _object(peer, "peer")
        pid = _text(p.get("id"), "peer.id")
        if not re.fullmatch(r"P[1-9][0-9]*", pid) or pid in ids:
            _bad("peer.id must be unique P<number>")
        ids.add(pid)
        host = _text(p.get("host"), "peer.host")
        try:
            ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            _bad("peer.host must be IPv4")
        pport = _integer(p.get("port"), "peer.port")
        if pport > 65535 or (host, pport) in endpoints:
            _bad("invalid or duplicate peer endpoint")
        endpoints.add((host, pport))
        directory = _text(p.get("dir"), "peer.dir")
        if directory in dirs:
            _bad("duplicate peer.dir")
        dirs.add(directory)
        for key in ("up_kbps", "down_kbps"):
            _integer(p.get(key), key)
    files = e.get("files")
    if not isinstance(files, list) or not files:
        _bad("files must be nonempty")
    names, total = set(), 0
    for file in files:
        f = _object(file, "file")
        name = _text(f.get("name"), "file.name")
        if name in names or any(c.isspace() or c in "/\\" for c in name) or name in (".", ".."):
            _bad("invalid or duplicate file.name")
        names.add(name)
        size = _integer(f.get("size"), "file.size")
        if f.get("origin") not in ids:
            _bad("file.origin is not a peer")
        if not isinstance(f.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", f["sha256"]):
            _bad("file.sha256 must be lowercase SHA-256")
        total += ((size + chunk - 1) // chunk) * (len(peers) - 1)
    if _integer(e.get("progress_total_chunks"), "progress_total_chunks") != total:
        _bad("progress_total_chunks does not match files/peers")
    download = _object(e.get("download"), "download")
    _integer(download.get("workers"), "download.workers")
    _integer(download.get("per_peer_max"), "download.per_peer_max")
    if download.get("policy") not in (None, "random", "rarest"):
        _bad("invalid download.policy")
    if "policy" not in download:
        _bad("download.policy is required")
    _integer(download.get("policy_seed"), "download.policy_seed", None)
    timing = _object(e.get("timing"), "timing")
    for key in TIMING_KEYS:
        if key == "fail_limit":
            _integer(timing.get(key), key)
        else:
            _number(timing.get(key), key, positive=True)
    crashes = e.get("crashes")
    if not isinstance(crashes, list):
        _bad("crashes must be a list")
    for crash in crashes:
        c = _object(crash, "crash")
        if c.get("peer") not in ids:
            _bad("crash.peer is not a peer")
        _number(c.get("at_sec"), "crash.at_sec")
        _number(c.get("duration_sec"), "crash.duration_sec", positive=True)
    if "destroy" not in e:
        _bad("destroy is required")
    if e["destroy"] is not None:
        d = _object(e["destroy"], "destroy")
        if d.get("peer") not in ids or d.get("trigger") not in ("time", "progress", "after_replication"):
            _bad("invalid destroy peer/trigger")
        value = _number(d.get("value"), "destroy.value")
        if d["trigger"] != "time" and value > 1:
            _bad("destroy progress/value must be 0..1")
        if type(d.get("replica_safe")) is not bool:
            _bad("destroy.replica_safe must be bool")
    return e


def validate_env(env: Any) -> dict:
    try:
        return _validate_env(env)
    except (TypeError, KeyError, OverflowError) as exc:
        raise ConfigurationError(f"invalid env field: {exc}", operation="config") from exc


def load_env(path: str | Path) -> dict:
    try:
        with open(path, encoding="utf-8") as stream:
            env = json.load(stream)
    except (OSError, ValueError, UnicodeError) as exc:
        raise ConfigurationError(f"cannot read env: {exc}", operation="config") from exc
    return validate_env(env)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ConfigurationError(message, operation="cli")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _Parser(description="HW6 Tracker")
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("port", nargs="?", type=port_number)
    return parser.parse_args(argv)
