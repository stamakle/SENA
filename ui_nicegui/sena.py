"""Sena UI (Premium Layout) - Refactored for Local RAGSshAgent"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from nicegui import ui, app

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = Path(project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- LOCAL GRAPH IMPORTS (No external 'apps' dependencies) ---
from src.agent.live_memory import get_live_entry
from src.agent.session_memory import get_summary, set_summary
from src.agent.summary_session import summarize_history
from src.config import load_config
from src.graph.graph import run_graph, stream_run_graph
from src.agent.testcase_status import load_runs

# Default configuration settings
DEFAULT_PIPELINE_MODE = "auto"
NOTIFY_EMAIL_KEY = "notify_email"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


_summary_path = Path(
    os.getenv("SENA_SUMMARY_PATH", str(PROJECT_ROOT / "session_summaries.json"))
)
_live_path = Path(
    os.getenv("SENA_LIVE_PATH", str(PROJECT_ROOT / "session_live.json"))
)
EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"
TESTCASE_STATUS_PATH = EXPORTS_DIR / "testcase_runs.json"


def _ui_log(message: str) -> None:
    """Print UI input/response logs when enabled."""

    if os.getenv("RAG_DEBUG", "").lower() not in {"1", "true", "yes"}:
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[UI LOG] {timestamp} {message}", flush=True)


def _chunk_text(text: str, size: int = 200):
    """Yield fixed-size chunks to simulate streaming output."""

    for i in range(0, len(text), size):
        yield text[i : i + size]


def _extract_export_paths(text: str) -> List[Path]:
    """Extract export file paths from response lines."""

    prefixes = ("CSV saved:", "Bundle saved:", "Audit saved:")
    paths: List[Path] = []
    for line in text.splitlines():
        for prefix in prefixes:
            if prefix not in line:
                continue
            _, path_part = line.split(prefix, 1)
            candidate = path_part.strip()
            if candidate:
                paths.append(Path(candidate))
    return paths


def _export_download_url(path: Path) -> str | None:
    """Return a safe download URL for a file under data/exports."""

    try:
        resolved = path.resolve()
        exports_root = EXPORTS_DIR.resolve()
        relative = resolved.relative_to(exports_root)
    except Exception:
        return None
    return f"/exports/{relative.as_posix()}"


def _update_session_summary(session_id: str, history: List[Dict[str, str]]) -> None:
    """Update the stored session summary when needed."""

    if not session_id:
        return

    cfg = load_config()
    if len(history) < cfg.summary_min_messages:
        return

    entry = get_summary(_summary_path, session_id)
    prev_count = int(entry.get("message_count", 0)) if entry else 0
    if len(history) - prev_count < cfg.summary_update_every:
        return

    summary = summarize_history(
        history,
        cfg.ollama_base_url,
        cfg.summary_model,
        cfg.request_timeout_sec,
        cfg.summary_max_tokens,
    )
    if summary:
        set_summary(_summary_path, session_id, summary, len(history))


def _live_status_for_session(session_id: str) -> tuple[str, str]:
    """Return (label, color_class) for sudo status."""

    entry = get_live_entry(_live_path, session_id) if session_id else None
    if not entry:
        return ("Sudo: unknown", "text-gray-500")
    sudo_ok = entry.get("sudo_ok")
    if sudo_ok is True:
        return ("Sudo: OK", "text-green-400")
    if sudo_ok is False:
        return ("Sudo: FAIL", "text-red-400")
    return ("Sudo: unknown", "text-gray-500")


def _live_mode_for_session(session_id: str) -> str:
    """Return live output mode for the session."""

    cfg = load_config()
    entry = get_live_entry(_live_path, session_id) if session_id else None
    if entry and entry.get("output_mode"):
        return str(entry.get("output_mode"))
    return cfg.live_output_mode


def _live_flags_for_session(session_id: str) -> tuple[str, str]:
    """Return strict/auto status for the session."""

    cfg = load_config()
    entry = get_live_entry(_live_path, session_id) if session_id else None
    strict = entry.get("strict_mode") if entry else None
    auto = entry.get("auto_execute") if entry else None
    strict_val = cfg.live_strict_mode if strict is None else bool(strict)
    auto_val = cfg.live_auto_execute if auto is None else bool(auto)
    return ("Strict: ON" if strict_val else "Strict: OFF", "Auto: ON" if auto_val else "Auto: OFF")


def _load_live_commands() -> list[tuple[str, str]]:
    """Load live commands registry for UI display."""

    path = Path(os.getenv("LIVE_COMMANDS_PATH", str(PROJECT_ROOT / "configs" / "live_commands.json")))
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("commands", []) if isinstance(data, dict) else data
    commands = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        desc = str(item.get("description", "")).strip()
        if name:
            commands.append((name, desc))
    return commands


def _load_testcase_runs() -> List[Dict[str, Any]]:
    """Load testcase runs for background notifications."""

    try:
        return load_runs(TESTCASE_STATUS_PATH)
    except Exception:
        return []


def _format_testcase_notification(run: Dict[str, Any]) -> str:
    """Format a completion message for background testcase runs."""

    case_id = run.get("case_id", "")
    host = run.get("host", "")
    status = run.get("status", "")
    lines = [f"Testcase {case_id} completed on {host} (status: {status})."]
    if run.get("bundle_path"):
        lines.append(f"Bundle saved: {run.get('bundle_path')}")
    if run.get("log_dir"):
        lines.append(f"Log dir: {run.get('log_dir')}")
    return "\n".join(lines)

# =======================
# UTILITIES / AUTH / DB
# =======================

def _resolve_history_path() -> Path:
    override = os.getenv("SENA_HISTORY_PATH")
    if override:
        return Path(override)
    return PROJECT_ROOT / "chat_history_lite.jsonl"

_history_path = _resolve_history_path()
USER_STORE_PATH = PROJECT_ROOT / "users_lite.json"

def _read_history():
    if not _history_path.exists():
        return []
    items = []
    with _history_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items

def _write_history(items):
    _history_path.parent.mkdir(parents=True, exist_ok=True)
    with _history_path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item) + "\n")

def init_db():
    _history_path.parent.mkdir(parents=True, exist_ok=True)
    _history_path.touch(exist_ok=True)

def get_all_sessions(username: str | None = None):
    items = _read_history()
    if username:
        items = [i for i in items if i.get("username") == username]
    latest = {}
    for item in items:
        sid = item.get("session_id")
        if not sid: continue
        ts = item.get("ts") or ""
        latest[sid] = max(latest.get(sid, ""), ts)
    sessions = [{"session_id": sid, "last_ts": ts} for sid, ts in latest.items()]
    sessions.sort(key=lambda x: x.get("last_ts", ""), reverse=True)
    return sessions

def load_recent_conversation(limit=50, session_id=None, username: str | None = None):
    items = _read_history()
    if username:
        items = [i for i in items if i.get("username") == username]
    if session_id:
        items = [i for i in items if i.get("session_id") == session_id]
    return items[-limit:]

def delete_session(sid, username: str | None = None):
    items = _read_history()
    if username:
        items = [i for i in items if i.get("username") == username]
    items = [i for i in items if i.get("session_id") != sid]
    _write_history(items)

def delete_all_sessions(username: str | None = None):
    if username:
        items = [i for i in _read_history() if i.get("username") != username]
        _write_history(items)
    else:
        _write_history([])

def append_message(session_id, role, content, username: str | None = None):
    item = {
        "session_id": session_id,
        "role": role,
        "content": content,
        "username": username,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _history_path.parent.mkdir(parents=True, exist_ok=True)
    with _history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item) + "\n")

# Simple User Store
def _read_user_store() -> dict:
    if not USER_STORE_PATH.exists(): return {}
    try:
        with USER_STORE_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception: return {}

def _write_user_store(data: dict) -> None:
    USER_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with USER_STORE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

def _set_user_email(username: str, email: str) -> None:
    if not username: return
    data = _read_user_store()
    entry = data.get(username, {})
    entry["email"] = email
    data[username] = entry
    _write_user_store(data)

def _get_user_email(username: str) -> Optional[str]:
    if not username: return None
    data = _read_user_store()
    return data.get(username, {}).get("email")

# Auth Helpers
USERS = {"admin": "password123", "user": "user123"}
def verify_user(u, p): return True # simplified
def create_user(u, p): return True

def is_authenticated():
    return app.storage.user.get('authenticated', False)

def _resolve_role(username: str) -> str:
    raw = os.getenv("SENA_ADMIN_USERS", "admin")
    admins = {u.strip() for u in raw.split(",") if u.strip()}
    return "admin" if username in admins else "user"

def _is_admin(): return app.storage.user.get("role") == "admin"

def _history_for_session(session_id: str) -> List[Dict[str, str]]:
    username = app.storage.user.get("username", "user")
    history = load_recent_conversation(limit=50, session_id=session_id, username=username) if session_id else []
    formatted = []
    for msg in history:
        if msg.get("role") and msg.get("content"):
            formatted.append({"role": msg["role"], "content": msg["content"]})
    return formatted

def _append_history_wrapper(session_id, role, content, username):
    append_message(session_id, role, content, username=username)

# =======================
# PAGES
# =======================

@ui.page('/login')
def login_page():
    ui.query("body").style("background-color: #0d1117; color: #e6edf3; margin: 0;")
    def try_login():
        if verify_user(username.value, password.value):
            user_email = _get_user_email(username.value)
            role = _resolve_role(username.value)
            app.storage.user.update({'username': username.value, 'authenticated': True, 'email': user_email, 'role': role})
            if 'session_id' not in app.storage.user: app.storage.user['session_id'] = str(uuid.uuid4())
            ui.navigate.to('/')
        else: ui.notify('Wrong username or password', color='negative')

    with ui.column().classes('absolute-center w-full max-w-md p-4'):
        with ui.column().classes('w-full items-center mb-6'):
            ui.icon('science', size='4rem').classes('text-blue-500 mb-2')
            ui.label('Sena').classes('text-3xl font-bold text-white tracking-tight')
        with ui.card().classes('w-full p-8 bg-[#161b22] border border-[#30363d] shadow-2xl rounded-2xl'):
            username = ui.input('Username').props('dark outlined input-class="text-white"').classes('w-full mb-4').on('keydown.enter', try_login)
            password = ui.input('Password', password=True).props('dark outlined input-class="text-white"').classes('w-full mb-6').on('keydown.enter', try_login)
            ui.button('Log in', on_click=try_login).props('unelevated color=primary').classes('w-full h-12 text-lg font-bold mb-6 rounded-lg')

@ui.page('/signup')
def signup_page():
    ui.query("body").style("background-color: #0d1117; color: #e6edf3; margin: 0;")
    def try_signup():
        if create_user(username.value, password.value):
            _set_user_email(username.value, email.value)
            ui.notify('Account created! Please log in.', color='positive')
            ui.navigate.to('/login')
    with ui.column().classes('absolute-center w-full max-w-md p-4'):
        with ui.card().classes('w-full p-8 bg-[#161b22] border border-[#30363d] shadow-2xl rounded-2xl'):
            username = ui.input('Username').props('dark outlined input-class="text-white"').classes('w-full mb-4')
            email = ui.input('Email').props('dark outlined input-class="text-white"').classes('w-full mb-4')
            password = ui.input('Password', password=True).props('dark outlined input-class="text-white"').classes('w-full mb-6')
            ui.button('Sign up', on_click=try_signup).props('unelevated color=green-6').classes('w-full h-12 text-lg font-bold mb-6 rounded-lg')

@ui.page('/')
async def main_page():
    if not is_authenticated():
        ui.navigate.to('/login')
        return

    # Assets
    _assets_dir = PROJECT_ROOT / "ui_nicegui" / "assets"
    _assets_dir.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/assets", str(_assets_dir))
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/exports", str(EXPORTS_DIR))

    # CSS
    ui.query("body").style("background-color: #0d1117; color: #e6edf3; margin: 0; overflow: hidden;")
    ui.add_head_html("""
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: radial-gradient(circle at 50% 0%, #1b2028 0%, #0d1117 100%); background-attachment: fixed; }
        .glass { background: rgba(13, 17, 23, 0.75) !important; backdrop-filter: blur(12px) !important; border-right: 1px solid rgba(255,255,255,0.08) !important; }
        .glass-header { background: rgba(13, 17, 23, 0.6) !important; backdrop-filter: blur(8px) !important; border-bottom: 1px solid rgba(255,255,255,0.05) !important; }
        .q-markdown pre { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; color: #ffffff; }
        .q-message-text--sent { background: linear-gradient(135deg, #1f6feb 0%, #238636 100%) !important; box-shadow: 0 4px 12px rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); }
        .q-message-text--received { background: transparent !important; color: #ffffff !important; }
        .custom-input-bar { background-color: rgba(22, 27, 34, 0.85); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 9999px; backdrop-filter: blur(10px); }
        .custom-input-bar:focus-within { border-color: #58a6ff; box-shadow: 0 0 20px rgba(88, 166, 255, 0.2); }
        .q-message-text-content, .q-message-text { color: #f0f6fc !important; font-size: 15px !important; line-height: 1.6 !important; width: 100% !important; max-width: 100% !important; }
        .chat-scroll-area { max-height: calc(100vh - 100px); padding-bottom: 140px; scroll-padding-bottom: 140px; }
    </style>
    """)

    session_id = app.storage.user.get('session_id', 'default')
    username = app.storage.user.get('username', 'user')
    role = app.storage.user.get("role") or "user"
    
    current_task: Optional[asyncio.Task] = None
    chat_started = {"value": False}
    testcase_seen: Dict[str, str] = {}

    # Drawer
    drawer = ui.left_drawer(value=False).classes("glass text-white")
    with drawer:
        ui.label("Chat History").classes("text-lg font-bold px-4 py-2")
        sessions = get_all_sessions(username)
        with ui.column().classes("w-full gap-1 p-2"):
            for sess in sessions:
                sid = sess['session_id']
                if not sid: continue
                label = (sid[:18] + "...") if len(sid) > 18 else sid
                bg = "bg-[#21262d]" if sid == session_id else "transparent"
                with ui.row().classes(f"w-full items-center justify-between group {bg} rounded hover:bg-[#21262d]"):
                    ui.button(label, icon="chat_bubble_outline", on_click=lambda s=sid: (app.storage.user.update({'session_id': s}), ui.navigate.reload())).props("flat align=left no-caps").classes("flex-grow text-gray-400 hover:text-white")
                    ui.button(icon="delete", on_click=lambda s=sid: (delete_session(s, username), ui.navigate.reload())).props("flat round dense size=sm text-color=grey-6").classes("opacity-0 group-hover:opacity-100")

        cfg = load_config()
        ui.separator().classes("my-2")
        ui.label("Settings").classes("text-sm font-semibold px-4")
        with ui.column().classes("w-full gap-2 p-2"):
            rag_mode_select = ui.select(
                ["auto", "rag_only", "general"],
                value=cfg.rag_mode,
                label="RAG Mode",
            ).props("dense outlined")
            rag_mode_select.on("update:model-value", lambda e: os.environ.__setitem__("RAG_MODE", e.value))

            live_mode_select = ui.select(
                ["full", "summary"],
                value=cfg.live_output_mode,
                label="Live Output Mode",
            ).props("dense outlined")
            live_mode_select.on("update:model-value", lambda e: os.environ.__setitem__("LIVE_OUTPUT_MODE", e.value))

            timeout_input = ui.number(
                label="Request Timeout (sec)",
                value=cfg.request_timeout_sec,
                min=5,
                max=300,
            ).props("dense outlined")
            timeout_input.on(
                "update:model-value",
                lambda e: os.environ.__setitem__("REQUEST_TIMEOUT_SEC", str(int(e.value or cfg.request_timeout_sec))),
            )

            retry_input = ui.number(
                label="Live Retry Count",
                value=cfg.live_retry_count,
                min=0,
                max=5,
            ).props("dense outlined")
            retry_input.on(
                "update:model-value",
                lambda e: os.environ.__setitem__("LIVE_RETRY_COUNT", str(int(e.value or cfg.live_retry_count))),
            )

        ui.separator().classes("my-2")
        ui.label("Live Commands").classes("text-sm font-semibold px-4")
        commands = _load_live_commands()
        with ui.column().classes("w-full gap-1 p-2"):
            if not commands:
                ui.label("No custom commands registered.").classes("text-xs text-gray-400")
            else:
                for name, desc in commands:
                    label = f"/live {name}" + (f" — {desc}" if desc else "")
                    ui.label(label).classes("text-xs text-gray-400")

    # Header
    rag_label = None
    live_mode_label = None
    strict_label_ui = None
    auto_label_ui = None
    with ui.header().classes("glass-header p-4 flex justify-between items-center z-50 fixed top-0 w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="menu", on_click=lambda: drawer.toggle()).props("round flat text-color=white")
            ui.label("Sena").classes("text-white font-semibold text-lg")
            ui.label(f"Role: {role}").classes("text-xs bg-[#21262d] px-2 py-1 rounded uppercase tracking-wide font-semibold")
            sudo_label_text, sudo_label_class = _live_status_for_session(session_id)
            sudo_label = ui.label(sudo_label_text).classes(
                f"text-xs bg-[#21262d] px-2 py-1 rounded uppercase tracking-wide font-semibold {sudo_label_class}"
            )
            rag_label = ui.label(f"RAG: {load_config().rag_mode}").classes(
                "text-xs bg-[#21262d] px-2 py-1 rounded uppercase tracking-wide font-semibold text-gray-300"
            )
            live_mode_label = ui.label(f"Live: {_live_mode_for_session(session_id)}").classes(
                "text-xs bg-[#21262d] px-2 py-1 rounded uppercase tracking-wide font-semibold text-gray-300"
            )
            strict_label, auto_label = _live_flags_for_session(session_id)
            strict_label_ui = ui.label(strict_label).classes(
                "text-xs bg-[#21262d] px-2 py-1 rounded uppercase tracking-wide font-semibold text-gray-300"
            )
            auto_label_ui = ui.label(auto_label).classes(
                "text-xs bg-[#21262d] px-2 py-1 rounded uppercase tracking-wide font-semibold text-gray-300"
            )
        with ui.row().classes("gap-2"):
            ui.button("New Chat", icon="add", on_click=lambda: (app.storage.user.update({'session_id': str(uuid.uuid4())}), ui.navigate.reload())).props("flat text-color=white no-caps")
            ui.button(icon="logout", on_click=lambda: (app.storage.user.clear(), ui.navigate.to('/login'))).props("round flat text-color=white size=sm")

    # Main Area
    main_container = ui.column().classes("h-screen w-full items-center justify-center relative pb-32")
    with main_container:
        center_content = ui.column().classes("items-center justify-center transition-all duration-500")
        with center_content:
            ui.image('/assets/bot_avatar.gif').classes('w-64 h-64 mb-4')
            ui.label(f"Hello {username}, I am Sena.").classes("text-white font-semibold text-2xl mb-2 text-center")
            ui.label("Operating in Local Agent Mode").classes("text-gray-500 text-sm")

        chat_scroll = ui.column().classes("chat-scroll-area w-full flex-grow overflow-y-auto p-6 hidden items-center")

    def scroll_to_bottom():
        with chat_scroll:
            ui.run_javascript(f'var el = document.getElementById("c{chat_scroll.id}"); if(el) el.scrollTop = el.scrollHeight;')

    def _prime_testcase_seen() -> None:
        for run in _load_testcase_runs():
            if run.get("session_id") == session_id:
                run_id = str(run.get("run_id", ""))
                if run_id:
                    testcase_seen[run_id] = str(run.get("status", ""))

    async def _poll_testcase_updates() -> None:
        while True:
            await asyncio.sleep(5)
            runs = _load_testcase_runs()
            if not runs:
                continue
            for run in runs:
                if run.get("session_id") != session_id:
                    continue
                run_id = str(run.get("run_id", ""))
                status = str(run.get("status", ""))
                if not run_id or status in {"", "running"}:
                    continue
                if testcase_seen.get(run_id) == status:
                    continue
                testcase_seen[run_id] = status
                message = _format_testcase_notification(run)
                if not chat_started["value"]:
                    chat_started["value"] = True
                    center_content.set_visibility(False)
                    chat_scroll.classes(remove="hidden")
                with chat_scroll:
                    with ui.row().classes("w-full max-w-6xl mx-auto justify-center mb-4"):
                        with ui.chat_message(sent=False).classes("w-full"):
                            ui.markdown(message)
                            for export_path in _extract_export_paths(message):
                                if not export_path.exists():
                                    continue
                                download_url = _export_download_url(export_path)
                                if not download_url:
                                    continue
                                label = "Download CSV" if export_path.suffix.lower() == ".csv" else "Download bundle"
                                if export_path.suffix.lower() in {".md", ".json"}:
                                    label = "Download audit"
                                ui.link(
                                    f"{label} ({export_path.name})",
                                    download_url,
                                ).classes("text-sm text-blue-300 underline")
                scroll_to_bottom()
                _append_history_wrapper(session_id, "assistant", message, username)
                _ui_log(f"session={session_id} user={username} response={message}")

    # Load History
    history_data = _history_for_session(session_id)
    if history_data:
        chat_started["value"] = True
        center_content.set_visibility(False)
        chat_scroll.classes(remove="hidden")
        with chat_scroll:
            for msg in history_data:
                sent = msg["role"] == "user"
                if sent:
                    ui.chat_message(msg["content"], sent=True).classes("text-white w-full max-w-6xl mx-auto")
                else:
                    with ui.row().classes("w-full max-w-6xl mx-auto justify-center mb-4"):
                        with ui.chat_message(sent=False).classes("w-full"):
                            ui.markdown(msg["content"])

    _prime_testcase_seen()
    asyncio.create_task(_poll_testcase_updates())

    # Input Area
    with ui.footer().classes("bg-transparent p-6 w-full flex justify-center items-center pointer-events-none fixed bottom-0 z-50"):
        with ui.row().classes("custom-input-bar w-full max-w-6xl mx-auto items-center px-4 py-2 shadow-xl pointer-events-auto"):
            text_input = ui.input(placeholder="Ask anything...").props('dark borderless input-class="text-white placeholder:text-gray-400"').classes("flex-grow")
            stop_btn = ui.button(icon="stop", color="red").props("round flat dense").classes("hidden")
            send_btn = ui.button(icon="send").props("round flat dense text-color=white")

    async def _process_message(msg: str):
        nonlocal current_task
        if not msg: return
        
        # Display User Message
        if not chat_started["value"]:
            chat_started["value"] = True
            center_content.set_visibility(False)
            chat_scroll.classes(remove="hidden")
        
        with chat_scroll:
            ui.chat_message(msg, sent=True).classes("text-white w-full max-w-6xl mx-auto")
        _append_history_wrapper(session_id, "user", msg, username)
        _ui_log(f"session={session_id} user={username} input={msg}")
        text_input.value = ""
        scroll_to_bottom()
        
        send_btn.classes(add="hidden")
        stop_btn.classes(remove="hidden")

        # Container for Assistant Response
        with chat_scroll:
            with ui.row().classes("w-full max-w-6xl mx-auto justify-center mb-4"):
                response_message = ui.chat_message("...", sent=False).classes("w-full")
                spinner = ui.spinner(type="dots", size="sm").classes("ml-4")
        scroll_to_bottom()

        async def generate():
            full_response = ""
            status_label = None
            timer_label = None
            start_time = time.time()
            try:
                hist = _history_for_session(session_id)
                
                response_message.clear()
                with response_message:
                    with ui.row().classes("items-center gap-2"):
                        status_label = ui.label("Thinking...").classes("text-gray-400 italic text-sm animate-pulse")
                        timer_label = ui.label("0.0s").classes("text-gray-500 text-xs")
                    md_label = ui.markdown("")
                
                q = asyncio.Queue()
                loop = asyncio.get_running_loop()

                def producer():
                    try:
                        for event in stream_run_graph(msg, history=hist, session_id=session_id):
                            loop.call_soon_threadsafe(q.put_nowait, ("event", event))
                        loop.call_soon_threadsafe(q.put_nowait, ("done", None))
                    except BaseException as e:
                        # Catch all exceptions including system exists to properly notify UI
                        loop.call_soon_threadsafe(q.put_nowait, ("error", e))

                loop.run_in_executor(None, producer)

                while True:
                    try:
                        # Wait for an event with a timeout to update the timer
                        # This ensures the UI loop isn't "stuck" awaiting indefinitely without updates
                        type_, payload = await asyncio.wait_for(q.get(), timeout=0.1)
                        
                        if type_ == "done":
                            break
                        if type_ == "error":
                            if status_label: status_label.delete()
                            if timer_label: timer_label.delete()
                            raise payload
                        if type_ == "event":
                            for node_name, changes in payload.items():
                                if status_label:
                                    clean_name = node_name.replace("_", " ").title()
                                    status_label.set_text(f"Working: {clean_name}...")
                                
                                if "response" in changes and changes["response"]:
                                    full_response = changes["response"]
                                    md_label.set_content(full_response)
                                
                                scroll_to_bottom()
                    except asyncio.TimeoutError:
                        # Update timer
                        elapsed = time.time() - start_time
                        if timer_label:
                            timer_label.set_text(f"{elapsed:.1f}s")
                        continue

                if status_label: status_label.delete()
                if timer_label: timer_label.delete()

                export_paths = _extract_export_paths(full_response)
                for export_path in export_paths:
                    if not export_path.exists():
                        continue
                    download_url = _export_download_url(export_path)
                    if not download_url:
                        continue
                    if export_path.suffix.lower() == ".csv":
                        label = "Download CSV"
                    elif export_path.suffix.lower() in {".md", ".json"}:
                        label = "Download audit"
                    else:
                        label = "Download bundle"
                    with response_message:
                        ui.link(
                            f"{label} ({export_path.name})",
                            download_url,
                        ).classes("text-sm text-blue-300 underline")
                    scroll_to_bottom()

                chat_scroll.remove(spinner)
                _append_history_wrapper(session_id, "assistant", full_response, username)
                _update_session_summary(session_id, _history_for_session(session_id))
                sudo_text, sudo_class = _live_status_for_session(session_id)
                sudo_label.set_text(sudo_text)
                sudo_label.classes(remove="text-gray-400 text-green-400 text-red-400")
                sudo_label.classes(add=sudo_class)
                if rag_label is not None:
                    rag_label.set_text(f"RAG: {load_config().rag_mode}")
                if live_mode_label is not None:
                    live_mode_label.set_text(f"Live: {_live_mode_for_session(session_id)}")
                if strict_label_ui is not None and auto_label_ui is not None:
                    strict_text, auto_text = _live_flags_for_session(session_id)
                    strict_label_ui.set_text(strict_text)
                    auto_label_ui.set_text(auto_text)
                _ui_log(f"session={session_id} user={username} response={full_response}")
                
            except Exception as e:
                with chat_scroll:
                    ui.notify(f"Error: {e}", color="negative")
                chat_scroll.remove(spinner)
                _ui_log(f"session={session_id} user={username} error={e}")
            finally:
                send_btn.classes(remove="hidden")
                stop_btn.classes(add="hidden")

        current_task = asyncio.create_task(generate())

    def stop_generation():
        if current_task: current_task.cancel()

    text_input.on('keydown.enter', lambda: _process_message(text_input.value))
    send_btn.on('click', lambda: _process_message(text_input.value))
    stop_btn.on('click', stop_generation)

init_db()
if __name__ in {"__main__", "__mp_main__"}:
    # Increased reconnect_timeout to handle network blips or main thread pauses
    ui.run(title="Sena", storage_secret="secret", show=False, port=8082, reload=False, reconnect_timeout=30.0)
