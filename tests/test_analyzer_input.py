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
    assert all("contacts" not in link for link in links), "страница без товарных ключей не берётся"
    assert len(links) <= analyzer_module.MAX_EXTRA_PAGES


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

    assert len(text) <= budget + 60, f"текст вышел за бюджет: {len(text)} > {budget}"
    assert "## Страница /catalog" in text
    assert "Лидер по поставке оборудования" in text


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
    monkeypatch.setattr(
        analyzer,
        "collect_site_text",
        lambda url: "структурированный текст сайта " * 10,
    )
    analyzer.llm_client.answers = {
        "chat_json": {
            "steps": ["Выделить сегменты"],
            "brief_analysis": "разбор",
            "comparison_table": {"columns": ["Сегмент"], "rows": [["Технологи"]]},
        },
        "chat_with_system": "- короткий ответ",
    }
    monkeypatch.setattr(analyzer, "generate_analysis_steps", lambda text: ["Выделить сегменты"])

    result = analyzer.analyze_site("https://tateng.ru/")

    assert result["url"] == "https://tateng.ru/"
    assert result["intermediate_results"][0]["step_number"] == 1
    assert result["final_analysis"]["comparison_table"]["rows"] == [["Технологи"]]
