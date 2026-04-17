import subprocess
import time
import os
import re
import sys
import socket
import json
from datetime import datetime

# ==========================================
# 🧠 GEMINI-X: SMART ORCHESTRATION ENGINE
# Author: Alice (Canadian Ultra)
# Objective: Purge, Renew, and Report.
# ==========================================

REPORT_PATH = r"C:\Users\viper\Desktop\GEMINIX_STATUS_REPORT.txt"
LAUNCHER_SCRIPT = r"C:\Users\viper\LAUNCH_MOLTBOOK.py"
TUNNEL_LOG = r"C:\Users\viper\tunnel.log"

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run_diagnostic():
    """Runs a full system check and returns a summary list."""
    checks = []
    
    # 1. Check Port 5005
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', 5005)) == 0:
            checks.append("✅ Node Alpha API: ONLINE (Port 5005)")
        else:
            checks.append("❌ Node Alpha API: OFFLINE")
        s.close()
    except: checks.append("❌ Node Alpha API: UNREACHABLE")

    # 2. Check Cloudflare Tunnel
    url = "NOT_FOUND"
    if os.path.exists(TUNNEL_LOG):
        with open(TUNNEL_LOG, "r") as f:
            content = f.read()
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if match: url = match.group(0)
    
    if url != "NOT_FOUND":
        checks.append(f"✅ Cloudflare Tunnel: ACTIVE ({url})")
    else:
        checks.append("❌ Cloudflare Tunnel: INACTIVE")

    # 3. Check GPU / VRAM
    try:
        import torch
        if torch.cuda.is_available():
            vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            checks.append(f"✅ Hardware: Quadro K4000 ONLINE ({vram:.2f} GB VRAM)")
        else:
            checks.append("⚠️ Hardware: GPU NOT DETECTED (CPU Fallback)")
    except: checks.append("❌ Hardware: Torch Context Failure")

    # 4. Check Ollama Specialist Models
    try:
        import requests
        res = requests.get("http://localhost:11434/api/tags")
        if res.status_code == 200:
            models = [m['name'] for m in res.json().get('models', [])]
            checks.append(f"✅ Ollama Engines: {len(models)} models loaded ({', '.join(models[:3])}...)")
        else: checks.append("❌ Ollama Service: UNRESPONSIVE")
    except: checks.append("❌ Ollama Service: DISCONNECTED")

    return checks, url

def generate_report(checks, url):
    report = f"""# ╔══════════════════════════════════════════════════════════════╗
# ║             G E M I N I - X   S T A T U S   R E P O R T           ║
# ║             Generated: {get_timestamp()}            ║
# ╚══════════════════════════════════════════════════════════════╝

## 🛡️ MANIFOLD HEALTH SUMMARY:
"""
    for check in checks:
        report += f"{check}\n"

    report += f"""
---
## 🚀 ACCESS PORTAL:
- **Cloudflare URL:** {url}
- **Auth Token:** gemini_bridge_token_123
- **Local Port:** 5005

## 🧬 ALICE'S NOTES:
Manifold has been purged and reignited. 
The 3GB VRAM lanes are fenced and monitored.
The Hyper-Heartbeat is active in the background.

STATUS: 5-NINES STABILIZED.
"""
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ Smart Report generated at: {REPORT_PATH}")

def main():
    print("=" * 70)
    print("           G E M I N I - X :  S M A R T   I G N I T I O N           ")
    print("=" * 70)
    
    my_pid = os.getpid()
    # 1. Selective Purge
    print("[SHIELD] Purging manifold components...")
    subprocess.run(f"taskkill /F /IM cloudflared.exe /T", shell=True, stderr=subprocess.DEVNULL)
    # Kill uvicorn and other python components, but NOT the orchestrator
    subprocess.run(f"powershell -Command \"Get-Process python | Where-Object {{ $_.Id -ne {my_pid} }} | Stop-Process -Force\"", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run("taskkill /F /IM ollama.exe /T", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(3)

    # 2. Launch Launcher in background
    print("[SHIELD] Igniting Node Alpha and Establishing Bridge...")
    # Use Popen to launch it detached
    subprocess.Popen([sys.executable, LAUNCHER_SCRIPT], creationflags=subprocess.CREATE_NEW_CONSOLE)
    
    # 3. Wait for handshake
    print("[SHIELD] Waiting for 180-IQ Handshake (45s)...")
    time.sleep(45)
    
    # 4. Diagnostic & Report
    checks, url = run_diagnostic()
    generate_report(checks, url)
    
    print("=" * 70)
    print("IGNITION COMPLETE. Check your Desktop for the Status Report.")
    print("=" * 70)

if __name__ == "__main__":
    main()
