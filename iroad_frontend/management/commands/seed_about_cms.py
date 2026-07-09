"""
Seed default About Page CMS (singleton + repeaters) from designer about.html.
Idempotent: approach pillars, how-work steps, and FAQ items are upserted each
run so EN/AR stays in sync. Always refreshes AboutPageContent text fields.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from iroad_frontend.models import (
    AboutApproachPillar,
    AboutFaqItem,
    AboutHowWorkStep,
    AboutPageContent,
)


def _about_singleton_text():
    return {
        'page_title_en': (
            'About IRoute - Transport Management SaaS Platform'
        ),
        'page_title_ar': 'عن آيروت - منصة SaaS لإدارة النقل',
        'meta_description_en': (
            'Learn how IRoute helps transport companies digitize operations, '
            'manage fleet and drivers, and gain full visibility.'
        ),
        'meta_description_ar': (
            'تعرّف على كيف تساعد آيروت شركات النقل على رقمنة العمليات وإدارة '
            'الأسطول والسائقين وتحقيق رؤية كاملة.'
        ),
        'page_header_h1_en': 'About IRoute',
        'page_header_h1_ar': 'عن آيروت',
        'breadcrumb_current_en': 'About IRoute',
        'breadcrumb_current_ar': 'عن آيروت',
        'about_kicker_en': 'About IRoute',
        'about_kicker_ar': 'عن آيروت',
        'about_heading_part1_en': 'Driving Transport Efficiency Through',
        'about_heading_part1_ar': 'نقود كفاءة النقل عبر',
        'about_heading_part2_en': 'Smart SaaS Technology',
        'about_heading_part2_ar': 'تقنية SaaS ذكية',
        'about_heading_part3_en': 'for modern logistics teams.',
        'about_heading_part3_ar': 'لفرق اللوجستيات الحديثة.',
        'about_counter_1_value': '24/7',
        'about_counter_1_label_en': 'System Availability',
        'about_counter_1_label_ar': 'توفر النظام',
        'about_counter_2_value': '100+',
        'about_counter_2_label_en': 'Companies Using IRoute',
        'about_counter_2_label_ar': 'شركة تستخدم آيروت',
        'about_mid_title_en': 'Built for Modern Transport Businesses',
        'about_mid_title_ar': 'مُصمَّم لشركات النقل الحديثة',
        'about_mid_body_en': (
            'IRoute connects operations, fleet, finance, and reporting into '
            'a single unified system.'
        ),
        'about_mid_body_ar': (
            'تربط آيروت العمليات والأسطول والمالية والتقارير في نظام موحّد.'
        ),
        'about_body_en': (
            'We provide a complete digital ecosystem for transport '
            'companies to manage workflows efficiently and scale '
            'operations.'
        ),
        'about_body_ar': (
            'نوفر نظاماً رقمياً متكاملاً لشركات النقل لإدارة سير العمل '
            'بكفاءة وتوسيع العمليات.'
        ),
        'about_list_item_1_en': 'End-to-End Workflow Automation',
        'about_list_item_1_ar': 'أتمتة سير العمل من البداية للنهاية',
        'about_list_item_2_en': 'Real-Time Tracking & Insights',
        'about_list_item_2_ar': 'تتبع ورؤى لحظية',
        'about_explore_label_en': 'Explore Platform',
        'about_explore_label_ar': 'استكشف المنصة',
        'about_explore_url': '/about/',
        'about_footer_text_en': (
            'IRoute is a modern transport management system designed to help '
            'logistics companies streamline operations, manage fleet, and '
            'gain full business visibility.'
        ),
        'about_footer_text_ar': (
            'آيروت نظام حديث لإدارة النقل يُساعد شركات اللوجستيات على تبسيط '
            'العمليات وإدارة الأسطول وتحقيق رؤية كاملة للأعمال.'
        ),
        'about_footer_cta_label_en': 'Book a Demo',
        'about_footer_cta_label_ar': 'احجز عرضاً',
        'about_footer_cta_url': '/contact/',
        'about_rating_value': '4.9/5',
        'about_review_label_en': '4,200+ reviews',
        'about_review_label_ar': '+4,200 تقييم',
        'approach_kicker_en': 'Our Approach',
        'approach_kicker_ar': 'نهجنا',
        'approach_heading_en': 'How IRoute Transforms Transport Operations',
        'approach_heading_ar': 'كيف تحوّل آيروت عمليات النقل',
        'approach_body_en': (
            'We focus on automation, visibility, and control to simplify '
            'complex logistics workflows.'
        ),
        'approach_body_ar': (
            'نركز على الأتمتة والرؤية والتحكم لتبسيط سير عمل اللوجستيات المعقد.'
        ),
        'approach_cta_label_en': 'Book a Demo',
        'approach_cta_label_ar': 'احجز عرضاً',
        'approach_cta_url': '/contact/',
        'how_kicker_en': 'How It Works',
        'how_kicker_ar': 'كيف يعمل',
        'how_heading_en': 'How IRoute streamlines your transport workflows',
        'how_heading_ar': 'كيف تبسّط آيروت سير عمل النقل لديك',
        'how_footer_text_en': (
            'Automate operations, improve visibility, and scale with '
            'confidence using IRoute.'
        ),
        'how_footer_text_ar': (
            'أتمتة العمليات وتحسين الرؤية والتوسع بثقة مع آيروت.'
        ),
        'how_footer_link_label_en': 'Start Free Trial',
        'how_footer_link_label_ar': 'ابدأ مجاناً',
        'how_footer_link_url': '/contact/',
        'how_rating_value': '4.9/5',
        'how_review_label_en': '4,200+ reviews',
        'how_review_label_ar': '+4,200 تقييم',
        'faq_kicker_en': 'FAQs',
        'faq_kicker_ar': 'الأسئلة الشائعة',
        'faq_heading_en': 'Answers to common questions about IRoute TMS',
        'faq_heading_ar': 'إجابات عن أسئلة شائعة حول نظام آيروت لإدارة النقل',
        'faq_intro_en': (
            'Learn how IRoute helps transport companies automate workflows, '
            'manage fleets, and improve operational visibility.'
        ),
        'faq_intro_ar': (
            'تعرّف على كيف تساعد آيروت شركات النقل على أتمتة سير العمل وإدارة '
            'الأساطيل وتحسين الرؤية التشغيلية.'
        ),
        'faq_view_all_label_en': "View all FAQ's",
        'faq_view_all_label_ar': 'عرض كل الأسئلة الشائعة',
        'faq_view_all_url': '#',
        'updated_by': 'seed_about_cms',
    }


APPROACH_PILLARS = [
    {
        'order': 1,
        'title_en': 'Our Mission',
        'title_ar': 'مهمتنا',
        'body_en': (
            'To simplify transport operations through powerful and '
            'easy-to-use SaaS solutions.'
        ),
        'body_ar': (
            'تبسيط عمليات النقل عبر حلول SaaS قوية وسهلة الاستخدام.'
        ),
    },
    {
        'order': 2,
        'title_en': 'Our Vision',
        'title_ar': 'رؤيتنا',
        'body_en': (
            'To become the leading digital platform for transport and '
            'logistics management.'
        ),
        'body_ar': (
            'أن نكون المنصة الرقمية الرائدة لإدارة النقل واللوجستيات.'
        ),
    },
    {
        'order': 3,
        'title_en': 'Core Value',
        'title_ar': 'قيمتنا الأساسية',
        'body_en': (
            'Efficiency, transparency, scalability, and innovation.'
        ),
        'body_ar': (
            'الكفاءة والشفافية وقابلية التوسع والابتكار.'
        ),
    },
]

HOW_WORK_STEPS = [
    {
        'order': 1,
        'step_number': '01',
        'title_en': 'Create Order',
        'title_ar': 'إنشاء الطلب',
        'body_en': 'Add and manage transport orders.',
        'body_ar': 'إضافة وإدارة طلبات النقل.',
    },
    {
        'order': 2,
        'step_number': '02',
        'title_en': 'Assign Fleet & Driver',
        'title_ar': 'تعيين الأسطول والسائق',
        'body_en': 'Allocate vehicles and drivers efficiently.',
        'body_ar': 'تخصيص المركبات والسائقين بكفاءة.',
    },
    {
        'order': 3,
        'step_number': '03',
        'title_en': 'Track Shipment',
        'title_ar': 'تتبع الشحنة',
        'body_en': 'Monitor real-time shipment status.',
        'body_ar': 'مراقبة حالة الشحنة لحظياً.',
    },
    {
        'order': 4,
        'step_number': '04',
        'title_en': 'Delivery & POD',
        'title_ar': 'التسليم وإثبات التسليم',
        'body_en': 'Complete delivery with proof and updates.',
        'body_ar': 'إتمام التسليم مع الإثبات والتحديثات.',
    },
]

FAQ_ITEMS = [
    {
        'order': 1,
        'question_en': 'Q1. What is IRoute TMS?',
        'question_ar': 'س1. ما هو نظام آيروت لإدارة النقل؟',
        'answer_en': (
            'IRoute is a SaaS-based transport management system that '
            'helps companies manage orders, booking, fleet, drivers, '
            'finance, POD, and reports in one platform.'
        ),
        'answer_ar': (
            'آيروت نظام SaaS لإدارة النقل يساعد الشركات على إدارة الطلبات '
            'والحجز والأسطول والسائقين والمالية وإثبات التسليم والتقارير في منصة واحدة.'
        ),
    },
    {
        'order': 2,
        'question_en': 'Q2. Can I manage fleet and drivers?',
        'question_ar': 'س2. هل يمكنني إدارة الأسطول والسائقين؟',
        'answer_en': (
            'Yes. IRoute includes fleet and driver management tools for '
            'allocation, availability tracking, and assignment control.'
        ),
        'answer_ar': (
            'نعم. تتضمن آيروت أدوات لإدارة الأسطول والسائقين للتخصيص وتتبع '
            'التوفر والتحكم في التعيينات.'
        ),
    },
    {
        'order': 3,
        'question_en': 'Q3. Does it support invoicing & payments?',
        'question_ar': 'س3. هل يدعم الفوترة والمدفوعات؟',
        'answer_en': (
            'Yes. IRoute includes integrated finance features for '
            'invoicing, payments, and transport-related financial '
            'tracking.'
        ),
        'answer_ar': (
            'نعم. تتضمن آيروت ميزات مالية متكاملة للفوترة والمدفوعات '
            'والتتبع المالي المرتبط بالنقل.'
        ),
    },
    {
        'order': 4,
        'question_en': 'Q4. Is it suitable for small transport companies?',
        'question_ar': 'س4. هل يناسب شركات النقل الصغيرة؟',
        'answer_en': (
            'Absolutely. IRoute is designed for businesses of different '
            'sizes, from small teams to multi-branch transport '
            'operations.'
        ),
        'answer_ar': (
            'بالتأكيد. صُممت آيروت لأعمال بأحجام مختلفة من الفرق الصغيرة '
            'إلى عمليات نقل متعددة الفروع.'
        ),
    },
    {
        'order': 5,
        'question_en': 'Q5. Can I track shipments in real-time?',
        'question_ar': 'س5. هل يمكنني تتبع الشحنات لحظياً؟',
        'answer_en': (
            'Yes. IRoute provides real-time shipment tracking and status '
            'updates from booking through delivery and POD.'
        ),
        'answer_ar': (
            'نعم. توفر آيروت تتبعاً لحظياً للشحنات وتحديثات الحالة من الحجز '
            'حتى التسليم وإثبات التسليم.'
        ),
    },
    {
        'order': 6,
        'question_en': 'Q6. Is data secure?',
        'question_ar': 'س6. هل البيانات آمنة؟',
        'answer_en': (
            'Yes. IRoute uses secure, role-based access and '
            'platform-level safeguards to protect operational and '
            'financial data.'
        ),
        'answer_ar': (
            'نعم. تستخدم آيروت وصولاً آمناً حسب الدور وضمانات على مستوى المنصة '
            'لحماية البيانات التشغيلية والمالية.'
        ),
    },
]


class Command(BaseCommand):
    help = 'Seed default about page CMS content (idempotent for repeaters).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding about page CMS...'))
        try:
            with transaction.atomic():
                self._seed_about_singleton()
                self._seed_approach_pillars()
                self._seed_how_work_steps()
                self._seed_faq_items()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Seed failed: {exc}'))
            raise
        self.stdout.write(self.style.SUCCESS('Done.'))

    def _seed_about_singleton(self):
        about = AboutPageContent.get_singleton()
        data = _about_singleton_text()
        for key, value in data.items():
            setattr(about, key, value)
        about.save()
        self.stdout.write(
            self.style.SUCCESS(
                '  AboutPageContent (pk=1): updated text fields.'
            )
        )

    def _seed_approach_pillars(self):
        about = AboutPageContent.get_singleton()
        for row in APPROACH_PILLARS:
            order = row['order']
            AboutApproachPillar.objects.update_or_create(
                about=about,
                order=order,
                defaults={
                    'title_en': row['title_en'],
                    'title_ar': row.get('title_ar', ''),
                    'body_en': row['body_en'],
                    'body_ar': row.get('body_ar', ''),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  AboutApproachPillar order={order} '
                    f'({row["title_en"]}): upserted.'
                )
            )

    def _seed_how_work_steps(self):
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
                    f'  AboutHowWorkStep order={order} '
                    f'({row["title_en"]}): upserted.'
                )
            )

    def _seed_faq_items(self):
        about = AboutPageContent.get_singleton()
        for row in FAQ_ITEMS:
            order = row['order']
            AboutFaqItem.objects.update_or_create(
                about=about,
                order=order,
                defaults={
                    'question_en': row['question_en'],
                    'question_ar': row.get('question_ar', ''),
                    'answer_en': row['answer_en'],
                    'answer_ar': row.get('answer_ar', ''),
                    'is_active': True,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'  AboutFaqItem order={order}: upserted.'
                )
            )
