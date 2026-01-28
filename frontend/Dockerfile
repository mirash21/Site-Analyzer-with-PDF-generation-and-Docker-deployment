# ==========================================
# PRODUCTION DOCKERFILE FOR FRONTEND
# ==========================================
# Multi-stage build для оптимизации размера образа
# ==========================================

# Stage 1: Build
# ==========================================
# Используем Node.js для сборки React приложения
# ==========================================
FROM node:20-alpine as builder

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем package files
COPY package*.json ./

# Устанавливаем зависимости с --legacy-peer-deps для совместимости
RUN npm ci --legacy-peer-deps

# Копируем исходный код
COPY . .

# Собираем production версию
RUN npm run build

# Stage 2: Production
# ==========================================
# Используем nginx для обслуживания статических файлов
# ==========================================
FROM nginx:alpine

# Копируем nginx конфигурацию
COPY nginx.conf /etc/nginx/nginx.conf

# Копируем собранные файлы из builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Открываем порт 80
EXPOSE 80

# Запускаем nginx
CMD ["nginx", "-g", "daemon off;"]
