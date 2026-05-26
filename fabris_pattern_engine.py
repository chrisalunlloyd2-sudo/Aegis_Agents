"""
FABRIS pattern engine (local):
Feedback-Aware Behavioral Recurrence Intelligence Signals.

Tracks recurrent chat/runtime failure patterns and exposes short hints that can
be injected into coder context without adding heavy routing layers.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "gemini_bridge.db"

LOW_SIGNAL_MARKERS = (
    "default directive updated. it remains available for explicit configuration and automation jobs.",
    "execution loop is working through the reduced brief",
    "i am an aegis coding and build agent, ready to assist.",
)

TIMEOUT_MARKERS = (
    "timed out",
    "request failed with status 502",
    "request failed with status 524",
    "local stream finished without tokens",
    "no reply came back from the active model",
)


def _ensure_tables() -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fabris_turn_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL,
                route_name TEXT,
                requested_mode TEXT,
                target_model TEXT,
                prompt_len INTEGER,
                reply_len INTEGER,
                meta_json TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fabris_pattern_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                project TEXT NOT NULL,
                route_name TEXT,
                pattern_key TEXT NOT NULL,
                severity INTEGER NOT NULL,
                signal TEXT,
                detail_json TEXT,
                FOREIGN KEY(event_id) REFERENCES fabris_turn_events(id)
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_fabris_hits_project_time ON fabris_pattern_hits(project, timestamp)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_fabris_hits_pattern ON fabris_pattern_hits(pattern_key)")
        connection.commit()
    finally:
        connection.close()


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().split())


def _repetitive_line_ratio(text: str) -> float:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 8:
        return 0.0
    lowered = [line.lower() for line in lines]
    unique = len(set(lowered))
    duplicate_ratio = 1.0 - (unique / max(len(lowered), 1))
    return max(0.0, min(1.0, duplicate_ratio))


def _detect_patterns(prompt: str, reply: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    prompt_norm = _normalize(prompt)
    reply_norm = _normalize(reply)
    reply_lower = reply_norm.lower()

    if not reply_norm:
        hits.append(
            {
                "pattern_key": "empty_reply",
                "severity": 3,
                "signal": "Assistant reply was empty.",
                "detail": {"reply_len": 0},
            }
        )

    for marker in TIMEOUT_MARKERS:
        if marker in reply_lower:
            hits.append(
                {
                    "pattern_key": "timeout_or_stream_failure",
                    "severity": 3,
                    "signal": marker,
                    "detail": {"marker": marker},
                }
            )
            break

    for marker in LOW_SIGNAL_MARKERS:
        if marker in reply_lower:
            hits.append(
                {
                    "pattern_key": "low_signal_autoreply",
                    "severity": 3,
                    "signal": marker[:180],
                    "detail": {"marker": marker},
                }
            )
            break

    if "tok-keyword" in reply_lower or "tok-comment" in reply_lower:
        hits.append(
            {
                "pattern_key": "html_token_leak",
                "severity": 2,
                "signal": "HTML syntax-token markup leaked into assistant reply.",
                "detail": {},
            }
        )

    repeat_ratio = _repetitive_line_ratio(reply_norm)
    if repeat_ratio >= 0.45:
        hits.append(
            {
                "pattern_key": "repetitive_output",
                "severity": 2,
                "signal": f"Repeated-line ratio {repeat_ratio:.2f}",
                "detail": {"repeat_ratio": round(repeat_ratio, 3)},
            }
        )

    asked_casual = bool(re.search(r"\b(hi|hello|how are you|what's up)\b", prompt_norm.lower()))
    if asked_casual and re.search(r"\b(program loop started|default directive updated|direct program route)\b", reply_lower):
        hits.append(
            {
                "pattern_key": "intent_misroute_chat_to_builder",
                "severity": 2,
                "signal": "Casual chat prompt routed into build/automation phrasing.",
                "detail": {},
            }
        )

    # Positive signal: evidence-backed execution language.
    if re.search(r"\b(verified|passed|test evidence|tool evidence|wrote file|created)\b", reply_lower):
        hits.append(
            {
                "pattern_key": "evidence_positive",
                "severity": 1,
                "signal": "Reply included verification/evidence language.",
                "detail": {},
            }
        )

    return hits


def record_fabris_turn(
    *,
    session_id: str,
    project: str,
    prompt: str,
    reply: str,
    requested_mode: str,
    target_model: str,
    route_name: str,
) -> Dict[str, Any]:
    _ensure_tables()
    now = datetime.utcnow().isoformat()
    prompt_text = (prompt or "").strip()
    reply_text = (reply or "").strip()
    hits = _detect_patterns(prompt_text, reply_text)
    metadata = {
        "prompt_preview": prompt_text[:220],
        "reply_preview": reply_text[:260],
    }

    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(
            """
            INSERT INTO fabris_turn_events (
                timestamp, session_id, project, route_name, requested_mode, target_model,
                prompt_len, reply_len, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                session_id or "unknown",
                project or "general",
                route_name or "chat",
                requested_mode or "",
                target_model or "",
                len(prompt_text),
                len(reply_text),
                json.dumps(metadata, ensure_ascii=True),
            ),
        )
        event_id = int(cursor.lastrowid)
        for hit in hits:
            connection.execute(
                """
                INSERT INTO fabris_pattern_hits (
                    event_id, timestamp, project, route_name, pattern_key, severity, signal, detail_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    now,
                    project or "general",
                    route_name or "chat",
                    str(hit.get("pattern_key") or "unknown"),
                    int(hit.get("severity") or 1),
                    str(hit.get("signal") or "")[:300],
                    json.dumps(hit.get("detail") or {}, ensure_ascii=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()

    return {"ok": True, "event_id": event_id, "pattern_count": len(hits), "patterns": hits}


def top_fabris_patterns(
    *,
    project: str = "general",
    route_name: Optional[str] = None,
    since_hours: int = 48,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    _ensure_tables()
    since_iso = (datetime.utcnow() - timedelta(hours=max(1, int(since_hours)))).isoformat()
    params: List[Any] = [project, since_iso]
    route_clause = ""
    if route_name:
        route_clause = "AND route_name = ?"
        params.append(route_name)
    params.append(max(1, int(limit)))

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"""
            SELECT
                pattern_key,
                COUNT(*) AS hit_count,
                ROUND(AVG(severity), 2) AS avg_severity,
                MAX(timestamp) AS last_seen,
                MAX(signal) AS sample_signal
            FROM fabris_pattern_hits
            WHERE project = ?
              AND timestamp >= ?
              {route_clause}
            GROUP BY pattern_key
            ORDER BY hit_count DESC, avg_severity DESC, last_seen DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    finally:
        connection.close()

    recommendation_map = {
        "timeout_or_stream_failure": "Increase stream timeout, reduce prompt payload, and auto-recycle stalled model runners.",
        "low_signal_autoreply": "Keep directive-capture disabled for normal chat and route greetings to simple prompt mode.",
        "intent_misroute_chat_to_builder": "Strengthen intent gate so casual chat never triggers program/builder route.",
        "repetitive_output": "Add anti-repeat penalty or summary compression before final response emission.",
        "html_token_leak": "Strip formatter artifacts before final reply and block syntax-highlighter HTML tokens.",
        "empty_reply": "Fail fast to fallback model after first empty token window.",
        "evidence_positive": "Maintain evidence-gated workflow for execution claims.",
    }

    output: List[Dict[str, Any]] = []
    for row in rows:
        key = str(row["pattern_key"])
        output.append(
            {
                "pattern_key": key,
                "hit_count": int(row["hit_count"] or 0),
                "avg_severity": float(row["avg_severity"] or 0.0),
                "last_seen": str(row["last_seen"] or ""),
                "sample_signal": str(row["sample_signal"] or ""),
                "recommendation": recommendation_map.get(key, "Review recurrence and tune the response route or model contract."),
            }
        )
    return output


def build_fabris_context_hints(*, project: str, prompt: str, limit: int = 3) -> str:
    prompt_lower = (prompt or "").lower()
    if not re.search(r"\b(error|timeout|slow|stuck|optimi[sz]e|loop|response|freeze|bug|fail)\b", prompt_lower):
        return ""
    patterns = top_fabris_patterns(project=project or "general", since_hours=72, limit=max(1, int(limit)))
    if not patterns:
        return ""
    lines = ["FABRIS PATTERN HINTS (recent recurrent runtime signals):"]
    for item in patterns[: max(1, int(limit))]:
        lines.append(
            f"- {item['pattern_key']}: {item['hit_count']} hit(s), severity {item['avg_severity']:.2f}. "
            f"Recommendation: {item['recommendation']}"
        )
    return "\n".join(lines)


def fabris_status() -> Dict[str, Any]:
    _ensure_tables()
    connection = sqlite3.connect(DB_PATH)
    try:
        event_count = int(connection.execute("SELECT COUNT(1) FROM fabris_turn_events").fetchone()[0])
        hit_count = int(connection.execute("SELECT COUNT(1) FROM fabris_pattern_hits").fetchone()[0])
    finally:
        connection.close()
    return {
        "db_path": str(DB_PATH),
        "event_count": event_count,
        "pattern_hit_count": hit_count,
        "top_patterns": top_fabris_patterns(project="general", since_hours=72, limit=5),
    }
