from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, HttpUrl
import os
from sqlalchemy.orm import Session
from app.services.llm_client import LLMClient
from app.services.analyzer import SiteAnalyzer
from app.services.auth import get_current_active_user
from app.services.logger import log_site_analysis
from app.models.models import User
from app.database import get_db

router = APIRouter(prefix="/llm", tags=["LLM"])

# Инициализация клиента
base_url = os.getenv("OPENAI_API_BASE")
api_key = os.getenv("OPENAI_API_KEY")

if not base_url or not api_key:
    raise ValueError("Не заданы переменные окружения OPENAI_API_BASE или OPENAI_API_KEY")

llm_client = LLMClient(base_url=base_url, api_key=api_key)
site_analyzer = SiteAnalyzer(llm_client=llm_client)


class ChatRequest(BaseModel):
    prompt: str


class ChatWithSystemRequest(BaseModel):
    system_prompt: str
    user_prompt: str


class ChatJsonRequest(BaseModel):
    system_prompt: str
    user_prompt: str
    jsonStandard: str = "json_object"


class AnalyzeRequest(BaseModel):
    url: str


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Простой запрос к LLM. Требует авторизации.

    Args:
        request: Объект с полем prompt

    Returns:
        Текст ответа модели
    """
    try:
        response = llm_client.chat(request.prompt)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-with-system")
async def chat_with_system(
    request: ChatWithSystemRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Запрос к LLM с системным промптом. Требует авторизации.

    Args:
        request: Объект с полями system_prompt и user_prompt

    Returns:
        Текст ответа модели
    """
    try:
        response = llm_client.chat_with_system(request.system_prompt, request.user_prompt)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-json")
async def chat_json(
    request: ChatJsonRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Запрос к LLM со структурированным ответом в формате JSON. Требует авторизации.

    Args:
        request: Объект с полями system_prompt, user_prompt и jsonStandard

    Returns:
        Словарь с парсированным JSON-ответом
    """
    try:
        response = llm_client.chat_json(request.system_prompt, request.user_prompt)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-site")
async def analyze_site(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> dict:
    """
    Анализ сайта для выявления идей для таргетированной рекламы. Требует авторизации.

    Endpoint выполняет следующие шаги:
    1. Скачивает HTML-код сайта по URL
    2. Очищает HTML от тегов, оставляя только текст
    3. Генерирует список шагов для анализа через LLM
    4. Выполняет каждый шаг анализа
    5. Формирует финальный анализ с примерами рекламных постов
    6. Сохраняет результат в базу данных

    Args:
        request: Объект с полем url (ссылка на сайт для анализа)

    Returns:
        Словарь, содержащий:
        - url: исходный URL
        - steps: список шагов анализа
        - intermediate_results: результаты каждого шага
        - final_analysis: итоговый анализ с рекламными постами

    Raises:
        HTTPException 400: Если не удалось скачать или распарсить сайт
        HTTPException 500: При внутренней ошибке обработки
    """
    try:
        result = site_analyzer.analyze_site(request.url)
        
        # Сохранение анализа в базу данных
        log_site_analysis(current_user.id, request.url, result, db)
        
        return result
    except Exception as e:
        error_msg = str(e)
        if "не удалось скачать" in error_msg.lower() or "не удалось распарсить" in error_msg.lower():
            raise HTTPException(status_code=400, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
