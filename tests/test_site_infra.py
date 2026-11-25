"""Проверки инфраструктуры: robots.txt, sitemap и живые ссылки.

Здесь нет интернета: анализатор передаёт в модуль функцию `fetch`, и тесты
подставляют свою. Ценность ровно в том, что выводы считаются по кодам ответа —
«файла нет», «доступ закрыт» и «сервер молчит» для клиента значат разное.
"""

import pytest

from app.services import analyzer as analyzer_module
from app.services import site_infra as infra
from app.services.analyzer import SiteAnalyzer

ROBOTS = """# комментарий
User-agent: *
Disallow: /admin/
Allow: /admin/panel
Crawl-delay: 7

User-agent: YandexBot
Disallow: /
Host: tateng.ru
Sitemap: https://tateng.ru/sitemap-index.xml
Sitemap: https://tateng.ru/sitemap-video.xml
"""

SITEMAP = (
    '<?xml version="1.0"?><urlset>'
    "<url><loc>https://tateng.ru/catalog</loc><lastmod>2026-04-01</lastmod></url>"
    "<url><loc>https://tateng.ru/uslugi</loc><lastmod>2026-09-15</lastmod></url>"
    "<url><loc>https://other.ru/clone</loc><lastmod>2020-01-01</lastmod></url>"
    "</urlset>"
)

ORIGIN = "https://tateng.ru"


class FakeFetch:
    """Отдаёт заготовленные ответы и помнит, куда и каким методом заходили.

    `head` задаёт ответ на HEAD отдельно: сервер, который не понимает HEAD, —
    обычное явление, и именно поэтому битой считается ссылка, не ответившая
    и на GET.
    """

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url, method="GET"):
        self.calls.append((method, url))
        entry = self.pages.get(url)
        if entry is None:
            return {"status": 404, "text": "", "chain": []}
        if isinstance(entry, int):
            entry = {"status": entry, "text": ""}
        status = entry.get("head", entry.get("status", 200)) if method == "HEAD" else entry.get("status", 200)
        # HEAD тела не приносит: иначе зонд нашёл бы разметку там, где её нет.
        return {"status": status, "text": "" if method == "HEAD" else entry.get("text", ""),
                "chain": entry.get("chain", [])}

    def methods_for(self, url):
        return [method for method, target in self.calls if target == url]


def row_of(table, check):
    return next(row for row in table["rows"] if row[0] == check)


def test_robots_rules_are_counted_from_the_file():
    parsed = infra.parse_robots({"status": 200, "text": ROBOTS})

    assert parsed["state"] == "ok"
    assert parsed["rules"] == 3, "две строки Disallow и одна Allow"
    assert parsed["allow"] == 1
    assert parsed["agents"] == ["*", "yandexbot"]
    assert parsed["blocked_agents"] == ["yandexbot"], "Disallow: / закрыт именно для YandexBot"
    assert parsed["sitemaps"] == ["https://tateng.ru/sitemap-index.xml",
                                 "https://tateng.ru/sitemap-video.xml"]
    assert parsed["host"] == "tateng.ru" and parsed["crawl_delay"] == "7"


def test_absent_file_and_silent_server_are_different_answers():
    absent = infra.build_infra_checks(
        infra.probe_site(ORIGIN, FakeFetch({}), [])
    )
    silent = infra.build_infra_checks({
        **infra.empty_infra(),
        "robots": {"state": "unreachable", "status": 0, "rules": 0, "agents": [],
                   "sitemaps": [], "host": "", "crawl_delay": "", "blocked_agents": [], "allow": 0},
    })

    assert row_of(absent, "robots.txt")[1] == infra.STATE_TEXT["absent"]
    assert row_of(absent, "robots.txt")[2].startswith(infra.CHECK)
    assert row_of(silent, "robots.txt")[2].startswith(infra.UNKNOWN), (
        "молчание сервера нельзя выдавать за «файла нет»"
    )


def test_closed_and_broken_responses_are_not_called_absent():
    assert infra._state(403, "") == "blocked"
    assert infra._state(500, "oops") == "error"
    assert infra._state(301, "") == "error", "незакрытый редирект — не прочитанный файл"
    assert infra._state(0, "") == "unreachable"
    assert infra._state(200, "   ") == "empty"


def test_sitemap_counts_addresses_and_foreign_hosts():
    parsed = infra.parse_sitemap({"status": 200, "text": SITEMAP}, ORIGIN)

    assert parsed["state"] == "ok"
    assert parsed["urls"] == 3
    assert parsed["offsite"] == 1
    assert parsed["newest"] == "2026-09-15"
    assert parsed["sample"][0] == "https://tateng.ru/catalog"


def test_html_page_passing_for_a_sitemap_is_not_a_map():
    parsed = infra.parse_sitemap(
        {"status": 200, "text": "<html><body>Главная</body></html>"}, ORIGIN
    )
    table = infra.build_infra_checks({**infra.empty_infra(), "sitemap": parsed})

    assert parsed["state"] == "foreign"
    assert row_of(table, "Sitemap")[1] == infra.STATE_TEXT["foreign"]


def test_sitemap_of_maps_is_reported_as_index():
    text = (
        "<sitemapindex>"
        "<sitemap><loc>https://tateng.ru/sitemap-1.xml</loc></sitemap>"
        "<sitemap><loc>https://tateng.ru/sitemap-2.xml</loc></sitemap>"
        "</sitemapindex>"
    )

    assert infra.parse_sitemap({"status": 200, "text": text}, ORIGIN)["state"] == "index"


def test_links_are_probed_with_head_and_confirmed_by_get():
    fetch = FakeFetch({
        "https://tateng.ru/ok": {"status": 200},
        "https://tateng.ru/gone": {"status": 404},
        "https://tateng.ru/old": {"status": 200, "chain": [{"from": "https://tateng.ru/old",
                                                            "to": "https://tateng.ru/new",
                                                            "status": 301}]},
        "https://tateng.ru/no-head": {"head": 405, "status": 200},
        "https://tateng.ru/no-head-and-gone": {"head": 501, "status": 404},
    })

    result = infra.probe_links(
        ["https://tateng.ru/ok", "https://tateng.ru/gone", "https://tateng.ru/old",
         "https://tateng.ru/no-head", "https://tateng.ru/no-head-and-gone"],
        fetch,
    )

    assert result["checked"] == 5
    assert [item["url"] for item in result["broken"]] == [
        "https://tateng.ru/gone", "https://tateng.ru/no-head-and-gone",
    ]
    assert [item["status"] for item in result["broken"]] == [404, 404], (
        "решает ответ GET: 405 на HEAD — отказ от метода, а не отсутствующая страница"
    )
    assert result["redirected"][0]["to"] == "https://tateng.ru/new"
    assert result["redirected"][0]["status"] == 301
    assert fetch.methods_for("https://tateng.ru/no-head") == ["HEAD", "GET"], (
        "405 на HEAD проверяют GET, иначе битой станет здоровая страница"
    )


def test_redirect_row_shows_where_the_link_lands():
    """Счётчик редиректов клиенту ничего не даёт — нужен адрес назначения."""
    result = infra.probe_links(["https://tateng.ru/old"], FakeFetch({
        "https://tateng.ru/old": {"status": 200, "chain": [
            {"from": "https://tateng.ru/old", "to": "https://tateng.ru/new", "status": 301}]},
    }))
    table = infra.build_infra_checks({**infra.empty_infra(), "links": result})

    row = row_of(table, "Ссылка через редирект")
    assert row[1] == "https://tateng.ru/old -> https://tateng.ru/new (HTTP 301)", row
    assert row[2].startswith(infra.CHECK)
    assert row_of(table, "Внутренние ссылки")[2].startswith(infra.CHECK)


def test_unanswered_link_is_not_reported_as_broken():
    fetch = FakeFetch({"https://tateng.ru/dead": {"status": 0}})

    result = infra.probe_links(["https://tateng.ru/dead"], fetch)

    assert result["broken"] == [] and result["unreachable"] == 1
    table = infra.build_infra_checks({**infra.empty_infra(), "links": result})
    assert "без ответа 1" in row_of(table, "Внутренние ссылки")[1]


def test_link_probe_stops_at_its_time_budget():
    ticks = iter([0, 0, 12, 25, 40])
    fetch = FakeFetch({f"https://tateng.ru/p{i}": {"status": 200} for i in range(10)})

    result = infra.probe_links(
        [f"https://tateng.ru/p{i}" for i in range(10)], fetch, budget=15, clock=lambda: next(ticks)
    )

    assert result["checked"] < result["found"], "бюджет обязан ограничить проверки"
    assert "бюджет" in result["stopped"]


def test_link_probe_stops_at_its_count_budget():
    """Десять адресов — и все healthy не мешают: двенадцатый не проверяют."""
    fetch = FakeFetch({f"https://tateng.ru/p{i}": {"status": 200} for i in range(12)})

    result = infra.probe_links([f"https://tateng.ru/p{i}" for i in range(12)], fetch, budget=10_000)

    assert result["checked"] == infra.MAX_LINK_CHECKS
    assert result["found"] == 12
    assert f"из {result['found']}" in result["stopped"], "отчёт обязан сказать, что проверили не всё"


def test_budget_out_before_the_first_link_is_not_reported_as_checked():
    fetch = FakeFetch({"https://tateng.ru/a": {"status": 200}})

    result = infra.probe_links(["https://tateng.ru/a"], fetch, budget=-1)
    table = infra.build_infra_checks({**infra.empty_infra(), "links": result})

    assert result["checked"] == 0 and fetch.calls == []
    row = row_of(table, "Внутренние ссылки")
    assert row[1] == "проверить не удалось" and row[2].startswith(infra.UNKNOWN), (
        "ни одного ответа не было — нельзя писать «битых нет»"
    )
    assert "не удалось" in infra.infra_gaps({"links": result})[0]


def test_probe_prefers_the_map_declared_in_robots():
    fetch = FakeFetch({
        ORIGIN + "/robots.txt": {"status": 200, "text": "User-agent: *\nSitemap: https://tateng.ru/big.xml\n"},
        "https://tateng.ru/big.xml": {"status": 200, "text": SITEMAP},
    })

    result = infra.probe_site(ORIGIN, fetch, [])

    assert result["sitemap"]["url"] == "https://tateng.ru/big.xml"
    assert result["sitemap"]["state"] == "ok"
    assert ("GET", "https://tateng.ru/big.xml") in fetch.calls
    assert ("GET", ORIGIN + "/sitemap.xml") not in fetch.calls, "годная карта найдена, запасной путь не нужен"


def test_probe_falls_back_to_default_map_paths():
    fetch = FakeFetch({ORIGIN + "/sitemap_index.xml": {"status": 200, "text": SITEMAP}})

    result = infra.probe_site(ORIGIN, fetch, [])

    assert result["robots"]["state"] == "absent"
    assert result["sitemap"]["url"] == ORIGIN + "/sitemap_index.xml"


def test_absent_map_names_the_addresses_that_were_checked():
    """«Карты нет» без перечисления путей — голословие."""
    table = infra.build_infra_checks(infra.probe_site(ORIGIN, FakeFetch({}), []))
    seen = row_of(table, "Sitemap")[1]

    assert "/sitemap.xml" in seen and "/sitemap_index.xml" in seen, seen


def test_telling_answer_beats_plain_404_on_the_backup_path():
    """Главный путь отдал HTML-страницу — это важнее, чем 404 на запасном.

    Иначе отчёт скажет «карты нет», хотя сервер на типовом адресе выдаёт
    что-то, что картой притворяется, — и чинить нужно именно его.
    """
    fetch = FakeFetch({
        ORIGIN + "/sitemap.xml": {"status": 404},
        ORIGIN + "/sitemap_index.xml": {"status": 200, "text": "<html><body>Главная</body></html>"},
    })

    result = infra.probe_site(ORIGIN, fetch, [])

    assert result["sitemap"]["state"] == "foreign"
    assert result["sitemap"]["url"] == ORIGIN + "/sitemap_index.xml"


def test_prompt_block_says_where_the_map_was_found():
    found = infra.render_infra(infra.probe_site(ORIGIN, FakeFetch({
        ORIGIN + "/robots.txt": {"status": 200, "text": "Sitemap: https://tateng.ru/big.xml\n"},
        "https://tateng.ru/big.xml": {"status": 200, "text": SITEMAP},
    }), []))
    missing = infra.render_infra(infra.probe_site(ORIGIN, FakeFetch({}), []))

    assert "адрес: https://tateng.ru/big.xml" in found
    assert "проверено путей: 2" in missing


def test_blocked_indexing_is_a_hard_finding():
    robots = infra.parse_robots({"status": 200, "text": "User-agent: *\nDisallow: /\n"})
    table = infra.build_infra_checks({**infra.empty_infra(), "robots": robots})

    assert row_of(table, "Закрыто от индексации")[2].startswith(infra.BAD)
    assert "*" in row_of(table, "Закрыто от индексации")[1]


def test_table_never_leaves_a_row_without_a_verdict():
    for source in ({}, {"failed": True}, infra.empty_infra()):
        table = infra.build_infra_checks(source)
        assert table["columns"] == ["Проверка", "Что видно на сервере", "Вывод"]
        assert table["rows"], "пустой результат обязан быть виден, а не молчать"
        for row in table["rows"]:
            assert len(row) == 3 and all(cell.strip() for cell in row), row
            assert row[2].split(" —")[0] in (
                infra.OK, infra.CHECK, infra.MISSING, infra.BAD, infra.UNKNOWN
            ), row


def test_failed_probe_says_it_was_not_checked():
    table = infra.build_infra_checks({"failed": True})

    assert row_of(table, "Инфраструктура сайта")[2].startswith(infra.UNKNOWN)
    assert any("руками" in gap for gap in infra.infra_gaps({"failed": True}))


def test_gaps_name_what_the_server_cannot_tell():
    fetch = FakeFetch({ORIGIN + "/robots.txt": {"status": 200, "text": "User-agent: *\nDisallow: /admin/\n"}})
    gaps = "\n".join(infra.infra_gaps(infra.probe_site(ORIGIN, fetch, ["https://tateng.ru/x"])))

    assert "карт" in gaps.lower(), "без карты нельзя утверждать, что сайт проиндексирован"
    assert infra.infra_gaps({}) == [], "если пробу не делали, не о чем и сообщать"


def test_prompt_block_carries_status_facts():
    text = infra.render_infra(infra.probe_site(ORIGIN, FakeFetch({
        ORIGIN + "/robots.txt": {"status": 200, "text": ROBOTS},
        "https://tateng.ru/sitemap-index.xml": {"status": 200, "text": SITEMAP},
        "https://tateng.ru/catalog": {"status": 404},
    }), ["https://tateng.ru/catalog"]))

    assert text.startswith("## Инфраструктура сайта")
    assert "битых 1" in text
    assert "https://tateng.ru/catalog (HTTP 404)" in text
    assert "агентов: 2" in text


@pytest.fixture()
def analyzer():
    return SiteAnalyzer(FakeLLM())


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


def facts_with(infra_result):
    return {"phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
            "signals": {"pages": 1, "analytics": {"Яндекс Метрика": 1}, "messengers": {},
                        "forms": 1, "inputs": 2},
            "infra": infra_result}


def test_infra_reaches_the_report_and_the_prompts(analyzer):
    probe = infra.probe_site(ORIGIN, FakeFetch({
        ORIGIN + "/robots.txt": {"status": 200, "text": "User-agent: *\nDisallow: /admin/\n"},
        ORIGIN + "/sitemap.xml": {"status": 200, "text": SITEMAP},
    }), [])
    sources = [{"id": 1, "url": ORIGIN + "/", "path": "/", "title": "T", "chars": 900}]

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts_with(probe))

    assert row_of(normalized["site_infra"], "Sitemap")[2].startswith(infra.OK)
    joined = "\n".join(normalized["data_gaps"])
    assert "не на чем" in joined, (
        "карта найдена, а ссылок не проверено: отчёт обязан сказать, чего не знает"
    )
    assert "проиндексировано" not in joined, "при годной карте жаловаться на неё нельзя"

    analyzer.generate_final_analysis(
        [{"step_number": 1, "step": "шаг", "result": "ответ"}], "текст", sources, facts_with(probe)
    )
    prompt = analyzer.llm_client.prompts("chat_json")[-1][1]
    assert "## Инфраструктура сайта" in prompt, "модель обязана рассуждать по фактам ответа сервера"


def test_failed_probe_does_not_pass_for_a_checked_site(analyzer):
    """Сбойный зонд не учит модель: в отчёте он виден как «не проверено»."""
    block = analyzer._checks_block(facts_with({"failed": True}))
    normalized = analyzer._normalize_final_analysis(
        {}, [{"id": 1, "url": ORIGIN, "path": "/", "title": "T", "chars": 900}],
        facts_with({"failed": True}),
    )

    assert "## Инфраструктура сайта" not in block
    assert row_of(normalized["site_infra"], "Инфраструктура сайта")[2].startswith(infra.UNKNOWN)


def test_pdf_label_for_infra_exists():
    from app.services import pdf_report

    assert pdf_report._label("site_infra").startswith("Инфраструктура сайта")


def test_infra_checks_come_after_markup_checks():
    order = list(analyzer_module.REPORT_SECTION_ORDER)

    assert order.index("site_checks") < order.index("site_infra") < order.index("ad_instructions")


def test_internal_links_skip_external_visited_and_anchors(analyzer):
    html = """
    <html><body>
      <a href="/catalog">Каталог</a><a href="https://tateng.ru/uslugi#price">Услуги</a>
      <a href="tel:+78432001122">Позвонить</a><a href="mailto:a@b.ru">Почта</a>
      <a href="https://other.ru/page">Чужой</a><a href="/catalog/">Каталог повторно</a>
      <a href="/contacts">Контакты</a>
    </body></html>
    """

    links = analyzer.internal_links(ORIGIN + "/", [(ORIGIN + "/", html)], [ORIGIN + "/uslugi"], limit=5)

    assert links == ["https://tateng.ru/catalog", "https://tateng.ru/contacts"], links


def test_relative_link_is_checked_where_it_actually_leads(analyzer):
    """Относительная ссылка подкаталога ведёт в подкаталог, а не в корень.

    Разрешив её от главной, зонд пришёл бы на несуществующий адрес и отчёт
    выдал бы клиенту битую ссылку там, где меню работает.
    """
    catalog = """
    <html><body>
      <a href="socket/bolt.html">Болт</a><a href="/krep">Крепёж</a>
      <a href="../about">О нас</a>
    </body></html>
    """

    links = analyzer.internal_links(ORIGIN + "/", [(ORIGIN + "/catalog/", catalog)], [], limit=5)

    assert links == [
        "https://tateng.ru/catalog/socket/bolt.html",
        "https://tateng.ru/krep",
        "https://tateng.ru/about",
    ], links


def test_fetch_probe_reports_chain_and_never_raises(analyzer, monkeypatch):
    class Response:
        def __init__(self, status, headers=None, text=""):
            self.status_code = status
            self.headers = headers or {}
            self.text = text

        def close(self):
            pass

    seen = []

    def fake_request(method, url, **kwargs):
        seen.append((method, url, kwargs.get("allow_redirects")))
        if url.endswith("/moved"):
            return Response(301, {"Location": "/final"})
        if url.endswith("/boom"):
            raise RuntimeError("соединение разорвано")
        if url.endswith("/private"):
            raise analyzer_module.SSRFError("внутренний адрес")
        return Response(200, {}, "тело")

    monkeypatch.setattr(analyzer_module.requests, "request", fake_request)
    monkeypatch.setattr(SiteAnalyzer, "_validate_url", staticmethod(lambda url: url))

    moved = analyzer.fetch_probe(ORIGIN + "/moved", "HEAD")
    boom = analyzer.fetch_probe(ORIGIN + "/boom")
    blocked = analyzer.fetch_probe(ORIGIN + "/private")

    assert moved["status"] == 200 and moved["chain"][0]["status"] == 301
    assert moved["chain"][0]["to"] == ORIGIN + "/final"
    assert moved["text"] == "", "HEAD тела не даёт — иначе проверка ссылки читает чужую страницу"
    assert all(option is False for _, _, option in seen), "редиректы разворачивает сам зонд"
    assert boom["status"] == 0 and boom["chain"] == []
    assert blocked["status"] == 0, "SSRF-ограничение — это ответ, а не исключение"


def test_probe_never_follows_a_redirect_into_internal_address(analyzer, monkeypatch):
    """Адреса пробы приходят с чужого сайта — редирект внутрь сети это граница.

    Robots.txt и ссылки клиент пишет сам; проверка каждого шага — единственное,
    что отличает аудит сайта от запроса к метаданным хоста, где крутится приложение.
    """
    seen = []
    real_validate = SiteAnalyzer._validate_url

    class Response:
        status_code = 301
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        text = ""

        def close(self):
            pass

    def fake_request(method, url, **kwargs):
        seen.append(url)
        return Response()

    def validate(url):
        # Хост клиента резолвить не нужно: в тесте он и так публичный.
        return url if url.startswith(ORIGIN) else real_validate(url)

    monkeypatch.setattr(analyzer_module.requests, "request", fake_request)
    monkeypatch.setattr(SiteAnalyzer, "_validate_url", staticmethod(validate))

    result = analyzer.fetch_probe(ORIGIN + "/mirror")

    assert seen == [ORIGIN + "/mirror"], "на внутренний адрес зонд не ходит"
    assert result["status"] == 0


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/robots.txt",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/sitemap.xml",
    "ftp://tateng.ru/sitemap.xml",
    "http://user:pass@tateng.ru/sitemap.xml",
])
def test_probe_refuses_addresses_outside_the_public_web(url):
    with pytest.raises(analyzer_module.SSRFError):
        SiteAnalyzer._validate_url(url)
