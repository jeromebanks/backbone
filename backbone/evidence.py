"""Locate LLM-supplied quotes in the source text and convert them to line spans.

We never trust model-reported locations. A quote is accepted if it matches the document after
light normalisation (whitespace, dash and quote-mark variants, case), or - as a fallback - if a
contiguous window of the document is >= 0.92 similar. Anything else is unverified, and claims with
unverified quotes are excluded from reconciliation (and reported).
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
        idx = self.norm.find(q)
        if idx >= 0:
            ls, le = self._span(idx, idx + len(q))
            match = "exact" if quote in self.text else "normalized"
            return Span(quote, ls, le, match)
        # Ellipsis-joined fragments: every fragment must be present, in order.
        parts = [p.strip() for p in re.split(r"\.\.\.|…", q) if len(p.strip()) >= 8]
        if len(parts) > 1:
            pos, first, last = 0, None, None
            for p in parts:
                i = self.norm.find(p, pos)
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
            if best >= 0.92:
                ls, le = self._span(best_i, best_i + len(q))
                return Span(quote, ls, le, "fuzzy")
        return Span(quote, None, None, "missing")
