import json
import unittest

from gani_agent.server import build_router, STALE_REV


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.router = build_router()

    def call(self, method, params=None, rid=1):
        raw = self.router.handle(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}))
        return json.loads(raw)

    def test_snapshot_sync_and_ping(self):
        snapshot = {
            "options": {"LOOP": False, "CONTINUOUS": False, "SINGLEDIRECTION": True},
            "defaults": {},
            "sprites": [],
            "frames": [{"duration": 50, "sounds": [], "dirs": [[]]}],
        }
        result = self.call("gani.snapshot", {"snapshot": snapshot})["result"]
        self.assertEqual(result["rev"], 0)
        self.assertIsNotNone(result["gani"])
        self.assertEqual(self.call("ping")["result"]["rev"], 0)

    def test_transaction_rollback_restores_base_revision(self):
        snapshot = {
            "options": {"LOOP": False, "CONTINUOUS": False, "SINGLEDIRECTION": True},
            "defaults": {},
            "sprites": [],
            "frames": [{"duration": 50, "sounds": [], "dirs": [[]]}],
        }
        self.call("gani.snapshot", {"snapshot": snapshot})
        tx = self.call("tx.begin", {"label": "test"})["result"]["tx"]
        self.router.rev = 3
        result = self.call("tx.rollback", {"tx": tx})["result"]
        self.assertEqual(result["rev"], 0)
        self.assertEqual(self.call("ping")["result"]["rev"], 0)

    def test_invalid_params_are_json_rpc_errors(self):
        result = self.call("gani.apply", {"snapshot": {}, "base_rev": "bad", "ops": []})
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
