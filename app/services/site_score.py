"""Балл сайта и очередь работ: код складывает уже посчитанные проверки.

Модели это доверять нельзя: она не делала ни одного запроса и не знает, какие
проверки вообще завершились. Здесь суммируются строки тех таблиц, что клиент
прочитает в том же отчёте ниже, — site_infra, site_checks, site_speed. Балл
обязан быть той же арифметикой, что и выводы: «ошибка» в таблице не может
ужиться с «готов к трафику» сверху страницы.

Незамеренное не наказывает и не спасает: строка «не проверено» не попадает в
знаменатель, но попадает в честный блок — оценка по трём проверкам из
тринадцати была бы обманом. Ось, где посчитано меньше трёх строк, в итог не
идёт совсем, а не раздувается до сотни.

Первая страница и чек-лист — те же находки, что и в очереди: краткий вывод
обязан называть то же число, что таблица осей ниже, а список работ — все
находки, а не восемь первых. Глагол работы берётся из вывода кода: «ошибка»
чинят, отсутствующее добавляют, спорное проверяют.
"""

from typing import Dict, List, Tuple

# Слова выводов общие со словарём кодовых таблиц: читатель видит те же строки.
OK = "норма"
CHECK = "проверить"
BAD = "ошибка"
MISSING = "не найдено"
UNKNOWN = "не проверено"

# Балл за строку. «проверить» — половина: часть таких строк окажется нормой,
# часть — неделей работы, и угадывать здесь нечем. «не найдено» и «ошибка»
# стоят одинаково: счётчика на сайте нет, независимо от того, нашли мы его
# плохо или не нашли вовсе.
POINTS = {OK: 1.0, CHECK: 0.5, BAD: 0.0, MISSING: 0.0}

# Вес оси — сколько она стоит рекламному бюджету: без индексации и без счётчиков
# кампания не начнётся, а медленная страница сольёт оплаченный трафик.
AXES: Tuple[Tuple[str, str, float], ...] = (
    ("site_infra", "Индексация и живые ссылки", 0.35),
    ("site_checks", "Маркировка и приём заявок", 0.35),
    ("site_speed", "Скорость и мобильность", 0.30),
)
# Обход описывает аудитора, а не сайт: в балл он не входит, но в очередь работ
# входит — непрошедшие страницы и висящие ссылки чинить всё равно клиенту.
EXTRA_AXES: Tuple[Tuple[str, str, float], ...] = (
    ("site_crawl", "Что осталось за обходом", 0.15),
)

# Ось из двух посчитанных строк — не ось: её балл зависит от одной строки.
MIN_MEASURED = 3
MAX_PRIORITY_ROWS = 8
# Полоса «готов» не выдаётся, пока в отчёте стоит хоть одна незакрытая ошибка.
READY_BAND = 85
BANDS = (
    (READY_BAND, "готов вести трафик"),
    (70, "работать можно, мешают детали"),
    (50, "до рекламы нужно починить"),
    (0, "сначала сайт, потом бюджет"),
)

# Срочность = вес оси × тяжесть находки. Пороги такие, что любая «ошибка»
# попадает в «до запуска», а мелкая придирка к лёгкой оси — в «по мере сил».
URGENCY_SEVERITY = {BAD: 1.0, MISSING: 1.0, CHECK: 0.5}
URGENT = "до запуска рекламы"
SOON = "первые две недели"
LATER = "по мере сил"
MAX_CELL = 170
# Глагол чек-листа берётся из вывода кода, а не из фантазии о сайте: «ошибка»
# чинят, отсутствующее добавляют, спорное проверяют.
ACTION_VERB = {BAD: "Исправить", MISSING: "Добавить", CHECK: "Проверить"}
CHECKBOX = "[ ]"
DEADLINES = (URGENT, SOON, LATER)


def verdict_of(row) -> str:
    """Слово вывода из строки таблицы: «норма — потому что…» → «норма»."""
    cells = list(row or [])
    if len(cells) < 3:
        return ""
    return str(cells[2] or "").split(" —")[0].strip()


def tally(table: Dict) -> Dict:
    """Счёт выводов по таблице: из чего именно сложится балл оси."""
    rows = [
        row for row in ((table or {}).get("rows") or [])
        if isinstance(row, (list, tuple)) and len(row) >= 3
    ]
    out: Dict = {"total": len(rows), "rows": rows}
    for verdict in POINTS:
        out[verdict] = sum(1 for row in rows if verdict_of(row) == verdict)
    out["measured"] = sum(out[verdict] for verdict in POINTS)
    out["silent"] = out["total"] - out["measured"]
    out["mistakes"] = out[BAD] + out[MISSING]
    return out


def axis_of(result: Dict, key: str, name: str, weight: float) -> Dict:
    """Одна ось: счёт по своей таблице, балл и право войти в итог."""
    counts = tally((result or {}).get(key))
    measured = counts["measured"]
    gained = sum(POINTS[verdict] * counts[verdict] for verdict in POINTS)
    return {
        "key": key,
        "name": name,
        "weight": weight,
        "counts": counts,
        "score": int(round(100 * gained / measured)) if measured else 0,
        "counted": measured >= MIN_MEASURED,
    }


def grade(score: int, mistakes: int) -> str:
    """Человеческий смысл числа. Верхняя полоса снимается при любой ошибке."""
    text = BANDS[-1][1]
    for floor, name in BANDS:
        if score >= floor:
            text = name
            break
    if text == BANDS[0][1] and mistakes:
        text = "готов вести трафик после исправления ошибок"
    return text


def _seen_cell(counts: Dict) -> str:
    if not counts["total"]:
        return "строк проверки в отчёте нет"
    parts = [f"норма {counts[OK]}", f"проверить {counts[CHECK]}"]
    if counts[BAD]:
        parts.append(f"ошибка {counts[BAD]}")
    if counts[MISSING]:
        parts.append(f"не найдено {counts[MISSING]}")
    if counts["silent"]:
        parts.append(f"не проверено {counts['silent']}")
    return ", ".join(parts)


def _weight_note(weight: float) -> str:
    return f"вес оси {int(round(weight * 100))}%"


def score_table(axes: List[Dict]) -> Dict:
    """Таблица осей и итог. Пустой отчёт остаётся одной честной строкой."""
    columns = ["Ось оценки", "Что посчитано кодом", "Балл и вес"]
    if not any(axis["counts"]["total"] for axis in axes):
        return {
            "columns": columns,
            "rows": [["Итог", "кодовых таблиц проверок в отчёте нет",
                      f"{UNKNOWN} — балл не посчитан"]],
        }
    rows: List[List[str]] = []
    for axis in axes:
        rows.append([
            axis["name"],
            _seen_cell(axis["counts"]),
            (f"{axis['score']}/100 · {_weight_note(axis['weight'])}" if axis["counted"]
             else f"{UNKNOWN}: посчитано меньше {MIN_MEASURED} проверок"),
        ])
    summary = summarize(axes)
    rows.append([
        "Итог",
        f"в балл вошли оси: {summary['used']}; ошибок и отсутствующего: {summary['mistakes']}",
        (f"{summary['total']}/100 — {grade(summary['total'], summary['mistakes'])}"
         if summary["axes"] else f"{UNKNOWN} — балл не посчитан"),
    ])
    return {"columns": columns, "rows": rows}


def summarize(axes: List[Dict]) -> Dict:
    """Взвешенный итог по осям, которые набрали право быть посчитанными."""
    counted = [axis for axis in axes if axis["counted"]]
    weight = sum(axis["weight"] for axis in counted)
    total = 0
    if weight:
        total = int(round(sum(axis["weight"] * axis["score"] for axis in counted) / weight))
    return {
        "total": total,
        "axes": counted,
        "used": ", ".join(axis["name"] for axis in counted) or "нет ни одной",
        # Ошибка в оси, не вошедшей в балл, всё равно остаётся ошибкой:
        # верхняя полоса не должна выдаваться из-за того, что ось отсеялась.
        "mistakes": sum(axis["counts"]["mistakes"] for axis in axes
                        if axis["counts"]["total"]),
    }


def due_for(weight: float, severity: float) -> str:
    urgency = weight * severity
    return URGENT if urgency >= 0.3 else SOON if urgency >= 0.15 else LATER


def _action_cell(row: List) -> str:
    """Что измерено и почему это важно — обе половины кодовой строки."""
    seen = str(row[1] or "").strip()
    verdict = str(row[2] or "")
    why = verdict.split(" — ", 1)[1].strip() if " — " in verdict else ""
    text = f"{seen} — {why}" if seen and why else (seen or why or "без деталей")
    return text[:MAX_CELL]


def _findings(queue: List[Dict]) -> List[Tuple]:
    """Все находки в порядке срочности: вес оси умножается на тяжесть вывода."""
    found: List[Tuple] = []
    for axis in queue:
        for row in axis["counts"]["rows"]:
            verdict = verdict_of(row)
            severity = URGENCY_SEVERITY.get(verdict)
            if severity is None:
                continue
            found.append((round(axis["weight"] * severity, 4), axis, row, verdict, severity))
    found.sort(key=lambda item: -item[0])
    return found


def priority_rows(axes: List[Dict], limit: int = MAX_PRIORITY_ROWS) -> List[List[str]]:
    """Очередь работ: тяжесть находки умножается на вес её оси, а не на красноречие."""
    return [
        [
            due_for(axis["weight"], severity),
            f"{str(row[0] or '').strip()} · {axis['name']}",
            _action_cell(row),
        ]
        for _, axis, row, _verdict, severity in _findings(axes)[:limit]
    ]


def findings_count(axes: List[Dict]) -> int:
    """Сколько находок дала бы очередь без потолка строк."""
    return len(_findings(axes))


def priorities_table(axes: List[Dict]) -> Dict:
    columns = ["Когда", "Проверка и ось", "Что нашёл код"]
    rows = priority_rows(axes)
    if rows:
        return {"columns": columns, "rows": rows}
    if not any(axis["counts"]["total"] for axis in axes):
        return {
            "columns": columns,
            "rows": [["вне расписания", "Приоритеты не посчитаны",
                      f"{UNKNOWN}: готовых таблиц проверок в отчёте нет"]],
        }
    # Выводов нет только по двум причинам: всё оказалось нормой, либо проверки
    # не завершились. Выдать вторую за первую — обещать клиенту покой, которого
    # аудит не видел.
    measured = sum(axis["counts"]["measured"] for axis in axes)
    if not measured:
        return {
            "columns": columns,
            "rows": [["вне расписания", "Работы не записано",
                      f"{UNKNOWN}: вывода нет ни по одной строке проверки — "
                      "очередь по такому отчёту не собрать"]],
        }
    return {
        "columns": columns,
        "rows": [["вне расписания", "Грубых находок код не нашёл",
                  f"засчитано проверок: {measured} — что проверять руками, "
                  "читается в рисках"]],
    }


def deadline_counts(queue: List[Dict]) -> Dict:
    """Сколько работ в каждом сроке — тем же множителем, что и в очереди."""
    out = {name: 0 for name in DEADLINES}
    for _, axis, _row, _verdict, severity in _findings(queue):
        out[due_for(axis["weight"], severity)] += 1
    return out


def _where_cell(axis: Dict, row: List) -> str:
    seen = str(row[1] or "").strip()
    text = f"{axis['name']} · вес оси {int(round(axis['weight'] * 100))}%"
    return f"{text} · {seen}"[:MAX_CELL] if seen else text


def checklist_rows(queue: List[Dict]) -> List[List[str]]:
    """Чек-лист для исполнителя: все находки, без потолка, с глаголом работы."""
    return [
        [
            f"{CHECKBOX} {due_for(axis['weight'], severity)}",
            f"{ACTION_VERB[verdict]}: {str(row[0] or '').strip()}",
            _where_cell(axis, row),
        ]
        for _, axis, row, verdict, severity in _findings(queue)
    ]


def checklist_table(queue: List[Dict]) -> Dict:
    columns = ["Отметка и срок", "Что сделать", "Где искать и в каком объёме"]
    rows = checklist_rows(queue)
    if rows:
        return {"columns": columns, "rows": rows}
    if not any(axis["counts"]["total"] for axis in queue):
        return {
            "columns": columns,
            "rows": [[CHECKBOX, "Чек-лист не посчитан",
                      f"{UNKNOWN}: готовых таблиц проверок в отчёте нет"]],
        }
    measured = sum(axis["counts"]["measured"] for axis in queue)
    if not measured:
        return {
            "columns": columns,
            "rows": [[CHECKBOX, "Работы не записаны",
                      f"{UNKNOWN}: вывода нет ни по одной строке проверки"]],
        }
    return {
        "columns": columns,
        "rows": [[CHECKBOX, "Грубых находок код не нашёл",
                  f"засчитано проверок: {measured} — список ручных проверок "
                  "читается в рисках"]],
    }


def summary_table(summary: Dict, caveats: List[str], queue: List[Dict]) -> Dict:
    """Первая страница: то же число, что и в таблице осей ниже, без новых слов."""
    columns = ["Что решает отчёт", "Посчитано кодом"]
    findings = _findings(queue)
    urgent = [item for item in findings if due_for(item[1]["weight"], item[4]) == URGENT]
    due = deadline_counts(queue)
    rows: List[List[str]] = [
        ["Балл готовности к трафику",
         (f"{summary['total']}/100 — {grade(summary['total'], summary['mistakes'])}"
          if summary["axes"] else f"{UNKNOWN}: балл не посчитан")],
        ["Что мешает запустить рекламу",
         (f"{str(urgent[0][2][0] or '').strip()} — всего таких находок {len(urgent)}" if urgent
          else (f"{UNKNOWN}: таблиц проверок в отчёте нет"
                if not any(item["counts"]["total"] for item in queue)
                else ("выводов нет ни по одной проверке"
                      if not sum(item["counts"]["measured"] for item in queue)
                      else "грубых находок код не нашёл")))],
        ["Порядок работ",
         (", ".join(f"{name}: {due[name]}" for name in DEADLINES)
          if any(item["counts"]["total"] for item in queue)
          else f"{UNKNOWN}: записывать нечего")],
        ["Чему в этом балле верить нельзя",
         (f"ограничений: {len(caveats)} — они в разделе «Каких данных нет»" if caveats
          else "ни одна ось не отсеяна, очередь не урезана")],
    ]
    return {"columns": columns, "rows": rows}


def score_caveats(axes: List[Dict], summary: Dict) -> List[str]:
    """Чего этот балл утверждать не может — списком в честный блок отчёта."""
    if not any(axis["counts"]["total"] for axis in axes):
        return [
            "Кодовых таблиц проверок в отчёте нет: балл сайта и очередь работ "
            "не посчитаны"
        ]
    gaps: List[str] = []
    if not summary["axes"]:
        gaps.append(
            "Общий балл не посчитан: ни одна ось не набрала "
            f"{MIN_MEASURED} посчитанных проверок — по этому сайту судить рано"
        )
    for axis in axes:
        counts = axis["counts"]
        if not counts["total"]:
            gaps.append(
                f"Ось «{axis['name']}» не посчитана: строк этой проверки в отчёте нет"
            )
        elif not axis["counted"]:
            gaps.append(
                f"Ось «{axis['name']}» в балл не вошла: проверок с выводом "
                f"{counts['measured']} из {counts['total']} — нужно не меньше "
                f"{MIN_MEASURED}, иначе оценка по ней была бы догадкой"
            )
        elif counts["silent"] > counts["measured"]:
            gaps.append(
                f"Ось «{axis['name']}» оценена по остатку: проверок без ответа "
                f"{counts['silent']} из {counts['total']}"
            )
    return gaps


def assess(result: Dict) -> Dict:
    """Всё, что нужно отчёту: две таблицы, число и список честных пробелов."""
    axes = [axis_of(result, key, name, weight) for key, name, weight in AXES]
    queue = axes + [axis_of(result, key, name, weight) for key, name, weight in EXTRA_AXES]
    summary = summarize(axes)
    caveats = score_caveats(axes, summary)
    # Список работ урезан: читатель обязан знать, что находок было больше, чем
    # строк в таблице, иначе «восемь пунктов» звучат как полный перечень.
    beyond = findings_count(queue) - len(priority_rows(queue))
    if beyond > 0:
        caveats.append(
            f"Очередь работ урезана до {MAX_PRIORITY_ROWS} строк, остальные находки "
            f"({beyond}) — в таблицах проверок ниже"
        )
    return {
        "score": score_table(axes),
        "priorities": priorities_table(queue),
        "checklist": checklist_table(queue),
        "summary": summary_table(summary, caveats, queue),
        "total": summary["total"],
        "mistakes": summary["mistakes"],
        "axes": axes,
        "band": grade(summary["total"], summary["mistakes"]) if summary["axes"] else "",
        "counted": bool(summary["axes"]),
        "caveats": caveats,
    }
