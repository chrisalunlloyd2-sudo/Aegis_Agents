"""
Hybrid vector memory for AEGIS.

- Cloud-first PostgreSQL/pgvector retrieval when configured
- Persistent local Qdrant failover storage
- Semantic embeddings via Ollama nomic-embed-text when available
- Deterministic lexical hash vectors as an always-on fallback
- Project-aware filtering for multi-project programming work
"""

import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import ollama
from dotenv import load_dotenv
from hash_utils import merge_hash_metadata, utc_now_iso
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    VectorParams,
)

try:
    import psycopg2
    from psycopg2 import pool
except Exception:
    psycopg2 = None
    pool = None

load_dotenv()

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
LEXICAL_VECTOR_SIZE = 64
SEMANTIC_VECTOR_SIZE = 768
SEMANTIC_MODEL = "nomic-embed-text"
SEMANTIC_KEEP_ALIVE = os.getenv("AEGIS_OLLAMA_EMBED_KEEP_ALIVE", "2m").strip() or "2m"
LOCAL_ONLY_VECTOR = os.getenv("AEGIS_FORCE_LOCAL_VECTOR", "0").strip().lower() in {"1", "true", "yes", "on"}
CLOUD_DSN_ENV_KEYS = (
    "AEGIS_CLOUD_VECTOR_DSN",
    "PGVECTOR_DATABASE_URL",
    "VECTOR_DATABASE_URL",
)


def lexical_embed(text: str) -> List[float]:
    vector = [0.0] * LEXICAL_VECTOR_SIZE
    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector

    for token in tokens:
        vector[hash(token) % LEXICAL_VECTOR_SIZE] += 1.0

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def expand_lexical_vector(vector: Sequence[float]) -> List[float]:
    if not vector:
        return [0.0] * SEMANTIC_VECTOR_SIZE

    repeats = math.ceil(SEMANTIC_VECTOR_SIZE / len(vector))
    expanded = list(vector) * repeats
    expanded = expanded[:SEMANTIC_VECTOR_SIZE]
    norm = math.sqrt(sum(value * value for value in expanded)) or 1.0
    return [value / norm for value in expanded]


def resolve_cloud_dsn() -> Optional[str]:
    if LOCAL_ONLY_VECTOR:
        return None
    for key in CLOUD_DSN_ENV_KEYS:
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return None


def redact_dsn(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    host = parsed.hostname or "unknown-host"
    database = parsed.path.lstrip("/") or "unknown-db"
    return f"{parsed.scheme}://{host}/{database}"


def format_vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


def build_payload(
    memory_id: str,
    text: str,
    *,
    project: str,
    session_id: str,
    subject: str,
    kind: str,
    role: str,
    metadata: Optional[Dict],
) -> Dict:
    clean_text = text.strip()
    recorded_at = utc_now_iso()
    payload_metadata = merge_hash_metadata(metadata, clean_text, recorded_at=recorded_at)
    return {
        "memory_id": memory_id,
        "project": project or "general",
        "session_id": session_id,
        "subject": subject,
        "kind": kind,
        "role": role,
        "timestamp": recorded_at,
        "content": clean_text,
        "content_hash": payload_metadata["content_hash"],
        "metadata": payload_metadata,
    }


class LocalQdrantVectorBackend:
    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else Path(__file__).resolve().parent / "vector_memory_db"
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.semantic_collection = "aegis_semantic_memory"
        self.lexical_collection = "aegis_lexical_memory"
        self.semantic_backend = "ollama"
        self.semantic_available = True
        self.persistent = True
        self.quantization_enabled = False
        self.quantization_type = "int8"
        self.fallback_reason = None

        try:
            self.client = QdrantClient(path=str(self.storage_path))
            self.backend = "qdrant-local"
        except RuntimeError as exc:
            self.client = QdrantClient(":memory:")
            self.backend = "qdrant-session-fallback"
            self.persistent = False
            self.fallback_reason = str(exc)

        self._ensure_collection(self.lexical_collection, LEXICAL_VECTOR_SIZE)
        self._ensure_collection(self.semantic_collection, SEMANTIC_VECTOR_SIZE)

    def _quantization_config(self) -> ScalarQuantization:
        return ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                quantile=0.99,
                always_ram=False,
            )
        )

    def _ensure_collection(self, name: str, vector_size: int):
        existing = {item.name for item in self.client.get_collections().collections}
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        try:
            self.client.update_collection(
                collection_name=name,
                quantization_config=self._quantization_config(),
            )
            self.quantization_enabled = True
        except Exception:
            self.quantization_enabled = False

    def _embed_semantic(self, text: str) -> Optional[List[float]]:
        try:
            response = ollama.embeddings(
                model=SEMANTIC_MODEL,
                prompt=text,
                keep_alive=SEMANTIC_KEEP_ALIVE,
            )
            embedding = response.get("embedding")
            if not embedding or len(embedding) != SEMANTIC_VECTOR_SIZE:
                return None
            self.semantic_available = True
            self.semantic_backend = f"ollama:{SEMANTIC_MODEL}"
            return embedding
        except Exception:
            self.semantic_available = False
            self.semantic_backend = "unavailable"
            return None

    def manifold_embed(self, text: str) -> List[float]:
        semantic = self._embed_semantic(text)
        if semantic is not None:
            return semantic
        return expand_lexical_vector(lexical_embed(text))

    def _build_filter(
        self,
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Optional[Filter]:
        conditions = []
        if project:
            conditions.append(FieldCondition(key="project", match=MatchValue(value=project)))
        if session_id:
            conditions.append(FieldCondition(key="session_id", match=MatchValue(value=session_id)))
        if subject:
            conditions.append(FieldCondition(key="subject", match=MatchValue(value=subject)))
        if kind:
            conditions.append(FieldCondition(key="kind", match=MatchValue(value=kind)))
        if not conditions:
            return None
        return Filter(must=conditions)

    def _normalize_point_id(self, memory_id: Optional[str]) -> str:
        if not memory_id:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(str(memory_id)))
        except (ValueError, TypeError, AttributeError):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(memory_id)))

    def store(
        self,
        text: str,
        *,
        project: str = "general",
        session_id: str = "default",
        subject: str = "chat",
        kind: str = "chat",
        role: str = "user",
        metadata: Optional[Dict] = None,
        memory_id: Optional[str] = None,
    ) -> Optional[str]:
        clean_text = text.strip()
        if not clean_text:
            return None

        memory_id = self._normalize_point_id(memory_id)
        payload = build_payload(
            memory_id,
            clean_text,
            project=project,
            session_id=session_id,
            subject=subject,
            kind=kind,
            role=role,
            metadata=metadata,
        )

        lexical_point = PointStruct(
            id=memory_id,
            vector=lexical_embed(clean_text),
            payload=payload,
        )
        self.client.upsert(collection_name=self.lexical_collection, points=[lexical_point])

        semantic_point = PointStruct(
            id=memory_id,
            vector=self.manifold_embed(clean_text),
            payload=payload,
        )
        self.client.upsert(collection_name=self.semantic_collection, points=[semantic_point])

        return memory_id

    def search(
        self,
        query: str,
        *,
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 6,
    ) -> List[Dict]:
        clean_query = query.strip()
        if not clean_query:
            return []

        query_filter = self._build_filter(project=project, session_id=session_id, subject=subject, kind=kind)
        lexical_hits = self.client.search(
            collection_name=self.lexical_collection,
            query_vector=lexical_embed(clean_query),
            query_filter=query_filter,
            limit=limit,
        )

        merged: Dict[str, Dict] = {}
        for hit in lexical_hits:
            payload = hit.payload or {}
            merged[str(hit.id)] = {
                "memory_id": str(hit.id),
                "score": float(hit.score) * 0.35,
                "source": "lexical",
                **payload,
            }

        semantic_hits = self.client.search(
            collection_name=self.semantic_collection,
            query_vector=self.manifold_embed(clean_query),
            query_filter=query_filter,
            limit=limit,
        )
        for hit in semantic_hits:
            payload = hit.payload or {}
            memory_id = str(hit.id)
            weighted_score = float(hit.score)
            if memory_id in merged:
                merged[memory_id]["score"] += weighted_score
                merged[memory_id]["source"] = "hybrid"
            else:
                merged[memory_id] = {
                    "memory_id": memory_id,
                    "score": weighted_score,
                    "source": "semantic",
                    **payload,
                }

        results = sorted(merged.values(), key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def project_stats(self, project: str) -> Dict:
        query_filter = self._build_filter(project=project)
        lexical_count = self.client.count(
            collection_name=self.lexical_collection,
            count_filter=query_filter,
            exact=True,
        ).count
        semantic_count = self.client.count(
            collection_name=self.semantic_collection,
            count_filter=query_filter,
            exact=True,
        ).count
        return {
            "project": project,
            "lexical_points": lexical_count,
            "semantic_points": semantic_count,
        }

    def recent_project_memories(self, project: str, limit: int = 8) -> List[Dict]:
        query_filter = self._build_filter(project=project)
        records, _ = self.client.scroll(
            collection_name=self.lexical_collection,
            scroll_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        items = []
        for record in records:
            payload = record.payload or {}
            items.append(
                {
                    "memory_id": str(record.id),
                    "project": payload.get("project"),
                    "session_id": payload.get("session_id"),
                    "subject": payload.get("subject"),
                    "kind": payload.get("kind"),
                    "role": payload.get("role"),
                    "timestamp": payload.get("timestamp"),
                    "content": payload.get("content", ""),
                    "metadata": payload.get("metadata", {}),
                }
            )
        items.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
        return items[:limit]

    def count(self) -> Dict[str, int]:
        lexical_count = self.client.count(self.lexical_collection, exact=True).count
        semantic_count = self.client.count(self.semantic_collection, exact=True).count
        return {
            "lexical_points": lexical_count,
            "semantic_points": semantic_count,
        }

    def status(self) -> Dict:
        counts = self.count()
        return {
            "backend": self.backend,
            "persistent": self.persistent,
            "path": str(self.storage_path),
            "semantic_backend": self.semantic_backend,
            "semantic_available": self.semantic_available,
            "quantization_enabled": self.quantization_enabled,
            "quantization_type": self.quantization_type if self.quantization_enabled else "disabled",
            "fallback_reason": self.fallback_reason,
            **counts,
        }


class PostgresVectorBackend:
    def __init__(self, dsn: str):
        if not psycopg2 or not pool:
            raise RuntimeError("psycopg2 is required for cloud pgvector support")

        self.dsn = dsn
        self.backend = "pgvector-postgres"
        self.pool = pool.ThreadedConnectionPool(1, 4, dsn)
        self.last_error = None
        self._initialize_schema()

    def _get_connection(self):
        return self.pool.getconn()

    def _put_connection(self, connection) -> None:
        self.pool.putconn(connection)

    def _initialize_schema(self) -> None:
        connection = self._get_connection()
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aegis_vector_memories (
                        memory_id UUID PRIMARY KEY,
                        project TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        role TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        content TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        lexical_vector vector(64) NOT NULL,
                        semantic_vector vector(768) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_aegis_vector_lookup
                    ON aegis_vector_memories (project, subject, kind, timestamp DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_aegis_vector_session
                    ON aegis_vector_memories (session_id, timestamp DESC)
                    """
                )
                try:
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_aegis_vector_lexical_hnsw
                        ON aegis_vector_memories
                        USING hnsw (lexical_vector vector_cosine_ops)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_aegis_vector_semantic_hnsw
                        ON aegis_vector_memories
                        USING hnsw (semantic_vector vector_cosine_ops)
                        """
                    )
                except Exception:
                    pass
        finally:
            connection.autocommit = False
            self._put_connection(connection)

    def _filter_sql(
        self,
        *,
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Tuple[str, List]:
        clauses = []
        params: List = []
        if project:
            clauses.append("project = %s")
            params.append(project)
        if session_id:
            clauses.append("session_id = %s")
            params.append(session_id)
        if subject:
            clauses.append("subject = %s")
            params.append(subject)
        if kind:
            clauses.append("kind = %s")
            params.append(kind)
        if not clauses:
            return "", params
        return " AND " + " AND ".join(clauses), params

    def store(
        self,
        payload: Dict,
        lexical_vector: Sequence[float],
        semantic_vector: Sequence[float],
    ) -> str:
        connection = self._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO aegis_vector_memories (
                        memory_id,
                        project,
                        session_id,
                        subject,
                        kind,
                        role,
                        timestamp,
                        content,
                        content_hash,
                        metadata,
                        lexical_vector,
                        semantic_vector
                    ) VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s::vector,
                        %s::vector
                    )
                    ON CONFLICT (memory_id) DO UPDATE SET
                        project = EXCLUDED.project,
                        session_id = EXCLUDED.session_id,
                        subject = EXCLUDED.subject,
                        kind = EXCLUDED.kind,
                        role = EXCLUDED.role,
                        timestamp = EXCLUDED.timestamp,
                        content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash,
                        metadata = EXCLUDED.metadata,
                        lexical_vector = EXCLUDED.lexical_vector,
                        semantic_vector = EXCLUDED.semantic_vector
                    """,
                    (
                        payload["memory_id"],
                        payload["project"],
                        payload["session_id"],
                        payload["subject"],
                        payload["kind"],
                        payload["role"],
                        payload["timestamp"],
                        payload["content"],
                        payload["content_hash"],
                        json.dumps(payload["metadata"]),
                        format_vector_literal(lexical_vector),
                        format_vector_literal(semantic_vector),
                    ),
                )
            connection.commit()
            self.last_error = None
            return payload["memory_id"]
        except Exception as exc:
            connection.rollback()
            self.last_error = str(exc)
            raise
        finally:
            self._put_connection(connection)

    def _run_ranked_search(
        self,
        *,
        column: str,
        vector_literal: str,
        project: Optional[str],
        session_id: Optional[str],
        subject: Optional[str],
        kind: Optional[str],
        limit: int,
    ) -> List[Dict]:
        filter_sql, filter_params = self._filter_sql(
            project=project,
            session_id=session_id,
            subject=subject,
            kind=kind,
        )
        connection = self._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        memory_id::text,
                        project,
                        session_id,
                        subject,
                        kind,
                        role,
                        timestamp,
                        content,
                        metadata,
                        1 - ({column} <=> %s::vector) AS score
                    FROM aegis_vector_memories
                    WHERE {column} IS NOT NULL
                    {filter_sql}
                    ORDER BY {column} <=> %s::vector
                    LIMIT %s
                    """,
                    [vector_literal, *filter_params, vector_literal, limit],
                )
                rows = cursor.fetchall()
        finally:
            self._put_connection(connection)

        hits = []
        for row in rows:
            memory_id, hit_project, hit_session, hit_subject, hit_kind, hit_role, timestamp, content, metadata, score = row
            hits.append(
                {
                    "memory_id": memory_id,
                    "project": hit_project,
                    "session_id": hit_session,
                    "subject": hit_subject,
                    "kind": hit_kind,
                    "role": hit_role,
                    "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                    "content": content,
                    "metadata": metadata or {},
                    "score": float(score or 0.0),
                }
            )
        return hits

    def search(
        self,
        *,
        query: str,
        lexical_vector: Sequence[float],
        semantic_vector: Sequence[float],
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 6,
    ) -> List[Dict]:
        if not query.strip():
            return []

        lexical_hits = self._run_ranked_search(
            column="lexical_vector",
            vector_literal=format_vector_literal(lexical_vector),
            project=project,
            session_id=session_id,
            subject=subject,
            kind=kind,
            limit=limit,
        )
        semantic_hits = self._run_ranked_search(
            column="semantic_vector",
            vector_literal=format_vector_literal(semantic_vector),
            project=project,
            session_id=session_id,
            subject=subject,
            kind=kind,
            limit=limit,
        )

        merged: Dict[str, Dict] = {}
        for hit in lexical_hits:
            merged[hit["memory_id"]] = {
                **hit,
                "score": hit["score"] * 0.35,
                "source": "lexical",
            }
        for hit in semantic_hits:
            memory_id = hit["memory_id"]
            if memory_id in merged:
                merged[memory_id]["score"] += hit["score"]
                merged[memory_id]["source"] = "hybrid"
            else:
                merged[memory_id] = {
                    **hit,
                    "source": "semantic",
                }

        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:limit]

    def project_stats(self, project: str) -> Dict:
        connection = self._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE lexical_vector IS NOT NULL),
                        COUNT(*) FILTER (WHERE semantic_vector IS NOT NULL)
                    FROM aegis_vector_memories
                    WHERE project = %s
                    """,
                    (project,),
                )
                lexical_count, semantic_count = cursor.fetchone()
        finally:
            self._put_connection(connection)

        return {
            "project": project,
            "lexical_points": int(lexical_count or 0),
            "semantic_points": int(semantic_count or 0),
        }

    def recent_project_memories(self, project: str, limit: int = 8) -> List[Dict]:
        connection = self._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        memory_id::text,
                        project,
                        session_id,
                        subject,
                        kind,
                        role,
                        timestamp,
                        content,
                        metadata
                    FROM aegis_vector_memories
                    WHERE project = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (project, limit),
                )
                rows = cursor.fetchall()
        finally:
            self._put_connection(connection)

        items = []
        for row in rows:
            memory_id, hit_project, hit_session, hit_subject, hit_kind, hit_role, timestamp, content, metadata = row
            items.append(
                {
                    "memory_id": memory_id,
                    "project": hit_project,
                    "session_id": hit_session,
                    "subject": hit_subject,
                    "kind": hit_kind,
                    "role": hit_role,
                    "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                    "content": content,
                    "metadata": metadata or {},
                }
            )
        return items

    def count(self) -> Dict[str, int]:
        connection = self._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE lexical_vector IS NOT NULL),
                        COUNT(*) FILTER (WHERE semantic_vector IS NOT NULL)
                    FROM aegis_vector_memories
                    """
                )
                lexical_count, semantic_count = cursor.fetchone()
        finally:
            self._put_connection(connection)

        return {
            "lexical_points": int(lexical_count or 0),
            "semantic_points": int(semantic_count or 0),
        }

    def status(self) -> Dict:
        counts = self.count()
        return {
            "backend": self.backend,
            "target": redact_dsn(self.dsn),
            "last_error": self.last_error,
            **counts,
        }


class AegisVectorMemory:
    def __init__(self, storage_path: Optional[str] = None, cloud_dsn: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else Path(__file__).resolve().parent / "vector_memory_db"
        self.semantic_backend = "ollama"
        self.semantic_available = True
        self.cloud_dsn = cloud_dsn or resolve_cloud_dsn()
        self.cloud_enabled = bool(self.cloud_dsn)
        self.cloud_available = False
        self.mirror_local_writes = os.getenv("AEGIS_VECTOR_MIRROR_LOCAL", "1").strip().lower() not in {"0", "false", "no"}
        self.fallback_reason = None

        self.local_backend = LocalQdrantVectorBackend(self.storage_path)
        self.quantization_enabled = self.local_backend.quantization_enabled
        self.quantization_type = self.local_backend.quantization_type
        self.persistent = self.local_backend.persistent

        self.cloud_backend = None
        if self.cloud_enabled:
            try:
                self.cloud_backend = PostgresVectorBackend(self.cloud_dsn)
                self.cloud_available = True
            except Exception as exc:
                self.cloud_available = False
                self.fallback_reason = f"Cloud vector init failed: {exc}"

    @property
    def backend(self) -> str:
        if self.cloud_backend and self.cloud_available:
            return "hybrid-cloud-first"
        return self.local_backend.backend

    def _embed_semantic(self, text: str) -> Optional[List[float]]:
        try:
            response = ollama.embeddings(
                model=SEMANTIC_MODEL,
                prompt=text,
                keep_alive=SEMANTIC_KEEP_ALIVE,
            )
            embedding = response.get("embedding")
            if not embedding or len(embedding) != SEMANTIC_VECTOR_SIZE:
                return None
            self.semantic_available = True
            self.semantic_backend = f"ollama:{SEMANTIC_MODEL}"
            return embedding
        except Exception:
            self.semantic_available = False
            self.semantic_backend = "unavailable"
            return None

    def manifold_embed(self, text: str) -> List[float]:
        semantic = self._embed_semantic(text)
        if semantic is not None:
            return semantic
        return expand_lexical_vector(lexical_embed(text))

    def _normalize_point_id(self, memory_id: Optional[str]) -> str:
        if not memory_id:
            return str(uuid.uuid4())
        try:
            return str(uuid.UUID(str(memory_id)))
        except (ValueError, TypeError, AttributeError):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(memory_id)))

    def store(
        self,
        text: str,
        *,
        project: str = "general",
        session_id: str = "default",
        subject: str = "chat",
        kind: str = "chat",
        role: str = "user",
        metadata: Optional[Dict] = None,
        memory_id: Optional[str] = None,
    ) -> Optional[str]:
        clean_text = text.strip()
        if not clean_text:
            return None

        memory_id = self._normalize_point_id(memory_id)
        payload = build_payload(
            memory_id,
            clean_text,
            project=project,
            session_id=session_id,
            subject=subject,
            kind=kind,
            role=role,
            metadata=metadata,
        )
        lexical_vector = lexical_embed(clean_text)
        semantic_vector = self.manifold_embed(clean_text)

        cloud_write_ok = False
        local_write_ok = False
        errors = []

        if self.cloud_backend:
            try:
                self.cloud_backend.store(payload, lexical_vector, semantic_vector)
                self.cloud_available = True
                cloud_write_ok = True
            except Exception as exc:
                self.cloud_available = False
                self.fallback_reason = f"Cloud vector write failed: {exc}"
                errors.append(self.fallback_reason)

        if self.mirror_local_writes or not cloud_write_ok:
            try:
                self.local_backend.store(
                    clean_text,
                    project=project,
                    session_id=session_id,
                    subject=subject,
                    kind=kind,
                    role=role,
                    metadata=metadata,
                    memory_id=memory_id,
                )
                local_write_ok = True
            except Exception as exc:
                self.fallback_reason = f"Local vector write failed: {exc}"
                errors.append(self.fallback_reason)

        if not cloud_write_ok and not local_write_ok:
            raise RuntimeError("; ".join(errors) or "No vector backend available")

        return memory_id

    def search(
        self,
        query: str,
        *,
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 6,
    ) -> List[Dict]:
        clean_query = query.strip()
        if not clean_query:
            return []

        lexical_vector = lexical_embed(clean_query)
        semantic_vector = self.manifold_embed(clean_query)

        if self.cloud_backend:
            try:
                results = self.cloud_backend.search(
                    query=clean_query,
                    lexical_vector=lexical_vector,
                    semantic_vector=semantic_vector,
                    project=project,
                    session_id=session_id,
                    subject=subject,
                    kind=kind,
                    limit=limit,
                )
                self.cloud_available = True
                if results:
                    return results
            except Exception as exc:
                self.cloud_available = False
                self.fallback_reason = f"Cloud vector search failed: {exc}"

        return self.local_backend.search(
            clean_query,
            project=project,
            session_id=session_id,
            subject=subject,
            kind=kind,
            limit=limit,
        )

    def project_stats(self, project: str) -> Dict:
        if self.cloud_backend:
            try:
                stats = self.cloud_backend.project_stats(project)
                self.cloud_available = True
                return stats
            except Exception as exc:
                self.cloud_available = False
                self.fallback_reason = f"Cloud vector stats failed: {exc}"
        return self.local_backend.project_stats(project)

    def recent_project_memories(self, project: str, limit: int = 8) -> List[Dict]:
        if self.cloud_backend:
            try:
                records = self.cloud_backend.recent_project_memories(project, limit=limit)
                self.cloud_available = True
                if records:
                    return records
            except Exception as exc:
                self.cloud_available = False
                self.fallback_reason = f"Cloud vector recent query failed: {exc}"
        return self.local_backend.recent_project_memories(project, limit=limit)

    def count(self) -> Dict[str, int]:
        if self.cloud_backend:
            try:
                counts = self.cloud_backend.count()
                self.cloud_available = True
                return counts
            except Exception as exc:
                self.cloud_available = False
                self.fallback_reason = f"Cloud vector count failed: {exc}"
        return self.local_backend.count()

    def status(self) -> Dict:
        counts = self.count()
        local_status = self.local_backend.status()
        cloud_status = None
        if self.cloud_backend and self.cloud_available:
            try:
                cloud_status = self.cloud_backend.status()
            except Exception:
                cloud_status = {
                    "backend": "pgvector-postgres",
                    "target": redact_dsn(self.cloud_dsn),
                    "last_error": self.fallback_reason,
                }

        return {
            "backend": self.backend,
            "primary_backend": "pgvector-postgres" if self.cloud_backend and self.cloud_available else self.local_backend.backend,
            "local_only_mode": LOCAL_ONLY_VECTOR,
            "cloud_enabled": self.cloud_enabled,
            "cloud_available": self.cloud_available,
            "cloud_target": redact_dsn(self.cloud_dsn),
            "mirror_local_writes": self.mirror_local_writes,
            "persistent": self.persistent,
            "path": str(self.storage_path),
            "semantic_backend": self.semantic_backend,
            "semantic_available": self.semantic_available,
            "quantization_enabled": self.quantization_enabled,
            "quantization_type": self.quantization_type if self.quantization_enabled else "disabled",
            "fallback_reason": self.fallback_reason or local_status.get("fallback_reason"),
            "local_backend": local_status.get("backend"),
            "local_lexical_points": local_status.get("lexical_points", 0),
            "local_semantic_points": local_status.get("semantic_points", 0),
            "cloud_status": cloud_status,
            **counts,
        }

vector_memory = AegisVectorMemory()
