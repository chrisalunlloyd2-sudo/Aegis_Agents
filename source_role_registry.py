import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AEGIS_MANIFOLD_DB", str(REPO_ROOT / "gemini_bridge.db")))
EXTERNAL_SOURCE_ROOT = Path(
    os.getenv("AEGIS_EXTERNAL_SOURCE_ROOT", str(REPO_ROOT.parent / "AIEngine" / "external_sources"))
)
FABRIC_PATTERN_ROOT = Path(
    os.getenv(
        "AEGIS_FABRIC_PATTERN_ROOT",
        str(EXTERNAL_SOURCE_ROOT / "fabric" / "data" / "patterns"),
    )
)

REGISTRY_ENABLED = os.getenv("AEGIS_SOURCE_ROLE_REGISTRY_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FABRIC_RAM_CACHE_ENABLED = os.getenv("AEGIS_FABRIC_RAM_CACHE_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FABRIC_RAM_CACHE_MAX_BYTES = int(
    float(os.getenv("AEGIS_FABRIC_RAM_CACHE_MAX_MB", "500")) * 1024 * 1024
)
EXTERNAL_SOURCES_ACTIVE_IN_PROMPT = os.getenv(
    "AEGIS_EXTERNAL_SOURCES_ACTIVE_IN_PROMPT",
    "0",
).strip().lower() in {"1", "true", "yes", "on"}
DB_READ_POLICY = os.getenv("AEGIS_DB_READ_POLICY", "cue_or_evidence_only")
SOURCE_TRACE_INPUT_LIMIT = int(os.getenv("AEGIS_SOURCE_TRACE_INPUT_LIMIT", "12000"))


REQUIRED_PERFORMATIVES: List[str] = [
    "FABRIC",
    "LAVA",
    "AIDER",
    "ACL/KQML",
    "LOGIC",
    "MATH",
    "SCIENTIFIC_METHOD",
    "SOAP",
    "GENETIC",
]

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "can",
    "do",
    "for",
    "from",
    "get",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "make",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "so",
    "that",
    "the",
    "this",
    "to",
    "use",
    "we",
    "with",
    "you",
}

ACTION_WORDS = {
    "add",
    "build",
    "compile",
    "crawl",
    "debug",
    "decompile",
    "download",
    "execute",
    "extract",
    "fix",
    "index",
    "load",
    "log",
    "monitor",
    "mutate",
    "optimize",
    "record",
    "route",
    "score",
    "select",
    "summarize",
    "test",
    "trace",
    "validate",
    "verify",
}

CONSTRAINT_WORDS = {
    "always",
    "critical",
    "deterministic",
    "fast",
    "limit",
    "memory",
    "never",
    "no",
    "only",
    "ram",
    "safe",
    "scientific",
    "single",
    "timeout",
    "volatile",
}

SOURCE_KEYWORDS: Dict[str, List[str]] = {
    "fabric": [
        "fabric",
        "wisdom",
        "template",
        "pattern",
        "performative",
        "prompt",
        "positive",
        "teach",
    ],
    "hf_datasets": [
        "dataset",
        "training",
        "tool",
        "toolcall",
        "toolcalling",
        "selection",
        "deepfabric",
        "examples",
    ],
    "lava": [
        "lava",
        "orchestrate",
        "route",
        "process",
        "event",
        "workspace",
        "scratchpad",
        "neuromorphic",
        "loihi",
    ],
    "lava-dl": [
        "lava",
        "vision",
        "language",
        "deep",
        "learning",
        "slayer",
        "image",
        "sensor",
        "spiking",
    ],
    "lava-dnf": [
        "lava",
        "dynamic",
        "field",
        "attention",
        "workspace",
        "signal",
        "vision",
    ],
    "lava-optimization": [
        "lava",
        "optimization",
        "soap",
        "score",
        "solver",
        "constraint",
        "fitness",
        "genetic",
    ],
    "logic_and_proof": [
        "logic",
        "axiom",
        "proof",
        "zfc",
        "set",
        "formal",
        "math",
        "theorem",
    ],
    "mathlib4": [
        "logic",
        "axiom",
        "proof",
        "math",
        "lean",
        "theorem",
        "formal",
        "zfc",
    ],
    "aima-python": [
        "algorithm",
        "ai",
        "search",
        "planning",
        "agent",
        "reasoning",
        "graph",
        "logic",
    ],
    "openclaw": [
        "tool",
        "toolcall",
        "toolcalling",
        "agent",
        "gateway",
        "kqml",
        "acl",
        "protocol",
        "sidecar",
    ],
    "deepseek_coder": [
        "deepseek",
        "coder",
        "code",
        "program",
        "repository",
        "inference",
        "finetune",
        "evaluation",
        "structure",
    ],
    "deepseek_coder_knowledge_trees": [
        "deepseek",
        "distilled",
        "coder",
        "code",
        "test",
        "verify",
        "pass_rate",
        "operational",
        "dataset",
        "structure",
    ],
    "claude_distilled_reference": [
        "claude",
        "opus",
        "distilled",
        "qwen",
        "reasoning",
        "logic",
        "stem",
        "math",
        "coding",
        "programming",
    ],
}


LAYER_ROLES: List[Dict[str, Any]] = [
    {
        "role": "fabric",
        "job": "teach",
        "responsibility": "Stable wisdom, proven patterns, reusable good examples.",
        "access_rule": "Access often; add rarely after evidence.",
        "write_rule": "Only distilled, proven, high-signal behavior graduates here.",
        "active_by_default": True,
    },
    {
        "role": "lava",
        "job": "route",
        "responsibility": "Event/process flow for tools, SOAP, GC, compiler/test loops.",
        "access_rule": "Use as orchestration state and event routing, not conversational memory.",
        "write_rule": "Record process events and scores; do not become a wisdom store.",
        "active_by_default": True,
    },
    {
        "role": "genetic_coder",
        "job": "mutate_build",
        "responsibility": "Fast, sloppy candidate generation inside a sandbox.",
        "access_rule": "Allowed to be messy internally; only outputs evidence and candidates.",
        "write_rule": "Successful attempts go to DB evidence; only distilled successes may reach Fabric.",
        "active_by_default": True,
    },
    {
        "role": "soap",
        "job": "score_adapt",
        "responsibility": "Score candidates and adapt weights from pass/fail evidence.",
        "access_rule": "Consumes evidence and feature signals; does not talk to user.",
        "write_rule": "Writes scoring state and fitness traces.",
        "active_by_default": True,
    },
    {
        "role": "compiler",
        "job": "verify",
        "responsibility": "Compile, run, test, and reject broken code.",
        "access_rule": "Called by Lava/GC phases when verification is required.",
        "write_rule": "Writes pass/fail evidence only.",
        "active_by_default": True,
    },
    {
        "role": "db",
        "job": "remember",
        "responsibility": "Evidence ledger, source index, user-cued memory, run history.",
        "access_rule": DB_READ_POLICY,
        "write_rule": "Always record evidence; read into active reasoning only when cued or required.",
        "active_by_default": True,
    },
    {
        "role": "ram",
        "job": "accelerate",
        "responsibility": "Hot cache for small stable data such as Fabric patterns.",
        "access_rule": "Cache for speed, not blanket prompt injection.",
        "write_rule": "Ephemeral cache only; DB remains the durable ledger.",
        "active_by_default": True,
    },
    {
        "role": "model",
        "job": "talk",
        "responsibility": "Natural conversation, intent understanding, final human-facing reply.",
        "access_rule": "Uses selected context only; does not own tool/process state.",
        "write_rule": "Replies and summaries are recorded as evidence/memory by other layers.",
        "active_by_default": True,
    },
]


SOURCE_ROLE_RULES: Dict[str, Dict[str, Any]] = {
    "fabric": {
        "role": "fabric",
        "source_type": "wisdom_patterns",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Fabric patterns are selected wisdom, not a blanket prompt layer.",
    },
    "hf_datasets": {
        "role": "fabric",
        "source_type": "tool_call_training_data",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "DeepFabric-style data teaches tool selection after indexing/training, not live prompt injection.",
    },
    "lava": {
        "role": "lava",
        "source_type": "orchestration_reference",
        "ram_eligible": False,
        "active_in_prompt": False,
        "notes": "Lava source is a process/message-passing reference and future runtime target.",
    },
    "lava-dl": {
        "role": "lava",
        "source_type": "learning_reference",
        "ram_eligible": False,
        "active_in_prompt": False,
        "notes": "Large reference library; retrieve selectively.",
    },
    "lava-dnf": {
        "role": "lava",
        "source_type": "dynamic_field_reference",
        "ram_eligible": False,
        "active_in_prompt": False,
        "notes": "Large reference library; retrieve selectively.",
    },
    "lava-optimization": {
        "role": "lava",
        "source_type": "soap_gc_optimization_reference",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Optimization concepts map to SOAP/GC scoring.",
    },
    "logic_and_proof": {
        "role": "fabric",
        "source_type": "logic_wisdom",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Small formal logic source; safe as selectable wisdom.",
    },
    "mathlib4": {
        "role": "fabric",
        "source_type": "formal_logic_library",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Formal logic/math library; index and retrieve selectively.",
    },
    "aima-python": {
        "role": "fabric",
        "source_type": "ai_algorithm_reference",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Classical AI algorithms and logic references.",
    },
    "openclaw": {
        "role": "lava",
        "source_type": "agent_tool_runtime_reference",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Reference for tool-call routing and gateway behavior.",
    },
    "deepseek_coder": {
        "role": "fabric",
        "source_type": "code_model_reference",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "Official DeepSeek-Coder repository: inference, evaluation, finetuning, and code-model structure.",
    },
    "deepseek_coder_knowledge_trees": {
        "role": "fabric",
        "source_type": "distilled_code_operational_data",
        "ram_eligible": True,
        "active_in_prompt": False,
        "notes": "DeepSeek distilled code metadata and bounded operational sample with tests, verify scores, and pass rates.",
    },
    "claude_distilled_reference": {
        "role": "db",
        "source_type": "quarter_weight_reasoning_reference",
        "ram_eligible": False,
        "active_in_prompt": False,
        "notes": "Claude-distilled Qwen reasoning is an indexed nominal reference at 0.25 weight, prioritized for logic, STEM, math, computers, and programming.",
    },
}


_fabric_pattern_cache: Dict[str, str] = {}
_fabric_cache_loaded_at: Optional[str] = None
_fabric_cache_bytes: int = 0
_tables_initialized = False
_tables_init_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_source_role_tables() -> None:
    global _tables_initialized
    if _tables_initialized:
        return
    with _tables_init_lock:
        if _tables_initialized:
            return
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS aegis_layer_roles (
                    role TEXT PRIMARY KEY,
                    job TEXT NOT NULL,
                    responsibility TEXT NOT NULL,
                    access_rule TEXT NOT NULL,
                    write_rule TEXT NOT NULL,
                    active_by_default INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
            CREATE TABLE IF NOT EXISTS aegis_external_sources (
                source_name TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                source_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    total_bytes INTEGER NOT NULL,
                    row_count INTEGER NOT NULL,
                    ram_eligible INTEGER NOT NULL,
                    active_in_prompt INTEGER NOT NULL,
                    notes TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            CREATE INDEX IF NOT EXISTS idx_aegis_external_sources_role
                ON aegis_external_sources(role, source_type);
            CREATE TABLE IF NOT EXISTS aegis_source_selection_traces (
                trace_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                input_excerpt TEXT NOT NULL,
                keyword_vector_json TEXT NOT NULL,
                candidates_json TEXT NOT NULL,
                selected_json TEXT NOT NULL,
                active_prompt_sources_json TEXT NOT NULL,
                rule TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_aegis_source_selection_traces_project_time
                ON aegis_source_selection_traces(project, created_at);
            """
        )
            now = _utc_now()
            for role in LAYER_ROLES:
                conn.execute(
                    """
                    INSERT INTO aegis_layer_roles (
                        role, job, responsibility, access_rule, write_rule,
                        active_by_default, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(role) DO UPDATE SET
                        job=excluded.job,
                        responsibility=excluded.responsibility,
                        access_rule=excluded.access_rule,
                        write_rule=excluded.write_rule,
                        active_by_default=excluded.active_by_default,
                        updated_at=excluded.updated_at
                    """,
                    (
                        role["role"],
                        role["job"],
                        role["responsibility"],
                        role["access_rule"],
                        role["write_rule"],
                        1 if role["active_by_default"] else 0,
                        now,
                    ),
                )
        _tables_initialized = True


def _iter_files(path: Path) -> Iterable[Path]:
    if not path.exists():
        return []
    return (p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts and ".cache" not in p.parts)


def _count_rows(path: Path) -> int:
    rows = 0
    for file_path in _iter_files(path):
        suffix = file_path.suffix.lower()
        if suffix == ".jsonl":
            try:
                with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    rows += sum(1 for line in handle if line.strip())
            except OSError:
                continue
        elif suffix == ".parquet":
            try:
                import pyarrow.parquet as pq

                rows += int(pq.ParquetFile(str(file_path)).metadata.num_rows)
            except Exception:
                continue
    return rows


def _source_stats(path: Path) -> Dict[str, int]:
    files = list(_iter_files(path))
    return {
        "file_count": len(files),
        "total_bytes": sum(p.stat().st_size for p in files if p.exists()),
        "row_count": _count_rows(path),
    }


def rebuild_external_source_index() -> Dict[str, Any]:
    ensure_source_role_tables()
    indexed: List[Dict[str, Any]] = []
    now = _utc_now()
    with _connect() as conn:
        for path in sorted(EXTERNAL_SOURCE_ROOT.iterdir() if EXTERNAL_SOURCE_ROOT.exists() else []):
            if not path.is_dir():
                continue
            rule = SOURCE_ROLE_RULES.get(
                path.name,
                {
                    "role": "db",
                    "source_type": "unclassified_reference",
                    "ram_eligible": False,
                    "active_in_prompt": False,
                    "notes": "Unclassified external source; inactive until reviewed.",
                },
            )
            stats = _source_stats(path)
            row = {
                "source_name": path.name,
                "role": rule["role"],
                "source_type": rule["source_type"],
                "path": str(path),
                "file_count": stats["file_count"],
                "total_bytes": stats["total_bytes"],
                "row_count": stats["row_count"],
                "ram_eligible": bool(rule["ram_eligible"]) and stats["total_bytes"] <= FABRIC_RAM_CACHE_MAX_BYTES,
                "active_in_prompt": bool(rule["active_in_prompt"]) and EXTERNAL_SOURCES_ACTIVE_IN_PROMPT,
                "notes": rule["notes"],
                "updated_at": now,
            }
            conn.execute(
                """
                INSERT INTO aegis_external_sources (
                    source_name, role, source_type, path, file_count,
                    total_bytes, row_count, ram_eligible, active_in_prompt,
                    notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    role=excluded.role,
                    source_type=excluded.source_type,
                    path=excluded.path,
                    file_count=excluded.file_count,
                    total_bytes=excluded.total_bytes,
                    row_count=excluded.row_count,
                    ram_eligible=excluded.ram_eligible,
                    active_in_prompt=excluded.active_in_prompt,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    row["source_name"],
                    row["role"],
                    row["source_type"],
                    row["path"],
                    row["file_count"],
                    row["total_bytes"],
                    row["row_count"],
                    1 if row["ram_eligible"] else 0,
                    1 if row["active_in_prompt"] else 0,
                    row["notes"],
                    row["updated_at"],
                ),
            )
            indexed.append(row)
    return {"ok": True, "indexed_count": len(indexed), "sources": indexed, "updated_at": now}


def load_fabric_pattern_cache(force: bool = False) -> Dict[str, Any]:
    global _fabric_cache_bytes, _fabric_cache_loaded_at, _fabric_pattern_cache
    if not FABRIC_RAM_CACHE_ENABLED:
        return {"enabled": False, "pattern_count": 0, "bytes": 0, "loaded_at": None}
    if _fabric_pattern_cache and not force:
        return {
            "enabled": True,
            "pattern_count": len(_fabric_pattern_cache),
            "bytes": _fabric_cache_bytes,
            "loaded_at": _fabric_cache_loaded_at,
        }
    pattern_files = list(FABRIC_PATTERN_ROOT.rglob("*.md")) if FABRIC_PATTERN_ROOT.exists() else []
    total_bytes = sum(p.stat().st_size for p in pattern_files if p.exists())
    if total_bytes > FABRIC_RAM_CACHE_MAX_BYTES:
        _fabric_pattern_cache = {}
        _fabric_cache_bytes = 0
        _fabric_cache_loaded_at = None
        return {
            "enabled": True,
            "pattern_count": 0,
            "bytes": total_bytes,
            "loaded_at": None,
            "skipped_reason": "fabric pattern set exceeds RAM cache budget",
        }
    cache: Dict[str, str] = {}
    for path in pattern_files:
        try:
            key = str(path.relative_to(FABRIC_PATTERN_ROOT)).replace("\\", "/")
            cache[key] = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    _fabric_pattern_cache = cache
    _fabric_cache_bytes = total_bytes
    _fabric_cache_loaded_at = _utc_now()
    return {
        "enabled": True,
        "pattern_count": len(_fabric_pattern_cache),
        "bytes": _fabric_cache_bytes,
        "loaded_at": _fabric_cache_loaded_at,
    }


def extract_keyword_vector(input_text: str) -> Dict[str, Any]:
    bounded_text = (input_text or "")[:SOURCE_TRACE_INPUT_LIMIT]
    tokens = [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_+./-]{1,}", bounded_text.lower())
        if token not in STOPWORDS
    ]
    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    verbs = [token for token in counts if token in ACTION_WORDS]
    constraints = [token for token in counts if token in CONSTRAINT_WORDS]
    nouns = [token for token in counts if token not in ACTION_WORDS and token not in CONSTRAINT_WORDS]
    weighted = [
        {"keyword": token, "weight": count + (2 if token in ACTION_WORDS else 0) + (1 if token in CONSTRAINT_WORDS else 0)}
        for token, count in counts.items()
    ]
    weighted.sort(key=lambda item: (-item["weight"], item["keyword"]))
    return {
        "verbs": sorted(verbs),
        "nouns": sorted(nouns)[:80],
        "constraints": sorted(constraints),
        "weighted": weighted[:80],
        "token_count": len(tokens),
    }


def _candidate_score(source: Dict[str, Any], keyword_vector: Dict[str, Any]) -> Dict[str, Any]:
    weighted_keywords = {
        item["keyword"]: int(item["weight"])
        for item in keyword_vector.get("weighted", [])
    }
    source_name = str(source.get("source_name") or "")
    haystack = " ".join(
        [
            source_name,
            str(source.get("role") or ""),
            str(source.get("source_type") or ""),
            str(source.get("notes") or ""),
            " ".join(SOURCE_KEYWORDS.get(source_name, [])),
        ]
    ).lower()
    matched: List[str] = []
    score = 0.0
    for keyword, weight in weighted_keywords.items():
        if keyword in haystack:
            matched.append(keyword)
            score += float(weight)
    role = str(source.get("role") or "")
    if role == "fabric" and any(k in weighted_keywords for k in ("logic", "math", "template", "wisdom", "pattern")):
        score += 2.0
    if role == "lava" and any(k in weighted_keywords for k in ("route", "tool", "orchestrate", "workspace", "vision")):
        score += 2.0
    if int(source.get("ram_eligible") or 0):
        score += 0.25
    return {
        "source_name": source_name,
        "role": role,
        "source_type": source.get("source_type"),
        "score": round(score, 3),
        "matched_keywords": sorted(matched),
        "ram_eligible": bool(source.get("ram_eligible")),
        "active_in_prompt": bool(source.get("active_in_prompt")),
    }


def trace_source_selection(input_text: str, project: str = "general", limit: int = 6) -> Dict[str, Any]:
    if not REGISTRY_ENABLED:
        return {"enabled": False}
    ensure_source_role_tables()
    keyword_vector = extract_keyword_vector(input_text)
    with _connect() as conn:
        source_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM aegis_external_sources ORDER BY role, source_name"
            ).fetchall()
        ]
        if not source_rows:
            rebuild_external_source_index()
            source_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM aegis_external_sources ORDER BY role, source_name"
                ).fetchall()
            ]
    candidates = [_candidate_score(row, keyword_vector) for row in source_rows]
    candidates.sort(key=lambda item: (-float(item["score"]), item["role"], item["source_name"]))
    selected = [item for item in candidates if float(item["score"]) > 0][: max(1, min(limit, 12))]
    primary = selected[0] if selected else None
    support = selected[1:] if len(selected) > 1 else []
    trace_id = uuid.uuid4().hex
    now = _utc_now()
    active_prompt_sources = [item["source_name"] for item in selected if item.get("active_in_prompt")]
    result = {
        "enabled": True,
        "trace_id": trace_id,
        "project": project,
        "keyword_vector": keyword_vector,
        "primary_source": primary,
        "supporting_sources": support,
        "candidates": candidates,
        "active_prompt_sources": active_prompt_sources,
        "compiled_template_count": 1 if selected else 0,
        "rule": "Trace only: sources are scored and recorded, not injected into the prompt.",
        "created_at": now,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO aegis_source_selection_traces (
                trace_id, project, input_excerpt, keyword_vector_json,
                candidates_json, selected_json, active_prompt_sources_json,
                rule, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                project,
                (input_text or "")[:1000],
                json.dumps(keyword_vector, sort_keys=True),
                json.dumps(candidates, sort_keys=True),
                json.dumps({"primary": primary, "support": support}, sort_keys=True),
                json.dumps(active_prompt_sources, sort_keys=True),
                result["rule"],
                now,
            ),
        )
    return result


def recent_source_selection_traces(project: str = "general", limit: int = 20) -> Dict[str, Any]:
    ensure_source_role_tables()
    safe_limit = max(1, min(int(limit or 20), 100))
    with _connect() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT trace_id, project, input_excerpt, keyword_vector_json,
                       selected_json, active_prompt_sources_json, rule, created_at
                FROM aegis_source_selection_traces
                WHERE project = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project, safe_limit),
            ).fetchall()
        ]
    for row in rows:
        row["keyword_vector"] = json.loads(row.pop("keyword_vector_json") or "{}")
        row["selected"] = json.loads(row.pop("selected_json") or "{}")
        row["active_prompt_sources"] = json.loads(row.pop("active_prompt_sources_json") or "[]")
    return {"project": project, "count": len(rows), "traces": rows}


def source_role_status(project: str = "general", include_sources: bool = True) -> Dict[str, Any]:
    if not REGISTRY_ENABLED:
        return {"enabled": False}
    ensure_source_role_tables()
    fabric_cache = load_fabric_pattern_cache(force=False)
    with _connect() as conn:
        roles = [dict(row) for row in conn.execute("SELECT * FROM aegis_layer_roles ORDER BY role").fetchall()]
        sources = []
        totals = conn.execute(
            "SELECT COUNT(*) AS source_count, COALESCE(SUM(total_bytes), 0) AS total_bytes "
            "FROM aegis_external_sources"
        ).fetchone()
        active_prompt_sources = [
            row["source_name"]
            for row in conn.execute(
                "SELECT source_name FROM aegis_external_sources "
                "WHERE active_in_prompt = 1 ORDER BY source_name"
            ).fetchall()
        ]
        if include_sources:
            sources = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM aegis_external_sources ORDER BY role, source_name"
                ).fetchall()
            ]
    source_count = len(sources) if include_sources else int(totals["source_count"] or 0)
    total_source_bytes = (
        sum(int(row.get("total_bytes") or 0) for row in sources)
        if include_sources
        else int(totals["total_bytes"] or 0)
    )
    return {
        "enabled": True,
        "project": project,
        "external_source_root": str(EXTERNAL_SOURCE_ROOT),
        "fabric_pattern_root": str(FABRIC_PATTERN_ROOT),
        "fabric_ram_cache": fabric_cache,
        "db_read_policy": DB_READ_POLICY,
        "active_prompt_sources": active_prompt_sources,
        "roles": roles,
        "source_count": source_count,
        "source_total_mb": round(total_source_bytes / (1024 * 1024), 2),
        "sources": sources,
        "rule": "Fabric teaches; Lava routes; GC mutates/builds; SOAP scores; compilers verify; DB remembers; RAM accelerates; model talks.",
    }


def write_status_snapshot(path: Optional[Path] = None) -> Path:
    target = path or (REPO_ROOT / "source_role_registry_snapshot.json")
    status = source_role_status(include_sources=True)
    target.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return target
