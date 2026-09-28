"""text_clean 单元测试：伪空格/零宽字符/CRLF 清洗是规则通路正确性的前提。"""

import unittest

from siteguard.ingest.parsers import clean_text, parse_lines


class TestCleanText(unittest.TestCase):
    def test_removes_pseudo_space_between_cjk(self):
        # PDF/CAD 导出常见：中文间逐字符伪空格
        self.assertEqual(clean_text("临边 未设置 防护栏杆"), "临边未设置防护栏杆")

    def test_removes_zero_width_and_bom(self):
        self.assertEqual(clean_text("\ufeff临边\u200b未设置"), "临边未设置")

    def test_crlf_normalized_and_blank_dropped(self):
        self.assertEqual(clean_text("a\r\n\r\nb\rc"), "a\nb\nc")

    def test_fullwidth_space_between_cjk_removed(self):
        # 全角空格夹在中文字符之间与半角伪空格同源，一并清除
        self.assertEqual(clean_text("临边\u3000未设置"), "临边未设置")


class TestParseLines(unittest.TestCase):
    def test_record_line(self):
        recs = parse_lines("[2026-09-21 10:12] 3#楼3层临边未设置防护栏杆")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["index"], 1)
        self.assertEqual(recs[0]["timestamp"], "2026-09-21 10:12")
        self.assertEqual(recs[0]["text"], "3#楼3层临边未设置防护栏杆")

    def test_header_and_blank_skipped(self):
        text = "项目：样例工程\n\n[2026-09-21 08:30] 隐患甲\n[2026-09-21 08:53] 隐患乙\n"
        recs = parse_lines(clean_text(text))
        self.assertEqual([r["index"] for r in recs], [1, 2])
        self.assertEqual(recs[1]["text"], "隐患乙")

    def test_no_record(self):
        self.assertEqual(parse_lines("没有任何记录行"), [])


class TestTimestampTolerance(unittest.TestCase):
    """M1：时间戳格式容错，统一规范化为 YYYY-MM-DD HH:MM。"""

    def test_slash_and_dot_separators(self):
        for ts in ("2026/09/21 08:30", "2026.09.21 08:30"):
            recs = parse_lines("[%s] 隐患甲" % ts)
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["timestamp"], "2026-09-21 08:30")

    def test_chinese_date_and_single_digit_time(self):
        recs = parse_lines("[2026年9月21日 8:30] 隐患甲")
        self.assertEqual(recs[0]["timestamp"], "2026-09-21 08:30")

    def test_chinese_full_time(self):
        recs = parse_lines("[2026年09月21日08时30分] 隐患甲")
        self.assertEqual(recs[0]["timestamp"], "2026-09-21 08:30")

    def test_seconds_are_dropped(self):
        recs = parse_lines("[2026-09-21 08:30:45] 隐患甲")
        self.assertEqual(recs[0]["timestamp"], "2026-09-21 08:30")

    def test_date_only(self):
        recs = parse_lines("[2026-09-21] 隐患甲")
        self.assertEqual(recs[0]["timestamp"], "2026-09-21")


class TestMultiLineMerge(unittest.TestCase):
    """M1：同一记录跨行时按邻近合并，注释/表头不参与合并。"""

    def test_continuation_merged_into_previous_record(self):
        text = ("[2026-09-21 08:30] 3#楼12层楼层临边未设置\n"
                "    防护栏杆，共2处\n"
                "[2026-09-21 08:53] 现场安全巡查总体受控。")
        recs = parse_lines(clean_text(text))
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["text"], "3#楼12层楼层临边未设置防护栏杆，共2处")
        self.assertEqual([r["index"] for r in recs], [1, 2])

    def test_header_and_note_not_merged(self):
        text = "项目：样例工程\n[2026-09-21 08:30] 隐患甲\n备注：次日复查"
        recs = parse_lines(clean_text(text))
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["text"], "隐患甲")

    def test_ascii_word_boundary_joins_with_space(self):
        text = "[2026-09-21 08:30] 检查 TN-S\n    system 布线"
        recs = parse_lines(clean_text(text))
        self.assertEqual(recs[0]["text"], "检查 TN-S system 布线")


if __name__ == "__main__":
    unittest.main()
