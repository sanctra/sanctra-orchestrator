import asyncio
import datetime
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from google.cloud import storage

from app.clients.rag_client import RagClient
from app.clients.gemini_client import GeminiClient
from app.clients.tts_client import TtsClient
from app.clients.avatar_client import AvatarClient
from app.clients.stt_client import SttClient

router = APIRouter()

# --- Clients (in a real app, use dependency injection) ---
rag_client = RagClient()
gemini_client = GeminiClient()
tts_client = TtsClient()
avatar_client = AvatarClient()
gcs_client = storage.Client()

# --- In-memory state for SSE notifications ---
sse_queues: Dict[str, asyncio.Queue] = {}

class TurnRequest(BaseModel):
    session_id: str
    person_id: str
    text: str

def create_signed_url(gcs_uri: str) -> str:
    """Creates a signed URL for a GCS object."""
    if not gcs_uri.startswith("gs://"):
        return gcs_uri # Not a GCS URI, return as is
    
    bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    # URL is valid for 15 minutes.
    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=15),
        method="GET",
    )
    return url

async def run_pipeline(session_id: str, person_id: str, text: str):
    """The core logic pipeline, now with error handling and signed URLs."""
    queue = sse_queues.get(session_id)
    try:
        # 1. RAG retrieval
        context = await rag_client.retrieve(person_id=person_id, query=text)
        
        # 2. Gemini generation
        gemini_response_text = await gemini_client.generate_response(text, context)
        if queue:
            await queue.put({"event": "agent_text", "data": gemini_response_text})
        
        # 3. TTS synthesis
        audio_wav = await tts_client.synth(gemini_response_text)
        if not audio_wav:
            raise RuntimeError("TTS synthesis failed")
            
        # 4. Avatar Rendering (as a background task)
        video_gcs_uri = await avatar_client.render(session_id, audio_wav)
        if video_gcs_uri:
            signed_video_url = create_signed_url(video_gcs_uri)
            if queue:
                await queue.put({"event": "video_url", "data": signed_video_url})
        else:
            raise RuntimeError("Avatar rendering failed")

    except Exception as e:
        print(f"Error in pipeline for session {session_id}: {e}")
        if queue:
            await queue.put({"event": "error", "data": f"An internal error occurred: {e}"})


@router.post("")
async def text_turn(req: TurnRequest):
    asyncio.create_task(run_pipeline(req.session_id, req.person_id, req.text))
    return {"status": "processing"}

@router.get("/events")
async def sse_events(request: Request):
    session_id = request.query_params.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}, 400
    
    sse_queues[session_id] = asyncio.Queue()

    async def event_generator():
        try:
            while True:
                message = await sse_queues[session_id].get()
                yield message
        except asyncio.CancelledError:
            if session_id in sse_queues:
                del sse_queues[session_id]
            print(f"SSE client disconnected for session {session_id}, cleaning up.")

    return EventSourceResponse(event_generator())


@router.websocket("/stream")
async def stream_turn(websocket: WebSocket, session_id: str, person_id: str):
    await websocket.accept()
    stt = SttClient()
    await stt.connect()
    
    async def stt_receiver():
        async for transcript in stt.receive_transcripts():
            queue = sse_queues.get(session_id)
            if transcript.get("type") == "final" and transcript.get("text"):
                asyncio.create_task(run_pipeline(session_id, person_id, transcript["text"]))
            elif transcript.get("type") == "partial" and queue:
                await queue.put({"event": "interim", "data": transcript["text"]})

    receiver_task = asyncio.create_task(stt_receiver())

    try:
        while True:
            audio_chunk = await websocket.receive_bytes()
            await stt.send_audio(audio_chunk)
    except WebSocketDisconnect:
        print(f"Client disconnected audio stream for session {session_id}")
    finally:
        await stt.close()
        receiver_task.cancel()