from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List


KERNEL_DIR_NAME = "coding_kernels"


LANGUAGE_PROFILES: Dict[str, Dict[str, Any]] = {
    "python": {
        "aliases": ["python", "py", "pytest", "unittest", "pip", "venv"],
        "extensions": [".py"],
        "default_files": ["app.py", "tests/test_app.py", "README.md"],
        "research_terms": "python implementation testing best practices",
        "language_label": "Python",
        "verification_commands": [
            ["{python_exe}", "-m", "pytest", "-q"],
            ["{python_exe}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        ],
        "verification_label": "pytest+unittest",
        "test_strategy": "Run pytest first, then fallback to unittest discovery.",
    },
    "javascript": {
        "aliases": ["javascript", "node", "nodejs", "npm", "js", "ecmascript"],
        "extensions": [".js", ".mjs", ".cjs"],
        "default_files": ["src/index.js", "tests/index.test.js", "README.md"],
        "research_terms": "javascript node implementation testing best practices",
        "language_label": "JavaScript",
        "verification_commands": [
            ["node", "--test"],
            ["node", "src/index.js"],
        ],
        "verification_label": "node",
        "test_strategy": "Prefer node --test and keep the runtime dependency-free unless the task requires packages.",
    },
    "typescript": {
        "aliases": ["typescript", "ts", "tsx", "tsconfig"],
        "extensions": [".ts", ".tsx"],
        "default_files": ["src/index.ts", "tests/index.test.ts", "tsconfig.json", "README.md"],
        "research_terms": "typescript implementation testing best practices",
        "language_label": "TypeScript",
        "verification_commands": [
            ["tsc", "--noEmit"],
            ["node", "--test"],
        ],
        "verification_label": "tsc+node",
        "test_strategy": "Prefer a type-check pass first, then run node-based tests only if the workspace supports them.",
    },
    "powershell": {
        "aliases": ["powershell", "pwsh", "ps1", "windows shell"],
        "extensions": [".ps1", ".psm1"],
        "default_files": ["main.ps1", "tests/main.Tests.ps1", "README.md"],
        "research_terms": "powershell script implementation testing best practices",
        "language_label": "PowerShell",
        "verification_commands": [
            ["pwsh", "-NoProfile", "-Command", "[void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'main.ps1'),[ref]$null,[ref]$null)"],
            ["pwsh", "-NoProfile", "-File", "main.ps1"],
        ],
        "verification_label": "pwsh",
        "test_strategy": "Syntax-parse the script first, then execute the main entry script if it exists.",
    },
    "bash": {
        "aliases": ["bash", "shell script", "sh", "zsh", "posix shell"],
        "extensions": [".sh"],
        "default_files": ["main.sh", "tests/test_main.sh", "README.md"],
        "research_terms": "bash shell script implementation testing best practices",
        "language_label": "Bash",
        "verification_commands": [
            ["bash", "-n", "main.sh"],
            ["bash", "main.sh"],
        ],
        "verification_label": "bash",
        "test_strategy": "Run a syntax check first, then execute the script only if it is safe and self-contained.",
    },
    "sql": {
        "aliases": ["sql", "sqlite", "postgres", "postgresql", "mysql", "query"],
        "extensions": [".sql"],
        "default_files": ["queries.sql", "README.md"],
        "research_terms": "sql query design best practices",
        "language_label": "SQL",
        "verification_commands": [],
        "verification_label": "static-review",
        "test_strategy": "Prefer concrete schemas, example inputs, and expected result sets when execution is not available.",
    },
    "html_css": {
        "aliases": ["html", "css", "frontend", "web page", "landing page", "website"],
        "extensions": [".html", ".css"],
        "default_files": ["index.html", "styles.css", "README.md"],
        "research_terms": "html css implementation accessibility best practices",
        "language_label": "HTML/CSS",
        "verification_commands": [],
        "verification_label": "static-review",
        "test_strategy": "Prefer valid structure, accessibility, responsive layout, and clear file boundaries.",
    },
    "json_yaml_regex": {
        "aliases": ["json", "yaml", "yml", "regex", "regular expression"],
        "extensions": [".json", ".yaml", ".yml"],
        "default_files": ["config.json", "README.md"],
        "research_terms": "json yaml regex design validation best practices",
        "language_label": "JSON/YAML/Regex",
        "verification_commands": [],
        "verification_label": "static-review",
        "test_strategy": "Prefer examples, schema shape, and explicit valid/invalid cases.",
    },
    "rust": {
        "aliases": ["rust", "cargo", "crate", "rs"],
        "extensions": [".rs"],
        "default_files": ["src/main.rs", "tests/smoke.rs", "Cargo.toml", "README.md"],
        "research_terms": "rust implementation testing best practices",
        "language_label": "Rust",
        "verification_commands": [
            ["cargo", "test", "--quiet"],
            ["cargo", "run", "--quiet"],
        ],
        "verification_label": "cargo",
        "test_strategy": "Prefer cargo test and keep ownership/borrowing simple before optimizing.",
    },
    "go": {
        "aliases": ["golang", "go", "go.mod"],
        "extensions": [".go"],
        "default_files": ["main.go", "main_test.go", "go.mod", "README.md"],
        "research_terms": "go implementation testing best practices",
        "language_label": "Go",
        "verification_commands": [
            ["go", "test", "./..."],
            ["go", "run", "."],
        ],
        "verification_label": "go",
        "test_strategy": "Prefer small packages, table-driven tests, and explicit errors.",
    },
    "java_android": {
        "aliases": [
            "android",
            "android java",
            "java",
            "d8",
            "dex",
            "apk",
            "termux",
            "gradle",
            "activity",
            "manifest",
        ],
        "extensions": [".java", ".xml"],
        "default_files": ["src/MainActivity.java", "AndroidManifest.xml", "build_d8.ps1", "README.md"],
        "research_terms": "android java d8 dex apk flat java termux implementation compatibility",
        "language_label": "Android Java / D8",
        "verification_commands": [
            ["d8", "--version"],
            ["javac", "-version"],
        ],
        "verification_label": "d8+javac",
        "test_strategy": "Prefer Flat Java static structure first; run D8 or javac checks only when local Android/D8 tools exist.",
        "compression_guidance": "D8 compression: use Flat Java with explicit named classes, direct handlers, minimal dependencies, and no anonymous inner classes, lambdas, hidden Runnables, reflection-heavy glue, or ornamental wrappers.",
    },
}


DEFAULT_LANGUAGE = "python"
AUXILIARY_LANGUAGES = {"json_yaml_regex"}


def coding_kernels_dir(base_dir: Path) -> Path:
    return Path(base_dir) / KERNEL_DIR_NAME


def normalize_language_name(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return DEFAULT_LANGUAGE
    if text in LANGUAGE_PROFILES:
        return text
    for language, profile in LANGUAGE_PROFILES.items():
        aliases = profile.get("aliases") or []
        if text == language or text in aliases:
            return language
    if text in {"ps", "psm1"}:
        return "powershell"
    if text in {"js", "mjs", "cjs"}:
        return "javascript"
    if text in {"ts", "tsx"}:
        return "typescript"
    return DEFAULT_LANGUAGE


def get_language_profile(language: str) -> Dict[str, Any]:
    key = normalize_language_name(language)
    profile = dict(LANGUAGE_PROFILES.get(key) or LANGUAGE_PROFILES[DEFAULT_LANGUAGE])
    profile["language"] = key
    return profile


def _count_hits(text: str, patterns: List[str]) -> int:
    score = 0
    for pattern in patterns:
        if not pattern:
            continue
        if pattern.startswith("."):
            score += text.count(pattern)
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(pattern)}(?![a-z0-9_])", text):
            score += 2
    return score


def detect_languages(prompt: str, *, project: str = "", context_text: str = "", limit: int = 2) -> List[str]:
    source = " ".join(part for part in [prompt or "", project or "", context_text or ""] if part).lower()
    if not source.strip():
        return [DEFAULT_LANGUAGE]

    scored: List[tuple[int, str]] = []
    for language, profile in LANGUAGE_PROFILES.items():
        score = 0
        score += _count_hits(source, profile.get("aliases") or [])
        score += _count_hits(source, profile.get("extensions") or [])
        if language == DEFAULT_LANGUAGE and score == 0 and re.search(r"\b(code|script|program|tool|function|class|cli|api)\b", source):
            score = 1
        if score > 0:
            scored.append((score, language))

    if not scored:
        return [DEFAULT_LANGUAGE]

    ranked = [language for _, language in sorted(scored, key=lambda item: (-item[0], item[1]))]
    deduped: List[str] = []
    for language in ranked:
        if language not in deduped:
            deduped.append(language)
    if deduped and deduped[0] in AUXILIARY_LANGUAGES:
        for index, language in enumerate(deduped[1:], start=1):
            if language not in AUXILIARY_LANGUAGES:
                deduped[0], deduped[index] = deduped[index], deduped[0]
                break
    return deduped[: max(1, limit)] or [DEFAULT_LANGUAGE]


def infer_primary_language(prompt: str, *, project: str = "", context_text: str = "") -> str:
    return detect_languages(prompt, project=project, context_text=context_text, limit=1)[0]


def kernel_file_path(base_dir: Path, language: str) -> Path:
    return coding_kernels_dir(base_dir) / f"{normalize_language_name(language)}.txt"


def common_kernel_path(base_dir: Path) -> Path:
    return coding_kernels_dir(base_dir) / "common.txt"


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_common_kernel(base_dir: Path) -> str:
    return _read_text_if_exists(common_kernel_path(base_dir))


def load_language_kernel(base_dir: Path, language: str) -> str:
    return _read_text_if_exists(kernel_file_path(base_dir, language))


def extract_task_hints(prompt: str) -> List[str]:
    normalized = (prompt or "").lower()
    hints: List[str] = []
    if re.search(r"\bjson\b", normalized):
        hints.append("Requested output format: JSON from the primary language. Do not replace code with raw JSON or prose.")
    if re.search(r"\byaml\b|\byml\b", normalized):
        hints.append("Requested output format: YAML from the primary language when configuration is part of the deliverable.")
    if re.search(r"\bcsv\b", normalized):
        hints.append("Requested output format: CSV-compatible emission or parsing if the task calls for it.")
    if re.search(r"\bcli\b|\bcommand line\b|\bscript\b", normalized):
        hints.append("Requested interface: script or CLI entrypoint.")
    if re.search(r"\bapi\b|\bendpoint\b|\bserver\b", normalized):
        hints.append("Requested interface: API or service boundary. Keep handlers separate from core logic.")
    if re.search(r"\btest\b|\bverify\b|\bsmoke\b", normalized):
        hints.append("Verification is part of the deliverable. Include runnable checks, not just implementation.")
    if re.search(r"\bd8\b|\bdex\b|\bapk\b|\bandroid\b|\btermux\b|flat java|anonymous inner classes|hidden runnables", normalized):
        hints.append(
            "D8 compression mode: use Flat Java with explicit named classes, direct handlers, minimal dependencies, and no anonymous inner classes, lambdas, hidden Runnables, or ornamental wrappers."
        )
    return hints


def build_coding_kernel_brief(
    base_dir: Path,
    prompt: str,
    *,
    project: str = "",
    context_text: str = "",
    max_languages: int = 2,
    max_chars: int = 1200,
) -> str:
    languages = detect_languages(prompt, project=project, context_text=context_text, limit=max_languages)
    primary_profile = get_language_profile(languages[0])
    blocks: List[str] = ["CODING KERNEL", f"Primary language: {primary_profile['language']}"]
    secondary = [language for language in languages[1:] if language != primary_profile["language"]]
    if secondary:
        blocks.append(f"Secondary languages: {', '.join(secondary)}")

    common_text = load_common_kernel(base_dir)
    if common_text:
        blocks.extend(["Common:", common_text])
    task_hints = extract_task_hints(prompt)
    if task_hints:
        blocks.append("Task hints:")
        blocks.extend(f"- {hint}" for hint in task_hints)

    for language in languages:
        profile = get_language_profile(language)
        kernel_text = load_language_kernel(base_dir, language)
        if not kernel_text:
            continue
        blocks.extend(
            [
                f"{profile['language_label']}:",
                kernel_text,
                f"Default files: {', '.join(profile.get('default_files') or [])}",
                f"Verify: {profile.get('test_strategy')}",
            ]
        )

    combined = "\n".join(blocks).strip()
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars].rstrip() + "\n...[trimmed]"


def build_language_runtime_profile(
    base_dir: Path,
    prompt: str,
    *,
    project: str = "",
    context_text: str = "",
) -> Dict[str, Any]:
    language = infer_primary_language(prompt, project=project, context_text=context_text)
    profile = get_language_profile(language)
    common_text = load_common_kernel(base_dir)
    language_text = load_language_kernel(base_dir, language)
    task_hints = extract_task_hints(prompt)
    profile["common_kernel_text"] = common_text
    profile["language_kernel_text"] = language_text
    profile["task_hints"] = task_hints
    profile["kernel_text"] = "\n\n".join(part for part in [common_text, language_text] if part).strip()
    return profile
