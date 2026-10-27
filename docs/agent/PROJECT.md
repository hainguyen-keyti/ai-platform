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
Web UI (React) --> API (Hono/TS) --> Worker (Python/cloakbrowser)
     |                  |                    |
     |                  v                    v
     |              SQLite DB         Browser Sessions
     |                  |                    |
     +------------------+-----> Storage (local/R2)
```

## Out of scope

- Billing/payment integration
- Public user registration (invite-only)
- Real-time collaboration features
- Mobile app

## Environments

| Environment | Exists | Deploy method | User-gated |
|-------------|--------|---------------|------------|
| Local       | Yes    | docker compose up | No |
| Staging     | No     | TBD | - |
| Production  | No     | TBD | Yes |
