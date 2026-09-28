"""整改建议生成：条款措施 + 历史案例（模板化），LLM 只做行文润色（M2 接入）。

纪律：建议文本必须携带出处（measure id / 条款编号），不得引入新的数值结论。
"""


def suggest(card, judgment, schema, graph=None):
    ht = schema["hazard_type_by_id"].get(card["hazard_type_id"], {})
    out = []
    clause_txt = "、".join(
        "%s %s" % (r["standard"], r["clause"]) for r in judgment.get("clause_refs", [])
    ) or "受控词表"
    for mid in ht.get("measure_ids", []):
        m = schema["measure_by_id"].get(mid)
        if not m:
            continue
        out.append({
            "text": "%s（依据 %s）" % (m["text"], clause_txt),
            "source": mid,
        })
    if not out:
        out.append({"text": "现场复查并按 %s 相关条款落实整改，整改结果拍照留档。"
                    % clause_txt, "source": "fallback"})
    return out
