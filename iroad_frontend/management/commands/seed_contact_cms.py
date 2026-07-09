"""
Seed ContactPageContent singleton from designer IRoute-landing/contact.html.
Idempotent: refreshes all text fields each run. No child models.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from iroad_frontend.models import ContactPageContent


def _contact_singleton_from_designer():
    return {
        'page_title_en': 'Contact IRoute',
        'page_title_ar': 'تواصل مع آيروت',
        'meta_description_en': (
            'Contact IRoute to request a demo, ask about pricing, or speak '
            'with our transport SaaS team.'
        ),
        'meta_description_ar': (
            'تواصل مع آيروت لطلب عرض أو الاستفسار عن الأسعار أو التحدث مع '
            'فريق منصة النقل.'
        ),
        'page_header_h1_en': 'Contact IRoute',
        'page_header_h1_ar': 'تواصل مع آيروت',
        'breadcrumb_current_en': 'Contact',
        'breadcrumb_current_ar': 'تواصل',
        'section_kicker_en': 'contact Us',
        'section_kicker_ar': 'تواصل معنا',
        'section_heading_en': (
            'Get in touch with our team to explore IRoute'
        ),
        'section_heading_ar': 'تواصل مع فريقنا لاستكشاف آيروت',
        'form_title_en': 'Request a Demo',
        'form_title_ar': 'اطلب عرضاً',
        'form_fname_placeholder_en': 'First Name',
        'form_fname_placeholder_ar': 'الاسم الأول',
        'form_lname_placeholder_en': 'Last Name',
        'form_lname_placeholder_ar': 'اسم العائلة',
        'form_phone_placeholder_en': 'Phone Number',
        'form_phone_placeholder_ar': 'رقم الهاتف',
        'form_email_placeholder_en': 'Email Address',
        'form_email_placeholder_ar': 'البريد الإلكتروني',
        'form_message_placeholder_en': (
            'Tell us about your transport business or requirements'
        ),
        'form_message_placeholder_ar': 'أخبرنا عن متطلباتك',
        'form_consent_label_en': (
            'I agree to receive communication regarding product updates and '
            'demo scheduling.'
        ),
        'form_consent_label_ar': (
            'أوافق على تلقي رسائل حول تحديثات المنتج وجدولة العرض التوضيحي.'
        ),
        'form_submit_label_en': 'Book Demo',
        'form_submit_label_ar': 'احجز عرضاً',
        'form_action_url': '/contact/submit/',
        'sidebar_heading_en': (
            'Start your digital transport journey with IRoute'
        ),
        'sidebar_heading_ar': 'ابدأ رحلتك الرقمية في النقل مع آيروت',
        'support_label_en': 'Our Support',
        'support_label_ar': 'الدعم',
        'support_hours_en': 'Monday - Friday : 9:00 AM - 6:00 PM',
        'support_hours_ar': 'الإثنين - الجمعة: 9:00 ص - 6:00 م',
        'support_online_label_en': '24/7 Email Support Available',
        'support_online_label_ar': 'دعم عبر البريد على مدار الساعة',
        'info_book_label_en': 'Book a Demo',
        'info_book_label_ar': 'احجز عرضاً',
        'info_phone_1': '+91 98765 43210',
        'info_phone_2': '+91 91234 56789',
        'info_email_label_en': 'Email',
        'info_email_label_ar': 'البريد',
        'info_email_1': 'support@iroute.com',
        'info_email_2': 'sales@iroute.com',
        'info_platform_label_en': (
            'Cloud-Based Platform - Accessible Worldwide'
        ),
        'info_platform_label_ar': 'منصة سحابية — متاحة عالمياً',
        'updated_by': 'seed_contact_cms',
    }


class Command(BaseCommand):
    help = 'Seed ContactPageContent singleton from designer contact.html.'

    @transaction.atomic
    def handle(self, *args, **options):
        contact = ContactPageContent.get_singleton()
        data = _contact_singleton_from_designer()
        for key, val in data.items():
            setattr(contact, key, val)
        contact.save()
        self.stdout.write(
            self.style.SUCCESS('Contact page CMS seeded (singleton).'),
        )
