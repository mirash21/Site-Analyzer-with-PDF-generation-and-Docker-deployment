# Руководство по развертыванию на сервере

## Обзор

Это руководство поможет развернуть приложение на сервере `185.117.155.237` с автоматическим обновлением контейнеров из Docker Hub.

## Предварительные требования

### На локальной машине:

1. Git
2. Docker (для сборки образов)
3. Docker Hub аккаунт: `mirash2008`

### На сервере:

- Docker (установлен)
- Docker Compose (установлен)
- SSH доступ: `ihor@185.117.155.237`
- Bash доступен

## Шаг 1: Сборка и публикация Docker образов на локальной машине

### 1.1. Создайте Dockerfile для Frontend (если нет)

Файл: `frontend/Dockerfile`
```dockerfile
# Build stage
FROM node:18-alpine as builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 1.2. Создайте nginx.conf для Frontend

Файл: `frontend/nginx.conf`
```nginx
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    server {
        listen 80;
        server_name _;
        root /usr/share/nginx/html;
        index index.html;

        # SPA routing
        location / {
            try_files $uri $uri/ /index.html;
        }

        # API proxy
        location /api/ {
            proxy_pass http://backend:8000/api/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_cache_bypass $http_upgrade;
        }
    }
}
```

### 1.3. Сборка и публикация Backend образа

```bash
# Вход в Docker Hub (если не залогинен)
docker login

# Сборка образа
docker build -t mirash2008/backend:latest -f Backend-Dockerfile .

# Публикация на Docker Hub
docker push mirash2008/backend:latest
```

### 1.4. Сборка и публикация Frontend образа

```bash
# Сборка образа
docker build -t mirash2008/frontend:latest -f frontend/Dockerfile frontend/

# Публикация на Docker Hub
docker push mirash2008/frontend:latest
```

## Шаг 2: Развертывание на сервере

### 2.1. Подключение к серверу

```bash
ssh ihor@185.117.155.237
```

### 2.2. Создание директории проекта

```bash
mkdir -p ~/Final_project_curs
cd ~/Final_project_curs
```

### 2.3. Создание необходимых файлов

#### Создайте `docker-compose.production.yml`

Скопируйте содержимое файла `docker-compose.production.yml` с локальной машины.

#### Создайте файл `.env`

```bash
# Backend конфигурация
DATABASE_URL=sqlite:///./data/app.db
SECRET_KEY=your-secret-key-change-this
ENVIRONMENT=production

# API конфигурация (опционально)
OPENAI_API_KEY=your-openai-key-if-needed
```

#### Создайте директорию для данных

```bash
mkdir -p data logs
```

### 2.4. Запуск контейнеров

```bash
# Запуск в фоновом режиме
docker-compose -f docker-compose.production.yml up -d

# Проверка статуса
docker-compose -f docker-compose.production.yml ps

# Просмотр логов
docker-compose -f docker-compose.production.yml logs -f
```

## Шаг 3: Настройка автоматического обновления

### 3.1. Загрузка скрипта обновления

Скопируйте файл `update-containers.sh` на сервер:

```bash
# С локальной машины
scp update-containers.sh ihor@185.117.155.237:~/Final_project_curs/
```

Или создайте его прямо на сервере (содержимое из файла `update-containers.sh`).

### 3.2. Сделайте скрипт исполняемым

```bash
cd ~/Final_project_curs
chmod +x update-containers.sh
```

### 3.3. Тестовый запуск

```bash
./update-containers.sh
```

Проверьте лог-файл:

```bash
tail -f /var/log/update-containers.log
```

### 3.4. Настройка cron job

Загрузите скрипт `setup-cron.sh` на сервер:

```bash
# С локальной машины
scp setup-cron.sh ihor@185.117.155.237:~/Final_project_curs/
```

Запустите скрипт для настройки cron:

```bash
cd ~/Final_project_curs
sudo ./setup-cron.sh
```

Cron будет запускать скрипт каждый час (в 0 минут каждого часа).

## Шаг 4: Мониторинг и обслуживание

### 4.1. Проверка статуса контейнеров

```bash
docker-compose -f docker-compose.production.yml ps
```

### 4.2. Просмотр логов

```bash
# Все логи
docker-compose -f docker-compose.production.yml logs

# Логи конкретного сервиса
docker-compose -f docker-compose.production.yml logs backend
docker-compose -f docker-compose.production.yml logs frontend

# Последние N строк
docker-compose -f docker-compose.production.yml logs --tail=50

# Отслеживание в реальном времени
docker-compose -f docker-compose.production.yml logs -f
```

### 4.3. Просмотр логов обновлений

```bash
# Все логи обновлений
cat /var/log/update-containers.log

# Последние строки
tail -f /var/log/update-containers.log

# Поиск ошибок
grep ERROR /var/log/update-containers.log
```

### 4.4. Ручное обновление

```bash
cd ~/Final_project_curs
./update-containers.sh
```

### 4.5. Перезапуск сервисов

```bash
# Пересоздать все контейнеры
docker-compose -f docker-compose.production.yml up -d --force-recreate

# Перезапустить конкретный сервис
docker-compose -f docker-compose.production.yml restart backend
docker-compose -f docker-compose.production.yml restart frontend
```

### 4.6. Остановка сервисов

```bash
# Остановка всех сервисов
docker-compose -f docker-compose.production.yml down

# Остановка и удаление volumes
docker-compose -f docker-compose.production.yml down -v
```

### 4.7. Проверка использования ресурсов

```bash
# Статистика контейнеров
docker stats

# Информация о контейнере
docker inspect backend-1
docker inspect frontend-1
```

## Шаг 5: Обновление приложений

### 5.1. На локальной машине:

1. Внесите изменения в код
2. Соберите новые образы:

```bash
docker build -t mirash2008/backend:latest -f Backend-Dockerfile .
docker push mirash2008/backend:latest

docker build -t mirash2008/frontend:latest -f frontend/Dockerfile frontend/
docker push mirash2008/frontend:latest
```

### 5.2. Автоматическое обновление на сервере:

Cron job автоматически проверит и подтянет новые образы через час.

### 5.3. Ручное обновление на сервере:

```bash
cd ~/Final_project_curs
./update-containers.sh
```

## Настройка Firewall

Откройте необходимые порты на сервере:

```bash
# Открыть порт 80 (HTTP)
sudo ufw allow 80

# Открыть порт 443 (HTTPS) если нужно
sudo ufw allow 443

# Открыть порт 8000 (Backend) если нужен прямой доступ
sudo ufw allow 8000

# Проверить статус
sudo ufw status
```

## Настройка SSL (опционально)

Для HTTPS используйте Let's Encrypt с certbot:

```bash
# Установка certbot
sudo apt-get update
sudo apt-get install certbot python3-certbot-nginx

# Получение сертификата
sudo certbot --nginx -d your-domain.com

# Автоматическое обновление сертификата
sudo certbot renew --dry-run
```

## Доступ к приложению

После развертывания приложение будет доступно по адресу:

- Frontend: `http://185.117.155.237`
- Backend API: `http://185.117.155.237/api/` (через nginx прокси)
- Backend прямой доступ: `http://185.117.155.237:8000`

## Решение проблем

### Контейнеры не запускаются

```bash
# Проверьте логи
docker-compose -f docker-compose.production.yml logs

# Проверьте статус
docker-compose -f docker-compose.production.yml ps -a

# Перезапустите
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml up -d
```

### Проблемы с правами доступа

```bash
# Измените владельца директории data
sudo chown -R $USER:$USER data

# Измените права на скрипт
chmod +x update-containers.sh
```

### Cron job не работает

```bash
# Проверьте cron tasks
crontab -l

# Проверьте логи cron
grep CRON /var/log/syslog

# Проверьте логи скрипта
tail -f /var/log/update-containers.log

# Протестируйте скрипт вручную
cd ~/Final_project_curs
./update-containers.sh
```

### Проблемы с сетью

```bash
# Проверьте сеть
docker network ls
docker network inspect app-network

# Пересоздайте сеть
docker network rm app-network
docker-compose -f docker-compose.production.yml up -d
```

## Структура проекта на сервере

```
~/Final_project_curs/
├── docker-compose.production.yml  # Production конфиг
├── .env                            # Переменные окружения
├── update-containers.sh            # Скрипт автообновления
├── setup-cron.sh                   # Скрипт настройки cron
├── data/                           # Директория для базы данных
│   └── app.db                      # SQLite база данных
└── logs/                           # Логи приложения
    ├── backend.log
    └── frontend.log
```

## Контакты

При возникновении проблем проверьте логи:

- Контейнеры: `docker-compose -f docker-compose.production.yml logs`
- Обновления: `/var/log/update-containers.log`
- Система: `/var/log/syslog`
