"""Tests for empty-move workflow_status projection."""

from __future__ import annotations



import uuid

from types import SimpleNamespace

from unittest.mock import MagicMock, patch



from django.test import SimpleTestCase



from mobile_api.job_detail.projections.movement_workflow_status_projection import (

    build_movement_workflow_status,

)





def _movement():

    return SimpleNamespace(

        movement_id=uuid.uuid4(),

        pk=uuid.uuid4(),

        movement_no='TML-0999',

        movement_source='empty',

        empty_move_reason='maintenance',

        from_location_point=None,

        to_location_point=None,

        from_location_address='Pickup addr',

        to_location_address='Drop addr',

        from_latitude='22.29415',

        from_longitude='73.13790',

        to_latitude='',

        to_longitude='',

        from_location_map_link='',

        to_location_map_link='',

    )





def _log(action_code: str, *, label: str = ''):

    impacts = {

        'EM1': 'In_Progress',

        'OA-0014': 'In_Progress',

        'EM4': 'Completed',

        'OA-0016': 'Completed',

        'OA-EM-004': 'Completed',

    }

    action = SimpleNamespace(

        action_code=action_code,

        english_label=label or action_code,

        arabic_label=label or action_code,

        movement_status_impact=impacts.get(action_code, ''),

        shipment_status_impact='',

        sequence_category='empty_move',

    )

    return SimpleNamespace(

        log_id=uuid.uuid4(),

        operation_action=action,

        log_date=None,

        created_at=None,

        media_rows=MagicMock(all=MagicMock(return_value=[])),

        latitude='',

        longitude='',

    )





class MovementWorkflowStatusProjectionTests(SimpleTestCase):

    def test_legacy_fallback_shows_four_steps_without_schema(self):

        steps = build_movement_workflow_status(_movement(), [])

        self.assertEqual(len(steps), 4)

        self.assertEqual([row['step_key'] for row in steps], [
            'pickup',
            'in_transit',
            'delivery',
            'complete',
        ])

        self.assertEqual(steps[0]['action_code'], 'EM1')

        self.assertEqual(steps[3]['action_code'], 'EM4')

        self.assertFalse(steps[3]['completed'])



    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')

    def test_tenant_three_step_workflow(self, mock_iter):

        mock_iter.return_value = [

            SimpleNamespace(

                action_code='OA-0014',

                english_label='Start Job',

                sequence_category='empty_move',

                sequence_number=1,

            ),

            SimpleNamespace(

                action_code='OA-0015',

                english_label='Departure',

                sequence_category='empty_move',

                sequence_number=2,

            ),

            SimpleNamespace(

                action_code='OA-0016',

                english_label='End Job',

                sequence_category='empty_move',

                sequence_number=3,

            ),

        ]

        steps = build_movement_workflow_status(_movement(), [], tenant_schema='tenant_a')

        self.assertEqual(len(steps), 3)

        self.assertEqual([row['step_key'] for row in steps], ['seq_1', 'seq_2', 'seq_3'])

        self.assertEqual(steps[0]['action_code'], 'OA-0014')

        self.assertEqual(steps[2]['action_code'], 'OA-0016')

        self.assertEqual(steps[0]['address']['display_name'], 'Pickup addr')
        self.assertEqual(steps[0]['address']['from_address'], 'Pickup addr')
        self.assertEqual(steps[0]['latitude'], '22.29415')
        self.assertEqual(steps[0]['longitude'], '73.13790')
        self.assertEqual(steps[0]['location_capture_mode'], 'gps')
        self.assertTrue(steps[0]['gps_capture_required'])

        self.assertEqual(steps[2]['address'], {})
        self.assertEqual(steps[2]['location'], '')
        self.assertEqual(steps[2]['latitude'], '')
        self.assertEqual(steps[2]['longitude'], '')
        self.assertEqual(steps[2]['location_capture_mode'], 'gps')
        self.assertTrue(steps[2]['gps_capture_required'])

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_end_job_delivery_address_after_departure(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-0014',
                english_label='Start Job',
                sequence_category='empty_move',
                sequence_number=1,
            ),
            SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                sequence_category='empty_move',
                sequence_number=2,
            ),
            SimpleNamespace(
                action_code='OA-0016',
                english_label='End Job',
                sequence_category='empty_move',
                sequence_number=3,
            ),
        ]
        movement = _movement()
        movement.to_latitude = '22.29400'
        movement.to_longitude = '73.13800'
        logs = [
            _log('OA-0014', label='Start Job'),
            _log('OA-0015', label='Departure'),
        ]
        steps = build_movement_workflow_status(
            movement,
            logs,
            tenant_schema='tenant_a',
        )
        end_step = steps[2]
        self.assertEqual(end_step['address']['to_address'], 'Drop addr')
        self.assertEqual(end_step['address']['latitude'], '22.29400')
        self.assertEqual(end_step['address']['longitude'], '73.13800')
        self.assertEqual(end_step['address']['location_capture_mode'], 'gps')
        self.assertEqual(end_step['location'], 'Drop addr')

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_end_job_to_address_from_execute_location_address(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-0014',
                english_label='Start Job',
                sequence_category='empty_move',
                sequence_number=1,
            ),
            SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                sequence_category='empty_move',
                sequence_number=2,
            ),
            SimpleNamespace(
                action_code='OA-0016',
                english_label='End Job',
                sequence_category='empty_move',
                sequence_number=3,
            ),
        ]
        movement = _movement()
        movement.to_location_address = ''
        movement.to_latitude = ''
        movement.to_longitude = ''
        end_log = _log('OA-0016', label='End Job')
        end_log.latitude = '21.3891'
        end_log.longitude = '39.8579'
        end_log._route_location_address = 'Industrial Area, Makkah, Saudi Arabia'
        steps = build_movement_workflow_status(
            movement,
            [_log('OA-0014'), _log('OA-0015'), end_log],
            tenant_schema='tenant_a',
        )
        end_step = steps[2]
        self.assertEqual(
            end_step['address']['to_address'],
            'Industrial Area, Makkah, Saudi Arabia',
        )
        self.assertEqual(end_step['location'], 'Industrial Area, Makkah, Saudi Arabia')

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_end_job_uses_stored_destination_without_execute_text(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-0014',
                english_label='Start Job',
                sequence_category='empty_move',
                sequence_number=1,
            ),
            SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                sequence_category='empty_move',
                sequence_number=2,
            ),
            SimpleNamespace(
                action_code='OA-0016',
                english_label='End Job',
                sequence_category='empty_move',
                sequence_number=3,
            ),
        ]
        movement = _movement()
        movement.to_location_address = 'Industrial Area, Makkah, Saudi Arabia'
        movement.to_latitude = ''
        movement.to_longitude = ''
        end_log = _log('OA-0016', label='End Job')
        end_log.latitude = '21.3891'
        end_log.longitude = '39.8579'
        steps = build_movement_workflow_status(
            movement,
            [_log('OA-0014'), _log('OA-0015'), end_log],
            tenant_schema='tenant_a',
        )
        end_step = steps[2]
        self.assertEqual(
            end_step['address']['to_address'],
            'Industrial Area, Makkah, Saudi Arabia',
        )
        self.assertEqual(end_step['address']['latitude'], '21.3891')

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_three_step_completion_by_action_code(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-0014',
                english_label='Start Job',
                sequence_category='empty_move',
                sequence_number=1,
            ),
            SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                sequence_category='empty_move',
                sequence_number=2,
            ),
            SimpleNamespace(
                action_code='OA-0016',
                english_label='End Job',
                sequence_category='empty_move',
                sequence_number=3,
            ),
        ]
        steps = build_movement_workflow_status(
            _movement(),
            [_log('OA-0014'), _log('OA-0015')],
            tenant_schema='tenant_a',
        )
        self.assertTrue(steps[0]['completed'])
        self.assertTrue(steps[1]['completed'])
        self.assertFalse(steps[2]['completed'])

    def test_first_step_complete_only_after_em1(self):

        steps = build_movement_workflow_status(_movement(), [_log('EM1')])

        self.assertTrue(steps[0]['completed'])

        self.assertFalse(steps[1]['completed'])

        self.assertFalse(steps[2]['completed'])

        self.assertFalse(steps[3]['completed'])



    def test_arrival_complete_after_em3(self):

        logs = [_log('EM1'), _log('EM2'), _log('EM3')]

        steps = build_movement_workflow_status(_movement(), logs)

        self.assertTrue(steps[0]['completed'])

        self.assertTrue(steps[1]['completed'])

        self.assertTrue(steps[2]['completed'])

        self.assertTrue(steps[2]['is_performed'])

        self.assertFalse(steps[3]['completed'])



    def test_arrival_complete_with_action_master_label(self):

        action = SimpleNamespace(

            action_code='EM3',

            english_label='Arrival At Destination',

            arabic_label='Arrival At Destination',

            movement_status_impact='',

            shipment_status_impact='',

            sequence_category='empty_move',

        )

        arrival_log = SimpleNamespace(

            log_id=uuid.uuid4(),

            operation_action=action,

            log_date=None,

            created_at=None,

            media_rows=MagicMock(all=MagicMock(return_value=[])),

            latitude='',

            longitude='',

        )

        steps = build_movement_workflow_status(

            _movement(),

            [_log('EM1'), _log('EM2'), arrival_log],

        )

        self.assertTrue(steps[2]['is_performed'])



    def test_complete_step_only_after_em4(self):

        logs = [_log('EM1'), _log('EM2'), _log('EM3'), _log('EM4')]

        steps = build_movement_workflow_status(_movement(), logs)

        self.assertTrue(steps[3]['completed'])

        self.assertEqual(steps[3]['step_key'], 'complete')

        self.assertEqual(steps[3]['action_code'], 'EM4')



    def test_em4_does_not_complete_arrival_without_em3_log(self):

        logs = [_log('EM1'), _log('EM2'), _log('EM4')]

        steps = build_movement_workflow_status(_movement(), logs)

        self.assertFalse(steps[2]['completed'])

        self.assertTrue(steps[3]['completed'])



    def test_arrival_complete_from_label_without_em_code(self):

        action = SimpleNamespace(

            action_code='M3',

            english_label='Arrival At Destination',

            arabic_label='Arrival At Destination',

            movement_status_impact='',

            shipment_status_impact='',

            sequence_category='empty_move',

        )

        logs = [_log('EM1'), _log('EM2'), SimpleNamespace(

            log_id=uuid.uuid4(),

            operation_action=action,

            log_date=None,

            created_at=None,

            media_rows=MagicMock(all=MagicMock(return_value=[])),

            latitude='',

            longitude='',

        )]

        steps = build_movement_workflow_status(_movement(), logs)

        self.assertTrue(steps[2]['completed'])


