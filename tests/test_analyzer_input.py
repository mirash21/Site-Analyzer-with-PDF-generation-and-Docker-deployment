"""Тесты входных данных анализа и нормализации итогового ответа.

Здесь проверяется то, из-за чего отчёт выглядел «не про сайт»: текст главной
страницы каталога — это меню, а не оффер; обрезка посреди слова; ответ модели
в форме, которую интерфейс не умеет рисовать.
"""

import pytest

from app.services import analyzer as analyzer_module
from app.services.analyzer import SiteAnalyzer


PAGE = """
<html><head><title>ТАТИНЖЕНЕР</title>
<meta name="description" content="Поставка металлорежущего инструмента">
<style>body { color: red }</style>
</head><body>
<nav><a href="/catalog">Каталог</a><a href="/about">О компании</a></nav>
<main>
  <h1>Лидер по поставке оборудования</h1>
  <p>Подбор инструмента по чертежам заказчика.</p>
  <ul><li>Сертификат качества AS9100</li><li>Доставка по России</li></ul>
</main>
<footer>© ООО «Татинженер», 2007</footer>
<script>var secret = "текст скрипта";</script>
</body></html>
"""


class FakeLLM:
    """Записывает промпты и отдаёт заранее заготовленные ответы."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def chat_json(self, system_prompt, user_prompt, **kwargs):
        self.calls.append(("chat_json", system_prompt, user_prompt))
        return self.answers.get("chat_json", {})

    def chat_with_system(self, system_prompt, user_prompt, **kwargs):
        self.calls.append(("chat_with_system", system_prompt, user_prompt))
        return self.answers.get("chat_with_system", "- короткий ответ")

    def prompts(self, kind):
        return [call for call in self.calls if call[0] == kind]


@pytest.fixture()
def analyzer():
    return SiteAnalyzer(FakeLLM())


def test_extraction_keeps_structure(analyzer):
    content, _ = analyzer.extract_page_text(PAGE)
    lines = [line for line in content.splitlines() if line.strip()]

    assert len(lines) >= 4, "текст должен оставаться построчным, а не одной строкой"
    assert "# ТАТИНЖЕНЕР" in content
    assert "Описание из мета-тегов: Поставка металлорежущего инструмента" in content
    assert "- Сертификат качества AS9100" in content
    assert "Подбор инструмента по чертежам заказчика." in content


def test_extraction_separates_chrome_from_content(analyzer):
    content, menu = analyzer.extract_page_text(PAGE)

    assert "текст скрипта" not in content
    assert "color: red" not in content
    assert "© ООО «Татинженер», 2007" not in content
    assert "Каталог" in menu
    assert menu.startswith("Меню и обвязка сайта")


def test_extraction_survives_empty_main_marker(analyzer):
    # Живые сайты ставят <main>/<article> декорацией: на tateng.ru <article>
    # был пустым, и разбор выдавал одну строку вместо всей страницы.
    html = """
    <html><head><title>Завод</title></head><body>
    <article></article>
    <div>
      <h1>Оборудование под заказ</h1>
      <p>Изготавливаем нестандартные узлы по чертежам заказчика.</p>
      <p>Гарантия на всю выпущенную продукцию — 24 месяца.</p>
      <p>Отгружаем в любой регион России транспортными компаниями.</p>
      <p>Собственный цех 1200 м2 и пять токарных станков с ЧПУ.</p>
    </div>
    </body></html>
    """
    content, _ = analyzer.extract_page_text(html)

    assert "Оборудование под заказ" in content
    assert content.count("\n") >= 4


def test_extraction_falls_back_to_div_markup(analyzer):
    html = """
    <html><head><title>Бутик</title></head><body>
    <div class="wrap">
      <div class="card">Куршер кожаный ручной работы, три цвета в наличии</div>
      <div class="card">Доставка по городу в день заказа, оплата при получении</div>
      <div class="card">Обмен и возврат в течение тридцати дней без вопросов</div>
    </div>
    </body></html>
    """
    content, _ = analyzer.extract_page_text(html)

    assert "Куршер кожаный ручной работы" in content
    assert "Обмен и возврат" in content


def test_candidate_links_matches_transliterated_paths(analyzer):
    # Путь транслитерируют, а якорь остаётся русским — нужен либо путь, либо текст ссылки.
    html = """
    <html><body>
      <a href="/katalog-produktsii/izmeritelnye-instrumenty-insize">Измерительные инструменты INSIZE</a>
      <a href="/page4.html">Новости</a>
    </body></html>
    """
    links = analyzer.candidate_links("https://tateng.ru/", html)

    assert links == ["https://tateng.ru/katalog-produktsii/izmeritelnye-instrumenty-insize"]


def test_business_facts_are_taken_out_of_markup_verbatim(analyzer):
    html = """
    <html><body>
    <a href="tel:+78432001122">+7 (843) 200-11-22</a>
    <a href="mailto:info@tateng.ru">написать</a>
    <p>Официальный дилер: ООО «Татинженер», ИНН 1657012345, ОГРН 1071690000000</p>
    <p>Резец проходной — 4 850 руб.</p>
    <p>Калибр-скоба INSIZE — 12 300 рублей</p>
    <p>Работаем с 2007 года, сертификат AS9100, тел. 8-917-200-11-22</p>
    </body></html>
    """

    facts = analyzer.extract_business_facts(html)

    assert facts["phones"] == ["+7 (843) 200-11-22", "+7 (917) 200-11-22"], (
        "один номер — одна запись, и в едином формате, а не как в разметке"
    )
    assert "info@tateng.ru" in facts["emails"]
    assert facts["legal_entities"] == ["ООО «Татинженер»"], "реквизиты не должны приклеиваться к названию"
    assert "ИНН 1657012345" in facts["requisites"]
    assert facts["prices"] == [4850, 12300], "«2007 года» и «AS9100» ценой стать не должны"


def test_business_facts_say_nothing_was_found(analyzer):
    html = "<html><body><p>Только текст без чисел и контактов</p></body></html>"

    facts = analyzer.extract_business_facts(html)
    rendered = analyzer.render_business_facts(facts)

    assert facts["prices"] == [] and facts["phones"] == []
    assert "не указаны" in rendered
    assert "не найдены" in rendered


def test_coverage_names_pages_and_missing_data(analyzer):
    sources = [
        {"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 2000},
        {"id": 2, "url": "https://tateng.ru/catalog", "path": "/catalog", "title": "C", "chars": 1000},
    ]
    facts = {"phones": ["+78432001122"], "emails": [], "legal_entities": [], "requisites": [], "prices": []}

    coverage = analyzer.describe_coverage(sources, facts, 18000)

    assert "Прочитано страниц: 2" in coverage
    assert "главная + 1 внутренних" in coverage
    assert "почта" in coverage and "цены" in coverage
    assert "телефоны" not in coverage.split("Не найдено")[1], "найденное не записывают в отсутствующее"


def test_report_carries_coverage_and_verbatim_data(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 2000}]
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": []}

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)

    assert "Прочитано страниц: 1" in normalized["data_coverage"]
    assert "raw_site_data" not in normalized, "из пустых данных раздел не делают"

    facts_with_prices = dict(facts, prices=[4850])
    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts_with_prices)
    assert "4 850" in normalized["raw_site_data"]


def test_string_lists_survive_every_shape_the_model_gives(analyzer):
    assert analyzer._normalize_string_list("- нет цен\n2. один призыв к действию\n") == [
        "нет цен",
        "один призыв к действию",
    ]
    assert analyzer._normalize_string_list([{"risk": "прайс неактуален"}, "прайс неактуален"]) == [
        "прайс неактуален"
    ]
    assert analyzer._normalize_string_list(None) == []
    assert analyzer._normalize_string_list("  ") == []


def test_missing_prices_are_reported_by_code_not_by_model(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 2000}]
    facts = {"phones": ["+7 (843) 200-11-22"], "emails": ["a@b.ru"], "legal_entities": ["ООО «Т»"], "requisites": [], "prices": []}

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)

    gaps = "\n".join(normalized["data_gaps"])
    assert "Цен" in gaps and "Реквизитов" in gaps
    assert "Телефонов" not in gaps and "Почты" not in gaps, "найденное не числится пропавшим"

    # Модель не освобождает от честного блока: её пункты добавляются к кодовым.
    normalized = analyzer._normalize_final_analysis(
        {"data_gaps": ["Нет кейсов по отраслям"]}, sources, facts
    )
    assert "Нет кейсов по отраслям" in normalized["data_gaps"]
    assert normalized["data_gaps"].index("Нет кейсов по отраслям") > 0


def test_sections_come_out_in_reading_order(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 2000}]

    normalized = analyzer._normalize_final_analysis(
        {
            "sources": {"columns": ["№"], "rows": [["1"]]},
            "ad_examples": [{"title": "t", "body": "b"}],
            "brief_analysis": "разбор",
            "comparison_table": {"columns": ["Сегмент"], "rows": [["Технологи"]]},
            "risks_and_checks": ["проверить дилерские права"],
            "kakoi_to_novyi_klyuch": "модель выдумала поле",
        },
        sources,
        {"phones": ["+7 (843) 200-11-22"], "prices": [100]},
    )

    keys = list(normalized)
    assert keys.index("brief_analysis") < keys.index("comparison_table") < keys.index("risks_and_checks")
    assert keys.index("risks_and_checks") < keys.index("data_gaps") < keys.index("sources")
    # Неизвестное поле не выбрасывается, но и в начало не лезет.
    assert keys[-1] == "kakoi_to_novyi_klyuch"


def test_prompt_asks_for_risks_and_honest_gaps(analyzer):
    analyzer.generate_final_analysis(
        [{"step_number": 1, "step": "шаг", "result": "ответ"}], "текст", [{"id": 1, "url": "u", "path": "/", "chars": 1}]
    )
    system_prompt = analyzer.llm_client.prompts("chat_json")[-1][1]

    for field in ('"site_gaps"', '"risks_and_checks"', '"data_gaps"'):
        assert field in system_prompt
    assert "не заменяя их догадками" in system_prompt


def test_fit_cuts_on_line_boundary(analyzer):
    text = "первая строка\nвторая строка\nтретья строка"
    fitted = analyzer._fit(text, 30)

    assert fitted.startswith("первая строка\nвторая строка")
    assert "не поместилось" in fitted
    # Обрезка по границе строки: последний целый блок не рвётся посреди слова.
    body = fitted.split("\n…")[0]
    assert body.splitlines()[-1] == "вторая строка"


def test_fit_breaks_long_paragraph_on_space(analyzer):
    text = "слово-заполнитель " * 40
    fitted = analyzer._fit(text, 40)

    assert fitted.endswith("слово-заполнитель\n…(остальное не поместилось в лимит)")
    assert not fitted.splitlines()[0].endswith("-")


def test_fit_leaves_short_text_alone(analyzer):
    assert analyzer._fit("короткий текст", 100) == "короткий текст"


def test_candidate_links_pick_offer_pages(analyzer):
    html = """
    <html><body>
      <a href="https://other.example/products">чужой домен</a>
      <a href="/catalog">каталог</a>
      <a href="/about#team">о компании</a>
      <a href="/catalog?page=2">каталог 2</a>
      <a href="mailto:a@b.c">почта</a>
      <a href="#top">якорь</a>
      <a href="/contacts">контакты</a>
    </body></html>
    """
    links = analyzer.candidate_links("https://tateng.ru/", html)

    assert links[:1] == ["https://tateng.ru/catalog"]
    assert all("other.example" not in link for link in links)
    assert all("mailto" not in link for link in links)
    # Контакты и «о компании» теперь берём намеренно: там телефоны, юрлицо и
    # реквизиты, без которых отчёт нельзя ни проверить, ни оценить.
    assert any("contacts" in link for link in links)
    assert any("about" in link for link in links)
    assert len(links) <= analyzer_module.MAX_EXTRA_PAGES


def test_links_spread_over_sections_instead_of_one_catalog(analyzer):
    html = "<html><body>" + "".join(
        f'<a href="/katalog-produktsii/group-{index}">Товары группы {index}</a>' for index in range(1, 8)
    ) + '<a href="/contacts">Контакты</a><a href="/prices">Цены</a></body></html>'

    links = analyzer.candidate_links("https://tateng.ru/", html)

    catalog_pages = [link for link in links if "/katalog-produktsii/" in link]
    assert len(catalog_pages) <= analyzer_module.MAX_PAGES_PER_SECTION
    assert any(link.endswith("/contacts") for link in links)
    assert any(link.endswith("/prices") for link in links)


def test_collect_site_text_adds_inner_pages_within_budget(analyzer, monkeypatch):
    inner = "<html><body><h1>Каталог</h1>" + "".join(
        f"<p>Позиция {index}: описание товара с характеристиками.</p>" for index in range(400)
    ) + "</body></html>"
    pages = {
        "https://tateng.ru/": PAGE,
        "https://tateng.ru/catalog": inner,
        "https://tateng.ru/about": inner,
    }
    monkeypatch.setattr(analyzer, "fetch_site_html", lambda url: pages[url])

    text = analyzer.collect_site_text("https://tateng.ru/")
    budget = analyzer_module.MAX_SITE_TEXT_LENGTH

    assert len(text) <= budget + 200, f"текст вышел за бюджет: {len(text)} > {budget}"
    assert "## Источник 2: /catalog" in text
    assert "Лидер по поставке оборудования" in text


def test_collect_site_evidence_numbers_every_read_page(analyzer, monkeypatch):
    inner = "<html><head><title>Каталог продукции</title></head><body><h1>Каталог</h1>" + "".join(
        f"<p>Позиция {index}: описание товара с характеристиками.</p>" for index in range(40)
    ) + "</body></html>"
    pages = {
        "https://tateng.ru/": PAGE,
        "https://tateng.ru/catalog": inner,
        "https://tateng.ru/about": inner,
    }
    monkeypatch.setattr(analyzer, "fetch_site_html", lambda url: pages[url])

    text, sources, facts = analyzer.collect_site_evidence("https://tateng.ru/")

    assert sources[0]["id"] == 1 and sources[0]["url"] == "https://tateng.ru/"
    assert [source["id"] for source in sources] == list(range(1, len(sources) + 1))
    assert sources[1]["title"] == "Каталог продукции"
    assert all(source["chars"] > 0 for source in sources)
    # Каждая прочитанная страница названа в тексте тем же номером, что и в реестре.
    for source in sources:
        assert f"## Источник {source['id']}:" in text
    # Дословные данные идут отдельным блоком, а не растворяются в тексте страниц.
    assert "## Данные, найденные в разметке страниц" in text
    assert isinstance(facts, dict) and "prices" in facts


def test_key_facts_resolve_source_numbers_to_real_urls(analyzer):
    sources = [
        {"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 900},
        {"id": 2, "url": "https://tateng.ru/catalog", "path": "/catalog", "title": "Каталог", "chars": 800},
    ]

    normalized = analyzer._normalize_final_analysis(
        {
            "brief_analysis": "текст",
            "key_facts": [
                {"fact": "Официальный представитель TaeguTec с 2007 года", "source": 1},
                {"fact": "Есть измерительный инструмент INSIZE", "source": "Источник 2"},
                {"fact": "Доставка во все регионы", "source": "https://tateng.ru/catalog"},
            ],
        },
        sources,
    )

    urls = [fact["source"] for fact in normalized["key_facts"]]
    assert urls == [
        "https://tateng.ru/",
        "https://tateng.ru/catalog",
        "https://tateng.ru/catalog",
    ]
    assert normalized["key_facts"][1]["page"] == "/catalog"


def test_invented_source_url_is_not_trusted(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 900}]

    normalized = analyzer._normalize_final_analysis(
        {
            "key_facts": [
                {"fact": "Цены от 1 200 рублей", "source": "https://tateng.ru/prices"},
                {"fact": "Сертификат AS9100", "source": 7},
                {"fact": "Факт без ссылки", "source": None},
            ]
        },
        sources,
    )

    unresolved = analyzer_module.SOURCE_REFERENCE_UNRESOLVED
    assert [fact["source"] for fact in normalized["key_facts"]] == [unresolved, unresolved, unresolved]
    assert all("page" not in fact for fact in normalized["key_facts"])


def test_report_lists_read_pages_as_a_table(analyzer):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 900}]

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "текст"}, sources)

    assert normalized["sources"]["columns"][0] == "№"
    assert normalized["sources"]["rows"] == [["1", "https://tateng.ru/", "ТАТИНЖЕНЕР", "900"]]


def test_final_prompt_asks_for_source_numbers_not_links(analyzer):
    analyzer.generate_final_analysis(
        [{"step_number": 1, "step": "шаг", "result": "ответ"}],
        "## Источник 1: /\nтекст главной",
        [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "T", "chars": 10}],
    )

    system_prompt = analyzer.llm_client.prompts("chat_json")[-1][1]
    assert '"key_facts"' in system_prompt
    assert "Источник N" in system_prompt
    assert "не выдумывай" in system_prompt


def test_collect_site_text_survives_broken_inner_page(analyzer, monkeypatch):
    def fetch(url):
        if url.endswith("/catalog"):
            raise Exception("503 от сервера сайта")
        return PAGE

    monkeypatch.setattr(analyzer, "fetch_site_html", fetch)

    text = analyzer.collect_site_text("https://tateng.ru/")
    assert "Лидер по поставке оборудования" in text


def test_collect_site_text_reports_script_only_pages(analyzer, monkeypatch):
    monkeypatch.setattr(analyzer, "fetch_site_html", lambda url: "<html><body><div id='app'></div></body></html>")

    with pytest.raises(Exception) as excinfo:
        analyzer.collect_site_text("https://tateng.ru/")
    assert "собран скриптами" in str(excinfo.value)


def test_steps_prompt_does_not_duplicate_the_site_text(analyzer):
    long_text = "длинный текст сайта " * 500
    analyzer.llm_client.answers = {"chat_json": {"steps": ["шаг один"]}}
    analyzer.generate_analysis_steps(long_text)
    kind, system_prompt, user_prompt = analyzer.llm_client.calls[-1]

    assert kind == "chat_json"
    assert "4-5 шагов" in system_prompt
    # Текст сайта уходит одним куском в user-промпт, а не вклеивается в инструкцию.
    assert long_text not in system_prompt
    assert user_prompt == long_text


def test_analysis_steps_are_wrapped_in_limits(analyzer):
    analyzer.execute_analysis_steps(["Выделить целевые сегменты"], "текст сайта")
    kind, system_prompt, user_prompt = analyzer.llm_client.calls[-1]

    assert "Выполни один шаг анализа сайта" in system_prompt
    assert "Выделить целевые сегменты" in system_prompt
    assert "до 1200 знаков" in system_prompt
    assert user_prompt == "текст сайта"


def test_final_prompt_requires_a_table_and_stops_quoting_source(analyzer):
    analyzer.generate_final_analysis(
        [{"step_number": 1, "step": "шаг", "result": "ответ" * 2000}],
        "текст сайта",
    )
    _, system_prompt, user_prompt = analyzer.llm_client.calls[-1]

    assert '"comparison_table"' in system_prompt
    assert '"ad_examples"' in system_prompt
    assert "Обязательно включи в анализ оригинальный текст сайта" not in system_prompt
    assert "Не вставляй в ответ оригинальный текст сайта целиком" in system_prompt
    # Промежуточный ответ тоже ограничивается: иначе итоговый промпт разрастается.
    assert len(system_prompt) < 6000
    assert len(user_prompt) < 5000


def test_normalization_turns_markdown_table_into_grid(analyzer):
    normalized = analyzer._normalize_final_analysis(
        {
            "brief_analysis": ["пункт один", "пункт два"],
            "ad_examples": ["Заголовок объявления\nТекст объявления", {"title": "T", "body": "B", "cta": ""}],
            "comparison_table": "| Сегмент | Боль |\n| --- | --- |\n| Технологи | срок |",
        }
    )

    assert normalized["brief_analysis"] == "пункт один\nпункт два"
    assert normalized["ad_examples"][0] == {"title": "Заголовок объявления", "body": "Текст объявления"}
    assert normalized["comparison_table"]["columns"] == ["Сегмент", "Боль"]
    assert normalized["comparison_table"]["rows"] == [["Технологи", "срок"]]


def test_normalization_drops_empty_or_missing_table(analyzer):
    assert "comparison_table" not in analyzer._normalize_final_analysis({"comparison_table": "не таблица"})
    assert "comparison_table" not in analyzer._normalize_final_analysis({})
    assert analyzer._normalize_final_analysis({"brief_analysis": "текст"})["brief_analysis"] == "текст"


def test_normalization_rejects_non_object_answer(analyzer):
    with pytest.raises(Exception) as excinfo:
        analyzer._normalize_final_analysis(["список вместо объекта"])
    assert "JSON-объекта" in str(excinfo.value)


def test_full_cycle_uses_structured_input(analyzer, monkeypatch):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 350}]
    facts = {"phones": ["+7 843 200 11 22"], "emails": [], "legal_entities": [], "requisites": [], "prices": [1200]}
    monkeypatch.setattr(
        analyzer,
        "collect_site_evidence",
        lambda url: ("структурированный текст сайта " * 10, sources, facts),
    )
    analyzer.llm_client.answers = {
        "chat_json": {
            "steps": ["Выделить сегменты"],
            "brief_analysis": "разбор",
            "key_facts": [{"fact": "Работаем с 2007 года", "source": 1}],
            "comparison_table": {"columns": ["Сегмент"], "rows": [["Технологи"]]},
        },
        "chat_with_system": "- короткий ответ",
    }
    monkeypatch.setattr(analyzer, "generate_analysis_steps", lambda text: ["Выделить сегменты"])

    result = analyzer.analyze_site("https://tateng.ru/")

    assert result["url"] == "https://tateng.ru/"
    assert result["intermediate_results"][0]["step_number"] == 1
    assert result["final_analysis"]["comparison_table"]["rows"] == [["Технологи"]]
    # Реестр прочитанного доезжает до отчёта, а факт получает ссылку на страницу.
    assert result["final_analysis"]["sources"]["rows"][0][1] == "https://tateng.ru/"
    assert result["final_analysis"]["key_facts"][0]["source"] == "https://tateng.ru/"
    assert "+7 843 200 11 22" in result["final_analysis"]["raw_site_data"]
    assert "Прочитано страниц: 1" in result["final_analysis"]["data_coverage"]
