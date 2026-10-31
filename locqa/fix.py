"""Conservative fixing and the human-review workflow.

* ``propose`` builds proposed replacements: automatic ones only where the rule is mechanical
  (restore a lost placeholder brace, repair a mixed-script/typo word, strip inserted padding,
  take an existing translation of the same source) plus curated ones from a CSV.
* Every changed string is written with ``x-locqa.reviewed_by_human = false`` until a person
  confirms it through the review file (``locqa apply-review``). Nothing is ever marked as
  reviewed automatically.
"""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from . import detectors as D
from .arb import ArbFile, write_fixed
from .core import Context, Finding
from .engine import Result

AUTO_TYPES = {"placeholder_mismatch", "orthography", "length_overflow", "wrong_language", "untranslated", "same_as_source"}
REVIEW_COLUMNS = ["key", "issue_types", "source", "original", "proposed", "origin", "decision", "final_text", "reviewer"]


def _key_findings(ctx: Context, key: str, text: str) -> List[Finding]:
    src = ctx.source.messages[key]
    old = ctx.target.messages.get(key)
    ctx.target.messages[key] = text
    try:
        out: List[Finding] = []
        for det in D.ALL_DETECTORS:
            out.extend(det(ctx, key, src, text))
        return out
    finally:
        if old is None:
            ctx.target.messages.pop(key, None)
        else:
            ctx.target.messages[key] = old


def load_curated(path: Optional[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path:
        return out
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("key") and row.get("new_text") is not None and not row["key"].startswith("#"):
                out[row["key"]] = row["new_text"].replace("\\n", "\n") if "\\n" in row["new_text"] and "\n" not in row["new_text"] else row["new_text"]
    return out


def propose(result: Result, curated: Optional[Dict[str, str]] = None, min_conf: float = 0.5
            ) -> "OrderedDict[str, dict]":
    ctx = result.ctx
    curated = curated or {}
    keys = OrderedDict()
    for f in result.findings:
        if f.confidence >= min_conf:
            keys.setdefault(f.key, []).append(f)
    props: "OrderedDict[str, dict]" = OrderedDict()
    for key, fs in keys.items():
        types = sorted({f.issue_type for f in fs})
        original = ctx.target.messages.get(key, "")
        if key in curated:
            new, origin = curated[key], "curated"
        else:
            text = original
            applied = False
            for _ in range(4):
                step = None
                for f in _key_findings(ctx, key, text) if text else fs:
                    if f.issue_type in AUTO_TYPES and f.suggestion and f.suggestion != text and f.confidence >= 0.8 \
                            and not (f.issue_type == "untranslated" and len(D.plain(f.source).split()) > 3):
                        step = f.suggestion
                        break
                if not step:
                    break
                text, applied = step, True
            if not applied:
                continue
            new, origin = text, "auto"
        if new == original:
            continue
        props[key] = {"issues": types, "original": original, "proposed": new, "origin": origin,
                      "source": ctx.source.messages.get(key, ""), "missing": key not in ctx.target.messages}
    # curated entries for keys that produced no finding (e.g. manual semantic fixes)
    for key, new in curated.items():
        if key not in props and key in ctx.source.messages and new != ctx.target.messages.get(key):
            props[key] = {"issues": ["manual"], "original": ctx.target.messages.get(key, ""), "proposed": new,
                          "origin": "curated", "source": ctx.source.messages[key], "missing": key not in ctx.target.messages}
    return props


def write_review_csv(props: Dict[str, dict], path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(REVIEW_COLUMNS)
        for k, p in props.items():
            w.writerow([k, "|".join(p["issues"]), p["source"], p["original"], p["proposed"], p["origin"], "", "", ""])


def read_review_csv(path: str) -> Dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["key"]] = row
    return out


def build_fixed(src_arb: ArbFile, props: Dict[str, dict], out_path: str, review: Optional[Dict[str, dict]] = None
                ) -> Dict[str, int]:
    """Write the fixed ARB. ``review`` rows decide the final text and the human flag."""
    review = review or {}
    changes: Dict[str, str] = {}
    added: Dict[str, str] = {}
    flags: Dict[str, dict] = {}
    stats = {"changed": 0, "reviewed_by_human": 0, "rejected": 0, "added": 0}
    for key, p in props.items():
        row = review.get(key, {})
        decision = (row.get("decision") or "").strip().lower()
        reviewer = (row.get("reviewer") or "").strip()
        text, human = p["proposed"], False
        if decision in ("reject", "no", "n", "отклонить"):
            stats["rejected"] += 1
            continue
        if decision in ("ok", "yes", "y", "да"):
            human = bool(reviewer) or True
        elif decision in ("edit", "fix", "правка"):
            if (row.get("final_text") or "").strip():
                text, human = row["final_text"], True
        flag = {"changed": True, "reviewed_by_human": human, "issues": p["issues"], "origin": p["origin"],
                "original": p["original"] or None}
        if human and reviewer:
            flag["reviewer"] = reviewer
        flags[key] = flag
        if p["missing"]:
            added[key] = text
            stats["added"] += 1
        else:
            changes[key] = text
        stats["changed"] += 1
        stats["reviewed_by_human"] += int(human)
    write_fixed(src_arb, changes, flags, out_path, added)
    return stats


def write_review_html(props: Dict[str, dict], path: str, lang_name: str) -> None:
    import html
    rows = []
    for i, (k, p) in enumerate(props.items()):
        rows.append(
            '<tr data-k="%s"><td><code>%s</code><br><small>%s · %s</small></td><td class="s">%s</td><td class="s">%s</td>'
            '<td><textarea rows="3" class="f">%s</textarea></td><td><select class="d"><option value="">—</option>'
            '<option value="ok">ok (верно)</option><option value="edit">правка</option><option value="reject">отклонить</option></select></td></tr>' % (
                html.escape(k), html.escape(k), html.escape(", ".join(p["issues"])), p["origin"], html.escape(p["source"]),
                html.escape(p["original"]), html.escape(p["proposed"])))
    doc = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>locqa review — {lang}</title>
<style>body{{font:14px system-ui;margin:16px;background:#fafafc;color:#1a1c24}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccd;padding:6px;vertical-align:top}}.s{{white-space:pre-wrap;max-width:280px}}textarea{{width:100%;min-width:260px}}
th{{position:sticky;top:0;background:#fff}}button,input{{padding:6px 10px}}</style></head><body>
<h2>Проверка исправлений ({lang}) — {n} строк</h2>
<p>Для каждой строки: сравните оригинал (ru), текущий перевод и предложение. Выберите <b>ok</b>, если предложение верно; <b>правка</b> — исправьте текст в поле;
<b>отклонить</b> — оставить как было. Строки без решения остаются непроверенными (<code>reviewed_by_human=false</code>).</p>
<p>Ваше имя: <input id="who"> <button onclick="exp()">Скачать review.csv</button> <span id="c"></span></p>
<table><thead><tr><th>ключ</th><th>оригинал (ru)</th><th>сейчас</th><th>предложение / финальный текст</th><th>решение</th></tr></thead><tbody>{rows}</tbody></table>
<script>
const rows=[...document.querySelectorAll('tbody tr')];
const ORIG={orig};
function q(s){{return '"'+String(s).replace(/"/g,'""')+'"'}}
function exp(){{const who=document.getElementById('who').value;let out=['key,issue_types,source,original,proposed,origin,decision,final_text,reviewer'];
rows.forEach(r=>{{const k=r.dataset.k,d=r.querySelector('.d').value,t=r.querySelector('.f').value,o=ORIG[k];
out.push([k,o.i,o.s,o.o,o.p,o.g,d,d=='edit'?t:'',d?who:''].map(q).join(','))}});
const b=new Blob(['\\ufeff'+out.join('\\r\\n')],{{type:'text/csv;charset=utf-8'}});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='review.csv';a.click()}}
document.addEventListener('change',()=>{{document.getElementById('c').textContent=rows.filter(r=>r.querySelector('.d').value).length+' / '+rows.length+' проверено'}});
</script></body></html>""".format(lang=html.escape(lang_name), n=len(props), rows="\n".join(rows),
                                 orig=json.dumps({k: {"i": "|".join(p["issues"]), "s": p["source"], "o": p["original"], "p": p["proposed"], "g": p["origin"]}
                                                  for k, p in props.items()}, ensure_ascii=False).replace("</", "<\\/"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
