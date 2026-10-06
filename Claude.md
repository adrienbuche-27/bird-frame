# AvianVisitors e-ink frame: handoff notes

Context for continuing work on this repo: what the project is, how the owner's station and frame are set up, what this fork changes compared with upstream, and what is still rough. Last updated 2026-10-06.

## Project

- **What it is:** a BirdNET-Pi station with the AvianVisitors overlay, which draws a collage of illustrated birds from what the microphone detects, plus an e-ink picture frame that shows that collage. The frame Pi screenshots the collage page, lays it out, and pushes it to the panel.
- **Origin:** fork of `Twarner491/AvianVisitors` (default branch `avian-visitors`), started from upstream commit `543c447` (2026-10-03). This fork's default branch is `main`. `theskyisthelimit/AvianVisitors` is an older copy, 111 commits behind; do not use it as a reference.
- **Licence:** Creative Commons BY-NC-SA 4.0, inherited from BirdNET-Pi. Keep `LICENSE` and the upstream credits; no commercial use.
- **Repo size:** about 900 MB with history, almost all of it illustrations under `avian/` and BirdNET models under `model/`. The frame code is small and lives in `frame/`. Avoid scanning `avian/` and `model/` unless a task needs them.

## Owner's setup

- **One Pi does both jobs:** `traffic-pi`, user `abuche`. It runs the BirdNET-Pi station and the frame service. The checkout is `~/BirdNET-Pi` (the name BirdNET-Pi uses; it is this repo).
- **Remotes on the Pi:** `origin` = `adrienbuche-27/bird-frame` (this fork), `upstream` = `Twarner491/AvianVisitors`. The fetch refspec was fixed to `+refs/heads/*:refs/remotes/origin/*` and `main` tracks `origin/main`, so a plain `git pull` works.
- **Panel:** Waveshare 7.3" e-Paper HAT (800x480), not upstream's Pimoroni Inky Impression 13.3" (1600x1200). The exact variant, (E), (F) or (G), is whatever `panel` is set to in the live config; confirm with the owner. Only that variant has been tested on hardware.
- **Boot config:** `dtoverlay=spi0-0cs` is commented out in `/boot/firmware/config.txt`. That overlay is for the Inky, which has no chip-select line; the Waveshare driver needs the hardware chip-select (CE0, GPIO 8).
- **Illustrations:** the owner is in Europe. About 80 European species (perched and flight poses, about 160 images) were added on top of the bundled North American set. New species are generated one at a time with the Atlas **generate** button, by choice: bulk generation through `pregen.py` cost too much on Gemini. Do not propose automatic generation without asking.

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
| `panel` | `waveshare_7in3e`, `_7in3f` or `_7in3g` | Without it, the Inky auto-detect runs and fails. |
| `opening` | `0.98` | Fills the bare panel; the default 0.7071 is for upstream's A5 mat. |
| `rotate` | 90 or 270 | Which way up the frame hangs. |
| `saturation` | default 0.6 | On Waveshare this is a colour boost before dithering. |
| `schedule` | `"sun"` if the owner enabled it | Overrides `hours` and `shoot_subtitle`. |

## Fork changes (all merged into `main`)

| PR | Change |
|---|---|
| #1 | Waveshare support: `frame/display.py` Waveshare path; `frame/waveshare_epd/` vendored from `waveshareteam/e-Paper`, `RaspberryPi_JetsonNano/python/lib/waveshare_epd/` at commit `a794fbc` (`__init__.py`, `epdconfig.py`, `epd7in3e.py`, `epd7in3f.py`, `epd7in3g.py`). |
| #2 | European illustrations (`avian/assets/illustrations/*.png`), `cuts.json`, and rebuilt `avian/frontend/masks.json` / `dims.json`. Two more species were later pushed straight to `main`. |
| #3 | `docs/custom-illustrations.md`; `.gitignore` for station work files (`.generate.*`, `raw/`, `.upgrade-stage/`, `model/labels_flickr.txt`). |
| #4 | Sun schedule: `frame/suntimes.py`, `display.py` (`apply_sun_schedule`, `scheduled`, `skip_reason`), `tests/test_frame_schedule.py`. |
| #5 | `install.sh --panel`, `frame/requirements-waveshare.txt`, installer tests; step 5 of the illustrations guide (`upgrade_cutouts.py`). |

## Illustrations workflow

Full guide: [`docs/custom-illustrations.md`](docs/custom-illustrations.md).

- The collage only draws a species listed in `avian/frontend/masks.json` and `dims.json`. A PNG without a mask entry is skipped silently. This is how the European birds once disappeared: a Git operation reset `masks.json` while the PNGs were still untracked.
- Commit the PNGs, `cuts.json`, `masks.json` and `dims.json` together. Never commit `.generate.*` or `raw/` (both ignored).
- Birds made with the website button get a quick chroma cutout and are listed as `"chroma"` in `cuts.json`. `avian/scripts/upgrade_cutouts.py --pi abuche@<address>`, run from a computer, re-cuts them with BiRefNet using `raw/` on the Pi. `raw/` exists only on the Pi; do not delete it while `cuts.json` lists birds.

## Known gaps

- **Re-running `install.sh` without `--panel`** adds `dtoverlay=spi0-0cs` back and breaks the Waveshare panel. Always pass `--panel`.
- **`install.sh --panel` has not run on a Pi yet**, in particular installing `lgpio` from pip on Raspberry Pi OS.
- **Tools → Pull latest** (`scripts/update_birdnet.sh`) refuses to run, because it only accepts upstream as `origin`. Update with `git pull`. Merging upstream changes is manual (`git fetch upstream && git merge upstream/avian-visitors`), and changes to `frame/display.py` or `frame/install.sh` may conflict.
- **CI is red on `main`, all inherited from upstream:** flake8 reports 425 findings (including the vendored `waveshare_epd/` and `shoot.py`), and `tests/test_frame_capture_browser.py::test_graphics_budget_keeps_all_source_art` fails on upstream `543c447` too. `tests/test_frame_capture.py::test_response_limits_reject_before_retaining_oversized_art` also fails locally on `main`.
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
