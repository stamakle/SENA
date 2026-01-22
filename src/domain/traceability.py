"""Requirement Traceability Matrix (Recommendation #18).

Maps validation Test Cases (TC-xxxxx) to specific NVMe Specification Requirements.
Ensures that every test result can be traced back to a normative requirement.

Usage:
    from src.domain.traceability import get_requirement_for_test
    
    req = get_requirement_for_test("TC-15174")
    print(req.id, req.description)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class Requirement:
    id: str
    source_document: str
    section: str
    description: str

@dataclass
class TestCaseTrace:
    tc_id: str
    requirement: Optional[Requirement]
    coverage_type: str = "Functional"  # Functional, Stress, Performance

# Traceability Matrix (Mock data based on typical NVMe validation)
TRACE_MATRIX: Dict[str, Requirement] = {
    "TC-15174": Requirement(
        id="REQ-NVME-FW-001",
        source_document="NVMe Base Spec 2.0",
        section="5.3",
        description="Controller shall accept Firmware Image Download command"
    ),
    "TC-SMART-005": Requirement(
        id="REQ-NVME-SMART-002",
        source_document="NVMe Base Spec 2.0",
        section="5.14.1.2",
        description="Critical Warning bit 0 shall be set when available spare is below threshold"
    ),
    "TC-PCIE-LINK-01": Requirement(
        id="REQ-PCIE-PHY-003",
        source_document="PCIe Base Spec 5.0",
        section="4.2",
        description="Link shall train to highest supported speed (Match LnkCap)"
    ),
}

def get_requirement_for_test(tc_id: str) -> Optional[Requirement]:
    """Retrieve requirement linked to a test case ID."""
    return TRACE_MATRIX.get(tc_id.upper())

def enrich_test_result_with_trace(response_text: str, tc_id: str) -> str:
    """Append traceability info to a test result string."""
    req = get_requirement_for_test(tc_id)
    if req:
        return (
            f"{response_text}\n\n"
            f"**Traceability:**\n"
            f"✅ Validates **{req.id}**: {req.description} ({req.source_document} §{req.section})"
        )
    return response_text
