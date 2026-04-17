"""
AEGIS Timescale Memory System v2.0
Optimized with deduplication and segmented indexing
- Boolean logic and operators only (no NLP)
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

class TimescaleMemory:
    def __init__(self, base_path: Optional[str] = None):
        """Initialize timescale memory system"""
        self.base_path = Path(base_path) if base_path else Path("C:/Users/viper/Aegis_Memory")
        self.desktop_path = Path(os.path.expanduser("~/Desktop"))
        self.max_chunk_size = 2 * 1024  # 2KB (reduced from 5KB)
        self.max_index_size = 10 * 1024  # 10KB per index segment
        self.heartbeat_counter = 0
        self.current_hour_folder = None
        self.seen_hashes: Set[str] = set()  # Deduplication cache
        
        # Create base structure
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "secrets").mkdir(exist_ok=True)
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
                return json.load(f)
        return {"sessions": {}, "subjects": {}, "keywords": {}, "file_count": 0}
    
    def _save_index(self):
        """Save current index segment, rotate if too large"""
        index_file = self._get_current_index_file()
        
        # Check size before saving
        temp_data = json.dumps(self.index, indent=2)
        if len(temp_data.encode('utf-8')) > self.max_index_size:
            # Rotate to new segment
            self.current_index_segment += 1
            self.index = {"sessions": {}, "subjects": {}, "keywords": {}, "file_count": 0}
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
    
    def _get_time_path(self, session_id: str, subject: str) -> Path:
        """Generate hierarchical path: session/subject/YYYY-MM-DD/HH/"""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%H")
        
        path = self.base_path / session_id / subject / date_str / hour_str
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _compress_to_boolean(self, text: str) -> str:
        """
        Compress text to boolean logic, equations, operators
        Remove NLP fluff, keep only essential data
        """
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Extract key patterns: equations, operators, boolean logic
        patterns = {
            'equations': r'[a-zA-Z0-9_]+\s*[=<>!]+\s*[a-zA-Z0-9_]+',
            'operators': r'[+\-*/&|^~<>=!]+',
            'booleans': r'\b(true|false|and|or|not|if|then|else)\b',
            'numbers': r'\b\d+\.?\d*\b',
            'variables': r'\b[a-zA-Z_][a-zA-Z0-9_]*\b'
        }
        
        # Keep only essential content
        essential = []
        for pattern_type, pattern in patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            essential.extend(matches)
        
        # If no patterns found, keep original but compressed
        if not essential:
            return text
        
        # Join with minimal spacing
        return '|'.join(essential)
    
    def store(self, session_id: str, subject: str, content: str, metadata: Optional[Dict] = None) -> Optional[str]:
        """
        Store content in timescale hierarchy with deduplication
        Returns: file path where content was stored, or None if duplicate
        """
        # Compress content
        compressed = self._compress_to_boolean(content)
        
        # Check for duplicates
        if self._is_duplicate(compressed):
            print(f"[MEMORY] Duplicate content skipped for {session_id}/{subject}")
            return None
        
        # Get current hour folder
        hour_path = self._get_time_path(session_id, subject)
        
        # Increment heartbeat counter
        self.heartbeat_counter += 1
        if self.heartbeat_counter > 60:
            self.heartbeat_counter = 1
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_hb{self.heartbeat_counter:02d}.txt"
        file_path = hour_path / filename
        
        # Check size (reduced to 2KB)
        if len(compressed.encode('utf-8')) > self.max_chunk_size:
            # Truncate instead of overflow for better performance
            compressed = compressed[:self.max_chunk_size-100] + "...[TRUNCATED]"
        
        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(compressed)
        
        # Update index
        self._update_index(session_id, subject, str(file_path), compressed, metadata)
        
        return str(file_path)
    
    def _update_index(self, session_id: str, subject: str, file_path: str, content: str, metadata: Optional[Dict] = None):
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
    
    def search(self, query: str, session_id: Optional[str] = None, subject: Optional[str] = None,
               time_range: Optional[str] = None) -> List[Tuple[str, str]]:
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
    
    def store_secrets(self, secrets: Dict[str, str]):
        """Store daily secrets file (APIs, links, variables)"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        secrets_file = self.base_path / "secrets" / f"secrets_{date_str}.json"
        
        with open(secrets_file, 'w', encoding='utf-8') as f:
            json.dump(secrets, f, indent=2)
    
    def get_secrets(self, date: Optional[str] = None) -> Dict[str, str]:
        """Retrieve secrets for a specific date (default: today)"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        secrets_file = self.base_path / "secrets" / f"secrets_{date}.json"
        if secrets_file.exists():
            with open(secrets_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
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
        
        # Create 1KB feelings file (ultra-compressed)
        feelings = self._compress_to_boolean(summary)
        if len(feelings) > 1024:
            feelings = feelings[:1024]
        
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
    
    def get_context(self, session_id: str, subject: str, max_files: int = 5) -> str:
        """Get recent context for a session/subject (optimized for Chain of Thought)"""
        # Search recent files from index first
        recent_files = []
        if session_id in self.index.get("sessions", {}):
            recent_files = self.index["sessions"][session_id][-max_files:]
        
        # If not enough from index, check filesystem
        if len(recent_files) < max_files:
            hour_path = self._get_time_path(session_id, subject)
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
                            context.append(content[:200])  # Limit context size
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


# Global instance
memory = TimescaleMemory()

# Made with Bob
