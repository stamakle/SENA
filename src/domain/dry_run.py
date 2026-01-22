"""Dry-Run Preview for Destructive Operations (Recommendation #12).

This module provides safety controls for destructive NVMe and disk operations.
It implements a preview mode that shows exactly what would happen before
execution, requiring explicit user confirmation for dangerous commands.

Usage:
    from src.domain.dry_run import check_command_safety, CommandSafetyResult
    
    result = check_command_safety("nvme format /dev/nvme0n1")
    if result.is_destructive:
        print(result.preview)
        if not user_confirms():
            return "Operation cancelled"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class RiskLevel(Enum):
    """Risk classification for commands."""
    SAFE = "safe"               # Read-only operations
    LOW = "low"                 # Minor modifications, easily reversible
    MEDIUM = "medium"           # Significant changes, may require recovery
    HIGH = "high"               # Destructive, data loss possible
    CRITICAL = "critical"       # Irreversible data destruction


@dataclass
class CommandSafetyResult:
    """Result of command safety analysis."""
    command: str
    is_destructive: bool
    risk_level: RiskLevel
    matched_patterns: List[str]
    affected_devices: List[str]
    preview: str
    requires_confirmation: bool
    suggested_dry_run: Optional[str]
    warnings: List[str]


# Destructive command patterns with their risk levels
DESTRUCTIVE_PATTERNS: Dict[str, Tuple[RiskLevel, str]] = {
    # NVMe destructive commands
    r"\bnvme\s+format\b": (
        RiskLevel.CRITICAL,
        "NVMe Format: Erases all data on the namespace. Irreversible."
    ),
    r"\bnvme\s+sanitize\b": (
        RiskLevel.CRITICAL,
        "NVMe Sanitize: Cryptographically erases all data. Irreversible."
    ),
    r"\bnvme\s+write-zeroes\b": (
        RiskLevel.HIGH,
        "Write Zeroes: Overwrites specified LBA range with zeros."
    ),
    r"\bnvme\s+write\b": (
        RiskLevel.HIGH,
        "NVMe Write: Writes data to specified LBAs. Data at those LBAs will be overwritten."
    ),
    r"\bnvme\s+security-erase\b": (
        RiskLevel.CRITICAL,
        "Security Erase: Performs ATA secure erase. All data destroyed."
    ),
    r"\bnvme\s+ns-delete\b": (
        RiskLevel.CRITICAL,
        "Namespace Delete: Removes the namespace and all its data."
    ),
    r"\bnvme\s+reset\b": (
        RiskLevel.MEDIUM,
        "NVMe Reset: Resets the controller. In-flight I/O may be lost."
    ),
    r"\bnvme\s+subsystem-reset\b": (
        RiskLevel.MEDIUM,
        "Subsystem Reset: Resets entire NVMe subsystem. All I/O interrupted."
    ),
    
    # Disk utilities
    r"\bblkdiscard\b": (
        RiskLevel.CRITICAL,
        "blkdiscard: Discards all data on the block device. Irreversible."
    ),
    r"\bfstrim\b": (
        RiskLevel.MEDIUM,
        "fstrim: Sends TRIM to free blocks. Generally safe but affects data layout."
    ),
    r"\bmkfs\b": (
        RiskLevel.CRITICAL,
        "mkfs: Creates new filesystem. Destroys existing filesystem and data."
    ),
    r"\bmkfs\.\w+": (
        RiskLevel.CRITICAL,
        "mkfs: Creates new filesystem. Destroys existing filesystem and data."
    ),
    r"\bfdisk\b": (
        RiskLevel.CRITICAL,
        "fdisk: Modifies partition table. Can destroy all partitions."
    ),
    r"\bparted\b": (
        RiskLevel.CRITICAL,
        "parted: Modifies partition table. Can destroy partitions."
    ),
    r"\bgdisk\b": (
        RiskLevel.CRITICAL,
        "gdisk: Modifies GPT partition table. Can destroy partitions."
    ),
    r"\bcfdisk\b": (
        RiskLevel.CRITICAL,
        "cfdisk: Modifies partition table interactively."
    ),
    r"\bsfdisk\b": (
        RiskLevel.CRITICAL,
        "sfdisk: Modifies partition table. Script-driven."
    ),
    
    # Data destruction tools
    r"\bdd\s+if=": (
        RiskLevel.CRITICAL,
        "dd: Direct disk write. Will overwrite target device/file."
    ),
    r"\bshred\b": (
        RiskLevel.CRITICAL,
        "shred: Securely overwrites files/devices. Irreversible."
    ),
    r"\bwipe\b": (
        RiskLevel.CRITICAL,
        "wipe: Securely erases files. Irreversible."
    ),
    r"\bsecure-delete\b": (
        RiskLevel.CRITICAL,
        "secure-delete: Securely erases data. Irreversible."
    ),
    r"\bsrm\b": (
        RiskLevel.CRITICAL,
        "srm: Secure remove. Overwrites before deletion."
    ),
    
    # Dangerous rm patterns
    r"\brm\s+(-[rfRF]+\s+)*(/|/dev|/sys|/proc|/boot)": (
        RiskLevel.CRITICAL,
        "rm on system path: Could destroy system files."
    ),
    r"\brm\s+-rf\s+/": (
        RiskLevel.CRITICAL,
        "rm -rf /: Would destroy entire filesystem. EXTREMELY DANGEROUS."
    ),
    
    # Firmware operations
    r"\bnvme\s+fw-download\b": (
        RiskLevel.HIGH,
        "Firmware Download: Uploads firmware image to drive."
    ),
    r"\bnvme\s+fw-commit\b": (
        RiskLevel.HIGH,
        "Firmware Commit: Activates downloaded firmware. May brick drive if wrong."
    ),
    r"\bnvme\s+fw-activate\b": (
        RiskLevel.HIGH,
        "Firmware Activate: Activates firmware slot. May brick drive if wrong."
    ),
    
    # hdparm danger zone
    r"\bhdparm\s+.*--security-erase": (
        RiskLevel.CRITICAL,
        "hdparm security-erase: ATA secure erase. All data destroyed."
    ),
    r"\bhdparm\s+.*--security-set-pass": (
        RiskLevel.HIGH,
        "hdparm: Sets ATA password. Drive may become locked."
    ),
    r"\bhdparm\s+.*--dco-restore": (
        RiskLevel.HIGH,
        "hdparm DCO restore: Modifies drive configuration overlay."
    ),
    
    # SCSI/SG dangerous
    r"\bsg_format\b": (
        RiskLevel.CRITICAL,
        "sg_format: Low-level SCSI format. Destroys all data."
    ),
    r"\bsg_sanitize\b": (
        RiskLevel.CRITICAL,
        "sg_sanitize: SCSI sanitize. Destroys all data."
    ),
}

# Commands that are always safe (read-only)
SAFE_PATTERNS: Set[str] = {
    r"\bnvme\s+list\b",
    r"\bnvme\s+smart-log\b",
    r"\bnvme\s+error-log\b",
    r"\bnvme\s+id-ctrl\b",
    r"\bnvme\s+id-ns\b",
    r"\bnvme\s+list-ns\b",
    r"\bnvme\s+fw-log\b",
    r"\bnvme\s+get-feature\b",
    r"\bnvme\s+show-regs\b",
    r"\bnvme\s+version\b",
    r"\blsblk\b",
    r"\blspci\b",
    r"\bcat\s+/sys/",
    r"\bcat\s+/proc/",
    r"\bdmesg\b",
    r"\buname\b",
    r"\bhostname\b",
    r"\bdf\b",
    r"\bdu\b",
    r"\bfree\b",
    r"\btop\b",
    r"\bps\b",
    r"\buptime\b",
    r"\bsmartctl\s+-[aAilH]",  # smartctl read operations
}

# Device path patterns
DEVICE_PATTERNS: List[str] = [
    r"/dev/nvme\d+n?\d*",      # NVMe devices
    r"/dev/sd[a-z]+\d*",       # SATA/SAS devices
    r"/dev/hd[a-z]+\d*",       # Old IDE devices
    r"/dev/vd[a-z]+\d*",       # Virtual devices
    r"/dev/loop\d+",           # Loop devices
    r"/dev/md\d+",             # RAID devices
    r"/dev/dm-\d+",            # Device mapper
    r"/dev/mapper/\S+",        # LVM devices
]


def _extract_devices(command: str) -> List[str]:
    """Extract device paths from a command string."""
    devices: List[str] = []
    for pattern in DEVICE_PATTERNS:
        matches = re.findall(pattern, command)
        devices.extend(matches)
    return list(set(devices))


def _is_safe_command(command: str) -> bool:
    """Check if command matches known safe patterns."""
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def check_command_safety(command: str) -> CommandSafetyResult:
    """Analyze a command for destructive operations.
    
    Args:
        command: The shell command to analyze
        
    Returns:
        CommandSafetyResult with safety analysis
    """
    command = command.strip()
    matched_patterns: List[str] = []
    warnings: List[str] = []
    max_risk = RiskLevel.SAFE
    
    # Check for safe commands first
    if _is_safe_command(command):
        return CommandSafetyResult(
            command=command,
            is_destructive=False,
            risk_level=RiskLevel.SAFE,
            matched_patterns=[],
            affected_devices=_extract_devices(command),
            preview="✅ This is a read-only command. Safe to execute.",
            requires_confirmation=False,
            suggested_dry_run=None,
            warnings=[],
        )
    
    # Check for destructive patterns
    for pattern, (risk, description) in DESTRUCTIVE_PATTERNS.items():
        if re.search(pattern, command, re.IGNORECASE):
            matched_patterns.append(description)
            if risk.value > max_risk.value:
                max_risk = risk
    
    # Extract affected devices
    affected_devices = _extract_devices(command)
    
    # Check for sudo without specific device
    if "sudo" in command and not affected_devices and max_risk != RiskLevel.SAFE:
        warnings.append("Command uses sudo but no specific device detected. Verify target carefully.")
    
    # Check for wildcards with destructive commands
    if "*" in command and max_risk.value >= RiskLevel.HIGH.value:
        warnings.append("Wildcard detected in destructive command. Could affect multiple targets.")
    
    # Generate preview
    is_destructive = max_risk.value >= RiskLevel.HIGH.value
    preview_lines: List[str] = []
    
    if is_destructive:
        preview_lines.append(f"⚠️ **DESTRUCTIVE OPERATION DETECTED**")
        preview_lines.append(f"")
        preview_lines.append(f"**Command:** `{command}`")
        preview_lines.append(f"**Risk Level:** {max_risk.value.upper()}")
        preview_lines.append(f"")
        
        if affected_devices:
            preview_lines.append(f"**Affected Devices:**")
            for dev in affected_devices:
                preview_lines.append(f"  - `{dev}`")
            preview_lines.append("")
        
        if matched_patterns:
            preview_lines.append(f"**Detected Operations:**")
            for pattern in matched_patterns:
                preview_lines.append(f"  ⛔ {pattern}")
            preview_lines.append("")
        
        if warnings:
            preview_lines.append(f"**Warnings:**")
            for warning in warnings:
                preview_lines.append(f"  ⚠️ {warning}")
            preview_lines.append("")
        
        preview_lines.append("**This operation may result in permanent data loss.**")
        preview_lines.append("Type 'CONFIRM' to proceed or 'CANCEL' to abort.")
    else:
        if matched_patterns:
            preview_lines.append(f"⚠️ **Potentially Risky Command**")
            preview_lines.append(f"")
            preview_lines.append(f"**Command:** `{command}`")
            preview_lines.append(f"**Risk Level:** {max_risk.value.upper()}")
            for pattern in matched_patterns:
                preview_lines.append(f"  • {pattern}")
        else:
            preview_lines.append(f"Command appears safe but is not in the known-safe list.")
            preview_lines.append(f"Please review before executing.")
    
    # Suggest dry-run alternatives
    suggested_dry_run = None
    if "nvme format" in command.lower():
        suggested_dry_run = command + " --dry-run"  # if supported
    elif "dd" in command.lower():
        suggested_dry_run = "echo 'Would run: " + command + "'"
    elif "rm" in command.lower():
        suggested_dry_run = command.replace("rm ", "rm -i ", 1)
    
    return CommandSafetyResult(
        command=command,
        is_destructive=is_destructive,
        risk_level=max_risk,
        matched_patterns=matched_patterns,
        affected_devices=affected_devices,
        preview="\n".join(preview_lines),
        requires_confirmation=is_destructive,
        suggested_dry_run=suggested_dry_run,
        warnings=warnings,
    )


def get_safe_alternatives(command: str) -> List[str]:
    """Suggest safer alternatives to a destructive command.
    
    Args:
        command: The potentially destructive command
        
    Returns:
        List of safer alternative commands
    """
    alternatives: List[str] = []
    command_lower = command.lower()
    
    # Extract device if present
    devices = _extract_devices(command)
    device = devices[0] if devices else "/dev/nvmeXnY"
    
    if "nvme format" in command_lower:
        alternatives.extend([
            f"# Check namespace info first:",
            f"nvme id-ns {device}",
            f"",
            f"# List all namespaces to confirm target:",
            f"nvme list",
            f"",
            f"# Verify no filesystems mounted:",
            f"lsblk -f {device}",
            f"mount | grep {device}",
        ])
    
    elif "blkdiscard" in command_lower:
        alternatives.extend([
            f"# Check device info first:",
            f"lsblk -o NAME,SIZE,MOUNTPOINT,FSTYPE {device}",
            f"",
            f"# Verify device is not mounted:",
            f"mount | grep {device}",
            f"",
            f"# Check TRIM support:",
            f"cat /sys/block/$(basename {device})/queue/discard_max_bytes",
        ])
    
    elif "mkfs" in command_lower:
        alternatives.extend([
            f"# Check current filesystem:",
            f"blkid {device}",
            f"",
            f"# List partition table:",
            f"fdisk -l {device}",
            f"",
            f"# Verify unmounted:",
            f"mount | grep {device}",
        ])
    
    elif "dd" in command_lower:
        alternatives.extend([
            f"# Verify source and destination:",
            f"ls -la <source_file>",
            f"lsblk -o NAME,SIZE,TYPE {device}",
            f"",
            f"# Dry-run (echo only):",
            f"echo \"Would run: {command}\"",
        ])
    
    elif "fw-download" in command_lower or "fw-commit" in command_lower:
        alternatives.extend([
            f"# Check current firmware:",
            f"nvme fw-log {device}",
            f"",
            f"# Get controller info:",
            f"nvme id-ctrl {device}",
            f"",
            f"# Verify firmware file:",
            f"file <firmware_file>",
        ])
    
    return alternatives


def format_confirmation_prompt(result: CommandSafetyResult) -> str:
    """Format a confirmation prompt for destructive operations.
    
    Args:
        result: CommandSafetyResult from check_command_safety
        
    Returns:
        Formatted prompt string for user confirmation
    """
    if not result.requires_confirmation:
        return ""
    
    lines = [
        "=" * 60,
        "⚠️  DESTRUCTIVE OPERATION - CONFIRMATION REQUIRED  ⚠️",
        "=" * 60,
        "",
        result.preview,
        "",
        "=" * 60,
        "",
    ]
    
    alternatives = get_safe_alternatives(result.command)
    if alternatives:
        lines.append("**Recommended steps before proceeding:**")
        lines.append("```bash")
        lines.extend(alternatives)
        lines.append("```")
        lines.append("")
    
    lines.extend([
        "To proceed with this destructive operation, respond with:",
        "  `CONFIRM` - Execute the command",
        "  `CANCEL` - Abort the operation",
        "",
    ])
    
    return "\n".join(lines)
