"""TORO-Resilience: disaster-response system (free data routes only).

Components:
  - EEW receiver: Wolfx (forecast + warning) and P2P earthquake information
    (warning + detection) over WebSocket, standard library only.
  - Tier engine: decides protective actions from EEW reports under a
    corroboration policy compensating for the free routes' limits.
  - Heartbeat agent / watcher: host liveness monitoring.
  - Actions: JSONL incident log, Discord webhook notification, Minecraft
    RCON commands (opt-in).
"""

__version__ = "0.1.0"
