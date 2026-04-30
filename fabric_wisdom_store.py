from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "gemini_bridge.db"


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
        c.commit()


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
    if not prompts:
        return ""
    lines = ["FABRIC WISDOM GUIDANCE (DB-weighted):"]
    for item in prompts:
        lines.append(f"- [{item['domain']}] {item['prompt_text']}")
    return "\n".join(lines)


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
        "top_prompts": [dict(row) for row in top],
    }
