## API Endpoints

### Авторизация
- `POST /auth/register` - **ОТКЛЮЧЕНА** (403 Forbidden)
- `POST /auth/login` - Вход в систему (возвращает JWT токен)
- `GET /auth/me` - Получение информации о текущем пользователе

### Админ-панель (только admin)
- `POST /auth/admin/users` - Создать нового пользователя
- `GET /auth/admin/users` - Список всех пользователей
- `PUT /auth/admin/users/{id}` - Обновить пользователя
- `DELETE /auth/admin/users/{id}` - Удалить пользователя

### Анализ (требует авторизации)
- `POST /llm/analyze-site` - Анализ сайта
- `POST /llm/chat` - Простой запрос к LLM
- `POST /llm/chat-with-system` - Запрос с системным промптом
- `POST /llm/chat-json` - Запрос с JSON ответом

### История (требует авторизации)
- `GET /history/requests` - История всех запросов
- `GET /history/analyses` - История анализов сайтов
- `GET /history/analysis/{id}` - Получение конкретного анализа

## Установка и запуск

### Предварительные требования
- Python 3.11+
- Node.js 20+
- Docker (опционально)

### Локальный запуск

#### Бэкенд

```bash
# Создание виртуального окружения
python -m venv venv

# Активация (Windows)
venv\Scripts\activate

# Активация (Linux/Mac)
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Генерация секретного ключа (опционально)
python -c "import secrets; print(secrets.token_hex(32))"

# Создание администратора (ОБЯЗАТЕЛЬНО при первом запуске!)
python create_admin.py

# Запуск
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Фронтенд

```bash
cd frontend

# Установка зависимостей
npm install

# Запуск
npm run dev
```

### Запуск через Docker

```bash
# Запуск всех сервисов
docker-compose up

# Запуск в фоне
docker-compose up -d

# Остановка
docker-compose down
```

## API Endpoints

### Авторизация
- `POST /auth/register` - Регистрация нового пользователя
- `POST /auth/login` - Вход в систему (возвращает JWT токен)
- `GET /auth/me` - Получение информации о текущем пользователе

### Анализ (требует авторизации)
- `POST /llm/analyze-site` - Анализ сайта
- `POST /llm/chat` - Простой запрос к LLM
- `POST /llm/chat-with-system` - Запрос с системным промптом
- `POST /llm/chat-json` - Запрос с JSON ответом

### История (требует авторизации)
- `GET /history/requests` - История всех запросов
- `GET /history/analyses` - История анализов сайтов
- `GET /history/analysis/{id}` - Получение конкретного анализа

## Структура проекта

```
Final_project_curs/
├── app/
│   ├── main.py              # Конфигурация FastAPI
│   ├── database.py          # Настройка базы данных
│   ├── models/
│   │   └── models.py       # SQLAlchemy модели
│   ├── routers/
│   │   ├── auth.py         # Роутеры авторизации
│   │   ├── llm.py          # LLM эндпоинты
│   │   └── history.py      # История запросов
│   └── services/
│       ├── auth.py         # JWT и хеширование
│       ├── logger.py       # Логирование действий
│       ├── llm_client.py   # Клиент LLM
│       └── analyzer.py     # Анализатор сайтов
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LoginForm.jsx
│   │   │   ├── Dashboard.jsx
│   │   │   ├── HistoryPanel.jsx
│   │   │   ├── Loader.jsx
│   │   │   └── ResultCard.jsx
│   │   └── App.jsx
│   └── package.json
├── docker-compose.yml
├── Backend-Dockerfile
├── requirements.txt
└── .env                    # Конфигурация (SECRET_KEY, OPENAI_API_KEY и т.д.)
```

## Безопасность

### В продакшене ОБЯЗАТЕЛЬНО:

1. **Измените SECRET_KEY** в `.env` файле:
   ```bash
   # Генерация безопасного ключа
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **Настройте CORS** - укажите конкретные домены вместо `*`

3. **Используйте HTTPS** для всех запросов

4. **Ограничьте CORS origins** в `app/main.py`:
   ```python
   allow_origins=["https://yourdomain.com"]
   ```

5. **Используйте продакшн-базу данных** вместо SQLite (PostgreSQL, MySQL)

## База данных

### Структура таблиц

#### users
- `id` - уникальный идентификатор
- `email` - email пользователя (уникальный)
- `username` - имя пользователя (уникальное)
- `hashed_password` - хеш пароля (bcrypt)
- `created_at` - дата создания
- `is_active` - статус активности

#### request_logs
- `id` - уникальный идентификатор
- `user_id` - ID пользователя
- `endpoint` - эндпоинт запроса
- `method` - HTTP метод
- `request_data` - тело запроса
- `response_data` - ответ сервера
- `status_code` - статус код
- `created_at` - дата запроса
- `ip_address` - IP адрес

#### site_analyses
- `id` - уникальный идентификатор
- `user_id` - ID пользователя
- `url` - проанализированный URL
- `steps` - список шагов анализа (JSON)
- `intermediate_results` - промежуточные результаты (JSON)
- `final_analysis` - финальный анализ (JSON)
- `created_at` - дата анализа

## Лицензия

MIT License
