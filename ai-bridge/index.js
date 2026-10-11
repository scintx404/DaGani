// Single import point. The upstream editor imports this file once (one line in anieditor.js),
// guarded by the feature flag so the rest of the fork stays untouched.
import { EditorAdapter } from "./EditorAdapter.js";

const AGENT_URL = "ws://127.0.0.1:8765";

export function initAiBridge(deps, { enabled = true } = {}) {
  if (!enabled) return null;
  const adapter = new EditorAdapter(deps);
  let ws = null;
  let token = null; // read from the local token file via the native shell

  function connect() {
    ws = new WebSocket(AGENT_URL);
    ws.onopen = () => ws.send(JSON.stringify({ auth: token }));
    ws.onmessage = e => handle(JSON.parse(e.data));
    ws.onclose = () => setTimeout(connect, 2000);
  }

  function handle(msg) {
    // JSON-RPC responses/notifications are routed by id; implemented with the router in Phase 1.
  }

  return { adapter, connect, setToken: t => { token = t; } };
}
