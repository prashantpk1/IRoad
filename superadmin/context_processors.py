from superadmin.models import InternalAlertNotification


def internal_alert_notifications(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {
            'internal_alert_items': [],
            'internal_alert_unread_count': 0,
        }

    qs = InternalAlertNotification.objects.filter(
        admin_user=request.user
    ).order_by('-created_at')
    return {
        'internal_alert_items': list(qs[:10]),
        'internal_alert_unread_count': qs.filter(is_read=False).count(),
    }
