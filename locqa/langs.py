"""Language profiles and lightweight language identification.

Every language-specific decision in locqa goes through a ``LangProfile`` that is
selected *explicitly* by the ``--lang`` option (or inferred from the target file's
``@@locale``). There is no shared mutable default: Uzbek is never processed with
Kazakh rules and vice versa (see tests/test_languages.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

CYR = "Ѐ-ӿ"
KK_SPECIAL = "әғқңөұүһіӘҒҚҢӨҰҮҺІ"
UZ_APOSTROPHES = "'‘’ʻʼ`´"

_WORD_RE = re.compile(r"[^\W\d_]+(?:[%s][^\W\d_]+)*" % re.escape(UZ_APOSTROPHES), re.UNICODE)


def strip_markup(text: str) -> str:
    """Remove ICU/printf placeholders, tags and escape sequences so only prose remains."""
    t = text.replace("\\n", " ").replace("\\t", " ").replace("\n", " ")
    prev = None
    while prev != t:                     # nested ICU braces
        prev = t
        t = re.sub(r"\{[^{}]*\}", " ", t)
    t = re.sub(r"</?\w+[^>]*>", " ", t)
    t = re.sub(r"%\d*\$?[sdfi]", " ", t)
    t = re.sub(r"[{}]", " ", t)
    return t


def words(text: str) -> List[str]:
    return _WORD_RE.findall(strip_markup(text))


def has_cyrillic(s: str) -> bool:
    return re.search("[%s]" % CYR, s) is not None


def has_latin(s: str) -> bool:
    return re.search("[A-Za-z]", s) is not None


def is_cyr_word(w: str) -> bool:
    return re.search("[%s]" % CYR, w) is not None and not has_latin(w)


# --------------------------------------------------------------------------- word lists for identification
_EN = set("""the to of and for you your with are not this that from have will can all new
get buy equipped level coins coin reward rewards sell buy open close start stop back next play shop store settings
profile bonus free time day days hours minutes seconds event rank player players team game battle pass season
equip unequip item items price cancel confirm error loading please try again select choose empty full""".split())
_PT = set("""para não você do da de dos das os as um uma com que é por perfil jogo aplicativo será favor fechado ser
excluir clique sua seu suas seus foi são está estão mais menos ou mas se em no na nos nas ao aos""".split())
_ES = set("""el la los las para con que de por una un tu tus es son está están no más menos o pero si en al del
perfil juego aplicación será favor cerrar eliminar haz clic""".split())
_UZ = set("""va uchun bilan emas bu bir siz sizning ham yoki har barcha yangi xato jami bo‘sh bo'sh bor yo‘q yo'q
kerak kiriting tanlang oling qiling bosing sovg‘a sovga olish berish xarid narx daraja vazifa vazifalar o‘yin o'yin
o‘yinchi hisob tugash qoldi keyin avval hozir endi bilan lekin agar ushbu shu ular biz men sen u""".split())
_RU_FUNC = set("""для это если что или при все вас вам вы ваш ваша ваше ваши как был была были быть нужно можно будет
чтобы который которые когда после перед через также только уже ещё еще нет вместе между потому тебе тебя тобой
можешь должен должны нужен нужна очень свой своего своих""".split())

_UZ_SUFFIXES = ("lash", "ning", "dagi", "ligi", "lari", "larni", "lardan", "lar", "ish", "iya", "siya", "tsiya", "chi",
                "lik", "ishi", "ga", "ni", "dan", "da")
_UZ_STRONG_SUFFIXES = ("lash", "ning", "dagi", "ligi", "lari", "larni", "lardan", "ishi", "tsiya")


def _score_latin(ws: List[str]) -> Dict[str, float]:
    score = {"uz": 0.0, "en": 0.0, "pt": 0.0, "es": 0.0}
    for w in ws:
        lw = w.lower()
        if lw in _UZ:
            score["uz"] += 3
        if lw in _EN:
            score["en"] += 3
        if lw in _PT:
            score["pt"] += 2
        if lw in _ES:
            score["es"] += 2
        if re.search("[og][%s]" % re.escape(UZ_APOSTROPHES), lw):
            score["uz"] += 3
        if any(lw.endswith(s) and len(lw) > len(s) + 2 for s in _UZ_STRONG_SUFFIXES):
            score["uz"] += 2.5
        elif len(lw) > 5 and any(lw.endswith(s) and len(lw) > len(s) + 3 for s in _UZ_SUFFIXES):
            score["uz"] += 0.7
        if "q" in lw and not lw.endswith("qu") and "qu" not in lw:
            score["uz"] += 1.5
        if re.search("x", lw) and not re.search("(ex|xp|xt|xi)", lw):
            score["uz"] += 1
        if "w" in lw or "th" in lw or lw.endswith(("ed", "ing", "tion", "ly")):
            score["en"] += 1.5
        if re.search("[ãõçêâ]", lw):
            score["pt"] += 4
        if re.search("[ñ¿¡]", lw) or lw.endswith("ción"):
            score["es"] += 4
        if lw.endswith(("ção", "ões")):
            score["pt"] += 4
        if re.search("[éóúíà]", lw):
            score["pt"] += 1
            score["es"] += 1
    return score


def guess_language(text: str) -> Tuple[str, float, str]:
    """Return (lang_code, confidence 0..1, reason). Codes: kk uz ru en pt es latin? cyr?"""
    ws = words(text)
    if not ws:
        return "none", 0.0, "no letters"
    lat = [w for w in ws if has_latin(w) and not has_cyrillic(w)]
    cyr = [w for w in ws if has_cyrillic(w)]
    if len(lat) >= len(cyr):
        sc = _score_latin(lat)
        best = max(sc, key=lambda k: sc[k])
        top = sc[best]
        second = sorted(sc.values())[-2]
        if top < 2:
            return "latin", 0.35, "латиница без опознаваемых признаков языка"
        conf = min(0.97, 0.55 + 0.1 * (top - second))
        return best, conf, "латиница, признаки языка: %s=%.1f" % (best, top)
    kk_letters = sum(1 for ch in text if ch in KK_SPECIAL)
    if kk_letters >= 1:
        return "kk", min(0.95, 0.6 + 0.07 * kk_letters), "казахские буквы (%d)" % kk_letters
    low = [w.lower() for w in cyr]
    ru_hits = sum(1 for w in low if w in _RU_FUNC)
    if ru_hits:
        return "ru", min(0.95, 0.55 + 0.15 * ru_hits), "русские служебные слова (%d)" % ru_hits
    return "cyr", 0.3, "кириллица без казахских букв"


@dataclass
class LangProfile:
    code: str
    name: str
    native_name: str
    script: str                                   # "cyrillic" | "latin"
    special_letters: str = ""
    plural_categories: Tuple[str, ...] = ("one", "other")
    # suffixes written after a placeholder that depend on the preceding sound
    harmony_suffix_re: Optional[str] = None
    # expected length growth relative to Russian for short UI strings
    max_ratio_short: float = 3.0
    brand_allow: FrozenSet[str] = frozenset()


KK = LangProfile(
    code="kk", name="Kazakh", native_name="Қазақша", script="cyrillic",
    special_letters=KK_SPECIAL, plural_categories=("one", "other"),
    harmony_suffix_re=(r"\}[-’'‑–]?(?:ға|ге|қа|ке|на|не|ны|ні|ды|ді|ты|ті|дың|дің|тың|тің|ның|нің|да|де|та|те|"
                       r"нан|нен|дан|ден|тан|тен|мен|бен|пен|мын|мін|пын|пін|ым|ім|сы|сі)(?![\wәғқңөұүһі])"),
)
UZ = LangProfile(
    code="uz", name="Uzbek", native_name="O‘zbekcha", script="latin",
    special_letters="oʻgʻ‘’", plural_categories=("one", "other"),
    # Uzbek has no vowel harmony, but k/q/g-final names change -ga/-ka/-qa;
    # the suffix is still glued to a runtime value, so it is flagged for code handling.
    harmony_suffix_re=r"\}[-’'‑–]?(?:ga|ka|qa|ni|ning|da|dan|dagi|dir|ligi|lar)(?![A-Za-z])",
)
RU = LangProfile(code="ru", name="Russian", native_name="Русский", script="cyrillic",
                 plural_categories=("one", "few", "many", "other"))
EN = LangProfile(code="en", name="English", native_name="English", script="latin")

PROFILES: Dict[str, LangProfile] = {"kk": KK, "uz": UZ, "ru": RU, "en": EN}


def get_profile(code: str) -> LangProfile:
    """Explicit lookup. Unknown codes give a *generic* profile - never silently Kazakh."""
    code = (code or "").lower()
    if code in PROFILES:
        return PROFILES[code]
    return LangProfile(code=code or "und", name=code or "unknown", native_name=code or "unknown",
                       script="latin", plural_categories=("one", "other"))
