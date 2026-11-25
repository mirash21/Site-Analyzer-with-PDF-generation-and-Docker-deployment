"""Проверка тестов мутациями: ломаем механику — набор тестов должен падать.

Каждая мутация воспроизводит конкретный дефект, который чинил этот шаг:
склейка текста в одну строку, обрезка посреди слова, меню вместо оффера,
чужой отчёт по id, таблица «плоским» списком, неэкранированный HTML.
Дальше — то, что появлялось вместе с профессиональным отчётом: выдуманный
адрес источника, телефон в восьми форматах, каталог вместо контактов,
семантика без потолка и пересечения с минус-словами, объявление длиннее
лимита площадки, средний чек из догадки вместо цен сайта.
Дальше — проверки по разметке: счётчик, найденный по слову о нём, охват
«стоит на половине страниц», вывод там, где читать было нечего.
Дальше — инфраструктура: «404» и «сервер молчит» подменены одним выводом,
HTML на месте карты назван картой, HEAD-отклик стал битой ссылкой, бюджет
пробы выключен, редирект ведёт внутрь сети.
Дальше — глубина обхода: пагинация опознана и стоит в очереди выше карточек,
отпечаток содержания различает цены, дубль не притворяется источником,
прочитанное не выдаётся за процитированное, а хвост очереди не исчезает молча
— остановка названа по имени: кончилось время или достигнут потолок страниц.
Дальше — файл не страница: его адрес считается один раз, в обход не качается
и живость свою проверяет пробой ссылок, а не пустой страницей в отчёте.
Дальше — потолок раздела считается долей бюджета: на сайте, где всё содержание
в одном каталоге, обход обязан выбрать страницы, а не уйти с половиной бюджета.
Дальше — скорость: свой замер не путается с чужим PSI, «молчит» не значит
«не найдено», defer снимает блокировку, квота Google не объявляется ошибкой сайта,
а неизмеренное остаётся «не проверено» — с пробелом в честном блоке. Вес, которого
сервер не назвал, не превращается ни в «ноль байт», ни в «норму»: незваный вес
статики остаётся измеренным только у тех файлов, где Content-Length был.
Дальше — балл: «не проверено» не входит в знаменатель, но обязано быть названо,
ось из двух строк в итог не идёт, полоса «готов вести трафик» снимается при любой
незакрытой ошибке — даже в той оси, которая в балл не попала. Очередь работ
сортируется по весу оси, молчание проверок не притворяется чистым счётом, а ноль
отличается от «не посчитано».
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/mirash/site-analyzer")
PY = "/home/mirash/.venvs/sa/bin/python"
LOCK = Path("/tmp/site-analyzer-mutation.lock")

MUTATIONS = [
    (
        "analyzer: обрезка посреди слова вместо границы строки",
        "app/services/analyzer.py",
        '        window = text[:limit]\n        cut = window.rfind("\\n")\n        if cut <= 0:\n            cut = window.rfind(" ")\n        if cut > 0:\n            window = window[:cut]\n        return window.rstrip() + "\\n…(остальное не поместилось в лимит)"',
        '        return text[:limit] + "\\n…(остальное не поместилось в лимит)"',
    ),
    (
        "analyzer: весь текст склеен в одну строку (прежний clean_html)",
        "app/services/analyzer.py",
        '        content = "\\n".join(header + lines).strip()',
        '        content = " ".join(header + lines).strip()',
    ),
    (
        "analyzer: навигация не отделена от содержания",
        "app/services/analyzer.py",
        "        for node in soup.find_all(CHROME_TAGS):",
        "        for node in soup.find_all([]):",
    ),
    (
        "analyzer: ссылки на чужие хосты принимаются",
        "app/services/analyzer.py",
        '            absolute = urljoin(base_url, href)\n'
        "            parsed = urlparse(absolute)\n"
        '            if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != base_netloc:',
        '            absolute = urljoin(base_url, href)\n'
        "            parsed = urlparse(absolute)\n"
        '            if parsed.scheme not in ("http", "https"):',
    ),
    (
        "analyzer: внутренние страницы без бюджета (лимит выключен)",
        "app/services/analyzer.py",
        '                f"{self._fit(extra_content, per_extra_room)}"',
        '                f"{extra_content}"',
    ),
    (
        "analyzer: markdown-таблица остаётся текстом",
        "app/services/analyzer.py",
        "        if isinstance(value, str):\n            return cls._markdown_table_to_grid(value)",
        "        if isinstance(value, str):\n            return {}",
    ),
    (
        "analyzer: пример объявления не разложен на заголовок и текст",
        "app/services/analyzer.py",
        "                lines = [line.strip() for line in item.splitlines() if line.strip()]",
        "                lines = [item.strip()] if item.strip() else []",
    ),
    (
        "analyzer: ответ не-объект принимается молча",
        "app/services/analyzer.py",
        '            raise Exception("LLM вернула итоговый анализ не в формате JSON-объекта")',
        "            return {}",
    ),
    (
        "history: проверка владельца отчёта удалена",
        "app/routers/history.py",
        "        SiteAnalysis.id == analysis_id,\n        SiteAnalysis.user_id == current_user.id,",
        "        SiteAnalysis.id == analysis_id,",
    ),
    (
        "pdf: заголовок таблицы добавлен плоским списком (падает на сборке)",
        "app/services/pdf_report.py",
        '        return [_table_flowable([[str(column) for column in value["columns"]]] + rows, styles)]',
        '        return [_table_flowable([str(column) for column in value["columns"]] + rows, styles)]',
    ),
    (
        "pdf: содержимое сайта не экранируется",
        "app/services/pdf_report.py",
        '    text = escape(str(raw if raw is not None else ""))',
        '    text = str(raw if raw is not None else "")',
    ),
    # --- механизмы, добавленные после переделки отчёта ---------------------
    (
        "analyzer: выдуманный адрес источника принимается за настоящий",
        "app/services/analyzer.py",
        "        return SOURCE_REFERENCE_UNRESOLVED",
        "        return text",
    ),
    (
        "analyzer: страницы в тексте без номеров реестра",
        "app/services/analyzer.py",
        '                f"## Источник {source_id}: {path}\\n"',
        '                f"## Страница: {path}\\n"',
    ),
    (
        "analyzer: телефон не нормализуется (каждый в своём формате)",
        "app/services/analyzer.py",
        '        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:]}"',
        "        return digits",
    ),
    (
        "analyzer: маска номера сдвинута",
        "app/services/analyzer.py",
        '            if len(digits) != 11 or digits[0] not in "78":',
        '            if len(digits) != 10:',
    ),
    (
        "analyzer: юрлицо хватает реквизиты вместе с названием",
        "app/services/analyzer.py",
        "{{1,3}}[«»\\\"']?\"",
        "{{1,9}}[«»\\\"']?\"",
    ),
    (
        "analyzer: стоп-слов в названии юрлица нет, ИНН становится частью имени",
        "app/services/analyzer.py",
        "(?:(?!(?:{LEGAL_ENTITY_STOP_WORDS})\\b)[А-Яа-яЁёA-Za-z]",
        "(?:[А-Яа-яЁёA-Za-z]",
    ),
    (
        "analyzer: квота раздела отключена (каталог вытесняет контакты)",
        "app/services/analyzer.py",
        "            if taken >= per_section:",
        "            if taken >= per_section * 20:",
    ),
    (
        "analyzer: честный блок отдаёт на откуп модели",
        "app/services/analyzer.py",
        "        seeded = (\n            cls._seed_data_gaps(facts)\n"
        '            + site_crawl.crawl_gaps(facts.get("crawl"))\n'
        '            + site_signals.signal_gaps(facts.get("signals"))\n'
        '            + site_infra.infra_gaps(facts.get("infra"))\n'
        '            + site_speed.speed_gaps(facts.get("speed"))\n        )',
        "        seeded = []",
    ),
    (
        "analyzer: порядок разделов — как его дала модель",
        "app/services/analyzer.py",
        "        ordered = {key: result[key] for key in REPORT_SECTION_ORDER if key in result}",
        "        ordered = {}",
    ),
    (
        "analyzer: список семантики не ограничен",
        "app/services/analyzer.py",
        '        seeds = cls._normalize_string_list(result.get("keyword_seeds"))[:MAX_KEYWORDS_PER_LIST]',
        '        seeds = cls._normalize_string_list(result.get("keyword_seeds"))',
    ),
    (
        "analyzer: фраза осталась и в семантике, и в минус-словах",
        "app/services/analyzer.py",
        "        seeds = [item for item in seeds if item.lower() not in excluded]",
        "        seeds = list(seeds)",
    ),
    (
        "analyzer: план кампании затирает нормализованный разбор",
        "app/services/analyzer.py",
        "        result = {key: response[key] for key in CAMPAIGN_PLAN_KEYS if key in response}",
        "        result = dict(response)",
    ),
    (
        "analyzer: объявления не ограничены списком",
        "app/services/analyzer.py",
        "            if len(normalized) >= MAX_AD_EXAMPLES:",
        "            if False:",
    ),
    (
        "analyzer: площадка не опознаётся, лимит знаков не проверить",
        "app/services/analyzer.py",
        '        key = cls._match_platform(ad.get("platform"))',
        '        key = ""',
    ),
    (
        "analyzer: объявление молча обрезано под лимит вместо замечания",
        "app/services/analyzer.py",
        '            ad["limit_note"] = "; ".join(over) + " — сокращать до запуска"',
        '            ad["title"] = (ad.get("title") or "")[: limits["title"] or None]',
    ),
    (
        "analyzer: второй вариант на сегмент не требуют",
        "app/services/analyzer.py",
        "            if count < MIN_ADS_PER_SEGMENT:",
        "            if count < 0:",
    ),
    (
        "analyzer: средний чек взят из догадки, а не из цен сайта",
        "app/services/analyzer.py",
        "            avg_check = float(cls._median(prices))",
        '            avg_check = cls._positive_number(response.get("avg_check")) or float(cls._median(prices))',
    ),
    (
        "analyzer: True проходит как цена клика",
        "app/services/analyzer.py",
        "        if isinstance(value, bool):",
        "        if isinstance(value, tuple):",
    ),
    (
        "analyzer: незакрытый ответ модели не попал в честный блок",
        "app/services/analyzer.py",
        "                notes.append(missing_note)",
        "                pass",
    ),
    (
        "pdf: список фраз снова идёт пунктами по строке",
        "app/services/pdf_report.py",
        '    return str(key or "").strip().lower() in KEYWORD_LIST_KEYS and isinstance(value, list) and bool(value)',
        "    return False",
    ),
    (
        "pdf: адрес источника в отчёте нельзя открыть",
        "app/services/pdf_report.py",
        '    if BARE_URL.fullmatch(whole):',
        '    if False:',
    ),
    (
        "analyzer: правило «пиши по-русски» выключено из всех промптов",
        "app/services/analyzer.py",
        '    "Пиши по-русски. Английское слово оставь только если это название бренда "',
        '    "Пиши как удобно. Английское слово оставь только если это название бренда "',
    ),
    (
        "analyzer: шаг анализа остался без правила о языке",
        "app/services/analyzer.py",
        '"заголовков h1 и пересказа исходного текста. "\n                + RUSSIAN_ONLY_RULE',
        '"заголовков h1 и пересказа исходного текста."',
    ),
    (
        "analyzer: итоговый отчёт остался без правила о языке",
        "app/services/analyzer.py",
        '"Если данных нет — честно пиши об этом в data_gaps, не заменяя их догадками. "\n            + RUSSIAN_ONLY_RULE',
        '"Если данных нет — честно пиши об этом в data_gaps, не заменяя их догадками."',
    ),
    # --- PDF не имеет права падать на разметке модели -----------------
    (
        "pdf: код в бэктиках раскрыт до выделения и склеивает звёздочки в <i>",
        "app/services/pdf_report.py",
        "    text = INLINE_CODE.sub(stash, text)",
        '    text = INLINE_CODE.sub(lambda m: f\'<font face="Courier">{m.group("text")}</font>\', text)',
    ),
    (
        "pdf: незакрытый тег снова роняет весь отчёт",
        "app/services/pdf_report.py",
        "    return _balanced(text)",
        "    return text",
    ),
    (
        "pdf: жирный курсив закрыт вразнобой",
        "app/services/pdf_report.py",
        "    text = INLINE_TRIPLE.sub(lambda m: f\"<b><i>{m.group('text')}</i></b>\", text)",
        "    text = INLINE_TRIPLE.sub(lambda m: f\"<b><i>{m.group('text')}</b></i>\", text)",
    ),
    # --- Проверки по разметке: код обязан считать, а не предполагать -----
    (
        "signals: пустой ответ засчитан как прочитанная страница",
        "app/services/site_signals.py",
        "    if not raw.strip():",
        "    if False:",
    ),
    (
        "signals: незагруженный сайт получил бы таблицу выводов",
        "app/services/site_signals.py",
        "    if not pages:\n        # Читать было нечего: любая строка ниже была бы утверждением о сайте,",
        "    if False:\n        # Читать было нечего: любая строка ниже была бы утверждением о сайте,",
    ),
    (
        "signals: название счётчика в тексте считается за установленный",
        "app/services/site_signals.py",
        "        return any(re.search(pattern, raw, re.I) for pattern in matches)",
        "        return True",
    ),
    (
        "signals: слияние страниц не складывает проверки",
        "app/services/site_signals.py",
        "        target[key] = int(target.get(key, 0)) + int(addition.get(key, 0))",
        "        target[key] = max(int(target.get(key, 0)), int(addition.get(key, 0)))",
    ),
    (
        "signals: охват счётчика свёрнут в голое «найдены: имя»",
        "app/services/site_signals.py",
        '        parts.append(f"{name} — на {count} из {pages}" if per_page and count < pages else name)',
        "        parts.append(name)",
    ),
    (
        "signals: два H1 на странице перестали быть дефектом",
        "app/services/site_signals.py",
        '    h1_seen = f"без H1: {h1_missing}, с двумя и больше: {h1_multiple}"',
        '    h1_seen = f"без H1: {h1_missing}"',
    ),
    (
        "signals: og-теги приписаны всем прочитанным страницам",
        "app/services/site_signals.py",
        '        f"og-теги: {og} из {pages}" if pages else "нет данных",',
        '        f"og-теги: {pages} из {pages}",',
    ),
    (
        "signals: отсутствие форм перестало быть честным пробелом",
        "app/services/site_signals.py",
        '    if not int(signals.get("forms", 0)):\n        gaps.append(NO_FORMS_GAP)',
        '    if int(signals.get("forms", 0)):\n        gaps.append(NO_FORMS_GAP)',
    ),
    (
        "analyzer: проверки разметки не дошли до итогового промпта",
        "app/services/analyzer.py",
        r'            + (f"{checks_block}\n\n" if checks_block else "")',
        '            + ""',
    ),
    (
        "analyzer: план кампании не видит проверок, посчитанных кодом",
        "app/services/analyzer.py",
        '        literal = self.render_business_facts(facts) if facts else ""\n'
        "        checks_block = self._checks_block(facts)",
        '        literal = self.render_business_facts(facts) if facts else ""\n'
        '        checks_block = ""',
    ),
    (
        "analyzer: экономика не видит проверок, посчитанных кодом",
        "app/services/analyzer.py",
        "        literal = self.render_business_facts(facts)\n"
        "        checks_block = self._checks_block(facts)",
        "        literal = self.render_business_facts(facts)\n"
        '        checks_block = ""',
    ),
    (
        "analyzer: пробелы из проверок теряются в data_gaps",
        "app/services/analyzer.py",
        '            + site_signals.signal_gaps(facts.get("signals"))',
        "            + []",
    ),
    (
        "analyzer: раздел проверок не попадает в отчёт",
        "app/services/analyzer.py",
        '            checks = site_signals.build_site_checks(facts.get("signals"))\n'
        '            if checks["rows"]:',
        '            checks = site_signals.build_site_checks(facts.get("signals"))\n'
        "            if False:",
    ),
    (
        "analyzer: внутренние страницы не проверяются по разметке",
        "app/services/analyzer.py",
        '            facts["signals"] = site_signals.merge_signals(\n'
        "                facts.get(\"signals\"), site_signals.scan_page(extra_html)\n"
        "            )",
        '            facts["signals"] = facts.get("signals") or site_signals.empty_signals()',
    ),
    (
        "analyzer: раздел проверок выпал из порядка чтения",
        "app/services/analyzer.py",
        '    "site_gaps",\n    "site_score",\n    "site_checks",\n',
        '    "site_gaps",\n    "site_score",\n',
    ),
    (
        "pdf: раздел проверок вышел в PDF сырым ключом",
        "app/services/pdf_report.py",
        '        "site_checks": "Проверки по разметке сайта (посчитано кодом)",',
        "",
    ),
    # --- Инфраструктура: вывод рождается из кода ответа, а не из догадки -----
    (
        "infra: молчание сервера сравнялось с «файла нет»",
        "app/services/site_infra.py",
        '    if not status:\n        return "unreachable"',
        '    if not status:\n        return "absent"',
    ),
    (
        "infra: незакрытый редирект засчитан прочитанным файлом",
        "app/services/site_infra.py",
        '        # Незакрытый редирект: файл мы не прочитали, но сказать «404» было бы враньём.\n        return "error"',
        '        # Незакрытый редирект: файл мы не прочитали, но сказать «404» было бы враньём.\n        return "ok"',
    ),
    (
        "infra: html-страница на месте sitemap объявлена картой",
        "app/services/site_infra.py",
        '        out["state"] = "foreign"',
        '        out["state"] = "ok"',
    ),
    (
        "infra: индекс карт назван картой страниц",
        "app/services/site_infra.py",
        '    elif out["nested"] == len(locs) and len(locs) > 1:',
        "    elif False:",
    ),
    (
        "infra: чужие хосты в карте не считаются",
        "app/services/site_infra.py",
        '    base_host = (urlparse(origin).netloc or "").lower()',
        '    base_host = ""',
    ),
    (
        "infra: отказ HEAD не перепроверяется GET",
        "app/services/site_infra.py",
        "        if status in (405, 501) or not status:",
        "        if not status:",
    ),
    (
        "infra: редирект ссылки потерян",
        "app/services/site_infra.py",
        "        elif chain:",
        "        elif False:",
    ),
    (
        "infra: бюджет времени пробы выключен",
        "app/services/site_infra.py",
        "        if clock() - started > budget:",
        "        if False:",
    ),
    (
        "infra: число проверяемых ссылок не ограничено",
        "app/services/site_infra.py",
        "    for url in links[:MAX_LINK_CHECKS]:",
        "    for url in links:",
    ),
    (
        "infra: говорящий ответ затёрт простым 404 на запасном пути",
        "app/services/site_infra.py",
        '        if chosen is None or (chosen["state"] == "absent" and sitemap["state"] != "absent"):',
        "        if chosen is None:",
    ),
    (
        "infra: типовые пути карты не проверяются",
        "app/services/site_infra.py",
        "    for path in SITEMAP_FALLBACKS:",
        "    for path in ():",
    ),
    (
        "infra: «карты нет» без перечисления проверенных путей",
        "app/services/site_infra.py",
        "        if probed:",
        "        if False:",
    ),
    (
        "infra: адрес найденной карты скрыт от модели",
        "app/services/site_infra.py",
        '    if state in ("ok", "index") and sitemap.get("url"):',
        "    if False:",
    ),
    (
        "infra: редиректы ссылок исчезли из таблицы",
        "app/services/site_infra.py",
        "        for item in redirected[:2]:",
        "        for item in []:",
    ),
    (
        "infra: «проверять нечего» и «сервер молчит» — один вывод",
        "app/services/site_infra.py",
        '            "внутренних ссылок не найдено" if not found else "проверить не удалось",',
        '            "проверить не удалось" if not found else "внутренних ссылок не найдено",',
    ),
    (
        "infra: редирект перестал быть поводом проверить",
        "app/services/site_infra.py",
        '        row("Внутренние ссылки", seen, BAD if broken else CHECK if redirected else OK,',
        '        row("Внутренние ссылки", seen, BAD if broken else OK,',
    ),
    (
        "infra: не завершившаяся проба притворилась проверкой",
        "app/services/site_infra.py",
        "    rows: List[List[str]] = []\n    if infra.get(\"failed\"):",
        "    rows: List[List[str]] = []\n    if False:",
    ),
    (
        "infra: сбой пробы пропал из честного блока",
        "app/services/site_infra.py",
        "    if infra.get(\"failed\"):\n        return [\n",
        "    if False:\n        return [\n",
    ),
    (
        "infra: отсутствие пробы породило выводы ни о чём",
        "app/services/site_infra.py",
        "def infra_gaps(infra: Dict) -> List[str]:\n    \"\"\"Чего нельзя утверждать по ответам сервера — честно списком.\"\"\"\n    if not infra:",
        "def infra_gaps(infra: Dict) -> List[str]:\n    \"\"\"Чего нельзя утверждать по ответам сервера — честно списком.\"\"\"\n    if False:",
    ),
    (
        "infra: претензия к карте сайта исчезла из честного блока",
        "app/services/site_infra.py",
        '    if (infra.get("sitemap") or {}).get("state") not in ("ok", "index"):',
        "    if False:",
    ),
    # --- Инфраструктура в анализаторе и отчёте ---------------------------
    (
        "analyzer: ответы сервера не дошли до промптов",
        "app/services/analyzer.py",
        '        infra = facts.get("infra") or {}\n'
        "        if infra and not infra.get(\"failed\"):\n"
        "            blocks.append(site_infra.render_infra(infra))",
        "        infra = {}",
    ),
    (
        "analyzer: сбой инфраструктуры потерялся в data_gaps",
        "app/services/analyzer.py",
        '            + site_infra.infra_gaps(facts.get("infra"))',
        "            + []",
    ),
    (
        "analyzer: раздел инфраструктуры не попадает в отчёт",
        "app/services/analyzer.py",
        '            infra_checks = site_infra.build_infra_checks(infra) if infra else {"rows": []}\n'
        '            if infra_checks["rows"]:',
        '            infra_checks = site_infra.build_infra_checks(infra) if infra else {"rows": []}\n'
        "            if False:",
    ),
    (
        "analyzer: раздел инфраструктуры выпал из порядка чтения",
        "app/services/analyzer.py",
        '    "site_checks",\n    "site_infra",\n',
        '    "site_checks",\n',
    ),
    (
        "analyzer: относительная ссылка проверяется не там, где живёт",
        "app/services/analyzer.py",
        "                absolute = urldefrag(urljoin(home, href)).url",
        "                absolute = urldefrag(urljoin(base_url, href)).url",
    ),
    (
        "analyzer: чужие ссылки уходят в пробу",
        "app/services/analyzer.py",
        "                absolute = urldefrag(urljoin(home, href)).url\n"
        "                parsed = urlparse(absolute)\n"
        '                if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != base_netloc:',
        "                absolute = urldefrag(urljoin(home, href)).url\n"
        "                parsed = urlparse(absolute)\n"
        '                if parsed.scheme not in ("http", "https"):',
    ),
    (
        "analyzer: прочитанные страницы перепроверяются зондом",
        "app/services/analyzer.py",
        "        seen = {site_crawl.norm(url) for url in skip if url}",
        "        seen = set()",
    ),
    (
        "analyzer: ссылки для пробы не собираются",
        "app/services/analyzer.py",
        "        links = self.internal_links(\n"
        "            url, pages_html, list(policy.pages), site_infra.MAX_LINK_CHECKS\n"
        "        )",
        "        links = []",
    ),
    (
        "analyzer: редиректы разворачивает requests, а не зонд",
        "app/services/analyzer.py",
        "                    allow_redirects=False,",
        "                    allow_redirects=True,",
    ),
    (
        "analyzer: шаг редиректа не проверяется на внутренний адрес",
        "app/services/analyzer.py",
        "                    current = self._validate_url(target)",
        "                    current = target",
    ),
    (
        "analyzer: HEAD принёс тело страницы в проверку",
        "app/services/analyzer.py",
        '                    body = response.text if method.upper() == "GET" else ""',
        "                    body = response.text",
    ),
    (
        "analyzer: мёртвый адрес роняет весь аудит",
        "app/services/analyzer.py",
        '            return {"status": 0, "text": "", "chain": chain, "url": current or url}',
        "            raise",
    ),
    (
        "pdf: раздел инфраструктуры вышел в PDF сырым ключом",
        "app/services/pdf_report.py",
        '        "site_infra": "Инфраструктура сайта: robots, sitemap, ссылки (посчитано кодом)",',
        "",
    ),
    # --- Глубина обхода: читает много, модели отдаёт новое ------------------
    (
        "crawl: адрес считается с якорем — одна страница становится двумя",
        "app/services/site_crawl.py",
        '    return urldefrag(str(url or "")).url.rstrip("/").lower()',
        '    return str(url or "").rstrip("/").lower()',
    ),
    (
        "crawl: регистр домена делит страницу надвое",
        "app/services/site_crawl.py",
        '    return urldefrag(str(url or "")).url.rstrip("/").lower()',
        '    return urldefrag(str(url or "")).url.rstrip("/")',
    ),
    (
        "crawl: раздел берётся из последнего сегмента пути",
        "app/services/site_crawl.py",
        '    return (urlparse(url).path.strip("/").split("/") or [""])[0].lower()',
        '    return (urlparse(url).path.strip("/").split("/") or [""])[-1].lower()',
    ),
    (
        "crawl: пагинация Bitrix не распознана (PAGEN_N — другой листинг)",
        "app/services/site_crawl.py",
        "        if low in PAGE_PARAMS or PAGE_NUMBER.match(low):",
        "        if low in PAGE_PARAMS:",
    ),
    (
        "crawl: страницы в пути (/page/2/) не распознаны",
        "app/services/site_crawl.py",
        "    match = PAGED_PATH.search(path)",
        "    match = None",
    ),
    (
        "crawl: сортировка и фильтр объявлены новым листингом",
        "app/services/site_crawl.py",
        '    base = f"{parsed.netloc.lower()}{path.rstrip(\'/\')}"',
        '    base = f"{parsed.netloc.lower()}{path.rstrip(\'/\')}{parsed.query}"',
    ),
    (
        "crawl: цифры не различают содержание (второй прайс стал дублем)",
        "app/services/site_crawl.py",
        'WORD = re.compile(r"[а-яёa-z]{3,}|\\d{2,}", re.I)',
        'WORD = re.compile(r"[а-яёa-z]{3,}", re.I)',
    ),
    (
        "crawl: шапка в другом регистре посчитана новым содержанием",
        "app/services/site_crawl.py",
        '    return set(WORD.findall(str(text or "").lower()))',
        '    return set(WORD.findall(str(text or "")))',
    ),
    (
        "crawl: отпечаток зависит от порядка слов",
        "app/services/site_crawl.py",
        '    return hashlib.sha1(" ".join(words).encode("utf-8")).hexdigest()[:16]',
        '    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:16]',
    ),
    (
        "crawl: пустая страница получила отпечаток и стала дублем сама себя",
        "app/services/site_crawl.py",
        '    if not words:\n        return ""',
        '    if not words:\n        return "пусто"',
    ),
    (
        "crawl: отказ по времени не проверяется до запроса",
        "app/services/site_crawl.py",
        '        if self.time_left() <= 0:\n            return "time"',
        '        if False:\n            return "time"',
    ),
    (
        "crawl: потолок страниц не проверяется до запроса",
        "app/services/site_crawl.py",
        '        if len(self.pages) >= self.max_pages:\n            return "budget"',
        '        if False:\n            return "budget"',
    ),
    (
        "crawl: потолок раздела выключен",
        "app/services/site_crawl.py",
        "        if section and self._count(section=section) >= self.max_per_section:",
        "        if False:",
    ),
    (
        "crawl: потолок глубины листинга выключен",
        "app/services/site_crawl.py",
        "        if group and self._count(group=group) >= self.max_per_group:",
        "        if False:",
    ),
    (
        "crawl: остановка обхода не названа",
        "app/services/site_crawl.py",
        '        if reason in ("time", "budget") and not self.stopped:',
        "        if False:",
    ),
    (
        "crawl: обход не помнит потолок страниц",
        "app/services/site_crawl.py",
        "        return self.time_left() > 0 and len(self.pages) < self.max_pages",
        "        return self.time_left() > 0",
    ),
    (
        "crawl: отказавшие ссылки идут первыми в очереди",
        "app/services/site_crawl.py",
        '        if self.reason_for(url):\n            return 3',
        '        if self.reason_for(url):\n            return 0',
    ),
    (
        "crawl: новый раздел не важнее карточки",
        "app/services/site_crawl.py",
        "        if section and not self._count(section=section):\n            return 0",
        "        if section and not self._count(section=section):\n            return 2",
    ),
    (
        "crawl: порядок очереди = порядок ссылок в HTML",
        "app/services/site_crawl.py",
        "            (self.bucket_of(link), pagination_of(link)[1], index, link)",
        "            (0, pagination_of(link)[1], index, link)",
    ),
    (
        "crawl: страницы листинга идут в порядке ссылки, а не номера",
        "app/services/site_crawl.py",
        "            (self.bucket_of(link), pagination_of(link)[1], index, link)",
        "            (self.bucket_of(link), 0, index, link)",
    ),
    (
        "crawl: очередь не сортируется",
        "app/services/site_crawl.py",
        "        return [item[3] for item in sorted(decorated)]",
        "        return [item[3] for item in decorated]",
    ),
    (
        "crawl: непройденные ссылки очереди потеряны",
        "app/services/site_crawl.py",
        "        self.pending = max(0, int(pending))",
        "        self.pending = 0",
    ),
    (
        "crawl: нехватка времени названа потолком страниц",
        "app/services/site_crawl.py",
        '        if self.time_left() <= 0:\n            reason = "time"',
        '        if self.time_left() <= 0:\n            reason = "budget"',
    ),
    (
        "crawl: повторная страница прочитана второй раз",
        "app/services/site_crawl.py",
        '        if key in self.pages:\n            return "repeat"',
        '        if False:\n            return "repeat"',
    ),
    (
        "crawl: порог текста выключен",
        "app/services/site_crawl.py",
        "        if chars < self.min_chars and not root:",
        "        if False:",
    ),
    (
        "crawl: тонкая главная не запускает обход",
        "app/services/site_crawl.py",
        "        if chars < self.min_chars and not root:",
        "        if chars < self.min_chars:",
    ),
    (
        "crawl: тот же текст под другим адресом прочитан как новый",
        "app/services/site_crawl.py",
        "        if sign and same_as:",
        "        if False:",
    ),
    (
        "crawl: дубль записан без адреса-оригинала",
        "app/services/site_crawl.py",
        '            self.duplicates.append({"url": key, "same_as": same_as})',
        '            self.duplicates.append({"url": key, "same_as": ""})',
    ),
    (
        "crawl: новизна страницы измерена после её же лексикона",
        "app/services/site_crawl.py",
        '            "novelty": fresh,',
        '            "novelty": 0.0,',
    ),
    (
        "crawl: вложенность страницы не записана",
        "app/services/site_crawl.py",
        '            "depth": len([part for part in urlparse(url).path.split("/") if part]),',
        '            "depth": 0,',
    ),
    (
        "crawl: лексикон не пополняется — каждая страница «новая»",
        "app/services/site_crawl.py",
        "        self.lexicon |= words_of(text)",
        "        pass",
    ),
    (
        "crawl: в текст модели идёт всё, что прочитано",
        "app/services/site_crawl.py",
        '        return bool(page) and page["novelty"] >= self.novelty_floor',
        "        return bool(page)",
    ),
    (
        "crawl: страница, которая не открылась, не находка",
        "app/services/site_crawl.py",
        '        self.failures.append({"url": norm(url), "reason": (str(reason or "")[:120])})',
        "        pass",
    ),
    (
        "crawl: число цитат выдано за число прочитанного",
        "app/services/site_crawl.py",
        '            "text_pages": int(quoted),',
        '            "text_pages": len(self.pages),',
    ),
    (
        "crawl: остаток очереди не попал в итог",
        "app/services/site_crawl.py",
        '            "pending": self.pending,',
        '            "pending": 0,',
    ),
    (
        "crawl: глубина вложенности подменена числом страниц",
        "app/services/site_crawl.py",
        '            "depth": max((page["depth"] for page in self.pages.values()), default=0),',
        '            "depth": len(self.pages),',
    ),
    (
        "crawl: таблица выводов там, где обход не делал ничего",
        "app/services/site_crawl.py",
        '    if not crawl:\n        return {"columns": [], "rows": []}',
        '    if False:\n        return {"columns": [], "rows": []}',
    ),
    (
        "crawl: таблица не различает прочитанное и процитированное",
        "app/services/site_crawl.py",
        '    if quoted and quoted < pages:\n        cell += f", в текст анализа вошло {quoted}"',
        '    if False:\n        cell += f", в текст анализа вошло {quoted}"',
    ),
    (
        "crawl: одна главная страница объявлена достаточной выборкой",
        "app/services/site_crawl.py",
        "        OK if pages >= 3 else CHECK,",
        "        OK,",
    ),
    (
        "crawl: хвост очереди скрыт из строки полноты",
        "app/services/site_crawl.py",
        '        if pending:\n            parts.append(f"ссылок осталось непроверенными: {pending}")',
        '        if False:\n            parts.append(f"ссылок осталось непроверенными: {pending}")',
    ),
    (
        "crawl: дубликаты содержания — норма",
        "app/services/site_crawl.py",
        "        CHECK if duplicates else OK,",
        "        OK,",
    ),
    (
        "crawl: дубликат назван без адресов",
        "app/services/site_crawl.py",
        '        duplicates[0]["url"] + " совпадает с " + duplicates[0]["same_as"] if duplicates else',
        '        "страницы совпадают по тексту" if duplicates else',
    ),
    (
        "crawl: мёртвая страница не ошибка",
        "app/services/site_crawl.py",
        "            BAD,",
        "            OK,",
    ),
    (
        "crawl: страницы без текста выпали из таблицы",
        "app/services/site_crawl.py",
        '    if refused.get("thin"):',
        "    if False:",
    ),
    (
        "crawl: остановка обхода пропала из честного блока",
        "app/services/site_crawl.py",
        '        if crawl.get("stopped"):\n            detail = f" {crawl[\'stopped\']}"',
        '        if False:\n            detail = f" {crawl[\'stopped\']}"',
    ),
    (
        "crawl: непройденные ссылки пропали из честного блока",
        "app/services/site_crawl.py",
        '            if pending:\n                detail += f", непроверенных ссылок осталось: {pending}"',
        '            if False:\n                detail += f", непроверенных ссылок осталось: {pending}"',
    ),
    (
        "crawl: неполный раздел не назван пробелом",
        "app/services/site_crawl.py",
        '        if int(crawl.get("refused", {}).get("section", 0)):',
        "        if False:",
    ),
    (
        "crawl: блок промпта сочиняется на пустом обходе",
        "app/services/site_crawl.py",
        '    if not crawl:\n        return ""',
        '    if False:\n        return ""',
    ),
    (
        "crawl: модель не знает, что цитат меньше прочитанного",
        "app/services/site_crawl.py",
        "    if quoted and quoted < pages:\n        lines.append(",
        "    if False:\n        lines.append(",
    ),
    (
        "crawl: дубли адресов скрыты от модели",
        "app/services/site_crawl.py",
        '    if duplicates:\n        lines.append(',
        '    if False:\n        lines.append(',
    ),
    (
        "crawl: не открывшиеся страницы скрыты от модели",
        "app/services/site_crawl.py",
        '    if failures:\n        lines.append("Не открылись: "',
        '    if False:\n        lines.append("Не открылись: "',
    ),
    (
        "crawl: модель не знает, где обход остановился",
        "app/services/site_crawl.py",
        '    if crawl.get("stopped"):\n        lines.append(f"Обход остановлен: {crawl[\'stopped\']} — ниже по списку ссылки не проверены")',
        '    if False:\n        lines.append(f"Обход остановлен: {crawl[\'stopped\']} — ниже по списку ссылки не проверены")',
    ),
    (
        "crawl: охват выдаёт процитированное за прочитанное",
        "app/services/site_crawl.py",
        "    if read <= quoted:",
        "    if True:",
    ),
    (
        "crawl: охват не говорит, сколько вошло в текст",
        "app/services/site_crawl.py",
        '        f"в текст анализа вошло {quoted}: остальные повторяли уже прочитанное, "',
        '        f"прочитанное повторяло уже изложенное, "',
    ),
    (
        "crawl: потолок страниц обхода стал единичным",
        "app/services/site_crawl.py",
        "MAX_CRAWL_PAGES = 18",
        "MAX_CRAWL_PAGES = 1",
    ),
    (
        "crawl: потолок страниц раздела выключен",
        "app/services/site_crawl.py",
        "MAX_PAGES_PER_SECTION = 4",
        "MAX_PAGES_PER_SECTION = 20",
    ),
    (
        "crawl: потолок глубины листинга выключен в константе",
        "app/services/site_crawl.py",
        "MAX_PAGES_PER_GROUP = 3",
        "MAX_PAGES_PER_GROUP = 20",
    ),
    (
        "crawl: со страницы берут шесть ссылок — пагинация не видна",
        "app/services/site_crawl.py",
        "MAX_NEW_LINKS_PER_PAGE = 40",
        "MAX_NEW_LINKS_PER_PAGE = 6",
    ),
    (
        "crawl: кандидатов берут ровно потолок — хвост исчезает молча",
        "app/services/site_crawl.py",
        "MAX_CANDIDATE_LINKS = 60",
        "MAX_CANDIDATE_LINKS = MAX_CRAWL_PAGES",
    ),
    (
        "crawl: времени на обход не осталось",
        "app/services/site_crawl.py",
        "CRAWL_BUDGET_SECONDS = 50.0",
        "CRAWL_BUDGET_SECONDS = 0.0",
    ),
    (
        "crawl: порог новизны нулевой",
        "app/services/site_crawl.py",
        "NOVELTY_FOR_TEXT = 0.12",
        "NOVELTY_FOR_TEXT = 0.0",
    ),
    (
        "crawl: порог осмысленного текста нулевой",
        "app/services/site_crawl.py",
        "MIN_PAGE_CHARS = 120",
        "MIN_PAGE_CHARS = 0",
    ),
    (
        "crawl: слово вывода разошлось с остальными таблицами",
        "app/services/site_crawl.py",
        'OK = "норма"',
        'OK = "ok"',
    ),
    (
        "crawl: файл признан страницей",
        "app/services/site_crawl.py",
        "    return path.endswith(FILE_EXTENSIONS)",
        "    return False",
    ),
    (
        "crawl: расширение проверено по всему адресу, а не по пути",
        "app/services/site_crawl.py",
        '    path = (urlparse(str(url or "")).path or "").lower()',
        '    path = str(url or "").lower()',
    ),
    (
        "crawl: из файлов признаны только PDF",
        "app/services/site_crawl.py",
        "    return path.endswith(FILE_EXTENSIONS)",
        '    return path.endswith((".pdf",))',
    ),
    (
        "crawl: образцы файлов не сохраняются",
        "app/services/site_crawl.py",
        "FILE_SAMPLES = 3",
        "FILE_SAMPLES = 0",
    ),
    (
        "crawl: intake не отбирает файлы из ссылок",
        "app/services/site_crawl.py",
        "            if is_file(link):",
        "            if False:",
    ),
    (
        "crawl: файл остался в списке страниц после учёта",
        "app/services/site_crawl.py",
        "                self.note_file(link)\n                continue\n            pages.append(link)",
        "                self.note_file(link)\n            pages.append(link)",
    ),
    (
        "crawl: один файл посчитан с каждого меню",
        "app/services/site_crawl.py",
        "        if key in self._file_keys:\n            return",
        "        if False:\n            return",
    ),
    (
        "crawl: файлы не посчитаны в итоге",
        "app/services/site_crawl.py",
        "        self.file_total += 1",
        "        pass",
    ),
    (
        "crawl: сводка не знает числа файлов",
        "app/services/site_crawl.py",
        '            "files": self.file_total,',
        '            "files": 0,',
    ),
    (
        "crawl: сводка не помнит имён файлов",
        "app/services/site_crawl.py",
        '            "file_samples": list(self.files),',
        '            "file_samples": [],',
    ),
    (
        "crawl: строка о файлах не выходит в таблицу",
        "app/services/site_crawl.py",
        '    files = int(crawl.get("files") or 0)\n    if files:',
        '    files = int(crawl.get("files") or 0)\n    if False:',
    ),
    (
        "crawl: какие файлы пропущены — клиенту не сказано",
        "app/services/site_crawl.py",
        'f", например {names}" if names else ""',
        '""',
    ),
    (
        "crawl: модель не знает, что файлы не читались",
        "app/services/site_crawl.py",
        '        f"Дубликатов содержания: {len(duplicates)}; не открылось страниц: {len(failures)}; "\n'
        '        f"файлов по ссылкам вместо страниц: {int(crawl.get(\'files\') or 0)}",',
        '        f"Дубликатов содержания: {len(duplicates)}; не открылось страниц: {len(failures)}",',
    ),
    (
        "crawl: доля бюджета на раздел выключена",
        "app/services/site_crawl.py",
        "MAX_SECTION_SHARE = 0.5",
        "MAX_SECTION_SHARE = 0.0",
    ),
    (
        "crawl: раздел получил весь бюджет обхода",
        "app/services/site_crawl.py",
        "MAX_SECTION_SHARE = 0.5",
        "MAX_SECTION_SHARE = 2.0",
    ),
    (
        "crawl: короткий бюджет отдан одному разделу",
        "app/services/site_crawl.py",
        "    return int(max(MAX_PAGES_PER_SECTION, min(share, budget)))",
        "    return int(max(1, min(share, budget)))",
    ),
    (
        "crawl: потолок раздела не зависит от бюджета обхода",
        "app/services/site_crawl.py",
        "            int(max_per_section) if max_per_section is not None else section_allowance(max_pages)",
        "            int(max_per_section) if max_per_section is not None else MAX_PAGES_PER_SECTION",
    ),
    (
        "crawl: явный потолок раздела перезаписан расчётом",
        "app/services/site_crawl.py",
        "            int(max_per_section) if max_per_section is not None else section_allowance(max_pages)",
        "            section_allowance(max_pages)",
    ),
    (
        "crawl: недочитанный раздел не попал в таблицу",
        "app/services/site_crawl.py",
        "    if stopped or pending or section_skipped or refused.get(\"budget\") or refused.get(\"time\"):",
        "    if stopped or pending or refused.get(\"budget\") or refused.get(\"time\"):",
    ),
    (
        "crawl: сколько страниц раздела не читали — не сказано",
        "app/services/site_crawl.py",
        '        if section_skipped:\n            parts.append(f"в разделах прочитано не всё: {section_skipped}")',
        "        if section_skipped:\n            pass",
    ),
    (
        "crawl: настоящая причина недосмотра подменена потолком страниц",
        "app/services/site_crawl.py",
        "        if stopped:\n            parts.append(stopped)",
        "        if False:\n            parts.append(stopped)",
    ),
    (
        "crawl: опустевшая очередь объявлена потолком страниц",
        "app/services/site_crawl.py",
        '        elif refused.get("budget") or refused.get("time"):\n            parts.append("достигнут потолок страниц обхода")',
        '        else:\n            parts.append("достигнут потолок страниц обхода")',
    ),
    (
        "crawl: модель не знает о недочитанном разделе",
        "app/services/site_crawl.py",
        '            f"Из раздела прочитаны не все страницы (отклонено ссылок: {section_skipped}): "',
        '            ""',
    ),
    # --- Обход в составе анализа и отчёта ------------------------------------
    (
        "analyzer: главная вошла в обход без права на тонкий текст",
        "app/services/analyzer.py",
        "        policy.take(url, content, root=True)",
        "        policy.take(url, content)",
    ),
    (
        "analyzer: кандидатов с главной берут ровно потолок обхода",
        "app/services/analyzer.py",
        "            limit=site_crawl.MAX_CANDIDATE_LINKS,",
        "            limit=site_crawl.MAX_CRAWL_PAGES,",
    ),
    (
        "analyzer: с главной берут по одной ссылке раздела",
        "app/services/analyzer.py",
        "            per_section=policy.max_per_section,",
        "            per_section=1,",
    ),
    (
        "analyzer: кандидатов с главной режет жёсткая четвёрка",
        "app/services/analyzer.py",
        "            per_section=policy.max_per_section,",
        "            per_section=site_crawl.MAX_PAGES_PER_SECTION,",
    ),
    (
        "analyzer: очередь не пересортирована после прочитанной страницы",
        "app/services/analyzer.py",
        "            if added:\n                queue = policy.rank(queue)",
        "            if False:\n                queue = policy.rank(queue)",
    ),
    (
        "analyzer: ссылки внутренней страницы не расширяют обход",
        "app/services/analyzer.py",
        "            for deeper in policy.intake(fresh):\n"
        "                queue.append(deeper)\n"
        "                added = True",
        "            for deeper in policy.intake(fresh):\n"
        "                pass",
    ),
    (
        "analyzer: файл с внутренней страницы качается как страница",
        "app/services/analyzer.py",
        "            for deeper in policy.intake(fresh):",
        "            for deeper in fresh:",
    ),
    (
        "analyzer: файл с главной качается как страница",
        "app/services/analyzer.py",
        "        queue: List[str] = policy.rank(policy.intake(candidates))",
        "        queue: List[str] = policy.rank(candidates)",
    ),
    (
        "analyzer: найденные ссылки не помечены известными",
        "app/services/analyzer.py",
        "            known.update(site_crawl.norm(deeper) for deeper in fresh)",
        "            pass",
    ),
    (
        "analyzer: известные ссылки не помнят кандидатов с главной",
        "app/services/analyzer.py",
        "        known = {site_crawl.norm(link) for link in [url, *candidates]}",
        "        known = {site_crawl.norm(link) for link in [url]}",
    ),
    (
        "analyzer: не открывшаяся страница пропала без следа",
        "app/services/analyzer.py",
        "                policy.note_failure(link, str(exc))",
        "                pass",
    ),
    (
        "analyzer: хвост очереди не посчитан",
        "app/services/analyzer.py",
        "        policy.leftover(len(queue))",
        "        policy.leftover(0)",
    ),
    (
        "analyzer: итог обхода не знает числа цитат",
        "app/services/analyzer.py",
        '        facts["crawl"] = policy.summary(quoted=len(sources))',
        '        facts["crawl"] = policy.summary()',
    ),
    (
        "analyzer: глубина обхода не дошла до промптов",
        "app/services/analyzer.py",
        '        if crawl.get("pages"):\n            blocks.append(site_crawl.render_crawl(crawl))',
        '        if False:\n            blocks.append(site_crawl.render_crawl(crawl))',
    ),
    (
        "analyzer: пробелы обхода теряются в data_gaps",
        "app/services/analyzer.py",
        '            + site_crawl.crawl_gaps(facts.get("crawl"))',
        "            + []",
    ),
    (
        "analyzer: раздел глубины обхода не попадает в отчёт",
        "app/services/analyzer.py",
        '            crawl_checks = site_crawl.build_crawl_checks(facts.get("crawl"))\n'
        '            if crawl_checks["rows"]:',
        '            crawl_checks = site_crawl.build_crawl_checks(facts.get("crawl"))\n'
        "            if False:",
    ),
    (
        "analyzer: раздел обхода выпал из порядка чтения",
        "app/services/analyzer.py",
        '    "site_infra",\n    "site_crawl",\n',
        '    "site_infra",\n',
    ),
    (
        "analyzer: охват сайта снова считает цитаты прочитанным",
        "app/services/analyzer.py",
        "            site_crawl.describe_pages(sources or [], (facts or {}).get(\"crawl\") or {}),",
        '            f"Прочитано страниц: {len(sources or [])}.",',
    ),
    (
        "analyzer: ссылка пагинации отброшена как якорь",
        "app/services/analyzer.py",
        '                if not href or href.startswith(("#", "tel:", "mailto:", "javascript:", "data:")):',
        '                if not href or href.startswith(("#", "?", "tel:", "mailto:", "javascript:", "data:")):',
    ),
    (
        "analyzer: потолок цитат для модели выключен",
        "app/services/analyzer.py",
        "MAX_QUOTED_PAGES = 6",
        "MAX_QUOTED_PAGES = 20",
    ),
    (
        "analyzer: страница идёт в текст без проверки потолка цитат",
        "app/services/analyzer.py",
        "            if len(sources) <= MAX_QUOTED_PAGES and policy.goes_to_text(link):",
        "            if policy.goes_to_text(link):",
    ),
    (
        "analyzer: вывод о непрочитанном не ограничен в промпте",
        "app/services/analyzer.py",
        '            "Если обход остановлен или часть ссылок не проверена — не пиши «на сайте нет X» "\n'
        '            "про то, чего обход не касался: формулируй это как что проверить, а не как вывод по сайту. "',
        '            ""',
    ),
    (
        "pdf: раздел глубины обхода вышел в PDF сырым ключом",
        "app/services/pdf_report.py",
        '        "site_crawl": "Глубина обхода сайта (посчитано кодом)",',
        "",
    ),
    # --- Скорость: замеры свои, PSI чужие и «как получится» -----------------
    (
        "speed: скрипт в теле страницы записан блокирующим",
        "app/services/site_speed.py",
        '    blocking = [\n        tag for tag in in_head',
        '    blocking = [\n        tag for tag in scripts',
    ),
    (
        "speed: defer и async не снимают блокировку отрисовки",
        "app/services/site_speed.py",
        '        return "async" in attrs or "defer" in attrs',
        "        return False",
    ),
    (
        "speed: свой хост записан чужим подключением",
        "app/services/site_speed.py",
        '        return bool(netloc) and netloc != host and not netloc.endswith("." + host)',
        "        return bool(netloc)",
    ),
    (
        "speed: блокировка зума замечена только в user-scalable",
        "app/services/site_speed.py",
        'VIEWPORT_LOCK = re.compile(r"(user-scalable\\s*=\\s*no|maximum-scale\\s*=\\s*1(\\.0)?\\b)", re.I)',
        'VIEWPORT_LOCK = re.compile(r"(user-scalable\\s*=\\s*no)", re.I)',
    ),
    (
        "speed: размеры картинок не сверяются с разметкой",
        "app/services/site_speed.py",
        '        return not (str(tag.get("width") or "").strip() and str(tag.get("height") or "").strip())',
        "        return True",
    ),
    (
        "speed: ленивая загрузка приписана всем картинкам",
        "app/services/site_speed.py",
        '        "images_lazy": sum(1 for tag in images if (tag.get("loading") or "").lower() == "lazy"),',
        '        "images_lazy": len(images),',
    ),
    (
        "speed: обычный src принят за набор размеров",
        "app/services/site_speed.py",
        '        return bool((tag.get("srcset") or tag.get("data-srcset") or "").strip())',
        '        return bool(str(tag.get("src") or "").strip())',
    ),
    (
        "speed: webp и avif не опознаны как облегчённые форматы",
        "app/services/site_speed.py",
        'MODERN_IMAGE = re.compile(r"\\.(webp|avif)(\\?|#|$)", re.I)',
        'MODERN_IMAGE = re.compile(r"\\.(gif|svg)(\\?|#|$)", re.I)',
    ),
    (
        "speed: пустой ответ засчитан прочитанной страницей",
        "app/services/site_speed.py",
        '    raw = str(html or "")\n    if not raw.strip():\n        return out',
        '    raw = str(html or "")\n    if False:\n        return out',
    ),
    (
        "speed: предзагрузка перестала быть предзагрузкой шрифта",
        "app/services/site_speed.py",
        '    preload = [tag for tag in links if "preload" in rel_of(tag)]',
        "    preload = []",
    ),
    (
        "speed: узлы DOM не посчитаны",
        "app/services/site_speed.py",
        '        "dom_nodes": len(soup.find_all()),',
        '        "dom_nodes": 0,',
    ),
    (
        "speed: потолок тяжёлого дерева отключён",
        "app/services/site_speed.py",
        "DOM_BAD_NODES = 1_500",
        "DOM_BAD_NODES = 100_000",
    ),
    (
        "speed: относительный адрес ресурса не превращён в путь сайта",
        "app/services/site_speed.py",
        '    return urljoin(base, str(href or "").strip())',
        '    return str(href or "").strip()',
    ),
    (
        "speed: незамеренная главная объявлена замеренной",
        "app/services/site_speed.py",
        "    measured = bool(probe.get(\"status\")) and bool(\n"
        "        probe.get(\"ttfb_ms\") or probe.get(\"content_bytes\")\n"
        "    )",
        "    measured = True",
    ),
    (
        "speed: тип контента не отделён от кодировки",
        "app/services/site_speed.py",
        '    content_type = (headers.get("content-type") or "").split(";")[0].strip()',
        '    content_type = (headers.get("content-type") or "").strip()',
    ),
    (
        "speed: объявленная кодировка страницы не увиденна",
        "app/services/site_speed.py",
        '        "charset": "utf-8" in (headers.get("content-type") or "").lower(),',
        '        "charset": False,',
    ),
    (
        "speed: финальный адрес редиректа потерян",
        "app/services/site_speed.py",
        '        "final_path": urlparse(probe.get("final_url") or "").path or "",',
        '        "final_path": "",',
    ),
    (
        "speed: редирект перестал быть поводом проверить",
        "app/services/site_speed.py",
        "            CHECK if hops else OK,",
        "            OK,",
    ),
    (
        "speed: число шагов редиректа пишут и когда их нет",
        "app/services/site_speed.py",
        '            f"{hops} шага, финальный адрес: {final}" if hops else "сразу 200",',
        '            f"{hops} шага, финальный адрес: {final}",',
    ),
    (
        "speed: HTTP/1.1 объявлен мультиплексированием",
        "app/services/site_speed.py",
        '            modern = version.replace("HTTP/", "").rstrip(".0") in ("2", "3")',
        "            modern = True",
    ),
    (
        "speed: протокол выводят, даже когда его не измерили",
        "app/services/site_speed.py",
        '        version = page.get("http_version") or ""\n        if version:',
        '        version = page.get("http_version") or ""\n        if True:',
    ),
    (
        "speed: кэш главной перестал риском устаревания",
        "app/services/site_speed.py",
        '            CHECK if _cache_state(cache, "") == "cached" else OK,',
        "            OK,",
    ),
    (
        "speed: порог медленного сервера сдвинут за разумное",
        "app/services/site_speed.py",
        "TTFB_BAD_MS = 600",
        "TTFB_BAD_MS = 5_000",
    ),
    (
        "speed: потолок веса главной отключён",
        "app/services/site_speed.py",
        "PAGE_OK_BYTES = 250_000",
        "PAGE_OK_BYTES = 50_000_000",
    ),
    (
        "speed: сжатая главная объявлена тяжёлой",
        "app/services/site_speed.py",
        "            BAD if (not encoding and size > PAGE_OK_BYTES)",
        "            BAD if size > PAGE_OK_BYTES",
    ),
    (
        "speed: вес главной оценён только названным весом в сети",
        "app/services/site_speed.py",
        "            else CHECK if basis > PAGE_OK_BYTES else OK,",
        "            else CHECK if wire > PAGE_OK_BYTES else OK,",
    ),
    (
        "speed: незапущенный PSI показан как ответ теста",
        "app/services/site_speed.py",
        '    if state == "ok":\n        score = int(psi.get("score") or 0)',
        '    if True:\n        score = int(psi.get("score") or 0)',
    ),
    (
        "speed: вывод о блокировке противоречит её числу",
        "app/services/site_speed.py",
        '            "белый экран держат не сервер, а эти скрипты" if blocking\n'
        '            else "критический путь загрузки не заблокирован",',
        '            "критический путь загрузки не заблокирован" if blocking\n'
        '            else "белый экран держат не сервер, а эти скрипты",',
    ),
    (
        "speed: россыпь блокирующих скриптов осталась замечанием",
        "app/services/site_speed.py",
        "            OK if not blocking else CHECK if blocking <= 2 else BAD,",
        "            OK if not blocking else CHECK,",
    ),
    (
        "speed: чужие виджеты всегда в норме",
        "app/services/site_speed.py",
        "        level = OK if third <= THIRD_PARTY_OK else CHECK if third <= THIRD_PARTY_BAD else BAD",
        "        level = OK",
    ),
    (
        "speed: норма по чужим хостам обнулена",
        "app/services/site_speed.py",
        "THIRD_PARTY_OK = 3",
        "THIRD_PARTY_OK = 0",
    ),
    (
        "speed: четвёртый iframe перестал быть ошибкой",
        "app/services/site_speed.py",
        "                CHECK if frames <= 3 else BAD,",
        "                CHECK,",
    ),
    (
        "speed: сдвиг макета не зависит от доли картинок без размеров",
        "app/services/site_speed.py",
        "                OK if not no_dims else CHECK if share <= 50 else BAD,",
        "                OK if not no_dims else BAD,",
    ),
    (
        "speed: картинки похвалены без ленивой загрузки и форматов",
        "app/services/site_speed.py",
        "                OK if modern or srcset else CHECK,",
        "                OK,",
    ),
    (
        "speed: шрифт без подсказки объявлен подсказанным",
        "app/services/site_speed.py",
        "                OK if hinted else CHECK,",
        "                OK,",
    ),
    (
        "speed: мобильная строка не различает viewport и запрет зума",
        "app/services/site_speed.py",
        "            OK if markup.get(\"viewport\") and not markup.get(\"zoom_locked\") else CHECK,",
        "            OK if markup.get(\"viewport\") else CHECK,",
    ),
    (
        "speed: объяснение зума противоречит разметке",
        "app/services/site_speed.py",
        '            "мелкий текст нельзя приблизить — заявка теряется на самом интересном"\n'
        "            if markup.get(\"zoom_locked\")",
        '            "телефон знает, что страница под него сверстана"\n'
        "            if markup.get(\"zoom_locked\")",
    ),
    (
        "speed: молчание сервера записано отсутствием файла",
        "app/services/site_speed.py",
        '        if not status:\n            out["unreachable"] += 1\n            continue',
        '        if not status:\n            out["dead"].append({"url": url, "status": status})\n'
        "            continue",
    ),
    (
        "speed: ответ 404 выпал из битых ресурсов",
        "app/services/site_speed.py",
        '        if status >= 400:\n            out["dead"].append({"url": url, "status": status})',
        '        if status >= 500:\n            out["dead"].append({"url": url, "status": status})',
    ),
    (
        "speed: бюджет времени пробы выключен",
        "app/services/site_speed.py",
        "        if clock() - started > budget:",
        "        if False:",
    ),
    (
        "speed: число опробованных ресурсов не считается",
        "app/services/site_speed.py",
        '        status = int(head.get("status") or 0)\n        out["checked"] += 1',
        '        status = int(head.get("status") or 0)',
    ),
    (
        "speed: no-cache разрешён как долгий кэш",
        "app/services/site_speed.py",
        '    if "no-store" in cc or "no-cache" in cc:\n        return "forbidden"',
        '    if "no-store" in cc:\n        return "forbidden"',
    ),
    (
        "speed: минутный кэш сравнен с годовым",
        "app/services/site_speed.py",
        '        return "cached" if seconds >= 60 else "short" if seconds > 0 else "forbidden"',
        '        return "cached"',
    ),
    (
        "speed: прошедшая дата Expires засчитана кэшем",
        "app/services/site_speed.py",
        '    if value and value != "0" and "1970" not in value:',
        '    if value and value != "0":',
    ),
    (
        "speed: чужие ресурсы пробуют раньше своих",
        "app/services/site_speed.py",
        "    return (own + foreign)[: max(0, int(limit))]",
        "    return (foreign + own)[: max(0, int(limit))]",
    ),
    (
        "speed: лимит проб статики выключен",
        "app/services/site_speed.py",
        "    return (own + foreign)[: max(0, int(limit))]",
        "    return own + foreign",
    ),
    (
        "speed: пробу ресурсов не делают",
        "app/services/site_speed.py",
        "MAX_ASSET_PROBES = 6",
        "MAX_ASSET_PROBES = 0",
    ),
    (
        "speed:resource без сжатия назван тяжёлым без меры",
        "app/services/site_speed.py",
        '        out["uncompressed"] += 1 if (not encoding and size > COMPRESS_MIN_BYTES) else 0',
        '        out["uncompressed"] += 1 if not encoding else 0',
    ),
    (
        "speed: кэшированный ресурс записан некэшированным",
        "app/services/site_speed.py",
        '        out["uncached"] += 0 if cache == "cached" else 1',
        '        out["uncached"] += 1',
    ),
    (
        "speed: невзвешенный ресурс записан взвешенным",
        "app/services/site_speed.py",
        '        out["weighed"] += 1 if size else 0',
        '        out["weighed"] += 1',
    ),
    (
        "speed: размер назван там, где сервер его молчит",
        "app/services/site_speed.py",
        '        out["size_unknown"] += 0 if size else 1',
        '        out["size_unknown"] += 0',
    ),
    (
        "speed: ресурс без веса не отличается от сжатого",
        "app/services/site_speed.py",
        '        out["weightless"] += 1 if (not encoding and not size) else 0',
        '        out["weightless"] += 1 if not encoding else 0',
    ),
    (
        "speed: вес в сети подменён весом разметки",
        "app/services/site_speed.py",
        '        "wire_bytes": int(probe.get("wire_bytes") or 0),',
        '        "wire_bytes": int(probe.get("wire_bytes") or probe.get("content_bytes") or 0),',
    ),
    (
        "speed: незваный вес в сети показан числом в строке",
        "app/services/site_speed.py",
        '            + (f"{_kb(wire)} в сети, " if wire else "вес в сети не назван, ")',
        '            + (f"{_kb(wire)} в сети, " if not wire else "вес в сети не назван, ")',
    ),
    (
        "speed: молчание статики записано неназванным размером",
        "app/services/site_speed.py",
        "    if checked and silent == checked:",
        "    if False:",
    ),
    (
        "speed: незамеренный вес статики скрыт из честного блока",
        "app/services/site_speed.py",
        '    elif checked and not assets.get("weighed"):',
        "    elif False:",
    ),
    (
        "speed: сорванная проба ресурсов не попала в честный блок",
        "app/services/site_speed.py",
        '    elif assets.get("found") and not checked:',
        "    elif False:",
    ),
    (
        "speed: промпт выдал неизмеренный вес статики за ноль",
        "app/services/site_speed.py",
        '        size = (f"{_kb(assets.get(\'bytes\'))}, вес назван у {weighed}" if weighed\n'
        '                else "вес не назвал ни один ресурс")',
        '        size = (f"{_kb(assets.get(\'bytes\'))}, вес назван у {weighed}" if not weighed\n'
        '                else "вес не назвал ни один ресурс")',
    ),
    (
        "speed: промпт назвал неизвестный вес в сети измеренным",
        "app/services/site_speed.py",
        '        wire = (f"{_kb(page.get(\'wire_bytes\'))} в сети"\n'
        '                if count(page, "wire_bytes") else "вес в сети не назван")',
        '        wire = (f"{_kb(page.get(\'wire_bytes\'))} в сети"\n'
        '                if not count(page, "wire_bytes") else "вес в сети не назван")',
    ),
    (
        "speed: найденные, но не опробованные ресурсы скрыты",
        "app/services/site_speed.py",
        '    elif assets.get("found"):',
        "    elif False:",
    ),
    (
        "speed: молчание всех ресурсов притворилось выводом",
        "app/services/site_speed.py",
        "        if silent == total:",
        "        if False:",
    ),
    (
        "speed: битый ресурс пропал из таблицы",
        "app/services/site_speed.py",
        '        for item in (assets.get("dead") or [])[:3]:',
        "        for item in []:",
    ),
    (
        "speed: мёртвый ресурс не стал ошибкой пробы",
        "app/services/site_speed.py",
        '        elif assets.get("dead"):\n            row(label, seen, BAD,',
        '        elif False:\n            row(label, seen, BAD,',
    ),
    (
        "speed: незваный вес статики показан находкой",
        "app/services/site_speed.py",
        "        elif loose or uncached or weightless:",
        "        elif False:",
    ),
    (
        "speed: неизмеренный вес статики стал нормой",
        "app/services/site_speed.py",
        "        elif not weighed:\n            row(label, seen, UNKNOWN,",
        "        elif False:\n            row(label, seen, UNKNOWN,",
    ),
    (
        "speed: причина находки не совпала с выводом пробы",
        "app/services/site_speed.py",
        '            row(label, seen, CHECK, "статика: " + "; ".join(causes))',
        '            row(label, seen, CHECK, "сжатая и кэшированная статика докачивается один раз")',
    ),
    (
        "speed: число взвешенных ресурсов нарисовано от probe",
        "app/services/site_speed.py",
        '            f"вес назван у {weighed} ({_kb(assets.get(\'bytes\') or 0)})" if weighed\n'
        '            else "вес не назвал ни один ресурс"',
        '            f"вес назван у {weighed} ({_kb(assets.get(\'bytes\') or 0)})" if not weighed\n'
        '            else "вес не назвал ни один ресурс"',
    ),
    (
        "speed: ресурсы без веса и без сжатия скрыты из строки",
        "app/services/site_speed.py",
        '        if weightless:\n            seen += f", без веса и без сжатия {weightless}"',
        "        if False:\n"
        '            seen += f", без веса и без сжатия {weightless}"',
    ),
    (
        "psi: «тест не ответил» сравнялся с ошибкой Google",
        "app/services/site_speed.py",
        '    if not status:\n        return "unreachable"',
        '    if not status:\n        return "error"',
    ),
    (
        "psi: дневная квота записана ошибкой теста",
        "app/services/site_speed.py",
        '    if status == 429:\n        return "quota"',
        '    if status == 429:\n        return "error"',
    ),
    (
        "psi: отклонённый ключ записан исчерпанной квотой",
        "app/services/site_speed.py",
        '    if status in (401, 403):\n        return "blocked"',
        '    if status in (401, 403):\n        return "quota"',
    ),
    (
        "psi: пустой конверт стал отчётом с баллом",
        "app/services/site_speed.py",
        "    if not (result.get(\"audits\") or result.get(\"categories\") or experience.get(\"metrics\")):\n"
        '        return "foreign"',
        "    if False:\n        return \"foreign\"",
    ),
    (
        "psi: тело ответа не обязано быть объектом",
        "app/services/site_speed.py",
        "    body = probe.get(\"body\") if isinstance(probe.get(\"body\"), dict) else {}",
        "    body = probe.get(\"body\") or {}",
    ),
    (
        "psi: балл не переведён из доли в сотню",
        "app/services/site_speed.py",
        '        out["score"] = int(round(float(score) * 100))',
        "        out[\"score\"] = int(float(score))",
    ),
    (
        "psi: лабораторный CLS сведён к целому",
        "app/services/site_speed.py",
        '        out["lab"][key] = round(number, 4) if key == "CLS" else int(round(number))',
        '        out["lab"][key] = int(round(number))',
    ),
    (
        "psi: сотые доли CLS реальных посетителей потеряны",
        "app/services/site_speed.py",
        '            "value": round(number / 100, 4) if key == "CLS" else int(round(number)),',
        '            "value": int(round(number)),',
    ),
    (
        "psi: отсутствующая метрика выдумана нулём",
        "app/services/site_speed.py",
        '        value = item.get("numericValue")\n        if value is None:\n            continue',
        '        value = item.get("numericValue")\n        if value is None:\n            value = 0',
    ),
    (
        "psi: недоступный тест объявлен ошибкой сайта",
        "app/services/site_speed.py",
        '            PSI_STATE_TEXT.get(state, "нет данных"),\n            UNKNOWN,',
        '            PSI_STATE_TEXT.get(state, "нет данных"),\n            BAD,',
    ),
    (
        "vitals: вывод взят по лучшей метрике, а не по худшей",
        "app/services/site_speed.py",
        "    return max(known, key=lambda grade: VERDICT_RANK[grade]) if known else UNKNOWN",
        "    return min(known, key=lambda grade: VERDICT_RANK[grade]) if known else UNKNOWN",
    ),
    (
        "vitals: оценка реальных посетителей не различается",
        "app/services/site_speed.py",
        'GRADE_VERDICT = {"fast": OK, "average": CHECK, "slow": BAD}',
        'GRADE_VERDICT = {"fast": OK, "average": OK, "slow": OK}',
    ),
    (
        "vitals: секунды показаны миллисекундами",
        "app/services/site_speed.py",
        '    return f"{float(value) / 1000:.1f} с" if float(value) >= 1000 else f"{int(float(value))} мс"',
        '    return f"{int(float(value))} мс"',
    ),
    (
        "vitals: границы метрик перестали влиять на вывод",
        "app/services/site_speed.py",
        "    return OK if value <= limits[0] else CHECK if value <= limits[1] else BAD",
        "    return OK",
    ),
    (
        "speed: неудачный замер выдал полную таблицу выводов",
        "app/services/site_speed.py",
        '    if speed.get("failed"):\n        return {\n            "columns": columns,',
        "    if False:\n        return {\n            \"columns\": columns,",
    ),
    (
        "speed: неудачный замер исчез из честного блока",
        "app/services/site_speed.py",
        '    if speed.get("failed"):\n        return [\n            "Замер скорости не завершился',
        "    if False:\n        return [\n            \"Замер скорости не завершился",
    ),
    (
        "speed: отсутствие замера породило пробелы ни о чём",
        "app/services/site_speed.py",
        "def speed_gaps(speed: Dict) -> List[str]:\n"
        '    """Чего этот раздел утверждать не может — честно списком."""\n    if not speed:',
        "def speed_gaps(speed: Dict) -> List[str]:\n"
        '    """Чего этот раздел утверждать не может — честно списком."""\n    if False:',
    ),
    (
        "speed: недоступный PageSpeed не назван пробелом",
        "app/services/site_speed.py",
        '    if psi.get("state") != "ok":',
        "    if False:",
    ),
    (
        "speed: данных о посетителях не хватает — пробел молчит",
        "app/services/site_speed.py",
        "    if not (psi.get(\"field\") or {}):",
        "    if False:",
    ),
    (
        "speed: незамеренная главная выпала из честного блока",
        "app/services/site_speed.py",
        "    if not (speed.get(\"page\") or {}).get(\"measured\"):",
        "    if False:",
    ),
    (
        "speed: промпт пишет о замере, которого не было",
        "app/services/site_speed.py",
        '    if page.get("measured"):\n        wire = (',
        "    if True:\n        wire = (",
    ),
    (
        "speed: неразабранная разметка выдана прочитанной",
        "app/services/site_speed.py",
        '    if markup.get("parsed"):\n        hosts = ',
        "    if True:\n        hosts = ",
    ),
    (
        "speed: проба ресурсов описана, хотя её не делали",
        "app/services/site_speed.py",
        '    if assets.get("checked"):\n        # Модель обязана отличать',
        "    if True:\n        # Модель обязана отличать",
    ),
    (
        "speed: PSI без ответа выдал балл ноль",
        "app/services/site_speed.py",
        '    if state == "ok":\n        lines.append(\n            f"PageSpeed Insights: балл ',
        '    if True:\n        lines.append(\n            f"PageSpeed Insights: балл ',
    ),
    (
        "speed: из сломанного замера сделали видимость проверки",
        "app/services/site_speed.py",
        '    if speed.get("failed"):\n        return "## Скорость и мобильность\\nЗамер не завершился',
        '    if False:\n        return "## Скорость и мобильность\\nЗамер не завершился',
    ),
    (
        "speed: этап PSI не независим — его сбой отменяет замеры",
        "app/services/site_speed.py",
        '    except Exception:  # noqa: BLE001 - тест мог не ответить, цифры веса это не отменяет\n'
        '        speed["psi"] = {"state": "error", "score": 0, "lab": {}, "field": {}}',
        "    except Exception:  # noqa: BLE001 - тест мог не ответить, цифры веса это не отменяет\n"
        "        raise",
    ),
    # --- Скорость в анализаторе и отчёте ------------------------------------
    (
        "analyzer: замеры скорости не дошли до промптов",
        "app/services/analyzer.py",
        '        speed = facts.get("speed") or {}\n'
        "        if speed and not speed.get(\"failed\"):\n"
        "            blocks.append(site_speed.render_speed(speed))",
        "        speed = {}",
    ),
    (
        "analyzer: пробелы скорости теряются в data_gaps",
        "app/services/analyzer.py",
        '            + site_speed.speed_gaps(facts.get("speed"))',
        "            + []",
    ),
    (
        "analyzer: раздел скорости не попадает в отчёт",
        "app/services/analyzer.py",
        '            speed_checks = site_speed.build_speed_checks(speed) if speed else {"rows": []}\n'
        '            if speed_checks["rows"]:',
        '            speed_checks = site_speed.build_speed_checks(speed) if speed else {"rows": []}\n'
        "            if False:",
    ),
    (
        "analyzer: раздел скорости выпал из порядка чтения",
        "app/services/analyzer.py",
        '    "site_crawl",\n    "site_speed",\n',
        '    "site_crawl",\n',
    ),
    (
        "analyzer: сбой замера скорости роняет весь аудит",
        "app/services/analyzer.py",
        "        except Exception:  # noqa: BLE001 - сбой замера не стоит всего анализа\n"
        '            facts["speed"] = {"failed": True}',
        "        except Exception:  # noqa: BLE001 - сбой замера не стоит всего анализа\n            raise",
    ),
    (
        "analyzer: вес в сети взят из длины тела, а не из заголовка",
        "app/services/analyzer.py",
        '                "wire_bytes": wire or (0 if encoding else len(body)),',
        '                "wire_bytes": len(body),',
    ),
    (
        "analyzer: сжатие главной не спросили — и не заметили его",
        "app/services/analyzer.py",
        "            headers={'User-Agent': SITE_USER_AGENT, 'Accept-Encoding': 'gzip, deflate, br'},",
        "            headers={'User-Agent': SITE_USER_AGENT},",
    ),
    (
        "analyzer: редиректы замера не посчитаны",
        "app/services/analyzer.py",
        '                "redirects": len(response.history),',
        '                "redirects": 0,',
    ),
    (
        "analyzer: версия протокола не переведена из числа",
        "app/services/analyzer.py",
        '                "http_version": site_speed.HTTP_VERSIONS.get(int(version), ""),',
        '                "http_version": "",',
    ),
    (
        "analyzer: тело главной не дочитано — вес оказался заголовками",
        "app/services/analyzer.py",
        '            body = b"".join(chunk for chunk in response.iter_content(65536) if chunk)',
        "            body = b\"\"",
    ),
    (
        "analyzer: сжатие не запрошено — «без сжатия» оказалось нашей ошибкой",
        "app/services/analyzer.py",
        "            headers={'User-Agent': SITE_USER_AGENT, 'Accept-Encoding': 'gzip, deflate, br'},",
        "            headers={'User-Agent': SITE_USER_AGENT},",
    ),
    (
        "analyzer: молчащий ресурс роняет раздел скорости",
        "app/services/analyzer.py",
        '            return {"status": 0, "bytes": 0, "encoding": "", "cache_control": "", "expires": ""}',
        "            raise",
    ),
    (
        "analyzer: пробу ресурсов делают со скачиванием тела",
        "app/services/analyzer.py",
        "                stream=True,\n                allow_redirects=True,",
        "                stream=False,\n                allow_redirects=True,",
    ),
    (
        "analyzer: PageSpeed просят для десктопа",
        "app/services/analyzer.py",
        '        params = {"url": url, "strategy": "mobile", "category": "PERFORMANCE"}',
        '        params = {"url": url, "strategy": "desktop", "category": "PERFORMANCE"}',
    ),
    (
        "analyzer: пустой ключ PSI уходят в запрос",
        "app/services/analyzer.py",
        '        if key:\n            params["key"] = key',
        '        params["key"] = key',
    ),
    (
        "analyzer: сбой запроса PSI роняет аудит вместо честной строки",
        "app/services/analyzer.py",
        "        except Exception:\n            return {\"status\": 0, \"body\": {}}",
        "        except Exception:\n            raise",
    ),
    (
        "pdf: раздел скорости вышел в PDF сырым ключом",
        "app/services/pdf_report.py",
        '        "site_speed": "Скорость и мобильность сайта (посчитано кодом)",',
        "",
    ),
    (
        "pdf: раздел балла вышел в PDF сырым ключом",
        "app/services/pdf_report.py",
        '        "site_score": "Оценка сайта по осям (посчитано кодом)",',
        "",
    ),
    (
        "pdf: раздел приоритетов вышел в PDF сырым ключом",
        "app/services/pdf_report.py",
        '        "action_priorities": "Что чинить и в каком порядке (посчитано кодом)",',
        "",
    ),
    (
        "ui: интерфейс не знает названия раздела балла",
        "frontend/src/utils/labels.js",
        "  site_score: 'Оценка сайта по осям',",
        "",
    ),
    (
        "ui: интерфейс не знает названия очереди работ",
        "frontend/src/utils/labels.js",
        "  action_priorities: 'Что чинить и в каком порядке',",
        "",
    ),
    (
        "score: вывод читается из первой ячейки вместо третьей",
        "app/services/site_score.py",
        '    return str(cells[2] or "").split(" —")[0].strip()',
        '    return str(cells[0] or "").split(" —")[0].strip()',
    ),
    (
        "score: строка без ячейки вывода разбирается как вывод",
        "app/services/site_score.py",
        "    if len(cells) < 3:\n        return \"\"",
        "    if len(cells) < 1:\n        return \"\"",
    ),
    (
        "score: таблица считает строки короче трёх ячеек",
        "app/services/site_score.py",
        "        if isinstance(row, (list, tuple)) and len(row) >= 3",
        "        if isinstance(row, (list, tuple))",
    ),
    (
        "score: «проверить» получило полный балл",
        "app/services/site_score.py",
        "POINTS = {OK: 1.0, CHECK: 0.5, BAD: 0.0, MISSING: 0.0}",
        "POINTS = {OK: 1.0, CHECK: 1.0, BAD: 0.0, MISSING: 0.0}",
    ),
    (
        "score: отсутствующий счётчик спасает балл",
        "app/services/site_score.py",
        "POINTS = {OK: 1.0, CHECK: 0.5, BAD: 0.0, MISSING: 0.0}",
        "POINTS = {OK: 1.0, CHECK: 0.5, BAD: 0.0, MISSING: 1.0}",
    ),
    (
        "score: ошибка стоит как придирка",
        "app/services/site_score.py",
        "POINTS = {OK: 1.0, CHECK: 0.5, BAD: 0.0, MISSING: 0.0}",
        "POINTS = {OK: 1.0, CHECK: 0.5, BAD: 0.5, MISSING: 0.0}",
    ),
    (
        "score: незамеренное попало в знаменатель",
        "app/services/site_score.py",
        '    measured = counts["measured"]\n    gained = sum(',
        '    measured = counts["total"]\n    gained = sum(',
    ),
    (
        "score: ось из одной строки вошла в итог",
        "app/services/site_score.py",
        '        "counted": measured >= MIN_MEASURED,',
        '        "counted": bool(measured),',
    ),
    (
        "score: порог оси снят до одной проверки",
        "app/services/site_score.py",
        "MIN_MEASURED = 3",
        "MIN_MEASURED = 1",
    ),
    (
        "score: потолок осей не урезает знаменатель ошибки",
        "app/services/site_score.py",
        '    out["mistakes"] = out[BAD] + out[MISSING]',
        '    out["mistakes"] = out[BAD]',
    ),
    (
        "score: ошибка прощает верхнюю полосу не полностью",
        "app/services/site_score.py",
        "    if text == BANDS[0][1] and mistakes:",
        "    if text == BANDS[0][1] and mistakes >= 3:",
    ),
    (
        "score: порог готовности задран",
        "app/services/site_score.py",
        "READY_BAND = 85",
        "READY_BAND = 95",
    ),
    (
        "score: пустой отчёт притворился списком осей",
        "app/services/site_score.py",
        '    if not any(axis["counts"]["total"] for axis in axes):\n        return {\n            "columns": columns,\n            "rows": [["Итог", "кодовых таблиц проверок в отчёте нет",',
        '    if False:\n        return {\n            "columns": columns,\n            "rows": [["Итог", "кодовых таблиц проверок в отчёте нет",',
    ),
    (
        "score: оси пропали из таблицы — остался только итог",
        "app/services/site_score.py",
        "    rows: List[List[str]] = []\n    for axis in axes:",
        "    rows: List[List[str]] = []\n    for axis in []:",
    ),
    (
        "score: незасчитанная ось показала собственный балл",
        "app/services/site_score.py",
        '            (f"{axis[\'score\']}/100 · {_weight_note(axis[\'weight\'])}" if axis["counted"]',
        '            (f"{axis[\'score\']}/100 · {_weight_note(axis[\'weight\'])}" if axis["counts"]["total"]',
    ),
    (
        "score: нулевой балл показан как «не посчитан»",
        "app/services/site_score.py",
        '         if summary["axes"] else f"{UNKNOWN} — балл не посчитан"),',
        '         if summary["total"] else f"{UNKNOWN} — балл не посчитан"),',
    ),
    (
        "score: вес оси исчез из строки результата",
        "app/services/site_score.py",
        '    return f"вес оси {int(round(weight * 100))}%"',
        '    return "вес оси не учтён"',
    ),
    (
        "score: счёт норм не показывает придирки",
        "app/services/site_score.py",
        '    parts = [f"норма {counts[OK]}", f"проверить {counts[CHECK]}"]',
        '    parts = [f"норма {counts[OK]}"]',
    ),
    (
        "score: пустая ось названа нулём норм",
        "app/services/site_score.py",
        '        return "строк проверки в отчёте нет"',
        '        return "норма 0, проверить 0"',
    ),
    (
        "score: итог усреднён, а не взвешен",
        "app/services/site_score.py",
        '        total = int(round(sum(axis["weight"] * axis["score"] for axis in counted) / weight))',
        '        total = int(round(sum(axis["score"] for axis in counted) / len(counted)))',
    ),
    (
        "score: ошибка в отсеянной оси прощена",
        "app/services/site_score.py",
        '        "mistakes": sum(axis["counts"]["mistakes"] for axis in axes\n                        if axis["counts"]["total"]),',
        '        "mistakes": sum(axis["counts"]["mistakes"] for axis in counted\n                        if axis["counts"]["total"]),',
    ),
    (
        "score: придирки не попали в очередь работ",
        "app/services/site_score.py",
        "URGENCY_SEVERITY = {BAD: 1.0, MISSING: 1.0, CHECK: 0.5}",
        "URGENCY_SEVERITY = {BAD: 1.0, MISSING: 1.0}",
    ),
    (
        "score: норма и молчание записаны в очередь работ",
        "app/services/site_score.py",
        "            if severity is None:\n                continue",
        "            if severity is None:\n                severity = 0.0",
    ),
    (
        "score: очередь отсортирована по названию проверки",
        "app/services/site_score.py",
        "    found.sort(key=lambda item: -item[0])",
        "    found.sort(key=lambda item: item[2])",
    ),
    (
        "score: потолок очереди снят",
        "app/services/site_score.py",
        "    return [item[1:] for item in found[:limit]]",
        "    return [item[1:] for item in found]",
    ),
    (
        "score: строка очереди потеряла название оси",
        "app/services/site_score.py",
        '                f"{str(row[0] or \'\').strip()} · {axis[\'name\']}",',
        '                str(row[0] or "").strip(),',
    ),
    (
        "score: срок платит не вес, а тяжесть",
        "app/services/site_score.py",
        "    return URGENT if urgency >= 0.3 else SOON if urgency >= 0.15 else LATER",
        "    return URGENT if severity >= 1.0 else SOON if urgency >= 0.15 else LATER",
    ),
    (
        "score: всё уехало в «до запуска рекламы»",
        "app/services/site_score.py",
        "    return URGENT if urgency >= 0.3 else SOON if urgency >= 0.15 else LATER",
        "    return URGENT if urgency >= 0 else SOON if urgency >= 0.15 else LATER",
    ),
    (
        "score: ячейка работы обрезана на середине",
        "app/services/site_score.py",
        "    return text[:MAX_CELL]",
        "    return text[:MAX_CELL // 2]",
    ),
    (
        "score: работа названа без причины",
        "app/services/site_score.py",
        '    why = verdict.split(" — ", 1)[1].strip() if " — " in verdict else ""',
        '    why = ""',
    ),
    (
        "score: молчание проверок названо чистым сайтом",
        "app/services/site_score.py",
        '    measured = sum(axis["counts"]["measured"] for axis in axes)\n    if not measured:',
        '    measured = sum(axis["counts"]["measured"] for axis in axes)\n    if False:',
    ),
    (
        "score: очередь без таблиц притворилась посчитанной",
        "app/services/site_score.py",
        '    if not any(axis["counts"]["total"] for axis in axes):\n        return {\n            "columns": columns,\n            "rows": [["вне расписания", "Приоритеты не посчитаны",',
        '    if False:\n        return {\n            "columns": columns,\n            "rows": [["вне расписания", "Приоритеты не посчитаны",',
    ),
    (
        "score: обход вышел из очереди работ",
        "app/services/site_score.py",
        "    queue = axes + [axis_of(result, key, name, weight) for key, name, weight in EXTRA_AXES]",
        "    queue = axes",
    ),
    (
        "score: урезание очереди не названо в пробелах",
        "app/services/site_score.py",
        "    if beyond > 0:",
        "    if beyond < 0:",
    ),
    (
        "score: число урезанных находок потеряно",
        "app/services/site_score.py",
        '            f"({beyond}) — в таблицах проверок ниже"',
        '            "— в таблицах проверок ниже"',
    ),
    (
        "score: отсеянная ось не названа в пробелах",
        "app/services/site_score.py",
        '        elif not axis["counted"]:\n            gaps.append(',
        '        elif False:\n            gaps.append(',
    ),
    (
        "score: оценка по остатку не названа",
        "app/services/site_score.py",
        '        elif counts["silent"] > counts["measured"]:',
        '        elif False:',
    ),
    (
        "score: отсутствующая ось не названа",
        "app/services/site_score.py",
        '        if not counts["total"]:\n            gaps.append(\n                f"Ось «{axis[\'name\']}» не посчитана: строк этой проверки в отчёте нет"',
        '        if False:\n            gaps.append(\n                f"Ось «{axis[\'name\']}» не посчитана: строк этой проверки в отчёте нет"',
    ),
    (
        "score: отсутствие таблиц названо посчитанным баллом",
        "app/services/site_score.py",
        '            "Кодовых таблиц проверок в отчёте нет: балл сайта и очередь работ "\n            "не посчитаны"',
        '            "Балл сайта посчитан: проверок в отчёте достаточно"\n            ", очередь работ собрана"',
    ),
    (
        "score: ось названа по числу строк вместо выводов",
        "app/services/site_score.py",
        '                f"Ось «{axis[\'name\']}» в балл не вошла: проверок с выводом "',
        '                f"Ось «{axis[\'name\']}» в балл не вошла: строк таблицы всего "',
    ),
    (
        "analyzer: балл из ответа модели прошёл в отчёт",
        "app/services/analyzer.py",
        '        result.pop("site_score", None)\n        result.pop("action_priorities", None)',
        "        pass",
    ),
    (
        "analyzer: раздел балла выпал из порядка отчёта",
        "app/services/analyzer.py",
        '    "site_score",\n    "site_checks",',
        '    "site_checks",',
    ),
    (
        "analyzer: очередь работ выпала из порядка отчёта",
        "app/services/analyzer.py",
        '    "site_speed",\n    "action_priorities",',
        '    "site_speed",',
    ),
    (
        "analyzer: очередь работ не попала в отчёт",
        "app/services/analyzer.py",
        '            result["action_priorities"] = rating["priorities"]',
        "            pass",
    ),
    (
        "analyzer: балл посчитан по пустому отчёту",
        "app/services/analyzer.py",
        '            rating = site_score.assess(result)\n            result["site_score"] = rating["score"]',
        '            rating = site_score.assess({})\n            result["site_score"] = rating["score"]',
    ),
    (
        "analyzer: пробелы балла не дошли до честного блока",
        "app/services/analyzer.py",
        "        if score_caveats:",
        "        if False:",
    ),
]


def run_suite(target):
    proc = subprocess.run(
        [PY, "-m", "pytest", *target, "-q", "-x", "--no-header", "-p", "no:warnings"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout


def acquire_lock() -> None:
    """Два параллельных прогона правят один файл и портят друг друга.

    Проверка на деле оставляла в рабочем дереве analyzer.py с уже применённой
    мутацией: снапшот, сделанный вторым прогоном, был испорчен, и весь отчёт
    показывал «пойманы» там, где падали посторонние тесты.
    """
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip() or "0")
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError):
            LOCK.unlink(missing_ok=True)  # след от убитого прошлого прогона
        except PermissionError:
            pass
        else:
            raise SystemExit(f"уже идёт проверка мутаций (pid {pid}) — дождитесь конца")
    LOCK.write_text(str(os.getpid()))


def main():
    targets = {
        "app/services/analyzer.py": (
            "tests/test_analyzer_input.py",
            "tests/test_site_signals.py",
            "tests/test_site_infra.py",
            "tests/test_site_crawl.py",
            "tests/test_site_speed.py",
            "tests/test_site_score.py",
        ),
        "app/routers/history.py": ("tests/test_history_pdf_endpoint.py",),
        "app/services/pdf_report.py": ("tests/test_pdf_report.py", "tests/test_site_infra.py"),
        "app/services/site_signals.py": ("tests/test_site_signals.py",),
        "app/services/site_infra.py": ("tests/test_site_infra.py",),
        "app/services/site_crawl.py": ("tests/test_site_crawl.py",),
        "app/services/site_speed.py": ("tests/test_site_speed.py",),
        "app/services/site_score.py": ("tests/test_site_score.py",),
        "frontend/src/utils/labels.js": ("tests/test_pdf_report.py",),
    }
    survived = []

    # Снапшоты читаются до первой правки: файл, испорченный прошлым прогоном,
    # дал бы «пойманы» на каждой мутации и ни одного настоящего доказательства.
    snapshots = {rel: (ROOT / rel).read_text(encoding="utf-8") for _, rel, _, _ in MUTATIONS}
    for rel in targets:
        if rel not in snapshots:
            raise SystemExit(f"{rel}: ни одной мутации — проверка не нужна, а цель остаётся")

    if run_suite(("tests",))[0] != 0:
        raise SystemExit("тесты падают до всяких мутаций — сначала зелёный набор")

    for name, rel, old, new in MUTATIONS:
        path = ROOT / rel
        original = snapshots[rel]
        if original.count(old) != 1:
            print(f"ПРОПУСК  {name}: якорь встречается {original.count(old)} раз")
            survived.append(f"{name} (якорь не найден однозначно)")
            continue

        path.write_text(original.replace(old, new), encoding="utf-8")
        try:
            code, out = run_suite(targets[rel])
        finally:
            path.write_text(original, encoding="utf-8")

        if code != 0:
            first = [line for line in out.splitlines() if line.startswith("FAILED")]
            detail = first[0].split(" - ")[0][7:] if first else "?"
            print(f"ПОЙМАНА  {name} -> {detail}")
        else:
            print(f"ВЫЖИЛА   {name}")
            survived.append(name)

    broken = [rel for rel, text in snapshots.items() if (ROOT / rel).read_text(encoding="utf-8") != text]
    for rel in broken:
        (ROOT / rel).write_text(snapshots[rel], encoding="utf-8")
    LOCK.unlink(missing_ok=True)

    print("\n---")
    if broken:
        print("Файлы вернули из снапшотов (прогон был прерван на правке): " + ", ".join(broken))
    if survived:
        print(f"Мутации без падения тестов: {len(survived)}")
        for item in survived:
            print(f"  - {item}")
        return 1
    print(f"Все {len(MUTATIONS)} мутаций пойманы тестами.")
    return 0


if __name__ == "__main__":
    acquire_lock()
    sys.exit(main())
