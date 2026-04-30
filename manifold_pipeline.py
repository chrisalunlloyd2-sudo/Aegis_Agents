"""
Background post-response pipeline for AEGIS.

Moves indexing, manifold persistence, and context distillation off the hot
response path so chat replies can stream first and index second.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from DIMON_CORE_DISTILLED import DIMONCore
from fabris_pattern_engine import record_fabris_turn
from manifold_db import manifold_db
from recursive_context_distiller import context_distiller
from timescale_memory import memory as timescale_memory
from vector_memory import vector_memory

pipeline_dimon = DIMONCore()
TRACKED_TOOL_ACTIONS = {"create_directory", "create_file"}
LOW_SIGNAL_ASSISTANT_MARKERS = (
    "[alice]",
    "maintenance sop executed.",
    "default directive updated. it remains available for explicit configuration and automation jobs.",
    "no usable reply was produced by",
    "no direct prose reply was produced.",
)


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_metadata(item) for item in value]
    return str(value)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _is_low_signal_assistant_reply(reply: str) -> bool:
    normalized = _normalize_text(reply).lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in LOW_SIGNAL_ASSISTANT_MARKERS)


def record_tool_action(
    *,
    session_id: str,
    project: str,
    user_prompt: str,
    tool_name: str,
    parameters: Optional[Dict[str, Any]],
    ok: bool,
    output: str,
    result_metadata: Optional[Dict[str, Any]],
    requested_mode: str,
    route_name: str,
) -> None:
    try:
        clean_tool_name = (tool_name or "").strip()
        if not ok or clean_tool_name not in TRACKED_TOOL_ACTIONS:
            return

        safe_parameters = _sanitize_metadata(parameters or {})
        safe_result_metadata = _sanitize_metadata(result_metadata or {})
        primary_path = (
            safe_result_metadata.get("path")
            if isinstance(safe_result_metadata, dict)
            else None
        ) or (
            safe_parameters.get("path")
            if isinstance(safe_parameters, dict)
            else None
        )

        action_hint = {
            "create_directory": "folder scaffold created, directory created, project setup",
            "create_file": "file scaffold created, file written, project setup",
        }.get(clean_tool_name, "tool action")

        record_text = "\n".join(
            [
                "AEGIS tool action committed to project memory.",
                f"Tool: {clean_tool_name}",
                "Status: success",
                f"Project: {project}",
                f"Path: {primary_path or '(not provided)'}",
                f"Prompt: {user_prompt.strip()}",
                f"Result: {output.strip()}",
                f"Keywords: {action_hint}",
                f"Parameters: {json.dumps(safe_parameters, sort_keys=True)}",
                f"Metadata: {json.dumps(safe_result_metadata, sort_keys=True)}",
            ]
        )

        storage_metadata = {
            "project": project,
            "route": route_name,
            "mode": requested_mode,
            "tool": clean_tool_name,
            "ok": ok,
            "path": primary_path,
            "parameters": safe_parameters,
            "result_metadata": safe_result_metadata,
        }

        timescale_memory.store(
            session_id,
            "tool_actions",
            record_text,
            project=project,
            metadata=storage_metadata,
        )
        vector_memory.store(
            record_text,
            project=project,
            session_id=session_id,
            subject="tool_actions",
            kind="tool_action",
            role="system",
            metadata=storage_metadata,
        )
        pipeline_dimon.process_text(
            source_name=f"{route_name}:{project}:{session_id}:tool:{clean_tool_name}",
            text=record_text,
            project=project,
            session_id=session_id,
            manifold_kind="tool_action",
            metadata={"mode": requested_mode, "tool": clean_tool_name, "ok": ok},
        )
    except Exception as exc:
        print(f"[WARN] Tool action persistence skipped for {project}/{session_id}: {exc}")


def postprocess_chat_turn(
    *,
    session_id: str,
    project: str,
    prompt: str,
    reply: str,
    requested_mode: str,
    target_model: str,
    route_name: str = "chat",
) -> None:
    try:
        clean_prompt = (prompt or "").strip()
        clean_reply = (reply or "").strip()
        persist_reply = clean_reply and not _is_low_signal_assistant_reply(clean_reply)

        try:
            record_fabris_turn(
                session_id=session_id,
                project=project,
                prompt=clean_prompt,
                reply=clean_reply,
                requested_mode=requested_mode,
                target_model=target_model,
                route_name=route_name,
            )
        except Exception as fabris_exc:
            print(f"[WARN] FABRIS pattern capture skipped for {project}/{session_id}: {fabris_exc}")

        if clean_prompt:
            timescale_memory.store(
                session_id,
                "chat",
                clean_prompt,
                project=project,
                metadata={"project": project, "role": "user", "route": route_name},
            )
            vector_memory.store(
                clean_prompt,
                project=project,
                session_id=session_id,
                subject="chat",
                kind="chat",
                role="user",
                metadata={"mode": requested_mode, "route": route_name},
            )
            pipeline_dimon.process_text(
                source_name=f"{route_name}:{project}:{session_id}:user",
                text=clean_prompt,
                project=project,
                session_id=session_id,
                manifold_kind="chat_user",
                metadata={"mode": requested_mode, "model": target_model},
            )
            manifold_db.record_conversation(session_id=session_id, role="user", content=clean_prompt)

        if persist_reply:
            timescale_memory.store(
                session_id,
                "chat",
                clean_reply,
                project=project,
                metadata={"project": project, "role": "assistant", "route": route_name},
            )
            vector_memory.store(
                clean_reply,
                project=project,
                session_id=session_id,
                subject="chat",
                kind="chat",
                role="assistant",
                metadata={"mode": requested_mode, "route": route_name},
            )
            manifold_db.record_conversation(session_id=session_id, role="assistant", content=clean_reply)
            pipeline_dimon.process_text(
                source_name=f"{route_name}:{project}:{session_id}:assistant",
                text=clean_reply,
                project=project,
                session_id=session_id,
                manifold_kind="chat_assistant",
                metadata={"mode": requested_mode, "model": target_model},
            )

        if persist_reply:
            summary_text = (
                f"Mode: {requested_mode}\n"
                f"Model: {target_model}\n"
                f"Route: {route_name}\n"
                f"Context sources: project directory signatures + project timescale + project vector memory\n"
                f"Response preview: {clean_reply[:300]}"
            )
            timescale_memory.store_reasoning_summary(
                session_id=session_id,
                project=project,
                objective=clean_prompt,
                summary=summary_text,
                metadata={"project": project, "model": target_model, "route": route_name},
            )
            vector_memory.store(
                f"Objective: {clean_prompt}\nSummary: {clean_reply[:500]}",
                project=project,
                session_id=session_id,
                subject="reasoning",
                kind="reasoning",
                role="system",
                metadata={"project": project, "model": target_model, "route": route_name},
            )
        context_distiller.build_project_signatures(project)
    except Exception as exc:
        print(f"[WARN] postprocess_chat_turn skipped for {project}/{session_id}: {exc}")


def postprocess_research_project(project: str) -> None:
    try:
        context_distiller.build_project_signatures(project)
    except Exception as exc:
        print(f"[WARN] postprocess_research_project skipped for {project}: {exc}")
