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
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"content-type": "application/json", **headers}
    )
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

GEMINI_FALLBACKS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

class Provider:
    def __init__(self, cfg):
        self.cfg = cfg
        self.kind = cfg.get("provider", "anthropic").lower()
        self.model = cfg.get("model") or os.environ.get("GANI_AGENT_MODEL") or "gemini-3.8-flash"
        
        # Read API key: accepts direct key string in api_key or api_key_env, or env variable name
        key_val = cfg.get("api_key") or cfg.get("api_key_env", "")
        if key_val and (key_val.startswith(("AQ.", "AIza", "sk-")) or len(key_val) > 25):
            # User directly pasted the key
            self.api_key = key_val
        elif key_val and key_val in os.environ:
            self.api_key = os.environ[key_val]
        else:
            # Check default env variable aliases
            if self.kind == "gemini":
                self.api_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
            elif self.kind == "anthropic":
                self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            else:
                self.api_key = os.environ.get("OPENAI_API_KEY", "")
            if not self.api_key and key_val:
                self.api_key = key_val

        self.base_url = cfg.get("base_url")
        self.max_tokens = int(cfg.get("max_tokens", 8000))
        self.usage_log = []

    async def tool_call(self, system, user_text, images, tool_name, tool_desc, schema):
        return await asyncio.to_thread(self._tool_call, system, user_text, images, tool_name, tool_desc, schema)

    def _tool_call(self, system, user_text, images, tool_name, tool_desc, schema):
        if not self.api_key and not self.base_url:
            key_name = "GEMINI_API_KEY" if self.kind == "gemini" else "OPENAI_API_KEY"
            raise LLMError(f"Missing API key. Please set the {key_name} environment variable or put it in config.toml.")

        if self.kind == "gemini":
            models_to_try = [self.model]
            for fb in GEMINI_FALLBACKS:
                if fb not in models_to_try:
                    models_to_try.append(fb)

            parts = [{"text": system + "\n\n" + user_text}]
            for im in images:
                parts.append({"inline_data": {"mime_type": "image/png", "data": im.b64_png}})
            body = {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": parts}],
                "generation_config": {
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "max_output_tokens": self.max_tokens
                }
            }
            base = self.base_url or "https://generativelanguage.googleapis.com/v1beta"

            last_err = None
            for m in models_to_try:
                model_path = m if not m.startswith("models/") else m.split("models/", 1)[1]
                url = f"{base}/models/{model_path}:generateContent?key={urllib.parse.quote(self.api_key)}"
                try:
                    res = _post(url, {}, body)
                    self.usage_log.append(res.get("usageMetadata", {}))
                    text = res["candidates"][0]["content"]["parts"][0]["text"]
                    self.model = m  # Lock into working model
                    return json.loads(text)
                except LLMError as e:
                    last_err = e
                    # If 404 or 400 (model not found / invalid), try the next fallback
                    if any(c in str(e) for c in ("HTTP 404", "HTTP 400", "not found", "NOT_FOUND")):
                        log.warning("Gemini model %s unavailable, falling back to next...", m)
                        continue
                    raise
                except Exception as e:
                    raise LLMError(f"Bad Gemini response from {m}: {e}") from None

            raise LLMError(f"All Gemini models failed. Last error: {last_err}")

        if self.kind == "anthropic":
            content = []
            for im in images:
                content += [{"type": "text", "text": f"{im.label}:"},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": im.b64_png}}]
            content.append({"type": "text", "text": user_text})
            body = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "tools": [{"name": tool_name, "description": tool_desc, "input_schema": schema, "cache_control": {"type": "ephemeral"}}],
                "tool_choice": {"type": "tool", "name": tool_name},
                "messages": [{"role": "user", "content": content}]
            }
            url = (self.base_url or "https://api.anthropic.com") + "/v1/messages"
            res = _post(url, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, body)
            self.usage_log.append(res.get("usage", {}))
            for block in res.get("content", []):
                if block.get("type") == "tool_use":
                    return block["input"]
            raise LLMError("Model did not call the tool")

        # OpenAI
        content = []
        for im in images:
            content += [{"type": "text", "text": f"{im.label}:"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + im.b64_png}}]
        content.append({"type": "text", "text": user_text})
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "tools": [{"type": "function", "function": {"name": tool_name, "description": tool_desc, "parameters": schema}}],
            "tool_choice": {"type": "function", "function": {"name": tool_name}}
        }
        url = (self.base_url or "https://api.openai.com/v1") + "/chat/completions"
        res = _post(url, {"authorization": f"Bearer {self.api_key}"}, body)
        self.usage_log.append(res.get("usage", {}))
        try:
            return json.loads(res["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        except Exception as e:
            raise LLMError(f"Bad structured response: {e}") from None
