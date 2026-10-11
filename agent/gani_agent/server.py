"""Authenticated loopback WebSocket server for the GANI Copilot."""
from __future__ import annotations
import asyncio,hmac,json,logging,os,secrets,tomllib
from pathlib import Path
from . import gani as G
from .corpus import Corpus,guess_category
from .llm import Provider,LLMError
from .ops import apply_ops
from .orchestrator import Orchestrator,Session as PipelineSession
from .renderer import HeadlessRenderer
from .session import EditorSession,EditorError
log=logging.getLogger("gani_agent")
TOKEN_FILE=Path.home()/".gani-agent"/"token"; STALE_REV=-32010; UNAUTHORIZED=-32001
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
  if not isinstance(req,dict):return json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"invalid request"}})
  rid=req.get("id");fn=self.methods.get(req.get("method",""))
  try:
   if fn is None:raise RpcError(-32601,f"method not found: {req.get('method')}")
   params=req.get("params") or {}
   if not isinstance(params,dict):raise RpcError(-32602,"params must be an object")
   result=fn(self,**params)
   if rid is None:return None
   return json.dumps({"jsonrpc":"2.0","id":rid,"result":result})
  except RpcError as e:err={"code":e.code,"message":str(e),"data":e.data}
  except (ValueError,KeyError,IndexError,TypeError) as e:err={"code":-32602,"message":str(e)}
  except Exception:log.exception("rpc failure");err={"code":-32603,"message":"internal error"}
  return json.dumps({"jsonrpc":"2.0","id":rid,"error":err})
def _cfg():
 p=(Path(__file__).parent.parent/"config.toml").resolve()
 try:return tomllib.loads(p.read_text())
 except Exception:return {"llm":{"provider":"openai","model":os.environ.get("GANI_AGENT_MODEL","")},"critic":{"max_rounds":3}}
def _pipeline():
 cfg=_cfg();llm=Provider(cfg.get("llm",{}));db=Path(os.environ.get("GANI_CORPUS_DB",str(Path(__file__).parents[1]/"corpus.sqlite")));return Orchestrator(llm,Corpus(db),HeadlessRenderer(),int(cfg.get("critic",{}).get("max_rounds",3)))
async def _on_prompt(session,p):
 prompt=str(p.get("prompt","")).strip()
 if not prompt:raise EditorError(-32602,"prompt is required")
 snap=await session.snapshot();category=p.get("category") or guess_category(prompt);pipe=PipelineSession(doc=G.from_snapshot(snap),catalog=snap.get("sprites",[]),sheet_png=p.get("sprite_sheet"))
 try:orch=_pipeline()
 except LLMError as e:raise EditorError(-32020,str(e))
 await session.notify("copilot.progress",{"stage":"planning","message":"Retrieving Graal references and planning frames"})
 try:
  await orch.generate(pipe,prompt,category,p.get("selection"),p.get("idle"));await session.notify("copilot.progress",{"stage":"qa","message":"Running metrics and critic refinement"})
  result=await orch.correct(pipe,static_ids=set(orch.corpus.category_stats(category).get("static_ids",[])),intent=prompt);tx=await session.tx_begin("AI Copilot proposal")
  await session.call("gani.load",{"gani":result["gani"],"proposal":True,"txId":tx});await session.notify("copilot.progress",{"stage":"ready","message":"Proposal ready for review","trace":pipe.trace})
  return {"ok":True,"txId":tx,"category":category,"frames":result["frames"],"total_ms":result["total_ms"],"verdict":result["verdict"],"metrics":result["metrics"],"trace":pipe.trace}
 except EditorError:raise
 except Exception as e:log.exception("generation failed");await session.notify("copilot.progress",{"stage":"error","message":str(e)});raise EditorError(-32021,str(e))
def build_router():
 r=Router()
 @r.method("ping")
 def ping(self):return {"ok":True,"rev":self.rev}
 @r.method("gani.validate")
 def validate(self,text):d=G.parse(text);return {"ok":G.parse(G.serialize(d))==d,"frames":len(d.frames),"total_ms":d.total_ms(),"unknown_directives":d.unknown_directives}
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
def origin_allowed(origin):return origin is None or origin.startswith(("wails://wails","http://wails.localhost","https://wails.localhost","http://localhost","http://127.0.0.1"))
def _origin(ws):
 h=getattr(getattr(ws,"request",None),"headers",None) or getattr(ws,"request_headers",None);return h.get("Origin") if h else None
async def serve(router,host="127.0.0.1",port=8765,rotate_token=False):
 import websockets
 token=load_token(rotate=rotate_token);log.info("gani-agent listening on ws://%s:%d",host,port)
 async def handler(ws):
  if not origin_allowed(_origin(ws)):await ws.close(code=1008);return
  try:first=json.loads(await ws.recv())
  except Exception:await ws.close();return
  if not isinstance(first,dict) or not hmac.compare_digest(str(first.get("auth","")),token):await ws.close();return
  session=EditorSession(ws.send,router);router.session=session;session.on_prompt=_on_prompt
  try:
   async for msg in ws:session.dispatch(msg)
  finally:session.close();router.session=None
 async with websockets.serve(handler,host,port,max_size=16*1024*1024):await asyncio.Future()
