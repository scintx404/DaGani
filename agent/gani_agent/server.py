"""JSON-RPC 2.0 over WebSocket on loopback, token-protected.

The editor is the client; this process is the server. Token is written to
~/.gani-agent/token on start (the editor reads it from there via the Tauri/Wails shell).
Requires: pip install websockets
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
from pathlib import Path

from . import gani as G
from .ops import OpError, apply_ops

log = logging.getLogger("gani_agent")
TOKEN_FILE = Path.home() / ".gani-agent" / "token"


class RpcError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.data = code, data


STALE_REV = -32010
UNAUTHORIZED = -32001


class Router:
    """Holds the method table + transaction state. Transport-independent, easy to unit test."""

    def __init__(self):
        self.methods: dict[str, callable] = {}
        self.rev = 0
        self.snapshot_doc: G.GaniDoc | None = None
        self.tx: dict | None = None      # {"id", "base": GaniDoc, "label": str}

    def method(self, name):
        def deco(fn):
            self.methods[name] = fn
            return fn
        return deco

    def handle(self, raw: str) -> str | None:
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            return json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        rid = req.get("id")
        fn = self.methods.get(req.get("method", ""))
        try:
            if fn is None:
                raise RpcError(-32601, f"method not found: {req.get('method')}")
            result = fn(self, **(req.get("params") or {}))
            if rid is None:
                return None
            return json.dumps({"jsonrpc": "2.0", "id": rid, "result": result})
        except RpcError as e:
            err = {"code": e.code, "message": str(e)}
            if e.data is not None:
                err["data"] = e.data
        except OpError as e:
            err = {"code": -32602, "message": str(e)}
        except TypeError as e:
            err = {"code": -32602, "message": f"bad params: {e}"}
        except Exception:  # never leak a traceback to the editor
            log.exception("rpc failure")
            err = {"code": -32603, "message": "internal error"}
        return json.dumps({"jsonrpc": "2.0", "id": rid, "error": err})


def build_router() -> Router:
    r = Router()

    @r.method("ping")
    def _ping(self):
        return {"ok": True, "rev": self.rev}

    @r.method("gani.validate")
    def _validate(self, text: str):
        doc = G.parse(text)
        ok = G.parse(G.serialize(doc)) == doc
        return {"ok": ok, "frames": len(doc.frames), "total_ms": doc.total_ms(),
                "unknown_directives": doc.unknown_directives}

    @r.method("gani.apply")
    def _apply(self, snapshot: dict, base_rev: int, ops: list):
        """Apply ops to the snapshot. Rejects stale revisions so we never fight a user edit."""
        if base_rev != self.rev:
            raise RpcError(STALE_REV, "state changed since snapshot; re-snapshot and retry", {"rev": self.rev})
        doc = G.from_snapshot(snapshot)
        new = apply_ops(doc, ops)
        self.rev += 1
        self.snapshot_doc = new
        return {"rev": self.rev, "gani": G.serialize(new)}

    @r.method("tx.begin")
    def _tx_begin(self, label: str = "AI edit"):
        if self.tx:
            raise RpcError(-32011, "a transaction is already open")
        self.tx = {"id": secrets.token_hex(4), "base": self.snapshot_doc, "label": label}
        return {"tx": self.tx["id"]}

    @r.method("tx.commit")
    def _tx_commit(self, tx: str):
        if not self.tx or self.tx["id"] != tx:
            raise RpcError(-32012, "unknown transaction")
        self.tx = None
        return {"ok": True}

    @r.method("tx.rollback")
    def _tx_rollback(self, tx: str):
        if not self.tx or self.tx["id"] != tx:
            raise RpcError(-32012, "unknown transaction")
        self.snapshot_doc = self.tx["base"]
        self.tx = None
        return {"ok": True, "rev": self.rev}

    return r


async def serve(router: Router, host: str = "127.0.0.1", port: int = 8765):
    import asyncio

    import websockets  # imported lazily so tests don't need it

    token = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)

    async def handler(ws):
        # first message must be {"auth": token}
        try:
            first = json.loads(await ws.recv())
        except Exception:
            await ws.close()
            return
        if not hmac.compare_digest(str(first.get("auth", "")), token):
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": None,
                                      "error": {"code": UNAUTHORIZED, "message": "unauthorized"}}))
            await ws.close()
            return
        async for msg in ws:
            out = router.handle(msg)
            if out:
                await ws.send(out)

    async with websockets.serve(handler, host, port, origins=None, max_size=8 * 1024 * 1024):
        log.info("gani-agent listening on ws://%s:%d", host, port)
        await asyncio.Future()
