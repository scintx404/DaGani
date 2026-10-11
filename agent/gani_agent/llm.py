"""Provider-agnostic multimodal LLM client with forced tool calls (structured output).

Zero third-party deps (urllib). Providers: anthropic, openai, and any OpenAI-compatible
endpoint (e.g. a local Ollama at http://127.0.0.1:11434/v1) via base_url.
Pin the model in config.toml and re-run the eval harness when you change it.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Image:
    b64_png: str
    label: str


class LLMError(RuntimeError):
    pass


def _post(url: str, headers: dict, body: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:800]
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


class Provider:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.kind = cfg.get("provider", "anthropic")
        self.model = cfg.get("model") or os.environ.get("GANI_AGENT_MODEL")
        if not self.model:
            raise LLMError("Set [llm].model in config.toml (pin your current frontier multimodal model)")
        key_env = cfg.get("api_key_env") or ("ANTHROPIC_API_KEY" if self.kind == "anthropic" else "OPENAI_API_KEY")
        self.api_key = os.environ.get(key_env, "")
        self.base_url = cfg.get("base_url")
        self.max_tokens = int(cfg.get("max_tokens", 8000))
        self.usage_log: list[dict] = []

    async def tool_call(self, system: str, user_text: str, images: list[Image], tool_name: str,
                        tool_desc: str, schema: dict) -> dict:
        return await asyncio.to_thread(self._tool_call, system, user_text, images, tool_name, tool_desc, schema)

    def _tool_call(self, system, user_text, images, tool_name, tool_desc, schema) -> dict:
        if self.kind == "anthropic":
            content = []
            for im in images:
                content.append({"type": "text", "text": f"{im.label}:"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                             "data": im.b64_png}})
            content.append({"type": "text", "text": user_text})
            body = {
                "model": self.model, "max_tokens": self.max_tokens,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "tools": [{"name": tool_name, "description": tool_desc, "input_schema": schema,
                           "cache_control": {"type": "ephemeral"}}],
                "tool_choice": {"type": "tool", "name": tool_name},
                "messages": [{"role": "user", "content": content}],
            }
            url = (self.base_url or "https://api.anthropic.com") + "/v1/messages"
            res = _post(url, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, body)
            self.usage_log.append(res.get("usage", {}))
            for block in res.get("content", []):
                if block.get("type") == "tool_use":
                    return block["input"]
            raise LLMError(f"model did not call the tool: {json.dumps(res)[:500]}")
        # openai / compatible
        content = []
        for im in images:
            content.append({"type": "text", "text": f"{im.label}:"})
            content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + im.b64_png}})
        content.append({"type": "text", "text": user_text})
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "tools": [{"type": "function", "function": {"name": tool_name, "description": tool_desc,
                                                        "parameters": schema}}],
            "tool_choice": {"type": "function", "function": {"name": tool_name}},
        }
        url = (self.base_url or "https://api.openai.com/v1") + "/chat/completions"
        res = _post(url, {"authorization": f"Bearer {self.api_key}"}, body)
        self.usage_log.append(res.get("usage", {}))
        try:
            call = res["choices"][0]["message"]["tool_calls"][0]
            return json.loads(call["function"]["arguments"])
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMError(f"bad tool response: {e}: {json.dumps(res)[:500]}") from None
