"""
mobile_api/views/driver_jobs.py

Driver job list feeds — separate shipment and movement operational queues.
"""
from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.helpers.job_list_cache import (
    build_list_fingerprint,
    get_cached_list_page,
    get_cached_job_summary,
    set_cached_job_summary,
    set_cached_list_page,
)
from mobile_api.helpers.job_list_guards import enforce_payload_limit
from mobile_api.helpers.job_list_observability import (
    build_count_fingerprint,
    estimate_payload_bytes,
    job_list_timer,
    log_payload_size,
)
from mobile_api.helpers.job_list_pagination import MobileJobListPagination
from mobile_api.helpers.job_list_performance import (
    job_list_fast_serialize_enabled,
    resolve_include_total,
)
from mobile_api.helpers.job_list_serialize import serialize_job_card_items
from mobile_api.permissions import HasDriverJobsAccess
from mobile_api.throttling import MobileJobListThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.views.driver_profile import (
    _mobile_jwt_payload,
    _mobile_tenant_schema,
    _mobile_user_id,
)
from mobile_api.helpers.job_list_action_aggregation import hydrate_job_list_page_actions
from mobile_api.helpers.job_list_security import (
    SecureJobListContext,
    sanitize_job_list_page,
)
from mobile_api.services.driver_job_list_service import (
    build_job_summary,
    resolve_secure_job_list_context,
)
from mobile_api.serializers.driver_job_list import JobSummarySerializer


class _DriverJobListBaseView(MobileAPIView):
    permission_classes = [HasDriverJobsAccess]
    required_mobile_capability = 'mobile.driver.jobs'
    throttle_classes = [MobileJobListThrottle]
    job_list_entity_type = ''

    def _resolve_driver(self, request):
        tenant_schema = _mobile_tenant_schema(request)
        secured = resolve_secure_job_list_context(
            user_id=_mobile_user_id(request),
            tenant_schema=tenant_schema,
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
        )
        if not secured.get('success'):
            return None, secured
        ctx = secured['ctx']
        return ctx, None

    def _paginate_job_cards(
        self,
        request,
        *,
        queryset,
        build_fn,
        serializer_class,
        meta: dict,
        message: str,
        message_key: str,
        driver=None,
        entity_type: str = 'shipment',
        include_actions: bool = True,
        list_ctx: SecureJobListContext | None = None,
        list_filters=None,
        sort: str = 'updated_desc',
    ):
        if list_filters is not None and list_ctx is not None:
            request._job_list_count_fingerprint = build_count_fingerprint(
                entity_type=entity_type,
                filters=list_filters,
                sort=sort,
                include_actions=include_actions,
            )
            request._job_list_tenant_schema = list_ctx.tenant_schema
            request._job_list_driver_id = str(list_ctx.driver.pk)
        self.job_list_sort = sort

        paginator = MobileJobListPagination()
        page_size = paginator.get_page_size(request)
        page_number = paginator.get_page_number(request, page_size)
        include_total = resolve_include_total(request)

        fingerprint = ''
        if list_filters is not None and list_ctx is not None:
            fingerprint = build_list_fingerprint(
                entity_type=entity_type,
                filters=list_filters,
                sort=sort,
                page=page_number,
                page_size=page_size,
                include_actions=include_actions,
                include_total=include_total,
            )
            cached = get_cached_list_page(
                tenant_schema=list_ctx.tenant_schema,
                driver_id=str(list_ctx.driver.pk),
                fingerprint=fingerprint,
            )
            if cached is not None:
                return self.success(
                    message=message,
                    data=cached,
                    message_key=message_key,
                )

        with job_list_timer(
            operation='list_page',
            tenant_schema=list_ctx.tenant_schema if list_ctx else '',
            driver_id=str(driver.pk) if driver is not None else '',
            entity_type=entity_type,
        ) as metrics:
            page = paginator.paginate_queryset(
                queryset,
                request,
                view=self,
            )
            if paginator.pagination_error:
                return self.error(
                    message=paginator.pagination_error,
                    code='job_list_pagination_limit',
                    message_key='mobile.jobs.pagination_limit',
                )

            fast_serialize = job_list_fast_serialize_enabled()

            def _build_items(rows):
                page_rows = list(rows)
                if list_ctx is not None and page_rows:
                    page_rows = sanitize_job_list_page(
                        page_rows,
                        ctx=list_ctx,
                        entity_type=entity_type,  # type: ignore[arg-type]
                    )
                if driver is not None and page_rows:
                    hydrate_job_list_page_actions(
                        page_rows,
                        entity_type=entity_type,  # type: ignore[arg-type]
                        driver=driver,
                        request=request,
                        include_actions=include_actions,
                    )
                return [build_fn(row, request=request) for row in page_rows]

            if page is not None:
                items = _build_items(page)
                metrics['item_count'] = len(items)
                payload_items = serialize_job_card_items(
                    items,
                    serializer_class=serializer_class,
                    use_fast_path=fast_serialize,
                )
                metrics['payload_bytes'] = estimate_payload_bytes(payload_items)
                payload_items, payload_err, payload_code = enforce_payload_limit(
                    payload_items,
                )
                if payload_items is None:
                    return self.error(
                        message=payload_err or _('mobile.jobs.payload_too_large'),
                        code=payload_code or 'job_list_payload_too_large',
                        message_key='mobile.jobs.payload_too_large',
                    )
                if payload_err:
                    metrics['payload_truncated'] = True
                log_payload_size(
                    operation=f'{entity_type}_list',
                    items=payload_items,
                    tenant_schema=list_ctx.tenant_schema if list_ctx else '',
                    driver_id=str(driver.pk) if driver is not None else '',
                )
                response = paginator.get_paginated_response(
                    payload_items,
                    message=message,
                )
                response.data['data']['meta'] = meta
                response.data['message_key'] = message_key
                if fingerprint and list_ctx is not None:
                    set_cached_list_page(
                        tenant_schema=list_ctx.tenant_schema,
                        driver_id=str(list_ctx.driver.pk),
                        fingerprint=fingerprint,
                        payload=response.data['data'],
                    )
                return response

            rows = list(queryset[:page_size])
            items = _build_items(rows)
            metrics['item_count'] = len(items)
            payload_items = serialize_job_card_items(
                items,
                serializer_class=serializer_class,
                use_fast_path=fast_serialize,
            )
            payload_items, payload_err, payload_code = enforce_payload_limit(
                payload_items,
            )
            if payload_items is None:
                return self.error(
                    message=payload_err or _('mobile.jobs.payload_too_large'),
                    code=payload_code or 'job_list_payload_too_large',
                    message_key='mobile.jobs.payload_too_large',
                )
            log_payload_size(
                operation=f'{entity_type}_list',
                items=payload_items,
                tenant_schema=list_ctx.tenant_schema if list_ctx else '',
                driver_id=str(driver.pk) if driver is not None else '',
            )
            data = {'items': payload_items, 'meta': meta}
            if payload_err:
                data['payload_warning'] = payload_code
            return self.success(
                message=message,
                data=data,
                message_key=message_key,
            )


class DriverJobSummaryView(_DriverJobListBaseView):
    """
    GET /api/v1/mobile/driver/jobs/summary/

    Operational counters for My Jobs tabs (tab-aligned; independent of dashboard payload).
    """

    def get(self, request):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='job_list_context_failed',
                message_key='mobile.error.generic',
            )

        driver_id = str(ctx.driver.pk)
        cached = get_cached_job_summary(
            tenant_schema=ctx.tenant_schema,
            driver_id=driver_id,
        )
        if cached is not None:
            serializer = JobSummarySerializer(cached)
            return self.success(
                message=_('mobile.jobs.summary_success'),
                data=serializer.data,
                message_key='mobile.jobs.summary_success',
            )

        with job_list_timer(
            operation='summary',
            tenant_schema=ctx.tenant_schema,
            driver_id=driver_id,
        ):
            summary = build_job_summary(
                driver=ctx.driver,
                tenant_schema=ctx.tenant_schema,
            )

        set_cached_job_summary(
            tenant_schema=ctx.tenant_schema,
            driver_id=driver_id,
            payload=summary,
        )
        serializer = JobSummarySerializer(summary)
        return self.success(
            message=_('mobile.jobs.summary_success'),
            data=serializer.data,
            message_key='mobile.jobs.summary_success',
        )
