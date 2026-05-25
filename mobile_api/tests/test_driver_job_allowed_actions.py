"""
Allowed-actions API tests (engine + metadata projections).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.action_execution_metadata import (
    build_execution_requirements,
    project_allowed_action_row,
)
from mobile_api.serializers.driver_job_allowed_actions import (
    AllowedActionsPayloadSerializer,
)


class ActionMetadataTests(SimpleTestCase):
    def test_a5_metadata_requires_gps_not_photo(self):
        action = MagicMock()
        action.action_id = uuid4()
        action.action_code = 'A5'
        action.english_label = 'Depart In Transit'
        action.arabic_label = ''
        action.action_scope = 'Job'
        action.sequence_category = 'forward'
        action.sequence_number = 5
        action.auto_pod_post = False
        action.auto_movement_post = False
        action.auto_shipment_post = False
        action.hard_copy_collection = False
        action.shipment_status_impact = 'In Transit'
        action.movement_status_impact = ''
        action.booking_status_impact = ''

        row = project_allowed_action_row(action, current_stage='Loaded')
        self.assertTrue(row['requires_gps'])
        self.assertFalse(row['requires_photo'])

    def test_a7_metadata_requires_photo(self):
        action = MagicMock()
        action.action_id = uuid4()
        action.action_code = 'A7'
        action.english_label = 'Upload POD'
        action.arabic_label = ''
        action.action_scope = 'Job'
        action.sequence_category = 'forward'
        action.sequence_number = 7
        action.auto_pod_post = True
        action.auto_movement_post = False
        action.auto_shipment_post = False
        action.hard_copy_collection = False
        action.shipment_status_impact = 'POD Submitted'
        action.movement_status_impact = ''
        action.booking_status_impact = ''

        req = build_execution_requirements(action)
        self.assertTrue(req['photo'])
        self.assertTrue(req['auto_pod_post'])


class AllowedActionsSerializerTests(SimpleTestCase):
    def test_payload_schema_accepts_full_action_row(self):
        action_id = uuid4()
        job_id = uuid4()
        data = {
            'job_type': 'shipment',
            'job_id': str(job_id),
            'job_no': 'SH-001',
            'current_stage': 'In Transit',
            'context_label': 'Allowed actions for shipment status: In Transit',
            'count': 1,
            'workflow_source': 'operation_execution.get_allowed_actions',
            'actions': [
                {
                    'action_id': str(action_id),
                    'action_code': 'A5',
                    'action_name': 'Depart',
                    'execution_label': 'Depart',
                    'requires_gps': True,
                    'requires_photo': False,
                    'requires_video': False,
                    'requires_note': False,
                    'action_category': 'Job',
                    'execution_order': 5,
                    'sort_index': 0,
                    'current_stage': 'In Transit',
                    'execution_requirements': {
                        'gps': True,
                        'photo': False,
                        'photo_min_count': 0,
                        'video': False,
                        'video_min_count': 0,
                        'note': False,
                        'note_required': False,
                        'signature': False,
                        'auto_movement_post': False,
                        'auto_pod_post': False,
                        'auto_shipment_post': False,
                        'hard_copy_collection': False,
                        'shipment_status_impact': 'In Transit',
                        'movement_status_impact': '',
                    },
                }
            ],
            'primary_action': None,
        }
        data['primary_action'] = data['actions'][0]
        ser = AllowedActionsPayloadSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)


class AllowedActionsViewTests(SimpleTestCase):
    def test_shipment_actions_uses_engine_mock(self):
        from rest_framework.test import APIRequestFactory
        from mobile_api.views.driver_job_allowed_actions import (
            DriverShipmentAllowedActionsView,
        )

        action_id = uuid4()
        shipment_id = uuid4()
        factory = APIRequestFactory()
        request = factory.get(
            '/api/v1/mobile/driver/jobs/shipments/%s/actions/' % shipment_id,
        )
        request.auth = {
            'tenant_schema': 'tenant_a',
            'driver_id': str(uuid4()),
            'sub': str(uuid4()),
        }

        engine_payload = {
            'job_type': 'shipment',
            'job_id': str(shipment_id),
            'job_no': 'SH-1',
            'current_stage': 'In Transit',
            'context_label': 'ctx',
            'count': 1,
            'workflow_source': 'operation_execution.get_allowed_actions',
            'actions': [
                {
                    'action_id': str(action_id),
                    'action_code': 'A5',
                    'action_name': 'Depart',
                    'execution_label': 'Depart',
                    'requires_gps': True,
                    'requires_photo': False,
                    'requires_video': False,
                    'requires_note': False,
                    'action_category': 'Job',
                    'execution_order': 5,
                    'sort_index': 0,
                    'current_stage': 'In Transit',
                    'execution_requirements': {
                        'gps': True,
                        'photo': False,
                        'photo_min_count': 0,
                        'video': False,
                        'video_min_count': 0,
                        'note': False,
                        'note_required': False,
                        'signature': False,
                        'auto_movement_post': False,
                        'auto_pod_post': False,
                        'auto_shipment_post': False,
                        'hard_copy_collection': False,
                        'shipment_status_impact': 'In Transit',
                        'movement_status_impact': '',
                    },
                }
            ],
            'primary_action': None,
            'execution_state': {
                'shipment_status': 'In Transit',
                'derived_status': 'In Transit',
                'operational_stage': 'In Transit',
                'in_sync': True,
            },
        }
        engine_payload['primary_action'] = engine_payload['actions'][0]

        view = DriverShipmentAllowedActionsView.as_view()

        with patch(
            'mobile_api.permissions.HasDriverJobsAccess.has_permission',
            return_value=True,
        ):
            with patch(
                'mobile_api.permissions.IsMobileAuthenticated.has_permission',
                return_value=True,
            ):
                with patch(
                    'mobile_api.views.driver_job_detail.resolve_secure_job_list_context',
                    return_value={
                        'success': True,
                        'ctx': MagicMock(
                            driver=MagicMock(pk=uuid4()),
                            tenant_user=MagicMock(user_id=uuid4()),
                        ),
                    },
                ):
                    with patch(
                        'mobile_api.views.driver_job_allowed_actions.DriverJobAllowedActionsService.get_shipment_allowed_actions',
                        return_value={
                            'success': True,
                            'allowed_actions': engine_payload,
                        },
                    ):
                        response = view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['allowed_actions']['count'], 1)
