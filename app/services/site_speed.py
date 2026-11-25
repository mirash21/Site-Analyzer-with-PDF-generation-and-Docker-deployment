"""Скорость и мобильность сайта: измеряем сами, PageSpeed добавляем если смог.

Бесплатный PageSpeed Insights бесплатен ровно до той минуты, когда кто-то другой
уже выбрал дневную квоту общего анонимного проекта: Google отвечает «429», и
половина раздела повисла бы на «неизвестно». Строить на этом отчёт нельзя —
клиент платит временем анализа за чужой лимит.

Поэтому раздел собран из двух независимых половин. Первая работает всегда:
один отдельный запрос к главной даёт время до первого байта, вес, сжатие,
протокол и редирект; горстка запросов к ресурсам даёт их вес и политику кэша;
разбор разметки не стоит ни одного запроса и объясняет, что именно тормозит
загрузку — блокирующие скрипты, чужие домены, картинки без размеров, viewport.
Вторая половина — цифры PSI, если тест всё-таки ответил. Они переписываются как
есть, с указанием, лаборатория это или реальные пользователи.

Ни одной выдуманной цифры: неизмеренное помечено «не проверено» с причиной, а не
правдоподобным значением. Сети в модуле нет — анализатор передаёт функции
запроса, и вся логика остаётся проверяемой без интернета.
"""

import re
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

# Ресурсов пробуем мало: каждый запрос стоит секунду, а аудит ждут минуту.
# Шести адресов хватает на блокирующие скрипты, стили и картинку первого экрана.
MAX_ASSET_PROBES = 6
ASSET_BUDGET_SECONDS = 15.0

# PSI ждут недолго: без ключа он чаще отказывает, чем считает тест.
PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_TIMEOUT = 25

# Выводы общие со всеми кодовыми проверками: клиент читает таблицы подряд.
OK = "норма"
CHECK = "проверить"
BAD = "ошибка"
UNKNOWN = "не проверено"

# Пороги взяты из публичных критериев Lighthouse и округлены: читателю важна не
# сотня миллисекунд, а ответ на вопрос «медленно это или нет».
TTFB_OK_MS = 300
TTFB_BAD_MS = 600
PAGE_OK_BYTES = 250_000
DOM_OK_NODES = 800
DOM_BAD_NODES = 1_500
THIRD_PARTY_OK = 3
THIRD_PARTY_BAD = 8
# Ресурс в килобайте сжатия не требует: «без сжатия» про него — ложная находка.
COMPRESS_MIN_BYTES = 1024

# Лабораторные метрики PSI: id аудита → своё короткое имя и границы норма/плохо.
PSI_AUDITS = {
    "server-response-time": "TTFB",
    "first-contentful-paint": "FCP",
    "largest-contentful-paint": "LCP",
    "speed-index": "SI",
    "total-blocking-time": "TBT",
    "cumulative-layout-shift": "CLS",
    "interactive": "TTI",
}
LAB_LIMITS = {
    "TTFB": (TTFB_OK_MS, TTFB_BAD_MS),
    "FCP": (1800, 3000),
    "LCP": (2500, 4000),
    "SI": (3400, 5800),
    "TBT": (200, 600),
    "CLS": (0.1, 0.25),
    "TTI": (3800, 7300),
}
LAB_NAMES = {
    "TTFB": "ответ сервера",
    "FCP": "первая отрисовка",
    "LCP": "самый долгий элемент",
    "SI": "индекс скорости",
    "TBT": "блокировка потока",
    "CLS": "сдвиг макета",
    "TTI": "готовность к действию",
}

# Полевые данные — то же самое, но из реальных посещений. INP в лаборатории
# не измеряется вообще, поэтому его берём только здесь.
FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "LCP",
    "INTERACTION_TO_NEXT_PAINT": "INP",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "CLS",
}
GRADE_TEXT = {"fast": "быстро", "average": "средне", "slow": "медленно"}
GRADE_VERDICT = {"fast": OK, "average": CHECK, "slow": BAD}

PSI_STATE_TEXT = {
    "ok": "тест ответил",
    "quota": "бесплатный запрос без ключа упёрся в дневную квоту Google",
    "blocked": "запрос отклонён — проверьте ключ PAGESPEED_API_KEY",
    "error": "тест вернул ошибку",
    "foreign": "ответ не похож на отчёт PageSpeed",
    "unreachable": "тест не ответил",
    "skipped": "тест не запускался",
}

VERDICT_RANK = {OK: 0, CHECK: 1, BAD: 2}

# Версию протокола отдаёт urllib3 числом: от неё зависит, грузится ли статика
# одним соединением или двадцатью параллельными.
HTTP_VERSIONS = {10: "HTTP/1.0", 11: "HTTP/1.1", 20: "HTTP/2", 30: "HTTP/3"}

VIEWPORT_LOCK = re.compile(r"(user-scalable\s*=\s*no|maximum-scale\s*=\s*1(\.0)?\b)", re.I)
FONT_FACE = re.compile(r"@font-face", re.I)
MODERN_IMAGE = re.compile(r"\.(webp|avif)(\?|#|$)", re.I)
MAX_AGE = re.compile(r"(?:s-)?max-age\s*=\s*(\d+)", re.I)
DIGITS = re.compile(r"\d+")


def content_length(value) -> int:
    """Число из заголовка «Content-Length: 12 345»: пустое и чужое даёт ноль."""
    match = DIGITS.search(str(value or ""))
    return int(match.group()) if match else 0


def empty_speed() -> Dict:
    """Пустой результат: ни один замер не сделан, ни одна цифра не выдумана."""
    return {
        "page": {"measured": False, "headers": {}},
        "markup": {"parsed": 0},
        "assets": {"checked": 0, "found": 0, "bytes": 0, "compressed": 0, "uncompressed": 0,
                   "uncached": 0, "unreachable": 0, "weighed": 0, "size_unknown": 0,
                   "weightless": 0, "dead": [], "items": [], "stopped": ""},
        "psi": {"state": "skipped", "score": 0, "lab": {}, "field": {}},
    }


def _kb(size) -> str:
    value = int(size or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} МБ"
    if value >= 1000:
        return f"{value // 1000} КБ"
    return f"{value} Б"


def _value(key: str, value) -> str:
    """CLS — доля, остальное — время: «0.12» и «3.4 с» читаются вместе."""
    if key == "CLS":
        return f"{float(value):.2f}"
    return f"{float(value) / 1000:.1f} с" if float(value) >= 1000 else f"{int(float(value))} мс"


def _grade(key: str, value: float) -> str:
    limits = LAB_LIMITS.get(key)
    if not limits:
        return UNKNOWN
    return OK if value <= limits[0] else CHECK if value <= limits[1] else BAD


def _worst(grades: List[str]) -> str:
    """Итог по метрикам — худшая из них: быстрый сервер не лечит медленный экран."""
    known = [grade for grade in grades if grade in VERDICT_RANK]
    return max(known, key=lambda grade: VERDICT_RANK[grade]) if known else UNKNOWN


def _absolute(base: str, href: str) -> str:
    return urljoin(base, str(href or "").strip())


def normalize_page(probe: Dict) -> Dict:
    """Ответ замеренного запроса к полям отчёта: чужой формы здесь быть не должно."""
    probe = probe or {}
    headers = {}
    for key, value in (probe.get("headers") or {}).items():
        headers[str(key).lower()] = str(value or "")
    content_type = (headers.get("content-type") or "").split(";")[0].strip()
    measured = bool(probe.get("status")) and bool(
        probe.get("ttfb_ms") or probe.get("content_bytes")
    )
    return {
        "measured": measured,
        "status": int(probe.get("status") or 0),
        "ttfb_ms": int(probe.get("ttfb_ms") or 0),
        "total_ms": int(probe.get("total_ms") or 0),
        "content_bytes": int(probe.get("content_bytes") or 0),
        # 0 здесь означает «сервер не назвал вес» (отдача кусками), а не «0 байт».
        "wire_bytes": int(probe.get("wire_bytes") or 0),
        "encoding": (headers.get("content-encoding") or "").lower(),
        "http_version": str(probe.get("http_version") or ""),
        "server": (headers.get("server") or "")[:40],
        "redirects": int(probe.get("redirects") or 0),
        "cache_control": headers.get("cache-control") or "",
        "content_type": content_type,
        "charset": "utf-8" in (headers.get("content-type") or "").lower(),
        "final_path": urlparse(probe.get("final_url") or "").path or "",
    }


def parse_markup(html: str, origin: str = "") -> Dict:
    """Что стоит в разметке и тормозит загрузку — посчитано без единого запроса.

    Часть дефектов скорости не видна ни в каком тайминге: скрипт без defer,
    картинка без высоты, четвёртый чужой виджет в шапке. Их считает разбор,
    и считает по той же главной странице, которую уже прочитал обход.
    """
    out = {
        "parsed": 0, "scripts": 0, "inline_scripts": 0, "blocking": 0, "deferred": 0,
        "styles": 0, "preconnect": 0, "preload": 0, "font_preload": 0, "font_faces": 0,
        "third_party": 0, "third_party_hosts": [], "iframes": 0, "iframe_hosts": [],
        "images": 0, "images_no_dims": 0, "images_lazy": 0, "images_srcset": 0,
        "images_modern": 0, "inline_script_bytes": 0, "inline_style_bytes": 0,
        "dom_nodes": 0, "viewport": False, "zoom_locked": False,
        "blocking_urls": [], "script_urls": [], "style_urls": [], "image_urls": [],
    }
    raw = str(html or "")
    if not raw.strip():
        return out
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:  # noqa: BLE001 - разбор одной страницы не должен ронять раздел
        return out
    out["parsed"] = 1

    host = (urlparse(origin).netloc or "").lower()
    base = origin.rstrip("/") + "/"

    def external(url: str) -> bool:
        netloc = (urlparse(url).netloc or "").lower()
        return bool(netloc) and netloc != host and not netloc.endswith("." + host)

    def deferred(tag) -> bool:
        attrs = tag.attrs or {}
        return "async" in attrs or "defer" in attrs

    scripts = soup.find_all("script")
    with_src = [tag for tag in scripts if (tag.get("src") or "").strip()]
    without_src = [tag for tag in scripts if not (tag.get("src") or "").strip()]
    head = soup.find("head")
    in_head = head.find_all("script") if head is not None else []
    blocking = [
        tag for tag in in_head
        if (tag.get("src") or "").strip() and not deferred(tag)
    ]

    links = soup.find_all("link")

    def rel_of(tag) -> str:
        value = tag.get("rel") or []
        return " ".join(value if isinstance(value, list) else [str(value)]).lower()

    styles = [tag for tag in links if "stylesheet" in rel_of(tag)]
    preload = [tag for tag in links if "preload" in rel_of(tag)]
    prefetch = sum(
        1 for tag in links if "preconnect" in rel_of(tag) or "dns-prefetch" in rel_of(tag)
    )

    script_urls = [_absolute(base, tag.get("src")) for tag in with_src]
    style_urls = [_absolute(base, tag.get("href")) for tag in styles]
    frame_urls = [_absolute(base, tag.get("src")) for tag in soup.find_all("iframe")]
    foreign = [url for url in [*script_urls, *style_urls, *frame_urls] if external(url)]

    images = soup.find_all("img")

    def netloc_of(url: str) -> str:
        return (urlparse(url).netloc or "").lower()

    def src_of(tag) -> str:
        return str(tag.get("src") or "").strip()

    def no_dims(tag) -> bool:
        return not (str(tag.get("width") or "").strip() and str(tag.get("height") or "").strip())

    def adaptive(tag) -> bool:
        return bool((tag.get("srcset") or tag.get("data-srcset") or "").strip())

    out.update({
        "scripts": len(with_src),
        "inline_scripts": len(without_src),
        "blocking": len(blocking),
        "blocking_urls": [_absolute(base, src_of(tag)) for tag in blocking][:MAX_ASSET_PROBES],
        "deferred": sum(1 for tag in with_src if deferred(tag)),
        "styles": len(styles),
        "preconnect": prefetch,
        "preload": len(preload),
        "font_preload": sum(1 for tag in preload if "font" in str(tag.get("as") or "").lower()),
        "font_faces": len(FONT_FACE.findall(raw)),
        "third_party": len(foreign),
        "third_party_hosts": sorted({netloc_of(url) for url in foreign}),
        "iframes": len(frame_urls),
        "iframe_hosts": sorted({netloc_of(url) for url in frame_urls}),
        "inline_script_bytes": sum(len(tag.get_text() or "") for tag in without_src),
        "inline_style_bytes": sum(len(tag.get_text() or "") for tag in soup.find_all("style")),
        "dom_nodes": len(soup.find_all()),
        "script_urls": script_urls[: MAX_ASSET_PROBES * 2],
        "style_urls": style_urls[:MAX_ASSET_PROBES],
        "image_urls": [_absolute(base, src_of(tag)) for tag in images if src_of(tag)][:4],
        "images": len(images),
        "images_no_dims": sum(1 for tag in images if no_dims(tag)),
        "images_lazy": sum(1 for tag in images if (tag.get("loading") or "").lower() == "lazy"),
        "images_srcset": sum(1 for tag in images if adaptive(tag)),
        "images_modern": sum(1 for tag in images if MODERN_IMAGE.search(src_of(tag))),
    })

    meta = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    content = str(meta.get("content") or "") if meta is not None else ""
    out["viewport"] = bool(content.strip())
    out["zoom_locked"] = bool(VIEWPORT_LOCK.search(content))
    return out


def pick_assets(markup: Dict, origin: str = "", limit: int = MAX_ASSET_PROBES) -> List[str]:
    """Горстка адресов, чей вес решают.

    Свои адреса идут первыми: их клиент может сжать, закэшировать и перенести
    сам, а чужой скрипт он умеет только выключить — пробивать его вес дороже,
    но полезнее остатка бюджета. Внутри своих держится порядок разметки:
    блокирующий скрипт важнее картинки из подвала.
    """
    markup = markup or {}
    host = (urlparse(origin).netloc or "").lower()
    own: List[str] = []
    foreign: List[str] = []
    for group in (
        markup.get("blocking_urls") or [],
        markup.get("style_urls") or [],
        markup.get("script_urls") or [],
        markup.get("image_urls") or [],
    ):
        for url in group:
            if not url or not url.lower().startswith("http") or url in own or url in foreign:
                continue
            if (urlparse(url).netloc or "").lower() == host:
                own.append(url)
            else:
                foreign.append(url)
    return (own + foreign)[: max(0, int(limit))]


def _cache_state(cache_control: str, expires: str = "") -> str:
    """Короткий ответ про кэш ресурса: годен, коротко, запрещён, не задан."""
    cc = (cache_control or "").lower()
    if "no-store" in cc or "no-cache" in cc:
        return "forbidden"
    match = MAX_AGE.search(cc)
    if match:
        seconds = int(match.group(1))
        return "cached" if seconds >= 60 else "short" if seconds > 0 else "forbidden"
    value = (expires or "").strip()
    if value and value != "0" and "1970" not in value:
        return "cached"
    return "none"


def probe_assets(urls: List[str], fetch: Callable, budget: float = ASSET_BUDGET_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> Dict:
    """Заголовки ресурсов: вес, сжатие и кэш видно только оттуда.

    Тела не качают — Content-Length достаточно, чтобы назвать вес скрипта,
    а гонять мегабайты картинок ради строчки отчёта аудит не вправе.

    «404» и «сервер молчит» считаются раздельно: первое — дефект сайта, второе —
    наша неудача, и в отчёте они значат разное. Тело не качаем, поэтому ресурс,
    отданный кусками без Content-Length, остаётся с неизвестным весом: это
    считаем отдельно и не выдаём ноль за измеренное число байт.
    """
    out = {"checked": 0, "found": len(urls or []), "bytes": 0, "compressed": 0,
           "uncompressed": 0, "uncached": 0, "unreachable": 0, "weighed": 0,
           "size_unknown": 0, "weightless": 0, "dead": [], "items": [], "stopped": ""}
    started = clock()
    for url in urls or []:
        if clock() - started > budget:
            out["stopped"] = "закончился бюджет времени на пробу ресурсов"
            break
        head = fetch(url) or {}
        status = int(head.get("status") or 0)
        out["checked"] += 1
        if not status:
            out["unreachable"] += 1
            continue
        if status >= 400:
            out["dead"].append({"url": url, "status": status})
            continue
        size = int(head.get("bytes") or 0)
        encoding = (head.get("encoding") or "").lower()
        cache = _cache_state(head.get("cache_control") or "", head.get("expires") or "")
        out["bytes"] += size
        out["weighed"] += 1 if size else 0
        out["size_unknown"] += 0 if size else 1
        out["compressed"] += 1 if encoding else 0
        out["uncompressed"] += 1 if (not encoding and size > COMPRESS_MIN_BYTES) else 0
        out["weightless"] += 1 if (not encoding and not size) else 0
        out["uncached"] += 0 if cache == "cached" else 1
        out["items"].append({
            "url": url,
            "path": urlparse(url).path or url,
            "bytes": size,
            "encoding": encoding,
            "cache": cache,
            "type": (head.get("content_type") or "").split("/")[-1][:12],
        })
    if not out["stopped"] and out["found"] > out["checked"]:
        out["stopped"] = f"проверено {out['checked']} ресурсов из {out['found']}"
    return out


def psi_state(status: int, body: Dict) -> str:
    """Состояние ответа PSI. «Квоты нет» и «тест не ответил» — разные выводы:
    в первом случае стоит подождать суток, во втором — искать причину у себя."""
    body = body or {}
    if not status:
        return "unreachable"
    if status == 429:
        return "quota"
    if status in (401, 403):
        return "blocked"
    if status >= 400:
        return "error"
    error = body.get("error") or {}
    if error:
        code = int(error.get("code") or 0)
        if code == 429:
            return "quota"
        return "blocked" if code in (401, 403) else "error"
    if not (body.get("lighthouseResult") or body.get("loadingExperience")):
        # Google отвечает 200 и на бессмысленный запрос: пустой конверт — это не
        # отчёт, и «балл 0» из него делать нельзя.
        return "foreign"
    result = body.get("lighthouseResult") or {}
    experience = body.get("loadingExperience") or {}
    if not (result.get("audits") or result.get("categories") or experience.get("metrics")):
        return "foreign"
    return "ok"


def psi_facts(probe: Dict) -> Dict:
    """Цифры PSI как есть, с названием источника. Балл не округляем в пользу клиента."""
    probe = probe or {}
    status = int(probe.get("status") or 0)
    body = probe.get("body") if isinstance(probe.get("body"), dict) else {}
    out = {"state": psi_state(status, body), "status": status, "score": 0,
           "lab": {}, "field": {}, "field_rating": "", "strategy": ""}
    if out["state"] != "ok":
        return out

    result = body.get("lighthouseResult") or {}
    config = result.get("configSettings") or {}
    out["strategy"] = str(config.get("formFactor") or "").lower()
    performance = (result.get("categories") or {}).get("performance") or {}
    score = performance.get("score")
    if score is not None:
        out["score"] = int(round(float(score) * 100))

    audits = result.get("audits") or {}
    for audit, key in PSI_AUDITS.items():
        item = audits.get(audit) or {}
        value = item.get("numericValue")
        if value is None:
            continue
        number = float(value)
        out["lab"][key] = round(number, 4) if key == "CLS" else int(round(number))

    experience = body.get("loadingExperience") or {}
    metrics = experience.get("metrics") or {}
    out["field_rating"] = str(experience.get("overall_category") or "").lower()
    for metric, key in FIELD_METRICS.items():
        item = metrics.get(metric) or {}
        percentile = item.get("percentile")
        if percentile is None:
            continue
        number = float(percentile)
        out["field"][key] = {
            "value": round(number / 100, 4) if key == "CLS" else int(round(number)),
            "grade": str(item.get("category") or "").lower(),
        }
    return out


def _lab_line(lab: Dict) -> str:
    return "; ".join(
        f"{key} — {_value(key, value)} ({LAB_NAMES.get(key, key)})"
        for key, value in lab.items()
        if key in LAB_NAMES
    )


def _field_line(field: Dict) -> str:
    parts = []
    for key, item in (field or {}).items():
        value = item.get("value") if isinstance(item, dict) else item
        grade = item.get("grade") if isinstance(item, dict) else ""
        unit = _value("CLS" if key == "CLS" else key, value or 0)
        parts.append(f"{key} — {unit} ({GRADE_TEXT.get(grade, 'оценка нет')})")
    return "; ".join(parts)


def _share(part: int, total: int) -> str:
    return f"{int(part)} из {int(total)}" if total else "нет данных"


def _verdict_rows(speed: Dict, rows: List[List[str]]) -> None:
    page = speed.get("page") or {}
    markup = speed.get("markup") or {}
    assets = speed.get("assets") or {}
    psi = speed.get("psi") or {}

    def row(check: str, seen: str, verdict: str, why: str) -> None:
        rows.append([check, seen, f"{verdict} — {why}" if why else verdict])

    if page.get("measured"):
        ttfb = int(page.get("ttfb_ms") or 0)
        row(
            "Ответ сервера",
            f"{ttfb} мс до первого байта, страница целиком за {int(page.get('total_ms') or 0)} мс",
            _grade("TTFB", ttfb),
            "пока сервер думает, заявитель уже открыл соседнюю вкладку" if ttfb > TTFB_OK_MS
            else "сервер отвечает быстро, дальше тормозит сама страница",
        )
        size = int(page.get("content_bytes") or 0)
        wire = int(page.get("wire_bytes") or 0)
        encoding = page.get("encoding") or ""
        # Без Content-Length при сжатии вес в сети не известен: меряем норму по
        # разметке, но в строке пишем ровно то, что действительно измерили.
        basis = wire or size
        row(
            "Вес главной страницы",
            f"{_kb(size)} разметки, "
            + (f"{_kb(wire)} в сети, " if wire else "вес в сети не назван, ")
            + (f"сжатие {encoding}" if encoding else "без сжатия"),
            BAD if (not encoding and size > PAGE_OK_BYTES)
            else CHECK if basis > PAGE_OK_BYTES else OK,
            "HTML летит целиком на каждый заход и не сжимается"
            if (not encoding and size > PAGE_OK_BYTES)
            else "размер главной в пределах нормы" if basis <= PAGE_OK_BYTES
            else "главная тяжёлая: часть текста уезжает за первый экран",
        )
        version = page.get("http_version") or ""
        if version:
            modern = version.replace("HTTP/", "").rstrip(".0") in ("2", "3")
            row(
                "Протокол соединения",
                version + (f", отдаёт: {page['server']}" if page.get("server") else ""),
                OK if modern else CHECK,
                "HTTP/2 грузит скрипты и стили одним соединением" if not modern
                else "соединение мультиплексируется",
            )
        hops = int(page.get("redirects") or 0)
        final = page.get("final_path") or "/"
        row(
            "Редирект при заходе",
            f"{hops} шага, финальный адрес: {final}" if hops else "сразу 200",
            CHECK if hops else OK,
            "каждый шаг — это ещё одна полная пауза до первого байта" if hops
            else "адрес из рекламы ведёт на страницу напрямую",
        )
        cache = page.get("cache_control") or ""
        row(
            "Кэш главной",
            f"Cache-Control: {cache}" if cache else "заголовка кэша нет",
            CHECK if _cache_state(cache, "") == "cached" else OK,
            "обновления на сайте начнут доходить не сразу"
            if _cache_state(cache, "") == "cached" else "главная всегда отдаётся свежей",
        )
    else:
        row("Ответ сервера", "замер не сделан", UNKNOWN,
            "главная не ответила на отдельный запрос — про скорость ничего не известно")

    if markup.get("parsed"):
        blocking = int(markup.get("blocking") or 0)
        held = int(markup.get("deferred") or 0)
        row(
            "Скрипты, блокирующие отрисовку",
            f"{blocking} в <head> без defer/async" + (f", отложены: {held}" if held else ""),
            OK if not blocking else CHECK if blocking <= 2 else BAD,
            "белый экран держат не сервер, а эти скрипты" if blocking
            else "критический путь загрузки не заблокирован",
        )
        hosts = markup.get("third_party_hosts") or []
        third = int(markup.get("third_party") or 0)
        level = OK if third <= THIRD_PARTY_OK else CHECK if third <= THIRD_PARTY_BAD else BAD
        row(
            "Чужие скрипты и виджеты",
            (f"{third} адресов с {len(hosts)} хостов: " + ", ".join(hosts[:4])) if hosts
            else "чужих подключений нет",
            level,
            "страница зависит только от вашего хостинга" if not hosts
            else "зависимость от чужих серверов невелика" if level == OK
            else "чужой сервер в критическом пути: он тормозит, падает и меняет экран без спроса",
        )
        frames = int(markup.get("iframes") or 0)
        if frames:
            row(
                "Виджеты в iframe",
                f"{frames}, хостов: {len(markup.get('iframe_hosts') or [])}",
                CHECK if frames <= 3 else BAD,
                "iframe грузит отдельную страницу целиком и всегда без ленивой загрузки",
            )
        images = int(markup.get("images") or 0)
        if images:
            no_dims = int(markup.get("images_no_dims") or 0)
            share = round(100 * no_dims / images)
            row(
                "Картинки без размеров (риск сдвига макета)",
                f"{_share(no_dims, images)} ({share}%)",
                OK if not no_dims else CHECK if share <= 50 else BAD,
                "размеры зарезервированы в разметке — экран не прыгает" if not no_dims
                else "пока картинка догружается, текст под ней прыгает — это же CLS",
            )
            lazy = int(markup.get("images_lazy") or 0)
            srcset = int(markup.get("images_srcset") or 0)
            modern = int(markup.get("images_modern") or 0)
            row(
                "Картинки: ленивая загрузка и форматы",
                f"lazy {lazy}, набор размеров (srcset) {srcset}, webp/avif {modern} из {images}",
                OK if modern or srcset else CHECK,
                "телефон скачивает полноразмерную картинку вместо готовой под экран"
                if not (modern or srcset) else "часть картинок уже облегчена",
            )
        nodes = int(markup.get("dom_nodes") or 0)
        if nodes:
            row(
                "Размер разметки (узлы DOM)",
                f"{nodes} узлов, инлайн-стилей: {_kb(markup.get('inline_style_bytes'))}, "
                f"инлайн-скриптов: {_kb(markup.get('inline_script_bytes'))}",
                OK if nodes <= DOM_OK_NODES else CHECK if nodes <= DOM_BAD_NODES else BAD,
                "дерево лёгкое — браузер пересобирает его быстро" if nodes <= DOM_OK_NODES
                else "тяжёлое дерево браузер пересобирает на каждое действие",
            )
        fonts = int(markup.get("font_faces") or 0)
        if fonts:
            hinted = bool(markup.get("font_preload") or markup.get("preconnect"))
            row(
                "Шрифты",
                f"{fonts} @font-face, предзагрузки: {int(markup.get('font_preload') or 0)}, "
                f"предсоединения: {int(markup.get('preconnect') or 0)}",
                OK if hinted else CHECK,
                "шрифт запрошен заранее — текст не ждёт молча" if hinted
                else "текст ждёт шрифт молча, а предзагрузка снимает эту паузу",
            )
        viewport = "viewport объявлен" if markup.get("viewport") else "viewport не найден"
        zoom = "; зум пальцем выключён" if markup.get("zoom_locked") else ""
        row(
            "Мобильная настройка",
            viewport + zoom,
            OK if markup.get("viewport") and not markup.get("zoom_locked") else CHECK,
            "мелкий текст нельзя приблизить — заявка теряется на самом интересном"
            if markup.get("zoom_locked")
            else "телефон знает, что страница под него сверстана" if markup.get("viewport")
            else "с телефона страницу показывают целиком и уменьшенной",
        )

    if assets.get("checked"):
        loose = int(assets.get("uncompressed") or 0)
        uncached = int(assets.get("uncached") or 0)
        silent = int(assets.get("unreachable") or 0)
        weighed = int(assets.get("weighed") or 0)
        weightless = int(assets.get("weightless") or 0)
        total = int(assets.get("checked") or 0)
        label = "Вес ресурсов (проба заголовков)"
        seen = f"пробовано {total}: " + (
            f"вес назван у {weighed} ({_kb(assets.get('bytes') or 0)})" if weighed
            else "вес не назвал ни один ресурс"
        )
        seen += f", со сжатием {int(assets.get('compressed') or 0)}, без кэша {uncached}"
        if weightless:
            seen += f", без веса и без сжатия {weightless}"
        if silent:
            seen += f", без ответа {silent}"
        if assets.get("stopped"):
            seen += f" ({assets['stopped']})"
        if silent == total:
            row(label, seen, UNKNOWN,
                "ни один ресурс не ответил — вес и кэш статики остались неизвестными")
        elif assets.get("dead"):
            row(label, seen, BAD, "часть статики из разметки не отдаётся совсем")
        elif loose or uncached or weightless:
            causes = []
            if loose:
                causes.append(f"{loose} летит без сжатия")
            if uncached:
                causes.append(f"{uncached} перекачивается при каждом заходе")
            if weightless:
                causes.append(f"{weightless} отдан без размера — его вес не проверить")
            row(label, seen, CHECK, "статика: " + "; ".join(causes))
        elif not weighed:
            row(label, seen, UNKNOWN,
                "сколько весят скрипты и стили — не измерено: сервер не назвал размеры")
        else:
            row(label, seen, OK, "сжатая и кэшированная статика докачивается один раз")
        for item in (assets.get("dead") or [])[:3]:
            path = urlparse(item.get("url") or "").path or item.get("url")
            row(
                "Ресурс не отдан",
                f"{path} — HTTP {int(item.get('status') or 0)}",
                BAD,
                "скрипт или картинка из разметки отсутствуют — часть страницы не отрисуется",
            )
    elif assets.get("found"):
        row("Вес ресурсов (проба заголовков)", "проверить не удалось", UNKNOWN,
            "сервер не ответил ни на один адрес ресурса")

    state = psi.get("state") or "skipped"
    if state == "ok":
        score = int(psi.get("score") or 0)
        row(
            "PageSpeed Insights (мобильные)",
            f"балл {score}" + (f", {psi['strategy']}" if psi.get("strategy") else ""),
            OK if score >= 90 else CHECK if score >= 50 else BAD,
            "оценка Google на одном прогоне: повторяется с разбросом в десять баллов",
        )
    else:
        row(
            "PageSpeed Insights (мобильные)",
            PSI_STATE_TEXT.get(state, "нет данных"),
            UNKNOWN,
            "точные замеры теста недоступны: остальные строки — разметка и ответы сервера",
        )

    lab = psi.get("lab") or {}
    if lab:
        row(
            "Core Web Vitals (лаборатория)",
            _lab_line(lab),
            _worst([_grade(key, value) for key, value in lab.items()]),
            "это замер на одном устройстве: у ваших посетителей может быть хуже",
        )
    field = psi.get("field") or {}
    if field:
        grades = [GRADE_VERDICT.get((item or {}).get("grade"), UNKNOWN) for item in field.values()]
        row(
            "Core Web Vitals (реальные посещения)",
            _field_line(field),
            _worst(grades),
            "по этим цифрам Google судит страницу в поиске",
        )
    else:
        row("Core Web Vitals (реальные посещения)", "данных нет", UNKNOWN,
            "нужен счётчик с WebVisor или отчёт CrUX — по одному прогону о посетителях не судят")


def build_speed_checks(speed: Dict) -> Dict:
    """Таблица скоростных проверок. Строки и цифры генерирует код."""
    speed = speed or empty_speed()
    columns = ["Проверка", "Что измерено", "Вывод"]
    if speed.get("failed"):
        return {
            "columns": columns,
            "rows": [["Скорость и мобильность", "замер не завершился",
                      f"{UNKNOWN} — время ответа, вес страницы и PSI смотрим руками"]],
        }
    rows: List[List[str]] = []
    _verdict_rows(speed, rows)
    return {"columns": columns, "rows": rows}


def speed_gaps(speed: Dict) -> List[str]:
    """Чего этот раздел утверждать не может — честно списком."""
    if not speed:
        return []
    if speed.get("failed"):
        return [
            "Замер скорости не завершился: время ответа сервера и вес страницы неизвестны — "
            "в отчёте они не оценены"
        ]
    gaps: List[str] = []
    psi = speed.get("psi") or {}
    if psi.get("state") != "ok":
        reason = PSI_STATE_TEXT.get(psi.get("state"), "тест не запускался")
        gaps.append(
            f"Лабораторных цифр PageSpeed Insights нет ({reason}): точный балл и "
            "Core Web Vitals неизвестны, раздел посчитан по ответам сервера и разметке"
        )
    if not (psi.get("field") or {}):
        gaps.append(
            "Данных о скорости у реальных посетителей нет: нужны Яндекс.Метрика с WebVisor "
            "или отчёт CrUX — один прогон не показывает, с чем сталкивается клиент"
        )
    if not (speed.get("page") or {}).get("measured"):
        gaps.append(
            "Главную страницу не удалось замерить отдельным запросом: время ответа сервера "
            "и вес HTML остались неизвестными"
        )
    assets = speed.get("assets") or {}
    checked = int(assets.get("checked") or 0)
    silent = int(assets.get("unreachable") or 0)
    if checked and silent == checked:
        gaps.append(
            "Статика не ответила на пробу: вес, сжатие и кэш скриптов и стилей не проверены"
        )
    elif checked and not assets.get("weighed"):
        gaps.append(
            "Вес статики не измерен: сервер отдал файлы без Content-Length — сколько качают "
            "скрипты и стили, по этому аудиту неизвестно"
        )
    elif assets.get("found") and not checked:
        gaps.append(
            "Пробу ресурсов не удалось сделать: вес, сжатие и кэш статики не проверены"
        )
    return gaps


def render_speed(speed: Dict) -> str:
    """Блок скорости для промпта: модель рассуждает по замерам, а не по догадкам.

    Без этой строки отчёт пишет «сайт медленный, оптимизируйте картинки» там,
    где сервер отвечает за 90 мс, а тормозит четвёртый чужой виджет.
    """
    speed = speed or {}
    if speed.get("failed"):
        return "## Скорость и мобильность\nЗамер не завершился: выводов о скорости нет."
    page = speed.get("page") or {}
    markup = speed.get("markup") or {}
    assets = speed.get("assets") or {}
    psi = speed.get("psi") or {}

    def count(source: Dict, key: str) -> int:
        return int(source.get(key) or 0)

    lines = ["## Скорость и мобильность (посчитано кодом по замерам и разметке)"]
    if page.get("measured"):
        wire = (f"{_kb(page.get('wire_bytes'))} в сети"
                if count(page, "wire_bytes") else "вес в сети не назван")
        lines.append(
            f"Замер главной: ответ сервера {count(page, 'ttfb_ms')} мс, весь запрос "
            f"{count(page, 'total_ms')} мс, {_kb(page.get('content_bytes'))} разметки, {wire}, "
            f"{page.get('encoding') or 'без сжатия'}, "
            f"{page.get('http_version') or 'протокол неизвестен'}, "
            f"редиректов: {count(page, 'redirects')}"
        )
    else:
        lines.append("Замер главной: не сделан — время ответа и вес страницы неизвестны")

    if markup.get("parsed"):
        hosts = ", ".join((markup.get("third_party_hosts") or [])[:5]) or "нет"
        lines.append(
            f"Разметка: скриптов {count(markup, 'scripts')} (блокирующих в head "
            f"{count(markup, 'blocking')}, отложенных {count(markup, 'deferred')}), "
            f"стилей {count(markup, 'styles')}, узлов DOM {count(markup, 'dom_nodes')}"
        )
        lines.append(
            f"Чужих подключений {count(markup, 'third_party')} с хостов: {hosts}; "
            f"iframe: {count(markup, 'iframes')}"
        )
        lines.append(
            f"Картинки: {count(markup, 'images')}, без размеров "
            f"{count(markup, 'images_no_dims')}, lazy {count(markup, 'images_lazy')}, "
            f"srcset {count(markup, 'images_srcset')}, webp/avif {count(markup, 'images_modern')}"
        )
        zoom = ", зум выключён" if markup.get("zoom_locked") else ""
        lines.append(
            f"Viewport: {'есть' if markup.get('viewport') else 'нет'}{zoom}; "
            f"@font-face: {count(markup, 'font_faces')}, предзагрузка шрифтов: "
            f"{count(markup, 'font_preload')}"
        )
    else:
        lines.append("Разметка главной не прочитана — блокирующие скрипты и картинки не посчитаны")

    if assets.get("checked"):
        # Модель обязана отличать «статика лёгкая» от «статика не взвешена»:
        # иначе из нуля байт она соберёт находку, которой в замере не было.
        weighed = count(assets, "weighed")
        size = (f"{_kb(assets.get('bytes'))}, вес назван у {weighed}" if weighed
                else "вес не назвал ни один ресурс")
        lines.append(
            f"Проба ресурсов: {assets['checked']} адресов, {size}, "
            f"без сжатия {count(assets, 'uncompressed')}, без кэша {count(assets, 'uncached')}, "
            f"не отдано {len(assets.get('dead') or [])}, без ответа {count(assets, 'unreachable')}"
        )
    else:
        lines.append("Проба ресурсов: не делалась — вес скриптов, стилей и картинок неизвестен")

    state = psi.get("state") or "skipped"
    if state == "ok":
        lines.append(
            f"PageSpeed Insights: балл {count(psi, 'score')}; лаборатория: "
            f"{_lab_line(psi.get('lab') or {}) or 'метрики не отдали'}; полевые данные: "
            f"{_field_line(psi.get('field') or {}) or 'нет данных о реальных посещениях'}"
        )
    else:
        reason = PSI_STATE_TEXT.get(state, "нет данных")
        lines.append(f"PageSpeed Insights: {reason} — цифр теста нет")
    return "\n".join(lines)


def assess(origin: str, html: str, page: Dict, fetch_headers: Callable,
           run_psi: Optional[Callable[[], Dict]] = None) -> Dict:
    """Весь скоростной срез сайта.

    Этапы независимы: разметка читается даже когда сервер молчит, а недоступный
    PageSpeed не мешает замерам веса и кэша.
    """
    speed = empty_speed()
    speed["origin"] = origin
    speed["page"] = normalize_page(page)
    speed["markup"] = parse_markup(html, origin)
    urls = pick_assets(speed["markup"], origin)
    speed["asset_urls"] = urls
    try:
        speed["assets"] = probe_assets(urls, fetch_headers)
    except Exception:  # noqa: BLE001 - сбой пробы не стоит остальных замеров
        speed["assets"] = dict(speed["assets"], found=len(urls), stopped="проба не удалась")
    try:
        speed["psi"] = psi_facts(run_psi() if run_psi else {})
    except Exception:  # noqa: BLE001 - тест мог не ответить, цифры веса это не отменяет
        speed["psi"] = {"state": "error", "score": 0, "lab": {}, "field": {}}
    return speed
