from django.urls import path

from . import api_views

urlpatterns = [
    path(
        'support/tickets/',
        api_views.tenant_ticket_list,
        name='api_ticket_list',
    ),
    path(
        'support/tickets/create/',
        api_views.tenant_ticket_create,
        name='api_ticket_create',
    ),
    path(
        'support/tickets/<uuid:ticket_id>/',
        api_views.tenant_ticket_detail,
        name='api_ticket_detail',
    ),
    path(
        'support/tickets/<uuid:ticket_id>/reply/',
        api_views.tenant_ticket_reply,
        name='api_ticket_reply',
    ),
    path(
        'support/categories/',
        api_views.tenant_category_list,
        name='api_category_list',
    ),
    path(
        'billing/orders/',
        api_views.tenant_billing_order_list,
        name='api_billing_order_list',
    ),
    path(
        'billing/orders/<uuid:order_id>/',
        api_views.tenant_billing_order_detail,
        name='api_billing_order_detail',
    ),
    path(
        'tenant/sessions/register/',
        api_views.tenant_session_register,
        name='api_tenant_session_register',
    ),
    path(
        'tenant/profile/sync/',
        api_views.tenant_profile_sync,
        name='api_tenant_profile_sync',
    ),
    path(
        'tenant/auth/bootstrap/',
        api_views.tenant_bootstrap_auth,
        name='api_tenant_bootstrap_auth',
    ),
]

