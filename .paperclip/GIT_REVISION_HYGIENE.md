# Paperclip Git Revision Hygiene SOP

Purpose: preserve useful revision history, prevent autonomous agents from clobbering operator work, and keep private/sensitive files out of GitHub.

## Default rule
Every Paperclip coding agent must leave repo state better than it found it:

1. Inspect `git status --short` before editing.
2. Respect existing dirty files. If files are unrelated to your task, do not overwrite them.
3. Read `.paperclip/PROJECT_GUARDRAILS.md` when present.
4. Respect `.gitignore`; never use `git add -f` unless the issue explicitly approves it.
5. Before committing, scan changed/staged files for secrets, credentials, private datasets, adult/private configs, generated media, model weights, venvs, node/npm caches, and build caches.
6. Commit coherent changes with a useful message that names the issue and outcome.
7. Push to the configured GitHub remote/branch when safe.
8. If blocked by dirty unrelated work, missing auth, secrets/private data, or unclear ownership: stop, comment on the issue, mark blocked or skip to other work. Do not clobber.

## Commit message format
Use concise, searchable messages:

```text
CON-123: implement package validation scaffold

- Added schema validation entrypoint
- Added smoke test fixture
- Left deploy disabled; headless auth owns GCP deploys
```

If the issue id is unknown, use the project and change summary:

```text
Sanctra: disable automatic GCP deploy in CI
```

## Branching
- Use the current branch if Paperclip already checked one out for the issue.
- Prefer `paperclip/<issue-id>-short-slug` for new work branches.
- Do not commit to `main` for risky/incomplete work unless the repo already uses `main` for safe backup snapshots and the change is small/safe.

## Push/remotes
- Existing private root backups:
  - `conciergecare-management/Textloom`
  - `conciergecare-management/Theonome`
  - `conciergecare-management/Narratron`
  - `conciergecare-management/Sanctra`
- Existing project remotes:
  - `conciergecare-management/SwiftNurse`
  - `conciergecare-management/SmartFront`
  - `sanctra/*` service repos
- Use SSH remotes where configured.
- `gh` API access from OpenClaw exec uses `/home/node/.openclaw/workspace/ops/scripts/gh_runtime_token.sh` because `GITHUB_TOKEN` is intentionally filtered from child shell env.

## PRs
Agents may create PRs only when the issue/task asks for review or integration. Otherwise push the branch and report the branch/commit in the Paperclip comment.

Recommended PR body:

```markdown
## Summary
- ...

## Verification
- ...

## Guardrails
- Secrets/private data scan: passed
- Generated media/model/data excluded: yes
- GCP deploy/push automation touched: no / intentionally disabled

Issue: CON-123
```

## GCP deploy guardrail
For Sanctra, do not re-enable automatic GitHub Actions push/deploy to GCP. Current direction is headless auth / impersonation accounts. GitHub Actions may run build/test checks, but automatic `google-github-actions/auth`, `gcloud`, `gsutil`, `docker push`, Terraform apply, or Cloud Run deploy requires explicit operator approval.

## Sensitive project notes
- Textloom may contain adult/private configs or datasets. Do not upload config/data directories or dataset artifacts to GitHub unless explicitly approved.
- Voice/video/persona projects may contain private likeness/audio/video data. Keep generated media, source samples, model weights, and persona datasets out of Git by default.
- Theonome corpora/source material should remain private unless specifically curated for commit.
