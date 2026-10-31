"""Placeholder and ICU MessageFormat helpers (plural / select) used by the QA rules."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

PH_RE = re.compile(r"\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:,[^{}]*)?\}")
PRINTF_RE = re.compile(r"%(?:\d+\$)?[sdfi]")
TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*\s*/?>")


@dataclass
class IcuNode:
    kind: str                      # "plural" | "select" | "selectordinal"
    arg: str
    branches: Dict[str, str] = field(default_factory=dict)
    raw: str = ""


def balanced(text: str) -> Tuple[bool, str]:
    """Check brace balance with ICU quoting ('{' escapes)."""
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and i + 1 < len(text) and text[i + 1] in "{}'":
            if text[i + 1] == "'":
                i += 2
                continue
            j = text.find("'", i + 2)
            if j == -1:
                return False, "незакрытая кавычка ICU после «'%s»" % text[i + 1]
            i = j + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False, "лишняя закрывающая скобка }"
        i += 1
    if depth:
        return False, "не закрыта скобка { (%d)" % depth
    return True, ""


def _matching(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_icu(text: str) -> List[IcuNode]:
    """Find top-level and nested plural/select blocks."""
    nodes: List[IcuNode] = []
    for m in re.finditer(r"\{\s*([A-Za-z_]\w*)\s*,\s*(plural|select|selectordinal)\s*,", text):
        start = m.start()
        end = _matching(text, start)
        if end == -1:
            nodes.append(IcuNode(m.group(2), m.group(1), {}, text[start:]))
            continue
        body = text[m.end():end]
        node = IcuNode(m.group(2), m.group(1), {}, text[start:end + 1])
        pos = 0
        while pos < len(body):
            bm = re.match(r"\s*(=?\w+)\s*\{", body[pos:])
            if not bm:
                break
            b_start = pos + bm.end() - 1
            b_end = _matching(body, b_start)
            if b_end == -1:
                node.branches[bm.group(1)] = body[b_start + 1:]
                break
            node.branches[bm.group(1)] = body[b_start + 1:b_end]
            pos = b_end + 1
        nodes.append(node)
    return nodes


def placeholders(text: str) -> Counter:
    """Named placeholders ({name}); ICU plural/select heads contribute their argument name."""
    c: Counter = Counter()
    for m in PH_RE.finditer(text):
        c[m.group(1)] += 1
    return c


def printf_tokens(text: str) -> Counter:
    return Counter(PRINTF_RE.findall(text))


def tags(text: str) -> Counter:
    return Counter(t.replace(" ", "") for t in TAG_RE.findall(text))
