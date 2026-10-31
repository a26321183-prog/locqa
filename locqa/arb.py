"""Reading and (format-preserving) writing of Flutter ARB files.

ARB is JSON, but real files repeat ``"@@comment"`` many times, which a strict
``json.load`` collapses. We therefore read pairs in order and keep duplicates.
Writing is done line by line so that comments, blank lines, ordering and the
original formatting of untouched keys are preserved byte for byte.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class _Pairs(list):
    """Marker for 'JSON object as ordered pair list'."""


@dataclass
class ArbFile:
    path: str
    locale: Optional[str]
    messages: Dict[str, str] = field(default_factory=dict)   # key -> text (str values only)
    meta: Dict[str, dict] = field(default_factory=dict)      # "@key" -> dict
    order: List[str] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    text: str = ""


def _to_py(value):
    if isinstance(value, _Pairs):
        out = {}
        for k, v in value:
            out[k] = _to_py(v)
        return out
    if isinstance(value, list):
        return [_to_py(v) for v in value]
    return value


_LINE_RE = re.compile(r'^\s*"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$')


def parse_arb(path: str) -> ArbFile:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    arb = ArbFile(path=path, locale=None, text=text)
    pairs: List[Tuple[str, object]]
    try:
        top = json.loads(text, object_pairs_hook=_Pairs)
        pairs = list(top)
    except json.JSONDecodeError:
        # Tolerant fallback: one "key": "value" per line.
        pairs = []
        for line in text.splitlines():
            m = _LINE_RE.match(line)
            if m:
                try:
                    pairs.append((json.loads('"%s"' % m.group(1)), json.loads('"%s"' % m.group(2))))
                except json.JSONDecodeError:
                    continue
    for key, value in pairs:
        if key == "@@locale" and isinstance(value, str):
            arb.locale = value
            continue
        if key.startswith("@@"):
            continue
        if key.startswith("@") or "@" in key:
            arb.meta[key] = _to_py(value) if not isinstance(value, str) else {"description": value}
            continue
        if not isinstance(value, str):
            continue
        if key in arb.messages:
            arb.duplicates.append(key)
        else:
            arb.order.append(key)
        arb.messages[key] = value
    return arb


def guess_locale(arb: ArbFile) -> Optional[str]:
    if arb.locale:
        return arb.locale.replace("_", "-").split("-")[0].lower()
    m = re.search(r"intl_([a-zA-Z]{2,3})", arb.path)
    return m.group(1).lower() if m else None


# --------------------------------------------------------------------------- writing

def _encode(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_fixed(src: ArbFile, changes: Dict[str, str], flags: Dict[str, dict], out_path: str,
                added: Optional[Dict[str, str]] = None) -> None:
    """Write ``src`` with ``changes`` applied.

    changes: key -> new text for keys present in the file
    flags:   key -> dict stored under ``x-locqa`` in the ``@key`` entry
             (changed / reviewed_by_human / original / issues)
    added:   keys absent from the file; appended in a trailing section
    """
    lines = src.text.split("\n")
    out: List[str] = []
    pending_meta = dict(flags)
    existing_meta_line: Dict[str, int] = {}
    for i, line in enumerate(lines):
        m = re.match(r'^\s*"(@(?:[^"\\]|\\.)+)"\s*:', line)
        if m:
            existing_meta_line[json.loads('"%s"' % m.group(1))] = i

    def meta_entry(key: str) -> str:
        return '  "@%s": { "x-locqa": %s },' % (key, json.dumps(flags[key], ensure_ascii=False))

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _LINE_RE.match(line)
        key = None
        if m:
            try:
                key = json.loads('"%s"' % m.group(1))
            except json.JSONDecodeError:
                key = None
        if key is not None and key in changes and not key.startswith("@"):
            comma = "," if line.rstrip().endswith(",") else ""
            indent = re.match(r"^\s*", line).group(0)
            out.append('%s%s: %s%s' % (indent, _encode(key), _encode(changes[key]), comma))
            if key in pending_meta and ("@" + key) not in existing_meta_line:
                out.append(meta_entry(key))
                pending_meta.pop(key)
            i += 1
            continue
        # merge into an existing "@key" entry (single- or multi-line)
        mm = re.match(r'^(\s*)"(@(?:[^"\\]|\\.)+)"\s*:\s*(\{.*)$', line)
        if mm:
            mkey = json.loads('"%s"' % mm.group(2))[1:]
            if mkey in pending_meta:
                block = mm.group(3)
                j = i
                while block.count("{") != block.count("}") and j + 1 < n:
                    j += 1
                    block += "\n" + lines[j]
                trailing = "," if block.rstrip().endswith(",") else ""
                body = block.rstrip().rstrip(",")
                try:
                    obj = json.loads(body)
                    obj["x-locqa"] = pending_meta.pop(mkey)
                    out.append('%s"@%s": %s%s' % (mm.group(1), mkey, json.dumps(obj, ensure_ascii=False), trailing))
                    i = j + 1
                    continue
                except json.JSONDecodeError:
                    pass
        out.append(line)
        i += 1
    tail: List[str] = []
    # flags that could not be merged stay out of the file (an orphan "@key" breaks gen-l10n)
    if added:
        tail.append('  "@@comment": "LOCQA_ADDED_MISSING_KEYS",')
        for key, val in added.items():
            tail.append('  %s: %s,' % (_encode(key), _encode(val)))
            if key in flags:
                tail.append(meta_entry(key))
    text = "\n".join(out)
    if tail:
        idx = text.rstrip().rfind("}")
        head = text[:idx].rstrip()
        if not head.endswith(",") and not head.endswith("{"):
            head += ","
        body = "\n".join(tail).rstrip(",")
        text = head + "\n" + body + "\n}\n"
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
