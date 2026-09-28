"""种子图谱装载：受控词表 + 条文块 + 措施 → SimpleGraph。

节点预算（plan/03 §5）：M0 种子约 50 节点，M3 扩至 ~160（≥100 为硬性目标）。
关系语义：
  HazardType -风险分级-> RiskLevel
  HazardType -属于-> Category
  HazardType -整改用-> Measure
  HazardType -应依据-> Regulation
"""

from .. import config
from .builder import SimpleGraph

REL_LEVEL = "风险分级"
REL_CATEGORY = "属于"
REL_MEASURE = "整改用"
REL_CLAUSE = "应依据"
REL_INSTANCE = "实例化"
REL_OCCUR = "发生于"
REL_WORKTYPE = "作业类型"
REL_INVOLVE = "涉及"


def build_seed_graph(schema=None):
    schema = schema or config.load_schema()
    g = SimpleGraph()

    for level in schema["risk_levels"]:
        g.add_node("RL:%s" % level, level, "RiskLevel")
    for cat in schema["categories"]:
        g.add_node("CAT:%s" % cat, cat, "Category")

    reg_by_ref = {}
    for reg in schema["regulations"]:
        node_id = "REG:%s#%s" % (reg["std_id"], reg["clause"])
        g.add_node(node_id, "[%s %s] %s" % (reg["std_id"], reg["clause"], reg["std_name"]),
                   "Regulation", text=reg.get("text", ""))
        reg_by_ref[(reg["std_id"], reg["clause"])] = node_id

    for measure in schema["measures"]:
        g.add_node("MS:%s" % measure["id"], measure["text"], "Measure")

    for ht in schema["hazard_types"]:
        ht_id = "HT:%s" % ht["id"]
        # category 供可视化按大类过滤（M3）；RiskLevel/Category 主干在 HTML 内恒显
        g.add_node(ht_id, ht["name"], "HazardType", base_level=ht.get("base_level", ""),
                   category=ht.get("category", "其他"))
        g.add_edge(ht_id, REL_LEVEL, "RL:%s" % ht.get("base_level", "低风险"))
        g.add_edge(ht_id, REL_CATEGORY, "CAT:%s" % ht.get("category", "其他"))
        for mid in ht.get("measure_ids", []):
            g.add_edge(ht_id, REL_MEASURE, "MS:%s" % mid)
        for ref in ht.get("clause_refs", []):
            reg_id = reg_by_ref.get((ref["standard"], ref["clause"]))
            if reg_id:
                g.add_edge(ht_id, REL_CLAUSE, reg_id)

    # WorkType / SiteObject 种子节点（词表派生，plan/02 §4 节点类型；M2 扩容）
    for wt in sorted({ht["work_type"] for ht in schema["hazard_types"] if ht.get("work_type")}):
        g.add_node("WT:%s" % wt, wt, "WorkType")
    for ht in schema["hazard_types"]:
        if ht.get("work_type"):
            g.add_edge("HT:%s" % ht["id"], REL_WORKTYPE, "WT:%s" % ht["work_type"])
        for obj in ht.get("site_objects", []):
            g.add_node("SO:%s" % obj, obj, "SiteObject")
            g.add_edge("HT:%s" % ht["id"], REL_OCCUR, "SO:%s" % obj)

    # 案例节点与关系（Case —涉及→ HazardType，plan/02 §4）
    for case in schema.get("cases", []):
        case_id = "CASE:%s" % case["case_id"]
        g.add_node(case_id, case.get("title", case["case_id"]), "Case",
                   risk_level=case.get("risk_level", ""))
        for tid in case.get("hazard_type_ids", []):
            g.add_edge(case_id, REL_INVOLVE, "HT:%s" % tid)

    return g


def attach_instance(g, card, judgment):
    """把研判后的隐患实例挂到种子图谱上（动态节点，运行时增长）。"""
    inst_id = "HI:%s" % card["card_id"]
    g.add_node(inst_id, card["quote"], "HazardInstance", risk_level=judgment["risk_level"])
    g.add_edge(inst_id, REL_INSTANCE, "HT:%s" % card["hazard_type_id"])
    if card.get("site_object"):
        obj_id = "SO:%s" % card["site_object"]
        g.add_node(obj_id, card["site_object"], "SiteObject")
        g.add_edge(inst_id, REL_OCCUR, obj_id)
    return inst_id
