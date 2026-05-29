"""
mobile_api/history/urls.py

Driver History routes (included from ``mobile_api.urls``).
"""
from django.urls import path

from mobile_api.history.views.history_detail_view import HistoryDetailAPIView
from mobile_api.history.views.history_list_view import HistoryListAPIView

urlpatterns = [
    path(
        'driver/history/',
        HistoryListAPIView.as_view(),
        name='driver_history_list',
    ),
    path(
        'driver/history/<str:shipment_id>/',
        HistoryDetailAPIView.as_view(),
        name='driver_history_detail',
    ),
]
