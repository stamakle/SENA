"""Circuit Breaker for Flapping Hosts (Recommendation #13).

Implements a circuit breaker pattern to prevent repeated connection attempts
to hosts that are consistently failing. This improves production stability
by avoiding retry storms and enabling graceful degradation.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failures exceeded threshold, requests fail fast
- HALF_OPEN: Testing if host has recovered

Usage:
    from src.domain.circuit_breaker import get_circuit_breaker, CircuitState
    
    breaker = get_circuit_breaker("192.168.1.10")
    
    if breaker.can_execute():
        try:
            result = run_ssh_command(...)
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
            if breaker.state == CircuitState.OPEN:
                return "Host is unhealthy, skipping"
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List
import json
from pathlib import Path


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing fast, not attempting connections
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changes: int = 0
    current_state: CircuitState = CircuitState.CLOSED


@dataclass
class CircuitBreaker:
    """Circuit breaker for a single host.
    
    Attributes:
        host: The host identifier (IP or hostname)
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before testing recovery
        failure_window: Seconds to track failures (rolling window)
        half_open_max_calls: Max calls allowed in half-open state
    """
    host: str
    failure_threshold: int = 3
    recovery_timeout: float = 600.0  # 10 minutes
    failure_window: float = 600.0    # 10 minutes
    half_open_max_calls: int = 1
    
    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failures: List[float] = field(default_factory=list, init=False)
    _last_failure_time: Optional[float] = field(default=None, init=False)
    _last_state_change: float = field(default_factory=time.time, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _stats: CircuitStats = field(default_factory=CircuitStats, init=False)
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, potentially transitioning from OPEN to HALF_OPEN."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                time_in_open = time.time() - self._last_state_change
                if time_in_open >= self.recovery_timeout:
                    self._transition_to(CircuitState.HALF_OPEN)
            return self._state
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state (must hold lock)."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._last_state_change = time.time()
            self._stats.state_changes += 1
            self._stats.current_state = new_state
            
            if new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0
    
    def _clean_old_failures(self) -> None:
        """Remove failures outside the rolling window (must hold lock)."""
        cutoff = time.time() - self.failure_window
        self._failures = [t for t in self._failures if t > cutoff]
    
    def can_execute(self) -> bool:
        """Check if a request can be executed.
        
        Returns:
            True if the request should proceed, False if it should fail fast.
        """
        current_state = self.state  # This may trigger OPEN -> HALF_OPEN
        
        with self._lock:
            if current_state == CircuitState.CLOSED:
                return True
            
            if current_state == CircuitState.OPEN:
                return False
            
            if current_state == CircuitState.HALF_OPEN:
                # Allow limited calls in half-open state
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
        
        return False
    
    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            self._stats.total_requests += 1
            self._stats.successful_requests += 1
            self._stats.last_success_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Recovery confirmed, close the circuit
                self._transition_to(CircuitState.CLOSED)
                self._failures.clear()
            elif self._state == CircuitState.CLOSED:
                # Success in closed state, clean up old failures
                self._clean_old_failures()
    
    def record_failure(self, error: Optional[str] = None) -> None:
        """Record a failed request.
        
        Args:
            error: Optional error message for logging
        """
        with self._lock:
            now = time.time()
            self._stats.total_requests += 1
            self._stats.failed_requests += 1
            self._stats.last_failure_time = now
            self._last_failure_time = now
            self._failures.append(now)
            
            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery test, re-open circuit
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                self._clean_old_failures()
                if len(self._failures) >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
    
    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failures.clear()
            self._half_open_calls = 0
    
    def get_status(self) -> Dict:
        """Get current status as a dictionary."""
        with self._lock:
            return {
                "host": self.host,
                "state": self._state.value,
                "failure_count": len(self._failures),
                "failure_threshold": self.failure_threshold,
                "last_failure": self._last_failure_time,
                "time_until_retry": max(
                    0,
                    self.recovery_timeout - (time.time() - self._last_state_change)
                ) if self._state == CircuitState.OPEN else 0,
                "stats": {
                    "total_requests": self._stats.total_requests,
                    "successful_requests": self._stats.successful_requests,
                    "failed_requests": self._stats.failed_requests,
                    "state_changes": self._stats.state_changes,
                },
            }


class CircuitBreakerRegistry:
    """Thread-safe registry of circuit breakers for all hosts.
    
    Provides centralized management and monitoring of host health status.
    """
    
    def __init__(
        self,
        default_failure_threshold: int = 3,
        default_recovery_timeout: float = 600.0,
        default_failure_window: float = 600.0,
    ):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
        self._default_failure_threshold = default_failure_threshold
        self._default_recovery_timeout = default_recovery_timeout
        self._default_failure_window = default_failure_window
    
    def get(self, host: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a host.
        
        Args:
            host: Host identifier (IP address or hostname)
            
        Returns:
            CircuitBreaker for the specified host
        """
        with self._lock:
            if host not in self._breakers:
                self._breakers[host] = CircuitBreaker(
                    host=host,
                    failure_threshold=self._default_failure_threshold,
                    recovery_timeout=self._default_recovery_timeout,
                    failure_window=self._default_failure_window,
                )
            return self._breakers[host]
    
    def get_all_status(self) -> List[Dict]:
        """Get status of all circuit breakers."""
        with self._lock:
            return [breaker.get_status() for breaker in self._breakers.values()]
    
    def get_open_circuits(self) -> List[str]:
        """Get list of hosts with open circuits (unhealthy)."""
        with self._lock:
            return [
                host for host, breaker in self._breakers.items()
                if breaker.state == CircuitState.OPEN
            ]
    
    def get_healthy_hosts(self, hosts: List[str]) -> List[str]:
        """Filter a list of hosts to only include healthy ones.
        
        Args:
            hosts: List of host identifiers to check
            
        Returns:
            List of hosts that are not in OPEN state
        """
        healthy = []
        for host in hosts:
            breaker = self.get(host)
            if breaker.can_execute():
                healthy.append(host)
        return healthy
    
    def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()
    
    def reset_host(self, host: str) -> bool:
        """Reset circuit breaker for a specific host.
        
        Returns:
            True if host was found and reset, False otherwise
        """
        with self._lock:
            if host in self._breakers:
                self._breakers[host].reset()
                return True
            return False
    
    def save_state(self, path: Path) -> None:
        """Save circuit breaker state to a JSON file."""
        state = {
            "timestamp": time.time(),
            "breakers": self.get_all_status(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    
    def summary(self) -> str:
        """Generate a human-readable summary of circuit breaker status."""
        statuses = self.get_all_status()
        if not statuses:
            return "No hosts tracked by circuit breaker."
        
        open_count = sum(1 for s in statuses if s["state"] == "open")
        half_open_count = sum(1 for s in statuses if s["state"] == "half_open")
        closed_count = sum(1 for s in statuses if s["state"] == "closed")
        
        lines = [
            f"**Circuit Breaker Summary** ({len(statuses)} hosts tracked)",
            f"- 🟢 Healthy (closed): {closed_count}",
            f"- 🟡 Testing (half-open): {half_open_count}",
            f"- 🔴 Unhealthy (open): {open_count}",
        ]
        
        if open_count > 0:
            lines.append("\n**Unhealthy Hosts:**")
            for status in statuses:
                if status["state"] == "open":
                    retry_mins = int(status["time_until_retry"] / 60)
                    lines.append(
                        f"- `{status['host']}`: {status['failure_count']} failures, "
                        f"retry in {retry_mins}m"
                    )
        
        return "\n".join(lines)


# Global registry singleton
_registry: Optional[CircuitBreakerRegistry] = None
_registry_lock = threading.Lock()


def get_circuit_breaker_registry(
    failure_threshold: int = 3,
    recovery_timeout: float = 600.0,
    failure_window: float = 600.0,
) -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry.
    
    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds before testing recovery
        failure_window: Rolling window for tracking failures
        
    Returns:
        Global CircuitBreakerRegistry instance
    """
    global _registry
    
    with _registry_lock:
        if _registry is None:
            _registry = CircuitBreakerRegistry(
                default_failure_threshold=failure_threshold,
                default_recovery_timeout=recovery_timeout,
                default_failure_window=failure_window,
            )
        return _registry


def get_circuit_breaker(host: str) -> CircuitBreaker:
    """Convenience function to get a circuit breaker for a host.
    
    Args:
        host: Host identifier (IP or hostname)
        
    Returns:
        CircuitBreaker for the specified host
    """
    return get_circuit_breaker_registry().get(host)
