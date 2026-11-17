#!/usr/bin/env python3
"""Compare dumps/ against dumps/inventory.yml.

  python3 site/inventory.py check [--json]   report new, changed, missing and unanalysed dumps
  python3 site/inventory.py add CHIP/N ...   record dumps in the inventory (keeps hand-written fields)
  python3 site/inventory.py sync             record every dump on disk that is not in the inventory yet

A dump is "new" when its file is on disk but not in the inventory, "changed" when its
SHA-256 no longer matches, "missing" when the inventory lists it but the file is gone,
and "unanalysed" when there is no analysis/<CHIP>/<N>.md for it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import yaml

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from dumplib import (  # noqa: E402
    INVENTORY,
    ROOT,
    analysis_path,
    chip_dirs,
    dump_files,
    read_front_matter,
    sha256_file,
)

HEADER = """\
# Chip dump inventory.
#
# One entry per dumps/<CHIP>/<N>.bin. site/inventory.py and the /analyze-dumps skill
# add entries; you can add `source:` (seller, listing, board) and `notes:` by hand and
# they are kept. Comments other than this header are not preserved.
"""


def load() -> dict:
    if not INVENTORY.exists():
        return {"chips": {}}
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8")) or {}
    data.setdefault("chips", {})
    for chip in list(data["chips"]):
        data["chips"][chip] = data["chips"][chip] or {}
        data["chips"][chip].setdefault("dumps", {})
        data["chips"][chip]["dumps"] = {int(k): v or {} for k, v in data["chips"][chip]["dumps"].items()}
    return data


def save(data: dict) -> None:
    chips = {}
    for chip in sorted(data["chips"], key=str.lower):
        entry = dict(data["chips"][chip])
        entry["dumps"] = {n: entry["dumps"][n] for n in sorted(entry["dumps"])}
        chips[chip] = entry
    body = yaml.safe_dump({"chips": chips}, sort_keys=False, allow_unicode=True, width=100)
    INVENTORY.write_text(HEADER + "\n" + body, encoding="utf-8")


def check() -> dict:
    inv = load()
    report = {"new": [], "changed": [], "missing": [], "unanalysed": [], "in_progress": [], "chips_without_metadata": []}
    seen = set()
    for chip_dir in chip_dirs():
        chip = chip_dir.name
        files = dump_files(chip_dir)
        if files and not (chip_dir / "chip.yml").exists():
            report["chips_without_metadata"].append(chip)
        known = inv["chips"].get(chip, {}).get("dumps", {})
        for n, path in files:
            seen.add((chip, n))
            item = {"chip": chip, "number": n, "path": str(path.relative_to(ROOT)), "size": path.stat().st_size}
            digest = sha256_file(path)
            item["sha256"] = digest
            if n not in known:
                report["new"].append(item)
            elif known[n].get("sha256") != digest:
                report["changed"].append({**item, "inventory_sha256": known[n].get("sha256")})
            ap = analysis_path(chip, n)
            if not ap.exists():
                if n in known:
                    report["unanalysed"].append(item)
            else:
                meta, _ = read_front_matter(ap)
                if meta.get("status") != "done":
                    report["in_progress"].append({**item, "analysis": str(ap.relative_to(ROOT))})
    for chip, entry in inv["chips"].items():
        for n in entry.get("dumps", {}):
            if (chip, n) not in seen:
                report["missing"].append({"chip": chip, "number": n})
    return report


def file_time(path) -> str:
    """When the dump landed in the folder (file modification time), as local ISO time."""
    return dt.datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat()


def add(specs: list[str]) -> list[str]:
    inv = load()
    done = []
    for spec in specs:
        chip, _, num = spec.partition("/")
        path = ROOT / "dumps" / chip / f"{num}.bin"
        if not num.isdigit() or not path.is_file():
            raise SystemExit(f"No dump at {path.relative_to(ROOT)}. Use CHIP/N, for example MBM29F016/7.")
        n = int(num)
        chip_entry = inv["chips"].setdefault(chip, {"dumps": {}})
        chip_entry.setdefault("dumps", {})
        entry = chip_entry["dumps"].get(n, {})
        entry.update({"file": f"{n}.bin", "size": path.stat().st_size, "sha256": sha256_file(path)})
        entry.setdefault("added", file_time(path))
        entry.setdefault("source", "")
        entry.setdefault("notes", "")
        chip_entry["dumps"][n] = entry
        done.append(f"{chip}/{n}")
    save(inv)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    a = sub.add_parser("add")
    a.add_argument("dumps", nargs="+", metavar="CHIP/N")
    sub.add_parser("sync")
    args = ap.parse_args()

    if args.cmd == "check":
        r = check()
        if args.json:
            print(json.dumps(r, indent=2))
            return
        labels = {
            "new": "New (not in inventory)",
            "changed": "Changed (hash differs from inventory)",
            "missing": "Missing (in inventory, file gone)",
            "unanalysed": "In inventory, no analysis yet",
            "in_progress": "Analysis not marked done",
        }
        for key, label in labels.items():
            items = r[key]
            print(f"{label}: {len(items)}")
            for it in items:
                print(f"  {it['chip']}/{it['number']}")
        if r["chips_without_metadata"]:
            print("Chip folders without chip.yml: " + ", ".join(r["chips_without_metadata"]))
    elif args.cmd == "add":
        for d in add(args.dumps):
            print(f"Recorded {d}")
    elif args.cmd == "sync":
        new = [f"{i['chip']}/{i['number']}" for i in check()["new"]]
        for d in add(new) if new else []:
            print(f"Recorded {d}")
        if not new:
            print("Inventory already lists every dump on disk.")


if __name__ == "__main__":
    main()
