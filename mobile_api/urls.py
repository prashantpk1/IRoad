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
    DriverLogoutView,
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

app_name = 'mobile_api'

urlpatterns = [
    path(
        'driver/auth/login/',
        DriverLoginView.as_view(),
        name='driver_login',
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
]

