"""Проверка тестов мутациями: ломаем механику — набор тестов должен падать.

Каждая мутация воспроизводит конкретный дефект, который чинил этот шаг:
склейка текста в одну строку, обрезка посреди слова, меню вместо оффера,
чужой отчёт по id, таблица «плоским» списком, неэкранированный HTML.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/mirash/site-analyzer")
PY = "/home/mirash/.venvs/sa/bin/python"

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
        '            extras.append(f"## Страница {path}\\n{self._fit(extra_content, per_extra_room)}")',
        '            extras.append(f"## Страница {path}\\n{extra_content}")',
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
        "                    lines = [line.strip() for line in item.splitlines() if line.strip()]",
        "                    lines = [item.strip()] if item.strip() else []",
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
]


def run_suite(target):
    proc = subprocess.run(
        [PY, "-m", "pytest", target, "-q", "-x", "--no-header", "-p", "no:warnings"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout


def main():
    targets = {
        "app/services/analyzer.py": "tests/test_analyzer_input.py",
        "app/routers/history.py": "tests/test_history_pdf_endpoint.py",
        "app/services/pdf_report.py": "tests/test_pdf_report.py",
    }
    survived = []

    for name, rel, old, new in MUTATIONS:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
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

    print("\n---")
    if survived:
        print(f"Мутации без падения тестов: {len(survived)}")
        for item in survived:
            print(f"  - {item}")
        return 1
    print("Все мутации пойманы тестами.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
