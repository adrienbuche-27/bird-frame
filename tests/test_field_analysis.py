"""Field recordings: analysis with the recording's own place and date."""
import datetime
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.utils import field
from tests.helpers import TESTDATA, Settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAGPIE = os.path.join(TESTDATA, 'Pica pica_30s.wav')
FEB = datetime.datetime(2024, 2, 24, 16, 19, 37)
HAS_FFMPEG = shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None


def settings():
    return Settings.with_defaults()


@unittest.skipUnless(HAS_FFMPEG, 'field analysis decodes audio with ffmpeg')
@patch('scripts.utils.analysis.loadCustomSpeciesList', return_value=[])
@patch('scripts.utils.field.loadCustomSpeciesList', return_value=[])
@patch('scripts.utils.helpers._load_settings', side_effect=lambda *a, **k: settings())
class FieldAnalysisTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_magpie_found_where_magpies_live(self, *_):
        found = field.analyze_file(MAGPIE, 50, 5, FEB, settings())
        names = {d['sci_name'] for d in found}
        self.assertEqual(names, {'Pica pica'})
        self.assertTrue(all(d['confidence'] >= 0.7 for d in found))
        self.assertTrue(all(d['end_s'] - d['start_s'] == 3.0 for d in found))

    def test_location_drives_the_species_filter(self, *_):
        # Sydney: no magpie (Pica pica) in the range model's list there.
        found = field.analyze_file(MAGPIE, -33.87, 151.21, FEB, settings())
        self.assertNotIn('Pica pica', {d['sci_name'] for d in found})

    def test_phone_formats_are_decoded(self, *_):
        m4a = os.path.join(self.tmp, 'walk.m4a')
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', MAGPIE, '-c:a', 'aac', m4a], check=True)
        found = field.analyze_file(m4a, 50, 5, FEB, settings())
        self.assertIn('Pica pica', {d['sci_name'] for d in found})

    def test_recorded_at_is_read_from_metadata(self, *_):
        tagged = os.path.join(self.tmp, 'tagged.m4a')
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', MAGPIE, '-c:a', 'aac',
                        '-metadata', 'creation_time=2026-05-01T05:30:00Z', tagged], check=True)
        expected = datetime.datetime(2026, 5, 1, 5, 30, tzinfo=datetime.timezone.utc).astimezone()
        self.assertEqual(field.probe_recorded_at(tagged), expected.strftime(field.TIME_FORMAT))
        self.assertIsNone(field.probe_recorded_at(MAGPIE))

    def queue(self, db, name, recorded_at=None, created_at='2024-02-24T17:00:00', lat=50, lon=5):
        audio = os.path.join(self.tmp, 'audio')
        os.makedirs(audio, exist_ok=True)
        cur = db.execute(
            "INSERT INTO recordings (original_name, stored_name, size_bytes, recorded_at, lat, lon, status, created_at) "
            "VALUES (?, ?, 1, ?, ?, ?, 'queued', ?)", (name, name, recorded_at, lat, lon, created_at))
        db.commit()
        return cur.lastrowid, audio

    def test_queue_stores_detections_and_falls_back_to_upload_time(self, *_):
        db_path = os.path.join(self.tmp, 'field.db')
        db = field.connect(db_path)
        rec_id, audio = self.queue(db, 'magpie.wav')
        shutil.copyfile(MAGPIE, os.path.join(audio, 'magpie.wav'))
        self.assertEqual(field.process_queue(db_path, audio, settings()), 1)
        row = db.execute('SELECT * FROM recordings WHERE id = ?', (rec_id,)).fetchone()
        self.assertEqual(row['status'], 'done')
        self.assertEqual(row['recorded_at'], '2024-02-24T17:00:00')  # no metadata: upload time
        self.assertAlmostEqual(row['duration_s'], 30, delta=1)
        species = {r['sci_name'] for r in db.execute('SELECT sci_name FROM detections WHERE recording_id = ?', (rec_id,))}
        self.assertEqual(species, {'Pica pica'})

    def test_unreadable_audio_is_an_error_not_a_crash(self, *_):
        db_path = os.path.join(self.tmp, 'field.db')
        db = field.connect(db_path)
        rec_id, audio = self.queue(db, 'broken.m4a', recorded_at='2024-02-24T08:00:00')
        with open(os.path.join(audio, 'broken.m4a'), 'wb') as f:
            f.write(b'not audio at all')
        field.process_queue(db_path, audio, settings())
        row = db.execute('SELECT status, error FROM recordings WHERE id = ?', (rec_id,)).fetchone()
        self.assertEqual(row['status'], 'error')
        self.assertIn('could not decode audio', row['error'])

    def test_deleting_a_recording_drops_its_detections(self, *_):
        db = field.connect(os.path.join(self.tmp, 'field.db'))
        rec_id, _ = self.queue(db, 'x.wav')
        db.execute("INSERT INTO detections (recording_id, sci_name, com_name, confidence, start_s, end_s) "
                   "VALUES (?, 'Pica pica', 'Magpie', 0.9, 0, 3)", (rec_id,))
        db.execute('DELETE FROM recordings WHERE id = ?', (rec_id,))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM detections').fetchone()[0], 0)


class FieldDatabaseTests(unittest.TestCase):

    def test_database_is_shared_with_the_web_server(self):
        # SQLite creates 0644 files whatever the umask; field.php (the web
        # server, in the owner's group) must be able to write it too.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        db_path = os.path.join(tmp, 'field.db')
        field.connect(db_path).close()
        self.assertEqual(os.stat(db_path).st_mode & 0o060, 0o060)


@unittest.skipUnless(HAS_FFMPEG, 'field analysis decodes audio with ffmpeg')
class FieldWorkerCliTests(unittest.TestCase):
    """scripts/field_analysis.py, imported the way the station runs it."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        spec = importlib.util.spec_from_file_location('field_analysis', os.path.join(ROOT, 'scripts', 'field_analysis.py'))
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(os.path.join(ROOT, 'scripts'))

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        for target in ('utils.helpers._load_settings',):
            p = patch(target, side_effect=lambda *a, **k: settings())
            p.start()
            self.addCleanup(p.stop)
        for target in ('utils.analysis.loadCustomSpeciesList', 'utils.field.loadCustomSpeciesList'):
            p = patch(target, return_value=[])
            p.start()
            self.addCleanup(p.stop)

    def test_run_skips_while_another_worker_holds_the_lock(self):
        import fcntl
        db_path, audio, lock_path = self.cli.paths(settings(), self.tmp)
        with open(lock_path, 'a') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertEqual(self.cli.run(settings(), self.tmp), 0)

    def test_run_requeues_a_recording_left_analyzing(self):
        db_path, audio, _ = self.cli.paths(settings(), self.tmp)
        shutil.copyfile(MAGPIE, os.path.join(audio, '1.wav'))
        db = sqlite3.connect(db_path)
        db.executescript(open(field.SCHEMA_PATH).read())
        db.execute("INSERT INTO recordings (original_name, stored_name, size_bytes, recorded_at, lat, lon, status, "
                   "created_at) VALUES ('a.wav', '1.wav', 1, '2024-02-24T08:00:00', 50, 5, 'analyzing', "
                   "'2024-02-24T08:00:00')")
        db.commit()
        self.assertEqual(self.cli.run(settings(), self.tmp), 1)
        self.assertEqual(db.execute('SELECT status FROM recordings').fetchone()[0], 'done')
        db.close()


if __name__ == '__main__':
    unittest.main()
