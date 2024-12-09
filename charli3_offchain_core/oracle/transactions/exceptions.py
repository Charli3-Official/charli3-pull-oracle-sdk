class UTxONotFoundError(Exception):
    """Raised when a required UTxO cannot be found"""

    pass


class ValidationError(Exception):
    """Custom exception for validation errors"""

    pass
