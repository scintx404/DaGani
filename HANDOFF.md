# gani-agent handoff

Read this first. It says what exists, what was decided, what is left, and what to do next.

## 1. Goal
AI assistant for the GSuite .gani animation editor. The user describes an animation ("heavy overhead slash, 6 frames, sound on impact"), the AI proposes it, the editor shows it live, and the AI self-corrects against pixel metrics and a contact-sheet critique. Accept = one undo entry. Reject = rollback.

## 2. Decisions (do not relitigate without a reason)
- The LLM never writes GANI text. It emits a KeyframePlan via tool call (generation) or ops JSON (corrections). A deterministic compiler and serializer write GANI.
- The LLM never measures pixels. OpenCV extracts sprite rects. Metrics catch drift, jitter, bounds and z-order. The vision model judges only what math can't: readability, arcs, silhouette.
- The AI sees clean offscreen renders from the editor's own export renderer (4x nearest, labelled contact sheet), not screen captures.
- Frontier multimodal API, provider-agnostic. Local CPU sidecar. No Colab, no tunnels.
- RAG over parsed corpus ASTs. No fine-tune until 500+ logged accepted plans.
- Editor integration is one import line plus a feature flag, plus one adapter file (`ai-bridge/EditorAdapter.js`). Do not rebase upstream. Merge plus rerere.
- Private code lives here. Keep the upstream remote push-disabled for sync.
- Narrow first: sword slash end to end, then generalize.

## 3. Architecture
Editor (GSuite, web/Wails) <-> JSON-RPC 2.0 over ws://127.0.0.1:8765 with a token <-> Python sidecar `gani-agent`.
Sidecar: orchestrator, sprite preprocessor (OpenCV), corpus (SQLite), compiler, metrics, LLM provider.
See the blueprint section in the project notes for the full diagram.

## 4. Repo facts (upstream scintx404/DaGani, GPL-3.0)
- Web app plus Wails v3 desktop shell (`main.go`, `service.go`, `workspace.go`). Version 0.1.85.
- Editor code: `js/anieditor.js` (about 900KB, the GANI editor). `js/leveleditor.js`, `js/particleengine.js` and others are out of scope.
- `ganis/` has about 50 production files. Sword and walk use `SPRITE` lines with a `SPRITE id SOURCE left top w h comment` shape.
- `js/wails-bridge.js` exposes `window.__GSUITE__` (fs, dialog, core.invoke).
- Upstream is GPL-3.0. Private modification is fine. Redistribution needs GPL compliance.
- Editor internals: `Animation` (frames, sprites Map, undoStack), `Frame` (pieces[4], sounds), `FramePieceSprite` (spriteIndex, xoffset, yoffset, scale, rotation, _zoom), `parseGani`, `drawFrame`, `drawSprite`, `serializeAnimationState`, `restoreAnimationState`, `addUndoCommand`, `redraw`.
- Export: GIF and MP4 export exists upstream. Find the render function (search `export` in anieditor.js) and reuse it for offscreen renders.
- `isExportRender` flag exists. Sounds are drawn only when not exporting.

## 5. Done (commit this with the handoff)
All code lives in the starter zip attached to the ClickUp task (`gani-agent-starter.zip`). It is not yet in this repo. Next agent: download it and copy `agent/` and `ai-bridge/` into the repo root.

- `agent/gani_agent/gani.py`: parser and serializer, `GaniDoc` AST. Golden round-trip holds on 3 fixtures. Unknown directives are kept verbatim.
- `agent/gani_agent/compiler.py`: `validate_plan`, `compile_plan` (tweens, quantize to 50ms, int px), `doc_to_plan`.
- `agent/gani_agent/ops.py`: op language (move, nudge, setSprite, addPiece, removePiece, reorder, setDuration, insertFrame, deleteFrame, addSound, removeSound). Atomic apply.
- `agent/gani_agent/metrics.py`: static drift, 1px jitter, out-of-bounds, empty dir, missing sprite, z-order rules (pairwise, learned from refs), raw coverage and centroid jump. Produces autofix ops.
- `agent/gani_agent/sprites.py`: OpenCV extraction (grid or connected components), exact rects, anchors, sheet-hash cache.
- `agent/gani_agent/corpus.py`: SQLite index, `index_dir` with round-trip and unknown-directive audit, category stats (p10/p50/p90), retrieval (category, keyword, motion).
- `agent/gani_agent/prompts.py`: planner and critic system prompts, KeyframePlan and critic JSON schemas, RAG injection template.
- `agent/gani_agent/llm.py`: Anthropic and OpenAI-compatible tool-call client, stdlib only, retries, prompt caching on system prompt.
- `agent/gani_agent/orchestrator.py`: generate (plan, one repair pass, compile) and correct (metrics, autofix, render, critic, apply, max 3 rounds). Emits a trace.
- `agent/gani_agent/renderer.py`: headless contact sheet and raw metrics from the sprite sheet. Stand-in until the editor renderer is wired.
- `agent/gani_agent/server.py`: JSON-RPC router. `ping`, `gani.validate`, `gani.apply` (stale-rev check), `tx.begin`/`tx.commit`/`tx.rollback`. Loopback WebSocket with token auth.
- `agent/gani_agent/cli.py`: `index`, `check`, `stats` (offline).
- `agent/tests/`: 16 parser, compiler, ops, metrics and sprite tests, plus 2 end-to-end tests with a fake LLM. Zero-dependency runner `run_tests.py` (pytest optional). Result: 18 passed.
- `agent/tests/fixtures/`: `sword.gani`, `walk.gani`, `editorcursor2.gani`, hand-transcribed from upstream. Must be replaced by byte-exact copies.
- `agent/config.toml`, `agent/requirements.txt`, `agent/README.md`.
- `ai-bridge/index.js`: init and WebSocket client skeleton (handler not implemented).
- `ai-bridge/EditorAdapter.js`: snapshot() implemented on paper, applyOps() throws, rest is placeholder names.

## 6. Not done (open, in priority order)
1. **Byte-exact fixtures.** Replace `agent/tests/fixtures/*.gani` with the real files from `ganis/`. Rerun the golden test. Fail the build if it doesn't pass.
2. **Phase 0: map the editor.** Read `js/anieditor.js` and fill EditorAdapter with real function names. Needed: snapshot, applyOps (one undo entry), loadGani in proposal mode, export render function, undo push, state-change hook. Verify WAIT timing against playback. Confirm `sword.gani` plays 250ms.
3. **Editor bridge.** Wire `ai-bridge/index.js` into the editor behind a feature flag (one import line). Implement the JSON-RPC client message handler and token read (Wails: via `window.__GSUITE__.fs.readTextFile` on the token file, or a service method).
4. **Real render.** Replace `HeadlessRenderer` with the editor's offscreen export renderer for `sheet()` and `raw()`.
5. **Corpus labels.** Run `gani-cli index` over the full `ganis/` set. Get one-time LLM descriptions. Review in bulk. Only then trust retrieval.
6. **Eval harness.** 20 held-out production slashes. Metrics: frame-count delta, total-ms delta, layer-order agreement, validator pass rate, metric violations. Every prompt or model change runs it.
7. **Agent panel UI** (prompt box, status, Accept, Reject, Refine). `ui.highlight` and `ui.status` during edits. Abort and re-snapshot on user edits (`state.changed by user`).
8. **Real critic loop test** against the live API with the pinned model (set `config.toml [llm].model`).
9. Later: other categories (walk, idle, reload, shoot, cast), sound suggestions, `sync.check` for upstream, training-data logging.
10. Last: the stealth mirror and private sync. The user asked to leave this for the end.

## 7. Known risks and open questions
- WAIT semantics: `(wait+1) x 50ms` is assumed. Unverified.
- Multi-sprite ids in the same gani can clash across sources. The sprite catalog keeps source names to disambiguate.
- Only one sprite-sheet image is loaded per session. Multi-sheet support is not done.
- `_isExportRender` suppresses sound icons. Make sure the export path doesn't pick up UI overlays.
- The `SPRITE` line format uses the editor's own column widths. Serializer output may differ in whitespace from upstream files. Round-trip is semantic, not byte-exact, so check it.
- Model choice is not pinned. Set it in `config.toml`.

## 8. Next action for the next agent
1. Copy `agent/` and `ai-bridge/` from the starter zip into the repo root. Commit.
2. Replace fixtures with byte-exact files from `ganis/`. Run `python3 agent/tests/run_tests.py`.
3. Do Phase 0 (item 2 above) and write the findings into this file under a "Phase 0 findings" section.
4. Then items 3 and 4.

## 9. Local commands
    python3 agent/tests/run_tests.py
    python3 -m agent.gani_agent.cli check agent/tests/fixtures/sword.gani
    pip install -r agent/requirements.txt && python3 -m agent.gani_agent --port 8765
