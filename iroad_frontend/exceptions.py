class ServiceUnavailableError(Exception):
    """Raised when a required infrastructure dependency (e.g. Redis) is offline."""
