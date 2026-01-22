"""Query Expansion with Domain-Specific Synonyms (Recommendation #5).

This module handles query expansion for SSD validation terminology,
mapping user-friendly terms to technical equivalents and vice versa.

Usage:
    from src.domain.query_expansion import expand_query
    
    original = "check PCIe link speed"
    expanded = expand_query(original)
    # Returns: "check PCIe link speed LnkSta LnkCap Gen4 Gen5"
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


# Domain-specific synonym dictionary
# Maps common terms to their technical equivalents and related terms
DOMAIN_SYNONYMS: Dict[str, List[str]] = {
    # PCIe terminology
    "pcie link": ["LnkSta", "LnkCap", "link speed", "link width", "PCIe"],
    "link speed": ["LnkSta", "Speed", "GT/s", "Gen3", "Gen4", "Gen5"],
    "link width": ["LnkCap", "Width", "x1", "x2", "x4", "x8", "x16"],
    "pcie gen": ["Gen3", "Gen4", "Gen5", "PCIe generation", "8GT/s", "16GT/s", "32GT/s"],
    "bdf": ["bus device function", "PCI address", "domain:bus:device.function"],
    
    # NVMe terminology
    "drives": ["nvme", "namespace", "/dev/nvme", "SSD", "NVMe drives"],
    "drive": ["nvme", "namespace", "/dev/nvme", "SSD", "NVMe drive"],
    "ssd": ["nvme", "solid state drive", "flash", "NVMe SSD"],
    "ssds": ["nvme", "solid state drives", "flash", "NVMe SSDs"],
    "nvme namespace": ["nvme", "ns", "namespace", "/dev/nvmeXnY"],
    "nvme controller": ["nvme", "ctrl", "controller", "/dev/nvmeX"],
    "smart": ["SMART", "smart-log", "health", "telemetry"],
    "smart log": ["smart-log", "SMART attributes", "health log"],
    "error log": ["error-log", "NVMe errors", "command errors"],
    "firmware": ["fw", "FW Rev", "firmware version", "fw-log"],
    
    # System terminology
    "memory": ["RAM", "DIMM", "DDR4", "DDR5", "memory modules"],
    "cpu": ["processor", "CPU", "cores", "threads", "sockets"],
    "temperature": ["temp", "thermal", "celsius", "temperature sensor"],
    "power": ["watt", "power consumption", "TDP", "power state"],
    
    # Host identifiers
    "hostname": ["host", "server", "system", "machine"],
    "service tag": ["serial", "asset tag", "system id", "service_tag"],
    "ip address": ["IP", "host ip", "management ip", "BMC IP", "iDRAC IP"],
    "rack": ["rack", "location", "cabinet", "bay"],
    
    # Test terminology
    "test case": ["TC-", "testcase", "test", "validation test"],
    "test step": ["step", "procedure", "action"],
    "expected result": ["expected", "pass criteria", "success criteria"],
    
    # Error/status terminology  
    "errors": ["error", "failure", "fault", "exception", "issue"],
    "failed": ["fail", "error", "crash", "timeout", "hung"],
    "timeout": ["timed out", "deadline exceeded", "no response"],
    "throttling": ["thermal throttle", "power throttle", "throttled"],
    
    # Log sources
    "dmesg": ["kernel log", "kernel messages", "system log"],
    "journalctl": ["journal", "systemd log", "system journal"],
    "sel": ["system event log", "BMC log", "iDRAC log", "IPMI log"],
    
    # Commands
    "list": ["show", "display", "get", "fetch"],
    "run": ["execute", "perform", "do", "invoke"],
    "check": ["verify", "validate", "test", "inspect"],
}

# Abbreviation expansions
ABBREVIATIONS: Dict[str, str] = {
    "nvme": "NVMe Non-Volatile Memory Express",
    "pcie": "PCIe Peripheral Component Interconnect Express",
    "ssd": "SSD Solid State Drive",
    "bdf": "BDF Bus Device Function",
    "smart": "SMART Self-Monitoring Analysis Reporting Technology",
    "sel": "SEL System Event Log",
    "bmc": "BMC Baseboard Management Controller",
    "idrac": "iDRAC integrated Dell Remote Access Controller",
    "dimm": "DIMM Dual In-line Memory Module",
    "tbw": "TBW Terabytes Written",
    "dwpd": "DWPD Drive Writes Per Day",
    "mtbf": "MTBF Mean Time Between Failures",
    "aer": "AER Advanced Error Reporting",
    "aspm": "ASPM Active State Power Management",
    "lba": "LBA Logical Block Address",
    "qd": "QD Queue Depth",
}

# NVMe-specific status code patterns
NVME_STATUS_PATTERNS: Dict[str, List[str]] = {
    "invalid opcode": ["0x01", "invalid command", "unsupported opcode"],
    "invalid field": ["0x02", "invalid parameter", "bad field"],
    "data transfer error": ["0x04", "PRP error", "SGL error"],
    "internal error": ["0x06", "controller error", "firmware error"],
    "media error": ["0x80", "read error", "write fault", "unrecovered error"],
}


def _normalize_query(query: str) -> str:
    """Normalize query for matching (lowercase, strip extra spaces)."""
    return " ".join(query.lower().split())


def _find_matching_terms(query: str) -> List[Tuple[str, List[str]]]:
    """Find domain terms that match parts of the query.
    
    Returns list of (matched_term, synonyms) tuples.
    """
    normalized = _normalize_query(query)
    matches: List[Tuple[str, List[str]]] = []
    
    for term, synonyms in DOMAIN_SYNONYMS.items():
        if term.lower() in normalized:
            matches.append((term, synonyms))
    
    return matches


def expand_query(query: str, max_expansion_terms: int = 10) -> str:
    """Expand query with domain-specific synonyms and related terms.
    
    Args:
        query: Original user query
        max_expansion_terms: Maximum number of terms to add
        
    Returns:
        Expanded query with additional search terms
    """
    if not query:
        return query
    
    # Find matching domain terms
    matches = _find_matching_terms(query)
    
    if not matches:
        return query
    
    # Collect expansion terms (avoid duplicates)
    expansion_terms: Set[str] = set()
    query_lower = query.lower()
    
    for term, synonyms in matches:
        for syn in synonyms:
            # Don't add terms already in query
            if syn.lower() not in query_lower:
                expansion_terms.add(syn)
                if len(expansion_terms) >= max_expansion_terms:
                    break
        if len(expansion_terms) >= max_expansion_terms:
            break
    
    if not expansion_terms:
        return query
    
    # Append expansion terms to query
    expansion_str = " ".join(sorted(expansion_terms))
    return f"{query} {expansion_str}"


def expand_abbreviation(abbrev: str) -> str:
    """Expand a known abbreviation to its full form.
    
    Args:
        abbrev: Abbreviation to expand
        
    Returns:
        Full form if known, otherwise original abbreviation
    """
    return ABBREVIATIONS.get(abbrev.lower(), abbrev)


def get_related_terms(term: str) -> List[str]:
    """Get related terms for a given domain term.
    
    Args:
        term: Domain term to look up
        
    Returns:
        List of related terms, empty if not found
    """
    normalized = term.lower()
    
    # Direct match
    if normalized in DOMAIN_SYNONYMS:
        return DOMAIN_SYNONYMS[normalized]
    
    # Partial match
    for key, synonyms in DOMAIN_SYNONYMS.items():
        if normalized in key.lower():
            return synonyms
        for syn in synonyms:
            if normalized == syn.lower():
                return [key] + [s for s in synonyms if s != syn]
    
    return []


def extract_nvme_context(query: str) -> Dict[str, str]:
    """Extract NVMe-specific context from a query.
    
    Returns dict with detected elements like device, namespace, command type.
    """
    context: Dict[str, str] = {}
    
    # Device patterns
    device_match = re.search(r"/dev/(nvme\d+n?\d*)", query)
    if device_match:
        context["device"] = device_match.group(1)
    
    # Namespace patterns
    ns_match = re.search(r"nvme(\d+)n(\d+)", query)
    if ns_match:
        context["controller"] = f"nvme{ns_match.group(1)}"
        context["namespace"] = f"nvme{ns_match.group(1)}n{ns_match.group(2)}"
    
    # Command type detection
    query_lower = query.lower()
    if "smart" in query_lower or "health" in query_lower:
        context["command_type"] = "smart-log"
    elif "error" in query_lower and "log" in query_lower:
        context["command_type"] = "error-log"
    elif "list" in query_lower:
        context["command_type"] = "list"
    elif "identify" in query_lower or "id-ctrl" in query_lower:
        context["command_type"] = "identify"
    elif "firmware" in query_lower or "fw" in query_lower:
        context["command_type"] = "fw-log"
    
    return context


def suggest_commands(query: str) -> List[str]:
    """Suggest relevant NVMe commands based on query intent.
    
    Args:
        query: User query
        
    Returns:
        List of suggested nvme-cli commands
    """
    suggestions: List[str] = []
    query_lower = query.lower()
    
    # Extract device if present
    device = "/dev/nvme0n1"  # Default
    device_match = re.search(r"(/dev/nvme\d+n?\d*)", query)
    if device_match:
        device = device_match.group(1)
    
    # Suggest based on intent
    if "smart" in query_lower or "health" in query_lower:
        suggestions.append(f"nvme smart-log {device}")
        suggestions.append(f"nvme smart-log {device} -o json")
    
    if "error" in query_lower:
        suggestions.append(f"nvme error-log {device}")
        suggestions.append("dmesg | grep -i nvme")
    
    if "list" in query_lower or "drive" in query_lower:
        suggestions.append("nvme list")
        suggestions.append("nvme list -o json")
    
    if "firmware" in query_lower or "fw" in query_lower:
        suggestions.append(f"nvme fw-log {device}")
        suggestions.append(f"nvme id-ctrl {device} | grep -i fw")
    
    if "pcie" in query_lower or "link" in query_lower:
        suggestions.append("lspci -vv | grep -A 20 'Non-Volatile'")
    
    if "temperature" in query_lower or "thermal" in query_lower:
        suggestions.append(f"nvme smart-log {device} | grep -i temp")
    
    return suggestions[:5]  # Limit to 5 suggestions
