"""Rule-based detectors. Every detector returns ``Finding`` objects with human-readable evidence.

Nothing here needs network access or an API key. Language specific behaviour is taken
from ``ctx.lang`` (a ``LangProfile``) - there is no hidden Kazakh default.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import icu
from .core import Context, Finding, norm, short_source
from .langs import (KK_SPECIAL, UZ_APOSTROPHES, _RU_FUNC, guess_language, has_cyrillic, has_latin, strip_markup,
                    words)

DEFAULT_IGNORE_KEYS = {"currencySymbol", "lang", "description"}

# ---------------------------------------------------------------------------------------------------- helpers
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(s: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in s.lower())


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", strip_markup(s)).strip()


def key_hint(key: str, src: str) -> str:
    k = key.lower()
    for token, label in (("button", "кнопку"), ("btn", "кнопку"), ("tab", "вкладку"), ("title", "заголовок"),
                         ("header", "заголовок"), ("label", "подпись"), ("short", "сокращение")):
        if token in k:
            return "ключ похож на %s" % label
    return "исходник из %d симв. — короткий элемент интерфейса" % len(plain(src))


def match_case(sample_src: str, text: str) -> str:
    """Adapt capitalisation of ``text`` to the shape of ``sample_src`` (UPPER / Capitalised / lower)."""
    letters = [c for c in sample_src if c.isalpha()]
    if len(letters) >= 2 and all(c.isupper() for c in letters):
        return text.upper()
    if letters and letters[0].isupper():
        return text[:1].upper() + text[1:]
    if letters and letters[0].islower():
        return text[:1].lower() + text[1:]
    return text


def is_dev_note(ctx: Context, src: str) -> bool:
    if ctx.src_lang.code == "en":
        return False
    code, conf, _ = guess_language(src)
    return code == "en" and conf >= 0.9 and len(words(src)) >= 4


def is_translatable(ctx: Context, src: str) -> bool:
    p = plain(src)
    if len(re.findall(r"[^\W\d_]", p)) < 2:
        return False
    if is_dev_note(ctx, src):
        return False
    return True


def lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def tm_best(ctx: Context, src: str, exclude: Optional[str] = None) -> Optional[Tuple[str, int, int]]:
    c = ctx.tm.get(norm(src))
    if not c:
        return None
    total = sum(c.values())
    for t, n in c.most_common():
        if exclude is not None and norm(t) == norm(exclude):
            continue
        return t, n, total
    return None


def F(ctx: Context, key: str, typ: str, sev: str, evidence: str, conf: float,
      suggestion: Optional[str] = None, target: Optional[str] = None) -> Finding:
    return Finding(key=key, issue_type=typ, severity=sev, source=ctx.source.messages.get(key, ""),
                   target=ctx.target.messages.get(key, "") if target is None else target,
                   evidence=evidence, suggestion=suggestion, confidence=conf)


# ---------------------------------------------------------------------------------------------------- untranslated
def d_untranslated(ctx: Context, key: str, src: str, tgt: Optional[str]) -> List[Finding]:
    if tgt is not None and tgt.strip():
        return []
    if not is_translatable(ctx, src):
        return []
    if tgt is not None and any((a.messages.get(key) is not None and not a.messages.get(key).strip()) for a in ctx.refs.values()):
        return []                    # empty in other languages too: intentional (word-order dependent fragment)
    why = "ключ отсутствует в %s-файле" % ctx.lang.code if tgt is None else "значение пустое"
    best = tm_best(ctx, src)
    sugg = best[0] if best and best[2] >= 1 and len(plain(src).split()) <= 3 else None
    ev = "%s; в игре строка не покажется или упадёт на запасной язык" % why
    if sugg:
        ev += "; тот же исходник уже переведён в другом ключе"
    return [F(ctx, key, "untranslated", "high", ev, 0.99, sugg, target="")]


# ---------------------------------------------------------------------------------------------------- placeholders / ICU
def d_placeholders(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    out: List[Finding] = []
    sp, tp = icu.placeholders(src), icu.placeholders(tgt)
    for n in icu.parse_icu(src):
        sp[n.arg] += 0 if n.arg in sp else 1
    for n in icu.parse_icu(tgt):
        tp[n.arg] += 0 if n.arg in tp else 1
    missing = [p for p in sp if p not in tp]
    extra = [p for p in tp if p not in sp]
    fixed = tgt
    notes: List[str] = []
    unresolved_missing: List[str] = []
    for name in missing:
        bare = re.search(r"(?<![\w{])%s(?![\w}])" % re.escape(name), strip_for_bare(tgt))
        near = difflib.get_close_matches(name, extra, n=1, cutoff=0.75)
        if near:
            fixed = fixed.replace("{%s}" % near[0], "{%s}" % name)
            extra.remove(near[0])
            notes.append("имя плейсхолдера {%s} искажено до {%s}" % (name, near[0]))
        elif bare:
            fixed = re.sub(r"(?<![\w{])%s(?![\w}])" % re.escape(name), "{%s}" % name, fixed, count=1)
            notes.append("у плейсхолдера {%s} потеряны фигурные скобки — в тексте осталось слово «%s»" % (name, name))
        else:
            unresolved_missing.append(name)
    if notes:
        out.append(F(ctx, key, "placeholder_mismatch", "high",
                     "; ".join(notes) + "; Flutter gen-l10n не соберёт такую строку или покажет «%s» как текст" % notes[0].split("{")[1].split("}")[0],
                     0.97, fixed if fixed != tgt else None))
    if unresolved_missing:
        out.append(F(ctx, key, "placeholder_mismatch", "high",
                     "в переводе нет плейсхолдера %s из оригинала — значение не будет подставлено" %
                     ", ".join("{%s}" % m for m in unresolved_missing), 0.93, None))
    if extra:
        out.append(F(ctx, key, "placeholder_mismatch", "high",
                     "в переводе есть плейсхолдер %s, которого нет в оригинале — gen-l10n выдаст ошибку" %
                     ", ".join("{%s}" % e for e in extra), 0.93, None))
    # repeated counts
    for name in set(sp) & set(tp):
        if sp[name] != tp[name] and sp[name] > 0 and tp[name] > 0:
            out.append(F(ctx, key, "placeholder_mismatch", "low",
                         "{%s} встречается %d раз в оригинале и %d в переводе" % (name, sp[name], tp[name]), 0.55, None))
    # printf-style and tags
    sf, tf = icu.printf_tokens(src), icu.printf_tokens(tgt)
    if sf != tf:
        out.append(F(ctx, key, "placeholder_mismatch", "high",
                     "форматные маркеры не совпадают: оригинал %s, перевод %s" %
                     (dict(sf) or "нет", dict(tf) or "нет"), 0.9, None))
    st, tt = icu.tags(src), icu.tags(tgt)
    if st != tt:
        out.append(F(ctx, key, "placeholder_mismatch", "medium",
                     "теги разметки не совпадают: оригинал %s, перевод %s" % (dict(st) or "нет", dict(tt) or "нет"), 0.85, None))
    ok_s, _ = icu.balanced(src)
    ok_t, why = icu.balanced(tgt)
    if ok_s and not ok_t:
        out.append(F(ctx, key, "placeholder_mismatch", "high", "ломаный ICU-синтаксис: " + why, 0.95, None))
    return out


def strip_for_bare(text: str) -> str:
    """Text where already-correct placeholders are removed so bare words can be spotted."""
    return re.sub(r"\{[^{}]*\}", " ", text)


def d_plural(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    out: List[Finding] = []
    sn, tn = icu.parse_icu(src), icu.parse_icu(tgt)
    if not sn and not tn:
        if re.search(r",\s*(plural|select)\s*,", tgt):
            out.append(F(ctx, key, "plural_mismatch", "high", "похоже на ICU plural/select, но разбор не удался (скобки/ветки)", 0.8))
        return out
    if sn and not tn:
        out.append(F(ctx, key, "plural_mismatch", "high",
                     "в оригинале есть ICU %s по {%s}, в переводе его нет — форма числа не будет выбираться" %
                     (sn[0].kind, sn[0].arg), 0.95))
        return out
    if tn and not sn:
        out.append(F(ctx, key, "plural_mismatch", "medium", "в переводе появился ICU %s, которого нет в оригинале" % tn[0].kind, 0.8))
    allowed = set(ctx.lang.plural_categories)
    for node in tn:
        if node.kind != "plural":
            if "other" not in node.branches:
                out.append(F(ctx, key, "plural_mismatch", "high", "в select по {%s} нет обязательной ветки other" % node.arg, 0.95))
            continue
        if "other" not in node.branches:
            out.append(F(ctx, key, "plural_mismatch", "high",
                         "в plural по {%s} нет обязательной ветки other: gen-l10n не соберёт файл" % node.arg, 0.97))
        if "one" not in node.branches and "one" in allowed and not any(b.startswith("=1") for b in node.branches):
            out.append(F(ctx, key, "plural_mismatch", "medium",
                         "для языка %s в plural по {%s} нужна ветка one (CLDR: %s)" % (ctx.lang.code, node.arg, "/".join(sorted(allowed))), 0.8))
        extra_cat = [b for b in node.branches if not b.startswith("=") and b not in allowed and b != "other"]
        if extra_cat:
            out.append(F(ctx, key, "plural_mismatch", "low",
                         "ветки %s не используются в %s (там только %s) — мёртвый код, ошибка переноса из русского" %
                         (", ".join(extra_cat), ctx.lang.code, "/".join(sorted(allowed))), 0.7))
        s_args = {n.arg for n in sn}
        if sn and node.arg not in s_args:
            out.append(F(ctx, key, "plural_mismatch", "high", "plural по {%s}, а в оригинале по %s" % (node.arg, ", ".join("{%s}" % a for a in s_args)), 0.9))
    return out


# ---------------------------------------------------------------------------------------------------- same_as_source
def d_same_as_source(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    if norm(src) != norm(tgt) or not is_translatable(ctx, src):
        return []
    p = plain(src)
    # Latin-only source: brands, English words, hashtags -> legitimately identical
    if not has_cyrillic(p) and ctx.src_lang.script == "cyrillic":
        return []
    if norm(p) in {norm(b) for b in ctx.options.get("brands", [])}:
        return []
    toks = words(src)
    funcs = [w for w in toks if w.lower() in _RU_FUNC]
    best = tm_best(ctx, src)
    sugg = best[0] if best else None
    # loanword evidence 1: the same word is used untranslated inside other target strings of this file
    occurrences = sum(ctx.vocab.get(w.lower(), 0) for w in toks) / max(1, len(toks))
    # loanword evidence 2: Uzbek reference is a transliteration of the Russian word
    uz_ref = ctx.ref("uz", key) if ctx.lang.code != "uz" else None
    translit_match = False
    if uz_ref:
        a, b = translit(p), re.sub(r"[%s]" % re.escape(UZ_APOSTROPHES), "", plain(uz_ref).lower())
        a = re.sub(r"[%s]" % re.escape(UZ_APOSTROPHES), "", a)
        translit_match = difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    n = len(toks)
    if ctx.lang.script == "latin":           # Cyrillic left in a Latin-script language
        return [F(ctx, key, "same_as_source", "high",
                  "перевод совпадает с русским оригиналом, остался кириллицей в %s-файле (латиница)" % ctx.lang.code, 0.95, sugg)]
    if n >= 3 or funcs:
        sev, conf = "high", 0.93
        ev = "перевод дословно совпадает с русским оригиналом (%d слов, предложение) — не переведено" % n
    elif translit_match:
        sev, conf = "low", 0.3
        ev = ("совпадает с русским, но в узбекском то же слово («%s») — вероятно общее заимствование; "
              "проверьте, как говорят игроки" % plain(uz_ref))
    elif occurrences >= 4:
        sev, conf = "low", 0.35
        ev = "совпадает с русским; такое слово без перевода встречается в файле %d раз — вероятно устоявшееся заимствование" % int(occurrences)
    else:
        sev, conf = "medium", 0.65
        ev = "совпадает с русским оригиналом (короткий термин); исключения — бренды, имена, цифры — не подходят"
    if sugg:
        ev += "; в других ключах тот же исходник переведён как «%s»" % sugg
        conf = min(0.97, conf + 0.1)
    return [F(ctx, key, "same_as_source", sev, ev, conf, sugg)]


# ---------------------------------------------------------------------------------------------------- wrong_language
def _latin_share(ws: List[str], src_tokens: set, brands: set) -> Tuple[List[str], float]:
    lat = [w for w in ws if has_latin(w) and not has_cyrillic(w) and w.lower() not in src_tokens and w.lower() not in brands]
    total = sum(len(w) for w in ws) or 1
    return lat, sum(len(w) for w in lat) / total


def is_cyr_word_only(w: str) -> bool:
    return has_cyrillic(w) and not has_latin(w)


def ref_language(ctx: Context, key: str, tgt: str) -> Optional[Tuple[str, float]]:
    """If the target text is (almost) identical to another language's string for the same key."""
    hits = []
    for code, arb in ctx.refs.items():
        r = arb.messages.get(key)
        if r and norm(r) and difflib.SequenceMatcher(None, norm(r), norm(tgt)).ratio() >= 0.9:
            hits.append(code)
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0], 0.98
    return ("en" if "en" in hits else hits[0]), 0.98


LANG_LABEL = {"uz": "узбекский", "en": "английский", "pt": "португальский", "es": "испанский", "ru": "русский",
              "kk": "казахский", "latin": "неопознанная латиница", "cyr": "кириллица без казахских букв"}


def d_wrong_language(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    if norm(src) == norm(tgt) or not is_translatable(ctx, src):
        return []
    ws = words(tgt)
    if not ws:
        return []
    brands = {b.lower() for b in ctx.options.get("brands", [])}
    src_tokens = {w.lower() for w in words(src)}
    best = tm_best(ctx, src)
    sugg = best[0] if best else None
    tcode = ctx.lang.code
    # ---- Latin-script target language (uz): look for Cyrillic and for non-Uzbek Latin
    if ctx.lang.script == "latin":
        cyr = [w for w in ws if is_cyr_word_only(w)]
        if cyr and sum(len(w) for w in cyr) / sum(len(w) for w in ws) >= 0.4:
            kk_letters = sum(1 for ch in tgt if ch in KK_SPECIAL)
            who = "казахский" if kk_letters else "русский/кириллица"
            return [F(ctx, key, "wrong_language", "high",
                      "в %s-файле текст написан кириллицей (%s): «%s»" % (tcode, who, " ".join(cyr[:4])),
                      0.95 if kk_letters else 0.85, sugg)]
        lat = [w for w in ws if has_latin(w) and not has_cyrillic(w) and w.lower() not in src_tokens and w.lower() not in brands]
        if len(lat) >= 3 and not all(len(w) == 1 for w in lat):
            from .langs import _score_latin
            sc = _score_latin(lat)
            code, conf, why = guess_language(" ".join(lat))
            if code in ("en", "pt", "es") and conf >= 0.8 and sc["uz"] <= 1:
                return [F(ctx, key, "wrong_language", "medium",
                          "текст выглядит как %s, а не %s: «%s» (%s)" % (LANG_LABEL[code], ctx.lang.name, " ".join(lat[:6]), why),
                          min(0.9, conf - 0.05), sugg)]
        return []
    # ---- Cyrillic-script target language (kk)
    lat, share = _latin_share(ws, src_tokens, brands)
    if lat and share >= 0.6 and max(len(w) for w in lat) >= 3:
        code, conf, why = guess_language(" ".join(lat))
        rl = ref_language(ctx, key, tgt)
        if rl:
            if rl[0] == tcode:
                return []
            if code in ("latin", "cyr") and (rl[0].startswith("en")):
                return []              # unidentified Latin text equal to the English file: a brand, name or abbreviation
            if code in ("latin", "cyr") or rl[0] != code:
                code, conf, why = rl[0], rl[1], "совпадает с %s-версией этого же ключа" % rl[0]
            else:
                conf = max(conf, 0.97)
                why += "; совпадает с %s-версией этого же ключа" % rl[0]
        if code == tcode:
            return []
        if "english" in key.lower() and code == "en":
            return []                      # key name says the text is intentionally English
        label = LANG_LABEL.get(code, code)
        if code in ("latin", "cyr"):
            # unidentified Latin: most likely a brand / event name / abbreviation kept in Latin
            if rl is None and (len(lat) <= 2 or all(w.isupper() for w in lat)):
                return [F(ctx, key, "wrong_language", "low",
                          "латиница в %s-файле при кириллическом оригинале: «%s»; язык не определён — возможно, название/бренд, но стоит проверить" %
                          (tcode, " ".join(lat[:6])), 0.3, sugg)]
        return [F(ctx, key, "wrong_language", "high",
                  "в %s-файле стоит текст на другом языке: похоже на %s (%s): «%s»" %
                  (tcode, label, why, " ".join(lat[:6])), max(0.5, min(0.97, conf)), sugg)]
    kk_letters = sum(1 for ch in tgt if ch in ctx.lang.special_letters)
    low = [w.lower() for w in ws]
    hits = [w for w in low if w in _RU_FUNC]
    if kk_letters == 0 and len(ws) >= 3 and len(hits) >= 2:
        return [F(ctx, key, "wrong_language", "high",
                  "текст на русском, а не на %s: служебные слова %s, нет специфичных букв %s" %
                  (ctx.lang.name, ", ".join(hits[:4]), ctx.lang.special_letters[:9]), 0.85, sugg)]
    return []


# ---------------------------------------------------------------------------------------------------- length_overflow
def d_length(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    if not short_source(src) or norm(src) == norm(tgt):
        return []
    ps, pt = plain(src), plain(tgt)
    ls, lt = len(ps), len(pt)
    if ls == 0:
        return []
    fragment = (ps[:1].islower() or ps[-1:] in "?:") and ls <= 8
    limit = max(ctx.lang.max_ratio_short * ls, ls + 20)
    if lt <= limit:
        return []
    toks = tuple(w.lower() for w in words(tgt))
    head = None
    tail_info = ""
    for suf, cnt in ctx.boilerplate:
        n = len(suf)
        if len(toks) > n and toks[-n:] == suf:
            wl = words(tgt)
            head_words = wl[:-n]
            head = " ".join(head_words)
            head = match_case(src, head)
            tail_info = "; хвост «%s» повторяется в %d ключах с короткими исходниками — это вставка, а не перевод" % (" ".join(suf), cnt)
            break
    if fragment and head is None:
        return []                  # tail of a sentence glued from several keys; length is not comparable
    ref_bits = []
    for code in ("uz", "en"):
        r = ctx.ref(code, key)
        if r and code != ctx.lang.code:
            ref_bits.append("%s: %d симв." % (code, len(plain(r))))
    if head is None and not (lt > 6 * ls or (lt > 4 * ls and lt > 35)):
        return []                  # long but no padding evidence: natural expansion in an agglutinative language
    sev = "high" if head or lt > 4 * ls else "medium"
    conf = 0.95 if head else 0.8
    ev = "%d символов против %d в исходнике, %s%s%s" % (lt, ls, key_hint(key, src), tail_info,
                                                       ("; " + ", ".join(ref_bits)) if ref_bits else "")
    sugg = head
    if not sugg:
        best = tm_best(ctx, src, exclude=tgt)
        if best and len(plain(best[0])) <= limit:
            sugg = best[0]
    return [F(ctx, key, "length_overflow", sev, ev, conf, sugg)]


# ---------------------------------------------------------------------------------------------------- glossary
def d_glossary(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    out: List[Finding] = []
    if norm(src) == norm(tgt):
        return out
    low = tgt.lower()
    for e in ctx.glossary.for_lang(ctx.lang.code):
        if not e.source_pattern().search(src):
            continue
        from .glossary import stem
        allowed = e.allowed(ctx.lang.code)
        a_stems = [stem(a, ctx.lang.code) if len(a) > 3 else a.lower() for a in allowed]
        if any(s in low for s in a_stems):
            continue
        bad = [b for b in e.bad(ctx.lang.code) if b in low]
        canon = allowed[0]
        sugg = None
        if bad:
            m = re.search(r"\b%s\w*" % re.escape(bad[0]), tgt, re.IGNORECASE)
            if m:
                word = m.group(0)
                tail = word[len(bad[0]):]
                sugg = tgt.replace(word, match_case(word, canon) + (tail if tail else ""), 1)
        ev = ("термин «%s» по глоссарию → «%s»%s; в переводе не найден" %
              (e.ru, "» / «".join(allowed), (" (%s)" % e.comment) if e.comment else ""))
        if bad:
            ev += ", вместо него использовано «%s»" % bad[0]
        out.append(F(ctx, key, "glossary_violation", "high" if bad else "medium", ev, 0.9 if bad else 0.6, sugg))
    return out


# ---------------------------------------------------------------------------------------------------- suffix harmony
def d_suffix(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    rx = ctx.lang.harmony_suffix_re
    if not rx:
        return []
    out: List[Finding] = []
    for m in re.finditer(r"\{([A-Za-z_]\w*)" + rx, tgt):
        name = m.group(1)
        suffix = m.group(0)[len(name) + 2:]
        sugg = reformulate(ctx, tgt, m, name)
        if ctx.lang.code == "kk":
            why = ("после {%s} жёстко записан аффикс «%s»: в казахском окончание зависит от последнего звука "
                   "имени, которое подставляется в игре (-ға/-ге/-қа/-ке, -ның/-нің/-дың/-дің …) — для части значений форма будет неверной" % (name, suffix.lstrip("-’'‑–")))
        else:
            why = ("после {%s} жёстко записан аффикс «%s»: форма зависит от конца подставляемого значения "
                   "(например -ga/-ka/-qa), нужна переформулировка или обработка в коде" % (name, suffix.lstrip("-’'‑–")))
        out.append(F(ctx, key, "suffix_harmony", "medium", why, 0.9, sugg))
        break  # one finding per string is enough
    return out


def reformulate(ctx: Context, tgt: str, m: "re.Match", name: str) -> Optional[str]:
    """Rule-based draft: move the placeholder behind a label so no affix follows it.

    Only used when the placeholder opens the string; it is a draft for the human reviewer.
    """
    if m.start() != 0:
        return None
    rest = tgt[m.end():].lstrip()
    if not rest or len(rest.split()) > 6:
        return None
    sentence_tail = ""
    mm = re.match(r"^(.*?)([.…!?:]*)$", rest, re.S)
    if mm:
        rest, sentence_tail = mm.group(1), mm.group(2)
    if "." in rest:
        return None
    return "%s: {%s}%s" % (rest[:1].upper() + rest[1:], name, sentence_tail)


# ---------------------------------------------------------------------------------------------------- orthography
_LAT2CYR = {"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к", "m": "м", "t": "т",
            "i": "і", "h": "һ", "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О",
            "P": "Р", "T": "Т", "X": "Х", "I": "І"}
_CYR2LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "j", "з": "z", "и": "i", "й": "y",
            "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
            "ф": "f", "х": "x", "і": "i", "ч": "ch", "ш": "sh"}
_CYR2LAT.update({k.upper(): v.upper() for k, v in list(_CYR2LAT.items())})
_KK_SUBS = {"к": ["қ"], "қ": ["к"], "а": ["ә"], "ә": ["а"], "г": ["ғ"], "ғ": ["г"], "н": ["ң"], "ң": ["н"],
            "о": ["ө"], "ө": ["о"], "у": ["ұ", "ү"], "ұ": ["у"], "ү": ["у"], "х": ["һ"], "һ": ["х"], "и": ["і"],
            "і": ["и", "ы"], "ы": ["і"]}
_KK_NAME = {"қ": "К", "ә": "А", "ғ": "Г", "ң": "Н", "ө": "О", "ұ": "У", "ү": "У", "һ": "Х", "і": "И"}


def _mixed_script(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    out = []
    for w in re.findall(r"[^\W\d_]+", strip_markup(tgt)):
        if has_cyrillic(w) and has_latin(w):
            if ctx.lang.script == "cyrillic":
                fixed = "".join(_LAT2CYR.get(ch, ch) for ch in w)
            else:
                fixed = "".join(_CYR2LAT.get(ch, ch) for ch in w)
                # ALL-CAPS words: keep the case of the Latin neighbours
                if w.isupper():
                    fixed = fixed.upper()
            if ctx.lang.script == "latin" and not re.fullmatch(r"[A-Za-z]+", fixed):
                continue
            if ctx.lang.script == "cyrillic" and has_latin(fixed):
                continue
            out.append(F(ctx, key, "orthography", "high",
                         "в слове «%s» смешаны кириллица и латиница (визуально похожие буквы) — слово не найдётся поиском и сломает сортировку/шрифт" % w,
                         0.93, tgt.replace(w, fixed, 1)))
    return out


def _kk_analog_letters(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    """Kazakh letters typed with Russian analogues (қ→к, ә→а, ғ→г ...): vocabulary based."""
    if ctx.lang.code != "kk":
        return []
    out = []
    seen = set()
    for w in words(tgt):
        lw = w.lower()
        if lw in seen or len(lw) < 4 or not is_cyr(lw) or ctx.vocab[lw] > 1:
            continue
        seen.add(lw)
        best = None
        for i, ch in enumerate(lw):
            for rep in _KK_SUBS.get(ch, []):
                cand = lw[:i] + rep + lw[i + 1:]
                c = ctx.vocab.get(cand, 0)
                if c >= 3 and c >= 3 * max(1, ctx.vocab[lw]):
                    if not best or c > best[1]:
                        best = (cand, c, ch, rep)
        if best:
            cand, c, ch, rep = best
            fixed = re.sub(re.escape(w), match_case(w, cand), tgt, count=1, flags=re.IGNORECASE)
            out.append(F(ctx, key, "orthography", "medium",
                         "«%s» встречается 1 раз, а «%s» — %d раз: вероятно, «%s» набрано русским аналогом вместо «%s»" % (w, cand, c, ch, rep),
                         0.8, fixed))
    return out


def is_cyr(w: str) -> bool:
    return has_cyrillic(w) and not has_latin(w)


def _uz_apostrophes(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    if ctx.lang.code != "uz" or not ctx.apostrophe_main:
        return []
    out = []
    main_og, main_tut = ctx.apostrophe_main.split("|")
    for m in re.finditer(r"([oOgG])([%s])" % re.escape(UZ_APOSTROPHES), tgt):
        if m.group(2) != main_og:
            fixed = re.sub(r"([oOgG])[%s]" % re.escape(UZ_APOSTROPHES), lambda mm: mm.group(1) + main_og, tgt)
            out.append(F(ctx, key, "orthography", "low",
                         "в o‘/g‘ использован знак «%s», в остальном файле — «%s»: несколько вариантов апострофа ломают поиск и сравнение" % (m.group(2), main_og),
                         0.8, fixed))
            break
    for m in re.finditer(r"(?<![oOgG])(?<=[A-Za-z])([%s])(?=[A-Za-z])" % re.escape(UZ_APOSTROPHES), tgt):
        if m.group(1) != main_tut:
            fixed = re.sub(r"(?<![oOgG])(?<=[A-Za-z])[%s](?=[A-Za-z])" % re.escape(UZ_APOSTROPHES), main_tut, tgt)
            out.append(F(ctx, key, "orthography", "low",
                         "знак «%s» (тутуқ белгиси: ma’lumot) отличается от основного «%s» в файле" % (m.group(1), main_tut),
                         0.7, fixed))
            break
    return out


def detect_apostrophes(target_texts: Iterable[str]) -> Optional[str]:
    og, tut = Counter(), Counter()
    for t in target_texts:
        for m in re.finditer(r"[oOgG]([%s])" % re.escape(UZ_APOSTROPHES), t):
            og[m.group(1)] += 1
        for m in re.finditer(r"(?<![oOgG])(?<=[A-Za-z])([%s])(?=[A-Za-z])" % re.escape(UZ_APOSTROPHES), t):
            tut[m.group(1)] += 1
    if not og and not tut:
        return None
    return "%s|%s" % (og.most_common(1)[0][0] if og else "ʻ", tut.most_common(1)[0][0] if tut else "ʼ")


def d_orthography(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    if norm(src) == norm(tgt):
        return []
    return _mixed_script(ctx, key, src, tgt) + _kk_analog_letters(ctx, key, src, tgt) + _uz_apostrophes(ctx, key, src, tgt)


# ---------------------------------------------------------------------------------------------------- machine translation
_RU_ENDINGS = re.compile(r"(ий|ый|ой|ая|ое|ие|ые|ать|ять|ить|ется|ают|ует|ого|ему|ых|ими|ыми|ости|ение|ания|щий|ющий)$")


def d_machine(ctx: Context, key: str, src: str, tgt: str) -> List[Finding]:
    out: List[Finding] = []
    if norm(src) == norm(tgt) or ctx.lang.script != "cyrillic":
        return out
    kk = sum(1 for ch in tgt if ch in ctx.lang.special_letters)
    left = []
    for w in words(tgt):
        lw = w.lower()
        if not is_cyr(w) or any(ch in ctx.lang.special_letters for ch in lw) or len(lw) < 5:
            continue
        if _RU_ENDINGS.search(lw) and ctx.src_vocab.get(lw, 0) >= 1 and ctx.vocab.get(lw, 0) <= 1:
            left.append(w)
    funcs = [w for w in words(tgt) if w.lower() in _RU_FUNC]
    if left or (funcs and kk):
        bits = []
        if left:
            bits.append("русское слово с русским окончанием: «%s»" % "», «".join(left[:3]))
        if funcs:
            bits.append("русские служебные слова внутри казахского текста: «%s»" % "», «".join(funcs[:3]))
        out.append(F(ctx, key, "machine_translation_suspect", "medium" if funcs else "low",
                     "; ".join(bits) + " — признак подстрочного/машинного перевода", 0.55 if funcs else 0.4, None))
    # numbers dropped or changed
    def _nums(t: str) -> Counter:
        t = re.sub(r"(?<=\d)[ \u00a0.,](?=\d{3}(?!\d))", "", t)
        return Counter(re.findall(r"\d+", t))
    sn, tn = _nums(src), _nums(tgt)
    if sn and sn != tn and not left and not re.search(r"\d\s*/\s*\d|https?://", src):
        out.append(F(ctx, key, "machine_translation_suspect", "medium",
                     "числа в переводе не совпадают с оригиналом: %s против %s" % (sorted(sn), sorted(tn)), 0.6, None))
    return out


ALL_DETECTORS: List[Callable[[Context, str, str, str], List[Finding]]] = [
    d_placeholders, d_plural, d_same_as_source, d_wrong_language, d_length, d_glossary, d_suffix, d_orthography, d_machine,
]


# ---------------------------------------------------------------------------------------------------- global: inconsistent_term
def d_inconsistent(ctx: Context, findings_by_key: Dict[str, set]) -> List[Finding]:
    groups: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for key, src in ctx.source.messages.items():
        tgt = ctx.target.messages.get(key)
        if not tgt or key in ctx.options.get("ignore_keys", set()):
            continue
        if not is_translatable(ctx, src) or norm(src) == norm(tgt):
            continue
        if len(words(src)) > 4 or "wrong_language" in findings_by_key.get(key, ()) or "length_overflow" in findings_by_key.get(key, ()):
            continue
        groups[norm(src)][norm(tgt)].append(key)
    out: List[Finding] = []
    for nsrc, variants in groups.items():
        total = sum(len(v) for v in variants.values())
        if len(variants) < 2 or total < 2:
            continue
        ranked = sorted(variants.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        top_t, top_keys = ranked[0]
        tie = len(ranked) > 1 and len(ranked[1][1]) == len(top_keys)
        canon_text = ctx.target.messages[top_keys[0]]
        for t, keys in ranked[1:] if not tie else ranked:
            sim = difflib.SequenceMatcher(None, t, top_t).ratio()
            strong_majority = (not tie) and len(top_keys) >= 3 * len(keys) and len(top_keys) >= 3
            typo_like = sim >= 0.85 and lev(t, top_t) <= 2 and len(t) >= 6 and not tie
            if not (strong_majority or typo_like):
                continue                 # synonym / inflection-level variation: too noisy to report
            for k in keys:
                src = ctx.source.messages[k]
                spelling = typo_like
                sev = "medium" if spelling else "low"
                conf = 0.75 if spelling else (0.55 if len(top_keys) >= 2 * len(keys) else 0.4)
                others = ", ".join("«%s» (%d×)" % (ctx.target.messages[v[0]], len(v)) for tt, v in ranked if tt != t)
                ev = ("исходник «%s» в %d ключах переведён по-разному: здесь «%s», в других — %s" %
                      (plain(src), total, ctx.target.messages[k], others))
                if spelling:
                    ev += "; варианты отличаются на пару букв — вероятно, опечатка"
                sugg = None if tie else canon_text
                out.append(F(ctx, k, "inconsistent_term", sev, ev, conf, sugg))
    return out


# ---------------------------------------------------------------------------------------------------- global: term alignment
_STOP_RU = set("""этого этому этой этом которые который которая когда чтобы после перед через также только
будет будут нужно можно вашего вашей вашим ваших своего свой своей своих очень более менее между""".split())


def d_term_consistency(ctx: Context, findings_by_key: Dict[str, set]) -> List[Finding]:
    """Statistical term check: a Russian content word that is almost always rendered with the same
    target root, but not in a few keys, is reported as an inconsistent term. No glossary required."""
    P = 5
    ru_sets: Dict[str, set] = {}
    tg_sets: Dict[str, set] = {}
    for key, src in ctx.source.messages.items():
        tgt = ctx.target.messages.get(key)
        if not tgt or key in ctx.options["ignore_keys"] or norm(src) == norm(tgt):
            continue
        if findings_by_key.get(key, set()) & {"wrong_language", "length_overflow", "untranslated"}:
            continue
        ru_sets[key] = {w.lower()[:P] for w in words(src) if len(w) >= P and w.lower() not in _STOP_RU}
        tg_sets[key] = {w.lower()[:P] for w in words(tgt) if len(w) >= P}
    df_r, df_t, co = Counter(), Counter(), Counter()
    for k, rs in ru_sets.items():
        ts = tg_sets[k]
        df_r.update(rs)
        df_t.update(ts)
        for r in rs:
            for t in ts:
                co[(r, t)] += 1
    best: Dict[str, Tuple[str, int, float]] = {}
    for (r, t), c in co.items():
        if df_r[r] < 6 or df_r[r] > 80 or c < 5:
            continue
        dice = 2 * c / (df_r[r] + df_t[t])
        cover = c / df_r[r]
        if dice >= 0.65 and cover >= 0.85 and (r not in best or dice > best[r][2]):
            best[r] = (t, c, dice)
    out: List[Finding] = []
    done: set = set()
    for r, (t, c, dice) in best.items():
        missing = [k for k, rs in ru_sets.items() if r in rs and t not in tg_sets[k]]
        if not missing or len(missing) > min(4, 0.2 * df_r[r]):
            continue
        for k in missing:
            # a second root that is itself regularly used for this term = established synonym, not a slip
            synonym = any(co[(r, t2)] >= 3 and 2 * co[(r, t2)] / (df_r[r] + df_t[t2]) >= 0.08
                          for t2 in tg_sets[k] if t2 != t)
            if synonym:
                continue
            ru_word = next((w for w in words(ctx.source.messages[k]) if w.lower().startswith(r)), r)
            tg_words = [w for w in words(ctx.target.messages[k])]
            ev = ("термин «%s» в %d из %d ключей передан корнем «%s…», здесь иначе — разнобой терминологии" %
                  (ru_word, c, df_r[r], t))
            if k in done:
                continue
            done.add(k)
            out.append(F(ctx, k, "inconsistent_term", "low", ev, 0.5, None))
    return out
