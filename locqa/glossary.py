"""glossary.csv loading and matching.

Columns (header row required): ``ru, kk, en, comment`` are the mandatory ones.
Optional columns: ``uz``, ``ru_regex`` (explicit source pattern), ``<lang>_forbidden``
(pipe-separated stems that must NOT be used for the term in that language),
``status`` (free text, e.g. ``proposed`` / ``verified``).

Matching is stem based because Kazakh and Uzbek are agglutinative: the term
«отбасы» must be accepted inside «отбасыңыз», «отбасының» and so on.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def stem(term: str, lang: str) -> str:
    t = term.lower().strip()
    if len(t) <= 3:
        return t
    cut = 1 if len(t) <= 6 else 2
    return t[:-cut]


@dataclass
class GlossaryEntry:
    ru: str
    terms: Dict[str, str]                 # lang -> canonical term(s) separated by '|'
    forbidden: Dict[str, List[str]]
    comment: str = ""
    ru_regex: Optional[str] = None
    status: str = ""

    def source_pattern(self):
        if self.ru_regex:
            return re.compile(self.ru_regex, re.IGNORECASE)
        parts = [re.escape(stem(w, "ru")) for w in self.ru.lower().split()]
        return re.compile(r"(?<![\w])" + r"\W+".join(p + r"\w*" for p in parts), re.IGNORECASE)

    def allowed(self, lang: str) -> List[str]:
        raw = self.terms.get(lang, "")
        return [x.strip() for x in raw.split("|") if x.strip()]

    def bad(self, lang: str) -> List[str]:
        return self.forbidden.get(lang, [])


@dataclass
class Glossary:
    entries: List[GlossaryEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Optional[str]) -> "Glossary":
        g = cls()
        if not path:
            return g
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rd = csv.DictReader(fh)
            for row in rd:
                ru = (row.get("ru") or "").strip()
                if not ru or ru.startswith("#"):
                    continue
                terms = {k: (row.get(k) or "").strip() for k in row if k in ("kk", "uz", "en") and row.get(k)}
                forb = {}
                for k in row:
                    if k and k.endswith("_forbidden") and row.get(k):
                        forb[k[:-len("_forbidden")]] = [x.strip().lower() for x in row[k].split("|") if x.strip()]
                g.entries.append(GlossaryEntry(
                    ru=ru, terms=terms, forbidden=forb, comment=(row.get("comment") or "").strip(),
                    ru_regex=(row.get("ru_regex") or "").strip() or None, status=(row.get("status") or "").strip()))
        return g

    def for_lang(self, lang: str) -> List[GlossaryEntry]:
        return [e for e in self.entries if e.allowed(lang)]
