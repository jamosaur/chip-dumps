"""Shared helpers: find dumps on disk, hash them and compute the stats the site shows."""

from __future__ import annotations

import collections
import hashlib
import math
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMPS_DIR = ROOT / "dumps"
ANALYSIS_DIR = ROOT / "analysis"
INVENTORY = DUMPS_DIR / "inventory.yml"
RELATIONS = ANALYSIS_DIR / "relations.yml"  # cross-dump relations, written by the cross-analyst
GROUPS_FILE = ANALYSIS_DIR / "groups.yml"  # group membership, written by the cross-analyst
GROUPS_DIR = ANALYSIS_DIR / "groups"  # group write-ups, written by the group-analyst

DUMP_NAME = re.compile(r"^(\d+)\.bin$")
STRING_RE = re.compile(rb"[\x20-\x7e]{10,}")


def slugify(chip: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", chip.lower()).strip("-")


def chip_dirs() -> list[Path]:
    if not DUMPS_DIR.is_dir():
        return []
    return sorted((p for p in DUMPS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name.lower())


def dump_files(chip_dir: Path) -> list[tuple[int, Path]]:
    out = []
    for p in chip_dir.iterdir():
        m = DUMP_NAME.match(p.name)
        if m and p.is_file():
            out.append((int(m.group(1)), p))
    return sorted(out)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def entropy(counts: collections.Counter, n: int) -> float:
    if not n:
        return 0.0
    return -sum(v / n * math.log2(v / n) for v in counts.values())


def interesting_strings(data: bytes, limit: int = 5000) -> list[tuple[int, str]]:
    """Printable runs of 10+ chars that look like words rather than byte noise."""
    out = []
    for m in STRING_RE.finditer(data):
        s = m.group().decode("ascii")
        alpha = sum(c.isalpha() for c in s) / len(s)
        wordy = sum(c.isalpha() or c in " ._-()/=:,%" for c in s) / len(s)
        if (alpha > 0.7 and " " in s) or (re.search(r"[A-Za-z]{4,}", s) and wordy > 0.85):
            out.append((m.start(), s))
            if len(out) >= limit:
                break
    return out


@dataclass
class Cell:
    entropy: float
    ff: float
    zero: float


@dataclass
class DumpStats:
    number: int
    path: Path
    size: int
    sha256: str
    md5: str
    crc32: str
    entropy: float
    ff: float
    zero: float
    columns: list[Cell] = field(default_factory=list)  # one per sector (or slice)
    grid: list[list[Cell]] = field(default_factory=list)  # [row][column]
    column_size: int = 0
    head: bytes = b""
    strings: list[tuple[int, str]] = field(default_factory=list)


def read_front_matter(path: Path) -> tuple[dict, str]:
    """Split a Markdown file into (YAML front matter, body). Missing front matter gives {}."""
    import yaml

    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            meta = yaml.safe_load(parts[0][3:]) or {}
            body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
            return (meta if isinstance(meta, dict) else {}), body
    return {}, text


def analysis_path(chip: str, number: int) -> Path:
    return ANALYSIS_DIR / chip / f"{number}.md"


def facts_path(chip: str, number: int) -> Path:
    """Structured facts the dump-analyst extracted from this dump alone."""
    return ANALYSIS_DIR / chip / f"{number}.facts.yml"


def print_path(chip: str, number: int) -> Path:
    """Fingerprint computed by site/fingerprint.py."""
    return ANALYSIS_DIR / chip / f"{number}.print.json"


def parse_ref(ref: str) -> tuple[str, int]:
    """'MBM29F016A/7' -> ('MBM29F016A', 7)."""
    chip, _, num = str(ref).partition("/")
    if not chip or not num.isdigit():
        raise ValueError(f"Not a dump reference: {ref!r}. Use CHIP/N, for example MBM29F016A/7.")
    return chip, int(num)


def all_dumps() -> list[tuple[str, int, Path]]:
    """Every dump on disk as (chip folder, number, path)."""
    return [(d.name, n, p) for d in chip_dirs() for n, p in dump_files(d)]


GRID_ROWS = 8
MAX_COLUMNS = 64


def compute_stats(number: int, path: Path, sector_size: int | None = None) -> DumpStats:
    data = path.read_bytes()
    n = len(data)
    counts = collections.Counter(data)

    if sector_size and n % sector_size == 0 and 0 < n // sector_size <= MAX_COLUMNS:
        cols = n // sector_size
    else:
        cols = 32 if n >= 32 * GRID_ROWS else 1
    col_size = max(1, n // cols)
    block = max(1, col_size // GRID_ROWS)

    grid: list[list[Cell]] = [[] for _ in range(GRID_ROWS)]
    columns: list[Cell] = []
    for c in range(cols):
        col_counts: collections.Counter = collections.Counter()
        col_n = 0
        for r in range(GRID_ROWS):
            chunk = data[c * col_size + r * block : c * col_size + (r + 1) * block]
            bc = collections.Counter(chunk)
            col_counts.update(bc)
            col_n += len(chunk)
            ln = len(chunk) or 1
            grid[r].append(Cell(entropy(bc, len(chunk)), bc[0xFF] / ln, bc[0] / ln))
        ln = col_n or 1
        columns.append(Cell(entropy(col_counts, col_n), col_counts[0xFF] / ln, col_counts[0] / ln))

    return DumpStats(
        number=number,
        path=path,
        size=n,
        sha256=hashlib.sha256(data).hexdigest(),
        md5=hashlib.md5(data).hexdigest(),
        crc32=f"{zlib.crc32(data):08x}",
        entropy=entropy(counts, n),
        ff=counts[0xFF] / (n or 1),
        zero=counts[0] / (n or 1),
        columns=columns,
        grid=grid,
        column_size=col_size,
        head=data[:384],
        strings=interesting_strings(data),
    )
