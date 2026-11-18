# Chip Dumps

Raw reads of flash and EPROM chips bought from Chinese sellers, with a reverse-engineering write-up for each image. The repository builds a static site that GitHub Pages serves.

## Layout

```
dumps/
  inventory.yml          every dump: hash, size, date added, cross-analysis date, source, notes
  <PART>/
    chip.yml             part, maker, package, specs (shown on the chip page)
    1.bin, 2.bin, ...    raw images, numbered
analysis/
  <PART>/
    <N>.md               isolated write-up for dump N, with YAML front matter
    <N>.facts.yml        structured facts from that analysis, for matching dumps
    <N>.print.json       computed fingerprint (site/fingerprint.py)
    <N>/images/          renders referenced from the write-up, with captions.yml
  relations.yml          how dumps relate (lanes of a bank, shared data, ...)
  groups.yml             dumps that came from one board, bank or chip set
  groups/<slug>.md       combined write-up for a group
site/
  build.py               static site generator -> _site/
  inventory.py           compare dumps/ with the inventory, track cross-analysis
  fingerprint.py         compute dump fingerprints
  compare.py             rank likely relations from fingerprints
  graph.py               validate relations, groups and facts; decide which groups are ready
  dumplib.py             shared code
  static/                CSS and JS
.claude/
  skills/analyze-dumps/  /analyze-dumps skill (the pipeline)
  agents/                dump-analyst, cross-analyst, group-analyst
```

## Adding dumps

1. Copy the image to `dumps/<PART>/<N>.bin` using the next free number.
2. In Claude Code, run `/analyze-dumps`. It runs three stages:
   - **Isolated analysis.** One `dump-analyst` per new dump reverse-engineers it without looking at any other dump, and writes the write-up and facts file. The dump is then fingerprinted.
   - **Cross-analysis.** `site/compare.py` ranks likely matches from the fingerprints, then one `cross-analyst` checks them against the facts files (reading targeted byte ranges where needed) and updates `relations.yml` and `groups.yml`.
   - **Group analysis.** A `group-analyst` writes a combined write-up for each group that is ready: at least two members, every dump of its chips analysed and cross-analysed, and members changed since its last write-up. This is the expensive stage, so it runs rarely.
3. Optionally fill in `source:` and `notes:` for the dump in `dumps/inventory.yml`.
4. Commit and push.

`/analyze-dumps MBM29F016A/3` re-analyses a single dump in isolation. `--redo` also redoes write-ups still marked `in-progress`, `--cross-all` cross-analyses every dump again, and `--groups` runs only the group stage.

## Building locally

```bash
pip install -r site/requirements.txt
python3 site/inventory.py check      # what is new, changed, missing, unanalysed or not cross-analysed
python3 site/graph.py check          # validate relations, groups and facts files
python3 site/graph.py groups         # which groups are ready for group analysis
python3 site/build.py                # writes _site/
python3 -m http.server -d _site      # preview at http://localhost:8000
```

## Publishing

`.github/workflows/pages.yml` builds and deploys on every push to `main`. In the repository's **Settings → Pages**, set **Source** to **GitHub Actions** once.
