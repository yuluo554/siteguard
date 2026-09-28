# -*- coding: utf-8 -*-
"""serve HTTP 层冒烟（TestClient）：两场景研判 + 失败路径 + 场景覆盖 + 0 外链。

固定标记词输出 HTTP_SMOKE_OK 表示全部通过；任何断言失败即抛异常退出非零。
"""
from fastapi.testclient import TestClient

from siteguard.serverapp import create_app

app = create_app()
c = TestClient(app)

r = c.get("/")
assert r.status_code == 200 and "SiteGuard" in r.text, r.status_code
r = c.get("/api/scenarios")
assert [x["key"] for x in r.json()] == ["gczy", "lsyd"], r.json()
r = c.get("/api/sample/gczy")
assert r.status_code == 200 and "脚手架" in r.json()["text"], r.status_code

for key, expect in (("gczy", 54), ("lsyd", 54)):
    s = c.get("/api/sample/" + key).json()
    r = c.post("/api/analyze", data={"text": s["text"], "filename": s["filename"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hazard_count"] == expect, (key, body["hazard_count"])
    assert body["source_file"] == s["filename"]
    assert body["downloads"]["docx"], body["downloads"]
    assert all("/" not in card["source"]["file"] or card["source"]["file"] == s["filename"]
               for card in body["cards"])
    r2 = c.get("/api/report/%s/md" % body["report_id"])
    assert r2.status_code == 200 and "研判报告" in r2.text
    r3 = c.get("/api/report/%s/docx" % body["report_id"])
    assert r3.status_code == 200 and len(r3.content) > 5000
    r4 = c.get("/api/report/%s/json" % body["report_id"])
    assert r4.status_code == 200

# 失败路径：坏后缀 400 / 坏 docx 降级警告 / 坏 fmt 404 / 不存在报告 404 / 空内容 400
r = c.post("/api/analyze", data={"text": "x=1", "filename": "evil.exe"})
assert r.status_code == 400, (r.status_code, r.text)
bad = c.post("/api/analyze", files={"file": ("bad.docx", b"not a real docx at all")})
assert bad.status_code == 200 and bad.json()["hazard_count"] == 0, (bad.status_code,)
assert bad.json()["warnings"] and any("docx" in w for w in bad.json()["warnings"])
assert c.get("/api/report/x/xml").status_code == 404
assert c.get("/api/report/no_such/md").status_code == 404
r = c.post("/api/analyze", data={"text": "   "})
assert r.status_code == 400, r.status_code
trav = c.get("/api/report/..%2F..%2Fkg/md")
assert trav.status_code == 404, trav.status_code

# 场景覆盖：--scenario gczy 时 lsyd 样例 404、gczy 可用
app2 = create_app(scenario="gczy")
c2 = TestClient(app2)
assert [x["key"] for x in c2.get("/api/scenarios").json()] == ["gczy"]
assert c2.get("/api/sample/lsyd").status_code == 404
assert c2.get("/api/sample/gczy").status_code == 200

# 静态资源可用 + 页面/脚本/样式 0 外链 CDN
for path, must in (("/static/style.css", "sev-major"), ("/static/app.js", "fetch(")):
    r = c.get(path)
    assert r.status_code == 200 and must in r.text, (path, r.status_code)
    assert "http://" not in r.text and "https://" not in r.text, path
r = c.get("/kg/kg.html")
assert r.status_code == 200
r = c.get("/")
for token in ("http://", "https://"):
    assert token not in r.text.replace('xmlns="http://www.w3.org/2000/svg"', ""), token
print("HTTP_SMOKE_OK 全部通过")
