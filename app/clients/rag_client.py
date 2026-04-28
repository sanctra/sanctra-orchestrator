from __future__ import annotations

import os
from typing import Dict, List

import httpx


class RagClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url if base_url is not None else os.getenv("RAG_SERVICE_URL", "")).rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0) if self.base_url else None

    async def retrieve(self, person_id: str, query: str, k: int = 5) -> List[Dict]:
        """Retrieves context from the RAG service.

        Missing RAG_SERVICE_URL should not prevent orchestrator import or local
        smoke tests; it degrades retrieval to an empty context until configured.
        """
        if not self.client or not self.base_url:
            return []

        try:
            response = await self.client.post(
                f"{self.base_url}/search",
                json={"person_id": person_id, "query": query, "k": k},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except httpx.HTTPStatusError as e:
            print(f"Error retrieving RAG context: {e.response.text}")
            return []
        except Exception as e:
            print(f"An unexpected error occurred in RAG client: {e}")
            return []
