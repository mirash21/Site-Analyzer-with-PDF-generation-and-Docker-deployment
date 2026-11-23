"""Сборка PDF-отчёта на сервере.

Раньше PDF склеивался в браузере из одного скриншота (html2canvas -> jsPDF):
длинные отчёты обрезались по лимиту размера canvas, строки разрезались пополам
на границе страницы, текст нельзя было выделить, а тёмная тема печаталась
светло-серым по белому. Здесь отчёт верстается настоящими блоками (Platypus):
перенос по границам абзацев и строк, читаемые таблицы, нумерация страниц.
"""

import io
import re
from typing import Any, List, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_MARGIN_X = 14 * mm
PAGE_MARGIN_TOP = 16 * mm
PAGE_MARGIN_BOTTOM = 18 * mm
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN_X

# Шрифт обязан содержать кириллицу: стандартные Helvetica её не рисуют.
FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf",
     "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
]

FONT_NAME = "DejaVuSans"
FONT_NAME_BOLD = "DejaVuSans-Bold"

ACCENT = colors.HexColor("#4f46e5")
MUTED = colors.HexColor("#6b7280")
BORDER = colors.HexColor("#cbd5e1")
HEAD_BG = colors.HexColor("#eef2ff")
ROW_BG = colors.HexColor("#f8fafc")


class PDFRenderError(Exception):
    """PDF не собрался; сообщение можно показать пользователю."""


def resolve_cyrillic_font() -> Sequence[str] | None:
    """Возвращает пути к регулярному и жирному начертанию либо None."""
    import os

    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular):
            return (regular, bold if os.path.exists(bold) else regular)
    return None


def _register_fonts() -> None:
    paths = resolve_cyrillic_font()
    if not paths:
        raise PDFRenderError(
            "Не удалось собрать PDF: в образе нет шрифта с кириллицей. "
            "Установите пакет fonts-dejavu-core."
        )
    pdfmetrics.registerFont(TTFont(FONT_NAME, paths[0]))
    if paths[1] != paths[0]:
        pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, paths[1]))
    pdfmetrics.registerFontFamily(
        FONT_NAME, normal=FONT_NAME, bold=FONT_NAME_BOLD, italic=FONT_NAME, boldItalic=FONT_NAME_BOLD
    )


def _styles() -> dict:
    ink = colors.HexColor("#111827")

    def style(name: str, **kwargs) -> ParagraphStyle:
        kwargs.setdefault("fontName", FONT_NAME)
        kwargs.setdefault("textColor", ink)
        kwargs.setdefault("alignment", TA_LEFT)
        return ParagraphStyle(name, **kwargs)

    bold = FONT_NAME_BOLD
    return {
        "title": style("title", fontSize=18, leading=23, spaceAfter=4, fontName=bold, textColor=ACCENT),
        "subtitle": style("subtitle", fontSize=10, leading=14, textColor=MUTED),
        "section": style(
            "section",
            fontSize=13,
            leading=17,
            spaceBefore=10,
            spaceAfter=6,
            fontName=bold,
            textColor=ACCENT,
            backColor=HEAD_BG,
            borderPadding=(4, 6),
            borderWidth=0.6,
            borderColor=BORDER,
        ),
        "h1": style("h1", fontSize=12.5, leading=16, spaceBefore=8, spaceAfter=3, fontName=bold),
        "h2": style("h2", fontSize=11.5, leading=15, spaceBefore=7, spaceAfter=3, fontName=bold),
        "h3": style("h3", fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=2, fontName=bold),
        "body": style("body", fontSize=10, leading=14, spaceAfter=4),
        "bullet": style("bullet", fontSize=10, leading=14, spaceAfter=2, leftIndent=10, bulletIndent=2),
        "cell": style("cell", fontSize=9, leading=12),
        "cell_head": style("cell_head", fontSize=9, leading=12, fontName=bold),
        "label": style("label", fontSize=9, leading=12, textColor=MUTED),
        "note": style("note", fontSize=9, leading=12, textColor=MUTED),
    }


INLINE_BOLD = re.compile(r"\*\*(?P<text>.+?)\*\*")
INLINE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(?P<text>[^*\n]+?)\*(?!\*)")
INLINE_CODE = re.compile(r"`(?P<text>[^`\n]+)`")
INLINE_LINK = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)\s]+)\)")


def inline_markup(raw: str) -> str:
    """Экранирует HTML и переводит markdown-выделение в теги ReportLab.

    Экранирование идёт первым, поэтому содержимое чужого сайта не может
    подставить в PDF теги разметки.
    """
    # escape() уже закрыл & < >, поэтому для href остаётся закрыть кавычки.
    text = escape(str(raw if raw is not None else ""))
    text = INLINE_LINK.sub(
        lambda m: f'<link href="{m.group("href").replace(chr(34), "&quot;")}" color="#4f46e5">{m.group("text")}</link>',
        text,
    )
    text = INLINE_BOLD.sub(lambda m: f"<b>{m.group('text')}</b>", text)
    text = INLINE_ITALIC.sub(lambda m: f"<i>{m.group('text')}</i>", text)
    text = INLINE_CODE.sub(lambda m: f'<font face="Courier">{m.group("text")}</font>', text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{2,}.*$")
HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+)$")
BULLET = re.compile(r"^\s*[-*+]\s+(?P<text>.+)$")
NUMBERED = re.compile(r"^\s*(?P<num>\d{1,3})[.)]\s+(?P<text>.+)$")
RULE = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")


def _split_table_row(line: str) -> List[str]:
    cells = line.strip().strip("|")
    return [cell.strip() for cell in cells.split("|")]


def _table_flowable(rows: List[List[str]], styles: dict) -> Table:
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]

    data = [
        [
            Paragraph(inline_markup(cell), styles["cell_head"] if index == 0 else styles["cell"])
            for cell in row
        ]
        for index, row in enumerate(normalized)
    ]

    width = CONTENT_WIDTH / max(columns, 1)
    table = Table(data, colWidths=[width] * columns, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_BG]),
            ]
        )
    )
    return table


def markdown_flowables(text: str, styles: dict) -> List[Any]:
    """Конвертирует markdown-ответ модели в блоки PDF.

    Поддерживается то, что модель реально выдаёт: заголовки, списки, таблицы
    через «|», горизонтальные линейки, выделение и ссылки.
    """
    flowables: List[Any] = []
    lines = str(text or "").split("\n")
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if TABLE_ROW.match(line):
            rows: List[List[str]] = []
            while index < len(lines) and TABLE_ROW.match(lines[index]):
                cells = _split_table_row(lines[index])
                if not all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                    rows.append(cells)
                index += 1
            if rows:
                flowables.append(_table_flowable(rows, styles))
                flowables.append(Spacer(1, 4))
            continue

        if RULE.match(stripped):
            flowables.append(Spacer(1, 3))
            index += 1
            continue

        heading = HEADING.match(stripped)
        if heading:
            level = len(heading.group("level"))
            style_key = "h1" if level <= 2 else ("h2" if level == 3 else "h3")
            flowables.append(Paragraph(inline_markup(heading.group("text")), styles[style_key]))
            index += 1
            continue

        bullet = BULLET.match(line)
        number = NUMBERED.match(line)
        if bullet or number:
            items: List[Any] = []
            while index < len(lines):
                item_bullet = BULLET.match(lines[index])
                item_number = NUMBERED.match(lines[index])
                if not (item_bullet or item_number):
                    break
                content = (item_bullet or item_number).group("text")
                marker = "•" if item_bullet else f"{item_number.group('num')}."
                items.append(Paragraph(inline_markup(content), styles["bullet"], bulletText=marker))
                index += 1
            flowables.extend(items)
            flowables.append(Spacer(1, 3))
            continue

        # Обычный абзац: склеиваем соседние строки, как это делает markdown.
        buffer = [stripped]
        index += 1
        while index < len(lines):
            following = lines[index].strip()
            if (
                not following
                or HEADING.match(following)
                or TABLE_ROW.match(lines[index])
                or BULLET.match(lines[index])
                or NUMBERED.match(lines[index])
                or RULE.match(following)
            ):
                break
            buffer.append(following)
            index += 1
        flowables.append(Paragraph(inline_markup(" ".join(buffer)), styles["body"]))

    return flowables


def _label(key: Any) -> str:
    labels = {
        "brief_analysis": "Краткий анализ сайта",
        "analysis": "Анализ сайта",
        "ad_instructions": "Инструкции по рекламным кампаниям",
        "instructions": "Инструкции",
        "ad_examples": "Примеры объявлений",
        "examples": "Примеры",
        "target_audience": "Целевая аудитория",
        "audience": "Аудитория",
        "usp": "Уникальные торговые предложения",
        "strengths": "Сильные стороны",
        "weaknesses": "Слабые стороны",
        "recommendations": "Рекомендации",
        "comparison_table": "Сравнительная таблица",
        "table": "Таблица",
        "title": "Заголовок",
        "heading": "Заголовок",
        "name": "Название",
        "body": "Текст",
        "text": "Текст",
        "content": "Содержание",
        "cta": "Призыв к действию",
        "call_to_action": "Призыв к действию",
        "channel": "Канал",
        "platform": "Площадка",
        "format": "Формат",
        "url": "Адрес сайта",
        "created_at": "Дата анализа",
    }
    key_str = str(key or "").strip().lower().replace("-", "_")
    if key_str in labels:
        return labels[key_str]
    spaced = key_str.replace("_", " ").strip()
    return spaced[:1].upper() + spaced[1:] if spaced else "Раздел"


def value_flowables(value: Any, styles: dict, depth: int = 0) -> List[Any]:
    """Рисует значение произвольной формы: строку, список, объект, таблицу."""
    if value is None or value == "" or value == [] or value == {}:
        return [Paragraph("нет данных", styles["note"])]

    if isinstance(value, bool):
        return [Paragraph("да" if value else "нет", styles["body"])]

    if isinstance(value, (int, float)):
        return [Paragraph(inline_markup(value), styles["body"])]

    if isinstance(value, str):
        return markdown_flowables(value, styles)

    if isinstance(value, dict) and isinstance(value.get("columns"), list) and isinstance(value.get("rows"), list):
        rows = [[str(cell) for cell in (row if isinstance(row, list) else list(row.values()))] for row in value["rows"]]
        return [_table_flowable([[str(column) for column in value["columns"]]] + rows, styles)]

    if isinstance(value, list):
        flowables: List[Any] = []
        for item in value:
            if isinstance(item, dict):
                flowables.append(KeepTogether(object_flowables(item, styles, depth + 1)))
            else:
                flowables.append(Paragraph(inline_markup(item), styles["bullet"], bulletText="•"))
        return flowables or [Paragraph("пусто", styles["note"])]

    if isinstance(value, dict):
        return object_flowables(value, styles, depth)

    return [Paragraph(inline_markup(value), styles["body"])]


def object_flowables(value: dict, styles: dict, depth: int = 0) -> List[Any]:
    """Один элемент списка (объявление, сегмент) — заголовок + поля."""
    title_key = next(
        (key for key in ("title", "heading", "name", "product", "segment") if isinstance(value.get(key), str) and value.get(key).strip()),
        None,
    )
    flowables: List[Any] = []
    if title_key:
        flowables.append(Paragraph(inline_markup(value[title_key]), styles["h3"]))

    rows = []
    for key, item in value.items():
        if key == title_key:
            continue
        if isinstance(item, (str, int, float)) or item is None:
            rows.append([Paragraph(_label(key), styles["label"]), Paragraph(inline_markup(item), styles["cell"])])
        else:
            rows.append([Paragraph(_label(key), styles["label"]), *value_flowables(item, styles, depth + 1)[:1]])

    if not rows and not flowables:
        return [Paragraph("пусто", styles["note"])]
    if rows:
        table = Table(rows, colWidths=[CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.7], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        flowables.append(table)
        flowables.append(Spacer(1, 6))
    return flowables


def _numbered_canvas(note: str):
    class NumberedCanvas(_canvas.Canvas):
        footer_note = note

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages: List[dict] = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for page_index, state in enumerate(self._saved_pages, start=1):
                self.__dict__.update(state)
                self.setFont(FONT_NAME, 8)
                self.setFillColor(MUTED)
                self.drawString(PAGE_MARGIN_X, 9 * mm, f"Страница {page_index} из {total}")
                if self.footer_note:
                    self.drawRightString(A4[0] - PAGE_MARGIN_X, 9 * mm, self.footer_note[:70])
                super().showPage()
            super().save()

    return NumberedCanvas


def build_analysis_pdf(analysis: dict) -> bytes:
    """Собирает PDF по записи анализа.

    Ожидаемая форма: {"url", "created_at", "steps": [...],
    "intermediate_results": [{"step_number", "step", "result"}],
    "final_analysis": {...}}.
    """
    analysis = analysis or {}
    styles = _styles()

    try:
        _register_fonts()
    except Exception as exc:  # noqa: BLE001 - превращаем в понятное сообщение
        raise PDFRenderError(str(exc)) from exc

    buffer = io.BytesIO()
    url = str(analysis.get("url") or "не указан")
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PAGE_MARGIN_X,
        rightMargin=PAGE_MARGIN_X,
        topMargin=PAGE_MARGIN_TOP,
        bottomMargin=PAGE_MARGIN_BOTTOM,
        title=f"Отчёт об анализе сайта {url}",
        author="Site Analyzer",
    )

    story: List[Any] = [
        Paragraph("Отчёт об анализе сайта", styles["title"]),
        Paragraph(inline_markup(url), styles["subtitle"]),
    ]
    if analysis.get("created_at"):
        story.append(Paragraph(f"Дата анализа: {inline_markup(analysis['created_at'])}", styles["subtitle"]))
    story.append(Spacer(1, 8))

    final_analysis = analysis.get("final_analysis") or {}
    story.append(Paragraph("Итоговый анализ", styles["section"]))
    if isinstance(final_analysis, dict) and final_analysis:
        for key, value in final_analysis.items():
            story.append(Paragraph(_label(key), styles["h2"]))
            story.extend(value_flowables(value, styles))
    elif final_analysis:
        story.extend(value_flowables(final_analysis, styles))
    else:
        story.append(Paragraph("итогового анализа нет", styles["note"]))

    steps = analysis.get("steps") or []
    if steps:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Шаги анализа", styles["section"]))
        for index, step in enumerate(steps, start=1):
            story.append(Paragraph(inline_markup(step), styles["bullet"], bulletText=f"{index}."))

    intermediates = analysis.get("intermediate_results") or []
    if intermediates:
        story.append(PageBreak())
        story.append(Paragraph("Промежуточные результаты", styles["section"]))
        for item in intermediates:
            if not isinstance(item, dict):
                story.extend(value_flowables(item, styles))
                continue
            header = f"Шаг {item.get('step_number', '?')}: {item.get('step') or ''}".strip(": ").strip()
            story.append(Paragraph(inline_markup(header), styles["h1"]))
            if item.get("step") and item.get("result"):
                story.append(Paragraph(inline_markup(item["step"]), styles["note"]))
            story.extend(value_flowables(item.get("result"), styles))
            story.append(Spacer(1, 8))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Отчёт сформирован автоматически в Site Analyzer.", styles["note"]))

    try:
        document.build(story, canvasmaker=_numbered_canvas(url))
    except PDFRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - внешний вид документа важнее стека
        raise PDFRenderError(f"Не удалось сверстать PDF: {exc}") from exc

    payload = buffer.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise PDFRenderError("PDF пуст или повреждён — повторите скачивание.")
    return payload


def pdf_filename(url: str = "", created_at: str = "") -> str:
    """ASCII-имя файла: латиница в Content-Disposition ненадёжна в браузерах."""
    host = ""
    match = re.search(r"https?://([^/\s]+)", str(url or ""))
    if match:
        host = match.group(1)
    date = str(created_at or "")[:10].replace(":", "-")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", host or "analysis").strip("-") or "analysis"
    return f"analysis_{slug}_{date or 'report'}.pdf"
