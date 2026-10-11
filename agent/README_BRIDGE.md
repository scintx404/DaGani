# Bridge integration

The editor-side bridge lives in `js/ai-bridge/`. It uses the active GANI tab (`tabManager.getActiveTab().data.ani`), validates operations atomically before writing, and exposes JSON-RPC methods for snapshots, edits, transactions, renders, metrics, and the Phase 0 probe.

Enable with `localStorage.ganiAgent = "1"` or `?agent=1`, then start the local sidecar on port 8765. The bridge is intentionally not imported into upstream `anieditor.js` yet: the probe must confirm the final undo and export hooks before that one-line integration is committed.
