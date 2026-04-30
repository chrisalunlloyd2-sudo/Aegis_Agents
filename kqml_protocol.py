"""
Small KQML/ACL message helpers for AEGIS internal agent traffic.

The wire form follows the classic KQML shape:

    (performative :sender ... :receiver ... :language ... :ontology ... :content ...)

Content is intentionally allowed to be JSON. KQML specifies the outer speech-act
envelope; the content language can be a domain language such as JSON, KIF, or text.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


KQML_RESERVED_FIELDS = (
    "sender",
    "receiver",
    "language",
    "ontology",
    "reply-with",
    "in-reply-to",
    "content",
    "force",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_conversation_id(prefix: str = "aegis") -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_.:-]+", "-", prefix or "aegis").strip("-") or "aegis"
    return f"{safe_prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def make_kqml_message(
    performative: str,
    *,
    sender: str,
    receiver: str,
    content: Any = "",
    language: str = "json",
    ontology: str = "aegis-runtime",
    conversation_id: Optional[str] = None,
    reply_with: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    force: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", performative or "").strip("-").lower()
    if not normalized:
        raise ValueError("KQML performative is required")
    message: Dict[str, Any] = {
        "protocol": "kqml",
        "performative": normalized,
        "sender": sender,
        "receiver": receiver,
        "language": language,
        "ontology": ontology,
        "conversation-id": conversation_id or new_conversation_id("conversation"),
        "timestamp": utc_timestamp(),
        "content": content,
    }
    if reply_with:
        message["reply-with"] = reply_with
    if in_reply_to:
        message["in-reply-to"] = in_reply_to
    if force:
        message["force"] = force
    if metadata:
        message["metadata"] = dict(metadata)
    return message


def _quote(value: Any) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=True)


def _content_to_wire(value: Any) -> str:
    if isinstance(value, str):
        return _quote(value)
    return _quote(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


def render_kqml(message: Dict[str, Any]) -> str:
    """Render a normalized message dictionary as an ASCII KQML performative."""
    performative = str(message.get("performative") or "").strip().lower()
    if not performative:
        raise ValueError("KQML message missing performative")
    parts = [f"({performative}"]
    ordered_fields = (
        "sender",
        "receiver",
        "language",
        "ontology",
        "conversation-id",
        "reply-with",
        "in-reply-to",
        "force",
    )
    for field in ordered_fields:
        if field in message and message.get(field) not in (None, ""):
            parts.append(f"  :{field} {_quote(message.get(field))}")
    if "content" in message:
        parts.append(f"  :content {_content_to_wire(message.get('content'))}")
    if message.get("metadata"):
        parts.append(f"  :metadata {_content_to_wire(message.get('metadata'))}")
    parts.append(")")
    return "\n".join(parts)


def _tokenize_kqml(text: str) -> List[str]:
    tokens: List[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char in "()":
            tokens.append(char)
            i += 1
            continue
        if char == '"':
            start = i
            i += 1
            escaped = False
            while i < len(text):
                current = text[i]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    i += 1
                    break
                i += 1
            tokens.append(text[start:i])
            continue
        start = i
        while i < len(text) and not text[i].isspace() and text[i] not in "()":
            i += 1
        tokens.append(text[start:i])
    return tokens


def _parse_expr(tokens: List[str], position: int = 0) -> Tuple[Any, int]:
    if position >= len(tokens):
        raise ValueError("Unexpected end of KQML input")
    token = tokens[position]
    if token == "(":
        values: List[Any] = []
        position += 1
        while position < len(tokens) and tokens[position] != ")":
            value, position = _parse_expr(tokens, position)
            values.append(value)
        if position >= len(tokens):
            raise ValueError("Unclosed KQML list")
        return values, position + 1
    if token == ")":
        raise ValueError("Unexpected KQML close paren")
    if token.startswith('"') and token.endswith('"'):
        return json.loads(token), position + 1
    return token, position + 1


def parse_kqml(text: str) -> Dict[str, Any]:
    """Parse a KQML performative into a normalized dictionary."""
    parsed, position = _parse_expr(_tokenize_kqml(text or ""))
    if position == 0 or not isinstance(parsed, list) or not parsed:
        raise ValueError("KQML input must be a performative list")
    performative = str(parsed[0]).strip().lower()
    message: Dict[str, Any] = {
        "protocol": "kqml",
        "performative": performative,
    }
    index = 1
    while index < len(parsed):
        key = parsed[index]
        if not isinstance(key, str) or not key.startswith(":"):
            raise ValueError(f"Expected KQML keyword at position {index}")
        if index + 1 >= len(parsed):
            raise ValueError(f"Missing KQML value for {key}")
        message[key[1:].lower()] = parsed[index + 1]
        index += 2
    return message


def performative_for_tool(tool_call: Dict[str, Any]) -> str:
    tool_name = str(tool_call.get("tool") or "").lower()
    if tool_name.startswith("search") or tool_name.startswith("read") or tool_name in {
        "list_directory",
        "get_runtime_status",
        "run_system_heartbeat",
    }:
        return "ask-one"
    return "achieve"


def make_tool_request_message(
    tool_call: Dict[str, Any],
    *,
    index: int,
    sender: str = "aegis-coordinator",
    receiver: str = "aegis-tool-router",
    conversation_id: Optional[str] = None,
    route_name: str = "local_tool",
) -> Dict[str, Any]:
    reply_with = f"{route_name}-tool-{index}-{uuid.uuid4().hex[:6]}"
    return make_kqml_message(
        performative_for_tool(tool_call),
        sender=sender,
        receiver=receiver,
        language="json",
        ontology=f"aegis.{route_name}",
        conversation_id=conversation_id,
        reply_with=reply_with,
        content={
            "tool": tool_call.get("tool"),
            "parameters": tool_call.get("parameters", {}),
            "route": route_name,
            "index": index,
        },
    )


def make_tool_result_message(
    tool_call: Dict[str, Any],
    tool_result: Any,
    request_message: Dict[str, Any],
    *,
    sender: str = "aegis-tool-router",
    receiver: str = "aegis-coordinator",
) -> Dict[str, Any]:
    ok = bool(getattr(tool_result, "ok", False)) if tool_result is not None else False
    rendered_output = str(getattr(tool_result, "output", tool_result) or "")
    error = str(getattr(tool_result, "error", "") or "")
    return make_kqml_message(
        "tell" if ok else "sorry",
        sender=sender,
        receiver=receiver,
        language="json",
        ontology=str(request_message.get("ontology") or "aegis.local_tool"),
        conversation_id=str(request_message.get("conversation-id") or new_conversation_id("conversation")),
        in_reply_to=str(request_message.get("reply-with") or ""),
        content={
            "tool": tool_call.get("tool"),
            "ok": ok,
            "output": rendered_output,
            "error": error,
            "metadata": getattr(tool_result, "metadata", {}) if tool_result is not None else {},
        },
    )


def render_kqml_exchange(request_message: Dict[str, Any], response_message: Dict[str, Any]) -> str:
    return "KQML request:\n" + render_kqml(request_message) + "\n\nKQML response:\n" + render_kqml(response_message)
