"""Birds heard without an illustration, in a real Chromium: the line under the
collage (current window) and the Atlas "to illustrate" sort (every bird heard,
field recordings included). Both are admin-only. The station frontend is
served from avian/frontend; the APIs are answered by the test.
"""
import json

import pytest

from tests.test_field_map_browser import browser, site  # noqa: F401 (fixtures)

pytest.importorskip("playwright.sync_api")

CROW = {"sci": "Corvus brachyrhynchos", "com": "American Crow"}
NEW = {"sci": "Nonexistus primus", "com": "First Made-up Bird"}
OLD = {"sci": "Nonexistus vetus", "com": "Old Made-up Bird"}
FIELD_ONLY = {"sci": "Nonexistus campus", "com": "Field Made-up Bird"}
RECENT = [dict(CROW, n=12), dict(NEW, n=3)]
LIFELIST = [dict(CROW, n=500, first_seen="2025-01-01 07:00:00"),
            dict(OLD, n=4, first_seen="2025-03-01 07:00:00"),
            dict(NEW, n=3, first_seen="2026-10-07 08:00:00")]
RECORDINGS = [{
    "id": 5, "name": "walk.m4a", "recorded_at": "2026-09-01T07:00:00", "lat": 48.8, "lon": 2.4,
    "place": "Bois", "status": "done", "error": None, "duration_s": 60.0, "size_bytes": 10,
    "created_at": "2026-09-01T09:00:00", "analyzed_at": "2026-09-01T09:01:00",
    "species": [dict(FIELD_ONLY, n=1, best=0.9), dict(CROW, n=1, best=0.8)],
    "detections": [dict(FIELD_ONLY, confidence=0.9, start=3.0, end=6.0),
                   dict(CROW, confidence=0.8, start=9.0, end=12.0),
                   dict(NEW, confidence=0.7, start=15.0, end=18.0)]}]


def open_station(browser, site, unlocked=True, stored_sort=None):  # noqa: F811
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    if stored_sort:
        page.add_init_script("localStorage.setItem('bird:atlasSort', %s)" % json.dumps(stored_sort))
    state = {"recent": [dict(s) for s in RECENT], "field_lists": 0}

    def api(route):
        url = route.request.url
        if "/avian/api/menu.php" in url:
            if not unlocked:
                return route.fulfill(status=401, json={"ok": False, "error": "unauthorized"})
            return route.fulfill(json={"items": [{"label": "settings", "href": "/#admin=settings", "native": True}],
                                       "auth": {"required": False, "direct_local": True}})
        if "/avian/api/field.php" in url:
            state["field_lists"] += 1
            return route.fulfill(json={"ok": True, "recordings": RECORDINGS})
        if "action=recent" in url:
            return route.fulfill(json={"hours": 24, "species": state["recent"], "as_of": ""})
        if "action=lifelist" in url:
            return route.fulfill(json={"species": LIFELIST})
        return route.fulfill(json={})

    page.route("**/avian/api/**", api)
    page.goto(site)
    return page, state


def test_line_under_collage_counts_the_window_and_opens_the_list(browser, site):  # noqa: F811
    page, _ = open_station(browser, site)
    line = page.locator("#artMissing")
    line.wait_for(state="visible", timeout=15000)
    # Only the window's birds: the old one and the field-only one are not in it.
    assert line.inner_text() == "1 bird without illustration: First Made-up Bird"
    button = page.locator("#atlasSort button[data-sort='missing']")
    assert button.is_visible()
    # Every bird heard: station life list plus field-only species.
    page.wait_for_function("document.querySelector(\"#atlasSort button[data-sort='missing'] .missing-n\").textContent === '3'")

    line.click()
    page.wait_for_selector("#atlasGrid .bird-card[data-sci='Nonexistus campus']")
    assert page.evaluate("localStorage.getItem('bird:atlasSort')") == "missing"
    assert button.get_attribute("aria-current") == "true"
    cards = page.locator("#atlasGrid .bird-card")
    scis = cards.evaluate_all("cs => cs.map(c => c.dataset.sci)")
    assert sorted(scis) == ["Nonexistus campus", "Nonexistus primus", "Nonexistus vetus"]
    assert cards.evaluate_all("cs => cs.every(c => c.classList.contains('needs-art'))")
    # The field-only bird keeps its field postcard; station birds do not get one.
    field = cards.evaluate_all("cs => cs.filter(c => c.dataset.field === '1').map(c => c.dataset.sci)")
    assert field == ["Nonexistus campus"]


def test_line_disappears_when_every_bird_in_the_window_is_drawn(browser, site):  # noqa: F811
    page, state = open_station(browser, site)
    page.locator("#artMissing").wait_for(state="visible", timeout=15000)
    # The new bird got its illustration (here: it left the window); load again.
    state["recent"] = [dict(CROW, n=13)]
    page.reload()
    page.wait_for_selector("#atlasSort button[data-sort='missing']:not([hidden])", timeout=15000)
    page.wait_for_timeout(500)
    assert page.locator("#artMissing").is_hidden()


def test_nothing_shows_without_admin(browser, site):  # noqa: F811
    page, state = open_station(browser, site, unlocked=False, stored_sort="missing")
    page.wait_for_selector("#collage .gtile, #collage img", state="attached", timeout=15000)
    page.wait_for_timeout(800)
    assert page.locator("#artMissing").is_hidden()
    assert page.locator("#atlasSort button[data-sort='missing']").is_hidden()
    # A remembered "to illustrate" sort falls back to the life list.
    page.click("#slider button[data-i='2']")
    page.wait_for_selector("#atlasGrid .bird-card", state="attached")
    assert page.locator("#atlasSort button[aria-current='true']").get_attribute("data-sort") == "life"
    assert state["field_lists"] == 0
