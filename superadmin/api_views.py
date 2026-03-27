import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import (
    SupportTicket,
    TicketReply,
    SupportCategory,
    TenantProfile,
)


def get_tenant_from_request(request):
    """
    Extract tenant_id from request header.
    Tenant API must pass X-Tenant-ID header.
    Returns TenantProfile or None.
    """
    tenant_id = request.headers.get('X-Tenant-ID')
    if not tenant_id:
        return None
    try:
        return TenantProfile.objects.get(
            tenant_id=tenant_id,
            account_status='Active',
        )
    except TenantProfile.DoesNotExist:
        return None


@csrf_exempt
@require_http_methods(["GET"])
def tenant_ticket_list(request):
    tenant = get_tenant_from_request(request)
    if not tenant:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    tickets = SupportTicket.objects.filter(
        tenant=tenant
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
    tenant = get_tenant_from_request(request)
    if not tenant:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        ticket = SupportTicket.objects.select_related('category').get(
            ticket_id=ticket_id,
            tenant=tenant,
        )
    except SupportTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket not found'}, status=404)

    replies = ticket.replies.filter(
        is_internal=False
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
    tenant = get_tenant_from_request(request)
    if not tenant:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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
    tenant = get_tenant_from_request(request)
    if not tenant:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        ticket = SupportTicket.objects.get(ticket_id=ticket_id, tenant=tenant)
    except SupportTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket not found'}, status=404)

    if ticket.status == 'Closed':
        return JsonResponse({
            'error': 'Cannot reply to a closed ticket. Please open a new ticket.'
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
    tenant = get_tenant_from_request(request)
    if not tenant:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    categories = SupportCategory.objects.filter(
        is_active=True
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

