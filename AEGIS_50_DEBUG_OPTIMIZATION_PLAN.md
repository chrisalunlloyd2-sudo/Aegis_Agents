# AEGIS 50-Point Debug Optimization Plan

Date: 2026-05-01

Scientific method rule: change one runtime-affecting variable at a time, predict the effect, test, keep only if evidence improves.

## Current Finding

Observed symptom: CPU spikes after the visible reply made it look like the model was still replying and getting cut off.

Hypothesis tested: post-reply semantic indexing was waking Ollama after the UI finished.

Result: live chat vector writes are now lexical-first by default. Smoke test returned a visible reply in about 19.8s, then Ollama CPU was 0 at 5s and 25s after completion.

## Phase 1: Stream Completion

1. Record first-token latency per reply.
2. Record final stream telemetry for every chat turn.
3. Add finish reason tracing when available from Ollama.
4. Flag replies that end at response budget.
5. Route "cut off" and "long story" prompts to full response budget.

## Phase 2: Model Runtime

6. Keep one active primary model for live chat unless testing a model switch.
7. Measure warm response time versus cold response time.
8. Measure CPU after visible completion.
9. Record Ollama HTTP 500 events with model and context size.
10. Recycle only stalled high-RAM runners, never the API listener.

## Phase 3: Context Policy

11. Keep a single context policy source in `context_policy.py`.
12. Avoid duplicate context knobs with competing values.
13. Use small context for casual chat.
14. Use long context only for explicit full-response/code/research cues.
15. Keep Fabric SOP selection to one or two templates per turn.

## Phase 4: Fabric

16. Store SOPs as compact JSON.
17. Keep Fabric performative, not factual.
18. Add SOPs only after a real lane exists.
19. Rank SOPs by exact keyword and role fit.
20. Do not inject raw SOP packs into every prompt.

## Phase 5: DB And Vector

21. Store nominal facts and evidence in DB/vector.
22. Use lexical-first live search.
23. Use lexical-first live writes.
24. Enable semantic embedding only for explicit indexing/research phases.
25. Prune low-signal chat snippets before promotion.

## Phase 6: Aider

26. Confirm Aider is installed before routing coding work.
27. Show Aider terminal output in the Web UI evidence panel.
28. Treat Aider as coding lane, not natural chat replacement.
29. Capture diffs, stdout, stderr, tests, and blockers.
30. Do not claim Aider completed work without terminal evidence.

## Phase 7: LAVA/KQML

31. Record agent-to-agent work as KQML-like events.
32. Keep LAVA volatile and evidence-oriented.
33. Expose recent LAVA events to the UI.
34. Use LAVA to record SOAP and genetic coder phases.
35. Do not use LAVA as long-term wisdom storage.

## Phase 8: SOAP And Genetic Coder

36. Mutate candidates in a sandbox.
37. Score candidates with compile/test evidence.
38. Update SOAP heuristic weights conservatively.
39. Promote only passing attempts to DB.
40. Promote only distilled, repeated successes to Fabric.

## Phase 9: UI

41. Remove unused buttons only after confirming the model/algorithm owns that decision.
42. Show terminal evidence separately from natural chat.
43. Show timeout/error traces in diagnostics.
44. Keep retry and stop controls visible.
45. Keep response text through refresh.

## Phase 10: Regression Guard

46. Run `py -3.11 -m py_compile` on changed Python files.
47. Validate all Fabric JSON.
48. Run `/api/health`.
49. Run one `/api/aegis/chat` smoke test.
50. Check CPU 5s and 25s after the reply.
