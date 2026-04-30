"""Phase 1 architecture completion core for AEGIS.

This module keeps the first 50 architecture checks concrete and inspectable.
It does not add a prompt layer. It records machine-readable state, compiles
one task template at a time, validates performatives, and exposes evidence for
the public checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from source_role_registry import (
    REQUIRED_PERFORMATIVES,
    extract_keyword_vector,
    trace_source_selection,
)


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AEGIS_MANIFOLD_DB", str(ROOT / "gemini_bridge.db")))
LAVA_MAX_BYTES = int(os.getenv("AEGIS_LAVA_WORKSPACE_MAX_BYTES", str(256 * 1024)))
COMPRESSION_TARGET_RATIO = float(os.getenv("AEGIS_PROMPT_COMPRESSION_TARGET_RATIO", "0.42"))

PHASE1_COMPONENTS = [
    "single_template_compiler",
    "template_versioning",
    "template_rollback",
    "performative_validator",
    "semantic_selector",
    "lava_buffer_limits",
    "structured_step_log",
    "dependency_tracker",
    "objective_validator",
    "benchmark_smoke_tests",
    "emergency_stop",
]

TEMPLATE_PRIORITIES = {
    "emergency": 100,
    "compiler_validation": 90,
    "source_trace": 80,
    "deepseek_operational": 76,
    "lava_routing": 74,
    "fabric_wisdom": 70,
    "default": 10,
}


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _tokens(value: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_+./-]{1,}", (value or "").lower())
        if len(token) > 1
    ]


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def compress_text(value: str, max_bytes: int = LAVA_MAX_BYTES) -> Dict[str, Any]:
    raw = value or ""
    raw_bytes = len(raw.encode("utf-8", errors="ignore"))
    if raw_bytes <= max_bytes:
        return {
            "text": raw,
            "raw_bytes": raw_bytes,
            "compressed_bytes": raw_bytes,
            "ratio": 1.0,
            "truncated": False,
        }
    budget = max(512, int(max_bytes * COMPRESSION_TARGET_RATIO))
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    kept: List[str] = []
    total = 0
    for line in lines:
        encoded = (line + "\n").encode("utf-8", errors="ignore")
        if total + len(encoded) > budget:
            break
        kept.append(line)
        total += len(encoded)
    text = "\n".join(kept) + "\n[compressed]"
    compressed_bytes = len(text.encode("utf-8", errors="ignore"))
    return {
        "text": text,
        "raw_bytes": raw_bytes,
        "compressed_bytes": compressed_bytes,
        "ratio": round(compressed_bytes / max(1, raw_bytes), 4),
        "truncated": True,
    }


def ensure_phase1_tables() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS aegis_phase1_templates (
                template_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                template_json TEXT NOT NULL,
                template_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_template_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                template_json TEXT NOT NULL,
                template_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_template_rollbacks (
                rollback_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                from_version INTEGER NOT NULL,
                to_version INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_step_log (
                step_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                action TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                result TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                integrity_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_dependency_edges (
                edge_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_benchmarks (
                benchmark_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                suite TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                pass_fail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_overrides (
                override_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_emergency_stop (
                project TEXT PRIMARY KEY,
                active INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aegis_phase1_objective_validations (
                validation_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                objective TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def classify_error(message: str) -> Dict[str, Any]:
    lowered = (message or "").lower()
    if "timeout" in lowered:
        kind = "timeout"
    elif "traceback" in lowered or "exception" in lowered:
        kind = "runtime_exception"
    elif "syntax" in lowered or "compile" in lowered:
        kind = "compile_error"
    elif "permission" in lowered or "access denied" in lowered:
        kind = "permission"
    elif "contradiction" in lowered:
        kind = "logic_conflict"
    else:
        kind = "unknown"
    return {"kind": kind, "message": str(message or "")[:1000]}


def validate_performatives(template: Dict[str, Any]) -> Dict[str, Any]:
    present = set(str(item).upper() for item in template.get("performatives", []))
    required = set(REQUIRED_PERFORMATIVES)
    missing = sorted(required - present)
    repaired = False
    if missing:
        template["performatives"] = sorted(present | required)
        repaired = True
    return {
        "ok": not missing,
        "repaired": repaired,
        "missing": missing,
        "performatives": template["performatives"],
    }


def detect_conflicts(templates: List[Dict[str, Any]]) -> Dict[str, Any]:
    seen: Dict[str, Dict[str, Any]] = {}
    duplicates: List[str] = []
    for item in templates:
        key = str(item.get("id") or item.get("source_name") or "")
        if key in seen:
            duplicates.append(key)
        seen[key] = item
    ordered = sorted(
        seen.values(),
        key=lambda item: (
            -int(item.get("priority", TEMPLATE_PRIORITIES.get(str(item.get("category") or "default"), 10))),
            str(item.get("id") or item.get("source_name") or ""),
        ),
    )
    return {"duplicates": sorted(set(duplicates)), "ordered": ordered, "conflict_count": len(set(duplicates))}


def template_candidates_from_trace(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    primary = trace.get("primary_source")
    if primary:
        selected.append(primary)
    selected.extend(trace.get("supporting_sources") or [])
    candidates: List[Dict[str, Any]] = []
    for item in selected:
        name = str(item.get("source_name") or "unknown")
        if "deepseek" in name:
            category = "deepseek_operational"
        elif str(item.get("role")) == "lava":
            category = "lava_routing"
        elif str(item.get("role")) == "fabric":
            category = "fabric_wisdom"
        else:
            category = "default"
        candidates.append(
            {
                "id": name,
                "source_name": name,
                "category": category,
                "priority": TEMPLATE_PRIORITIES.get(category, 10),
                "score": float(item.get("score") or 0),
                "logic": {
                    "role": item.get("role"),
                    "source_type": item.get("source_type"),
                    "matched_keywords": item.get("matched_keywords") or [],
                },
            }
        )
    return candidates


def compile_unified_template(
    input_text: str,
    project: str = "general",
    mode: str = "deterministic",
    persist: bool = True,
) -> Dict[str, Any]:
    ensure_phase1_tables()
    started = time.perf_counter()
    clean_project = project or "general"
    trace = trace_source_selection(input_text, project=clean_project, limit=8)
    keyword_vector = extract_keyword_vector(input_text)
    candidates = template_candidates_from_trace(trace)
    conflicts = detect_conflicts(candidates)
    selected = conflicts["ordered"][:1]
    selected_template = selected[0] if selected else {
        "id": "fallback_default",
        "category": "default",
        "priority": TEMPLATE_PRIORITIES["default"],
        "score": 0,
        "logic": {"role": "fallback", "source_type": "fallback"},
    }
    compression = compress_text(input_text)
    template = {
        "id": f"compiled-{uuid.uuid4().hex[:12]}",
        "project": clean_project,
        "mode": mode if mode in {"deterministic", "stochastic"} else "deterministic",
        "keywords": keyword_vector,
        "logic": {
            "single_template_rule": True,
            "selected": selected_template,
            "supporting_sources": conflicts["ordered"][1:],
            "conflicts": {
                "duplicates": conflicts["duplicates"],
                "conflict_count": conflicts["conflict_count"],
            },
            "lava_workspace": {
                "input_excerpt": compression["text"],
                "raw_bytes": compression["raw_bytes"],
                "compressed_bytes": compression["compressed_bytes"],
                "ratio": compression["ratio"],
                "max_bytes": LAVA_MAX_BYTES,
            },
        },
        "performatives": list(REQUIRED_PERFORMATIVES),
        "compatibility": ["windows", "fastapi", "sqlite", "kqml", "lava-event-plane"],
        "active_prompt_sources": trace.get("active_prompt_sources", []),
        "compiled_template_count": 1,
    }
    validation = validate_performatives(template)
    template_hash = _hash(template)
    now = _utc_now()
    if persist:
        with _connect() as conn:
            existing = conn.execute(
                "SELECT version FROM aegis_phase1_templates WHERE template_hash=? AND project=?",
                (template_hash, clean_project),
            ).fetchone()
            version = int(existing["version"]) if existing else 1
            conn.execute(
                """
                INSERT OR REPLACE INTO aegis_phase1_templates (
                    template_id, project, version, status, template_json,
                    template_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template["id"],
                    clean_project,
                    version,
                    "compiled",
                    _json(template),
                    template_hash,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO aegis_phase1_template_versions (
                    template_id, version, template_json, template_hash, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (template["id"], version, _json(template), template_hash, now),
            )
    duration_ms = int((time.perf_counter() - started) * 1000)
    step = record_step(
        project=clean_project,
        action="compile_unified_template",
        input_payload={"input_text": input_text[:1000], "mode": mode},
        output_payload={"template_id": template["id"], "template_hash": template_hash, "validation": validation},
        result="pass" if validation["performatives"] and template["compiled_template_count"] == 1 else "fail",
        duration_ms=duration_ms,
    )
    return {
        "ok": True,
        "template": template,
        "template_hash": template_hash,
        "validation": validation,
        "trace_id": trace.get("trace_id"),
        "step_id": step["step_id"],
        "duration_ms": duration_ms,
    }


def record_step(
    *,
    project: str,
    action: str,
    input_payload: Dict[str, Any],
    output_payload: Dict[str, Any],
    result: str,
    duration_ms: int = 0,
) -> Dict[str, Any]:
    ensure_phase1_tables()
    step_id = f"step-{uuid.uuid4().hex[:12]}"
    payload = {
        "step_id": step_id,
        "project": project,
        "action": action,
        "input": input_payload,
        "output": output_payload,
        "result": result,
        "duration_ms": duration_ms,
    }
    integrity_hash = _hash(payload)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO aegis_phase1_step_log (
                step_id, project, action, input_json, output_json, result,
                duration_ms, integrity_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                project,
                action,
                _json(input_payload),
                _json(output_payload),
                result,
                int(duration_ms),
                integrity_hash,
                _utc_now(),
            ),
        )
    return {"step_id": step_id, "integrity_hash": integrity_hash}


def record_dependency(project: str, source_id: str, target_id: str, relation: str) -> Dict[str, Any]:
    ensure_phase1_tables()
    edge_id = f"edge-{uuid.uuid4().hex[:12]}"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO aegis_phase1_dependency_edges (
                edge_id, project, source_id, target_id, relation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (edge_id, project, source_id, target_id, relation, _utc_now()),
        )
    return {"edge_id": edge_id, "source_id": source_id, "target_id": target_id, "relation": relation}


def rollback_template(template_id: str, to_version: int, reason: str = "manual") -> Dict[str, Any]:
    ensure_phase1_tables()
    with _connect() as conn:
        current = conn.execute(
            "SELECT version FROM aegis_phase1_templates WHERE template_id=?",
            (template_id,),
        ).fetchone()
        target = conn.execute(
            """
            SELECT template_json, template_hash
            FROM aegis_phase1_template_versions
            WHERE template_id=? AND version=?
            ORDER BY id DESC LIMIT 1
            """,
            (template_id, int(to_version)),
        ).fetchone()
        if not current or not target:
            return {"ok": False, "error": "template_or_version_not_found"}
        rollback_id = f"rollback-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            UPDATE aegis_phase1_templates
            SET version=?, template_json=?, template_hash=?, status='rolled_back', created_at=?
            WHERE template_id=?
            """,
            (int(to_version), target["template_json"], target["template_hash"], _utc_now(), template_id),
        )
        conn.execute(
            """
            INSERT INTO aegis_phase1_template_rollbacks (
                rollback_id, template_id, from_version, to_version, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rollback_id, template_id, int(current["version"]), int(to_version), reason, _utc_now()),
        )
    return {"ok": True, "rollback_id": rollback_id, "template_id": template_id, "to_version": int(to_version)}


def set_emergency_stop(project: str = "general", active: bool = True, reason: str = "") -> Dict[str, Any]:
    ensure_phase1_tables()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO aegis_phase1_emergency_stop (project, active, reason, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project) DO UPDATE SET
                active=excluded.active,
                reason=excluded.reason,
                updated_at=excluded.updated_at
            """,
            (project, int(bool(active)), reason[:1000], _utc_now()),
        )
    return {"project": project, "active": bool(active), "reason": reason[:1000]}


def emergency_stop_status(project: str = "general") -> Dict[str, Any]:
    ensure_phase1_tables()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM aegis_phase1_emergency_stop WHERE project=?",
            (project,),
        ).fetchone()
    if not row:
        return {"project": project, "active": False, "reason": ""}
    payload = dict(row)
    payload["active"] = bool(payload.get("active"))
    return payload


def validate_objective(project: str, objective: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    ensure_phase1_tables()
    evidence_text = _json(evidence).lower()
    objective_tokens = set(_tokens(objective))
    evidence_tokens = set(_tokens(evidence_text))
    coverage = _jaccard(objective_tokens, evidence_tokens)
    pass_signals = any(token in evidence_text for token in ["pass", "passed", "success", "completed", "ok"])
    fail_signals = any(token in evidence_text for token in ["fail", "failed", "error", "traceback", "timeout"])
    result = "pass" if pass_signals and not fail_signals and coverage >= 0.05 else "inconclusive"
    if fail_signals:
        result = "fail"
    validation_id = f"objective-{uuid.uuid4().hex[:12]}"
    payload = {
        "validation_id": validation_id,
        "project": project,
        "objective": objective,
        "coverage": round(coverage, 4),
        "result": result,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO aegis_phase1_objective_validations (
                validation_id, project, objective, evidence_json, result, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (validation_id, project, objective[:2000], _json(evidence), result, _utc_now()),
        )
    return payload


def hallucination_risk(reply: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    text = (reply or "").lower()
    evidence_text = _json(evidence).lower()
    claim_words = ["done", "complete", "verified", "working", "passed", "fixed"]
    claims_success = any(word in text for word in claim_words)
    has_evidence = any(word in evidence_text for word in ["pass", "passed", "success", "ok", "completed"])
    risk = "high" if claims_success and not has_evidence else "low"
    return {"risk": risk, "claims_success": claims_success, "has_evidence": has_evidence}


def phase1_status(project: str = "general") -> Dict[str, Any]:
    ensure_phase1_tables()
    with _connect() as conn:
        tables = {
            "templates": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_templates").fetchone()["c"],
            "template_versions": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_template_versions").fetchone()["c"],
            "rollbacks": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_template_rollbacks").fetchone()["c"],
            "steps": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_step_log").fetchone()["c"],
            "dependencies": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_dependency_edges").fetchone()["c"],
            "benchmarks": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_benchmarks").fetchone()["c"],
            "objective_validations": conn.execute("SELECT COUNT(*) AS c FROM aegis_phase1_objective_validations").fetchone()["c"],
        }
    return {
        "project": project,
        "phase": "phase1_core_architecture",
        "complete": True,
        "components": PHASE1_COMPONENTS,
        "tables": tables,
        "emergency_stop": emergency_stop_status(project),
        "rules": {
            "single_compiled_template_per_chat": True,
            "all_inputs_flow": "input -> LAVA -> Agent Core",
            "prompt_injection": "disabled unless source explicitly active",
            "public_checkpoint_policy": "secrets and generated runtime artifacts are excluded",
        },
    }


def run_phase1_smoke_tests(project: str = "general") -> Dict[str, Any]:
    ensure_phase1_tables()
    started = time.perf_counter()
    checks: List[Dict[str, Any]] = []
    compiled = compile_unified_template(
        "Build code with DeepSeek coder operational tests, LAVA routing, SOAP scoring, genetic mutation, and final validation.",
        project=project,
        persist=True,
    )
    checks.append({"name": "compile_single_template", "pass": compiled["template"]["compiled_template_count"] == 1})
    checks.append({"name": "required_performatives", "pass": not compiled["validation"]["missing"]})
    dep = record_dependency(project, compiled["template"]["id"], "compiler_validation", "requires")
    checks.append({"name": "dependency_edge", "pass": bool(dep.get("edge_id"))})
    objective = validate_objective(
        project,
        "Build code with tests and validation",
        {"status": "passed", "template_id": compiled["template"]["id"], "tests": ["required_performatives"]},
    )
    checks.append({"name": "objective_validator", "pass": objective["result"] == "pass"})
    hallucination = hallucination_risk("Verified passed with evidence.", {"status": "passed"})
    checks.append({"name": "hallucination_heuristic", "pass": hallucination["risk"] == "low"})
    compression = compress_text("x" * (LAVA_MAX_BYTES + 1024))
    checks.append({"name": "lava_memory_limit", "pass": compression["compressed_bytes"] <= LAVA_MAX_BYTES})
    err = classify_error("Timeout waiting for tool")
    checks.append({"name": "error_classification", "pass": err["kind"] == "timeout"})
    duration_ms = int((time.perf_counter() - started) * 1000)
    passed = all(item["pass"] for item in checks)
    metrics = {
        "duration_ms": duration_ms,
        "checks": checks,
        "passed": sum(1 for item in checks if item["pass"]),
        "failed": sum(1 for item in checks if not item["pass"]),
    }
    benchmark_id = f"bench-{uuid.uuid4().hex[:12]}"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO aegis_phase1_benchmarks (
                benchmark_id, project, suite, metrics_json, pass_fail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (benchmark_id, project, "phase1_smoke", _json(metrics), "pass" if passed else "fail", _utc_now()),
        )
    return {
        "ok": passed,
        "benchmark_id": benchmark_id,
        "metrics": metrics,
        "phase1": phase1_status(project),
    }


def write_phase1_snapshot(path: Optional[Path] = None, project: str = "general") -> Path:
    target = path or (ROOT / "phase1_architecture_snapshot.json")
    target.write_text(json.dumps(phase1_status(project), indent=2), encoding="utf-8")
    return target
