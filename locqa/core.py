"""Core data types and the analysis context shared by all detectors."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .arb import ArbFile
from .glossary import Glossary
from .langs import LangProfile, words

ISSUE_TYPES = (
    "untranslated", "same_as_source", "placeholder_mismatch", "plural_mismatch", "glossary_violation",
    "length_overflow", "machine_translation_suspect", "inconsistent_term", "suffix_harmony",
    "orthography", "wrong_language",
)
SEVERITIES = ("high", "medium", "low")


@dataclass
class Finding:
    key: str
    issue_type: str
    severity: str
    source: str
    target: str
    evidence: str
    suggestion: Optional[str]
    confidence: float
    reviewed_by_human: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = round(float(d["confidence"]), 2)
        return d


def norm(s: str) -> str:
    """Normalisation used to compare strings: case, whitespace, punctuation-insensitive."""
    s = unicodedata.normalize("NFKC", s).lower().replace("ё", "е")
    s = re.sub(r"\\n|\n", " ", s)
    return re.sub(r"[\W_]+", " ", s).strip()


@dataclass
class Context:
    source: ArbFile
    target: ArbFile
    lang: LangProfile
    src_lang: LangProfile
    glossary: Glossary
    refs: Dict[str, ArbFile] = field(default_factory=dict)       # other languages, optional evidence
    options: Dict[str, object] = field(default_factory=dict)
    # filled by build_indexes()
    vocab: Counter = field(default_factory=Counter)               # target word frequencies
    src_vocab: Counter = field(default_factory=Counter)
    tm: Dict[str, Counter] = field(default_factory=dict)          # norm(source) -> Counter(target)
    boilerplate: List[Tuple[Tuple[str, ...], int]] = field(default_factory=list)
    apostrophe_main: Optional[str] = None

    def build_indexes(self) -> None:
        for k, t in self.target.messages.items():
            for w in words(t):
                self.vocab[w.lower()] += 1
        for k, s in self.source.messages.items():
            for w in words(s):
                self.src_vocab[w.lower()] += 1
        tm: Dict[str, Counter] = defaultdict(Counter)
        for k, s in self.source.messages.items():
            t = self.target.messages.get(k)
            if t is None or not t.strip() or norm(t) == norm(s):
                continue
            if not script_ok(self.lang, t):
                continue
            tm[norm(s)][t.strip()] += 1
        self.tm = tm
        self.boilerplate = find_boilerplate(self)

    def ref(self, code: str, key: str) -> Optional[str]:
        a = self.refs.get(code)
        return a.messages.get(key) if a else None


def script_ok(lang: LangProfile, text: str) -> bool:
    """True if ``text`` is mostly written in the script the target language uses."""
    ws = words(text)
    if not ws:
        return True
    cyr = sum(len(w) for w in ws if re.search("[\u0400-\u04FF]", w))
    lat = sum(len(w) for w in ws if re.search("[A-Za-z]", w) and not re.search("[\u0400-\u04FF]", w))
    total = cyr + lat or 1
    return (cyr / total >= 0.5) if lang.script == "cyrillic" else (lat / total >= 0.5)


def short_source(src: str) -> bool:
    plain = re.sub(r"\{[^{}]*\}", "", src).replace("\\n", " ").strip()
    return 0 < len(plain) <= 16 and len(plain.split()) <= 3 and not re.search(r"[.!?;:]{1}\s*\S", plain)


def find_boilerplate(ctx: Context, min_count: int = 3) -> List[Tuple[Tuple[str, ...], int]]:
    """Word-suffixes of translations that are repeated across *different short sources*.

    A phrase like «… туралы толық ақпарат алу үшін» glued to many one-word buttons is
    padding, not translation. Detected from the data itself, so it works for any language.
    """
    short_counts: Counter = Counter()
    all_counts: Counter = Counter()
    for k, s in ctx.source.messages.items():
        t = ctx.target.messages.get(k)
        if not t:
            continue
        toks = tuple(w.lower() for w in words(t))
        is_short = short_source(s)
        seen = set()
        for n in range(2, 7):
            if len(toks) <= n:
                break
            suf = toks[-n:]
            if suf in seen:
                continue
            seen.add(suf)
            all_counts[suf] += 1
            if is_short:
                short_counts[suf] += 1
    out = []
    for suf, c in short_counts.items():
        if (c >= min_count or (c >= 2 and len(suf) >= 3)) and c / all_counts[suf] >= 0.6:
            out.append((suf, c))
    out.sort(key=lambda x: (-len(x[0]), -x[1]))
    return out
