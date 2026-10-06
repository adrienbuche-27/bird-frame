# Adding your own illustrations

How to add illustrations for species the bundled set does not cover (for
example European birds), and keep them safe in this fork.

The collage only draws a species when **both** of these are true:

1. its cutout exists in `avian/assets/illustrations/<slug>.png` (and
   optionally `<slug>-2.png` for the flight pose);
2. its silhouette is listed in `avian/frontend/masks.json` and
   `avian/frontend/dims.json`.

A PNG without a mask entry is skipped silently: the bird is detected, but
it never appears on the collage or the frame. Every step below exists to
keep the PNGs and the two JSON tables in step, and both in Git.

All commands run on the station Pi, from `~/BirdNET-Pi`.

---

## 1. Generate the illustrations

Either way works; both write into `avian/assets/illustrations/`.

- **From the website.** In the Atlas, a species with no artwork shows a nest
  and a *generate* button. Needs a Gemini API key in **Settings**. This path
  also merges the new species into `masks.json` and `dims.json`.
- **In bulk, from SSH.** The full pipeline in
  [`avian/scripts/README.md`](../avian/scripts/README.md)
  (`pregen.py` → `cutout.py` → `build_masks.py`).

Slugs are the scientific name in lowercase with hyphens:
*Pica pica* → `pica-pica.png`, flight pose `pica-pica-2.png`.

## 2. Rebuild the masks

Always rebuild from the full illustration folder before committing, even if
the website already merged the new species. It also restores entries that a
Git operation may have reset.

```bash
python3 avian/scripts/build_masks.py --check   # report only: +new / -removed
python3 avian/scripts/build_masks.py           # rewrite masks.json + dims.json
```

If it reports a missing `PIL` or `numpy`, run it with
`frame/.venv/bin/python` instead of `python3`.

Check one species:

```bash
grep -c '"pica-pica"' avian/frontend/masks.json   # 1 = listed, 0 = will not be drawn
```

## 3. Commit and push

Only the finished files go into Git:

| Commit | Path |
|---|---|
| yes | `avian/assets/illustrations/*.png` |
| yes | `avian/assets/illustrations/cuts.json` |
| yes | `avian/frontend/masks.json`, `avian/frontend/dims.json` |
| no (ignored) | `avian/assets/illustrations/.generate.*` (logs, rate-limit state) |
| no (ignored) | `avian/assets/illustrations/raw/` (uncut renders, kept on the Pi) |
| no (ignored) | `model/labels_flickr.txt` (symlink made by the installer) |

```bash
git checkout -b illustrations-<topic>
git add avian/assets/illustrations/*.png \
        avian/assets/illustrations/cuts.json \
        avian/frontend/masks.json avian/frontend/dims.json
git status --short | grep -v '^??'   # only PNGs and the three JSON files
git commit -m "avian: add <topic> illustrations and rebuild masks"
git push -u origin illustrations-<topic>
```

Then open a pull request on GitHub and merge it into `main`.

Commit the PNGs and the masks **together**. Pushing PNGs without the
rebuilt masks gives a fork where the art exists but is never drawn.

## 4. Check the result

- Reload the collage with a hard refresh (Ctrl+F5); the browser may hold
  the previous `masks.json`.
- Force a frame refresh:

  ```bash
  frame/.venv/bin/python frame/display.py --config ~/.birdframe/config.toml --force
  ```

## 5. Upgrade the cutouts (optional, from a computer)

Birds generated with the website button get a quick chroma-key cutout,
because the precise matting model (BiRefNet, about 1 GB) does not fit in
the Pi's memory. Their edges can show a cream halo, or lose fine feathers
and thin legs. `avian/scripts/upgrade_cutouts.py` re-cuts them on a laptop
or desktop at full quality and puts them back on the Pi. It costs nothing on
the Gemini side; everything runs locally.

It only touches birds listed as `"chroma"` in
`avian/assets/illustrations/cuts.json`, and needs their uncut render in
`raw/` on the Pi. Art made in bulk with `pregen.py` + `cutout.py` is already
cut with BiRefNet and is left alone.

See what is waiting, on the Pi:

```bash
grep -c '"chroma"' ~/BirdNET-Pi/avian/assets/illustrations/cuts.json
```

### One-time setup on the computer

Needs Python 3.10 or newer, an SSH client (built into Windows 10+, macOS and
Linux), about 4 GB of free RAM and 2 GB of disk.

```bash
git clone https://github.com/adrienbuche-27/bird-frame.git
cd bird-frame
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install rembg onnxruntime scipy pillow numpy
```

On Windows, use `py` in place of `python3`.

### SSH key (strongly recommended)

The script opens one SSH connection per bird, then a few more to install the
results. Without a key it asks for the Pi password every time.

```bash
ssh-keygen -t ed25519                  # press Enter at each prompt if you have no key yet
ssh-copy-id <user>@<pi-address>
ssh <user>@<pi-address> true           # must return without asking for a password
```

Windows has no `ssh-copy-id`. Append the contents of
`%USERPROFILE%\.ssh\id_ed25519.pub` to `~/.ssh/authorized_keys` on the Pi.

### Run it

From the `bird-frame` folder on the computer, with the virtual environment
active:

```bash
python avian/scripts/upgrade_cutouts.py --pi <user>@<pi-address>
```

`<pi-address>` can be a hostname (`birdnet.local`) or an IP address. If the
checkout on the Pi is not `~/BirdNET-Pi`, add `--repo <folder>` (relative to
the Pi user's home).

What it does:

1. Reads `cuts.json` over SSH and lists the `"chroma"` birds.
2. Downloads the BiRefNet model on the first run (about 1 GB, into
   `~/.u2net/`).
3. For each bird, fetches `raw/<slug>.png`, mattes it with BiRefNet, removes
   cream pockets (between the legs, for example), fills the body, and crops
   with a small margin. Each one takes a few seconds to a minute.
4. Copies the new PNGs into `.upgrade-stage/` on the Pi and moves them into
   place. The staging step is needed because the website created the
   originals as another user.
5. Runs `build_masks.py --add` for those birds on the Pi, then removes them
   from `cuts.json`.

It ends with `done: N upgraded`. Hard-refresh the collage to see the new
edges.

### Commit the result

The PNGs, `cuts.json`, `masks.json` and `dims.json` are tracked, so they now
show as modified on the Pi. Commit them as in step 3:

```bash
cd ~/BirdNET-Pi
git status --short
git checkout -b illustrations-birefnet
git add avian/assets/illustrations/*.png avian/assets/illustrations/cuts.json \
        avian/frontend/masks.json avian/frontend/dims.json
git commit -m "avian: upgrade chroma cutouts to BiRefNet"
git push -u origin illustrations-birefnet
```

### Troubleshooting

| Message | Cause and fix |
|---|---|
| `missing dependency (...)` | Activate the virtual environment and re-run the `pip install` line. |
| `could not read cuts.json from ...` | SSH failed, or `--repo` is wrong. Check that `ssh <user>@<pi-address> true` works. |
| `--pi must be a safe user@host target` | Pass exactly `user@host`, with no path or port. |
| `nothing to upgrade` | No `"chroma"` entries left in `cuts.json`. |
| `[fail] <slug>: ...` | Usually a missing `raw/<slug>.png`. The bird stays in `cuts.json` and is retried on the next run. |
| `remote install failed` | The new files are kept in `.upgrade-stage/` on the Pi. Fix the cause and run the script again. |

Do not delete `raw/` while `cuts.json` still lists birds: it holds the only
copy of their uncut renders, and it exists only on the Pi.

---

## Notes

**What `cuts.json` and `raw/` are for.** Art made on the Pi uses a quick
chroma-key cutout, rough at the edges. Each such species is listed in
`cuts.json` (the admin menu counts them), and its uncut render is kept in
`raw/`. Later, `avian/scripts/upgrade_cutouts.py`, run from a laptop,
reads `raw/` over SSH, re-cuts the birds with BiRefNet, updates their masks,
and clears their `cuts.json` entries (see step 5). Commit again after an
upgrade. `raw/` stays on the Pi only, so do not delete it while `cuts.json`
still lists species.

**Browser cache.** Upstream bumps `TABLE_VERSION` in
`avian/frontend/apt.js` whenever the mask tables change, so every visitor
fetches the new ones. On a single station a hard refresh is enough; bump it
if other people view the site.

**Tools → Pull latest.** `scripts/update_birdnet.sh` only accepts
`https://github.com/Twarner491/AvianVisitors` as `origin`. With `origin`
pointing at this fork it refuses to run, so update with Git instead
(`git pull origin main`).
