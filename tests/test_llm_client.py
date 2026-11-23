"""
Тесты разбора ошибок LLM-клиента.

Проверяют контракт, появившийся после аварии: обрыв соединения с LLM-прокси
не должен выглядеть как «модель ответила плохо» и не должен выливать пачку
повторных запросов на уже падающий сервис.
"""

from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from app.services import llm_client as lc
from app.services.llm_client import LLMClient, LLMUnavailableError

BASE_URL = "http://omniroute:20128/v1"
CHAT_URL = BASE_URL + "/chat/completions"


def make_response(content, finish_reason=None):
    """Минимальная заглушка ответа chat.completions."""
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content),
            finish_reason=finish_reason,
        )]
    )


def truncated(content=""):
    """Ответ, обрезанный лимитом токенов."""
    return make_response(content, finish_reason="length")


class FakeCompletions:
    """Заменяет client.chat.completions и считает обращения к LLM."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def client(monkeypatch):
    """Клиент без реальных запросов и без пауз между попытками."""
    monkeypatch.setattr(lc.time, "sleep", lambda _seconds: None)
    return LLMClient(base_url=BASE_URL, api_key="test-key", model="test-model")


def attach(client, results):
    """Подвешивает фейковые completions и возвращает счётчик вызовов."""
    completions = FakeCompletions(results)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return completions


def connection_error():
    return APIConnectionError(request=httpx.Request("POST", CHAT_URL))


def test_chat_json_returns_parsed_dict_on_good_answer(client):
    completions = attach(client, [make_response('{"steps": ["a", "b"]}')])

    assert client.chat_json("sys", "user") == {"steps": ["a", "b"]}
    assert len(completions.calls) == 1


def test_transport_error_becomes_llm_unavailable(client, monkeypatch):
    monkeypatch.setattr(
        lc.httpx, "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200)
    )
    attach(client, [connection_error()])

    with pytest.raises(LLMUnavailableError) as excinfo:
        client.chat_json("sys", "user")

    message = str(excinfo.value)
    assert BASE_URL in message
    assert "отвечает (HTTP 200)" in message
    assert "перезапускается" in message


def test_transport_error_stops_after_single_retry(client, monkeypatch):
    """Повторы к падающему прокси усиливают аварию — их должен быть ровно один."""
    monkeypatch.setattr(
        lc.httpx, "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200)
    )
    completions = attach(client, [connection_error()])

    with pytest.raises(LLMUnavailableError):
        client.chat("prompt", max_retries=5)

    # Абсолютный потолок: initial + одна повторная попытка, независимо от max_retries
    assert len(completions.calls) == 2


def test_transport_error_with_dead_service_names_the_outage(client, monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(lc.httpx, "get", refuse)
    attach(client, [connection_error()])

    with pytest.raises(LLMUnavailableError) as excinfo:
        client.chat_with_system("sys", "user")

    assert "не отвечает" in str(excinfo.value)


def test_unparsable_answer_keeps_legacy_prefix_and_retries(client):
    completions = attach(client, [make_response("я не умею в json")])

    with pytest.raises(Exception) as excinfo:
        client.chat_json("sys", "user", max_retries=2)

    assert not isinstance(excinfo.value, LLMUnavailableError)
    assert str(excinfo.value).startswith("Не удалось получить JSON-ответ от LLM:")
    assert len(completions.calls) == 3


def test_empty_answer_keeps_legacy_prefix(client):
    attach(client, [make_response("   ")])

    with pytest.raises(Exception) as excinfo:
        client.chat("prompt", max_retries=0)

    assert str(excinfo.value) == (
        "Не удалось получить ответ от LLM: LLM вернул пустой ответ"
    )


def test_http_status_error_is_reported_as_answer_problem(client):
    request = httpx.Request("POST", CHAT_URL)
    response = httpx.Response(402, request=request)
    error = APIStatusError("Add credits to continue", response=response, body=None)
    completions = attach(client, [error])

    with pytest.raises(Exception) as excinfo:
        client.chat_json("sys", "user", max_retries=1)

    assert not isinstance(excinfo.value, LLMUnavailableError)
    assert "Add credits to continue" in str(excinfo.value)
    assert len(completions.calls) == 2


def test_sdk_internal_retries_are_disabled(monkeypatch):
    """SDK сам делает повторы по умолчанию — они перемножаются с нашими."""
    monkeypatch.setattr(lc.time, "sleep", lambda _seconds: None)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    client = LLMClient(base_url=BASE_URL, api_key="test-key", model="test-model")

    assert client.client.max_retries == 0
    assert client.client.timeout == lc.DEFAULT_TIMEOUT_SECONDS


def test_request_timeout_comes_from_environment(monkeypatch):
    """Долгий ответ reasoning-модели не должен обрываться на дефолте."""
    monkeypatch.setattr(lc.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    client = LLMClient(base_url=BASE_URL, api_key="test-key", model="test-model")

    assert client.timeout == 45.0
    assert client.client.timeout == 45.0


def test_default_model_is_not_a_combo_route(monkeypatch):
    """auto/* роняет LLM-прокси по памяти и отдаёт чужие служебные тексты."""
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(lc.time, "sleep", lambda _seconds: None)

    client = LLMClient(base_url=BASE_URL, api_key="test-key")

    assert client.model == lc.DEFAULT_MODEL
    assert not client.model.startswith("auto/")


def test_empty_json_answer_is_still_an_empty_answer(client):
    """Пустой ответ без признака обрезки — прежнее сообщение про пустоту."""
    client.max_tokens = 2000
    completions = attach(client, [make_response("")])

    with pytest.raises(Exception) as excinfo:
        client.chat_json("sys", "user", max_retries=0)

    assert len(completions.calls) == 1
    assert str(excinfo.value) == (
        "Не удалось получить JSON-ответ от LLM: LLM вернул пустой ответ"
    )


def test_truncated_json_is_repeated_with_bigger_budget(client):
    """Reasoning-модели тратят бюджет на черновик — повтор обязан быть крупнее."""
    client.max_tokens = 2000
    client.max_tokens_ceiling = 8000
    completions = attach(client, [
        truncated('{ "steps": ["первые два'),
        make_response('{"steps": ["a", "b"]}'),
    ])

    assert client.chat_json("sys", "user") == {"steps": ["a", "b"]}
    assert [c["max_tokens"] for c in completions.calls] == [2000, 4000]


def test_truncation_escalation_stops_at_ceiling_and_says_so(client):
    client.max_tokens = 2000
    client.max_tokens_ceiling = 4000
    completions = attach(client, [truncated("обрывается на середине")])

    with pytest.raises(Exception) as excinfo:
        client.chat_json("sys", "user", max_retries=5)

    assert not isinstance(excinfo.value, LLMUnavailableError)
    assert [c["max_tokens"] for c in completions.calls] == [2000, 4000]
    message = str(excinfo.value)
    assert message.startswith("Не удалось получить JSON-ответ от LLM:")
    assert "лимите 4000 токенов" in message


def test_complete_json_with_length_stop_reason_is_accepted(client):
    """Если JSON успел закрыться — обрыв по токенам не повод переделывать."""
    client.max_tokens = 2000
    completions = attach(client, [make_response('{"steps": ["a"]}', finish_reason="length")])

    assert client.chat_json("sys", "user") == {"steps": ["a"]}
    assert len(completions.calls) == 1


def test_truncated_plain_text_also_gets_a_bigger_budget(client):
    client.max_tokens = 2000
    client.max_tokens_ceiling = 8000
    completions = attach(client, [truncated("неполный абзац"), make_response("полный абзац")])

    assert client.chat("prompt") == "полный абзац"
    assert [c["max_tokens"] for c in completions.calls] == [2000, 4000]


def test_without_token_limit_there_is_nothing_to_escalate(client):
    client.max_tokens = None
    client.max_tokens_ceiling = 8000
    completions = attach(client, [truncated("обрезано провайдером")])

    with pytest.raises(Exception) as excinfo:
        client.chat_with_system("sys", "user")

    assert "max_tokens" not in completions.calls[0]
    assert len(completions.calls) == 1
    assert "LLM оборвал ответ" in str(excinfo.value)


def test_non_growing_budget_does_not_loop_forever(client, monkeypatch):
    """Если настройки не дают бюджет расти — повторять бессмысленно."""
    monkeypatch.setattr(lc, "TRUNCATION_TOKEN_MULTIPLIER", 1)
    client.max_tokens = 2000
    client.max_tokens_ceiling = 8000
    completions = attach(client, [truncated("обрыв")])

    with pytest.raises(Exception):
        client.chat("prompt", max_retries=3)

    assert len(completions.calls) == 1
