import json
import os
import re
import time

try:
    import httpx
except ImportError:  # openai>=3 тянет переименованный пакет httpx2 вместо httpx
    import httpx2 as httpx

from openai import APIConnectionError, APITimeoutError, OpenAI
from dotenv import load_dotenv

load_dotenv()

# Модель по умолчанию. combo-маршруты вида auto/* запрещено строить на этой
# стороне: они заставляют LLM-прокси перебирать тысячи моделей, падают по
# памяти и в ответ отдают чужие служебные тексты вместо содержимого.
DEFAULT_MODEL = "kilo-gateway/kilo-auto/free"

# Разумный потолок ожидания одного ответа. Висящее соединение хуже медленного:
# оно держит воркера и не даёт пользователю честную ошибку.
DEFAULT_TIMEOUT_SECONDS = 180.0

# При сетевой ошибке повторяем только один раз: повторы к падающему LLM-прокси
# усиливают аварию вместо того, чтобы её показать.
TRANSPORT_RETRIES = 1


class LLMUnavailableError(Exception):
    """LLM-сервис не ответил ни разу (сетевой сбой или обрыв соединения)."""


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str = None, max_tokens: int = None):
        """
        Инициализация клиента для работы с LLM через Proxy API.

        Args:
            base_url: Базовый URL API
            api_key: API ключ для авторизации
            model: Название модели (по умолчанию из OPENAI_MODEL или DEFAULT_MODEL)
            max_tokens: Максимальное количество токенов в ответе
                (по умолчанию из OPENAI_MAX_TOKENS, если не задано — не ограничиваем)
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens or os.getenv("OPENAI_MAX_TOKENS")
        if self.max_tokens is not None:
            self.max_tokens = int(self.max_tokens)
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        # max_retries=0 отключает собственные повторы SDK: иначе они
        # перемножаются с нашими и добивают уже падающий прокси.
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=self.timeout,
            max_retries=0
        )

    def set_system_prompt(self, system_prompt: str):
        """Установить системный промпт по умолчанию."""
        self.system_prompt = system_prompt

    def set_max_tokens(self, max_tokens: int):
        """Установить максимальное количество токенов."""
        self.max_tokens = max_tokens

    def _request_kwargs(self) -> dict:
        """
        Дополнительные параметры запроса к LLM.

        Возвращает словарь с параметрами, которые передаются в
        chat.completions.create. Сейчас это max_tokens (если задан).

        Returns:
            Словарь с параметрами запроса
        """
        kwargs = {}
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        return kwargs

    @staticmethod
    def _extract_content(response) -> str:
        """
        Извлекает текстовый контент из ответа LLM.

        Args:
            response: Ответ OpenAI API

        Returns:
            Текст ответа модели

        Raises:
            ValueError: Если контент пустой или отсутствует
        """
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError):
            raise ValueError("LLM не вернул контент в ожидаемом формате")

        if not content or not str(content).strip():
            raise ValueError("LLM вернул пустой ответ")

        return str(content).strip()

    @staticmethod
    def _is_transport_error(exc: BaseException) -> bool:
        """Сервис не ответил вообще (в отличие от «ответил, но ответ непригоден»)."""
        return isinstance(exc, (APIConnectionError, APITimeoutError, httpx.TransportError))

    def _probe_service(self) -> str:
        """
        Быстрая проверка доступности LLM-сервиса после обрыва соединения.

        Возвращает пояснение на русском: сервис недоступен вовсе или рвёт
        соединение уже в процессе генерации.

        Returns:
            Текст диагноза без учётных данных
        """
        url = self.base_url.rstrip("/") + "/models"
        try:
            response = httpx.get(
                url,
                timeout=5,
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
        except Exception as exc:
            return (
                f"сервис {self.base_url} не отвечает ({type(exc).__name__}). "
                "Проверьте, что LLM-прокси запущен."
            )
        return (
            f"сервис {self.base_url} отвечает (HTTP {response.status_code}), "
            "но обрывает соединение во время генерации — вероятно, процесс "
            "LLM-прокси перезапускается."
        )

    def _failure(self, exc: BaseException, kind: str) -> Exception:
        """
        Превращает сырую ошибку клиента в понятную пользователю.

        Args:
            exc: исходная ошибка
            kind: тип ожидаемого ответа ("ответ" или "JSON-ответ")

        Returns:
            Готовое к выбросу исключение с указанием настоящей причины
        """
        if not self._is_transport_error(exc):
            return Exception(f"Не удалось получить {kind} от LLM: {exc}")
        return LLMUnavailableError(
            f"LLM-сервис недоступен: {self._probe_service()} "
            f"Исходная ошибка: {exc}"
        )

    def _call(self, kind: str, request, max_retries: int = 2):
        """
        Выполняет запрос к LLM, разделяя сетевые сбои и непригодные ответы модели.

        Args:
            kind: описание ожидаемого ответа для текста ошибки
            request: функция одного запроса, возвращающая готовый результат
            max_retries: повторы при непригодном ответе модели

        Returns:
            Результат запроса — текст или словарь

        Raises:
            LLMUnavailableError: сервис не ответил ни разу
            Exception: сервис ответил, но ответ непригоден
        """
        transport_left = TRANSPORT_RETRIES
        model_left = max_retries
        while True:
            try:
                return request()
            except Exception as exc:
                if self._is_transport_error(exc):
                    if transport_left <= 0:
                        raise self._failure(exc, kind) from exc
                    transport_left -= 1
                elif model_left <= 0:
                    raise self._failure(exc, kind) from exc
                else:
                    model_left -= 1
                time.sleep(2)

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        """
        Простой запрос к LLM.

        Args:
            prompt: Текст запроса пользователя
            max_retries: Количество повторных попыток при пустом ответе

        Returns:
            Текст ответа модели
        """
        def request() -> str:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                **self._request_kwargs()
            )
            return self._extract_content(response)

        return self._call("ответ", request, max_retries)

    def chat_with_system(self, system_prompt: str, user_prompt: str, max_retries: int = 2) -> str:
        """
        Запрос к LLM с системным промптом.

        Args:
            system_prompt: Системный промпт
            user_prompt: Запрос пользователя
            max_retries: Количество повторных попыток при пустом ответе

        Returns:
            Текст ответа модели
        """
        def request() -> str:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                **self._request_kwargs()
            )
            return self._extract_content(response)

        return self._call("ответ", request, max_retries)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        Извлекает JSON-объект из текста ответа LLM.

        Обрабатывает:
        - Чистый JSON
        - Markdown-обёртку ```json ... ```
        - Произвольный текст с JSON-объектом внутри

        Args:
            text: Текст ответа модели

        Returns:
            Распарсенный словарь

        Raises:
            ValueError: Если JSON не найден или невалиден
        """
        text = text.strip()

        # Убираем markdown-обёртку ```json ... ```
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fenced:
            text = fenced.group(1).strip()

        # Пробуем распарсить как есть
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Ищем JSON-объект внутри произвольного текста
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"LLM не вернул валидный JSON. Ответ: {text[:500]}")

    def chat_json(self, system_prompt: str, user_prompt: str, max_retries: int = 2) -> dict:
        """
        Запрос к LLM со структурированным ответом в формате JSON.

        Args:
            system_prompt: Системный промпт
            user_prompt: Запрос пользователя
            max_retries: Количество повторных попыток при ошибке

        Returns:
            Словарь с парсированным JSON-ответом
        """
        def request() -> dict:
            response = self.client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                **self._request_kwargs()
            )
            return self._extract_json(self._extract_content(response))

        return self._call("JSON-ответ", request, max_retries)


if __name__ == "__main__":
    # Инициализация клиента из переменных окружения
    base_url = os.getenv("OPENAI_API_BASE")
    api_key = os.getenv("OPENAI_API_KEY")

    if not base_url or not api_key:
        print("Ошибка: Не заданы переменные окружения OPENAI_API_BASE или OPENAI_API_KEY")
    else:
        client = LLMClient(base_url=base_url, api_key=api_key)

        print("=== Тест 1: Простой запрос ===")
        response1 = client.chat("Напиши приветствие на русском языке")
        print(f"Ответ: {response1}\n")

        print("=== Тест 2: Запрос с системным промптом ===")
        system_prompt = "Ты - полезный ассистент, который отвечает кратко и по делу."
        user_prompt = "Что такое Python?"
        response2 = client.chat_with_system(system_prompt, user_prompt)
        print(f"Ответ: {response2}\n")

        print("=== Тест 3: JSON-запрос ===")
        system_prompt_json = "Ты - помощник, который возвращает данные в формате JSON."
        user_prompt_json = "Верни информацию о программисте с полями: name, age, language"
        response3 = client.chat_json(system_prompt_json, user_prompt_json)
        print(f"Ответ: {response3}")
        print(f"Тип ответа: {type(response3)}")
