"""The op language shared by the critic LLM, the auto-fixer and the editor bridge.

Every op addresses frame (0-based), dir ("up"|"left"|"down"|"right"|"all" or 0..3)
and layer (index in that direction's draw order, 0 = furthest back).
The editor applies ops for real (ai-bridge/EditorAdapter.js); this module applies
them to a GaniDoc so we can validate + measure *before* touching the editor.
"""
from __future__ import annotations

import copy

from .gani import DIRS, GaniDoc, Frame, Piece, Sound, ms_to_wait

OP_SCHEMA = {
    "type": "object",
    "required": ["op"],
    "properties": {
        "op": {"enum": ["move", "nudge", "setSprite", "addPiece", "removePiece", "reorder",
                        "setDuration", "insertFrame", "deleteFrame", "addSound", "removeSound"]},
        "frame": {"type": "integer", "minimum": 0},
        "dir": {"type": "string", "enum": DIRS + ["all"]},
        "layer": {"type": "integer", "minimum": 0},
        "to": {"type": "integer", "minimum": 0},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "dx": {"type": "integer"}, "dy": {"type": "integer"},
        "sprite": {"type": "integer"},
        "ms": {"type": "integer", "minimum": 50, "multipleOf": 50},
        "copyFrom": {"type": "integer", "minimum": 0},
        "file": {"type": "string"},
        "index": {"type": "integer", "minimum": 0},
        "reason": {"type": "string"},
    },
}


def dir_index(doc: GaniDoc, d) -> int:
    if doc.single_dir:
        return 0
    if isinstance(d, int):
        return d
    if d == "all":
        raise OpError("dir 'all' is only valid for SINGLEDIRECTION ganis")
    return DIRS.index(d)


class OpError(ValueError):
    pass


def apply_ops(doc: GaniDoc, ops: list[dict], catalog_ids: set[int] | None = None) -> GaniDoc:
    """Apply ops to a copy of doc. Raises OpError on the first invalid op (atomic)."""
    out = copy.deepcopy(doc)
    ids = catalog_ids if catalog_ids is not None else {s.index for s in out.sprites}
    for n, op in enumerate(ops):
        try:
            _apply(out, op, ids)
        except (IndexError, KeyError, ValueError) as e:
            raise OpError(f"op #{n} {op}: {e}") from None
    return out


def _layer(doc, op):
    fr = doc.frames[op["frame"]]
    d = dir_index(doc, op.get("dir", "all"))
    pieces = fr.dirs[d]
    li = op.get("layer", 0)
    if li >= len(pieces):
        raise OpError(f"layer {li} does not exist (dir has {len(pieces)} layers)")
    return fr, d, pieces, li


def _apply(doc: GaniDoc, op: dict, ids: set[int]):
    kind = op["op"]
    if kind == "move":
        _, _, pieces, li = _layer(doc, op)
        pieces[li].x, pieces[li].y = int(op["x"]), int(op["y"])
    elif kind == "nudge":
        _, _, pieces, li = _layer(doc, op)
        pieces[li].x += int(op.get("dx", 0))
        pieces[li].y += int(op.get("dy", 0))
    elif kind == "setSprite":
        if op["sprite"] not in ids:
            raise OpError(f"sprite {op['sprite']} not in catalog")
        _, _, pieces, li = _layer(doc, op)
        pieces[li].sprite = str(op["sprite"])
    elif kind == "addPiece":
        if op["sprite"] not in ids:
            raise OpError(f"sprite {op['sprite']} not in catalog")
        fr = doc.frames[op["frame"]]
        d = dir_index(doc, op.get("dir", "all"))
        at = op.get("layer", len(fr.dirs[d]))
        fr.dirs[d].insert(at, Piece(str(op["sprite"]), int(op["x"]), int(op["y"])))
    elif kind == "removePiece":
        _, _, pieces, li = _layer(doc, op)
        pieces.pop(li)
    elif kind == "reorder":
        _, _, pieces, li = _layer(doc, op)
        p = pieces.pop(li)
        pieces.insert(min(int(op["to"]), len(pieces)), p)
    elif kind == "setDuration":
        doc.frames[op["frame"]].wait = ms_to_wait(int(op["ms"]))
    elif kind == "insertFrame":
        at = int(op.get("frame", len(doc.frames)))
        src = op.get("copyFrom")
        fr = copy.deepcopy(doc.frames[src]) if src is not None else Frame(dirs=[[] for _ in range(doc.ndirs)])
        doc.frames.insert(at, fr)
    elif kind == "deleteFrame":
        if len(doc.frames) <= 1:
            raise OpError("cannot delete the last frame")
        doc.frames.pop(op["frame"])
    elif kind == "addSound":
        doc.frames[op["frame"]].sounds.append(Sound(op["file"], op.get("x", 0), op.get("y", 0)))
    elif kind == "removeSound":
        doc.frames[op["frame"]].sounds.pop(op.get("index", 0))
    else:
        raise OpError(f"unknown op {kind}")
