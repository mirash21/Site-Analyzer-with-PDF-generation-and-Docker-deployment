from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.database import get_db
from app.services.auth import get_current_active_user
from app.models.models import User
from app.services.logger import get_user_history, get_user_analyses

router = APIRouter(prefix="/history", tags=["History"])


class RequestLogResponse(BaseModel):
    id: int
    endpoint: str
    method: str
    status_code: int
    created_at: str
    request_data: Optional[str] = None
    response_data: Optional[str] = None

    class Config:
        from_attributes = True


class SiteAnalysisResponse(BaseModel):
    id: int
    url: str
    steps: List[str]
    intermediate_results: List[dict]
    final_analysis: dict
    created_at: str


@router.get("/requests", response_model=List[RequestLogResponse])
async def get_requests_history(
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Получение истории всех запросов пользователя"""
    logs = get_user_history(current_user.id, db, limit)
    return logs


@router.get("/analyses", response_model=List[SiteAnalysisResponse])
async def get_analyses_history(
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Получение истории анализов сайтов"""
    return get_user_analyses(current_user.id, db, limit)


@router.get("/analysis/{analysis_id}")
async def get_analysis_by_id(
    analysis_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Получение конкретного анализа по ID"""
    from app.models.models import SiteAnalysis
    import json
    
    analysis = db.query(SiteAnalysis).filter(
        SiteAnalysis.id == analysis_id,
        SiteAnalysis.user_id == current_user.id
    ).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    
    return {
        "id": analysis.id,
        "url": analysis.url,
        "steps": json.loads(analysis.steps) if analysis.steps else [],
        "intermediate_results": json.loads(analysis.intermediate_results) if analysis.intermediate_results else [],
        "final_analysis": json.loads(analysis.final_analysis) if analysis.final_analysis else {},
        "created_at": analysis.created_at.isoformat()
    }
