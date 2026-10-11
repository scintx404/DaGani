# gani-agent

Local sidecar for the GSuite Gani editor. The LLM never writes GANI text and never measures pixels.

Pipeline: prompt -> retrieve refs -> planner emits a KeyframePlan (tool call) -> compiler -> GANI0001 -> metrics (drift, jitter, bounds, z-order) -> contact sheet -> critic emits ops -> apply (max 3 rounds).

See ../HANDOFF.md for the full plan and current integration notes.

## Layout
- `gani_agent/gani.py`: parser and serializer (AST = `GaniDoc`). Golden round-trip is the contract.
- `gani_agent/compiler.py`: KeyframePlan validation, tweening, quantising to 50ms ticks.
- `gani_agent/ops.py`: the op language shared by critic, autofix and the editor bridge. Atomic.
- `gani_agent/metrics.py`: deterministic QA and autofixes.
- `gani_agent/sprites.py`: OpenCV sprite extraction, exact rects, cached by sheet hash.
- `gani_agent/corpus.py`: SQLite index, category stats, retrieval.
- `gani_agent/prompts.py`, `llm.py`: prompts, schemas, provider client.
- `gani_agent/orchestrator.py`: generate + correct loop. `renderer.py`: headless contact sheet.
- `gani_agent/server.py`: JSON-RPC over loopback WebSocket with token auth, stale-revision checks, and transactions.
- `../ai-bridge/`: editor-side client and Copilot panel.

## Run
From the repository root:

```bash
export GEMINI_API_KEY="your-key"
python3 -m venv .venv
. .venv/bin/activate
pip install -r agent/requirements.txt
python3 -m gani_agent --port 8765
```

Start the web editor in another terminal with `npm start`, then open `http://localhost:13772/`. The Copilot panel lets you choose **Gemini 3.8 Flash** or **Gemini 3.1 Pro** per generation. The selection is persisted locally and the sidecar still falls back to configured Gemini models if a requested model is unavailable.

Never put an API key in `agent/config.toml` or commit it to git. If a key was ever committed, revoke it in Google AI Studio and create a new one.

## Tests
```bash
python3 agent/tests/run_tests.py
```

The editor bridge and sidecar are covered by regression tests; live model calls require a valid Gemini key and are intentionally not part of the offline test suite.
