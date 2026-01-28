from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import RequestLog, SiteAnalysis
from app.services.auth import get_current_active_user, get_current_user
import json
import time


async def log_request(
    request: Request,
    response_data: dict = None,
    status_code: int = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Логирование запроса пользователя"""
    try:
        # Чтение тела запроса
        body = await request.body()
        request_data = body.decode('utf-8') if body else None
        
        # Получение IP адреса
        ip_address = request.client.host if request.client else None
        
        # Создание записи лога
        log_entry = RequestLog(
            user_id=current_user.id,
            endpoint=request.url.path,
            method=request.method,
            request_data=request_data,
            response_data=json.dumps(response_data, ensure_ascii=False) if response_data else None,
            status_code=status_code or 200,
            ip_address=ip_address
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        # Не прерываем работу приложения при ошибке логирования
        print(f"Error logging request: {e}")


def log_site_analysis(
    user_id: int,
    url: str,
    analysis_data: dict,
    db: Session
):
    """Сохранение анализа сайта в базу данных"""
    try:
        analysis = SiteAnalysis(
            user_id=user_id,
            url=url,
            steps=json.dumps(analysis_data.get("steps", []), ensure_ascii=False),
            intermediate_results=json.dumps(
                analysis_data.get("intermediate_results", []),
                ensure_ascii=False
            ),
            final_analysis=json.dumps(
                analysis_data.get("final_analysis", {}),
                ensure_ascii=False
            )
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis.id
    except Exception as e:
        print(f"Error saving site analysis: {e}")
        return None


def get_user_history(
    user_id: int,
    db: Session,
    limit: int = 50
):
    """Получение истории запросов пользователя"""
    return db.query(RequestLog).filter(
        RequestLog.user_id == user_id
    ).order_by(RequestLog.created_at.desc()).limit(limit).all()


def get_user_analyses(
    user_id: int,
    db: Session,
    limit: int = 50
):
    """Получение истории анализов сайтов пользователя"""
    analyses = db.query(SiteAnalysis).filter(
        SiteAnalysis.user_id == user_id
    ).order_by(SiteAnalysis.created_at.desc()).limit(limit).all()
    
    # Десериализация JSON
    result = []
    for analysis in analyses:
        result.append({
            "id": analysis.id,
            "url": analysis.url,
            "steps": json.loads(analysis.steps) if analysis.steps else [],
            "intermediate_results": json.loads(analysis.intermediate_results) if analysis.intermediate_results else [],
            "final_analysis": json.loads(analysis.final_analysis) if analysis.final_analysis else {},
            "created_at": analysis.created_at.isoformat()
        })
    
    return result
