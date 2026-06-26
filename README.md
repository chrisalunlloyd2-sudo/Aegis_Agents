# Aegis_Agents

> Advanced Analytics System - Real-time algorithm evolution tracking - ML model performance dashboards - Predictive success scoring - Auto-optimization recommendations - Live competitor analysis

*Auto-generated 2026-06-26 10:04 from source — branch `main`, 25 Python modules, 27 other files.*

## Architecture

```
  .director_payload.md
  .env.template
  .gitignore
  AEGIS_INDEXER.py
  AEGIS_Launch.bat
  AEGIS_MANIFOLD_BLUEPRINT.txt
  AGENTIC_SYSTEM_GUIDE.md
  Aegis_Igniter.py
  Blueprint.md
  CHANGELOG.md
  DIAGNOSTIC_REPORT.md
  DIMON_CORE_DISTILLED.py
  gemini_extension/
    content.js
    manifest.json
    notes_inject.js
```

## Dependencies

External packages imported by this project:

`PIL`, `codecs`, `ddgs`, `dotenv`, `dspy`, `engine`, `fastapi`, `flask`, `flask_cors`, `flask_restful`, `gradio`, `html`, `numpy`, `ollama`, `playwright`, `psycopg2`, `pyautogui`, `pydantic`, `qdrant_client`, `requests`, `sklearn`, `sqlalchemy`, `statistics`, `tkinter`, `torch`, `uvicorn`, `webbrowser`

## How to run

Executable entry points (have a `__main__` block):

- `python AEGIS_INDEXER.py`
- `python Aegis_Igniter.py`
- `python DIMON_CORE_DISTILLED.py`
- `python Engine.py`
- `python GEMINIX_ORCHESTRATOR.py`
- `python MOLTBOOK_STRESS_TEST.py`
- `python aegis_dspy.py`
- `python agentic_demo.py`
- `python cleanup_memory.py`
- `python dimon_mionet_logic.py`
- `python dimon_neural_bridge.py`
- `python dimon_operator_engine.py`

## Modules

### `AEGIS_INDEXER.py`

- `index_workspace()`

### `Aegis_Igniter.py`

- `ignite()`

### `DIMON_CORE_DISTILLED.py`

- **class `FNN`**
  - methods: `forward`
- **class `AegisDIMON`**
  - methods: `forward`
- **class `DIMONCore`**
  - methods: `program_of_thoughts`, `rlcf_judge`, `knowledge_distillation`, `extract_topology`, `persist`, `process_file`

### `Engine.py`

- **class `AegisMasterEngine`**
  - methods: `read_local_file`, `fetch_cloud_memory`, `_bg_sync`, `sync_to_cloud`, `web_search`, `ask`
- **class `AegisGUI`**
  - methods: `append_to_chat`, `send_message`, `process_ai_response`, `display_ai_response`

### `GEMINIX_ORCHESTRATOR.py`

- `get_timestamp()`
- `run_diagnostic()` — Runs a full system check and returns a summary list.
- `generate_report(checks, url)`
- `main()`

### `MOLTBOOK_STRESS_TEST.py`

- `log(test_name, status, details)`
- `test_fastapi_health()`
- `test_database_wal()`
- `test_vram_fencing()`
- `test_manifold_persistence()`
- `main()`

### `advanced_analytics.py`

Advanced Analytics System
- Real-time algorithm evolution tracking
- ML model performance dashboards
- Predictive success scoring
- Auto-optimization recommendations
- Live competitor analysis

- **class `AlgorithmEvolutionTracker`** — Track how algorithms improve over time
  - methods: `track_algorithm_performance`, `predict_next_iteration`
- **class `MLModelDashboard`** — Track model performance metrics
  - methods: `log_model_run`, `compare_models`
- **class `PredictiveSuccessScoring`** — Predict success of new algorithms before running
  - methods: `score_algorithm`, `recommend_best_approach`
- **class `AutoOptimization`** — Automatically suggest optimizations
  - methods: `analyze_bottleneck`, `generate_optimization_report`
- **class `CompetitorAnalysis`** — Analyze competitor solutions and techniques
  - methods: `analyze_technique`, `compare_to_competitors`
- `register_analytics_routes(app)` — Add analytics endpoints to Flask app

### `aegis_dspy.py`

- **class `AegisLogicSignature`** — 180-IQ Symbolic Mapping.
- **class `AegisOptimizer`**
  - methods: `forward`
- `initialize_dspy(model_name)` — Initializes the DSPy compiler with the Gemini Teacher.

### `agentic_crawler_db.py`

Agentic Crawler Database v2.0
- Human-readable 5KB text chunks from web crawling
- Query-based web search and page crawling
- Boolean search with per-interaction NOT tables
- Correlation analysis (R-value calculation)
- Automatic pruning for expired and unused data

- **class `_HTMLContentExtractor`** — Extract visible text and links without extra dependencies.
  - methods: `handle_starttag`, `handle_endtag`, `handle_data`, `get_text`
- **class `AgenticCrawlerDB`**
  - methods: `_load_metadata`, `_save_metadata`, `_normalize_url`, `_extract_domain`, `_split_content`, `_clean_search_result_url`, `_strip_html`, `_fetch_text_resource`, `_fetch_page`

### `agentic_demo.py`

Agentic System Demo
Demonstrates the full agentic loop with web crawling and correlation analysis

- `decompose_research_task(description)` — Break down a complex research task into subtasks
- `execute_subtask(subtask)` — Execute a single subtask
- `demo_simple_task()` — Demo: Simple 4-step task
- `demo_complex_task()` — Demo: Complex multi-language research
- `demo_pruning()` — Demo: Database pruning
- `demo_job_management()` — Demo: Job listing and management

### `agentic_loop_controller.py`

Agentic Loop Controller v1.0
- Multi-step task decomposition (Plan → Execute → Evaluate → Summarize)
- Asynchronous background execution with job tracking
- Recursive summarization to prevent context drift
- Integration with crawler database

- **class `TaskStatus`**
- **class `SubTask`**
- **class `AgenticJob`**
- **class `AgenticLoopController`**
  - methods: `_load_jobs`, `_subtask_to_dict`, `_subtask_from_dict`, `_save_job`, `create_job`, `execute_job_async`, `_execute_job_loop`, `_evaluate_result`, `_create_recursive_summary`

### `cleanup_memory.py`

AEGIS Memory Cleanup Utility
Cleans up bloated indexes and removes old memory files

- `cleanup_bloated_index()` — Clean up the old bloated global_index.json
- `cleanup_old_indexes()` — Remove old index segments, keep only last 10
- `show_index_stats()` — Show current index statistics
- `rebuild_indexes()` — Rebuild indexes from scratch (nuclear option)

### `dimon_mionet_logic.py`

- **class `FNN`** — Standard Feed-Forward Neural Network for Branch/Trunk
  - methods: `forward`
- **class `AegisDIMON`** — True MIONet implementation for DIMON (Diffeomorphic Mapping Operator Learning).
  - methods: `forward`
- **class `DIMONLogicEngine`** — Orchestrates the mathematical logic recognition using MIONet.
  - methods: `_get_timescale_conn`, `extract_topology`, `learn_operator`, `_persist_to_timescale`

### `dimon_neural_bridge.py`

- **class `DIMONNeuralBridge`** — Implements DIMON-inspired Neural Database management with PCA-based kernel pruning.
  - methods: `fetch_embeddings`, `prune_kernel`, `update_neural_db`

### `dimon_operator_engine.py`

- **class `DIMONOperatorEngine`** — Implements the Diffeomorphic Mapping (phi_theta) from Nature 2024.
  - methods: `_init_db`, `map_to_reference`, `_store_manifold`

### `gemini_bridge.py`

- `log_event(msg)`
- `omni_acceptor()`
- `chat_interface(user_input, history)`

### `gemini_bridge_api.py`

Gemini Bridge API Server
Unified control interface for Gemini CLI and Cursor with TimescaleDB logging

- **class `Task`**
- **class `Heartbeat`**
- **class `Reminder`**
- **class `ResearchTask`**
- **class `ResearchNote`**
- **class `RagSync`**
- **class `HealthResource`**
  - methods: `get`
- **class `TaskResource`**
  - methods: `get`, `post`
- **class `HeartbeatResource`**
  - methods: `get`
- **class `ReminderResource`**
  - methods: `get`, `post`
- **class `ResearchResource`**
  - methods: `get`, `post`
- `check_auth()` — Skip auth in test mode
- `neural_search()`
- `receive_signal()` — Receive red dot signal from phone CLI (phone_automation_script.js)
- `get_signal_status()` — Check current status of the red dot signal
- `agent_command()`
- `desktop_screenshot()`
- `desktop_click()`
- `browser_open()`
- `browser_read()`
- `desktop_dot()`
- `mobile_dot()` — HOMEOSTASIS 1: The Android Red Dot Trigger.
- `timescale_sync()` — CANADIAN ULTRA: The TimescaleDB Sync Tunnel.
- `save_research_note()` — Saves a specific high-value note from the Gemini App to the RAG.
- `learn_logic()` — DIMON LEARNING: Stores a permanent behavioral/logical rule for the AI.
- `get_logic_rules()` — Retrieves all learned logic rules to inject into the App's context.

### `gemini_bridge_api_fast.py`

- **class `NeuralManifold`**
- **class `Task`**
- **class `Conversation`**
- **class `Feedback`**
- **class `ChatMessage`**
- **class `SignalData`**
- **class `FeedbackData`**
- `set_sqlite_pragma(dbapi_connection, connection_record)`
- `get_memory_status()` — Check timescale memory system status
- `sync_state(key, value)` — Persists global state to consistency.db
- `perform_deep_research(objective)`
- `agent_chooser(prompt)` — Always route to gemma2:2b as per user requirement - single model system.
- `get_ui()`
- `health()`
- `post_feedback(data)`
- `get_signal_status()`
- `receive_signal(data)`
- `delete_conversation()`
- `aegis_chat(data, background_tasks, request)`

### `gemini_bridge_minimal.py`

MINIMAL Gemini Bridge - Zero dependencies except Flask
Works offline, no database required initially

- `index()`
- `ui()`
- `health()`
- `task_handler()`
- `get_task(task_id)`
- `heartbeat()`
- `execute_task(task)`

### `gemini_bridge_rag.py`

Enterprise RAG System for Gemini Bridge
Real-time Task Tracking, Deep Research Orchestration, and File Integration
Uses: Qdrant (Vector DB), Gemini API, LLM Embeddings for context

- **class `EnterpriseRAGSystem`** — Enterprise-level RAG (Retrieval Augmented Generation) system
  - methods: `init_collections`, `get_embedding`, `store_in_rag`, `retrieve_relevant_context`, `complete_all_tasks`

### `gemma_tools.py`

Tool Calling System for Gemma 2B
Enables Gemma to use tools through structured prompts

- `create_file(path, content)` — Create a file with content
- `read_file(path)` — Read file contents
- `list_directory(path)` — List directory contents
- `execute_command(command)` — Execute shell command
- `search_web(query)` — Search web (placeholder)
- `get_tools_prompt()` — Generate prompt describing available tools
- `parse_tool_call(response)` — Parse tool call from Gemma's response
- `execute_tool(tool_call)` — Execute a tool call
- `create_system_prompt()` — Create system prompt with tool instructions

### `knowledge_base_api.py`

Algorithm & Code Knowledge Base API
Extends gemini_bridge_api.py with TimescaleDB integration
Tracks what worked, what didn't, and why

- **class `AlgorithmKnowledgeBase`** — Shared knowledge database for code and algorithms
  - methods: `log_code_attempt`, `log_lesson_learned`, `add_working_pattern`, `get_effectiveness_dashboard`, `get_failed_approaches`, `search_similar_problems`
- `get_db_connection()` — Connect to TimescaleDB knowledge base
- `register_kb_routes(app)` — Register knowledge base routes

### `logic_cube_solver.py`

- `boolean_multiply(A, B)` — Boolean matrix multiplication (AND then OR).
- `calculate_hamming_distance(C, target)` — Hamming distance between current result C and target B.
- `solve_logic_cube(A, target, max_iterations)` — Solves A * X = target for X in a Boolean field.

### `setup_aegis.py`

AEGIS-DIMON Setup Script
Automated setup and verification for the AEGIS system

- `print_header(text)`
- `print_status(message, status)`
- `check_python_version()`
- `check_ollama()`
- `check_env_file()`
- `install_requirements()`
- `check_database()`
- `create_consistency_db()`
- `main()`

### `timescale_memory.py`

AEGIS Timescale Memory System v2.0
Optimized with deduplication and segmented indexing
- Boolean logic and operators only (no NLP)
- 2KB max per file, 60 files per hour
- Segmented indexes (10KB max per segment)
- Deduplication to prevent repeats
- Daily secrets file for APIs/links/variables
- Weekly summaries compressed to 1KB "feelings" file

- **class `TimescaleMemory`**
  - methods: `_get_current_index_file`, `_load_current_index`, `_save_index`, `_load_seen_hashes`, `_content_hash`, `_is_duplicate`, `_get_time_path`, `_compress_to_boolean`, `store`

## Public API index

| Module | Function | Signature |
|--------|----------|-----------|
| `AEGIS_INDEXER` | `index_workspace` | `index_workspace()` |
| `Aegis_Igniter` | `ignite` | `ignite()` |
| `GEMINIX_ORCHESTRATOR` | `generate_report` | `generate_report(checks, url)` |
| `GEMINIX_ORCHESTRATOR` | `get_timestamp` | `get_timestamp()` |
| `GEMINIX_ORCHESTRATOR` | `main` | `main()` |
| `GEMINIX_ORCHESTRATOR` | `run_diagnostic` | `run_diagnostic()` |
| `MOLTBOOK_STRESS_TEST` | `log` | `log(test_name, status, details)` |
| `MOLTBOOK_STRESS_TEST` | `main` | `main()` |
| `MOLTBOOK_STRESS_TEST` | `test_database_wal` | `test_database_wal()` |
| `MOLTBOOK_STRESS_TEST` | `test_fastapi_health` | `test_fastapi_health()` |
| `MOLTBOOK_STRESS_TEST` | `test_manifold_persistence` | `test_manifold_persistence()` |
| `MOLTBOOK_STRESS_TEST` | `test_vram_fencing` | `test_vram_fencing()` |
| `advanced_analytics` | `register_analytics_routes` | `register_analytics_routes(app)` |
| `aegis_dspy` | `initialize_dspy` | `initialize_dspy(model_name)` |
| `agentic_demo` | `decompose_research_task` | `decompose_research_task(description)` |
| `agentic_demo` | `demo_complex_task` | `demo_complex_task()` |
| `agentic_demo` | `demo_job_management` | `demo_job_management()` |
| `agentic_demo` | `demo_pruning` | `demo_pruning()` |
| `agentic_demo` | `demo_simple_task` | `demo_simple_task()` |
| `agentic_demo` | `execute_subtask` | `execute_subtask(subtask)` |
| `cleanup_memory` | `cleanup_bloated_index` | `cleanup_bloated_index()` |
| `cleanup_memory` | `cleanup_old_indexes` | `cleanup_old_indexes()` |
| `cleanup_memory` | `rebuild_indexes` | `rebuild_indexes()` |
| `cleanup_memory` | `show_index_stats` | `show_index_stats()` |
| `gemini_bridge` | `chat_interface` | `chat_interface(user_input, history)` |
| `gemini_bridge` | `log_event` | `log_event(msg)` |
| `gemini_bridge` | `omni_acceptor` | `omni_acceptor()` |
| `gemini_bridge_api` | `aegis_chat` | `aegis_chat()` |
| `gemini_bridge_api` | `agent_command` | `agent_command()` |
| `gemini_bridge_api` | `browser_open` | `browser_open()` |
| `gemini_bridge_api` | `browser_read` | `browser_read()` |
| `gemini_bridge_api` | `check_auth` | `check_auth()` |
| `gemini_bridge_api` | `collect_heartbeat` | `collect_heartbeat()` |
| `gemini_bridge_api` | `desktop_click` | `desktop_click()` |
| `gemini_bridge_api` | `desktop_dot` | `desktop_dot()` |
| `gemini_bridge_api` | `desktop_screenshot` | `desktop_screenshot()` |
| `gemini_bridge_api` | `execute_research` | `execute_research(research_id)` |
| `gemini_bridge_api` | `execute_task` | `execute_task(task_id)` |
| `gemini_bridge_api` | `extract_section` | `extract_section(text, start_marker, end_marker)` |
| `gemini_bridge_api` | `get_logic_rules` | `get_logic_rules()` |
| `gemini_bridge_api` | `get_signal_status` | `get_signal_status()` |
| `gemini_bridge_api` | `heartbeat_thread` | `heartbeat_thread()` |
| `gemini_bridge_api` | `index` | `index()` |
| `gemini_bridge_api` | `learn_logic` | `learn_logic()` |
| `gemini_bridge_api` | `mobile_dot` | `mobile_dot()` |
| `gemini_bridge_api` | `neural_search` | `neural_search()` |
| `gemini_bridge_api` | `receive_signal` | `receive_signal()` |
| `gemini_bridge_api` | `save_research_note` | `save_research_note()` |
| `gemini_bridge_api` | `timescale_sync` | `timescale_sync()` |
| `gemini_bridge_api` | `trigger_cursor_handover` | `trigger_cursor_handover(task_message)` |
| `gemini_bridge_api` | `ui` | `ui()` |
| `gemini_bridge_api_fast` | `aegis_chat` | `aegis_chat(data, background_tasks, request)` |
| `gemini_bridge_api_fast` | `agent_chooser` | `agent_chooser(prompt)` |
| `gemini_bridge_api_fast` | `delete_conversation` | `delete_conversation()` |
| `gemini_bridge_api_fast` | `get_memory_status` | `get_memory_status()` |
| `gemini_bridge_api_fast` | `get_signal_status` | `get_signal_status()` |
| `gemini_bridge_api_fast` | `get_ui` | `get_ui()` |
| `gemini_bridge_api_fast` | `health` | `health()` |
| `gemini_bridge_api_fast` | `perform_deep_research` | `perform_deep_research(objective)` |
| `gemini_bridge_api_fast` | `post_feedback` | `post_feedback(data)` |

## Status

- Branch: `main`
- Last commit: 2026-06-21 19:44:15 -0600
- File types: .md ×11, .txt ×5, .js ×3, .template ×1, .bat ×1, .html ×1, .log ×1, .db ×1

### Recent commits
```
7baba9b [Moe autonomous] Aegis_Agents 2026-06-21 19:44
f04a613 [Moe autonomous] Aegis_Agents 2026-06-21 19:00
74d955c [Moe autonomous] Aegis_Agents 2026-06-19 20:56
e594065 Delete daily rituals from VIPER_PERSONAL_PROMPT.txt
a41b31e Enterprise: Automated Project Sync
a6f3e5b docs: Add docstrings to crawler database
0e55cde fix: Add null check for recursive summary
8d065c3 feat: Add Agentic Loop System with 100+ step reasoning - Implemented agentic_loop_controller.py for multi-step task decomposition - Added agentic_crawler_db.py with Pearson R-value correlation analysis - Created comprehensive documentation (AGENTIC_SYSTEM_GUIDE.md) - Fixed Cloudflare Tunnel Error 1033 - Replaced vector RAG with timescale memory system - Added automatic pruning (30-day retention) - Implemented recursive summarization to prevent context drift - Updated README.md and AEGIS_MANIFOLD_BLUEPRINT.txt
```

---
*README generated by `readme_generator.py` (Viper). Deterministic — derived from source, not LLM prose.*