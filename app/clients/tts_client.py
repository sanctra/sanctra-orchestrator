# app/clients/tts_client.py
from __future__ import annotations
import os
import asyncio
import json
import httpx
import websockets
from typing import AsyncGenerator, Optional

class TtsClient:
    def __init__(
        self,
        http_url: str = os.getenv("TTS_SERVICE_HTTP_URL", ""),
        ws_url: str = os.getenv("TTS_SERVICE_WS_URL", ""),
        timeout_s: float = float(os.getenv("TIMEOUT_SECONDS", "30")),
    ):
        if not http_url:
            raise ValueError("TTS_SERVICE_HTTP_URL is not set")
        if not ws_url:
            raise ValueError("TTS_SERVICE_WS_URL is not set")
        self.http_url = http_url.rstrip("/")
        self.ws_url = ws_url
        self.http = httpx.AsyncClient(timeout=timeout_s)

    async def synth_wav(self, text: str, speaker_id: str, language: str = "en",
                        style: Optional[str] = None, emotion: Optional[str] = None) -> Optional[bytes]:
        """
        One-shot synthesis -> returns WAV bytes. Ideal for SadTalker pipeline.
        """
        payload = {
            "text": text,
            "speaker_id": speaker_id,
            "language": language,
            "params": {"style": style, "emotion": emotion},
        }
        try:
            resp = await self.http.post(f"{self.http_url}/tts", json=payload)
            resp.raise_for_status()
            return resp.content  # WAV bytes
        except httpx.HTTPStatusError as e:
            print(f"TTS synth error: {e.response.text}")
            return None
        except Exception as e:
            print(f"TTS synth unexpected error: {e}")
            return None

    async def stream_pcm16(self, text: str, speaker_id: str, language: str = "en",
                           style: Optional[str] = None, emotion: Optional[str] = None) -> AsyncGenerator[bytes, None]:
        """
        Low-latency streaming synthesis -> yields PCM16 chunks for barge-in UX.
        """
        payload = {
            "text": text,
            "speaker_id": speaker_id,
            "language": language,
            "params": {"style": style, "emotion": emotion},
        }
        async with websockets.connect(f"{self.ws_url}/tts/stream") as ws:
            await ws.send(json.dumps(payload))
            try:
                while True:
                    msg = await ws.recv()
                    if isinstance(msg, (bytes, bytearray)):
                        yield msg  # raw PCM16 frames
                    else:
                        # optional: stream JSON telemetry e.g. {"event":"end"}
                        meta = json.loads(msg)
                        if meta.get("event") == "end":
                            break
            except websockets.exceptions.ConnectionClosed:
                return

    async def enroll_speaker(self, speaker_id: str, clip_wav_bytes: bytes, language: str = "en") -> bool:
        """
        Optional: upload a reference clip for zero-shot voices.
        """
        files = {"clip": ("ref.wav", clip_wav_bytes, "audio/wav")}
        data = {"speaker_id": speaker_id, "language": language}
        try:
            resp = await self.http.post(f"{self.http_url}/speakers/enroll", data=data, files=files)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"TTS enroll error: {e}")
            return False

    async def close(self):
        await self.http.aclose()
