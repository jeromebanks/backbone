"""Locate LLM-supplied quotes in the source text and convert them to line spans.

We never trust model-reported locations. A quote is accepted if it matches the document after
light normalisation (whitespace, dash and quote-mark variants, case), or - as a fallback - if a
contiguous window of the document is >= 0.92 similar AND every digit-bearing token (times, minutes, IDs) agrees
exactly. Anything else is unverified, and claims with unverified quotes are excluded from reconciliation (and
reported).
"""
from __future__ import annotations

import difflib
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
