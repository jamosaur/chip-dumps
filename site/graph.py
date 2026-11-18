#!/usr/bin/env python3
"""Relations between dumps, groups of dumps, and when a group is ready for group analysis.

  python3 site/graph.py check           validate relations.yml, groups.yml, facts files and group write-ups
  python3 site/graph.py groups [--json] which groups are ready for the group-analyst, and why others wait

Files (all under analysis/):
  <CHIP>/<N>.facts.yml   structured facts from the isolated dump analysis (dump-analyst)
  relations.yml          relations between dumps (cross-analyst)
  groups.yml             which dumps came from the same board, bank or set (cross-analyst)
  groups/<slug>.md       combined write-up for a group (group-analyst)

A group is ready for group analysis when it has at least two members, every dump of every
chip it touches is analysed and cross-analysed, and its members differ from the ones its
current write-up covers (or it has no write-up yet).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dumplib import (  # noqa: E402
    GROUPS_DIR,
    GROUPS_FILE,
    RELATIONS,
    ROOT,
    all_dumps,
    analysis_path,
    facts_path,
    parse_ref,
    read_front_matter,
)

KINDS = {
    "lanes-of-bank": "Lanes of one bank",
    "bank-continuation": "Bank continuation",
    "same-board-type": "Same board type",
    "same-firmware": "Same firmware",
    "shared-data": "Shared data",
    "duplicate": "Duplicate",
    "chip-set": "Same chip set",
    "other": "Related",
}
CONFIDENCE = ["high", "medium-high", "medium", "low"]
GROUP_KINDS = {"lanes", "chip-set"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FACT_KINDS = {"whole-image", "byte-lane", "word-lane", "unknown"}


@dataclass
class Relation:
    id: str
    kind: str
    dumps: list[str]
    confidence: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    method: str = ""
    found: str = ""
    status: str = "current"
    superseded_by: str = ""
    note: str = ""
    fulfils: list[dict] = field(default_factory=list)

    @property
    def current(self) -> bool:
        return self.status != "superseded"

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, self.kind)


@dataclass
class Member:
    dump: str
    bank: int | None = None
    lane: int | None = None
    confidence: str = ""
    note: str = ""


@dataclass
class Group:
    slug: str
    title: str
    summary: str = ""
    kind: str = "lanes"
    bus_bits: int | None = None
    lane_bits: int | None = None
    banks: int | None = None
    expected_members: int | None = None
    identified_as: str | None = None
    confidence: str = ""
    facts: dict = field(default_factory=dict)
    members: list[Member] = field(default_factory=list)
    wanted: list[dict] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    # filled from groups/<slug>.md
    meta: dict = field(default_factory=dict)
    body: str = ""

    @property
    def lanes(self) -> int:
        if self.kind == "lanes" and self.bus_bits and self.lane_bits:
            return max(1, self.bus_bits // self.lane_bits)
        return 0

    @property
    def expected(self) -> int | None:
        """How many chips the set had: stated, or banks × lanes when both are known."""
        if self.expected_members:
            return self.expected_members
        if self.kind == "lanes" and self.banks and self.lanes:
            return self.banks * self.lanes
        return None

    @property
    def refs(self) -> list[str]:
        return [m.dump for m in self.members]

    @property
    def chips(self) -> list[str]:
        return sorted({parse_ref(r)[0] for r in self.refs}, key=str.lower)

    def lane_bits_label(self, lane: int) -> str:
        """Lane 0 is the most significant byte lane."""
        if not (self.bus_bits and self.lane_bits):
            return ""
        hi = self.bus_bits - 1 - lane * self.lane_bits
        return f"D{hi}–D{hi - self.lane_bits + 1}"

    def position(self, m: Member) -> str:
        if self.kind == "chip-set":
            return "chip of a set"
        parts = []
        if self.banks and self.banks > 1 or (m.bank is None and self.banks != 1):
            parts.append(f"bank {m.bank}" if m.bank is not None else "bank ?")
        parts.append(f"lane {m.lane}" if m.lane is not None else "lane ?")
        return " · ".join(parts)

    @property
    def analysed_members(self) -> list[str]:
        return [str(x) for x in (self.meta.get("members") or [])]

    @property
    def has_writeup(self) -> bool:
        return bool(self.meta) and self.meta.get("status") == "done"

    @property
    def up_to_date(self) -> bool:
        return self.has_writeup and sorted(self.analysed_members) == sorted(self.refs)


def _load_yaml(path: Path, key: str) -> tuple[object, list[str]]:
    if not path.exists():
        return ({} if key == "groups" else []), []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return ({} if key == "groups" else []), [f"{path.relative_to(ROOT)}: not valid YAML ({exc})"]
    if not isinstance(data, dict):
        return ({} if key == "groups" else []), [f"{path.relative_to(ROOT)}: expected a mapping with `{key}:`"]
    return data.get(key) or ({} if key == "groups" else []), []


def _int(v) -> int | None:
    try:
        return None if v is None or v == "" else int(v)
    except (TypeError, ValueError):
        return None


def load_relations() -> tuple[list[Relation], list[str]]:
    raw, errors = _load_yaml(RELATIONS, "relations")
    out = []
    for i, r in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(r, dict):
            errors.append(f"relations.yml entry {i + 1}: not a mapping")
            continue
        out.append(Relation(
            id=str(r.get("id", "")),
            kind=str(r.get("kind", "other")),
            dumps=[str(d) for d in (r.get("dumps") or [])],
            confidence=str(r.get("confidence", "")).lower(),
            summary=str(r.get("summary", "")),
            evidence=[str(x) for x in (r.get("evidence") or [])],
            method=str(r.get("method", "")),
            found=str(r.get("found", "")),
            status=str(r.get("status", "current")),
            superseded_by=str(r.get("superseded_by") or ""),
            note=str(r.get("note") or ""),
            fulfils=[x for x in (r.get("fulfils") or []) if isinstance(x, dict)],
        ))
    return out, errors


def load_groups() -> tuple[list[Group], list[str]]:
    raw, errors = _load_yaml(GROUPS_FILE, "groups")
    out = []
    for slug, g in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(g, dict):
            errors.append(f"groups.yml {slug}: not a mapping")
            continue
        members = []
        for m in g.get("members") or []:
            if isinstance(m, dict):
                members.append(Member(str(m.get("dump", "")), _int(m.get("bank")), _int(m.get("lane")),
                                      str(m.get("confidence", "")).lower(), str(m.get("note") or "")))
        grp = Group(
            slug=str(slug), title=str(g.get("title") or slug), summary=str(g.get("summary") or ""),
            kind=str(g.get("kind") or "lanes"), bus_bits=_int(g.get("bus_bits")), lane_bits=_int(g.get("lane_bits")),
            banks=_int(g.get("banks")), expected_members=_int(g.get("expected_members")),
            identified_as=(str(g["identified_as"]) if g.get("identified_as") else None),
            confidence=str(g.get("confidence") or "").lower(),
            facts={str(k): str(v) for k, v in (g.get("facts") or {}).items()},
            members=members, wanted=[w for w in (g.get("wanted") or []) if isinstance(w, dict)],
            created=str(g.get("created") or ""), updated=str(g.get("updated") or ""),
        )
        md = GROUPS_DIR / f"{slug}.md"
        if md.exists():
            grp.meta, grp.body = read_front_matter(md)
        out.append(grp)
    return out, errors


def load_facts(chip: str, n: int) -> tuple[dict, list[str]]:
    p = facts_path(chip, n)
    if not p.exists():
        return {}, []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {}, [f"{p.relative_to(ROOT)}: not valid YAML ({exc})"]
    if not isinstance(data, dict):
        return {}, [f"{p.relative_to(ROOT)}: expected a mapping"]
    return data, []


def check() -> list[str]:
    errors: list[str] = []
    on_disk = {f"{c}/{n}" for c, n, _ in all_dumps()}
    facts = {}
    for ref in sorted(on_disk):
        chip, n = parse_ref(ref)
        f, errs = load_facts(chip, n)
        errors += errs
        if f:
            facts[ref] = f
            where = facts_path(chip, n).relative_to(ROOT)
            if str(f.get("dump", "")) != ref:
                errors.append(f"{where}: `dump` should be {ref}")
            if f.get("kind") not in FACT_KINDS:
                errors.append(f"{where}: `kind` must be one of {', '.join(sorted(FACT_KINDS))}")
            ids = [str(w.get("id", "")) for w in f.get("wanted") or [] if isinstance(w, dict)]
            if len(ids) != len(set(ids)) or not all(SLUG.match(i) for i in ids):
                errors.append(f"{where}: every `wanted` item needs a unique kebab-case `id`")
        elif analysis_path(chip, n).exists():
            meta, _ = read_front_matter(analysis_path(chip, n))
            if meta.get("status") == "done":
                errors.append(f"analysis/{chip}/{n}.md is done but analysis/{chip}/{n}.facts.yml is missing")

    rels, errs = load_relations()
    errors += errs
    ids = [r.id for r in rels]
    for r in rels:
        tag = f"relations.yml {r.id or '(no id)'}"
        if not SLUG.match(r.id):
            errors.append(f"{tag}: `id` must be kebab-case")
        if ids.count(r.id) > 1:
            errors.append(f"{tag}: duplicate id")
        if r.kind not in KINDS:
            errors.append(f"{tag}: unknown kind `{r.kind}` (use one of {', '.join(KINDS)})")
        if r.confidence not in CONFIDENCE:
            errors.append(f"{tag}: confidence must be one of {', '.join(CONFIDENCE)}")
        if len(r.dumps) < 2:
            errors.append(f"{tag}: needs at least two dumps")
        for d in r.dumps:
            if d not in on_disk:
                errors.append(f"{tag}: no dump {d}")
        if not r.summary or not r.evidence:
            errors.append(f"{tag}: needs a `summary` and at least one `evidence` item")
        if r.status not in ("current", "superseded"):
            errors.append(f"{tag}: status must be current or superseded")
        if r.superseded_by and r.superseded_by not in ids:
            errors.append(f"{tag}: superseded_by `{r.superseded_by}` does not exist")
        for fl in r.fulfils:
            d, w = str(fl.get("dump", "")), str(fl.get("wanted", ""))
            wanted_ids = {str(x.get("id")) for x in (facts.get(d, {}).get("wanted") or []) if isinstance(x, dict)}
            if w not in wanted_ids:
                errors.append(f"{tag}: fulfils {d} wanted `{w}`, which is not in that dump's facts file")

    groups, errs = load_groups()
    errors += errs
    seen: dict[str, str] = {}
    for g in groups:
        tag = f"groups.yml {g.slug}"
        if not SLUG.match(g.slug):
            errors.append(f"{tag}: the key must be kebab-case")
        if g.kind not in GROUP_KINDS:
            errors.append(f"{tag}: kind must be lanes or chip-set")
        if g.kind == "lanes" and not (g.bus_bits and g.lane_bits):
            errors.append(f"{tag}: lanes groups need bus_bits and lane_bits")
        if not g.members:
            errors.append(f"{tag}: has no members")
        for m in g.members:
            if m.dump not in on_disk:
                errors.append(f"{tag}: no dump {m.dump}")
            if m.dump in seen:
                errors.append(f"{tag}: {m.dump} is already in group {seen[m.dump]}")
            seen[m.dump] = g.slug
            if g.lanes and m.lane is not None and not 0 <= m.lane < g.lanes:
                errors.append(f"{tag}: {m.dump} lane {m.lane} is outside 0–{g.lanes - 1}")
            if g.banks and m.bank is not None and not 0 <= m.bank < g.banks:
                errors.append(f"{tag}: {m.dump} bank {m.bank} is outside 0–{g.banks - 1}")
        if g.meta:
            for k in ("title", "summary", "status", "updated", "model", "members"):
                if k not in g.meta:
                    errors.append(f"analysis/groups/{g.slug}.md: front matter needs `{k}`")
    if GROUPS_DIR.is_dir():
        known = {g.slug for g in groups}
        for md in GROUPS_DIR.glob("*.md"):
            if md.stem not in known:
                errors.append(f"analysis/groups/{md.name}: no group `{md.stem}` in groups.yml")
    return errors


def readiness() -> dict:
    """Which groups the group-analyst should run for, and why the others wait."""
    import inventory  # local import: inventory imports nothing from here

    inv = inventory.load()
    by_chip: dict[str, list[int]] = {}
    for c, n, _ in all_dumps():
        by_chip.setdefault(c, []).append(n)

    def chip_state(chip: str) -> list[str]:
        problems = []
        dumps = inv["chips"].get(chip, {}).get("dumps", {})
        for n in by_chip.get(chip, []):
            meta, _ = read_front_matter(analysis_path(chip, n)) if analysis_path(chip, n).exists() else ({}, "")
            if meta.get("status") != "done" or not facts_path(chip, n).exists():
                problems.append(f"{chip}/{n} not analysed")
            elif not (dumps.get(n) or {}).get("cross_analysed"):
                problems.append(f"{chip}/{n} not cross-analysed")
        return problems

    groups, _ = load_groups()
    report = {"ready": [], "waiting": [], "up_to_date": []}
    for g in groups:
        item = {"group": g.slug, "title": g.title, "members": g.refs}
        if g.up_to_date:
            report["up_to_date"].append(item)
            continue
        if len(g.members) < 2:
            report["waiting"].append({**item, "reason": "only one member; waits for a partner"})
            continue
        problems = [p for c in g.chips for p in chip_state(c)]
        if problems:
            report["waiting"].append({**item, "reason": "; ".join(problems[:6]) + (" …" if len(problems) > 6 else "")})
        else:
            report["ready"].append(item)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    g = sub.add_parser("groups")
    g.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.cmd == "check":
        errors = check()
        for err in errors:
            print(err)
        print(f"{len(errors)} problem{'s' if len(errors) != 1 else ''} found." if errors else "Relations, groups and facts files look valid.")
        raise SystemExit(1 if errors else 0)
    r = readiness()
    if args.json:
        print(json.dumps(r, indent=2))
        return
    for key, label in (("ready", "Ready for group analysis"), ("waiting", "Waiting"), ("up_to_date", "Up to date")):
        print(f"{label}: {len(r[key])}")
        for it in r[key]:
            print(f"  {it['group']}" + (f": {it['reason']}" if it.get("reason") else ""))


if __name__ == "__main__":
    main()
