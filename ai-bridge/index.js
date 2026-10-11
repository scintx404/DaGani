import { EditorAdapter } from "./EditorAdapter.js";

const AGENT_URL = "ws://127.0.0.1:8765";

export function initAiBridge(deps, { enabled = true, url = AGENT_URL, token = null, readToken = null } = {}) {
  if (!enabled) return null;
  const adapter = new EditorAdapter(deps);
  let ws = null;
  let nextId = 1;
  let retry = null;
  let closedByUser = false;
  let authToken = token;
  const pending = new Map();
  const listeners = new Set();

  const emit = (message) => { for (const listener of listeners) listener(message); };

  function request(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        pending.delete(id);
        reject(new Error("AI sidecar is not connected"));
        return;
      }
      ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  function notify(method, params = {}) {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ jsonrpc: "2.0", method, params }));
  }

  async function connect() {
    if (closedByUser || ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;
    if (!authToken && typeof readToken === "function") authToken = await readToken();
    if (!authToken) throw new Error("AI sidecar token is missing");
    ws = new WebSocket(url);
    ws.onopen = () => ws.send(JSON.stringify({ auth: authToken }));
    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      if (msg.id !== undefined && pending.has(msg.id)) {
        const call = pending.get(msg.id); pending.delete(msg.id);
        if (msg.error) call.reject(Object.assign(new Error(msg.error.message || "RPC error"), { code: msg.error.code, data: msg.error.data }));
        else call.resolve(msg.result);
      } else {
        emit(msg);
        if (msg.method === "state.changed" && msg.params?.by === "user") adapter._onStateChange(msg.params);
      }
    };
    ws.onerror = () => emit({ method: "bridge.error" });
    ws.onclose = () => {
      for (const call of pending.values()) call.reject(new Error("AI sidecar disconnected"));
      pending.clear();
      ws = null;
      if (!closedByUser) retry = setTimeout(() => connect().catch(() => {}), 2000);
    };
  }

  function disconnect() {
    closedByUser = true;
    if (retry) clearTimeout(retry);
    for (const call of pending.values()) call.reject(new Error("AI bridge closed"));
    pending.clear();
    ws?.close();
    ws = null;
  }

  return {
    adapter,
    connect,
    disconnect,
    request,
    notify,
    onMessage(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    setToken(value) { authToken = value; },
    isConnected() { return ws?.readyState === WebSocket.OPEN; },
  };
}
