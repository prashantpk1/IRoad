"""
iroad_frontend/models.py

CMS models for IRoad landing page.
All text fields are bilingual (EN + AR).
Images stored under media/marketing/home/
Singleton pattern for main content.
Child models for repeatable sections.
"""

from django.core.validators import FileExtensionValidator
from django.db import models

# ImageField uses Pillow and rejects SVG. CMS accepts logos/icons as SVG via FileField.
_CMS_UPLOAD_VALIDATORS = [
    FileExtensionValidator(
        allowed_extensions=[
            'svg',
            'png',
            'jpg',
            'jpeg',
            'gif',
            'webp',
            'ico',
            'bmp',
            'avif',
            'tif',
            'tiff',
        ],
    ),
]


def home_upload_path(instance, filename):
    return f'marketing/home/{filename}'


# ── Main Singleton ────────────────────────────────────────────────


class HomePageContent(models.Model):
    """
    Singleton CMS model for Home Page.
    Only ONE record should exist.
    All sections stored here except repeaters.
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200, blank=True, default='')
    page_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')
    favicon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )

    # ── Header ───────────────────────────────────────────────────
    logo_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    logo_alt_en = models.CharField(
        max_length=100, blank=True, default='IRoad')
    logo_alt_ar = models.CharField(
        max_length=100, blank=True, default='آيروود')
    nav_home_en = models.CharField(
        max_length=50, blank=True, default='Home')
    nav_home_ar = models.CharField(
        max_length=50, blank=True, default='الرئيسية')
    nav_about_en = models.CharField(
        max_length=50, blank=True, default='About')
    nav_about_ar = models.CharField(
        max_length=50, blank=True, default='عن الشركة')
    nav_pricing_en = models.CharField(
        max_length=50, blank=True, default='Pricing')
    nav_pricing_ar = models.CharField(
        max_length=50, blank=True, default='الأسعار')
    nav_contact_en = models.CharField(
        max_length=50, blank=True, default='Contact')
    nav_contact_ar = models.CharField(
        max_length=50, blank=True, default='اتصل بنا')
    header_cta_small_title_en = models.CharField(
        max_length=100, blank=True, default='')
    header_cta_small_title_ar = models.CharField(
        max_length=100, blank=True, default='')
    header_cta_title_en = models.CharField(
        max_length=100, blank=True, default='Book a Demo')
    header_cta_title_ar = models.CharField(
        max_length=100, blank=True, default='احجز عرضاً')
    header_cta_url = models.CharField(
        max_length=500, blank=True, default='#')
    header_sign_in_en = models.CharField(
        max_length=50, blank=True, default='Sign In')
    header_sign_in_ar = models.CharField(
        max_length=50, blank=True, default='تسجيل الدخول')
    header_sign_in_url = models.CharField(
        max_length=500, blank=True, default='/login/')

    # ── Hero ─────────────────────────────────────────────────────
    hero_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    hero_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    hero_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    hero_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    hero_subheading_en = models.TextField(blank=True, default='')
    hero_subheading_ar = models.TextField(blank=True, default='')
    hero_cta_label_en = models.CharField(
        max_length=100, blank=True, default='Start Free Trial')
    hero_cta_label_ar = models.CharField(
        max_length=100, blank=True, default='ابدأ مجاناً')
    hero_cta_url = models.CharField(
        max_length=500, blank=True, default='#')
    hero_bullet_1_en = models.CharField(
        max_length=200, blank=True, default='')
    hero_bullet_1_ar = models.CharField(
        max_length=200, blank=True, default='')
    hero_bullet_2_en = models.CharField(
        max_length=200, blank=True, default='')
    hero_bullet_2_ar = models.CharField(
        max_length=200, blank=True, default='')
    hero_bullet_3_en = models.CharField(
        max_length=200, blank=True, default='')
    hero_bullet_3_ar = models.CharField(
        max_length=200, blank=True, default='')
    hero_image_primary = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    hero_image_secondary = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )

    # ── Ticker ───────────────────────────────────────────────────
    ticker_item_1_en = models.CharField(
        max_length=100, blank=True, default='Fleet Management')
    ticker_item_1_ar = models.CharField(
        max_length=100, blank=True, default='إدارة الأسطول')
    ticker_item_2_en = models.CharField(
        max_length=100, blank=True, default='Shipment Tracking')
    ticker_item_2_ar = models.CharField(
        max_length=100, blank=True, default='تتبع الشحنات')
    ticker_item_3_en = models.CharField(
        max_length=100, blank=True, default='Finance Automation')
    ticker_item_3_ar = models.CharField(
        max_length=100, blank=True, default='أتمتة المالية')
    ticker_item_4_en = models.CharField(
        max_length=100, blank=True, default='Driver App')
    ticker_item_4_ar = models.CharField(
        max_length=100, blank=True, default='تطبيق السائق')
    ticker_item_5_en = models.CharField(
        max_length=100, blank=True, default='POD Management')
    ticker_item_5_ar = models.CharField(
        max_length=100, blank=True, default='إدارة التسليم')

    # ── About ────────────────────────────────────────────────────
    about_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    about_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    about_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    about_body_en = models.TextField(blank=True, default='')
    about_body_ar = models.TextField(blank=True, default='')
    about_main_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_point_1_title_en = models.CharField(
        max_length=200, blank=True, default='')
    about_point_1_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_point_1_body_en = models.TextField(blank=True, default='')
    about_point_1_body_ar = models.TextField(blank=True, default='')
    about_point_1_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_point_2_title_en = models.CharField(
        max_length=200, blank=True, default='')
    about_point_2_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_point_2_body_en = models.TextField(blank=True, default='')
    about_point_2_body_ar = models.TextField(blank=True, default='')
    about_point_2_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_experience_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_experience_number = models.CharField(
        max_length=20, blank=True, default='25')
    about_experience_suffix_en = models.CharField(
        max_length=20, blank=True, default='+')
    about_experience_suffix_ar = models.CharField(
        max_length=20, blank=True, default='+')
    about_experience_caption_en = models.CharField(
        max_length=200, blank=True, default='')
    about_experience_caption_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_cta_label_en = models.CharField(
        max_length=100, blank=True, default='More About Us')
    about_cta_label_ar = models.CharField(
        max_length=100, blank=True, default='المزيد عنا')
    about_cta_url = models.CharField(
        max_length=500, blank=True, default='/about/')

    # ── Services Section Header ───────────────────────────────────
    services_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    services_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    services_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    services_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    services_footer_text_en = models.CharField(
        max_length=300, blank=True, default='')
    services_footer_text_ar = models.CharField(
        max_length=300, blank=True, default='')
    services_footer_link_label_en = models.CharField(
        max_length=100, blank=True, default='Start Free Trial')
    services_footer_link_label_ar = models.CharField(
        max_length=100, blank=True, default='ابدأ مجاناً')
    services_footer_link_url = models.CharField(
        max_length=500, blank=True, default='#')

    # ── Why Choose Section ────────────────────────────────────────
    why_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    why_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    why_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    why_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    why_point_1_title_en = models.CharField(
        max_length=200, blank=True, default='')
    why_point_1_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    why_point_1_body_en = models.TextField(blank=True, default='')
    why_point_1_body_ar = models.TextField(blank=True, default='')
    why_point_1_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    why_point_2_title_en = models.CharField(
        max_length=200, blank=True, default='')
    why_point_2_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    why_point_2_body_en = models.TextField(blank=True, default='')
    why_point_2_body_ar = models.TextField(blank=True, default='')
    why_point_2_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    why_point_3_title_en = models.CharField(
        max_length=200, blank=True, default='')
    why_point_3_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    why_point_3_body_en = models.TextField(blank=True, default='')
    why_point_3_body_ar = models.TextField(blank=True, default='')
    why_point_3_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    why_image_1 = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    why_image_2 = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    why_image_3 = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )

    # ── Advanced Features Section ─────────────────────────────────
    features_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    features_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    features_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    features_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    features_footer_text_en = models.CharField(
        max_length=300, blank=True, default='')
    features_footer_text_ar = models.CharField(
        max_length=300, blank=True, default='')
    features_footer_link_label_en = models.CharField(
        max_length=100, blank=True, default='')
    features_footer_link_label_ar = models.CharField(
        max_length=100, blank=True, default='')
    features_footer_link_url = models.CharField(
        max_length=500, blank=True, default='#')
    features_rating_value = models.CharField(
        max_length=10, blank=True, default='4.9/5')
    features_review_count_label_en = models.CharField(
        max_length=100, blank=True, default='4,200+ reviews')
    features_review_count_label_ar = models.CharField(
        max_length=100, blank=True, default='+4,200 تقييم')
    feature_a_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    feature_a_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    feature_a_title_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_a_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_a_body_en = models.TextField(blank=True, default='')
    feature_a_body_ar = models.TextField(blank=True, default='')
    feature_b_title_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_b_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_b_body_en = models.TextField(blank=True, default='')
    feature_b_body_ar = models.TextField(blank=True, default='')
    feature_b_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    feature_b_list_item_1_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_b_list_item_1_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_b_list_item_2_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_b_list_item_2_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_c_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    feature_c_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    feature_c_title_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_c_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_c_body_en = models.TextField(blank=True, default='')
    feature_c_body_ar = models.TextField(blank=True, default='')
    feature_d_title_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_d_title_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_d_body_en = models.TextField(blank=True, default='')
    feature_d_body_ar = models.TextField(blank=True, default='')
    feature_d_icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    feature_d_list_item_1_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_d_list_item_1_ar = models.CharField(
        max_length=200, blank=True, default='')
    feature_d_list_item_2_en = models.CharField(
        max_length=200, blank=True, default='')
    feature_d_list_item_2_ar = models.CharField(
        max_length=200, blank=True, default='')

    # ── Pricing Section Header (tier rows are HomePricingTier) ─────
    pricing_kicker_en = models.CharField(
        max_length=200, blank=True, default='Pricing Plans')
    pricing_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    pricing_heading_en = models.CharField(
        max_length=300, blank=True,
        default='Pricing that scales with your transport team')
    pricing_heading_ar = models.CharField(
        max_length=300, blank=True, default='')

    # ── Business / Map Section ────────────────────────────────────
    business_map_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    business_counter_value = models.CharField(
        max_length=20, blank=True, default='200')
    business_counter_suffix_en = models.CharField(
        max_length=20, blank=True, default='+')
    business_counter_suffix_ar = models.CharField(
        max_length=20, blank=True, default='+')
    business_counter_caption_en = models.CharField(
        max_length=200, blank=True, default='')
    business_counter_caption_ar = models.CharField(
        max_length=200, blank=True, default='')
    business_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    business_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    business_body_en = models.TextField(blank=True, default='')
    business_body_ar = models.TextField(blank=True, default='')
    business_bullet_1_en = models.CharField(
        max_length=200, blank=True, default='')
    business_bullet_1_ar = models.CharField(
        max_length=200, blank=True, default='')
    business_bullet_2_en = models.CharField(
        max_length=200, blank=True, default='')
    business_bullet_2_ar = models.CharField(
        max_length=200, blank=True, default='')
    business_side_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )

    # ── Testimonials Section Header ───────────────────────────────
    testimonials_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    testimonials_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    testimonials_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    testimonials_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    testimonials_hero_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    testimonials_happy_count = models.CharField(
        max_length=20, blank=True, default='10+k')
    testimonials_happy_label_en = models.CharField(
        max_length=100, blank=True, default='Happy Customers')
    testimonials_happy_label_ar = models.CharField(
        max_length=100, blank=True, default='عملاء سعداء')

    # ── Footer ───────────────────────────────────────────────────
    footer_cta_left_en = models.CharField(
        max_length=200, blank=True, default="Let's Connect")
    footer_cta_left_ar = models.CharField(
        max_length=200, blank=True, default='لنتواصل')
    footer_brand_text_en = models.CharField(
        max_length=100, blank=True, default='IRoad')
    footer_brand_text_ar = models.CharField(
        max_length=100, blank=True, default='آيروود')
    footer_cta_right_en = models.CharField(
        max_length=200, blank=True, default='Book a Demo')
    footer_cta_right_ar = models.CharField(
        max_length=200, blank=True, default='احجز عرضاً')
    footer_about_blurb_en = models.TextField(blank=True, default='')
    footer_about_blurb_ar = models.TextField(blank=True, default='')
    footer_social_pinterest_url = models.CharField(
        max_length=500, blank=True, default='#')
    footer_social_x_url = models.CharField(
        max_length=500, blank=True, default='#')
    footer_social_facebook_url = models.CharField(
        max_length=500, blank=True, default='#')
    footer_social_instagram_url = models.CharField(
        max_length=500, blank=True, default='#')
    footer_column_title_en = models.CharField(
        max_length=100, blank=True, default='Features')
    footer_column_title_ar = models.CharField(
        max_length=100, blank=True, default='الميزات')
    footer_link_1_label_en = models.CharField(
        max_length=100, blank=True, default='About')
    footer_link_1_label_ar = models.CharField(
        max_length=100, blank=True, default='عن الشركة')
    footer_link_1_url = models.CharField(
        max_length=500, blank=True, default='/about/')
    footer_link_2_label_en = models.CharField(
        max_length=100, blank=True, default='Pricing')
    footer_link_2_label_ar = models.CharField(
        max_length=100, blank=True, default='الأسعار')
    footer_link_2_url = models.CharField(
        max_length=500, blank=True, default='/pricing/')
    footer_link_3_label_en = models.CharField(
        max_length=100, blank=True, default='Contact')
    footer_link_3_label_ar = models.CharField(
        max_length=100, blank=True, default='اتصل بنا')
    footer_link_3_url = models.CharField(
        max_length=500, blank=True, default='/contact/')
    footer_newsletter_title_en = models.CharField(
        max_length=200, blank=True, default='Get Product Updates')
    footer_newsletter_title_ar = models.CharField(
        max_length=200, blank=True, default='احصل على تحديثات المنتج')
    footer_newsletter_desc_en = models.TextField(
        blank=True, default='')
    footer_newsletter_desc_ar = models.TextField(
        blank=True, default='')
    footer_newsletter_placeholder_en = models.CharField(
        max_length=100, blank=True, default='Enter your email')
    footer_newsletter_placeholder_ar = models.CharField(
        max_length=100, blank=True, default='أدخل بريدك الإلكتروني')
    footer_newsletter_action_url = models.CharField(
        max_length=500, blank=True, default='#')
    footer_copyright_en = models.CharField(
        max_length=300, blank=True,
        default='© 2026 All Rights Reserved.')
    footer_copyright_ar = models.CharField(
        max_length=300, blank=True,
        default='© 2026 جميع الحقوق محفوظة.')
    footer_credit_en = models.CharField(
        max_length=300, blank=True, default='')
    footer_credit_ar = models.CharField(
        max_length=300, blank=True, default='')

    # ── Audit ─────────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200, blank=True, default='')

    class Meta:
        db_table = 'iroad_frontend_home_content'
        verbose_name = 'Home Page Content'
        verbose_name_plural = 'Home Page Content'

    def __str__(self):
        return 'Home Page Content'

    @classmethod
    def get_singleton(cls):
        """Get or create the single CMS record."""
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


# ── Service Cards (repeater) ──────────────────────────────────────


class HomeServiceCard(models.Model):
    """4 service feature cards in Core Features section."""
    home = models.ForeignKey(
        HomePageContent,
        on_delete=models.CASCADE,
        related_name='service_cards',
    )
    order = models.PositiveSmallIntegerField(default=0)
    title_en = models.CharField(max_length=200, blank=True, default='')
    title_ar = models.CharField(max_length=200, blank=True, default='')
    summary_en = models.TextField(blank=True, default='')
    summary_ar = models.TextField(blank=True, default='')
    icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    detail_url = models.CharField(
        max_length=500, blank=True, default='#')
    cta_label_en = models.CharField(
        max_length=100, blank=True, default='Explore Feature')
    cta_label_ar = models.CharField(
        max_length=100, blank=True, default='استكشف الميزة')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_home_service_card'
        ordering = ['order']
        verbose_name = 'Service Card'
        verbose_name_plural = 'Service Cards'

    def __str__(self):
        return f'Service Card {self.order}: {self.title_en}'


# ── Pricing Tiers (repeater) ──────────────────────────────────────


class HomePricingTier(models.Model):
    """3 pricing plan tiers in Pricing section."""
    home = models.ForeignKey(
        HomePageContent,
        on_delete=models.CASCADE,
        related_name='pricing_tiers',
    )
    order = models.PositiveSmallIntegerField(default=0)
    name_en = models.CharField(max_length=100, blank=True, default='')
    name_ar = models.CharField(max_length=100, blank=True, default='')
    summary_en = models.TextField(blank=True, default='')
    summary_ar = models.TextField(blank=True, default='')
    price_display_en = models.CharField(
        max_length=50, blank=True, default='')
    price_display_ar = models.CharField(
        max_length=50, blank=True, default='')
    bullet_1_en = models.CharField(max_length=200, blank=True, default='')
    bullet_1_ar = models.CharField(max_length=200, blank=True, default='')
    bullet_2_en = models.CharField(max_length=200, blank=True, default='')
    bullet_2_ar = models.CharField(max_length=200, blank=True, default='')
    bullet_3_en = models.CharField(max_length=200, blank=True, default='')
    bullet_3_ar = models.CharField(max_length=200, blank=True, default='')
    bullet_4_en = models.CharField(max_length=200, blank=True, default='')
    bullet_4_ar = models.CharField(max_length=200, blank=True, default='')
    cta_label_en = models.CharField(
        max_length=100, blank=True, default='Start Free Trial')
    cta_label_ar = models.CharField(
        max_length=100, blank=True, default='ابدأ مجاناً')
    cta_url = models.CharField(max_length=500, blank=True, default='#')
    is_featured = models.BooleanField(
        default=False,
        help_text='Highlighted plan (e.g. Business)')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_home_pricing_tier'
        ordering = ['order']
        verbose_name = 'Pricing Tier'
        verbose_name_plural = 'Pricing Tiers'

    def __str__(self):
        return f'Plan {self.order}: {self.name_en}'


class HomePricingBenefit(models.Model):
    """
    Repeater: benefit bullets under pricing tiers (Home + Pricing pages).
    Icons and EN/AR text are fully CMS-managed.
    """
    home = models.ForeignKey(
        HomePageContent,
        on_delete=models.CASCADE,
        related_name='pricing_benefits',
    )
    order = models.PositiveSmallIntegerField(default=0)
    text_en = models.CharField(max_length=300, blank=True, default='')
    text_ar = models.CharField(max_length=300, blank=True, default='')
    icon = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_home_pricing_benefit'
        ordering = ['order']
        verbose_name = 'Pricing Benefit'
        verbose_name_plural = 'Pricing Benefits'

    def __str__(self):
        return f'Benefit {self.order}: {self.text_en[:40]}'


# ── Testimonials (repeater) ───────────────────────────────────────


class HomeTestimonial(models.Model):
    """3 testimonial slides in Testimonials section."""
    home = models.ForeignKey(
        HomePageContent,
        on_delete=models.CASCADE,
        related_name='testimonials',
    )
    order = models.PositiveSmallIntegerField(default=0)
    quote_en = models.TextField(blank=True, default='')
    quote_ar = models.TextField(blank=True, default='')
    author_name_en = models.CharField(
        max_length=200, blank=True, default='')
    author_name_ar = models.CharField(
        max_length=200, blank=True, default='')
    author_role_en = models.CharField(
        max_length=200, blank=True, default='')
    author_role_ar = models.CharField(
        max_length=200, blank=True, default='')
    author_avatar = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    company_logo = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_home_testimonial'
        ordering = ['order']
        verbose_name = 'Testimonial'
        verbose_name_plural = 'Testimonials'

    def __str__(self):
        return f'Testimonial {self.order}: {self.author_name_en}'


# ── Map Location Cards (repeater) ─────────────────────────────────


class HomeMapLocation(models.Model):
    """4 map pin cards in Business/Map section."""
    home = models.ForeignKey(
        HomePageContent,
        on_delete=models.CASCADE,
        related_name='map_locations',
    )
    order = models.PositiveSmallIntegerField(default=0)
    title_en = models.CharField(max_length=200, blank=True, default='')
    title_ar = models.CharField(max_length=200, blank=True, default='')
    subtitle_en = models.CharField(
        max_length=300, blank=True, default='')
    subtitle_ar = models.CharField(
        max_length=300, blank=True, default='')
    card_image = models.FileField(
        upload_to=home_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_home_map_location'
        ordering = ['order']
        verbose_name = 'Map Location'
        verbose_name_plural = 'Map Locations'

    def __str__(self):
        return f'Location {self.order}: {self.title_en}'


# ── About Page CMS ────────────────────────────────────────────────


def about_upload_path(instance, filename):
    return f'marketing/about/{filename}'


class AboutPageContent(models.Model):
    """
    Singleton CMS for About Page.
    One record only — get_singleton() pattern.
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200, blank=True,
        default='About IRoad - Transport Management SaaS')
    page_title_ar = models.CharField(
        max_length=200, blank=True, default='عن آيروود')
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')

    # ── Page Header / Breadcrumb ──────────────────────────────────
    page_header_h1_en = models.CharField(
        max_length=300, blank=True, default='About IRoad')
    page_header_h1_ar = models.CharField(
        max_length=300, blank=True, default='عن آيروود')
    breadcrumb_current_en = models.CharField(
        max_length=100, blank=True, default='About IRoad')
    breadcrumb_current_ar = models.CharField(
        max_length=100, blank=True, default='عن آيروود')
    page_header_background = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
        verbose_name='Page header background image',
        help_text=(
            'Optional hero background for the about page header. '
            'If empty, a solid theme fallback is used (no stock photo).'
        ),
    )

    # ── About Us Section ──────────────────────────────────────────
    about_kicker_en = models.CharField(
        max_length=200, blank=True, default='About IRoad')
    about_kicker_ar = models.CharField(
        max_length=200, blank=True, default='عن آيروود')
    about_heading_part1_en = models.CharField(
        max_length=300, blank=True, default='')
    about_heading_part1_ar = models.CharField(
        max_length=300, blank=True, default='')
    about_heading_part2_en = models.CharField(
        max_length=200, blank=True, default='')
    about_heading_part2_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_heading_part3_en = models.CharField(
        max_length=200, blank=True, default='')
    about_heading_part3_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_counter_1_value = models.CharField(
        max_length=20, blank=True, default='24/7')
    about_counter_1_label_en = models.CharField(
        max_length=100, blank=True, default='System Availability')
    about_counter_1_label_ar = models.CharField(
        max_length=100, blank=True, default='توفر النظام')
    about_counter_2_value = models.CharField(
        max_length=20, blank=True, default='100+')
    about_counter_2_label_en = models.CharField(
        max_length=100, blank=True,
        default='Companies Using IRoad')
    about_counter_2_label_ar = models.CharField(
        max_length=100, blank=True,
        default='شركات تستخدم آيروود')
    about_body_en = models.TextField(blank=True, default='')
    about_body_ar = models.TextField(blank=True, default='')
    about_list_item_1_en = models.CharField(
        max_length=200, blank=True,
        default='End-to-End Workflow Automation')
    about_list_item_1_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_list_item_2_en = models.CharField(
        max_length=200, blank=True,
        default='Real-Time Tracking & Insights')
    about_list_item_2_ar = models.CharField(
        max_length=200, blank=True, default='')
    about_explore_label_en = models.CharField(
        max_length=100, blank=True, default='Explore Platform')
    about_explore_label_ar = models.CharField(
        max_length=100, blank=True, default='استكشف المنصة')
    about_explore_url = models.CharField(
        max_length=500, blank=True, default='#')
    about_footer_text_en = models.TextField(blank=True, default='')
    about_footer_text_ar = models.TextField(blank=True, default='')
    about_footer_cta_label_en = models.CharField(
        max_length=100, blank=True, default='Book a Demo')
    about_footer_cta_label_ar = models.CharField(
        max_length=100, blank=True, default='احجز عرضاً')
    about_footer_cta_url = models.CharField(
        max_length=500, blank=True, default='#')
    about_rating_value = models.CharField(
        max_length=20, blank=True, default='4.9/5')
    about_review_label_en = models.CharField(
        max_length=100, blank=True, default='4,200+ reviews')
    about_review_label_ar = models.CharField(
        max_length=100, blank=True, default='+4,200 تقييم')
    about_main_image = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_body_image = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_title_image_1 = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    about_title_image_2 = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    # Middle column (3-col about hero): title + body under counter 2
    about_mid_title_en = models.CharField(
        max_length=300, blank=True, default='')
    about_mid_title_ar = models.CharField(
        max_length=300, blank=True, default='')
    about_mid_body_en = models.TextField(blank=True, default='')
    about_mid_body_ar = models.TextField(blank=True, default='')

    # ── Our Approach Section ──────────────────────────────────────
    approach_kicker_en = models.CharField(
        max_length=200, blank=True, default='Our Approach')
    approach_kicker_ar = models.CharField(
        max_length=200, blank=True, default='نهجنا')
    approach_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    approach_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    approach_body_en = models.TextField(blank=True, default='')
    approach_body_ar = models.TextField(blank=True, default='')
    approach_cta_label_en = models.CharField(
        max_length=100, blank=True, default='Book a Demo')
    approach_cta_label_ar = models.CharField(
        max_length=100, blank=True, default='احجز عرضاً')
    approach_cta_url = models.CharField(
        max_length=500, blank=True, default='#')

    # ── How It Works Section ──────────────────────────────────────
    how_kicker_en = models.CharField(
        max_length=200, blank=True, default='How It Works')
    how_kicker_ar = models.CharField(
        max_length=200, blank=True, default='كيف يعمل')
    how_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    how_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    how_footer_text_en = models.TextField(blank=True, default='')
    how_footer_text_ar = models.TextField(blank=True, default='')
    how_footer_link_label_en = models.CharField(
        max_length=100, blank=True, default='Start Free Trial')
    how_footer_link_label_ar = models.CharField(
        max_length=100, blank=True, default='ابدأ مجاناً')
    how_footer_link_url = models.CharField(
        max_length=500, blank=True, default='#')
    how_rating_value = models.CharField(
        max_length=20, blank=True, default='4.9/5')
    how_review_label_en = models.CharField(
        max_length=100, blank=True, default='4,200+ reviews')
    how_review_label_ar = models.CharField(
        max_length=100, blank=True, default='+4,200 تقييم')

    # ── FAQ Section ───────────────────────────────────────────────
    faq_kicker_en = models.CharField(
        max_length=200, blank=True, default='FAQs')
    faq_kicker_ar = models.CharField(
        max_length=200, blank=True, default='الأسئلة الشائعة')
    faq_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    faq_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    faq_intro_en = models.TextField(blank=True, default='')
    faq_intro_ar = models.TextField(blank=True, default='')
    faq_view_all_label_en = models.CharField(
        max_length=100, blank=True, default="View all FAQ's")
    faq_view_all_label_ar = models.CharField(
        max_length=100, blank=True, default='عرض كل الأسئلة')
    faq_view_all_url = models.CharField(
        max_length=500, blank=True, default='#')

    # ── Audit ─────────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200, blank=True, default='')

    class Meta:
        db_table = 'iroad_frontend_about_content'
        verbose_name = 'About Page Content'
        verbose_name_plural = 'About Page Content'

    def __str__(self):
        return 'About Page Content'

    @classmethod
    def get_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class AboutApproachPillar(models.Model):
    """
    3 approach pillars: Mission, Vision, Core Value.
    """
    about = models.ForeignKey(
        AboutPageContent,
        on_delete=models.CASCADE,
        related_name='approach_pillars',
    )
    order = models.PositiveSmallIntegerField(default=0)
    title_en = models.CharField(
        max_length=200, blank=True, default='')
    title_ar = models.CharField(
        max_length=200, blank=True, default='')
    body_en = models.TextField(blank=True, default='')
    body_ar = models.TextField(blank=True, default='')
    icon = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_about_approach_pillar'
        ordering = ['order']
        verbose_name = 'Approach Pillar'
        verbose_name_plural = 'Approach Pillars'

    def __str__(self):
        return f'Pillar {self.order}: {self.title_en}'


class AboutHowWorkStep(models.Model):
    """
    4 how-it-works steps.
    """
    about = models.ForeignKey(
        AboutPageContent,
        on_delete=models.CASCADE,
        related_name='how_work_steps',
    )
    order = models.PositiveSmallIntegerField(default=0)
    step_number = models.CharField(
        max_length=10, blank=True, default='01')
    title_en = models.CharField(
        max_length=200, blank=True, default='')
    title_ar = models.CharField(
        max_length=200, blank=True, default='')
    body_en = models.TextField(blank=True, default='')
    body_ar = models.TextField(blank=True, default='')
    step_image = models.FileField(
        upload_to=about_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_about_how_work_step'
        ordering = ['order']
        verbose_name = 'How Work Step'
        verbose_name_plural = 'How Work Steps'

    def __str__(self):
        return f'Step {self.step_number}: {self.title_en}'


class AboutFaqItem(models.Model):
    """
    FAQ accordion items managed under About Page CMS (About page only).
    """
    about = models.ForeignKey(
        AboutPageContent,
        on_delete=models.CASCADE,
        related_name='faq_items',
    )
    order = models.PositiveSmallIntegerField(default=0)
    question_en = models.CharField(
        max_length=500, blank=True, default='')
    question_ar = models.CharField(
        max_length=500, blank=True, default='')
    answer_en = models.TextField(blank=True, default='')
    answer_ar = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_about_faq_item'
        ordering = ['order']
        verbose_name = 'About FAQ Item'
        verbose_name_plural = 'About FAQ Items'

    def __str__(self):
        return f'FAQ {self.order}: {self.question_en[:60]}'


# ── Pricing Page CMS ──────────────────────────────────────────────


def pricing_upload_path(instance, filename):
    return f'marketing/pricing/{filename}'


class PricingPageContent(models.Model):
    """
    Singleton CMS for Pricing Page.
    Reuses HomePricingTier, HomeTestimonial, HomeMapLocation from
    HomePageContent (same home=get_singleton()).
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200, blank=True,
        default='IRoad Pricing Plans')
    page_title_ar = models.CharField(
        max_length=200, blank=True, default='أسعار آيروود')
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')

    # ── Page Header ───────────────────────────────────────────────
    page_header_h1_en = models.CharField(
        max_length=300, blank=True,
        default='IRoad - SaaS Transport Management System Pricing Page')
    page_header_h1_ar = models.CharField(
        max_length=300, blank=True, default='صفحة أسعار آيروود')
    breadcrumb_current_en = models.CharField(
        max_length=100, blank=True, default='Pricing plans')
    breadcrumb_current_ar = models.CharField(
        max_length=100, blank=True, default='خطط الأسعار')
    page_header_background = models.FileField(
        upload_to=pricing_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
        verbose_name='Page header background image',
        help_text=(
            'Optional background for the pricing page header. '
            'If empty, a solid theme fallback is used (no stock photo).'
        ),
    )

    # ── Pricing Section Header ────────────────────────────────────
    pricing_kicker_en = models.CharField(
        max_length=200, blank=True, default='Pricing Plans')
    pricing_kicker_ar = models.CharField(
        max_length=200, blank=True, default='خطط الأسعار')
    pricing_heading_en = models.CharField(
        max_length=300, blank=True,
        default='Flexible pricing designed for your team')
    pricing_heading_ar = models.CharField(
        max_length=300, blank=True, default='')

    # ── Interactive Process Section ───────────────────────────────
    interactive_kicker_en = models.CharField(
        max_length=200, blank=True, default='')
    interactive_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    interactive_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    interactive_heading_ar = models.CharField(
        max_length=300, blank=True, default='')

    # ── Partner / Map Section ─────────────────────────────────────
    partner_kicker_en = models.CharField(
        max_length=200, blank=True, default='Trusted by…')
    partner_kicker_ar = models.CharField(
        max_length=200, blank=True, default='موثوق به من قبل...')
    partner_heading_en = models.CharField(
        max_length=300, blank=True, default='')
    partner_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    partner_body_en = models.TextField(blank=True, default='')
    partner_body_ar = models.TextField(blank=True, default='')
    partner_cta_label_en = models.CharField(
        max_length=100, blank=True, default='Book a Demo')
    partner_cta_label_ar = models.CharField(
        max_length=100, blank=True, default='احجز عرضاً')
    partner_cta_url = models.CharField(
        max_length=500, blank=True, default='#')
    partner_email_label_en = models.CharField(
        max_length=100, blank=True, default='Email')
    partner_email_label_ar = models.CharField(
        max_length=100, blank=True, default='البريد الإلكتروني')
    partner_email_value = models.CharField(
        max_length=200, blank=True, default='support@iroad.com')
    partner_platform_label_en = models.CharField(
        max_length=200, blank=True,
        default='Cloud-Based Platform - Accessible Worldwide')
    partner_platform_label_ar = models.CharField(
        max_length=200, blank=True, default='')
    partner_map_image = models.FileField(
        upload_to=pricing_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    counter_1_value = models.CharField(
        max_length=20, blank=True, default='10+')
    counter_1_label_en = models.CharField(
        max_length=100, blank=True, default='Modules')
    counter_1_label_ar = models.CharField(
        max_length=100, blank=True, default='وحدات')
    counter_2_value = models.CharField(
        max_length=20, blank=True, default='99.9%')
    counter_2_label_en = models.CharField(
        max_length=100, blank=True, default='Uptime')
    counter_2_label_ar = models.CharField(
        max_length=100, blank=True, default='وقت التشغيل')
    counter_3_value = models.CharField(
        max_length=20, blank=True, default='100+')
    counter_3_label_en = models.CharField(
        max_length=100, blank=True, default='Companies')
    counter_3_label_ar = models.CharField(
        max_length=100, blank=True, default='شركة')
    counter_4_value = models.CharField(
        max_length=20, blank=True, default='10K+')
    counter_4_label_en = models.CharField(
        max_length=100, blank=True, default='Orders Managed')
    counter_4_label_ar = models.CharField(
        max_length=100, blank=True, default='طلب مُدار')
    counter_5_value = models.CharField(
        max_length=20, blank=True, default='24/7')
    counter_5_label_en = models.CharField(
        max_length=100, blank=True, default='Access')
    counter_5_label_ar = models.CharField(
        max_length=100, blank=True, default='وصول')

    # ── Testimonials Section Header ───────────────────────────────
    testimonials_kicker_en = models.CharField(
        max_length=200, blank=True,
        default='Trusted by transport teams worldwide')
    testimonials_kicker_ar = models.CharField(
        max_length=200, blank=True, default='')
    testimonials_heading_en = models.CharField(
        max_length=300, blank=True,
        default='What transport teams say about IRoad')
    testimonials_heading_ar = models.CharField(
        max_length=300, blank=True, default='')

    # ── FAQ Section ───────────────────────────────────────────────
    faq_kicker_en = models.CharField(
        max_length=200, blank=True, default='FAQs')
    faq_kicker_ar = models.CharField(
        max_length=200, blank=True, default='الأسئلة الشائعة')
    faq_heading_en = models.CharField(
        max_length=300, blank=True,
        default='Answers to common questions about IRoad')
    faq_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    faq_intro_en = models.TextField(blank=True, default='')
    faq_intro_ar = models.TextField(blank=True, default='')
    faq_view_all_label_en = models.CharField(
        max_length=100, blank=True, default='View all FAQs')
    faq_view_all_label_ar = models.CharField(
        max_length=100, blank=True, default='عرض كل الأسئلة')
    faq_view_all_url = models.CharField(
        max_length=500, blank=True, default='#')

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200, blank=True, default='')

    class Meta:
        db_table = 'iroad_frontend_pricing_content'
        verbose_name = 'Pricing Page Content'
        verbose_name_plural = 'Pricing Page Content'

    def __str__(self):
        return 'Pricing Page Content'

    @classmethod
    def get_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class PricingFaqItem(models.Model):
    """
    FAQ items scoped to Pricing page only.
    Completely separate from AboutFaqItem.
    """
    pricing = models.ForeignKey(
        PricingPageContent,
        on_delete=models.CASCADE,
        related_name='faq_items',
    )
    order = models.PositiveSmallIntegerField(default=0)
    question_en = models.CharField(
        max_length=500, blank=True, default='')
    question_ar = models.CharField(
        max_length=500, blank=True, default='')
    answer_en = models.TextField(blank=True, default='')
    answer_ar = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_pricing_faq_item'
        ordering = ['order']
        verbose_name = 'Pricing FAQ Item'
        verbose_name_plural = 'Pricing FAQ Items'

    def __str__(self):
        return f'FAQ {self.order}: {self.question_en[:60]}'


class PricingInteractiveStep(models.Model):
    """
    4 interactive process items on pricing page.
    """
    pricing = models.ForeignKey(
        PricingPageContent,
        on_delete=models.CASCADE,
        related_name='interactive_steps',
    )
    order = models.PositiveSmallIntegerField(default=0)
    title_en = models.CharField(max_length=200, blank=True, default='')
    title_ar = models.CharField(max_length=200, blank=True, default='')
    subtitle_en = models.CharField(
        max_length=200, blank=True, default='')
    subtitle_ar = models.CharField(
        max_length=200, blank=True, default='')
    body_en = models.TextField(blank=True, default='')
    body_ar = models.TextField(blank=True, default='')
    icon = models.FileField(
        upload_to=pricing_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    bg_image = models.FileField(
        upload_to=pricing_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
    )
    detail_url = models.CharField(
        max_length=500, blank=True, default='#')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'iroad_frontend_pricing_interactive_step'
        ordering = ['order']
        verbose_name = 'Interactive Step'
        verbose_name_plural = 'Interactive Steps'

    def __str__(self):
        return f'Step {self.order}: {self.title_en}'


def contact_upload_path(instance, filename):
    return f'marketing/contact/{filename}'


class ContactPageContent(models.Model):
    """
    Singleton CMS for Contact Page.
    Manages all labels, info, and form field labels.
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200, blank=True, default='Contact IRoad')
    page_title_ar = models.CharField(
        max_length=200, blank=True, default='تواصل مع آيروود')
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')

    # ── Page Header ───────────────────────────────────────────────
    page_header_h1_en = models.CharField(
        max_length=300, blank=True, default='Contact IRoad')
    page_header_h1_ar = models.CharField(
        max_length=300, blank=True, default='تواصل مع آيروود')
    breadcrumb_current_en = models.CharField(
        max_length=100, blank=True, default='Contact')
    breadcrumb_current_ar = models.CharField(
        max_length=100, blank=True, default='تواصل')
    page_header_background = models.FileField(
        upload_to=contact_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
        verbose_name='Page header background image',
        help_text=(
            'Optional hero background for the contact page header. '
            'If empty, a solid theme fallback is used (no stock photo).'
        ),
    )

    # ── Contact Section ───────────────────────────────────────────
    section_kicker_en = models.CharField(
        max_length=200, blank=True, default='contact Us')
    section_kicker_ar = models.CharField(
        max_length=200, blank=True, default='تواصل معنا')
    section_heading_en = models.CharField(
        max_length=300, blank=True,
        default='Get in touch with our team to explore IRoad')
    section_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    contact_image = models.ImageField(
        upload_to=contact_upload_path,
        blank=True,
        null=True,
    )

    # ── Form Labels ───────────────────────────────────────────────
    form_title_en = models.CharField(
        max_length=200, blank=True, default='Request a Demo')
    form_title_ar = models.CharField(
        max_length=200, blank=True, default='اطلب عرضاً')
    form_fname_placeholder_en = models.CharField(
        max_length=100, blank=True, default='First Name')
    form_fname_placeholder_ar = models.CharField(
        max_length=100, blank=True, default='الاسم الأول')
    form_lname_placeholder_en = models.CharField(
        max_length=100, blank=True, default='Last Name')
    form_lname_placeholder_ar = models.CharField(
        max_length=100, blank=True, default='اسم العائلة')
    form_phone_placeholder_en = models.CharField(
        max_length=100, blank=True, default='Phone Number')
    form_phone_placeholder_ar = models.CharField(
        max_length=100, blank=True, default='رقم الهاتف')
    form_email_placeholder_en = models.CharField(
        max_length=100, blank=True, default='Email Address')
    form_email_placeholder_ar = models.CharField(
        max_length=100, blank=True, default='البريد الإلكتروني')
    form_message_placeholder_en = models.TextField(
        blank=True,
        default='Tell us about your transport business or requirements')
    form_message_placeholder_ar = models.TextField(
        blank=True, default='أخبرنا عن متطلباتك')
    form_consent_label_en = models.CharField(
        max_length=500, blank=True,
        default=(
            'I agree to receive communication regarding product updates and '
            'demo scheduling.'))
    form_consent_label_ar = models.CharField(
        max_length=500, blank=True, default='')
    form_submit_label_en = models.CharField(
        max_length=100, blank=True, default='Book Demo')
    form_submit_label_ar = models.CharField(
        max_length=100, blank=True, default='احجز عرضاً')
    form_action_url = models.CharField(
        max_length=500, blank=True, default='/contact/submit/')

    # ── Sidebar Info ──────────────────────────────────────────────
    sidebar_heading_en = models.CharField(
        max_length=300, blank=True,
        default='Start your digital transport journey with IRoad')
    sidebar_heading_ar = models.CharField(
        max_length=300, blank=True, default='')
    support_label_en = models.CharField(
        max_length=100, blank=True, default='Our Support')
    support_label_ar = models.CharField(
        max_length=100, blank=True, default='الدعم')
    support_hours_en = models.CharField(
        max_length=200, blank=True,
        default='Monday - Friday : 9:00 AM - 6:00 PM')
    support_hours_ar = models.CharField(
        max_length=200, blank=True, default='')
    support_online_label_en = models.CharField(
        max_length=200, blank=True,
        default='24/7 Email Support Available')
    support_online_label_ar = models.CharField(
        max_length=200, blank=True, default='')
    info_book_label_en = models.CharField(
        max_length=100, blank=True, default='Book a Demo')
    info_book_label_ar = models.CharField(
        max_length=100, blank=True, default='احجز عرضاً')
    info_phone_1 = models.CharField(
        max_length=50, blank=True, default='+91 98765 43210')
    info_phone_2 = models.CharField(
        max_length=50, blank=True, default='+91 91234 56789')
    info_email_label_en = models.CharField(
        max_length=100, blank=True, default='Email')
    info_email_label_ar = models.CharField(
        max_length=100, blank=True, default='البريد')
    info_email_1 = models.CharField(
        max_length=200, blank=True, default='support@iroad.com')
    info_email_2 = models.CharField(
        max_length=200, blank=True, default='sales@iroad.com')
    info_platform_label_en = models.CharField(
        max_length=200, blank=True,
        default='Cloud-Based Platform - Accessible Worldwide')
    info_platform_label_ar = models.CharField(
        max_length=200, blank=True, default='')

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200, blank=True, default='')

    class Meta:
        db_table = 'iroad_frontend_contact_content'
        verbose_name = 'Contact Page Content'
        verbose_name_plural = 'Contact Page Content'

    def __str__(self):
        return 'Contact Page Content'

    @classmethod
    def get_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


# ── Legal pages CMS (singletons) ────────────────────────────────────


def privacy_policy_upload_path(instance, filename):
    return f'marketing/legal/privacy/{filename}'


def terms_conditions_upload_path(instance, filename):
    return f'marketing/legal/terms/{filename}'


def mobile_about_us_upload_path(instance, filename):
    return f'marketing/legal/mobile-about-us/{filename}'


class PrivacyPolicyPageContent(models.Model):
    """
    Singleton CMS for the public Privacy Policy page.
    One record only — get_singleton() pattern.
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200,
        blank=True,
        default='Privacy Policy - IRoad',
    )
    page_title_ar = models.CharField(
        max_length=200,
        blank=True,
        default='سياسة الخصوصية - آيروود',
    )
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')

    # ── Page Header / Breadcrumb ──────────────────────────────────
    page_header_h1_en = models.CharField(
        max_length=300,
        blank=True,
        default='Privacy Policy',
    )
    page_header_h1_ar = models.CharField(
        max_length=300,
        blank=True,
        default='سياسة الخصوصية',
    )
    breadcrumb_current_en = models.CharField(
        max_length=100,
        blank=True,
        default='Privacy Policy',
    )
    breadcrumb_current_ar = models.CharField(
        max_length=100,
        blank=True,
        default='سياسة الخصوصية',
    )
    page_header_background = models.FileField(
        upload_to=privacy_policy_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
        verbose_name='Page header background image',
        help_text=(
            'Optional hero background for the privacy policy page header. '
            'If empty, a solid theme fallback is used.'
        ),
    )

    # ── Main body (rich text editor to be wired in superadmin later) ─
    content_en = models.TextField(blank=True, default='')
    content_ar = models.TextField(blank=True, default='')

    # ── Audit ─────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200,
        blank=True,
        default='',
    )

    class Meta:
        db_table = 'iroad_frontend_privacy_policy_content'
        verbose_name = 'Privacy Policy Page Content'
        verbose_name_plural = 'Privacy Policy Page Content'

    def __str__(self):
        return 'Privacy Policy Page Content'

    @classmethod
    def get_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class TermsConditionsPageContent(models.Model):
    """
    Singleton CMS for the public Terms & Conditions page.
    One record only — get_singleton() pattern.
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200,
        blank=True,
        default='Terms & Conditions - IRoad',
    )
    page_title_ar = models.CharField(
        max_length=200,
        blank=True,
        default='الشروط والأحكام - آيروود',
    )
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')

    # ── Page Header / Breadcrumb ──────────────────────────────────
    page_header_h1_en = models.CharField(
        max_length=300,
        blank=True,
        default='Terms & Conditions',
    )
    page_header_h1_ar = models.CharField(
        max_length=300,
        blank=True,
        default='الشروط والأحكام',
    )
    breadcrumb_current_en = models.CharField(
        max_length=100,
        blank=True,
        default='Terms & Conditions',
    )
    breadcrumb_current_ar = models.CharField(
        max_length=100,
        blank=True,
        default='الشروط والأحكام',
    )
    page_header_background = models.FileField(
        upload_to=terms_conditions_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
        verbose_name='Page header background image',
        help_text=(
            'Optional hero background for the terms page header. '
            'If empty, a solid theme fallback is used.'
        ),
    )

    # ── Main body (rich text editor to be wired in superadmin later) ─
    content_en = models.TextField(blank=True, default='')
    content_ar = models.TextField(blank=True, default='')

    # ── Audit ─────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200,
        blank=True,
        default='',
    )

    class Meta:
        db_table = 'iroad_frontend_terms_conditions_content'
        verbose_name = 'Terms & Conditions Page Content'
        verbose_name_plural = 'Terms & Conditions Page Content'

    def __str__(self):
        return 'Terms & Conditions Page Content'

    @classmethod
    def get_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class MobileAboutUsPageContent(models.Model):
    """
    Singleton CMS for the mobile app About Us page (not the marketing About page).

    Same field layout as Privacy / Terms legal singletons; managed under
    Website CMS → Legal Pages in superadmin.
    """

    # ── SEO ──────────────────────────────────────────────────────
    page_title_en = models.CharField(
        max_length=200,
        blank=True,
        default='About Us - IRoad',
    )
    page_title_ar = models.CharField(
        max_length=200,
        blank=True,
        default='من نحن - آيروود',
    )
    meta_description_en = models.TextField(blank=True, default='')
    meta_description_ar = models.TextField(blank=True, default='')

    # ── Page Header / Breadcrumb ──────────────────────────────────
    page_header_h1_en = models.CharField(
        max_length=300,
        blank=True,
        default='About Us',
    )
    page_header_h1_ar = models.CharField(
        max_length=300,
        blank=True,
        default='من نحن',
    )
    breadcrumb_current_en = models.CharField(
        max_length=100,
        blank=True,
        default='About Us',
    )
    breadcrumb_current_ar = models.CharField(
        max_length=100,
        blank=True,
        default='من نحن',
    )
    page_header_background = models.FileField(
        upload_to=mobile_about_us_upload_path,
        blank=True,
        null=True,
        validators=_CMS_UPLOAD_VALIDATORS,
        verbose_name='Page header background image',
        help_text=(
            'Optional hero background for the mobile About Us page header. '
            'If empty, a solid theme fallback is used.'
        ),
    )

    # ── Main body (rich text; TinyMCE in superadmin CMS template) ─
    content_en = models.TextField(blank=True, default='')
    content_ar = models.TextField(blank=True, default='')

    # ── Audit ─────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=200,
        blank=True,
        default='',
    )

    class Meta:
        db_table = 'iroad_frontend_mobile_about_us_content'
        verbose_name = 'Mobile About Us Page Content'
        verbose_name_plural = 'Mobile About Us Page Content'

    def __str__(self):
        return 'Mobile About Us Page Content'

    @classmethod
    def get_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class ContactSubmission(models.Model):
    """
    Stores demo request form submissions.
    Viewable from superadmin CMS.
    """
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    email = models.EmailField()
    message = models.TextField()
    consent_given = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(
        null=True, blank=True)

    class Meta:
        db_table = 'iroad_frontend_contact_submission'
        ordering = ['-submitted_at']
        verbose_name = 'Contact Submission'
        verbose_name_plural = 'Contact Submissions'

    def __str__(self):
        return f'{self.first_name} {self.last_name} — {self.email}'
