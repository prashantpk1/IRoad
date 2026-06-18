from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from config.text_validators import (
    ArabicTextFormMixin,
    is_arabic_text_field,
    is_english_text_field,
    validate_arabic_text,
    validate_digits_only_text,
    validate_english_text,
)
from django import forms


class ArabicTextValidationTests(SimpleTestCase):
    def test_is_arabic_text_field(self):
        self.assertTrue(is_arabic_text_field('name_arabic'))
        self.assertTrue(is_arabic_text_field('arabic_label'))
        self.assertTrue(is_arabic_text_field('name_ar'))
        self.assertFalse(is_arabic_text_field('name_english'))
        self.assertFalse(is_arabic_text_field('content_ar'))

    def test_is_english_text_field(self):
        self.assertTrue(is_english_text_field('name_english'))
        self.assertTrue(is_english_text_field('english_label'))
        self.assertTrue(is_english_text_field('role_name_en'))
        self.assertTrue(is_english_text_field('price_list_name'))
        self.assertFalse(is_english_text_field('body_en'))
        self.assertFalse(is_english_text_field('description_en'))
        self.assertFalse(is_english_text_field('name_arabic'))

    def test_validate_arabic_text_accepts_arabic(self):
        value = validate_arabic_text('شركة الصفا للخدمات')
        self.assertEqual(value, 'شركة الصفا للخدمات')

    def test_validate_arabic_text_allows_empty_when_optional(self):
        self.assertEqual(validate_arabic_text(''), '')
        self.assertEqual(validate_arabic_text('   '), '')

    def test_validate_arabic_text_rejects_latin(self):
        with self.assertRaises(ValidationError):
            validate_arabic_text('ABC Company')

    def test_validate_arabic_text_rejects_mixed(self):
        with self.assertRaises(ValidationError):
            validate_arabic_text('شركة ABC')

    def test_validate_arabic_text_required(self):
        with self.assertRaises(ValidationError):
            validate_arabic_text('', required=True, field_label='Arabic name')


class _SampleArabicForm(ArabicTextFormMixin, forms.Form):
    name_arabic = forms.CharField(required=False)
    name_english = forms.CharField(required=False)


class ArabicTextFormMixinTests(SimpleTestCase):
    def test_form_mixin_rejects_non_arabic(self):
        form = _SampleArabicForm(data={'name_arabic': 'English', 'name_english': 'OK'})
        self.assertFalse(form.is_valid())
        self.assertIn('name_arabic', form.errors)

    def test_form_mixin_allows_english_field(self):
        form = _SampleArabicForm(data={'name_arabic': 'شركة', 'name_english': 'Company'})
        self.assertTrue(form.is_valid())

    def test_form_mixin_rejects_non_english(self):
        form = _SampleArabicForm(data={'name_arabic': 'شركة', 'name_english': 'شركة'})
        self.assertFalse(form.is_valid())
        self.assertIn('name_english', form.errors)


class EnglishTextValidationTests(SimpleTestCase):
    def test_validate_english_text_accepts_latin(self):
        value = validate_english_text("Al Safa Trading Co.")
        self.assertEqual(value, "Al Safa Trading Co.")

    def test_validate_english_text_rejects_arabic(self):
        with self.assertRaises(ValidationError):
            validate_english_text('شركة الصفا')

    def test_validate_english_text_rejects_digits(self):
        with self.assertRaises(ValidationError):
            validate_english_text('Company 123')

    def test_validate_english_text_required(self):
        with self.assertRaises(ValidationError):
            validate_english_text('', required=True, field_label='Name (English)')


class DigitsOnlyValidationTests(SimpleTestCase):
    def test_validate_digits_only_text_accepts_numbers(self):
        self.assertEqual(validate_digits_only_text('1234567890'), '1234567890')

    def test_validate_digits_only_text_allows_empty_when_optional(self):
        self.assertEqual(validate_digits_only_text(''), '')

    def test_validate_digits_only_text_rejects_letters(self):
        with self.assertRaises(ValidationError):
            validate_digits_only_text('123ABC')

    def test_validate_digits_only_text_required(self):
        with self.assertRaises(ValidationError):
            validate_digits_only_text('', required=True, field_label='CR number')
