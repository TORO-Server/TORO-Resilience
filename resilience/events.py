"""Event model shared by all data routes.

JMA seismic intensity is handled as the numeric "scale value" used by the
P2P API (10=1, 20=2, 30=3, 40=4, 45=5弱, 50=5強, 55=6弱, 60=6強, 70=7),
which keeps threshold comparisons exact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCALE_TEXT = {
    10: "1", 20: "2", 30: "3", 40: "4", 45: "5弱",
    50: "5強", 55: "6弱", 60: "6強", 70: "7",
}

_TEXT_TO_SCALE = {
    "1": 10, "2": 20, "3": 30, "4": 40,
    "5弱": 45, "5-": 45, "5強": 50, "5+": 50,
    "6弱": 55, "6-": 55, "6強": 60, "6+": 60,
    "7": 70,
}


def scale_from_text(text) -> int | None:
    """Convert a JMA intensity string ('5弱', '4', '6強'...) to a scale value."""
    if text is None:
        return None
    s = str(text).strip()
    if s in _TEXT_TO_SCALE:
        return _TEXT_TO_SCALE[s]
    try:
        v = float(s)
    except ValueError:
        return None
    # Wolfx sometimes reports a plain instrumental intensity number.
    return scale_from_instrumental(v)


def scale_from_instrumental(value: float) -> int:
    """Convert an instrumental intensity (計測震度) to the nearest scale value."""
    if value < 0.5:
        return 0
    if value < 1.5:
        return 10
    if value < 2.5:
        return 20
    if value < 3.5:
        return 30
    if value < 4.5:
        return 40
    if value < 5.0:
        return 45
    if value < 5.5:
        return 50
    if value < 6.0:
        return 55
    if value < 6.5:
        return 60
    return 70


def scale_to_text(scale: int | None) -> str:
    if scale is None:
        return "不明"
    return SCALE_TEXT.get(int(scale), f"{scale}")


@dataclass
class EewReport:
    """One EEW report (one serial of one event) from any route."""

    source: str                 # 'wolfx' | 'p2p'
    event_id: str               # route-provided event identifier
    serial: int                 # report number within the event
    kind: str                   # 'forecast' (予報) | 'warning' (警報) | 'detection' (発表検出)
    cancelled: bool = False
    final: bool = False
    training: bool = False
    announced_at: str = ""      # local-format string as provided by the route
    origin_at: str = ""
    hypocenter_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    depth_km: float | None = None
    magnitude: float | None = None
    max_scale: int | None = None            # nationally predicted maximum scale value
    areas: dict = field(default_factory=dict)  # area name -> (scale_from, scale_to)
    received_monotonic: float = 0.0         # set by the receiver on arrival

    @property
    def key(self) -> tuple:
        return (self.source, self.event_id, self.serial)


@dataclass
class QuakeInfo:
    """JMA earthquake information (震度速報 / 震源・震度情報) for Tier 2."""

    source: str
    event_key_time: str          # earthquake origin time string as provided
    max_scale: int | None = None
    hypocenter_name: str = ""
    magnitude: float | None = None
    received_monotonic: float = 0.0
