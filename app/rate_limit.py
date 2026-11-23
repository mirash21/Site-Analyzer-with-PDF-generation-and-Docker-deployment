from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_client_ip(request) -> str:
    """
    Определение реального IP клиента за reverse proxy (nginx).

    Приложение работает за nginx, который проксирует запросы и добавляет
    заголовок X-Forwarded-For. Без учёта этого заголовка все запросы
    приходили бы с одного IP контейнера nginx, и rate-limit был бы глобальным.

    Args:
        request: Объект запроса FastAPI/Starlette

    Returns:
        Строка с IP-адресом клиента
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Берём первый IP из цепочки (реальный клиент)
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Единый экземпляр лимитера для всего приложения.
# Используется в main.py (app.state.limiter) и в роутерах (@limiter.limit(...)).
limiter = Limiter(key_func=_get_client_ip)
