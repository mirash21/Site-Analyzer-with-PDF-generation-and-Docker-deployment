"""Скорость и мобильность: замеры свои, PageSpeed — как получится.

Ценность раздела в том, что он не зависит от чужой бесплатной квоты. Google
отвечает «429» на большинстве суток, и если строить отчёт на нём, клиент получил
бы «скорость неизвестна» вместо ответа. Здесь цифры берутся из собственного
замера и из разметки, а PSI добавляется только когда ответил — и тогда
переписывается как есть.

Интернета в наборе нет: модуль получает функции запроса извне и остаёт
проверяемым на подставных ответах.
"""

import pytest

from app.services import analyzer as analyzer_module
from app.services import site_infra as infra
from app.services import site_signals as marks
from app.services import site_speed as speed
from app.services import site_crawl as crawl
from app.services.analyzer import SiteAnalyzer

ORIGIN = "https://tateng.ru"
HOME = ORIGIN


class FakeLLM:
    """Скорость считает код: выдумывать ответы модели в этом наборе нечего."""

    def chat_json(self, system_prompt, user_prompt, **kwargs):
        return {}

    def chat_with_system(self, system_prompt, user_prompt, **kwargs):
        return "-"


@pytest.fixture
def analyzer():
    return SiteAnalyzer(FakeLLM())


def row_of(table, name):
    for row in table["rows"]:
        if row[0] == name:
            return row
    raise AssertionError(f"строки «{name}» нет в таблице: {[r[0] for r in table['rows']]}")


def verdict_of(row):
    return row[2].split(" —")[0]


PAGE = {
    "status": 200,
    "ttfb_ms": 720,
    "total_ms": 1400,
    "content_bytes": 410_000,
    "wire_bytes": 96_000,
    "redirects": 2,
    "final_url": ORIGIN + "/index.php",
    "http_version": "HTTP/1.1",
    "headers": {
        "Content-Encoding": "gzip",
        "Cache-Control": "no-cache",
        "Content-Type": "text/html; charset=utf-8",
        "Server": "nginx/1.24.1",
    },
}

HEAVY_PAGE = """<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<link rel="stylesheet" href="/bitrix/css/main/kernel_main.css">
<link rel="preload" as="font" href="/local/fonts/roboto.woff2">
<style>@font-face {font-family: Roboto}</style>
<script src="/bitrix/js/main/core/kernel_debug.js"></script>
<script src="https://mc.yandex.ru/metrika/tag.js" async></script>
</head><body>
<h1>Завод метизов</h1>
<img src="/images/docs/01.jpg">
<img src="/images/catalog/shpilka.webp" width="320" height="240"
     loading="lazy" srcset="a 1x, b 2x">
<script src="https://www.google.com/recaptcha/api.js"></script>
<iframe src="https://yandex.ru/maps/?text=Казань"></iframe>
</body></html>"""


def measured(**overrides):
    return speed.normalize_page(dict(PAGE, **overrides))


def built(page=None, markup=None, assets=None, psi=None):
    """Готовый срез без сети: каждая половина подставлена целиком."""
    return {
        "page": page if page is not None else measured(),
        "markup": markup if markup is not None else speed.parse_markup(HEAVY_PAGE, ORIGIN),
        "assets": assets if assets is not None else speed.empty_speed()["assets"],
        "psi": psi if psi is not None else {"state": "quota", "score": 0, "lab": {}, "field": {}},
    }


# --- разметка: то, что не видно ни в одном тайминге -------------------------


def test_blocking_scripts_count_only_those_without_defer():
    markup = speed.parse_markup(HEAVY_PAGE, ORIGIN)

    assert markup["blocking"] == 1, "единственный скрипт в head без defer/async"
    assert markup["deferred"] == 1, "async-скрипт отложен и в блокирующие не идёт"
    assert markup["blocking_urls"] == [ORIGIN + "/bitrix/js/main/core/kernel_debug.js"]
    assert "mc.yandex.ru/metrika/tag.js" not in str(markup["blocking_urls"])


def test_script_from_body_is_not_reported_as_head_blocking():
    html = "<html><head></head><body><script src='/local/app.js'></script></body></html>"

    markup = speed.parse_markup(html, ORIGIN)

    assert markup["scripts"] == 1
    assert markup["blocking"] == 0, "скрипт в теле — не блокировка первой отрисовки"


def test_third_party_connections_are_named_by_host():
    markup = speed.parse_markup(HEAVY_PAGE, ORIGIN)

    assert markup["third_party"] == 3, markup["third_party"]
    assert markup["third_party_hosts"] == ["mc.yandex.ru", "www.google.com", "yandex.ru"]
    assert "tateng.ru" not in markup["third_party_hosts"], "свой хост не чужой виджет"


def test_iframe_and_font_facts_are_kept_separate():
    markup = speed.parse_markup(HEAVY_PAGE, ORIGIN)

    assert markup["iframes"] == 1 and markup["iframe_hosts"] == ["yandex.ru"]
    assert markup["font_faces"] == 1
    assert markup["font_preload"] == 1, "preload as=font — это предзагрузка шрифта"


def test_viewport_and_zoom_lock_are_different_defects():
    locked = speed.parse_markup(HEAVY_PAGE, ORIGIN)
    open_zoom = speed.parse_markup(
        '<meta name="viewport" content="width=device-width">', ORIGIN
    )
    absent = speed.parse_markup("<h1>без шапки</h1>", ORIGIN)

    assert locked["viewport"] and locked["zoom_locked"]
    assert open_zoom["viewport"] and not open_zoom["zoom_locked"]
    assert not absent["viewport"]


def test_images_are_counted_by_what_slows_them():
    markup = speed.parse_markup(HEAVY_PAGE, ORIGIN)

    assert markup["images"] == 2
    assert markup["images_no_dims"] == 1, "у jpg нет ни width, ни height"
    assert markup["images_lazy"] == 1
    assert markup["images_srcset"] == 1
    assert markup["images_modern"] == 1, "webp посчитан современным форматом"


def test_unparsed_html_makes_no_claims():
    markup = speed.parse_markup("   ", ORIGIN)

    assert not markup["parsed"]
    assert markup["scripts"] == 0 and markup["images"] == 0
    table = speed.build_speed_checks(built(markup=markup))
    claimed = [r for r in table["rows"] if r[0] == "Картинки без размеров (риск сдвига макета)"]
    assert not claimed, "по непрочитанной разметке нельзя утверждать «картинок нет»"


# --- собственный замер главной ----------------------------------------------


def test_measured_page_becomes_numbers_not_adjectives():
    page = measured()

    assert page["measured"]
    assert page["ttfb_ms"] == 720 and page["total_ms"] == 1400
    assert page["content_bytes"] == 410_000 and page["wire_bytes"] == 96_000
    assert page["encoding"] == "gzip" and page["http_version"] == "HTTP/1.1"
    assert page["redirects"] == 2 and page["final_path"] == "/index.php"
    assert page["server"] == "nginx/1.24.1"
    assert page["content_type"] == "text/html" and page["charset"]


def test_missing_response_leaves_the_speed_row_unknown():
    page = speed.normalize_page({})
    table = speed.build_speed_checks(built(page=page))

    assert not page["measured"]
    row = row_of(table, "Ответ сервера")
    assert row[1] == "замер не сделан" and verdict_of(row) == speed.UNKNOWN
    assert not [r for r in table["rows"] if r[0] == "Вес главной страницы"], (
        "невесомую страницу нельзя объявить лёгкой"
    )


def test_slow_server_and_light_html_are_judged_separately():
    table = speed.build_speed_checks(built())

    assert verdict_of(row_of(table, "Ответ сервера")) == speed.BAD
    assert verdict_of(row_of(table, "Вес главной страницы")) == speed.OK
    assert verdict_of(row_of(table, "Протокол соединения")) == speed.CHECK
    assert verdict_of(row_of(table, "Редирект при заходе")) == speed.CHECK


def test_uncompressed_heavy_html_is_an_error():
    heavy = measured(**{"wire_bytes": 500_000, "content_bytes": 900_000, "headers": {
        "Content-Type": "text/html", "Cache-Control": "private"}})
    table = speed.build_speed_checks(built(page=heavy))

    row = row_of(table, "Вес главной страницы")
    assert verdict_of(row) == speed.BAD
    assert "без сжатия" in row[1]


def test_unnamed_wire_weight_is_not_reported_as_the_page_weight():
    """Отдача кусками без Content-Length: вес в сети не назван — и в строке это видно."""
    page = measured(wire_bytes=0)
    row = row_of(speed.build_speed_checks(built(page=page)), "Вес главной страницы")

    assert "410 КБ разметки" in row[1] and "вес в сети не назван" in row[1]
    assert verdict_of(row) == speed.CHECK, (
        "410 КБ разметки — тяжело, даже если сервер сжал ответ на лету"
    )
    assert "главная тяжёлая" in row[2]
    assert "вес в сети не назван" in speed.render_speed(built(page=page))

    light = measured(wire_bytes=0, content_bytes=40_000)
    assert verdict_of(row_of(
        speed.build_speed_checks(built(page=light)), "Вес главной страницы"
    )) == speed.OK


def test_http2_and_no_redirects_clear_the_transport_rows():
    fast = measured(http_version="HTTP/2", redirects=0, ttfb_ms=90, total_ms=240,
                    content_bytes=120_000, wire_bytes=30_000)
    table = speed.build_speed_checks(built(page=fast))

    assert verdict_of(row_of(table, "Протокол соединения")) == speed.OK
    assert row_of(table, "Редирект при заходе")[1] == "сразу 200"
    assert verdict_of(row_of(table, "Ответ сервера")) == speed.OK


def test_cached_html_is_flagged_because_updates_will_lag():
    """Для главной «кэшируется» — не находка, а риск: клиент не увидит правку."""
    cached = measured(headers={"Content-Type": "text/html; charset=utf-8",
                               "Cache-Control": "max-age=3600"})
    table = speed.build_speed_checks(built(page=cached))

    row = row_of(table, "Кэш главной")
    assert verdict_of(row) == speed.CHECK
    assert "начнут доходить не сразу" in row[2]


# --- проба ресурсов ---------------------------------------------------------


def test_pick_assets_prefers_own_blocking_files():
    markup = speed.parse_markup(HEAVY_PAGE, ORIGIN)

    picked = speed.pick_assets(markup, ORIGIN, limit=6)

    assert picked[0] == ORIGIN + "/bitrix/js/main/core/kernel_debug.js"
    assert picked[1] == ORIGIN + "/bitrix/css/main/kernel_main.css"
    assert all(url.startswith(ORIGIN + "/") for url in picked[:4]), (
        "свои адреса идут впереди чужих: их клиент чинит сам"
    )
    assert speed.pick_assets(markup, ORIGIN, limit=0) == []


def test_probe_assets_reads_weight_and_cache_state():
    def head(url):
        if "kernel_debug" in url:
            return {"status": 200, "bytes": 480_000, "encoding": "",
                    "cache_control": "max-age=31536000"}
        if "favicon" in url:
            return {"status": 200, "bytes": 400, "encoding": "", "cache_control": ""}
        return {"status": 200, "bytes": 90_000, "encoding": "br", "cache_control": ""}

    assets = speed.probe_assets(
        [ORIGIN + "/bitrix/js/main/core/kernel_debug.js", ORIGIN + "/a.css",
         ORIGIN + "/b.jpg", ORIGIN + "/favicon.ico"],
        head,
    )

    assert assets["checked"] == 4 and assets["bytes"] == 660_400
    assert assets["compressed"] == 2
    assert assets["uncompressed"] == 1, "полкилобайта без сжатия — не находка, а шум"
    assert assets["uncached"] == 3, "max-age=0 и отсутствия политики — не кэш"
    assert assets["weighed"] == 4 and not assets["size_unknown"]
    assert not assets["weightless"] and not assets["dead"] and not assets["unreachable"]


def test_silent_asset_is_our_failure_and_not_a_missing_file():
    """«404» — дефект сайта, «молчит» — дефект проверки: выводы обязаны различаться."""
    assets = speed.probe_assets([ORIGIN + "/a.js", ORIGIN + "/b.js"], lambda url: {"status": 0})
    table = speed.build_speed_checks(built(assets=assets))

    assert assets["unreachable"] == 2 and not assets["dead"]
    row = row_of(table, "Вес ресурсов (проба заголовков)")
    assert verdict_of(row) == speed.UNKNOWN
    assert "не ответил" in row[2], "молчание сервера — не то же самое, что неназванный размер"
    assert "без ответа 2" in row[1]
    assert not [r for r in table["rows"] if r[0] == "Ресурс не отдан"]

    gaps = "\n".join(speed.speed_gaps(built(assets=assets)))
    assert "Статика не ответила на пробу" in gaps
    assert "Вес статики не измерен" not in gaps, (
        "нельзя отвечать «сервер не назвал размер» на сервер, который молчал"
    )


def test_dead_asset_becomes_its_own_finding():
    assets = speed.probe_assets(
        [ORIGIN + "/local/missing.js"],
        lambda url: {"status": 404, "bytes": 0},
    )
    table = speed.build_speed_checks(built(assets=assets))

    assert assets["dead"] == [{"url": ORIGIN + "/local/missing.js", "status": 404}]
    assert verdict_of(row_of(table, "Вес ресурсов (проба заголовков)")) == speed.BAD
    assert row_of(table, "Ресурс не отдан")[1] == "/local/missing.js — HTTP 404"


def test_probe_stops_at_its_time_budget():
    now = [0.0]

    def clock():
        return now[0]

    def head(url):
        now[0] += 9.0
        return {"status": 200, "bytes": 1000, "encoding": "gzip", "cache_control": "max-age=600"}

    urls = [f"{ORIGIN}/a{index}.js" for index in range(6)]
    assets = speed.probe_assets(urls, head, budget=15.0, clock=clock)

    assert assets["checked"] == 2, "бюджет времени важнее желания перебрать всё"
    assert "бюджет времени" in assets["stopped"]
    assert "бюджет времени" in row_of(
        speed.build_speed_checks(built(assets=assets)), "Вес ресурсов (проба заголовков)"
    )[1]


def test_assets_that_were_found_but_not_probed_are_admitted():
    """Найденные адреса и несделанная проба — не «всё в порядке» и не «404»."""
    assets = {"checked": 0, "found": 4, "bytes": 0, "compressed": 0, "uncompressed": 0,
              "uncached": 0, "unreachable": 0, "dead": [], "items": [], "stopped": ""}
    row = row_of(speed.build_speed_checks(built(assets=assets)), "Вес ресурсов (проба заголовков)")

    assert verdict_of(row) == speed.UNKNOWN
    assert row[1] == "проверить не удалось"


def test_assets_served_in_chunks_leave_their_weight_unmeasured():
    """Отдача кусками: нет Content-Length — значит вес не измерен, а не «ноль байт»."""
    def head(url):
        return {"status": 200, "bytes": 0, "encoding": "gzip",
                "cache_control": "max-age=2592000"}

    assets = speed.probe_assets([ORIGIN + "/a.css", ORIGIN + "/b.css"], head)
    row = row_of(
        speed.build_speed_checks(built(assets=assets)), "Вес ресурсов (проба заголовков)"
    )

    assert assets["weighed"] == 0 and assets["size_unknown"] == 2
    assert not assets["weightless"], "сжатие включено: веса нет, но находить нечего"
    assert "вес не назвал ни один ресурс" in row[1]
    assert verdict_of(row) == speed.UNKNOWN
    assert "не измерено" in row[2]
    gaps = "\n".join(speed.speed_gaps(built(assets=assets)))
    assert "Вес статики не измерен" in gaps
    assert "Статика не ответила на пробу" not in gaps


def test_unnamed_size_without_compression_is_a_check_and_not_a_norm():
    """Файл не сжат и его размер не назван: «норма» была бы выдумкой, «ошибка» — клеветой."""
    def head(url):
        return {"status": 200, "bytes": 0, "encoding": "", "cache_control": "max-age=2592000"}

    assets = speed.probe_assets([ORIGIN + "/a.js", ORIGIN + "/b.js"], head)
    row = row_of(
        speed.build_speed_checks(built(assets=assets)), "Вес ресурсов (проба заголовков)"
    )

    assert assets["weightless"] == 2 and not assets["uncompressed"]
    assert "без веса и без сжатия 2" in row[1]
    assert verdict_of(row) == speed.CHECK
    assert "его вес не проверить" in row[2]


def test_partially_weighed_static_keeps_only_measured_numbers():
    def head(url):
        size = 0 if "chunk" in url else 20_000
        return {"status": 200, "bytes": size, "encoding": "gzip",
                "cache_control": "max-age=604800"}

    assets = speed.probe_assets([ORIGIN + "/a.css", ORIGIN + "/chunk.css"], head)
    row = row_of(
        speed.build_speed_checks(built(assets=assets)), "Вес ресурсов (проба заголовков)"
    )
    gaps = "\n".join(speed.speed_gaps(built(assets=assets)))

    assert assets["weighed"] == 1 and assets["size_unknown"] == 1
    assert "вес назван у 1 (20 КБ)" in row[1], "в сумму входят только названные размеры"
    assert verdict_of(row) == speed.OK
    assert "Вес статики не измерен" not in gaps


def test_cache_state_reads_the_policy_and_not_the_header_presence():
    assert speed._cache_state("max-age=31536000") == "cached"
    assert speed._cache_state("max-age=30") == "short"
    assert speed._cache_state("no-store") == "forbidden"
    assert speed._cache_state("no-cache, max-age=3600") == "forbidden"
    assert speed._cache_state("private") == "none"
    assert speed._cache_state("", "Wed, 11 Jul 2050 10:00:00 GMT") == "cached"
    assert speed._cache_state("", "Thu, 01 Jan 1970 00:00:00 GMT") == "none"


# --- PageSpeed Insights: чужие цифры без пересчёта -------------------------


def test_psi_state_separates_quota_from_silence_and_noise():
    assert speed.psi_state(429, {}) == "quota"
    assert speed.psi_state(0, {}) == "unreachable"
    assert speed.psi_state(403, {}) == "blocked"
    assert speed.psi_state(500, {}) == "error"
    assert speed.psi_state(200, {}) == "foreign", "пустой конверт — не отчёт теста"
    assert speed.psi_state(200, {"lighthouseResult": {}}) == "foreign"
    assert speed.psi_state(200, {
        "lighthouseResult": {"configSettings": {"formFactor": "mobile"}}
    }) == "foreign", "оболочка без аудатов и баллов не считается ответом теста"
    assert speed.psi_state(200, {"loadingExperience": {"metrics": {}}}) == "foreign"
    assert speed.psi_state(200, {"error": {"code": 429}}) == "quota"
    assert speed.psi_state(200, {"lighthouseResult": {"audits": {"x": {}}}}) == "ok"


def test_psi_ignores_a_body_that_is_not_an_object():
    """Прокси или HTML-страница вместо JSON не должны ронять разбор."""
    facts = speed.psi_facts({"status": 200, "body": [1, 2]})

    assert facts["state"] == "foreign"
    assert not facts["lab"] and not facts["field"] and facts["score"] == 0


def test_psi_facts_take_lab_and_field_numbers_as_given():
    payload = {"status": 200, "body": {
        "lighthouseResult": {
            "configSettings": {"formFactor": "mobile"},
            "categories": {"performance": {"score": 0.61}},
            "audits": {
                "first-contentful-paint": {"numericValue": 1830.4},
                "largest-contentful-paint": {"numericValue": 4600},
                "total-blocking-time": {"numericValue": 120},
                "cumulative-layout-shift": {"numericValue": 0.0213},
                "server-response-time": {"numericValue": 310},
            },
        },
        "loadingExperience": {
            "overall_category": "AVERAGE",
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3100, "category": "AVERAGE"},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 240, "category": "FAST"},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 12, "category": "FAST"},
            },
        },
    }}

    facts = speed.psi_facts(payload)

    assert facts["state"] == "ok" and facts["score"] == 61 and facts["strategy"] == "mobile"
    assert facts["lab"]["FCP"] == 1830 and facts["lab"]["LCP"] == 4600
    assert facts["lab"]["CLS"] == 0.0213 and facts["lab"]["TTFB"] == 310
    assert "SI" not in facts["lab"], "метрики, которой нет в ответе, не досочиняют"
    assert facts["field"]["LCP"] == {"value": 3100, "grade": "average"}
    assert facts["field"]["CLS"]["value"] == 0.12, "CrUX отдаёт CLS сотыми долями"


def test_blocked_psi_gives_no_numbers_and_says_why():
    facts = speed.psi_facts({"status": 429, "body": {"error": {"code": 429}}})
    table = speed.build_speed_checks(built(psi=dict(facts, lab={}, field={})))

    assert facts["state"] == "quota" and not facts["lab"] and not facts["field"]
    row = row_of(table, "PageSpeed Insights (мобильные)")
    assert verdict_of(row) == speed.UNKNOWN
    assert "квоту" in row[1]
    assert not [r for r in table["rows"] if r[0] == "Core Web Vitals (лаборатория)"]


def test_core_web_vitals_rows_grade_the_worst_metric():
    ok = {"state": "ok", "score": 95, "lab": {"LCP": 1900, "TBT": 90, "CLS": 0.02}, "field": {}}
    bad = {"state": "ok", "score": 30, "lab": {"LCP": 1900, "TBT": 90, "CLS": 0.4}, "field": {}}

    good = row_of(speed.build_speed_checks(built(psi=ok)), "Core Web Vitals (лаборатория)")
    worst = row_of(speed.build_speed_checks(built(psi=bad)), "Core Web Vitals (лаборатория)")

    assert verdict_of(good) == speed.OK
    assert verdict_of(worst) == speed.BAD, (
        "один проваленный показатель не прячут за двумя хорошими"
    )
    assert "CLS — 0.40" in worst[1]
    assert verdict_of(row_of(
        speed.build_speed_checks(built(psi=ok)), "Core Web Vitals (реальные посещения)"
    )) == speed.UNKNOWN


def test_field_data_is_reported_with_its_own_grade():
    psi = {"state": "ok", "score": 70, "lab": {}, "field": {
        "LCP": {"value": 4800, "grade": "slow"},
        "INP": {"value": 180, "grade": "fast"},
    }}
    row = row_of(speed.build_speed_checks(built(psi=psi)), "Core Web Vitals (реальные посещения)")

    assert verdict_of(row) == speed.BAD
    assert "LCP — 4.8 с (медленно)" in row[1] and "INP — 180 мс (быстро)" in row[1]


# --- таблица, пробелы и блок для модели ------------------------------------


def test_speed_table_shares_the_verdict_words_of_other_code_tables():
    table = speed.build_speed_checks(built())

    assert (speed.OK, speed.CHECK, speed.BAD, speed.UNKNOWN) == (
        "норма", "проверить", "ошибка", "не проверено",
    )
    assert (speed.OK, speed.CHECK) == (marks.OK, marks.CHECK) == (infra.OK, infra.CHECK)
    for row in table["rows"]:
        assert verdict_of(row) in (speed.OK, speed.CHECK, speed.BAD, speed.UNKNOWN), row


def test_verdict_and_explanation_never_contradict_each_other():
    """Строка «норма — чужой сервер тормозит» обесценивает всю таблицу."""
    table = speed.build_speed_checks(built())

    third = row_of(table, "Чужие скрипты и виджеты")
    assert verdict_of(third) == speed.OK
    assert "критическом пути" not in third[2], third[2]

    rich = speed.build_speed_checks(built(markup=speed.parse_markup(
        "<html><body>" + "".join(f'<img src="/i{k}.jpg">' for k in range(4)) + "</body></html>",
        ORIGIN,
    )))
    dims = row_of(rich, "Картинки без размеров (риск сдвига макета)")
    assert verdict_of(dims) == speed.BAD and "прыгает" in dims[2]


def test_failed_measurement_says_so_instead_of_guessing():
    table = speed.build_speed_checks({"failed": True})
    gaps = speed.speed_gaps({"failed": True})

    assert len(table["rows"]) == 1
    assert table["rows"][0][1] == "замер не завершился"
    assert verdict_of(table["rows"][0]) == speed.UNKNOWN
    assert "Замер скорости не завершился" in gaps[0]


def test_gaps_name_everything_this_section_cannot_claim():
    gaps = speed.speed_gaps(built())

    joined = "\n".join(gaps)
    assert "PageSpeed Insights нет" in joined and "квоту" in joined
    assert "у реальных посетителей нет" in joined
    assert speed.speed_gaps({}) == [], "пробу не делали — нечего и заявлять"
    assert speed.speed_gaps(None) == []


def test_unmeasured_home_page_is_declared_a_gap():
    gaps = "\n".join(speed.speed_gaps(built(page=speed.normalize_page({}))))

    assert "не удалось замерить" in gaps, (
        "время ответа и вес HTML не известны — отчёт обязан это признать"
    )


def test_a_probe_that_never_started_is_declared_a_gap():
    """Сбой пробы — не «всё чисто»: модель обязана знать, что веса статики не видел никто."""
    assets = dict(speed.empty_speed()["assets"], found=5, stopped="проба не удалась")
    gaps = "\n".join(speed.speed_gaps(built(assets=assets)))

    assert "Пробу ресурсов не удалось сделать" in gaps
    assert "Вес статики не измерен" not in gaps, "пробы не было — писать про размеры рано"


def test_no_gap_is_invented_when_psi_answered_with_field_data():
    psi = {"state": "ok", "score": 80, "lab": {"LCP": 2000},
           "field": {"LCP": {"value": 2100, "grade": "fast"}}}

    assert speed.speed_gaps(built(psi=psi)) == []


def test_prompt_block_hands_the_model_measured_numbers():
    block = speed.render_speed(built())

    assert block.startswith("## Скорость и мобильность")
    assert "720 мс" in block and "HTTP/1.1" in block and "96 КБ" in block
    assert "блокирующих в head 1" in block
    assert "mc.yandex.ru" in block
    assert "упёрся в дневную квоту" in block
    assert "Проба ресурсов: 0 адресов" not in block, "пустую пробу не выдают за замер"


def test_prompt_block_separates_weighed_static_from_unweighed():
    """Модель не должна собрать «статика весит 0 Б» из отсутствующего заголовка."""
    def head(url):
        return {"status": 200, "bytes": 0, "encoding": "gzip", "cache_control": ""}

    unweighed = speed.render_speed(built(assets=speed.probe_assets([ORIGIN + "/a.css"], head)))
    assert "вес не назвал ни один ресурс" in unweighed
    assert "адресов, 0 Б" not in unweighed

    def heavy(url):
        return {"status": 200, "bytes": 120_000, "encoding": "gzip",
                "cache_control": "max-age=604800"}

    block = speed.render_speed(built(assets=speed.probe_assets([ORIGIN + "/a.css"], heavy)))
    assert "120 КБ, вес назван у 1" in block


def test_prompt_block_without_measurements_admits_it():
    block = speed.render_speed(built(
        page=speed.normalize_page({}),
        markup=speed.parse_markup("", ORIGIN),
        psi=speed.psi_facts({}),
    ))

    assert "Замер главной: не сделан" in block
    assert "Разметка главной не прочитана" in block
    assert "Проба ресурсов: не делалась" in block
    assert "тест не ответил" in block


# --- строки, которые иначе остались бы без проверки ------------------------


def test_content_length_reads_digits_and_ignores_noise():
    assert speed.content_length("4096") == 4096
    assert speed.content_length(" 4096 ") == 4096
    assert speed.content_length(4096) == 4096
    assert speed.content_length(None) == 0
    assert speed.content_length("") == 0
    assert speed.content_length("chunked") == 0, "значение без цифр не становится весом"
    assert speed.content_length("0") == 0


def test_kb_units_switch_at_readable_magnitudes():
    assert speed._kb(800) == "800 Б"
    assert speed._kb(96_000) == "96 КБ"
    assert speed._kb(3_400_000) == "3.4 МБ"


def test_blocking_scripts_row_scales_with_their_number():
    single = row_of(speed.build_speed_checks(built()), "Скрипты, блокирующие отрисовку")
    assert verdict_of(single) == speed.CHECK
    assert "белый экран" in single[2], single[2]

    many = speed.parse_markup("<html><head>" + "".join(
        f'<script src="/local/s{k}.js"></script>' for k in range(4)
    ) + "</head></html>", ORIGIN)
    crowded = row_of(
        speed.build_speed_checks(built(markup=many)), "Скрипты, блокирующие отрисовку"
    )
    assert verdict_of(crowded) == speed.BAD

    clean = speed.parse_markup(
        "<html><head></head><body><script src='/a.js'></script></body></html>", ORIGIN
    )
    clear = row_of(speed.build_speed_checks(built(markup=clean)), "Скрипты, блокирующие отрисовку")
    assert verdict_of(clear) == speed.OK
    assert "не заблокирован" in clear[2]


def test_heavy_dom_tree_is_flagged_by_its_size():
    heavy = speed.parse_markup("<html><body>" + "<div>текст</div>" * 1600, ORIGIN)
    light = speed.parse_markup("<html><body><p>текст</p></body></html>", ORIGIN)
    assert heavy["dom_nodes"] > speed.DOM_BAD_NODES and light["dom_nodes"] < speed.DOM_OK_NODES

    fat = row_of(speed.build_speed_checks(built(markup=heavy)), "Размер разметки (узлы DOM)")
    thin = row_of(speed.build_speed_checks(built(markup=light)), "Размер разметки (узлы DOM)")
    assert verdict_of(fat) == speed.BAD and "тяжёлое дерево" in fat[2]
    assert verdict_of(thin) == speed.OK and "дерево лёгкое" in thin[2]


def test_widget_rows_only_appear_when_widgets_are_connected():
    iframe = row_of(speed.build_speed_checks(built()), "Виджеты в iframe")
    assert verdict_of(iframe) == speed.CHECK and iframe[1] == "1, хостов: 1"

    bare = speed.parse_markup("<html><body><p>без виджетов</p></body></html>", ORIGIN)
    table = speed.build_speed_checks(built(markup=bare))
    assert not [r for r in table["rows"] if r[0] == "Виджеты в iframe"], (
        "если iframe нет, строки про них быть не должно"
    )

    crowded = speed.parse_markup("<html><body>" + "".join(
        f'<iframe src="https://map{k}.ru/x"></iframe>' for k in range(4)
    ) + "</body></html>", ORIGIN)
    many = row_of(speed.build_speed_checks(built(markup=crowded)), "Виджеты в iframe")
    assert verdict_of(many) == speed.BAD and many[1] == "4, хостов: 4"


def test_layout_shift_row_names_the_share_of_images():
    half = row_of(
        speed.build_speed_checks(built()), "Картинки без размеров (риск сдвига макета)"
    )
    assert verdict_of(half) == speed.CHECK
    assert half[1] == "1 из 2 (50%)"

    all_of_them = speed.parse_markup("<html><body>" + "".join(
        f'<img src="/i{k}.jpg">' for k in range(4)
    ) + "</body></html>", ORIGIN)
    worst = row_of(
        speed.build_speed_checks(built(markup=all_of_them)),
        "Картинки без размеров (риск сдвига макета)",
    )
    assert verdict_of(worst) == speed.BAD

    sized = speed.parse_markup("<img src='/a.jpg' width='10' height='10'>", ORIGIN)
    clear = row_of(
        speed.build_speed_checks(built(markup=sized)),
        "Картинки без размеров (риск сдвига макета)",
    )
    assert verdict_of(clear) == speed.OK and "не прыгает" in clear[2]


def test_many_third_party_hosts_become_a_finding():
    html = "<html><body>" + "".join(
        f'<script src="https://host{k}.ru/tag.js"></script>' for k in range(9)
    ) + "</body></html>"
    row = row_of(
        speed.build_speed_checks(built(markup=speed.parse_markup(html, ORIGIN))),
        "Чужие скрипты и виджеты",
    )

    assert verdict_of(row) == speed.BAD
    assert "критическом пути" in row[2]
    assert "9 адресов с 9 хостов" in row[1], "числа не расходятся с перечнем хостов"


def test_silent_third_party_page_is_not_praised_as_clean():
    row = row_of(
        speed.build_speed_checks(built(markup=speed.parse_markup("<p>текст</p>", ORIGIN))),
        "Чужие скрипты и виджеты",
    )

    assert verdict_of(row) == speed.OK
    assert row[1] == "чужих подключений нет" and "только от вашего хостинга" in row[2]


def test_images_are_praised_only_when_something_lightens_them():
    row = row_of(speed.build_speed_checks(built()), "Картинки: ленивая загрузка и форматы")
    assert verdict_of(row) == speed.OK

    plain = speed.parse_markup("<html><body><img src='/a.jpg'></body></html>", ORIGIN)
    heavy = row_of(
        speed.build_speed_checks(built(markup=plain)), "Картинки: ленивая загрузка и форматы"
    )
    assert verdict_of(heavy) == speed.CHECK
    assert "полноразмерную" in heavy[2]


def test_font_row_blames_the_missing_hint_and_not_the_font():
    hinted = row_of(speed.build_speed_checks(built()), "Шрифты")
    assert verdict_of(hinted) == speed.OK
    assert "не ждёт молча" in hinted[2]

    bare = speed.parse_markup("<style>@font-face {font-family: X}</style>", ORIGIN)
    raw = row_of(speed.build_speed_checks(built(markup=bare)), "Шрифты")
    assert verdict_of(raw) == speed.CHECK
    assert "текст ждёт шрифт" in raw[2]


def test_mobile_row_separates_locked_zoom_from_missing_viewport():
    locked = row_of(speed.build_speed_checks(built()), "Мобильная настройка")
    assert verdict_of(locked) == speed.CHECK
    assert "зум пальцем выключён" in locked[1] and "приблизить" in locked[2]

    open_zoom = speed.parse_markup(
        '<meta name="viewport" content="width=device-width">', ORIGIN
    )
    fit = row_of(speed.build_speed_checks(built(markup=open_zoom)), "Мобильная настройка")
    assert verdict_of(fit) == speed.OK

    absent = speed.parse_markup("<html><body><p>без шапки</p></body></html>", ORIGIN)
    blind = row_of(speed.build_speed_checks(built(markup=absent)), "Мобильная настройка")
    assert "viewport не найден" in blind[1] and "показывают целиком" in blind[2]


def test_compressed_but_heavy_html_is_a_warning_not_an_error():
    heavy = measured(wire_bytes=400_000, content_bytes=1_200_000, headers={
        "Content-Type": "text/html", "Content-Encoding": "gzip"})
    row = row_of(speed.build_speed_checks(built(page=heavy)), "Вес главной страницы")

    assert verdict_of(row) == speed.CHECK
    assert "тяжёлая" in row[2]


def test_protocol_row_stays_out_when_the_version_is_unknown():
    table = speed.build_speed_checks(built(page=measured(http_version="")))

    assert not [r for r in table["rows"] if r[0] == "Протокол соединения"], (
        "протокол не измерен — выводить нечего"
    )


def test_psi_score_row_grades_the_number_it_was_given():
    strong = {"state": "ok", "score": 93, "strategy": "mobile", "lab": {}, "field": {}}
    weak = {"state": "ok", "score": 24, "lab": {}, "field": {}}

    good = row_of(speed.build_speed_checks(built(psi=strong)), "PageSpeed Insights (мобильные)")
    bad = row_of(speed.build_speed_checks(built(psi=weak)), "PageSpeed Insights (мобильные)")

    assert verdict_of(good) == speed.OK and good[1] == "балл 93, mobile"
    assert verdict_of(bad) == speed.BAD


def test_assess_keeps_the_markup_when_the_probe_and_the_test_break():
    """Этапы независимы: разбор разметки не стоит запроса и не зависит от чужих сбоев."""
    def explode(*args):
        raise RuntimeError("сбой запроса")

    result = speed.assess(ORIGIN, HEAVY_PAGE, PAGE, explode, explode)

    assert result["markup"]["parsed"] == 1
    assert result["page"]["ttfb_ms"] == 720
    assert result["assets"]["stopped"] == "проба не удалась"
    assert result["psi"]["state"] == "error"


# --- собственные запросы анализатора ---------------------------------------


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(b"0123", b"4567"), version=20,
                 history=(), url=ORIGIN + "/", encoding="utf-8"):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks
        self.raw = type("Raw", (), {"version": version})()
        self.history = list(history)
        self.url = url
        self.encoding = encoding
        self.closed = False

    def iter_content(self, size):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        self.closed = True


def patch_get(analyzer, monkeypatch, response=None, error=None):
    """Подменяет requests.get и записывает, с какими параметрами заходили."""
    seen = []

    def fake_get(url, **kwargs):
        seen.append((url, kwargs))
        if error:
            raise error
        return response

    monkeypatch.setattr(analyzer_module.requests, "get", fake_get)
    monkeypatch.setattr(SiteAnalyzer, "_validate_url", staticmethod(lambda url: url))
    return seen


def test_fetch_measured_returns_stopwatch_bytes_and_protocol(analyzer, monkeypatch):
    response = FakeResponse(
        headers={"Content-Length": "4096", "Content-Encoding": "br", "Server": "nginx",
                 "Content-Type": "text/html; charset=utf-8"},
        version=11, history=[object(), object()], url=ORIGIN + "/index.php",
    )
    seen = patch_get(analyzer, monkeypatch, response)

    probe = analyzer.fetch_measured(ORIGIN + "/")

    assert seen[0][1]["stream"] is True, "часы врубаются до чтения тела"
    assert "br" in seen[0][1]["headers"]["Accept-Encoding"], (
        "без запроса сжатия сервер отдал бы несжатый HTML — и «без сжатия» было бы наврано"
    )
    assert probe["status"] == 200 and probe["ttfb_ms"] >= 0
    assert probe["content_bytes"] == 8, "вес разметки — это прочитанное тело"
    assert probe["wire_bytes"] == 4096, "вес в сети берут из Content-Length"
    assert probe["http_version"] == "HTTP/1.1"
    assert probe["redirects"] == 2 and probe["final_url"] == ORIGIN + "/index.php"
    assert probe["headers"]["Content-Encoding"] == "br"
    assert response.closed, "незакрытое соединение стоит времени всего анализа"


def test_fetch_measured_reports_no_wire_weight_for_a_chunked_response(analyzer, monkeypatch):
    """Сжатый ответ кусками: Content-Length нет — значит вес в сети не измерен."""
    response = FakeResponse(headers={"Content-Encoding": "br", "Content-Type": "text/html"})
    patch_get(analyzer, monkeypatch, response)

    probe = analyzer.fetch_measured(ORIGIN + "/")

    assert probe["content_bytes"] == 8, "тело прочитано и его размер известен"
    assert probe["wire_bytes"] == 0, "размер тела не выдают за вес в сети"
    assert speed.normalize_page(probe)["wire_bytes"] == 0


def test_fetch_measured_counts_the_body_when_nothing_was_compressed(analyzer, monkeypatch):
    response = FakeResponse(headers={"Content-Type": "text/html"})
    patch_get(analyzer, monkeypatch, response)

    assert analyzer.fetch_measured(ORIGIN + "/")["wire_bytes"] == 8, (
        "без сжатия по сети шло ровно прочитанное тело"
    )


def test_fetch_measured_raises_instead_of_reporting_zero_seconds(analyzer, monkeypatch):
    """Часы не могут соврать: таймаут — это исключение, а не «0 мс»."""
    patch_get(analyzer, monkeypatch, error=ConnectionError("сервер молчит"))

    with pytest.raises(Exception):
        analyzer.fetch_measured(ORIGIN + "/")


def test_fetch_headers_needs_no_body_and_never_raises(analyzer, monkeypatch):
    response = FakeResponse(headers={"Content-Length": "1200", "Content-Encoding": "gzip",
                                     "Cache-Control": "max-age=86400",
                                     "Content-Type": "application/javascript"})
    seen = patch_get(analyzer, monkeypatch, response)

    head = analyzer.fetch_headers(ORIGIN + "/app.js")

    assert seen[0][1]["stream"] is True, "тело ресурса в пробу не качают"
    assert head["status"] == 200 and head["bytes"] == 1200
    assert head["encoding"] == "gzip" and head["cache_control"] == "max-age=86400"
    assert response.closed

    patch_get(analyzer, monkeypatch, error=RuntimeError("обрыв"))
    assert analyzer.fetch_headers(ORIGIN + "/app.js")["status"] == 0


def test_pagespeed_request_is_mobile_and_honest_about_failure(analyzer, monkeypatch):
    response = FakeResponse(status=200, headers={}, chunks=[])
    response.json = lambda: {"lighthouseResult": {"audits": {}}}
    seen = patch_get(analyzer, monkeypatch, response)

    probe = analyzer.run_pagespeed(ORIGIN + "/")

    params = seen[0][1]["params"]
    assert params["url"] == ORIGIN + "/" and params["strategy"] == "mobile"
    assert params["category"] == "PERFORMANCE"
    assert "key" not in params, "ключа в конфигурации нет — в запросе его быть не должно"
    assert probe["status"] == 200 and probe["body"]["lighthouseResult"]

    patch_get(analyzer, monkeypatch, error=ConnectionError("таймаут"))
    assert analyzer.run_pagespeed(ORIGIN + "/") == {"status": 0, "body": {}}


def test_pagespeed_key_is_sent_only_when_configured(analyzer, monkeypatch):
    response = FakeResponse(status=200, chunks=[])
    response.json = lambda: {}
    seen = patch_get(analyzer, monkeypatch, response)
    monkeypatch.setenv("PAGESPEED_API_KEY", "secret-key")

    analyzer.run_pagespeed(ORIGIN + "/")

    assert seen[0][1]["params"]["key"] == "secret-key"


def test_pagespeed_accepts_a_reply_that_is_not_json(analyzer, monkeypatch):
    class Broken(FakeResponse):
        def json(self):
            raise ValueError("не json")

    patch_get(analyzer, monkeypatch, Broken(status=200, chunks=[]))

    probe = analyzer.run_pagespeed(ORIGIN + "/")

    assert probe == {"status": 200, "body": {}}, "HTML-ответ прокси не должен ронять раздел"


def test_analysis_survives_a_site_that_refuses_to_be_measured(analyzer, monkeypatch):
    """Замер скорости — отдельный запрос: его отказ не отменяет аудит сайта."""
    monkeypatch.setattr(analyzer, "fetch_site_html", lambda url: HEAVY_PAGE)
    monkeypatch.setattr(analyzer, "fetch_probe",
                        lambda url, method="GET": {"status": 404, "text": "", "chain": []})

    _, _, facts = analyzer.collect_site_evidence(HOME + "/")

    assert facts["speed"]["page"]["measured"] is False
    assert facts["speed"]["markup"]["parsed"] == 1, "разметка прочитана без единого запроса"
    assert facts["speed"]["psi"]["state"] == "unreachable"
    assert facts["speed"]["assets"]["checked"] == speed.MAX_ASSET_PROBES
    row = row_of(speed.build_speed_checks(facts["speed"]), "Вес ресурсов (проба заголовков)")
    assert verdict_of(row) == speed.UNKNOWN, "молчание сервера — не «ресурс не найден»"


def test_a_broken_speed_assessment_degrades_to_one_line(analyzer, monkeypatch):
    """Сбой сборки фактов — строка «замер не завершился», а не падший аудит."""
    monkeypatch.setattr(analyzer, "fetch_site_html", lambda url: HEAVY_PAGE)
    monkeypatch.setattr(analyzer, "fetch_probe",
                        lambda url, method="GET": {"status": 404, "text": "", "chain": []})

    def broken(*args, **kwargs):
        raise RuntimeError("сбор фактов скорости не удался")

    monkeypatch.setattr(speed, "assess", broken)
    _, _, facts = analyzer.collect_site_evidence(HOME + "/")

    assert facts["speed"] == {"failed": True}
    rows = speed.build_speed_checks(facts["speed"])["rows"]
    assert len(rows) == 1 and rows[0][1] == "замер не завершился"


# --- место раздела в анализе ------------------------------------------------


def test_section_order_keeps_speed_after_the_crawl():
    order = list(analyzer_module.REPORT_SECTION_ORDER)

    assert order.count("site_speed") == 1
    assert order.index("site_crawl") < order.index("site_speed") < order.index("ad_instructions")


def test_analysis_measures_speed_once_and_keeps_it_in_facts(analyzer, monkeypatch):
    calls = []

    def html_fetch(url):
        return HEAVY_PAGE

    def measured_fetch(url):
        calls.append(("page", url))
        return dict(PAGE, text=HEAVY_PAGE)

    def head(url):
        calls.append(("head", url))
        return {"status": 200, "bytes": 40_000, "encoding": "gzip",
                "cache_control": "max-age=2592000"}

    def psi(url):
        calls.append(("psi", url))
        return {"status": 429, "body": {"error": {"code": 429}}}

    monkeypatch.setattr(analyzer, "fetch_site_html", html_fetch)
    monkeypatch.setattr(analyzer, "fetch_probe",
                        lambda url, method="GET": {"status": 404, "text": "", "chain": []})
    monkeypatch.setattr(analyzer, "fetch_measured", measured_fetch)
    monkeypatch.setattr(analyzer, "fetch_headers", head)
    monkeypatch.setattr(analyzer, "run_pagespeed", psi)

    _, _, facts = analyzer.collect_site_evidence(HOME + "/")
    table = speed.build_speed_checks(facts["speed"])

    assert facts["speed"]["page"]["ttfb_ms"] == 720
    assert facts["speed"]["markup"]["parsed"] == 1
    assert facts["speed"]["psi"]["state"] == "quota"
    assert [kind for kind, _ in calls].count("psi") == 1, "тест запрашивают один раз за анализ"
    assert [kind for kind, _ in calls].count("head") <= speed.MAX_ASSET_PROBES
    assert verdict_of(row_of(table, "Ответ сервера")) == speed.BAD


def test_speed_reaches_the_report_after_the_crawl_section(analyzer):
    sources = [{"id": 1, "url": HOME, "path": "/", "title": "T", "chars": 900}]

    def head(url, method="GET"):
        return {"status": 404, "text": "", "chain": []}

    facts = {
        "phones": [], "emails": [], "legal_entities": [], "requisites": [], "prices": [],
        "crawl": {"pages": 9, "limit": crawl.MAX_CRAWL_PAGES, "text_pages": 4,
                  "sections": ["catalog"], "depth": 2, "paged": 0, "duplicates": [],
                  "failures": [], "refused": {}, "pending": 0, "stopped": "",
                  "seconds": 18.0, "budget": 50.0},
        "signals": marks.scan_page(HEAVY_PAGE),
        "infra": infra.probe_site(HOME, head, []),
        "speed": built(),
    }

    normalized = analyzer._normalize_final_analysis({"brief_analysis": "разбор"}, sources, facts)
    keys = list(normalized)

    order = list(analyzer_module.REPORT_SECTION_ORDER)
    assert keys.index("site_crawl") < keys.index("site_speed")
    assert order.index("site_speed") < order.index("ad_instructions")
    assert row_of(normalized["site_speed"], "Ответ сервера")[1].startswith("720 мс")
    joined = "\n".join(normalized["data_gaps"])
    assert "PageSpeed Insights нет" in joined, "недоступность теста обязана быть в пробелах"


def test_failed_measurement_still_answers_in_one_line():
    block = speed.render_speed({"failed": True})

    assert block.startswith("## Скорость и мобильность")
    assert "выводов о скорости нет" in block and "Замер главной" not in block, (
        "из сломанного замера не делают видимость проверки"
    )


def test_checks_block_lets_a_failed_measurement_out_of_the_prompt(analyzer):
    """Неудачный замер не должен приходить модели как факт — только таблица его видит."""
    with_numbers = analyzer._checks_block({"speed": built()})
    without = analyzer._checks_block({"speed": {"failed": True}})
    empty = analyzer._checks_block({})

    assert "Скорость и мобильность" in with_numbers
    assert "Скорость и мобильность" not in without
    assert "Скорость и мобильность" not in empty
