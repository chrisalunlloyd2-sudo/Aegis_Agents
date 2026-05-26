from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aegis_toolkit import score_source_credibility
from agentic_loop_controller import SubTask


CODE_SUFFIX_HINTS = {
    "python": [".py"],
    "javascript": [".js", ".ts"],
    "typescript": [".ts", ".tsx"],
    "java": [".java"],
    "android": [".java", ".kt", ".xml"],
    "powershell": [".ps1"],
    "web": [".html", ".css", ".js"],
}


def _clamp(value: float, low: float = 0.05, high: float = 0.95) -> float:
    return max(low, min(high, value))


def _text_has_tests(text: str) -> bool:
    return bool(re.search(r"\b(tests?|pytest|unittest|node:test|assert|self[- ]?tests?|verification|pass/fail)\b", text or "", re.I))


def _text_has_deploy(text: str) -> bool:
    return bool(re.search(r"\b(deploy|deployment|docker|uvicorn|flask|fastapi|build|install|requirements|package.json|manifest|apk|d8)\b", text or "", re.I))


def _text_has_placeholder_risk(text: str) -> bool:
    return bool(re.search(r"\b(todo|placeholder|pseudo-code|pseudocode|example only|not implemented|mock only|stub)\b", text or "", re.I))


def predict_execution_likelihood(payload: Dict[str, Any]) -> Dict[str, Any]:
    prompt = str(payload.get("prompt") or payload.get("objective") or "")
    code = str(payload.get("code") or payload.get("reply") or "")
    language = str(payload.get("language") or "").lower()
    code_lines = int(payload.get("code_lines") or 0)
    research_hits = int(payload.get("research_hits") or 0)
    prior_pass_rate = payload.get("prior_pass_rate")
    try:
        prior = float(prior_pass_rate)
    except Exception:
        prior = 0.5

    combined = f"{prompt}\n{code}"
    score = 0.34
    factors: List[Dict[str, Any]] = []

    def add(name: str, delta: float, note: str) -> None:
        nonlocal score
        score += delta
        factors.append({"name": name, "delta": round(delta, 3), "note": note})

    if code_lines >= 20:
        add("working_code_volume", 0.10, "Enough generated code to be more than a stub.")
    elif code_lines >= 5:
        add("small_code_volume", 0.04, "Some runnable-looking code exists, but it is still small.")
    else:
        add("low_code_volume", -0.12, "Little or no code is visible before execution.")

    if _text_has_tests(combined):
        add("verification_present", 0.16, "The prompt or output includes explicit tests/assertions.")
    else:
        add("verification_missing", -0.10, "No obvious test harness or pass/fail check was found.")

    if _text_has_deploy(combined):
        add("deployment_context", 0.08, "Deployment/build terms are present.")
    else:
        add("deployment_context_missing", -0.03, "No deployment/build path is visible yet.")

    if research_hits >= 5:
        add("research_grounding", 0.08, "Several research hits support the build.")
    elif research_hits > 0:
        add("some_research_grounding", 0.03, "Some research support exists.")

    if _text_has_placeholder_risk(combined):
        add("placeholder_risk", -0.18, "Placeholder or pseudo-code language was detected.")

    if re.search(r"\b(program that creates|generate.*program|code generator|scaffold.*project)\b", combined, re.I):
        add("programs_make_programs", 0.06, "The task is explicitly structured as a program-maker.")

    if "d8" in combined.lower() or "flat java" in combined.lower():
        add("d8_compression", 0.05, "D8/Flat Java compression rules are present.")

    if language in CODE_SUFFIX_HINTS:
        add("known_language_lane", 0.04, f"Known language lane: {language}.")

    add("prior_pass_rate", (prior - 0.5) * 0.18, "Recent observed pass rate nudges the estimate.")

    probability = _clamp(score)
    label = "high" if probability >= 0.72 else "medium" if probability >= 0.48 else "low"
    required_checks = [
        "syntax check",
        "unit/self-test command",
        "runtime smoke test",
    ]
    if _text_has_deploy(combined):
        required_checks.append("deployment start/health probe")
    if "program" in combined.lower() and "creates" in combined.lower():
        required_checks.append("generated-program execution check")

    return {
        "probability": round(probability, 3),
        "percent": round(probability * 100, 1),
        "label": label,
        "should_execute": probability >= 0.55,
        "factors": factors,
        "required_checks": required_checks,
        "summary": f"{label.upper()} run confidence: {probability * 100:.1f}%. Required checks: {', '.join(required_checks)}.",
    }


def decompose_long_research_task(objective: str, *, hours: int = 8, cycles: Optional[int] = None) -> List[str]:
    safe_hours = max(1, min(int(hours or 8), 48))
    cycle_count = max(2, min(int(cycles or safe_hours), 24))
    steps = [
        f"[LONG_RESEARCH_BOOTSTRAP] Prepare 8-hour research plan for {objective}",
    ]
    for index in range(1, cycle_count + 1):
        steps.append(f"[LONG_RESEARCH_CYCLE {index}/{cycle_count}] Crawl, compress, and append findings for {objective}")
    steps.append(f"[LONG_RESEARCH_FINAL] Produce large document, compressed algorithms, and deployment notes for {objective}")
    return steps


def _flatten_crawl_matches(crawl_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for crawl in crawl_payload.get("crawls", []):
        for chunk in crawl.get("stored_chunks", []) or []:
            matches.append({
                "title": crawl.get("title") or crawl.get("url") or "crawled page",
                "url": crawl.get("url") or chunk.get("url") or "",
                "domain": crawl.get("domain") or chunk.get("domain") or "",
                "content": chunk.get("content") or chunk.get("text") or "",
                "credibility": crawl.get("credibility") or {},
            })
    return matches


def _compress_to_algorithms(matches: List[Dict[str, Any]], objective: str) -> str:
    lines = [
        "# Compressed Algorithms",
        "",
        f"Objective: {objective}",
        "",
        "## Core Loop",
        "1. Convert the ask into constraints, inputs, outputs, verification gates, and deployment target.",
        "2. Retrieve only facts that change implementation choices.",
        "3. Convert facts into small executable rules.",
        "4. Generate code and tests together.",
        "5. Predict run probability before execution; execute only when the required checks are visible.",
        "6. If execution fails, preserve working code, isolate the failing axiom, and retry the smallest patch.",
        "",
        "## Source-Derived Rules",
    ]
    seen = set()
    for item in matches[:80]:
        content = re.sub(r"\s+", " ", str(item.get("content") or item.get("snippet") or "")).strip()
        if not content:
            continue
        sentence = content.split(". ")[0][:220].strip(" -")
        key = sentence.lower()[:90]
        if not sentence or key in seen:
            continue
        seen.add(key)
        lines.append(f"- IF task context matches `{sentence[:80]}` THEN consider `{item.get('domain') or 'source'}` as a support signal.")
    if len(lines) < 14:
        lines.append("- IF source evidence is thin THEN run another crawl cycle before deploying.")
    return "\n".join(lines).strip() + "\n"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def build_long_research_executor(
    *,
    job_id: str,
    objective: str,
    project: str,
    hours: int,
    cycles: Optional[int],
    max_results: int,
    max_pages: int,
    base_dir: Path,
    crawler_db: Any,
    timescale_memory: Any,
    vector_memory: Any,
    postprocess_callback: Optional[Callable[[str], None]] = None,
) -> Callable[[SubTask], str]:
    safe_hours = max(1, min(int(hours or 8), 48))
    cycle_count = max(2, min(int(cycles or safe_hours), 24))
    cycle_interval = (safe_hours * 3600.0) / cycle_count
    started = datetime.utcnow()
    deadline = started + timedelta(hours=safe_hours)
    run_dir = base_dir / "agentic_jobs" / "long_research" / project / job_id
    run_dir.mkdir(parents=True, exist_ok=True)

    state: Dict[str, Any] = {
        "job_id": job_id,
        "objective": objective,
        "project": project,
        "started_at": started.isoformat(),
        "deadline": deadline.isoformat(),
        "search_results": [],
        "crawled_matches": [],
        "cycle_reports": [],
        "warnings": [],
    }

    def save_state() -> None:
        _write_json(run_dir / "LONG_RESEARCH_STATE.json", state)

    def cycle_query(index: int) -> str:
        variants = [
            "implementation patterns",
            "verification testing deployment",
            "failure modes edge cases",
            "compressed algorithms formulas",
            "reference architecture examples",
            "performance constraints",
        ]
        return f"{objective} {variants[(index - 1) % len(variants)]}"

    def sleep_until_next_cycle(index: int) -> None:
        if index >= cycle_count:
            return
        target = started.timestamp() + cycle_interval * index
        while time.time() < target and datetime.utcnow() < deadline:
            time.sleep(min(300, max(1, target - time.time())))

    def executor(subtask: SubTask) -> str:
        description = subtask.description or ""
        save_state()

        if description.startswith("[LONG_RESEARCH_BOOTSTRAP]"):
            plan = {
                "objective": objective,
                "hours": safe_hours,
                "cycles": cycle_count,
                "cycle_interval_seconds": round(cycle_interval, 2),
                "outputs": [
                    "large_research_document.md",
                    "compressed_algorithms.md",
                    "deployment_blueprint.md",
                    "LONG_RESEARCH_STATE.json",
                ],
                "pre_execution_policy": "predict_execution_likelihood must be checked before every code execution or deployment smoke.",
            }
            _write_json(run_dir / "research_plan.json", plan)
            state["plan"] = plan
            save_state()
            return f"Long research plan written to {run_dir / 'research_plan.json'}"

        if description.startswith("[LONG_RESEARCH_CYCLE"):
            match = re.search(r"(\d+)/(\d+)", description)
            cycle = int(match.group(1)) if match else 1
            query = cycle_query(cycle)
            search_results = crawler_db.search_web(query, max_results=max(1, min(max_results, 12)))
            state["search_results"].extend(search_results)

            crawl_payload = {"crawls": []}
            for result in search_results[: max(1, min(max_results, 8))]:
                url = result.get("url") or ""
                if not url:
                    continue
                try:
                    credibility = score_source_credibility(url, title=result.get("title", ""))
                    crawled = crawler_db.crawl_url(
                        url,
                        max_depth=0,
                        max_pages=max(1, min(max_pages, 24)),
                        metadata={
                            "job_id": job_id,
                            "project": project,
                            "objective": objective,
                            "cycle": cycle,
                            "credibility": credibility,
                        },
                        ttl_hours=24 * 30,
                    )
                    crawled["credibility"] = credibility
                    crawl_payload["crawls"].append(crawled)
                except Exception as exc:
                    state["warnings"].append(f"cycle {cycle} crawl failed for {url}: {exc}")

            matches = _flatten_crawl_matches(crawl_payload)
            state["crawled_matches"].extend(matches)
            algorithm_text = _compress_to_algorithms(state["crawled_matches"], objective)
            cycle_doc = run_dir / f"cycle_{cycle:02d}.md"
            cycle_doc.write_text(
                "\n".join([
                    f"# Long Research Cycle {cycle}/{cycle_count}",
                    "",
                    f"Query: {query}",
                    f"Generated: {datetime.utcnow().isoformat()}",
                    "",
                    "## Search Seeds",
                    *[f"- [{item.get('title') or item.get('url')}]({item.get('url') or ''})" for item in search_results],
                    "",
                    "## Compressed Algorithm Delta",
                    algorithm_text,
                ]).strip() + "\n",
                encoding="utf-8",
            )
            state["cycle_reports"].append(str(cycle_doc))
            (run_dir / "compressed_algorithms.md").write_text(algorithm_text, encoding="utf-8")
            save_state()
            sleep_until_next_cycle(cycle)
            return f"Cycle {cycle}/{cycle_count} crawled {len(search_results)} seed(s), captured {len(matches)} match(es), wrote {cycle_doc}"

        if description.startswith("[LONG_RESEARCH_FINAL]"):
            large_doc = run_dir / "large_research_document.md"
            compressed_doc = run_dir / "compressed_algorithms.md"
            deployment_doc = run_dir / "deployment_blueprint.md"
            matches = state.get("crawled_matches") or []
            search_results = state.get("search_results") or []
            memory_results = timescale_memory.search(objective, time_range="last_week", project=project)
            vector_results = vector_memory.search(objective, project=project, limit=10)
            algorithm_text = _compress_to_algorithms(matches, objective)
            compressed_doc.write_text(algorithm_text, encoding="utf-8")
            deployment_text = "\n".join([
                "# Deployment Blueprint",
                "",
                f"Objective: {objective}",
                "",
                "## Pre-Execution Gate",
                "- Estimate statistical run likelihood before every execution.",
                "- Require syntax check, self-test, smoke run, and deployment health probe.",
                "- If predicted probability is below 55%, generate missing tests or dependencies before running.",
                "",
                "## Full Code Deployment Loop",
                "1. Scaffold files.",
                "2. Install only declared dependencies.",
                "3. Run syntax/static checks.",
                "4. Run tests.",
                "5. Start service or executable.",
                "6. Probe health/output.",
                "7. Store pass/fail and patch the smallest failing axiom.",
            ]).strip() + "\n"
            deployment_doc.write_text(deployment_text, encoding="utf-8")
            large_doc.write_text(
                "\n".join([
                    "# Long-Run Research Document",
                    "",
                    f"Objective: {objective}",
                    f"Project: {project}",
                    f"Job: {job_id}",
                    f"Generated: {datetime.utcnow().isoformat()}",
                    "",
                    "## Search Seeds",
                    *[f"- [{item.get('title') or item.get('url')}]({item.get('url') or ''})" for item in search_results],
                    "",
                    "## Memory Links",
                    *[f"- {str(item)[:260]}" for item in memory_results[:20]],
                    "",
                    "## Vector Links",
                    *[f"- {str(item.get('text') or item.get('content') or item)[:260]}" for item in vector_results[:20]],
                    "",
                    "## Compressed Algorithms",
                    algorithm_text,
                    "",
                    "## Deployment Blueprint",
                    deployment_text,
                    "",
                    "## Cycle Reports",
                    *[f"- {path}" for path in state.get("cycle_reports", [])],
                ]).strip() + "\n",
                encoding="utf-8",
            )
            state["outputs"] = {
                "large_document": str(large_doc),
                "compressed_algorithms": str(compressed_doc),
                "deployment_blueprint": str(deployment_doc),
                "match_count": len(matches),
                "search_seed_count": len(search_results),
            }
            save_state()
            try:
                timescale_memory.store_reasoning_summary(
                    session_id=job_id,
                    project=project,
                    objective=objective,
                    summary=f"Long research completed. Large document: {large_doc}\nCompressed algorithms: {compressed_doc}\nDeployment blueprint: {deployment_doc}",
                    metadata={"job_id": job_id, "kind": "long_research", **state["outputs"]},
                )
                vector_memory.store(
                    large_doc.read_text(encoding="utf-8", errors="replace")[:12000],
                    project=project,
                    session_id=job_id,
                    subject="long_research_bundle",
                    kind="long_research",
                    role="system",
                    metadata={"job_id": job_id, **state["outputs"]},
                )
            except Exception as exc:
                state["warnings"].append(f"memory store failed: {exc}")
                save_state()
            if postprocess_callback:
                try:
                    postprocess_callback(project)
                except Exception as exc:
                    state["warnings"].append(f"postprocess failed: {exc}")
                    save_state()
            return f"Long research bundle written to {large_doc}\nCompressed algorithms: {compressed_doc}\nDeployment blueprint: {deployment_doc}"

        return f"Unhandled long research step: {description}"

    return executor
