# -*- coding: utf-8 -*-
"""脱敏四步审查（M5，程序化、可重跑；plan/00 验收门第 6 条）。

四步（程序化审查）：
① 密钥扫描：跟踪文件中的密钥字面量模式（sk- 长串 / Bearer 长串 / api_key=、
   password= 等赋值形态）；.env 与 config/settings.json 必须不在 git 跟踪列表。
② 个人信息扫描：手机号（1[3-9] 开头 11 位）、身份证号（18 位）正则全量扫描。
③ 个人路径扫描：盘符路径（C:\\Users、其他盘符 + 仓库本机目录）、/Users/、
   AppData、本地临时目录等本机路径模式；报告类产物必须是仓库相对路径。
④ 二进制内容扫描：跟踪的二进制文件必须全部在台账登记白名单内（SHWD 抽样
   2 张 + docx 程序生成样例 2 个），抽样图的 sha256 与 data/README.md 台账
   登记值比对一致。

结果：逐步 PASS/FAIL，全部通过打印 DESSENSITIZE_AUDIT_OK 并 exit 0；
任一 FAIL 打印 DESSENSITIZE_AUDIT_FAIL 与明细并 exit 1（留痕方式见
data/README.md"脱敏四步审查记录（M5）"）。
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 本脚本自身含模式字符串，自引用不参扫；tests/test_m5.py 的断言字面量同为
# 模式串自引用（非真实路径），两者均白名单留痕。
SKIP_FILES = {"scripts/desensitize_audit.py", "tests/test_m5.py"}

# ④ 跟踪二进制白名单：文件 → 台账登记 sha256（None = 程序生成样例，重算登记）。
# docx 样例当前不入仓（需要时由 scripts.make_docx_sample 程序生成，台账留痕）；
# docs/技术方案.docx 为 M6 提交材料固化物（scripts.tech_doc_to_docx 程序化生成，
# 重新生成后须同步更新此处与 data/README.md 台账的 sha256）。
BINARY_WHITELIST = {
    "data/samples/images/shwd_3.jpg":
        "7ee8627c844213fc785d09828c969181b2d84ee266c138735a8109629902e4fc",
    "data/samples/images/shwd_5.jpg":
        "2b867f3d132d23f7df9d3e8612132795f40eaf5f9c7d5f16e867680a5a35abea",
    "docs/技术方案.docx":
        "fd83f1f9c16a4fd2d27f7b17444d020c18ef6c45548cd0637528b2cad6e45254",
}

# ① 密钥模式（赋值形态要求引号内长字面量，避免命中 api_key_env 等变量名/环境变量引用）
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "sk- 开头密钥字面量"),
    (re.compile(r"Bearer [A-Za-z0-9\-_.]{20,}"), "Bearer 长令牌字面量"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|passwd)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
     "密钥赋值字面量"),
]
MUST_NOT_TRACK = (".env", "config/settings.json")

# ② 个人信息模式（前视排除小数点上下文：排除内嵌库代码中 0.0027… 类数值字面量误报）
PII_PATTERNS = [
    (re.compile(r"(?<![\d.])1[3-9]\d{9}(?!\d)"), "手机号"),
    (re.compile(r"(?<![\d.])\d{17}[\dXx](?!\d)"), "身份证号"),
]

# ③ 本机路径模式（模式串拼接书写，避免本脚本自匹配）
PATH_PATTERNS = [
    (re.compile("[A-Za-z]:" + r"\\Users\\", re.I), "盘符 Users 目录"),
    (re.compile("[A-Za-z]:" + r"\\Windows\\"), "盘符 Windows 目录"),
    (re.compile("/Users/(?!_)"), "POSIX Users 目录"),
    (re.compile("AppData", re.I), "AppData 目录"),
    (re.compile("ProgramData"), "ProgramData 目录"),
    (re.compile("Users" + r"\\ASUS"), "本机用户目录"),
]


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def is_binary(data):
    return b"\0" in data


def main():
    files = [f for f in tracked_files() if f.replace("\\", "/") not in SKIP_FILES]
    problems = {k: [] for k in ("①密钥", "②个人信息", "③个人路径", "④二进制")}

    for f in MUST_NOT_TRACK:
        hits = [x for x in tracked_files() if x.replace("\\", "/") == f]
        if hits:
            problems["①密钥"].append("跟踪列表出现禁入文件: %s" + f)

    for rel in files:
        p = REPO / rel
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            if rel.replace("\\", "/") not in BINARY_WHITELIST:
                problems["④二进制"].append("白名单外的二进制文件: %s" % rel)
            continue
        text = data.decode("utf-8", errors="replace")
        for pat, label in SECRET_PATTERNS:
            m = pat.search(text)
            if m:
                problems["①密钥"].append("%s: %s 命中[%s] 上下文: %r"
                                          % (rel, label, m.group(0)[:6], text[max(0, m.start() - 30):m.end() + 10][:60]))
        for pat, label in PII_PATTERNS:
            for m in pat.finditer(text):
                problems["②个人信息"].append("%s: 疑似%s: %s…" % (rel, label, m.group(0)[:6]))
        for pat, label in PATH_PATTERNS:
            for m in pat.finditer(text):
                problems["③个人路径"].append(
                    "%s: 命中[%s] 上下文: %r" % (rel, label, text[max(0, m.start() - 20):m.end() + 20][:60]))

    # ④ 白名单内文件哈希比对
    for rel, expect in sorted(BINARY_WHITELIST.items()):
        p = REPO / rel
        if not p.exists():
            problems["④二进制"].append("白名单文件缺失: %s" % rel)
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if expect is not None and digest != expect:
            problems["④二进制"].append("sha256 与台账不符: %s（实际 %s…）" % (rel, digest[:16]))
        else:
            print("④ 哈希一致: %s sha256=%s" % (rel, digest))

    for step in ("①密钥", "②个人信息", "③个人路径", "④二进制"):
        if problems[step]:
            print("%s: FAIL（%d 处）" % (step, len(problems[step])))
            for x in problems[step][:20]:
                print("   - %s" % x)
        else:
            print("%s: PASS" % step)

    if any(problems.values()):
        print("DESENSITIZE_AUDIT_FAIL")
        return 1
    print("DESENSITIZE_AUDIT_OK 四步审查全部通过（跟踪文件 %d 个，跳过自引用 %s）"
          % (len(files), ",".join(sorted(SKIP_FILES))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
