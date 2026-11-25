"""Проверки, для которых нужен не текст страницы, а ответы сервера.

robots.txt и sitemap клиент руками не открывает, а без них нельзя сказать,
индексируется ли сайт вообще. Ссылки проверяются запросами к серверу: отчёт
обязан видеть 404 там, где меню на экране выглядит целым.

Сеть в этот модуль не приходит — анализатор передаёт функцию `fetch`, и вся
логика остаётся проверяемой без интернета.
"""

import re
import time
from typing import Callable, Dict, List
from urllib.parse import urlparse

# Дальше вывод дороже времени: ссылку ищут секунду, аудит ждут минуту.
MAX_LINK_CHECKS = 10
LINK_BUDGET_SECONDS = 20.0

# Файл мог лежать под другим именем — проверяем оба, не выдумывая третьих.
SITEMAP_FALLBACKS = ("/sitemap.xml", "/sitemap_index.xml")

OK = "норма"
CHECK = "проверить"
MISSING = "не найдено"
BAD = "ошибка"
UNKNOWN = "не проверено"

ABSENT_STATES = ("absent", "blocked")
LOC_TAG = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
LASTMOD_TAG = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)

STATE_TEXT = {
    "ok": "файл прочитан",
    "index": "прочитан индекс карт",
    "absent": "файл не найден (HTTP 404)",
    "blocked": "доступ закрыт (HTTP 401/403)",
    "error": "сервер ответил ошибкой",
    "empty": "файл есть, но пустой",
    "foreign": "ответ не похож на карту сайта",
    "unreachable": "ответ не получен",
}

# 404 — это факт о сайте, «сервер молчит» — факт о нашей проверке. Выводы
# должны различаться: в первом случае есть что чинить, во втором — что досмотреть.
STATE_VERDICT = {
    "absent": CHECK,
    "blocked": CHECK,
    "empty": CHECK,
    "foreign": CHECK,
    "error": BAD,
    "unreachable": UNKNOWN,
}


def empty_infra() -> Dict:
    """Пустой результат: ни одна проверка не сделана, ни одна не выдумана."""
    return {
        "robots": {"state": "unreachable", "status": 0, "rules": 0, "agents": [], "sitemaps": [],
                   "host": "", "crawl_delay": "", "blocked_agents": [], "allow": 0},
        "sitemap": {"state": "unreachable", "status": 0, "urls": 0, "nested": 0, "offsite": 0,
                    "newest": "", "sample": [], "url": "", "probed": []},
        "links": {"checked": 0, "found": 0, "broken": [], "redirected": [], "unreachable": 0,
                  "stopped": ""},
    }


def _state(status: int, text: str) -> str:
    """Состояние ответа без подмены: «нет файла» и «сервер молчит» — разные выводы."""
    if not status:
        return "unreachable"
    if status in (404, 410):
        return "absent"
    if status in (401, 403):
        return "blocked"
    if status >= 300:
        # Незакрытый редирект: файл мы не прочитали, но сказать «404» было бы враньём.
        return "error"
    return "empty" if not text.strip() else "ok"


def parse_robots(probe: Dict) -> Dict:
    """Разбор robots.txt: правила, агенты, закрытые разделы, объявленные sitemap'ы."""
    status = int(probe.get("status") or 0)
    text = str(probe.get("text") or "")
    out = {
        "status": status,
        "state": _state(status, text),
        "rules": 0,
        "allow": 0,
        "agents": [],
        "blocked_agents": [],
        "sitemaps": [],
        "host": "",
        "crawl_delay": "",
    }
    if out["state"] != "ok":
        return out

    agents: List[str] = []
    current: List[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            name = (value or "*").lower()
            current = [name]
            if name not in agents:
                agents.append(name)
        elif key in ("disallow", "allow"):
            if not current:
                current = ["*"]
                agents.append("*")
            out["rules"] += 1
            if key == "allow":
                out["allow"] += 1
            elif value == "/" and not any(agent in out["blocked_agents"] for agent in current):
                out["blocked_agents"].extend(current)
            for agent in current:
                if agent not in agents:
                    agents.append(agent)
        elif key == "sitemap":
            if value and value not in out["sitemaps"]:
                out["sitemaps"].append(value)
        elif key == "host":
            out["host"] = value
        elif key == "crawl-delay":
            out["crawl_delay"] = value

    out["agents"] = agents
    return out


def parse_sitemap(probe: Dict, origin: str = "") -> Dict:
    """Разбор sitemap: сколько адресов, свои ли они, когда обновлялись."""
    status = int(probe.get("status") or 0)
    text = str(probe.get("text") or "")
    out = {
        "status": status,
        "state": _state(status, text),
        "urls": 0,
        "nested": 0,
        "offsite": 0,
        "newest": "",
        "sample": [],
    }
    if out["state"] != "ok":
        return out

    locs = [url.strip() for url in LOC_TAG.findall(text) if url.strip()]
    out["urls"] = len(locs)
    out["nested"] = sum(1 for url in locs if url.lower().endswith((".xml", ".xml.gz")))
    base_host = (urlparse(origin).netloc or "").lower()
    if base_host:
        out["offsite"] = sum(
            1 for url in locs if (urlparse(url).netloc or "").lower() not in ("", base_host, "www." + base_host)
        )
    dates = [value for value in LASTMOD_TAG.findall(text) if value.strip()]
    if dates:
        out["newest"] = max(dates)[:10]
    out["sample"] = locs[:5]
    if not locs:
        # CMS часто отдают на /sitemap.xml главную страницу с кодом 200. Называть
        # такое «картой» нельзя: ответ есть, а карты нет.
        out["state"] = "foreign"
    elif out["nested"] == len(locs) and len(locs) > 1:
        out["state"] = "index"
    return out


def probe_links(links: List[str], fetch: Callable, budget: float = LINK_BUDGET_SECONDS,
                clock: Callable[[], float] = time.monotonic) -> Dict:
    """HEAD по внутренним ссылкам: битые и ведущие через редирект видно только так.

    Бюджет по времени и по количеству — не косметика: аудит ждут минуту, а
    сервер может отвечать на каждый адрес пятнадцать секунд.
    """
    result = {"checked": 0, "found": len(links), "broken": [], "redirected": [],
              "unreachable": 0, "stopped": ""}
    started = clock()
    for url in links[:MAX_LINK_CHECKS]:
        if clock() - started > budget:
            result["stopped"] = "закончился бюджет времени на проверку ссылок"
            break
        probe = fetch(url, "HEAD")
        status = int(probe.get("status") or 0)
        if status in (405, 501) or not status:
            # HEAD не поддержан или упал — подтверждаем GET, иначе «битая ссылка»
            # окажется просто капризом сервера.
            probe = fetch(url, "GET")
            status = int(probe.get("status") or 0)
        result["checked"] += 1
        chain = probe.get("chain") or []
        if not status:
            result["unreachable"] += 1
        elif status >= 400:
            result["broken"].append({"url": url, "status": status})
        elif chain:
            result["redirected"].append({"url": url, "status": int(chain[0].get("status") or 0),
                                          "to": chain[-1].get("to") or ""})
    if not result["stopped"] and result["found"] > result["checked"]:
        result["stopped"] = f"проверено {result['checked']} ссылок из {result['found']}"
    return result


def probe_site(origin: str, fetch: Callable, links: List[str]) -> Dict:
    """Полный инфраструктурный срез: robots, sitemap по robots и fallback, ссылки."""
    infra = empty_infra()
    infra["robots"] = parse_robots(fetch(origin.rstrip("/") + "/robots.txt", "GET"))

    candidates = [
        url for url in infra["robots"]["sitemaps"]
        if (urlparse(url).scheme or "").lower() in ("http", "https")
    ]
    for path in SITEMAP_FALLBACKS:
        candidate = origin.rstrip("/") + path
        if candidate not in candidates:
            candidates.append(candidate)

    chosen = None
    probed: List[str] = []
    for url in candidates[:3]:
        probed.append(url)
        sitemap = dict(parse_sitemap(fetch(url, "GET"), origin), url=url)
        if sitemap["state"] in ("ok", "index"):
            chosen = sitemap
            break
        # Из негодных выбираем самое говорящее: 404 на запасном пути не должен
        # затереть ответ «это не карта» с основного адреса.
        if chosen is None or (chosen["state"] == "absent" and sitemap["state"] != "absent"):
            chosen = sitemap
    infra["sitemap"] = dict(chosen or empty_infra()["sitemap"], probed=probed)
    infra["links"] = probe_links(links, fetch)
    return infra


def _verdict_rows(infra: Dict, rows: List[List[str]]) -> None:
    robots = infra.get("robots") or {}
    sitemap = infra.get("sitemap") or {}
    links = infra.get("links") or {}

    def row(check: str, seen: str, verdict: str, why: str) -> None:
        rows.append([check, seen, f"{verdict} — {why}" if why else verdict])

    state = robots.get("state")
    if state == "ok":
        rules = int(robots.get("rules") or 0)
        seen = (
            f"файл есть, правил: {rules} (allow: {int(robots.get('allow') or 0)}), "
            f"агентов: {len(robots.get('agents') or [])}"
        )
        row("robots.txt", seen, OK if rules else CHECK,
            "по нему поиск понимает, что можно читать" if rules else
            "файл есть, но запретов и разрешений в нём нет")
    else:
        row("robots.txt", STATE_TEXT.get(state, "нет данных"),
            STATE_VERDICT.get(state, UNKNOWN),
            "поисковик идёт по всему сайту, включая мусор и служебные страницы"
            if state in ABSENT_STATES else "файл не прочитан, выводов о нём нет")

    blocked = robots.get("blocked_agents") or []
    if blocked:
        row("Закрыто от индексации", "Disallow: / для " + ", ".join(blocked[:6]), BAD,
            "такие роботы на сайт не придут вовсе")
    elif state == "ok":
        row("Закрыто от индексации", "полных запретов нет", OK, "сайт открыт поисковым роботам")

    if robots.get("sitemaps"):
        row("Sitemap объявлен в robots", ", ".join(robots["sitemaps"][:3]), OK,
            "робот узнаёт о карте без ручных настроек")
    elif state == "ok":
        row("Sitemap объявлен в robots", "строк Sitemap: нет", CHECK,
            "карту поиска приходится подсказывать вручную")

    sstate = sitemap.get("state")
    if sstate in ("ok", "index"):
        urls = int(sitemap.get("urls") or 0)
        kind = "карта-индекс" if sstate == "index" else "карта страниц"
        seen = f"{kind}, адресов: {urls}"
        if sitemap.get("newest"):
            seen += f", обновлена {sitemap['newest']}"
        row("Sitemap", seen, OK if urls else CHECK,
            "по нему поиск видит новые страницы без ручного обхода")
    else:
        seen = STATE_TEXT.get(sstate, "нет данных")
        probed = sitemap.get("probed") or []
        if probed:
            # «Карты нет» без списка проверенных адресов — голословие: карта
            # может лежать под именем, которое мы не искали.
            seen += ": проверены " + ", ".join(
                (urlparse(url).path or url) for url in probed[:3]
            )
        row("Sitemap", seen,
            STATE_VERDICT.get(sstate, UNKNOWN),
            "новые страницы доходят до поиска медленно"
            if sstate in ABSENT_STATES else "карта не прочитана, выводов о ней нет")

    offsite = int(sitemap.get("offsite") or 0)
    if sstate in ("ok", "index"):
        row("Чужие адреса в sitemap", f"{offsite}" if offsite else "нет",
            BAD if offsite else OK,
            "чужие страницы в карте — повод искать ошибку сборки или взлом")

    checked = int(links.get("checked") or 0)
    broken = links.get("broken") or []
    redirected = links.get("redirected") or []
    if checked:
        seen = f"проверено {checked}: битых {len(broken)}, с редиректом {len(redirected)}"
        if links.get("unreachable"):
            seen += f", без ответа {links['unreachable']}"
        if links.get("stopped"):
            seen += f" ({links['stopped']})"
        row("Внутренние ссылки", seen, BAD if broken else CHECK if redirected else OK,
            "битая ссылка в меню — это потерянная заявка, а не мелочь")
        for item in broken[:3]:
            row("Битая ссылка", f"{item.get('url')} — HTTP {item.get('status')}", BAD,
                "страницы нет, а ссылка на неё кликабельна")
        for item in redirected[:2]:
            row("Ссылка через редирект",
                f"{item.get('url')} -> {item.get('to')} (HTTP {item.get('status')})", CHECK,
                "ссылка ведёт через шаг, а на медленных сетях шаг стоит заявителя")
    else:
        # Пустой список ссылок и молчаливый сервер — разные выводы: в первом
        # случае проверять было нечего, во втором — не получилось.
        found = int(links.get("found") or 0)
        row(
            "Внутренние ссылки",
            "внутренних ссылок не найдено" if not found else "проверить не удалось",
            CHECK if not found else UNKNOWN,
            "на прочитанных страницах нет ни одной внутренней ссылки"
            if not found
            else "сервер не ответил ни на один адрес — про доступность страниц ничего не известно",
        )


def build_infra_checks(infra: Dict) -> Dict:
    """Таблица инфраструктурных проверок. Строки генерирует код."""
    infra = infra or empty_infra()
    rows: List[List[str]] = []
    if infra.get("failed"):
        return {
            "columns": ["Проверка", "Что видно на сервере", "Вывод"],
            "rows": [["Инфраструктура сайта", "проверка не завершилась",
                      f"{UNKNOWN} — robots.txt, карту и ссылки смотрим руками"]],
        }
    _verdict_rows(infra, rows)
    return {"columns": ["Проверка", "Что видно на сервере", "Вывод"], "rows": rows}


def infra_gaps(infra: Dict) -> List[str]:
    """Чего нельзя утверждать по ответам сервера — честно списком."""
    if not infra:
        # Пробу не делали — значит, и утверждать про robots и sitemap нечего.
        return []
    if infra.get("failed"):
        return [
            "Инфраструктуру сайта проверить не удалось: robots.txt, карту сайта "
            "и доступность ссылок смотрим руками"
        ]
    links = infra.get("links") or {}
    gaps: List[str] = []

    if not int(links.get("checked") or 0):
        if int(links.get("found") or 0):
            gaps.append(
                "Живые ссылки проверить не удалось: сервер не ответил — "
                "про доступность страниц в отчёте ничего не известно"
            )
        else:
            gaps.append(
                "Внутренних ссылок на прочитанных страницах нет — проверить "
                "доступность страниц не на чем"
            )
    if (infra.get("sitemap") or {}).get("state") not in ("ok", "index"):
        gaps.append(
            "Карты сайта нет или её не удалось прочитать: сколько страниц "
            "проиндексировано — неизвестно, нужны данные поисковых систем"
        )
    return gaps


def _map_where(sitemap: Dict) -> str:
    """Где карту искали: найденный адрес или число проверенных путей."""
    state = sitemap.get("state")
    if state in ("ok", "index") and sitemap.get("url"):
        return f"адрес: {sitemap['url']}"
    return f"проверено путей: {len(sitemap.get('probed') or [])}"


def render_infra(infra: Dict) -> str:
    """Инфраструктура для промпта: модель рассуждает по фактам ответа сервера."""
    infra = infra or {}
    robots = infra.get("robots") or {}
    sitemap = infra.get("sitemap") or {}
    links = infra.get("links") or {}
    broken = links.get("broken") or []
    redirected = links.get("redirected") or []

    lines = [
        "## Инфраструктура сайта (посчитано кодом по ответам сервера)",
        f"robots.txt: {STATE_TEXT.get(robots.get('state'), 'нет данных')}; "
        f"правил: {int(robots.get('rules') or 0)}, агентов: {len(robots.get('agents') or [])}; "
        f"закрыто полностью: {', '.join(robots.get('blocked_agents') or []) or 'нет'}",
        f"Sitemap: {STATE_TEXT.get(sitemap.get('state'), 'нет данных')}; {_map_where(sitemap)}; "
        f"адресов: {int(sitemap.get('urls') or 0)}; чужих хостов: {int(sitemap.get('offsite') or 0)}; "
        f"обновлена: {sitemap.get('newest') or 'не известно'}",
        f"Ссылки: проверено {int(links.get('checked') or 0)} из {int(links.get('found') or 0)}; "
        f"битых {len(broken)}; с редиректом {len(redirected)}; без ответа {int(links.get('unreachable') or 0)}",
    ]
    if broken:
        lines.append(
            "Битые адреса: " + "; ".join(f"{item.get('url')} (HTTP {item.get('status')})" for item in broken[:5])
        )
    if redirected:
        lines.append(
            "Редиректы: " + "; ".join(
                f"{item.get('url')} -> {item.get('to')} ({item.get('status')})" for item in redirected[:5]
            )
        )
    return "\n".join(lines)
