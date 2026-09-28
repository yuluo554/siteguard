# -*- coding: utf-8 -*-
"""生成 .docx 演示样例：由已生成的 .txt 样例做格式转换（台账纪律 plan/04：样例一律程序生成，禁止手改）。

本脚本只做 txt→docx 格式转换，不改动任何记录内容；
依赖 python-docx（可选依赖，pyproject doc 组），未安装时给出安装提示。
用法：py -X utf8 -m scripts.make_docx_sample
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def txt_to_docx(txt_path, docx_path):
    """把单个 .txt 巡查记录转成 .docx（逐行成段）。缺依赖返回错误码 1 并提示安装。"""
    try:
        import docx  # python-docx（可选依赖）
    except ImportError:
        print("缺少可选依赖 python-docx：py -X utf8 -m pip install python-docx", file=sys.stderr)
        return 1
    text = Path(txt_path).read_text(encoding="utf-8")
    document = docx.Document()
    for line in text.splitlines():
        if line.strip():
            document.add_paragraph(line.strip())
    document.save(str(docx_path))
    print("生成:", docx_path)
    return 0


def main():
    src_dir = ROOT / "data" / "samples" / "text"
    if not src_dir.exists():
        print("样例目录不存在: %s（先运行 py -X utf8 -m siteguard.cli datagen）" % src_dir,
              file=sys.stderr)
        return 1
    made = 0
    for txt in sorted(src_dir.glob("*.txt")):
        rc = txt_to_docx(txt, txt.with_suffix(".docx"))
        if rc:
            return rc
        made += 1
    print("共生成 %d 个 docx 样例" % made)
    return 0


if __name__ == "__main__":
    sys.exit(main())
