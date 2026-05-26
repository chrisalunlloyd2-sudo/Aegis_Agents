"""
Recursive context distillation for AEGIS project lanes.

This creates lean, project-scoped "directory signature" summaries so the
retrieval path can look at high-signal summaries before drilling into the
underlying files.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from dimon_mionet_logic import DIMONLogicEngine
from hash_utils import build_hash_record, utc_now_iso
from timescale_memory import memory as timescale_memory
from vector_memory import vector_memory


TOKEN_RE = re.compile(r"[A-Za-z0-9_]{4,}")


class RecursiveContextDistiller:
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path) if base_path else timescale_memory.base_path / "directory_signatures"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.logic_engine = DIMONLogicEngine()

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _infer_subject(self, file_path: Path) -> str:
        parts = file_path.parts
        if "projects" in parts:
            idx = parts.index("projects")
            if len(parts) > idx + 2:
                return parts[idx + 2]
        return file_path.parent.name

    def _keywords(self, text: str, limit: int = 12) -> List[str]:
        counts: Dict[str, int] = defaultdict(int)
        for token in TOKEN_RE.findall(text.lower()):
            counts[token] += 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [token for token, _count in ranked[:limit]]

    def _record_path(self, project: str, subject: str) -> Path:
        project_dir = self.base_path / project
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / f"{subject}.json"

    def build_project_signatures(self, project: str, limit_files: int = 24) -> List[Dict]:
        file_paths = list(timescale_memory.index.get("projects", {}).get(project, []))[-limit_files:]
        if not file_paths:
            return []

        grouped: Dict[str, List[Path]] = defaultdict(list)
        for entry in file_paths:
            path = Path(entry)
            grouped[self._infer_subject(path)].append(path)

        records = []
        for subject, paths in grouped.items():
            snippets = []
            for file_path in paths[-limit_files:]:
                content = self._safe_read(file_path)[:320]
                if content:
                    snippets.append(f"[{file_path.name}] {content}")

            if not snippets:
                continue

            summary_text = "\n".join(snippets[:12])
            keywords = self._keywords(summary_text)
            signature_input = (
                f"Project: {project}\n"
                f"Subject: {subject}\n"
                f"Files: {len(paths)}\n"
                f"Keywords: {', '.join(keywords)}\n"
                f"Summary:\n{summary_text}"
            )
            input_embedding = vector_memory.manifold_embed(signature_input)
            manifold = self.logic_engine.distill_directory_signature(
                source_name=f"DIRSIG::{project}::{subject}",
                summary_text=signature_input,
                input_embedding=input_embedding,
                project=project,
            )

            recorded_at = utc_now_iso()
            content_hash_record = build_hash_record(signature_input, recorded_at=recorded_at)
            record = {
                "project": project,
                "subject": subject,
                "updated_at": recorded_at,
                "file_count": len(paths),
                "keywords": keywords,
                "summary": summary_text[:1800],
                **content_hash_record,
                "signature": manifold.get("signature"),
                "signature_timestamp": recorded_at,
                "variance_score": manifold.get("variance_score"),
            }

            self._record_path(project, subject).write_text(json.dumps(record, indent=2), encoding="utf-8")
            vector_memory.store(
                f"Directory signature for {project}/{subject}\nKeywords: {', '.join(keywords)}\n{summary_text[:1200]}",
                memory_id=f"dirsig::{project}::{subject}",
                project=project,
                session_id=f"dirsig::{project}",
                subject=subject,
                kind="directory_signature",
                role="system",
                metadata={
                    "signature": manifold.get("signature"),
                    "signature_timestamp": recorded_at,
                    "variance_score": manifold.get("variance_score"),
                    "file_count": len(paths),
                    **content_hash_record,
                },
            )
            records.append(record)

        return records

    def search_signatures(self, query: str, project: str, limit: int = 3) -> List[Dict]:
        return vector_memory.search(query, project=project, kind="directory_signature", limit=limit)

    def recent_signatures(self, project: str, limit: int = 6) -> List[Dict]:
        project_dir = self.base_path / project
        if not project_dir.exists():
            return []

        records = []
        for record_path in sorted(project_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                records.append(json.loads(record_path.read_text(encoding="utf-8")))
            except Exception:
                continue
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return records[:limit]


context_distiller = RecursiveContextDistiller()
