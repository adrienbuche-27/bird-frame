import contextlib
import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo


ROOT = pathlib.Path(__file__).resolve().parents[1]
FRAME = ROOT / "frame"
PARIS = ZoneInfo("Europe/Paris")
LAT, LON = 48.8566, 2.3522


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SunTimesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sun = load_module("frame_suntimes_test", FRAME / "suntimes.py")

    def assertNear(self, actual, hh, mm, tz=PARIS):
        expected = datetime.combine(actual.astimezone(tz).date(), datetime.min.time(), tz)
        expected = expected.replace(hour=hh, minute=mm)
        self.assertLessEqual(abs((actual - expected).total_seconds()), 180)

    def test_paris_autumn(self):
        rise, sset = self.sun.sun_times(date(2026, 10, 6), LAT, LON)
        self.assertNear(rise, 7, 58)
        self.assertNear(sset, 19, 19)

    def test_paris_midsummer(self):
        rise, sset = self.sun.sun_times(date(2026, 6, 21), LAT, LON)
        self.assertNear(rise, 5, 47)
        self.assertNear(sset, 21, 58)

    def test_polar_cases(self):
        self.assertEqual(self.sun.sun_times(date(2026, 6, 21), 69.65, 18.96), ("polar_day", None))
        self.assertEqual(self.sun.sun_times(date(2026, 12, 21), 69.65, 18.96), (None, "polar_night"))


class SunScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(FRAME))
        cls.display = load_module("frame_display_schedule_test", FRAME / "display.py")

    def cfg(self, **extra):
        cfg = dict(self.display.DEFAULTS, shoot=True, schedule="sun", latitude=LAT, longitude=LON)
        cfg.update(extra)
        return cfg

    def at(self, month, day, hh, mm):
        return datetime(2026, month, day, hh, mm, tzinfo=PARIS)

    def quiet(self, fn, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return fn(*args)

    def test_daytime_shows_last_hour(self):
        out = self.quiet(self.display.apply_sun_schedule, self.cfg(), self.at(10, 6, 12, 0))
        self.assertEqual(out["hours"], 1)
        self.assertEqual(out["shoot_subtitle"], "Dernière heure")
        self.assertEqual(out["_schedule_scope"], "sun:day")

    def test_evening_shows_since_sunrise(self):
        # Sunrise ~07:58, so 21:00 is 13h02 later: rounded up to 14h.
        out = self.quiet(self.display.apply_sun_schedule, self.cfg(), self.at(10, 6, 21, 0))
        self.assertEqual(out["hours"], 14)
        self.assertEqual(out["shoot_subtitle"], "Aujourd'hui")
        self.assertEqual(out["_schedule_scope"], "sun:night")

    def test_before_dawn_uses_yesterdays_sunrise(self):
        # 05:00 on the 7th is ~21h after sunrise on the 6th.
        out = self.quiet(self.display.apply_sun_schedule, self.cfg(), self.at(10, 7, 5, 0))
        self.assertEqual(out["hours"], 22)
        self.assertEqual(out["_schedule_scope"], "sun:night")

    def test_custom_day_window_and_subtitles(self):
        cfg = self.cfg(day_hours=2, day_subtitle="Last Hours", night_subtitle="Today")
        day = self.quiet(self.display.apply_sun_schedule, cfg, self.at(10, 6, 12, 0))
        night = self.quiet(self.display.apply_sun_schedule, cfg, self.at(10, 6, 22, 0))
        self.assertEqual((day["hours"], day["shoot_subtitle"]), (2, "Last Hours"))
        self.assertEqual(night["shoot_subtitle"], "Today")

    def test_ignored_without_local_capture(self):
        cfg = self.cfg(shoot=False, image_url="https://example.invalid/frame.png")
        out = self.quiet(self.display.apply_sun_schedule, cfg, self.at(10, 6, 12, 0))
        self.assertNotIn("_schedule_scope", out)
        self.assertEqual(out["hours"], 24)

    def test_location_from_birdnet_conf(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("SITE_NAME=garden\nLATITUDE=48.8566\nLONGITUDE='2.3522'\n")
        self.addCleanup(pathlib.Path(f.name).unlink)
        cfg = self.cfg(latitude=None, longitude=None, birdnet_conf=f.name)
        self.assertEqual(self.display.sun_location(cfg), (48.8566, 2.3522))

    def run_with(self, species, state=None, force=False):
        """Run display.run with the network, capture and panel stubbed out."""
        with tempfile.TemporaryDirectory() as tmp:
            state_path = pathlib.Path(tmp) / "state.json"
            if state is not None:
                self.display.save_state(str(state_path), *state)
            cfg = self.cfg(state=str(state_path), cache=tmp)
            with mock.patch.object(self.display, "fetch_species", return_value=species), \
                    mock.patch.object(self.display, "obtain_image") as obtain, \
                    mock.patch.object(self.display, "mat_and_center"), \
                    mock.patch.object(self.display, "fit_panel"), \
                    mock.patch.object(self.display, "push_panel") as push, \
                    mock.patch.object(self.display, "apply_sun_schedule",
                                      side_effect=lambda c, now: dict(c, hours=1, _schedule_scope="sun:day")):
                self.quiet(self.display.run, cfg, None, force)
            return obtain, push

    def test_empty_window_keeps_current_image(self):
        _, push = self.run_with([])
        push.assert_not_called()

    def test_force_still_renders_empty_window(self):
        _, push = self.run_with([], force=True)
        push.assert_called_once()

    def test_birds_in_window_refresh_panel(self):
        _, push = self.run_with([{"sci": "Pica pica", "n": 3}])
        push.assert_called_once()

    def test_phase_change_alone_triggers_refresh(self):
        species = [{"sci": "Pica pica", "n": 3}]
        night_sig = self.display.signature(species, "sun:night")
        _, push = self.run_with(species, state=(night_sig, 9e18))
        push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
