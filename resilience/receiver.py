"""Route receivers: one thread per WebSocket route, reconnecting forever.

Liveness expectations differ per route (established by measurement):
  - Wolfx sends a heartbeat every 60 s; silence beyond 150 s is abnormal.
  - P2P has no guaranteed periodic traffic: its code 555 arrived at
    intervals between ~10 s and ~183 s in measurement. Silence beyond
    600 s is treated as abnormal, and protocol-level pings are used to
    keep the connection verifiable.
"""
from __future__ import annotations

import threading
import time

from .events import QuakeInfo
from .parsers import parse_message
from .ws_client import WsConnection

SILENCE_LIMIT_S = {"wolfx": 150.0, "p2p": 600.0}


class RouteReceiver(threading.Thread):
    def __init__(self, source: str, url: str, engine, record):
        super().__init__(daemon=True, name=f"receiver-{source}")
        self.source = source
        self.url = url
        self.engine = engine
        self.record = record
        self.last_message_at = 0.0
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._session()
                backoff = 1.0
            except Exception as e:
                self.record({"type": "route_disconnected", "source": self.source,
                             "error": f"{type(e).__name__}: {e}"})
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 60.0)

    def _session(self) -> None:
        conn = WsConnection(self.url, timeout=30.0)
        conn.connect()
        self.record({"type": "route_connected", "source": self.source})
        self.last_message_at = time.monotonic()
        if self.source == "wolfx":
            conn.send_text("ping")  # documented application-level ping
        try:
            while not self._stop.is_set():
                try:
                    message = conn.recv_message()
                except TimeoutError:
                    conn.send_ping()
                    self._check_silence()
                    continue
                if message is None:
                    raise ConnectionError("server closed the connection")
                self.last_message_at = time.monotonic()
                event = parse_message(self.source, message)
                if event is None:
                    continue
                event.received_monotonic = self.last_message_at
                if isinstance(event, QuakeInfo):
                    self.engine.handle_quake(event, now=self.last_message_at)
                else:
                    self.engine.handle_report(event, now=self.last_message_at)
        finally:
            conn.close()

    def _check_silence(self) -> None:
        limit = SILENCE_LIMIT_S.get(self.source, 600.0)
        if self.last_message_at and time.monotonic() - self.last_message_at > limit:
            raise ConnectionError(f"no message for over {limit:.0f}s")


def start_receivers(config, engine, record):
    receivers = []
    if config.enable_wolfx:
        receivers.append(RouteReceiver("wolfx", config.wolfx_url, engine, record))
    if config.enable_p2p:
        receivers.append(RouteReceiver("p2p", config.p2p_url, engine, record))
    for r in receivers:
        r.start()
    return receivers
