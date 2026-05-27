"""
mobile_api/issues/urls.py
"""
from django.urls import path

from mobile_api.issues.views.issue_lifecycle_view import IssueLifecycleAPIView
from mobile_api.issues.views.issue_reporting_view import IssueReportingAPIView

urlpatterns = [
    path(
        'driver/issues/report/',
        IssueReportingAPIView.as_view(),
        name='driver_issue_report',
    ),
    path(
        'issues/<uuid:issue_id>/acknowledge/',
        IssueLifecycleAPIView.as_view(),
        {'operation': 'acknowledge'},
        name='issue_acknowledge',
    ),
    path(
        'issues/<uuid:issue_id>/resolve/',
        IssueLifecycleAPIView.as_view(),
        {'operation': 'resolve'},
        name='issue_resolve',
    ),
    path(
        'issues/<uuid:issue_id>/reject/',
        IssueLifecycleAPIView.as_view(),
        {'operation': 'reject'},
        name='issue_reject',
    ),
    path(
        'issues/<uuid:issue_id>/reopen/',
        IssueLifecycleAPIView.as_view(),
        {'operation': 'reopen'},
        name='issue_reopen',
    ),
]
