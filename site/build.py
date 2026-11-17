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

STATIC = Path(__file__).resolve().parent / "static"
FONTS = (
    "https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700"
    "&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
)
SIDEBAR_STRINGS = 12
LATEST_COUNT = 10
e = html.escape


# --------------------------------------------------------------------------- data


@dataclass
class Dump:
    chip: "Chip"
    stats: DumpStats
    meta: dict = field(default_factory=dict)
    body_html: str = ""
    added: str = ""  # ISO timestamp from dumps/inventory.yml
    images: list["Image"] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.stats.number

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
    notes_html: str = ""

    @property
    def part(self) -> str:
        return str(self.info.get("part") or self.name)


def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    # Analysis text quotes bytes from untrusted dumps, so raw HTML is escaped, never passed through.
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    out = md.convert(text)
    out = re.sub(r'(href|src)="\s*(?:javascript|data|vbscript):[^"]*"', r'\1="#"', out, flags=re.I)
    # Inline images open in the lightbox, captioned with their alt text.
    out = re.sub(
        r'<img alt="([^"]*)" src="([^"]+)"\s*/?>',
        r'<a class="inline-shot" href="\2" data-lightbox data-caption="\1"><img alt="\1" src="\2" loading="lazy"></a>',
        out,
    )
    return out.replace("<table>", '<div class="table-scroll"><table>').replace("</table>", "</table></div>")


def load_added() -> dict[tuple[str, int], str]:
    if not INVENTORY.exists():
        return {}
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8")) or {}
    out = {}
    for chip, entry in (data.get("chips") or {}).items():
        for n, d in ((entry or {}).get("dumps") or {}).items():
            if d and d.get("added"):
                out[(chip, int(n))] = str(d["added"]).replace(" ", "T")
    return out


def load_chips() -> list[Chip]:
    added = load_added()
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
            # Dumps not yet in the inventory are the newest by definition.
            dump.added = added.get((d.name, n), "9999")
            ap = analysis_path(d.name, n)
            if ap.exists():
                meta, body = read_front_matter(ap)
                dump.meta = meta or {"status": "in-progress"}
                dump.body_html = render_markdown(body)
            dump.images = load_images(ANALYSIS_DIR / d.name / str(n) / "images")
            chip.dumps.append(dump)
        notes = ANALYSIS_DIR / d.name / "index.md"
        if notes.exists():
            chip.notes_html = render_markdown(read_front_matter(notes)[1])
        chips.append(chip)
    return chips


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


# --------------------------------------------------------------------------- views


def dump_table(dumps: list[Dump], root: str, with_chip: bool, with_added: bool = False) -> str:
    rows = []
    for d in dumps:
        s = d.stats
        url = d.url(root)
        title = e(str(d.meta["title"])) if d.meta.get("title") else f'<span class="sub">{auto_tag(s)}</span>'
        summary = f'<span class="summary-line">{e(str(d.meta["summary"]))}</span>' if d.meta.get("summary") else ""
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


def view_home(chips: list[Chip]) -> str:
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
            <span class="num">{len(c.dumps)} dumps</span><span class="num">{cd} analysed · {cw} in progress</span></div></div>
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
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Chips</h2><p>Each folder in <code>dumps/</code> becomes a chip page</p></div>
      <div class="panel">{''.join(rows)}</div>
    </section>
    <section>
      <div class="section-head"><h2>Latest dumps</h2><p>{latest_note}</p></div>
      <div class="panel table-scroll">{dump_table(latest, root, True, with_added=True)}</div>
      {legend()}
    </section>
  </div>"""
    return page("Chip Dumps", root, "home", body)


def view_chip(c: Chip) -> str:
    root = "../"
    specs = c.info.get("specs") or {}
    spec_html = "".join(f"<dt>{e(str(k))}</dt><dd>{e(str(v))}</dd>" for k, v in specs.items())
    lede = e(str(c.info.get("description", ""))) or f"{len(c.dumps)} dumps of this chip so far."
    notes = (
        f'<section><div class="section-head"><h2>Notes across dumps</h2><p><code>analysis/{e(c.name)}/index.md</code></p></div>'
        f'<div class="panel chip-notes prose">{c.notes_html}</div></section>'
        if c.notes_html
        else ""
    )
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
    return f'<article class="panel writeup"><div class="wmeta">{"".join(bits)}</div><div class="prose">{d.body_html}</div></article>'


def gallery(d: Dump) -> str:
    if not d.images:
        return ""
    items = []
    for img in d.images:
        src = f"images/{e(img.name)}"
        dims = f' width="{img.width}" height="{img.height}"' if img.width else ""
        items.append(
            f'<figure><a href="{src}" data-lightbox data-caption="{e(img.caption)}">'
            f'<img src="{src}" alt="{e(img.caption)}" loading="lazy"{dims}></a>'
            f"<figcaption>{e(img.caption)}</figcaption></figure>"
        )
    count = f"{len(d.images)} image{'s' if len(d.images) != 1 else ''}"
    return f"""<section>
      <div class="section-head"><h2>Extracted images</h2><p>{count} rendered from the dump. Select one to enlarge.</p></div>
      <div class="gallery">{''.join(items)}</div>
    </section>"""


def view_dump(d: Dump, prev: Dump | None, nxt: Dump | None) -> str:
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
    {gallery(d)}
    <section class="dump-body">
      <div>
        <div class="section-head"><h2>Write-up</h2>{tag_html}</div>
        {writeup(d)}
      </div>
      <aside class="side">
        <div class="panel"><header><h3>Strings</h3><span class="label num">{len(s.strings)} found</span></header>{strings_html}</div>
        <div class="panel"><header><h3>Header</h3><span class="label">0x000–0x{len(s.head) - 1:03X}</span></header>
          <div class="hex"><pre>{hex_view(s.head)}</pre></div></div>
      </aside>
    </section>
    <nav class="pager" aria-label="Other dumps">{pager}</nav>
  </div>"""
    desc = str(d.meta.get("summary") or f"Dump {d.n} of the {c.part}.")
    return page(f"{c.part} dump {d.n} · Chip Dumps", root, "chip", body, desc)


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
  inventory.yml     <span style="color:var(--muted)"># every dump, its hash and where it came from</span>
  MBM29F016/
    chip.yml        <span style="color:var(--muted)"># part, maker, package, specs</span>
    1.bin
    2.bin
analysis/
  MBM29F016/
    index.md        <span style="color:var(--muted)"># notes across dumps (optional)</span>
    1.md            <span style="color:var(--muted)"># write-up with front matter</span>
site/               <span style="color:var(--muted)"># generator, styles, inventory tool</span>
.claude/skills/analyze-dumps/</pre>
      </div>
      <div>
        <div class="section-head"><h2>Adding a dump</h2></div>
        <ol>
          <li><strong>Copy</strong> the image to <code>dumps/&lt;PART&gt;/&lt;N&gt;.bin</code>, using the next free number.</li>
          <li><strong>Run</strong> <code>/analyze-dumps</code> in Claude Code. It compares the folders with the inventory, sends one sub-agent to reverse-engineer each new image, and writes <code>analysis/&lt;PART&gt;/&lt;N&gt;.md</code>.</li>
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
    slugs = [c.slug for c in chips]
    clash = {s for s in slugs if slugs.count(s) > 1 or s in ("about", "assets")}
    if clash:
        raise SystemExit(f"Chip folder names collide after lower-casing: {', '.join(sorted(clash))}")

    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for f in STATIC.iterdir():
        shutil.copy2(f, out / "assets" / f.name)
    (out / ".nojekyll").touch()

    write(out / "index.html", view_home(chips))
    write(out / "about" / "index.html", view_about())
    for c in chips:
        write(out / c.slug / "index.html", view_chip(c))
        for i, d in enumerate(c.dumps):
            prev = c.dumps[i - 1] if i > 0 else None
            nxt = c.dumps[i + 1] if i + 1 < len(c.dumps) else None
            write(out / c.slug / str(d.n) / "index.html", view_dump(d, prev, nxt))
            write(out / c.slug / str(d.n) / "strings.txt", "".join(f"{o:08x}  {t}\n" for o, t in d.stats.strings))
            shutil.copy2(d.stats.path, out / c.slug / f"{d.n}.bin")
            if d.images:
                (out / c.slug / str(d.n) / "images").mkdir(exist_ok=True)
                for img in d.images:
                    shutil.copy2(img.path, out / c.slug / str(d.n) / "images" / img.name)

    n = sum(len(c.dumps) for c in chips)
    print(f"Built {len(chips)} chip pages and {n} dump pages in {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
