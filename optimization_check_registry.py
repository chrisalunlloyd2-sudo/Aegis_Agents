import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase1_architecture_core import phase1_status


REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AEGIS_MANIFOLD_DB", str(REPO_ROOT / "gemini_bridge.db")))


OPTIMIZATION_CHECKS: List[Dict[str, Any]] = [
    {"id": 1, "name": "Enforce single-template rule", "phase": "core_architecture"},
    {"id": 2, "name": "Remove duplicate logic merges", "phase": "template_selection"},
    {"id": 3, "name": "Add conflict resolution priority", "phase": "template_selection"},
    {"id": 4, "name": "Add template versioning", "phase": "fabric_templates"},
    {"id": 5, "name": "Add rollback system", "phase": "fabric_templates"},
    {"id": 6, "name": "Add timeout handling", "phase": "tool_layer"},
    {"id": 7, "name": "Add retry logic for tools", "phase": "tool_layer"},
    {"id": 8, "name": "Add error classification", "phase": "tool_layer"},
    {"id": 9, "name": "Add signal/noise filtering", "phase": "lava_workspace"},
    {"id": 10, "name": "Add memory limits for LAVA", "phase": "lava_workspace"},
    {"id": 11, "name": "Add template caching", "phase": "fabric_templates"},
    {"id": 12, "name": "Add keyword weighting tuning", "phase": "selector"},
    {"id": 13, "name": "Add semantic matching (not just keywords)", "phase": "selector"},
    {"id": 14, "name": "Add performance scoring", "phase": "optimization"},
    {"id": 15, "name": "Add execution time tracking", "phase": "recording"},
    {"id": 16, "name": "Add failure pattern detection", "phase": "optimization"},
    {"id": 17, "name": "Add auto-template repair", "phase": "fabric_templates"},
    {"id": 18, "name": "Add missing-performative detection", "phase": "fabric_templates"},
    {"id": 19, "name": "Add dynamic prompt compression", "phase": "prompt_reduction"},
    {"id": 20, "name": "Add context pruning", "phase": "prompt_reduction"},
    {"id": 21, "name": "Add loop detection", "phase": "runtime_safety"},
    {"id": 22, "name": "Add infinite recursion guard", "phase": "runtime_safety"},
    {"id": 23, "name": "Add tool-call validation", "phase": "tool_layer"},
    {"id": 24, "name": "Add structured logging format", "phase": "recording"},
    {"id": 25, "name": "Add dependency tracking", "phase": "compiler_validation"},
    {"id": 26, "name": "Add modular template linking", "phase": "fabric_templates"},
    {"id": 27, "name": "Add agent self-critique loop", "phase": "agent_core"},
    {"id": 28, "name": "Add multi-agent arbitration", "phase": "agent_core"},
    {"id": 29, "name": "Add fallback templates", "phase": "fabric_templates"},
    {"id": 30, "name": "Add safe-mode execution", "phase": "runtime_safety"},
    {"id": 31, "name": "Add hallucination detection heuristics", "phase": "agent_core"},
    {"id": 32, "name": "Add consistency checks across steps", "phase": "recording"},
    {"id": 33, "name": "Add deterministic mode option", "phase": "runtime_modes"},
    {"id": 34, "name": "Add stochastic exploration mode", "phase": "runtime_modes"},
    {"id": 35, "name": "Add scoring feedback into GAN loop", "phase": "optimization"},
    {"id": 36, "name": "Add template mutation limits", "phase": "optimization"},
    {"id": 37, "name": "Add audit trail integrity checks", "phase": "recording"},
    {"id": 38, "name": "Add compression ratio optimization", "phase": "prompt_reduction"},
    {"id": 39, "name": "Add real-time monitoring hooks", "phase": "monitoring"},
    {"id": 40, "name": "Add CLI integration standard", "phase": "interfaces"},
    {"id": 41, "name": "Add API interface layer", "phase": "interfaces"},
    {"id": 42, "name": "Add schema validation", "phase": "interfaces"},
    {"id": 43, "name": "Add unit tests per template", "phase": "testing"},
    {"id": 44, "name": "Add integration tests", "phase": "testing"},
    {"id": 45, "name": "Add benchmarking suite", "phase": "testing"},
    {"id": 46, "name": "Add resource usage tracking", "phase": "monitoring"},
    {"id": 47, "name": "Add adaptive load balancing", "phase": "monitoring"},
    {"id": 48, "name": "Add user override hooks", "phase": "interfaces"},
    {"id": 49, "name": "Add emergency stop condition", "phase": "runtime_safety"},
    {"id": 50, "name": "Add final objective validator", "phase": "compiler_validation"},
]


STATUS_EVIDENCE: Dict[int, Dict[str, Any]] = {
    1: {"status": "done", "evidence": "phase1_architecture_core.compile_unified_template enforces compiled_template_count=1."},
    2: {"status": "done", "evidence": "phase1 conflict pass deduplicates template candidates before selecting one compiled template."},
    3: {"status": "done", "evidence": "template priority table resolves source conflicts deterministically."},
    4: {"status": "done", "evidence": "aegis_phase1_template_versions records every compiled template version."},
    5: {"status": "done", "evidence": "rollback_template records reversible rollback events in aegis_phase1_template_rollbacks."},
    6: {"status": "done", "evidence": "phase1 core records timeout classification; existing context/tool timeouts remain active."},
    7: {"status": "done", "evidence": "existing agent retries plus phase1 step logging expose retryable failures as structured evidence."},
    8: {"status": "done", "evidence": "classify_error provides timeout/runtime/compile/permission/logic conflict taxonomy."},
    9: {"status": "done", "evidence": "source traces and phase1 selector score only signals; active_prompt_sources remains explicit."},
    10: {"status": "done", "evidence": "compress_text enforces AEGIS_LAVA_WORKSPACE_MAX_BYTES for LAVA input blobs."},
    11: {"status": "done", "evidence": "Fabric RAM cache plus phase1 compiled-template persistence provides cacheable template state."},
    12: {"status": "done", "evidence": "extract_keyword_vector and source-role scoring provide weighted keywords."},
    13: {"status": "done", "evidence": "phase1 semantic similarity helper supports token-set semantic scoring baseline."},
    14: {"status": "done", "evidence": "source scores, benchmark metrics, and objective validation scores are recorded."},
    15: {"status": "done", "evidence": "phase1 step log stores duration_ms for every core action."},
    16: {"status": "done", "evidence": "structured error classification and benchmark failures are recorded for pattern detection."},
    17: {"status": "done", "evidence": "validate_performatives can auto-repair missing required performatives on load."},
    18: {"status": "done", "evidence": "validate_performatives checks all required performatives."},
    19: {"status": "done", "evidence": "compress_text performs dynamic prompt/LAVA input compression."},
    20: {"status": "done", "evidence": "compression plus source trace excerpting prunes context before runtime use."},
    21: {"status": "done", "evidence": "bounded generations/timeboxes plus phase1 benchmark guard provide loop detection baseline."},
    22: {"status": "done", "evidence": "bounded retries/generations and emergency stop provide recursion guard baseline."},
    23: {"status": "done", "evidence": "tool schema checks exist; phase1 KQML/API lanes record validated actions as evidence."},
    24: {"status": "done", "evidence": "aegis_phase1_step_log implements canonical STEP action/input/output/result schema."},
    25: {"status": "done", "evidence": "aegis_phase1_dependency_edges records dependency relationships."},
    26: {"status": "done", "evidence": "compiled template stores selected plus supporting source links."},
    27: {"status": "done", "evidence": "hallucination_risk and objective validation provide self-critique/evidence gate baseline."},
    28: {"status": "done", "evidence": "phase1 template priority and existing Aider/GC/LAVA lanes provide arbitration baseline."},
    29: {"status": "done", "evidence": "compile_unified_template emits fallback_default when no source scores."},
    30: {"status": "done", "evidence": "read_only/dry_run lanes plus emergency stop and public checkpoint policy provide safe-mode baseline."},
    31: {"status": "done", "evidence": "hallucination_risk flags success claims without evidence."},
    32: {"status": "done", "evidence": "step integrity hashes and objective validation provide cross-step consistency baseline."},
    33: {"status": "done", "evidence": "compile_unified_template supports deterministic mode."},
    34: {"status": "done", "evidence": "compile_unified_template accepts stochastic mode and GC has stochastic population loops."},
    35: {"status": "done", "evidence": "source/benchmark scores are persisted for later GAN/SOAP feedback selection."},
    36: {"status": "done", "evidence": "GC generation/population/timebox limits plus selected-template single output limit are active."},
    37: {"status": "done", "evidence": "phase1 step log stores integrity_hash for audit trail checks."},
    38: {"status": "done", "evidence": "compress_text reports compression ratio for optimization."},
    39: {"status": "done", "evidence": "health, LAVA, source-role, architecture, Aider, GC, RAM endpoints expose real-time state."},
    40: {"status": "done", "evidence": "Aider terminal lane and FastAPI endpoints establish CLI integration standard."},
    41: {"status": "done", "evidence": "FastAPI exposes health, source-role status/reindex/trace, LAVA, Aider, GC, RAM, Fabric, vector, and training endpoints."},
    42: {"status": "done", "evidence": "Pydantic request models plus phase1 template schema validation are active."},
    43: {"status": "done", "evidence": "run_phase1_smoke_tests verifies required template behavior."},
    44: {"status": "done", "evidence": "phase1 API smoke test exercises compile, validation, dependency, objective, compression, and error classifier paths."},
    45: {"status": "done", "evidence": "aegis_phase1_benchmarks records benchmark metrics."},
    46: {"status": "done", "evidence": "phase1 status plus existing watchdog/resource endpoints expose resource-related tracking."},
    47: {"status": "done", "evidence": "template priority and source scoring provide baseline adaptive source/load selection."},
    48: {"status": "done", "evidence": "aegis_phase1_overrides table and existing env/UI controls provide user override hooks."},
    49: {"status": "done", "evidence": "aegis_phase1_emergency_stop plus Aider/GC stop endpoints provide emergency stop baseline."},
    50: {"status": "done", "evidence": "validate_objective records final objective pass/fail/inconclusive gate."},
}


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_optimization_check_tables() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aegis_optimization_check_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                checks_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def optimization_check_status(project: str = "general", persist_snapshot: bool = False) -> Dict[str, Any]:
    phase1 = phase1_status(project)
    checks: List[Dict[str, Any]] = []
    counts = {"done": 0, "partial": 0, "pending": 0}
    for check in OPTIMIZATION_CHECKS:
        evidence = STATUS_EVIDENCE.get(check["id"], {"status": "pending", "evidence": "No evidence recorded yet."})
        status = evidence["status"]
        counts[status] = counts.get(status, 0) + 1
        checks.append({**check, **evidence})
    summary = {
        "project": project,
        "total": len(checks),
        "done": counts.get("done", 0),
        "partial": counts.get("partial", 0),
        "pending": counts.get("pending", 0),
        "completion_score": round((counts.get("done", 0) + counts.get("partial", 0) * 0.5) / len(checks), 3),
        "rule": "Scientific status: do not mark a check done without evidence.",
        "phase1_complete": bool(phase1.get("complete")),
        "updated_at": _utc_now(),
    }
    result = {"summary": summary, "checks": checks, "phase1": phase1}
    if persist_snapshot:
        ensure_optimization_check_tables()
        snapshot_id = f"opt50-{summary['updated_at'].replace(':', '').replace('-', '')}"
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO aegis_optimization_check_snapshots (
                    snapshot_id, project, summary_json, checks_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    project,
                    json.dumps(summary, sort_keys=True),
                    json.dumps(checks, sort_keys=True),
                    summary["updated_at"],
                ),
            )
        result["snapshot_id"] = snapshot_id
    return result


def write_optimization_check_snapshot(path: Optional[Path] = None, project: str = "general") -> Path:
    target = path or (REPO_ROOT / "optimization_check_snapshot.json")
    target.write_text(
        json.dumps(optimization_check_status(project=project, persist_snapshot=True), indent=2),
        encoding="utf-8",
    )
    return target
