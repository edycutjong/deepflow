"""
Logging configuration for Silent Whale.
- Development: pretty loguru console output
- Production: structured JSON to stdout for log aggregation
"""
import os
import sys

from loguru import logger


def setup_logging() -> None:
    """Configure loguru based on LOG_FORMAT env var."""
    log_format = os.getenv("LOG_FORMAT", "pretty")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # Remove default handler
    logger.remove()

    if log_format == "json":
        # Production: JSON lines to stdout
        logger.add(
            sys.stdout,
            format="{message}",
            level=log_level,
            serialize=True,  # JSON output
        )
    else:
        # Development: pretty colored output
        logger.add(
            sys.stdout,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            level=log_level,
            colorize=True,
        )

    logger.info(f"Logging configured: format={log_format}, level={log_level}")
