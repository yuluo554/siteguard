"""四级风险判定引擎（确定性，从重原则，命中即停）。

判定顺序（M2 起主通路读规则库 data/knowledge/rules/rules_v1.json）：
1. 命中重大隐患词形（规则库 major_patterns）→ 重大风险；
2. 命中规则库 override（重大隐患判定情形）→ 重大风险（只升不降）；
3. 严重词（坠亡/伤亡/触电身亡等）在基础上调一档，封顶重大；
4. 阈值数值判定：条目卡 attrs 携带实测值且超限 → 取阈值表 level_on_violation；
5. 否则取受控词表 base_level。

模块常量 MAJOR_PATTERNS/SEVERITY_WORDS 保留为兜底默认值（规则库数据缺失时使用），
迁移一致性由 scripts/verify_seed_data.py 校验。
每条判定输出 rule_id 可溯源：override 命中→override_id，阈值命中→RT-*，否则→RL-<类型后缀>。

四档命名固定：低风险 / 一般风险 / 较大风险 / 重大风险。
"""

import re

LEVELS = ["低风险", "一般风险", "较大风险", "重大风险"]

SEVERITY_WORDS = ["坠亡", "伤亡", "死亡", "触电身亡", "坠落伤人", "高坠事故"]

MAJOR_PATTERNS = [
    r"塔吊.{0,10}(限位|保险)装置(失效|缺失)",
    r"(深基坑|高支模).{0,12}未(编制|组织).{0,8}(专项施工方案|专家论证)",
    r"(施工升降机|物料提升机).{0,8}超载(运行)?",
]


def level_index(level):
    return LEVELS.index(level) if level in LEVELS else 0


def _rules(schema):
    """规则库数据（缺失时回退模块常量，保证零配置可运行）。"""
    data = schema.get("rules") or {}
    return {
        "major_patterns": data.get("major_patterns") or MAJOR_PATTERNS,
        "severity_words": data.get("severity_words") or SEVERITY_WORDS,
        "overrides": data.get("overrides") or [],
        "threshold_rules": data.get("threshold_rules") or [],
    }


def _threshold_violations(card, rules, thresholds):
    """阈值数值判定：条目卡 attrs 携带实测值且超限时返回违规的 threshold_rules。"""
    attrs = card.get("attrs") or {}
    if not attrs:
        return []
    th_by_id = {t.get("id"): t for t in thresholds}
    hits = []
    for tr in rules["threshold_rules"]:
        th = th_by_id.get(tr.get("threshold_id"))
        if not th:
            continue
        type_ids = tr.get("hazard_type_ids") or []
        if type_ids and card.get("hazard_type_id") not in type_ids:
            continue
        value = attrs.get(th.get("param"))
        if not isinstance(value, (int, float)):
            continue
        op = th.get("op")
        limit = th.get("value")
        if op == "<":
            violated = value < limit
        elif op == ">":
            violated = value > limit
        elif op == "<=":
            violated = value <= limit
        elif op == ">=":
            violated = value >= limit
        elif op == "not_in":
            lo, hi = th.get("range") or (None, None)
            violated = not (lo <= value <= hi)
        else:
            continue
        if violated:
            hits.append(tr)
    return hits


def judge(card, clause_refs, schema):
    rules = _rules(schema)
    ht = schema["hazard_type_by_id"].get(card["hazard_type_id"], {})
    base = ht.get("base_level", "一般风险")
    quote = card.get("quote", "")
    idx = level_index(base)
    major_hit, severity_hit, override_hit, threshold_hit = None, None, None, None

    for pat in rules["major_patterns"]:
        if re.search(pat, quote):
            major_hit = pat
            idx = level_index("重大风险")
            break
    for ov in rules["overrides"]:
        if any(re.search(p, quote) for p in ov.get("match", {}).get("any_of", [])):
            override_hit = ov
            idx = max(idx, level_index(ov.get("level", "重大风险")))
            break
    if major_hit is None and override_hit is None:
        for w in rules["severity_words"]:
            if w in quote:
                severity_hit = w
                idx = min(idx + 1, level_index("重大风险"))
                break
        if severity_hit is None:
            violations = _threshold_violations(card, rules, schema.get("thresholds", []))
            if violations:
                threshold_hit = violations[0]
                idx = max(idx, level_index(threshold_hit.get("level_on_violation", "较大风险")))

    return {
        "card_id": card["card_id"],
        "hazard_type_id": card["hazard_type_id"],
        "hazard_type": card["hazard_type"],
        "category": card["category"],
        "risk_level": LEVELS[idx],
        "base_level": base,
        "rule_id": (override_hit or {}).get("override_id")
        or (threshold_hit or {}).get("rule_id")
        or "RL-" + card["hazard_type_id"].replace("HT-", ""),
        "clause_refs": clause_refs,
        "upgraded": {"major_pattern": major_hit, "severity_word": severity_hit},
        "override_id": (override_hit or {}).get("override_id"),
        "threshold_id": (threshold_hit or {}).get("threshold_id"),
        "human_confirm": bool(card.get("confidence", 1.0) < 0.6 or card.get("extractor") == "llm"),
    }
