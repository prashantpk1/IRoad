from django.apps import AppConfig


class TenantWorkspaceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenant_workspace'
    label = 'tenant_workspace'
    verbose_name = 'Tenant workspace (isolated schema)'
