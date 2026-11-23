import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Tuple
from app.services.llm_client import LLMClient


class SSRFError(Exception):
    """Исключение при попытке SSRF-атаки (доступ к внутренним адресам)."""


# Максимальная длина текста сайта, отправляемого в LLM (в символах).
# Ограничивает стоимость и время анализа больших страниц.
MAX_SITE_TEXT_LENGTH = 12000

# Теги, в которых маркетингового содержания нет.
NOISE_TAGS = (
    "script", "style", "noscript", "template", "svg", "iframe",
    "button", "input", "select", "textarea", "option",
)

# Обвязка: меню, подвал, aside. Её текст идёт отдельной короткой строкой, а не
# смешивается с содержанием страницы, иначе модель принимает меню за сайт.
CHROME_TAGS = ("nav", "footer", "aside", "form")

# Блоки, которые несут содержание.
CONTENT_TAGS = (
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li",
    "blockquote", "dt", "dd", "figcaption", "td", "th",
)

# Запас для вёрстки без p/li: на сайтах, где весь текст лежит в div, иначе
# разбор выходит пустым.
FALLBACK_BLOCK_TAGS = ("div", "td", "th", "span", "dd", "dt", "li", "p")
MIN_CONTENT_LENGTH = 400
MIN_FALLBACK_LINE_LENGTH = 40

# Кроме главной разбираем ещё несколько внутренних страниц: у каталогов
# офферы лежат там, а на главной — только меню.
MAX_EXTRA_PAGES = 2
EXTRA_PAGES_SHARE = 0.35
MENU_SHARE = 0.08
SITE_FETCH_TIMEOUT = 15
MIN_EXTRA_PAGE_CHARS = 200

# Модель ссылается на страницы только номерами: адрес она обязана взять из
# реестра, а не сочинять. Не распознанный номер факт не теряет, но помечается.
SOURCE_REFERENCE_UNRESOLVED = "источник не распознан"

# Ссылки, которые обычно ведут к офферу, а не к обвязке сайта. Ищем и по
# адресу, и по тексту ссылки: пути часто транслитерируют (katalog-produktsii),
# а якорь при этом остаётся русским.
PAGE_LINK_KEYWORDS = (
    "catalog", "katalog", "category", "product", "produkt", "goods",
    "price", "pric", "about", "company", "servic", "brand", "item",
    "каталог", "продукц", "товар", "цен", "услуг", "о-комп", "окомп", "бренд",
)


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
                timeout=SITE_FETCH_TIMEOUT,
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

    @staticmethod
    def _meta(soup: BeautifulSoup, name: str) -> str:
        """Метаописание страницы (description или og:description)."""
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if not tag:
            return ""
        return re.sub(r"\s+", " ", tag.get("content") or "").strip()

    @staticmethod
    def pick_lead(soup: BeautifulSoup):
        """Контейнер, в котором реально больше всего текста.

        Полагаться на первый найденный <main> или <article> нельзя: на живых
        сайтах эти метки часто пустые декорации, и разбор выдавал пару строк
        вместо всей страницы.
        """
        candidates = [soup.find("main"), soup.find("article"), soup.body, soup]
        best, best_score = soup, -1
        for node in candidates:
            if node is None:
                continue
            score = sum(
                len(block.get_text(" ", strip=True))
                for block in node.find_all(list(CONTENT_TAGS))
            )
            if score > best_score:
                best, best_score = node, score
        return best

    def extract_page_text(self, html: str) -> Tuple[str, str]:
        """Разбирает страницу на блоки, сохраняя структуру.

        Возвращает (содержание, список пунктов обвязки). Прежняя версия склеивала
        всё в одну строку через пробел: модель теряла границы абзацев и
        списков, а меню каталога выглядело как основной текст.

        Args:
            html: HTML-код страницы

        Returns:
            Кортеж (текст содержания, короткая строка с меню)

        Raises:
            Exception: Если страницу не удалось распарсить
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            raise Exception(f"Не удалось распарсить HTML: {exc}") from exc

        title = re.sub(r"\s+", " ", soup.title.get_text(strip=True)).strip() if soup.title else ""
        description = self._meta(soup, "description") or self._meta(soup, "og:description")

        # Обвязку вырезаем до сбора содержания, но её пункты возвращаем
        # отдельной строкой: модель должна видеть навигацию, а не читать её
        # вместо товаров.
        menu_items: List[str] = []
        for node in soup.find_all(CHROME_TAGS):
            for text in node.stripped_strings:
                text = text.strip()
                if text and text not in menu_items:
                    menu_items.append(text)
            node.decompose()

        for node in soup.find_all(list(NOISE_TAGS)):
            node.decompose()

        lead = self.pick_lead(soup)

        lines: List[str] = []
        seen = set()
        for node in lead.find_all(list(CONTENT_TAGS)):
            # Родительские блоки пропускаем: их текст придёт дочерними строками.
            if node.find(list(CONTENT_TAGS)):
                continue

            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if len(text) < 2:
                continue

            name = node.name
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                entry = f"{'#' * min(int(name[1]), 4)} {text}"
            elif name == "li":
                entry = f"- {text}"
            else:
                entry = text

            if entry in seen:
                continue
            seen.add(entry)
            lines.append(entry)

        if sum(len(line) for line in lines) < MIN_CONTENT_LENGTH:
            # Вёрстка без единого p или li: берём текстовые листья div/td,
            # иначе страница с одним контентом останется без содержания.
            for node in lead.find_all(list(FALLBACK_BLOCK_TAGS)):
                if node.find(list(FALLBACK_BLOCK_TAGS)):
                    continue
                text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
                if len(text) < MIN_FALLBACK_LINE_LENGTH or text in seen:
                    continue
                seen.add(text)
                lines.append(text)

        header = []
        if title:
            header.append(f"# {title}")
        if description:
            header.append(f"Описание из мета-тегов: {description}")

        content = "\n".join(header + lines).strip()
        menu = ("Меню и обвязка сайта (не содержание): " + " · ".join(menu_items[:60])).strip()
        return content, menu

    @staticmethod
    def _fit(text: str, limit: int) -> str:
        """Обрезает текст по границе строки (или слова), а не посреди слова.

        Для текста, который уходит в LLM блоками, лучше потерять неполную
        последнюю строку, чем передать обрезанное пополам утверждение.
        """
        text = (text or "").strip()
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text

        window = text[:limit]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut > 0:
            window = window[:cut]
        return window.rstrip() + "\n…(остальное не поместилось в лимит)"

    def candidate_links(self, base_url: str, html: str) -> List[str]:
        """Внутренние ссылки этого же хоста, где обычно живёт оффер."""
        soup = BeautifulSoup(html, "html.parser")
        base_netloc = urlparse(base_url).netloc.lower()

        links: List[str] = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = urldefrag(anchor["href"].strip())[0]
            if not href or href.lower().startswith(("mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != base_netloc:
                continue

            path = (parsed.path or "").rstrip("/")
            if not path or path.lower() in seen:
                continue

            # Якорь говорит не меньше пути: «Каталог продукции» ведёт на
            # /katalog-produktsii, и по пути это не угадать.
            anchor_text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
            haystack = f"{path} {parsed.query} {anchor_text}".lower()
            if not any(word in haystack for word in PAGE_LINK_KEYWORDS):
                continue

            seen.add(path.lower())
            links.append(absolute)

        return links[:MAX_EXTRA_PAGES]

    @staticmethod
    def _page_title(html: str) -> str:
        """Заголовок страницы — он идёт в список источников отчёта."""
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return ""
        if soup.title:
            return re.sub(r"\s+", " ", soup.title.get_text(strip=True)).strip()
        heading = soup.find("h1")
        return re.sub(r"\s+", " ", heading.get_text(strip=True)).strip() if heading else ""

    def collect_site_evidence(self, url: str) -> Tuple[str, List[Dict]]:
        """Текст сайта плюс реестр прочитанных страниц.

        Реестр нужен, чтобы отчёт можно было проверить: модель ссылается на номер
        источника, а адрес подставляется здесь из реально скачанных страниц.
        Ссылка, сочинённая моделью, в отчёт не попадает.
        """
        html = self.fetch_site_html(url)
        content, menu = self.extract_page_text(html)
        if not content:
            raise Exception("На странице нет читаемого текста — возможно, сайт собран скриптами")

        start = urlparse(url)
        sources: List[Dict] = [{
            "id": 1,
            "url": url,
            "path": start.path or "/",
            "title": self._page_title(html),
            "chars": len(content),
        }]

        menu_room = int(MAX_SITE_TEXT_LENGTH * MENU_SHARE)
        extra_room = int(MAX_SITE_TEXT_LENGTH * EXTRA_PAGES_SHARE)
        per_extra_room = extra_room // max(MAX_EXTRA_PAGES, 1)

        extras: List[str] = []
        for link in self.candidate_links(url, html):
            try:
                extra_html = self.fetch_site_html(link)
            except Exception:
                # Внутренняя страница не важнее всего анализа: пропускаем её.
                continue
            extra_content, _ = self.extract_page_text(extra_html)
            if len(extra_content) < MIN_EXTRA_PAGE_CHARS:
                continue

            source_id = len(sources) + 1
            path = urlparse(link).path.rstrip("/") or "/"
            sources.append({
                "id": source_id,
                "url": link,
                "path": path,
                "title": self._page_title(extra_html),
                "chars": len(extra_content),
            })
            extras.append(
                f"## Источник {source_id}: {path}\n"
                f"{self._fit(extra_content, per_extra_room)}"
            )
            if len(sources) >= MAX_EXTRA_PAGES + 1:
                break

        # Главная получает первый номер: ссылки вида «Источник 1» должны
        # вести на неё, а не на первую попавшуюся внутреннюю страницу.
        unused = max(0, extra_room - sum(len(part) for part in extras))
        main_room = MAX_SITE_TEXT_LENGTH - menu_room - extra_room + unused
        parts = [f"## Источник 1: {sources[0]['path']}\n{self._fit(content, main_room)}"]
        parts.extend(extras)
        if menu:
            parts.append(self._fit(menu, menu_room))
        return "\n\n".join(part for part in parts if part), sources

    def collect_site_text(self, url: str) -> str:
        """Текст главной плюс пара внутренних страниц, в пределах бюджета.

        Одной главной страницы каталога не хватает: там только меню, поэтому
        разбор выходил общим и не про конкретный товар.
        """
        text, _ = self.collect_site_evidence(url)
        return text

    def generate_analysis_steps(self, site_text: str) -> List[str]:
        """
        Генерирует список шагов для анализа сайта с помощью LLM.

        Args:
            site_text: Очищенный текст сайта

        Returns:
            Список шагов (промптов) для анализа
        """
        system_prompt = (
            "Ты бот-анализатор сайтов и маркетолог. "
            "В ответе в формате JSON выдай список из 4-5 шагов, "
            "которые нужно выполнить, чтобы подготовить таргетированную рекламу этого сайта. "
            "Каждый шаг — одно короткое повелительное предложение (до 120 знаков), "
            "без нумерации и без пояснений. Не повторяй текст сайта. "
            'Формат ответа: {"steps": ["шаг1", "шаг2", ...]}'
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
            # Шаг сам по себе был system-промптом без рамок: модель выдавала
            # по 4 KB рассуждений на шаг, и весь анализ шёл минут шесть.
            system_prompt = (
                "Ты маркетолог-аналитик. Выполни один шаг анализа сайта: "
                f"{step}. "
                "Опирайся только на переданный текст, не додумывай факты. "
                "Ответ до 1200 знаков, markdown-списком, без вступлений, "
                "заголовков h1 и пересказа исходного текста."
            )
            result = self.llm_client.chat_with_system(system_prompt, site_text)
            results.append({
                "step": step,
                "result": result,
                "step_number": i + 1
            })

        return results

    def generate_final_analysis(
        self,
        intermediate_results: List[Dict[str, str]],
        site_text: str,
        sources: List[Dict] | None = None,
    ) -> Dict:
        """
        Генерирует финальный анализ сайта на основе промежуточных результатов.

        Args:
            intermediate_results: Список промежуточных результатов
            site_text: Очищенный текст сайта

        Returns:
            Итоговый анализ с рекламными постами
        """
        # Собираем промежуточные ответы в один блок, ограничивая размер:
        # без потолка итоговый промпт разрастался до десятков килобайт.
        results_str = "\n\n".join([
            f"Шаг {r['step_number']}: {r['step']}\nРезультат: {self._fit(r['result'], 1600)}"
            for r in intermediate_results
        ])

        # Раньше промпт требовал «обязательно включи оригинальный текст сайта»:
        # модель пересказывала меню вместо разбора, а ответ упирался в лимит
        # токенов. Теперь требуются конкретные поля ограниченного размера,
        # включая сравнительную таблицу — её интерфейс рисует как таблицу.
        system_prompt = (
            "Ты маркетолог. Объедини результаты промежуточного анализа в итоговый "
            "отчёт по сайту. Факты бери только из переданных данных.\n\n"
            f"Результаты анализа:\n{results_str}\n\n"
            "Ответ строго в JSON со всеми полями:\n"
            "{\n"
            '  "brief_analysis": "краткий анализ сайта: кто продаёт, кому, чем цепляет; до 1500 знаков, markdown-список",\n'
            '  "key_facts": [ {"fact": "короткий проверяемый факт со страницы", "source": N}, ... 5-8 фактов, где N — номер из заголовка «Источник N» ],\n'
            '  "ad_instructions": "пошаговая инструкция по созданию рекламных постов; до 1500 знаков, нумерованный список",\n'
            '  "ad_examples": [ {"title": "заголовок", "body": "текст объявления", "cta": "призыв к действию"}, ... ровно 3 примера ],\n'
            '  "comparison_table": {"columns": ["Сегмент", "Боль", "УТП", "Канал"], "rows": [["...", "...", "...", "..."], ... 4-6 строк]}\n'
            "}\n"
            "Не вставляй в ответ оригинальный текст сайта целиком: максимум одна цитата длиной до 200 знаков. "
            "В rows и columns не переноси текст на новые строки. "
            "Номер источника указывай только тот, который есть в заголовках «Источник N»; своих адресов не выдумывай."
        )

        user_prompt = f"Контекст о сайте (фрагменты текста по источникам):\n{self._fit(site_text, 4000)}"

        response = self.llm_client.chat_json(system_prompt, user_prompt)

        return self._normalize_final_analysis(response, sources)

    @staticmethod
    def _markdown_table_to_grid(text: str) -> Dict:
        """Превращает markdown-таблицу в {columns, rows}.

        Модель иногда игнорирует схему и возвращает таблицу текстом; интерфейс
        и PDF рисуют такую сетку настоящими ячейками.
        """
        rows = []
        for line in str(text or "").splitlines():
            line = line.strip()
            if not (line.startswith("|") and line.endswith("|")):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                continue
            rows.append(cells)
        if len(rows) < 2:
            return {}
        width = max(len(row) for row in rows)
        grid = [row + [""] * (width - len(row)) for row in rows]
        return {"columns": grid[0], "rows": grid[1:]}

    @classmethod
    def _normalize_table(cls, value) -> Dict:
        if isinstance(value, str):
            return cls._markdown_table_to_grid(value)
        if not isinstance(value, dict):
            return {}

        columns = value.get("columns") or value.get("headers") or []
        rows = value.get("rows") or value.get("data") or []
        if not isinstance(columns, list) or not isinstance(rows, list) or not columns:
            return {}

        width = len(columns)
        clean_rows = []
        for row in rows:
            cells = row if isinstance(row, list) else list(row.values()) if isinstance(row, dict) else [row]
            cells = [str(cell).replace("\n", " ").strip() for cell in cells][:width]
            if any(cells):
                clean_rows.append(cells + [""] * (width - len(cells)))

        return {
            "columns": [str(column).strip() for column in columns],
            "rows": clean_rows,
        }

    @staticmethod
    def _source_index(sources) -> Dict[str, Dict]:
        """Индекс «номер страницы -> её адрес» из реально скачанного."""
        index: Dict[str, Dict] = {}
        for source in sources or []:
            if isinstance(source, dict) and source.get("url"):
                index[str(source.get("id"))] = source
        return index

    @classmethod
    def _resolve_source_reference(cls, value, index: Dict[str, Dict]) -> str:
        """Номер источника -> адрес страницы из реестра.

        Принимает «2», «Источник 2» и URL, который модель списала со страницы.
        Ссылку, которой нет в реестре, возвращает как нераспознанную: выдуманная
        ссылка в профессиональном отчёте хуже, чем её отсутствие.
        """
        if not index or value is None:
            return ""

        text = str(value).strip()
        if not text:
            return ""

        digits = re.findall(r"\d+", text)
        if len(digits) == 1:
            source = index.get(digits[0])
            if source:
                return source["url"]

        normalized = text.rstrip("/").lower()
        for source in index.values():
            if source["url"].rstrip("/").lower() == normalized:
                return source["url"]

        return SOURCE_REFERENCE_UNRESOLVED

    @classmethod
    def _normalize_key_facts(cls, value, sources) -> List[Dict]:
        """Факты с привязкой к страницам, на которых их можно проверить."""
        index = cls._source_index(sources)
        if isinstance(value, str):
            value = [line for line in value.splitlines() if line.strip()]
        if not isinstance(value, list):
            return []

        facts: List[Dict] = []
        for item in value:
            if isinstance(item, dict):
                fact = str(
                    item.get("fact") or item.get("claim") or item.get("text") or ""
                ).strip()
                reference = item.get("source") or item.get("source_id") or item.get("источник")
            else:
                fact, reference = str(item).strip(), None
            if not fact:
                continue

            url = cls._resolve_source_reference(reference, index)
            entry = {"fact": fact, "source": url or SOURCE_REFERENCE_UNRESOLVED}
            if url and url in {source["url"] for source in index.values()}:
                entry["page"] = next(
                    source["path"] for source in index.values() if source["url"] == url
                )
            facts.append(entry)
        return facts

    @staticmethod
    def _sources_table(sources) -> Dict:
        """Реестр прочитанных страниц как таблица отчёта."""
        if not sources:
            return {}
        rows = [
            [str(source["id"]), source["url"], source.get("title") or "", str(source["chars"])]
            for source in sources
            if isinstance(source, dict) and source.get("url")
        ]
        if not rows:
            return {}
        return {
            "columns": ["№", "Адрес страницы", "Заголовок страницы", "Знаков текста"],
            "rows": rows,
        }

    @classmethod
    def _normalize_final_analysis(cls, response: Dict, sources=None) -> Dict:
        """Приводит ответ модели к форме, которую рисуют интерфейс и PDF.

        Без этого списка строк в ad_examples превращались в кашу, таблица
        приходила текстом, а отсутствующие поля роняли экран результата.
        """
        if not isinstance(response, dict):
            raise Exception("LLM вернула итоговый анализ не в формате JSON-объекта")

        result = dict(response)

        for key in ("brief_analysis", "ad_instructions"):
            value = result.get(key)
            if isinstance(value, list):
                result[key] = "\n".join(str(item) for item in value)
            elif value is not None and not isinstance(value, str):
                result[key] = str(value)

        examples = result.get("ad_examples")
        if examples is None and isinstance(result.get("examples"), list):
            examples = result.pop("examples")
        if isinstance(examples, list):
            normalized = []
            for item in examples:
                if isinstance(item, dict):
                    entry = {str(key): str(value) for key, value in item.items()}
                    if any(entry.values()):
                        normalized.append(entry)
                elif isinstance(item, str) and item.strip():
                    lines = [line.strip() for line in item.splitlines() if line.strip()]
                    normalized.append(
                        {"title": lines[0], "body": "\n".join(lines[1:])} if len(lines) > 1 else {"body": item.strip()}
                    )
            result["ad_examples"] = normalized

        table = cls._normalize_table(result.get("comparison_table"))
        if table:
            result["comparison_table"] = table
        else:
            # Пустая таблица в отчёте выглядит как сломанный раздел.
            result.pop("comparison_table", None)

        key_facts = cls._normalize_key_facts(result.get("key_facts"), sources)
        if key_facts:
            result["key_facts"] = key_facts
        else:
            result.pop("key_facts", None)

        sources_table = cls._sources_table(sources)
        if sources_table:
            result["sources"] = sources_table

        return result

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
        # Шаг 1-2: скачиваем главную и внутренние страницы, приводим к
        # структурированному тексту в пределах бюджета и запоминаем, что читали.
        site_text, sources = self.collect_site_evidence(url)

        if not site_text or len(site_text) < 100:
            raise Exception("Не удалось получить достаточное количество текста с сайта")

        site_text = self._fit(site_text, MAX_SITE_TEXT_LENGTH)
        
        # Шаг 3: Генерируем список шагов для анализа
        steps = self.generate_analysis_steps(site_text)
        
        # Шаг 4: Выполняем каждый шаг анализа
        intermediate_results = self.execute_analysis_steps(steps, site_text)
        
        # Шаг 5: Генерируем финальный анализ
        final_analysis = self.generate_final_analysis(intermediate_results, site_text, sources)
        
        # Формируем итоговый результат
        return {
            "url": url,
            "steps": steps,
            "intermediate_results": intermediate_results,
            "final_analysis": final_analysis
        }
