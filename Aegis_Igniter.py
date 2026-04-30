import os
import sys
import subprocess
import time
import webbrowser
from pathlib import Path

# AEGIS PROJECT PATH
PROJECT_ROOT = Path(os.getenv("AEGIS_ENGINE_ROOT", Path.home() / "AIEngine"))
sys.path.append(str(PROJECT_ROOT))

def ignite():
    print("--- [AEGIS IGNITION SEQUENCE] ---")
    
    # 1. ENFORCE HARDWARE OPTIMIZATION (K4000 MATH / RAM WEIGHTS)
    os.environ["OLLAMA_VULKAN"] = "1"
    os.environ["OLLAMA_GPU_OVERHEAD"] = "2500MiB" 
    os.environ["AEGIS_CONTEXT_WINDOW"] = "8192"
    
    print("[SYSTEM] Hardware: Quadro K4000 (Math-Only Offload Active)")
    print("[SYSTEM] Neural Architecture: 3-Model MoE (Abliterated 6B-9B Swarm)")
    
    # 2. START THE UI PROCESS
    ui_script = PROJECT_ROOT / "engine" / "aegis_ui.py"
    
    print(f"[LAUNCH] Starting Aegis Social UI...")
    # Use the current python interpreter to run the UI
    cmd = [sys.executable, str(ui_script)]
    
    process = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
    
    # 3. WAIT AND OPEN BROWSER
    time.sleep(3)
    webbrowser.open("http://127.0.0.1:7860")
    
    print("[ONLINE] AEGIS is live at http://127.0.0.1:7860")
    print("[INFO] Keep this window open while using AEGIS.")
    
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        print("\n[OFFLINE] AEGIS Powering Down.")

if __name__ == "__main__":
    ignite()
