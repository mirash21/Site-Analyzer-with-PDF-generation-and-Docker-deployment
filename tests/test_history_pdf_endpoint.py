"""Точки доступа PDF-отчёта: права, формат ответа и честная ошибка.

Скачивание должно отдавать именно PDF, чужой отчёт — не отдавать вовсе, а
проблема со шрифтом или вёрсткой — превращаться в понятное сообщение, а не в
пустой файл.
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models.models import Base, SiteAnalysis, User
from app.services.auth import get_current_active_user

RESULT_MARKDOWN = (
    "# Сегменты\n\n"
    "- **Технологи** — подбор по чертежу\n"
    "- Закупщики — цена\n\n"
    "| Сегмент | Потребность |\n| --- | --- |\n| Технологи | чертеж |\n"
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()

    db.add_all(
        [
            User(id=1, email="owner@example.com", username="owner", hashed_password="x", is_active=True),
            User(id=2, email="other@example.com", username="other", hashed_password="x", is_active=True),
        ]
    )
    db.add(
        SiteAnalysis(
            id=5,
            user_id=1,
            url="https://tateng.ru/",
            steps=json.dumps(["Определить сегменты"], ensure_ascii=False),
            intermediate_results=json.dumps(
                [{"step_number": 1, "step": "Определить сегменты", "result": RESULT_MARKDOWN}],
                ensure_ascii=False,
            ),
            final_analysis=json.dumps(
                {
                    "brief_analysis": "Поставщик инструмента.",
                    "ad_examples": [{"title": "Пост", "body": "Текст", "cta": "Позвонить"}],
                },
                ensure_ascii=False,
            ),
            created_at=datetime(2026, 11, 23, 19, 47, 38),
        )
    )
    db.add(
        SiteAnalysis(
            id=6,
            user_id=2,
            url="https://other.example/",
            steps=json.dumps(["чужой шаг"], ensure_ascii=False),
            intermediate_results="[]",
            final_analysis="{}",
            created_at=datetime(2026, 11, 23, 20, 0, 0),
        )
    )
    db.commit()

    yield db
    db.close()


def make_client(session, user_id=1):
    app.dependency_overrides[get_db] = lambda: session
    if user_id is not None:
        user = session.get(User, user_id)
        app.dependency_overrides[get_current_active_user] = lambda: user
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    """Переопределения не должны переходить между тестами."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(session):
    return make_client(session)


def test_pdf_endpoint_returns_pdf_file(client):
    response = client.get("/history/analysis/5/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert "analysis_tateng.ru_2026-11-23.pdf" in response.headers["content-disposition"]


def test_pdf_endpoint_hides_other_users_reports(session):
    client = make_client(session, user_id=1)
    response = client.get("/history/analysis/6/pdf")
    assert response.status_code == 404


def test_pdf_endpoint_requires_authorization(session):
    client = make_client(session, user_id=None)
    response = client.get("/history/analysis/5/pdf")
    assert response.status_code in (401, 403)


def test_broken_layout_reports_reason_instead_of_empty_file(session, monkeypatch):
    import app.routers.history as history_router
    from app.services.pdf_report import PDFRenderError

    def broken(payload):
        raise PDFRenderError("Не удалось сверстать PDF: сломанный блок")

    # Маршрут импортирует функцию напрямую, поэтому подменяем её в модуле маршрута.
    monkeypatch.setattr(history_router, "build_analysis_pdf", broken)
    client = make_client(session)

    response = client.get("/history/analysis/5/pdf")
    assert response.status_code == 500
    assert "сломанный блок" in response.json()["detail"]
