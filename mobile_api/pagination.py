"""
mobile_api/pagination.py

DRF Custom Pagination class for Mobile API.

Enforces standard pagination envelope (same as ``MobileAPIView.success``):

{
  "status": 1,
  "message": "...",
  "data": {
    "items": [...],
    "total_records": 100,
    "total_pages": 10,
    "current_page": 1,
    "page_size": 10
  },
  "meta": { "request_id": "...", "timestamp": "...", "locale": "...", "api_version": "..." }
}

Usage in views:
  class TruckListView(ListAPIView):
      pagination_class = MobileApiPagination

  Or use get_paginated_response() manually:
      page = self.paginate_queryset(queryset)
      return self.get_paginated_response(serializer.data)
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django.conf import settings
import math

from mobile_api.response_envelope import build_meta


class MobileApiPagination(PageNumberPagination):
    """
    Standard pagination envelope for future mobile list endpoints.
    """
    page_query_param = 'page'
    page_size_query_param = 'page_size'

    @property
    def page_size(self):
        return getattr(settings, 'MOBILE_API_DEFAULT_PAGE_SIZE', 10)

    @property
    def max_page_size(self):
        return getattr(settings, 'MOBILE_API_MAX_PAGE_SIZE', 100)

    def get_paginated_response(self, data, message='Data retrieved successfully'):
        """
        Override to return our standard envelope.
        """
        total_records = self.page.paginator.count
        page_size = self.get_page_size(self.request)
        total_pages = math.ceil(total_records / page_size) if page_size else 1

        return Response({
            'status': 1,
            'message': str(message),
            'data': {
                'items': data,
                'total_records': total_records,
                'total_pages': total_pages,
                'current_page': self.page.number,
                'page_size': page_size,
            },
            'meta': build_meta(self.request),
        })

    def get_paginated_response_schema(self, schema):
        """
        OpenAPI schema for paginated responses.
        """
        return {
            'type': 'object',
            'properties': {
                'status': {'type': 'integer', 'example': 1},
                'message': {'type': 'string'},
                'data': {
                    'type': 'object',
                    'properties': {
                        'items': schema,
                        'total_records': {'type': 'integer'},
                        'total_pages': {'type': 'integer'},
                        'current_page': {'type': 'integer'},
                        'page_size': {'type': 'integer'},
                    }
                }
            }
        }

