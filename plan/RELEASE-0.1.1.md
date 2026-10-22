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
| **D8**（本批新增） | P1 | **诊断报告里没有、由 CI + 实装探活逼出来**：`pyproject` 只声明 `packages`，仓库根的 `data/`/`webapp/`/`config/` 进不了 wheel → 装出来的包能 import、`/api/health` 也活着，但 `eval` 抛 `FileNotFoundError`、面板首页 500 | `[tool.setuptools.data-files]` 把 24 个资产装到 `<prefix>/share/siteguard/`；`config` 按用途分层（`asset_path` 只读资产回落 share / `out_path` 可写产物落 CWD / `data_path` 两级查找）；`repo_path` 保留为别名；新增 7 项装态契约测试 + CI `packaging` 腿（非 editable 真装 + 中性 CWD 端到端）。细节见 §四·4.2 |
| **D9**（本批新增） | P1 | 同上来源：文件名穿越清洗用 `Path(name).name`，**POSIX 上 `\` 不是分隔符** → 防穿越在 Linux/macOS 静默失效（Windows 上恰好有效，故 `v0.1.0` 未暴露） | 抽出 `_clean_filename()` 按 `[\\/]` 同时切分；新增 2 条跨平台回归测试。细节见 §四·4.2 |

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

（本节在打完 tag 后追加，如实记录 tag 之后才发现/发生的事。）

### 4.1 tag 时点

- tag `v0.1.1`（annotated）→ 剥离后指向 `1881dfaaab09b3ae7ea6355fe0fbfa169ded5e8c`
- 该提交就是 CI 全绿的那个提交：run `39704057452`（5 job 全 success）
- 与 `v0.1.0`（`8355584`）的关系：3 个提交（`4089fad` / `ef0d524` / `1881dfa`）

### 4.2 tag 之前就发生、但不属于原计划的两次修复（都是 CI/实装自己抓出来的）

原提示词的批次 1–4 里**没有**这两条，它们是做完之后被门禁/实装实测逼出来的：

1. **`ef0d524`：文件名穿越清洗在 POSIX 上失效**
   CI 第一次跑（run `39702353643`）的 Linux 腿红了一条：`Path(name).name` 在 POSIX
   上不把 `\` 当分隔符，`..\..\evil\demo_gczy.txt` 原样保留。这在 Windows 上
   恰好有效，所以 `v0.1.0` 一年没暴露。改为按 `[\/]` 同时切分，+2 条回归测试。
   **注意**：这不是我改坏的，是既有缺陷被新 CI 抓到——正好印证 D2「没有 CI 就没人发现」。

2. **`1881dfa`：DEC2=B 引出的「装完不能用」（记为 D8）**
   决定附 wheel 后实测：wheel 里**零资产**（`data/`/`webapp/`/`config/` 都在仓库根，
   `package-data` 收不到）。装出来的包能 import、`/api/health` 也活着，但
   `eval` 抛 `FileNotFoundError`、面板首页 500 —— **比装不上更坑**。
   按用户拍板「A 真修」：新增 `data-files`（24 个资产）+ `config` 按用途分层
   （`asset_path` 只读资产回落 share / `out_path` 可写产物落 CWD）+ 7 项装态契约测试
   + CI 新增 packaging 腿（非 editable 真装）。
   若不修，本版 Release 的两个附件会是"看起来装好了但用不了"的产物。

### 4.3 发布物与三方 sha256 对撞

附件来自 **tag 树重新构建**（`git clone --branch v0.1.1` → `python -m build`），不是本地工作树：

| 文件 | 字节 | sha256（本地 = SHA256SUMS = GitHub digest） |
|---|---|---|
| `siteguard_safety-0.1.1-py3-none-any.whl` | 305 292 | `03f7e3d66c39a51a59d586b8af23a8ea53ab8b73d01b24881ad4d034cdb7adde` |
| `siteguard_safety-0.1.1.tar.gz` | 313 105 | `a0bc6713fde5e9f85fe08db18747ca8e4d241816a294b75796faf7a829612bb0` |
| `SHA256SUMS` | 202 | `461e3de5ec7f7c9002f828bffe70bb4dc70b4ace4ea25cafe161bfb681723b26` |

真下载复验（`curl` Release 附件 → `cmp` 本地 → `sha256sum -c`）：**两个附件均 IDENTICAL / OK**。

### 4.4 从下载件装完能用（对外用户视角，实测）

干净 venv（系统 Python 3.12.10）→ `pip install <下载的 whl>[llm,doc,kg,web]` → 中性 CWD：

| 命令 | 结果 |
|---|---|
| `siteguard version` | `SiteGuard v0.1.1`，rc=0 |
| `siteguard eval` | F1=1.0000（category/site_object/…）：**达标**，rc=0 |
| `siteguard demo` / `build-kg` | rc=0 / rc=0，产物落 CWD 的 `examples/` |
| 面板 `/` `/static/app.js` `/api/health` `/api/scenarios` `/api/sample/gczy` | 全 200 |
| `POST /api/analyze` | `hazard_count=54`，三格式下载齐全 |
| site-packages 产物污染 | **0**（`find` 无命中） |

sdist 同样验过：`pip install <下载的 tar.gz>[llm,doc,kg,web]` → `version`/`eval`/`build-kg` 全 rc=0。

### 4.5 本版 CI 最终留痕

- run `39704057452`（push `1881dfa`）：`core-only` / `full-extras`×2 / `packaging`×2 = **5 job 全 success**
- 注解：3 条 `ubuntu-latest → Ubuntu 26` 迁移提示（GitHub 平台公告），**Node20 弃用告警 0 条**
- 前两次 run 如实留痕：`39702353643` failure（抓到跨平台缺陷）、`39702910942` success
- run `39704705047`（push `00af704`，本文件的 tag 后补充）：同样 **5 job 全 success**

### 4.6 tag 之后还有一个纯文档提交（如实披露）

打 tag 后，本文件（`plan/RELEASE-0.1.1.md`）需要补写 §四「tag 后事实」，于是多出：

| 项 | 值 |
|---|---|
| `v0.1.1..HEAD` | **恰好 1 个提交**：`00af704`（只改 `plan/RELEASE-0.1.1.md`，+61/−1 行） |
| 是否含代码/资产改动 | **否**（`git diff --stat v0.1.1..HEAD` 只有这一个文件） |
| 该文件是否在发布物里 | **否**（实测：wheel 里无 `plan/`；sdist 里 `plan/` 条目数 = **0**） |
| 结论 | **已发布的两个附件仍然是 tag 树 `1881dfa` 的完整代码**，不含也不需要这个文档提交 |

**为什么不把 tag 挪到 `00af704`**：挪了之后附件就不再是"从 tag 树构建"的产物
（setuptools 构建非字节可复现，重建会改变 sha256，导致已发布的三方对撞失效）。
两害相权，保留 tag = 代码提交、并把「1 个纯文档提交的滞后」写进本表，是更能被复验的口径。

复验方若要确认，跑这两条即可：

```bash
git -C <repo> log --oneline v0.1.1..HEAD          # → 只有 00af704
git -C <repo> diff --stat v0.1.1..HEAD            # → 只有 plan/RELEASE-0.1.1.md
```

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
