"""KG 可视化与导出。

- export_stats / export_graph_json：零依赖 JSON 导出（统计 / 全图）。
- export_html：pyvis 离线交互 HTML（M3）——
  * 资源全部内嵌（cdn_resources="in_line"），单文件离线可开，禁外链 CDN；
  * 节点按类型着色定型，HazardType 放大突出；
  * 点击 HazardType 节点高亮一跳邻居（其余隐藏，点空白恢复）；
  * 按 Category / RiskLevel 下拉过滤（RiskLevel/Category 主干恒显）；
  * 悬浮显示节点属性，Regulation 节点显示条文原文；
  * 支持 kg.html#<encodeURIComponent(节点id)> 锚点定位（研判报告条款跳转，
    见 kg/anchors.py）。
- 缺 pyvis 依赖或生成失败：优雅降级导出 JSON 统计 + 安装提示，不崩溃。
"""

import html as _html
import json
import re
from pathlib import Path

TARGET_MIN_NODES = 100
INSTALL_HINT = ("缺 pyvis 依赖，KG 可视化已降级为 JSON 导出；安装："
                "pip install pyvis -i https://pypi.tuna.tsinghua.edu.cn/simple")

# pyvis 0.3.2 模板在 cdn_resources="in_line" 下仍残留 bootstrap CDN 外链标签；
# 生成后统一剔除（空的 <script src=...></script> 与 <link href=...>），保证单文件离线。
_EXTERNAL_TAG_RE = re.compile(
    r'<script\b[^>]*\bsrc="https?://[^"]*"[^>]*>\s*</script\s*>'
    r'|<link\b[^>]*\bhref="https?://[^"]*"[^>]*/?>',
    re.IGNORECASE)


def _strip_external_links(page):
    """剔除模板残留的 CDN 外链标签，保证 kg.html 单文件离线可开。"""
    return _EXTERNAL_TAG_RE.sub("<!-- siteguard: external resource stripped -->", page)

_STYLE = {
    "HazardType": ("box", 16, "#e74c3c"),
    "Regulation": ("dot", 8, "#2f7fc1"),
    "Measure": ("dot", 8, "#27ae60"),
    "Case": ("diamond", 12, "#8e44ad"),
    "RiskLevel": ("star", 14, "#f39c12"),
    "Category": ("ellipse", 12, "#16a085"),
    "WorkType": ("triangle", 10, "#7f8c8d"),
    "SiteObject": ("dot", 6, "#95a5a6"),
}


def _node_title(node):
    parts = ["<b>%s</b>" % _html.escape(node.get("label", ""))]
    if node.get("type"):
        parts.append("类型：%s" % _html.escape(node["type"]))
    for k in ("base_level", "risk_level", "category"):
        if node.get(k):
            parts.append("%s：%s" % (k, _html.escape(node[k])))
    if node.get("text"):
        parts.append("条文原文：%s" % _html.escape(node["text"]))
    return "<br>".join(parts)


def _node_meta(graph):
    nodes_meta = {}
    for nid, node in graph._nodes.items():
        m = {"t": node.get("type", "")}
        if m["t"] == "HazardType":
            m["cat"] = node.get("category", "")
            m["lv"] = node.get("base_level", "")
        nodes_meta[nid] = m
    adj = dict((nid, []) for nid in graph._nodes)
    for e in graph._edges.values():
        adj.setdefault(e["src"], []).append(e["dst"])
        adj.setdefault(e["dst"], []).append(e["src"])
    return {"nodes": nodes_meta, "adj": adj}


_JS_TEMPLATE = """<script id="siteguard-kg-enhance" type="text/javascript">
(function () {
  try {
    if (typeof network === "undefined" || typeof nodes === "undefined" || !network) return;
    var META = __SITEGUARD_META__;
    var selCat = null, selLv = null, dimmed = false;

    function visibleOf(m) {
      if (m.t !== "HazardType") return null;
      return (!selCat || m.cat === selCat) && (!selLv || m.lv === selLv);
    }
    function applyFilter() {
      dimmed = false;
      var showHt = {};
      Object.keys(META.nodes).forEach(function (id) {
        var v = visibleOf(META.nodes[id]);
        if (v !== null) showHt[id] = v;
      });
      var upd = [];
      Object.keys(META.nodes).forEach(function (id) {
        var m = META.nodes[id];
        var show = true;
        if (m.t === "HazardType") show = showHt[id];
        else if (m.t !== "RiskLevel" && m.t !== "Category") {
          show = (META.adj[id] || []).some(function (nb) { return showHt[nb]; });
        }
        upd.push({ id: id, hidden: !show });
      });
      nodes.update(upd);
    }
    function highlightOneHop(id) {
      dimmed = true;
      var keep = {};
      keep[id] = true;
      (META.adj[id] || []).forEach(function (nb) { keep[nb] = true; });
      var upd = [];
      Object.keys(META.nodes).forEach(function (nid) {
        var m = META.nodes[nid];
        if (m.t === "RiskLevel" || m.t === "Category") return;
        upd.push({ id: nid, hidden: !keep[nid] });
      });
      nodes.update(upd);
    }
    function resetView() {
      selCat = null; selLv = null; dimmed = false;
      var upd = [];
      Object.keys(META.nodes).forEach(function (id) { upd.push({ id: id, hidden: false }); });
      nodes.update(upd);
      network.fit();
    }
    var bar = document.createElement("div");
    bar.style.cssText = "padding:6px 10px;font:13px/1.6 'Microsoft YaHei',sans-serif;"
      + "background:#f5f7fa;border-bottom:1px solid #dde3ea;";
    var catOpts = [], lvOpts = [];
    Object.keys(META.nodes).forEach(function (id) {
      var m = META.nodes[id];
      if (m.t === "HazardType") {
        if (m.cat && catOpts.indexOf(m.cat) < 0) catOpts.push(m.cat);
        if (m.lv && lvOpts.indexOf(m.lv) < 0) lvOpts.push(m.lv);
      }
    });
    function mkSel(placeholder, arr, cb) {
      var s = document.createElement("select");
      s.style.margin = "0 8px";
      var o = document.createElement("option");
      o.value = ""; o.textContent = placeholder;
      s.appendChild(o);
      arr.sort().forEach(function (v) {
        var x = document.createElement("option");
        x.value = v; x.textContent = v;
        s.appendChild(x);
      });
      s.onchange = function () { cb(s.value); applyFilter(); };
      return s;
    }
    bar.appendChild(document.createTextNode("\\u5206\\u7c7b\\u8fc7\\u6ee4\\uff1a"));
    bar.appendChild(mkSel("\\u5168\\u90e8\\u7c7b\\u522b", catOpts, function (v) { selCat = v || null; }));
    bar.appendChild(document.createTextNode("\\u98ce\\u9669\\u7b49\\u7ea7\\uff1a"));
    bar.appendChild(mkSel("\\u5168\\u90e8\\u7b49\\u7ea7", lvOpts, function (v) { selLv = v || null; }));
    var btn = document.createElement("button");
    btn.textContent = "\\u91cd\\u7f6e\\u89c6\\u56fe";
    btn.style.marginLeft = "10px";
    btn.onclick = resetView;
    bar.appendChild(btn);
    var hint = document.createElement("span");
    hint.style.cssText = "color:#888;margin-left:10px;";
    hint.textContent = "\\u70b9\\u51fb\\u7ea2\\u8272\\u9690\\u60a3\\u7c7b\\u578b\\u8282\\u70b9\\u9ad8\\u4eae\\u4e00\\u8df3\\u90bb\\u5c45\\uff1b\\u70b9\\u51fb\\u7a7a\\u767d\\u5904\\u6062\\u590d";
    bar.appendChild(hint);
    var box = document.getElementById("mynetwork");
    if (box && box.parentNode) box.parentNode.insertBefore(bar, box);

    network.on("click", function (params) {
      if (params.nodes.length === 0) {
        if (dimmed) {
          if (selCat || selLv) applyFilter(); else resetView();
        }
        return;
      }
      var m = META.nodes[params.nodes[0]];
      if (m && m.t === "HazardType") highlightOneHop(params.nodes[0]);
    });

    var h = window.location.hash
      ? decodeURIComponent(window.location.hash.slice(1)) : "";
    if (h && META.nodes[h]) {
      setTimeout(function () {
        try {
          network.focus(h, { scale: 1.3, animation: true });
          nodes.update([{ id: h, borderWidth: 4,
                          color: { border: "#ff9800" }, font: { size: 18 } }]);
        } catch (e) {}
      }, 400);
    }
  } catch (e) { /* 增强失败不影响基础图展示 */ }
})();
</script>"""


def _render_pyvis_html(graph):
    from pyvis.network import Network

    net = Network(height="780px", width="100%", bgcolor="#ffffff",
                  font_color="#333333", notebook=False,
                  heading="SiteGuard 施工现场安全知识图谱",
                  cdn_resources="in_line")
    for nid, node in graph._nodes.items():
        shape, size, color = _STYLE.get(node.get("type", ""), ("dot", 7, "#888888"))
        net.add_node(nid, label=node.get("label", nid), title=_node_title(node),
                     shape=shape, size=size, color=color, font={"size": 12})
    for e in graph._edges.values():
        net.add_edge(e["src"], e["dst"], title=e["relation"], arrows="to")
    page = net.generate_html(notebook=False)
    meta_json = json.dumps(_node_meta(graph), ensure_ascii=False).replace("</", "<\\/")
    script = _JS_TEMPLATE.replace("__SITEGUARD_META__", meta_json)
    page = page.replace("</body>", script + "\n</body>")
    return _strip_external_links(page)


def _write_fallback(graph, out_path, hint):
    fb = out_path.parent / (out_path.stem + ".fallback.json")
    payload = {"ok": False, "stats": graph.stats(),
               "target_min_nodes": TARGET_MIN_NODES,
               "note": "pyvis 可视化不可用，已降级导出 JSON 统计（不崩溃）",
               "install_hint": hint}
    with open(str(fb), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"ok": False, "fallback": str(fb), "hint": hint}


def export_stats(graph, out_path):
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stats": graph.stats(), "target_min_nodes": TARGET_MIN_NODES,
               "note": "种子图谱（M3）：185 节点，pyvis 离线交互 HTML 由 build-kg 同步产出"}
    with open(str(p), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def export_graph_json(graph, out_path):
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "w", encoding="utf-8") as f:
        json.dump(graph.to_dict(), f, ensure_ascii=False, indent=2)


def export_html(graph, out_path, pyvis_mod=None):
    """pyvis 离线交互 HTML 导出。

    pyvis_mod：None=自动导入；False=模拟缺依赖（测试降级路径）；模块对象=直接使用。
    成功返回 {"ok": True, "path", "nodes", "edges"}；
    缺依赖/生成失败降级返回 {"ok": False, "fallback", "hint"}，同时写 <stem>.fallback.json。
    """
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    mod = pyvis_mod
    if mod is None:
        try:
            import pyvis as mod
        except ImportError:
            mod = False
    if mod is False:
        return _write_fallback(graph, p, INSTALL_HINT)
    try:
        page = _render_pyvis_html(graph)
    except Exception as exc:  # 生成失败不崩溃：降级并留因
        return _write_fallback(graph, p, INSTALL_HINT + "；本次生成失败：%s" % exc)
    with open(str(p), "w", encoding="utf-8") as f:
        f.write(page)
    return {"ok": True, "path": str(p),
            "nodes": graph.node_count(), "edges": graph.edge_count()}
