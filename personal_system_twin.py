"""
Local personal system twin for AEGIS.

This module records structured workflow events and turns repeated local patterns
into compact, weak hints. It does not capture screenshots, clipboard contents,
keystrokes, or raw chat history. Higher layers decide what events are safe to
send here.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import threading
from typing import Any, Dict, List, Optional


MAX_SUMMARY_CHARS = 520
MAX_EVENTS_FOR_ANALYSIS = 240

TAG_PATTERNS = {
    "dependency": ["dependency", "dependencies", "import", "module not found", "package", "pip", "npm", "venv"],
    "service": ["server", "service", "api", "uvicorn", "port", "localhost", "ollama", "backend"],
    "build": ["build", "compile", "compiler", "d8", "dex", "apk", "gradle", "javac"],
    "test": ["test", "pytest", "unittest", "smoke", "verify", "validation", "failed"],
    "resource": ["ram", "memory", "cpu", "slow", "sluggish", "frozen", "stuck", "hang"],
    "browser": ["browser", "tab", "page", "web ui", "click", "dom"],
    "debugging": ["debug", "bug", "error", "traceback", "exception", "crash", "stack"],
    "android": ["android", "apk", "d8", "dex", "activity", "manifest", "termux"],
    "automation": ["agent", "automation", "watchdog", "heartbeat", "scheduler", "loop"],
}

STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "check",
    "could", "doing", "from", "have", "into", "just", "like", "more", "need",
    "only", "over", "should", "that", "their", "there", "this", "what", "when",
    "where", "with", "would", "your",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _slug_words(text: str, limit: int = 6) -> str:
    words = []
    for word in re.findall(r"[a-z0-9_\-]{3,}", text.lower()):
        if word in STOPWORDS or word in words:
            continue
        words.append(word)
        if len(words) >= limit:
            break
    return ":".join(words) or "general"


def _contains_pattern(source: str, pattern: str) -> bool:
    if not pattern:
        return False
    if " " in pattern:
        return pattern in source
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(pattern)}(?![a-z0-9_])", source))


def _derive_tags(activity: str, summary: str, node: str = "") -> List[str]:
    source = f"{activity} {summary} {node}".lower()
    tags = []
    for tag, patterns in TAG_PATTERNS.items():
        if any(_contains_pattern(source, pattern) for pattern in patterns):
            tags.append(tag)
    if "error state" in source and "debugging" not in tags:
        tags.append("debugging")
    return tags[:8]


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class PersonalSystemTwin:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        root = Path(base_dir or Path(__file__).resolve().parent)
        self.data_dir = root / "system_twin"
        self.events_path = self.data_dir / "events.jsonl"
        self.habits_path = self.data_dir / "habits.json"
        self.snapshot_path = self.data_dir / "latest_snapshot.json"
        self.lock = threading.RLock()

    def record_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        clean = self._normalize_event(event)
        with self.lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(clean, sort_keys=True) + "\n")
            habits = self._update_habits(clean)
            recent = self._read_recent_events(MAX_EVENTS_FOR_ANALYSIS)
            snapshot = self._build_snapshot(clean, recent, habits)
            _write_json(self.snapshot_path, snapshot)
        return {"ok": True, "event": clean, "snapshot": snapshot}

    def status(self) -> Dict[str, Any]:
        snapshot = _load_json(self.snapshot_path, {})
        habits = _load_json(self.habits_path, {})
        return {
            "enabled": True,
            "data_dir": str(self.data_dir),
            "events_path": str(self.events_path),
            "event_count": int(habits.get("event_count", 0) or 0),
            "last_update": snapshot.get("updated_at"),
            "active_workflow": snapshot.get("active_workflow"),
            "habit_hints": snapshot.get("habit_hints", []),
            "privacy": "structured local events only; no screenshots, clipboard, keystrokes, or raw chat logs",
        }

    def build_prompt_context(self, project: str = "", activity: str = "", max_hints: int = 3) -> str:
        snapshot = _load_json(self.snapshot_path, {})
        hints = [str(item).strip() for item in snapshot.get("habit_hints", []) if str(item).strip()]
        if not hints:
            return ""
        workflow = str(snapshot.get("active_workflow") or "unknown").strip()
        lines = ["PERSONAL SYSTEM TWIN HINTS:"]
        if workflow and workflow != "unknown":
            lines.append(f"- Active workflow guess: {workflow}.")
        for hint in hints[: max(1, max_hints)]:
            lines.append(f"- {hint}")
        lines.append("- Treat these as weak local heuristics. Current logs, tests, and explicit user instructions outrank them.")
        return "\n".join(lines)

    def _normalize_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        event = event or {}
        activity = _clean_text(event.get("activity") or "unknown", 80).lower() or "unknown"
        summary = _clean_text(event.get("summary") or event.get("message") or "", MAX_SUMMARY_CHARS)
        node = _clean_text(event.get("node") or event.get("machine") or "unknown", 120) or "unknown"
        project = _clean_text(event.get("project") or event.get("project_lane") or "general", 100) or "general"
        source = _clean_text(event.get("source") or "manual", 80) or "manual"
        try:
            confidence = max(0.0, min(1.0, float(event.get("confidence", 0.0) or 0.0)))
        except Exception:
            confidence = 0.0
        tags = list(event.get("tags") or [])
        tags = [_clean_text(tag, 40).lower() for tag in tags if _clean_text(tag, 40)]
        for tag in _derive_tags(activity, summary, node):
            if tag not in tags:
                tags.append(tag)
        signature = f"{node.lower()}|{activity}|{_slug_words(summary)}"
        return {
            "timestamp": _clean_text(event.get("timestamp") or event.get("time") or _utc_now(), 80),
            "source": source,
            "project": project,
            "node": node,
            "activity": activity,
            "summary": summary,
            "confidence": confidence,
            "tags": tags[:8],
            "signature": signature,
        }

    def _update_habits(self, event: Dict[str, Any]) -> Dict[str, Any]:
        habits = _load_json(
            self.habits_path,
            {
                "event_count": 0,
                "activity_counts": {},
                "node_counts": {},
                "tag_counts": {},
                "signature_counts": {},
                "last_seen": {},
            },
        )
        habits["event_count"] = int(habits.get("event_count", 0) or 0) + 1
        for key, value in (
            ("activity_counts", event.get("activity")),
            ("node_counts", event.get("node")),
            ("signature_counts", event.get("signature")),
        ):
            bucket = habits.setdefault(key, {})
            label = str(value or "unknown")
            bucket[label] = int(bucket.get(label, 0) or 0) + 1
        tag_counts = habits.setdefault("tag_counts", {})
        for tag in event.get("tags", []):
            tag_counts[tag] = int(tag_counts.get(tag, 0) or 0) + 1
        habits.setdefault("last_seen", {})[event.get("signature", "general")] = event.get("timestamp")
        habits["updated_at"] = _utc_now()
        _write_json(self.habits_path, habits)
        return habits

    def _read_recent_events(self, limit: int) -> List[Dict[str, Any]]:
        if not self.events_path.exists():
            return []
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()[-limit:]
        except Exception:
            return []
        events = []
        for line in lines:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    events.append(item)
            except Exception:
                continue
        return events

    def _build_snapshot(self, event: Dict[str, Any], recent: List[Dict[str, Any]], habits: Dict[str, Any]) -> Dict[str, Any]:
        activities = Counter(str(item.get("activity") or "unknown") for item in recent)
        tags = Counter(tag for item in recent for tag in item.get("tags", []))
        signatures = Counter(str(item.get("signature") or "general") for item in recent)
        active_workflow = self._classify_workflow(activities, tags, event)
        hints = self._derive_hints(event, activities, tags, signatures, habits)
        return {
            "updated_at": _utc_now(),
            "event_count_total": int(habits.get("event_count", 0) or 0),
            "recent_event_count": len(recent),
            "active_workflow": active_workflow,
            "recent_activity_counts": dict(activities.most_common(8)),
            "recent_tag_counts": dict(tags.most_common(10)),
            "habit_hints": hints[:6],
            "last_event": event,
        }

    def _classify_workflow(self, activities: Counter, tags: Counter, event: Dict[str, Any]) -> str:
        if tags.get("debugging", 0) or "debug" in str(event.get("activity", "")):
            if tags.get("service", 0):
                return "debugging local service or API"
            if tags.get("dependency", 0):
                return "debugging dependency or environment"
            return "debugging"
        if tags.get("build", 0) and tags.get("android", 0):
            return "building Android/D8 program"
        if tags.get("automation", 0):
            return "automation or agent monitoring"
        if tags.get("resource", 0):
            return "system health and resources"
        if tags.get("browser", 0):
            return "browser or GUI workflow"
        return str(event.get("activity") or "general")

    def _derive_hints(
        self,
        event: Dict[str, Any],
        activities: Counter,
        tags: Counter,
        signatures: Counter,
        habits: Dict[str, Any],
    ) -> List[str]:
        hints: List[str] = []
        activity = str(event.get("activity") or "")
        node = str(event.get("node") or "this node")
        signature = str(event.get("signature") or "general")
        signature_total = int((habits.get("signature_counts") or {}).get(signature, 0) or 0)

        if signature_total >= 2 or signatures.get(signature, 0) >= 2:
            hints.append(f"Recurring pattern on {node}: check the known first-order blockers before broad rewrites.")
        if "debug" in activity or tags.get("debugging", 0):
            hints.append("Debugging habit: inspect the latest error/log, dependency state, and active service before changing architecture.")
        if tags.get("dependency", 0):
            hints.append("Dependency hint: confirm imports, package install path, virtual environment, and model/tool availability first.")
        if tags.get("service", 0):
            hints.append("Service hint: confirm the expected port, one live backend instance, and the freshest log before deeper fixes.")
        if tags.get("build", 0) or tags.get("test", 0):
            hints.append("Build loop hint: make one small change, run the closest verification, then repair from the exact output.")
        if tags.get("android", 0):
            hints.append("Android/D8 hint: prefer Flat Java, explicit manifest/build commands, and minimal dependencies before adding frameworks.")
        if tags.get("resource", 0):
            hints.append("System health hint: run heartbeat/resource checks before killing processes or changing runtime settings.")
        if tags.get("automation", 0):
            hints.append("Automation hint: keep actions reversible and log every command, approval, and termination decision.")

        deduped: List[str] = []
        for hint in hints:
            if hint not in deduped:
                deduped.append(hint)
        return deduped


personal_system_twin = PersonalSystemTwin()
