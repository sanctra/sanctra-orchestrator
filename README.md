# sanctra-orchestrator

Cloud Run service written in Python FastAPI. Entry point for sessions.
Pipeline: STT -> RAG -> Gemini Live -> ElevenLabs TTS -> SadTalker avatar.
Streams audio first, returns MP4 when ready.

## Local dev

python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install uv
uv pip compile pyproject.toml -o requirements.txt
uv pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

## Docker

make build
make run
# push requires auth to Artifact Registry
make push

## Endpoints

- POST /session/start
- POST /turn/text (planned)
- WS   /turn/stream (planned)

## Secrets (GitHub)

- GAR_JSON_KEY
- ELEVENLABS_API_KEY
- GEMINI_API_KEY
- GCS_SERVICE_ACCOUNT_JSON
