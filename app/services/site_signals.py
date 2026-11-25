"""Проверки, которые аудитор делает руками по разметке, без сторонних API.

Считает код по тем же страницам, что уже скачал обход: ни одного лишнего
запроса и ни одного числа, которое модель могла бы выдумать. «Не найдено» —
тоже ответ, и в отчёте он обязан быть: отсутствие счётчика меняет весь разговор
о конверсии сильнее, чем красивый абзац про воронку.
"""

import re
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

# Счётчики и пиксели ищем и по адресу скрипта, и по вызову: ставят их и вручную,
# и шаблоном, и через консолидатор тегов.
ANALYTICS_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "Яндекс Метрика": (r"mc\.yandex\.ru/metrika", r"\bym\(\s*['\"]count"),
    "Google Analytics": (
        r"google-analytics\.com/(ga|analytics)\.js",
        r"gtag\.js",
        r"\bga\(\s*['\"]create",
    ),
    "Google Tag Manager": (r"googletagmanager\.com/gtm\.js",),
    "Пиксель VK": (r"vk\.com/rtrg", r"top\.mail\.ru/js/topdraw"),
    "Пиксель Facebook": (r"connect\.facebook\.net/[a-z_.]+/fbevents\.js",),
    "Сквозная аналитика (Roistat/Calltouch)": (r"scripts\.roistat\.com", r"calltouch\.ru"),
}

# Контакт, с которого клиенту удобно начать разговор: список мессенджеров в
# разметке — это про фактические пути заявки, а не про дизайн.
MESSENGER_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "WhatsApp": (r"wa\.me/", r"api\.whatsapp\.com"),
    "Telegram": (r"t\.me/", r"telegram\.me/"),
    "Viber": (r"viber://", r"clients\.viber\.com"),
}

OK = "норма"
CHECK = "проверить"
MISSING = "не найдено"

# Сигналы, которые копят по страницам. Числа складываются, наборы объединяются.
COUNTER_KEYS = (
    "pages",
    "titles_missing",
    "descriptions_missing",
    "h1_missing",
    "h1_multiple",
    "viewports_missing",
    "canonical_missing",
    "og_pages",
    "jsonld_blocks",
    "forms",
    "inputs",
    "tel_links",
    "mailto_links",
    "images",
    "images_without_alt",
)

NO_ANALYTICS_GAP = (
    "Данных о трафике и конверсии нет: счётчики на прочитанных страницах "
    "не найдены — все цифры в отчёте остаются допущениями"
)
NO_FORMS_GAP = (
    "Форм заявок на прочитанных страницах нет — считать конверсию будет не по чему"
)


def empty_signals() -> Dict:
    return {key: 0 for key in COUNTER_KEYS} | {"analytics": {}, "messengers": {}}


def scan_page(html: str) -> Dict:
    """Что видно на одной странице, посчитанное по разметке."""
    raw = str(html or "")
    signals = empty_signals()
    if not raw.strip():
        # Пустой ответ — не прочитанная страница: «форм не найдено» про неё
        # звучало бы как вывод аудита, хотя смотреть было не на что.
        return signals
    signals["pages"] = 1

    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:  # noqa: BLE001 - разбор одной страницы не должен ронять аудит
        return signals

    def flag(matches: Tuple[str, ...]) -> bool:
        return any(re.search(pattern, raw, re.I) for pattern in matches)

    for name, patterns in ANALYTICS_PATTERNS.items():
        if flag(patterns):
            signals["analytics"][name] = 1
    for name, patterns in MESSENGER_PATTERNS.items():
        if flag(patterns):
            signals["messengers"][name] = 1

    title = soup.title.get_text(strip=True) if soup.title else ""
    if not title.strip():
        signals["titles_missing"] = 1

    meta = soup.find("meta", attrs={"name": "description"})
    if not (meta and (meta.get("content") or "").strip()):
        signals["descriptions_missing"] = 1

    h1_count = len(soup.find_all("h1"))
    if h1_count == 0:
        signals["h1_missing"] = 1
    elif h1_count > 1:
        signals["h1_multiple"] = 1

    if not soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}):
        signals["viewports_missing"] = 1
    if not soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)}):
        signals["canonical_missing"] = 1

    # og: считаем по количеству тегов, а не по названию страницы: набор у всех
    # разный, а пустой head без них — это «в соцсети ссылка уйдёт ссылкой-обрубком».
    if any(
        (tag.get("property") or "").lower().startswith("og:")
        for tag in soup.find_all("meta")
    ):
        signals["og_pages"] = 1
    signals["jsonld_blocks"] = len(soup.find_all("script", type=re.compile("ld\\+json", re.I)))

    signals["forms"] = len(soup.find_all("form"))
    signals["inputs"] = len(soup.find_all(["input", "textarea"]))
    signals["tel_links"] = len(soup.find_all("a", href=re.compile(r"^tel:", re.I)))
    signals["mailto_links"] = len(soup.find_all("a", href=re.compile(r"^mailto:", re.I)))

    images = soup.find_all("img")
    signals["images"] = len(images)
    signals["images_without_alt"] = sum(
        1 for image in images if not (image.get("alt") or "").strip()
    )
    return signals


def merge_signals(target: Dict, addition: Dict) -> Dict:
    """Копит проверки по страницам: числа складываются, счётчики — тоже.

    Счётчик считают по числу страниц, где он найден: «Метрика стоит» и «Метрика
    стоит на главной, а в каталоге её нет» — это разные выводы для клиента.
    """
    target = target or empty_signals()
    addition = addition or {}
    for key in COUNTER_KEYS:
        target[key] = int(target.get(key, 0)) + int(addition.get(key, 0))
    for key in ("analytics", "messengers"):
        merged = dict(target.get(key) or {})
        for name, value in (addition.get(key) or {}).items():
            merged[name] = int(merged.get(name, 0)) + int(value)
        target[key] = merged
    return target


def _missing(count: int, pages: int) -> str:
    """«без title: 2 из 7» — читатель должен видеть, чего не хватает, а не догадку."""
    return f"{int(count)} из {pages}" if pages else "нет данных"


def _found_names(values: Dict, pages: int, per_page: bool = False) -> str:
    """Список найденного с охватом там, где половинчатый результат важнее «есть»."""
    parts = []
    for name, count in sorted((values or {}).items()):
        if not count:
            continue
        parts.append(f"{name} — на {count} из {pages}" if per_page and count < pages else name)
    return ", ".join(parts)


def build_site_checks(signals: Dict) -> Dict:
    """Таблица «проверка — что видно — вывод». Строки генерирует код."""
    signals = signals or empty_signals()
    pages = int(signals.get("pages", 0))
    rows: List[List[str]] = []
    table = {"columns": ["Проверка", "Что видно на страницах", "Вывод"], "rows": rows}

    def row(check: str, seen: str, verdict: str, why: str) -> None:
        rows.append([check, seen, f"{verdict} — {why}" if why else verdict])

    if not pages:
        # Читать было нечего: любая строка ниже была бы утверждением о сайте,
        # которого код не видел.
        return table

    analytics = _found_names(signals.get("analytics"), pages, per_page=True)
    if analytics:
        # Консолидатор тегов прячет содержимое: по HTML нельзя утверждать,
        # что внутри контейнера есть нужные счётчики.
        note = (
            "какие именно события собираются — видно только в кабинете"
            if "Tag Manager" in analytics
            else "трафик измеряется, конверсию можно считать"
        )
        row("Счётчики и пиксели", "найдены: " + analytics, OK, note)
    else:
        row("Счётчики и пиксели", "ни одного в разметке", MISSING, "измерять конверсию нечем")

    row(
        "Заголовок страницы (title)",
        "без title: " + _missing(int(signals.get("titles_missing", 0)), pages),
        OK if pages and not signals.get("titles_missing") else CHECK,
        "по title поиск и объявления понимают, о чём страница",
    )
    row(
        "Описание (meta description)",
        "без description: " + _missing(int(signals.get("descriptions_missing", 0)), pages),
        OK if pages and not signals.get("descriptions_missing") else CHECK,
        "без него сниппет собирает случайную строку со страницы",
    )

    h1_missing = int(signals.get("h1_missing", 0))
    h1_multiple = int(signals.get("h1_multiple", 0))
    h1_seen = f"без H1: {h1_missing}, с двумя и больше: {h1_multiple}"
    row(
        "H1 на странице",
        h1_seen,
        OK if not (h1_missing or h1_multiple) else CHECK,
        "H1 — первое, что читает человек с рекламы",
    )

    row(
        "Мобильная вёрстка (viewport)",
        "без viewport: " + _missing(int(signals.get("viewports_missing", 0)), pages),
        OK if pages and not signals.get("viewports_missing") else CHECK,
        "с телефона идёт большая часть показов рекламы",
    )
    row(
        "Canonical",
        "без canonical: " + _missing(int(signals.get("canonical_missing", 0)), pages),
        OK if pages and not signals.get("canonical_missing") else CHECK,
        "без него индекс дублирует страницы и размывает вес",
    )
    og = int(signals.get("og_pages", 0))
    row(
        "OG-теги для ссылок в соцсетях",
        f"og-теги: {og} из {pages}" if pages else "нет данных",
        OK if og else CHECK,
        "по ним пост ссылки выглядит карточкой, а не обрубком",
    )

    blocks = int(signals.get("jsonld_blocks", 0))
    row(
        "Микроразметка (JSON-LD)",
        f"{blocks} блоков" if blocks else "не найдена",
        OK if blocks else CHECK,
        "даёт расширенный сниппет: цена, товар, организация в поиске",
    )

    forms = int(signals.get("forms", 0))
    row(
        "Формы заявок",
        f"{forms} форм, полей: {int(signals.get('inputs', 0))}" if forms else "ни одной формы",
        OK if forms else MISSING,
        "куда направить трафик с рекламы" if forms else "заявку принимать некуда, кроме звонка",
    )

    tel = int(signals.get("tel_links", 0))
    row(
        "Телефон кликом (tel:)",
        f"{tel} ссылок" if tel else "не найден",
        OK if tel else CHECK,
        "с телефона набор идёт в один тап",
    )
    mailto = int(signals.get("mailto_links", 0))
    row(
        "Почта кликом (mailto:)",
        f"{mailto} ссылок" if mailto else "не найдена",
        OK if mailto else CHECK,
        "для запросов с прайсом и ТЗ",
    )

    messengers = sorted(
        name for name, value in (signals.get("messengers") or {}).items() if value
    )
    row(
        "Мессенджеры в контактах",
        "найдены: " + ", ".join(messengers) if messengers else "не найдены",
        OK if messengers else CHECK,
        "короткий путь для того, кто ещё не готов к звонку",
    )

    images = int(signals.get("images", 0))
    no_alt = int(signals.get("images_without_alt", 0))
    share = round(100 * no_alt / images) if images else 0
    row(
        "Картинки без alt",
        f"{no_alt} из {images} ({share}%)" if images else "картинок нет",
        OK if images and share <= 25 else CHECK,
        "alt читают поиск и голосовой браузер",
    )

    return table


def signal_gaps(signals: Dict) -> List[str]:
    """Что из-за этих проверок нельзя узнать из данных сайта."""
    signals = signals or empty_signals()
    if not int(signals.get("pages", 0)):
        # Ни одной страницы не прочитано — утверждать «счётчиков нет» нельзя.
        return []
    gaps: List[str] = []
    if not any(signals.get("analytics") or {}):
        gaps.append(NO_ANALYTICS_GAP)
    if not int(signals.get("forms", 0)):
        gaps.append(NO_FORMS_GAP)
    return gaps


def render_signals(signals: Dict) -> str:
    """Компактный блок для промпта: модель обязана опираться на него, а не угадывать."""
    signals = signals or empty_signals()
    analytics = sorted(
        name for name, value in (signals.get("analytics") or {}).items() if value
    )
    messengers = sorted(
        name for name, value in (signals.get("messengers") or {}).items() if value
    )
    pages = int(signals.get("pages", 0))

    def missing(key: str) -> str:
        count = int(signals.get(key, 0))
        return f"{count} из {pages} страниц" if count else "нет"

    lines = [
        "## Проверки по разметке (посчитано кодом, не догадка)",
        f"Счётчики: {', '.join(analytics) if analytics else 'не найдены'}",
        f"Страниц без title: {missing('titles_missing')}; без description: "
        f"{missing('descriptions_missing')}; без H1: {missing('h1_missing')}; "
        f"с двумя H1: {missing('h1_multiple')}",
        f"Без viewport: {missing('viewports_missing')}; без canonical: "
        f"{missing('canonical_missing')}; блоков JSON-LD: {int(signals.get('jsonld_blocks', 0))}",
        f"Форм: {int(signals.get('forms', 0))}, полей: {int(signals.get('inputs', 0))}; "
        f"ссылок tel: {int(signals.get('tel_links', 0))}, mailto: {int(signals.get('mailto_links', 0))}",
        f"Мессенджеры: {', '.join(messengers) if messengers else 'не найдены'}; "
        f"картинок без alt: {int(signals.get('images_without_alt', 0))} из {int(signals.get('images', 0))}",
    ]
    return "\n".join(lines)
