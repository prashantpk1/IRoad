For Table Design Promt :-

- Apply the same table UI design used on the "Client-contract-list.html" page to the "Operation-action-log-details.html" page.

- Update the table headings/content based on the "Operation-action-log.html" form feilds , also update details page contant as pr "Operation-action-log.html".

-
- Apply the same table UI design used on the "Report-shipment-documentation.html" page to the "Report-support-management.html" page.
- Update the table headings/content based on the given image
-
-
-

For Form Design Promt :-

- Apply the same form UI design used on the ( Sales-invoice-list-invoicing.html and Client-account-setting.html ) page to the "Surcharge-purchase-transaction-create.html" ( create new pages) page.
- according to fields make proepr UI Design
- Update the form fields based on the data
  (
---

# Fields List

## 1. Transaction No
**Field Key:** `trx_no`

- Auto-number
- Unique
- Read-only

---

## 2. Shipment Ref
**Field Key:** `shipment_id`

- Required
- Select shipment
- Main source reference

---

## 3. Booking Ref
**Field Key:** `booking_id`

- Auto-fetched from Shipment
- Read-only

---

## 4. Vendor
**Field Key:** `vendor_id`

- Auto-fetched from Shipment
- No manual selection

---

## 5. Date
**Field Key:** `trx_date`

- Required
- Default = Today

---

## 6. Currency
**Field Key:** `currency_code`

- Auto-fetched from Shipment
- Locked

---

## 7. Service
**Field Key:** `service_item_id`

- Required
- Must be Cost Service Item

---

## 8. Description
**Field Key:** `description`

- Optional
- Additional details

---

## 9. Quantity
**Field Key:** `quantity`

- Required
- Decimal
- Default = 1

---

## 10. Unit Cost
**Field Key:** `unit_cost`

- Required
- Manual input or fetched from master

---

## 11. Total Amount
**Field Key:** `total_amount`

- Auto-calculated

Formula:

Quantity × Unit Cost

---

## 12. Vendor Ref No
**Field Key:** `vendor_ref_no`

- Optional
- Vendor invoice number / claim reference

---

## 13. Status
**Field Key:** `status`

Options:

- Draft
- Confirmed
- Billed
- Cancelled

---

## 14. Attachment
**Field Key:** `attachment_file`

- Required
- Supporting proof document

Examples:
- Vendor Bill
- Receipt
- Invoice Copy
- Claim Slip

---

# Business Rules

## Shipment Source Logic

When Shipment selected:

- Booking auto-fill
- Vendor auto-fill
- Currency auto-fill

---

## Vendor Rule

Vendor is locked from Shipment.  
No manual override.

---

## Pricing Logic

Total updates automatically when:

- Quantity changes
- Unit Cost changes

---

## Service Rule

Only cost/service items allowed.

Revenue items not allowed.

---

# Validation Rules

## Required Fields

- Transaction No
- Shipment Ref
- Date
- Service
- Quantity
- Unit Cost
- Total Amount
- Status
- Attachment

---

## Numeric Rules

- Quantity > 0
- Unit Cost >= 0
- Total Amount >= 0

---

## Confirmation Rules

Before Confirm:

- Shipment selected
- Vendor available in shipment
- Service selected
- Valid amount entered
- Attachment uploaded

---

## Billing Rule

When linked to Purchase Invoice / Vendor Bill:

- Status = Billed
- Record becomes locked

---

## Cancellation Rule

Allow cancel only if:

- Not billed
- User has permission

---

# Suggested UI Layout

## Section 1: Transaction Header
- Transaction No
- Date
- Status

## Section 2: Shipment Details
- Shipment Ref
- Booking Ref
- Vendor
- Currency

## Section 3: Cost Details
- Service
- Description
- Quantity
- Unit Cost
- Total Amount
- Vendor Ref No

## Section 4: Proof & Documents
- Attachment

---

# Recommended Dashboard KPIs

- Total Extra Cost
- Draft Costs
- Confirmed Costs
- Billed Costs
- Cancelled Costs
- Cost by Vendor
- Cost by Service Type
- Monthly Operational Cost

---

# Search Filters

- Transaction No
- Shipment Ref
- Booking Ref
- Vendor
- Date Range
- Status
- Service
- Amount Range


  ( note :- for css use style.css and responsive.css , do not write css in html use give files )

-
