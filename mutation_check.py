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
        '            + site_infra.infra_gaps(facts.get("infra"))\n        )',
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
        '    "site_gaps",\n    "site_checks",\n',
        '    "site_gaps",\n',
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
        ),
        "app/routers/history.py": ("tests/test_history_pdf_endpoint.py",),
        "app/services/pdf_report.py": ("tests/test_pdf_report.py", "tests/test_site_infra.py"),
        "app/services/site_signals.py": ("tests/test_site_signals.py",),
        "app/services/site_infra.py": ("tests/test_site_infra.py",),
        "app/services/site_crawl.py": ("tests/test_site_crawl.py",),
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
