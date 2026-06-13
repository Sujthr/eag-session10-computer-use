"""
Multi-provider LLM client.

Priority: Gemini (round-robin across up to 6 keys)
       → Groq → Cerebras → NVIDIA → GitHub → OpenRouter
       → OpenAI (paid, last resort)

All providers except Gemini speak the OpenAI-compatible chat/completions API.
"""
import base64
import io
import json
from typing import Any

import httpx
from PIL import Image

from computer_use import config
from computer_use.logger import log

_TIMEOUT = 60.0

# ─────────────────────────────────────────────────────────────────────────────
# Gemini (native SDK)
# ─────────────────────────────────────────────────────────────────────────────

def _gemini_chat(prompt: str, system: str = "") -> str:
    import google.generativeai as genai
    key = config.next_gemini_key()
    genai.configure(api_key=key)
    model = genai.GenerativeModel(
        config.GEMINI_MODEL,
        system_instruction=system or None,
    )
    log.debug(f"[llm] gemini/{config.GEMINI_MODEL}  prompt={len(prompt)}ch")
    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0.1, "max_output_tokens": 2048},
    )
    return response.text


def _gemini_vision(image: Image.Image, prompt: str, system: str = "") -> str:
    import google.generativeai as genai
    key = config.next_gemini_key()
    genai.configure(api_key=key)
    model_kwargs = {}
    if system:
        model_kwargs["system_instruction"] = system
    model = genai.GenerativeModel(config.GEMINI_MODEL, **model_kwargs)
    log.debug(f"[llm] gemini-vision  prompt={len(prompt)}ch")
    response = model.generate_content([image, prompt])
    text = response.text if response.text else ""
    if not text.strip():
        raise ValueError("Gemini vision returned empty response (safety filter or quota)")
    return text


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible providers
# ─────────────────────────────────────────────────────────────────────────────

_OAI_COMPAT: dict[str, dict] = {
    "groq":       {"base": "https://api.groq.com/openai/v1",               "key": config.GROQ_API_KEY,       "model": config.GROQ_MODEL},
    "cerebras":   {"base": "https://api.cerebras.ai/v1",                    "key": config.CEREBRAS_API_KEY,   "model": config.CEREBRAS_MODEL},
    "nvidia":     {"base": "https://integrate.api.nvidia.com/v1",           "key": config.NVIDIA_API_KEY,     "model": config.NVIDIA_MODEL},
    "github":     {"base": "https://models.inference.ai.azure.com",         "key": config.GITHUB_TOKEN,       "model": config.GITHUB_MODEL},
    "openrouter": {"base": "https://openrouter.ai/api/v1",                  "key": config.OPENROUTER_API_KEY, "model": config.OPENROUTER_MODEL},
    "openai":     {"base": "https://api.openai.com/v1",                     "key": config.OPENAI_API_KEY,     "model": config.OPENAI_MODEL},
}


def _oai_chat(provider: str, prompt: str, system: str = "") -> str:
    cfg = _OAI_COMPAT[provider]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    log.debug(f"[llm] {provider}/{cfg['model']}  prompt={len(prompt)}ch")
    resp = httpx.post(
        f"{cfg['base']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json={"model": cfg["model"], "messages": messages, "temperature": 0.1, "max_tokens": 2048},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _oai_vision(provider: str, image: Image.Image, prompt: str) -> str:
    cfg = _OAI_COMPAT[provider]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ],
    }]
    log.debug(f"[llm] {provider}-vision/{cfg['model']}")
    resp = httpx.post(
        f"{cfg['base']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        json={"model": cfg["model"], "messages": messages, "max_tokens": 512},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

_RETRYABLE = (429, 500, 502, 503, 504)


def chat(prompt: str, system: str = "") -> str:
    """Text completion with automatic provider fallback."""
    errors: list[str] = []
    for provider in config.PROVIDER_ORDER:
        try:
            if provider == "gemini":
                return _gemini_chat(prompt, system)
            else:
                return _oai_chat(provider, prompt, system)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning(f"[llm] {provider} failed ({e}), trying next…")
            errors.append(f"{provider}: {e}")
            # Rotate Gemini key on quota errors
            if provider == "gemini" and status in (429, 503):
                try:
                    config.next_gemini_key()
                except RuntimeError:
                    pass
            continue

    raise RuntimeError("All LLM providers exhausted:\n" + "\n".join(errors))


def vision(image: Image.Image, prompt: str, system: str = "") -> str:
    """Vision completion. Tries Gemini first, OpenAI-vision last."""
    vision_providers = [p for p in config.PROVIDER_ORDER
                        if p in ("gemini", "openai")]
    errors: list[str] = []
    for provider in vision_providers:
        try:
            if provider == "gemini":
                return _gemini_vision(image, prompt, system=system)
            else:
                return _oai_vision(provider, image, prompt)
        except Exception as e:
            log.warning(f"[llm-vision] {provider} failed ({e}), trying next…")
            errors.append(f"{provider}: {e}")
            continue

    raise RuntimeError("All vision providers exhausted:\n" + "\n".join(errors))


def chat_json(prompt: str, system: str = "") -> dict[str, Any]:
    """Like chat() but parses the response as JSON, stripping markdown fences."""
    import re as _re
    raw = chat(prompt, system)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    text = text.strip()
    # Use raw_decode so extra text after the first JSON object is ignored
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Regex fallback: extract first {...} block
    for m in _re.finditer(r'\{.*?\}', text, _re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError(f"No valid JSON object found in: {text[:100]!r}", text, 0)
