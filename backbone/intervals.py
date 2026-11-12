"""Minute-resolution interval algebra on a single service date. All durations come from here."""
from __future__ import annotations

Interval = tuple[int, int]  # [start, end) in minutes after midnight


def to_min(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    try:
        h, m = hhmm.strip().split(":")[:2]
        return int(h) * 60 + int(m[:2])
    except (ValueError, AttributeError):
        return None


def fmt(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def fmt_set(ivs: list[Interval]) -> str:
    return " + ".join(f"{fmt(s)}–{fmt(e)}" for s, e in ivs) or "∅"


def normalize(ivs) -> list[Interval]:
    """Sort and merge overlapping/adjacent intervals; drop empty or inverted ones."""
    out: list[list[int]] = []
    for s, e in sorted((s, e) for s, e in ivs if s is not None and e is not None and e > s):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def subtract(a, b) -> list[Interval]:
    """a minus b."""
    res: list[Interval] = []
    b = normalize(b)
    for s, e in normalize(a):
        cur = s
        for bs, be in b:
            if be <= cur or bs >= e:
                continue
            if bs > cur:
                res.append((cur, bs))
            cur = max(cur, be)
            if cur >= e:
                break
        if cur < e:
            res.append((cur, e))
    return res


def intersect(a, b) -> list[Interval]:
    res: list[Interval] = []
    for s, e in normalize(a):
        for bs, be in normalize(b):
            lo, hi = max(s, bs), min(e, be)
            if hi > lo:
                res.append((lo, hi))
    return normalize(res)


def total(ivs) -> int:
    return sum(e - s for s, e in normalize(ivs))


def overlaps(a, b) -> bool:
    return total(intersect(a, b)) > 0
