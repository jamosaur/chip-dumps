#!/usr/bin/env python3
"""Compute a fingerprint for each dump, so dumps can be compared without re-reading them.

  python3 site/fingerprint.py                 fingerprint every dump that has none, or a stale one
  python3 site/fingerprint.py CHIP/N ...      (re)compute these dumps
  python3 site/fingerprint.py --all           recompute every dump

Writes analysis/<CHIP>/<N>.print.json. A fingerprint is stale when the dump's SHA-256 or
the fingerprint VERSION changed. Everything here is computed from the bytes alone, so the
result is the same every time; site/compare.py ranks dumps against each other from it.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dumplib import DUMPS_DIR, all_dumps, parse_ref, print_path  # noqa: E402

VERSION = 2
BLOCK = 4096  # exact-match block size
CDC_MASK = 0x3FF  # content-defined chunks average about 1 KB
CDC_MIN, CDC_MAX = 256, 8192
MAX_STRINGS = 4000
MAX_SIGNATURES = 200
LAGS = range(1, 9)

STRING_RE = re.compile(rb"[\x20-\x7e]{6,}")

# Magic numbers that survive in a whole image. Lane-split data hides them, which is why the
# dump-analyst records decoded structures in the facts file as well.
SIGNATURES = [
    (b"PK\x03\x04", "zip-local-header"),
    (b"PK\x01\x02", "zip-central-directory"),
    (b"PK\x05\x06", "zip-end-of-directory"),
    (b"\x7fELF", "elf"),
    (b"\x1f\x8b\x08", "gzip"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"BZh91AY&SY", "bzip2"),
    (b"hsqs", "squashfs"),
    (b"UBI#", "ubi"),
    (b"\x27\x05\x19\x56", "u-boot-image"),
    (b"\x85\x19\x03\x20", "jffs2"),
    (b"-lh5-", "lha"),
    (b"\x5d\x00\x00\x80\x00", "lzma"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF89a", "gif"),
    (b"GIF87a", "gif"),
    (b"JFIF\x00", "jpeg-jfif"),
    (b"Exif\x00\x00", "jpeg-exif"),
]

# Gear table for content-defined chunking, derived from a fixed seed so it never changes.
GEAR = [int.from_bytes(hashlib.blake2b(bytes([i]), digest_size=4).digest(), "big") for i in range(256)]


def h8(b: bytes) -> str:
    return hashlib.blake2b(b, digest_size=8).hexdigest()


def uniform(b: bytes) -> bool:
    return not b or b.count(b[0]) == len(b)


def entropy(counts, n: int) -> float:
    return -sum(v / n * math.log2(v / n) for v in counts if v) if n else 0.0


def chunks(data: bytes) -> list[str]:
    """Content-defined chunk hashes: shared data is found even when it moved."""
    out, start, h = set(), 0, 0
    n = len(data)
    i = 0
    while i < n:
        h = ((h << 1) + GEAR[data[i]]) & 0xFFFFFFFF
        i += 1
        size = i - start
        if (size >= CDC_MIN and (h & CDC_MASK) == 0) or size >= CDC_MAX or i == n:
            c = data[start:i]
            if not uniform(c):
                out.add(h8(c))
            start, h = i, 0
    return sorted(out)


def bit_stats(hist: list[int]) -> tuple[list[float], list[list[float]]]:
    """Per-bit 1-frequency and the 8×8 bit-correlation matrix, from a byte histogram."""
    n = sum(hist) or 1
    p = [sum(c for b, c in enumerate(hist) if b >> i & 1) / n for i in range(8)]
    corr = [[1.0] * 8 for _ in range(8)]
    for i in range(8):
        for j in range(i + 1, 8):
            pij = sum(c for b, c in enumerate(hist) if b >> i & 1 and b >> j & 1) / n
            den = math.sqrt(p[i] * (1 - p[i]) * p[j] * (1 - p[j]))
            r = (pij - p[i] * p[j]) / den if den else 0.0
            corr[i][j] = corr[j][i] = round(r, 4)
    return [round(x, 4) for x in p], corr


def sector_size_for(chip: str, size: int) -> int:
    info_path = DUMPS_DIR / chip / "chip.yml"
    info = yaml.safe_load(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    s = int((info or {}).get("sector_size") or 0)
    if s and size % s == 0 and 0 < size // s <= 64:
        return s
    return max(1, size // 32)


def compute(chip: str, n: int, path: Path) -> dict:
    data = path.read_bytes()
    size = len(data)
    sector = sector_size_for(chip, size)

    sectors, heads = [], []
    for off in range(0, size, sector):
        sec = data[off : off + sector]
        c = collections.Counter(sec)
        ln = len(sec) or 1
        ones = sum(bin(b).count("1") * k for b, k in c.items())
        sectors.append({
            "entropy": round(entropy(c.values(), len(sec)), 3),
            "ff": round(c[0xFF] / ln, 4),
            "zero": round(c[0] / ln, 4),
            "ones": round(ones / (8 * ln), 4),
        })
        heads.append(sec[:16].hex(" "))

    blocks, content = [], bytearray()
    for off in range(0, size, BLOCK):
        b = data[off : off + BLOCK]
        if uniform(b):
            blocks.append(None)
        else:
            blocks.append(h8(b))
            content += b
    content = bytes(content)  # the non-uniform blocks, used for the content statistics

    hist = [0] * 256
    for b, k in collections.Counter(content).items():
        hist[b] = k
    bitfreq, bitcorr = bit_stats(hist)
    lag_equal = {}
    for k in LAGS:
        m = len(content) - k
        lag_equal[str(k)] = round(sum(a == b for a, b in zip(content, content[k:])) / m, 4) if m > 0 else 0.0

    strings = []
    for m in STRING_RE.finditer(data):
        s = m.group().decode("ascii")
        if len(set(s)) >= 3:
            strings.append([m.start(), s[:120]])
            if len(strings) >= MAX_STRINGS:
                break

    sigs = []
    for magic, name in SIGNATURES:
        start = 0
        while len(sigs) < MAX_SIGNATURES:
            i = data.find(magic, start)
            if i < 0:
                break
            sigs.append([i, name])
            start = i + 1
    sigs.sort()

    erased = []  # [offset, length] of erased runs, in whole blocks
    for off in range(0, size, BLOCK):
        b = data[off : off + BLOCK]
        if b.count(0xFF) == len(b):
            if erased and sum(erased[-1]) == off:
                erased[-1][1] += len(b)
            else:
                erased.append([off, len(b)])

    return {
        "version": VERSION,
        "dump": f"{chip}/{n}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": size,
        "sector_size": sector,
        "content_bytes": len(content),
        "sectors": sectors,
        "sector_heads": heads,
        "blocks": blocks,
        "chunks": chunks(content),
        "histogram": hist,
        "bitfreq": bitfreq,
        "bitcorr": bitcorr,
        "lag_equal": lag_equal,
        "strings": strings,
        "signatures": sigs,
        "erased_runs": erased,
    }


def load(chip: str, n: int) -> dict | None:
    p = print_path(chip, n)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def is_current(fp: dict | None, path: Path) -> bool:
    if not fp or fp.get("version") != VERSION:
        return False
    return fp.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()


def ensure(chip: str, n: int, path: Path, force: bool = False, write: bool = True) -> tuple[dict, bool]:
    """Return (fingerprint, recomputed). Recomputes when missing, stale or forced."""
    fp = load(chip, n)
    if not force and is_current(fp, path):
        return fp, False
    fp = compute(chip, n, path)
    if write:
        out = print_path(chip, n)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fp, separators=(",", ":")) + "\n", encoding="utf-8")
    return fp, True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dumps", nargs="*", metavar="CHIP/N")
    ap.add_argument("--all", action="store_true", help="recompute every dump")
    args = ap.parse_args()

    on_disk = {(c, n): p for c, n, p in all_dumps()}
    if args.dumps:
        targets = []
        for ref in args.dumps:
            key = parse_ref(ref)
            if key not in on_disk:
                raise SystemExit(f"No dump at dumps/{key[0]}/{key[1]}.bin")
            targets.append(key)
        force = True
    else:
        targets, force = sorted(on_disk), args.all
    for chip, n in targets:
        _, done = ensure(chip, n, on_disk[(chip, n)], force=force)
        print(f"{'Wrote' if done else 'Current'} {print_path(chip, n).relative_to(DUMPS_DIR.parent)}")


if __name__ == "__main__":
    main()
