# AEGIS Phase 2 Fabric SOP Blueprint

This file captures the next implementation shape after the Phase 1 public checkpoint. It is intentionally operational, not a personality prompt.

## Fabric JSON Rule

All Fabric guidance should exist as weighted JSON templates with this hierarchy:

```json
{
  "template": {
    "name": "template_name",
    "schema_version": "fabric-json-v1",
    "description": "what it is for",
    "objective": "what success means",
    "keywords": ["activation", "words"],
    "heuristics": ["minimal_cli", "self_test"],
    "constraints": {},
    "metrics": {},
    "sop": ["ordered action rule"],
    "tool_context_rule": "Do not tool call in the main context window. Route tool calls through a separate tool window/context packet and return only compressed evidence to the GUI."
  }
}
```

## Always-On Web UI SOP

The model is answering inside an HTML/Web UI stream. It should answer naturally, avoid raw tool payloads, and use keepalive/status packets for long jobs. Tool work must happen in the separate tool context and return compressed evidence to the main reply.

## Genetic Coder SOP

1. Parse the ask into AskSet, ConstraintSet, CodeSet, TestSet, and EvidenceSet.
2. Use Fabric for distilled SOP and vector DB for full citations.
3. Ask Aider or the main model for outline edges only: first page, last page, interfaces, and test shape.
4. Build candidate blocks with Karoo-style tree/mutation logic.
5. Use SOAP-style fitness weighting to select mutation direction.
6. Compile/parse every candidate.
7. Run local tests for every surviving candidate.
8. Store passing candidates to vector DB.
9. Add distilled passing lessons back to Fabric citations.
10. Generate README, whitepaper, and build paper only after passing evidence exists.

## Webcrawl SOP

Flow:

```text
webcrawl -> parsed data -> thesis paper -> Fabric code rules -> vector DB citations
```

Rules:

- Official and primary sources first.
- Crawl into chunks with URL, domain, timestamp, credibility, and objective correlation.
- Store full source evidence in vector DB.
- Store only small distilled rules in Fabric.
- Prune duplicated SEO text, low-correlation chunks, stale fragments, and anything not tied to the user's active goals.

## Timeout Trace SOP

Timeouts and stream failures are recorded in `runtime_traces`.

Useful endpoints:

- `GET /api/runtime-traces/status`
- `GET /api/runtime-traces/recent?limit=50`

## Model Swap Note

The default local primary/code model is now configured as `gemma4:26b`. If `/api/health` reports it missing under `ollama_models.available`, the model download has not completed or has not been started on this machine.

## Next Integration Step

Tie the genetic coder, SOAP optimizer, Karoo-style mutation tree, compiler, debugger evidence, and Fabric/vector citation feedback into one supervised job lane. That final lane should be able to self-edit small blocks, but every change still needs pass/fail evidence before being called complete.
