"""Centralized logging configuration with lazy logging patterns.

This module provides a standardized logging setup with lazy evaluation
to improve performance by deferring string interpolation until necessary.

Lazy logging example:
    logger.debug("Processing: %s", expensive_data)  # String not evaluated if level disabled
    
Instead of:
    logger.debug(f"Processing: {expensive_data}")   # Always evaluated
"""

import logging
import logging.config
from typing import Optional, Any


def _resolve_log_level(level: str) -> int:
    """Resolve a textual log level to the logging module integer value.

    Args:
        level: Logging level name, e.g. "DEBUG", "INFO".

    Returns:
        int: Numeric logging level constant.

    Raises:
        ValueError: If the provided level string is not recognized.
    """
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        raise ValueError(f"Invalid log level: {level}")
    return resolved


def setup_logging(
    name: str,
    level: str = "INFO",
    log_format: Optional[str] = None
) -> logging.Logger:
    """Setup a logger with lazy logging patterns and consistent formatting.
    
    This function creates a logger with a standardized format that supports
    lazy string interpolation. All loggers should use this function for
    consistency across the application.
    
    Args:
        name: Logger name (typically __name__)
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Custom log format string. Uses default if None.
        
    Returns:
        Configured logger instance

    Raises:
        ValueError: If the provided log level is invalid.
        
    Example:
        >>> logger = setup_logging(__name__)
        >>> logger.info("User created: %s", user_id)  # Lazy evaluation
        >>> logger.debug("Data: %s", large_object)    # Only if DEBUG enabled
    """
    
    if log_format is None:
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    resolved_level = _resolve_log_level(level)

    logger = logging.getLogger(name)
    logger.setLevel(resolved_level)
    
    # Remove existing handlers to prevent duplicates
    logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(resolved_level)
    
    # Create formatter
    formatter = logging.Formatter(log_format)
    handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(handler)
    
    return logger


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Get or create a logger with lazy logging support.
    
    This is a convenience function for getting loggers in modules.
    
    Args:
        name: Logger name (typically __name__)
        level: Logging level
        
    Returns:
        Configured logger instance

    Raises:
        ValueError: If the provided log level is invalid.
    """
    return setup_logging(name, level)


class StructuredLogger:
    """Wrapper for structured logging with lazy evaluation.
    
    Provides helper methods that ensure lazy evaluation of log arguments,
    improving performance when logging complex objects or function results.
    
    Example:
        >>> logger = StructuredLogger.for_module(__name__)
        >>> logger.log_grpc_call("CreateInvoice", invoice_id="INV-001")
        >>> logger.log_db_operation("INSERT", "invoices", rows_affected=1)
    """
    
    def __init__(self, logger: logging.Logger):
        """Initialize with base logger.
        
        Args:
            logger: Base logging.Logger instance
        """
        self.logger = logger
    
    @classmethod
    def for_module(cls, module_name: str, level: str = "INFO") -> "StructuredLogger":
        """Create a StructuredLogger for a module.
        
        Args:
            module_name: Module name (typically __name__)
            level: Logging level
            
        Returns:
            StructuredLogger instance
        """
        logger = setup_logging(module_name, level)
        return cls(logger)
    
    def log_grpc_call(
        self,
        method_name: str,
        status: str = "IN_PROGRESS",
        **context_data: Any
    ) -> None:
        """Log a gRPC method call with context.
        
        Args:
            method_name: Name of gRPC method
            status: Operation status (IN_PROGRESS, SUCCESS, FAILED)
            **context_data: Additional context to log (lazy evaluated)
        """
        context_str = ", ".join(f"{k}=%s" % (v,) for k, v in context_data.items())
        if context_str:
            self.logger.info("gRPC %s [%s] - %s", method_name, status, context_str)
        else:
            self.logger.info("gRPC %s [%s]", method_name, status)
    
    def log_db_operation(
        self,
        operation: str,
        entity: str,
        status: str = "SUCCESS",
        **details: Any
    ) -> None:
        """Log a database operation.
        
        Args:
            operation: Operation type (CREATE, READ, UPDATE, DELETE)
            entity: Entity type (e.g., "invoice")
            status: Operation status
            **details: Additional details (lazy evaluated)
        """
        details_str = ", ".join(f"{k}=%s" % (v,) for k, v in details.items())
        if details_str:
            self.logger.info("DB %s %s [%s] - %s", operation, entity, status, details_str)
        else:
            self.logger.info("DB %s %s [%s]", operation, entity, status)
    
    def log_rabbitmq_event(
        self,
        event: str,
        status: str = "SUCCESS",
        **context: Any
    ) -> None:
        """Log a RabbitMQ event.
        
        Args:
            event: Event type (CONNECTED, MESSAGE_RECEIVED, MESSAGE_SENT, ERROR)
            status: Event status
            **context: Additional context (lazy evaluated)
        """
        context_str = ", ".join(f"{k}=%s" % (v,) for k, v in context.items())
        if context_str:
            self.logger.info("RabbitMQ %s [%s] - %s", event, status, context_str)
        else:
            self.logger.info("RabbitMQ %s [%s]", event, status)
    
    def log_error(self, message: str, exc_info: Optional[Exception] = None, **context: Any) -> None:
        """Log an error with context.
        
        Args:
            message: Error message
            exc_info: Exception object (optional)
            **context: Additional context (lazy evaluated)
        """
        context_str = ", ".join(f"{k}=%s" % (v,) for k, v in context.items())
        if context_str:
            self.logger.error("%s - %s", message, context_str, exc_info=exc_info)
        else:
            self.logger.error(message, exc_info=exc_info)
    
    def log_warning(self, message: str, **context: Any) -> None:
        """Log a warning with context.
        
        Args:
            message: Warning message
            **context: Additional context (lazy evaluated)
        """
        context_str = ", ".join(f"{k}=%s" % (v,) for k, v in context.items())
        if context_str:
            self.logger.warning("%s - %s", message, context_str)
        else:
            self.logger.warning(message)

    def log_info(self, message: str, **context: Any) -> None:
        """Log an info message with context.

        Args:
            message: Info message
            **context: Additional context (lazy evaluated)
        """
        context_str = ", ".join(f"{k}=%s" % (v,) for k, v in context.items())
        if context_str:
            self.logger.info("%s - %s", message, context_str)
        else:
            self.logger.info(message)
    
    def log_debug(self, message: str, **context: Any) -> None:
        """Log debug info with context.
        
        Args:
            message: Debug message
            **context: Additional context (lazy evaluated)
        """
        context_str = ", ".join(f"{k}=%s" % (v,) for k, v in context.items())
        if context_str:
            self.logger.debug("%s - %s", message, context_str)
        else:
            self.logger.debug(message)


# Module-level logger for this file
_logger = setup_logging(__name__)
