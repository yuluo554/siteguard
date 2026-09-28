/* SiteGuard Web 面板（M5）：零第三方依赖（免构建 vanilla JS），零外链 CDN。 */
"use strict";

var LEVEL_CLASS = {
  "重大风险": "sev-major",
  "较大风险": "sev-high",
  "一般风险": "sev-medium",
  "低风险": "sev-low"
};

function el(id) {
  return document.getElementById(id);
}

function setStatus(msg) {
  el("status").textContent = msg || "";
}

function loadScenarios() {
  fetch("/api/scenarios").then(function (r) { return r.json(); }).then(function (list) {
    var box = el("scenario-buttons");
    box.innerHTML = "";
    list.forEach(function (s) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ghost";
      btn.textContent = s.name;
      btn.onclick = function () { loadSample(s.key, s.name); };
      box.appendChild(btn);
    });
  }).catch(function () {
    setStatus("场景列表加载失败（服务是否已启动？）");
  });
}

function loadSample(key, name) {
  clearFile();
  fetch("/api/sample/" + key).then(function (r) {
    if (!r.ok) { throw new Error("HTTP " + r.status); }
    return r.json();
  }).then(function (data) {
    el("log-text").value = data.text;
    el("log-text").dataset.filename = data.filename;
    setStatus("已载入示例：" + name + "（" + data.filename + "）");
  }).catch(function () {
    setStatus("示例载入失败：请先运行 py -X utf8 -m siteguard.cli datagen");
  });
}

function clearFile() {
  el("log-text").dataset.filename = "";
  el("file-input").value = "";
}

function analyze() {
  var btn = el("analyze-btn");
  var text = el("log-text").value.trim();
  var file = el("file-input").files[0];
  var form = new FormData();
  if (file) {
    form.append("file", file, file.name);
  } else if (text) {
    form.append("text", text);
    form.append("filename", el("log-text").dataset.filename || "pasted.txt");
  } else {
    setStatus("请先载入示例、粘贴文本或选择文件。");
    return;
  }
  btn.disabled = true;
  setStatus("研判中…（规则抽取 → 条款关联 → 风险分级 → 建议生成）");
  fetch("/api/analyze", { method: "POST", body: form })
    .then(function (r) { return r.json().then(function (data) {
      if (!r.ok) { throw new Error(data.detail || ("HTTP " + r.status)); }
      return data;
    }); })
    .then(function (data) { render(data); })
    .catch(function (err) { setStatus("研判失败：" + err.message); })
    .finally(function () { btn.disabled = false; });
}

function render(data) {
  el("summary").innerHTML = "";
  el("cards").innerHTML = "";
  el("warnings-box").innerHTML = "";
  el("downloads").innerHTML = "";
  el("result-panel").hidden = false;

  var stat = document.createElement("div");
  stat.className = "stat";
  stat.innerHTML = "源文件 <b>" + escapeHtml(data.source_file) + "</b>：记录 " +
    data.record_count + " 条，识别隐患 <b>" + data.hazard_count + "</b> 条，警告 " +
    data.warnings.length + " 条";
  el("summary").appendChild(stat);

  data.cards.forEach(function (card, i) { el("cards").appendChild(renderCard(card, i)); });

  if (data.warnings.length) {
    var box = document.createElement("div");
    box.className = "warnings";
    box.innerHTML = "<h3>警告</h3>";
    data.warnings.forEach(function (w) {
      var p = document.createElement("p");
      p.textContent = w;
      box.appendChild(p);
    });
    el("warnings-box").appendChild(box);
  }

  Object.keys(data.downloads).forEach(function (fmt) {
    var name = data.downloads[fmt];
    var a = document.createElement("a");
    if (name) {
      a.className = "dl";
      a.href = "/api/report/" + encodeURIComponent(data.report_id) + "/" + fmt;
      a.textContent = ({ json: "JSON", md: "Markdown", docx: "Word（含签署栏）" })[fmt];
    } else {
      a.className = "dl disabled";
      a.textContent = "Word（需 python-docx）";
      a.title = "服务端缺 python-docx 依赖，Word 导出不可用";
    }
    el("downloads").appendChild(a);
  });
  setStatus("完成：隐患 " + data.hazard_count + " 条。");
}

function renderCard(card, i) {
  var j = card.judgment || {};
  var div = document.createElement("div");
  var level = j.risk_level || "—";
  div.className = "card " + (LEVEL_CLASS[level] || "sev-low");
  var html = '<div class="card-head"><span class="badge ' +
    (LEVEL_CLASS[level] || "") + '">' + escapeHtml(level) + "</span>" +
    '<span class="htype">' + escapeHtml(card.hazard_type || "") + "</span>" +
    '<span class="meta">' + escapeHtml(card.category || "") +
    (card.site_object ? " · " + escapeHtml(card.site_object) : "") +
    (card.extractor ? " · " + escapeHtml(card.extractor) : "") + "</span></div>" +
    '<p class="quote">「' + escapeHtml(card.quote || "") + "」</p>";
  var refs = (j.clause_refs || []);
  if (refs.length) {
    html += '<p class="clauses">依据条款：';
    html += refs.map(function (r) {
      var label = escapeHtml((r.standard || "") + " " + (r.clause || ""));
      if (r.anchor) {
        return '<a href="/kg/' + escapeHtml(r.anchor) + '" target="_blank" rel="noopener">' +
          label + "</a>";
      }
      return label;
    }).join("、");
    html += "</p>";
  } else {
    html += '<p class="clauses">依据条款：无条款（词表未挂官方核验条款，不编造）</p>';
  }
  var sugg = (j.suggestions || []).map(function (s) { return escapeHtml(s.text || ""); })
    .filter(Boolean).join("；");
  html += '<p class="sugg">整改建议：' + (sugg || "—") + "</p>";
  if (j.human_confirm) {
    html += '<p class="confirm">待人工确认（低置信/兜底产出）</p>';
  }
  div.innerHTML = html;
  return div;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

el("analyze-btn").onclick = analyze;
el("file-input").onchange = function () {
  if (el("file-input").files[0]) {
    el("log-text").value = "";
    el("log-text").dataset.filename = "";
    setStatus("已选择文件：" + el("file-input").files[0].name);
  }
};
loadScenarios();
