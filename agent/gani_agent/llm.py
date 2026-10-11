"""Provider-agnostic multimodal structured-output client with model fallback."""
from __future__ import annotations
import asyncio,json,logging,os,time,urllib.error,urllib.parse,urllib.request
from dataclasses import dataclass

log = logging.getLogger("gani_agent")

@dataclass
class Image:
    b64_png: str
    label: str

class LLMError(RuntimeError):
    pass

def _post(url, headers, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"content-type": "application/json", **headers})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:1000]
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(2 ** attempt * 2)
                continue
            raise LLMError(f"HTTP {e.code}: {msg}") from None
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(2)
                continue
            raise LLMError(str(e)) from None
    raise LLMError("unreachable")

GEMINI_FALLBACKS = ["gemini-3.8-flash", "gemini-3.1-pro", "gemini-2.5-flash", "gemini-2.5-pro"]

class Provider:
    def __init__(self, cfg):
        self.cfg = cfg
        self.kind = cfg.get("provider", "gemini").lower()
        self.model = cfg.get("model") or os.environ.get("GANI_AGENT_MODEL") or "gemini-3.8-flash"
        key_name = cfg.get("api_key_env") or ({"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(self.kind, "OPENAI_API_KEY"))
        self.api_key = os.environ.get(key_name, "")
        self.base_url = cfg.get("base_url")
        self.max_tokens = int(cfg.get("max_tokens", 8000))
        self.usage_log = []

    async def tool_call(self, system, user_text, images, tool_name, tool_desc, schema):
        return await asyncio.to_thread(self._tool_call, system, user_text, images, tool_name, tool_desc, schema)

    def _tool_call(self, system, user_text, images, tool_name, tool_desc, schema):
        if not self.api_key and not self.base_url:
            key_name = self.cfg.get("api_key_env") or ("GEMINI_API_KEY" if self.kind == "gemini" else "OPENAI_API_KEY")
            raise LLMError(f"Missing API key. Set {key_name} in the environment.")
        if self.kind == "gemini":
            models_to_try = [self.model] + [m for m in GEMINI_FALLBACKS if m != self.model]
            parts = [{"text": system + "\n\n" + user_text}]
            for im in images:
                parts.append({"inline_data": {"mime_type": "image/png", "data": im.b64_png}})
            body = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}], "generation_config": {"response_mime_type": "application/json", "response_schema": schema, "max_output_tokens": self.max_tokens}}
            base = self.base_url or "https://generativelanguage.googleapis.com/v1beta"
            last_err = None
            for model in models_to_try:
                model_path = model.removeprefix("models/")
                try:
                    res = _post(f"{base}/models/{model_path}:generateContent?key={urllib.parse.quote(self.api_key)}", {}, body)
                    self.usage_log.append(res.get("usageMetadata", {}))
                    text = res["candidates"][0]["content"]["parts"][0]["text"]
                    self.model = model
                    return json.loads(text)
                except LLMError as e:
                    last_err = e
                    if any(c in str(e) for c in ("HTTP 400", "HTTP 404", "not found", "NOT_FOUND")):
                        log.warning("Gemini model %s unavailable; trying fallback", model)
                        continue
                    raise
                except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                    raise LLMError(f"Bad Gemini structured response from {model}: {e}") from None
            raise LLMError(f"All configured Gemini models failed. Last error: {last_err}")
        if self.kind == "anthropic":
            content = []
            for im in images:
                content += [{"type": "text", "text": f"{im.label}:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": im.b64_png}}]
            content.append({"type": "text", "text": user_text})
            body = {"model": self.model, "max_tokens": self.max_tokens, "system": [{"type": "text", "text": system}], "tools": [{"name": tool_name, "description": tool_desc, "input_schema": schema}], "tool_choice": {"type": "tool", "name": tool_name}, "messages": [{"role": "user", "content": content}]}
            res = _post((self.base_url or "https://api.anthropic.com") + "/v1/messages", {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, body)
            for block in res.get("content", []):
                if block.get("type") == "tool_use": return block["input"]
            raise LLMError("Model did not call the tool")
        content = []
        for im in images:
            content += [{"type": "text", "text": f"{im.label}:"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + im.b64_png}}]
        content.append({"type": "text", "text": user_text})
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}], "tools": [{"type": "function", "function": {"name": tool_name, "description": tool_desc, "parameters": schema}}], "tool_choice": {"type": "function", "function": {"name": tool_name}}}
        res = _post((self.base_url or "https://api.openai.com/v1") + "/chat/completions", {"authorization": f"Bearer {self.api_key}"}, body)
        try: return json.loads(res["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e: raise LLMError(f"Bad structured response: {e}") from None
