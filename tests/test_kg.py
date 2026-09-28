"""KG 构建测试：节点规模、关系语义、实例挂图。"""

import unittest

from siteguard import config
from siteguard.kg import builder, schema as kg_schema


class TestSeedGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = config.load_schema()
        cls.graph = kg_schema.build_seed_graph(cls.schema)

    def test_node_budget(self):
        # M0 种子 ~50 节点；M3 目标 ≥100（硬性目标），此处保底校验
        self.assertGreaterEqual(self.graph.node_count(), 40)
        self.assertGreater(self.graph.edge_count(), 30)

    def test_hazard_type_nodes_complete(self):
        for ht in self.schema["hazard_types"]:
            node = self.graph.get_node("HT:%s" % ht["id"])
            self.assertIsNotNone(node, "缺少节点 %s" % ht["id"])
            self.assertEqual(node["type"], "HazardType")

    def test_relation_semantics(self):
        rels = {r for _, r in self.graph.neighbors("HT:HT-GCZY-001")}
        self.assertIn(kg_schema.REL_LEVEL, rels)
        self.assertIn(kg_schema.REL_CLAUSE, rels)
        self.assertIn(kg_schema.REL_MEASURE, rels)
        self.assertIn(kg_schema.REL_CATEGORY, rels)

    def test_regulation_text_attached(self):
        node = self.graph.get_node("REG:JGJ 46-2005#8.1.3")
        self.assertIsNotNone(node)
        self.assertIn("开关箱", node["text"])

    def test_stats_shape(self):
        stats = self.graph.stats()
        self.assertGreaterEqual(stats["nodes_by_type"].get("HazardType", 0), 12)
        self.assertGreaterEqual(stats["nodes_by_type"].get("Regulation", 0), 12)
        self.assertGreaterEqual(stats["nodes_by_type"].get("Measure", 0), 12)

    def test_attach_instance(self):
        card = {"card_id": "HC-00001", "quote": "3#楼3层临边未设置防护栏杆",
                "hazard_type_id": "HT-GCZY-001", "site_object": "楼层临边"}
        judgment = {"risk_level": "较大风险"}
        inst = kg_schema.attach_instance(self.graph, card, judgment)
        self.assertTrue(self.graph.has_node(inst))
        self.assertTrue(self.graph.has_node("SO:楼层临边"))


class TestSimpleGraph(unittest.TestCase):
    def test_dedup_and_neighbors(self):
        g = builder.SimpleGraph()
        g.add_node("a", "A", "T1")
        g.add_node("b", "B", "T2")
        g.add_edge("a", "r", "b")
        g.add_edge("a", "r", "b")  # 去重
        self.assertEqual(g.node_count(), 2)
        self.assertEqual(g.edge_count(), 1)
        self.assertEqual(g.neighbors("b"), [("a", "r")])

    def test_missing_node_lookup(self):
        g = builder.SimpleGraph()
        self.assertIsNone(g.get_node("nope"))


if __name__ == "__main__":
    unittest.main()
