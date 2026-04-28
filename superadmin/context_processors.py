from superadmin.models import InternalAlertNotification
from django.urls import NoReverseMatch, reverse


def internal_alert_notifications(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {
            'internal_alert_items': [],
            'internal_alert_unread_count': 0,
        }

    qs = InternalAlertNotification.objects.filter(
        admin_user=request.user
    ).order_by('-created_at')

    def _target_url_for(item):
        payload = item.context_payload or {}
        try:
            if item.trigger_event == 'New_Tenant_Registered':
                tenant_id = payload.get('tenant_id')
                if tenant_id:
                    return reverse('tenant_detail', kwargs={'pk': tenant_id})
            elif item.trigger_event == 'Bank_Transfer_Pending':
                order_id = payload.get('order_id')
                if order_id:
                    return reverse('order_detail', kwargs={'pk': order_id})
            elif item.trigger_event == 'Payment_Failed':
                txn_id = payload.get('transaction_id')
                if txn_id:
                    return reverse('transaction_detail', kwargs={'pk': txn_id})
                order_id = payload.get('order_id')
                if order_id:
                    return reverse('order_detail', kwargs={'pk': order_id})
            elif item.trigger_event == 'High_Priority_Ticket':
                ticket_id = payload.get('ticket_id')
                if ticket_id:
                    return reverse('ticket_detail', kwargs={'pk': ticket_id})
            elif item.trigger_event == 'Subscription_Expired':
                tenant_id = payload.get('tenant_id')
                if tenant_id:
                    return reverse('tenant_detail', kwargs={'pk': tenant_id})
        except NoReverseMatch:
            return ''
        return ''

    items = list(qs[:100])
    for item in items:
        item.target_url = _target_url_for(item)

    return {
        'internal_alert_items': items,
        'internal_alert_unread_count': qs.filter(is_read=False).count(),
    }
