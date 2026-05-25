"""
Reusable operational execution services (portal + mobile).

Import service classes from this package instead of calling portal view helpers.
"""

from iroad_tenants.services.cod_execution_service import CODExecutionService
from iroad_tenants.services.latest_state_service import LatestStateService
from iroad_tenants.services.operation_execution_service import OperationExecutionService
from iroad_tenants.services.pod_execution_service import PODExecutionService
from iroad_tenants.services.timeline_service import TimelineService


def __getattr__(name: str):
    if name == 'ActionExecutionService':
        from iroad_tenants.services.action_execution_service import ActionExecutionService

        return ActionExecutionService
    raise AttributeError(name)


__all__ = [
    'ActionExecutionService',
    'CODExecutionService',
    'LatestStateService',
    'OperationExecutionService',
    'PODExecutionService',
    'TimelineService',
]
