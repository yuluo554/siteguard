"""LLM 兜底通路（M2 接入 DashScope OpenAI 兼容接口；默认关闭、失败降级、绝不抛异常）。

接入纪律（plan/02 §3 防幻觉三件套）：
1. 候选行压缩：只送含隐患关键词/数字的行（is_candidate），控制 token 成本与噪声；
2. 摘录子串校验：LLM 返回 quote 不是原文子串即丢弃（validate_llm_item）；
3. 受控词表校验：hazard_type_id 必须映射进词表，category（如携带）必须在受控类别内。

客户端纪律：enable_thinking=false（qwen3 系提速）、max_tokens 截断后 JSON 修复、
超时+指数退避重试、失败整体降级规则通路（返回空列表 + 警告，绝不抛异常中断主流程）。
传输层可注入（transport 参数）以便测试；默认走 urllib（stdlib 零新增依赖）。
API key 只放本地 config/settings.json（已 gitignore）或环境变量，绝不入仓库、绝不写日志。
"""

import json
import os
import re
import time
import urllib.request

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"

# 候选行压缩：只有含这些信号词的行才值得送 LLM（控制 token 成本）
SIGNAL_HINTS = ["未", "缺失", "破损", "违规", "无", "漏", "超", "失效", "隐患", "死亡", "坠落", "触电"]

_SYSTEM_PROMPT = (
    "你是施工现场安全隐患抽取助手。只从用户给出的巡查/日志记录中摘录原文，"
    '输出 JSON 数组：[{"record_index": 记录序号, "quote": "原文逐字摘录", '
    '"hazard_type_id": "词表内的隐患类型ID"}]。'
    "禁止改写、缩写或编造原文；无法判定的记录不要输出；只输出 JSON。")


def is_candidate(text):
    return any(h in text for h in SIGNAL_HINTS)


def _resolve_api_key(llm_cfg):
    """key 只来自本地配置 api_key 或环境变量 api_key_env；缺失返回空串。"""
    key = str(llm_cfg.get("api_key") or "").strip()
    if not key:
        env = str(llm_cfg.get("api_key_env") or "").strip()
        if env:
            key = os.environ.get(env, "").strip()
    return key


def _build_payload(records, llm_cfg):
    lines = ["[%d] %s" % (r["index"], r["text"]) for r in records if is_candidate(r["text"])]
    return {
        "model": llm_cfg.get("model", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines) or "（无候选记录）"},
        ],
        "enable_thinking": bool(llm_cfg.get("enable_thinking", False)),
        "temperature": 0.1,
        "max_tokens": int(llm_cfg.get("max_tokens", 1024)),
    }


def _default_transport(url, payload, headers, timeout):
    """真实 HTTP 通路（urllib stdlib，零第三方依赖）。仅本地配置 key 后使用。"""
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_items(content):
    """从模型回复中提取 JSON 数组（容忍代码围栏与截断）。"""
    match = re.search(r"\[.*\]", content or "", re.S)
    if not match:
        return []
    raw = match.group(0)
    try:
        data = json.loads(raw)
    except ValueError:
        try:
            data = json.loads(fix_json_truncated(raw))
        except ValueError:
            return []
    return data if isinstance(data, list) else []


def extract_cards_llm(records, source_file="<memory>", settings=None,
                      schema=None, transport=None):
    """LLM 兜底抽取。未配置/超时/失败一律降级规则通路（返回空列表+警告，绝不抛异常）。

    真实调用仅在本地配置 api_key 后发生；评测与测试全程关闭 LLM（settings 注入 + transport 注入）。
    """
    settings = settings or {}
    if settings.get("disable_llm", True):
        return [], ["LLM 兜底通路关闭（SITEGUARD_DISABLE_LLM=1），仅规则通路"]
    llm_cfg = settings.get("llm", {}) or {}
    if not llm_cfg.get("enabled") or not _resolve_api_key(llm_cfg):
        return [], ["LLM 未配置（config/settings.json 缺 enabled/api_key 或环境变量未设），降级规则通路"]

    if schema is None:
        from .. import config as config_mod
        schema = config_mod.load_schema()
    full_text = "\n".join(r["text"] for r in records)
    if not any(is_candidate(r["text"]) for r in records):
        return [], ["无候选行（候选行压缩后为空），跳过 LLM 调用"]

    url = str(llm_cfg.get("base_url", DEFAULT_BASE_URL)).rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer %s" % _resolve_api_key(llm_cfg)}
    payload = _build_payload(records, llm_cfg)
    timeout = float(llm_cfg.get("timeout_s", 30))
    retries = int(llm_cfg.get("max_retries", 2))
    transport = transport or _default_transport

    warnings = []
    response = None
    for attempt in range(retries + 1):
        try:
            response = transport(url, payload, headers, timeout)
            break
        except Exception as exc:  # 网络/超时/HTTP 错误：退避重试，最终降级
            warnings.append("LLM 调用失败（第%d次）：%s: %s" % (attempt + 1, type(exc).__name__, exc))
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4.0))
    if response is None:
        warnings.append("LLM 通路不可用，整体降级规则通路")
        return [], warnings

    content = ""
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        warnings.append("LLM 回复结构异常，降级规则通路（%s: %s）" % (type(exc).__name__, exc))
        return [], warnings

    items = _extract_items(content)
    from .rules import new_card
    cards = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not validate_llm_item(item, full_text, schema):
            warnings.append("LLM 候选项未通过校验已丢弃（摘录非原文子串或词表未命中）")
            continue
        record = next((r for r in records if r["index"] == item.get("record_index")), None)
        if record is None or item["quote"] not in record["text"]:
            warnings.append("LLM 候选项定位不到原记录已丢弃（record_index=%s）" % item.get("record_index"))
            continue
        ht_def = schema["hazard_type_by_id"][item["hazard_type_id"]]
        site_object = item.get("site_object") or ""
        if site_object and site_object not in ht_def.get("site_objects", []):
            site_object = ""
        try:
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        cards.append(new_card(source_file, record["index"], record["text"],
                              ht_def, "llm", site_object, confidence))
    warnings.append("LLM 兜底抽取完成：候选 %d 条，通过校验 %d 条" % (len(items), len(cards)))
    return cards, warnings


def validate_llm_item(item, full_text, schema):
    """LLM 输出单条校验：摘录必须是原文子串、词表必须命中、类别（如携带）必须受控。"""
    quote = item.get("quote", "")
    if not quote or quote not in full_text:
        return False
    if item.get("hazard_type_id") not in schema.get("hazard_type_by_id", {}):
        return False
    category = item.get("category")
    if category and category not in schema.get("categories", []):
        return False
    return True


def fix_json_truncated(text):
    """max_tokens 截断后的简单 JSON 修复：截到最后一个完整的中括号项。"""
    text = text.strip()
    if text.endswith("]"):
        return text
    last = text.rfind("}")
    if last != -1:
        return text[: last + 1] + "]"
    return "[]"
