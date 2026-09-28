# -*- coding: utf-8 -*-
"""M4 多模态与图文融合测试。

fake 检测器/模型仅在本文件注入并标注（fake，非真实检出；禁止编造检测结果进真实报告）：
- FakeDetector / lambda detector：vision.detect 的 detector 注入参数；
- FakeYoloModel：模拟 ultralytics YOLO.predict 接口，经 monkeypatch load_model 注入。
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from siteguard import config
from siteguard.extract import vision
from siteguard.kg import schema as kg_schema
from siteguard.pipeline import runner

REPO = config.repo_path()
SCHEMA = config.load_schema()
SAMPLE_IMG = str(REPO / "data" / "samples" / "images" / "shwd_3.jpg")


def make_text_card(**kw):
    card = {
        "card_id": "HC-00001", "source": {"file": "x.txt", "record_index": 1},
        "quote": "外脚手架上作业工人未佩戴安全帽", "extractor": "rules",
        "hazard_type": "未佩戴安全帽", "hazard_type_id": "HT-GCZY-007",
        "category": "高处作业", "work_type": "高处作业", "site_object": "外脚手架",
        "attrs": {}, "evidence": {"record_index": 1},
        "confidence": 0.95, "merged_from": ["rules"],
    }
    card.update(kw)
    return card


def make_vision_card(**kw):
    card = {
        "card_id": None, "source": {"file": "img.jpg", "record_index": 1},
        "quote": "图像 img.jpg 检出：未佩戴安全帽", "extractor": "vision",
        "hazard_type": "未佩戴安全帽", "hazard_type_id": "HT-GCZY-007",
        "category": "高处作业", "work_type": "高处作业", "site_object": "外脚手架",
        "attrs": {"bbox": [1.0, 2.0, 3.0, 4.0], "detection_class": "head"},
        "evidence": {"image": "img.jpg", "bbox": [1.0, 2.0, 3.0, 4.0]},
        "confidence": 0.7, "merged_from": ["vision"],
    }
    card.update(kw)
    return card


def fake_detector(path):  # fake，仅测试注入
    return [{"class_name": "head", "bbox": [1.0, 2.0, 3.0, 4.0], "confidence": 0.7}]


class _List:
    def __init__(self, v):
        self._v = v

    def tolist(self):
        return self._v


class _FakeBoxes:
    def __init__(self):
        self.xyxy = _List([[1.0, 2.0, 3.0, 4.0]])
        self.conf = _List([0.7])
        self.cls = _List([1])


class _FakeResult:
    boxes = _FakeBoxes()


class FakeYoloModel:
    """模拟 ultralytics YOLO（fake，仅测试注入）。"""

    names = {0: "helmet", 1: "head"}

    def predict(self, path, conf=None, verbose=False):
        return [_FakeResult()]


class TestVisionDegradation(unittest.TestCase):
    """三路径优雅降级：禁用 / 坏图缺图 / 缺依赖，均空卡 + warnings 不崩溃。"""

    def test_disabled_by_env(self):
        old = os.environ.get("SITEGUARD_DISABLE_VISION")
        os.environ["SITEGUARD_DISABLE_VISION"] = "1"
        try:
            cards, warns = vision.detect(SAMPLE_IMG)
        finally:
            if old is None:
                os.environ.pop("SITEGUARD_DISABLE_VISION", None)
            else:
                os.environ["SITEGUARD_DISABLE_VISION"] = old
        self.assertEqual(cards, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("禁用", warns[0])

    def test_bad_image(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            bad = tmp / "bad.jpg"
            bad.write_bytes(b"not an image at all!!")
            cards, warns = vision.detect(str(bad), schema=SCHEMA)
            self.assertEqual(cards, [])
            self.assertEqual(len(warns), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_dependency(self):
        cards, warns = vision.detect(SAMPLE_IMG, schema=SCHEMA)
        self.assertEqual(cards, [])
        self.assertTrue(warns)

    def test_missing_image(self):
        cards, warns = vision.detect("no_such_file_xyz.jpg")
        self.assertEqual(cards, [])
        self.assertTrue(warns)


class TestVisionCards(unittest.TestCase):
    """fake 检测器产出合法条目卡：受控词表映射正确、quote/attrs/evidence 齐备。"""

    def test_fake_detector_maps_controlled_vocab(self):
        cards, warns = vision.detect(SAMPLE_IMG, detector=fake_detector, schema=SCHEMA)
        self.assertEqual(len(cards), 1)
        self.assertEqual(warns, [])
        c = cards[0]
        self.assertEqual(c["extractor"], "vision")
        self.assertEqual(c["hazard_type_id"], "HT-GCZY-007")
        self.assertEqual(c["hazard_type"], "未佩戴安全帽")
        self.assertEqual(c["category"], "高处作业")
        self.assertEqual(c["site_object"], "外脚手架")
        self.assertEqual(c["attrs"]["bbox"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(c["evidence"]["image"], "shwd_3.jpg")
        self.assertIn("未佩戴安全帽", c["quote"])

    def test_unmapped_class_dropped(self):
        cards, warns = vision.detect(
            SAMPLE_IMG,
            detector=lambda p: [{"class_name": "crane", "bbox": [0, 0, 1, 1], "confidence": 0.9}],
            schema=SCHEMA)
        self.assertEqual(cards, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("crane", warns[0])

    def test_fake_yolo_model_mapping(self):
        cards, warns = vision.detect(SAMPLE_IMG, model=FakeYoloModel(), schema=SCHEMA)
        self.assertEqual(len(cards), 1)
        self.assertEqual(warns, [])
        self.assertEqual(cards[0]["hazard_type_id"], "HT-GCZY-007")

    def test_low_confidence_judged_human_confirm(self):
        cards, _ = vision.detect(
            SAMPLE_IMG,
            detector=lambda p: [{"class_name": "head", "bbox": [0, 0, 1, 1], "confidence": 0.3}],
            schema=SCHEMA)
        from siteguard.reasoning import risk_level
        cards[0]["card_id"] = "HC-00001"
        j = risk_level.judge(cards[0], [], SCHEMA)
        self.assertTrue(j["human_confirm"])


class TestFusion(unittest.TestCase):
    """融合：合并/不合并/时间窗边界；不带视觉输入时逐位不变。"""

    def test_no_vision_identity(self):
        text = [make_text_card()]
        out, warns = vision.merge_cards(text, [])
        self.assertIs(out, text)
        self.assertEqual(warns, [])

    def test_merge_same_site_and_type(self):
        out, warns = vision.merge_cards([make_text_card()], [make_vision_card()])
        self.assertEqual(len(out), 1)
        self.assertEqual(warns, [])
        f = out[0]
        self.assertEqual(f["merged_from"], ["rules", "vision"])
        self.assertEqual(f["confidence"], 0.95)
        self.assertEqual(f["evidence"]["record_index"], 1)
        self.assertEqual(f["evidence"]["vision"],
                         [{"image": "img.jpg", "bbox": [1.0, 2.0, 3.0, 4.0], "confidence": 0.7}])

    def test_no_merge_different_hazard_type(self):
        v = make_vision_card(hazard_type_id="HT-GCZY-002", hazard_type="高处作业未系安全带")
        out, _ = vision.merge_cards([make_text_card()], [v])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["merged_from"], ["vision"])

    def test_no_merge_different_site_object(self):
        v = make_vision_card(site_object="屋面")
        out, _ = vision.merge_cards([make_text_card()], [v])
        self.assertEqual(len(out), 2)

    def test_time_window_boundary(self):
        t = make_text_card(attrs={"time": "09:30"})
        inside = make_vision_card(attrs={"time": "10:30"})
        outside = make_vision_card(attrs={"time": "10:31"})
        out, _ = vision.merge_cards([dict(t)], [inside])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["merged_from"], ["rules", "vision"])
        out, _ = vision.merge_cards([dict(t)], [outside])
        self.assertEqual(len(out), 2)

    def test_time_window_skipped_when_one_side_missing(self):
        out, _ = vision.merge_cards(
            [make_text_card()],
            [make_vision_card(attrs={"time": "23:59"})])
        self.assertEqual(len(out), 1)


class TestRunnerIntegration(unittest.TestCase):
    """run_file 视觉集成：融合端到端 + 纯文本通路行为不变。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.log = self.tmp / "probe_case.txt"
        self.log.write_text(
            "项目：M4 测试（合成日志，非真实项目）\n"
            "[2026-09-21 08:30] 1#楼外脚手架上作业工人未佩戴安全帽\n",
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fusion_end_to_end(self):
        r = runner.run_file(self.log, vision_images=[SAMPLE_IMG], detector=fake_detector)
        self.assertEqual(len(r["cards"]), 1)
        c = r["cards"][0]
        self.assertEqual(c["merged_from"], ["rules", "vision"])
        self.assertEqual(c["hazard_type_id"], "HT-GCZY-007")
        self.assertEqual(c["confidence"], 0.95)
        self.assertEqual(c["evidence"]["vision"][0]["image"], "shwd_3.jpg")
        self.assertEqual(c["judgment"]["risk_level"], "较大风险")
        self.assertIn("vision_images", r)

    def test_text_only_unchanged(self):
        r = runner.run_file(self.log)
        self.assertEqual(len(r["cards"]), 1)
        self.assertEqual(r["cards"][0]["merged_from"], ["rules"])
        self.assertNotIn("vision_images", r)


class TestDemoWithVision(unittest.TestCase):
    """demo --with-vision 冒烟（注入 fake，仅测试）：融合报告产出与优雅降级。"""

    def test_demo_with_vision_smoke_fake_model(self):
        import siteguard.extract.vision as vmod
        from siteguard.cli import main
        out_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        old = vmod.load_model
        vmod.load_model = lambda model=None: (FakeYoloModel(), [])  # fake，仅测试注入
        try:
            rc = main(["demo", "--with-vision", "--out", str(out_dir)])
        finally:
            vmod.load_model = old
        self.assertEqual(rc, 0)
        reports = sorted(out_dir.glob("*.report.json"))
        self.assertEqual(len(reports), 2)
        for rp in reports:
            payload = json.loads(rp.read_text(encoding="utf-8"))
            self.assertIn("vision_images", payload)
            self.assertEqual(len(payload["vision_images"]), 2)
            vcards = [c for c in payload["cards"] if "vision" in (c.get("merged_from") or [])]
            self.assertTrue(vcards, rp.name)
            self.assertTrue(all("judgment" in c for c in vcards))
        md = (out_dir / "demo_gczy.report.md").read_text(encoding="utf-8")
        self.assertIn("图像 shwd_3.jpg 检出", md)

    def test_demo_without_vision_unchanged(self):
        from siteguard.cli import main
        out_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        rc = main(["demo", "--scenario", "gczy", "--out", str(out_dir)])
        self.assertEqual(rc, 0)
        payload = json.loads((out_dir / "demo_gczy.report.json").read_text(encoding="utf-8"))
        self.assertNotIn("vision_images", payload)
        self.assertTrue(all("vision" not in (c.get("merged_from") or [])
                            for c in payload["cards"]))

    def test_demo_with_vision_missing_deps_degrades(self):
        from siteguard.cli import main
        out_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        import siteguard.extract.vision as vmod
        old = vmod.load_model
        vmod.load_model = lambda model=None: (
            None, ["缺 ultralytics 依赖（pyproject vision 组），视觉通路降级"])
        try:
            rc = main(["demo", "--with-vision", "--out", str(out_dir)])
        finally:
            vmod.load_model = old
        self.assertEqual(rc, 0)
        payload = json.loads((out_dir / "demo_gczy.report.json").read_text(encoding="utf-8"))
        self.assertIn("vision_images", payload)
        self.assertTrue(any("降级" in w for w in payload["warnings"]))
        self.assertTrue(all("vision" not in (c.get("merged_from") or [])
                            for c in payload["cards"]))


class TestM4Regression(unittest.TestCase):
    """M3 产物与受控词表回归：KG 三件套、锚点、词表/规则一致性不回退。"""

    def test_seed_vocab_and_rules_consistent(self):
        self.assertEqual(len(SCHEMA["hazard_types"]), 31)
        self.assertEqual(len(SCHEMA["rules"]["base_rules"]), 31)
        self.assertEqual(len(SCHEMA["measures"]), 29)
        self.assertEqual(len(SCHEMA["rules"]["base_rules"]), len(SCHEMA["hazard_types"]))

    def test_kg_artifacts_include_m4_nodes(self):
        data = json.loads((REPO / "examples" / "kg" / "kg.json").read_text(encoding="utf-8"))
        labels = {(n["label"], n["type"]) for n in data["nodes"]}
        self.assertIn(("未佩戴安全帽", "HazardType"), labels)
        self.assertGreaterEqual(len(data["nodes"]), 100)

    def test_kg_html_artifact_offline(self):
        html = (REPO / "examples" / "kg" / "kg.html").read_text(encoding="utf-8")
        self.assertNotIn('src="http://', html)
        self.assertNotIn('src="https://', html)

    def test_report_md_still_has_clause_anchors(self):
        from siteguard.cli import main
        out_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        rc = main(["demo", "--scenario", "gczy", "--out", str(out_dir)])
        self.assertEqual(rc, 0)
        md = (out_dir / "demo_gczy.report.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(md.count("kg.html#"), 40)


if __name__ == "__main__":
    unittest.main()
