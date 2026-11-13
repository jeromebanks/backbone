"""Locate LLM-supplied quotes in the source text and convert them to line spans.

We never trust model-reported locations. A quote is accepted if it matches the document after
light normalisation (whitespace, dash and quote-mark variants, case), or - as a fallback - if a
contiguous window of the document is >= 0.92 similar AND every digit-bearing token (times, minutes, IDs) agrees
exactly. Anything else is unverified, and claims with unverified quotes are excluded from reconciliation (and
reported).
"""
from __future__ import annotations

import difflib
from functools import lru_cache
import re
from dataclasses import dataclass

_TRANS = str.maketrans({
    "–": "-", "—": "-", "−": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', " ": " ",
})


def _norm_char(c: str) -> str:
    return c.translate(_TRANS).lower()


@dataclass
class Span:
    quote: str
    line_start: int | None
    line_end: int | None
    match: str  # exact | normalized | fuzzy | missing

    def as_dict(self) -> dict:
        return {"quote": self.quote, "line_start": self.line_start, "line_end": self.line_end, "match": self.match}


class DocumentIndex:
    """Normalised copy of a document with a map back to original line numbers."""

    def __init__(self, text: str):
        self.text = text
        chars: list[str] = []
        lines: list[int] = []
        line = 1
        prev_space = True
        for c in text:
            if c == "\n":
                line += 1
            if c.isspace():
                if not prev_space:
                    chars.append(" ")
                    lines.append(line)
                prev_space = True
                continue
            chars.append(_norm_char(c))
            lines.append(line)
            prev_space = False
        self.norm = "".join(chars)
        self.line_of = lines

    @staticmethod
    def normalize(s: str) -> str:
        return re.sub(r"\s+", " ", s.translate(_TRANS).lower()).strip()

    def _span(self, start: int, end: int) -> tuple[int, int]:
        return self.line_of[start], self.line_of[max(start, end - 1)]

    def locate(self, quote: str) -> Span:
        if not quote or not quote.strip():
            return Span(quote, None, None, "missing")
        q = self.normalize(quote)
        idx = self._find(q)
        if idx >= 0:
            ls, le = self._span(idx, idx + len(q))
            match = "exact" if quote in self.text else "normalized"
            return Span(quote, ls, le, match)
        # Ellipsis-joined fragments: every fragment must be present, in order.
        parts = [p.strip() for p in re.split(r"\.\.\.|…", q) if len(p.strip()) >= 8]
        if len(parts) > 1:
            pos, first, last = 0, None, None
            for p in parts:
                i = self._find(p, pos)
                if i < 0:
                    break
                first = i if first is None else first
                last = i + len(p)
                pos = last
            else:
                ls, le = self._span(first, last)
                return Span(quote, ls, le, "normalized")
        # Fuzzy fallback: best window of the same length.
        if len(q) >= 20:
            best, best_i = 0.0, -1
            step = max(1, len(q) // 8)
            for i in range(0, max(1, len(self.norm) - len(q) + 1), step):
                r = difflib.SequenceMatcher(None, q, self.norm[i:i + len(q)], autojunk=False).ratio()
                if r > best:
                    best, best_i = r, i
            if best_i >= 0:
                # refine around the best coarse hit
                for i in range(max(0, best_i - step), min(len(self.norm), best_i + step + 1)):
                    r = difflib.SequenceMatcher(None, q, self.norm[i:i + len(q)], autojunk=False).ratio()
                    if r > best:
                        best, best_i = r, i
            end = min(len(self.norm), best_i + len(q))   # the refined window may run past the document's end
            if best >= 0.92 and self._same_numbers(q, best_i, end):
                ls, le = self._span(best_i, end)
                return Span(quote, ls, le, "fuzzy")
        return Span(quote, None, None, "missing")

    def _find(self, needle: str, pos: int = 0) -> int:
        """`str.find` that will not start or end a match in the middle of a word or number, so "5 minutes" does
        not verify against "45 minutes". A needle edge that is punctuation or space may abut anything."""
        n = len(needle)
        while (i := self.norm.find(needle, pos)) >= 0:
            j = i + n
            if not (needle[0].isalnum() and i > 0 and self.norm[i - 1].isalnum()) and \
               not (needle[-1].isalnum() and j < len(self.norm) and self.norm[j].isalnum()):
                return i
            pos = i + 1
        return -1

    def _same_numbers(self, q: str, start: int, end: int) -> bool:
        """Fuzzy matching may forgive prose typos, never a changed number or identifier: every token containing a
        digit (times, minutes, scores, dates, IDs like hg-e110) must appear unchanged and in the same order in the
        matched window. The window is widened to whole tokens first, so an edge cut mid-token cannot cause a miss."""
        while start > 0 and not self.norm[start - 1].isspace():
            start -= 1
        while end < len(self.norm) and not self.norm[end].isspace():
            end += 1
        want, have = _numeric_tokens(q), _numeric_tokens(self.norm[start:end])
        return any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))


_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _numeric_tokens(s: str) -> list[str]:
    s = re.sub(r"\s*-\s*", "-", s)          # "10:00 - 10:30" and "10:00-10:30" tokenize alike
    return [t for t in _TOKEN.findall(s) if any(c.isdigit() for c in t)]


# --------------------------------------------------------------------------------------------- value grounding (#36)
# A located quote proves the quote exists, not that the structured values extracted alongside it say what the quote
# says. `ground_values` checks clock times, minute counts, scores/thresholds and dates in a claim's payload against
# the claim's own quotes, after normalising formats ("9:00" = "09:00" = "9:00 am", en dashes, "50 min" = "50 minutes",
# "January 5, 2026" = "Jan05" = "2026-01-05"). It only reports; ingest decides what an ungrounded value means.

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_AMPM = r"(a\.?\s?m\b\.?|p\.?\s?m\b\.?)"
_TIME = re.compile(r"(?<![\d:])(\d{1,2})[:.h](\d{2})(?![\d:])\s*" + _AMPM + "?", re.I)
_TIME_HOUR = re.compile(r"(?<![\d:.])(\d{1,2})\s*" + _AMPM, re.I)
_MINUTES = re.compile(r"(?<![\d.])(\d{1,4})\s*-?\s*(?:minutes?|mins?\b|min\b)", re.I)
_HOURS = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*-?\s*(?:hours?|hrs?\b)", re.I)
_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?!\d)")
_WORDS = {w: i for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                                       "ten", "eleven", "twelve"])}
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_MDY = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_MONTH_DAY = re.compile(r"\b" + _MON + r"\s*(\d{1,2})(?!\d)(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", re.I)
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"(?:,?\s*(\d{4}))?", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(_TRANS))


@lru_cache(maxsize=1024)          # pure; grounding asks the same document text once per value (#36)
def times_in(s: str) -> set[int]:
    """Clock times stated in `s`, as minutes after midnight ("9:00", "09:00", "9.00 am", "2 pm")."""
    out: set[int] = set()
    s = _clean(s)
    for h, m, ap in _TIME.findall(s):
        h, m = int(h), int(m)
        if ap:
            h = h % 12 + (12 if ap.lower().startswith("p") else 0)
        if h < 24 and m < 60:
            out.add(h * 60 + m)
    for h, ap in _TIME_HOUR.findall(s):
        h = int(h) % 12 + (12 if ap.lower().startswith("p") else 0)
        if h < 24:
            out.add(h * 60)
    return frozenset(out)


@lru_cache(maxsize=1024)          # pure; grounding asks the same document text once per value (#36)
def minutes_in(s: str) -> set[float]:
    """Durations stated with a unit ("50 minutes", "50 min", "45-minute", "1 hour" = 60)."""
    s = _clean(s)
    return frozenset({float(m) for m in _MINUTES.findall(s)} | {float(h) * 60 for h in _HOURS.findall(s)})


@lru_cache(maxsize=1024)          # pure; grounding asks the same document text once per value (#36)
def numbers_in(s: str) -> set[float]:
    """Every number stated in `s`, including the number words zero..twelve."""
    s = _clean(s).lower()
    return frozenset({float(n) for n in _NUMBER.findall(s)} | {float(v) for w, v in _WORDS.items() if re.search(rf"\b{w}\b", s)})


@lru_cache(maxsize=1024)          # pure; grounding asks the same document text once per value (#36)
def dates_in(s: str) -> set[tuple[int | None, int, int]]:
    """Dates stated in `s` as (year or None, month, day): ISO, m/d[/y], "January 5, 2026", "Jan05", "5 Jan"."""
    s = _clean(s)
    out: set[tuple[int | None, int, int]] = set()
    for y, m, d in _ISO.findall(s):
        out.add((int(y), int(m), int(d)))
    for m, d, y in _MDY.findall(s):
        out.add(((int(y) + 2000 if len(y) == 2 else int(y)) if y else None, int(m), int(d)))
    for mon, d, y in _MONTH_DAY.findall(s):
        out.add((int(y) if y else None, _MONTHS[mon[:3].lower()], int(d)))
    for d, mon, y in _DAY_MONTH.findall(s):
        out.add((int(y) if y else None, _MONTHS[mon[:3].lower()], int(d)))
    return frozenset(out)


def _value_in(kind: str, value, text: str) -> bool:
    if kind == "time":
        t = times_in(str(value))
        return bool(t) and t <= times_in(text)
    if kind == "minutes":
        return float(value) in minutes_in(text)
    if kind == "number":
        return float(value) in numbers_in(text)
    if kind == "date":
        m = _ISO.search(str(value))
        if not m:
            return False
        y, mo, d = (int(x) for x in m.groups())
        found = dates_in(text)
        return (y, mo, d) in found or (None, mo, d) in found   # "January 19" grounds 2026-01-19
    raise ValueError(kind)


def ground_values(fields: list[tuple[str, str, object, list[str]]]) -> dict[str, bool]:
    """`fields` = [(field_path, kind, value, quotes)], kind in time | minutes | number | date. Returns
    {field_path: grounded} for every non-null value; a value is grounded when one of its quotes states it."""
    return {path: any(_value_in(kind, value, q or "") for q in quotes)
            for path, kind, value, quotes in fields if value not in (None, "")}
