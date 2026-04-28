from fastapi import APIRouter
from pydantic import BaseModel
import uuid

router = APIRouter()

class StartReq(BaseModel):
    person_id: str

@router.post("/start")
def start_session(req: StartReq):
    sid = str(uuid.uuid4())
    return {"session_id": sid}
