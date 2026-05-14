"""
Core decorator for AutoFixerSkill.
Heals type mismatches before they reach the main logic.
"""
import functools
import inspect
from typing import Any, Callable, Dict, Type

from skills.logger import LoggerSkill
from .casting import attempt_cast
from .skills.sanitizer import SanitizerSkill

# Initialize logger using LoggerSkill
logger = LoggerSkill.get_logger("AutoFixer")

def auto_fix(input_types: Dict[str, Type], sanitize: bool = True) -> Callable:
    """
    Decorator that attempts to fix argument types before function execution.
    
    Args:
        input_types: Mapping of argument names to desired types.
        sanitize: Whether to clean strings before casting.
        
    Returns:
        The decorated function with auto-casting capabilities.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            signature = inspect.signature(func)
            bound_arguments = signature.bind(*args, **kwargs)
            bound_arguments.apply_defaults()
            
            arguments = dict(bound_arguments.arguments)
            
            for name, value in arguments.items():
                if name in input_types:
                    target_type = input_types[name]
                    
                    # 1. Sanitize if enabled and it's a string
                    if sanitize and isinstance(value, str):
                        value = SanitizerSkill.clean_string(value)
                        # If targeting a number, remove non-numeric chars
                        if target_type in (int, float):
                            value = SanitizerSkill.numeric_only(value)
                    
                    # 2. Attempt Casting
                    if not isinstance(value, target_type):
                        fixed_value = attempt_cast(value, target_type)
                        
                        if isinstance(fixed_value, target_type):
                            logger.info(
                                f"AutoFixer: Handled '{name}' in '{func.__name__}'. "
                                f"Converted {type(bound_arguments.arguments[name]).__name__} -> {target_type.__name__}"
                            )
                            arguments[name] = fixed_value
            
            return func(**arguments)
        return wrapper
    return decorator
