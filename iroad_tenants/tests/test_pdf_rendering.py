from django.test import SimpleTestCase

from iroad_tenants.pdf_rendering import (
    expand_print_css_variables,
    inject_wkhtmltopdf_compat_styles,
    prepare_print_html_for_wkhtmltopdf,
)


class PrintCssVariableExpansionTests(SimpleTestCase):
    def test_expands_brand_tokens_used_in_print_templates(self):
        html = '<style>thead th { background: var(--brand-blue-dark); color: var(--paper); }</style>'
        expanded = expand_print_css_variables(html)
        self.assertIn('background: #1E40AF', expanded)
        self.assertIn('color: #FFFFFF', expanded)
        self.assertNotIn('var(--', expanded)

    def test_injects_base_tag_when_site_url_configured(self):
        with self.settings(SITE_URL='http://127.0.0.1:8000'):
            html = '<html><head><meta charset="utf-8"></head><body></body></html>'
            prepared = prepare_print_html_for_wkhtmltopdf(html)
        self.assertIn('<base href="http://127.0.0.1:8000/">', prepared)

    def test_injects_wkhtmltopdf_compat_styles_once(self):
        html = '<html><head></head><body></body></html>'
        prepared = inject_wkhtmltopdf_compat_styles(html)
        self.assertEqual(prepared.count('id="wkhtmltopdf-compat"'), 1)
        self.assertIn('display: table !important', prepared)
        self.assertIn('background: #1E40AF !important', prepared)
