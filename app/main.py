from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import llm, auth, history
from app.database import init_db

app = FastAPI(title="LLM API", description="API для работы с LLM через Proxy API")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажите конкретные домены
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
