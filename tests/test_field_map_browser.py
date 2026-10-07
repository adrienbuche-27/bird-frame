"""Field recordings map page (#admin=field) in a real Chromium.

The station frontend is served from avian/frontend; the admin menu and
field.php are answered by the test, Leaflet comes from a local copy of the
pinned release (same bytes as the CDN, so the SRI hash must match), and map
tiles are a blank PNG. Nothing leaves the machine.
"""
import base64
import functools
import http.server
import io
import json
import os
import threading
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
LEAFLET = ROOT / "tests/testdata/leaflet-1.9.4"

RECORDINGS = [
    {"id": 2, "name": "dawn.m4a", "recorded_at": "2026-05-01T06:15:00", "lat": 48.8448, "lon": 2.4395,
     "place": "Bois de Vincennes", "status": "done", "error": None, "duration_s": 312.0, "size_bytes": 10,
     "created_at": "2026-05-01T09:00:00", "analyzed_at": "2026-05-01T09:01:00",
     "species": [{"sci": "Pica pica", "com": "Eurasian Magpie", "n": 3, "best": 0.93},
                 {"sci": "Erithacus rubecula", "com": "European Robin", "n": 1, "best": 0.78}],
     "detections": []},
    {"id": 1, "name": "coast.wav", "recorded_at": "2026-04-20T18:40:00", "lat": 47.2, "lon": -2.5,
     "place": "", "status": "error", "error": "could not decode audio: invalid data", "duration_s": None,
     "size_bytes": 10, "created_at": "2026-04-20T20:00:00", "analyzed_at": None,
     "species": [], "detections": []},
]


def blank_png():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (256, 256), (230, 230, 225)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}),
        directory=str(ROOT / "avian/frontend")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    server.server_close()


@pytest.fixture
def browser():
    executable = os.environ.get("FRAME_TEST_CHROMIUM")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(**({"executable_path": executable} if executable else {}))
        yield b
        b.close()


def open_field_page(browser, site, calls):
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    state = {"recordings": [dict(r) for r in RECORDINGS], "upload": bytearray()}
    tile = blank_png()

    def api(route):
        request = route.request
        url = request.url
        if "/avian/api/menu.php" in url:
            return route.fulfill(json={"items": [
                {"label": "settings", "href": "/#admin=settings", "native": True},
                {"label": "map", "href": "/#admin=field", "native": True, "full": True}],
                "auth": {"required": False, "direct_local": True}})
        if "/avian/api/field.php" in url:
            action = url.split("action=")[1].split("&")[0]
            body = json.loads(request.post_data) if request.post_data else {}
            calls.append((action, body, dict(request.headers)))
            if action == "list":
                return route.fulfill(json={"ok": True, "recordings": state["recordings"]})
            if action == "begin":
                state["begin"] = body
                return route.fulfill(json={"ok": True, "id": 3, "chunk_bytes": 4})
            if action == "chunk":
                state["upload"] += base64.b64decode(body["data"])
                return route.fulfill(json={"ok": True, "received": len(state["upload"])})
            if action == "finish":
                b = state["begin"]
                state["recordings"].insert(0, dict(RECORDINGS[0], id=3, place=b.get("place", ""), lat=b["lat"],
                                                   lon=b["lon"], status="queued", species=[]))
                return route.fulfill(json={"ok": True, "id": 3, "status": "queued"})
            if action in ("update", "reanalyze", "delete"):
                if action == "delete":
                    state["recordings"] = [r for r in state["recordings"] if r["id"] != body["id"]]
                return route.fulfill(json={"ok": True, "id": body["id"]})
            return route.fulfill(status=404, json={"ok": False, "error": "unknown action"})
        if "/avian/api/" in url:
            return route.fulfill(json={})
        return route.continue_()

    page.route("**/avian/api/**", api)
    page.route("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
               lambda r: r.fulfill(body=(LEAFLET / "leaflet.js").read_bytes(), content_type="application/javascript",
                                   headers={"Access-Control-Allow-Origin": "*"}))
    page.route("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
               lambda r: r.fulfill(body=(LEAFLET / "leaflet.css").read_bytes(), content_type="text/css",
                                   headers={"Access-Control-Allow-Origin": "*"}))
    page.route("https://tile.openstreetmap.org/**", lambda r: r.fulfill(body=tile, content_type="image/png"))
    page.goto(site + "#admin=field")
    page.wait_for_selector(".field-map.leaflet-container", timeout=15000)
    return page, state


def test_map_lists_and_shows_recordings(browser, site):
    calls = []
    page, _ = open_field_page(browser, site, calls)
    assert page.inner_text("#adminTitle") == "Field recordings"
    page.wait_for_selector(".field-item")
    items = page.locator(".field-item")
    assert items.count() == 2
    assert "Bois de Vincennes" in items.nth(0).inner_text()
    assert "Eurasian Magpie, European Robin" in items.nth(0).inner_text()
    assert "47.20000, -2.50000" in items.nth(1).inner_text()  # no place name: coordinates
    # One vector marker per recording, no marker images needed.
    assert page.locator(".leaflet-interactive").count() == 2

    items.nth(0).click()
    detail = page.locator("#fieldDetail")
    assert "Eurasian Magpie" in detail.inner_text() and "93%" in detail.inner_text()
    assert detail.locator("audio").get_attribute("src").endswith("field.php?action=audio&id=2")
    assert "cutout.php?sci=Pica%20pica" in detail.locator("img").first.get_attribute("src")

    items.nth(1).click()
    assert "could not decode audio" in page.inner_text("#fieldDetail")


def test_upload_in_chunks_after_picking_a_spot(browser, site, tmp_path):
    calls = []
    page, state = open_field_page(browser, site, calls)
    payload = bytes(range(10))
    audio = tmp_path / "walk.m4a"
    audio.write_bytes(payload)

    page.set_input_files("#fieldFile", str(audio))
    page.click("#fieldSend")
    assert "click the map" in page.inner_text("#fieldUploadStatus")  # position is required

    box = page.locator("#fieldMap").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert "," in page.inner_text("#fieldPos")
    page.fill("#fieldPlace", "Forêt de Fontainebleau")
    page.fill("#fieldWhen", "2026-10-06T07:30")
    page.click("#fieldSend")
    page.wait_for_function("document.getElementById('fieldUploadStatus').textContent.includes('analysing')")

    begin = next(body for action, body, _ in calls if action == "begin")
    assert begin["name"] == "walk.m4a" and begin["size"] == 10
    assert begin["place"] == "Forêt de Fontainebleau" and begin["recorded_at"] == "2026-10-06T07:30"
    assert -90 <= begin["lat"] <= 90 and -180 <= begin["lon"] <= 180
    assert bytes(state["upload"]) == payload  # 3 chunks of at most 4 bytes, in order
    assert [a for a, _, _ in calls].count("chunk") == 3
    for action, _, headers in calls:
        if action != "list":
            assert headers.get("x-avian-action") == "1" and headers.get("content-type") == "application/json"
    page.wait_for_selector(".field-item >> text=Forêt de Fontainebleau")
    assert "waiting" in page.locator(".field-item").first.inner_text().lower()


def test_edit_reanalyse_and_delete(browser, site):
    calls = []
    page, _ = open_field_page(browser, site, calls)
    page.wait_for_selector(".field-item")
    page.locator(".field-item").first.click()
    page.click(".field-edit summary")
    page.fill("[data-field-edit=place]", "Vincennes, lac des Minimes")
    page.click("[data-field-act=save]")
    page.wait_for_function("document.querySelector('[data-field-out]') === null"
                           " || !document.querySelector('[data-field-out]').textContent.includes('working')")
    update = next(body for action, body, _ in calls if action == "update")
    assert update == {"id": 2, "place": "Vincennes, lac des Minimes"}  # date unchanged: not sent

    page.locator(".field-item").first.click()
    page.click("[data-field-act=reanalyze]")
    page.wait_for_timeout(300)
    assert any(action == "reanalyze" for action, _, _ in calls)

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".field-item").first.click()
    page.click("[data-field-act=delete]")
    page.wait_for_function("document.querySelectorAll('.field-item').length === 1")
    assert page.locator("#fieldDetail").is_hidden()
