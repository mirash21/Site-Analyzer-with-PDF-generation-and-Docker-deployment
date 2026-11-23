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
MAX_SITE_TEXT_LENGTH = 18000

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

# Кроме главной разбираем несколько внутренних страниц: у каталогов офферы
# лежат там, а на главной — только меню.
MAX_EXTRA_PAGES = 6
MAX_PAGES_PER_SECTION = 2
EXTRA_PAGES_SHARE = 0.45
MENU_SHARE = 0.06
SITE_FETCH_TIMEOUT = 15
MIN_EXTRA_PAGE_CHARS = 200
FACTS_BLOCK_ROOM = 1200

# Список семантики короче, чем фантазия модели: 60 фраз «купить инструмент»
# на одну страницу никто не проверяет, а платят за показ каждой.
MAX_KEYWORDS_PER_LIST = 25

# План кампании — отдельный ответ модели. В отчёт берутся только эти поля:
# модель часто возвращает вместе с планом поля разбора сайта, и там номер
# источника — число, а не ссылка; подмешивать такое к готовому нельзя.
CAMPAIGN_PLAN_KEYS = ("ad_instructions", "ad_examples", "keyword_seeds", "negative_keywords")

# Лимиты площадок по знакам: объявление, не проходящее в блок, просто не
# встанет в кампанию. Значения взяты из открытых правил площадок (Яндекс
# Директ: заголовок 56, текст 81; Google Ads: 30 и 90; VK Реклама: 40 и 90;
# Telegram Ads: один текст до 160, заголовка нет). Площадки меняют лимиты, поэтому
# отчёт показывает проверку, а не переписывает текст за модель.
PLATFORM_LIMITS = {
    "yandex": {"label": "Яндекс Директ", "title": 56, "body": 81},
    "google": {"label": "Google Ads", "title": 30, "body": 90},
    "vk": {"label": "VK Реклама", "title": 40, "body": 90},
    "telegram": {"label": "Telegram Ads", "title": 0, "body": 160},
}
PLATFORM_HINTS = {
    "yandex": ("директ", "яндекс", "yandex"),
    "google": ("google", "гугл", "adwords", "адворд"),
    "vk": ("vk", "вконтакт"),
    "telegram": ("telegram", "телеграм"),
}
UNKNOWN_PLATFORM = "площадка не указана"
MIN_ADS_PER_SEGMENT = 2
MAX_AD_EXAMPLES = 12

# Экономика тестовой кампании: бюджет фиксирован, арифметику считает код.
# Модель обязана назвать только допущения: иначе в отчёте появляется
# «средний чек 250 000 ₽» там, где на сайте не указано ни одной цены.
TEST_CAMPAIGN_BUDGET = 18000
NO_DATA = "нет данных"

# Модель ссылается на страницы только номерами: адрес она обязана взять из
# реестра, а не сочинять. Не распознанный номер факт не теряет, но помечается.
SOURCE_REFERENCE_UNRESOLVED = "источник не распознан"

# Ссылки, которые обычно ведут к офферу, а не к обвязке сайта. Ищем и по
# адресу, и по тексту ссылки: пути часто транслитерируют (katalog-produktsii),
# а якорь при этом остаётся русским.
PAGE_LINK_KEYWORDS = (
    "catalog", "katalog", "category", "product", "produkt", "goods",
    "price", "pric", "about", "company", "servic", "brand", "item",
    "contact", "kontak", "adres", "delivery", "dostavk", "oplata", "payment",
    "sertif", "dokument", "review", "otzyv",
    "каталог", "продукц", "товар", "цен", "услуг", "о-комп", "окомп", "бренд",
    "контакт", "адрес", "доставк", "оплат", "сертиф", "документ", "отзыв",
)

# Числа, которые отчёт обязан видеть в исходном виде. Модель не умеет читать
# разметку, а цены, телефоны и реквизиты нужны в отчёте дословно: иначе в
# экономическом разделе появляются красивые, но выдуманные значения.
PHONE_PATTERN = re.compile(r"(?:\+7|8)[\s(+]?[0-9()\- ]{9,18}[0-9]")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Форма + название из одного-трёх слов без цифр и запятых: жадный класс
# захватывал «ООО «Татинженер», ИНН 1657012345, ОГРН 10716» целиком.
# Стоп-слова снимают второй вариант той же ошибки — когда реквизиты идут
# без запятых и формально подходят под «ещё одно слово названия».
LEGAL_ENTITY_STOP_WORDS = r"ИНН|КПП|ОГРН\w*|тел\w*|факс\w*|e-?mail|почт\w*|сайт\w*|адрес\w*"
LEGAL_ENTITY_PATTERN = re.compile(
    r"\b(?:ООО|ОАО|ПАО|ЗАО|АО|ИП)\s*[«»\"']?\s*"
    rf"(?:(?!(?:{LEGAL_ENTITY_STOP_WORDS})\b)[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{{1,24}}[ ]?){{1,3}}[«»\"']?"
)
REQUISITE_PATTERNS = (
    ("ИНН", re.compile(r"ИНН\s*:?\s*(\d{10,12})", re.I)),
    ("КПП", re.compile(r"КПП\s*:?\s*(\d{10})", re.I)),
    ("ОГРН", re.compile(r"ОГРНИ?П?\s*:?\s*(\d{13,15})", re.I)),
)
PRICE_PATTERN = re.compile(r"(\d[\d\s\u00a0]{0,9})\s*(?:руб(?:\.|лей)?\b|₽)", re.I)
MIN_PLAUSIBLE_PRICE = 10
MAX_PLAUSIBLE_PRICE = 100_000_000

# Порядок разделов отчёта: сначала то, что клиент узнает про свой сайт,
# потом рекламные выводы, затем цифры и честно — чего не хватает.
REPORT_SECTION_ORDER = (
    "brief_analysis",
    "key_facts",
    "comparison_table",
    "site_gaps",
    "ad_instructions",
    "keyword_seeds",
    "negative_keywords",
    "ad_examples",
    "economics_table",
    "economics_assumptions",
    "risks_and_checks",
    "data_gaps",
    "data_coverage",
    "raw_site_data",
    "sources",
)

# Эти строки считает код, а не модель: отсутствие цен на сайте — факт
# разбора, и в отчёте оно обязано быть, даже если модель ответила красиво.
DATA_GAP_LABELS = {
    "prices": "Цен на прочитанных страницах нет — нужен прайс от клиента",
    "phones": "Телефонов на прочитанных страницах нет — проверить раздел «Контакты»",
    "emails": "Почты на прочитанных страницах нет",
    "legal_entities": "Юридическое лицо на сайте не указано — для рекламы это риск",
    "requisites": "Реквизитов (ИНН/ОГРН) не найдено — проверить раздел «О компании»",
}


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

    @staticmethod
    def _unique(values) -> List[str]:
        """Убирает повторы, порядок первого вхождения сохраняет."""
        seen: set = set()
        out: List[str] = []
        for value in values:
            cleaned = re.sub(r"\s+", " ", str(value)).strip(" .,;:")
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                out.append(cleaned)
        return out

    @staticmethod
    def _format_phone(digits: str) -> str:
        """11 цифр -> «+7 (843) 240-64-32»: один формат вместо восьми записей одного номера."""
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:]}"

    @classmethod
    def _phones_in(cls, text: str) -> List[str]:
        """Российские номера: одиннадцать цифр, начинаются с 7 или 8.

        По маске с кодом 9xx городские номера терялись, и отчёт выходил без
        телефона даже там, где он написан в шапке. Один и тот же номер в
        разметке встречается и как tel:, и как текст — считаем его один раз.
        """
        by_digits: Dict[str, str] = {}
        for raw in PHONE_PATTERN.findall(text):
            digits = re.sub(r"\D", "", raw)
            if len(digits) != 11 or digits[0] not in "78":
                continue
            by_digits.setdefault(digits[1:], cls._format_phone(digits))
        return list(by_digits.values())

    @classmethod
    def extract_business_facts(cls, html: str) -> Dict:
        """Телефоны, цены, юрлица и реквизиты, найденные в разметке страницы.

        Модель эти значения видит только если их передать текстом, а без них в
        экономическом разделе отчёта появляются правдоподобные, но выдуманные
        цифры. Здесь всё, что на сайте написано буквально.
        """
        try:
            visible = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            visible = ""

        # href="tel:..." и href="mailto:..." в видимом тексте отсутствуют.
        haystack = f"{html}\n{visible}"

        prices = []
        for raw in PRICE_PATTERN.findall(haystack):
            digits = re.sub(r"\D", "", raw)
            if not digits:
                continue
            value = int(digits)
            if MIN_PLAUSIBLE_PRICE <= value <= MAX_PLAUSIBLE_PRICE:
                prices.append(value)

        requisites = []
        for label, pattern in REQUISITE_PATTERNS:
            requisites.extend(f"{label} {value}" for value in pattern.findall(haystack))

        return {
            "phones": cls._phones_in(haystack),
            "emails": cls._unique(EMAIL_PATTERN.findall(haystack)),
            "legal_entities": cls._unique(LEGAL_ENTITY_PATTERN.findall(visible or haystack)),
            "requisites": cls._unique(requisites),
            "prices": sorted(set(prices)),
        }

    @classmethod
    def _merge_facts(cls, target: Dict, addition: Dict) -> Dict:
        for key in ("phones", "emails", "legal_entities", "requisites"):
            target[key] = cls._unique(list(target.get(key, [])) + list(addition.get(key, [])))
        target["prices"] = sorted(set(target.get("prices", [])) | set(addition.get("prices", [])))
        return target

    @staticmethod
    def _money(value: int) -> str:
        """1200 -> «1 200»: неразрывные пробелы в отчёте читают лучше запятых."""
        return f"{int(value):,}".replace(",", " ")

    @staticmethod
    def render_business_facts(facts: Dict) -> str:
        """Блок «что на страницах написано буквально» для промпта и отчёта."""
        prices = list(facts.get("prices") or [])
        lines = ["## Данные, найденные в разметке страниц (без интерпретации)"]

        def pair(label: str, values: List[str]) -> str:
            return f"{label}: " + ("; ".join(values) if values else "не найдены")

        lines.append(pair("Телефоны", facts.get("phones") or []))
        lines.append(pair("Почта", facts.get("emails") or []))
        lines.append(pair("Юридические лица", facts.get("legal_entities") or []))
        lines.append(pair("Реквизиты", facts.get("requisites") or []))

        if prices:
            sample = ", ".join(SiteAnalyzer._money(value) for value in prices[:8])
            lines.append(
                f"Цены: найдено {len(prices)} различных значений, диапазон "
                f"{SiteAnalyzer._money(min(prices))}–{SiteAnalyzer._money(max(prices))} руб. "
                f"Примеры: {sample}."
            )
        else:
            lines.append(
                "Цены: на прочитанных страницах не указаны. В отчёте так и писать, "
                "не подставляя вместо них отраслевые допущения."
            )
        return "\n".join(lines)

    @staticmethod
    def describe_coverage(sources: List[Dict], facts: Dict, budget: int) -> str:
        """Сколько реально прочитано: читатель должен знать потолок выводов."""
        read = sum(source.get("chars", 0) for source in sources or [])
        missing = [
            label
            for label, values in (
                ("телефоны", facts.get("phones")),
                ("почта", facts.get("emails")),
                ("юрлицо", facts.get("legal_entities")),
                ("реквизиты", facts.get("requisites")),
                ("цены", facts.get("prices")),
            )
            if not values
        ]
        parts = [
            f"Прочитано страниц: {len(sources or [])} (главная + "
            f"{max(len(sources or []) - 1, 0)} внутренних).",
            f"Знаков текста сайта: {read} из бюджета {budget}.",
        ]
        if missing:
            parts.append("Не найдено на прочитанных страницах: " + ", ".join(missing) + ".")
        return " ".join(parts)

    @staticmethod
    def _spread_over_sections(links: List[str]) -> List[str]:
        """Не больше MAX_PAGES_PER_SECTION ссылок из одного раздела сайта.

        Каталог выдаёт десятки однотипных подстраниц, и без ограничения
        анализ съедали шесть групп товаров, а контакты и условия поставки
        не попадали в поле зрения.
        """
        per_section: Dict[str, int] = {}
        spread: List[str] = []
        for link in links:
            section = (urlparse(link).path.strip("/").split("/") or [""])[0].lower()
            taken = per_section.get(section, 0)
            if taken >= MAX_PAGES_PER_SECTION:
                continue
            per_section[section] = taken + 1
            spread.append(link)
        return spread

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

        # Ограничение накладывается после разбора всех ссылок: если резать
        # сразу, шесть страниц каталога вытеснят контакты и цены.
        return self._spread_over_sections(links)[:MAX_EXTRA_PAGES]

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

    def collect_site_evidence(self, url: str) -> Tuple[str, List[Dict], Dict]:
        """Текст сайта, реестр прочитанных страниц и дословные данные с них.

        Реестр нужен, чтобы отчёт можно было проверить: модель ссылается на номер
        источника, а адрес подставляется здесь из реально скачанных страниц.
        Ссылка, сочинённая моделью, в отчёт не попадает.
        """
        html = self.fetch_site_html(url)
        content, menu = self.extract_page_text(html)
        if not content:
            raise Exception("На странице нет читаемого текста — возможно, сайт собран скриптами")

        start = urlparse(url)
        facts = self.extract_business_facts(html)
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
            self._merge_facts(facts, self.extract_business_facts(extra_html))

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
        facts_block = self.render_business_facts(facts)
        unused = max(
            0,
            extra_room - sum(len(part) for part in extras) - len(facts_block),
        )
        main_room = MAX_SITE_TEXT_LENGTH - menu_room - extra_room + unused
        parts = [f"## Источник 1: {sources[0]['path']}\n{self._fit(content, main_room)}"]
        parts.extend(extras)
        parts.append(self._fit(facts_block, FACTS_BLOCK_ROOM))
        if menu:
            parts.append(self._fit(menu, menu_room))
        return "\n\n".join(part for part in parts if part), sources, facts

    def collect_site_text(self, url: str) -> str:
        """Текст главной плюс внутренние страницы, в пределах бюджета.

        Одной главной страницы каталога не хватает: там только меню, поэтому
        разбор выходил общим и не про конкретный товар.
        """
        text, _, _ = self.collect_site_evidence(url)
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
        facts: Dict | None = None,
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
            '  "comparison_table": {"columns": ["Сегмент", "Боль", "УТП", "Канал"], "rows": [["...", "...", "...", "..."], ... 4-6 строк]},\n'
            '  "site_gaps": ["что на сайте мешает конверсии — 3-6 пунктов, только то, что видно на прочитанных страницах"],\n'
            '  "risks_and_checks": ["что проверить перед запуском: дилерские права, товарные знаки брендов, актуальность сертификатов, сроки поставки — 3-6 пунктов"],\n'
            '  "data_gaps": ["каких данных на сайте нет и потому нет в отчёте — 2-5 пунктов"],\n'
            "}\n"
            "Не вставляй в ответ оригинальный текст сайта целиком: максимум одна цитата длиной до 200 знаков. "
            "В rows и columns не переноси текст на новые строки. "
            "Номер источника указывай только тот, который есть в заголовках «Источник N»; своих адресов не выдумывай. "
            "Если данных нет — честно пиши об этом в data_gaps, не заменяя их догадками."
        )

        user_prompt = f"Контекст о сайте (фрагменты текста по источникам):\n{self._fit(site_text, 4000)}"

        response = self.llm_client.chat_json(system_prompt, user_prompt)

        return self._normalize_final_analysis(response, sources, facts)

    def generate_campaign_plan(
        self,
        intermediate_results: List[Dict[str, str]],
        site_text: str,
        facts: Dict | None = None,
    ) -> Dict:
        """План кампании: инструкция, семантика и минус-слова — отдельным запросом.

        В один JSON модель начала обрезаться на середине, а половина отчёта
        хуже двух целых: здесь у каждого ответа свой умеренный бюджет токенов.
        """
        results_str = "\n\n".join(
            f"Шаг {r['step_number']}: {r['step']}\nРезультат: {self._fit(r['result'], 1600)}"
            for r in intermediate_results
        )
        literal = self.render_business_facts(facts) if facts else ""

        system_prompt = (
            "Ты рекламный специалист. По результатам анализа сайта собери план кампании. "
            "Фразы должны браться из товаров и услуг этого сайта, а не из общих слов о рекламе.\n\n"
            f"Результаты анализа:\n{results_str}\n\n"
            + (f"{literal}\n\n" if literal else "")
            + "Ответ строго в JSON со всеми полями:\n"
            "{\n"
            '  "ad_instructions": "пошаговая инструкция по запуску кампании; до 1500 знаков, нумерованный список",\n'
            '  "ad_examples": [ {"segment": "сегмент", "platform": "Яндекс Директ | Google Ads | VK Реклама | Telegram Ads", "title": "заголовок объявления", "body": "текст объявления", "cta": "призыв к действию"}, ... 6-12 объявлений: на каждый сегмент два ],\n'
            '  "keyword_seeds": ["поисковые фразы из 2-5 слов, соответствующие товарам и услугам сайта — 12-20 штук"],\n'
            '  "negative_keywords": ["минус-слова, отсекающие нецелевые показы — 10-20 штук"],\n'
            "}\n"
            "Фразы пиши без кавычек, операторов и переносов строк, в начальной форме. "
            "Одна фраза не может быть одновременно в семантике и в минус-листах.\n\n"
            "Про объявления: на каждый сегмент ровно два варианта — один про выгоду, второй про возражение "
            "или страх клиента. Площадку указывай одной из: Яндекс Директ, Google Ads, VK Реклама, Telegram Ads. "
            "Держись в лимитах знаков: Яндекс Директ — заголовок 56, текст 81; Google Ads — 30 и 90; "
            "VK Реклама — 40 и 90; Telegram Ads — один текст до 160 знаков, заголовка там нет. "
            "Пробелы, знаки препинания и цифры считаются; одно слово в заголовке — не длиннее 22 знаков."
        )

        user_prompt = f"Контекст о сайте (фрагменты текста):\n{self._fit(site_text, 3000)}"

        response = self.llm_client.chat_json(system_prompt, user_prompt)

        return self._normalize_campaign_plan(response)

    def generate_economics(
        self,
        intermediate_results: List[Dict[str, str]],
        site_text: str,
        facts: Dict | None = None,
    ) -> Dict:
        """Цифры кампании: модель называет допущения, итог считает код.

        Так в отчёте остаётся прослеживаемость: видно, какая цифра взята со
        страницы, какая предложена как допущение и по какой формуле получена.
        """
        facts = facts or {}
        literal = self.render_business_facts(facts)
        results_str = "\n\n".join(
            f"Шаг {r['step_number']}: {r['step']}\nРезультат: {self._fit(r['result'], 900)}"
            for r in intermediate_results
        )

        system_prompt = (
            "Ты медиапланер. Оцени экономику тестовой кампании этого сайта. "
            f"Бюджет теста фиксированный: {self._money(TEST_CAMPAIGN_BUDGET)} ₽ — считать по нему. "
            "Итоги не выводи, их считает код: тебе нужны только допущения.\n\n"
            f"{literal}\n\n"
            "Ответ строго в JSON со всеми полями:\n"
            "{\n"
            '  "cpc": цена клика в рублях — число,\n'
            '  "conversion_rate": конверсия сайта в заявку в процентах — число,\n'
            '  "margin": наценка в процентах от цены — число,\n'
            '  "avg_check": средний чек в рублях — число или null,\n'
            '  "notes": ["что ещё учесть при запуске — 2-4 коротких пункта"]\n'
            "}\n"
            "Если на страницах есть цены — avg_check оставь null: средний чек возьмут из них. "
            "Не знаешь значения — ставь null, угаданное число в медиаплане стоит денег."
        )

        user_prompt = (
            f"Результаты анализа:\n{self._fit(results_str, 2500)}\n\n"
            f"Фрагменты текста сайта:\n{self._fit(site_text, 1500)}"
        )

        response = self.llm_client.chat_json(system_prompt, user_prompt)

        return self._build_economics(response, facts)

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
    def _normalize_string_list(cls, value) -> List[str]:
        """Список пунктов из того, что реально может вернуть модель.

        Модель отдаёт то markdown-список, то одну строку через переносы, то
        список объектов — интерфейс же ждёт ровно список строк.
        """
        if value is None:
            return []
        if isinstance(value, str):
            items: List = value.splitlines()
        elif isinstance(value, (list, tuple)):
            items = list(value)
        else:
            items = [value]

        cleaned: List[str] = []
        for item in items:
            if isinstance(item, dict):
                item = next((found for found in item.values() if isinstance(found, str) and found.strip()), "")
            text = re.sub(r"^\s*(?:[-*+]|\d{1,3}[.)])\s*", "", str(item or "")).strip()
            if text:
                cleaned.append(text)
        return cls._unique(cleaned)

    @classmethod
    def _seed_data_gaps(cls, facts) -> List[str]:
        """Чего не хватает — по факту разбора, а не по желанию модели."""
        facts = facts or {}
        return [label for key, label in DATA_GAP_LABELS.items() if not facts.get(key)]

    @classmethod
    def _merge_data_gaps(cls, model_gaps: List[str], facts) -> List[str]:
        return cls._unique(cls._seed_data_gaps(facts) + list(model_gaps))

    @staticmethod
    def _order_sections(result: Dict) -> Dict:
        """Разделы отчёта идут в порядке чтения, а не в порядке фантазии модели."""
        ordered = {key: result[key] for key in REPORT_SECTION_ORDER if key in result}
        for key, value in result.items():
            ordered.setdefault(key, value)
        return ordered

    @staticmethod
    def _match_platform(value) -> str:
        """Площадка из текста модели: «Директ», «Яндекс Директ (поиск)», «vк»."""
        text = str(value or "").strip().lower()
        for key, hints in PLATFORM_HINTS.items():
            if any(hint in text for hint in hints):
                return key
        return ""

    @classmethod
    def _check_ad_limits(cls, ad: Dict) -> Dict:
        """Считает знаки объявления против лимита площадки.

        Обрезание «под лимит» молча меняет смысл оффера, поэтому код только
        измеряет и говорит, что сокращать.
        """
        key = cls._match_platform(ad.get("platform"))
        if not key:
            ad["platform"] = UNKNOWN_PLATFORM
            return ad

        limits = PLATFORM_LIMITS[key]
        title = ad.get("title") or ""
        body = ad.get("body") or ""
        ad["platform"] = limits["label"]

        parts = []
        over = []
        if limits["title"]:
            parts.append(f"заголовок {len(title)}/{limits['title']}")
            if len(title) > limits["title"]:
                over.append(f"заголовок длиннее на {len(title) - limits['title']} зн.")
        parts.append(f"текст {len(body)}/{limits['body']}")
        if len(body) > limits["body"]:
            over.append(f"текст длиннее на {len(body) - limits['body']} зн.")

        ad["char_fit"] = " · ".join(parts)
        if over:
            # Лимит превышен — такое объявление не пройдёт модерацию.
            ad["limit_note"] = "; ".join(over) + " — сокращать до запуска"
        return ad

    @classmethod
    def _ad_coverage_notes(cls, value, ads: List[Dict]) -> List[str]:
        """Чем код дополняет креативы: площадка, вариантность, срезка списка."""
        notes: List[str] = []
        if isinstance(value, list) and len(value) > MAX_AD_EXAMPLES:
            notes.append(
                f"Модель дала {len(value)} объявлений — оставлены первые {MAX_AD_EXAMPLES}, иначе отчёт не читается."
            )

        unknown = sum(1 for ad in ads if ad.get("platform") == UNKNOWN_PLATFORM)
        if unknown:
            notes.append(f"У {unknown} объявлений нет площадки — лимиты знаков не проверены.")

        counts: Dict[str, int] = {}
        for ad in ads:
            segment = (ad.get("segment") or "").strip() or "без сегмента"
            counts[segment] = counts.get(segment, 0) + 1
        for segment, count in counts.items():
            if count < MIN_ADS_PER_SEGMENT:
                notes.append(
                    f"Сегмент «{segment}»: объявлений {count} — нужен второй вариант, про возражение или страх."
                )
        return notes

    @classmethod
    def _normalize_ad_examples(cls, value) -> List[Dict]:
        """Объявления в форму, которую рисуют интерфейс и PDF."""
        if value is None:
            return []
        if not isinstance(value, list):
            return []

        normalized: List[Dict] = []
        for item in value:
            if isinstance(item, dict):
                entry = {str(key): str(val) for key, val in item.items()}
                if any(entry.values()):
                    normalized.append(cls._check_ad_limits(entry))
            elif isinstance(item, str) and item.strip():
                lines = [line.strip() for line in item.splitlines() if line.strip()]
                entry = (
                    {"title": lines[0], "body": "\n".join(lines[1:])} if len(lines) > 1 else {"body": item.strip()}
                )
                normalized.append(cls._check_ad_limits(entry))
            if len(normalized) >= MAX_AD_EXAMPLES:
                break
        return normalized

    @classmethod
    def _normalize_keywords(cls, result: Dict) -> None:
        """Семантика и минус-слова: списки ограничены, пересечение снято.

        Одна и та же фраза в семантике и в минус-листе обнуляет показы: решение
        за исключением — оно безопаснее для бюджета.
        """
        seeds = cls._normalize_string_list(result.get("keyword_seeds"))[:MAX_KEYWORDS_PER_LIST]
        negatives = cls._normalize_string_list(result.get("negative_keywords"))[:MAX_KEYWORDS_PER_LIST]

        excluded = {item.lower() for item in negatives}
        seeds = [item for item in seeds if item.lower() not in excluded]

        for key, values in (("keyword_seeds", seeds), ("negative_keywords", negatives)):
            if values:
                result[key] = values
            else:
                result.pop(key, None)

    @staticmethod
    def _positive_number(value) -> float | None:
        """Число из любой формы, которую даёт модель: «38,5 ₽», 38, None.

        Отрицательное или нулевое допущение ломает всю арифметику плана, поэтому
        такое значение считается отсутствующим.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            number = float(value)
        else:
            text = str(value or "").replace("\u00a0", " ").replace(",", ".")
            match = re.search(r"\d+(?:\.\d+)?", text)
            if not match:
                return None
            number = float(match.group())
        return number if number > 0 else None

    @staticmethod
    def _median(values: List[int]) -> int | None:
        if not values:
            return None
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return int((values[middle - 1] + values[middle]) / 2)

    @classmethod
    def _build_economics(cls, response, facts: Dict | None = None) -> Dict:
        """Считает план кампании по допущениям модели и ценам сайта."""
        if not isinstance(response, dict):
            raise Exception("LLM не вернула экономику кампании в формате JSON-объекта")

        facts = facts or {}
        budget = TEST_CAMPAIGN_BUDGET
        cpc = cls._positive_number(response.get("cpc"))
        conversion = cls._positive_number(response.get("conversion_rate"))
        margin = cls._positive_number(response.get("margin"))

        prices = sorted({int(value) for value in (facts.get("prices") or []) if isinstance(value, (int, float))})
        if prices:
            avg_check = float(cls._median(prices))
            check_origin = f"медиана из {len(prices)} цен со страниц сайта"
        else:
            avg_check = cls._positive_number(response.get("avg_check"))
            check_origin = (
                "оценка модели — на прочитанных страницах цен нет" if avg_check else "цен на сайте нет, чек неизвестен"
            )

        clicks = int(budget // cpc) if cpc else None
        leads = int(clicks * conversion / 100) if clicks and conversion else None
        cpl = int(budget / leads) if leads else None
        profit = int(avg_check * margin / 100) if avg_check and margin else None
        payback = -(-budget // profit) if profit else None

        def money(value):
            return f"{cls._money(value)} ₽" if value else NO_DATA

        rows = [
            ["Бюджет теста", money(budget), "фиксирован в отчёте"],
            ["Цена клика (CPC)", money(int(cpc)) if cpc else NO_DATA, "допущение модели — проверить в кабинете"],
            ["Кликов", cls._money(clicks) if clicks else NO_DATA, "бюджет / CPC"],
            ["Конверсия сайта", f"{conversion:g}%" if conversion else NO_DATA, "допущение модели"],
            ["Заявок", cls._money(leads) if leads else NO_DATA, "клики × конверсия"],
            ["Цена заявки (CPL)", money(cpl), "бюджет / заявки"],
            ["Средний чек", money(int(avg_check)) if avg_check else NO_DATA, check_origin],
            ["Наценка", f"{margin:g}%" if margin else NO_DATA, "допущение модели — уточнить у клиента"],
            ["Прибыль с продажи", money(profit), "средний чек × наценка"],
            ["Продаж для окупаемости", cls._money(payback) if payback else NO_DATA, "бюджет / прибыль с продажи"],
        ]

        assumptions = [
            "Клики = бюджет / CPC; заявок = клики × конверсия; CPL = бюджет / заявок.",
            "Окупаемость = бюджет / (средний чек × наценка). Конверсию заявки в договор "
            "не учитывали: в B2B она заметно меньше единицы, реальный план ниже.",
        ]
        if not prices:
            assumptions.append("Средний чек — допущение, а не факт: запросите у клиента прайс.")
        assumptions.extend(cls._normalize_string_list(response.get("notes"))[:4])

        result: Dict = {"economics_table": {"columns": ["Показатель", "Значение", "Откуда"], "rows": rows}}
        unique_assumptions = cls._unique(assumptions)
        if unique_assumptions:
            result["economics_assumptions"] = unique_assumptions
        return result

    @classmethod
    def _normalize_campaign_plan(cls, response: Dict) -> Dict:
        """План кампании: те же правила формы, что и для остального отчёта."""
        if not isinstance(response, dict):
            raise Exception("LLM не вернула план кампании в формате JSON-объекта")

        result = {key: response[key] for key in CAMPAIGN_PLAN_KEYS if key in response}

        instructions = cls._normalize_string_list(result.get("ad_instructions"))
        if instructions:
            result["ad_instructions"] = "\n".join(
                f"{index}. {item}" for index, item in enumerate(instructions, start=1)
            )
        elif isinstance(result.get("ad_instructions"), str):
            result["ad_instructions"] = result["ad_instructions"].strip()
        else:
            result.pop("ad_instructions", None)

        examples = cls._normalize_ad_examples(result.get("ad_examples"))
        notes = cls._ad_coverage_notes(result.get("ad_examples"), examples)
        if examples:
            result["ad_examples"] = examples
        else:
            result.pop("ad_examples", None)

        cls._normalize_keywords(result)
        if notes:
            # Служебное поле: analyze_site переносит его в честный блок отчёта.
            result["coverage_notes"] = notes
        return result

    @classmethod
    def _normalize_final_analysis(cls, response: Dict, sources=None, facts=None) -> Dict:
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

        examples = cls._normalize_ad_examples(
            result.get("ad_examples") if result.get("ad_examples") is not None else result.get("examples")
        )
        if examples:
            result["ad_examples"] = examples
        else:
            result.pop("ad_examples", None)
            result.pop("examples", None)

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

        # Потолочный разбор: читатель обязан видеть, сколько реально прочитано
        # и чего на страницах не было. Это считает код, а не модель.
        if sources:
            facts = facts or {}
            result["data_coverage"] = cls.describe_coverage(sources, facts, MAX_SITE_TEXT_LENGTH)
            if any(facts.get(key) for key in ("phones", "emails", "legal_entities", "requisites", "prices")):
                result["raw_site_data"] = cls.render_business_facts(facts)

        for key in ("site_gaps", "risks_and_checks", "data_gaps"):
            values = cls._normalize_string_list(result.get(key))
            if values:
                result[key] = values
            else:
                result.pop(key, None)

        if facts is not None:
            # Отсутствие цен на сайте — вывод кода, а не модели: без этого
            # честный раздел мог «забыться» в любом удачном ответе.
            merged = cls._merge_data_gaps(result.get("data_gaps", []), facts)
            if merged:
                result["data_gaps"] = merged

        return cls._order_sections(result)

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
        site_text, sources, facts = self.collect_site_evidence(url)

        if not site_text or len(site_text) < 100:
            raise Exception("Не удалось получить достаточное количество текста с сайта")

        site_text = self._fit(site_text, MAX_SITE_TEXT_LENGTH)
        
        # Шаг 3: Генерируем список шагов для анализа
        steps = self.generate_analysis_steps(site_text)
        
        # Шаг 4: Выполняем каждый шаг анализа
        intermediate_results = self.execute_analysis_steps(steps, site_text)
        
        # Шаг 5: Генерируем финальный анализ
        final_analysis = self.generate_final_analysis(intermediate_results, site_text, sources, facts)

        # Шаг 6: дополнительные ответы модели. В один JSON она обрезалась на
        # середине, а половина отчёта хуже двух целых ответов: план кампании и
        # экономика идут отдельными запросами.
        extras = (
            ("план кампании", self.generate_campaign_plan, ("ad_examples", "keyword_seeds", "negative_keywords"),
             "Семантика и минус-слова не сгенерированы — их придётся подбирать вручную."),
            ("экономику", self.generate_economics, ("economics_table", "economics_assumptions"),
             "Экономика кампании не посчитана — CPC и CPL придётся брать из кабинета."),
        )
        notes: List[str] = []
        for name, generate, owned_keys, missing_note in extras:
            try:
                part = generate(intermediate_results, site_text, facts)
            except Exception as exc:  # noqa: BLE001 - без части отчёт всё равно полезен
                # Поля принадлежат этому ответу. Если модель вернула их же в
                # первом ответе, они не нормализованы и выглядят в отчёте мусором.
                for key in owned_keys:
                    final_analysis.pop(key, None)
                notes.append(missing_note)
                print(f"{name} не собрано: {exc}")
                continue
            notes.extend(part.pop("coverage_notes", []))
            # Честный блок считает код по данным сайта — дополнительные ответы
            # модели его не затирают.
            part.pop("data_gaps", None)
            final_analysis = self._order_sections({**final_analysis, **part})

        if notes:
            final_analysis["data_gaps"] = self._unique(list(final_analysis.get("data_gaps", [])) + notes)

        # Формируем итоговый результат
        return {
            "url": url,
            "steps": steps,
            "intermediate_results": intermediate_results,
            "final_analysis": final_analysis
        }
