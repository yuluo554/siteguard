# -*- coding: utf-8 -*-
"""serve 真实进程演示（M5 验收门"CLI + Web ≥2 场景真实演示"）。

启动真实 uvicorn 进程（py -m siteguard.cli serve），经真实 HTTP socket：
上传高处作业 + 临时用电两场景日志 → 研判 → 校验隐患卡片与下载三格式 → 停服。
全部断言通过打印 SERVE_LIVE_DEMO_OK；任何失败非零退出。
"""
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
PORT = 8137
BASE = "http://127.0.0.1:%d" % PORT


def wait_ready(deadline_s=40):
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            r = requests.get(BASE + "/api/health", timeout=2)
            if r.status_code == 200 and r.json().get("ok"):
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def main():
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-B", "-m", "siteguard.cli", "serve",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        assert wait_ready(), "serve 未在期限内就绪（见上方服务输出）"
        print("① 服务就绪：%s（真实 uvicorn 进程）" % BASE)

        scen = requests.get(BASE + "/api/scenarios", timeout=5).json()
        assert [x["key"] for x in scen] == ["gczy", "lsyd"], scen
        print("② 场景清单：%s" % "、".join("%s=%s" % (x["key"], x["name"]) for x in scen))

        for key in ("gczy", "lsyd"):
            sample = BASE.replace("http://", "")  # noqa: 占位说明用
            path = REPO / "data" / "samples" / "text" / ("demo_%s.txt" % key)
            with open(str(path), "rb") as f:
                r = requests.post(BASE + "/api/analyze",
                                  files={"file": (path.name, f)}, timeout=60)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["hazard_count"] == 54, (key, body["hazard_count"])
            levels = {}
            for card in body["cards"]:
                lv = card["judgment"]["risk_level"]
                levels[lv] = levels.get(lv, 0) + 1
            print("③ 场景[%s] 上传→研判：隐患 %d 条，等级分布 %s"
                  % (key, body["hazard_count"], levels))
            rid = body["report_id"]
            for fmt, min_len in (("json", 1000), ("md", 1000), ("docx", 5000)):
                d = requests.get("%s/api/report/%s/%s" % (BASE, rid, fmt), timeout=30)
                assert d.status_code == 200 and len(d.content) >= min_len, (fmt, len(d.content))
            print("   下载三格式 OK：JSON / Markdown / Word（含签署栏）")
            first = body["cards"][0]
            print("   首条卡片：[%s] %s → %s"
                  % (first["judgment"]["risk_level"], first["quote"][:30],
                     first["judgment"]["hazard_type"]))

        page = requests.get(BASE + "/", timeout=5).text
        assert "SiteGuard" in page and "http://" not in page and "https://" not in page
        print("④ 面板页面零外链 CDN，断网可演示")
        print("SERVE_LIVE_DEMO_OK 两场景真实演示通过")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
