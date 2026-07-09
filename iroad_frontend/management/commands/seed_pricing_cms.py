"""
Seed Pricing Page CMS: singleton text, pricing interactive steps, pricing FAQs,
About page how-it-work steps (EN/AR), HomeServiceCard, HomePricingTier, and
HomeTestimonial rows used on the marketing site.

Idempotent for pricing FAQs (create-if-missing). Refreshes singleton, pricing
interactive steps, about how-work steps, service cards, pricing tiers, and
testimonials each run.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from iroad_frontend.management.commands.seed_about_cms import HOW_WORK_STEPS
from iroad_frontend.management.commands.seed_home_cms import (
    PRICING_TIERS,
    SERVICE_CARDS,
    TESTIMONIALS,
    TESTIMONIAL_QUOTE_AR,
    TESTIMONIAL_QUOTE_EN,
)
from iroad_frontend.models import (
    AboutHowWorkStep,
    AboutPageContent,
    HomePageContent,
    HomePricingTier,
    HomeServiceCard,
    HomeTestimonial,
    PricingFaqItem,
    PricingInteractiveStep,
    PricingPageContent,
)


def _pricing_singleton_text():
    return {
        'page_title_en': 'IRoute - SaaS Transport Management System Pricing Page',
        'page_title_ar': 'آيروت - صفحة أسعار نظام إدارة النقل SaaS',
        'meta_description_en': (
            'IRoute pricing plans for transport teams — Starter, Business, and '
            'Enterprise. Compare modules, trials, and support.'
        ),
        'meta_description_ar': (
            'خطط أسعار آيروت لفرق النقل — المبتدئ والأعمال والمؤسسات. قارن '
            'الوحدات والتجارب والدعم.'
        ),
        'page_header_h1_en': (
            'IRoute - SaaS Transport Management System Pricing Page'
        ),
        'page_header_h1_ar': 'صفحة أسعار آيروت - نظام إدارة النقل SaaS',
        'breadcrumb_current_en': 'Pricing plans',
        'breadcrumb_current_ar': 'خطط الأسعار',
        'pricing_kicker_en': 'Pricing Plans',
        'pricing_kicker_ar': 'خطط الأسعار',
        'pricing_heading_en': (
            'Flexible pricing designed for transport businesses of all sizes'
        ),
        'pricing_heading_ar': (
            'أسعار مرنة مصممة لشركات النقل بجميع الأحجام'
        ),
        'interactive_kicker_en': 'How it works',
        'interactive_kicker_ar': 'كيف يعمل',
        'interactive_heading_en': 'Streamline your transport workflows',
        'interactive_heading_ar': 'بسّط سير عمل النقل لديك',
        'partner_kicker_en': 'Trusted by Transport Businesses Across Regions',
        'partner_kicker_ar': 'موثوق به من شركات النقل عبر المناطق',
        'partner_heading_en': 'Trusted by Transport Businesses Across Regions',
        'partner_heading_ar': 'موثوق به من شركات النقل عبر المناطق',
        'partner_body_en': (
            'IRoute helps logistics companies digitize operations and scale '
            'efficiently.'
        ),
        'partner_body_ar': (
            'تساعد آيروت شركات اللوجستيات على رقمنة العمليات والتوسع بكفاءة.'
        ),
        'partner_cta_label_en': 'Book a Demo',
        'partner_cta_label_ar': 'احجز عرضاً',
        'partner_cta_url': '/contact/',
        'partner_email_label_en': 'Email',
        'partner_email_label_ar': 'البريد الإلكتروني',
        'partner_email_value': 'support@iroute.com',
        'partner_platform_label_en': 'Cloud-Based Platform (Accessible Anywhere)',
        'partner_platform_label_ar': 'منصة سحابية (متاحة من أي مكان)',
        'counter_1_value': '24/7',
        'counter_1_label_en': 'Support',
        'counter_1_label_ar': 'دعم',
        'counter_2_value': '10K+',
        'counter_2_label_en': 'Global Freight',
        'counter_2_label_ar': 'شحن عالمي',
        'counter_3_value': '100+',
        'counter_3_label_en': 'Countries',
        'counter_3_label_ar': 'دولة',
        'counter_4_value': '99.9%',
        'counter_4_label_en': 'Uptime',
        'counter_4_label_ar': 'وقت التشغيل',
        'counter_5_value': '10+',
        'counter_5_label_en': 'Partners',
        'counter_5_label_ar': 'شريك',
        'testimonials_kicker_en': 'Our Testimonials',
        'testimonials_kicker_ar': 'آراء عملائنا',
        'testimonials_heading_en': 'What transport teams say about IRoute',
        'testimonials_heading_ar': 'ماذا يقول فرق النقل عن آيروت',
        'faq_kicker_en': 'FAQs',
        'faq_kicker_ar': 'الأسئلة الشائعة',
        'faq_heading_en': 'Answers to common questions about IRoute',
        'faq_heading_ar': 'إجابات عن أسئلة شائعة حول آيروت',
        'faq_intro_en': (
            'Find clear, detailed answers about IRoute TMS, plans, modules, '
            'support, and data security.'
        ),
        'faq_intro_ar': (
            'اعثر على إجابات واضحة ومفصلة عن نظام آيروت لإدارة النقل والخطط '
            'والوحدات والدعم وأمان البيانات.'
        ),
        'faq_view_all_label_en': 'View all FAQs',
        'faq_view_all_label_ar': 'عرض كل الأسئلة الشائعة',
        'faq_view_all_url': '/faqs/',
        'updated_by': 'seed_pricing_cms',
    }


INTERACTIVE_STEPS = [
    {
        'order': 0,
        'title_en': 'Smart Workflow Automation',
        'title_ar': 'أتمتة ذكية لسير العمل',
        'subtitle_en': '',
        'subtitle_ar': '',
        'body_en': 'Automate order, booking, and shipment processes',
        'body_ar': 'أتمتة عمليات الطلب والحجز والشحن',
        'detail_url': '#',
    },
    {
        'order': 1,
        'title_en': 'Real-Time Dashboard',
        'title_ar': 'لوحة تحكم لحظية',
        'subtitle_en': '',
        'subtitle_ar': '',
        'body_en': (
            'Get live insights on operations, fleet, and performance'
        ),
        'body_ar': (
            'احصل على رؤى حية للعمليات والأسطول والأداء'
        ),
        'detail_url': '#',
    },
    {
        'order': 2,
        'title_en': 'Scalable SaaS Platform',
        'title_ar': 'منصة SaaS قابلة للتوسع',
        'subtitle_en': '',
        'subtitle_ar': '',
        'body_en': 'Grow your business with flexible and scalable system',
        'body_ar': 'نمّ عملك بنظام مرن وقابل للتوسع',
        'detail_url': '#',
    },
    {
        'order': 3,
        'title_en': '24/7 Platform Access',
        'title_ar': 'وصول للمنصة على مدار الساعة',
        'subtitle_en': '',
        'subtitle_ar': '',
        'body_en': 'Access your system anytime, anywhere',
        'body_ar': 'الوصول إلى نظامك في أي وقت ومن أي مكان',
        'detail_url': '#',
    },
]


PRICING_FAQS = [
    {
        'order': 1,
        'question_en': 'What plans does IRoute offer?',
        'question_ar': 'ما الخطط التي يقدمها آيروت؟',
        'answer_en': (
            'IRoute offers Starter, Business, and Enterprise plans to fit teams '
            'of all sizes.'
        ),
        'answer_ar': (
            'يقدم آيروت خطط المبتدئ والأعمال والمؤسسات لتناسب فرق العمل '
            'بجميع الأحجام.'
        ),
    },
    {
        'order': 2,
        'question_en': 'Is there a free trial?',
        'question_ar': 'هل توجد تجربة مجانية؟',
        'answer_en': (
            'Yes — all plans come with a 30-day free trial, no credit card '
            'required.'
        ),
        'answer_ar': (
            'نعم — جميع الخطط تشمل تجربة مجانية لمدة 30 يوماً دون الحاجة '
            'لبطاقة ائتمان.'
        ),
    },
    {
        'order': 3,
        'question_en': 'Can I change my plan later?',
        'question_ar': 'هل يمكنني تغيير خطتي لاحقاً؟',
        'answer_en': (
            'Yes, you can upgrade or downgrade at any time from your account '
            'settings.'
        ),
        'answer_ar': (
            'نعم، يمكنك الترقية أو التخفيض في أي وقت من إعدادات حسابك.'
        ),
    },
    {
        'order': 4,
        'question_en': 'Are there any hidden fees?',
        'question_ar': 'هل توجد رسوم مخفية؟',
        'answer_en': (
            'No. The price you see is the price you pay — no setup fees or '
            'hidden charges.'
        ),
        'answer_ar': (
            'لا. السعر الذي تراه هو ما تدفعه — دون رسوم إعداد أو تكاليف '
            'مخفية.'
        ),
    },
    {
        'order': 5,
        'question_en': 'How does billing work?',
        'question_ar': 'كيف يعمل الفوترة؟',
        'answer_en': (
            'Plans are billed monthly. Annual billing with a discount is '
            'available on request.'
        ),
        'answer_ar': (
            'الخطط تُفوتر شهرياً. يتوفر الفوترة السنوية بخصم عند الطلب.'
        ),
    },
    {
        'order': 6,
        'question_en': 'Can I cancel anytime?',
        'question_ar': 'هل يمكنني الإلغاء في أي وقت؟',
        'answer_en': (
            'Yes — you can cancel your subscription at any time with no '
            'cancellation fees.'
        ),
        'answer_ar': (
            'نعم — يمكنك إلغاء اشتراكك في أي وقت دون رسوم إلغاء.'
        ),
    },
]


class Command(BaseCommand):
    help = (
        'Seed PricingPageContent, pricing interactive steps, PricingFaqItem, '
        'AboutHowWorkStep (bilingual), HomeServiceCard, HomePricingTier, and '
        'HomeTestimonial on shared CMS records.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        pricing = PricingPageContent.get_singleton()
        data = _pricing_singleton_text()
        for key, val in data.items():
            setattr(pricing, key, val)
        pricing.save()

        for spec in INTERACTIVE_STEPS:
            order = spec['order']
            PricingInteractiveStep.objects.update_or_create(
                pricing=pricing,
                order=order,
                defaults={
                    'title_en': spec['title_en'],
                    'title_ar': spec.get('title_ar', ''),
                    'subtitle_en': spec.get('subtitle_en', ''),
                    'subtitle_ar': spec.get('subtitle_ar', ''),
                    'body_en': spec['body_en'],
                    'body_ar': spec.get('body_ar', ''),
                    'detail_url': spec.get('detail_url', '#'),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'PricingInteractiveStep order={order} '
                    f'({spec["title_en"]}): upserted.'
                )
            )

        about = AboutPageContent.get_singleton()
        for row in HOW_WORK_STEPS:
            order = row['order']
            AboutHowWorkStep.objects.update_or_create(
                about=about,
                order=order,
                defaults={
                    'step_number': row['step_number'],
                    'title_en': row['title_en'],
                    'title_ar': row.get('title_ar', ''),
                    'body_en': row['body_en'],
                    'body_ar': row.get('body_ar', ''),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'AboutHowWorkStep order={order} ({row["title_en"]}): upserted.'
                )
            )

        for faq_data in PRICING_FAQS:
            order = faq_data['order']
            exists = PricingFaqItem.objects.filter(
                pricing=pricing,
                order=order,
            ).exists()
            if not exists:
                PricingFaqItem.objects.create(
                    pricing=pricing,
                    question_en=faq_data['question_en'],
                    question_ar=faq_data.get('question_ar', ''),
                    answer_en=faq_data['answer_en'],
                    answer_ar=faq_data.get('answer_ar', ''),
                    order=order,
                    is_active=True,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Pricing FAQ created: {faq_data["question_en"]}'
                    )
                )
            else:
                self.stdout.write(
                    f'Skipped (exists): {faq_data["question_en"]}'
                )

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
                    f'HomeServiceCard order={order} ({row["title_en"]}): upserted.'
                )
            )

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
                    f'HomePricingTier order={order} ({row["name_en"]}): upserted.'
                )
            )

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
                    f'HomeTestimonial order={order} ({row["author_name_en"]}): '
                    'upserted.'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                'Pricing CMS seeded (singleton + pricing interactive steps + '
                'about how-work steps + FAQs + service cards + pricing tiers + '
                'testimonials EN/AR).'
            )
        )
