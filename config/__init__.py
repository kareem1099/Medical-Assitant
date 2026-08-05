"""
Configuration module for the Smart Medical Assistant.

Exports:
    settings: Global Settings instance with validated configuration
    setup_logging: Function to configure application logging
    get_logger: Function to get module-specific loggers
"""

from config.settings import settings, Settings
from config.logging_config import setup_logging, get_logger

__all__ = ["settings", "Settings", "setup_logging", "get_logger"]
