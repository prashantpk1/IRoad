from django.urls import path

from .views import (
    TenantAutoNumberConfigurationView,
    TenantDashboardView,
    TenantLogoutView,
    TenantMyAccountView,
    TenantOrganizationProfileEditView,
    TenantOrganizationProfileView,
)

app_name = 'iroad_tenants'


urlpatterns = [
    path('dashboard/', TenantDashboardView.as_view(), name='tenant_dashboard'),
    path(
        'administration/organization-profile/',
        TenantOrganizationProfileView.as_view(),
        name='tenant_organization_profile',
    ),
    path(
        'administration/organization-profile/edit/',
        TenantOrganizationProfileEditView.as_view(),
        name='tenant_organization_profile_edit',
    ),
    path(
        'configuration/auto-number/',
        TenantAutoNumberConfigurationView.as_view(),
        name='tenant_auto_number_configuration',
    ),
    path('my-account/', TenantMyAccountView.as_view(), name='tenant_my_account'),
    path('logout/', TenantLogoutView.as_view(), name='tenant_logout'),
]
