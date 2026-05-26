"""
Dedicated browser-use worker that runs inside the isolated browser-use venv.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from browser_use import Agent, Browser
from browser_use.llm.ollama.chat import ChatOllama

from context_policy import WORKER_CONTEXT_WINDOW


def _safe_call(target, fallback):
    if callable(target):
        try:
            return target()
        except Exception:
            return fallback
    return target if target is not None else fallback


async def _run(request: dict) -> dict:
    task = (request.get("task") or "").strip()
    start_url = (request.get("start_url") or "").strip()
    allowed_domains = [str(item).strip() for item in request.get("allowed_domains", []) if str(item).strip()]
    headless = bool(request.get("headless", True))
    max_steps = max(1, min(int(request.get("max_steps", 10)), 25))
    model = (request.get("model") or "aegis-gemma2-abliterated:2b-q8").strip()
    ollama_base_url = (request.get("ollama_base_url") or "http://127.0.0.1:11434").strip()

    final_task = task
    if start_url:
        final_task = f"Start at {start_url}. {task}"

    llm = ChatOllama(
        model=model,
        host=ollama_base_url,
        ollama_options={
            "temperature": 0.1,
            "num_ctx": WORKER_CONTEXT_WINDOW,
            "num_predict": 160,
        },
    )
    browser = Browser(
        headless=headless,
        allowed_domains=allowed_domains or None,
        keep_alive=False,
        enable_default_extensions=False,
        minimum_wait_page_load_time=0.5,
        wait_for_network_idle_page_load_time=0.5,
        wait_between_actions=0.2,
    )
    agent = Agent(
        task=final_task,
        llm=llm,
        browser=browser,
        use_vision=False,
        use_thinking=False,
        enable_planning=False,
        use_judge=False,
        flash_mode=True,
        max_actions_per_step=1,
        step_timeout=45,
        llm_timeout=45,
    )

    try:
        history = await agent.run(max_steps=max_steps)
        urls = [item for item in (_safe_call(getattr(history, "urls", None), []) or []) if item]
        errors = [item for item in (_safe_call(getattr(history, "errors", None), []) or []) if item]
        actions = [item for item in (_safe_call(getattr(history, "action_names", None), []) or []) if item]
        return {
            "ok": bool(_safe_call(getattr(history, "is_done", None), False)) and not errors,
            "summary": _safe_call(getattr(history, "final_result", None), "") or "browser-use task finished.",
            "urls": urls,
            "errors": errors,
            "actions": actions,
            "steps": _safe_call(getattr(history, "number_of_steps", None), 0),
        }
    finally:
        try:
            stop_result = browser.stop()
            if asyncio.iscoroutine(stop_result):
                await stop_result
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Missing request path."}))
        return 1

    request_path = Path(sys.argv[1])
    if not request_path.exists():
        print(json.dumps({"ok": False, "error": f"Request file not found: {request_path}"}))
        return 1

    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result = asyncio.run(_run(request))
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result.get("ok") else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
