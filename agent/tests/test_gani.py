from pathlib import Path

try:
    import pytest
except ImportError:  # zero-dep runner in tests/run_tests.py
    class _Mark:
        def parametrize(self, names, values):
            def deco(fn):
                fn.pytestmark = [type("M", (), {"name": "parametrize", "args": (names, values)})]
                return fn
            return deco

        def __getattr__(self, k):
            return lambda *a, **kw: (lambda f: f)

    class pytest:  # noqa: N801
        mark = _Mark()

        @staticmethod
        def raises(exc):
            import contextlib

            @contextlib.contextmanager
            def cm():
                try:
                    yield
                except exc:
                    return
                raise AssertionError(f"did not raise {exc}")
            return cm()

from gani_agent import gani as G
from gani_agent import metrics as M
from gani_agent.compiler import PlanError, compile_plan, validate_plan
from gani_agent.ops import OpError, apply_ops
from gani_agent.server import STALE_REV, build_router
from gani_agent.sprites import extract

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return G.parse((FIX / f"{name}.gani").read_text())


@pytest.mark.parametrize("name", ["sword", "walk", "editorcursor2"])
def test_golden_roundtrip(name):
    d = load(name)
    assert G.parse(G.serialize(d)) == d


def test_no_unknown_directives_in_fixtures():
    for n in ["sword", "walk", "editorcursor2"]:
        assert load(n).unknown_directives == []


def test_sword_shape():
    d = load("sword")
    assert len(d.frames) == 5 and d.total_ms() == 250 and d.setbackto == "idle"
    assert [len(x) for x in d.frames[0].dirs] == [6, 5, 6, 5]
    assert d.frames[0].sounds[0].file == "sword.wav"


def test_single_dir_cursor():
    d = load("editorcursor2")
    assert d.single_dir and d.loop and len(d.frames) == 2 and d.frames[0].wait == 2


def test_ms_to_wait():
    assert G.ms_to_wait(50) == 0 and G.ms_to_wait(150) == 2 and G.ms_to_wait(10) == 0


def _catalog(d):
    return [{"index": s.index, "source": s.source, "left": s.left, "top": s.top, "width": s.width,
             "height": s.height, "comment": s.comment} for s in d.sprites]


def test_plan_validation_catches_bad_sprite_and_tween():
    cat = {200, 201, 202, 203, 100, 40}
    plan = {"name": "x", "category": "other", "options": {}, "keyframes": [
        {"duration_ms": 100, "ease": "linear", "dirs": {
            k: [{"sprite": 999, "x": 0, "y": 0}] for k in G.DIRS}},
        {"duration_ms": 100, "ease": "step", "dirs": {
            k: [{"sprite": 200, "x": 0, "y": 0}] for k in G.DIRS}}]}
    errs = validate_plan(plan, cat)
    assert any("not in SPRITE_CATALOG" in e for e in errs)
    assert any("requires identical sprite lists" in e for e in errs)


def test_compile_plan_roundtrips_and_tweens():
    base = load("walk")
    cat = _catalog(base)
    ids = {s["index"] for s in cat}
    plan = {"name": "t", "category": "walk", "options": {"LOOP": True, "CONTINUOUS": True},
            "tween_step_ms": 50, "keyframes": [
                {"duration_ms": 100, "ease": "linear", "dirs": {k: [{"sprite": 100, "x": 8, "y": 0}] for k in G.DIRS}},
                {"duration_ms": 100, "ease": "step", "dirs": {k: [{"sprite": 100, "x": 8, "y": 10}] for k in G.DIRS}}]}
    d = compile_plan(plan, base, ids)
    assert d.total_ms() == 200
    assert G.parse(G.serialize(d)) == d
    ys = [f.dirs[0][0].y for f in d.frames]
    assert ys[0] == 0 and ys[1] > 0 and ys[1] < ys[2]  # tween moves monotonically


def test_compile_rejects_invalid():
    with pytest.raises(PlanError):
        compile_plan({"name": "x", "category": "other", "options": {}, "keyframes": [
            {"duration_ms": 75, "ease": "step", "dirs": {k: [] for k in G.DIRS}}]}, load("walk"))


def test_ops_are_atomic():
    d = load("sword")
    before = G.serialize(d)
    with pytest.raises(OpError):
        apply_ops(d, [{"op": "nudge", "frame": 0, "dir": "up", "layer": 0, "dx": 1},
                      {"op": "setSprite", "frame": 0, "dir": "up", "layer": 0, "sprite": 99999}])
    assert G.serialize(d) == before


def test_ops_nudge_and_reorder():
    d = load("sword")
    out = apply_ops(d, [{"op": "nudge", "frame": 0, "dir": "up", "layer": 0, "dx": 3, "dy": -1},
                        {"op": "reorder", "frame": 0, "dir": "up", "layer": 0, "to": 2}])
    orig = d.frames[0].dirs[0][0]
    moved = out.frames[0].dirs[0][2]          # layer 0 was reordered to position 2
    assert (moved.sprite, moved.x, moved.y) == (orig.sprite, orig.x + 3, orig.y - 1)
    assert G.parse(G.serialize(out)) == out


def test_metrics_flags_static_drift_and_jitter():
    d = load("walk")
    d.frames[1].dirs[0][0].x += 2  # shadow (sprite 0) is layer 0 in every frame
    rep = M.compute(d, static_ids={0})
    kinds = {i["kind"] for i in rep["issues"]}
    assert "static_drift" in kinds
    assert rep["autofix_ops"], "static drift should produce an autofix"


def test_static_and_zorder_from_refs():
    d = load("sword")
    assert 0 in M.static_ids_from_refs([d])
    z = M.z_priors_from_refs([d])
    assert ["BODY", "HEAD"] in z["down"]


def test_sprites_extract_exact_rects(tmp_path):
    import numpy as np
    import cv2
    img = np.zeros((32, 64, 4), np.uint8)
    img[4:20, 3:13] = (0, 0, 255, 255)
    img[2:30, 40:60] = (0, 255, 0, 255)
    p = tmp_path / "sheet.png"
    cv2.imwrite(str(p), img)
    c = extract(p)
    assert [s["rect"] for s in c["sprites"]] == [[3, 4, 10, 16], [40, 2, 20, 28]]


def test_rpc_stale_rev_and_roundtrip():
    import json
    r = build_router()
    text = (FIX / "editorcursor2.gani").read_text()
    res = json.loads(r.handle(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "gani.validate",
                                          "params": {"text": text}})))
    assert res["result"]["ok"] is True
    res = json.loads(r.handle(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "gani.apply",
                                          "params": {"snapshot": {"frames": []}, "base_rev": 7, "ops": []}})))
    assert res["error"]["code"] == STALE_REV
    res = json.loads(r.handle(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "nope"})))
    assert res["error"]["code"] == -32601
