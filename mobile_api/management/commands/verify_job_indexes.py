"""Alias: audit job-list PostgreSQL indexes (same as verify_job_list_readiness)."""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Alias for verify_job_list_readiness — audit job-list indexes per tenant schema.'

    def add_arguments(self, parser):
        parser.add_argument('--schema', action='append', dest='schemas')
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        call_command(
            'verify_job_list_readiness',
            *([f'--schema={s}' for s in options['schemas']] if options.get('schemas') else []),
            *(['--json'] if options.get('json') else []),
        )
