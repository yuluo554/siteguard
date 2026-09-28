"""内置基准评测（零 API 依赖，可重复）：抽取 F1 + 分级准确率 + 字段级 P/R/F1 + 配对差异检出。

口径（M1 v2）：
- 主指标：预测集与真值集按 (记录序号, hazard_type_id) 键值对做微平均 P/R/F1；
- 分级准确率：键值对齐且判定等级 == 期望等级的比例；
- 字段级 P/R/F1：在键值对齐的命中对上比较 hazard_type / category / site_object
  三个字段（两侧皆空不计，单侧空计 fp/fn，值不等同时计 fp 与 fn）；
- 配对差异：施工日志版 vs 巡查记录版按规范化时间戳对齐，检出 漏项/数值不一致/多报，
  与生成器 gold 差异清单比对。
目标（M1）：F1 ≥ 0.90（v2 语料变体更多），误报 FP = 0（硬性不变）。
"""

import json
import re
from collections import Counter
from pathlib import Path

from . import config
from .pipeline import runner

FIELDS = ("hazard_type", "category", "site_object")
_TARGET = {"f1": 0.90, "fp": 0, "field_f1": 0.90, "e2e_detection": 0.90, "e2e_fpr": 0}
_DIGIT_RE = re.compile(r"\d+")


def _prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _pairs_from_report(report):
    return {(c["source"]["record_index"], c["hazard_type_id"])
            for c in report.get("cards", [])}


def field_stats(matched_keys, cards_by_key, gold_by_key):
    """字段级统计（纯函数，便于单测）：matched_keys 为对齐的 (index, hazard_type_id) 集合。"""
    stats = {f: {"tp": 0, "fp": 0, "fn": 0} for f in FIELDS}
    for key in matched_keys:
        card = cards_by_key[key]
        gold = gold_by_key[key]
        for f in FIELDS:
            pred = (card.get(f) or "").strip()
            gold_val = (gold.get(f) or "").strip()
            if pred and gold_val:
                if pred == gold_val:
                    stats[f]["tp"] += 1
                else:
                    stats[f]["fp"] += 1
                    stats[f]["fn"] += 1
            elif pred:
                stats[f]["fp"] += 1
            elif gold_val:
                stats[f]["fn"] += 1
    return stats


def _field_payload(stats):
    return {f: dict(s, **_prf(s["tp"], s["fp"], s["fn"])) for f, s in stats.items()}


def eval_file(sample_path, gold_path, schema=None, graph=None, settings=None):
    schema = schema or config.load_schema()
    report = runner.run_file(sample_path, schema, graph, settings)
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    gold_by_key = {(r["index"], r["hazard_type_id"]): r for r in gold["records"]}
    cards_by_key = {(c["source"]["record_index"], c["hazard_type_id"]): c
                    for c in report.get("cards", [])}
    gold_pairs = set(gold_by_key)
    pred_pairs = set(cards_by_key)

    tp = len(gold_pairs & pred_pairs)
    fp = len(pred_pairs - gold_pairs)
    fn = len(gold_pairs - pred_pairs)

    level_total, level_hit = 0, 0
    for key in gold_pairs & pred_pairs:
        level_total += 1
        if cards_by_key[key]["judgment"]["risk_level"] == gold_by_key[key]["expected_level"]:
            level_hit += 1

    fstats = field_stats(gold_pairs & pred_pairs, cards_by_key, gold_by_key)
    prf = _prf(tp, fp, fn)

    # 端到端指标（M2）：全链路研判结果 vs gold——检出=命中且分级正确，误报=预测集多报
    e2e = {
        "detected": level_hit,
        "gold_count": len(gold_pairs),
        "detection_rate": round(level_hit / len(gold_pairs), 4) if gold_pairs else 1.0,
        "false_positives": fp,
        "pred_count": len(pred_pairs),
        "false_positive_rate": round(fp / len(pred_pairs), 4) if pred_pairs else 0.0,
    }

    return {
        "file": str(sample_path),
        "gold_count": len(gold_pairs),
        "pred_count": len(pred_pairs),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": prf["precision"],
        "recall": prf["recall"],
        "f1": prf["f1"],
        "level_accuracy": round(level_hit / level_total, 4) if level_total else None,
        "field_stats": _field_payload(fstats),
        "end_to_end": e2e,
        "warnings": report.get("warnings", []),
    }


def _digit_multiset(text):
    return Counter(_DIGIT_RE.findall(text))


def detect_paired_diffs(log_records, patrol_records):
    """按规范化时间戳对齐两版记录，检出 漏项/多报/数值不一致 三类差异。

    数值不一致 = 同一时间戳两侧文本的数字多重集不同（楼层/楼号等相同数字不受影响）。
    """
    log_by = {}
    for r in log_records:
        log_by.setdefault(r["timestamp"], r)
    patrol_by = {}
    for r in patrol_records:
        patrol_by.setdefault(r["timestamp"], r)
    diffs = []
    for ts, r in log_by.items():
        if ts not in patrol_by:
            diffs.append({"kind": "missing", "timestamp": ts, "index_in_log": r["index"]})
    for ts, r in patrol_by.items():
        if ts not in log_by:
            diffs.append({"kind": "extra", "timestamp": ts, "index_in_patrol": r["index"]})
    for ts, r in log_by.items():
        pr = patrol_by.get(ts)
        if pr is not None and _digit_multiset(r["text"]) != _digit_multiset(pr["text"]):
            diffs.append({"kind": "value", "timestamp": ts,
                          "index_in_log": r["index"], "index_in_patrol": pr["index"]})
    diffs.sort(key=lambda d: d["timestamp"])
    return diffs


def eval_paired():
    """配对语料差异检出 vs 生成器 gold 差异清单。"""
    from .datagen import PAIRED
    from .ingest import parsers

    cases = []
    for key, pspec in PAIRED.items():
        base = config.repo_path("data", "eval", "cases")
        log_records = parsers.parse_log_file(base / pspec["log"])
        patrol_records = parsers.parse_log_file(base / pspec["patrol"])
        gold = config.load_json(base / pspec["gold"])
        detected = detect_paired_diffs(log_records, patrol_records)
        gold_keys = {(d["kind"], d["timestamp"]) for d in gold["diffs"]}
        det_keys = {(d["kind"], d["timestamp"]) for d in detected}
        hits = gold_keys & det_keys
        cases.append({
            "case": key,
            "gold_diffs": len(gold_keys),
            "detected": len(det_keys),
            "hits": len(hits),
            "missed": sorted("%s@%s" % k for k in gold_keys - det_keys),
            "false": sorted("%s@%s" % k for k in det_keys - gold_keys),
        })
    return cases


def run_eval(settings=None, out_path=None):
    schema = config.load_schema()
    graph = None  # 评测不依赖图谱内容，条款关联走词表即可
    results = []
    for key, spec in _scenarios():
        txt = config.repo_path("data", "samples", "text", spec["file"])
        gold = config.repo_path("data", "eval", "gold", spec["file"].replace(".txt", ".gold.json"))
        results.append(eval_file(txt, gold, schema, graph, settings))
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    micro = dict({"tp": tp, "fp": fp, "fn": fn}, **_prf(tp, fp, fn))

    field_agg = {f: {"tp": 0, "fp": 0, "fn": 0} for f in FIELDS}
    for r in results:
        for f in FIELDS:
            for k in ("tp", "fp", "fn"):
                field_agg[f][k] += r["field_stats"][f][k]
    field_level = _field_payload(field_agg)

    # 端到端指标汇总（M2）：全链路检出率/误报率
    e2e_gold = sum(r["end_to_end"]["gold_count"] for r in results)
    e2e_det = sum(r["end_to_end"]["detected"] for r in results)
    e2e_fp = sum(r["end_to_end"]["false_positives"] for r in results)
    e2e_pred = sum(r["end_to_end"]["pred_count"] for r in results)
    end_to_end = {
        "detected": e2e_det,
        "gold_count": e2e_gold,
        "detection_rate": round(e2e_det / e2e_gold, 4) if e2e_gold else 1.0,
        "false_positives": e2e_fp,
        "pred_count": e2e_pred,
        "false_positive_rate": round(e2e_fp / e2e_pred, 4) if e2e_pred else 0.0,
    }

    payload = {
        "metric": "hazard_extraction_micro",
        "corpus": "v2",
        # M5 脱敏第③步：评测报告内的样例路径统一为仓库相对路径（本机路径不入产物）
        "files": [dict(r, file=config.display_path(r["file"])) for r in results],
        "micro": micro,
        "field_level": field_level,
        "end_to_end": end_to_end,
        "paired": eval_paired(),
        "target": dict(_TARGET),
        "note": "零 API 依赖；样例/真值/配对差异由 siteguard.datagen 生成（seed=42，corpus v2）；"
                "字段级指标在 (index, hazard_type_id) 对齐命中对上统计。",
    }
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _scenarios():
    from .datagen import SCENARIOS
    return SCENARIOS.items()
