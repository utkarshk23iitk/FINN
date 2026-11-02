"""Minimal Gemini client: JSON in, JSON out, with token counts.

Plain REST over requests, so there is no SDK to install. Callers cache the
results themselves (by announcement id or document hash), so the same
document is never paid for twice.
"""
import base64
import json
import os
import time
from pathlib import Path

import requests

# Cheap model for bulk extraction; the stronger one only when a check fails
# or where reasoning is the product (promised vs delivered).
CHEAP = "gemini-3.5-flash-lite"
STRONG = "gemini-3.5-flash"
# When a model is overloaded (503), try an older one before giving up.
FALLBACK = {STRONG: "gemini-2.5-flash", CHEAP: "gemini-2.5-flash-lite"}
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class LLMError(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip("'\"")
    if not key:
        raise LLMError("GEMINI_API_KEY is not set (put it in .env)")
    return key


def generate_json(prompt: str, schema: dict, model: str = CHEAP, pdf: bytes = None,
                  retries: int = 3) -> tuple:
    """Return (parsed JSON, usage dict). `schema` is a Gemini responseSchema."""
    parts = [{"text": prompt}]
    if pdf:
        parts.append({"inline_data": {"mime_type": "application/pdf",
                                      "data": base64.b64encode(pdf).decode()}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseSchema": schema},
    }
    for attempt in range(retries):
        resp = requests.post(API.format(model=model), json=body, timeout=120,
                             headers={"x-goog-api-key": api_key()})
        if resp.status_code in (429, 500, 503) and attempt < retries - 1:
            time.sleep(5 * (attempt + 1))  # free-tier rate limits are per minute
            continue
        if resp.status_code == 503 and model in FALLBACK:
            return generate_json(prompt, schema, FALLBACK[model], pdf, retries)
        if not resp.ok:
            msg = resp.json().get("error", {}).get("message", "") if resp.content else ""
            raise LLMError(f"{model}: HTTP {resp.status_code} {msg[:200]}")
        out = resp.json()
        try:
            text = out["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise LLMError(f"{model}: empty response ({out.get('promptFeedback', '')})")
        meta = out.get("usageMetadata", {})
        usage = {"model": model, "input_tokens": meta.get("promptTokenCount", 0),
                 "output_tokens": meta.get("candidatesTokenCount", 0)}
        return json.loads(text), usage
    raise LLMError(f"{model}: gave up after {retries} attempts")
