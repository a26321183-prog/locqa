"""Command line interface.

    locqa check --source intl_ru.arb --target intl_kk.arb --glossary glossary.csv --out report.json
    locqa fix   --source intl_ru.arb --target intl_kk.arb --out-dir out/ [--curated fixes.csv]
    locqa apply-review --source ... --target ... --review review.csv --out intl_kk_fixed.arb
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional

from . import __version__
from .arb import parse_arb
from .engine import analyse
from .fix import (build_fixed, load_curated, propose, read_review_csv, write_review_csv, write_review_html)
from .report import write_html, write_json, write_summary


def _refs(items: Optional[List[str]]) -> Dict[str, str]:
    out = {}
    for it in items or []:
        if "=" in it:
            code, path = it.split("=", 1)
        else:
            code, path = os.path.basename(it).replace("intl_", "").split(".")[0], it
        out[code.lower()] = path
    return out


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--source", required=True, help="source ARB (e.g. intl_ru.arb)")
    p.add_argument("--target", required=True, help="target ARB (e.g. intl_kk.arb or intl_uz.arb)")
    p.add_argument("--lang", help="target language rules: kk | uz (default: from @@locale / file name)")
    p.add_argument("--glossary", help="glossary.csv")
    p.add_argument("--ref", action="append", metavar="CODE=PATH", help="other language file used only as evidence (repeatable)")
    p.add_argument("--ignore-key", action="append", default=[], help="key to skip (repeatable)")
    p.add_argument("--brand", action="append", default=[], help="text that may stay identical / in Latin (repeatable)")
    p.add_argument("--min-confidence", type=float, default=0.5, help="drop findings below this confidence (default 0.5)")


def _run(a) -> "object":
    return analyse(a.source, a.target, a.glossary, a.lang, _refs(a.ref), a.ignore_key, a.brand, a.min_confidence)


def cmd_check(a) -> int:
    res = _run(a)
    summ = res.summary()
    write_json(res.findings, a.out)
    base = os.path.splitext(a.out)[0]
    html_path = a.html or base + ".html"
    write_html(res.findings, summ, html_path)
    write_summary(summ, base + ".summary.json")
    print("locqa %s: %s -> %s [%s]: %d findings in %d keys (high %d, medium %d, low %d)" % (
        __version__, a.source, a.target, summ["language"], summ["findings"], summ["affected_keys"],
        summ["by_severity"]["high"], summ["by_severity"]["medium"], summ["by_severity"]["low"]))
    print("  wrote %s, %s, %s" % (a.out, html_path, base + ".summary.json"))
    if a.fail_on and any(f.severity == a.fail_on or (a.fail_on == "medium" and f.severity == "high") for f in res.findings):
        return 1
    return 0


def cmd_fix(a) -> int:
    res = _run(a)
    props = propose(res, load_curated(a.curated), a.min_confidence)
    os.makedirs(a.out_dir, exist_ok=True)
    code = res.ctx.lang.code
    write_review_csv(props, os.path.join(a.out_dir, "review_%s.csv" % code))
    write_review_html(props, os.path.join(a.out_dir, "review_%s.html" % code), res.ctx.lang.name)
    out = os.path.join(a.out_dir, "intl_%s_fixed.arb" % code)
    stats = build_fixed(res.ctx.target, props, out)
    print("fixed %s: %s" % (code, stats))
    return 0


def cmd_apply(a) -> int:
    res = _run(a)
    props = propose(res, load_curated(a.curated), a.min_confidence)
    stats = build_fixed(res.ctx.target, props, a.out, read_review_csv(a.review))
    print("applied review: %s" % stats)
    return 0


def cmd_validate(a) -> int:
    from .validate import validate
    problems = validate(a.source, a.fixed)
    for p in problems:
        print("PROBLEM:", p)
    print("OK: %s is consistent with %s" % (a.fixed, a.source) if not problems else "%d problem(s)" % len(problems))
    return 1 if problems else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="locqa", description="QA for Flutter ARB localisation (Kazakh, Uzbek, any ARB)")
    ap.add_argument("--version", action="version", version="locqa " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="find problems and write report.json + HTML")
    _common(c)
    c.add_argument("--out", default="report.json")
    c.add_argument("--html")
    c.add_argument("--fail-on", choices=("high", "medium"), help="exit 1 when findings of this severity exist (CI)")
    c.set_defaults(fn=cmd_check)
    f = sub.add_parser("fix", help="write a fixed ARB (all changes flagged unreviewed) + review files")
    _common(f)
    f.add_argument("--out-dir", default="out")
    f.add_argument("--curated", help="CSV key,new_text with hand-written fixes")
    f.set_defaults(fn=cmd_fix)
    r = sub.add_parser("apply-review", help="write the fixed ARB using a filled review.csv")
    _common(r)
    r.add_argument("--review", required=True)
    r.add_argument("--curated")
    r.add_argument("--out", required=True)
    r.set_defaults(fn=cmd_apply)
    v = sub.add_parser("validate", help="offline gen-l10n compatibility check of a fixed ARB")
    v.add_argument("--source", required=True)
    v.add_argument("--fixed", required=True)
    v.set_defaults(fn=cmd_validate)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
