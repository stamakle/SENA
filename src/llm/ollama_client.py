"""Ollama client helpers for chat and embedding calls.

This module keeps all Ollama HTTP details in one place to simplify the rest
of the code.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable, List, Optional


def _post_json(url: str, payload: Dict, timeout_sec: int) -> Dict:
    """Send a JSON POST request and return the parsed JSON response."""

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {url}: {exc.reason}") from exc
    return json.loads(body)


def _get_json(url: str, timeout_sec: int) -> Dict:
    """Send a JSON GET request and return the parsed JSON response."""

    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {url}: {exc.reason}") from exc
    return json.loads(body)


def list_models(base_url: str, timeout_sec: int) -> List[str]:
    """Return a list of available Ollama models."""

    url = f"{base_url}/api/tags"
    data = _get_json(url, timeout_sec)
    models = data.get("models", [])
    return [model.get("name", "") for model in models if model.get("name")]


def resolve_model(base_url: str, model: str, timeout_sec: int) -> str:
    """Return the best matching model name available in Ollama."""

    available = list_models(base_url, timeout_sec)
    if model in available:
        return model
    for name in available:
        if name.startswith(f"{model}:"):
            return name
    return model


def ensure_model(base_url: str, model: str, timeout_sec: int) -> None:
    """Ensure the requested model is available in Ollama."""

    available = list_models(base_url, timeout_sec)
    if model in available:
        return
    if any(name.startswith(f"{model}:") for name in available):
        return
    if model not in available:
        raise RuntimeError(
            f"Ollama model '{model}' is not available. "
            f"Run: ollama pull {model}"
        )


# Step 5: Build the vector index (embeddings via Ollama).

def embed_text(base_url: str, model: str, text: str, timeout_sec: int) -> List[float]:
    """Return an embedding vector for the given text using Ollama."""

    url = f"{base_url}/api/embeddings"
    payload = {"model": model, "prompt": text}
    retries = int(os.getenv("OLLAMA_RETRY_COUNT", "2"))
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            data = _post_json(url, payload, timeout_sec)
            last_exc = None
            break
        except RuntimeError as exc:
            last_exc = exc
            msg = str(exc)
            if "Ollama HTTP 500" in msg or "EOF" in msg:
                if attempt < retries:
                    time.sleep(1.0 + attempt)
                    continue
            raise
    if last_exc is not None:
        raise last_exc
    if "embedding" not in data:
        raise RuntimeError(f"Ollama embedding response missing 'embedding': {data}")
    embedding = data.get("embedding", [])
    if not embedding:
        raise RuntimeError(
            "Ollama embedding returned an empty vector. "
            "Ensure the embedding model is pulled and Ollama is running."
        )
    return embedding


# Step 8: Build the answer context (chat via Ollama).

def chat_completion(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: int,
    num_predict: Optional[int] = None,
) -> str:
    """Generate a full response from Ollama in a single call."""

    url = f"{base_url}/api/chat"
    payload: Dict[str, object] = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if num_predict is not None:
        payload["options"] = {"num_predict": num_predict}
    data = _post_json(url, payload, timeout_sec)
    message = data.get("message", {})
    return message.get("content", "")


def chat_completion_stream(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: int,
    num_predict: Optional[int] = None,
) -> Iterable[str]:
    """Stream tokens from Ollama as they are generated."""

    url = f"{base_url}/api/chat"
    payload: Dict[str, object] = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if num_predict is not None:
        payload["options"] = {"num_predict": num_predict}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            for line in resp:
                if not line:
                    continue
                decoded = line.decode("utf-8").strip()
                if not decoded:
                    continue
                chunk = json.loads(decoded)
                if chunk.get("done"):
                    break
                message = chunk.get("message", {})
                content = message.get("content", "")
                if content:
                    yield content
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {url}: {exc.reason}") from exc
