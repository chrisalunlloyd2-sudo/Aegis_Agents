"""
Aider terminal lane for AEGIS.

This is not a hidden tool orchestrator. It starts Aider as the coding agent,
records the terminal evidence, and exposes the run state for the Web UI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent
AIDER_RUNS_DIR = REPO_ROOT / "agentic_jobs" / "aider_terminal"


def _safe_project(project: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in (project or "general")).strip("-")
    return cleaned or "general"


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _python_exe() -> str:
    configured = os.getenv("AEGIS_AIDER_PYTHON", "").strip()
    if configured and Path(configured).exists():
        return configured
    default = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe"
    if default.exists():
        return str(default)
    return "python"


def _aider_command() -> Optional[List[str]]:
    configured = os.getenv("AEGIS_AIDER_COMMAND", "").strip()
    if configured:
        return [configured]
    vendored = REPO_ROOT / "vendor" / "aider_venv" / "Scripts" / "aider.exe"
    if vendored.exists():
        return [str(vendored)]
    aider_path = shutil.which("aider")
    if aider_path:
        return [aider_path]
    py = _python_exe()
    try:
        probe = subprocess.run(
            [py, "-m", "aider", "--version"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if probe.returncode == 0:
            return [py, "-m", "aider"]
    except Exception:
        pass
    return None


def build_aider_context(project: str) -> str:
    """Build a compact context packet from Fabric/RAM/DB for Aider."""
    lines = [
        "AEGIS AIDER CONTEXT PACKET",
        f"timestamp: {_now()}",
        f"project: {_safe_project(project)}",
        "",
        "Role split:",
        "- Aider is the coding agent and terminal actor.",
        "- AEGIS Web UI records terminal evidence, stdout/stderr, diffs, and summaries.",
        "- Fabric/RAM/DB provide context only; they do not replace Aider's code editing.",
        "",
    ]
    try:
        from fabric_wisdom_store import build_fabric_guidance_block, fabric_wisdom_status

        lines.append(build_fabric_guidance_block(project=project, limit=8, prune=True))
        lines.append("")
        lines.append("Fabric status:")
        lines.append(json.dumps(fabric_wisdom_status(project=project), ensure_ascii=True, indent=2, default=str)[:2500])
    except Exception as exc:
        lines.append(f"Fabric context unavailable: {exc}")
    try:
        from ram_working_memory import RamWorkingMemory

        ram = RamWorkingMemory()
        lines.append("")
        lines.append("RAM working memory status:")
        lines.append(json.dumps(ram.status(), ensure_ascii=True, indent=2, default=str)[:2500])
    except Exception as exc:
        lines.append(f"RAM context unavailable: {exc}")
    try:
        from knowledge_library_pipeline import search as search_knowledge_library

        hits = search_knowledge_library("tool calling code editing tests evidence", project=project, limit=5)
        lines.append("")
        lines.append("Knowledge library hits:")
        lines.append(json.dumps(hits, ensure_ascii=True, indent=2, default=str)[:3500])
    except Exception as exc:
        lines.append(f"Knowledge library context unavailable: {exc}")
    return "\n".join(lines).strip() + "\n"


@dataclass
class AiderRun:
    job_id: str
    project: str
    prompt: str
    cwd: str
    run_dir: Path
    command: List[str]
    started_at: str = field(default_factory=_now)
    finished_at: Optional[str] = None
    status: str = "running"
    returncode: Optional[int] = None
    output_tail: List[str] = field(default_factory=list)
    error: str = ""
    process: Optional[subprocess.Popen] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project": self.project,
            "prompt": self.prompt,
            "cwd": self.cwd,
            "run_dir": str(self.run_dir),
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "returncode": self.returncode,
            "output_tail": self.output_tail[-120:],
            "error": self.error,
            "disclaimer": (
                "Aider terminal lane: this is where the coding agent is typing. "
                "Terminal output is recorded as evidence and may include stdout, stderr, diffs, tests, and prompts."
            ),
        }


class AiderTerminalLane:
    def __init__(self) -> None:
        self._jobs: Dict[str, AiderRun] = {}
        self._lock = threading.Lock()

    def status(self) -> Dict[str, Any]:
        command = _aider_command()
        return {
            "available": command is not None,
            "command": command or [],
            "runs_dir": str(AIDER_RUNS_DIR),
            "active_jobs": [
                job.to_public_dict()
                for job in self._jobs.values()
                if job.status == "running"
            ],
        }

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.started_at, reverse=True)
            return [job.to_public_dict() for job in jobs[: max(1, min(limit, 100))]]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_public_dict() if job else None

    def stop_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"ok": False, "error": "Aider job not found."}
        if job.process and job.status == "running":
            job.process.terminate()
            job.status = "stopping"
            return {"ok": True, "status": "stopping", "job_id": job_id}
        return {"ok": True, "status": job.status, "job_id": job_id}

    def start_run(
        self,
        *,
        prompt: str,
        project: str = "general",
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        dry_run: bool = True,
        read_only: bool = True,
    ) -> Dict[str, Any]:
        command_base = _aider_command()
        if not command_base:
            return {
                "ok": False,
                "error": "Aider is not installed or not available on PATH/module path.",
                "install_ready_wheels": str(REPO_ROOT / "vendor" / "downloads" / "python_wheels"),
            }
        clean_project = _safe_project(project)
        job_id = f"aider-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        run_dir = AIDER_RUNS_DIR / clean_project / job_id
        run_dir.mkdir(parents=True, exist_ok=True)
        context_path = run_dir / "aegis_context.txt"
        message_path = run_dir / "message.txt"
        output_path = run_dir / "terminal_output.txt"
        metadata_path = run_dir / "metadata.json"
        target_cwd = str(Path(cwd or REPO_ROOT).resolve())
        context = build_aider_context(clean_project)
        context_path.write_text(context, encoding="utf-8")
        message = (
            prompt.strip()
            + "\n\n"
            + "Use the attached AEGIS context packet as read-only project context. "
            + "Show terminal-visible evidence for actions, diffs, tests, and failures. "
            + "Do not claim success unless terminal/test evidence supports it.\n"
            + f"\nContext file: {context_path}\n"
        )
        message_path.write_text(message, encoding="utf-8")

        aider_model = (model or os.getenv("AEGIS_AIDER_MODEL") or "ollama_chat/qwen2.5:3b").strip()
        command = command_base + [
            "--model",
            aider_model,
            "--message-file",
            str(message_path),
            "--read",
            str(context_path),
            "--no-auto-commits",
            "--no-attribute-author",
            "--no-attribute-committer",
            "--no-gitignore",
            "--no-check-update",
            "--no-show-release-notes",
            "--analytics-disable",
            "--skip-sanity-check-repo",
            "--map-tokens",
            "0",
            "--exit",
            "--no-pretty",
            "--stream",
            "--timeout",
            os.getenv("AEGIS_AIDER_TIMEOUT", "240"),
        ]
        if dry_run:
            command.append("--dry-run")
        if read_only:
            command.extend(["--read", str(REPO_ROOT / "AEGIS_MASTER_SEQUENCE_AIDER_SOAP_GENETIC_CODER.txt")])

        env = os.environ.copy()
        env.setdefault("OLLAMA_API_BASE", os.getenv("AEGIS_OLLAMA_API_BASE", "http://127.0.0.1:11434"))
        env.setdefault("AIDER_ANALYTICS_DISABLE", "1")
        env.setdefault("NO_COLOR", "1")
        env.setdefault("CLICOLOR", "0")

        job = AiderRun(
            job_id=job_id,
            project=clean_project,
            prompt=prompt,
            cwd=target_cwd,
            run_dir=run_dir,
            command=command,
        )
        metadata_path.write_text(json.dumps(job.to_public_dict(), indent=2, ensure_ascii=True), encoding="utf-8")
        with self._lock:
            self._jobs[job_id] = job

        def worker() -> None:
            try:
                with output_path.open("w", encoding="utf-8", errors="replace") as output:
                    output.write(job.to_public_dict()["disclaimer"] + "\n\n")
                    output.write("$ " + " ".join(command) + "\n\n")
                    output.flush()
                    process = subprocess.Popen(
                        command,
                        cwd=target_cwd,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    job.process = process
                    assert process.stdout is not None
                    for line in process.stdout:
                        output.write(line)
                        output.flush()
                        clean_line = line.rstrip("\n")
                        if clean_line:
                            job.output_tail.append(clean_line[-1000:])
                            job.output_tail = job.output_tail[-160:]
                    job.returncode = process.wait()
                    job.status = "completed" if job.returncode == 0 else "failed"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.finished_at = _now()
                metadata_path.write_text(json.dumps(job.to_public_dict(), indent=2, ensure_ascii=True), encoding="utf-8")

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, **job.to_public_dict()}


aider_terminal_lane = AiderTerminalLane()
