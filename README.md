# AEGIS-DIMON Hybrid AI System

Local-first coding and systems runtime with project memory, vector retrieval, compact worker lanes, and inspectable background loops.

## Quick start

Run:

```bat
AEGIS_Launch.bat
```

Default live posture:
- local-only blueprint
- FastAPI backend on `5005`
- coordinator and main code model: `aegis-gemma2-abliterated:2b-q8`
- tiny worker/tool model: `qwen2.5-coder:1.5b`
- embeddings: `nomic-embed-text:latest`
- browser lane isolated through `browser-use`
- PicoClaw available as a compact coding or verification sidecar

If `5005` is busy:

```powershell
$env:AEGIS_PORT = "5006"
.\AEGIS_Launch.bat
```

## What the runtime is now

AEGIS is currently built around a small number of hot-path layers:
- `gemini_bridge_api_fast.py` owns routing, streaming chat, local API endpoints, job launch, and runtime state.
- `gemma_tools.py` owns request profiling, tool policy, and modifier logic.
- `aider_terminal_lane.py` owns the Aider terminal evidence lane. Aider is installed in `vendor/aider_venv` and is launched from the Web UI so stdout/stderr/output tails are recorded instead of hidden.
- `heuristic_genetic_coder.py` owns the new heuristic genetic coding lane. It evolves small Python candidates, compiles them, runs tests, stores KQML traces, and writes successful code tries back to SQLite.
- `coding_kernels.py` plus `coding_kernels/` provide compact language-specific reference packs for code generation.
- `local_program_loop.py` owns the background research -> plan -> implement -> test -> fix cycle.
- `timescale_memory.py`, `vector_memory.py`, and `gemini_bridge.db` hold local project memory and persistence.

## Aider plus genetic coder lane

The current working architecture is:
- Aider owns the coding outline and terminal-facing pair-programming lane.
- The Web UI records Aider terminal evidence.
- The heuristic genetic coder fills tested implementation candidates inside a local workspace.
- SOAP-style heuristic weights reinforce mutation strategies that produce passing code.
- KQML envelopes record the internal handoff and evidence messages.
- Successful code tries are persisted in `gemini_bridge.db` under the genetic coder tables.
- The Lava-ready event plane records GC/SOAP/KQML events through `/api/lava/*` and feeds verified successes back into Fabric wisdom.

First verified smoke result:
- Endpoint: `POST /api/genetic-coder/run`
- Job: `genetic-1777438289-d5b090df`
- Result: compile pass, runtime pass, best fitness `0.9072`
- Workspace: `agentic_jobs/genetic_coder/general/Build-a-tiny-Python-program-that-returns-an-EvidenceSet-and-proves-it-runs/`

Set-theory path for this lane:
- `AskSet`: user objective plus Aider outline.
- `SourceSnippetSet`: GitHub/web crawl snippets used as implementation evidence.
- `ConstraintSet`: local workspace, timebox, language, no-network execution.
- `CodeSet`: generated candidate files and best candidate.
- `TestSet`: compile and runtime checks.
- `DebuggerSet`: compiler/runtime/debugger traces converted into bounded repair hints for the next mutation.
- `EvidenceSet`: command output, return codes, likelihood score, pass/fail, and fitness.

GitHub and web snippets are useful as evidence, not automatic execution. Repos can provide patterns, tests, and algorithms, but installation or running newly acquired code still needs explicit confirmation.

For binary-code work, the debugger belongs inside this same loop: compile or build candidate -> run/debug -> collect trace evidence -> propose the smallest fix -> recompile -> pass/fail. Vector35/Binary Ninja-style debugger integration is therefore an adapter for the genetic coder fitness loop, not a separate chat layer.

## Lava event plane

Intel Lava/Loihi is not installed or active yet. The current implementation is the local control plane that lets us learn safely before hardware work:
- `lava_event_orchestrator.py` records KQML-shaped events in SQLite.
- `/api/lava/status` shows the effective event state and confirms whether Intel Lava is enabled.
- `/api/lava/events` returns the recent event log for the Web UI.
- Genetic-coder candidates now emit Lava-plane events after evaluation.
- Passing genetic-coder candidates are upserted into Fabric as weighted project wisdom.

This gives the GC a real event loop to learn from while keeping Loihi work on a later machine and avoiding duplicate prompt/context layers.

## What we did not lose

The cleanup pass removed prompt clutter, not core capability.

Still live:
- project lenses
- fallback global directive
- PicoClaw delegation
- browser-use lane
- research loop
- create-program loop
- local memory plus vector retrieval
- local public tunnel path

Moved out of the hot path but not deleted:
- older orchestration posture files
- bulky steering layers
- remote/cloud lane posture docs and older prompt scaffolding

Those archived layers live under `prompt_layer_archive/`.

## Distilled knowledge packs

One of the main lessons from this pass is simple:

If the model does not reliably know a domain in the exact form we need, add a distilled pack instead of adding more vague steering.

Current live pack family:
- `coding_kernels/` for language-focused coding guidance

Good next pack families:
- math kernels
- statistics kernels
- STEM kernels
- project-specific domain kernels
- personal heuristic packs that capture how you prefer problems to be reduced

The right pattern is:
- keep packs terse
- keep them practical
- load only the relevant pack
- avoid turning them into essays

## Personal system twin

AEGIS now has a first-pass local personal system twin in `personal_system_twin.py`. It records structured workflow events, derives habit hints, and writes `system_twin/latest_snapshot.json` so Lens, watchdogs, and build loops can communicate through snapshots instead of raw chat memory.

It is intentionally trust-preserving: no screenshots, clipboard contents, keystrokes, or raw chat logs are collected by this module. It only learns from explicit structured events that other local layers send.

## Memory and retrieval

AEGIS uses two local memory surfaces:
- readable project memory through `timescale_memory.py`
- semantic plus lexical recall through `vector_memory.py`

This gives the runtime:
- human-readable records
- project lanes
- local retrieval without depending on a remote DB
- better recall for prior fixes, reports, and artifacts

## Build loops and stable workspaces

The create-program engine now uses stable workspaces instead of bouncing into fresh scratch folders by default.

Default workspace shape:

```text
agentic_jobs/program_workspaces/<project>/<objective>/
```

Inside a program workspace, the loop writes:
- `objective.txt`
- `project.txt`
- `language_profile.json`
- `coding_kernel.txt`
- `task_hints.txt`
- `directive_snapshot.txt`
- `LATEST_SNAPSHOT.json`
- `research.md`
- `BUILD_REPORT.md`
- `artifacts/...`

That layout is meant to keep the loop inspectable and reduce file-to-file churn.

## Modifier logic

The runtime now promotes some user phrases into explicit control flags instead of leaving them as soft prompt hints.

Examples:
- `be more vocal`
- `full response`
- `make it run`
- `research loop`
- `program loop`

These flags are threaded into:
- the system prompt
- the reduced brief
- the execution plan
- tool follow-up prompts
- the program loop workspace choice

## Snapshots and layer communication

The cleanest way to pass state between layers is a structured snapshot, not another free-form prompt layer.

Current live behavior:
- program workspaces now maintain `LATEST_SNAPSHOT.json`
- phase snapshots are also written under `artifacts/`

Why this is better:
- smaller than replaying long prompt history
- machine-readable
- diffable
- easier to inspect when the model drifts
- easier to reuse across coordinator, worker, and repair phases

Snapshot guidance is documented in `LAYER_SNAPSHOT_PROTOCOL.md`.

## API surface

Main routes:
- `POST /api/aegis/chat`
- `GET /api/aider/status`
- `POST /api/aider/run`
- `GET /api/aider/job/{job_id}`
- `POST /api/genetic-coder/run`
- `GET /api/genetic-coder/job/{job_id}`
- `POST /api/agentic/research`
- `POST /api/agentic/create-program`
- `GET /api/agentic/job/{job_id}`
- `GET /api/project/dashboard`
- `GET /api/vector/status`
- `GET /api/health`
- `GET /api/system-twin/status`
- `POST /api/system-twin/event`

Useful direct chat triggers:
- `/research <objective>`
- `/program <objective>`

## Current truth on sidecars

PicoClaw:
- live and callable through `delegate_picoclaw`
- best treated as a compact worker, not a memory authority
- native CLI path still needs hardening

Browser-use:
- live and useful for browser-only flows
- intentionally not the main orchestrator for coding or system loops

## Upgrade path

Near term:
1. Keep expanding distilled packs beyond coding.
2. Add stricter output-contract checks for things like JSON or CSV so the code path obeys format requests more reliably.
3. Promote `LATEST_SNAPSHOT.json` into a shared handoff surface across more layers, not just the program loop.
4. Add stronger acceptance-test gating to the create-program loop.

Later:
1. Re-enable remote lanes only when local-first behavior is stable enough that remote capacity is truly useful.
2. Add Activepieces only if editable workflow graphs and approvals become worth the complexity.
3. Add an optional OpenAI/Codex escalation lane later without replacing the local default path.

## Canonical docs

- `README.md`
- `QUICK_START.md`
- `AEGIS_MANIFOLD_BLUEPRINT.txt`
- `MANIFOLD_CHANGELOG.md`
- `LAYER_SNAPSHOT_PROTOCOL.md`
- `PERSONAL_SYSTEM_TWIN_BLUEPRINT.md`
- `project_lenses/README.md`
- `coding_kernels/README.md`
- `prompt_layer_archive/2026-04-21_cold_layers/README.md`

## Web-Equivalent Dry Replay Tester

The no-browser testing lane is:
- `Aegis_Test_Rounds_GUI.py` for a desktop Submit Test Rounds launcher.
- `aegis_web_replay_batch.py` for long unattended batches such as 500 prompts.
- `.vscode/tasks.json` for launching the API, GUI, or 500-prompt dry run from the current Aegis VS Code workspace.

The replay runner calls the same `/api/aegis/chat` contract used by the browser UI and parses the same JSON/SSE response shape. It adds `dry_run=true` so directive writes, tool execution, research jobs, program loops, and memory postprocessing are recorded as proposed actions instead of executed.

Outputs are saved under:

```text
training_runs/web_replay/<run_id>/
```

Important files:
- `SUMMARY.txt`
- `responses_all.txt`
- `metrics.csv`
- `records.jsonl`
- `proposed_changes_and_tools.txt`
- `errors.txt`
- `apk_training_notes.txt`
- `prompts/*.txt`
