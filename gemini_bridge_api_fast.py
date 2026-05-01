from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import subprocess
import json
import asyncio
import base64
import hashlib
import queue
import re
import sqlite3
import shlex
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict
from pydantic import BaseModel
from io import BytesIO
import pyautogui
from dotenv import load_dotenv

import sys
from pathlib import Path, PureWindowsPath

# Add current directory to path for local module imports
sys.path.append(str(Path(__file__).parent))

# Moltbook v3.8 Core
from aegis_dspy import initialize_dspy
from aegis_toolkit import score_source_credibility, tool_registry
from browser_use_bridge import browser_use_runtime_status
from gemma_tools import (
    apply_code_intent_italics,
    build_axiom_processing_frame,
    build_response_contract,
    build_request_profile,
    create_system_prompt,
    execute_tool_calls,
    execute_tool_result,
    format_axiom_processing_brief,
    normalize_prompt_text,
    parse_tool_call,
    parse_tool_calls,
    prompt_matches_signal,
    should_execute_tool_call,
    should_execute_tool_calls,
)
from agentic_crawler_db import crawler_db
from agentic_loop_controller import agentic_controller, SubTask
from coding_kernels import build_coding_kernel_brief
from context_policy import (
    OLLAMA_CHAT_TIMEOUT_SECONDS,
    OLLAMA_NUM_CTX_DEFAULT,
    OLLAMA_NUM_CTX_LONG,
    OLLAMA_NUM_CTX_SIMPLE,
    OLLAMA_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS,
    RESPONSE_BUDGET_DEFAULT,
    RESPONSE_BUDGET_DELIBERATE,
    RESPONSE_BUDGET_FULL,
    RESPONSE_BUDGET_MAX,
    RESPONSE_BUDGET_SIMPLE,
    runtime_context_policy,
)
from systems_kernels import build_systems_kernel_brief, detect_system_domains
from manifold_db import Conversation, Feedback, SessionLocal, manifold_db
from manifold_pipeline import postprocess_chat_turn, postprocess_research_project, record_tool_action
from fabris_pattern_engine import build_fabris_context_hints, fabris_status, top_fabris_patterns
from local_program_loop import build_program_executor, decompose_program_task, default_program_target_dir
from training_experiment_engine import (
    build_long_research_executor,
    decompose_long_research_task,
    predict_execution_likelihood,
)
from picoclaw_bridge import picoclaw_one_step_write, picoclaw_runtime_status
from picoclaw_environment_sidecar import picoclaw_environment_sidecar
from project_lenses import directive_target_path, load_runtime_directive as load_runtime_lens, merge_directive_text as merge_lens_text, read_text_if_exists
from script_registry import ingest_scripts, registry_status, search_scripts
from personal_system_twin import personal_system_twin
from recursive_context_distiller import context_distiller
from vector_memory import vector_memory
from ram_working_memory import RamWorkingMemory
from knowledge_library_pipeline import (
    ingest_library as ingest_knowledge_library,
    reindex_chunks_to_vector as reindex_knowledge_library_chunks,
    search as search_knowledge_library,
    seed_sources as seed_knowledge_library_sources,
    status as knowledge_library_status,
)
from kqml_protocol import (
    make_kqml_message,
    make_tool_request_message,
    make_tool_result_message,
    new_conversation_id,
    render_kqml_exchange,
)
from aider_terminal_lane import aider_terminal_lane
from heuristic_genetic_coder import genetic_coder_manager
from lava_event_orchestrator import lava_event_orchestrator
from source_role_registry import (
    rebuild_external_source_index,
    recent_source_selection_traces,
    source_role_status,
    trace_source_selection,
)
from optimization_check_registry import optimization_check_status, write_optimization_check_snapshot
from phase1_architecture_core import (
    compile_unified_template,
    emergency_stop_status,
    phase1_status,
    run_phase1_smoke_tests,
    set_emergency_stop,
    validate_objective,
    write_phase1_snapshot,
)
from fabric_wisdom_store import (
    build_fabric_guidance_block,
    ensure_fabric_tables,
    fabric_ram_status,
    fabric_wisdom_status,
    load_json_templates_from_disk,
    prune_low_weight_prompts,
    record_fabric_feedback,
    record_fabric_wisdom,
    seed_default_json_templates,
    seed_default_domains,
    try_pin_fabric_chooser_to_vram,
)
from runtime_trace import (
    ensure_runtime_trace_tables,
    recent_runtime_traces,
    record_runtime_trace,
    runtime_trace_status,
)
optimizer = None # Lazy load DSPy

# Database & Timescale Memory
from timescale_memory import memory as timescale_memory

load_dotenv()

# ===== CONFIG =====
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
USER_HOME = Path.home()
REPO_ROOT = Path(__file__).resolve().parent
DESKTOP_ENGINE_ROOT = REPO_ROOT.parent / "AIEngine"
CURSOR_EXE = os.getenv(
    "AEGIS_CURSOR_EXE",
    str(USER_HOME / "AppData" / "Local" / "Programs" / "cursor" / "Cursor.exe"),
)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///gemini_bridge.db")
CONSISTENCY_DB = os.getenv("AEGIS_CONSISTENCY_DB", str(USER_HOME / "consistency.db"))
LOCAL_ONLY_MODE = os.getenv("AEGIS_LOCAL_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_PRIMARY_MODEL = os.getenv(
    "AEGIS_LOCAL_PRIMARY_MODEL",
    "gemma4:26b-a4b-it-q8_0",
).strip() or "gemma4:26b-a4b-it-q8_0"
LOCAL_CODE_MODEL = os.getenv(
    "AEGIS_LOCAL_CODE_MODEL",
    LOCAL_PRIMARY_MODEL,
).strip() or LOCAL_PRIMARY_MODEL
LOCAL_TOOL_MODEL = os.getenv(
    "AEGIS_LOCAL_TOOL_MODEL",
    "qwen2.5-coder:1.5b",
).strip() or "qwen2.5-coder:1.5b"
LOCAL_PRIMARY_KEEP_ALIVE = os.getenv(
    "AEGIS_OLLAMA_PRIMARY_KEEP_ALIVE",
    "30m",
).strip() or "30m"
LOCAL_TOOL_KEEP_ALIVE = os.getenv(
    "AEGIS_OLLAMA_TOOL_KEEP_ALIVE",
    "8m",
).strip() or "8m"
OLLAMA_API_BASE = (
    os.getenv("AEGIS_OLLAMA_API_BASE")
    or os.getenv("OLLAMA_HOST")
    or "http://127.0.0.1:11434"
).rstrip("/")


CHOOSER_MODEL = LOCAL_PRIMARY_MODEL
DEFAULT_KERNEL_MODE = os.getenv("AEGIS_DEFAULT_MODE", "auto").strip().lower() or "auto"
VISIBLE_STATUS_UPDATES = os.getenv("AEGIS_VISIBLE_STATUS_UPDATES", "1").strip().lower() in {"1", "true", "yes", "on"}
VISIBLE_ROUND0_REPLY = os.getenv("AEGIS_VISIBLE_ROUND0_REPLY", "0").strip().lower() in {"1", "true", "yes", "on"}
CHAT_DIRECTIVE_CAPTURE_ENABLED = os.getenv("AEGIS_CHAT_DIRECTIVE_CAPTURE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
DIRECT_ROUTE_ENABLED = os.getenv("AEGIS_DIRECT_ROUTE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
FABRIC_ONLY_MODE = os.getenv("AEGIS_FABRIC_ONLY_MODE", "1").strip().lower() in {"1", "true", "yes", "on"}
FABRIC_PRUNING_ENABLED = os.getenv("AEGIS_FABRIC_PRUNING_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
FABRIC_POSITIVE_REINFORCEMENT = os.getenv("AEGIS_FABRIC_POSITIVE_REINFORCEMENT", "1").strip().lower() in {"1", "true", "yes", "on"}
# RAM working memory geofence (text-first, Fabric-centric)
RAM_WORKING_MEMORY_ENABLED = os.getenv("AEGIS_RAM_WORKING_MEMORY_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
try:
    RAM_WORKING_MEMORY_MB = max(32, min(int(os.getenv("AEGIS_RAM_WORKING_MEMORY_MB", "128")), 2048))
except ValueError:
    RAM_WORKING_MEMORY_MB = 128
try:
    RAM_WORKING_SUMMARY_SLOTS = max(1, min(int(os.getenv("AEGIS_RAM_SUMMARY_SLOTS", "10")), 100))
except ValueError:
    RAM_WORKING_SUMMARY_SLOTS = 10
try:
    RAM_WORKING_LEXICAL_SLOTS = max(1, min(int(os.getenv("AEGIS_RAM_LEXICAL_SLOTS", "10")), 100))
except ValueError:
    RAM_WORKING_LEXICAL_SLOTS = 10
try:
    RAM_WORKING_SEMANTIC_SLOTS = max(1, min(int(os.getenv("AEGIS_RAM_SEMANTIC_SLOTS", "10")), 100))
except ValueError:
    RAM_WORKING_SEMANTIC_SLOTS = 10
try:
    RAM_WORKING_LOG_SLOTS = max(1, min(int(os.getenv("AEGIS_RAM_LOG_SLOTS", "10")), 100))
except ValueError:
    RAM_WORKING_LOG_SLOTS = 10
try:
    RAM_WORKING_LAST_REPLIES_SLOTS = max(1, min(int(os.getenv("AEGIS_RAM_LAST_REPLIES_SLOTS", "20")), 200))
except ValueError:
    RAM_WORKING_LAST_REPLIES_SLOTS = 20
# In Fabric-only mode, legacy guided-script paths are hard-disabled.
if FABRIC_ONLY_MODE:
    CHAT_DIRECTIVE_CAPTURE_ENABLED = False
    DIRECT_ROUTE_ENABLED = False
AEGIS_GOOGLE_PAID_ENABLED = os.getenv("AEGIS_ENABLE_GOOGLE_PAID", "0").strip().lower() in {"1", "true", "yes", "on"}
CLOUD_EXECUTION_ENABLED = (
    AEGIS_GOOGLE_PAID_ENABLED
    and os.getenv("AEGIS_DISABLE_CLOUD", "1").strip().lower() not in {"1", "true", "yes", "on"}
)


def visible_runtime_thoughts(text: str, *, force: bool = False) -> str:
    if force or VISIBLE_STATUS_UPDATES:
        return text
    return ""


def run_powershell_text(script: str, *, timeout_seconds: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(5, int(timeout_seconds)),
    )


def recycle_stalled_ollama_runner(*, min_ram_mb: float = 1800.0) -> Dict[str, Any]:
    """Kill only the largest high-RAM Ollama runner, never the Ollama API listener."""
    script = f"""
$serverPid = $null
$conn = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {{ $serverPid = [int]$conn.OwningProcess }}
$threshold = [int64]({float(min_ram_mb)} * 1MB)
$target = Get-Process -Name ollama -ErrorAction SilentlyContinue |
  Where-Object {{ $_.Id -ne $serverPid -and $_.WorkingSet64 -ge $threshold }} |
  Sort-Object WorkingSet64 -Descending |
  Select-Object -First 1
if (-not $target) {{
  [PSCustomObject]@{{ terminated = $false; reason = "no_high_ram_runner"; server_pid = $serverPid }} | ConvertTo-Json -Compress
  exit 0
}}
$pidToStop = [int]$target.Id
$ramMb = [math]::Round($target.WorkingSet64 / 1MB, 2)
Stop-Process -Id $pidToStop -Force
[PSCustomObject]@{{
  terminated = $true
  pid = $pidToStop
  name = $target.ProcessName
  ram_mb = $ramMb
  server_pid = $serverPid
}} | ConvertTo-Json -Compress
"""
    try:
        completed = run_powershell_text(script, timeout_seconds=20)
    except Exception as exc:
        return {"terminated": False, "error": str(exc)}
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        return {
            "terminated": False,
            "error": (completed.stderr or completed.stdout or "PowerShell recovery failed").strip(),
            "returncode": completed.returncode,
        }
    try:
        parsed = json.loads(output) if output else {}
    except json.JSONDecodeError:
        parsed = {"terminated": False, "raw": output}
    return parsed if isinstance(parsed, dict) else {"terminated": False, "raw": parsed}


def ollama_model_status() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_API_BASE}/api/tags", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": str(exc), "base": OLLAMA_API_BASE}
    models = payload.get("models") or []
    names = sorted(str(item.get("name") or "") for item in models if item.get("name"))
    wanted = [LOCAL_PRIMARY_MODEL, LOCAL_CODE_MODEL, LOCAL_TOOL_MODEL]
    return {
        "ok": True,
        "base": OLLAMA_API_BASE,
        "models": names,
        "wanted": wanted,
        "available": {name: name in names for name in wanted},
        "download_note": "If a wanted model is false, Ollama has not finished or has not started that model download.",
    }


def build_logic_telemetry(
    request_profile: Dict[str, Any],
    *,
    route_name: str,
    project: str,
    elapsed_ms: Optional[int] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    logic_keys = [
        "mentions_code",
        "discussion_intent",
        "coding_action",
        "needs_coding",
        "needs_research",
        "needs_verification",
        "needs_automation",
        "needs_browser_automation",
        "needs_system_diagnosis",
        "needs_code_execution_loop",
        "planning_only",
        "requires_deliberate_mode",
        "use_targeted_web_synthesis",
        "use_research_loop",
        "needs_axiomatic_planning",
        "prefer_code_compression",
        "use_d8_compression",
        "is_configuration_directive",
        "directive_capture_applied",
        "directive_capture_suppressed",
    ]
    active_points = [key for key in logic_keys if bool(request_profile.get(key))]
    return {
        "route": route_name,
        "project": project,
        "model": model or "",
        "elapsed_ms": elapsed_ms,
        "logic_points": active_points,
        "flags": {key: bool(request_profile.get(key)) for key in logic_keys},
        "timestamp": datetime.utcnow().isoformat(),
    }


def append_feedback_conditioning(payload: Dict[str, Any]) -> Optional[str]:
    try:
        feedback_dir = Path(__file__).resolve().parent / "training_runs"
        feedback_dir.mkdir(parents=True, exist_ok=True)
        path = feedback_dir / "feedback_conditioning.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return str(path)
    except OSError:
        return None


def prompt_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def read_feedback_conditioning(limit: int = 200) -> List[Dict[str, Any]]:
    path = Path(__file__).resolve().parent / "training_runs" / "feedback_conditioning.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records: List[Dict[str, Any]] = []
    for line in lines[-max(1, min(limit, 1000)):]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


MODEL_PLANNER_ENABLED = os.getenv("AEGIS_ENABLE_MODEL_PLANNER", "0").strip().lower() in {"1", "true", "yes", "on"}
OPENAI_ESCALATION_ENABLED = os.getenv("AEGIS_OPENAI_ESCALATION_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
OPENAI_ESCALATION_MODEL = os.getenv("AEGIS_OPENAI_ESCALATION_MODEL", "gpt-5").strip() or "gpt-5"
OPENAI_API_KEY_PRESENT = bool(os.getenv("OPENAI_API_KEY", "").strip())
OPENAI_ESCALATION_AVAILABLE = OPENAI_ESCALATION_ENABLED and OPENAI_API_KEY_PRESENT
try:
    OPENAI_FILTER_TIMEOUT_SECONDS = max(5, min(int(os.getenv("AEGIS_OPENAI_FILTER_TIMEOUT_SECONDS", "45")), 180))
except ValueError:
    OPENAI_FILTER_TIMEOUT_SECONDS = 45
CLOUD_MANIFOLD_ENABLED = (
    not LOCAL_ONLY_MODE
    and os.getenv("AEGIS_CLOUD_MANIFOLD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
)
CLOUD_MANIFOLD_TRANSPORT = os.getenv("AEGIS_CLOUD_MANIFOLD_TRANSPORT", "gcloud").strip().lower() or "gcloud"
CLOUD_MANIFOLD_INSTANCE = os.getenv("AEGIS_CLOUD_MANIFOLD_INSTANCE", "ai-lean-node").strip()
CLOUD_MANIFOLD_ZONE = os.getenv("AEGIS_CLOUD_MANIFOLD_ZONE", "us-west1-b").strip()
CLOUD_MANIFOLD_HOST = os.getenv("AEGIS_CLOUD_MANIFOLD_HOST", os.getenv("AEGIS_XEON_HOST", "")).strip()
CLOUD_MANIFOLD_USER = os.getenv(
    "AEGIS_CLOUD_MANIFOLD_USER",
    os.getenv("AEGIS_XEON_USER", os.getenv("USERNAME", "aegis")),
).strip()
CLOUD_MANIFOLD_PORT = os.getenv("AEGIS_CLOUD_MANIFOLD_PORT", os.getenv("AEGIS_XEON_PORT", "22")).strip() or "22"
CLOUD_MANIFOLD_KEY_PATH = os.getenv(
    "AEGIS_CLOUD_MANIFOLD_KEY_PATH",
    os.getenv("AEGIS_XEON_KEY_PATH", str(USER_HOME / ".ssh" / "google_compute_engine")),
).strip()
CLOUD_MANIFOLD_PYTHON = os.getenv("AEGIS_CLOUD_MANIFOLD_PYTHON", os.getenv("AEGIS_XEON_PYTHON", "python3")).strip() or "python3"
CLOUD_MANIFOLD_REMOTE_DIR = (
    os.getenv("AEGIS_CLOUD_MANIFOLD_REMOTE_DIR", f"/home/{CLOUD_MANIFOLD_USER}/Aegis_Agents").strip()
    or f"/home/{CLOUD_MANIFOLD_USER}/Aegis_Agents"
)
CLOUD_MANIFOLD_TEMP_DIR = os.getenv("AEGIS_CLOUD_MANIFOLD_TEMP_DIR", "/tmp").strip() or "/tmp"
CLOUD_MANIFOLD_ALLOW_LOCAL_HANDS = os.getenv("AEGIS_CLOUD_MANIFOLD_ALLOW_LOCAL_HANDS", "0").strip().lower() in {"1", "true", "yes", "on"}
ALICE_ENABLED = (
    not LOCAL_ONLY_MODE
    and os.getenv("AEGIS_ALICE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
)
ALICE_TRANSPORT = os.getenv("AEGIS_ALICE_TRANSPORT", CLOUD_MANIFOLD_TRANSPORT).strip().lower() or CLOUD_MANIFOLD_TRANSPORT
ALICE_INSTANCE = os.getenv("AEGIS_ALICE_INSTANCE", CLOUD_MANIFOLD_INSTANCE).strip()
ALICE_ZONE = os.getenv("AEGIS_ALICE_ZONE", CLOUD_MANIFOLD_ZONE).strip()
ALICE_HOST = os.getenv("AEGIS_ALICE_HOST", CLOUD_MANIFOLD_HOST).strip()
ALICE_USER = os.getenv("AEGIS_ALICE_USER", CLOUD_MANIFOLD_USER).strip()
ALICE_PORT = os.getenv("AEGIS_ALICE_PORT", CLOUD_MANIFOLD_PORT).strip() or CLOUD_MANIFOLD_PORT
ALICE_KEY_PATH = os.getenv("AEGIS_ALICE_KEY_PATH", CLOUD_MANIFOLD_KEY_PATH).strip()
ALICE_PYTHON = os.getenv("AEGIS_ALICE_PYTHON", CLOUD_MANIFOLD_PYTHON).strip() or CLOUD_MANIFOLD_PYTHON
ALICE_REMOTE_DIR = os.getenv("AEGIS_ALICE_REMOTE_DIR", CLOUD_MANIFOLD_REMOTE_DIR).strip() or CLOUD_MANIFOLD_REMOTE_DIR
ALICE_TEMP_DIR = os.getenv("AEGIS_ALICE_TEMP_DIR", CLOUD_MANIFOLD_TEMP_DIR).strip() or CLOUD_MANIFOLD_TEMP_DIR
ALICE_MODEL = os.getenv("AEGIS_ALICE_MODEL", LOCAL_PRIMARY_MODEL).strip() or LOCAL_PRIMARY_MODEL
ALICE_TEMPERATURE = float(os.getenv("AEGIS_ALICE_TEMPERATURE", "0.8"))
GCLOUD_EXE = (
    os.getenv("AEGIS_GCLOUD_EXE")
    or shutil.which("gcloud")
    or shutil.which("gcloud.cmd")
    or str(USER_HOME / "AppData" / "Local" / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd")
)
SSH_EXE = (
    os.getenv("AEGIS_SSH_EXE")
    or shutil.which("ssh")
    or shutil.which("ssh.exe")
    or r"C:\Windows\System32\OpenSSH\ssh.exe"
)
SCP_EXE = (
    os.getenv("AEGIS_SCP_EXE")
    or shutil.which("scp")
    or shutil.which("scp.exe")
    or r"C:\Windows\System32\OpenSSH\scp.exe"
)
XEON_ENABLED = (
    not LOCAL_ONLY_MODE
    and os.getenv("AEGIS_XEON_ENABLED", "0").strip().lower() not in {"0", "false", "no", "off"}
)
XEON_HOST = os.getenv("AEGIS_XEON_HOST", "").strip()
XEON_USER = os.getenv("AEGIS_XEON_USER", os.getenv("USERNAME", "aegis")).strip()
XEON_PORT = os.getenv("AEGIS_XEON_PORT", "22").strip() or "22"
XEON_REMOTE_DIR = os.getenv("AEGIS_XEON_REMOTE_DIR", f"/home/{XEON_USER}/Aegis_Agents").strip() or f"/home/{XEON_USER}/Aegis_Agents"
XEON_PYTHON = os.getenv("AEGIS_XEON_PYTHON", "python3").strip() or "python3"
XEON_KEY_PATH = os.getenv("AEGIS_XEON_KEY_PATH", str(USER_HOME / ".ssh" / "google_compute_engine")).strip()
XEON_TEMP_DIR = os.getenv("AEGIS_XEON_TEMP_DIR", "/tmp").strip() or "/tmp"

# ===== FastAPI Setup =====
app = FastAPI(title="Aegis-DIMON Bridge v3.8.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_picoclaw_environment_sidecar():
    await asyncio.to_thread(ensure_fabric_tables)
    await asyncio.to_thread(ensure_runtime_trace_tables)
    await asyncio.to_thread(seed_default_domains, "general")
    await asyncio.to_thread(seed_default_json_templates, "general")
    await asyncio.to_thread(load_json_templates_from_disk, "general")
    if os.getenv("AEGIS_FABRIC_VRAM_CHOOSER_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
        await asyncio.to_thread(try_pin_fabric_chooser_to_vram, "general")
    await asyncio.to_thread(seed_knowledge_library_sources)
    if FABRIC_PRUNING_ENABLED:
        await asyncio.to_thread(prune_low_weight_prompts, "general", 0.35)
    await picoclaw_environment_sidecar.start(
        action_handlers={"recycle_ollama": recycle_stalled_ollama_runner}
    )


@app.on_event("shutdown")
async def shutdown_picoclaw_environment_sidecar():
    await picoclaw_environment_sidecar.stop()

# ===== Global Systems =====
# Timescale Memory System (replaces RAG)
# rag_system = EnterpriseRAGSystem()  # DEPRECATED - using timescale_memory instead

# ===== State =====
kernel_state = {
    "local_fallback_active": False,
    "fallback_until": datetime.now(),
    "last_error": None,
    "mode": DEFAULT_KERNEL_MODE # auto, cloud, manifold, xeon, alice, local
}
red_dot_state = {"active": False, "x": 0, "y": 0, "last_seen": None}
global_config = {"kernel_mode": DEFAULT_KERNEL_MODE}
chat_memory = {} # {session_id: [messages]}
MAX_TOOL_ROUNDS = 3

def _offload_ram_turn_to_vector(record: Dict[str, Any]) -> None:
    try:
        project = str(record.get("project") or "general")
        session_id = str(record.get("session_id") or "ram")
        payload = (
            "RAM_OFFLOAD_RECORD\n"
            f"ts={record.get('ts','')}\n"
            f"route={record.get('route','')}\n"
            f"prompt={str(record.get('prompt',''))[:1200]}\n"
            f"reply={str(record.get('reply',''))[:1800]}\n"
            f"thoughts={str(record.get('thoughts',''))[:600]}"
        )
        vector_memory.store(
            payload,
            project=project,
            session_id=session_id,
            subject="ram_overflow",
            kind="ram_offload",
            role="system",
            metadata={"source": "ram_working_memory"},
        )
    except Exception as exc:
        print(f"[WARN] RAM offload to vector failed: {exc}")

ram_working_memory = RamWorkingMemory(
    max_bytes=RAM_WORKING_MEMORY_MB * 1024 * 1024,
    summary_slots=RAM_WORKING_SUMMARY_SLOTS,
    lexical_slots=RAM_WORKING_LEXICAL_SLOTS,
    semantic_slots=RAM_WORKING_SEMANTIC_SLOTS,
    log_slots=RAM_WORKING_LOG_SLOTS,
    last_replies_slots=RAM_WORKING_LAST_REPLIES_SLOTS,
    offload_callback=_offload_ram_turn_to_vector,
)

def get_memory_status():
    """Check timescale memory system status"""
    try:
        if timescale_memory.base_path.exists():
            return "ACTIVE"
        return "INITIALIZING"
    except:
        return "OFFLINE"

def normalize_project(project: Optional[str]) -> str:
    value = (project or "general").strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value)
    return value.strip("-") or "general"


def normalize_kernel_mode(mode: Optional[str]) -> str:
    value = (mode or DEFAULT_KERNEL_MODE).strip().lower()
    if value not in {"auto", "cloud", "local", "manifold", "alice", "xeon"}:
        return DEFAULT_KERNEL_MODE
    if value == "cloud" and not CLOUD_EXECUTION_ENABLED:
        return "local"
    if value == "manifold" and not CLOUD_MANIFOLD_ENABLED:
        return "local"
    if value == "alice" and not ALICE_ENABLED:
        return "local"
    if value == "xeon" and not xeon_available():
        return "local"
    return value


def resolve_runtime_mode(requested_mode: str, request_profile: Optional[Dict[str, Any]] = None) -> str:
    profile = request_profile or {}
    mode = normalize_kernel_mode(requested_mode)
    if LOCAL_ONLY_MODE:
        return "local"
    if mode != "auto":
        return mode
    if profile.get("needs_automation"):
        return "local"
    if cloud_manifold_available():
        return "manifold"
    if xeon_available():
        return "xeon"
    return "local"


def runtime_priority() -> List[str]:
    if LOCAL_ONLY_MODE:
        return ["local"]
    priority = ["manifold", "xeon", "local"]
    if CLOUD_EXECUTION_ENABLED:
        priority.append("cloud")
    return priority


def runtime_labels() -> Dict[str, str]:
    if LOCAL_ONLY_MODE:
        return {
            "manifold": f"Local Blueprint Alias -> {LOCAL_PRIMARY_MODEL}",
            "xeon": "Disabled in local-only blueprint",
            "alice": f"Local ALICE Alias -> {LOCAL_PRIMARY_MODEL}",
            "local": f"Local Hands + Local Brain ({LOCAL_PRIMARY_MODEL})",
            "cloud": "CLI Cloud: Google Gemini path (manual opt-in only)",
            "auto": "Auto = local-only blueprint, local DB, local vector memory, local model",
        }
    if CLOUD_MANIFOLD_TRANSPORT == "ssh":
        manifold_label = f"Cloud Manifold: SSH worker ({CLOUD_MANIFOLD_HOST or 'unset host'})"
    else:
        manifold_label = f"Cloud Manifold: GCloud worker ({CLOUD_MANIFOLD_INSTANCE or 'unset instance'})"
    if ALICE_TRANSPORT == "ssh":
        alice_label = f"Project ALICE: SSH logic lane ({ALICE_HOST or 'unset host'})"
    else:
        alice_label = f"Project ALICE: GCloud logic lane ({ALICE_INSTANCE or 'unset instance'})"
    return {
        "manifold": manifold_label,
        "xeon": "Xeon Swarm = external SSH worker / secondary compute lane",
        "alice": alice_label,
        "local": "Local Hands: Desktop Logic & Vision",
        "cloud": "CLI Cloud: Google Gemini path (manual opt-in only)",
        "auto": "Auto = manifold first, xeon swarm second, local hands when needed, Google paid path disabled unless explicitly enabled",
    }


def alice_available() -> bool:
    if not (ALICE_ENABLED and ALICE_REMOTE_DIR and ALICE_MODEL):
        return False
    if ALICE_TRANSPORT == "ssh":
        return ssh_transport_available(ALICE_HOST, ALICE_KEY_PATH)
    if ALICE_TRANSPORT == "gcloud":
        return bool(ALICE_INSTANCE and ALICE_ZONE and gcloud_transport_available())
    return False


def xeon_available() -> bool:
    return bool(XEON_ENABLED and XEON_HOST and XEON_REMOTE_DIR and ssh_transport_available(XEON_HOST, XEON_KEY_PATH))


def xeon_workspace_dir() -> str:
    base = (XEON_REMOTE_DIR or f"/home/{XEON_USER}/Aegis_Agents").rstrip("/")
    if base.endswith("/Aegis_Agents"):
        return base
    return f"{base}/Aegis_Agents"


def gcloud_transport_available() -> bool:
    return bool(GCLOUD_EXE and Path(GCLOUD_EXE).exists())


def ssh_transport_available(host: str, key_path: str = "") -> bool:
    if not (host and SSH_EXE and Path(SSH_EXE).exists()):
        return False
    if key_path and not Path(key_path).exists():
        return False
    return True


def scp_transport_available() -> bool:
    return bool(SCP_EXE and Path(SCP_EXE).exists())


def build_ssh_target(host: str, user: str = "") -> str:
    return f"{user}@{host}" if user else host


def run_remote_command(
    transport: str,
    remote_command: str,
    *,
    instance: str = "",
    zone: str = "",
    host: str = "",
    user: str = "",
    port: str = "22",
    key_path: str = "",
    timeout: int = 900,
) -> subprocess.CompletedProcess:
    if transport == "gcloud":
        if not gcloud_transport_available():
            raise RuntimeError("gcloud CLI is not available for remote routing")
        return subprocess.run(
            [
                GCLOUD_EXE,
                "compute",
                "ssh",
                instance,
                f"--zone={zone}",
                "--strict-host-key-checking=no",
                f"--command={remote_command}",
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )

    if transport == "ssh":
        if not ssh_transport_available(host, key_path):
            raise RuntimeError("SSH routing is not configured yet")
        command = [
            SSH_EXE,
            "-p",
            str(port or "22"),
            "-o",
            "StrictHostKeyChecking=no",
        ]
        if key_path:
            command.extend(["-i", key_path])
        command.extend([build_ssh_target(host, user), remote_command])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )

    raise RuntimeError(f"Unsupported transport: {transport}")


def upload_remote_file(
    transport: str,
    local_path: str,
    remote_path: str,
    *,
    instance: str = "",
    zone: str = "",
    host: str = "",
    user: str = "",
    port: str = "22",
    key_path: str = "",
    timeout: int = 900,
) -> subprocess.CompletedProcess:
    if transport == "gcloud":
        if not gcloud_transport_available():
            raise RuntimeError("gcloud CLI is not available for remote upload")
        return subprocess.run(
            [
                GCLOUD_EXE,
                "compute",
                "scp",
                local_path,
                f"{instance}:{remote_path}",
                f"--zone={zone}",
            ],
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )

    if transport == "ssh":
        if not scp_transport_available():
            raise RuntimeError("scp is not available for SSH upload")
        command = [
            SCP_EXE,
            "-P",
            str(port or "22"),
            "-o",
            "StrictHostKeyChecking=no",
        ]
        if key_path:
            command.extend(["-i", key_path])
        command.extend([local_path, f"{build_ssh_target(host, user)}:{remote_path}"])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )

    raise RuntimeError(f"Unsupported transport: {transport}")


def parse_remote_worker_result(stdout: str, label: str) -> Dict[str, Any]:
    lines = (stdout or "").strip().splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"{label} returned no JSON payload")


def run_remote_python_worker(
    payload: Dict[str, Any],
    *,
    worker_script: str,
    remote_dir: str,
    python_exe: str,
    temp_dir: str,
    transport: str,
    label: str,
    instance: str = "",
    zone: str = "",
    host: str = "",
    user: str = "",
    port: str = "22",
    key_path: str = "",
) -> Dict[str, Any]:
    payload_json = json.dumps(payload)
    encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
    if len(encoded) <= 6000:
        remote_command = (
            f"cd {shlex.quote(remote_dir)} && "
            f"{shlex.quote(python_exe)} {shlex.quote(worker_script)} {shlex.quote(encoded)}"
        )
        result = run_remote_command(
            transport,
            remote_command,
            instance=instance,
            zone=zone,
            host=host,
            user=user,
            port=port,
            key_path=key_path,
        )
    else:
        remote_payload_name = f"aegis_payload_{worker_script}_{int(datetime.utcnow().timestamp())}.json"
        remote_payload_path = f"{temp_dir.rstrip('/')}/{remote_payload_name}"
        local_payload_path = None
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
                handle.write(payload_json)
                local_payload_path = handle.name

            upload_result = upload_remote_file(
                transport,
                local_payload_path,
                remote_payload_path,
                instance=instance,
                zone=zone,
                host=host,
                user=user,
                port=port,
                key_path=key_path,
            )
            if upload_result.returncode != 0:
                raise RuntimeError((upload_result.stderr or upload_result.stdout or f"{label} payload upload failed").strip())

            remote_command = (
                f"cd {shlex.quote(remote_dir)} && "
                f"{shlex.quote(python_exe)} {shlex.quote(worker_script)} --payload-file {shlex.quote(remote_payload_path)}; "
                f"rm -f {shlex.quote(remote_payload_path)}"
            )
            result = run_remote_command(
                transport,
                remote_command,
                instance=instance,
                zone=zone,
                host=host,
                user=user,
                port=port,
                key_path=key_path,
            )
        finally:
            if local_payload_path and Path(local_payload_path).exists():
                try:
                    Path(local_payload_path).unlink()
                except OSError:
                    pass

    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"{label} command failed").strip())
    return parse_remote_worker_result(result.stdout, label)


def runtime_feature_surface() -> Dict[str, Any]:
    relay_policy = (
        "Everything runs on this desktop in the local-only blueprint. "
        "No remote compute lane is used unless local-only mode is disabled."
        if LOCAL_ONLY_MODE
        else "Remote lanes expose the same planning, memory, research, and SOP surface. "
        "Only actions that must touch this desktop are relayed to Local Hands."
    )
    return {
        "shared_capabilities": [
            "project lanes",
            "timescale memory",
            "vector retrieval",
            "research loops",
            "secrets storage",
            "tiny sidecar delegate",
            "browser automation",
            "personal system twin",
            "systems kernels",
            "short-round ACL/KQML controller",
            "evidence-gated build summaries",
        ],
        "registered_tools": sorted(tool_registry.all_tools().keys()),
        "relay_policy": relay_policy,
        "local_only_actions": [
            "direct desktop clicks and keyboard input on this PC",
            "folder and file creation on this PC",
            "local app inspection on this PC",
        ],
        "lanes": {
            "manifold": {"available": cloud_manifold_available(), "label": runtime_labels()["manifold"]},
            "xeon": {"available": xeon_available(), "label": runtime_labels()["xeon"]},
            "alice": {"available": alice_available(), "label": runtime_labels()["alice"]},
            "local": {"available": True, "label": runtime_labels()["local"]},
            "cloud": {"available": CLOUD_EXECUTION_ENABLED, "label": runtime_labels()["cloud"]},
        },
        "sidecars": {
            "picoclaw": picoclaw_runtime_status(),
            "browser_use": browser_use_runtime_status(),
            "openai_filter_backup": {
                "enabled": OPENAI_ESCALATION_ENABLED,
                "available": openai_filter_available(),
                "model": OPENAI_ESCALATION_MODEL,
            },
        },
        "system_twin": personal_system_twin.status(),
    }


def runtime_topology_status() -> Dict[str, Any]:
    if LOCAL_ONLY_MODE:
        return {
            "topology": "local-only-blueprint",
            "local_model": LOCAL_PRIMARY_MODEL,
            "local_tool_model": LOCAL_TOOL_MODEL,
            "vector_mode": "local-qdrant",
            "remote_lanes_enabled": False,
        }
    return {
        "manifold": {
            "transport": CLOUD_MANIFOLD_TRANSPORT,
            "target": CLOUD_MANIFOLD_HOST if CLOUD_MANIFOLD_TRANSPORT == "ssh" else CLOUD_MANIFOLD_INSTANCE,
            "remote_dir": CLOUD_MANIFOLD_REMOTE_DIR,
            "temp_dir": CLOUD_MANIFOLD_TEMP_DIR,
        },
        "alice": {
            "transport": ALICE_TRANSPORT,
            "target": ALICE_HOST if ALICE_TRANSPORT == "ssh" else ALICE_INSTANCE,
            "remote_dir": ALICE_REMOTE_DIR,
            "temp_dir": ALICE_TEMP_DIR,
            "model": ALICE_MODEL,
        },
        "xeon": {
            "target": XEON_HOST,
            "remote_dir": xeon_workspace_dir(),
            "temp_dir": XEON_TEMP_DIR,
        },
    }


def known_root_directories() -> Dict[str, str]:
    user_home = str(Path.home())
    return {
        "desktop_home": user_home,
        "desktop_workspace": str(Path(__file__).resolve().parent),
        "desktop_engine": str(DESKTOP_ENGINE_ROOT),
        "desktop_onedrive": str(Path(user_home) / "OneDrive"),
        "desktop_desktop": str(Path(user_home) / "Desktop"),
        "cloud_manifold": CLOUD_MANIFOLD_REMOTE_DIR,
        "cloud_alice": ALICE_REMOTE_DIR,
        "xeon_workspace": xeon_workspace_dir(),
    }


def build_root_directory_brief() -> str:
    roots = known_root_directories()
    return (
        "Known root directories:\n"
        f"- Desktop home: {roots['desktop_home']}\n"
        f"- Aegis workspace: {roots['desktop_workspace']}\n"
        f"- AIEngine workspace: {roots['desktop_engine']}\n"
        f"- OneDrive sync: {roots['desktop_onedrive']}\n"
        f"- Desktop folder: {roots['desktop_desktop']}\n"
        f"- Cloud Manifold workspace: {roots['cloud_manifold']}\n"
        f"- Project ALICE workspace: {roots['cloud_alice']}\n"
        f"- Xeon Swarm workspace: {roots['xeon_workspace']}\n"
        "- Never guess a Documents folder or generic save path when a real path is unknown.\n"
        "- If a file was created by a tool, prefer the exact tool-returned path.\n"
        "- If the user asks where something is, answer with the known workspace roots above or say the exact path is unknown."
    )


def load_persistent_project_directive(
    project: Optional[str] = None,
    *,
    include_global: bool = False,
    include_guardian_fallback: bool = False,
) -> str:
    workspace = Path(__file__).resolve().parent
    return load_runtime_lens(
        workspace,
        project=project,
        include_global=include_global,
        include_guardian_fallback=include_guardian_fallback,
    )


def merge_project_directive_text(new_text: str, project: Optional[str] = None) -> str:
    workspace = Path(__file__).resolve().parent
    existing = read_text_if_exists(directive_target_path(workspace, project))
    return merge_lens_text(existing, new_text)


def build_alice_payload(message: str, project: str, request_profile: Dict[str, Any]) -> Dict[str, Any]:
    rooted_message = (
        "You are Project ALICE, the reasoning lane for AEGIS.\n"
        "Use deliberate hidden reasoning internally, but do not expose private chain-of-thought.\n"
        "Assume the user is the 180-kernel operator and that most prompts are performative requests for action.\n"
        "Do not qualify, patronize, or default to generic help-desk phrasing.\n"
        "Treat spelling errors, shorthand, and messy phrasing as noise to be resolved internally.\n"
        "Bias toward doing, planning, or routing the work instead of explaining why you cannot infer intent.\n"
        "For substantial tasks, maintain a recurrent internal loop: understand -> inspect -> act -> verify -> summarize.\n"
        "If a task has independent safe sub-checks, plan them in parallel before concluding.\n"
        "Keep explicit user directives pinned even if you must drop repeated context.\n"
        "If context pressure rises, ask for one compact refresh instead of fading into a blank or generic answer.\n"
        "When choosing between too little action and too much action, prefer more visible progress.\n"
        f"{build_root_directory_brief()}\n\n"
        f"Project lane: {project}\n"
        "User request:\n"
        f"{message}"
    )
    return {
        "message": rooted_message,
        "project": project,
        "request_profile": request_profile,
        "timestamp": datetime.utcnow().isoformat(),
        "model": ALICE_MODEL,
        "temperature": ALICE_TEMPERATURE,
    }


def summarize_tool_output_with_alice(raw_text: str, project: str, request_profile: Dict[str, Any], fallback_text: str) -> str:
    # Auto-summary is intentionally disabled so tool output reaches the user
    # directly without extra latency or speculative paraphrasing.
    return fallback_text


def run_cloud_alice_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    return run_remote_python_worker(
        payload,
        worker_script="cloud_alice_worker.py",
        remote_dir=ALICE_REMOTE_DIR,
        python_exe=ALICE_PYTHON,
        temp_dir=ALICE_TEMP_DIR,
        transport=ALICE_TRANSPORT,
        label="project alice",
        instance=ALICE_INSTANCE,
        zone=ALICE_ZONE,
        host=ALICE_HOST,
        user=ALICE_USER,
        port=ALICE_PORT,
        key_path=ALICE_KEY_PATH,
    )


def cloud_manifold_available() -> bool:
    if not (CLOUD_MANIFOLD_ENABLED and CLOUD_MANIFOLD_REMOTE_DIR):
        return False
    if CLOUD_MANIFOLD_TRANSPORT == "ssh":
        return ssh_transport_available(CLOUD_MANIFOLD_HOST, CLOUD_MANIFOLD_KEY_PATH)
    if CLOUD_MANIFOLD_TRANSPORT == "gcloud":
        return bool(CLOUD_MANIFOLD_INSTANCE and CLOUD_MANIFOLD_ZONE and gcloud_transport_available())
    return False


def build_xeon_payload(message: str, project: str, request_profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message": message,
        "project": project,
        "action": "research" if request_profile.get("needs_research") else "plan",
        "request_profile": request_profile,
        "max_results": 5,
        "max_pages": 4,
        "runtime": "xeon_swarm",
        "timestamp": datetime.utcnow().isoformat(),
    }


def run_xeon_swarm_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not xeon_available():
        raise RuntimeError("Xeon swarm routing is not configured yet")
    return run_remote_python_worker(
        payload,
        worker_script="cloud_manifold_worker.py",
        remote_dir=xeon_workspace_dir(),
        python_exe=XEON_PYTHON,
        temp_dir=XEON_TEMP_DIR,
        transport="ssh",
        label="xeon swarm",
        host=XEON_HOST,
        user=XEON_USER,
        port=XEON_PORT,
        key_path=XEON_KEY_PATH,
    )


def build_cloud_manifold_payload(message: str, project: str, request_profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message": message,
        "project": project,
        "action": "research" if request_profile.get("needs_research") else "plan",
        "request_profile": request_profile,
        "max_results": 5,
        "max_pages": 4,
        "timestamp": datetime.utcnow().isoformat(),
    }


def run_cloud_manifold_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    return run_remote_python_worker(
        payload,
        worker_script="cloud_manifold_worker.py",
        remote_dir=CLOUD_MANIFOLD_REMOTE_DIR,
        python_exe=CLOUD_MANIFOLD_PYTHON,
        temp_dir=CLOUD_MANIFOLD_TEMP_DIR,
        transport=CLOUD_MANIFOLD_TRANSPORT,
        label="cloud manifold",
        instance=CLOUD_MANIFOLD_INSTANCE,
        zone=CLOUD_MANIFOLD_ZONE,
        host=CLOUD_MANIFOLD_HOST,
        user=CLOUD_MANIFOLD_USER,
        port=CLOUD_MANIFOLD_PORT,
        key_path=CLOUD_MANIFOLD_KEY_PATH,
    )

def project_session_key(session_id: str, project: str) -> str:
    return f"{session_id}::{project}"

def extract_project_override(message: str, fallback_project: str) -> tuple[str, str]:
    if not message.lower().startswith("/project "):
        return fallback_project, message

    remainder = message[len("/project "):].strip()
    if not remainder:
        return fallback_project, message

    parts = remainder.split(" ", 1)
    project = normalize_project(parts[0])
    stripped_message = parts[1].strip() if len(parts) > 1 else ""
    return project, stripped_message or message


def extract_focus_keywords(text: str, limit: int = 8) -> List[str]:
    stopwords = {
        "about", "after", "agent", "because", "before", "could", "everything",
        "please", "project", "should", "thanks", "thank", "their", "there",
        "these", "thing", "things", "using", "want", "with", "would", "your",
    }
    tokens = re.findall(r"[A-Za-z0-9_]{4,}", normalize_prompt_text(text))
    keywords: List[str] = []
    for token in tokens:
        if token in stopwords or token in keywords:
            continue
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def reduce_context_sections(
    context_text: str,
    prompt: str,
    max_sections: int = 3,
    max_section_chars: int = 520,
    max_total_chars: int = 1400,
) -> str:
    sections = [section.strip() for section in (context_text or "").split("\n\n") if section.strip()]
    if not sections:
        return ""

    focus_keywords = extract_focus_keywords(prompt, limit=10)
    section_records = []
    for index, section in enumerate(sections):
        normalized = normalize_prompt_text(section)
        score = sum(1 for keyword in focus_keywords if keyword in normalized)
        if "recent reasoning notes" in normalized:
            score += 3
        if "directory signatures" in normalized:
            score += 2
        if "vector matches" in normalized:
            score += 1
        section_records.append(
            {
                "score": float(score),
                "index": index,
                "section": section[:max_section_chars],
                "tokens": set(re.findall(r"[A-Za-z0-9_]{4,}", normalized)),
            }
        )

    selected = []
    while section_records and len(selected) < max_sections:
        best_record = None
        best_value = None
        for record in section_records:
            novelty_penalty = 0.0
            if selected and record["tokens"]:
                novelty_penalty = max(
                    (
                        len(record["tokens"] & existing["tokens"]) /
                        max(1, len(record["tokens"] | existing["tokens"]))
                    )
                    for existing in selected
                )
            value = record["score"] - (1.25 * novelty_penalty)
            if best_record is None or value > best_value:
                best_record = record
                best_value = value

        if best_record is None:
            break
        selected.append(best_record)
        section_records = [record for record in section_records if record is not best_record]

    selected.sort(key=lambda item: item["index"])

    kept: List[str] = []
    consumed = 0
    for record in selected:
        remaining = max_total_chars - consumed
        if remaining <= 0:
            break
        clipped = str(record["section"])[:remaining].rstrip()
        kept.append(clipped)
        consumed += len(clipped) + 2

    return "\n\n".join(kept)


def summarize_recent_history(messages: List[Dict], max_items: int = 4, max_chars: int = 500) -> str:
    candidates: List[tuple[float, str]] = []
    focus_keywords = extract_focus_keywords(" ".join((item.get("content") or "") for item in (messages or [])[-6:]), limit=6)
    for item in messages or []:
        role = item.get("role") or "user"
        content = (item.get("content") or "").strip()
        if not content:
            continue
        condensed = compress_signal_text(content, focus_keywords=focus_keywords, max_sentences=2, max_chars=180) or content[:180]
        snippet = f"- {role}: {condensed}"
        score = 1.0
        if role == "user":
            score += 2.0
        if has_directive_signal(condensed):
            score += 3.5
        if role == "assistant" and re.search(r"\b(updated|created|verified|found|changed|patched|tested|running)\b", normalize_prompt_text(condensed)):
            score += 2.0
        candidates.append((score, snippet))
    candidates.sort(key=lambda item: -item[0])
    return "\n".join(dedupe_text_items([item[1] for item in candidates], max_items=max_items, max_chars=max_chars))


def summarize_reasoning_notes(project: str, limit: int = 2) -> str:
    notes = timescale_memory.recent_reasoning_notes(project, limit=limit)
    if not notes:
        return ""

    lines = []
    focus_keywords = extract_focus_keywords(" ".join((note.get("content") or "") for note in notes[:limit]), limit=6)
    for note in notes[:limit]:
        content = (note.get("content") or "").strip()
        if not content:
            continue
        content = content.replace("\r", "")
        content = re.sub(r"\n{2,}", "\n", content)
        compressed = compress_signal_text(content, focus_keywords=focus_keywords, max_sentences=3, max_chars=220) or content[:220]
        lines.append(f"- {compressed}")
    return "\n".join(dedupe_text_items(lines, max_items=limit, max_chars=500))


def compress_signal_text(text: str, focus_keywords: Optional[List[str]] = None, max_sentences: int = 6, max_chars: int = 900) -> str:
    source = (text or "").strip()
    if not source:
        return ""

    normalized_source = re.sub(r"\s+", " ", source)
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", normalized_source)
    keywords = [item.lower() for item in (focus_keywords or []) if item]
    selected: List[tuple[float, str]] = []
    seen_signatures = set()

    for sentence in raw_sentences:
        clean = sentence.strip(" -")
        if len(clean) < 18:
            continue
        signature = re.sub(r"[^a-z0-9]+", " ", clean.lower()).strip()
        signature = " ".join(signature.split()[:14])
        if not signature or signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        score = 1.0
        lowered = clean.lower()
        score += sum(2.0 for keyword in keywords if keyword and keyword in lowered)
        if "objective:" in lowered or "steps:" in lowered or "done when:" in lowered:
            score += 2.5
        if "project:" in lowered or "summary:" in lowered:
            score += 1.5
        selected.append((score, clean))

    selected.sort(key=lambda item: (-item[0], -len(item[1])))

    kept: List[str] = []
    consumed = 0
    for _score, sentence in selected[:max_sentences]:
        if consumed + len(sentence) > max_chars:
            break
        kept.append(sentence)
        consumed += len(sentence) + 1

    return " ".join(kept).strip()


DIRECTIVE_SIGNAL_PATTERNS = (
    r"\bmust\b",
    r"\bneed(?:s)? to\b",
    r"\bshould\b",
    r"\balways\b",
    r"\bnever\b",
    r"\bkeep\b",
    r"\buse\b",
    r"\bprefer\b",
    r"\bavoid\b",
    r"\bmake sure\b",
    r"\bdo not\b",
    r"\bdon't\b",
    r"\bwant\b",
    r"\bonly if\b",
    r"\bif and only if\b",
    r"\bfallback\b",
    r"\bstay\b",
)


def text_signature(text: str, limit_words: int = 14) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", normalize_prompt_text(text or "")).strip()
    return " ".join(normalized.split()[:limit_words])


def has_directive_signal(text: str) -> bool:
    lowered = normalize_prompt_text(text or "")
    if not lowered:
        return False
    return any(re.search(pattern, lowered) for pattern in DIRECTIVE_SIGNAL_PATTERNS)


def dedupe_text_items(items: List[str], max_items: int, max_chars: int) -> List[str]:
    kept: List[str] = []
    seen = set()
    consumed = 0
    for item in items:
        clean = re.sub(r"\s+", " ", (item or "")).strip()
        if not clean:
            continue
        signature = text_signature(clean)
        if not signature or signature in seen:
            continue
        next_cost = len(clean)
        if len(kept) >= max_items or consumed + next_cost > max_chars:
            break
        seen.add(signature)
        kept.append(clean)
        consumed += next_cost + 1
    return kept


def score_sticky_directive(text: str, focus_keywords: Optional[List[str]] = None) -> float:
    lowered = normalize_prompt_text(text or "")
    if not lowered:
        return 0.0

    score = 1.0
    if has_directive_signal(lowered):
        score += 4.0
    if "explicitly said" in lowered or "need to stay" in lowered:
        score += 4.0
    if "context window" in lowered or "context" in lowered or "compression" in lowered:
        score += 2.0
    if "too much action" in lowered or "too much of a reply" in lowered or "borderline annoying" in lowered:
        score += 3.0
    if focus_keywords:
        score += sum(1.5 for keyword in focus_keywords if keyword and keyword in lowered)
    return score


def extract_sticky_directives(
    prompt: str,
    history: List[Dict],
    context_text: str,
    reasoning_digest: str,
    max_items: int = 8,
    max_chars: int = 800,
) -> List[str]:
    focus_keywords = extract_focus_keywords(prompt, limit=8)
    candidates: List[tuple[float, str]] = []

    def add_candidates(raw_text: str, source_bias: float = 0.0) -> None:
        normalized = (raw_text or "").replace("\r", "\n")
        if not normalized.strip():
            return
        parts = re.split(r"(?<=[.!?])\s+|\n+", normalized)
        for part in parts:
            clean = re.sub(r"\s+", " ", part).strip(" -*")
            if len(clean) < 16 or len(clean) > 260:
                continue
            if not has_directive_signal(clean):
                continue
            candidates.append((score_sticky_directive(clean, focus_keywords) + source_bias, clean))

    add_candidates(prompt, source_bias=5.0)
    add_candidates(reasoning_digest, source_bias=2.0)
    add_candidates(context_text, source_bias=1.0)

    for item in history or []:
        role = item.get("role") or "user"
        add_candidates(item.get("content") or "", source_bias=3.0 if role == "user" else 1.5)

    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return dedupe_text_items([item[1] for item in candidates], max_items=max_items, max_chars=max_chars)


def build_context_window_advice(
    prompt: str,
    context_text: str,
    history: List[Dict],
    sticky_directives: List[str],
) -> str:
    pressure_score = 0
    if len((prompt or "").strip()) > 450:
        pressure_score += 1
    if len((context_text or "").strip()) > 1200:
        pressure_score += 1
    if sum(len((item.get("content") or "").strip()) for item in history or []) > 1400:
        pressure_score += 1
    if len(sticky_directives) >= 5:
        pressure_score += 1

    if pressure_score <= 1:
        return (
            "Context control: keep only the pinned directives plus the smallest set of facts needed to act. "
            "Drop repeated context silently."
        )
    return (
        "Context control: pressure is elevated. Keep pinned directives, the current goal, target paths, and newest verified facts. "
        "Discard repetition and stale retrieval. If more context is still needed, ask the user for one compact refresh instead of stalling."
    )


def build_global_reduction_brief(
    prompt: str,
    project: str,
    request_profile: Dict[str, Any],
    context_text: str,
    history: List[Dict],
) -> str:
    focus_keywords = extract_focus_keywords(prompt, limit=6)
    reduced_context = reduce_context_sections(context_text, prompt)
    sticky_directives = extract_sticky_directives(
        prompt=prompt,
        history=(history or [])[-4:],
        context_text="",
        reasoning_digest="",
        max_items=2,
        max_chars=160,
    )
    persistent_directive = load_persistent_project_directive(
        project=project,
        include_global=bool(request_profile.get("needs_automation")),
        include_guardian_fallback=bool(request_profile.get("needs_automation")),
    )
    compressed_history = ""
    if request_profile.get("is_multi_step") or request_profile.get("needs_automation"):
        reduced_history = summarize_recent_history((history or [])[-4:])
        compressed_history = compress_signal_text(
            reduced_history,
            focus_keywords=focus_keywords,
            max_sentences=2,
            max_chars=160,
        )
    compressed_context = compress_signal_text(
        reduced_context,
        focus_keywords=focus_keywords,
        max_sentences=4,
        max_chars=480,
    )
    coding_kernel = ""
    if request_profile.get("needs_coding"):
        coding_kernel = build_coding_kernel_brief(
            Path(__file__).resolve().parent,
            prompt,
            project=project,
            context_text=reduced_context,
            max_languages=2,
            max_chars=1100,
        )
    systems_kernel = ""
    if (
        request_profile.get("needs_coding")
        or request_profile.get("needs_automation")
        or request_profile.get("needs_system_diagnosis")
        or request_profile.get("needs_browser_automation")
        or request_profile.get("needs_code_execution_loop")
    ):
        systems_kernel = build_systems_kernel_brief(
            Path(__file__).resolve().parent,
            prompt,
            project=project,
            context_text=reduced_context,
            max_domains=4,
            max_chars=1300,
        )
    response_contract = build_response_contract(request_profile)
    axiom_brief = ""
    if request_profile.get("needs_axiomatic_planning") or request_profile.get("needs_coding") or request_profile.get("is_multi_step"):
        axiom_brief = format_axiom_processing_brief(prompt, request_profile=request_profile)
    workspace_hint = ""
    if request_profile.get("prefer_single_workspace"):
        workspace_hint = str(default_program_target_dir(Path(__file__).resolve().parent, project, prompt))

    blocks = [
        "BRIEF",
        f"Project: {project}",
        f"Objective: {prompt[:180].strip()}",
        "Prefer the current task state. Ignore stale or repeated context.",
    ]
    if sticky_directives:
        blocks.append("Pinned:")
        blocks.extend(f"- {item}" for item in sticky_directives)
    if persistent_directive:
        blocks.extend(["Directive:", persistent_directive])
    if compressed_history:
        blocks.extend(["Recent:", compressed_history])
    if compressed_context:
        blocks.extend(["Context:", compressed_context])
    if response_contract:
        blocks.extend(["Contract:", response_contract])
    if axiom_brief:
        blocks.extend(["Axiom frame:", axiom_brief])
    if workspace_hint:
        blocks.append(f"Stable workspace: {workspace_hint}")
    if coding_kernel:
        blocks.append(coding_kernel)
    if systems_kernel:
        blocks.append(systems_kernel)
    return "\n".join(blocks).strip()


def build_planner_prompt(project: str, request_profile: Dict[str, Any]) -> str:
    rules = [
        "- Break the task into 3 to 6 concrete phases.",
        "- Keep the end goal explicit.",
        "- Prefer: understand -> research -> inspect -> act -> verify -> summarize.",
        "- Treat the user as the high-agency operator; default to execution-oriented interpretation instead of passive Q&A framing.",
        "- If multiple checks are independent and safe, prefer a parallel first pass.",
        "- For long workflows, keep a recurrent loop until the done_when conditions are actually satisfied.",
        "- Use at most 4 initial tool calls and only if they reduce uncertainty.",
        "- Treat spelling mistakes as noise and infer the intended task.",
        "- Reduce noisy context to high-signal facts before planning.",
        "- Keep explicit user directives pinned even if older context is dropped.",
        "- If context pressure is high, ask for one compact refresh instead of going blank.",
        "- When deciding between under-responding and over-responding, prefer more visible progress.",
    ]
    if request_profile.get("needs_coding"):
        rules.append("- For coding tasks, decompose the request into ask set, program set, axioms, logic blocks, and acceptance tests.")
    if request_profile.get("use_logic_block_table"):
        rules.append("- Keep logic blocks small, movable, and assignable to explicit worker packets.")
    if request_profile.get("prefer_code_compression"):
        rules.append("- Prefer compact, flattened, compiler-friendly code paths over decorative abstraction.")
    if request_profile.get("use_targeted_web_synthesis"):
        rules.append("- When research supports code, target exact flags, parameters, and implementation constraints instead of broad summaries.")

    return (
        f"You are the AEGIS execution planner for project lane {project}.\n"
        "Return JSON only.\n"
        "Schema:\n"
        "{\n"
        '  "end_goal": "string",\n'
        '  "task_type": "research|coding|ops|automation|mixed",\n'
        '  "needs_research": true,\n'
        '  "needs_coding": false,\n'
        '  "needs_verification": true,\n'
        '  "assumptions": ["string"],\n'
        '  "steps": ["string"],\n'
        '  "tool_calls": [{"tool": "name", "parameters": {}}],\n'
        '  "done_when": ["string"]\n'
        "}\n"
        "Rules:\n"
        f"{chr(10).join(rules)}\n"
        f"{build_root_directory_brief()}\n"
        f"- Request profile: {json.dumps(request_profile, indent=2)}"
    )


def infer_task_type(request_profile: Dict[str, Any]) -> str:
    if request_profile.get("needs_automation"):
        return "automation"
    if request_profile.get("needs_system_diagnosis"):
        return "ops"
    if request_profile.get("needs_research") and request_profile.get("needs_coding"):
        return "mixed"
    if request_profile.get("needs_research"):
        return "research"
    if request_profile.get("needs_coding"):
        return "coding"
    return "mixed"


def build_fast_execution_plan(prompt: str, project: str, request_profile: Dict[str, Any]) -> Dict[str, Any]:
    focus_keywords = extract_focus_keywords(prompt, limit=6)
    task_type = infer_task_type(request_profile)
    steps: List[str] = ["Reduce the request into the real end goal and ignore spelling noise."]
    tool_calls: List[Dict[str, Any]] = []
    assumptions = [f"Project lane is {project}."]
    done_when = ["The response stays tied to the explicit end goal instead of generic filler."]

    if request_profile.get("needs_system_diagnosis"):
        steps.append("Inspect runtime health, duplicate processes, and cleanup signals.")
        tool_calls.append(
            {
                "tool": "run_system_heartbeat",
                "parameters": {
                    "cleanup_temp": False,
                    "kill_extra_gemini_cli": True,
                    "temp_days": 2,
                },
            }
        )
        done_when.append("System bottlenecks are named with evidence.")

    if request_profile.get("needs_research") or request_profile.get("use_targeted_web_synthesis"):
        steps.append("Gather the most credible recent evidence before making claims.")
        tool_calls.append(
            {
                "tool": "search_web",
                "parameters": {
                    "query": " ".join(
                        focus_keywords[:5] or ["credible", "technical", "guidance"]
                    )
                },
            }
        )
        done_when.append("Claims are grounded in credible sources or project memory.")
        if request_profile.get("use_targeted_web_synthesis"):
            steps.append("Extract only exact flags, parameters, and implementation constraints from the research that materially affect the build.")
            done_when.append("Research findings are reduced to actionable implementation facts instead of broad summaries.")

    if request_profile.get("needs_coding"):
        steps.append("Inspect project memory or code context before proposing changes.")
        workspace_hint = str(default_program_target_dir(Path(__file__).resolve().parent, project, prompt))
        tool_calls.append(
            {
                "tool": "search_project_memory",
                "parameters": {
                    "query": " ".join(focus_keywords[:5] or ["recent", "project", "coding", "constraints"]),
                    "project": project or "general",
                },
            }
        )
        if request_profile.get("use_logic_block_table"):
            steps.append("Reduce the request into ask set, program set, explicit logic blocks, and owned files before editing code.")
            done_when.append("The implementation plan names logic blocks, file ownership, and acceptance tests.")
        if request_profile.get("prefer_code_compression"):
            steps.append("Prefer compact, flattened, compiler-friendly code paths while keeping the result readable and runnable.")
        if project and project != "general":
            tool_calls.append(
                {
                    "tool": "search_project_memory",
                    "parameters": {
                        "query": " ".join(focus_keywords[:5] or ["recent", "project", "changes"]),
                        "project": project,
                    },
                }
            )
        if request_profile.get("needs_code_execution_loop"):
            kernel_brief = build_coding_kernel_brief(
                Path(__file__).resolve().parent,
                prompt,
                project=project,
                max_languages=1,
                max_chars=900,
            )
            systems_brief = build_systems_kernel_brief(
                Path(__file__).resolve().parent,
                prompt,
                project=project,
                max_domains=4,
                max_chars=900,
            )
            tool_calls.append(
                {
                    "tool": "delegate_picoclaw",
                    "parameters": {
                        "prompt": (
                            "*Intent: create a first verified code plan and compact candidate for the user request.*\n\n"
                            f"User request: {prompt}\n"
                            f"Project: {project}\n"
                            f"Workspace hint: {workspace_hint}\n\n"
                            "Partition the work into logic blocks. Use the distilled coding kernel below. "
                            "Use the systems kernel below for real-world constraints. "
                            "Produce the smallest runnable candidate or exact blocker, plus tests/evidence. "
                            "Do not claim files were saved unless a tool actually saved them.\n\n"
                            f"{kernel_brief}\n\n{systems_brief}"
                        ),
                        "workspace": workspace_hint,
                        "session": f"{project}:build-loop",
                        "timeout_seconds": 120,
                    },
                }
            )
        done_when.append("The answer includes concrete implementation direction.")

    if request_profile.get("needs_verification"):
        steps.append("Verify the fix, result, or next best action before wrapping up.")
        done_when.append("The reply includes an explicit verification section.")

    if request_profile.get("needs_automation"):
        steps.append("Keep the workflow moving in phases instead of answering once and stopping.")
        done_when.append("The reply names the next actionable step in the loop.")

    if request_profile.get("wants_full_response"):
        steps.append("Keep the answer complete and explicit instead of ending after the first partial draft.")
        done_when.append("The response is materially complete rather than clipped.")

    if request_profile.get("must_make_code_run"):
        steps.append("Use one stable program workspace and keep iterating until the code runs or the blocker is explicit.")
        assumptions.append("Use one stable test workspace instead of scattered scratch files.")
        done_when.append("The code runs or the exact blocker and latest verification result are stated plainly.")
    if request_profile.get("needs_axiomatic_planning"):
        assumptions.append("Use axioms and constraint sets as the working decomposition for the build.")

    if request_profile.get("use_research_loop"):
        steps.append("Stay in the research loop until enough evidence is gathered to support the implementation or answer.")
        done_when.append("Research continues until the evidence is sufficient for a grounded answer.")

    steps.append("Summarize the result with the end goal, changes, verification, and next step.")

    deduped_steps: List[str] = []
    for step in steps:
        if step not in deduped_steps:
            deduped_steps.append(step)

    deduped_done_when: List[str] = []
    for item in done_when:
        if item not in deduped_done_when:
            deduped_done_when.append(item)

    seen_tools = set()
    deduped_tool_calls: List[Dict[str, Any]] = []
    for item in tool_calls:
        tool_name = str(item.get("tool", "")).strip()
        if not tool_name or tool_name in seen_tools:
            continue
        seen_tools.add(tool_name)
        deduped_tool_calls.append(item)

    return {
        "end_goal": prompt[:240].strip(),
        "task_type": task_type,
        "needs_research": bool(request_profile.get("needs_research")),
        "needs_coding": bool(request_profile.get("needs_coding")),
        "needs_verification": bool(request_profile.get("needs_verification")),
        "assumptions": assumptions[:4],
        "steps": deduped_steps[:6],
        "tool_calls": deduped_tool_calls[:4],
        "done_when": deduped_done_when[:4],
    }


def build_short_round_controller(prompt: str, project: str, request_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic ACL/KQML-style short-round controller.

    This keeps the first user-visible response fast, then lets the runtime
    choose the first useful tools instead of waiting for model obedience.
    """
    plan = build_fast_execution_plan(prompt, project, request_profile)
    systems_domains = detect_system_domains(prompt, project=project, limit=4)
    systems_kernel = build_systems_kernel_brief(
        Path(__file__).resolve().parent,
        prompt,
        project=project,
        max_domains=4,
        max_chars=1100,
    )
    coding_kernel = ""
    if request_profile.get("needs_coding"):
        coding_kernel = build_coding_kernel_brief(
            Path(__file__).resolve().parent,
            prompt,
            project=project,
            max_languages=2,
            max_chars=900,
        )
    packet = {
        "performative": "achieve",
        "sender": "aegis-short-round-controller",
        "receiver": "aegis-runtime",
        "reply_with": "evidence-gated-summary",
        "ontology": "short-round-build-loop",
        "content": {
            "ask_set": build_axiom_processing_frame(prompt, request_profile=request_profile).get("ask_set", []),
            "intent_set": {
                "coding": bool(request_profile.get("needs_coding")),
                "research": bool(request_profile.get("needs_research") or request_profile.get("use_targeted_web_synthesis")),
                "automation": bool(request_profile.get("needs_automation")),
                "system": bool(request_profile.get("needs_system_diagnosis")),
            },
            "kernel_set": {
                "systems": systems_domains,
                "coding_loaded": bool(coding_kernel),
                "systems_loaded": bool(systems_kernel),
            },
            "tool_set": [item.get("tool") for item in plan.get("tool_calls", [])],
            "evidence_set": [],
            "state_set": {
                "phase": "round_0_ack",
                "project": project,
                "objective": prompt[:240].strip(),
                "next_action": "round_2_tools" if plan.get("tool_calls") else "round_3_model",
            },
        },
    }
    if request_profile.get("needs_code_execution_loop"):
        round0 = (
            "I’ll split this into a short build loop: first I’ll load the coding and systems kernels, "
            "then run the needed tools/PicoClaw pass, then come back with evidence instead of guessing.\n\n"
        )
    elif request_profile.get("requires_deliberate_mode"):
        round0 = "I’ll take this in short rounds so you get progress quickly, then I’ll verify the next step before summarizing.\n\n"
    else:
        round0 = ""
    return {
        "round0_reply": round0,
        "packet": packet,
        "execution_plan": plan,
        "systems_kernel": systems_kernel,
        "coding_kernel": coding_kernel,
    }


def should_use_model_planner(prompt: str, request_profile: Dict[str, Any]) -> bool:
    if not MODEL_PLANNER_ENABLED:
        return False
    prompt_length = len((prompt or "").strip())
    signal_count = sum(
        int(bool(request_profile.get(key)))
        for key in (
            "needs_research",
            "needs_coding",
            "needs_verification",
            "needs_automation",
            "needs_system_diagnosis",
        )
    )
    if prompt_length >= 260:
        return True
    if signal_count >= 4:
        return True
    if request_profile.get("needs_research") and request_profile.get("needs_system_diagnosis"):
        return True
    return False


def parse_execution_plan(response: str) -> Optional[Dict[str, Any]]:
    parsed = parse_tool_call(response)
    if not isinstance(parsed, dict):
        return None

    end_goal = str(parsed.get("end_goal", "")).strip()
    steps = parsed.get("steps")
    if not end_goal or not isinstance(steps, list):
        return None

    clean_steps = [
        str(step).strip()
        for step in steps
        if str(step).strip()
    ][:6]
    if not clean_steps:
        return None

    clean_tool_calls = []
    if isinstance(parsed.get("tool_calls"), list):
        clean_tool_calls = [
            item for item in parsed.get("tool_calls", [])
            if isinstance(item, dict) and str(item.get("tool", "")).strip()
        ][:4]

    assumptions = [
        str(item).strip()
        for item in parsed.get("assumptions", [])
        if str(item).strip()
    ][:4] if isinstance(parsed.get("assumptions"), list) else []
    done_when = [
        str(item).strip()
        for item in parsed.get("done_when", [])
        if str(item).strip()
    ][:4] if isinstance(parsed.get("done_when"), list) else []

    return {
        "end_goal": end_goal[:240],
        "task_type": str(parsed.get("task_type", "mixed")).strip() or "mixed",
        "needs_research": bool(parsed.get("needs_research", False)),
        "needs_coding": bool(parsed.get("needs_coding", False)),
        "needs_verification": bool(parsed.get("needs_verification", False)),
        "assumptions": assumptions,
        "steps": clean_steps,
        "tool_calls": clean_tool_calls,
        "done_when": done_when,
    }


def format_execution_plan_summary(plan: Dict[str, Any]) -> str:
    lines = [
        f"End goal: {plan.get('end_goal', '')}",
        f"Task type: {plan.get('task_type', 'mixed')}",
        "Steps:",
    ]
    for index, step in enumerate(plan.get("steps", []), start=1):
        lines.append(f"{index}. {step}")
    if plan.get("done_when"):
        lines.append("Done when:")
        for item in plan.get("done_when", []):
            lines.append(f"- {item}")
    return "\n".join(lines)


def build_execution_user_prompt(
    prompt: str,
    plan: Optional[Dict[str, Any]],
    request_profile: Optional[Dict[str, Any]] = None,
    project: str = "general",
) -> str:
    if not plan:
        return prompt
    request_profile = request_profile or {}
    contract_text = build_response_contract(request_profile)
    axiom_frame = ""
    if request_profile.get("needs_axiomatic_planning") or request_profile.get("needs_coding") or request_profile.get("is_multi_step"):
        axiom_frame = json.dumps(
            build_axiom_processing_frame(prompt, request_profile=request_profile),
            indent=2,
        )
    workspace_hint = ""
    if request_profile.get("prefer_single_workspace"):
        workspace_hint = str(default_program_target_dir(Path(__file__).resolve().parent, project, prompt))
    return (
        f"Original user request:\n{prompt}\n\n"
        + "Execution plan:\n"
        + f"{json.dumps(plan, indent=2)}\n\n"
        + (f"Execution contract:\n{contract_text}\n\n" if contract_text else "")
        + (f"Axiom frame:\n{axiom_frame}\n\n" if axiom_frame else "")
        + (f"Stable workspace:\n{workspace_hint}\n\n" if workspace_hint else "")
        + "Carry out this plan. Keep the end goal visible. Use tools when they reduce uncertainty. "
        + (
            "For build-loop work, do not end after the first draft: partition, tool-call, self-question the latest code/proposal, apply the answer, reinitialize to the current partition/evidence, then summarize. "
            if request_profile.get("needs_code_execution_loop")
            else ""
        )
        + "If another research or verification step is still needed, continue the loop instead of stopping early."
    )


def build_tool_follow_up_prompt(
    tool_context_blocks: List[str],
    tool_round: int,
    tool_round_limit: int,
    plan: Optional[Dict[str, Any]],
    request_profile: Optional[Dict[str, Any]] = None,
    prompt: str = "",
    project: str = "general",
) -> str:
    plan_text = format_execution_plan_summary(plan) if plan else "No explicit execution plan was captured."
    request_profile = request_profile or {}
    contract_text = build_response_contract(request_profile) or "No extra completion contract was captured."
    axiom_frame = ""
    if request_profile.get("needs_axiomatic_planning") or request_profile.get("needs_coding") or request_profile.get("is_multi_step"):
        axiom_frame = json.dumps(
            build_axiom_processing_frame(prompt, request_profile=request_profile),
            indent=2,
        )
    workspace_hint = ""
    if request_profile.get("prefer_single_workspace"):
        workspace_hint = str(default_program_target_dir(Path(__file__).resolve().parent, project, prompt))
    return (
        "The following KQML tool exchanges were executed.\n\n"
        + "\n\n".join(tool_context_blocks)
        + "\n\nExecution plan summary:\n"
        + plan_text
        + "\n\nExecution contract:\n"
        + contract_text
        + (f"\n\nAxiom frame:\n{axiom_frame}" if axiom_frame else "")
        + (f"\n\nStable workspace:\n{workspace_hint}" if workspace_hint else "")
        + "\n\nContinue the loop."
        + f" You are on tool round {tool_round} of {tool_round_limit}."
        + (
            " For build-loop work, partition the latest evidence into code blocks, ask one internal question about the last code/proposal, answer it, apply that answer to the next code/proposal, then reinitialize context to only: user objective, partition, latest tool evidence, and verification state."
            if request_profile.get("needs_code_execution_loop")
            else ""
        )
        + " If more evidence, inspection, or verification is still needed, make the next JSON tool call."
        + " Do not treat the answer as finished until the execution contract is satisfied."
        + " Otherwise answer in normal prose with these sections: End Goal, What Changed, Verification, Next Best Step."
    )


def build_code_loop_self_review_prompt(
    tool_context_blocks: List[str],
    *,
    prompt: str,
    project: str,
    plan: Optional[Dict[str, Any]],
    request_profile: Optional[Dict[str, Any]] = None,
) -> str:
    request_profile = request_profile or {}
    plan_text = format_execution_plan_summary(plan) if plan else "No explicit execution plan was captured."
    axiom_frame = json.dumps(
        build_axiom_processing_frame(prompt, request_profile=request_profile),
        indent=2,
    )
    evidence = "\n\n".join(tool_context_blocks[-6:]) if tool_context_blocks else "No tool evidence was captured."
    workspace_hint = str(default_program_target_dir(Path(__file__).resolve().parent, project, prompt))
    return (
        "Build-loop self-review checkpoint.\n\n"
        f"Original user request:\n{prompt}\n\n"
        f"Project: {project}\n"
        f"Stable workspace: {workspace_hint}\n\n"
        f"Execution plan summary:\n{plan_text}\n\n"
        f"Axiom frame:\n{axiom_frame}\n\n"
        f"Latest tool evidence:\n{evidence}\n\n"
        "Do not end with vague confidence. Reinitialize context to only the objective, partition, latest tool evidence, and verification state.\n"
        "Ask one internal question about the latest code/proposal, answer it, and apply that answer to the next candidate or plan.\n"
        "If another tool is required, emit JSON only for that tool call. Otherwise answer in normal prose with exactly these sections:\n"
        "End Goal\nPartition\nInternal Question\nApplied Answer\nTool Evidence\nVerification State\nNext Step"
    )


def openai_filter_available() -> bool:
    return bool(OPENAI_ESCALATION_AVAILABLE and os.getenv("OPENAI_API_KEY", "").strip())


def extract_openai_output_text(payload: Dict[str, Any]) -> str:
    direct = str(payload.get("output_text") or "").strip()
    if direct:
        return direct
    parts: List[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict):
                text = content.get("text") or content.get("output_text")
                if text:
                    parts.append(str(text))
    return "\n".join(parts).strip()


def call_openai_filter_backup(
    *,
    prompt: str,
    project: str,
    packet: Dict[str, Any],
    evidence_blocks: List[str],
    draft_reply: str,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not (OPENAI_ESCALATION_ENABLED and api_key):
        return {"ok": False, "skipped": True, "reason": "openai_filter_disabled_or_missing_key"}

    instructions = (
        "You are an optional AEGIS comprehension filter and processing backup. "
        "Do not write the target program payload. Do not replace PicoClaw. "
        "Help the local system understand the user and critique the current loop. "
        "Return concise JSON only with keys: interpreted_goal, missing_systems_knowledge, "
        "evidence_gate, risks, next_round_prompt."
    )
    user_input = {
        "project": project,
        "user_prompt": prompt,
        "short_round_packet": packet,
        "latest_evidence": evidence_blocks[-6:],
        "draft_reply": draft_reply[-3000:],
    }
    body = json.dumps(
        {
            "model": OPENAI_ESCALATION_MODEL,
            "instructions": instructions,
            "input": json.dumps(user_input, ensure_ascii=True, indent=2),
            "max_output_tokens": 700,
        }
    ).encode("utf-8")
    request_obj = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=OPENAI_FILTER_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        text = extract_openai_output_text(payload)
        return {
            "ok": bool(text),
            "model": OPENAI_ESCALATION_MODEL,
            "response_id": payload.get("id"),
            "text": text,
        }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:900]
        return {"ok": False, "error": f"openai_http_{exc.code}", "detail": detail}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def apply_evidence_gate(reply: str, evidence_blocks: List[str], request_profile: Dict[str, Any]) -> str:
    cleaned = (reply or "").strip()
    if not request_profile.get("needs_code_execution_loop"):
        return cleaned
    evidence_text = "\n".join(evidence_blocks or [])
    has_tool_evidence = bool(evidence_text.strip())
    has_pass_evidence = bool(
        re.search(
            r"\b(returncode\s*[:=]\s*0|tests?\s+passed|passed\b|ok\s*[:=]\s*true|SNIPPET_FORGE_TESTS_PASSED)\b",
            evidence_text,
            flags=re.IGNORECASE,
        )
    )
    claims_success = bool(
        re.search(r"\b(verified|working|works|passes|passed|success|complete|done)\b", cleaned, flags=re.IGNORECASE)
    )
    if claims_success and not has_pass_evidence:
        return (
            cleaned.rstrip()
            + "\n\nEvidence Gate: I do not have passing test/tool evidence yet, so this is a proposal or next candidate, not a verified working result."
        )
    if not has_tool_evidence:
        return cleaned.rstrip() + "\n\nEvidence Gate: No tool evidence was captured for this build loop yet."
    return cleaned


def build_cloud_execution_prompt(prompt: str, project: str, request_profile: Dict[str, Any]) -> str:
    if not request_profile.get("requires_deliberate_mode"):
        return prompt

    focus_keywords = extract_focus_keywords(prompt, limit=8)
    work_style = []
    if request_profile.get("needs_research"):
        work_style.append("credible-source research")
    if request_profile.get("needs_coding"):
        work_style.append("code and tooling")
    if request_profile.get("needs_verification"):
        work_style.append("verification")
    if request_profile.get("needs_automation"):
        work_style.append("automation")

    return (
        f"Project lane: {project}\n"
        "Execution mode: deliberate multi-step\n"
        f"Focus keywords: {', '.join(focus_keywords) if focus_keywords else 'none'}\n"
        f"Work style: {', '.join(work_style) if work_style else 'direct'}\n"
        "Rules:\n"
        "- Keep the end goal explicit.\n"
        "- Break the task into phases before acting.\n"
        "- Prefer: understand -> research -> inspect -> act -> verify -> summarize.\n"
        "- Treat spelling mistakes as noise.\n"
        "- Avoid generic mainstream filler and default replies.\n"
        "- Keep explicit user directives pinned even if older context is dropped.\n"
        "- If another safe step is obvious, continue instead of stopping early.\n"
        "- If context pressure gets high, ask for one compact refresh instead of going blank.\n"
        "- Prefer extra visible progress over silence.\n\n"
        "User request:\n"
        f"{prompt}"
    )


def get_lens_context_profile() -> Dict[str, Any]:
    confidence = float(lens_memory_state.get("last_confidence") or 0.0)
    activity = str(lens_memory_state.get("last_activity") or "").strip().lower()
    summary_raw = str(lens_memory_state.get("last_summary") or "").strip()
    node_raw = str(lens_memory_state.get("active_node") or "").strip()
    summary = normalize_prompt_text(summary_raw)
    node = normalize_prompt_text(node_raw)
    debugging_code = (
        activity == "debugging"
        and any(
            token in f"{summary} {node}"
            for token in ("python", "api", "code", "file", "editor", "module", "function", "runtime bug")
        )
    )
    return {
        "confidence": confidence,
        "activity": activity,
        "summary_raw": summary_raw,
        "node_raw": node_raw,
        "inject_observer": bool(activity and summary_raw and confidence >= 0.55),
        "debugging_code": debugging_code,
        "suppress_raw_memory": bool(debugging_code and confidence >= 0.72),
    }


def summarize_distinct_labels(items: List[str], max_items: int = 3) -> str:
    labels: List[str] = []
    for item in items:
        clean = re.sub(r"\s+", " ", str(item or "")).strip()
        if not clean or clean in labels:
            continue
        labels.append(clean)
        if len(labels) >= max_items:
            break
    return ", ".join(labels)


def render_compact_search_web_result(raw_tool_result: Any = None, query: str = "", max_items: int = 5) -> str:
    metadata = getattr(raw_tool_result, "metadata", {}) or {}
    ranked_results = metadata.get("ranked_results", []) if isinstance(metadata, dict) else []
    output_text = str(getattr(raw_tool_result, "output", "") or "").strip()

    if not isinstance(ranked_results, list) or not ranked_results:
        if output_text:
            return f"[OK] {output_text}"
        query_suffix = f" for: {query}" if query else ""
        return f"[OK] Web search completed{query_suffix}."

    query_suffix = f" for: {query}" if query else ""
    lines = [f"[OK] Web search found {len(ranked_results)} ranked source lead(s){query_suffix}."]
    for index, result in enumerate(ranked_results[:max_items], start=1):
        credibility = result.get("credibility", {}) if isinstance(result, dict) else {}
        title = str(result.get("title") or result.get("url") or "Untitled result").strip()
        url = str(result.get("url") or "").strip()
        label = str(credibility.get("label") or "source").strip()
        risk = str(credibility.get("purpose_risk") or "unknown").strip()
        score = float(credibility.get("score", 0.0) or 0.0)
        corroboration = (
            "needs corroboration"
            if credibility.get("corroboration_required", True)
            else "stronger corroboration"
        )
        lines.append(
            f"{index}. [{label} score={score:.2f} risk={risk}; {corroboration}] "
            f"{title} - {url}"
        )
    remaining = len(ranked_results) - max_items
    if remaining > 0:
        lines.append(f"... plus {remaining} more ranked result(s).")
    lines.append("Internal credibility JSON was suppressed so the reply stays readable.")
    return "\n".join(lines)


def render_compact_heartbeat_result(raw_tool_result: Any = None) -> str:
    ok = bool(getattr(raw_tool_result, "ok", True))
    prefix = "[OK]" if ok else "[ERROR]"
    output_text = str(getattr(raw_tool_result, "output", "") or "").strip()
    if not output_text:
        return f"{prefix} System heartbeat completed."
    return (
        f"{prefix} {output_text}\n"
        "Internal heartbeat report JSON was suppressed so the reply stays readable."
    )


def sanitize_memory_tool_result_for_prompt(tool_call: Dict[str, Any], rendered: str, raw_tool_result: Any = None) -> str:
    tool_name = str(tool_call.get("tool", "")).strip()
    parameters = tool_call.get("parameters", {}) if isinstance(tool_call, dict) else {}

    if tool_name == "search_web":
        query = str(parameters.get("query", "")).strip()
        return render_compact_search_web_result(raw_tool_result, query=query)

    if tool_name == "run_system_heartbeat":
        return render_compact_heartbeat_result(raw_tool_result)

    if tool_name != "search_project_memory":
        return rendered

    lens_profile = get_lens_context_profile()
    if not lens_profile.get("suppress_raw_memory"):
        return rendered

    project = str(parameters.get("project", "")).strip() or "general"
    query = str(parameters.get("query", "")).strip()
    hit_count = 0
    output_text = str(getattr(raw_tool_result, "output", "") or "")
    if output_text:
        hit_count = len(re.findall(r"(?m)^\d+\.", output_text))
    count_text = f"{hit_count} hit(s)" if hit_count else "historical hits"
    query_text = f" for query '{query[:80]}'" if query else ""
    return (
        f"[OK] Project memory search found {count_text} in project '{project}'{query_text}, "
        "but raw excerpts are suppressed because live lens debugging context is high-confidence.\n"
        "Use the result only as weak corroboration for recurring files, modules, or prior attempts."
    )


def build_hybrid_context(session_id: str, project: str, prompt: str) -> str:
    blocks = []
    focus_keywords = extract_focus_keywords(prompt, limit=6)
    lens_profile = get_lens_context_profile()
    suppress_raw_memory = bool(lens_profile.get("suppress_raw_memory"))

    # [AEGIS-LENS INJECTION]
    if lens_profile.get("inject_observer"):
        lens_block = (
            "[SYSTEM OBSERVER: DEV DESKTOP CONTEXT]\n"
            f"Active Node: '{lens_memory_state['active_node']}'\n"
            f"Activity: {lens_memory_state['last_activity']}\n"
            f"Observer Confidence: {lens_profile['confidence']:.2f}\n"
            f"Screen Summary: {lens_memory_state['last_summary']}\n"
            "Use this observer context to resolve ambiguous references like 'the app', 'this', 'here', 'next step', or 'what should I do next'.\n"
        )
        if lens_memory_state.get("stuck_count", 0) > 10:
            lens_block += "WARNING: User has been stuck on this for >2 minutes.\n"
        if lens_profile.get("debugging_code"):
            lens_block += "Bias toward the next concrete local inspection, command, or file-level step before asking broad clarifying questions.\n"
            lens_block += "If the prompt is underspecified, assume the user is referring to the currently observed code or runtime issue unless they explicitly switch topics.\n"
        if suppress_raw_memory:
            lens_block += "Prefer the live observer context over historical retrieval. Do not surface raw memory excerpts, stale stack traces, or old error fragments unless the user explicitly asks for history.\n"
        lens_block += "==============================\n"
        blocks.append(lens_block)

    try:
        twin_context = personal_system_twin.build_prompt_context(
            project=project,
            activity=lens_profile.get("activity", ""),
            max_hints=3,
        )
        if twin_context:
            blocks.append(twin_context)
    except Exception as exc:
        print(f"[ERROR] Personal system twin context error: {exc}")

    try:
        fabris_hints = build_fabris_context_hints(project=project, prompt=prompt, limit=3)
        if fabris_hints:
            blocks.append(fabris_hints)
    except Exception as exc:
        print(f"[ERROR] FABRIS context hint error: {exc}")

    try:
        signature_hits = context_distiller.search_signatures(prompt, project=project, limit=2)
        if signature_hits:
            if suppress_raw_memory:
                subject_labels = summarize_distinct_labels([str(hit.get("subject", "project")) for hit in signature_hits], max_items=3)
                blocks.append(
                    "DIRECTORY SIGNATURE HINTS:\n"
                    f"- Historical signatures exist ({len(signature_hits)} hit(s){': ' + subject_labels if subject_labels else ''}).\n"
                    "- Use them only to confirm recurring files or modules; do not surface raw historical snippets."
                )
            else:
                summaries = []
                for hit in signature_hits:
                    content = compress_signal_text((hit.get("content") or ""), focus_keywords=focus_keywords, max_sentences=2, max_chars=180)
                    summaries.append(
                        f"- [{hit.get('subject', 'project')}] score={hit.get('score', 0):.3f}: {content}"
                    )
                blocks.append("DIRECTORY SIGNATURES:\n" + "\n".join(summaries))
    except Exception as exc:
        print(f"[ERROR] Directory signature retrieval error: {exc}")

    try:
        timescale_context = timescale_memory.get_context(session_id, "chat", max_files=5, project=project)
        if timescale_context:
            if suppress_raw_memory:
                blocks.append(
                    f"PROJECT MEMORY HINTS ({project}):\n"
                    "- Historical project memory exists, but raw excerpts are suppressed because the live observer context is higher confidence.\n"
                    "- Use memory only to confirm recurring files, modules, or prior attempts; do not quote stale error text."
                )
            else:
                reduced_timescale = reduce_context_sections(timescale_context, prompt, max_sections=2, max_section_chars=320, max_total_chars=700)
                blocks.append(f"PROJECT TIMESCALE CONTEXT ({project}):\n{reduced_timescale[:700]}")
    except Exception as exc:
        print(f"[ERROR] Timescale context retrieval error: {exc}")

    include_reasoning_notes = os.getenv("AEGIS_INCLUDE_REASONING_NOTES", "0").strip().lower() in {"1", "true", "yes", "on"}
    if include_reasoning_notes:
        try:
            reasoning_notes = timescale_memory.recent_reasoning_notes(project, limit=2)
            if reasoning_notes:
                if suppress_raw_memory:
                    blocks.append(
                        "REASONING NOTE HINTS:\n"
                        f"- {len(reasoning_notes)} recent reasoning note(s) exist for this project.\n"
                        "- Use them only to recover prior plan direction, not to surface stale snippets or old error context."
                    )
                else:
                    summaries = []
                    for note in reasoning_notes:
                        content = (note.get("content") or "").replace("\r", " ")
                        content = re.sub(r"\s+", " ", content).strip()
                        content = compress_signal_text(content, focus_keywords=focus_keywords, max_sentences=2, max_chars=180) or content[:180]
                        summaries.append(f"- {content[:220]}")
                    blocks.append("RECENT REASONING NOTES:\n" + "\n".join(summaries))
        except Exception as exc:
            print(f"[ERROR] Reasoning note retrieval error: {exc}")

    try:
        vector_hits = vector_memory.search(
            prompt,
            project=project,
            limit=4,
        )
        if vector_hits:
            if suppress_raw_memory:
                kind_labels = summarize_distinct_labels(
                    [
                        f"{hit.get('kind', 'memory')}/{hit.get('role', 'unknown')}"
                        for hit in vector_hits
                    ],
                    max_items=3,
                )
                blocks.append(
                    "VECTOR MEMORY HINTS:\n"
                    f"- {len(vector_hits)} historical match(es) exist{f' ({kind_labels})' if kind_labels else ''}.\n"
                    "- Use them only as weak corroboration for recurring files or issues; do not quote raw memory text or old errors."
                )
            else:
                summaries = []
                for hit in vector_hits:
                    content = compress_signal_text((hit.get("content") or ""), focus_keywords=focus_keywords, max_sentences=2, max_chars=180)
                    summaries.append(
                        f"- [{hit.get('kind', 'memory')}/{hit.get('role', 'unknown')}] score={hit.get('score', 0):.3f}: {content}"
                    )
                blocks.append("VECTOR MATCHES:\n" + "\n".join(summaries))
    except Exception as exc:
        print(f"[ERROR] Vector retrieval error: {exc}")

    try:
        knowledge_hits = search_knowledge_library(prompt, project=project, limit=3)
        if knowledge_hits:
            summaries = []
            for hit in knowledge_hits:
                metadata = hit.get("metadata") or {}
                title = str(metadata.get("title") or hit.get("kind") or "knowledge")
                url = str(metadata.get("url") or "")
                domain_label = str(metadata.get("source_domain") or "")
                summaries.append(
                    f"- [{title}] score={hit.get('score', 0):.3f}"
                    + (f" ({domain_label})" if domain_label else "")
                    + (f" {url}" if url else "")
                )
            blocks.append("KNOWLEDGE LIBRARY MATCHES:\n" + "\n".join(summaries))
    except Exception as exc:
        print(f"[ERROR] Knowledge library retrieval error: {exc}")

    return "\n\n".join(dedupe_text_items(blocks, max_items=4, max_chars=1800))


def trim_context_text(context_text: str, max_chars: int = 2200) -> str:
    cleaned = (context_text or "").strip()
    if cleaned:
        sections = [section.strip() for section in cleaned.split("\n\n") if section.strip()]
        cleaned = "\n\n".join(dedupe_text_items(sections, max_items=5, max_chars=max_chars))
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "\n...[context trimmed]"


def trim_chat_history(messages: List[Dict], max_messages: int = 6, max_chars: int = 1800) -> List[Dict]:
    recent_window = (messages or [])[-10:]
    focus_keywords = extract_focus_keywords(" ".join((item.get("content") or "") for item in recent_window), limit=8)
    scored_messages: List[tuple[float, int, Dict[str, str]]] = []
    for index, message in enumerate(messages or []):
        content = (message.get("content") or "").strip()
        role = message.get("role") or "user"
        if not content:
            continue
        compressed = compress_signal_text(content, focus_keywords=focus_keywords, max_sentences=4, max_chars=420) or content[:420]
        score = float(index) / max(len(messages or []), 1)
        if role == "user":
            score += 2.5
        if has_directive_signal(content):
            score += 4.0
        if role == "assistant" and re.search(r"\b(updated|created|verified|found|changed|patched|tested|running|will)\b", normalize_prompt_text(content)):
            score += 1.5
        scored_messages.append((score, index, {"role": role, "content": compressed[:420]}))

    scored_messages.sort(key=lambda item: -item[0])
    selected: List[tuple[int, Dict[str, str]]] = []
    consumed = 0
    seen = set()
    for _score, index, message in scored_messages:
        signature = text_signature(message.get("content", ""))
        if not signature or signature in seen:
            continue
        next_cost = len(message.get("content", ""))
        if len(selected) >= max_messages or consumed + next_cost > max_chars:
            continue
        seen.add(signature)
        selected.append((index, message))
        consumed += next_cost

    chronological = [message for _index, message in sorted(selected, key=lambda item: item[0])]
    return chronological[:max_messages]


def strip_ansi_text(text: str) -> str:
    cleaned = text or ""
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", cleaned)
    cleaned = re.sub(r"\x1b[@-_]", "", cleaned)
    return cleaned


def strip_model_reasoning(text: str) -> str:
    cleaned = text or ""
    cleaned = re.sub(r"<think>[\s\S]*?</think>\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*thinking\.\.\..*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def normalize_model_reply(text: str) -> str:
    cleaned = strip_ansi_text(text or "")
    cleaned = strip_model_reasoning(cleaned)
    cleaned = cleaned.replace("\r", "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_direct_reply_text(reply: str, *, project: str) -> str:
    cleaned = normalize_model_reply(reply or "")
    if not cleaned:
        return ""

    parsed = parse_tool_call(cleaned)
    if not isinstance(parsed, dict):
        return cleaned

    for key in ("reply", "message", "answer", "summary", "result", "content", "text"):
        value = parsed.get(key)
        if not isinstance(value, str):
            continue
        candidate = normalize_model_reply(value)
        if candidate and not parse_tool_calls(candidate):
            return candidate

    if not parse_tool_calls(cleaned):
        return cleaned

    return f"Project lane: {project}.\nNo direct prose reply was produced."


def finalize_reply_text(reply: str, *, prompt: str, project: str, source: str) -> str:
    cleaned = normalize_model_reply(reply or "")
    if cleaned and cleaned != "...":
        return apply_code_intent_italics(cleaned, prompt)

    return (
        f"Project lane: {project}.\n"
        f"No usable reply was produced by {source}."
    )


def sanitize_direct_tool_path(candidate: str) -> Optional[str]:
    path = (candidate or "").strip().strip("\"'")
    if not path:
        return None

    path = re.sub(
        r'\s+(?:with\s+content|with\s+contents|with\s+text|containing|that\s+says)\b.*$',
        '',
        path,
        flags=re.IGNORECASE,
    )
    path = re.sub(
        r'\s+(?:and then|and|then)\s+(?:tell|show|list|open|verify|confirm|report|give|return)\b.*$',
        '',
        path,
        flags=re.IGNORECASE,
    )
    path = re.sub(r'\s+please\b.*$', '', path, flags=re.IGNORECASE)
    path = path.rstrip(" .")

    if len(path) > 320:
        return None
    if any(marker in path.lower() for marker in ("runtime error", "request failed", "shield down", "like dislike retry")):
        return None
    if '"' in path or "\n" in path or "\r" in path:
        return None
    if not re.match(r'^[A-Za-z]:\\', path):
        return None

    try:
        windows_path = PureWindowsPath(path)
    except Exception:
        return None

    if len(windows_path.parts) < 2:
        return None
    if windows_path.name in {"", ".", ".."}:
        return None

    return str(windows_path)


def extract_direct_file_content(prompt: str) -> str:
    content_patterns = [
        r'\bwith\s+content\s*:\s*(.+)$',
        r'\bwith\s+contents\s*:\s*(.+)$',
        r'\bcontaining\s+(.+)$',
        r'\bthat\s+says\s+(.+)$',
        r'\bwith\s+text\s*:\s*(.+)$',
    ]

    for pattern in content_patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        content = (match.group(1) or "").strip()
        content = re.sub(r'\s+please\b.*$', '', content, flags=re.IGNORECASE)
        content = content.strip().strip('"').strip("'")
        return content

    return ""


def program_start_is_confirmed(message: str) -> bool:
    prompt = (message or "").strip()
    lowered = normalize_prompt_text(prompt)
    if prompt.lower().startswith("/program confirm "):
        return True
    confirmation_patterns = (
        r"\b(?:ok|okay|yes|confirm|confirmed|approve|approved)\b.*\b(?:start|run|execute|launch)\b.*\b(?:program|builder|build|picoclaw|pico|code)\b",
        r"\b(?:start|run|execute|launch)\b.*\b(?:approved|confirmed|okayed)\b.*\b(?:program|builder|build|picoclaw|pico|code)\b",
        r"\bexecute approved logic grid\b",
        r"\bstart approved program\b",
    )
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in confirmation_patterns)


def program_prompt_needs_conversation_first(message: str) -> bool:
    lowered = normalize_prompt_text(message or "")
    if program_start_is_confirmed(message):
        return False
    conversational_signals = (
        "how are you",
        "ready to make",
        "ready to build",
        "can we make",
        "lets make",
        "let us make",
        "want to make",
        "what should we build",
        "talk about",
        "brainstorm",
    )
    return any(signal in lowered for signal in conversational_signals)


def strip_program_confirmation_prefix(objective: str) -> str:
    cleaned = (objective or "").strip()
    cleaned = re.sub(
        r'^\s*(?:ok|okay|yes|confirm|confirmed|approve|approved)\s+'
        r'(?:please\s+)?(?:start|run|execute|launch)\s+'
        r'(?:the\s+)?(?:program\s+loop|program|builder|build|code)\s*:?\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r'^\s*(?:execute\s+approved\s+logic\s+grid|start\s+approved\s+program)\s*:?\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or objective


def clean_program_objective(objective: str) -> str:
    original = (objective or "").strip()
    cleaned = strip_program_confirmation_prefix(original)
    cleaned = re.sub(
        r'^\s*(?:ok|okay|yes|yeah|yep|sure|please)\s*,?\s+',
        '',
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r'^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?'
        r'(?:make|build|create|write|code|develop)\s+(?:me\s+)?'
        r'(?:(?:a|an|the)\s+)?(?:small\s+|tiny\s+|simple\s+)?'
        r'(?:program|app|application|script|tool|utility)\s*'
        r'(?:that|which|to)?\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r'^\s*(?:(?:a|an|the)\s+)?(?:program|app|application|script|tool|utility)\s*'
        r'(?:that|which|to)?\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or original or "the proposed program"


def infer_program_preflight(objective: str) -> Dict[str, Any]:
    lowered = normalize_prompt_text(objective)
    notes: List[str] = []
    tests: List[str] = []
    questions: List[str] = []

    if any(token in lowered for token in ("pop3", "email", "mailbox", "inbox")):
        notes.extend([
            "Use Python with POP3 over SSL first, unless you tell me otherwise.",
            "Keep credentials out of code; use environment variables or an ignored local config file.",
            "Make the first pass read-only: count/list messages and preview safe headers, no deletes or sends.",
        ])
        tests.extend([
            "Mock the POP3 client so tests run without touching your real email account.",
            "Verify login settings, message listing, and header parsing separately.",
        ])
        questions.append("Should it only count mail, or also show sender/subject/date previews?")
    elif any(token in lowered for token in ("apk", "android", "d8", "termux")):
        notes.extend([
            "Use flattened, compiler-friendly code so D8/Termux has less hidden structure to fight.",
            "Keep the first version small enough to compile and install before adding features.",
        ])
        tests.extend([
            "Compile the minimal package first, then add one feature at a time.",
            "Record the exact D8 command and output as evidence.",
        ])
        questions.append("Should PicoClaw target Termux/D8 directly or generate a desktop-side Android project?")
    elif any(token in lowered for token in ("gui", "web interface", "web ui", "dashboard")):
        notes.extend([
            "Build the smallest local web UI first, then wire features behind tested endpoints.",
            "Keep generated files in a dedicated dev workspace so the main system is not mutated accidentally.",
        ])
        tests.extend([
            "Smoke-test the backend route and save one sample UI response.",
            "Keep a run log with response time and pass/fail evidence.",
        ])
        questions.append("Should the first UI be plain local HTML or a Python web framework?")
    else:
        notes.extend([
            "Start with a minimal working version before expanding the feature set.",
            "Keep the code in a dedicated workspace and make PicoClaw return test evidence after each block.",
        ])
        tests.extend([
            "Run syntax checks first, then focused unit or smoke tests.",
            "Keep stdout/stderr and the final artifact path in the job report.",
        ])
        questions.append("Do you want the first pass as a CLI tool, GUI, web UI, or library?")

    return {"notes": notes, "tests": tests, "questions": questions}


def build_program_confirmation_reply(
    objective: str,
    *,
    project: str = "general",
    hours: int = 24,
    cpu_target: int = 30,
) -> str:
    objective = clean_program_objective(objective)
    preflight = infer_program_preflight(objective)
    note_lines = [f"- {line}" for line in preflight["notes"][:4]]
    test_lines = [f"- {line}" for line in preflight["tests"][:3]]
    question_lines = [f"- {line}" for line in preflight["questions"][:2]]
    return "\n".join([
        "I can build that. I am not starting PicoClaw, writing files, or launching a background loop until you approve it.",
        "",
        f"My read of the build target: {objective}",
        f"Project lane: {project}. Default run after approval: up to {hours} hour(s), aiming around {cpu_target}% CPU.",
        "",
        "First safe shape:",
        *note_lines,
        "",
        "Verification before keeping it:",
        *test_lines,
        "",
        "Before I hand this to PicoClaw:",
        *question_lines,
        "",
        f"If that matches what you want, reply: `OK start program loop: {objective}`",
    ])


def detect_direct_tool_request(message: str, project: str = "general") -> Optional[Dict[str, Any]]:
    prompt = (message or "").strip()
    if not prompt:
        return None

    if len(prompt) > 500 and re.search(
        r'\b(?:runtime error|request failed|shield down|like|dislike|retry|step \d|highlighter|garbage disposal)\b',
        prompt,
        flags=re.IGNORECASE,
    ):
        return None

    lowered = normalize_prompt_text(prompt)
    list_directory_signals = (
        "list directory",
        "list folder",
        "show directory",
        "show folder",
        "open directory",
        "open folder",
    )
    if any(prompt_matches_signal(lowered, signal) for signal in list_directory_signals):
        quoted_match = re.search(r'["\']([A-Za-z]:\\[^"\']+)["\']', prompt)
        if quoted_match:
            path = sanitize_direct_tool_path(quoted_match.group(1))
            if path:
                return {"tool": "list_directory", "parameters": {"path": path}}
        absolute_match = re.search(r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+)', prompt)
        if absolute_match:
            path = sanitize_direct_tool_path(absolute_match.group(1))
            if path:
                return {"tool": "list_directory", "parameters": {"path": path}}

    folder_signals = (
        "create folder",
        "create a folder",
        "create directory",
        "create a directory",
        "make folder",
        "make a folder",
        "make directory",
        "make a directory",
        "new folder",
        "new directory",
    )
    direct_request_pattern = re.compile(
        r'^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+|i want you to\s+|help me\s+)?'
        r'(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\b',
        flags=re.IGNORECASE,
    )

    folder_intent = any(prompt_matches_signal(lowered, signal) for signal in folder_signals)
    if folder_intent and (direct_request_pattern.search(prompt) or re.search(r'[A-Za-z]:\\', prompt)):
        quoted_match = re.search(r'["\']([A-Za-z]:\\[^"\']+)["\']', prompt)
        if quoted_match:
            path = sanitize_direct_tool_path(quoted_match.group(1))
            if path:
                return {"tool": "create_directory", "parameters": {"path": path}}

        absolute_match = re.search(r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+)', prompt)
        if absolute_match:
            path = sanitize_direct_tool_path(absolute_match.group(1))
            if path:
                return {"tool": "create_directory", "parameters": {"path": path}}

    file_signals = (
        "create file",
        "create a file",
        "write file",
        "write a file",
        "save file",
        "save a file",
        "make file",
        "make a file",
    )
    direct_file_request_pattern = re.compile(
        r'^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+|i want you to\s+|help me\s+)?'
        r'(?:create|write|save|make)\s+(?:a\s+)?(?:new\s+)?file\b',
        flags=re.IGNORECASE,
    )

    file_intent = any(prompt_matches_signal(lowered, signal) for signal in file_signals)
    if file_intent and (direct_file_request_pattern.search(prompt) or re.search(r'[A-Za-z]:\\', prompt)):
        quoted_match = re.search(r'["\']([A-Za-z]:\\[^"\']+)["\']', prompt)
        if quoted_match:
            path = sanitize_direct_tool_path(quoted_match.group(1))
            if path:
                return {
                    "tool": "create_file",
                    "parameters": {
                        "path": path,
                        "content": extract_direct_file_content(prompt),
                    },
                }

        absolute_match = re.search(r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+)', prompt)
        if absolute_match:
            path = sanitize_direct_tool_path(absolute_match.group(1))
            if path:
                return {
                    "tool": "create_file",
                    "parameters": {
                        "path": path,
                        "content": extract_direct_file_content(prompt),
                    },
                }

    research_signals = (
        "research loop",
        "agentic research",
        "deep research",
        "research all night",
        "keep researching",
        "crawl and research",
    )
    research_activation_signals = (
        "start",
        "run",
        "do",
        "keep",
        "loop",
        "all night",
        "crawl",
        "research",
    )
    if any(signal in lowered for signal in research_signals) and any(
        signal in lowered for signal in research_activation_signals
    ):
        objective = re.sub(
            r'^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:start|run|do|keep)\s+',
            '',
            prompt,
            flags=re.IGNORECASE,
        ).strip()
        return {
            "performative": "research_job",
            "objective": objective or prompt,
            "max_results": 6,
            "max_pages": 6,
            "ttl_hours": 24 * 14,
        }

    program_loop_signals = (
        "create program loop",
        "program loop",
        "iterate until it works",
        "until it works",
        "build test fix",
        "test fix redo",
        "fix redo cycle",
    )
    program_activation_signals = (
        "start",
        "run",
        "launch",
        "create",
        "make",
        "loop",
        "iterate",
        "keep",
    )
    program_loop_hit = any(signal in lowered for signal in program_loop_signals)
    if program_loop_hit and any(
        prompt_matches_signal(lowered, signal) for signal in program_activation_signals
    ):
        objective = re.sub(
            r'^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:start|run|launch|create|make|keep)\s+',
            '',
            prompt,
            flags=re.IGNORECASE,
        ).strip()
        objective = re.sub(r'^(?:a\s+)?program\s+loop(?:\s+and)?\s*', '', objective, flags=re.IGNORECASE).strip()
        objective = re.sub(r'^(?:iterate|loop)\s+until\s+it\s+(?:works|runs)\s+(?:for\s+)?', '', objective, flags=re.IGNORECASE).strip()
        objective = re.sub(r'^until\s+it\s+(?:works|runs)\s+(?:for\s+)?', '', objective, flags=re.IGNORECASE).strip()
        objective = clean_program_objective(objective)
        hours_match = re.search(r'(\d+)\s*hours?', prompt, flags=re.IGNORECASE)
        cpu_match = re.search(r'(\d+)\s*%\s*cpu|\bcpu\s*(?:target|limit)?\s*(\d+)', prompt, flags=re.IGNORECASE)
        hours = int(hours_match.group(1)) if hours_match else 24
        cpu_target = 30
        if cpu_match:
            cpu_target = int(cpu_match.group(1) or cpu_match.group(2) or 30)
        if not program_start_is_confirmed(prompt):
            return {
                "performative": "program_confirmation_request",
                "objective": objective or prompt,
                "hours": max(1, min(hours, 24 * 7)),
                "cpu_target": max(15, min(cpu_target, 60)),
            }
        return {
            "performative": "create_program_job",
            "objective": objective or prompt,
            "hours": max(1, min(hours, 24 * 7)),
            "cpu_target": max(15, min(cpu_target, 60)),
        }

    lens_profile = get_lens_context_profile()
    lens_debugging_code = bool(lens_profile.get("debugging_code"))

    maintenance_signals = (
        "sluggish",
        "unsluggish",
        "extra instances",
        "operating environment",
        "system health",
        "machine health",
        "heartbeat",
        "temp cleanup",
        "temp files",
        "machine feels",
    )
    maintenance_activation_signals = (
        "check",
        "inspect",
        "diagnose",
        "fix",
        "cleanup",
        "clean up",
        "optimize",
        "speed up",
        "repair",
        "monitor",
        "heartbeat",
        "audit",
    )
    maintenance_hit = any(prompt_matches_signal(lowered, signal) for signal in maintenance_signals)
    maintenance_action = any(prompt_matches_signal(lowered, signal) for signal in maintenance_activation_signals)
    explicit_system_focus = any(
        prompt_matches_signal(lowered, signal)
        for signal in (
            "cpu",
            "ram",
            "memory",
            "temp",
            "background processes",
            "startup",
            "sluggish",
            "slow pc",
            "system health",
            "machine health",
            "heartbeat",
        )
    )
    if lens_debugging_code and not explicit_system_focus:
        maintenance_hit = False
    if maintenance_hit and maintenance_action:
        search_query = (
            "Windows PC sluggish performance optimization official docs whitepaper research "
            "background processes memory startup temp cleanup"
        )
        tool_calls: List[Dict[str, Any]] = [
            {
                "tool": "run_system_heartbeat",
                "parameters": {
                    "cleanup_temp": bool(
                        "temp" in lowered and any(token in lowered for token in ("clean", "cleanup", "garbage"))
                    ),
                    "kill_extra_gemini_cli": bool("extra instances" in lowered or "gemini cli" in lowered),
                    "temp_days": 2,
                },
            },
            {
                "tool": "search_web",
                "parameters": {"query": search_query},
            },
        ]
        if project and project != "general":
            tool_calls.insert(
                1,
                {
                    "tool": "search_project_memory",
                    "parameters": {
                        "query": "machine sluggish performance cleanup heartbeat prior fixes",
                        "project": project,
                    },
                },
            )
        return {"performative": "diagnose", "tool_calls": tool_calls}

    return None

def sync_state(key, value):
    """Persists global state to consistency.db"""
    try:
        conn = sqlite3.connect(CONSISTENCY_DB)
        conn.execute("INSERT OR REPLACE INTO global_state (key, value, last_updated) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, str(value)))
        conn.commit()
        conn.close()
    except: pass

# ===== Models =====
class ChatMessage(BaseModel):
    message: str
    mode: Optional[str] = "auto"
    retry: Optional[bool] = False
    project: Optional[str] = "general"
    dry_run: Optional[bool] = False
    replay_id: Optional[str] = None

class SignalData(BaseModel):
    signal: str
    x: Optional[int] = 0
    y: Optional[int] = 0

class FeedbackData(BaseModel):
    message_id: int
    score: int
    run_id: Optional[str] = None
    project: Optional[str] = "general"
    prompt: Optional[str] = None
    response: Optional[str] = None
    route: Optional[str] = None
    response_ms: Optional[int] = None
    logic_points: Optional[List[str]] = None

class AgenticResearchRequest(BaseModel):
    task: str
    max_results: Optional[int] = 5
    max_pages: Optional[int] = 5
    ttl_hours: Optional[int] = 24 * 7
    project: Optional[str] = "general"


class CreateProgramRequest(BaseModel):
    task: str
    hours: Optional[int] = 24
    cpu_target: Optional[int] = 30
    target_dir: Optional[str] = None
    model: Optional[str] = None
    project: Optional[str] = "general"



class LongResearchRequest(BaseModel):
    task: str
    hours: Optional[int] = 8
    cycles: Optional[int] = None
    max_results: Optional[int] = 10
    max_pages: Optional[int] = 20
    project: Optional[str] = "general"


class ExecutionLikelihoodRequest(BaseModel):
    prompt: str = ""
    objective: Optional[str] = ""
    code: Optional[str] = ""
    reply: Optional[str] = ""
    language: Optional[str] = ""
    code_lines: Optional[int] = 0
    research_hits: Optional[int] = 0
    prior_pass_rate: Optional[float] = None


class ScriptRegistryIngestRequest(BaseModel):
    roots: Optional[List[str]] = None


class KnowledgeLibraryIngestRequest(BaseModel):
    project: Optional[str] = "general"
    max_sources: Optional[int] = None
    max_chunks_per_source: Optional[int] = 80
    timeout_seconds: Optional[int] = 35


class KnowledgeLibraryReindexRequest(BaseModel):
    project: Optional[str] = "general"
    force: Optional[bool] = False
    domain: Optional[str] = None
    limit: Optional[int] = None


class PicoClawOneStepWriteRequest(BaseModel):
    objective: str
    relative_path: Optional[str] = "index.html"
    project: Optional[str] = "general"
    timeout_seconds: Optional[int] = 45


class AiderRunRequest(BaseModel):
    prompt: str
    project: Optional[str] = "general"
    cwd: Optional[str] = None
    model: Optional[str] = None
    dry_run: Optional[bool] = True
    read_only: Optional[bool] = True


class GeneticCoderRequest(BaseModel):
    objective: str
    project: Optional[str] = "general"
    language: Optional[str] = "python"
    outline: Optional[str] = ""
    snippets: Optional[List[Dict[str, Any]]] = None
    max_generations: Optional[int] = 8
    population: Optional[int] = 4
    timebox_minutes: Optional[int] = 20
    workspace: Optional[str] = None


class LavaEventRequest(BaseModel):
    project: Optional[str] = "general"
    event_type: str
    source: Optional[str] = "aegis-ui"
    target: Optional[str] = "aegis-lava-event-plane"
    content: Optional[Dict[str, Any]] = None
    performative: Optional[str] = "tell"
    status: Optional[str] = "observed"
    score: Optional[float] = 0.0
    reinforce_fabric: Optional[bool] = False
    fabric_domain: Optional[str] = None


class SourceTraceRequest(BaseModel):
    input_text: str
    project: Optional[str] = "general"
    limit: Optional[int] = 6


class Phase1CompileRequest(BaseModel):
    input_text: str
    project: Optional[str] = "general"
    mode: Optional[str] = "deterministic"
    persist: Optional[bool] = True


class Phase1EmergencyStopRequest(BaseModel):
    project: Optional[str] = "general"
    active: Optional[bool] = True
    reason: Optional[str] = ""


class Phase1ObjectiveValidationRequest(BaseModel):
    project: Optional[str] = "general"
    objective: str
    evidence: Dict[str, Any]



class DryRunBackgroundTasks(BackgroundTasks):
    """BackgroundTasks-compatible recorder that never executes side effects."""

    def __init__(self, action_log: Optional[List[Dict[str, Any]]] = None):
        super().__init__()
        self.action_log = action_log if action_log is not None else []

    def add_task(self, func, *args, **kwargs):  # type: ignore[override]
        self.action_log.append({
            "kind": "background_task",
            "function": getattr(func, "__name__", str(func)),
            "args": [_dry_summarize_arg(arg) for arg in args],
            "kwargs": {str(key): _dry_summarize_arg(value) for key, value in kwargs.items()},
        })


def _dry_summarize_arg(value: Any, limit: int = 500) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return {str(k): _dry_summarize_arg(v, limit=limit) for k, v in list(value.items())[:12]}
    if isinstance(value, (list, tuple)):
        return [_dry_summarize_arg(item, limit=limit) for item in list(value)[:12]]
    return getattr(value, "__name__", value.__class__.__name__)


def _dry_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, default=str)


def _render_dry_run_direct_reply(direct_tool_call: Dict[str, Any], *, project: str, message: str) -> Dict[str, Any]:
    performative = str(direct_tool_call.get("performative") or direct_tool_call.get("tool") or "tool_call")
    proposed_tool_calls: List[Dict[str, Any]] = []
    proposed_changes: List[Dict[str, Any]] = []

    if isinstance(direct_tool_call.get("tool_calls"), list):
        proposed_tool_calls = list(direct_tool_call.get("tool_calls") or [])
    elif direct_tool_call.get("tool"):
        proposed_tool_calls = [direct_tool_call]

    if performative == "research_job":
        proposed_changes.append({
            "type": "agentic_job",
            "action": "would_start_research_job",
            "objective": direct_tool_call.get("objective", message),
            "project": project,
        })
    elif performative == "program_confirmation_request":
        objective = clean_program_objective(str(direct_tool_call.get("objective", message)).strip() or message)
        reply = build_program_confirmation_reply(
            objective,
            project=project,
            hours=int(direct_tool_call.get("hours", 24)),
            cpu_target=int(direct_tool_call.get("cpu_target", 30)),
        )
        return {
            "reply": reply,
            "thoughts": "",
            "project": project,
            "dry_run": True,
            "proposed_tool_calls": [],
            "proposed_changes": [{
                "type": "confirmation_gate",
                "action": "await_user_approval_before_program_loop",
                "objective": objective,
                "project": project,
            }],
        }
    elif performative == "create_program_job":
        proposed_changes.append({
            "type": "agentic_job",
            "action": "would_start_program_loop",
            "objective": direct_tool_call.get("objective", message),
            "project": project,
        })
    elif proposed_tool_calls:
        proposed_changes.append({
            "type": "tool_batch",
            "action": "would_execute_tool_calls",
            "count": len(proposed_tool_calls),
            "project": project,
        })

    reply = "\n".join([
        "[DRY RUN] No tools, jobs, files, memory writes, or system mutations were executed.",
        "",
        "## Proposed Tool Calls",
        _dry_json(proposed_tool_calls or direct_tool_call),
        "",
        "## Proposed Changes",
        _dry_json(proposed_changes or [{"type": "none_detected", "action": "no_mutation"}]),
    ]).strip()
    return {
        "reply": reply,
        "thoughts": f"Dry-run intercepted direct route: {performative}. Proposed actions were recorded only.",
        "project": project,
        "dry_run": True,
        "proposed_tool_calls": proposed_tool_calls,
        "proposed_changes": proposed_changes,
    }


def _append_dry_run_section(reply: str, proposed_tool_calls: List[Dict[str, Any]]) -> str:
    if not proposed_tool_calls:
        return reply
    section = "\n\n".join([
        "## Dry-Run Proposed Tool Calls",
        "The following tool calls were proposed by the normal route and were not executed:",
        "```json",
        _dry_json(proposed_tool_calls),
        "```",
    ])
    return (reply or "").rstrip() + "\n\n" + section

class SecretsData(BaseModel):
    secrets: Dict[str, str]
    project: Optional[str] = "general"

import ollama

# --- Background Task Logic ---
def decompose_research_task(objective: str) -> List[str]:
    clean_objective = re.sub(r"^\[[^\]]+\]\s*", "", objective).strip()
    return [
        f"[SEARCH] Find web sources for {clean_objective}",
        f"[CRAWL] Crawl sources for {clean_objective}",
        f"[INDEX] Apply boolean filtering for {clean_objective}",
        f"[MEMORY] Merge recent memory for {clean_objective}",
        f"[REPORT] Write research report for {clean_objective}",
    ]

def _flatten_crawled_matches(crawl_payload: Dict) -> List[Dict]:
    matches = []
    for crawl in crawl_payload.get("crawls", []):
        for item in crawl.get("stored_chunks", []):
            matches.append(item)
    return matches

def build_research_executor(
    job_id: str,
    objective: str,
    project: str,
    max_results: int,
    max_pages: int,
    ttl_hours: int,
):
    state: Dict[str, object] = {
        "search_results": [],
        "crawl_payload": {},
        "filtered_chunks": [],
        "memory_results": [],
        "vector_results": [],
        "report_path": None,
        "warnings": [],
    }

    def executor(subtask: SubTask) -> str:
        if subtask.description.startswith("[SEARCH]"):
            state["search_results"] = crawler_db.search_web(objective, max_results=max_results)
            search_results = state["search_results"]
            if not search_results:
                raise RuntimeError(f"No web sources found for research objective: {objective}")
            if search_results[0].get("title") == "search_error":
                raise RuntimeError(f"Search error: {search_results[0].get('snippet', 'unknown error')}")
            ranked_results = []
            for result in search_results:
                ranked_results.append(
                    {
                        **result,
                        "credibility": score_source_credibility(
                            result.get("url", ""),
                            title=result.get("title", ""),
                        ),
                    }
                )
            ranked_results.sort(
                key=lambda item: item.get("credibility", {}).get("score", 0.0),
                reverse=True,
            )
            state["search_results"] = ranked_results
            return f"Found {len(search_results)} seed source(s)"

        if subtask.description.startswith("[CRAWL]"):
            state["crawl_payload"] = crawler_db.research_query(
                objective,
                max_results=max_results,
                max_pages=max_pages,
                same_domain_only=False,
                ttl_hours=ttl_hours,
                seed_results=state["search_results"],
                project=project,
                interaction_id=job_id,
            )
            crawl_matches = _flatten_crawled_matches(state["crawl_payload"])
            total_chunks = sum(len(item.get("chunk_ids", [])) for item in crawl_matches)
            errors = state["crawl_payload"].get("errors", [])
            if errors:
                state["warnings"].extend(errors[:10])
            if not crawl_matches:
                raise RuntimeError(f"Crawl produced no stored pages for: {objective}")
            return f"Crawled {len(crawl_matches)} page(s) and stored {total_chunks} chunk(s)"

        if subtask.description.startswith("[INDEX]"):
            state["filtered_chunks"] = crawler_db.search_chunks(
                objective,
                time_range="last_week",
                limit=max_pages * 6,
                interaction_id=job_id,
                persist_not_table=True,
                project=project,
            )
            if not state["filtered_chunks"]:
                raise RuntimeError(f"No relevant chunks survived indexing for: {objective}")
            for chunk in state["filtered_chunks"]:
                vector_memory.store(
                    chunk.get("excerpt", ""),
                    project=project,
                    session_id=job_id,
                    subject="research",
                    kind="research",
                    role="system",
                    metadata={
                        "url": chunk.get("url"),
                        "domain": chunk.get("domain"),
                        "timestamp": chunk.get("timestamp"),
                        "chunk_id": chunk.get("chunk_id"),
                        "score": chunk.get("score"),
                    },
                )
            not_table_path = crawler_db.not_tables_dir / f"not_table_{job_id}.json"
            return f"Indexed {len(state['filtered_chunks'])} relevant chunk(s); NOT table: {not_table_path}"

        if subtask.description.startswith("[MEMORY]"):
            state["memory_results"] = timescale_memory.search(objective, time_range="last_week", project=project)
            state["vector_results"] = vector_memory.search(objective, project=project, limit=5)
            return (
                f"Merged {len(state['memory_results'])} timescale match(es) and "
                f"{len(state['vector_results'])} vector match(es)"
            )

        if subtask.description.startswith("[REPORT]"):
            report_path = crawler_db.write_research_report(
                query=objective,
                search_results=state["search_results"],
                crawled_matches=state["filtered_chunks"],
                memory_results=state["memory_results"],
                vector_results=state["vector_results"],
                notes=[
                    f"Project: {project}",
                    f"NOT table: {crawler_db.not_tables_dir / f'not_table_{job_id}.json'}",
                    f"Vector matches: {len(state['vector_results'])}",
                    f"TTL hours: {ttl_hours}",
                ] + [f"Warning: {warning}" for warning in state["warnings"]],
                job_id=job_id,
            )
            state["report_path"] = report_path
            report_text = Path(report_path).read_text(encoding="utf-8")
            timescale_memory.store(
                job_id,
                "research_report",
                report_text,
                project=project,
                metadata={"job_id": job_id, "report_path": report_path, "objective": objective},
            )
            vector_memory.store(
                report_text,
                project=project,
                session_id=job_id,
                subject="research_report",
                kind="research_report",
                role="system",
                metadata={"job_id": job_id, "report_path": report_path, "objective": objective},
            )
            timescale_memory.store_reasoning_summary(
                session_id=job_id,
                project=project,
                objective=objective,
                summary=(
                    f"Research report completed.\n"
                    f"Search seeds: {len(state['search_results'])}\n"
                    f"Filtered chunks: {len(state['filtered_chunks'])}\n"
                    f"Timescale matches: {len(state['memory_results'])}\n"
                    f"Vector matches: {len(state['vector_results'])}\n"
                    f"Report: {report_path}"
                ),
                metadata={"job_id": job_id, "report_path": report_path},
            )
            postprocess_research_project(project)
            return f"Report written to {report_path}"

        return f"Unhandled subtask: {subtask.description}"

    return executor

def start_agentic_research(
    objective: str,
    project: str = "general",
    max_results: int = 5,
    max_pages: int = 5,
    ttl_hours: int = 24 * 7,
) -> str:
    job_id = agentic_controller.create_job(
        description=f"[{project}] {objective}",
        task_decomposer=lambda _description: decompose_research_task(objective),
    )
    executor = build_research_executor(
        job_id=job_id,
        objective=objective,
        project=project,
        max_results=max_results,
        max_pages=max_pages,
        ttl_hours=ttl_hours,
    )
    agentic_controller.execute_job_async(job_id, executor)
    return job_id


def start_create_program_loop(
    objective: str,
    *,
    project: str = "general",
    hours: int = 24,
    cpu_target: int = 30,
    target_dir: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    safe_hours = max(1, min(int(hours or 24), 24 * 7))
    safe_cpu_target = max(15, min(int(cpu_target or 30), 60))
    selected_model = (model or LOCAL_CODE_MODEL or LOCAL_PRIMARY_MODEL).strip() or LOCAL_PRIMARY_MODEL
    max_cycles = max(2, min(8, safe_hours))
    job_id = agentic_controller.create_job(
        description=f"[{project}] create_program {objective}",
        task_decomposer=lambda _description: decompose_program_task(objective, max_cycles=max_cycles),
    )
    executor = build_program_executor(
        job_id=job_id,
        objective=objective,
        project=project,
        hours=safe_hours,
        cpu_target=safe_cpu_target,
        target_dir=target_dir,
        model=selected_model,
    )
    agentic_controller.execute_job_async(job_id, executor)
    return job_id


def extract_agentic_report_path(status: Dict[str, Any], log: List[Dict[str, Any]]) -> Optional[str]:
    candidates = [
        str(status.get("final_result") or ""),
        str(status.get("summary") or ""),
    ]
    candidates.extend(str(item.get("result") or "") for item in log or [])

    patterns = (
        r"Report written to\s+(.+)",
        r"Report:\s+(.+)",
        r"Build report written to\s+(.+)",
    )
    for text in candidates:
        for line in text.splitlines():
            for pattern in patterns:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if not match:
                    continue
                raw_path = match.group(1).strip().strip("`\"'")
                try:
                    candidate_path = Path(raw_path)
                except Exception:
                    continue
                if candidate_path.exists() and candidate_path.is_file():
                    return str(candidate_path)
    return None


PROGRAM_METRIC_CODE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".ps1", ".sh", ".bat", ".cmd",
    ".html", ".css", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
    ".swift", ".xml",
}


def _safe_program_workspace_path(candidate: Optional[str]) -> Optional[Path]:
    if not candidate:
        return None
    try:
        workspace = Path(str(candidate).strip().strip("`\"'")).expanduser().resolve()
    except Exception:
        return None

    program_root = (Path(__file__).resolve().parent / "agentic_jobs" / "program_workspaces").resolve()
    try:
        workspace.relative_to(program_root)
    except ValueError:
        return None

    if not workspace.exists() or not workspace.is_dir():
        return None
    return workspace


def extract_agentic_workspace_path(status: Dict[str, Any], log: List[Dict[str, Any]], report_text: str = "") -> Optional[str]:
    candidates = [
        str(status.get("workspace") or ""),
        str(status.get("final_result") or ""),
        str(status.get("summary") or ""),
        report_text or "",
    ]
    candidates.extend(str(item.get("result") or "") for item in log or [])

    patterns = (
        r"Workspace:\s+(.+)",
        r"stable workspace\s+(.+?)\s+for\s+plan",
        r"workspace\s+(.+?)\s+for\s+plan",
    )
    for text_block in candidates:
        for line in str(text_block).splitlines():
            for pattern in patterns:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if not match:
                    continue
                raw_path = match.group(1).strip().strip("`\"'")
                workspace = _safe_program_workspace_path(raw_path)
                if workspace:
                    return str(workspace)
    return None


def summarize_program_workspace_metrics(workspace_candidate: Optional[str]) -> Dict[str, Any]:
    workspace = _safe_program_workspace_path(workspace_candidate)
    if not workspace:
        return {"available": False, "error": "workspace unavailable or outside program workspace root"}

    skip_dirs = {"artifacts", "__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache"}
    code_files: List[Dict[str, Any]] = []
    total_lines = 0
    total_bytes = 0

    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(workspace).parts):
            continue
        if path.suffix.lower() not in PROGRAM_METRIC_CODE_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nonblank_lines = sum(1 for line in content.splitlines() if line.strip())
        total_lines += nonblank_lines
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        code_files.append({
            "path": path.relative_to(workspace).as_posix(),
            "lines": nonblank_lines,
            "suffix": path.suffix.lower(),
        })

    latest_snapshot: Dict[str, Any] = {}
    latest_path = workspace / "LATEST_SNAPSHOT.json"
    if latest_path.exists():
        try:
            latest_snapshot = json.loads(latest_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            latest_snapshot = {}

    try:
        created = datetime.utcfromtimestamp(workspace.stat().st_ctime)
    except OSError:
        created = datetime.utcnow()
    duration_seconds = max((datetime.utcnow() - created).total_seconds(), 1.0)
    report_path = latest_snapshot.get("report_path") or str(workspace / "BUILD_REPORT.md")
    if report_path and not Path(str(report_path)).exists():
        report_path = ""

    return {
        "available": True,
        "workspace": str(workspace),
        "created_at": created.isoformat(),
        "duration_seconds": round(duration_seconds, 2),
        "code_files": len(code_files),
        "code_lines": total_lines,
        "code_bytes": total_bytes,
        "code_lines_per_minute": round(total_lines / max(duration_seconds / 60.0, 0.016), 2),
        "largest_files": sorted(code_files, key=lambda item: item["lines"], reverse=True)[:8],
        "phase": latest_snapshot.get("phase") or "",
        "cycle": latest_snapshot.get("cycle") or 0,
        "max_cycles": latest_snapshot.get("max_cycles") or 0,
        "last_test_ok": bool(latest_snapshot.get("last_test_ok")),
        "last_test_runner": latest_snapshot.get("last_test_runner") or "",
        "last_test_excerpt": latest_snapshot.get("last_test_excerpt") or "",
        "subtask_count": latest_snapshot.get("subtask_count") or 0,
        "logic_block_count": latest_snapshot.get("logic_block_count") or 0,
        "written_files": latest_snapshot.get("written_files") or [],
        "report_path": report_path,
    }


def context_window_policy() -> Dict[str, Any]:
    """Expose the single effective source of truth for context/reply sizing."""
    return runtime_context_policy()


def build_agentic_result_reply(
    status: Dict[str, Any],
    *,
    report_path: Optional[str] = None,
    report_text: str = "",
) -> str:
    job_id = status.get("job_id", "unknown")
    state = status.get("status", "unknown")
    description = status.get("description", "agentic job")
    lines = [
        f"Agentic job {job_id} is {state}.",
        f"Task: {description}",
        f"Progress: {status.get('progress', 'unknown')}",
    ]
    if report_path:
        lines.append(f"Report: {report_path}")
    if status.get("summary"):
        lines.extend(["", "Summary:", str(status.get("summary")).strip()])
    if status.get("final_result"):
        lines.extend(["", "Final result:", str(status.get("final_result")).strip()])
    if report_text:
        preview = report_text.strip()
        if len(preview) > 4500:
            preview = preview[:4500].rstrip() + "\n\n[report preview trimmed]"
        lines.extend(["", "Report preview:", preview])
    if status.get("failed_steps"):
        failed = [
            f"- Step {item.get('step')}: {item.get('description')} ({item.get('error')})"
            for item in status.get("failed_steps", [])
        ]
        lines.extend(["", "Failed steps:", "\n".join(failed)])
    return "\n".join(line for line in lines if line is not None).strip()


async def agent_chooser(prompt: str):
    """Single-model local blueprint router."""
    return LOCAL_PRIMARY_MODEL

# ===== ROUTES =====

@app.get("/")
@app.get("/ui")
async def get_ui():
    ui_path = os.path.join(os.path.dirname(__file__), 'aegis_ui_clone.html')
    if os.path.exists(ui_path):
        return FileResponse(ui_path, media_type='text/html')
    return HTMLResponse(content="<h1>UI file not found</h1>", status_code=404)

@app.get("/api/health")
async def health():
    resolved_mode = resolve_runtime_mode(global_config["kernel_mode"])
    if resolved_mode == "alice" and alice_available():
        effective_kernel = "ALICE"
    elif resolved_mode == "xeon" and xeon_available():
        effective_kernel = "XEON"
    elif resolved_mode == "manifold" and cloud_manifold_available():
        effective_kernel = "MANIFOLD"
    elif resolved_mode == "local" or not CLOUD_EXECUTION_ENABLED or kernel_state["local_fallback_active"]:
        effective_kernel = "LOCAL"
    else:
        effective_kernel = "CLOUD"
    return {
        "status": "MOLTBOOK_v3.8.1_ACTIVE",
        "engine": "FASTAPI_UVIVORN",
        "kernel": effective_kernel,
        "mode": global_config["kernel_mode"],
        "resolved_mode": resolved_mode,
        "google_paid_enabled": AEGIS_GOOGLE_PAID_ENABLED,
        "cloud_execution_enabled": CLOUD_EXECUTION_ENABLED,
        "cloud_manifold_enabled": cloud_manifold_available(),
        "xeon_enabled": xeon_available(),
        "alice_enabled": alice_available(),
        "runtime_priority": runtime_priority(),
        "runtime_labels": runtime_labels(),
        "local_only_mode": LOCAL_ONLY_MODE,
        "local_primary_model": LOCAL_PRIMARY_MODEL,
        "local_code_model": LOCAL_CODE_MODEL,
        "local_tool_model": LOCAL_TOOL_MODEL,
        "ollama_models": ollama_model_status(),
        "fabric_mode": {
            "enabled": FABRIC_ONLY_MODE,
            "pruning_enabled": FABRIC_PRUNING_ENABLED,
            "positive_reinforcement_enabled": FABRIC_POSITIVE_REINFORCEMENT,
            "wisdom": fabric_wisdom_status(project="general"),
        },
        "source_roles": source_role_status(project="general", include_sources=False),
        "context_window_policy": context_window_policy(),
        "lava_event_plane": lava_event_orchestrator.runtime_status(project="general"),
        "ram_working_memory": ram_working_memory.status() if RAM_WORKING_MEMORY_ENABLED else {"enabled": False},
        "runtime_traces": runtime_trace_status(project="general"),
        "openai_filter_backup": {
            "enabled": OPENAI_ESCALATION_ENABLED,
            "available": openai_filter_available(),
            "model": OPENAI_ESCALATION_MODEL,
            "api_key_present": OPENAI_API_KEY_PRESENT,
            "role": "optional comprehension/evidence filter; not the PicoClaw code writer",
        },
        "agent_sidecars": {
            "picoclaw": picoclaw_runtime_status(),
            "picoclaw_environment": picoclaw_environment_sidecar.status(),
            "browser_use": browser_use_runtime_status(),
            "aider_terminal": aider_terminal_lane.status(),
        },
        "script_registry": registry_status(),
        "remote_topology": runtime_topology_status(),
        "runtime_features": runtime_feature_surface(),
        "system_twin": personal_system_twin.status(),
        "fabris": fabris_status(),
        "memory_status": get_memory_status(),
        "rag_status": get_memory_status(),
        "vector_status": vector_memory.status(),
        "db_status": manifold_db.status(),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/aider/status")
async def get_aider_terminal_status():
    return aider_terminal_lane.status()


@app.get("/api/aider/jobs")
async def list_aider_terminal_jobs(limit: int = 20):
    return {"jobs": aider_terminal_lane.list_jobs(limit=limit)}


@app.get("/api/aider/job/{job_id}")
async def get_aider_terminal_job(job_id: str):
    job = aider_terminal_lane.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Aider job not found")
    return job


@app.post("/api/aider/run")
async def run_aider_terminal_job(data: AiderRunRequest):
    prompt = (data.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    return await asyncio.to_thread(
        aider_terminal_lane.start_run,
        prompt=prompt,
        project=normalize_project(data.project),
        cwd=data.cwd,
        model=data.model,
        dry_run=bool(data.dry_run),
        read_only=bool(data.read_only),
    )


@app.post("/api/aider/job/{job_id}/stop")
async def stop_aider_terminal_job(job_id: str):
    return aider_terminal_lane.stop_job(job_id)


@app.post("/api/genetic-coder/run")
async def run_genetic_coder_job(data: GeneticCoderRequest):
    objective = (data.objective or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="objective is required")
    if (data.language or "python").lower().strip() != "python":
        raise HTTPException(status_code=400, detail="first genetic coder lane is python-only; other compilers attach next")
    return genetic_coder_manager.start(
        objective=objective,
        project=normalize_project(data.project),
        language=data.language or "python",
        outline=data.outline or "",
        snippets=data.snippets or [],
        max_generations=max(1, min(int(data.max_generations or 8), 200)),
        population=max(1, min(int(data.population or 4), 50)),
        timebox_minutes=max(1, min(int(data.timebox_minutes or 20), 24 * 60)),
        workspace=data.workspace,
    )


@app.get("/api/genetic-coder/jobs")
async def list_genetic_coder_jobs():
    return {"jobs": genetic_coder_manager.list_jobs()}


@app.get("/api/genetic-coder/job/{job_id}")
async def get_genetic_coder_job(job_id: str):
    job = genetic_coder_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Genetic coder job not found")
    return job


@app.post("/api/genetic-coder/job/{job_id}/stop")
async def stop_genetic_coder_job(job_id: str):
    return genetic_coder_manager.stop(job_id)


@app.get("/api/lava/status")
async def get_lava_event_status(project: str = "general"):
    return lava_event_orchestrator.runtime_status(project=normalize_project(project))


@app.get("/api/lava/events")
async def get_lava_events(project: str = "general", limit: int = 30):
    return lava_event_orchestrator.recent_events(project=normalize_project(project), limit=limit)


@app.post("/api/lava/event")
async def post_lava_event(data: LavaEventRequest):
    return lava_event_orchestrator.record_event(
        project=normalize_project(data.project),
        event_type=data.event_type,
        source=data.source or "aegis-ui",
        target=data.target or "aegis-lava-event-plane",
        content=data.content or {},
        performative=data.performative or "tell",
        status=data.status or "observed",
        score=float(data.score or 0.0),
        fabric_domain=data.fabric_domain,
        reinforce_fabric=bool(data.reinforce_fabric),
    )


@app.get("/api/context/policy")
async def get_context_policy():
    return context_window_policy()


@app.get("/api/source-roles/status")
async def get_source_roles_status(project: str = "general", include_sources: bool = True):
    return source_role_status(project=normalize_project(project), include_sources=include_sources)


@app.post("/api/source-roles/reindex")
async def reindex_source_roles():
    return await asyncio.to_thread(rebuild_external_source_index)


@app.post("/api/source-roles/trace")
async def trace_source_roles(data: SourceTraceRequest):
    input_text = (data.input_text or "").strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="input_text is required")
    return await asyncio.to_thread(
        trace_source_selection,
        input_text,
        normalize_project(data.project),
        max(1, min(int(data.limit or 6), 12)),
    )


@app.get("/api/source-roles/traces")
async def list_source_role_traces(project: str = "general", limit: int = 20):
    return await asyncio.to_thread(
        recent_source_selection_traces,
        normalize_project(project),
        max(1, min(int(limit or 20), 100)),
    )


@app.get("/api/architecture/optimization-checks")
async def get_optimization_checks(project: str = "general", persist_snapshot: bool = False):
    return await asyncio.to_thread(
        optimization_check_status,
        normalize_project(project),
        bool(persist_snapshot),
    )


@app.post("/api/architecture/optimization-checks/snapshot")
async def snapshot_optimization_checks(project: str = "general"):
    path = await asyncio.to_thread(write_optimization_check_snapshot, None, normalize_project(project))
    return {"ok": True, "path": str(path)}


@app.get("/api/architecture/phase1/status")
async def get_phase1_architecture_status(project: str = "general"):
    return await asyncio.to_thread(phase1_status, normalize_project(project))


@app.post("/api/architecture/phase1/compile")
async def compile_phase1_template(data: Phase1CompileRequest):
    input_text = (data.input_text or "").strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="input_text is required")
    return await asyncio.to_thread(
        compile_unified_template,
        input_text,
        normalize_project(data.project),
        data.mode or "deterministic",
        bool(data.persist),
    )


@app.post("/api/architecture/phase1/smoke-test")
async def run_phase1_architecture_smoke_test(project: str = "general"):
    return await asyncio.to_thread(run_phase1_smoke_tests, normalize_project(project))


@app.post("/api/architecture/phase1/snapshot")
async def snapshot_phase1_architecture(project: str = "general"):
    path = await asyncio.to_thread(write_phase1_snapshot, None, normalize_project(project))
    return {"ok": True, "path": str(path)}


@app.get("/api/architecture/emergency-stop")
async def get_phase1_emergency_stop(project: str = "general"):
    return await asyncio.to_thread(emergency_stop_status, normalize_project(project))


@app.post("/api/architecture/emergency-stop")
async def set_phase1_emergency_stop(data: Phase1EmergencyStopRequest):
    return await asyncio.to_thread(
        set_emergency_stop,
        normalize_project(data.project),
        bool(data.active),
        data.reason or "",
    )


@app.post("/api/architecture/objective/validate")
async def validate_phase1_objective(data: Phase1ObjectiveValidationRequest):
    objective = (data.objective or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="objective is required")
    return await asyncio.to_thread(
        validate_objective,
        normalize_project(data.project),
        objective,
        data.evidence or {},
    )


@app.get("/api/picoclaw/environment")
async def get_picoclaw_environment_status():
    return picoclaw_environment_sidecar.status()


@app.post("/api/picoclaw/environment/tick")
async def run_picoclaw_environment_tick():
    return await picoclaw_environment_sidecar.tick_once(reason="manual_api")


@app.post("/api/picoclaw/one-step-write")
async def run_picoclaw_one_step_write(data: PicoClawOneStepWriteRequest):
    project = normalize_project(data.project)
    root = Path(__file__).resolve().parent / "agentic_jobs" / "picoclaw_one_step_writes" / project
    return await asyncio.to_thread(
        picoclaw_one_step_write,
        data.objective,
        data.relative_path or "index.html",
        root_dir=root,
        timeout_seconds=max(10, min(int(data.timeout_seconds or 45), 180)),
    )


@app.get("/api/fabris/status")
async def get_fabris_status():
    return fabris_status()


@app.get("/api/fabris/patterns")
async def get_fabris_patterns(project: str = "general", route: str = "", hours: int = 48, limit: int = 10):
    normalized_project = normalize_project(project)
    safe_hours = max(1, min(int(hours), 24 * 30))
    safe_limit = max(1, min(int(limit), 50))
    return {
        "project": normalized_project,
        "route": route or None,
        "hours": safe_hours,
        "limit": safe_limit,
        "patterns": top_fabris_patterns(
            project=normalized_project,
            route_name=(route or None),
            since_hours=safe_hours,
            limit=safe_limit,
        ),
    }


@app.get("/api/fabric/wisdom/status")
async def get_fabric_wisdom_status(project: str = "general"):
    normalized_project = normalize_project(project)
    return {
        "fabric_mode_enabled": FABRIC_ONLY_MODE,
        "pruning_enabled": FABRIC_PRUNING_ENABLED,
        "positive_reinforcement_enabled": FABRIC_POSITIVE_REINFORCEMENT,
        "wisdom": fabric_wisdom_status(project=normalized_project),
        "ram": fabric_ram_status(project=normalized_project),
        "active_guidance_block": build_fabric_guidance_block(
            project=normalized_project,
            limit=6,
            prune=FABRIC_PRUNING_ENABLED,
        ),
    }


@app.post("/api/fabric/templates/reload")
async def reload_fabric_templates(project: str = "general", pin_vram: bool = True):
    normalized_project = normalize_project(project)
    seeded = await asyncio.to_thread(seed_default_json_templates, normalized_project)
    loaded = await asyncio.to_thread(load_json_templates_from_disk, normalized_project)
    vram = await asyncio.to_thread(try_pin_fabric_chooser_to_vram, normalized_project) if pin_vram else None
    return {
        "project": normalized_project,
        "seeded": seeded,
        "loaded": loaded,
        "ram": fabric_ram_status(project=normalized_project),
        "vram": vram,
    }


@app.post("/api/fabric/templates/pin-vram")
async def pin_fabric_templates_to_vram(project: str = "general"):
    normalized_project = normalize_project(project)
    return await asyncio.to_thread(try_pin_fabric_chooser_to_vram, normalized_project)


@app.get("/api/runtime-traces/status")
async def get_runtime_trace_status(project: str = "general"):
    normalized_project = normalize_project(project)
    return runtime_trace_status(project=normalized_project)


@app.get("/api/runtime-traces/recent")
async def get_recent_runtime_traces(project: str = "general", trace_type: str = "", limit: int = 50):
    normalized_project = normalize_project(project)
    return {
        "project": normalized_project,
        "trace_type": trace_type or None,
        "traces": recent_runtime_traces(
            project=normalized_project,
            trace_type=trace_type or "",
            limit=max(1, min(int(limit), 500)),
        ),
    }


@app.get("/api/ram/status")
async def get_ram_working_status():
    if not RAM_WORKING_MEMORY_ENABLED:
        return {"enabled": False}
    return ram_working_memory.status()


@app.get("/api/script-registry/status")
async def get_script_registry_status():
    return registry_status()


@app.get("/api/script-registry/search")
async def search_script_registry(query: str = "", language: str = "", limit: int = 20):
    return {
        "query": query,
        "language": language,
        "limit": limit,
        "results": search_scripts(query=query, language=language, limit=limit),
    }


@app.post("/api/script-registry/ingest")
async def ingest_script_registry(data: ScriptRegistryIngestRequest):
    roots = [Path(root) for root in (data.roots or [])] if data.roots else None
    return ingest_scripts(roots)


@app.post("/api/feedback")
async def post_feedback(data: FeedbackData):
    try:
        project = normalize_project(data.project)
        manifold_db.record_feedback(message_id=data.message_id, score=data.score)
        conditioning_payload = {
            "kind": "positive_conditioning" if data.score > 0 else "negative_conditioning",
            "message_id": data.message_id,
            "run_id": data.run_id,
            "score": data.score,
            "project": project,
            "prompt": (data.prompt or "")[:5000],
            "response": (data.response or "")[:8000],
            "route": data.route or "",
            "response_ms": data.response_ms,
            "logic_points": data.logic_points or [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        path = append_feedback_conditioning(conditioning_payload)
        fabric_result = await asyncio.to_thread(
            record_fabric_feedback,
            project=project,
            score=float(data.score or 0.0),
            prompt_text=(data.prompt or ""),
            response_text=(data.response or ""),
            positive_reinforcement=FABRIC_POSITIVE_REINFORCEMENT,
        )
        pruned = 0
        if FABRIC_PRUNING_ENABLED and float(data.score or 0.0) <= 0:
            pruned = await asyncio.to_thread(prune_low_weight_prompts, project, 0.35)
        if data.score > 0:
            print(f"[LEARNING] Positive conditioning recorded for {data.run_id or data.message_id}.")

        return {
            "status": "recorded",
            "conditioning_path": path,
            "fabric_feedback": fabric_result,
            "fabric_pruned": pruned,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/signal/status")
async def get_signal_status():
    if red_dot_state["active"] and red_dot_state["last_seen"]:
        last_seen_dt = datetime.fromisoformat(red_dot_state["last_seen"])
        if datetime.now() - last_seen_dt > timedelta(seconds=15):
            red_dot_state["active"] = False
    return red_dot_state

@app.post("/api/signal")
async def receive_signal(data: SignalData):
    red_dot_state.update({
        "active": True,
        "x": data.x,
        "y": data.y,
        "last_seen": datetime.now().isoformat()
    })
    return {"status": "ok"}

@app.delete("/api/conversation/local")
async def delete_conversation():
    session = SessionLocal()
    try:
        session.query(Conversation).delete()
        session.commit()
        chat_memory.clear()
        return {"status": "cleared"}
    finally:
        session.close()

@app.post("/api/secrets")
async def store_project_secrets(data: SecretsData):
    project = normalize_project(data.project)
    timescale_memory.store_secrets(data.secrets, project=project)
    return {"status": "stored", "project": project, "keys": sorted(data.secrets.keys())}

@app.get("/api/secrets")
async def get_project_secrets(project: Optional[str] = "general", date: Optional[str] = None):
    clean_project = normalize_project(project)
    return {
        "project": clean_project,
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "secrets": timescale_memory.get_secrets(date=date, project=clean_project),
    }

@app.get("/api/vector/status")
async def get_vector_status():
    return vector_memory.status()

@app.get("/api/knowledge-library/status")
async def get_knowledge_library_status():
    return knowledge_library_status()

@app.get("/api/knowledge-library/search")
async def query_knowledge_library(query: str, project: Optional[str] = "general", limit: int = 8, domain: Optional[str] = None):
    clean_project = normalize_project(project)
    return {
        "query": query,
        "project": clean_project,
        "domain": domain or "",
        "results": search_knowledge_library(query, project=clean_project, limit=max(1, min(limit, 24)), domain=domain),
    }

@app.post("/api/knowledge-library/ingest")
async def ingest_knowledge_library_endpoint(data: KnowledgeLibraryIngestRequest):
    clean_project = normalize_project(data.project)
    result = await asyncio.to_thread(
        ingest_knowledge_library,
        project=clean_project,
        max_sources=data.max_sources,
        max_chunks_per_source=max(1, min(int(data.max_chunks_per_source or 80), 200)),
        timeout_seconds=max(10, min(int(data.timeout_seconds or 35), 120)),
    )
    return result

@app.post("/api/knowledge-library/reindex")
async def reindex_knowledge_library_endpoint(data: KnowledgeLibraryReindexRequest):
    clean_project = normalize_project(data.project)
    result = await asyncio.to_thread(
        reindex_knowledge_library_chunks,
        project=clean_project,
        force=bool(data.force),
        domain=(data.domain or "").strip().lower() or None,
        limit=max(1, min(int(data.limit), 50000)) if data.limit else None,
    )
    return result

@app.get("/api/vector/search")
async def search_vector_memory(query: str, project: Optional[str] = "general", limit: int = 6):
    clean_project = normalize_project(project)
    return {
        "query": query,
        "project": clean_project,
        "results": vector_memory.search(query, project=clean_project, limit=max(1, min(limit, 20))),
    }

@app.get("/api/project/dashboard")
async def get_project_dashboard(project: Optional[str] = "general"):
    clean_project = normalize_project(project)
    project_status = timescale_memory.get_project_status(clean_project)
    reasoning_notes = timescale_memory.recent_reasoning_notes(clean_project, limit=4)
    directory_signatures = context_distiller.recent_signatures(clean_project, limit=4)
    vector_stats = vector_memory.project_stats(clean_project)
    vector_recent = vector_memory.recent_project_memories(clean_project, limit=12)
    recent_tool_actions = [item for item in vector_recent if item.get("kind") == "tool_action"][:6]
    secrets = timescale_memory.get_secrets(project=clean_project)

    return {
        "project": clean_project,
        "memory_status": get_memory_status(),
        "vector_status": vector_memory.status(),
        "db_status": manifold_db.status(),
        "project_timescale": project_status,
        "project_vector": vector_stats,
        "recent_reasoning_notes": reasoning_notes,
        "recent_directory_signatures": directory_signatures,
        "recent_vector_memories": vector_recent[:6],
        "recent_tool_actions": recent_tool_actions,
        "secret_keys": sorted(secrets.keys()),
        "sops": {
            "tools": [
                "Search project memory before repeating a long explanation or re-researching a solved bug.",
                "Use /research for multi-step web work so the loop can crawl, filter, vectorize, and write a report.",
                "Store project secrets through the secrets endpoint instead of burying them in chat context.",
                "Remote lanes keep the same memory and research surface; only direct desktop-touch actions relay to Local Hands."
            ],
            "coding": [
                "Open a project lane first and keep one concern per project so retrieval stays sharp.",
                "Capture checkpoints and design summaries in reasoning notes after major refactors.",
                "Prefer targeted fixes with project-aware context retrieval before broad rewrites.",
                "Use manifold or xeon lanes for heavy planning and indexing so desktop VRAM stays free for hands-on work."
            ],
            "desktop_automation": [
                "Use the desktop lane for UI/button workflows, not for normal code retrieval.",
                "Keep repeatable button-click procedures in SOP form so they can be executed consistently.",
                "When an automation touches external apps, record the goal and last known safe steps in reasoning notes.",
                "Phone bridges and external worker nodes stay under the same SOP contract even when they run on different hardware."
            ]
        },
        "runtime_features": runtime_feature_surface(),
    }

@app.post("/api/agentic/research")
async def create_agentic_research_job(data: AgenticResearchRequest):
    project = normalize_project(data.project)
    job_id = start_agentic_research(
        objective=data.task,
        project=project,
        max_results=max(1, min(data.max_results or 5, 10)),
        max_pages=max(1, min(data.max_pages or 5, 20)),
        ttl_hours=max(1, min(data.ttl_hours or (24 * 7), 24 * 30)),
    )
    return {"job_id": job_id, "job_type": "research", "status": "started", "project": project, "objective": data.task}


@app.post("/api/agentic/create-program")
async def create_program_job(data: CreateProgramRequest):
    project = normalize_project(data.project)
    workspace_path = Path(data.target_dir).expanduser().resolve() if data.target_dir else default_program_target_dir(Path(__file__).resolve().parent, project, data.task)
    job_id = start_create_program_loop(
        data.task,
        project=project,
        hours=max(1, min(data.hours or 24, 24 * 7)),
        cpu_target=max(15, min(data.cpu_target or 30, 60)),
        target_dir=str(workspace_path),
        model=data.model,
    )
    return {
        "job_id": job_id,
        "job_type": "program",
        "status": "started",
        "project": project,
        "workspace": str(workspace_path),
        "objective": data.task,
    }

@app.get("/api/agentic/job/{job_id}")
async def get_agentic_job_status(job_id: str):
    status = agentic_controller.get_job_status(job_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status

@app.get("/api/agentic/job/{job_id}/log")
async def get_agentic_job_log(job_id: str):
    log = agentic_controller.get_job_log(job_id)
    if not log:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "log": log}

@app.get("/api/agentic/job/{job_id}/result")
async def get_agentic_job_result(job_id: str):
    status = agentic_controller.get_job_status(job_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])

    log = agentic_controller.get_job_log(job_id)
    report_path = extract_agentic_report_path(status, log)
    report_text = ""
    if report_path:
        try:
            report_text = Path(report_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            report_text = ""

    workspace_path = extract_agentic_workspace_path(status, log, report_text)
    metrics = summarize_program_workspace_metrics(workspace_path) if workspace_path else {}

    return {
        **status,
        "report_path": report_path,
        "workspace": workspace_path,
        "metrics": metrics,
        "report_text": report_text[:12000],
        "reply": build_agentic_result_reply(status, report_path=report_path, report_text=report_text),
    }


@app.get("/api/agentic/workspace-metrics")
async def get_agentic_workspace_metrics(workspace: str):
    metrics = summarize_program_workspace_metrics(workspace)
    if not metrics.get("available"):
        raise HTTPException(status_code=404, detail=metrics.get("error") or "workspace metrics unavailable")
    return metrics

@app.get("/api/agentic/jobs")
async def list_agentic_jobs():
    return {"jobs": agentic_controller.list_jobs()}


@app.post("/api/training/execution-likelihood")
async def training_execution_likelihood(data: ExecutionLikelihoodRequest):
    return predict_execution_likelihood(data.dict())


@app.get("/api/training/conditioning")
async def get_training_conditioning(limit: int = 200):
    records = read_feedback_conditioning(limit=limit)
    positive = sum(1 for item in records if int(item.get("score") or 0) > 0)
    negative = sum(1 for item in records if int(item.get("score") or 0) < 0)
    logic_counts: Dict[str, int] = {}
    for item in records:
        for point in item.get("logic_points") or []:
            logic_counts[str(point)] = logic_counts.get(str(point), 0) + 1
    return {
        "records": records,
        "summary": {
            "count": len(records),
            "positive": positive,
            "negative": negative,
            "logic_counts": logic_counts,
        },
    }


@app.post("/api/training/long-research")
async def create_long_research_job(data: LongResearchRequest):
    project = normalize_project(data.project)
    hours = max(1, min(data.hours or 8, 48))
    cycles = max(2, min(data.cycles or hours, 24))
    max_results = max(1, min(data.max_results or 10, 12))
    max_pages = max(1, min(data.max_pages or 20, 24))
    job_id = agentic_controller.create_job(
        description=f"[{project}] long_research {data.task}",
        task_decomposer=lambda _description: decompose_long_research_task(
            data.task,
            hours=hours,
            cycles=cycles,
        ),
    )
    executor = build_long_research_executor(
        job_id=job_id,
        objective=data.task,
        project=project,
        hours=hours,
        cycles=cycles,
        max_results=max_results,
        max_pages=max_pages,
        base_dir=Path(__file__).resolve().parent,
        crawler_db=crawler_db,
        timescale_memory=timescale_memory,
        vector_memory=vector_memory,
        postprocess_callback=postprocess_research_project,
    )
    agentic_controller.execute_job_async(job_id, executor)
    return {
        "job_id": job_id,
        "job_type": "long_research",
        "status": "started",
        "project": project,
        "objective": data.task,
        "hours": hours,
        "cycles": cycles,
        "outputs_dir": str(Path(__file__).resolve().parent / "agentic_jobs" / "long_research" / project / job_id),
    }

@app.get("/api/research/search")
async def search_research_chunks(query: str, time_range: Optional[str] = "last_week", project: Optional[str] = None):
    clean_project = normalize_project(project) if project else None
    return {
        "query": query,
        "project": clean_project,
        "results": crawler_db.search_chunks(query, time_range=time_range, limit=10, project=clean_project),
    }

@app.post("/api/aegis/chat")
async def aegis_chat(data: ChatMessage, background_tasks: BackgroundTasks, request: Request):
    global optimizer, chat_memory
    request_started = time.perf_counter()
    dry_run = bool(getattr(data, "dry_run", False))
    dry_run_actions: List[Dict[str, Any]] = []
    if dry_run:
        background_tasks = DryRunBackgroundTasks(dry_run_actions)
    project = normalize_project(data.project)
    project, message = extract_project_override(data.message, project)
    raw_requested_mode = (data.mode or global_config["kernel_mode"] or "auto").strip().lower()
    requested_mode = normalize_kernel_mode(raw_requested_mode)
    request_profile = build_request_profile(message)
    if raw_requested_mode == "cloud" and not CLOUD_EXECUTION_ENABLED:
        local_result = await aegis_chat(
            ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
            background_tasks,
            request,
        )
        if isinstance(local_result, dict):
            local_result["thoughts"] = visible_runtime_thoughts(
                "Google paid cloud route is disabled by policy. "
                "Answered with the local/manifold stack instead."
            )
        return local_result
    resolved_mode = resolve_runtime_mode(requested_mode, request_profile)
    if not dry_run:
        global_config["kernel_mode"] = requested_mode
        kernel_state["mode"] = resolved_mode
    client_host = request.client.host if request.client else "local"
    session_id = f"dry-run:{getattr(data, 'replay_id', None) or client_host}" if dry_run else client_host
    chat_key = project_session_key(session_id, project)

    if chat_key not in chat_memory:
        chat_memory[chat_key] = []
    if not dry_run:
        sync_state(f"last_message_{session_id}", message)

    if request_profile.get("is_configuration_directive") and not CHAT_DIRECTIVE_CAPTURE_ENABLED:
        request_profile["directive_capture_suppressed"] = True

    if request_profile.get("is_configuration_directive") and CHAT_DIRECTIVE_CAPTURE_ENABLED:
        directive_path = directive_target_path(Path(__file__).resolve().parent, project)
        if dry_run:
            proposed = [{
                "type": "directive_file",
                "action": "would_update_project_directive",
                "path": str(directive_path),
                "project": project,
            }]
            dry_run_actions.extend(proposed)
        else:
            updated_directive = merge_project_directive_text(message, project=project)
            scope_name = normalize_project(project)
            is_project_lens = scope_name != "general"
            try:
                directive_path.write_text(updated_directive + "\n", encoding="utf-8")
                request_profile["directive_capture_applied"] = True
                background_tasks.add_task(
                    timescale_memory.store_reasoning_summary,
                    session_id=session_id,
                    project=project,
                    objective="project_directive_update",
                    summary=updated_directive[:1800],
                    metadata={
                        "kind": "project_lens" if is_project_lens else "project_directive",
                        "mode": requested_mode,
                        "path": str(directive_path),
                        "visible_reply": "model_continued",
                    },
                )
            except OSError as exc:
                request_profile["directive_capture_error"] = str(exc)

    direct_tool_call = detect_direct_tool_request(message, project=project) if DIRECT_ROUTE_ENABLED else None
    if direct_tool_call:
        if dry_run:
            payload = _render_dry_run_direct_reply(direct_tool_call, project=project, message=message)
            chat_memory[chat_key].append({"role": "user", "content": message})
            chat_memory[chat_key].append({"role": "assistant", "content": payload["reply"]})
            chat_memory[chat_key] = chat_memory[chat_key][-40:]
            return payload
        extra_response_fields: Dict[str, Any] = {}
        if direct_tool_call.get("performative") == "research_job":
            objective = str(direct_tool_call.get("objective", message)).strip() or message
            job_id = start_agentic_research(
                objective=objective,
                project=project,
                max_results=max(1, min(int(direct_tool_call.get("max_results", 6)), 10)),
                max_pages=max(1, min(int(direct_tool_call.get("max_pages", 6)), 20)),
                ttl_hours=max(1, min(int(direct_tool_call.get("ttl_hours", 24 * 14)), 24 * 30)),
            )
            reply_text = f"Agentic research loop started for: {objective}"
            thoughts_text = (
                f"Direct research route: job {job_id} is crawling, filtering, vectorizing, and preparing a report for project {project}."
            )
            extra_response_fields.update({"job_id": job_id, "job_type": "research", "objective": objective})
        elif direct_tool_call.get("performative") == "program_confirmation_request":
            objective = clean_program_objective(str(direct_tool_call.get("objective", message)).strip() or message)
            reply_text = build_program_confirmation_reply(
                objective,
                project=project,
                hours=max(1, min(int(direct_tool_call.get("hours", 24)), 24 * 7)),
                cpu_target=max(15, min(int(direct_tool_call.get("cpu_target", 30)), 60)),
            )
            thoughts_text = ""
            extra_response_fields.update({
                "job_type": "program_confirmation",
                "objective": objective,
                "approval_required": True,
                "confirmation_phrase": f"OK start program loop: {objective}",
            })
        elif direct_tool_call.get("performative") == "create_program_job":
            objective = clean_program_objective(str(direct_tool_call.get("objective", message)).strip() or message)
            workspace_path = default_program_target_dir(Path(__file__).resolve().parent, project, objective)
            job_id = start_create_program_loop(
                objective,
                project=project,
                hours=max(1, min(int(direct_tool_call.get("hours", 24)), 24 * 7)),
                cpu_target=max(15, min(int(direct_tool_call.get("cpu_target", 30)), 60)),
                target_dir=str(workspace_path),
                model=LOCAL_CODE_MODEL,
            )
            reply_text = f"Program loop started for: {objective}\nWorkspace: {workspace_path}"
            thoughts_text = (
                f"Direct program route: job {job_id} is using stable workspace {workspace_path} for plan -> implement -> test -> fix cycles."
            )
            extra_response_fields.update({
                "job_id": job_id,
                "job_type": "program",
                "workspace": str(workspace_path),
                "objective": objective,
            })
        elif isinstance(direct_tool_call.get("tool_calls"), list):
            tool_runs = execute_tool_calls(direct_tool_call.get("tool_calls", []))
            reply_blocks = []
            for index, tool_run in enumerate(tool_runs, start=1):
                tool_call = tool_run.get("tool_call", {})
                raw_tool_result = tool_run.get("result")
                rendered = sanitize_memory_tool_result_for_prompt(
                    tool_call,
                    tool_run.get("rendered", ""),
                    raw_tool_result,
                )
                if raw_tool_result:
                    background_tasks.add_task(
                        record_tool_action,
                        session_id=session_id,
                        project=project,
                        user_prompt=message,
                        tool_name=tool_call.get("tool", ""),
                        parameters=tool_call.get("parameters", {}),
                        ok=raw_tool_result.ok,
                        output=raw_tool_result.output,
                        result_metadata=raw_tool_result.metadata,
                        requested_mode=resolved_mode,
                        route_name="direct_tool",
                )
                reply_blocks.append(f"{index}. {tool_call.get('tool')}\n{rendered}")
            raw_text = "\n\n".join(reply_blocks)
            reply_text = raw_text or "No tool output was produced."
            thoughts_text = (
                f"Direct tool route: {direct_tool_call.get('performative', 'tool_batch')} "
                f"({len(tool_runs)} checks)"
            )
        else:
            raw_tool_result = execute_tool_result(direct_tool_call)
            rendered_result = sanitize_memory_tool_result_for_prompt(
                direct_tool_call,
                raw_tool_result.render(),
                raw_tool_result,
            )
            reply_text = rendered_result
            thoughts_text = f"Direct tool route: {direct_tool_call.get('tool')}"
            background_tasks.add_task(
                record_tool_action,
                session_id=session_id,
                project=project,
                user_prompt=message,
                tool_name=direct_tool_call.get("tool", ""),
                parameters=direct_tool_call.get("parameters", {}),
                ok=raw_tool_result.ok,
                output=raw_tool_result.output,
                result_metadata=raw_tool_result.metadata,
                requested_mode=resolved_mode,
                route_name="direct_tool",
            )
        chat_memory[chat_key].append({"role": "user", "content": message})
        chat_memory[chat_key].append({"role": "assistant", "content": reply_text})
        chat_memory[chat_key] = chat_memory[chat_key][-40:]
        background_tasks.add_task(
            postprocess_chat_turn,
            session_id=session_id,
            project=project,
            prompt=message,
            reply=reply_text,
            requested_mode=resolved_mode,
            target_model="direct_tool",
            route_name="direct_tool",
        )
        elapsed_ms = int((time.perf_counter() - request_started) * 1000)
        return {
            "reply": reply_text,
            "thoughts": visible_runtime_thoughts(thoughts_text),
            "project": project,
            "telemetry": build_logic_telemetry(
                request_profile,
                route_name="direct_tool",
                project=project,
                elapsed_ms=elapsed_ms,
                model="direct_tool",
            ),
            **extra_response_fields,
        }

    # MANUAL MODEL SELECTOR / LOCAL MODE
    if message.lower().startswith('/local') or resolved_mode == "local" or (kernel_state["local_fallback_active"] and datetime.now() < kernel_state["fallback_until"]):
        target_model = None
        prompt = message
        if message.lower().startswith('/local'):
            parts = message.split(' ', 2)
            if len(parts) > 2:
                target_model = parts[1]
                prompt = parts[2]
            elif len(parts) == 2:
                prompt = parts[1]
            else:
                prompt = message

        # Determine model
        if not target_model:
            target_model = await agent_chooser(prompt)
        request_profile = build_request_profile(prompt)
        if FABRIC_ONLY_MODE:
            request_profile.update(
                {
                    "requires_deliberate_mode": False,
                    "needs_research": False,
                    "needs_automation": False,
                    "needs_code_execution_loop": False,
                    "use_research_loop": False,
                    "must_make_code_run": False,
                }
            )

        print(f"[STREAM-INIT] Routing to {target_model}...")

        async def event_generator():
            simple_prompt_mode = (
                len((prompt or "").strip()) <= 160
                and not request_profile.get("requires_deliberate_mode")
                and not request_profile.get("needs_research")
                and not request_profile.get("needs_coding")
                and not request_profile.get("needs_verification")
                and not request_profile.get("needs_automation")
                and not request_profile.get("needs_system_diagnosis")
                and not request_profile.get("wants_full_response")
                and not request_profile.get("must_make_code_run")
                and not request_profile.get("needs_code_execution_loop")
                and not request_profile.get("use_research_loop")
            )
            if (
                request_profile.get("discussion_intent")
                and len((prompt or "").strip()) <= 1000
                and not request_profile.get("coding_action")
                and not request_profile.get("needs_research")
                and not request_profile.get("needs_automation")
                and not request_profile.get("needs_code_execution_loop")
            ):
                simple_prompt_mode = True
            if (
                request_profile.get("planning_only")
                and len((prompt or "").strip()) <= 500
                and not request_profile.get("needs_research")
                and not request_profile.get("needs_automation")
                and not request_profile.get("needs_system_diagnosis")
            ):
                simple_prompt_mode = True
            if FABRIC_ONLY_MODE:
                simple_prompt_mode = True
            show_status_updates = VISIBLE_STATUS_UPDATES or dry_run

            def status_event(text: str, **extra):
                if not show_status_updates:
                    return None
                payload = {"thoughts": text}
                payload.update(extra)
                return json.dumps(payload) + "\n"

            def keepalive_event():
                return "\n"

            if FABRIC_ONLY_MODE:
                short_round = {"packet": {}, "execution_plan": None, "round0_reply": ""}
            else:
                short_round = build_short_round_controller(prompt, project, request_profile)
            if short_round.get("round0_reply") and VISIBLE_ROUND0_REPLY:
                yield json.dumps({"reply_chunk": short_round["round0_reply"]}) + "\n"
                event = status_event(
                    "Round 0 sent. Building ACL/KQML packet and selecting deterministic Round 2 tools..."
                )
                if event:
                    yield event

            def stream_reply_chunks(text: str, chunk_size: int = 220):
                for start in range(0, len(text), chunk_size):
                    yield text[start:start + chunk_size]

            def get_response_budget() -> int:
                if simple_prompt_mode:
                    return RESPONSE_BUDGET_SIMPLE
                if request_profile.get("requires_deliberate_mode"):
                    budget = RESPONSE_BUDGET_DELIBERATE
                elif len((prompt or "").strip()) <= 140:
                    budget = max(RESPONSE_BUDGET_SIMPLE, RESPONSE_BUDGET_DEFAULT // 2)
                else:
                    budget = RESPONSE_BUDGET_DEFAULT
                if request_profile.get("wants_full_response"):
                    budget = max(budget, RESPONSE_BUDGET_FULL)
                if request_profile.get("must_make_code_run"):
                    budget = max(budget, RESPONSE_BUDGET_FULL)
                if request_profile.get("use_research_loop"):
                    budget = max(budget, RESPONSE_BUDGET_DELIBERATE)
                return min(budget, RESPONSE_BUDGET_MAX)

            def build_ollama_chat_payload(
                messages,
                *,
                num_predict: int,
                temperature: Optional[float],
                stream: bool,
            ) -> Dict[str, Any]:
                if simple_prompt_mode:
                    effective_temperature = 0.2
                else:
                    effective_temperature = 0.55 if request_profile.get("requires_deliberate_mode") else 0.8
                if temperature is not None:
                    effective_temperature = temperature
                return {
                    "model": target_model,
                    "messages": messages,
                    "stream": stream,
                    "options": {
                        "num_ctx": (
                            OLLAMA_NUM_CTX_SIMPLE
                            if simple_prompt_mode
                            else (
                                OLLAMA_NUM_CTX_LONG
                                if (
                                    request_profile.get("requires_deliberate_mode")
                                    or request_profile.get("must_make_code_run")
                                    or request_profile.get("use_research_loop")
                                    or request_profile.get("wants_full_response")
                                )
                                else OLLAMA_NUM_CTX_DEFAULT
                            )
                        ),
                        "temperature": effective_temperature,
                        "num_predict": num_predict,
                    },
                    "keep_alive": (
                        LOCAL_TOOL_KEEP_ALIVE
                        if target_model == LOCAL_TOOL_MODEL
                        else LOCAL_PRIMARY_KEEP_ALIVE
                    ),
                }

            def call_chat(messages, num_predict: int = 4096, temperature: Optional[float] = None):
                client_timeout = OLLAMA_CHAT_TIMEOUT_SECONDS
                body = json.dumps(
                    build_ollama_chat_payload(
                        messages,
                        num_predict=num_predict,
                        temperature=temperature,
                        stream=False,
                    )
                ).encode("utf-8")
                request_obj = urllib.request.Request(
                    f"{OLLAMA_API_BASE}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request_obj, timeout=client_timeout) as response:
                    return json.loads(response.read().decode("utf-8", errors="replace"))

            def stream_chat_tokens(messages, num_predict: int = 4096, temperature: Optional[float] = None):
                client_timeout = OLLAMA_CHAT_TIMEOUT_SECONDS
                body = json.dumps(
                    build_ollama_chat_payload(
                        messages,
                        num_predict=num_predict,
                        temperature=temperature,
                        stream=True,
                    )
                ).encode("utf-8")
                request_obj = urllib.request.Request(
                    f"{OLLAMA_API_BASE}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request_obj, timeout=client_timeout) as response:
                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        payload = json.loads(line)
                        if payload.get("error"):
                            raise RuntimeError(str(payload.get("error")))
                        token = ((payload.get("message") or {}).get("content") or "")
                        if token:
                            yield token
                        if payload.get("done"):
                            break

            # Chain of Thought Reasoning
            cot_thoughts = (
                f"Engaging local hardware ({target_model}). "
                f"Project lane: {project}. Mapping timescale and vector context... Analyzing objective..."
            )
            event = status_event(cot_thoughts)
            if event:
                yield event

            context_text = ""
            if not simple_prompt_mode and not FABRIC_ONLY_MODE:
                try:
                    context_text = trim_context_text(build_hybrid_context(session_id, project, prompt))
                except Exception as e:
                    print(f"[ERROR] Memory retrieval error: {e}")

            history = trim_chat_history(chat_memory.get(chat_key, []))
            if FABRIC_ONLY_MODE:
                history = history[-4:]
                fabric_guidance = build_fabric_guidance_block(
                    project=project,
                    limit=6,
                    prune=FABRIC_PRUNING_ENABLED,
                )
                reduction_lines = [
                    "Fabric-only guidance mode.",
                    f"Project lane: {project}",
                    "No scripted guided prompts. Use only user intent plus Fabric wisdom context.",
                    "Respond organically and directly. Do not auto-route into program loops unless explicitly requested.",
                    "Do not claim actions, tools, files, or tests unless evidence is present.",
                    "You are replying in a Web UI HTML stream: keep display output readable and do not dump raw tool payloads.",
                    "Tool calls must happen in a separate tool context/window; the main GUI reply receives only compressed evidence.",
                ]
                if fabric_guidance:
                    reduction_lines.append(fabric_guidance)
                reduction_brief = "\n".join(reduction_lines)
            elif simple_prompt_mode:
                persistent_directive = load_persistent_project_directive(
                    project=project,
                    include_global=bool(request_profile.get("needs_automation")),
                    include_guardian_fallback=bool(request_profile.get("needs_automation")),
                )
                history = []
                reduction_lines = [
                    "Simple prompt mode.",
                    f"Project lane: {project}",
                ]
                if persistent_directive:
                    reduction_lines.append(persistent_directive)
                reduction_lines.extend(
                    [
                        "Be direct, compact, and organic.",
                        "Do not claim you used tools, searched memory, inspected files, or changed anything unless tool evidence is present in the prompt.",
                        "Do not assume code words imply execution; talking about code, AI behavior, or possible improvements is conversation unless the user explicitly asks to run, edit, create files, start jobs, or approve PicoClaw.",
                        "Do not emit planning scaffolds, execution plans, JSON, markdown fences, or tool calls unless explicitly requested.",
                        "You are replying in a Web UI HTML stream; avoid raw tool payloads in the visible reply.",
                        "If the user asks for exactly one sentence, return exactly one sentence.",
                    ]
                )
                reduction_brief = "\n".join(reduction_lines)
            else:
                reduction_brief = build_global_reduction_brief(
                    prompt=prompt,
                    project=project,
                    request_profile=request_profile,
                    context_text=context_text,
                    history=history,
                )
                if request_profile.get("requires_deliberate_mode"):
                    reduction_brief = (
                        reduction_brief
                        + "\n\nSHORT ROUND PACKET:\n"
                        + json.dumps(short_round.get("packet", {}), indent=2)
                    )
            execution_plan = None
            if request_profile.get("requires_deliberate_mode"):
                event = status_event("Reducing context noise and locking an execution plan...")
                if event:
                    yield event
                execution_plan = short_round.get("execution_plan") or build_fast_execution_plan(prompt, project, request_profile)
                if should_use_model_planner(prompt, request_profile):
                    planner_messages = [
                        {
                            'role': 'system',
                            'content': f"{build_planner_prompt(project, request_profile)}\n\n{reduction_brief}",
                        }
                    ] + history + [{'role': 'user', 'content': prompt}]
                    planner_task = asyncio.create_task(
                        asyncio.to_thread(call_chat, planner_messages, 700, 0.2)
                    )
                    while not planner_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(planner_task), timeout=6.0)
                        except asyncio.TimeoutError:
                            event = status_event("Planner is reducing ambiguity and building step-by-step execution...")
                            if event:
                                yield event
                            else:
                                yield keepalive_event()
                    planner_response = planner_task.result()
                    model_plan = parse_execution_plan((planner_response.get('message') or {}).get('content', ''))
                    if model_plan:
                        execution_plan = model_plan
                if execution_plan:
                    background_tasks.add_task(
                        timescale_memory.store_reasoning_summary,
                        session_id=session_id,
                        project=project,
                        objective=prompt,
                        summary=format_execution_plan_summary(execution_plan),
                        metadata={"task_type": execution_plan.get("task_type"), "steps": execution_plan.get("steps", [])},
                    )
                    event = status_event(
                        "Execution plan ready: "
                        + " | ".join(execution_plan.get("steps", [])[:3])
                    )
                    if event:
                        yield event

            if simple_prompt_mode:
                system_prompt = (
                    "Respond naturally and directly. "
                    "For greetings or casual check-ins, answer conversationally without announcing your role. "
                    "For code discussion, architecture, reasoning, or AI-improvement ideas, talk through the idea instead of starting execution. "
                    "For explicit build, debug, tool, scripting, automation, or program-creation actions, be concrete and practical. "
                    "You are replying in a Web UI HTML stream, so format for readable display and keep raw tool calls out of the visible answer. "
                    "If tools are required, they must run in a separate tool context/window and return compressed evidence only. "
                    "Do not claim you used tools, searched memory, inspected files, or changed anything unless tool evidence is present in the prompt. "
                    "Do not emit canned readiness lines, status updates, planning scaffolds, JSON, markdown fences, or tool calls unless explicitly requested. "
                    "Do not invent formats the user did not ask for."
                )
            else:
                system_prompt = create_system_prompt(request_profile=request_profile)
            base_messages = [
                {'role': 'system', 'content': f'{system_prompt}\n\n{reduction_brief}'}
            ] + history + [{'role': 'user', 'content': build_execution_user_prompt(prompt, execution_plan, request_profile=request_profile, project=project)}]
            full_messages = list(base_messages)
            all_tool_context_blocks: List[str] = []
            kqml_conversation_id = new_conversation_id(f"aegis-{project}")
            kqml_trace: List[Dict[str, Any]] = []

            def build_kqml_tool_exchange_block(
                *,
                index: int,
                tool_call: Dict[str, Any],
                rendered_result: str,
                raw_tool_result: Any,
                route_name: str,
            ) -> str:
                request_message = make_tool_request_message(
                    tool_call,
                    index=index,
                    conversation_id=kqml_conversation_id,
                    route_name=route_name,
                )
                response_message = make_tool_result_message(
                    tool_call,
                    raw_tool_result,
                    request_message,
                )
                if raw_tool_result is None:
                    response_message["content"]["output"] = rendered_result
                kqml_trace.extend([request_message, response_message])
                return f"{index}. " + render_kqml_exchange(request_message, response_message)

            preflight_tool_calls = []
            if execution_plan and not simple_prompt_mode:
                preflight_tool_calls = should_execute_tool_calls(
                    prompt,
                    execution_plan.get("tool_calls", []),
                    request_profile=request_profile,
                )
            if preflight_tool_calls and dry_run:
                dry_run_actions.append({
                    "kind": "preflight_tool_calls",
                    "tool_calls": preflight_tool_calls,
                    "project": project,
                })
                event = status_event(
                    f"Dry run: {len(preflight_tool_calls)} preflight tool check(s) proposed; not executed.",
                    dry_run=True,
                    proposed_tool_calls=preflight_tool_calls,
                )
                if event:
                    yield event
            elif preflight_tool_calls:
                event = status_event(f"Fast plan found {len(preflight_tool_calls)} useful preflight tool check(s)...")
                if event:
                    yield event
                preflight_runs = execute_tool_calls(preflight_tool_calls)
                preflight_blocks = []
                for index, tool_run in enumerate(preflight_runs, start=1):
                    tool_call = tool_run.get("tool_call", {})
                    raw_tool_result = tool_run.get("result")
                    tool_result = sanitize_memory_tool_result_for_prompt(
                        tool_call,
                        tool_run.get("rendered", ""),
                        raw_tool_result,
                    )
                    if raw_tool_result:
                        background_tasks.add_task(
                            record_tool_action,
                            session_id=session_id,
                            project=project,
                            user_prompt=prompt,
                            tool_name=tool_call.get("tool", ""),
                            parameters=tool_call.get("parameters", {}),
                            ok=raw_tool_result.ok,
                            output=raw_tool_result.output,
                            result_metadata=raw_tool_result.metadata,
                            requested_mode=resolved_mode,
                            route_name="local_preflight_tool",
                        )
                    preflight_blocks.append(
                        build_kqml_tool_exchange_block(
                            index=index,
                            tool_call=tool_call,
                            rendered_result=tool_result,
                            raw_tool_result=raw_tool_result,
                            route_name="local_preflight_tool",
                        )
                    )
                all_tool_context_blocks.extend(preflight_blocks)
                full_messages = base_messages + [
                    {
                        'role': 'user',
                        'content': (
                            "Preflight tool results are available.\n\n"
                            + "\n\n".join(preflight_blocks)
                            + "\n\nUse these results immediately instead of rediscovering the same checks."
                            + (
                                "\n\nBuild-loop continuation: partition the evidence into AskSet, ConstraintSet, CodeSet, TestSet, and EvidenceSet. "
                                "Ask one internal question about the latest PicoClaw code/proposal, answer it, apply that answer to the next code/proposal, "
                                "then reinitialize the context to the current objective, partition, latest tool evidence, and verification state before summarizing."
                                if request_profile.get("needs_code_execution_loop")
                                else ""
                            )
                        ),
                    }
                ]

            full_reply = ""
            reply_streamed_live = False
            stream_final_reply_after_tool = False
            try:
                response_budget = get_response_budget()
                if simple_prompt_mode:
                    first_token_timeout_seconds = float(OLLAMA_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS)
                    max_stream_attempts = 3
                    stream_attempt = 1

                    def start_stream_worker() -> "queue.Queue[tuple[str, str]]":
                        stream_events: "queue.Queue[tuple[str, str]]" = queue.Queue()

                        def stream_worker() -> None:
                            try:
                                for token in stream_chat_tokens(full_messages, response_budget, None):
                                    stream_events.put(("token", token))
                            except Exception as exc:
                                stream_events.put(("error", str(exc)))
                            finally:
                                stream_events.put(("done", ""))

                        threading.Thread(target=stream_worker, daemon=True).start()
                        return stream_events

                    async def recover_and_retry_stream(reason: str) -> bool:
                        nonlocal stream_attempt, stream_events, first_token_deadline
                        await asyncio.to_thread(
                            record_runtime_trace,
                            project=project,
                            trace_type="stream_timeout_recovery",
                            route="local_chat",
                            model=target_model,
                            prompt_hash=prompt_hash(prompt),
                            elapsed_ms=int((time.perf_counter() - request_started) * 1000),
                            payload={
                                "reason": reason,
                                "attempt": stream_attempt,
                                "response_chars": len(full_reply),
                                "timeout_seconds": first_token_timeout_seconds,
                            },
                        )
                        if stream_attempt >= max_stream_attempts:
                            return False
                        try:
                            recovery = await asyncio.to_thread(
                                recycle_stalled_ollama_runner,
                                min_ram_mb=1800.0,
                            )
                        except Exception as exc:
                            print(f"[STREAM-RECOVERY] Recovery failed after {reason}: {exc}")
                            recovery = {"terminated": False, "error": str(exc)}
                        if not recovery.get("terminated"):
                            # Even without a recycle, retry the stream once because local
                            # Ollama can briefly return HTTP 500 during model handoff.
                            print(f"[STREAM-RECOVERY] No runner recycled after {reason}; retrying stream anyway: {recovery}")
                            await asyncio.sleep(1.0)
                        stream_attempt += 1
                        print(f"[STREAM-RECOVERY] Restarted stream after {reason}: {recovery}")
                        stream_events = start_stream_worker()
                        first_token_deadline = time.perf_counter() + first_token_timeout_seconds
                        return True

                    stream_events = start_stream_worker()
                    first_token_deadline = time.perf_counter() + first_token_timeout_seconds
                    while True:
                        try:
                            event_kind, event_value = await asyncio.to_thread(stream_events.get, True, 2.0)
                        except queue.Empty:
                            if not full_reply.strip() and time.perf_counter() >= first_token_deadline:
                                if await recover_and_retry_stream("first-token timeout"):
                                    continue
                                raise RuntimeError("local model produced no tokens before recovery deadline")
                            yield keepalive_event()
                            continue
                        if event_kind == "token":
                            full_reply += event_value
                            reply_streamed_live = True
                            yield json.dumps({"reply_chunk": event_value}) + "\n"
                            continue
                        if event_kind == "error":
                            if not full_reply.strip():
                                if await recover_and_retry_stream(f"stream error: {event_value}"):
                                    continue
                                raise RuntimeError(event_value)
                            break
                        if event_kind == "done":
                            break
                else:
                    response_task = asyncio.create_task(
                        asyncio.to_thread(call_chat, full_messages, response_budget, None)
                    )
                    while not response_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(response_task), timeout=8.0)
                        except asyncio.TimeoutError:
                            yield keepalive_event()
                    response = response_task.result()
                    full_reply = (response.get('message') or {}).get('content', '')

                if not full_reply.strip() and simple_prompt_mode:
                    fallback_response = await asyncio.to_thread(call_chat, full_messages, response_budget, None)
                    full_reply = (fallback_response.get('message') or {}).get('content', '')
                    if not full_reply.strip():
                        raise RuntimeError("local model returned no tokens")
                    for chunk in stream_reply_chunks(full_reply):
                        reply_streamed_live = True
                        yield json.dumps({"reply_chunk": chunk}) + "\n"

                if simple_prompt_mode:
                    explicit_tool_intent = bool(
                        request_profile.get("needs_automation")
                        or request_profile.get("needs_research")
                        or request_profile.get("needs_system_diagnosis")
                        or request_profile.get("coding_action")
                        or "tool" in (prompt or "").lower()
                    )
                    if FABRIC_ONLY_MODE and explicit_tool_intent:
                        tool_round_limit = 1
                    else:
                        tool_round_limit = 0
                elif request_profile.get("requires_deliberate_mode"):
                    tool_round_limit = MAX_TOOL_ROUNDS
                    if request_profile.get("must_make_code_run"):
                        tool_round_limit += 1
                    if request_profile.get("use_research_loop"):
                        tool_round_limit += 1
                elif request_profile.get("must_make_code_run"):
                    tool_round_limit = 2
                else:
                    tool_round_limit = 1
                tool_round_limit = min(tool_round_limit, 5)
                conversation_messages = list(full_messages)
                tool_round = 0

                while tool_round < tool_round_limit:
                    parsed_tool_calls = parse_tool_calls(full_reply)
                    approved_tool_calls = should_execute_tool_calls(
                        prompt,
                        parsed_tool_calls,
                        request_profile=request_profile,
                    )
                    if approved_tool_calls:
                        if dry_run:
                            dry_run_actions.append({
                                "kind": "model_tool_calls",
                                "tool_calls": approved_tool_calls,
                                "project": project,
                            })
                            event = status_event(
                                f"Dry run: {len(approved_tool_calls)} model-proposed tool call(s) recorded; not executed.",
                                dry_run=True,
                                proposed_tool_calls=approved_tool_calls,
                            )
                            if event:
                                yield event
                            full_reply = _append_dry_run_section(full_reply, approved_tool_calls)
                            break
                        tool_round += 1
                        tool_label = "tools" if len(approved_tool_calls) > 1 else "tool"
                        event = status_event(
                            f"Execution round {tool_round}/{tool_round_limit}: running {len(approved_tool_calls)} {tool_label}..."
                        )
                        if event:
                            yield event
                        tool_runs = execute_tool_calls(approved_tool_calls)
                        tool_context_blocks = []
                        for index, tool_run in enumerate(tool_runs, start=1):
                            tool_call = tool_run.get("tool_call", {})
                            raw_tool_result = tool_run.get("result")
                            tool_result = sanitize_memory_tool_result_for_prompt(
                                tool_call,
                                tool_run.get("rendered", ""),
                                raw_tool_result,
                            )
                            if raw_tool_result:
                                background_tasks.add_task(
                                    record_tool_action,
                                    session_id=session_id,
                                    project=project,
                                    user_prompt=prompt,
                                    tool_name=tool_call.get("tool", ""),
                                    parameters=tool_call.get("parameters", {}),
                                    ok=raw_tool_result.ok,
                                    output=raw_tool_result.output,
                                    result_metadata=raw_tool_result.metadata,
                                    requested_mode=resolved_mode,
                                    route_name="local_tool",
                                )
                            tool_context_blocks.append(
                                build_kqml_tool_exchange_block(
                                    index=index,
                                    tool_call=tool_call,
                                    rendered_result=tool_result,
                                    raw_tool_result=raw_tool_result,
                                    route_name="local_tool",
                                )
                            )
                        all_tool_context_blocks.extend(tool_context_blocks)

                        conversation_messages = conversation_messages + [
                            {'role': 'assistant', 'content': full_reply},
                            {
                                'role': 'user',
                                'content': build_tool_follow_up_prompt(
                                    tool_context_blocks,
                                    tool_round=tool_round,
                                    tool_round_limit=tool_round_limit,
                                    plan=execution_plan,
                                    request_profile=request_profile,
                                    prompt=prompt,
                                    project=project,
                                ),
                            }
                        ]
                        follow_up_task = asyncio.create_task(
                            asyncio.to_thread(call_chat, conversation_messages, 1600, None)
                        )
                        while not follow_up_task.done():
                            try:
                                await asyncio.wait_for(asyncio.shield(follow_up_task), timeout=8.0)
                            except asyncio.TimeoutError:
                                event = status_event(
                                    f"Execution round {tool_round}/{tool_round_limit} complete. Evaluating next step..."
                                )
                                if event:
                                    yield event
                                else:
                                    yield keepalive_event()
                        follow_up_response = follow_up_task.result()
                        full_reply = ((follow_up_response.get('message') or {}).get('content', '') or "").strip()
                        stream_final_reply_after_tool = True
                        continue

                    if parsed_tool_calls:
                        event = status_event("Tool call plan was skipped. Keeping only any direct prose reply...")
                        if event:
                            yield event
                        full_reply = extract_direct_reply_text(full_reply, project=project)
                    break

                if request_profile.get("needs_code_execution_loop"):
                    event = status_event("Build-loop review: self-questioning the latest code/proposal against tool evidence...")
                    if event:
                        yield event
                    review_messages = conversation_messages + [
                        {'role': 'assistant', 'content': full_reply},
                        {
                            'role': 'user',
                            'content': build_code_loop_self_review_prompt(
                                all_tool_context_blocks,
                                prompt=prompt,
                                project=project,
                                plan=execution_plan,
                                request_profile=request_profile,
                            ),
                        },
                    ]
                    review_task = asyncio.create_task(
                        asyncio.to_thread(call_chat, review_messages, 1700, 0.35)
                    )
                    while not review_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(review_task), timeout=8.0)
                        except asyncio.TimeoutError:
                            event = status_event("Build-loop review is applying the internal question to the candidate...")
                            if event:
                                yield event
                            else:
                                yield keepalive_event()
                    review_response = review_task.result()
                    review_reply = ((review_response.get('message') or {}).get('content', '') or "").strip()
                    review_tool_calls = should_execute_tool_calls(
                        prompt,
                        parse_tool_calls(review_reply),
                        request_profile=request_profile,
                    )
                    if review_tool_calls:
                        if dry_run:
                            dry_run_actions.append({
                                "kind": "build_loop_review_tool_calls",
                                "tool_calls": review_tool_calls,
                                "project": project,
                            })
                            full_reply = _append_dry_run_section(review_reply, review_tool_calls)
                        else:
                            event = status_event(
                                f"Build-loop review requested {len(review_tool_calls)} more tool check(s)..."
                            )
                            if event:
                                yield event
                            review_tool_runs = execute_tool_calls(review_tool_calls[:2])
                            review_blocks = []
                            for index, tool_run in enumerate(review_tool_runs, start=1):
                                tool_call = tool_run.get("tool_call", {})
                                raw_tool_result = tool_run.get("result")
                                tool_result = sanitize_memory_tool_result_for_prompt(
                                    tool_call,
                                    tool_run.get("rendered", ""),
                                    raw_tool_result,
                                )
                                if raw_tool_result:
                                    background_tasks.add_task(
                                        record_tool_action,
                                        session_id=session_id,
                                        project=project,
                                        user_prompt=prompt,
                                        tool_name=tool_call.get("tool", ""),
                                        parameters=tool_call.get("parameters", {}),
                                        ok=raw_tool_result.ok,
                                        output=raw_tool_result.output,
                                        result_metadata=raw_tool_result.metadata,
                                        requested_mode=resolved_mode,
                                        route_name="local_build_review_tool",
                                    )
                                review_blocks.append(
                                    build_kqml_tool_exchange_block(
                                        index=index,
                                        tool_call=tool_call,
                                        rendered_result=tool_result,
                                        raw_tool_result=raw_tool_result,
                                        route_name="local_build_review_tool",
                                    )
                                )
                            all_tool_context_blocks.extend(review_blocks)
                            final_review_messages = review_messages + [
                                {'role': 'assistant', 'content': review_reply},
                                {
                                    'role': 'user',
                                    'content': build_code_loop_self_review_prompt(
                                        all_tool_context_blocks,
                                        prompt=prompt,
                                        project=project,
                                        plan=execution_plan,
                                        request_profile=request_profile,
                                    ),
                                },
                            ]
                            final_review_response = await asyncio.to_thread(call_chat, final_review_messages, 1700, 0.25)
                            full_reply = ((final_review_response.get('message') or {}).get('content', '') or "").strip()
                            stream_final_reply_after_tool = True
                    elif review_reply:
                        full_reply = review_reply
                        stream_final_reply_after_tool = True

                if request_profile.get("needs_code_execution_loop") and openai_filter_available():
                    event = status_event(
                        f"Optional GPT filter ({OPENAI_ESCALATION_MODEL}) is checking comprehension and evidence boundaries..."
                    )
                    if event:
                        yield event
                    filter_result = await asyncio.to_thread(
                        call_openai_filter_backup,
                        prompt=prompt,
                        project=project,
                        packet=short_round.get("packet", {}),
                        evidence_blocks=all_tool_context_blocks,
                        draft_reply=full_reply,
                    )
                    if filter_result.get("ok"):
                        filter_text = str(filter_result.get("text") or "").strip()
                        all_tool_context_blocks.append(
                            f"OpenAI filter backup ({filter_result.get('model')}):\n{filter_text}"
                        )
                        full_reply = (
                            full_reply.rstrip()
                            + "\n\nGPT Filter Check:\n"
                            + filter_text[:1600].rstrip()
                        )
                    else:
                        event = status_event(
                            f"Optional GPT filter skipped or failed: {filter_result.get('reason') or filter_result.get('error', 'unknown')}"
                        )
                        if event:
                            yield event

                full_reply = apply_evidence_gate(full_reply, all_tool_context_blocks, request_profile)

                full_reply = finalize_reply_text(
                    full_reply,
                    prompt=prompt,
                    project=project,
                    source=target_model,
                )

                if stream_final_reply_after_tool:
                    yield json.dumps({"reply_chunk": "\n\n"}) + "\n"
                    for chunk in stream_reply_chunks(full_reply):
                        yield json.dumps({"reply_chunk": chunk}) + "\n"
                elif not reply_streamed_live:
                    for chunk in stream_reply_chunks(full_reply):
                        yield json.dumps({"reply_chunk": chunk}) + "\n"
                if dry_run_actions:
                    yield json.dumps({"dry_run": True, "proposed_actions": dry_run_actions}) + "\n"
                kqml_trace.append(
                    make_kqml_message(
                        "eos",
                        sender="aegis-coordinator",
                        receiver="web-ui",
                        language="json",
                        ontology="aegis.local_chat",
                        conversation_id=kqml_conversation_id,
                        content={"status": "complete", "route": "local_chat"},
                    )
                )
                yield json.dumps({
                    "telemetry": build_logic_telemetry(
                        request_profile,
                        route_name="local_chat",
                        project=project,
                        elapsed_ms=int((time.perf_counter() - request_started) * 1000),
                        model=target_model,
                    ),
                    "kqml_trace": kqml_trace[-80:],
                }) + "\n"

                # Update Memory
                chat_memory[chat_key].append({"role": "user", "content": prompt})
                chat_memory[chat_key].append({"role": "assistant", "content": full_reply})
                chat_memory[chat_key] = chat_memory[chat_key][-40:]
                if RAM_WORKING_MEMORY_ENABLED:
                    try:
                        ram_working_memory.add_turn(
                            session_id=session_id,
                            project=project,
                            prompt=prompt,
                            reply=full_reply,
                            thoughts=cot_thoughts,
                            image_descriptions=[],
                            route="local_chat",
                        )
                    except Exception as ram_exc:
                        print(f"[WARN] RAM working memory add_turn failed: {ram_exc}")
                background_tasks.add_task(
                    postprocess_chat_turn,
                    session_id=session_id,
                    project=project,
                    prompt=prompt,
                    reply=full_reply,
                    requested_mode=resolved_mode,
                    target_model=target_model,
                    route_name="local_chat",
                )

            except Exception as e:
                await asyncio.to_thread(
                    record_runtime_trace,
                    project=project,
                    trace_type="chat_error_or_timeout",
                    route="local_chat",
                    model=target_model if "target_model" in locals() else None,
                    prompt_hash=prompt_hash(prompt if "prompt" in locals() else message),
                    elapsed_ms=int((time.perf_counter() - request_started) * 1000),
                    payload={
                        "error": str(e),
                        "requested_mode": requested_mode,
                        "resolved_mode": resolved_mode,
                        "dry_run": dry_run,
                    },
                )
                yield json.dumps({"error": str(e)}) + "\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            background=background_tasks,
        )

    # 0. DEEP RESEARCH
    if message.lower().startswith('/research'):
        objective = message[9:].strip()
        if not objective:
            return {"reply": "Usage: /research <objective>", "thoughts": visible_runtime_thoughts("Awaiting target objective.")}
        if dry_run:
            return _render_dry_run_direct_reply({"performative": "research_job", "objective": objective}, project=project, message=message)
        job_id = start_agentic_research(objective, project=project)
        return {
            "reply": f"Agentic research loop started for: {objective}",
            "thoughts": visible_runtime_thoughts(f"Job {job_id} is crawling, indexing, vectorizing, and writing a report for project {project}."),
            "job_id": job_id,
            "job_type": "research",
            "project": project,
            "objective": objective,
        }

    if message.lower().startswith('/program'):
        objective = message[8:].strip()
        if not objective:
            return {
                "reply": "Usage: /program <objective> to talk through the first build shape, then /program confirm <objective> to start PicoClaw.",
                "thoughts": visible_runtime_thoughts("Awaiting target objective."),
            }
        confirmed_program_command = objective.lower().startswith("confirm ")
        if confirmed_program_command:
            objective = objective[8:].strip()
        objective = clean_program_objective(objective)
        if not confirmed_program_command:
            return {
                "reply": build_program_confirmation_reply(objective, project=project),
                "thoughts": "",
                "job_type": "program_confirmation",
                "project": project,
                "objective": objective,
                "approval_required": True,
                "confirmation_phrase": f"/program confirm {objective}",
            }
        if dry_run:
            return _render_dry_run_direct_reply({"performative": "create_program_job", "objective": objective}, project=project, message=message)
        workspace_path = default_program_target_dir(Path(__file__).resolve().parent, project, objective)
        job_id = start_create_program_loop(
            objective,
            project=project,
            hours=24,
            cpu_target=30,
            target_dir=str(workspace_path),
            model=LOCAL_CODE_MODEL,
        )
        return {
            "reply": f"Program loop started for: {objective}",
            "thoughts": visible_runtime_thoughts(f"Job {job_id} is using stable workspace {workspace_path} for plan -> implement -> test -> fix cycles."),
            "job_id": job_id,
            "job_type": "program",
            "project": project,
            "workspace": str(workspace_path),
            "objective": objective,
        }

        # 0.5 PROJECT ALICE EXECUTION (WITH STREAMING HEARTBEATS)
    if resolved_mode == "alice":
        if not alice_available():
            return await aegis_chat(
                ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
                background_tasks,
                request,
            )

        alice_request_profile = build_request_profile(message)
        if alice_request_profile.get("needs_automation"):
            fallback_message = (
                "Project ALICE keeps direct desktop-touch actions on Local Hands. "
                "Using the same project memory and SOP surface, then relaying this task locally."
            )
            local_result = await aegis_chat(
                ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
                background_tasks,
                request,
            )
            if isinstance(local_result, dict):
                local_result["thoughts"] = visible_runtime_thoughts(fallback_message)
            return local_result

        alice_payload = build_alice_payload(message, project, alice_request_profile)

        async def alice_stream():
            if VISIBLE_STATUS_UPDATES:
                yield json.dumps({"thoughts": "Project ALICE initiated. Transmitting objective to Manifold Node..."}) + "\n"
            alice_task = asyncio.create_task(asyncio.to_thread(run_cloud_alice_worker, alice_payload))

            # Streaming Heartbeat to prevent Cloudflare 524 Timeout (100s)
            while not alice_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(alice_task), timeout=15.0)
                except asyncio.TimeoutError:
                    if VISIBLE_STATUS_UPDATES:
                        yield json.dumps({"thoughts": "ALICE is reasoning on the 16GB Cloud Node. Maintaining tunnel connection..."}) + "\n"

            try:
                alice_result = alice_task.result()
                clean_res = finalize_reply_text(
                    str(alice_result.get("reply", "")).strip(),
                    prompt=message,
                    project=project,
                    source="project_alice",
                )
                thoughts = str(alice_result.get("thoughts", f"Project ALICE route completed with {ALICE_MODEL}.")).strip()

                chat_memory[chat_key].append({"role": "user", "content": message})
                chat_memory[chat_key].append({"role": "assistant", "content": clean_res})
                chat_memory[chat_key] = chat_memory[chat_key][-40:]

                background_tasks.add_task(
                    postprocess_chat_turn,
                    session_id=session_id,
                    project=project,
                    prompt=message,
                    reply=clean_res,
                    requested_mode=resolved_mode,
                    target_model=ALICE_MODEL,
                    route_name="project_alice",
                )

                if VISIBLE_STATUS_UPDATES:
                    yield json.dumps({"thoughts": thoughts, "project": project}) + "\n"

                # Stream the reply in chunks so the UI renders it properly like the local model
                chunk_size = 220
                clean_res = f"[ALICE] {clean_res}"
                for start in range(0, len(clean_res), chunk_size):
                    yield json.dumps({"reply_chunk": clean_res[start:start + chunk_size]}) + "\n"

            except Exception as exc:
                kernel_state.update({
                    "last_error": str(exc),
                    "local_fallback_active": True,
                    "fallback_until": datetime.now() + timedelta(minutes=5),
                })
                yield json.dumps({"error": f"ALICE Cloud Execution Failed: {str(exc)}"}) + "\n"

        return StreamingResponse(
            alice_stream(),
            media_type="text/event-stream",
            background=background_tasks,
        )

        alice_payload = build_alice_payload(message, project, request_profile)
        try:
            alice_result = await asyncio.to_thread(run_cloud_alice_worker, alice_payload)
            clean_res = finalize_reply_text(
                str(alice_result.get("reply", "")).strip(),
                prompt=message,
                project=project,
                source="project_alice",
            )
            thoughts = str(alice_result.get("thoughts", f"Project ALICE route completed with {ALICE_MODEL}.")).strip()
            chat_memory[chat_key].append({"role": "user", "content": message})
            chat_memory[chat_key].append({"role": "assistant", "content": clean_res})
            chat_memory[chat_key] = chat_memory[chat_key][-40:]
            background_tasks.add_task(
                postprocess_chat_turn,
                session_id=session_id,
                project=project,
                prompt=message,
                reply=clean_res,
                requested_mode=resolved_mode,
                target_model=ALICE_MODEL,
                route_name="project_alice",
            )
            return {"reply": f"[ALICE] {clean_res}", "thoughts": visible_runtime_thoughts(thoughts), "project": project}
        except Exception as exc:
            kernel_state.update({
                "last_error": str(exc),
                "local_fallback_active": True,
                "fallback_until": datetime.now() + timedelta(minutes=5),
            })
            fallback_mode = "xeon" if xeon_available() else "local"
            return await aegis_chat(
                ChatMessage(message=data.message, mode=fallback_mode, retry=data.retry, project=project),
                background_tasks,
                request,
            )

    # 0.75 XEON SWARM EXECUTION
    if resolved_mode == "xeon":
        if not xeon_available():
            fallback_mode = "manifold" if cloud_manifold_available() else "local"
            return await aegis_chat(
                ChatMessage(message=data.message, mode=fallback_mode, retry=data.retry, project=project),
                background_tasks,
                request,
            )

        xeon_request_profile = build_request_profile(message)
        if xeon_request_profile.get("needs_automation"):
            fallback_message = (
                "Xeon swarm keeps direct desktop-touch actions on Local Hands. "
                "Using the same project memory and SOP surface, then relaying desktop steps locally."
            )
            local_result = await aegis_chat(
                ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
                background_tasks,
                request,
            )
            if isinstance(local_result, dict):
                local_result["thoughts"] = visible_runtime_thoughts(fallback_message)
            return local_result

        xeon_payload = build_xeon_payload(message, project, xeon_request_profile)
        try:
            xeon_result = await asyncio.to_thread(run_xeon_swarm_worker, xeon_payload)
            clean_res = finalize_reply_text(
                str(xeon_result.get("reply", "")).strip(),
                prompt=message,
                project=project,
                source="xeon_swarm",
            )
            thoughts = str(xeon_result.get("thoughts", "Xeon swarm task completed.")).strip()
            chat_memory[chat_key].append({"role": "user", "content": message})
            chat_memory[chat_key].append({"role": "assistant", "content": clean_res})
            chat_memory[chat_key] = chat_memory[chat_key][-40:]
            background_tasks.add_task(
                postprocess_chat_turn,
                session_id=session_id,
                project=project,
                prompt=message,
                reply=clean_res,
                requested_mode=resolved_mode,
                target_model="xeon_swarm",
                route_name="xeon_swarm",
            )
            response_payload = {"reply": f"[XEON] {clean_res}", "thoughts": visible_runtime_thoughts(thoughts), "project": project}
            if xeon_result.get("report_path"):
                response_payload["report_path"] = xeon_result.get("report_path")
            return response_payload
        except Exception as exc:
            kernel_state.update({
                "last_error": str(exc),
                "local_fallback_active": True,
                "fallback_until": datetime.now() + timedelta(minutes=5),
            })
            fallback_mode = "manifold" if cloud_manifold_available() else "local"
            return await aegis_chat(
                ChatMessage(message=data.message, mode=fallback_mode, retry=data.retry, project=project),
                background_tasks,
                request,
            )

    # 1. CLOUD MANIFOLD EXECUTION
    if resolved_mode == "manifold":
        if not cloud_manifold_available():
            fallback_mode = "xeon" if xeon_available() else "local"
            return await aegis_chat(
                ChatMessage(message=data.message, mode=fallback_mode, retry=data.retry, project=project),
                background_tasks,
                request,
            )

        manifold_request_profile = build_request_profile(message)
        if manifold_request_profile.get("needs_automation") and not CLOUD_MANIFOLD_ALLOW_LOCAL_HANDS:
            fallback_message = (
                "Cloud manifold keeps desktop and direct OS actions on the local runtime. "
                "Switching this request to local hands."
            )
            local_result = await aegis_chat(
                ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
                background_tasks,
                request,
            )
            if isinstance(local_result, dict):
                local_result["thoughts"] = visible_runtime_thoughts(fallback_message)
            return local_result

        manifold_payload = build_cloud_manifold_payload(message, project, manifold_request_profile)
        try:
            manifold_result = await asyncio.to_thread(run_cloud_manifold_worker, manifold_payload)
            clean_res = finalize_reply_text(
                str(manifold_result.get("reply", "")).strip(),
                prompt=message,
                project=project,
                source="cloud_manifold",
            )
            thoughts = str(manifold_result.get("thoughts", "Cloud manifold task completed.")).strip()
            chat_memory[chat_key].append({"role": "user", "content": message})
            chat_memory[chat_key].append({"role": "assistant", "content": clean_res})
            chat_memory[chat_key] = chat_memory[chat_key][-40:]
            background_tasks.add_task(
                postprocess_chat_turn,
                session_id=session_id,
                project=project,
                prompt=message,
                reply=clean_res,
                requested_mode=resolved_mode,
                target_model="cloud_manifold",
                route_name="cloud_manifold",
            )
            response_payload = {"reply": f"[MANIFOLD] {clean_res}", "thoughts": visible_runtime_thoughts(thoughts), "project": project}
            if manifold_result.get("report_path"):
                response_payload["report_path"] = manifold_result.get("report_path")
            return response_payload
        except Exception as exc:
            kernel_state.update({
                "last_error": str(exc),
                "local_fallback_active": True,
                "fallback_until": datetime.now() + timedelta(minutes=5),
            })
            return await aegis_chat(
                ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
                background_tasks,
                request,
            )

    # 2. CLOUD EXECUTION
    if not CLOUD_EXECUTION_ENABLED:
        fallback_message = (
            "Google paid cloud route is disabled by policy. "
            "Routing this request to the non-Google local/manifold stack instead."
        )
        local_result = await aegis_chat(
            ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
            background_tasks,
            request,
        )
        if isinstance(local_result, dict):
            local_result["thoughts"] = visible_runtime_thoughts(fallback_message)
        return local_result

    gemini_cmd_path = os.getenv(
        "AEGIS_GEMINI_CMD",
        str(USER_HOME / "AppData" / "Roaming" / "npm" / "gemini.cmd"),
    )
    cloud_request_profile = request_profile
    if cloud_request_profile.get("needs_automation"):
        fallback_message = (
            "CLI cloud keeps direct desktop-touch actions on Local Hands. "
            "Using the same project memory and SOP surface, then relaying this task locally."
        )
        local_result = await aegis_chat(
            ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
            background_tasks,
            request,
        )
        if isinstance(local_result, dict):
            local_result["thoughts"] = visible_runtime_thoughts(fallback_message)
        return local_result

    cloud_prompt = build_cloud_execution_prompt(message, project, cloud_request_profile)
    try:
        def run_cli():
            return subprocess.run([gemini_cmd_path, "-p", cloud_prompt, "--approval-mode=yolo", "--resume", "latest"], capture_output=True, text=True, shell=False, timeout=600)
        result = await asyncio.to_thread(run_cli)

        if "quota exceeded" in result.stdout.lower() or "429" in result.stderr:
            kernel_state.update({"local_fallback_active": True, "fallback_until": datetime.now() + timedelta(minutes=15)})
            return await aegis_chat(
                ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
                background_tasks,
                request,
            )

        def strip_ansi(text): return re.sub(r'\x1b\[[0-9;]*m', '', text)
        clean_res = strip_ansi(result.stdout).strip() or strip_ansi(result.stderr).strip()
        clean_res = finalize_reply_text(clean_res, prompt=message, project=project, source="cloud_cli")
        chat_memory[chat_key].append({"role": "user", "content": message})
        chat_memory[chat_key].append({"role": "assistant", "content": clean_res})
        chat_memory[chat_key] = chat_memory[chat_key][-40:]
        background_tasks.add_task(
            postprocess_chat_turn,
            session_id=session_id,
            project=project,
            prompt=message,
            reply=clean_res,
            requested_mode=resolved_mode,
            target_model="cloud_cli",
            route_name="cloud_chat",
        )

        return {"reply": f"[CLOUD] {clean_res}", "thoughts": visible_runtime_thoughts("Teacher manifold verified.")}
    except Exception as exc:
        kernel_state.update({
            "local_fallback_active": True,
            "fallback_until": datetime.now() + timedelta(minutes=10),
            "last_error": str(exc),
        })
        return await aegis_chat(
            ChatMessage(message=data.message, mode="local", retry=data.retry, project=project),
            background_tasks,
            request,
        )


# ==============================================================================
# AEGIS-LENS OBSERVER AGENT INTEGRATION
# ==============================================================================
lens_memory_state = {
    "last_activity": None,
    "last_summary": None,
    "last_update": None,
    "stuck_count": 0,
    "active_node": None,
    "last_confidence": 0.0,
}

@app.post("/api/lens/update")
async def update_lens_context(request: Request):
    data = await request.json()
    node = data.get("node", "unknown")
    activity = str(data.get("activity", "unknown")).strip().lower() or "unknown"
    summary = data.get("summary", "")
    confidence = float(data.get("confidence", 0.0) or 0.0)

    # 1. Trigger System: Error State
    if activity == "error state":
        print(f"\n[!] AEGIS-LENS ALERT: Error detected on node {node}: {summary}\n")
        # Here we could trigger a background worker to research the error automatically

    # 2. Auto-help logic: Check if stuck
    if activity == "debugging" and lens_memory_state["last_activity"] == "debugging":
        lens_memory_state["stuck_count"] += 1
        if lens_memory_state["stuck_count"] > 10:  # ~2 minutes if checks are every 10s
            print(f"\n[*] AEGIS-LENS NOTIFICATION: User seems stuck on {summary}. Suggesting intervention.\n")
    else:
        lens_memory_state["stuck_count"] = 0

    # 3. Context Memory & 4. Cross-Node Awareness
    lens_memory_state["last_activity"] = activity
    lens_memory_state["last_summary"] = summary
    lens_memory_state["last_update"] = data.get("timestamp")
    lens_memory_state["active_node"] = node
    lens_memory_state["last_confidence"] = confidence

    try:
        twin_record = personal_system_twin.record_event(
            {
                "source": "aegis_lens",
                "node": node,
                "activity": activity,
                "summary": summary,
                "confidence": confidence,
                "timestamp": data.get("timestamp") or data.get("time"),
                "project": data.get("project") or data.get("project_lane") or "general",
            }
        )
    except Exception as exc:
        twin_record = {"ok": False, "error": str(exc)}

    print(f"[CORE] Lens Memory Updated: {node} is {activity} -> {summary[:60]}")

    return {
        "status": "memory_updated",
        "recorded_activity": activity,
        "system_twin": {
            "ok": bool(twin_record.get("ok")),
            "active_workflow": (twin_record.get("snapshot") or {}).get("active_workflow"),
            "habit_hints": (twin_record.get("snapshot") or {}).get("habit_hints", [])[:3],
            "error": twin_record.get("error"),
        },
    }


@app.get("/api/system-twin/status")
async def system_twin_status():
    return personal_system_twin.status()


@app.post("/api/system-twin/event")
async def record_system_twin_event(request: Request):
    data = await request.json()
    return personal_system_twin.record_event(data)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5005)
