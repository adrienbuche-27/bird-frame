# Field recordings

Analyse audio recorded away from the station, for example on a phone during a
walk, and keep a record of which birds were heard where.

Each recording is analysed with the same BirdNET model as the station, but
with the **place and date of the recording**. The range model uses them to
decide which species are plausible, so a recording made 500 km away is judged
against that area's birds, not the garden's.

Field recordings are kept apart from the station:

- they are stored in `<RECS_DIR>/Field` (`~/BirdSongs/Field`): a database,
  `field.db`, and the audio files in `audio/`;
- they never enter `birds.db`, so the collage, the statistics and the e-ink
  frame only ever show what the station's own microphone heard.

> **Status.** Parts A (storage, upload API, analysis) and B (the map page)
> are done. Field-recording stamps in the Atlas (part C) come next.

---

## One-time setup on the station

Run these over SSH on the station, from `~/BirdNET-Pi`.

```bash
cd ~/BirdNET-Pi && git pull

# 1. The folder for field recordings. Group-writable with setgid, so both
#    you (command line) and the web server (uploads) can write in it.
install -d -m 2775 ~/BirdSongs/Field
id caddy          # must list your user's group; the BirdNET-Pi installer adds it

# 2. Publish the new API in Caddy (it only serves the API files it lists).
sudo install -o root -g root -m 0755 scripts/update_caddyfile.sh /usr/local/sbin/avian-caddy-refresh
sudo /usr/local/sbin/avian-caddy-refresh
```

**Tools → Pull latest** does not work on this fork (see
[custom illustrations](custom-illustrations.md#notes)), which is why the Caddy
helper is installed by hand.

---

## The map page

Open the menu, then **map** (it is an admin page, at `/#admin=field`).

- **The map** shows one dot per recording; a red dot is one whose analysis
  failed. Click a dot, or a recording in the list, to open it.
- **Add a recording**: choose the audio file, click the map where it was
  recorded (an orange ring marks the spot), optionally name the place and
  set the date, then **upload and analyse**. The file is sent in pieces with
  a progress percentage; the analysis then runs in the background and the
  page refreshes by itself until it is done.
- **Leave the date empty** to read it from the file. Correct it afterwards
  if needed.
- **A recording** shows its place, date, position and length, an audio
  player, and the birds found with their illustration, best confidence and
  number of detections. Under **correct place or date** you can rename it,
  change its date, or **move it on the map** (click the button, then the new
  spot). Changing the date or position analyses it again. **Analyse again**
  and **delete** are below.

**Use my position** needs a secure page. Browsers only share the location
with `https://` sites (or `localhost`), and the station is usually opened as
`http://<address>` on the home network, so the button is greyed out there:
click the map instead. Behind an HTTPS setup (see
[`avian/forwarding/`](../avian/forwarding/)) it works.

The map library (Leaflet, pinned and checked with a hash) and the map tiles
come from the internet (unpkg.com and openstreetmap.org), and only when this
page is open. Without internet the page says so; uploads still work.

---

## Add a recording from the command line

```bash
cd ~/BirdNET-Pi
birdnet/bin/python3 scripts/field_analysis.py add ~/walk.m4a \
    --lat 48.8448 --lon 2.4395 --place "Bois de Vincennes"
```

- `--lat` / `--lon`: where it was recorded, in decimal degrees. Copy them from
  any map app (long-press the spot).
- `--date 2026-10-06T07:30:00`: when it was recorded, local time. Optional:
  without it the date is read from the file (most phones store it). If the file
  has no date, the upload time is used.
- `--place`: an optional name for the spot.

The file is copied into `~/BirdSongs/Field/audio/`, analysed, and the result
printed:

```
#3 2026-10-06T07:31:12  Bois de Vincennes  [done]  walk.m4a
    Eurasian Magpie (Pica pica)  best 0.93, 4 detection(s)
    European Robin (Erithacus rubecula)  best 0.78, 1 detection(s)
```

`birdnet/bin/python3 scripts/field_analysis.py list` shows every recording.

Accepted formats: `wav`, `mp3`, `m4a`, `aac`, `ogg`, `oga`, `opus`, `flac`,
`webm`, `3gp`, `amr` (decoded with ffmpeg), up to 200 MB per file.
Long recordings take a while to analyse on a Pi; `add` waits for the result,
while uploads through the API are analysed in the background.

### What filters apply

| Station setting | Applies to field recordings? |
|---|---|
| Minimum confidence (`CONFIDENCE`) | yes |
| Privacy filter (human voices) | yes |
| Species occurrence (range model) | yes, with the recording's place and week |
| Exclude list | yes (it usually holds known false positives) |
| Include list | **no**: it describes the station's area, not the walk |

---

## The upload API

`avian/api/field.php`, used by the map page. Every action requires the
station admin, since recordings reveal where you have been. POST actions take
a JSON body and need the `X-Avian-Action: 1` header, like the other admin APIs.

| Action | Does |
|---|---|
| `GET ?action=list` | every recording, newest first, with its species and detections |
| `GET ?action=audio&id=N` | the audio file (supports seeking) |
| `POST ?action=begin` `{name, size, lat, lon, recorded_at?, place?}` | starts an upload, returns `id` and `chunk_bytes` |
| `POST ?action=chunk` `{id, offset, data}` | appends one base64 chunk (at most `chunk_bytes` once decoded) |
| `POST ?action=finish` `{id}` | checks the size and queues the analysis |
| `POST ?action=update` `{id, lat?, lon?, recorded_at?, place?}` | corrects a recording; changing place or time re-analyses it |
| `POST ?action=reanalyze` `{id}` | analyses it again (after changing settings, say) |
| `POST ?action=delete` `{id}` | removes the recording, its audio and its detections |

Files travel in base64 chunks inside JSON, so uploads keep the shared JSON
action guard and fit PHP's default 8 MB request limit. Uploads abandoned for a
day are cleaned up automatically. The analysis runs in the background
(`scripts/field_analysis.py run`, one at a time); its log is
`~/BirdSongs/Field/worker.log`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| API answers `field recordings folder ... is not writable` | Re-run step 1 of the setup; check `ls -ld ~/BirdSongs/Field` shows `drwxrwsr-x`. |
| API answers 404 | Step 2 of the setup was not run, or failed. |
| A recording stays `queued` | Look at `~/BirdSongs/Field/worker.log`, then run `birdnet/bin/python3 scripts/field_analysis.py run`. |
| Status `error: could not decode audio` | The file is damaged or not audio; try exporting it again from the phone. |
| Fewer birds than expected | Check the place and date: they decide which species are allowed. Fix them with the `update` action (or re-add the file with `--date`). |
