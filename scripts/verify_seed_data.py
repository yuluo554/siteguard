# -*- coding: utf-8 -*-
"""种子数据完整性校验（M2 台账纪律的工具化）。

校验项：
1. 全部 JSON/JSONL 可解析；
2. 词表 measure_ids ⊆ 措施库；clause_refs ⊆ 条文库（含勘误后条款号）；
3. 规则库：major_patterns/severity_words 与 risk_level 模块常量一致（迁移完整性）、
   overrides 的 std_id+clause ⊆ 条文库、threshold_rules 的 threshold_id ⊆ 阈值表、
   base_rules 的 hazard_type_id ⊆ 词表、rule_id 与词表 id 派生一致；
4. 全部 patterns 可编译为正则（防运行期炸裂）；
5. 案例 hazard_type_ids/measure_ids 引用可解析。

用法：py -X utf8 -m scripts.verify_seed_data  （退出码 0=全绿）
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K = ROOT / "data" / "knowledge"

errors = []
warns = []


def err(msg):
    errors.append(msg)


def load_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        err("%s JSON解析失败: %s" % (p.name, exc))
        return None


def load_jsonl(p):
    items = []
    try:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception as exc:
                err("%s 第%d行解析失败: %s" % (p.name, i, exc))
    except Exception as exc:
        err("%s 读取失败: %s" % (p.name, exc))
    return items


def compile_ok(pats, where):
    for p in pats:
        try:
            re.compile(p)
        except re.error as exc:
            err("%s 正则不可编译 %r: %s" % (where, p, exc))


def main():
    # ---- 词表 ----
    ht = load_json(K / "seed" / "hazard_types.json") or {}
    types = ht.get("hazard_types", [])
    type_ids = {t.get("id") for t in types}
    print("词表类型数:", len(types), "类别数:", len(ht.get("categories", [])))

    # ---- 条文/措施/阈值/规则/案例 ----
    regs = load_jsonl(K / "regulations" / "seed_regulations.jsonl")
    reg_keys = {(r.get("std_id"), r.get("clause")) for r in regs}
    print("条文数:", len(regs))
    dup = len(regs) - len(reg_keys)
    if dup:
        err("条文 (std_id,clause) 重复 %d 处" % dup)

    ms = load_json(K / "seed" / "measures.json") or {}
    measures = ms.get("measures", [])
    measure_ids = {m.get("id") for m in measures}
    if len(measure_ids) != len(measures):
        err("措施 id 重复")
    print("措施数:", len(measures))

    th = load_json(K / "thresholds" / "seed_thresholds.json") or {}
    thresholds = th.get("thresholds", [])
    threshold_ids = {t.get("id") for t in thresholds}
    if len(threshold_ids) != len(thresholds):
        err("阈值 id 重复")
    print("阈值数:", len(thresholds))

    rules = load_json(K / "rules" / "rules_v1.json") or {}
    cases = load_jsonl(K / "cases" / "cases.jsonl")
    case_ids = {c.get("case_id") for c in cases}
    if len(case_ids) != len(cases):
        err("案例 case_id 重复")
    print("案例数:", len(cases))

    # ---- 词表交叉引用 + 正则可编译 ----
    for t in types:
        tid = t.get("id", "?")
        if not t.get("patterns"):
            err("%s 缺 patterns" % tid)
        compile_ok(t.get("patterns", []), tid)
        for mid in t.get("measure_ids", []):
            if mid not in measure_ids:
                err("%s 引用不存在的措施 %s" % (tid, mid))
        for ref in t.get("clause_refs", []):
            key = (ref.get("standard"), ref.get("clause"))
            if key not in reg_keys:
                err("%s 引用不存在的条文 %s#%s" % (tid, key[0], key[1]))

    # ---- 规则库一致性 ----
    sys.path.insert(0, str(ROOT))
    from siteguard.reasoning import risk_level as rl

    mp = rules.get("major_patterns", [])
    sw = rules.get("severity_words", [])
    if mp != rl.MAJOR_PATTERNS:
        err("major_patterns 与 risk_level.MAJOR_PATTERNS 不一致（迁移不完整）")
    if sw != rl.SEVERITY_WORDS:
        err("severity_words 与 risk_level.SEVERITY_WORDS 不一致（迁移不完整）")

    for ov in rules.get("overrides", []):
        compile_ok(ov.get("match", {}).get("any_of", []), ov.get("override_id", "?"))
        key = (ov.get("std_id"), ov.get("clause"))
        if key not in reg_keys:
            err("override %s 引用不存在的条文 %s#%s" % (ov.get("override_id"), key[0], key[1]))
        if ov.get("level") not in ("重大风险",):
            err("override %s level 异常: %s" % (ov.get("override_id"), ov.get("level")))

    for tr in rules.get("threshold_rules", []):
        if tr.get("threshold_id") not in threshold_ids:
            err("threshold_rule %s 引用不存在的阈值 %s" % (tr.get("rule_id"), tr.get("threshold_id")))
        for tid in tr.get("hazard_type_ids", []):
            if tid not in type_ids:
                err("threshold_rule %s 引用不存在的类型 %s" % (tr.get("rule_id"), tid))

    for br in rules.get("base_rules", []):
        hid = br.get("hazard_type_id")
        if hid not in type_ids:
            err("base_rule %s 引用不存在的类型 %s" % (br.get("rule_id"), hid))
            continue
        expect = "RL-" + hid.replace("HT-", "")
        if br.get("rule_id") != expect:
            err("base_rule rule_id 与词表派生不一致: %s != %s" % (br.get("rule_id"), expect))
        ht_def = next(t for t in types if t.get("id") == hid)
        if br.get("base_level") != ht_def.get("base_level"):
            err("base_rule %s base_level 与词表不一致" % br.get("rule_id"))

    # ---- 案例交叉引用 ----
    for c in cases:
        cid = c.get("case_id", "?")
        for tid in c.get("hazard_type_ids", []):
            if tid not in type_ids:
                err("%s 引用不存在的隐患类型 %s" % (cid, tid))
        for mid in c.get("measure_ids", []):
            if mid not in measure_ids:
                err("%s 引用不存在的措施 %s" % (cid, mid))

    # ---- 汇总 ----
    print("-" * 46)
    if warns:
        for w in warns:
            print("WARN:", w)
    if errors:
        for e in errors:
            print("ERR:", e)
        print("校验失败：%d 项错误" % len(errors))
        return 1
    print("校验通过：全部种子数据可解析、交叉引用完整、正则可编译")
    return 0


if __name__ == "__main__":
    sys.exit(main())
