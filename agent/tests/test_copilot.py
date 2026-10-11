import asyncio,json
from gani_agent.anatomy import classify
from gani_agent.session import EditorSession

def test_anatomy_roles_and_anchors():
 assert classify("head19.png", "head #1")["role"] == "head"
 assert classify("sword1.png", "sword")["anchor"] == "hand"
 assert classify("shadow.png", "shadow")["anchor_offset"]["y"] == 0

def test_session_routes_prompt_and_notifications():
 sent=[]
 async def send(x):sent.append(json.loads(x))
 async def prompt(session,p):return {"ok":True,"echo":p["prompt"]}
 async def run():
  s=EditorSession(send);s.on_prompt=prompt;s.dispatch(json.dumps({"jsonrpc":"2.0","id":7,"method":"user.prompt","params":{"prompt":"slash"}}));await asyncio.sleep(0.01)
  assert sent[-1]["result"]["echo"]=="slash"
 asyncio.run(run())
