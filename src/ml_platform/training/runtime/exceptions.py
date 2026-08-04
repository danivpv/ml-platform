"""
training/runtime/exceptions.py
==============================
Exceptions specific to the ML Platform Training microservice.
"""

from ml_platform.exceptions import PlatformException


class TrainingException(PlatformException):
    """Base exception for all Training microservice errors."""

    status_code: int = 500
    error_id: str = "2000"
    message: str = "An unexpected training error occurred"


class EmptyDatasetError(TrainingException):
    """Raised when the merged training dataset contains no rows."""

    status_code: int = 400
    error_id: str = "2001"
    message: str = "Merged training dataset is empty — check that entity IDs and event timestamps align between the feature parquet and labels parquet."
