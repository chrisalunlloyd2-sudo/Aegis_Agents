"""
AEGIS Timescale Memory System v2.0
Optimized with deduplication and segmented indexing
- Structured human-readable records with summary, keywords, signals, and body
- 2KB max per file, 60 files per hour
- Segmented indexes (10KB max per segment)
- Deduplication to prevent repeats
- Daily secrets file for APIs/links/variables
- Weekly summaries compressed to 1KB "feelings" file
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
import re

from hash_utils import merge_hash_metadata, utc_now_iso

class TimescaleMemory:
    def __init__(self, base_path: Optional[str] = None):
        """Initialize timescale memory system"""
        self.base_path = Path(base_path) if base_path else Path(os.getenv("AEGIS_MEMORY_ROOT", str(Path.home() / "Aegis_Memory")))
        self.desktop_path = Path(os.path.expanduser("~/Desktop"))
        self.max_chunk_size = 2 * 1024  # 2KB (reduced from 5KB)
        self.max_index_size = 10 * 1024  # 10KB per index segment
        self.heartbeat_counter = 0
        self.current_hour_folder = None
        self.seen_hashes: Set[str] = set()  # Deduplication cache

        # Create base structure
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "secrets").mkdir(exist_ok=True)
        (self.base_path / "reasoning_notes").mkdir(exist_ok=True)
        (self.base_path / "weekly_summaries").mkdir(exist_ok=True)
        (self.base_path / "feelings").mkdir(exist_ok=True)
        (self.base_path / "indexes").mkdir(exist_ok=True)

        # Segmented indexes
        self.current_index_segment = 0
        self.index = self._load_current_index()
        self._load_seen_hashes()

    def _get_current_index_file(self) -> Path:
        """Get current index segment file"""
        return self.base_path / "indexes" / f"index_segment_{self.current_index_segment:04d}.json"

    def _load_current_index(self) -> Dict:
        """Load current index segment"""
        index_file = self._get_current_index_file()
        if index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data.setdefault("projects", {})
                return data
        return {"sessions": {}, "subjects": {}, "projects": {}, "keywords": {}, "file_count": 0}

    def _save_index(self):
        """Save current index segment, rotate if too large"""
        index_file = self._get_current_index_file()

        # Check size before saving
        temp_data = json.dumps(self.index, indent=2)
        if len(temp_data.encode('utf-8')) > self.max_index_size:
            # Rotate to new segment
            self.current_index_segment += 1
            self.index = {"sessions": {}, "subjects": {}, "projects": {}, "keywords": {}, "file_count": 0}
            index_file = self._get_current_index_file()

        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=2)

    def _load_seen_hashes(self):
        """Load deduplication cache from recent files"""
        # Only load hashes from last 24 hours to keep cache small
        cutoff = datetime.now() - timedelta(hours=24)
        for index_file in sorted((self.base_path / "indexes").glob("index_segment_*.json"), reverse=True)[:5]:
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Extract file paths and compute hashes
                    for files in data.get("sessions", {}).values():
                        for file_path in files[-10:]:  # Only recent files
                            if Path(file_path).exists():
                                with open(file_path, 'r', encoding='utf-8') as cf:
                                    content = cf.read()
                                    self.seen_hashes.add(hashlib.md5(content.encode()).hexdigest())
            except:
                pass

    def _content_hash(self, content: str) -> str:
        """Generate hash for deduplication"""
        return hashlib.md5(content.encode()).hexdigest()

    def _is_duplicate(self, content: str) -> bool:
        """Check if content is duplicate"""
        content_hash = self._content_hash(content)
        if content_hash in self.seen_hashes:
            return True
        self.seen_hashes.add(content_hash)
        # Keep cache size manageable
        if len(self.seen_hashes) > 1000:
            self.seen_hashes = set(list(self.seen_hashes)[-500:])
        return False

    def _sanitize_key(self, value: str) -> str:
        sanitized = re.sub(r'[^A-Za-z0-9_.-]+', '-', value.strip())
        return sanitized.strip('-') or "general"

    def _get_time_path(self, session_id: str, subject: str, project: Optional[str] = None) -> Path:
        """Generate hierarchical path: session/subject/YYYY-MM-DD/HH/"""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%H")

        clean_session = self._sanitize_key(session_id)
        clean_subject = self._sanitize_key(subject)
        if project:
            clean_project = self._sanitize_key(project)
            path = self.base_path / clean_session / "projects" / clean_project / clean_subject / date_str / hour_str
        else:
            path = self.base_path / clean_session / clean_subject / date_str / hour_str
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _normalize_text(self, text: str) -> str:
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _truncate_utf8(self, text: str, max_bytes: int) -> str:
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text
        return encoded[:max_bytes].decode('utf-8', errors='ignore').rstrip()

    def _summarize_text(self, text: str, max_chars: int = 220) -> str:
        cleaned = re.sub(r'\s+', ' ', text.strip())
        if len(cleaned) <= max_chars:
            return cleaned

        sentences = re.split(r'(?<=[.!?])\s+', cleaned)
        summary = ""
        for sentence in sentences:
            candidate = f"{summary} {sentence}".strip()
            if len(candidate) > max_chars:
                break
            summary = candidate

        if summary:
            return summary
        return cleaned[:max_chars].rstrip() + "..."

    def _extract_signals(self, text: str, limit: int = 12) -> List[str]:
        patterns = (
            r'[A-Za-z0-9_]+\s*[=<>!]+\s*[A-Za-z0-9_]+',
            r'\b(?:true|false|and|or|not|if|then|else)\b',
            r'[+\-*/&|^~<>=!]{2,}',
        )
        signals = []
        for pattern in patterns:
            for match in re.findall(pattern, text, re.IGNORECASE):
                signal = str(match).strip()
                if signal and signal not in signals:
                    signals.append(signal)
                if len(signals) >= limit:
                    return signals
        return signals

    def _extract_keywords(self, text: str, limit: int = 12) -> List[str]:
        stop_words = {
            "that", "this", "with", "from", "have", "your", "about", "there",
            "their", "would", "could", "should", "into", "when", "what", "where",
            "which", "while", "after", "before", "because", "been", "being",
        }
        keywords = []
        for token in re.findall(r'\b[A-Za-z_][A-Za-z0-9_]{3,}\b', text.lower()):
            if token in stop_words or token in keywords:
                continue
            keywords.append(token)
            if len(keywords) >= limit:
                break
        return keywords

    def _build_structured_record(
        self,
        *,
        session_id: str,
        subject: str,
        content: str,
        metadata: Optional[Dict] = None,
        project: Optional[str] = None,
    ) -> str:
        normalized = self._normalize_text(content)
        recorded_at = utc_now_iso()
        metadata_payload = merge_hash_metadata(metadata, normalized, recorded_at=recorded_at)
        keywords = ", ".join(self._extract_keywords(normalized)) or "none"
        signals = " | ".join(self._extract_signals(normalized)) or "none"
        summary = self._summarize_text(normalized, max_chars=260) or "none"
        header = [
            "AEGIS_RECORD v3",
            f"timestamp: {recorded_at}",
            f"session_id: {self._sanitize_key(session_id)}",
            f"project: {self._sanitize_key(project) if project else 'general'}",
            f"subject: {self._sanitize_key(subject)}",
            f"content_hash: {metadata_payload['content_hash']}",
            f"content_hash_algorithm: {metadata_payload['content_hash_algorithm']}",
            f"content_hash_timestamp: {metadata_payload['content_hash_timestamp']}",
            f"keywords: {keywords}",
            f"signals: {signals}",
            f"summary: {summary}",
            f"metadata: {json.dumps(metadata_payload, sort_keys=True)}",
        ]

        header_text = "\n".join(header) + "\n---\n"
        remaining_bytes = max(self.max_chunk_size - len(header_text.encode('utf-8')) - 16, 256)
        body = self._truncate_utf8(normalized, remaining_bytes)
        if body != normalized:
            body = body.rstrip() + "\n[TRUNCATED]"
        return header_text + body

    def _extract_context_excerpt(self, record_text: str, max_chars: int = 260) -> str:
        if "\n---\n" not in record_text:
            return self._summarize_text(record_text, max_chars=max_chars)

        header_text, body = record_text.split("\n---\n", 1)
        summary_match = re.search(r'^summary:\s*(.+)$', header_text, re.MULTILINE)
        keywords_match = re.search(r'^keywords:\s*(.+)$', header_text, re.MULTILINE)

        parts = []
        if summary_match:
            parts.append(summary_match.group(1).strip())
        if keywords_match and keywords_match.group(1).strip().lower() != "none":
            parts.append(f"Keywords: {keywords_match.group(1).strip()}")
        body_excerpt = self._summarize_text(body, max_chars=max_chars)
        if body_excerpt and body_excerpt not in parts:
            parts.append(body_excerpt)
        return "\n".join(parts[:3]).strip()

    def store(
        self,
        session_id: str,
        subject: str,
        content: str,
        metadata: Optional[Dict] = None,
        project: Optional[str] = None,
    ) -> Optional[str]:
        """
        Store content in timescale hierarchy with deduplication
        Returns: file path where content was stored, or None if duplicate
        """
        normalized = self._normalize_text(content)
        if not normalized:
            return None
        structured_record = self._build_structured_record(
            session_id=session_id,
            subject=subject,
            content=normalized,
            metadata=metadata,
            project=project,
        )

        # Check for duplicates
        if self._is_duplicate(normalized):
            print(f"[MEMORY] Duplicate content skipped for {session_id}/{subject}")
            return None

        # Get current hour folder
        hour_path = self._get_time_path(session_id, subject, project=project)

        # Increment heartbeat counter
        self.heartbeat_counter += 1
        if self.heartbeat_counter > 60:
            self.heartbeat_counter = 1

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_hb{self.heartbeat_counter:02d}.txt"
        file_path = hour_path / filename

        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(structured_record)

        # Update index
        structured_metadata = merge_hash_metadata(metadata, normalized)
        self._update_index(session_id, subject, str(file_path), structured_record, structured_metadata, project=project)

        return str(file_path)

    def _update_index(
        self,
        session_id: str,
        subject: str,
        file_path: str,
        content: str,
        metadata: Optional[Dict] = None,
        project: Optional[str] = None,
    ):
        """Update segmented search index with size limits"""
        # Increment file count
        self.index["file_count"] = self.index.get("file_count", 0) + 1

        # Session index (keep only last 20 files per session)
        if session_id not in self.index["sessions"]:
            self.index["sessions"][session_id] = []
        self.index["sessions"][session_id].append(file_path)
        if len(self.index["sessions"][session_id]) > 20:
            self.index["sessions"][session_id] = self.index["sessions"][session_id][-20:]

        # Subject index (keep only last 30 files per subject)
        if subject not in self.index["subjects"]:
            self.index["subjects"][subject] = []
        self.index["subjects"][subject].append(file_path)
        if len(self.index["subjects"][subject]) > 30:
            self.index["subjects"][subject] = self.index["subjects"][subject][-30:]

        if project:
            self.index.setdefault("projects", {})
            if project not in self.index["projects"]:
                self.index["projects"][project] = []
            self.index["projects"][project].append(file_path)
            if len(self.index["projects"][project]) > 40:
                self.index["projects"][project] = self.index["projects"][project][-40:]

        # Keyword index (only top 5 keywords, keep only last 10 files per keyword)
        keywords = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', content)
        top_keywords = list(set(keywords))[:5]  # Limit to 5 keywords
        for keyword in top_keywords:
            if keyword not in self.index["keywords"]:
                self.index["keywords"][keyword] = []
            self.index["keywords"][keyword].append(file_path)
            if len(self.index["keywords"][keyword]) > 10:
                self.index["keywords"][keyword] = self.index["keywords"][keyword][-10:]

        # Clean up keywords with no recent files
        if len(self.index["keywords"]) > 100:
            # Keep only most recent 50 keywords
            sorted_keywords = sorted(self.index["keywords"].items(),
                                   key=lambda x: len(x[1]), reverse=True)
            self.index["keywords"] = dict(sorted_keywords[:50])

        self._save_index()

    def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        time_range: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """
        Optimized search across segmented indexes
        Returns: List of (file_path, content) tuples
        """
        results = []
        all_search_files = set()

        # Search across all index segments
        for index_file in sorted((self.base_path / "indexes").glob("index_segment_*.json"), reverse=True)[:3]:
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)

                # Determine search scope for this segment
                if session_id and session_id in index_data.get("sessions", {}):
                    all_search_files.update(index_data["sessions"][session_id][-10:])
                elif project and project in index_data.get("projects", {}):
                    all_search_files.update(index_data["projects"][project][-15:])
                elif subject and subject in index_data.get("subjects", {}):
                    all_search_files.update(index_data["subjects"][subject][-15:])
                else:
                    # Search by keywords
                    keywords = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', query)
                    for keyword in keywords[:3]:  # Limit to 3 keywords
                        if keyword in index_data.get("keywords", {}):
                            all_search_files.update(index_data["keywords"][keyword][-5:])
            except:
                continue

        search_files = list(all_search_files)

        # Apply time range filter
        if time_range:
            search_files = self._filter_by_time(search_files, time_range)

        # Read and return matching files (limit to 20 for performance)
        for file_path in search_files[-20:]:
            if Path(file_path).exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if any(kw.lower() in content.lower() for kw in query.split()[:3]):
                            results.append((file_path, content))
                            if len(results) >= 10:  # Limit results
                                break
                except:
                    continue

        return results

    def _filter_by_time(self, files: List[str], time_range: str) -> List[str]:
        """Filter files by time range (e.g., 'last_hour', 'today', 'last_week')"""
        now = datetime.now()

        if time_range == "last_hour":
            cutoff = now - timedelta(hours=1)
        elif time_range == "today":
            cutoff = now.replace(hour=0, minute=0, second=0)
        elif time_range == "last_week":
            cutoff = now - timedelta(days=7)
        else:
            return files

        filtered = []
        for file_path in files:
            # Extract timestamp from path
            match = re.search(r'(\d{8}_\d{6})', file_path)
            if match:
                timestamp_str = match.group(1)
                file_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                if file_time >= cutoff:
                    filtered.append(file_path)

        return filtered

    def store_secrets(self, secrets: Dict[str, str], project: Optional[str] = None):
        """Store daily secrets file (APIs, links, variables)"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        if project:
            project_dir = self.base_path / "secrets" / self._sanitize_key(project)
            project_dir.mkdir(parents=True, exist_ok=True)
            secrets_file = project_dir / f"secrets_{date_str}.json"
        else:
            secrets_file = self.base_path / "secrets" / f"secrets_{date_str}.json"

        with open(secrets_file, 'w', encoding='utf-8') as f:
            json.dump(secrets, f, indent=2)

    def get_secrets(self, date: Optional[str] = None, project: Optional[str] = None) -> Dict[str, str]:
        """Retrieve secrets for a specific date (default: today)"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        if project:
            secrets_file = self.base_path / "secrets" / self._sanitize_key(project) / f"secrets_{date}.json"
        else:
            secrets_file = self.base_path / "secrets" / f"secrets_{date}.json"
        if secrets_file.exists():
            with open(secrets_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def store_reasoning_summary(
        self,
        session_id: str,
        project: str,
        objective: str,
        summary: str,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Store explicit reasoning notes for a project.
        This is for user-visible planning summaries, not hidden internal chain-of-thought.
        """
        now = datetime.now()
        project_dir = self.base_path / "reasoning_notes" / self._sanitize_key(project) / now.strftime("%Y-%m-%d")
        project_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{self._sanitize_key(session_id)}.md"
        note_path = project_dir / filename
        payload = [
            f"Objective: {objective}",
            "",
            summary.strip(),
        ]
        if metadata:
            payload.extend(["", json.dumps(metadata, indent=2)])
        note_path.write_text("\n".join(payload).strip() + "\n", encoding="utf-8")
        return str(note_path)

    def create_weekly_summary(self):
        """Create 5KB summary of last 7 days, compress to 1KB feelings file"""
        now = datetime.now()
        week_ago = now - timedelta(days=7)

        # Collect all files from last 7 days
        all_content = []
        for session_id, files in self.index["sessions"].items():
            for file_path in files:
                match = re.search(r'(\d{8}_\d{6})', file_path)
                if match:
                    timestamp_str = match.group(1)
                    file_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    if file_time >= week_ago:
                        if Path(file_path).exists():
                            with open(file_path, 'r', encoding='utf-8') as f:
                                all_content.append(f.read())

        # Create 5KB summary
        summary = "\n".join(all_content)
        if len(summary) > 5 * 1024:
            summary = summary[:5 * 1024]

        week_str = now.strftime("%Y-W%W")
        summary_file = self.base_path / "weekly_summaries" / f"summary_{week_str}.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary)

        # Create 1KB feelings file with distilled signals
        feelings_parts = [
            f"summary={self._summarize_text(summary, max_chars=420)}",
            f"keywords={', '.join(self._extract_keywords(summary, limit=18)) or 'none'}",
            f"signals={' | '.join(self._extract_signals(summary, limit=18)) or 'none'}",
        ]
        feelings = "\n".join(feelings_parts)
        if len(feelings) > 1024:
            feelings = self._truncate_utf8(feelings, 1024)

        feelings_file = self.base_path / "feelings" / f"feelings_{week_str}.txt"
        with open(feelings_file, 'w', encoding='utf-8') as f:
            f.write(feelings)

        return str(summary_file), str(feelings_file)

    def search_weeks_ago(self, weeks: int) -> str:
        """Search feelings file for N weeks ago"""
        target_date = datetime.now() - timedelta(weeks=weeks)
        week_str = target_date.strftime("%Y-W%W")

        feelings_file = self.base_path / "feelings" / f"feelings_{week_str}.txt"
        if feelings_file.exists():
            with open(feelings_file, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def get_context(self, session_id: str, subject: str, max_files: int = 5, project: Optional[str] = None) -> str:
        """Get recent context for a session/subject (optimized for Chain of Thought)"""
        # Search recent files from index first
        recent_files = []
        if project and project in self.index.get("projects", {}):
            project_files = self.index["projects"][project]
            subject_marker_a = f"\\{self._sanitize_key(subject)}\\"
            subject_marker_b = f"/{self._sanitize_key(subject)}/"
            recent_files = [
                file_path
                for file_path in project_files
                if subject_marker_a in file_path or subject_marker_b in file_path
            ][-max_files:]
        elif session_id in self.index.get("sessions", {}):
            recent_files = self.index["sessions"][session_id][-max_files:]

        # If not enough from index, check filesystem
        if len(recent_files) < max_files:
            hour_path = self._get_time_path(session_id, subject, project=project)
            if hour_path.exists():
                fs_files = sorted(hour_path.glob("*.txt"), reverse=True)[:max_files-len(recent_files)]
                recent_files.extend([str(f) for f in fs_files])

        context = []
        seen_content = set()
        for file_path in recent_files:
            if Path(file_path).exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Deduplicate context
                        content_hash = self._content_hash(content)
                        if content_hash not in seen_content:
                            seen_content.add(content_hash)
                            context.append(self._extract_context_excerpt(content, max_chars=320))
                except:
                    continue

        return "\n---\n".join(context)

    def cleanup_old_indexes(self, keep_segments: int = 10):
        """Clean up old index segments to prevent bloat"""
        index_files = sorted((self.base_path / "indexes").glob("index_segment_*.json"))
        if len(index_files) > keep_segments:
            for old_file in index_files[:-keep_segments]:
                try:
                    old_file.unlink()
                    print(f"[MEMORY] Cleaned up old index: {old_file.name}")
                except:
                    pass

    def get_project_status(self, project: str, limit: int = 6) -> Dict:
        clean_project = self._sanitize_key(project)
        project_files = self.index.get("projects", {}).get(project, [])
        recent_files = project_files[-limit:]

        secrets_dir = self.base_path / "secrets" / clean_project
        reasoning_dir = self.base_path / "reasoning_notes" / clean_project

        secret_files = sorted(secrets_dir.glob("*.json"), reverse=True) if secrets_dir.exists() else []
        reasoning_files = sorted(reasoning_dir.rglob("*.md"), reverse=True) if reasoning_dir.exists() else []

        return {
            "project": project,
            "timescale_files": len(project_files),
            "recent_files": recent_files,
            "secret_files": [str(path) for path in secret_files[:limit]],
            "reasoning_files": [str(path) for path in reasoning_files[:limit]],
        }

    def recent_reasoning_notes(self, project: str, limit: int = 5) -> List[Dict]:
        clean_project = self._sanitize_key(project)
        reasoning_dir = self.base_path / "reasoning_notes" / clean_project
        if not reasoning_dir.exists():
            return []

        notes = []
        for note_path in sorted(reasoning_dir.rglob("*.md"), reverse=True)[:limit]:
            try:
                content = note_path.read_text(encoding='utf-8')
            except Exception:
                continue
            notes.append(
                {
                    "path": str(note_path),
                    "name": note_path.name,
                    "content": content[:600],
                }
            )
        return notes


# Global instance
memory = TimescaleMemory()

# Made with Bob
