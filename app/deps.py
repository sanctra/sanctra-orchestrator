from typing import Optional
import os

class Settings:
    elevenlabs_api_key: Optional[str] = os.getenv("ELEVENLABS_API_KEY")
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    gcs_sa_json_b64: Optional[str] = os.getenv("GCS_SERVICE_ACCOUNT_JSON")

settings = Settings()
