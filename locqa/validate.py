"""Offline check that an ARB file is safe for ``flutter gen-l10n`` (flutter itself is not required)."""
from __future__ import annotations

import json
from typing import List

from . import icu
from .arb import parse_arb


def validate(source_path: str, fixed_path: str) -> List[str]:
    problems: List[str] = []
    try:
        with open(fixed_path, encoding="utf-8") as fh:
            raw = json.loads(fh.read(), object_pairs_hook=list)
    except json.JSONDecodeError as exc:
        return ["invalid JSON: %s" % exc]
    src, fx = parse_arb(source_path), parse_arb(fixed_path)
    orig_msgs = set(fx.messages)
    for key, text in fx.messages.items():
        if key not in src.messages:
            problems.append("%s: key does not exist in the source file" % key)
            continue
        if icu.placeholders(src.messages[key]) != icu.placeholders(text) and not icu.parse_icu(src.messages[key]):
            problems.append("%s: placeholders differ from source (%s vs %s)" % (
                key, dict(icu.placeholders(src.messages[key])), dict(icu.placeholders(text))))
        ok, why = icu.balanced(text)
        if not ok:
            problems.append("%s: %s" % (key, why))
    for key, meta in fx.meta.items():
        base = key[1:] if key.startswith("@") else key
        if base not in fx.messages and "@" not in base:
            problems.append("%s: metadata without a message (gen-l10n rejects this)" % key)
    flagged = {k[1:] for k, m in fx.meta.items() if isinstance(m, dict) and "x-locqa" in m}
    for key in flagged:
        flag = fx.meta["@" + key]["x-locqa"]
        if not isinstance(flag.get("reviewed_by_human"), bool):
            problems.append("%s: reviewed_by_human must be a boolean" % key)
    return problems
