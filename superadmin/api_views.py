"""
Tenant-facing JSON API (CP Type B bridge).

State-changing endpoints use ``@csrf_exempt`` intentionally: authentication is
via ``X-Tenant-ID`` + API key (or dev-only ``TENANT_API_REQUIRE_KEY=False``),
not browser cookies.
"""
import json
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.contrib.auth.hashers import check_password

from .api_auth import resolve_tenant_api_request
from .audit_helpers import get_client_ip
from .models import (
    ActiveSession,
    CommLog,
    Country,
    PushDeviceToken,
    PushNotificationReceipt,
    SubscriptionOrder,
    SupportCategory,
    SupportTicket,
    TenantProfile,
    TicketReply,
)


def _tenant_or_error(request):
    tenant, err = resolve_tenant_api_request(request)
    if err is not None:
        return None, err
    return tenant, None


@csrf_exempt
@require_http_methods(["GET"])
def tenant_ticket_list(request):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    tickets = SupportTicket.objects.filter(
        tenant=tenant,
    ).select_related('category').order_by('-created_at')

    status = request.GET.get('status')
    if status:
        tickets = tickets.filter(status=status)

    data = []
    for t in tickets:
        data.append({
            'ticket_id': str(t.ticket_id),
            'ticket_no': t.ticket_no,
            'subject': t.subject,
            'category': t.category.name_en,
            'priority': t.priority,
            'status': t.status,
            'created_at': t.created_at.isoformat(),
            'closed_at': t.closed_at.isoformat() if t.closed_at else None,
        })

    return JsonResponse({'tickets': data}, status=200)


@csrf_exempt
@require_http_methods(["GET"])
def tenant_ticket_detail(request, ticket_id):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        ticket = SupportTicket.objects.select_related('category').get(
            ticket_id=ticket_id,
            tenant=tenant,
        )
    except SupportTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket not found'}, status=404)

    replies = ticket.replies.filter(
        is_internal=False,
    ).order_by('created_at')

    replies_data = []
    for r in replies:
        replies_data.append({
            'reply_id': str(r.reply_id),
            'sender_type': r.sender_type,
            'message_body': r.message_body,
            'attachment': r.attachment.url if r.attachment else None,
            'created_at': r.created_at.isoformat(),
        })

    data = {
        'ticket_id': str(ticket.ticket_id),
        'ticket_no': ticket.ticket_no,
        'subject': ticket.subject,
        'category': ticket.category.name_en,
        'priority': ticket.priority,
        'status': ticket.status,
        'created_at': ticket.created_at.isoformat(),
        'closed_at': ticket.closed_at.isoformat() if ticket.closed_at else None,
        'replies': replies_data,
    }
    return JsonResponse({'ticket': data}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def tenant_ticket_create(request):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    subject = body.get('subject', '').strip()
    category_id = body.get('category_id')
    created_by = body.get('created_by', 'tenant_user')

    if not subject:
        return JsonResponse({'error': 'Subject is required'}, status=400)

    try:
        category = SupportCategory.objects.get(
            category_id=category_id,
            is_active=True,
        )
    except SupportCategory.DoesNotExist:
        return JsonResponse({'error': 'Invalid category'}, status=400)

    ticket = SupportTicket.objects.create(
        ticket_no=SupportTicket.generate_ticket_no(),
        tenant=tenant,
        subject=subject,
        category=category,
        priority='Medium',
        status='New',
        created_by=created_by,
    )

    TicketReply.objects.create(
        ticket=ticket,
        sender_type='System_Bot',
        sender_id='SYSTEM',
        message_body=(
            f"Ticket {ticket.ticket_no} has been "
            f"created. Our support team will review "
            f"your issue shortly."
        ),
        is_internal=False,
    )

    return JsonResponse({
        'ticket_id': str(ticket.ticket_id),
        'ticket_no': ticket.ticket_no,
        'status': ticket.status,
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def tenant_ticket_reply(request, ticket_id):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        ticket = SupportTicket.objects.get(ticket_id=ticket_id, tenant=tenant)
    except SupportTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket not found'}, status=404)

    if ticket.status == 'Closed':
        return JsonResponse({
            'error': 'Cannot reply to a closed ticket. Please open a new ticket.',
        }, status=403)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    message = body.get('message_body', '').strip()
    sender_id = body.get('sender_id', 'tenant_user')

    if not message:
        return JsonResponse({'error': 'Message body is required'}, status=400)

    TicketReply.objects.create(
        ticket=ticket,
        sender_type='Tenant_User',
        sender_id=sender_id,
        message_body=message,
        is_internal=False,
    )

    if ticket.status != 'Closed':
        ticket.status = 'In_Progress'
        ticket.save()

    return JsonResponse({
        'message': 'Reply submitted successfully.',
        'ticket_status': ticket.status,
    }, status=201)


@csrf_exempt
@require_http_methods(["GET"])
def tenant_category_list(request):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    categories = SupportCategory.objects.filter(
        is_active=True,
    ).order_by('name_en')

    data = [
        {
            'category_id': str(c.category_id),
            'name_en': c.name_en,
            'name_ar': c.name_ar,
        }
        for c in categories
    ]
    return JsonResponse({'categories': data}, status=200)


@csrf_exempt
@require_http_methods(["GET"])
def tenant_billing_order_list(request):
    """List subscription orders for the authenticated tenant (read-only)."""
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    orders = SubscriptionOrder.objects.filter(tenant=tenant).order_by(
        '-created_at',
    )[:100]

    data = []
    for o in orders:
        data.append({
            'order_id': str(o.order_id),
            'classification': o.order_classification,
            'status': o.order_status,
            'currency': o.currency_id,
            'sub_total': str(o.sub_total),
            'discount_amount': str(o.discount_amount),
            'tax_amount': str(o.tax_amount),
            'grand_total': str(o.grand_total),
            'created_at': o.created_at.isoformat(),
        })
    return JsonResponse({'orders': data}, status=200)


@csrf_exempt
@require_http_methods(["GET"])
def tenant_billing_order_detail(request, order_id):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        order = SubscriptionOrder.objects.select_related(
            'currency',
            'payment_method',
        ).get(order_id=order_id, tenant=tenant)
    except SubscriptionOrder.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

    plan_lines = []
    for pl in order.plan_lines.select_related('plan').all():
        pname = (pl.plan_name_en_snapshot or '').strip()
        if not pname and pl.plan_id:
            pname = pl.plan.plan_name_en
        plan_lines.append({
            'plan_id': str(pl.plan_id),
            'plan_name': pname,
            'number_of_cycles': pl.number_of_cycles,
            'plan_price': str(pl.plan_price),
            'pro_rata_adjustment': str(pl.pro_rata_adjustment),
            'line_total': str(pl.line_total),
        })

    payload = {
        'order_id': str(order.order_id),
        'classification': order.order_classification,
        'status': order.order_status,
        'currency': order.currency_id,
        'sub_total': str(order.sub_total),
        'discount_amount': str(order.discount_amount),
        'tax_amount': str(order.tax_amount),
        'grand_total': str(order.grand_total),
        'base_currency_equivalent': str(order.base_currency_equivalent),
        'exchange_rate_snapshot': str(order.exchange_rate_snapshot),
        'created_at': order.created_at.isoformat(),
        'plan_lines': plan_lines,
    }
    if order.payment_method_id:
        payload['payment_method'] = order.payment_method.method_name_en
    return JsonResponse({'order': payload}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def tenant_session_register(request):
    """
    Called by the tenant workspace after login: records Redis session + CP
    ActiveSession row for Kill Switch / session monitor.
    """
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    user_domain = body.get('user_domain', 'Tenant_User')
    if user_domain not in ('Tenant_User', 'Driver'):
        return JsonResponse({'error': 'user_domain must be Tenant_User or Driver'}, status=400)

    reference_id = (body.get('reference_id') or '').strip()
    if not reference_id:
        return JsonResponse({'error': 'reference_id is required'}, status=400)

    reference_name = (body.get('reference_name') or '').strip()
    jti_in = (body.get('jti') or '').strip()
    try:
        sid = uuid.UUID(jti_in) if jti_in else uuid.uuid4()
    except ValueError:
        return JsonResponse({'error': 'jti must be a UUID string'}, status=400)
    jti = str(sid)

    from superadmin.models import TenantSecuritySettings

    sec = TenantSecuritySettings.objects.first()
    timeout_min = 12 * 60
    if sec:
        if user_domain == 'Driver':
            timeout_min = max(60, int(sec.driver_app_timeout_days or 1) * 24 * 60)
        else:
            timeout_min = max(60, int(sec.tenant_web_timeout_hours or 12) * 60)

    from superadmin.redis_helpers import create_tenant_session

    create_tenant_session(
        str(tenant.tenant_id),
        user_domain,
        reference_id,
        reference_name,
        get_client_ip(request),
        request.META.get('HTTP_USER_AGENT', ''),
        timeout_min,
        jti=jti,
    )

    ActiveSession.objects.create(
        session_id=sid,
        user_domain=user_domain,
        reference_id=reference_id,
        reference_name=reference_name or None,
        tenant=tenant,
        redis_jti=jti,
        ip_address=get_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '') or '')[:500],
        is_active=True,
    )

    return JsonResponse({'jti': jti, 'timeout_minutes': timeout_min}, status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def tenant_profile_sync(request):
    """
    Push subscriber profile fields from tenant workspace to master CRM (CP-PCS-P5).
    Auth: same as other bridge routes (X-Tenant-ID + API key when required).
    """
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({'error': 'Body must be a JSON object'}, status=400)

    allowed = (
        'company_name',
        'registration_number',
        'primary_email',
        'primary_phone',
        'tax_number',
        'country_code',
    )
    updates = {k: body.get(k) for k in allowed if k in body}
    if not updates:
        return JsonResponse(
            {'error': f'Provide at least one of: {", ".join(allowed)}'},
            status=400,
        )

    if 'company_name' in updates:
        name = (updates['company_name'] or '').strip()
        if not name:
            return JsonResponse({'error': 'company_name cannot be empty'}, status=400)
        if len(name) > 100:
            return JsonResponse({'error': 'company_name too long'}, status=400)
        tenant.company_name = name

    if 'registration_number' in updates:
        reg = (updates['registration_number'] or '').strip()
        if not reg:
            return JsonResponse(
                {'error': 'registration_number cannot be empty'},
                status=400,
            )
        if len(reg) > 50:
            return JsonResponse(
                {'error': 'registration_number too long'},
                status=400,
            )
        tenant.registration_number = reg

    if 'primary_email' in updates:
        email = (updates['primary_email'] or '').strip().lower()
        if not email:
            return JsonResponse({'error': 'primary_email cannot be empty'}, status=400)
        if len(email) > 100:
            return JsonResponse({'error': 'primary_email too long'}, status=400)
        duplicate_exists = TenantProfile.objects.filter(
            primary_email__iexact=email
        ).exclude(pk=tenant.pk).exists()
        if duplicate_exists:
            return JsonResponse(
                {'error': 'primary_email already used by another tenant'},
                status=400,
            )
        tenant.primary_email = email

    if 'primary_phone' in updates:
        phone = (updates['primary_phone'] or '').strip()
        if not phone:
            return JsonResponse({'error': 'primary_phone cannot be empty'}, status=400)
        if len(phone) > 20:
            return JsonResponse({'error': 'primary_phone too long'}, status=400)
        tenant.primary_phone = phone

    if 'tax_number' in updates:
        raw = updates['tax_number']
        tenant.tax_number = (raw or '').strip() or None
        if tenant.tax_number and len(tenant.tax_number) > 50:
            return JsonResponse({'error': 'tax_number too long'}, status=400)

    if 'country_code' in updates:
        code = (updates['country_code'] or '').strip().upper()
        if not code:
            tenant.country = None
        else:
            country = Country.objects.filter(
                country_code=code,
                is_active=True,
            ).first()
            if not country:
                return JsonResponse(
                    {'error': f'Unknown or inactive country_code: {code}'},
                    status=400,
                )
            tenant.country = country

    tenant.save()

    return JsonResponse({
        'tenant_id': str(tenant.tenant_id),
        'company_name': tenant.company_name,
        'registration_number': tenant.registration_number,
        'primary_email': tenant.primary_email,
        'primary_phone': tenant.primary_phone,
        'tax_number': tenant.tax_number or '',
        'country_code': tenant.country_id if tenant.country_id else None,
        'updated_at': tenant.updated_at.isoformat(),
    }, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def tenant_bootstrap_auth(request):
    """
    First workspace sign-in using email + one-time password from welcome mail.
    Requires X-Tenant-ID (from handover). Returns JWT with tenant_id + jti for
    session registration — not a substitute for full IAM.
    """
    tenant_id = (request.headers.get('X-Tenant-ID') or '').strip()
    if not tenant_id:
        return JsonResponse({'error': 'Missing X-Tenant-ID header'}, status=401)

    tenant = TenantProfile.objects.filter(tenant_id=tenant_id).first()
    if not tenant:
        return JsonResponse({'error': 'Invalid credentials'}, status=401)
    if tenant.account_status != 'Active':
        return JsonResponse({'error': 'Tenant account is not active'}, status=403)

    if not (tenant.portal_bootstrap_password_hash or '').strip():
        return JsonResponse(
            {'error': 'Bootstrap password not available; use your workspace login.'},
            status=403,
        )

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    email = (body.get('email') or '').strip()
    password = body.get('password') or ''
    if not email or not password:
        return JsonResponse({'error': 'email and password required'}, status=400)

    if email.strip().lower() != tenant.primary_email.strip().lower():
        return JsonResponse({'error': 'Invalid credentials'}, status=401)
    if not check_password(password, tenant.portal_bootstrap_password_hash):
        return JsonResponse({'error': 'Invalid credentials'}, status=401)

    from .tenant_jwt import sign_tenant_access_jwt

    ttl = max(60, int(settings.TENANT_BOOTSTRAP_JWT_TTL_SECONDS))
    token_str, jti = sign_tenant_access_jwt(
        tenant_id=tenant.tenant_id,
        subject=tenant.primary_email,
        token_type='tenant_bootstrap',
        ttl_seconds=ttl,
    )

    return JsonResponse({
        'access_token': token_str,
        'token_type': 'Bearer',
        'expires_in': ttl,
        'tenant_id': str(tenant.tenant_id),
        'jti': jti,
    }, status=200)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def tenant_push_token_upsert(request):
    """
    Register or update tenant-user/driver push token for FCM delivery.
    """
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    token = (body.get('device_token') or '').strip()
    user_domain = (body.get('user_domain') or 'Tenant_User').strip()
    reference_id = (body.get('reference_id') or '').strip()
    is_active = body.get('is_active', True)

    if not token:
        return JsonResponse({'error': 'device_token is required'}, status=400)
    if user_domain not in ('Tenant_User', 'Driver'):
        return JsonResponse({'error': 'user_domain must be Tenant_User or Driver'}, status=400)
    if not reference_id:
        return JsonResponse({'error': 'reference_id is required'}, status=400)

    obj, _created = PushDeviceToken.objects.update_or_create(
        device_token=token,
        defaults={
            'tenant': tenant,
            'user_domain': user_domain,
            'reference_id': reference_id,
            'is_active': bool(is_active),
        },
    )
    return JsonResponse({
        'token_id': str(obj.token_id),
        'device_token': obj.device_token,
        'user_domain': obj.user_domain,
        'reference_id': obj.reference_id,
        'is_active': obj.is_active,
        'updated_at': obj.updated_at.isoformat(),
    }, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def tenant_push_token_deactivate(request):
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    token = (body.get('device_token') or '').strip()
    if not token:
        return JsonResponse({'error': 'device_token is required'}, status=400)

    qs = PushDeviceToken.objects.filter(tenant=tenant, device_token=token)
    updated = qs.update(is_active=False)
    if not updated:
        return JsonResponse({'error': 'Token not found for tenant'}, status=404)
    return JsonResponse({'status': 'deactivated', 'device_token': token}, status=200)


@csrf_exempt
@require_http_methods(["GET"])
def tenant_push_notifications(request):
    """
    Fetch recently dispatched push notifications for the authenticated tenant.
    Supports filters: user_domain, reference_id, limit, offset.
    """
    tenant, err = _tenant_or_error(request)
    if err:
        return err

    user_domain = (request.GET.get('user_domain') or '').strip()
    reference_id = (request.GET.get('reference_id') or '').strip()
    try:
        limit = max(1, min(100, int(request.GET.get('limit', 20))))
    except ValueError:
        limit = 20
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except ValueError:
        offset = 0

    qs = PushNotificationReceipt.objects.filter(tenant=tenant).order_by('-created_at')
    if user_domain in ('Tenant_User', 'Driver'):
        qs = qs.filter(user_domain=user_domain)
    if reference_id:
        qs = qs.filter(reference_id=reference_id)

    total = qs.count()
    rows = qs[offset:offset + limit]

    data = [
        {
            'receipt_id': str(r.receipt_id),
            'notification_id': str(r.notification_id) if r.notification_id else None,
            'title': r.title,
            'message': r.message,
            'action_link': r.action_link,
            'event_code': r.event_code,
            'delivery_status': r.delivery_status,
            'error_details': r.error_details or '',
            'user_domain': r.user_domain,
            'reference_id': r.reference_id,
            'created_at': r.created_at.isoformat(),
        }
        for r in rows
    ]

    # Backward-compatible fallback: if receipt table is empty, return recent push logs.
    if total == 0:
        tokens_qs = PushDeviceToken.objects.filter(tenant=tenant, is_active=True)
        if user_domain in ('Tenant_User', 'Driver'):
            tokens_qs = tokens_qs.filter(user_domain=user_domain)
        if reference_id:
            tokens_qs = tokens_qs.filter(reference_id=reference_id)
        token_values = list(tokens_qs.values_list('device_token', flat=True))
        log_qs = CommLog.objects.filter(
            channel_type='Push',
            recipient__in=token_values,
        ).order_by('-dispatched_at')
        log_total = log_qs.count()
        log_rows = log_qs[offset:offset + limit]
        data = [
            {
                'receipt_id': str(l.log_id),
                'notification_id': None,
                'title': l.trigger_source,
                'message': '',
                'action_link': None,
                'event_code': None,
                'delivery_status': l.delivery_status,
                'error_details': l.error_details or '',
                'user_domain': user_domain or '',
                'reference_id': reference_id or '',
                'created_at': l.dispatched_at.isoformat() if l.dispatched_at else '',
            }
            for l in log_rows
        ]
        return JsonResponse({
            'count': len(data),
            'total': log_total,
            'limit': limit,
            'offset': offset,
            'notifications': data,
        }, status=200)

    return JsonResponse({
        'count': len(data),
        'total': total,
        'limit': limit,
        'offset': offset,
        'notifications': data,
    }, status=200)
