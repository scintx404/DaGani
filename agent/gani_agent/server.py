"""Authenticated loopback WebSocket server for the GANI editor bridge."""
from __future__ import annotations
import hmac,json,logging,secrets
from pathlib import Path
from . import gani as G
from .ops import OpError,apply_ops
from .session import EditorSession,EditorError
log=logging.getLogger("gani_agent")
TOKEN_FILE=Path.home()/".gani-agent"/"token"
STALE_REV=-32010
UNAUTHORIZED=-32001
class RpcError(Exception):
 def __init__(self,code,message,data=None):super().__init__(message);self.code,self.data=code,data
class Router:
 def __init__(self):self.methods={};self.rev=0;self.snapshot_doc=None;self.tx=None;self.session=None
 def method(self,name):
  def deco(fn):self.methods[name]=fn;return fn
  return deco
 def handle(self,raw):
  try:req=json.loads(raw)
  except json.JSONDecodeError:return json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"parse error"}})
  rid=req.get("id");fn=self.methods.get(req.get("method",""))
  try:
   if fn is None:raise RpcError(-32601,f"method not found: {req.get('method')}")
   result=fn(self,**(req.get("params") or {}))
   if rid is None:return None
   return json.dumps({"jsonrpc":"2.0","id":rid,"result":result})
  except RpcError as e:err={"code":e.code,"message":str(e),"data":e.data}
  except OpError as e:err={"code":-32602,"message":str(e)}
  except TypeError as e:err={"code":-32602,"message":f"bad params: {e}"}
  except Exception:log.exception("rpc failure");err={"code":-32603,"message":"internal error"}
  return json.dumps({"jsonrpc":"2.0","id":rid,"error":err})
def build_router():
 r=Router()
 @r.method("ping")
 def ping(self):return {"ok":True,"rev":self.rev}
 @r.method("gani.validate")
 def validate(self,text):
  d=G.parse(text);return {"ok":G.parse(G.serialize(d))==d,"frames":len(d.frames),"total_ms":d.total_ms(),"unknown_directives":d.unknown_directives}
 @r.method("gani.apply")
 def apply(self,snapshot,base_rev=None,baseRev=None,ops=None):
  base=base_rev if base_rev is not None else baseRev
  if base!=self.rev:raise RpcError(STALE_REV,"state changed since snapshot; re-snapshot and retry",{"rev":self.rev})
  d=apply_ops(G.from_snapshot(snapshot),ops or []);self.rev+=1;self.snapshot_doc=d;return {"rev":self.rev,"gani":G.serialize(d),"applied":len(ops or [])}
 @r.method("tx.begin")
 def begin(self,label="AI edit"):
  if self.tx:raise RpcError(-32011,"a transaction is already open")
  self.tx={"id":secrets.token_hex(4),"base":self.snapshot_doc,"label":label};return {"txId":self.tx["id"],"tx":self.tx["id"]}
 @r.method("tx.commit")
 def commit(self,tx=None,txId=None):
  if not self.tx or self.tx["id"]!=(txId or tx):raise RpcError(-32012,"unknown transaction")
  self.tx=None;return {"ok":True,"rev":self.rev}
 @r.method("tx.rollback")
 def rollback(self,tx=None,txId=None):
  if not self.tx or self.tx["id"]!=(txId or tx):raise RpcError(-32012,"unknown transaction")
  self.snapshot_doc=self.tx["base"];self.tx=None;return {"ok":True,"rev":self.rev}
 return r
def load_token(path=TOKEN_FILE,rotate=False):
 if path.exists() and not rotate:
  t=path.read_text().strip()
  if len(t)>=24:return t
 t=secrets.token_urlsafe(24);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(t);path.chmod(0o600);return t
def origin_allowed(origin):
 if origin is None:return True
 return origin.startswith(("wails://wails","http://wails.localhost","https://wails.localhost","http://localhost","http://127.0.0.1"))
def _origin(ws):
 h=getattr(getattr(ws,"request",None),"headers",None) or getattr(ws,"request_headers",None);return h.get("Origin") if h else None
async def serve(router,host="127.0.0.1",port=8765,rotate_token=False):
 import asyncio,websockets
 token=load_token(rotate=rotate_token);log.info("pairing token: %s",token)
 async def handler(ws):
  if not origin_allowed(_origin(ws)):await ws.close(code=1008);return
  try:first=json.loads(await ws.recv())
  except Exception:await ws.close();return
  if not hmac.compare_digest(str(first.get("auth","")),token):
   await ws.send(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":UNAUTHORIZED,"message":"unauthorized"}}));await ws.close();return
  session=EditorSession(ws.send,router);router.session=session
  try:
   async for msg in ws:session.dispatch(msg)
  finally:session.close();router.session=None
 async with websockets.serve(handler,host,port,max_size=16*1024*1024):
  log.info("gani-agent listening on ws://%s:%d",host,port);await asyncio.Future()
