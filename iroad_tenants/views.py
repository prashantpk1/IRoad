from django.shortcuts import redirect, render
from django.views import View
from superadmin.models import TenantProfile
from superadmin.redis_helpers import revoke_tenant_session_key


def _tenant_context_from_session(request):
    tenant_id = request.session.get('tenant_bootstrap_tenant_id')
    tenant = None
    if tenant_id:
        tenant = TenantProfile.objects.filter(pk=tenant_id).first()
    if tenant is None:
        return None
    display_name = (tenant.company_name or 'Tenant User').strip()
    display_email = (tenant.primary_email or 'tenant@example.com').strip()
    return {
        'tenant': tenant,
        'display_name': display_name,
        'display_email': display_email,
        'display_role': 'Tenant Admin',
        'avatar_name': display_name.replace(' ', '+'),
    }


class TenantDashboardView(View):
    """Tenant dashboard rendered from app template copy."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            return redirect('login')
        return render(request, 'iroad_tenants/index.html', context)


class TenantMyAccountView(View):
    """Tenant self account summary page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            return redirect('login')
        return render(request, 'iroad_tenants/my_account.html', context)


class TenantLogoutView(View):
    """Clear tenant session and redirect to login."""

    def get(self, request):
        self._clear_tenant_session(request)
        return redirect('login')

    def post(self, request):
        self._clear_tenant_session(request)
        return redirect('login')

    @staticmethod
    def _clear_tenant_session(request):
        tenant_id = request.session.get('tenant_bootstrap_tenant_id')
        jti = request.session.get('tenant_bootstrap_jti')
        if tenant_id and jti:
            revoke_tenant_session_key(str(tenant_id), str(jti))
        for key in (
            'tenant_bootstrap_token',
            'tenant_bootstrap_tenant_id',
            'tenant_bootstrap_jti',
            'tenant_bootstrap_expires_in',
        ):
            request.session.pop(key, None)
