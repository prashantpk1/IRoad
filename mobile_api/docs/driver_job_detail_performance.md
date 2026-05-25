# Job Detail — performance & production hardening

## Query architecture

| Layer | Responsibility |
|-------|----------------|
| `job_detail_perf.py` | **Single** bounded action-log fetch for detail + allowed-actions state |
| `timeline_projections.py` | Batched media previews (`action_log_id__in`, capped per log) |
| `timeline_cursor.py` | Keyset pagination (no offset) |
| `workflow_state_reconciler.py` | `prefetched_logs` avoids duplicate log scans |
| `driver_job_execute_service.py` | `select_for_update` on shipment/movement before execute |

### Detail read (GET snapshot)

1. Load shipment/movement once (driver-scoped queryset + ownership).
2. `load_scoped_action_logs(limit=max(preview, scan))` — one query with `select_related`.
3. Derive **latest action**, **timeline preview**, and **execution_state** from the same rows.
4. `get_allowed_driver_actions()` — separate engine call (executed-ID query); not duplicated for state.

### Timeline feed (GET timeline)

1. Cursor filter on scoped queryset (`page_size + 1` probe).
2. One batched media query for page `log_id`s.
3. Payload cap via `enforce_detail_payload_size`.

### Execute / POD / COD (POST)

1. `transaction.atomic` + `select_for_update` on job rows.
2. Idempotency + recent-duplicate guards in `ActionExecutionService`.
3. `execution_transaction_timer` logs `txn_ms` and `reused_existing`.

## Production limits

| Setting | Default | Purpose |
|---------|---------|---------|
| `MOBILE_JOB_DETAIL_TIMELINE_PREVIEW_LIMIT` | 15 | Detail embedded preview rows |
| `MOBILE_JOB_DETAIL_LOG_SCAN_LIMIT` | 120 | Max logs for state reconciliation |
| `MOBILE_JOB_TIMELINE_DEFAULT_PAGE_SIZE` | 20 | Timeline page |
| `MOBILE_JOB_TIMELINE_MAX_PAGE_SIZE` | 50 | Hard timeline cap |
| `MOBILE_JOB_TIMELINE_MEDIA_PER_LOG` | 3 | Media previews per log |
| `MOBILE_API_JOBS_MAX_RESPONSE_BYTES` | 524288 | JSON payload reject |
| `MOBILE_API_JOBS_DETAIL_SLOW_REQUEST_MS` | 1500 | Slow-request warning |

## Observability

- Logger: `mobile_api.jobs.detail`
- Slow requests: `job_detail_slow_request` security audit event
- Middleware: classifies path (`job_detail_shipment`, `timeline`, `execute_action`, …)
- DEBUG: `maybe_record_query_count()` attaches ORM query count to metrics

## Race conditions

Concurrent execute on the same shipment/movement is serialized at the database row via `lock_entities_for_execution()` before validation and log insert.

## Client guidance

- Use `include_timeline=0` / `include_actions=0` on detail when the full timeline/actions endpoints are loaded separately.
- Timeline: always use `cursor` + `page_size`; never offset pagination.
- Prefer dedicated `GET .../timeline/` over large detail previews for long histories.
