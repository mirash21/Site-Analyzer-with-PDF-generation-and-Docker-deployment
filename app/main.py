from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from app.routers import llm, auth, history
from app.database import init_db
from app.rate_limit import limiter
import os

app = FastAPI(title="LLM API", description="API для работы с LLM через Proxy API")

# Rate limiting (защита от перебора паролей и злоупотребления LLM)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Обработчик превышения лимита запросов."""
    # exc.detail может быть строкой или объектом Limit; безопасно извлекаем retry_after
    retry_after = getattr(exc.detail, "retry_after", None)
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов. Попробуйте позже."},
        headers=headers,
    )

# Настройка CORS: только конкретные домены (задаются в .env через CORS_ORIGINS)
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
] or ["http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(llm.router)
app.include_router(auth.router)
app.include_router(history.router)


@app.on_event("startup")
async def startup_event():
    """Инициализация базы данных при запуске"""
    init_db()


@app.get("/")
async def root():
    return {"message": "LLM API работает!"}


@app.get("/health")
async def health():
    return {"status": "ok"}
