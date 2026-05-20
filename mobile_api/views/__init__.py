"""View exports for mobile API."""

from mobile_api.views.base import MobileAPIView
from mobile_api.views.driver_auth import (
    DriverForgotPasswordView,
    DriverLoginView,
    DriverLogoutAllDevicesView,
    DriverLogoutView,
    DriverRefreshTokenView,
    DriverResetPasswordView,
    DriverVerifyOtpView,
)
from mobile_api.views.driver_profile import (
    DriverChangePasswordView,
    DriverProfilePhotoUpdateView,
    DriverProfileView,
    DriverRequestChangePasswordOtpView,
    DriverVerifyChangePasswordOtpView,
)

__all__ = [
    'MobileAPIView',
    'DriverChangePasswordView',
    'DriverLoginView',
    'DriverForgotPasswordView',
    'DriverRefreshTokenView',
    'DriverProfilePhotoUpdateView',
    'DriverProfileView',
    'DriverRequestChangePasswordOtpView',
    'DriverVerifyChangePasswordOtpView',
    'DriverVerifyOtpView',
    'DriverResetPasswordView',
    'DriverLogoutAllDevicesView',
    'DriverLogoutView',
]
