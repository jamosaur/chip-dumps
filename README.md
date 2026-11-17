# Chip Dumps

Raw reads of flash and EPROM chips bought from Chinese sellers, with a reverse-engineering write-up for each image. The repository builds a static site that GitHub Pages serves.

## Layout

```
dumps/
  inventory.yml          every dump: hash, size, date added, source, notes
  <PART>/
    chip.yml             part, maker, package, specs (shown on the chip page)
    1.bin, 2.bin, ...    raw images, numbered
analysis/
  <PART>/
    index.md             notes that span several dumps (optional)
    <N>.md               write-up for dump N, with YAML front matter
site/
  build.py               static site generator -> _site/
  inventory.py           compare dumps/ with the inventory
  dumplib.py             shared stats code
  static/                CSS and JS
.claude/
  skills/analyze-dumps/  /analyze-dumps skill
  agents/dump-analyst.md sub-agent that analyses one dump
```

## Adding dumps

1. Copy the image to `dumps/<PART>/<N>.bin` using the next free number.
2. In Claude Code, run `/analyze-dumps`. It checks the folders against `dumps/inventory.yml`, starts one `dump-analyst` sub-agent per new or unanalysed dump, writes `analysis/<PART>/<N>.md`, records the dump in the inventory and builds the site.
3. Optionally fill in `source:` and `notes:` for the dump in `dumps/inventory.yml`.
4. Commit and push.

`/analyze-dumps MBM29F016/3` re-analyses a single dump; `/analyze-dumps --redo` also redoes write-ups still marked `in-progress`.

## Building locally

```bash
pip install -r site/requirements.txt
python3 site/inventory.py check      # what is new, changed, missing or unanalysed
python3 site/build.py                # writes _site/
python3 -m http.server -d _site      # preview at http://localhost:8000
```

## Publishing

`.github/workflows/pages.yml` builds and deploys on every push to `main`. In the repository's **Settings → Pages**, set **Source** to **GitHub Actions** once.
