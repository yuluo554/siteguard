"""规则抽取与降级通路测试。"""

import unittest

from siteguard import config
from siteguard.extract import llm, rules


class TestRuleEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.engine = rules.RuleEngine(cls.schema)

    def _records(self, *texts):
        return [{"index": i + 1, "timestamp": "2026-09-21", "text": t}
                for i, t in enumerate(texts)]

    def test_extracts_known_hazard(self):
        cards = self.engine.extract(self._records("3#楼3层临边未设置防护栏杆"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["hazard_type_id"], "HT-GCZY-001")
        self.assertEqual(cards[0]["category"], "高处作业")
        self.assertEqual(cards[0]["extractor"], "rules")

    def test_benign_line_no_match(self):
        cards = self.engine.extract(self._records("现场安全巡查总体受控，未发现新增隐患。"))
        self.assertEqual(cards, [])

    def test_site_object_captured(self):
        cards = self.engine.extract(self._records("2#楼5层配电箱无门无锁"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["hazard_type_id"], "HT-LSYD-003")
        self.assertEqual(cards[0]["site_object"], "配电箱")

    def test_all_seed_patterns_compiled(self):
        # 词表里每个隐患类型都必须有可编译 pattern，防止空规则混入
        for ht, pats in self.engine._compiled:
            self.assertTrue(pats, "%s 缺少 patterns" % ht["id"])


class TestLlmFallback(unittest.TestCase):
    def test_disabled_by_default(self):
        cards, warnings = llm.extract_cards_llm([], settings={"disable_llm": True})
        self.assertEqual(cards, [])
        self.assertTrue(warnings)

    def test_unconfigured_degrades(self):
        cards, warnings = llm.extract_cards_llm(
            [], settings={"disable_llm": False, "llm": {}})
        self.assertEqual(cards, [])
        self.assertTrue(any("降级" in w for w in warnings))

    def test_validate_item_rejects_fabricated_quote(self):
        schema = config.load_schema()
        bad = {"quote": "这条原文里没有", "hazard_type_id": "HT-GCZY-001"}
        good = {"quote": "临边未设置防护栏杆", "hazard_type_id": "HT-GCZY-001"}
        full = "3#楼3层临边未设置防护栏杆"
        self.assertFalse(llm.validate_llm_item(bad, full, schema))
        self.assertTrue(llm.validate_llm_item(good, full, schema))

    def test_fix_json_truncated(self):
        self.assertEqual(llm.fix_json_truncated('[{"a": 1}, {"b": 2'), '[{"a": 1}]')
        self.assertEqual(llm.fix_json_truncated('[{"a": 1}]'), '[{"a": 1}]')


class TestVisionStub(unittest.TestCase):
    def test_not_implemented_yet(self):
        # M0 骨架期此测试断言占位 raise NotImplementedError；
        # M4 起视觉通路已实现（extract/vision.py），改为断言缺图时优雅降级：
        # 不崩溃，返回空卡列表 + warnings（回归测试：test_m4.py 覆盖三路径降级）。
        from siteguard.extract import vision
        cards, warns = vision.detect("x.jpg")
        self.assertEqual(cards, [])
        self.assertTrue(warns)


if __name__ == "__main__":
    unittest.main()
