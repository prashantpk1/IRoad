"""
Tests for mobile list pagination helper.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.list_pagination import paginate_sequence, parse_list_pagination


class ListPaginationTests(SimpleTestCase):
    def test_parse_defaults(self):
        params = parse_list_pagination(None, None)
        self.assertEqual(params.page, 1)
        self.assertEqual(params.page_size, 10)

    def test_parse_caps_page_size(self):
        params = parse_list_pagination('2', '500')
        self.assertEqual(params.page, 2)
        self.assertEqual(params.page_size, 100)

    def test_paginate_sequence_page_two(self):
        rows = list(range(15))
        page = paginate_sequence(rows, page=2, page_size=10)
        self.assertEqual(page['count'], 5)
        self.assertEqual(page['results_found'], 15)
        self.assertEqual(page['total_records'], 15)
        self.assertEqual(page['total_pages'], 2)
        self.assertEqual(page['current_page'], 2)
        self.assertEqual(page['items'], [10, 11, 12, 13, 14])
