"""规则抽取引擎（主通路，零 API 依赖、可评测）。

匹配纪律：
- 正则模式全部来自受控词表 hazard_types.json，禁止在代码里散落魔法字符串；
- 命中即产 HazardCard（统一中间表示），后续研判只认条目卡。
"""

import re


def new_card(source_file, record_index, quote, hazard_def, extractor, site_object, confidence):
    return {
        "card_id": None,  # 由 pipeline 统一编号
        "source": {"file": str(source_file), "record_index": record_index},
        "quote": quote,
        "extractor": extractor,
        "hazard_type": hazard_def["name"],
        "hazard_type_id": hazard_def["id"],
        "category": hazard_def["category"],
        "work_type": hazard_def.get("work_type", "普通作业"),
        "site_object": site_object,
        "attrs": {},
        "evidence": {"record_index": record_index},
        "confidence": confidence,
        "merged_from": [extractor],
    }


class RuleEngine:
    def __init__(self, schema):
        self.schema = schema
        self._compiled = []
        for ht in schema["hazard_types"]:
            pats = [re.compile(p) for p in ht.get("patterns", [])]
            self._compiled.append((ht, pats))

    def extract(self, records, source_file="<memory>"):
        cards = []
        for rec in records:
            text = rec["text"]
            for ht, pats in self._compiled:
                if not any(p.search(text) for p in pats):
                    continue
                site_object = self._find_site_object(ht, text)
                cards.append(new_card(source_file, rec["index"], text, ht, "rules", site_object, 0.95))
        return cards

    @staticmethod
    def _find_site_object(ht, text):
        # 最长匹配：如"分配电箱"同时命中"配电箱"与"分配电箱"时取更具体的部位
        hits = [obj for obj in ht.get("site_objects", []) if obj in text]
        if not hits:
            return ""
        return max(hits, key=len)
