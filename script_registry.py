from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCRIPT_EXTENSIONS: Dict[str, str] = {
    ".py": "python",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".sh": "shell",
}

UBER_SCRIPT_BASE_WEIGHT = float(os.getenv("AEGIS_SCRIPT_UBER_WEIGHT", "1000"))
MAX_INLINE_BYTES = int(os.getenv("AEGIS_SCRIPT_REGISTRY_MAX_INLINE_BYTES", str(2 * 1024 * 1024)))
def _default_roots() -> tuple[Path, ...]:
    configured = os.getenv("AEGIS_SCRIPT_REGISTRY_ROOTS", "").strip()
    if configured:
        return tuple(Path(part.strip()) for part in configured.split(os.pathsep) if part.strip())
    repo_root = Path(__file__).resolve().parent
    return (repo_root, repo_root.parent / "AIEngine")


DEFAULT_ROOTS = _default_roots()


@dataclass
class ScriptRecord:
    path: str
    root: str
    rel_path: str
    name: str
    extension: str
    language: str
    sha256: str
    size_bytes: int
    line_count: int
    content: str
    content_encoding: str
    weight: float
    base_weight: float
    evidence_weight: float
    tags: List[str]
    imported_at: str
    updated_at: str
    last_seen_at: str
    active: int = 1


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def db_path_from_url(database_url: Optional[str] = None, *, base_dir: Optional[Path] = None) -> Path:
    raw = (database_url or os.getenv("DATABASE_URL") or "sqlite:///gemini_bridge.db").strip()
    base = base_dir or Path(__file__).resolve().parent
    if raw.startswith("sqlite:///"):
        value = raw[len("sqlite:///") :]
    elif raw.startswith("sqlite://"):
        value = raw[len("sqlite://") :]
    else:
        value = raw
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path


def connect_registry(database_url: Optional[str] = None) -> sqlite3.Connection:
    path = db_path_from_url(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS script_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            root TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            name TEXT NOT NULL,
            extension TEXT NOT NULL,
            language TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            line_count INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_encoding TEXT NOT NULL,
            weight REAL NOT NULL,
            base_weight REAL NOT NULL,
            evidence_weight REAL NOT NULL DEFAULT 0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            pass_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            avg_response_ms REAL,
            last_result TEXT,
            last_error TEXT,
            tags_json TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_script_registry_weight
            ON script_registry(weight DESC, active);
        CREATE INDEX IF NOT EXISTS idx_script_registry_language
            ON script_registry(language, weight DESC);
        CREATE INDEX IF NOT EXISTS idx_script_registry_sha
            ON script_registry(sha256);

        CREATE TABLE IF NOT EXISTS script_registry_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id INTEGER,
            path TEXT NOT NULL,
            event_type TEXT NOT NULL,
            weight_delta REAL NOT NULL DEFAULT 0,
            response_ms INTEGER,
            passed INTEGER,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(script_id) REFERENCES script_registry(id)
        );

        CREATE TABLE IF NOT EXISTS script_registry_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            roots_json TEXT NOT NULL,
            scanned_count INTEGER NOT NULL,
            inserted_count INTEGER NOT NULL,
            updated_count INTEGER NOT NULL,
            skipped_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    conn.commit()


def iter_script_paths(roots: Sequence[Path]) -> Iterable[tuple[Path, Path]]:
    seen: set[str] = set()
    for raw_root in roots:
        root = raw_root.expanduser().resolve()
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SCRIPT_EXTENSIONS:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            yield root, path


def decode_script_bytes(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def classify_tags(path: Path, root: Path, language: str, size_bytes: int, line_count: int) -> List[str]:
    rel_lower = path.relative_to(root).as_posix().lower()
    name_lower = path.name.lower()
    tags: List[str] = [language]
    if any(token in rel_lower for token in ("maintenance/", "patch_backups/", "archive/", "backup/")):
        tags.append("archive_or_backup")
    if any(token in rel_lower for token in ("vendor/", "node_modules/", ".venv/", "venv/", "__pycache__/")):
        tags.append("third_party_or_cache")
    if any(token in name_lower for token in ("test", "smoke", "stress")):
        tags.append("test_or_benchmark")
    if any(token in name_lower for token in ("bridge", "api", "server", "worker")):
        tags.append("runtime")
    if any(token in name_lower for token in ("tool", "agent", "loop", "registry", "crawler")):
        tags.append("agent_tooling")
    if size_bytes > MAX_INLINE_BYTES:
        tags.append("oversized_content_stub")
    if line_count <= 20:
        tags.append("tiny_script")
    return sorted(set(tags))


def compute_base_weight(path: Path, root: Path, tags: Sequence[str], language: str, size_bytes: int, line_count: int) -> float:
    root_name = root.name.lower()
    weight = UBER_SCRIPT_BASE_WEIGHT
    weight += min(350.0, math.log10(max(size_bytes, 1)) * 85.0)
    weight += min(250.0, math.log10(max(line_count, 1)) * 90.0)
    if root_name == "aegis_agents":
        weight += 250.0
    if root_name == "aiengine":
        weight += 180.0
    if language in {"python", "powershell"}:
        weight += 125.0
    if "runtime" in tags:
        weight += 300.0
    if "agent_tooling" in tags:
        weight += 220.0
    if "test_or_benchmark" in tags:
        weight += 120.0
    if "archive_or_backup" in tags:
        weight -= 420.0
    if "third_party_or_cache" in tags:
        weight -= 520.0
    if "oversized_content_stub" in tags:
        weight -= 100.0
    return round(max(UBER_SCRIPT_BASE_WEIGHT * 0.45, weight), 3)


def build_record(path: Path, root: Path) -> ScriptRecord:
    stat = path.stat()
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    content, encoding = decode_script_bytes(raw[:MAX_INLINE_BYTES])
    if len(raw) > MAX_INLINE_BYTES:
        content += f"\n\n[script_registry: content truncated at {MAX_INLINE_BYTES} bytes; full sha256={sha}]"
    line_count = content.count("\n") + (1 if content else 0)
    language = SCRIPT_EXTENSIONS[path.suffix.lower()]
    tags = classify_tags(path, root, language, stat.st_size, line_count)
    base_weight = compute_base_weight(path, root, tags, language, stat.st_size, line_count)
    now = utc_now()
    return ScriptRecord(
        path=str(path.resolve()),
        root=str(root.resolve()),
        rel_path=path.relative_to(root).as_posix(),
        name=path.name,
        extension=path.suffix.lower(),
        language=language,
        sha256=sha,
        size_bytes=int(stat.st_size),
        line_count=line_count,
        content=content,
        content_encoding=encoding,
        weight=base_weight,
        base_weight=base_weight,
        evidence_weight=0.0,
        tags=tags,
        imported_at=now,
        updated_at=now,
        last_seen_at=now,
    )


def upsert_record(conn: sqlite3.Connection, record: ScriptRecord) -> str:
    existing = conn.execute(
        "SELECT id, sha256, evidence_weight, usage_count, pass_count, fail_count, avg_response_ms, imported_at FROM script_registry WHERE path = ?",
        (record.path,),
    ).fetchone()
    tags_json = json.dumps(record.tags, ensure_ascii=False)
    if existing:
        evidence_weight = float(existing["evidence_weight"] or 0)
        weight = round(record.base_weight + evidence_weight, 3)
        conn.execute(
            """
            UPDATE script_registry
            SET root = ?, rel_path = ?, name = ?, extension = ?, language = ?, sha256 = ?,
                size_bytes = ?, line_count = ?, content = ?, content_encoding = ?,
                weight = ?, base_weight = ?, tags_json = ?, updated_at = ?, last_seen_at = ?, active = 1
            WHERE path = ?
            """,
            (
                record.root,
                record.rel_path,
                record.name,
                record.extension,
                record.language,
                record.sha256,
                record.size_bytes,
                record.line_count,
                record.content,
                record.content_encoding,
                weight,
                record.base_weight,
                tags_json,
                record.updated_at,
                record.last_seen_at,
                record.path,
            ),
        )
        return "updated" if existing["sha256"] != record.sha256 else "seen"

    conn.execute(
        """
        INSERT INTO script_registry (
            path, root, rel_path, name, extension, language, sha256, size_bytes,
            line_count, content, content_encoding, weight, base_weight, evidence_weight,
            tags_json, imported_at, updated_at, last_seen_at, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            record.path,
            record.root,
            record.rel_path,
            record.name,
            record.extension,
            record.language,
            record.sha256,
            record.size_bytes,
            record.line_count,
            record.content,
            record.content_encoding,
            record.weight,
            record.base_weight,
            record.evidence_weight,
            tags_json,
            record.imported_at,
            record.updated_at,
            record.last_seen_at,
        ),
    )
    return "inserted"


def ingest_scripts(roots: Optional[Sequence[Path]] = None, *, database_url: Optional[str] = None) -> Dict[str, Any]:
    started_at = utc_now()
    run_id = started_at.replace(":", "").replace("-", "").replace("T", "_")
    roots = tuple(roots or DEFAULT_ROOTS)
    scanned = inserted = updated = skipped = total_bytes = 0
    errors: List[Dict[str, str]] = []
    conn = connect_registry(database_url)
    try:
        conn.execute("UPDATE script_registry SET active = 0")
        for root, path in iter_script_paths(roots):
            scanned += 1
            try:
                record = build_record(path, root)
                total_bytes += record.size_bytes
                action = upsert_record(conn, record)
                if action == "inserted":
                    inserted += 1
                elif action == "updated":
                    updated += 1
            except Exception as exc:
                skipped += 1
                errors.append({"path": str(path), "error": str(exc)})
        finished_at = utc_now()
        conn.execute(
            """
            INSERT OR REPLACE INTO script_registry_runs (
                run_id, roots_json, scanned_count, inserted_count, updated_count,
                skipped_count, total_bytes, started_at, finished_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                json.dumps([str(root) for root in roots], ensure_ascii=False),
                scanned,
                inserted,
                updated,
                skipped,
                total_bytes,
                started_at,
                finished_at,
                json.dumps({"errors": errors[:100]}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return {
            "ok": True,
            "run_id": run_id,
            "database": str(db_path_from_url(database_url)),
            "roots": [str(root) for root in roots],
            "scanned_count": scanned,
            "inserted_count": inserted,
            "updated_count": updated,
            "skipped_count": skipped,
            "total_bytes": total_bytes,
            "errors": errors[:20],
            "started_at": started_at,
            "finished_at": finished_at,
        }
    finally:
        conn.close()


def registry_status(database_url: Optional[str] = None) -> Dict[str, Any]:
    conn = connect_registry(database_url)
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active,
                SUM(size_bytes) AS total_bytes,
                AVG(weight) AS avg_weight,
                MAX(weight) AS max_weight
            FROM script_registry
            """
        ).fetchone()
        languages = [
            dict(item)
            for item in conn.execute(
                """
                SELECT language, COUNT(*) AS count, ROUND(AVG(weight), 3) AS avg_weight
                FROM script_registry
                WHERE active = 1
                GROUP BY language
                ORDER BY count DESC
                """
            ).fetchall()
        ]
        latest_run = conn.execute(
            "SELECT * FROM script_registry_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "ok": True,
            "database": str(db_path_from_url(database_url)),
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "avg_weight": round(float(row["avg_weight"] or 0), 3),
            "max_weight": round(float(row["max_weight"] or 0), 3),
            "languages": languages,
            "latest_run": dict(latest_run) if latest_run else None,
            "weight_model": {
                "base_prior": UBER_SCRIPT_BASE_WEIGHT,
                "meaning": "scripts start with high prior weight; evidence adjusts evidence_weight over time",
            },
        }
    finally:
        conn.close()


def record_script_event(
    path: str,
    *,
    event_type: str,
    weight_delta: float = 0.0,
    response_ms: Optional[int] = None,
    passed: Optional[bool] = None,
    details: Optional[Dict[str, Any]] = None,
    database_url: Optional[str] = None,
) -> Dict[str, Any]:
    conn = connect_registry(database_url)
    try:
        row = conn.execute("SELECT id, evidence_weight FROM script_registry WHERE path = ?", (path,)).fetchone()
        script_id = int(row["id"]) if row else None
        conn.execute(
            """
            INSERT INTO script_registry_events (
                script_id, path, event_type, weight_delta, response_ms, passed, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                path,
                event_type,
                float(weight_delta),
                response_ms,
                None if passed is None else int(bool(passed)),
                json.dumps(details or {}, ensure_ascii=False),
                utc_now(),
            ),
        )
        if script_id is not None:
            pass_inc = 1 if passed is True else 0
            fail_inc = 1 if passed is False else 0
            conn.execute(
                """
                UPDATE script_registry
                SET evidence_weight = evidence_weight + ?,
                    weight = base_weight + evidence_weight + ?,
                    usage_count = usage_count + 1,
                    pass_count = pass_count + ?,
                    fail_count = fail_count + ?,
                    avg_response_ms = CASE
                        WHEN ? IS NULL THEN avg_response_ms
                        WHEN avg_response_ms IS NULL THEN ?
                        ELSE ((avg_response_ms * usage_count) + ?) / (usage_count + 1)
                    END,
                    last_result = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    float(weight_delta),
                    float(weight_delta),
                    pass_inc,
                    fail_inc,
                    response_ms,
                    response_ms,
                    response_ms,
                    event_type,
                    utc_now(),
                    script_id,
                ),
            )
        conn.commit()
        return {"ok": True, "script_id": script_id, "path": path, "weight_delta": weight_delta}
    finally:
        conn.close()


def search_scripts(query: str = "", *, language: str = "", limit: int = 20, database_url: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = connect_registry(database_url)
    try:
        clauses = ["active = 1"]
        params: List[Any] = []
        if language:
            clauses.append("language = ?")
            params.append(language)
        if query:
            like = f"%{query}%"
            clauses.append("(name LIKE ? OR rel_path LIKE ? OR tags_json LIKE ? OR content LIKE ?)")
            params.extend([like, like, like, like])
        params.append(max(1, min(int(limit), 200)))
        rows = conn.execute(
            f"""
            SELECT path, rel_path, name, language, size_bytes, line_count, weight,
                   base_weight, evidence_weight, usage_count, pass_count, fail_count,
                   tags_json, updated_at
            FROM script_registry
            WHERE {' AND '.join(clauses)}
            ORDER BY weight DESC, updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if key != "tags_json"},
                "tags": json.loads(row["tags_json"] or "[]"),
            }
            for row in rows
        ]
    finally:
        conn.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Aegis weighted script registry")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="ingest every script under the configured roots")
    ingest.add_argument("--root", action="append", default=[], help="root to scan; may be repeated")
    ingest.add_argument("--db-url", default=None)
    ingest.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help="show registry status")
    status.add_argument("--db-url", default=None)
    status.add_argument("--json", action="store_true")
    search = sub.add_parser("search", help="search weighted scripts")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--language", default="")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--db-url", default=None)
    search.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "ingest":
        roots = [Path(item) for item in args.root] if args.root else list(DEFAULT_ROOTS)
        result = ingest_scripts(roots, database_url=args.db_url)
    elif args.command == "status":
        result = registry_status(database_url=args.db_url)
    else:
        result = {"ok": True, "results": search_scripts(args.query, language=args.language, limit=args.limit, database_url=args.db_url)}

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
