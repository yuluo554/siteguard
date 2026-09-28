# -*- coding: utf-8 -*-
"""M2 测试：规则库数据驱动、override/阈值判定、docx 解析、LLM 降级路径、端到端指标。"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from siteguard import config
from siteguard.benchmark import run_eval
from siteguard.ingest import parsers
from siteguard.reasoning import risk_level


def setUpModule():
    from siteguard.datagen import generate_all
    generate_all(force=False)


def _card(quote, ht_id, schema, attrs=None, extractor="rules", confidence=0.95):
    ht = schema["hazard_type_by_id"][ht_id]
    return {"card_id": "HC-00001", "quote": quote, "hazard_type_id": ht_id,
            "hazard_type": ht["name"], "category": ht["category"],
            "extractor": extractor, "confidence": confidence, "attrs": attrs or {}}


class TestRulesLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.rules = cls.schema["rules"]

    def test_rules_data_loaded(self):
        self.assertEqual(len(self.rules["overrides"]), 15)
        self.assertEqual(len(self.rules["threshold_rules"]), 7)
        self.assertEqual(len(self.rules["base_rules"]), len(self.schema["hazard_types"]))

    def test_migration_consistency(self):
        # risk_level 模块常量与规则库数据一致（迁移完整性）
        self.assertEqual(self.rules["major_patterns"], risk_level.MAJOR_PATTERNS)
        self.assertEqual(self.rules["severity_words"], risk_level.SEVERITY_WORDS)

    def test_override_fires_major(self):
        j = risk_level.judge(
            _card("附着式升降脚手架未经验收合格即投入使用", "HT-SJA-002", self.schema),
            [], self.schema)
        self.assertEqual(j["risk_level"], "重大风险")
        self.assertEqual(j["override_id"], "OV-2022-007-3")
        self.assertEqual(j["rule_id"], "OV-2022-007-3")

    def test_override_does_not_downgrade(self):
        # 重大词形命中后 override 只升不降，且 major_pattern 保留（兼容 M1 判例）
        j = risk_level.judge(
            _card("塔吊回转限位装置失效仍在运行", "HT-GCZY-004", self.schema), [], self.schema)
        self.assertEqual(j["risk_level"], "重大风险")
        self.assertIsNotNone(j["upgraded"]["major_pattern"])

    def test_threshold_numeric_judgment(self):
        card = _card("附着式升降脚手架使用中", "HT-SJA-002", self.schema,
                     attrs={"附着式升降脚手架架体悬臂高度": 7.5})
        j = risk_level.judge(card, [], self.schema)
        self.assertEqual(j["risk_level"], "重大风险")
        self.assertEqual(j["threshold_id"], "TH-SJA-002")
        self.assertEqual(j["rule_id"], "RT-SJA-002")

    def test_threshold_not_triggered_in_range(self):
        card = _card("附着式升降脚手架使用中", "HT-SJA-002", self.schema,
                     attrs={"附着式升降脚手架架体悬臂高度": 5.0})
        j = risk_level.judge(card, [], self.schema)
        self.assertEqual(j["risk_level"], "较大风险")
        self.assertIsNone(j["threshold_id"])

    def test_fallback_without_rules_data(self):
        schema = dict(self.schema)
        schema["rules"] = {}
        j = risk_level.judge(_card("外架未挂设安全网", "HT-GCZY-004", self.schema), [], schema)
        self.assertEqual(j["risk_level"], "一般风险")  # 兜底常量仍可用


class TestDocxParse(unittest.TestCase):
    def test_docx_sample_roundtrip(self):
        from scripts.make_docx_sample import txt_to_docx
        tmp = Path(tempfile.mkdtemp(prefix="siteguard_docx_"))
        try:
            txt = config.repo_path("data", "samples", "text", "demo_gczy.txt")
            docx_path = tmp / "demo_gczy.docx"
            self.assertEqual(txt_to_docx(txt, docx_path), 0)
            recs_txt = parsers.parse_log_file(txt)
            recs_docx = parsers.parse_log_file(docx_path)
            self.assertEqual(recs_docx, recs_txt)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_bad_docx_raises_valueerror(self):
        tmp = Path(tempfile.mkdtemp(prefix="siteguard_docx_"))
        try:
            bad = tmp / "bad.docx"
            bad.write_bytes("这不是docx，是纯文本".encode("utf-8"))
            with self.assertRaises(ValueError):
                parsers.parse_log_file(bad)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_missing_dependency_hint(self):
        tmp = Path(tempfile.mkdtemp(prefix="siteguard_docx_"))
        try:
            dummy = tmp / "x.docx"
            dummy.write_bytes(b"stub")
            saved = sys.modules.get("docx")
            sys.modules["docx"] = None  # 强制触发 ImportError 路径
            try:
                with self.assertRaises(ValueError) as ctx:
                    parsers.parse_log_file(dummy)
                self.assertIn("python-docx", str(ctx.exception))
            finally:
                if saved is None:
                    sys.modules.pop("docx", None)
                else:
                    sys.modules["docx"] = saved
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class TestLlmFallbackPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.records = [{"index": 1, "timestamp": "2026-09-21 08:30",
                        "text": "3#楼3层临边未设置防护栏杆"}]

    @staticmethod
    def _settings(**extra):
        cfg = {"disable_llm": False,
               "llm": {"enabled": True, "api_key": "test-key", "model": "fake", "max_retries": 0}}
        cfg["llm"].update(extra)
        return cfg

    @staticmethod
    def _transport(content):
        def fake(url, payload, headers, timeout):
            return {"choices": [{"message": {"content": content}}]}
        return fake

    def test_disabled_by_default(self):
        from siteguard.extract import llm
        cards, warnings = llm.extract_cards_llm([], settings={"disable_llm": True})
        self.assertEqual(cards, [])
        self.assertTrue(warnings)

    def test_unconfigured_degrades(self):
        from siteguard.extract import llm
        cards, warnings = llm.extract_cards_llm([], settings={"disable_llm": False, "llm": {}})
        self.assertEqual(cards, [])
        self.assertTrue(any("降级" in w for w in warnings))

    def test_fabricated_quote_rejected(self):
        from siteguard.extract import llm
        items = [{"record_index": 1, "quote": "这句话原文里没有", "hazard_type_id": "HT-GCZY-001"},
                 {"record_index": 1, "quote": "临边未设置防护栏杆", "hazard_type_id": "HT-NOPE"}]
        cards, warnings = llm.extract_cards_llm(
            self.records, "memory", self._settings(), schema=self.schema,
            transport=self._transport(json.dumps(items, ensure_ascii=False)))
        self.assertEqual(cards, [])
        self.assertTrue(any("校验" in w for w in warnings))

    def test_valid_items_build_llm_cards(self):
        from siteguard.extract import llm
        items = [{"record_index": 1, "quote": "临边未设置防护栏杆",
                  "hazard_type_id": "HT-GCZY-001"}]
        cards, warnings = llm.extract_cards_llm(
            self.records, "memory", self._settings(), schema=self.schema,
            transport=self._transport(json.dumps(items, ensure_ascii=False)))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["extractor"], "llm")
        self.assertEqual(cards[0]["hazard_type_id"], "HT-GCZY-001")

    def test_transport_failure_degrades(self):
        from siteguard.extract import llm

        def boom(url, payload, headers, timeout):
            raise IOError("network down")

        cards, warnings = llm.extract_cards_llm(
            self.records, "memory", self._settings(max_retries=1), schema=self.schema,
            transport=boom)
        self.assertEqual(cards, [])
        self.assertTrue(any("降级" in w for w in warnings))


class TestEndToEndMetrics(unittest.TestCase):
    def test_eval_has_end_to_end(self):
        payload = run_eval()
        e2e = payload["end_to_end"]
        self.assertEqual(e2e["false_positives"], 0, "端到端误报必须为 0")
        self.assertGreaterEqual(e2e["detection_rate"], 0.90)
        for r in payload["files"]:
            self.assertIn("end_to_end", r)
            self.assertEqual(r["end_to_end"]["false_positive_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
