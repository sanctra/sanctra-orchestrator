from __future__ import annotations
import os
import google.generativeai as genai
from typing import List, Dict

class GeminiClient:
    def __init__(self, api_key: str = os.getenv("GEMINI_API_KEY", "")):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def _build_prompt(self, query: str, rag_context: List[Dict]) -> str:
        context_str = "\n\n".join([item.get('text', '') for item in rag_context])
        prompt = f"""
You are a digital avatar representing a person. Based on the following context, answer the user's query in a conversational, first-person style.

Context:
---
{context_str}
---

User Query: "{query}"

Your Answer:
"""
        return prompt

    async def generate_response(self, query: str, rag_context: List[Dict]) -> str:
        """Generates a response using Gemini, grounded in RAG context."""
        if not query:
            return "I'm not sure how to respond to that. Could you say a bit more?"

        full_prompt = self._build_prompt(query, rag_context)
        try:
            response = await self.model.generate_content_async(full_prompt)
            return response.text
        except Exception as e:
            print(f"Error generating response from Gemini: {e}")
            return "I'm having a little trouble thinking right now. Please try again in a moment."