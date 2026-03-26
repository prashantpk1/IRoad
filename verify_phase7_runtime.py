from datetime import timedelta
import uuid

from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from superadmin.forms import (
    CommGatewayForm,
    EventMappingForm,
    InternalAlertRouteForm,
    NotificationTemplateForm,
    PushNotificationForm,
    SystemBannerForm,
)
from superadmin.models import (
    AdminUser,
    CommGateway,
    CommLog,
    EventMapping,
    InternalAlertRoute,
    NotificationTemplate,
    PushNotification,
    SystemBanner,
)


if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append('testserver')

results = []


def record(item, ok, err=''):
    results.append({'item': item, 'ok': bool(ok), 'err': err})


def check(item, fn):
    try:
        ok, err = fn()
        record(item, ok, err)
    except Exception as exc:  # noqa: BLE001
        record(item, False, f'{type(exc).__name__}: {exc}')


suffix = uuid.uuid4().hex[:8]
root = AdminUser.objects.filter(is_root=True).first()
if not root:
    root = AdminUser(
        first_name='Root',
        last_name='Admin',
        email=f'root_{suffix}@iroad.local',
        status='Active',
        is_root=True,
    )
    root.set_password('Root@12345')
    root.save()

client = Client()
client.raise_request_exception = False
client.force_login(root)


# MODELS
check('CommGateway model exists with UUID PK', lambda: (CommGateway._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {CommGateway._meta.pk.__class__.__name__}'))
check('gateway_type choices: Email, SMS only', lambda: (set(dict(CommGateway.GATEWAY_TYPE_CHOICES).keys()) == {'Email', 'SMS'}, f'choices={list(dict(CommGateway.GATEWAY_TYPE_CHOICES).keys())}'))
check('password_secret field exists', lambda: ('password_secret' in [f.name for f in CommGateway._meta.fields], 'password_secret missing'))
check('is_active default False on CommGateway', lambda: (CommGateway._meta.get_field('is_active').default is False, f"default={CommGateway._meta.get_field('is_active').default}"))
check('NotificationTemplate model exists with UUID PK', lambda: (NotificationTemplate._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {NotificationTemplate._meta.pk.__class__.__name__}'))
check('template_name is unique', lambda: (NotificationTemplate._meta.get_field('template_name').unique, 'template_name.unique is False'))
check('subject_en and subject_ar nullable', lambda: (NotificationTemplate._meta.get_field('subject_en').null and NotificationTemplate._meta.get_field('subject_ar').null, f"subject_en.null={NotificationTemplate._meta.get_field('subject_en').null}, subject_ar.null={NotificationTemplate._meta.get_field('subject_ar').null}"))
check('body_en and body_ar required TextFields', lambda: (NotificationTemplate._meta.get_field('body_en').__class__.__name__ == 'TextField' and NotificationTemplate._meta.get_field('body_ar').__class__.__name__ == 'TextField' and not NotificationTemplate._meta.get_field('body_en').null and not NotificationTemplate._meta.get_field('body_ar').null, 'body fields not required TextField'))
check('EventMapping model exists with UUID PK', lambda: (EventMapping._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {EventMapping._meta.pk.__class__.__name__}'))
check('system_event has unique=True constraint', lambda: (EventMapping._meta.get_field('system_event').unique, 'system_event.unique is False'))
check('SYSTEM_EVENT_CHOICES has 12 events', lambda: (len(EventMapping.SYSTEM_EVENT_CHOICES) == 12, f'count={len(EventMapping.SYSTEM_EVENT_CHOICES)}'))
check('fallback_channel and fallback_template nullable', lambda: (EventMapping._meta.get_field('fallback_channel').null and EventMapping._meta.get_field('fallback_template').null, 'fallback fields are not nullable'))
check('PushNotification model exists with UUID PK', lambda: (PushNotification._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {PushNotification._meta.pk.__class__.__name__}'))
check('trigger_mode choices: Manual_Broadcast, System_Event', lambda: (set(dict(PushNotification.TRIGGER_MODE_CHOICES).keys()) == {'Manual_Broadcast', 'System_Event'}, f'choices={list(dict(PushNotification.TRIGGER_MODE_CHOICES).keys())}'))
check('SystemBanner model exists with UUID PK', lambda: (SystemBanner._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {SystemBanner._meta.pk.__class__.__name__}'))
check('is_expired property exists on SystemBanner', lambda: (hasattr(SystemBanner, 'is_expired'), 'is_expired property missing'))
check('severity choices: Info, Warning, Critical', lambda: (set(dict(SystemBanner.SEVERITY_CHOICES).keys()) == {'Info', 'Warning', 'Critical'}, f'choices={list(dict(SystemBanner.SEVERITY_CHOICES).keys())}'))
check('InternalAlertRoute model exists with UUID PK', lambda: (InternalAlertRoute._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {InternalAlertRoute._meta.pk.__class__.__name__}'))
check('TRIGGER_EVENT_CHOICES has 6 events', lambda: (len(InternalAlertRoute.TRIGGER_EVENT_CHOICES) == 6, f'count={len(InternalAlertRoute.TRIGGER_EVENT_CHOICES)}'))
check('CommLog model exists with UUID PK', lambda: (CommLog._meta.pk.__class__.__name__ == 'UUIDField', f'PK type is {CommLog._meta.pk.__class__.__name__}'))


def _commlog_immutable_save():
    log = CommLog.objects.create(
        recipient=f'user_{suffix}@mail.com',
        channel_type='Email',
        trigger_source='Event: OTP_Requested',
        delivery_status='Sent',
    )
    log.delivery_status = 'Failed'
    try:
        log.save()
    except PermissionError:
        return True, ''
    return False, 'CommLog.save() update did not raise PermissionError'


def _commlog_immutable_delete():
    log = CommLog.objects.create(
        recipient=f'user2_{suffix}@mail.com',
        channel_type='Email',
        trigger_source='Event: OTP_Requested',
        delivery_status='Sent',
    )
    try:
        log.delete()
    except PermissionError:
        return True, ''
    return False, 'CommLog.delete() did not raise PermissionError'


check('CommLog save() raises on update attempt', _commlog_immutable_save)
check('CommLog delete() raises on delete attempt', _commlog_immutable_delete)


# FORMS
check('CommGatewayForm port required for Email type', lambda: (not CommGatewayForm(data={'gateway_type': 'Email', 'provider_name': 'X', 'host_url': 'smtp.x.com', 'port': '', 'username_key': 'u', 'password_secret': 's', 'sender_id': 'from@x.com', 'encryption_type': 'TLS', 'is_active': False}).is_valid(), str(CommGatewayForm(data={'gateway_type': 'Email', 'provider_name': 'X', 'host_url': 'smtp.x.com', 'port': '', 'username_key': 'u', 'password_secret': 's', 'sender_id': 'from@x.com', 'encryption_type': 'TLS', 'is_active': False}).errors)))
check('CommGatewayForm password uses PasswordInput widget', lambda: (CommGatewayForm().fields['password_secret'].widget.__class__.__name__ == 'PasswordInput', f"widget={CommGatewayForm().fields['password_secret'].widget.__class__.__name__}"))
check('NotificationTemplateForm subject required for Email', lambda: (not NotificationTemplateForm(data={'template_name': f'TplE_{suffix}', 'channel_type': 'Email', 'category': 'Transactional', 'subject_en': '', 'subject_ar': '', 'body_en': 'Hi', 'body_ar': 'Hi', 'is_active': True}).is_valid(), 'Email form unexpectedly valid without subjects'))
check('NotificationTemplateForm allows no subject for SMS', lambda: (NotificationTemplateForm(data={'template_name': f'TplS_{suffix}', 'channel_type': 'SMS', 'category': 'Transactional', 'subject_en': '', 'subject_ar': '', 'body_en': 'Hi', 'body_ar': 'Hi', 'is_active': True}).is_valid(), str(NotificationTemplateForm(data={'template_name': f'TplS_{suffix}', 'channel_type': 'SMS', 'category': 'Transactional', 'subject_en': '', 'subject_ar': '', 'body_en': 'Hi', 'body_ar': 'Hi', 'is_active': True}).errors)))

pt = NotificationTemplate.objects.create(
    template_name=f'EV_PRIMARY_{suffix}',
    channel_type='Email',
    category='Transactional',
    subject_en='a',
    subject_ar='b',
    body_en='body',
    body_ar='body',
    created_by=root,
)
ft = NotificationTemplate.objects.create(
    template_name=f'EV_FALLBACK_{suffix}',
    channel_type='SMS',
    category='Transactional',
    body_en='body',
    body_ar='body',
    created_by=root,
)

check('EventMappingForm fallback channel same as primary blocked', lambda: (not EventMappingForm(data={'system_event': 'OTP_Requested', 'primary_channel': 'Email', 'primary_template': str(pt.pk), 'fallback_channel': 'Email', 'fallback_template': str(pt.pk), 'is_active': True}).is_valid(), 'fallback same as primary unexpectedly valid'))
check('EventMappingForm template channel mismatch blocked', lambda: (not EventMappingForm(data={'system_event': 'Password_Changed', 'primary_channel': 'SMS', 'primary_template': str(pt.pk), 'fallback_channel': '', 'fallback_template': '', 'is_active': True}).is_valid(), 'template mismatch unexpectedly valid'))
check('EventMappingForm fallback template required when fallback channel set', lambda: (not EventMappingForm(data={'system_event': 'Invoice_Paid', 'primary_channel': 'Email', 'primary_template': str(pt.pk), 'fallback_channel': 'SMS', 'fallback_template': '', 'is_active': True}).is_valid(), 'missing fallback template unexpectedly valid'))
check('PushNotificationForm linked_event required for System_Event mode', lambda: (not PushNotificationForm(data={'internal_name': f'P1_{suffix}', 'title_en': 't', 'title_ar': 't', 'message_en': 'm', 'message_ar': 'm', 'action_link': '', 'trigger_mode': 'System_Event', 'linked_event': '', 'target_audience': '', 'specific_target_id': '', 'scheduled_at': '', 'is_active': True, 'dispatch_status': 'Draft'}).is_valid(), 'linked_event not enforced'))
check('PushNotificationForm target_audience required for Manual_Broadcast', lambda: (not PushNotificationForm(data={'internal_name': f'P2_{suffix}', 'title_en': 't', 'title_ar': 't', 'message_en': 'm', 'message_ar': 'm', 'action_link': '', 'trigger_mode': 'Manual_Broadcast', 'linked_event': '', 'target_audience': '', 'specific_target_id': '', 'scheduled_at': '', 'is_active': True, 'dispatch_status': 'Draft'}).is_valid(), 'target_audience not enforced'))
check('SystemBannerForm valid_until before valid_from blocked', lambda: (not SystemBannerForm(data={'title_en': 't', 'title_ar': 't', 'message_en': 'm', 'message_ar': 'm', 'severity': 'Info', 'is_dismissible': True, 'valid_from': '2026-01-02T10:00', 'valid_until': '2026-01-01T10:00', 'is_active': True}).is_valid(), 'valid_until < valid_from unexpectedly valid'))
check('InternalAlertRouteForm both role and email empty blocked', lambda: (not InternalAlertRouteForm(data={'trigger_event': 'System_Error', 'notify_role': '', 'notify_custom_email': '', 'is_active': True}).is_valid(), 'both empty unexpectedly valid'))


# COMM GATEWAYS
secret_value = f'SECRET_{suffix}'
g1 = CommGateway.objects.create(
    gateway_type='Email',
    provider_name=f'P1_{suffix}',
    host_url='smtp1.test',
    port=587,
    username_key='u1',
    password_secret=secret_value,
    sender_id='noreply@test.com',
    encryption_type='TLS',
    is_active=True,
    updated_by=root,
)
check('/comm/gateways/ list loads', lambda: (client.get('/comm/gateways/').status_code == 200, f"status={client.get('/comm/gateways/').status_code}"))
check('Password never shown in list', lambda: (secret_value not in client.get('/comm/gateways/').content.decode('utf-8', errors='ignore'), 'password_secret leaked in list HTML'))


def _create_gateway():
    resp = client.post('/comm/gateways/create/', data={
        'gateway_type': 'Email',
        'provider_name': f'P2_{suffix}',
        'host_url': 'smtp2.test',
        'port': 465,
        'username_key': 'u2',
        'password_secret': 'secret2',
        'sender_id': 'ops@test.com',
        'encryption_type': 'SSL',
        'is_active': 'on',
    })
    exists = CommGateway.objects.filter(provider_name=f'P2_{suffix}', gateway_type='Email').exists()
    return (resp.status_code in [302, 301] and exists, f"status={resp.status_code}, exists={exists}")


check('Create Email gateway works', _create_gateway)
check('Activating gateway deactivates other of same type', lambda: ((CommGateway.objects.filter(gateway_type='Email', is_active=True).count() == 1), f"active_email_count={CommGateway.objects.filter(gateway_type='Email', is_active=True).count()}"))

sms1 = CommGateway.objects.create(gateway_type='SMS', provider_name=f'S1_{suffix}', host_url='https://sms1.test', username_key='k1', password_secret='s1', sender_id='IROAD', is_active=True, updated_by=root)
sms2 = CommGateway.objects.create(gateway_type='SMS', provider_name=f'S2_{suffix}', host_url='https://sms2.test', username_key='k2', password_secret='s2', sender_id='IROAD', is_active=False, updated_by=root)
client.post(reverse('comm_gateway_toggle', kwargs={'pk': sms2.gateway_id}))
check('Only one active Email and one active SMS at a time', lambda: (CommGateway.objects.filter(gateway_type='Email', is_active=True).count() <= 1 and CommGateway.objects.filter(gateway_type='SMS', is_active=True).count() <= 1, f"email_active={CommGateway.objects.filter(gateway_type='Email', is_active=True).count()}, sms_active={CommGateway.objects.filter(gateway_type='SMS', is_active=True).count()}"))
check('Test Connection button visible but disabled', lambda: (('Test Connection' in client.get('/comm/gateways/create/').content.decode('utf-8', errors='ignore')) and ('disabled' in client.get('/comm/gateways/create/').content.decode('utf-8', errors='ignore')), 'button missing or not disabled'))
check('Port hidden for SMS type', lambda: ("portWrap.style.display = isEmail ? 'block' : 'none';" in client.get('/comm/gateways/create/').content.decode('utf-8', errors='ignore'), 'JS hide/show for port not found'))
check('Delete redirects with error', lambda: ((client.get(reverse('comm_gateway_delete', kwargs={'pk': g1.gateway_id}), follow=True).redirect_chain != []) and ('cannot be deleted' in client.get(reverse('comm_gateway_delete', kwargs={'pk': g1.gateway_id}), follow=True).content.decode('utf-8', errors='ignore').lower()), 'no redirect or error message missing'))


# NOTIFICATION TEMPLATES
check('/comm/templates/ list loads', lambda: (client.get('/comm/templates/').status_code == 200, f"status={client.get('/comm/templates/').status_code}"))


def _create_email_tpl():
    resp = client.post('/comm/templates/create/', data={
        'template_name': f'EMAIL_OK_{suffix}',
        'channel_type': 'Email',
        'category': 'Transactional',
        'subject_en': 'Subject EN',
        'subject_ar': 'Subject AR',
        'body_en': 'Body EN',
        'body_ar': 'Body AR',
        'is_active': 'on',
    })
    ok = NotificationTemplate.objects.filter(template_name=f'EMAIL_OK_{suffix}').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


def _create_sms_tpl():
    resp = client.post('/comm/templates/create/', data={
        'template_name': f'SMS_OK_{suffix}',
        'channel_type': 'SMS',
        'category': 'Transactional',
        'subject_en': '',
        'subject_ar': '',
        'body_en': 'Body EN',
        'body_ar': 'Body AR',
        'is_active': 'on',
    })
    ok = NotificationTemplate.objects.filter(template_name=f'SMS_OK_{suffix}').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


check('Create Email template with subjects works', _create_email_tpl)
check('Create SMS template without subjects works', _create_sms_tpl)
check('Subject required error shows for Email without subject', lambda: ('Subject (English) is required for Email templates.' in client.post('/comm/templates/create/', data={'template_name': f'EMAIL_BAD_{suffix}', 'channel_type': 'Email', 'category': 'Transactional', 'subject_en': '', 'subject_ar': '', 'body_en': 'Body EN', 'body_ar': 'Body AR', 'is_active': 'on'}).content.decode('utf-8', errors='ignore'), 'expected subject required error not found'))
check('Variables reference box visible on form', lambda: ('Available Variables' in client.get('/comm/templates/create/').content.decode('utf-8', errors='ignore'), 'variables box missing'))

t_for_toggle = NotificationTemplate.objects.create(template_name=f'TOGGLE_{suffix}', channel_type='SMS', category='Transactional', body_en='B', body_ar='B', created_by=root, is_active=True)
client.post(reverse('notif_template_toggle', kwargs={'pk': t_for_toggle.template_id}))
t_for_toggle.refresh_from_db()
check('Toggle status works', lambda: (t_for_toggle.is_active is False, f'is_active={t_for_toggle.is_active}'))
check('Delete redirects with error', lambda: ((client.get(reverse('notif_template_delete', kwargs={'pk': t_for_toggle.template_id}), follow=True).redirect_chain != []) and ('cannot be deleted' in client.get(reverse('notif_template_delete', kwargs={'pk': t_for_toggle.template_id}), follow=True).content.decode('utf-8', errors='ignore').lower()), 'no redirect or delete error missing'))


# EVENTS MAPPING
check('/comm/events/ list loads', lambda: (client.get('/comm/events/').status_code == 200, f"status={client.get('/comm/events/').status_code}"))
check('Unmapped events show as warning rows', lambda: ('Not Configured' in client.get('/comm/events/').content.decode('utf-8', errors='ignore'), 'Not Configured warning rows not found'))


def _create_mapping():
    resp = client.post('/comm/events/create/', data={
        'system_event': 'Welcome_Email',
        'primary_channel': 'Email',
        'primary_template': str(pt.pk),
        'fallback_channel': 'SMS',
        'fallback_template': str(ft.pk),
        'is_active': 'on',
    })
    ok = EventMapping.objects.filter(system_event='Welcome_Email').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


check('Create mapping works', _create_mapping)
check('Duplicate system_event mapping blocked', lambda: ('A mapping already exists for this event. Edit it instead.' in client.post('/comm/events/create/', data={'system_event': 'Welcome_Email', 'primary_channel': 'Email', 'primary_template': str(pt.pk), 'fallback_channel': '', 'fallback_template': '', 'is_active': 'on'}).content.decode('utf-8', errors='ignore'), 'duplicate mapping error not shown'))
check('Fallback same channel as primary blocked', lambda: ('Fallback channel cannot be same as primary channel.' in client.post('/comm/events/create/', data={'system_event': 'Subscription_Activated', 'primary_channel': 'Email', 'primary_template': str(pt.pk), 'fallback_channel': 'Email', 'fallback_template': str(pt.pk), 'is_active': 'on'}).content.decode('utf-8', errors='ignore'), 'fallback same channel error missing'))
m = EventMapping.objects.get(system_event='Welcome_Email')
client.post(reverse('event_mapping_toggle', kwargs={'pk': m.mapping_id}))
m.refresh_from_db()
check('Toggle status works', lambda: (m.is_active is False, f'is_active={m.is_active}'))


# PUSH
check('/comm/push/ list loads', lambda: (client.get('/comm/push/').status_code == 200, f"status={client.get('/comm/push/').status_code}"))


def _create_system_push():
    resp = client.post('/comm/push/create/', data={
        'internal_name': f'SYS_PUSH_{suffix}',
        'title_en': 'Title EN',
        'title_ar': 'Title AR',
        'message_en': 'Message EN',
        'message_ar': 'Message AR',
        'action_link': '',
        'trigger_mode': 'System_Event',
        'linked_event': 'OTP_Requested',
        'target_audience': '',
        'specific_target_id': '',
        'scheduled_at': '',
        'is_active': 'on',
        'dispatch_status': 'Draft',
    })
    ok = PushNotification.objects.filter(internal_name=f'SYS_PUSH_{suffix}').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


def _create_manual_push():
    resp = client.post('/comm/push/create/', data={
        'internal_name': f'MAN_PUSH_{suffix}',
        'title_en': 'Title EN',
        'title_ar': 'Title AR',
        'message_en': 'Message EN',
        'message_ar': 'Message AR',
        'action_link': '',
        'trigger_mode': 'Manual_Broadcast',
        'linked_event': '',
        'target_audience': 'All',
        'specific_target_id': '',
        'scheduled_at': '',
        'is_active': 'on',
        'dispatch_status': 'Draft',
    })
    ok = PushNotification.objects.filter(internal_name=f'MAN_PUSH_{suffix}').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


check('Create System_Event push works', _create_system_push)
check('Create Manual_Broadcast push works', _create_manual_push)
completed_push = PushNotification.objects.create(
    internal_name=f'COMP_PUSH_{suffix}',
    title_en='a',
    title_ar='a',
    message_en='m',
    message_ar='m',
    trigger_mode='Manual_Broadcast',
    target_audience='All',
    dispatch_status='Completed',
    created_by=root,
)
check('Editing Completed push is blocked', lambda: (client.get(reverse('push_notif_edit', kwargs={'pk': completed_push.notification_id}), follow=True).redirect_chain != [] and 'cannot be edited' in client.get(reverse('push_notif_edit', kwargs={'pk': completed_push.notification_id}), follow=True).content.decode('utf-8', errors='ignore').lower(), 'completed push edit not blocked'))


# BANNERS
check('/comm/banners/ list loads', lambda: (client.get('/comm/banners/').status_code == 200, f"status={client.get('/comm/banners/').status_code}"))


def _create_banner():
    resp = client.post('/comm/banners/create/', data={
        'title_en': f'Banner_{suffix}',
        'title_ar': 'Banner AR',
        'message_en': 'Message EN',
        'message_ar': 'Message AR',
        'severity': 'Info',
        'is_dismissible': 'on',
        'valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'),
        'valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
        'is_active': 'on',
    })
    ok = SystemBanner.objects.filter(title_en=f'Banner_{suffix}').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


check('Create banner works', _create_banner)
SystemBanner.objects.create(
    title_en=f'Expired_{suffix}',
    title_ar='Expired AR',
    message_en='Expired msg',
    message_ar='Expired msg',
    severity='Warning',
    valid_from=timezone.now() - timedelta(days=2),
    valid_until=timezone.now() - timedelta(days=1),
    is_active=True,
)
check('Expired banner shows EXPIRED badge', lambda: ('EXPIRED' in client.get('/comm/banners/').content.decode('utf-8', errors='ignore'), 'EXPIRED badge missing'))
check('Severity colors correct in list', lambda: ('bg-primary' in client.get('/comm/banners/').content.decode('utf-8', errors='ignore') and 'bg-warning' in client.get('/comm/banners/').content.decode('utf-8', errors='ignore') and 'bg-danger' in client.get('/comm/banners/').content.decode('utf-8', errors='ignore'), 'severity color classes missing'))
b = SystemBanner.objects.filter(title_en=f'Banner_{suffix}').first()
client.post(reverse('banner_toggle', kwargs={'pk': b.banner_id}))
b.refresh_from_db()
check('Toggle status works', lambda: (b.is_active is False, f'is_active={b.is_active}'))


# INTERNAL ALERTS
check('/comm/alert-routes/ list loads', lambda: (client.get('/comm/alert-routes/').status_code == 200, f"status={client.get('/comm/alert-routes/').status_code}"))


def _create_route():
    resp = client.post('/comm/alert-routes/create/', data={
        'trigger_event': 'System_Error',
        'notify_role': '',
        'notify_custom_email': f'alerts_{suffix}@iroad.local',
        'is_active': 'on',
    })
    ok = InternalAlertRoute.objects.filter(notify_custom_email=f'alerts_{suffix}@iroad.local').exists()
    return (resp.status_code in [302, 301] and ok, f"status={resp.status_code}, exists={ok}")


check('Create route works', _create_route)
check('Empty role and email both blocked with error', lambda: ('At least one of Role or Custom Email must be provided.' in client.post('/comm/alert-routes/create/', data={'trigger_event': 'Payment_Failed', 'notify_role': '', 'notify_custom_email': '', 'is_active': 'on'}).content.decode('utf-8', errors='ignore'), 'expected validation message missing'))
r = InternalAlertRoute.objects.filter(notify_custom_email=f'alerts_{suffix}@iroad.local').first()
client.post(reverse('alert_route_toggle', kwargs={'pk': r.route_id}))
r.refresh_from_db()
check('Toggle status works', lambda: (r.is_active is False, f'is_active={r.is_active}'))


# COMM LOGS
log_a = CommLog.objects.create(recipient=f'chan_email_{suffix}@mail.com', channel_type='Email', trigger_source='Event: OTP_Requested', delivery_status='Sent')
log_b = CommLog.objects.create(recipient=f'chan_sms_{suffix}', channel_type='SMS', trigger_source='Event: OTP_Requested', delivery_status='Failed')
check('/comm/logs/ list loads', lambda: (client.get('/comm/logs/').status_code == 200, f"status={client.get('/comm/logs/').status_code}"))
check('Filter by channel works', lambda: (f'chan_sms_{suffix}' not in client.get('/comm/logs/?channel=Email').content.decode('utf-8', errors='ignore'), 'SMS record still shown when channel=Email'))
check('Filter by delivery status works', lambda: (f'chan_email_{suffix}' not in client.get('/comm/logs/?status=Failed').content.decode('utf-8', errors='ignore'), 'Sent record still shown when status=Failed'))
log_html = client.get('/comm/logs/').content.decode('utf-8', errors='ignore')
check('No edit or delete buttons anywhere', lambda: ('/comm/logs/' in log_html and 'Edit' not in log_html and 'Delete' not in log_html, 'Found Edit/Delete text in comm logs page'))
check('CommLog immutability confirmed', _commlog_immutable_save)


# SIDEBAR + links
sidebar_html = client.get('/dashboard/').content.decode('utf-8', errors='ignore')
check('Communication & Alerts has all 7 sub-items', lambda: (all(x in sidebar_html for x in ['Gateway Settings', 'Notification Templates', 'Events Mapping', 'Push Notifications', 'System Banners', 'Internal Alerts', 'Comm Logs']), 'one or more sidebar sub-items missing'))


def _all_links_work():
    urls = [
        '/comm/gateways/',
        '/comm/templates/',
        '/comm/events/',
        '/comm/push/',
        '/comm/banners/',
        '/comm/alert-routes/',
        '/comm/logs/',
    ]
    bad = []
    for u in urls:
        status = client.get(u).status_code
        if status != 200:
            bad.append(f'{u} -> {status}')
    if bad:
        return False, '; '.join(bad)
    return True, ''


check('All sub-item links work correctly', _all_links_work)

print(results)
