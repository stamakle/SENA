"""SENA UI v5.2 - Hybrid Design (Gemini Aesthetics + Enterprise Logic)"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from nicegui import ui, app

# --- PROJECT SETUP ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = Path(project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.db.session_store import load_messages
from src.graph.graph import stream_run_graph

# --- CONFIG ---
EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# --- STYLES (Tailwind + Custom) ---
THEME = {
    "bg_grad": "background: radial-gradient(circle at 60% -20%, #172554 0%, #020617 60%, #000000 100%); background-attachment: fixed;",
    "glass_panel": "background: rgba(30, 41, 59, 0.4); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08);",
    "glass_sidebar": "background: rgba(2, 6, 23, 0.8); backdrop-filter: blur(20px); border-right: 1px solid rgba(255, 255, 255, 0.05);",
    "input_glass": "background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);",
}

# --- CONTROLLER ---
class UIState:
    """Manages UI State for Agent Manipulation."""
    def __init__(self):
        self.logs = []
        self.tabs_map = {}
        
    def log(self, action: str):
        print(f"UI_AUDIT: {action}")
        self.logs.insert(0, f"{datetime.now().strftime('%H:%M:%S')} {action}")

ui_state = UIState()

def get_greeting():
    h = datetime.now().hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"

# --- COMPONENTS ---

def nav_item(icon: str, label: str, click_cb, active: bool = False, visible: Any = True):
    """Sidebar Item with Glass Hover Effect. 'visible' can be a bindable."""
    bg = "bg-blue-600 text-white shadow-lg shadow-blue-900/50" if active else "text-gray-400 hover:text-white hover:bg-white/5"
    
    # We wrap in a row to allow visibility binding if needed, though simple label hiding works too
    with ui.item(on_click=click_cb).classes(f"rounded-lg mb-1 transition-all duration-300 cursor-pointer {bg}"):
        with ui.item_section().props('avatar'):
            ui.icon(icon).classes("text-lg")
        
        # Label section hidden in mini mode logic handled by controller or overflow
        with ui.item_section().classes("whitespace-nowrap overflow-hidden transition-all duration-300"):
            ui.label(label).classes("text-sm font-medium")

def chat_bubble(text: str, sent: bool, avatar: str = None):
    """Gemini-style Bubbles."""
    align = "justify-end" if sent else "justify-start"
    bg = "bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-tr-sm shadow-lg" if sent else "bg-transparent text-gray-200"
    
    with ui.row().classes(f"w-full {align} mb-6 animate__animated animate__fadeIn"):
        if not sent and avatar:
            ui.image(avatar).classes("w-9 h-9 rounded-full mt-1 border border-white/10 opacity-90 mr-3")
        
        with ui.column().classes(f"max-w-4xl {bg} rounded-2xl px-5 py-3"):
            if sent:
                ui.label(text).classes("text-[15px] leading-relaxed font-sans")
            else:
                ui.markdown(text, extras=['tables', 'fenced-code-blocks']).classes("prose prose-invert max-w-none text-[15px] leading-7")
                reqs = re.findall(r"(REQ-[A-Z]+-\d+)", text)
                if reqs:
                    with ui.row().classes("gap-2 mt-3 pt-2 border-t border-white/10"):
                        for r in set(reqs):
                            ui.chip(r, icon="verified").props("outline dense size=xs color=cyan").classes("opacity-80")

# --- MAIN PAGE ---

@ui.page('/')
async def main_page():
    if not app.storage.user.get('authenticated'):
        ui.navigate.to('/login')
        return

    # --- ASSETS & STYLES ---
    ui.add_head_html("""
    <link href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@200;300;400;500;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; margin: 0; color: #e2e8f0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 99px; }
    </style>
    """)
    ui.query("body").style(THEME["bg_grad"])

    # --- STATE ---
    user = app.storage.user
    session_id = user.get('session_id')
    username = user.get('username', 'Guest')
    
    ChatActive = {"value": False}
    if session_id and load_messages(session_id, limit=1):
        ChatActive["value"] = True

    MiniMode = {"value": False} # False = Fully Open by default

    # --- CONTROLLER LOGIC ---
    def toggle_sidebar():
        MiniMode["value"] = not MiniMode["value"]
        if MiniMode["value"]:
            sidebar.props(add="mini")
        else:
            sidebar.props(remove="mini")
        ui_state.log("Sidebar Toggled")

    def switch_tab(name):
        tabs_control.set_value(name)
        activate_chat_mode()
        ui_state.log(f"Switched Tab: {name}")

    def activate_chat_mode():
        if not ChatActive["value"]:
            ChatActive["value"] = True
            hero_section.classes(add="hidden")
            content_area.classes(remove="hidden")
            footer_area.classes(remove="hidden")
    
    async def submit_query(text: str = None):
        val = text or input_hero.value or input_chat.value
        if not val: return
        
        input_hero.set_value("")
        input_chat.set_value("")

        # Agent Control
        if "run test" in val.lower():
            run_ui_test()
            return
        if "open settings" in val.lower():
            ui.notify("⚙️ Settings opened", type="info")
            return
        
        activate_chat_mode()
        switch_tab("chat")
        
        with chat_scroll:
            chat_bubble(val, True)
            response_container = ui.column().classes("w-full")
        
        ui.run_javascript(f'var el = document.getElementById("c{chat_scroll.id}"); el.scrollTo(0, el.scrollHeight);')

        full_res = ""
        try:
            hist = load_messages(session_id)
            fmt = [{"role": m["role"], "content": m["content"]} for m in hist]
            
            with response_container:
                md_label = ui.markdown("Thinking...").classes("prose prose-invert text-sm animate-pulse ml-12")
            
            async for changes in stream_run_graph(val, history=fmt, session_id=session_id):
                for delta in changes.values():
                    response = None
                    if isinstance(delta, dict):
                        response = delta.get("response")
                    else:
                        response = getattr(delta, "response", None)
                    if response:
                        full_res = str(response)
                        md_label.set_content(full_res)
            
            response_container.clear()
            with chat_scroll:
                chat_bubble(full_res, False, "/assets/bot_avatar.gif")
            
        except Exception as e:
            ui.notify(f"Error: {e}", color="negative")
            response_container.clear()

    def run_ui_test():
        ui.notify("🤖 Agent executing UI Test Pattern...", type="warning")
        ui.timer(1.0, toggle_sidebar, once=True)
        ui.timer(2.0, lambda: switch_tab("inventory"), once=True)
        ui.timer(3.0, lambda: switch_tab("chat"), once=True)

    # --- LAYOUT ---

    # 1. SIDEBAR
    with ui.left_drawer(value=True).style(THEME["glass_sidebar"]).props("width=240 behavior=desktop bordered") as sidebar:
        with ui.column().classes("p-3 w-full h-full justify-between no-wrap overflow-hidden"):
            # Logo
            with ui.row().classes("items-center mb-6 pl-1 transition-all"):
                ui.image("/assets/bot_avatar.gif").classes("w-9 h-9 rounded-full border border-blue-400/30 shadow-lg")
                # Label is inside row, relies on drawer shrinking to hide overflow
                with ui.column().classes("gap-0 leading-none"):
                    ui.label("SENA Labs").classes("font-bold tracking-widest text-blue-100 text-sm ml-3 whitespace-nowrap")
                    ui.label("Orchestrator").classes("text-[10px] text-gray-500 ml-3 whitespace-nowrap")
            
            # Nav
            with ui.column().classes("gap-1 w-full flex-grow"):
                # Renamed "Live Chat" to "mAgent"
                nav_item("smart_toy", "mAgent", lambda: switch_tab("chat"), active=True)
                nav_item("monitor_heart", "Diagnostics", lambda: switch_tab("diagnostics"))
                nav_item("terminal", "System Logs", lambda: switch_tab("logs"))
                nav_item("dns", "Inventory", lambda: switch_tab("inventory"))
            
            # Bottom
            with ui.column().classes("gap-1 w-full"):
                nav_item("settings", "Settings", lambda: None)
                nav_item("logout", "Sign Out", lambda: (user.clear(), ui.navigate.to('/login')))

    # 2. HAMBURGER (Fixed)
    ui.button(icon="menu", on_click=toggle_sidebar).classes("fixed top-4 left-4 z-50 bg-black/40 backdrop-blur rounded-full text-white hover:bg-white/10 transition-all shadow-lg")

    # 3. HERO (Gemini Style)
    hero_section = ui.column().classes(f"w-full h-screen items-center justify-center p-4 transition-all duration-500 {'hidden' if ChatActive['value'] else ''}")
    with hero_section:
        ui.label(f"{get_greeting()}, {username}").classes("text-5xl font-light text-transparent bg-clip-text bg-gradient-to-r from-blue-200 to-white mb-2 animate__animated animate__fadeInDown")
        ui.label("How can I help you today?").classes("text-3xl font-thin text-gray-400 mb-10 animate__animated animate__fadeIn")
        
        with ui.row().classes("w-full max-w-2xl relative group"):
            ui.element("div").classes("absolute inset-0 bg-blue-500/20 blur-2xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300")
            with ui.input(placeholder="Ask anything...").style(THEME["input_glass"]).props("rounded outlined input-class='text-white'").classes("w-full rounded-full px-6 py-2 text-lg z-10") as input_hero:
                ui.button(icon="mic").props("flat round dense text-color=gray-400").classes("absolute right-14 top-2")
                ui.button(icon="send", on_click=lambda: submit_query()).props("flat round dense color=blue").classes("absolute right-2 top-2")
            input_hero.on('keydown.enter', lambda: submit_query())

        with ui.row().classes("gap-4 mt-8 flex-wrap justify-center animate__animated animate__fadeInUp"):
            for lbl in ["Analyze Logs", "Check Health", "Run Diagnostics"]:
                ui.button(lbl, on_click=lambda l=lbl: submit_query(f"{l}")).classes("rounded-full bg-white/5 hover:bg-white/10 border border-white/5 text-gray-300 px-6 py-2 text-sm font-normal")

    # 4. CONTENT
    content_area = ui.column().classes(f"w-full h-screen p-0 m-0 transition-opacity duration-500 {'hidden' if not ChatActive['value'] else ''}")
    with content_area:
        with ui.row().classes("w-full h-16 items-center px-12 border-b border-white/5 bg-black/20 backdrop-blur sticky top-0 z-40"):
            with ui.tabs().classes("text-gray-400 active-text-blue-400 bg-transparent") as tabs_control:
                ui.tab("chat", label="mAgent", icon="smart_toy")
                ui.tab("diagnostics", label="Health", icon="activity")
                ui.tab("logs", label="Logs", icon="terminal")
                ui.tab("inventory", label="Inventory", icon="dns")

        with ui.tab_panels(tabs_control, value="chat").classes("w-full flex-grow bg-transparent text-white"):
            with ui.tab_panel("chat").classes("p-0 h-full relative"):
                chat_scroll = ui.scroll_area().classes("w-full h-[calc(100vh-140px)] px-4 md:px-24 pt-4")
                with chat_scroll:
                    if session_id:
                        for m in load_messages(session_id, limit=20):
                            chat_bubble(m['content'], m['role']=="user", "/assets/bot_avatar.gif")

            with ui.tab_panel("diagnostics"):
                with ui.row().classes("gap-4 p-8"):
                     with ui.card().style(THEME["glass_panel"]).classes("w-64 p-6 rounded-xl"):
                        ui.label("System Status").classes("text-gray-400 text-xs font-bold uppercase tracking-wider")
                        ui.label("OPERATIONAL").classes("text-2xl font-bold text-emerald-400 my-2")
            with ui.tab_panel("logs"):
                 ui.log().classes("w-full h-full bg-black/50 border border-white/10 font-mono text-xs text-green-300 p-4 rounded-lg").push("System ready.")
            with ui.tab_panel("inventory"):
                ui.label("Inventory").classes("text-gray-400 p-8")

    # 5. FOOTER (Chat Input) - Root Level
    footer_area = ui.footer().classes(f"bg-transparent p-6 flex justify-center pointer-events-none transition-all duration-500 {'hidden' if not ChatActive['value'] else ''}")
    with footer_area:
        with ui.row().style(THEME["input_glass"]).classes("w-full max-w-3xl rounded-full px-4 py-2 items-center pointer-events-auto gap-2"):
            ui.button(icon="add_circle").props("flat round dense text-color=grey-5")
            input_chat = ui.input(placeholder="Message SENA...").props("borderless dense input-class='text-white'").classes("flex-grow")
            input_chat.on('keydown.enter', lambda: submit_query())
            ui.button(icon="send", on_click=lambda: submit_query()).props("flat round dense color=blue")

# --- LOGIN ---
@ui.page('/login')
def login_page():
    ui.query("body").style(THEME["bg_grad"])
    username_input = None
    password_input = None

    def try_login():
        username = (username_input.value or "Guest").strip() if username_input else "Guest"
        app.storage.user.update(
            {
                "authenticated": True,
                "session_id": str(uuid.uuid4()),
                "username": username,
            }
        )
        ui.navigate.to('/')
    
    with ui.column().classes("absolute-center"):
        ui.image("/assets/bot_avatar.gif").classes("w-24 h-24 rounded-full mb-6 shadow-2xl animate__animated animate__fadeInDown")
        with ui.card().style(THEME["glass_panel"]).classes("w-80 p-8 rounded-2xl animate__animated animate__fadeInUp"):
            ui.label("SENA").classes("text-2xl font-light text-center text-white mb-6 tracking-widest")
            username_input = ui.input("Username").props("dark rounded outlined dense").classes("w-full mb-3")
            password_input = (
                ui.input("Password", password=True)
                .props("dark rounded outlined dense")
                .classes("w-full mb-6")
                .on("keydown.enter", try_login)
            )
            ui.button("Enter Workspace", on_click=try_login).classes("w-full rounded-full bg-blue-600 hover:bg-blue-500 shadow-lg text-sm font-bold tracking-wide")

# --- EXECUTION ---
app.add_static_files("/assets", str(PROJECT_ROOT / "ui_nicegui" / "assets"))

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="SENA v5.2", storage_secret="sena_v5_secret", show=False, port=8085, reconnect_timeout=15)
