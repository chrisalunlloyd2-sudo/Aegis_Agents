# AEGIS-DIMON Quick Start Guide

## Getting started in 60 seconds

### Prerequisites
1. Python 3.11+
2. Ollama installed and running
3. Local models available:
   - `aegis-gemma2-abliterated:2b-q8`
   - `qwen2.5-coder:1.5b`
   - `nomic-embed-text:latest`

### Quick launch
```bash
AEGIS_Launch.bat
```

Default posture:
- local-only blueprint
- FastAPI backend on `5005`
- coordinator model `aegis-gemma2-abliterated:2b-q8`
- PicoClaw direct-first execution sidecar on `aegis-gemma2-abliterated:2b-q8`
- tiny worker model `qwen2.5-coder:1.5b`
- browser helper isolated through `browser-use`
- remote lanes disabled unless you explicitly re-enable them
- normal turns only inject a matching file from `project_lenses/<project>.txt` when one exists
- the global `PROJECT_DIRECTIVE.txt` is now mainly for fallback defaults and automation flows

If `5005` is already taken:
```powershell
$env:AEGIS_PORT = "5006"
.\AEGIS_Launch.bat
```

## Manual startup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
copy .env.template .env
```

Important defaults in `.env`:
- `AEGIS_LOCAL_ONLY=1`
- `AEGIS_LOCAL_PRIMARY_MODEL=aegis-gemma2-abliterated:2b-q8`
- `AEGIS_LOCAL_CODE_MODEL=aegis-gemma2-abliterated:2b-q8`
- `AEGIS_LOCAL_TOOL_MODEL=qwen2.5-coder:1.5b`
- `AEGIS_PICOCLAW_MODEL=aegis-gemma2-abliterated:2b-q8`
- `AEGIS_BROWSER_USE_MODEL=aegis-gemma2-abliterated:2b-q8`

### 3. Install missing local models if needed
```bash
ollama pull qwen2.5-coder:1.5b
ollama pull nomic-embed-text
ollama create aegis-gemma2-abliterated:2b-q8 -f vendor/models/Modelfile.gemma2-abliterated-q8
```

### 4. Start the backend
```bash
python gemini_bridge_api_fast.py
```

## Access points

- Web UI: `http://localhost:5005/ui`
- Health: `http://localhost:5005/api/health`
- Docs: `http://localhost:5005/docs`
- Lens update route: `http://localhost:5005/api/lens/update`
- Aider status: `http://localhost:5005/api/aider/status`
- Genetic coder jobs: `http://localhost:5005/api/genetic-coder/jobs`
- Lava event status: `http://localhost:5005/api/lava/status`
- Lava event log: `http://localhost:5005/api/lava/events`
- Context policy: `http://localhost:5005/api/context/policy`

## What is running today

Core path:
- `gemini_bridge_api_fast.py` for the main local API
- `gemma_tools.py` for routing and tool policy
- `aegis_toolkit.py` for the registered tool surface
- `timescale_memory.py`, `vector_memory.py`, and `gemini_bridge.db` for local memory and persistence

Coordinator and worker split:
- the main model plans, routes, and provisions step blocks
- the tiny PicoClaw worker receives ACL/KQML-style task packets
- the tiny worker is stateless and does not need DB coupling to run code or verification tasks

Sidecars:
- `delegate_picoclaw` for tiny code insertion and verification tasks
- `browser_use_task` for browser and GUI automation only
- Aider terminal lane for recorded coding-agent output
- heuristic genetic coder for compile/test/debugger-evidence/fitness loops
- Lava-ready event plane for KQML/GC/SOAP recording and Fabric wisdom reinforcement
- Intel Lava package and Loihi hardware lane are still disabled until separately installed and tested

Notes:
- Activepieces is the preferred visual orchestration path if you later want editable workflows and approval gates.
- OpenAI/Codex escalation is intentionally off by default and not required for normal local operation.

## Troubleshooting

### Port already in use
```bash
python -m uvicorn gemini_bridge_api_fast:app --port 5006
```

### Database looks locked
- Close duplicate AEGIS backends first.
- Then delete `gemini_bridge.db-shm` and `gemini_bridge.db-wal` only if the backend is fully stopped.

### PicoClaw feels stuck
- The native CLI path is still being hardened.
- `delegate_picoclaw` will fall back to direct local Ollama chat when the native PicoClaw agent path stalls.

### Browser automation feels slow
- Keep `browser-use` tasks tight and browser-only.
- Do not use it as the main orchestrator for coding or system-wide loops.

### API 500s after edits
```powershell
Remove-Item -Recurse -Force __pycache__
python gemini_bridge_api_fast.py
```

## Upgrade path

Near-term priorities:
1. Stabilize native PicoClaw CLI behavior.
2. Add acceptance-test gating to `local_program_loop.py`.
3. Test the expanded long-reply budget through the Web UI.
4. Test Lava event recording from a real genetic-coder run, then add Intel Lava as a CPU-simulation probe only after confirmation.
5. Add the binary debugger adapter into the genetic coder `DebuggerSet` path.
6. Reduce lens memory bleed in ambiguous debugging turns.

Later options:
1. Add Activepieces for visual orchestration and approvals.
2. Add Skyvern only if GUI-heavy automation outgrows `browser-use`.
3. Add an optional OpenAI/Codex Responses API escalation lane for hard coding cases.

## Canonical docs

- `README.md`
- `AEGIS_MANIFOLD_BLUEPRINT.txt`
- `MANIFOLD_CHANGELOG.md`
- `project_lenses/README.md`
- `prompt_layer_archive/2026-04-21_cold_layers/README.md`
