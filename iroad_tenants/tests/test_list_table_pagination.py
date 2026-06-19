from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase

from iroad_tenants.list_table_utils import eal_list_query_href, paginate_tenant_list


class EalListPaginationTests(SimpleTestCase):
    def test_eal_list_query_href_uses_question_mark_when_empty(self):
        self.assertEqual(eal_list_query_href(''), '?')
        self.assertEqual(eal_list_query_href('page=2'), '?page=2')

    def test_page_one_link_clears_existing_page_param(self):
        factory = RequestFactory()
        request = factory.get('/operations/truck-movement-log/', {'page': '6'})

        page, ctx = paginate_tenant_list(request, list(range(58)))

        self.assertEqual(page.number, 6)
        page_one_href = ctx['pagination_page_links'][0][1]
        self.assertEqual(page_one_href, '?')
        self.assertEqual(ctx['pagination_prev_url'], '?page=5')
