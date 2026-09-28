"""Web 面板服务（M5）：FastAPI + 免构建静态页（webapp/，零第三方前端依赖）。

设计纪律（照 M3 pyvis_mod / M4 detector 可注入范式）：
- import 期零硬依赖 fastapi/uvicorn（只进 pyproject optional 组 ``web``）：
  缺依赖时 create_app/run_server 抛 RuntimeError 带 INSTALL_HINT，cli.cmd_serve
  捕获后打印提示 exit 2，不崩溃（评测与测试零 Web 依赖）；
- fastapi/uvicorn 经 _import_fastapi/_import_uvicorn 惰性获取，测试可注入模拟
  缺依赖路径（monkeypatch 抛 ImportError）；
- 上传核心逻辑 analyze_input 为纯函数（不依赖 fastapi 类型），HTTP 层薄封装：
  文件名清洗（防路径穿越）→ 落临时文件 → run_file 研判 → 报告内路径统一替换
  为上传原始文件名（脱敏第③步：临时目录/本机路径不入报告产物）→ 导出
  JSON/MD/docx 到 out_dir → 返回摘要、卡片与下载链接；
- 静态页 webapp/（index.html/app.js/style.css）零外链 CDN，断网可演示；
  /kg 挂载 examples/kg 目录供报告条款锚点（kg.html#REG%3A...）跳转定位；
- --scenario 覆盖面板预置示例场景（all=高处作业+临时用电两场景，对齐验收门
  "CLI + Web ≥2 场景真实演示"）。
"""

import shutil
import tempfile
from pathlib import Path

from . import config

INSTALL_HINT = ("Web 面板需要可选依赖 fastapi/uvicorn（pyproject web 组）："
                "py -m pip install fastapi uvicorn "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple")

ALLOWED_SUFFIXES = (".txt", ".docx")
FMT_MEDIA = {
    "json": "application/json",
    "md": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _import_fastapi():
    import fastapi
    return fastapi


def _import_uvicorn():
    import uvicorn
    return uvicorn


def scenario_payload(scenario="all"):
    """面板可用场景清单（--scenario 覆盖：all=高处作业+临时用电两场景）。"""
    from .datagen import SCENARIOS
    if scenario == "all":
        keys = list(SCENARIOS)
    elif scenario in SCENARIOS:
        keys = [scenario]
    else:
        raise ValueError("未知场景: %s（可选 all/gczy/lsyd）" % scenario)
    return [{"key": k, "name": SCENARIOS[k].get("title", k), "file": SCENARIOS[k]["file"]}
            for k in keys]


def analyze_input(content, filename, out_dir):
    """上传内容 → 研判报告与导出产物（纯函数，不依赖 fastapi 类型）。

    content 为 bytes 或 str；filename 为上传原始文件名（自动清洗路径成分）。
    返回 dict(report=报告 dict, downloads={fmt: 文件名或 None})；
    不支持的后缀/空内容抛 ValueError（HTTP 层转 400）。坏 docx/坏编码不崩溃：
    按流水线条目级降级纪律进 report["warnings"]。
    """
    name = Path(str(filename or "")).name
    if not name:
        name = "pasted.txt"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("暂不支持的文件类型: %s（支持 .txt/.docx）" % (suffix or "(无后缀)"))
    if isinstance(content, bytes):
        raw = content
    else:
        raw = str(content).encode("utf-8")
    if not raw.strip():
        raise ValueError("上传内容为空")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="siteguard_web_"))
    try:
        tmp_file = tmp_dir / name
        tmp_file.write_bytes(raw)
        from .pipeline import runner
        report = runner.run_file(tmp_file)
        # 脱敏第③步：报告内不落临时目录/本机路径——统一替换为上传原始文件名
        report["source_file"] = name
        for card in report.get("cards", []):
            src = card.get("source") or {}
            if src.get("file"):
                src["file"] = name

        from .report import export
        stem = tmp_file.stem
        export.export_json(report, out_dir / (stem + ".report.json"))
        export.export_md(report, out_dir / (stem + ".report.md"))
        downloads = {"json": stem + ".report.json", "md": stem + ".report.md",
                     "docx": None}
        try:
            export.export_docx(report, out_dir / (stem + ".report.docx"))
            downloads["docx"] = stem + ".report.docx"
        except ValueError as exc:  # 缺 python-docx：docx 下载不可用，其余不受影响
            report.setdefault("warnings", []).append(str(exc))
        return {"report": report, "downloads": downloads}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def create_app(out_dir="examples/web_output", scenario="all"):
    """构建 FastAPI 应用（缺 fastapi 依赖抛 RuntimeError 带 INSTALL_HINT）。"""
    try:
        fastapi = _import_fastapi()
    except Exception as exc:
        raise RuntimeError("%s（%s: %s）" % (INSTALL_HINT, type(exc).__name__, exc)) from exc
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    scenario_payload(scenario)  # --scenario 参数合法性前置校验

    app = fastapi.FastAPI(
        title="SiteGuard Web 面板",
        description="融合 LLM 与知识图谱的施工现场安全风险隐患智能研判系统",
        version=_app_version())
    out_path = config.repo_path(out_dir)
    webapp_dir = config.repo_path("webapp")
    kg_dir = config.repo_path("examples", "kg")

    @app.get("/")
    def index():
        return FileResponse(str(webapp_dir / "index.html"), media_type="text/html")

    @app.get("/api/health")
    def health():
        return {"ok": True, "tool": "SiteGuard", "scenario": scenario}

    @app.get("/api/scenarios")
    def api_scenarios():
        return scenario_payload(scenario)

    @app.get("/api/sample/{scenario_key}")
    def api_sample(scenario_key: str):
        spec = next((x for x in scenario_payload(scenario) if x["key"] == scenario_key), None)
        if spec is None:
            raise fastapi.HTTPException(
                status_code=404, detail="场景不存在或未包含在 --scenario=%s 中: %s"
                                        % (scenario, scenario_key))
        p = config.repo_path("data", "samples", "text", spec["file"])
        if not p.exists():
            raise fastapi.HTTPException(
                status_code=404, detail="样例文件不存在，请先运行：py -X utf8 -m siteguard.cli datagen")
        return {"key": spec["key"], "name": spec["name"], "filename": spec["file"],
                "text": p.read_text(encoding="utf-8")}

    @app.post("/api/analyze")
    def api_analyze(file: fastapi.UploadFile = fastapi.File(None),
                    text: str = fastapi.Form(None),
                    filename: str = fastapi.Form(None)):
        if file is not None and file.filename:
            content = file.file.read()
            name = file.filename
        elif text:
            content = text
            name = filename or "pasted.txt"
        else:
            raise fastapi.HTTPException(status_code=400, detail="请上传文件或粘贴文本")
        try:
            result = analyze_input(content, name, out_path)
        except ValueError as exc:
            raise fastapi.HTTPException(status_code=400, detail=str(exc))
        report = result["report"]
        return {
            "report_id": Path(str(name)).stem or "report",
            "source_file": report.get("source_file", ""),
            "record_count": report.get("record_count", 0),
            "hazard_count": report.get("hazard_count", 0),
            "warnings": report.get("warnings", []),
            "cards": report.get("cards", []),
            "downloads": result["downloads"],
        }

    @app.get("/api/report/{report_id}/{fmt}")
    def api_report(report_id: str, fmt: str):
        if fmt not in FMT_MEDIA:
            raise fastapi.HTTPException(status_code=404, detail="不支持的报告格式: %s" % fmt)
        safe_id = Path(report_id).name  # 防路径穿越
        p = out_path / ("%s.report.%s" % (safe_id, fmt))
        if not p.exists():
            raise fastapi.HTTPException(status_code=404, detail="报告不存在: %s" % p.name)
        return FileResponse(str(p), media_type=FMT_MEDIA[fmt], filename=p.name)

    if (webapp_dir / "index.html").exists():
        app.mount("/static", StaticFiles(directory=str(webapp_dir)), name="static")
    if (kg_dir / "kg.html").exists():
        app.mount("/kg", StaticFiles(directory=str(kg_dir)), name="kg")
    return app


def _app_version():
    from . import __version__
    return __version__


def run_server(host="127.0.0.1", port=8000, out_dir="examples/web_output", scenario="all"):
    """构建应用并启动 uvicorn（缺依赖抛 RuntimeError，由 cli.cmd_serve 兜底）。"""
    app = create_app(out_dir=out_dir, scenario=scenario)
    try:
        uvicorn = _import_uvicorn()
    except Exception as exc:
        raise RuntimeError("%s（%s: %s）" % (INSTALL_HINT, type(exc).__name__, exc)) from exc
    print("SiteGuard Web 面板：http://%s:%d  （Ctrl+C 停止；面板零外链，可断网演示）" % (host, port))
    uvicorn.run(app, host=host, port=port, log_level="warning")
