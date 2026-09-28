"""SiteGuard 命令行入口（argparse，stdlib 零依赖）。

子命令：
  demo       两大典型场景端到端研判，产出 JSON+Markdown 报告（--docx 可选导出 Word）
  build-kg   构建种子知识图谱并导出统计
  eval       内置基准评测（解析 F1 + 分级准确率）
  datagen    （重新）生成样例与真值
  serve      Web 面板（M5：FastAPI + 免构建静态页；缺依赖优雅提示 exit 2 不崩溃）
  version    打印版本

Windows 控制台统一按 UTF-8 输出，避免 GBK 编码报错。
"""

import argparse
import json
import sys

from . import __version__


def _ensure_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        enc = getattr(stream, "encoding", "") or ""
        if enc.lower().replace("-", "") not in ("utf8",):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def cmd_demo(args):
    from . import config
    from .datagen import SCENARIOS, generate_all
    from .pipeline import runner

    generate_all(force=False)
    if args.scenario == "all":
        files = [config.repo_path("data", "samples", "text", s["file"])
                 for s in SCENARIOS.values()]
    else:
        spec = SCENARIOS[args.scenario]
        files = [config.repo_path("data", "samples", "text", spec["file"])]

    video_frames = []
    if getattr(args, "video", ""):
        from .extract import video as video_mod
        try:
            video_frames = video_mod.extract_keyframes(
                args.video, config.repo_path(args.out) / "video_frames")
            print("视频抽帧：%d 帧关键帧（复用视觉通路参与图文融合，optional video 组）"
                  % len(video_frames))
        except ValueError as exc:  # 缺 opencv / 坏文件：打印说明降级，不崩溃
            print("说明：视频抽帧降级：%s" % exc)

    reports = []
    for f in files:
        vision_images = [str(p) for p in video_frames]
        if getattr(args, "with_vision", False):
            img_dir = config.repo_path("data", "samples", "images")
            if img_dir.exists():
                imgs = sorted(
                    (p for p in img_dir.iterdir()
                     if p.suffix.lower() in (".jpg", ".jpeg", ".png")),
                    key=lambda p: p.name)
                vision_images += [str(p) for p in imgs]
            if not vision_images:
                print("说明：data/samples/images/ 下无样例图，本次演示跳过视觉通路。")
        report = runner.run_file(f, vision_images=vision_images)
        if getattr(args, "vector_fallback", False):
            from .retrieval import vector as vector_mod
            n_fb = vector_mod.fallback_clauses(
                report, vector_mod.build_regulation_index())
            print("  向量检索兜底：%d 张卡片补充候选条款（提示性，非判定依据）" % n_fb)
        out_dir = config.repo_path(args.out)
        from .report import export
        stem = f.stem
        export.export_json(report, out_dir / (stem + ".report.json"))
        export.export_md(report, out_dir / (stem + ".report.md"))
        if getattr(args, "docx", False):
            try:
                export.export_docx(report, out_dir / (stem + ".report.docx"))
            except ValueError as exc:  # 缺 python-docx：打印提示跳过，不崩溃（照 --with-vision 降级范式）
                print("说明：%s" % exc)
        reports.append(report)

    for r in reports:
        if getattr(args, "with_vision", False) or video_frames:
            vc = sum(1 for c in r["cards"] if "vision" in (c.get("merged_from") or []))
            print("  视觉通路：视觉/融合卡片 %d 条%s"
                  % (vc, "" if vc else "（缺依赖或无检出时优雅降级，详见 warnings）"))
        print("== %s ==" % r["source_file"])
        print("  记录 %d 条，识别隐患 %d 条，警告 %d 条"
              % (r["record_count"], r["hazard_count"], len(r["warnings"])))
        for c in r["cards"]:
            j = c["judgment"]
            print("  [%s|%s] %s -> %s（%s）"
                  % (j["risk_level"], c["extractor"], c["quote"],
                     j["hazard_type"],
                     "、".join("%s %s" % (x["standard"], x["clause"])
                               for x in j["clause_refs"]) or "无条款"))
    print("报告目录：%s" % config.repo_path(args.out))
    return 0


def cmd_build_kg(args):
    from . import config
    from .kg import schema as kg_schema
    from .kg import visualize

    graph = kg_schema.build_seed_graph()
    out = config.repo_path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = visualize.export_stats(graph, out / "kg_stats.json")
    visualize.export_graph_json(graph, out / "kg.json")
    result = visualize.export_html(graph, out / "kg.html")
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))
    ok = payload["stats"]["node_count"] >= payload["target_min_nodes"]
    print("节点目标（≥100 节点）：%s" % ("已达标" if ok else "未达标，需扩充"))
    if result.get("ok"):
        print("可视化：%s（离线单文件：Category/RiskLevel 过滤、点击隐患类型高亮一跳邻居、悬浮看属性；条款锚点 kg.html#<URL编码节点id>）"
              % result.get("path"))
    else:
        print("可视化降级：%s" % result.get("hint", "缺 pyvis 依赖"))
    return 0


def cmd_eval(args):
    from . import config
    from .benchmark import run_eval

    generate_if_needed()
    payload = run_eval(out_path=config.repo_path(args.out))
    print(json.dumps(payload["micro"], ensure_ascii=False))
    for r in payload["files"]:
        print("%s: F1=%.4f P=%.4f R=%.4f 分级准确率=%s"
              % (r["file"], r["f1"], r["precision"], r["recall"], r["level_accuracy"]))
    for fname, st in payload.get("field_level", {}).items():
        print("字段级[%s]: P=%.4f R=%.4f F1=%.4f (tp=%d fp=%d fn=%d)"
              % (fname, st["precision"], st["recall"], st["f1"],
                 st["tp"], st["fp"], st["fn"]))
    for pc in payload.get("paired", []):
        print("配对[%s]: gold差异=%d 检出=%d 命中=%d 漏检=%d 误报差异=%d"
              % (pc["case"], pc["gold_diffs"], pc["detected"], pc["hits"],
                 len(pc["missed"]), len(pc["false"])))
    e2e = payload.get("end_to_end") or {}
    if e2e:
        print("端到端: 检出 %d/%d (%.4f)  误报 %d/%d (%.4f)"
              % (e2e["detected"], e2e["gold_count"], e2e["detection_rate"],
                 e2e["false_positives"], e2e["pred_count"], e2e["false_positive_rate"]))
    target = payload["target"]
    field_ok = all(st["f1"] >= target.get("field_f1", target["f1"])
                   for st in payload.get("field_level", {}).values())
    paired_ok = all(not pc["missed"] and not pc["false"]
                    for pc in payload.get("paired", []))
    e2e_ok = (not e2e) or (e2e["false_positives"] <= target.get("e2e_fpr", 0)
                           and e2e["detection_rate"] >= target.get("e2e_detection", 0.90))
    passed = (payload["micro"]["f1"] >= target["f1"]
              and payload["micro"]["fp"] <= target["fp"]
              and field_ok and paired_ok and e2e_ok)
    print("目标 F1>=%.2f 且误报<=%d（字段级 F1>=%.2f、配对差异全检出、端到端误报=%d）：%s"
          % (target["f1"], target["fp"], target.get("field_f1", target["f1"]),
             target.get("e2e_fpr", 0), "达标" if passed else "未达标"))
    print("评测报告：%s" % config.repo_path(args.out))
    return 0 if passed else 1


def generate_if_needed():
    from .datagen import generate_all
    generate_all(force=False)


def cmd_datagen(args):
    from .datagen import generate_all
    made = generate_all(force=args.force)
    print(json.dumps(made, ensure_ascii=False))
    return 0


def cmd_serve(args):
    """Web 面板（M5）：FastAPI + 免构建静态页。

    缺 fastapi/uvicorn 依赖时打印安装提示 exit 2，不崩溃（import 期零硬依赖，
    照 M3 pyvis_mod / M4 detector 可注入降级范式）。
    """
    from .serverapp import INSTALL_HINT, run_server
    try:
        run_server(args.host, args.port, out_dir=args.out, scenario=args.scenario)
    except (ImportError, RuntimeError) as exc:
        print("Web 面板启动失败：%s" % exc)
        print(INSTALL_HINT)
        return 2
    except KeyboardInterrupt:
        print("\nserve 已停止。")
        return 0
    return 0


def cmd_version(args):
    print("SiteGuard v%s" % __version__)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="siteguard", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("demo", help="典型场景端到端研判演示")
    d.add_argument("--scenario", choices=["all", "gczy", "lsyd"], default="all",
                   help="gczy=高处作业，lsyd=临时用电")
    d.add_argument("--out", default="examples/demo_output", help="报告输出目录")
    d.add_argument("--docx", action="store_true",
                   help="额外导出 Word 报告（含签署栏；缺 python-docx 时打印提示跳过）")
    d.add_argument("--with-vision", action="store_true",
                   help="启用视觉通路：data/samples/images/ 下样例图参与图文融合；"
                        "无样例图/缺依赖时优雅降级（exit 0）")
    d.add_argument("--video", default="",
                   help="视频文件路径：抽关键帧参与图文融合（optional video 组，无需新模型；"
                        "缺 opencv/坏文件打印说明降级 exit 0）")
    d.add_argument("--vector-fallback", action="store_true",
                   help="对无条款依据的卡片以向量检索补充候选条款"
                        "（提示性信息，非判定依据；纯 stdlib 词法向量实现）")
    d.set_defaults(func=cmd_demo)

    k = sub.add_parser("build-kg", help="构建种子知识图谱并导出统计")
    k.add_argument("--out", default="examples/kg", help="输出目录")
    k.set_defaults(func=cmd_build_kg)

    e = sub.add_parser("eval", help="内置基准评测（解析 F1 + 分级准确率）")
    e.add_argument("--out", default="examples/eval_report.json", help="评测报告路径")
    e.set_defaults(func=cmd_eval)

    g = sub.add_parser("datagen", help="（重新）生成样例与真值语料")
    g.add_argument("--force", action="store_true", help="覆盖已有样例")
    g.set_defaults(func=cmd_datagen)

    s = sub.add_parser("serve", help="Web 面板（FastAPI + 免构建静态页，M5）")
    s.add_argument("--host", default="127.0.0.1", help="监听地址（默认本机）")
    s.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    s.add_argument("--out", default="examples/web_output", help="面板研判报告输出目录")
    s.add_argument("--scenario", choices=["all", "gczy", "lsyd"], default="all",
                   help="面板预置示例场景覆盖（all=高处作业+临时用电两场景）")
    s.set_defaults(func=cmd_serve)

    v = sub.add_parser("version", help="打印版本")
    v.set_defaults(func=cmd_version)
    return p


def main(argv=None):
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
