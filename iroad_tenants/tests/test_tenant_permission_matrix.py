import csv
import io
from datetime import datetime, timezone
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.tenant_permission_matrix import (
    TENANT_PERMISSION_FLAGS,
    resolve_canonical_form_name,
    resolve_canonical_permission_location,
)
from iroad_tenants.views import (
    _build_tenant_roles_permissions_csv_response,
    _merge_permission_flags,
    _permissions_by_key,
)


class _PermissionStub:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _PermissionsStub:
    def __init__(self, permissions):
        self._permissions = permissions

    def all(self):
        return self._permissions


class _RoleStub:
    def __init__(self, permissions, **role_fields):
        self.permissions = _PermissionsStub(permissions)
        self.role_id = role_fields.get('role_id', uuid4())
        self.role_name_en = role_fields.get('role_name_en', 'Administration')
        self.role_name_ar = role_fields.get('role_name_ar', 'Administration')
        self.description_en = role_fields.get('description_en', 'This is admin')
        self.description_ar = role_fields.get('description_ar', '')
        self.created_by_label = role_fields.get('created_by_label', 'System')
        self.status = role_fields.get('status', 'Active')
        self.created_at = role_fields.get(
            'created_at',
            datetime(2024, 5, 29, 7, 9, 0, 393705, tzinfo=timezone.utc),
        )
        self.updated_at = role_fields.get('updated_at', None)


class TenantPermissionMatrixTests(SimpleTestCase):
    def test_resolve_canonical_form_name_maps_legacy_labels(self):
        self.assertEqual(
            resolve_canonical_form_name('Shipment POD Analysis'),
            'Shipment PODs',
        )
        self.assertEqual(
            resolve_canonical_form_name('Sales Invoicing'),
            'Sales Invoice Report',
        )
        self.assertEqual(resolve_canonical_form_name('Booking'), 'Booking')

    def test_resolve_canonical_permission_location_maps_sidebar_modules(self):
        self.assertEqual(
            resolve_canonical_permission_location('Administration', 'Organization Profile'),
            ('Account Management', 'Organization Profile'),
        )
        self.assertEqual(
            resolve_canonical_permission_location('Operations', 'Shipment POD Analysis'),
            ('Operations Management', 'Shipment PODs'),
        )
        self.assertEqual(
            resolve_canonical_permission_location('Finance', 'Sales Invoicing'),
            ('Sales Invoicing', 'Sales Invoice Report'),
        )

    def test_permissions_by_key_maps_legacy_module_form_to_canonical_matrix_key(self):
        role = _RoleStub(
            [
                _PermissionStub(
                    module_name='Operations',
                    form_name='Shipment POD Analysis',
                    can_access=True,
                    can_write=True,
                    can_read=True,
                    can_view=True,
                    can_edit=True,
                    can_export=True,
                    can_approve=True,
                    can_print=True,
                )
            ]
        )
        perms = _permissions_by_key(role)
        self.assertTrue(perms['Operations Management|Shipment PODs']['can_view'])
        self.assertTrue(perms['Operations Management|Shipment PODs']['can_export'])

    def test_merge_permission_flags_combines_duplicate_rows(self):
        merged = _merge_permission_flags(
            {'can_view': False, 'can_export': True},
            {'can_view': True, 'can_export': False},
        )
        self.assertTrue(merged['can_view'])
        self.assertTrue(merged['can_export'])
        self.assertEqual(set(merged.keys()), set(TENANT_PERMISSION_FLAGS))

    def test_roles_permissions_export_uses_sidebar_matrix_labels(self):
        role = _RoleStub(
            [
                _PermissionStub(
                    module_name='Operations',
                    form_name='Shipment POD Analysis',
                    can_access=True,
                    can_write=True,
                    can_read=True,
                    can_view=True,
                    can_edit=True,
                    can_export=True,
                    can_approve=True,
                    can_print=True,
                )
            ]
        )
        response = _build_tenant_roles_permissions_csv_response([role])
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        permission_rows = [
            row
            for row in rows
            if len(row) >= 11
            and row[1] == 'Operations Management'
            and row[2] == 'Shipment PODs'
        ]
        self.assertEqual(len(permission_rows), 1)
        self.assertEqual(
            permission_rows[0][3:],
            ['Yes', 'Yes', 'Yes', 'Yes', 'Yes', 'Yes', 'Yes', 'Yes'],
        )
