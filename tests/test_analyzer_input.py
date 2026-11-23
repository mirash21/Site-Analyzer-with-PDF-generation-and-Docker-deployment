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
    # Объявления уехали в отдельный запрос: вместе с планом модель обрезалась
    # на середине ответа, и отчёт приходил наполовину пустой.
    assert '"ad_examples"' not in system_prompt
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
    assert normalized["ad_examples"][0]["title"] == "Заголовок объявления"
    assert normalized["ad_examples"][0]["body"] == "Текст объявления"
    assert normalized["comparison_table"]["columns"] == ["Сегмент", "Боль"]
    assert normalized["comparison_table"]["rows"] == [["Технологи", "срок"]]


def test_ads_are_measured_against_the_platform_limit(analyzer):
    title = "Противогазы ППМ в наличии и под заказ со склада в Казани с гарантией качества"

    plan = analyzer._normalize_campaign_plan(
        {
            "ad_examples": [
                {
                    "segment": "Промышленность",
                    "platform": "Яндекс Директ (поиск)",
                    "title": title,
                    "body": "Подбор по чертежам",
                    "cta": "Позвонить",
                }
            ]
        }
    )

    ad = plan["ad_examples"][0]
    assert ad["platform"] == "Яндекс Директ", "название площадки приводят к одному виду"
    assert ad["char_fit"] == f"заголовок {len(title)}/56 · текст 18/81"
    assert ad["limit_note"].startswith(f"заголовок длиннее на {len(title) - 56} зн.")


def test_telegram_ad_has_no_headline_to_measure(analyzer):
    plan = analyzer._normalize_campaign_plan(
        {"ad_examples": [{"segment": "Охотники", "platform": "Telegram Ads", "title": "х", "body": "текст"}]}
    )

    ad = plan["ad_examples"][0]
    assert ad["char_fit"] == "текст 5/160"
    assert "limit_note" not in ad


def test_one_ad_per_segment_is_reported_by_code(analyzer):
    plan = analyzer._normalize_campaign_plan(
        {
            "ad_examples": [
                {"segment": "Технологи", "platform": "Яндекс Директ", "title": "а", "body": "б"},
                {"segment": "Технологи", "platform": "VK Реклама", "title": "в", "body": "г"},
                {"segment": "Закупщики", "platform": "VK Реклама", "title": "д", "body": "е"},
            ]
        }
    )

    notes = "\n".join(plan["coverage_notes"])
    assert "Закупщики" in notes and "нужен второй вариант" in notes
    assert "Технологи" not in notes, "два объявления на сегмент — это норма"


def test_ads_are_capped_and_the_cut_is_reported(analyzer):
    plan = analyzer._normalize_campaign_plan({"ad_examples": [{"body": f"объявление {index}"} for index in range(20)]})

    assert len(plan["ad_examples"]) == analyzer_module.MAX_AD_EXAMPLES
    notes = "\n".join(plan["coverage_notes"])
    assert "оставлены первые" in notes
    assert "нет площадки" in notes, "без площадки лимит знаков не проверить"


def test_ad_notes_join_the_honest_block_without_erasing_it(analyzer, monkeypatch):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 350}]
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": []}
    monkeypatch.setattr(
        analyzer, "collect_site_evidence", lambda url: ("структурированный текст сайта " * 10, sources, facts)
    )
    monkeypatch.setattr(analyzer, "generate_analysis_steps", lambda text: ["Выделить сегменты"])
    analyzer.llm_client.answers = {
        "chat_json": {
            "steps": ["Выделить сегменты"],
            "brief_analysis": "разбор",
            "ad_examples": [{"segment": "Технологи", "platform": "Яндекс Директ", "title": "а", "body": "б"}],
        }
    }

    result = analyzer.analyze_site("https://tateng.ru/")

    gaps = "\n".join(result["final_analysis"]["data_gaps"])
    # Кодовый пропуск из разбора сайта и замечание о креативах — вместе.
    assert "Цен" in gaps
    assert "нужен второй вариант" in gaps
    assert "coverage_notes" not in result["final_analysis"]


def test_normalization_drops_empty_or_missing_table(analyzer):
    assert "comparison_table" not in analyzer._normalize_final_analysis({"comparison_table": "не таблица"})
    assert "comparison_table" not in analyzer._normalize_final_analysis({})
    assert analyzer._normalize_final_analysis({"brief_analysis": "текст"})["brief_analysis"] == "текст"


def test_normalization_rejects_non_object_answer(analyzer):
    with pytest.raises(Exception) as excinfo:
        analyzer._normalize_final_analysis(["список вместо объекта"])
    assert "JSON-объекта" in str(excinfo.value)


def test_campaign_plan_prompt_asks_for_semantics_and_negatives(analyzer):
    facts = {
        "phones": ["+7 (843) 200-11-22"],
        "emails": [],
        "legal_entities": [],
        "requisites": [],
        "prices": [],
    }
    analyzer.generate_campaign_plan(
        [{"step_number": 1, "step": "шаг", "result": "ответ"}], "текст сайта", facts
    )
    _, system_prompt, _ = analyzer.llm_client.calls[-1]

    assert '"keyword_seeds"' in system_prompt
    assert '"negative_keywords"' in system_prompt
    assert "минус-слова" in system_prompt
    # Креативы обязывают лимитами площадок и двумя вариантами на сегмент.
    assert "заголовок 56, текст 81" in system_prompt
    assert "ровно два варианта" in system_prompt
    # Объявления пишутся про реальные товары, поэтому дословные данные сайта —
    # и в этом запросе тоже.
    assert "+7 (843) 200-11-22" in system_prompt
    assert len(system_prompt) < 6000


def test_semantic_list_is_capped(analyzer):
    plan = analyzer._normalize_campaign_plan(
        {"keyword_seeds": [f"купить товар {index}" for index in range(80)], "negative_keywords": ["скачать"]}
    )

    assert len(plan["keyword_seeds"]) == analyzer_module.MAX_KEYWORDS_PER_LIST
    assert plan["keyword_seeds"][0] == "купить товар 0"


def test_a_phrase_cannot_be_a_keyword_and_a_negative(analyzer):
    plan = analyzer._normalize_campaign_plan(
        {
            "keyword_seeds": ["купить резец", "Резец проходной", "метчик м6"],
            "negative_keywords": ["резец ПРОХОДНОЙ", "скачать"],
        }
    )

    # Пересечение обнулило бы показы: решение за исключением — оно безопаснее
    # для бюджета.
    assert plan["keyword_seeds"] == ["купить резец", "метчик м6"]
    assert plan["negative_keywords"] == ["резец ПРОХОДНОЙ", "скачать"]


def test_campaign_plan_keeps_only_plan_fields(analyzer):
    plan = analyzer._normalize_campaign_plan(
        {
            "ad_instructions": ["собрать семантику", "настроить кампанию"],
            "keyword_seeds": ["резец проходной"],
            "negative_keywords": [],
            "brief_analysis": "модель заодно вернула разбор сайта",
            "key_facts": [{"fact": "Работаем с 2007 года", "source": 1}],
        }
    )

    assert plan["ad_instructions"] == "1. собрать семантику\n2. настроить кампанию"
    assert plan["keyword_seeds"] == ["резец проходной"]
    assert "negative_keywords" not in plan, "пустой список — это не раздел отчёта"
    # key_facts из ответа плана — сырой номер источника, а не ссылка: подмешать
    # их к готовому разбору значит лишить факты проверяемого адреса.
    assert "brief_analysis" not in plan and "key_facts" not in plan


def test_failed_campaign_plan_does_not_lose_the_report(analyzer, monkeypatch):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 350}]
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [1200]}
    monkeypatch.setattr(
        analyzer, "collect_site_evidence", lambda url: ("структурированный текст сайта " * 10, sources, facts)
    )
    monkeypatch.setattr(analyzer, "generate_analysis_steps", lambda text: ["Выделить сегменты"])

    def broken_plan(*args, **kwargs):
        raise Exception("429 от шлюза")

    monkeypatch.setattr(analyzer, "generate_campaign_plan", broken_plan)
    analyzer.llm_client.answers = {
        "chat_json": {
            "steps": ["Выделить сегменты"],
            "brief_analysis": "разбор",
            # Модель вернула поля плана в первом же ответе — они не нормализованы.
            "keyword_seeds": ["купить резец", {"странная": "форма"}],
        }
    }

    result = analyzer.analyze_site("https://tateng.ru/")

    assert result["final_analysis"]["brief_analysis"] == "разбор"
    assert "keyword_seeds" not in result["final_analysis"]
    assert any("Семантика" in gap for gap in result["final_analysis"]["data_gaps"])


def test_dozen_forms_of_a_number_all_come_out_one(analyzer):
    assert analyzer._positive_number("38,5 ₽") == 38.5
    assert analyzer._positive_number("от 40 рублей") == 40
    assert analyzer._positive_number(40) == 40
    assert analyzer._positive_number(None) is None
    assert analyzer._positive_number("нет данных") is None
    assert analyzer._positive_number(0) is None
    assert analyzer._positive_number(-5) is None
    assert analyzer._positive_number(True) is None, "True — не цена клика"


def test_economics_counts_from_site_prices_not_from_the_models_guess(analyzer):
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [4850, 9200, 12300]}

    economics = analyzer._build_economics(
        {"cpc": 40, "conversion_rate": 3, "margin": 25, "avg_check": 999999}, facts
    )
    rows = {row[0]: row for row in economics["economics_table"]["rows"]}

    assert rows["Средний чек"][1] == "9 200 ₽", "средний чек берут из цен сайта, а не из фантазии"
    assert "медиана" in rows["Средний чек"][2]
    assert rows["Кликов"][1] == "450"
    assert rows["Заявок"][1] == "13"
    assert rows["Цена заявки (CPL)"][1] == "1 384 ₽"
    assert rows["Прибыль с продажи"][1] == "2 300 ₽"
    assert rows["Продаж для окупаемости"][1] == "8"


def test_economics_admits_that_the_site_has_no_prices(analyzer):
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": []}

    economics = analyzer._build_economics(
        {"cpc": 50, "conversion_rate": None, "margin": 20, "avg_check": 30000}, facts
    )
    rows = {row[0]: row for row in economics["economics_table"]["rows"]}

    assert rows["Средний чек"][1] == "30 000 ₽"
    assert "оценка модели" in rows["Средний чек"][2], "догадку подписывают как догадку"
    assert rows["Заявок"][1] == analyzer_module.NO_DATA
    assert rows["Цена заявки (CPL)"][1] == analyzer_module.NO_DATA
    assert any("прайс" in line for line in economics["economics_assumptions"])


def test_economics_prompt_fixes_the_budget_and_asks_only_for_assumptions(analyzer):
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [100]}

    analyzer.generate_economics([{"step_number": 1, "step": "шаг", "result": "ответ"}], "текст", facts)
    _, system_prompt, _ = analyzer.llm_client.calls[-1]

    assert "18 000" in system_prompt
    assert '"cpc"' in system_prompt and '"avg_check"' in system_prompt
    assert "ставь null" in system_prompt
    assert "Их считает код" in system_prompt or "их считает код" in system_prompt
    assert len(system_prompt) < 3000


def test_missing_economics_is_reported_instead_of_invented(analyzer, monkeypatch):
    sources = [{"id": 1, "url": "https://tateng.ru/", "path": "/", "title": "ТАТИНЖЕНЕР", "chars": 350}]
    facts = {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": []}
    monkeypatch.setattr(
        analyzer, "collect_site_evidence", lambda url: ("структурированный текст сайта " * 10, sources, facts)
    )
    monkeypatch.setattr(analyzer, "generate_analysis_steps", lambda text: ["Выделить сегменты"])

    def broken_economics(*args, **kwargs):
        raise Exception("таймаут")

    monkeypatch.setattr(analyzer, "generate_economics", broken_economics)
    analyzer.llm_client.answers = {"chat_json": {"steps": ["Выделить сегменты"], "brief_analysis": "разбор"}}

    result = analyzer.analyze_site("https://tateng.ru/")

    assert result["final_analysis"]["brief_analysis"] == "разбор"
    assert "economics_table" not in result["final_analysis"]
    assert any("Экономика" in gap for gap in result["final_analysis"]["data_gaps"])


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
            "ad_instructions": ["собрать семантику"],
            "key_facts": [{"fact": "Работаем с 2007 года", "source": 1}],
            "comparison_table": {"columns": ["Сегмент"], "rows": [["Технологи"]]},
            "keyword_seeds": ["купить резец", "резец проходной", "скачать"],
            "negative_keywords": ["скачать", "бесплатно"],
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
    # План кампании — второй запрос, и он не затирает разбор сайта.
    assert result["final_analysis"]["keyword_seeds"] == ["купить резец", "резец проходной"]
    assert result["final_analysis"]["negative_keywords"] == ["скачать", "бесплатно"]
    keys = list(result["final_analysis"])
    assert keys.index("ad_instructions") < keys.index("keyword_seeds") < keys.index("negative_keywords")
    # Экономика — третий ответ модели, и он тоже доезжает до отчёта.
    assert result["final_analysis"]["economics_table"]["columns"] == ["Показатель", "Значение", "Откуда"]
    assert keys.index("negative_keywords") < keys.index("economics_table")
