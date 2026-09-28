"""四级风险判定引擎测试（确定性、从重原则、封顶重大）。"""

import unittest

from siteguard import config
from siteguard.reasoning import risk_level


def _card(quote, ht_id="HT-GCZY-004", extractor="rules", confidence=0.95):
    schema = config.load_schema()
    ht = schema["hazard_type_by_id"][ht_id]
    return {"card_id": "HC-00001", "quote": quote, "hazard_type_id": ht_id,
            "hazard_type": ht["name"], "category": ht["category"],
            "extractor": extractor, "confidence": confidence}


class TestRiskLevel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()

    def test_base_level(self):
        j = risk_level.judge(_card("外架未挂设安全网"), [], self.schema)
        self.assertEqual(j["risk_level"], "一般风险")  # HT-GCZY-004 base
        self.assertEqual(j["rule_id"], "RL-GCZY-004")

    def test_severity_word_upgrades_one_level(self):
        j = risk_level.judge(_card("外架未挂设安全网，此前已发生坠落伤人事件"), [], self.schema)
        self.assertEqual(j["risk_level"], "较大风险")
        self.assertEqual(j["upgraded"]["severity_word"], "坠落伤人")

    def test_major_pattern_overrides_to_top(self):
        j = risk_level.judge(_card("塔吊回转限位装置失效仍在运行"), [], self.schema)
        self.assertEqual(j["risk_level"], "重大风险")
        self.assertIsNotNone(j["upgraded"]["major_pattern"])

    def test_upgrade_capped_at_major(self):
        # 重大 + 严重词仍封顶重大
        j = risk_level.judge(_card("深基坑未编制专项施工方案，可能造成伤亡"), [], self.schema)
        self.assertEqual(j["risk_level"], "重大风险")

    def test_human_confirm_for_llm(self):
        j = risk_level.judge(_card("临边未设置防护栏杆", extractor="llm"), [], self.schema)
        self.assertTrue(j["human_confirm"])

    def test_clause_refs_carried(self):
        refs = [{"standard": "JGJ 80-2016", "clause": "4.1.2", "quote": "原文"}]
        j = risk_level.judge(_card("临边未设置防护栏杆", ht_id="HT-GCZY-001"), refs, self.schema)
        self.assertEqual(j["clause_refs"][0]["clause"], "4.1.2")


if __name__ == "__main__":
    unittest.main()
