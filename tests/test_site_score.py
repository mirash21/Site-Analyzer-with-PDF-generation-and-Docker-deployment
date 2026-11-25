"""Балл сайта и очередь работ: арифметика уже посчитанных таблиц.

Ценность этих строк в том, что они не расходятся с отчётом ниже: «ошибка» в
таблице проверок и «готов вести трафик» на первой странице — это два разных
аудита одного сайта. Модель такое число не выведет, потому что не делала ни
одной проверки и не знает, сколько из них завершились выводом.

Поэтому проверяются три вещи: балл складывается ровно из тех выводов, что
читатель увидит в таблицах; незамеренное не попадает ни в числитель, ни в
знаменатель, но обязано быть названо; и очередь работ сортируется по весу оси,
а не по тому, насколько красивее формулировка.
"""

import pytest

from app.services import analyzer as analyzer_module
from app.services import site_crawl as crawl
from app.services import site_infra as infra
from app.services import site_score as rating
from app.services import site_signals as marks
from app.services import site_speed as speed
from app.services.analyzer import SiteAnalyzer

ORIGIN = "https://tateng.ru"

DIRTY_PAGE = """<html><head><title>Каталог</title></head><body>
<h1>Каталог</h1><h1>Прайс-лист</h1>
<p>У нас стоят счётчики и метрики, следим за статистикой.</p>
<img src="a.png"><img src="b.png" alt="">
</body></html>"""

CLEAN_PAGE = """<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://mc.yandex.ru/metrika/tag.js"></script>
</head><body>
<h1>Станки</h1><p>Цена 120 000 руб.</p>
<form><input name="phone" type="tel"></form>
<a href="tel:+78432001122">Позвонить</a>
<img src="a.png" alt="Станок" width="300" height="200">
<a href="/catalog">Каталог</a>
</body></html>"""


@pytest.fixture
def analyzer():
    return SiteAnalyzer(FakeLLM())


class FakeLLM:
    """Балл считает код: отвечать модели в этом наборе нечем."""

    def chat_json(self, system_prompt, user_prompt, **kwargs):
        return {}

    def chat_with_system(self, system_prompt, user_prompt, **kwargs):
        return "-"


def row(check, seen, verdict, why=""):
    """Строка кодовой таблицы: вывод всегда стоит в третьей ячейке."""
    return [check, seen, f"{verdict} — {why}" if why else verdict]


def table(*rows):
    return {"columns": ["Проверка", "Что видно", "Вывод"], "rows": [list(item) for item in rows]}


def made(key, name, weight, *rows):
    """Одна ось по её таблице — так же, как её считает assess."""
    return rating.axis_of({key: table(*rows)}, key, name, weight)


def filled(key, name, weight, verdict, count):
    """Ось из count одинаковых строк — удобно для границ полос и порогов."""
    return made(key, name, weight, *[
        row(f"проверка {i}", f"увидено {i}", verdict, "причина") for i in range(1, count + 1)
    ])


def queue_of(result):
    """Оси в том же составе, что собирает assess: балльные плюс обход."""
    axes = [rating.axis_of(result, key, name, weight) for key, name, weight in rating.AXES]
    return axes + [rating.axis_of(result, key, name, weight)
                   for key, name, weight in rating.EXTRA_AXES]


def robots_fetch(url, method="GET"):
    if url.endswith("/robots.txt"):
        return {"status": 200,
                "text": "User-agent: *\nDisallow: /admin/\n"
                        "Sitemap: https://tateng.ru/sitemap.xml\n",
                "chain": []}
    if url.endswith("/sitemap.xml"):
        return {"status": 200,
                "text": '<?xml version="1.0"?><urlset><url>'
                        "<loc>https://tateng.ru/catalog</loc></url></urlset>",
                "chain": []}
    return {"status": 404, "text": "", "chain": []}


def speed_block(html=DIRTY_PAGE):
    """Срез скорости без сети: замер подставлен, PageSpeed упёрся в квоту."""
    block = speed.empty_speed()
    block["page"] = speed.normalize_page({
        "status": 200, "ttfb_ms": 240, "total_ms": 700, "content_bytes": 40_000,
        "wire_bytes": 12_000, "final_url": ORIGIN + "/", "http_version": "HTTP/2",
        "headers": {"content-encoding": "gzip", "content-type": "text/html; charset=utf-8"},
    })
    block["markup"] = speed.parse_markup(html, ORIGIN)
    block["psi"] = {"state": "quota", "score": 0, "lab": {}, "field": {}}
    return block


CRAWL = {"pages": 9, "limit": crawl.MAX_CRAWL_PAGES, "text_pages": 4, "sections": ["catalog"],
         "depth": 2, "paged": 0, "duplicates": [], "failures": [], "refused": {}, "pending": 0,
         "stopped": "", "seconds": 18.0, "budget": 50.0}


# --- как читается вывод из строки таблицы ------------------------------------


def test_verdict_is_the_first_word_of_the_third_cell():
    assert rating.verdict_of(row("a", "b", "норма — всё хорошо")) == "норма"
    assert rating.verdict_of(row("a", "b", "ошибка")) == "ошибка"


def test_a_row_without_a_verdict_cell_is_not_a_conclusion():
    assert rating.verdict_of(["только", "две ячейки"]) == ""
    assert rating.verdict_of(None) == ""


def test_foreign_word_in_the_verdict_cell_stays_unmeasured():
    """Незнакомое слово — не находка и не норма: оно не должно получить балл."""
    counts = rating.tally(table(
        row("a", "1", "норма — есть"),
        row("b", "2", "примерно нормально — на глаз"),
    ))

    assert counts["total"] == 2
    assert counts["measured"] == 1
    assert counts["silent"] == 1
    assert counts["mistakes"] == 0


def test_rows_are_filtered_before_counting():
    counts = rating.tally(table(["без вывода"], row("a", "1", "ошибка — сломано")))

    assert counts["total"] == 1
    assert counts["mistakes"] == 1


def test_an_absent_table_tallies_to_nothing():
    for empty in (None, {}, {"rows": []}, {"rows": None}):
        assert rating.tally(empty)["total"] == 0


# --- балл оси ----------------------------------------------------------------


def test_half_a_point_for_a_maybe():
    axis = made("site_infra", "Индексация", 0.35,
                row("a", "1", "норма — есть"),
                row("b", "2", "проверить — похоже на правду"),
                row("c", "3", "норма — работает"))

    assert axis["counts"]["measured"] == 3
    assert axis["score"] == 83
    assert axis["counted"] is True


def test_absence_and_error_cost_the_same():
    """Счётчика может и не быть, а может не хватить разметки: исход один."""
    missing = made("site_checks", "Маркировка", 0.35,
                   row("a", "1", "норма — есть"), row("b", "2", "норма — есть"),
                   row("c", "3", "норма — есть"), row("d", "4", "не найдено — нету"))
    broken = made("site_checks", "Маркировка", 0.35,
                  row("a", "1", "норма — есть"), row("b", "2", "норма — есть"),
                  row("c", "3", "норма — есть"), row("d", "4", "ошибка — сломано"))

    assert missing["score"] == broken["score"] == 75
    assert missing["counts"]["mistakes"] == broken["counts"]["mistakes"] == 1


def test_unmeasured_rows_leave_the_denominator_but_not_the_report():
    """Пять «не проверено» не тянут балл вниз и не поднимают его до ста."""
    axis = made("site_infra", "Индексация", 0.35,
                row("a", "1", "норма — есть"), row("b", "2", "норма — есть"),
                *[row(f"x{i}", "нет данных", "не проверено — не замерено") for i in range(5)])

    assert axis["score"] == 100
    assert axis["counted"] is False, "две посчитанные строки — ещё не ось"
    assert axis["counts"]["silent"] == 5


def test_an_axis_needs_three_conclusions_to_be_counted():
    thin = filled("site_infra", "Индексация", 0.35, "норма", rating.MIN_MEASURED - 1)
    enough = filled("site_infra", "Индексация", 0.35, "норма", rating.MIN_MEASURED)

    assert thin["counted"] is False
    assert enough["counted"] is True


def test_a_missing_table_makes_an_empty_axis():
    axis = rating.axis_of({}, "site_speed", "Скорость", 0.30)

    assert axis["counts"]["total"] == 0
    assert axis["score"] == 0 and axis["counted"] is False


# --- полоса смысла -----------------------------------------------------------


@pytest.mark.parametrize("score,band", [
    (100, "готов вести трафик"),
    (85, "готов вести трафик"),
    (84, "работать можно, мешают детали"),
    (70, "работать можно, мешают детали"),
    (69, "до рекламы нужно починить"),
    (50, "до рекламы нужно починить"),
    (49, "сначала сайт, потом бюджет"),
    (0, "сначала сайт, потом бюджет"),
])
def test_bands_break_on_round_numbers(score, band):
    assert rating.grade(score, 0) == band


def test_the_ready_band_is_withheld_while_an_error_remains():
    assert rating.grade(90, 1) == "готов вести трафик после исправления ошибок"
    assert rating.grade(85, 3) == "готов вести трафик после исправления ошибок"


def test_lower_bands_already_promise_nothing():
    """Снимать маску не с чего: ниже верхней полосы обещаний и так нет."""
    assert rating.grade(84, 2) == "работать можно, мешают детали"
    assert rating.grade(40, 9) == "сначала сайт, потом бюджет"


# --- таблица балла -----------------------------------------------------------


def test_an_empty_report_stays_one_honest_line():
    made_up = rating.score_table([])

    assert made_up["columns"] == ["Ось оценки", "Что посчитано кодом", "Балл и вес"]
    assert len(made_up["rows"]) == 1
    assert "балл не посчитан" in made_up["rows"][0][2]


def test_a_real_zero_is_not_reported_as_unmeasured():
    """0/100 — это вывод аудита; «не посчитан» — это вывод о самом аудите."""
    axes = [filled("site_infra", "Индексация", 0.35, "ошибка", 4),
            filled("site_checks", "Маркировка", 0.35, "не найдено", 4),
            filled("site_speed", "Скорость", 0.30, "ошибка", 4)]
    made_up = rating.score_table(axes)
    last = made_up["rows"][-1]

    assert made_up["rows"][0][2] == "0/100 · вес оси 35%"
    assert last[0] == "Итог" and last[2].startswith("0/100 —")
    assert "не посчитан" not in last[2]


def test_an_uncounted_axis_shows_no_number_of_its_own():
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4),
            made("site_speed", "Скорость", 0.30,
                 row("a", "1", "норма — есть"), row("b", "2", "ошибка — сломано"))]
    made_up = rating.score_table(axes)
    speed_row = [item for item in made_up["rows"] if item[0] == "Скорость"][0]

    assert speed_row[2] == "не проверено: посчитано меньше 3 проверок"
    assert "100/100" not in speed_row[2] and "50/100" not in speed_row[2]


def test_counts_of_an_axis_are_printed_as_the_reader_sees_them():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("a", "1", "норма — есть"), row("b", "2", "ошибка — сломано"),
                 row("c", "3", "не найдено — нету"), row("d", "4", "не проверено — не смог"))]
    seen = rating.score_table(axes)["rows"][0][1]

    assert seen == "норма 1, проверить 0, ошибка 1, не найдено 1, не проверено 1"


def test_an_axis_with_no_rows_says_so_instead_of_zero():
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4),
            rating.axis_of({}, "site_speed", "Скорость и мобильность", 0.30)]
    made_up = rating.score_table(axes)
    silent = [item for item in made_up["rows"] if item[0] == "Скорость и мобильность"][0]

    assert silent[1] == "строк проверки в отчёте нет"
    assert silent[2] == "не проверено: посчитано меньше 3 проверок"


def test_error_in_a_dropped_axis_still_blocks_the_top_band():
    """Отсеять ось — не значит простить стоящую в ней ошибку."""
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4),
            filled("site_checks", "Маркировка", 0.35, "норма", 3),
            made("site_speed", "Скорость", 0.30,
                 row("a", "1", "норма — быстрый"), row("b", "2", "ошибка — прыгает"))]
    summary = rating.summarize(axes)

    assert summary["total"] == 100, "ось вне списка не тянет балл вниз"
    assert summary["mistakes"] == 1, "но её ошибка остаётся ошибкой"
    assert rating.grade(summary["total"], summary["mistakes"]) == (
        "готов вести трафик после исправления ошибок")


def test_score_is_weighted_by_what_the_budget_depends_on():
    """Половина беглой оси не перетянет целую индексацию."""
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4),
            filled("site_checks", "Маркировка", 0.35, "норма", 4),
            filled("site_speed", "Скорость", 0.30, "ошибка", 4)]
    summary = rating.summarize(axes)

    assert summary["total"] == 70
    assert summary["used"].count(",") == 2


# --- очередь работ -----------------------------------------------------------


def test_queue_sorts_by_axis_weight_times_severity():
    """Придирка к тяжёлой оси обгоняет грубую находку на лёгкой: вес решает."""
    axes = [
        made("site_speed", "Скорость", 0.30, row("тормоз", "720 мс", "ошибка — ждёт")),
        made("site_infra", "Индексация", 0.35, row("закрыт", "Disallow: /", "ошибка — нет")),
        made("site_crawl", "Обход", 0.15, row("упало", "3 ошибки", "ошибка — сбой")),
        made("site_infra", "Индексация", 0.35, row("мелочь", "нет og", "проверить — странно")),
    ]
    queue = rating.priority_rows(axes)

    assert [item[1] for item in queue] == [
        "закрыт · Индексация", "тормоз · Скорость", "мелочь · Индексация", "упало · Обход"]
    assert [item[0] for item in queue] == [rating.URGENT, rating.URGENT,
                                           rating.SOON, rating.SOON]


def test_deadlines_split_by_urgency_and_not_by_words():
    assert rating.due_for(0.35, 1.0) == rating.URGENT
    assert rating.due_for(0.30, 1.0) == rating.URGENT
    assert rating.due_for(0.35, 0.5) == rating.SOON
    assert rating.due_for(0.15, 1.0) == rating.SOON
    assert rating.due_for(0.15, 0.5) == rating.LATER


def test_norm_and_unmeasured_rows_never_join_the_queue():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("норма", "1", "норма — есть"),
                 row("молчание", "0", "не проверено — не замерено"),
                 row("чужое слово", "1", "сомнительно — на глаз"))]

    assert rating.priority_rows(axes) == []
    assert rating.findings_count(axes) == 0


def test_crawl_finds_join_the_queue_though_crawl_is_not_scored():
    """Обход описывает аудитора, но висящие ссылки чинить всё равно клиенту."""
    axes = [made("site_crawl", "Что осталось за обходом", 0.15,
                 row("Битые ссылки", "2", "ошибка — ведёт в никуда"))]
    queue = rating.priority_rows(axes)

    assert queue[0][0] == rating.SOON
    assert "Битые ссылки" in queue[0][1]


def test_crawl_findings_join_the_queue_of_a_whole_report():
    """Assess обязан не терять обход: в балле его нет, в работах он есть."""
    out = rating.assess({
        "site_infra": table(*[row(f"a{i}", "1", "норма — есть") for i in range(4)]),
        "site_crawl": table(row("Битые ссылки", "2", "ошибка — ведёт в никуда")),
    })
    cells = "\n".join(str(cell) for item in out["priorities"]["rows"] for cell in item)

    assert "Что осталось за обходом" in cells
    assert "Битые ссылки" in cells


def test_the_queue_is_capped_and_says_the_rest_exists():
    rows = [row(f"проверка {i}", "нет", "ошибка — сломано")
            for i in range(rating.MAX_PRIORITY_ROWS + 5)]
    out = rating.assess({"site_infra": table(*rows)})

    assert len(out["priorities"]["rows"]) == rating.MAX_PRIORITY_ROWS
    joined = "\n".join(out["caveats"])
    assert "Очередь работ урезана" in joined and "(5)" in joined


def test_action_cell_keeps_the_number_and_the_reason():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("Sitemap", "карта, адресов: 40", "ошибка — карта не читается"))]
    queue = rating.priority_rows(axes)

    assert queue[0][2] == "карта, адресов: 40 — карта не читается"


def test_action_cell_never_outgrows_the_page():
    long_seen = "д" * (rating.MAX_CELL + 120)
    axes = [made("site_infra", "Индексация", 0.35, row("a", long_seen, "ошибка — причина"))]
    cell = rating.priority_rows(axes)[0][2]

    assert len(cell) == rating.MAX_CELL


def test_action_cell_survives_a_missing_half():
    assert rating._action_cell(row("a", "", "ошибка — причина только в выводе")) == (
        "причина только в выводе")
    assert rating._action_cell(row("a", "увидено", "ошибка")) == "увидено"
    assert rating._action_cell(row("a", "", "ошибка — ")) == "без деталей"


def test_queue_without_any_table_admits_it_was_not_counted():
    made_up = rating.priorities_table([rating.axis_of({}, "site_infra", "Индексация", 0.35)])

    assert made_up["columns"] == ["Когда", "Проверка и ось", "Что нашёл код"]
    assert made_up["rows"][0][1] == "Приоритеты не посчитаны"
    assert made_up["rows"][0][2].startswith("не проверено")


def test_silence_is_not_reported_as_a_clean_bill_of_health():
    """Все проверки молчат — это не «работ нет», это нет вывода вовсе."""
    axes = [made("site_infra", "Индексация", 0.35,
                 *[row(f"a{i}", "нет данных", "не проверено — не замерено") for i in range(5)])]
    made_up = rating.priorities_table(axes)

    assert made_up["rows"][0][1] == "Работы не записано"
    assert "грубых находок" not in made_up["rows"][0][2].lower()


def test_a_clean_site_gets_an_empty_queue_explained_in_words():
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4)]
    made_up = rating.priorities_table(axes)

    assert made_up["rows"][0][1] == "Грубых находок код не нашёл"
    assert "засчитано проверок: 4" in made_up["rows"][0][2]


# --- чек-лист и первая страница ---------------------------------------------


def findings_report():
    """Отчёт, в котором есть находка каждого вывода — и молчание тоже."""
    return {
        "site_infra": table(
            row("robots.txt", "есть", "норма — открыт"),
            row("Sitemap", "404", "проверить — медленно"),
            row("Ссылки", "2 битых", "ошибка — заявка потеряна"),
            row("Редирект", "3", "норма — один прыжок")),
        "site_checks": table(
            row("Счётчики и пиксели", "ни одного", "не найдено — вслепую"),
            row("Формы заявок", "2", "норма — принимают"),
            row("Мобильная вёрстка (viewport)", "нет", "проверить — телефон"),
            row("Картинки без alt", "13 из 20", "проверить — поиск")),
        "site_speed": table(
            row("Ответ сервера", "900 мс", "ошибка — ждёт"),
            row("Картинки без размеров", "51 из 51", "проверить — прыгают"),
            row("Вес главной страницы", "12 КБ", "норма — лёгкая"),
            row("PageSpeed Insights (мобильные)", "квота", "не проверено — нет теста")),
        "site_crawl": table(
            row("Дубликаты содержания", "3", "проверить — одно и то же"),
            row("Глубина обхода", "2 страницы", "норма — мало")),
    }


def test_checklist_lists_every_finding_without_the_queue_cap():
    rows = [row(f"проверка {i}", "нет", "ошибка — сломано")
            for i in range(rating.MAX_PRIORITY_ROWS + 7)]
    out = rating.assess({"site_infra": table(*rows)})

    assert len(out["priorities"]["rows"]) == rating.MAX_PRIORITY_ROWS
    assert len(out["checklist"]["rows"]) == rating.MAX_PRIORITY_ROWS + 7


def test_checklist_verb_comes_from_the_verdict_and_not_from_imagination():
    out = rating.checklist_rows([
        made("site_infra", "Индексация", 0.35, row("a", "2", "ошибка — сломано")),
        made("site_checks", "Маркировка", 0.35, row("b", "нет", "не найдено — пусто")),
        made("site_speed", "Скорость", 0.30, row("c", "нет og", "проверить — странно")),
    ])

    assert [item[1] for item in out] == ["Исправить: a", "Добавить: b", "Проверить: c"]


def test_checklist_box_and_deadline_share_one_cell():
    out = rating.checklist_rows([
        made("site_infra", "Индексация", 0.35, row("a", "2", "ошибка — сломано")),
        made("site_crawl", "Обход", 0.15, row("b", "нет og", "проверить — странно")),
    ])

    assert out[0][0] == f"[ ] {rating.URGENT}"
    assert out[1][0] == f"[ ] {rating.LATER}"


def test_checklist_keeps_axis_weight_and_the_measured_number():
    out = rating.checklist_rows([
        made("site_speed", "Скорость и мобильность", 0.30,
             row("Картинки без размеров", "51 из 51 (100%)", "ошибка — прыгают")),
    ])

    assert out[0][2] == "Скорость и мобильность · вес оси 30% · 51 из 51 (100%)"


def test_checklist_cell_is_capped_like_the_queue():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("a", "д" * (rating.MAX_CELL + 90), "ошибка — сломано"))]

    assert max(len(cell) for cell in rating.checklist_rows(axes)[0]) <= rating.MAX_CELL


def test_checklist_orders_by_the_same_urgency_as_the_queue():
    out = rating.checklist_table(queue_of(findings_report()))
    deadlines = [item[0].replace("[ ] ", "") for item in out["rows"]]

    assert deadlines == [rating.URGENT, rating.URGENT, rating.URGENT] + [rating.SOON] * 4 + \
        [rating.LATER], "срок обязан идти группами: исполнитель читает сверху вниз"


def test_checklist_without_tables_says_it_was_not_counted():
    out = rating.checklist_table([rating.axis_of({}, "site_infra", "Индексация", 0.35)])

    assert out["columns"] == ["Отметка и срок", "Что сделать", "Где искать и в каком объёме"]
    assert out["rows"] == [["[ ]", "Чек-лист не посчитан",
                           "не проверено: готовых таблиц проверок в отчёте нет"]]


def test_checklist_of_a_silent_report_writes_no_work():
    axes = [made("site_infra", "Индексация", 0.35,
                 *[row(f"a{i}", "нет", "не проверено — молчит") for i in range(4)])]

    assert rating.checklist_table(axes)["rows"][0][1] == "Работы не записаны"


def test_checklist_of_a_clean_site_counts_what_stood():
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4)]
    row_cell = rating.checklist_table(axes)["rows"][0][2]

    assert "Грубых находок код не нашёл" in rating.checklist_table(axes)["rows"][0][1]
    assert "засчитано проверок: 4" in row_cell


def test_checklist_of_a_whole_report_keeps_the_crawl_work():
    """Assess обязан сдавать в чек-лист всю очередь, а не только балльные оси."""
    out = rating.assess({
        "site_infra": table(*[row(f"a{i}", "1", "норма — есть") for i in range(4)]),
        "site_crawl": table(row("Битые ссылки", "2", "ошибка — ведёт в никуда")),
    })
    cells = "\n".join(" · ".join(item) for item in out["checklist"]["rows"])

    assert "Битые ссылки" in cells
    assert "Что осталось за обходом" in cells


def test_summary_of_the_report_carries_the_caveats_of_the_same_run():
    """Срок работ без объяснения, чему в балле верить нельзя, — половина вывода."""
    out = rating.assess({"site_infra": table(row("a", "1", "норма — есть"))})

    assert out["caveats"]
    assert out["summary"]["rows"][3][1] == (
        f"ограничений: {len(out['caveats'])} — они в разделе «Каких данных нет»")


def test_summary_quotes_the_number_from_the_axis_table():
    out = rating.assess(findings_report())
    score_last = out["score"]["rows"][-1][2]

    assert out["summary"]["rows"][0] == ["Балл готовности к трафику", score_last], (
        "первая страница и таблица осей обязана давать одно и то же число"
    )


def test_summary_names_the_first_blocking_finding():
    out = rating.summary_table(*_summary_args(findings_report()))
    blocker = out["rows"][1][1]

    assert blocker.startswith("Ссылки") and "всего таких находок 3" in blocker


def test_summary_deadlines_count_the_same_rows_as_the_checklist():
    out = rating.assess(findings_report())
    counts = {rating.URGENT: 3, rating.SOON: 4, rating.LATER: 1}
    checklist = "\n".join(item[0] for item in out["checklist"]["rows"])

    assert out["summary"]["rows"][2][1] == (
        "до запуска рекламы: 3, первые две недели: 4, по мере сил: 1")
    for name, count in counts.items():
        assert checklist.count(f"[ ] {name}") == count


def test_summary_reports_its_own_limits_in_the_honest_block():
    args = _summary_args({"site_infra": table(
        row("a", "1", "норма — есть"), row("b", "2", "норма — есть"),
        row("c", "3", "ошибка — сломано"))})
    out = rating.summary_table(*args)

    assert "ограничений:" in out["rows"][3][1]
    assert "Каких данных нет" in out["rows"][3][1]


def test_a_clean_summary_is_allowed_to_say_ready():
    args = _summary_args({key: table(*[row(f"x{i}", "1", "норма — есть") for i in range(4)])
                          for key in ("site_infra", "site_checks", "site_speed")})
    out = rating.summary_table(*args)

    assert out["rows"][0][1] == "100/100 — готов вести трафик"
    assert out["rows"][1][1] == "грубых находок код не нашёл"
    assert out["rows"][3][1] == "ни одна ось не отсеяна, очередь не урезана"


def test_silence_is_not_summarised_as_a_clean_site():
    args = _summary_args({key: table(*[row(f"x{i}", "нет", "не проверено — молчит")
                                       for i in range(4)])
                          for key in ("site_infra", "site_checks", "site_speed")})
    out = rating.summary_table(*args)

    assert out["rows"][1][1] == "выводов нет ни по одной проверке"
    assert out["rows"][0][1] == "не проверено: балл не посчитан"


def test_an_empty_summary_admits_there_was_nothing_to_count():
    out = rating.assess({})["summary"]

    assert out["rows"][0][1] == "не проверено: балл не посчитан"
    assert out["rows"][1][1] == "не проверено: таблиц проверок в отчёте нет"
    assert out["rows"][2][1] == "не проверено: записывать нечего"


def _summary_args(result):
    queue = queue_of(result)
    axes = queue[:len(rating.AXES)]
    summary = rating.summarize(axes)
    caveats = rating.score_caveats(axes, summary)
    beyond = rating.findings_count(queue) - len(rating.priority_rows(queue))
    if beyond > 0:
        caveats.append(f"Очередь работ урезана до {rating.MAX_PRIORITY_ROWS} строк")
    return summary, caveats, queue


# --- честные пробелы ---------------------------------------------------------


def test_no_tables_at_all_is_one_caveat_and_no_invention():
    out = rating.assess({})

    assert len(out["caveats"]) == 1
    assert "балл сайта и очередь работ не посчитаны" in out["caveats"][0]
    assert out["counted"] is False and out["band"] == ""
    assert len(out["score"]["rows"]) == 1 and len(out["priorities"]["rows"]) == 1


def test_a_thin_report_says_it_is_too_early_to_judge():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("a", "1", "норма — есть"), row("b", "2", "ошибка — сломано"))]
    gaps = rating.score_caveats(axes, rating.summarize(axes))

    assert any("Общий балл не посчитан" in item for item in gaps)


def test_an_absent_axis_is_named_in_the_honest_block():
    axes = [filled("site_infra", "Индексация", 0.35, "норма", 4),
            rating.axis_of({}, "site_speed", "Скорость и мобильность", 0.30)]
    gaps = rating.score_caveats(axes, rating.summarize(axes))

    assert any("«Скорость и мобильность» не посчитана" in item for item in gaps)


def test_a_scored_axis_names_its_weakest_part():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("a", "1", "норма — есть"), row("b", "2", "норма — есть"),
                 row("c", "3", "норма — есть"),
                 *[row(f"x{i}", "нет", "не проверено — не смог") for i in range(4)])]
    gaps = rating.score_caveats(axes, rating.summarize(axes))

    assert gaps == ["Ось «Индексация» оценена по остатку: проверок без ответа 4 из 7"]


def test_an_axis_with_more_conclusions_than_silence_is_not_flagged():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("a", "1", "норма — есть"), row("b", "2", "норма — есть"),
                 row("c", "3", "норма — есть"), row("d", "4", "не проверено — не смог"))]

    assert rating.score_caveats(axes, rating.summarize(axes)) == []


def test_a_thin_axis_is_reported_with_its_own_counts():
    axes = [made("site_infra", "Индексация", 0.35,
                 row("a", "1", "норма — есть"), row("b", "2", "ошибка — сломано"))]
    gaps = rating.score_caveats(axes, rating.summarize(axes))

    assert any("Ось «Индексация» в балл не вошла" in item for item in gaps)
    assert any("проверок с выводом 2 из 2" in item and "нужно не меньше 3" in item
               for item in gaps)


# --- вместе: форма и непротиворечивость -------------------------------------


def test_assess_tables_share_the_report_shape():
    out = rating.assess({"site_infra": table(*[
        row("a", "1", "норма — есть"), row("b", "2", "ошибка — сломано"),
        row("c", "3", "норма — есть"), row("d", "4", "проверить — странно")])})

    for name, width in (("score", 3), ("priorities", 3), ("checklist", 3), ("summary", 2)):
        made_up = out[name]
        assert len(made_up["columns"]) == width, "PDF рисует равные колонки"
        for item in made_up["rows"]:
            assert len(item) == width
            assert all(isinstance(cell, str) and cell for cell in item)
    # Первая страница обязана оставаться четырёхстрочной и называть автора чисел.
    assert out["summary"]["columns"] == ["Что решает отчёт", "Посчитано кодом"]
    assert len(out["summary"]["rows"]) == 4


def test_the_number_and_the_words_cannot_disagree():
    """Полоса обязана следовать из таблицы: 52 балла — это не «готов»."""
    out = rating.assess({
        "site_infra": table(*[row(f"a{i}", "1", "норма — есть") for i in range(4)]),
        "site_checks": table(*[row(f"c{i}", "1", "проверить — можно") for i in range(6)]),
        "site_speed": table(*[row(f"s{i}", "1", "ошибка — сломано") for i in range(4)]),
    })

    assert out["counted"] is True
    # 35 (индексация) + 17.5 (половина за «проверить») + 0 (скорость сломана).
    assert out["total"] == 52 and out["mistakes"] == 4
    assert out["band"] == rating.grade(out["total"], out["mistakes"])
    assert "готов вести трафик" not in out["band"]


def test_a_ready_band_never_survives_an_open_error():
    out = rating.assess({
        "site_infra": table(*[row(f"a{i}", "1", "норма — есть") for i in range(4)]),
        "site_checks": table(*[row(f"c{i}", "1", "норма — есть") for i in range(3)],
                             row("дубли", "2", "не найдено — нет")),
        "site_speed": table(*[row(f"s{i}", "1", "норма — есть") for i in range(4)]),
    })

    assert out["total"] >= rating.READY_BAND
    assert out["band"] == "готов вести трафик после исправления ошибок"


def test_real_tables_feed_the_same_words_as_the_score():
    """Общий словарь выводов: переименуют его в любой таблице — балл замолчит."""
    known = {rating.OK, rating.CHECK, rating.BAD, rating.MISSING, rating.UNKNOWN}
    made_up = {
        "site_checks": marks.build_site_checks(marks.scan_page(DIRTY_PAGE)),
        "site_infra": infra.build_infra_checks(infra.probe_site(ORIGIN, robots_fetch, [])),
        "site_speed": speed.build_speed_checks(speed_block()),
        "site_crawl": crawl.build_crawl_checks(CRAWL),
    }
    out = rating.assess(made_up)

    for key, item in made_up.items():
        for source in item["rows"]:
            assert rating.verdict_of(source) in known, f"{key}: вывод вне словаря"
    assert out["counted"] is True
    assert len(out["score"]["rows"]) == 4, "три оси и итог"
    assert out["priorities"]["rows"][0][0] == rating.URGENT, "без счётчиков реклама вслепую"


def test_a_broken_site_scores_below_a_readable_one():
    dirty = rating.summarize([
        rating.axis_of({"x": marks.build_site_checks(marks.scan_page(DIRTY_PAGE))},
                       "x", "Маркировка", 1.0)])
    clean = rating.summarize([
        rating.axis_of({"x": marks.build_site_checks(marks.scan_page(CLEAN_PAGE))},
                       "x", "Маркировка", 1.0)])

    assert clean["total"] > dirty["total"]
    assert dirty["mistakes"] == 2 and clean["mistakes"] == 0


# --- в отчёте ----------------------------------------------------------------


def test_score_and_queue_reach_the_report_in_order(analyzer):
    sources = [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}]
    facts = {
        "phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
        "crawl": CRAWL,
        "signals": marks.scan_page(DIRTY_PAGE),
        "infra": infra.probe_site(ORIGIN, robots_fetch, []),
        "speed": speed_block(),
    }

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    keys = list(normalized)
    order = list(analyzer_module.REPORT_SECTION_ORDER)

    assert keys.index("site_score") < keys.index("site_checks")
    assert keys.index("site_speed") < keys.index("action_priorities")
    assert order.index("site_score") < order.index("site_checks")
    assert order.index("site_speed") < order.index("action_priorities")
    assert len(normalized["site_score"]["rows"]) == 4
    assert normalized["action_priorities"]["rows"]


def test_the_model_cannot_write_its_own_score(analyzer):
    """Ключ с именем кодового раздела из ответа модели — подделка."""
    sources = [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}]
    forged = {"columns": ["Ось оценки", "Что посчитано кодом", "Балл и вес"],
              "rows": [["Сайт", "по моим словам", "100/100 — готов вести трафик"]]}
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
             "signals": marks.scan_page(CLEAN_PAGE)}
    answer = {"brief_analysis": "разбор", "site_score": forged, "action_priorities": forged,
              "executive_summary": forged, "implementation_checklist": forged}

    with_sources = analyzer._normalize_final_analysis(answer, sources, facts)
    without_sources = analyzer._normalize_final_analysis(answer, None, None)

    assert "готов вести трафик" not in str(with_sources["site_score"])
    assert "готов вести трафик" not in str(with_sources["executive_summary"])
    for key in ("site_score", "action_priorities", "executive_summary",
                "implementation_checklist"):
        assert key not in without_sources, f"{key}: выдумка модели уцелела в отчёте"


def test_the_score_of_a_clean_report_is_not_padded_with_caveats(analyzer):
    sources = [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}]
    facts = {
        "phones": ["+78432001122"], "emails": [], "legal_entities": [], "requisites": [],
        "prices": [120000], "crawl": CRAWL,
        "signals": marks.scan_page(CLEAN_PAGE),
        "infra": infra.probe_site(ORIGIN, robots_fetch, []),
        "speed": speed_block(CLEAN_PAGE),
    }

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    gaps = "\n".join(normalized.get("data_gaps") or [])

    assert "Ось «Скорость и мобильность»" not in gaps, "ось посчитана — её не за что упрекнуть"


def test_a_thin_crawl_sends_the_axis_into_the_honest_block(analyzer):
    """Балл по половине проверок читается как полный: пробел обязан быть назван."""
    sources = [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}]
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
             "signals": marks.scan_page(DIRTY_PAGE)}

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    gaps = "\n".join(normalized["data_gaps"])

    assert "site_infra" not in normalized and "site_speed" not in normalized
    assert "Индексация и живые ссылки» не посчитана" in gaps
    assert "Скорость и мобильность» не посчитана" in gaps
    assert "строк этой проверки в отчёте нет" in gaps


def test_summary_and_checklist_open_the_report(analyzer):
    """Первая страница обязана быть первой — и в PDF, и в интерфейсе."""
    sources = [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}]
    facts = {
        "phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
        "crawl": CRAWL,
        "signals": marks.scan_page(DIRTY_PAGE),
        "infra": infra.probe_site(ORIGIN, robots_fetch, []),
        "speed": speed_block(),
    }

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    keys = list(normalized)
    order = list(analyzer_module.REPORT_SECTION_ORDER)

    assert keys[0] == "executive_summary"
    assert order[0] == "executive_summary"
    assert keys.index("action_priorities") + 1 == keys.index("implementation_checklist")
    assert len(normalized["executive_summary"]["rows"]) == 4
    assert normalized["executive_summary"]["rows"][0][1] == normalized["site_score"]["rows"][-1][2]


def test_the_checklist_in_the_report_is_longer_than_the_capped_queue(analyzer):
    sources = [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}]
    facts = {
        "phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
        "crawl": CRAWL,
        "signals": marks.scan_page(DIRTY_PAGE),
        "infra": infra.probe_site(ORIGIN, robots_fetch, []),
        "speed": speed_block(),
    }

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    checklist = normalized["implementation_checklist"]

    assert len(checklist["columns"]) == 3
    assert len(checklist["rows"]) > len(normalized["action_priorities"]["rows"])
    assert all(item[0].startswith("[ ] ") for item in checklist["rows"])


def test_a_silent_probe_leaves_the_queue_without_a_promise():
    """Ни находок, ни выводов: очередь обязана сказать, что её не из чего собирать."""
    silent = {"site_infra": table(
        *[row(f"a{i}", "нет данных", "не проверено — сервер молчит") for i in range(4)]),
        "site_checks": table(
            *[row(f"c{i}", "нет данных", "не проверено — сервер молчит") for i in range(4)]),
        "site_speed": table(
            *[row(f"s{i}", "нет данных", "не проверено — сервер молчит") for i in range(4)])}
    out = rating.assess(silent)

    assert out["total"] == 0
    assert out["priorities"]["rows"][0][1] == "Работы не записано"
    assert any("Общий балл не посчитан" in item for item in out["caveats"])
