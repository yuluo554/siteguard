# KG 构建方法说明（M3 · 图谱与可视化周）

> 本文说明 SiteGuard 施工现场安全知识图谱的建模、装载、实例挂图、可视化与过滤设计，
> 供技术方案文档（M5）的"KG 构建方法"一节引用。
> 代码入口：`siteguard/kg/schema.py`（种子装载）、`siteguard/kg/builder.py`（SimpleGraph）、
> `siteguard/kg/visualize.py`（离线可视化导出）、`siteguard/kg/anchors.py`（报告条款锚点）。

## 1. 建模总览（plan/02 §4）

**节点类型（8 类种子节点 + 1 类运行时实例节点）**

| 节点类型 | 节点 id 规则 | 数据来源 | 实测数量 |
| --- | --- | --- | --- |
| Regulation（规范条文） | `REG:{标准号}#{条款号}` | data/knowledge/regulations/seed_regulations.jsonl | 54 |
| HazardType（隐患类型） | `HT:{id}` | data/knowledge/seed/hazard_types.json | 30 |
| Measure（整改措施） | `MS:{id}` | data/knowledge/seed/measures.json | 28 |
| Case（案例） | `CASE:{case_id}` | data/knowledge/cases/cases.jsonl | 10 |
| SiteObject（部位/设备） | `SO:{名称}` | 词表 site_objects 派生 | 44 |
| WorkType（作业类型） | `WT:{名称}` | 词表 work_type 去重派生 | 7 |
| RiskLevel（风险等级） | `RL:{等级}` | 词表 risk_levels（四级） | 4 |
| Category（隐患大类） | `CAT:{大类}` | 词表 categories（8 大类） | 8 |
| HazardInstance（隐患实例，运行时） | `HI:{card_id}` | 研判产物动态挂图，不计种子预算 | 动态 |

**关系类型（7 种，常量定义于 kg/schema.py）**

| 关系 | 语义 | 方向 | 实测边数 |
| --- | --- | --- | --- |
| 风险分级 | 隐患类型的基础风险档 | HazardType → RiskLevel | 30 |
| 属于 | 隐患类型归属大类 | HazardType → Category | 30 |
| 整改用 | 隐患类型挂整改措施 | HazardType → Measure | 30 |
| 应依据 | 隐患类型挂依据条款 | HazardType → Regulation | 28 |
| 作业类型 | 隐患类型关联作业 | HazardType → WorkType | 30 |
| 发生于 | 部位关联 | HazardType/HazardInstance → SiteObject | 68 |
| 涉及 | 案例涉及隐患类型 | Case → HazardType | 14 |

**实测规模：185 节点 / 230 边**（`py -X utf8 -m siteguard.cli build-kg` 产出
`kg_stats.json`；≥100 节点目标与 M3 预算 ≥150 均达标）。

## 2. 种子装载机制（build_seed_graph）

1. `config.load_schema()` 一次性加载 `data/knowledge/` 五类种子：
   受控词表（hazard_types.json，30 类/8 大类，含 clause_refs/measure_ids/site_objects/
   work_type/base_level/category）、条文块 JSONL（54 条）、措施（28 条）、
   阈值表（7 条）、规则库 v1（52 条）、案例（10 条，脱敏）。
2. `kg/schema.py:build_seed_graph(schema)` 按上表 id 规则装载节点与七种关系边；
   Regulation 节点携带 `text` 属性（条文原文/摘录），供研判引用与可视化悬浮展示。
3. 条文来源纪律：建质规〔2022〕2号 40 条为官方 docx 原文逐字摘录（sha256 与来源链
   登记 data/README.md 查证记录）；JGJ 系列种子为标注"以官方文本为准"的摘录概括，
   未经官方核验的扩充条目不入库（查证失败不编造）。

## 3. 实例挂图机制（attach_instance）

研判流水线（pipeline/runner）对每张隐患条目卡调用
`kg/schema.py:attach_instance(graph, card, judgment)`：

- 生成运行时节点 `HI:{card_id}`（携带 risk_level 属性）；
- 挂边 `HI →实例化→ HT:{hazard_type_id}`、`HI →发生于→ SO:{site_object}`（缺则补建）。

种子图谱保证 ≥100 节点不依赖运行时数据（plan/02 §4 构建方法）；实例挂图只在
研判时向图上累加，不影响种子规模达标结论。

## 4. 规模预算与实测对照（plan/03 §5）

| 节点类型 | 预算 | 实测 | 说明 |
| --- | --- | --- | --- |
| Regulation | ~80 | 54 | JGJ 扩充官方全文通道受限，按查证纪律收窄（见 data/README.md 待核验清单） |
| HazardType | ~30 | 30 | 词表 v2 达成 |
| Measure | ~25 | 28 | 超预算 |
| Case | ~10 | 10 | 达成 |
| SiteObject/WorkType/RiskLevel/Category | ~15 | 63 | 词表派生，超预算 |
| **合计** | **≈160** | **185** | ≥100 节点与 ≥150（M3 预算）均达标 |

## 5. 可视化与过滤设计（kg/visualize.py:export_html，M3 新增）

- **离线单文件**：pyvis `cdn_resources="in_line"` 将 vis.js/vis.css 全文内嵌；
  生成后再经 `_strip_external_links` 剔除 pyvis 0.3.2 模板残留的 bootstrap CDN
  外链标签（实测 2 处），产物 `kg.html` 无任何外链，断网可开（测试硬断言，
  tests/test_m3.py）。
- **节点样式**：按节点类型着色定型，HazardType 放大突出；悬浮（title）显示节点
  属性——Regulation 节点悬浮显示条文原文摘录。
- **点击高亮一跳邻居**：点击 HazardType 节点，隐藏其余节点仅保留其一跳邻居，
  点击空白恢复全图。
- **按 Category/RiskLevel 过滤**：图上方工具条下拉过滤（选项由图数据自动汇总）；
  过滤后仅保留所选大类/等级的 HazardType 及其一跳关联节点，RiskLevel/Category
  主干恒显，避免子图断链；可重置视图。
- **条款锚点定位**：`kg.html#<URL编码节点id>`（如
  `kg.html#REG%3AJGJ%2080-2016%234.1.2`）。页面内嵌增强脚本解析 `location.hash`，
  decodeURIComponent 后 `network.focus` 定位并高亮该节点——研判报告的条款锚点
  即指向此处（见 §6）。
- **缺依赖优雅降级**：pyvis 未安装或生成失败时不崩溃——导出
  `kg.fallback.json`（图谱统计 + 安装提示 `pip install pyvis`），CLI 打印降级说明，
  退出码 0；pyvis_mod 参数可强制模拟缺依赖路径（有测试覆盖）。

## 6. 报告条款锚点联动（kg/anchors.py，M3 新增）

条款引用 → 图节点的映射规则统一定义在 `kg/anchors.py`：

```
kg_node_id(standard, clause) == "REG:{standard}#{clause}"     # 与种子装载规则一致
clause_anchor(standard, clause) == "kg.html#REG%3A...%23..."  # URL 编码（safe=""）
```

`report/export.py` 在导出前调用 `attach_anchors(report)` 为每条 clause_ref 注入
`kg_node`（图节点 id）与 `anchor`（kg.html 锚点链接）字段：JSON 报告携带机器可读
锚点，Markdown 报告"依据条款"列渲染为可点击链接。函数幂等，重复导出不重复注入。
部署约定：报告与 kg.html 同目录（或按部署调整 anchor 前缀）即可点击跳转并自动
定位条款节点。

## 7. 构建与校验命令

```bash
py -X utf8 -m siteguard.cli build-kg        # 产出 examples/kg/{kg.json, kg_stats.json, kg.html}
py -X utf8 -m scripts.verify_seed_data      # 种子数据完整性（JSON/交叉引用/正则/迁移一致性）
py -X utf8 -m unittest discover -s tests    # 78 项测试（含 M3 新增 9 项：可视化/降级/锚点/CLI 产物）
```

## 8. 台账与查证纪律（承接 M2）

条文与数值不确定必须查证官方原文，查证失败不编造、登记台账（data/README.md
查证记录/待核验清单）。M3 轮对 JGJ 扩充条款的官方通道做了两轮直连尝试
（住建部官网栏目均 404），通用搜索无官方直链且摘要与 M2 污染记录一致，不采信；
条文库保持 54 条，扩充留待核验通道恢复（详见 data/README.md M3 查证记录）。
