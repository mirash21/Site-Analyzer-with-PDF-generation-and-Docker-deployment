import ipaddress
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from app.services.llm_client import LLMClient


class SSRFError(Exception):
    """Исключение при попытке SSRF-атаки (доступ к внутренним адресам)."""


# Максимальная длина текста сайта, отправляемого в LLM (в символах).
# Ограничивает стоимость и время анализа больших страниц.
MAX_SITE_TEXT_LENGTH = 12000


class SiteAnalyzer:
    def __init__(self, llm_client: LLMClient):
        """
        Инициализация анализатора сайтов.

        Args:
            llm_client: Клиент для работы с LLM
        """
        self.llm_client = llm_client

    @staticmethod
    def _validate_url(url: str) -> str:
        """
        Валидация URL и защита от SSRF.

        Проверяет, что URL использует http/https, и что резолвится в публичный IP
        (не private/loopback/link-local/reserved).

        Args:
            url: URL для проверки

        Returns:
            Нормализованный URL

        Raises:
            SSRFError: Если URL небезопасен
        """
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            raise SSRFError("Допускаются только http/https URL")

        if not parsed.hostname:
            raise SSRFError("Некорректный URL: отсутствует хост")

        # Блокируем URL с учётными данными (user:pass@host)
        if parsed.username or parsed.password:
            raise SSRFError("URL не должен содержать учётные данные")

        # Резолвим hostname в IP-адреса
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror:
            raise SSRFError(f"Не удалось разрешить хост: {parsed.hostname}")

        for info in infos:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise SSRFError(f"Доступ к внутреннему адресу запрещён: {ip_str}")

        return url

    def fetch_site_html(self, url: str) -> str:
        """
        Скачивает HTML-код сайта по URL.

        Args:
            url: URL сайта для анализа

        Returns:
            HTML-код страницы

        Raises:
            Exception: Если не удалось скачать страницу
        """
        try:
            # SSRF-защита: валидация URL перед запросом
            url = self._validate_url(url)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(
                url,
                headers=headers,
                timeout=10,
                allow_redirects=True,
                # Не разрешаем редиректы на внутренние адреса
                hooks={'response': self._check_redirect_target}
            )
            response.raise_for_status()
            return response.text
        except SSRFError as e:
            raise Exception(str(e))
        except Exception as e:
            raise Exception(f"Не удалось скачать страницу: {str(e)}")

    @staticmethod
    def _check_redirect_target(response, *args, **kwargs):
        """
        Проверка каждого редиректа на SSRF-безопасность.

        Вызывается requests для каждого ответа (включая промежуточные редиректы).
        """
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if location:
                SiteAnalyzer._validate_url(location)
        return response

    def clean_html(self, html: str) -> str:
        """
        Очищает HTML от тегов, оставляя только текст.

        Args:
            html: HTML-код страницы

        Returns:
            Очищенный текст страницы

        Raises:
            Exception: Если не удалось распарсить HTML
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Удаляем script и style элементы
            for script in soup(["script", "style", "noscript"]):
                script.decompose()
            
            # Получаем текст
            text = soup.get_text(separator=' ', strip=True)
            
            # Убираем лишние пробелы и переносы строк
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text
        except Exception as e:
            raise Exception(f"Не удалось распарсить HTML: {str(e)}")

    def generate_analysis_steps(self, site_text: str) -> List[str]:
        """
        Генерирует список шагов для анализа сайта с помощью LLM.

        Args:
            site_text: Очищенный текст сайта

        Returns:
            Список шагов (промптов) для анализа
        """
        system_prompt = (
            "Ты бот-анализатор сайтов. "
            f"Вот текст сайта: {site_text}. "
            "В ответе в формате JSON выдай список из 5-6 шагов (промптов), "
            "которые нужно выполнить для анализа этого сайта и выявления идей для таргетированной рекламы. "
            "Формат ответа: {\"steps\": [\"шаг1\", \"шаг2\", ...]}"
        )
        
        response = self.llm_client.chat_json(system_prompt, site_text)
        
        if "steps" not in response:
            raise Exception("LLM не вернула список шагов в ожидаемом формате")
        
        return response["steps"]

    def execute_analysis_steps(self, steps: List[str], site_text: str) -> List[Dict[str, str]]:
        """
        Выполняет каждый шаг анализа и сохраняет результаты.

        Args:
            steps: Список шагов для анализа
            site_text: Очищенный текст сайта

        Returns:
            Список результатов выполнения каждого шага
        """
        results = []
        
        for i, step in enumerate(steps):
            result = self.llm_client.chat_with_system(step, site_text)
            results.append({
                "step": step,
                "result": result,
                "step_number": i + 1
            })
        
        return results

    def generate_final_analysis(
        self,
        intermediate_results: List[Dict[str, str]],
        site_text: str
    ) -> Dict:
        """
        Генерирует финальный анализ сайта на основе промежуточных результатов.

        Args:
            intermediate_results: Список промежуточных результатов
            site_text: Очищенный текст сайта

        Returns:
            Итоговый анализ с рекламными постами
        """
        # Формируем строку с промежуточными результатами
        results_str = "\n\n".join([
            f"Шаг {r['step_number']}: {r['step']}\nРезультат: {r['result']}"
            for r in intermediate_results
        ])
        
        system_prompt = (
            "У тебя есть результаты промежуточного анализа: "
            f"{results_str}. "
            "Объедини их и выдай итоговый анализ сайта. "
            "Ответ должен содержать: краткий анализ, инструкцию по созданию рекламных постов и три примера постов. "
            "Обязательно включи в анализ оригинальный текст сайта. "
            "Формат ответа в JSON: {"
            "\"brief_analysis\": \"краткий анализ\", "
            "\"ad_instructions\": \"инструкция по созданию постов\", "
            "\"ad_examples\": [\"пример 1\", \"пример 2\", \"пример 3\"]"
            "}"
        )
        
        user_prompt = f"Оригинальный текст сайта:\n{site_text}"
        
        response = self.llm_client.chat_json(system_prompt, user_prompt)
        
        return response

    def analyze_site(self, url: str) -> Dict:
        """
        Полный цикл анализа сайта.

        Args:
            url: URL сайта для анализа

        Returns:
            Словарь с результатами анализа, включающий:
            - url: исходный URL
            - steps: список шагов анализа
            - intermediate_results: промежуточные результаты
            - final_analysis: итоговый анализ с постами

        Raises:
            Exception: При ошибке на любом этапе анализа
        """
        # Шаг 1: Скачиваем HTML
        html = self.fetch_site_html(url)
        
        # Шаг 2: Очищаем HTML от тегов
        site_text = self.clean_html(html)
        
        if not site_text or len(site_text) < 100:
            raise Exception("Не удалось получить достаточное количество текста с сайта")
        
        # Ограничиваем длину текста, чтобы не перегружать LLM
        if len(site_text) > MAX_SITE_TEXT_LENGTH:
            site_text = site_text[:MAX_SITE_TEXT_LENGTH]
        
        # Шаг 3: Генерируем список шагов для анализа
        steps = self.generate_analysis_steps(site_text)
        
        # Шаг 4: Выполняем каждый шаг анализа
        intermediate_results = self.execute_analysis_steps(steps, site_text)
        
        # Шаг 5: Генерируем финальный анализ
        final_analysis = self.generate_final_analysis(intermediate_results, site_text)
        
        # Формируем итоговый результат
        return {
            "url": url,
            "steps": steps,
            "intermediate_results": intermediate_results,
            "final_analysis": final_analysis
        }
