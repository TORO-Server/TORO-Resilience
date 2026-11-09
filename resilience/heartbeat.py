"""Heartbeat agent and watcher.

The agent runs on the protected host and rewrites a small JSON heartbeat
file every interval; in deployment the file is exposed to the watcher over
a private channel (the transport is deliberately not fixed here: a shared
file, a static HTTP endpoint, or object storage all satisfy the format).
The watcher runs off-host, checks the heartbeat age, and notifies when it
exceeds the stale threshold, and again when it recovers.
"""
from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_heartbeat(path: str, extra: dict | None = None) -> dict:
    payload = {
        "ts": _now_iso(),
        "epoch": time.time(),
        "host": socket.gethostname(),
    }
    if extra:
        payload.update(extra)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
    return payload


def read_heartbeat(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def heartbeat_status(path: str, stale_s: float, now_epoch: float | None = None) -> dict:
    """Return {'state': 'ok'|'stale'|'missing', 'age_s': float|None, ...}."""
    now_epoch = time.time() if now_epoch is None else now_epoch
    data = read_heartbeat(path)
    if data is None or "epoch" not in data:
        return {"state": "missing", "age_s": None, "heartbeat": data}
    age = now_epoch - float(data["epoch"])
    return {"state": "ok" if age <= stale_s else "stale",
            "age_s": age, "heartbeat": data}


def suppress_restart_active(incident_log_path: str) -> bool:
    return os.path.exists(incident_log_path + ".suppress-restart")
