> **Superseded by the code, see `docs/agent/PROJECT.md`.** Kept as the design approved on 2026-09-23; where it and the code differ, the code is right.

# AI Platform - Multi-Model Browser Automation

**Date:** 2026-09-23  
**Status:** Approved  
**Author:** keyti

## Overview

Platform cho phép team sử dụng nhiều AI models (ChatGPT, Grok, Gemini) thông qua browser automation (cloakbrowser). Hỗ trợ 3 features chính: chat, image generation, video script generation.

### Goals
- Multi-model support với unified interface
- Multi-user với authentication
- Quản lý media và conversations per user
- SaaS-ready architecture, MVP cho team trước

### Non-Goals (MVP)
- Billing/payment
- Public registration (invite-only)
- Real-time collaboration

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Web UI (React + Tailwind)                          │
│  localhost:5173                                     │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  API Server (TypeScript + Hono)                     │
│  localhost:3000                                     │
│  - JWT Authentication                               │
│  - REST API                                         │
│  - Job queue management                             │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  Browser Worker (Python + cloakbrowser)             │
│  localhost:8000                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │  Browser Pool Manager                        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │ ChatGPT  │ │   Grok   │ │  Gemini  │    │   │
│  │  │ Session  │ │ Session  │ │ Session  │    │   │
│  │  └──────────┘ └──────────┘ └──────────┘    │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             
   ┌────────┐    ┌────────┐    
   │ SQLite │    │  Local │    
   │   DB   │    │ Storage│    
   └────────┘    └────────┘    
```

## Project Structure

```
ai-platform/
├── docker-compose.yml
├── .env.example
│
├── api/                    # REST API Server
│   ├── src/
│   │   ├── routes/
│   │   │   ├── auth.ts
│   │   │   ├── chat.ts
│   │   │   ├── image.ts
│   │   │   └── video.ts
│   │   ├── middleware/
│   │   │   ├── auth.ts
│   │   │   └── rateLimit.ts
│   │   ├── db/
│   │   │   ├── schema.ts
│   │   │   └── client.ts
│   │   └── index.ts
│   ├── package.json
│   └── Dockerfile
│
├── worker/                 # Browser automation service
│   ├── src/
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── chatgpt.py
│   │   │   ├── grok.py
│   │   │   └── gemini.py
│   │   ├── features/
│   │   │   ├── chat.py
│   │   │   ├── image.py
│   │   │   └── video.py
│   │   ├── pool.py
│   │   ├── queue.py
│   │   └── main.py
│   ├── sessions/
│   ├── requirements.txt
│   └── Dockerfile
│
├── web/                    # Frontend
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── lib/
│   ├── package.json
│   └── Dockerfile
│
├── storage/                # Local storage (dev)
│   ├── media/
│   ├── sessions/
│   └── db/
│
└── scripts/
    ├── login-chatgpt.py
    ├── login-grok.py
    └── login-gemini.py
```

## Components

### 1. Provider Interface

Abstract interface cho tất cả AI providers:

```python
class ProviderType(Enum):
    CHATGPT = "chatgpt"
    GROK = "grok"
    GEMINI = "gemini"

class FeatureType(Enum):
    CHAT = "chat"
    IMAGE = "image"
    VIDEO_SCRIPT = "video_script"

class BaseProvider(ABC):
    provider_type: ProviderType
    supported_features: List[FeatureType]
    
    async def initialize(self, session_path: str) -> bool
    async def chat(self, messages: List[Message]) -> GenerationResult
    async def generate_image(self, prompt: str, reference: str = None) -> GenerationResult
    async def generate_video_script(self, image_path: str, duration: int = 5) -> GenerationResult
    async def cleanup(self)
```

### 2. Database Schema

```sql
-- Users
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    role TEXT DEFAULT 'user',
    quota_remaining INTEGER DEFAULT 100,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions (auth)
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Conversations
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Messages
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Media
CREATE TABLE media (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    conversation_id TEXT REFERENCES conversations(id),
    provider TEXT NOT NULL,
    type TEXT NOT NULL,
    prompt TEXT,
    file_path TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Jobs (queue)
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,
    feature TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
```

### 3. API Routes

```
# Auth
POST /auth/register
POST /auth/login
POST /auth/logout
GET  /auth/me

# Conversations
GET  /conversations
POST /conversations
GET  /conversations/:id
DELETE /conversations/:id

# Features
POST /chat
POST /image/generate
POST /video/script

# Jobs
GET  /jobs/:id

# Media
GET  /media
GET  /media/:id
DELETE /media/:id

# Admin
GET  /admin/users
PUT  /admin/users/:id/quota
GET  /admin/providers
POST /admin/providers/:name/login
```

### 4. Browser Pool Manager

```python
class BrowserPool:
    def __init__(self, config: dict)
    async def initialize(self)
    async def execute(self, provider_name: str, feature: str, payload: dict) -> GenerationResult
    async def get_status(self) -> dict
```

Key behaviors:
- Lock per provider (1 request at a time per browser)
- Session persistence across restarts
- Health check endpoint for admin

### 5. Docker Compose

```yaml
services:
  api:
    build: ./api
    ports: ["3000:3000"]
    volumes:
      - ./storage/db:/data/db
      - ./storage/media:/data/media

  worker:
    build: ./worker
    ports: ["8000:8000"]
    volumes:
      - ./storage/sessions:/sessions
      - ./storage/media:/data/media
      - ./storage/db:/data/db
    shm_size: '2gb'

  web:
    build: ./web
    ports: ["5173:5173"]
```

### 6. Web UI

Pages:
- Login
- Chat (main interface)
- Gallery (media per user)
- Admin (users, providers)

Tech: React + Tailwind + Zustand + React Query

## Implementation Phases

### Phase 1: Foundation
- Project scaffold (docker-compose, directories)
- Database schema + migrations
- API server skeleton với auth
- Worker skeleton với provider interface

### Phase 2: ChatGPT Provider
- Migrate existing chatgpt_full.py vào provider interface
- Connect API → Worker
- Basic web UI cho chat

### Phase 3: Image & Video Features
- Image generation endpoint
- Video script generation endpoint
- Media storage và gallery

### Phase 4: Additional Providers
- Grok provider
- Gemini provider
- Provider health monitoring

### Phase 5: Polish
- Rate limiting
- Error handling
- Admin panel
- Documentation

## Testing Strategy

- Unit tests cho provider interface
- Integration tests cho API routes
- E2E tests cho critical flows (login, chat, image gen)

## Migration from Current Code

Existing files to migrate:
- `chatgpt_full.py` → `worker/src/providers/chatgpt.py`
- `chatgpt_cloak.py` → base cho login scripts
- `server.py` → reference cho worker HTTP interface

## Security Considerations

- JWT với short expiry (1h) + refresh tokens
- Password hashing với bcrypt
- Rate limiting per user
- Browser sessions stored locally (not in DB)
- Admin-only provider login endpoints

## Future Considerations (Post-MVP)

- Cloudflare deployment (Workers + D1 + R2)
- Multiple browser instances per provider
- WebSocket for real-time job updates
- Billing integration
- Public registration
