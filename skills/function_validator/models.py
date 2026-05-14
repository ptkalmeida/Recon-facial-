"""
Models and types for FunctionValidatorSkill.
"""
from typing import Any, Callable, Dict, Optional, Type
from dataclasses import dataclass

@dataclass
class ValidationMetadata:
    """Metadata for a validation operation."""
    function_name: str
    args: tuple
    kwargs: dict
    expected_types: Optional[Dict[str, Type]] = None
    return_type: Optional[Type] = None
    execution_time: Optional[float] = None
