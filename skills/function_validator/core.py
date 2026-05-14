"""
Core logic for FunctionValidatorSkill.
Provides decorators for runtime function validation.
"""
import functools
import inspect
import time
from typing import Any, Callable, Dict, Type, Union

from skills.logger import LoggerSkill
from .exceptions import InputValidationError, OutputValidationError
from .models import ValidationMetadata

# Initialize logger using LoggerSkill
logger = LoggerSkill.get_logger("FunctionValidator")

def validate_contract(
    input_types: Dict[str, Type] = None,
    output_type: Type = None,
    log_execution: bool = True
) -> Callable:
    """
    Decorator to validate function inputs and outputs against specified types.

    Args:
        input_types: Dictionary mapping argument names to expected types.
        output_type: Expected return type.
        log_execution: Whether to log execution details and timing.

    Returns:
        The decorated function.

    Example:
        @validate_contract(input_types={'x': int, 'y': int}, output_type=int)
        def add(x, y):
            return x + y
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            func_name = func.__name__
            
            # 1. Validate Inputs
            if input_types:
                signature = inspect.signature(func)
                bound_arguments = signature.bind(*args, **kwargs)
                bound_arguments.apply_defaults()
                
                for name, value in bound_arguments.arguments.items():
                    if name in input_types:
                        expected = input_types[name]
                        if not isinstance(value, expected):
                            msg = f"Argument '{name}' in '{func_name}' expected {expected}, got {type(value)}"
                            logger.error(msg)
                            raise InputValidationError(msg)

            # 2. Execute and Time
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                end_time = time.perf_counter()
                duration = end_time - start_time
            except Exception as e:
                logger.exception(f"Exception during execution of '{func_name}': {str(e)}")
                raise

            # 3. Validate Output
            if output_type and not isinstance(result, output_type):
                msg = f"Return value of '{func_name}' expected {output_type}, got {type(result)}"
                logger.error(msg)
                raise OutputValidationError(msg)

            # 4. Optional Logging
            if log_execution:
                logger.info(f"Function '{func_name}' executed successfully in {duration:.4f}s")

            return result
        return wrapper
    return decorator

def check_not_none(value: Any, name: str = "Value") -> Any:
    """
    Utility to ensure a value is not None.
    
    Args:
        value: The value to check.
        name: Name for error reporting.
        
    Returns:
        The value if not None.
        
    Raises:
        InputValidationError: If value is None.
    """
    if value is None:
        raise InputValidationError(f"{name} cannot be None")
    return value
