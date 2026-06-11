"""
Multi-LLM router with admin-switchable modes.
Mode hierarchy: free → balanced → quality → premium
Switch via settings.json or POST /admin/llm-mode
"""

import json
import time
import hashlib
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"
CACHE_DIR = Path(__file__).parent.parent / "cache"


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def save_mode(mode: str):
    settings = load_settings()
    valid = list(settings["llm"]["modes"].keys())
    if mode not in valid:
        raise ValueError(f"Invalid mode '{mode}'. Choose from: {valid}")
    settings["llm"]["mode"] = mode
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    mode: str
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    latency_ms: int = 0


class TokenTracker:
    """Tracks cumulative token usage and costs across the session."""

    def __init__(self):
        self._log_path = CACHE_DIR / "token_usage.json"
        CACHE_DIR.mkdir(exist_ok=True)
        self._load()

    def _load(self):
        if self._log_path.exists():
            with open(self._log_path) as f:
                self._data = json.load(f)
        else:
            self._data = {"total_cost_usd": 0.0, "total_tokens": 0, "calls": []}

    def record(self, response: LLMResponse):
        if response.cached:
            return
        entry = {
            "ts": int(time.time()),
            "model": response.model,
            "mode": response.mode,
            "tokens_in": response.tokens_input,
            "tokens_out": response.tokens_output,
            "cost_usd": response.cost_usd,
        }
        self._data["calls"].append(entry)
        self._data["total_cost_usd"] += response.cost_usd
        self._data["total_tokens"] += response.tokens_input + response.tokens_output
        # Keep last 1000 entries to avoid unbounded growth
        if len(self._data["calls"]) > 1000:
            self._data["calls"] = self._data["calls"][-1000:]
        with open(self._log_path, "w") as f:
            json.dump(self._data, f)

    def summary(self) -> dict:
        self._load()
        return {
            "total_cost_usd": round(self._data["total_cost_usd"], 4),
            "total_tokens": self._data["total_tokens"],
            "call_count": len(self._data["calls"]),
            "est_sgd": round(self._data["total_cost_usd"] * 1.35, 4),
        }


class ResponseCache:
    """File-based cache keyed on prompt hash + model to avoid re-calling LLMs."""

    def __init__(self, ttl_hours: int = 6):
        self._dir = CACHE_DIR / "llm_responses"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_hours * 3600

    def _key(self, prompt: str, model: str) -> str:
        return hashlib.md5(f"{model}:{prompt}".encode()).hexdigest()

    def get(self, prompt: str, model: str) -> Optional[str]:
        path = self._dir / f"{self._key(prompt, model)}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if time.time() - data["ts"] > self._ttl:
            path.unlink()
            return None
        return data["content"]

    def set(self, prompt: str, model: str, content: str):
        path = self._dir / f"{self._key(prompt, model)}.json"
        path.write_text(json.dumps({"ts": time.time(), "content": content}))


_tracker = TokenTracker()
_cache = ResponseCache()


def call(
    prompt: str,
    system: str = "",
    mode_override: Optional[str] = None,
    use_cache: bool = True,
    max_tokens: int = 1024,
) -> LLMResponse:
    """
    Main entry point. Routes to the correct LLM based on current mode.
    Falls back through the chain if a provider fails.
    """
    settings = load_settings()
    mode = mode_override or settings["llm"]["mode"]
    mode_cfg = settings["llm"]["modes"][mode]
    provider = mode_cfg["provider"]
    model = mode_cfg["model"]

    # Cache check
    cache_key = f"{system}\n{prompt}"
    if use_cache and settings["llm"]["cache_responses"]:
        cached = _cache.get(cache_key, model)
        if cached:
            return LLMResponse(
                content=cached, model=model, provider=provider,
                mode=mode, cached=True
            )

    t0 = time.time()
    try:
        content, tok_in, tok_out = _dispatch(provider, model, system, prompt, max_tokens)
    except Exception as e:
        # Fallback chain
        fallback_chain = settings["llm"]["fallback_chain"]
        for fallback_mode in fallback_chain:
            if fallback_mode == mode:
                continue
            try:
                fb_cfg = settings["llm"]["modes"][fallback_mode]
                content, tok_in, tok_out = _dispatch(
                    fb_cfg["provider"], fb_cfg["model"], system, prompt, max_tokens
                )
                mode = fallback_mode
                model = fb_cfg["model"]
                provider = fb_cfg["provider"]
                mode_cfg = fb_cfg
                break
            except Exception:
                continue
        else:
            raise RuntimeError(f"All LLM providers failed. Last error: {e}")

    latency = int((time.time() - t0) * 1000)
    cost = (
        tok_in * mode_cfg["cost_per_1k_tokens_input"] / 1000
        + tok_out * mode_cfg["cost_per_1k_tokens_output"] / 1000
    )

    resp = LLMResponse(
        content=content, model=model, provider=provider, mode=mode,
        tokens_input=tok_in, tokens_output=tok_out,
        cost_usd=cost, cached=False, latency_ms=latency,
    )
    _tracker.record(resp)

    if use_cache and settings["llm"]["cache_responses"]:
        _cache.set(cache_key, model, content)

    return resp


def _dispatch(provider: str, model: str, system: str, prompt: str, max_tokens: int):
    """Returns (content, tokens_in, tokens_out)."""
    if provider == "anthropic":
        return _call_anthropic(model, system, prompt, max_tokens)
    elif provider == "google":
        return _call_gemini(model, system, prompt, max_tokens)
    elif provider == "groq":
        return _call_groq(model, system, prompt, max_tokens)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _call_anthropic(model: str, system: str, prompt: str, max_tokens: int):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or "You are PropertyOS, a Singapore property intelligence assistant.",
        messages=[{"role": "user", "content": prompt}],
    )
    content = msg.content[0].text
    return content, msg.usage.input_tokens, msg.usage.output_tokens


def _call_gemini(model: str, system: str, prompt: str, max_tokens: int):
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    m = genai.GenerativeModel(model)
    resp = m.generate_content(
        full_prompt,
        generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
    )
    text = resp.text
    # Gemini doesn't always return token counts in basic API; estimate
    tok_in = len(full_prompt.split()) * 4 // 3
    tok_out = len(text.split()) * 4 // 3
    return text, tok_in, tok_out


def _call_groq(model: str, system: str, prompt: str, max_tokens: int):
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens
    )
    content = resp.choices[0].message.content
    usage = resp.usage
    return content, usage.prompt_tokens, usage.completion_tokens


def get_token_summary() -> dict:
    return _tracker.summary()


def get_current_mode() -> dict:
    settings = load_settings()
    mode = settings["llm"]["mode"]
    return {"mode": mode, **settings["llm"]["modes"][mode]}
