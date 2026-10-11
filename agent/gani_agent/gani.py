"""GANI parser / serializer.

The AST (GaniDoc) is the single source of truth on the Python side. Rules:
  * parse(serialize(doc)) == doc for every file in the library (golden test).
  * Anything we do not understand is kept verbatim (doc.extra / doc.script) so
    nothing is ever silently dropped.
  * Direction order in files and in Frame.dirs is always: up, left, down, right.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

DIRS = ["up", "left", "down", "right"]
TICK_MS = 50  # one GANI tick. WAIT n => frame lasts (n + 1) ticks.  # verify vs editor playback (Phase 0)

KNOWN_FLAGS = ("LOOP", "CONTINUOUS", "SINGLEDIRECTION")


@dataclass
class SpriteDef:
    index: int
    source: str            # BODY / HEAD / SWORD / SHIELD / ATTR1 / SPRITES / some.png ...
    left: int
    top: int
    width: int
    height: int
    comment: str = ""


@dataclass
class Piece:
    sprite: str            # numeric id as string, or a sprite name (editor supports both)
    x: float
    y: float
    extra: list[str] = field(default_factory=list)   # editor extension fields (xscale yscale rotation zoom)

    @property
    def sprite_id(self) -> Optional[int]:
        try:
            return int(self.sprite)
        except ValueError:
            return None


@dataclass
class Sound:
    file: str
    x: float = 0.0
    y: float = 0.0


@dataclass
class Frame:
    dirs: list[list[Piece]]         # 4 lists, or 1 when SINGLEDIRECTION
    wait: int = 0                   # extra ticks
    sounds: list[Sound] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)   # unknown per-frame lines, verbatim

    @property
    def duration_ms(self) -> int:
        return (self.wait + 1) * TICK_MS


@dataclass
class GaniDoc:
    header: Optional[str] = None
    sprites: list[SpriteDef] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)          # LOOP / CONTINUOUS / SINGLEDIRECTION in file order
    setbackto: Optional[str] = None
    defaults: dict[str, str] = field(default_factory=dict)  # DEFAULTBODY -> body.png (key without DEFAULT prefix)
    extra: list[str] = field(default_factory=list)          # unknown header directives, verbatim, in order
    script: Optional[list[str]] = None                      # SCRIPT ... SCRIPTEND body lines
    frames: list[Frame] = field(default_factory=list)
    unknown_directives: list[str] = field(default_factory=list)  # names only, for the Phase 0 audit

    # ---------- convenience ----------
    @property
    def single_dir(self) -> bool:
        return "SINGLEDIRECTION" in self.flags

    @property
    def loop(self) -> bool:
        return "LOOP" in self.flags

    @property
    def ndirs(self) -> int:
        return 1 if self.single_dir else 4

    def sprite_map(self) -> dict[int, SpriteDef]:
        return {s.index: s for s in self.sprites}

    def total_ms(self) -> int:
        return sum(f.duration_ms for f in self.frames)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- parsing
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _num(s: str):
    v = float(s)
    return int(v) if v.is_integer() else v


def _parse_piece_line(line: str) -> list[Piece]:
    pieces = []
    for chunk in line.split(","):
        parts = chunk.split()
        if len(parts) < 3:
            continue
        pieces.append(Piece(parts[0], _num(parts[1]), _num(parts[2]), parts[3:]))
    return pieces


def _looks_like_piece_line(line: str) -> bool:
    first = line.split(",")[0].split()
    if len(first) < 3:
        return False
    return bool(_NUM.match(first[1]) and _NUM.match(first[2])) and first[0].upper() not in ("WAIT", "PLAYSOUND")


def parse(text: str) -> GaniDoc:
    doc = GaniDoc()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        line = raw.strip()
        i += 1
        if not line:
            continue
        word = line.split()[0].upper()
        if word.startswith("GANI") and doc.header is None and not doc.sprites:
            doc.header = line
        elif word == "SPRITE":
            p = line.split(None, 7)
            try:
                doc.sprites.append(SpriteDef(int(p[1]), p[2], int(float(p[3])), int(float(p[4])),
                                             int(float(p[5])), int(float(p[6])),
                                             p[7].strip() if len(p) > 7 else ""))
            except (IndexError, ValueError):
                doc.extra.append(raw.rstrip())
        elif word in KNOWN_FLAGS:
            doc.flags.append(word)
        elif word == "SETBACKTO":
            doc.setbackto = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
        elif word.startswith("DEFAULT") and len(word) > 7:
            key = word[7:]
            doc.defaults[key] = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
        elif word == "SCRIPT":
            body = []
            while i < n and lines[i].strip().upper() != "SCRIPTEND":
                body.append(lines[i].rstrip())
                i += 1
            i += 1
            doc.script = body
        elif word == "ANI":
            i = _parse_ani(lines, i, doc)
        else:
            doc.extra.append(raw.rstrip())
            doc.unknown_directives.append(word)
    return doc


def _parse_ani(lines: list[str], i: int, doc: GaniDoc) -> int:
    ndirs = doc.ndirs
    cur: Optional[Frame] = None
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        i += 1
        up = line.upper()
        if up == "ANIEND":
            break
        if cur is not None and len(cur.dirs) < ndirs:
            # inside a frame: every line (even blank) is a direction row
            cur.dirs.append(_parse_piece_line(line) if line else [])
            continue
        if not line:
            continue
        word = up.split()[0]
        if word == "WAIT" and cur is not None:
            try:
                cur.wait = int(float(line.split()[1]))
            except (IndexError, ValueError):
                cur.extra.append(line)
        elif word == "PLAYSOUND" and cur is not None:
            p = line.split()
            cur.sounds.append(Sound(p[1] if len(p) > 1 else "",
                                    _num(p[2]) if len(p) > 2 else 0,
                                    _num(p[3]) if len(p) > 3 else 0))
        elif _looks_like_piece_line(line):
            cur = Frame(dirs=[_parse_piece_line(line)])
            doc.frames.append(cur)
        elif cur is not None:
            cur.extra.append(line)
        else:
            doc.extra.append(line)
    # pad incomplete trailing frame
    if cur is not None:
        while len(cur.dirs) < ndirs:
            cur.dirs.append([])
    return i


# ---------------------------------------------------------------- serializing
def _fmt(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def _fmt_piece(p: Piece) -> str:
    sid = p.sprite
    try:
        head = "%4d" % int(sid)
    except ValueError:
        head = "%4s" % sid
    x, y = p.x, p.y
    if isinstance(x, int) and isinstance(y, int):
        s = f"{head} {x:3d} {y:3d}"
    else:
        s = f"{head} {_fmt(x):>3} {_fmt(y):>3}"
    if p.extra:
        s += " " + " ".join(p.extra)
    return s


def serialize(doc: GaniDoc) -> str:
    out: list[str] = []
    if doc.header:
        out.append(doc.header)
    for s in doc.sprites:
        line = "SPRITE %4d %15s %4d %4d %4d %4d %s" % (s.index, s.source, s.left, s.top, s.width, s.height, s.comment)
        out.append(line.rstrip() if not s.comment else line)
    out.append("")
    for f in doc.flags:
        out.append(f)
    if doc.setbackto is not None:
        out.append(f"SETBACKTO {doc.setbackto}".rstrip())
    for k, v in doc.defaults.items():
        out.append(f"DEFAULT{k} {v}")
    out.extend(doc.extra)
    if doc.script is not None:
        out.append("")
        out.append("SCRIPT")
        out.extend(doc.script)
        out.append("SCRIPTEND")
    out.append("")
    out.append("ANI")
    for fr in doc.frames:
        for d in fr.dirs:
            out.append(", ".join(_fmt_piece(p) for p in d))
        if fr.wait:
            out.append(f"WAIT {fr.wait}")
        for snd in fr.sounds:
            out.append(f"PLAYSOUND {snd.file} {_fmt(snd.x)} {_fmt(snd.y)}")
        out.extend(fr.extra)
        out.append("")
    out.append("ANIEND")
    out.append("")
    return "\n".join(out)


def ms_to_wait(ms: int) -> int:
    """Duration in ms -> WAIT value. Rounds to the nearest tick, min one tick."""
    ticks = max(1, int(round(ms / TICK_MS)))
    return ticks - 1


# ---------------------------------------------------------------- editor snapshot interop
def from_snapshot(snap: dict) -> GaniDoc:
    """Build a GaniDoc from the JSON the editor bridge returns for gani.snapshot."""
    opts = snap.get("options", {})
    flags = [k for k in KNOWN_FLAGS if opts.get(k)]
    doc = GaniDoc(flags=flags, setbackto=opts.get("SETBACKTO") or None,
                  defaults=dict(snap.get("defaults", {})))
    for s in snap.get("sprites", []):
        doc.sprites.append(SpriteDef(int(s["index"]), s.get("source", "CUSTOM"), int(s.get("left", 0)),
                                     int(s.get("top", 0)), int(s.get("width", 0)), int(s.get("height", 0)),
                                     s.get("comment", "")))
    for f in snap.get("frames", []):
        dirs = [[Piece(str(p["sprite"]), p["x"], p["y"]) for p in d] for d in f["dirs"]]
        doc.frames.append(Frame(dirs=dirs, wait=ms_to_wait(int(f.get("duration", TICK_MS))),
                                sounds=[Sound(s["file"], s.get("x", 0), s.get("y", 0)) for s in f.get("sounds", [])]))
    return doc
