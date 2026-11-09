"""Configuration loading.

Values come from a JSON file (path given by --config or the
RESILIENCE_CONFIG environment variable); secrets are never stored in the
file but referenced by environment variable name. Infrastructure-specific
values (host coordinates, area names, endpoints of the protected server)
belong in this file or the environment, never in the repository.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # Host location for predicted-intensity computation. When unset, only
    # per-area forecasts matching host_area_names can drive tier actions.
    host_lat: float | None = None
    host_lon: float | None = None
    host_area_names: list = field(default_factory=list)

    # Tier thresholds (JMA scale values: 40=4, 45=5弱, 50=5強).
    save_scale: int = 40        # at/above: Tier 0 + save start
    full_scale: int = 45        # at/above: full Tier 1 (login stop), corroboration required
    observed_stop_scale: int = 50  # observed (Tier 2) at/above: stop recommended

    # Corroboration window between routes, seconds.
    corroboration_window_s: float = 120.0
    # Events are kept for matching late reports / cancels, seconds.
    event_retention_s: float = 1800.0

    # Data routes (public endpoints; overridable for sandbox testing).
    wolfx_url: str = "wss://ws-api.wolfx.jp/jma_eew"
    p2p_url: str = "wss://api.p2pquake.net/v2/ws"
    enable_wolfx: bool = True
    enable_p2p: bool = True

    # Actions.
    incident_log_path: str = "incidents.jsonl"
    discord_webhook_env: str = "RESILIENCE_DISCORD_WEBHOOK"
    notify_discord: bool = True

    rcon_enabled: bool = False
    rcon_host: str = "127.0.0.1"
    rcon_port: int = 25575
    rcon_password_env: str = "RESILIENCE_RCON_PASSWORD"
    commands_on_save: list = field(default_factory=lambda: ["save-all flush"])
    # Login gating depends on the server setup (gate plugin etc.), so the
    # commands are operator-defined. Empty lists mean: track and notify
    # only, do not touch the server.
    commands_on_login_stop: list = field(default_factory=list)
    commands_on_login_resume: list = field(default_factory=list)
    # Stopping the server automatically is off unless explicitly allowed.
    allow_server_stop: bool = False
    commands_on_stop: list = field(default_factory=lambda: ["stop"])

    # Heartbeat agent / watcher.
    heartbeat_path: str = "heartbeat.json"
    heartbeat_interval_s: float = 60.0
    heartbeat_stale_s: float = 180.0

    @classmethod
    def load(cls, path: str | None) -> "Config":
        cfg = cls()
        if path is None:
            path = os.environ.get("RESILIENCE_CONFIG")
        if path:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        return cfg

    def env_secret(self, env_name: str) -> str | None:
        value = os.environ.get(env_name)
        return value if value else None
