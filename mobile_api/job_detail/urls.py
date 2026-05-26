"""
mobile_api/job_detail/urls.py

Job Detail routes (included from ``mobile_api.urls``).
"""
from django.urls import path

from mobile_api.job_detail.views.job_detail_timeline_view import (
    JobDetailTimelineAPIView,
)
from mobile_api.job_detail.views.job_detail_view import JobDetailAPIView

urlpatterns = [
    path(
        'driver/jobs/<str:job_type>/<str:job_id>/',
        JobDetailAPIView.as_view(),
        name='driver_job_detail',
    ),
    path(
        'driver/jobs/<str:job_type>/<str:job_id>/timeline/',
        JobDetailTimelineAPIView.as_view(),
        name='driver_job_detail_timeline',
    ),
]
