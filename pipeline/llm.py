"""Talk to a local model through Ollama or any OpenAI-compatible server (LM Studio, llama.cpp)."""
from __future__ import annotations

import json
import logging
import time

import requests

from .config import Config

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LocalLLM:
    def __init__(self, cfg: Config, model: str | None = None):
        c = cfg.llm
        self.provider = c.get("provider", "ollama")
        self.base = c["base_url"].rstrip("/")
        self.model = model or c["model"]
        self.num_ctx = int(c["num_ctx"])
        self.max_out = int(c["max_output_tokens"])
        self.temperature = float(c["temperature"])
        self.timeout = float(c["timeout_s"])
        self.no_think = bool(c.get("disable_thinking", True))
        self._think_supported = True
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "seconds": 0.0}

    # ---- health check -------------------------------------------------------
    def check(self) -> str:
        try:
            if self.provider == "ollama":
                r = requests.get(self.base + "/api/tags", timeout=10)
                r.raise_for_status()
                names = [m["name"] for m in r.json().get("models", [])]
                if not any(n == self.model or n.split(":")[0] == self.model for n in names):
                    raise LLMError(f"model '{self.model}' not found in Ollama. Run: ollama pull {self.model}")
                return f"Ollama OK, model {self.model}"
            r = requests.get(self.base + "/models", timeout=10)
            r.raise_for_status()
            return f"OpenAI-compatible server OK ({len(r.json().get('data', []))} models)"
        except requests.RequestException as e:
            raise LLMError(f"cannot reach the local model server at {self.base}: {e}") from e

    # ---- structured call ----------------------------------------------------
    def json_call(self, system: str, user: str, schema: dict) -> dict:
        last_err = None
        for attempt in range(2):
            msg_user = user if attempt == 0 else user + "\n\nReturn ONLY valid JSON matching the schema."
            t0 = time.time()
            content = self._ollama(system, msg_user, schema) if self.provider == "ollama" \
                else self._openai(system, msg_user, schema)
            self.usage["seconds"] += time.time() - t0
            self.usage["calls"] += 1
            try:
                return json.loads(_strip_fences(content))
            except json.JSONDecodeError as e:
                last_err = e
                log.warning("model returned invalid JSON (attempt %d)", attempt + 1)
        raise LLMError(f"model did not return valid JSON: {last_err}")

    def _ollama(self, system: str, user: str, schema: dict) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx, "num_predict": self.max_out},
        }
        if self.no_think and self._think_supported:
            body["think"] = False
        try:
            r = requests.post(self.base + "/api/chat", json=body, timeout=self.timeout)
            if r.status_code == 400 and "think" in r.text.lower() and "think" in body:
                self._think_supported = False      # model has no thinking mode — retry without the flag
                body.pop("think")
                r = requests.post(self.base + "/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise LLMError(f"Ollama call failed: {e}") from e
        data = r.json()
        self.usage["prompt_tokens"] += int(data.get("prompt_eval_count", 0) or 0)
        self.usage["output_tokens"] += int(data.get("eval_count", 0) or 0)
        if data.get("done_reason") == "length":
            log.warning("output hit max_output_tokens — result may be cut off")
        return data["message"]["content"]

    def _openai(self, system: str, user: str, schema: dict) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_out,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "extraction", "strict": True, "schema": schema}},
        }
        try:
            r = requests.post(self.base + "/chat/completions", json=body, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise LLMError(f"local server call failed: {e}") from e
        data = r.json()
        u = data.get("usage", {})
        self.usage["prompt_tokens"] += int(u.get("prompt_tokens", 0) or 0)
        self.usage["output_tokens"] += int(u.get("completion_tokens", 0) or 0)
        return data["choices"][0]["message"]["content"]


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    # some models wrap thinking in <think> tags even when asked not to
    if "</think>" in s:
        s = s.split("</think>", 1)[1]
    return s.strip()
