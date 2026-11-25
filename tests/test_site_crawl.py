"""Обход глубже, текст не больше: читает много, модели отдаёт новое.

Проверки держат обе границы. Первая — вторая страница прайса всё-таки прочитана,
хотя в разметке листинга она стоит ниже двадцати карточек товаров. Вторая —
страницы с тем же текстом не разбираются на цитаты: бюджет знаков нужнее
раздела, которого обход ещё не видел, а проверки разметки считаются по всем
прочитанным, а не по процитированным.
"""

import pytest

from app.services import analyzer as analyzer_module
from app.services import site_crawl as crawl
from app.services import site_infra as infra
from app.services import site_signals as marks
from app.services.analyzer import SiteAnalyzer

HOME = "https://tateng.ru"


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


def make_page(title, body, links=()):
    anchors = "".join(f'<a href="{href}">{label}</a>' for href, label in links)
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<h1>{title}</h1>{body}<nav>{anchors}</nav></body></html>"
    )


def filler(topic, blocks=8):
    """Шаблонный текст: лексикон тот же, новым остаётся только слово темы."""
    return "".join(
        f"<p>{topic}: поставка, гарантия, паспорт изделия, отгрузка со склада, "
        f"заявка на {topic} {index:02d}.</p>"
        for index in range(blocks)
    )


def distinct(index, count=14):
    """Страница со своим лексиконом: обход прочтёт её новой, а не дублем."""
    root = f"метиз{chr(ord('а') + index)}"
    body = " ".join(f"{root}{chr(ord('а') + k)}" for k in range(count))
    return f"<p>{body} — характеристики и область применения.</p>"


PRICE_TEXT = (
    "<p>Прайс: арматура фланцевая 1200 руб., отвод стальной 850 руб., "
    "задвижка 4300 руб. Для мелкого опта НДС не облагается.</p>"
)
CONTACT_TEXT = (
    "<p>Адрес офиса: Казань, улица Техническая 15, режим работы, схема проезда, "
    "реквизиты ООО «Татметиз» ИНН 1657012345.</p>"
)
DELIVERY_TEXT = (
    "<p>Отгрузка транспортной компанией, срок две недели, паллеты, обрешётка, "
    "самовывоз в будние дни, доверенность на водителя.</p>"
)


class FakeSite:
    """Отдаёт заготовленные страницы и помнит порядок обращений."""

    def __init__(self, pages):
        self.pages = {crawl.norm(url): html for url, html in pages.items()}
        self.order = []

    def __call__(self, url):
        key = crawl.norm(url)
        self.order.append(key)
        html = self.pages.get(key)
        if html is None:
            raise ConnectionError(f"страница {url} не отвечает")
        return html

    def status_probe(self, url, method="GET"):
        return {"status": 0, "text": "", "chain": []}


# --- адреса и отпечатки ------------------------------------------------------


def test_anchor_and_trailing_slash_do_not_make_two_pages():
    assert crawl.norm("HTTPS://Tateng.RU/Katalog/#hits") == "https://tateng.ru/katalog"


def test_pages_of_one_listing_share_a_group():
    cases = {
        "https://tateng.ru/catalog?PAGEN_1=2": 2,
        "https://tateng.ru/catalog/?page=3": 3,
        "https://tateng.ru/catalog/page/4/": 4,
        "https://tateng.ru/catalog?p=5&sort=price": 5,
        "https://tateng.ru/catalog": 0,
    }
    groups = {}
    for url, number in cases.items():
        group, page = crawl.pagination_of(url)
        assert page == number, f"{url}: номер страницы потерян"
        groups.setdefault(group, []).append(url)

    assert len(groups) == 1, f"страницы одного листинга стали разными группами: {groups}"


def test_a_different_listing_is_a_different_group():
    assert (
        crawl.pagination_of("https://tateng.ru/catalog")[0]
        != crawl.pagination_of("https://tateng.ru/uslugi")[0]
    )


def test_numbers_make_content_new():
    """Тот же текст с другими ценами — не дубль: в нём другие предложения клиенту."""
    same = crawl.signature("прайс фрезерный станок по металлу")
    assert same and same == crawl.signature("станок прайс по металлу фрезерный")
    assert crawl.signature("фреза КМ2 цена 12500 руб") != crawl.signature("фреза Р6М5 цена 14800 руб")
    assert crawl.signature("") == ""
    assert crawl.signature("Прайс Фреза КМ2") == crawl.signature("прайс фреза км2"), (
        "шапка в другом регистре — тот же текст, а не новый раздел"
    )


# --- решения политики --------------------------------------------------------


def test_short_pages_are_refused_but_the_home_page_is_not():
    policy = crawl.CrawlPolicy(min_chars=200)

    assert policy.take("https://tateng.ru/ok", "короткий текст") == "thin"
    assert policy.take("https://tateng.ru/", "короткая главная", root=True) == "read"
    assert policy.refused["thin"] == 1
    assert policy.pages["https://tateng.ru"]["chars"] == len("короткая главная")


def test_the_same_text_under_another_address_is_a_duplicate():
    policy = crawl.CrawlPolicy(min_chars=10)
    text = filler("метизы")

    assert policy.take("https://tateng.ru/katalog", text) == "read"
    assert policy.take("https://tateng.ru/katalog", text) == "repeat"
    assert policy.take("https://tateng.ru/mobilnaya-versiya", text) == "duplicate"
    assert policy.duplicates == [
        {"url": "https://tateng.ru/mobilnaya-versiya", "same_as": "https://tateng.ru/katalog"}
    ]
    assert len(policy.pages) == 1, "дубль не занимает место прочитанной страницы"


def test_only_new_content_is_quoted_to_the_model():
    policy = crawl.CrawlPolicy(min_chars=10)
    policy.take("https://tateng.ru/", filler("метизы"))
    policy.take("https://tateng.ru/g-gruppa", filler("фрезы"))

    assert policy.goes_to_text("https://tateng.ru/") is True
    assert policy.goes_to_text("https://tateng.ru/g-gruppa") is False, (
        "страница прочитана, но новых слов в ней меньше порога — в прозу она не идёт"
    )
    assert policy.goes_to_text("https://tateng.ru/net-takoy") is False


def test_section_cap_refuses_the_rest_of_the_catalog():
    policy = crawl.CrawlPolicy(max_per_section=2, min_chars=10)
    for topic in ("балка", "труба"):
        policy.take(f"https://tateng.ru/catalog/{topic}", filler(topic))

    assert policy.reason_for("https://tateng.ru/catalog/gr99") == "section"
    assert policy.reason_for("https://tateng.ru/contacts") == ""
    assert policy.allow("https://tateng.ru/catalog/gr99") is False
    assert policy.refused["section"] == 1


def test_listing_group_stops_at_its_depth():
    policy = crawl.CrawlPolicy(max_per_group=2, min_chars=10)
    for number in (1, 2):
        policy.take(
            f"https://tateng.ru/catalog?PAGEN_1={number}",
            "".join(f"<p>Лист {index:02d}: позиция, цена, наличие.</p>" for index in range(number * 3)),
        )

    assert policy.reason_for("https://tateng.ru/catalog?PAGEN_1=3") == "group"
    assert policy.reason_for("https://tateng.ru/catalog/page/9/") == "group"


def test_time_budget_decides_before_a_request_is_spent():
    ticks = [0.0]
    policy = crawl.CrawlPolicy(budget=5, clock=lambda: ticks[0])
    policy.take("https://tateng.ru/", filler("метизы"), root=True)
    ticks[0] = 6.0

    assert policy.reason_for("https://tateng.ru/prices") == "time"
    assert not policy.wants_more()


def test_page_budget_stops_and_is_named_as_stopped():
    policy = crawl.CrawlPolicy(max_pages=1, min_chars=10)
    policy.take("https://tateng.ru/", filler("метизы"))

    assert policy.allow("https://tateng.ru/prices") is False
    assert policy.stopped == crawl.REASONS["budget"]
    assert crawl.crawl_gaps(policy.summary())[0].startswith("Сайт обойдён не полностью")


def test_links_left_in_the_queue_are_reported_as_unexamined():
    ticks = [0.0]
    policy = crawl.CrawlPolicy(budget=5, clock=lambda: ticks[0])
    policy.take("https://tateng.ru/", filler("метизы"), root=True)
    policy.leftover(0)
    assert policy.summary()["pending"] == 0 and policy.stopped == ""

    ticks[0] = 9.0
    policy.leftover(7)
    summary = policy.summary()

    assert summary["pending"] == 7
    assert summary["stopped"] == crawl.REASONS["time"]
    assert "непроверенных ссылок осталось: 7" in "\n".join(crawl.crawl_gaps(summary))


def test_queued_links_are_not_double_counted_as_refused():
    policy = crawl.CrawlPolicy(max_pages=1, min_chars=10)
    policy.take("https://tateng.ru/", filler("метизы"))
    policy.leftover(4)

    # Очередь — это «до этих ссылок не дошли», а не «отказали этим страницам».
    assert policy.refused == {}
    assert policy.summary()["pending"] == 4


# --- порядок обхода ----------------------------------------------------------


def test_pagination_outranks_the_cards_of_the_same_listing():
    policy = crawl.CrawlPolicy(min_chars=10)
    policy.take("https://tateng.ru/catalog", filler("фрезы"))
    links = [f"https://tateng.ru/catalog/item{index:02d}" for index in range(1, 20)]
    links += ["https://tateng.ru/catalog?PAGEN_1=2", "https://tateng.ru/contacts"]

    ranked = policy.rank(links)

    assert ranked[0] == "https://tateng.ru/contacts", "новый раздел интереснее карточки"
    assert ranked.index("https://tateng.ru/catalog?PAGEN_1=2") < ranked.index(
        "https://tateng.ru/catalog/item01"
    ), "вторая страница листинга стоит выше карточек, иначе до неё не дойти"
    assert ranked[-1].startswith("https://tateng.ru/catalog/item")


def test_earlier_listing_pages_come_before_later_ones():
    policy = crawl.CrawlPolicy(min_chars=10)
    policy.take("https://tateng.ru/catalog", filler("фрезы"))

    ranked = policy.rank([
        "https://tateng.ru/catalog?PAGEN_1=7",
        "https://tateng.ru/catalog?PAGEN_1=2",
        "https://tateng.ru/catalog?PAGEN_1=3",
    ])

    assert [crawl.pagination_of(url)[1] for url in ranked] == [2, 3, 7]


def test_pages_without_room_fall_to_the_end_of_the_queue():
    policy = crawl.CrawlPolicy(max_per_section=1, min_chars=10)
    policy.take("https://tateng.ru/catalog", filler("фрезы"))
    links = ["https://tateng.ru/catalog/item01", "https://tateng.ru/prices"]

    assert policy.rank(links) == ["https://tateng.ru/prices", "https://tateng.ru/catalog/item01"]
    assert policy.bucket_of("https://tateng.ru/catalog/item01") == 3


# --- таблицы, пробелы и текст промпта ---------------------------------------


def test_empty_crawl_claims_nothing():
    assert crawl.build_crawl_checks({})["rows"] == []
    assert crawl.crawl_gaps({}) == []
    assert crawl.render_crawl({}) == ""


def test_depth_row_separates_read_from_quoted():
    table = crawl.build_crawl_checks({
        "pages": 14, "limit": 18, "text_pages": 5, "sections": ["catalog", "prices"],
        "depth": 3, "paged": 2, "duplicates": [], "failures": [], "refused": {},
        "pending": 0, "stopped": "", "seconds": 12.4, "budget": 50.0,
    })
    row = row_of(table, "Глубина обхода")

    assert "прочитано страниц: 14 из 18" in row[1]
    assert "вошло 5" in row[1], "число цитат и число запросов — разные числа"
    assert "глубина вложенности: 3" in row[1]
    assert row[2].startswith(crawl.OK)
    assert row_of(table, "Пагинация листинга")[1] == "страниц списков прочитано: 2"


def test_shallow_crawl_is_a_complaint_not_a_normal_line():
    table = crawl.build_crawl_checks({
        "pages": 1, "limit": 18, "text_pages": 1, "sections": [], "depth": 0, "paged": 0,
        "duplicates": [], "failures": [], "refused": {}, "pending": 0, "stopped": "",
        "seconds": 1.0, "budget": 50.0,
    })

    assert row_of(table, "Глубина обхода")[2].startswith(crawl.CHECK)
    assert row_of(table, "Дубликаты содержания")[2].startswith(crawl.OK)


def test_unopened_pages_are_an_error_row():
    table = crawl.build_crawl_checks({
        "pages": 6, "limit": 18, "text_pages": 4, "sections": ["catalog"], "depth": 2,
        "paged": 0, "duplicates": [], "refused": {}, "pending": 0, "stopped": "",
        "failures": [{"url": "https://tateng.ru/old-catalog", "reason": "connection reset"}],
        "seconds": 9.0, "budget": 50.0,
    })
    row = row_of(table, "Страницы не открылись")

    assert row[2].startswith(crawl.BAD)
    assert "old-catalog" in row[1]


def test_every_row_shows_a_shared_verdict_word():
    table = crawl.build_crawl_checks({
        "pages": 11, "limit": 18, "text_pages": 3, "sections": ["catalog", "prices"],
        "depth": 3, "paged": 1,
        "duplicates": [{"url": "https://tateng.ru/m", "same_as": "https://tateng.ru/"}],
        "refused": {"section": 4, "thin": 2}, "pending": 6, "stopped": crawl.REASONS["budget"],
        "failures": [{"url": "https://tateng.ru/gone", "reason": "timeout"}],
        "seconds": 48.0, "budget": 50.0,
    })

    assert table["columns"] == ["Проверка", "Что посчитано кодом", "Вывод"]
    for row in table["rows"]:
        assert len(row) == 3 and all(cell.strip() for cell in row), row
        assert row[2].split(" —")[0] in (crawl.OK, crawl.CHECK, crawl.BAD), row
    assert "ссылок осталось непроверенными: 6" in row_of(table, "Полнота обхода")[1]
    assert "служебных или почти пустых: 2" in row_of(table, "Страницы без текста")[1]
    assert "tateng.ru/m совпадает с https://tateng.ru/" in row_of(table, "Дубликаты содержания")[2], (
        "дубль называют адресами, иначе клиент не поймёт, какой адрес чистить"
    )


def test_verdict_words_match_the_other_code_tables():
    """Клиент читает таблицы подряд: «ок» рядом с «норма» — две разные оценки."""
    assert (crawl.OK, crawl.CHECK) == (marks.OK, marks.CHECK) == (infra.OK, infra.CHECK)
    assert (crawl.OK, crawl.CHECK, crawl.BAD) == ("норма", "проверить", "ошибка")


def test_prompt_block_marks_the_ceiling_of_the_review():
    block = crawl.render_crawl({
        "pages": 12, "limit": 18, "text_pages": 4, "sections": ["catalog", "kontakty"],
        "duplicates": [{"url": "https://tateng.ru/print", "same_as": "https://tateng.ru/catalog"}],
        "failures": [{"url": "https://tateng.ru/broken", "reason": "404"}],
        "refused": {"section": 3}, "pending": 5, "stopped": crawl.REASONS["budget"],
        "seconds": 30.0, "budget": 50.0,
    })

    assert block.startswith("## Глубина обхода")
    assert "Текст для разбора дан по 4 страницам из 12" in block
    assert "https://tateng.ru/print = https://tateng.ru/catalog" in block
    assert "Не открылись: https://tateng.ru/broken" in block
    assert "Обход остановлен" in block


def test_coverage_does_not_pass_read_pages_off_as_quoted():
    sources = [{"id": 1, "url": HOME, "path": "/", "title": "T", "chars": 900}]

    assert crawl.describe_pages(sources, {}) == "Прочитано страниц: 1 (главная + 0 внутренних)."
    said = crawl.describe_pages(sources, {"pages": 9})
    assert said.startswith("Прочитано страниц: 9")
    assert "вошло 1" in said


# --- обход в составе анализа -------------------------------------------------


def collect(analyzer, monkeypatch, pages):
    site = FakeSite(pages)
    monkeypatch.setattr(analyzer, "fetch_site_html", site)
    monkeypatch.setattr(analyzer, "fetch_probe", site.status_probe)
    text, sources, facts = analyzer.collect_site_evidence(HOME + "/")
    return site, text, sources, facts


def test_crawl_reads_more_pages_than_the_model_is_given(analyzer, monkeypatch):
    pages = {
        HOME + "/": make_page("Завод метизов", filler("метизы"), [
            ("/catalog", "Каталог"), ("/prices", "Цены"), ("/contacts", "Контакты"),
            ("/delivery", "Доставка"),
            ("/katalog-produktsii/balka", "Группа балки"),
            ("/katalog-produktsii/truba", "Группа трубы"),
            ("/katalog-produktsii/shesternya", "Группа шестерни"),
            ("/katalog-produktsii/shurup", "Группа шурупы"),
            ("/katalog-produktsii/gajka", "Группа гайки"),
            ("/katalog-produktsii/zaklepki", "Группа заклёпки"),
        ]),
        HOME + "/catalog": make_page("Каталог", filler("фрезы")),
        HOME + "/prices": make_page("Цены", PRICE_TEXT * 2),
        HOME + "/contacts": make_page("Контакты", CONTACT_TEXT * 2),
        HOME + "/delivery": make_page("Доставка", DELIVERY_TEXT * 2),
    }
    for path, topic in (
        ("balka", "балка"), ("truba", "труба"), ("shesternya", "шестерня"),
        ("shurup", "шуруп"), ("gajka", "гайка"), ("zaklepki", "заклёпка"),
    ):
        pages[f"{HOME}/katalog-produktsii/{path}"] = make_page(
            f"Группа {topic}", filler(topic)
        )

    site, text, sources, facts = collect(analyzer, monkeypatch, pages)
    summary = facts["crawl"]

    assert summary["pages"] == len(site.order), "обход помнит каждую прочитанную страницу"
    assert summary["pages"] >= 5, "без внутренних страниц обход не глубже главной"
    assert len(sources) < summary["pages"], "шаблонные страницы не должны есть бюджет цитат"
    assert summary["text_pages"] == len(sources)
    assert facts["signals"]["pages"] == summary["pages"], (
        "разметку считают по всем прочитанным страницам, а не по процитированным"
    )
    assert summary["depth"] == 2, "обход обязан видеть третий уровень вложенности"
    assert "Цены" in text and "Доставка" in text, "новое содержание обязано дойти до модели"
    groups = [key for key in site.order if "katalog-produktsii" in key]
    assert len(groups) == crawl.MAX_PAGES_PER_SECTION, (
        "один раздел не имеет права вытеснить из обхода остальные"
    )


def test_one_listing_does_not_consume_the_whole_crawl(analyzer, monkeypatch):
    """У листинга может быть сорок страниц: обход идёт вглубь до потолка группы.

    Без потолка первые же страницы листинга забирают весь бюджет запросов, и
    контактов, условий поставки и цен другого раздела аудит не увидит вовсе.
    """
    listing = [(f"/catalog?PAGEN_1={number}", f"страница {number}") for number in range(2, 9)]
    pages = {
        HOME + "/": make_page("Завод метизов", filler("метизы"), [("/catalog", "Каталог фрез")]),
        HOME + "/catalog": make_page("Каталог фрез", filler("фрезы") + PRICE_TEXT, listing),
    }
    for number in range(2, 9):
        # Каждая страница листа обязана своим содержанием: иначе дубль не
        # засчитывается в группу, и потолок группы никто не проверяет.
        pages[f"{HOME}/catalog?PAGEN_1={number}"] = make_page(
            f"Лист {number:02d}",
            f"<p>Позиции листа {number:02d}: арматура фланцевая {number:02d} мм, отвод стальной, "
            f"задвижка, клапан, наличие на складе, отгрузка транспортной компанией.</p>",
        )

    site, _, _, facts = collect(analyzer, monkeypatch, pages)
    deeper = [key for key in site.order if "pagen_1" in key]

    assert len(deeper) + 1 == crawl.MAX_PAGES_PER_GROUP, (
        "листинг читают на глубину потолка группы, а не до конца каталога"
    )
    assert facts["crawl"]["refused"].get("group"), "отказ по группе обязан быть посчитан"


def test_second_listing_page_adds_its_prices(analyzer, monkeypatch):
    """Низ листинга важнее его середины: пагинацию обязаны прочитать.

    Bitrix пишет ссылку второй страницы как «?PAGEN_1=2» — без косой черты, и
    отбросив такие href вместе с якорями, обход не узнает о другом прайсе.
    Карточек на листе девятнадцать: идти по порядку разметки — значит извести
    потолок раздела на карточках, и второй страницы аудита клиент не дождётся.
    """
    cards = [(f"/catalog/item{index:02d}", f"позиция {index}") for index in range(1, 20)]
    pages = {
        HOME + "/": make_page("Завод метизов", filler("метизы"), [("/catalog", "Каталог фрез")]),
        HOME + "/catalog": make_page(
            "Каталог фрез",
            filler("фрезы") + "<p>Фреза КМ2 цена 12 500 руб.</p>",
            cards + [("?PAGEN_1=2", "2"), ("?PAGEN_1=3", "3")],
        ),
        HOME + "/catalog?pagen_1=2": make_page(
            "Каталог фрез, страница 2",
            filler("фрезы") + "<p>Фреза Р6М5 цена 14 800 руб.</p>",
        ),
    }
    for index in range(1, 20):
        pages[f"{HOME}/catalog/item{index:02d}"] = make_page(f"Позиция {index:02d}", distinct(index))

    site, _, _, facts = collect(analyzer, monkeypatch, pages)

    assert "https://tateng.ru/catalog?pagen_1=2" in site.order, (
        "пагинация стоит после карточек — без ранжирования обход до неё не доходит"
    )
    assert 14800 in facts["prices"] and 12500 in facts["prices"], (
        "цена со второй страницы листинга обязана попасть в факты"
    )
    assert facts["crawl"]["paged"] >= 1


def test_short_home_page_is_still_the_start_of_the_crawl(analyzer, monkeypatch):
    pages = {
        HOME + "/": make_page("Завод метизов", "<p>Метизы. Звоните.</p>", [("/catalog", "Каталог")]),
        HOME + "/catalog": make_page("Каталог", filler("фрезы")),
    }

    _, _, _, facts = collect(analyzer, monkeypatch, pages)
    table = crawl.build_crawl_checks(facts["crawl"])

    assert facts["crawl"]["pages"] == 2, "тонкая главная — всё равно прочитанная страница"
    assert facts["crawl"]["refused"].get("thin") is None
    assert row_of(table, "Глубина обхода")[1].startswith("прочитано страниц: 2")


def test_model_text_stays_inside_its_budget(analyzer, monkeypatch):
    links = [(f"/catalog-{index}/x{index:02d}", f"Каталог {index}") for index in range(1, 11)]
    pages = {HOME + "/": make_page("Завод метизов", filler("метизы"), links)}
    for index in range(1, 11):
        pages[f"{HOME}/catalog-{index}/x{index:02d}"] = make_page(
            f"Раздел {index}", distinct(index)
        )

    _, text, sources, facts = collect(analyzer, monkeypatch, pages)
    budget = analyzer_module.MAX_SITE_TEXT_LENGTH + analyzer_module.FACTS_BLOCK_ROOM

    assert facts["crawl"]["pages"] >= 8, "обход обязан прочитать больше, чем позволяют цитаты"
    assert len(sources) <= 7, (
        "семь источников — потолок текста модели; считают по константе, а не по её значению"
    )
    assert len(sources) < facts["crawl"]["pages"]
    assert len(text) <= budget + 40, f"текст модели вышел за бюджет: {len(text)} > {budget}"


def test_template_pages_stay_out_of_the_prose(analyzer, monkeypatch):
    pages = {
        HOME + "/": make_page("Завод метизов", filler("метизы"), [
            ("/catalog", "Каталог"), ("/prices", "Цены"),
            ("/katalog-produktsii/balka", "Группа 1"),
            ("/katalog-produktsii/truba", "Группа 2"),
        ]),
        HOME + "/catalog": make_page("Каталог", filler("фрезы")),
        HOME + "/prices": make_page("Цены", PRICE_TEXT * 2),
        HOME + "/katalog-produktsii/balka": make_page("Группа 1", filler("балка")),
        HOME + "/katalog-produktsii/truba": make_page("Группа 2", filler("труба")),
    }

    _, text, sources, facts = collect(analyzer, monkeypatch, pages)

    assert facts["crawl"]["pages"] == 5
    assert "балка" not in text and "труба" not in text, (
        "тот же лексикон под другим адресом не должен есть бюджет цитат"
    )
    assert "арматура" in text, "новое содержание обязано дойти до модели"


def test_crawl_stops_at_its_page_budget_and_says_so(analyzer, monkeypatch):
    links = [(f"/catalog-{index}/x{index:02d}", f"Каталог {index}") for index in range(1, 26)]
    pages = {HOME + "/": make_page("Завод метизов", filler("метизы"), links)}
    for index in range(1, 26):
        pages[f"{HOME}/catalog-{index}/x{index:02d}"] = make_page(
            f"Раздел {index}", distinct(index)
        )

    _, _, _, facts = collect(analyzer, monkeypatch, pages)
    summary = facts["crawl"]
    table = crawl.build_crawl_checks(summary)

    assert summary["pages"] == crawl.MAX_CRAWL_PAGES, "обход не обязан читать больше потолка"
    assert summary["pending"] == 25 + 1 - crawl.MAX_CRAWL_PAGES
    assert summary["stopped"] == crawl.REASONS["budget"]
    assert "ссылок осталось непроверенными: 8" in row_of(table, "Полнота обхода")[1]
    assert "непроверенных ссылок осталось: 8" in "\n".join(crawl.crawl_gaps(summary))


def test_pages_that_never_opened_become_a_finding(analyzer, monkeypatch):
    pages = {
        HOME + "/": make_page("Завод метизов", filler("метизы"), [
            ("/catalog", "Каталог"), ("/prices", "Цены"), ("/catalog-old", "Старый каталог"),
        ]),
        HOME + "/catalog": make_page("Каталог", filler("фрезы")),
        # /prices и /gone намеренно отсутствуют — страница не отвечает.
    }

    _, _, _, facts = collect(analyzer, monkeypatch, pages)
    table = crawl.build_crawl_checks(facts["crawl"])

    urls = [item["url"] for item in facts["crawl"]["failures"]]
    assert "https://tateng.ru/prices" in urls and "https://tateng.ru/catalog-old" in urls
    assert row_of(table, "Страницы не открылись")[2].startswith(crawl.BAD)


def test_thin_pages_are_counted_and_said_loudly(analyzer, monkeypatch):
    pages = {
        HOME + "/": make_page("Завод метизов", filler("метизы"), [
            ("/catalog", "Каталог"), ("/prices", "Цены"),
        ]),
        HOME + "/catalog": make_page("Каталог", filler("фрезы")),
        HOME + "/prices": make_page("Цены", "<p>Скоро.</p>"),
    }

    _, _, _, facts = collect(analyzer, monkeypatch, pages)

    assert facts["crawl"]["refused"].get("thin") == 1
    assert facts["signals"]["pages"] == facts["crawl"]["pages"], (
        "почти пустая страница не участвует в проверках разметки"
    )
    assert "служебных или почти пустых: 1" in row_of(
        crawl.build_crawl_checks(facts["crawl"]), "Страницы без текста"
    )[1]


def test_crawl_joins_every_facts_prompt(analyzer):
    facts = {
        "phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
        "crawl": {"pages": 7, "limit": crawl.MAX_CRAWL_PAGES, "text_pages": 3,
                  "sections": ["catalog"], "duplicates": [], "failures": [],
                  "refused": {"section": 2}, "pending": 2, "stopped": crawl.REASONS["budget"],
                  "seconds": 20.0, "budget": 50.0},
        "signals": marks.scan_page(make_page("Каталог", filler("фрезы"))),
        "infra": infra.probe_site(
            HOME, lambda url, method="GET": {"status": 404, "text": "", "chain": []}, []
        ),
    }
    steps = [{"step_number": 1, "step": "шаг", "result": "ответ"}]
    sources = [{"id": 1, "url": HOME, "path": "/", "title": "T", "chars": 900}]

    analyzer.generate_final_analysis(steps, "текст", sources, facts)
    analyzer.generate_campaign_plan(steps, "текст", facts)
    analyzer.generate_economics(steps, "текст", facts)

    prompts = [call[1] for call in analyzer.llm_client.prompts("chat_json")]
    assert len(prompts) == 3, "проверка не должна молча пропустить новый запрос"
    for prompt in prompts:
        assert "Глубина обхода" in prompt
        assert prompt.index("Глубина обхода") < prompt.index("Ответ строго в JSON")


def test_crawl_reaches_the_report_after_the_server_checks(analyzer):
    sources = [
        {"id": index, "url": f"{HOME}/p{index}", "path": f"/p{index}", "title": "T", "chars": 900}
        for index in range(1, 5)
    ]
    facts = {
        "phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
        "crawl": {"pages": 9, "limit": crawl.MAX_CRAWL_PAGES, "text_pages": 4,
                  "sections": ["catalog", "prices"], "depth": 2, "paged": 3,
                  "duplicates": [{"url": "https://tateng.ru/print", "same_as": HOME}],
                  "failures": [], "refused": {"section": 3}, "pending": 0, "stopped": "",
                  "seconds": 18.0, "budget": 50.0},
        "signals": marks.scan_page(make_page("Каталог", filler("фрезы"))),
        "infra": infra.probe_site(
            HOME, lambda url, method="GET": {"status": 404, "text": "", "chain": []}, []
        ),
    }

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    keys = list(normalized)

    assert keys.index("site_infra") < keys.index("site_crawl")
    order = list(analyzer_module.REPORT_SECTION_ORDER)
    assert order.index("site_infra") < order.index("site_crawl") < order.index("ad_instructions")
    assert row_of(normalized["site_crawl"], "Глубина обхода")[1].startswith("прочитано страниц: 9")
    assert row_of(normalized["site_crawl"], "Дубликаты содержания")[2].startswith(crawl.CHECK)
    joined = "\n".join(normalized["data_gaps"])
    assert "прочитаны не все страницы" in joined, "недосмотр обхода попадает в пробелы сам"
    assert "Прочитано страниц: 9" in normalized["data_coverage"]
    assert "вошло 4" in normalized["data_coverage"]


def test_report_order_names_the_new_section_once():
    order = list(analyzer_module.REPORT_SECTION_ORDER)

    assert order.count("site_crawl") == 1


def test_final_prompt_bounds_conclusions_to_pages_the_crawl_reached(analyzer):
    """Не прочитано — не утверждается: обход знает, где он остановился."""
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": []}
    sources = [{"id": 1, "url": HOME, "path": "/", "title": "T", "chars": 900}]

    analyzer.generate_final_analysis(
        [{"step_number": 1, "step": "шаг", "result": "ответ"}], "текст", sources, facts
    )
    system = analyzer.llm_client.prompts("chat_json")[0][1]

    assert "не пиши «на сайте нет X»" in system, (
        "без этой границы модель объявляет отсутствующим то, до чего обход не дошёл"
    )
