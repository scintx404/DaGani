"""KeyframePlan <-> GaniDoc.

The planner LLM only ever emits a KeyframePlan (JSON). This module turns it into
frames deterministically: tween -> quantize to 50ms ticks -> integer pixels.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .gani import DIRS, TICK_MS, Frame, GaniDoc, Piece, Sound, ms_to_wait

EASES = {
    "step": None,
    "linear": lambda t: t,
    "ease_in": lambda t: t * t,
    "ease_out": lambda t: 1 - (1 - t) * (1 - t),
}


@dataclass
class PlanError(Exception):
    errors: list[str] = field(default_factory=list)

    def __str__(self):
        return "; ".join(self.errors)


def _dir_keys(single: bool) -> list[str]:
    return ["all"] if single else list(DIRS)


def validate_plan(plan: dict, catalog_ids: set[int]) -> list[str]:
    """Return a list of human/LLM-readable errors. Empty list = valid."""
    errs: list[str] = []
    opts = plan.get("options", {}) or {}
    single = bool(opts.get("SINGLEDIRECTION"))
    keys = _dir_keys(single)
    kfs = plan.get("keyframes") or []
    if not kfs:
        errs.append("plan has no keyframes")
    step = int(plan.get("tween_step_ms", TICK_MS) or TICK_MS)
    if step % TICK_MS:
        errs.append(f"tween_step_ms {step} is not a multiple of {TICK_MS}")
    for i, kf in enumerate(kfs):
        d = kf.get("duration_ms", 0)
        if not isinstance(d, int) or d < TICK_MS or d % TICK_MS:
            errs.append(f"keyframe {i}: duration_ms {d} must be a positive multiple of {TICK_MS}")
        if kf.get("ease", "step") not in EASES:
            errs.append(f"keyframe {i}: unknown ease {kf.get('ease')}")
        dirs = kf.get("dirs") or {}
        for k in keys:
            if k not in dirs:
                errs.append(f"keyframe {i}: missing direction '{k}'")
        for k in dirs:
            if k not in keys:
                errs.append(f"keyframe {i}: unexpected direction key '{k}' (expected {keys})")
        for k, layers in dirs.items():
            for j, layer in enumerate(layers or []):
                sid = layer.get("sprite")
                if not isinstance(sid, int) or sid not in catalog_ids:
                    errs.append(f"keyframe {i} dir {k} layer {j}: sprite {sid} is not in SPRITE_CATALOG")
                for c in ("x", "y"):
                    if not isinstance(layer.get(c), int):
                        errs.append(f"keyframe {i} dir {k} layer {j}: {c} must be an integer")
        ease = kf.get("ease", "step")
        if ease != "step" and i + 1 < len(kfs):
            nxt = kfs[i + 1].get("dirs") or {}
            for k in keys:
                a = [l.get("sprite") for l in dirs.get(k, [])]
                b = [l.get("sprite") for l in nxt.get(k, [])]
                if a != b:
                    errs.append(f"keyframe {i}: ease '{ease}' requires identical sprite lists in dir {k} "
                                f"as keyframe {i+1} (got {a} vs {b}); use 'step' for sprite swaps")
    return errs


def compile_plan(plan: dict, base: GaniDoc, catalog_ids: set[int] | None = None) -> GaniDoc:
    """Compile a KeyframePlan into a new GaniDoc that keeps base's sprites/defaults/script."""
    ids = catalog_ids if catalog_ids is not None else {s.index for s in base.sprites}
    errs = validate_plan(plan, ids)
    if errs:
        raise PlanError(errs)

    doc = copy.deepcopy(base)
    opts = plan.get("options", {}) or {}
    flags = [f for f in ("LOOP", "CONTINUOUS", "SINGLEDIRECTION") if opts.get(f)]
    doc.flags = flags
    if "SETBACKTO" in opts:
        doc.setbackto = opts.get("SETBACKTO") or None
    for k, v in (plan.get("defaults") or {}).items():
        doc.defaults[k.upper().removeprefix("DEFAULT")] = v
    single = "SINGLEDIRECTION" in flags
    keys = _dir_keys(single)
    step = int(plan.get("tween_step_ms", TICK_MS) or TICK_MS)
    kfs = plan["keyframes"]
    frames: list[Frame] = []

    def make_frame(kf_dirs: dict, ms: int, sounds) -> Frame:
        dirs = [[Piece(str(l["sprite"]), int(l["x"]), int(l["y"])) for l in kf_dirs.get(k, [])] for k in keys]
        return Frame(dirs=dirs, wait=ms_to_wait(ms),
                     sounds=[Sound(s["file"], s.get("x", 0), s.get("y", 0)) for s in (sounds or [])])

    for i, kf in enumerate(kfs):
        ease = kf.get("ease", "step")
        dur = kf["duration_ms"]
        nxt = kfs[i + 1] if i + 1 < len(kfs) else (kfs[0] if opts.get("LOOP") else None)
        fn = EASES.get(ease)
        if fn is None or nxt is None or dur < 2 * step:
            frames.append(make_frame(kf["dirs"], dur, kf.get("sounds")))
            continue
        n = dur // step
        rem = dur - n * step
        for s in range(n):
            t = fn(s / n)
            dirs = {}
            for k in keys:
                a, b = kf["dirs"].get(k, []), nxt["dirs"].get(k, [])
                dirs[k] = [{"sprite": la["sprite"],
                            "x": int(round(la["x"] + (lb["x"] - la["x"]) * t)),
                            "y": int(round(la["y"] + (lb["y"] - la["y"]) * t))} for la, lb in zip(a, b)]
            ms = step + (rem if s == n - 1 else 0)
            frames.append(make_frame(dirs, ms, kf.get("sounds") if s == 0 else None))
    doc.frames = frames
    return doc


def doc_to_plan(doc: GaniDoc, name: str = "", category: str = "other") -> dict:
    """Convert an existing gani into the compact KeyframePlan shape (used for RAG references)."""
    keys = _dir_keys(doc.single_dir)
    kfs = []
    for f in doc.frames:
        dirs = {}
        for k, pieces in zip(keys, f.dirs):
            dirs[k] = [{"sprite": p.sprite_id if p.sprite_id is not None else p.sprite,
                        "x": int(round(p.x)), "y": int(round(p.y))} for p in pieces]
        kf = {"duration_ms": f.duration_ms, "ease": "step", "dirs": dirs}
        if f.sounds:
            kf["sounds"] = [{"file": s.file, "x": s.x, "y": s.y} for s in f.sounds]
        kfs.append(kf)
    return {
        "name": name, "category": category,
        "options": {"LOOP": doc.loop, "CONTINUOUS": "CONTINUOUS" in doc.flags,
                    "SINGLEDIRECTION": doc.single_dir, "SETBACKTO": doc.setbackto},
        "keyframes": kfs,
    }
