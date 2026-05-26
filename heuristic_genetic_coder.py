"""
Heuristic genetic coder lane for AEGIS.

This is the bridge between an outline-producing coding agent and an evidence
driven code-evolution loop. It keeps the logic explicit:

- AskSet: what the user wants
- ConstraintSet: boundaries and invariants
- CodeSet: candidate implementation files
- TestSet: verification commands and expected behavior
- DebuggerSet: compile/runtime/debugger observations that can suggest repairs
- EvidenceSet: compile/test/runtime results

The SOAP portion here is an optimizer state for mutation heuristics. It is not
model fine-tuning yet; it records adaptive preconditioner-style statistics so
the next training lane can distill successful edits into a small model.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kqml_protocol import make_kqml_message, new_conversation_id, render_kqml
from lava_event_orchestrator import lava_event_orchestrator
from training_experiment_engine import predict_execution_likelihood


REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "gemini_bridge.db"
RUNS_DIR = REPO_ROOT / "agentic_jobs" / "genetic_coder"
LAB_OUTPUT_DIR = Path.home() / "LAB_OUTPUT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: str, fallback: str = "job") -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", (value or "").strip()).strip("-")
    return (clean or fallback)[:90]


def _safe_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _line_count(text: str) -> int:
    return len([line for line in (text or "").splitlines() if line.strip()])


@dataclass
class Candidate:
    candidate_id: str
    generation: int
    heuristics: List[str]
    files: Dict[str, str]
    parent_id: str = ""
    fitness: float = 0.0
    tests_pass: bool = False
    compile_pass: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeTemplate:
    template_id: str
    framework: str
    language: str
    pages: int
    target_lines: int
    files: List[str]
    rationale: str


def _infer_code_template(objective: str, outline: str = "") -> CodeTemplate:
    text = f"{objective} {outline}".lower()
    wants_web = any(token in text for token in ("web", "website", "html", "browser", "dashboard", "page", "hosted locally"))
    wants_api = any(token in text for token in ("api", "server", "endpoint", "rest", "flask", "fastapi"))
    wants_gui = any(token in text for token in ("gui", "window", "button", "tkinter", "desktop app"))
    wants_data = any(token in text for token in ("csv", "json", "data", "report", "parse", "analyze"))
    wants_multi_page = any(token in text for token in ("multi page", "multipage", "pages", "dashboard", "admin"))
    wants_large = any(token in text for token in ("full", "complete", "end to end", "production", "robust", "large"))

    if wants_web or wants_api:
        pages = 3 if wants_multi_page or wants_large else 1
        return CodeTemplate(
            template_id="python_local_web_app",
            framework="python stdlib http.server + static html/css/js",
            language="python",
            pages=pages,
            target_lines=220 if pages > 1 else 140,
            files=["app.py", "templates/index.html", "static/style.css", "static/app.js", "test_app.py", "README.md"],
            rationale="Web/API cues imply a local browser-facing app with a tiny Python server and static UI.",
        )

    if wants_gui:
        return CodeTemplate(
            template_id="python_tkinter_gui",
            framework="python tkinter",
            language="python",
            pages=1,
            target_lines=180 if wants_large else 120,
            files=["app.py", "test_app.py", "README.md"],
            rationale="GUI/window cues imply a simple desktop UI skeleton with testable pure functions.",
        )

    if wants_data:
        return CodeTemplate(
            template_id="python_data_cli",
            framework="python argparse + json/csv stdlib",
            language="python",
            pages=1,
            target_lines=160 if wants_large else 110,
            files=["app.py", "sample_input.json", "test_app.py", "README.md"],
            rationale="Data/report cues imply a CLI transformer with sample input and JSON evidence output.",
        )

    return CodeTemplate(
        template_id="python_cli_evidence_app",
        framework="python argparse + json stdlib",
        language="python",
        pages=1,
        target_lines=120 if wants_large else 90,
        files=["app.py", "test_app.py", "README.md"],
        rationale="No stronger framework cue was found, so the safest first candidate is a runnable CLI app.",
    )


class SoapHeuristicState:
    """Small SOAP-inspired optimizer over mutation heuristic weights."""

    def __init__(self) -> None:
        self.weights: Dict[str, float] = {
            "minimal_cli": 1.0,
            "json_report": 1.0,
            "self_test": 1.0,
            "edge_cases": 0.8,
            "clear_errors": 0.8,
            "decompile_compile_hook": 0.55,
        }
        self.first_moment: Dict[str, float] = {key: 0.0 for key in self.weights}
        self.second_moment: Dict[str, float] = {key: 1.0 for key in self.weights}

    def choose(self, rng: random.Random, count: int) -> List[str]:
        keys = list(self.weights)
        weighted = [max(0.05, self.weights[key]) for key in keys]
        selected: List[str] = []
        for _ in range(max(1, count)):
            choice = rng.choices(keys, weights=weighted, k=1)[0]
            if choice not in selected:
                selected.append(choice)
        return selected

    def update(self, heuristics: List[str], reward: float) -> None:
        for name in heuristics:
            if name not in self.weights:
                continue
            grad = max(-1.0, min(1.0, reward))
            self.first_moment[name] = 0.85 * self.first_moment[name] + 0.15 * grad
            self.second_moment[name] = 0.92 * self.second_moment[name] + 0.08 * (grad * grad)
            step = 0.18 * self.first_moment[name] / (self.second_moment[name] ** 0.5 + 1e-6)
            self.weights[name] = max(0.05, min(3.0, self.weights[name] + step))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weights": self.weights,
            "first_moment": self.first_moment,
            "second_moment": self.second_moment,
            "note": "SOAP-ready heuristic optimizer state; successful code tries can later become training samples.",
        }


class GeneticCoderStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._ensure()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS genetic_coder_runs (
                    job_id TEXT PRIMARY KEY,
                    project TEXT,
                    objective TEXT,
                    language TEXT,
                    status TEXT,
                    workspace TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    best_fitness REAL DEFAULT 0,
                    best_candidate_id TEXT,
                    tests_pass INTEGER DEFAULT 0,
                    kqml_trace_json TEXT,
                    soap_state_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS genetic_code_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    candidate_id TEXT,
                    project TEXT,
                    generation INTEGER,
                    heuristics_json TEXT,
                    fitness REAL,
                    tests_pass INTEGER,
                    compile_pass INTEGER,
                    files_json TEXT,
                    evidence_json TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS genetic_code_successes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    candidate_id TEXT,
                    project TEXT,
                    objective TEXT,
                    language TEXT,
                    files_json TEXT,
                    evidence_json TEXT,
                    fitness REAL,
                    created_at TEXT
                )
                """
            )

    def upsert_run(self, payload: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO genetic_coder_runs (
                    job_id, project, objective, language, status, workspace,
                    created_at, updated_at, best_fitness, best_candidate_id,
                    tests_pass, kqml_trace_json, soap_state_json
                )
                VALUES (
                    :job_id, :project, :objective, :language, :status, :workspace,
                    :created_at, :updated_at, :best_fitness, :best_candidate_id,
                    :tests_pass, :kqml_trace_json, :soap_state_json
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    best_fitness=excluded.best_fitness,
                    best_candidate_id=excluded.best_candidate_id,
                    tests_pass=excluded.tests_pass,
                    kqml_trace_json=excluded.kqml_trace_json,
                    soap_state_json=excluded.soap_state_json
                """,
                payload,
            )

    def record_attempt(self, *, job_id: str, project: str, candidate: Candidate) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO genetic_code_attempts (
                    job_id, candidate_id, project, generation, heuristics_json,
                    fitness, tests_pass, compile_pass, files_json, evidence_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    candidate.candidate_id,
                    project,
                    candidate.generation,
                    json.dumps(candidate.heuristics, ensure_ascii=True),
                    candidate.fitness,
                    int(candidate.tests_pass),
                    int(candidate.compile_pass),
                    json.dumps(candidate.files, ensure_ascii=True),
                    json.dumps(candidate.evidence, ensure_ascii=True, default=str),
                    _now(),
                ),
            )
            if candidate.tests_pass:
                conn.execute(
                    """
                    INSERT INTO genetic_code_successes (
                        job_id, candidate_id, project, objective, language,
                        files_json, evidence_json, fitness, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        candidate.candidate_id,
                        project,
                        str(candidate.evidence.get("objective") or ""),
                        str(candidate.evidence.get("language") or "python"),
                        json.dumps(candidate.files, ensure_ascii=True),
                        json.dumps(candidate.evidence, ensure_ascii=True, default=str),
                        candidate.fitness,
                        _now(),
                    ),
                )


class HeuristicGeneticCoderJob:
    def __init__(
        self,
        *,
        objective: str,
        project: str = "general",
        language: str = "python",
        outline: str = "",
        snippets: Optional[List[Dict[str, Any]]] = None,
        max_generations: int = 8,
        population: int = 4,
        timebox_minutes: int = 20,
        workspace: Optional[str] = None,
    ) -> None:
        self.job_id = f"genetic-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        self.project = _slug(project or "general", "general")
        self.objective = objective.strip()
        self.language = (language or "python").lower().strip()
        self.outline = outline.strip()
        self.snippets = snippets or []
        self.template = _infer_code_template(self.objective, self.outline)
        self.max_generations = _safe_int(max_generations, 8, 1, 200)
        self.population = _safe_int(population, 4, 1, 50)
        self.timebox_minutes = _safe_int(timebox_minutes, 20, 1, 24 * 60)
        self.created_at = _now()
        self.updated_at = self.created_at
        self.status = "pending"
        self.error = ""
        self.kqml_trace: List[Dict[str, Any]] = []
        self.soap = SoapHeuristicState()
        root = Path(workspace).resolve() if workspace else LAB_OUTPUT_DIR / self.project / _slug(self.objective, self.job_id)
        self.workspace = root
        self.best: Optional[Candidate] = None
        self.candidates: List[Candidate] = []
        self.store = GeneticCoderStore()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._rng = random.Random(self.job_id)
        self.conversation_id = new_conversation_id("genetic-coder")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project": self.project,
            "objective": self.objective,
            "language": self.language,
            "outline": self.outline,
            "snippets": self.snippets[-20:],
            "selected_template": asdict(self.template),
            "max_generations": self.max_generations,
            "population": self.population,
            "timebox_minutes": self.timebox_minutes,
            "workspace": str(self.workspace),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "error": self.error,
            "best": asdict(self.best) if self.best else None,
            "candidate_count": len(self.candidates),
            "soap": self.soap.to_dict(),
            "kqml_trace": self.kqml_trace[-80:],
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.status = "stopping"
        self._persist()

    def _kqml(self, performative: str, receiver: str, content: Any, *, in_reply_to: str = "") -> Dict[str, Any]:
        msg = make_kqml_message(
            performative,
            sender="aegis-genetic-coder",
            receiver=receiver,
            content=content,
            language="json",
            ontology="aegis.genetic-coder.set-theory",
            conversation_id=self.conversation_id,
            reply_with=f"{performative}-{uuid.uuid4().hex[:8]}",
            in_reply_to=in_reply_to or None,
        )
        msg["wire"] = render_kqml(msg)
        self.kqml_trace.append(msg)
        return msg

    def _set_table(self) -> Dict[str, Any]:
        return {
            "AskSet": {
                "objective": self.objective,
                "outline": self.outline,
                "language": self.language,
                "inferred_framework": self.template.framework,
                "estimated_pages": self.template.pages,
                "estimated_target_lines": self.template.target_lines,
            },
            "SourceSnippetSet": [
                {
                    "title": str(item.get("title") or item.get("url") or "snippet")[:120],
                    "url": str(item.get("url") or ""),
                    "content": str(item.get("content") or item.get("snippet") or "")[:500],
                }
                for item in self.snippets[-12:]
            ],
            "ConstraintSet": {
                "workspace": str(self.workspace),
                "lab_output_root": str(LAB_OUTPUT_DIR),
                "no_network": True,
                "local_execution_only": True,
                "timebox_minutes": self.timebox_minutes,
                "stop_on_success": True,
                "selected_template": asdict(self.template),
            },
            "CodeSet": {
                "candidate_count": len(self.candidates),
                "best_candidate": self.best.candidate_id if self.best else None,
                "template_id": self.template.template_id,
                "framework": self.template.framework,
                "expected_files": self.template.files,
            },
            "TestSet": {
                "compile": "python -m py_compile app.py test_app.py",
                "runtime": "python test_app.py",
                "debugger": "extract traceback/error evidence and feed bounded repair hints into the next mutation",
                "decompile_compile_hook": "reserved for Binary Ninja/Ghidra/JDK/D8 adapters when installed and approved",
            },
            "DebuggerSet": {
                "active_adapter": "python-trace-parser",
                "binary_adapter": "reserved for Binary Ninja/Vector35 debugger or other approved debugger toolchains",
                "latest": (self.best.evidence.get("debugger") if self.best else None),
            },
            "EvidenceSet": {
                "best_fitness": self.best.fitness if self.best else 0.0,
                "tests_pass": bool(self.best and self.best.tests_pass),
                "latest_status": self.status,
                "ai_feedback_packet": self._ai_feedback_packet(),
            },
        }

    def _ai_feedback_packet(self, candidate: Optional[Candidate] = None, final_output_dir: str = "") -> Dict[str, Any]:
        active = candidate or self.best
        evidence = active.evidence if active else {}
        return {
            "performative": "tell",
            "receiver": "aegis-ai",
            "purpose": "code_template_extrapolation_feedback",
            "template_id": self.template.template_id,
            "framework": self.template.framework,
            "estimated_pages": self.template.pages,
            "estimated_target_lines": self.template.target_lines,
            "workspace": str(self.workspace),
            "best_candidate": active.candidate_id if active else "",
            "tests_pass": bool(active and active.tests_pass),
            "fitness": active.fitness if active else 0.0,
            "final_output_dir": str(final_output_dir or evidence.get("final_output_dir") or ""),
        }

    def _persist(self) -> None:
        self.updated_at = _now()
        self.workspace.mkdir(parents=True, exist_ok=True)
        _write_json(self.workspace / "GENETIC_CODER_STATE.json", self.to_dict())
        _write_json(self.workspace / "SET_TABLE.json", self._set_table())
        self.store.upsert_run(
            {
                "job_id": self.job_id,
                "project": self.project,
                "objective": self.objective,
                "language": self.language,
                "status": self.status,
                "workspace": str(self.workspace),
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "best_fitness": self.best.fitness if self.best else 0.0,
                "best_candidate_id": self.best.candidate_id if self.best else "",
                "tests_pass": int(bool(self.best and self.best.tests_pass)),
                "kqml_trace_json": json.dumps(self.kqml_trace[-80:], ensure_ascii=True, default=str),
                "soap_state_json": json.dumps(self.soap.to_dict(), ensure_ascii=True, default=str),
            }
        )

    def _initial_candidate(self) -> Candidate:
        files = _render_python_project(self.objective, self.outline, ["minimal_cli", "self_test"], self.snippets, self.template)
        return Candidate(
            candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
            generation=0,
            heuristics=["minimal_cli", "self_test"],
            files=files,
        )

    def _mutate(self, parent: Candidate, generation: int) -> Candidate:
        heuristics = self.soap.choose(self._rng, self._rng.randint(1, 3))
        debugger = parent.evidence.get("debugger") if isinstance(parent.evidence, dict) else {}
        repair_hints = debugger.get("repair_hints") if isinstance(debugger, dict) else []
        if repair_hints:
            heuristics.extend(["clear_errors", "self_test"])
        all_heuristics = sorted(set(parent.heuristics + heuristics))
        files = _render_python_project(self.objective, self.outline, all_heuristics, self.snippets, self.template)
        if "edge_cases" in heuristics:
            files["test_app.py"] = files["test_app.py"].replace(
                "assert isinstance(result, dict)",
                "assert isinstance(result, dict)\n    assert result.get('ok') is True",
            )
        if "clear_errors" in heuristics:
            files["app.py"] = files["app.py"].replace(
                "return {\"ok\": True, \"objective\": objective, \"steps\": steps}",
                "return {\"ok\": True, \"objective\": objective, \"steps\": steps, \"error\": \"\"}",
            )
        return Candidate(
            candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
            generation=generation,
            heuristics=all_heuristics,
            files=files,
            parent_id=parent.candidate_id,
        )

    def _evaluate(self, candidate: Candidate) -> Candidate:
        candidate_dir = self.workspace / "candidates" / candidate.candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        for rel, text in candidate.files.items():
            path = candidate_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        compile_cmd = [os.fspath(_python_exe()), "-m", "py_compile", "app.py", "test_app.py"]
        runtime_cmd = [os.fspath(_python_exe()), "test_app.py"]
        compile_result = _run_command(compile_cmd, candidate_dir, timeout=25)
        runtime_result = _run_command(runtime_cmd, candidate_dir, timeout=35) if compile_result["ok"] else {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "compile failed; runtime skipped",
            "duration_seconds": 0,
        }
        debugger_result = _build_debugger_evidence(
            language=self.language,
            compile_result=compile_result,
            runtime_result=runtime_result,
            files=candidate.files,
        )
        likelihood = predict_execution_likelihood(
            {
                "prompt": self.objective,
                "code": "\n\n".join(candidate.files.values()),
                "language": self.language,
                "code_lines": sum(_line_count(text) for text in candidate.files.values()),
                "research_hits": len(self.snippets),
                "prior_pass_rate": 1.0 if runtime_result["ok"] else 0.25,
            }
        )
        candidate.compile_pass = bool(compile_result["ok"])
        candidate.tests_pass = bool(runtime_result["ok"])
        candidate.fitness = _score_candidate(candidate, compile_result, runtime_result, likelihood)
        candidate.evidence = {
            "objective": self.objective,
            "language": self.language,
            "candidate_dir": str(candidate_dir),
            "selected_template": asdict(self.template),
            "compile": compile_result,
            "runtime": runtime_result,
            "debugger": debugger_result,
            "likelihood": likelihood,
            "line_count": sum(_line_count(text) for text in candidate.files.values()),
            "set_table": self._set_table(),
            "decompile_compile": {
                "enabled": False,
                "note": "Binary debugger/decompiler adapters belong in this fitness loop after installation/licensing; their traces should propose bounded fixes before recompile.",
            },
        }
        if candidate.tests_pass:
            final_output_dir = str(self._publish_candidate(candidate))
            candidate.evidence["final_output_dir"] = final_output_dir
            candidate.evidence["ai_feedback_packet"] = self._ai_feedback_packet(candidate, final_output_dir)
        self.store.record_attempt(job_id=self.job_id, project=self.project, candidate=candidate)
        return candidate

    def _publish_candidate(self, candidate: Candidate) -> Path:
        final_dir = self.workspace / "FINAL"
        final_dir.mkdir(parents=True, exist_ok=True)
        for rel, text in candidate.files.items():
            path = final_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        feedback_packet = self._ai_feedback_packet(candidate, str(final_dir))
        _write_json(
            final_dir / "AEGIS_BUILD_PACKET.json",
            {
                "job_id": self.job_id,
                "candidate_id": candidate.candidate_id,
                "objective": self.objective,
                "template": asdict(self.template),
                "fitness": candidate.fitness,
                "tests_pass": candidate.tests_pass,
                "ai_feedback_packet": feedback_packet,
            },
        )
        return final_dir

    def run(self) -> None:
        deadline = time.time() + self.timebox_minutes * 60
        self.status = "running"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._kqml("ask-one", "aider-outline", {"request": "outline_first_last_pages", "objective": self.objective})
        self._kqml("achieve", "heuristic-genetic-engine", self._set_table())
        lava_event_orchestrator.record_event(
            project=self.project,
            event_type="gc_plan",
            source="aegis-genetic-coder",
            target="aegis-lava-event-plane",
            content={
                "job_id": self.job_id,
                "objective": self.objective,
                "language": self.language,
                "selected_template": asdict(self.template),
                "ai_feedback_packet": self._ai_feedback_packet(),
                "set_table": self._set_table(),
            },
            performative="achieve",
            status="observed",
            score=0.0,
            soap_state=self.soap.to_dict(),
        )
        self._persist()

        try:
            seed = self._evaluate(self._initial_candidate())
            self.candidates.append(seed)
            self.best = seed
            self.soap.update(seed.heuristics, seed.fitness)
            lava_event_orchestrator.record_genetic_candidate(
                project=self.project,
                job_id=self.job_id,
                objective=self.objective,
                candidate=seed,
                soap_state=self.soap.to_dict(),
                reward=seed.fitness,
            )
            self._kqml("tell", "aegis-db", {"candidate": seed.candidate_id, "fitness": seed.fitness, "tests_pass": seed.tests_pass})
            self._persist()
            if seed.tests_pass:
                self.status = "completed"
                self._write_report()
                self._persist()
                return

            generation = 1
            while generation <= self.max_generations and time.time() < deadline and not self._stop.is_set():
                parents = sorted(self.candidates, key=lambda item: item.fitness, reverse=True)[: max(1, min(3, len(self.candidates)))]
                generation_candidates: List[Candidate] = []
                for _ in range(self.population):
                    parent = self._rng.choice(parents)
                    child = self._evaluate(self._mutate(parent, generation))
                    self.candidates.append(child)
                    generation_candidates.append(child)
                    reward = child.fitness - parent.fitness
                    self.soap.update(child.heuristics, reward)
                    lava_event_orchestrator.record_genetic_candidate(
                        project=self.project,
                        job_id=self.job_id,
                        objective=self.objective,
                        candidate=child,
                        soap_state=self.soap.to_dict(),
                        reward=reward,
                    )
                    if not self.best or child.fitness > self.best.fitness:
                        self.best = child
                    self._kqml(
                        "tell",
                        "aegis-db",
                        {
                            "generation": generation,
                            "candidate": child.candidate_id,
                            "fitness": child.fitness,
                            "tests_pass": child.tests_pass,
                            "heuristics": child.heuristics,
                        },
                    )
                    if child.tests_pass:
                        self.status = "completed"
                        self._write_report()
                        self._persist()
                        return
                self._write_generation_report(generation, generation_candidates)
                self._persist()
                generation += 1

            self.status = "stopped" if self._stop.is_set() else "failed"
            self._write_report()
            self._persist()
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self._kqml("sorry", "aegis-ui", {"error": self.error})
            self._write_report()
            self._persist()

    def _write_generation_report(self, generation: int, candidates: List[Candidate]) -> None:
        rows = [
            {
                "candidate": item.candidate_id,
                "fitness": item.fitness,
                "tests_pass": item.tests_pass,
                "compile_pass": item.compile_pass,
                "heuristics": item.heuristics,
            }
            for item in candidates
        ]
        _write_json(self.workspace / "generations" / f"generation_{generation:03d}.json", rows)

    def _write_report(self) -> None:
        lines = [
            "# Genetic Coder Report",
            "",
            f"Job: {self.job_id}",
            f"Status: {self.status}",
            f"Objective: {self.objective}",
            f"Workspace: {self.workspace}",
            "",
            "## Set Theory",
            "```json",
            json.dumps(self._set_table(), indent=2, ensure_ascii=True),
            "```",
            "",
            "## Best Candidate",
        ]
        if self.best:
            lines.extend(
                [
                    f"- Candidate: {self.best.candidate_id}",
                    f"- Fitness: {self.best.fitness:.3f}",
                    f"- Tests pass: {self.best.tests_pass}",
                    f"- Compile pass: {self.best.compile_pass}",
                    f"- Heuristics: {', '.join(self.best.heuristics)}",
                    f"- Candidate dir: {self.best.evidence.get('candidate_dir', '')}",
                ]
            )
        lines.extend(["", "## SOAP Heuristic State", "```json", json.dumps(self.soap.to_dict(), indent=2), "```"])
        lines.extend(["", "## KQML Trace Tail", "```"])
        lines.extend(render_kqml(msg) for msg in self.kqml_trace[-12:])
        lines.append("```")
        (self.workspace / "GENETIC_CODER_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class HeuristicGeneticCoderManager:
    def __init__(self) -> None:
        self.jobs: Dict[str, HeuristicGeneticCoderJob] = {}
        self.lock = threading.RLock()

    def start(self, **kwargs: Any) -> Dict[str, Any]:
        job = HeuristicGeneticCoderJob(**kwargs)
        with self.lock:
            self.jobs[job.job_id] = job
        job.start()
        return job.to_dict()

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
        return job.to_dict() if job else None

    def stop(self, job_id: str) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            return {"ok": False, "error": "Genetic coder job not found."}
        job.stop()
        return {"ok": True, "job_id": job_id, "status": job.status}

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [job.to_dict() for job in sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)]


def _python_exe() -> Path:
    configured = os.getenv("AEGIS_PYTHON", "").strip()
    if configured and Path(configured).exists():
        return Path(configured)
    default = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe"
    return default if default.exists() else Path("python")


def _run_command(command: List[str], cwd: Path, timeout: int) -> Dict[str, Any]:
    start = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "duration_seconds": round(time.time() - start, 3),
            "command": command,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": "timeout",
            "duration_seconds": round(time.time() - start, 3),
            "command": command,
        }


def _build_debugger_evidence(
    *,
    language: str,
    compile_result: Dict[str, Any],
    runtime_result: Dict[str, Any],
    files: Dict[str, str],
) -> Dict[str, Any]:
    """Convert verifier output into bounded repair hints for the next mutation."""
    stderr = "\n".join(
        str(part or "")
        for part in (
            compile_result.get("stderr"),
            runtime_result.get("stderr"),
            runtime_result.get("stdout") if not runtime_result.get("ok") else "",
        )
    )
    combined = stderr[-3000:]
    hints: List[str] = []
    lower = combined.lower()
    if "syntaxerror" in lower or "indentationerror" in lower:
        hints.append("repair syntax before changing behavior")
    if "assertionerror" in lower:
        hints.append("align output shape with TestSet assertions")
    if "modulenotfounderror" in lower or "importerror" in lower:
        hints.append("remove undeclared dependencies or add local fallback")
    if "jsondecodeerror" in lower:
        hints.append("make CLI emit valid JSON only")
    if "timeout" in lower:
        hints.append("reduce loops and bound runtime")
    if not hints and not compile_result.get("ok"):
        hints.append("inspect compiler stderr and produce the smallest compiling patch")
    if not hints and compile_result.get("ok") and not runtime_result.get("ok"):
        hints.append("inspect runtime failure and mutate the smallest behavior surface")

    return {
        "enabled": True,
        "adapter": "python-trace-parser" if (language or "python").lower() == "python" else "generic-compiler-output-parser",
        "binary_adapter_ready": False,
        "binary_adapter_note": "Vector35/Binary Ninja or equivalent debugger output should enter here as trace evidence before the next compile/test attempt.",
        "compile_pass": bool(compile_result.get("ok")),
        "runtime_pass": bool(runtime_result.get("ok")),
        "repair_hints": hints[:5],
        "signal_tail": combined[-1200:],
        "files_observed": sorted(files.keys()),
    }


def _render_python_project(
    objective: str,
    outline: str,
    heuristics: List[str],
    snippets: Optional[List[Dict[str, Any]]] = None,
    template: Optional[CodeTemplate] = None,
) -> Dict[str, str]:
    template = template or _infer_code_template(objective, outline)
    objective_literal = json.dumps(objective, ensure_ascii=True)
    outline_literal = json.dumps(outline, ensure_ascii=True)
    template_literal = json.dumps(asdict(template), ensure_ascii=True)
    snippet_lines = []
    for item in (snippets or [])[-8:]:
        title = str(item.get("title") or item.get("url") or "snippet").strip()
        content = re.sub(r"\s+", " ", str(item.get("content") or item.get("snippet") or "")).strip()
        if title or content:
            snippet_lines.append({"title": title[:120], "content": content[:360], "url": str(item.get("url") or "")})
    snippets_literal = json.dumps(snippet_lines, ensure_ascii=True)
    include_json = "json_report" in heuristics
    include_hook = "decompile_compile_hook" in heuristics
    if template.template_id == "python_local_web_app":
        index = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LAB_OUTPUT App</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main class="shell">
    <p class="eyebrow">AEGIS LAB_OUTPUT</p>
    <h1>{objective}</h1>
    <section id="evidence"></section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
'''
        style = '''body { margin: 0; font-family: Segoe UI, sans-serif; background: #0f172a; color: #e2e8f0; }
.shell { max-width: 860px; margin: 8vh auto; padding: 32px; border: 1px solid #334155; border-radius: 24px; background: #111827; }
.eyebrow { color: #38bdf8; letter-spacing: .16em; font-size: 12px; text-transform: uppercase; }
h1 { line-height: 1.1; }
#evidence { margin-top: 24px; padding: 18px; background: #020617; border-radius: 16px; white-space: pre-wrap; }
'''
        script = f'''const evidence = {json.dumps({
            "ok": True,
            "objective": objective,
            "framework": template.framework,
            "estimated_pages": template.pages,
            "estimated_target_lines": template.target_lines,
            "steps": ["serve local page", "render objective", "return EvidenceSet"]
        }, ensure_ascii=True, indent=2)};
document.getElementById("evidence").textContent = JSON.stringify(evidence, null, 2);
'''
        app = f'''from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict


OBJECTIVE = {objective_literal}
TEMPLATE = {template_literal}
ROOT = Path(__file__).resolve().parent


def evidence_set() -> Dict[str, Any]:
    return {{"ok": True, "objective": OBJECTIVE, "template": TEMPLATE, "served_files": ["templates/index.html", "static/style.css", "static/app.js"]}}


def main(port: int = 8765) -> int:
    print(json.dumps(evidence_set(), indent=2))
    print(f"Open http://127.0.0.1:{{port}}")
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
        test = '''from __future__ import annotations

import json
from pathlib import Path

import app


def test_evidence_shape() -> None:
    payload = app.evidence_set()
    assert payload["ok"] is True
    assert payload["template"]["template_id"] == "python_local_web_app"


def test_static_files_exist() -> None:
    root = Path(__file__).resolve().parent
    assert (root / "templates" / "index.html").read_text(encoding="utf-8")
    assert "AEGIS LAB_OUTPUT" in (root / "templates" / "index.html").read_text(encoding="utf-8")
    assert (root / "static" / "app.js").read_text(encoding="utf-8")


if __name__ == "__main__":
    test_evidence_shape()
    test_static_files_exist()
    print("PASS")
'''
        readme = f"""# LAB_OUTPUT Web Candidate

Objective: {objective}

Framework: {template.framework}
Estimated pages: {template.pages}
Estimated target lines: {template.target_lines}

Run tests:

```powershell
python -m py_compile app.py test_app.py
python test_app.py
```

Run app:

```powershell
python app.py
```
"""
        return {
            "app.py": app,
            "templates/index.html": index,
            "static/style.css": style,
            "static/app.js": script,
            "test_app.py": test,
            "README.md": readme,
        }

    if template.template_id == "python_data_cli":
        sample = json.dumps(
            {
                "objective": objective,
                "items": [
                    {"name": "alpha", "value": 1},
                    {"name": "beta", "value": 2},
                ],
            },
            ensure_ascii=True,
            indent=2,
        )
        app = f'''from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


OBJECTIVE = {objective_literal}
TEMPLATE = {template_literal}


def load_input(path: str = "sample_input.json") -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_evidence(data: Dict[str, Any]) -> Dict[str, Any]:
    items = data.get("items") if isinstance(data, dict) else []
    return {{
        "ok": True,
        "objective": OBJECTIVE,
        "template": TEMPLATE,
        "item_count": len(items) if isinstance(items, list) else 0,
        "keys": sorted(data.keys()) if isinstance(data, dict) else [],
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description="LAB_OUTPUT data CLI candidate")
    parser.add_argument("--input", default="sample_input.json")
    args = parser.parse_args()
    print(json.dumps(build_evidence(load_input(args.input)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
        test = '''from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import app


def test_sample_input_exists() -> None:
    assert Path("sample_input.json").exists()


def test_build_evidence() -> None:
    payload = app.build_evidence(app.load_input())
    assert payload["ok"] is True
    assert payload["template"]["template_id"] == "python_data_cli"
    assert payload["item_count"] == 2


def test_cli_outputs_json() -> None:
    completed = subprocess.run([sys.executable, "app.py"], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True


if __name__ == "__main__":
    test_sample_input_exists()
    test_build_evidence()
    test_cli_outputs_json()
    print("PASS")
'''
        readme = f"""# LAB_OUTPUT Data CLI Candidate

Objective: {objective}

Framework: {template.framework}
Estimated target lines: {template.target_lines}

Run:

```powershell
python test_app.py
python app.py --input sample_input.json
```
"""
        return {"app.py": app, "sample_input.json": sample, "test_app.py": test, "README.md": readme}

    if template.template_id == "python_tkinter_gui":
        app = f'''from __future__ import annotations

import json
from typing import Any, Dict


OBJECTIVE = {objective_literal}
TEMPLATE = {template_literal}


def build_evidence() -> Dict[str, Any]:
    return {{"ok": True, "objective": OBJECTIVE, "template": TEMPLATE, "ui": "tkinter"}}


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    root.title("LAB_OUTPUT GUI Candidate")
    frame = tk.Frame(root, padx=18, pady=18)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text=OBJECTIVE, wraplength=520, justify="left").pack(anchor="w")
    text = tk.Text(frame, height=10, width=72)
    text.pack(fill="both", expand=True, pady=(12, 0))
    text.insert("1.0", json.dumps(build_evidence(), indent=2))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
        test = '''from __future__ import annotations

import app


def test_build_evidence() -> None:
    payload = app.build_evidence()
    assert payload["ok"] is True
    assert payload["template"]["template_id"] == "python_tkinter_gui"
    assert payload["ui"] == "tkinter"


if __name__ == "__main__":
    test_build_evidence()
    print("PASS")
'''
        readme = f"""# LAB_OUTPUT Tkinter GUI Candidate

Objective: {objective}

Framework: {template.framework}
Estimated target lines: {template.target_lines}

Run:

```powershell
python test_app.py
python app.py
```
"""
        return {"app.py": app, "test_app.py": test, "README.md": readme}

    app = f'''from __future__ import annotations

import json
from typing import Any, Dict, List


OBJECTIVE = {objective_literal}
OUTLINE = {outline_literal}
SOURCE_SNIPPETS = {snippets_literal}
TEMPLATE = {template_literal}


def build_steps(objective: str = OBJECTIVE, outline: str = OUTLINE) -> List[str]:
    base = [
        "parse objective into AskSet and ConstraintSet",
        "create minimal executable CodeSet",
        "run compile and runtime TestSet",
        "return EvidenceSet before claiming success",
    ]
    if outline:
        base.insert(1, "respect Aider outline first and last page")
    if SOURCE_SNIPPETS:
        base.insert(2, "use SourceSnippetSet as implementation evidence")
    return base


def solve(objective: str = OBJECTIVE) -> Dict[str, Any]:
    steps = build_steps(objective)
    result = {{"ok": True, "objective": objective, "steps": steps, "template": TEMPLATE}}
    if {str(include_json)}:
        result["report_format"] = "json"
    if {str(include_hook)}:
        result["compile_decompile_hook"] = "reserved"
    if SOURCE_SNIPPETS:
        result["source_snippet_count"] = len(SOURCE_SNIPPETS)
    return result


def main() -> int:
    print(json.dumps(solve(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    test = '''from __future__ import annotations

import json
import subprocess
import sys

import app


def test_solve_shape() -> None:
    result = app.solve()
    assert isinstance(result, dict)
    assert result.get("objective")
    assert isinstance(result.get("steps"), list)
    assert "EvidenceSet" in " ".join(result["steps"])


def test_cli_outputs_json() -> None:
    completed = subprocess.run([sys.executable, "app.py"], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True


if __name__ == "__main__":
    test_solve_shape()
    test_cli_outputs_json()
    print("PASS")
'''
    readme = f"""# Genetic Coder Candidate

Objective: {objective}

This candidate was produced by the heuristic genetic coder. It is intentionally
small: successful attempts are fed back to SQLite before larger synthesis.

Source snippets attached: {len(snippet_lines)}
"""
    return {"app.py": app, "test_app.py": test, "README.md": readme}


def _score_candidate(candidate: Candidate, compile_result: Dict[str, Any], runtime_result: Dict[str, Any], likelihood: Dict[str, Any]) -> float:
    score = 0.0
    if compile_result.get("ok"):
        score += 0.35
    if runtime_result.get("ok"):
        score += 0.45
    score += min(0.12, 0.02 * len(candidate.heuristics))
    score += min(0.08, float(likelihood.get("probability") or 0) * 0.08)
    if not runtime_result.get("ok"):
        score -= 0.05
    return round(max(0.0, min(1.0, score)), 4)


genetic_coder_manager = HeuristicGeneticCoderManager()
