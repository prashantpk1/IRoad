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
from mobile_api.views.driver_dashboard import (
    DriverDashboardCurrentJobView,
    DriverDashboardNotificationsSummaryView,
    DriverDashboardQuickActionsView,
    DriverDashboardRecentActivityView,
    DriverDashboardSummaryView,
    DriverDashboardView,
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
        'driver/dashboard/current-job/',
        DriverDashboardCurrentJobView.as_view(),
        name='driver_dashboard_current_job',
    ),
    path(
        'driver/dashboard/quick-actions/',
        DriverDashboardQuickActionsView.as_view(),
        name='driver_dashboard_quick_actions',
    ),
    path(
        'driver/dashboard/notifications-summary/',
        DriverDashboardNotificationsSummaryView.as_view(),
        name='driver_dashboard_notifications_summary',
    ),
    path(
        'driver/dashboard/recent-activity/',
        DriverDashboardRecentActivityView.as_view(),
        name='driver_dashboard_recent_activity',
    ),
    path(
        'driver/dashboard/summary/',
        DriverDashboardSummaryView.as_view(),
        name='driver_dashboard_summary',
    ),
    path(
        'driver/dashboard/',
        DriverDashboardView.as_view(),
        name='driver_dashboard',
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
]
