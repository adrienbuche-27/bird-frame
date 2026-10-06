# AvianVisitors e-ink frame: handoff notes

Context for continuing work on this repo. It summarises a setup and debugging session done before the repo was forked: what the project is, how the frame is configured, what was changed in the code, and what is still rough.

## Project

- **What it is:** an e-ink picture frame that shows a collage of the birds detected by a BirdNET-Pi station. A Raspberry Pi screenshots the BirdNET-Pi collage page, lays it out, and pushes it to the panel.
- **Origin:** fork of `Twarner491/AvianVisitors`, default branch `avian-visitors`. The work was based on upstream commit `543c447` (2026-10-03). `theskyisthelimit/AvianVisitors` is an older copy, 111 commits behind; do not use it as a reference.
- **Licence:** Creative Commons BY-NC-SA 4.0, inherited from BirdNET-Pi. Keep `LICENSE` and the upstream credits; no commercial use.
- **Repo size:** about 900 MB with history. Almost all of it is the bird illustrations under `avian/` (921 PNG files) and the BirdNET models under `model/`. The frame code is small and lives in `frame/`. Avoid scanning `avian/` and `model/` unless a task needs them.

## Hardware (differs from upstream)

- Upstream targets the **Pimoroni Inky Impression 13.3"** (1600x1200, driven by the `inky` library).
- This frame uses a **Waveshare 7.3" e-Paper HAT** (800x480). Exact variant, (E), (F) or (G), is whatever `panel` is set to in the live config; confirm with the owner.
- The Pi user is `abuche`. The BirdNET-Pi is a separate device on the LAN, reached by IP address.

## How the frame side works

All paths below are relative to `frame/`.

- `install.sh` enables SPI and I2C, creates `.venv`, installs Playwright and Chromium, writes `~/.birdframe/config.toml`, and installs the `birdframe` systemd service and timer. If the config file already exists it is left untouched, so edits to the config template inside `install.sh` have no effect on an existing install.
- `systemd/birdframe.timer` runs the service every 15 minutes (`OnUnitActiveSec=15min`).
- `display.py` is the entry point. Each run it:
  1. fetches the recent species list from `<base_url>/avian/api/birdnet-api.php?action=recent&hours=<hours>` and builds a signature;
  2. skips the refresh unless the signature changed, `heal_hours` (24) have passed, or `--force` is given;
  3. screenshots the collage with `shoot.py` (when `shoot = true`);
  4. lays the title and collage out on a fixed 1200x1600 portrait canvas (`mat_and_center`);
  5. pushes the result to the panel (`push_panel`).
- `config_contract.py` and `config.example.toml` document the config keys. `config.toml` and `.venv/` are gitignored.

## Live configuration

The config lives outside the repo at `~/.birdframe/config.toml`. Keys that matter for this install:

| Key | Value here | Notes |
|---|---|---|
| `base_url` | `http://<BirdNET-Pi IP>` | Must include `http://`; a bare IP fails with "unknown url type". |
| `shoot` | `true` | This Pi renders the collage itself (local mode). |
| `hours` | owner's choice, default 24 | Rolling window of detections shown, in whole hours. Not written by `install.sh` in local mode. |
| `shoot_subtitle` | default "Heard Today" | Label only; change it by hand to match `hours`. |
| `panel` | `waveshare_7in3e`, `_7in3f` or `_7in3g` | New values added in this session (see below). |
| `opening` | `0.98` | Makes the content fill the smaller bare panel; the default 0.7071 is for the upstream A5 mat. |
| `rotate` | 90 or 270 | Which way up the frame hangs. |
| `saturation` | default 0.6 | On Waveshare this is a colour boost before dithering (see below). |

## Changes made in the session

### 1. `frame/display.py` (modified)

Added a Waveshare path next to the existing Inky path. The Inky behaviour is unchanged.

- `ImageEnhance` added to the PIL import.
- `WAVESHARE`: maps the `panel` config values `waveshare_7in3e`, `waveshare_7in3f`, `waveshare_7in3g` to the Waveshare driver modules `epd7in3e`, `epd7in3f`, `epd7in3g`.
- `_fit_aspect(img, tw, th)`: fits the 4:3 canvas to a panel of another shape without stretching. It trims spare paper margin when the content fits inside the crop, otherwise pads with the paper colour, then resizes.
- `_prep_waveshare(img, saturation)`: lifts the cream paper colour to pure white so the background does not dither into speckles, then boosts colour by `1 + saturation`.
- `push_waveshare(img, rotate, saturation, panel)`: rotates, fits, prepares, then runs the driver sequence `init()`, `display(getbuffer(img))`, `sleep()`. The panel is always put to sleep, even on error.
- `push_panel(...)`: dispatches to `push_waveshare` when `panel` is one of the Waveshare values; otherwise the original Inky code runs.
- Comment on the `panel` entry in `DEFAULTS` updated to list the new values.

### 2. `frame/waveshare_epd/` (new folder)

Vendored from `waveshareteam/e-Paper`, path `RaspberryPi_JetsonNano/python/lib/waveshare_epd/`, branch `master`. Files: `__init__.py`, `epdconfig.py`, `epd7in3e.py`, `epd7in3f.py`, `epd7in3g.py`. It is imported as a plain package because it sits next to `display.py`.

### 3. Extra Python packages in `frame/.venv`

`gpiozero`, `lgpio`, `spidev`, needed by the Waveshare driver. They are not yet listed in `requirements-frame.txt`.

### 4. System change on the Pi (outside the repo)

`dtoverlay=spi0-0cs` was commented out in `/boot/firmware/config.txt`, followed by a reboot. `install.sh` adds that line for the Inky board, which is wired without a chip-select line. The Waveshare driver relies on the hardware chip-select (CE0, GPIO 8), so with the overlay active the panel receives nothing.

**Re-running `install.sh` adds the overlay back and breaks the Waveshare panel.**

## Verification status

- The frame refreshes correctly on the owner's Waveshare 7.3" panel after these changes.
- The image handling (`_fit_aspect`, `_prep_waveshare`, the dispatch) was also tested against a stand-in driver with synthetic images at `opening` 0.7071 and 0.98.
- Only the variant the owner has was tested on hardware; the other two variants are untested.
- No automated tests cover the new functions.

## Known gaps (candidate clean-ups)

- `install.sh` is not Waveshare-aware: it always adds `dtoverlay=spi0-0cs`, does not fetch `waveshare_epd` or install its packages, and does not write `panel`, `opening` or `hours` to the config.
- `requirements-frame.txt` does not include `gpiozero`, `lgpio`, `spidev`.
- `config.example.toml`, `config_contract.py` and `frame/README.md` do not mention the Waveshare `panel` values.
- The layout still happens on a hard-coded 1200x1600 canvas (`PANEL_W`, `PANEL_H`) and is adapted to 800x480 only at push time. Laying out directly at the panel's resolution would give sharper results and make `opening` behave more predictably.
- `--preview` still simulates the Spectra 6 palette of the Inky panel, not the Waveshare pipeline (white-point lift, colour boost, pure-ink dithering).
- The mapping of `saturation` to a colour boost on Waveshare is a first guess and has not been tuned.

## Useful commands (run on the frame Pi, from `frame/`)

```bash
# Force a refresh and see the result on stdout
.venv/bin/python display.py --config ~/.birdframe/config.toml --force

# What the timer runs have been doing
journalctl -u birdframe.service -n 30 --no-pager

# After editing the timer interval in /etc/systemd/system/birdframe.timer
sudo systemctl daemon-reload && sudo systemctl restart birdframe.timer
```

Messages printed by `display.py`:

- `panel updated`: success.
- `signature fetch failed: ...` or `could not get image: ...`: the BirdNET-Pi is unreachable or `base_url` is wrong.
- `panel push failed: ...`: display side (driver, SPI, wiring). "No EEPROM detected" means the Inky auto-detect ran, so `panel` is not set to a Waveshare value.
- `another render is in progress; skipping`: the timer is running at the same moment.

## Git setup

```bash
git remote -v   # origin = personal public fork, upstream = Twarner491/AvianVisitors
git fetch upstream && git merge upstream/avian-visitors   # pull upstream updates
```

Upstream changes to `frame/display.py` or `frame/install.sh` may conflict with the Waveshare work above. The repo is public, so keep `~/.birdframe/config.toml` (LAN address, any credentials) out of it.
