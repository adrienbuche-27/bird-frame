-- Field recordings: audio recorded elsewhere (a phone, a walk) and uploaded
-- to the station for analysis. Kept apart from birds.db so the collage,
-- statistics and frame only ever reflect the station's own microphone.
-- Read by both avian/api/field.php and scripts/utils/field.py.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS recordings (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  original_name TEXT    NOT NULL,
  stored_name   TEXT    NOT NULL,
  size_bytes    INTEGER NOT NULL,
  -- Local time of the recording, "YYYY-MM-DDTHH:MM:SS". NULL until known:
  -- the worker then reads it from the file's metadata.
  recorded_at   TEXT,
  lat           REAL    NOT NULL,
  lon           REAL    NOT NULL,
  place         TEXT    NOT NULL DEFAULT '',
  -- uploading -> queued -> analyzing -> done | error
  status        TEXT    NOT NULL DEFAULT 'uploading',
  error         TEXT,
  duration_s    REAL,
  created_at    TEXT    NOT NULL,
  analyzed_at   TEXT
);

CREATE TABLE IF NOT EXISTS detections (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  sci_name      TEXT    NOT NULL,
  com_name      TEXT    NOT NULL,
  confidence    REAL    NOT NULL,
  start_s       REAL    NOT NULL,
  end_s         REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS detections_recording ON detections(recording_id);
CREATE INDEX IF NOT EXISTS detections_species ON detections(sci_name);
