"""
ModelForms for IRoad marketing home page CMS (superadmin).
"""

from django import forms
from django.db import models as dj_models
from django.forms import ModelForm, TextInput, Textarea, FileInput, CheckboxInput
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _

from iroad_frontend.models import (
    AboutApproachPillar,
    AboutFaqItem,
    AboutHowWorkStep,
    AboutPageContent,
    ContactPageContent,
    HomeMapLocation,
    HomePageContent,
    HomePricingBenefit,
    HomePricingTier,
    HomeServiceCard,
    HomeTestimonial,
    PricingFaqItem,
    PricingInteractiveStep,
    PricingPageContent,
    MobileAboutUsPageContent,
    PrivacyPolicyPageContent,
    TermsConditionsPageContent,
)

_CTRL = {'class': 'form-control'}
_TEXTAREA_ATTRS = {'class': 'form-control', 'rows': 3}
_LEGAL_RICH_TEXTAREA_ATTRS = {'class': 'form-control', 'rows': 16}


def _apply_home_page_widgets(form):
    for name, field in form.fields.items():
        mf = HomePageContent._meta.get_field(name)
        if isinstance(mf, dj_models.TextField):
            field.widget = Textarea(attrs=_TEXTAREA_ATTRS.copy())
        elif isinstance(mf, dj_models.FileField):
            field.widget = FileInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.CharField):
            field.widget = TextInput(attrs=_CTRL.copy())


def _apply_child_widgets(form, model):
    for name, field in form.fields.items():
        mf = model._meta.get_field(name)
        if isinstance(mf, dj_models.TextField):
            field.widget = Textarea(attrs=_TEXTAREA_ATTRS.copy())
        elif isinstance(mf, dj_models.FileField):
            field.widget = FileInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.BooleanField):
            field.widget = CheckboxInput(attrs={'class': 'form-check-input'})
        elif isinstance(mf, dj_models.CharField):
            field.widget = TextInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.PositiveSmallIntegerField):
            field.widget = TextInput(attrs=_CTRL.copy())


def _apply_about_page_widgets(form):
    """About singleton: TextInput / Textarea / FileInput by field type."""
    for name, field in form.fields.items():
        mf = AboutPageContent._meta.get_field(name)
        if isinstance(mf, dj_models.TextField):
            field.widget = Textarea(attrs=_TEXTAREA_ATTRS.copy())
        elif isinstance(mf, dj_models.FileField):
            field.widget = FileInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.CharField):
            field.widget = TextInput(attrs=_CTRL.copy())


def _apply_pricing_page_widgets(form):
    """Pricing singleton: same widget rules as about page CMS."""
    for name, field in form.fields.items():
        mf = PricingPageContent._meta.get_field(name)
        if isinstance(mf, dj_models.TextField):
            field.widget = Textarea(attrs=_TEXTAREA_ATTRS.copy())
        elif isinstance(mf, dj_models.FileField):
            field.widget = FileInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.CharField):
            field.widget = TextInput(attrs=_CTRL.copy())


def _apply_contact_page_widgets(form):
    """Contact singleton: TextInput / Textarea / FileInput (ImageField is FileField subclass)."""
    for name, field in form.fields.items():
        mf = ContactPageContent._meta.get_field(name)
        if isinstance(mf, dj_models.TextField):
            field.widget = Textarea(attrs=_TEXTAREA_ATTRS.copy())
        elif isinstance(mf, dj_models.FileField):
            field.widget = FileInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.CharField):
            field.widget = TextInput(attrs=_CTRL.copy())


def _html_to_plain_text(value: str) -> str:
    """Strip tags and collapse whitespace for required-body checks (TinyMCE HTML)."""
    plain = strip_tags(value or '')
    plain = plain.replace('\xa0', ' ').strip()
    return plain


def _apply_legal_page_widgets(form, model_cls):
    """
    Privacy / Terms singleton: Char/Text/File like other marketing CMS.
    Main legal body uses a taller textarea (TinyMCE attaches in admin template).
    """
    for name, field in form.fields.items():
        mf = model_cls._meta.get_field(name)
        if name in ('content_en', 'content_ar'):
            attrs = {**_LEGAL_RICH_TEXTAREA_ATTRS}
            if name == 'content_ar':
                attrs['dir'] = 'rtl'
            field.widget = Textarea(attrs=attrs)
        elif isinstance(mf, dj_models.TextField):
            field.widget = Textarea(attrs=_TEXTAREA_ATTRS.copy())
        elif isinstance(mf, dj_models.FileField):
            field.widget = FileInput(attrs=_CTRL.copy())
        elif isinstance(mf, dj_models.CharField):
            field.widget = TextInput(attrs=_CTRL.copy())


class LegalPageSingletonFormMixin:
    """
    Shared validation for bilingual legal singleton forms.
    HTML from TinyMCE is stored as-is (trusted superadmin); public views
    should render with an appropriate sanitization policy.
    """

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data

        title_en = (cleaned_data.get('page_title_en') or '').strip()
        title_ar = (cleaned_data.get('page_title_ar') or '').strip()
        if not title_en:
            self.add_error(
                'page_title_en',
                _('English page title is required.'),
            )
        if not title_ar:
            self.add_error(
                'page_title_ar',
                _('Arabic page title is required.'),
            )

        body_en = _html_to_plain_text(cleaned_data.get('content_en', ''))
        body_ar = _html_to_plain_text(cleaned_data.get('content_ar', ''))
        if not body_en:
            self.add_error(
                'content_en',
                _('English content is required.'),
            )
        if not body_ar:
            self.add_error(
                'content_ar',
                _('Arabic content is required.'),
            )

        return cleaned_data


class HomePageContentForm(ModelForm):
    """Singleton home page — all editable columns except id / auto timestamp."""

    class Meta:
        model = HomePageContent
        exclude = ('id', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_home_page_widgets(self)


class HomeServiceCardForm(ModelForm):
    class Meta:
        model = HomeServiceCard
        exclude = ('home',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, HomeServiceCard)


class HomePricingTierForm(ModelForm):
    class Meta:
        model = HomePricingTier
        exclude = ('home',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, HomePricingTier)


class HomeTestimonialForm(ModelForm):
    class Meta:
        model = HomeTestimonial
        exclude = ('home',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, HomeTestimonial)


class HomeMapLocationForm(ModelForm):
    class Meta:
        model = HomeMapLocation
        exclude = ('home',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, HomeMapLocation)


class HomePricingBenefitForm(ModelForm):
    class Meta:
        model = HomePricingBenefit
        exclude = ('home',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, HomePricingBenefit)


class AboutPageContentForm(ModelForm):
    """Singleton about page — same widget rules as home CMS."""

    class Meta:
        model = AboutPageContent
        exclude = ('updated_at', 'updated_by')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_about_page_widgets(self)


class AboutApproachPillarForm(ModelForm):
    class Meta:
        model = AboutApproachPillar
        exclude = ('about',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, AboutApproachPillar)


class AboutHowWorkStepForm(ModelForm):
    class Meta:
        model = AboutHowWorkStep
        exclude = ('about',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, AboutHowWorkStep)


class AboutFaqItemForm(ModelForm):
    class Meta:
        model = AboutFaqItem
        exclude = ('about',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, AboutFaqItem)


class PricingFaqItemForm(ModelForm):
    class Meta:
        model = PricingFaqItem
        exclude = ('pricing',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, PricingFaqItem)


class PricingPageContentForm(ModelForm):
    """Singleton pricing page — same widget rules as about page CMS."""

    class Meta:
        model = PricingPageContent
        exclude = ('updated_at', 'updated_by')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_pricing_page_widgets(self)


class ContactPageContentForm(ModelForm):
    """Singleton contact page — bilingual labels, form copy, sidebar info."""

    class Meta:
        model = ContactPageContent
        exclude = ('updated_at', 'updated_by')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_contact_page_widgets(self)


class PricingInteractiveStepForm(ModelForm):
    class Meta:
        model = PricingInteractiveStep
        fields = (
            'order',
            'title_en',
            'title_ar',
            'subtitle_en',
            'subtitle_ar',
            'body_en',
            'body_ar',
            'icon',
            'bg_image',
            'detail_url',
            'is_active',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_child_widgets(self, PricingInteractiveStep)


class PrivacyPolicyPageContentForm(LegalPageSingletonFormMixin, ModelForm):
    """Singleton privacy policy — bilingual body + SEO (TinyMCE in admin template)."""

    class Meta:
        model = PrivacyPolicyPageContent
        exclude = ('id', 'created_at', 'updated_at', 'updated_by')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_legal_page_widgets(self, PrivacyPolicyPageContent)


class TermsConditionsPageContentForm(LegalPageSingletonFormMixin, ModelForm):
    """Singleton terms & conditions — bilingual body + SEO (TinyMCE in admin template)."""

    class Meta:
        model = TermsConditionsPageContent
        exclude = ('id', 'created_at', 'updated_at', 'updated_by')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_legal_page_widgets(self, TermsConditionsPageContent)


class MobileAboutUsPageContentForm(LegalPageSingletonFormMixin, ModelForm):
    """Singleton mobile app About Us — bilingual body + SEO (TinyMCE in admin template)."""

    class Meta:
        model = MobileAboutUsPageContent
        exclude = ('id', 'created_at', 'updated_at', 'updated_by')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_legal_page_widgets(self, MobileAboutUsPageContent)
