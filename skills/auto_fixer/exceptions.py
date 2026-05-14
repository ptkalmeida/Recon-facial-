"""
Custom exceptions for AutoFixerSkill.
"""

class AutoFixError(Exception):
    """Base exception for AutoFixerSkill."""
    pass

class CastingError(AutoFixError):
    """Raised when a type conversion fails and strict mode is enabled."""
    pass
