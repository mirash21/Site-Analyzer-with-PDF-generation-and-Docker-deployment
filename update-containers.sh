#!/bin/bash

# ==========================================
# AUTO-UPDATE SCRIPT FOR DOCKER CONTAINERS
# ==========================================
# Скрипт проверяет новые версии образов на Docker Hub
# и обновляет контейнеры если есть изменения
# ==========================================
# Запуск: ./update-containers.sh
# Cron: 0 * * * * /path/to/update-containers.sh >> /var/log/update-containers.log 2>&1
# ==========================================

# ============================
# КОНФИГУРАЦИЯ
# ============================
# Docker Hub пользователь (измените если нужно)
DOCKER_USERNAME="mirash2008"

# Образы для проверки (формат: образ:тег)
# Измените версии если используете конкретные теги
BACKEND_IMAGE="${DOCKER_USERNAME}/backend:latest"
FRONTEND_IMAGE="${DOCKER_USERNAME}/frontend:latest"

# Путь к docker-compose файлу (production конфиг)
COMPOSE_FILE="docker-compose.production.yml"

# Имена контейнеров для логов
BACKEND_CONTAINER="backend-1"
FRONTEND_CONTAINER="frontend-1"

# Лог-файл для записи действий
LOG_FILE="/var/log/update-containers.log"

# ============================
# ФУНКЦИИ
# ============================

# Функция логирования
log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $1"
}

# Функция получения digest образа из Docker Hub
get_remote_digest() {
    local image=$1
    local image_name=${image%%:*}
    local tag=${image##*:}
    
    # Получаем digest через Docker API
    local digest=$(docker pull $image --quiet 2>&1 | head -n1)
    if [[ $? -eq 0 ]]; then
        # Получаем digest локально после pull
        docker image inspect $image --format='{{.RepoDigests[0]}}' 2>/dev/null
    fi
}

# Функция получения digest локального образа
get_local_digest() {
    local image=$1
    docker image inspect $image --format='{{.RepoDigests[0]}}' 2>/dev/null
}

# Функция проверки и обновления образа
check_and_update_image() {
    local image=$1
    local container_name=$2
    
    log "=== Проверка образа: $image ==="
    
    # Проверяем существует ли локальный образ
    local local_exists=$(docker image inspect $image >/dev/null 2>&1 && echo "yes" || echo "no")
    
    if [[ "$local_exists" == "no" ]]; then
        log "Локальный образ не найден, загрузка..."
        docker pull $image
        return 1
    fi
    
    # Получаем digest локального и удаленного образа
    local local_digest=$(get_local_digest $image)
    
    # Пытаемся получить новую версию
    log "Проверка обновлений на Docker Hub..."
    docker pull $image 2>&1 | grep -i "newer image available" >/dev/null
    
    if [[ $? -eq 0 ]]; then
        log "Найдена новая версия образа: $image"
        return 0
    else
        log "Образ $image актуален, обновлений нет"
        return 1
    fi
}

# Функция перезапуска контейнера
restart_container() {
    local container_name=$1
    
    log "Перезапуск контейнера: $container_name"
    docker-compose -f $COMPOSE_FILE up -d --no-deps --build $container_name
    
    if [[ $? -eq 0 ]]; then
        log "Контейнер $container_name успешно перезапущен"
        return 0
    else
        log "ОШИБКА при перезапуске контейнера $container_name"
        return 1
    fi
}

# ============================
# ОСНОВНОЙ БЛОК
# ============================

# Запись в лог-файл
{
    log "========================================="
    log "НАЧАЛО ПРОВЕРКИ ОБНОВЛЕНИЙ"
    log "========================================="
    
    # Переходим в директорию проекта
    # Укажите полный путь к вашей папке проекта
    cd /home/ihor/Final_project_curs || {
        log "ОШИБКА: Не удалось перейти в директорию проекта"
        exit 1
    }
    
    log "Рабочая директория: $(pwd)"
    
    # Флаг обновления
    UPDATE_NEEDED=false
    
    # Проверка backend
    log ""
    check_and_update_image "$BACKEND_IMAGE" "$BACKEND_CONTAINER"
    BACKEND_UPDATE_NEEDED=$?
    
    # Проверка frontend
    log ""
    check_and_update_image "$FRONTEND_IMAGE" "$FRONTEND_CONTAINER"
    FRONTEND_UPDATE_NEEDED=$?
    
    # Если есть обновления
    if [[ $BACKEND_UPDATE_NEEDED -eq 0 ]] || [[ $FRONTEND_UPDATE_NEEDED -eq 0 ]]; then
        UPDATE_NEEDED=true
        log ""
        log "========================================="
        log "НАЙДЕНЫ ОБНОВЛЕНИЯ, ПЕРЕЗАПУСК КОНТЕЙНЕРОВ"
        log "========================================="
        
        # Останавливаем старые контейнеры
        log "Остановка текущих контейнеров..."
        docker-compose -f $COMPOSE_FILE down
        
        # Поднимаем новые контейнеры
        log "Запуск новых контейнеров..."
        docker-compose -f $COMPOSE_FILE up -d
        
        # Проверяем статус контейнеров
        log ""
        log "Проверка статуса контейнеров..."
        docker-compose -f $COMPOSE_FILE ps
        
        # Проверяем логи
        log ""
        log "Логи новых контейнеров (последние 10 строк):"
        docker-compose -f $COMPOSE_FILE logs --tail=10
        
        log ""
        log "========================================="
        log "ОБНОВЛЕНИЕ ЗАВЕРШЕНО УСПЕШНО"
        log "========================================="
    else
        log ""
        log "========================================="
        log "ОБНОВЛЕНИЙ НЕ НАЙДЕНО"
        log "========================================="
        log "Все контейнеры работают с актуальными версиями образов"
        
        # Показываем текущий статус
        log ""
        log "Текущий статус контейнеров:"
        docker-compose -f $COMPOSE_FILE ps
    fi
    
    # Очистка неиспользуемых образов (опционально)
    log ""
    log "Очистка неиспользуемых Docker ресурсов..."
    docker image prune -f
    docker system prune -f
    
    log ""
    log "========================================="
    log "СЦЕНАРИЙ ЗАВЕРШЕН"
    log "========================================="
    log ""
    
} | tee -a $LOG_FILE

exit 0
