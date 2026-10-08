from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.db.client import init_db
from src.routes import admin, auth, chat, conversations, image, internal, media, v1, video


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Platform API", lifespan=lifespan)

# Auth travels in the Authorization header, never a cookie, so a wildcard origin
# cannot be used to ride an ambient session.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, conversations, chat, image, video, media, admin, internal, v1):
    app.include_router(module.router)


@app.get("/health")
def health():
    return {"status": "ok"}
