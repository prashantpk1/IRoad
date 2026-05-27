"""
mobile_api.pod_capture

Shipment-only POD evidence preparation layer.

POD Capture stages evidence for later binding via the Unified Execute Action API.
It does **not** execute workflow actions, mutate shipment status, or call kernel side effects.
"""

__all__ = [
    'PodCaptureError',
]

from mobile_api.pod_capture.exceptions import PodCaptureError
