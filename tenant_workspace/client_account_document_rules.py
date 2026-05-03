"""Client account document rules (tenant schema settings) — pure helpers, no ORM."""

_CLIENT_TYPE_INDIVIDUAL = 'Individual'
_CLIENT_TYPE_BUSINESS = 'Business'

MSG_NATIONAL_ID = (
    'National ID is required for individual clients under your Client Account Settings.'
)
MSG_COMMERCIAL_REG = (
    'Commercial Registration is required for business clients under your Client Account Settings.'
)
MSG_TAX_VAT = (
    'Tax/VAT registration is required for business clients under your Client Account Settings.'
)


def collect_client_account_document_rule_errors(
    *,
    client_type: str,
    national_id: str,
    commercial_registration_no: str,
    tax_registration_no: str,
    require_national_id_individual: bool,
    require_commercial_registration_business: bool,
    require_tax_vat_registration_business: bool,
) -> dict[str, str]:
    """Return ``{field_name: message}`` for violations; empty if none."""
    errors: dict[str, str] = {}
    ct = (client_type or '').strip()
    if ct == _CLIENT_TYPE_INDIVIDUAL:
        if require_national_id_individual and not (national_id or '').strip():
            errors['national_id'] = MSG_NATIONAL_ID
    elif ct == _CLIENT_TYPE_BUSINESS:
        if require_commercial_registration_business and not (
            (commercial_registration_no or '').strip()
        ):
            errors['commercial_registration_no'] = MSG_COMMERCIAL_REG
        if require_tax_vat_registration_business and not ((tax_registration_no or '').strip()):
            errors['tax_registration_no'] = MSG_TAX_VAT
    return errors
