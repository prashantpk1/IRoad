"""
Return-leg route proxy for round-trip bookings (dashboard + job detail).
"""
from __future__ import annotations

from typing import Any


def backload_route_booking_proxy(booking: Any) -> Any:
    """Shallow view so route serialization uses the return leg on round trips."""
    route = getattr(booking, 'route', None)
    if route is None:
        return booking
    origin = getattr(route, 'destination_point', None)
    destination = getattr(route, 'origin_point', None)
    if origin is None or destination is None:
        return booking

    class _RouteProxy:
        def __init__(self, base):
            self._base = base
            self.route = base.route
            self.route_display = ''
            self.route_direction = 'reverse'

        def __getattr__(self, name):
            return getattr(self._base, name)

    return _RouteProxy(booking)
