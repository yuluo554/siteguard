"""视觉通路：图像检测 → 隐患条目卡（多模态加分项，里程碑 M4 接入）。

设计纪律（沿用 M3 kg/visualize.export_html 的可注入依赖范式）：
- ultralytics/torch 只进 pyproject optional 组 ``vision``，本模块 import 期零硬依赖；
  缺依赖 / 坏图 / 禁用（``SITEGUARD_DISABLE_VISION=1``）一律返回空卡列表 + warnings，不崩溃；
- detector / model 均可注入：``detector(image_path) -> list[dict]``（dict 含
  class_name/bbox/confidence，仅供测试与扩展注入）；真实推理只在依赖与权重可用时发生，
  无真实检出不得伪造（fake 检测器仅限测试注入并在测试中标注）；
- 检出类别名 → 受控词表（data/knowledge/seed/hazard_types.json）映射：
  SHWD 的 "head"（未戴帽人头）→ "未佩戴安全帽"（HT-GCZY-007）；
  词表未登记的检出类别 → warning 并丢弃该条（不得硬编码未登记 id）；
- 卡片置信度沿用风险分级引擎的 human_confirm 纪律（confidence < 0.6 → 待人工确认）。

融合（merge_cards）：同 site_object 且同 hazard_type_id 的文本/视觉卡合并为一张：
merged_from 回填双方 extractor、confidence 取高、evidence/attrs 合并保留双方出处；
两侧均有可解析时间（attrs["time"]，HH:MM[:SS]）时再施加时间窗约束（默认 60 分钟，
含边界）；任一侧缺时间不施加。不带视觉输入时原样返回文本卡，通路行为逐位不变。
"""

import os
import re
from pathlib import Path

from .. import config
from . import rules as rules_mod

# 检出类别名 → 受控词表 hazard name（SHWD 标注：helmet=已佩戴安全帽人头，head=未戴帽人头；
# "helmet" 为合规佩戴，不构成隐患，故不进映射）
CLASS_TO_HAZARD = {
    "head": "未佩戴安全帽",
    "no_helmet": "未佩戴安全帽",
    "person_without_helmet": "未佩戴安全帽",
}

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def disable_vision(settings=None):
    """视觉通路总开关：环境变量 SITEGUARD_DISABLE_VISION=1 或 settings["disable_vision"]。"""
    if os.environ.get("SITEGUARD_DISABLE_VISION", "").strip() == "1":
        return True
    return bool((settings or {}).get("disable_vision", False))


def _image_ok(path):
    """图像可用性检查：存在 + 非空 + JPEG/PNG 魔数（stdlib 实现，不依赖 PIL）。"""
    p = Path(path)
    if not p.exists():
        return False, "图像不存在: %s" % p
    try:
        with p.open("rb") as f:
            head = f.read(8)
    except OSError as exc:
        return False, "图像不可读: %s (%s)" % (p, exc)
    if len(head) < 8:
        return False, "图像文件过小或损坏: %s" % p
    if head[:3] == b"\xff\xd8\xff":
        return True, ""
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return True, ""
    return False, "非 JPEG/PNG 图像或文件损坏: %s" % p


def load_model(model=None):
    """加载 ultralytics YOLO 模型（可选依赖，import 期零硬依赖）。

    model：已加载模型实例 / 权重路径 str / None（取环境变量 SITEGUARD_VISION_MODEL）。
    返回 (model_or_None, warnings)；缺依赖 / 未配置权重 / 加载失败一律 (None, warnings)。
    """
    if model is not None and hasattr(model, "predict"):
        return model, []
    weights = str(model) if model is not None else os.environ.get("SITEGUARD_VISION_MODEL", "")
    if not weights:
        return None, ["未配置视觉模型权重（model 参数或 SITEGUARD_VISION_MODEL），视觉通路降级"]
    try:
        from ultralytics import YOLO  # 延迟导入，禁止 import 期硬依赖
    except Exception as exc:
        return None, ["缺 ultralytics 依赖（pyproject vision 组），视觉通路降级: %s" % exc]
    try:
        return YOLO(weights), []
    except Exception as exc:
        return None, ["视觉模型加载失败: %s" % exc]


def _results_to_detections(result, names):
    """ultralytics Results → 统一 detection dict 列表（class_name/bbox/confidence）。"""
    dets = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return dets
    xyxy = boxes.xyxy.tolist() if hasattr(boxes.xyxy, "tolist") else list(boxes.xyxy)
    confs = boxes.conf.tolist() if hasattr(boxes.conf, "tolist") else list(boxes.conf)
    clss = boxes.cls.tolist() if hasattr(boxes.cls, "tolist") else list(boxes.cls)
    for bbox, conf, cls_id in zip(xyxy, confs, clss):
        dets.append({
            "class_name": str(names.get(int(cls_id), cls_id)),
            "bbox": [round(float(x), 1) for x in bbox],
            "confidence": round(float(conf), 4),
        })
    return dets


def _card_from_detection(image_path, index, det, schema):
    """单条检出 → HazardCard（映射受控词表）。返回 (card|None, warning|None)。"""
    class_name = det.get("class_name", "")
    hazard_name = CLASS_TO_HAZARD.get(class_name)
    if hazard_name is None:
        return None, ("检出类别 %r 未登记受控映射，已丢弃（词表缺条目须走受控流程补登记）" % class_name)
    hazard_def = None
    for h in schema.get("hazard_types", []):
        if h.get("name") == hazard_name:
            hazard_def = h
            break
    if hazard_def is None:
        return None, "受控词表缺条目 %r，已丢弃（不得硬编码未登记 id）" % hazard_name
    conf = float(det.get("confidence", 0.0))
    bbox = [float(x) for x in det.get("bbox", [])]
    card = rules_mod.new_card(
        str(image_path), index,
        "图像 %s 检出：%s" % (Path(image_path).name, hazard_name),
        hazard_def, "vision",
        (hazard_def.get("site_objects") or [""])[0],
        conf,
    )
    card["attrs"] = {"bbox": bbox, "detection_class": class_name}
    card["evidence"] = {"image": Path(image_path).name, "bbox": bbox}
    return card, None


def detect(image_path, model=None, detector=None, schema=None):
    """单张图像 → (list[HazardCard], warnings)。

    三路径优雅降级：禁用（SITEGUARD_DISABLE_VISION=1）/ 缺图坏图 / 缺依赖或推理失败，
    均返回空列表 + warnings，不崩溃。detector 注入仅供测试（见模块 docstring）。
    """
    warnings = []
    if disable_vision():
        return [], ["视觉通路已禁用（SITEGUARD_DISABLE_VISION=1）"]
    schema = schema if schema is not None else config.load_schema()
    ok, why = _image_ok(image_path)
    if not ok:
        return [], [why]

    if detector is not None:
        try:
            dets = list(detector(str(image_path)))
        except Exception as exc:
            return [], ["注入检测器执行失败: %s" % exc]
    else:
        model, mw = load_model(model)
        warnings += mw
        if model is None:
            return [], warnings
        try:
            results = model.predict(str(image_path), conf=0.25, verbose=False) or []
            dets = []
            for r in results:
                dets += _results_to_detections(r, getattr(model, "names", {}) or {})
        except Exception as exc:
            return [], warnings + ["视觉推理失败: %s" % exc]

    cards = []
    for i, det in enumerate(dets, 1):
        card, w = _card_from_detection(image_path, i, det, schema)
        if w:
            warnings.append(w)
            continue
        cards.append(card)
    return cards, warnings


def collect_vision_cards(image_paths, schema=None, detector=None, model=None):
    """多张图像逐张 detect，汇总 (cards, warnings)。"""
    all_cards, all_warnings = [], []
    for p in image_paths:
        cards, warns = detect(p, model=model, detector=detector, schema=schema)
        all_cards += cards
        all_warnings += warns
    return all_cards, all_warnings


def _card_minutes(card):
    """卡片 attrs['time']（HH:MM[:SS]）→ 当日分钟数；缺时间或不可解析返回 None。"""
    t = (card.get("attrs") or {}).get("time")
    if not t:
        return None
    m = _TIME_RE.match(str(t).strip())
    if not m:
        return None
    hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return hh * 60 + mm + ss / 60.0


def merge_cards(text_cards, vision_cards, time_window=60):
    """图文融合：同 site_object 且同 hazard_type_id 的文本/视觉卡合并为一张。

    - 两侧均有可解析时间（attrs["time"]，HH:MM[:SS]）时施加时间窗约束
      （|Δ分钟| <= time_window，含边界）；任一侧缺时间不施加；
    - 合并卡：merged_from 回填双方 extractor、confidence 取高、evidence/attrs
      合并保留双方出处（视觉证据收进 evidence["vision"] 列表）；
    - 不同 hazard_type 或不同 site_object 一律不合并；未命中的视觉卡原样保留
      （merged_from=["vision"]），正常合并不产生 warnings；
    - 不带视觉输入（vision_cards 为空）时原样返回 text_cards，行为逐位不变。

    返回 (cards, warnings)。
    """
    if not vision_cards:
        return text_cards, []
    merged = list(text_cards)
    warnings = []
    for v in vision_cards:
        v_time = _card_minutes(v)
        hit = None
        for i, t in enumerate(merged):
            if not t.get("site_object") or t.get("site_object") != v.get("site_object"):
                continue
            if t.get("hazard_type_id") != v.get("hazard_type_id"):
                continue
            t_time = _card_minutes(t)
            if (t_time is not None and v_time is not None
                    and abs(t_time - v_time) > float(time_window)):
                continue
            hit = i
            break
        if hit is None:
            merged.append(v)
            continue
        t = merged[hit]
        fused = dict(t)
        fused["confidence"] = max(float(t.get("confidence", 0.0)), float(v.get("confidence", 0.0)))
        mf = list(t.get("merged_from") or [])
        for x in (v.get("merged_from") or []):
            if x not in mf:
                mf.append(x)
        fused["merged_from"] = mf
        ev = dict(t.get("evidence") or {})
        ev.setdefault("vision", []).append({
            "image": (v.get("evidence") or {}).get("image"),
            "bbox": (v.get("evidence") or {}).get("bbox"),
            "confidence": float(v.get("confidence", 0.0)),
        })
        fused["evidence"] = ev
        attrs = dict(t.get("attrs") or {})
        for k, val in (v.get("attrs") or {}).items():
            if k not in attrs:
                attrs[k] = val
        fused["attrs"] = attrs
        merged[hit] = fused
    return merged, warnings
