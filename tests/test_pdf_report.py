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


def test_site_content_cannot_inject_markup_into_the_pdf():
    assert inline_markup("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert "<script>" not in inline_markup('<b onclick="x">жирный</b>')


def test_emphasis_and_links_are_converted():
    rendered = inline_markup("**важно** и [сайт](https://example.com?a=1&b=2)")
    assert "<b>важно</b>" in rendered
    assert '<link href="https://example.com?a=1&amp;b=2"' in rendered


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


def test_filename_is_ascii_safe():
    assert pdf_filename("https://tateng.ru/catalog?x=1", "2026-11-23 19:47:38") == (
        "analysis_tateng.ru_2026-11-23.pdf"
    )
    assert pdf_filename("", "") == "analysis_analysis_report.pdf"
