# RELEASE 0.1.1（维护版）

> 起点：`v0.1.0` = `83555845faff55225d7808e930ae93ffa9fceb91`（2026-09-28，单提交）
> 本版性质：**维护版**（修 P1 缺陷 + 补 CI + 自述前置条件），不改判定逻辑与评测资产。

## 一、决策记录（用户拍板，2026-10-22）

| 编号 | 决策点 | 选定 | 理由 |
| --- | --- | --- | --- |
| **DEC1** | Python floor | **B：抬到 `>=3.12`** | 本仓没有任何依赖把 floor 卡在 3.8（核心零依赖、extras 全是 `>=` 下限），3.8 已于 2024-10 EOL，纯负担；与同组仓口径统一，CI 更省。README 原「本机 3.8.8 实测」改为一次性历史记录表述。 |
| **DEC2** | Release 附件 | **B：附 sdist + wheel** | 纯 Python 包、`pyproject.toml` 完整，sdist/wheel 是最自然的交付物；这正是 D1 会被外部用户撞到的渠道，附 wheel 后同时验「从 wheel 装 `[web]` 能否起面板」。 |

## 二、修了什么（缺陷编号对齐 `update/00-诊断报告.md`）

| 编号 | 级别 | 问题 | 处理 |
| --- | --- | --- | --- |
| **D1** | P1 | `web` extra 漏 `python-multipart`，而 `serverapp.py` 用了 `fastapi.File`/`fastapi.Form` → `create_app()` 阶段抛 `RuntimeError`，照 README 装 `[web]` 得到起不来的面板 | `pyproject.toml` 的 `web` 补 `python-multipart>=0.0.5`；README 装法由手工列举改为 `pip install -e ".[web]"`；`INSTALL_HINT` 同步补 httpx/python-multipart；新增静态契约测试 `tests/test_extras_contract.py`；CI 在干净环境真跑 `create_app()` |
| **D2** | P1 | 完全没有 CI | 新建 `.github/workflows/ci.yml`：**core-only**（零依赖断言 + 归因门禁 + 产物字节一致）+ **full-extras**（ubuntu/windows × 3.12，全量测试 + eval 门 + 脱敏审查 + D1 回归探针） |
| **D3** | P2 | README 称 134 项全绿但没说要装哪些 extra；手工装法还漏 `httpx` | README/docs 全部计数行带「装齐 `.[llm,doc,kg,web]` 后」前置条件；新增自指守门 `TestReadmeTestCountSelfConsistency`（自述数必须等于实测可发现数） |
| **D4** | P2 | `vision`/`video` 两条通路本轮未验证 | **维持不验证**，在 README「已知限制」如实登记（不声称已交付） |
| **D5** | P2 | `v0.1.0` Release 是 0 附件 | DEC2=B：`v0.1.1` 附 sdist + wheel + SHA256SUMS；`v0.1.0` 的 tag/Release **原样不动** |
| **D7** | P2 | 规范条文只有登记日期，没有「下次复核」 | `data/README.md` 知识库表加「下次复核」列（2027-09-27，年度复核）+ 复核节奏说明；机读字段（`seed_regulations.jsonl` 的 `reviewed_on`/`next_review_due`）**未做**，因与本批纪律「不许改 `data/knowledge/*`」冲突，纪律优先，已记入待办 |

## 三、tag 时点事实（本节在打 tag 前写定，内容不随后续提交变化）

- 起点 `HEAD` = `83555845faff55225d7808e930ae93ffa9fceb91`，`tag v0.1.0` == 该提交（零滞后）
- 起点工作树：仅 `?? update/`（交接物，已在本批第一步加入 `.gitignore`）
- 起点版本：`pyproject.toml` = `0.1.0`，包名 `siteguard-safety`（≠ 仓库名 `siteguard` ≠ 目录名 `09-28-siteguard`）
- 起点测试基线（三档实测，2026-10-22 复验）：
  - 只装核心：`Ran 129` / 3 failures + 3 errors + 3 skipped（unittest 口径）
  - 装 `[llm,doc,kg,web]`（旧声明，无 multipart）：`FAILED (errors=1)` ← D1
  - 补 multipart：`Ran 134` / `OK`
- 本版改后测试基线：**141 项全绿**（装齐 `.[llm,doc,kg,web]`）
- 评测（本版实测，未变）：`F1=1.0000`、`tp=108 fp=0 fn=0`、分级准确率 1.0、
  配对差异 4/4+4/4、端到端 108/108、误报 0/108，`exit 0`
- 确定性：`examples/eval_report.json` 重跑后 `git status` 为空
- 起点 CI：无（`gh api repos/yuluo554/siteguard/actions/workflows --jq .total_count` → 0）
- 起点 Release：`v0.1.0`，0 附件

## 四、tag 后追加事实

（打 tag 之后填写，见文末「执行记录」。）

## 五、验收命令与结果

```bash
# 1. 全量测试（干净 venv，装齐 extras）
python -m unittest discover -s tests -t .
# → Ran 141 tests ... OK   rc=0

# 2. D1 回归：只装 [web] 的干净环境，面板必须能起来
python -c "from siteguard.serverapp import create_app; print(create_app().title)"
# → CREATE_APP_OK SiteGuard Web 面板   rc=0

# 3. 核心腿归因门禁
python -m scripts.ci_core_only_gate --selftest   # → SELFTEST_OK  rc=0
python -m scripts.ci_core_only_gate              # → CORE_ONLY_GATE_OK  rc=0

# 4. 核心零依赖断言
python -m scripts.ci_core_only_gate --assert-core-only-env   # → CORE_ONLY_ENV_OK  rc=0

# 5. eval 门
python -m siteguard.cli eval   # → "达标" + f1=1.0   rc=0

# 6. 脱敏四步
python -m scripts.desensitize_audit   # → DESENSITIZE_AUDIT_OK   rc=0
```

## 六、本版未做（如实登记）

- `vision` / `video` 真实推理通路（D4）：不安装 `ultralytics`/`opencv-python`，不宣称
- Web 面板真实浏览器目检：CI 只到 `TestClient` 级 + `create_app()` 可启动
- `data/knowledge/regulations/seed_regulations.jsonl` 的机读复核字段：与纪律 ⑧ 冲突，未动
- `v0.1.0` 的 tag 与 Release（0 附件）：保持原样
