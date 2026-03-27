from decimal import Decimal
import json


def get_client_ip(request):
    """Extract real IP from request headers."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def model_to_dict_safe(instance):
    """
    Convert model instance to JSON-safe dict.
    Handles UUID, Decimal, datetime, FK fields.
    """
    from django.forms.models import model_to_dict
    import uuid
    from datetime import datetime, date

    data = {}
    for field in instance._meta.fields:
        value = getattr(instance, field.name, None)
        if value is None:
            data[field.name] = None
        elif isinstance(value, uuid.UUID):
            data[field.name] = str(value)
        elif isinstance(value, Decimal):
            data[field.name] = float(value)
        elif isinstance(value, (datetime, date)):
            data[field.name] = value.isoformat()
        elif hasattr(value, 'pk'):
            # FK field — store PK only
            data[field.name] = str(value.pk)
        else:
            data[field.name] = value
    return data


def log_audit_action(
        request,
        action_type,
        module_name,
        record_id,
        old_instance=None,
        new_instance=None):
    """
    Record an immutable audit log entry.

    Usage in views:
    
    # On Create:
    log_audit_action(request, 'Create',
        'Subscription Plans', str(plan.plan_id),
        new_instance=plan)

    # On Update:
    log_audit_action(request, 'Update',
        'Tax Settings', str(tax.tax_code),
        old_instance=old_obj, new_instance=new_obj)

    # On Status Change:
    log_audit_action(request, 'Status_Change',
        'Tenant Profile', str(tenant.tenant_id),
        old_instance=old_obj, new_instance=new_obj)

    # On Delete:
    log_audit_action(request, 'Delete',
        'Country', str(country.country_code),
        old_instance=old_obj)
    """
    from .models import AuditLog

    old_payload = None
    new_payload = None

    if old_instance is not None:
        try:
            old_payload = model_to_dict_safe(old_instance)
        except Exception:
            old_payload = {'error': 'Could not serialize'}

    if new_instance is not None:
        try:
            new_payload = model_to_dict_safe(new_instance)
        except Exception:
            new_payload = {'error': 'Could not serialize'}

    try:
        AuditLog(
            admin=request.user
                if hasattr(request, 'user')
                and request.user.is_authenticated
                else None,
            action_type=action_type,
            module_name=module_name,
            record_id=str(record_id),
            old_payload=old_payload,
            new_payload=new_payload,
            ip_address=get_client_ip(request),
        ).save()
    except Exception as e:
        # Never let audit logging break the main operation
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Audit log failed: {e}")


def create_session(request, user, user_domain):
    """
    Register a new active session on login.
    Called from LoginView after successful authentication.
    """
    from .models import ActiveSession
    import uuid

    session = ActiveSession(
        session_id=uuid.uuid4(),
        user_domain=user_domain,
        reference_id=str(user.admin_id)
            if hasattr(user, 'admin_id')
            else str(user.pk),
        reference_name=(
            f"{user.first_name} {user.last_name}"
            if hasattr(user, 'first_name')
            else str(user)),
        ip_address=get_client_ip(request),
        user_agent=request.META.get(
            'HTTP_USER_AGENT', '')[:500],
        is_active=True,
    )
    # Store session_id in Django session for later revocation
    session.save()
    request.session['active_session_id'] = \
        str(session.session_id)

    # TODO Phase 11 Redis: Also store JWT JTI in
    # Redis with TTL for real-time revocation here.
    return session


def close_session(request):
    """
    Mark session as inactive on logout.
    Called from LogoutView.
    """
    from .models import ActiveSession

    session_id = request.session.get('active_session_id')
    if session_id:
        try:
            session = ActiveSession.objects.get(
                session_id=session_id, is_active=True)
            from django.utils import timezone
            session.is_active = False
            session.revoked_at = timezone.now()
            session.save()
        except ActiveSession.DoesNotExist:
            pass

    # TODO Phase 11 Redis: Also revoke JWT token
    # from Redis here.
