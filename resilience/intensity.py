"""Predicted seismic intensity at the host location.

Primary source: per-area forecasts carried by the reports themselves
(Wolfx WarnArea, P2P areas). These are JMA's own per-area values and are
the only basis allowed for disruptive actions (login stop).

Fallback: an attenuation estimate from hypocentre parameters, using the
Si & Midorikawa (1999) PGV relation (epicentral distance as the
point-source approximation of the fault distance), a generic surface
amplification of 1.31, and I = 2*log10(PGV) + 0.94 (PGV in cm/s).
Calibration limit, stated plainly: this estimate runs lower than JMA's
per-area forecasts (which use per-site amplification). It is therefore
used only for notification and the save start, never for a login stop,
and it never lowers an area-based value.
"""
from __future__ import annotations

import math

from .events import scale_from_instrumental

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_scale(magnitude: float, depth_km: float,
                   epicentral_km: float) -> int:
    """Estimate the scale value at a point from hypocentre parameters."""
    if magnitude is None or depth_km is None or epicentral_km is None:
        return 0
    x = max(epicentral_km, 1.0)
    log_pgv = (0.58 * magnitude + 0.0038 * depth_km - 1.29
               - math.log10(x + 0.0028 * (10 ** (0.50 * magnitude)))
               - 0.002 * x)
    pgv_surface = (10 ** log_pgv) * 1.31
    if pgv_surface <= 0:
        return 0
    instrumental = 2 * math.log10(pgv_surface) + 0.94
    return scale_from_instrumental(instrumental)


def host_scale(report, host_lat: float | None, host_lon: float | None,
               host_area_names):
    """Best available predicted scale at the host for one report.

    Returns (scale, kind) with kind 'area' or 'estimate', or None.
    'area' values come from the report's per-area forecast (upper bound
    of the matched area's range) and may drive any tier. 'estimate'
    values come from the attenuation fallback and may drive only
    notification and the save start.
    """
    for name in host_area_names or ():
        if name in report.areas:
            _lo, hi = report.areas[name]
            return (hi, "area")
    if (host_lat is not None and host_lon is not None
            and report.latitude is not None and report.longitude is not None
            and report.magnitude is not None and report.depth_km is not None):
        dist = haversine_km(host_lat, host_lon, report.latitude, report.longitude)
        return (estimate_scale(report.magnitude, report.depth_km, dist), "estimate")
    return None
