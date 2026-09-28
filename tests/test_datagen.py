"""M1 生成器 v2 测试：语料规模、变体覆盖、禁词纪律、配对差异清单一致性。"""

import re
import unittest

from siteguard import config
from siteguard.benchmark import eval_paired
from siteguard.datagen import PAIRED, SCENARIOS, TEMPLATES, generate_all
from siteguard.ingest import parsers
from siteguard.reasoning import risk_level


def setUpModule():
    generate_all(force=False)


def _gold(key):
    spec = SCENARIOS[key]
    return config.load_json(config.repo_path(
        "data", "eval", "gold", spec["file"].replace(".txt", ".gold.json")))


class TestCorpusV2(unittest.TestCase):
    def test_each_scenario_at_least_50_hazards(self):
        for key in SCENARIOS:
            gold = _gold(key)
            self.assertGreaterEqual(len(gold["records"]), 50, key)
            self.assertEqual(gold.get("corpus"), "v2", key)

    def test_each_type_has_at_least_5_variants(self):
        for ht_id, variants in TEMPLATES.items():
            texts = {v[0] for v in variants}
            self.assertGreaterEqual(len(texts), 5, ht_id)

    def test_corpus_covers_at_least_5_variants_per_type(self):
        for key in SCENARIOS:
            by_type = {}
            for r in _gold(key)["records"]:
                by_type.setdefault(r["hazard_type_id"], set()).add(r["quote"])
            for ht_id, quotes in by_type.items():
                self.assertGreaterEqual(len(quotes), 5, "%s/%s" % (key, ht_id))

    def test_gold_schema_v2_fields(self):
        for r in _gold("gczy")["records"]:
            for field in ("index", "quote", "hazard_type_id", "hazard_type",
                          "category", "site_object", "expected_level"):
                self.assertIn(field, r)


class TestCorpusHygiene(unittest.TestCase):
    """全语料扫描：无严重词、无重大隐患词形（保持分级评测干净，M1 禁止事项）。"""

    def test_no_severity_words_or_major_patterns(self):
        paths = [config.repo_path("data", "samples", "text", s["file"])
                 for s in SCENARIOS.values()]
        paths += [config.repo_path("data", "eval", "cases", p["log"])
                  for p in PAIRED.values()]
        paths += [config.repo_path("data", "eval", "cases", p["patrol"])
                  for p in PAIRED.values()]
        for p in paths:
            for rec in parsers.parse_log_file(p):
                for w in risk_level.SEVERITY_WORDS:
                    self.assertNotIn(w, rec["text"], str(p))
                for pat in risk_level.MAJOR_PATTERNS:
                    self.assertIsNone(re.search(pat, rec["text"]), str(p))


class TestPairedCorpus(unittest.TestCase):
    def test_gold_diff_kinds_complete(self):
        base = config.repo_path("data", "eval", "cases")
        for key, pspec in PAIRED.items():
            gold = config.load_json(base / pspec["gold"])
            kinds = {d["kind"] for d in gold["diffs"]}
            self.assertEqual(kinds, {"missing", "value", "extra"}, key)
            self.assertGreaterEqual(len(gold["diffs"]), 3, key)

    def test_diffs_detected_exactly(self):
        cases = eval_paired()
        self.assertEqual(len(cases), len(PAIRED))
        for c in cases:
            self.assertEqual(c["gold_diffs"], c["hits"], c["case"])
            self.assertEqual(c["missed"], [], c["case"])
            self.assertEqual(c["false"], [], c["case"])


if __name__ == "__main__":
    unittest.main()
