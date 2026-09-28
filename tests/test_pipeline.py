"""端到端流水线与基准评测测试（含失败路径）。"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from siteguard import config
from siteguard.benchmark import run_eval
from siteguard.datagen import generate_all
from siteguard.pipeline import runner
from siteguard.report import export


def setUpModule():
    generate_all(force=False)


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.sample = config.repo_path("data", "samples", "text", "demo_gczy.txt")

    def test_run_file_end_to_end(self):
        report = runner.run_file(self.sample)
        self.assertGreater(report["hazard_count"], 0)
        self.assertGreaterEqual(report["record_count"], report["hazard_count"])
        for card in report["cards"]:
            j = card["judgment"]
            self.assertIn(j["risk_level"], config.load_schema()["risk_levels"])
            self.assertTrue(j["clause_refs"], "判定缺少条款依据")
            self.assertTrue(j["suggestions"], "判定缺少整改建议")
        self.assertEqual(report["warnings"], [])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            runner.run_file(config.repo_path("data", "samples", "text", "nope.txt"))

    def test_run_batch_writes_reports(self):
        tmp = Path(tempfile.mkdtemp(prefix="siteguard_test_"))
        try:
            src = config.repo_path("data", "samples", "text")
            tmp_in = tmp / "in"
            tmp_in.mkdir()
            for f in src.glob("*.txt"):
                shutil.copy(str(f), str(tmp_in / f.name))
            bad = tmp_in / "broken.txt"
            bad.write_bytes("，中文GBK".encode("gbk"))  # 坏编码：应降级不崩溃
            result = runner.run_batch(tmp_in, out_dir=tmp / "out")
            self.assertEqual(result["summary"]["files"], 3)
            self.assertEqual(result["summary"]["failed_files"], 1)
            out_files = sorted(p.name for p in (tmp / "out").iterdir())
            self.assertIn("summary.json", out_files)
            self.assertIn("demo_gczy.report.md", out_files)
            self.assertIn("demo_gczy.report.json", out_files)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class TestEval(unittest.TestCase):
    def test_generated_data_separation(self):
        payload = run_eval()
        self.assertEqual(payload["micro"]["fp"], 0, "误报必须为 0")
        self.assertGreaterEqual(payload["micro"]["f1"], 0.90, "M1 门限 F1>=0.90")
        for r in payload["files"]:
            self.assertEqual(r["level_accuracy"], 1.0)

    def test_field_level_metrics(self):
        payload = run_eval()
        self.assertIn("site_object", payload["field_level"])
        for fname, st in payload["field_level"].items():
            self.assertGreaterEqual(st["f1"], 0.90, fname)

    def test_paired_diffs_all_detected(self):
        payload = run_eval()
        self.assertEqual(len(payload["paired"]), 2)
        for pc in payload["paired"]:
            self.assertEqual(pc["gold_diffs"], pc["hits"], pc["case"])
            self.assertEqual(pc["false"], [], pc["case"])

    def test_eval_report_written(self):
        tmp = Path(tempfile.mkdtemp(prefix="siteguard_eval_"))
        try:
            payload = run_eval(out_path=tmp / "eval.json")
            data = json.loads((tmp / "eval.json").read_text(encoding="utf-8"))
            self.assertEqual(data["micro"]["f1"], payload["micro"]["f1"])
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class TestExport(unittest.TestCase):
    def test_md_contains_key_sections(self):
        report = runner.run_file(config.repo_path("data", "samples", "text", "demo_lsyd.txt"))
        tmp = Path(tempfile.mkdtemp(prefix="siteguard_md_"))
        try:
            p = export.export_md(report, tmp / "r.md")
            text = p.read_text(encoding="utf-8")
            for section in ("# 安全风险隐患研判报告", "## 隐患清单", "依据条款"):
                self.assertIn(section, text)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
