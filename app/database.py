from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

# Автоопределение правильного пути к базе данных
# Для Docker: sqlite:////app/data/app.db
# Для локального запуска: sqlite:///./data/app.db

# Проверяем, находимся ли мы в Docker контейнере
is_docker = os.path.exists('/.dockerenv')

if is_docker:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////app/data/app.db")
else:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

# Создаем директорию для базы данных, если её нет
if "sqlite" in DATABASE_URL:
    db_path = DATABASE_URL.replace("sqlite:///", "").replace("sqlite:////", "")
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), "..", db_path)
    
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    # Обновляем путь, если он относительный
    if not os.path.isabs(db_path):
        db_path = os.path.abspath(db_path)
        DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Получение сессии базы данных"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Инициализация базы данных - создание всех таблиц"""
    from app.models import models
    models.Base.metadata.create_all(bind=engine)
