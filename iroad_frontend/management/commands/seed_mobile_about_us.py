"""
Seed MobileAboutUsPageContent singleton with default EN/AR copy and HTML body.

Overwrites all seeded text/HTML fields on every run (same pattern as
``seed_legal_pages_cms``). Does not set ``page_header_background`` so an
optional image uploaded in superadmin CMS is preserved.

Usage:
    python manage.py seed_mobile_about_us

Console output uses an ``[OK]`` prefix (ASCII-safe on Windows ``cp1252`` consoles).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from iroad_frontend.models import MobileAboutUsPageContent


def _mobile_about_seed_data():
    return {
        'page_title_en': 'About Us',
        'page_title_ar': 'من نحن',
        'meta_description_en': (
            'About the IRoute Driver App: the field execution layer for our '
            'enterprise TMS and fleet platform - guided workflows, dispatch '
            'coordination, and logistics excellence.'
        ),
        'meta_description_ar': (
            'تعرّف على تطبيق آيروت للسائقين: طبقة التنفيذ الميداني لمنصة إدارة '
            'النقل والأسطول للمؤسسات - سير عمل موجّه، وتنسيق مع غرف العمليات، '
            'وتميّز لوجستي.'
        ),
        'page_header_h1_en': 'About Us',
        'page_header_h1_ar': 'من نحن',
        'breadcrumb_current_en': 'About Us',
        'breadcrumb_current_ar': 'من نحن',
        'content_en': _MOBILE_ABOUT_HTML_EN,
        'content_ar': _MOBILE_ABOUT_HTML_AR,
        'updated_by': 'seed_mobile_about_us',
    }


_MOBILE_ABOUT_HTML_EN = """
<section class="mobile-about-seed">
  <h2>IRoute Driver App</h2>
  <p><strong>Version</strong> 2.4.1</p>

  <h3>Driving Logistics Excellence</h3>
  <p>
    IRoute is a private, enterprise-grade Transport Management System (TMS) and Fleet
    platform. Designed as a dedicated internal environment for transport companies, it
    enables the centralized management of end-to-end logistics administration and
    operational execution.
  </p>

  <h3>The Field Execution Interface</h3>
  <p>
    The IRoute Driver App serves as the intelligent field execution layer of the platform.
    Our mission is to empower drivers with a focused, &ldquo;One Action at a Time&rdquo;
    workflow that simplifies daily tasks through guided operational logging and seamless
    coordination with dispatchers.
  </p>

  <footer class="mt-4 pt-3 border-top">
    <p class="mb-0"><small>Copyright: &copy; 2026 SPCO. All Rights Reserved</small></p>
  </footer>
</section>
""".strip()


_MOBILE_ABOUT_HTML_AR = """
<section class="mobile-about-seed" dir="rtl">
  <h2>تطبيق آيروت للسائقين</h2>
  <p><strong>الإصدار</strong> 2.4.1</p>

  <h3>التميّز في إدارة اللوجستيات</h3>
  <p>
    آيروت نظام خاص على مستوى المؤسسات لإدارة النقل (TMS) ومنصة أسطول. صُمّم كبيئة
    داخلية مخصّصة لشركات النقل، ويمكّن من إدارة مركزية لإدارة اللوجستيات والتنفيذ
    التشغيلي من البداية إلى النهاية.
  </p>

  <h3>واجهة التنفيذ الميداني</h3>
  <p>
    يعمل تطبيق آيروت للسائقين كطبقة التنفيذ الميداني الذكية للمنصة. مهمتنا تمكين
    السائقين من سير عمل مركّز &ldquo;إجراء واحد في كل مرة&rdquo; يبسّط المهام اليومية
    عبر تسجيل تشغيلي موجّه وتنسيق سلس مع مراكز التحكم والإرسال.
  </p>

  <footer class="mt-4 pt-3 border-top">
    <p class="mb-0"><small>حقوق النشر: &copy; 2026 سابكو. جميع الحقوق محفوظة</small></p>
  </footer>
</section>
""".strip()


class Command(BaseCommand):
    help = (
        'Seed MobileAboutUsPageContent singleton (EN/AR text and HTML bodies). '
        'Overwrites seeded fields each run; does not clear page_header_background.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        page = MobileAboutUsPageContent.get_singleton()
        for key, val in _mobile_about_seed_data().items():
            setattr(page, key, val)
        page.save()
        self.stdout.write(
            self.style.SUCCESS(
                '[OK] Mobile About Us CMS seeded (defaults applied).',
            ),
        )
