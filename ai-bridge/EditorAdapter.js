// The only bridge module that knows GANI editor internals.
// Keep the rest of the AI sidecar editor-agnostic.

const DIRS = ["up", "left", "down", "right"];

export class EditorAdapter {
  constructor({
    getAni,
    setAni,
    parseGani,
    serializeGani,
    serializeAnimationState,
    restoreAnimationState,
    addUndoCommand,
    redraw,
    renderer,
    onStateChange,
  }) {
    this.getAni = getAni;
    this.setAni = setAni || (() => {});
    this.parseGani = parseGani;
    this.serializeGani = serializeGani;
    this.serializeAnimationState = serializeAnimationState;
    this.restoreAnimationState = restoreAnimationState;
    this.addUndoCommand = addUndoCommand;
    this.redraw = redraw || (() => {});
    this.renderer = renderer || {};
    this.rev = 0;
    this._unsubscribe = onStateChange ? onStateChange((event) => this._onStateChange?.(event)) : null;
  }

  _onStateChange = () => {};

  setStateListener(callback) {
    this._onStateChange = typeof callback === "function" ? callback : () => {};
    return () => { this._onStateChange = () => {}; };
  }

  _dirs(ani) { return ani.singleDir ? ["all"] : DIRS; }

  _dirIndex(ani, dir) {
    if (ani.singleDir) return 0;
    if (typeof dir === "number") {
      if (dir < 0 || dir > 3) throw new Error(`invalid direction ${dir}`);
      return dir;
    }
    if (dir === "all") throw new Error("dir 'all' requires SINGLEDIRECTION");
    const index = DIRS.indexOf(dir || "down");
    if (index < 0) throw new Error(`invalid direction ${dir}`);
    return index;
  }

  snapshot() {
    const ani = this.getAni();
    if (!ani) throw new Error("no active animation");
    const dirs = this._dirs(ani);
    return {
      rev: this.rev,
      name: ani.fileName || "",
      options: {
        LOOP: !!ani.looped,
        CONTINUOUS: !!ani.continous,
        SINGLEDIRECTION: !!ani.singleDir,
        SETBACKTO: ani.nextAni || null,
      },
      defaults: Object.fromEntries(ani.defaultImages ? [...ani.defaultImages] : []),
      sprites: [...(ani.sprites?.values?.() || [])].map((s) => ({
        index: s.index, source: s.type, left: s.left, top: s.top,
        width: s.width, height: s.height, comment: s.comment || "",
      })),
      frames: (ani.frames || []).map((frame) => ({
        duration: frame.duration,
        sounds: (frame.sounds || []).map((s) => ({ file: s.fileName, x: s.xoffset, y: s.yoffset })),
        dirs: dirs.map((_, d) => (frame.pieces[d] || []).filter((p) => p.type === "sprite").map((p) => ({
          sprite: p.spriteIndex, x: p.xoffset, y: p.yoffset,
        }))),
      })),
    };
  }

  _piece(frame, dir, layer) {
    const pieces = frame.pieces[dir] || [];
    if (!Number.isInteger(layer) || layer < 0 || layer >= pieces.length) {
      throw new Error(`layer ${layer} does not exist`);
    }
    return { pieces, piece: pieces[layer], layer };
  }

  _applyOne(ani, op) {
    const frameIndex = Number(op.frame);
    if (!Number.isInteger(frameIndex) || !ani.frames[frameIndex]) throw new Error(`invalid frame ${op.frame}`);
    const frame = ani.frames[frameIndex];
    const dir = this._dirIndex(ani, op.dir);
    const kind = op.op;

    if (kind === "setDuration") {
      if (op.ms < 50 || op.ms % 50) throw new Error("duration must be a multiple of 50ms");
      frame.duration = Number(op.ms);
      return;
    }
    if (kind === "insertFrame") {
      const source = Number.isInteger(op.copyFrom) ? ani.frames[op.copyFrom]?.duplicate() : null;
      ani.frames.splice(frameIndex, 0, source || new frame.constructor());
      return;
    }
    if (kind === "deleteFrame") {
      if (ani.frames.length <= 1) throw new Error("cannot delete the last frame");
      ani.frames.splice(frameIndex, 1);
      return;
    }
    if (kind === "addSound") {
      const sound = new (frame.sounds[0]?.constructor || Object)();
      Object.assign(sound, { fileName: String(op.file || ""), xoffset: Number(op.x || 0), yoffset: Number(op.y || 0) });
      frame.sounds.push(sound);
      return;
    }
    if (kind === "removeSound") {
      if (!frame.sounds?.length) throw new Error("frame has no sounds");
      frame.sounds.splice(Number(op.index || 0), 1);
      return;
    }

    const { pieces, piece, layer } = this._piece(frame, dir, Number(op.layer));
    if (kind === "move") { piece.xoffset = Number(op.x); piece.yoffset = Number(op.y); return; }
    if (kind === "nudge") { piece.xoffset += Number(op.dx || 0); piece.yoffset += Number(op.dy || 0); return; }
    if (kind === "setSprite") {
      const sprite = ani.getAniSprite(Number(op.sprite), "");
      if (!sprite) throw new Error(`sprite ${op.sprite} does not exist`);
      piece.spriteIndex = Number(op.sprite); piece.spriteName = ""; return;
    }
    if (kind === "removePiece") { pieces.splice(layer, 1); return; }
    if (kind === "reorder") {
      const [moving] = pieces.splice(layer, 1);
      pieces.splice(Math.max(0, Math.min(Number(op.to), pieces.length)), 0, moving);
      return;
    }
    if (kind === "addPiece") {
      const sprite = ani.getAniSprite(Number(op.sprite), "");
      if (!sprite) throw new Error(`sprite ${op.sprite} does not exist`);
      const pieceType = pieces[0]?.constructor;
      if (!pieceType) throw new Error("cannot infer sprite piece type for empty layer");
      const next = new pieceType();
      next.spriteIndex = Number(op.sprite); next.xoffset = Number(op.x || 0); next.yoffset = Number(op.y || 0);
      pieces.splice(Math.max(0, Math.min(Number(op.layer), pieces.length)), 0, next);
      return;
    }
    throw new Error(`unknown op ${kind}`);
  }

  applyOps(ops, { description = "AI animation edit" } = {}) {
    if (!Array.isArray(ops) || !ops.length) return this.snapshot();
    if (!this.serializeAnimationState || !this.restoreAnimationState || !this.addUndoCommand) {
      throw new Error("editor undo hooks are not wired");
    }
    const oldState = this.serializeAnimationState();
    const ani = this.getAni();
    try {
      for (const op of ops) this._applyOne(ani, op);
      this.setAni(ani);
      this.redraw();
      const newState = this.serializeAnimationState();
      this.addUndoCommand({ description, oldState, newState,
        undo: () => this.restoreAnimationState(oldState),
        redo: () => this.restoreAnimationState(newState) });
      this.rev += 1;
      return this.snapshot();
    } catch (error) {
      this.restoreAnimationState(oldState);
      throw error;
    }
  }

  loadGani(text) {
    const ani = this.parseGani(text);
    if (!ani) throw new Error("editor parser returned no animation");
    this.setAni(ani);
    this.redraw();
    this.rev += 1;
    return this.snapshot();
  }

  validateGani(text) {
    const parsed = this.parseGani(text);
    return { ok: !!parsed, text: parsed ? this.serializeGani(parsed) : null };
  }

  renderFrames(options = {}) {
    if (typeof this.renderer.frames !== "function") throw new Error("export renderer is not wired");
    return this.renderer.frames(this.getAni(), { ...options, scale: options.scale || 4, nearest: true });
  }

  renderSheet(options = {}) {
    if (typeof this.renderer.sheet !== "function") throw new Error("export renderer is not wired");
    return this.renderer.sheet(this.getAni(), { ...options, scale: options.scale || 4, nearest: true });
  }
}
