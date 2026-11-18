#!/usr/bin/env python3
"""Rank which other dumps are most likely related to a dump, from fingerprints alone.

  python3 site/compare.py CHIP/N ...            ranked candidates for each dump, as text
  python3 site/compare.py CHIP/N ... --json     the same as JSON (for the cross-analyst)
  python3 site/compare.py --all [--json]        every dump against every other

This is a cheap first pass, not a verdict: it says which pairs deserve a closer look and
why. The cross-analyst confirms or rejects them, reading byte ranges where it needs to.
Missing or stale fingerprints are computed first (see site/fingerprint.py).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fingerprint  # noqa: E402
from dumplib import all_dumps, parse_ref  # noqa: E402

TOP = 8


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2 or n != len(b):
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if not va or not vb:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def _hist_shape(fp: dict) -> list[float]:
    # Leave out 00 and FF: padding and erased bytes say little about the content.
    h = fp["histogram"]
    total = sum(h) - h[0] - h[255] or 1
    return [c / total for i, c in enumerate(h) if i not in (0, 255)]


def _heads(fp: dict) -> set[str]:
    out = set()
    for h in fp["sector_heads"]:
        b = h.split()[:4]
        if len(b) == 4 and len(set(b)) > 1:
            out.add(" ".join(b))
    return out


def _strings(fp: dict) -> set[str]:
    return {s for _, s in fp["strings"] if len(s) >= 8 and len(set(s)) >= 4}


def score(a: dict, b: dict) -> dict:
    """Similarity components for two fingerprints, a 0–1 total and readable reasons."""
    reasons = []

    ba = {x for x in a["blocks"] if x}
    bb = {x for x in b["blocks"] if x}
    shared_blocks = len(ba & bb)
    if shared_blocks:
        reasons.append(f"{shared_blocks} identical 4 KB blocks")

    ca, cb = set(a["chunks"]), set(b["chunks"])
    shared_chunks = len(ca & cb)
    jaccard = shared_chunks / (len(ca | cb) or 1)
    if shared_chunks >= 3:
        reasons.append(f"{shared_chunks} shared content chunks (Jaccard {jaccard:.3f}), so some data is shared even where it moved")

    hist = pearson(_hist_shape(a), _hist_shape(b))
    if hist > 0.6:
        reasons.append(f"byte histograms correlate at {hist:.2f}")

    # Bit-correlation matrices: the same wiring quirk (for example a swapped data-bit pair)
    # shows up as the same off-diagonal pattern.
    off = [(i, j) for i in range(8) for j in range(i + 1, 8)]
    diff = sum(abs(a["bitcorr"][i][j] - b["bitcorr"][i][j]) for i, j in off) / len(off)
    strongest = max(off, key=lambda ij: abs(a["bitcorr"][ij[0]][ij[1]]) + abs(b["bitcorr"][ij[0]][ij[1]]))
    sa, sb = a["bitcorr"][strongest[0]][strongest[1]], b["bitcorr"][strongest[0]][strongest[1]]
    bitcorr = max(0.0, 1 - diff * 4)
    if bitcorr > 0.7 and min(abs(sa), abs(sb)) > 0.05:
        reasons.append(f"same bit-correlation pattern (D{strongest[0]}/D{strongest[1]}: {sa:+.2f} vs {sb:+.2f})")

    lag = 1 - sum(abs(a["lag_equal"][k] - b["lag_equal"][k]) for k in a["lag_equal"]) / max(
        1e-9, sum(a["lag_equal"].values()) + sum(b["lag_equal"].values())
    )

    heads = _heads(a) & _heads(b)
    if heads:
        shown = ", ".join(f"`{h}`" for h in sorted(heads)[:3])
        reasons.append(f"{len(heads)} sector-start patterns in common ({shown})")

    strs = _strings(a) & _strings(b)
    if strs:
        sample = ", ".join(f"`{s[:24]}`" for s in sorted(strs, key=len, reverse=True)[:3])
        reasons.append(f"{len(strs)} strings of 8+ characters in common ({sample})")

    layout = 0.0
    if len(a["sectors"]) == len(b["sectors"]):
        layout = pearson([s["entropy"] for s in a["sectors"]], [s["entropy"] for s in b["sectors"]])
        if layout > 0.8:
            reasons.append(f"sector entropy profiles correlate at {layout:.2f}")

    sigs = {n for _, n in a["signatures"]} & {n for _, n in b["signatures"]}
    if sigs:
        reasons.append("both contain " + ", ".join(sorted(sigs)))

    total = (
        0.30 * min(1.0, jaccard * 4 + shared_blocks / 16)
        + 0.15 * max(0.0, hist)
        + 0.15 * bitcorr
        + 0.10 * min(1.0, len(strs) / 10)
        + 0.10 * min(1.0, len(heads) / 2)
        + 0.10 * max(0.0, layout)
        + 0.05 * max(0.0, lag)
        + 0.05 * min(1.0, len(sigs))
    )
    return {
        "score": round(total, 3),
        "shared_blocks": shared_blocks,
        "shared_chunks": shared_chunks,
        "chunk_jaccard": round(jaccard, 4),
        "histogram_corr": round(hist, 3),
        "bitcorr_similarity": round(bitcorr, 3),
        "lag_similarity": round(lag, 3),
        "shared_sector_heads": sorted(heads)[:10],
        "shared_strings": len(strs),
        "layout_corr": round(layout, 3),
        "shared_signatures": sorted(sigs),
        "reasons": reasons,
    }


def load_prints(write: bool = True) -> dict[str, dict]:
    """Fingerprints of every dump on disk, computing missing or stale ones."""
    out = {}
    for chip, n, path in all_dumps():
        fp, _ = fingerprint.ensure(chip, n, path, write=write)
        out[f"{chip}/{n}"] = fp
    return out


def rank(target: str, prints: dict[str, dict], top: int = TOP) -> list[dict]:
    a = prints[target]
    rows = [{"dump": ref, **score(a, b)} for ref, b in prints.items() if ref != target]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:top]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dumps", nargs="*", metavar="CHIP/N")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=TOP)
    args = ap.parse_args()

    prints = load_prints()
    targets = sorted(prints) if args.all or not args.dumps else []
    for ref in args.dumps:
        chip, n = parse_ref(ref)
        key = f"{chip}/{n}"
        if key not in prints:
            raise SystemExit(f"No dump at dumps/{chip}/{n}.bin")
        targets.append(key)

    result = {t: rank(t, prints, args.top) for t in targets}
    if args.json:
        print(json.dumps(result, indent=1))
        return
    for t, rows in result.items():
        print(f"{t}")
        for r in rows:
            why = "; ".join(r["reasons"]) or "nothing specific"
            print(f"  {r['score']:.3f}  {r['dump']:<16} {why}")
        print()


if __name__ == "__main__":
    main()
