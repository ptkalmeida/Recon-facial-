"""
LoggerSkill - Centralized logging system for all skills.
"""
import logging
import sys
from typing import Optional

class LoggerSkill:
    """
    Handles standardized logging for the entire application.
    """
    
    @staticmethod
    def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
        """
        Returns a configured logger instance.
        
        Args:
            name: The name of the logger (usually the skill name).
            level: The logging level.
            
        Returns:
            A configured logging.Logger instance.
        """
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(level)
        return logger
