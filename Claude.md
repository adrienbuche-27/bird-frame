# AvianVisitors e-ink frame: handoff notes

Context for continuing work on this repo: what the project is, how the owner's station and frame are set up, what this fork changes compared with upstream, and what is still rough. Last updated 2026-10-07, after PR #10.

## Project

- **What it is:** a BirdNET-Pi station with the AvianVisitors overlay, which draws a collage of illustrated birds from what the microphone detects, plus an e-ink picture frame that shows that collage. The frame Pi screenshots the collage page, lays it out, and pushes it to the panel.
- **Origin:** fork of `Twarner491/AvianVisitors` (default branch `avian-visitors`), started from upstream commit `543c447` (2026-10-03). This fork's default branch is `main`. `theskyisthelimit/AvianVisitors` is an older copy, 111 commits behind; do not use it as a reference.
- **Licence:** Creative Commons BY-NC-SA 4.0, inherited from BirdNET-Pi. Keep `LICENSE` and the upstream credits; no commercial use.
- **Repo size:** about 900 MB with history, almost all of it illustrations under `avian/` and BirdNET models under `model/`. The frame code is small and lives in `frame/`. Avoid scanning `avian/` and `model/` unless a task needs them.

## Owner's setup

- **One Pi does both jobs:** `traffic-pi`, user `abuche`. It runs the BirdNET-Pi station and the frame service. The checkout is `~/BirdNET-Pi` (the name BirdNET-Pi uses; it is this repo).
- **Remotes on the Pi:** `origin` = `adrienbuche-27/bird-frame` (this fork), `upstream` = `Twarner491/AvianVisitors`. The fetch refspec was fixed to `+refs/heads/*:refs/remotes/origin/*` and `main` tracks `origin/main`, so a plain `git pull` works.
- **Panel:** Waveshare 7.3" e-Paper HAT (800x480), not upstream's Pimoroni Inky Impression 13.3" (1600x1200). The variant is **(E)**, the 6-colour Spectra 6 panel, so the live config has `panel = "waveshare_7in3e"` and the driver module is `waveshare_epd/epd7in3e.py`. Only (E) has been tested on hardware; the (F) and (G) paths are untested.
- **Boot config:** `dtoverlay=spi0-0cs` is commented out in `/boot/firmware/config.txt`. That overlay is for the Inky, which has no chip-select line; the Waveshare driver needs the hardware chip-select (CE0, GPIO 8).
- **Illustrations:** the owner is in Europe. About 80 European species (perched and flight poses, about 160 images) were added on top of the bundled North American set. New species are generated one at a time with the Atlas **generate** button, by choice: bulk generation through `pregen.py` cost too much on Gemini. Do not propose automatic generation without asking.
- **Working style:** the owner writes in French and wants a design agreed before any code. Larger features are split into parts (A, B, C…), each validated, then tested on a branch on the Pi before merging to `main`.

## How the frame works

All paths are relative to `frame/`.

- `systemd/birdframe.timer` runs `birdframe.service` every 15 minutes. The service runs `display.py --config ~/.birdframe/config.toml`.
- `display.py`, each run:
  1. applies the sun schedule when `schedule = "sun"` (see below);
  2. fetches the species list from `<base_url>/avian/api/birdnet-api.php?action=recent&hours=<hours>` and builds a signature (with the day/night phase in it);
  3. skips the refresh unless the signature changed, `heal_hours` (24) have passed, or `--force` is given. With the schedule on, an empty window also skips, keeping the current image;
  4. screenshots the collage with `shoot.py` (when `shoot = true`);
  5. lays the title and collage out on a fixed 1200x1600 portrait canvas (`mat_and_center`);
  6. pushes the result to the panel (`push_panel`, which dispatches to `push_waveshare` for the Waveshare values).
- **Waveshare path:** `WAVESHARE` maps `waveshare_7in3e`/`f`/`g` to the vendored driver modules in `waveshare_epd/`. `push_waveshare` rotates, fits the canvas to 800x480 without stretching (`_fit_aspect`), lifts the cream paper to white and boosts colour by `1 + saturation` (`_prep_waveshare`), then runs `init()`, `display(getbuffer(img))`, `sleep()`. The panel is always put to sleep, even on error.
- **Sun schedule** (`schedule = "sun"`): from sunrise to sunset, shows the last `day_hours` (default 1) with `day_subtitle` ("Dernière heure"). After sunset, shows every bird since that morning's sunrise, until the next sunrise, with `night_subtitle` ("Aujourd'hui"). Sun times come from `suntimes.py` (standard-library NOAA formula) at `LATITUDE`/`LONGITUDE` from `/etc/birdnet/birdnet.conf`, or `latitude`/`longitude` in the frame config. Only applies to local capture; ignored for BirdWeather and `image_url`.
- `install.sh --panel waveshare_7in3e|f|g` sets up a Waveshare frame: SPI only, no `spi0-0cs` (comments it out and reboots if found), installs `requirements-waveshare.txt` (`gpiozero`, `lgpio`, `spidev`), and writes `panel`, `opening = 0.98` and (local mode) `schedule = "sun"` to a new config. An existing config is never modified.
- `config.example.toml` is the full reference for config keys. `config_contract.py` only checks that an existing config selects the requested source. `config.toml` and `.venv/` are gitignored.

## Live configuration

The config lives outside the repo at `~/.birdframe/config.toml`. Keys that matter for this install:

| Key | Value here | Notes |
|---|---|---|
| `base_url` | `http://<station address>` | Must include `http://`; a bare IP fails with "unknown url type". |
| `shoot` | `true` | The Pi renders the collage itself (local mode). |
| `panel` | `waveshare_7in3e` | Variant (E). Without it, the Inky auto-detect runs and fails. |
| `opening` | `0.98` | Fills the bare panel; the default 0.7071 is for upstream's A5 mat. |
| `rotate` | 90 or 270 | Which way up the frame hangs. |
| `saturation` | default 0.6 | On Waveshare this is a colour boost before dithering. |
| `schedule` | `"sun"` if the owner enabled it | Overrides `hours` and `shoot_subtitle`. |

## Fork changes (all merged into `main`)

| PR | Change |
|---|---|
| #1 | Waveshare support: `frame/display.py` Waveshare path; `frame/waveshare_epd/` vendored from `waveshareteam/e-Paper`, `RaspberryPi_JetsonNano/python/lib/waveshare_epd/` at commit `a794fbc` (`__init__.py`, `epdconfig.py`, `epd7in3e.py`, `epd7in3f.py`, `epd7in3g.py`). |
| #2 | European illustrations (`avian/assets/illustrations/*.png`), `cuts.json`, and rebuilt `avian/frontend/masks.json` / `dims.json`. Three more species were later pushed straight to `main` (`chroicocephalus-ridibundus`, `corvus-corone`, `motacilla-alba`). |
| #3 | `docs/custom-illustrations.md`; `.gitignore` for station work files (`.generate.*`, `raw/`, `.upgrade-stage/`, `model/labels_flickr.txt`). |
| #4 | Sun schedule: `frame/suntimes.py`, `display.py` (`apply_sun_schedule`, `scheduled`, `skip_reason`), `tests/test_frame_schedule.py`. |
| #5 | `install.sh --panel`, `frame/requirements-waveshare.txt`, installer tests; step 5 of the illustrations guide (`upgrade_cutouts.py`). |
| #6 | This file rewritten for the state after #1–#5. |
| #7 | `avian/scripts/upgrade_cutouts.py` progress output: timestamped steps, a per-bird `[i/N]` counter with time left, a final summary, and `-v`/`--verbose` for sizes, timings and the remote command. The per-bird loop is `cut_all()`. Tests in `tests/test_upgrade_cutouts.py`. |
| #8 | 138 bulk European images (69 species from `pregen.py`) had never been cut out: opaque RGB with the cream ground, drawn as rectangles. All were cut with `cutout.py`; `anser-rossii` (perched) was redone with `upgrade_cutouts.birefnet_cut` because the matte erased its white body. Masks rebuilt; `TABLE_VERSION` r14, `SKETCH_VERSION`/`IMG_VERSION` r13 in `apt.js`. CI: `python-lint` now lints only the `.py` files a PR changes, and `frame/waveshare_epd/` is excluded in `.flake8`. |
| #9 | This file updated for #6–#8 and the panel variant (E). |
| #10 | Field recordings (see below): `scripts/utils/field.py`, `scripts/field_analysis.py`, `scripts/field_schema.sql`, `avian/api/field.php` (added to the Caddy list in `scripts/update_caddyfile.sh`), the **map** admin page and the Atlas **elsewhere** stamps in `apt.js`/`styles.css`/`index.html`, `generate.php` accepting field-only species, `docs/field-recordings.md`. Tests: `test_field_analysis.py`, `test_field_api.php`/`.py`, `test_field_map_browser.py`. The merge also brought 8 new species (corvus-monedula, parus-major, periparus-ater, picus-viridis from `main`; delichon-urbicum, dendrocopos-major, falco-tinnunculus, garrulus-glandarius from the branch), masks rebuilt, `TABLE_VERSION` r15, cache keys `styles.css?v=r198`, `apt.js?v=r239`. |

## Field recordings (PR #10)

Full guide: [`docs/field-recordings.md`](docs/field-recordings.md). Tested on `traffic-pi`: command line, API, map and Atlas stamps all work.

- **What:** audio recorded elsewhere (a phone on a walk) is uploaded, analysed with the station's BirdNET model using **the recording's place and week** for the range filter, shown on a map, and shown in the Atlas as "elsewhere" stamps. Admin-only everywhere, because recordings reveal where the owner has been.
- **Storage:** `~/BirdSongs/Field/` (`<RECS_DIR>/Field`): `field.db` (SQLite WAL, tables `recordings` and `detections`) and `audio/`. Never `birds.db`, so the collage, statistics and e-ink frame only show the station's own microphone. The folder is `2775` and `field.db` is chmodded group-writable (SQLite creates files 0644 whatever the umask), so both `abuche` and `caddy` can write.
- **Analysis:** `scripts/utils/field.py` decodes with ffmpeg and runs the model. `CONFIDENCE`, the privacy filter and the exclude list apply; the include list does not. Date: request, else file metadata (ffprobe `creation_time`), else upload time. Always run it with `birdnet/bin/python3` (the station venv); the system Python lacks the model packages, and installing tensorflow/tzlocal there is not needed.
- **Worker:** `field.php` spawns `field_analysis.py run` in the background (one at a time, `flock` on `.worker.lock`, log in `worker.log`). Over SSH: `birdnet/bin/python3 scripts/field_analysis.py add FILE --lat .. --lon .. [--date ..] [--place ..]` and `... list`.
- **API** (`avian/api/field.php`): `list`, `audio` (Range), `begin`/`chunk`/`finish` (base64 chunks of 2 MB inside JSON, to stay under PHP's 8 MB post limit and keep the JSON action guard), `update`, `reanalyze`, `delete`. Max 200 MB per file. `generate.php` loads it with `AVIAN_FIELD_LIBRARY_ONLY` to name species heard only in the field.
- **Map page** (menu → **map**, `/#admin=field`): Leaflet 1.9.4 from unpkg with SRI hashes, OpenStreetMap tiles. The site is `no-referrer`, but OSM blocks tiles without a Referer, so only the tile layer uses `referrerPolicy: 'strict-origin-when-cross-origin'`. "Use my position" is greyed out over plain `http://` (browsers only geolocate on secure pages).
- **Atlas:** a fifth sort button (map pin, `data-sort="elsewhere"`), visible only while admin is unlocked; no time window applies. The postcard lists each detection with place, date, confidence and an `<audio>` clip (`field.php?action=audio&id=N#t=start,end`). Locking admin hides the button, drops the data and closes an open elsewhere postcard.

## Illustrations workflow

Full guide: [`docs/custom-illustrations.md`](docs/custom-illustrations.md).

- The collage only draws a species listed in `avian/frontend/masks.json` and `dims.json`. A PNG without a mask entry is skipped silently. This is how the European birds once disappeared: a Git operation reset `masks.json` while the PNGs were still untracked.
- Commit the PNGs, `cuts.json`, `masks.json` and `dims.json` together. Never commit `.generate.*` or `raw/` (both ignored).
- **Birds without an illustration** are flagged in three places (all use "no `dims.json` entry", the collage's own rule): a line under the collage for the current window and a pencil "to illustrate" sort in the Atlas with a count badge (every bird heard, field recordings included), both admin-only; and on the frame a line under the subtitle (`missing_label`, default "+ {n} oiseaux non illustrés"), whose count is part of the frame signature so a generate refreshes the panel. The frame fetches `<base_url>/dims.json` for this; if that fails the line is just left out.
- Push new illustrations to one branch only. Pushing the same species with different images to `main` and to a feature branch blocks the merge (add/add conflicts on the PNGs, conflicts in `masks.json`/`dims.json`); this happened during #10. To resolve, pick one image per file, align `cuts.json` with it, regenerate the tables with `build_masks.py` (never hand-merge them) and bump `TABLE_VERSION`.
- After rebuilding the tables, bump `TABLE_VERSION` in `apt.js`; after editing `apt.js` or `styles.css`, bump their `?v=` keys in `index.html`. The `apt.js` key is pinned in `tests/smoke_admin_ui_polish.mjs`, `smoke_atlas_classic.mjs` and `smoke_educators_ui.mjs`; update all three with it.
- Every illustration must be an RGBA cutout. Art made in bulk with `pregen.py` must go through `cutout.py` before it is committed, otherwise it shows as an opaque rectangle (the #8 bug). Quick check: `python3 -c "from PIL import Image; print(Image.open('avian/assets/illustrations/<slug>.png').mode)"` must print `RGBA`. `cutout.py` loads BiRefNet (~9–14 GB of RAM per process), so run it one slug at a time; give it the `-2` slug first, because a perched slug also processes its flight pose. Check white or pale birds afterwards: the matte can erase a pale body.
- Birds made with the website button get a quick chroma cutout and are listed as `"chroma"` in `cuts.json`. `avian/scripts/upgrade_cutouts.py --pi abuche@<address>`, run from a computer, re-cuts them with BiRefNet using `raw/` on the Pi (add `-v` for per-step detail). `raw/` exists only on the Pi; do not delete it while `cuts.json` lists birds.

## Known gaps

- **Re-running `install.sh` without `--panel`** adds `dtoverlay=spi0-0cs` back and breaks the Waveshare panel. Always run `./install.sh --panel waveshare_7in3e` on this frame.
- **`install.sh --panel` has not run on a Pi yet**, in particular installing `lgpio` from pip on Raspberry Pi OS.
- **Tools → Pull latest** (`scripts/update_birdnet.sh`) refuses to run, because it only accepts upstream as `origin`. Update with `git pull`. Merging upstream changes is manual (`git fetch upstream && git merge upstream/avian-visitors`), and changes to `frame/display.py` or `frame/install.sh` may conflict.
- **Field recordings:** a new API file is only served once it is listed in `scripts/update_caddyfile.sh` and the helper is reinstalled and run (`sudo install -o root -g root -m 0755 scripts/update_caddyfile.sh /usr/local/sbin/avian-caddy-refresh && sudo /usr/local/sbin/avian-caddy-refresh`); otherwise Caddy answers 404. The map needs internet (unpkg, OSM). Test recordings must not be committed: the repo is public and audio reveals places (two `.m4a` files were committed by mistake and removed in #10; they remain in history).
- **CI:** green on `main` since #8. `python-lint` lints only the Python files a PR changes, so editing an old file can still surface its inherited findings (about 425 across the codebase, e.g. C901 in `frame/shoot.py`). To run the browser capture tests locally, Playwright needs a matching Chromium; in a Claude cloud session use `FRAME_TEST_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`. `test_generation_install_fixes.py` needs `USER` set in the environment. Without it the tests fail before running, which once looked like an upstream failure but was not.
- **Layout** still happens on the hard-coded 1200x1600 canvas (`PANEL_W`, `PANEL_H`) and is adapted to 800x480 only at push time. Laying out at the panel's resolution would be sharper and make `opening` more predictable.
- **`--preview`** still simulates the Inky's Spectra 6 palette, not the Waveshare pipeline (white-point lift, colour boost, pure-ink dithering).
- **`saturation`** as a colour boost on Waveshare is a first guess and has not been tuned.
- **Sun schedule:** the recent API takes whole hours, so the night window can start up to an hour before sunrise. If **Reset at midnight** is enabled on the station, the night view restarts at midnight.

## Useful commands (on `traffic-pi`, from `~/BirdNET-Pi`)

```bash
# Update the checkout
git pull

# Force a refresh and see the result on stdout
frame/.venv/bin/python frame/display.py --config ~/.birdframe/config.toml --force

# What the timer runs have been doing
journalctl -u birdframe.service -n 30 --no-pager

# After editing the timer interval in /etc/systemd/system/birdframe.timer
sudo systemctl daemon-reload && sudo systemctl restart birdframe.timer

# Rebuild the collage masks after adding illustrations
python3 avian/scripts/build_masks.py

# Field recordings: analyse a file, list everything, see the worker log
birdnet/bin/python3 scripts/field_analysis.py add ~/walk.m4a --lat 48.84 --lon 2.44 --place "Bois"
birdnet/bin/python3 scripts/field_analysis.py list
tail -n 30 ~/BirdSongs/Field/worker.log
```

Messages printed by `display.py`:

- `schedule: day, last 1h` / `schedule: night, last Nh`: the sun schedule picked the window.
- `panel updated`: success.
- `no change; skip`: the birds in the window have not changed.
- `no birds in the window; keeping the current image`: the schedule's window is empty.
- `signature fetch failed: ...` or `could not get image: ...`: the station is unreachable or `base_url` is wrong.
- `panel push failed: ...`: display side (driver, SPI, wiring). "No EEPROM detected" means the Inky auto-detect ran, so `panel` is not set to a Waveshare value. "Waveshare driver not installed" means `waveshare_epd/` or its packages are missing.
- `another render is in progress; skipping`: the timer is running at the same moment.

The repo is public, so keep `~/.birdframe/config.toml` (LAN address, any credentials) out of it.
