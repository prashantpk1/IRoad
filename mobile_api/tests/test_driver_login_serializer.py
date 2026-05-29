"""Driver login serializer — email and phone formats."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.serializers.driver_auth import DriverLoginSerializer


class DriverLoginSerializerTests(SimpleTestCase):
    def test_email_only_valid(self):
        s = DriverLoginSerializer(
            data={
                'email': 'user@example.com',
                'password': 'secret',
            },
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_phone_requires_extension(self):
        s = DriverLoginSerializer(
            data={
                'phone': '987456321',
                'password': 'secret',
            },
        )
        self.assertFalse(s.is_valid())

    def test_phone_with_extension_valid(self):
        s = DriverLoginSerializer(
            data={
                'extension': '+966',
                'phone': '987456321',
                'password': 'secret',
            },
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_neither_email_nor_phone_invalid(self):
        s = DriverLoginSerializer(data={'password': 'secret'})
        self.assertFalse(s.is_valid())

    def test_email_and_phone_both_invalid(self):
        s = DriverLoginSerializer(
            data={
                'email': 'user@example.com',
                'extension': '+966',
                'phone': '987456321',
                'password': 'secret',
            },
        )
        self.assertFalse(s.is_valid())
