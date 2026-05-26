"""Lava-ready event substrate for AEGIS.

This module is intentionally not a Loihi dependency yet. It records the same
event-shaped traffic that can later be mapped to Intel Lava Processes while
keeping today's workstation fast and testable: KQML envelopes, GC/SOAP events,
and Fabric wisdom reinforcement for verified outcomes.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fabric_wisdom_store import record_fabric_wisdom
from kqml_protocol import make_kqml_message, new_conversation_id, render_kqml


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "gemini_bridge.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _bounded_text(value: Any, limit: int = 1800) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[trimmed]"


class LavaEventOrchestrator:
    """DB-backed event lane that can later be backed by real Lava processes."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with _conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS lava_event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    project TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    kqml_json TEXT NOT NULL,
                    kqml_wire TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS lava_orchestration_state (
                    project TEXT PRIMARY KEY,
                    last_event_id TEXT,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    timeout_count INTEGER NOT NULL DEFAULT 0,
                    current_phase TEXT NOT NULL DEFAULT 'idle',
                    soap_state_json TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            c.commit()

    def runtime_status(self, project: str = "general") -> Dict[str, Any]:
        clean_project = project or "general"
        with _conn() as c:
            row = c.execute(
                """
                SELECT *
                FROM lava_orchestration_state
                WHERE project=?
                """,
                (clean_project,),
            ).fetchone()
            recent = c.execute(
                """
                SELECT event_type, status, source, target, score, created_at
                FROM lava_event_log
                WHERE project=?
                ORDER BY id DESC
                LIMIT 8
                """,
                (clean_project,),
            ).fetchall()
        return {
            "project": clean_project,
            "event_recorder_enabled": True,
            "intel_lava_enabled": os.getenv("AEGIS_INTEL_LAVA_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
            "backend": os.getenv("AEGIS_INTEL_LAVA_BACKEND", "cpu-simulation").strip() or "cpu-simulation",
            "workspace": os.getenv(
                "AEGIS_INTEL_LAVA_WORKSPACE",
                str(ROOT / "agentic_jobs" / "lava_neuromorphic"),
            ),
            "state": dict(row) if row else {
                "project": clean_project,
                "event_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "timeout_count": 0,
                "current_phase": "idle",
            },
            "recent_events": [dict(item) for item in recent],
            "note": "Local event control plane is active; Intel Lava package/Loihi hardware remain disabled until explicitly installed.",
        }

    def recent_events(self, project: str = "general", limit: int = 30) -> Dict[str, Any]:
        clean_project = project or "general"
        safe_limit = max(1, min(int(limit or 30), 200))
        with _conn() as c:
            rows = c.execute(
                """
                SELECT event_id, project, event_type, source, target, status, score,
                       kqml_json, kqml_wire, content_json, created_at
                FROM lava_event_log
                WHERE project=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (clean_project, safe_limit),
            ).fetchall()
        events: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["kqml"] = _load_json(str(item.pop("kqml_json", "")), {})
            item["content"] = _load_json(str(item.pop("content_json", "")), {})
            events.append(item)
        return {
            "project": clean_project,
            "events": events,
            "status": self.runtime_status(clean_project),
        }

    def record_event(
        self,
        *,
        project: str = "general",
        event_type: str,
        source: str,
        target: str,
        content: Dict[str, Any],
        performative: str = "tell",
        status: str = "observed",
        score: float = 0.0,
        soap_state: Optional[Dict[str, Any]] = None,
        fabric_domain: Optional[str] = None,
        reinforce_fabric: bool = False,
    ) -> Dict[str, Any]:
        clean_project = project or "general"
        clean_event_type = (event_type or "event").strip() or "event"
        event_id = f"lava-{uuid.uuid4().hex[:12]}"
        kqml = make_kqml_message(
            performative,
            sender=source or "aegis",
            receiver=target or "aegis-lava-event-plane",
            content={
                "event_id": event_id,
                "project": clean_project,
                "event_type": clean_event_type,
                "status": status,
                "score": float(score or 0.0),
                "payload": content or {},
            },
            language="json",
            ontology="aegis.lava.event-plane",
            conversation_id=new_conversation_id("lava"),
            reply_with=f"{clean_event_type}-{uuid.uuid4().hex[:8]}",
        )
        kqml_wire = render_kqml(kqml)
        created_at = _now()
        self._write_event(
            event_id=event_id,
            project=clean_project,
            event_type=clean_event_type,
            source=source or "aegis",
            target=target or "aegis-lava-event-plane",
            status=status,
            score=float(score or 0.0),
            kqml=kqml,
            kqml_wire=kqml_wire,
            content=content or {},
            soap_state=soap_state,
            created_at=created_at,
        )
        fabric_result: Dict[str, Any] = {"ok": False, "reason": "not_reinforced"}
        if reinforce_fabric and float(score or 0.0) > 0:
            fabric_text = self._fabric_text(clean_event_type, content or {})
            fabric_result = record_fabric_wisdom(
                project=clean_project,
                domain=fabric_domain or f"lava_{clean_event_type}",
                prompt_text=fabric_text,
                score=min(1.0, max(0.0, float(score or 0.0))),
                positive_reinforcement=True,
            )
        return {
            "ok": True,
            "event_id": event_id,
            "project": clean_project,
            "event_type": clean_event_type,
            "status": status,
            "score": float(score or 0.0),
            "kqml": kqml,
            "kqml_wire": kqml_wire,
            "fabric": fabric_result,
        }

    def _write_event(
        self,
        *,
        event_id: str,
        project: str,
        event_type: str,
        source: str,
        target: str,
        status: str,
        score: float,
        kqml: Dict[str, Any],
        kqml_wire: str,
        content: Dict[str, Any],
        soap_state: Optional[Dict[str, Any]],
        created_at: str,
    ) -> None:
        success = int(status in {"success", "passed", "completed"} or score >= 0.75)
        failure = int(status in {"failed", "error"} or score < 0)
        timeout = int("timeout" in event_type.lower() or status == "timeout")
        phase = self._phase_from_event(event_type, status)
        with _conn() as c:
            c.execute(
                """
                INSERT INTO lava_event_log
                (event_id, project, event_type, source, target, status, score,
                 kqml_json, kqml_wire, content_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    project,
                    event_type,
                    source,
                    target,
                    status,
                    float(score),
                    _json(kqml),
                    kqml_wire,
                    _json(content),
                    created_at,
                ),
            )
            c.execute(
                """
                INSERT INTO lava_orchestration_state
                (project, last_event_id, event_count, success_count, failure_count,
                 timeout_count, current_phase, soap_state_json, updated_at)
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project) DO UPDATE SET
                    last_event_id=excluded.last_event_id,
                    event_count=event_count + 1,
                    success_count=success_count + excluded.success_count,
                    failure_count=failure_count + excluded.failure_count,
                    timeout_count=timeout_count + excluded.timeout_count,
                    current_phase=excluded.current_phase,
                    soap_state_json=COALESCE(excluded.soap_state_json, soap_state_json),
                    updated_at=excluded.updated_at
                """,
                (
                    project,
                    event_id,
                    success,
                    failure,
                    timeout,
                    phase,
                    _json(soap_state) if soap_state else None,
                    created_at,
                ),
            )
            c.commit()

    def _phase_from_event(self, event_type: str, status: str) -> str:
        name = (event_type or "").lower()
        if "compile_fail" in name or status == "failed":
            return "repair"
        if "compile_pass" in name or "runtime_pass" in name:
            return "verify"
        if "soap" in name:
            return "optimize"
        if "gc" in name or "candidate" in name:
            return "evolve"
        if "timeout" in name:
            return "recover"
        return "observe"

    def _fabric_text(self, event_type: str, content: Dict[str, Any]) -> str:
        objective = _bounded_text(content.get("objective") or content.get("ask") or "", 500)
        candidate = _bounded_text(content.get("candidate_id") or content.get("candidate") or "", 160)
        heuristics = content.get("heuristics") or []
        debugger = content.get("debugger") or {}
        repair_hints = debugger.get("repair_hints") if isinstance(debugger, dict) else []
        parts = [
            f"Event {event_type} produced verified project wisdom.",
            f"Objective: {objective}" if objective else "",
            f"Candidate: {candidate}" if candidate else "",
            f"Heuristics: {', '.join(map(str, heuristics[:8]))}" if isinstance(heuristics, list) and heuristics else "",
            f"Repair hints: {', '.join(map(str, repair_hints[:6]))}" if isinstance(repair_hints, list) and repair_hints else "",
        ]
        return "\n".join(part for part in parts if part).strip()

    def record_genetic_candidate(
        self,
        *,
        project: str,
        job_id: str,
        objective: str,
        candidate: Any,
        soap_state: Optional[Dict[str, Any]] = None,
        reward: Optional[float] = None,
    ) -> Dict[str, Any]:
        evidence = getattr(candidate, "evidence", {}) or {}
        compile_pass = bool(getattr(candidate, "compile_pass", False))
        tests_pass = bool(getattr(candidate, "tests_pass", False))
        fitness = float(getattr(candidate, "fitness", 0.0) or 0.0)
        event_type = "gc_runtime_pass" if tests_pass else ("gc_compile_pass" if compile_pass else "gc_compile_fail")
        status = "passed" if tests_pass else ("observed" if compile_pass else "failed")
        content = {
            "job_id": job_id,
            "objective": objective,
            "candidate_id": getattr(candidate, "candidate_id", ""),
            "generation": getattr(candidate, "generation", 0),
            "fitness": fitness,
            "reward": reward,
            "compile_pass": compile_pass,
            "tests_pass": tests_pass,
            "heuristics": getattr(candidate, "heuristics", []),
            "debugger": evidence.get("debugger") if isinstance(evidence, dict) else {},
            "likelihood": evidence.get("likelihood") if isinstance(evidence, dict) else {},
        }
        return self.record_event(
            project=project,
            event_type=event_type,
            source="aegis-genetic-coder",
            target="aegis-lava-event-plane",
            content=content,
            performative="tell",
            status=status,
            score=fitness if tests_pass else (-0.1 if not compile_pass else min(fitness, 0.6)),
            soap_state=soap_state,
            fabric_domain="genetic_coder_success",
            reinforce_fabric=tests_pass,
        )


lava_event_orchestrator = LavaEventOrchestrator()
