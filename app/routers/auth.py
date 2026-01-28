from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.models.models import User
from app.services.auth import (
    verify_password, get_password_hash, create_access_token,
    get_current_active_user, get_admin_user
)
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])


class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    role: str = "user"  # "user", "admin", "frontend_dev"


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class UserUpdate(BaseModel):
    email: EmailStr = None
    username: str = None
    role: str = None
    is_active: bool = None


@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Регистрация нового пользователя (ОТКЛЮЧЕНА - только для админа)

    ВНИМАНИЕ: Регистрация отключена. Для создания новых пользователей
    обратитесь к администратору через личный кабинет.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Регистрация отключена. Обратитесь к администратору для создания аккаунта."
    )


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Вход в систему"""
    # Поиск пользователя по username или email
    user = db.query(User).filter(
        (User.username == form_data.username) | (User.email == form_data.username)
    ).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Создание токена
    access_token = create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user)
    }


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Получение информации о текущем пользователе"""
    return current_user


# ========== Admin Endpoints ==========

@router.post("/admin/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Создание нового пользователя (только для администратора)"""
    # Проверка существования email
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким email уже существует"
        )

    # Проверка существования username
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким именем уже существует"
        )

    # Валидация роли
    valid_roles = ["user", "admin", "frontend_dev"]
    if user_data.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимая роль. Доступные: {', '.join(valid_roles)}"
        )

    # Создание пользователя
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hashed_password,
        role=user_data.role,
        created_by=admin.id
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.get("/admin/users", response_model=list[UserResponse])
async def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Получение списка всех пользователей (только для администратора)"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return users


@router.put("/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Обновление данных пользователя (только для администратора)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Нельзя изменить роль первого админа (защита от блокировки)
    if user.id == admin.id and user_update.role != "admin":
        raise HTTPException(
            status_code=400,
            detail="Нельзя изменить роль самого администратора"
        )

    # Валидация роли
    if user_update.role and user_update.role not in ["user", "admin", "frontend_dev"]:
        raise HTTPException(
            status_code=400,
            detail="Недопустимая роль"
        )

    # Обновление полей
    if user_update.email is not None:
        # Проверка уникальности email
        existing = db.query(User).filter(
            User.email == user_update.email,
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email уже занят")
        user.email = user_update.email

    if user_update.username is not None:
        # Проверка уникальности username
        existing = db.query(User).filter(
            User.username == user_update.username,
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
        user.username = user_update.username

    if user_update.role is not None:
        user.role = user_update.role

    if user_update.is_active is not None:
        # Нельзя деактивировать самого админа
        if user.id == admin.id and not user_update.is_active:
            raise HTTPException(
                status_code=400,
                detail="Нельзя деактивировать самого администратора"
            )
        user.is_active = user_update.is_active

    db.commit()
    db.refresh(user)
    return user


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    """Удаление пользователя (только для администратора)"""
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить самого себя"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    db.delete(user)
    db.commit()
    return {"message": "Пользователь удален"}
