// Конфигурация API в зависимости от окружения
const getApiBaseUrl = () => {
  // В продакшн используем относительный путь (проксируется nginx)
  // В разработке - localhost:8000
  return import.meta.env.VITE_API_URL || 'http://localhost:8000'
}

export const API_BASE_URL = getApiBaseUrl()
