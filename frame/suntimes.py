#!/usr/bin/env python3
"""Sunrise and sunset for one place and one day, standard library only.

Implements the NOAA sunrise equation (as on Wikipedia's "Sunrise equation"
page). Accurate to a minute or two away from the poles, which is plenty for
choosing what the frame shows. Longitude is east-positive.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

_J2000 = 2451545.0          # Julian date of 2000-01-01 12:00 UTC
_J2000_ORDINAL = date(2000, 1, 1).toordinal()
_UNIX_EPOCH_JD = 2440587.5


def _jd_to_datetime(jd):
    return datetime.fromtimestamp((jd - _UNIX_EPOCH_JD) * 86400, tz=timezone.utc)


def sun_times(day, lat, lon):
    """Return (sunrise, sunset) as aware UTC datetimes for ``day``.

    Returns ("polar_day", None) when the sun never sets that day and
    (None, "polar_night") when it never rises.
    """
    n = day.toordinal() - _J2000_ORDINAL
    j_star = n - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = _J2000 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    sin_d = math.sin(lam) * math.sin(math.radians(23.4397))
    cos_d = math.cos(math.asin(sin_d))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * sin_d) / (math.cos(phi) * cos_d)
    if cos_w < -1:
        return "polar_day", None
    if cos_w > 1:
        return None, "polar_night"
    w = math.degrees(math.acos(cos_w)) / 360.0
    return _jd_to_datetime(transit - w), _jd_to_datetime(transit + w)
