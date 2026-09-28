"""M3 测试：KG 可视化导出（离线 HTML）、缺依赖降级、报告条款锚点、build-kg CLI 产物。"""

import json
import os
import re
import shutil
import tempfile
import unittest

from siteguard import config
from siteguard.kg import schema as kg_schema
from siteguard.kg import visualize as vz

try:
    import pyvis  # noqa: F401
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False

_EXTERNAL_TAG_RE = re.compile(
    r'<script[^>]+src="https?://|<link[^>]+href="https?://')


class TestVisualization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.graph = kg_schema.build_seed_graph(cls.schema)
        cls.tmp = tempfile.mkdtemp(prefix="siteguard_m3_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @unittest.skipUnless(HAS_PYVIS, "pyvis 未安装")
    def test_export_html_generates_offline_file(self):
        out = os.path.join(self.tmp, "kg.html")
        r = vz.export_html(self.graph, out)
        self.assertTrue(r.get("ok"))
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as f:
            html = f.read()
        # 离线硬性要求：不得有外链 script/link 标签（禁外链 CDN）
        self.assertEqual(_EXTERNAL_TAG_RE.findall(html), [])
        # 交互增强脚本已注入（过滤/一跳高亮/锚点定位）
        self.assertIn("siteguard-kg-enhance", html)
        self.assertIn("location.hash", html)
        # 种子条款节点进入图数据（悬浮/锚点可达）
        self.assertIn("REG:JGJ 80-2016#4.1.2", html)

    @unittest.skipUnless(HAS_PYVIS, "pyvis 未安装")
    def test_export_html_contains_all_node_types(self):
        out = os.path.join(self.tmp, "kg_types.html")
        vz.export_html(self.graph, out)
        with open(out, encoding="utf-8") as f:
            html = f.read()
        self.assertGreaterEqual(html.count('"t": "HazardType"'), 30)
        self.assertGreaterEqual(html.count('"t": "Regulation"'), 54)
        self.assertGreaterEqual(html.count('"t": "Measure"'), 28)

    def test_export_html_fallback_without_pyvis(self):
        out = os.path.join(self.tmp, "kg_fb.html")
        r = vz.export_html(self.graph, out, pyvis_mod=False)
        self.assertFalse(r.get("ok"))
        self.assertIn("pyvis", r.get("hint", ""))
        fb = r.get("fallback", "")
        self.assertTrue(fb and os.path.exists(fb))
        with open(fb, encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["stats"]["node_count"], self.graph.node_count())
        self.assertFalse(os.path.exists(out), "降级时不应产出半成品 HTML")


class TestClauseAnchors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.graph = kg_schema.build_seed_graph(cls.schema)
        cls.tmp = tempfile.mkdtemp(prefix="siteguard_m3_anchor_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_anchor_format_and_reg_node_exists(self):
        from siteguard.kg import anchors
        ht = self.schema["hazard_type_by_id"]["HT-GCZY-001"]
        refs = ht.get("clause_refs", [])
        self.assertTrue(refs)
        for ref in refs:
            nid = anchors.kg_node_id(ref["standard"], ref["clause"])
            self.assertTrue(nid.startswith("REG:"))
            self.assertIsNotNone(self.graph.get_node(nid),
                                 "锚点节点在图中不存在: %s" % nid)
            a = anchors.clause_anchor(ref["standard"], ref["clause"])
            self.assertTrue(a.startswith("kg.html#REG%3A"), a)
            frag = a.split("#", 1)[1]
            self.assertNotIn("#", frag.replace("%23", ""))  # 节点 id 内的 # 已编码
            self.assertNotIn(" ", frag.replace("%20", ""))  # 空格已编码

    def test_attach_anchors_idempotent(self):
        from siteguard.kg import anchors
        report = self._mini_report()
        anchors.attach_anchors(report)
        first = report["cards"][0]["judgment"]["clause_refs"][0]["anchor"]
        anchors.attach_anchors(report)
        self.assertEqual(
            report["cards"][0]["judgment"]["clause_refs"][0]["anchor"], first)

    def test_export_json_attaches_anchor(self):
        from siteguard.report import export
        out = os.path.join(self.tmp, "r.json")
        export.export_json(self._mini_report(), out)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        refs = [r for c in data["cards"] for r in c["judgment"]["clause_refs"]]
        self.assertTrue(refs)
        for r in refs:
            self.assertTrue(r.get("anchor", "").startswith("kg.html#"), r)
            self.assertTrue(r.get("kg_node", "").startswith("REG:"), r)

    def test_export_md_contains_anchor_links(self):
        from siteguard.report import export
        out = os.path.join(self.tmp, "r.md")
        export.export_md(self._mini_report(), out)
        with open(out, encoding="utf-8") as f:
            md = f.read()
        self.assertIn("(kg.html#REG%3A", md)

    @staticmethod
    def _mini_report():
        return {
            "cards": [{
                "quote": "3#楼3层临边未设置防护栏杆",
                "hazard_type": "临边防护缺失",
                "category": "高处作业",
                "judgment": {
                    "risk_level": "较大风险",
                    "clause_refs": [{"standard": "JGJ 80-2016", "clause": "4.1.2",
                                     "quote": "临边作业时，应在临边设置防护栏杆"}],
                    "suggestions": [],
                },
            }],
            "warnings": [],
        }


class TestBuildKgCli(unittest.TestCase):
    def test_cli_build_kg_outputs_three_artifacts(self):
        from siteguard import cli
        tmp = tempfile.mkdtemp(prefix="siteguard_kg_cli_")
        try:
            rc = cli.main(["build-kg", "--out", tmp])
            self.assertEqual(rc, 0)
            for f in ("kg.json", "kg_stats.json", "kg.html"):
                self.assertTrue(os.path.exists(os.path.join(tmp, f)), f)
            with open(os.path.join(tmp, "kg_stats.json"), encoding="utf-8") as f:
                stats = json.load(f)
            self.assertGreaterEqual(stats["stats"]["node_count"], 100)
            with open(os.path.join(tmp, "kg.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertEqual(_EXTERNAL_TAG_RE.findall(html), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_build_kg_survives_without_pyvis(self):
        # 缺依赖降级：模拟 pyvis 不可用 → 不崩溃、退出码 0、产出 fallback JSON 而非 HTML
        from siteguard import cli
        from siteguard.kg import visualize as vz
        orig = vz.export_html
        tmp = tempfile.mkdtemp(prefix="siteguard_kg_fb_")
        try:
            vz.export_html = lambda g, p, **kw: orig(g, p, pyvis_mod=False, **kw)
            rc = cli.main(["build-kg", "--out", tmp])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(os.path.join(tmp, "kg.fallback.json")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "kg.html")))
        finally:
            vz.export_html = orig
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
