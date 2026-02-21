# app/services/social/llm/llm_router.py

from __future__ import annotations

import os
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from ....utils.logger import Log  # adjust if your relative path differs


# ---------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
DEFAULT_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))  # total attempts = 1 + retries
DEFAULT_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "900"))


# ---------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------
def _strip_markdown_fences(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s*```$", "", s).strip()
    return s


def _unwrap_common_json_wrappers(obj: Any) -> Dict[str, Any]:
    """
    Unwrap common wrappers like {"result": {...}} or {"output": {...}} if present.
    """
    if not isinstance(obj, dict):
        raise ValueError("Parsed JSON is not an object")

    if len(obj.keys()) == 1:
        k = next(iter(obj.keys()))
        if k in ("result", "output", "data", "response"):
            inner = obj.get(k)
            if isinstance(inner, dict):
                return inner
    return obj


def _extract_first_json_object(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found")
    return json.loads(match.group(0))


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Extract JSON from LLM output safely.
      - Pure JSON
      - JSON inside markdown fences
      - JSON embedded in text
      - Wrapped JSON objects
    """
    if not isinstance(text, str):
        raise ValueError("LLM output is not a string")

    s = _strip_markdown_fences(text)

    # 1) direct parse
    try:
        obj = json.loads(s)
        return _unwrap_common_json_wrappers(obj)
    except Exception:
        pass

    # 2) first {...} object
    try:
        obj = _extract_first_json_object(s)
        return _unwrap_common_json_wrappers(obj)
    except Exception:
        pass

    # 3) parse from first "{"
    try:
        idx = s.find("{")
        if idx >= 0:
            obj = json.loads(s[idx:])
            return _unwrap_common_json_wrappers(obj)
    except Exception:
        pass

    raise ValueError(f"Could not parse JSON from LLM output: {text[:300]}")


# ---------------------------------------------------------------------
# Errors / tracing
# ---------------------------------------------------------------------
class LLMError(Exception):
    pass


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _retry_call(fn, *, retries: int, trace_id: str, backoff_base: float = 0.6):
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt >= retries:
                break
            sleep_s = backoff_base * (2 ** attempt)
            Log.warning(f"[llm_router][{trace_id}] retry={attempt+1}/{retries} sleeping={sleep_s:.2f}s err={e}")
            time.sleep(sleep_s)
    raise last_err


# ---------------------------------------------------------------------
# Base Interface
# ---------------------------------------------------------------------
class BaseLLMClient:
    provider: str = "base"

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        raise NotImplementedError

    def generate_json(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> Dict[str, Any]:
        strict_prompt = (
            "Return ONLY valid JSON.\n"
            "No markdown.\n"
            "No explanation.\n"
            "No trailing commas.\n\n"
            f"{prompt}"
        )
        text = self.generate_text(system=system, prompt=strict_prompt, trace_id=trace_id, **kwargs)
        return _extract_json(text)

    # Backward compatibility
    def complete(self, *, system: str, prompt: str, trace_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        trace_id = trace_id or _new_trace_id()
        return self.generate_json(system=system, prompt=prompt, trace_id=trace_id, **kwargs)


# ---------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------
@dataclass
class OpenAIClient(BaseLLMClient):
    api_key: str
    model: str
    provider: str = "openai"

    def __post_init__(self):
        try:
            from openai import OpenAI
        except Exception as e:
            raise ImportError("pip install openai") from e
        self._client = OpenAI(api_key=self.api_key)

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        max_tokens = int(kwargs.get("max_tokens", DEFAULT_MAX_TOKENS))
        temperature = float(kwargs.get("temperature", DEFAULT_TEMPERATURE))

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------
@dataclass
class AnthropicClient(BaseLLMClient):
    api_key: str
    model: str
    provider: str = "anthropic"

    def __post_init__(self):
        try:
            import anthropic
        except Exception as e:
            raise ImportError("pip install anthropic") from e
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        max_tokens = int(kwargs.get("max_tokens", DEFAULT_MAX_TOKENS))
        temperature = float(kwargs.get("temperature", DEFAULT_TEMPERATURE))

        resp = self._client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if resp and resp.content:
            return (resp.content[0].text or "").strip()
        return ""


# ---------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------
@dataclass
class GoogleClient(BaseLLMClient):
    api_key: str
    model: str
    provider: str = "google"

    def __post_init__(self):
        try:
            from google import genai
        except Exception as e:
            raise ImportError("pip install google-genai") from e
        self._client = genai.Client(api_key=self.api_key)

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        try:
            temperature = float(kwargs.get("temperature", DEFAULT_TEMPERATURE))
            full_prompt = f"{system}\n\n{prompt}"
            resp = self._client.models.generate_content(
                model=self.model,
                contents=full_prompt,
                config={"temperature": temperature},
            )
            return (getattr(resp, "text", "") or "").strip()
        except Exception as e:
            Log.warning(f"[llm_router][{trace_id}][google] generate_text failed: {e}")
            return ""


# ---------------------------------------------------------------------
# HuggingFace
# ---------------------------------------------------------------------
@dataclass
class HFClient(BaseLLMClient):
    token: str
    model: str
    provider: str = "hf"

    def __post_init__(self):
        try:
            from huggingface_hub import InferenceClient
        except Exception as e:
            raise ImportError("pip install huggingface_hub") from e
        self._client = InferenceClient(model=self.model, token=self.token)

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        full = f"{system}\n\n{prompt}"
        return (self._client.text_generation(
            full,
            max_new_tokens=int(kwargs.get("max_tokens", DEFAULT_MAX_TOKENS)),
            temperature=float(kwargs.get("temperature", DEFAULT_TEMPERATURE)),
            do_sample=True,
            return_full_text=False,
        ) or "").strip()


# ---------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------
@dataclass
class OllamaClient(BaseLLMClient):
    api_url: str = "http://localhost:11434"
    model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    provider: str = "ollama"

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        timeout = int(kwargs.get("timeout", DEFAULT_TIMEOUT_SECONDS))
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": kwargs.get("options", {}),
        }

        try:
            resp = requests.post(f"{self.api_url}/api/chat", json=body, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return (data.get("message", {}).get("content", "") or "").strip()

        except requests.exceptions.ConnectionError:
            Log.error(f"[llm_router][{trace_id}][ollama] Cannot connect to {self.api_url}. Is Ollama running?")
            return ""
        except requests.exceptions.Timeout:
            Log.warning(f"[llm_router][{trace_id}][ollama] Request timeout model={self.model}")
            return ""
        except Exception as e:
            Log.warning(f"[llm_router][{trace_id}][ollama] request failed: {e}")
            return ""


# ---------------------------------------------------------------------
# Mock (Safe default)
# ---------------------------------------------------------------------
class MockClient(BaseLLMClient):
    provider: str = "mock"

    def generate_text(self, *, system: str, prompt: str, trace_id: str, **kwargs) -> str:
        # This mock returns JSON to keep downstream stable
        return json.dumps({
            "suggestions": [
                {"type": "fix_grammar", "title": "Fix spelling & grammar", "details": ["No issues found."]},
                {"type": "optimize_length", "title": "Optimize length", "details": ["Caption length looks good."]},
                {"type": "adjust_tone", "title": "Adjust tone", "details": ["Try a slightly more upbeat tone."]},
                {"type": "inspire_engagement", "title": "Inspire engagement", "details": ["Ask a question to boost comments."]},
            ],
            "rewrites": {
                "recommended_text": "Your joy is our responsibility ✨ How can we support you today?"
            },
            "platform_notes": [],
        })


# ---------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------
def get_llm_client() -> BaseLLMClient:
    provider = (os.getenv("LLM_PROVIDER") or "mock").lower().strip()
    model = (os.getenv("LLM_MODEL") or "").strip()

    trace_id = _new_trace_id()

    try:
        if provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise LLMError("OPENAI_API_KEY missing")
            client = OpenAIClient(api_key=key, model=(model or "gpt-4o-mini"))
            Log.info(f"[llm_router][{trace_id}] Using OpenAI model={client.model}")
            return client

        if provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise LLMError("ANTHROPIC_API_KEY missing")
            client = AnthropicClient(api_key=key, model=(model or "claude-3.5-sonnet-latest"))
            Log.info(f"[llm_router][{trace_id}] Using Anthropic model={client.model}")
            return client

        if provider in ("google", "gemini"):
            key = os.getenv("GOOGLE_API_KEY")
            if not key:
                raise LLMError("GOOGLE_API_KEY missing")
            client = GoogleClient(api_key=key, model=(model or "gemini-2.5-flash"))
            Log.info(f"[llm_router][{trace_id}] Using Google model={client.model}")
            return client

        if provider in ("hf", "huggingface"):
            token = os.getenv("HF_TOKEN")
            if not token:
                raise LLMError("HF_TOKEN missing")
            client = HFClient(token=token, model=(model or "mistralai/Mistral-7B-Instruct-v0.3"))
            Log.info(f"[llm_router][{trace_id}] Using HuggingFace model={client.model}")
            return client

        if provider == "ollama":
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            name = model or os.getenv("OLLAMA_MODEL", "llama2")
            client = OllamaClient(api_url=host, model=name)
            Log.info(f"[llm_router][{trace_id}] Using Ollama model={client.model} host={client.api_url}")
            return client

    except Exception as e:
        Log.warning(f"[llm_router][{trace_id}] provider={provider} unavailable: {e}")

    Log.info(f"[llm_router][{trace_id}] Using Mock LLM")
    return MockClient()


def llm_generate_json(*, system: str, prompt: str, **kwargs) -> Dict[str, Any]:
    """
    Convenience wrapper with retries.
    """
    trace_id = kwargs.pop("trace_id", None) or _new_trace_id()
    client = get_llm_client()

    def _call():
        return client.generate_json(system=system, prompt=prompt, trace_id=trace_id, **kwargs)

    try:
        return _retry_call(_call, retries=DEFAULT_MAX_RETRIES, trace_id=trace_id)
    except Exception as e:
        Log.warning(f"[llm_router][{trace_id}] generate_json failed: {e}")
        raise