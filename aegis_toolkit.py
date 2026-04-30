"""
Unified tool/plugin architecture for AEGIS.

This standardizes local tools behind a shared interface so both the local
kernel and future cloud/kernel adapters can execute them consistently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from agentic_crawler_db import crawler_db
from browser_use_bridge import browser_use_runtime_status, run_browser_use_task
from logic_cube_solver import boolean_multiply, solve_logic_cube
from picoclaw_bridge import delegate_picoclaw, picoclaw_runtime_status
from script_registry import search_scripts
from vector_memory import vector_memory

OFFICIAL_SOURCE_DOMAINS = {
    "learn.microsoft.com",
    "support.microsoft.com",
    "microsoft.com",
    "windows.com",
    "postgresql.org",
    "qdrant.tech",
    "cloudflare.com",
    "openai.com",
    "developer.mozilla.org",
    "mozilla.org",
    "python.org",
    "docs.python.org",
}
REPUTABLE_TECH_DOMAINS = {
    "arstechnica.com",
    "howtogeek.com",
    "tomshardware.com",
    "pcgamer.com",
    "pcmag.com",
    "stackexchange.com",
    "stackoverflow.com",
}
COMMUNITY_SOURCE_DOMAINS = {
    "reddit.com",
    "superuser.com",
    "answers.microsoft.com",
}


def score_source_credibility(url: str, title: str = "") -> Dict[str, Any]:
    parsed = urlparse(url or "")
    domain = (parsed.netloc or "").lower()
    scheme = (parsed.scheme or "").lower()
    title_lower = (title or "").lower()
    url_lower = (url or "").lower()
    score = 0.35
    label = "unclassified"

    if any(domain == item or domain.endswith(f".{item}") for item in OFFICIAL_SOURCE_DOMAINS):
        score = 0.95
        label = "official_vendor"
    elif domain.endswith(".gov"):
        score = 0.98
        label = "government"
    elif domain.endswith(".edu"):
        score = 0.92
        label = "academic"
    elif any(domain == item or domain.endswith(f".{item}") for item in REPUTABLE_TECH_DOMAINS):
        score = 0.74
        label = "reputable_tech_media"
    elif any(domain == item or domain.endswith(f".{item}") for item in COMMUNITY_SOURCE_DOMAINS):
        score = 0.58
        label = "community"
    elif domain.endswith(".org"):
        score = 0.68
        label = "organization"
    elif domain.endswith(".com"):
        score = 0.52
        label = "commercial"

    if scheme == "https":
        score = min(score + 0.02, 0.99)

    whitepaper_like = any(
        token in title_lower or token in url_lower
        for token in ("whitepaper", "research paper", "technical paper", "technical report", ".pdf", "arxiv")
    )
    if whitepaper_like:
        score = min(score + 0.04, 0.99)

    purpose_risk = "low"
    if label in {"community", "commercial"}:
        purpose_risk = "medium"
    if label == "unclassified":
        purpose_risk = "high"

    return {
        "score": round(score, 2),
        "label": label,
        "domain": domain or "unknown",
        "authority_score": round(score, 2),
        "purpose_risk": purpose_risk,
        "corroboration_required": score < 0.8,
        "format_hint": "whitepaper_or_pdf" if whitepaper_like else "web_page",
        "criteria": [
            "author_or_publisher",
            "purpose_and_bias",
            "scope_and_coverage",
            "currency",
            "corroboration",
        ],
    }


@dataclass
class ToolResult:
    ok: bool
    output: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        prefix = "[OK]" if self.ok else "[ERROR]"
        if not self.metadata:
            return f"{prefix} {self.output}"
        return f"{prefix} {self.output}\n{json.dumps(self.metadata, indent=2)}"


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    return [item.strip() for item in raw.split(",") if item.strip()]


class BaseAegisTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, str] = {}
    expose_to_llm: bool = True

    def schema(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "parameters": self.parameters,
        }

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError


class CreateFileTool(BaseAegisTool):
    name = "create_file"
    description = "Create a new file with content"
    parameters = {
        "path": "string - file path",
        "content": "string - file content",
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
        content = str(kwargs.get("content", ""))
        if not path:
            return ToolResult(False, "Missing required parameter: path")
        try:
            target = Path(path)
            existed_before = target.exists()
            if target.parent:
                target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(
                True,
                f"File created: {target}",
                {
                    "action": "create_file",
                    "path": str(target),
                    "parent": str(target.parent),
                    "existed_before": existed_before,
                    "exists_now": target.exists(),
                    "content_chars": len(content),
                },
            )
        except PermissionError:
            target = Path(path)
            root_hint = (
                " Writing directly to the drive root may require administrator privileges."
                if str(target.parent) == f"{target.drive}\\"
                else ""
            )
            return ToolResult(False, f"Permission denied for path: {target}.{root_hint}")
        except Exception as exc:
            return ToolResult(False, str(exc))


class CreateDirectoryTool(BaseAegisTool):
    name = "create_directory"
    description = "Create a new directory or folder"
    parameters = {
        "path": "string - directory path",
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
        if not path:
            return ToolResult(False, "Missing required parameter: path")
        try:
            target = Path(path)
            existed_before = target.exists()
            target.mkdir(parents=True, exist_ok=True)
            return ToolResult(
                True,
                f"Directory ready: {target}",
                {
                    "action": "create_directory",
                    "path": str(target),
                    "parent": str(target.parent),
                    "existed_before": existed_before,
                    "exists_now": target.exists(),
                },
            )
        except PermissionError:
            target = Path(path)
            root_hint = (
                " Creating folders directly at the drive root may require administrator privileges."
                if str(target.parent) == f"{target.drive}\\"
                else ""
            )
            return ToolResult(False, f"Permission denied for path: {target}.{root_hint}")
        except Exception as exc:
            return ToolResult(False, str(exc))


class ReadFileTool(BaseAegisTool):
    name = "read_file"
    description = "Read contents of a file"
    parameters = {
        "path": "string - file path",
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
        if not path:
            return ToolResult(False, "Missing required parameter: path")
        try:
            return ToolResult(True, Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            return ToolResult(False, str(exc))


class ListDirectoryTool(BaseAegisTool):
    name = "list_directory"
    description = "List files in a directory"
    parameters = {
        "path": "string - directory path",
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "")).strip()
        if not path:
            return ToolResult(False, "Missing required parameter: path")
        try:
            files = os.listdir(path)
            return ToolResult(True, "\n".join(files))
        except Exception as exc:
            return ToolResult(False, str(exc))


class ExecuteCommandTool(BaseAegisTool):
    name = "execute_command"
    description = "Execute a shell command"
    parameters = {
        "command": "string - command to execute",
    }

    def execute(self, **kwargs) -> ToolResult:
        command = str(kwargs.get("command", "")).strip()
        if not command:
            return ToolResult(False, "Missing required parameter: command")
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            output = result.stdout if result.stdout else result.stderr
            success = result.returncode == 0
            return ToolResult(success, output or "(no output)", {"returncode": result.returncode})
        except Exception as exc:
            return ToolResult(False, str(exc))


class SearchWebTool(BaseAegisTool):
    name = "search_web"
    description = "Search the web for information, rank sources by credibility, and return top result URLs"
    parameters = {
        "query": "string - search query",
    }

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(False, "Missing required parameter: query")
        results = crawler_db.search_web(query, max_results=5)
        if not results:
            return ToolResult(False, f"No web results found for: {query}")
        if results[0].get("title") == "search_error":
            return ToolResult(False, results[0].get("snippet", "unknown search error"))

        ranked_results = []
        for result in results:
            credibility = score_source_credibility(
                result.get("url", ""),
                title=result.get("title", ""),
            )
            ranked_results.append({**result, "credibility": credibility})
        ranked_results.sort(
            key=lambda item: item.get("credibility", {}).get("score", 0.0),
            reverse=True,
        )

        lines = [f"Top web results for: {query}"]
        for index, result in enumerate(ranked_results, start=1):
            credibility = result.get("credibility", {})
            lines.append(
                f"{index}. [score={credibility.get('score', 0):.2f} {credibility.get('label', 'unknown')} "
                f"risk={credibility.get('purpose_risk', 'unknown')} format={credibility.get('format_hint', 'unknown')} "
                f"corroborate={credibility.get('corroboration_required', True)}] "
                f"{result.get('title')} - {result.get('url')}"
            )
        return ToolResult(True, "\n".join(lines), {"ranked_results": ranked_results})


class CrawlURLTool(BaseAegisTool):
    name = "crawl_url"
    description = "Crawl a web page into the local text database"
    parameters = {
        "url": "string - web page URL",
    }

    def execute(self, **kwargs) -> ToolResult:
        url = str(kwargs.get("url", "")).strip()
        if not url:
            return ToolResult(False, "Missing required parameter: url")
        result = crawler_db.crawl_url(url, max_depth=0, max_pages=1, same_domain_only=True)
        if result.get("error"):
            return ToolResult(False, result["error"])
        stored = result.get("stored_chunks", [])
        if not stored:
            return ToolResult(False, f"No crawlable text found at {url}")
        first = stored[0]
        return ToolResult(
            True,
            f"Stored {len(first.get('chunk_ids', []))} chunk(s) from {first.get('url')}",
            {"pages_crawled": result.get("pages_crawled", 0)},
        )


class SearchProjectMemoryTool(BaseAegisTool):
    name = "search_project_memory"
    description = "Search the local hybrid vector memory for a project"
    parameters = {
        "query": "string - search query",
        "project": "string - project name",
    }

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        project = str(kwargs.get("project", "")).strip()
        if not query or not project:
            return ToolResult(False, "Missing required parameters: query and project")
        results = vector_memory.search(query, project=project, limit=5)
        if not results:
            return ToolResult(False, f"No project memory results for '{query}' in project '{project}'.")

        lines = [f"Project memory hits for {project}:"]
        for index, result in enumerate(results, start=1):
            content = (result.get("content") or "")[:180]
            lines.append(
                f"{index}. [{result.get('kind', 'memory')}/{result.get('role', 'unknown')}] "
                f"score={result.get('score', 0):.3f} {content}"
            )
        return ToolResult(True, "\n".join(lines))


class SearchScriptRegistryTool(BaseAegisTool):
    name = "search_script_registry"
    description = "Search the weighted database of local scripts by query, language, and evidence weight"
    parameters = {
        "query": "string - script name, purpose, tag, or content query",
        "language": "string - optional language filter such as python, powershell, javascript",
        "limit": "integer - optional result limit",
    }

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        language = str(kwargs.get("language", "")).strip()
        try:
            limit = max(1, min(int(kwargs.get("limit", 10)), 50))
        except Exception:
            limit = 10
        results = search_scripts(query=query, language=language, limit=limit)
        if not results:
            return ToolResult(False, f"No weighted script results for query '{query}'.")
        lines = ["Weighted script registry hits:"]
        for index, item in enumerate(results, start=1):
            lines.append(
                f"{index}. weight={float(item.get('weight', 0)):.3f} "
                f"lang={item.get('language')} lines={item.get('line_count')} "
                f"path={item.get('path')}"
            )
            tags = ", ".join(item.get("tags") or [])
            if tags:
                lines.append(f"   tags={tags}")
        return ToolResult(
            True,
            "\n".join(lines),
            {
                "query": query,
                "language": language,
                "limit": limit,
                "count": len(results),
                "results": results,
            },
        )


class SystemHeartbeatTool(BaseAegisTool):
    name = "run_system_heartbeat"
    description = "Inspect system load, AI process counts, duplicate runtime candidates, and optional safe temp cleanup"
    parameters = {
        "cleanup_temp": "boolean - optional, clean only the current user's temp folder",
        "kill_extra_gemini_cli": "boolean - optional, stop extra gemini-cli node processes and keep the newest one",
        "temp_days": "integer - optional, minimum age in days for temp cleanup candidates",
    }

    def execute(self, **kwargs) -> ToolResult:
        script_path = Path(__file__).resolve().parent / "maintenance" / "Aegis_Heartbeat.ps1"
        report_path = Path(__file__).resolve().parent / "maintenance" / "monitoring" / "heartbeat_latest.json"
        if not script_path.exists():
            return ToolResult(False, f"Missing heartbeat script: {script_path}")

        cleanup_temp = bool(kwargs.get("cleanup_temp", False))
        kill_extra_gemini_cli = bool(kwargs.get("kill_extra_gemini_cli", False))
        try:
            temp_days = max(1, int(kwargs.get("temp_days", 2)))
        except Exception:
            temp_days = 2

        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-TempDays",
            str(temp_days),
        ]
        if cleanup_temp:
            command.append("-CleanupTemp")
        if kill_extra_gemini_cli:
            command.append("-KillExtraGeminiCli")

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=90,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            return ToolResult(False, str(exc))

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            return ToolResult(
                False,
                stdout or stderr or "Heartbeat command failed",
                {
                    "returncode": result.returncode,
                    "script": str(script_path),
                },
            )

        report_data: Dict[str, Any] = {}
        if report_path.exists():
            try:
                report_data = json.loads(report_path.read_text(encoding="utf-8-sig"))
            except Exception:
                report_data = {}

        signals = report_data.get("boolean_signals", {}) if isinstance(report_data, dict) else {}
        ai_counts = report_data.get("ai_process_counts", {}) if isinstance(report_data, dict) else {}
        temp = report_data.get("temp", {}) if isinstance(report_data, dict) else {}
        output_lines = [
            "System heartbeat complete.",
            f"CPU: {report_data.get('cpu_percent', 'unknown')}%",
            f"Available memory: {report_data.get('available_memory_mb', 'unknown')} MB",
            (
                "AI process counts: "
                f"bridge={ai_counts.get('uvicorn_bridge', 'unknown')}, "
                f"gemini_cli={ai_counts.get('gemini_cli_node', 'unknown')}, "
                f"ollama={ai_counts.get('ollama', 'unknown')}"
            ),
            (
                "Temp candidates: "
                f"{temp.get('candidate_count', 0)} item(s), "
                f"{temp.get('candidate_bytes', 0)} byte(s)"
            ),
            (
                "Signals: "
                + ", ".join(f"{key}={value}" for key, value in signals.items())
                if signals
                else "Signals: none"
            ),
        ]
        if stdout:
            output_lines.append(stdout)

        metadata = {
            "report_path": str(report_path),
            "cleanup_temp": cleanup_temp,
            "kill_extra_gemini_cli": kill_extra_gemini_cli,
            "temp_days": temp_days,
            "report": report_data,
        }
        return ToolResult(True, "\n".join(output_lines), metadata)


class LogicCubeSolverTool(BaseAegisTool):
    name = "solve_logic_cube"
    description = "Solve a boolean matrix directive cube"
    expose_to_llm = False
    parameters = {
        "A": "array - boolean matrix",
        "target": "array - boolean target matrix",
        "max_iterations": "integer - optional iteration limit",
    }

    def execute(self, **kwargs) -> ToolResult:
        try:
            matrix_a = np.array(kwargs.get("A"), dtype=int)
            target = np.array(kwargs.get("target"), dtype=int)
            max_iterations = int(kwargs.get("max_iterations", 1000))
            solution, iterations = solve_logic_cube(matrix_a, target, max_iterations=max_iterations)
            result_state = boolean_multiply(matrix_a, solution).tolist()
            return ToolResult(
                True,
                f"Logic cube solved in {iterations} iteration(s).",
                {
                    "solution": solution.tolist(),
                    "result_state": result_state,
                },
            )
        except Exception as exc:
            return ToolResult(False, str(exc))


class AgenticResearchTool(BaseAegisTool):
    name = "run_research_query"
    description = "Run a multi-result web search and crawl pass"
    expose_to_llm = False
    parameters = {
        "query": "string - research query",
        "max_results": "integer - optional result count",
        "max_pages": "integer - optional page count",
    }

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(False, "Missing required parameter: query")
        max_results = int(kwargs.get("max_results", 5))
        max_pages = int(kwargs.get("max_pages", 5))
        result = crawler_db.research_query(query, max_results=max_results, max_pages=max_pages)
        return ToolResult(
            True,
            f"Research query completed for '{query}'.",
            {
                "errors": result.get("errors", []),
                "crawls": len(result.get("crawls", [])),
                "search_results": len(result.get("search_results", [])),
            },
        )


class PhoneAutomationBridgeTool(BaseAegisTool):
    name = "phone_automation_bridge"
    description = "Describe the Android automation bridge script and where to deploy it"
    expose_to_llm = False
    parameters = {}

    def execute(self, **_kwargs) -> ToolResult:
        script_path = Path(__file__).resolve().parent / "phone_automation_script.js"
        if not script_path.exists():
            return ToolResult(False, f"Missing script: {script_path}")
        return ToolResult(
            True,
            "Phone automation bridge is packaged as an external Auto.js / MacroDroid script.",
            {
                "path": str(script_path),
                "runtime": "Auto.js or MacroDroid JavaScript runtime on Android",
            },
        )


class PicoClawDelegateTool(BaseAegisTool):
    name = "delegate_picoclaw"
    description = "Delegate a compact coding or verification subtask to the tiny PicoClaw sidecar"
    parameters = {
        "prompt": "string - coordinator prompt; italicized text is treated as the highest-priority intent",
        "workspace": "string - optional workspace or target path to mention",
        "session": "string - optional PicoClaw session key",
        "model_name": "string - optional PicoClaw model alias",
        "timeout_seconds": "integer - optional timeout, default 90",
    }

    def execute(self, **kwargs) -> ToolResult:
        prompt = str(kwargs.get("prompt", "")).strip()
        if not prompt:
            return ToolResult(False, "Missing required parameter: prompt")

        result = delegate_picoclaw(
            prompt,
            workspace=str(kwargs.get("workspace", "")).strip() or None,
            session=str(kwargs.get("session", "")).strip() or None,
            model_name=str(kwargs.get("model_name", "")).strip() or None,
            timeout_seconds=max(15, min(int(kwargs.get("timeout_seconds", 90)), 300)),
        )
        if not result.get("ok"):
            return ToolResult(False, result.get("error") or result.get("response") or "PicoClaw delegation failed.", result)
        return ToolResult(True, result.get("response", "PicoClaw delegation completed."), result)


class BrowserUseTaskTool(BaseAegisTool):
    name = "browser_use_task"
    description = "Run an isolated browser-use task in the dedicated venv with the tiny local model"
    parameters = {
        "task": "string - browser task to execute",
        "start_url": "string - optional starting URL",
        "allowed_domains": "string - optional comma-separated or JSON-array domain allowlist",
        "headless": "boolean - optional headless mode, default true",
        "max_steps": "integer - optional max browser steps, default 10",
        "timeout_seconds": "integer - optional timeout, default 240",
        "workspace": "string - optional workspace note for the task",
    }

    def execute(self, **kwargs) -> ToolResult:
        task = str(kwargs.get("task", "")).strip()
        if not task:
            return ToolResult(False, "Missing required parameter: task")

        result = run_browser_use_task(
            task,
            start_url=str(kwargs.get("start_url", "")).strip() or None,
            allowed_domains=_coerce_list(kwargs.get("allowed_domains")),
            headless=_coerce_bool(kwargs.get("headless", True), default=True),
            max_steps=max(1, min(int(kwargs.get("max_steps", 10)), 25)),
            timeout_seconds=max(30, min(int(kwargs.get("timeout_seconds", 240)), 600)),
            workspace=str(kwargs.get("workspace", "")).strip() or None,
        )
        if not result.get("ok"):
            return ToolResult(False, result.get("error") or result.get("summary") or "browser-use task failed.", result)
        return ToolResult(True, result.get("summary", "browser-use task completed."), result)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseAegisTool] = {}

    def register(self, tool: BaseAegisTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseAegisTool]:
        return self._tools.get(name)

    def execute_result(self, name: str, parameters: Optional[Dict[str, Any]] = None) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return ToolResult(False, f"Unknown tool: {name}", {"tool": name})
        return tool.execute(**(parameters or {}))

    def execute(self, name: str, parameters: Optional[Dict[str, Any]] = None) -> str:
        return self.execute_result(name, parameters).render()

    def llm_schemas(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: tool.schema()
            for name, tool in self._tools.items()
            if tool.expose_to_llm
        }

    def all_tools(self) -> Dict[str, BaseAegisTool]:
        return dict(self._tools)


tool_registry = ToolRegistry()
tool_registry.register(CreateFileTool())
tool_registry.register(CreateDirectoryTool())
tool_registry.register(ReadFileTool())
tool_registry.register(ListDirectoryTool())
tool_registry.register(ExecuteCommandTool())
tool_registry.register(SearchWebTool())
tool_registry.register(CrawlURLTool())
tool_registry.register(SearchProjectMemoryTool())
tool_registry.register(SearchScriptRegistryTool())
tool_registry.register(SystemHeartbeatTool())
tool_registry.register(LogicCubeSolverTool())
tool_registry.register(AgenticResearchTool())
tool_registry.register(PicoClawDelegateTool())
tool_registry.register(BrowserUseTaskTool())
tool_registry.register(PhoneAutomationBridgeTool())
