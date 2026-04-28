# Paperclip Project Guardrails

This repository is operator-owned and may contain in-progress human work.

Paperclip/autonomous agents must:
- Respect `.gitignore` and never force-add ignored files.
- Never commit or upload `.env`, credentials, secrets, private datasets, generated media, model weights, caches, venvs, or node/npm caches.
- If blocked by missing secrets, private data, content-safety concerns, or unclear ownership: stop, leave a short note/status, and work on another task instead of clobbering local work.
- Prefer small branches/commits and avoid rewriting operator work in progress.
- For sensitive-content projects, treat config/persona/prompt/data files as private unless explicitly approved.
