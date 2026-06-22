import os
import subprocess
import json
import time
import datetime
import threading
import pyautogui
import gradio as gr
from flask import Flask, request, jsonify
from flask_cors import CORS
from qdrant_client import QdrantClient
from qdrant_client.http import models

# --- CONFIG ---
ACL_PATH = os.path.expanduser("~/Desktop/ACL")
REPORT_PATH = os.path.expanduser("~/Desktop/AEGIS_UPGRADE_REPORT.txt")
QDRANT_PATH = os.path.expanduser("~/qdrant_storage")

def log_event(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    with open(REPORT_PATH, "a") as f:
        f.write(f"\n[AEGIS_SUPER_AUTO] [{ts}] {msg}")
    print(f"[*] {msg}")

# --- THE OMNI-ACCEPTOR (Aggressive Window Handling) ---
def omni_acceptor():
    log_event("Omni-Acceptor: INITIALIZED. Monitoring for popups...")
    while True:
        try:
            # 1. Safety Check: Only pulse if Cursor/VSCode is in focus
            active_window = pyautogui.getActiveWindowTitle()
            if active_window and ("Cursor" in active_window or "Visual Studio Code" in active_window):
                # Pulse common 'Accept' hotkeys
                pyautogui.hotkey('ctrl', 'shift', 'enter') # Cursor Apply
                pyautogui.hotkey('ctrl', 'enter')       # Generic Apply
                pyautogui.press('enter')                # Generic OK

            time.sleep(5) # High-frequency 5s pulse
        except Exception as e:
            pass

# --- GRADIO WEB INTERFACE (For Mobile) ---
def chat_interface(user_input, history):
    try:
        # Fallback logic: If user says 'copilot', we can log it for manual web use
        # or execute via Gemini CLI.
        result = subprocess.run(["gemini", user_input], capture_output=True, text=True, shell=True)
        return result.stdout if result.stdout else result.stderr
    except Exception as e:
        return f"Error: {str(e)}"

# Define a dark, mobile-friendly theme
theme = gr.themes.Soft(
    primary_hue="cyan",
    secondary_hue="blue",
    neutral_hue="slate",
).set(
    button_primary_background_fill="*primary_500",
    button_primary_background_fill_hover="*primary_600",
)

with gr.Blocks(theme=theme, title="AEGIS MOBILE PORTAL") as demo:
    gr.Markdown("# 🌀 AEGIS : REMOTE COMMAND")
    chatbot = gr.ChatInterface(fn=chat_interface)
    with gr.Row():
        status = gr.Markdown("🟢 **Hypercore:** ONLINE | 🤖 **Auto-Accept:** ACTIVE")

# --- MAIN ---
if __name__ == "__main__":
    log_event("AEGIS_REMOTE_GATEWAY: STARTING")

    # 1. Start Omni-Acceptor
    threading.Thread(target=omni_acceptor, daemon=True).start()

    # 2. Create Desktop Shortcut
    desktop = os.path.expanduser("~/Desktop")
    with open(os.path.join(desktop, "Aegis_Web_Portal.url"), "w") as f:
        f.write("[InternetShortcut]\nURL=http://localhost:7860")

    # 3. Launch GUI
    print("[*] Launching Web UI for Phone Access...")
    # Opening browser locally for you to see
    subprocess.Popen(["start", "http://localhost:7860"], shell=True)

    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
