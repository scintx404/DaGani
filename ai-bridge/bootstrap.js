import { initAiBridge } from "./index.js";

const TOKEN_PATH = ".gani-agent/token";

async function readToken() {
  const native = window.__GSUITE__;
  if (native?.core?.invoke) {
    const path = await native.core.invoke("get_gani_agent_token_path").catch(() => TOKEN_PATH);
    return native.fs.readTextFile(path).then((value) => value.trim()).catch(() => null);
  }
  return window.localStorage.getItem("ganiAgentToken")?.trim() || null;
}

function activeAnimation() {
  return window.tabManager?.getActiveTab?.()?.data?.ani || window.currentAnimation || null;
}

export async function startGaniAiBridge({ enabled = true } = {}) {
  if (!enabled || window.GANI_AI_ENABLED === false || window.ganiAiBridge) return window.ganiAiBridge || null;
  const bridge = initAiBridge({
    getAni: activeAnimation,
    setAni(ani) {
      const tab = window.tabManager?.getActiveTab?.();
      if (tab?.data) tab.data.ani = ani;
      window.currentAnimation = ani;
      window.redraw?.();
    },
    parseGani: window.parseGani,
    serializeGani: window.serializeGani,
    serializeAnimationState: window.serializeAnimationState,
    restoreAnimationState: window.restoreAnimationState,
    addUndoCommand: window.addUndoCommand,
    redraw: window.redraw,
    renderer: window.ganiAiRenderer,
  }, { readToken });
  window.ganiAiBridge = bridge;
  try {
    await bridge.connect();
    bridge.request("gani.snapshot", { snapshot: bridge.adapter.snapshot() }).catch(() => {});
  } catch (error) {
    console.info("[gani-ai] sidecar unavailable; editor continues normally");
  }
  return bridge;
}

window.startGaniAiBridge = startGaniAiBridge;
window.addEventListener("load", () => {
  const ready = () => typeof window.parseGani === "function" && typeof window.serializeAnimationState === "function";
  if (ready()) startGaniAiBridge();
  else {
    let tries = 0;
    const wait = () => { if (ready()) startGaniAiBridge(); else if (++tries < 120) setTimeout(wait, 50); };
    wait();
  }
});
