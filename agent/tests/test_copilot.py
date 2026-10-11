import asyncio,json,os
from gani_agent.anatomy import classify
from gani_agent.llm import Provider
from gani_agent.session import EditorSession

def test_anatomy_roles_and_anchors():
 assert classify("head19.png", "head #1")["role"] == "head"
 assert classify("sword1.png", "sword")["anchor"] == "hand"
 assert classify("shadow.png", "shadow")["anchor_offset"]["y"] == 0

def test_provider_uses_selected_model_and_env_key(monkeypatch=None):
 old=os.environ.get("GEMINI_API_KEY")
 os.environ["GEMINI_API_KEY"]="test-key"
 try:
  p=Provider({"provider":"gemini","model":"gemini-3.1-pro","api_key_env":"GEMINI_API_KEY"})
  assert p.model=="gemini-3.1-pro"
  assert p.api_key=="test-key"
 finally:
  if old is None: os.environ.pop("GEMINI_API_KEY",None)
  else: os.environ["GEMINI_API_KEY"]=old

def test_session_routes_prompt_and_notifications():
 sent=[]
 async def send(x):sent.append(json.loads(x))
 async def prompt(session,p):return {"ok":True,"echo":p["prompt"]}
 async def run():
  s=EditorSession(send);s.on_prompt=prompt;s.dispatch(json.dumps({"jsonrpc":"2.0","id":7,"method":"user.prompt","params":{"prompt":"slash"}}));await asyncio.sleep(0.01)
  assert sent[-1]["result"]["echo"]=="slash"
 asyncio.run(run())
