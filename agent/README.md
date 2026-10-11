# gani-agent

Local sidecar for the GSuite Gani editor. The LLM never writes GANI text and never measures pixels.

Pipeline: prompt -> retrieve refs -> planner emits a KeyframePlan (tool call) -> compiler -> GANI0001 ->
metrics (drift, jitter, bounds, z-order) -> contact sheet -> critic emits ops -> apply (max 3 rounds).

See ../HANDOFF.md for the full plan, status and next steps.

## Layout
- `gani_agent/gani.py`: parser and serializer (AST = `GaniDoc`). Golden round-trip is the contract.
- `gani_agent/compiler.py`: KeyframePlan validation, tweening, quantising to 50ms ticks.
- `gani_agent/ops.py`: the op language shared by critic, autofix and the editor bridge. Atomic.
- `gani_agent/metrics.py`: deterministic QA and autofixes.
- `gani_agent/sprites.py`: OpenCV sprite extraction, exact rects, cached by sheet hash.
- `gani_agent/corpus.py`: SQLite index, category stats, retrieval.
- `gani_agent/prompts.py`, `llm.py`: prompts, schemas, provider client (Anthropic / OpenAI-compatible).
- `gani_agent/orchestrator.py`: generate + correct loop. `renderer.py`: headless contact sheet.
- `gani_agent/server.py`: JSON-RPC over loopback WebSocket with token auth, `gani.apply` stale-rev check, tx.begin/commit/rollback.
- `../ai-bridge/`: editor-side client. `EditorAdapter.js` is the only file that touches editor internals (Phase 0 stub).

## Run (from the agent/ folder)
    python3 tests/run_tests.py                       # zero-dep test runner (pytest also works)
    python3 -m gani_agent.cli index /path/to/ganis --db corpus.sqlite
    python3 -m gani_agent.cli check tests/fixtures/sword.gani
    pip install -r requirements.txt && python3 -m gani_agent --port 8765

## Status
- Done: parser/serializer, compiler, ops, metrics, sprite extraction, corpus, orchestrator, RPC router, headless renderer, 18 tests.
- Not done (needs the editor source, Phase 0): EditorAdapter mutators, render via the editor's export path, ui.highlight, tx wiring to the real undo stack.
- Fixtures: `tests/fixtures/` are copies of upstream `ganis/` files (sword, walk, editorcursor2).
- Open questions: WAIT semantics (`(wait+1) * 50ms` assumed, verify against playback), sprite id collisions across sources.
