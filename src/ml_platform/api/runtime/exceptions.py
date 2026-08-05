"""
api/runtime/exceptions.py
=========================
Distributed exceptions catalog for the API service.
Uses domain-prefixing (CAT-XXXX) to prevent ID collisions.
"""

from ml_platform.exceptions import PlatformException


class CatalogException(PlatformException):
    """Base exception for all Catalog API errors."""

    status_code: int = 500
    error_id: str = "1000"
    message: str = "An unexpected error occurred"


class ModelNotFoundError(CatalogException):
    status_code = 404
    error_id = "1004"
    message = "Model {model_name} not found"


class ModelConflictError(CatalogException):
    status_code = 409
    error_id = "1009"
    message = "Model {model_name} already exists in the catalog."


class DatabaseError(CatalogException):
    status_code = 500
    error_id = "1010"
    message = "A database error occurred."


class TaskLaunchError(CatalogException):
    status_code = 500
    error_id = "1011"
    message = "Failed to launch ECS task."


class UpstreamServiceError(CatalogException):
    status_code = 502
    error_id = "1012"
    message = "Failed to communicate with an upstream service (e.g. MLflow, AWS ECS)."
