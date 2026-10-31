"""Orchestration: load files, build indexes, run detectors, rank findings."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional

from . import detectors as D
from .arb import ArbFile, guess_locale, parse_arb
from .core import Context, Finding, ISSUE_TYPES
from .glossary import Glossary
from .langs import get_profile

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def analyse(source_path: str, target_path: str, glossary_path: Optional[str] = None, lang: Optional[str] = None,
            refs: Optional[Dict[str, str]] = None, ignore_keys: Iterable[str] = (), brands: Iterable[str] = (),
            min_confidence: float = 0.0, src_lang: Optional[str] = None) -> "Result":
    source = parse_arb(source_path)
    target = parse_arb(target_path)
    tcode = (lang or guess_locale(target) or "und").lower()
    scode = (src_lang or guess_locale(source) or "ru").lower()
    ctx = Context(source=source, target=target, lang=get_profile(tcode), src_lang=get_profile(scode),
                  glossary=Glossary.load(glossary_path))
    for code, path in (refs or {}).items():
        if code != tcode:
            ctx.refs[code] = parse_arb(path)
    ctx.options["ignore_keys"] = set(D.DEFAULT_IGNORE_KEYS) | set(ignore_keys)
    ctx.options["brands"] = list(brands)
    ctx.build_indexes()
    if ctx.lang.code == "uz":
        ctx.apostrophe_main = D.detect_apostrophes(target.messages.values())
    findings: List[Finding] = []
    by_key: Dict[str, set] = defaultdict(set)
    for key, src in source.messages.items():
        if key in ctx.options["ignore_keys"]:
            continue
        tgt = target.messages.get(key)
        fs = D.d_untranslated(ctx, key, src, tgt)
        if tgt is not None and tgt.strip():
            for det in D.ALL_DETECTORS:
                fs.extend(det(ctx, key, src, tgt))
        for f in fs:
            by_key[key].add(f.issue_type)
        findings.extend(fs)
    findings.extend(D.d_inconsistent(ctx, by_key))
    findings.extend(D.d_term_consistency(ctx, by_key))
    findings = [f for f in findings if f.confidence >= min_confidence]
    order = {k: i for i, k in enumerate(source.messages)}
    findings.sort(key=lambda f: (SEV_ORDER[f.severity], -f.confidence, order.get(f.key, 10 ** 9), f.issue_type))
    return Result(ctx, findings)


class Result:
    def __init__(self, ctx: Context, findings: List[Finding]):
        self.ctx = ctx
        self.findings = findings

    def summary(self) -> dict:
        by_type = Counter(f.issue_type for f in self.findings)
        by_sev = Counter(f.severity for f in self.findings)
        src, tgt = self.ctx.source, self.ctx.target
        return {
            "tool": "locqa", "language": self.ctx.lang.code, "language_name": self.ctx.lang.name,
            "language_native": self.ctx.lang.native_name,
            "source_file": src.path, "target_file": tgt.path,
            "source_keys": len(src.messages), "target_keys": len(tgt.messages),
            "findings": len(self.findings), "affected_keys": len({f.key for f in self.findings}),
            "by_type": {t: by_type.get(t, 0) for t in ISSUE_TYPES}, "by_severity": {s: by_sev.get(s, 0) for s in ("high", "medium", "low")},
            "glossary_terms": len(self.ctx.glossary.entries), "reference_languages": sorted(self.ctx.refs),
            "duplicate_keys_in_target": sorted(set(tgt.duplicates))[:20],
        }
