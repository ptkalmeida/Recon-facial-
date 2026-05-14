"""
Logic for automatic type casting and data repair.
"""
from typing import Any, Type, Dict, Callable

def attempt_cast(value: Any, target_type: Type) -> Any:
    """
    Attempts to cast a value to a target type using common conversion rules.
    
    Args:
        value: The raw input value.
        target_type: The desired Python type.
        
    Returns:
        The casted value if successful, otherwise the original value.
    """
    if isinstance(value, target_type):
        return value
    
    try:
        # 1. String to Numbers
        if target_type == int:
            # Handle float strings like "10.0" -> 10
            return int(float(value))
        
        if target_type == float:
            return float(value)
        
        # 2. String to Boolean
        if target_type == bool:
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "y", "t", "on")
            return bool(value)
            
        # 3. Numeric to String
        if target_type == str:
            return str(value)
            
        # 4. Fallback: Generic constructor call
        return target_type(value)
        
    except (ValueError, TypeError, AttributeError):
        # If any error occurs, we return the original value 
        # and let the ValidatorSkill handle the failure downstream.
        return value
