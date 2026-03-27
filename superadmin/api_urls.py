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
]

