from __future__ import annotations
import httpx
import os

class TtsClient:
    def __init__(self, api_key: str = os.getenv("ELEVENLABS_API_KEY", "")):
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set")
        self.api_key = api_key
        # TODO: Make voice_id configurable per person
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM") # Default: Rachel
        self.client = httpx.AsyncClient(
            base_url="https://api.elevenlabs.io/v1",
            headers={"xi-api-key": self.api_key},
            timeout=60.0,
        )

    async def synth(self, text: str) -> bytes | None:
        """Synthesizes text into speech audio bytes (WAV)."""
        try:
            response = await self.client.post(
                f"/text-to-speech/{self.voice_id}",
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
            response.raise_for_status()
            return response.content  # Returns audio bytes
        except httpx.HTTPStatusError as e:
            print(f"Error synthesizing audio: {e.response.text}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred in TTS client: {e}")
            return None