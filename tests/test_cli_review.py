import csv
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from locqa.arb import parse_arb
from locqa.cli import main
from tests.helpers import Tmp, write_arb
from tests.test_core import RU, kk_target


class CliReviewTests(unittest.TestCase):
    def test_check_fix_and_review_flow(self):
        with Tmp() as d:
            src = write_arb(d, "intl_ru.arb", RU)
            t = kk_target()
            t["hello"] = "Сәлем, name!"
            tgt = write_arb(d, "intl_kk.arb", t)
            rep = os.path.join(d, "report.json")
            self.assertEqual(main(["check", "--source", src, "--target", tgt, "--out", rep]), 0)
            data = json.load(open(rep, encoding="utf-8"))
            self.assertTrue(isinstance(data, list) and data)
            self.assertTrue(os.path.exists(os.path.join(d, "report.html")))
            out = os.path.join(d, "out")
            self.assertEqual(main(["fix", "--source", src, "--target", tgt, "--out-dir", out]), 0)
            fixed = parse_arb(os.path.join(out, "intl_kk_fixed.arb"))
            self.assertEqual(fixed.messages["hello"], "Сәлем, {name}!")
            self.assertIs(fixed.meta["@hello"]["x-locqa"]["reviewed_by_human"], False)
            # human review: confirm "hello"
            rows = list(csv.DictReader(open(os.path.join(out, "review_kk.csv"), encoding="utf-8-sig")))
            for r in rows:
                if r["key"] == "hello":
                    r["decision"], r["reviewer"] = "ok", "Aigerim"
            with open(os.path.join(d, "rev.csv"), "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            final = os.path.join(d, "final.arb")
            main(["apply-review", "--source", src, "--target", tgt, "--review", os.path.join(d, "rev.csv"), "--out", final])
            f2 = parse_arb(final)
            self.assertIs(f2.meta["@hello"]["x-locqa"]["reviewed_by_human"], True)
            others = [k for k, m in f2.meta.items() if "x-locqa" in m and k != "@hello"]
            for k in others:
                self.assertIs(f2.meta[k]["x-locqa"]["reviewed_by_human"], False)

    def test_uzbek_cli_returns_uzbek_report(self):
        with Tmp() as d:
            src = write_arb(d, "intl_ru.arb", RU)
            uz = write_arb(d, "intl_uz.arb", {"hello": "Salom, name!", "buy": "Sotib olish"})
            rep = os.path.join(d, "report_uz.json")
            main(["check", "--source", src, "--target", uz, "--lang", "uz", "--out", rep])
            summary = json.load(open(os.path.join(d, "report_uz.summary.json"), encoding="utf-8"))
            self.assertEqual(summary["language"], "uz")
            self.assertEqual(summary["language_native"], "O‘zbekcha")
            html = open(os.path.join(d, "report_uz.html"), encoding="utf-8").read()
            self.assertIn("Uzbek", html)
            self.assertNotIn("Kazakh", html)

    def test_fail_on_for_ci(self):
        with Tmp() as d:
            src = write_arb(d, "intl_ru.arb", RU)
            tgt = write_arb(d, "intl_kk.arb", {"hello": "Сәлем, name!"})
            self.assertEqual(main(["check", "--source", src, "--target", tgt, "--out", os.path.join(d, "r.json"), "--fail-on", "high"]), 1)


if __name__ == "__main__":
    unittest.main()
