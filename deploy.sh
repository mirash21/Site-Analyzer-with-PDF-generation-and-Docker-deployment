#!/bin/bash

# ==========================================
# DEPLOYMENT SCRIPT
# ==========================================
# Скрипт для полной настройки сервера:
# 1. Копирование файлов
# 2. Настройка docker-compose
# 3. Создание директорий
# 4. Запуск контейнеров
# 5. Настройка автообновления
# ==========================================
# Запуск на локальной машине: ./deploy.sh
# ==========================================

# ============================
# КОНФИГУРАЦИЯ
# ============================
SERVER_USER="ihor"
SERVER_IP="185.117.155.237"
SERVER_PATH="/home/${SERVER_USER}/Final_project_curs"
LOCAL_PROJECT_PATH=$(pwd)

# Файлы для копирования на сервер
FILES_TO_UPLOAD=(
    "docker-compose.production.yml"
    "update-containers.sh"
    "setup-cron.sh"
)

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

# Проверка SSH соединения
check_ssh() {
    print_step "ПРОВЕРКА SSH СОЕДИНЕНИЯ"
    
    ssh -o ConnectTimeout=5 ${SERVER_USER}@${SERVER_IP} "echo 'SSH соединение успешно установлено'" > /dev/null 2>&1
    
    if [[ $? -eq 0 ]]; then
        print_success "SSH соединение с сервером ${SERVER_IP} установлено"
        return 0
    else
        print_error "Не удалось установить SSH соединение с ${SERVER_IP}"
        return 1
    fi
}

# Создание директорий на сервере
create_directories() {
    print_step "СОЗДАНИЕ ДИРЕКТОРИЙ НА СЕРВЕРЕ"
    
    ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${SERVER_PATH}/{data,logs,logs/backend,logs/frontend}"
    
    if [[ $? -eq 0 ]]; then
        print_success "Директории созданы: ${SERVER_PATH}/data, ${SERVER_PATH}/logs"
        return 0
    else
        print_error "Не удалось создать директории"
        return 1
    fi
}

# Загрузка файлов на сервер
upload_files() {
    print_step "ЗАГРУЗКА ФАЙЛОВ НА СЕРВЕР"
    
    for file in "${FILES_TO_UPLOAD[@]}"; do
        if [[ -f "${LOCAL_PROJECT_PATH}/${file}" ]]; then
            print_info "Загрузка: ${file}"
            scp "${LOCAL_PROJECT_PATH}/${file}" ${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/
            
            if [[ $? -eq 0 ]]; then
                print_success "Файл ${file} загружен"
            else
                print_error "Не удалось загрузить ${file}"
                return 1
            fi
        else
            print_error "Файл не найден: ${file}"
        fi
    done
    
    return 0
}

# Создание .env файла на сервере
create_env_file() {
    print_step "СОЗДАНИЕ .env ФАЙЛА"
    
    cat > /tmp/server.env <<EOF
# Backend конфигурация
DATABASE_URL=sqlite:///./data/app.db
SECRET_KEY=prod-secret-key-change-this-$(date +%s)
ENVIRONMENT=production

# API конфигурация (измените на реальные значения)
# OPENAI_API_KEY=your-openai-key-here

# CORS конфигурация
CORS_ORIGINS=http://185.117.155.237
EOF
    
    scp /tmp/server.env ${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/.env
    
    if [[ $? -eq 0 ]]; then
        print_success ".env файл создан"
        print_info "Внимание: Измените SECRET_KEY и добавьте OPENAI_API_KEY при необходимости"
        return 0
    else
        print_error "Не удалось создать .env файл"
        return 1
    fi
}

# Загрузка Dockerfile для frontend (если нужно)
upload_frontend_nginx() {
    print_step "ЗАГРУЗКА NGINX КОНФИГУРАЦИИ"
    
    if [[ -f "${LOCAL_PROJECT_PATH}/frontend/nginx.conf" ]]; then
        scp "${LOCAL_PROJECT_PATH}/frontend/nginx.conf" ${SERVER_USER}@${SERVER_IP}:${SERVER_PATH}/
        
        if [[ $? -eq 0 ]]; then
            print_success "nginx.conf загружен"
            return 0
        else
            print_error "Не удалось загрузить nginx.conf"
            return 1
        fi
    else
        print_info "frontend/nginx.conf не найден, пропускаем"
        return 0
    fi
}

# Запуск контейнеров
start_containers() {
    print_step "ЗАПУСК КОНТЕЙНЕРОВ"
    
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml pull"
    
    if [[ $? -eq 0 ]]; then
        print_success "Образы загружены"
    else
        print_error "Не удалось загрузить образы"
        return 1
    fi
    
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml up -d"
    
    if [[ $? -eq 0 ]]; then
        print_success "Контейнеры запущены"
        return 0
    else
        print_error "Не удалось запустить контейнеры"
        return 1
    fi
}

# Проверка статуса
check_status() {
    print_step "ПРОВЕРКА СТАТУСА КОНТЕЙНЕРОВ"
    
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml ps"
    
    return $?
}

# Настройка прав доступа
setup_permissions() {
    print_step "НАСТРОЙКА ПРАВ ДОСТУПА"
    
    ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && chmod +x update-containers.sh setup-cron.sh"
    
    if [[ $? -eq 0 ]]; then
        print_success "Права доступа настроены"
        return 0
    else
        print_error "Не удалось настроить права доступа"
        return 1
    fi
}

# Настройка cron (опционально)
setup_cron() {
    print_step "НАСТРОЙКА CRON ДЛЯ АВТООБНОВЛЕНИЯ"
    
    read -p "Настроить cron job для автоматического обновления? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ssh ${SERVER_USER}@${SERVER_IP} "cd ${SERVER_PATH} && sudo bash setup-cron.sh"
        
        if [[ $? -eq 0 ]]; then
            print_success "Cron job настроен"
        else
            print_error "Не удалось настроить cron job"
            return 1
        fi
    else
        print_info "Настройка cron пропущена"
    fi
    
    return 0
}

# Открытие портов (опционально)
setup_firewall() {
    print_step "НАСТРОЙКА FIREWALL"
    
    read -p "Открыть порты 80 и 443 в firewall? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ssh ${SERVER_USER}@${SERVER_IP} "sudo ufw allow 80 && sudo ufw allow 443"
        
        if [[ $? -eq 0 ]]; then
            print_success "Порты 80 и 443 открыты"
        else
            print_error "Не удалось открыть порты"
            return 1
        fi
    else
        print_info "Настройка firewall пропущена"
    fi
    
    return 0
}

# Вывод итоговой информации
print_summary() {
    print_step "РАЗВЕРТЫВАНИЕ ЗАВЕРШЕНО"
    
    echo ""
    echo "🌐 Приложение доступно по адресу:"
    echo "   Frontend: http://${SERVER_IP}"
    echo "   Backend:  http://${SERVER_IP}/api/"
    echo ""
    echo "📋 Полезные команды:"
    echo "   Статус:     ssh ${SERVER_USER}@${SERVER_IP} 'cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml ps'"
    echo "   Логи:       ssh ${SERVER_USER}@${SERVER_IP} 'cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml logs -f'"
    echo "   Обновление: ssh ${SERVER_USER}@${SERVER_IP} 'cd ${SERVER_PATH} && ./update-containers.sh'"
    echo "   Остановка:   ssh ${SERVER_USER}@${SERVER_IP} 'cd ${SERVER_PATH} && docker-compose -f docker-compose.production.yml down'"
    echo ""
    echo "📝 Следующие шаги:"
    echo "   1. Убедитесь, что образы опубликованы на Docker Hub"
    echo "   2. Проверьте .env файл на сервере и настройте SECRET_KEY"
    echo "   3. Тестовые команды:"
    echo "      - Проверьте статус контейнеров"
    echo "      - Откройте http://${SERVER_IP} в браузере"
    echo ""
    print_success "Развертывание завершено успешно!"
}

# ============================
# ОСНОВНОЙ БЛОК
# ============================

print_step "НАЧАЛО РАЗВЕРТЫВАНИЯ НА СЕРВЕР ${SERVER_IP}"

# Проверка необходимых файлов
for file in "${FILES_TO_UPLOAD[@]}"; do
    if [[ ! -f "${LOCAL_PROJECT_PATH}/${file}" ]]; then
        print_error "Файл не найден: ${file}"
        print_info "Убедитесь, что находитесь в корне проекта"
        exit 1
    fi
done

# Последовательное выполнение шагов
check_ssh || exit 1
create_directories || exit 1
upload_files || exit 1
create_env_file || exit 1
upload_frontend_nginx || exit 1
setup_permissions || exit 1
start_containers || exit 1
check_status || exit 1
setup_cron || exit 1
setup_firewall || exit 1

print_summary

exit 0
