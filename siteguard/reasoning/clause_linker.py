"""条款关联：条目卡 → 规范条文（证据链的根）。

条款来源：受控词表 clause_refs；图谱 Regulation 节点命中时附原文摘录 quote。
查不到时不硬造引用（warnings 由 pipeline 汇总）。
"""


def link(card, schema, graph=None):
    ht = schema["hazard_type_by_id"].get(card["hazard_type_id"], {})
    refs = []
    for ref in ht.get("clause_refs", []):
        item = {"standard": ref["standard"], "clause": ref["clause"], "quote": ""}
        if graph is not None:
            node = graph.get_node("REG:%s#%s" % (ref["standard"], ref["clause"]))
            if node:
                item["quote"] = node.get("text", "")
        refs.append(item)
    return refs, []
