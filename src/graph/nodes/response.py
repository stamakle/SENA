"""Response generation node for LangGraph."""

from __future__ import annotations

import os
from pathlib import Path

from src.config import load_config
import re

from src.agent.live_extract import extract_error_lines, summarize_errors
from src.agent.live_memory import get_live_entry
from src.agent.pci_lookup import describe_pci_id
from src.agent.session_memory import get_summary
from src.db.postgres import get_connection
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.graph.nodes.live_rag import _extract_rack, _fetch_hosts_by_rack
from src.llm.ollama_client import chat_completion
from src.agent.model_router import select_chat_model
from prompt import SYSTEM_PROMPT


# Step 12: Graph response node.


def _help_text() -> str:
    """Return example prompts for the UI help command."""

    return "\n".join(
        [
            "Here are some free-form prompts you can try:",
            "- Show hosts in rack B1",
            "- Show hosts in rack B19",
            "- List hosts in rack B9",
            "- List systems in rack B19",
            "- Show system in rack B1",
            "- Show system with service tag D86HXK2",
            "- Show hostname cve-dell-7-6",
            "- Show model R740 systems",
            "- List test case TC-1198",
            "- List all test cases",
            "- List SPDM test cases",
            "- List PCIe SSD hotplug test steps",
            "- What is the expected result for SPDM - Response While in the Link Disabled State?",
            "- List steps only for TC-15174",
            "- Show detailed steps for TC-15174",
            "- Get `dmesg | tail -n 200` from hostname cve-dell-7-6",
            "- Fetch `journalctl -k --since \"10 min ago\"` from service tag D86HXK2",
            "- Run `lscpu` on host cve-dell-7-6",
            "- /ssh D86HXK2 \"uname -a\"",
            "- /live last",
            "- /live errors",
            "- /live clear",
            "- /live sudo-check <hostname|service_tag>",
            "- /live dmesg <hostname|service_tag>",
            "- /live journal <hostname|service_tag>",
            "- /live lscpu <hostname|service_tag>",
            "- /live lspci <hostname|service_tag>",
            "- /live lsblk <hostname|service_tag>",
            "- /live ip <hostname|service_tag>",
            "- /live uname <hostname|service_tag>",
            "- /live nvme <hostname|service_tag>",
            "- /live nvme-errors <hostname|service_tag>",
            "- /live os <hostname|service_tag>",
            "- /live strict on|off|status",
            "- /live auto on|off|status",
            "- /live execute",
            "- /summary live",
            "- /summary context",
            "- /debug last output",
            "- /audit testcase TC-15174 log path /path/to/logs",
            "- /memory",
            "- /safety",
            "- /health <hostname|service_tag>",
            "- /inventory rack D1",
            "- /regression TC-3362 host 98HLZ85",
            "- /metrics",
            "- /ingest <path>",
            "- /policy",
            "- /feedback",
            "- /recovery",
        ]
    )


_FOLLOW_UP_PREFIXES = ("yes", "please", "outline", "more", "continue", "ok")


def _should_include_history(query: str, has_context: bool) -> bool:
    """Return True when history should be included for conversational continuity."""

    lower = query.strip().lower()
    if not lower:
        return False
    if lower.startswith(_FOLLOW_UP_PREFIXES):
        return True
    if len(lower.split()) <= 4:
        return True
    return not has_context


def _format_recent_history(history: list[dict], limit: int = 6) -> str:
    """Format a short history block for follow-up continuity."""

    lines: list[str] = []
    for item in history[-limit:]:
        role = item.get("role")
        content = item.get("content")
        if role and content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _is_live_followup(query: str) -> bool:
    """Return True when the query references the last live output."""

    lower = query.lower()
    keywords = (
        "this output",
        "that output",
        "the output",
        "this log",
        "that log",
        "this dmesg",
        "that dmesg",
        "these errors",
        "those errors",
        "errors",
        "list errors",
        "what errors",
        "find errors",
        "where are the errors",
        "where the errors",
        "show errors",
        "error lines",
        "error entries",
        "critical",
        "issues",
        "warnings",
        "suspicious",
        "dmesg",
        "journal",
        "lscpu",
        "lspci",
        "nvme",
        "cpu",
        "processor",
        "virtualization",
        "hypervisor",
        "sockets",
        "cores",
        "threads",
        "vendor",
        "device id",
        "device ids",
        "link flap",
        "link flaps",
        "link speed",
        "linkspeed",
        "link width",
        "linkcap",
        "link cap",
        "lnkcap",
        "lnksta",
        "pcie",
        "lane",
        "lanes",
        "nic",
        "denied",
        "audit",
        "apparmor",
    )
    return any(term in lower for term in keywords)


def _wants_error_extract(query: str) -> bool:
    """Return True when the query asks about errors."""

    lower = query.lower()
    return any(term in lower for term in ("error", "errors", "failed", "panic", "exception"))


def _wants_summary(query: str) -> bool:
    """Return True when the query asks for a summary or issues."""

    lower = query.lower()
    return any(
        term in lower
        for term in (
            "summarize",
            "summary",
            "issues",
            "problems",
            "what happened",
            "what's wrong",
            "whats wrong",
        )
    )


def _wants_cpu_summary(query: str) -> bool:
    """Return True when the query asks for a CPU summary."""

    lower = query.lower()
    return "cpu" in lower and any(term in lower for term in ("summary", "summarize", "key details"))


def _wants_cpu_topology(query: str) -> bool:
    """Return True when the query asks about sockets/cores/threads."""

    lower = query.lower()
    return any(term in lower for term in ("socket", "core", "thread"))


def _wants_virtualization(query: str) -> bool:
    """Return True when the query asks about virtualization."""

    lower = query.lower()
    return any(term in lower for term in ("virtualization", "hypervisor"))


def _wants_nvme_details(query: str) -> bool:
    """Return True when the query asks about NVMe details."""

    lower = query.lower()
    return any(
        term in lower
        for term in (
            "nvme",
            "vendor",
            "device id",
            "device ids",
        )
    )


def _wants_details(query: str) -> bool:
    """Return True when the user asks for more details."""

    lower = query.lower()
    return any(
        term in lower
        for term in (
            "more details",
            "details",
            "tell me more",
            "explain more",
            "more info",
            "need more",
        )
    )


def _wants_full_output(query: str) -> bool:
    """Return True when the query explicitly asks for full/raw output."""

    lower = query.lower()
    return any(term in lower for term in ("full", "raw", "unfiltered", "show all"))


def _wants_link_info(query: str) -> bool:
    """Return True when the query asks about PCIe link info."""

    lower = query.lower()
    return any(
        term in lower
        for term in (
            "link speed",
            "linkspeed",
            "link width",
            "linkcap",
            "link cap",
            "lnkcap",
            "lnksta",
            "pcie",
            "lane",
            "lanes",
        )
    )




def _needs_rag_context(query: str) -> bool:
    """Return True when the query is likely environment/data specific."""

    lower = query.lower()
    if "tc-" in lower or "test case" in lower or "testcase" in lower:
        return True
    if any(term in lower for term in ("rack", "host", "hostname", "service tag", "system id", "bmc", "idrac")):
        return True
    if any(term in lower for term in ("sel", "dmesg", "journalctl", "lspci", "lscpu", "nvme list", "lsblk")):
        return True
    if "this output" in lower or "that output" in lower or "last output" in lower:
        return True
    return False


def _context_hint(query: str, no_context: bool) -> str:
    """Return a hint for the assistant when system context is missing."""

    if not no_context:
        return ""
    if not _needs_rag_context(query):
        return ""
    return (
        "Note: There is no system-specific context or live output available. "
        "Provide a best-effort general answer, state assumptions, and ask for "
        "the missing details or suggest a minimal next step to fetch data."
    )


def _extract_nvme_lines(output: str) -> list[str]:
    """Return lines that look like NVMe/NVMe controller entries."""

    lines = []
    for line in output.splitlines():
        lowered = line.lower()
        if "non-volatile memory controller" in lowered or "nvme" in lowered:
            lines.append(line.strip())
    return lines


def _is_lscpu_output(output: str) -> bool:
    """Return True when output looks like lscpu output."""

    if not output:
        return False
    return "Architecture:" in output and "CPU(s):" in output


def _parse_lscpu_fields(output: str) -> dict[str, str]:
    """Parse selected lscpu fields into a dict."""

    fields: dict[str, str] = {}
    last_key = ""
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            fields[key] = value
            last_key = key
        elif line.startswith(" ") and last_key:
            fields[last_key] = f"{fields.get(last_key, '').strip()} {line.strip()}".strip()
    return fields


def _extract_nvme_link_info(output: str) -> str:
    """Extract NVMe PCIe link speed/width lines from lspci output."""

    if not output:
        return ""
    current_bdf = ""
    entries: dict[str, dict[str, str]] = {}
    for line in output.splitlines():
        header_match = re.match(r"^([0-9a-fA-F]{2,4}:[0-9a-fA-F]{2}\.[0-7])\s+(.*)$", line.strip())
        if header_match:
            current_bdf = header_match.group(1)
            entries.setdefault(current_bdf, {})
            continue
        lowered = line.lower()
        if "lnkcap" in lowered or "lnksta" in lowered:
            speed_match = re.search(r"speed\s*([0-9.]+GT/s)", line, re.IGNORECASE)
            width_match = re.search(r"width\s*(x\d+)", line, re.IGNORECASE)
            if not current_bdf:
                continue
            entry = entries.setdefault(current_bdf, {})
            if "lnkcap" in lowered:
                if speed_match:
                    entry["cap_speed"] = speed_match.group(1)
                if width_match:
                    entry["cap_width"] = width_match.group(1)
            if "lnksta" in lowered:
                if speed_match:
                    entry["sta_speed"] = speed_match.group(1)
                if width_match:
                    entry["sta_width"] = width_match.group(1)

    lines = []
    for bdf, info in entries.items():
        if not info:
            continue
        sta_speed = info.get("sta_speed", "unknown")
        sta_width = info.get("sta_width", "unknown")
        cap_speed = info.get("cap_speed", "unknown")
        cap_width = info.get("cap_width", "unknown")
        lines.append(
            f"- {bdf}: LnkSta {sta_speed} {sta_width} (Cap: {cap_speed} {cap_width})"
        )
    return "\n".join(lines)


def _format_cpu_summary(fields: dict[str, str]) -> str:
    """Return a deterministic CPU summary."""

    lines: list[str] = []
    for key in (
        "Architecture",
        "Model name",
        "CPU(s)",
        "Socket(s)",
        "Core(s) per socket",
        "Thread(s) per core",
        "Hypervisor vendor",
        "Virtualization type",
    ):
        value = fields.get(key, "")
        if value:
            lines.append(f"- {key}: {value}")
    if not lines:
        return "No CPU details were detected in the last live output."
    return "Key CPU details:\n" + "\n".join(lines)


def _extract_lines_by_terms(output: str, terms: tuple[str, ...], max_lines: int = 20) -> str:
    """Return lines containing any of the given terms (case-insensitive)."""

    if not output:
        return ""
    hits: list[str] = []
    lowered_terms = [term.lower() for term in terms]
    for idx, line in enumerate(output.splitlines(), start=1):
        lowered = line.lower()
        if any(term in lowered for term in lowered_terms):
            hits.append(f"{idx}: {line}")
        if len(hits) >= max_lines:
            break
    return "\n".join(hits)


_PCI_ID_PATTERN = re.compile(r"\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]")


def _format_nvme_details(lines: list[str], host: str = "") -> str:
    """Format a deterministic NVMe detail response."""

    if not lines:
        return "No NVMe entries were found in the last live output."

    header = f"NVMe entries from lspci{f' on {host}' if host else ''}:"
    formatted_lines = []
    for line in lines:
        match = _PCI_ID_PATTERN.search(line)
        if match:
            vendor_id, device_id = match.group(1).lower(), match.group(2).lower()
            vendor_name, device_name = describe_pci_id(vendor_id, device_id)
            formatted_lines.append(
                f"- {line} (Vendor: {vendor_name} [{vendor_id}], Device: {device_name} [{device_id}])"
            )
        else:
            formatted_lines.append(f"- {line}")
    formatted = "\n".join(formatted_lines)
    detail_hint = (
        "\n\nNext deterministic checks:\n"
        "- /live nvme <hostname|service_tag>\n"
        "- /live lspci <hostname|service_tag>\n"
        "- /live lsblk <hostname|service_tag>"
    )
    return f"{header}\n{formatted}{detail_hint}"


def _format_rack_table(rack: str, hosts: list[dict]) -> str:
    """Return a markdown table for rack systems."""

    rows = []
    for host in hosts:
        rack_val = str(host.get("rack") or rack)
        system_id = str(host.get("system_id") or "")
        hostname = str(host.get("hostname") or "")
        address = str(host.get("address") or "")
        rows.append((rack_val, system_id, hostname, address))
    if not rows:
        return f"No systems found for rack {rack}."
    header = "| Rack | Service Tag | Hostname | IP |"
    sep = "| --- | --- | --- | --- |"
    lines = [header, sep]
    for row in rows:
        lines.append("| {} | {} | {} | {} |".format(*row))
    return "\n".join(lines)


def _fetch_test_case(case_id: str, cfg) -> dict | None:
    """Fetch a single testcase record from Postgres."""

    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id, name, type, description, steps FROM test_cases WHERE case_id = %s",
                (case_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "case_id": row[0],
            "name": row[1] or "",
            "type": row[2] or "",
            "description": row[3] or "",
            "steps": row[4] or [],
        }
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def _list_test_cases(cfg, term: str | None, limit: int = 200) -> list[dict]:
    """Return a list of test case ids/names."""

    conn = None
    rows: list[dict] = []
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            if term:
                cur.execute(
                    """
                    SELECT case_id, name
                    FROM test_cases
                    WHERE name ILIKE %s OR description ILIKE %s
                    ORDER BY case_id
                    LIMIT %s
                    """,
                    (f"%{term}%", f"%{term}%", limit),
                )
            else:
                cur.execute(
                    """
                    SELECT case_id, name
                    FROM test_cases
                    ORDER BY case_id
                    LIMIT %s
                    """,
                    (limit,),
                )
            for case_id, name in cur.fetchall():
                rows.append({"case_id": case_id, "name": name or ""})
    except Exception:
        return []
    finally:
        if conn is not None:
            conn.close()
    return rows


def _format_testcase_table(rows: list[dict], heading: str) -> str:
    """Return a markdown table for test cases."""

    if not rows:
        return "No test cases found."
    lines = [heading, "", "| Test Case | Title |", "| --- | --- |"]
    for row in rows:
        lines.append("| {} | {} |".format(row.get("case_id", ""), row.get("name", "")))
    return "\n".join(lines)


def _format_testcase_steps(record: dict, mode: str, max_steps: int | None = None) -> str:
    """Return the test case in the expected numbered format."""

    case_id = record.get("case_id", "")
    name = record.get("name", "")
    test_type = record.get("type", "") or "Unknown"
    steps = record.get("steps") or []
    if max_steps is not None:
        steps = steps[:max_steps]
    lines = [f"Test Case: {case_id} Name: {name}", f"Test Type: {test_type}"]
    description = (record.get("description") or "").strip()
    if description:
        lines.append(f"Description: {description}")
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        desc = (step.get("description") or "").strip()
        expected = (step.get("expected") or "").strip()
        if not desc and not expected:
            continue
        line = f"{idx} Description {desc}".strip()
        if mode == "detailed" and expected:
            line = f"{line} Expected {expected}".strip()
        lines.append(line)
    return "\n".join(lines)


def response_node(state: GraphState | dict) -> dict:
    """Generate a final response for the user."""

    current = coerce_state(state)
    if current.response:
        return state_to_dict(current)
    if current.route == "help":
        current.response = _help_text()
        return state_to_dict(current)

    if current.error:
        current.response = f"Error during retrieval: {current.error}"
        return state_to_dict(current)
    if current.response and any(
        marker in current.response
        for marker in ("Bundle saved:", "CSV saved:", "Audit saved:")
    ):
        return state_to_dict(current)

    # Rec 9: Auto-generate reproduction bundle if we have an error context
    if "error" in (current.response or "").lower() and current.plan:
        try:
            exports_dir = Path(os.getenv("SENA_EXPORTS_DIR", str(Path(__file__).resolve().parents[3] / "data" / "exports")))
            exports_dir.mkdir(parents=True, exist_ok=True)
            repro_path = exports_dir / f"repro_{current.session_id[:8]}.sh"
            with open(repro_path, "w") as f:
                f.write("#!/bin/bash\n# Reproduction Script\n")
                f.write(f"# Query: {current.query}\n")
                if current.plan:
                    f.write(f"# Plan:\n# {current.plan.replace(chr(10), chr(10)+'# ')}\n")
                f.write("\n# Commands (Manual extraction needed for full fidelity):\n")
                # In a real system, we'd iterate over executed steps.
                f.write("echo 'Run validation...'\n")
            
            current.response += f"\n\nBundle saved: {repro_path}"
        except Exception as e:
            current.response += f"\n(Failed to save Bundle: {e})"

    cfg = load_config()
    query = current.augmented_query or current.query
    session_summary = ""
    live_output = ""
    live_summary = ""
    live_host = ""
    live_command = ""
    live_mode = ""
    if current.session_id:
        summary_path = Path(
            os.getenv(
                "SENA_SUMMARY_PATH",
                str(Path(__file__).resolve().parents[3] / "session_summaries.json"),
            )
        )
        entry = get_summary(summary_path, current.session_id)
        if entry:
            session_summary = str(entry.get("summary", "")).strip()
        live_path = Path(
            os.getenv(
                "SENA_LIVE_PATH",
                str(Path(__file__).resolve().parents[3] / "session_live.json"),
            )
        )
        live_entry = get_live_entry(live_path, current.session_id)
        if live_entry:
            live_output = str(live_entry.get("output", "")).strip()
            live_summary = str(live_entry.get("summary", "")).strip()
            live_host = str(live_entry.get("host", "")).strip()
            live_command = str(live_entry.get("command", "")).strip()
            live_mode = str(live_entry.get("output_mode", "")).strip().lower()
        else:
            live_mode = ""

    chat_model = select_chat_model(query, bool(current.context or live_output or live_summary), cfg)

    if current.context:
        base = f"Context:\n{current.context}\n\nQuestion: {query}"
    else:
        base = query

    has_any_context = bool(current.context or live_output or live_summary or session_summary)
    history_block = ""
    if not session_summary and current.history and _should_include_history(query, has_any_context):
        history_text = _format_recent_history(current.history)
        if history_text:
            history_block = f"Recent conversation:\n{history_text}\n\n"

    live_block = ""
    if _is_live_followup(query):
        if live_output:
            if _wants_full_output(query):
                current.response = f"Last live output:\n{live_output}"
                return state_to_dict(current)
            if _wants_summary(query):
                heuristic = summarize_errors(live_output, max_lines=cfg.live_error_max_lines)
                if heuristic:
                    current.response = f"Summary of the last live output:\n{heuristic}"
                else:
                    current.response = "No summary is available yet. Run another live command first."
                return state_to_dict(current)

        is_nvme_bundle = (
            (live_command or "").strip().lower() == "nvme-errors bundle"
            or "nvme error bundle" in live_output.lower()
        )

        if live_output and _wants_link_info(query):
            link_info = _extract_nvme_link_info(live_output)
            if link_info:
                current.response = f"NVMe PCIe link info:\n{link_info}"
            else:
                current.response = (
                    "No PCIe link info was found in the last live output. "
                    "Run `/live nvme-errors <hostname|service_tag>` or `/live lspci -vv <hostname|service_tag>`."
                )
            return state_to_dict(current)

        if live_output and _is_lscpu_output(live_output):
            fields = _parse_lscpu_fields(live_output)
            if _wants_cpu_summary(query):
                current.response = _format_cpu_summary(fields)
                return state_to_dict(current)
            if _wants_virtualization(query):
                hypervisor = fields.get("Hypervisor vendor", "")
                virt = fields.get("Virtualization type", "")
                if hypervisor or virt:
                    current.response = (
                        "Virtualization details:\n"
                        f"- Hypervisor vendor: {hypervisor or 'Unknown'}\n"
                        f"- Virtualization type: {virt or 'Unknown'}"
                    )
                    return state_to_dict(current)
            if _wants_cpu_topology(query):
                sockets = fields.get("Socket(s)", "Unknown")
                cores = fields.get("Core(s) per socket", "Unknown")
                threads = fields.get("Thread(s) per core", "Unknown")
                total = fields.get("CPU(s)", "Unknown")
                current.response = (
                    "CPU topology:\n"
                    f"- Socket(s): {sockets}\n"
                    f"- Core(s) per socket: {cores}\n"
                    f"- Thread(s) per core: {threads}\n"
                    f"- CPU(s) total: {total}"
                )
                return state_to_dict(current)

        if live_output and (
            _wants_nvme_details(query)
            or _wants_details(query)
            or ("nvme" in query.lower() and "lspci" in (live_command or "").lower())
            or "filter nvme" in query.lower()
        ) and not is_nvme_bundle:
            nvme_lines = _extract_nvme_lines(live_output)
            if nvme_lines:
                current.response = _format_nvme_details(nvme_lines, live_host)
                return state_to_dict(current)
            current.response = (
                "No NVMe entries were detected in the last live output. "
                "Run `/live lspci <host>` to refresh the PCI inventory."
            )
            return state_to_dict(current)
        if live_output:
            lowered = query.lower()
            if "top 5" in lowered or "top five" in lowered:
                extracted = extract_error_lines(live_output, max_lines=5)
                if extracted:
                    current.response = f"Top 5 issue lines:\n{extracted}"
                else:
                    current.response = "No issue lines were found in the last live output."
                return state_to_dict(current)
            if any(term in lowered for term in ("denied", "apparmor", "audit")):
                filtered = _extract_lines_by_terms(live_output, ("denied", "apparmor", "audit"))
                if filtered:
                    current.response = f"Filtered AppArmor/audit lines:\n{filtered}"
                else:
                    current.response = "No AppArmor/audit lines were found in the last live output."
                return state_to_dict(current)
            if "link" in lowered and any(term in lowered for term in ("flap", "flaps", "nic", "link")):
                filtered = _extract_lines_by_terms(live_output, ("link is down", "link is up"))
                if filtered:
                    current.response = f"NIC link events:\n{filtered}"
                else:
                    current.response = "No NIC link flap lines were found in the last live output."
                return state_to_dict(current)
            if "nvme" in lowered and "lspci" not in lowered:
                filtered = _extract_lines_by_terms(live_output, ("nvme", "non-volatile memory controller"))
                if filtered:
                    current.response = f"NVMe-related lines:\n{filtered}"
                    return state_to_dict(current)
            if "hogged cpu" in lowered or "hogged" in lowered:
                filtered = _extract_lines_by_terms(live_output, ("hogged cpu",))
                if filtered:
                    current.response = (
                        f"Hogged CPU lines:\n{filtered}\n\n"
                        "Meaning: the kernel workqueue reports a task running longer than expected. "
                        "This can indicate CPU contention or a slow driver; consider WQ_UNBOUND if repeated."
                    )
                else:
                    current.response = "No hogged CPU lines were found in the last live output."
                return state_to_dict(current)
            if "critical" in lowered or "panic" in lowered or "fatal" in lowered:
                filtered = _extract_lines_by_terms(live_output, ("critical", "panic", "fatal", "oops", "bug:"))
                if filtered:
                    current.response = f"Critical error lines:\n{filtered}"
                else:
                    current.response = "No critical/panic/fatal lines were found in the last live output."
                return state_to_dict(current)
            if "suspicious" in lowered or "issues" in lowered or "warnings" in lowered:
                extracted = extract_error_lines(live_output, max_lines=cfg.live_error_max_lines)
                if extracted:
                    current.response = f"Potentially suspicious lines:\n{extracted}"
                else:
                    current.response = "No suspicious/error-like lines were found in the last live output."
                return state_to_dict(current)

        if _wants_error_extract(query) and live_output:
            extracted = extract_error_lines(live_output, max_lines=cfg.live_error_max_lines)
            if extracted:
                current.response = f"Extracted error lines:\n{extracted}"
                return state_to_dict(current)
            current.response = (
                "No error-like lines were found in the last live output. "
                "Try `/live errors` after capturing logs, or ask for a summary."
            )
            return state_to_dict(current)

        if live_block:
            if session_summary:
                user_prompt = f"{live_block}Session Summary:\n{session_summary}\n\n{base}"
            else:
                user_prompt = f"{live_block}{history_block}{base}"
            current.response = chat_completion(
                cfg.ollama_base_url,
                chat_model,
                SYSTEM_PROMPT,
                user_prompt,
                cfg.request_timeout_sec,
                num_predict=cfg.chat_max_tokens,
            )
            return state_to_dict(current)
        
        # If we didn't trigger above (e.g. wants_error_extract was false), check for 'analyze' intent
        if "analyze" in query.lower() and live_output:
             subset = live_output[: cfg.live_output_max_chars]
             live_block = f"Last live output (full/partial):\n{subset}\n\n"
             if session_summary:
                user_prompt = f"{live_block}Session Summary:\n{session_summary}\n\n{base}"
             else:
                user_prompt = f"{live_block}{history_block}{base}"
             current.response = chat_completion(
                cfg.ollama_base_url,
                chat_model,
                SYSTEM_PROMPT,
                user_prompt,
                cfg.request_timeout_sec,
                num_predict=cfg.chat_max_tokens,
             )
             return state_to_dict(current)

        mode = live_mode or cfg.live_output_mode.lower()
        if mode == "summary" and live_summary:
            live_block = f"Last live output summary:\n{live_summary}\n\n"
        elif mode == "summary" and not live_summary and live_output:
            live_block = f"Last live output:\n{live_output}\n\n"
        elif live_output:
            live_block = f"Last live output:\n{live_output}\n\n"
        elif live_summary:
            live_block = f"Last live output summary:\n{live_summary}\n\n"

    no_context = not (current.context or live_output or live_summary or session_summary or live_block)
    context_hint = _context_hint(query, no_context)
    if context_hint:
        context_hint = f"{context_hint}\n\n"

    if session_summary:
        user_prompt = f"{context_hint}{live_block}Session Summary:\n{session_summary}\n\n{base}"
    else:
        user_prompt = f"{context_hint}{live_block}{history_block}{base}"
    rag_mode = (cfg.rag_mode or "auto").strip().lower()
    if cfg.rag_only:
        rag_mode = "rag_only"
    if rag_mode not in {"auto", "rag_only", "general"}:
        rag_mode = "auto"
    lower = query.lower()
    rack = _extract_rack(query)
    if rack and any(term in query.lower() for term in ("list", "show", "find", "search", "system", "host")):
        try:
            hosts = _fetch_hosts_by_rack(rack, cfg)
        except Exception:
            hosts = []
        if hosts:
            current.response = _format_rack_table(rack, hosts)
            return state_to_dict(current)
        current.response = f"No systems found for rack {rack}. Ensure system_logs has rack metadata."
        return state_to_dict(current)

    case_match = re.search(r"\b(?:TC|DSSTC)-\d+\b", query, re.IGNORECASE)
    if case_match and "step" in lower:
        case_id = case_match.group(0).upper()
        record = _fetch_test_case(case_id, cfg)
        if record:
            current.response = _format_testcase_steps(record, current.step_mode or "steps_only")
            return state_to_dict(current)
        current.response = f"No test case found for {case_id}."
        return state_to_dict(current)
    if case_match and any(term in lower for term in ("show test case", "find test case", "test case", "testcase")):
        case_id = case_match.group(0).upper()
        record = _fetch_test_case(case_id, cfg)
        if record:
            max_steps = 3 if (current.step_mode or "summary") == "summary" else None
            current.response = _format_testcase_steps(record, current.step_mode or "summary", max_steps=max_steps)
            return state_to_dict(current)
        current.response = f"No test case found for {case_id}."
        return state_to_dict(current)
    if re.search(r"\b(list|show|find|search)\b.*\btest cases?\b", lower) and not case_match:
        term = None
        for keyword in ("spdm", "pcie", "nvme", "ssd", "hotplug"):
            if keyword in lower:
                term = keyword
                break
        rows = _list_test_cases(cfg, term)
        heading = "Test Cases:"
        if term:
            heading = f"Test Cases ({term.upper()}):"
        current.response = _format_testcase_table(rows, heading)
        return state_to_dict(current)

    if no_context:
        case_match = re.search(r"\b(?:TC|DSSTC)-\d+\b", query, re.IGNORECASE)
        if case_match:
            case_id = case_match.group(0).upper()
            current.response = (
                f"No test case found for {case_id}. "
                "Ensure test case data is indexed (scripts/setup.sh update)."
            )
            return state_to_dict(current)
        if rag_mode == "rag_only":
            current.response = (
                "RAG-only mode is enabled, and no relevant context was found. "
                "Please provide a test case ID, relevant logs, or run a live command "
                "so I can answer based on evidence.\n\n"
                "Examples:\n"
                "- /live dmesg <hostname>\n"
                "- /live lspci <hostname>\n"
                "- Show test case TC-15174"
            )
            return state_to_dict(current)
        # In free-prompt mode, allow general responses even without context.

    current.response = chat_completion(
        cfg.ollama_base_url,
        chat_model,
        SYSTEM_PROMPT,
        user_prompt,
        cfg.request_timeout_sec,
        num_predict=cfg.chat_max_tokens,
    )
    return state_to_dict(current)
