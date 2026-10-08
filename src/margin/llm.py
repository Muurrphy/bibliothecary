"""A tiny client for OpenAI-compatible APIs (no dependencies).

OpenAI, Moonshot/Kimi, DeepSeek, OpenRouter, Ollama and LM Studio all speak the
same ``/chat/completions`` dialect, so one client covers them: point
``base_url`` and ``model`` at the one you use.

    OPENAI_API_KEY=...                      # or MARGIN_API_KEY
    MARGIN_BASE_URL=https://api.openai.com/v1
    MARGIN_MODEL=...                        # the model that writes lessons and answers
"""

from __future__ import annotations

import json
import os
import urllib.error
import uuid
from collections.abc import Iterator
from typing import Any

from . import net


class APIError(RuntimeError):
    pass


class OpenAICompatible:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None,
                 timeout: float = 60.0) -> None:
        self.api_key = api_key or os.environ.get("MARGIN_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise APIError("set OPENAI_API_KEY (or MARGIN_API_KEY)")
        self.base_url = (base_url or os.environ.get("MARGIN_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("MARGIN_MODEL") or "gpt-5-mini"
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> OpenAICompatible | None:
        try:
            return cls()
        except APIError:
            return None

    # ---- transport -------------------------------------------------------------------
    def _open(self, path: str, body: bytes, content_type: str) -> net.Response:
        try:
            return net.request("POST", self.base_url + path, body, timeout=self.timeout, headers={
                "Authorization": f"Bearer {self.api_key}", "Content-Type": content_type})
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:500]
            raise APIError(f"{err.code} from {path}: {detail}") from err
        except (urllib.error.URLError, OSError) as err:
            raise APIError(f"cannot reach {self.base_url}: {getattr(err, 'reason', err)}") from err

    def _post(self, path: str, body: bytes, content_type: str) -> bytes:
        return self._open(path, body, content_type).read()

    def warm(self) -> None:
        """Open the connection before the first question needs it."""
        net.warm(self.base_url + "/models", {"Authorization": f"Bearer {self.api_key}"})

    # ---- text ------------------------------------------------------------------------
    def chat_json(self, system: str, user: str, *, model: str | None = None, max_tokens: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        if max_tokens:
            body["max_completion_tokens"] = max_tokens
        raw = self._post("/chat/completions", json.dumps(body).encode(), "application/json")
        try:
            content = json.loads(raw)["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as err:
            raise APIError(f"unexpected reply: {raw[:300]!r}") from err

    def chat_json_stream(self, system: str, user: str, *, model: str | None = None,
                         max_tokens: int | None = None) -> Iterator[str]:
        """The same JSON reply as ``chat_json``, as text pieces while the model writes it."""
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "stream": True,
        }
        if max_tokens:
            body["max_completion_tokens"] = max_tokens
        res = self._open("/chat/completions", json.dumps(body).encode(), "application/json")
        for line in res.lines():
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            try:
                choices = json.loads(data).get("choices") or []
            except json.JSONDecodeError:
                continue
            piece = (choices[0].get("delta") or {}).get("content") if choices else None
            if piece:
                yield piece

    # ---- audio -----------------------------------------------------------------------
    def speech(self, text: str, *, voice: str, model: str, instructions: str | None = None) -> bytes:
        body = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
        if instructions:
            body["instructions"] = instructions
        return self._post("/audio/speech", json.dumps(body).encode(), "application/json")

    def transcribe(self, audio: bytes, *, filename: str = "question.webm", mime: str = "audio/webm",
                   model: str | None = None, language: str | None = None) -> str:
        model = model or os.environ.get("MARGIN_STT_MODEL", "gpt-4o-mini-transcribe")
        boundary = uuid.uuid4().hex
        parts = [("model", model)] + ([("language", language)] if language else [])
        body = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in parts
        ) + (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()
        raw = self._post("/audio/transcriptions", body, f"multipart/form-data; boundary={boundary}")
        return json.loads(raw).get("text", "").strip()
