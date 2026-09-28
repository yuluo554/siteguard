"""端到端流水线：加载 → 清洗/解析 → 规则抽取 →(可选)LLM兜底 → 条款关联
→ 风险分级 → 建议生成 → 报告。

每个节点记录耗时；单条目失败降级不中断（warnings 汇总），保证任何时刻有可用产物。
"""

import time
from pathlib import Path

from .. import __version__ as pkg_version
from .. import config
from ..extract import rules as rules_mod
from ..extract import llm as llm_mod
from ..extract import vision as vision_mod
from ..ingest import parsers
from ..kg import schema as kg_schema
from ..reasoning import clause_linker, risk_level, suggest


def _timed(step, fn, *args, **kwargs):
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        return result, {"step": step, "seconds": round(time.time() - t0, 4), "ok": True}, []
    except Exception as exc:  # 条目级降级：记录并继续
        return None, {"step": step, "seconds": round(time.time() - t0, 4), "ok": False,
                      "error": "%s: %s" % (type(exc).__name__, exc)}, [str(exc)]


def run_file(sample_file, schema=None, graph=None, settings=None,
             vision_images=None, detector=None):
    """研判单个日志文件，返回报告 dict（不落盘）。缺输入文件直接报错。

    vision_images 提供样例图列表时启用视觉通路（extract/vision），视觉卡与文本卡
    经 merge_cards 融合；detector 为可注入检测器（仅供测试注入）。不带视觉输入时
    文本通路行为逐位不变。
    """
    sample_file = Path(sample_file)
    if not sample_file.exists():
        raise FileNotFoundError("输入文件不存在: %s" % sample_file)
    schema = schema or config.load_schema()
    graph = graph or kg_schema.build_seed_graph(schema)
    settings = settings or config.settings()
    warnings = []
    timings = []

    records, t, errs = _timed("parse", parsers.parse_log_file, sample_file)
    timings.append(t)
    warnings += errs
    records = records or []

    engine = rules_mod.RuleEngine(schema)
    cards, t, errs = _timed("extract_rules", engine.extract, records, str(sample_file))
    timings.append(t)
    warnings += errs
    cards = cards or []

    if not settings.get("disable_llm", True):
        extra, llm_warnings = llm_mod.extract_cards_llm(records, str(sample_file), settings)
        warnings += llm_warnings
        cards.extend(extra)

    if vision_images:
        vision_cards, vw = vision_mod.collect_vision_cards(vision_images, schema, detector=detector)
        warnings += vw
        cards, fw = vision_mod.merge_cards(cards, vision_cards)
        warnings += fw

    for i, card in enumerate(cards, 1):
        card["card_id"] = "HC-%05d" % i
        refs, errs = clause_linker.link(card, schema, graph)
        warnings += ["%s: %s" % (card["card_id"], e) for e in errs]
        judgment = risk_level.judge(card, refs, schema)
        judgment["suggestions"] = suggest.suggest(card, judgment, schema, graph)
        card["judgment"] = judgment

    report = {
        "tool": "SiteGuard",
        "version": pkg_version,
        "source_file": str(sample_file),
        "record_count": len(records),
        "hazard_count": len(cards),
        "cards": cards,
        "warnings": warnings,
        "timings": timings,
        "settings": {"disable_llm": settings.get("disable_llm", True)},
    }
    if vision_images:
        report["vision_images"] = [str(p) for p in vision_images]
    return report


def run_batch(input_dir, out_dir=None, schema=None, graph=None, settings=None):
    """批量研判目录下所有 .txt；out_dir 提供时写 JSON+Markdown 报告。"""
    schema = schema or config.load_schema()
    graph = graph or kg_schema.build_seed_graph(schema)
    settings = settings or config.settings()
    d = Path(input_dir)
    if not d.exists():
        raise FileNotFoundError("输入目录不存在: %s" % d)
    files = sorted(p for p in d.iterdir() if p.suffix.lower() == ".txt")
    reports = []
    for f in files:
        try:
            reports.append(run_file(f, schema, graph, settings))
        except Exception as exc:
            reports.append({"source_file": str(f), "error": "%s: %s" % (type(exc).__name__, exc),
                            "cards": [], "warnings": ["文件级失败: %s" % exc]})
    summary = {
        "files": len(files),
        "hazard_count": sum(r.get("hazard_count", 0) for r in reports),
        "failed_files": sum(
            1 for r in reports
            if "error" in r or any(not t.get("ok") for t in r.get("timings", []))),
    }
    if out_dir:
        from ..report import export
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for r in reports:
            stem = Path(r["source_file"]).stem
            if "error" not in r:
                export.export_json(r, out / (stem + ".report.json"))
                export.export_md(r, out / (stem + ".report.md"))
        export.export_json(summary, out / "summary.json")
    return {"summary": summary, "reports": reports}
