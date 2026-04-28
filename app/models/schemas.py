from pydantic import BaseModel

class StartSessionResponse(BaseModel):
    session_id: str
    live_api_token: str
