"""Bidirectional JSON-RPC session for the connected editor bridge."""
from __future__ import annotations
import asyncio,json,itertools
class EditorError(Exception):
 def __init__(self,code,message,data=None):super().__init__(message);self.code,self.data=code,data
class EditorSession:
 def __init__(self,send,router=None):
  self._send=send;self.router=router;self._ids=itertools.count(1);self._pending={};self.hello=None;self.editor_rev=None;self.user_edit=asyncio.Event();self.decisions=asyncio.Queue();self.on_prompt=None;self.proposal_tx=None
 async def call(self,method,params=None,timeout=120):
  rid=next(self._ids);fut=asyncio.get_running_loop().create_future();self._pending[rid]=fut;await self._send(json.dumps({"jsonrpc":"2.0","id":rid,"method":method,"params":params or {}}))
  try:return await asyncio.wait_for(fut,timeout)
  finally:self._pending.pop(rid,None)
 async def notify(self,method,params=None):await self._send(json.dumps({"jsonrpc":"2.0","method":method,"params":params or {}}))
 def close(self,reason="editor disconnected"):
  for f in self._pending.values():
   if not f.done():f.set_exception(EditorError(-32000,reason))
  self._pending.clear()
 async def on_message(self,raw):
  try:m=json.loads(raw)
  except json.JSONDecodeError:return
  if "method" not in m:
   f=self._pending.get(m.get("id"))
   if f and not f.done():
    if "error" in m:e=m["error"];f.set_exception(EditorError(e.get("code",-32603),e.get("message","error"),e.get("data")))
    else:f.set_result(m.get("result"))
   return
  method=m["method"];p=m.get("params") or {};rid=m.get("id")
  try:
   if method=="session.hello":self.hello=p;self.editor_rev=p.get("rev");result={"ok":True,"protocol":1}
   elif method=="state.changed":self.editor_rev=p.get("rev");self.user_edit.set() if p.get("by")=="user" else None;result={}
   elif method=="user.decision":await self.decisions.put(p);result={}
   elif method=="user.prompt":result=await self.on_prompt(self,p) if self.on_prompt else {"ok":False,"message":"generation is not wired"}
   elif self.router:
    raw_result=self.router.handle(raw);parsed=json.loads(raw_result or "{}");
    if "error" in parsed:raise EditorError(parsed["error"].get("code",-32603),parsed["error"].get("message","error"),parsed["error"].get("data"))
    result=parsed.get("result",{})
   else:raise EditorError(-32601,f"method not found: {method}")
   if rid is not None:await self._send(json.dumps({"jsonrpc":"2.0","id":rid,"result":result}))
  except EditorError as e:
   if rid is not None:await self._send(json.dumps({"jsonrpc":"2.0","id":rid,"error":{"code":e.code,"message":str(e),"data":e.data}}))
 def dispatch(self,raw):asyncio.ensure_future(self.on_message(raw))
 async def snapshot(self):
  s=await self.call("gani.snapshot");self.editor_rev=s.get("rev");self.user_edit.clear();return s
 async def apply(self,ops,label="AI edit"):
  r=await self.call("gani.apply",{"ops":ops,"baseRev":self.editor_rev,"label":label});self.editor_rev=r.get("rev");return r
 async def tx_begin(self,label="AI edit"):r=await self.call("tx.begin",{"label":label});self.proposal_tx=r.get("txId") or r.get("tx");return self.proposal_tx
 async def tx_commit(self,tx=None):return await self.call("tx.commit",{"txId":tx or self.proposal_tx})
 async def tx_rollback(self,tx=None):return await self.call("tx.rollback",{"txId":tx or self.proposal_tx})
