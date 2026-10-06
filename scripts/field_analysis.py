#!/usr/bin/env python3
"""Analyse field recordings (audio recorded away from the station).

    field_analysis.py run
        Analyse every queued recording. avian/api/field.php starts this in
        the background after an upload; only one copy works at a time.
    field_analysis.py add FILE --lat 48.85 --lon 2.35 [--date 2026-10-06T07:30:00] [--place "Bois"]
        Add a file from the command line and analyse it now. Without --date
        the recording time is read from the file's metadata.
    field_analysis.py list
        Show the recordings and what was found in each.

Data lives in <RECS_DIR>/Field (field.db + audio/), never in birds.db.
"""
import argparse
import fcntl
import logging
import os
import shutil
import sys

from utils.field import TIME_FORMAT, connect, field_dir, now_local, process_queue
from utils.helpers import get_settings

AUDIO_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac', '.webm', '.3gp', '.amr'}


def paths(conf, override=None):
    # The web server (field.php) and the owner's shell both write here.
    os.umask(0o002)
    base = override or field_dir(conf)
    audio = os.path.join(base, 'audio')
    os.makedirs(audio, exist_ok=True)
    return os.path.join(base, 'field.db'), audio, os.path.join(base, '.worker.lock')


def queued_count(db_path):
    db = connect(db_path)
    try:
        return db.execute("SELECT COUNT(*) FROM recordings WHERE status = 'queued'").fetchone()[0]
    finally:
        db.close()


def run(conf, base=None):
    db_path, audio, lock_path = paths(conf, base)
    total = 0
    while True:
        with open(lock_path, 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                logging.info('another field analysis is running; it will pick this up')
                return total
            # Holding the lock, any "analyzing" row is left over from a worker
            # that died mid-run: give it another go.
            db = connect(db_path)
            db.execute("UPDATE recordings SET status = 'queued' WHERE status = 'analyzing'")
            db.commit()
            db.close()
            total += process_queue(db_path, audio, conf)
        # A recording queued just as the lock was released would otherwise
        # wait for the next upload: look once more before exiting.
        if not queued_count(db_path):
            return total


def add(conf, args):
    if not -90 <= args.lat <= 90 or not -180 <= args.lon <= 180:
        sys.exit('latitude must be in [-90, 90] and longitude in [-180, 180]')
    ext = os.path.splitext(args.file)[1].lower()
    if ext not in AUDIO_EXTENSIONS:
        sys.exit(f'unsupported audio type {ext!r}; use one of {", ".join(sorted(AUDIO_EXTENSIONS))}')
    if args.date:
        try:
            from datetime import datetime
            datetime.strptime(args.date, TIME_FORMAT)
        except ValueError:
            sys.exit('--date must look like 2026-10-06T07:30:00')
    db_path, audio, _ = paths(conf, args.field_dir)
    db = connect(db_path)
    with db:
        cur = db.execute(
            "INSERT INTO recordings (original_name, stored_name, size_bytes, recorded_at, lat, lon, place, "
            "status, created_at) VALUES (?, '', ?, ?, ?, ?, ?, 'uploading', ?)",
            (os.path.basename(args.file), os.path.getsize(args.file), args.date, args.lat, args.lon,
             (args.place or '')[:120], now_local()))
        rec_id = cur.lastrowid
    stored = f'{rec_id}{ext}'
    shutil.copyfile(args.file, os.path.join(audio, stored))
    with db:
        db.execute("UPDATE recordings SET stored_name = ?, status = 'queued' WHERE id = ?", (stored, rec_id))
    db.close()
    print(f'added recording {rec_id}; analysing...')
    run(conf, args.field_dir)
    show(conf, args.field_dir, only=rec_id)


def show(conf, base=None, only=None):
    db_path, _, _ = paths(conf, base)
    db = connect(db_path)
    query = 'SELECT * FROM recordings' + (' WHERE id = ?' if only else '') + ' ORDER BY id'
    for rec in db.execute(query, (only,) if only else ()):
        where = rec['place'] or f"{rec['lat']:.4f}, {rec['lon']:.4f}"
        print(f"#{rec['id']} {rec['recorded_at'] or '?'}  {where}  [{rec['status']}]  {rec['original_name']}")
        if rec['error']:
            print(f"    error: {rec['error']}")
        species = db.execute(
            'SELECT sci_name, com_name, MAX(confidence) AS best, COUNT(*) AS n FROM detections '
            'WHERE recording_id = ? GROUP BY sci_name ORDER BY best DESC', (rec['id'],)).fetchall()
        for s in species:
            print(f"    {s['com_name']} ({s['sci_name']})  best {s['best']:.2f}, {s['n']} detection(s)")
    db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--field-dir', help='override <RECS_DIR>/Field (tests)')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('run')
    a = sub.add_parser('add')
    a.add_argument('file')
    a.add_argument('--lat', type=float, required=True)
    a.add_argument('--lon', type=float, required=True)
    a.add_argument('--date', help='local time, YYYY-MM-DDTHH:MM:SS (default: read from the file)')
    a.add_argument('--place', help='a name for the place')
    sub.add_parser('list')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    conf = get_settings()
    if args.cmd == 'add':
        add(conf, args)
    elif args.cmd == 'list':
        show(conf, args.field_dir)
    else:
        n = run(conf, args.field_dir)
        logging.info('field analysis: %d recording(s) analysed', n)


if __name__ == '__main__':
    main()
