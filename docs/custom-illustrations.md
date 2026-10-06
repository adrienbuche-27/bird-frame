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

---

## Notes

**What `cuts.json` and `raw/` are for.** Art made on the Pi uses a quick
chroma-key cutout, rough at the edges. Each such species is listed in
`cuts.json` (the admin menu counts them), and its uncut render is kept in
`raw/`. Later, `avian/scripts/upgrade_cutouts.py`, run from a laptop,
reads `raw/` over SSH, re-cuts the birds with BiRefNet, and clears their
`cuts.json` entries. Rebuild the masks and commit again after an upgrade.
`raw/` stays on the Pi only, so do not delete it while `cuts.json` still
lists species.

**Browser cache.** Upstream bumps `TABLE_VERSION` in
`avian/frontend/apt.js` whenever the mask tables change, so every visitor
fetches the new ones. On a single station a hard refresh is enough; bump it
if other people view the site.

**Tools → Pull latest.** `scripts/update_birdnet.sh` only accepts
`https://github.com/Twarner491/AvianVisitors` as `origin`. With `origin`
pointing at this fork it refuses to run, so update with Git instead
(`git pull origin main`).
