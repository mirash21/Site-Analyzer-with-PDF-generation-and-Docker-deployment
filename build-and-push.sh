#!/bin/bash

# ==========================================
# СКРИПТ СБОРКИ И ПУБЛИКАЦИИ DOCKER ОБРАЗОВ
# ==========================================
# Скрипт собирает и публикует образы backend и frontend на Docker Hub
# ==========================================
# Запуск: ./build-and-push.sh
# ==========================================

# ============================
# КОНФИГУРАЦИЯ
# ============================
DOCKER_USERNAME="mirash2008"
BACKEND_TAG="${DOCKER_USERNAME}/backend:latest"
FRONTEND_TAG="${DOCKER_USERNAME}/frontend:latest"

# Пути к Dockerfile
BACKEND_DOCKERFILE="Backend-Dockerfile"
FRONTEND_DOCKERFILE="frontend/Dockerfile"

# ============================
# ФУНКЦИИ
# ============================

print_step() {
    echo ""
    echo "========================================="
    echo "  $1"
    echo "========================================="
}

print_error() {
    echo "❌ ОШИБКА: $1"
}

print_success() {
    echo "✅ $1"
}

print_info() {
    echo "ℹ️  $1"
}

# Проверка Docker Hub авторизации
check_docker_login() {
    print_step "ПРОВЕРКА АВТОРИЗАЦИИ DOCKER HUB"
    
    if docker info | grep -q "Username: ${DOCKER_USERNAME}"; then
        print_success "Уже авторизован как ${DOCKER_USERNAME}"
        return 0
    else
        print_info "Требуется авторизация в Docker Hub"
        docker login
        return $?
    fi
}

# Сборка Backend образа
build_backend() {
    print_step "СБОРКА BACKEND ОБРАЗА"
    
    print_info "Dockerfile: ${BACKEND_DOCKERFILE}"
    print_info "Тег: ${BACKEND_TAG}"
    
    if [[ ! -f "${BACKEND_DOCKERFILE}" ]]; then
        print_error "Dockerfile не найден: ${BACKEND_DOCKERFILE}"
        return 1
    fi
    
    # Сборка с кэшем
    docker build --progress=plain \
        -t ${BACKEND_TAG} \
        -f ${BACKEND_DOCKERFILE} \
        .
    
    if [[ $? -eq 0 ]]; then
        print_success "Backend образ собран успешно"
        return 0
    else
        print_error "Не удалось собрать backend образ"
        return 1
    fi
}

# Публикация Backend образа
push_backend() {
    print_step "ПУБЛИКАЦИЯ BACKEND ОБРАЗА НА DOCKER HUB"
    
    print_info "Отправка: ${BACKEND_TAG}"
    
    docker push ${BACKEND_TAG}
    
    if [[ $? -eq 0 ]]; then
        print_success "Backend образ опубликован"
        return 0
    else
        print_error "Не удалось опубликовать backend образ"
        return 1
    fi
}

# Сборка Frontend образа
build_frontend() {
    print_step "СБОРКА FRONTEND ОБРАЗА"
    
    print_info "Директория: frontend/"
    print_info "Dockerfile: ${FRONTEND_DOCKERFILE}"
    print_info "Тег: ${FRONTEND_TAG}"
    
    if [[ ! -f "${FRONTEND_DOCKERFILE}" ]]; then
        print_error "Dockerfile не найден: ${FRONTEND_DOCKERFILE}"
        return 1
    fi
    
    # Сборка с кэшем
    docker build --progress=plain \
        -t ${FRONTEND_TAG} \
        -f ${FRONTEND_DOCKERFILE} \
        frontend/
    
    if [[ $? -eq 0 ]]; then
        print_success "Frontend образ собран успешно"
        return 0
    else
        print_error "Не удалось собрать frontend образ"
        return 1
    fi
}

# Публикация Frontend образа
push_frontend() {
    print_step "ПУБЛИКАЦИЯ FRONTEND ОБРАЗА НА DOCKER HUB"
    
    print_info "Отправка: ${FRONTEND_TAG}"
    
    docker push ${FRONTEND_TAG}
    
    if [[ $? -eq 0 ]]; then
        print_success "Frontend образ опубликован"
        return 0
    else
        print_error "Не удалось опубликовать frontend образ"
        return 1
    fi
}

# Тестирование локально (опционально)
test_images() {
    print_step "ТЕСТИРОВАНИЕ ОБРАЗОВ"
    
    print_info "Размер образов:"
    docker images ${DOCKER_USERNAME}/{backend,frontend}:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    
    read -p "Запустить тестирование контейнеров локально? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Запуск тестовых контейнеров..."
        
        # Запуск теста backend
        docker run --rm -p 8001:8000 ${BACKEND_TAG} &
        BACKEND_PID=$!
        
        # Ожидание запуска
        sleep 5
        
        # Проверка
        if curl -s http://localhost:8001/health > /dev/null 2>&1; then
            print_success "Backend контейнер работает"
        else
            print_info "Backend контейнер не отвечает (может быть нормально)"
        fi
        
        # Остановка
        kill $BACKEND_PID 2>/dev/null
        
        print_info "Тестирование завершено"
    else
        print_info "Тестирование пропущено"
    fi
}

# Очистка старых образов (опционально)
cleanup_old_images() {
    print_step "ОЧИСТКА СТАРЫХ ОБРАЗОВ"
    
    read -p "Удалить старые образы и dangling layers? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Удаление dangling images..."
        docker image prune -f
        
        print_info "Удаление старых образов без тегов..."
        docker image prune -a -f
        
        print_success "Очистка завершена"
    else
        print_info "Очистка пропущена"
    fi
}

# Вывод информации об образах
print_image_info() {
    print_step "ИНФОРМАЦИЯ ОБ ОБРАЗАХ"
    
    docker images ${DOCKER_USERNAME}/{backend,frontend}:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}\t{{.Size}}"
}

# ============================
# ОСНОВНОЙ БЛОК
# ============================

print_step "НАЧАЛО СБОРКИ И ПУБЛИКАЦИИ DOCKER ОБРАЗОВ"

# Проверка авторизации
check_docker_login || exit 1

# Сборка и публикация Backend
build_backend || exit 1
push_backend || exit 1

# Сборка и публикация Frontend
build_frontend || exit 1
push_frontend || exit 1

# Вывод информации
print_image_info

# Тестирование (опционально)
test_images

# Очистка (опционально)
cleanup_old_images

print_step "СБОРКА И ПУБЛИКАЦИЯ ЗАВЕРШЕНЫ"
print_success "Образы готовы к развертыванию на сервере"
print_info "Для развертывания запустите: ./deploy.sh"
