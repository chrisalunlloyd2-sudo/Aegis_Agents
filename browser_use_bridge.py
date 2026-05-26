"""
Helpers for isolated browser-use runs inside the dedicated venv.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import for standalone use
    load_dotenv = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _ensure_env_loaded() -> None:
    if load_dotenv is not None:
        load_dotenv(_repo_root() / ".env", override=False)


def _browser_use_python() -> Path:
    _ensure_env_loaded()
    raw = os.getenv("AEGIS_BROWSER_USE_PYTHON", "").strip()
    if raw:
        return Path(raw)
    return _repo_root() / "vendor" / "browser_use_venv" / "Scripts" / "python.exe"


def _worker_script() -> Path:
    return _repo_root() / "browser_use_worker.py"


def _default_browser_model() -> str:
    _ensure_env_loaded()
    return (
        os.getenv("AEGIS_BROWSER_USE_MODEL", "").strip()
        or os.getenv("AEGIS_LOCAL_TOOL_FALLBACK_MODEL", "").strip()
        or os.getenv("AEGIS_LOCAL_PRIMARY_MODEL", "").strip()
        or "aegis-gemma2-abliterated:2b-q8"
    )


def _default_ollama_base_url() -> str:
    _ensure_env_loaded()
    return os.getenv("AEGIS_BROWSER_USE_OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip() or "http://127.0.0.1:11434"


def browser_use_runtime_status() -> Dict[str, Any]:
    python_exe = _browser_use_python()
    worker = _worker_script()
    return {
        "enabled": python_exe.exists() and worker.exists(),
        "python": str(python_exe),
        "worker_script": str(worker),
        "python_exists": python_exe.exists(),
        "worker_exists": worker.exists(),
        "model": _default_browser_model(),
        "ollama_base_url": _default_ollama_base_url(),
    }


def run_browser_use_task(
    task: str,
    *,
    start_url: Optional[str] = None,
    allowed_domains: Optional[List[str]] = None,
    headless: bool = True,
    max_steps: int = 10,
    timeout_seconds: int = 240,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    runtime = browser_use_runtime_status()
    if not runtime["enabled"]:
        return {
            "ok": False,
            "error": "browser-use runtime is not ready.",
            "runtime": runtime,
        }

    task_text = (task or "").strip()
    if not task_text:
        return {
            "ok": False,
            "error": "Missing browser task.",
            "runtime": runtime,
        }

    allowed = [item for item in (allowed_domains or []) if item]
    payload = {
        "task": task_text,
        "start_url": (start_url or "").strip() or None,
        "allowed_domains": allowed,
        "headless": bool(headless),
        "max_steps": max(1, min(int(max_steps), 25)),
        "workspace": (workspace or "").strip() or None,
        "model": _default_browser_model(),
        "ollama_base_url": _default_ollama_base_url(),
    }

    with tempfile.TemporaryDirectory(prefix="aegis_browser_use_") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        request_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        command = [
            runtime["python"],
            runtime["worker_script"],
            str(request_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(30, int(timeout_seconds)),
            )
        except subprocess.TimeoutExpired as exc:
            partial_stdout = (exc.stdout or "").strip()
            partial_stderr = (exc.stderr or "").strip()
            if partial_stdout:
                try:
                    payload = json.loads(partial_stdout)
                    payload.setdefault("ok", False)
                    payload["error"] = payload.get("error") or f"browser-use timed out after {timeout_seconds} seconds."
                    payload["stdout"] = partial_stdout
                    payload["stderr"] = partial_stderr
                    payload["runtime"] = runtime
                    return payload
                except Exception:
                    pass
            return {
                "ok": False,
                "error": f"browser-use timed out after {timeout_seconds} seconds.",
                "stdout": partial_stdout,
                "stderr": partial_stderr,
                "runtime": runtime,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "runtime": runtime,
            }

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        try:
            payload = json.loads(stdout) if stdout else {}
        except Exception:
            payload = {
                "ok": result.returncode == 0,
                "summary": stdout or stderr or "browser-use returned no structured output.",
            }
        payload.setdefault("ok", result.returncode == 0)
        payload["returncode"] = result.returncode
        payload["stderr"] = stderr
        payload["runtime"] = runtime
        return payload
