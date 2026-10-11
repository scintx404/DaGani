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
See `agent/README.md` for the module layout.

## 4. Repo facts (upstream scintx404/DaGani, GPL-3.0)
- Web app plus Wails v3 desktop shell (`main.go`, `service.go`, `workspace.go`). Version 0.1.85.
- Editor code: `js/anieditor.js` (about 900KB, the GANI editor). `js/leveleditor.js`, `js/particleengine.js` and others are out of scope.
- `ganis/` has about 50 production files. Sword and walk use `SPRITE` lines with a `SPRITE id SOURCE left top w h comment` shape.
- `js/wails-bridge.js` exposes `window.__GSUITE__` (fs, dialog, core.invoke).
- Upstream is GPL-3.0. Private modification is fine. Redistribution needs GPL compliance.
- Editor internals: `Animation` (frames, sprites Map, undoStack), `Frame` (pieces[4], sounds), `FramePieceSprite` (spriteIndex, xoffset, yoffset, scale, rotation, _zoom), `parseGani`, `drawFrame`, `drawSprite`, `serializeAnimationState`, `restoreAnimationState`, `addUndoCommand`, `redraw`.
- Export: GIF and MP4 export exists upstream. Find the render function (search `export` in anieditor.js) and reuse it for offscreen renders.
- `isExportRender` flag exists. Sounds are drawn only when not exporting.

## 5. Done (all in the repo now)
- `agent/` is the sidecar package. Modules: `gani_agent/gani.py` (parser and serializer), `compiler.py`, `ops.py`, `metrics.py`, `sprites.py`, `corpus.py`, `prompts.py`, `llm.py`, `orchestrator.py`, `renderer.py`, `server.py`, `cli.py`.
- `agent/tests/`: 16 unit tests and 2 end-to-end tests with a fake LLM. Run `python3 agent/tests/run_tests.py` from the repo root. Last run: 18 passed.
- `agent/tests/fixtures/`: `sword.gani`, `walk.gani`, `editorcursor2.gani` are copies of upstream `ganis/` files.
- `agent/config.toml`, `agent/requirements.txt`, `agent/README.md`.
- `ai-bridge/index.js`: init and WebSocket client skeleton. The message handler is not implemented.
- `ai-bridge/EditorAdapter.js`: `snapshot()` written against guessed editor names. `applyOps()` throws. Other names are placeholders.
- Not verified against the live editor or the live LLM API. Nothing has been run in a browser.

## 6. Not done (open, in priority order)
1. **Phase 0: map the editor.** Read `js/anieditor.js` and fill EditorAdapter with real function names. Needed: snapshot, applyOps (one undo entry), loadGani in proposal mode, export render function, undo push, state-change hook. Verify WAIT timing against playback. Confirm `sword.gani` plays 250ms. Write the findings into this file under a "Phase 0 findings" section.
2. **Editor bridge.** Wire `ai-bridge/index.js` into the editor behind a feature flag (one import line). Implement the JSON-RPC client message handler and token read (Wails: via `window.__GSUITE__.fs.readTextFile` on the token file, or a service method).
3. **Real render.** Replace `HeadlessRenderer` with the editor's offscreen export renderer for `sheet()` and `raw()`.
4. **Corpus labels.** Run `gani-cli index` over the full `ganis/` set. Get one-time LLM descriptions. Review in bulk. Only then trust retrieval.
5. **Eval harness.** 20 held-out production slashes. Metrics: frame-count delta, total-ms delta, layer-order agreement, validator pass rate, metric violations. Every prompt or model change runs it.
6. **Agent panel UI** (prompt box, status, Accept, Reject, Refine). `ui.highlight` and `ui.status` during edits. Abort and re-snapshot on user edits (`state.changed by user`).
7. **Real critic loop test** against the live API with the pinned model (set `config.toml [llm].model`).
8. Later: other categories (walk, idle, reload, shoot, cast), sound suggestions, `sync.check` for upstream, training-data logging.
9. Last: the stealth mirror and private sync. The user asked to leave this for the end.

## 7. Known risks and open questions
- WAIT semantics: `(wait+1) x 50ms` is assumed. Unverified.
- Multi-sprite ids in the same gani can clash across sources. The sprite catalog keeps source names to disambiguate.
- Only one sprite-sheet image is loaded per session. Multi-sheet support is not done.
- `_isExportRender` suppresses sound icons. Make sure the export path doesn't pick up UI overlays.
- The `SPRITE` serializer uses fixed column widths. Round-trip is semantic (parse then serialize then parse gives the same AST), not byte-exact to upstream whitespace. Check before any writes back to user files.
- Model choice is not pinned. Set it in `config.toml`.
- Fake-LLM tests prove the plumbing, not output quality. The eval harness (item 5) is what proves quality.

## 8. Next action for the next agent
1. Run `python3 agent/tests/run_tests.py`. Confirm 18 pass.
2. Do Phase 0 (section 6, item 1). Record the real function names, then update `ai-bridge/EditorAdapter.js`.
3. Then items 2 and 3.

## 9. Local commands (run from the repo root)
    python3 agent/tests/run_tests.py
    cd agent && python3 -m gani_agent.cli check tests/fixtures/sword.gani
    cd agent && pip install -r requirements.txt && python3 -m gani_agent --port 8765
