from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "gemini_bridge.db"
TEMPLATE_ROOT = ROOT / "fabric_templates"
TOOL_WINDOW_RULE = (
    "Do not tool call in the main context window. Route tool calls through a separate "
    "tool window/context packet and return only compressed evidence to the GUI."
)
_TEMPLATE_RAM_CACHE: Dict[str, Any] = {"project": None, "items": [], "bytes": 0, "loaded_at": None}
_TEMPLATE_VRAM_STATE: Dict[str, Any] = {
    "enabled": False,
    "attempted": False,
    "backend": "none",
    "bytes": 0,
    "reason": "not attempted",
}


def _conn() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_fabric_tables() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS fabric_wisdom_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                domain TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                enabled INTEGER NOT NULL DEFAULT 1,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS fabric_wisdom_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                score REAL NOT NULL,
                prompt_len INTEGER NOT NULL DEFAULT 0,
                response_len INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS fabric_json_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                name TEXT NOT NULL,
                template_json TEXT NOT NULL,
                keywords_json TEXT NOT NULL DEFAULT '[]',
                weight REAL NOT NULL DEFAULT 1.0,
                enabled INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'seed',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project, name)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS fabric_vector_citations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                template_name TEXT NOT NULL,
                vector_memory_id TEXT,
                citation_text TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        c.commit()


def _base_template(
    *,
    name: str,
    description: str,
    objective: str,
    keywords: List[str],
    heuristics: Optional[List[str]] = None,
    constraints: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    sop: Optional[List[str]] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "template": {
            "name": name,
            "schema_version": "fabric-json-v1",
            "description": description,
            "objective": objective,
            "keywords": sorted(set(keywords)),
            "heuristics": heuristics or ["minimal_cli", "self_test"],
            "constraints": constraints or {
                "code_quality": "high",
                "performance": "good",
                "maintainability": "high",
                "tool_context": TOOL_WINDOW_RULE,
            },
            "metrics": metrics or {
                "execution_time": "fast",
                "memory_usage": "efficient",
                "test_coverage": "high",
            },
            "sop": sop or [],
            "parameters": parameters or {},
            "tool_context_rule": TOOL_WINDOW_RULE,
            "information_hierarchy": {
                "input": "user ask",
                "workspace": "LAVA scratch context",
                "fabric": "weighted wisdom template",
                "vector_db": "citation/evidence recall",
                "output": "natural GUI reply plus evidence summary",
            },
        }
    }


def default_json_templates() -> List[Dict[str, Any]]:
    genetic_parameters = {
        "population_size": 10,
        "generations": 50,
        "mutation_rate": 0.2,
        "crossover_rate": 0.8,
        "fitness_function": {
            "name": "code_quality_and_performance",
            "description": (
                "Score candidates by passing tests, runtime, memory, simplicity, maintainability, "
                "and evidence completeness."
            ),
        },
    }
    return [
        _base_template(
            name="genetic_coder",
            description="Fabric template for using the Genetic Coder.",
            objective=(
                "Build a robust and efficient code generation process that leverages genetic "
                "algorithms to optimize code quality, performance, and maintainability."
            ),
            keywords=[
                "genetic",
                "coder",
                "compiler",
                "mutation",
                "crossover",
                "fitness",
                "karoo",
                "soap",
                "program",
                "compile",
                "test",
                "debug",
                "self_test",
                "minimal_cli",
            ],
            sop=[
                "Partition ask into AskSet, ConstraintSet, CodeSet, TestSet, EvidenceSet.",
                "Ask Aider or the main model for first/last page outline only.",
                "Generate candidate code blocks from weighted snippets and kernel citations.",
                "Compile or parse each candidate before runtime testing.",
                "Mutate only the failing block; do not rewrite the entire program unless fitness collapses.",
                "Store passing candidates as vector citations and Fabric wisdom.",
                "Stop on objective pass, inconclusive evidence, emergency stop, or timebox.",
            ],
            parameters=genetic_parameters,
        ),
        _base_template(
            name="soap_genetic_flow",
            description="SOAP-style data-flow optimization for the genetic coder.",
            objective="Use stable optimizer heuristics to select, mutate, and distill code candidates.",
            keywords=[
                "soap",
                "optimizer",
                "precondition",
                "shampoo",
                "adaptive",
                "gradient",
                "genetic",
                "fitness",
                "distill",
                "selection",
            ],
            heuristics=["conservative_lr", "fitness_first", "blockwise_mutation", "frequent_eval"],
            sop=[
                "Normalize candidate features: tests, static errors, runtime, memory, complexity.",
                "Apply conservative weighted updates to mutation strategy.",
                "Prefer block-local edits over full rewrites.",
                "Distill successful candidate traits back to Fabric and vector memory.",
            ],
        ),
        _base_template(
            name="webcrawl_data_retrieval",
            description="Advanced webcrawl and retrieval pipeline template.",
            objective="Crawl, parse, cite, distill, and transform external research into code-ready evidence.",
            keywords=[
                "webcrawl",
                "crawl",
                "scrape",
                "retrieval",
                "thesis",
                "paper",
                "parse",
                "citation",
                "vector",
                "fabric",
                "hyperlocal",
                "spoofing",
                "data",
            ],
            sop=[
                "Search official or high-signal sources first.",
                "Crawl pages into chunks with URL, domain, timestamp, and credibility.",
                "Parse into thesis summary, algorithm notes, code patterns, and citations.",
                "Store full evidence in vector DB; store only distilled rules in Fabric.",
                "Reject low-correlation chunks and duplicated SEO text during pruning.",
            ],
            constraints={
                "source_quality": "high",
                "citation_required": True,
                "privacy": "no credentials, no private scraping targets",
                "tool_context": TOOL_WINDOW_RULE,
            },
        ),
        _base_template(
            name="web_ui_context_window",
            description="SOP for responding through the Web UI HTML window.",
            objective="Keep the model aware that it is replying in a GUI stream with display limits.",
            keywords=[
                "webui",
                "web",
                "gui",
                "html",
                "context",
                "window",
                "stream",
                "timeout",
                "reply",
                "display",
            ],
            sop=[
                "Reply naturally for conversation; do not auto-start jobs.",
                "For tools, route work through separate tool context and stream keepalives.",
                "Summarize evidence back to the GUI without raw tool spam.",
                "If a task is long, estimate duration and schedule/report progress.",
            ],
            parameters={"last_prompt_memory": 20, "quick_prompt_always_on": True},
        ),
        _base_template(
            name="logic_axioms",
            description="Axiomatic reasoning and set-theory decomposition template.",
            objective="Convert ambiguous asks into explicit variables, constraints, falsifiable tests, and evidence gates.",
            keywords=[
                "axiom",
                "logic",
                "set",
                "zfc",
                "math",
                "reasoning",
                "scientific",
                "hypothesis",
                "variable",
                "constraint",
            ],
            sop=[
                "Define variables before using them.",
                "Separate AskSet from ConstraintSet and EvidenceSet.",
                "Change one tested variable at a time when optimizing behavior.",
                "Reject claims that contradict evidence or lack a pass/fail test.",
            ],
        ),
        _base_template(
            name="desktop_automation_lava_vision",
            description="LAVA-shaped vision and desktop automation event template.",
            objective="Route visual/desktop events through LAVA-style event packets instead of screenshot-heavy prompt injection.",
            keywords=[
                "lava",
                "vision",
                "desktop",
                "automation",
                "video",
                "encode",
                "decode",
                "quadro",
                "event",
                "tool",
            ],
            sop=[
                "Represent visual observations as event packets and state changes.",
                "Keep raw video/screenshot data out of the main chat context.",
                "Return only compressed action/evidence summaries to the Web UI.",
            ],
            parameters={"vision_mode": "lava_event_packets", "screenshots_in_main_context": False},
        ),
    ]


def _validate_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    template = payload.get("template") if isinstance(payload, dict) else None
    if not isinstance(template, dict):
        raise ValueError("template object is required")
    required = ["name", "description", "objective", "keywords", "heuristics", "constraints", "metrics"]
    missing = [key for key in required if key not in template]
    if missing:
        raise ValueError(f"template missing required keys: {', '.join(missing)}")
    template["name"] = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(template["name"]).strip()).strip("_")
    if not template["name"]:
        raise ValueError("template name is empty")
    keywords = template.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    template["keywords"] = sorted({str(item).strip().lower() for item in keywords if str(item).strip()})
    template["tool_context_rule"] = str(template.get("tool_context_rule") or TOOL_WINDOW_RULE)
    template.setdefault("schema_version", "fabric-json-v1")
    return {"template": template}


def _write_template_file(payload: Dict[str, Any]) -> None:
    TEMPLATE_ROOT.mkdir(parents=True, exist_ok=True)
    name = payload["template"]["name"]
    path = TEMPLATE_ROOT / f"{name}.json"
    if not path.exists():
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def upsert_fabric_template(
    *,
    project: str,
    payload: Dict[str, Any],
    weight: float = 1.0,
    source: str = "seed",
) -> Dict[str, Any]:
    ensure_fabric_tables()
    clean_project = (project or "general").strip() or "general"
    checked = _validate_template(payload)
    template = checked["template"]
    now = datetime.utcnow().isoformat()
    keywords_json = json.dumps(template.get("keywords", []), ensure_ascii=True)
    template_json = json.dumps(checked, ensure_ascii=True, sort_keys=True)
    with _conn() as c:
        row = c.execute(
            "SELECT id, version FROM fabric_json_templates WHERE project=? AND name=?",
            (clean_project, template["name"]),
        ).fetchone()
        if row:
            version = int(row["version"]) + 1
            c.execute(
                """
                UPDATE fabric_json_templates
                SET template_json=?, keywords_json=?, weight=?, enabled=1, source=?, version=?, updated_at=?
                WHERE id=?
                """,
                (template_json, keywords_json, float(weight), source, version, now, int(row["id"])),
            )
            template_id = int(row["id"])
        else:
            cur = c.execute(
                """
                INSERT INTO fabric_json_templates
                (project, name, template_json, keywords_json, weight, enabled, source, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, 1, ?, ?)
                """,
                (clean_project, template["name"], template_json, keywords_json, float(weight), source, now, now),
            )
            template_id = int(cur.lastrowid)
        c.commit()
    _TEMPLATE_RAM_CACHE["project"] = None
    return {"ok": True, "project": clean_project, "template": template["name"], "template_id": template_id}


def seed_default_json_templates(project: str = "general") -> Dict[str, Any]:
    ensure_fabric_tables()
    seeded = []
    for payload in default_json_templates():
        checked = _validate_template(payload)
        _write_template_file(checked)
        result = upsert_fabric_template(project=project, payload=checked, weight=1.25, source="default_json")
        seeded.append(result["template"])
    return {"ok": True, "project": project, "seeded": seeded}


def load_json_templates_from_disk(project: str = "general") -> Dict[str, Any]:
    ensure_fabric_tables()
    TEMPLATE_ROOT.mkdir(parents=True, exist_ok=True)
    loaded = []
    errors = []
    for path in sorted(TEMPLATE_ROOT.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = upsert_fabric_template(project=project, payload=payload, weight=1.2, source=str(path.name))
            loaded.append(result["template"])
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"ok": not errors, "project": project, "loaded": loaded, "errors": errors}


def get_active_fabric_templates(project: str = "general", limit: int = 8, use_ram_cache: bool = True) -> List[Dict[str, Any]]:
    ensure_fabric_tables()
    clean_project = (project or "general").strip() or "general"
    if use_ram_cache and _TEMPLATE_RAM_CACHE.get("project") == clean_project:
        return list(_TEMPLATE_RAM_CACHE.get("items") or [])[: max(1, int(limit))]
    with _conn() as c:
        rows = c.execute(
            """
            SELECT name, template_json, keywords_json, weight, source, version, updated_at
            FROM fabric_json_templates
            WHERE project=? AND enabled=1
            ORDER BY weight DESC, updated_at DESC
            LIMIT ?
            """,
            (clean_project, max(1, int(limit))),
        ).fetchall()
    items = []
    for row in rows:
        try:
            payload = json.loads(row["template_json"])
        except json.JSONDecodeError:
            continue
        item = dict(row)
        item["payload"] = payload
        item.pop("template_json", None)
        try:
            item["keywords"] = json.loads(row["keywords_json"] or "[]")
        except json.JSONDecodeError:
            item["keywords"] = []
        items.append(item)
    cache_bytes = len(json.dumps(items, ensure_ascii=True, default=str).encode("utf-8"))
    _TEMPLATE_RAM_CACHE.update(
        {"project": clean_project, "items": items, "bytes": cache_bytes, "loaded_at": datetime.utcnow().isoformat()}
    )
    return list(items)[: max(1, int(limit))]


def try_pin_fabric_chooser_to_vram(project: str = "general") -> Dict[str, Any]:
    """Best-effort concept test: place Fabric keyword vectors in GPU memory if CuPy is available."""
    _TEMPLATE_VRAM_STATE.update({"attempted": True, "enabled": False, "backend": "none", "bytes": 0})
    try:
        import cupy as cp  # type: ignore
    except Exception as exc:
        _TEMPLATE_VRAM_STATE.update({"reason": f"cupy unavailable: {exc}"})
        return dict(_TEMPLATE_VRAM_STATE)
    templates = get_active_fabric_templates(project=project, limit=64)
    keywords = sorted({kw for item in templates for kw in item.get("keywords", [])})
    if not keywords:
        _TEMPLATE_VRAM_STATE.update({"reason": "no keywords to pin"})
        return dict(_TEMPLATE_VRAM_STATE)
    try:
        # Tiny deterministic keyword feature matrix. This is a chooser proof-of-concept,
        # not an LLM offload path.
        matrix = []
        for item in templates:
            row = [1.0 if kw in set(item.get("keywords", [])) else 0.0 for kw in keywords]
            matrix.append(row)
        gpu_matrix = cp.asarray(matrix, dtype=cp.float32)
        _TEMPLATE_VRAM_STATE.update(
            {
                "enabled": True,
                "backend": "cupy",
                "bytes": int(gpu_matrix.nbytes),
                "template_count": len(templates),
                "keyword_count": len(keywords),
                "reason": "fabric chooser keyword matrix pinned to VRAM",
            }
        )
        return dict(_TEMPLATE_VRAM_STATE)
    except Exception as exc:
        _TEMPLATE_VRAM_STATE.update({"reason": f"vram pin failed: {exc}"})
        return dict(_TEMPLATE_VRAM_STATE)


def fabric_ram_status(project: str = "general") -> Dict[str, Any]:
    templates = get_active_fabric_templates(project=project, limit=64, use_ram_cache=True)
    return {
        "project": project,
        "template_count": len(templates),
        "ram_cache_bytes": int(_TEMPLATE_RAM_CACHE.get("bytes") or 0),
        "ram_cache_loaded_at": _TEMPLATE_RAM_CACHE.get("loaded_at"),
        "vram": dict(_TEMPLATE_VRAM_STATE),
    }


def seed_default_domains(project: str = "general") -> None:
    ensure_fabric_tables()
    now = datetime.utcnow().isoformat()
    domains = {
        "logic_axioms": "Use explicit logic sets: AskSet, ConstraintSet, CodeSet, TestSet, EvidenceSet. Derive from axioms before coding.",
        "c": "When C is requested, prioritize safe memory handling, compile command clarity, and testable single-file prototypes first.",
        "rust": "When Rust is requested, prefer ownership-safe minimal crates, deterministic builds, and unit tests before expansion.",
        "java": "When Java is requested, prefer straightforward class structure, explicit entry points, and JDK-compatible build steps.",
        "statistics": "For statistics tasks, define assumptions, variables, and validation metrics before computations.",
        "stem": "For STEM tasks, show formula grounding, units, edge-case checks, and reproducible verification steps.",
    }
    with _conn() as c:
        for domain, prompt_text in domains.items():
            exists = c.execute(
                "SELECT 1 FROM fabric_wisdom_prompts WHERE project=? AND domain=? AND prompt_text=?",
                (project, domain, prompt_text),
            ).fetchone()
            if exists:
                continue
            c.execute(
                """
                INSERT INTO fabric_wisdom_prompts
                (project, domain, prompt_text, weight, enabled, success_count, failure_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 0, 0, ?, ?)
                """,
                (project, domain, prompt_text, 1.0, now, now),
            )
        c.commit()
    seed_default_json_templates(project)


def get_active_fabric_guidance(project: str = "general", limit: int = 6, prune: bool = True) -> List[Dict[str, Any]]:
    ensure_fabric_tables()
    if prune:
        prune_low_weight_prompts(project=project, threshold=0.35)
    with _conn() as c:
        rows = c.execute(
            """
            SELECT id, project, domain, prompt_text, weight, success_count, failure_count, updated_at
            FROM fabric_wisdom_prompts
            WHERE project=? AND enabled=1
            ORDER BY weight DESC, updated_at DESC
            LIMIT ?
            """,
            (project, max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def build_fabric_guidance_block(project: str = "general", limit: int = 6, prune: bool = True) -> str:
    prompts = get_active_fabric_guidance(project=project, limit=limit, prune=prune)
    templates = get_active_fabric_templates(project=project, limit=limit)
    if not prompts and not templates:
        return ""
    lines = ["FABRIC WISDOM GUIDANCE (DB-weighted JSON):", f"- Tool context rule: {TOOL_WINDOW_RULE}"]
    for item in templates:
        template = (item.get("payload") or {}).get("template", {})
        if not template:
            continue
        lines.append(
            "- JSON_TEMPLATE "
            + json.dumps(
                {
                    "name": template.get("name"),
                    "objective": template.get("objective"),
                    "keywords": template.get("keywords", [])[:16],
                    "heuristics": template.get("heuristics", [])[:8],
                    "constraints": template.get("constraints", {}),
                    "metrics": template.get("metrics", {}),
                    "sop": template.get("sop", [])[:8],
                },
                ensure_ascii=True,
            )
        )
    for item in prompts:
        lines.append(f"- [{item['domain']}] {item['prompt_text']}")
    return "\n".join(lines)


def record_fabric_citation(
    *,
    project: str,
    template_name: str,
    citation_text: str,
    vector_memory_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_fabric_tables()
    clean_project = (project or "general").strip() or "general"
    clean_template = re.sub(r"[^A-Za-z0-9_.:-]+", "_", (template_name or "general").strip()).strip("_") or "general"
    clean_text = (citation_text or "").strip()
    if not clean_text:
        return {"ok": False, "error": "empty citation"}
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO fabric_vector_citations
            (project, template_name, vector_memory_id, citation_text, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clean_project,
                clean_template,
                vector_memory_id,
                clean_text[:6000],
                json.dumps(metadata or {}, ensure_ascii=True, default=str),
                now,
            ),
        )
        c.commit()
    return {
        "ok": True,
        "project": clean_project,
        "template_name": clean_template,
        "citation_id": int(cur.lastrowid),
        "vector_memory_id": vector_memory_id,
    }


def record_fabric_feedback(
    *,
    project: str,
    score: float,
    prompt_text: str,
    response_text: str,
    positive_reinforcement: bool = True,
) -> Dict[str, Any]:
    ensure_fabric_tables()
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO fabric_wisdom_feedback
            (project, score, prompt_len, response_len, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project,
                float(score),
                len(prompt_text or ""),
                len(response_text or ""),
                json.dumps({"project": project}, ensure_ascii=True),
                now,
            ),
        )
        direction = 0.05 if score > 0 else -0.08
        if not positive_reinforcement and score > 0:
            direction = 0.0
        c.execute(
            """
            UPDATE fabric_wisdom_prompts
            SET weight = CASE
                WHEN weight + ? < 0.1 THEN 0.1
                WHEN weight + ? > 3.0 THEN 3.0
                ELSE weight + ?
            END,
            success_count = success_count + CASE WHEN ? > 0 THEN 1 ELSE 0 END,
            failure_count = failure_count + CASE WHEN ? <= 0 THEN 1 ELSE 0 END,
            updated_at = ?
            WHERE project=? AND enabled=1
            """,
            (direction, direction, direction, float(score), float(score), now, project),
        )
        c.commit()
    return {"ok": True, "project": project, "score": float(score)}


def record_fabric_wisdom(
    *,
    project: str,
    domain: str,
    prompt_text: str,
    score: float = 1.0,
    positive_reinforcement: bool = True,
) -> Dict[str, Any]:
    """Upsert one tested lesson into Fabric's weighted wisdom table."""
    ensure_fabric_tables()
    clean_project = (project or "general").strip() or "general"
    clean_domain = re.sub(r"[^A-Za-z0-9_.:-]+", "_", (domain or "project_wisdom").strip()).strip("_")
    clean_domain = clean_domain or "project_wisdom"
    clean_prompt = (prompt_text or "").strip()
    if not clean_prompt:
        return {"ok": False, "project": clean_project, "domain": clean_domain, "error": "empty wisdom text"}

    now = datetime.utcnow().isoformat()
    bounded_score = max(-1.0, min(1.0, float(score or 0.0)))
    delta = 0.08 if bounded_score > 0 else -0.05
    if not positive_reinforcement and bounded_score > 0:
        delta = 0.0

    with _conn() as c:
        row = c.execute(
            """
            SELECT id, weight
            FROM fabric_wisdom_prompts
            WHERE project=? AND domain=? AND prompt_text=?
            """,
            (clean_project, clean_domain, clean_prompt),
        ).fetchone()
        if row:
            c.execute(
                """
                UPDATE fabric_wisdom_prompts
                SET weight = CASE
                    WHEN weight + ? < 0.1 THEN 0.1
                    WHEN weight + ? > 3.0 THEN 3.0
                    ELSE weight + ?
                END,
                enabled=1,
                success_count = success_count + CASE WHEN ? > 0 THEN 1 ELSE 0 END,
                failure_count = failure_count + CASE WHEN ? <= 0 THEN 1 ELSE 0 END,
                updated_at=?
                WHERE id=?
                """,
                (delta, delta, delta, bounded_score, bounded_score, now, int(row["id"])),
            )
            prompt_id = int(row["id"])
        else:
            initial_weight = max(0.1, min(3.0, 1.0 + max(delta, 0.0)))
            cur = c.execute(
                """
                INSERT INTO fabric_wisdom_prompts
                (project, domain, prompt_text, weight, enabled, success_count, failure_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    clean_project,
                    clean_domain,
                    clean_prompt,
                    initial_weight,
                    1 if bounded_score > 0 else 0,
                    1 if bounded_score <= 0 else 0,
                    now,
                    now,
                ),
            )
            prompt_id = int(cur.lastrowid)
        c.commit()
    return {
        "ok": True,
        "project": clean_project,
        "domain": clean_domain,
        "prompt_id": prompt_id,
        "score": bounded_score,
    }


def prune_low_weight_prompts(project: str = "general", threshold: float = 0.35) -> int:
    ensure_fabric_tables()
    with _conn() as c:
        cur = c.execute(
            """
            UPDATE fabric_wisdom_prompts
            SET enabled=0, updated_at=?
            WHERE project=? AND enabled=1 AND weight < ?
            """,
            (datetime.utcnow().isoformat(), project, float(threshold)),
        )
        c.commit()
        return int(cur.rowcount or 0)


def fabric_wisdom_status(project: str = "general") -> Dict[str, Any]:
    ensure_fabric_tables()
    with _conn() as c:
        total = int(c.execute("SELECT COUNT(1) FROM fabric_wisdom_prompts WHERE project=?", (project,)).fetchone()[0])
        enabled = int(c.execute("SELECT COUNT(1) FROM fabric_wisdom_prompts WHERE project=? AND enabled=1", (project,)).fetchone()[0])
        template_total = int(c.execute("SELECT COUNT(1) FROM fabric_json_templates WHERE project=?", (project,)).fetchone()[0])
        template_enabled = int(c.execute("SELECT COUNT(1) FROM fabric_json_templates WHERE project=? AND enabled=1", (project,)).fetchone()[0])
        citation_total = int(c.execute("SELECT COUNT(1) FROM fabric_vector_citations WHERE project=?", (project,)).fetchone()[0])
        top = c.execute(
            """
            SELECT domain, weight, success_count, failure_count
            FROM fabric_wisdom_prompts
            WHERE project=? AND enabled=1
            ORDER BY weight DESC, updated_at DESC
            LIMIT 6
            """,
            (project,),
        ).fetchall()
    return {
        "project": project,
        "db_path": str(DB_PATH),
        "total_prompts": total,
        "enabled_prompts": enabled,
        "total_json_templates": template_total,
        "enabled_json_templates": template_enabled,
        "vector_citations": citation_total,
        "ram": fabric_ram_status(project),
        "top_prompts": [dict(row) for row in top],
    }
