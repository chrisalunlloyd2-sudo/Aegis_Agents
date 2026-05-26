from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AEGIS_MANIFOLD_DB", str(ROOT / "gemini_bridge.db")))


def _conn() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_runtime_trace_tables() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                trace_type TEXT NOT NULL,
                route TEXT NOT NULL,
                model TEXT,
                prompt_hash TEXT,
                elapsed_ms INTEGER,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        c.commit()


def record_runtime_trace(
    *,
    project: str,
    trace_type: str,
    route: str,
    payload: Dict[str, Any],
    model: Optional[str] = None,
    prompt_hash: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
) -> Dict[str, Any]:
    ensure_runtime_trace_tables()
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO runtime_traces
            (project, trace_type, route, model, prompt_hash, elapsed_ms, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project or "general",
                trace_type or "event",
                route or "unknown",
                model,
                prompt_hash,
                elapsed_ms,
                json.dumps(payload or {}, ensure_ascii=True, default=str),
                now,
            ),
        )
        c.commit()
    return {"ok": True, "trace_id": int(cur.lastrowid), "created_at": now}


def recent_runtime_traces(project: str = "general", limit: int = 50, trace_type: str = "") -> List[Dict[str, Any]]:
    ensure_runtime_trace_tables()
    safe_limit = max(1, min(int(limit), 500))
    with _conn() as c:
        if trace_type:
            rows = c.execute(
                """
                SELECT * FROM runtime_traces
                WHERE project=? AND trace_type=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (project or "general", trace_type, safe_limit),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT * FROM runtime_traces
                WHERE project=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (project or "general", safe_limit),
            ).fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            item["payload"] = {}
        results.append(item)
    return results


def runtime_trace_status(project: str = "general") -> Dict[str, Any]:
    ensure_runtime_trace_tables()
    with _conn() as c:
        total = int(c.execute("SELECT COUNT(1) FROM runtime_traces WHERE project=?", (project,)).fetchone()[0])
        timeouts = int(
            c.execute(
                "SELECT COUNT(1) FROM runtime_traces WHERE project=? AND trace_type LIKE '%timeout%'",
                (project,),
            ).fetchone()[0]
        )
    return {"project": project, "db_path": str(DB_PATH), "total_traces": total, "timeout_traces": timeouts}
