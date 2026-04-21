from django.urls import path

from .views import TenantDashboardView, TenantLogoutView, TenantMyAccountView

app_name = 'iroad_tenants'


urlpatterns = [
    path('dashboard/', TenantDashboardView.as_view(), name='tenant_dashboard'),
    path('my-account/', TenantMyAccountView.as_view(), name='tenant_my_account'),
    path('logout/', TenantLogoutView.as_view(), name='tenant_logout'),
]
