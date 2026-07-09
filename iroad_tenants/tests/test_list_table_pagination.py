from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase
from django.core.paginator import Paginator

from iroad_tenants.list_table_utils import (
    build_eal_pagination_page_links,
    eal_list_query_href,
    paginate_tenant_list,
)


class EalListPaginationTests(SimpleTestCase):
    def test_eal_list_query_href_uses_question_mark_when_empty(self):
        self.assertEqual(eal_list_query_href(''), '?')
        self.assertEqual(eal_list_query_href('page=2'), '?page=2')

    def test_page_one_link_clears_existing_page_param(self):
        factory = RequestFactory()
        request = factory.get('/operations/truck-movement-log/', {'page': '6'})

        page, ctx = paginate_tenant_list(request, list(range(58)))

        self.assertEqual(page.number, 6)
        page_one_href = next(href for num, href in ctx['pagination_page_links'] if num == 1)
        self.assertEqual(page_one_href, '?')
        self.assertEqual(ctx['pagination_prev_url'], '?page=5')

    def test_elided_page_links_show_ellipsis_for_many_pages(self):
        paginator = Paginator(list(range(123)), 10)
        page = paginator.get_page(1)

        links = build_eal_pagination_page_links(page, lambda n: f'?page={n}')

        labels = [num for num, _href in links]
        self.assertIn(Paginator.ELLIPSIS, labels)
        self.assertEqual(labels[0], 1)
        self.assertEqual(labels[-1], 13)
        self.assertLess(len(labels), paginator.num_pages)
