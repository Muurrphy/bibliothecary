"""Optional ElevenLabs HTTP streaming adapter with same-stream alignment.

The adapter makes one TTS request. Audio is never uploaded to a second model to
recover mouth timing. Importing this module does not require or expose an API key.
"""

from __future__ import annotations

import atexit
import base64
import json
import threading
import time

from ..phonemes import spans_from_elevenlabs
from .base import AlignedAudioChunk

_SESSION = None
_SESSION_LOCK = threading.Lock()


def _shared_session(requests):
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=2, pool_block=True)
            session.mount("https://", adapter)
            _SESSION = session
            atexit.register(session.close)
    return _SESSION


def prewarm(api_key: str) -> float:
    """Establish and authenticate a reusable connection without generating audio."""

    try:
        import requests
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install robot-lipsync[elevenlabs]") from error
    if not api_key:
        raise ValueError("api_key is required")
    started = time.perf_counter()
    with _shared_session(requests).get(
        "https://api.elevenlabs.io/v1/models",
        headers={"xi-api-key": api_key},
        timeout=(5, 10),
    ) as response:
        response.raise_for_status()
        _ = response.content
    return (time.perf_counter() - started) * 1000.0


class ElevenLabsHttpProvider:
    """Stream PCM and character timestamps over a pooled HTTP connection."""

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_flash_v2_5",
        output_format: str = "pcm_24000",
        reuse_session: bool = True,
    ) -> None:
        if not api_key or not voice_id:
            raise ValueError("api_key and voice_id are required")
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.reuse_session = reuse_session

    def stream(self, text: str, *, trace=None):
        if not text.strip():
            raise ValueError("text must not be empty")
        try:
            import requests
        except ImportError as error:  # pragma: no cover - optional dependency
            raise RuntimeError("install robot-lipsync[elevenlabs]") from error

        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            f"/stream/with-timestamps?output_format={self.output_format}"
        )
        if trace:
            trace.mark("tts_request_start")
        client = _shared_session(requests) if self.reuse_session else requests
        with client.post(
            url,
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            json={"text": text, "model_id": self.model_id},
            stream=True,
            timeout=(10, 30),
        ) as response:
            if trace:
                trace.mark("tts_response_headers")
            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                raise RuntimeError(f"ElevenLabs request failed with status {response.status_code}") from error
            for raw in response.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                message = json.loads(raw)
                audio = base64.b64decode(message.get("audio_base64") or "")
                if audio and trace:
                    trace.mark("tts_first_audio")
                alignment_data = (
                    message.get("alignment")
                    or message.get("normalized_alignment")
                    or message.get("normalizedAlignment")
                )
                spans = tuple(spans_from_elevenlabs(alignment_data)) if alignment_data else ()
                if audio or spans:
                    yield AlignedAudioChunk(audio, 24_000, spans)
        yield AlignedAudioChunk(b"", 24_000, (), True)
