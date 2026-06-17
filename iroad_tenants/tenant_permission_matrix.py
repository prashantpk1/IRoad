"""Tenant role permission matrix — modules and forms/submodules for RBAC."""

# Permission flag fields on TenantRolePermission (order matches matrix UI columns).
TENANT_PERMISSION_FLAGS = (
    'can_access',
    'can_write',
    'can_read',
    'can_view',
    'can_edit',
    'can_export',
    'can_approve',
    'can_print',
)

# Legacy form labels still stored on older tenant_role_permissions rows.
TENANT_PERMISSION_FORM_ALIASES = {
    'Shipment POD Analysis': 'Shipment PODs',
    'Sales Invoicing': 'Sales Invoice Report',
    'Driver Treasury Transactions': 'Transactions',
}

# Legacy module/form pairs mapped to the current sidebar-aligned matrix location.
TENANT_PERMISSION_LOCATION_ALIASES = {
    ('Administration', 'Organization Profile'): ('Account Management', 'Organization Profile'),
    ('Administration', 'Users Administration'): ('User Management', 'Users Administration'),
    ('Administration', 'Roles & Permissions'): ('User Management', 'Roles & Permissions'),
    ('Administration', 'Subscription Plan'): ('Subscriptions Management', 'Subscription Plan'),
    ('Administration', 'Subscription Billing'): ('Subscriptions Management', 'Subscription Billing'),
    ('Administration', 'Login / Session Events'): ('Audit & Security Logs', 'Login / Session Events'),
    ('Administration', 'Role / Permission Changes'): ('Audit & Security Logs', 'Role / Permission Changes'),
    ('Administration', 'Critical Account Changes'): ('Audit & Security Logs', 'Critical Account Changes'),
    ('Administration', 'Support Ticket Master'): ('Support Management', 'Support Ticket Master'),
    ('CRM', 'Client Account'): ('Clients Management', 'Client Account'),
    ('CRM', 'Client Account Settings'): ('Clients Management', 'Client Account Settings'),
    ('CRM', 'Client Attachments'): ('Clients Management', 'Client Attachments'),
    ('CRM', 'Client Contacts'): ('Clients Management', 'Client Contacts'),
    ('CRM', 'Client Contracts'): ('Clients Management', 'Client Contracts'),
    ('CRM', 'Client Contract Settings'): ('Clients Management', 'Client Contract Settings'),
    ('Master Data', 'Address Master'): ('Address Management', 'Address Master'),
    ('Master Data', 'Cargo Master'): ('Cargo Management', 'Cargo Master'),
    ('Master Data', 'Cargo Category Config'): ('Cargo Management', 'Cargo Category Config'),
    ('Master Data', 'Location Master'): ('Route Management', 'Location Master'),
    ('Master Data', 'Route Master'): ('Route Management', 'Route Master'),
    ('Master Data', 'Service Item Master'): ('Services Management', 'Service Item Master'),
    ('Master Data', 'Service Category Config'): ('Services Management', 'Service Category Config'),
    ('Master Data', 'Price List Master'): ('Services Management', 'Price List Master'),
    ('Operations', 'Booking'): ('Operations Management', 'Booking'),
    ('Operations', 'Shipment'): ('Operations Management', 'Shipment'),
    ('Operations', 'Shipment Documents'): ('Operations Management', 'Shipment Documents'),
    ('Operations', 'Surcharge Sales Transaction'): ('Operations Management', 'Surcharge Sales Transaction'),
    ('Operations', 'Shipment PODs'): ('Operations Management', 'Shipment PODs'),
    ('Operations', 'Shipment POD Analysis'): ('Operations Management', 'Shipment PODs'),
    ('Operations', 'Document Handover'): ('Operations Management', 'Document Handover'),
    ('Operations', 'Truck Movement Log'): ('Operations Management', 'Truck Movement Log'),
    ('Operations', 'Operation Actions'): ('Operations Management', 'Operation Actions'),
    ('Fleet', 'Truck Master'): ('Fleet Management', 'Truck Master'),
    ('Fleet', 'Truck Type Master'): ('Fleet Management', 'Truck Type Master'),
    ('Fleet', 'Truck Attachments'): ('Fleet Management', 'Truck Attachments'),
    ('Fleet', 'Truck Settings'): ('Fleet Management', 'Truck Settings'),
    ('Drivers', 'Driver Master'): ('Driver Management', 'Driver Master'),
    ('Drivers', 'Driver Attachments'): ('Driver Management', 'Driver Attachments'),
    ('Drivers', 'Driver Settings'): ('Driver Management', 'Driver Settings'),
    ('Finance', 'Sales Invoicing'): ('Sales Invoicing', 'Sales Invoice Report'),
    ('Finance', 'Sales Invoice Report'): ('Sales Invoicing', 'Sales Invoice Report'),
    ('Finance', 'Driver Treasuries'): ('Driver Treasury', 'Driver Treasuries'),
    ('Finance', 'Driver Treasury Transactions'): ('Driver Treasury', 'Transactions'),
    ('Finance', 'Transactions'): ('Driver Treasury', 'Transactions'),
    ('System', 'Auto Number Configuration'): ('Configurations', 'Auto Number Configuration'),
}


def resolve_canonical_form_name(form_name):
    """Map legacy stored form names to the current matrix label."""
    return TENANT_PERMISSION_FORM_ALIASES.get(form_name, form_name)


def resolve_canonical_permission_location(module_name, form_name):
    """Map legacy module/form pairs to the current sidebar-aligned matrix location."""
    canonical_form = resolve_canonical_form_name(form_name)
    return TENANT_PERMISSION_LOCATION_ALIASES.get(
        (module_name, form_name),
        TENANT_PERMISSION_LOCATION_ALIASES.get(
            (module_name, canonical_form),
            (module_name, canonical_form),
        ),
    )


# Sidebar-aligned permission matrix (section → submenu → form).
TENANT_PERMISSION_MATRIX = [
    # Administration — Account Management
    {'module_name': 'Account Management', 'form_name': 'Organization Profile'},
    # Administration — User Management
    {'module_name': 'User Management', 'form_name': 'Users Administration'},
    {'module_name': 'User Management', 'form_name': 'Roles & Permissions'},
    # Administration — Subscriptions Management
    {'module_name': 'Subscriptions Management', 'form_name': 'Subscription Plan'},
    {'module_name': 'Subscriptions Management', 'form_name': 'Subscription Billing'},
    # Administration — Audit & Security Logs
    {'module_name': 'Audit & Security Logs', 'form_name': 'Login / Session Events'},
    {'module_name': 'Audit & Security Logs', 'form_name': 'Role / Permission Changes'},
    {'module_name': 'Audit & Security Logs', 'form_name': 'Critical Account Changes'},
    # Administration — Support Management
    {'module_name': 'Support Management', 'form_name': 'Support Ticket Master'},
    # CRM — Clients Management
    {'module_name': 'Clients Management', 'form_name': 'Client Account'},
    {'module_name': 'Clients Management', 'form_name': 'Client Account Settings'},
    {'module_name': 'Clients Management', 'form_name': 'Client Attachments'},
    {'module_name': 'Clients Management', 'form_name': 'Client Contacts'},
    {'module_name': 'Clients Management', 'form_name': 'Client Contracts'},
    {'module_name': 'Clients Management', 'form_name': 'Client Contract Settings'},
    # Master Data — Address Management
    {'module_name': 'Address Management', 'form_name': 'Address Master'},
    # Master Data — Cargo Management
    {'module_name': 'Cargo Management', 'form_name': 'Cargo Master'},
    {'module_name': 'Cargo Management', 'form_name': 'Cargo Category Config'},
    # Master Data — Route Management
    {'module_name': 'Route Management', 'form_name': 'Location Master'},
    {'module_name': 'Route Management', 'form_name': 'Route Master'},
    # Master Data — Services Management
    {'module_name': 'Services Management', 'form_name': 'Service Item Master'},
    {'module_name': 'Services Management', 'form_name': 'Service Category Config'},
    {'module_name': 'Services Management', 'form_name': 'Price List Master'},
    # Operations — Operations Management
    {'module_name': 'Operations Management', 'form_name': 'Booking'},
    {'module_name': 'Operations Management', 'form_name': 'Shipment'},
    {'module_name': 'Operations Management', 'form_name': 'Shipment Documents'},
    {'module_name': 'Operations Management', 'form_name': 'Surcharge Sales Transaction'},
    {'module_name': 'Operations Management', 'form_name': 'Shipment PODs'},
    {'module_name': 'Operations Management', 'form_name': 'Document Handover'},
    {'module_name': 'Operations Management', 'form_name': 'Truck Movement Log'},
    {'module_name': 'Operations Management', 'form_name': 'Operation Actions'},
    # Operations — Fleet Management
    {'module_name': 'Fleet Management', 'form_name': 'Truck Master'},
    {'module_name': 'Fleet Management', 'form_name': 'Truck Type Master'},
    {'module_name': 'Fleet Management', 'form_name': 'Truck Attachments'},
    {'module_name': 'Fleet Management', 'form_name': 'Truck Settings'},
    # Operations — Driver Management
    {'module_name': 'Driver Management', 'form_name': 'Driver Master'},
    {'module_name': 'Driver Management', 'form_name': 'Driver Attachments'},
    {'module_name': 'Driver Management', 'form_name': 'Driver Settings'},
    # Finance — Sales Invoicing
    {'module_name': 'Sales Invoicing', 'form_name': 'Sales Invoice Report'},
    # Finance — Driver Treasury
    {'module_name': 'Driver Treasury', 'form_name': 'Driver Treasuries'},
    {'module_name': 'Driver Treasury', 'form_name': 'Transactions'},
    # System — Configurations
    {'module_name': 'Configurations', 'form_name': 'Auto Number Configuration'},
]


def enrich_permission_matrix_rows(rows):
    """Add show_module_name for grouped table display."""
    prev_module = None
    enriched = []
    for row in rows:
        module_name = row['module_name']
        enriched.append({**row, 'show_module_name': module_name != prev_module})
        prev_module = module_name
    return enriched
