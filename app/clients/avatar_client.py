from __future__ import annotations
import httpx
import os
from google.cloud import storage
import uuid

class AvatarClient:
    def __init__(self, base_url: str = os.getenv("AVATAR_SERVICE_URL", "")):
        if not base_url:
            raise ValueError("AVATAR_SERVICE_URL is not set")
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0) # Rendering can be slow
        self.gcs_client = storage.Client()
        self.bucket_name = os.getenv("AVATAR_UPLOADS_BUCKET", "")
        self.renders_bucket_name = os.getenv("AVATAR_RENDERS_BUCKET", "")
        # TODO: Get the image_gcs_uri for the person_id
        self.default_image_uri = os.getenv("DEFAULT_AVATAR_IMAGE_GCS_URI", "")

    async def _upload_to_gcs(self, data: bytes, extension: str) -> str:
        """Uploads data to GCS and returns the gs:// URI."""
        if not self.bucket_name:
            raise ValueError("AVATAR_UPLOADS_BUCKET is not set")
        bucket = self.gcs_client.bucket(self.bucket_name)
        blob_name = f"avatar-inputs/{uuid.uuid4()}.{extension}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(data)
        return f"gs://{self.bucket_name}/{blob_name}"

    async def render(self, session_id: str, audio_wav_bytes: bytes) -> str | None:
        """Renders an avatar video and returns the GCS URL of the MP4."""
        try:
            audio_gcs_uri = await self._upload_to_gcs(audio_wav_bytes, "wav")
            response = await self.client.post(
                f"{self.base_url}/render",
                json={
                    "session_id": session_id,
                    "image_gcs_uri": self.default_image_uri,
                    "audio_gcs_uri": audio_gcs_uri,
                    "fps": 30,
                    "out_res": "1080p",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("video_gcs_uri") # e.g., gs://avatars-renders/.../reply.mp4
        except httpx.HTTPStatusError as e:
            print(f"Error rendering avatar: {e.response.text}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred in Avatar client: {e}")
            return None