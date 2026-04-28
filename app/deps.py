# app/deps.py
from typing import Optional
import os

class Settings:
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    gcs_sa_json_b64: Optional[str] = os.getenv("GCS_SERVICE_ACCOUNT_JSON")
    # Upstream service URLs are read directly by clients from env

settings = Settings()
