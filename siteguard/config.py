"""配置与路径解析：全部路径基于仓库根目录（支持中文路径）。"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def repo_path(*parts):
    """返回仓库内相对路径的绝对 Path（容忍中文目录名）。"""
    return ROOT.joinpath(*parts)


def display_path(path, root=None):
    """仓库内绝对路径 → posix 风格相对路径（M5 脱敏第③步：本机路径不入产物）。

    路径不在仓库内（如测试临时目录、用户上传的本地文件）时原样返回 str(path)。
    """
    root = Path(root).resolve() if root is not None else ROOT.resolve()
    try:
        p = Path(path)
        if not p.is_absolute():
            return p.as_posix()
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return str(path)


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise FileNotFoundError("配置/数据文件不存在: %s" % p)
    with open(str(p), "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("数据文件不存在: %s" % p)
    items = []
    with open(str(p), "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError as exc:
                raise ValueError("JSONL 第 %d 行解析失败(%s): %s" % (i, p, exc))
    return items


def settings():
    """运行配置：骨架期 LLM 默认关闭，M2 接入 DashScope 后由 config/settings.json 打开。"""
    disable_llm = os.environ.get("SITEGUARD_DISABLE_LLM", "1") == "1"
    cfg_path = repo_path("config", "settings.json")
    file_cfg = load_json(cfg_path, default={}) if cfg_path.exists() else {}
    llm_cfg = load_json(repo_path("config", "settings.example.json"), default={}).get("llm", {})
    llm_cfg.update(file_cfg.get("llm", {}))
    return {
        "disable_llm": disable_llm,
        "llm": llm_cfg,
    }


def knowledge_paths():
    return {
        "hazard_types": repo_path("data", "knowledge", "seed", "hazard_types.json"),
        "measures": repo_path("data", "knowledge", "seed", "measures.json"),
        "regulations": repo_path("data", "knowledge", "regulations", "seed_regulations.jsonl"),
        "thresholds": repo_path("data", "knowledge", "thresholds", "seed_thresholds.json"),
        "rules": repo_path("data", "knowledge", "rules", "rules_v1.json"),
        "cases": repo_path("data", "knowledge", "cases", "cases.jsonl"),
    }


def load_schema():
    """加载受控词表与规则种子，返回 schema dict（全模块共用）。"""
    kp = knowledge_paths()
    ht = load_json(kp["hazard_types"])
    return {
        "meta": ht.get("meta", {}),
        "categories": ht["categories"],
        "risk_levels": ht["risk_levels"],
        "hazard_types": ht["hazard_types"],
        "hazard_type_by_id": {h["id"]: h for h in ht["hazard_types"]},
        "measures": load_json(kp["measures"]).get("measures", []),
        "measure_by_id": {m["id"]: m for m in load_json(kp["measures"]).get("measures", [])},
        "regulations": load_jsonl(kp["regulations"]),
        "thresholds": load_json(kp["thresholds"]).get("thresholds", []),
        "rules": load_json(kp["rules"]),
        "cases": load_jsonl(kp["cases"]),
    }
