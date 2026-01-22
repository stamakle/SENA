"""Structured Error Taxonomy (Recommendation #14).

This module defines a hierarchy of specific error classes for the agent to
programmatically handle failures (e.g., distinguishing between a network
timeout and a fatal NVMe media error).

Usage:
    from src.errors import SSHTimeoutError, NVMeMediaError
    
    try:
        run_command(...)
    except SSHTimeoutError:
        retry()
    except NVMeMediaError:
        abort_test()
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any, Dict

@dataclass
class ErrorContext:
    """Contextual metadata for errors."""
    host: Optional[str] = None
    command: Optional[str] = None
    device: Optional[str] = None
    severity: str = "error"  # warning, error, critical
    recoverable: bool = True

class SENAError(Exception):
    """Base class for all SENA agent errors."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message)
        self.context = context or ErrorContext()
        self.error_code = "GENERIC_ERROR"

# --- Infrastructure Errors (Network, SSH, System) ---

class InfrastructureError(SENAError):
    """Base for system/infra errors."""
    pass

class SSHConnectionError(InfrastructureError):
    """SSH connection failed completely."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "SSH_CONN_FAIL"

class SSHTimeoutError(InfrastructureError):
    """Command timed out locally or remotely."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "SSH_TIMEOUT"

class CircuitOpenError(InfrastructureError):
    """Operation blocked by circuit breaker."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "CIRCUIT_OPEN"
        self.context.recoverable = False

# --- Domain Errors (NVMe, Test, Device) ---

class DomainError(SENAError):
    """Base for SSD/Validation domain errors."""
    pass

class NVMeCommandError(DomainError):
    """Non-zero exit status from nvme-cli."""
    def __init__(self, message: str, status_code: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "NVME_CMD_FAIL"
        self.nvme_status = status_code

class NVMeMediaError(DomainError):
    """Critical media failure (Unrecovered Read Error, etc.)."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "NVME_MEDIA_FAIL"
        self.context.severity = "critical"
        self.context.recoverable = False

class NVMeCriticalWarning(DomainError):
    """SMART critical warning set."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "NVME_CRIT_WARN"
        self.context.severity = "critical"

class TestCaseFailure(DomainError):
    """Validation logic assertion failed."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "TEST_ASSERT_FAIL"

# --- Agent Errors (Planning, context) ---

class AgentError(SENAError):
    """Internal agent logic errors."""
    pass

class ContextLimitExceeded(AgentError):
    """RAG context too large."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "CTX_overflow"

class PlanExecutionError(AgentError):
    """Failure in step executor loop."""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message, context)
        self.error_code = "PLAN_EXEC_FAIL"
