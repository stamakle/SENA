"""NVMe Admin Command Semantics (Recommendation #10).

Knowledge base mapping NVMe Admin opcodes to command names, expected inputs,
and output structures. Used to interpret 'nvme admin-passthru' commands
and raw trace logs.

Usage:
    from src.domain.admin_opcodes import lookup_admin_opcode
    
    cmd_info = lookup_admin_opcode(0x06)
    print(cmd_info.name)  # "Identify"
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, List

@dataclass
class AdminCommand:
    opcode: int
    hex_opcode: str
    name: str
    description: str
    data_direction: str  # "Host to Controller", "Controller to Host", "None"
    key_fields: List[str]  # Important CDW fields (e.g., "nsid", "cdw10")

# NVMe Admin Command Set (NVM Express Base Specification)
ADMIN_COMMANDS: Dict[int, AdminCommand] = {
    0x00: AdminCommand(0x00, "0x00", "Delete I/O Submission Queue", "Deletes an I/O SQ", "None", ["sqid"]),
    0x01: AdminCommand(0x01, "0x01", "Create I/O Submission Queue", "Creates an I/O SQ", "Host to Controller", ["sqid", "qsize", "prp1"]),
    0x02: AdminCommand(0x02, "0x02", "Get Log Page", "Retrieves a log page", "Controller to Host", ["nsid", "lid", "numd"]),
    0x04: AdminCommand(0x04, "0x04", "Delete I/O Completion Queue", "Deletes an I/O CQ", "None", ["cqid"]),
    0x05: AdminCommand(0x05, "0x05", "Create I/O Completion Queue", "Creates an I/O CQ", "Host to Controller", ["cqid", "qsize", "prp1"]),
    0x06: AdminCommand(0x06, "0x06", "Identify", "Returns controller/namespace data", "Controller to Host", ["nsid", "cns"]),
    0x08: AdminCommand(0x08, "0x08", "Abort", "Aborts a specific command", "None", ["sqid", "cid"]),
    0x09: AdminCommand(0x09, "0x09", "Set Features", "Sets a specific feature", "Host to Controller", ["fid", "dword11"]),
    0x0A: AdminCommand(0x0A, "0x0A", "Get Features", "Retrieves a feature value", "Controller to Host", ["fid"]),
    0x0C: AdminCommand(0x0C, "0x0C", "Asynchronous Event Request", "Submits an AER", "Controller to Host", []),
    0x10: AdminCommand(0x10, "0x10", "Firmware Commit", "Verifies/commits fw image", "None", ["slot", "action"]),
    0x11: AdminCommand(0x11, "0x11", "Firmware Image Download", "Downloads fw image", "Host to Controller", ["numd", "offset"]),
    0x14: AdminCommand(0x14, "0x14", "Device Self-test", "Starts device self-test", "None", ["nsid", "stc"]),
    0x18: AdminCommand(0x18, "0x18", "Namespace Management", "Creates/deletes namespaces", "Host to Controller", ["sel", "nsid"]),
    0x19: AdminCommand(0x19, "0x19", "Namespace Attachment", "Attaches/detaches namespaces", "Host to Controller", ["sel", "nsid"]),
    0x80: AdminCommand(0x80, "0x80", "Format NVM", "Low-level format", "None", ["nsid", "lbaf", "ses"]),
    0x81: AdminCommand(0x81, "0x81", "Security Send", "Transfers security protocol data", "Host to Controller", ["secp", "spsp"]),
    0x82: AdminCommand(0x82, "0x82", "Security Receive", "Receives security protocol data", "Controller to Host", ["secp", "spsp"]),
    0x84: AdminCommand(0x84, "0x84", "Sanitize", "Starts sanitize operation", "None", ["sanact"]),
}

def lookup_admin_opcode(opcode: int) -> Optional[AdminCommand]:
    """Look up NVMe admin command details by opcode integer."""
    return ADMIN_COMMANDS.get(opcode)

def lookup_admin_opcode_hex(hex_str: str) -> Optional[AdminCommand]:
    """Look up by hex string (e.g. '0x06')."""
    try:
        val = int(hex_str, 16)
        return ADMIN_COMMANDS.get(val)
    except ValueError:
        return None

def interpret_trace_line(line: str) -> str:
    """Attempt to interpret a raw nvme trace line containing an opcode."""
    # Simple heuristic to find opcode=0xXX patterns
    import re
    match = re.search(r"opcode=(0x[0-9a-fA-F]+)", line)
    if match:
        opcode_str = match.group(1)
        cmd = lookup_admin_opcode_hex(opcode_str)
        if cmd:
            return f"{line.strip()} -> [NVMe Admin: {cmd.name}]"
    return line
