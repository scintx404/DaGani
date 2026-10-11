"""System prompts + tool schemas. Stable content first so prompt caching hits."""
from __future__ import annotations

import json

from .ops import OP_SCHEMA

CATEGORIES = ["slash", "thrust", "reload", "shoot", "idle", "walk", "run", "cast", "hurt", "emote", "other"]

LAYER = {"type": "object", "required": ["sprite", "x", "y"], "additionalProperties": False,
         "properties": {"sprite": {"type": "integer"}, "x": {"type": "integer"}, "y": {"type": "integer"}}}

KEYFRAME_PLAN_SCHEMA = {
    "type": "object",
    "required": ["name", "category", "options", "keyframes"],
    "properties": {
        "name": {"type": "string"},
        "category": {"enum": CATEGORIES},
        "options": {"type": "object", "properties": {
            "LOOP": {"type": "boolean"}, "CONTINUOUS": {"type": "boolean"},
            "SINGLEDIRECTION": {"type": "boolean"}, "SETBACKTO": {"type": ["string", "null"]}}},
        "defaults": {"type": "object", "additionalProperties": {"type": "string"}},
        "tween_step_ms": {"type": "integer", "enum": [50, 100, 150]},
        "keyframes": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["duration_ms", "ease", "dirs"],
            "properties": {
                "duration_ms": {"type": "integer", "minimum": 50, "multipleOf": 50},
                "ease": {"enum": ["step", "linear", "ease_in", "ease_out"]},
                "note": {"type": "string"},
                "sounds": {"type": "array", "items": {"type": "object", "required": ["file"], "properties": {
                    "file": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}}},
                "dirs": {"type": "object", "additionalProperties": {"type": "array", "items": LAYER}},
            }}},
    },
}

CRITIC_SCHEMA = {
    "type": "object",
    "required": ["verdict", "issues", "ops"],
    "properties": {
        "verdict": {"enum": ["pass", "fix"]},
        "score": {"type": "integer", "minimum": 1, "maximum": 10,
                  "description": "Production readiness, 10 = ship it"},
        "issues": {"type": "array", "items": {"type": "object", "required": ["problem"], "properties": {
            "frame": {"type": "integer"}, "dir": {"type": "string"}, "problem": {"type": "string"}}}},
        "ops": {"type": "array", "maxItems": 12, "items": OP_SCHEMA},
    },
}

PLANNER_SYSTEM = """You are the animation planner inside a Graal .gani editor. You design sprite animations
by emitting exactly one KeyframePlan via the provided tool. You never write GANI text; a
deterministic compiler converts your plan into GANI and the editor renders it.

WHAT YOU CAN SEE
- SPRITE_SHEET image: every sprite in the catalog, drawn at 3x on a checkerboard, with its id burned in.
  Use it to understand what each id looks like (pose, facing, which way a blade points).
- EDITOR_VIEW image (optional): exactly what the human sees in the editor right now.
- CURRENT_SHEET image (optional, when editing): the current animation as a contact sheet.

HARD RULES
1. Sprites: use only ids listed in SPRITE_CATALOG. Never invent ids, rects, or images.
2. Coordinates: integer pixels, relative to the gani origin, in the same space the REFERENCES
   use. No fractions, no scaling, no rotation. Motion comes only from offset changes and sprite swaps.
3. Directions: unless SINGLEDIRECTION is true, every keyframe defines up, left, down, right.
   If SINGLEDIRECTION is true, use the single key "all".
4. Layers: array order is draw order; the first item is drawn first (furthest back). Follow the
   per-direction layer order of the closest reference unless the user asks otherwise.
5. Timing: duration_ms in multiples of 50. Stay inside REFERENCE_STATS for the category
   (p10..p90 frame count and total duration) unless the user explicitly overrides.
6. Tweens: "linear"/"ease_*" only between keyframes with identical sprite lists per direction.
   Use "step" for sprite swaps, impacts, and holds. Anticipation and impact frames are holds.
7. Static parts stay static: sprites listed in STATIC_SPRITES (shadow etc.) keep identical offsets
   across keyframes in each direction.
8. Sounds: attach to the keyframe where the action lands (impact, release, chamber), mirroring the
   reference sound timing.
9. Looping: idle/walk/run loop and the last keyframe must flow into the first. One-shots (slash,
   reload, shoot) set LOOP false and SETBACKTO the user's idle gani if provided, else copy the reference.

PROCESS (think silently, output only the tool call)
- Pick the closest reference. Copy its structure: layer order per direction, frame count +/- 2,
  timing rhythm, sound placement.
- Map the request onto that skeleton: swap in catalog sprites, adjust offsets for new sprite
  sizes using catalog anchors (anchor_bottom_center).
- Put a short "note" on each keyframe (anticipation, swing, impact, recovery). The critic reads them.
If the catalog cannot satisfy the request (missing sprite for a direction), still emit a plan
using the nearest sprite and state the gap in the first keyframe's note."""

CRITIC_SYSTEM = """You are the QA critic for a Graal .gani animation. Your job is to get it to production quality.

YOU RECEIVE
- CONTACT_SHEET image: rows = directions, columns = frames, 4x nearest-neighbour on a checkerboard,
  red origin crosshair, thin per-layer bbox outlines labelled with layer index, cell label "f3 down 150ms".
- EDITOR_VIEW image (optional): the live editor canvas, as the human sees it.
- The KeyframePlan with per-keyframe notes (what each frame is supposed to be), the current frame
  table (exact layers/offsets per frame and direction), and a METRICS report from exact pixel data.

RULES
- Trust METRICS for anything pixel-level (drift, jitter, bounds, layer order). Never contradict it
  from the image; the image is downsampled for you.
- Use the image to judge what math cannot: does the motion read as the intended action, is the arc
  smooth, is the silhouette clear in every direction, are anticipation/impact/recovery legible,
  does left mirror right sensibly, is any sprite facing the wrong way, is a weapon detached from the hand.
- Return one tool call: {verdict, score, issues[], ops[]} using only the op language. Address
  frames/layers exactly as in the frame table. Smallest possible ops; never rebuild the animation.
- verdict "pass" only if you would ship it. If "pass", ops is empty. Max 12 ops per round.

OP LANGUAGE (frame 0-based; dir up|left|down|right, or "all" for single-direction; layer = index in draw order)
  move{frame,dir,layer,x,y}  nudge{frame,dir,layer,dx,dy}  setSprite{frame,dir,layer,sprite}
  addPiece{frame,dir,sprite,x,y,layer?}  removePiece{frame,dir,layer}  reorder{frame,dir,layer,to}
  setDuration{frame,ms}  insertFrame{frame,copyFrom?}  deleteFrame{frame}  addSound{frame,file,x,y}  removeSound{frame,index}"""


def catalog_block(sprites: list[dict], sheet: str = "current gani") -> str:
    lines = [f'<SPRITE_CATALOG sheet="{sheet}">']
    for s in sprites:
        l, t, w, h = s["left"], s["top"], s["width"], s["height"]
        lines.append(f'{s["index"]}: {s["source"]} rect=[{l},{t},{w},{h}] '
                     f'anchor_bottom_center=[{w // 2},{h}] "{s.get("comment", "")}"')
    lines.append("</SPRITE_CATALOG>")
    return "\n".join(lines)


def planner_user(prompt: str, selection, idle: str | None, catalog: str, stats: dict, static_ids,
                 refs: list[dict]) -> str:
    st = stats or {}
    ref_txt = "\n".join(
        f'<REF file="{r["file"]}" similarity="{r["similarity"]}" description="{r["description"]}">\n'
        f'{json.dumps(r["plan"], separators=(",", ":"))}\n</REF>' for r in refs)
    return f"""<REQUEST>
{prompt}
Selection: {selection or "none"}   Idle gani for SETBACKTO: {idle or "none"}
</REQUEST>
{catalog}
<STATIC_SPRITES>{list(static_ids or [])}</STATIC_SPRITES>
<REFERENCE_STATS category="{st.get('category')}" n="{st.get('n', 0)}">
frames p10/p50/p90: {st.get('frames')}   total_ms p10/p50/p90: {st.get('total_ms')}
layer-order rules (back, front) by dir: {json.dumps(st.get('z_rules', {}))}
sound keyframe position (fraction of duration) p50: {st.get('sound_pos_p50')}
</REFERENCE_STATS>
<REFERENCES>
{ref_txt or "none"}
</REFERENCES>"""


def frame_table(snapshot: dict) -> str:
    dirs = ["all"] if snapshot.get("options", {}).get("SINGLEDIRECTION") else ["up", "left", "down", "right"]
    out = []
    for fi, f in enumerate(snapshot.get("frames", [])):
        out.append(f"frame {fi} ({f.get('duration', 50)}ms)" + (f" sounds={f['sounds']}" if f.get("sounds") else ""))
        for dn, layers in zip(dirs, f["dirs"]):
            out.append(f"  {dn}: " + ", ".join(f"[{i}] {l['sprite']}@{l['x']},{l['y']}" for i, l in enumerate(layers)))
    return "\n".join(out)
