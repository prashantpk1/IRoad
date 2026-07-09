"""
Seed PrivacyPolicyPageContent and TermsConditionsPageContent singletons.

Idempotent: overwrites all text/HTML fields each run. Does not set
page_header_background (optional FileField — upload via superadmin CMS).

Usage:
    python manage.py seed_legal_pages_cms
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from iroad_frontend.models import (
    PrivacyPolicyPageContent,
    TermsConditionsPageContent,
)


def _privacy_seed_data():
    return {
        'page_title_en': 'Privacy Policy - IRoute',
        'page_title_ar': 'سياسة الخصوصية - آيروت',
        'meta_description_en': (
            'Read the IRoute privacy policy: how we collect, use, and protect '
            'your data when you use our transport management platform.'
        ),
        'meta_description_ar': (
            'اطلع على سياسة خصوصية آيروت: كيف نجمع بياناتك ونستخدمها ونحميها '
            'عند استخدامك لمنصة إدارة النقل.'
        ),
        'page_header_h1_en': 'Privacy Policy',
        'page_header_h1_ar': 'سياسة الخصوصية',
        'breadcrumb_current_en': 'Privacy Policy',
        'breadcrumb_current_ar': 'سياسة الخصوصية',
        'content_en': _PRIVACY_HTML_EN,
        'content_ar': _PRIVACY_HTML_AR,
        'updated_by': 'seed_legal_pages_cms',
    }


def _terms_seed_data():
    return {
        'page_title_en': 'Terms & Conditions - IRoute',
        'page_title_ar': 'الشروط والأحكام - آيروت',
        'meta_description_en': (
            'IRoute terms and conditions of use for the website and SaaS '
            'transport management services.'
        ),
        'meta_description_ar': (
            'شروط وأحكام استخدام آيروت للموقع ولخدمات إدارة النقل السحابية.'
        ),
        'page_header_h1_en': 'Terms & Conditions',
        'page_header_h1_ar': 'الشروط والأحكام',
        'breadcrumb_current_en': 'Terms & Conditions',
        'breadcrumb_current_ar': 'الشروط والأحكام',
        'content_en': _TERMS_HTML_EN,
        'content_ar': _TERMS_HTML_AR,
        'updated_by': 'seed_legal_pages_cms',
    }


_PRIVACY_HTML_EN = """
<h2>Introduction</h2>
<p>IRoute (&ldquo;we&rdquo;, &ldquo;us&rdquo;, or &ldquo;our&rdquo;) operates a transport management
software platform. This Privacy Policy explains how we handle personal and
business information when you visit our website or use our services.</p>

<h2>Information we collect</h2>
<ul>
  <li><strong>Account data:</strong> name, email, phone, company name, and role.</li>
  <li><strong>Usage data:</strong> log data, device type, browser, and approximate region.</li>
  <li><strong>Support content:</strong> messages and attachments you send to us.</li>
</ul>

<h2>How we use information</h2>
<p>We use the information to provide and improve the service, authenticate users,
send operational notices, comply with law, and protect the security and
integrity of our platform.</p>

<h2>Sharing</h2>
<p>We do not sell your personal information. We may share data with subprocessors
who assist us (e.g. hosting, email delivery) under strict agreements, or when
required by law.</p>

<h2>Retention</h2>
<p>We retain data as long as needed to provide the service and meet legal
obligations. Retention periods may vary by data category.</p>

<h2>Your rights</h2>
<p>Depending on your jurisdiction, you may have rights to access, correct,
delete, or restrict processing of your personal data. Contact us using the
details on our contact page.</p>

<h2>Changes</h2>
<p>We may update this policy from time to time. The &ldquo;Last updated&rdquo; date will be
revised when material changes are made.</p>

<h2>Contact</h2>
<p>For privacy questions, please reach out through the contact options published
on our website.</p>
""".strip()


_PRIVACY_HTML_AR = """
<h2>مقدمة</h2>
<p>تُدير شركة آيروت (&ldquo;نحن&rdquo;) منصة برمجيات لإدارة النقل. توضح سياسة الخصوصية هذه
كيفية تعاملنا مع المعلومات الشخصية وذات الصلة بالأعمال عند زيارتك لموقعنا أو
استخدامك لخدماتنا.</p>

<h2>المعلومات التي نجمعها</h2>
<ul>
  <li><strong>بيانات الحساب:</strong> الاسم والبريد والهاتف واسم الشركة والدور.</li>
  <li><strong>بيانات الاستخدام:</strong> سجلات الدخول ونوع الجهاز والمتصفح والمنطقة التقريبية.</li>
  <li><strong>محتوى الدعم:</strong> الرسائل والمرفقات التي ترسلها إلينا.</li>
</ul>

<h2>كيف نستخدم المعلومات</h2>
<p>نستخدم المعلومات لتقديم الخدمة وتحسينها والتحقق من المستخدمين وإرسال إشعارات
تشغيلية والامتثال للقانون وحماية أمن المنصة وسلامتها.</p>

<h2>المشاركة</h2>
<p>لا نبيع معلوماتك الشخصية. قد نشارك البيانات مع معالجين فرعيين يساعدوننا
(مثل الاستضافة وإرسال البريد) بموجب اتفاقيات صارمة، أو عند الاقتضاء القانوني.</p>

<h2>الاحتفاظ</h2>
<p>نحتفظ بالبيانات ما دام ذلك لازماً لتقديم الخدمة والوفاء بالالتزامات القانونية،
وقد تختلف مدة الاحتفاظ حسب فئة البيانات.</p>

<h2>حقوقك</h2>
<p>بحسب اختصاصك القضائي قد يكون لك حق الوصول أو التصحيح أو الحذف أو تقييد
المعالجة. تواصل معنا عبر وسائل الاتصال المنشورة في الموقع.</p>

<h2>التغييرات</h2>
<p>قد نحدّث هذه السياسة من وقت لآخر، وسيُعدَّل تاريخ &ldquo;آخر تحديث&rdquo; عند إجراء تغييرات
جوهرية.</p>

<h2>التواصل</h2>
<p>للاستفسارات المتعلقة بالخصوصية، يرجى التواصل عبر خيارات الاتصال المنشورة في
موقعنا.</p>
""".strip()


_TERMS_HTML_EN = """
<h2>Agreement</h2>
<p>By accessing or using IRoute websites, demos, or cloud services, you agree to
these Terms &amp; Conditions and our Privacy Policy.</p>

<h2>Services</h2>
<p>IRoute provides software and related services for transport and logistics
operations. Features and availability may differ by plan or region.</p>

<h2>Accounts</h2>
<p>You are responsible for maintaining the confidentiality of credentials and for
all activity under your account. Notify us promptly of any unauthorized use.</p>

<h2>Acceptable use</h2>
<ul>
  <li>No unlawful, harmful, or deceptive activity.</li>
  <li>No attempt to disrupt, probe, or bypass security controls.</li>
  <li>No scraping or automated access that violates our policies or applicable law.</li>
</ul>

<h2>Intellectual property</h2>
<p>IRoute and its licensors retain all rights in the software, branding, and
content. You receive a limited license to use the service according to your
subscription.</p>

<h2>Disclaimer</h2>
<p>The service is provided on an &ldquo;as is&rdquo; basis to the extent permitted by law.
We do not warrant uninterrupted or error-free operation.</p>

<h2>Limitation of liability</h2>
<p>To the maximum extent permitted by law, IRoute is not liable for indirect,
incidental, special, or consequential damages arising from use of the service.</p>

<h2>Termination</h2>
<p>We may suspend or terminate access for breach of these terms or for operational
or legal reasons, subject to your contract where applicable.</p>

<h2>Governing law</h2>
<p>These terms are governed by the laws applicable to your agreement with IRoute,
unless otherwise specified in writing.</p>

<h2>Changes</h2>
<p>We may update these terms. Continued use after changes constitutes acceptance of
the revised terms where permitted by law.</p>

<h2>Contact</h2>
<p>For questions about these terms, use the contact information on our website.</p>
""".strip()


_TERMS_HTML_AR = """
<h2>الاتفاق</h2>
<p>باستخدامك لمواقع آيروت أو العروض التوضيحية أو الخدمات السحابية فإنك توافق على
هذه الشروط والأحكام وعلى سياسة الخصوصية.</p>

<h2>الخدمات</h2>
<p>توفر آيروت برمجيات وخدمات مرتبطة بعمليات النقل واللوجستيات، وقد تختلف
الميزات والتوفر حسب الخطة أو المنطقة.</p>

<h2>الحسابات</h2>
<p>أنت مسؤول عن سرية بيانات الدخول وعن كل النشاط تحت حسابك. أبلغنا فوراً عن أي
استخدام غير مصرح به.</p>

<h2>الاستخدام المقبول</h2>
<ul>
  <li>يُمنع أي نشاط غير قانوني أو ضار أو مضلل.</li>
  <li>يُمنع محاولة تعطيل أو اختبار أو تجاوز ضوابط الأمن.</li>
  <li>يُمنع الاستخراج الآلي أو الوصول الآلي بما يخالف سياساتنا أو القانون.</li>
</ul>

<h2>الملكية الفكرية</h2>
<p>تحتفظ آيروت والمرخصون لها بجميع الحقوق في البرمجيات والعلامات والمحتوى،
ويُمنح لك ترخيص محدود لاستخدام الخدمة وفق اشتراكك.</p>

<h2>إخلاء المسؤولية</h2>
<p>تُقدَّم الخدمة &ldquo;كما هي&rdquo; في الحدود التي يسمح بها القانون، ولا نضمن تشغيلاً
دائماً أو خالياً من الأخطاء.</p>

<h2>تحديد المسؤولية</h2>
<p>في الحد الأقصى الذي يسمح به القانون، لا تتحمل آيروت المسؤولية عن الأضرار
غير المباشرة أو العرضية أو الخاصة أو التبعية الناتجة عن استخدام الخدمة.</p>

<h2>إنهاء الخدمة</h2>
<p>قد نعلق أو ننهي الوصول عند مخالفة هذه الشروط أو لأسباب تشغيلية أو قانونية،
مع مراعاة عقدك حيث ينطبق ذلك.</p>

<h2>القانون الحاكم</h2>
<p>تخضع هذه الشروط للقوانين المعمول بها في اتفاقك مع آيروت ما لم يُنص على
خلاف ذلك كتابةً.</p>

<h2>التغييرات</h2>
<p>قد نحدّث هذه الشروط، ويُعدّ استمرارك في الاستخدام بعد التغيير قبولاً للشروط
المعدّلة حيث يسمح القانون بذلك.</p>

<h2>التواصل</h2>
<p>للأسئلة حول هذه الشروط، استخدم معلومات الاتصال المنشورة في موقعنا.</p>
""".strip()


class Command(BaseCommand):
    help = (
        'Seed PrivacyPolicyPageContent and TermsConditionsPageContent '
        'singletons (EN/AR text and sample HTML bodies).'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        privacy = PrivacyPolicyPageContent.get_singleton()
        for key, val in _privacy_seed_data().items():
            setattr(privacy, key, val)
        privacy.save()
        self.stdout.write(
            self.style.SUCCESS('Privacy Policy CMS singleton seeded.'),
        )

        terms = TermsConditionsPageContent.get_singleton()
        for key, val in _terms_seed_data().items():
            setattr(terms, key, val)
        terms.save()
        self.stdout.write(
            self.style.SUCCESS('Terms & Conditions CMS singleton seeded.'),
        )
