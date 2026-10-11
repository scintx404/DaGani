"""End-to-end pipeline with a scripted fake LLM (no network, no API key)."""
import asyncio
import pathlib
import sys
import tempfile

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gani_agent import gani as G  # noqa: E402
from gani_agent.corpus import Corpus  # noqa: E402
from gani_agent.orchestrator import Orchestrator, Session  # noqa: E402
from gani_agent.renderer import HeadlessRenderer  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


class FakeLLM:
    """Returns scripted tool outputs in order. Records what it was sent."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def tool_call(self, system, user_text, images, tool_name, tool_desc, schema):
        self.calls.append((tool_name, len(images)))
        return self.outputs.pop(0)


def _sheet(tmp):
    img = np.zeros((64, 64, 4), np.uint8)
    img[0:32, 0:32] = (200, 100, 50, 255)
    img[32:64, 0:32] = (50, 200, 50, 255)
    p = pathlib.Path(tmp) / "sheet.png"
    cv2.imwrite(str(p), img)
    return str(p)


def test_generate_then_correct_with_fake_llm():
    tmp = tempfile.mkdtemp()
    corpus = Corpus(pathlib.Path(tmp) / "c.sqlite")
    corpus.index_dir(FIX)
    base = G.parse((FIX / "walk.gani").read_text())
    catalog = [{"index": s.index, "source": s.source, "left": s.left, "top": s.top, "width": s.width,
                "height": s.height, "comment": s.comment} for s in base.sprites]
    plan = {"name": "walk-test", "category": "walk", "options": {"LOOP": True, "CONTINUOUS": True},
            "keyframes": [{"duration_ms": 100, "ease": "step", "note": "contact",
                           "dirs": {k: [{"sprite": 0, "x": 0, "y": 0}, {"sprite": 200, "x": 0, "y": 0}] for k in G.DIRS}}]}
    critic_fix = {"verdict": "fix", "score": 6, "issues": [{"frame": 0, "dir": "up", "problem": "shadow drift"}],
                  "ops": [{"op": "nudge", "frame": 0, "dir": "up", "layer": 0, "dx": 0, "dy": 0}]}
    critic_pass = {"verdict": "pass", "score": 9, "issues": [], "ops": []}
    llm = FakeLLM([plan, critic_fix, critic_pass])
    renderer = HeadlessRenderer(_sheet(tmp))
    orch = Orchestrator(llm, corpus, renderer, max_rounds=3)
    sess = Session(doc=base, catalog=catalog, sheet_png=renderer.sheet(base, catalog))

    doc = asyncio.run(orch.generate(sess, "walk", "walk"))
    assert len(doc.frames) == 1 and doc.loop
    assert G.parse(G.serialize(doc)) == doc
    res = asyncio.run(orch.correct(sess, static_ids={0}, intent="walk"))
    assert res["verdict"] == "pass"
    assert [c[0] for c in llm.calls] == ["emit_keyframe_plan", "submit_critique", "submit_critique"]
    assert any(t["step"] == "critic" and t["round"] == 2 for t in sess.trace)


def test_corpus_index_is_roundtrip_clean_and_retrieves():
    tmp = tempfile.mkdtemp()
    c = Corpus(pathlib.Path(tmp) / "c.sqlite")
    stats = c.index_dir(FIX)
    assert stats["indexed"] == 3 and stats["roundtrip_fail"] == []
    refs = c.retrieve("sword slash", "slash", k=2)
    assert refs and refs[0]["file"] == "sword.gani"
    assert c.category_stats("walk")["n"] >= 1
