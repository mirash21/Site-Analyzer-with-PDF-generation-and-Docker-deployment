"""Общие условия для тестов.

Живого интернета в наборе нет. Проверка инфраструктуры (robots, sitemap,
ссылки) делает настоящие запросы к сайту клиента: без подмены набор зависел бы
от доступности чужого сайта и тянул секунды на каждом прогоне. Запрос считается
неудачным — ровно так же, как на недоступном сервере, и этот путь тесты покрывают.
"""

import pytest

from app.services import analyzer as analyzer_module


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    """Сеть недоступна: зонд отвечает «ответ не получен», а не ждёт таймаут."""

    def blocked(*args, **kwargs):
        raise ConnectionError("сеть в тестах недоступна — запросы подставляют в fetch")

    monkeypatch.setattr(analyzer_module.requests, "request", blocked)
    monkeypatch.setattr(analyzer_module.requests, "get", blocked)
