"""
Tool calling helpers for the local AEGIS model.

Backed by the unified BaseAegisTool registry so local and future cloud/kernel
tool execution can share the same interface.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any, Dict, List

from aegis_toolkit import ToolResult, tool_registry

TOOLS = tool_registry.llm_schemas()
PARALLEL_SAFE_TOOLS = {
    "search_project_memory",
    "search_script_registry",
    "search_web",
    "run_system_heartbeat",
    "list_directory",
    "read_file",
}


COMMON_NORMALIZATIONS = {
    "consecutivly": "consecutively",
    "definately": "definitely",
    "enviroment": "environment",
    "exparation": "expiration",
    "oporating": "operating",
    "opreating": "operating",
    "paralell": "parallel",
    "parralel": "parallel",
    "sluggsh": "sluggish",
    "sluggishh": "sluggish",
    "speling": "spelling",
    "thigs": "things",
    "unsluggify": "unsluggish",
}


def normalize_prompt_text(prompt: str) -> str:
    text = (prompt or "").lower()
    for wrong, correct in COMMON_NORMALIZATIONS.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", correct, text)
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9:\\/.\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _prompt_tokens(prompt: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", normalize_prompt_text(prompt))


def _fuzzy_token_match(token: str, candidate: str, threshold: float = 0.84) -> bool:
    if token == candidate:
        return True
    return SequenceMatcher(None, token, candidate).ratio() >= threshold


def prompt_matches_signal(prompt: str, signal: str) -> bool:
    normalized_prompt = normalize_prompt_text(prompt)
    normalized_signal = normalize_prompt_text(signal)
    if not normalized_signal:
        return False
    if normalized_signal in normalized_prompt:
        return True

    prompt_tokens = _prompt_tokens(normalized_prompt)
    signal_tokens = _prompt_tokens(normalized_signal)
    if not prompt_tokens or not signal_tokens:
        return False

    matched = 0
    for signal_token in signal_tokens:
        if any(_fuzzy_token_match(prompt_token, signal_token) for prompt_token in prompt_tokens):
            matched += 1

    required = max(1, len(signal_tokens) - 1)
    return matched >= required


def build_request_profile(prompt: str) -> Dict[str, Any]:
    normalized = normalize_prompt_text(prompt)

    def has_any(signals: List[str]) -> bool:
        return any(prompt_matches_signal(normalized, signal) for signal in signals)

    def has_exact_any(signals: List[str]) -> bool:
        return any(str(signal or "").strip().lower() in normalized for signal in signals if str(signal or "").strip())

    research_signals = [
        "research",
        "credible sources",
        "whitepaper",
        "official docs",
        "look up",
        "latest",
        "current",
        "evidence",
        "cite",
    ]
    coding_signals = [
        "code",
        "coding",
        "bug",
        "fix",
        "implement",
        "build",
        "build app",
        "build program",
        "android",
        "android app",
        "apk",
        "d8",
        "dex",
        "flat java",
        "bottom up",
        "from scratch",
        "program",
        "application",
        "feature",
        "refactor",
        "script",
        "api",
        "function",
        "module",
        "test",
        "smoke test",
        "tool",
        "tools",
    ]
    verification_signals = [
        "verify",
        "test",
        "validate",
        "check",
        "confirm",
        "smoke test",
        "prove",
    ]
    automation_signals = [
        "automation",
        "automate",
        "agentic loop",
        "all night",
        "scheduler",
        "heartbeat",
        "background",
        "recurring",
        "monitoring",
    ]
    browser_signals = [
        "browser use",
        "browser-use",
        "browser automation",
        "navigate website",
        "click on the website",
        "web ui",
        "log into site",
        "open the page and click",
    ]
    filesystem_signals = [
        "file",
        "folder",
        "directory",
        "path",
        "c drive",
        "project lane",
        "workspace",
    ]
    system_signals = [
        "sluggish",
        "slow",
        "operating environment",
        "system health",
        "cleanup",
        "garbage",
        "temp files",
        "extra instances",
        "performance",
    ]
    multi_step_signals = [
        "step by step",
        "break it down",
        "end goal",
        "and then",
        "after that",
        "next",
        "multi step",
        "research code",
        "test code",
        "phase",
        "workflow",
    ]
    command_signals = [
        "run tests",
        "run command",
        "execute command",
        "smoke test",
        "build",
        "pytest",
        "uvicorn",
        "powershell",
        "cmd",
    ]
    # Persistent directive capture must be opt-in. Natural chat like
    # "you should..." or "I want..." should shape the model response, not
    # bypass the model with a canned "directive updated" reply.
    directive_signals = [
        "/directive",
        "/project directive",
        "/project lens",
        "save this directive",
        "store this directive",
        "persist this directive",
        "capture this directive",
        "update project directive",
        "set project directive",
        "update default directive",
        "set default directive",
        "update project lens",
        "set project lens",
        "save as project lens",
        "store as project lens",
    ]
    directive_prefixes = [
        "/directive",
        "/project directive",
        "/project lens",
        "save this directive:",
        "store this directive:",
        "persist this directive:",
        "capture this directive:",
        "update project directive:",
        "set project directive:",
        "update default directive:",
        "set default directive:",
        "update project lens:",
        "set project lens:",
        "save as project lens:",
        "store as project lens:",
    ]
    direct_build_request_signals = [
        "build me",
        "make me",
        "create me",
        "build a",
        "build an",
        "make a",
        "make an",
        "create a",
        "create an",
        "write a",
        "write an",
        "implement a",
        "implement an",
        "show me",
        "scan all",
        "map my",
    ]
    coding_action_signals = [
        "debug this",
        "debug the",
        "fix this",
        "fix the",
        "fix my",
        "patch this",
        "patch the",
        "edit this",
        "edit the",
        "implement",
        "write code",
        "write a script",
        "write a program",
        "create file",
        "create a file",
        "save to",
        "run tests",
        "run the test",
        "execute the code",
        "make it run",
        "make this run",
    ]
    directive_blocker_signals = [
        "run this",
        "fix this file",
        "create file",
        "create folder",
        "list directory",
        "read file",
        "execute command",
    ]
    full_response_signals = [
        "full response",
        "full answer",
        "complete response",
        "complete answer",
        "be more vocal",
        "more vocal",
        "more detail",
        "detailed response",
        "do not stop early",
        "don't stop early",
        "finish the answer",
        "not over until",
    ]
    make_it_run_signals = [
        "make it run",
        "make the code run",
        "make this run",
        "until it works",
        "until it runs",
        "actually runs",
        "working code",
        "runnable",
        "execute test fix",
        "test fix redo",
        "create program loop",
        "program loop",
        "build test fix",
        "fix redo cycle",
    ]
    research_loop_signals = [
        "research loop",
        "agentic research",
        "deep research",
        "keep researching",
        "crawl and research",
        "research all night",
    ]
    axiomatic_signals = [
        "axiomatic",
        "axiom",
        "logic set",
        "logic sets",
        "constraint set",
        "constraint sets",
        "mathematical set of constraints",
        "ask set",
        "program set",
        "logic block",
        "logic blocks",
        "move blocks around",
    ]
    compression_signals = [
        "code compression",
        "code compression synthesis",
        "flat java",
        "flat code",
        "flattened code",
        "compact code",
        "compiler friendly",
        "minimal nesting",
        "lightweight packages",
        "d8 compression",
        "apk compression",
        "termux compiler",
        "anonymous inner classes",
        "hidden runnables",
    ]
    d8_compression_signals = [
        "d8",
        "d8 compression",
        "dex",
        "apk",
        "android apk",
        "android app",
        "flat java",
        "termux compiler",
        "anonymous inner classes",
        "hidden runnables",
    ]
    targeted_web_synthesis_signals = [
        "targeted web synthesis",
        "targeted web-synthesis",
        "high precision web",
        "high-precision web",
        "precise web crawl",
        "precise web crawls",
        "exact hardware flags",
        "exact flags",
        "exact parameters",
        "implementation flags",
    ]
    planning_only_signals = [
        "do not write files",
        "don't write files",
        "no file writes",
        "plan only",
        "planning only",
        "talk through",
        "talk me through",
        "propose first",
        "propose the first",
        "first step only",
        "ask me before",
        "wait for approval",
        "before pico",
        "before picoclaw",
    ]
    discussion_intent_signals = [
        "see if we can",
        "see whether we can",
        "can we",
        "could we",
        "what if",
        "do you think",
        "should we",
        "talk about",
        "discuss",
        "reason about",
        "think through",
        "explore",
        "maybe",
        "possibly",
    ]
    explicit_action_override_signals = [
        "go ahead",
        "do it",
        "start the",
        "start a",
        "run it",
        "run this",
        "execute it",
        "execute this",
        "create the file",
        "write the file",
        "edit the file",
        "patch the file",
        "make it run",
        "ok start",
        "/program confirm",
    ]

    explicit_build_request = has_exact_any(direct_build_request_signals)
    mentions_code = has_any(coding_signals)
    discussion_intent = has_any(discussion_intent_signals) and not has_exact_any(explicit_action_override_signals)
    coding_action = (explicit_build_request or has_any(coding_action_signals)) and not discussion_intent
    needs_research = has_any(research_signals)
    needs_coding = coding_action
    needs_verification = has_any(verification_signals) and not discussion_intent
    needs_automation = has_any(automation_signals) and not discussion_intent
    needs_browser_automation = has_any(browser_signals) and not discussion_intent
    needs_filesystem = has_any(filesystem_signals) and not discussion_intent
    needs_system_diagnosis = has_any(system_signals) and not discussion_intent
    wants_full_response = has_exact_any(full_response_signals)
    must_make_code_run = has_exact_any(make_it_run_signals)
    use_research_loop = has_exact_any(research_loop_signals)
    needs_axiomatic_planning = has_any(axiomatic_signals)
    use_d8_compression = has_any(d8_compression_signals)
    planning_only = has_exact_any(planning_only_signals)
    prefer_code_compression = has_any(compression_signals) or use_d8_compression or (needs_coding and needs_axiomatic_planning)
    signal_count = sum(
        int(flag)
        for flag in (
            needs_research,
            needs_coding,
            needs_verification,
            needs_automation,
            needs_browser_automation,
            needs_system_diagnosis,
        )
    )
    is_multi_step = has_any(multi_step_signals) or signal_count >= 2
    use_logic_block_table = needs_axiomatic_planning or (needs_coding and is_multi_step)
    directive_phrase_match = has_exact_any(directive_signals)
    directive_prefix_match = any(normalized.startswith(prefix) for prefix in directive_prefixes if prefix)
    needs_code_execution_loop = bool(
        not planning_only
        and not discussion_intent
        and (
            explicit_build_request
            or must_make_code_run
            or (needs_coding and (needs_verification or needs_automation or is_multi_step))
        )
    )
    use_targeted_web_synthesis = (
        has_any(targeted_web_synthesis_signals)
        or (needs_research and needs_coding)
        or needs_code_execution_loop
    )
    directive_blocked_by_operation = has_exact_any(directive_blocker_signals) or any(
        normalized.startswith(prefix) for prefix in directive_blocker_signals if prefix
    )
    is_configuration_directive = (
        (directive_phrase_match or directive_prefix_match)
        and not explicit_build_request
        and not discussion_intent
        and not directive_blocked_by_operation
    )

    allow_operational_commands = (not planning_only) and (
        has_any(command_signals)
        or (needs_coding and (needs_verification or needs_automation or is_multi_step))
    )
    prefer_single_workspace = bool((not planning_only) and (needs_coding or needs_verification or needs_filesystem or must_make_code_run))
    requires_deliberate_mode = bool(
        (needs_research and not is_configuration_directive)
        or needs_system_diagnosis
        or needs_automation
        or (is_multi_step and (needs_verification or signal_count >= 2))
        or wants_full_response
        or must_make_code_run
        or use_research_loop
        or needs_code_execution_loop
    )

    return {
        "normalized_prompt": normalized,
        "needs_research": needs_research,
        "mentions_code": mentions_code,
        "discussion_intent": discussion_intent,
        "coding_action": coding_action,
        "needs_coding": needs_coding,
        "needs_verification": needs_verification,
        "needs_automation": needs_automation,
        "needs_browser_automation": needs_browser_automation,
        "needs_filesystem": needs_filesystem,
        "needs_system_diagnosis": needs_system_diagnosis,
        "is_multi_step": is_multi_step,
        "is_configuration_directive": is_configuration_directive,
        "allow_operational_commands": allow_operational_commands,
        "requires_deliberate_mode": requires_deliberate_mode,
        "prefer_parallel_tools": is_multi_step or needs_system_diagnosis,
        "wants_full_response": wants_full_response,
        "must_make_code_run": must_make_code_run,
        "needs_code_execution_loop": needs_code_execution_loop,
        "planning_only": planning_only,
        "use_research_loop": use_research_loop,
        "prefer_single_workspace": prefer_single_workspace,
        "needs_axiomatic_planning": needs_axiomatic_planning,
        "prefer_code_compression": prefer_code_compression,
        "use_d8_compression": use_d8_compression,
        "use_targeted_web_synthesis": use_targeted_web_synthesis,
        "use_logic_block_table": use_logic_block_table,
    }


def build_response_contract(request_profile: Dict[str, Any] | None = None) -> str:
    request_profile = request_profile or {}
    lines: List[str] = []

    if request_profile.get("wants_full_response"):
        lines.extend(
            [
                "Response contract:",
                "- Be explicit and complete instead of prematurely concise.",
                "- Do not stop after the first partial answer if a more useful continuation is obvious.",
            ]
        )

    if request_profile.get("must_make_code_run"):
        lines.extend(
            [
                "Completion contract:",
                "- The coding task is not done until the code runs, or the exact blocker and latest verification result are stated plainly.",
                "- Prefer one stable program workspace over scattered scratch files.",
            ]
        )

    if request_profile.get("needs_code_execution_loop"):
        lines.extend(
            [
                "Build-loop contract:",
                "- Do not end after the first draft on explicit build requests.",
                "- Partition the ask into logic blocks, use the relevant tool or PicoClaw lane, self-question the latest code/proposal, apply the answer, then summarize evidence.",
                "- Load the distilled coding kernel for the detected language before delegating or writing code.",
            ]
        )

    if request_profile.get("use_research_loop"):
        lines.extend(
            [
                "Research contract:",
                "- If evidence is thin, continue the research loop instead of answering from shallow memory.",
            ]
        )

    if request_profile.get("prefer_single_workspace"):
        lines.extend(
            [
                "Workspace contract:",
                "- Stay anchored to one relevant workspace or test area instead of bouncing across unrelated files.",
            ]
        )

    if (
        request_profile.get("needs_axiomatic_planning")
        or request_profile.get("prefer_code_compression")
        or request_profile.get("use_targeted_web_synthesis")
        or request_profile.get("use_logic_block_table")
    ):
        lines.extend(
            [
                "Method contract:",
                "- Reduce build tasks into ask set, program set, axioms, constraints, logic blocks, and acceptance tests.",
                "- Keep logic blocks explicit enough to hand to a coordinator or worker without extra interpretation.",
                "- Prefer compact, flattened, compiler-friendly code over decorative indirection.",
                "- When research is needed for implementation, carry forward only the exact flags, parameters, or constraints that unblock the build.",
            ]
        )

    if request_profile.get("use_d8_compression"):
        lines.extend(
            [
                "D8 compression contract:",
                "- For Android/Java/APK tasks, use Flat Java with named classes, direct handlers, explicit manifest/build steps, and minimal dependencies.",
                "- Avoid anonymous inner classes, lambdas, hidden Runnables, reflection-heavy glue, and ornamental wrapper layers.",
            ]
        )

    return "\n".join(lines).strip()


def _extract_prompt_clauses(prompt: str, limit: int = 6) -> List[str]:
    clauses: List[str] = []
    source = re.sub(r"\s+", " ", (prompt or "").strip())
    if not source:
        return clauses
    for raw in re.split(r"[.?!;]+", source):
        clean = re.sub(r"\s+", " ", raw).strip(" -\t\r\n")
        if clean and clean not in clauses:
            clauses.append(clean)
            if len(clauses) >= limit:
                break
    return clauses


def build_axiom_processing_frame(
    prompt: str,
    request_profile: Dict[str, Any] | None = None,
) -> Dict[str, List[str]]:
    request_profile = request_profile or build_request_profile(prompt)
    normalized = normalize_prompt_text(prompt)
    ask_set = _extract_prompt_clauses(prompt, limit=4)
    if not ask_set and str(prompt or "").strip():
        ask_set = [str(prompt).strip()]

    program_set: List[str] = []
    if request_profile.get("needs_coding"):
        program_set.append("Produce runnable code instead of only describing the solution.")
    if "python" in normalized:
        program_set.append("Primary implementation lane: Python.")
    if "javascript" in normalized or "node" in normalized:
        program_set.append("Primary implementation lane: JavaScript.")
    if request_profile.get("use_d8_compression") or any(token in normalized for token in ("android", "apk", "d8", "dex")):
        program_set.append("Android/D8 lane: produce Flat Java, explicit manifest/build steps, and DEX/APK-oriented verification.")
    if "web interface" in normalized or "gui web" in normalized:
        program_set.append("Expose the result through a web-facing interface.")
    if request_profile.get("needs_verification") or request_profile.get("must_make_code_run"):
        program_set.append("Keep a verification path close to the implementation.")
    if request_profile.get("prefer_single_workspace"):
        program_set.append("Use one stable workspace instead of scattered scratch files.")
    if not program_set:
        program_set.append("Reduce the request into concrete implementation blocks before acting.")

    axioms = [
        "The smallest runnable solution that satisfies the ask wins.",
        "Explicit constraints outrank stale assumptions.",
        "Verification results outrank speculation during iteration.",
    ]
    if request_profile.get("use_logic_block_table"):
        axioms.append("Split work into logic blocks with clear ownership and boundaries.")
    if request_profile.get("prefer_code_compression"):
        axioms.append("Prefer compact, flattened, compiler-friendly code paths over ornamental indirection.")
    if request_profile.get("use_d8_compression"):
        axioms.append("D8 compatibility outranks decorative Java patterns.")
    if request_profile.get("use_targeted_web_synthesis"):
        axioms.append("Carry forward only exact implementation facts from research that materially change the build.")

    constraints = [
        "Stay tied to the current user objective.",
        "Use tools only when they reduce uncertainty or execute the task.",
    ]
    if request_profile.get("prefer_single_workspace"):
        constraints.append("Stay anchored to one relevant workspace or test lane.")
    if request_profile.get("needs_automation"):
        constraints.append("Keep the workflow advancing in phases until the stated done condition is reached.")
    if request_profile.get("use_d8_compression"):
        constraints.append("No anonymous inner classes, lambdas, hidden Runnables, or dependency-heavy Android glue unless explicitly required.")

    completion_tests = []
    if request_profile.get("needs_coding"):
        completion_tests.append("The answer includes a concrete implementation path or code output.")
    if request_profile.get("must_make_code_run"):
        completion_tests.append("The code runs, or the exact blocker and latest verification result are stated plainly.")
    elif request_profile.get("needs_verification"):
        completion_tests.append("The result includes an explicit verification step or status.")
    if request_profile.get("needs_research"):
        completion_tests.append("Claims are grounded in current evidence or project memory.")
    if request_profile.get("use_d8_compression"):
        completion_tests.append("D8/Flat-Java constraints are reflected in the code structure and build notes.")
    if not completion_tests:
        completion_tests.append("The response stays tied to the explicit end goal.")

    return {
        "ask_set": ask_set[:4],
        "program_set": program_set[:5],
        "axioms": axioms[:6],
        "constraints": constraints[:5],
        "completion_tests": completion_tests[:5],
    }


def format_axiom_processing_brief(
    prompt: str,
    request_profile: Dict[str, Any] | None = None,
) -> str:
    frame = build_axiom_processing_frame(prompt, request_profile=request_profile)
    lines = ["Axiom processing frame:"]
    for key in ("ask_set", "program_set", "axioms", "constraints", "completion_tests"):
        label = key.replace("_", " ").title()
        lines.append(f"{label}:")
        for item in frame.get(key, []):
            lines.append(f"- {item}")
    return "\n".join(lines)


def get_tools_prompt() -> str:
    """Generate prompt describing available tools."""
    lines = ["Available tools:"]
    for name, info in TOOLS.items():
        params = ", ".join(info["parameters"].keys())
        suffix = f" ({params})" if params else ""
        lines.append(f"- {name}{suffix}: {info['description']}")
    lines.extend(
        [
            "",
            "Emit JSON only for tool calls.",
            '{"tool":"tool_name","parameters":{"key":"value"}}',
            'For safe independent checks, you may batch: {"tool_calls":[...]}',
        ]
    )
    return "\n".join(lines)


def parse_tool_call(response: str) -> Dict[str, Any] | None:
    """Parse a tool call from model output."""
    def find_first_json_object(text: str) -> str:
        start = text.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escape = False
            for index in range(start, len(text)):
                char = text[index]
                if in_string:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:index + 1]
            start = text.find("{", start + 1)
        return ""

    try:
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()

        return json.loads(json_str)
    except Exception:
        try:
            json_str = find_first_json_object(response or "")
            if json_str:
                return json.loads(json_str)
        except Exception:
            pass
    return None


def parse_tool_calls(response: str) -> List[Dict[str, Any]]:
    parsed = parse_tool_call(response)
    if not isinstance(parsed, dict):
        return []

    if isinstance(parsed.get("tool_calls"), list):
        return [
            item for item in parsed["tool_calls"]
            if isinstance(item, dict) and str(item.get("tool", "")).strip()
        ]

    if str(parsed.get("tool", "")).strip():
        return [parsed]

    return []


def should_execute_tool_call(
    prompt: str,
    tool_call: Dict[str, Any] | None,
    request_profile: Dict[str, Any] | None = None,
) -> bool:
    """Heuristic guardrail so the model only uses tools for explicit tool tasks."""
    if not tool_call:
        return False

    tool_name = (tool_call.get("tool") or "").strip()
    request_profile = request_profile or build_request_profile(prompt)
    prompt_lower = request_profile.get("normalized_prompt") or normalize_prompt_text(prompt)
    parameters = tool_call.get("parameters", {}) or {}

    explicit_signals = {
        "create_directory": ["create folder", "create directory", "make folder", "make directory", "new folder", "new directory"],
        "create_file": ["create file", "write file", "save file", "make file"],
        "read_file": ["read file", "open file", "show file", "display file", "print file"],
        "list_directory": [
            "list directory",
            "list folder",
            "list files",
            "show folder",
            "show directory",
            "what files are in",
            "contents of folder",
            "contents of directory",
        ],
        "execute_command": ["run command", "execute command", "run this command", "terminal", "powershell", "cmd"],
        "search_web": ["search web", "search the web", "look up", "google", "search online", "latest", "current"],
        "crawl_url": ["crawl", "scrape", "fetch url", "open url", "index url", "visit website"],
        "search_project_memory": ["search memory", "project memory", "remember", "recall", "what do you remember"],
        "search_script_registry": ["script registry", "weighted scripts", "script database", "find script", "search scripts"],
        "run_system_heartbeat": [
            "heartbeat",
            "sluggish",
            "slow",
            "unsluggish",
            "cleanup",
            "garbage",
            "temp files",
            "temp folder",
            "extra instances",
            "system health",
            "operating environment",
            "performance",
        ],
        "delegate_picoclaw": [
            "picoclaw",
            "tiny agent",
            "micro agent",
            "italic",
            "italics",
            "small local model",
            "delegate coding",
        ],
        "browser_use_task": [
            "browser use",
            "browser-use",
            "browser automation",
            "web ui",
            "navigate website",
            "click on website",
            "open page and click",
        ],
    }

    matched_signal = any(
        prompt_matches_signal(prompt_lower, signal)
        for signal in explicit_signals.get(tool_name, [])
    )
    profile_allowed = False
    if tool_name == "search_web":
        profile_allowed = bool(
            request_profile.get("needs_research")
            or request_profile.get("use_targeted_web_synthesis")
            or request_profile.get("needs_code_execution_loop")
        )
    elif tool_name == "search_project_memory":
        profile_allowed = bool(
            request_profile.get("needs_coding")
            or request_profile.get("needs_automation")
            or request_profile.get("is_multi_step")
        )
    elif tool_name == "search_script_registry":
        profile_allowed = bool(
            request_profile.get("needs_coding")
            or request_profile.get("needs_automation")
            or request_profile.get("needs_verification")
        )
    elif tool_name in {"read_file", "list_directory"}:
        profile_allowed = bool(
            request_profile.get("needs_coding")
            or request_profile.get("needs_filesystem")
            or request_profile.get("is_multi_step")
        )
    elif tool_name == "execute_command":
        profile_allowed = bool(request_profile.get("allow_operational_commands"))
    elif tool_name == "run_system_heartbeat":
        profile_allowed = bool(request_profile.get("needs_system_diagnosis"))
    elif tool_name == "delegate_picoclaw":
        profile_allowed = bool(
            request_profile.get("needs_coding")
            or request_profile.get("needs_verification")
            or request_profile.get("needs_automation")
        )
    elif tool_name == "browser_use_task":
        profile_allowed = bool(
            request_profile.get("needs_browser_automation")
            or request_profile.get("needs_automation")
            or request_profile.get("needs_research")
        )

    if not (matched_signal or profile_allowed):
        return False

    if tool_name in {"create_directory", "create_file", "read_file", "list_directory"}:
        path = str(parameters.get("path", "")).strip()
        if not path:
            return False
        if path.startswith("/") and not path.startswith("//"):
            return False

    if tool_name == "crawl_url":
        url = str(parameters.get("url", "")).strip().lower()
        if not url.startswith(("http://", "https://")):
            return False

    if tool_name == "search_project_memory":
        return bool(str(parameters.get("query", "")).strip() and str(parameters.get("project", "")).strip())

    if tool_name == "search_script_registry":
        return bool(str(parameters.get("query", "")).strip())

    if tool_name == "execute_command":
        return bool(str(parameters.get("command", "")).strip())

    return True


def should_execute_tool_calls(
    prompt: str,
    tool_calls: List[Dict[str, Any]],
    request_profile: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    request_profile = request_profile or build_request_profile(prompt)
    approved = []
    for tool_call in tool_calls[:4]:
        if should_execute_tool_call(prompt, tool_call, request_profile=request_profile):
            approved.append(tool_call)
    return approved


def execute_tool(tool_call: Dict[str, Any]) -> str:
    """Execute a tool call through the shared registry."""
    return execute_tool_result(tool_call).render()


def execute_tool_result(tool_call: Dict[str, Any]) -> ToolResult:
    """Execute a tool call and return the structured result."""
    tool_name = tool_call.get("tool")
    parameters = tool_call.get("parameters", {})
    return tool_registry.execute_result(tool_name, parameters)


def execute_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    calls = [call for call in tool_calls if str(call.get("tool", "")).strip()]
    if not calls:
        return []

    results: List[Dict[str, Any]] = []
    can_parallelize = len(calls) > 1 and all(
        str(call.get("tool", "")).strip() in PARALLEL_SAFE_TOOLS
        for call in calls
    )

    if can_parallelize:
        with ThreadPoolExecutor(max_workers=min(4, len(calls))) as executor:
            future_map = {
                executor.submit(execute_tool_result, call): call
                for call in calls
            }
            for future in as_completed(future_map):
                call = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = ToolResult(False, str(exc), {"tool": call.get("tool")})
                results.append(
                    {
                        "tool_call": call,
                        "result": result,
                        "rendered": result.render(),
                    }
                )
        order = {
            id(call): index
            for index, call in enumerate(calls)
        }
        results.sort(key=lambda item: order.get(id(item["tool_call"]), 0))
        return results

    for call in calls:
        result = execute_tool_result(call)
        results.append(
            {
                "tool_call": call,
                "result": result,
                "rendered": result.render(),
            }
        )
    return results


def create_system_prompt(request_profile: Dict[str, Any] | None = None) -> str:
    """Create system prompt with tool instructions."""
    request_profile = request_profile or {}
    deliberate_block = ""
    response_contract = build_response_contract(request_profile)
    if request_profile.get("requires_deliberate_mode"):
        deliberate_block = """

Deliberate mode:
- Keep the goal explicit.
- Inspect before acting.
- Use the smallest safe tool set.
"""

    return f"""You are AEGIS, a coding and systems agent with tools.

Default:
- Interpret first.
- Be direct, natural, and practical.
- Talking about code, AI behavior, reasoning, architecture, or possible improvements is conversation unless the user explicitly asks to run, edit, create files, start jobs, or approve PicoClaw.
- Prefer implementation, debugging, testing, and concrete next steps only for explicit action requests.
- Use discovered or provided paths only.
- Prefer current facts over stale summaries.
- Do not introduce yourself as AEGIS or emit canned readiness/status lines unless the user explicitly asks who you are.
- For explicit machine-health actions, start with run_system_heartbeat.
- For explicit small code or verification actions, prefer delegate_picoclaw.
- Keep PicoClaw handoff intent internal unless visible intent markers are explicitly enabled.
{deliberate_block}
{response_contract}

{get_tools_prompt()}
"""


def apply_code_intent_italics(reply: str, prompt: str) -> str:
    cleaned = (reply or "").strip()
    if not cleaned:
        return cleaned
    if os.getenv("AEGIS_INTENT_MARKERS_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return cleaned

    profile = build_request_profile(prompt)
    if not (
        profile.get("needs_coding")
        or profile.get("needs_verification")
        or profile.get("needs_automation")
    ):
        return cleaned

    first_line = cleaned.splitlines()[0].strip() if cleaned.splitlines() else ""
    if first_line.startswith("*") and first_line.endswith("*") and len(first_line) > 2:
        return cleaned

    marker = "*Intent: create or modify working code, run the relevant checks, and keep the result executable.*"
    return f"{marker}\n\n{cleaned}"
