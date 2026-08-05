"""
Logging configuration for the Smart Medical Assistant.

Configures structured logging with output to both console and file.
Uses ISO format timestamps and includes logger name and level in output.
"""

import logging
import os
from pathlib import Path
from typing import Optional


def setup_logging(log_file: str = "./logs/app.log", level: int = logging.INFO) -> None:
    """
    Configure application logging.
    
    Sets up logging to write to both console and file with structured format:
    - Timestamp in ISO 8601 format
    - Logger name
    - Log level
    - Message
    
    Args:
        log_file: Path to log file (default: ./logs/app.log)
        level: Logging level (default: logging.INFO)
    
    Raises:
        OSError: If log directory cannot be created or accessed
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Define structured log format
    # Format: 2024-01-15 10:23:45,123 - module_name - INFO - Log message
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Create formatter
    formatter = logging.Formatter(log_format, datefmt=date_format)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear any existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Console handler (INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (INFO and above)
    try:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError as e:
        root_logger.warning(
            f"Could not create log file at {log_file}: {e}. "
            f"Continuing with console logging only."
        )
    
    # Log successful configuration
    root_logger.info(f"Logging configured: level={logging.getLevelName(level)}, file={log_file}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__ from the calling module)
    
    Returns:
        Configured logger instance
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started")
    """
    return logging.getLogger(name)
