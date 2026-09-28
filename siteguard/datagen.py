"""程序化样例生成器 v2：随机生成带真值（gold）的巡查记录/施工日志语料。

纪律（plan/04 §3）：
- 样例与真值由同一生成器产出（确定性 seed），评测只信生成器真值；
- 样例文件禁止手改，改动需求改模板后重新生成；
- 生成句式必须与 hazard_types.json 的 patterns 配套演进（改任一侧必须重跑评测）；
- 生成期自检：隐患记录必须恰好命中自身类型、正常记录零命中、site_object 标注
  必须与词表一致、全语料禁止严重词与重大隐患词形——模板与词表失配直接报错。

M1 v2 变更：
- 两大场景各 ≥50 条隐患记录（round_count=9，每类 6 变体轮转覆盖）；
- 每类隐患 6 种口语化变体（句式/部位/时间/量词变化）；
- gold 增加 site_object 字段（字段级评测真值），标记 corpus=v2；
- 部分隐患拆成两行，检验解析器多行合并；时间戳 4 种表面格式轮转，检验容错；
- 新增配对语料：同项目"施工日志版 vs 巡查记录版"双文件，巡查版注入已知差异
  （漏项 missing / 数值不一致 value / 多报 extra），差异清单写入 data/eval/cases/。
"""

import json
import random
import re
from pathlib import Path

from . import config
from .reasoning import risk_level

DEFAULT_SEED = 42
SCENARIOS = {
    "gczy": {"file": "demo_gczy.txt", "title": "高处作业", "category": "高处作业"},
    "lsyd": {"file": "demo_lsyd.txt", "title": "临时用电", "category": "临时用电"},
}
PAIRED = {
    "gczy": {"log": "paired_gczy_log.txt", "patrol": "paired_gczy_patrol.txt",
             "gold": "paired_gczy.diff.json"},
    "lsyd": {"log": "paired_lsyd_log.txt", "patrol": "paired_lsyd_patrol.txt",
             "gold": "paired_lsyd.diff.json"},
}

BUILDINGS = ["1#楼", "2#楼", "3#楼"]
FLOORS = ["3", "5", "8", "12", "15", "18"]
TIME_WORDS = ["今晨", "上午", "下午", "夜间"]
NUMBERS = [2, 3, 4, 5]

# 每类隐患 6 个口语化变体：(模板, site_object 标注)；"" 表示该句无受控部位词。
# 与 hazard_types.json 的 patterns 配套演进；禁止严重词与 MAJOR_PATTERNS 词形。
TEMPLATES = {
    "HT-GCZY-001": [
        ("{b}{f}楼层临边未设置防护栏杆", "楼层临边"),
        ("{t}{b}{f}楼梯间临边未安装防护栏杆", ""),
        ("{b}屋面临边防护栏杆缺失", "屋面临边"),
        ("{b}{f}阳台临边未搭设防护栏杆，共{n}处", "阳台临边"),
        ("{b}{f}临边无防护", ""),
        ("{t}{b}{f}楼梯临边未设置防护栏杆", "楼梯临边"),
    ],
    "HT-GCZY-002": [
        ("{b}{f}外脚手架上作业工人未系安全带", "外脚手架"),
        ("{t}{b}屋面防水作业人员未佩戴安全带", "屋面"),
        ("{b}{f}钢结构作业面焊接工人安全带未系挂", "钢结构作业面"),
        ("{b}{f}外架拆除作业{n}名工人未系安全带", ""),
        ("{t}{b}屋面保温施工人员安全带未挂设", "屋面"),
        ("{b}{f}预留洞口周边支模人员未系安全带", "洞口"),
    ],
    "HT-GCZY-003": [
        ("{b}{f}预留洞口无防护", "预留洞口"),
        ("{b}{f}预留洞口未加盖防护盖板", "预留洞口"),
        ("{b}{f}电梯井口未设置防护", "电梯井口"),
        ("{t}{b}{f}楼梯口无防护", "楼梯口"),
        ("{b}{f}地下室顶板预留洞口未采取防护，共{n}处", "预留洞口"),
        ("{b}{f}管道井洞口无防护盖板", ""),
    ],
    "HT-GCZY-004": [
        ("{b}外脚手架安全网破损", "外脚手架"),
        ("{b}{f}外架未挂设安全网", ""),
        ("{b}{f}楼层临边安全网破损{n}处", "楼层临边"),
        ("{t}{b}卸料平台侧面临边未张挂安全网", ""),
        ("{b}{f}外脚手架安全网破旧未更换", "外脚手架"),
        ("{t}{b}{f}楼层临边安全网缺失", "楼层临边"),
    ],
    "HT-GCZY-005": [
        ("{b}首层安全通道被占用堆放模板", "安全通道"),
        ("{b}{f}安全通道不畅通", "安全通道"),
        ("{b}基坑东侧安全通道堵塞", "安全通道"),
        ("{b}{f}{n}处安全通道未设置", "安全通道"),
        ("{b}地下室安全通道被占用堆放钢管", "安全通道"),
        ("{t}{b}首层通道被占用", "首层通道"),
    ],
    "HT-GCZY-006": [
        ("{b}{f}移动操作平台超载堆放材料", "移动操作平台"),
        ("{b}{f}移动操作平台脚轮未锁", "移动操作平台"),
        ("{t}{b}内装修操作平台未固定", "操作平台"),
        ("{b}{f}移动操作平台超载堆放钢管{n}捆", "移动操作平台"),
        ("{b}{f}操作平台超载", "操作平台"),
        ("{t}{b}{f}移动操作平台作业时未固定", "移动操作平台"),
    ],
    "HT-LSYD-001": [
        ("{b}现场临时用电未落实三级配电", ""),
        ("{b}配电系统未采用TN-S接零保护", ""),
        ("{b}{f}分配电箱回路三级配电两级保护未落实", "分配电箱"),
        ("{t}{b}总配电箱未落实两级保护", "总配电箱"),
        ("{b}生活区用电未执行三级配电要求", ""),
        ("{b}{n}台设备回路未落实两级保护", ""),
    ],
    "HT-LSYD-002": [
        ("{b}钢筋加工棚开关箱一闸多机", "开关箱"),
        ("{b}{f}开关箱接多台设备", "开关箱"),
        ("{t}{b}木工棚一机一闸一漏未落实", ""),
        ("{b}{f}开关箱一闸多机带{n}台设备", "开关箱"),
        ("{b}一个开关箱控制2台电焊机", "开关箱"),
        ("{t}{b}{f}配电箱一闸多机", "配电箱"),
    ],
    "HT-LSYD-003": [
        ("{b}{f}配电箱无门无锁", "配电箱"),
        ("{b}室外配电箱无防雨措施", "配电箱"),
        ("{t}{b}{f}楼梯间开关箱无锁", "开关箱"),
        ("{b}{f}{n}台配电箱无门无锁", "配电箱"),
        ("{b}钢筋棚分配电箱无锁", "分配电箱"),
        ("{t}{b}开关箱无门无锁", "开关箱"),
    ],
    "HT-LSYD-004": [
        ("{b}{f}主干电缆拖地敷设", "主干电缆"),
        ("{b}基坑周边电缆泡水", ""),
        ("{t}{b}生活区私拉乱接电线", ""),
        ("{b}{f}主干电缆拖地敷设约{n}米", "主干电缆"),
        ("{b}{f}楼层电缆老化", ""),
        ("{t}{b}宿舍区电线乱拉乱接", ""),
    ],
    "HT-LSYD-005": [
        ("{b}钢筋棚开关箱漏电保护器失效", "开关箱"),
        ("{b}{f}配电箱漏电保护器参数不合格", "配电箱"),
        ("{t}{b}搅拌机专用箱漏电保护器未检测", ""),
        ("{b}{f}{n}台开关箱漏电保护器不动作", "开关箱"),
        ("{b}{f}配电箱漏电保护器缺失", "配电箱"),
        ("{t}{b}木工棚开关箱漏电保护器未安装", "开关箱"),
    ],
    "HT-LSYD-006": [
        ("{b}{f}发现非电工私接照明线路", ""),
        ("{b}木工棚无证电工接线作业", ""),
        ("{t}{b}现场发现非电工操作配电箱", "配电箱"),
        ("{b}{f}{n}名非电工私接临时线路", ""),
        ("{b}非电工私接钢筋棚配电箱", "配电箱"),
        ("{t}{b}无证人员操作用电设备", "用电设备"),
    ],
}

BENIGN = [
    "现场安全巡查总体受控，未发现新增隐患。",
    "钢筋材料已按平面布置图码放整齐。",
    "今日进行班前安全教育，交底记录已归档。",
    "混凝土浇筑完成，现场文明施工保持良好。",
    "材料进场验收已完成并登记台账。",
    "监理例会布置本周安全检查重点并形成纪要。",
    "天气晴，各班组按计划正常作业。",
    "生活区及办公区卫生检查合格。",
    "消防器材月检记录已更新。",
    "基坑监测数据无异常，位移在控制值内。",
]

HEADER = "项目：样例住宅楼二期工程 安全巡查记录（程序生成样例，非真实项目）"
HEADER_LOG = "项目：样例住宅楼二期工程 施工日志（程序生成样例，非真实项目）"
HEADER_PATROL = "项目：样例住宅楼二期工程 安全巡查记录（程序生成样例，非真实项目）"
PAIRED_DATE = "2026-09-21"


def _render(tpl, slots):
    return tpl.format(**slots)


def _make_slots(rng):
    return {"b": rng.choice(BUILDINGS), "f": rng.choice(FLOORS) + "层",
            "t": rng.choice(TIME_WORDS), "n": rng.choice(NUMBERS)}


def _surface_ts(style, day, minutes):
    """时间戳 4 种表面格式轮转（检验解析器容错）。"""
    hh, mm = minutes // 60 % 24, minutes % 60
    if style == 0:
        return "2026-09-%02d %02d:%02d" % (day, hh, mm)
    if style == 1:
        return "2026/09/%02d %02d:%02d" % (day, hh, mm)
    if style == 2:
        return "2026年09月%02d日 %02d:%02d" % (day, hh, mm)
    return "2026-09-%02d %02d:%02d:%02d" % (day, hh, mm, (day * 7 + mm) % 60)


def _canon_ts(minutes):
    """配对差异 gold 用规范化时间戳（与解析器 normalize_timestamp 口径一致）。"""
    return "%s %02d:%02d" % (PAIRED_DATE, minutes // 60 % 24, minutes % 60)


def _match_ids(text, schema):
    return [ht["id"] for ht in schema["hazard_types"]
            if any(re.search(p, text) for p in ht.get("patterns", []))]


def _self_check(records, schema):
    """生成期自检（plan/04 配套演进纪律）：模板与词表失配立即报错。"""
    for rec in records:
        text = rec["text"]
        for w in risk_level.SEVERITY_WORDS:
            if w in text:
                raise AssertionError("语料含严重词 %r: %r" % (w, text))
        for pat in risk_level.MAJOR_PATTERNS:
            if re.search(pat, text):
                raise AssertionError("语料命中重大隐患词形 %r: %r" % (pat, text))
        hits = _match_ids(text, schema)
        if rec["kind"] == "hazard":
            expected = rec["ht"]["id"]
            if hits != [expected]:
                raise AssertionError("模板/词表失配: %r 命中 %s，期望 [%s]"
                                     % (text, hits, [expected]))
            members = [o for o in rec["ht"].get("site_objects", []) if o in text]
            got = max(members, key=len) if members else ""
            if rec["site_object"] != got:
                raise AssertionError("site_object 标注 %r 与文本命中 %r 不一致: %r"
                                     % (rec["site_object"], got, text))
        elif hits:
            raise AssertionError("正常记录命中隐患规则: %r -> %s" % (text, hits))


def generate_scenario(spec, rng, round_count=9):
    """一个场景的记录列表（dict），正常记录按时间顺序交错。

    演示语料纪律（plan/04 §3）：只生成有口语化模板的类型；新增类别（脚手架/基坑/
    起重/消防/有限空间）词表/规则/条文已支撑研判，但按计划不进演示语料。
    """
    types = [ht for ht in config.load_schema()["hazard_types"]
             if ht["category"] == spec["category"] and ht["id"] in TEMPLATES]
    assert types, "场景 %s 没有受控隐患类型" % spec["category"]
    records = []
    for i in range(round_count * len(types)):
        if i % 4 == 3:
            records.append({"kind": "benign", "text": rng.choice(BENIGN),
                            "ht": None, "site_object": "", "tpl": "", "slots": {}})
        ht = types[i % len(types)]
        variants = TEMPLATES[ht["id"]]
        tpl, site_object = variants[(i // len(types)) % len(variants)]
        slots = _make_slots(rng)
        records.append({"kind": "hazard", "text": _render(tpl, slots), "ht": ht,
                        "site_object": site_object, "tpl": tpl, "slots": slots})
    return records


def _split_continuation(text):
    """把一条记录拆成两行（检验解析器多行合并）；避免在 ASCII 词中间断开。"""
    if "，" in text and text.index("，") < len(text) - 1:
        p = text.index("，") + 1
    else:
        p = max(1, len(text) // 2)
        while p < len(text) - 1 and text[p - 1].isascii() and text[p - 1].isalnum() \
                and text[p].isascii() and text[p].isalnum():
            p += 1
    return text[:p], text[p:]


def write_scenario(out_text, out_gold, spec, records, seed):
    """写样例 txt + gold JSON v2。记录序号 = 解析器口径（1 起，标题行不计）。"""
    lines = [HEADER]
    gold_records = []
    for i, rec in enumerate(records):
        ts = _surface_ts(i % 4, 21 + i % 5, 8 * 60 + 30 + i * 23)
        text = rec["text"]
        if rec["kind"] == "hazard" and i % 9 == 5:
            head, tail = _split_continuation(text)
            lines.append("[%s] %s" % (ts, head))
            lines.append("    " + tail)
        else:
            lines.append("[%s] %s" % (ts, text))
        if rec["kind"] == "hazard":
            gold_records.append({
                "index": i + 1,
                "quote": text,
                "hazard_type_id": rec["ht"]["id"],
                "hazard_type": rec["ht"]["name"],
                "category": rec["ht"]["category"],
                "site_object": rec["site_object"],
                "expected_level": rec["ht"]["base_level"],
            })
    Path(out_text).parent.mkdir(parents=True, exist_ok=True)
    Path(out_gold).parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_text), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(str(out_gold), "w", encoding="utf-8") as f:
        json.dump({"file": spec["file"], "seed": seed, "corpus": "v2",
                   "records": gold_records}, f, ensure_ascii=False, indent=2)
    return len(gold_records)


def _build_paired(spec, pspec, rng, schema, force=False):
    """同项目"施工日志版 vs 巡查记录版"配对语料：巡查版注入已知差异。

    差异三类（写入 gold 差异清单）：漏项 missing / 数值不一致 value / 多报 extra。
    两版按同一事件序列生成（时间戳一一对应），巡查版换表面时间格式与行文前缀。
    """
    log_path = config.repo_path("data", "eval", "cases", pspec["log"])
    patrol_path = config.repo_path("data", "eval", "cases", pspec["patrol"])
    gold_path = config.repo_path("data", "eval", "cases", pspec["gold"])
    if not force and _paired_uptodate(gold_path):
        return "exists"

    types = [ht for ht in schema["hazard_types"] if ht["category"] == spec["category"] and ht["id"] in TEMPLATES]
    events = []
    minute = 8 * 60 + 30
    hazard_i = 0
    for r in range(3):
        for ti, ht in enumerate(types):
            if hazard_i % 4 == 3:
                events.append({"kind": "benign", "minutes": minute,
                               "text": rng.choice(BENIGN)})
                minute += 23
            hazard_i += 1
            variants = TEMPLATES[ht["id"]]
            tpl, site_object = variants[(ti + r * 2) % len(variants)]
            slots = _make_slots(rng)
            events.append({"kind": "hazard", "tpl": tpl, "slots": slots, "ht": ht,
                           "site_object": site_object, "minutes": minute,
                           "text": _render(tpl, slots)})
            minute += 23

    value_candidates = [e for e in events
                        if e["kind"] == "hazard" and "{n}" in e["tpl"]]
    rng.shuffle(value_candidates)
    value_events = value_candidates[:2]
    if len(value_events) < 2:
        raise AssertionError("配对语料数值差异候选不足: %s" % spec["category"])
    remaining = [e for e in events if e["kind"] == "hazard" and e not in value_events]
    missing_event = rng.choice(remaining)

    ht_extra = types[rng.randrange(len(types))]
    tpl_extra, so_extra = TEMPLATES[ht_extra["id"]][
        rng.randrange(len(TEMPLATES[ht_extra["id"]]))]
    extra_slots = _make_slots(rng)
    extra_event = {"kind": "hazard", "tpl": tpl_extra, "slots": extra_slots,
                   "ht": ht_extra, "site_object": so_extra, "minutes": minute,
                   "text": _render(tpl_extra, extra_slots)}

    patrol_events = [e for e in events if e is not missing_event]
    patrol_n = {id(e): rng.choice([x for x in NUMBERS if x != e["slots"]["n"]])
                for e in value_events}
    log_records = [{"kind": e["kind"], "text": e["text"], "ht": e.get("ht"),
                    "site_object": e.get("site_object", ""), "minutes": e["minutes"],
                    "tpl": e.get("tpl", ""), "slots": e.get("slots", {})}
                   for e in events]
    patrol_records = []
    for e in patrol_events:
        if e in value_events:
            slots = dict(e["slots"])
            slots["n"] = patrol_n[id(e)]
            patrol_records.append({"kind": "hazard", "text": _render(e["tpl"], slots),
                                   "ht": e["ht"], "site_object": e["site_object"],
                                   "minutes": e["minutes"],
                                   "tpl": e["tpl"], "slots": slots})
        else:
            patrol_records.append({"kind": e["kind"], "text": e["text"],
                                   "ht": e.get("ht"),
                                   "site_object": e.get("site_object", ""),
                                   "minutes": e["minutes"],
                                   "tpl": e.get("tpl", ""),
                                   "slots": e.get("slots", {})})
    patrol_records.append({"kind": "hazard", "text": extra_event["text"],
                           "ht": extra_event["ht"],
                           "site_object": extra_event["site_object"],
                           "minutes": extra_event["minutes"],
                           "tpl": extra_event["tpl"], "slots": extra_event["slots"]})
    _self_check(log_records, schema)
    _self_check(patrol_records, schema)

    def _iso(minutes):
        return "%s %02d:%02d" % (PAIRED_DATE, minutes // 60 % 24, minutes % 60)

    def _cn(minutes):
        return "2026年09月21日 %02d:%02d" % (minutes // 60 % 24, minutes % 60)

    log_lines = [HEADER_LOG]
    for rec in log_records:
        log_lines.append("[%s] %s" % (_iso(rec["minutes"]), rec["text"]))
    patrol_lines = [HEADER_PATROL]
    for rec in patrol_records:
        prefix = "日常巡查：" if rec["kind"] == "benign" else "巡查发现："
        patrol_lines.append("[%s] %s%s" % (_cn(rec["minutes"]), prefix, rec["text"]))

    log_index = {id(e): i + 1 for i, e in enumerate(events)}
    patrol_index = {id(e): i + 1 for i, e in enumerate(patrol_events)}
    diffs = [{
        "kind": "missing", "label": "漏项",
        "timestamp": _canon_ts(missing_event["minutes"]),
        "index_in_log": log_index[id(missing_event)], "index_in_patrol": None,
        "log_quote": missing_event["text"], "patrol_quote": None,
    }]
    for e in value_events:
        n2 = patrol_n[id(e)]
        diffs.append({
            "kind": "value", "label": "数值不一致", "field": "quantity",
            "timestamp": _canon_ts(e["minutes"]),
            "index_in_log": log_index[id(e)], "index_in_patrol": patrol_index[id(e)],
            "log_quote": e["text"],
            "patrol_quote": _render(e["tpl"], dict(e["slots"], n=n2)),
            "log_value": e["slots"]["n"], "patrol_value": n2,
        })
    diffs.append({
        "kind": "extra", "label": "多报",
        "timestamp": _canon_ts(extra_event["minutes"]),
        "index_in_log": None, "index_in_patrol": len(patrol_events) + 1,
        "log_quote": None, "patrol_quote": extra_event["text"],
    })

    for path, lines in ((log_path, log_lines), (patrol_path, patrol_lines)):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    with open(str(gold_path), "w", encoding="utf-8") as f:
        json.dump({
            "project": "样例住宅楼二期工程", "date": PAIRED_DATE,
            "log": pspec["log"], "patrol": pspec["patrol"], "version": 2,
            "note": "巡查记录版相对施工日志版注入已知差异：missing=漏项 / "
                    "value=数值不一致 / extra=多报；timestamp 为规范化时间。",
            "diffs": diffs,
        }, f, ensure_ascii=False, indent=2)
    return len(diffs)


def _scenario_uptodate(txt, gold):
    if not (txt.exists() and gold.exists()):
        return False
    try:
        data = config.load_json(gold)
    except (ValueError, OSError):
        return False
    return data.get("corpus") == "v2"


def _paired_uptodate(gold_path):
    if not gold_path.exists():
        return False
    try:
        data = config.load_json(gold_path)
    except (ValueError, OSError):
        return False
    return data.get("version") == 2


def generate_all(force=False, seed=DEFAULT_SEED):
    """生成全部场景样例 + 真值 + 配对语料。

    force=False 时产物已存在且语料版本为当前版本则跳过（幂等）；
    旧版本语料视为过期自动重生成，避免评测跑在失配语料上。
    """
    schema = config.load_schema()
    rng = random.Random(seed)
    made = {}
    for key, spec in SCENARIOS.items():
        txt = config.repo_path("data", "samples", "text", spec["file"])
        gold = config.repo_path("data", "eval", "gold",
                                spec["file"].replace(".txt", ".gold.json"))
        if not force and _scenario_uptodate(txt, gold):
            made[key] = "exists"
            continue
        records = generate_scenario(spec, rng)
        _self_check(records, schema)
        made[key] = write_scenario(txt, gold, spec, records, seed)
    for key, pspec in PAIRED.items():
        made["paired_" + key] = _build_paired(SCENARIOS[key], pspec, rng, schema,
                                              force=force)
    return made


if __name__ == "__main__":
    print(json.dumps(generate_all(force=True), ensure_ascii=False))
