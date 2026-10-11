// EditorAdapter: the ONLY file that knows editor internals.
// Every op goes through the same functions the UI calls, so undo/redo and live preview just work.
//
// Phase 0 TODO (needs the editor functions, mapped from js/anieditor.js):
//   snapshot()        -> { options, defaults, sprites[], frames[{duration, sounds, dirs}] }
//   applyOps(ops)     -> applies a batch in ONE undo entry (use addUndoCommand / the transaction helper)
//   loadGani(text)    -> parseGani(text) then a proposal-mode load (not committed to disk)
//   renderFrames(opts)-> frame PNGs via the export renderer (same code as GIF/MP4 export), 4x nearest
//   metricsRaw()      -> per-cell alpha coverage / centroid from the exact render
//   sheetImage()      -> sprite sheet with ids burned in (for the planner's SPRITE_SHEET image)
//   onUserEdit(cb)    -> hook for state.changed {by:"user"} so the agent aborts and re-snapshots
//
// Names below are placeholders until Phase 0 maps the real function names.

export class EditorAdapter {
  constructor({ getAni, setAni, parseGani, serializeGani, addUndoCommand, renderer }) {
    this.getAni = getAni;                 // () => current Animation
    this.setAni = setAni;                 // (ani) => void, rebuilds the view
    this.parseGani = parseGani;           // text -> Animation (the editor's own parser)
    this.serializeGani = serializeGani;   // Animation -> text
    this.addUndoCommand = addUndoCommand; // one undo entry per batch
    this.renderer = renderer;             // export renderer on OffscreenCanvas
    this.rev = 0;                         // bumped on every mutation; sent as base_rev
  }

  snapshot() {
    const ani = this.getAni();
    const dirs = ani.singleDir ? ["all"] : ["up", "left", "down", "right"];
    return {
      rev: this.rev,
      options: { LOOP: !!ani.looped, CONTINUOUS: !!ani.continous, SINGLEDIRECTION: !!ani.singleDir, SETBACKTO: ani.nextAni || null },
      defaults: Object.fromEntries(ani.defaultImages ? [...ani.defaultImages] : []),
      sprites: [...ani.sprites.values()].map(s => ({ index: s.index, source: s.type, left: s.left, top: s.top, width: s.width, height: s.height, comment: s.comment })),
      frames: ani.frames.map(f => ({
        duration: f.duration,
        sounds: (f.sounds || []).map(s => ({ file: s.fileName, x: s.xoffset, y: s.yoffset })),
        dirs: dirs.map((_, d) => (f.pieces[d] || []).map(p => ({ sprite: p.spriteIndex, x: p.xoffset, y: p.yoffset }))),
      })),
    };
  }

  // ops use the same language as agent/gani_agent/ops.py. Implement each op with the editor's mutators.
  applyOps(ops) {
    throw new Error("applyOps: not implemented until Phase 0 maps the editor mutators");
  }
}
