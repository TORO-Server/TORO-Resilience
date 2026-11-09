"""Action layer used by the engine.

Every action is recorded to the JSONL incident log first. Discord
notification is fire-and-forget (own thread; failures are logged, never
raised into the engine). Server commands run only when RCON is enabled
in the configuration; a server stop additionally requires
allow_server_stop. All methods are safe to call in dry-run setups:
with RCON disabled they reduce to record + notify.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime, timezone

from .events import scale_to_text
from .rcon import RconClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class IncidentLog:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()

    def record(self, entry: dict) -> None:
        row = {"ts": _now_iso(), **entry}
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


class DiscordNotifier:
    def __init__(self, webhook_url: str | None, log: IncidentLog):
        self.webhook_url = webhook_url
        self.log = log

    def send(self, text: str) -> None:
        if not self.webhook_url:
            return
        thread = threading.Thread(target=self._post, args=(text,), daemon=True)
        thread.start()

    def _post(self, text: str) -> None:
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps({"content": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:  # notification failure must not break the engine
            self.log.record({"type": "discord_notify_failed", "error": f"{type(e).__name__}: {e}"})


class ActionHub:
    """Engine-facing actions: record + notify + optional RCON commands."""

    def __init__(self, config, log: IncidentLog, notifier: DiscordNotifier):
        self.config = config
        self.log = log
        self.notifier = notifier

    # -- engine interface ------------------------------------------------

    def record(self, entry: dict) -> None:
        self.log.record(entry)

    def notify_eew(self, key, state) -> None:
        self.log.record({"type": "tier0_notify", "event": key,
                         "host_scale": state.host_scale,
                         "host_scale_text": scale_to_text(state.host_scale)})
        self.notifier.send(
            f"緊急地震速報: {state.hypocenter_name or '震源不明'} "
            f"予測震度 {scale_to_text(state.host_scale)}（ホスト所在地）。"
            f"保存を開始します。"
        )

    def notify_cancel(self, key, state) -> None:
        self.log.record({"type": "tier_cancel_notify", "event": key})
        self.notifier.send("緊急地震速報は取り消されました。")

    def save_start(self, key, state) -> None:
        self.log.record({"type": "tier1_save_start", "event": key})
        self._run_rcon(self.config.commands_on_save, key, "save")

    def login_stop(self, key, state) -> None:
        self.log.record({"type": "tier1_login_stop", "event": key,
                         "corroborated": True})
        self.notifier.send("予測震度が閾値以上です。新規ログインを停止しました。")
        self._run_rcon(self.config.commands_on_login_stop, key, "login_stop")

    def login_resume(self, key, state) -> None:
        self.log.record({"type": "tier1_login_resume", "event": key})
        self.notifier.send("取消に伴い、新規ログイン停止を解除しました。")
        self._run_rcon(self.config.commands_on_login_resume, key, "login_resume")

    def stop_recommended(self, key, info) -> None:
        self.log.record({"type": "tier2_stop_recommended", "event": key,
                         "observed_max_scale": info.max_scale})
        self.notifier.send(
            f"震度速報で最大震度 {scale_to_text(info.max_scale)} を観測しました。"
            f"サーバー停止を推奨します。再起動は自動では行われません。"
        )
        # Record restart suppression next to the incident log; operators and
        # startup scripts can check this flag before restarting the server.
        flag_path = self.config.incident_log_path + ".suppress-restart"
        try:
            with open(flag_path, "w", encoding="utf-8") as f:
                json.dump({"ts": _now_iso(), "event": key,
                           "observed_max_scale": info.max_scale}, f)
        except OSError as e:
            self.log.record({"type": "suppress_flag_failed", "error": str(e)})
        if self.config.allow_server_stop:
            self._run_rcon(self.config.commands_on_stop, key, "stop")

    # -- internals ---------------------------------------------------------

    def _run_rcon(self, commands, key, label: str) -> None:
        if not commands:
            return
        if not self.config.rcon_enabled:
            self.log.record({"type": "rcon_skipped_disabled", "event": key,
                             "action": label, "commands": commands})
            return
        password = self.config.env_secret(self.config.rcon_password_env)
        if password is None:
            self.log.record({"type": "rcon_skipped_no_password", "event": key,
                             "action": label})
            return
        try:
            with RconClient(self.config.rcon_host, self.config.rcon_port, password) as client:
                for cmd in commands:
                    response = client.command(cmd)
                    self.log.record({"type": "rcon_command", "event": key,
                                     "action": label, "command": cmd,
                                     "response": response[:200]})
        except Exception as e:
            self.log.record({"type": "rcon_failed", "event": key, "action": label,
                             "error": f"{type(e).__name__}: {e}"})
