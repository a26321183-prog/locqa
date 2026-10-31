import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa.arb import parse_arb, write_fixed
from locqa.engine import analyse
from locqa.validate import validate
from tests.helpers import Tmp, write_arb

RU = {
    "hello": "Привет, {name}!", "cancel": "Отмена", "buy": "Купить", "brand": "Grand Mobile", "num": "100",
    "garage": "Гараж", "rent_button": "Арендовать", "family": "Семья игрока", "faction": "Фракция",
    "items": "{count, plural, one{{count} предмет} other{{count} предметов}}",
    "retry": "Подключение к {provider}", "sentence": "Вы действительно хотите купить этот предмет?",
    "tab_a": "Победа", "tab_b": "Верх", "tab_c": "Цвет", "tab_d": "Ранг", "missing": "Нет такого",
}


def kk_target():
    t = {
        "hello": "Сәлем, {name}!", "cancel": "Болдырмау", "buy": "Сатып алу", "brand": "Grand Mobile", "num": "100",
        "garage": "Гараж", "rent_button": "Жалға алу үшін басыңыз", "family": "Ойыншы отбасы", "faction": "Топ",
        "items": "{count} зат", "retry": "{provider}-ға қосылу", "sentence": "Вы действительно хотите купить этот предмет?",
        "tab_a": "Жеңіс режимін қосу және жалғастыру", "tab_b": "Үсті режимін қосу және жалғастыру",
        "tab_c": "Түс режимін қосу және жалғастыру", "tab_d": "Ранг",
    }
    return t


class CoreTests(unittest.TestCase):
    def setUp(self):
        self._t = Tmp()
        self.d = self._t.__enter__()
        self.src = write_arb(self.d, "intl_ru.arb", RU)

    def tearDown(self):
        self._t.__exit__()

    def check(self, target_items, lang="kk", **kw):
        tgt = write_arb(self.d, "intl_%s.arb" % lang, target_items)
        return analyse(self.src, tgt, kw.pop("glossary", None), lang, **kw)

    def types(self, res, key):
        return {f.issue_type for f in res.findings if f.key == key}

    def test_repeated_comment_markers_are_parsed(self):
        arb = parse_arb(self.src)
        self.assertEqual(len(arb.messages), len(RU))

    def test_untranslated_missing_key(self):
        res = self.check(kk_target())
        self.assertIn("untranslated", self.types(res, "missing"))

    def test_same_as_source_but_brand_and_numbers_are_exceptions(self):
        res = self.check(kk_target())
        self.assertIn("same_as_source", self.types(res, "sentence"))
        self.assertNotIn("same_as_source", self.types(res, "brand"))
        self.assertNotIn("same_as_source", self.types(res, "num"))

    def test_placeholder_lost_braces_and_typo(self):
        t = kk_target()
        t["hello"] = "Сәлем, name!"
        res = self.check(t)
        f = [f for f in res.findings if f.key == "hello" and f.issue_type == "placeholder_mismatch"][0]
        self.assertEqual(f.suggestion, "Сәлем, {name}!")
        t["hello"] = "Сәлем, {nam}!"
        res = self.check(t)
        f = [f for f in res.findings if f.key == "hello" and f.issue_type == "placeholder_mismatch"][0]
        self.assertEqual(f.suggestion, "Сәлем, {name}!")

    def test_plural_missing_other_and_dropped(self):
        t = kk_target()
        t["items"] = "{count, plural, one{{count} зат}}"
        res = self.check(t)
        self.assertIn("plural_mismatch", self.types(res, "items"))
        res = self.check(kk_target())          # plural dropped completely
        self.assertIn("plural_mismatch", self.types(res, "items"))
        t["items"] = "{count, plural, one{{count} зат} other{{count} зат}}"
        res = self.check(t)
        self.assertNotIn("plural_mismatch", self.types(res, "items"))

    def test_suffix_harmony_kazakh_and_uzbek(self):
        res = self.check(kk_target())
        self.assertIn("suffix_harmony", self.types(res, "retry"))
        res = self.check({"retry": "{provider}ga ulanish"}, lang="uz")
        self.assertIn("suffix_harmony", self.types(res, "retry"))

    def test_length_overflow_detects_padding_and_suggests_head(self):
        res = self.check(kk_target())
        f = [f for f in res.findings if f.key == "tab_a" and f.issue_type == "length_overflow"][0]
        self.assertEqual(f.suggestion, "Жеңіс")
        self.assertEqual(self.types(res, "tab_d") & {"length_overflow"}, set())

    def test_orthography_mixed_script_kk_and_uz(self):
        t = kk_target()
        t["buy"] = "Сатып алу" .replace("у", "y")      # Latin y inside a Cyrillic word
        res = self.check(t)
        self.assertIn("orthography", self.types(res, "buy"))
        res = self.check({"buy": "Sotib оlish"}, lang="uz")    # Cyrillic о inside Latin word
        f = [f for f in res.findings if f.key == "buy" and f.issue_type == "orthography"][0]
        self.assertEqual(f.suggestion, "Sotib olish")

    def test_wrong_language_kk_file_containing_uzbek_and_english(self):
        t = kk_target()
        t["buy"] = "Sotib olish"
        t["cancel"] = "Equipped"
        res = self.check(t)
        self.assertIn("wrong_language", self.types(res, "buy"))
        self.assertIn("wrong_language", self.types(res, "cancel"))

    def test_uzbek_is_not_processed_as_kazakh(self):
        uz = {"hello": "Salom, {name}!", "buy": "Sotib olish", "cancel": "Бекор қилиш"}
        res = self.check(uz, lang="uz")
        self.assertEqual(res.summary()["language"], "uz")
        self.assertEqual(res.ctx.lang.script, "latin")
        # Latin Uzbek text is NOT reported as wrong language in an Uzbek file ...
        self.assertNotIn("wrong_language", self.types(res, "buy"))
        # ... while Kazakh Cyrillic text is, and it is recognised as Kazakh.
        f = [f for f in res.findings if f.key == "cancel" and f.issue_type == "wrong_language"][0]
        self.assertIn("казахский", f.evidence)
        # the very same Latin text IS wrong in a Kazakh file
        res_kk = self.check({"buy": "Sotib olish"}, lang="kk")
        self.assertIn("wrong_language", self.types(res_kk, "buy"))

    def test_language_rules_do_not_leak(self):
        from locqa.langs import get_profile
        self.assertEqual(get_profile("uz").code, "uz")
        self.assertNotEqual(get_profile("uz").harmony_suffix_re, get_profile("kk").harmony_suffix_re)
        self.assertEqual(get_profile("xx").script, "latin")      # unknown -> generic, never Kazakh
        self.assertNotEqual(get_profile("xx").code, "kk")

    def test_glossary_violation_per_language(self):
        gl = os.path.join(self.d, "g.csv")
        with open(gl, "w", encoding="utf-8") as fh:
            fh.write("ru,kk,en,uz,comment,kk_forbidden,uz_forbidden\nфракция,фракция,faction,Fraksiya,t,топ,Tashkilot\n")
        res = self.check(kk_target(), glossary=gl)
        self.assertIn("glossary_violation", self.types(res, "faction"))
        res = self.check({"faction": "Tashkilot"}, lang="uz", glossary=gl)
        f = [f for f in res.findings if f.issue_type == "glossary_violation"][0]
        self.assertIn("Fraksiya", f.suggestion)

    def test_inconsistent_term_typo_variant(self):
        src = write_arb(self.d, "intl_ru.arb", {"a": "Создание продажи", "b": "Создание продажи", "c": "Создание продажи",
                                               "d": "Создание продажи"})
        tgt = write_arb(self.d, "intl_kk.arb", {"a": "Сатуды құру", "b": "Сатуды құру", "c": "Сатуды құру", "d": "Сатуды кұру"})
        res = analyse(src, tgt, None, "kk")
        self.assertIn("inconsistent_term", {f.issue_type for f in res.findings if f.key == "d"})

    def test_report_schema(self):
        res = self.check(kk_target())
        need = {"key", "issue_type", "severity", "source", "target", "evidence", "suggestion", "confidence", "reviewed_by_human"}
        for f in res.findings:
            d = f.to_dict()
            self.assertEqual(set(d), need)
            self.assertIn(d["severity"], ("high", "medium", "low"))
            self.assertFalse(d["reviewed_by_human"])
            self.assertTrue(d["evidence"])

    def test_any_language_works(self):
        res = self.check({"hello": "Merhaba {name}!", "buy": "Satın al"}, lang="tr")
        self.assertEqual(res.summary()["language"], "tr")

    def test_writer_preserves_file_and_flags_unreviewed(self):
        tgt = write_arb(self.d, "intl_kk.arb", kk_target())
        arb = parse_arb(tgt)
        out = os.path.join(self.d, "fixed.arb")
        write_fixed(arb, {"hello": "Сәлем, {name}!!"}, {"hello": {"changed": True, "reviewed_by_human": False}}, out,
                    added={"missing": "Жоқ"})
        fixed = parse_arb(out)
        self.assertEqual(fixed.messages["hello"], "Сәлем, {name}!!")
        self.assertEqual(fixed.messages["cancel"], arb.messages["cancel"])
        self.assertEqual(fixed.messages["missing"], "Жоқ")
        self.assertIs(fixed.meta["@hello"]["x-locqa"]["reviewed_by_human"], False)
        self.assertEqual(validate(self.src, out), [])

    def test_validate_catches_broken_placeholder(self):
        bad = write_arb(self.d, "intl_kk.arb", {"hello": "Сәлем, name!", "retry": "{x}"})
        self.assertTrue(validate(self.src, bad))


if __name__ == "__main__":
    unittest.main()
