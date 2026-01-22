"""Rate-Limited Parallel SSH Execution (Recommendation #16).

This module provides a semaphore-controlled SSH executor for parallel
command execution across multiple hosts while respecting connection limits.

Usage:
    from src.domain.parallel_ssh import ParallelSSHExecutor
    
    executor = ParallelSSHExecutor(max_concurrent=4)
    results = executor.execute_on_hosts(
        hosts=["host1", "host2", "host3"],
        command="nvme list",
    )
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
from queue import Queue
import os


@dataclass
class SSHResult:
    """Result of a single SSH command execution."""
    host: str
    command: str
    output: str = ""
    error: str = ""
    exit_code: int = 0
    duration_sec: float = 0.0
    success: bool = True
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class BatchResult:
    """Result of batch SSH execution across multiple hosts."""
    command: str
    results: List[SSHResult] = field(default_factory=list)
    total_hosts: int = 0
    successful_hosts: int = 0
    failed_hosts: int = 0
    skipped_hosts: int = 0
    total_duration_sec: float = 0.0
    
    def summary(self) -> str:
        """Generate a summary of batch execution."""
        lines = [
            f"**Batch SSH Execution Summary**",
            f"- Command: `{self.command}`",
            f"- Total Hosts: {self.total_hosts}",
            f"- Successful: {self.successful_hosts} ✅",
            f"- Failed: {self.failed_hosts} ❌",
            f"- Skipped: {self.skipped_hosts} ⏭️",
            f"- Duration: {self.total_duration_sec:.2f}s",
        ]
        return "\n".join(lines)


class RateLimiter:
    """Token bucket rate limiter for SSH connections."""
    
    def __init__(self, rate: float = 10.0, burst: int = 5):
        """Initialize rate limiter.
        
        Args:
            rate: Connections allowed per second
            burst: Maximum burst size
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
        self._lock = threading.Lock()
    
    def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire a token (blocking).
        
        Returns:
            True if token acquired, False if timeout
        """
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            with self._lock:
                now = time.time()
                # Add tokens based on elapsed time
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now
                
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            
            # Wait a bit before retrying
            time.sleep(0.1)
        
        return False


class ParallelSSHExecutor:
    """Execute SSH commands in parallel with rate limiting.
    
    Features:
    - Configurable concurrency limit
    - Rate limiting to prevent connection storms
    - Circuit breaker integration
    - Progress callbacks
    """
    
    def __init__(
        self,
        max_concurrent: int = 4,
        rate_limit: float = 10.0,
        connection_timeout_sec: int = 30,
        command_timeout_sec: int = 60,
    ):
        """Initialize the executor.
        
        Args:
            max_concurrent: Maximum concurrent SSH connections
            rate_limit: Connections per second limit
            connection_timeout_sec: Connection timeout
            command_timeout_sec: Command execution timeout
        """
        self.max_concurrent = max_concurrent
        self.connection_timeout = connection_timeout_sec
        self.command_timeout = command_timeout_sec
        self.rate_limiter = RateLimiter(rate=rate_limit, burst=max_concurrent)
        self._semaphore = threading.Semaphore(max_concurrent)
        
    def _execute_single(
        self,
        host: str,
        command: str,
        ssh_config_path: str,
        ssh_func: Callable,
        circuit_check: Optional[Callable] = None,
    ) -> SSHResult:
        """Execute command on a single host with rate limiting."""
        
        start_time = time.time()
        
        # Check circuit breaker if provided
        if circuit_check and not circuit_check(host):
            return SSHResult(
                host=host,
                command=command,
                skipped=True,
                skip_reason="Circuit breaker open",
                success=False,
            )
        
        # Acquire rate limit token
        if not self.rate_limiter.acquire(timeout=30.0):
            return SSHResult(
                host=host,
                command=command,
                error="Rate limit timeout",
                success=False,
            )
        
        # Acquire concurrency semaphore
        acquired = self._semaphore.acquire(timeout=self.connection_timeout)
        if not acquired:
            return SSHResult(
                host=host,
                command=command,
                error="Concurrency limit timeout",
                success=False,
            )
        
        try:
            # Execute SSH command
            result = ssh_func(
                host,
                command,
                ssh_config_path,
                timeout_sec=self.command_timeout,
            )
            duration = time.time() - start_time
            stdout = getattr(result, "stdout", result)
            stderr = getattr(result, "stderr", "")
            exit_code = getattr(result, "exit_code", 0)
            return SSHResult(
                host=host,
                command=command,
                output=stdout or "",
                error=stderr or "",
                exit_code=exit_code or 0,
                duration_sec=duration,
                success=exit_code == 0,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return SSHResult(
                host=host,
                command=command,
                error=str(e),
                duration_sec=duration,
                success=False,
            )
        finally:
            self._semaphore.release()
    
    def execute_on_hosts(
        self,
        hosts: List[str],
        command: str,
        ssh_config_path: str,
        ssh_func: Optional[Callable] = None,
        circuit_check: Optional[Callable] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchResult:
        """Execute command on multiple hosts in parallel.
        
        Args:
            hosts: List of host identifiers
            command: Command to execute
            ssh_config_path: Path to SSH config
            ssh_func: SSH execution function (default: run_ssh_command)
            circuit_check: Optional function to check circuit breaker
            progress_callback: Optional callback(completed, total) for progress
            
        Returns:
            BatchResult with all execution results
        """
        if ssh_func is None:
            from src.tools.ssh_client import run_ssh_command
            ssh_func = run_ssh_command
        
        start_time = time.time()
        results: List[SSHResult] = []
        completed = 0
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures: Dict[Future, str] = {}
            
            for host in hosts:
                future = executor.submit(
                    self._execute_single,
                    host,
                    command,
                    ssh_config_path,
                    ssh_func,
                    circuit_check,
                )
                futures[future] = host
            
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                completed += 1
                
                if progress_callback:
                    progress_callback(completed, len(hosts))
        
        total_duration = time.time() - start_time
        
        # Calculate statistics
        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success and not r.skipped)
        skipped = sum(1 for r in results if r.skipped)
        
        return BatchResult(
            command=command,
            results=results,
            total_hosts=len(hosts),
            successful_hosts=successful,
            failed_hosts=failed,
            skipped_hosts=skipped,
            total_duration_sec=total_duration,
        )
    
    def execute_pipeline(
        self,
        hosts: List[str],
        commands: List[str],
        ssh_config_path: str,
        ssh_func: Optional[Callable] = None,
        stop_on_error: bool = False,
    ) -> List[BatchResult]:
        """Execute a pipeline of commands on hosts.
        
        Args:
            hosts: List of hosts
            commands: List of commands to execute in sequence
            ssh_config_path: SSH config path
            ssh_func: SSH execution function
            stop_on_error: Stop pipeline if any command fails
            
        Returns:
            List of BatchResults, one per command
        """
        all_results: List[BatchResult] = []
        
        for command in commands:
            result = self.execute_on_hosts(
                hosts=hosts,
                command=command,
                ssh_config_path=ssh_config_path,
                ssh_func=ssh_func,
            )
            all_results.append(result)
            
            if stop_on_error and result.failed_hosts > 0:
                break
        
        return all_results


# Default executor singleton
_executor: Optional[ParallelSSHExecutor] = None


def get_executor(
    max_concurrent: Optional[int] = None,
) -> ParallelSSHExecutor:
    """Get the default parallel SSH executor.
    
    Args:
        max_concurrent: Override default concurrency (from env or 4)
    """
    global _executor
    
    if _executor is None or max_concurrent is not None:
        concurrent = max_concurrent or int(os.getenv("SENA_SSH_MAX_CONCURRENT", "4"))
        rate_limit = float(os.getenv("SENA_SSH_RATE_LIMIT", "10.0"))
        _executor = ParallelSSHExecutor(
            max_concurrent=concurrent,
            rate_limit=rate_limit,
        )
    
    return _executor


def execute_parallel(
    hosts: List[str],
    command: str,
    ssh_config_path: str,
    max_concurrent: int = 4,
) -> BatchResult:
    """Convenience function for parallel SSH execution."""
    executor = get_executor(max_concurrent)
    return executor.execute_on_hosts(hosts, command, ssh_config_path)
