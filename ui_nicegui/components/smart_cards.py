"""Placeholder for smart card UI components."""

from __future__ import annotations
from nicegui import ui


def triage_summary_card(result: dict):
    with ui.card():
        ui.label(f"Risk: {result.get('risk_level', 'unknown')}").classes("text-xl font-bold")
        ui.label("Student summary:")
        ui.label(result.get("student_answer", "")).classes("text-sm")
