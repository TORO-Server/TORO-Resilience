"""Parsers converting route payloads into the shared event model.

Wolfx jma_eew: forecast and warning reports in Wolfx's JSON format.
P2P (JSON API v2 schema, identical over WebSocket):
  code 554 EEW detection notice, code 556 EEW (warning only),
  code 551 JMA earthquake information.
Unknown or housekeeping payloads (Wolfx heartbeat/pong, P2P 555/561/9611)
return None; liveness is tracked by the receiver, not the parser.
"""
from __future__ import annotations

import json

from .events import EewReport, QuakeInfo, scale_from_text


def parse_message(source: str, text: str):
    """Parse one raw WebSocket text frame. Returns EewReport | QuakeInfo | None."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if source == "wolfx":
        return _parse_wolfx(data)
    if source == "p2p":
        return _parse_p2p(data)
    return None


def _parse_wolfx(d: dict):
    if d.get("type") in ("heartbeat", "pong"):
        return None
    if "EventID" not in d or "Title" not in d:
        return None
    title = str(d.get("Title", ""))
    is_warn = bool(d.get("isWarn"))
    kind = "warning" if (is_warn or "警報" in title) else "forecast"
    areas = {}
    for a in d.get("WarnArea") or []:
        if not isinstance(a, dict):
            continue
        name = a.get("Chiiki")
        if not name:
            continue
        hi = scale_from_text(a.get("Shindo1"))
        lo = scale_from_text(a.get("Shindo2"))
        if hi is None:
            continue
        areas[name] = (lo if lo is not None else hi, hi)
    return EewReport(
        source="wolfx",
        event_id=str(d.get("EventID")),
        serial=int(d.get("Serial") or 0),
        kind=kind,
        cancelled=bool(d.get("isCancel")),
        final=bool(d.get("isFinal")),
        training=bool(d.get("isTraining")),
        announced_at=str(d.get("AnnouncedTime", "")),
        origin_at=str(d.get("OriginTime", "")),
        hypocenter_name=str(d.get("Hypocenter", "")),
        latitude=_f(d.get("Latitude")),
        longitude=_f(d.get("Longitude")),
        depth_km=_f(d.get("Depth")),
        magnitude=_f(d.get("Magnitude", d.get("Magunitude"))),
        max_scale=scale_from_text(d.get("MaxIntensity")),
        areas=areas,
    )


def _parse_p2p(d: dict):
    code = d.get("code")
    if code == 554:
        # Detection notice only: carries no hypocentre data. Used by the
        # engine solely as corroboration that JMA issued an EEW.
        return EewReport(
            source="p2p",
            event_id="detection",
            serial=0,
            kind="detection",
            announced_at=str(d.get("time", "")),
        )
    if code == 556:
        issue = d.get("issue") or {}
        eq = d.get("earthquake") or {}
        hypo = eq.get("hypocenter") or {}
        areas = {}
        for a in d.get("areas") or []:
            name = a.get("name")
            if not name:
                continue
            lo = a.get("scaleFrom")
            hi = a.get("scaleTo")
            areas[name] = (
                int(lo) if lo is not None and int(lo) >= 0 else None,
                int(hi) if hi is not None and int(hi) != 99 else int(lo or 0),
            )
        serial_raw = issue.get("serial")
        return EewReport(
            source="p2p",
            event_id=str(issue.get("eventId", "")),
            serial=int(serial_raw) if str(serial_raw).isdigit() else 0,
            kind="warning",
            cancelled=bool(d.get("cancelled")),
            announced_at=str(issue.get("time", "")),
            origin_at=str(eq.get("originTime", "")),
            hypocenter_name=str(hypo.get("name", "")),
            latitude=_f(hypo.get("latitude")),
            longitude=_f(hypo.get("longitude")),
            depth_km=_f(hypo.get("depth")),
            magnitude=_f(hypo.get("magnitude")),
            areas=areas,
        )
    if code == 551:
        eq = d.get("earthquake") or {}
        hypo = eq.get("hypocenter") or {}
        max_scale = eq.get("maxScale")
        return QuakeInfo(
            source="p2p",
            event_key_time=str(eq.get("time", "")),
            max_scale=int(max_scale) if max_scale is not None else None,
            hypocenter_name=str(hypo.get("name", "")),
            magnitude=_f(hypo.get("magnitude")),
        )
    return None


def _f(value):
    try:
        if value is None:
            return None
        v = float(value)
    except (TypeError, ValueError):
        return None
    # P2P uses sentinel values (-200 lat/lon, -1 depth/magnitude) for
    # missing hypocentre data.
    if v <= -100:
        return None
    return v
