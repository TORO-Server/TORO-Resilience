"""Command line entry points.

  python3 -m resilience receiver   EEW receiver + tier engine (long-running)
  python3 -m resilience agent      heartbeat writer on the protected host
  python3 -m resilience watcher    heartbeat checker off-host (notifies)
  python3 -m resilience replay     feed recorded route payloads to the engine
                                   with a recording action sink (verification)

Common options: --config PATH (JSON configuration file).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .actions import ActionHub, DiscordNotifier, IncidentLog
from .config import Config
from .engine import Engine
from .events import QuakeInfo
from .heartbeat import heartbeat_status, write_heartbeat
from .parsers import parse_message
from .receiver import start_receivers


def _build_hub(config: Config) -> ActionHub:
    log = IncidentLog(config.incident_log_path)
    webhook = config.env_secret(config.discord_webhook_env) if config.notify_discord else None
    return ActionHub(config, log, DiscordNotifier(webhook, log))


def cmd_receiver(args) -> int:
    config = Config.load(args.config)
    hub = _build_hub(config)
    engine = Engine(config, hub)
    receivers = start_receivers(config, engine, hub.record)
    hub.record({"type": "receiver_started", "routes": [r.source for r in receivers]})
    try:
        while True:
            time.sleep(5)
            engine.tick()
    except KeyboardInterrupt:
        for r in receivers:
            r.stop()
    return 0


def cmd_agent(args) -> int:
    config = Config.load(args.config)
    while True:
        write_heartbeat(config.heartbeat_path)
        if args.once:
            return 0
        time.sleep(config.heartbeat_interval_s)


def cmd_watcher(args) -> int:
    config = Config.load(args.config)
    log = IncidentLog(config.incident_log_path)
    webhook = config.env_secret(config.discord_webhook_env) if config.notify_discord else None
    notifier = DiscordNotifier(webhook, log)
    state = "ok"
    while True:
        status = heartbeat_status(config.heartbeat_path, config.heartbeat_stale_s)
        current = status["state"]
        if current != "ok" and state == "ok":
            log.record({"type": "heartbeat_lost", **status})
            notifier.send("ホストの heartbeat が途絶しました。障害の可能性があります。")
        elif current == "ok" and state != "ok":
            log.record({"type": "heartbeat_recovered", **status})
            notifier.send("ホストの heartbeat が復旧しました。")
        state = current
        if args.once:
            print(json.dumps(status, ensure_ascii=False))
            return 0 if current == "ok" else 1
        time.sleep(min(config.heartbeat_interval_s, 60.0))


class _PrintActions:
    """Replay sink: prints every action the engine would take."""

    def __init__(self):
        self.calls = []

    def _emit(self, name, *a):
        entry = (name,) + a
        self.calls.append(entry)
        print("ACTION", name, *[str(x) for x in a])

    def record(self, entry):
        print("RECORD", json.dumps(entry, ensure_ascii=False))

    def notify_eew(self, key, state):
        self._emit("notify_eew", key, state.host_scale)

    def notify_cancel(self, key, state):
        self._emit("notify_cancel", key)

    def save_start(self, key, state):
        self._emit("save_start", key)

    def login_stop(self, key, state):
        self._emit("login_stop", key)

    def login_resume(self, key, state):
        self._emit("login_resume", key)

    def stop_recommended(self, key, info):
        self._emit("stop_recommended", key, info.max_scale)


def cmd_replay(args) -> int:
    config = Config.load(args.config)
    actions = _PrintActions()
    engine = Engine(config, actions)
    now = 1000.0
    with open(args.file, encoding="utf-8") as f:
        text = f.read()
    payloads = []
    try:
        data = json.loads(text)
        payloads = data if isinstance(data, list) else [data]
    except ValueError:
        for line in text.splitlines():
            line = line.strip()
            if line:
                payloads.append(json.loads(line))
    for payload in payloads:
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        event = parse_message(args.source, raw)
        if event is None:
            continue
        now += args.step
        if isinstance(event, QuakeInfo):
            engine.handle_quake(event, now=now)
        else:
            engine.handle_report(event, now=now)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="resilience")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("receiver")
    p_agent = sub.add_parser("agent")
    p_agent.add_argument("--once", action="store_true")
    p_watcher = sub.add_parser("watcher")
    p_watcher.add_argument("--once", action="store_true")
    p_replay = sub.add_parser("replay")
    p_replay.add_argument("--source", required=True, choices=["wolfx", "p2p"])
    p_replay.add_argument("--step", type=float, default=1.0)
    p_replay.add_argument("file")

    args = parser.parse_args(argv)
    if args.command == "receiver":
        return cmd_receiver(args)
    if args.command == "agent":
        return cmd_agent(args)
    if args.command == "watcher":
        return cmd_watcher(args)
    if args.command == "replay":
        return cmd_replay(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
