"""
Микросервис Health Check: liveness и readiness для оркестрации и мониторинга.
GET /health — всегда 200 (liveness).
GET /ready — 200 только если доступны БД и Redis (readiness).
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Опциональные зависимости для /ready
DATABASE_URL = os.environ.get("DATABASE_URL")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if getattr(app.state, "redis", None) is not None:
        await app.state.redis.aclose()


app = FastAPI(title="Health Check", lifespan=lifespan)


@app.get("/health")
def health():
    """Liveness: сервис запущен."""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness: БД и Redis доступны (если настроены)."""
    errors = []
    if DATABASE_URL and DATABASE_URL.strip().startswith("postgresql"):
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL.strip(), timeout=3)
            await conn.execute("SELECT 1")
            await conn.close()
        except Exception as e:
            errors.append(f"db:{str(e)}")
    if REDIS_URL and REDIS_URL.strip():
        try:
            import redis.asyncio as redis
            if not getattr(app.state, "redis", None):
                app.state.redis = redis.from_url(REDIS_URL.strip())
            await app.state.redis.ping()
        except Exception as e:
            errors.append(f"redis:{str(e)}")
    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "errors": errors},
        )
    return {"status": "ready"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
