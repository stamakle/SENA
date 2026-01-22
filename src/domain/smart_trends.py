"""SMART Attribute Trend Analysis (Recommendation #8).

This module provides storage and analysis of SMART data trends over time.
It stores snapshots in a device_state table and can detect drift/degradation
patterns that indicate potential drive failures.

Usage:
    from src.domain.smart_trends import store_smart_snapshot, analyze_smart_trend
    
    # Store a SMART snapshot
    store_smart_snapshot("nvme0n1", smart_data, host="server01")
    
    # Analyze trend for a specific device
    trend = analyze_smart_trend("nvme0n1", hours=24)
    print(trend.temperature_delta)  # +15°C increase
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class SmartSnapshot:
    """A single SMART data snapshot."""
    device: str
    timestamp: datetime
    host: str = ""
    temperature: Optional[int] = None  # Celsius
    power_on_hours: Optional[int] = None
    data_units_read: Optional[int] = None
    data_units_written: Optional[int] = None
    host_read_commands: Optional[int] = None
    host_write_commands: Optional[int] = None
    controller_busy_time: Optional[int] = None
    power_cycles: Optional[int] = None
    unsafe_shutdowns: Optional[int] = None
    media_errors: Optional[int] = None
    error_log_entries: Optional[int] = None
    available_spare: Optional[int] = None  # Percentage
    available_spare_threshold: Optional[int] = None
    percentage_used: Optional[int] = None  # Endurance used
    critical_warning: Optional[int] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrendAnalysis:
    """Analysis of SMART trends over a time period."""
    device: str
    start_time: datetime
    end_time: datetime
    snapshot_count: int
    
    # Temperature trends
    temperature_min: Optional[int] = None
    temperature_max: Optional[int] = None
    temperature_delta: Optional[int] = None  # Change over period
    temperature_avg: Optional[float] = None
    
    # Endurance metrics
    data_written_delta: Optional[int] = None  # In units
    data_read_delta: Optional[int] = None
    percentage_used_delta: Optional[int] = None
    
    # Error trends
    media_errors_delta: int = 0
    error_log_delta: int = 0
    unsafe_shutdowns_delta: int = 0
    
    # Health indicators
    spare_degradation: Optional[int] = None  # Spare decrease
    is_healthy: bool = True
    warnings: List[str] = field(default_factory=list)
    severity: str = "normal"  # normal, warning, critical


def parse_nvme_smart_log(output: str) -> Dict[str, Any]:
    """Parse nvme smart-log output (text or JSON) into structured data.
    
    Handles both JSON format (-o json) and text format output.
    """
    data: Dict[str, Any] = {}
    
    # Try JSON first
    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Parse text format
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("SMART"):
            continue
        
        # Handle "key : value" format
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_").replace("-", "_")
            value = value.strip()
            
            # Extract numeric values
            try:
                # Handle percentage values
                if "%" in value:
                    data[key] = int(value.replace("%", "").strip())
                # Handle temperature with unit
                elif "celsius" in value.lower() or "°c" in value.lower():
                    data[key] = int(value.split()[0])
                # Handle plain numbers
                else:
                    # Try to extract first number
                    parts = value.split()
                    if parts and parts[0].replace(",", "").isdigit():
                        data[key] = int(parts[0].replace(",", ""))
                    else:
                        data[key] = value
            except (ValueError, IndexError):
                data[key] = value
    
    return data


def extract_smart_fields(raw_data: Dict[str, Any]) -> SmartSnapshot:
    """Extract standard SMART fields from parsed data."""
    
    # Field name mappings (various formats)
    temp_keys = ["temperature", "temperature_sensor_1", "composite_temperature", "temp"]
    poh_keys = ["power_on_hours", "power_on_hours_poh", "poh"]
    written_keys = ["data_units_written", "total_data_written", "host_writes"]
    read_keys = ["data_units_read", "total_data_read", "host_reads"]
    media_err_keys = ["media_errors", "media_and_data_integrity_errors"]
    spare_keys = ["available_spare", "avail_spare"]
    used_keys = ["percentage_used", "percent_used", "endurance_used"]
    
    def get_first(keys: List[str]) -> Optional[int]:
        for key in keys:
            val = raw_data.get(key)
            if val is not None:
                if isinstance(val, int):
                    return val
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
        return None
    
    return SmartSnapshot(
        device="",  # Will be set by caller
        timestamp=datetime.now(timezone.utc),
        temperature=get_first(temp_keys),
        power_on_hours=get_first(poh_keys),
        data_units_written=get_first(written_keys),
        data_units_read=get_first(read_keys),
        media_errors=get_first(media_err_keys),
        available_spare=get_first(spare_keys),
        percentage_used=get_first(used_keys),
        error_log_entries=get_first(["num_err_log_entries", "error_log_entries"]),
        unsafe_shutdowns=get_first(["unsafe_shutdowns"]),
        power_cycles=get_first(["power_cycles"]),
        critical_warning=get_first(["critical_warning"]),
        raw_data=raw_data,
    )


class SmartTrendStore:
    """Store and analyze SMART data trends.
    
    Uses a JSON file for persistence (can be upgraded to PostgreSQL).
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        if storage_path is None:
            storage_path = Path(__file__).resolve().parents[2] / "data" / "smart_trends.json"
        self.storage_path = storage_path
        self._ensure_storage()
    
    def _ensure_storage(self) -> None:
        """Ensure storage file exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self.storage_path.write_text("{}")
    
    def _load(self) -> Dict[str, List[Dict]]:
        """Load all snapshots from storage."""
        try:
            return json.loads(self.storage_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _save(self, data: Dict[str, List[Dict]]) -> None:
        """Save all snapshots to storage."""
        self.storage_path.write_text(json.dumps(data, indent=2, default=str))
    
    def store_snapshot(self, device: str, smart_output: str, host: str = "") -> SmartSnapshot:
        """Parse and store a SMART snapshot.
        
        Args:
            device: Device identifier (e.g., "nvme0n1" or "/dev/nvme0n1")
            smart_output: Raw output from nvme smart-log command
            host: Optional host identifier
            
        Returns:
            The stored SmartSnapshot
        """
        # Normalize device name
        device = device.replace("/dev/", "")
        
        # Parse SMART data
        raw_data = parse_nvme_smart_log(smart_output)
        snapshot = extract_smart_fields(raw_data)
        snapshot.device = device
        snapshot.host = host
        snapshot.timestamp = datetime.now(timezone.utc)
        
        # Store
        data = self._load()
        key = f"{host}:{device}" if host else device
        
        if key not in data:
            data[key] = []
        
        # Convert to dict for storage
        snapshot_dict = {
            "device": snapshot.device,
            "host": snapshot.host,
            "timestamp": snapshot.timestamp.isoformat(),
            "temperature": snapshot.temperature,
            "power_on_hours": snapshot.power_on_hours,
            "data_units_written": snapshot.data_units_written,
            "data_units_read": snapshot.data_units_read,
            "media_errors": snapshot.media_errors,
            "available_spare": snapshot.available_spare,
            "percentage_used": snapshot.percentage_used,
            "error_log_entries": snapshot.error_log_entries,
            "unsafe_shutdowns": snapshot.unsafe_shutdowns,
            "power_cycles": snapshot.power_cycles,
            "critical_warning": snapshot.critical_warning,
        }
        
        data[key].append(snapshot_dict)
        
        # Limit history (keep last 1000 snapshots per device)
        if len(data[key]) > 1000:
            data[key] = data[key][-1000:]
        
        self._save(data)
        return snapshot
    
    def get_snapshots(
        self,
        device: str,
        host: str = "",
        hours: int = 24,
    ) -> List[SmartSnapshot]:
        """Get snapshots for a device within the time range."""
        
        device = device.replace("/dev/", "")
        key = f"{host}:{device}" if host else device
        
        data = self._load()
        if key not in data:
            return []
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        snapshots = []
        
        for item in data[key]:
            try:
                ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
                if ts >= cutoff:
                    snapshot = SmartSnapshot(
                        device=item.get("device", device),
                        host=item.get("host", host),
                        timestamp=ts,
                        temperature=item.get("temperature"),
                        power_on_hours=item.get("power_on_hours"),
                        data_units_written=item.get("data_units_written"),
                        data_units_read=item.get("data_units_read"),
                        media_errors=item.get("media_errors"),
                        available_spare=item.get("available_spare"),
                        percentage_used=item.get("percentage_used"),
                        error_log_entries=item.get("error_log_entries"),
                        unsafe_shutdowns=item.get("unsafe_shutdowns"),
                        power_cycles=item.get("power_cycles"),
                        critical_warning=item.get("critical_warning"),
                    )
                    snapshots.append(snapshot)
            except (ValueError, KeyError):
                continue
        
        return sorted(snapshots, key=lambda s: s.timestamp)
    
    def analyze_trend(
        self,
        device: str,
        host: str = "",
        hours: int = 24,
    ) -> TrendAnalysis:
        """Analyze SMART trends for a device.
        
        Args:
            device: Device identifier
            host: Optional host identifier
            hours: Analysis window in hours
            
        Returns:
            TrendAnalysis with detected patterns and warnings
        """
        snapshots = self.get_snapshots(device, host, hours)
        
        now = datetime.now(timezone.utc)
        analysis = TrendAnalysis(
            device=device,
            start_time=now - timedelta(hours=hours),
            end_time=now,
            snapshot_count=len(snapshots),
        )
        
        if len(snapshots) < 2:
            analysis.warnings.append("Insufficient data for trend analysis")
            return analysis
        
        first = snapshots[0]
        last = snapshots[-1]
        
        # Temperature analysis
        temps = [s.temperature for s in snapshots if s.temperature is not None]
        if temps:
            analysis.temperature_min = min(temps)
            analysis.temperature_max = max(temps)
            analysis.temperature_avg = sum(temps) / len(temps)
            if first.temperature and last.temperature:
                analysis.temperature_delta = last.temperature - first.temperature
                
                # Warning: Temperature increase > 10°C
                if analysis.temperature_delta > 10:
                    analysis.warnings.append(
                        f"Temperature increased by {analysis.temperature_delta}°C"
                    )
                    analysis.severity = "warning"
                
                # Critical: Temperature > 70°C
                if analysis.temperature_max > 70:
                    analysis.warnings.append(
                        f"Critical temperature: {analysis.temperature_max}°C"
                    )
                    analysis.severity = "critical"
        
        # Media errors
        if first.media_errors is not None and last.media_errors is not None:
            analysis.media_errors_delta = last.media_errors - first.media_errors
            if analysis.media_errors_delta > 0:
                analysis.warnings.append(
                    f"New media errors: {analysis.media_errors_delta}"
                )
                analysis.severity = "critical"
                analysis.is_healthy = False
        
        # Error log entries
        if first.error_log_entries is not None and last.error_log_entries is not None:
            analysis.error_log_delta = last.error_log_entries - first.error_log_entries
            if analysis.error_log_delta > 5:
                analysis.warnings.append(
                    f"Error log increased by {analysis.error_log_delta} entries"
                )
                if analysis.severity != "critical":
                    analysis.severity = "warning"
        
        # Unsafe shutdowns
        if first.unsafe_shutdowns is not None and last.unsafe_shutdowns is not None:
            analysis.unsafe_shutdowns_delta = last.unsafe_shutdowns - first.unsafe_shutdowns
            if analysis.unsafe_shutdowns_delta > 0:
                analysis.warnings.append(
                    f"Unsafe shutdowns: {analysis.unsafe_shutdowns_delta}"
                )
        
        # Available spare
        if first.available_spare is not None and last.available_spare is not None:
            analysis.spare_degradation = first.available_spare - last.available_spare
            if analysis.spare_degradation > 5:
                analysis.warnings.append(
                    f"Available spare decreased by {analysis.spare_degradation}%"
                )
                if analysis.severity != "critical":
                    analysis.severity = "warning"
            if last.available_spare < 10:
                analysis.warnings.append(
                    f"Available spare critically low: {last.available_spare}%"
                )
                analysis.severity = "critical"
                analysis.is_healthy = False
        
        # Percentage used (endurance)
        if first.percentage_used is not None and last.percentage_used is not None:
            analysis.percentage_used_delta = last.percentage_used - first.percentage_used
            if last.percentage_used > 90:
                analysis.warnings.append(
                    f"Endurance nearly exhausted: {last.percentage_used}% used"
                )
                analysis.severity = "critical"
                analysis.is_healthy = False
        
        # Data written
        if first.data_units_written is not None and last.data_units_written is not None:
            analysis.data_written_delta = last.data_units_written - first.data_units_written
        
        return analysis


def format_trend_report(analysis: TrendAnalysis) -> str:
    """Format a trend analysis as a human-readable report."""
    
    severity_icons = {
        "normal": "✅",
        "warning": "⚠️",
        "critical": "🔴",
    }
    
    icon = severity_icons.get(analysis.severity, "❓")
    lines = [
        f"## {icon} SMART Trend Analysis: {analysis.device}",
        "",
        f"**Period:** {analysis.start_time.strftime('%Y-%m-%d %H:%M')} to {analysis.end_time.strftime('%Y-%m-%d %H:%M')}",
        f"**Snapshots:** {analysis.snapshot_count}",
        f"**Health Status:** {'Healthy' if analysis.is_healthy else 'DEGRADED'}",
        "",
    ]
    
    # Temperature section
    if analysis.temperature_avg is not None:
        lines.append("### Temperature")
        lines.append(f"- Average: {analysis.temperature_avg:.1f}°C")
        lines.append(f"- Range: {analysis.temperature_min}°C - {analysis.temperature_max}°C")
        if analysis.temperature_delta:
            direction = "↑" if analysis.temperature_delta > 0 else "↓"
            lines.append(f"- Change: {direction} {abs(analysis.temperature_delta)}°C")
        lines.append("")
    
    # Errors section
    if analysis.media_errors_delta or analysis.error_log_delta or analysis.unsafe_shutdowns_delta:
        lines.append("### Errors")
        if analysis.media_errors_delta:
            lines.append(f"- Media Errors: +{analysis.media_errors_delta}")
        if analysis.error_log_delta:
            lines.append(f"- Error Log Entries: +{analysis.error_log_delta}")
        if analysis.unsafe_shutdowns_delta:
            lines.append(f"- Unsafe Shutdowns: +{analysis.unsafe_shutdowns_delta}")
        lines.append("")
    
    # Warnings
    if analysis.warnings:
        lines.append("### ⚠️ Warnings")
        for warning in analysis.warnings:
            lines.append(f"- {warning}")
        lines.append("")
    
    return "\n".join(lines)


# Convenience functions
_default_store: Optional[SmartTrendStore] = None


def get_store() -> SmartTrendStore:
    """Get the default trend store singleton."""
    global _default_store
    if _default_store is None:
        _default_store = SmartTrendStore()
    return _default_store


def store_smart_snapshot(device: str, smart_output: str, host: str = "") -> SmartSnapshot:
    """Store a SMART snapshot (convenience function)."""
    return get_store().store_snapshot(device, smart_output, host)


def analyze_smart_trend(device: str, host: str = "", hours: int = 24) -> TrendAnalysis:
    """Analyze SMART trends (convenience function)."""
    return get_store().analyze_trend(device, host, hours)
