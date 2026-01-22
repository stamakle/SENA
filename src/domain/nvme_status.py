"""NVMe Status Code Lookup Table (Recommendation #7).

This module provides comprehensive NVMe error code interpretation based on
NVMe Base Specification 2.0. Status codes are returned in bits 17:01 of the
Completion Queue Entry DW3.

Usage:
    from src.domain.nvme_status import lookup_status_code, interpret_nvme_output
    
    # Lookup a specific status code
    result = lookup_status_code(0x02)
    print(result)  # {'code': 0x02, 'name': 'Invalid Field', ...}
    
    # Interpret raw command output for status codes
    interpretation = interpret_nvme_output("status: 0x4002")
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
import re


# NVMe Generic Command Status (Figure 126 in NVMe Spec)
GENERIC_STATUS: Dict[int, Dict[str, str]] = {
    0x00: {
        "name": "Successful Completion",
        "description": "The command completed without error.",
        "severity": "info",
        "action": "None required",
    },
    0x01: {
        "name": "Invalid Command Opcode",
        "description": "The command opcode is invalid or not supported.",
        "severity": "error",
        "action": "Verify the command opcode is valid for this controller/namespace.",
    },
    0x02: {
        "name": "Invalid Field in Command",
        "description": "A reserved bit or an invalid combination of fields was set.",
        "severity": "error",
        "action": "Check command parameters and flags. Ensure namespace exists.",
    },
    0x03: {
        "name": "Command ID Conflict",
        "description": "The command identifier is already in use.",
        "severity": "error",
        "action": "Internal driver error. Restart nvme driver or reboot host.",
    },
    0x04: {
        "name": "Data Transfer Error",
        "description": "An error occurred during data transfer (PRP/SGL).",
        "severity": "error",
        "action": "Check PCIe link stability. Run lspci to verify link speed/width.",
    },
    0x05: {
        "name": "Commands Aborted due to Power Loss Notification",
        "description": "Commands were aborted due to power loss.",
        "severity": "critical",
        "action": "Check power supply and UPS status. Verify PLI capacitor health.",
    },
    0x06: {
        "name": "Internal Error",
        "description": "The controller experienced an internal error.",
        "severity": "critical",
        "action": "Collect firmware logs. Escalate to vendor. Consider drive replacement.",
    },
    0x07: {
        "name": "Command Abort Requested",
        "description": "The command was aborted by an Abort command.",
        "severity": "warning",
        "action": "Normal behavior if abort was intentional. Check for timeout issues.",
    },
    0x08: {
        "name": "Command Aborted due to SQ Deletion",
        "description": "The command was aborted due to deletion of the Submission Queue.",
        "severity": "warning",
        "action": "Normal during controller reset. Check for unexpected queue deletion.",
    },
    0x09: {
        "name": "Command Aborted due to Failed Fused Command",
        "description": "The fused command sequence failed.",
        "severity": "error",
        "action": "Check both fused commands. Verify atomicity requirements.",
    },
    0x0A: {
        "name": "Command Aborted due to Missing Fused Command",
        "description": "The second command in a fused operation was not received.",
        "severity": "error",
        "action": "Ensure both fused commands are submitted together.",
    },
    0x0B: {
        "name": "Invalid Namespace or Format",
        "description": "The namespace ID or format is invalid.",
        "severity": "error",
        "action": "Verify namespace exists: nvme list-ns /dev/nvmeX",
    },
    0x0C: {
        "name": "Command Sequence Error",
        "description": "Commands were submitted in the wrong sequence.",
        "severity": "error",
        "action": "Check command ordering. Some commands require prior configuration.",
    },
    0x0D: {
        "name": "Invalid SGL Segment Descriptor",
        "description": "SGL segment descriptor is invalid.",
        "severity": "error",
        "action": "Driver/kernel bug. Update nvme driver. Check kernel version.",
    },
    0x0E: {
        "name": "Invalid Number of SGL Descriptors",
        "description": "The number of SGL descriptors is invalid.",
        "severity": "error",
        "action": "Driver/kernel bug. Update nvme driver.",
    },
    0x0F: {
        "name": "Data SGL Length Invalid",
        "description": "The data SGL length is invalid for the command.",
        "severity": "error",
        "action": "Check transfer size alignment. Verify LBA format.",
    },
    0x10: {
        "name": "Metadata SGL Length Invalid",
        "description": "The metadata SGL length is invalid.",
        "severity": "error",
        "action": "Check metadata size matches namespace format.",
    },
    0x11: {
        "name": "SGL Descriptor Type Invalid",
        "description": "The SGL descriptor type is not supported.",
        "severity": "error",
        "action": "Verify controller SGL capabilities: nvme id-ctrl -H",
    },
    0x12: {
        "name": "Invalid Use of Controller Memory Buffer",
        "description": "CMB usage is invalid for this command.",
        "severity": "error",
        "action": "Check CMB configuration. Not all commands support CMB.",
    },
    0x13: {
        "name": "PRP Offset Invalid",
        "description": "The PRP offset is invalid.",
        "severity": "error",
        "action": "Memory alignment issue. Check driver/kernel.",
    },
    0x14: {
        "name": "Atomic Write Unit Exceeded",
        "description": "The write operation exceeds atomic write unit limits.",
        "severity": "error",
        "action": "Reduce I/O size. Check AWUN/AWUPF values: nvme id-ns",
    },
    0x15: {
        "name": "Operation Denied",
        "description": "The operation was denied due to lock or reservation.",
        "severity": "warning",
        "action": "Check namespace reservations. Another host may hold lock.",
    },
    0x16: {
        "name": "SGL Offset Invalid",
        "description": "The starting offset in SGL is invalid.",
        "severity": "error",
        "action": "Driver bug. Update nvme driver.",
    },
    0x17: {
        "name": "Reserved",
        "description": "Reserved status code.",
        "severity": "unknown",
        "action": "Unexpected code. Check NVMe spec version.",
    },
    0x18: {
        "name": "Host Identifier Inconsistent Format",
        "description": "Host identifier format is inconsistent.",
        "severity": "error",
        "action": "Check host identifier configuration.",
    },
    0x19: {
        "name": "Keep Alive Timer Expired",
        "description": "The keep alive timer expired on a persistent connection.",
        "severity": "warning",
        "action": "Increase keep alive timeout or check network stability (NVMe-oF).",
    },
    0x1A: {
        "name": "Keep Alive Timeout Invalid",
        "description": "The keep alive timeout value is invalid.",
        "severity": "error",
        "action": "Check keep alive configuration value.",
    },
    0x1B: {
        "name": "Command Aborted due to Preempt and Abort",
        "description": "Command aborted due to reservation preempt.",
        "severity": "warning",
        "action": "Normal if reservation change was intentional.",
    },
    0x1C: {
        "name": "Sanitize Failed",
        "description": "The sanitize operation failed.",
        "severity": "critical",
        "action": "Check sanitize log: nvme sanitize-log. Drive may need replacement.",
    },
    0x1D: {
        "name": "Sanitize In Progress",
        "description": "A sanitize operation is currently in progress.",
        "severity": "info",
        "action": "Wait for sanitize to complete. Check progress: nvme sanitize-log",
    },
    0x1E: {
        "name": "SGL Data Block Granularity Invalid",
        "description": "SGL data block granularity is invalid.",
        "severity": "error",
        "action": "Check SGLS capability: nvme id-ctrl",
    },
    0x1F: {
        "name": "Command Not Supported for Queue in CMB",
        "description": "Command not supported when queue is in CMB.",
        "severity": "error",
        "action": "Use different queue or disable CMB for this queue.",
    },
    0x20: {
        "name": "Namespace is Write Protected",
        "description": "Write operations are not allowed to this namespace.",
        "severity": "warning",
        "action": "Check write protect state: nvme ns-descs. Clear if unintended.",
    },
    0x21: {
        "name": "Command Interrupted",
        "description": "Command was interrupted (e.g., by controller reset).",
        "severity": "warning",
        "action": "Retry the command. Check for controller reset events.",
    },
    0x22: {
        "name": "Transient Transport Error",
        "description": "A transient error occurred during transport (NVMe-oF).",
        "severity": "warning",
        "action": "Retry command. Check network stability for NVMe-oF.",
    },
}

# Command Specific Status Codes (Figure 127)
COMMAND_SPECIFIC_STATUS: Dict[int, Dict[str, str]] = {
    0x80: {
        "name": "LBA Out of Range",
        "description": "The LBA exceeds the namespace size.",
        "severity": "error",
        "action": "Verify namespace size: nvme id-ns. Check LBA in command.",
    },
    0x81: {
        "name": "Capacity Exceeded",
        "description": "The operation would exceed namespace capacity.",
        "severity": "error",
        "action": "Free space or expand namespace if thin provisioned.",
    },
    0x82: {
        "name": "Namespace Not Ready",
        "description": "The namespace is not ready for I/O operations.",
        "severity": "warning",
        "action": "Wait for namespace to become ready. Check nvme list.",
    },
    0x83: {
        "name": "Reservation Conflict",
        "description": "A reservation conflict prevented command execution.",
        "severity": "warning",
        "action": "Check reservations: nvme resv-report. Release if needed.",
    },
    0x84: {
        "name": "Format In Progress",
        "description": "A format operation is in progress.",
        "severity": "info",
        "action": "Wait for format to complete.",
    },
    0x85: {
        "name": "Invalid Value Size",
        "description": "The value size is invalid for this feature.",
        "severity": "error",
        "action": "Check feature value size requirements.",
    },
    0x86: {
        "name": "Invalid Key Size",
        "description": "The key size is invalid for this feature.",
        "severity": "error",
        "action": "Check key size requirements.",
    },
    0x87: {
        "name": "KV Key Does Not Exist",
        "description": "The specified key-value key does not exist.",
        "severity": "warning",
        "action": "Verify key exists before retrieval.",
    },
    0x88: {
        "name": "Unrecovered Error",
        "description": "Data could not be recovered after retries.",
        "severity": "critical",
        "action": "Media failure. Check SMART data. Consider drive replacement.",
    },
    0x89: {
        "name": "Key Exists",
        "description": "The key already exists (for create operations).",
        "severity": "warning",
        "action": "Use update instead of create, or delete existing key.",
    },
}

# Media and Data Integrity Errors (Figure 128)
MEDIA_DATA_INTEGRITY_STATUS: Dict[int, Dict[str, str]] = {
    0x80: {
        "name": "Write Fault",
        "description": "A write fault occurred during the operation.",
        "severity": "critical",
        "action": "Media failure. Check SMART: nvme smart-log. Consider RMA.",
    },
    0x81: {
        "name": "Unrecovered Read Error",
        "description": "Data could not be read after all recovery attempts.",
        "severity": "critical",
        "action": "Data loss likely. Check SMART error log. Run fsck if filesystem.",
    },
    0x82: {
        "name": "End-to-End Guard Check Error",
        "description": "The PI guard check failed.",
        "severity": "critical",
        "action": "Data integrity violation. Check for silent corruption.",
    },
    0x83: {
        "name": "End-to-End Application Tag Check Error",
        "description": "The PI application tag check failed.",
        "severity": "critical",
        "action": "Application tag mismatch. Check PI configuration.",
    },
    0x84: {
        "name": "End-to-End Reference Tag Check Error",
        "description": "The PI reference tag check failed.",
        "severity": "critical",
        "action": "Reference tag mismatch. Check sector numbering.",
    },
    0x85: {
        "name": "Compare Failure",
        "description": "Data comparison (Compare command) failed.",
        "severity": "warning",
        "action": "Data does not match expected. Verify source data.",
    },
    0x86: {
        "name": "Access Denied",
        "description": "Access was denied due to access control.",
        "severity": "warning",
        "action": "Check namespace access control settings.",
    },
    0x87: {
        "name": "Deallocated or Unwritten Logical Block",
        "description": "Read from deallocated or unwritten block.",
        "severity": "info",
        "action": "Normal if block was never written or was trimmed.",
    },
}

# Common vendor status codes (examples)
VENDOR_STATUS: Dict[str, Dict[int, Dict[str, str]]] = {
    "samsung": {
        0xC0: {
            "name": "Internal Temperature Exceeded",
            "description": "Samsung internal temperature threshold exceeded.",
            "severity": "critical",
            "action": "Check cooling. Reduce workload. Check SMART temperature.",
        },
    },
    "intel": {
        0xC0: {
            "name": "Device Reliability Degraded",
            "description": "Intel drive reliability has degraded.",
            "severity": "critical",
            "action": "Backup data. Plan drive replacement. Check wear level.",
        },
    },
    "micron": {
        0xC0: {
            "name": "Firmware Assert",
            "description": "Micron firmware assertion failure.",
            "severity": "critical",
            "action": "Collect debug logs. Contact Micron support.",
        },
    },
    "western digital": {
        0xC0: {
            "name": "Internal Error",
            "description": "WD/SanDisk internal error.",
            "severity": "critical",
            "action": "Power cycle drive. If persists, replace drive.",
        },
    },
}


def _get_status_code_type(sc: int, sct: int) -> str:
    """Determine the status code type name from SCT field."""
    sct_names = {
        0: "Generic Command Status",
        1: "Command Specific Status",
        2: "Media and Data Integrity Errors",
        3: "Path Related Status",
        7: "Vendor Specific",
    }
    return sct_names.get(sct, f"Reserved SCT ({sct})")


def lookup_status_code(
    status_code: int,
    status_code_type: int = 0,
    vendor: Optional[str] = None,
) -> Dict[str, Any]:
    """Look up an NVMe status code and return interpretation.
    
    Args:
        status_code: The SC (Status Code) field value (7 bits)
        status_code_type: The SCT (Status Code Type) field value (3 bits)
        vendor: Optional vendor name for vendor-specific codes
        
    Returns:
        Dictionary with code interpretation including name, description,
        severity, and recommended action.
    """
    result: Dict[str, Any] = {
        "code": status_code,
        "code_hex": f"0x{status_code:02X}",
        "sct": status_code_type,
        "sct_name": _get_status_code_type(status_code, status_code_type),
        "name": "Unknown Status Code",
        "description": f"Status code 0x{status_code:02X} with SCT {status_code_type}",
        "severity": "unknown",
        "action": "Consult NVMe specification for this status code.",
    }
    
    # Select the appropriate lookup table based on SCT
    lookup_table: Optional[Dict[int, Dict[str, str]]] = None
    
    if status_code_type == 0:
        lookup_table = GENERIC_STATUS
    elif status_code_type == 1:
        lookup_table = COMMAND_SPECIFIC_STATUS
    elif status_code_type == 2:
        lookup_table = MEDIA_DATA_INTEGRITY_STATUS
    elif status_code_type == 7 and vendor:
        vendor_lower = vendor.lower()
        for vendor_key, vendor_codes in VENDOR_STATUS.items():
            if vendor_key in vendor_lower:
                lookup_table = vendor_codes
                break
    
    if lookup_table and status_code in lookup_table:
        entry = lookup_table[status_code]
        result.update(entry)
    
    return result


def parse_status_from_output(output: str) -> List[Dict[str, Any]]:
    """Parse NVMe command output and extract status codes.
    
    Handles various output formats:
    - "status: 0x4002" (nvme-cli)
    - "SC: 0x02, SCT: 0x01"
    - "NVMe status: INVALID_FIELD(0x2)"
    
    Returns:
        List of parsed status code interpretations.
    """
    results: List[Dict[str, Any]] = []
    
    # Pattern 1: Full status word (status: 0xXXXX)
    full_status_pattern = r"status:\s*0x([0-9a-fA-F]{4})"
    for match in re.finditer(full_status_pattern, output, re.IGNORECASE):
        status_word = int(match.group(1), 16)
        # Extract SC (bits 8:1) and SCT (bits 11:9)
        sc = (status_word >> 1) & 0xFF
        sct = (status_word >> 9) & 0x7
        results.append(lookup_status_code(sc, sct))
    
    # Pattern 2: Separate SC and SCT
    separate_pattern = r"SC:\s*0x([0-9a-fA-F]+)\s*,?\s*SCT:\s*0x?([0-9a-fA-F]+)"
    for match in re.finditer(separate_pattern, output, re.IGNORECASE):
        sc = int(match.group(1), 16)
        sct = int(match.group(2), 16)
        results.append(lookup_status_code(sc, sct))
    
    # Pattern 3: Named error with code
    named_pattern = r"NVMe\s+(?:status|error):\s*(\w+)\s*\(0x([0-9a-fA-F]+)\)"
    for match in re.finditer(named_pattern, output, re.IGNORECASE):
        sc = int(match.group(2), 16)
        results.append(lookup_status_code(sc, 0))
    
    # Pattern 4: Simple hex code after "error" or "failed"
    simple_pattern = r"(?:error|failed)[:\s]+0x([0-9a-fA-F]{1,4})\b"
    for match in re.finditer(simple_pattern, output, re.IGNORECASE):
        code = int(match.group(1), 16)
        if code <= 0xFF:
            results.append(lookup_status_code(code, 0))
        else:
            # Full status word
            sc = (code >> 1) & 0xFF
            sct = (code >> 9) & 0x7
            results.append(lookup_status_code(sc, sct))
    
    return results


def interpret_nvme_output(output: str, vendor: Optional[str] = None) -> str:
    """Generate a human-readable interpretation of NVMe command output.
    
    Args:
        output: Raw NVMe command output text
        vendor: Optional vendor name for vendor-specific interpretation
        
    Returns:
        Formatted interpretation string with status code meanings.
    """
    status_codes = parse_status_from_output(output)
    
    if not status_codes:
        return ""
    
    lines: List[str] = ["", "📋 **NVMe Status Code Interpretation:**"]
    
    for idx, status in enumerate(status_codes, 1):
        severity_icons = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🔴",
            "unknown": "❓",
        }
        icon = severity_icons.get(status.get("severity", "unknown"), "❓")
        
        lines.append(f"\n{icon} **Status {status['code_hex']}** ({status['sct_name']})")
        lines.append(f"   • **Name:** {status['name']}")
        lines.append(f"   • **Description:** {status['description']}")
        lines.append(f"   • **Severity:** {status['severity'].upper()}")
        lines.append(f"   • **Recommended Action:** {status['action']}")
    
    return "\n".join(lines)


def get_critical_status_codes() -> List[Dict[str, Any]]:
    """Return all status codes classified as critical severity.
    
    Useful for alerting and monitoring systems.
    """
    critical: List[Dict[str, Any]] = []
    
    for code, entry in GENERIC_STATUS.items():
        if entry.get("severity") == "critical":
            critical.append({"code": code, "sct": 0, **entry})
    
    for code, entry in COMMAND_SPECIFIC_STATUS.items():
        if entry.get("severity") == "critical":
            critical.append({"code": code, "sct": 1, **entry})
    
    for code, entry in MEDIA_DATA_INTEGRITY_STATUS.items():
        if entry.get("severity") == "critical":
            critical.append({"code": code, "sct": 2, **entry})
    
    return critical
