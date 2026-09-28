"""研判报告条款锚点（M3：报告挂条款跳转）。

条款引用（clause_refs）与 KG 条款节点的对应规则由本模块统一定义：

    kg_node_id(standard, clause) == "REG:{standard}#{clause}"   # 与 kg/schema.py 一致
    anchor_for(kg_node_id)       == "kg.html#REG%3A...%23..."   # URL 编码（safe=""）

report/export.py 在导出前调用 attach_anchors 为每条 clause_ref 注入
``kg_node``（图节点 id）与 ``anchor``（kg.html 锚点链接）字段：
JSON 报告携带机器可读锚点，Markdown 报告渲染为可点击链接。
kg.html 内嵌增强脚本读取 location.hash（decodeURIComponent 后）定位并高亮条款节点。

约定：anchor 使用文件名 ``kg.html``（相对链接），部署时与报告同目录或按需替换前缀。
"""


def kg_node_id(standard, clause):
    """条款引用 → KG Regulation 节点 id（与 kg/schema.py 的装载规则一致）。"""
    return "REG:%s#%s" % (standard, clause)


def anchor_for(node_id, href="kg.html"):
    """KG 节点 id → 可跳转锚点字符串（kg.html#<URL编码节点id>）。"""
    from urllib.parse import quote

    return "%s#%s" % (href, quote(node_id, safe=""))


def clause_anchor(standard, clause, href="kg.html"):
    """条款引用 → 锚点（快捷组合）。"""
    return anchor_for(kg_node_id(standard, clause), href=href)


def attach_anchors(report, href="kg.html"):
    """为报告 dict 中每条 clause_ref 就地注入 kg_node / anchor 字段。

    幂等：重复调用不重复注入/覆盖。返回 report 本身（便于链式使用）。
    """
    for card in report.get("cards", []):
        judgment = card.get("judgment") or {}
        for ref in judgment.get("clause_refs", []) or []:
            if not isinstance(ref, dict) or "standard" not in ref or "clause" not in ref:
                continue
            node_id = kg_node_id(ref["standard"], ref["clause"])
            ref.setdefault("kg_node", node_id)
            ref.setdefault("anchor", anchor_for(node_id, href=href))
    return report
