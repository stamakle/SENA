"""CI/CD Webhook Reporter (Recommendation #17).

This module provides webhook integration for reporting test results
to external systems like Jenkins, GitLab CI, or custom CI/CD pipelines.

Usage:
    from src.domain.webhook_reporter import report_test_result, WebhookConfig
    
    # Configure webhook
    config = WebhookConfig(url="https://ci.example.com/webhook")
    
    # Report a test result
    report_test_result(
        case_id="TC-15174",
        status="passed",
        host="server01",
        config=config,
    )
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path
import hashlib
import hmac


@dataclass
class WebhookConfig:
    """Configuration for webhook reporting."""
    url: str = ""
    secret: str = ""  # For HMAC signing
    timeout_sec: int = 30
    retry_count: int = 3
    headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    
    @classmethod
    def from_env(cls) -> "WebhookConfig":
        """Load configuration from environment variables."""
        return cls(
            url=os.getenv("SENA_WEBHOOK_URL", ""),
            secret=os.getenv("SENA_WEBHOOK_SECRET", ""),
            timeout_sec=int(os.getenv("SENA_WEBHOOK_TIMEOUT", "30")),
            retry_count=int(os.getenv("SENA_WEBHOOK_RETRIES", "3")),
            enabled=os.getenv("SENA_WEBHOOK_ENABLED", "true").lower() in {"true", "1", "yes"},
        )


@dataclass
class TestResult:
    """Represents a test case result for webhook reporting."""
    case_id: str
    status: str  # passed, failed, skipped, error
    host: str = ""
    duration_sec: float = 0.0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error_message: str = ""
    output: str = ""
    artifacts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class WebhookPayload:
    """Complete webhook payload."""
    event_type: str  # test_completed, test_started, batch_completed
    timestamp: str
    source: str = "SENA"
    version: str = "1.0"
    test_result: Optional[TestResult] = None
    batch_results: List[TestResult] = field(default_factory=list)
    session_id: str = ""
    rack: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "version": self.version,
            "session_id": self.session_id,
            "rack": self.rack,
        }
        if self.test_result:
            data["test_result"] = self.test_result.to_dict()
        if self.batch_results:
            data["batch_results"] = [r.to_dict() for r in self.batch_results]
        return data


class WebhookReporter:
    """Sends test results to configured webhook endpoints."""
    
    def __init__(self, config: Optional[WebhookConfig] = None):
        self.config = config or WebhookConfig.from_env()
        self._delivery_log_path = Path(__file__).resolve().parents[2] / "logs" / "webhook_deliveries.jsonl"
    
    def _sign_payload(self, payload: bytes) -> str:
        """Create HMAC signature for payload."""
        if not self.config.secret:
            return ""
        
        signature = hmac.new(
            self.config.secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        return f"sha256={signature}"
    
    def _log_delivery(self, payload: Dict, status: str, response: str = "") -> None:
        """Log webhook delivery attempt."""
        try:
            self._delivery_log_path.parent.mkdir(parents=True, exist_ok=True)
            
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": self.config.url,
                "event_type": payload.get("event_type"),
                "status": status,
                "response": response[:500],  # Truncate long responses
            }
            
            with open(self._delivery_log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass  # Don't fail on logging errors
    
    def send(self, payload: WebhookPayload) -> bool:
        """Send webhook payload to configured endpoint.
        
        Returns:
            True if delivery succeeded, False otherwise.
        """
        if not self.config.enabled or not self.config.url:
            return False
        
        payload_dict = payload.to_dict()
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SENA-Webhook/1.0",
            "X-SENA-Event": payload.event_type,
            **self.config.headers,
        }
        
        # Add signature if secret is configured
        signature = self._sign_payload(payload_bytes)
        if signature:
            headers["X-SENA-Signature"] = signature
        
        last_error = None
        for attempt in range(self.config.retry_count):
            try:
                req = urllib.request.Request(
                    self.config.url,
                    data=payload_bytes,
                    headers=headers,
                    method="POST",
                )
                
                with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                    response_body = resp.read().decode("utf-8")
                    if resp.status in (200, 201, 202, 204):
                        self._log_delivery(payload_dict, "success", response_body)
                        return True
                    else:
                        self._log_delivery(payload_dict, f"failed:{resp.status}", response_body)
                        
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}: {e.reason}"
                self._log_delivery(payload_dict, f"error:{e.code}", str(e))
                
            except urllib.error.URLError as e:
                last_error = str(e.reason)
                self._log_delivery(payload_dict, "error:network", str(e))
                
            except Exception as e:
                last_error = str(e)
                self._log_delivery(payload_dict, "error:unknown", str(e))
        
        return False
    
    def report_test_started(
        self,
        case_id: str,
        host: str = "",
        session_id: str = "",
    ) -> bool:
        """Report that a test has started."""
        
        payload = WebhookPayload(
            event_type="test_started",
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            test_result=TestResult(
                case_id=case_id,
                status="running",
                host=host,
                start_time=datetime.now(timezone.utc).isoformat(),
            ),
        )
        
        return self.send(payload)
    
    def report_test_completed(
        self,
        case_id: str,
        status: str,
        host: str = "",
        duration_sec: float = 0.0,
        error_message: str = "",
        output: str = "",
        artifacts: Optional[List[str]] = None,
        session_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Report that a test has completed."""
        
        payload = WebhookPayload(
            event_type="test_completed",
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            test_result=TestResult(
                case_id=case_id,
                status=status,
                host=host,
                duration_sec=duration_sec,
                end_time=datetime.now(timezone.utc).isoformat(),
                error_message=error_message,
                output=output[:10000] if output else "",  # Truncate large outputs
                artifacts=artifacts or [],
                metadata=metadata or {},
            ),
        )
        
        return self.send(payload)
    
    def report_batch_completed(
        self,
        results: List[TestResult],
        rack: str = "",
        session_id: str = "",
    ) -> bool:
        """Report that a batch of tests has completed."""
        
        payload = WebhookPayload(
            event_type="batch_completed",
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            rack=rack,
            batch_results=results,
        )
        
        return self.send(payload)


# Global reporter instance
_reporter: Optional[WebhookReporter] = None


def get_reporter() -> WebhookReporter:
    """Get the global webhook reporter instance."""
    global _reporter
    if _reporter is None:
        _reporter = WebhookReporter()
    return _reporter


def report_test_result(
    case_id: str,
    status: str,
    host: str = "",
    duration_sec: float = 0.0,
    error_message: str = "",
    output: str = "",
    session_id: str = "",
    **kwargs,
) -> bool:
    """Convenience function to report a test result."""
    return get_reporter().report_test_completed(
        case_id=case_id,
        status=status,
        host=host,
        duration_sec=duration_sec,
        error_message=error_message,
        output=output,
        session_id=session_id,
        metadata=kwargs,
    )
