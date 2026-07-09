"""
Unit tests for dashboard POD/COD projection (read-only compliance flags).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.projections.pod_cod_projection import (
    build_pod_cod_summary,
    build_pod_cod_summary_for_context,
)
from mobile_api.dashboard.selectors import pod_cod_policy as policy
from tenant_workspace.models import TenantShipment


def _mock_no_promoted_submission(mock_submission) -> None:
    qs = MagicMock()
    qs.exclude.return_value = qs
    qs.filter.return_value = qs
    qs.first.return_value = None
    mock_submission.objects.filter.return_value = qs


def _shipment(
    *,
    order_type='Standard',
    pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
    pod_type=TenantShipment.PodType.DIGITAL,
    collection_status=TenantShipment.CollectionStatus.PENDING,
    shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
):
    s = MagicMock()
    s.pk = uuid4()
    s.order_type = order_type
    s.pod_status = pod_status
    s.pod_type = pod_type
    s.collection_status = collection_status
    s.shipment_status = shipment_status
    s.driver = MagicMock()
    s.driver.pk = uuid4()
    s.driver_id = ''
    s.cod_amount = Decimal('100.00')
    return s


class PodCodPolicyTests(SimpleTestCase):
    def test_pod_pending(self):
        shipment = _shipment(pod_status=TenantShipment.PodStatus.NOT_COMPLETED)
        self.assertTrue(policy.derive_pod_pending(shipment))
        self.assertFalse(policy.derive_pod_compliant(shipment))

    def test_pod_compliant(self):
        shipment = _shipment(pod_status=TenantShipment.PodStatus.COMPLETED)
        self.assertTrue(policy.derive_pod_compliant(shipment))
        self.assertFalse(policy.derive_pod_pending(shipment))

    def test_hard_pod_not_pending_during_pickup_or_transit(self):
        for status in (
            TenantShipment.ShipmentStatus.LOADED,
            TenantShipment.ShipmentStatus.IN_TRANSIT,
            TenantShipment.ShipmentStatus.CREATED,
        ):
            shipment = _shipment(
                pod_type=TenantShipment.PodType.HARD,
                pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
                shipment_status=status,
            )
            self.assertFalse(
                policy.derive_hard_pod_pending(shipment),
                msg=f'expected False for {status}',
            )

    def test_hard_pod_pending_after_digital_pod_at_delivery(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission, patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=True,
        ):
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertTrue(
                policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence={'pod_uploaded': True},
                )
            )

    def test_hard_pod_not_pending_at_unloading_completed_before_digital_pod(self):
        """Unloading Completed (OA-0008) must not surface hard-copy pending."""
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission, patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=False,
        ):
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertFalse(policy.derive_hard_pod_pending(shipment))
            self.assertFalse(
                policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence={'pod_uploaded': False},
                )
            )

    def test_hard_pod_pending_from_booking_when_shipment_pod_type_still_digital(self):
        """Booking Hard POD applies only after digital POD at delivery."""
        shipment = _shipment(
            pod_type=TenantShipment.PodType.DIGITAL,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        shipment.booking = MagicMock(pod_type=TenantShipment.PodType.HARD)
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission, patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=True,
        ):
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertTrue(
                policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence={'pod_uploaded': True},
                )
            )

    def test_digital_booking_never_requires_hard_copy_even_if_shipment_hard(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        shipment.booking = MagicMock(pod_type=TenantShipment.PodType.DIGITAL)
        self.assertFalse(policy.shipment_requires_hard_copy(shipment))
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission:
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertFalse(policy.derive_hard_pod_pending(shipment))

    def test_hard_pod_still_pending_when_hard_copy_received_without_a7h(self):
        """Digital POD may have set HARD_COPY_RECEIVED before custody execute."""
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission, patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=True,
        ):
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertTrue(policy.derive_hard_pod_pending(shipment))
        self.assertTrue(policy.derive_pod_compliant(shipment))

    def test_hard_pod_pending_when_upload_log_loaded_without_explicit_evidence(self):
        """Defer/repair paths load mobile log evidence when callers omit log_evidence."""
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        with patch(
            'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
            return_value={'pod_uploaded': True},
        ), patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission, patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=True,
        ):
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertTrue(policy.derive_hard_pod_pending(shipment))

    def test_hard_pod_not_pending_when_a7h_log_present(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission:
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': 'execute_action_log',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertFalse(
                policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence={'hard_pod_log': True},
                )
            )

    def test_pod_pending_cleared_when_upload_log_present(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        flags = policy.derive_pod_cod_flags(
            shipment,
            log_evidence={'pod_uploaded': True, 'hard_pod_log': False},
        )
        self.assertFalse(flags['pod_pending'])
        self.assertTrue(flags['hard_pod_pending'])

    def test_collect_payment_flags_when_hard_pod_complete(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.COMPLETED,
            order_type='COD',
        )
        flags = policy.derive_pod_cod_flags(
            shipment,
            log_evidence={'pod_uploaded': True, 'hard_pod_log': True},
        )
        self.assertFalse(flags['pod_pending'])
        self.assertFalse(flags['hard_pod_pending'])
        self.assertTrue(flags['pod_compliant'])

    def test_hard_pod_still_pending_when_compliant_without_a7h_log(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority, patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPODCustodySubmission',
        ) as mock_submission:
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': '',
            }
            _mock_no_promoted_submission(mock_submission)
            self.assertTrue(
                policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence={'hard_pod_log': False, 'pod_uploaded': True},
                )
            )
            self.assertFalse(
                policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence={'hard_pod_log': True, 'pod_uploaded': True},
                )
            )

    def test_custody_authority_clears_hard_pod_pending_without_hard_pod_log_flag(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.DELIVERED,
        )
        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.HardPodCustodyAuthorityService',
        ) as mock_authority:
            mock_authority.return_value.resolve_authority.return_value = {
                'custody_authority': 'promoted_custody_submission',
            }
            evidence = policy.enrich_log_evidence_hard_pod(
                {'pod_uploaded': True, 'hard_pod_log': False},
                shipment,
            )
            self.assertTrue(evidence['hard_pod_log'])
            flags = policy.derive_pod_cod_flags(
                shipment,
                log_evidence=evidence,
            )
            self.assertFalse(flags['hard_pod_pending'])
            self.assertTrue(flags['pod_compliant'])

    def test_cod_pending_and_collected(self):
        pending = _shipment(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
        )
        collected = _shipment(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
        )
        self.assertTrue(policy.derive_cod_pending(pending))
        self.assertFalse(policy.derive_cod_collected(pending))
        self.assertTrue(policy.derive_cod_collected(collected))
        self.assertFalse(policy.derive_cod_pending(collected))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.validate_shipment_status_transition',
    )
    def test_delivery_blocked_when_validation_fails(self, mock_validate):
        shipment = _shipment(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        mock_validate.side_effect = ValidationError('blocked')
        self.assertTrue(policy.derive_delivery_blocked(shipment))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.validate_shipment_status_transition',
    )
    def test_delivery_not_blocked_when_validation_passes(self, mock_validate):
        shipment = _shipment(
            pod_status=TenantShipment.PodStatus.COMPLETED,
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
            order_type='COD',
        )
        mock_validate.return_value = None
        self.assertFalse(policy.derive_delivery_blocked(shipment))

    def test_delivery_not_blocked_while_in_transit(self):
        shipment = _shipment(
            order_type='COD',
            shipment_status=TenantShipment.ShipmentStatus.IN_TRANSIT,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        self.assertFalse(policy.derive_delivery_blocked(shipment))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.cod_client_collection_exists',
        return_value=False,
    )
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.ensure_active_driver_treasury',
    )
    def test_treasury_pending_when_collected_but_no_txn(
        self, mock_treasury, mock_exists
    ):
        treasury = MagicMock()
        mock_treasury.return_value = treasury
        shipment = _shipment(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
        )
        self.assertTrue(policy.derive_treasury_pending(shipment))
        mock_exists.assert_called_once()

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.cod_client_collection_exists',
        return_value=True,
    )
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.ensure_active_driver_treasury',
    )
    def test_treasury_not_pending_when_wallet_posted(
        self, mock_treasury, _mock_exists
    ):
        mock_treasury.return_value = MagicMock()
        shipment = _shipment(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
        )
        self.assertFalse(policy.derive_treasury_pending(shipment))


class PodCodProjectionTests(SimpleTestCase):
    def test_empty_summary_without_shipment(self):
        summary = build_pod_cod_summary(shipment=None)
        self.assertEqual(summary['pod_pending'], False)
        self.assertEqual(summary['delivery_blocked'], False)

    def test_projection_from_shipment(self):
        shipment = _shipment(
            pod_status=TenantShipment.PodStatus.COMPLETED,
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
        )
        with patch.object(
            policy,
            'derive_pod_cod_flags',
            return_value={
                'pod_pending': False,
                'pod_compliant': True,
                'hard_pod_pending': False,
                'cod_pending': False,
                'cod_collected': True,
                'treasury_pending': False,
                'delivery_blocked': False,
            },
        ):
            summary = build_pod_cod_summary(shipment=shipment)
        self.assertTrue(summary['pod_compliant'])
        self.assertTrue(summary['cod_collected'])

    def test_projection_from_booking_selection(self):
        shipment = _shipment(pod_status=TenantShipment.PodStatus.NOT_COMPLETED)
        booking = MagicMock()
        selection = DriverBookingSelectionResult(
            booking=booking,
            active_shipment=shipment,
            next_executable_shipment=shipment,
        )
        summary = build_pod_cod_summary(selection=selection)
        self.assertTrue(summary['pod_pending'])

    def test_projection_from_context(self):
        shipment = _shipment(pod_status=TenantShipment.PodStatus.NOT_COMPLETED)
        context = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='tenant_a',
            user_id='u1',
            active_shipment=shipment,
        )
        summary = build_pod_cod_summary_for_context(context)
        self.assertTrue(summary['pod_pending'])
