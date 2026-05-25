"""
Observability-safe request simulation for Job Detail / jobs middleware readiness.

Readiness probes must expose the same attributes production middleware and metrics
code expect (``method``, ``path``, ``headers``, ``mobile_job_*`` flags).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from mobile_api.helpers.job_list_security import JOBS_API_PREFIX

_DEFAULT_SHIPMENT_ID = '00000000-0000-0000-0000-000000000099'
_DEFAULT_MOVEMENT_ID = '00000000-0000-0000-0000-000000000088'


@dataclass(frozen=True)
class MiddlewareSmokeCase:
    """One synthetic jobs API request for readiness validation."""

    label: str
    method: str
    path: str
    headers: dict[str, str] | None = None
    expect_status: int = 200
    via_full_middleware: bool = True


def _normalize_method(method: str | None) -> str:
    return (method or 'GET').upper()


def ensure_request_observability_attrs(request: Any) -> Any:
    """
    Guarantee attributes used by ``MobileJobListSecurityMiddleware`` and
    ``_jobs_finish_request`` metrics (avoids ``metrics_error`` on partial fakes).
    """
    if request is None:
        raise ValueError('request is required')

    method = _normalize_method(getattr(request, 'method', None))
    if not hasattr(request, 'method') or getattr(request, 'method', None) is None:
        request.method = method
    else:
        request.method = method

    path = (
        getattr(request, 'path', None)
        or getattr(request, 'path_info', None)
        or '/'
    )
    if not isinstance(path, str):
        path = str(path)
    if not path.startswith('/'):
        path = '/' + path.lstrip('/')
    request.path = path
    if not getattr(request, 'path_info', None):
        request.path_info = path

    if not hasattr(request, 'headers'):
        meta = getattr(request, 'META', None)
        if isinstance(meta, dict):
            request.headers = {
                k[5:].replace('_', '-').title(): v
                for k, v in meta.items()
                if k.startswith('HTTP_')
            }
        else:
            request.headers = {}

    if not isinstance(request, HttpRequest):
        if not hasattr(request, 'GET'):
            request.GET = {}
        if not hasattr(request, 'POST'):
            request.POST = {}
        if not hasattr(request, 'body'):
            request.body = b''

    return request


def build_jobs_smoke_request(
    *,
    path: str,
    method: str = 'GET',
    headers: dict[str, str] | None = None,
    data: dict | None = None,
) -> Any:
    """
    Build a Django test request with full WSGI attributes for middleware smoke.
    """
    factory = RequestFactory()
    method_u = _normalize_method(method)
    path = (path or '').strip() or f'{JOBS_API_PREFIX}shipments/{_DEFAULT_SHIPMENT_ID}/'
    if not path.startswith('/'):
        path = '/' + path

    extra = dict(headers or {})
    if method_u in ('GET', 'HEAD', 'OPTIONS', 'DELETE'):
        request = getattr(factory, method_u.lower())(
            path,
            data=data or {},
            headers=extra,
        )
    else:
        request = factory.generic(
            method_u,
            path,
            data=data or {},
            headers=extra,
        )

    return ensure_request_observability_attrs(request)


def default_job_detail_smoke_cases() -> tuple[MiddlewareSmokeCase, ...]:
    sid = _DEFAULT_SHIPMENT_ID
    mid = _DEFAULT_MOVEMENT_ID
    base = JOBS_API_PREFIX
    return (
        MiddlewareSmokeCase(
            label='timeline_get',
            method='GET',
            path=f'{base}shipments/{sid}/timeline/',
        ),
        MiddlewareSmokeCase(
            label='allowed_actions_get',
            method='GET',
            path=f'{base}shipments/{sid}/actions/',
        ),
        MiddlewareSmokeCase(
            label='detail_get',
            method='GET',
            path=f'{base}shipments/{sid}/',
        ),
        MiddlewareSmokeCase(
            label='execute_post',
            method='POST',
            path=f'{base}shipments/{sid}/actions/execute/',
            expect_status=200,
        ),
        MiddlewareSmokeCase(
            label='upload_pod_post',
            method='POST',
            path=f'{base}shipments/{sid}/upload-pod/',
            expect_status=200,
        ),
        MiddlewareSmokeCase(
            label='movement_timeline_get',
            method='GET',
            path=f'{base}movements/{mid}/timeline/',
        ),
        MiddlewareSmokeCase(
            label='finish_helper_head',
            method='HEAD',
            path=f'{base}shipments/{sid}/timeline/',
            via_full_middleware=False,
        ),
    )


def _noop_get_response(request: Any) -> HttpResponse:
    return HttpResponse('ok', status=200)


def run_single_middleware_smoke_case(
    case: MiddlewareSmokeCase,
    *,
    get_response: Callable[[Any], HttpResponse] | None = None,
) -> tuple[bool, str]:
    """Run one smoke case; return (ok, error_message)."""
    import time

    from mobile_api.middleware import MobileJobListSecurityMiddleware, _jobs_finish_request

    handler = get_response or _noop_get_response
    mw = MobileJobListSecurityMiddleware(handler)

    try:
        request = build_jobs_smoke_request(
            path=case.path,
            method=case.method,
            headers=case.headers,
        )
        started = time.perf_counter()
        if case.via_full_middleware:
            response = mw(request)
        else:
            response = _jobs_finish_request(mw, request, started)
        status = getattr(response, 'status_code', None)
        if status != case.expect_status:
            return (
                False,
                f'{case.label}: expected HTTP {case.expect_status}, got {status}',
            )
        if not getattr(request, 'method', None):
            return False, f'{case.label}: request.method missing after smoke'
        return True, ''
    except Exception as exc:
        return False, f'{case.label}: {exc}'


def run_middleware_smoke_suite(
    cases: Iterable[MiddlewareSmokeCase] | None = None,
) -> tuple[bool, str]:
    """
    Validate jobs middleware + metrics path for representative Job Detail routes.
    """
    for case in cases or default_job_detail_smoke_cases():
        ok, err = run_single_middleware_smoke_case(case)
        if not ok:
            return False, err
    return True, ''


def validate_metrics_readiness_on_request(request: Any) -> tuple[bool, str]:
    """
    Ensure observability helpers accept this request (no ``metrics_error`` path).
    """
    from mobile_api.helpers.job_detail_observability import (
        classify_job_detail_operation,
        record_middleware_timing,
    )

    request = ensure_request_observability_attrs(request)
    try:
        op = classify_job_detail_operation(request.path, request.method)
        record_middleware_timing(
            operation=op,
            elapsed_ms=0.1,
            path=request.path,
            slow_threshold_ms=999999.0,
        )
    except Exception as exc:
        return False, str(exc)
    if not op:
        return False, 'empty operation label'
    return True, ''


def build_minimal_legacy_fake_request(path: str) -> Any:
    """
    Reproduce legacy readiness probes that only set ``path`` (no ``method``).

    Used by tests to prove ``ensure_request_observability_attrs`` fixes warnings.
    """

    class _LegacyFake:
        pass

    fake = _LegacyFake()
    fake.path = path
    return ensure_request_observability_attrs(fake)
