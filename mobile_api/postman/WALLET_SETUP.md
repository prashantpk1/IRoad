# Driver Wallet API — Postman Setup

## Import

1. Postman → **Import**
2. Select:
   - `Iroad_Mobile_Driver_Wallet.postman_collection.json`
   - `Iroad_Mobile_Local.postman_environment.json`
3. Environment: **Iroad Mobile — Local**

## Run order

| Step | Request |
|------|---------|
| 1 | **01 — Login** |
| 2 | **02 — Wallet List** |
| 3 | **03 — Filter Preview** (`count_only=true`) |
| 4 | **04 — Apply Filter** |
| 5 | **05 — Transaction Detail** |

## Prerequisites

- Driver has an **active** `DriverTreasury` wallet
- At least one **COD** shipment with **A9 Collect Payment** fired (creates Client Collection · Credit row)
- Capability `mobile.driver.wallet`

## Endpoints

| Screen | Method | URL |
|--------|--------|-----|
| My Wallet | GET | `{{base_url}}/driver/wallet/` |
| Filter preview / apply | GET | same + `count_only`, `shipment_no`, `date` |
| Transaction detail | GET | `{{base_url}}/driver/wallet/transactions/{{transaction_id}}/` |

See `mobile_api/wallet/WALLET_API.md` for response shapes.
