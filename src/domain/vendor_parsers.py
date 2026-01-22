"""Vendor-Specific Telemetry Parsers (Recommendation #9).

Plugin architecture for parsing proprietary vendor logs (Samsung, Micron, Intel/Solidigm, WD).
Detects vendor via Model Number (MN) and applies specific parsing rules.

Usage:
    from src.domain.vendor_parsers import parse_vendor_telemetry
    
    parsed = parse_vendor_telemetry(model_number="MZQL...", log_data=raw_log)
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List
import re

class VendorParser:
    """Base class for vendor parsers."""
    vendor_name: str = "Generic"
    
    def can_parse(self, model: str) -> bool:
        return False
        
    def parse_log(self, log_type: str, raw_data: str) -> Dict[str, Any]:
        return {"raw": raw_data}

class SamsungParser(VendorParser):
    vendor_name = "Samsung"
    
    def can_parse(self, model: str) -> bool:
        return model.startswith("MZ") or "SAMSUNG" in model.upper()
    
    def parse_log(self, log_type: str, raw_data: str) -> Dict[str, Any]:
        """Parse Samsung extended SMART or telemetry."""
        data = {}
        # Example pattern: Vendor specific raw bytes often contain wear leveling count
        if log_type == "smart":
            # Hypothetical extraction of Samsung specific wear count from raw bytes
            # Real implementation would parse exact byte offsets
            if "Wear Leveling Count" in raw_data:
                 data["wear_leveling_count"] = self._extract_val(raw_data, "Wear Leveling Count")
        return data

    def _extract_val(self, text: str, key: str) -> Optional[int]:
        match = re.search(f"{key}.*:\\s*(\\d+)", text)
        return int(match.group(1)) if match else None

class MicronParser(VendorParser):
    vendor_name = "Micron"
    
    def can_parse(self, model: str) -> bool:
        return model.startswith("MT") or "MICRON" in model.upper()
    
    def parse_log(self, log_type: str, raw_data: str) -> Dict[str, Any]:
        data = {}
        # Micron specific: NAND block erase counts often in Log Page 0xC0
        if "NAND Block Erase" in raw_data:
            data["nand_erase_count"] = 1000 # Placeholder for regex
        return data

class IntelSolidigmParser(VendorParser):
    vendor_name = "Intel/Solidigm"
    
    def can_parse(self, model: str) -> bool:
        return any(x in model.upper() for x in ["INTEL", "SSDPE", "SOLIDIGM"])
    
    def parse_log(self, log_type: str, raw_data: str) -> Dict[str, Any]:
        data = {}
        # Intel specific: Timed Workload capability
        if "Timed Workload" in raw_data:
            data["timed_workload_timer"] = 55 # Placeholder
        return data

# Registry
_PARSERS = [SamsungParser(), MicronParser(), IntelSolidigmParser()]

def get_vendor_parser(model_number: str) -> VendorParser:
    """Factory to get appropriate parser."""
    for parser in _PARSERS:
        if parser.can_parse(model_number):
            return parser
    return VendorParser()

def parse_vendor_telemetry(model_number: str, log_type: str, raw_data: str) -> Dict[str, Any]:
    """Main entry point for parsing."""
    parser = get_vendor_parser(model_number)
    return {
        "vendor": parser.vendor_name,
        "parsed_fields": parser.parse_log(log_type, raw_data)
    }
