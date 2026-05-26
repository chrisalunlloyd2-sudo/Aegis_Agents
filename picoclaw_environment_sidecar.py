"""
Resident PicoClaw environment maintainer.

This is not an external scheduler or wrapper script. It is loaded by the AEGIS
runtime and keeps a small, inspectable sidecar loop alive inside that process.
The deterministic part collects state and enforces strict process env vars; the
PicoClaw model is asked for bounded maintenance decisions when something drifts.
"""

from __future__ import annotations

import asyncio
import csv
import ctypes
import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from picoclaw_bridge import ask_picoclaw_maintenance_decision, picoclaw_runtime_status


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "system_twin"
STATE_PATH = STATE_DIR / "picoclaw_environment_sidecar.json"
LOG_PATH = STATE_DIR / "picoclaw_environment_sidecar.log"
DB_PATH = ROOT / "gemini_bridge.db"


STRICT_ENV_CONTRACT: Dict[str, str] = {
    "AEGIS_LOCAL_ONLY": "1",
    "AEGIS_DISABLE_CLOUD": "1",
    "AEGIS_ENABLE_GOOGLE_PAID": "0",
    "AEGIS_FORCE_LOCAL_VECTOR": "1",
    "AEGIS_CHAT_DIRECTIVE_CAPTURE_ENABLED": "0",
    "AEGIS_DIRECT_ROUTE_ENABLED": "0",
    "AEGIS_FABRIC_ONLY_MODE": "1",
    "AEGIS_FABRIC_PRUNING_ENABLED": "1",
    "AEGIS_FABRIC_POSITIVE_REINFORCEMENT": "1",
    "AEGIS_ALWAYS_ON_LOGIC": "1",
    "AEGIS_RAM_WORKING_MEMORY_ENABLED": "1",
    "AEGIS_RAM_WORKING_MEMORY_MB": "128",
    "AEGIS_RAM_SUMMARY_SLOTS": "10",
    "AEGIS_RAM_LEXICAL_SLOTS": "10",
    "AEGIS_RAM_SEMANTIC_SLOTS": "10",
    "AEGIS_RAM_LOG_SLOTS": "10",
    "AEGIS_RAM_LAST_REPLIES_SLOTS": "15",
    "AEGIS_VISIBLE_STATUS_UPDATES": "1",
    "AEGIS_VISIBLE_ROUND0_REPLY": "0",
    "AEGIS_INTENT_MARKERS_ENABLED": "0",
    "AEGIS_LOCAL_PRIMARY_MODEL": "aegis-gemma2-abliterated:2b-q8",
    "AEGIS_LOCAL_CODE_MODEL": "aegis-gemma2-abliterated:2b-q8",
    "AEGIS_LOCAL_TOOL_MODEL": "qwen2.5-coder:1.5b",
    "AEGIS_LOCAL_TOOL_FALLBACK_MODEL": "aegis-gemma2-abliterated:2b-q8",
    "AEGIS_PICOCLAW_MODEL": "aegis-gemma2-abliterated:2b-q8",
    "AEGIS_PICOCLAW_PREFER_DIRECT": "1",
    "AEGIS_PICOCLAW_API_BASE": "http://127.0.0.1:11434/v1",
    "AEGIS_OLLAMA_API_BASE": "http://127.0.0.1:11434",
    "AEGIS_OLLAMA_SINGLE_ACTIVE_MODEL": "1",
    "AEGIS_OLLAMA_PRIMARY_KEEP_ALIVE": "12m",
    "AEGIS_OLLAMA_TOOL_KEEP_ALIVE": "2m",
    "AEGIS_OLLAMA_EMBED_KEEP_ALIVE": "4m",
    "OLLAMA_KEEP_ALIVE": "15m",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q4_0",
}


WATCH_PROCESS_NAMES = {
    "codex",
    "ollama",
    "python",
    "python.exe",
    "msedge",
    "msedge.exe",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _gb(value: float) -> float:
    return round(value / (1024 ** 3), 2)


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def collect_memory_snapshot() -> Dict[str, Any]:
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    used = status.ullTotalPhys - status.ullAvailPhys
    return {
        "used_percent": round(float(status.dwMemoryLoad), 2),
        "used_gb": _gb(float(used)),
        "free_gb": _gb(float(status.ullAvailPhys)),
        "total_gb": _gb(float(status.ullTotalPhys)),
    }


def _parse_tasklist_ram(value: str) -> float:
    cleaned = re.sub(r"[^0-9]", "", value or "")
    if not cleaned:
        return 0.0
    return round(int(cleaned) / 1024.0, 2)


def collect_process_snapshot(limit: int = 16) -> List[Dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception as exc:
        return [{"error": f"tasklist failed: {exc}"}]
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "tasklist failed").strip()
        return [{"error": detail[:500]}]

    rows: List[Dict[str, Any]] = []
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) < 5:
            continue
        image_name = (row[0] or "").strip()
        lower_name = image_name.lower()
        base_name = lower_name.removesuffix(".exe")
        if lower_name not in WATCH_PROCESS_NAMES and base_name not in WATCH_PROCESS_NAMES:
            continue
        try:
            pid = int(row[1])
        except ValueError:
            pid = 0
        rows.append(
            {
                "name": image_name,
                "pid": pid,
                "ram_mb": _parse_tasklist_ram(row[4]),
            }
        )
    return sorted(rows, key=lambda item: item.get("ram_mb", 0.0), reverse=True)[:limit]


def enforce_strict_environment() -> List[Dict[str, str]]:
    drift: List[Dict[str, str]] = []
    for key, expected in STRICT_ENV_CONTRACT.items():
        current = os.environ.get(key)
        if current != expected:
            drift.append(
                {
                    "name": key,
                    "before": "" if current is None else str(current),
                    "after": expected,
                }
            )
            os.environ[key] = expected
    return drift


def build_picoclaw_maintenance_prompt(snapshot: Dict[str, Any]) -> str:
    compact = {
        "timestamp": snapshot.get("timestamp"),
        "memory": snapshot.get("memory"),
        "alerts": snapshot.get("alerts"),
        "env_drift_count": len(snapshot.get("env_drift") or []),
        "top_processes": snapshot.get("processes", [])[:8],
        "recent_memory_events": recent_memory_events(5),
        "allowed_actions": ["OBSERVE", "WARN_ONLY", "RECYCLE_OLLAMA"],
    }
    return (
        "(ask-one\n"
        "  :sender \"aegis-runtime\"\n"
        "  :receiver \"picoclaw-sidecar\"\n"
        "  :language \"acl-kqml\"\n"
        "  :ontology \"environment-maintenance\"\n"
        "  :content (\n"
        "    :role \"resident environment maintainer\"\n"
        "    :policy \"Keep AEGIS local-first, no cloud credits, no auto replies, no scripts, no broad kills.\"\n"
        "    :allowed-actions \"OBSERVE, WARN_ONLY, RECYCLE_OLLAMA\"\n"
        "    :decision-rules \"If alerts contains ollama_high_ram, choose RECYCLE_OLLAMA. If alerts contains ram_pressure without ollama_high_ram, choose WARN_ONLY. If there are no alerts, choose OBSERVE. Env drift is already corrected by the host and should not require action unless paired with alerts.\"\n"
        "    :state-json "
        + json.dumps(compact, ensure_ascii=True)
        + "\n"
        "  )\n"
        "  :reply-format \"JSON only: {\\\"action\\\":\\\"OBSERVE|WARN_ONLY|RECYCLE_OLLAMA\\\",\\\"reason\\\":\\\"short\\\"}\"\n"
        ")"
    )


def parse_picoclaw_action(text: str) -> Dict[str, str]:
    cleaned = (text or "").strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
            action = str(payload.get("action", "OBSERVE")).strip().upper()
            reason = str(payload.get("reason", "")).strip()
            return {"action": action, "reason": reason[:240]}
        except Exception:
            pass
    upper = cleaned.upper()
    for action in ("RECYCLE_OLLAMA", "WARN_ONLY", "OBSERVE"):
        if action in upper:
            return {"action": action, "reason": cleaned[:240]}
    return {"action": "OBSERVE", "reason": cleaned[:240] or "No explicit PicoClaw action."}


def ensure_memory_db() -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS picoclaw_environment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                memory_used_percent REAL,
                env_drift_count INTEGER,
                alert_count INTEGER,
                pico_action TEXT,
                effective_action TEXT,
                action_ok INTEGER,
                summary_json TEXT NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def record_memory_event(snapshot: Dict[str, Any]) -> None:
    ensure_memory_db()
    timestamp = str(snapshot.get("timestamp") or datetime.utcnow().isoformat())
    event_type = str(snapshot.get("reason") or "interval")
    memory = snapshot.get("memory") if isinstance(snapshot.get("memory"), dict) else {}
    decision = snapshot.get("picoclaw_decision") if isinstance(snapshot.get("picoclaw_decision"), dict) else {}
    effective_decision = snapshot.get("effective_decision") if isinstance(snapshot.get("effective_decision"), dict) else {}
    action_result = snapshot.get("action_result") if isinstance(snapshot.get("action_result"), dict) else {}
    used_percent = memory.get("used_percent") if isinstance(memory, dict) else None
    env_drift_count = len(snapshot.get("env_drift") or [])
    alert_count = len(snapshot.get("alerts") or [])
    pico_action = str(decision.get("action") or "OBSERVE")
    effective_action = str(effective_decision.get("action") or pico_action or "OBSERVE")
    action_ok = 1 if bool(action_result.get("ok")) else 0
    summary = {
        "timestamp": timestamp,
        "reason": event_type,
        "memory": snapshot.get("memory"),
        "alerts": snapshot.get("alerts"),
        "env_drift_count": env_drift_count,
        "picoclaw_decision": decision,
        "effective_decision": effective_decision,
        "contract_override": snapshot.get("contract_override"),
        "action_result": action_result,
    }
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            """
            INSERT INTO picoclaw_environment_events (
                timestamp,
                event_type,
                memory_used_percent,
                env_drift_count,
                alert_count,
                pico_action,
                effective_action,
                action_ok,
                summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                event_type,
                float(used_percent) if used_percent is not None else None,
                int(env_drift_count),
                int(alert_count),
                pico_action,
                effective_action,
                int(action_ok),
                json.dumps(summary, ensure_ascii=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def recent_memory_events(limit: int = 8) -> List[Dict[str, Any]]:
    ensure_memory_db()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, timestamp, event_type, memory_used_percent, env_drift_count, alert_count,
                   pico_action, effective_action, action_ok
            FROM picoclaw_environment_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


@dataclass
class PicoClawEnvironmentSidecar:
    enabled: bool = field(default_factory=lambda: _env_bool("AEGIS_PICOCLAW_ENV_SIDECAR_ENABLED", True))
    interval_seconds: int = field(default_factory=lambda: _env_int("AEGIS_PICOCLAW_ENV_INTERVAL_SECONDS", 60, minimum=20, maximum=1800))
    decision_interval_seconds: int = field(default_factory=lambda: _env_int("AEGIS_PICOCLAW_ENV_DECISION_INTERVAL_SECONDS", 600, minimum=60, maximum=7200))
    max_ram_percent: float = field(default_factory=lambda: _env_float("AEGIS_PICOCLAW_ENV_MAX_RAM_PERCENT", 82.0, minimum=50.0, maximum=98.0))
    max_ollama_runner_mb: float = field(default_factory=lambda: _env_float("AEGIS_PICOCLAW_ENV_MAX_OLLAMA_MB", 1800.0, minimum=512.0, maximum=16000.0))
    _task: Optional[asyncio.Task] = field(default=None, init=False, repr=False)
    _stop: Optional[asyncio.Event] = field(default=None, init=False, repr=False)
    _action_handlers: Dict[str, Callable[..., Dict[str, Any]]] = field(default_factory=dict, init=False, repr=False)
    _last_decision_at: float = field(default=0.0, init=False)
    _last_snapshot: Dict[str, Any] = field(default_factory=dict, init=False)

    async def start(self, action_handlers: Optional[Dict[str, Callable[..., Dict[str, Any]]]] = None) -> None:
        self._action_handlers = action_handlers or {}
        if not self.enabled:
            self._last_snapshot = {
                "status": "disabled",
                "timestamp": datetime.utcnow().isoformat(),
                "reason": "AEGIS_PICOCLAW_ENV_SIDECAR_ENABLED=0",
            }
            self._write_state(self._last_snapshot)
            return
        if self._task and not self._task.done():
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="picoclaw-environment-sidecar")

    async def stop(self) -> None:
        if self._stop:
            self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def status(self) -> Dict[str, Any]:
        running = bool(self._task and not self._task.done())
        return {
            "enabled": self.enabled,
            "running": running,
            "interval_seconds": self.interval_seconds,
            "decision_interval_seconds": self.decision_interval_seconds,
            "strict_env_count": len(STRICT_ENV_CONTRACT),
            "state_path": str(STATE_PATH),
            "db_path": str(DB_PATH),
            "recent_memory_events": recent_memory_events(5),
            "last_snapshot": self._last_snapshot,
        }

    async def _run_loop(self) -> None:
        await self.tick_once(reason="startup")
        while self._stop and not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                await self.tick_once(reason="interval")

    async def tick_once(self, *, reason: str = "manual") -> Dict[str, Any]:
        snapshot = await asyncio.to_thread(self._collect_snapshot, reason)
        needs_decision = bool(snapshot.get("alerts") or snapshot.get("env_drift"))
        if time.time() - self._last_decision_at >= self.decision_interval_seconds:
            needs_decision = True
        if needs_decision:
            decision = await asyncio.to_thread(self._ask_picoclaw, snapshot)
            snapshot["picoclaw_decision"] = decision
            contract_action = self._contract_action(snapshot)
            snapshot["contract_action"] = contract_action
            effective_decision = dict(decision)
            if contract_action["action"] != "OBSERVE" and decision.get("action") != contract_action["action"]:
                snapshot["contract_override"] = {
                    "from": decision.get("action"),
                    "to": contract_action["action"],
                    "reason": contract_action["reason"],
                }
                effective_decision.update(contract_action)
            snapshot["effective_decision"] = effective_decision
            if effective_decision.get("action") == "RECYCLE_OLLAMA":
                snapshot["action_result"] = await asyncio.to_thread(
                    self._execute_recycle_ollama,
                    snapshot,
                    effective_decision,
                )
            self._last_decision_at = time.time()
        else:
            snapshot["picoclaw_decision"] = {"action": "OBSERVE", "reason": "State within contract; skipped model call."}
            snapshot["contract_action"] = {"action": "OBSERVE", "reason": "No contract violation."}
            snapshot["effective_decision"] = snapshot["picoclaw_decision"]
        self._last_snapshot = snapshot
        await asyncio.to_thread(self._write_state, snapshot)
        await asyncio.to_thread(record_memory_event, snapshot)
        return snapshot

    def _collect_snapshot(self, reason: str) -> Dict[str, Any]:
        env_drift = enforce_strict_environment()
        try:
            memory = collect_memory_snapshot()
        except Exception as exc:
            memory = {"error": str(exc)}
        processes = collect_process_snapshot()
        alerts: List[Dict[str, Any]] = []
        used_percent = float(memory.get("used_percent") or 0.0) if isinstance(memory, dict) else 0.0
        if used_percent >= self.max_ram_percent:
            alerts.append({"type": "ram_pressure", "used_percent": used_percent, "limit": self.max_ram_percent})
        for process in processes:
            if str(process.get("name", "")).lower().startswith("ollama") and float(process.get("ram_mb") or 0.0) >= self.max_ollama_runner_mb:
                alerts.append(
                    {
                        "type": "ollama_high_ram",
                        "pid": process.get("pid"),
                        "ram_mb": process.get("ram_mb"),
                        "limit_mb": self.max_ollama_runner_mb,
                    }
                )
                break
        return {
            "status": "watching",
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "memory": memory,
            "processes": processes,
            "env_contract": {
                "count": len(STRICT_ENV_CONTRACT),
                "names": sorted(STRICT_ENV_CONTRACT.keys()),
            },
            "env_drift": env_drift,
            "alerts": alerts,
            "picoclaw_runtime": picoclaw_runtime_status(),
        }

    def _ask_picoclaw(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        prompt = build_picoclaw_maintenance_prompt(snapshot)
        response = ask_picoclaw_maintenance_decision(
            prompt,
            timeout_seconds=_env_int("AEGIS_PICOCLAW_ENV_DECISION_TIMEOUT_SECONDS", 35, minimum=10, maximum=120),
        )
        text = str(response.get("response") or response.get("content") or response.get("error") or "")
        decision = parse_picoclaw_action(text)
        decision["ok"] = bool(response.get("ok"))
        decision["model"] = str(response.get("model") or "")
        decision["raw"] = text[:500]
        if decision["action"] not in {"OBSERVE", "WARN_ONLY", "RECYCLE_OLLAMA"}:
            decision["reason"] = f"Blocked unsupported action {decision['action']}: {decision.get('reason', '')}"
            decision["action"] = "OBSERVE"
        return decision

    def _contract_action(self, snapshot: Dict[str, Any]) -> Dict[str, str]:
        alerts = snapshot.get("alerts") or []
        if any(item.get("type") == "ollama_high_ram" for item in alerts):
            return {
                "action": "RECYCLE_OLLAMA",
                "reason": "Strict contract: high-RAM Ollama runner is above limit.",
            }
        if any(item.get("type") == "ram_pressure" for item in alerts):
            return {
                "action": "WARN_ONLY",
                "reason": "Strict contract: total RAM pressure needs operator-visible warning.",
            }
        return {"action": "OBSERVE", "reason": "No contract violation."}

    def _execute_recycle_ollama(self, snapshot: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
        has_ollama_alert = any(item.get("type") == "ollama_high_ram" for item in snapshot.get("alerts", []))
        if not has_ollama_alert:
            return {"ok": False, "blocked": True, "reason": "No ollama_high_ram alert present."}
        handler = self._action_handlers.get("recycle_ollama")
        if not handler:
            return {"ok": False, "blocked": True, "reason": "No recycle_ollama handler registered."}
        try:
            result = handler(min_ram_mb=self.max_ollama_runner_mb)
            return {"ok": bool(result.get("terminated")), "handler_result": result, "decision": decision}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "decision": decision}

    def _write_state(self, snapshot: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                f"[{snapshot.get('timestamp')}] status={snapshot.get('status')} "
                f"alerts={len(snapshot.get('alerts') or [])} "
                f"env_drift={len(snapshot.get('env_drift') or [])} "
                f"decision={(snapshot.get('picoclaw_decision') or {}).get('action', 'PENDING')}\n"
            )


picoclaw_environment_sidecar = PicoClawEnvironmentSidecar()
