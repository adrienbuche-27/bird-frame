"""Field recordings: analyse audio recorded away from the station.

A field recording is a file uploaded through avian/api/field.php (or added
with scripts/field_analysis.py). It is analysed with the same BirdNET model
as the station, but with the latitude, longitude and week of the place and
day it was recorded, so the range model admits the right species. Results
live in their own database (field.db) and never reach birds.db.

Filters, compared with the station's run_analysis():
- CONFIDENCE and the privacy (human) filter come from the station settings;
- the exclude list still applies (it usually holds known false positives);
- the include list does not: it describes the station's area, not the walk.
"""
import datetime
import json
import logging
import os
import sqlite3
import subprocess
import tempfile

from .analysis import analyzeAudioData, load_global_model, loadCustomSpeciesList, readAudioData
from .classes import birdnet_week
from .helpers import BASE_PATH, get_language

log = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(BASE_PATH, 'scripts', 'field_schema.sql')
TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


def field_dir(conf):
    """Where field.db and the uploaded audio live: <RECS_DIR>/Field.

    RECS_DIR is written as "$HOME/BirdSongs". $HOME is the station user's
    home, i.e. the checkout's parent, not the home of whoever runs this:
    field.php starts the worker as the web server's user.
    """
    home = os.path.dirname(BASE_PATH)
    recs = conf.get('RECS_DIR') or '$HOME/BirdSongs'
    return os.path.join(recs.replace('${HOME}', home).replace('$HOME', home), 'Field')


def share_with_group(path):
    """Give the group write access to a file this user owns.

    SQLite creates databases as 0644 whatever the umask, but the owner's
    shell and the web server (field.php, in the owner's group) both write
    field.db. Its -wal and -shm files copy the database's mode.
    """
    try:
        st = os.stat(path)
        if st.st_uid == os.getuid() and st.st_mode & 0o060 != 0o060:
            os.chmod(path, st.st_mode | 0o060)
    except OSError:
        pass


def connect(db_path):
    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    with open(SCHEMA_PATH) as f:
        db.executescript(f.read())
    share_with_group(db_path)
    return db


def now_local():
    return datetime.datetime.now().strftime(TIME_FORMAT)


def _ffprobe(path):
    out = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if out.returncode != 0:
        return {}
    try:
        return json.loads(out.stdout).get('format', {})
    except ValueError:
        return {}


def probe_recorded_at(path):
    """Recording time from the file's metadata, as local "YYYY-MM-DDTHH:MM:SS".

    Phones usually write an ISO creation_time in UTC (iPhone Voice Memos,
    most Android recorders). Returns None when the file carries no date.
    """
    tags = {k.lower(): v for k, v in (_ffprobe(path).get('tags') or {}).items()}
    for key in ('creation_time', 'date', 'com.apple.quicktime.creationdate'):
        value = tags.get(key)
        if not value:
            continue
        try:
            when = datetime.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            continue
        if when.tzinfo is not None:
            when = when.astimezone().replace(tzinfo=None)
        if when.year < 2000:  # an unset clock, not a real date
            continue
        return when.strftime(TIME_FORMAT)
    return None


def probe_duration(path):
    try:
        return float(_ffprobe(path).get('duration'))
    except (TypeError, ValueError):
        return None


def to_wav(src, dst, sample_rate):
    """Decode any phone format (m4a, mp3, opus, ...) to mono PCM WAV."""
    out = subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
         '-i', src, '-vn', '-ac', '1', '-ar', str(sample_rate), '-acodec', 'pcm_s16le', dst],
        capture_output=True, text=True, check=False, timeout=1800,
    )
    if out.returncode != 0:
        raise RuntimeError('could not decode audio: ' + (out.stderr.strip().splitlines() or ['ffmpeg failed'])[-1])


def analyze_file(path, lat, lon, when, conf):
    """Run BirdNET on one file for a given place and time.

    Returns a list of dicts: sci_name, com_name, confidence, start_s, end_s.
    """
    model = load_global_model()
    names = get_language(conf['DATABASE_LANG'])
    exclude = loadCustomSpeciesList(os.path.join(BASE_PATH, 'exclude_species_list.txt'))
    whitelist = loadCustomSpeciesList(os.path.join(BASE_PATH, 'whitelist_species_list.txt'))
    overlap = conf.getfloat('OVERLAP')
    min_conf = conf.getfloat('CONFIDENCE')

    with tempfile.TemporaryDirectory(prefix='field-') as tmp:
        wav = os.path.join(tmp, 'audio.wav')
        to_wav(path, wav, model.sample_rate)
        chunks = readAudioData(wav, overlap, model.sample_rate, model.chunk_duration)
    raw, predicted = analyzeAudioData(chunks, overlap, lat, lon, birdnet_week(when))

    found = []
    for time_slot, entries in raw.items():
        start, end = (float(t) for t in time_slot.split(';'))
        for sci_name, confidence in entries:
            if confidence < min_conf or sci_name == 'Human_Human':
                continue
            if sci_name in exclude:
                continue
            if predicted and sci_name not in predicted and sci_name not in whitelist:
                continue
            found.append({
                'sci_name': sci_name,
                'com_name': names.get(sci_name, sci_name),
                'confidence': round(float(confidence), 4),
                'start_s': start,
                'end_s': end,
            })
    return found


def process_recording(db, rec_id, audio_dir, conf):
    """Analyse one queued recording and store its detections."""
    row = db.execute('SELECT * FROM recordings WHERE id = ?', (rec_id,)).fetchone()
    if row is None:
        return
    db.execute("UPDATE recordings SET status = 'analyzing', error = NULL WHERE id = ?", (rec_id,))
    db.commit()
    path = os.path.join(audio_dir, row['stored_name'])
    try:
        recorded_at = row['recorded_at'] or probe_recorded_at(path) or row['created_at']
        when = datetime.datetime.strptime(recorded_at, TIME_FORMAT)
        found = analyze_file(path, row['lat'], row['lon'], when, conf)
        duration = probe_duration(path)
    except Exception as e:  # recorded on the row; the UI shows it
        log.exception('field recording %s failed', rec_id)
        db.execute("UPDATE recordings SET status = 'error', error = ?, analyzed_at = ? WHERE id = ?",
                   (str(e)[:500] or e.__class__.__name__, now_local(), rec_id))
        db.commit()
        return
    with db:
        db.execute('DELETE FROM detections WHERE recording_id = ?', (rec_id,))
        db.executemany(
            'INSERT INTO detections (recording_id, sci_name, com_name, confidence, start_s, end_s) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            [(rec_id, d['sci_name'], d['com_name'], d['confidence'], d['start_s'], d['end_s']) for d in found])
        db.execute("UPDATE recordings SET status = 'done', error = NULL, recorded_at = ?, "
                   "duration_s = ?, analyzed_at = ? WHERE id = ?",
                   (recorded_at, duration, now_local(), rec_id))
    log.info('field recording %s: %d detection(s)', rec_id, len(found))


def process_queue(db_path, audio_dir, conf):
    """Analyse every queued recording, oldest first. Returns how many ran."""
    db = connect(db_path)
    done = 0
    try:
        while True:
            row = db.execute("SELECT id FROM recordings WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return done
            process_recording(db, row['id'], audio_dir, conf)
            done += 1
    finally:
        db.close()
