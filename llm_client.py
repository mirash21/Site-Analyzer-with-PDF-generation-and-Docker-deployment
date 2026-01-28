from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str = "gpt-4o-mini"):
        """
        Инициализация клиента для работы с LLM через Proxy API.

        Args:
            base_url: Базовый URL API
            api_key: API ключ для авторизации
            model: Название модели (по умолчанию gpt-4o-mini)
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key
        )

    def set_system_prompt(self, system_prompt: str):
        """Установить системный промпт по умолчанию."""
        self.system_prompt = system_prompt

    def set_max_tokens(self, max_tokens: int):
        """Установить максимальное количество токенов."""
        self.max_tokens = max_tokens

    def chat(self, prompt: str) -> str:
        """
        Простой запрос к LLM.

        Args:
            prompt: Текст запроса пользователя

        Returns:
            Текст ответа модели
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content

    def chat_with_system(self, system_prompt: str, user_prompt: str) -> str:
        """
        Запрос к LLM с системным промптом.

        Args:
            system_prompt: Системный промпт
            user_prompt: Запрос пользователя

        Returns:
            Текст ответа модели
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message.content

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Запрос к LLM со структурированным ответом в формате JSON.

        Args:
            system_prompt: Системный промпт
            user_prompt: Запрос пользователя

        Returns:
            Словарь с парсированным JSON-ответом
        """
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        import json
        return json.loads(response.choices[0].message.content)


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
