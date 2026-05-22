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
- POST /packages
- GET  /packages/{package_id}
- PUT  /packages/{package_id}
- GET  /packages/{package_id}/status
- PATCH /packages/{package_id}/lifecycle
- POST /packages/{package_id}/authority-preflight
- POST /packages/{package_id}/artifact-manifests

## Secrets (GitHub)

- GAR_JSON_KEY
- ELEVENLABS_API_KEY
- GEMINI_API_KEY
- GCS_SERVICE_ACCOUNT_JSON

## Async package authoring scaffold

The `/packages` endpoints provide the first consultant-led async memorial package authoring seam. Package bundles use Sanctra-native ids, are stored as JSON under `SANCTRA_PACKAGE_STORE_DIR` (default: system temp outside the source repo), and keep generated media/model artifacts as external storage references only. Voice/video artifact preflight requires accepted or limited authority records for the requested likeness use.

The backend lifecycle spine is intentionally non-media-pipeline-specific:

- Package state moves through `draft`, intake/review/production states, `approved`, `delivered`, `paused`, `takedown_requested`, and `revoked`.
- `GET /packages/{package_id}/status` returns package status, consultant white-glove entitlement, artifact manifest refs, generation refs, output refs, retention policy, and revocation refs.
- `PATCH /packages/{package_id}/lifecycle` records a lifecycle event and, for `revoked` or `takedown_requested`, marks package artifact manifests `revoked` or `removed` while retaining manifest hashes and audit refs.
- Tier entitlement is checked before storing manifests: `async_starter` is text-only; `guided_consultant` supports text, audio, image, and future video with consultant review.
- Artifact references stay as governed manifests, not embedded generated media. Text outputs must declare UTF-8 text or PDF metadata, audio outputs must use WAV/MP3 refs with `sha256:` hashes, image outputs require `model_manifest` and `dataset_manifest` refs, and future video placeholders must declare `video/mp4` with an H.264 1080p media contract.
