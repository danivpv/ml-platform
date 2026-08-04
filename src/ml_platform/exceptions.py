"""
ml_platform/exceptions.py
=========================
Shared base exception class for all ML Platform microservices.
Pulls the service prefix (e.g., CAT, TRN, INF) from the SERVICE_PREFIX environment variable.
"""

from ml_platform.config import settings


class PlatformException(Exception):
    """
    Base exception for all ML Platform errors.
    Automatically formats error messages and prefixes error codes based on the service environment.
    """

    status_code: int = 500
    error_id: str = "1000"
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None, **kwargs):
        self.error_code = f"{settings.service_prefix}-{self.error_id}"

        self.message = message or self.message.format(**kwargs)
        super().__init__(self.message)
