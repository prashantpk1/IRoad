"""
mobile_api/pod_capture/urls.py

POD Capture routes (included from ``mobile_api.urls``).
"""
from django.urls import path

from mobile_api.pod_capture.views.pod_capture_view import PodCaptureAPIView

urlpatterns = [
    path(
        'driver/jobs/shipments/<str:shipment_id>/pod/capture/',
        PodCaptureAPIView.as_view(),
        name='driver_pod_capture',
    ),
]
