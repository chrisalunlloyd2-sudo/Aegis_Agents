"""
Helpers for running PicoClaw as a tiny local coding sidecar.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from context_policy import WORKER_CONTEXT_WINDOW
from kqml_protocol import new_conversation_id

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import for standalone use
    load_dotenv = None


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)
ITALIC_UNDERSCORE_RE = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", re.DOTALL)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _ensure_env_loaded() -> None:
    if load_dotenv is not None:
        load_dotenv(_repo_root() / ".env", override=False)


def _picoclaw_home() -> Path:
    _ensure_env_loaded()
    raw = os.getenv("AEGIS_PICOCLAW_HOME", "").strip()
    return Path(raw) if raw else (_repo_root() / "vendor" / "picoclaw_runtime")


def _picoclaw_exe() -> Path:
    _ensure_env_loaded()
    raw = os.getenv("AEGIS_PICOCLAW_EXE", "").strip()
    if raw:
        return Path(raw)
    return _repo_root() / "vendor" / "picoclaw" / "picoclaw.exe"


def _picoclaw_workspace() -> Path:
    return _picoclaw_home() / "workspace"


def _picoclaw_config_path() -> Path:
    return _picoclaw_home() / "config.json"


def _default_model_alias() -> str:
    _ensure_env_loaded()
    return os.getenv("AEGIS_PICOCLAW_MODEL_ALIAS", "aegis-local-coder").strip() or "aegis-local-coder"


def _default_model_name() -> str:
    _ensure_env_loaded()
    return (
        os.getenv("AEGIS_PICOCLAW_MODEL", "").strip()
        or os.getenv("AEGIS_LOCAL_TOOL_MODEL", "").strip()
        or "qwen2.5-coder:1.5b"
    )


def _default_api_base() -> str:
    _ensure_env_loaded()
    return os.getenv("AEGIS_PICOCLAW_API_BASE", "http://127.0.0.1:11434/v1").strip() or "http://127.0.0.1:11434/v1"


def _fallback_model_name() -> str:
    _ensure_env_loaded()
    return (
        os.getenv("AEGIS_LOCAL_TOOL_FALLBACK_MODEL", "").strip()
        or os.getenv("AEGIS_LOCAL_PRIMARY_MODEL", "").strip()
        or "aegis-gemma2-abliterated:2b-q8"
    )


def _prefer_direct_delegate(model_name: Optional[str] = None) -> bool:
    _ensure_env_loaded()
    raw = os.getenv("AEGIS_PICOCLAW_PREFER_DIRECT", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    lowered = (model_name or _default_model_name()).strip().lower()
    return "aegis-gemma2-abliterated" in lowered


def _tool_keep_alive() -> str:
    _ensure_env_loaded()
    return os.getenv("AEGIS_OLLAMA_TOOL_KEEP_ALIVE", "8m").strip() or "8m"


def _is_usable_sidecar_response(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 24:
        return False
    tokens = re.findall(r"[A-Za-z0-9_]+", cleaned.lower())
    if len(tokens) < 6:
        return False
    unique_ratio = len(set(tokens)) / max(1, len(tokens))
    if unique_ratio < 0.38:
        return False
    most_common = Counter(tokens).most_common(1)
    if most_common and most_common[0][1] > max(3, int(len(tokens) * 0.34)):
        return False
    return True


def _post_ollama_chat(
    *,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int,
    require_usable: bool = True,
) -> Dict[str, Any]:
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "keep_alive": _tool_keep_alive(),
        "options": {
            "temperature": 0.1,
            "num_ctx": WORKER_CONTEXT_WINDOW,
            "num_predict": 160,
        },
    }
    request = urllib.request.Request(
        f"{_default_api_base().rsplit('/v1', 1)[0]}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(10, int(timeout_seconds))) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP error: {detail}", "model": model_name}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "model": model_name}

    content = (((body.get("message") or {}) if isinstance(body, dict) else {}).get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "empty response", "model": model_name}
    if require_usable and not _is_usable_sidecar_response(content):
        return {"ok": False, "error": f"low-signal response: {content!r}", "model": model_name}
    return {"ok": True, "content": content, "model": model_name}


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")


def _kqml_quote(text: Optional[str]) -> str:
    return json.dumps((text or "").strip(), ensure_ascii=True)


def _clean_picoclaw_stdout(text: str) -> str:
    cleaned = _strip_ansi(text or "")
    cleaned = re.sub(r"^.*?Usage:\s*picoclaw.*?$", "", cleaned, flags=re.DOTALL)
    lines: List[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("████") or stripped.startswith("██") or stripped.startswith("╚") or stripped.startswith("╔"):
            continue
        if stripped.startswith("🦞 picoclaw"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_markdown_italics(text: str) -> List[str]:
    captures: List[str] = []
    for pattern in (ITALIC_STAR_RE, ITALIC_UNDERSCORE_RE):
        for match in pattern.findall(text or ""):
            cleaned = re.sub(r"\s+", " ", str(match)).strip()
            if cleaned and cleaned not in captures:
                captures.append(cleaned)
    return captures


def build_picoclaw_delegate_message(
    prompt: str,
    workspace: Optional[str] = None,
    *,
    conversation_id: Optional[str] = None,
    reply_with: Optional[str] = None,
) -> str:
    italic_intents = extract_markdown_italics(prompt)
    task_blocks = italic_intents or [prompt.strip()]
    conversation_id = conversation_id or new_conversation_id("picoclaw")
    reply_with = reply_with or f"{conversation_id}:task-result"
    rendered_blocks = []
    for index, item in enumerate(task_blocks, start=1):
        rendered_blocks.append(
            f"      (:task-block {index} :mode \"code_or_verify\" :intent {_kqml_quote(item)})"
        )
    return (
        "(achieve\n"
        "  :sender \"aegis-coordinator\"\n"
        "  :receiver \"picoclaw-sidecar\"\n"
        "  :language \"acl-kqml\"\n"
        "  :ontology \"micro-code-execution\"\n"
        f"  :conversation-id {_kqml_quote(conversation_id)}\n"
        f"  :reply-with {_kqml_quote(reply_with)}\n"
        "  :content (\n"
        f"    :workspace {_kqml_quote(workspace or 'not specified')}\n"
        "    :policy \"stateless subordinate task worker; AEGIS coordinator assigns task blocks; no db coupling; no long memory coupling\"\n"
        "    :methodology \"reduce the ask into owned logic blocks; translate the active block into runnable code or verification work\"\n"
        "    :compression \"prefer flat compiler-friendly code and compact patch-ready output; for Android/Java/APK use D8 compression: Flat Java, named classes, no anonymous inner classes, lambdas, or hidden Runnables\"\n"
        "    :execution \"run code, verify steps, obey the active logic block, return compact patch-ready output\"\n"
        "    :task-blocks (\n"
        f"{chr(10).join(rendered_blocks)}\n"
        "    )\n"
        f"    :coordinator_message {_kqml_quote(prompt)}\n"
        "  )\n"
        ")\n"
    )


def _delegate_via_direct_ollama(prompt: str, workspace: Optional[str], timeout_seconds: int) -> Dict[str, Any]:
    italic_intents = extract_markdown_italics(prompt)
    intent_block = "\n".join(f"- {item}" for item in italic_intents) if italic_intents else "- Use the full coordinator message."
    system_prompt = (
        "You are PicoClaw, the AEGIS execution sidecar.\n"
        "AEGIS is the coordinator/master planner and speaks in ACL/KQML-style task packets.\n"
        "You are the subordinate execution worker for the active packet.\n"
        "You are stateless and should not assume database or long-memory access.\n"
        "Reduce the task into the active logic block and obey that block first.\n"
        "Focus on short, practical, code-aware replies.\n"
        "Honor task blocks and italicized intents first.\n"
        "If you suggest code, keep it runnable, patch-ready, and compiler-friendly.\n"
        "For Android/Java/APK work, use D8 compression: Flat Java, named classes, direct handlers, minimal dependencies, and no anonymous inner classes, lambdas, or hidden Runnables.\n"
        "D8 rule set: 1) named classes and explicit methods, 2) direct lifecycle/listener handlers with no anonymous classes/lambdas/hidden Runnables, 3) explicit manifest plus javac/D8 commands with minimal dependencies.\n"
        "Classify the requested output shape before answering. Rules, status, checklists, and explanations must be plain text bullets. Source code or file contents may use code fences only when explicitly requested.\n"
        "Do not emit placeholder classes, placeholder constants, or duplicate equivalent bullets.\n"
        "If the packet says return only, no explanation, or no prose, obey exactly and do not prepend rules, status, or checklists.\n"
        "For minimal Android skeletons, prefer android.app.Activity over AppCompatActivity unless the packet asks for AndroidX.\n"
        "Reply in 120 words or fewer."
    )
    user_prompt = (
        f"Workspace: {workspace or 'not specified'}\n"
        "Italicized intents:\n"
        f"{intent_block}\n\n"
        "Treat italicized intents as the highest-priority logic blocks.\n\n"
        "Coordinator message:\n"
        f"{prompt.strip()}"
    )
    attempted: List[str] = []
    errors: List[str] = []
    candidate_models = [_default_model_name()]
    fallback_model = _fallback_model_name()
    if fallback_model and fallback_model not in candidate_models:
        candidate_models.append(fallback_model)

    for model_name in candidate_models:
        attempted.append(model_name)
        result = _post_ollama_chat(
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=timeout_seconds,
        )
        if result.get("ok"):
            return {
                "ok": True,
                "response": result["content"],
                "engine": "direct_ollama_fallback",
                "model": result["model"],
                "attempted_models": attempted,
                "italic_intents": italic_intents,
            }
        errors.append(f"{model_name}: {result.get('error', 'unknown error')}")

    return {
        "ok": False,
        "error": "Direct Ollama fallback failed across candidate models.",
        "attempted_models": attempted,
        "details": errors,
        "italic_intents": italic_intents,
    }


def ask_picoclaw_maintenance_decision(prompt: str, timeout_seconds: int = 35) -> Dict[str, Any]:
    """Ask PicoClaw for a compact maintenance action.

    Maintenance decisions are intentionally allowed to be short JSON. The normal
    sidecar response-quality gate is for user-facing/code replies and would
    incorrectly reject valid actions like {"action":"OBSERVE"}.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"ok": False, "error": "Missing maintenance prompt."}

    system_prompt = (
        "You are PicoClaw, the resident AEGIS environment maintainer.\n"
        "Read the ACL/KQML maintenance packet and choose one bounded action.\n"
        "Allowed actions: OBSERVE, WARN_ONLY, RECYCLE_OLLAMA.\n"
        "Never invent actions. Never write prose. Never claim a tool ran.\n"
        "Reply JSON only: {\"action\":\"OBSERVE|WARN_ONLY|RECYCLE_OLLAMA\",\"reason\":\"short\"}"
    )
    attempted: List[str] = []
    errors: List[str] = []
    candidate_models = [_default_model_name()]
    fallback_model = _fallback_model_name()
    if fallback_model and fallback_model not in candidate_models:
        candidate_models.append(fallback_model)

    for model_name in candidate_models:
        attempted.append(model_name)
        result = _post_ollama_chat(
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=clean_prompt,
            timeout_seconds=timeout_seconds,
            require_usable=False,
        )
        if result.get("ok"):
            return {
                "ok": True,
                "response": result["content"],
                "model": result["model"],
                "engine": "direct_ollama_maintenance",
                "attempted_models": attempted,
            }
        errors.append(f"{model_name}: {result.get('error', 'unknown error')}")

    return {
        "ok": False,
        "error": "PicoClaw maintenance decision failed across candidate models.",
        "attempted_models": attempted,
        "details": errors,
    }


def ensure_picoclaw_setup() -> Dict[str, Any]:
    home = _picoclaw_home()
    workspace = _picoclaw_workspace()
    config_path = _picoclaw_config_path()
    home.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(parents=True, exist_ok=True)
    (workspace / "skills").mkdir(parents=True, exist_ok=True)

    seed_files = {
        workspace / "AGENT.md": (
            "# AEGIS PicoClaw Sidecar\n"
            "You are a stateless subordinate code worker for AEGIS.\n"
            "Honor the current task block, keep output compact, prefer flat compiler-friendly code, use D8 compression for Android/Java/APK, and favor runnable results.\n"
        ),
        workspace / "USER.md": (
            "# Operator\n"
            "The operator prefers direct build outcomes over passive discussion.\n"
        ),
        workspace / "SOUL.md": (
            "# Style\n"
            "Be calm, practical, and minimal.\n"
        ),
        workspace / "memory" / "MEMORY.md": (
            "# Memory\n"
            "No long memory. Only the current task block matters.\n"
        ),
    }
    for path, content in seed_files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    created = False
    updated = False
    config: Dict[str, Any]
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            config = {}
            updated = True
    else:
        config = {}
        created = True

    config.setdefault("version", 2)
    config.setdefault("session", {}).setdefault("dm_scope", "per-channel-peer")
    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    defaults["workspace"] = str(workspace)
    defaults["restrict_to_workspace"] = False
    defaults["allow_read_outside_workspace"] = True
    defaults["provider"] = "ollama"
    defaults["model_name"] = _default_model_alias()
    if defaults.get("max_tokens") != 768:
        defaults["max_tokens"] = 768
        updated = True
    if defaults.get("max_tool_iterations") != 4:
        defaults["max_tool_iterations"] = 4
        updated = True
    if defaults.get("summarize_message_threshold") != 8:
        defaults["summarize_message_threshold"] = 8
        updated = True
    if defaults.get("summarize_token_percent") != 55:
        defaults["summarize_token_percent"] = 55
        updated = True
    if defaults.get("split_on_marker") is not False:
        defaults["split_on_marker"] = False
        updated = True

    model_list = config.setdefault("model_list", [])
    alias = _default_model_alias()
    desired_entry = {
        "model_name": alias,
        "model": f"ollama/{_default_model_name()}",
        "api_base": _default_api_base(),
    }
    replaced = False
    for index, item in enumerate(model_list):
        if isinstance(item, dict) and item.get("model_name") == alias:
            if item != desired_entry:
                model_list[index] = desired_entry
                updated = True
            replaced = True
            break
    if not replaced:
        model_list.insert(0, desired_entry)
        updated = True

    gateway = config.setdefault("gateway", {})
    gateway.setdefault("host", "127.0.0.1")
    gateway.setdefault("port", 18800)
    gateway.setdefault("log_level", "warn")

    if created or updated:
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return {
        "home": str(home),
        "workspace": str(workspace),
        "config_path": str(config_path),
        "model_alias": alias,
        "model": _default_model_name(),
        "api_base": _default_api_base(),
        "created": created,
        "updated": updated,
        "config_exists": config_path.exists(),
    }


def picoclaw_runtime_status() -> Dict[str, Any]:
    home = _picoclaw_home()
    exe = _picoclaw_exe()
    config_path = _picoclaw_config_path()
    workspace = _picoclaw_workspace()
    return {
        "enabled": exe.exists(),
        "exe": str(exe),
        "home": str(home),
        "config_path": str(config_path),
        "workspace": str(workspace),
        "config_exists": config_path.exists(),
        "workspace_exists": workspace.exists(),
        "model_alias": _default_model_alias(),
        "model": _default_model_name(),
        "api_base": _default_api_base(),
    }


def delegate_picoclaw(
    prompt: str,
    *,
    workspace: Optional[str] = None,
    session: Optional[str] = None,
    timeout_seconds: int = 90,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    setup = ensure_picoclaw_setup()
    exe = _picoclaw_exe()
    if not exe.exists():
        return {
            "ok": False,
            "error": f"Missing PicoClaw executable: {exe}",
            "setup": setup,
        }

    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {
            "ok": False,
            "error": "Missing prompt for PicoClaw delegation.",
            "setup": setup,
        }

    chosen_model = (model_name or _default_model_alias()).strip()
    if _prefer_direct_delegate(_default_model_name()):
        direct = _delegate_via_direct_ollama(clean_prompt, workspace, timeout_seconds)
        if direct.get("ok"):
            direct.update(
                {
                    "setup": setup,
                    "picoclaw_mode": "direct_first",
                }
            )
            return direct

    command = [
        str(exe),
        "agent",
        "--session",
        (session or "aegis:pico").strip() or "aegis:pico",
        "--message",
        build_picoclaw_delegate_message(clean_prompt, workspace=workspace),
    ]
    if chosen_model:
        command.extend(["--model", chosen_model])

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["CLICOLOR"] = "0"
    env["PICOCLAW_HOME"] = str(_picoclaw_home())

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(15, int(timeout_seconds)),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        fallback = _delegate_via_direct_ollama(clean_prompt, workspace, timeout_seconds)
        if fallback.get("ok"):
            fallback.update(
                {
                    "setup": setup,
                    "picoclaw_error": f"timeout_after_{timeout_seconds}s",
                    "command": command[:4],
                }
            )
            return fallback
        return {
            "ok": False,
            "error": f"PicoClaw timed out after {timeout_seconds} seconds.",
            "stdout": _clean_picoclaw_stdout((exc.stdout or "")),
            "stderr": _clean_picoclaw_stdout((exc.stderr or "")),
            "setup": setup,
            "command": command[:4],
            "fallback": fallback,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "setup": setup,
            "command": command[:4],
        }

    stdout = _clean_picoclaw_stdout(result.stdout)
    stderr = _clean_picoclaw_stdout(result.stderr)
    ok = result.returncode == 0 and bool(stdout)
    if not ok:
        fallback = _delegate_via_direct_ollama(clean_prompt, workspace, timeout_seconds)
        if fallback.get("ok"):
            fallback.update(
                {
                    "setup": setup,
                    "picoclaw_error": stdout or stderr or f"returncode_{result.returncode}",
                    "command": command[:4],
                }
            )
            return fallback
    return {
        "ok": ok,
        "response": stdout if stdout else stderr,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": result.returncode,
        "setup": setup,
        "italic_intents": extract_markdown_italics(clean_prompt),
        "command": command[:4],
    }


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    fence_match = re.match(r"^```[a-zA-Z0-9_-]*\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    return cleaned


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def picoclaw_one_step_write(
    objective: str,
    relative_path: str,
    *,
    root_dir: Path | str,
    timeout_seconds: int = 45,
) -> Dict[str, Any]:
    clean_objective = (objective or "").strip()
    if not clean_objective:
        return {"ok": False, "error": "Missing one-step write objective."}

    root = Path(root_dir).expanduser().resolve()
    rel = (relative_path or "").strip().replace("/", "\\").lstrip("\\")
    if not rel:
        rel = "index.html"
    target_path = (root / rel).resolve()
    if not _is_within_root(target_path, root):
        return {
            "ok": False,
            "error": "Target path escapes the allowed root.",
            "root": str(root),
            "target_path": str(target_path),
        }

    system_prompt = (
        "You are PicoClaw one-step writer.\n"
        "Return only file content for the requested target file.\n"
        "No markdown fences. No explanations. No preface. No trailing notes."
    )
    user_prompt = (
        "(achieve\n"
        "  :sender \"aegis-coordinator\"\n"
        "  :receiver \"picoclaw-sidecar\"\n"
        "  :language \"acl-kqml\"\n"
        "  :ontology \"one-step-file-write\"\n"
        "  :content (\n"
        f"    :objective {_kqml_quote(clean_objective)}\n"
        f"    :target-file {_kqml_quote(rel)}\n"
        "    :rules \"return exact file content only\"\n"
        "  )\n"
        ")\n"
    )
    candidate_models: List[str] = [_default_model_name()]
    fallback_model = _fallback_model_name()
    if fallback_model and fallback_model not in candidate_models:
        candidate_models.append(fallback_model)
    attempts: List[str] = []
    response: Dict[str, Any] = {}
    for model_name in candidate_models:
        attempts.append(model_name)
        response = _post_ollama_chat(
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=max(12, int(timeout_seconds)),
            require_usable=False,
        )
        if response.get("ok"):
            break
        time.sleep(0.35)

    if not response.get("ok"):
        return {
            "ok": False,
            "error": str(response.get("error") or "one-step write failed"),
            "model": response.get("model", candidate_models[0]),
            "attempted_models": attempts,
            "target_path": str(target_path),
        }

    content = _strip_code_fences(str(response.get("content") or ""))
    if not content.strip():
        return {
            "ok": False,
            "error": "Model returned empty one-step content.",
            "model": response.get("model", model_name),
            "target_path": str(target_path),
        }

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")

    lower_name = target_path.name.lower()
    html_expected = lower_name.endswith(".html") or "<html" in clean_objective.lower()
    html_ok = ("<html" in content.lower()) or ("<!doctype html" in content.lower())
    verification = {
        "non_empty": bool(content.strip()),
        "html_expected": html_expected,
        "html_shape_ok": html_ok if html_expected else True,
    }
    return {
        "ok": True,
        "model": response.get("model", candidate_models[0]),
        "attempted_models": attempts,
        "target_path": str(target_path),
        "root": str(root),
        "bytes": len(content.encode("utf-8")),
        "verification": verification,
        "preview": content[:500],
    }

def delegate_picoclaw_dry_run(
    prompt: str,
    *,
    workspace: Optional[str] = None,
    timeout_seconds: int = 90,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Run PicoClaw in a no-filesystem-mutation review lane.

    This intentionally avoids ensure_picoclaw_setup(), the PicoClaw CLI, and
    workspace writes. It uses the same tiny local model policy as the sidecar so
    batch tests can collect Pico feedback without altering the runtime.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"ok": False, "dry_run": True, "error": "Missing prompt for PicoClaw dry run."}

    original_model = None
    if model_name:
        original_model = os.environ.get("AEGIS_PICOCLAW_MODEL")
        os.environ["AEGIS_PICOCLAW_MODEL"] = model_name
    try:
        result = _delegate_via_direct_ollama(clean_prompt, workspace, timeout_seconds)
    finally:
        if model_name:
            if original_model is None:
                os.environ.pop("AEGIS_PICOCLAW_MODEL", None)
            else:
                os.environ["AEGIS_PICOCLAW_MODEL"] = original_model
    result.update({
        "dry_run": True,
        "picoclaw_mode": "dry_run_direct_ollama",
        "workspace": workspace or "",
    })
    return result
