"""Shipment POD evidence helpers (PCS §5.6.2)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from iroad_tenants.shipment_pod_evidence import (
    action_log_attachment_meta_from_media,
    action_log_map_url,
)


class ActionLogMapUrlTests(TestCase):
    def test_prefers_stored_map_link(self):
        log = SimpleNamespace(map_link='https://maps.example.com/pin', latitude='24.7', longitude='46.6')
        self.assertEqual(action_log_map_url(log), 'https://maps.example.com/pin')

    def test_builds_google_maps_from_coordinates(self):
        log = SimpleNamespace(map_link='', latitude='24.7136', longitude='46.6753')
        self.assertEqual(
            action_log_map_url(log),
            'https://maps.google.com/?q=24.7136,46.6753',
        )

    def test_returns_empty_when_no_gps(self):
        log = SimpleNamespace(map_link='', latitude='', longitude='')
        self.assertEqual(action_log_map_url(log), '')

    def test_returns_empty_for_none(self):
        self.assertEqual(action_log_map_url(None), '')


class ActionLogAttachmentMetaTests(TestCase):
    def test_uses_media_description(self):
        media = SimpleNamespace(description='POD photo', file=SimpleNamespace(name='uploads/pod.jpg', url='/media/pod.jpg'))
        label, url = action_log_attachment_meta_from_media([media])
        self.assertEqual(label, 'POD photo')
        self.assertEqual(url, '/media/pod.jpg')

    def test_falls_back_to_filename(self):
        media = SimpleNamespace(description='', file=SimpleNamespace(name='uploads/evidence.png', url='/media/evidence.png'))
        label, url = action_log_attachment_meta_from_media([media])
        self.assertEqual(label, 'evidence.png')
        self.assertEqual(url, '/media/evidence.png')

    def test_empty_when_no_media(self):
        self.assertEqual(action_log_attachment_meta_from_media([]), ('', ''))
