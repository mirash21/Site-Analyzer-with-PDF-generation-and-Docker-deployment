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
        '        if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != base_netloc:',
        '        if parsed.scheme not in ("http", "https"):',
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
        "            if taken >= MAX_PAGES_PER_SECTION:",
        "            if taken >= MAX_PAGES_PER_SECTION * 20:",
    ),
    (
        "analyzer: честный блок отдаёт на откуп модели",
        "app/services/analyzer.py",
        '        seeded = cls._seed_data_gaps(facts) + site_signals.signal_gaps(facts.get("signals"))',
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
        r'            + (f"{signals_block}\n\n" if signals_block else "")',
        '            + ""',
    ),
    (
        "analyzer: план кампании не видит проверок по разметке",
        "app/services/analyzer.py",
        '        literal = self.render_business_facts(facts) if facts else ""\n'
        "        signals_block = self._signals_block(facts)",
        '        literal = self.render_business_facts(facts) if facts else ""',
    ),
    (
        "analyzer: экономика не видит проверок по разметке",
        "app/services/analyzer.py",
        "        literal = self.render_business_facts(facts)\n"
        "        signals_block = self._signals_block(facts)",
        "        literal = self.render_business_facts(facts)",
    ),
    (
        "analyzer: пробелы из проверок теряются в data_gaps",
        "app/services/analyzer.py",
        "        seeded = cls._seed_data_gaps(facts) + site_signals.signal_gaps(facts.get(\"signals\"))",
        "        seeded = cls._seed_data_gaps(facts)",
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
        "app/services/analyzer.py": ("tests/test_analyzer_input.py", "tests/test_site_signals.py"),
        "app/routers/history.py": ("tests/test_history_pdf_endpoint.py",),
        "app/services/pdf_report.py": ("tests/test_pdf_report.py",),
        "app/services/site_signals.py": ("tests/test_site_signals.py",),
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
