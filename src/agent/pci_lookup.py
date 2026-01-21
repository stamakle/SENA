"""Local PCI ID lookup table for deterministic device details."""

from __future__ import annotations

from typing import Dict, Tuple


# Step 26: Deterministic PCI ID expansion.


PCI_VENDOR_TABLE: Dict[str, str] = {
    "15ad": "VMware",
}

PCI_DEVICE_TABLE: Dict[str, Dict[str, str]] = {
    "15ad": {
        "07f0": "NVMe SSD Controller",
    }
}


def describe_pci_id(vendor_id: str, device_id: str) -> Tuple[str, str]:
    """Return (vendor_name, device_name) for the given PCI IDs."""

    vendor = PCI_VENDOR_TABLE.get(vendor_id.lower(), "Unknown vendor")
    device = PCI_DEVICE_TABLE.get(vendor_id.lower(), {}).get(device_id.lower(), "Unknown device")
    return vendor, device
