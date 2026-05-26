"""
mobile_api/execution/urls.py

Execute Action routes (included from ``mobile_api.urls``).
"""
from django.urls import path

from mobile_api.execution.views.execute_action_view import ExecuteActionAPIView

urlpatterns = [
    path(
        'driver/jobs/<str:job_type>/<str:job_id>/actions/<str:action_code>/execute/',
        ExecuteActionAPIView.as_view(),
        name='driver_execute_action',
    ),
]
