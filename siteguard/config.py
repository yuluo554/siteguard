"""配置与路径解析：支持源码态（仓库根）与装态（pip 安装到 <prefix>/share/siteguard）。

两种布局（v0.1.1 起，DEC2=B 附 sdist/wheel 后必须都成立）：

- **源码态**：本文件在 ``<repo>/siteguard/config.py``，``ROOT`` = 仓库根，
  资产（data/ webapp/ config/）与产物（examples/）都在仓库里，行为与 0.1.0 一致；
- **装态**：本文件在 ``<prefix>/Lib/site-packages/siteguard/config.py``，仓库根不存在。
  资产由 ``[tool.setuptools.data-files]`` 装到 ``<prefix>/share/siteguard/{data,webapp,config}``，
  由 :func:`share_root` 回落到那里；产物（examples/ 下的 eval/demo/kg 输出）**不能**
  写进 site-packages，回落到 ``<cwd>/examples``（或 ``$SITEGUARD_OUT_ROOT``）。

因此路径分成三类，别混用：
- :func:`asset_path` —— 只读资产（data/ webapp/ config/），装态会去 share 找；
- :func:`out_path`   —— 可写产物（examples/ 与用户指定的 --out），总是落在可写处；
- :func:`repo_path`  —— 历史名字，等价于 asset_path（保留给既有调用点与测试）。
"""

import json
import os
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 装态 share 目录名（与 pyproject 的 data-files 前缀一致）
SHARE_SUBDIR = Path("share") / "siteguard"

# 资产目录名：只有这些前缀走 asset_path 解析到 share
ASSET_DIRS = ("data", "webapp", "config")


def _share_roots():
    """候选 ``<...>/share/siteguard`` 目录（装态资产落点），按优先级排列。"""
    bases = []
    for prefix in (sys.prefix, getattr(sys, "base_prefix", None)):
        if prefix:
            bases.append(Path(prefix))
    user_base = getattr(site, "USER_BASE", None)
    if user_base:
        bases.append(Path(user_base))
    try:
        for site_dir in list(site.getsitepackages()) + [site.getusersitepackages()]:
            p = Path(site_dir)
            bases.append(p.parent.parent)   # <prefix>/Lib/site-packages -> <prefix>
            bases.append(p.parent)          # <prefix>/Lib -> <prefix>
    except Exception:  # pragma: no cover - 极端环境（无 site 支持）
        pass

    roots = []
    for base in bases:
        cand = base / SHARE_SUBDIR
        if cand not in roots:
            roots.append(cand)
    return roots


def is_installed_layout():
    """当前是否处于"装态"（仓库根的 data/ 不存在，但 share 里有）。"""
    if (ROOT / "data" / "knowledge" / "seed" / "hazard_types.json").is_file():
        return False
    return any((r / "data" / "knowledge" / "seed" / "hazard_types.json").is_file()
               for r in _share_roots())


def share_root():
    """装态资产根目录；源码态返回仓库根（调用方可无脑 join）。"""
    if (ROOT / "data" / "knowledge" / "seed" / "hazard_types.json").is_file():
        return ROOT
    for cand in _share_roots():
        if (cand / "data" / "knowledge" / "seed" / "hazard_types.json").is_file():
            return cand
    return ROOT


def asset_path(*parts):
    """只读资产路径（data/ webapp/ config/）：源码态在仓库，装态在 share。"""
    if parts and parts[0] in ASSET_DIRS:
        root = share_root()
        if root != ROOT:
            return root.joinpath(*parts)
    return ROOT.joinpath(*parts)


def writable_data_root():
    """``data/`` 的可写根：源码态就是仓库的 data/，装态是 ``<out_root>/data``。

    为什么要分：装态下 ``data/`` 在 site-packages 里（只读），而 ``datagen``
    需要写样例与真值；写进 site-packages 会被权限拒绝，或污染已安装包。
    """
    if is_installed_layout():
        return out_root() / "data"
    return ROOT / "data"


def data_path(*parts):
    """数据文件路径：``knowledge/`` 是只读资产；其余（samples / eval）可被重生成。

    读取顺序（仅对可重生成的部分）：先看可写根里有没有（datagen --force 的产物），
    再回落到随包资产。这样"装态下先 datagen --force 再 eval"也能自洽。
    """
    if parts and parts[0] == "knowledge":
        return asset_path("data", *parts)
    cand = writable_data_root().joinpath(*parts)
    if cand.exists():
        return cand
    return asset_path("data", *parts)


def out_root():
    """可写产物根目录（examples/ 的父目录）。

    源码态 = 仓库根（保持 0.1.0 行为，产物仍写在仓库内、仍被 git 跟踪）；
    装态   = ``$SITEGUARD_OUT_ROOT`` 或 ``<cwd>``（site-packages 不可写）。
    """
    env = os.environ.get("SITEGUARD_OUT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    if is_installed_layout():
        return Path.cwd()
    return ROOT


def out_path(*parts):
    """可写产物路径（examples/ 与 --out 目标）。"""
    return out_root().joinpath(*parts)


def repo_path(*parts):
    """历史名字：等价 asset_path（既有调用点与测试按仓库相对路径理解）。"""
    return asset_path(*parts)


def display_path(path, root=None):
    """绝对路径 → posix 风格相对路径（M5 脱敏第③步：本机路径不入产物）。

    相对路径原样返回；绝对路径依次尝试相对 ``root``、仓库根、可写根，
    都不在则原样返回 str(path)（如测试临时目录、用户上传的本地文件）。
    """
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        resolved = p.resolve()
    except OSError:
        return str(path)
    candidates = []
    if root is not None:
        candidates.append(Path(root).resolve())
    candidates.extend([ROOT.resolve(), out_root().resolve()])
    for base in candidates:
        try:
            return resolved.relative_to(base).as_posix()
        except ValueError:
            continue
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
    cfg_path = asset_path("config", "settings.json")
    file_cfg = load_json(cfg_path, default={}) if cfg_path.exists() else {}
    llm_cfg = load_json(asset_path("config", "settings.example.json"), default={}).get("llm", {})
    llm_cfg.update(file_cfg.get("llm", {}))
    return {
        "disable_llm": disable_llm,
        "llm": llm_cfg,
    }


def knowledge_paths():
    return {
        "hazard_types": asset_path("data", "knowledge", "seed", "hazard_types.json"),
        "measures": asset_path("data", "knowledge", "seed", "measures.json"),
        "regulations": asset_path("data", "knowledge", "regulations", "seed_regulations.jsonl"),
        "thresholds": asset_path("data", "knowledge", "thresholds", "seed_thresholds.json"),
        "rules": asset_path("data", "knowledge", "rules", "rules_v1.json"),
        "cases": asset_path("data", "knowledge", "cases", "cases.jsonl"),
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
