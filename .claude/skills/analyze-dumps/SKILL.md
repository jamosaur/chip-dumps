---
name: analyze-dumps
description: Check dumps/ against dumps/inventory.yml, then send one dump-analyst sub-agent per new or unanalysed dump to reverse-engineer it and write analysis/<CHIP>/<N>.md. Use when the user adds dumps, asks to analyse dumps, or runs /analyze-dumps.
argument-hint: "[CHIP/N ...] [--redo]"
---

# Analyse new chip dumps

Arguments: `$ARGUMENTS`

- No arguments: analyse every dump that is new or has no write-up.
- `CHIP/N` values (for example `MBM29F016/7`): analyse only those dumps, even if they already have a write-up.
- `--redo`: also re-analyse dumps whose write-up has `status: in-progress`.

Run all commands from the repository root.

## 1. Check the folders against the inventory

```bash
python3 site/inventory.py check --json
```

The report has these lists:

| Key | Meaning | What to do |
| --- | --- | --- |
| `new` | `.bin` on disk, not in the inventory | Analyse |
| `unanalysed` | In the inventory, no `analysis/<CHIP>/<N>.md` | Analyse |
| `in_progress` | Write-up exists but is not `status: done` | Analyse only with `--redo` or when named |
| `changed` | SHA-256 differs from the inventory | Ask the user before doing anything: the file may have been replaced by mistake |
| `missing` | In the inventory, file gone | Report it; do not edit the inventory |
| `chips_without_metadata` | Chip folder has no `chip.yml` | Create it in step 2 |

Tell the user in one or two lines what you found and how many dumps you are about to analyse. If there is nothing to analyse, say so and stop.

If `site/inventory.py` fails because PyYAML or Markdown is missing, install them with `pip install --user -r site/requirements.txt` (or use `uv run --with-requirements site/requirements.txt python3 ...`).

## 2. Create missing chip metadata

For each folder in `chips_without_metadata`, look up the part number (datasheet search) and write `dumps/<CHIP>/chip.yml` in the same shape as `dumps/MBM29F016/chip.yml`: `part`, `maker`, `kind`, `package`, `marking_line`, `sector_size` (bytes, only if sectors are uniform), `description`, and a `specs` map. Only state values you found in a datasheet; leave a field out rather than guess. Do this before starting the agents, since they read it.

## 3. Send one sub-agent per dump

Use the Agent tool with `subagent_type: "dump-analyst"`, one agent per dump. Keep up to 4 running at once: start the first 4 in a single message, then start the next queued dump as soon as any agent finishes, so 4 stay busy until the queue is empty. Process each agent's result (step 4) as it arrives instead of waiting for the whole run.

Each agent starts with no context, so its prompt must contain:

- The chip folder name, dump number, repo-relative path and SHA-256 (from the check report).
- The full contents of `dumps/<CHIP>/chip.yml`.
- The list of other dump paths for the same chip.
- The paths of existing write-ups for that chip (`analysis/<CHIP>/*.md`, including `index.md`), so it can read them for context.
- The `source` and `notes` fields from the inventory for that dump, if the user filled them in.
- The output path: `analysis/<CHIP>/<N>.md`.
- Today's date for the `updated` field.

Do not include your own guesses about what the dump contains; let the agent look with fresh eyes.

## 4. Check the results

For each dump an agent reported on:

1. Confirm `analysis/<CHIP>/<N>.md` exists and its front matter has `title`, `summary`, `status`, `tags`, `updated` and `model`. Fix small formatting problems yourself; if the file is missing or empty, note the failure and leave the dump out of step 5 so it shows up as new next time.
2. If the agent saved images, check `analysis/<CHIP>/<N>/images/`. It should hold PNGs only, at most 12, each under 1 MB, plus a `captions.yml` that names every image. Delete anything else in the folder, such as raw extracted files or debug renders.
3. Confirm the agent did not change anything under `dumps/` (compare `python3 site/inventory.py check --json` before and after: no new `changed` entries).

## 5. Update the inventory

Record each successfully analysed dump that was in the `new` list:

```bash
python3 site/inventory.py add MBM29F016/7 MBM29F016/8
```

This keeps any `source` and `notes` the user wrote by hand.

## 6. Merge cross-dump notes

Collect the "Cross-dump observations" from the agents' replies. If any are substantive, add them to `analysis/<CHIP>/index.md` under a dated `## YYYY-MM-DD` heading (create the file with front matter `title: <CHIP> notes` if it does not exist). Keep everything already in the file. If two agents disagree, record both views and what would settle it.

When several dumps look like lanes of one wider bus, say which dumps, the probable lane order and the evidence.

## 7. Build the site

```bash
python3 site/build.py
```

It must finish without errors. Do not commit or push unless the user asks.

## 8. Report

Finish with a short table: dump, title, status, one-line summary. Then list any failures, `changed` or `missing` dumps that need the user's attention, and the cross-dump notes you added.
