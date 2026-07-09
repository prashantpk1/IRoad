# Driver My Wallet API

Read-only COD treasury view per IRoute Ch.13 (driver wallet) and Collect Payment (A9).

**Base:** `/api/v1/mobile/`  
**Capability:** `mobile.driver.wallet`  
**Auth:** `Authorization: Bearer <access_token>`

## Wallet list + filter preview

`GET /driver/wallet/`

| Query | Description |
|-------|-------------|
| `shipment_no` | Filter by shipment number (partial), transaction no, or shipment UUID |
| `date` | Transaction date — `YYYY-MM-DD` or `DD-MM-YYYY` |
| `count_only` | `true` — filter modal preview (`results_found` only) |

Returns **summary** (total balance) plus the full filtered transaction list (no pagination).

**Success `data`:**

```json
{
  "summary": {
    "treasury_id": "uuid",
    "treasury_code": "DTR-000001",
    "total_cash_collected": "10500.00",
    "currency": "SAR",
    "sync_status": "synced",
    "read_only": true
  },
  "items": [
    {
      "transaction_id": "uuid",
      "transaction_no": "TT-000001",
      "booking_no": "BK-000010",
      "shipment_no": "SH-2026-1001",
      "amount": "4500.00",
      "currency": "SAR",
      "cash_flow": "in",
      "transaction_type_label": "Received Amount",
      "transaction_date": "2026-02-10",
      "transaction_date_display": "10 Feb 2026",
      "payment_method": "COD",
      "read_only": true
    }
  ],
  "count": 1,
  "results_found": 1
}
```

## Transaction detail

`GET /driver/wallet/transactions/<transaction_id>/`

`transaction_id` = UUID or `transaction_no` (e.g. `TT-000001`).

**Success `data`:**

```json
{
  "summary": {
    "transaction_no": "TT-000001",
    "transaction_type_label": "Received Amount",
    "amount": "4500.00",
    "currency": "SAR",
    "transaction_date": "2026-02-10",
    "transaction_date_display": "10 Feb 2026",
    "cash_flow": "in",
    "read_only": true
  },
  "transaction": { },
  "shipment": {
    "shipment_no": "SH-2026-1001",
    "status": "Completed",
    "transaction_type": "Credit",
    "transaction_type_label": "Received Amount",
    "route": { "type": "Round", "route_display": "Jeddah → Riyadh" },
    "payment_method": "COD",
    "client_name": "Al Marai Company"
  },
  "description": "Action 9 · Collect Payment · COD collection …",
  "read_only": true
}
```

## Rules (IRoute Ch.13)

- **Read-only** — wallet does not create treasury rows; A9 / admin paths do.
- Driver sees only their **active** `DriverTreasury` wallet.
- **Client Collection · Credit** = cash received (UI: “Received Amount”, `cash_flow: in`).
- **Custody Collection · Debit** = cash handed over (`cash_flow: out`).
- Balance = `DriverTreasury.current_balance` (credits − debits).

## Errors

| Code | HTTP | When |
|------|------|------|
| `invalid_date` | 400 | Bad `date` query |
| `wallet_not_found` | 404 | No active driver treasury |
| `transaction_not_found` | 404 | Unknown / foreign transaction |
| `tenant_required` | 400 | Missing tenant schema |
