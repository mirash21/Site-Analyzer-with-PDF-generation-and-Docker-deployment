"""
Скрипт для создания первого администратора системы.

Использование:
    python create_admin.py

Запустите этот скрипт один раз для создания учетной записи администратора.

ПРЕДВАРИТЕЛЬНО:
    - Установите зависимости: pip install -r requirements.txt
    - Или активируйте venv и запустите скрипт внутри него
"""

import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.database import init_db, SessionLocal
    from app.models.models import User
    from app.services.auth import get_password_hash
except ImportError as e:
    print("❌ Ошибка импорта модулей!")
    print(f"   {e}")
    print("\nУбедитесь, что:")
    print("   1. Установлены зависимости: pip install -r requirements.txt")
    print("   2. Активировано виртуальное окружение (venv)")
    sys.exit(1)


def create_admin_user():
    """Создание пользователя с ролью admin"""
    print("=== Создание администратора ===\n")

    # Инициализация базы данных
    print("Инициализация базы данных...")
    init_db()

    db = SessionLocal()

    # Проверка существования admin
    existing_admin = db.query(User).filter(User.username == "admin").first()
    if existing_admin:
        print(f"⚠️  Пользователь 'admin' уже существует!")
        print(f"   Email: {existing_admin.email}")
        print(f"   Роль: {existing_admin.role}")
        choice = input("\nХотите обновить пароль? (y/n): ").lower()
        if choice != 'y':
            print("Выход.")
            db.close()
            return

    # Ввод данных
    print("\nВведите данные для администратора:")
    email = input("Email: ").strip()
    if not email:
        print("❌ Email обязателен!")
        return

    username = input("Имя пользователя (по умолчанию 'admin'): ").strip() or "admin"

    password = input("Пароль: ").strip()
    if not password or len(password) < 6:
        print("❌ Пароль должен быть не менее 6 символов!")
        return

    # Создание или обновление admin
    if existing_admin:
        existing_admin.email = email
        existing_admin.hashed_password = get_password_hash(password)
        existing_admin.role = "admin"
        existing_admin.is_active = True
        print("\n✅ Пароль администратора обновлен!")
    else:
        # Проверка существующего email
        if db.query(User).filter(User.email == email).first():
            print("❌ Пользователь с таким email уже существует!")
            return

        hashed_password = get_password_hash(password)
        admin_user = User(
            email=email,
            username=username,
            hashed_password=hashed_password,
            role="admin",
            is_active=True,
            created_by=None  # Создан системой
        )
        db.add(admin_user)
        print("\n✅ Администратор создан!")

    db.commit()
    db.refresh(existing_admin if existing_admin else admin_user)

    print(f"\n=== Данные администратора ===")
    print(f"   Username: {username}")
    print(f"   Email: {email}")
    print(f"   Role: admin")
    print(f"\nТеперь вы можете войти через:")
    print(f"   Frontend: http://localhost:5173")
    print(f"   API: http://localhost:8000/docs")

    db.close()


if __name__ == "__main__":
    try:
        create_admin_user()
    except KeyboardInterrupt:
        print("\n\n❌ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
