"""Corpus indexing + retrieval (RAG over parsed ASTs, not fine-tuning).

Index = SQLite table of features per .gani. Retrieval = metadata filter -> text
similarity on name/description/tags -> motion-signature rerank. An embedding
column can be added later without changing callers.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from . import gani as G
from .compiler import doc_to_plan
from .metrics import static_ids_from_refs, z_priors_from_refs

CATEGORY_RULES = [
    ("slash", r"sword|slash|swing|attack|hit(?!ler)"),
    ("thrust", r"thrust|stab|lunge|spear"),
    ("reload", r"reload"),
    ("shoot", r"shoot|fire|gun|bow|arrow"),
    ("cast", r"cast|spell|magic|pray"),
    ("hurt", r"hurt|dead|die|death|knock"),
    ("run", r"run|sprint|skip"),
    ("walk", r"walk|swim|ride(?!still)|push|pull|carry(?!still)"),
    ("idle", r"idle|still|sit|sleep|lay|stand"),
    ("emote", r"emote|wave|dance|laugh|spin"),
]


def guess_category(text: str) -> str:
    t = text.lower()
    for cat, rx in CATEGORY_RULES:
        if re.search(rx, t):
            return cat
    return "other"


def features(doc: G.GaniDoc) -> dict:
    sources = sorted({s.source for s in doc.sprites})
    sound_frames = [i for i, f in enumerate(doc.frames) if f.sounds]
    waits = [f.wait for f in doc.frames]
    return {
        "frames": len(doc.frames), "total_ms": doc.total_ms(), "loop": doc.loop,
        "single_dir": doc.single_dir, "setbackto": doc.setbackto, "sources": sources,
        "waits": waits, "sound_frames": sound_frames,
        "sound_pos": [i / max(1, len(doc.frames)) for i in sound_frames],
        "motion": motion_signature(doc),
    }


def motion_signature(doc: G.GaniDoc, bins: int = 8) -> list[float]:
    """Per-source normalized displacement curve (down dir), resampled to `bins`."""
    if not doc.frames:
        return [0.0] * bins
    d = 0 if doc.single_dir else 2
    smap = doc.sprite_map()
    per_frame = []
    for f in doc.frames:
        acc = defaultdict(list)
        for p in f.dirs[d] if d < len(f.dirs) else []:
            s = smap.get(p.sprite_id)
            if s:
                acc[s.source].append((p.x, p.y))
        per_frame.append({k: (sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v)) for k, v in acc.items()})
    first = per_frame[0]
    curve = []
    for pf in per_frame:
        ds = [math.dist(pf[k], first[k]) for k in pf if k in first]
        curve.append(sum(ds) / len(ds) if ds else 0.0)
    out = []
    for i in range(bins):
        out.append(curve[min(len(curve) - 1, int(i * len(curve) / bins))])
    m = max(out) or 1.0
    return [round(v / m, 3) for v in out]


class Corpus:
    def __init__(self, db_path: str | Path):
        self.db = sqlite3.connect(str(db_path))
        self.db.execute("""CREATE TABLE IF NOT EXISTS ganis (
            file TEXT PRIMARY KEY, category TEXT, description TEXT, tags TEXT,
            features TEXT, plan TEXT, text TEXT, reviewed INTEGER DEFAULT 0)""")
        self.db.commit()

    # ---------------- indexing
    def index_dir(self, root: str | Path, report_unknown: bool = True) -> dict:
        root = Path(root)
        stats = {"indexed": 0, "roundtrip_fail": [], "unknown_directives": defaultdict(int)}
        for path in sorted(root.rglob("*.gani")):
            text = path.read_text(encoding="utf-8", errors="replace")
            doc = G.parse(text)
            if G.parse(G.serialize(doc)) != doc:
                stats["roundtrip_fail"].append(str(path))
            for u in doc.unknown_directives:
                stats["unknown_directives"][u] += 1
            name = path.stem
            cat = guess_category(name)
            self.db.execute("""INSERT INTO ganis(file, category, description, tags, features, plan, text)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(file) DO UPDATE SET
                features=excluded.features, plan=excluded.plan, text=excluded.text,
                category=CASE WHEN ganis.reviewed=1 THEN ganis.category ELSE excluded.category END""",
                            (str(path.relative_to(root)), cat, name, name,
                             json.dumps(features(doc)), json.dumps(doc_to_plan(doc, name, cat)), text))
            stats["indexed"] += 1
        self.db.commit()
        stats["unknown_directives"] = dict(stats["unknown_directives"])
        return stats

    def set_label(self, file: str, category: str | None = None, description: str | None = None,
                  tags: str | None = None):
        cur = self.db.execute("SELECT category, description, tags FROM ganis WHERE file=?", (file,)).fetchone()
        if not cur:
            raise KeyError(file)
        self.db.execute("UPDATE ganis SET category=?, description=?, tags=?, reviewed=1 WHERE file=?",
                        (category or cur[0], description or cur[1], tags or cur[2], file))
        self.db.commit()

    # ---------------- stats
    def category_stats(self, category: str) -> dict:
        rows = self.db.execute("SELECT features, text FROM ganis WHERE category=?", (category,)).fetchall()
        if not rows:
            return {"category": category, "n": 0}
        feats = [json.loads(r[0]) for r in rows]
        docs = [G.parse(r[1]) for r in rows]

        def pct(vals, q):
            v = sorted(vals)
            return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]

        frames = [f["frames"] for f in feats]
        total = [f["total_ms"] for f in feats]
        snd = [p for f in feats for p in f["sound_pos"]]
        return {
            "category": category, "n": len(rows),
            "frames": [pct(frames, .1), pct(frames, .5), pct(frames, .9)],
            "total_ms": [pct(total, .1), pct(total, .5), pct(total, .9)],
            "sound_pos_p50": pct(snd, .5) if snd else None,
            "loop_ratio": sum(f["loop"] for f in feats) / len(feats),
            "z_rules": z_priors_from_refs(docs),
            "static_ids": sorted(static_ids_from_refs(docs)),
        }

    # ---------------- retrieval
    def retrieve(self, prompt: str, category: str, single_dir: bool | None = None, k: int = 3,
                 motion: list[float] | None = None) -> list[dict]:
        q = "SELECT file, category, description, tags, features, plan FROM ganis"
        rows = self.db.execute(q).fetchall()
        words = set(re.findall(r"[a-z0-9]+", prompt.lower()))
        scored = []
        for file, cat, desc, tags, feats, plan in rows:
            f = json.loads(feats)
            if single_dir is not None and f["single_dir"] != single_dir:
                continue
            s = 0.0
            if cat == category:
                s += 2.0
            text = set(re.findall(r"[a-z0-9]+", f"{file} {desc} {tags}".lower()))
            if words:
                s += len(words & text) / len(words)
            if motion:
                s += 1.0 - min(1.0, sum(abs(a - b) for a, b in zip(motion, f["motion"])) / len(motion))
            scored.append((s, file, cat, desc, plan))
        scored.sort(reverse=True)
        return [{"file": f, "category": c, "description": d, "similarity": round(s, 3), "plan": json.loads(p)}
                for s, f, c, d, p in scored[:k]]

    def docs(self, category: str | None = None) -> list[G.GaniDoc]:
        if category:
            rows = self.db.execute("SELECT text FROM ganis WHERE category=?", (category,)).fetchall()
        else:
            rows = self.db.execute("SELECT text FROM ganis").fetchall()
        return [G.parse(r[0]) for r in rows]
