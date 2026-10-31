"""Report writers: machine-readable report.json and a self-contained HTML report."""
from __future__ import annotations

import html
import json
from typing import List

from .core import Finding, ISSUE_TYPES


def write_json(findings: List[Finding], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([f.to_dict() for f in findings], fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_summary(summary: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


TYPE_DOC = {
    "untranslated": "строка отсутствует", "same_as_source": "совпадает с русской", "placeholder_mismatch": "плейсхолдеры/теги",
    "plural_mismatch": "ICU-плюралы", "glossary_violation": "термин не по глоссарию", "length_overflow": "слишком длинно для кнопки",
    "machine_translation_suspect": "признаки машинного перевода", "inconsistent_term": "термин переведён по-разному",
    "suffix_harmony": "аффикс после плейсхолдера", "orthography": "орфография / буквы", "wrong_language": "текст на другом языке",
}


def write_html(findings: List[Finding], summary: dict, path: str) -> None:
    rows = []
    for f in findings:
        rows.append(
            '<tr data-sev="%s" data-type="%s"><td><code>%s</code></td><td><span class="t">%s</span></td>'
            '<td><span class="sev %s">%s</span></td><td class="src">%s</td><td class="tgt">%s</td>'
            '<td>%s</td><td class="sg">%s</td><td>%.2f</td><td>%s</td></tr>' % (
                f.severity, f.issue_type, html.escape(f.key), f.issue_type, f.severity, f.severity,
                html.escape(f.source), html.escape(f.target), html.escape(f.evidence),
                html.escape(f.suggestion) if f.suggestion else "—", f.confidence,
                "да" if f.reviewed_by_human else "нет"))
    max_t = max([1] + list(summary["by_type"].values()))
    bars = "".join(
        '<div class="bar" data-type="%s"><span>%s</span><i style="width:%d%%"></i><b>%d</b></div>' % (
            t, t, int(100 * n / max_t), n) for t, n in summary["by_type"].items())
    opts = "".join('<option value="%s">%s — %s</option>' % (t, t, TYPE_DOC[t]) for t in ISSUE_TYPES)
    doc = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>locqa — {lang} ({native})</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#0f1117;--fg:#e8e8ee;--mut:#9aa0b4;--card:#181b25;--line:#2a2f3f;--ac:#7bd88f}}
@media(prefers-color-scheme:light){{:root{{--bg:#fafafc;--fg:#1a1c24;--mut:#5b6178;--card:#fff;--line:#dde0ea;--ac:#1f8a3b}}}}
body{{margin:0;font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
main{{max-width:1400px;margin:0 auto;padding:24px 16px}}h1{{margin:0 0 4px}}.mut{{color:var(--mut)}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:120px}}
.card b{{display:block;font-size:24px}}.bars{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:6px 24px;margin:12px 0}}
.bar{{display:grid;grid-template-columns:210px 1fr 40px;align-items:center;gap:8px;cursor:pointer}}.bar i{{display:block;height:8px;background:var(--ac);border-radius:4px;min-width:2px}}
.bar b{{text-align:right}}.tools{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}}input,select{{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}}th,td{{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}
th{{position:sticky;top:0;background:var(--card)}}.sev{{padding:1px 8px;border-radius:10px;font-size:12px}}.sev.high{{background:#c0392b;color:#fff}}.sev.medium{{background:#d49a00;color:#111}}.sev.low{{background:#566;color:#fff}}
.src,.tgt,.sg{{max-width:260px;word-break:break-word;white-space:pre-wrap}}.t{{font-size:12px;color:var(--mut)}}code{{font-size:12px}}
</style></head><body><main>
<h1>locqa — отчёт по {lang} ({native})</h1>
<div class="mut">{src} → {tgt} · ключей: {sk} / {tk} · глоссарий: {gl} терминов · справочные языки: {refs}</div>
<div class="cards"><div class="card"><b>{n}</b>находок</div><div class="card"><b>{ak}</b>ключей затронуто</div>
<div class="card"><b>{h}</b>high</div><div class="card"><b>{m}</b>medium</div><div class="card"><b>{l}</b>low</div></div>
<div class="bars">{bars}</div>
<div class="tools"><input id="q" placeholder="поиск по ключу / тексту / evidence"><select id="ty"><option value="">все типы</option>{opts}</select>
<select id="sv"><option value="">любая важность</option><option>high</option><option>medium</option><option>low</option></select>
<span class="mut" id="cnt"></span></div>
<table><thead><tr><th>ключ</th><th>тип</th><th>важн.</th><th>источник (ru)</th><th>перевод ({code})</th><th>почему это ошибка</th><th>предложение</th><th>conf</th><th>проверил человек</th></tr></thead>
<tbody id="tb">{rows}</tbody></table>
<script>
const q=document.getElementById('q'),ty=document.getElementById('ty'),sv=document.getElementById('sv'),cnt=document.getElementById('cnt');
function f(){{const s=q.value.toLowerCase();let n=0;document.querySelectorAll('#tb tr').forEach(r=>{{const ok=(!ty.value||r.dataset.type==ty.value)&&(!sv.value||r.dataset.sev==sv.value)&&(!s||r.textContent.toLowerCase().includes(s));r.style.display=ok?'':'none';if(ok)n++}});cnt.textContent=n+' показано'}}
[q,ty,sv].forEach(e=>e.addEventListener('input',f));document.querySelectorAll('.bar').forEach(b=>b.addEventListener('click',()=>{{ty.value=b.dataset.type;f()}}));f();
</script></main></body></html>""".format(
        lang=html.escape(summary["language_name"]), native=html.escape(summary["language_native"]),
        code=html.escape(summary["language"]), src=html.escape(summary["source_file"]), tgt=html.escape(summary["target_file"]),
        sk=summary["source_keys"], tk=summary["target_keys"], gl=summary["glossary_terms"],
        refs=", ".join(summary["reference_languages"]) or "нет", n=summary["findings"], ak=summary["affected_keys"],
        h=summary["by_severity"]["high"], m=summary["by_severity"]["medium"], l=summary["by_severity"]["low"],
        bars=bars, opts=opts, rows="\n".join(rows))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
