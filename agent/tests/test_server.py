import json

from gani_agent.server import STALE_REV, build_router


def _call(router, method, params=None, rid=1):
    raw = router.handle(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}))
    return json.loads(raw)


def _snapshot():
    return {
        "options": {"LOOP": False, "CONTINUOUS": False, "SINGLEDIRECTION": True},
        "defaults": {}, "sprites": [],
        "frames": [{"duration": 50, "sounds": [], "dirs": [[]]}],
    }


def test_snapshot_sync_and_ping():
    router = build_router()
    result = _call(router, "gani.snapshot", {"snapshot": _snapshot()})["result"]
    assert result["rev"] == 0
    assert result["gani"]
    assert _call(router, "ping")["result"]["rev"] == 0


def test_transaction_rollback_restores_base_revision():
    router = build_router()
    _call(router, "gani.snapshot", {"snapshot": _snapshot()})
    tx = _call(router, "tx.begin", {"label": "test"})["result"]["tx"]
    router.rev = 3
    result = _call(router, "tx.rollback", {"tx": tx})["result"]
    assert result["rev"] == 0
    assert _call(router, "ping")["result"]["rev"] == 0


def test_invalid_revision_is_rejected():
    result = _call(build_router(), "gani.apply", {"snapshot": {}, "base_rev": "bad", "ops": []})
    assert result["error"]["code"] == STALE_REV
