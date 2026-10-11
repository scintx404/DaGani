"""Provider-agnostic multimodal structured-output client."""
from __future__ import annotations
import asyncio,json,os,time,urllib.error,urllib.parse,urllib.request
from dataclasses import dataclass
@dataclass
class Image:b64_png:str;label:str
class LLMError(RuntimeError):pass
def _post(url,headers,body,timeout=180):
 req=urllib.request.Request(url,data=json.dumps(body).encode(),method="POST",headers={"content-type":"application/json",**headers})
 for attempt in range(3):
  try:
   with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read())
  except urllib.error.HTTPError as e:
   msg=e.read().decode(errors="replace")[:800]
   if e.code in (429,500,502,503,529) and attempt<2:time.sleep(2**attempt*2);continue
   raise LLMError(f"HTTP {e.code}: {msg}") from None
  except urllib.error.URLError as e:
   if attempt<2:time.sleep(2);continue
   raise LLMError(str(e)) from None
 raise LLMError("unreachable")
class Provider:
 def __init__(self,cfg):
  self.cfg=cfg;self.kind=cfg.get("provider","anthropic").lower();self.model=cfg.get("model") or os.environ.get("GANI_AGENT_MODEL");self.api_key=os.environ.get(cfg.get("api_key_env") or ({"anthropic":"ANTHROPIC_API_KEY","gemini":"GEMINI_API_KEY"}.get(self.kind,"OPENAI_API_KEY")),"");self.base_url=cfg.get("base_url");self.max_tokens=int(cfg.get("max_tokens",8000));self.usage_log=[]
  if not self.model:raise LLMError("Set [llm].model or GANI_AGENT_MODEL")
 async def tool_call(self,system,user_text,images,tool_name,tool_desc,schema):return await asyncio.to_thread(self._tool_call,system,user_text,images,tool_name,tool_desc,schema)
 def _tool_call(self,system,user_text,images,tool_name,tool_desc,schema):
  if self.kind=="gemini":
   parts=[{"text":system+"\n\n"+user_text}]
   for im in images:parts.append({"inline_data":{"mime_type":"image/png","data":im.b64_png}})
   body={"system_instruction":{"parts":[{"text":system}]},"contents":[{"role":"user","parts":parts}],"generation_config":{"response_mime_type":"application/json","response_schema":schema,"max_output_tokens":self.max_tokens}}
   base=self.base_url or "https://generativelanguage.googleapis.com/v1beta";url=f"{base}/models/{self.model}:generateContent?key={urllib.parse.quote(self.api_key)}";res=_post(url,{},body);self.usage_log.append(res.get("usageMetadata",{}))
   try:return json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
   except Exception as e:raise LLMError(f"bad Gemini structured response: {e}") from None
  if self.kind=="anthropic":
   content=[]
   for im in images:content += [{"type":"text","text":f"{im.label}:"},{"type":"image","source":{"type":"base64","media_type":"image/png","data":im.b64_png}}]
   content.append({"type":"text","text":user_text});body={"model":self.model,"max_tokens":self.max_tokens,"system":[{"type":"text","text":system,"cache_control":{"type":"ephemeral"}}],"tools":[{"name":tool_name,"description":tool_desc,"input_schema":schema,"cache_control":{"type":"ephemeral"}}],"tool_choice":{"type":"tool","name":tool_name},"messages":[{"role":"user","content":content}]};url=(self.base_url or "https://api.anthropic.com")+"/v1/messages";res=_post(url,{"x-api-key":self.api_key,"anthropic-version":"2023-06-01"},body);self.usage_log.append(res.get("usage",{}));
   for block in res.get("content",[]):
    if block.get("type")=="tool_use":return block["input"]
   raise LLMError("model did not call the tool")
  content=[]
  for im in images:content += [{"type":"text","text":f"{im.label}:"},{"type":"image_url","image_url":{"url":"data:image/png;base64,"+im.b64_png}}]
  content.append({"type":"text","text":user_text});body={"model":self.model,"messages":[{"role":"system","content":system},{"role":"user","content":content}],"tools":[{"type":"function","function":{"name":tool_name,"description":tool_desc,"parameters":schema}}],"tool_choice":{"type":"function","function":{"name":tool_name}}};url=(self.base_url or "https://api.openai.com/v1")+"/chat/completions";res=_post(url,{"authorization":f"Bearer {self.api_key}"},body);self.usage_log.append(res.get("usage",{}))
  try:return json.loads(res["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
  except Exception as e:raise LLMError(f"bad structured response: {e}") from None
