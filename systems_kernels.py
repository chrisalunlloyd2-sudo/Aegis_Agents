from __future__ import annotations

from pathlib import Path
import re
from typing import Dict, List


SYSTEMS_KERNEL_DIR_NAME = "systems_kernels"


SYSTEM_PROFILES: Dict[str, Dict[str, List[str] | str]] = {
    "windows_processes": {
        "aliases": ["windows", "process", "processes", "ram", "cpu", "service", "services", "powershell", "task"],
        "label": "Windows Processes",
    },
    "networking": {
        "aliases": ["network", "networking", "socket", "tcp", "udp", "http", "api", "port", "ssl", "tls"],
        "label": "Networking",
    },
    "email_pop3_smtp": {
        "aliases": ["email", "mail", "mailbox", "inbox", "pop3", "smtp", "imap"],
        "label": "Email POP3/SMTP",
    },
    "browser_automation": {
        "aliases": ["browser", "browser-use", "web ui", "click", "navigate", "form", "website"],
        "label": "Browser Automation",
    },
    "android_d8": {
        "aliases": ["android", "apk", "d8", "dex", "termux", "manifest", "activity"],
        "label": "Android / D8",
    },
    "filesystem": {
        "aliases": ["file", "folder", "directory", "path", "workspace", "save", "read", "write"],
        "label": "Filesystem",
    },
    "testing_verification": {
        "aliases": ["test", "tests", "verify", "verification", "smoke", "pytest", "unittest", "assert"],
        "label": "Testing / Verification",
    },
    "security_credentials": {
        "aliases": ["password", "secret", "credential", "token", "api key", "login", "auth", "oauth"],
        "label": "Security / Credentials",
    },
}


DEFAULT_SYSTEMS = ["filesystem", "testing_verification", "security_credentials"]


def systems_kernels_dir(base_dir: Path) -> Path:
    return Path(base_dir) / SYSTEMS_KERNEL_DIR_NAME


def systems_kernel_path(base_dir: Path, domain: str) -> Path:
    return systems_kernels_dir(base_dir) / f"{domain}.txt"


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _count_hits(text: str, aliases: List[str]) -> int:
    score = 0
    for alias in aliases:
        if not alias:
            continue
        if " " in alias:
            if alias in text:
                score += 3
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])", text):
            score += 2
    return score


def detect_system_domains(prompt: str, *, project: str = "", context_text: str = "", limit: int = 4) -> List[str]:
    source = " ".join(part for part in [prompt or "", project or "", context_text or ""] if part).lower()
    scored: List[tuple[int, str]] = []
    for domain, profile in SYSTEM_PROFILES.items():
        aliases = list(profile.get("aliases") or [])
        score = _count_hits(source, aliases)
        if score > 0:
            scored.append((score, domain))

    ranked = [domain for _, domain in sorted(scored, key=lambda item: (-item[0], item[1]))]
    for domain in DEFAULT_SYSTEMS:
        if domain not in ranked:
            ranked.append(domain)
    return ranked[: max(1, limit)]


def build_systems_kernel_brief(
    base_dir: Path,
    prompt: str,
    *,
    project: str = "",
    context_text: str = "",
    max_domains: int = 4,
    max_chars: int = 1400,
) -> str:
    domains = detect_system_domains(prompt, project=project, context_text=context_text, limit=max_domains)
    blocks: List[str] = ["SYSTEMS KERNEL", f"Domains: {', '.join(domains)}"]
    for domain in domains:
        profile = SYSTEM_PROFILES.get(domain) or {}
        kernel_text = _read_text_if_exists(systems_kernel_path(base_dir, domain))
        if not kernel_text:
            continue
        blocks.extend([f"{profile.get('label', domain)}:", kernel_text])

    combined = "\n".join(blocks).strip()
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars].rstrip() + "\n...[trimmed]"
