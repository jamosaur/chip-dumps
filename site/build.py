#!/usr/bin/env python3
"""Build the static GitHub Pages site from dumps/ and analysis/.

  python3 site/build.py              writes _site/
  python3 site/build.py --out DIR    writes somewhere else

Preview locally with:  python3 -m http.server -d _site
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dumplib import (  # noqa: E402
    ANALYSIS_DIR,
    GROUPS_DIR,
    INVENTORY,
    ROOT,
    DumpStats,
    analysis_path,
    chip_dirs,
    compute_stats,
    dump_files,
    read_front_matter,
    slugify,
)
import compare  # noqa: E402
import fingerprint  # noqa: E402
import graph  # noqa: E402
from graph import CONFIDENCE, Group, Member, Relation  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
FONTS = (
    "https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700"
    "&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
)
SIDEBAR_STRINGS = 12
LATEST_COUNT = 10
NEAREST_COUNT = 4
e = html.escape


# --------------------------------------------------------------------------- data


@dataclass
class Dump:
    chip: "Chip"
    stats: DumpStats
    meta: dict = field(default_factory=dict)
    body_html: str = ""
    added: str = ""  # ISO timestamp from dumps/inventory.yml
    cross_analysed: str = ""  # date from dumps/inventory.yml
    images: list["Image"] = field(default_factory=list)
    unreferenced: list["Image"] = field(default_factory=list)  # images no write-up references
    facts: dict = field(default_factory=dict)  # analysis/<CHIP>/<N>.facts.yml
    fp: dict | None = None  # analysis/<CHIP>/<N>.print.json
    group: Group | None = None
    member: Member | None = None
    relations: list[Relation] = field(default_factory=list)
    nearest: list[tuple["Dump", float]] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.stats.number

    @property
    def ref(self) -> str:
        return f"{self.chip.name}/{self.n}"

    def label(self, other_chip: bool) -> str:
        return f"{self.chip.part} dump {self.n}" if other_chip else f"Dump {self.n}"

    @property
    def status(self) -> str:
        if not self.meta:
            return "todo"
        return "done" if self.meta.get("status") == "done" else "wip"

    def url(self, root: str) -> str:
        return f"{root}{self.chip.slug}/{self.n}/"


@dataclass
class Image:
    path: Path
    caption: str
    width: int | None = None
    height: int | None = None

    @property
    def name(self) -> str:
        return self.path.name


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}  # no SVG: it can carry script


def png_size(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as f:
        head = f.read(24)
    if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return None, None


def load_images(folder: Path) -> list[Image]:
    """Images in analysis/<CHIP>/<N>/images/, captioned from captions.yml (filename: caption)."""
    if not folder.is_dir():
        return []
    captions_file = folder / "captions.yml"
    captions = yaml.safe_load(captions_file.read_text(encoding="utf-8")) if captions_file.exists() else {}
    captions = captions if isinstance(captions, dict) else {}
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_TYPES]
    # Images listed in captions.yml come first, in that order; the rest follow by name.
    order = {name: i for i, name in enumerate(captions)}
    files.sort(key=lambda p: (order.get(p.name, len(order)), p.name))
    out = []
    for p in files:
        caption = str(captions.get(p.name) or p.stem.replace("-", " ").replace("_", " ").capitalize())
        out.append(Image(p, caption, *png_size(p)))
    return out


@dataclass
class Chip:
    name: str
    slug: str
    info: dict
    dumps: list[Dump] = field(default_factory=list)

    @property
    def part(self) -> str:
        return str(self.info.get("part") or self.name)


def render_markdown(text: str, captions: dict[str, str] | None = None) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    # Analysis text quotes bytes from untrusted dumps, so raw HTML is escaped, never passed through.
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    out = md.convert(text)
    out = re.sub(r'(href|src)="\s*(?:javascript|data|vbscript):[^"]*"', r'\1="#"', out, flags=re.I)
    captions = captions or {}

    # An image on its own line becomes a figure with its captions.yml caption underneath.
    def figure(m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        cap = captions.get(src.rsplit("/", 1)[-1])
        cap_html = e(cap) if cap else alt
        return (
            f'<figure class="inline-fig"><a class="inline-shot" href="{src}" data-lightbox data-caption="{cap_html}">'
            f'<img alt="{alt}" src="{src}" loading="lazy"></a><figcaption>{cap_html}</figcaption></figure>'
        )

    out = re.sub(r'<p>\s*<img alt="([^"]*)" src="([^"]+)"\s*/?>\s*</p>', figure, out)
    # Images inside running text open in the lightbox too.
    out = re.sub(
        r'<img alt="([^"]*)" src="([^"]+)"\s*/?>(?!</a>)',
        r'<a class="inline-shot" href="\2" data-lightbox data-caption="\1"><img alt="\1" src="\2" loading="lazy"></a>',
        out,
    )
    return out.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")


def inline_md(text: str) -> str:
    """Escape a one-line string from YAML, keeping `code` and **bold**."""
    out = e(str(text))
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)


def referenced_images(body_html: str, images: list[Image]) -> list[Image]:
    used = set(re.findall(r'src="images/([^"/]+)"', body_html))
    return [i for i in images if i.name not in used]


def load_inventory() -> dict[tuple[str, int], dict]:
    if not INVENTORY.exists():
        return {}
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8")) or {}
    out = {}
    for chip, entry in (data.get("chips") or {}).items():
        for n, d in ((entry or {}).get("dumps") or {}).items():
            out[(chip, int(n))] = d or {}
    return out


def load_chips() -> list[Chip]:
    inv = load_inventory()
    chips = []
    for d in chip_dirs():
        files = dump_files(d)
        if not files:
            continue
        info_path = d / "chip.yml"
        info = yaml.safe_load(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
        chip = Chip(d.name, slugify(d.name), info or {})
        sector = chip.info.get("sector_size")
        for n, path in files:
            print(f"  {d.name}/{n}.bin", file=sys.stderr)
            dump = Dump(chip, compute_stats(n, path, int(sector) if sector else None))
            entry = inv.get((d.name, n), {})
            # Dumps not yet in the inventory are the newest by definition.
            dump.added = str(entry["added"]).replace(" ", "T") if entry.get("added") else "9999"
            dump.cross_analysed = str(entry.get("cross_analysed") or "")
            dump.images = load_images(ANALYSIS_DIR / d.name / str(n) / "images")
            ap = analysis_path(d.name, n)
            if ap.exists():
                meta, body = read_front_matter(ap)
                dump.meta = meta or {"status": "in-progress"}
                dump.body_html = render_markdown(body, {i.name: i.caption for i in dump.images})
            dump.unreferenced = referenced_images(dump.body_html, dump.images)
            if dump.unreferenced and dump.meta:
                names = ", ".join(i.name for i in dump.unreferenced)
                print(f"  warning: analysis/{d.name}/{n}.md does not reference {names}", file=sys.stderr)
            dump.facts, errs = graph.load_facts(d.name, n)
            for err in errs:
                print(f"  warning: {err}", file=sys.stderr)
            fp = fingerprint.load(d.name, n)
            if not fp or fp.get("version") != fingerprint.VERSION or fp.get("sha256") != dump.stats.sha256:
                print(f"  fingerprint for {d.name}/{n} is missing or stale; computing it (run site/fingerprint.py to save it)", file=sys.stderr)
                fp = fingerprint.compute(d.name, n, path)
            dump.fp = fp
            chip.dumps.append(dump)
        chips.append(chip)
    return chips


def link_graph(chips: list[Chip]) -> tuple[list[Group], list[Relation]]:
    """Attach relations, groups and fingerprint neighbours to the dumps."""
    by_ref = {d.ref: d for c in chips for d in c.dumps}
    rels, errs = graph.load_relations()
    groups, errs2 = graph.load_groups()
    for err in errs + errs2:
        print(f"  warning: {err}", file=sys.stderr)
    for r in rels:
        for ref in r.dumps:
            if ref in by_ref:
                by_ref[ref].relations.append(r)
    for g in groups:
        g.members = [m for m in g.members if m.dump in by_ref]
        for m in g.members:
            by_ref[m.dump].group, by_ref[m.dump].member = g, m
    groups = [g for g in groups if g.members]
    dumps = list(by_ref.values())
    for d in dumps:
        scored = [(o, compare.score(d.fp, o.fp)["score"]) for o in dumps if o is not d]
        d.nearest = sorted(scored, key=lambda x: x[1], reverse=True)[:NEAREST_COUNT]
    return groups, rels


# --------------------------------------------------------------------------- helpers


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def size_label(n: int) -> str:
    for unit, div in (("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div and n % div == 0:
            return f"{n // div} {unit}"
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def heat(cell) -> str:
    if cell.ff >= 0.985:
        return "var(--erased)"
    if cell.zero >= 0.985:
        return "var(--zero)"
    p = round(max(0.0, min(1.0, cell.entropy / 8)) * 100)
    return f"color-mix(in oklab, var(--heat-hi) {p}%, var(--heat-lo))"


def auto_tag(s: DumpStats) -> str:
    if s.entropy > 7.5:
        return "High entropy: compressed or encrypted"
    if s.ff > 0.5:
        return f"Mostly erased ({pct(s.ff)} FFh)"
    if s.zero > 0.4:
        return "Sparse: structured data or code"
    return "Mixed content"


def added_label(d: Dump) -> str:
    return "Not recorded" if d.added == "9999" else e(d.added[:10])


def column_word(d: Dump) -> str:
    """Columns are real erase sectors only when chip.yml's sector_size set them."""
    return "sector" if d.chip.info.get("sector_size") == d.stats.column_size else "slice"


def pill(status: str) -> str:
    label = {"done": "Analysed", "wip": "In progress", "todo": "Not started"}[status]
    return f'<span class="pill {status}">{label}</span>'


def barcode(d: Dump) -> str:
    cells = "".join(f'<i style="background:{heat(c)}"></i>' for c in d.stats.columns)
    return f'<span class="barcode" title="Dump {d.n}: entropy per sector">{cells}</span>'


def legend() -> str:
    return (
        '<div class="legend"><span><i style="background:var(--erased)"></i>Erased (FFh)</span>'
        '<span><i style="background:var(--zero)"></i>Zero-filled</span>'
        '<span>Entropy 0 <span class="ramp"></span> 8 bits/byte</span></div>'
    )


def chip_svg(chip: Chip, small: bool = False) -> str:
    pkg = str(chip.info.get("package", ""))
    m = re.search(r"(\d+)", pkg)
    per_side = max(4, min(32, int(m.group(1)) // 2)) if m else 20
    pitch = 124 / per_side
    pins = "".join(
        f'<rect x="4" y="{14 + i * pitch:.1f}" width="16" height="{max(1.5, pitch * 0.5):.1f}" fill="var(--accent)"></rect>'
        f'<rect x="220" y="{14 + i * pitch:.1f}" width="16" height="{max(1.5, pitch * 0.5):.1f}" fill="var(--accent)"></rect>'
        for i in range(per_side)
    )
    size = ' width="64" height="40"' if small else ""
    org = e(str(chip.info.get("marking_line", chip.info.get("specs", {}).get("Organisation", ""))))
    return f"""<svg viewBox="0 0 240 150"{size} role="img" aria-label="{e(chip.part)} package">
    {pins}
    <rect x="20" y="10" width="200" height="130" rx="3" fill="var(--ink)"></rect>
    <circle cx="34" cy="24" r="5" fill="var(--surface)" opacity="0.25"></circle>
    <text x="120" y="76" text-anchor="middle" fill="var(--surface)" font-family="Chakra Petch, sans-serif" font-weight="700" font-size="{min(24, 300 // max(1, len(chip.part)))}" letter-spacing="1">{e(chip.part)}</text>
    <text x="120" y="98" text-anchor="middle" fill="var(--surface)" opacity="0.6" font-family="IBM Plex Mono, monospace" font-size="10">{org}</text>
    <text x="120" y="124" text-anchor="middle" fill="var(--surface)" opacity="0.35" font-family="IBM Plex Mono, monospace" font-size="9">{e(pkg)}</text>
  </svg>"""


def page(title: str, root: str, nav: str, body: str, description: str = "") -> str:
    sha = os.environ.get("GITHUB_SHA", "")[:7]
    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    def cur(key: str) -> str:
        return ' aria-current="page"' if key == nav else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(description or 'Flash and EPROM dumps with reverse-engineering notes.')}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{root}assets/style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 26'%3E%3Crect x='5' y='4' width='16' height='18' rx='1.5' fill='%2317201d'/%3E%3Cg fill='%23a8521c'%3E%3Crect x='1' y='6' width='4' height='2'/%3E%3Crect x='1' y='12' width='4' height='2'/%3E%3Crect x='1' y='18' width='4' height='2'/%3E%3Crect x='21' y='6' width='4' height='2'/%3E%3Crect x='21' y='12' width='4' height='2'/%3E%3Crect x='21' y='18' width='4' height='2'/%3E%3C/g%3E%3C/svg%3E">
</head>
<body>
<header class="topbar">
  <div class="wrap">
    <a class="brand" href="{root}" aria-label="Chip Dumps home">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
        <rect x="5" y="4" width="16" height="18" rx="1.5" fill="var(--ink)"></rect>
        <circle cx="8.5" cy="7.5" r="1.3" fill="var(--surface)"></circle>
        <g fill="var(--accent)">
          <rect x="1" y="6" width="4" height="1.6"></rect><rect x="1" y="10" width="4" height="1.6"></rect><rect x="1" y="14" width="4" height="1.6"></rect><rect x="1" y="18" width="4" height="1.6"></rect>
          <rect x="21" y="6" width="4" height="1.6"></rect><rect x="21" y="10" width="4" height="1.6"></rect><rect x="21" y="14" width="4" height="1.6"></rect><rect x="21" y="18" width="4" height="1.6"></rect>
        </g>
      </svg>
      Chip Dumps
    </a>
    <nav class="nav" aria-label="Site">
      <a href="{root}"{cur('home')}>Chips</a>
      <a href="{root}about/"{cur('about')}>How it works</a>
    </nav>
  </div>
</header>
<main><div class="wrap">
{body}
</div></main>
<footer><div class="wrap"><span>Built {built}{f' from {sha}' if sha else ''}. Raw images are unmodified reads.</span><span>Offsets are byte addresses on the chip.</span></div></footer>
<script src="{root}assets/site.js" defer></script>
</body>
</html>
"""


# --------------------------------------------------------------------------- groups and relations


CONF_PILL = {"high": "done", "medium-high": "wip", "medium": "wip", "low": "todo"}


def conf_pill(conf: str) -> str:
    label = conf.replace("-", " ").capitalize() if conf else "Unrated"
    return f'<span class="pill {CONF_PILL.get(conf, "todo")}">{e(label)}</span>'


def group_url(g: Group, root: str) -> str:
    return f"{root}groups/{g.slug}/"


def group_counts(g: Group) -> str:
    """'3 of 4', '1 of ?'."""
    return f"{len(g.members)} of {g.expected or '?'}"


def group_label(g: Group) -> str:
    if g.kind == "chip-set":
        return f"Group · {len(g.members)} chip{'s' if len(g.members) != 1 else ''} of {g.expected or 'several'}"
    return f"Group · {group_counts(g)} lanes"


def group_pill(g: Group) -> str:
    if len(g.members) < 2:
        return '<span class="pill todo">Waiting for partners</span>'
    if g.identified_as:
        return '<span class="pill done">Identified</span>'
    return '<span class="pill wip">Unidentified</span>'


def group_state(g: Group) -> tuple[str, str]:
    """(pill class, label) for the group analysis itself."""
    if g.up_to_date:
        return "done", "Analysed"
    if len(g.members) < 2:
        return "todo", "Waiting for partners"
    if g.has_writeup:
        return "wip", "Update pending"
    return "wip", "Group analysis pending"


def group_chips(g: Group, by_ref: dict[str, Dump]) -> str:
    counts: dict[str, int] = {}
    for m in g.members:
        part = by_ref[m.dump].chip.part
        counts[part] = counts.get(part, 0) + 1
    return ", ".join(f"{p} × {k}" for p, k in sorted(counts.items()))


def lane_grid(g: Group, by_ref: dict[str, Dump], root: str, here: Dump | None = None, compact: bool = True) -> str:
    """Bank × lane grid (or the slots of a chip set) with members linked."""
    multi_chip = len(g.chips) > 1

    def cell(d: Dump | None) -> str:
        if d is None:
            return '<td class="gap"><span class="sr">not dumped</span></td>'
        text = e(d.ref if multi_chip else str(d.n))
        if here is not None and d is here:
            sub = "" if compact else "<small>this dump</small>"
            return f'<td class="here"><span>{text}</span>{sub}</td>'
        return f'<td class="have"><a href="{d.url(root)}">{text}</a></td>'

    if g.kind == "chip-set" or not g.lanes:
        cells = [cell(by_ref[m.dump]) for m in g.members]
        missing = (g.expected_members or 0) - len(g.members)
        cells += [cell(None)] * max(0, missing)
        if not g.expected_members:
            cells.append('<td class="more">…</td>')
        return f'<div class="lanes-scroll"><table class="lanes{" compact" if compact else ""}"><tbody><tr><th>Chips</th>{"".join(cells)}</tr></tbody></table></div>'

    lanes = g.lanes
    banks: list[int | None] = list(range(g.banks)) if g.banks else []
    if not banks or any(m.bank is None for m in g.members):
        banks.append(None)
    head = "".join(
        f'<th title="{g.lane_bits_label(i)}">L{i}' + ("" if compact else f"<small>{g.lane_bits_label(i)}</small>") + "</th>"
        for i in range(lanes)
    )
    rows, unplaced = [], []
    for b in banks:
        tds = []
        for lane in range(lanes):
            m = next((m for m in g.members if m.bank == b and m.lane == lane), None)
            tds.append(cell(by_ref[m.dump] if m else None))
        if b is None:
            label = "Bank" if g.banks == 1 or (g.banks is None and len(banks) == 1 and len(g.members) == 1) else "Bank ?"
        else:
            label = f"Bank {b}" if len(banks) > 1 else "Bank"
        rows.append(f"<tr><th>{label}</th>{''.join(tds)}</tr>")
    for m in g.members:
        if m.lane is None:
            unplaced.append(by_ref[m.dump])
    extra = ""
    if unplaced:
        extra = '<p class="fine">Position unknown: ' + ", ".join(
            f'<a href="{d.url(root)}">{e(d.ref if multi_chip else "dump " + str(d.n))}</a>' for d in unplaced) + "</p>"
    return (f'<div class="lanes-scroll"><table class="lanes{" compact" if compact else ""}"><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>{extra}')


def group_card(g: Group, by_ref: dict[str, Dump], root: str) -> str:
    foot = " · ".join(e(v) for v in list(g.facts.values())[:3])
    return f"""<a class="panel gcard" href="{group_url(g, root)}">
          <div class="gtop"><span class="label">{e(group_label(g))}</span>{group_pill(g)}</div>
          <h3>{e(g.title)}</h3>
          <p>{inline_md(g.summary)}</p>
          {lane_grid(g, by_ref, root)}
          {f'<span class="gfoot">{foot}</span>' if foot else ''}
        </a>"""


def relation_item(r: Relation, d: Dump, by_ref: dict[str, Dump], root: str) -> str:
    others = [by_ref[x] for x in r.dumps if x != d.ref and x in by_ref]
    targets = "".join(f'<a class="target" href="{o.url(root)}">{e(o.label(o.chip is not d.chip))}</a>' for o in others)
    if not r.current:
        note = f"<p>{inline_md(r.note)}</p>" if r.note else ""
        found = f"Suggested {e(r.found)}. " if r.found else ""
        return f"""<details class="rel old">
            <summary><span class="kind">{e(r.kind_label)}</span><span class="targets">{targets}</span><span class="pill todo">Superseded</span></summary>
            <p>{inline_md(r.summary)}</p><p class="when">{found}No longer holds.</p>{note}
          </details>"""
    ev = "".join(f"<li>{inline_md(x)}</li>" for x in r.evidence)
    when = " · ".join(x for x in (f"Found {e(r.found)}" if r.found else "", e(r.method)) if x)
    return f"""<article class="rel">
            <div class="rel-top"><span class="kind">{e(r.kind_label)}</span><span class="targets">{targets}</span>{conf_pill(r.confidence)}</div>
            <p>{inline_md(r.summary)}</p>
            <ul>{ev}</ul>
            {f'<p class="when">{when}</p>' if when else ''}
          </article>"""


def sort_relations(rels: list[Relation]) -> list[Relation]:
    rank = {c: i for i, c in enumerate(CONFIDENCE)}
    current = sorted((r for r in rels if r.current), key=lambda r: (rank.get(r.confidence, 9), r.found), reverse=False)
    return current + [r for r in rels if not r.current]


def related_section(d: Dump, by_ref: dict[str, Dump], root: str) -> str:
    parts = []
    g = d.group
    if g:
        foot = " · ".join(e(v) for v in list(g.facts.values())[:3])
        parts.append(f"""<article class="panel group">
          <header>
            <span class="label">{e(group_label(g))}</span>
            <h3>{e(g.title)}</h3>
            <p>{inline_md(g.summary)}</p>
          </header>
          {lane_grid(g, by_ref, root, here=d, compact=False)}
          {f'<p class="fine">{foot}</p>' if foot else ''}
          <div class="combined">
            <span class="label">This dump</span>
            <p>{e(g.position(d.member).capitalize())}{f", {e(d.member.confidence)} confidence" if d.member and d.member.confidence else ""}.{(" " + inline_md(d.member.note)) if d.member and d.member.note else ""}</p>
            <a class="btn" href="{group_url(g, root)}">Group page</a>
          </div>
        </article>""")
    rels = sort_relations(d.relations)
    if rels:
        parts.append(f'<div class="panel rels">{"".join(relation_item(r, d, by_ref, root) for r in rels)}</div>')
    if not parts:
        msg = (f"No related dumps found. Cross-analysed {e(d.cross_analysed)}." if d.cross_analysed
               else "Not cross-analysed yet. Relations to other dumps appear here after the next <code>/analyze-dumps</code> run.")
        return f"""<section>
      <div class="section-head"><h2>Related dumps</h2></div>
      <p class="panel empty-line">{msg}</p>
    </section>"""
    when = f" · cross-analysed {e(d.cross_analysed)}" if d.cross_analysed else ""
    layout = "rel-grid" if len(parts) == 2 else "rel-single"
    return f"""<section>
      <div class="section-head"><h2>Related dumps</h2><p>From <code>analysis/relations.yml</code> and <code>groups.yml</code>{when}</p></div>
      <div class="{layout}">{"".join(parts)}</div>
    </section>"""


def fingerprint_panel(d: Dump, root: str) -> str:
    f = d.facts
    rows = []
    if f:
        kind = {"whole-image": "Whole image", "byte-lane": "Byte lane", "word-lane": "Word lane"}.get(str(f.get("kind")), "Unknown")
        bus = f.get("bus") or {}
        if bus.get("width_bits"):
            kind += f" of a {bus['width_bits']}-bit bus"
        if bus.get("stride"):
            kind += f", stride {bus['stride']}"
        rows.append(("Kind", e(kind)))
        if f.get("bit_order") and str(f["bit_order"]).lower() not in ("normal", "unknown"):
            rows.append(("Bit order", e(str(f["bit_order"]))))
        arch = " · ".join(str(x) for x in (f.get("architecture"), f.get("endianness")) if x and str(x) != "unknown")
        if arch:
            rows.append(("Code", e(arch)))
        if f.get("layout"):
            rows.append(("Layout", inline_md(f["layout"])))
        structs = [x for x in (f.get("structures") or []) if isinstance(x, dict)][:3]
        if structs:
            rows.append(("Structures", "<br>".join(f"{inline_md(x.get('type', ''))} at <code>{e(str(x.get('offset', '')))}</code>" for x in structs)))
    sigs = sorted({n for _, n in (d.fp or {}).get("signatures", [])})
    if sigs:
        rows.append(("Signatures", e(", ".join(sigs))))
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    near = "".join(
        f'<li><a href="{o.url(root)}">{e(o.label(o.chip is not d.chip))}</a><span class="bar"><i style="width:{round(sc * 100)}%"></i></span><span class="num">{sc:.2f}</span></li>'
        for o, sc in d.nearest
    )
    near_html = f'<div class="nn"><span class="label">Nearest by fingerprint</span><ol>{near}</ol><p class="fine">A ranking aid for cross-analysis, not a verdict.</p></div>' if near else ""
    return f"""<div class="panel"><header><h3>Fingerprint</h3><span class="label">{d.n}.print.json</span></header>
          {f'<dl class="fp">{dl}</dl>' if dl else ''}{near_html}</div>"""


def wanted_panel(items: list[dict], met: dict[str, str], label: str) -> str:
    if not items:
        return ""
    lis = []
    for w in items:
        wid = str(w.get("id", ""))
        found = met.get(wid)
        sub = f'<span>{found}</span>' if found else (f"<span>{inline_md(w.get('look_for') or w.get('why') or '')}</span>" if (w.get("look_for") or w.get("why")) else "")
        lis.append(f'<li{" class=\"met\"" if found else ""}><strong>{inline_md(w.get("what", wid))}</strong>{sub}</li>')
    return f'<div class="panel"><header><h3>Wanted</h3><span class="label">{e(label)}</span></header><ul class="wanted">{"".join(lis)}</ul></div>'


def dump_wanted(d: Dump, by_ref: dict[str, Dump], root: str) -> str:
    met = {}
    for r in d.relations:
        if not r.current:
            continue
        for fl in r.fulfils:
            if str(fl.get("dump")) == d.ref:
                others = [by_ref[x] for x in r.dumps if x != d.ref and x in by_ref]
                met[str(fl.get("wanted"))] = "Found in " + ", ".join(
                    f'<a href="{o.url(root)}">{e(o.label(o.chip is not d.chip).lower() if o.chip is d.chip else o.label(True))}</a>' for o in others)
    return wanted_panel([w for w in (d.facts.get("wanted") or []) if isinstance(w, dict)], met, f"{d.n}.facts.yml")


# --------------------------------------------------------------------------- views


def dump_table(dumps: list[Dump], root: str, with_chip: bool, with_added: bool = False) -> str:
    rows = []
    for d in dumps:
        s = d.stats
        url = d.url(root)
        title = e(str(d.meta["title"])) if d.meta.get("title") else f'<span class="sub">{auto_tag(s)}</span>'
        summary = f'<span class="summary-line">{e(str(d.meta["summary"]))}</span>' if d.meta.get("summary") else ""
        if d.group:
            summary += (f'<a class="grp-tag" href="{group_url(d.group, root)}">{e(d.group.title)}'
                        f'<span>{e(d.group.position(d.member))}</span></a>')
        rows.append(
            f'<tr class="link" data-href="{url}">'
            f'<td class="dumpno"><a href="{url}">{d.n}</a></td>'
            + (f'<td class="mono">{e(d.chip.part)}</td>' if with_chip else "")
            + (f'<td class="num col-hide">{added_label(d)}</td>' if with_added else "")
            + f"<td>{barcode(d)}</td>"
            f'<td class="num">{s.entropy:.2f}</td>'
            f'<td class="num col-hide">{pct(s.ff)}</td>'
            f'<td class="mono col-hide">{s.crc32}</td>'
            f"<td>{title}{summary}</td>"
            f"<td>{pill(d.status)}</td></tr>"
        )
    chip_th = ("<th>Chip</th>" if with_chip else "") + ('<th class="col-hide">Added</th>' if with_added else "")
    return (
        f'<table><thead><tr><th>#</th>{chip_th}<th>Sector map</th><th>Entropy</th><th class="col-hide">Erased</th>'
        f'<th class="col-hide">CRC32</th><th>Contents</th><th>Write-up</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def groups_meta(c: Chip, groups: list[Group]) -> str:
    k = sum(1 for g in groups if c.name in g.chips)
    return f'<span class="num">{k} group{"s" if k != 1 else ""}</span>' if k else ""


def sort_groups(groups: list[Group]) -> list[Group]:
    return sorted(groups, key=lambda g: (-len(g.members), g.title.lower()))


def home_groups(groups: list[Group], by_ref: dict[str, Dump], root: str) -> str:
    if not groups:
        return ""
    rows = "".join(
        f'<tr class="link" data-href="{group_url(g, root)}"><td><a class="gname" href="{group_url(g, root)}">{e(g.title)}</a></td>'
        f'<td class="mono">{e(group_chips(g, by_ref))}</td><td class="num">{group_counts(g)}</td>'
        f'<td class="col-hide">{e(g.identified_as or "Unidentified")}</td><td>{group_pill(g)}</td></tr>'
        for g in sort_groups(groups)
    )
    return f"""<section id="groups">
      <div class="section-head"><h2>Groups</h2><p>Dumps that came from the same board, bank or chip set. A group can span chip types.</p></div>
      <div class="panel table-scroll"><table><thead><tr><th>Group</th><th>Chips</th><th>Members</th><th class="col-hide">Identified as</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>
    </section>"""


def view_home(chips: list[Chip], groups: list[Group], by_ref: dict[str, Dump]) -> str:
    root = ""
    dumps = [d for c in chips for d in c.dumps]
    done = sum(d.status == "done" for d in dumps)
    total_bytes = sum(d.stats.size for d in dumps)
    latest = sorted(dumps, key=lambda d: (d.added, d.chip.name, d.n), reverse=True)[:LATEST_COUNT]
    latest_note = (
        f"The {len(latest)} most recently added. Chip pages list every dump."
        if len(dumps) > LATEST_COUNT
        else "Newest first"
    )
    rows = []
    for c in chips:
        cd = sum(d.status == "done" for d in c.dumps)
        cw = sum(d.status == "wip" for d in c.dumps)
        rows.append(f"""<a class="chip-row" href="{c.slug}/">
          {chip_svg(c, small=True)}
          <div><h3>{e(c.part)}</h3>
            <div class="meta"><span>{e(str(c.info.get('maker', '')))}</span><span>{e(str(c.info.get('kind', '')))}</span>
            <span class="num">{len(c.dumps)} dumps</span><span class="num">{cd} analysed · {cw} in progress</span>{groups_meta(c, groups)}</div></div>
          <div class="barcodes">{''.join(barcode(d) for d in c.dumps)}</div></a>""")
    body = f"""<div class="stack">
    <section>
      <h1>Chip Dumps</h1>
      <p class="lede">Raw reads of flash and EPROM chips bought from Chinese sellers, sorted by part number. Each image has its own page with a sector map, strings, a hex header and a reverse-engineering write-up.</p>
      <div class="inline-stats">
        <div><strong>{len(chips)}</strong><span class="label">Chip {'type' if len(chips) == 1 else 'types'}</span></div>
        <div><strong>{len(dumps)}</strong><span class="label">Dumps</span></div>
        <div><strong>{size_label(total_bytes)}</strong><span class="label">Raw data</span></div>
        <div><strong>{done} / {len(dumps)}</strong><span class="label">Analysed</span></div>
        <div><strong>{len(groups)}</strong><span class="label">Groups</span></div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Chips</h2><p>Each folder in <code>dumps/</code> becomes a chip page</p></div>
      <div class="panel">{''.join(rows)}</div>
    </section>
    {home_groups(groups, by_ref, root)}
    <section>
      <div class="section-head"><h2>Latest dumps</h2><p>{latest_note}</p></div>
      <div class="panel table-scroll">{dump_table(latest, root, True, with_added=True)}</div>
      {legend()}
    </section>
  </div>"""
    return page("Chip Dumps", root, "home", body)


def chip_groups(c: Chip, groups: list[Group], by_ref: dict[str, Dump], root: str) -> str:
    mine = sort_groups([g for g in groups if c.name in g.chips])
    analysed = sum(1 for d in c.dumps if d.status == "done" and d.facts)
    crossed = sum(1 for d in c.dumps if d.cross_analysed)
    multi = [g for g in mine if len(g.members) >= 2]
    pending = [g for g in multi if not g.up_to_date]
    if not multi:
        gstate, gtext = "", "No group has two members yet"
    elif pending:
        gstate, gtext = "", f"{len(pending)} of {len(multi)} groups pending"
    else:
        gstate, gtext = "ok", f"Up to date · {max((str(g.meta.get('updated', '')) for g in multi), default='')}"
    n = len(c.dumps)
    strip = f"""<div class="pipeline panel" role="list">
        <div role="listitem"><span class="dot{' ok' if analysed == n else ''}"></span><div><strong>Analysed</strong><span>{analysed} of {n} dumps</span></div></div>
        <div role="listitem"><span class="dot{' ok' if crossed == n else ''}"></span><div><strong>Cross-analysed</strong><span>{crossed} of {n} dumps</span></div></div>
        <div role="listitem"><span class="dot {gstate}"></span><div><strong>Group analysis</strong><span>{e(gtext)}</span></div></div>
        <p class="gate">Group analysis runs only once every dump of this chip is analysed and cross-analysed, and only for groups whose members changed. A group with one dump waits for a partner before it gets a group write-up.</p>
      </div>"""
    cards = f'<div class="group-cards">{"".join(group_card(g, by_ref, root) for g in mine)}</div>' if mine else ""
    loose = [d for d in c.dumps if not d.group]
    loose_html = ""
    if loose:
        items = []
        for d in loose:
            title = e(str(d.meta.get("title"))) if d.meta.get("title") else auto_tag(d.stats)
            cur = [r for r in d.relations if r.current]
            why = f"{len(cur)} relation{'s' if len(cur) != 1 else ''} to other dumps" if cur else (
                "No related dumps" if d.cross_analysed else "Not cross-analysed yet")
            items.append(f'<li><a href="{d.url(root)}">{d.n}</a><div><strong>{title}</strong><span>{why}</span></div></li>')
        loose_html = f"""<div class="panel ungrouped">
        <header><h3>Not in a group</h3><span class="label">{len(loose)} dump{'s' if len(loose) != 1 else ''}</span></header>
        <ul>{"".join(items)}</ul>
      </div>"""
    return f"""<section>
      <div class="section-head"><h2>Groups</h2><p>From <code>analysis/groups.yml</code></p></div>
      {strip}{cards}{loose_html}
    </section>"""


def view_chip(c: Chip, groups: list[Group], by_ref: dict[str, Dump]) -> str:
    root = "../"
    specs = c.info.get("specs") or {}
    spec_html = "".join(f"<dt>{e(str(k))}</dt><dd>{e(str(v))}</dd>" for k, v in specs.items())
    lede = e(str(c.info.get("description", ""))) or f"{len(c.dumps)} dumps of this chip so far."
    notes = chip_groups(c, groups, by_ref, root)
    body = f"""<div class="stack">
    <section>
      <nav class="crumbs" aria-label="Breadcrumb"><a href="{root}">Chips</a><span>/</span><span>{e(c.part)}</span></nav>
      <div class="chip-head">
        <div>
          <span class="label">{e(str(c.info.get('kind', 'Chip')))}</span>
          <h1>{e(c.part)}</h1>
          <p class="lede">{lede}</p>
          <dl class="specs">{spec_html}</dl>
        </div>
        <div class="panel pkg">{chip_svg(c)}<p>{e(str(c.info.get('maker', '')))}</p></div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Dumps</h2><p>Sector map: one column per {size_label(c.dumps[0].stats.column_size)} {column_word(c.dumps[0])}</p></div>
      <div class="panel table-scroll">{dump_table(c.dumps, root, False)}</div>
      {legend()}
    </section>
    {notes}
  </div>"""
    return page(f"{c.part} · Chip Dumps", root, "chip", body, f"{len(c.dumps)} dumps of the {c.part}.")


def hex_view(data: bytes) -> str:
    lines = []
    for o in range(0, len(data), 16):
        row = data[o : o + 16]
        parts = []
        for i, b in enumerate(row):
            s = f"{b:02x}"
            cls = "d" if b in (0, 255) else ("t" if 32 <= b < 127 else "")
            parts.append((" " if i == 8 else "") + (f'<span class="{cls}">{s}</span>' if cls else s))
        asc = "".join(e(chr(b)) if 32 <= b < 127 else '<span class="d">.</span>' for b in row)
        lines.append(f'<span class="o">{o:06x}</span>  {" ".join(parts)}  {asc}')
    return "\n".join(lines)


def sector_map(d: Dump) -> str:
    s = d.stats
    cols = len(s.columns)
    step = 4 if cols >= 16 else 1
    out = [f'<div class="smap" style="grid-template-columns: 44px repeat({cols}, minmax(9px, 1fr))"><span></span>']
    out += [f'<span class="collab">{c if c % step == 0 else ""}</span>' for c in range(cols)]
    block = s.column_size // len(s.grid)
    for r, row in enumerate(s.grid):
        label = f"+{r * block // 1024}K" if block >= 1024 else f"+{r * block:x}"
        out.append(f'<span class="rowlab">{label}</span>')
        for c, cell in enumerate(row):
            off = c * s.column_size + r * block
            out.append(f'<span class="cell" style="background:{heat(cell)}" title="0x{off:06X} · column {c} · entropy {cell.entropy:.2f}"></span>')
    out.append("</div>")
    return "".join(out)


def writeup(d: Dump) -> str:
    rel = f"analysis/{d.chip.name}/{d.n}.md"
    if not d.meta:
        return f"""<article class="panel empty">
      <span class="pill todo" style="align-self:flex-start">Not started</span>
      <h2>No write-up yet</h2>
      <p>Run <code>/analyze-dumps</code> in Claude Code to analyse this dump. The notes go in <code>{e(rel)}</code> and appear here on the next build.</p>
    </article>"""
    m = d.meta
    bits = [pill(d.status)]
    if m.get("updated"):
        bits.append(f"<span>Updated {e(str(m['updated']))}</span>")
    if m.get("model"):
        bits.append(f"<span>{e(str(m['model']))}</span>")
    bits.append(f"<span>{e(rel)}</span>")
    extra = ""
    if d.unreferenced:
        figs = "".join(figure_html(f"images/{i.name}", i.caption) for i in d.unreferenced)
        extra = f"<h2>More images</h2>{figs}"
    return f'<article class="panel writeup"><div class="wmeta">{"".join(bits)}</div><div class="prose">{d.body_html}{extra}</div></article>'


def figure_html(src: str, caption: str) -> str:
    cap = e(caption)
    return (f'<figure class="inline-fig"><a class="inline-shot" href="{e(src)}" data-lightbox data-caption="{cap}">'
            f'<img alt="{cap}" src="{e(src)}" loading="lazy"></a><figcaption>{cap}</figcaption></figure>')


def view_dump(d: Dump, prev: Dump | None, nxt: Dump | None, by_ref: dict[str, Dump]) -> str:
    root = "../../"
    s = d.stats
    c = d.chip
    tags = d.meta.get("tags") or []
    tag_html = f'<p>{" ".join(f"<code>{e(str(t))}</code>" for t in tags)}</p>' if tags else ""
    tagline = e(str(d.meta.get("title"))) if d.meta.get("title") else auto_tag(s)
    shown = s.strings[:SIDEBAR_STRINGS]
    if shown:
        items = "".join(f"<li><span>{o:06x}</span><span>{e(t[:96])}</span></li>" for o, t in shown)
        more = f'<a class="strings-more" href="strings.txt">All {len(s.strings)} strings</a>' if len(s.strings) > len(shown) else ""
        strings_html = f'<ul class="strings">{items}</ul>{more}'
    else:
        strings_html = '<p class="none">No readable strings of 10+ characters.</p>'
    pager = (
        (f'<a class="btn" href="../{prev.n}/">← Dump {prev.n}</a>' if prev else "<span></span>")
        + (f'<a class="btn" href="../{nxt.n}/">Dump {nxt.n} →</a>' if nxt else "<span></span>")
    )
    body = f"""<div class="stack">
    <section>
      <nav class="crumbs" aria-label="Breadcrumb"><a href="{root}">Chips</a><span>/</span><a href="../">{e(c.part)}</a><span>/</span><span>Dump {d.n}</span></nav>
      <div class="dump-head">
        <div>
          <h1><small>{e(c.part)}</small>Dump {d.n}</h1>
          <p class="tagline">{tagline}</p>
        </div>
        <div class="actions">
          {pill(d.status)}
          <a class="btn primary" href="../{d.n}.bin" download>Download {d.n}.bin</a>
          <button class="btn" type="button" data-copy="{s.sha256}">Copy SHA-256</button>
        </div>
      </div>
    </section>
    <section class="panel facts">
      <div><span class="label">Size</span><div class="v big num">{size_label(s.size)}</div></div>
      <div><span class="label">Entropy</span><div class="v big num">{s.entropy:.2f}</div></div>
      <div><span class="label">Erased (FFh)</span><div class="v big num">{pct(s.ff)}</div></div>
      <div><span class="label">Zero bytes</span><div class="v big num">{pct(s.zero)}</div></div>
      <div><span class="label">CRC32</span><div class="v">{s.crc32}</div></div>
      <div><span class="label">SHA-256</span><div class="v" title="{s.sha256}">{s.sha256[:16]}…</div></div>
    </section>
    <section class="panel smap-wrap">
      <div class="section-head"><h3>Sector map</h3><p>Columns are {size_label(s.column_size)} {column_word(d)}s. Rows are {size_label(s.column_size // len(s.grid))} blocks within each {column_word(d)}.</p></div>
      <div class="smap-scroll">{sector_map(d)}</div>
      {legend()}
    </section>
    {related_section(d, by_ref, root)}
    <section class="dump-body">
      <div>
        <div class="section-head"><h2>Write-up</h2>{tag_html}</div>
        {writeup(d)}
      </div>
      <aside class="side">
        {fingerprint_panel(d, root)}
        {dump_wanted(d, by_ref, root)}
        <div class="panel"><header><h3>Strings</h3><span class="label num">{len(s.strings)} found</span></header>{strings_html}</div>
        <div class="panel"><header><h3>Header</h3><span class="label">0x000–0x{len(s.head) - 1:03X}</span></header>
          <div class="hex"><pre>{hex_view(s.head)}</pre></div></div>
      </aside>
    </section>
    <nav class="pager" aria-label="Other dumps">{pager}</nav>
  </div>"""
    desc = str(d.meta.get("summary") or f"Dump {d.n} of the {c.part}.")
    return page(f"{c.part} dump {d.n} · Chip Dumps", root, "chip", body, desc)


def bank_map(g: Group, by_ref: dict[str, Dump], root: str) -> str:
    """One row per lane slot (or chip), one cell per sector, coloured like the dump sector maps."""
    multi_chip = len(g.chips) > 1
    rows = []

    def row(label: str, sub: str, d: Dump | None) -> str:
        if d:
            cells = "".join(f'<i style="background:{heat(c)}"></i>' for c in d.stats.columns)
            who = f'<a href="{d.url(root)}">{e(d.label(multi_chip))}</a>'
            n = len(d.stats.columns)
        else:
            n = max((len(by_ref[m.dump].stats.columns) for m in g.members), default=32)
            cells = '<i class="missing"></i>' * n
            who = '<span class="miss">not dumped</span>'
        return (f'<div class="bm-row"><span class="bm-lane">{label}<small>{sub}</small></span><span class="bm-dump">{who}</span>'
                f'<div class="bm-cells" style="grid-template-columns: repeat({n}, minmax(0, 1fr))">{cells}</div></div>')

    if g.kind == "lanes" and g.lanes:
        banks: list[int | None] = list(range(g.banks)) if g.banks else []
        if not banks or any(m.bank is None for m in g.members):
            banks.append(None)
        for b in banks:
            for lane in range(g.lanes):
                m = next((m for m in g.members if m.bank == b and m.lane == lane), None)
                if b is None and m is None and g.banks:
                    continue  # unknown-bank row only lists members that are in it
                prefix = "" if len(banks) == 1 else (f"Bank {b} · " if b is not None else "Bank ? · ")
                rows.append(row(f"{prefix}Lane {lane}", g.lane_bits_label(lane), by_ref[m.dump] if m else None))
        for m in g.members:
            if m.lane is None:
                rows.append(row("Lane ?", "position unknown", by_ref[m.dump]))
    else:
        for i, m in enumerate(g.members):
            rows.append(row(f"Chip {i + 1}", "", by_ref[m.dump]))
        missing = (g.expected_members or len(g.members) + 1) - len(g.members)
        for i in range(max(0, missing)):
            rows.append(row("Other chip" if not g.expected_members else f"Chip {len(g.members) + i + 1}", "", None))
    return "".join(rows)


def view_group(g: Group, by_ref: dict[str, Dump], rels: list[Relation]) -> str:
    root = "../../"
    multi_chip = len(g.chips) > 1
    pc, plabel = group_state(g)
    facts = [("Members", e(group_counts(g)))] + [(e(k), e(v)) for k, v in list(g.facts.items())[:4]]
    ident = e(g.identified_as) + (f" · {e(g.confidence)}" if g.confidence else "") if g.identified_as else "Unidentified"
    facts.append(("Identification", ident))
    facts_html = "".join(
        f'<div><span class="label">{k}</span><div class="v{" big" if len(v) <= 14 else ""}">{v}</div></div>' for k, v in facts
    )

    rel = f"analysis/groups/{g.slug}.md"
    images = load_images(GROUPS_DIR / g.slug / "images")
    if g.meta:
        body_html = render_markdown(g.body, {i.name: i.caption for i in images})
        for i in referenced_images(body_html, images):
            body_html += figure_html(f"images/{i.name}", i.caption)
        bits = [f'<span class="pill {"done" if g.meta.get("status") == "done" else "wip"}">{"Analysed" if g.meta.get("status") == "done" else "In progress"}</span>']
        if g.meta.get("updated"):
            bits.append(f"<span>Updated {e(str(g.meta['updated']))}</span>")
        if g.meta.get("model"):
            bits.append(f"<span>{e(str(g.meta['model']))}</span>")
        bits.append(f"<span>{e(rel)}</span>")
        stale = ""
        if not g.up_to_date:
            added = [r for r in g.refs if r not in g.analysed_members]
            gone = [r for r in g.analysed_members if r not in g.refs]
            change = "; ".join(x for x in (
                ("since joined by " + ", ".join(added)) if added else "",
                ("no longer includes " + ", ".join(gone)) if gone else "") if x)
            stale = f'<p class="callout-line">This write-up predates the current membership ({e(change)}). It is rewritten on the next group analysis.</p>'
        writeup_html = f'{stale}<article class="panel writeup"><div class="wmeta">{"".join(bits)}</div><div class="prose">{body_html}</div></article>'
    else:
        if len(g.members) < 2:
            msg = "This group has one dump so far. Its group write-up is written once a partner turns up and every dump of the chip is cross-analysed. Until then, the Wanted list says what to look for."
        else:
            msg = f"Group analysis runs once every dump of {e(', '.join(g.chips))} is analysed and cross-analysed. The member write-ups cover each dump on its own."
        writeup_html = f"""<article class="panel empty"><span class="pill {pc}" style="align-self:flex-start">{plabel}</span>
      <h2>No group write-up yet</h2><p>{msg}</p></article>"""

    members = []
    for m in g.members:
        d = by_ref[m.dump]
        members.append(f'<li><a href="{d.url(root)}">{e(d.label(multi_chip))}</a><span>{e(g.position(m).capitalize())}</span>{barcode(d)}</li>')
    if g.kind == "lanes" and g.lanes:
        banks = range(g.banks) if g.banks else [None]
        for b in banks:
            for lane in range(g.lanes):
                if not any(m.bank == b and m.lane == lane for m in g.members):
                    pos = (f"Bank {b} · lane {lane}" if b is not None and g.banks and g.banks > 1 else f"Lane {lane}")
                    members.append(f'<li class="missing"><span>Not dumped</span><span>{pos} · {g.lane_bits_label(lane)}</span><span class="barcode ghost"></span></li>')

    refs = set(g.refs)
    evidence = [r for r in rels if r.current and len(set(r.dumps) & refs) >= 2]
    ev_html = "".join(
        f'<li><span class="kind">{e(r.kind_label)}</span>{conf_pill(r.confidence)}<p>{inline_md(r.summary)}</p></li>' for r in sort_relations(evidence)
    )
    run = ""
    if g.meta:
        covered = ", ".join(g.analysed_members) or "not recorded"
        run = f"""<div class="panel"><header><h3>Group analysis run</h3><span class="label">{e(str(g.meta.get('updated', '')))}</span></header>
          <dl class="fp"><dt>Covered</dt><dd>{e(covered)}</dd><dt>Model</dt><dd>{e(str(g.meta.get('model', '')))}</dd>
          <dt>Next run</dt><dd>When a member joins or leaves, once every dump of {e(', '.join(g.chips))} is cross-analysed again</dd></dl></div>"""

    body = f"""<div class="stack">
    <section>
      <nav class="crumbs" aria-label="Breadcrumb"><a href="{root}">Chips</a><span>/</span><a href="{root}#groups">Groups</a><span>/</span><span>{e(g.title)}</span></nav>
      <div class="dump-head">
        <div>
          <h1><small>Group · {e(group_chips(g, by_ref))}</small>{e(g.title)}</h1>
          <p class="tagline">{inline_md(str(g.meta.get("summary") or g.summary))}</p>
        </div>
        <div class="actions">{group_pill(g)}<span class="pill {pc}">{plabel}</span></div>
      </div>
    </section>
    <section class="panel facts" style="grid-template-columns: repeat({len(facts)}, minmax(0, 1fr))">{facts_html}</section>
    <section class="panel smap-wrap">
      <div class="section-head"><h3>{"Bank map" if g.kind == "lanes" else "Chip map"}</h3><p>One row per {"byte lane" if g.kind == "lanes" else "chip"}, one column per sector, coloured by entropy. Hatched rows were not dumped.</p></div>
      <div class="smap-scroll"><div class="bankmap">{bank_map(g, by_ref, root)}</div></div>
      <div class="legend"><span><i style="background:var(--erased)"></i>Erased (FFh)</span><span><i style="background:var(--zero)"></i>Zero-filled</span><span>Entropy 0 <span class="ramp"></span> 8 bits/byte</span><span><i class="missing-key"></i>Not dumped</span></div>
    </section>
    <section class="dump-body">
      <div>
        <div class="section-head"><h2>Group write-up</h2>{f'<p>{" ".join(f"<code>{e(str(t))}</code>" for t in (g.meta.get("tags") or []))}</p>' if g.meta.get("tags") else ""}</div>
        {writeup_html}
      </div>
      <aside class="side">
        <div class="panel"><header><h3>Members</h3><span class="label">{e(group_counts(g))}</span></header><ul class="members">{"".join(members)}</ul></div>
        {f'<div class="panel"><header><h3>Membership evidence</h3><span class="label">relations.yml</span></header><ul class="evidence">{ev_html}</ul></div>' if ev_html else ""}
        {wanted_panel(g.wanted, {}, "groups.yml")}
        {run}
      </aside>
    </section>
  </div>"""
    return page(f"{g.title} · Chip Dumps", root, "home", body, g.summary or g.title)


def view_about() -> str:
    root = "../"
    body = """<div class="stack">
    <section>
      <h1>How it works</h1>
      <p class="lede">The site is generated from the repository. Dumps and write-ups are plain files; a GitHub Action builds these pages and publishes them to GitHub Pages on every push to main.</p>
    </section>
    <section class="how">
      <div>
        <div class="section-head"><h2>Repository layout</h2></div>
<pre class="code-block">dumps/
  inventory.yml     <span style="color:var(--muted)"># every dump, its hash, where it came from</span>
  MBM29F016A/
    chip.yml        <span style="color:var(--muted)"># part, maker, package, specs</span>
    1.bin
analysis/
  MBM29F016A/
    1.md            <span style="color:var(--muted)"># isolated write-up</span>
    1.facts.yml     <span style="color:var(--muted)"># facts for cross-analysis</span>
    1.print.json    <span style="color:var(--muted)"># computed fingerprint</span>
  relations.yml     <span style="color:var(--muted)"># how dumps relate</span>
  groups.yml        <span style="color:var(--muted)"># boards, banks and chip sets</span>
  groups/
    &lt;group&gt;.md      <span style="color:var(--muted)"># combined group write-up</span>
site/               <span style="color:var(--muted)"># generator and pipeline tools</span>
.claude/            <span style="color:var(--muted)"># /analyze-dumps and its agents</span></pre>
      </div>
      <div>
        <div class="section-head"><h2>Adding a dump</h2></div>
        <ol>
          <li><strong>Copy</strong> the image to <code>dumps/&lt;PART&gt;/&lt;N&gt;.bin</code>, using the next free number.</li>
          <li><strong>Run</strong> <code>/analyze-dumps</code> in Claude Code. Each new image is reverse-engineered on its own, without looking at other dumps, and gets a write-up, a facts file and a fingerprint.</li>
          <li><strong>Cross-analysis</strong> then compares the new dumps with the whole collection, from the facts and fingerprints plus targeted byte reads, and records relations and groups.</li>
          <li><strong>Group analysis</strong> combines the dumps of a group (interleaving lanes, following data across banks). It runs only when every dump of the chip has been analysed and cross-analysed, and the group's members changed.</li>
          <li><strong>Push.</strong> The build computes hashes, entropy per block, erased and zero ratios and strings, then renders every page.</li>
        </ol>
      </div>
    </section>
  </div>"""
    return page("How it works · Chip Dumps", root, "about", body)


# --------------------------------------------------------------------------- main


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "_site"))
    args = ap.parse_args()
    out = Path(args.out).resolve()

    print("Reading dumps", file=sys.stderr)
    chips = load_chips()
    groups, rels = link_graph(chips)
    by_ref = {d.ref: d for c in chips for d in c.dumps}
    slugs = [c.slug for c in chips]
    clash = {s for s in slugs if slugs.count(s) > 1 or s in ("about", "assets", "groups")}
    if clash:
        raise SystemExit(f"Chip folder names collide after lower-casing: {', '.join(sorted(clash))}")

    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for f in STATIC.iterdir():
        shutil.copy2(f, out / "assets" / f.name)
    (out / ".nojekyll").touch()

    write(out / "index.html", view_home(chips, groups, by_ref))
    write(out / "about" / "index.html", view_about())
    for c in chips:
        write(out / c.slug / "index.html", view_chip(c, groups, by_ref))
        for i, d in enumerate(c.dumps):
            prev = c.dumps[i - 1] if i > 0 else None
            nxt = c.dumps[i + 1] if i + 1 < len(c.dumps) else None
            write(out / c.slug / str(d.n) / "index.html", view_dump(d, prev, nxt, by_ref))
            write(out / c.slug / str(d.n) / "strings.txt", "".join(f"{o:08x}  {t}\n" for o, t in d.stats.strings))
            shutil.copy2(d.stats.path, out / c.slug / f"{d.n}.bin")
            if d.images:
                (out / c.slug / str(d.n) / "images").mkdir(exist_ok=True)
                for img in d.images:
                    shutil.copy2(img.path, out / c.slug / str(d.n) / "images" / img.name)

    for g in groups:
        write(out / "groups" / g.slug / "index.html", view_group(g, by_ref, rels))
        for img in load_images(GROUPS_DIR / g.slug / "images"):
            (out / "groups" / g.slug / "images").mkdir(parents=True, exist_ok=True)
            shutil.copy2(img.path, out / "groups" / g.slug / "images" / img.name)

    n = sum(len(c.dumps) for c in chips)
    print(f"Built {len(chips)} chip pages, {n} dump pages and {len(groups)} group pages in {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
