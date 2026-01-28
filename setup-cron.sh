#!/bin/bash

# ==========================================
# SETUP CRON JOB FOR AUTO-UPDATE SCRIPT
# ==========================================
# Скрипт настраивает cron job для автоматического
# запуска update-containers.sh каждый час
# ==========================================
# Запуск: sudo ./setup-cron.sh
# ==========================================

# ============================
# КОНФИГУРАЦИЯ
# ============================
# Путь к скрипту обновления
UPDATE_SCRIPT="/home/ihor/Final_project_curs/update-containers.sh"

# Путь к лог-файлу
LOG_FILE="/var/log/update-containers.log"

# ============================
# ОСНОВНОЙ БЛОК
# ============================

echo "========================================="
echo "НАСТРОЙКА CRON JOB ДЛЯ АВТООБНОВЛЕНИЯ"
echo "========================================="

# Проверяем запуск с правами root
if [[ $EUID -ne 0 ]]; then
   echo "Этот скрипт должен быть запущен с sudo"
   echo "Используйте: sudo $0"
   exit 1
fi

# Проверяем существование скрипта обновления
if [[ ! -f "$UPDATE_SCRIPT" ]]; then
    echo "ОШИБКА: Скрипт $UPDATE_SCRIPT не найден!"
    echo "Убедитесь, что путь к скрипту правильный"
    exit 1
fi

# Делаем скрипт исполняемым
echo ""
echo "Делаем скрипт обновления исполняемым..."
chmod +x $UPDATE_SCRIPT
echo "Готово: $UPDATE_SCRIPT теперь исполняемый"

# Создаем директорию для логов если не существует
echo ""
echo "Создание директории для логов..."
mkdir -p $(dirname $LOG_FILE)
touch $LOG_FILE
chmod 644 $LOG_FILE
echo "Лог-файл: $LOG_FILE"

# Создаем cron job
# Запуск каждый час (в 0 минут каждого часа)
CRON_JOB="0 * * * * $UPDATE_SCRIPT >> $LOG_FILE 2>&1"

echo ""
echo "Настройка cron job..."
echo "Добавляем запись: $CRON_JOB"

# Проверяем существует ли уже такой cron job
if crontab -l 2>/dev/null | grep -q "update-containers.sh"; then
    echo "Предупреждение: Cron job для update-containers.sh уже существует"
    echo "Текущие cron задачи:"
    crontab -l 2>/dev/null | grep "update-containers.sh"
    
    echo ""
    read -p "Заменить существующий cron job? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Удаляем старую запись
        crontab -l 2>/dev/null | grep -v "update-containers.sh" | crontab -
        # Добавляем новую
        (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
        echo "Cron job обновлен"
    else
        echo "Cron job оставлен без изменений"
        exit 0
    fi
else
    # Добавляем новый cron job
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "Cron job добавлен"
fi

# Показываем текущий cron
echo ""
echo "========================================="
echo "ТЕКУЩИЕ CRON ЗАДАЧИ:"
echo "========================================="
crontab -l

echo ""
echo "========================================="
echo "НАСТРОЙКА ЗАВЕРШЕНА"
echo "========================================="
echo "Скрипт будет запускаться каждый час"
echo "Логи будут записываться в: $LOG_FILE"
echo ""
echo "Для просмотра логов:"
echo "  tail -f $LOG_FILE"
echo ""
echo "Для ручного запуска обновления:"
echo "  $UPDATE_SCRIPT"
echo ""
echo "Для редактирования cron:"
echo "  crontab -e"
echo ""
