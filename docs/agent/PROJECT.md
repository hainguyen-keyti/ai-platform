# PROJECT.md: static context (the agent reads it at the start of every session)

## What this is

AI Platform for browser-based automation of multiple AI models (ChatGPT, Grok, Gemini). Provides
unified interface for chat, image generation, and video script generation. Multi-user with
authentication, media management per user. Docker Compose deployment.

## Current stage and consequences

**Stage: PRE-LAUNCH (MVP for team)**

Consequences (obeyed absolutely):
- Data is test data that can be reset without ceremony
- No backward compatibility required
- No migration ceremony needed
- Breaking changes are allowed
- A stage change means rewriting this whole section

## Architecture on one screen

```
In Docker (docker compose up -d)          On the host, in WSL Ubuntu (./scripts/run-worker.sh)

Web UI (React/Vite) :5173
     |  HTTP, Authorization: Bearer <login JWT>
     v
API (FastAPI, Python) :3000  <-----------  Worker (Python, cloakbrowser) :8000
     |                  polls /internal/*,         |
     v                  X-Worker-Token             v
SQLite storage/db/app.db                    Browser profiles storage/sessions/<provider>/

Media: storage/media/ on local disk (no R2), written by the worker (and by the api for a picture
uploaded to /v1/images), served by the api.
The worker holds no database handle: it claims jobs from the api and posts results back.
```

## Out of scope

- Billing/payment integration
- Public user registration (invite-only)
- Real-time collaboration features
- Mobile app

## Environments

| Environment | Exists | Deploy method | User-gated |
|-------------|--------|---------------|------------|
| Local       | Yes    | `docker compose up -d` (api, web; the containers run in Docker Desktop with its WSL2 backend) plus the host worker (`./scripts/run-worker.sh`), both started from WSL Ubuntu on the Windows 11 machine, in `/mnt/d/keyti/ai-platform` | No |
| Staging     | No     | TBD | - |
| Production  | No     | TBD | Yes |
