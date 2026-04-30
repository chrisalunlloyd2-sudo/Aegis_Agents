"""
Local time-boxed program builder loop for AEGIS.

This module provides a background job executor that can:
- research a build objective
- create an implementation plan
- generate or revise a small local program
- run verification
- iterate through fix cycles until tests pass or the time budget expires

The CPU target is cooperative rather than hard enforced. The loop throttles by
sleeping between heavy model/test steps so the workstation stays usable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ollama

from aegis_toolkit import score_source_credibility
from agentic_crawler_db import crawler_db
from agentic_loop_controller import SubTask
from coding_kernels import build_language_runtime_profile
from context_policy import PROGRAM_LOOP_CONTEXT_WINDOW
from systems_kernels import build_systems_kernel_brief
from project_lenses import load_runtime_directive
from timescale_memory import memory as timescale_memory
from vector_memory import vector_memory


@dataclass
class ACLPacket:
    performative: str
    conversation_id: str
    reply_with: str
    in_reply_to: str
    ontology: str
    language: str
    phase: str
    cycle: int
    worker_name: str
    parallel_group: str
    priority: str
    files_to_touch: List[str]
    token_budget: int
    content: str


def _slugify(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", (value or "").strip())
    clean = clean.strip("-")
    return clean[:80] or "program"


def default_program_target_dir(base_dir: Path, project: str, objective: str) -> Path:
    project_slug = _slugify(project or "general")
    objective_slug = _slugify(re.sub(r"\s+", " ", objective or "").strip())[:64]
    if not objective_slug:
        objective_slug = "program"
    return (Path(base_dir) / "agentic_jobs" / "program_workspaces" / project_slug / objective_slug).resolve()


def _cycle_from_step(description: str) -> int:
    match = re.search(r"\b(\d+)\b", description or "")
    return int(match.group(1)) if match else 1


def _extract_json_object(text: str) -> Dict:
    source = (text or "").strip()
    if not source:
        return {}
    if "```json" in source:
        source = source.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in source:
        source = source.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(source)
    except Exception:
        start = source.find("{")
        end = source.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(source[start : end + 1])
            except Exception:
                return {}
    return {}


def _load_project_directive(base_dir: Path, project: str) -> str:
    return load_runtime_directive(
        base_dir,
        project=project,
        include_global=True,
        include_guardian_fallback=True,
    )


def _throttle_delay(cpu_target: int) -> float:
    cpu_target = max(10, min(cpu_target, 90))
    return max(1.0, min(6.0, round((100 - cpu_target) / 14.0, 1)))


def _chat_json(model: str, system_prompt: str, user_prompt: str, num_predict: int = 900) -> Dict:
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
        options={
            "temperature": 0.2,
            "num_ctx": PROGRAM_LOOP_CONTEXT_WINDOW,
            "num_predict": num_predict,
        },
        format="json",
    )
    content = ((response.get("message") or {}).get("content") or "").strip()
    return _extract_json_object(content)


def _trim_text(value: str, limit: int = 4000) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[trimmed]"


def _path_matches_scope(rel_path: str, include_paths: List[str]) -> bool:
    if not include_paths:
        return True
    normalized = rel_path.replace("\\", "/").strip("/")
    for raw in include_paths:
        candidate = str(raw or "").replace("\\", "/").strip().strip("/")
        if not candidate:
            continue
        if normalized == candidate:
            return True
        if normalized.startswith(candidate + "/"):
            return True
        if candidate.startswith(normalized + "/"):
            return True
    return False


def _load_workspace_files(workspace_dir: Path) -> List[Tuple[str, str]]:
    files: List[Tuple[str, str]] = []
    skip_dirs = {
        "__pycache__",
        "artifacts",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
    }
    skip_names = {
        "directive_snapshot.txt",
        "research.md",
        "coding_kernel.txt",
        "task_hints.txt",
        "language_profile.json",
        "objective.txt",
        "project.txt",
        "BUILD_REPORT.md",
    }
    for path in sorted(workspace_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.name in skip_names or path.name.endswith((".pyc", ".pyo")):
            continue
        rel = path.relative_to(workspace_dir)
        rel_posix = rel.as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append((rel_posix, text))
    return files


def _read_workspace_snapshot(
    workspace_dir: Path,
    max_chars_per_file: int = 5000,
    *,
    include_paths: Optional[List[str]] = None,
    max_total_chars: int = 18000,
    workspace_files: Optional[List[Tuple[str, str]]] = None,
) -> str:
    files: List[str] = []
    entries = workspace_files if workspace_files is not None else _load_workspace_files(workspace_dir)
    for rel_posix, text in entries:
        if include_paths and not _path_matches_scope(rel_posix, include_paths):
            continue
        files.append(f"FILE: {rel_posix}\n{text[:max_chars_per_file]}\n")
    return "\n".join(files)[:max_total_chars]


def _write_workspace_snapshot_file(
    workspace_dir: Path,
    *,
    job_id: str,
    project: str,
    objective: str,
    language_profile: Dict[str, Any],
    state: Dict[str, object],
    phase: str,
    cycle: int,
    max_cycles: int,
    cpu_target: int,
    hours: int,
    note: str = "",
) -> None:
    last_plan = state.get("last_plan") if isinstance(state.get("last_plan"), dict) else {}
    last_logic_table = state.get("last_logic_table") if isinstance(state.get("last_logic_table"), dict) else {}
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "project": project,
        "objective": objective,
        "workspace": str(workspace_dir),
        "language": language_profile.get("language"),
        "language_label": language_profile.get("language_label"),
        "phase": phase,
        "cycle": cycle,
        "max_cycles": max_cycles,
        "cpu_target": cpu_target,
        "hours": hours,
        "task_hints": language_profile.get("task_hints") or [],
        "written_files": list(state.get("written_files") or [])[:24],
        "last_test_ok": bool(state.get("last_test_ok")),
        "last_test_runner": str(state.get("last_test_runner") or ""),
        "last_test_excerpt": _trim_text(str(state.get("last_test_output") or ""), 900),
        "plan_summary": str(last_plan.get("summary") or ""),
        "files_to_touch": list(last_plan.get("files_to_touch") or [])[:24],
        "subtask_count": len(state.get("last_acl_subtasks") or []),
        "logic_block_count": len(last_logic_table.get("logic_blocks") or []),
        "logic_table_path": str(state.get("logic_table_path") or ""),
        "report_path": str(state.get("report_path") or ""),
        "timebox_exhausted": bool(state.get("timebox_exhausted")),
        "note": note,
    }
    latest_path = workspace_dir / "LATEST_SNAPSHOT.json"
    artifact_path = workspace_dir / "artifacts" / f"snapshot_{phase.lower()}_{cycle:02d}.json"
    serialized = json.dumps(payload, indent=2)
    latest_path.write_text(serialized + "\n", encoding="utf-8")
    artifact_path.write_text(serialized + "\n", encoding="utf-8")


def _fallback_program_files(objective: str, cycle: int, language_profile: Dict[str, Any]) -> Dict[str, str]:
    title = objective.strip() or "AEGIS Program"
    language = str(language_profile.get("language") or "python")
    if language == "java_android":
        return {
            "README.md": (
                f"# Android D8 Prototype\n\n"
                f"Objective: {title}\n\n"
                f"This fallback scaffold was generated during cycle {cycle} with D8 compression rules: Flat Java, named classes, direct handlers, and minimal dependencies.\n"
            ),
            "AndroidManifest.xml": (
                "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\" package=\"com.aegis.prototype\">\n"
                "    <application android:theme=\"@android:style/Theme.Material.Light.NoActionBar\" android:label=\"AEGIS Prototype\">\n"
                "        <activity android:name=\".MainActivity\" android:exported=\"true\">\n"
                "            <intent-filter>\n"
                "                <action android:name=\"android.intent.action.MAIN\" />\n"
                "                <category android:name=\"android.intent.category.LAUNCHER\" />\n"
                "            </intent-filter>\n"
                "        </activity>\n"
                "    </application>\n"
                "</manifest>\n"
            ),
            "src/MainActivity.java": (
                "package com.aegis.prototype;\n\n"
                "import android.app.Activity;\n"
                "import android.os.Bundle;\n"
                "import android.widget.TextView;\n\n"
                "public final class MainActivity extends Activity {\n"
                "    private static final String OBJECTIVE = " + json.dumps(title) + ";\n\n"
                "    @Override\n"
                "    public void onCreate(Bundle savedInstanceState) {\n"
                "        super.onCreate(savedInstanceState);\n"
                "        TextView view = new TextView(this);\n"
                "        view.setText(buildMessage());\n"
                "        setContentView(view);\n"
                "    }\n\n"
                "    public static String buildMessage() {\n"
                "        return \"AEGIS prototype ready for: \" + OBJECTIVE;\n"
                "    }\n"
                "}\n"
            ),
            "build_d8.ps1": (
                "$ErrorActionPreference = 'Stop'\n"
                "$AndroidHome = $env:ANDROID_HOME\n"
                "if (-not $AndroidHome) { throw 'ANDROID_HOME must point to an Android SDK before D8 packaging can run.' }\n"
                "$PlatformRoot = Join-Path $AndroidHome 'platforms'\n"
                "$Platform = Get-ChildItem -Path $PlatformRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1\n"
                "if (-not $Platform) { throw 'No Android SDK platform found under ANDROID_HOME\platforms.' }\n"
                "$AndroidJar = Join-Path $Platform.FullName 'android.jar'\n"
                "New-Item -ItemType Directory -Force -Path 'build\classes', 'build\dex' | Out-Null\n"
                "javac -classpath $AndroidJar -d build\classes src\MainActivity.java\n"
                "d8 --lib $AndroidJar --output build\dex build\classes\com\aegis\prototype\MainActivity.class\n"
                "Write-Host 'D8 wrote build\dex\classes.dex'\n"
            ),
        }
    if language == "javascript":
        return {
            "README.md": (
                f"# Program Prototype\n\n"
                f"Objective: {title}\n\n"
                f"This fallback scaffold was generated during cycle {cycle} so the loop has a runnable baseline.\n"
            ),
            "src/index.js": (
                "const OBJECTIVE = " + json.dumps(title) + ";\n\n"
                "function buildMessage() {\n"
                "  return `AEGIS prototype ready for: ${OBJECTIVE}`;\n"
                "}\n\n"
                "module.exports = { buildMessage };\n\n"
                "if (require.main === module) {\n"
                "  console.log(buildMessage());\n"
                "}\n"
            ),
            "tests/index.test.js": (
                "const test = require('node:test');\n"
                "const assert = require('node:assert/strict');\n"
                "const { buildMessage } = require('../src/index.js');\n\n"
                "test('buildMessage includes the objective', () => {\n"
                "  assert.match(buildMessage(), /AEGIS prototype ready for:/);\n"
                "});\n"
            ),
        }
    if language == "powershell":
        return {
            "README.md": (
                f"# Program Prototype\n\n"
                f"Objective: {title}\n\n"
                f"This fallback scaffold was generated during cycle {cycle} so the loop has a runnable baseline.\n"
            ),
            "main.ps1": (
                "$Objective = " + json.dumps(title) + "\n\n"
                "function Get-AegisMessage {\n"
                "    [CmdletBinding()]\n"
                "    param()\n"
                "    \"AEGIS prototype ready for: $Objective\"\n"
                "}\n\n"
                "Get-AegisMessage\n"
            ),
        }
    if language == "bash":
        return {
            "README.md": (
                f"# Program Prototype\n\n"
                f"Objective: {title}\n\n"
                f"This fallback scaffold was generated during cycle {cycle} so the loop has a runnable baseline.\n"
            ),
            "main.sh": (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n\n"
                "objective=" + json.dumps(title) + "\n"
                "printf 'AEGIS prototype ready for: %s\\n' \"$objective\"\n"
            ),
        }
    return {
        "README.md": (
            f"# Program Prototype\n\n"
            f"Objective: {title}\n\n"
            f"This fallback scaffold was generated during cycle {cycle} so the loop has a runnable baseline.\n"
        ),
        "app.py": (
            "from __future__ import annotations\n\n"
            "import sys\n\n"
            "OBJECTIVE = " + repr(title) + "\n\n"
            "def build_message() -> str:\n"
            "    return f\"AEGIS prototype ready for: {OBJECTIVE}\"\n\n"
            "def main(argv: list[str] | None = None) -> int:\n"
            "    print(build_message())\n"
            "    return 0\n\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(main(sys.argv[1:]))\n"
        ),
        "tests/test_app.py": (
            "import io\n"
            "import unittest\n"
            "from contextlib import redirect_stdout\n\n"
            "from app import build_message, main\n\n"
            "class TestApp(unittest.TestCase):\n"
            "    def test_build_message_contains_objective(self):\n"
            "        msg = build_message()\n"
            "        self.assertIn('AEGIS prototype ready for:', msg)\n\n"
            "    def test_main_returns_zero(self):\n"
            "        stream = io.StringIO()\n"
            "        with redirect_stdout(stream):\n"
            "            self.assertEqual(main([]), 0)\n"
            "        self.assertIn('AEGIS prototype ready for:', stream.getvalue())\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        ),
    }


def _write_program_files(workspace_dir: Path, files_payload: Dict[str, str]) -> List[str]:
    written: List[str] = []
    for relative_path, content in files_payload.items():
        clean_rel = str(relative_path).replace("\\", "/").strip().lstrip("/")
        if not clean_rel or clean_rel.startswith(".."):
            continue
        target = workspace_dir / clean_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(clean_rel)
    return written


def _resolve_verification_commands(language_profile: Dict[str, Any]) -> List[List[str]]:
    python_exe = os.environ.get("PYTHON_EXE") or "python"
    commands: List[List[str]] = []
    for raw_command in language_profile.get("verification_commands") or []:
        command = [str(part).replace("{python_exe}", python_exe) for part in raw_command]
        executable = command[0]
        if os.path.isabs(executable) or shutil.which(executable):
            commands.append(command)
    return commands


def _run_tests(workspace_dir: Path, language_profile: Dict[str, Any]) -> Tuple[bool, str, str]:
    test_env = os.environ.copy()
    test_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    common_kwargs = {
        "cwd": str(workspace_dir),
        "capture_output": True,
        "text": True,
        "timeout": 120,
        "shell": False,
        "env": test_env,
    }
    if os.name == "nt" and hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
        common_kwargs["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS

    commands = _resolve_verification_commands(language_profile)
    if not commands:
        return False, str(language_profile.get("verification_label") or "static-review"), "No executable verification command is configured for this language profile."

    outputs: List[str] = []
    success_patterns = {
        "python": r"\bRan\s+[1-9]\d*\s+test|\bpassed\b",
        "javascript": r"\bpass\b|\bok\b",
        "typescript": r"\bFound 0 errors\b|\bpass\b|\bok\b",
        "java_android": r"\bd8\b|\bdex\b|\bclasses\.dex\b|\bjavac\s+\d|\bok\b|\bsuccess\b",
    }
    language = str(language_profile.get("language") or "python")
    pattern = success_patterns.get(language, r"\bpass\b|\bok\b|\bsuccess\b")

    for command in commands:
        result = subprocess.run(command, **common_kwargs)
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        label = " ".join(command)
        outputs.append(f"[{label}]\n{output.strip()}".strip())
        if result.returncode == 0:
            stripped = output.strip()
            if not stripped or re.search(pattern, stripped, flags=re.IGNORECASE):
                return True, label, stripped

    return False, str(language_profile.get("verification_label") or "verification"), "\n\n".join(part for part in outputs if part.strip()).strip()


def _normalize_relative_paths(raw_paths: Any) -> List[str]:
    normalized: List[str] = []
    values = raw_paths if isinstance(raw_paths, list) else [raw_paths]
    for raw_path in values:
        clean = str(raw_path or "").replace("\\", "/").strip().lstrip("/")
        if clean and not clean.startswith("..") and clean not in normalized:
            normalized.append(clean)
    return normalized


def _string_list(value: Any, *, limit: int = 12) -> List[str]:
    items: List[str] = []
    values = value if isinstance(value, list) else [value]
    for raw in values:
        if isinstance(raw, dict):
            raw = raw.get("goal") or raw.get("summary") or raw.get("name") or json.dumps(raw, ensure_ascii=False)
        text = str(raw or "").strip()
        if not text:
            continue
        for part in re.split(r"(?:\r?\n|;)", text):
            clean = re.sub(r"\s+", " ", part or "").strip(" -\t\r\n")
            if clean and clean not in items:
                items.append(clean)
                if len(items) >= limit:
                    return items
    return items


def _select_logic_block(logic_table: Dict[str, Any], subtask: Dict[str, Any]) -> Dict[str, Any]:
    blocks = logic_table.get("logic_blocks") if isinstance(logic_table, dict) else None
    if not isinstance(blocks, list):
        return {}

    target_id = _slugify(str(subtask.get("logic_block_id") or subtask.get("name") or ""))
    target_files = set(_normalize_relative_paths(subtask.get("files_to_touch") or []))
    best_match: Dict[str, Any] = {}
    best_score = -1

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = _slugify(str(block.get("id") or block.get("name") or ""))
        block_files = set(_normalize_relative_paths(block.get("files_to_touch") or []))
        score = 0
        if target_id and block_id == target_id:
            score += 4
        if target_files and block_files:
            score += len(target_files.intersection(block_files))
        if score > best_score:
            best_match = block
            best_score = score

    return best_match if best_score > 0 else {}


def _build_logic_table(
    *,
    objective: str,
    project: str,
    plan: Dict[str, Any],
    language_profile: Dict[str, Any],
    workspace_dir: Path,
    cycle: int,
    max_cycles: int,
    subtasks: List[Dict[str, Any]],
    research_results: List[Dict[str, Any]],
    prior_test_output: str,
) -> Dict[str, Any]:
    ask_set = _string_list(
        plan.get("ask_set")
        or [
            objective,
            plan.get("summary") or "",
            plan.get("success_criteria") or "",
        ],
        limit=10,
    )
    if not ask_set:
        ask_set = [objective.strip() or "Build the requested program."]

    program_set = _string_list(plan.get("program_set"), limit=10)
    if not program_set:
        program_set = _string_list(
            [plan.get("architecture") or ""]
            + [f"Own file set: {', '.join(item.get('files_to_touch') or [])}" for item in subtasks],
            limit=10,
        )

    axioms = _string_list(plan.get("axioms"), limit=8)
    if not axioms:
        axioms = [
            f"Use {language_profile.get('language_label') or 'the primary language'} as the default implementation lane unless the objective overrides it.",
            "Each logic block owns explicit files and can be revised independently when possible.",
            "Prefer the smallest runnable, testable structure over ornamental abstraction.",
            "Latest verification output overrides stale assumptions during fix cycles.",
        ]

    constraints = _string_list(plan.get("constraints"), limit=8)
    if not constraints:
        constraints = [
            f"Stay inside stable workspace {workspace_dir}.",
            "Only edit files owned by the active logic block.",
            "Keep outputs complete, runnable, and aligned with local verification.",
            f"Cycle {cycle} of {max_cycles}: prioritize the blockers that prevent the program from running.",
        ]

    acceptance_tests = _string_list(
        plan.get("acceptance_tests")
        or [
            plan.get("success_criteria") or "",
            plan.get("test_strategy") or "",
        ],
        limit=8,
    )
    if not acceptance_tests:
        acceptance_tests = [
            "The program runs locally.",
            "Verification passes with the simplest native test path available.",
        ]

    compression_rules = _string_list(plan.get("compression_rules"), limit=6)
    if not compression_rules:
        compression_rules = [
            "Prefer flat, compiler-friendly control flow and direct data paths.",
            "Avoid placeholder scaffolding, dead wrappers, and unnecessary nesting.",
            "Return complete replacement file contents rather than fragments.",
        ]
    if str(language_profile.get("language") or "") == "java_android":
        d8_rules = [
            "D8/Android: keep Java flat with explicit named classes and direct handlers.",
            "D8/Android: avoid anonymous inner classes, lambdas, hidden Runnables, reflection-heavy glue, and dependency-heavy wrappers.",
            "D8/Android: keep manifest, permissions, SDK flags, and javac/D8 commands explicit.",
        ]
        compression_rules = (d8_rules + [rule for rule in compression_rules if rule not in d8_rules])[:6]

    web_synthesis_targets = _string_list(plan.get("web_synthesis_targets"), limit=6)
    if not web_synthesis_targets:
        for item in research_results[:3]:
            title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
            url = str(item.get("url") or "").strip()
            if title and url:
                web_synthesis_targets.append(f"Extract exact implementation details from {title} ({url}).")
            elif title:
                web_synthesis_targets.append(f"Extract exact implementation details from {title}.")
            elif url:
                web_synthesis_targets.append(f"Extract exact implementation details from {url}.")
            if len(web_synthesis_targets) >= 6:
                break
    if not web_synthesis_targets:
        web_synthesis_targets = [
            "Extract only exact flags, parameters, and compatibility constraints that materially unblock the build.",
        ]

    raw_logic_blocks = plan.get("logic_blocks")
    if not isinstance(raw_logic_blocks, list):
        raw_logic_blocks = plan.get("subtasks")

    logic_blocks: List[Dict[str, Any]] = []
    if isinstance(raw_logic_blocks, list):
        for index, block in enumerate(raw_logic_blocks, start=1):
            if not isinstance(block, dict):
                continue
            files = _normalize_relative_paths(block.get("files_to_touch") or [])
            if not files and index - 1 < len(subtasks):
                files = list(subtasks[index - 1].get("files_to_touch") or [])
            if not files:
                continue
            logic_blocks.append(
                {
                    "id": _slugify(block.get("id") or block.get("logic_block_id") or block.get("name") or f"logic_block_{index}"),
                    "goal": str(block.get("goal") or block.get("summary") or f"Implement block {index} for {objective}").strip(),
                    "files_to_touch": files,
                    "parallel_safe": bool(block.get("parallel_safe", True)),
                    "acceptance_tests": _string_list(block.get("acceptance_tests"), limit=6) or acceptance_tests[:3],
                    "axioms": _string_list(block.get("axioms"), limit=6) or axioms[:3],
                    "constraints": _string_list(block.get("constraints"), limit=6) or constraints[:3],
                    "compression_focus": str(block.get("compression_focus") or "").strip() or compression_rules[0],
                    "research_focus": _string_list(block.get("research_focus"), limit=4) or web_synthesis_targets[:2],
                }
            )

    if not logic_blocks:
        for index, subtask in enumerate(subtasks, start=1):
            files = list(subtask.get("files_to_touch") or [])
            if not files:
                continue
            logic_blocks.append(
                {
                    "id": _slugify(subtask.get("logic_block_id") or subtask.get("name") or f"logic_block_{index}"),
                    "goal": str(subtask.get("goal") or f"Implement block {index} for {objective}").strip(),
                    "files_to_touch": files,
                    "parallel_safe": bool(subtask.get("parallel_safe", True)),
                    "acceptance_tests": list(subtask.get("acceptance_tests") or []) or acceptance_tests[:3],
                    "axioms": list(subtask.get("axioms") or []) or axioms[:3],
                    "constraints": list(subtask.get("constraints") or []) or constraints[:3],
                    "compression_focus": str(subtask.get("compression_focus") or "").strip() or compression_rules[0],
                    "research_focus": list(subtask.get("research_focus") or []) or web_synthesis_targets[:2],
                }
            )

    research_sources = []
    for item in research_results[:4]:
        research_sources.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "credibility": round(float(item.get("credibility", {}).get("score", 0.0) or 0.0), 3),
            }
        )

    return {
        "schema_version": 1,
        "objective": objective,
        "project": project,
        "workspace": str(workspace_dir),
        "cycle": cycle,
        "max_cycles": max_cycles,
        "ask_set": ask_set,
        "program_set": program_set,
        "axioms": axioms,
        "constraints": constraints,
        "acceptance_tests": acceptance_tests,
        "compression_rules": compression_rules,
        "web_synthesis_targets": web_synthesis_targets,
        "research_sources": research_sources,
        "prior_test_output_excerpt": _trim_text(prior_test_output, 1200),
        "logic_blocks": logic_blocks[:12],
    }


def _normalize_acl_subtasks(plan: Dict[str, Any], objective: str) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    raw_subtasks = (plan.get("subtasks") or plan.get("logic_blocks")) if isinstance(plan, dict) else None
    if isinstance(raw_subtasks, list):
        for index, item in enumerate(raw_subtasks, start=1):
            if not isinstance(item, dict):
                continue
            files = _normalize_relative_paths(item.get("files_to_touch") or [])
            if not files:
                continue
            normalized.append(
                {
                    "name": _slugify(item.get("name") or f"worker_{index}"),
                    "goal": str(item.get("goal") or item.get("summary") or f"Implement part {index} of {objective}").strip(),
                    "files_to_touch": files,
                    "parallel_safe": bool(item.get("parallel_safe", True)),
                    "logic_block_id": _slugify(item.get("logic_block_id") or item.get("id") or item.get("name") or f"logic_block_{index}"),
                    "acceptance_tests": _string_list(item.get("acceptance_tests"), limit=6),
                    "axioms": _string_list(item.get("axioms"), limit=6),
                    "constraints": _string_list(item.get("constraints"), limit=6),
                    "compression_focus": str(item.get("compression_focus") or "").strip(),
                    "research_focus": _string_list(item.get("research_focus"), limit=4),
                }
            )
    if normalized:
        return normalized

    plan_files = _normalize_relative_paths(plan.get("files_to_touch") or []) if isinstance(plan, dict) else []
    if not plan_files:
        plan_files = ["app.py", "tests/test_app.py", "README.md"]

    primary_files: List[str] = []
    test_files: List[str] = []
    for file_path in plan_files:
        if file_path.startswith("tests/") or Path(file_path).name.startswith("test_"):
            test_files.append(file_path)
        else:
            primary_files.append(file_path)

    if primary_files:
        normalized.append(
            {
                "name": "core_implementation",
                "goal": f"Implement the core program behavior for {objective}",
                "files_to_touch": primary_files,
                "parallel_safe": True,
                "logic_block_id": "core_implementation",
            }
        )
    if test_files:
        normalized.append(
            {
                "name": "verification_assets",
                "goal": f"Keep tests and verification aligned with the implementation for {objective}",
                "files_to_touch": test_files,
                "parallel_safe": True,
                "logic_block_id": "verification_assets",
            }
        )
    if not normalized:
        normalized.append(
            {
                "name": "single_worker",
                "goal": f"Implement a compact Python baseline for {objective}",
                "files_to_touch": ["app.py", "tests/test_app.py"],
                "parallel_safe": True,
                "logic_block_id": "single_worker",
            }
        )
    return normalized


def _acl_token_budget(files_to_touch: List[str], workspace_snapshot: str, prior_test_output: str, base_budget: int) -> int:
    budget = base_budget + (len(files_to_touch) * 120) + max(0, len(workspace_snapshot) // 8) + max(0, len(prior_test_output) // 12)
    return max(600, min(2200, budget))


def _build_acl_packets(
    *,
    job_id: str,
    phase: str,
    cycle: int,
    max_cycles: int,
    objective: str,
    project: str,
    plan: Dict[str, Any],
    directive_text: str,
    language_profile: Dict[str, Any],
    workspace_dir: Path,
    workspace_files: Optional[List[Tuple[str, str]]],
    subtasks: List[Dict[str, Any]],
    logic_table: Optional[Dict[str, Any]],
    prior_test_output: str,
    base_budget: int,
) -> List[ACLPacket]:
    packets: List[ACLPacket] = []
    conversation_id = f"{job_id}:{phase}:{cycle}"
    in_reply_to = f"{job_id}:{phase}:{cycle - 1}" if cycle > 1 else f"{job_id}:root"
    plan_summary = _trim_text(json.dumps(plan or {}, indent=2), 2800)
    trimmed_test_output = _trim_text(prior_test_output, 2600)
    kernel_text = _trim_text(str(language_profile.get("kernel_text") or ""), 1200)
    systems_kernel_text = _trim_text(str(language_profile.get("systems_kernel_text") or ""), 1200)
    language_label = str(language_profile.get("language_label") or language_profile.get("language") or "language")
    packet_language = f"json_{str(language_profile.get('language') or 'code').replace('-', '_')}_files_v1"
    default_files = json.dumps(language_profile.get("default_files") or [], indent=2)
    task_hints = _trim_text("\n".join(f"- {item}" for item in (language_profile.get("task_hints") or [])), 600)
    logic_table = logic_table if isinstance(logic_table, dict) else {}
    ask_set_text = _trim_text("\n".join(f"- {item}" for item in _string_list(logic_table.get("ask_set"), limit=10)) or "(none)", 900)
    program_set_text = _trim_text("\n".join(f"- {item}" for item in _string_list(logic_table.get("program_set"), limit=10)) or "(none)", 900)
    axioms_text = _trim_text("\n".join(f"- {item}" for item in _string_list(logic_table.get("axioms"), limit=10)) or "(none)", 900)
    constraints_text = _trim_text("\n".join(f"- {item}" for item in _string_list(logic_table.get("constraints"), limit=10)) or "(none)", 900)
    compression_text = _trim_text("\n".join(f"- {item}" for item in _string_list(logic_table.get("compression_rules"), limit=8)) or "(none)", 700)
    synthesis_text = _trim_text("\n".join(f"- {item}" for item in _string_list(logic_table.get("web_synthesis_targets"), limit=8)) or "(none)", 900)
    for index, subtask in enumerate(subtasks, start=1):
        files_to_touch = [str(path).replace("\\", "/").strip().lstrip("/") for path in subtask.get("files_to_touch") or []]
        workspace_snapshot = _read_workspace_snapshot(
            workspace_dir,
            max_chars_per_file=2200,
            include_paths=files_to_touch,
            max_total_chars=9000,
            workspace_files=workspace_files,
        )
        if not workspace_snapshot:
            workspace_snapshot = _read_workspace_snapshot(
                workspace_dir,
                max_chars_per_file=1400,
                max_total_chars=5000,
                workspace_files=workspace_files,
            )
        logic_block = _select_logic_block(logic_table, subtask) or {
            "id": subtask.get("logic_block_id") or subtask.get("name") or f"logic_block_{index}",
            "goal": subtask.get("goal") or "",
            "files_to_touch": files_to_touch,
            "parallel_safe": bool(subtask.get("parallel_safe", True)),
            "acceptance_tests": list(subtask.get("acceptance_tests") or []),
            "axioms": list(subtask.get("axioms") or []),
            "constraints": list(subtask.get("constraints") or []),
            "compression_focus": str(subtask.get("compression_focus") or "").strip(),
            "research_focus": list(subtask.get("research_focus") or []),
        }
        logic_block_text = _trim_text(json.dumps(logic_block, indent=2), 1800)
        packet = ACLPacket(
            performative="request",
            conversation_id=conversation_id,
            reply_with=f"{conversation_id}:{index}",
            in_reply_to=in_reply_to,
            ontology="aegis_program_builder",
            language=packet_language,
            phase=phase,
            cycle=cycle,
            worker_name=subtask.get("name") or f"worker_{index}",
            parallel_group=f"{phase}_{cycle}",
            priority="high" if phase == "fix" else "normal",
            files_to_touch=files_to_touch,
            token_budget=_acl_token_budget(files_to_touch, workspace_snapshot, trimmed_test_output, base_budget),
            content=(
                f"(request :sender planner :receiver {subtask.get('name') or f'worker_{index}'} "
                f":ontology aegis_program_builder :language {packet_language} "
                f":conversation-id {conversation_id} :in-reply-to {in_reply_to} "
                f":reply-with {conversation_id}:{index} :content \"{phase} cycle {cycle}\")\n\n"
                f"Objective:\n{objective}\n\n"
                f"Project:\n{project}\n\n"
                f"Stable workspace:\n{workspace_dir}\n\n"
                f"Phase:\n{phase} ({cycle}/{max_cycles})\n\n"
                f"Worker goal:\n{subtask.get('goal')}\n\n"
                f"Owned files:\n{json.dumps(files_to_touch, indent=2)}\n\n"
                f"Persistent directive:\n{directive_text}\n\n"
                f"Primary language:\n{language_label}\n\n"
                f"Language defaults:\n{default_files}\n\n"
                f"Language kernel:\n{kernel_text or '(no kernel loaded)'}\n\n"
                f"Systems kernel:\n{systems_kernel_text or '(no systems kernel loaded)'}\n\n"
                f"Task hints:\n{task_hints or '(none)'}\n\n"
                f"Ask set:\n{ask_set_text}\n\n"
                f"Program set:\n{program_set_text}\n\n"
                f"Axioms:\n{axioms_text}\n\n"
                f"Constraints:\n{constraints_text}\n\n"
                f"Owned logic block:\n{logic_block_text}\n\n"
                f"Compression rules:\n{compression_text}\n\n"
                f"Targeted web-synthesis targets:\n{synthesis_text}\n\n"
                f"Current plan:\n{plan_summary}\n\n"
                f"Latest test output:\n{trimmed_test_output or '(none yet)'}\n\n"
                f"Relevant workspace snapshot:\n{workspace_snapshot or '(workspace is empty)'}\n\n"
                "Rules:\n"
                "- AEGIS coordinator defines the packet order, owned logic block, and file boundary.\n"
                "- Translate the owned logic block into runnable code and aligned verification assets.\n"
                "- Match the primary language and file conventions unless the plan explicitly changes them.\n"
                "- Prefer the smallest runnable, testable, compiler-friendly structure.\n"
                "- Use only the exact external parameters that materially help this implementation.\n"
                "- Avoid prose placeholders, fake JSON-in-code, or explanation text inside source files.\n"
                "- Only change the files you own in this packet.\n"
                f"- Stay within a compact response budget of about { _acl_token_budget(files_to_touch, workspace_snapshot, trimmed_test_output, base_budget) } tokens.\n\n"
                "Return strict JSON with one top-level key named files.\n"
                "files must be an object mapping relative file paths to complete replacement contents.\n"
            ),
        )
        packets.append(packet)
    return packets


def _max_parallel_workers(cpu_target: int, packet_count: int) -> int:
    if packet_count <= 1:
        return 1
    if cpu_target <= 20:
        return 1
    return min(2, packet_count)


def _run_acl_packets(
    model: str,
    packets: List[ACLPacket],
    *,
    system_prompt: str,
    num_predict: int,
    max_workers: int,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    if not packets:
        return results

    def _invoke(packet: ACLPacket) -> Tuple[str, Dict[str, Any]]:
        payload = _chat_json(model, system_prompt, packet.content, num_predict=num_predict)
        return packet.reply_with, payload if isinstance(payload, dict) else {}

    worker_count = max(1, min(max_workers, len(packets)))
    if worker_count == 1:
        for packet in packets:
            key, payload = _invoke(packet)
            results[key] = payload
        return results

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="aegis_acl") as executor:
        future_map = {executor.submit(_invoke, packet): packet for packet in packets}
        for future in as_completed(future_map):
            packet = future_map[future]
            try:
                key, payload = future.result()
            except Exception as exc:
                key = packet.reply_with
                payload = {"error": str(exc)}
            results[key] = payload
    return results


def _merge_acl_packet_files(
    packets: List[ACLPacket],
    responses: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    merged: Dict[str, str] = {}
    response_notes: List[Dict[str, Any]] = []
    for packet in packets:
        payload = responses.get(packet.reply_with) or {}
        files_payload = payload.get("files") if isinstance(payload, dict) else None
        accepted_files: List[str] = []
        if isinstance(files_payload, dict):
            for relative_path, content in files_payload.items():
                clean = str(relative_path or "").replace("\\", "/").strip().lstrip("/")
                if not clean or clean.startswith("..") or not isinstance(content, str):
                    continue
                if packet.files_to_touch and clean not in packet.files_to_touch:
                    continue
                merged[clean] = content
                accepted_files.append(clean)
        response_notes.append(
            {
                "reply_with": packet.reply_with,
                "worker_name": packet.worker_name,
                "accepted_files": accepted_files,
                "error": payload.get("error") if isinstance(payload, dict) else None,
            }
        )
    return merged, response_notes


def decompose_program_task(objective: str, max_cycles: int) -> List[str]:
    steps = [
        f"[SETUP] Create program workspace for {objective}",
        f"[RESEARCH] Gather credible implementation references for {objective}",
    ]
    for cycle in range(1, max_cycles + 1):
        steps.extend(
            [
                f"[PLAN {cycle}] Build or revise the implementation plan for {objective}",
                f"[IMPLEMENT {cycle}] Write program files for {objective}",
                f"[TEST {cycle}] Execute verification for {objective}",
                f"[FIX {cycle}] Repair failures for {objective}",
            ]
        )
    steps.append(f"[REPORT] Write build report for {objective}")
    return steps


def build_program_executor(
    *,
    job_id: str,
    objective: str,
    project: str,
    hours: int,
    cpu_target: int,
    target_dir: Optional[str],
    model: str,
):
    base_dir = Path(__file__).resolve().parent
    workspace_root = Path(target_dir).expanduser() if target_dir else default_program_target_dir(base_dir, project, objective)
    workspace_dir = workspace_root.resolve()
    directive_text = _load_project_directive(base_dir, project)
    language_profile = build_language_runtime_profile(base_dir, objective, project=project)
    language_profile["systems_kernel_text"] = build_systems_kernel_brief(
        base_dir,
        objective,
        project=project,
        max_domains=4,
        max_chars=1400,
    )
    deadline = datetime.utcnow() + timedelta(hours=max(1, hours))
    throttle_seconds = _throttle_delay(cpu_target)
    max_cycles = max(2, min(8, hours))
    state: Dict[str, object] = {
        "workspace_dir": str(workspace_dir),
        "research_results": [],
        "research_chunks": [],
        "research_summary": "",
        "last_plan": {},
        "last_acl_subtasks": [],
        "last_logic_table": {},
        "last_test_ok": False,
        "last_test_output": "",
        "last_test_runner": "",
        "timebox_exhausted": False,
        "written_files": [],
        "logic_table_path": "",
        "report_path": "",
        "workspace_files_cache": [],
        "workspace_cache_dirty": True,
    }

    def _deadline_check() -> None:
        if datetime.utcnow() > deadline:
            state["timebox_exhausted"] = True

    def _sleep() -> None:
        time.sleep(throttle_seconds)

    def _mark_workspace_dirty() -> None:
        state["workspace_cache_dirty"] = True

    def _workspace_files() -> List[Tuple[str, str]]:
        if state.get("workspace_cache_dirty") or not state.get("workspace_files_cache"):
            state["workspace_files_cache"] = _load_workspace_files(workspace_dir)
            state["workspace_cache_dirty"] = False
        return list(state.get("workspace_files_cache") or [])

    def executor(subtask: SubTask) -> str:
        _deadline_check()
        step = subtask.description
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / "artifacts").mkdir(exist_ok=True)

        if step.startswith("[SETUP]"):
            (workspace_dir / "objective.txt").write_text(objective.strip() + "\n", encoding="utf-8")
            (workspace_dir / "project.txt").write_text(project.strip() + "\n", encoding="utf-8")
            (workspace_dir / "language_profile.json").write_text(json.dumps(language_profile, indent=2), encoding="utf-8")
            if language_profile.get("kernel_text"):
                (workspace_dir / "coding_kernel.txt").write_text(str(language_profile["kernel_text"]).strip() + "\n", encoding="utf-8")
            if language_profile.get("systems_kernel_text"):
                (workspace_dir / "systems_kernel.txt").write_text(str(language_profile["systems_kernel_text"]).strip() + "\n", encoding="utf-8")
            if language_profile.get("task_hints"):
                (workspace_dir / "task_hints.txt").write_text("\n".join(f"- {item}" for item in language_profile["task_hints"]) + "\n", encoding="utf-8")
            (workspace_dir / "directive_snapshot.txt").write_text(directive_text + "\n", encoding="utf-8")
            _mark_workspace_dirty()
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="setup",
                cycle=0,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note="Workspace initialized.",
            )
            return f"Workspace ready at {workspace_dir} for {language_profile.get('language')}"

        if step.startswith("[RESEARCH]"):
            query = re.sub(r"\s+", " ", f"{objective} {language_profile.get('research_terms') or ''}").strip()
            results = crawler_db.search_web(query, max_results=5)
            ranked = []
            for result in results or []:
                if result.get("title") == "search_error":
                    continue
                ranked.append(
                    {
                        **result,
                        "credibility": score_source_credibility(
                            result.get("url", ""),
                            title=result.get("title", ""),
                        ),
                    }
                )
            ranked.sort(key=lambda item: item.get("credibility", {}).get("score", 0.0), reverse=True)
            state["research_results"] = ranked[:5]
            research_chunks: List[Dict[str, Any]] = []
            try:
                if state["research_results"]:
                    crawler_db.research_query(
                        query,
                        max_results=min(3, len(state["research_results"])),
                        max_pages=3,
                        same_domain_only=False,
                        seed_results=list(state["research_results"][:3]),
                        project=project,
                        interaction_id=job_id,
                    )
                    research_chunks = crawler_db.search_chunks(
                        query,
                        limit=5,
                        interaction_id=job_id,
                        project=project,
                    )
            except Exception:
                research_chunks = []
            state["research_chunks"] = research_chunks
            lines = [
                f"Research query: {query}",
                "",
                f"Language profile: {language_profile.get('language_label')}",
                "Targeted synthesis mode: extract only exact flags, parameters, and implementation constraints that unblock the build.",
                "",
            ]
            for index, item in enumerate(state["research_results"], start=1):
                cred = item.get("credibility", {})
                lines.append(
                    f"{index}. [{cred.get('score', 0):.2f}] {item.get('title')} - {item.get('url')}"
                )
            if research_chunks:
                lines.extend(["", "Evidence excerpts:"])
                for index, item in enumerate(research_chunks[:4], start=1):
                    lines.append(
                        f"{index}. {item.get('title') or item.get('url')} - {item.get('url')}"
                    )
                    lines.append(f"   {str(item.get('excerpt') or '').strip()}")
            summary = "\n".join(lines).strip() or "No web results captured."
            state["research_summary"] = summary
            (workspace_dir / "research.md").write_text(summary + "\n", encoding="utf-8")
            vector_memory.store(
                summary,
                project=project,
                session_id=job_id,
                subject="program_research",
                kind="program_research",
                role="system",
                metadata={"job_id": job_id, "objective": objective},
            )
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="research",
                cycle=0,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note=f"Stored {len(state['research_results'])} research source(s).",
            )
            _sleep()
            return f"Stored {len(state['research_results'])} research source(s)"

        cycle = _cycle_from_step(step)
        if state["timebox_exhausted"] and not step.startswith("[REPORT]"):
            return f"Skipped {step} because the time budget expired."
        if state["last_test_ok"] and (
            step.startswith("[PLAN ")
            or step.startswith("[IMPLEMENT ")
            or step.startswith("[FIX ")
        ):
            return f"Skipped {step} because tests already pass."

        if step.startswith("[PLAN "):
            workspace_snapshot = _read_workspace_snapshot(workspace_dir, workspace_files=_workspace_files())
            plan_prompt = f"""
Objective:
{objective}

Project:
{project}

Stable workspace:
{workspace_dir}

Cycle:
{cycle}/{max_cycles}

Persistent directive:
{directive_text}

Primary language:
{language_profile.get("language_label")}

Task hints:
{chr(10).join(f"- {item}" for item in (language_profile.get("task_hints") or [])) or "(none)"}

Language kernel:
{language_profile.get("kernel_text")}

Systems kernel:
{language_profile.get("systems_kernel_text")}

Research summary:
{state['research_summary']}

Last test output:
{state['last_test_output']}

Current workspace snapshot:
{workspace_snapshot}

Return JSON with:
- summary
- architecture
- success_criteria
- ask_set (array of strings)
- program_set (array of strings)
- axioms (array of strings)
- constraints (array of strings)
- files_to_touch (array of relative paths)
- logic_blocks (array of objects with id, goal, files_to_touch, acceptance_tests, parallel_safe)
- subtasks (array of objects with name, goal, files_to_touch, parallel_safe)
- acceptance_tests (array of strings)
- compression_rules (array of strings)
- web_synthesis_targets (array of strings)
- test_strategy

Rules:
- Match the primary language unless the objective explicitly asks for another stack.
- Reduce the work into ask set versus program set before writing subtasks.
- Express the plan as movable logic blocks with explicit file ownership.
- Prefer small file ownership groups that can be worked on in parallel.
- Prefer compact, flattened, compiler-friendly code paths over decorative abstraction.
- If research is available, carry forward only the exact flags, parameters, or implementation constraints that materially unblock the build.
- Prefer the simplest verification path that is native to the language and likely to exist locally.
"""
            plan = _chat_json(
                model,
                f"You are a senior software builder. Return only compact JSON for a {language_profile.get('language_label')} implementation plan.",
                plan_prompt,
                num_predict=700,
            )
            if not plan:
                default_files = list(language_profile.get("default_files") or ["app.py", "tests/test_app.py", "README.md"])
                primary_files = [path for path in default_files if not path.startswith("tests/")]
                test_files = [path for path in default_files if path.startswith("tests/")]
                plan = {
                    "summary": f"Build a compact {language_profile.get('language_label')} baseline, then iterate using verification output.",
                    "architecture": "Small entry module plus verification assets",
                    "success_criteria": "Verification passes and the program runs locally.",
                    "ask_set": [
                        objective,
                        "Produce a runnable program rather than a speculative outline.",
                    ],
                    "program_set": [
                        "Small entry module",
                        "Verification assets",
                        "Workspace notes",
                    ],
                    "axioms": [
                        f"Use {language_profile.get('language_label')} as the primary implementation lane.",
                        "The smallest runnable structure wins.",
                        "Latest verification output overrides stale assumptions.",
                    ],
                    "constraints": [
                        "Stay inside the stable workspace.",
                        "Keep file ownership explicit.",
                        "Make the result locally runnable.",
                    ],
                    "files_to_touch": default_files,
                    "logic_blocks": [
                        {
                            "id": "core_implementation",
                            "goal": f"Build the core {language_profile.get('language_label')} program behavior.",
                            "files_to_touch": primary_files or default_files,
                            "acceptance_tests": [
                                "Primary program files are runnable.",
                            ],
                            "parallel_safe": True,
                        },
                        {
                            "id": "verification_assets",
                            "goal": "Keep tests aligned with the implementation.",
                            "files_to_touch": test_files or default_files[-1:],
                            "acceptance_tests": [
                                "Verification assets match the current behavior.",
                            ],
                            "parallel_safe": True,
                        },
                    ],
                    "subtasks": [
                        {
                            "name": "core_implementation",
                            "goal": f"Build the core {language_profile.get('language_label')} program behavior.",
                            "files_to_touch": primary_files or default_files,
                            "parallel_safe": True,
                        },
                        {
                            "name": "verification_assets",
                            "goal": "Keep tests aligned with the implementation.",
                            "files_to_touch": test_files or default_files[-1:],
                            "parallel_safe": True,
                        },
                    ],
                    "acceptance_tests": [
                        "The program runs locally.",
                        "Verification passes.",
                    ],
                    "compression_rules": [
                        "Prefer flat, compiler-friendly code paths.",
                        "Avoid unnecessary wrappers or placeholder scaffolding.",
                    ],
                    "web_synthesis_targets": [
                        "Extract only exact implementation details that materially unblock the build.",
                    ],
                    "test_strategy": str(language_profile.get("test_strategy") or "Run the simplest available local verification."),
                }
            state["last_plan"] = plan
            state["last_acl_subtasks"] = _normalize_acl_subtasks(plan, objective)
            state["last_logic_table"] = _build_logic_table(
                objective=objective,
                project=project,
                plan=plan,
                language_profile=language_profile,
                workspace_dir=workspace_dir,
                cycle=cycle,
                max_cycles=max_cycles,
                subtasks=state["last_acl_subtasks"],
                research_results=list(state.get("research_results") or []),
                prior_test_output=str(state.get("last_test_output") or ""),
            )
            logic_table_text = json.dumps(state["last_logic_table"], indent=2)
            (workspace_dir / "LOGIC_TABLE.json").write_text(logic_table_text + "\n", encoding="utf-8")
            logic_table_path = workspace_dir / "artifacts" / f"logic_table_cycle_{cycle}.json"
            logic_table_path.write_text(logic_table_text + "\n", encoding="utf-8")
            state["logic_table_path"] = str(logic_table_path)
            (workspace_dir / "artifacts" / f"plan_cycle_{cycle}.json").write_text(
                json.dumps(
                    {
                        "plan": plan,
                        "acl_subtasks": state["last_acl_subtasks"],
                        "logic_table_path": str(logic_table_path),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="plan",
                cycle=cycle,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note=str(plan.get("summary") or "Plan updated."),
            )
            _sleep()
            return f"Plan cycle {cycle}: {plan.get('summary', 'plan ready')}"

        if step.startswith("[IMPLEMENT "):
            plan = state.get("last_plan") or {}
            acl_subtasks = state.get("last_acl_subtasks") or _normalize_acl_subtasks(plan, objective)
            acl_packets = _build_acl_packets(
                job_id=job_id,
                phase="implement",
                cycle=cycle,
                max_cycles=max_cycles,
                objective=objective,
                project=project,
                plan=plan,
                directive_text=directive_text,
                language_profile=language_profile,
                workspace_dir=workspace_dir,
                workspace_files=_workspace_files(),
                subtasks=acl_subtasks,
                logic_table=state.get("last_logic_table") or {},
                prior_test_output=str(state["last_test_output"]),
                base_budget=900,
            )
            parallel_workers = _max_parallel_workers(cpu_target, len(acl_packets))
            responses = _run_acl_packets(
                model,
                acl_packets,
                system_prompt=(
                    f"You are an AEGIS coordinator packet worker for concise runnable {language_profile.get('language_label')} project files. "
                    "Return strict JSON only. "
                    "Match the requested language, logic block, and file ownership exactly. "
                    "Prefer flat, compiler-friendly code with direct data flow. "
                    "Avoid prose, placeholders, and fake code."
                ),
                num_predict=1400,
                max_workers=parallel_workers,
            )
            files_payload, response_notes = _merge_acl_packet_files(acl_packets, responses)
            if not files_payload:
                files_payload = _fallback_program_files(objective, cycle, language_profile)
            written = _write_program_files(workspace_dir, files_payload)
            _mark_workspace_dirty()
            state["written_files"] = written
            (workspace_dir / "artifacts" / f"acl_implement_cycle_{cycle}.json").write_text(
                json.dumps(
                    {
                        "parallel_workers": parallel_workers,
                        "packets": [asdict(packet) for packet in acl_packets],
                        "response_notes": response_notes,
                        "written_files": written,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="implement",
                cycle=cycle,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note=f"Wrote {len(written)} file(s) across {len(acl_packets)} ACL packet(s).",
            )
            _sleep()
            return (
                f"Wrote {len(written)} file(s) across {len(acl_packets)} ACL packet(s) "
                f"with {parallel_workers} worker(s): {', '.join(written[:6])}"
            )

        if step.startswith("[TEST "):
            ok, runner, output = _run_tests(workspace_dir, language_profile)
            state["last_test_ok"] = ok
            state["last_test_runner"] = runner
            state["last_test_output"] = output
            (workspace_dir / "artifacts" / f"test_cycle_{cycle}_{runner}.txt").write_text(
                output + "\n",
                encoding="utf-8",
            )
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="test",
                cycle=cycle,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note=f"Verification {'passed' if ok else 'failed'} with {runner}.",
            )
            _sleep()
            if ok:
                return f"Tests passed with {runner}"
            return f"Tests failed with {runner}:\n{output[:2000]}"

        if step.startswith("[FIX "):
            if state["last_test_ok"]:
                return "No fix required because the latest tests passed."
            plan = state.get("last_plan") or {}
            acl_subtasks = state.get("last_acl_subtasks") or _normalize_acl_subtasks(plan, objective)
            acl_packets = _build_acl_packets(
                job_id=job_id,
                phase="fix",
                cycle=cycle,
                max_cycles=max_cycles,
                objective=objective,
                project=project,
                plan=plan,
                directive_text=directive_text,
                language_profile=language_profile,
                workspace_dir=workspace_dir,
                workspace_files=_workspace_files(),
                subtasks=acl_subtasks,
                logic_table=state.get("last_logic_table") or {},
                prior_test_output=str(state["last_test_output"]),
                base_budget=1100,
            )
            parallel_workers = _max_parallel_workers(cpu_target, len(acl_packets))
            responses = _run_acl_packets(
                model,
                acl_packets,
                system_prompt=(
                    f"You are an AEGIS repair packet worker fixing a local {language_profile.get('language_label')} project from verification failures. "
                    "Return strict JSON only. "
                    "Preserve working code, follow the owned logic block, and edit only the owned files needed to fix the failures. "
                    "Prefer direct, compact, compiler-friendly fixes over broad rewrites. "
                    "Do not answer with explanation text in place of source code."
                ),
                num_predict=1600,
                max_workers=parallel_workers,
            )
            files_payload, response_notes = _merge_acl_packet_files(acl_packets, responses)
            if not files_payload:
                files_payload = _fallback_program_files(objective, cycle, language_profile)
            written = _write_program_files(workspace_dir, files_payload)
            _mark_workspace_dirty()
            (workspace_dir / "artifacts" / f"acl_fix_cycle_{cycle}.json").write_text(
                json.dumps(
                    {
                        "parallel_workers": parallel_workers,
                        "packets": [asdict(packet) for packet in acl_packets],
                        "response_notes": response_notes,
                        "written_files": written,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="fix",
                cycle=cycle,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note=f"Applied fix cycle {cycle} across {len(written)} file(s).",
            )
            _sleep()
            return (
                f"Applied ACL fix cycle {cycle} across {len(written)} file(s) "
                f"with {parallel_workers} worker(s)"
            )

        if step.startswith("[REPORT]"):
            status = "passed" if state["last_test_ok"] else "unfinished"
            report_lines = [
                f"Program build report for job {job_id}",
                f"Objective: {objective}",
                f"Project: {project}",
                f"Workspace: {workspace_dir}",
                f"Model: {model}",
                f"Primary language: {language_profile.get('language_label')}",
                f"CPU target hint: {cpu_target}%",
                f"Time budget hours: {hours}",
                f"Timebox exhausted: {state['timebox_exhausted']}",
                f"Last ACL subtask count: {len(state.get('last_acl_subtasks') or [])}",
                f"Logic table path: {state.get('logic_table_path') or '(not written)'}",
                f"Final status: {status}",
                f"Last test runner: {state['last_test_runner']}",
                "",
                "Research summary:",
                str(state["research_summary"]),
                "",
                "Last plan:",
                json.dumps(state.get("last_plan") or {}, indent=2),
                "",
                "Last logic table:",
                json.dumps(state.get("last_logic_table") or {}, indent=2),
                "",
                "Last test output:",
                str(state["last_test_output"])[:4000],
            ]
            report_path = workspace_dir / "BUILD_REPORT.md"
            report_text = "\n".join(report_lines).strip() + "\n"
            report_path.write_text(report_text, encoding="utf-8")
            state["report_path"] = str(report_path)
            _write_workspace_snapshot_file(
                workspace_dir,
                job_id=job_id,
                project=project,
                objective=objective,
                language_profile=language_profile,
                state=state,
                phase="report",
                cycle=max_cycles,
                max_cycles=max_cycles,
                cpu_target=cpu_target,
                hours=hours,
                note=f"Build report written to {report_path}.",
            )
            timescale_memory.store_reasoning_summary(
                session_id=job_id,
                project=project,
                objective=objective,
                summary=report_text[:4000],
                metadata={"job_id": job_id, "report_path": str(report_path), "kind": "program_build"},
            )
            vector_memory.store(
                report_text,
                project=project,
                session_id=job_id,
                subject="program_build_report",
                kind="program_build_report",
                role="system",
                metadata={"job_id": job_id, "report_path": str(report_path), "objective": objective},
            )
            return f"Build report written to {report_path}"

        return f"Unhandled subtask: {step}"

    return executor
