from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pypdf import PdfReader

from vector_memory import vector_memory


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "gemini_bridge.db"
STATE_DIR = ROOT / "system_twin" / "knowledge_library"
MANIFEST_PATH = STATE_DIR / "manifest.json"

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 35
DEFAULT_CHUNK_CHARS = 1700
DEFAULT_CHUNK_OVERLAP = 220
DEFAULT_MAX_CHUNKS_PER_SOURCE = 80


@dataclass(frozen=True)
class LibrarySource:
    domain: str
    title: str
    url: str
    source_type: str
    license_hint: str = ""


DEFAULT_SOURCES: List[LibrarySource] = [
    LibrarySource("logic", "Stanford Encyclopedia of Philosophy: Logic and Ontology", "https://plato.stanford.edu/entries/logic-ontology/", "html", "academic_reference"),
    LibrarySource("logic", "Stanford Encyclopedia of Philosophy: Set Theory", "https://plato.stanford.edu/entries/set-theory/", "html", "academic_reference"),
    LibrarySource("logic", "Open Logic Project", "https://openlogicproject.org/", "html", "open_textbook"),
    LibrarySource("logic", "Open Logic Textbook PDF", "https://builds.openlogicproject.org/open-logic-text.pdf", "pdf", "open_textbook"),
    LibrarySource("math", "MIT OCW Mathematics", "https://ocw.mit.edu/courses/mathematics/", "html", "course_material"),
    LibrarySource("math", "NIST/SEMATECH Engineering Statistics Handbook", "https://www.itl.nist.gov/div898/handbook/", "html", "gov_reference"),
    LibrarySource("math", "OpenStax Precalculus 2e", "https://openstax.org/details/books/precalculus-2e", "html", "open_textbook"),
    LibrarySource("math", "OpenStax Calculus Volume 1", "https://openstax.org/details/books/calculus-volume-1", "html", "open_textbook"),
    LibrarySource("statistics", "OpenStax Introductory Statistics", "https://openstax.org/details/books/introductory-statistics", "html", "open_textbook"),
    LibrarySource("statistics", "StatLect Probability and Statistics", "https://www.statlect.com/", "html", "reference"),
    LibrarySource("stem", "Wikipedia: Scientific Method", "https://en.wikipedia.org/wiki/Scientific_method", "html", "reference"),
    LibrarySource("stem", "Khan Academy Science", "https://www.khanacademy.org/science", "html", "learning_reference"),
    LibrarySource("c", "cppreference C language", "https://en.cppreference.com/w/c", "html", "language_reference"),
    LibrarySource("c", "ISO C draft N1570", "https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf", "pdf", "standard_draft"),
    LibrarySource("c", "GNU C Manual", "https://www.gnu.org/software/gnu-c-manual/gnu-c-manual.html", "html", "manual"),
    LibrarySource("rust", "The Rust Programming Language", "https://doc.rust-lang.org/book/", "html", "official_book"),
    LibrarySource("rust", "The Rust Reference", "https://doc.rust-lang.org/reference/", "html", "official_reference"),
    LibrarySource("rust", "Rust by Example", "https://doc.rust-lang.org/rust-by-example/", "html", "official_examples"),
    LibrarySource("java", "Java Language Specification", "https://docs.oracle.com/javase/specs/jls/se21/html/index.html", "html", "official_spec"),
    LibrarySource("java", "Java Tutorials", "https://docs.oracle.com/javase/tutorial/", "html", "official_tutorial"),
    LibrarySource("java", "OpenJDK Documentation", "https://openjdk.org/guide/", "html", "official_reference"),
    LibrarySource("python", "Python Language Reference", "https://docs.python.org/3/reference/index.html", "html", "official_reference"),
    LibrarySource("python", "Python Library Reference", "https://docs.python.org/3/library/index.html", "html", "official_reference"),
    LibrarySource("cs", "MIT OCW Intro to Algorithms", "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/", "html", "course_material"),
    LibrarySource("cs", "CS61B Data Structures", "https://sp24.datastructur.es/", "html", "course_material"),
    LibrarySource("cs", "CS 188 Intro to AI", "https://inst.eecs.berkeley.edu/~cs188/sp24/", "html", "course_material"),
    LibrarySource("cs", "RFC Editor Index", "https://www.rfc-editor.org/rfc-index.html", "html", "standards_index"),
    LibrarySource("proofs", "Lean Theorem Prover Documentation", "https://lean-lang.org/learn/", "html", "official_docs"),
    LibrarySource("proofs", "Coq Documentation", "https://coq.inria.fr/documentation", "html", "official_docs"),
    LibrarySource("discrete_math", "Discrete Mathematics Open Textbook", "https://discrete.openmathbooks.org/dmoi3.html", "html", "open_textbook"),
]


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_tables() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_library_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                license_hint TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_library_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                project TEXT NOT NULL,
                source_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                details_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_library_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                http_status INTEGER,
                content_type TEXT,
                byte_count INTEGER,
                text_char_count INTEGER,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                fetched_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES knowledge_library_sources(id)
            );

            CREATE TABLE IF NOT EXISTS knowledge_library_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                content TEXT NOT NULL,
                vector_memory_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source_id, content_hash),
                FOREIGN KEY(source_id) REFERENCES knowledge_library_sources(id)
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_library_sources_domain
                ON knowledge_library_sources(domain, enabled);
            CREATE INDEX IF NOT EXISTS idx_knowledge_library_chunks_source
                ON knowledge_library_chunks(source_id, chunk_index);
            """
        )
        conn.commit()


def seed_sources() -> Dict[str, int]:
    ensure_tables()
    now = _utc_now()
    inserted = 0
    updated = 0
    with _connect() as conn:
        for src in DEFAULT_SOURCES:
            existing = conn.execute(
                "SELECT id FROM knowledge_library_sources WHERE url=?",
                (src.url,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE knowledge_library_sources
                    SET domain=?, title=?, source_type=?, license_hint=?, updated_at=?, enabled=1
                    WHERE id=?
                    """,
                    (src.domain, src.title, src.source_type, src.license_hint, now, int(existing["id"])),
                )
                updated += 1
                continue
            conn.execute(
                """
                INSERT INTO knowledge_library_sources
                (domain, title, url, source_type, license_hint, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (src.domain, src.title, src.url, src.source_type, src.license_hint, now, now),
            )
            inserted += 1
        conn.commit()
    return {"inserted": inserted, "updated": updated, "total_seed": len(DEFAULT_SOURCES)}


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_html_text(raw_bytes: bytes) -> str:
    decoded = raw_bytes.decode("utf-8", errors="replace")
    decoded = re.sub(r"(?is)<script.*?>.*?</script>", " ", decoded)
    decoded = re.sub(r"(?is)<style.*?>.*?</style>", " ", decoded)
    decoded = re.sub(r"(?i)</(p|div|section|article|h1|h2|h3|h4|h5|h6|li|tr|br)>", "\n", decoded)
    decoded = re.sub(r"(?is)<[^>]+>", " ", decoded)
    decoded = unescape(decoded)
    return _normalize_text(decoded)


def _extract_pdf_text(raw_bytes: bytes, max_pages: int = 400) -> str:
    reader = PdfReader(BytesIO(raw_bytes))
    pages: List[str] = []
    for idx, page in enumerate(reader.pages):
        if idx >= max_pages:
            break
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            pages.append(page_text)
    return _normalize_text("\n\n".join(pages))


def _detect_type(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct or url.lower().endswith(".pdf"):
        return "pdf"
    if "html" in ct or "text/" in ct:
        return "html"
    return "binary"


def _fetch(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> Tuple[int, str, bytes]:
    headers = {
        "User-Agent": "AegisKnowledgeIndexer/1.0 (+local scientific ingestion)",
        "Accept": "text/html,application/pdf,text/plain,*/*",
    }
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=timeout_seconds) as res:
        status = int(getattr(res, "status", 200) or 200)
        content_type = str(res.headers.get("Content-Type", ""))
        chunks: List[bytes] = []
        total = 0
        while True:
            block = res.read(1024 * 128)
            if not block:
                break
            total += len(block)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f"download exceeded max bytes ({MAX_DOWNLOAD_BYTES})")
            chunks.append(block)
        return status, content_type, b"".join(chunks)


def _chunk_text(text: str, target_chars: int = DEFAULT_CHUNK_CHARS, overlap_chars: int = DEFAULT_CHUNK_OVERLAP) -> List[str]:
    if not text:
        return []
    paras = [item.strip() for item in text.split("\n\n") if item.strip()]
    chunks: List[str] = []
    current = ""
    for para in paras:
        if not current:
            current = para
            continue
        if len(current) + len(para) + 2 <= target_chars:
            current = f"{current}\n\n{para}"
            continue
        chunks.append(current.strip())
        carry = current[-overlap_chars:] if overlap_chars > 0 else ""
        current = f"{carry}\n\n{para}".strip()
    if current.strip():
        chunks.append(current.strip())
    return [item for item in chunks if len(item) >= 120]


def _source_rows(max_sources: Optional[int] = None) -> List[sqlite3.Row]:
    ensure_tables()
    limit_sql = ""
    params: List[Any] = []
    if max_sources and max_sources > 0:
        limit_sql = " LIMIT ?"
        params.append(int(max_sources))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, domain, title, url, source_type, license_hint
            FROM knowledge_library_sources
            WHERE enabled=1
            ORDER BY domain, id
            {limit_sql}
            """,
            params,
        ).fetchall()
    return rows


def ingest_library(
    *,
    project: str = "general",
    max_sources: Optional[int] = None,
    max_chunks_per_source: int = DEFAULT_MAX_CHUNKS_PER_SOURCE,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    ensure_tables()
    seed_sources()
    sources = _source_rows(max_sources=max_sources)
    run_id = f"knowledge_{int(time.time())}"
    started = time.time()
    success_count = 0
    failed_count = 0
    total_chunks = 0
    details: List[Dict[str, Any]] = []
    now = _utc_now()

    with _connect() as conn:
        for row in sources:
            source_id = int(row["id"])
            domain = str(row["domain"])
            title = str(row["title"])
            url = str(row["url"])
            parsed_domain = urlparse(url).netloc.lower()
            doc_result: Dict[str, Any] = {
                "source_id": source_id,
                "domain": domain,
                "title": title,
                "url": url,
                "status": "failed",
                "chunks": 0,
            }
            try:
                http_status, content_type, raw = _fetch(url, timeout_seconds=timeout_seconds)
                detected_type = _detect_type(url, content_type)
                if detected_type == "pdf":
                    text = _extract_pdf_text(raw)
                elif detected_type == "html":
                    text = _extract_html_text(raw)
                else:
                    raise RuntimeError(f"unsupported content type: {content_type}")

                if len(text) < 400:
                    raise RuntimeError(f"extracted text too short ({len(text)} chars)")

                chunks = _chunk_text(text)
                if max_chunks_per_source > 0:
                    chunks = chunks[:max_chunks_per_source]

                inserted_chunks = 0
                for idx, chunk in enumerate(chunks):
                    content_hash = hashlib.sha256(f"{url}\n{chunk}".encode("utf-8", errors="ignore")).hexdigest()
                    existing_chunk = conn.execute(
                        "SELECT id, vector_memory_id FROM knowledge_library_chunks WHERE source_id=? AND content_hash=?",
                        (source_id, content_hash),
                    ).fetchone()
                    if existing_chunk:
                        continue
                    vector_text = (
                        f"SOURCE TITLE: {title}\n"
                        f"SOURCE URL: {url}\n"
                        f"SOURCE DOMAIN: {parsed_domain}\n"
                        f"KNOWLEDGE DOMAIN: {domain}\n"
                        f"CONTENT CHUNK:\n{chunk}"
                    )
                    vector_id = vector_memory.store(
                        vector_text,
                        project=project,
                        session_id=f"knowledge-library:{domain}",
                        subject="knowledge_library",
                        kind=domain,
                        role="reference",
                        metadata={
                            "title": title,
                            "url": url,
                            "source_domain": parsed_domain,
                            "domain": domain,
                            "chunk_index": idx,
                            "run_id": run_id,
                        },
                    )
                    conn.execute(
                        """
                        INSERT INTO knowledge_library_chunks
                        (source_id, chunk_index, content_hash, content, vector_memory_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (source_id, idx, content_hash, chunk, vector_id, _utc_now()),
                    )
                    inserted_chunks += 1

                conn.execute(
                    """
                    INSERT INTO knowledge_library_documents
                    (run_id, source_id, status, http_status, content_type, byte_count, text_char_count, chunk_count, error, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        run_id,
                        source_id,
                        "ok",
                        http_status,
                        content_type,
                        len(raw),
                        len(text),
                        inserted_chunks,
                        _utc_now(),
                    ),
                )
                conn.commit()

                success_count += 1
                total_chunks += inserted_chunks
                doc_result.update(
                    {
                        "status": "ok",
                        "http_status": http_status,
                        "content_type": content_type,
                        "detected_type": detected_type,
                        "chars": len(text),
                        "chunks": inserted_chunks,
                    }
                )
            except (HTTPError, URLError, RuntimeError, ValueError) as exc:
                conn.execute(
                    """
                    INSERT INTO knowledge_library_documents
                    (run_id, source_id, status, http_status, content_type, byte_count, text_char_count, chunk_count, error, fetched_at)
                    VALUES (?, ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?)
                    """,
                    (run_id, source_id, "failed", str(exc), _utc_now()),
                )
                conn.commit()
                failed_count += 1
                doc_result["error"] = str(exc)
            details.append(doc_result)

        duration_ms = int((time.time() - started) * 1000)
        conn.execute(
            """
            INSERT INTO knowledge_library_runs
            (run_id, project, source_count, success_count, failed_count, chunk_count, started_at, finished_at, duration_ms, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project,
                len(sources),
                success_count,
                failed_count,
                total_chunks,
                now,
                _utc_now(),
                duration_ms,
                json.dumps(details, ensure_ascii=False),
            ),
        )
        conn.commit()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "project": project,
        "source_count": len(sources),
        "success_count": success_count,
        "failed_count": failed_count,
        "chunk_count": total_chunks,
        "duration_ms": int((time.time() - started) * 1000),
        "timestamp": _utc_now(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return manifest


def status() -> Dict[str, Any]:
    ensure_tables()
    with _connect() as conn:
        source_count = int(conn.execute("SELECT COUNT(*) FROM knowledge_library_sources WHERE enabled=1").fetchone()[0])
        chunk_count = int(conn.execute("SELECT COUNT(*) FROM knowledge_library_chunks").fetchone()[0])
        run_row = conn.execute(
            """
            SELECT run_id, project, source_count, success_count, failed_count, chunk_count, started_at, finished_at, duration_ms
            FROM knowledge_library_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        domain_rows = conn.execute(
            """
            SELECT s.domain, COUNT(c.id) AS chunk_count
            FROM knowledge_library_sources s
            LEFT JOIN knowledge_library_chunks c ON c.source_id = s.id
            WHERE s.enabled=1
            GROUP BY s.domain
            ORDER BY chunk_count DESC, s.domain
            """
        ).fetchall()

    latest_run = dict(run_row) if run_row else None
    return {
        "db_path": str(DB_PATH),
        "manifest_path": str(MANIFEST_PATH),
        "enabled_sources": source_count,
        "total_chunks": chunk_count,
        "domains": [dict(row) for row in domain_rows],
        "latest_run": latest_run,
    }


def reindex_chunks_to_vector(
    *,
    project: str = "general",
    force: bool = False,
    domain: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    ensure_tables()
    inserted = 0
    skipped = 0
    failed = 0
    started = time.time()
    domain_filter = " AND s.domain = ? " if domain else ""
    params: List[Any] = [domain] if domain else []
    limit_sql = ""
    if limit and limit > 0:
        limit_sql = " LIMIT ? "
        params.append(int(limit))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.id AS chunk_id,
                c.chunk_index,
                c.content,
                c.vector_memory_id,
                s.domain,
                s.title,
                s.url
            FROM knowledge_library_chunks c
            JOIN knowledge_library_sources s ON s.id = c.source_id
            WHERE s.enabled=1
            {domain_filter}
            ORDER BY s.domain, c.id
            {limit_sql}
            """,
            params,
        ).fetchall()
        total = len(rows)
        for row in rows:
            existing_vector = str(row["vector_memory_id"] or "").strip()
            if existing_vector and not force:
                skipped += 1
                continue
            title = str(row["title"])
            url = str(row["url"])
            domain_name = str(row["domain"])
            parsed_domain = urlparse(url).netloc.lower()
            chunk_index = int(row["chunk_index"])
            content = str(row["content"])
            vector_text = (
                f"SOURCE TITLE: {title}\n"
                f"SOURCE URL: {url}\n"
                f"SOURCE DOMAIN: {parsed_domain}\n"
                f"KNOWLEDGE DOMAIN: {domain_name}\n"
                f"CONTENT CHUNK:\n{content}"
            )
            try:
                vector_id = vector_memory.store(
                    vector_text,
                    project=project,
                    session_id=f"knowledge-library:{domain_name}",
                    subject="knowledge_library",
                    kind=domain_name,
                    role="reference",
                    metadata={
                        "title": title,
                        "url": url,
                        "source_domain": parsed_domain,
                        "domain": domain_name,
                        "chunk_index": chunk_index,
                        "reindexed_at": _utc_now(),
                    },
                )
                conn.execute(
                    "UPDATE knowledge_library_chunks SET vector_memory_id=?, created_at=? WHERE id=?",
                    (vector_id, _utc_now(), int(row["chunk_id"])),
                )
                inserted += 1
            except Exception:
                failed += 1
        conn.commit()
    return {
        "project": project,
        "domain": domain or "",
        "force": bool(force),
        "total_considered": total,
        "inserted": inserted,
        "skipped": skipped,
        "failed": failed,
        "duration_ms": int((time.time() - started) * 1000),
    }


def search(
    query: str,
    *,
    project: str = "general",
    limit: int = 8,
    domain: Optional[str] = None,
) -> List[Dict[str, Any]]:
    kind = domain.strip().lower() if domain else None
    return vector_memory.search(
        query,
        project=project,
        subject="knowledge_library",
        kind=kind,
        limit=max(1, min(limit, 24)),
    )
