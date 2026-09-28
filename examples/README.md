# examples/ 演示产物

由固定命令产出并随仓库提交，作为"示例运行结果"演示材料：

- `demo_output/demo_gczy.report.{json,md}` — 高处作业场景研判报告（`demo` 子命令）
- `demo_output/demo_lsyd.report.{json,md}` — 临时用电场景研判报告
- `kg/kg_stats.json`、`kg/kg.json` — 种子知识图谱统计与结构（`build-kg` 子命令）
- `eval_report.json` — 内置基准评测结果（`eval` 子命令；M1 起含字段级 P/R/F1
  与配对语料差异检出结果）

重新生成：`py -X utf8 -m siteguard.cli demo && py -X utf8 -m siteguard.cli build-kg && py -X utf8 -m siteguard.cli eval`
