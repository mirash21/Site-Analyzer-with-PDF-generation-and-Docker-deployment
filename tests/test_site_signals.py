"""Проверки, которые код считает по разметке, без сторонних сервисов.

Ценность этих строк в том, что их нельзя выдумать: счётчик либо стоит в HTML,
либо нет. Поэтому тесты держат обе стороны — и что найденное не теряется, и что
слово «Метрика» в тексте страницы не записывается в установленный счётчик.
"""

import pytest

from app.services import analyzer as analyzer_module
from app.services import site_signals as marks
from app.services.analyzer import SiteAnalyzer

GOOD_PAGE = """
<html><head><title>Инструмент</title>
<meta name="description" content="Поставка металлорежущего инструмента">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://tateng.ru/katalog">
<meta property="og:title" content="Инструмент">
<script type="application/ld+json">{"@type":"Organization"}</script>
<script src="https://mc.yandex.ru/metrika/tag.js"></script>
</head><body>
<nav><a href="/catalog">Каталог</a><a href="/about">О компании</a></nav>
<h1>Поставка инструмента</h1>
<form><input name="phone" type="tel"></form>
<a href="tel:+78432001122">Позвонить</a>
<a href="mailto:info@tateng.ru">Написать</a>
<a href="https://wa.me/78432001122">WhatsApp</a>
<img src="stationok.png" alt="Фрезерный станок">
</body></html>
"""

BAD_PAGE = """
<html><head><title>Каталог</title></head><body>
<h1>Каталог</h1><h1>Прайс-лист</h1>
<p>Мы подключаем Яндекс Метрику и следим за статистикой обращений.</p>
<img src="a.png"><img src="b.png" alt="">
</body></html>
"""


class FakeLLM:
    """Записывает промпты, чтобы видеть, что именно ушло модели."""

    def __init__(self):
        self.calls = []

    def chat_json(self, system_prompt, user_prompt, **kwargs):
        self.calls.append(("chat_json", system_prompt, user_prompt))
        return {}

    def chat_with_system(self, system_prompt, user_prompt, **kwargs):
        self.calls.append(("chat_with_system", system_prompt, user_prompt))
        return "-"

    def prompts(self, kind):
        return [call for call in self.calls if call[0] == kind]


@pytest.fixture()
def analyzer():
    return SiteAnalyzer(FakeLLM())


def row_of(table, check):
    return next(row for row in table["rows"] if row[0] == check)


def facts_with(signals):
    return {
        "phones": [],
        "emails": [],
        "legal_entities": [],
        "requisites": [],
        "prices": [],
        "signals": signals,
    }


def test_clean_page_leaves_nothing_to_check():
    table = marks.build_site_checks(marks.scan_page(GOOD_PAGE))
    complaints = [row for row in table["rows"] if not row[2].startswith(marks.OK)]

    assert not complaints, f"на странице, где всё стоит, ругаться нечем: {complaints}"


def test_words_about_analytics_are_not_an_installed_counter():
    table = marks.build_site_checks(marks.scan_page(BAD_PAGE))

    assert marks.scan_page(BAD_PAGE)["analytics"] == {}, "упоминание текстом — не счётчик"
    assert row_of(table, "Счётчики и пиксели")[1] == "ни одного в разметке"
    assert row_of(table, "Счётчики и пиксели")[2].startswith(marks.MISSING)
    assert row_of(table, "Формы заявок")[2].startswith(marks.MISSING)
    assert "с двумя и больше: 1" in row_of(table, "H1 на странице")[1]
    assert "2 из 2 (100%)" in row_of(table, "Картинки без alt")[1]


def test_findings_are_counted_per_page_not_in_total():
    merged = marks.merge_signals(marks.scan_page(GOOD_PAGE), marks.scan_page(BAD_PAGE))
    table = marks.build_site_checks(merged)

    assert merged["pages"] == 2
    assert merged["analytics"] == {"Яндекс Метрика": 1}
    # Метрика на половине страниц — это «стоит не везде», а не «стоит».
    assert "на 1 из 2" in row_of(table, "Счётчики и пиксели")[1]
    assert "без description: 1 из 2" in row_of(table, "Описание (meta description)")[1]
    assert "og-теги: 1 из 2" in row_of(table, "OG-теги для ссылок в соцсетях")[1]


def test_messengers_and_contacts_come_out_of_links():
    signals = marks.scan_page(GOOD_PAGE)

    assert signals["messengers"] == {"WhatsApp": 1}
    assert signals["tel_links"] == 1 and signals["mailto_links"] == 1
    assert signals["forms"] == 1 and signals["inputs"] == 1


def test_every_row_states_check_observation_and_verdict():
    table = marks.build_site_checks(marks.scan_page(BAD_PAGE))

    assert table["columns"] == ["Проверка", "Что видно на страницах", "Вывод"]
    assert len(table["rows"]) >= 12, "проверок не должно стать молча меньше"
    for row in table["rows"]:
        assert len(row) == 3 and all(cell.strip() for cell in row), row
        assert row[2].split(" —")[0] in (marks.OK, marks.CHECK, marks.MISSING), row


def test_unread_site_produces_no_claims():
    empty = marks.scan_page("   ")

    assert empty["pages"] == 0
    assert marks.build_site_checks(empty)["rows"] == []
    assert marks.signal_gaps(empty) == []


def test_broken_markup_does_not_break_the_audit():
    signals = marks.scan_page("<html><body><div class=\"x\"><script>var a = {</script>")

    assert signals["pages"] == 1
    assert signals["titles_missing"] == 1


def test_missing_analytics_and_forms_become_honest_gaps():
    gaps = "\n".join(marks.signal_gaps(marks.scan_page(BAD_PAGE)))

    assert "счётчик" in gaps.lower() and "форм" in gaps.lower()
    assert marks.signal_gaps(marks.scan_page(GOOD_PAGE)) == []


def test_prompt_block_repeats_computed_numbers():
    block = marks.render_signals(marks.merge_signals(
        marks.scan_page(GOOD_PAGE), marks.scan_page(BAD_PAGE)
    ))

    assert block.startswith("## Проверки по разметке")
    assert "1 из 2 страниц" in block
    assert "Яндекс Метрика" in block
    assert "картинок без alt: 2 из 3" in block


def test_markup_checks_join_every_facts_prompt(analyzer):
    facts = facts_with(marks.scan_page(BAD_PAGE))
    steps = [{"step_number": 1, "step": "шаг", "result": "ответ"}]
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 900}]

    analyzer.generate_final_analysis(steps, "текст", sources, facts)
    analyzer.generate_campaign_plan(steps, "текст", facts)
    analyzer.generate_economics(steps, "текст", facts)

    prompts = [call[1] for call in analyzer.llm_client.prompts("chat_json")]
    assert len(prompts) == 3, "проверка не должна молча пропустить новый запрос"
    for prompt in prompts:
        assert "Проверки по разметке" in prompt
        assert prompt.index("Проверки по разметке") < prompt.index("Ответ строго в JSON"), (
            "блок стоит до требований к формату, иначе модель читает его как пояснение"
        )


def test_checks_reach_the_report_and_their_gaps_too(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 900}]
    normalized = analyzer._normalize_final_analysis(
        {"brief_analysis": "разбор", "site_gaps": ["Один экран без оффера"]},
        sources,
        facts_with(marks.scan_page(BAD_PAGE)),
    )

    assert row_of(normalized["site_checks"], "Счётчики и пиксели")[2].startswith(marks.MISSING)
    joined = "\n".join(normalized["data_gaps"])
    assert "счётчик" in joined.lower(), "код не ждёт, пока модель сама вспомнит про счётчики"
    keys = list(normalized)
    # Вывод модели идёт вперёд, посчитанные основания — сразу под ним.
    assert keys.index("site_gaps") < keys.index("site_checks") < keys.index("data_gaps")


def test_checks_stay_before_the_ad_block():
    order = list(analyzer_module.REPORT_SECTION_ORDER)

    assert order.index("site_checks") < order.index("ad_instructions")


def test_report_without_read_pages_has_no_checks_section(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 900}]

    normalized = analyzer._normalize_final_analysis(
        {"brief_analysis": "разбор"}, sources, facts_with(marks.scan_page(""))
    )

    assert "site_checks" not in normalized, "о непрочитанном сайте не пишут как о проверенном"


def test_evidence_collection_counts_every_page_it_read(analyzer, monkeypatch):
    inner = BAD_PAGE.replace(
        "</body>",
        "".join(f"<p>Позиция {index}: характеристики, описание, применимость.</p>"
                for index in range(30))
        + '<a href="/delivery">Доставка</a></body>',
    )
    pages = {
        "https://tateng.ru/": GOOD_PAGE,
        "https://tateng.ru/catalog": inner,
        "https://tateng.ru/about": inner,
    }
    monkeypatch.setattr(analyzer, "fetch_site_html", lambda url: pages.get(url, ""))
    probed = []

    def fake_probe(url, method="GET"):
        probed.append(url)
        return {"status": 0, "text": "", "chain": []}

    monkeypatch.setattr(analyzer, "fetch_probe", fake_probe)

    _, sources, facts = analyzer.collect_site_evidence("https://tateng.ru/")

    assert len(sources) >= 2, "тест без внутренних страниц ничего не проверяет"
    assert facts["signals"]["pages"] == facts["crawl"]["pages"], (
        "разметку считают по всем прочитанным страницам, а не по процитированным"
    )
    assert len(sources) <= facts["crawl"]["pages"], "цитат прочитано не больше, чем страниц"
    assert facts["signals"]["analytics"] == {"Яндекс Метрика": 1}, "со страниц без счётчика их не добавляют"
    assert "https://tateng.ru/delivery" in probed, (
        "ссылки внутренних страниц обязаны попасть в пробу, а не только ссылки главной"
    )
    assert "https://tateng.ru/catalog" not in probed, "прочитанную страницу не перепроверяют"


# --- то, что раньше держалось на догадке ------------------------------------


UPPER_PAGE = """
<HTML><HEAD><TITLE>Станки</TITLE>
<META NAME="DESCRIPTION" CONTENT="Поставка станков и инструмента">
<META NAME="VIEWPORT" CONTENT="width=device-width, initial-scale=1">
<LINK REL="CANONICAL" HREF="https://tateng.ru/katalog">
<META PROPERTY="OG:TITLE" CONTENT="Станки">
<SCRIPT TYPE="APPLICATION/LD+JSON">{"@type":"Organization"}</SCRIPT>
<SCRIPT SRC="https://mc.yandex.ru/metrika/tag.js"></SCRIPT>
</HEAD><BODY>
<H1>Поставка станков</H1>
<FORM><INPUT NAME="phone" TYPE="TEL"></FORM>
<A HREF="TEL:+78432001122">Позвонить</A>
<A HREF="MAILTO:INFO@TATENG.RU">Написать</A>
<A HREF="HTTPS://WA.ME/78432001122">WhatsApp</A>
<IMG SRC="stationok.png" ALT="Фрезерный станок">
</BODY></HTML>
"""


def alt_page(missing: int, total: int) -> str:
    """Страница из total картинок, где missing — без alt."""
    pictures = "".join(
        f'<img src="{index}.png">' if index < missing
        else f'<img src="{index}.png" alt="Станок">' for index in range(total)
    )
    return f"<html><head><title>Станки</title></head><body>{pictures}</body></html>"


def test_uppercase_markup_is_the_same_markup():
    """Регистр атрибутов не превращает стоящее в «не найдено»."""
    table = marks.build_site_checks(marks.scan_page(UPPER_PAGE))
    complaints = [row for row in table["rows"] if not row[2].startswith(marks.OK)]

    assert not complaints, f"регистр не должен менять вывод: {complaints}"


def test_tag_manager_is_not_reported_as_event_tracking():
    """Консолидатор тегов прячет содержимое: про события по нему молчат."""
    page = GOOD_PAGE.replace(
        "</head>",
        '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script></head>',
    )
    row_cell = row_of(marks.build_site_checks(marks.scan_page(page)), "Счётчики и пиксели")

    assert "Tag Manager" in row_cell[1]
    assert "видно только в кабинете" in row_cell[2]


def test_counter_on_every_page_is_not_flagged_with_coverage():
    row_cell = row_of(marks.build_site_checks(marks.scan_page(GOOD_PAGE)), "Счётчики и пиксели")

    assert row_cell[1] == "найдены: Яндекс Метрика", "охват 1 из 1 — это не охват"


def test_quarter_of_pictures_without_alt_is_still_the_norm():
    quarter = marks.build_site_checks(marks.scan_page(alt_page(1, 4)))
    half = marks.build_site_checks(marks.scan_page(alt_page(2, 4)))

    assert row_of(quarter, "Картинки без alt")[1] == "1 из 4 (25%)"
    assert row_of(quarter, "Картинки без alt")[2].startswith(marks.OK)
    assert row_of(half, "Картинки без alt")[1] == "2 из 4 (50%)"
    assert row_of(half, "Картинки без alt")[2].startswith(marks.CHECK)


def test_a_site_without_pictures_is_not_blamed_for_alt():
    row_cell = row_of(
        marks.build_site_checks(marks.scan_page(alt_page(0, 0))), "Картинки без alt")

    assert row_cell[1] == "картинок нет"
    assert row_cell[2].startswith(marks.OK)
    assert "проверять нечего" in row_cell[2]


def test_merge_survives_a_side_that_was_never_scanned():
    merged = marks.merge_signals(None, marks.scan_page(GOOD_PAGE))

    assert merged["pages"] == 1 and merged["analytics"] == {"Яндекс Метрика": 1}
    assert marks.merge_signals(merged, None)["forms"] == 1


def test_prompt_block_names_absence_instead_of_zero():
    block = marks.render_signals(marks.scan_page(GOOD_PAGE))

    assert "без title: нет" in block
    assert "картинок без alt: 0 из 1" in block


def test_a_form_without_counters_leaves_exactly_one_gap():
    page = BAD_PAGE.replace("</body>", '<form><input name="q"></form></body>')

    assert marks.signal_gaps(marks.scan_page(page)) == [marks.NO_ANALYTICS_GAP]


def test_absence_of_pages_is_not_a_missing_count():
    assert marks._missing(3, 0) == "нет данных"
