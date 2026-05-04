"""
Run with project venv from repo root:
  .\\env\\Scripts\\python.exe scratch\\validate_address_master_form.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def main():
    import django

    django.setup()

    from django.db import connection, transaction
    from django_tenants.utils import schema_context

    from superadmin.models import Country
    from tenant_workspace.models import TenantAddressMaster, TenantClientAccount
    from iroad_tenants.models import TenantRegistry
    from iroad_tenants.forms_tenant_address import TenantAddressMasterForm
    from iroad_tenants.views import (
        ADDRESS_MASTER_AUTO_FORM_CODE,
        ADDRESS_MASTER_AUTO_FORM_LABEL,
        ADDRESS_MASTER_REF_PREFIX,
        _next_auto_number_for_form,
    )

    results = []

    def ok(msg):
        results.append(('OK', msg))

    def fail(msg):
        results.append(('FAIL', msg))

    with schema_context('public'):
        country = Country.objects.filter(is_active=True).first()
        if not country:
            fail('No active Country rows in public master — cannot validate')
            _print(results)
            return 2

    connection.set_schema_to_public()
    reg = None
    client = None
    for cand in TenantRegistry.objects.all():
        connection.set_tenant(cand)
        client = TenantClientAccount.objects.order_by('-created_at').first()
        if client is not None:
            reg = cand
            break
    connection.set_schema_to_public()
    if reg is None or client is None:
        fail(
            'No tenant schema with TenantClientAccount — create a client '
            '(or tenants) before address CRUD smoke test'
        )
        _print(results)
        return 2

    connection.set_tenant(reg)
    ok(f'Using tenant schema={getattr(connection, "schema_name", "?")} client={client.account_no}')

    cat = TenantAddressMaster.AddressCategory.PICKUP_ADDRESS
    base_post = {
        'client_account': str(client.account_id),
        'display_name': '__CRUD validation smoke test',
        'address_category': cat,
        'status': TenantAddressMaster.Status.ACTIVE,
        'province': 'Riyadh',
        'city': 'Riyadh',
        'district': '',
        'street': '',
        'building_no': '',
        'postal_code': '',
        'address_line_1': 'Line 1 test',
        'address_line_2': '',
        'map_link': '',
        'site_instructions': '',
        'contact_name': '',
        'position': '',
        'mobile_no_1': '0501234567',
        'mobile_no_2': '',
        'whatsapp_no': '',
        'phone_no': '',
        'email': '',
        'arabic_label': '',
        'english_label': '',
        'country': country.country_code,
    }

    form = TenantAddressMasterForm(data=base_post)
    if form.is_valid():
        ok('Create-form: valid minimal POST')
        choices = getattr(form.fields['country'], 'choices', [])
        try:
            flat = list(choices)
        except TypeError:
            flat = []
        nc = sum(1 for cv, lbl in flat if cv not in ('', None))
        if nc >= 1:
            ok(f'Country field has {nc} selectable countries (dropdown not empty)')
        else:
            fail('Country field has no selectable options')
    else:
        fail(f'Create-form should be valid: {form.errors.as_json()}')

    bad_mob = {**base_post, 'mobile_no_1': 'abc'}
    f2 = TenantAddressMasterForm(data=bad_mob)
    if not f2.is_valid() and 'mobile_no_1' in f2.errors:
        ok('Invalid mobile rejected')
    else:
        fail('Invalid mobile should fail mobile_no_1')

    bad_co = {**base_post, 'country': '^^INVALID^^'}
    f3 = TenantAddressMasterForm(data=bad_co)
    if not f3.is_valid():
        ok('Invalid country PK rejected')
    else:
        fail('Invalid country should fail validation')

    miss = dict(base_post)
    miss['display_name'] = ''
    miss['country'] = ''
    f4 = TenantAddressMasterForm(data=miss)
    if not f4.is_valid():
        ok('Missing required fields rejected')
    else:
        fail('Empty display_name/country should fail')

    if form.is_valid():
        sid = transaction.savepoint()
        try:
            code, seq = _next_auto_number_for_form(
                ADDRESS_MASTER_AUTO_FORM_CODE,
                ADDRESS_MASTER_AUTO_FORM_LABEL,
                ADDRESS_MASTER_REF_PREFIX,
            )
            addr = form.save(commit=False)
            addr.address_code = code
            addr.address_sequence = seq
            addr.save()
            ref = TenantAddressMaster.objects.get(pk=addr.address_id)
            if ref.country_id == country.country_code and ref.mobile_no_1 == '0501234567':
                ok(
                    'DB round-trip: saved country FK and normalized mobile '
                    f'(code={ref.address_code}, rolled back)'
                )
            else:
                fail(
                    f'FK mismatch saved country_id={ref.country_id} expected '
                    f'{country.country_code} mobile={ref.mobile_no_1}'
                )
        except Exception as e:
            fail(f'DB save exception: {type(e).__name__}: {e}')
        finally:
            transaction.savepoint_rollback(sid)

    addr_edit = TenantAddressMaster.objects.filter(
        status=TenantAddressMaster.Status.ACTIVE,
    ).first()
    if addr_edit and addr_edit.country_id:
        f5 = TenantAddressMasterForm(instance=addr_edit)
        fld = f5.fields['country']
        if fld.initial == addr_edit.country_id:
            ok(f'Edit form: country initial matches instance ({addr_edit.country_id})')
        else:
            fail(
                f'Edit country initial mismatch initial={fld.initial!r} '
                f'want={addr_edit.country_id!r}'
            )
    elif not addr_edit:
        ok('Edit preselect: SKIP (no address row to edit in tenant)')

    connection.set_schema_to_public()
    _print(results)
    return 0 if all(s == 'OK' for s, _ in results) else 1


def _print(results):
    for status, msg in results:
        print(f'[{status}] {msg}')


if __name__ == '__main__':
    raise SystemExit(main())
