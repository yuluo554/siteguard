# -*- coding: utf-8 -*-
"""装态（非 editable pip 安装）契约守门（v0.1.1 新增，对应 DEC2=B 引发的 D8）。

背景：v0.1.1 决定给 Release 附 sdist + wheel（DEC2=B）。实测发现一个问题：
`pyproject.toml` 只声明了 `packages`，仓库根的 `data/`、`webapp/`、`config/`
**一个都进不了 wheel** —— 装出来的包能 `import`，`/api/health` 也活着，但：

    $ siteguard eval
    FileNotFoundError: 配置/数据文件不存在: .../site-packages/data/knowledge/seed/hazard_types.json
    $ GET /           ← Web 面板首页
    500 File at path .../site-packages/webapp/index.html does not exist

也就是"装完不能用"——比装不上更坑，因为看起来像装成功了。

修复：`[tool.setuptools.data-files]` 把三样东西装到 `<prefix>/share/siteguard/`，
`config.share_root()` / `asset_path()` 在装态回落查找；产物（`examples/`）改落
`<cwd>`，不写 site-packages。

本测试是**静态契约**（不需要真装一次，快、可进常规 CI）：
断言 pyproject 的 data-files 覆盖了源码实际需要的每一个资产文件。
真正的端到端验证在 CI 的 packaging 步骤里（真 pip install 非 editable + 跑 CLI）。

自指纪律：新增/删除随包资产时，data-files 必须同步，否则本测试红。
"""
import sys
import unittest
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover
    _toml = None

from siteguard import config

REPO = config.repo_path()


def _data_files():
    if _toml is None:  # pragma: no cover
        raise unittest.SkipTest("需要 Python 3.11+ 的 tomllib")
    with open(REPO / "pyproject.toml", "rb") as f:
        return _toml.load(f).get("tool", {}).get("setuptools", {}).get("data-files", {})


def _declared_targets():
    """data-files 里声明的**实际文件**（把 glob 模式按仓库展开，用相对 posix 路径比对）。

    只比文件名不够：``data/samples/text/*.txt`` 这类模式必须真展开，
    否则"声明了通配但一个文件都没匹配上"会被误判成已覆盖。
    """
    declared = set()
    for _dest, patterns in _data_files().items():
        for pattern in patterns:
            for p in REPO.glob(pattern):
                if p.is_file():
                    declared.add(p.relative_to(REPO).as_posix())
    return declared


def _undeclared(files):
    declared = _declared_targets()
    return [p.relative_to(REPO).as_posix() for p in files
            if p.is_file() and p.relative_to(REPO).as_posix() not in declared]


class TestInstalledAssetsContract(unittest.TestCase):
    """仓库根资产必须全部被 data-files 声明（否则装态装不到）。"""

    def test_knowledge_files_declared(self):
        files = [p for p in (REPO / "data" / "knowledge").rglob("*") if p.is_file()]
        self.assertEqual(_undeclared(files), [],
                         "data/knowledge 下有文件未被 data-files 声明")

    def test_samples_and_gold_declared(self):
        files = []
        for sub in (("data", "samples", "text"), ("data", "samples", "images"),
                    ("data", "eval", "gold"), ("data", "eval", "cases")):
            files.extend(p for p in REPO.joinpath(*sub).glob("*") if p.is_file())
        self.assertEqual(_undeclared(files), [],
                         "样例/真值/配对语料有文件未被 data-files 声明")

    def test_webapp_and_config_declared(self):
        files = []
        for sub in ("webapp", "config"):
            files.extend(p for p in (REPO / sub).glob("*") if p.is_file())
        self.assertEqual(_undeclared(files), [],
                         "webapp/config 有文件未被 data-files 声明")

    def test_declared_paths_exist(self):
        """data-files 里写的模式不能是死规则（指向不存在的文件）。"""
        dead = []
        for _dest, patterns in _data_files().items():
            for pattern in patterns:
                if not list(REPO.glob(pattern)):
                    dead.append(pattern)
        self.assertEqual(dead, [], "data-files 含指向不存在文件的死规则: %s" % dead)


class TestPathLayering(unittest.TestCase):
    """config 的路径分层：资产用 asset_path，产物用 out_path，两者不可混用。"""

    def test_asset_paths_resolve_in_source_layout(self):
        # 源码态：资产就在仓库里
        self.assertTrue(config.asset_path("data", "knowledge", "seed",
                                          "hazard_types.json").is_file())
        self.assertTrue(config.asset_path("webapp", "index.html").is_file())
        self.assertTrue(config.asset_path("config", "settings.example.json").is_file())

    def test_out_path_is_separate_from_site_packages(self):
        """产物路径绝不能落在 site-packages（装态不可写、且会污染已安装包）。"""
        out = config.out_path("examples", "eval_report.json")
        self.assertNotIn("site-packages", str(out).replace("\\", "/"))
        self.assertNotIn("share/siteguard", str(out).replace("\\", "/"))

    def test_repo_path_alias_keeps_asset_semantics(self):
        """repo_path 是历史别名，必须与 asset_path 等价（既有调用点依赖这点）。"""
        self.assertEqual(config.repo_path("data", "knowledge"),
                         config.asset_path("data", "knowledge"))


if __name__ == "__main__":
    unittest.main()
