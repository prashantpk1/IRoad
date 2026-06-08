"""
mobile_api/hard_pod/urls.py
"""
from django.urls import path

from mobile_api.hard_pod.views.hard_pod_documents_view import HardPodDocumentsAPIView
from mobile_api.hard_pod.views.hard_pod_list_view import HardPodListAPIView
from mobile_api.hard_pod.views.hard_pod_submit_view import HardPodSubmitAPIView

urlpatterns = [
    path(
        'driver/hard-pod/pending/',
        HardPodListAPIView.as_view(),
        name='driver_hard_pod_pending',
    ),
    path(
        'driver/hard-pod/submit/',
        HardPodSubmitAPIView.as_view(),
        name='driver_hard_pod_submit',
    ),
    path(
        'driver/jobs/shipments/<str:shipment_id>/hard-pod/documents/',
        HardPodDocumentsAPIView.as_view(),
        name='driver_hard_pod_documents',
    ),
]
