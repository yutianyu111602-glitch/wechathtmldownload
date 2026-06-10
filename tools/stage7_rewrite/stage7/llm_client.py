"""OpenAI-compatible LLM client with Ollama adapter."""
from __future__ import annotations
import time
import json
from typing import Optional

try:
    import httpx
except ImportError:
    raise ImportError("httpx is required. Install: pip install httpx")

from .logging_setup import setup_logging
from .config import LLMConfig


class LlmClientError(Exception):
    pass


class LlmClient:
    def __init__(self, config: LLMConfig, logger=None):
        self.config = config
        self.logger = logger or setup_logging(__import__("pathlib").Path(".") / "logs", "llm_client")
        headers = {}
        if getattr(config, "api_key", None):
            headers["Authorization"] = f"Bearer {config.api_key}"
        self.client = httpx.Client(
            base_url=config.endpoint,
            timeout=config.timeout_sec + 30,
            headers=headers,
        )

    def _ollama_chat(self, messages, temp, top_p, max_tok, max_retries, timeout, profile_name) -> dict:
        """Ollama /api/chat. Returns OpenAI-compatible result dict."""
        request_body = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temp,
                "top_p": top_p,
                "num_predict": max_tok,
                "num_ctx": getattr(self.config, "num_ctx", 8192),
            },
        }
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                self.logger.debug("Ollama attempt %d/%d (profile=%s)", attempt + 1, max_retries + 1, profile_name or "default")
                resp = self.client.post("/api/chat", json=request_body, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return {
                    "ok": True,
                    "content": content,
                    "model": data.get("model", self.config.model),
                    "usage": {"prompt_tokens": data.get("prompt_eval_count", 0), "completion_tokens": data.get("eval_count", 0)},
                    "attempt": attempt,
                }
            except httpx.TimeoutException as e:
                last_error = {"type": "llm_timeout", "message": str(e)}
                self.logger.warning("Ollama timeout attempt %d", attempt + 1)
            except httpx.ConnectError as e:
                last_error = {"type": "llm_connection_error", "message": str(e)}
                self.logger.warning("Ollama connect error attempt %d", attempt + 1)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:1000] if e.response.text else ""
                self.logger.error("Ollama HTTP %d: %s", status, body)
                if status == 413 or "context" in body.lower() or "exceeded" in body.lower():
                    last_error = {"type": "context_exceeded", "message": f"HTTP {status}: {body}"}
                else:
                    last_error = {"type": "http_error", "message": f"HTTP {status}: {body}"}
            except Exception as e:
                last_error = {"type": "unknown_error", "message": str(e)}
                self.logger.warning("Ollama error attempt %d: %s", attempt + 1, e)
            if attempt < max_retries:
                backoff = self.config.retry_backoff_sec[min(attempt, len(self.config.retry_backoff_sec) - 1)]
                time.sleep(backoff)
        return {"ok": False, "content": "", "error_type": last_error["type"] if last_error else "unknown",
                "error_message": last_error["message"] if last_error else "", "attempt": max_retries}

    def _openai_chat(self, messages, temp, top_p, max_tok, top_k, repeat_penalty, no_thinking, max_retries, timeout, profile_name) -> dict:
        """OpenAI /v1/chat/completions. Returns result dict."""
        request_body = {"model": self.config.model, "messages": messages, "temperature": temp, "top_p": top_p, "max_tokens": max_tok}
        if top_k is not None:
            request_body["top_k"] = top_k
        if repeat_penalty is not None:
            request_body["repeat_penalty"] = repeat_penalty
        if no_thinking:
            request_body["enable_thinking"] = False
            request_body["thinking"] = False
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                self.logger.debug("OpenAI attempt %d/%d (profile=%s)", attempt + 1, max_retries + 1, profile_name or "default")
                resp = self.client.post("/v1/chat/completions", json=request_body, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return {"ok": True, "content": content, "model": data.get("model", self.config.model),
                        "usage": data.get("usage", {}), "attempt": attempt}
            except httpx.TimeoutException as e:
                last_error = {"type": "llm_timeout", "message": str(e)}
                self.logger.warning("OpenAI timeout attempt %d", attempt + 1)
            except httpx.ConnectError as e:
                last_error = {"type": "llm_connection_error", "message": str(e)}
                self.logger.warning("OpenAI connect error attempt %d", attempt + 1)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:1000] if e.response.text else ""
                self.logger.error("HTTP %d: %s", status, body)
                if status == 413 or "context" in body.lower() or "exceeded" in body.lower():
                    last_error = {"type": "context_exceeded", "message": f"HTTP {status}: {body}"}
                else:
                    last_error = {"type": "http_error", "message": f"HTTP {status}: {body}"}
            except Exception as e:
                last_error = {"type": "unknown_error", "message": str(e)}
                self.logger.warning("OpenAI error attempt %d: %s", attempt + 1, e)
            if attempt < max_retries:
                backoff = self.config.retry_backoff_sec[min(attempt, len(self.config.retry_backoff_sec) - 1)]
                time.sleep(backoff)
        return {"ok": False, "content": "", "error_type": last_error["type"] if last_error else "unknown",
                "error_message": last_error["message"] if last_error else "", "attempt": max_retries}

    def chat_completion(self, system_prompt: str, user_content: str, profile: dict | None = None) -> dict:
        """Send chat completion with retry. Routes to Ollama or OpenAI based on api_style."""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
        temp = profile.get("temperature", self.config.temperature) if profile else self.config.temperature
        top_p = profile.get("top_p", self.config.top_p) if profile else self.config.top_p
        max_tok = profile.get("max_tokens", self.config.max_tokens) if profile else self.config.max_tokens
        max_retries = profile.get("retries", self.config.max_retries) if profile else self.config.max_retries
        timeout = profile.get("request_timeout_sec", self.config.timeout_sec) if profile else self.config.timeout_sec
        profile_name = profile.get("name", "default") if profile else "default"

        api_style = getattr(self.config, "api_style", "openai_compatible")

        if api_style == "ollama":
            return self._ollama_chat(messages, temp, top_p, max_tok, max_retries, timeout, profile_name)

        top_k = profile.get("top_k", self.config.top_k) if profile else self.config.top_k
        repeat_penalty = profile.get("repeat_penalty", self.config.repeat_penalty) if profile else self.config.repeat_penalty
        no_thinking = profile.get("no_thinking", self.config.no_thinking) if profile else self.config.no_thinking
        return self._openai_chat(messages, temp, top_p, max_tok, top_k, repeat_penalty, no_thinking, max_retries, timeout, profile_name)

    def health_check(self) -> dict:
        """Quick health check.

        llama-swap on this host serves the Ollama chat endpoint used by the
        runner (``/api/chat``) but does not serve Ollama's model-list endpoint
        (``/api/tags``).  For ``api_style: ollama`` we therefore try
        ``/api/tags`` first for native Ollama, then fall back to OpenAI-style
        ``/v1/models`` for llama-swap before reporting DOWN.
        """
        api_style = getattr(self.config, "api_style", "openai_compatible")
        errors: list[str] = []
        if api_style == "ollama":
            try:
                resp = self.client.get("/api/tags", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return {"ok": True, "models": models, "endpoint": "/api/tags"}
            except Exception as e:
                errors.append(f"/api/tags: {e}")

        try:
            resp = self.client.get("/v1/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", [])]
            return {"ok": True, "models": models, "endpoint": "/v1/models", "fallback_errors": errors}
        except Exception as e:
            errors.append(f"/v1/models: {e}")
            return {"ok": False, "error": "; ".join(errors)}

    def close(self) -> None:
        self.client.close()
