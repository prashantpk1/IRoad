"""
mobile_api/urls.py

Mobile API URL configuration.
All endpoints versioned under /api/v1/mobile/
"""
from django.urls import path

from mobile_api.views.driver_auth import (
    DriverDeleteAccountView,
    DriverForgotPasswordView,
    DriverLoginView,
    DriverLogoutAllDevicesView,
    DriverLogoutView,
    DriverRefreshTokenView,
    DriverResetPasswordView,
    DriverVerifyOtpView,
)
from mobile_api.views.driver_organization_profile import (
    DriverOrganizationProfileView,
)
from mobile_api.views.driver_profile import (
    DriverChangePasswordView,
    DriverProfilePhotoUpdateView,
    DriverProfileView,
    DriverRequestChangePasswordOtpView,
    DriverVerifyChangePasswordOtpView,
)
from mobile_api.views.mobile_operational import MobileOperationalHealthView
from mobile_api.dashboard.views.dashboard_view import DashboardAPIView
from mobile_api.execution.urls import urlpatterns as execution_urlpatterns
from mobile_api.job_detail.urls import urlpatterns as job_detail_urlpatterns
from mobile_api.pod_capture.urls import urlpatterns as pod_capture_urlpatterns
from mobile_api.hard_pod.urls import urlpatterns as hard_pod_urlpatterns
from mobile_api.payment_collection.urls import urlpatterns as payment_collection_urlpatterns
from mobile_api.issues.urls import urlpatterns as issues_urlpatterns

app_name = 'mobile_api'

urlpatterns = [
    path(
        'driver/auth/login/',
        DriverLoginView.as_view(),
        name='driver_login',
    ),
    path(
        'driver/auth/refresh/',
        DriverRefreshTokenView.as_view(),
        name='driver_refresh',
    ),
    path(
        'driver/auth/forgot-password/',
        DriverForgotPasswordView.as_view(),
        name='driver_forgot_password',
    ),
    path(
        'driver/auth/verify-otp/',
        DriverVerifyOtpView.as_view(),
        name='driver_verify_otp',
    ),
    path(
        'driver/auth/reset-password/',
        DriverResetPasswordView.as_view(),
        name='driver_reset_password',
    ),
    path(
        'driver/auth/logout/',
        DriverLogoutView.as_view(),
        name='driver_logout',
    ),
    path(
        'driver/auth/logout-all/',
        DriverLogoutAllDevicesView.as_view(),
        name='driver_logout_all',
    ),
    path(
        'driver/auth/delete-account/',
        DriverDeleteAccountView.as_view(),
        name='driver_delete_account',
    ),
    path(
        'driver/auth/change-password/request-otp/',
        DriverRequestChangePasswordOtpView.as_view(),
        name='driver_request_change_password_otp',
    ),
    path(
        'driver/auth/change-password/verify-otp/',
        DriverVerifyChangePasswordOtpView.as_view(),
        name='driver_verify_change_password_otp',
    ),
    path(
        'driver/auth/change-password/',
        DriverChangePasswordView.as_view(),
        name='driver_change_password',
    ),
    path(
        'driver/profile/',
        DriverProfileView.as_view(),
        name='driver_profile',
    ),
    # GET — tenant org support snapshot (auth + X-Tenant-ID). See
    # mobile_api/docs/driver_organization_profile.md and Postman "Get Organization Profile".
    path(
        'driver/organization-profile/',
        DriverOrganizationProfileView.as_view(),
        name='driver_organization_profile',
    ),
    path(
        'driver/profile/photo/',
        DriverProfilePhotoUpdateView.as_view(),
        name='driver_profile_photo_update',
    ),
    path(
        'operational/health/',
        MobileOperationalHealthView.as_view(),
        name='mobile_operational_health',
    ),
    # Unified driver dashboard (workflow-driven; skeleton — logic TODO in mobile_api.dashboard)
    path(
        'driver/dashboard/',
        DashboardAPIView.as_view(),
        name='driver_dashboard',
    ),
] + job_detail_urlpatterns + execution_urlpatterns + pod_capture_urlpatterns + hard_pod_urlpatterns + payment_collection_urlpatterns + issues_urlpatterns
