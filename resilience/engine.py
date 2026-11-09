"""Tier engine: turns EEW reports from the free routes into actions.

Policy (free routes only; no paid route is used):

  Tier 0 (notify + record) and the save start of Tier 1 are low-harm,
  reversible actions. A single route may trigger them when the predicted
  intensity at the host reaches the save threshold (scale 40 / 震度4).

  The login stop of Tier 1 is disruptive, so it requires an area-based
  host intensity (per-area forecast from a route, not the attenuation
  estimate) and corroboration:
    - a P2P code 556 report (relayed JMA warning content), or
    - a Wolfx warning report plus a P2P code 554 detection notice for the
      same event within the corroboration window.
  Wolfx alone never triggers a login stop: it is an unofficial relay and
  its own documentation states it must not replace official warnings.
  P2P alone never triggers it from a forecast, because P2P carries no
  forecast feed at all.

  Cancellation: if the login stop is in effect and the server has not been
  stopped, only the login stop is released. After a stop, a cancellation
  never restarts the server automatically.

  Tier 2: when JMA earthquake information (P2P code 551) reports an
  observed maximum intensity at/above the stop threshold for the event,
  a stop is recommended and restart suppression is recorded. Executing
  the stop itself additionally requires allow_server_stop in the config.

All timing is injected (monotonic seconds) so behaviour is testable and
replayable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from .events import EewReport, QuakeInfo, scale_to_text
from .intensity import host_scale


def _parse_time(text: str) -> float | None:
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except (ValueError, TypeError):
            continue
    return None


@dataclass
class EventState:
    key: str
    first_seen: float
    last_seen: float
    event_ids: set = field(default_factory=set)
    origin_epoch: float | None = None
    hypocenter_name: str = ""
    sources: set = field(default_factory=set)
    host_scale: int | None = None        # effective (area or estimate) for notify/save
    host_scale_area: int | None = None   # area-based only; required for login stop
    wolfx_warning: bool = False
    p2p_warning: bool = False
    p2p_detection_at: float | None = None
    notified: bool = False
    save_started: bool = False
    login_stopped: bool = False
    awaiting_corroboration: bool = False
    cancelled: bool = False
    final: bool = False
    stop_recommended: bool = False
    closed: bool = False


class Engine:
    def __init__(self, config, actions):
        self.config = config
        self.actions = actions
        self._seen_reports: set = set()
        self._events: dict[str, EventState] = {}
        self._event_counter = 0

    # -- intake ---------------------------------------------------------

    def handle_report(self, report: EewReport, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if report.training:
            self.actions.record({"type": "training_ignored", "source": report.source,
                                 "event_id": report.event_id})
            return
        if report.kind == "detection":
            self._handle_detection(report, now)
            return
        if report.key in self._seen_reports:
            return
        self._seen_reports.add(report.key)

        state = self._match_event(report, now)
        state.last_seen = now
        state.sources.add(report.source)
        state.event_ids.add(report.event_id)
        if report.hypocenter_name:
            state.hypocenter_name = report.hypocenter_name
        if report.source == "wolfx" and report.kind == "warning":
            state.wolfx_warning = True
        if report.source == "p2p" and report.kind == "warning":
            state.p2p_warning = True
        if report.final:
            state.final = True

        self.actions.record({
            "type": "eew_report", "source": report.source,
            "event_id": report.event_id, "serial": report.serial,
            "kind": report.kind, "cancelled": report.cancelled,
            "hypocenter": report.hypocenter_name,
            "magnitude": report.magnitude, "max_scale": report.max_scale,
            "announced_at": report.announced_at,
        })

        if report.cancelled:
            self._handle_cancel(state, report, now)
            return

        result = host_scale(report, self.config.host_lat, self.config.host_lon,
                            self.config.host_area_names)
        if result is not None:
            scale, kind = result
            state.host_scale = scale if state.host_scale is None else max(state.host_scale, scale)
            if kind == "area":
                state.host_scale_area = (scale if state.host_scale_area is None
                                         else max(state.host_scale_area, scale))

        self._evaluate_tiers(state, now)

    def handle_quake(self, info: QuakeInfo, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.actions.record({
            "type": "quake_info", "source": info.source,
            "origin_at": info.event_key_time, "max_scale": info.max_scale,
            "hypocenter": info.hypocenter_name, "magnitude": info.magnitude,
        })
        origin = _parse_time(info.event_key_time)
        for state in self._events.values():
            if state.closed or state.cancelled:
                continue
            if state.origin_epoch is None or origin is None:
                continue
            if abs(state.origin_epoch - origin) > self.config.corroboration_window_s:
                continue
            # Tier 2: observed intensity confirms a severe event.
            if (info.max_scale is not None
                    and info.max_scale >= self.config.observed_stop_scale
                    and not state.stop_recommended):
                state.stop_recommended = True
                self.actions.stop_recommended(state.key, info)
            state.closed = True

    def tick(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        expired = [k for k, s in self._events.items()
                   if now - s.last_seen > self.config.event_retention_s]
        for k in expired:
            del self._events[k]

    # -- internals ------------------------------------------------------

    def _handle_detection(self, report: EewReport, now: float) -> None:
        self.actions.record({"type": "eew_detection", "source": report.source,
                             "announced_at": report.announced_at})
        # A detection corroborates any recent active event still waiting
        # for it (the detection itself carries no event identifier).
        for state in self._events.values():
            if state.closed or state.cancelled:
                continue
            if now - state.first_seen <= self.config.corroboration_window_s:
                state.p2p_detection_at = now
                self._evaluate_tiers(state, now)

    def _match_event(self, report: EewReport, now: float) -> EventState:
        origin = _parse_time(report.origin_at)
        for state in self._events.values():
            if state.closed:
                continue
            if report.event_id and report.event_id in state.event_ids:
                return state
            if (origin is not None and state.origin_epoch is not None
                    and abs(origin - state.origin_epoch) <= self.config.corroboration_window_s):
                return state
        self._event_counter += 1
        key = f"ev{self._event_counter}"
        state = EventState(key=key, first_seen=now, last_seen=now,
                           origin_epoch=origin)
        self._events[key] = state
        return state

    def _corroborated(self, state: EventState, now: float) -> bool:
        if state.p2p_warning:
            return True
        if state.wolfx_warning and state.p2p_detection_at is not None:
            if now - state.p2p_detection_at <= self.config.corroboration_window_s:
                return True
        return False

    def _evaluate_tiers(self, state: EventState, now: float) -> None:
        if state.cancelled or state.closed:
            return
        scale = state.host_scale
        if scale is None:
            return
        # Tier 0: notification (once per event).
        if scale >= self.config.save_scale and not state.notified:
            state.notified = True
            self.actions.notify_eew(state.key, state)
        # Tier 1 (save start): single route is enough.
        if scale >= self.config.save_scale and not state.save_started:
            state.save_started = True
            self.actions.save_start(state.key, state)
        # Tier 1 (login stop): area-based scale and corroboration required.
        area_scale = state.host_scale_area
        if (area_scale is not None and area_scale >= self.config.full_scale
                and not state.login_stopped):
            if self._corroborated(state, now):
                state.login_stopped = True
                state.awaiting_corroboration = False
                self.actions.login_stop(state.key, state)
            elif not state.awaiting_corroboration:
                state.awaiting_corroboration = True
                self.actions.record({
                    "type": "awaiting_corroboration", "event": state.key,
                    "host_scale": area_scale,
                    "host_scale_text": scale_to_text(area_scale),
                })

    def _handle_cancel(self, state: EventState, report: EewReport, now: float) -> None:
        state.cancelled = True
        self.actions.record({"type": "eew_cancelled", "event": state.key,
                             "source": report.source})
        self.actions.notify_cancel(state.key, state)
        if state.login_stopped and not state.stop_recommended:
            state.login_stopped = False
            self.actions.login_resume(state.key, state)
        state.closed = True
