"""
Helpers for optional project-scoped runtime lenses.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Optional


DEFAULT_GLOBAL_DIRECTIVE = """PROJECT DIRECTIVE

- Build first.
- Prefer direct, practical coding or system action.
- Use tools when they help; ask only when a destructive action or a real missing detail blocks progress.
"""

DEFAULT_GUARDIAN_DIRECTIVE = """GUARDIAN DIRECTIVE

- Fallback only.
- Do not add extra steering beyond PROJECT_DIRECTIVE.txt.
- Keep the runtime local, simple, and stable.
"""

PROJECT_LENSES_README = """# Project Lenses

Optional per-project lens files live here.

How it works:
- Use `PROJECT_DIRECTIVE.txt` for the default global build-first behavior.
- Use `<project>.txt` here only when one project needs a special lens.
- Normal chat turns do not inject the global directive by default anymore.
- Project-specific lenses are loaded for that project when present.
- Automation and background build loops may still include the global directive.
"""


def normalize_project_name(project: Optional[str]) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", (project or "").strip())
    value = value.strip("-")
    return value or "general"


def project_lenses_dir(base_dir: Path) -> Path:
    return base_dir / "project_lenses"


def ensure_project_lenses_dir(base_dir: Path) -> Path:
    directory = project_lenses_dir(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    readme_path = directory / "README.md"
    if not readme_path.exists():
        readme_path.write_text(PROJECT_LENSES_README + "\n", encoding="utf-8")
    return directory


def project_lens_path(base_dir: Path, project: Optional[str]) -> Optional[Path]:
    normalized = normalize_project_name(project)
    if normalized == "general":
        return None
    return project_lenses_dir(base_dir) / f"{normalized}.txt"


def directive_target_path(base_dir: Path, project: Optional[str]) -> Path:
    lens_path = project_lens_path(base_dir, project)
    if lens_path is not None:
        ensure_project_lenses_dir(base_dir)
        return lens_path
    return base_dir / "PROJECT_DIRECTIVE.txt"


def read_text_if_exists(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return ""


def load_global_directive(base_dir: Path) -> str:
    return read_text_if_exists(base_dir / "PROJECT_DIRECTIVE.txt") or DEFAULT_GLOBAL_DIRECTIVE.strip()


def load_guardian_directive(base_dir: Path) -> str:
    return read_text_if_exists(base_dir / "guardian_directive.txt") or DEFAULT_GUARDIAN_DIRECTIVE.strip()


def load_project_lens(base_dir: Path, project: Optional[str]) -> str:
    return read_text_if_exists(project_lens_path(base_dir, project))


def load_runtime_directive(
    base_dir: Path,
    *,
    project: Optional[str] = None,
    include_global: bool = False,
    include_guardian_fallback: bool = False,
) -> str:
    blocks = []

    project_text = load_project_lens(base_dir, project)
    if project_text:
        blocks.append(project_text)

    if include_global:
        global_text = load_global_directive(base_dir)
        if global_text:
            blocks.append(global_text)

    if not blocks and include_guardian_fallback:
        guardian_text = load_guardian_directive(base_dir)
        if guardian_text:
            blocks.append(guardian_text)

    return "\n\n".join(blocks).strip()


def merge_directive_text(existing_text: str, new_text: str) -> str:
    merged = (existing_text or "").strip()
    clean_new = re.sub(r"\s+", " ", (new_text or "")).strip()
    if not clean_new:
        return merged
    if not merged:
        return clean_new
    if clean_new in merged:
        return merged
    if clean_new.startswith("- "):
        return (merged + "\n" + clean_new).strip()
    return (merged + "\n- " + clean_new).strip()
