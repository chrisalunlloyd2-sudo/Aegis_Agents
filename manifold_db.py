"""
Unified database manager for AEGIS.

- Centralizes engine/session creation
- Applies SQLite WAL optimizations
- Auto-migrates shared tables and columns
- Provides a single persistence layer for bridge + DIMON modules
"""

from __future__ import annotations

import base64
import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, event, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///gemini_bridge.db")

Base = declarative_base()


class NeuralManifold(Base):
    __tablename__ = "neural_manifolds"

    id = Column(Integer, primary_key=True)
    source_origin = Column(String(255))
    project = Column(String(100))
    session_id = Column(String(100))
    manifold_kind = Column(String(50), default="logic")
    ast_nodes = Column(Integer)
    structural_depth = Column(Integer)
    canonical_coords = Column(Text)
    operator_signature = Column(String(100))
    variance_score = Column(Float)
    metadata_json = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    prompt = Column(Text)
    result = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(100))
    role = Column(String(20))
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer)
    score = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ManifoldDB:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or DATABASE_URL
        connect_args: Dict[str, Any] = {"check_same_thread": False} if self.is_sqlite else {}
        self.engine = create_engine(self.db_url, connect_args=connect_args)

        if self.is_sqlite:
            event.listen(self.engine, "connect", self._set_sqlite_pragmas)

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.migrate_schema()

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    def _set_sqlite_pragmas(self, dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _get_columns(self, table_name: str) -> Dict[str, str]:
        inspector = inspect(self.engine)
        if not inspector.has_table(table_name):
            return {}
        return {
            column["name"]: str(column["type"])
            for column in inspector.get_columns(table_name)
        }

    def _add_column_if_missing(self, table_name: str, column_name: str, sql_type: str):
        existing = self._get_columns(table_name)
        if column_name in existing:
            return
        with self.engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"))

    def migrate_schema(self):
        """
        Keep shared tables aligned across modules.

        SQLite cannot do advanced ALTER operations, so this keeps the
        migration set to additive columns only.
        """
        additive_columns = {
            "neural_manifolds": {
                "project": "VARCHAR(100)",
                "session_id": "VARCHAR(100)",
                "manifold_kind": "VARCHAR(50)",
                "variance_score": "FLOAT",
                "metadata_json": "TEXT",
            },
            "conversations": {
                "timestamp": "DATETIME",
            },
            "feedback": {
                "timestamp": "DATETIME",
            },
            "tasks": {
                "timestamp": "DATETIME",
            },
        }

        for table_name, columns in additive_columns.items():
            for column_name, sql_type in columns.items():
                self._add_column_if_missing(table_name, column_name, sql_type)

    def _serialize_coords(self, canonical_coords: Any) -> str:
        if canonical_coords is None:
            return ""

        if isinstance(canonical_coords, bytes):
            return base64.b64encode(canonical_coords).decode("ascii")

        if hasattr(canonical_coords, "detach"):
            canonical_coords = canonical_coords.detach().cpu().numpy()

        if hasattr(canonical_coords, "tobytes"):
            return base64.b64encode(canonical_coords.tobytes()).decode("ascii")

        if isinstance(canonical_coords, (dict, list, tuple)):
            return json.dumps(canonical_coords)

        return str(canonical_coords)

    def persist_neural_manifold(
        self,
        *,
        source_origin: str,
        canonical_coords: Any,
        operator_signature: str,
        ast_nodes: int = 0,
        structural_depth: int = 0,
        variance_score: Optional[float] = None,
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        manifold_kind: str = "logic",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        recorded_at = datetime.utcnow()
        payload_metadata = dict(metadata or {})
        payload_metadata.setdefault("operator_signature", operator_signature)
        payload_metadata.setdefault("operator_signature_timestamp", recorded_at.isoformat())
        record = NeuralManifold(
            source_origin=source_origin,
            project=project,
            session_id=session_id,
            manifold_kind=manifold_kind,
            ast_nodes=ast_nodes,
            structural_depth=structural_depth,
            canonical_coords=self._serialize_coords(canonical_coords),
            operator_signature=operator_signature,
            variance_score=variance_score,
            metadata_json=json.dumps(payload_metadata),
            timestamp=recorded_at,
        )
        with self.session_scope() as session:
            session.add(record)
            session.flush()
            return int(record.id)

    def record_conversation(self, *, session_id: str, role: str, content: str) -> int:
        record = Conversation(session_id=session_id, role=role, content=content, timestamp=datetime.utcnow())
        with self.session_scope() as session:
            session.add(record)
            session.flush()
            return int(record.id)

    def record_feedback(self, *, message_id: int, score: int) -> int:
        record = Feedback(message_id=message_id, score=score, timestamp=datetime.utcnow())
        with self.session_scope() as session:
            session.add(record)
            session.flush()
            return int(record.id)

    def status(self) -> Dict[str, Any]:
        if self.is_sqlite:
            target = self.db_url.replace("sqlite:///", "")
        else:
            target = "remote-managed-db"
        return {
            "backend": "sqlite" if self.is_sqlite else "sqlalchemy-remote",
            "target": target,
            "wal_enabled": self.is_sqlite,
        }


manifold_db = ManifoldDB()
SessionLocal = manifold_db.SessionLocal
engine = manifold_db.engine
