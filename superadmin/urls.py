from django.urls import path
from django.views.generic import RedirectView

from .views import (
    AccessLogListView,
    CountryCreateView,
    CountryDeleteView,
    CountryListView,
    CountryToggleStatusView,
    CountryUpdateView,
    CurrencyCreateView,
    CurrencyDeleteView,
    CurrencyListView,
    CurrencyToggleStatusView,
    CurrencyUpdateView,
    DashboardView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    ResetPasswordConfirmView,
    SetPasswordView,
    AdminUserCreateView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserToggleStatusView,
    AdminUserUpdateView,
    SystemUsersAnalyticsView,
    RoleCreateView,
    RoleDeleteView,
    RoleListView,
    RoleToggleStatusView,
    RoleUpdateView,
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path(
        'reset-password/',
        ForgotPasswordView.as_view(),
        name='reset_password',
    ),
    path(
        'new-password/<str:token>/',
        ResetPasswordConfirmView.as_view(),
        name='new_password',
    ),
    path(
        'set-password/<str:token>/',
        SetPasswordView.as_view(),
        name='set_password',
    ),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('roles/', RoleListView.as_view(), name='role_list'),
    path('roles/create/', RoleCreateView.as_view(), name='role_create'),
    path('roles/<uuid:pk>/edit/', RoleUpdateView.as_view(), name='role_edit'),
    path(
        'roles/<uuid:pk>/toggle-status/',
        RoleToggleStatusView.as_view(),
        name='role_toggle_status',
    ),
    path(
        'roles/<uuid:pk>/delete/',
        RoleDeleteView.as_view(),
        name='role_delete',
    ),
    path('admin-users/', AdminUserListView.as_view(), name='admin_user_list'),
    path(
        'admin-users/create/',
        AdminUserCreateView.as_view(),
        name='admin_user_create',
    ),
    path(
        'admin-users/<uuid:pk>/',
        AdminUserDetailView.as_view(),
        name='admin_user_detail',
    ),
    path(
        'admin-users/<uuid:pk>/edit/',
        AdminUserUpdateView.as_view(),
        name='admin_user_edit',
    ),
    path(
        'admin-users/<uuid:pk>/toggle-status/',
        AdminUserToggleStatusView.as_view(),
        name='admin_user_toggle_status',
    ),
    path(
        'system-users/analytics/',
        SystemUsersAnalyticsView.as_view(),
        name='users_analytics',
    ),
    path(
        'security/access-log/',
        AccessLogListView.as_view(),
        name='access_log',
    ),
    path(
        'master-data/countries/',
        CountryListView.as_view(),
        name='country_list',
    ),
    path(
        'master-data/countries/create/',
        CountryCreateView.as_view(),
        name='country_create',
    ),
    path(
        'master-data/countries/<str:pk>/edit/',
        CountryUpdateView.as_view(),
        name='country_edit',
    ),
    path(
        'master-data/countries/<str:pk>/toggle-status/',
        CountryToggleStatusView.as_view(),
        name='country_toggle_status',
    ),
    path(
        'master-data/countries/<str:pk>/delete/',
        CountryDeleteView.as_view(),
        name='country_delete',
    ),
    path(
        'master-data/currencies/',
        CurrencyListView.as_view(),
        name='currency_list',
    ),
    path(
        'master-data/currencies/create/',
        CurrencyCreateView.as_view(),
        name='currency_create',
    ),
    path(
        'master-data/currencies/<str:pk>/edit/',
        CurrencyUpdateView.as_view(),
        name='currency_edit',
    ),
    path(
        'master-data/currencies/<str:pk>/toggle-status/',
        CurrencyToggleStatusView.as_view(),
        name='currency_toggle_status',
    ),
    path(
        'master-data/currencies/<str:pk>/delete/',
        CurrencyDeleteView.as_view(),
        name='currency_delete',
    ),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
]

