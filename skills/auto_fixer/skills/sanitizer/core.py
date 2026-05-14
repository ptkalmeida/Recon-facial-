"""
SanitizerSkill - Nested within AutoFixerSkill.
Cleans and normalizes string inputs before they are cast to other types.
"""
import re
from typing import Any

class SanitizerSkill:
    """
    Provides methods to clean and normalize data.
    """
    
    @staticmethod
    def clean_string(text: str) -> str:
        """
        Removes leading/trailing whitespace and hidden characters.
        """
        if not isinstance(text, str):
            return text
        return text.strip()

    @staticmethod
    def numeric_only(text: str) -> str:
        """
        Removes all non-numeric characters except dots for floats.
        """
        if not isinstance(text, str):
            return text
        return re.sub(r'[^0-9.]', '', text)
