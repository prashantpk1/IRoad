"""Shipment POD evidence helpers (PCS §5.6.2)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from iroad_tenants.shipment_pod_evidence import (
    action_log_attachment_meta_from_media,
    action_log_attachment_storage_path_from_media,
    action_log_map_url,
    resolve_pod_page_display_row,
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


class ResolvePodPageDisplayRowTests(TestCase):
    def test_separates_legacy_attachment_path_from_map_url(self):
        line = SimpleNamespace(
            line_no=1,
            doc_page='Evidence-1',
            source='Action Log',
            map_url='mobile/pod_evidence/abc.jpg',
            attachment_storage_path='',
            attachment_label='abc.jpg',
            action_log=None,
        )
        row = resolve_pod_page_display_row(
            line,
            file_url_builder=lambda path: f'/media/{path}',
        )
        self.assertEqual(row['map_url'], '')
        self.assertEqual(row['attachment_storage_path'], 'mobile/pod_evidence/abc.jpg')
        self.assertEqual(row['attachment_url'], '/media/mobile/pod_evidence/abc.jpg')

    def test_uses_http_map_url_and_action_log_fallbacks(self):
        action_log = SimpleNamespace(
            map_link='',
            latitude='24.7136',
            longitude='46.6753',
        )
        line = SimpleNamespace(
            line_no=2,
            doc_page='Page-1',
            source='Action Log',
            map_url='',
            attachment_storage_path='',
            attachment_label='',
            action_log=action_log,
        )
        row = resolve_pod_page_display_row(
            line,
            file_url_builder=lambda _path: '',
            attachment_meta_resolver=lambda _log: ('photo.jpg', '/media/photo.jpg'),
        )
        self.assertEqual(row['map_url'], 'https://maps.google.com/?q=24.7136,46.6753')
        self.assertEqual(row['attachment_label'], 'photo.jpg')
        self.assertEqual(row['attachment_url'], '/media/photo.jpg')


class ActionLogAttachmentStoragePathTests(TestCase):
    def test_returns_file_storage_name(self):
        media = SimpleNamespace(
            description='',
            file=SimpleNamespace(name='mobile/pod_evidence/file.mp4', url='/media/file.mp4'),
        )
        self.assertEqual(
            action_log_attachment_storage_path_from_media([media]),
            'mobile/pod_evidence/file.mp4',
        )
