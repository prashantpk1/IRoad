"""
Audit Job Detail production readiness (alias for verify_job_detail_readiness).
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Verify Job Detail indexes and middleware (delegates to verify_job_detail_readiness).'

    def add_arguments(self, parser):
        parser.add_argument('--schema', action='append', dest='schemas')
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--skip-middleware', action='store_true')

    def handle(self, *args, **options):
        argv = []
        if options.get('schemas'):
            for schema in options['schemas']:
                argv.append(f'--schema={schema}')
        if options.get('json'):
            argv.append('--json')
        if options.get('skip_middleware'):
            argv.append('--skip-middleware')
        call_command('verify_job_detail_readiness', *argv)
