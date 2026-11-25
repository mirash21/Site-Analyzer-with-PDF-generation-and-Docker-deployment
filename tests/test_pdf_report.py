"""Тесты серверной сборки PDF-отчёта.

Проверяют не пиксели, а контракт: markdown ответа модели превращается в
настоящие блоки (таблицы, списки, заголовки), содержимое чужого сайта не может
подставить разметку, а пустой или битый вход не уронить скачивание.
"""

import re

import pytest
from reportlab.platypus import Paragraph, Table

from app.services import pdf_report
from app.services.pdf_report import (
    PDFRenderError,
    build_analysis_pdf,
    format_created_at,
    inline_markup,
    markdown_flowables,
    pdf_filename,
    value_flowables,
)


def styles():
    return pdf_report._styles()


def sample_analysis():
    return {
        "url": "https://tateng.ru/",
        "created_at": "2026-11-23 19:47:38",
        "steps": ["Определить целевые сегменты", "Разобрать ассортимент"],
        "intermediate_results": [
            {
                "step_number": 1,
                "step": "Определить целевые сегменты",
                "result": "# Сегменты\n\n- **Технологи** — подбор по чертежу\n- Закупщики — цена\n\n"
                "| Сегмент | Потребность |\n| --- | --- |\n| Технологи | чертеж |\n",
            }
        ],
        "final_analysis": {
            "brief_analysis": "Сайт поставщика инструмента.\n\nКлючевые факты: **AS9100**, доставка по РФ.",
            "ad_instructions": "1. Выбрать сегмент\n2. Написать заголовок",
            "ad_examples": [
                {"title": "Пост для Telegram", "body": "Подбор по чертежу", "cta": "Отправить чертёж"}
            ],
        },
    }


def test_pdf_is_a_real_pdf_document():
    payload = build_analysis_pdf(sample_analysis())
    assert payload.startswith(b"%PDF-")
    assert b"%%EOF" in payload[-2048:]


def test_empty_analysis_still_produces_pdf():
    assert build_analysis_pdf({}).startswith(b"%PDF-")


def test_long_report_is_paginated():
    analysis = sample_analysis()
    analysis["intermediate_results"] = [
        {
            "step_number": index,
            "step": f"шаг {index}",
            "result": ("Абзац с довольно длинным текстом для проверки разбивки. " * 60),
        }
        for index in range(1, 7)
    ]
    payload = build_analysis_pdf(analysis)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", payload))
    assert pages >= 2


def test_keyword_lists_are_a_compact_block_not_a_column_of_bullets():
    analysis = sample_analysis()
    analysis["final_analysis"]["keyword_seeds"] = ["резец проходной", "калибр INSIZE", "метчик м6"]
    analysis["final_analysis"]["negative_keywords"] = ["скачать", "бесплатно"]

    assert build_analysis_pdf(analysis).startswith(b"%PDF-")
    block = pdf_report.keyword_list_flowable(analysis["final_analysis"]["keyword_seeds"], styles())
    assert block.text == "резец проходной · калибр INSIZE · метчик м6"
    # Обычные списки отчёта остаются пунктуальными: compact — только про фразы.
    assert pdf_report._is_keyword_list("keyword_seeds", ["резец"])
    assert not pdf_report._is_keyword_list("site_gaps", ["нет цен"])
    assert not pdf_report._is_keyword_list("keyword_seeds", [])


def test_markdown_table_becomes_a_table_block():
    blocks = markdown_flowables(
        "| Сегмент | Потребность |\n| --- | --- |\n| Технологи | подбор по чертежу |",
        styles(),
    )
    tables = [block for block in blocks if isinstance(block, Table)]
    assert len(tables) == 1
    assert len(tables[0]._cellvalues) == 2


def test_headings_and_lists_become_readable_blocks():
    blocks = markdown_flowables("# Заголовок\n\n## Подзаголовок\n\n- первый\n- второй", styles())
    texts = [getattr(block, "text", "") for block in blocks if isinstance(block, Paragraph)]
    assert "Заголовок" in texts[0]
    assert any("первый" in text for text in texts)


def test_structured_table_value_renders_as_table():
    blocks = value_flowables(
        {"columns": ["Канал", "Формат"], "rows": [["Telegram", "пост"], ["Дзен", "статья"]]},
        styles(),
    )
    tables = [block for block in blocks if isinstance(block, Table)]
    assert tables
    assert len(tables[0]._cellvalues) == 3


def test_markup_checks_get_their_own_chapter():
    assert pdf_report._label("site_checks").startswith("Проверки по разметке"), (
        "раздел не должен выходить в PDF как «site checks»"
    )

    blocks = value_flowables(
        {
            "columns": ["Проверка", "Что видно на страницах", "Вывод"],
            "rows": [["Счётчики и пиксели", "ни одного в разметке", "не найдено — измерять нечем"]],
        },
        styles(),
    )
    cells = [block for block in blocks if isinstance(block, Table)][0]._cellvalues
    assert cells[0][0].text == "Проверка"
    assert cells[1][2].text.startswith("не найдено")


def test_site_content_cannot_inject_markup_into_the_pdf():
    assert inline_markup("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert "<script>" not in inline_markup('<b onclick="x">жирный</b>')


def test_emphasis_and_links_are_converted():
    rendered = inline_markup("**важно** и [сайт](https://example.com?a=1&b=2)")
    assert "<b>важно</b>" in rendered
    assert '<link href="https://example.com?a=1&amp;b=2"' in rendered


def test_bare_source_url_is_clickable_in_pdf():
    rendered = inline_markup("https://tateng.ru/catalog?b=1&c=2")
    assert rendered.startswith('<link href="https://tateng.ru/catalog?b=1&amp;c=2"')
    assert rendered.endswith('</link>')


def test_sources_and_key_facts_reach_the_pdf():
    analysis = sample_analysis()
    analysis["final_analysis"] = {
        "brief_analysis": "разбор",
        "key_facts": [
            {"fact": "Официальный представитель TaeguTec", "source": "https://tateng.ru/", "page": "/"},
            {"fact": "Факт без подтверждения", "source": "источник не распознан"},
        ],
        "sources": {
            "columns": ["№", "Адрес страницы", "Заголовок страницы", "Знаков текста"],
            "rows": [["1", "https://tateng.ru/", "ТАТИНЖЕНЕР", "4505"]],
        },
    }

    pdf = build_analysis_pdf(analysis)

    assert pdf.startswith(b"%PDF")
    blocks = value_flowables(analysis["final_analysis"]["sources"], styles())
    cells = [block for block in blocks if isinstance(block, Table)][0]._cellvalues
    assert cells[0][1].text == "Адрес страницы"
    assert 'href="https://tateng.ru/"' in cells[1][1].text


@pytest.mark.parametrize(
    "value",
    [None, "", [], {}, 0, False, 12, ["строка"], {"вложенный": {"список": [1, 2]}}],
)
def test_odd_values_render_instead_of_crashing(value):
    assert value_flowables(value, styles())


def test_missing_cyrillic_font_is_reported_plainly(monkeypatch):
    monkeypatch.setattr(pdf_report, "resolve_cyrillic_font", lambda: None)
    with pytest.raises(PDFRenderError) as excinfo:
        build_analysis_pdf({"url": "https://example.com"})
    assert "fonts-dejavu-core" in str(excinfo.value)


def test_report_date_is_human_readable():
    assert format_created_at("2026-11-23T17:19:12.064392") == "23.11.2026 17:19"
    assert format_created_at("2026-11-23 19:47:38") == "23.11.2026 19:47"
    assert format_created_at("не дата") == "не дата"
    assert format_created_at(None) == ""


def test_filename_is_ascii_safe():
    assert pdf_filename("https://tateng.ru/catalog?x=1", "2026-11-23 19:47:38") == (
        "analysis_tateng.ru_2026-11-23.pdf"
    )
    assert pdf_filename("", "") == "analysis_analysis_report.pdf"


def test_markup_inside_code_spans_stays_literal():
    # Живой шаг анализа: «`/katalog-produktsii/*` и `/uslugi/*`». Две
    # звёздочки из разных кусков склеивались в незакрытый <i>, и PDF не
    # собрался целиком — клиент вместо файла получил HTTP 500.
    line = "Сегментировать по URL: `/katalog-produktsii/*` и `/uslugi-po-obrabotke-metalla/*`"

    markup = inline_markup(line)

    assert "<i>" not in markup, "звёздочка внутри кода — символ пути, а не разметка"
    assert markup.count("<font") == markup.count("</font") == 2
    assert "/katalog-produktsii/*" in markup


def test_bold_italic_stars_do_not_split_into_unbalanced_tags():
    assert inline_markup("***важно***") == "<b><i>важно</i></b>"


@pytest.mark.parametrize(
    "value",
    [
        "***текст***",
        "**текст *курсив** ещё*",
        "`*`*",
        "**текст",
        "текст**",
        "*a`b*",
        "[ссылка](x)*",
        "a\x020\x02b",
        "```",
        "***",
        "| таблица | без | закрытия",
    ],
)
def test_any_markdown_crumbs_survive_the_pdf(value):
    """Ни один обрывок разметки не имеет права уронить скачивание отчёта."""
    analysis = sample_analysis()
    analysis["intermediate_results"][0]["result"] = f"- {value}\n- обычный пункт"
    analysis["final_analysis"]["brief_analysis"] = value

    assert build_analysis_pdf(analysis).startswith(b"%PDF-")


def test_every_section_is_named_in_pdf_and_ui():
    """Порядок разделов задаёт бэкенд, названия — PDF и интерфейс.

    Раздел без перевода выходит в отчёт сырым ключом: «Site infra» вместо
    «Инфраструктура сайта». Проверка держит три списка в согласии.
    """
    from pathlib import Path

    from app.services import analyzer as analyzer_module

    script = (
        Path(__file__).resolve().parents[1] / "frontend" / "src" / "utils" / "labels.js"
    ).read_text(encoding="utf-8")

    for key in analyzer_module.REPORT_SECTION_ORDER:
        spaced = key.replace("_", " ").strip()
        humanized = spaced[:1].upper() + spaced[1:]
        assert pdf_report._label(key) != humanized, f"{key}: в PDF раздела нет"
        assert f"{key}:" in script, f"{key}: фронтенд не знает названия раздела"
