"""The frame's count of birds in the window that have no illustration yet."""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CROW = {"sci": "Corvus brachyrhynchos", "com": "American Crow", "n": 20}
NEW = {"sci": "Nonexistus birdus", "com": "Made-up Bird", "n": 2}
OTHER = {"sci": "Nonexistus alter", "com": "Other Bird", "n": 1}
DIMS = {"corvus-brachyrhynchos", "corvus-brachyrhynchos-2"}


def load_display():
    spec = importlib.util.spec_from_file_location("missing_art_display", ROOT / "frame/display.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MissingArtTest(unittest.TestCase):
    def setUp(self):
        self.display = load_display()
        self.cfg = dict(self.display.DEFAULTS, shoot=True)

    def test_count_and_note(self):
        d = self.display
        self.assertEqual(d.missing_count([CROW], DIMS), 0)
        self.assertEqual(d.missing_count([CROW, NEW, OTHER], DIMS), 2)
        self.assertIsNone(d.missing_note(self.cfg, 0))
        self.assertEqual(d.missing_note(self.cfg, 1), "+ 1 oiseau non illustré")
        self.assertEqual(d.missing_note(self.cfg, 3), "+ 3 oiseaux non illustrés")
        custom = dict(self.cfg, missing_label="{n} to draw", missing_label_one="")
        self.assertEqual(d.missing_note(custom, 2), "2 to draw")
        self.assertIsNone(d.missing_note(custom, 1))

    def test_signature_follows_the_count_and_keeps_old_ones_without_missing(self):
        d = self.display
        cfg = dict(self.cfg, _schedule_scope="sun:day")
        plain = d.signature([CROW], d.signature_scope(cfg))
        self.assertEqual(d.signature([CROW], d.signature_scope(cfg, [CROW], DIMS)), plain)
        self.assertEqual(d.signature([CROW], d.signature_scope(cfg, [CROW], None)), plain)
        one = d.signature([CROW, NEW], d.signature_scope(cfg, [CROW, NEW], DIMS))
        drawn = d.signature([CROW, NEW], d.signature_scope(cfg, [CROW, NEW], DIMS | {"nonexistus-birdus"}))
        self.assertNotEqual(one, drawn)

    def test_art_index_only_for_local_capture(self):
        d = self.display
        with mock.patch.object(d, "fetch_dims", return_value=DIMS) as fetch:
            self.assertEqual(d.art_index(self.cfg), DIMS)
            self.assertIsNone(d.art_index(dict(self.cfg, shoot=False, image_url="http://x/f.png")))
            self.assertIsNone(d.art_index(dict(self.cfg, species_source="birdweather")))
            self.assertIsNone(d.art_index(dict(self.cfg, missing_label="")))
        self.assertEqual(fetch.call_count, 1)

    def test_failed_dims_fetch_only_drops_the_note(self):
        d = self.display
        with mock.patch.object(d, "fetch_dims", side_effect=OSError("down")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(d.art_index(self.cfg))
        self.assertIn("no missing count", err.getvalue())

    def test_fetch_dims_reads_station_table(self):
        d = self.display
        body = io.BytesIO(json.dumps({"corvus-brachyrhynchos": [560, 500]}).encode())
        with mock.patch.object(d.urllib.request, "urlopen", return_value=contextlib.nullcontext(body)) as urlopen:
            self.assertEqual(d.fetch_dims("http://station/", 5, "Basic abc"), {"corvus-brachyrhynchos"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://station/dims.json")
        self.assertEqual(request.get_header("Authorization"), "Basic abc")
        with mock.patch.object(d.urllib.request, "urlopen", return_value=contextlib.nullcontext(io.BytesIO(b"{}"))):
            with self.assertRaises(ValueError):
                d.fetch_dims("http://station", 5)

    def test_run_passes_the_note_to_the_capture(self):
        d = self.display
        seen = {}

        def obtain(cfg, species, *, capture=None, dims=None):
            seen["dims"] = dims
            return mock.Mock()

        with mock.patch.object(d, "load_state", return_value={}), \
                mock.patch.object(d, "fetch_dims", return_value=DIMS), \
                mock.patch.object(d, "fetch_species", return_value=[CROW, NEW]), \
                mock.patch.object(d, "obtain_image", side_effect=obtain), \
                mock.patch.object(d, "fit_panel"), mock.patch.object(d, "mat_and_center"), \
                mock.patch.object(d, "push_panel"), \
                mock.patch.object(d, "save_state") as save, \
                contextlib.redirect_stdout(io.StringIO()):
            d.run(self.cfg)
        self.assertEqual(seen["dims"], DIMS)
        self.assertEqual(save.call_args.args[1],
                         d.signature([CROW, NEW], d.signature_scope(self.cfg, [CROW, NEW], DIMS)))

    def test_shoot_gets_a_note_from_the_drawn_species(self):
        d = self.display
        calls = []
        fake = mock.Mock(shoot=lambda *a, **kw: calls.append(kw))
        with mock.patch.dict("sys.modules", {"shoot": fake}), \
                mock.patch.object(d.Image, "open"):
            d.obtain_image(self.cfg, [CROW], capture={}, dims=DIMS)
            d.obtain_image(self.cfg, [CROW], capture={})
        note = calls[0]["subtitle_note"]
        self.assertEqual(note([CROW, NEW]), "+ 1 oiseau non illustré")
        self.assertIsNone(note([CROW]))
        self.assertIsNone(calls[1]["subtitle_note"])


if __name__ == "__main__":
    unittest.main()
