"""
Seed default Home Page CMS content (singleton + repeaters) from designer index.
Idempotent: most repeaters skip if already present; service cards, pricing
tiers, pricing benefits, and testimonials are upserted each run so EN/AR copy
stays in sync with seed data.
Always refreshes HomePageContent text fields (not images) to designer defaults
with matching Arabic (_ar) copy alongside English.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from iroad_frontend.models import (
    HomeMapLocation,
    HomePageContent,
    HomePricingBenefit,
    HomePricingTier,
    HomeServiceCard,
    HomeTestimonial,
)

# Designer index.html — bilingual EN/AR seed copy.
TESTIMONIAL_QUOTE_EN = (
    'Their logistics solutions transformed our supply chain. On-time delivery '
    'and real-time tracking have made our operations seamless reliable, '
    'efficient, and professional service every time.'
)
TESTIMONIAL_QUOTE_AR = (
    'لقد غيّرت حلولهم اللوجستية سلسلة التوريد لدينا. التسليم في الموعد '
    'والتتبع اللحظي جعلا عملياتنا سلسة وموثوقة وفعّالة مع خدمة احترافية في كل مرة.'
)


def _home_text_defaults():
    """Char/Text fields only; images use static fallbacks until uploaded in CMS."""
    return {
        'page_title_en': 'IRoute - Transport Management System',
        'page_title_ar': 'آيروت - نظام إدارة النقل',
        'meta_description_en': (
            'IRoute is an all-in-one transport management system for modern '
            'logistics companies — manage operations, fleet, and finances in one '
            'powerful SaaS platform.'
        ),
        'meta_description_ar': (
            'آيروت منصة شاملة لإدارة النقل لشركات اللوجستيات الحديثة — أدِر العمليات '
            'والأسطول والمالية في منصة SaaS واحدة قوية.'
        ),
        'logo_alt_en': 'Logo',
        'logo_alt_ar': 'آيروت',
        'nav_home_en': 'Home',
        'nav_home_ar': 'الرئيسية',
        'nav_about_en': 'About',
        'nav_about_ar': 'عن الشركة',
        'nav_pricing_en': 'Pricing',
        'nav_pricing_ar': 'الأسعار',
        'nav_contact_en': 'Contact',
        'nav_contact_ar': 'اتصل بنا',
        'header_cta_small_title_en': 'Book a Demo',
        'header_cta_small_title_ar': 'احجز عرضاً',
        'header_cta_title_en': 'Book a Demo',
        'header_cta_title_ar': 'احجز عرضاً',
        'header_cta_url': '/contact/',
        'header_sign_in_en': 'Sign In',
        'header_sign_in_ar': 'تسجيل الدخول',
        'header_sign_in_url': '/login/',
        'hero_kicker_en': 'Welcome to IRoute',
        'hero_kicker_ar': 'مرحباً بك في آيروت',
        'hero_heading_en': (
            'All-in-One Transport Management System for Modern Logistics Companies'
        ),
        'hero_heading_ar': (
            'نظام إدارة نقل شامل لشركات اللوجستيات الحديثة'
        ),
        'hero_subheading_en': (
            'Manage your operations, fleet, and finances in one powerful SaaS platform.'
        ),
        'hero_subheading_ar': (
            'أدِر عملياتك وأسطولك وماليتك في منصة SaaS واحدة قوية.'
        ),
        'hero_cta_label_en': 'Start Free Trial',
        'hero_cta_label_ar': 'ابدأ مجاناً',
        'hero_cta_url': '/contact/',
        'hero_bullet_1_en': 'End-to-End Transport Workflow',
        'hero_bullet_1_ar': 'سير عمل نقل من البداية للنهاية',
        'hero_bullet_2_en': 'Real-Time Operations Visibility',
        'hero_bullet_2_ar': 'رؤية لحظية للعمليات',
        'hero_bullet_3_en': 'Integrated Finance & Reporting',
        'hero_bullet_3_ar': 'مالية وتقارير متكاملة',
        'about_kicker_en': 'About IRoute',
        'about_kicker_ar': 'عن آيروت',
        'about_heading_en': 'A Complete Transport Management System Built for Efficiency',
        'about_heading_ar': 'نظام إدارة نقل متكامل مبني من أجل الكفاءة',
        'about_body_en': (
            'IRoute is a powerful SaaS platform designed to help transport companies '
            'manage operations, fleet, finance, and delivery workflows from a single system.'
        ),
        'about_body_ar': (
            'آيروت منصة SaaS قوية تساعد شركات النقل على إدارة العمليات والأسطول '
            'والمالية وسير عمل التسليم من نظام واحد.'
        ),
        'about_point_1_title_en': 'Centralized Operations Control',
        'about_point_1_title_ar': 'تحكم مركزي بالعمليات',
        'about_point_1_body_en': (
            'Manage transport orders, bookings, and execution with complete control.'
        ),
        'about_point_1_body_ar': (
            'أدِر طلبات النقل والحجوزين والتنفيذ بتحكم كامل.'
        ),
        'about_point_2_title_en': 'Role-Based Access (RBAC)',
        'about_point_2_title_ar': 'صلاحيات حسب الدور (RBAC)',
        'about_point_2_body_en': (
            'Securely manage permissions across teams with role-based workflows.'
        ),
        'about_point_2_body_ar': (
            'أدِر الصلاحيات بين الفرق بأمان عبر سير عمل يعتمد على الأدوار.'
        ),
        'about_experience_number': '25',
        'about_experience_suffix_en': '+',
        'about_experience_suffix_ar': '+',
        'about_experience_caption_en': 'Built for Modern Logistics Teams',
        'about_experience_caption_ar': 'مصمم لفرق اللوجستيات الحديثة',
        'about_cta_label_en': 'More About Us',
        'about_cta_label_ar': 'المزيد عنا',
        'about_cta_url': '/about/',
        'services_kicker_en': 'Core Features',
        'services_kicker_ar': 'الميزات الأساسية',
        'services_heading_en': (
            'Everything you need to control transport operations in one place'
        ),
        'services_heading_ar': (
            'كل ما تحتاجه للتحكم بعمليات النقل في مكان واحد'
        ),
        'services_footer_text_en': "Let's build something great together.",
        'services_footer_text_ar': 'لنصنع شيئاً رائعاً معاً.',
        'services_footer_link_label_en': 'Start Free Trial',
        'services_footer_link_label_ar': 'ابدأ مجاناً',
        'services_footer_link_url': '/contact/',
        'why_kicker_en': 'Why Choose IRoute',
        'why_kicker_ar': 'لماذا آيروت',
        'why_heading_en': 'Full control, automation, and real-time visibility',
        'why_heading_ar': 'تحكم كامل وأتمتة ورؤية لحظية',
        'why_point_1_title_en': 'Full Operational Control',
        'why_point_1_title_ar': 'تحكم تشغيلي كامل',
        'why_point_1_body_en': (
            'Manage roles, permissions, and workflows with complete control.'
        ),
        'why_point_1_body_ar': (
            'أدِر الأدوار والصلاحيات وسير العمل بتحكم كامل.'
        ),
        'why_point_2_title_en': 'Smart Workflow Automation',
        'why_point_2_title_ar': 'أتمتة ذكية لسير العمل',
        'why_point_2_body_en': 'Streamline booking, shipment, and delivery processes.',
        'why_point_2_body_ar': 'بسّط الحجز والشحن والتسليم.',
        'why_point_3_title_en': 'Integrated Finance',
        'why_point_3_title_ar': 'مالية متكاملة',
        'why_point_3_body_en': (
            'Handle invoices, payments, and adjustments in one place.'
        ),
        'why_point_3_body_ar': (
            'تعامل مع الفواتير والمدفوعات والتسويات في مكان واحد.'
        ),
        'features_kicker_en': 'Advanced Capabilities',
        'features_kicker_ar': 'قدرات متقدمة',
        'features_heading_en': 'Advanced tools built for control and visibility',
        'features_heading_ar': 'أدوات متقدمة للتحكم والرؤية',
        'features_footer_text_en': 'Transform how your team operates with IRoute SaaS.',
        'features_footer_text_ar': 'حوّل طريقة عمل فريقك مع آيروت SaaS.',
        'features_footer_link_label_en': 'Start Free Trial',
        'features_footer_link_label_ar': 'ابدأ مجاناً',
        'features_footer_link_url': '/contact/',
        'features_rating_value': '4.9/5',
        'features_review_count_label_en': '4,200+ reviews',
        'features_review_count_label_ar': '+4,200 تقييم',
        'feature_a_title_en': 'Real-Time Dashboard Insights',
        'feature_a_title_ar': 'رؤى لوحة تحكم لحظية',
        'feature_a_body_en': (
            'Get live operational insights across orders, bookings, and shipments.'
        ),
        'feature_a_body_ar': (
            'احصل على رؤى تشغيلية حية للطلبات والحجوزين والشحنات.'
        ),
        'feature_b_title_en': 'Shipment Lifecycle Tracking',
        'feature_b_title_ar': 'تتبع دورة حياة الشحنة',
        'feature_b_body_en': (
            'Track every stage and capture Proof of Delivery (POD) in one flow.'
        ),
        'feature_b_body_ar': (
            'تتبع كل مرحلة واعتماد إثبات التسليم (POD) في تدفق واحد.'
        ),
        'feature_b_list_item_1_en': 'Orders',
        'feature_b_list_item_1_ar': 'الطلبات',
        'feature_b_list_item_2_en': 'POD',
        'feature_b_list_item_2_ar': 'إثبات التسليم',
        'feature_c_title_en': 'Multi-Currency Support',
        'feature_c_title_ar': 'دعم متعدد العملات',
        'feature_c_body_en': (
            'Run invoicing and payments with automated currency conversions.'
        ),
        'feature_c_body_ar': (
            'شغّل الفوترة والمدفوعات مع تحويلات عملات تلقائية.'
        ),
        'feature_d_title_en': 'Vendor & Client Management',
        'feature_d_title_ar': 'إدارة الموردين والعملاء',
        'feature_d_body_en': (
            'Centralize vendors and client records for faster coordination.'
        ),
        'feature_d_body_ar': (
            'مركز سجلات الموردين والعملاء لتنسيق أسرع.'
        ),
        'feature_d_list_item_1_en': 'Vendors',
        'feature_d_list_item_1_ar': 'الموردون',
        'feature_d_list_item_2_en': 'Clients',
        'feature_d_list_item_2_ar': 'العملاء',
        'pricing_kicker_en': 'Pricing Plans',
        'pricing_kicker_ar': 'خطط الأسعار',
        'pricing_heading_en': 'Pricing that scales with your transport team',
        'pricing_heading_ar': 'أسعار تنمو مع فريق النقل لديك',
        'business_counter_value': '200',
        'business_counter_suffix_en': '+',
        'business_counter_suffix_ar': '+',
        'business_counter_caption_en': (
            'Helping logistics businesses digitize and scale operations globally.'
        ),
        'business_counter_caption_ar': (
            'نساعد أعمال اللوجستيات على الرقمنة وتوسيع العمليات عالمياً.'
        ),
        'business_heading_en': 'Used by Transport Companies Across Regions',
        'business_heading_ar': 'يستخدمه شركات نقل عبر المناطق',
        'business_body_en': (
            'Helping logistics businesses digitize and scale operations globally.'
        ),
        'business_body_ar': (
            'نساعد أعمال اللوجستيات على الرقمنة وتوسيع العمليات عالمياً.'
        ),
        'business_bullet_1_en': 'Digitization',
        'business_bullet_1_ar': 'الرقمنة',
        'business_bullet_2_en': 'Scalability',
        'business_bullet_2_ar': 'قابلية التوسع',
        'testimonials_kicker_en': 'Our Testimonials',
        'testimonials_kicker_ar': 'آراء عملائنا',
        'testimonials_heading_en': 'What transport teams say about IRoute',
        'testimonials_heading_ar': 'ماذا يقول فرق النقل عن آيروت',
        'testimonials_happy_count': '10k',
        'testimonials_happy_label_en': 'Trusted by World Customer',
        'testimonials_happy_label_ar': 'موثوق به من عملاء حول العالم',
        'footer_cta_left_en': "Let's Connect",
        'footer_cta_left_ar': 'لنتواصل',
        'footer_brand_text_en': 'IRoute',
        'footer_brand_text_ar': 'آيروت',
        'footer_cta_right_en': 'Book a Demo',
        'footer_cta_right_ar': 'احجز عرضاً',
        'footer_about_blurb_en': (
            'IRoute is a modern SaaS platform for transport companies to manage '
            'operations, fleet, and finance efficiently.'
        ),
        'footer_about_blurb_ar': (
            'آيروت منصة SaaS حديثة لشركات النقل لإدارة العمليات والأسطول '
            'والمالية بكفاءة.'
        ),
        'footer_social_pinterest_url': '#',
        'footer_social_x_url': '#',
        'footer_social_facebook_url': '#',
        'footer_social_instagram_url': '#',
        'footer_column_title_en': 'Features',
        'footer_column_title_ar': 'الميزات',
        'footer_link_1_label_en': 'About',
        'footer_link_1_label_ar': 'عن الشركة',
        'footer_link_1_url': '/about/',
        'footer_link_2_label_en': 'Pricing',
        'footer_link_2_label_ar': 'الأسعار',
        'footer_link_2_url': '/pricing/',
        'footer_link_3_label_en': 'Contact',
        'footer_link_3_label_ar': 'اتصل بنا',
        'footer_link_3_url': '/contact/',
        'footer_newsletter_title_en': 'Get Product Updates',
        'footer_newsletter_title_ar': 'احصل على تحديثات المنتج',
        'footer_newsletter_desc_en': (
            'Get IRoute product news, releases, and feature updates.'
        ),
        'footer_newsletter_desc_ar': (
            'أخبار منتج آيروت والإصدارات وتحديثات الميزات.'
        ),
        'footer_newsletter_placeholder_en': 'Enter your email',
        'footer_newsletter_placeholder_ar': 'أدخل بريدك الإلكتروني',
        'footer_newsletter_action_url': '#',
        'footer_copyright_en': 'Copyright © 2026 All Rights Reserved.',
        'footer_copyright_ar': '© 2026 جميع الحقوق محفوظة.',
        'footer_credit_en': 'Design & Developed by Redspark Technologies',
        'footer_credit_ar': 'التصميم والتطوير بواسطة Redspark Technologies',
        'updated_by': 'seed_home_cms',
    }


SERVICE_CARDS = [
    {
        'order': 0,
        'title_en': 'Order & Booking Management',
        'title_ar': 'إدارة الطلبات والحجز',
        'summary_en': (
            'Manage transport orders, bookings, and execution with complete control.'
        ),
        'summary_ar': (
            'أدِر طلبات النقل والحجوزين والتنفيذ بتحكم كامل.'
        ),
        'detail_url': '#',
        'cta_label_en': 'Explore Feature',
        'cta_label_ar': 'استكشف الميزة',
    },
    {
        'order': 1,
        'title_en': 'Fleet & Driver Management',
        'title_ar': 'إدارة الأسطول والسائقين',
        'summary_en': (
            'Manage fleet availability, drivers, and assignments with real-time '
            'scheduling.'
        ),
        'summary_ar': (
            'أدِر توفر المركبات والسائقين والتعيينات مع جدولة لحظية.'
        ),
        'detail_url': '#',
        'cta_label_en': 'Explore Feature',
        'cta_label_ar': 'استكشف الميزة',
    },
    {
        'order': 2,
        'title_en': 'Shipment Tracking & POD',
        'title_ar': 'تتبع الشحنات وإثبات التسليم',
        'summary_en': (
            'Track shipments end-to-end and capture Proof of Delivery (POD) in one '
            'workflow.'
        ),
        'summary_ar': (
            'تتبع الشحنات من البداية للنهاية واعتماد إثبات التسليم في سير عمل واحد.'
        ),
        'detail_url': '#',
        'cta_label_en': 'Explore Feature',
        'cta_label_ar': 'استكشف الميزة',
    },
    {
        'order': 3,
        'title_en': 'Finance & Invoicing',
        'title_ar': 'المالية والفوترة',
        'summary_en': (
            'Automate invoices, payments, and adjustments with integrated finance tools.'
        ),
        'summary_ar': (
            'أتمتة الفواتير والمدفوعات والتسويات بأدوات مالية متكاملة.'
        ),
        'detail_url': '#',
        'cta_label_en': 'Explore Feature',
        'cta_label_ar': 'استكشف الميزة',
    },
]

PRICING_BENEFITS = [
    {
        'order': 0,
        'text_en': 'Get a 30-day free trial',
        'text_ar': 'احصل على تجربة مجانية لمدة 30 يوماً',
    },
    {
        'order': 1,
        'text_en': 'No hidden fees',
        'text_ar': 'بدون رسوم خفية',
    },
    {
        'order': 2,
        'text_en': 'You can cancel anytime',
        'text_ar': 'يمكنك الإلغاء في أي وقت',
    },
]

PRICING_TIERS = [
    {
        'order': 0,
        'name_en': 'Starter',
        'name_ar': 'المبتدئ',
        'summary_en': (
            'Basic modules with essential tools for small transport teams.'
        ),
        'summary_ar': (
            'وحدات أساسية مع أدوات ضرورية لفرق النقل الصغيرة.'
        ),
        'price_display_en': '$19<sub>/month</sub>',
        'price_display_ar': '19$<sub>/شهر</sub>',
        'bullet_1_en': 'Basic modules',
        'bullet_1_ar': 'وحدات أساسية',
        'bullet_2_en': 'Limited users',
        'bullet_2_ar': 'مستخدمون محدودون',
        'bullet_3_en': 'Order and booking management',
        'bullet_3_ar': 'إدارة الطلب والحجز',
        'bullet_4_en': 'Standard support',
        'bullet_4_ar': 'دعم قياسي',
        'cta_label_en': 'Start Free Trial',
        'cta_label_ar': 'ابدأ مجاناً',
        'cta_url': '/contact/',
        'is_featured': False,
    },
    {
        'order': 1,
        'name_en': 'Business',
        'name_ar': 'الأعمال',
        'summary_en': (
            'Complete access for growing transport operations with analytics.'
        ),
        'summary_ar': (
            'وصول كامل لعمليات النقل النامية مع التحليلات.'
        ),
        'price_display_en': '$29<sub>/month</sub>',
        'price_display_ar': '29$<sub>/شهر</sub>',
        'bullet_1_en': 'Full system access',
        'bullet_1_ar': 'وصول كامل للنظام',
        'bullet_2_en': 'Reports and analytics',
        'bullet_2_ar': 'التقارير والتحليلات',
        'bullet_3_en': 'Fleet and driver management',
        'bullet_3_ar': 'إدارة الأسطول والسائقين',
        'bullet_4_en': 'Priority support',
        'bullet_4_ar': 'دعم ذو أولوية',
        'cta_label_en': 'Start Free Trial',
        'cta_label_ar': 'ابدأ مجاناً',
        'cta_url': '/contact/',
        'is_featured': True,
    },
    {
        'order': 2,
        'name_en': 'Enterprise',
        'name_ar': 'المؤسسات',
        'summary_en': (
            'Advanced setup for large-scale operations with tailored controls.'
        ),
        'summary_ar': (
            'إعداد متقدم للعمليات واسعة النطاق مع ضوابط مخصصة.'
        ),
        'price_display_en': '$39<sub>/month</sub>',
        'price_display_ar': '39$<sub>/شهر</sub>',
        'bullet_1_en': 'Custom workflows',
        'bullet_1_ar': 'سير عمل مخصص',
        'bullet_2_en': 'Dedicated support',
        'bullet_2_ar': 'دعم مخصص',
        'bullet_3_en': 'Advanced integrations',
        'bullet_3_ar': 'تكاملات متقدمة',
        'bullet_4_en': 'Enhanced security controls',
        'bullet_4_ar': 'ضوابط أمان معززة',
        'cta_label_en': 'Start Free Trial',
        'cta_label_ar': 'ابدأ مجاناً',
        'cta_url': '/contact/',
        'is_featured': False,
    },
]

TESTIMONIALS = [
    {
        'order': 0,
        'author_name_en': 'Darlene Robertson',
        'author_name_ar': 'دارلين روبرتسون',
        'author_role_en': 'Global Trade Inc.',
        'author_role_ar': 'شركة التجارة العالمية',
    },
    {
        'order': 1,
        'author_name_en': 'Leslie Alexander',
        'author_name_ar': 'ليزلي ألكسندر',
        'author_role_en': 'CEO, Tech Startup',
        'author_role_ar': 'الرئيس التنفيذي، شركة تقنية ناشئة',
    },
    {
        'order': 2,
        'author_name_en': 'Courtney Henry',
        'author_name_ar': 'كورتني هنري',
        'author_role_en': 'Fleet Supervisor',
        'author_role_ar': 'مشرف أسطول',
    },
]

MAP_LOCATIONS = [
    {
        'order': 0,
        'title_en': 'Saudi Arabia',
        'title_ar': 'المملكة العربية السعودية',
        'subtitle_en': 'Major hub for North America',
        'subtitle_ar': 'مركز لوجستي رئيسي',
    },
    {
        'order': 1,
        'title_en': 'UAE',
        'title_ar': 'الإمارات العربية المتحدة',
        'subtitle_en': 'Regional logistics hub',
        'subtitle_ar': 'مركز لوجستي إقليمي',
    },
    {
        'order': 2,
        'title_en': 'Kuwait',
        'title_ar': 'الكويت',
        'subtitle_en': 'Regional logistics hub',
        'subtitle_ar': 'مركز لوجستي إقليمي',
    },
    {
        'order': 3,
        'title_en': 'Qatar',
        'title_ar': 'قطر',
        'subtitle_en': 'Regional logistics hub',
        'subtitle_ar': 'مركز لوجستي إقليمي',
    },
]


class Command(BaseCommand):
    help = 'Seed default home page CMS content (idempotent for repeaters).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding home page CMS...'))
        try:
            with transaction.atomic():
                self._seed_home_page()
                self._seed_service_cards()
                self._seed_pricing_tiers()
                self._seed_pricing_benefits()
                self._seed_testimonials()
                self._seed_map_locations()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Seed failed: {exc}'))
            raise
        self.stdout.write(self.style.SUCCESS('Done.'))

    def _seed_home_page(self):
        home = HomePageContent.get_singleton()
        data = _home_text_defaults()
        for key, value in data.items():
            setattr(home, key, value)
        home.save()
        self.stdout.write(self.style.SUCCESS('  HomePageContent (pk=1): updated text fields.'))

    def _seed_service_cards(self):
        home = HomePageContent.get_singleton()
        for row in SERVICE_CARDS:
            order = row['order']
            HomeServiceCard.objects.update_or_create(
                home=home,
                order=order,
                defaults={
                    'title_en': row['title_en'],
                    'title_ar': row.get('title_ar', ''),
                    'summary_en': row['summary_en'],
                    'summary_ar': row.get('summary_ar', ''),
                    'detail_url': row['detail_url'],
                    'cta_label_en': row['cta_label_en'],
                    'cta_label_ar': row.get('cta_label_ar', 'استكشف الميزة'),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  HomeServiceCard order={order} ({row["title_en"]}): upserted.'
                )
            )

    def _seed_pricing_tiers(self):
        home = HomePageContent.get_singleton()
        for row in PRICING_TIERS:
            order = row['order']
            HomePricingTier.objects.update_or_create(
                home=home,
                order=order,
                defaults={
                    'name_en': row['name_en'],
                    'name_ar': row.get('name_ar', ''),
                    'summary_en': row['summary_en'],
                    'summary_ar': row.get('summary_ar', ''),
                    'price_display_en': row['price_display_en'],
                    'price_display_ar': row.get('price_display_ar', ''),
                    'bullet_1_en': row.get('bullet_1_en', ''),
                    'bullet_1_ar': row.get('bullet_1_ar', ''),
                    'bullet_2_en': row.get('bullet_2_en', ''),
                    'bullet_2_ar': row.get('bullet_2_ar', ''),
                    'bullet_3_en': row.get('bullet_3_en', ''),
                    'bullet_3_ar': row.get('bullet_3_ar', ''),
                    'bullet_4_en': row.get('bullet_4_en', ''),
                    'bullet_4_ar': row.get('bullet_4_ar', ''),
                    'cta_label_en': row['cta_label_en'],
                    'cta_label_ar': row.get('cta_label_ar', 'ابدأ مجاناً'),
                    'cta_url': row['cta_url'],
                    'is_featured': row.get('is_featured', False),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  HomePricingTier order={order} ({row["name_en"]}): upserted.'
                )
            )

    def _seed_pricing_benefits(self):
        home = HomePageContent.get_singleton()
        for row in PRICING_BENEFITS:
            order = row['order']
            HomePricingBenefit.objects.update_or_create(
                home=home,
                order=order,
                defaults={
                    'text_en': row['text_en'],
                    'text_ar': row.get('text_ar', ''),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  HomePricingBenefit order={order}: upserted.'
                )
            )

    def _seed_testimonials(self):
        home = HomePageContent.get_singleton()
        for row in TESTIMONIALS:
            order = row['order']
            HomeTestimonial.objects.update_or_create(
                home=home,
                order=order,
                defaults={
                    'quote_en': TESTIMONIAL_QUOTE_EN,
                    'quote_ar': TESTIMONIAL_QUOTE_AR,
                    'author_name_en': row['author_name_en'],
                    'author_name_ar': row.get('author_name_ar', ''),
                    'author_role_en': row['author_role_en'],
                    'author_role_ar': row.get('author_role_ar', ''),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  HomeTestimonial order={order} ({row["author_name_en"]}): '
                    'upserted.'
                )
            )

    def _seed_map_locations(self):
        home = HomePageContent.get_singleton()
        for row in MAP_LOCATIONS:
            order = row['order']
            if HomeMapLocation.objects.filter(home=home, order=order).exists():
                self.stdout.write(
                    f'  HomeMapLocation order={order}: already exists, skipped.'
                )
                continue
            HomeMapLocation.objects.create(
                home=home,
                order=order,
                title_en=row['title_en'],
                title_ar=row.get('title_ar', ''),
                subtitle_en=row['subtitle_en'],
                subtitle_ar=row.get('subtitle_ar', ''),
                is_active=True,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  HomeMapLocation order={order} ({row["title_en"]}): created.'
                )
            )
