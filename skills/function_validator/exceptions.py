"""
Custom exceptions for the FunctionValidatorSkill.
"""

class ValidationError(Exception):
    """Base class for validation errors."""
    pass

class InputValidationError(ValidationError):
    """Raised when function arguments fail validation."""
    pass

class OutputValidationError(ValidationError):
    """Raised when function return value fails validation."""
    pass
