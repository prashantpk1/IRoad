from django.core.management.base import BaseCommand

from superadmin.models import InternalAlertRoute, Role


class Command(BaseCommand):
    help = (
        'Create/update Internal Alert Routes for selected roles and optional '
        'custom email across chosen trigger events.'
    )

    DEFAULT_EVENTS = [
        'New_Tenant_Registered',
        'High_Priority_Ticket',
        'Payment_Failed',
        'Subscription_Expired',
        'Bank_Transfer_Pending',
        'System_Error',
    ]

    ROLE_ALIASES = {
        'superadmin': 'super admin',
        'super_admin': 'super admin',
        'staff': 'staff',
        'sales': 'sales',
        'support': 'support',
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--roles',
            default='Super Admin,Staff,Sales',
            help=(
                'Comma-separated role names. Example: '
                '"Super Admin,Staff,Sales".'
            ),
        )
        parser.add_argument(
            '--custom-email',
            default='',
            help='Optional custom email recipient added for each selected event.',
        )
        parser.add_argument(
            '--events',
            default=','.join(self.DEFAULT_EVENTS),
            help=(
                'Comma-separated event codes from InternalAlertRoute choices. '
                f'Default: {",".join(self.DEFAULT_EVENTS)}'
            ),
        )
        parser.add_argument(
            '--inactive',
            action='store_true',
            help='Create/update routes as inactive (default is active).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would change without writing to DB.',
        )

    def handle(self, *args, **options):
        role_inputs = self._split_csv(options.get('roles', ''))
        custom_email = (options.get('custom_email') or '').strip().lower()
        event_inputs = self._split_csv(options.get('events', ''))
        is_active = not options.get('inactive', False)
        dry_run = bool(options.get('dry_run'))

        if not role_inputs and not custom_email:
            self.stderr.write(
                self.style.ERROR(
                    'Provide at least one role (--roles) or --custom-email.',
                ),
            )
            return

        valid_events = {code for code, _ in InternalAlertRoute.TRIGGER_EVENT_CHOICES}
        invalid_events = [evt for evt in event_inputs if evt not in valid_events]
        if invalid_events:
            self.stderr.write(
                self.style.ERROR(
                    f'Invalid event code(s): {", ".join(invalid_events)}',
                ),
            )
            self.stdout.write(
                f'Allowed events: {", ".join(sorted(valid_events))}',
            )
            return

        roles, missing_roles = self._resolve_roles(role_inputs)
        if role_inputs and not roles:
            self.stderr.write(
                self.style.ERROR(
                    'No roles matched. Check role names from Role master.',
                ),
            )
            return

        if missing_roles:
            self.stdout.write(
                self.style.WARNING(
                    f'Unmatched role inputs skipped: {", ".join(missing_roles)}',
                ),
            )

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        self.stdout.write(
            'Applying internal alert routes for events: '
            + ', '.join(event_inputs),
        )
        if roles:
            self.stdout.write(
                'Matched roles: ' + ', '.join(role.role_name_en for role in roles),
            )
        if custom_email:
            self.stdout.write(f'Custom email: {custom_email}')
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run mode: no DB changes.'))

        for event_code in event_inputs:
            for role in roles:
                changed, state = self._upsert_route(
                    trigger_event=event_code,
                    notify_role=role,
                    notify_custom_email=None,
                    is_active=is_active,
                    dry_run=dry_run,
                )
                if changed == 'created':
                    created_count += 1
                elif changed == 'updated':
                    updated_count += 1
                else:
                    unchanged_count += 1
                self.stdout.write(
                    f'[{state}] {event_code} -> role:{role.role_name_en}',
                )

            if custom_email:
                changed, state = self._upsert_route(
                    trigger_event=event_code,
                    notify_role=None,
                    notify_custom_email=custom_email,
                    is_active=is_active,
                    dry_run=dry_run,
                )
                if changed == 'created':
                    created_count += 1
                elif changed == 'updated':
                    updated_count += 1
                else:
                    unchanged_count += 1
                self.stdout.write(
                    f'[{state}] {event_code} -> email:{custom_email}',
                )

        self.stdout.write(
            self.style.SUCCESS(
                'Done. '
                f'created={created_count}, '
                f'updated={updated_count}, '
                f'unchanged={unchanged_count}',
            ),
        )

    def _resolve_roles(self, role_inputs):
        roles = []
        missing = []
        for raw in role_inputs:
            normalized = self._normalize_role_input(raw)
            matched = (
                Role.objects.filter(role_name_en__iexact=normalized)
                .order_by('role_name_en')
                .first()
            )
            if not matched:
                matched = (
                    Role.objects.filter(role_name_en__icontains=normalized)
                    .order_by('role_name_en')
                    .first()
                )
            if matched:
                if matched not in roles:
                    roles.append(matched)
            else:
                missing.append(raw)
        return roles, missing

    def _normalize_role_input(self, value):
        key = (value or '').strip().lower()
        return self.ROLE_ALIASES.get(key, (value or '').strip())

    def _upsert_route(
        self,
        *,
        trigger_event,
        notify_role,
        notify_custom_email,
        is_active,
        dry_run,
    ):
        existing = InternalAlertRoute.objects.filter(
            trigger_event=trigger_event,
            notify_role=notify_role,
            notify_custom_email=notify_custom_email,
        ).first()

        if existing:
            if existing.is_active == is_active:
                return 'unchanged', 'UNCHANGED'
            if not dry_run:
                existing.is_active = is_active
                existing.save(update_fields=['is_active'])
            return 'updated', 'UPDATED'

        if not dry_run:
            InternalAlertRoute.objects.create(
                trigger_event=trigger_event,
                notify_role=notify_role,
                notify_custom_email=notify_custom_email,
                is_active=is_active,
            )
        return 'created', 'CREATED'

    @staticmethod
    def _split_csv(value):
        return [item.strip() for item in (value or '').split(',') if item.strip()]
