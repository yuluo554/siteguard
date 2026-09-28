# -*- coding: utf-8 -*-
"""向量检索兜底：条款库词法向量检索（M6 缓冲周加分项）。

定位与纪律：
- **兜底候选不是判定依据**：仅对 clause_refs 为空的卡片（如受控词表中条款留空的
  HT-GCZY-007 未佩戴安全帽）附加 fallback_clauses 候选列表，逐条标注"非判定依据"；
  不改动 risk_level / clause_refs / suggestions，研判结论与评测指标零影响
  （评测零依赖：本模块不参与默认研判流程，仅 demo --vector-fallback 显式启用）。
- **纯 stdlib 实现**：字符二元组 TF-IDF 词法向量 + 余弦相似度，零第三方依赖
  （"依赖只进 optional 组"纪律的更强形态——本模块根本没有依赖）；语义向量后端
  可经 embedder 注入扩展（照 M2 transport / M4 detector 可注入范式），缺省 None
  走本地词法向量。
- 检索范围仅为 data/knowledge/regulations/ 条文库，候选必挂条款编号与标准名，
  不产生无出处内容（防幻觉纪律不变）。
"""

import json
import math
import re
from pathlib import Path

from .. import config

FALLBACK_NOTE = "向量检索兜底候选，非判定依据（以官方文本为准）"

# 保留 CJK/字母/数字，剔除标点与空白后取字符二元组（中文短文本词法检索稳健）
_KEEP_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


def _tokenize(text):
    """文本 → 词法 token 计数 dict（字符二元组；单字符文本取自身；空文本空 dict）。"""
    s = "".join(_KEEP_RE.findall(str(text).lower()))
    if not s:
        return {}
    if len(s) == 1:
        return {s: 1}
    grams = {}
    for i in range(len(s) - 1):
        g = s[i:i + 2]
        grams[g] = grams.get(g, 0) + 1
    return grams


def _l2(weights):
    """稀疏权重 dict L2 归一化（零向量原样返回）。"""
    norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
    return {t: w / norm for t, w in weights.items()}


class VectorIndex:
    """可检索向量索引：docs = [{id, text, standard, clause, std_name, ...}]。

    embedder=None：字符二元组 TF-IDF 稀疏向量（TF 子线性 + 平滑 IDF，L2 归一化）；
    embedder=text->list[float]：注入稠密向量（测试注入或语义后端扩展），L2 归一化
    后余弦相似度。检索接口统一返回 [(doc, score)] 按分数降序、同分按下标稳定排序。
    """

    def __init__(self, docs, embedder=None):
        self.docs = list(docs)
        self._embedder = embedder
        self._sparse = []
        self._dense = None
        if embedder is not None:
            self._dense = [self._norm_dense(embedder(d.get("text", "")))
                           for d in self.docs]
            return
        df = {}
        tfs = []
        for d in self.docs:
            tf = _tokenize(d.get("text", ""))
            tfs.append(tf)
            for t in tf:
                df[t] = df.get(t, 0) + 1
        n = max(1, len(self.docs))
        self._sparse = [
            _l2({t: (1.0 + math.log(c)) * (math.log((1.0 + n) / (1.0 + df[t])) + 1.0)
                 for t, c in tf.items()})
            for tf in tfs
        ]

    @staticmethod
    def _norm_dense(vec):
        v = [float(x) for x in (vec or [])]
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def search(self, query, top_k=3):
        """查询 → [(doc, score)] 降序，最多 top_k 条；空索引/空查询返回空表。"""
        hits = []
        if self._embedder is not None:
            qv = self._norm_dense(self._embedder(str(query)))
            for i, dv in enumerate(self._dense):
                score = sum(a * b for a, b in zip(qv, dv))
                hits.append((score, i))
        else:
            q = _l2(_tokenize(query))
            if q:
                for i, dv in enumerate(self._sparse):
                    if not dv:
                        continue
                    score = sum(w * dv[t] for t, w in q.items() if t in dv)
                    hits.append((score, i))
        hits.sort(key=lambda x: (-x[0], x[1]))
        top_k = max(0, int(top_k))
        return [(self.docs[i], round(score, 4)) for score, i in hits[:top_k]]


def build_regulation_index(regs_path=None, embedder=None):
    """装载条文库 → VectorIndex（缺省 data/knowledge/regulations/seed_regulations.jsonl）。

    doc 的 text 由标准名 + 条文文本 + 关键词拼接；standard/clause/std_name 作为
    候选元数据随命中返回（候选必挂条款出处）。
    """
    p = Path(regs_path) if regs_path else config.repo_path(
        "data", "knowledge", "regulations", "seed_regulations.jsonl")
    docs = []
    if p.exists():
        with open(str(p), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                docs.append({
                    "id": "%s %s" % (r.get("std_id", ""), r.get("clause", "")),
                    "text": " ".join([r.get("std_name", ""), r.get("text", ""),
                                      " ".join(r.get("keywords") or [])]),
                    "standard": r.get("std_id", ""),
                    "clause": r.get("clause", ""),
                    "std_name": r.get("std_name", ""),
                })
    return VectorIndex(docs, embedder=embedder)


def fallback_clauses(report, index, top_k=2, min_score=0.05):
    """对 clause_refs 为空的卡片附加 fallback_clauses 候选；返回补充的卡片数。

    - 查询文本 = 原文摘录 + 隐患类型名；
    - 候选逐条 {standard, clause, std_name, score, note}，note 标注非判定依据；
    - 已有条款依据的卡片一律不动；低于 min_score 的候选不补充；
    - 不改动卡片任何判定字段，报告其余部分逐位不变。
    """
    annotated = 0
    for card in report.get("cards", []):
        j = card.get("judgment") or {}
        if j.get("clause_refs"):
            continue
        query = " ".join([card.get("quote", ""), card.get("hazard_type", "")])
        cands = []
        for doc, score in index.search(query, top_k=top_k):
            if score < float(min_score):
                continue
            cands.append({
                "standard": doc.get("standard", ""),
                "clause": doc.get("clause", ""),
                "std_name": doc.get("std_name", ""),
                "score": score,
                "note": FALLBACK_NOTE,
            })
        if cands:
            card["fallback_clauses"] = cands
            annotated += 1
    return annotated
