---
name: analyze-dumps
description: Run the chip-dump analysis pipeline. Check dumps/ against dumps/inventory.yml, analyse each new dump in isolation (dump-analyst), fingerprint it, cross-analyse it against the whole collection (cross-analyst), and write group analyses for groups that are ready (group-analyst). Use when the user adds dumps, asks to analyse dumps, or runs /analyze-dumps.
argument-hint: "[CHIP/N ...] [--redo] [--cross-all] [--groups]"
---

# Analyse chip dumps

Arguments: `$ARGUMENTS`

- No arguments: analyse every dump that is new or has no write-up, then cross-analyse and run group analysis where ready.
- `CHIP/N` values (for example `MBM29F016A/7`): re-analyse those dumps in isolation, even if they already have a write-up, then continue as usual.
- `--redo`: also re-analyse dumps whose write-up has `status: in-progress`.
- `--cross-all`: cross-analyse every dump again, not only the ones that need it.
- `--groups`: skip stages 1 and 2 and only run stage 3 (group analysis for groups that are ready).

The pipeline has three stages. Each one only touches its own files:

| Stage | Who | Reads | Writes |
| --- | --- | --- | --- |
| 1. Isolated analysis | `dump-analyst`, one per dump | that dump and its `chip.yml` | `analysis/<CHIP>/<N>.md`, `<N>.facts.yml`, `<N>/images/` |
| 2. Cross-analysis | `site/compare.py`, then one `cross-analyst` | facts, fingerprints, write-ups, targeted byte ranges | `analysis/relations.yml`, `analysis/groups.yml` |
| 3. Group analysis | `group-analyst`, one per ready group | the members' dumps and analyses | `analysis/groups/<slug>.md`, `analysis/groups/<slug>/images/` |

Group analysis is expensive, so it runs rarely: only for groups with two or more members, only once **every** dump of every chip in the group is analysed and cross-analysed, and only when the group's members changed since its write-up. `site/graph.py groups` applies these rules; do not work around them.

Run all commands from the repository root. If a script fails because PyYAML or Markdown is missing, install them with `pip install --user -r site/requirements.txt` (or use `uv run --with-requirements site/requirements.txt python3 ...`).

## 1. Check the folders against the inventory

```bash
python3 site/inventory.py check --json
```

| Key | Meaning | What to do |
| --- | --- | --- |
| `new` | `.bin` on disk, not in the inventory | Analyse (stage 1) |
| `unanalysed` | In the inventory, no write-up | Analyse (stage 1) |
| `in_progress` | Write-up not `status: done` | Analyse only with `--redo` or when named |
| `facts_missing` | Write-up done, no facts file | Analyse (stage 1): the write-up predates the facts file |
| `not_cross_analysed` | Analysed, not cross-analysed | Cross-analyse (stage 2) |
| `changed` | SHA-256 differs from the inventory | Ask the user before doing anything: the file may have been replaced by mistake |
| `missing` | In the inventory, file gone | Report it; do not edit the inventory |
| `chips_without_metadata` | Chip folder with dumps but no `chip.yml` | Create it first (below) |

Tell the user in one or two lines what you found: how many dumps go to stage 1, how many to stage 2, and whether any groups look ready. If there is nothing to do in any stage, say so and stop.

**Missing chip metadata.** For each folder in `chips_without_metadata`, look up the part number (datasheet search) and write `dumps/<CHIP>/chip.yml` in the same shape as `dumps/MBM29F016A/chip.yml`: `part`, `maker`, `kind`, `package`, `marking_line`, `sector_size` (bytes, only if sectors are uniform), `description`, and a `specs` map. Only state values you found in a datasheet; leave a field out rather than guess. Do this before stage 1, since the agents read it.

## 2. Stage 1: isolated analysis

**Prepare each dump.** If it already has output, delete it first so the agent starts clean and stale images cannot survive (git keeps the history):

```bash
rm -rf analysis/<CHIP>/<N>.md analysis/<CHIP>/<N>.facts.yml analysis/<CHIP>/<N>/images
```

Then clear its cross-analysis mark if it is in the inventory, because its facts are about to change: `python3 site/inventory.py cross --clear <CHIP>/<N>`.

**Send the agents.** Use the Agent tool with `subagent_type: "dump-analyst"`, one agent per dump. Keep up to 4 running at once: start the first 4 in a single message, then start the next queued dump as soon as one finishes, so 4 stay busy until the queue is empty. Check each result as it arrives.

Each agent starts with no context. Its prompt must contain only:

- The chip folder name, dump number, repo-relative path and SHA-256.
- The full contents of `dumps/<CHIP>/chip.yml`.
- The `source` and `notes` fields from the inventory for that dump, if the user filled them in.
- The output paths: `analysis/<CHIP>/<N>.md` and `analysis/<CHIP>/<N>.facts.yml`.
- Today's date for the `updated` field.

Do not mention other dumps, earlier write-ups or your own guesses. The analysis must be isolated.

**Check each result:**

1. `analysis/<CHIP>/<N>.md` exists and its front matter has `title`, `summary`, `status`, `tags`, `updated` and `model`. Fix small formatting problems yourself.
2. `analysis/<CHIP>/<N>.facts.yml` exists and `python3 site/graph.py check` reports no problems for it. Fix small YAML problems yourself.
3. `analysis/<CHIP>/<N>/images/`, if present, holds PNGs only, at most 12, each under 1 MB, plus a `captions.yml` that names every image. Delete anything else, such as raw extracted files or debug renders.
4. Nothing under `dumps/` changed: `python3 site/inventory.py check --json` shows no new `changed` entries.

If the write-up or facts file is missing or empty, note the failure and leave the dump out of the rest of the run, so it shows up again next time.

**Record and fingerprint** every dump that succeeded:

```bash
python3 site/inventory.py add MBM29F016A/7 MBM29F016A/8     # only dumps from the `new` list; keeps hand-written fields
python3 site/fingerprint.py MBM29F016A/7 MBM29F016A/8
```

## 3. Stage 2: cross-analysis

Targets are every dump in `not_cross_analysed` plus every dump that finished stage 1 in this run (all analysed dumps with `--cross-all`). Skip this stage if there are none.

1. Make sure every dump has a current fingerprint: `python3 site/fingerprint.py` (it only recomputes missing or stale ones).
2. Write the comparator report for the targets to a scratch file outside the repo:

   ```bash
   python3 site/compare.py MBM29F016A/7 MBM29F016A/8 --json > "$SCRATCH/compare.json"
   ```

3. Start **one** `cross-analyst` agent (`subagent_type: "cross-analyst"`). Its prompt contains the list of target dumps, the path of the comparator report, and today's date. Only one cross-analyst runs at a time, because it edits shared files.
4. When it finishes, run `python3 site/graph.py check`. If it reports problems in `relations.yml` or `groups.yml`, send them back to the same agent with SendMessage and ask it to fix them. Fix trivial YAML issues yourself.
5. Mark the targets as cross-analysed: `python3 site/inventory.py cross MBM29F016A/7 MBM29F016A/8`.

## 4. Stage 3: group analysis

```bash
python3 site/graph.py groups --json
```

For each group in `ready`, delete stale images first (`rm -rf analysis/groups/<slug>/images`), then start a `group-analyst` agent (`subagent_type: "group-analyst"`), up to 4 at once. Its prompt contains the group key, the group's full entry from `analysis/groups.yml` (paste it), the member dump paths, and today's date. Leave groups in `waiting` alone; report why they wait.

Check each result: `analysis/groups/<slug>.md` exists, its front matter has `title`, `summary`, `status`, `tags`, `updated`, `model` and a `members` list equal to the group's members, and its images follow the same rules as in stage 1. If the agent reports that a membership or position looks wrong, tell the user; the next cross-analysis can correct it.

## 5. Build the site

```bash
python3 site/graph.py check
python3 site/build.py
```

Both must finish without errors. Do not commit or push unless the user asks.

## 6. Report

Finish with:

- A short table of dumps analysed in stage 1: dump, title, status, one-line summary.
- New or superseded relations and group changes from stage 2, one line each.
- Groups analysed in stage 3, and groups still waiting with the reason.
- Failures, and any `changed` or `missing` dumps that need the user's attention.
