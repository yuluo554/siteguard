# -*- coding: utf-8 -*-
"""optional-dependencies 契约守门（v0.1.1 新增，对应 D1）。

背景：`web` extra 曾漏声明 `python-multipart`，而 `siteguard/serverapp.py` 的
`/api/analyze` 用了 `fastapi.File` / `fastapi.Form`——FastAPI 在 `create_app()`
阶段就会抛 `RuntimeError: Form data requires "python-multipart" to be installed`。
照 README 装 `[web]` 的用户会得到一个起不来的 Web 面板，而本仓当时没有 CI
（D2）能在干净环境里暴露它。

本测试是**静态契约**：不联网、不装包，只读 `pyproject.toml` 与源码，
保证"源码里用了什么可选依赖的能力，声明的 extra 就必须能装出什么"。

另含两条自指守门（本仓历史教训：README 的测试计数会随新增测试漂移）：
- README 自述的测试项数必须等于实际可发现（discover）的测试数；
- README 的测试计数行必须带"装齐 extras"前置条件（D3）。
"""
import re
import sys
import unittest
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover - 3.11 以下无 stdlib TOML，用最小解析兜底
    _toml = None

from siteguard import config

REPO = config.repo_path()


def _load_pyproject():
    raw = (REPO / "pyproject.toml").read_bytes()
    if _toml is not None:
        return _toml.loads(raw.decode("utf-8"))
    # 最小兜底：仅解析 [project.optional-dependencies] 段（需 tomli 未装时的退路）
    text = raw.decode("utf-8")
    section = {}
    in_opt = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_opt = stripped == "[project.optional-dependencies]"
            continue
        if in_opt and "=" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition("=")
            section[key.strip()] = re.findall(r'"([^"]+)"', value)
    return {"project": {"optional-dependencies": section}}


def _extra_names(specs):
    """把 ["fastapi>=0.95", ...] 归一成 {"fastapi", ...}（小写、去版本约束）。"""
    names = set()
    for spec in specs:
        name = re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0]
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


class TestWebExtraContract(unittest.TestCase):
    """web extra 必须能装出 serverapp.py 在 import/建 app 阶段就需要的全部依赖。"""

    def setUp(self):
        self.pyproject = _load_pyproject()
        self.extras = self.pyproject["project"]["optional-dependencies"]
        self.web = _extra_names(self.extras.get("web", []))

    def test_web_extra_declares_required_packages(self):
        # fastapi/uvicorn：serverapp 运行必需；httpx：fastapi.testclient 依赖（测试用）；
        # python-multipart：fastapi.File / fastapi.Form 运行必需（D1 就是漏了它）
        required = {"fastapi", "uvicorn", "httpx", "python-multipart"}
        self.assertTrue(required.issubset(self.web),
                        "web extra 缺: %s（现有: %s）"
                        % (sorted(required - self.web), sorted(self.web)))

    def test_multipart_required_whenever_file_or_form_used(self):
        """源码一旦出现 fastapi.File( / fastapi.Form(，web extra 就必须声明 multipart。"""
        source = (REPO / "siteguard" / "serverapp.py").read_text(encoding="utf-8")
        uses_multipart = ("fastapi.File(" in source) or ("fastapi.Form(" in source)
        if not uses_multipart:
            self.skipTest("serverapp 未使用 fastapi.File/Form，multipart 非必需")
        self.assertIn("python-multipart", self.web,
                      "serverapp.py 用了 fastapi.File/fastapi.Form，但 web extra 未声明 python-multipart")


class TestOtherExtrasConsistency(unittest.TestCase):
    """其余 extra 的自洽性（静态可判的部分；运行期由 CI 的装法矩阵覆盖）。"""

    def setUp(self):
        self.extras = _load_pyproject()["project"]["optional-dependencies"]

    def test_every_declared_extra_has_content(self):
        for name, specs in self.extras.items():
            self.assertTrue(specs, "extra %s 声明为空" % name)

    def test_all_extra_specs_are_lowercase_normalized(self):
        for name, specs in self.extras.items():
            for pkg in _extra_names(specs):
                self.assertEqual(pkg, pkg.lower(), "extra %s 含非规范包名: %s" % (name, pkg))

    def test_requires_python_floor_is_modern(self):
        """floor 与代码/依赖口径一致（v0.1.1 决策：>=3.12，见 plan/RELEASE-0.1.1.md）。"""
        floor = str(self.pyproject_floor())
        self.assertRegex(floor, r"^>=3\.(1[2-9]|[2-9]\d)$",
                         "requires-python 应 >=3.12，实际: %s" % floor)

    def pyproject_floor(self):
        return _load_pyproject()["project"]["requires-python"]


class TestReadmeTestCountSelfConsistency(unittest.TestCase):
    """README 自述的测试项数必须与实测可发现数一致（防计数漂移）。"""

    @staticmethod
    def _discovered_count():
        loader = unittest.TestLoader()
        suite = loader.discover(str(REPO / "tests"), top_level_dir=str(REPO))

        def count(item):
            if isinstance(item, unittest.TestSuite):
                return sum(count(x) for x in item)
            return 1

        return count(suite)

    def test_readme_count_matches_discovered(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        line = next((ln for ln in readme.splitlines()
                     if "单元/集成测试" in ln and "项全绿" in ln), None)
        self.assertIsNotNone(line, "README 找不到「单元/集成测试 … 项全绿」行")
        claimed = int(re.search(r"(\d+)\s*项全绿", line).group(1))
        self.assertEqual(claimed, self._discovered_count(),
                         "README 自述 %d 项，实测可发现 %d 项（新增/删除测试后请同步 README）"
                         % (claimed, self._discovered_count()))

    def test_readme_count_line_states_extras_precondition(self):
        """D3：全绿项数是有前提的（要装齐可选依赖），README 必须写明。"""
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        line = next((ln for ln in readme.splitlines()
                     if "单元/集成测试" in ln and "项全绿" in ln), None)
        self.assertIsNotNone(line)
        # 接受两种等价写法：「装齐 .[llm,doc,kg,web]」或「装齐 extras」
        self.assertRegex(line, r"装齐[^|]*(\[|extras)",
                         "README 测试计数行须写明「装齐 .[...] / 装齐 extras」前置条件: %s" % line)


if __name__ == "__main__":
    unittest.main()
