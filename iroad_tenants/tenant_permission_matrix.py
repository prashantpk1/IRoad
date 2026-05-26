"""Tenant role permission matrix — modules and forms/submodules for RBAC."""

TENANT_PERMISSION_MATRIX = [
    # Administration
    {'module_name': 'Administration', 'form_name': 'Organization Profile'},
    {'module_name': 'Administration', 'form_name': 'Users Administration'},
    {'module_name': 'Administration', 'form_name': 'Roles & Permissions'},
    {'module_name': 'Administration', 'form_name': 'Subscription Plan'},
    {'module_name': 'Administration', 'form_name': 'Subscription Billing'},
    {'module_name': 'Administration', 'form_name': 'Login / Session Events'},
    {'module_name': 'Administration', 'form_name': 'Role / Permission Changes'},
    {'module_name': 'Administration', 'form_name': 'Critical Account Changes'},
    {'module_name': 'Administration', 'form_name': 'Support Ticket Master'},
    # CRM
    {'module_name': 'CRM', 'form_name': 'Client Account'},
    {'module_name': 'CRM', 'form_name': 'Client Account Settings'},
    {'module_name': 'CRM', 'form_name': 'Client Attachments'},
    {'module_name': 'CRM', 'form_name': 'Client Contacts'},
    {'module_name': 'CRM', 'form_name': 'Client Contracts'},
    {'module_name': 'CRM', 'form_name': 'Client Contract Settings'},
    # Master Data
    {'module_name': 'Master Data', 'form_name': 'Address Master'},
    {'module_name': 'Master Data', 'form_name': 'Cargo Master'},
    {'module_name': 'Master Data', 'form_name': 'Cargo Category Config'},
    {'module_name': 'Master Data', 'form_name': 'Location Master'},
    {'module_name': 'Master Data', 'form_name': 'Route Master'},
    {'module_name': 'Master Data', 'form_name': 'Service Item Master'},
    {'module_name': 'Master Data', 'form_name': 'Price List Master'},
    # Operations
    {'module_name': 'Operations', 'form_name': 'Booking'},
    {'module_name': 'Operations', 'form_name': 'Shipment'},
    {'module_name': 'Operations', 'form_name': 'Shipment Documents'},
    {'module_name': 'Operations', 'form_name': 'Surcharge Sales Transaction'},
    {'module_name': 'Operations', 'form_name': 'Shipment POD Analysis'},
    {'module_name': 'Operations', 'form_name': 'Document Handover'},
    {'module_name': 'Operations', 'form_name': 'Truck Movement Log'},
    {'module_name': 'Operations', 'form_name': 'Operation Actions'},
    # Fleet
    {'module_name': 'Fleet', 'form_name': 'Truck Master'},
    {'module_name': 'Fleet', 'form_name': 'Truck Type Master'},
    {'module_name': 'Fleet', 'form_name': 'Truck Attachments'},
    {'module_name': 'Fleet', 'form_name': 'Truck Settings'},
    # Drivers
    {'module_name': 'Drivers', 'form_name': 'Driver Master'},
    {'module_name': 'Drivers', 'form_name': 'Driver Attachments'},
    {'module_name': 'Drivers', 'form_name': 'Driver Settings'},
    # Finance
    {'module_name': 'Finance', 'form_name': 'Sales Invoicing'},
    {'module_name': 'Finance', 'form_name': 'Purchase Invoicing'},
    {'module_name': 'Finance', 'form_name': 'Driver Treasuries'},
    {'module_name': 'Finance', 'form_name': 'Driver Treasury Transactions'},
    # System
    {'module_name': 'System', 'form_name': 'Auto Number Configuration'},
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
