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

    def test_strips_google_fonts_and_base_tag_for_offline_pdf(self):
        html = (
            '<html><head>'
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans" rel="stylesheet">'
            '<base href="http://127.0.0.1:8000/">'
            '</head><body></body></html>'
        )
        prepared = prepare_print_html_for_wkhtmltopdf(html)
        self.assertNotIn('fonts.googleapis.com', prepared)
        self.assertNotIn('<base ', prepared.lower())

    def test_injects_wkhtmltopdf_compat_styles_once(self):
        html = '<html><head></head><body></body></html>'
        prepared = inject_wkhtmltopdf_compat_styles(html)
        self.assertEqual(prepared.count('id="wkhtmltopdf-compat"'), 1)
        self.assertIn('display: table !important', prepared)
        self.assertIn('background: #1E40AF !important', prepared)
