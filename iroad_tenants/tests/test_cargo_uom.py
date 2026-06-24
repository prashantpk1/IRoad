"""Cargo UOM normalization tests."""
from __future__ import annotations

from django.test import SimpleTestCase

from iroad_tenants.forms_tenant_cargo import normalize_cargo_uom


class CargoUomNormalizationTests(SimpleTestCase):
    def test_boxs_maps_to_boxes(self):
        self.assertEqual(normalize_cargo_uom('Boxs'), 'Boxes')

    def test_places_maps_to_pieces(self):
        self.assertEqual(normalize_cargo_uom('places'), 'Pieces')

    def test_canonical_values_unchanged(self):
        self.assertEqual(normalize_cargo_uom('Pallets'), 'Pallets')
