# -*- coding: utf-8 -*-
"""CI 核心腿门禁：只装核心（``pip install -e .``）时的失败必须**全部**是
"缺某个 optional 依赖" 这一类，且归因由**环境探测**给出，不靠异常文本。

为什么要这个门（v0.1.1 D1 的教训）：
- 本仓核心是真零依赖，但 ``tests/`` 里有一部分用例天然需要 optional 组
  （docx / fastapi / pyvis）。只装核心时它们必然失败——这是**设计如此**，不是缺陷；
- 但如果对这些失败视而不见（或者干脆把整套测试在核心腿里跳过），
  D1 那种"声明漏项 / 装法不完整"的问题就再也没人会发现。
  所以核心腿的口径是：**失败必须在允许清单内，出现一条清单外的失败就红**。

归因方式（关键设计）：允许清单只声明"这条用例需要哪个模块"，
门自己用 ``importlib.util.find_spec`` 核实「该模块在本环境确实不存在」。
- 模块确实缺失 → 归因为 optional 依赖，放行；
- 模块**装好了**用例仍然失败 → 这是真缺陷（不是缺依赖），必须红；
- 用例不在清单里 → 必须红（新增用例请先归因再入清单）。
这样清单无法被"字符串匹配巧合"糊过去，也不会因为断言文案改动而失效。

用法：
    python -m scripts.ci_core_only_gate                       # 门（exit 0 = 通过）
    python -m scripts.ci_core_only_gate --selftest            # 正控：注入清单外失败，必须 exit 1
    python -m scripts.ci_core_only_gate --assert-core-only-env # 断言环境里没有 optional 依赖
"""
import argparse
import importlib.util
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 核心装法下**不许**出现在 site-packages 的包（发行名小写）。
# 核心零依赖是 README 第一卖点；这份清单也是"装法是否真的只用核心"的判据。
OPTIONAL_DISTS = (
    "requests", "python-docx", "networkx", "pyvis", "fastapi", "uvicorn",
    "httpx", "python-multipart", "ultralytics", "opencv-python",
)

# 用例 id → (所需模块, 归因说明)
# 只装核心时这些用例会失败，且**仅当**所需模块确实缺失才允许通过。
ALLOWED = {
    "tests.test_m2.TestDocxParse.test_docx_sample_roundtrip": (
        ["docx"], "缺 doc extra（python-docx）：docx 解析降级为 warning"),
    "tests.test_m3.TestBuildKgCli.test_cli_build_kg_outputs_three_artifacts": (
        ["pyvis"], "缺 kg extra（pyvis）：kg.html 降级为 JSON 导出"),
    "tests.test_m5.TestExportDocx.test_docx_no_external_image_links": (
        ["docx"], "缺 doc extra（python-docx）"),
    "tests.test_m5.TestExportDocx.test_docx_with_signature_block": (
        ["docx"], "缺 doc extra（python-docx）"),
    "tests.test_m5.TestServeCore.test_analyze_input_two_scenarios": (
        ["docx"], "缺 doc extra：面板的 Word 下载降级为不可用（其余格式不受影响）"),
    "setUpClass (tests.test_m5.TestServeHTTP)": (
        ["fastapi"], "缺 web extra（fastapi）：HTTP 层整组用例需要 TestClient"),
}

# setUpClass 汇总错误在 id 里带空格前缀，统一归一成上面那种写法
def _normalize(test_id):
    return test_id.strip()


# 只装核心时预期被 skip 的模块（pyvis/docx 相关的 skipUnless 分支）
EXPECTED_SKIP_PREFIXES = ("tests.test_m3.", "tests.test_m6.")


class CollectingResult(unittest.TextTestResult):
    """收集 (kind, 用例 id, 异常尾行) 供归因，其余行为与 TextTestResult 一致。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.problems = []
        self.skipped_ids = []

    def _record(self, kind, test, err):
        tail = ""
        if err is not None:
            text = "".join(__import__("traceback").format_exception(*err)).strip()
            tail = (text.splitlines() or [""])[-1][:300]
        test_id = _normalize(test.id() if hasattr(test, "id") else str(test))
        self.problems.append((kind, test_id, tail))

    def addError(self, test, err):
        self._record("error", test, err)
        super().addError(test, err)

    def addFailure(self, test, err):
        self._record("failure", test, err)
        super().addFailure(test, err)

    def addSkip(self, test, reason):
        self.skipped_ids.append(_normalize(test.id() if hasattr(test, "id") else str(test)))
        super().addSkip(test, reason)


def _missing(module):
    """模块是否真的不可导入（True = 确实缺失）。"""
    try:
        return importlib.util.find_spec(module) is None
    except (ImportError, ValueError):
        return True


def classify(test_id):
    """返回 (attributed: bool, 说明)。归因依据是"所需模块确实缺失"。"""
    entry = ALLOWED.get(test_id)
    if entry is None:
        return False, "用例不在允许清单内（新增用例请先归因再入清单）"
    modules, reason = entry
    installed = [m for m in modules if not _missing(m)]
    if installed:
        return False, ("所需模块 %s 实际已安装，用例仍失败 ⇒ 这是真缺陷，不是缺依赖"
                       % "/".join(installed))
    return True, reason


def run_gate(extra_unexpected=False):
    suite = unittest.TestLoader().discover(str(REPO / "tests"), top_level_dir=str(REPO))
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=0,
                                     resultclass=CollectingResult)
    result = runner.run(suite)

    attributed, unattributed = [], []
    for kind, test_id, tail in result.problems:
        ok, reason = classify(test_id)
        item = {"kind": kind, "test": test_id, "detail": reason}
        if ok:
            attributed.append(item)
        else:
            item["tail"] = tail
            unattributed.append(item)

    bad_skips = [s for s in result.skipped_ids
                 if not s.startswith(EXPECTED_SKIP_PREFIXES)]

    if extra_unexpected:
        unattributed.append({"kind": "failure", "test": "selftest.injected",
                             "detail": "SelftestInjectedFailure 清单外失败（正控）",
                             "tail": "SelftestInjectedFailure"})

    ok = not unattributed and not bad_skips
    report = {
        "ran": result.testsRun,
        "problems": len(result.problems),
        "attributed": attributed,
        "unattributed": unattributed,
        "skipped": result.skipped_ids,
        "unexpected_skips": bad_skips,
        "ok": ok,
    }
    return ok, report


def assert_core_only_env():
    """核心装法断言：site-packages 里不得出现任何 optional 依赖 + 各模块确实不可导入。

    返回 0 通过 / 1 失败。两个判据互为交叉验证：
    - pip list 看得见发行名（防止"装了个同名残留目录"漏判）；
    - find_spec 看得见导入路径（防止 pip 元数据缺失但模块可导入）。
    """
    out = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"],
                         capture_output=True, text=True).stdout.lower()
    present = []
    for dist in OPTIONAL_DISTS:
        if re.search(r"^%s==" % re.escape(dist), out, re.M):
            present.append(dist)
    importable = []
    for module in ("requests", "docx", "networkx", "pyvis", "fastapi", "uvicorn",
                   "httpx", "multipart", "ultralytics", "cv2"):
        if not _missing(module):
            importable.append(module)
    report = {"pip_list_hits": present, "importable": importable,
              "ok": not present and not importable}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        print("CORE_ONLY_ENV_FAIL 核心装法里出现了 optional 依赖（零依赖卖点被破坏）")
        return 1
    print("CORE_ONLY_ENV_OK 核心装法下无任何 optional 依赖")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="核心腿门禁：失败必须全部可归因到确实缺失的 optional 依赖")
    parser.add_argument("--selftest", action="store_true",
                        help="正控：注入一条清单外失败，门必须 exit 1")
    parser.add_argument("--assert-core-only-env", action="store_true",
                        help="断言当前环境是纯核心装法（无任何 optional 依赖）")
    args = parser.parse_args(argv)

    if args.assert_core_only_env:
        return assert_core_only_env()

    ok, report = run_gate(extra_unexpected=args.selftest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.selftest:
        if ok:
            print("SELFTEST_FAIL 门未能识别清单外失败（门本身失效）")
            return 1
        print("SELFTEST_OK 门正确识别清单外失败")
        return 0
    if ok:
        print("CORE_ONLY_GATE_OK 核心腿失败 %d 条全部可归因到确实缺失的 optional 依赖"
              % len(report["attributed"]))
        return 0
    print("CORE_ONLY_GATE_FAIL 存在不可归因的失败或非预期跳过")
    return 1


if __name__ == "__main__":
    sys.exit(main())
