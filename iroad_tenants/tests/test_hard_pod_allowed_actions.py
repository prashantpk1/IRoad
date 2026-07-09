"""Hard POD (A7H) allowed-action policy tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from iroad_tenants.operation_execution import (
    _action_is_allowed,
    _combined_pod_allows_hard_copy_retry,
    _hard_copy_collection_shipment_allowed,
    _hard_pod_post_digital_promotion_allowed,
    _hard_pod_promotion_allowed_for_submission,
    _is_hard_copy_collection_action,
    _is_standalone_hard_copy_collection_action,
    validate_operation_action_allowed,
)
from tenant_workspace.models import TenantOperationAction, TenantShipment


def _hard_pod_action():
    return SimpleNamespace(
        action_id=uuid4(),
        action_code='A7H',
        english_label='Hard POD Collection',
        status=TenantOperationAction.Status.ACTIVE,
        sequence_category='job',
        shipment_status_impact='',
        movement_status_impact='',
        booking_status_impact='',
        auto_shipment_post=False,
        auto_movement_post=False,
        auto_pod_post=False,
        hard_copy_collection=True,
    )


class HardPodTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.patchers = [
            patch(
                'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
                return_value={'pod_uploaded': False, 'hard_pod_log': False},
            ),
            patch(
                'iroad_tenants.operation_execution._executed_action_ids',
                return_value=set(),
            ),
            patch(
                'iroad_tenants.operation_execution._executed_action_codes',
                return_value=set(),
            ),
            patch(
                'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_delivery_milestones_done',
                return_value=(True, True),
            ),
            patch(
                'iroad_tenants.operation_execution.get_allowed_actions',
                return_value=type(
                    'QS',
                    (),
                    {'filter': lambda *a, **k: type('F', (), {'exists': lambda *a, **k: False})()},
                )(),
            ),
            patch(
                'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_logs_for_milestones',
                return_value=[],
            ),
            patch(
                'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_log_is_valid',
                return_value=True,
            ),
            patch(
                'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_execution_counts',
                return_value=True,
            ),
        ]
        self.mocks = [p.start() for p in self.patchers]
        self.mock_evidence = self.mocks[0]
        self.mock_executed_ids = self.mocks[1]
        self.mock_executed_codes = self.mocks[2]
        self.mock_milestones = self.mocks[3]
        self.mock_allowed = self.mocks[4]
        self.mock_milestone_logs = self.mocks[5]
        self.mock_pod_log_valid = self.mocks[6]
        self.mock_execution_counts = self.mocks[7]

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        super().tearDown()


class HardPodAllowedActionTests(HardPodTestCase):
    def test_hard_copy_action_detection(self):
        self.assertTrue(_is_hard_copy_collection_action(_hard_pod_action()))

    def test_combined_pod_not_standalone_hard_copy(self):
        combined = _hard_pod_action()
        combined.action_code = 'OA-0008'
        combined.english_label = 'POD'
        combined.auto_pod_post = True
        self.assertTrue(_is_hard_copy_collection_action(combined))
        self.assertFalse(_is_standalone_hard_copy_collection_action(combined))

    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value={'A7'})
    def test_hard_copy_allowed_after_a7_at_delivery(self, _mock_codes):
        self.mock_evidence.return_value = {'pod_uploaded': True, 'hard_pod_log': False}
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
            order_type='COD',
            booking_item_type='Outbound',
        )
        self.assertTrue(
            _hard_copy_collection_shipment_allowed(shipment),
        )

    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=False)
    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value=set())
    def test_hard_copy_blocked_without_a7_or_custody(self, _mock_codes, _mock_custody):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
        )
        self.assertFalse(_hard_copy_collection_shipment_allowed(shipment))

    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value=set())
    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=True)
    def test_hard_copy_allowed_with_pending_custody_submit(self, _mock_custody, _mock_codes):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
        )
        self.assertTrue(_hard_copy_collection_shipment_allowed(shipment))

    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value={'A7'})
    def test_action_is_allowed_for_a7h_after_a7(self, _codes, _ids, _movement):
        self.mock_evidence.return_value = {'pod_uploaded': True, 'hard_pod_log': False}
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.AT_DELIVERY
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.order_type = 'COD'
        action = _hard_pod_action()
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
                executed_action_ids=set(),
            )
        )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=True)
    def test_label_only_pod_allows_hard_copy_retry_without_flags(
        self,
        _mock_custody,
        _mock_evidence,
        _mock_pending,
    ):
        """Tenant POD row (english_label only) — step 2 after custody submit."""
        action = SimpleNamespace(
            action_id=uuid4(),
            action_code='OA-0009',
            english_label='POD',
            auto_pod_post=False,
            hard_copy_collection=False,
            status=TenantOperationAction.Status.ACTIVE,
        )
        shipment = SimpleNamespace(pk=uuid4(), pod_type=TenantShipment.PodType.HARD)
        self.assertTrue(_combined_pod_allows_hard_copy_retry(action, shipment))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    @patch(
        'iroad_tenants.operation_execution._pending_hard_pod_custody_exists',
        return_value=False,
    )
    def test_label_only_pod_hard_copy_allowed_at_delivered_without_custody_row(
        self,
        _mock_custody,
        _mock_evidence,
        _mock_pending,
    ):
        """Hard-copy step 2 after digital POD when status drifted to Delivered."""
        action = SimpleNamespace(
            action_id=uuid4(),
            action_code='OA-0009',
            english_label='POD',
            auto_pod_post=False,
            hard_copy_collection=False,
            status=TenantOperationAction.Status.ACTIVE,
        )
        shipment = SimpleNamespace(
            pk=uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            shipment_status=TenantShipment.ShipmentStatus.DELIVERED,
        )
        self.assertTrue(_combined_pod_allows_hard_copy_retry(action, shipment))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    def test_combined_pod_allows_hard_copy_retry_after_digital(
        self,
        _mock_evidence,
        _mock_pending,
    ):
        action = _hard_pod_action()
        action.auto_pod_post = True
        action.action_code = 'OA-0008'
        shipment = SimpleNamespace(pk=uuid4(), pod_type=TenantShipment.PodType.HARD)
        self.assertTrue(_combined_pod_allows_hard_copy_retry(action, shipment))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': True, 'pod_uploaded': False},
    )
    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids')
    def test_combined_pod_allowed_at_delivered_for_hard_copy_retry(
        self,
        mock_executed_ids,
        _movement,
        _mock_evidence,
        _mock_pending,
    ):
        action = _hard_pod_action()
        action.auto_pod_post = True
        action.action_code = 'OA-0008'
        action.english_label = 'POD'
        action.shipment_status_impact = 'Delivered'
        mock_executed_ids.return_value = {action.action_id}
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.order_type = 'COD'
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
            )
        )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    @patch('iroad_tenants.operation_execution.get_allowed_actions')
    def test_validate_allows_combined_pod_at_delivered_via_allowed_queryset(
        self,
        mock_allowed,
        _mock_evidence,
        _mock_pending,
    ):
        action = _hard_pod_action()
        action.auto_pod_post = True
        action.action_code = 'OA-0008'
        action.pk = action.action_id
        allowed_qs = MagicMock()
        allowed_qs.filter.return_value.exists.return_value = True
        mock_allowed.return_value = allowed_qs
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.HARD
        with patch(
            'iroad_tenants.operation_runtime.latest_state.repair_delivered_before_hard_pod_custody',
            return_value=False,
        ):
            self.assertIsNone(
                validate_operation_action_allowed(
                    action,
                    shipment=shipment,
                )
            )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    def test_repair_delivered_before_hard_pod_custody(self, _mock_pending):
        self.mock_evidence.return_value = {'pod_uploaded': True, 'hard_pod_log': False}
        from iroad_tenants.operation_runtime.latest_state import (
            repair_delivered_before_hard_pod_custody,
        )

        shipment = MagicMock()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.HARD
        self.assertTrue(repair_delivered_before_hard_pod_custody(shipment))
        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
        shipment.save.assert_called_once()

    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.is_hard_pod_custody_complete',
        return_value=True,
    )
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=False,
    )
    def test_collect_payment_allowed_at_pod_submitted_after_hard_pod(
        self,
        _pending,
        _custody,
        _compliant,
        _unload,
        _ids,
        _movement,
    ):
        self.mock_evidence.return_value = {'pod_uploaded': True, 'hard_pod_log': True}
        payment = SimpleNamespace(
            action_id=uuid4(),
            action_code='OA-0010',
            english_label='Payment Collection',
            status=TenantOperationAction.Status.ACTIVE,
            sequence_category='job',
            sequence_number=10,
            shipment_status_impact='Delivered',
            movement_status_impact='',
            booking_status_impact='',
            auto_shipment_post=False,
            auto_movement_post=False,
            auto_pod_post=False,
            auto_treasury_post=True,
            hard_copy_collection=False,
        )
        payment.pk = payment.action_id
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.POD_SUBMITTED
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.order_type = 'COD'
        shipment.collection_status = TenantShipment.CollectionStatus.PENDING
        self.assertIsNone(
            validate_operation_action_allowed(
                payment,
                shipment=shipment,
            ),
        )


class PodDeliveredStatusDriftTests(HardPodTestCase):
    """Credit unloading may set Delivered before digital POD — execute must still work."""

    def _pod_action(self):
        return SimpleNamespace(
            action_id=uuid4(),
            action_code='OA-0009',
            english_label='POD',
            status=TenantOperationAction.Status.ACTIVE,
            sequence_category='job',
            shipment_status_impact='POD_Submitted',
            movement_status_impact='',
            booking_status_impact='',
            auto_shipment_post=False,
            auto_movement_post=False,
            auto_pod_post=True,
            hard_copy_collection=True,
        )

    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'pod_uploaded': False, 'hard_pod_log': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_ready_for_pod_capture',
        return_value=True,
    )
    @patch('iroad_tenants.operation_execution._hard_pod_custody_promoted', return_value=False)
    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_workflow_sequence_prerequisites_met',
        return_value=True,
    )
    def test_digital_pod_allowed_at_delivered_credit(
        self,
        _workflow,
        _executed,
        _movement,
        _promoted,
        _ready,
        _evidence,
    ):
        action = self._pod_action()
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        shipment.order_type = 'Credit'
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
            ),
        )

    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'pod_uploaded': False, 'hard_pod_log': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_ready_for_pod_capture',
        return_value=True,
    )
    @patch('iroad_tenants.operation_execution._hard_pod_custody_promoted', return_value=False)
    @patch('iroad_tenants.operation_execution.get_allowed_actions')
    def test_validate_allows_pod_at_delivered_before_digital_evidence(
        self,
        mock_allowed,
        _promoted,
        _ready,
        _evidence,
    ):
        action = self._pod_action()
        action.pk = action.action_id
        allowed_qs = MagicMock()
        allowed_qs.filter.return_value.exists.return_value = False
        mock_allowed.return_value = allowed_qs
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        shipment.order_type = 'Credit'
        with patch(
            'iroad_tenants.operation_runtime.latest_state.repair_delivered_before_hard_pod_custody',
            return_value=False,
        ):
            self.assertIsNone(
                validate_operation_action_allowed(
                    action,
                    shipment=shipment,
                ),
            )


class HardPodPromotionAtPodSubmittedTests(HardPodTestCase):
    """Hard-copy custody promotion after digital POD at POD Submitted."""

    def _combined_pod_action(self):
        return SimpleNamespace(
            action_id=uuid4(),
            pk=None,
            action_code='OA-0008',
            english_label='POD',
            status=TenantOperationAction.Status.ACTIVE,
            sequence_category='job',
            shipment_status_impact='POD_Submitted',
            movement_status_impact='',
            booking_status_impact='',
            auto_shipment_post=False,
            auto_movement_post=False,
            auto_pod_post=True,
            hard_copy_collection=True,
        )

    @patch(
        'iroad_tenants.operation_runtime.latest_state.repair_delivered_before_hard_pod_custody',
        return_value=False,
    )
    @patch('iroad_tenants.operation_execution.get_allowed_actions')
    @patch('iroad_tenants.operation_execution._hard_pod_promotion_allowed_for_submission')
    def test_validate_allows_promotion_with_custody_submission_id(
        self,
        mock_promotion_allowed,
        mock_allowed,
        _repair,
    ):
        action = self._combined_pod_action()
        action.pk = action.action_id
        mock_promotion_allowed.return_value = True
        allowed_qs = MagicMock()
        allowed_qs.filter.return_value.exists.return_value = False
        mock_allowed.return_value = allowed_qs
        shipment = MagicMock()
        shipment.pk = uuid4()
        submission_id = str(uuid4())
        self.assertIsNone(
            validate_operation_action_allowed(
                action,
                shipment=shipment,
                hard_pod_custody_submission_id=submission_id,
            ),
        )
        mock_promotion_allowed.assert_called_once()

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=True)
    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids')
    def test_combined_pod_allowed_at_pod_submitted_with_pending_custody(
        self,
        mock_executed_ids,
        _movement,
        _pending,
        _evidence,
        _derive,
    ):
        action = self._combined_pod_action()
        mock_executed_ids.return_value = {action.action_id}
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.POD_SUBMITTED
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.order_type = 'COD'
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
            )
        )
        self.assertTrue(
            _combined_pod_allows_hard_copy_retry(
                action,
                shipment,
            )
        )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=True)
    def test_combined_pod_allowed_when_pending_custody_even_if_derive_pending_false(
        self,
        _pending,
        _evidence,
        _derive,
    ):
        action = self._combined_pod_action()
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.POD_SUBMITTED
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.booking = MagicMock(pod_type=TenantShipment.PodType.HARD)
        self.assertTrue(
            _combined_pod_allows_hard_copy_retry(
                action,
                shipment,
            )
        )


class HardPodRoundTripBackloadPromotionTests(HardPodTestCase):
    """Round-trip leg 2: custody promotion at POD Submitted with pending submission."""

    def _pod_action(self):
        return SimpleNamespace(
            action_id=uuid4(),
            pk=None,
            action_code='OA-0009',
            english_label='POD',
            status=TenantOperationAction.Status.ACTIVE,
            sequence_category='job',
            shipment_status_impact='POD_Submitted',
            movement_status_impact='',
            booking_status_impact='',
            auto_shipment_post=False,
            auto_movement_post=False,
            auto_pod_post=True,
            hard_copy_collection=False,
        )

    @patch('mobile_api.hard_pod.models.HardPODCustodySubmission')
    def test_promotion_allowed_for_unpromoted_submission_on_backload_shipment(
        self,
        mock_submission_model,
    ):
        action = self._pod_action()
        action.pk = action.action_id
        shipment_pk = uuid4()
        submission_pk = uuid4()
        submission = SimpleNamespace(
            pk=submission_pk,
            shipment_id=str(shipment_pk),
            tenant_schema='tenant_a',
            promoted_at=None,
        )
        mock_submission_model.objects.filter.return_value.first.return_value = submission
        shipment = SimpleNamespace(
            pk=shipment_pk,
            shipment_id=shipment_pk,
            pod_type=TenantShipment.PodType.HARD,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.HARD),
        )
        self.assertTrue(
            _hard_pod_promotion_allowed_for_submission(
                action,
                shipment,
                str(submission_pk),
            )
        )

    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'pod_uploaded': True, 'hard_pod_log': False},
    )
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.is_hard_pod_custody_complete',
        return_value=True,
    )
    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=True)
    @patch('iroad_tenants.operation_execution._hard_pod_custody_promoted', return_value=False)
    @patch('iroad_tenants.operation_execution._digital_pod_step_complete', return_value=True)
    def test_post_digital_promotion_allowed_when_pending_custody_despite_complete_flag(
        self,
        _digital,
        _promoted,
        _pending,
        _complete,
        _evidence,
    ):
        action = self._pod_action()
        shipment = SimpleNamespace(
            pk=uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.HARD),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        self.assertTrue(_hard_pod_post_digital_promotion_allowed(action, shipment))
