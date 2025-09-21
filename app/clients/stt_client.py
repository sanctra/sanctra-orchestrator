from __future__ import annotations
import asyncio
import json
import os
import websockets
from typing import AsyncGenerator, Dict, Any

class SttClient:
    def __init__(self, base_url: str = os.getenv("ASR_SERVICE_URL", "")):
        if not base_url:
            raise ValueError("ASR_SERVICE_URL is not set")
        self.base_url = base_url
        self._ws: websockets.WebSocketClientProtocol | None = None

    async def connect(self):
        """Establishes a WebSocket connection."""
        self._ws = await websockets.connect(self.base_url)

    async def send_audio(self, chunk: bytes):
        """Sends an audio chunk to the ASR service."""
        if self._ws:
            await self._ws.send(chunk)

    async def receive_transcripts(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receives and yields transcription results."""
        if not self._ws:
            return

        try:
            while True:
                message = await self._ws.recv()
                if isinstance(message, str):
                    yield json.loads(message)
        except websockets.exceptions.ConnectionClosed:
            pass # Connection closed gracefully

    async def close(self):
        """Closes the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None