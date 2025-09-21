from __future__ import annotations
import httpx
import os
from typing import List, Dict

class RagClient:
    def __init__(self, base_url: str = os.getenv("RAG_SERVICE_URL", "")):
        if not base_url:
            raise ValueError("RAG_SERVICE_URL is not set")
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def retrieve(self, person_id: str, query: str, k: int = 5) -> List[Dict]:
        """Retrieves context from the RAG service."""
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