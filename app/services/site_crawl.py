"""Планирование обхода сайта: глубже без раздувания текста для модели.

Одной главной и шести страниц из меню не хватает: прайс живёт в листинге,
условия поставки — в третьем уровне вложенности, а счётчик не стоит там, где
его ищут. При этом текст, уходящий модели, ограничен бюджетом, и расширять его
нельзя — отчёт дорожает и обрезается.

Разделение простое: читает обход много страниц, а в прозу идут только те, где
содержание действительно новое. Остальные работают фактами — проверками разметки,
дословными телефонами и ценами, списком ссылок для пробы.

Сети здесь нет: скачивание делает анализатор, а этот модуль считает, что уже
видено, куда идти дальше и почему отказал.
"""

import hashlib
import re
import time
from typing import Callable, Dict, List, Tuple
from urllib.parse import parse_qs, urldefrag, urlparse

# Страниц обхода больше, чем страниц в тексте: модель читает выбранное, код
# смотрит всё. 18 — потолок по времени, а не по вкусу.
MAX_CRAWL_PAGES = 18
MAX_PAGES_PER_SECTION = 4
MAX_PAGES_PER_GROUP = 3
# Ссылок с прочитанной страницы берём много: их разбор стоит только чтения
# HTML в памяти, а не запроса. Отрезать пришлось бы пагинацию — на листингах
# она стоит после карточек товаров, и узкая выборка никогда бы до неё не дошла.
MAX_NEW_LINKS_PER_PAGE = 40
# Кандидатов с главной берут больше, чем страниц в потолке обхода: иначе ссылки
# за вычетом потолка исчезают молча, и «не дошли 8 ссылок» превращается в «обшли всё».
MAX_CANDIDATE_LINKS = 60

# Обход ждут минуты: страница может думать пятнадцать секунд, и на десятой
# такой аудит превращается в ожидание таймаута.
CRAWL_BUDGET_SECONDS = 50.0

# Страница из двух абзацев меню фактов не даёт.
MIN_PAGE_CHARS = 120

# Доля слов, которых мы ещё не видели. Ниже — это тот же текст под другим
# адресом, и в отчёт он должен попасть как дубль, а не как источник.
NOVELTY_FOR_TEXT = 0.12

# Слова выводов едины для всех проверок, посчитанных кодом: клиент читает
# таблицы подряд, и «ок» рядом с «норма» означает для него разные оценки.
OK = "норма"
CHECK = "проверить"
BAD = "ошибка"

# Пагинация листинга: один и тот же раздел, разные страницы. Имена параметров
# взяты из типовых CMS (Bitrix — PAGEN_N, большинство — page/p).
PAGE_PARAMS = ("page", "p", "pn", "pagenum", "pagen", "start", "offset")
PAGE_NUMBER = re.compile(r"^pagen_\d+$")
PAGED_PATH = re.compile(r"/page/(\d+)(/?$)", re.I)
# Слова содержательной части и числа от двух знаков. Цифры нужны потому:
# страницы листинга отличаются ценами и артикулами, и «тот же текст с другими
# цифрами» — это другие предложения клиенту, а не дубль.
WORD = re.compile(r"[а-яёa-z]{3,}|\d{2,}", re.I)

# Причины, по которым страница не попала в обход. Перечислены явно: «не
# проверено всё» и «проверено всё» — разные выводы для клиента.
REASONS = {
    "section": "раздел уже прочитан достаточно",
    "group": "листинг прочитан достаточно глубоко",
    "budget": "страниц в обходе уже достаточно",
    "time": "бюджет времени обхода исчерпан",
    "thin": "на странице почти нет текста",
}


def norm(url: str) -> str:
    """Адрес без якоря и косой черты на конце — так одна страница не станет двумя."""
    return urldefrag(str(url or "")).url.rstrip("/").lower()


def section_of(url: str) -> str:
    """Первый сегмент пути: «каталог», «uslugi», «kontakty»."""
    return (urlparse(url).path.strip("/").split("/") or [""])[0].lower()


def pagination_of(url: str) -> Tuple[str, int]:
    """(группа листинга, номер страницы). Группа одинакова у всех страниц одного листа.

    Номер ищут и в параметре (page, p, pn, BITRIX_PAGEN_N), и в пути
    (/catalog/page/2/). Прочие параметры — сортировка, вид, фильтр — группой
    считаются: тот же список, переставленный по цене, новой страницей не нужен.
    """
    parsed = urlparse(url)
    page = 0
    for key, values in parse_qs(parsed.query or "").items():
        low = key.lower()
        if low in PAGE_PARAMS or PAGE_NUMBER.match(low):
            digits = re.sub(r"\D", "", values[0] if values else "")
            page = max(page, int(digits) if digits else 0)
    path = parsed.path
    match = PAGED_PATH.search(path)
    if match:
        page = max(page, int(match.group(1)))
        path = path[: match.start()] + (match.group(2) or "")
    base = f"{parsed.netloc.lower()}{path.rstrip('/')}"
    return base, page


def words_of(text: str) -> set:
    """Слова содержательной части: цифры и артикулы страницы листинга различают,
    а оформительский мусор — нет."""
    return set(WORD.findall(str(text or "").lower()))


def signature(text: str) -> str:
    """Отпечаток содержания. Порядок слов не важен: карточки в листинге меняются
    местами, а страницей-новизной быть не перестают."""
    words = sorted(words_of(text))
    if not words:
        return ""
    return hashlib.sha1(" ".join(words).encode("utf-8")).hexdigest()[:16]


class CrawlPolicy:
    """Кто уже прочитан, куда идти дальше и почему отказали.

    Состояние держится здесь, а не в анализаторе: лимиты раздела, группы
    листинга и бюджета времени связаны между собой, и проверять их по месту
    скачивания нельзя — иначе отказ пришёл бы уже потратив запрос.
    """

    def __init__(self, max_pages: int = MAX_CRAWL_PAGES,
                 max_per_section: int = MAX_PAGES_PER_SECTION,
                 max_per_group: int = MAX_PAGES_PER_GROUP,
                 min_chars: int = MIN_PAGE_CHARS,
                 novelty_floor: float = NOVELTY_FOR_TEXT,
                 budget: float = CRAWL_BUDGET_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self.max_pages = max_pages
        self.max_per_section = max_per_section
        self.max_per_group = max_per_group
        self.min_chars = min_chars
        self.novelty_floor = novelty_floor
        self.budget = budget
        self.clock = clock
        self.started = clock()

        self.pages: Dict[str, Dict] = {}
        self.duplicates: List[Dict] = []
        self.failures: List[Dict] = []
        self.refused: Dict[str, int] = {}
        self.lexicon: set = set()
        self._signs: Dict[str, str] = {}
        self.stopped = ""
        self.pending = 0

    # --- решения до скачивания ------------------------------------------------

    def reason_for(self, url: str) -> str:
        """Почему страницу брать нельзя. Пустая строка — можно."""
        if self.time_left() <= 0:
            return "time"
        if len(self.pages) >= self.max_pages:
            return "budget"
        if not url:
            return "budget"
        section = section_of(url)
        if section and self._count(section=section) >= self.max_per_section:
            return "section"
        group, _ = pagination_of(url)
        if group and self._count(group=group) >= self.max_per_group:
            return "group"
        return ""

    def allow(self, url: str) -> bool:
        """Брать ли страницу: отказ учитывается, чтобы отчёт видел недосмотр."""
        reason = self.reason_for(url)
        if reason:
            self.refuse(url, reason)
            return False
        return True

    def refuse(self, url: str, reason: str) -> None:
        self.refused[reason] = self.refused.get(reason, 0) + 1
        if reason in ("time", "budget") and not self.stopped:
            self.stopped = REASONS[reason]

    def time_left(self) -> float:
        return self.budget - (self.clock() - self.started)

    def wants_more(self) -> bool:
        return self.time_left() > 0 and len(self.pages) < self.max_pages

    def bucket_of(self, url: str) -> int:
        """Насколько адрес интереснее остальных — 0 самый желанный.

        Список ссылок листинга идёт в порядке страницы: первыми идут карточки
        товаров, пагинация — в самом низу. Отбирать ссылки по порядку значит
        никогда не дочитать до второй страницы прайса, где цены другие.
        """
        if self.reason_for(url):
            return 3
        section = section_of(url)
        if section and not self._count(section=section):
            return 0
        group, page = pagination_of(url)
        if page and self._count(group=group):
            return 1
        return 2

    def rank(self, links: List[str]) -> List[str]:
        """Порядок обхода: новые разделы, затем продолжение начатого листинга.

        Ранжирование пересчитывают после каждой прочитанной страницы: «новый
        раздел» и «осталось место» меняются вместе с прочитанным, и порядок,
        посчитанный один раз на старте, быстро становится вымышленным.
        """
        decorated = [
            (self.bucket_of(link), pagination_of(link)[1], index, link)
            for index, link in enumerate(links)
        ]
        return [item[3] for item in sorted(decorated)]

    def leftover(self, pending: int) -> None:
        """Сколько ссылок осталось за пределами обхода.

        Молча бросить очередь на середине — значит сказать клиенту «проверено
        всё», где просто кончилось время.
        """
        self.pending = max(0, int(pending))
        if not self.pending:
            return
        if self.time_left() <= 0:
            reason = "time"
        elif len(self.pages) >= self.max_pages:
            reason = "budget"
        else:
            return
        if not self.stopped:
            self.stopped = REASONS[reason]

    # --- решения после скачивания --------------------------------------------

    def novelty(self, text: str) -> float:
        """Доля слов, которых нет в уже прочитанном."""
        words = words_of(text)
        if not words:
            return 0.0
        return len(words - self.lexicon) / len(words)

    def take(self, url: str, text: str, root: bool = False) -> str:
        """Принять страницу. Ответ: read | repeat | thin | duplicate.

        Главная не бывает «слишком тонкой», чтобы не войти в обход: её читают
        всегда, и проверки разметки считают по ней в первую очередь.
        """
        key = norm(url)
        if key in self.pages:
            return "repeat"
        chars = len(str(text or "").strip())
        if chars < self.min_chars and not root:
            self.refuse(url, "thin")
            return "thin"
        sign = signature(text)
        same_as = self._signs.get(sign)
        if sign and same_as:
            self.duplicates.append({"url": key, "same_as": same_as})
            return "duplicate"
        fresh = self.novelty(text)
        section = section_of(url)
        group, page = pagination_of(url)
        self.pages[key] = {
            "url": key,
            "chars": chars,
            "section": section,
            "group": group,
            "page": page,
            "depth": len([part for part in urlparse(url).path.split("/") if part]),
            "novelty": fresh,
            "read": self.time_left(),
        }
        if sign:
            self._signs[sign] = key
        self.lexicon |= words_of(text)
        return "read"

    def goes_to_text(self, url: str) -> bool:
        """Идёт ли страница в текст модели: только новое по содержанию.

        Считается по новизне, сохранённой в момент чтения: лексикон уже пополнен
        этой страницей, и измеряй его после — каждая страница показалась бы дублем.
        Иначе бюджет съедают шесть страниц каталога с одними и теми же словами,
        а контакты и условия поставки до модели не доходят.
        """
        page = self.pages.get(norm(url))
        return bool(page) and page["novelty"] >= self.novelty_floor

    # --- учёт сбоев и итог ---------------------------------------------------

    def note_failure(self, url: str, reason: str = "") -> None:
        """Страница не открылась: для аудита это находка, а не тихий пропуск."""
        self.failures.append({"url": norm(url), "reason": (str(reason or "")[:120])})

    def _count(self, section: str = "", group: str = "") -> int:
        if section:
            return sum(1 for page in self.pages.values() if page["section"] == section)
        return sum(1 for page in self.pages.values() if page["group"] == group)

    def summary(self, quoted: int = 0) -> Dict:
        sections = sorted({page["section"] for page in self.pages.values() if page["section"]})
        return {
            "pages": len(self.pages),
            "limit": self.max_pages,
            "text_pages": int(quoted),
            "depth": max((page["depth"] for page in self.pages.values()), default=0),
            "paged": sum(1 for page in self.pages.values() if page["page"] > 0),
            "sections": sections,
            "duplicates": self.duplicates,
            "failures": self.failures,
            "refused": dict(self.refused),
            "pending": self.pending,
            "stopped": self.stopped,
            "seconds": round(self.clock() - self.started, 1),
            "budget": self.budget,
        }


def describe_pages(sources: List[Dict], crawl: Dict) -> str:
    """Сколько страниц прочитано и сколько из них стало текстом для модели.

    Число источников больше не равно числу прочитанного: обход читает дольше,
    чем цитирует. «Прочитано 7» при восемнадцати скачанных страницах
    присваивает проверки дублей к цитатам, а «прочитано 18» в списке из семи
    источников обещает разбор, которого читатель в отчёте не найдёт.
    """
    quoted = len(sources or [])
    read = int(crawl.get("pages") or 0)
    if read <= quoted:
        return f"Прочитано страниц: {quoted} (главная + {max(quoted - 1, 0)} внутренних)."
    return (
        f"Прочитано страниц: {read} (главная + {read - 1} внутренних), "
        f"в текст анализа вошло {quoted}: остальные повторяли уже прочитанное, "
        "но участвовали в проверках разметки и в поиске фактов."
    )


def build_crawl_checks(crawl: Dict) -> Dict:
    """Таблица глубины обхода: что прочитано, что пропущено и почему."""
    if not crawl:
        return {"columns": [], "rows": []}
    columns = ["Проверка", "Что посчитано кодом", "Вывод"]
    rows: List[List[str]] = []

    def row(check: str, seen: str, verdict: str, why: str = "") -> None:
        rows.append([check, seen, f"{verdict} — {why}" if why else verdict])

    pages = int(crawl.get("pages") or 0)
    limit = int(crawl.get("limit") or MAX_CRAWL_PAGES)
    refused = crawl.get("refused") or {}
    quoted = int(crawl.get("text_pages") or 0)
    cell = f"прочитано страниц: {pages} из {limit}"
    if quoted and quoted < pages:
        cell += f", в текст анализа вошло {quoted}"
    cell += (
        f", разделов: {len(crawl.get('sections') or [])}, "
        f"глубина вложенности: {int(crawl.get('depth') or 0)}"
    )
    row(
        "Глубина обхода",
        cell,
        OK if pages >= 3 else CHECK,
        "выводы аудита опираются на внутренние страницы, а не только на главную"
        if pages >= 3 else "прочитано слишком мало, чтобы судить о всём сайте",
    )
    paged = int(crawl.get("paged") or 0)
    if paged:
        row("Пагинация листинга", f"страниц списков прочитано: {paged}", OK,
            "цены на второй и третьей странице могли отличаться от первой")
    stopped = crawl.get("stopped") or ""
    pending = int(crawl.get("pending") or 0)
    if stopped or pending or refused.get("budget") or refused.get("time"):
        seen = stopped or "достигнут потолок страниц обхода"
        if pending:
            seen += f", ссылок осталось непроверенными: {pending}"
        row("Полнота обхода", seen, CHECK, "часть ссылок осталась непроверенной")
    duplicates = crawl.get("duplicates") or []
    row(
        "Дубликаты содержания",
        f"страниц с тем же текстом: {len(duplicates)}" if duplicates else "дублей не найдено",
        CHECK if duplicates else OK,
        duplicates[0]["url"] + " совпадает с " + duplicates[0]["same_as"] if duplicates else
        "разные адреса несут разное содержание",
    )
    failures = crawl.get("failures") or []
    if failures:
        row("Страницы не открылись",
            "; ".join(item.get("url", "") for item in failures[:3]),
            BAD,
            "ссылка есть в меню, а страницы нет — это потерянные заявки")
    if refused.get("thin"):
        row("Страницы без текста", f"служебных или почти пустых: {refused['thin']}", CHECK,
            "такие адреса отдают шаблон вместо содержания — проверить руками")
    seconds = float(crawl.get("seconds") or 0)
    row("Время обхода", f"{seconds} с из {crawl.get('budget') or 0} с", OK,
        "остальное время аудита уходит на проверки и разбор")
    return {"columns": columns, "rows": rows}


def crawl_gaps(crawl: Dict) -> List[str]:
    """Чего обход не увидел — честно, чтобы модель не утверждала лишнего."""
    if not crawl:
        return []
    gaps: List[str] = []
    pages = int(crawl.get("pages") or 0)
    if pages:
        pending = int(crawl.get("pending") or 0)
        if crawl.get("stopped"):
            detail = f" {crawl['stopped']}"
            if pending:
                detail += f", непроверенных ссылок осталось: {pending}"
            gaps.append(
                f"Сайт обойдён не полностью ({detail.strip()}): "
                "пропущенные разделы могут содержать другие цены и условия"
            )
        if int(crawl.get("refused", {}).get("section", 0)):
            gaps.append(
                "Из некоторых разделов прочитаны не все страницы — "
                "полный ассортимент по сайту не известен"
            )
    return gaps


def render_crawl(crawl: Dict) -> str:
    """Короткий блок для промпта: модель знает потолок своих выводов."""
    if not crawl:
        return ""
    duplicates = crawl.get("duplicates") or []
    failures = crawl.get("failures") or []
    quoted = int(crawl.get("text_pages") or 0)
    pages = int(crawl.get("pages") or 0)
    lines = [
        "## Глубина обхода (посчитано кодом)",
        f"Прочитано страниц: {pages} из {int(crawl.get('limit') or MAX_CRAWL_PAGES)}; "
        f"разделы: {', '.join(crawl.get('sections') or []) or 'не определены'}",
        f"Дубликатов содержания: {len(duplicates)}; не открылось страниц: {len(failures)}",
    ]
    if quoted and quoted < pages:
        lines.append(
            f"Текст для разбора дан по {quoted} страницам из {pages}: остальные прочитаны, "
            "но повторили уже изложенное. Выводов о содержании прочитанных, но не процитированных "
            "страниц не делайте — ссылайтесь на источники."
        )
    if duplicates:
        lines.append(
            "Один и тот же текст под разными адресами: "
            + "; ".join(f"{item.get('url')} = {item.get('same_as')}" for item in duplicates[:3])
        )
    if failures:
        lines.append("Не открылись: " + "; ".join(item.get("url", "") for item in failures[:5]))
    if crawl.get("stopped"):
        lines.append(f"Обход остановлен: {crawl['stopped']} — ниже по списку ссылки не проверены")
    return "\n".join(lines)
