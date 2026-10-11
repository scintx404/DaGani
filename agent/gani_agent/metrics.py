"""Pixel/geometry QA. Math catches what vision models can't see (1-2px errors).

Inputs: a GaniDoc (+ optional raw pixel metrics from the editor's metrics.raw).
Output: a report {issues: [...], per_cell: [...]} and deterministic auto-fix ops.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .gani import DIRS, GaniDoc

DEFAULT_BOUNDS = {"min_x": -48, "min_y": -64, "max_x": 96, "max_y": 96}


def _dir_name(doc, d):
    return "all" if doc.single_dir else DIRS[d]


def piece_rect(doc: GaniDoc, piece, smap):
    s = smap.get(piece.sprite_id) if piece.sprite_id is not None else None
    w, h = (s.width, s.height) if s else (16, 16)
    return (piece.x, piece.y, piece.x + w, piece.y + h)


def compute(doc: GaniDoc, raw: dict | None = None, static_ids: set[int] | None = None,
            z_priors: dict | None = None, bounds: dict | None = None) -> dict:
    smap = doc.sprite_map()
    b = {**DEFAULT_BOUNDS, **(bounds or {})}
    issues: list[dict] = []
    cells: list[dict] = []
    static_ids = set(static_ids or ())

    for fi, fr in enumerate(doc.frames):
        for d, pieces in enumerate(fr.dirs):
            dn = _dir_name(doc, d)
            if not pieces:
                issues.append({"severity": "warn", "kind": "empty_dir", "frame": fi, "dir": dn,
                               "problem": "direction has no pieces"})
                continue
            rects = []
            for li, p in enumerate(pieces):
                if p.sprite_id is not None and p.sprite_id not in smap:
                    issues.append({"severity": "error", "kind": "missing_sprite", "frame": fi, "dir": dn,
                                   "layer": li, "problem": f"sprite {p.sprite} is not defined"})
                if p.x != int(p.x) or p.y != int(p.y):
                    issues.append({"severity": "warn", "kind": "subpixel", "frame": fi, "dir": dn,
                                   "layer": li, "problem": f"non-integer offset {p.x},{p.y}"})
                rects.append(piece_rect(doc, p, smap))
            ux0, uy0 = min(r[0] for r in rects), min(r[1] for r in rects)
            ux1, uy1 = max(r[2] for r in rects), max(r[3] for r in rects)
            cell = {"frame": fi, "dir": dn, "bbox": [ux0, uy0, ux1 - ux0, uy1 - uy0], "layers": len(pieces)}
            cells.append(cell)
            if ux0 < b["min_x"] or uy0 < b["min_y"] or ux1 > b["max_x"] or uy1 > b["max_y"]:
                issues.append({"severity": "warn", "kind": "out_of_bounds", "frame": fi, "dir": dn,
                               "problem": f"union bbox {cell['bbox']} exceeds {b}"})
        if fr.duration_ms % 50:
            issues.append({"severity": "warn", "kind": "timing", "frame": fi, "problem": "duration not on 50ms grid"})

    # --- per (dir, sprite id) trajectories
    traj: dict[tuple[int, int], list[tuple[int, int, float, float]]] = defaultdict(list)
    for fi, fr in enumerate(doc.frames):
        for d, pieces in enumerate(fr.dirs):
            for li, p in enumerate(pieces):
                if p.sprite_id is not None:
                    traj[(d, p.sprite_id)].append((fi, li, p.x, p.y))

    fixes: list[dict] = []
    for (d, sid), pts in traj.items():
        dn = _dir_name(doc, d)
        # static sprites must not move at all
        if sid in static_ids and len(pts) > 1:
            mode = Counter((x, y) for _, _, x, y in pts).most_common(1)[0][0]
            for fi, li, x, y in pts:
                if (x, y) != mode:
                    issues.append({"severity": "error", "kind": "static_drift", "frame": fi, "dir": dn, "layer": li,
                                   "problem": f"static sprite {sid} at {x},{y}, expected {mode[0]},{mode[1]}"})
                    fixes.append({"op": "move", "frame": fi, "dir": dn, "layer": li, "x": int(mode[0]),
                                  "y": int(mode[1]), "reason": "snap static sprite"})
        # 1px A-B-A oscillation across consecutive frames
        for (f0, _, x0, y0), (f1, l1, x1, y1), (f2, _, x2, y2) in zip(pts, pts[1:], pts[2:]):
            if f1 != f0 + 1 or f2 != f1 + 1:
                continue
            if (x0, y0) == (x2, y2) and (x1, y1) != (x0, y0) and abs(x1 - x0) <= 1 and abs(y1 - y0) <= 1:
                issues.append({"severity": "warn", "kind": "jitter_1px", "frame": f1, "dir": dn, "layer": l1,
                               "problem": f"sprite {sid} wobbles 1px ({x0},{y0})->({x1},{y1})->({x2},{y2})"})
                if sid not in static_ids:
                    fixes.append({"op": "move", "frame": f1, "dir": dn, "layer": l1, "x": int(x0), "y": int(y0),
                                  "reason": "remove 1px oscillation"})

    # --- z-order priors: strong pairwise rules {dir: [[back_source, front_source], ...]}
    if z_priors:
        for fi, fr in enumerate(doc.frames):
            for d, pieces in enumerate(fr.dirs):
                dn = _dir_name(doc, d)
                order = [smap[p.sprite_id].source for p in pieces if p.sprite_id in smap]
                pos = {}
                for i, src in enumerate(order):
                    pos.setdefault(src, i)
                for back, front in z_priors.get(dn, []):
                    if back in pos and front in pos and pos[back] > pos[front]:
                        issues.append({"severity": "warn", "kind": "z_order", "frame": fi, "dir": dn,
                                       "problem": f"{front} is drawn behind {back}; references almost always draw it in front"})

    # --- pixel metrics from the editor (exact alpha data)
    if raw:
        by = {(c["frame"], c["dir"]): c for c in raw.get("cells", [])}
        for (fi, dn), c in by.items():
            if c.get("opaque_px", 1) == 0:
                issues.append({"severity": "error", "kind": "invisible", "frame": fi, "dir": dn,
                               "problem": "nothing visible rendered (missing image?)"})
            if c.get("missing_images"):
                issues.append({"severity": "error", "kind": "missing_image", "frame": fi, "dir": dn,
                               "problem": f"images not loaded: {c['missing_images']}"})
        for dn in {k[1] for k in by}:
            seq = sorted((k[0], v) for k, v in by.items() if k[1] == dn)
            for (fa, a), (fb, bb) in zip(seq, seq[1:]):
                ca, cb = a.get("centroid"), bb.get("centroid")
                if ca and cb:
                    jump = ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5
                    if jump > 10:
                        issues.append({"severity": "info", "kind": "centroid_jump", "frame": fb, "dir": dn,
                                       "problem": f"visual centre jumps {jump:.1f}px from frame {fa}"})

    sev = Counter(i["severity"] for i in issues)
    return {"summary": dict(sev), "issues": issues, "cells": cells, "autofix_ops": _dedupe(fixes),
            "frames": len(doc.frames), "total_ms": doc.total_ms()}


def _dedupe(ops):
    seen, out = set(), []
    for o in ops:
        k = (o["frame"], o["dir"], o["layer"])
        if k not in seen:
            seen.add(k)
            out.append(o)
    return out


def static_ids_from_refs(docs: list[GaniDoc]) -> set[int]:
    """Sprite ids whose position never changes (per dir) in every reference that uses them."""
    moving, seen = set(), set()
    for doc in docs:
        pos = defaultdict(set)
        for fr in doc.frames:
            for d, pieces in enumerate(fr.dirs):
                for p in pieces:
                    if p.sprite_id is not None:
                        pos[(d, p.sprite_id)].add((p.x, p.y))
        for (d, sid), s in pos.items():
            seen.add(sid)
            if len(s) > 1:
                moving.add(sid)
    # a sprite that appears in only one frame isn't evidence of being static
    multi = set()
    for doc in docs:
        c = Counter(p.sprite_id for fr in doc.frames for d in fr.dirs for p in d)
        multi |= {k for k, v in c.items() if v > 1}
    return (seen - moving) & multi


def z_priors_from_refs(docs: list[GaniDoc], min_ratio: float = 0.9, min_samples: int = 4) -> dict:
    """Pairwise layer-order rules that hold in >= min_ratio of reference frames, per direction."""
    out = {}
    for d in range(4):
        before = Counter()
        for doc in docs:
            if doc.single_dir:
                continue
            smap = doc.sprite_map()
            for fr in doc.frames:
                order = []
                for p in fr.dirs[d]:
                    s = smap.get(p.sprite_id)
                    if s and s.source not in order:
                        order.append(s.source)
                for i, a in enumerate(order):
                    for b in order[i + 1:]:
                        before[(a, b)] += 1
        rules = []
        for (a, b), n in before.items():
            rev = before.get((b, a), 0)
            if n >= min_samples and n / (n + rev) >= min_ratio:
                rules.append([a, b])
        out[DIRS[d]] = sorted(rules)
    return out
