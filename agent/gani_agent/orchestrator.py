"""Generation + self-correction loop. Transport-agnostic: the server wires it to the editor bridge.

Generate:  intent -> retrieve refs -> planner (tool call) -> validate -> compile -> validate doc
Correct:   metrics -> deterministic autofix -> render sheet -> critic (tool call) -> apply ops
           (max `max_rounds`, stop on pass). Every step returns a trace the UI can show.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import gani as G
from . import metrics as M
from .compiler import PlanError, compile_plan, validate_plan
from .llm import Image
from .ops import OpError, apply_ops
from .prompts import (CRITIC_SCHEMA, CRITIC_SYSTEM, KEYFRAME_PLAN_SCHEMA, PLANNER_SYSTEM, catalog_block,
                      frame_table, planner_user)

log = logging.getLogger("gani_agent")


@dataclass
class Session:
    doc: G.GaniDoc
    catalog: list[dict]              # [{index, source, left, top, width, height, comment}]
    sheet_png: str | None = None     # base64 sprite sheet (labelled)
    trace: list[dict] = field(default_factory=list)


class Orchestrator:
    def __init__(self, llm, corpus, renderer, max_rounds: int = 3):
        self.llm = llm
        self.corpus = corpus
        self.renderer = renderer     # object with .sheet(doc, catalog) -> base64 png, .raw(doc) -> dict|None
        self.max_rounds = max_rounds

    # ------------------------------------------------------------ generation
    async def generate(self, sess: Session, prompt: str, category: str, selection=None, idle=None) -> G.GaniDoc:
        cat_stats = self.corpus.category_stats(category)
        refs = self.corpus.retrieve(prompt, category, k=3)
        static_ids = set(cat_stats.get("static_ids", []))
        sess.trace.append({"step": "retrieve", "refs": [r["file"] for r in refs], "stats_n": cat_stats.get("n")})
        catalog_ids = {s["index"] for s in sess.catalog}
        images = []
        if sess.sheet_png:
            images.append(Image(sess.sheet_png, "SPRITE_SHEET"))
        user = planner_user(prompt, selection, idle, catalog_block(sess.catalog), cat_stats, static_ids, refs)
        plan = await self.llm.tool_call(PLANNER_SYSTEM, user, images, "emit_keyframe_plan",
                                        "Emit the KeyframePlan for this animation.", KEYFRAME_PLAN_SCHEMA)
        errs = validate_plan(plan, catalog_ids)
        if errs:  # one repair attempt, feeding the errors back
            plan = await self.llm.tool_call(PLANNER_SYSTEM, user + "\n<FIX_THESE>\n" + "\n".join(errs) + "\n</FIX_THESE>",
                                            images, "emit_keyframe_plan", "Emit a corrected KeyframePlan.",
                                            KEYFRAME_PLAN_SCHEMA)
            errs = validate_plan(plan, catalog_ids)
            if errs:
                raise PlanError(errs)
        base = G.GaniDoc(sprites=[G.SpriteDef(s["index"], s["source"], s["left"], s["top"], s["width"], s["height"],
                                              s.get("comment", "")) for s in sess.catalog],
                         defaults=dict(cat_stats.get("defaults", {})))
        doc = compile_plan(plan, base, catalog_ids)
        sess.doc = doc
        sess.trace.append({"step": "compile", "frames": len(doc.frames), "total_ms": doc.total_ms()})
        return doc

    # ------------------------------------------------------------ self-correction
    async def correct(self, sess: Session, static_ids=None, z_rules=None, intent: str = "") -> dict:
        catalog_ids = {s["index"] for s in sess.catalog}
        for rnd in range(1, self.max_rounds + 1):
            report = M.compute(sess.doc, raw=self.renderer.raw(sess.doc), static_ids=static_ids, z_priors=z_rules)
            fixes = report["autofix_ops"]
            if fixes:
                sess.doc = apply_ops(sess.doc, fixes, catalog_ids)
                report = M.compute(sess.doc, raw=self.renderer.raw(sess.doc), static_ids=static_ids, z_priors=z_rules)
            sheet = self.renderer.sheet(sess.doc, sess.catalog)
            user = (f"<INTENT>{intent}</INTENT>\n<METRICS>{report['summary']}\n"
                    + "\n".join(f"- {i['severity']} {i['kind']} f{i.get('frame')} {i.get('dir')}: {i['problem']}"
                                for i in report["issues"][:40]) + "\n</METRICS>\n"
                    f"<FRAME_TABLE>\n{frame_table(_snap(sess.doc))}\n</FRAME_TABLE>")
            critic = await self.llm.tool_call(CRITIC_SYSTEM, user, [Image(sheet, "CONTACT_SHEET")],
                                              "submit_critique", "Return verdict, issues and ops.", CRITIC_SCHEMA)
            sess.trace.append({"step": "critic", "round": rnd, "verdict": critic["verdict"],
                               "score": critic.get("score"), "autofixes": len(fixes),
                               "issues": critic.get("issues", [])[:12], "ops": len(critic.get("ops", []))})
            if critic["verdict"] == "pass" or not critic.get("ops"):
                break
            try:
                sess.doc = apply_ops(sess.doc, critic["ops"][:12], catalog_ids)
            except OpError as e:
                sess.trace.append({"step": "ops_rejected", "round": rnd, "error": str(e)})
                break
        final = M.compute(sess.doc, raw=self.renderer.raw(sess.doc), static_ids=static_ids, z_priors=z_rules)
        last = next((t for t in reversed(sess.trace) if t.get("step") == "critic"), None)
        return {"verdict": last["verdict"] if last else "pass",
                "metrics": final["summary"], "frames": len(sess.doc.frames), "total_ms": sess.doc.total_ms(),
                "gani": G.serialize(sess.doc)}


def _snap(doc: G.GaniDoc) -> dict:
    """Doc -> editor-shaped snapshot (used for prompts; same shape as gani.from_snapshot input)."""
    return {"options": {"LOOP": doc.loop, "CONTINUOUS": "CONTINUOUS" in doc.flags,
                        "SINGLEDIRECTION": doc.single_dir, "SETBACKTO": doc.setbackto},
            "frames": [{"duration": f.duration_ms, "sounds": [s.file for s in f.sounds],
                        "dirs": [[{"sprite": p.sprite, "x": p.x, "y": p.y} for p in d] for d in f.dirs]}
                       for f in doc.frames]}
