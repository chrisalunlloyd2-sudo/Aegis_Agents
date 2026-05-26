from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional


def _iso_now() -> str:
    return datetime.utcnow().isoformat()


def _compact(text: str, max_chars: int) -> str:
    clean = " ".join((text or "").strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 3)].rstrip() + "..."


def _estimate_bytes(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    except Exception:
        return len(str(payload).encode("utf-8", errors="ignore"))


class RamWorkingMemory:
    """
    Lightweight in-process RAM working memory.
    - Geofenced by max_bytes
    - Text-first turn memory
    - 10 summary slots, 10 lexical slots, 10 semantic slots, 10 trace logs
    - Overflow offload callback
    """

    def __init__(
        self,
        *,
        max_bytes: int = 128 * 1024 * 1024,
        summary_slots: int = 10,
        lexical_slots: int = 10,
        semantic_slots: int = 10,
        log_slots: int = 10,
        last_replies_slots: int = 15,
        offload_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.max_bytes = max(4 * 1024 * 1024, int(max_bytes))
        self.summary_slots = max(1, int(summary_slots))
        self.lexical_slots = max(1, int(lexical_slots))
        self.semantic_slots = max(1, int(semantic_slots))
        self.log_slots = max(1, int(log_slots))
        self.last_replies_slots = max(1, int(last_replies_slots))
        self.offload_callback = offload_callback

        self._lock = threading.RLock()
        self.turns: Deque[Dict[str, Any]] = deque()
        self.session_summaries: Deque[Dict[str, Any]] = deque(maxlen=self.summary_slots)
        self.lexical_memory: Deque[Dict[str, Any]] = deque(maxlen=self.lexical_slots)
        self.semantic_memory: Deque[Dict[str, Any]] = deque(maxlen=self.semantic_slots)
        self.trace_logs: Deque[Dict[str, Any]] = deque(maxlen=self.log_slots)
        self.last_replies: Deque[Dict[str, Any]] = deque(maxlen=self.last_replies_slots)
        self._bytes = 0
        self._offloaded_count = 0

    def _track_append(self, payload: Dict[str, Any]) -> None:
        self.turns.append(payload)
        self._bytes += _estimate_bytes(payload)

    def _recompute_bytes(self) -> None:
        self._bytes = sum(_estimate_bytes(item) for item in self.turns)

    def _offload_if_needed(self) -> None:
        # Keep a little headroom after overflow.
        target = int(self.max_bytes * 0.90)
        while self._bytes > self.max_bytes and self.turns:
            oldest = self.turns.popleft()
            self._bytes -= _estimate_bytes(oldest)
            self._offloaded_count += 1
            if self.offload_callback:
                try:
                    self.offload_callback(oldest)
                except Exception:
                    pass
        while self._bytes > target and self.turns:
            oldest = self.turns.popleft()
            self._bytes -= _estimate_bytes(oldest)
            self._offloaded_count += 1
            if self.offload_callback:
                try:
                    self.offload_callback(oldest)
                except Exception:
                    pass

    def add_turn(
        self,
        *,
        session_id: str,
        project: str,
        prompt: str,
        reply: str,
        thoughts: str = "",
        image_descriptions: Optional[List[str]] = None,
        route: str = "local_chat",
    ) -> None:
        with self._lock:
            prompt = prompt or ""
            reply = reply or ""
            thoughts = thoughts or ""
            image_descriptions = image_descriptions or []
            turn = {
                "ts": _iso_now(),
                "session_id": str(session_id or "unknown"),
                "project": str(project or "general"),
                "route": str(route or "chat"),
                "prompt": prompt,
                "reply": reply,
                "thoughts": thoughts,
                "image_descriptions": [str(x)[:600] for x in image_descriptions[:6]],
            }
            self._track_append(turn)

            summary = {
                "ts": turn["ts"],
                "session_id": turn["session_id"],
                "project": turn["project"],
                "summary": _compact(f"Q: {prompt} A: {reply}", 420),
            }
            self.session_summaries.append(summary)

            lexical = {
                "ts": turn["ts"],
                "session_id": turn["session_id"],
                "project": turn["project"],
                "text": _compact(f"{prompt} {reply}", 240),
            }
            self.lexical_memory.append(lexical)

            semantic = {
                "ts": turn["ts"],
                "session_id": turn["session_id"],
                "project": turn["project"],
                "intent": _compact(prompt, 160),
                "outcome": _compact(reply, 220),
            }
            self.semantic_memory.append(semantic)
            self.last_replies.append(
                {
                    "ts": turn["ts"],
                    "session_id": turn["session_id"],
                    "project": turn["project"],
                    "reply": _compact(reply, 400),
                }
            )

            self.trace_logs.append(
                {
                    "ts": turn["ts"],
                    "event": "turn_added",
                    "session_id": turn["session_id"],
                    "project": turn["project"],
                    "route": turn["route"],
                    "bytes_now": self._bytes,
                }
            )

            self._offload_if_needed()

    def recent_turns_for_session(self, session_id: str, limit: int = 2) -> List[Dict[str, Any]]:
        with self._lock:
            clean_sid = str(session_id or "")
            items = [item for item in self.turns if item.get("session_id") == clean_sid]
            return items[-max(1, int(limit)) :]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "max_bytes": self.max_bytes,
                "bytes_in_use": self._bytes,
                "bytes_utilization": round(self._bytes / max(self.max_bytes, 1), 4),
                "turn_count": len(self.turns),
                "session_summary_count": len(self.session_summaries),
                "lexical_count": len(self.lexical_memory),
                "semantic_count": len(self.semantic_memory),
                "trace_log_count": len(self.trace_logs),
                "last_reply_count": len(self.last_replies),
                "last_replies": list(self.last_replies),
                "offloaded_count": self._offloaded_count,
                "recent_trace_logs": list(self.trace_logs)[-5:],
            }
