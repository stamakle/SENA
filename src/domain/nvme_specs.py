"""NVMe Specification Knowledge Base (Recommendation #4).

This module provides a knowledge base of NVMe Base Specification (2.0+)
references for normative behavior lookup. Used by Spec-RAG to cite
authoritative behavior when analyzing validation results.

Note: Running on CPU - uses text matching rather than embeddings for lookup.

Usage:
    from src.domain.nvme_specs import lookup_spec, get_spec_section
    
    # Lookup specification for a command
    spec = lookup_spec("WRITE_ZEROES")
    print(spec.section)  # "5.17 Write Zeroes command"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import re


@dataclass
class SpecReference:
    """Reference to NVMe specification section."""
    section: str
    title: str
    description: str
    keywords: List[str] = field(default_factory=list)
    related_commands: List[str] = field(default_factory=list)
    normative_behavior: str = ""
    spec_version: str = "2.0"


# NVMe Base Specification 2.0 - Key Sections
NVME_SPEC_SECTIONS: Dict[str, SpecReference] = {
    # Admin Commands
    "identify": SpecReference(
        section="5.1",
        title="Identify command",
        description="Returns a data buffer that describes information about the NVMe subsystem, the controller, or a namespace.",
        keywords=["identify", "id-ctrl", "id-ns", "controller", "namespace", "capabilities"],
        related_commands=["nvme id-ctrl", "nvme id-ns", "nvme list-ns"],
        normative_behavior="The controller shall return the Identify data structure for the specified CNS value.",
    ),
    "get_log_page": SpecReference(
        section="5.4",
        title="Get Log Page command",
        description="Returns a data buffer containing the requested log page.",
        keywords=["log", "smart", "error", "firmware", "telemetry"],
        related_commands=["nvme smart-log", "nvme error-log", "nvme fw-log"],
        normative_behavior="The controller shall return the log page data for valid Log Page Identifiers.",
    ),
    "get_features": SpecReference(
        section="5.5",
        title="Get Features command",
        description="Returns the attributes of the specified feature.",
        keywords=["feature", "arbitration", "power", "temperature", "error recovery"],
        related_commands=["nvme get-feature"],
        normative_behavior="The controller shall return the current value of the specified feature.",
    ),
    "set_features": SpecReference(
        section="5.6",
        title="Set Features command",
        description="Sets the attributes of the specified feature.",
        keywords=["feature", "configure", "settings"],
        related_commands=["nvme set-feature"],
        normative_behavior="The controller shall update the feature value if the command completes successfully.",
    ),
    "firmware_download": SpecReference(
        section="5.3",
        title="Firmware Image Download command",
        description="Downloads all or a portion of a firmware image to the controller.",
        keywords=["firmware", "download", "update", "fw"],
        related_commands=["nvme fw-download"],
        normative_behavior="The controller shall store the firmware image data at the specified offset.",
    ),
    "firmware_commit": SpecReference(
        section="5.2",
        title="Firmware Commit command",
        description="Commits a previously downloaded firmware image.",
        keywords=["firmware", "commit", "activate", "slot"],
        related_commands=["nvme fw-commit", "nvme fw-activate"],
        normative_behavior="The controller shall activate the firmware in the specified slot based on the Commit Action.",
    ),
    "format_nvm": SpecReference(
        section="5.7",
        title="Format NVM command",
        description="Low level formats the NVM media.",
        keywords=["format", "secure erase", "lba format", "protection"],
        related_commands=["nvme format"],
        normative_behavior="The controller shall format all namespaces attached to the controller if NSID is FFFFFFFFh. This is a destructive operation.",
    ),
    "sanitize": SpecReference(
        section="5.8",
        title="Sanitize command",
        description="Starts a sanitize operation to alter all user data in the NVM subsystem.",
        keywords=["sanitize", "erase", "crypto", "security", "block erase", "overwrite"],
        related_commands=["nvme sanitize", "nvme sanitize-log"],
        normative_behavior="A sanitize operation alters ALL user data in the NVM subsystem such that recovery is not possible. This is IRREVERSIBLE.",
    ),
    
    # I/O Commands
    "read": SpecReference(
        section="6.1",
        title="Read command",
        description="Reads data and metadata from the NVM media.",
        keywords=["read", "data", "lba", "sectors"],
        related_commands=["nvme read"],
        normative_behavior="The controller shall transfer the requested data from the specified LBA range.",
    ),
    "write": SpecReference(
        section="6.2",
        title="Write command",
        description="Writes data and metadata to the NVM media.",
        keywords=["write", "data", "lba", "sectors"],
        related_commands=["nvme write"],
        normative_behavior="The controller shall write the data to the specified LBA range. Data at those LBAs is overwritten.",
    ),
    "write_zeroes": SpecReference(
        section="6.5",
        title="Write Zeroes command",
        description="Sets a range of logical blocks to zero.",
        keywords=["write zeroes", "zero", "deallocate", "unmap"],
        related_commands=["nvme write-zeroes"],
        normative_behavior="The controller shall write zeros to the specified LBA range. This is a data modification command.",
    ),
    "flush": SpecReference(
        section="6.3",
        title="Flush command",
        description="Commits data and metadata to non-volatile media.",
        keywords=["flush", "sync", "persist", "commit"],
        related_commands=["nvme flush"],
        normative_behavior="All data and metadata shall be written to non-volatile media before completion.",
    ),
    "compare": SpecReference(
        section="6.4",
        title="Compare command",
        description="Compares data on the NVM media with the provided data buffer.",
        keywords=["compare", "verify", "check"],
        related_commands=["nvme compare"],
        normative_behavior="The controller shall compare the data and report Compare Failure (status 0x85) if mismatch.",
    ),
    
    # Status Codes
    "status_generic": SpecReference(
        section="4.6.1.2.1",
        title="Generic Command Status Values",
        description="Status codes applicable to all commands.",
        keywords=["status", "error", "generic", "completion"],
        normative_behavior="Generic status values are defined in Figure 126.",
    ),
    "status_command_specific": SpecReference(
        section="4.6.1.2.2",
        title="Command Specific Status Values",
        description="Status codes specific to particular commands.",
        keywords=["status", "error", "command specific"],
        normative_behavior="Command specific status values are defined in Figure 127.",
    ),
    "status_media": SpecReference(
        section="4.6.1.2.3",
        title="Media and Data Integrity Errors",
        description="Status codes for media failures and data integrity issues.",
        keywords=["media error", "data integrity", "ECC", "uncorrectable"],
        normative_behavior="Media errors indicate permanent or transient media failures. See Figure 128.",
    ),
    
    # SMART / Health
    "smart_log": SpecReference(
        section="5.4.1.2",
        title="SMART / Health Information Log",
        description="Contains SMART attributes and health information.",
        keywords=["smart", "health", "temperature", "wear", "endurance", "spare"],
        related_commands=["nvme smart-log"],
        normative_behavior="Critical Warning field bits indicate conditions requiring attention. Available Spare below threshold is critical.",
    ),
    "error_log": SpecReference(
        section="5.4.1.1",
        title="Error Information Log",
        description="Contains information about errors that have occurred.",
        keywords=["error", "log", "failure", "command"],
        related_commands=["nvme error-log"],
        normative_behavior="Entries are added when commands complete with error status.",
    ),
    
    # PCIe Integration
    "pcie_registers": SpecReference(
        section="3.1",
        title="PCIe Transport Register Layout",
        description="Memory-mapped registers for PCIe-based NVMe controllers.",
        keywords=["pcie", "mmio", "registers", "bar", "capabilities"],
        normative_behavior="Controller registers are mapped to PCIe BAR0.",
    ),
    "controller_reset": SpecReference(
        section="3.7",
        title="Controller Reset",
        description="Resetting the controller using CC.EN or PCIe reset.",
        keywords=["reset", "CC.EN", "enable", "disable"],
        related_commands=["nvme reset", "nvme subsystem-reset"],
        normative_behavior="Setting CC.EN to 0 initiates controller shutdown. All outstanding commands are aborted.",
    ),
    
    # Queues
    "submission_queue": SpecReference(
        section="4.1",
        title="Submission Queue",
        description="Circular buffer for submitting commands to the controller.",
        keywords=["queue", "SQ", "submission", "doorbell", "command"],
        normative_behavior="Commands are fetched from the submission queue in order of tail pointer advancement.",
    ),
    "completion_queue": SpecReference(
        section="4.2",
        title="Completion Queue",
        description="Circular buffer for receiving command completions.",
        keywords=["queue", "CQ", "completion", "status", "phase"],
        normative_behavior="Completions may be posted out of order for I/O commands.",
    ),
    "queue_depth": SpecReference(
        section="4.1.1",
        title="Queue Size and Depth",
        description="Configuration of queue sizes and maximum outstanding commands.",
        keywords=["queue depth", "QD", "outstanding", "size", "entries"],
        normative_behavior="Maximum queue entries is MQES+1 from CAP register. Deep queues improve parallelism but increase memory.",
    ),
}

# Keyword to section mapping for fast lookup
_KEYWORD_INDEX: Dict[str, List[str]] = {}


def _build_keyword_index() -> None:
    """Build keyword to section ID mapping."""
    global _KEYWORD_INDEX
    if _KEYWORD_INDEX:
        return
    
    for section_id, ref in NVME_SPEC_SECTIONS.items():
        for keyword in ref.keywords:
            key = keyword.lower()
            if key not in _KEYWORD_INDEX:
                _KEYWORD_INDEX[key] = []
            _KEYWORD_INDEX[key].append(section_id)
        
        # Also index by section ID and title words
        _KEYWORD_INDEX[section_id.lower()] = [section_id]
        for word in ref.title.lower().split():
            if len(word) > 3:
                if word not in _KEYWORD_INDEX:
                    _KEYWORD_INDEX[word] = []
                if section_id not in _KEYWORD_INDEX[word]:
                    _KEYWORD_INDEX[word].append(section_id)


def lookup_spec(query: str) -> Optional[SpecReference]:
    """Look up the most relevant spec section for a query.
    
    Args:
        query: Search query (command name, keyword, etc.)
        
    Returns:
        Most relevant SpecReference or None
    """
    _build_keyword_index()
    
    query_lower = query.lower().strip()
    
    # Direct section ID match
    if query_lower in NVME_SPEC_SECTIONS:
        return NVME_SPEC_SECTIONS[query_lower]
    
    # Keyword match
    if query_lower in _KEYWORD_INDEX:
        section_id = _KEYWORD_INDEX[query_lower][0]
        return NVME_SPEC_SECTIONS[section_id]
    
    # Multi-word query - find best matching section
    query_words = set(re.findall(r'\w+', query_lower))
    best_match: Optional[str] = None
    best_score = 0
    
    for section_id, ref in NVME_SPEC_SECTIONS.items():
        section_words = set(kw.lower() for kw in ref.keywords)
        section_words.update(ref.title.lower().split())
        
        overlap = len(query_words & section_words)
        if overlap > best_score:
            best_score = overlap
            best_match = section_id
    
    if best_match and best_score > 0:
        return NVME_SPEC_SECTIONS[best_match]
    
    return None


def get_spec_section(section_id: str) -> Optional[SpecReference]:
    """Get a specific spec section by ID.
    
    Args:
        section_id: Section identifier (e.g., "identify", "smart_log")
        
    Returns:
        SpecReference or None
    """
    return NVME_SPEC_SECTIONS.get(section_id.lower())


def search_specs(query: str, max_results: int = 5) -> List[SpecReference]:
    """Search for relevant spec sections.
    
    Args:
        query: Search query
        max_results: Maximum results to return
        
    Returns:
        List of matching SpecReferences
    """
    _build_keyword_index()
    
    query_words = set(re.findall(r'\w+', query.lower()))
    scored: List[tuple] = []
    
    for section_id, ref in NVME_SPEC_SECTIONS.items():
        section_words = set(kw.lower() for kw in ref.keywords)
        section_words.update(ref.title.lower().split())
        section_words.update(ref.description.lower().split())
        
        score = len(query_words & section_words)
        if score > 0:
            scored.append((score, section_id, ref))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ref for _, _, ref in scored[:max_results]]


def format_spec_citation(ref: SpecReference) -> str:
    """Format a spec reference as a citation string.
    
    Args:
        ref: SpecReference to format
        
    Returns:
        Formatted citation string
    """
    return (
        f"**NVMe Spec {ref.spec_version} Section {ref.section}** - {ref.title}\n"
        f"{ref.description}\n"
        f"*Normative Behavior:* {ref.normative_behavior}"
    )


def get_destructive_commands() -> List[SpecReference]:
    """Get all spec references for destructive commands."""
    destructive_ids = ["format_nvm", "sanitize", "write", "write_zeroes"]
    return [NVME_SPEC_SECTIONS[sid] for sid in destructive_ids if sid in NVME_SPEC_SECTIONS]


def get_health_specs() -> List[SpecReference]:
    """Get all spec references related to health/SMART."""
    health_ids = ["smart_log", "error_log", "get_log_page"]
    return [NVME_SPEC_SECTIONS[sid] for sid in health_ids if sid in NVME_SPEC_SECTIONS]
